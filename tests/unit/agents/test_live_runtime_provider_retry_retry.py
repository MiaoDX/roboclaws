from __future__ import annotations

import asyncio
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from roboclaws.agents.drivers.openai_agents_metrics import (
    model_racing_observability_metrics as _model_racing_observability_metrics,
)
from roboclaws.agents.drivers.openai_agents_metrics import (
    model_service_fallback_metrics as _model_service_fallback_metrics,
)
from roboclaws.agents.drivers.openai_agents_retry_model import (
    _RetryingModel,
    _should_retry_model_service_failure,
)
from tests.unit.agents.live_runtime_support import (
    _assert_openai_agents_config_failure,
)


def test_openai_agents_runtime_classifies_model_service_retryability() -> None:
    retryable_messages = [
        "Error code: 500 - internal server error",
        "model unavailable",
        "transport error: connection reset",
    ]
    for message in retryable_messages:
        should_retry, failure = _should_retry_model_service_failure(
            RuntimeError(message),
            attempt_index=0,
            retry_attempts=1,
        )
        assert should_retry is True
        assert failure.reason == "provider_transient_failure"
        assert failure.retryable is True

    non_retryable_messages = [
        "invalid api key 401",
        "kimi-openai-chat requires KIMI_API_KEY",
        "Your input exceeds the context window",
        "tool failed while calling cleanup MCP",
    ]
    for message in non_retryable_messages:
        should_retry, failure = _should_retry_model_service_failure(
            RuntimeError(message),
            attempt_index=0,
            retry_attempts=1,
        )
        assert should_retry is False
        assert failure.retryable is False


def test_openai_agents_retrying_model_retries_transient_once(tmp_path: Path) -> None:
    class FakeModel:
        def __init__(self) -> None:
            self.calls = 0

        async def get_response(self, *_args, **_kwargs):
            self.calls += 1
            if self.calls == 1:
                raise RuntimeError("Error code: 503 - service unavailable")
            return SimpleNamespace(
                output="ok",
                usage={
                    "input_tokens": 100,
                    "input_tokens_details": {"cached_tokens": 25},
                    "output_tokens": 10,
                    "output_tokens_details": {"reasoning_tokens": 3},
                },
            )

        async def close(self) -> None:
            return None

        def stream_response(self, *_args, **_kwargs):
            raise AssertionError("not used")

    events_path = tmp_path / "openai-agents-events.jsonl"
    spans_path = tmp_path / "openai-agents-spans.jsonl"
    model = _RetryingModel(
        FakeModel(),
        retry_attempts=1,
        retry_sleep_s=0,
        events_path=events_path,
        spans_path=spans_path,
        runtime_config={
            "runtime": "openai-agents-live",
            "provider_profile": "kimi-openai-chat",
            "wire_api": "responses",
            "model": "kimi-k2.7-code",
        },
    )

    result = asyncio.run(
        model.get_response(
            None,
            "clean the room",
            object(),
            [],
            None,
            [],
            object(),
            previous_response_id=None,
            conversation_id=None,
            prompt=None,
        )
    )

    assert result.output == "ok"
    events = [json.loads(line) for line in events_path.read_text(encoding="utf-8").splitlines()]
    model_service_events = [
        event["event"]
        for event in events
        if str(event.get("event", "")).startswith("model_service_")
    ]
    assert model_service_events == [
        "model_service_attempt",
        "model_service_failure",
        "model_service_retry_scheduled",
        "model_service_attempt",
        "model_service_success",
    ]
    failures = [event for event in events if event.get("event") == "model_service_failure"]
    assert failures[0]["failure_class"] == "provider_transient_failure"
    assert "clean the room" not in events_path.read_text(encoding="utf-8")
    racing_events = [
        event
        for event in events
        if event.get("schema") == "openai_agents_model_racing_observability_v1"
    ]
    assert [event["event"] for event in racing_events] == [
        "model_racing_arm_start",
        "model_racing_arm_failure",
        "model_racing_arm_start",
        "model_racing_arm_finish",
    ]
    assert racing_events[0]["call_index"] == 0
    assert racing_events[0]["arm_id"] == "call-0-attempt-0-arm-0"
    assert racing_events[-1]["winner"] is True
    assert racing_events[-1]["cancelled"] is False
    assert racing_events[-1]["usage_summary"] == {
        "usage_available": True,
        "input_tokens": 100,
        "cached_input_tokens": 25,
        "uncached_input_tokens": 75,
        "output_tokens": 10,
        "reasoning_tokens": 3,
    }
    span_events = [json.loads(line) for line in spans_path.read_text(encoding="utf-8").splitlines()]
    assert any(event["span_type"] == "model_service_fallback" for event in span_events)
    assert any(event["span_type"] == "model_racing_observability" for event in span_events)


