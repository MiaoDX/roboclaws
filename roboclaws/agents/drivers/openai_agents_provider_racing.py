"""Concurrent provider-arm racing for OpenAI Agents model calls."""

from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass
from typing import Any

from roboclaws.agents.drivers.openai_agents_event_log import (
    _append_model_racing_event,
    _model_racing_arm_id,
    _round_duration,
)
from roboclaws.agents.drivers.openai_agents_event_projection import _usage_summary
from roboclaws.agents.drivers.openai_agents_provider_runtime import (
    failure_from_exception as _failure_from_exception,
)
from roboclaws.agents.drivers.openai_agents_setting_values import _positive_int


@dataclass(frozen=True)
class _ModelRacingArmOutcome:
    arm_index: int
    arm_id: str
    elapsed_s: float
    result: Any = None
    exc: Exception | None = None


def _get_response_racing_enabled(runtime_config: dict[str, Any]) -> bool:
    config = (
        runtime_config.get("model_racing_observability")
        if isinstance(runtime_config.get("model_racing_observability"), dict)
        else {}
    )
    return bool(config.get("enabled")) and _racing_arm_count(runtime_config) > 1


def _racing_arm_count(runtime_config: dict[str, Any]) -> int:
    config = (
        runtime_config.get("model_racing_observability")
        if isinstance(runtime_config.get("model_racing_observability"), dict)
        else {}
    )
    return _positive_int(
        config.get("arm_count"),
        setting_name="model_racing_observability.arm_count",
        default=1,
    )


async def _race_get_response(
    model: Any,
    *,
    call_index: int,
    attempt_index: int,
    system_instructions: str | None,
    input: Any,
    model_settings: Any,
    tools: list[Any],
    output_schema: Any,
    handoffs: list[Any],
    tracing: Any,
    previous_response_id: str | None,
    conversation_id: str | None,
    prompt: Any,
) -> Any:
    tasks = [
        asyncio.create_task(
            _get_response_racing_arm(
                model,
                arm_index=arm_index,
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
        )
        for arm_index in range(_racing_arm_count(model.runtime_config))
    ]
    pending = set(tasks)
    failures: list[_ModelRacingArmOutcome] = []
    try:
        while pending:
            done, pending = await asyncio.wait(pending, return_when=asyncio.FIRST_COMPLETED)
            successful = [
                outcome for task in done for outcome in [task.result()] if outcome.exc is None
            ]
            failures.extend(
                outcome for task in done for outcome in [task.result()] if outcome.exc is not None
            )
            if not successful:
                continue

            winner = min(successful, key=lambda outcome: outcome.arm_index)
            for outcome in successful:
                _append_model_racing_event(
                    model.events_path,
                    model.spans_path,
                    "model_racing_arm_finish",
                    runtime_config=model.runtime_config,
                    call_index=call_index,
                    attempt_index=attempt_index,
                    arm_id=outcome.arm_id,
                    arm_index=outcome.arm_index,
                    method="get_response",
                    arm_role="winner" if outcome is winner else "loser",
                    elapsed_s=outcome.elapsed_s,
                    final_outcome="success" if outcome is winner else "success_loser",
                    winner=outcome is winner,
                    cancelled=False,
                    cancellation_observed=False,
                    loser_billing_unknown=outcome is not winner,
                    usage_summary=_usage_summary(outcome.result),
                )
            for task in pending:
                task.cancel()
            if pending:
                await asyncio.gather(*pending, return_exceptions=True)
            return winner.result
        if failures and failures[-1].exc is not None:
            raise failures[-1].exc
        raise RuntimeError("model racing completed without a winning arm")
    finally:
        for task in tasks:
            if not task.done():
                task.cancel()
        if any(not task.done() for task in tasks):
            await asyncio.gather(*tasks, return_exceptions=True)


async def _get_response_racing_arm(
    model: Any,
    *,
    arm_index: int,
    call_index: int,
    attempt_index: int,
    system_instructions: str | None,
    input: Any,
    model_settings: Any,
    tools: list[Any],
    output_schema: Any,
    handoffs: list[Any],
    tracing: Any,
    previous_response_id: str | None,
    conversation_id: str | None,
    prompt: Any,
) -> "_ModelRacingArmOutcome":
    started = time.time()
    arm_id = _model_racing_arm_id(
        call_index=call_index,
        attempt_index=attempt_index,
        arm_index=arm_index,
    )
    _append_model_racing_event(
        model.events_path,
        model.spans_path,
        "model_racing_arm_start",
        runtime_config=model.runtime_config,
        call_index=call_index,
        attempt_index=attempt_index,
        arm_id=arm_id,
        arm_index=arm_index,
        method="get_response",
        arm_role="candidate",
    )
    try:
        result = await model.base_model.get_response(
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
    except asyncio.CancelledError:
        _append_model_racing_event(
            model.events_path,
            model.spans_path,
            "model_racing_arm_cancelled",
            runtime_config=model.runtime_config,
            call_index=call_index,
            attempt_index=attempt_index,
            arm_id=arm_id,
            arm_index=arm_index,
            method="get_response",
            arm_role="loser",
            elapsed_s=_round_duration(time.time() - started),
            final_outcome="cancelled",
            winner=False,
            cancelled=True,
            cancellation_observed=True,
            loser_billing_unknown=True,
        )
        raise
    except Exception as exc:
        failure = _failure_from_exception(exc)
        _append_model_racing_event(
            model.events_path,
            model.spans_path,
            "model_racing_arm_failure",
            runtime_config=model.runtime_config,
            call_index=call_index,
            attempt_index=attempt_index,
            arm_id=arm_id,
            arm_index=arm_index,
            method="get_response",
            arm_role="candidate",
            elapsed_s=_round_duration(time.time() - started),
            final_outcome="failure",
            failure_class=failure.reason,
            provider_reason=failure.provider_reason,
            retryable=failure.retryable,
            winner=False,
            cancelled=False,
            cancellation_observed=False,
            loser_billing_unknown=False,
            safe_to_replay=True,
        )
        return _ModelRacingArmOutcome(
            arm_index=arm_index,
            arm_id=arm_id,
            elapsed_s=_round_duration(time.time() - started),
            exc=exc,
        )
    return _ModelRacingArmOutcome(
        arm_index=arm_index,
        arm_id=arm_id,
        elapsed_s=_round_duration(time.time() - started),
        result=result,
    )
