"""Transient provider retry model for the OpenAI Agents runtime."""

from __future__ import annotations

import asyncio
import math
import os
import time
from pathlib import Path
from typing import Any

from roboclaws.agents.drivers.openai_agents_event_log import (
    _append_model_racing_event,
    _append_model_service_event,
    _append_model_service_failure_events,
    _model_racing_arm_id,
    _round_duration,
)
from roboclaws.agents.drivers.openai_agents_event_projection import _usage_summary
from roboclaws.agents.drivers.openai_agents_provider_racing import (
    _get_response_racing_enabled,
    _race_get_response,
)
from roboclaws.agents.drivers.openai_agents_provider_runtime import (
    close_async_resource as _close_async_resource,
)
from roboclaws.agents.drivers.openai_agents_provider_runtime import (
    failure_from_exception as _failure_from_exception,
)
from roboclaws.agents.live_runtime import LiveAgentRequest
from roboclaws.agents.live_status import LiveAgentFailure

try:
    from agents.models.interface import Model as _AgentsModel  # type: ignore[import-not-found]
except ImportError:
    _AgentsModel = object

DEFAULT_MODEL_SERVICE_RETRY_ATTEMPTS = 1
DEFAULT_MODEL_SERVICE_RETRY_SLEEP_S = 1.0
MODEL_SERVICE_RETRY_ATTEMPTS_ENV = "ROBOCLAWS_OPENAI_AGENTS_MODEL_SERVICE_RETRY_ATTEMPTS"
MODEL_SERVICE_RETRY_SLEEP_ENV = "ROBOCLAWS_OPENAI_AGENTS_MODEL_SERVICE_RETRY_SLEEP_S"


def _model_service_retry_config(request: LiveAgentRequest) -> dict[str, int | float]:
    metadata = dict(request.metadata)
    attempts = _non_negative_int(
        metadata.get("model_service_retry_attempts"),
        setting_name="model_service_retry_attempts",
        env_name=MODEL_SERVICE_RETRY_ATTEMPTS_ENV,
        default=DEFAULT_MODEL_SERVICE_RETRY_ATTEMPTS,
    )
    sleep_s = _non_negative_float(
        metadata.get("model_service_retry_sleep_s"),
        setting_name="model_service_retry_sleep_s",
        env_name=MODEL_SERVICE_RETRY_SLEEP_ENV,
        default=DEFAULT_MODEL_SERVICE_RETRY_SLEEP_S,
    )
    return {"retry_attempts": attempts, "retry_sleep_s": sleep_s}