def test_openai_agents_retrying_model_reports_retry_exhaustion(tmp_path: Path) -> None:
    class FakeModel:
        async def get_response(self, *_args, **_kwargs):
            raise RuntimeError("model unavailable")

        def stream_response(self, *_args, **_kwargs):
            raise AssertionError("not used")

    events_path = tmp_path / "openai-agents-events.jsonl"
    spans_path = tmp_path / "openai-agents-spans.jsonl"
    model = _RetryingModel(
        FakeModel(),
        retry_attempts=1,
        retry_sleep_s=0,
        events_path=events_path,
        spans_path=spans_path,
        runtime_config={
            "runtime": "openai-agents-live",
            "provider_profile": "minimax-responses",
            "wire_api": "responses",
            "model": "MiniMax-M3",
        },
    )

    with pytest.raises(RuntimeError, match="model unavailable"):
        asyncio.run(
            model.get_response(
                None,
                "clean the room",
                object(),
                [],
                None,
                [],
                object(),
                previous_response_id=None,
                conversation_id=None,
                prompt=None,
            )
        )

    metrics = _model_service_fallback_metrics(tmp_path)
    assert metrics["available"] is True
    assert metrics["attempt_event_count"] == 2
    assert metrics["retry_scheduled_count"] == 1
    assert metrics["failure_event_count"] == 2
    assert metrics["retry_exhausted"] is True
    assert metrics["failure_classes"] == {"provider_transient_failure": 2}
    assert metrics["provider_reasons"] == {"upstream_unavailable": 2}
    assert metrics["attempted_models"] == ["MiniMax-M3"]
    assert metrics["attempted_provider_profiles"] == ["minimax-responses"]
    assert metrics["attempted_wire_apis"] == ["responses"]
    racing_metrics = _model_racing_observability_metrics(tmp_path)
    assert racing_metrics["available"] is True
    assert racing_metrics["call_count"] == 2
    assert racing_metrics["arm_count"] == 2
    assert racing_metrics["winner_count"] == 0
    assert racing_metrics["final_outcomes"] == {"failure": 1, "retry_scheduled": 1}


def test_openai_agents_retrying_model_satisfies_sdk_model_contract(tmp_path: Path) -> None:
    pytest.importorskip("agents")
    from agents.models.interface import Model

    class FakeModel:
        async def get_response(self, *_args, **_kwargs):
            return SimpleNamespace(output="ok")

        def stream_response(self, *_args, **_kwargs):
            raise AssertionError("not used")

    model = _RetryingModel(
        FakeModel(),
        retry_attempts=0,
        retry_sleep_s=0,
        events_path=tmp_path / "openai-agents-events.jsonl",
        spans_path=tmp_path / "openai-agents-spans.jsonl",
        runtime_config={"runtime": "openai-agents-live"},
    )

    assert isinstance(model, Model)


def test_openai_agents_retrying_model_zero_retry_still_records_observability(
    tmp_path: Path,
) -> None:
    class FakeModel:
        def __init__(self) -> None:
            self.calls = 0

        async def get_response(self, *_args, **_kwargs):
            self.calls += 1
            raise RuntimeError("model unavailable")

        def stream_response(self, *_args, **_kwargs):
            raise AssertionError("not used")

    fake_model = FakeModel()
    model = _RetryingModel(
        fake_model,
        retry_attempts=0,
        retry_sleep_s=0,
        events_path=tmp_path / "openai-agents-events.jsonl",
        spans_path=tmp_path / "openai-agents-spans.jsonl",
        runtime_config={
            "runtime": "openai-agents-live",
            "provider_profile": "minimax-responses",
            "wire_api": "responses",
            "model": "MiniMax-M3",
        },
    )

    with pytest.raises(RuntimeError, match="model unavailable"):
        asyncio.run(
            model.get_response(
                None,
                "clean the room",
                object(),
                [],
                None,
                [],
                object(),
                previous_response_id=None,
                conversation_id=None,
                prompt=None,
            )
        )

    assert fake_model.calls == 1
    metrics = _model_racing_observability_metrics(tmp_path)
    assert metrics["available"] is True
    assert metrics["call_count"] == 1
    assert metrics["arm_count"] == 1
    assert metrics["winner_count"] == 0
    assert metrics["final_outcomes"] == {"failure": 1}


def test_openai_agents_retrying_model_races_get_response_and_cancels_loser(
    tmp_path: Path,
) -> None:
    class FakeModel:
        def __init__(self) -> None:
            self.calls = 0
            self.cancelled = 0

        async def get_response(self, *_args, **_kwargs):
            self.calls += 1
            call_index = self.calls
            try:
                if call_index == 1:
                    await asyncio.sleep(0.01)
                    return SimpleNamespace(output="winner", usage={"input_tokens": 10})
                await asyncio.sleep(10)
                return SimpleNamespace(output="loser")
            except asyncio.CancelledError:
                self.cancelled += 1
                raise

        def stream_response(self, *_args, **_kwargs):
            raise AssertionError("not used")

    fake_model = FakeModel()
    events_path = tmp_path / "openai-agents-events.jsonl"
    spans_path = tmp_path / "openai-agents-spans.jsonl"
    model = _RetryingModel(
        fake_model,
        retry_attempts=0,
        retry_sleep_s=0,
        events_path=events_path,
        spans_path=spans_path,
        runtime_config={
            "runtime": "openai-agents-live",
            "provider_profile": "minimax-responses",
            "wire_api": "responses",
            "model": "MiniMax-M3",
            "model_racing_observability": {
                "schema": "agent_sdk_model_racing_observability_v1",
                "enabled": True,
                "mode": "get_response_racing_v1",
                "candidate_ids": ["D", "C"],
                "arm_count": 2,
                "racing_multiplier": 2.0,
                "winner_selection": "first_successful_sdk_response",
                "loser_cancellation": "cancel_pending_losers",
                "unknown_loser_billing": True,
            },
        },
    )

    result = asyncio.run(
        model.get_response(
            None,
            "clean the room SECRET_PROMPT",
            object(),
            [],
            None,
            [],
            object(),
            previous_response_id=None,
            conversation_id=None,
            prompt=None,
        )
    )

    assert result.output == "winner"
    assert fake_model.calls == 2
    assert fake_model.cancelled == 1
    events_text = events_path.read_text(encoding="utf-8")
    assert "SECRET_PROMPT" not in events_text
    events = [json.loads(line) for line in events_text.splitlines()]
    racing_events = [
        event
        for event in events
        if event.get("schema") == "openai_agents_model_racing_observability_v1"
    ]
    assert [event["event"] for event in racing_events] == [
        "model_racing_arm_start",
        "model_racing_arm_start",
        "model_racing_arm_finish",
        "model_racing_arm_cancelled",
    ]
    assert {event["arm_id"] for event in racing_events[:2]} == {
        "call-0-attempt-0-arm-0",
        "call-0-attempt-0-arm-1",
    }
    finish = next(event for event in racing_events if event["event"] == "model_racing_arm_finish")
    assert finish["winner"] is True
    assert finish["arm_role"] == "winner"
    assert finish["racing_enabled"] is True
    assert finish["racing_multiplier"] == 2.0
    assert finish["winner_selection"] == "first_successful_sdk_response"
    assert finish["usage_summary"] == {
        "usage_available": True,
        "input_tokens": 10,
    }
    cancelled = next(
        event for event in racing_events if event["event"] == "model_racing_arm_cancelled"
    )
    assert cancelled["cancelled"] is True
    assert cancelled["cancellation_observed"] is True
    assert cancelled["loser_billing_unknown"] is True
    metrics = _model_racing_observability_metrics(tmp_path)
    assert metrics["racing_enabled"] is True
    assert metrics["racing_multiplier"] == 2.0
    assert metrics["call_count"] == 1
    assert metrics["arm_count"] == 2
    assert metrics["max_arm_count_per_call"] == 2
    assert metrics["winner_count"] == 1
    assert metrics["cancelled_count"] == 1
    assert metrics["cancellation_observed_count"] == 1
    assert metrics["loser_billing_unknown_count"] == 1
    assert metrics["methods"] == ["get_response"]
    assert metrics["racing_modes"] == ["get_response_racing_v1"]