class _RetryingModel(_AgentsModel):
    """Retry transient provider failures at the SDK model request boundary."""

    def __init__(
        self,
        base_model: Any,
        *,
        client: Any | None = None,
        retry_attempts: int,
        retry_sleep_s: float,
        events_path: Path,
        spans_path: Path,
        runtime_config: dict[str, Any],
    ) -> None:
        self.base_model = base_model
        self.client = client
        self.retry_attempts = max(0, retry_attempts)
        self.retry_sleep_s = max(0.0, retry_sleep_s)
        self.events_path = events_path
        self.spans_path = spans_path
        self.runtime_config = dict(runtime_config)
        self._model_call_index = 0

    async def close(self) -> None:
        try:
            await _close_async_resource(self.base_model)
        finally:
            if self.client is not self.base_model:
                await _close_async_resource(self.client)
        return None

    def get_retry_advice(self, request: Any) -> Any:
        get_retry_advice = getattr(self.base_model, "get_retry_advice", None)
        if get_retry_advice is None:
            return None
        return get_retry_advice(request)

    async def get_response(
        self,
        system_instructions: str | None,
        input: Any,
        model_settings: Any,
        tools: list[Any],
        output_schema: Any,
        handoffs: list[Any],
        tracing: Any,
        *,
        previous_response_id: str | None,
        conversation_id: str | None,
        prompt: Any,
    ) -> Any:
        attempt_index = 0
        while True:
            started = time.time()
            call_index = self._next_model_call_index()
            racing_enabled = _get_response_racing_enabled(self.runtime_config)
            _append_model_service_event(
                self.events_path,
                self.spans_path,
                "model_service_attempt",
                runtime_config=self.runtime_config,
                attempt_index=attempt_index,
                retry_budget=self.retry_attempts,
                method="get_response",
            )
            try:
                if racing_enabled:
                    result = await _race_get_response(
                        self,
                        call_index=call_index,
                        attempt_index=attempt_index,
                        system_instructions=system_instructions,
                        input=input,
                        model_settings=model_settings,
                        tools=tools,
                        output_schema=output_schema,
                        handoffs=handoffs,
                        tracing=tracing,
                        previous_response_id=previous_response_id,
                        conversation_id=conversation_id,
                        prompt=prompt,
                    )
                else:
                    arm_id = _model_racing_arm_id(
                        call_index=call_index,
                        attempt_index=attempt_index,
                        arm_index=0,
                    )
                    _append_model_racing_event(
                        self.events_path,
                        self.spans_path,
                        "model_racing_arm_start",
                        runtime_config=self.runtime_config,
                        call_index=call_index,
                        attempt_index=attempt_index,
                        arm_id=arm_id,
                        arm_index=0,
                        method="get_response",
                        arm_role="single",
                    )
                    result = await self.base_model.get_response(
                        system_instructions,
                        input,
                        model_settings,
                        tools,
                        output_schema,
                        handoffs,
                        tracing,
                        previous_response_id=previous_response_id,
                        conversation_id=conversation_id,
                        prompt=prompt,
                    )
            except Exception as exc:
                should_retry, failure = _should_retry_model_service_failure(
                    exc,
                    attempt_index=attempt_index,
                    retry_attempts=self.retry_attempts,
                )
                _append_model_service_failure_events(
                    self.events_path,
                    self.spans_path,
                    runtime_config=self.runtime_config,
                    attempt_index=attempt_index,
                    retry_budget=self.retry_attempts,
                    method="get_response",
                    started_at=started,
                    failure=failure,
                    will_retry=should_retry,
                    retry_delay_s=self.retry_sleep_s if should_retry else None,
                    safe_to_replay=True,
                )
                if not racing_enabled:
                    _append_model_racing_event(
                        self.events_path,
                        self.spans_path,
                        "model_racing_arm_failure",
                        runtime_config=self.runtime_config,
                        call_index=call_index,
                        attempt_index=attempt_index,
                        arm_id=_model_racing_arm_id(
                            call_index=call_index,
                            attempt_index=attempt_index,
                            arm_index=0,
                        ),
                        arm_index=0,
                        method="get_response",
                        arm_role="single",
                        elapsed_s=_round_duration(time.time() - started),
                        final_outcome="retry_scheduled" if should_retry else "failure",
                        failure_class=failure.reason,
                        provider_reason=failure.provider_reason,
                        retryable=failure.retryable,
                        winner=False,
                        cancelled=False,
                        cancellation_observed=False,
                        loser_billing_unknown=False,
                        safe_to_replay=True,
                    )
                if not should_retry:
                    raise
                if self.retry_sleep_s:
                    await asyncio.sleep(self.retry_sleep_s)
                attempt_index += 1
                continue
            _append_model_service_event(
                self.events_path,
                self.spans_path,
                "model_service_success",
                runtime_config=self.runtime_config,
                attempt_index=attempt_index,
                retry_budget=self.retry_attempts,
                method="get_response",
                elapsed_s=_round_duration(time.time() - started),
                final_outcome="success",
            )
            if not racing_enabled:
                _append_model_racing_event(
                    self.events_path,
                    self.spans_path,
                    "model_racing_arm_finish",
                    runtime_config=self.runtime_config,
                    call_index=call_index,
                    attempt_index=attempt_index,
                    arm_id=_model_racing_arm_id(
                        call_index=call_index,
                        attempt_index=attempt_index,
                        arm_index=0,
                    ),
                    arm_index=0,
                    method="get_response",
                    arm_role="single",
                    elapsed_s=_round_duration(time.time() - started),
                    final_outcome="success",
                    winner=True,
                    cancelled=False,
                    cancellation_observed=False,
                    loser_billing_unknown=False,
                    usage_summary=_usage_summary(result),
                )
            return result

    async def stream_response(
        self,
        system_instructions: str | None,
        input: Any,
        model_settings: Any,
        tools: list[Any],
        output_schema: Any,
        handoffs: list[Any],
        tracing: Any,
        *,
        previous_response_id: str | None,
        conversation_id: str | None,
        prompt: Any,
    ) -> Any:
        attempt_index = 0
        while True:
            started = time.time()
            yielded_event = False
            call_index = self._next_model_call_index()
            arm_id = _model_racing_arm_id(call_index=call_index, attempt_index=attempt_index)
            _append_model_racing_event(
                self.events_path,
                self.spans_path,
                "model_racing_arm_start",
                runtime_config=self.runtime_config,
                call_index=call_index,
                attempt_index=attempt_index,
                arm_id=arm_id,
                method="stream_response",
                arm_role="single",
                arm_count=1,
                racing_enabled=False,
                racing_mode="stream_response_single_arm_no_racing",
                racing_multiplier=1.0,
                winner_selection="stream_response_single_arm_no_racing",
                loser_cancellation="not_applicable_stream_response",
            )
            _append_model_service_event(
                self.events_path,
                self.spans_path,
                "model_service_attempt",
                runtime_config=self.runtime_config,
                attempt_index=attempt_index,
                retry_budget=self.retry_attempts,
                method="stream_response",
            )
            try:
                stream = self.base_model.stream_response(
                    system_instructions,
                    input,
                    model_settings,
                    tools,
                    output_schema,
                    handoffs,
                    tracing,
                    previous_response_id=previous_response_id,
                    conversation_id=conversation_id,
                    prompt=prompt,
                )
                async for event in stream:
                    yielded_event = True
                    yield event
            except Exception as exc:
                safe_to_replay = not yielded_event
                should_retry, failure = _should_retry_model_service_failure(
                    exc,
                    attempt_index=attempt_index,
                    retry_attempts=self.retry_attempts,
                    safe_to_replay=safe_to_replay,
                )
                _append_model_service_failure_events(
                    self.events_path,
                    self.spans_path,
                    runtime_config=self.runtime_config,
                    attempt_index=attempt_index,
                    retry_budget=self.retry_attempts,
                    method="stream_response",
                    started_at=started,
                    failure=failure,
                    will_retry=should_retry,
                    retry_delay_s=self.retry_sleep_s if should_retry else None,
                    safe_to_replay=safe_to_replay,
                )
                _append_model_racing_event(
                    self.events_path,
                    self.spans_path,
                    "model_racing_arm_failure",
                    runtime_config=self.runtime_config,
                    call_index=call_index,
                    attempt_index=attempt_index,
                    arm_id=arm_id,
                    method="stream_response",
                    arm_role="single",
                    arm_count=1,
                    racing_enabled=False,
                    racing_mode="stream_response_single_arm_no_racing",
                    racing_multiplier=1.0,
                    winner_selection="stream_response_single_arm_no_racing",
                    loser_cancellation="not_applicable_stream_response",
                    elapsed_s=_round_duration(time.time() - started),
                    final_outcome="retry_scheduled" if should_retry else "failure",
                    failure_class=failure.reason,
                    provider_reason=failure.provider_reason,
                    retryable=failure.retryable,
                    winner=False,
                    cancelled=False,
                    cancellation_observed=False,
                    loser_billing_unknown=False,
                    safe_to_replay=safe_to_replay,
                )
                if not should_retry:
                    raise
                if self.retry_sleep_s:
                    await asyncio.sleep(self.retry_sleep_s)
                attempt_index += 1
                continue
            _append_model_service_event(
                self.events_path,
                self.spans_path,
                "model_service_success",
                runtime_config=self.runtime_config,
                attempt_index=attempt_index,
                retry_budget=self.retry_attempts,
                method="stream_response",
                elapsed_s=_round_duration(time.time() - started),
                final_outcome="success",
            )
            _append_model_racing_event(
                self.events_path,
                self.spans_path,
                "model_racing_arm_finish",
                runtime_config=self.runtime_config,
                call_index=call_index,
                attempt_index=attempt_index,
                arm_id=arm_id,
                method="stream_response",
                arm_role="single",
                arm_count=1,
                racing_enabled=False,
                racing_mode="stream_response_single_arm_no_racing",
                racing_multiplier=1.0,
                winner_selection="stream_response_single_arm_no_racing",
                loser_cancellation="not_applicable_stream_response",
                elapsed_s=_round_duration(time.time() - started),
                final_outcome="success",
                winner=True,
                cancelled=False,
                cancellation_observed=False,
                loser_billing_unknown=False,
            )
            return

    def _next_model_call_index(self) -> int:
        value = self._model_call_index
        self._model_call_index += 1
        return value