def test_openai_agents_retrying_model_racing_reports_all_arm_failures(
    tmp_path: Path,
) -> None:
    class FakeModel:
        def __init__(self) -> None:
            self.calls = 0

        async def get_response(self, *_args, **_kwargs):
            self.calls += 1
            raise RuntimeError(f"model unavailable {self.calls}")

        def stream_response(self, *_args, **_kwargs):
            raise AssertionError("not used")

    fake_model = FakeModel()
    model = _RetryingModel(
        fake_model,
        retry_attempts=0,
        retry_sleep_s=0,
        events_path=tmp_path / "openai-agents-events.jsonl",
        spans_path=tmp_path / "openai-agents-spans.jsonl",
        runtime_config={
            "runtime": "openai-agents-live",
            "provider_profile": "minimax-responses",
            "wire_api": "responses",
            "model": "MiniMax-M3",
            "model_racing_observability": {
                "enabled": True,
                "mode": "get_response_racing_v1",
                "arm_count": 2,
                "racing_multiplier": 2.0,
                "winner_selection": "first_successful_sdk_response",
                "loser_cancellation": "cancel_pending_losers",
                "unknown_loser_billing": True,
            },
        },
    )

    with pytest.raises(RuntimeError, match="model unavailable"):
        asyncio.run(
            model.get_response(
                None,
                "clean the room",
                object(),
                [],
                None,
                [],
                object(),
                previous_response_id=None,
                conversation_id=None,
                prompt=None,
            )
        )

    assert fake_model.calls == 2
    metrics = _model_racing_observability_metrics(tmp_path)
    assert metrics["available"] is True
    assert metrics["event_counts"] == {
        "model_racing_arm_failure": 2,
        "model_racing_arm_start": 2,
    }
    assert metrics["winner_count"] == 0
    assert metrics["failure_classes"] == {"provider_transient_failure": 2}
    assert metrics["final_outcomes"] == {"failure": 2}


def test_openai_agents_retrying_model_does_not_race_stream_response(
    tmp_path: Path,
) -> None:
    class FakeModel:
        def __init__(self) -> None:
            self.stream_calls = 0

        async def get_response(self, *_args, **_kwargs):
            raise AssertionError("not used")

        async def stream_response(self, *_args, **_kwargs):
            self.stream_calls += 1
            yield SimpleNamespace(output="streamed")

    async def collect_stream(model: _RetryingModel) -> list[object]:
        events = []
        async for event in model.stream_response(
            None,
            "clean the room",
            object(),
            [],
            None,
            [],
            object(),
            previous_response_id=None,
            conversation_id=None,
            prompt=None,
        ):
            events.append(event)
        return events

    fake_model = FakeModel()
    model = _RetryingModel(
        fake_model,
        retry_attempts=0,
        retry_sleep_s=0,
        events_path=tmp_path / "openai-agents-events.jsonl",
        spans_path=tmp_path / "openai-agents-spans.jsonl",
        runtime_config={
            "runtime": "openai-agents-live",
            "provider_profile": "minimax-responses",
            "wire_api": "responses",
            "model": "MiniMax-M3",
            "model_racing_observability": {
                "enabled": True,
                "mode": "get_response_racing_v1",
                "arm_count": 2,
                "racing_multiplier": 2.0,
                "winner_selection": "first_successful_sdk_response",
                "loser_cancellation": "cancel_pending_losers",
                "unknown_loser_billing": True,
            },
        },
    )

    events = asyncio.run(collect_stream(model))

    assert [event.output for event in events] == ["streamed"]
    assert fake_model.stream_calls == 1
    metrics = _model_racing_observability_metrics(tmp_path)
    assert metrics["racing_enabled"] is False
    assert metrics["racing_multiplier"] == 1.0
    assert metrics["arm_count"] == 1
    assert metrics["max_arm_count_per_call"] == 1
    assert metrics["methods"] == ["stream_response"]
    assert metrics["racing_modes"] == ["stream_response_single_arm_no_racing"]


@pytest.mark.parametrize(
    ("metadata", "env", "expected_detail"),
    [
        (
            {},
            {"ROBOCLAWS_OPENAI_AGENTS_MODEL_SERVICE_RETRY_ATTEMPTS": "many"},
            "model_service_retry_attempts "
            "(ROBOCLAWS_OPENAI_AGENTS_MODEL_SERVICE_RETRY_ATTEMPTS) must be a "
            "non-negative integer, got 'many'",
        ),
        (
            {"model_service_retry_attempts": True},
            {},
            "model_service_retry_attempts (model_service_retry_attempts) must be a "
            "non-negative integer, got True",
        ),
        (
            {"model_service_retry_attempts": float("inf")},
            {},
            "model_service_retry_attempts (model_service_retry_attempts) must be a "
            "non-negative integer, got inf",
        ),
        (
            {},
            {"ROBOCLAWS_OPENAI_AGENTS_MODEL_SERVICE_RETRY_ATTEMPTS": "inf"},
            "model_service_retry_attempts "
            "(ROBOCLAWS_OPENAI_AGENTS_MODEL_SERVICE_RETRY_ATTEMPTS) must be a "
            "non-negative integer, got 'inf'",
        ),
    ],
)
def test_openai_agents_runtime_rejects_invalid_retry_attempt_numeric_values(
    tmp_path: Path,
    monkeypatch,
    metadata: dict[str, object],
    env: dict[str, str],
    expected_detail: str,
) -> None:
    for key, value in env.items():
        monkeypatch.setenv(key, value)

    _assert_openai_agents_config_failure(tmp_path, metadata=metadata, detail=expected_detail)


@pytest.mark.parametrize(
    ("metadata", "env", "expected_detail"),
    [
        (
            {"model_service_retry_sleep_s": "later"},
            {},
            "model_service_retry_sleep_s (model_service_retry_sleep_s) must be a "
            "finite non-negative number, got 'later'",
        ),
        (
            {"model_service_retry_sleep_s": True},
            {},
            "model_service_retry_sleep_s (model_service_retry_sleep_s) must be a "
            "finite non-negative number, got True",
        ),
        (
            {"model_service_retry_sleep_s": float("nan")},
            {},
            "model_service_retry_sleep_s (model_service_retry_sleep_s) must be a "
            "finite non-negative number, got nan",
        ),
        (
            {},
            {"ROBOCLAWS_OPENAI_AGENTS_MODEL_SERVICE_RETRY_SLEEP_S": "inf"},
            "model_service_retry_sleep_s "
            "(ROBOCLAWS_OPENAI_AGENTS_MODEL_SERVICE_RETRY_SLEEP_S) must be a "
            "finite non-negative number, got 'inf'",
        ),
    ],
)
def test_openai_agents_runtime_rejects_invalid_retry_sleep_numeric_values(
    tmp_path: Path,
    monkeypatch,
    metadata: dict[str, object],
    env: dict[str, str],
    expected_detail: str,
) -> None:
    for key, value in env.items():
        monkeypatch.setenv(key, value)

    _assert_openai_agents_config_failure(tmp_path, metadata=metadata, detail=expected_detail)