def _should_retry_model_service_failure(
    exc: Exception,
    *,
    attempt_index: int,
    retry_attempts: int,
    safe_to_replay: bool = True,
) -> tuple[bool, LiveAgentFailure]:
    failure = _failure_from_exception(exc)
    should_retry = (
        safe_to_replay
        and failure.reason == "provider_transient_failure"
        and failure.retryable
        and attempt_index < retry_attempts
    )
    return should_retry, failure


def _non_negative_int(value: Any, *, setting_name: str, env_name: str, default: int) -> int:
    source = setting_name
    if value is None:
        raw_env = os.environ.get(env_name)
        if raw_env not in {None, ""}:
            value = raw_env
            source = env_name
        else:
            value = default
    if isinstance(value, bool):
        raise ValueError(
            f"OpenAI Agents SDK setting {setting_name} ({source}) must be a "
            f"non-negative integer, got {value!r}"
        )
    try:
        parsed = int(value)
    except (OverflowError, TypeError, ValueError) as exc:
        raise ValueError(
            f"OpenAI Agents SDK setting {setting_name} ({source}) must be a "
            f"non-negative integer, got {value!r}"
        ) from exc
    if parsed < 0:
        raise ValueError(
            f"OpenAI Agents SDK setting {setting_name} ({source}) must be a "
            f"non-negative integer, got {value!r}"
        )
    return parsed


def _non_negative_float(value: Any, *, setting_name: str, env_name: str, default: float) -> float:
    source = setting_name
    if value is None:
        raw_env = os.environ.get(env_name)
        if raw_env not in {None, ""}:
            value = raw_env
            source = env_name
        else:
            value = default
    if isinstance(value, bool):
        raise ValueError(
            f"OpenAI Agents SDK setting {setting_name} ({source}) must be a "
            f"finite non-negative number, got {value!r}"
        )
    try:
        parsed = float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(
            f"OpenAI Agents SDK setting {setting_name} ({source}) must be a "
            f"finite non-negative number, got {value!r}"
        ) from exc
    if not math.isfinite(parsed) or parsed < 0:
        raise ValueError(
            f"OpenAI Agents SDK setting {setting_name} ({source}) must be a "
            f"finite non-negative number, got {value!r}"
        )
    return parsed
