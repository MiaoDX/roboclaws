from __future__ import annotations

import asyncio
import json
import uuid
from argparse import Namespace
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace

import pytest

from roboclaws.agents.drivers.openai_agents_budget import (
    OpenAIAgentsBudgetExceededError,
    openai_agents_budget_failure,
    openai_agents_observe_budget_advisory,
    raw_fpv_budget_metrics,
)
from roboclaws.agents.drivers.openai_agents_live import (
    OpenAIAgentsLiveRuntime,
    _default_sdk_model_settings_payload,
    _failure_from_exception,
    _mcp_client_session_timeout_seconds,
    _RetryingModel,
    _should_retry_model_service_failure,
)
from roboclaws.agents.drivers.openai_agents_model_input import (
    _compact_model_input_items,
    _model_input_shape_summary,
)
from roboclaws.agents.drivers.openai_agents_spans import RoboclawsSpanRecorder
from roboclaws.agents.live_runtime import (
    LiveAgentMCPServer,
    LiveAgentRequest,
    LiveAgentResult,
    live_agent_result_from_artifacts,
)
from roboclaws.agents.live_status import LiveAgentFailure
from roboclaws.agents.live_timing import live_timing_timeline as _live_timing_timeline
from roboclaws.agents.live_timing import mcp_control_plane_metrics as _mcp_control_plane_metrics
from roboclaws.agents.prompts.household_cleanup import (
    render_kickoff_prompt,
    render_map_build_prompt,
)
from scripts.molmo_cleanup.openai_agents_perf_profile import (
    resolve_agent_sdk_perf_profile as _resolve_agent_sdk_perf_profile,
)
from scripts.molmo_cleanup.run_live_openai_agents_cleanup import (
    IncompleteTurnRecoveryPolicy,
    LiveOpenAIAgentsCleanupRunner,
    _budget_failure_from_run_state,
    _cache_metrics,
    _compact_continuation_prompt,
    _compact_continuation_state,
    _context_growth_metrics,
    _context_metrics,
    _kickoff_prompt_source,
    _load_agent_sdk_skill_context,
    _model_input_filter_metrics,
    _model_racing_observability_metrics,
    _model_service_fallback_metrics,
    _openai_agents_event_metrics,
    _openai_agents_span_metrics,
    _profiled_kickoff_prompt,
)
from scripts.molmo_cleanup.run_live_openai_agents_cleanup import (
    parse_args as _parse_live_openai_agents_args,
)


def _isolated_repo_root(tmp_path: Path) -> Path:
    repo_root = tmp_path / "repo"
    repo_root.mkdir()
    return repo_root


class FakeModelSettings:
    def __init__(self, **kwargs) -> None:
        self.__dict__.update(kwargs)


class FakeRunConfig:
    def __init__(self, **kwargs) -> None:
        self.__dict__.update(kwargs)


def test_live_agent_request_keeps_one_turn_policy_explicit(tmp_path: Path) -> None:
    request = LiveAgentRequest(
        run_id="household-world",
        skill_name="household-world",
        kickoff_prompt="clean the room",
        mcp_server=LiveAgentMCPServer(name="cleanup", url="http://127.0.0.1:18788/mcp"),
        run_dir=tmp_path / "run",
        artifact_paths={"live_status": tmp_path / "status.json"},
    )

    assert request.one_turn is True
    assert request.max_turns is None
    assert request.artifact_path("live_status", "live_status.json") == tmp_path / "status.json"
    assert request.artifact_path("events", "events.jsonl") == tmp_path / "run" / "events.jsonl"


def test_openai_agents_default_model_settings_apply_provider_thinking_policy() -> None:
    responses = _default_sdk_model_settings_payload(
        provider_profile="codex-router-responses",
        wire_api="responses",
        profile_id="baseline",
    )
    kimi_chat = _default_sdk_model_settings_payload(
        provider_profile="kimi-openai-chat",
        wire_api="chat-completions",
        profile_id="baseline",
    )
    mimo_inside_chat = _default_sdk_model_settings_payload(
        provider_profile="mimo-inside-openai-chat",
        wire_api="chat-completions",
        profile_id="baseline",
    )
    disabled_chat = _default_sdk_model_settings_payload(
        provider_profile="mimo-tp-openai-chat",
        wire_api="chat-completions",
        profile_id="baseline",
        thinking_mode="disabled",
    )

    assert responses["reasoning"] == {"effort": "medium"}
    assert "truncation" not in responses
    assert "extra_body" not in kimi_chat
    assert kimi_chat["extra_headers"] == {"User-Agent": "claude-code/1.0.0"}
    assert mimo_inside_chat["extra_body"]["thinking"] == {"type": "disabled"}
    assert disabled_chat["extra_body"]["thinking"] == {"type": "disabled"}


def test_live_agent_request_rejects_invalid_sdk_turn_budget(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="max_turns must be >= 1"):
        LiveAgentRequest(
            run_id="household-world",
            skill_name="household-world",
            kickoff_prompt="clean the room",
            mcp_server=LiveAgentMCPServer(name="cleanup", url="http://127.0.0.1:18788/mcp"),
            run_dir=tmp_path / "run",
            max_turns=0,
        )


def test_live_agent_result_from_failure_matches_live_status_fields() -> None:
    result = LiveAgentResult.from_failure(
        phase="failed",
        exit_status=1,
        failure=LiveAgentFailure(
            reason="provider_transient_failure",
            provider_reason="rate_limit",
            retryable=True,
            resume_available=True,
            detail="429 Too Many Requests",
        ),
        started_at_epoch=10.0,
        finished_at_epoch=12.0,
    )

    assert result.to_live_status_payload() == {
        "phase": "failed",
        "started_at_epoch": 10.0,
        "finished_at_epoch": 12.0,
        "exit_status": 1,
        "reason": "provider_transient_failure",
        "provider_reason": "rate_limit",
        "retryable": True,
        "resume_available": True,
        "detail": "429 Too Many Requests",
    }


def test_live_agent_result_reads_existing_cli_artifacts(tmp_path: Path) -> None:
    run_dir = tmp_path / "run"
    run_dir.mkdir()
    (run_dir / "live_status.json").write_text(
        json.dumps(
            {
                "phase": "failed",
                "exit_status": 1,
                "reason": "tool_binding_failure",
                "retryable": False,
                "resume_available": False,
            }
        ),
        encoding="utf-8",
    )
    (run_dir / "run_result.json").write_text(
        json.dumps(
            {
                "task_name": "household-cleanup",
                "cleanup_success": False,
                "private_target_truth": {"must_not": "drive runtime status"},
            }
        ),
        encoding="utf-8",
    )
    (run_dir / "codex-events.jsonl").write_text('{"type":"error"}\n', encoding="utf-8")
    (run_dir / "openai-agents-spans.jsonl").write_text('{"event":"span_end"}\n', encoding="utf-8")

    result = live_agent_result_from_artifacts(run_dir)

    assert result.phase == "failed"
    assert result.reason == "tool_binding_failure"
    assert result.retryable is False
    assert result.resume_available is False
    assert result.run_result_present is True
    assert result.task_completion == {
        "task_name": "household-cleanup",
        "cleanup_success": False,
    }
    assert result.artifact_paths["codex_events"] == run_dir / "codex-events.jsonl"
    assert result.artifact_paths["openai_agents_spans"] == run_dir / "openai-agents-spans.jsonl"


def test_live_agent_result_keeps_missing_artifacts_optional(tmp_path: Path) -> None:
    run_dir = tmp_path / "run"
    run_dir.mkdir()

    result = live_agent_result_from_artifacts(run_dir)

    assert result.phase == "unknown"
    assert result.run_result_present is False
    assert result.task_completion == {}


def test_live_agent_result_fails_on_malformed_live_status_source(tmp_path: Path) -> None:
    run_dir = tmp_path / "run"
    run_dir.mkdir()
    (run_dir / "live_status.json").write_text("{not json", encoding="utf-8")

    with pytest.raises(ValueError, match=r"live_status\.json.*invalid JSON"):
        live_agent_result_from_artifacts(run_dir)


def test_live_agent_result_fails_on_non_object_run_result_source(tmp_path: Path) -> None:
    run_dir = tmp_path / "run"
    run_dir.mkdir()
    (run_dir / "live_status.json").write_text(
        json.dumps({"phase": "finished", "exit_status": 0}),
        encoding="utf-8",
    )
    (run_dir / "run_result.json").write_text(json.dumps(["ok"]), encoding="utf-8")

    with pytest.raises(ValueError, match=r"run_result\.json.*non-object JSON"):
        live_agent_result_from_artifacts(run_dir)


def test_openai_agents_runtime_missing_sdk_writes_normalized_failure(
    tmp_path: Path, monkeypatch
) -> None:
    def missing_sdk(*_args, **_kwargs):
        raise ImportError("no module named agents")

    monkeypatch.setattr(
        "roboclaws.agents.drivers.openai_agents_live._run_openai_agents",
        missing_sdk,
    )
    request = LiveAgentRequest(
        run_id="household-world",
        skill_name="household-world",
        kickoff_prompt="clean the room",
        mcp_server=LiveAgentMCPServer(name="cleanup", url="http://127.0.0.1:18788/mcp"),
        run_dir=tmp_path / "run",
    )

    result = OpenAIAgentsLiveRuntime().run(request)

    assert result.phase == "failed"
    assert result.exit_status == 1
    assert result.reason == "provider_config_failure"
    assert result.retryable is False
    payload = json.loads((tmp_path / "run" / "live_status.json").read_text(encoding="utf-8"))
    assert payload["reason"] == "provider_config_failure"
    assert "not installed" in payload["detail"]


def test_openai_agents_runtime_classifies_context_window_before_502() -> None:
    failure = _failure_from_exception(
        RuntimeError(
            "Error code: 502 - {'error': {'message': 'Your input exceeds the context "
            "window of this model. Please adjust your input and try again.'}}"
        )
    )

    assert failure.reason == "provider_context_failure"
    assert failure.retryable is False
    assert failure.resume_available is False


def test_openai_agents_runtime_classifies_sdk_max_turn_budget() -> None:
    class MaxTurnsExceeded(Exception):
        pass

    failure = _failure_from_exception(MaxTurnsExceeded("Max turns (40) exceeded"))

    assert failure.reason == "agent_sdk_turn_budget_exceeded"
    assert failure.retryable is False
    assert failure.resume_available is False


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
        "codex-router-responses requires CODEX_API_KEY",
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
            "provider_profile": "codex-router-responses",
            "wire_api": "responses",
            "model": "gpt-5.5",
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
            "provider_profile": "mimo-mify-responses",
            "wire_api": "responses",
            "model": "xiaomi/mimo-v2.5",
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
    assert metrics["attempted_models"] == ["xiaomi/mimo-v2.5"]
    assert metrics["attempted_provider_profiles"] == ["mimo-mify-responses"]
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
            "provider_profile": "mimo-mify-responses",
            "wire_api": "responses",
            "model": "xiaomi/mimo-v2.5",
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
            "provider_profile": "mimo-mify-responses",
            "wire_api": "responses",
            "model": "xiaomi/mimo-v2.5",
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
            "provider_profile": "mimo-mify-responses",
            "wire_api": "responses",
            "model": "xiaomi/mimo-v2.5",
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
            "provider_profile": "mimo-mify-responses",
            "wire_api": "responses",
            "model": "xiaomi/mimo-v2.5",
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


def test_openai_agents_runtime_turn_completion_does_not_infer_cleanup_success(
    tmp_path: Path, monkeypatch
) -> None:
    class FakeSDKResult:
        final_output = "I stopped before calling done."
        trace_id = "trace_123"
        usage = {"requests": 1}

    monkeypatch.setattr(
        "roboclaws.agents.drivers.openai_agents_live._run_openai_agents",
        lambda *_args, **_kwargs: FakeSDKResult(),
    )
    request = LiveAgentRequest(
        run_id="household-world",
        skill_name="household-world",
        kickoff_prompt="clean the room",
        mcp_server=LiveAgentMCPServer(name="cleanup", url="http://127.0.0.1:18788/mcp"),
        run_dir=tmp_path / "run",
    )

    result = OpenAIAgentsLiveRuntime().run(request)

    assert result.phase == "agent-turn-complete"
    assert result.exit_status == 0
    assert result.run_result_present is False
    assert result.trace_id == "trace_123"
    payload = json.loads((tmp_path / "run" / "live_status.json").read_text(encoding="utf-8"))
    assert payload["phase"] == "agent-turn-complete"
    assert payload["trace_id"] == "trace_123"
    trace_payload = json.loads((tmp_path / "run" / "openai-agents-trace.json").read_text())
    assert "I stopped before calling done." not in json.dumps(trace_payload)
    assert trace_payload["final_output_present"] is True
    assert trace_payload["final_output_chars"] == len("I stopped before calling done.")
    assert trace_payload["message"].startswith("OpenAI Agents SDK result captured")


def test_openai_agents_runtime_defaults_to_codex_env_responses_profile(
    tmp_path: Path, monkeypatch
) -> None:
    captured: dict[str, object] = {}

    class FakeOpenAIResponsesModel:
        def __init__(self, model: str, *, openai_client: object) -> None:
            captured["responses_model"] = self
            captured["model"] = model
            captured["client"] = openai_client

    class FakeAsyncOpenAI:
        def __init__(
            self,
            *,
            api_key: str,
            base_url: str,
            default_headers: dict[str, str] | None = None,
        ) -> None:
            captured["api_key"] = api_key
            captured["base_url"] = base_url
            captured["default_headers"] = default_headers

    monkeypatch.setenv("CODEX_BASE_URL", "https://codex.example.test/v1")
    monkeypatch.setenv("CODEX_API_KEY", "fake-codex-key")
    monkeypatch.setattr(
        "roboclaws.agents.drivers.openai_agents_live._run_with_async_mcp_server",
        lambda *_args, **_kwargs: SimpleNamespace(final_output="done"),
    )
    monkeypatch.setitem(
        __import__("sys").modules,
        "agents",
        SimpleNamespace(
            Agent=lambda **kwargs: captured.setdefault("agent_kwargs", kwargs),
            Runner=SimpleNamespace(
                run_sync=lambda *_args, **kwargs: (
                    captured.setdefault("runner_kwargs", kwargs) or SimpleNamespace()
                )
            ),
            ModelSettings=FakeModelSettings,
            RunConfig=FakeRunConfig,
            OpenAIResponsesModel=FakeOpenAIResponsesModel,
        ),
    )
    monkeypatch.setitem(
        __import__("sys").modules,
        "agents.mcp",
        SimpleNamespace(
            MCPServerStreamableHttp=lambda **kwargs: (
                captured.setdefault("mcp_server_kwargs", kwargs) or SimpleNamespace(kwargs=kwargs)
            )
        ),
    )
    monkeypatch.setitem(
        __import__("sys").modules,
        "openai",
        SimpleNamespace(AsyncOpenAI=FakeAsyncOpenAI),
    )
    request = LiveAgentRequest(
        run_id="household-world",
        skill_name="household-world",
        kickoff_prompt="clean the room",
        mcp_server=LiveAgentMCPServer(name="cleanup", url="http://127.0.0.1:18788/mcp"),
        run_dir=tmp_path / "run",
    )

    OpenAIAgentsLiveRuntime().run(request)

    assert captured["model"] == "gpt-5.6-sol"
    assert captured["base_url"] == "https://codex.example.test/v1"
    assert captured["api_key"] == "fake-codex-key"
    window_id = captured["default_headers"]["X-Codex-Window-Id"]
    thread_id, generation = window_id.rsplit(":", 1)
    assert uuid.UUID(thread_id)
    assert generation == "0"
    wrapped_model = captured["agent_kwargs"]["model"]
    assert isinstance(wrapped_model, _RetryingModel)
    assert wrapped_model.base_model is captured["responses_model"]
    assert captured["agent_kwargs"]["model_settings"].tool_choice == "auto"
    assert captured["agent_kwargs"]["model_settings"].parallel_tool_calls is False
    assert not hasattr(captured["agent_kwargs"]["model_settings"], "truncation")
    assert not hasattr(captured["agent_kwargs"]["model_settings"], "extra_headers")
    assert captured["runner_kwargs"]["run_config"].trace_include_sensitive_data is False
    assert captured["runner_kwargs"]["run_config"].workflow_name == "roboclaws-openai-agents-live"
    assert captured["mcp_server_kwargs"]["cache_tools_list"] is True
    assert "client_session_timeout_seconds" not in captured["mcp_server_kwargs"]
    events_text = (tmp_path / "run" / "openai-agents-events.jsonl").read_text(encoding="utf-8")
    assert "x-codex" not in events_text.lower()
    assert captured["agent_kwargs"]["mcp_config"]["failure_error_function"]
    assert captured["runner_kwargs"]["max_turns"] == 128
    events = [
        json.loads(line)
        for line in (tmp_path / "run" / "openai-agents-events.jsonl").read_text().splitlines()
    ]
    assert events[0]["wire_api"] == "responses"
    assert events[0]["sdk_model_settings"]["store"] is False
    assert events[0]["sdk_model_settings"]["reasoning"] == {"effort": "medium"}
    assert events[0]["sdk_run_config"]["trace_include_sensitive_data"] is False
    assert events[0]["agent_sdk_responses_features"]["available"] is True
    assert events[0]["agent_sdk_responses_features"]["server_managed_continuation_default"] is False
    assert events[0]["model_input_compaction"]["enabled"] is False
    assert events[0]["model_input_compaction"]["mode"] == "off"
    assert events[0]["model_racing_observability"]["enabled"] is False
    assert events[0]["model_racing_observability"]["winner_selection"] == "single_arm_no_racing"


def test_openai_agents_runtime_includes_skill_context_without_persisting_body(
    tmp_path: Path, monkeypatch
) -> None:
    captured: dict[str, object] = {}
    skill_text = "# Molmo Real-World Cleanup\n\nCall metric_map first."

    class FakeOpenAIResponsesModel:
        def __init__(self, model: str, *, openai_client: object) -> None:
            captured["model"] = model

    class FakeAsyncOpenAI:
        def __init__(
            self,
            *,
            api_key: str,
            base_url: str,
            default_headers: dict[str, str] | None = None,
        ) -> None:
            pass

    monkeypatch.setenv("CODEX_BASE_URL", "https://codex.example.test/v1")
    monkeypatch.setenv("CODEX_API_KEY", "fake-codex-key")
    monkeypatch.setattr(
        "roboclaws.agents.drivers.openai_agents_live._run_with_async_mcp_server",
        lambda *_args, **_kwargs: SimpleNamespace(final_output="done"),
    )
    monkeypatch.setitem(
        __import__("sys").modules,
        "agents",
        SimpleNamespace(
            Agent=lambda **kwargs: captured.setdefault("agent_kwargs", kwargs),
            Runner=SimpleNamespace(
                run_sync=lambda *_args, **kwargs: (
                    captured.setdefault("runner_kwargs", kwargs) or SimpleNamespace()
                )
            ),
            ModelSettings=FakeModelSettings,
            RunConfig=FakeRunConfig,
            OpenAIResponsesModel=FakeOpenAIResponsesModel,
        ),
    )
    monkeypatch.setitem(
        __import__("sys").modules,
        "agents.mcp",
        SimpleNamespace(
            MCPServerStreamableHttp=lambda **kwargs: (
                captured.setdefault("mcp_server_kwargs", kwargs) or SimpleNamespace(kwargs=kwargs)
            )
        ),
    )
    monkeypatch.setitem(
        __import__("sys").modules,
        "openai",
        SimpleNamespace(AsyncOpenAI=FakeAsyncOpenAI),
    )
    request = LiveAgentRequest(
        run_id="household-world",
        skill_name="household-world",
        kickoff_prompt="clean the room",
        mcp_server=LiveAgentMCPServer(name="cleanup", url="http://127.0.0.1:18788/mcp"),
        run_dir=tmp_path / "run",
        metadata={
            "skill_context": {
                "skill_name": "household-world",
                "included": True,
                "reason": "included",
                "relative_path": "skills/household-world/SKILL.md",
                "sha256": "abc123",
                "bytes": len(skill_text),
                "estimated_tokens": 12,
                "policy": "canonical_skill_markdown",
                "content": skill_text,
            }
        },
    )

    result = OpenAIAgentsLiveRuntime().run(request)

    assert result.artifact_paths["openai_agents_skill_context"] == (
        tmp_path / "run" / "openai-agents-skill-context.json"
    )
    instructions = str(captured["agent_kwargs"]["instructions"])
    assert "Canonical skill context" in instructions
    assert (
        "Run-specific kickoff instructions override any conflicting generic skill-context "
        "guidance for this run"
    ) in instructions
    assert skill_text in instructions
    assert instructions.endswith("clean the room")
    artifact = json.loads(
        (tmp_path / "run" / "openai-agents-skill-context.json").read_text(encoding="utf-8")
    )
    assert artifact == {
        "schema": "openai_agents_skill_context_v1",
        "skill_name": "household-world",
        "included": True,
        "reason": "included",
        "relative_path": "skills/household-world/SKILL.md",
        "sha256": "abc123",
        "bytes": len(skill_text),
        "estimated_tokens": 12,
        "policy": "canonical_skill_markdown",
    }
    assert skill_text not in json.dumps(artifact)
    events_text = (tmp_path / "run" / "openai-agents-events.jsonl").read_text(encoding="utf-8")
    assert "abc123" in events_text
    assert skill_text not in events_text


def test_openai_agents_runtime_can_use_mimo_openai_chat_profile(
    tmp_path: Path, monkeypatch
) -> None:
    captured: dict[str, object] = {}

    class FakeOpenAIChatCompletionsModel:
        def __init__(self, model: str, *, openai_client: object) -> None:
            captured["chat_model"] = self
            captured["model"] = model
            captured["client"] = openai_client

    class FakeAsyncOpenAI:
        def __init__(
            self,
            *,
            api_key: str,
            base_url: str,
            default_headers: dict[str, str] | None = None,
        ) -> None:
            captured["api_key"] = api_key
            captured["base_url"] = base_url

    monkeypatch.setenv("MIMO_TP_KEY", "fake-mimo-key")
    monkeypatch.setattr(
        "roboclaws.agents.drivers.openai_agents_live._run_with_async_mcp_server",
        lambda *_args, **_kwargs: SimpleNamespace(final_output="done"),
    )
    monkeypatch.setitem(
        __import__("sys").modules,
        "agents",
        SimpleNamespace(
            Agent=lambda **kwargs: captured.setdefault("agent_kwargs", kwargs),
            Runner=SimpleNamespace(run_sync=lambda *_args, **_kwargs: SimpleNamespace()),
            ModelSettings=FakeModelSettings,
            RunConfig=FakeRunConfig,
            OpenAIChatCompletionsModel=FakeOpenAIChatCompletionsModel,
        ),
    )
    monkeypatch.setitem(
        __import__("sys").modules,
        "agents.mcp",
        SimpleNamespace(
            MCPServerStreamableHttp=lambda **kwargs: (
                captured.setdefault("mcp_server_kwargs", kwargs) or SimpleNamespace(kwargs=kwargs)
            )
        ),
    )
    monkeypatch.setitem(
        __import__("sys").modules,
        "openai",
        SimpleNamespace(AsyncOpenAI=FakeAsyncOpenAI),
    )
    request = LiveAgentRequest(
        run_id="household-world",
        skill_name="household-world",
        kickoff_prompt="clean the room",
        mcp_server=LiveAgentMCPServer(name="cleanup", url="http://127.0.0.1:18788/mcp"),
        run_dir=tmp_path / "run",
        provider_profile="mimo-tp-openai-chat",
    )

    OpenAIAgentsLiveRuntime().run(request)

    assert captured["model"] == "mimo-v2.5"
    assert captured["base_url"] == "https://token-plan-cn.xiaomimimo.com/v1"
    assert captured["api_key"] == "fake-mimo-key"
    wrapped_model = captured["agent_kwargs"]["model"]
    assert isinstance(wrapped_model, _RetryingModel)
    assert wrapped_model.base_model is captured["chat_model"]
    assert captured["agent_kwargs"]["model_settings"].include_usage is True
    assert captured["agent_kwargs"]["model_settings"].parallel_tool_calls is False
    assert captured["agent_kwargs"]["model_settings"].extra_body == {
        "thinking": {"type": "enabled", "keep": "all"}
    }
    events = [
        json.loads(line)
        for line in (tmp_path / "run" / "openai-agents-events.jsonl").read_text().splitlines()
    ]
    assert events[0]["provider_profile"] == "mimo-tp-openai-chat"
    assert events[0]["wire_api"] == "chat-completions"
    assert events[0]["sdk_model_settings"]["include_usage"] is True
    assert events[0]["agent_sdk_responses_features"]["available"] is False


def test_openai_agents_runtime_applies_kimi_coding_user_agent(tmp_path: Path, monkeypatch) -> None:
    captured: dict[str, object] = {}

    class FakeOpenAIChatCompletionsModel:
        def __init__(self, model: str, *, openai_client: object) -> None:
            captured["chat_model"] = self
            captured["model"] = model
            captured["client"] = openai_client

    class FakeAsyncOpenAI:
        def __init__(
            self,
            *,
            api_key: str,
            base_url: str,
            default_headers: dict[str, str] | None = None,
        ) -> None:
            captured["api_key"] = api_key
            captured["base_url"] = base_url

    monkeypatch.setenv("KIMI_API_KEY", "fake-kimi-key")
    monkeypatch.setattr(
        "roboclaws.agents.drivers.openai_agents_live._run_with_async_mcp_server",
        lambda *_args, **_kwargs: SimpleNamespace(final_output="done"),
    )
    monkeypatch.setitem(
        __import__("sys").modules,
        "agents",
        SimpleNamespace(
            Agent=lambda **kwargs: captured.setdefault("agent_kwargs", kwargs),
            Runner=SimpleNamespace(run_sync=lambda *_args, **_kwargs: SimpleNamespace()),
            ModelSettings=FakeModelSettings,
            RunConfig=FakeRunConfig,
            OpenAIChatCompletionsModel=FakeOpenAIChatCompletionsModel,
        ),
    )
    monkeypatch.setitem(
        __import__("sys").modules,
        "agents.mcp",
        SimpleNamespace(
            MCPServerStreamableHttp=lambda **kwargs: (
                captured.setdefault("mcp_server_kwargs", kwargs) or SimpleNamespace(kwargs=kwargs)
            )
        ),
    )
    monkeypatch.setitem(
        __import__("sys").modules,
        "openai",
        SimpleNamespace(AsyncOpenAI=FakeAsyncOpenAI),
    )
    request = LiveAgentRequest(
        run_id="household-world",
        skill_name="household-world",
        kickoff_prompt="clean the room",
        mcp_server=LiveAgentMCPServer(name="cleanup", url="http://127.0.0.1:18788/mcp"),
        run_dir=tmp_path / "run",
        provider_profile="kimi-openai-chat",
        metadata={
            "agent_sdk_perf_profile": {
                "profile_id": "baseline",
                "provider_profile": "kimi-openai-chat",
                "wire_api": "chat-completions",
                "sdk_model_settings": {
                    "tool_choice": "auto",
                    "parallel_tool_calls": False,
                    "model_thinking_mode": "default",
                    "include_usage": True,
                },
            }
        },
    )

    OpenAIAgentsLiveRuntime().run(request)

    model_settings = captured["agent_kwargs"]["model_settings"]
    assert captured["model"] == "kimi-k2.7-code"
    assert captured["base_url"] == "https://api.kimi.com/coding/v1"
    assert captured["api_key"] == "fake-kimi-key"
    assert model_settings.include_usage is True
    assert not hasattr(model_settings, "extra_body")
    assert model_settings.extra_headers == {"User-Agent": "claude-code/1.0.0"}
    events = [
        json.loads(line)
        for line in (tmp_path / "run" / "openai-agents-events.jsonl").read_text().splitlines()
    ]
    assert events[0]["provider_profile"] == "kimi-openai-chat"
    assert events[0]["sdk_model_settings"]["extra_headers"] == {"User-Agent": "claude-code/1.0.0"}


def test_openai_agents_runtime_configures_model_input_compaction_filter(
    tmp_path: Path, monkeypatch
) -> None:
    captured: dict[str, object] = {}

    class FakeOpenAIResponsesModel:
        def __init__(self, model: str, *, openai_client: object) -> None:
            captured["model"] = model

    class FakeAsyncOpenAI:
        def __init__(
            self,
            *,
            api_key: str,
            base_url: str,
            default_headers: dict[str, str] | None = None,
        ) -> None:
            pass

    monkeypatch.setenv("CODEX_BASE_URL", "https://codex.example.test/v1")
    monkeypatch.setenv("CODEX_API_KEY", "fake-codex-key")
    monkeypatch.setattr(
        "roboclaws.agents.drivers.openai_agents_live._run_with_async_mcp_server",
        lambda *_args, **_kwargs: SimpleNamespace(final_output="done"),
    )
    monkeypatch.setitem(
        __import__("sys").modules,
        "agents",
        SimpleNamespace(
            Agent=lambda **kwargs: captured.setdefault("agent_kwargs", kwargs),
            Runner=SimpleNamespace(
                run_sync=lambda *_args, **kwargs: (
                    captured.setdefault("runner_kwargs", kwargs) or SimpleNamespace()
                )
            ),
            ModelSettings=FakeModelSettings,
            RunConfig=FakeRunConfig,
            OpenAIResponsesModel=FakeOpenAIResponsesModel,
        ),
    )
    monkeypatch.setitem(
        __import__("sys").modules,
        "agents.mcp",
        SimpleNamespace(
            MCPServerStreamableHttp=lambda **kwargs: (
                captured.setdefault("mcp_server_kwargs", kwargs) or SimpleNamespace(kwargs=kwargs)
            )
        ),
    )
    monkeypatch.setitem(
        __import__("sys").modules,
        "openai",
        SimpleNamespace(AsyncOpenAI=FakeAsyncOpenAI),
    )
    request = LiveAgentRequest(
        run_id="household-world",
        skill_name="household-world",
        kickoff_prompt="clean the room",
        mcp_server=LiveAgentMCPServer(name="cleanup", url="http://127.0.0.1:18788/mcp"),
        run_dir=tmp_path / "run",
        metadata={
            "agent_sdk_perf_profile": {
                "profile_id": "custom",
                "provider_profile": "codex-router-responses",
                "wire_api": "responses",
                "model_input_compaction": {
                    "enabled": True,
                    "mode": "public_tool_result_summary_v1+camera_grounded_history_v1",
                    "min_chars": 80,
                    "camera_grounded_history": {
                        "schema": "agent_sdk_camera_grounded_history_policy_v1",
                        "enabled": True,
                        "mode": "retain_latest_actionable_outputs",
                        "retained_recent_outputs": 2,
                        "candidate_ids": ["AC"],
                    },
                },
            }
        },
    )

    OpenAIAgentsLiveRuntime().run(request)

    run_config = captured["runner_kwargs"]["run_config"]
    assert callable(run_config.call_model_input_filter)
    events = [
        json.loads(line)
        for line in (tmp_path / "run" / "openai-agents-events.jsonl").read_text().splitlines()
    ]
    assert events[0]["model_input_compaction"]["enabled"] is True
    assert (
        events[0]["model_input_compaction"]["mode"]
        == "public_tool_result_summary_v1+camera_grounded_history_v1"
    )
    assert events[0]["model_input_compaction"]["camera_grounded_history"] == {
        "schema": "agent_sdk_camera_grounded_history_policy_v1",
        "enabled": True,
        "mode": "retain_latest_actionable_outputs",
        "retained_recent_outputs": 2,
        "summary_kind": "roboclaws_camera_grounded_history_summary_v1",
        "candidate_ids": ["AC"],
        "private_artifact_policy": (
            "model-facing camera-grounded history compaction only; MCP traces, reports, "
            "and run artifacts remain complete"
        ),
    }
    assert "call_model_input_filter" not in events[0]["sdk_run_config"]


def test_openai_agents_model_input_filter_warns_before_model_call_on_observe_budget(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: dict[str, object] = {}

    class FakeOpenAIResponsesModel:
        def __init__(self, model: str, *, openai_client: object) -> None:
            captured["model"] = model

    class FakeAsyncOpenAI:
        def __init__(
            self,
            *,
            api_key: str,
            base_url: str,
            default_headers: dict[str, str] | None = None,
        ) -> None:
            pass

    def fake_run_with_async_mcp_server(_server, _agent, request, _events_path, *, run_config):
        data = SimpleNamespace(
            model_data=SimpleNamespace(
                input=[{"role": "user", "content": "continue map build"}],
                instructions="inspect the next waypoint",
            )
        )
        (request.run_dir / "trace.jsonl").write_text(
            "\n".join(
                json.dumps(item)
                for item in [
                    {
                        "event": "response",
                        "tool": "observe",
                        "response": {"ok": True, "waypoint_id": "generated_exploration_001"},
                    },
                    {
                        "event": "response",
                        "tool": "observe",
                        "response": {"ok": True, "waypoint_id": "generated_exploration_001"},
                    },
                ]
            )
            + "\n",
            encoding="utf-8",
        )
        captured["filtered_model_data"] = asyncio.run(run_config.call_model_input_filter(data))
        return SimpleNamespace(final_output="continued after observation advisory")

    monkeypatch.setenv("CODEX_BASE_URL", "https://codex.example.test/v1")
    monkeypatch.setenv("CODEX_API_KEY", "fake-codex-key")
    monkeypatch.setattr(
        "roboclaws.agents.drivers.openai_agents_live._run_with_async_mcp_server",
        fake_run_with_async_mcp_server,
    )
    monkeypatch.setitem(
        __import__("sys").modules,
        "agents",
        SimpleNamespace(
            Agent=lambda **kwargs: captured.setdefault("agent_kwargs", kwargs),
            Runner=SimpleNamespace(
                run_sync=lambda *_args, **kwargs: captured.setdefault("runner_kwargs", kwargs)
            ),
            ModelSettings=FakeModelSettings,
            RunConfig=FakeRunConfig,
            OpenAIResponsesModel=FakeOpenAIResponsesModel,
        ),
    )
    monkeypatch.setitem(
        __import__("sys").modules,
        "agents.mcp",
        SimpleNamespace(
            MCPServerStreamableHttp=lambda **kwargs: SimpleNamespace(
                __aenter__=lambda: None,
                kwargs=kwargs,
            )
        ),
    )
    monkeypatch.setitem(
        __import__("sys").modules,
        "openai",
        SimpleNamespace(AsyncOpenAI=FakeAsyncOpenAI),
    )
    request = LiveAgentRequest(
        run_id="household-world",
        skill_name="household-map-build",
        kickoff_prompt="build a map",
        mcp_server=LiveAgentMCPServer(name="cleanup", url="http://127.0.0.1:18788/mcp"),
        run_dir=tmp_path / "run",
        provider_profile="codex-router-responses",
        metadata={
            "provider_profile": "codex-router-responses",
            "evidence_lane": "camera-grounded-labels",
            "agent_sdk_perf_profile": {
                "profile_id": "context_managed_v1",
                "provider_profile": "codex-router-responses",
                "wire_api": "responses",
                "context_hard_limit_tokens": None,
                "max_observe_per_waypoint": 1,
                "raw_fpv_candidate_budget": None,
                "raw_fpv_repeated_failure_limit": None,
                "model_input_compaction": {"enabled": False, "mode": "off"},
            },
        },
    )

    result = OpenAIAgentsLiveRuntime().run(request)

    assert result.exit_status == 0
    assert result.phase == "agent-turn-complete"
    filtered_model_data = captured["filtered_model_data"]
    assert "Observation cadence advisory" in filtered_model_data.instructions
    assert "generated_exploration_001" in filtered_model_data.instructions
    assert "preferred limit of 1" in filtered_model_data.instructions
    events = [
        json.loads(line)
        for line in (tmp_path / "run" / "openai-agents-events.jsonl").read_text().splitlines()
    ]
    assert events[0]["model_input_compaction"]["enabled"] is False
    assert not any(item.get("event") == "model_input_budget_guard" for item in events)
    advisory_event = next(
        item for item in events if item.get("event") == "model_input_budget_advisory"
    )
    assert advisory_event["reason"] == "observe_budget_exceeded"
    assert advisory_event["detail_schema"] == "agent_sdk_observe_budget_advisory_v1"
    assert advisory_event["detail_summary"]["observe_over_budget_by_waypoint"] == {
        "generated_exploration_001": 2
    }


def test_openai_agents_budget_exception_preserves_failure_classification() -> None:
    exc = OpenAIAgentsBudgetExceededError(
        LiveAgentFailure(
            "provider_context_budget_exceeded",
            retryable=False,
            resume_available=False,
            detail='{"schema":"agent_sdk_context_budget_terminal_v1"}',
        )
    )

    failure = _failure_from_exception(exc)

    assert failure.reason == "provider_context_budget_exceeded"
    assert failure.retryable is False
    assert failure.detail == '{"schema":"agent_sdk_context_budget_terminal_v1"}'


def test_model_input_compaction_reduces_oversized_public_tool_outputs() -> None:
    large_output = json.dumps(
        {
            "tool": "inspect_visible_object",
            "object_id": "object_1",
            "public_observations": [
                {"note": f"large public observation payload {idx}", "objects": ["cup", "plate"]}
                for idx in range(20)
            ],
        }
    )
    items = [
        {"role": "user", "content": "clean the room"},
        {
            "type": "function_call_output",
            "call_id": "call_inspect_visible_object",
            "output": large_output,
        },
    ]

    filtered, metrics = _compact_model_input_items(items, min_chars=80)

    assert metrics["input_item_count"] == 2
    assert metrics["compacted_item_count"] == 1
    assert metrics["input_bytes_after"] < metrics["input_bytes_before"]
    assert filtered[0] == items[0]
    assert filtered[1]["call_id"] == "call_inspect_visible_object"
    replacement = json.loads(filtered[1]["output"])
    assert replacement["schema"] == "roboclaws_public_tool_output_summary_v1"
    assert replacement["original_chars"] == len(large_output)
    assert "large public observation payload 19" not in json.dumps(filtered)


def test_model_input_compaction_rejects_invalid_min_chars_env(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("ROBOCLAWS_OPENAI_AGENTS_INPUT_COMPACTION_MIN_CHARS", "many")
    request = LiveAgentRequest(
        run_id="household-world",
        skill_name="household-world",
        kickoff_prompt="clean the room",
        mcp_server=LiveAgentMCPServer(name="cleanup", url="http://127.0.0.1:18788/mcp"),
        run_dir=tmp_path / "run",
        metadata={"model_input_compaction": {"enabled": True}},
    )

    result = OpenAIAgentsLiveRuntime().run(request)

    assert result.phase == "failed"
    assert result.reason == "provider_config_failure"
    payload = json.loads((tmp_path / "run" / "live_status.json").read_text(encoding="utf-8"))
    assert payload["reason"] == "provider_config_failure"
    assert "ROBOCLAWS_OPENAI_AGENTS_INPUT_COMPACTION_MIN_CHARS" in payload["detail"]
    assert "must be a positive integer" in payload["detail"]


@pytest.mark.parametrize(
    ("metadata", "setting_name"),
    [
        (
            {"model_input_compaction": {"enabled": "sometimes"}},
            "model_input_compaction.enabled",
        ),
        (
            {
                "model_input_compaction": {
                    "enabled": True,
                    "raw_fpv_image_memory": {"enabled": "sometimes"},
                }
            },
            "raw_fpv_image_memory.enabled",
        ),
        (
            {
                "model_input_compaction": {
                    "enabled": True,
                    "camera_grounded_history": {"enabled": "sometimes"},
                }
            },
            "camera_grounded_history.enabled",
        ),
    ],
)
def test_model_input_compaction_rejects_invalid_boolean_settings(
    tmp_path: Path,
    monkeypatch,
    metadata: dict[str, object],
    setting_name: str,
) -> None:
    monkeypatch.setenv("CODEX_BASE_URL", "https://codex.example.test/v1")
    monkeypatch.setenv("CODEX_API_KEY", "fake-codex-key")
    request = LiveAgentRequest(
        run_id="household-world",
        skill_name="household-world",
        kickoff_prompt="clean the room",
        mcp_server=LiveAgentMCPServer(name="cleanup", url="http://127.0.0.1:18788/mcp"),
        run_dir=tmp_path / "run",
        metadata=metadata,
    )

    result = OpenAIAgentsLiveRuntime().run(request)

    assert result.phase == "failed"
    assert result.reason == "provider_config_failure"
    payload = json.loads((tmp_path / "run" / "live_status.json").read_text(encoding="utf-8"))
    assert payload["reason"] == "provider_config_failure"
    assert setting_name in payload["detail"]
    assert "must be true or false" in payload["detail"]


def test_model_input_compaction_rejects_invalid_direct_policy_limits(
    tmp_path: Path, monkeypatch
) -> None:
    monkeypatch.setenv("CODEX_BASE_URL", "https://codex.example.test/v1")
    monkeypatch.setenv("CODEX_API_KEY", "fake-codex-key")
    request = LiveAgentRequest(
        run_id="household-world",
        skill_name="household-world",
        kickoff_prompt="clean the room",
        mcp_server=LiveAgentMCPServer(name="cleanup", url="http://127.0.0.1:18788/mcp"),
        run_dir=tmp_path / "run",
        metadata={
            "model_input_compaction": {
                "enabled": True,
                "raw_fpv_image_memory": {
                    "enabled": True,
                    "retained_full_frame_limit": "latest",
                },
            }
        },
    )

    result = OpenAIAgentsLiveRuntime().run(request)

    assert result.phase == "failed"
    assert result.reason == "provider_config_failure"
    payload = json.loads((tmp_path / "run" / "live_status.json").read_text(encoding="utf-8"))
    assert payload["reason"] == "provider_config_failure"
    assert (
        "OpenAI Agents SDK setting raw_fpv_image_memory.retained_full_frame_limit"
        in payload["detail"]
    )
    assert "must be a positive integer, got 'latest'" in payload["detail"]


@pytest.mark.parametrize(
    ("config", "setting_name"),
    [
        ({"enabled": "sometimes"}, "model_racing_observability.enabled"),
        (
            {"unknown_loser_billing": "sometimes"},
            "model_racing_observability.unknown_loser_billing",
        ),
    ],
)
def test_openai_agents_runtime_rejects_invalid_model_racing_boolean_settings(
    tmp_path: Path,
    monkeypatch,
    config: dict[str, object],
    setting_name: str,
) -> None:
    monkeypatch.setenv("CODEX_BASE_URL", "https://codex.example.test/v1")
    monkeypatch.setenv("CODEX_API_KEY", "fake-codex-key")
    request = LiveAgentRequest(
        run_id="household-world",
        skill_name="household-world",
        kickoff_prompt="clean the room",
        mcp_server=LiveAgentMCPServer(name="cleanup", url="http://127.0.0.1:18788/mcp"),
        run_dir=tmp_path / "run",
        metadata={"model_racing_observability": config},
    )

    result = OpenAIAgentsLiveRuntime().run(request)

    assert result.phase == "failed"
    assert result.reason == "provider_config_failure"
    payload = json.loads((tmp_path / "run" / "live_status.json").read_text(encoding="utf-8"))
    assert payload["reason"] == "provider_config_failure"
    assert setting_name in payload["detail"]
    assert "must be true or false" in payload["detail"]


@pytest.mark.parametrize(
    ("config", "setting_name", "message"),
    [
        (
            {"arm_count": "many"},
            "model_racing_observability.arm_count",
            "must be a positive integer",
        ),
        (
            {"arm_count": 0},
            "model_racing_observability.arm_count",
            "must be a positive integer",
        ),
        (
            {"racing_multiplier": "fast"},
            "model_racing_observability.racing_multiplier",
            "must be a positive finite number",
        ),
        (
            {"racing_multiplier": float("inf")},
            "model_racing_observability.racing_multiplier",
            "must be a positive finite number",
        ),
    ],
)
def test_openai_agents_runtime_rejects_invalid_model_racing_numeric_settings(
    tmp_path: Path,
    monkeypatch,
    config: dict[str, object],
    setting_name: str,
    message: str,
) -> None:
    monkeypatch.setenv("CODEX_BASE_URL", "https://codex.example.test/v1")
    monkeypatch.setenv("CODEX_API_KEY", "fake-codex-key")
    request = LiveAgentRequest(
        run_id="household-world",
        skill_name="household-world",
        kickoff_prompt="clean the room",
        mcp_server=LiveAgentMCPServer(name="cleanup", url="http://127.0.0.1:18788/mcp"),
        run_dir=tmp_path / "run",
        metadata={"model_racing_observability": config},
    )

    result = OpenAIAgentsLiveRuntime().run(request)

    assert result.phase == "failed"
    assert result.reason == "provider_config_failure"
    payload = json.loads((tmp_path / "run" / "live_status.json").read_text(encoding="utf-8"))
    assert payload["reason"] == "provider_config_failure"
    assert setting_name in payload["detail"]
    assert message in payload["detail"]


def _assert_openai_agents_config_failure(
    tmp_path: Path,
    *,
    metadata: dict[str, object] | None = None,
    detail: str,
) -> None:
    request = LiveAgentRequest(
        run_id="household-world",
        skill_name="household-world",
        kickoff_prompt="clean the room",
        mcp_server=LiveAgentMCPServer(name="cleanup", url="http://127.0.0.1:18788/mcp"),
        run_dir=tmp_path / "run",
        metadata=metadata or {},
    )

    result = OpenAIAgentsLiveRuntime().run(request)

    assert result.phase == "failed"
    assert result.reason == "provider_config_failure"
    payload = json.loads((tmp_path / "run" / "live_status.json").read_text(encoding="utf-8"))
    assert payload["reason"] == "provider_config_failure"
    assert detail in payload["detail"]


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


@pytest.mark.parametrize(
    ("metadata", "env", "expected_detail"),
    [
        (
            {},
            {"ROBOCLAWS_OPENAI_AGENTS_MCP_CLIENT_SESSION_TIMEOUT_S": "eventually"},
            "mcp_client_session_timeout_s "
            "(ROBOCLAWS_OPENAI_AGENTS_MCP_CLIENT_SESSION_TIMEOUT_S) must be a "
            "finite non-negative number, got 'eventually'",
        ),
        (
            {"mcp_client_session_timeout_s": -1},
            {},
            "mcp_client_session_timeout_s (mcp_client_session_timeout_s) must be a "
            "finite non-negative number, got -1",
        ),
        (
            {"mcp_client_session_timeout_s": True},
            {},
            "mcp_client_session_timeout_s (mcp_client_session_timeout_s) must be a "
            "finite non-negative number, got True",
        ),
        (
            {"mcp_client_session_timeout_s": float("nan")},
            {},
            "mcp_client_session_timeout_s (mcp_client_session_timeout_s) must be a "
            "finite non-negative number, got nan",
        ),
        (
            {},
            {"ROBOCLAWS_OPENAI_AGENTS_MCP_CLIENT_SESSION_TIMEOUT_S": "inf"},
            "mcp_client_session_timeout_s "
            "(ROBOCLAWS_OPENAI_AGENTS_MCP_CLIENT_SESSION_TIMEOUT_S) must be a "
            "finite non-negative number, got 'inf'",
        ),
    ],
)
def test_openai_agents_runtime_rejects_invalid_mcp_timeout_numeric_values(
    tmp_path: Path,
    monkeypatch,
    metadata: dict[str, object],
    env: dict[str, str],
    expected_detail: str,
) -> None:
    for key, value in env.items():
        monkeypatch.setenv(key, value)

    _assert_openai_agents_config_failure(tmp_path, metadata=metadata, detail=expected_detail)


def test_openai_agents_runtime_preserves_zero_mcp_client_timeout_disable(
    tmp_path: Path,
) -> None:
    request = LiveAgentRequest(
        run_id="household-world",
        skill_name="household-world",
        kickoff_prompt="clean the room",
        mcp_server=LiveAgentMCPServer(name="cleanup", url="http://127.0.0.1:18788/mcp"),
        run_dir=tmp_path / "run",
        metadata={"mcp_client_session_timeout_s": 0},
    )

    assert _mcp_client_session_timeout_seconds(request) == (True, None)


@pytest.mark.parametrize(
    ("value", "expected_detail"),
    [
        ("many", "must be a positive integer, got 'many'"),
        (0, "must be a positive integer, got 0"),
        (True, "must be a positive integer, got True"),
        (float("inf"), "must be a positive integer, got inf"),
    ],
)
def test_openai_agents_runtime_rejects_invalid_direct_max_turns(
    tmp_path: Path,
    value: object,
    expected_detail: str,
) -> None:
    _assert_openai_agents_config_failure(
        tmp_path,
        metadata={"max_turns": value},
        detail=f"OpenAI Agents SDK setting max_turns {expected_detail}",
    )


@pytest.mark.parametrize(
    ("metadata", "env", "expected_detail"),
    [
        (
            {"provider_profile": "kimi-openai-chat"},
            {"ROBOCLAWS_PROVIDER_PROFILE": "codex-router-responses"},
            "conflicting OpenAI Agents SDK setting provider_profile",
        ),
        (
            {"model": "gpt-5.5"},
            {"ROBOCLAWS_OPENAI_AGENTS_MODEL": "kimi-k2.7-code"},
            "conflicting OpenAI Agents SDK setting model",
        ),
        (
            {"base_url": "https://codex-one.example.test/v1"},
            {"CODEX_BASE_URL": "https://codex-two.example.test/v1"},
            "conflicting OpenAI Agents SDK setting base_url",
        ),
        (
            {"api_key": "metadata-key"},
            {"CODEX_API_KEY": "env-key"},
            "conflicting OpenAI Agents SDK setting api_key",
        ),
    ],
)
def test_openai_agents_runtime_rejects_conflicting_provider_model_env_settings(
    tmp_path: Path,
    monkeypatch,
    metadata: dict[str, object],
    env: dict[str, str],
    expected_detail: str,
) -> None:
    base_env = {
        "CODEX_BASE_URL": "https://codex.example.test/v1",
        "CODEX_API_KEY": "fake-codex-key",
    }
    base_env.update(env)
    for key, value in base_env.items():
        monkeypatch.setenv(key, value)
    request = LiveAgentRequest(
        run_id="household-world",
        skill_name="household-world",
        kickoff_prompt="clean the room",
        mcp_server=LiveAgentMCPServer(name="cleanup", url="http://127.0.0.1:18788/mcp"),
        run_dir=tmp_path / "run",
        metadata=metadata,
    )

    result = OpenAIAgentsLiveRuntime().run(request)

    assert result.phase == "failed"
    assert result.reason == "provider_config_failure"
    payload = json.loads((tmp_path / "run" / "live_status.json").read_text(encoding="utf-8"))
    assert payload["reason"] == "provider_config_failure"
    assert expected_detail in payload["detail"]


def test_openai_agents_runtime_rejects_unknown_model_env(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("CODEX_BASE_URL", "https://codex.example.test/v1")
    monkeypatch.setenv("CODEX_API_KEY", "fake-codex-key")
    monkeypatch.setenv("ROBOCLAWS_OPENAI_AGENTS_MODEL", "not-in-provider-catalog")
    request = LiveAgentRequest(
        run_id="household-world",
        skill_name="household-world",
        kickoff_prompt="clean the room",
        mcp_server=LiveAgentMCPServer(name="cleanup", url="http://127.0.0.1:18788/mcp"),
        run_dir=tmp_path / "run",
    )

    result = OpenAIAgentsLiveRuntime().run(request)

    assert result.phase == "failed"
    assert result.reason == "provider_config_failure"
    payload = json.loads((tmp_path / "run" / "live_status.json").read_text(encoding="utf-8"))
    assert payload["reason"] == "provider_config_failure"
    assert "OpenAI Agents SDK setting model is unknown" in payload["detail"]
    assert "not-in-provider-catalog" in payload["detail"]


def test_openai_agents_runtime_rejects_route_incompatible_model_env(
    tmp_path: Path, monkeypatch
) -> None:
    monkeypatch.setenv("MM_API_KEY", "fake-mm-key")
    monkeypatch.setenv("ROBOCLAWS_PROVIDER_PROFILE", "minimax-responses")
    monkeypatch.setenv("ROBOCLAWS_OPENAI_AGENTS_MODEL", "gpt-5.5")
    request = LiveAgentRequest(
        run_id="household-world",
        skill_name="household-world",
        kickoff_prompt="clean the room",
        mcp_server=LiveAgentMCPServer(name="cleanup", url="http://127.0.0.1:18788/mcp"),
        run_dir=tmp_path / "run",
    )

    result = OpenAIAgentsLiveRuntime().run(request)

    assert result.phase == "failed"
    assert result.reason == "provider_config_failure"
    payload = json.loads((tmp_path / "run" / "live_status.json").read_text(encoding="utf-8"))
    assert payload["reason"] == "provider_config_failure"
    assert "OpenAI Agents SDK setting model is incompatible" in payload["detail"]
    assert (
        "model 'gpt-5.5' is incompatible with provider_profile 'minimax-responses'"
        in (payload["detail"])
    )


def test_openai_agents_runtime_allows_matching_provider_model_env_aliases(
    tmp_path: Path,
    monkeypatch,
) -> None:
    captured: dict[str, object] = {}

    class FakeOpenAIResponsesModel:
        def __init__(self, model: str, *, openai_client: object) -> None:
            captured["model"] = model

    class FakeAsyncOpenAI:
        def __init__(
            self,
            *,
            api_key: str,
            base_url: str,
            default_headers: dict[str, str] | None = None,
        ) -> None:
            captured["api_key"] = api_key
            captured["base_url"] = base_url

    monkeypatch.setenv("MM_BASE_URL", "https://codex.example.test/v1/")
    monkeypatch.setenv("MM_API_KEY", "fake-codex-key")
    monkeypatch.setenv("ROBOCLAWS_PROVIDER_PROFILE", "minimax-responses")
    monkeypatch.setenv("ROBOCLAWS_OPENAI_AGENTS_MODEL", "MiniMax-M3")
    monkeypatch.setattr(
        "roboclaws.agents.drivers.openai_agents_live._run_with_async_mcp_server",
        lambda *_args, **_kwargs: SimpleNamespace(final_output="done"),
    )
    monkeypatch.setitem(
        __import__("sys").modules,
        "agents",
        SimpleNamespace(
            Agent=lambda **kwargs: captured.setdefault("agent_kwargs", kwargs),
            Runner=SimpleNamespace(run_sync=lambda *_args, **_kwargs: SimpleNamespace()),
            ModelSettings=FakeModelSettings,
            RunConfig=FakeRunConfig,
            OpenAIResponsesModel=FakeOpenAIResponsesModel,
        ),
    )
    monkeypatch.setitem(
        __import__("sys").modules,
        "agents.mcp",
        SimpleNamespace(
            MCPServerStreamableHttp=lambda **kwargs: (
                captured.setdefault("mcp_server_kwargs", kwargs) or SimpleNamespace(kwargs=kwargs)
            )
        ),
    )
    monkeypatch.setitem(
        __import__("sys").modules,
        "openai",
        SimpleNamespace(AsyncOpenAI=FakeAsyncOpenAI),
    )
    request = LiveAgentRequest(
        run_id="household-world",
        skill_name="household-world",
        kickoff_prompt="clean the room",
        mcp_server=LiveAgentMCPServer(name="cleanup", url="http://127.0.0.1:18788/mcp"),
        run_dir=tmp_path / "run",
        provider_profile="minimax-responses",
        model="minimax",
        metadata={
            "provider_profile": "minimax-responses",
            "base_url": "https://codex.example.test/v1",
            "api_key": "fake-codex-key",
        },
    )

    result = OpenAIAgentsLiveRuntime().run(request)

    assert result.exit_status == 0
    assert captured["model"] == "MiniMax-M3"
    assert captured["base_url"] == "https://codex.example.test/v1"
    assert captured["api_key"] == "fake-codex-key"


def test_model_input_shape_summary_is_aggregate_only() -> None:
    summary = _model_input_shape_summary(
        [
            {"role": "user", "content": "secret prompt body"},
            {
                "type": "mcp_call",
                "id": "mcp_secret",
                "name": "roboclaws__observe_camera_grounded_candidates",
                "server_label": "roboclaws",
                "arguments": '{"secret": true}',
                "output": "large private tool output body",
                "status": "completed",
            },
            {
                "type": "function_call_output",
                "call_id": "call_metric_map",
                "output": "metric map body",
            },
        ]
    )

    assert summary["schema"] == "openai_agents_model_input_shape_summary_v1"
    assert summary["input_item_count"] == 3
    assert summary["type_counts"] == {
        "<missing>": 1,
        "function_call_output": 1,
        "mcp_call": 1,
    }
    assert summary["tool_field_counts"] == {
        "call_id": 1,
        "id": 1,
        "name": 1,
    }
    assert summary["output_field_counts"] == {"content": 1, "output": 2}
    encoded = json.dumps(summary)
    assert "secret prompt body" not in encoded
    assert "large private tool output body" not in encoded
    assert "roboclaws__observe_camera_grounded_candidates" not in encoded
    assert "metric map body" not in encoded


def test_model_input_compaction_summarizes_repeated_metric_map_outputs() -> None:
    first_map = {
        "ok": True,
        "tool": "metric_map",
        "map_id": "home",
        "map_version": "v1",
        "base_metric_map": {"enabled": True},
        "inspection_waypoints": [
            {
                "waypoint_id": f"wp_{idx}",
                "room": "kitchen",
                "navigation_note": "large public map waypoint payload",
            }
            for idx in range(80)
        ],
        "runtime_metric_map": {
            "observed_objects": [{"object_id": "cup_1"}],
            "target_candidates": [{"object_id": "cup_1"}],
        },
    }
    second_map = {
        **first_map,
        "runtime_metric_map": {
            "observed_objects": [{"object_id": "cup_1"}, {"object_id": "book_1"}],
            "target_candidates": [{"object_id": "cup_1"}, {"object_id": "book_1"}],
        },
    }
    items = [
        {
            "type": "function_call_output",
            "call_id": "call_metric_map_first",
            "output": json.dumps(first_map),
        },
        {
            "type": "function_call_output",
            "call_id": "call_metric_map_second",
            "output": json.dumps(second_map),
        },
    ]

    filtered, metrics = _compact_model_input_items(items, min_chars=999_999)

    assert filtered[0] == items[0]
    replacement = json.loads(filtered[1]["output"])
    assert replacement["schema"] == "roboclaws_repeated_metric_map_delta_summary_v1"
    assert replacement["map_id"] == "home"
    assert replacement["inspection_waypoint_count"] == 80
    assert replacement["runtime_observed_object_count"] == 2
    assert "book_1" not in json.dumps(filtered[1])
    assert metrics["metric_map_output_count"] == 2
    assert metrics["repeated_metric_map_output_count"] == 1
    assert metrics["metric_map_delta_compacted_count"] == 1
    assert metrics["metric_map_bytes_after"] < metrics["metric_map_bytes_before"]
    assert metrics["metric_map_bytes_reduced"] > 0


def test_model_input_compaction_keeps_first_metric_map_output_with_opaque_call_ids() -> None:
    first_map = {
        "ok": True,
        "tool": "metric_map",
        "map_id": "home",
        "map_version": "v1",
        "inspection_waypoints": [
            {
                "waypoint_id": f"room_{idx}_inspection",
                "room_id": f"room_{idx}",
                "label": "inspection waypoint",
            }
            for idx in range(80)
        ],
    }
    second_map = {
        **first_map,
        "map_version": "v2",
        "runtime_metric_map": {"observed_objects": [{"object_id": "book_1"}]},
    }
    items = [
        {"type": "function_call", "call_id": "call_opaque_1", "name": "metric_map"},
        {
            "type": "function_call_output",
            "call_id": "call_opaque_1",
            "output": json.dumps(first_map),
        },
        {"type": "function_call", "call_id": "call_opaque_2", "name": "metric_map"},
        {
            "type": "function_call_output",
            "call_id": "call_opaque_2",
            "output": json.dumps(second_map),
        },
    ]

    filtered, metrics = _compact_model_input_items(items, min_chars=1200)

    assert filtered[1] == items[1]
    replacement = json.loads(filtered[3]["output"])
    assert replacement["schema"] == "roboclaws_repeated_metric_map_delta_summary_v1"
    assert replacement["map_version"] == "v2"
    assert replacement["inspection_waypoint_count"] == 80
    assert "room_79_inspection" in filtered[1]["output"]
    assert "room_79_inspection" not in filtered[3]["output"]
    assert metrics["metric_map_output_count"] == 2
    assert metrics["repeated_metric_map_output_count"] == 1
    assert metrics["metric_map_delta_compacted_count"] == 1
    assert metrics["metric_map_bytes_before"] > metrics["metric_map_bytes_after"]


def test_model_input_compaction_evicted_raw_fpv_images_keep_latest_frame() -> None:
    items = [
        {
            "type": "function_call_output",
            "call_id": "observe_raw_fpv_001",
            "output": json.dumps(
                {
                    "schema": "raw_fpv_mcp_observe_state_v1",
                    "raw_fpv_observation": {"observation_id": "raw_fpv_001"},
                }
            ),
        },
        {
            "type": "image",
            "_mime_type": "image/png",
            "_format": "png",
            "data": "raw_fpv_001:" + ("a" * 3_000),
        },
        {
            "type": "function_call_output",
            "call_id": "observe_raw_fpv_002",
            "output": json.dumps(
                {
                    "schema": "raw_fpv_mcp_observe_state_v1",
                    "raw_fpv_observation": {"observation_id": "raw_fpv_002"},
                }
            ),
        },
        {
            "type": "image",
            "_mime_type": "image/png",
            "_format": "png",
            "data": "raw_fpv_002:" + ("b" * 3_000),
        },
    ]

    filtered, metrics = _compact_model_input_items(
        items,
        min_chars=999_999,
        public_tool_output_summary=False,
        repeated_metric_map_delta=False,
        raw_fpv_image_memory={
            "enabled": True,
            "mode": "retain_latest_full_frame",
            "retained_full_frame_limit": 1,
        },
    )

    assert filtered[0] == items[0]
    assert filtered[2] == items[2]
    evicted = filtered[1]
    assert evicted["schema"] == "raw_fpv_evicted_image_frame_summary_v1"
    assert evicted["observation_id"] == "raw_fpv_001"
    assert evicted["original_data_bytes"] > 0
    assert "a" * 20 not in json.dumps(evicted)
    assert filtered[3] == items[3]
    assert metrics["raw_fpv_image_memory_enabled"] is True
    assert metrics["raw_fpv_image_item_count"] == 2
    assert metrics["raw_fpv_image_retained_count"] == 1
    assert metrics["raw_fpv_image_evicted_count"] == 1
    assert metrics["raw_fpv_image_bytes_after"] < metrics["raw_fpv_image_bytes_before"]
    assert metrics["raw_fpv_image_bytes_reduced"] > 0


def test_model_input_compaction_handles_sdk_nested_raw_fpv_images() -> None:
    def observe_output(observation_id: str, image_byte: str) -> dict[str, object]:
        return {
            "type": "function_call_output",
            "call_id": f"observe_{observation_id}",
            "output": [
                {
                    "type": "input_text",
                    "text": json.dumps(
                        {
                            "schema": "raw_fpv_mcp_observe_state_v1",
                            "raw_fpv_observation": {"observation_id": observation_id},
                        }
                    ),
                },
                {
                    "type": "input_image",
                    "image_url": f"data:image/png;base64,{image_byte * 3_000}",
                },
            ],
        }

    items = [observe_output("raw_fpv_001", "a"), observe_output("raw_fpv_002", "b")]

    filtered, metrics = _compact_model_input_items(
        items,
        min_chars=1200,
        raw_fpv_image_memory={
            "enabled": True,
            "mode": "retain_latest_full_frame",
            "retained_full_frame_limit": 1,
        },
    )

    assert filtered[0]["output"][0] == items[0]["output"][0]
    evicted = filtered[0]["output"][1]
    assert evicted["type"] == "input_text"
    evicted_summary = json.loads(evicted["text"])
    assert evicted_summary["schema"] == "raw_fpv_evicted_image_frame_summary_v1"
    assert evicted_summary["observation_id"] == "raw_fpv_001"
    assert "a" * 20 not in json.dumps(filtered[0])
    assert filtered[1] == items[1]
    assert filtered[1]["output"][1]["type"] == "input_image"
    assert metrics["raw_fpv_image_item_count"] == 2
    assert metrics["raw_fpv_image_retained_count"] == 1
    assert metrics["raw_fpv_image_evicted_count"] == 1


def test_model_input_compaction_does_not_summarize_latest_sdk_raw_fpv_image() -> None:
    item = {
        "type": "function_call_output",
        "call_id": "observe_raw_fpv_001",
        "output": [
            {
                "type": "input_text",
                "text": json.dumps(
                    {
                        "schema": "raw_fpv_mcp_observe_state_v1",
                        "raw_fpv_observation": {"observation_id": "raw_fpv_001"},
                    }
                ),
            },
            {"type": "input_image", "image_url": "data:image/png;base64," + "a" * 3_000},
        ],
    }

    filtered, metrics = _compact_model_input_items(
        [item],
        min_chars=1200,
        public_tool_output_summary=True,
        raw_fpv_image_memory={
            "enabled": True,
            "mode": "retain_latest_full_frame",
            "retained_full_frame_limit": 1,
        },
    )

    assert filtered == [item]
    assert metrics["compacted_item_count"] == 0
    assert metrics["raw_fpv_image_item_count"] == 1
    assert metrics["raw_fpv_image_retained_count"] == 1


def test_model_input_compaction_summarizes_old_camera_grounded_history() -> None:
    def camera_output(idx: int) -> dict[str, object]:
        return {
            "ok": True,
            "status": "ok",
            "tool": "observe_camera_grounded_candidates",
            "observation_id": f"raw_fpv_{idx:03d}",
            "waypoint_id": f"generated_exploration_{idx:03d}",
            "room_id": f"room_{idx}",
            "camera_model_candidates": [
                {
                    "object_id": f"observed_{idx:03d}",
                    "category": "Potato",
                    "recommended_tool": "place_inside",
                    "cleanup_recommended": True,
                    "visual_grounding_evidence": {
                        "candidate_state": "navigation_authorized",
                        "source_observation_id": f"raw_fpv_{idx:03d}",
                    },
                    "large_public_camera_payload": "x" * 5000,
                }
            ],
            "raw_fpv_observation": {
                "observation_id": f"raw_fpv_{idx:03d}",
                "public_camera_diagnostics": "y" * 5000,
            },
        }

    items = [
        {
            "type": "function_call_output",
            "call_id": f"call_observe_camera_grounded_candidates_{idx}",
            "output": json.dumps(camera_output(idx)),
        }
        for idx in range(1, 4)
    ]

    filtered, metrics = _compact_model_input_items(
        items,
        min_chars=999_999,
        public_tool_output_summary=False,
        repeated_metric_map_delta=False,
        camera_grounded_history={
            "enabled": True,
            "mode": "retain_latest_actionable_outputs",
            "retained_recent_outputs": 1,
        },
    )

    first_replacement = json.loads(filtered[0]["output"])
    assert first_replacement["schema"] == "roboclaws_camera_grounded_history_summary_v1"
    assert first_replacement["tool"] == "observe_camera_grounded_candidates"
    assert first_replacement["observation_id"] == "raw_fpv_001"
    assert first_replacement["candidate_count"] == 1
    assert first_replacement["actionable_candidate_count"] == 1
    assert first_replacement["candidate_refs"] == [
        {
            "object_id": "observed_001",
            "category": "Potato",
            "recommended_tool": "place_inside",
            "source_observation_id": "raw_fpv_001",
            "cleanup_recommended": True,
            "candidate_state": "navigation_authorized",
        }
    ]
    assert "large_public_camera_payload" not in json.dumps(filtered[0])
    assert "public_camera_diagnostics" not in json.dumps(filtered[0])
    assert (
        json.loads(filtered[-1]["output"])["raw_fpv_observation"]["public_camera_diagnostics"]
        == "y" * 5000
    )
    assert metrics["camera_grounded_history_enabled"] is True
    assert metrics["camera_grounded_history_item_count"] == 3
    assert metrics["camera_grounded_history_retained_count"] == 1
    assert metrics["camera_grounded_history_compacted_count"] == 2
    assert (
        metrics["camera_grounded_history_bytes_after"]
        < metrics["camera_grounded_history_bytes_before"]
    )
    assert metrics["camera_grounded_history_bytes_reduced"] > 0


def test_model_input_compaction_summarizes_prefixed_mcp_camera_grounded_history() -> None:
    def camera_output(idx: int) -> dict[str, object]:
        return {
            "ok": True,
            "status": "ok",
            "observation_id": f"raw_fpv_{idx:03d}",
            "waypoint_id": f"generated_exploration_{idx:03d}",
            "camera_model_candidates": [
                {
                    "object_id": f"observed_{idx:03d}",
                    "category": "Book",
                    "recommended_tool": "place",
                    "actionability_status": "actionable",
                    "large_public_camera_payload": "x" * 5000,
                }
            ],
        }

    items = [
        {
            "type": "mcp_call",
            "id": f"mcp_{idx}",
            "name": "roboclaws__observe_camera_grounded_candidates",
            "server_label": "roboclaws",
            "arguments": "{}",
            "output": json.dumps(camera_output(idx)),
            "status": "completed",
        }
        for idx in range(1, 4)
    ]

    filtered, metrics = _compact_model_input_items(
        items,
        min_chars=999_999,
        public_tool_output_summary=False,
        repeated_metric_map_delta=False,
        camera_grounded_history={
            "enabled": True,
            "mode": "retain_latest_actionable_outputs",
            "retained_recent_outputs": 1,
        },
    )

    first_replacement = json.loads(filtered[0]["output"])
    assert first_replacement["schema"] == "roboclaws_camera_grounded_history_summary_v1"
    assert first_replacement["tool"] == "observe_camera_grounded_candidates"
    assert first_replacement["observation_id"] == "raw_fpv_001"
    assert first_replacement["candidate_count"] == 1
    assert first_replacement["actionable_candidate_count"] == 1
    assert "large_public_camera_payload" not in json.dumps(filtered[0])
    assert json.loads(filtered[-1]["output"])["camera_model_candidates"][0][
        "large_public_camera_payload"
    ] == ("x" * 5000)
    assert metrics["camera_grounded_history_enabled"] is True
    assert metrics["camera_grounded_history_item_count"] == 3
    assert metrics["camera_grounded_history_retained_count"] == 1
    assert metrics["camera_grounded_history_compacted_count"] == 2
    assert metrics["camera_grounded_history_bytes_reduced"] > 0


def test_model_input_compaction_summarizes_wrapped_mcp_camera_grounded_history() -> None:
    def camera_output(idx: int) -> dict[str, object]:
        return {
            "ok": True,
            "status": "ok",
            "observation_id": f"raw_fpv_{idx:03d}",
            "waypoint_id": f"generated_exploration_{idx:03d}",
            "camera_model_candidates": [
                {
                    "object_id": f"wrapped_{idx:03d}",
                    "category": "Bottle",
                    "recommended_tool": "place_inside",
                    "cleanup_recommended": True,
                    "large_public_camera_payload": "x" * 5000,
                }
            ],
        }

    items = []
    for idx in range(1, 4):
        text_content = [{"type": "text", "text": json.dumps(camera_output(idx))}]
        output: object = (
            {"content": text_content}
            if idx == 1
            else text_content
            if idx == 2
            else json.dumps({"content": text_content})
        )
        items.append(
            {
                "type": "mcp_call",
                "id": f"mcp_{idx}",
                "name": "roboclaws__observe_camera_grounded_candidates",
                "server_label": "roboclaws",
                "arguments": "{}",
                "output": output,
                "status": "completed",
            }
        )

    filtered, metrics = _compact_model_input_items(
        items,
        min_chars=999_999,
        public_tool_output_summary=False,
        repeated_metric_map_delta=False,
        camera_grounded_history={
            "enabled": True,
            "mode": "retain_latest_actionable_outputs",
            "retained_recent_outputs": 1,
        },
    )

    first_replacement = json.loads(filtered[0]["output"])
    second_replacement = json.loads(filtered[1]["output"])
    assert first_replacement["schema"] == "roboclaws_camera_grounded_history_summary_v1"
    assert second_replacement["schema"] == "roboclaws_camera_grounded_history_summary_v1"
    assert first_replacement["tool"] == "observe_camera_grounded_candidates"
    assert first_replacement["observation_id"] == "raw_fpv_001"
    assert first_replacement["candidate_count"] == 1
    assert first_replacement["actionable_candidate_count"] == 1
    assert "large_public_camera_payload" not in json.dumps(filtered[0])
    assert "large_public_camera_payload" not in json.dumps(filtered[1])
    retained_output = json.loads(filtered[-1]["output"])["content"][0]["text"]
    assert json.loads(retained_output)["camera_model_candidates"][0][
        "large_public_camera_payload"
    ] == ("x" * 5000)
    assert metrics["camera_grounded_history_enabled"] is True
    assert metrics["camera_grounded_history_item_count"] == 3
    assert metrics["camera_grounded_history_retained_count"] == 1
    assert metrics["camera_grounded_history_compacted_count"] == 2
    assert metrics["camera_grounded_history_bytes_reduced"] > 0


def test_model_input_compaction_summarizes_named_mcp_camera_history_without_json_output() -> None:
    items = [
        {
            "type": "mcp_call",
            "id": f"mcp_{idx}",
            "name": "roboclaws__observe_camera_grounded_candidates",
            "server_label": "roboclaws",
            "arguments": "{}",
            "output": "MCP tool output body unavailable in structured JSON. " + ("x" * 5000),
            "status": "completed",
        }
        for idx in range(1, 4)
    ]

    filtered, metrics = _compact_model_input_items(
        items,
        min_chars=999_999,
        public_tool_output_summary=False,
        repeated_metric_map_delta=False,
        camera_grounded_history={
            "enabled": True,
            "mode": "retain_latest_actionable_outputs",
            "retained_recent_outputs": 1,
        },
    )

    first_replacement = json.loads(filtered[0]["output"])
    assert first_replacement["schema"] == "roboclaws_camera_grounded_history_summary_v1"
    assert first_replacement["tool"] == "observe_camera_grounded_candidates"
    assert first_replacement["candidate_count"] == 0
    assert "x" * 100 not in json.dumps(filtered[0])
    assert "x" * 100 in json.dumps(filtered[-1])
    assert metrics["camera_grounded_history_item_count"] == 3
    assert metrics["camera_grounded_history_retained_count"] == 1
    assert metrics["camera_grounded_history_compacted_count"] == 2
    assert metrics["camera_grounded_history_bytes_reduced"] > 0


def test_model_input_compaction_summarizes_function_call_camera_history_by_call_id() -> None:
    def camera_output(idx: int) -> dict[str, object]:
        return {
            "ok": True,
            "status": "ok",
            "observation_id": f"raw_fpv_{idx:03d}",
            "camera_model_candidates": [
                {
                    "object_id": f"function_{idx:03d}",
                    "category": "Book",
                    "recommended_tool": "place",
                    "actionability_status": "actionable",
                    "large_public_camera_payload": "x" * 5000,
                }
            ],
        }

    items = []
    for idx in range(1, 4):
        call_id = f"call_camera_{idx}"
        items.extend(
            [
                {
                    "type": "function_call",
                    "id": f"fc_{idx}",
                    "call_id": call_id,
                    "name": "roboclaws__observe_camera_grounded_candidates",
                    "arguments": "{}",
                    "status": "completed",
                },
                {
                    "type": "function_call_output",
                    "call_id": call_id,
                    "output": json.dumps(camera_output(idx)),
                },
            ]
        )

    filtered, metrics = _compact_model_input_items(
        items,
        min_chars=999_999,
        public_tool_output_summary=False,
        repeated_metric_map_delta=False,
        camera_grounded_history={
            "enabled": True,
            "mode": "retain_latest_actionable_outputs",
            "retained_recent_outputs": 1,
        },
    )

    first_output_item = filtered[1]
    first_replacement = json.loads(first_output_item["output"])
    assert first_replacement["schema"] == "roboclaws_camera_grounded_history_summary_v1"
    assert first_replacement["tool"] == "observe_camera_grounded_candidates"
    assert first_replacement["observation_id"] == "raw_fpv_001"
    assert first_replacement["candidate_count"] == 1
    assert first_replacement["actionable_candidate_count"] == 1
    assert "large_public_camera_payload" not in json.dumps(first_output_item)
    assert json.loads(filtered[-1]["output"])["camera_model_candidates"][0][
        "large_public_camera_payload"
    ] == ("x" * 5000)
    assert metrics["camera_grounded_history_item_count"] == 3
    assert metrics["camera_grounded_history_retained_count"] == 1
    assert metrics["camera_grounded_history_compacted_count"] == 2
    assert metrics["camera_grounded_history_bytes_reduced"] > 0


def test_openai_agents_runtime_can_use_kimi_openai_chat_profile(
    tmp_path: Path, monkeypatch
) -> None:
    captured: dict[str, object] = {}

    class FakeOpenAIChatCompletionsModel:
        def __init__(self, model: str, *, openai_client: object) -> None:
            captured["model"] = model

    class FakeAsyncOpenAI:
        def __init__(
            self,
            *,
            api_key: str,
            base_url: str,
            default_headers: dict[str, str] | None = None,
        ) -> None:
            captured["api_key"] = api_key
            captured["base_url"] = base_url

    monkeypatch.setenv("KIMI_API_KEY", "fake-kimi-key")
    monkeypatch.setattr(
        "roboclaws.agents.drivers.openai_agents_live._run_with_async_mcp_server",
        lambda *_args, **_kwargs: SimpleNamespace(final_output="done"),
    )
    monkeypatch.setitem(
        __import__("sys").modules,
        "agents",
        SimpleNamespace(
            Agent=lambda **kwargs: captured.setdefault("agent_kwargs", kwargs),
            Runner=SimpleNamespace(run_sync=lambda *_args, **_kwargs: SimpleNamespace()),
            ModelSettings=FakeModelSettings,
            RunConfig=FakeRunConfig,
            OpenAIChatCompletionsModel=FakeOpenAIChatCompletionsModel,
        ),
    )
    monkeypatch.setitem(
        __import__("sys").modules,
        "agents.mcp",
        SimpleNamespace(
            MCPServerStreamableHttp=lambda **kwargs: (
                captured.setdefault("mcp_server_kwargs", kwargs) or SimpleNamespace(kwargs=kwargs)
            )
        ),
    )
    monkeypatch.setitem(
        __import__("sys").modules,
        "openai",
        SimpleNamespace(AsyncOpenAI=FakeAsyncOpenAI),
    )
    request = LiveAgentRequest(
        run_id="household-world",
        skill_name="household-world",
        kickoff_prompt="clean the room",
        mcp_server=LiveAgentMCPServer(name="cleanup", url="http://127.0.0.1:18788/mcp"),
        run_dir=tmp_path / "run",
        provider_profile="kimi-openai-chat",
    )

    OpenAIAgentsLiveRuntime().run(request)

    assert captured["model"] == "kimi-k2.7-code"
    assert captured["base_url"] == "https://api.kimi.com/coding/v1"
    assert captured["api_key"] == "fake-kimi-key"
    assert captured["agent_kwargs"]["model_settings"].extra_headers == {
        "User-Agent": "claude-code/1.0.0"
    }
    assert not hasattr(captured["agent_kwargs"]["model_settings"], "extra_body")


def test_openai_agents_runtime_allows_disabling_mcp_tool_list_cache(
    tmp_path: Path, monkeypatch
) -> None:
    captured: dict[str, object] = {}

    class FakeOpenAIResponsesModel:
        def __init__(self, model: str, *, openai_client: object) -> None:
            captured["model"] = model

    class FakeAsyncOpenAI:
        def __init__(
            self,
            *,
            api_key: str,
            base_url: str,
            default_headers: dict[str, str] | None = None,
        ) -> None:
            pass

    monkeypatch.setenv("CODEX_BASE_URL", "https://codex.example.test/v1")
    monkeypatch.setenv("CODEX_API_KEY", "fake-codex-key")
    monkeypatch.setattr(
        "roboclaws.agents.drivers.openai_agents_live._run_with_async_mcp_server",
        lambda *_args, **_kwargs: SimpleNamespace(final_output="done"),
    )
    monkeypatch.setitem(
        __import__("sys").modules,
        "agents",
        SimpleNamespace(
            Agent=lambda **kwargs: captured.setdefault("agent_kwargs", kwargs),
            Runner=SimpleNamespace(run_sync=lambda *_args, **_kwargs: SimpleNamespace()),
            ModelSettings=FakeModelSettings,
            RunConfig=FakeRunConfig,
            OpenAIResponsesModel=FakeOpenAIResponsesModel,
        ),
    )
    monkeypatch.setitem(
        __import__("sys").modules,
        "agents.mcp",
        SimpleNamespace(
            MCPServerStreamableHttp=lambda **kwargs: (
                captured.setdefault("mcp_server_kwargs", kwargs) or SimpleNamespace(kwargs=kwargs)
            )
        ),
    )
    monkeypatch.setitem(
        __import__("sys").modules,
        "openai",
        SimpleNamespace(AsyncOpenAI=FakeAsyncOpenAI),
    )
    request = LiveAgentRequest(
        run_id="household-world",
        skill_name="household-world",
        kickoff_prompt="clean the room",
        mcp_server=LiveAgentMCPServer(name="cleanup", url="http://127.0.0.1:18788/mcp"),
        run_dir=tmp_path / "run",
        metadata={"cache_tools_list": False},
    )

    OpenAIAgentsLiveRuntime().run(request)

    assert captured["mcp_server_kwargs"]["cache_tools_list"] is False


def test_openai_agents_runtime_rejects_invalid_cache_tools_metadata(
    tmp_path: Path, monkeypatch
) -> None:
    monkeypatch.setenv("CODEX_BASE_URL", "https://codex.example.test/v1")
    monkeypatch.setenv("CODEX_API_KEY", "fake-codex-key")
    request = LiveAgentRequest(
        run_id="household-world",
        skill_name="household-world",
        kickoff_prompt="clean the room",
        mcp_server=LiveAgentMCPServer(name="cleanup", url="http://127.0.0.1:18788/mcp"),
        run_dir=tmp_path / "run",
        metadata={"cache_tools_list": "sometimes"},
    )

    result = OpenAIAgentsLiveRuntime().run(request)

    assert result.phase == "failed"
    assert result.exit_status == 1
    assert result.reason == "provider_config_failure"
    assert "OpenAI Agents SDK setting cache_tools_list must be true or false" in result.detail
    payload = json.loads((tmp_path / "run" / "live_status.json").read_text(encoding="utf-8"))
    assert payload["reason"] == "provider_config_failure"
    assert "OpenAI Agents SDK setting cache_tools_list must be true or false" in payload["detail"]


def test_openai_agents_live_runner_rejects_invalid_cache_tools_env(monkeypatch) -> None:
    monkeypatch.setenv("ROBOCLAWS_OPENAI_AGENTS_CACHE_TOOLS_LIST", "sometimes")

    with pytest.raises(ValueError, match="ROBOCLAWS_OPENAI_AGENTS_CACHE_TOOLS_LIST"):
        _parse_live_openai_agents_args([])


def test_openai_agents_runtime_configures_mcp_client_session_timeout(
    tmp_path: Path, monkeypatch
) -> None:
    captured: dict[str, object] = {}

    class FakeOpenAIResponsesModel:
        def __init__(self, model: str, *, openai_client: object) -> None:
            captured["model"] = model

    class FakeAsyncOpenAI:
        def __init__(
            self,
            *,
            api_key: str,
            base_url: str,
            default_headers: dict[str, str] | None = None,
        ) -> None:
            pass

    monkeypatch.setenv("CODEX_BASE_URL", "https://codex.example.test/v1")
    monkeypatch.setenv("CODEX_API_KEY", "fake-codex-key")
    monkeypatch.setenv("ROBOCLAWS_OPENAI_AGENTS_MCP_CLIENT_SESSION_TIMEOUT_S", "30")
    monkeypatch.setattr(
        "roboclaws.agents.drivers.openai_agents_live._run_with_async_mcp_server",
        lambda *_args, **_kwargs: SimpleNamespace(final_output="done"),
    )
    monkeypatch.setitem(
        __import__("sys").modules,
        "agents",
        SimpleNamespace(
            Agent=lambda **kwargs: captured.setdefault("agent_kwargs", kwargs),
            Runner=SimpleNamespace(run_sync=lambda *_args, **_kwargs: SimpleNamespace()),
            ModelSettings=FakeModelSettings,
            RunConfig=FakeRunConfig,
            OpenAIResponsesModel=FakeOpenAIResponsesModel,
        ),
    )
    monkeypatch.setitem(
        __import__("sys").modules,
        "agents.mcp",
        SimpleNamespace(
            MCPServerStreamableHttp=lambda **kwargs: (
                captured.setdefault("mcp_server_kwargs", kwargs) or SimpleNamespace(kwargs=kwargs)
            )
        ),
    )
    monkeypatch.setitem(
        __import__("sys").modules,
        "openai",
        SimpleNamespace(AsyncOpenAI=FakeAsyncOpenAI),
    )
    request = LiveAgentRequest(
        run_id="household-world",
        skill_name="household-world",
        kickoff_prompt="clean the room",
        mcp_server=LiveAgentMCPServer(name="cleanup", url="http://127.0.0.1:18788/mcp"),
        run_dir=tmp_path / "run",
    )

    OpenAIAgentsLiveRuntime().run(request)

    assert captured["mcp_server_kwargs"]["client_session_timeout_seconds"] == 30.0
    events = [
        json.loads(line)
        for line in (tmp_path / "run" / "openai-agents-events.jsonl").read_text().splitlines()
    ]
    assert events[0]["event"] == "start"
    assert events[0]["mcp_client_session_timeout_s"] == 30.0


def test_openai_agents_cleanup_runner_invokes_sdk_then_checker(tmp_path: Path, monkeypatch) -> None:
    run_dir = tmp_path / "run"
    checker_commands: list[list[str]] = []

    class FakeProcess:
        pid = 4242

        def __init__(self, *_args, **_kwargs) -> None:
            self._poll: int | None = None

        def poll(self) -> int | None:
            return self._poll

        def wait(self, timeout: float | None = None) -> int:
            self._poll = 0
            return 0

        def terminate(self) -> None:
            self._poll = 0

        def kill(self) -> None:
            self._poll = 0

    class FakeRuntime:
        def run(self, request: LiveAgentRequest) -> LiveAgentResult:
            assert request.mcp_server.url == "http://127.0.0.1:18788/mcp"
            assert request.provider_profile == "codex-router-responses"
            (request.run_dir / "run_result.json").write_text(
                json.dumps(
                    {
                        "task": "clean",
                        "task_name": "household-cleanup",
                        "backend": "molmospaces_subprocess",
                        "policy": "openai_agents_agent",
                        "cleanup_success": True,
                    }
                ),
                encoding="utf-8",
            )
            (request.run_dir / "openai-agents-events.jsonl").write_text(
                '{"event":"result"}\n',
                encoding="utf-8",
            )
            (request.run_dir / "openai-agents-trace.json").write_text(
                '{"trace_id":"trace_1"}\n',
                encoding="utf-8",
            )
            return LiveAgentResult(
                phase="finished",
                exit_status=0,
                trace_id="trace_1",
                run_result_present=True,
                usage={"requests": 1},
            )

    monkeypatch.setattr(
        "scripts.molmo_cleanup.run_live_openai_agents_cleanup.subprocess.Popen",
        FakeProcess,
    )
    port_checks = iter([False, True])
    monkeypatch.setattr(
        "scripts.molmo_cleanup.run_live_openai_agents_cleanup._port_accepting",
        lambda *_args, **_kwargs: next(port_checks),
    )
    monkeypatch.setattr(
        "scripts.molmo_cleanup.run_live_openai_agents_cleanup.OpenAIAgentsLiveRuntime",
        lambda: FakeRuntime(),
    )

    def fake_run_and_tee(command, *, cwd, stdout_path, stderr_path, env):
        checker_commands.append(command)
        stdout_path.write_text("checker ok\n", encoding="utf-8")
        return 0

    monkeypatch.setattr(
        "scripts.molmo_cleanup.run_live_openai_agents_cleanup._run_and_tee",
        fake_run_and_tee,
    )
    lock_path = tmp_path / "live.lock"
    args = Namespace(
        run_dir=run_dir,
        repo_root=_isolated_repo_root(tmp_path),
        status_path=run_dir / "live_status.json",
        client_url="http://127.0.0.1:18788/mcp",
        host="127.0.0.1",
        port=18788,
        lock_path=lock_path,
        provider_profile="codex-router-responses",
        model="gpt-5.5",
        max_turns=128,
        mcp_client_session_timeout_s=30.0,
        agent_sdk_perf_profile="",
        continuation_mode="",
        context_soft_limit_tokens=None,
        context_hard_limit_tokens=None,
        max_observe_per_waypoint=None,
        raw_fpv_candidate_budget=None,
        done_retry_budget=None,
        model_service_retry_attempts=None,
        model_service_retry_sleep_s=None,
        server_startup_timeout_s=1.0,
        kickoff_prompt="clean the room",
        backend="molmospaces_subprocess",
        run_id="household-world",
        policy="openai_agents_agent",
        task="clean",
        min_generated_mess_count="5",
        profile="smoke",
        server_arg=[],
        checker_visual_arg=[],
    )

    status = LiveOpenAIAgentsCleanupRunner(args).run()

    assert status == 0
    status_payload = json.loads((run_dir / "live_status.json").read_text(encoding="utf-8"))
    assert status_payload["phase"] == "finished"
    assert status_payload["exit_status"] == 0
    timing = json.loads((run_dir / "live_timing.json").read_text(encoding="utf-8"))
    _assert_context_managed_openai_agents_timing(timing)
    _assert_openai_agents_timeline_and_checker(timing, checker_commands)


def _assert_context_managed_openai_agents_timing(timing: dict[str, object]) -> None:
    assert timing["runtime"] == "openai-agents-live"
    assert timing["surface"] == "household-world"
    assert timing["intent"] == "cleanup"
    assert timing["task_name"] == "household-world"
    assert timing["evidence_lane"] == "smoke"
    assert timing["mcp_client_session_timeout_s"] == 30.0
    assert timing["agent_sdk_perf_profile"]["schema"] == "agent_sdk_perf_profile_v1"
    assert timing["agent_sdk_perf_profile"]["profile_id"] == "context_managed_v1"
    assert timing["agent_sdk_perf_profile"]["source"] == "default"
    assert timing["agent_sdk_perf_profile"]["continuation_mode"] == "state_summary_only"
    assert timing["agent_sdk_perf_profile"]["max_turns"] == 128
    assert timing["agent_sdk_perf_profile"]["max_observe_per_waypoint"] == 1
    assert timing["agent_sdk_perf_profile"]["context_hard_limit_tokens"] == 128_000
    assert timing["agent_sdk_perf_profile"]["model_input_compaction"]["enabled"] is True
    assert (
        timing["agent_sdk_perf_profile"]["context_policy"]["provider_native_compaction"]["mode"]
        == "off"
    )
    assert timing["agent_sdk_perf_profile"]["model_service_retry_attempts"] == 1
    assert timing["agent_sdk_perf_profile"]["model_service_retry_sleep_s"] == 1.0
    assert timing["agent_sdk_perf_profile"]["model_racing_observability"] == (
        _expected_model_racing_observability()
    )
    assert timing["agent_sdk_perf_profile"]["sdk_model_settings"] == {
        "model_thinking_mode": "default",
        "parallel_tool_calls": False,
        "prompt_cache_retention": "in_memory",
        "store": False,
        "tool_choice": "auto",
    }
    assert timing["agent_sdk_perf_profile"]["sdk_run_config"] == {
        "trace_include_sensitive_data": False,
        "workflow_name": "roboclaws-openai-agents-live",
    }
    assert timing["kickoff_prompt_stable_prefix"]["schema"] == "agent_sdk_stable_prefix_v1"
    assert timing["kickoff_prompt_stable_prefix"]["hash"]
    assert (
        timing["cache_metrics"]["stable_prefix_hash"]
        == timing["kickoff_prompt_stable_prefix"]["hash"]
    )
    assert timing["openai_agents"]["trace_id"] == "trace_1"
    assert timing["mcp_control_plane_metrics"]["available"] is False
    assert timing["openai_agents_event_metrics"]["available"] is True
    assert timing["openai_agents_span_metrics"]["available"] is False


def _assert_openai_agents_timeline_and_checker(
    timing: dict[str, object], checker_commands: list[list[str]]
) -> None:
    assert timing["timeline"]["schema"] == "live_agent_timeline_v1"
    assert timing["timeline"]["surface"] == "household-world"
    assert timing["timeline"]["intent"] == "cleanup"
    assert timing["timeline"]["runtime"] == "openai-agents-live"
    assert timing["timeline"]["evidence_lane"] == "smoke"
    assert [item["name"] for item in timing["timeline"]["runner_segments"]] == [
        "pre_agent_setup",
        "openai_agents_runtime",
        "post_agent_server_wait",
        "checker",
        "final_overhead",
    ]
    assert timing["timeline"]["latency_attribution"]["mcp_client_session_timeout_s"] == 30.0
    assert checker_commands
    checker_command = checker_commands[0]
    assert "scripts/molmo_cleanup/check_molmo_realworld_cleanup_result.py" in checker_command
    assert "--expect-policy" in checker_command
    assert "openai_agents_agent" in checker_command
    assert "--require-clean-agent-run" in checker_command


@pytest.mark.parametrize(
    ("source_name", "source_text", "expected_detail"),
    [
        ("run_result.json", "{not-json}\n", "run_result.json: invalid JSON"),
        ("run_result.json", "[1]\n", "run_result.json: non-object JSON: list"),
        (
            "trace.jsonl",
            json.dumps({"event": "request", "tool": "done"}) + "\n[]\n",
            "OpenAI Agents live source row must contain a JSON object",
        ),
    ],
)
def test_openai_agents_live_timing_fails_aloud_on_malformed_mcp_timing_source(
    tmp_path: Path,
    source_name: str,
    source_text: str,
    expected_detail: str,
) -> None:
    run_dir = tmp_path / "run"
    run_dir.mkdir()
    args = _parse_live_openai_agents_args(
        [
            "--run-dir",
            str(run_dir),
            "--repo-root",
            str(_isolated_repo_root(tmp_path)),
            "--status-path",
            str(run_dir / "live_status.json"),
            "--provider-profile",
            "codex-router-responses",
            "--model",
            "gpt-5.5",
            "--client-url",
            "http://127.0.0.1:18788/mcp",
            "--host",
            "127.0.0.1",
            "--port",
            "18788",
            "--lock-path",
            str(tmp_path / "live.lock"),
            "--server-startup-timeout-s",
            "1",
            "--kickoff-prompt",
            "clean the room",
            "--backend",
            "molmospaces_subprocess",
            "--task",
            "clean",
            "--min-generated-mess-count",
            "5",
            "--profile",
            "smoke",
        ]
    )
    runner = LiveOpenAIAgentsCleanupRunner(args)
    (run_dir / source_name).write_text(source_text, encoding="utf-8")

    source_error = runner._write_live_timing("finished", 0)

    timing = json.loads((run_dir / "live_timing.json").read_text(encoding="utf-8"))
    assert source_error.startswith("live_timing_source_error: OpenAI Agents live source")
    assert expected_detail in source_error
    assert timing["phase"] == "failed"
    assert timing["exit_status"] == 1
    assert timing["reason"] == source_error
    assert timing["live_timing_source_error"] == source_error
    assert timing["mcp_trace_timing"]["available"] is False
    assert expected_detail in timing["mcp_trace_timing"]["source_error"]


def test_openai_agents_camera_grounded_composite_profile_adds_private_server_flag(
    tmp_path: Path,
    monkeypatch,
) -> None:
    run_dir = tmp_path / "run"
    server_commands: list[list[str]] = []
    prompts: list[str] = []

    class FakeProcess:
        pid = 4242

        def __init__(self, command, *_args, **_kwargs) -> None:
            server_commands.append(list(command))
            self._poll: int | None = None

        def poll(self) -> int | None:
            return self._poll

        def wait(self, timeout: float | None = None) -> int:
            self._poll = 0
            return 0

        def terminate(self) -> None:
            self._poll = 0

        def kill(self) -> None:
            self._poll = 0

    class FakeRuntime:
        def run(self, request: LiveAgentRequest) -> LiveAgentResult:
            prompts.append(request.kickoff_prompt)
            assert (
                request.metadata["agent_sdk_perf_profile"]["camera_grounded_composite_tools"][
                    "enabled"
                ]
                is True
            )
            (request.run_dir / "run_result.json").write_text(
                json.dumps(
                    {
                        "task": "clean",
                        "task_name": "household-cleanup",
                        "backend": "molmospaces_subprocess",
                        "policy": "openai_agents_agent",
                        "cleanup_success": True,
                    }
                ),
                encoding="utf-8",
            )
            return LiveAgentResult(phase="finished", exit_status=0, run_result_present=True)

    monkeypatch.setattr(
        "scripts.molmo_cleanup.run_live_openai_agents_cleanup.subprocess.Popen",
        FakeProcess,
    )
    port_checks = iter([False, True])
    monkeypatch.setattr(
        "scripts.molmo_cleanup.run_live_openai_agents_cleanup._port_accepting",
        lambda *_args, **_kwargs: next(port_checks),
    )
    monkeypatch.setattr(
        "scripts.molmo_cleanup.run_live_openai_agents_cleanup.OpenAIAgentsLiveRuntime",
        lambda: FakeRuntime(),
    )

    def fake_run_and_tee(command, *, cwd, stdout_path, stderr_path, env):
        stdout_path.write_text("checker ok\n", encoding="utf-8")
        return 0

    monkeypatch.setattr(
        "scripts.molmo_cleanup.run_live_openai_agents_cleanup._run_and_tee",
        fake_run_and_tee,
    )
    args = Namespace(
        run_dir=run_dir,
        repo_root=_isolated_repo_root(tmp_path),
        status_path=run_dir / "live_status.json",
        client_url="http://127.0.0.1:18788/mcp",
        host="127.0.0.1",
        port=18788,
        lock_path=tmp_path / "live.lock",
        provider_profile="codex-router-responses",
        model="gpt-5.5",
        max_turns=128,
        mcp_client_session_timeout_s=30.0,
        agent_sdk_perf_profile="context_managed_v1",
        continuation_mode="",
        model_input_compaction=None,
        model_input_compaction_min_chars=None,
        camera_grounded_composite_tools=True,
        context_soft_limit_tokens=None,
        context_hard_limit_tokens=None,
        max_observe_per_waypoint=None,
        raw_fpv_candidate_budget=None,
        done_retry_budget=None,
        model_service_retry_attempts=None,
        model_service_retry_sleep_s=None,
        server_startup_timeout_s=1.0,
        kickoff_prompt="clean the room",
        backend="molmospaces_subprocess",
        run_id="household-world",
        policy="openai_agents_agent",
        task="clean",
        min_generated_mess_count="5",
        profile="camera-grounded-labels",
        server_arg=[],
        checker_visual_arg=[],
    )

    status = LiveOpenAIAgentsCleanupRunner(args).run()

    assert status == 0
    assert server_commands
    assert prompts
    assert "observe_camera_grounded_candidates instead of a separate observe" in prompts[0]
    assert "do not call declare_visual_candidates again for the same" in prompts[0]
    assert "--agent-sdk-camera-grounded-composite-tools" in server_commands[0]
    timing = json.loads((run_dir / "live_timing.json").read_text(encoding="utf-8"))
    composite = timing["agent_sdk_perf_profile"]["camera_grounded_composite_tools"]
    assert composite["enabled"] is True
    assert composite["tool_names"] == ["observe_camera_grounded_candidates"]
    assert timing["agent_sdk_camera_grounded_composite_tools"] == composite


def test_openai_agents_robot_view_capture_policy_adds_private_server_flag(
    tmp_path: Path,
    monkeypatch,
) -> None:
    run_dir = tmp_path / "run"
    server_commands: list[list[str]] = []

    class FakeProcess:
        pid = 4242

        def __init__(self, command, *_args, **_kwargs) -> None:
            server_commands.append(list(command))
            self._poll: int | None = None

        def poll(self) -> int | None:
            return self._poll

        def wait(self, timeout: float | None = None) -> int:
            self._poll = 0
            return 0

        def terminate(self) -> None:
            self._poll = 0

        def kill(self) -> None:
            self._poll = 0

    class FakeRuntime:
        def run(self, request: LiveAgentRequest) -> LiveAgentResult:
            policy = request.metadata["agent_sdk_perf_profile"]["robot_view_capture_policy"]
            assert policy["policy"] == "action_timeline"
            assert policy["candidate_ids"] == ["F"]
            (request.run_dir / "run_result.json").write_text(
                json.dumps(
                    {
                        "task": "clean",
                        "task_name": "household-cleanup",
                        "backend": "molmospaces_subprocess",
                        "policy": "openai_agents_agent",
                        "cleanup_success": True,
                    }
                ),
                encoding="utf-8",
            )
            return LiveAgentResult(phase="finished", exit_status=0, run_result_present=True)

    monkeypatch.setattr(
        "scripts.molmo_cleanup.run_live_openai_agents_cleanup.subprocess.Popen",
        FakeProcess,
    )
    port_checks = iter([False, True])
    monkeypatch.setattr(
        "scripts.molmo_cleanup.run_live_openai_agents_cleanup._port_accepting",
        lambda *_args, **_kwargs: next(port_checks),
    )
    monkeypatch.setattr(
        "scripts.molmo_cleanup.run_live_openai_agents_cleanup.OpenAIAgentsLiveRuntime",
        lambda: FakeRuntime(),
    )
    monkeypatch.setattr(
        "scripts.molmo_cleanup.run_live_openai_agents_cleanup._run_and_tee",
        lambda *_args, **_kwargs: 0,
    )
    args = Namespace(
        run_dir=run_dir,
        repo_root=_isolated_repo_root(tmp_path),
        status_path=run_dir / "live_status.json",
        client_url="http://127.0.0.1:18788/mcp",
        host="127.0.0.1",
        port=18788,
        lock_path=tmp_path / "live.lock",
        provider_profile="codex-router-responses",
        model="gpt-5.5",
        max_turns=128,
        mcp_client_session_timeout_s=30.0,
        agent_sdk_perf_profile="context_managed_v1",
        continuation_mode="",
        model_input_compaction=None,
        model_input_compaction_min_chars=None,
        camera_grounded_composite_tools=None,
        robot_view_capture_policy="action_timeline",
        context_soft_limit_tokens=None,
        context_hard_limit_tokens=None,
        max_observe_per_waypoint=None,
        raw_fpv_candidate_budget=None,
        raw_fpv_repeated_failure_limit=None,
        done_retry_budget=None,
        model_service_retry_attempts=None,
        model_service_retry_sleep_s=None,
        server_startup_timeout_s=1.0,
        kickoff_prompt="clean the room",
        backend="molmospaces_subprocess",
        run_id="household-world",
        policy="openai_agents_agent",
        task="clean",
        min_generated_mess_count="5",
        profile="world-public-labels",
        server_arg=[],
        checker_visual_arg=[],
    )

    status = LiveOpenAIAgentsCleanupRunner(args).run()

    assert status == 0
    assert server_commands
    assert "--robot-view-capture-policy" in server_commands[0]
    policy_index = server_commands[0].index("--robot-view-capture-policy")
    assert server_commands[0][policy_index + 1] == "action_timeline"
    timing = json.loads((run_dir / "live_timing.json").read_text(encoding="utf-8"))
    policy = timing["agent_sdk_perf_profile"]["robot_view_capture_policy"]
    assert policy["policy"] == "action_timeline"
    assert timing["agent_sdk_robot_view_capture_policy"] == policy


def test_openai_agents_camera_grounded_composite_rerenders_stale_two_step_prompt() -> None:
    stale_prompt = render_kickoff_prompt("camera-grounded-labels")
    args = Namespace(
        kickoff_prompt=stale_prompt,
        profile="camera-grounded-labels",
        run_id="household-world",
        task="clean",
        min_generated_mess_count="5",
    )
    profile = {
        "raw_fpv_candidate_budget": 24,
        "max_observe_per_waypoint": 1,
        "done_retry_budget": 1,
        "camera_grounded_composite_tools": {
            "enabled": True,
            "tool_names": ["observe_camera_grounded_candidates"],
        },
    }

    prompt = _profiled_kickoff_prompt(args, profile=profile)

    assert "declare_visual_candidates with observation_id only" in stale_prompt
    assert "observe_camera_grounded_candidates instead of a separate observe" in prompt
    assert "declare_visual_candidates with observation_id only" not in prompt
    assert _kickoff_prompt_source(args, profile) == "profile-rendered-lane-default"


def test_openai_agents_camera_grounded_composite_rerenders_map_build_prompt() -> None:
    stale_prompt = render_map_build_prompt(
        "camera-grounded-labels",
        "build a Runtime Metric Map",
    )
    args = Namespace(
        kickoff_prompt=stale_prompt,
        profile="camera-grounded-labels",
        run_id="household-world",
        intent="map-build",
        task="build a Runtime Metric Map",
        min_generated_mess_count="0",
    )
    profile = {
        "raw_fpv_candidate_budget": 24,
        "max_observe_per_waypoint": 1,
        "done_retry_budget": 1,
        "camera_grounded_composite_tools": {
            "enabled": True,
            "tool_names": ["observe_camera_grounded_candidates"],
        },
    }

    prompt = _profiled_kickoff_prompt(args, profile=profile)

    assert "declare_visual_candidates for each raw FPV observation" in stale_prompt
    assert "observe_camera_grounded_candidates" in prompt
    assert "after navigating to each public inspection waypoint" in prompt
    assert "Prefer one observe_camera_grounded_candidates response per waypoint_id" in prompt
    assert "One bounded re-observation is allowed" in prompt
    assert "Do not resume the older observe plus declare_visual_candidates cadence" in prompt
    assert "declare_visual_candidates for each raw FPV observation" not in prompt
    assert "Do not pick, place, place_inside" in prompt


def test_openai_agents_camera_grounded_composite_runner_rerenders_stale_two_step_prompt(
    tmp_path: Path,
    monkeypatch,
) -> None:
    run_dir = tmp_path / "run"
    prompts: list[str] = []

    class FakeProcess:
        pid = 4242

        def __init__(self, *_args, **_kwargs) -> None:
            self._poll: int | None = None

        def poll(self) -> int | None:
            return self._poll

        def wait(self, timeout: float | None = None) -> int:
            self._poll = 0
            return 0

        def terminate(self) -> None:
            self._poll = 0

        def kill(self) -> None:
            self._poll = 0

    class FakeRuntime:
        def run(self, request: LiveAgentRequest) -> LiveAgentResult:
            prompts.append(request.kickoff_prompt)
            (request.run_dir / "run_result.json").write_text(
                json.dumps(
                    {
                        "task": "clean",
                        "task_name": "household-cleanup",
                        "backend": "molmospaces_subprocess",
                        "policy": "openai_agents_agent",
                        "cleanup_success": True,
                    }
                ),
                encoding="utf-8",
            )
            return LiveAgentResult(phase="finished", exit_status=0, run_result_present=True)

    monkeypatch.setattr(
        "scripts.molmo_cleanup.run_live_openai_agents_cleanup.subprocess.Popen",
        FakeProcess,
    )
    port_checks = iter([False, True])
    monkeypatch.setattr(
        "scripts.molmo_cleanup.run_live_openai_agents_cleanup._port_accepting",
        lambda *_args, **_kwargs: next(port_checks),
    )
    monkeypatch.setattr(
        "scripts.molmo_cleanup.run_live_openai_agents_cleanup.OpenAIAgentsLiveRuntime",
        lambda: FakeRuntime(),
    )

    def fake_run_and_tee(command, *, cwd, stdout_path, stderr_path, env):
        stdout_path.write_text("checker ok\n", encoding="utf-8")
        return 0

    monkeypatch.setattr(
        "scripts.molmo_cleanup.run_live_openai_agents_cleanup._run_and_tee",
        fake_run_and_tee,
    )
    stale_prompt = render_kickoff_prompt("camera-grounded-labels")
    args = Namespace(
        run_dir=run_dir,
        repo_root=_isolated_repo_root(tmp_path),
        status_path=run_dir / "live_status.json",
        client_url="http://127.0.0.1:18788/mcp",
        host="127.0.0.1",
        port=18788,
        lock_path=tmp_path / "live.lock",
        provider_profile="codex-router-responses",
        model="gpt-5.5",
        max_turns=128,
        mcp_client_session_timeout_s=30.0,
        agent_sdk_perf_profile="context_managed_v1",
        continuation_mode="",
        model_input_compaction=None,
        model_input_compaction_min_chars=None,
        camera_grounded_composite_tools=True,
        context_soft_limit_tokens=None,
        context_hard_limit_tokens=None,
        max_observe_per_waypoint=None,
        raw_fpv_candidate_budget=None,
        done_retry_budget=None,
        model_service_retry_attempts=None,
        model_service_retry_sleep_s=None,
        server_startup_timeout_s=1.0,
        kickoff_prompt=stale_prompt,
        backend="molmospaces_subprocess",
        run_id="household-world",
        policy="openai_agents_agent",
        task="clean",
        min_generated_mess_count="5",
        profile="camera-grounded-labels",
        server_arg=[],
        checker_visual_arg=[],
    )

    status = LiveOpenAIAgentsCleanupRunner(args).run()

    assert status == 0
    assert "declare_visual_candidates with observation_id only" in stale_prompt
    assert prompts
    assert "observe_camera_grounded_candidates instead of a separate observe" in prompts[0]
    assert "declare_visual_candidates with observation_id only" not in prompts[0]
    timing = json.loads((run_dir / "live_timing.json").read_text(encoding="utf-8"))
    assert timing["kickoff_prompt_source"] == "profile-rendered-lane-default"


def test_openai_agents_cleanup_runner_loads_canonical_skill_context(
    tmp_path: Path, monkeypatch
) -> None:
    run_dir = tmp_path / "run"
    repo_root = tmp_path / "repo"
    skill_path = repo_root / "skills/household-world/SKILL.md"
    skill_path.parent.mkdir(parents=True)
    skill_text = "# Molmo Real-World Cleanup\n\nCall metric_map first."
    skill_path.write_text(skill_text, encoding="utf-8")
    captured_contexts: list[dict[str, object]] = []

    class FakeProcess:
        pid = 4242

        def __init__(self, *_args, **_kwargs) -> None:
            self._poll: int | None = None

        def poll(self) -> int | None:
            return self._poll

        def wait(self, timeout: float | None = None) -> int:
            self._poll = 0
            return 0

        def terminate(self) -> None:
            self._poll = 0

        def kill(self) -> None:
            self._poll = 0

    class FakeRuntime:
        def run(self, request: LiveAgentRequest) -> LiveAgentResult:
            captured_contexts.append(dict(request.metadata["skill_context"]))
            (request.run_dir / "run_result.json").write_text(
                json.dumps(
                    {
                        "task": "clean",
                        "task_name": "household-cleanup",
                        "backend": "molmospaces_subprocess",
                        "policy": "openai_agents_agent",
                        "cleanup_success": True,
                    }
                ),
                encoding="utf-8",
            )
            (request.run_dir / "openai-agents-skill-context.json").write_text(
                json.dumps(
                    {
                        "schema": "openai_agents_skill_context_v1",
                        "skill_name": "household-world",
                        "included": True,
                        "sha256": request.metadata["skill_context"]["sha256"],
                    }
                ),
                encoding="utf-8",
            )
            return LiveAgentResult(
                phase="finished",
                exit_status=0,
                run_result_present=True,
                artifact_paths={
                    "openai_agents_skill_context": request.artifact_path(
                        "openai_agents_skill_context",
                        "missing.json",
                    )
                },
            )

    monkeypatch.setattr(
        "scripts.molmo_cleanup.run_live_openai_agents_cleanup.subprocess.Popen",
        FakeProcess,
    )
    port_checks = iter([False, True])
    monkeypatch.setattr(
        "scripts.molmo_cleanup.run_live_openai_agents_cleanup._port_accepting",
        lambda *_args, **_kwargs: next(port_checks),
    )
    monkeypatch.setattr(
        "scripts.molmo_cleanup.run_live_openai_agents_cleanup.OpenAIAgentsLiveRuntime",
        lambda: FakeRuntime(),
    )

    def fake_run_and_tee(command, *, cwd, stdout_path, stderr_path, env):
        stdout_path.write_text("checker ok\n", encoding="utf-8")
        return 0

    monkeypatch.setattr(
        "scripts.molmo_cleanup.run_live_openai_agents_cleanup._run_and_tee",
        fake_run_and_tee,
    )
    args = Namespace(
        run_dir=run_dir,
        repo_root=repo_root,
        status_path=run_dir / "live_status.json",
        client_url="http://127.0.0.1:18788/mcp",
        host="127.0.0.1",
        port=18788,
        lock_path=tmp_path / "live.lock",
        provider_profile="codex-router-responses",
        model="gpt-5.5",
        max_turns=128,
        incomplete_turn_continuation_attempts=2,
        mcp_client_session_timeout_s=30.0,
        agent_sdk_perf_profile="",
        continuation_mode="",
        context_soft_limit_tokens=None,
        context_hard_limit_tokens=None,
        max_observe_per_waypoint=None,
        raw_fpv_candidate_budget=None,
        done_retry_budget=None,
        model_service_retry_attempts=None,
        model_service_retry_sleep_s=None,
        server_startup_timeout_s=1.0,
        kickoff_prompt="clean the room",
        backend="molmospaces_subprocess",
        run_id="household-world",
        policy="openai_agents_agent",
        task="clean",
        min_generated_mess_count="5",
        profile="world-public-labels",
        server_arg=[],
        checker_visual_arg=[],
    )

    status = LiveOpenAIAgentsCleanupRunner(args).run()

    assert status == 0
    assert captured_contexts
    skill_context = captured_contexts[0]
    assert skill_context["included"] is True
    assert skill_context["content"] == skill_text
    assert skill_context["relative_path"] == "skills/household-world/SKILL.md"
    timing = json.loads((run_dir / "live_timing.json").read_text(encoding="utf-8"))
    assert timing["agent_sdk_skill_context"]["included"] is True
    assert timing["agent_sdk_skill_context"]["relative_path"] == ("skills/household-world/SKILL.md")
    assert timing["agent_sdk_skill_context"]["bytes"] == len(skill_text.encode("utf-8"))
    assert "content" not in timing["agent_sdk_skill_context"]
    assert skill_text not in json.dumps(timing)


def test_agent_sdk_skill_context_loader_reports_missing_source(tmp_path: Path) -> None:
    context = _load_agent_sdk_skill_context(
        tmp_path / "repo",
        skill_name="household-world",
    )

    assert context["included"] is False
    assert context["reason"] == "source_unavailable"
    assert context["relative_path"] == "skills/household-world/SKILL.md"
    assert "content" not in context


def test_openai_agents_cleanup_runner_continues_incomplete_sdk_turn(
    tmp_path: Path, monkeypatch
) -> None:
    run_dir = tmp_path / "run"
    checker_commands: list[list[str]] = []
    prompts: list[str] = []
    event_paths: list[Path] = []
    span_paths: list[Path] = []

    class FakeProcess:
        pid = 4242

        def __init__(self, *_args, **_kwargs) -> None:
            self._poll: int | None = None

        def poll(self) -> int | None:
            return self._poll

        def wait(self, timeout: float | None = None) -> int:
            self._poll = 0
            return 0

        def terminate(self) -> None:
            self._poll = 0

        def kill(self) -> None:
            self._poll = 0

    class FakeRuntime:
        def run(self, request: LiveAgentRequest) -> LiveAgentResult:
            prompts.append(request.kickoff_prompt)
            event_paths.append(request.artifact_path("openai_agents_events", "missing.jsonl"))
            span_paths.append(request.artifact_path("openai_agents_spans", "missing.jsonl"))
            if len(prompts) == 1:
                return LiveAgentResult(
                    phase="agent-turn-complete",
                    exit_status=0,
                    run_result_present=False,
                    trace_id="trace_initial",
                )
            assert "Continuation recovery" in request.kickoff_prompt
            assert request.metadata["attempt_role"] == "continuation"
            (request.run_dir / "run_result.json").write_text(
                json.dumps(
                    {
                        "task": "clean",
                        "task_name": "household-cleanup",
                        "backend": "molmospaces_subprocess",
                        "policy": "openai_agents_agent",
                        "cleanup_success": True,
                    }
                ),
                encoding="utf-8",
            )
            return LiveAgentResult(
                phase="finished",
                exit_status=0,
                run_result_present=True,
                trace_id="trace_continuation",
            )

    monkeypatch.setattr(
        "scripts.molmo_cleanup.run_live_openai_agents_cleanup.subprocess.Popen",
        FakeProcess,
    )
    port_checks = iter([False, True])
    monkeypatch.setattr(
        "scripts.molmo_cleanup.run_live_openai_agents_cleanup._port_accepting",
        lambda *_args, **_kwargs: next(port_checks),
    )
    monkeypatch.setattr(
        "scripts.molmo_cleanup.run_live_openai_agents_cleanup.OpenAIAgentsLiveRuntime",
        lambda: FakeRuntime(),
    )

    def fake_run_and_tee(command, *, cwd, stdout_path, stderr_path, env):
        checker_commands.append(command)
        stdout_path.write_text("checker ok\n", encoding="utf-8")
        return 0

    monkeypatch.setattr(
        "scripts.molmo_cleanup.run_live_openai_agents_cleanup._run_and_tee",
        fake_run_and_tee,
    )
    args = Namespace(
        run_dir=run_dir,
        repo_root=_isolated_repo_root(tmp_path),
        status_path=run_dir / "live_status.json",
        client_url="http://127.0.0.1:18788/mcp",
        host="127.0.0.1",
        port=18788,
        lock_path=tmp_path / "live.lock",
        provider_profile="codex-router-responses",
        model="gpt-5.5",
        max_turns=128,
        incomplete_turn_continuation_attempts=2,
        mcp_client_session_timeout_s=30.0,
        agent_sdk_perf_profile="",
        continuation_mode="",
        context_soft_limit_tokens=None,
        context_hard_limit_tokens=None,
        max_observe_per_waypoint=None,
        raw_fpv_candidate_budget=None,
        done_retry_budget=None,
        model_service_retry_attempts=None,
        model_service_retry_sleep_s=None,
        server_startup_timeout_s=1.0,
        kickoff_prompt="clean the room",
        backend="molmospaces_subprocess",
        run_id="household-world",
        policy="openai_agents_agent",
        task="clean",
        min_generated_mess_count="5",
        profile="smoke",
        server_arg=[],
        checker_visual_arg=[],
    )

    status = LiveOpenAIAgentsCleanupRunner(args).run()

    assert status == 0
    assert len(prompts) == 2
    assert event_paths == [
        run_dir / "openai-agents-events.jsonl",
        run_dir / "openai-agents-events.continuation-1.jsonl",
    ]
    assert span_paths == [
        run_dir / "openai-agents-spans.jsonl",
        run_dir / "openai-agents-spans.continuation-1.jsonl",
    ]
    assert checker_commands
    timing = json.loads((run_dir / "live_timing.json").read_text(encoding="utf-8"))
    assert [item["attempt_role"] for item in timing["openai_agents_attempts"]] == [
        "initial",
        "continuation",
    ]
    assert timing["openai_agents_attempts"][0]["recovery_action"] == "continue"
    assert timing["openai_agents"]["trace_id"] == "trace_continuation"


def test_openai_agents_cleanup_runner_compact_continuation_excludes_full_prompt(
    tmp_path: Path, monkeypatch
) -> None:
    run_dir = tmp_path / "run"
    prompts: list[str] = []

    class FakeProcess:
        pid = 4242

        def __init__(self, *_args, **_kwargs) -> None:
            self._poll: int | None = None

        def poll(self) -> int | None:
            return self._poll

        def wait(self, timeout: float | None = None) -> int:
            self._poll = 0
            return 0

        def terminate(self) -> None:
            self._poll = 0

        def kill(self) -> None:
            self._poll = 0

    class FakeRuntime:
        def run(self, request: LiveAgentRequest) -> LiveAgentResult:
            prompts.append(request.kickoff_prompt)
            if len(prompts) == 1:
                (request.run_dir / "trace.jsonl").write_text(
                    "\n".join(
                        [
                            json.dumps(
                                {
                                    "event": "molmo_realworld_cleanup_mcp_initialized",
                                    "evidence_lane": "world-public-labels",
                                    "goal_contract": {
                                        "surface": "household-world",
                                        "intent": "cleanup",
                                        "normalized_goal": "clean the room",
                                    },
                                }
                            ),
                            json.dumps(
                                {
                                    "event": "response",
                                    "tool": "observe",
                                    "response": {
                                        "ok": True,
                                        "waypoint_id": "generated_exploration_001",
                                    },
                                }
                            ),
                        ]
                    )
                    + "\n",
                    encoding="utf-8",
                )
                return LiveAgentResult(
                    phase="agent-turn-complete",
                    exit_status=0,
                    run_result_present=False,
                )
            assert request.metadata["agent_sdk_perf_profile"]["profile_id"] == "context_managed_v1"
            (request.run_dir / "run_result.json").write_text(
                json.dumps(
                    {
                        "task": "clean",
                        "task_name": "household-cleanup",
                        "backend": "molmospaces_subprocess",
                        "policy": "openai_agents_agent",
                        "cleanup_success": True,
                    }
                ),
                encoding="utf-8",
            )
            return LiveAgentResult(phase="finished", exit_status=0, run_result_present=True)

    monkeypatch.setattr(
        "scripts.molmo_cleanup.run_live_openai_agents_cleanup.subprocess.Popen",
        FakeProcess,
    )
    port_checks = iter([False, True])
    monkeypatch.setattr(
        "scripts.molmo_cleanup.run_live_openai_agents_cleanup._port_accepting",
        lambda *_args, **_kwargs: next(port_checks),
    )
    monkeypatch.setattr(
        "scripts.molmo_cleanup.run_live_openai_agents_cleanup.OpenAIAgentsLiveRuntime",
        lambda: FakeRuntime(),
    )

    def fake_run_and_tee(command, *, cwd, stdout_path, stderr_path, env):
        stdout_path.write_text("checker ok\n", encoding="utf-8")
        return 0

    monkeypatch.setattr(
        "scripts.molmo_cleanup.run_live_openai_agents_cleanup._run_and_tee",
        fake_run_and_tee,
    )
    full_prompt = "FULL ORIGINAL PROMPT THAT SHOULD NOT REPEAT"
    args = Namespace(
        run_dir=run_dir,
        repo_root=_isolated_repo_root(tmp_path),
        status_path=run_dir / "live_status.json",
        client_url="http://127.0.0.1:18788/mcp",
        host="127.0.0.1",
        port=18788,
        lock_path=tmp_path / "live.lock",
        provider_profile="codex-router-responses",
        model="gpt-5.5",
        max_turns=128,
        incomplete_turn_continuation_attempts=2,
        mcp_client_session_timeout_s=30.0,
        agent_sdk_perf_profile="context_managed_v1",
        continuation_mode="",
        context_soft_limit_tokens=None,
        context_hard_limit_tokens=None,
        max_observe_per_waypoint=None,
        raw_fpv_candidate_budget=None,
        done_retry_budget=None,
        model_service_retry_attempts=None,
        model_service_retry_sleep_s=None,
        server_startup_timeout_s=1.0,
        kickoff_prompt=full_prompt,
        backend="molmospaces_subprocess",
        run_id="household-world",
        policy="openai_agents_agent",
        task="clean",
        min_generated_mess_count="5",
        profile="smoke",
        server_arg=[],
        checker_visual_arg=[],
    )

    status = LiveOpenAIAgentsCleanupRunner(args).run()

    assert status == 0
    assert len(prompts) == 2
    assert prompts[0] == full_prompt
    assert full_prompt not in prompts[1]
    assert "compact_continuation_state" in prompts[1]
    assert "generated_exploration_001" in prompts[1]
    timing = json.loads((run_dir / "live_timing.json").read_text(encoding="utf-8"))
    assert timing["openai_agents_attempts"][0]["recovery_action"] == "continue"
    assert timing["openai_agents_attempts"][0]["continuation_prompt_chars"] == len(prompts[1])


def test_raw_fpv_compact_continuation_preserves_scan_progress_and_done_blockers(
    tmp_path: Path,
) -> None:
    run_dir = tmp_path / "run"
    run_dir.mkdir()
    events = [
        {
            "event": "molmo_realworld_cleanup_mcp_initialized",
            "evidence_lane": "camera-raw-fpv",
            "goal_contract": {
                "surface": "household-world",
                "intent": "cleanup",
                "normalized_goal": "clean the room",
            },
        },
        {
            "event": "response",
            "tool": "observe",
            "response": {"ok": True, "waypoint_id": "room_2_inspection"},
        },
        {
            "event": "response",
            "tool": "observe",
            "response": {"ok": True, "waypoint_id": "room_2_inspection"},
        },
        {
            "event": "response",
            "tool": "observe",
            "response": {"ok": True, "waypoint_id": "room_3_inspection"},
        },
        {
            "event": "response",
            "tool": "done",
            "response": {
                "ok": False,
                "status": "blocked",
                "completion": {
                    "blockers": [
                        {
                            "type": "insufficient_grounded_cleanup_chains",
                            "current": 2,
                            "required": 4,
                            "required_tool": "navigate_to_visual_candidate",
                            "recovery_hint": "continue the cleanup loop",
                        }
                    ]
                },
            },
        },
    ]
    (run_dir / "trace.jsonl").write_text(
        "\n".join(json.dumps(event) for event in events) + "\n",
        encoding="utf-8",
    )

    prompt = _compact_continuation_prompt(
        run_dir,
        profile={"profile_id": "context_managed_v1", "raw_fpv_candidate_budget": 24},
        context_metrics={},
    )

    assert "RAW-FPV continuation" in prompt
    assert "do not call done again" in prompt
    assert '"room_2_inspection": 2' in prompt
    assert '"room_3_inspection": 1' in prompt
    assert '"current": 2' in prompt
    assert '"required": 4' in prompt
    assert "navigate_to_relative_pose(forward_m=0, lateral_m=0, yaw_delta_deg=90)" in prompt
    assert "clipped at the left or right edge" in prompt
    assert "adjust_camera(yaw_delta_deg=45 or -45, pitch_delta_deg=0)" in prompt


def test_raw_fpv_compact_continuation_reconciles_scan_and_candidate_progress(
    tmp_path: Path,
) -> None:
    run_dir = tmp_path / "run"
    run_dir.mkdir()
    events: list[dict[str, object]] = []
    for waypoint_id in ("room_2_inspection", "room_3_inspection"):
        for _ in range(4):
            events.append(
                {
                    "event": "response",
                    "tool": "observe",
                    "response": {"ok": True, "waypoint_id": waypoint_id},
                }
            )
    events.extend(
        [
            {
                "event": "response",
                "tool": "observe",
                "response": {"ok": False, "waypoint_id": "room_4_inspection"},
            },
            {
                "event": "request",
                "tool": "navigate_to_visual_candidate",
                "request": {
                    "source_observation_id": "raw_fpv_001",
                    "category": "cup",
                    "image_region": {"type": "bbox", "value": [10, 20, 30, 40]},
                },
            },
            {
                "event": "response",
                "tool": "navigate_to_visual_candidate",
                "response": {
                    "ok": False,
                    "status": "error",
                    "error_reason": "visual_candidate_not_resolved",
                    "object_id": "observed_001",
                },
            },
            {
                "event": "response",
                "tool": "done",
                "response": {
                    "ok": False,
                    "status": "blocked",
                    "completion": {
                        "blockers": [
                            {
                                "type": "insufficient_grounded_cleanup_chains",
                                "current": 1,
                                "required": 4,
                            },
                            {
                                "type": "insufficient_waypoint_coverage",
                                "current": 1,
                                "required": 3,
                            },
                        ]
                    },
                },
            },
            {
                "event": "response",
                "tool": "place",
                "response": {"ok": True, "status": "ok", "object_id": "observed_002"},
            },
            {
                "event": "response",
                "tool": "place",
                "response": {"ok": False, "status": "error", "object_id": "observed_bad"},
            },
        ]
    )
    (run_dir / "trace.jsonl").write_text(
        "\n".join(json.dumps(event) for event in events) + "\n",
        encoding="utf-8",
    )
    profile = {
        "profile_id": "context_managed_v1",
        "raw_fpv_candidate_budget": 24,
        "max_observe_per_waypoint": 4,
    }

    state = _compact_continuation_state(run_dir, profile=profile, context_metrics={})
    prompt = _compact_continuation_prompt(run_dir, profile=profile, context_metrics={})

    assert state["completed_waypoints"] == ["room_2_inspection", "room_3_inspection"]
    assert state["scan_exhausted_waypoints"] == ["room_2_inspection", "room_3_inspection"]
    assert state["remaining_observes_by_waypoint"] == {
        "room_2_inspection": 0,
        "room_3_inspection": 0,
    }
    assert state["raw_fpv_candidate_budget"] == {
        "attempted": 1,
        "limit": 24,
        "remaining": 23,
    }
    assert state["handled_object_handles"] == ["observed_002"]
    assert state["latest_done_blockers"][0]["current"] == 2
    assert state["latest_done_blockers"][0]["progress_source"] == ("trace_reconciled_after_done")
    assert state["latest_done_blockers"][1] == {
        "type": "insufficient_waypoint_coverage",
        "current": 1,
        "required": 3,
    }
    assert state["recent_failed_candidate_attempts"][0]["error_reason"] == (
        "visual_candidate_not_resolved"
    )
    assert "do not broad re-sweep exhausted waypoints" in prompt.lower()


def test_openai_agents_cleanup_runner_compact_continuation_preserves_composite_cadence(
    tmp_path: Path, monkeypatch
) -> None:
    run_dir = tmp_path / "run"
    prompts: list[str] = []

    class FakeProcess:
        pid = 4242

        def __init__(self, *_args, **_kwargs) -> None:
            self._poll: int | None = None

        def poll(self) -> int | None:
            return self._poll

        def wait(self, timeout: float | None = None) -> int:
            self._poll = 0
            return 0

        def terminate(self) -> None:
            self._poll = 0

        def kill(self) -> None:
            self._poll = 0

    class FakeRuntime:
        def run(self, request: LiveAgentRequest) -> LiveAgentResult:
            prompts.append(request.kickoff_prompt)
            if len(prompts) == 1:
                (request.run_dir / "trace.jsonl").write_text(
                    "\n".join(
                        [
                            json.dumps(
                                {
                                    "event": "molmo_realworld_cleanup_mcp_initialized",
                                    "evidence_lane": "camera-grounded-labels",
                                    "goal_contract": {
                                        "surface": "household-world",
                                        "intent": "cleanup",
                                        "normalized_goal": "clean the room",
                                    },
                                }
                            ),
                            json.dumps(
                                {
                                    "event": "response",
                                    "tool": "observe_camera_grounded_candidates",
                                    "response": {
                                        "ok": True,
                                        "observe": {
                                            "waypoint_id": "generated_exploration_001",
                                        },
                                        "declaration": {
                                            "source_observation_id": "obs_001",
                                        },
                                    },
                                }
                            ),
                        ]
                    )
                    + "\n",
                    encoding="utf-8",
                )
                return LiveAgentResult(
                    phase="agent-turn-complete",
                    exit_status=0,
                    run_result_present=False,
                )
            assert request.metadata["attempt_role"] == "continuation"
            (request.run_dir / "run_result.json").write_text(
                json.dumps(
                    {
                        "task": "clean",
                        "task_name": "household-cleanup",
                        "backend": "molmospaces_subprocess",
                        "policy": "openai_agents_agent",
                        "cleanup_success": True,
                    }
                ),
                encoding="utf-8",
            )
            return LiveAgentResult(phase="finished", exit_status=0, run_result_present=True)

    monkeypatch.setattr(
        "scripts.molmo_cleanup.run_live_openai_agents_cleanup.subprocess.Popen",
        FakeProcess,
    )
    port_checks = iter([False, True])
    monkeypatch.setattr(
        "scripts.molmo_cleanup.run_live_openai_agents_cleanup._port_accepting",
        lambda *_args, **_kwargs: next(port_checks),
    )
    monkeypatch.setattr(
        "scripts.molmo_cleanup.run_live_openai_agents_cleanup.OpenAIAgentsLiveRuntime",
        lambda: FakeRuntime(),
    )
    monkeypatch.setattr(
        "scripts.molmo_cleanup.run_live_openai_agents_cleanup._run_and_tee",
        lambda command, *, cwd, stdout_path, stderr_path, env: 0,
    )
    full_prompt = "FULL ORIGINAL PROMPT THAT SHOULD NOT REPEAT"
    args = Namespace(
        run_dir=run_dir,
        repo_root=_isolated_repo_root(tmp_path),
        status_path=run_dir / "live_status.json",
        client_url="http://127.0.0.1:18788/mcp",
        host="127.0.0.1",
        port=18788,
        lock_path=tmp_path / "live.lock",
        provider_profile="mimo-mify-responses",
        model="xiaomi/mimo-v2.5",
        max_turns=128,
        incomplete_turn_continuation_attempts=2,
        mcp_client_session_timeout_s=30.0,
        agent_sdk_perf_profile="context_managed_v1",
        continuation_mode="",
        context_soft_limit_tokens=None,
        context_hard_limit_tokens=None,
        max_observe_per_waypoint=None,
        raw_fpv_candidate_budget=None,
        raw_fpv_repeated_failure_limit=None,
        done_retry_budget=None,
        model_service_retry_attempts=None,
        model_service_retry_sleep_s=None,
        server_startup_timeout_s=1.0,
        kickoff_prompt=full_prompt,
        backend="molmospaces_subprocess",
        run_id="household-world",
        policy="openai_agents_agent",
        task="clean",
        min_generated_mess_count="5",
        profile="camera-grounded-labels",
        server_arg=[],
        checker_visual_arg=[],
        camera_grounded_composite_tools=True,
        model_input_compaction=None,
        model_input_compaction_min_chars=None,
        robot_view_capture_policy=None,
    )

    status = LiveOpenAIAgentsCleanupRunner(args).run()

    assert status == 0
    assert len(prompts) == 2
    assert full_prompt not in prompts[1]
    assert "compact_continuation_state" in prompts[1]
    assert "Camera-grounded composite continuation" in prompts[1]
    assert "observe_camera_grounded_candidates for remaining waypoint observations" in prompts[1]
    assert "Do not resume the older observe plus declare_visual_candidates cadence" in prompts[1]
    timing = json.loads((run_dir / "live_timing.json").read_text(encoding="utf-8"))
    composite = timing["agent_sdk_perf_profile"]["camera_grounded_composite_tools"]
    assert composite["enabled"] is True


def test_openai_agents_cleanup_runner_uses_profiled_compact_kickoff_prompt(
    tmp_path: Path, monkeypatch
) -> None:
    run_dir = tmp_path / "run"
    prompts: list[str] = []

    class FakeProcess:
        pid = 4242

        def __init__(self, *_args, **_kwargs) -> None:
            self._poll: int | None = None

        def poll(self) -> int | None:
            return self._poll

        def wait(self, timeout: float | None = None) -> int:
            self._poll = 0
            return 0

        def terminate(self) -> None:
            self._poll = 0

        def kill(self) -> None:
            self._poll = 0

    class FakeRuntime:
        def run(self, request: LiveAgentRequest) -> LiveAgentResult:
            prompts.append(request.kickoff_prompt)
            (request.run_dir / "run_result.json").write_text(
                json.dumps(
                    {
                        "task": "clean",
                        "task_name": "household-cleanup",
                        "backend": "molmospaces_subprocess",
                        "policy": "openai_agents_agent",
                        "cleanup_success": True,
                    }
                ),
                encoding="utf-8",
            )
            return LiveAgentResult(phase="finished", exit_status=0, run_result_present=True)

    monkeypatch.setattr(
        "scripts.molmo_cleanup.run_live_openai_agents_cleanup.subprocess.Popen",
        FakeProcess,
    )
    port_checks = iter([False, True])
    monkeypatch.setattr(
        "scripts.molmo_cleanup.run_live_openai_agents_cleanup._port_accepting",
        lambda *_args, **_kwargs: next(port_checks),
    )
    monkeypatch.setattr(
        "scripts.molmo_cleanup.run_live_openai_agents_cleanup.OpenAIAgentsLiveRuntime",
        lambda: FakeRuntime(),
    )
    monkeypatch.setattr(
        "scripts.molmo_cleanup.run_live_openai_agents_cleanup._run_and_tee",
        lambda command, *, cwd, stdout_path, stderr_path, env: 0,
    )
    args = Namespace(
        run_dir=run_dir,
        repo_root=_isolated_repo_root(tmp_path),
        status_path=run_dir / "live_status.json",
        client_url="http://127.0.0.1:18788/mcp",
        host="127.0.0.1",
        port=18788,
        lock_path=tmp_path / "live.lock",
        provider_profile="codex-router-responses",
        model="gpt-5.5",
        max_turns=128,
        incomplete_turn_continuation_attempts=2,
        mcp_client_session_timeout_s=30.0,
        agent_sdk_perf_profile="context_managed_v1",
        continuation_mode="",
        context_soft_limit_tokens=None,
        context_hard_limit_tokens=None,
        max_observe_per_waypoint=None,
        raw_fpv_candidate_budget=None,
        done_retry_budget=None,
        model_service_retry_attempts=None,
        model_service_retry_sleep_s=None,
        server_startup_timeout_s=1.0,
        kickoff_prompt="FULL PROMPT THAT SHOULD BE REPLACED",
        backend="molmospaces_subprocess",
        run_id="household-world",
        policy="openai_agents_agent",
        task="clean",
        min_generated_mess_count="5",
        profile="world-public-labels",
        server_arg=[],
        checker_visual_arg=[],
    )

    status = LiveOpenAIAgentsCleanupRunner(args).run()

    assert status == 0
    assert len(prompts) == 1
    assert "FULL PROMPT THAT SHOULD BE REPLACED" not in prompts[0]
    assert "Compact action cadence for world-public-labels" in prompts[0]
    assert "pending_cleanup_candidates" in prompts[0]
    timing = json.loads((run_dir / "live_timing.json").read_text(encoding="utf-8"))
    assert timing["kickoff_prompt_source"] == "profile-rendered-lane-default"


def test_incomplete_turn_recovery_compacts_after_context_soft_limit(tmp_path: Path) -> None:
    run_dir = tmp_path / "run"
    run_dir.mkdir()
    (run_dir / "trace.jsonl").write_text(
        json.dumps(
            {
                "event": "molmo_realworld_cleanup_mcp_initialized",
                "evidence_lane": "world-public-labels",
                "goal_contract": {
                    "surface": "household-world",
                    "intent": "cleanup",
                    "normalized_goal": "clean the room",
                },
            }
        )
        + "\n",
        encoding="utf-8",
    )
    result = LiveAgentResult(phase="agent-turn-complete", exit_status=0)

    prompt = IncompleteTurnRecoveryPolicy(max_attempts=1).continuation_prompt(
        original_prompt="ORIGINAL FULL PROMPT",
        result=result,
        run_dir=run_dir,
        attempt_index=0,
        profile={
            "profile_id": "baseline",
            "continuation_mode": "repeat_full_prompt",
            "context_soft_limit_tokens": 100,
        },
        context_metrics={"available": True, "total_input_tokens": 100},
    )

    assert prompt is not None
    assert "compact_continuation_state" in prompt
    assert "ORIGINAL FULL PROMPT" not in prompt


def test_context_budget_result_recovers_with_compact_continuation(tmp_path: Path) -> None:
    run_dir = tmp_path / "run"
    run_dir.mkdir()
    (run_dir / "trace.jsonl").write_text(
        json.dumps(
            {
                "event": "molmo_realworld_cleanup_mcp_initialized",
                "evidence_lane": "camera-raw-fpv",
                "goal_contract": {
                    "surface": "household-world",
                    "intent": "cleanup",
                    "normalized_goal": "clean the room",
                },
            }
        )
        + "\n",
        encoding="utf-8",
    )
    result = LiveAgentResult(
        phase="failed",
        exit_status=1,
        reason="provider_context_budget_exceeded",
    )

    prompt = IncompleteTurnRecoveryPolicy(max_attempts=2).continuation_prompt(
        original_prompt="ORIGINAL FULL PROMPT",
        result=result,
        run_dir=run_dir,
        attempt_index=0,
        profile={
            "profile_id": "context_managed_v1",
            "continuation_mode": "state_summary_only",
            "raw_fpv_candidate_budget": 24,
        },
        context_metrics={"available": True, "max_input_tokens": 128_000},
    )

    assert prompt is not None
    assert "compact_continuation_state" in prompt
    assert "RAW-FPV continuation" in prompt
    assert "ORIGINAL FULL PROMPT" not in prompt


def test_openai_agents_budget_guard_classifies_context_hard_limit(tmp_path: Path) -> None:
    run_dir = tmp_path / "run"
    run_dir.mkdir()
    (run_dir / "openai-agents-spans.jsonl").write_text(
        json.dumps(
            {
                "event": "span_end",
                "span_type": "response",
                "usage": {"input_tokens": 150, "input_tokens_details": {"cached_tokens": 50}},
            }
        )
        + "\n",
        encoding="utf-8",
    )

    failure = _budget_failure_from_run_state(
        run_dir,
        {"evidence_lane": "world-public-labels", "cache_tools_list": True},
        {
            "profile_id": "custom",
            "context_hard_limit_tokens": 100,
            "raw_fpv_candidate_budget": None,
            "max_observe_per_waypoint": None,
        },
    )

    assert failure is not None
    assert failure.reason == "provider_context_budget_exceeded"
    assert failure.retryable is False
    detail = json.loads(failure.detail)
    assert detail["current_input_tokens"] == 150
    assert detail["total_input_tokens"] == 150
    assert detail["context_hard_limit_tokens"] == 100


def test_context_budget_guard_is_scoped_to_current_attempt_spans(tmp_path: Path) -> None:
    run_dir = tmp_path / "run"
    run_dir.mkdir()
    base_spans = run_dir / "openai-agents-spans.jsonl"
    continuation_spans = run_dir / "openai-agents-spans.continuation-1.jsonl"
    base_spans.write_text(
        json.dumps(
            {
                "event": "span_end",
                "span_type": "response",
                "usage": {"input_tokens": 150},
            }
        )
        + "\n",
        encoding="utf-8",
    )
    continuation_spans.write_text(
        json.dumps(
            {
                "event": "span_end",
                "span_type": "response",
                "usage": {"input_tokens": 80},
            }
        )
        + "\n",
        encoding="utf-8",
    )
    profile = {"context_hard_limit_tokens": 100}

    assert (
        openai_agents_budget_failure(
            run_dir,
            {},
            profile,
            context_spans_path=continuation_spans,
        )
        is None
    )
    assert (
        openai_agents_budget_failure(
            run_dir,
            {},
            profile,
            context_spans_path=base_spans,
        ).reason
        == "provider_context_budget_exceeded"
    )


def test_openai_agents_budget_guard_uses_current_context_not_cumulative_tokens(
    tmp_path: Path,
) -> None:
    run_dir = tmp_path / "run"
    run_dir.mkdir()
    (run_dir / "openai-agents-spans.jsonl").write_text(
        "\n".join(
            json.dumps(
                {
                    "event": "span_end",
                    "span_type": "response",
                    "usage": {
                        "input_tokens": 40_000,
                        "input_tokens_details": {"cached_tokens": 38_000},
                    },
                }
            )
            for _ in range(4)
        )
        + "\n",
        encoding="utf-8",
    )

    failure = _budget_failure_from_run_state(
        run_dir,
        {"evidence_lane": "world-public-labels", "cache_tools_list": True},
        {
            "profile_id": "context_managed_v1",
            "context_hard_limit_tokens": 96_000,
            "raw_fpv_candidate_budget": None,
            "max_observe_per_waypoint": None,
        },
    )

    assert failure is None


def test_openai_agents_budget_guard_classifies_raw_fpv_candidate_exhaustion(
    tmp_path: Path,
) -> None:
    run_dir = tmp_path / "run"
    run_dir.mkdir()
    events = [
        {
            "event": "request",
            "tool": "navigate_to_visual_candidate",
            "request": {
                "source_observation_id": "raw_fpv_001",
                "category": "cup",
                "image_region": {"type": "bbox", "value": [1, 2, 3, 4]},
            },
        },
        {
            "event": "response",
            "tool": "navigate_to_visual_candidate",
            "response": {
                "ok": False,
                "source_observation_id": "raw_fpv_001",
                "category": "cup",
                "error_reason": "invalid_visual_candidate",
            },
        },
        {
            "event": "request",
            "tool": "navigate_to_visual_candidate",
            "request": {
                "source_observation_id": "raw_fpv_002",
                "category": "book",
                "image_region": {"type": "bbox", "value": [5, 6, 7, 8]},
            },
        },
    ]
    (run_dir / "trace.jsonl").write_text(
        "\n".join(json.dumps(item) for item in events) + "\n",
        encoding="utf-8",
    )

    failure = _budget_failure_from_run_state(
        run_dir,
        {"evidence_lane": "camera-raw-fpv", "cache_tools_list": True},
        {
            "profile_id": "context_managed_v1",
            "context_hard_limit_tokens": None,
            "raw_fpv_candidate_budget": 2,
            "max_observe_per_waypoint": None,
        },
    )

    assert failure is not None
    assert failure.reason == "raw_fpv_candidate_budget_exhausted"
    detail = json.loads(failure.detail)
    assert detail["candidate_attempt_count"] == 2
    assert detail["raw_fpv_candidate_budget"] == 2
    assert detail["candidate_attempts_sample"][0]["source_observation_id"] == "raw_fpv_001"


def test_openai_agents_budget_guard_classifies_repeated_raw_fpv_failures(
    tmp_path: Path,
) -> None:
    run_dir = tmp_path / "run"
    run_dir.mkdir()
    events = []
    for _ in range(3):
        events.extend(
            [
                {
                    "event": "request",
                    "tool": "navigate_to_visual_candidate",
                    "request": {
                        "source_observation_id": "raw_fpv_001",
                        "category": "cup",
                        "image_region": {"type": "bbox", "value": [1, 2, 3, 4]},
                    },
                },
                {
                    "event": "response",
                    "tool": "navigate_to_visual_candidate",
                    "response": {
                        "ok": False,
                        "object_id": f"observed_{len(events):03d}",
                        "error_reason": "source_observation_locality_unresolved",
                    },
                },
            ]
        )
    (run_dir / "trace.jsonl").write_text(
        "\n".join(json.dumps(item) for item in events) + "\n",
        encoding="utf-8",
    )

    failure = _budget_failure_from_run_state(
        run_dir,
        {"evidence_lane": "camera-raw-fpv", "cache_tools_list": True},
        {
            "profile_id": "context_managed_v1",
            "context_hard_limit_tokens": None,
            "raw_fpv_candidate_budget": 24,
            "raw_fpv_repeated_failure_limit": 3,
            "max_observe_per_waypoint": None,
        },
    )

    assert failure is not None
    assert failure.reason == "raw_fpv_repeated_candidate_failure"
    assert failure.retryable is False
    detail = json.loads(failure.detail)
    assert detail["reasons"] == ["raw_fpv_repeated_candidate_failure"]
    assert detail["raw_fpv_repeated_failure_limit"] == 3
    assert detail["candidate_attempt_count"] == 3
    assert detail["repeated_failure_limit_hits"][0]["count"] == 3
    assert detail["repeated_failure_limit_hits"][0]["category"] == "cup"
    assert detail["repeated_failure_limit_hits"][0]["failure_reason"] == (
        "source_observation_locality_unresolved"
    )
    assert "image_region" not in json.dumps(detail)


def test_openai_agents_budget_guard_ignores_success_status_as_failure() -> None:
    metrics = raw_fpv_budget_metrics(
        [
            {
                "event": "request",
                "tool": "navigate_to_visual_candidate",
                "request": {
                    "source_observation_id": "raw_fpv_001",
                    "category": "book",
                    "image_region": {"type": "bbox", "value": [1, 2, 3, 4]},
                },
            },
            {
                "event": "response",
                "tool": "navigate_to_visual_candidate",
                "response": {"ok": True, "status": "ok", "object_id": "observed_001"},
            },
        ]
    )

    assert metrics["candidate_attempt_count"] == 1
    assert metrics["repeated_failure_fingerprints"] == []


def test_raw_fpv_budget_pairs_mixed_embedded_and_fifo_responses() -> None:
    def request(source_id: str, category: str) -> dict[str, object]:
        return {
            "event": "request",
            "tool": "navigate_to_visual_candidate",
            "request": {
                "source_observation_id": source_id,
                "category": category,
                "image_region": {"type": "bbox", "value": [10, 20, 30, 40]},
            },
        }

    first = request("raw_fpv_001", "cup")
    second = request("raw_fpv_002", "book")
    metrics = raw_fpv_budget_metrics(
        [
            first,
            {
                "event": "response",
                "tool": "navigate_to_visual_candidate",
                "request": first["request"],
                "response": {"ok": False, "error_reason": "not_resolved"},
            },
            second,
            {
                "event": "response",
                "tool": "navigate_to_visual_candidate",
                "response": {"ok": False, "error_reason": "not_resolved"},
            },
        ]
    )

    assert [item["category"] for item in metrics["failed_candidate_attempts_sample"]] == [
        "cup",
        "book",
    ]


def test_raw_fpv_repeated_failures_are_scoped_to_materially_same_view() -> None:
    def observe(source_id: str, yaw_delta_deg: float) -> dict[str, object]:
        return {
            "event": "response",
            "tool": "observe",
            "response": {
                "ok": True,
                "waypoint_id": "room_2_inspection",
                "raw_fpv_observation": {
                    "observation_id": source_id,
                    "camera_offset": {
                        "yaw_delta_deg": yaw_delta_deg,
                        "pitch_delta_deg": 0,
                    },
                },
            },
        }

    def failed_attempt(source_id: str) -> list[dict[str, object]]:
        return [
            {
                "event": "request",
                "tool": "navigate_to_visual_candidate",
                "request": {
                    "source_observation_id": source_id,
                    "category": "cup",
                    "image_region": {"type": "bbox", "value": [10, 20, 30, 40]},
                },
            },
            {
                "event": "response",
                "tool": "navigate_to_visual_candidate",
                "response": {"ok": False, "error_reason": "not_resolved"},
            },
        ]

    metrics = raw_fpv_budget_metrics(
        [
            observe("raw_fpv_001", 0),
            *failed_attempt("raw_fpv_001"),
            observe("raw_fpv_002", 45),
            *failed_attempt("raw_fpv_002"),
            observe("raw_fpv_003", 45),
            *failed_attempt("raw_fpv_003"),
        ]
    )

    assert len(metrics["repeated_failure_fingerprints"]) == 1
    assert metrics["repeated_failure_fingerprints"][0]["count"] == 2


def test_openai_agents_budget_guard_reports_label_lane_observe_budget_as_advisory(
    tmp_path: Path,
) -> None:
    run_dir = tmp_path / "run"
    run_dir.mkdir()
    events = [
        {
            "event": "response",
            "tool": "observe",
            "response": {
                "ok": False,
                "waypoint_id": "generated_exploration_001",
                "error_reason": "capture_failed",
            },
        },
        {
            "event": "response",
            "tool": "observe",
            "response": {"ok": True},
        },
        {
            "event": "response",
            "tool": "observe",
            "response": {"ok": True, "waypoint_id": "generated_exploration_001"},
        },
        {
            "event": "response",
            "tool": "observe",
            "response": {"ok": True, "waypoint_id": "generated_exploration_001"},
        },
    ]
    (run_dir / "trace.jsonl").write_text(
        "\n".join(json.dumps(item) for item in events) + "\n",
        encoding="utf-8",
    )

    timing = {"evidence_lane": "camera-grounded-labels", "cache_tools_list": True}
    profile = {
        "profile_id": "context_managed_v1",
        "context_hard_limit_tokens": None,
        "raw_fpv_candidate_budget": None,
        "raw_fpv_repeated_failure_limit": None,
        "max_observe_per_waypoint": 1,
    }

    failure = _budget_failure_from_run_state(
        run_dir,
        timing,
        profile,
    )
    advisory = openai_agents_observe_budget_advisory(run_dir, timing, profile)

    assert failure is None
    assert advisory is not None
    assert advisory["schema"] == "agent_sdk_observe_budget_advisory_v1"
    assert advisory["reason"] == "observe_budget_exceeded"
    assert advisory["evidence_lane"] == "camera-grounded-labels"
    assert advisory["max_observe_per_waypoint"] == 1
    assert advisory["observe_count_by_waypoint"] == {"generated_exploration_001": 2}
    assert advisory["observe_over_budget_by_waypoint"] == {"generated_exploration_001": 2}


def test_openai_agents_cleanup_runner_fails_after_bounded_continuation(
    tmp_path: Path, monkeypatch
) -> None:
    run_dir = tmp_path / "run"
    prompts: list[str] = []
    checker_called = False

    class FakeProcess:
        pid = 4242

        def __init__(self, *_args, **_kwargs) -> None:
            self._poll: int | None = None

        def poll(self) -> int | None:
            return self._poll

        def wait(self, timeout: float | None = None) -> int:
            self._poll = 0
            return 0

        def terminate(self) -> None:
            self._poll = 0

        def kill(self) -> None:
            self._poll = 0

    class FakeRuntime:
        def run(self, request: LiveAgentRequest) -> LiveAgentResult:
            prompts.append(request.kickoff_prompt)
            return LiveAgentResult(
                phase="agent-turn-complete",
                exit_status=0,
                run_result_present=False,
                trace_id=f"trace_{len(prompts)}",
            )

    monkeypatch.setattr(
        "scripts.molmo_cleanup.run_live_openai_agents_cleanup.subprocess.Popen",
        FakeProcess,
    )
    port_checks = iter([False, True])
    monkeypatch.setattr(
        "scripts.molmo_cleanup.run_live_openai_agents_cleanup._port_accepting",
        lambda *_args, **_kwargs: next(port_checks),
    )
    monkeypatch.setattr(
        "scripts.molmo_cleanup.run_live_openai_agents_cleanup.OpenAIAgentsLiveRuntime",
        lambda: FakeRuntime(),
    )

    def fake_run_and_tee(*_args, **_kwargs):
        nonlocal checker_called
        checker_called = True
        return 0

    monkeypatch.setattr(
        "scripts.molmo_cleanup.run_live_openai_agents_cleanup._run_and_tee",
        fake_run_and_tee,
    )
    args = Namespace(
        run_dir=run_dir,
        repo_root=_isolated_repo_root(tmp_path),
        status_path=run_dir / "live_status.json",
        client_url="http://127.0.0.1:18788/mcp",
        host="127.0.0.1",
        port=18788,
        lock_path=tmp_path / "live.lock",
        provider_profile="codex-router-responses",
        model="gpt-5.5",
        max_turns=128,
        incomplete_turn_continuation_attempts=1,
        mcp_client_session_timeout_s=30.0,
        agent_sdk_perf_profile="",
        continuation_mode="",
        context_soft_limit_tokens=None,
        context_hard_limit_tokens=None,
        max_observe_per_waypoint=None,
        raw_fpv_candidate_budget=None,
        done_retry_budget=None,
        model_service_retry_attempts=None,
        model_service_retry_sleep_s=None,
        server_startup_timeout_s=1.0,
        kickoff_prompt="clean the room",
        backend="molmospaces_subprocess",
        run_id="household-world",
        policy="openai_agents_agent",
        task="clean",
        min_generated_mess_count="5",
        profile="smoke",
        server_arg=[],
        checker_visual_arg=[],
    )

    status = LiveOpenAIAgentsCleanupRunner(args).run()

    assert status == 1
    assert len(prompts) == 2
    assert checker_called is False
    status_payload = json.loads((run_dir / "live_status.json").read_text(encoding="utf-8"))
    assert status_payload["phase"] == "failed"
    assert status_payload["exit_status"] == 1
    assert (
        status_payload["reason"]
        == "OpenAI Agents SDK turn ended without done after 2 OpenAI Agents SDK invocation(s)"
    )
    timing = json.loads((run_dir / "live_timing.json").read_text(encoding="utf-8"))
    assert len(timing["openai_agents_attempts"]) == 2
    assert timing["openai_agents"]["phase"] == "agent-turn-complete"


def _openai_agents_perf_profile_base_args(**overrides) -> Namespace:
    values = dict.fromkeys(
        """
        max_turns incomplete_turn_continuation_attempts context_soft_limit_tokens
        context_hard_limit_tokens max_observe_per_waypoint raw_fpv_candidate_budget
        done_retry_budget model_input_compaction model_input_compaction_min_chars model_racing
        model_racing_arm_count raw_fpv_repeated_failure_limit raw_fpv_image_memory
        raw_fpv_image_memory_retain camera_grounded_history_compaction
        camera_grounded_history_retain camera_grounded_composite_tools
        model_service_retry_attempts model_service_retry_sleep_s
        model_thinking_mode
        """.split(),
        None,
    )
    values.update(
        provider_profile="codex-router-responses",
        model="gpt-5.5",
        agent_sdk_perf_profile="",
        continuation_mode="",
        model_thinking_mode="default",
        cache_tools_list=True,
        mcp_client_session_timeout_s=30.0,
        robot_view_capture_policy="",
    )
    values.update(overrides)
    return Namespace(**values)


def _expected_model_racing_observability(**overrides) -> dict[str, object]:
    payload: dict[str, object] = {
        "schema": "agent_sdk_model_racing_observability_v1",
        "enabled": False,
        "mode": "per_arm_observability_v1",
        "candidate_ids": ["D"],
        "arm_count": 1,
        "racing_multiplier": 1.0,
        "winner_selection": "single_arm_no_racing",
        "loser_cancellation": "not_applicable_until_racing_enabled",
        "unknown_loser_billing": False,
        "hook": "OpenAI Agents SDK model request boundary",
        "private_artifact_policy": (
            "records model-call arm lifecycle, winner/cancel fields, timing, provider/model "
            "ids, and usage availability only; raw prompts, model text, tool payload bodies, "
            "credentials, and private truth are not persisted"
        ),
    }
    payload.update(overrides)
    return payload


def _expected_raw_fpv_image_memory_policy(retained_full_frame_limit: int) -> dict[str, object]:
    return {
        "schema": "agent_sdk_raw_fpv_image_memory_policy_v1",
        "enabled": True,
        "mode": "retain_latest_full_frame",
        "retained_full_frame_limit": retained_full_frame_limit,
        "candidate_ids": ["AA"],
        "private_artifact_policy": (
            "model-facing raw-FPV image memory only; MCP traces, reports, and image artifacts "
            "remain complete"
        ),
    }


def test_openai_agents_perf_profile_resolves_context_managed_defaults(monkeypatch) -> None:
    monkeypatch.delenv("ROBOCLAWS_OPENAI_AGENTS_PERF_PROFILE", raising=False)
    monkeypatch.delenv("ROBOCLAWS_OPENAI_AGENTS_MCP_CLIENT_SESSION_TIMEOUT_S", raising=False)
    profile = _resolve_agent_sdk_perf_profile(
        _openai_agents_perf_profile_base_args(profile="camera-grounded-labels")
    )

    assert profile["profile_id"] == "context_managed_v1"
    assert profile["source"] == "default"
    assert profile["provider_profile"] == "codex-router-responses"
    assert profile["wire_api"] == "responses"
    assert profile["model_family"] == "gpt"
    assert profile["evidence_lane"] == "camera-grounded-labels"
    assert profile["model_thinking_mode"] == "default"
    assert profile["continuation_mode"] == "state_summary_only"
    assert profile["max_turns"] == 128
    assert profile["max_continuations"] == 1
    assert profile["cache_tools_list"] is True
    assert profile["mcp_client_session_timeout_s"] == 30.0
    assert profile["context_soft_limit_tokens"] == 96_000
    assert profile["context_hard_limit_tokens"] == 128_000
    assert profile["max_observe_per_waypoint"] == 1
    assert profile["raw_fpv_candidate_budget"] is None
    assert profile["context_policy"] == {
        "schema": "agent_sdk_context_policy_v1",
        "source_level_tool_output_reduction": True,
        "deterministic_model_input_compaction": True,
        "provider_native_compaction": {
            "mode": "off",
            "threshold_tokens": None,
            "provider_capability": "",
            "proof_artifact": "",
        },
    }
    assert profile["model_input_compaction"]["enabled"] is True
    assert profile["model_input_compaction"]["mode"] == (
        "public_tool_result_summary_v1+repeated_metric_map_delta_v1+camera_grounded_history_v1"
    )
    assert profile["model_input_compaction"]["camera_grounded_history"]["enabled"] is True
    assert profile["camera_grounded_composite_tools"]["enabled"] is True
    assert profile["camera_grounded_composite_tools"]["tool_names"] == [
        "observe_camera_grounded_candidates"
    ]
    assert profile["robot_view_capture_policy"] == {
        "schema": "agent_sdk_robot_view_capture_policy_v1",
        "policy": "full",
        "candidate_ids": [],
        "scope": "report-only robot-view capture",
        "hook": "cleanup MCP server --robot-view-capture-policy",
        "private_artifact_policy": (
            "full report robot-view capture; default public route behavior unchanged"
        ),
    }
    assert profile["model_racing_observability"] == _expected_model_racing_observability()
    assert profile["sdk_model_settings"] == {
        "tool_choice": "auto",
        "parallel_tool_calls": False,
        "model_thinking_mode": "default",
        "store": False,
        "prompt_cache_retention": "in_memory",
    }
    assert profile["sdk_run_config"] == {
        "trace_include_sensitive_data": False,
        "workflow_name": "roboclaws-openai-agents-live",
    }


def test_openai_agents_perf_profile_resolves_explicit_baseline_defaults(monkeypatch) -> None:
    monkeypatch.delenv("ROBOCLAWS_OPENAI_AGENTS_PERF_PROFILE", raising=False)
    baseline = _resolve_agent_sdk_perf_profile(
        _openai_agents_perf_profile_base_args(agent_sdk_perf_profile="baseline")
    )

    assert baseline["profile_id"] == "baseline"
    assert baseline["source"] == "cli"
    assert baseline["continuation_mode"] == "repeat_full_prompt"
    assert baseline["max_continuations"] == 2
    assert baseline["context_soft_limit_tokens"] is None
    assert baseline["context_hard_limit_tokens"] is None
    assert baseline["model_input_compaction"]["enabled"] is False
    assert baseline["camera_grounded_composite_tools"]["enabled"] is False
    assert baseline["context_policy"]["source_level_tool_output_reduction"] is False
    assert baseline["context_policy"]["deterministic_model_input_compaction"] is False


def test_openai_agents_perf_profile_rejects_conflicting_cli_and_env(monkeypatch) -> None:
    monkeypatch.setenv("ROBOCLAWS_OPENAI_AGENTS_PERF_PROFILE", "baseline")

    with pytest.raises(ValueError, match="conflicting OpenAI Agents SDK performance profile"):
        _resolve_agent_sdk_perf_profile(
            _openai_agents_perf_profile_base_args(agent_sdk_perf_profile="context_managed_v1")
        )


def test_openai_agents_perf_profile_accepts_matching_cli_and_env(monkeypatch) -> None:
    monkeypatch.setenv("ROBOCLAWS_OPENAI_AGENTS_PERF_PROFILE", "context_managed_v1")

    profile = _resolve_agent_sdk_perf_profile(
        _openai_agents_perf_profile_base_args(agent_sdk_perf_profile="context_managed_v1")
    )

    assert profile["profile_id"] == "context_managed_v1"
    assert profile["source"] == "cli+environment"


@pytest.mark.parametrize(
    "removed_profile",
    ["gpt_compact_v1", "mimo_compact_v1", "raw_fpv_budgeted_v1", "custom"],
)
def test_openai_agents_perf_profile_rejects_removed_profile_ids(
    monkeypatch,
    removed_profile: str,
) -> None:
    monkeypatch.delenv("ROBOCLAWS_OPENAI_AGENTS_PERF_PROFILE", raising=False)

    with pytest.raises(ValueError, match="removed OpenAI Agents SDK performance profile"):
        _resolve_agent_sdk_perf_profile(
            _openai_agents_perf_profile_base_args(agent_sdk_perf_profile=removed_profile)
        )


def test_openai_agents_perf_profile_rejects_conflicting_cli_and_env_settings(
    monkeypatch,
) -> None:
    monkeypatch.setenv("ROBOCLAWS_OPENAI_AGENTS_CONTINUATION_MODE", "repeat_full_prompt")
    monkeypatch.setenv("ROBOCLAWS_OPENAI_AGENTS_MAX_TURNS", "10")
    monkeypatch.delenv("ROBOCLAWS_OPENAI_AGENTS_MCP_CLIENT_SESSION_TIMEOUT_S", raising=False)
    monkeypatch.setenv("ROBOCLAWS_OPENAI_AGENTS_MODEL_SERVICE_RETRY_SLEEP_S", "1.5")
    monkeypatch.setenv("ROBOCLAWS_OPENAI_AGENTS_MODEL_RACING", "0")

    conflict_cases = [
        (
            {"continuation_mode": "state_summary_only"},
            "conflicting OpenAI Agents SDK setting continuation_mode",
        ),
        ({"max_turns": 11}, "conflicting OpenAI Agents SDK setting max_turns"),
        (
            {"model_service_retry_sleep_s": 2.0},
            "conflicting OpenAI Agents SDK setting model_service_retry_sleep_s",
        ),
        ({"model_racing": True}, "conflicting OpenAI Agents SDK setting model_racing"),
    ]

    for overrides, expected_error in conflict_cases:
        with pytest.raises(ValueError, match=expected_error):
            _resolve_agent_sdk_perf_profile(_openai_agents_perf_profile_base_args(**overrides))


def test_openai_agents_perf_profile_rejects_conflicting_mcp_timeout_cli_and_env(
    monkeypatch,
) -> None:
    monkeypatch.setenv("ROBOCLAWS_OPENAI_AGENTS_MCP_CLIENT_SESSION_TIMEOUT_S", "45")

    with pytest.raises(
        ValueError,
        match="conflicting OpenAI Agents SDK setting mcp_client_session_timeout_s",
    ):
        _resolve_agent_sdk_perf_profile(
            _openai_agents_perf_profile_base_args(mcp_client_session_timeout_s=30.0)
        )


def test_openai_agents_perf_profile_accepts_matching_cli_and_env_settings(
    monkeypatch,
) -> None:
    monkeypatch.setenv("ROBOCLAWS_OPENAI_AGENTS_CONTINUATION_MODE", "state_summary_only")
    monkeypatch.setenv("ROBOCLAWS_OPENAI_AGENTS_MAX_TURNS", "9")
    monkeypatch.setenv("ROBOCLAWS_OPENAI_AGENTS_MCP_CLIENT_SESSION_TIMEOUT_S", "45")
    monkeypatch.setenv("ROBOCLAWS_OPENAI_AGENTS_MODEL_SERVICE_RETRY_SLEEP_S", "1.5")
    monkeypatch.setenv("ROBOCLAWS_OPENAI_AGENTS_MODEL_RACING", "yes")

    profile = _resolve_agent_sdk_perf_profile(
        _openai_agents_perf_profile_base_args(
            continuation_mode="state_summary_only",
            max_turns=9,
            mcp_client_session_timeout_s=45.0,
            model_service_retry_sleep_s=1.5,
            model_racing=True,
        )
    )

    assert profile["continuation_mode"] == "state_summary_only"
    assert profile["max_turns"] == 9
    assert profile["mcp_client_session_timeout_s"] == 45.0
    assert profile["model_service_retry_sleep_s"] == 1.5
    assert profile["model_racing_observability"]["enabled"] is True


def test_openai_agents_perf_profile_rejects_invalid_cache_tools_env(monkeypatch) -> None:
    monkeypatch.setenv("ROBOCLAWS_OPENAI_AGENTS_CACHE_TOOLS_LIST", "sometimes")

    with pytest.raises(
        ValueError,
        match="OpenAI Agents SDK boolean setting must be true or false",
    ):
        _resolve_agent_sdk_perf_profile(
            _openai_agents_perf_profile_base_args(cache_tools_list=None)
        )


def test_openai_agents_perf_profile_uses_cache_tools_env(monkeypatch) -> None:
    monkeypatch.setenv("ROBOCLAWS_OPENAI_AGENTS_CACHE_TOOLS_LIST", "off")

    profile = _resolve_agent_sdk_perf_profile(
        _openai_agents_perf_profile_base_args(cache_tools_list=None)
    )

    assert profile["cache_tools_list"] is False


@pytest.mark.parametrize(
    ("env_value", "direct_value", "expected_error"),
    [
        (
            "eventually",
            None,
            "OpenAI Agents SDK setting mcp_client_session_timeout_s must be a non-negative number",
        ),
        ("nan", None, "mcp_client_session_timeout_s must be a finite non-negative number"),
        ("inf", None, "mcp_client_session_timeout_s must be a finite non-negative number"),
        ("", -1.0, "mcp_client_session_timeout_s must be a finite non-negative number"),
        ("", float("nan"), "mcp_client_session_timeout_s must be a finite non-negative number"),
        ("", float("inf"), "mcp_client_session_timeout_s must be a finite non-negative number"),
        ("", float("-inf"), "mcp_client_session_timeout_s must be a finite non-negative number"),
    ],
)
def test_openai_agents_perf_profile_rejects_invalid_mcp_timeout_values(
    monkeypatch,
    env_value: str,
    direct_value: float | None,
    expected_error: str,
) -> None:
    if env_value:
        monkeypatch.setenv("ROBOCLAWS_OPENAI_AGENTS_MCP_CLIENT_SESSION_TIMEOUT_S", env_value)
    else:
        monkeypatch.delenv("ROBOCLAWS_OPENAI_AGENTS_MCP_CLIENT_SESSION_TIMEOUT_S", raising=False)

    with pytest.raises(ValueError, match=expected_error):
        _resolve_agent_sdk_perf_profile(
            _openai_agents_perf_profile_base_args(mcp_client_session_timeout_s=direct_value)
        )


def test_openai_agents_perf_profile_rejects_invalid_integer_env(monkeypatch) -> None:
    monkeypatch.setenv("ROBOCLAWS_OPENAI_AGENTS_RAW_FPV_CANDIDATE_BUDGET", "many")

    with pytest.raises(
        ValueError,
        match="OpenAI Agents SDK setting raw_fpv_candidate_budget must be an integer",
    ):
        _resolve_agent_sdk_perf_profile(
            _openai_agents_perf_profile_base_args(raw_fpv_candidate_budget=None)
        )


def test_openai_agents_perf_profile_rejects_invalid_direct_integer(monkeypatch) -> None:
    monkeypatch.delenv("ROBOCLAWS_OPENAI_AGENTS_RAW_FPV_CANDIDATE_BUDGET", raising=False)

    with pytest.raises(
        ValueError,
        match="OpenAI Agents SDK setting raw_fpv_candidate_budget must be an integer",
    ):
        _resolve_agent_sdk_perf_profile(
            _openai_agents_perf_profile_base_args(raw_fpv_candidate_budget="many")
        )


@pytest.mark.parametrize(
    ("env_name", "overrides", "expected_error"),
    [
        (
            "ROBOCLAWS_OPENAI_AGENTS_MAX_TURNS",
            {"max_turns": True},
            "OpenAI Agents SDK setting max_turns must be an integer",
        ),
        (
            "ROBOCLAWS_OPENAI_AGENTS_RAW_FPV_CANDIDATE_BUDGET",
            {"raw_fpv_candidate_budget": True},
            "OpenAI Agents SDK setting raw_fpv_candidate_budget must be an integer",
        ),
        (
            "ROBOCLAWS_OPENAI_AGENTS_MCP_CLIENT_SESSION_TIMEOUT_S",
            {"mcp_client_session_timeout_s": True},
            "OpenAI Agents SDK setting mcp_client_session_timeout_s must be a non-negative number",
        ),
        (
            "ROBOCLAWS_OPENAI_AGENTS_MODEL_SERVICE_RETRY_SLEEP_S",
            {"model_service_retry_sleep_s": True},
            "OpenAI Agents SDK setting model_service_retry_sleep_s must be a non-negative number",
        ),
    ],
)
def test_openai_agents_perf_profile_rejects_boolean_numeric_values(
    monkeypatch,
    env_name: str,
    overrides: dict[str, object],
    expected_error: str,
) -> None:
    monkeypatch.delenv(env_name, raising=False)

    with pytest.raises(ValueError, match=expected_error):
        _resolve_agent_sdk_perf_profile(_openai_agents_perf_profile_base_args(**overrides))


def test_openai_agents_perf_profile_rejects_non_positive_max_turns(monkeypatch) -> None:
    monkeypatch.delenv("ROBOCLAWS_OPENAI_AGENTS_MAX_TURNS", raising=False)

    with pytest.raises(
        ValueError,
        match="OpenAI Agents SDK setting max_turns must be positive",
    ):
        _resolve_agent_sdk_perf_profile(_openai_agents_perf_profile_base_args(max_turns=0))


@pytest.mark.parametrize(
    ("overrides", "expected_error"),
    [
        (
            {"model_racing": True, "model_racing_arm_count": 0},
            "OpenAI Agents SDK setting model_racing_arm_count must be positive when "
            "model_racing is enabled",
        ),
        (
            {"raw_fpv_image_memory": True, "raw_fpv_image_memory_retain": 0},
            "OpenAI Agents SDK setting raw_fpv_image_memory_retain must be positive when "
            "raw_fpv_image_memory is enabled",
        ),
        (
            {"camera_grounded_history_compaction": True, "camera_grounded_history_retain": 0},
            "OpenAI Agents SDK setting camera_grounded_history_retain must be positive when "
            "camera_grounded_history_compaction is enabled",
        ),
    ],
)
def test_openai_agents_perf_profile_rejects_non_positive_enabled_feature_counts(
    monkeypatch,
    overrides: dict[str, object],
    expected_error: str,
) -> None:
    monkeypatch.delenv("ROBOCLAWS_OPENAI_AGENTS_MODEL_RACING_ARM_COUNT", raising=False)
    monkeypatch.delenv("ROBOCLAWS_OPENAI_AGENTS_RAW_FPV_IMAGE_MEMORY_RETAIN", raising=False)
    monkeypatch.delenv("ROBOCLAWS_OPENAI_AGENTS_CAMERA_GROUNDED_HISTORY_RETAIN", raising=False)

    with pytest.raises(ValueError, match=expected_error):
        _resolve_agent_sdk_perf_profile(_openai_agents_perf_profile_base_args(**overrides))


def test_openai_agents_perf_profile_resolves_managed_and_racing_defaults(monkeypatch) -> None:
    monkeypatch.delenv("ROBOCLAWS_OPENAI_AGENTS_PERF_PROFILE", raising=False)
    gpt = _resolve_agent_sdk_perf_profile(
        _openai_agents_perf_profile_base_args(agent_sdk_perf_profile="context_managed_v1")
    )

    assert gpt["source"] == "cli"
    assert gpt["continuation_mode"] == "state_summary_only"
    assert gpt["max_turns"] == 128
    assert gpt["max_continuations"] == 1
    assert gpt["context_soft_limit_tokens"] == 96_000
    assert gpt["context_hard_limit_tokens"] == 128_000
    assert gpt["done_retry_budget"] == 1
    assert "truncation" not in gpt["sdk_model_settings"]
    assert gpt["sdk_model_settings"]["prompt_cache_retention"] == "in_memory"
    assert gpt["model_input_compaction"]["candidate_ids"] == ["I", "N", "AC"]
    assert gpt["model_input_compaction"]["repeated_metric_map_delta"] is True
    assert gpt["model_input_compaction"]["camera_grounded_history"] == {
        "schema": "agent_sdk_camera_grounded_history_policy_v1",
        "enabled": True,
        "mode": "retain_latest_actionable_outputs",
        "retained_recent_outputs": 4,
        "candidate_ids": ["AC"],
        "private_artifact_policy": (
            "model-facing camera-grounded history compaction only; MCP traces, reports, "
            "and run artifacts remain complete"
        ),
    }
    assert gpt["camera_grounded_composite_tools"]["candidate_ids"] == ["O"]
    assert gpt["camera_grounded_composite_tools"]["enabled"] is True

    racing = _resolve_agent_sdk_perf_profile(
        _openai_agents_perf_profile_base_args(model_racing=True, model_racing_arm_count=None)
    )
    assert racing["model_racing_observability"] == _expected_model_racing_observability(
        enabled=True,
        mode="get_response_racing_v1",
        candidate_ids=["D", "C"],
        arm_count=2,
        racing_multiplier=2.0,
        winner_selection="first_successful_sdk_response",
        loser_cancellation="cancel_pending_losers",
        unknown_loser_billing=True,
    )


def test_openai_agents_perf_profile_resolves_mimo_and_chat_defaults(monkeypatch) -> None:
    monkeypatch.delenv("ROBOCLAWS_OPENAI_AGENTS_PERF_PROFILE", raising=False)
    mimo = _resolve_agent_sdk_perf_profile(
        _openai_agents_perf_profile_base_args(
            provider_profile="mimo-mify-responses",
            model="xiaomi/mimo-v2.5",
            agent_sdk_perf_profile="context_managed_v1",
        )
    )

    assert mimo["provider_profile"] == "mimo-mify-responses"
    assert mimo["wire_api"] == "responses"
    assert mimo["model_family"] == "mimo"
    assert mimo["max_continuations"] == 1
    assert mimo["context_soft_limit_tokens"] == 64_000
    assert mimo["context_hard_limit_tokens"] == 96_000
    assert mimo["sdk_model_settings"]["truncation"] == "auto"

    chat = _resolve_agent_sdk_perf_profile(
        _openai_agents_perf_profile_base_args(
            provider_profile="mimo-tp-openai-chat",
            model="mimo-v2.5",
        )
    )
    assert chat["provider_profile"] == "mimo-tp-openai-chat"
    assert chat["wire_api"] == "chat-completions"
    assert chat["model_family"] == "mimo"
    assert chat["sdk_model_settings"] == {
        "tool_choice": "auto",
        "parallel_tool_calls": False,
        "model_thinking_mode": "default",
        "include_usage": True,
    }

    kimi = _resolve_agent_sdk_perf_profile(
        _openai_agents_perf_profile_base_args(
            provider_profile="kimi-openai-chat",
            model="kimi-k2.7-code",
        )
    )
    assert kimi["provider_profile"] == "kimi-openai-chat"
    assert kimi["wire_api"] == "chat-completions"
    assert kimi["sdk_model_settings"]["extra_headers"] == {"User-Agent": "claude-code/1.0.0"}


def test_openai_agents_perf_profile_rejects_route_incompatible_model(monkeypatch) -> None:
    monkeypatch.delenv("ROBOCLAWS_OPENAI_AGENTS_PERF_PROFILE", raising=False)

    with pytest.raises(
        ValueError,
        match=("model 'gpt-5.5' is incompatible with provider_profile 'minimax-responses'"),
    ):
        _resolve_agent_sdk_perf_profile(
            _openai_agents_perf_profile_base_args(
                provider_profile="minimax-responses",
                model="gpt-5.5",
            )
        )


def test_openai_agents_perf_profile_rejects_unknown_model(monkeypatch) -> None:
    monkeypatch.delenv("ROBOCLAWS_OPENAI_AGENTS_PERF_PROFILE", raising=False)

    with pytest.raises(
        ValueError,
        match=("unknown model 'not-in-provider-catalog' for provider_profile minimax-responses"),
    ):
        _resolve_agent_sdk_perf_profile(
            _openai_agents_perf_profile_base_args(
                provider_profile="minimax-responses",
                model="not-in-provider-catalog",
            )
        )


def test_openai_agents_perf_profile_accepts_thinking_mode_override(monkeypatch) -> None:
    monkeypatch.delenv("ROBOCLAWS_OPENAI_AGENTS_PERF_PROFILE", raising=False)
    profile = _resolve_agent_sdk_perf_profile(
        _openai_agents_perf_profile_base_args(model_thinking_mode="disabled")
    )

    assert profile["model_thinking_mode"] == "disabled"
    assert profile["sdk_model_settings"]["model_thinking_mode"] == "disabled"


def test_openai_agents_perf_profile_resolves_raw_fpv_budget_defaults(monkeypatch) -> None:
    monkeypatch.delenv("ROBOCLAWS_OPENAI_AGENTS_PERF_PROFILE", raising=False)
    raw = _resolve_agent_sdk_perf_profile(
        _openai_agents_perf_profile_base_args(
            agent_sdk_perf_profile="context_managed_v1",
            profile="camera-raw-fpv",
        )
    )

    assert raw["max_turns"] == 128
    assert raw["max_continuations"] == 2
    assert raw["raw_fpv_candidate_budget"] == 24
    assert raw["raw_fpv_repeated_failure_limit"] == 3
    assert raw["max_observe_per_waypoint"] == 4
    assert raw["model_input_compaction"]["enabled"] is True
    assert raw["model_input_compaction"]["raw_fpv_image_memory"] == (
        _expected_raw_fpv_image_memory_policy(1)
    )
    assert raw["done_retry_budget"] == 1


def test_openai_agents_perf_profile_resolves_direct_overrides(monkeypatch) -> None:
    monkeypatch.delenv("ROBOCLAWS_OPENAI_AGENTS_PERF_PROFILE", raising=False)
    profile = _resolve_agent_sdk_perf_profile(
        _openai_agents_perf_profile_base_args(
            agent_sdk_perf_profile="context_managed_v1",
            profile="camera-raw-fpv",
            continuation_mode="state_summary_only",
            max_turns=9,
            incomplete_turn_continuation_attempts=3,
            context_soft_limit_tokens=12,
            context_hard_limit_tokens=34,
            max_observe_per_waypoint=2,
            raw_fpv_candidate_budget=3,
            raw_fpv_repeated_failure_limit=2,
            raw_fpv_image_memory=True,
            raw_fpv_image_memory_retain=2,
            robot_view_capture_policy="action_timeline",
            done_retry_budget=4,
        )
    )

    assert profile["profile_id"] == "context_managed_v1"
    assert profile["max_turns"] == 9
    assert profile["max_continuations"] == 3
    assert profile["context_soft_limit_tokens"] == 12
    assert profile["context_hard_limit_tokens"] == 34
    assert profile["max_observe_per_waypoint"] == 2
    assert profile["raw_fpv_repeated_failure_limit"] == 2
    assert profile["model_input_compaction"]["candidate_ids"] == ["I", "N", "AA", "AC"]
    assert profile["model_input_compaction"]["mode"] == (
        "public_tool_result_summary_v1+repeated_metric_map_delta_v1+raw_fpv_image_memory_v1+"
        "camera_grounded_history_v1"
    )
    assert profile["model_input_compaction"]["enabled"] is True
    assert (
        profile["model_input_compaction"]["raw_fpv_image_memory"]["retained_full_frame_limit"] == 2
    )
    assert profile["model_input_compaction"]["camera_grounded_history"]["enabled"] is True
    assert profile["robot_view_capture_policy"]["policy"] == "action_timeline"
    assert profile["robot_view_capture_policy"]["candidate_ids"] == ["F"]


def test_openai_agents_perf_profile_resolves_custom_compaction(monkeypatch) -> None:
    monkeypatch.delenv("ROBOCLAWS_OPENAI_AGENTS_PERF_PROFILE", raising=False)
    compaction = _resolve_agent_sdk_perf_profile(
        _openai_agents_perf_profile_base_args(
            agent_sdk_perf_profile="context_managed_v1",
            profile="camera-raw-fpv",
            model_input_compaction=True,
            model_input_compaction_min_chars=80,
            raw_fpv_image_memory=True,
            raw_fpv_image_memory_retain=2,
            camera_grounded_history_compaction=True,
            camera_grounded_history_retain=3,
            camera_grounded_composite_tools=True,
        )
    )

    model_input = compaction["model_input_compaction"]
    assert model_input["schema"] == "agent_sdk_model_input_compaction_v1"
    assert model_input["enabled"] is True
    assert model_input["mode"] == (
        "public_tool_result_summary_v1+repeated_metric_map_delta_v1+raw_fpv_image_memory_v1+"
        "camera_grounded_history_v1"
    )
    assert model_input["min_chars"] == 80
    assert model_input["candidate_ids"] == ["I", "N", "AA", "AC"]
    assert model_input["hook"] == "RunConfig.call_model_input_filter"
    assert model_input["repeated_metric_map_delta"] is True
    assert model_input["raw_fpv_image_memory"] == _expected_raw_fpv_image_memory_policy(2)
    assert model_input["camera_grounded_history"] == {
        "schema": "agent_sdk_camera_grounded_history_policy_v1",
        "enabled": True,
        "mode": "retain_latest_actionable_outputs",
        "retained_recent_outputs": 3,
        "candidate_ids": ["AC"],
        "private_artifact_policy": (
            "model-facing camera-grounded history compaction only; MCP traces, reports, "
            "and run artifacts remain complete"
        ),
    }
    assert model_input["private_artifact_policy"] == (
        "model-facing compaction only; MCP traces, reports, and run artifacts remain complete"
    )
    assert compaction["camera_grounded_composite_tools"] == {
        "schema": "agent_sdk_camera_grounded_composite_tools_v1",
        "enabled": True,
        "tool_names": ["observe_camera_grounded_candidates"],
        "candidate_ids": ["O"],
        "scope": "camera-grounded-labels only",
        "hook": "cleanup MCP server private extra tool",
        "private_artifact_policy": (
            "SDK-private MCP tool addition only; default public MCP/profile tools remain unchanged"
        ),
    }


def test_openai_agents_control_plane_metrics_parse_server_log(tmp_path: Path) -> None:
    run_dir = tmp_path / "run"
    run_dir.mkdir()
    (run_dir / "openai-agents-server.log").write_text(
        "\n".join(
            [
                "[2026-06-09] INFO Created new transport with session ID: abc",
                'INFO:     127.0.0.1:1 - "POST /mcp HTTP/1.1" 200 OK',
                "[2026-06-09] INFO Processing request of type ListToolsRequest",
                'INFO:     127.0.0.1:2 - "POST /mcp HTTP/1.1" 202 Accepted',
                "[2026-06-09] INFO Processing request of type CallToolRequest",
                "[2026-06-09] INFO Processing request of type CallToolRequest",
                "OPENAI_API_KEY is not set, skipping trace export",
                "[2026-06-09] INFO Terminating session: abc",
            ]
        )
        + "\n",
        encoding="utf-8",
    )

    metrics = _mcp_control_plane_metrics(run_dir)

    assert metrics["available"] is True
    assert metrics["request_type_counts"] == {
        "CallToolRequest": 2,
        "ListToolsRequest": 1,
    }
    assert metrics["total_mcp_request_count"] == 3
    assert metrics["call_tool_request_count"] == 2
    assert metrics["list_tools_request_count"] == 1
    assert metrics["control_request_count"] == 1
    assert metrics["list_tools_per_call_tool"] == 0.5
    assert metrics["streamable_http_session_count"] == 1
    assert metrics["session_termination_count"] == 1
    assert metrics["trace_export_skip_count"] == 1
    assert metrics["http_status_counts"] == {
        "200 OK": 1,
        "202 Accepted": 1,
    }


def test_openai_agents_event_metrics_parse_tool_errors(tmp_path: Path) -> None:
    run_dir = tmp_path / "run"
    run_dir.mkdir()
    (run_dir / "openai-agents-events.jsonl").write_text(
        "\n".join(
            [
                json.dumps({"event": "start", "mcp_client_session_timeout_s": 5}),
                json.dumps(
                    {
                        "event": "tool_error",
                        "classification": "mcp_client_request_timeout",
                        "message": (
                            "Timed out while waiting for response to ClientRequest. "
                            "Waited 5.0 seconds."
                        ),
                    }
                ),
                json.dumps({"event": "result"}),
            ]
        )
        + "\n",
        encoding="utf-8",
    )

    metrics = _openai_agents_event_metrics(run_dir)

    assert metrics["available"] is True
    assert metrics["event_counts"]["tool_error"] == 1
    assert metrics["tool_error_count"] == 1
    assert metrics["tool_error_classifications"] == {"mcp_client_request_timeout": 1}
    assert "Waited 5.0 seconds" in metrics["tool_error_messages_sample"][0]


def test_openai_agents_event_metrics_fail_aloud_on_malformed_event_source(
    tmp_path: Path,
) -> None:
    run_dir = tmp_path / "run"
    run_dir.mkdir()
    (run_dir / "openai-agents-events.jsonl").write_text(
        '{"event":"result"}\n{bad-json}\n',
        encoding="utf-8",
    )

    with pytest.raises(
        ValueError,
        match=r"OpenAI Agents metrics source row must contain valid JSON object: "
        r".*openai-agents-events\.jsonl:2",
    ):
        _openai_agents_event_metrics(run_dir)


def test_openai_agents_model_racing_observability_metrics_are_aggregate_only(
    tmp_path: Path,
) -> None:
    run_dir = tmp_path / "run"
    run_dir.mkdir()
    (run_dir / "openai-agents-events.jsonl").write_text(
        "\n".join(
            [
                json.dumps(
                    {
                        "schema": "openai_agents_model_racing_observability_v1",
                        "event": "model_racing_arm_start",
                        "provider_profile": "mimo-mify-responses",
                        "wire_api": "responses",
                        "model": "xiaomi/mimo-v2.5",
                        "call_index": 0,
                        "arm_id": "call-0-attempt-0-arm-0",
                        "arm_count": 1,
                        "method": "get_response",
                        "racing_enabled": False,
                        "racing_mode": "per_arm_observability_v1",
                        "racing_multiplier": 1.0,
                    }
                ),
                json.dumps(
                    {
                        "schema": "openai_agents_model_racing_observability_v1",
                        "event": "model_racing_arm_finish",
                        "provider_profile": "mimo-mify-responses",
                        "wire_api": "responses",
                        "model": "xiaomi/mimo-v2.5",
                        "call_index": 0,
                        "arm_id": "call-0-attempt-0-arm-0",
                        "arm_count": 1,
                        "method": "get_response",
                        "racing_enabled": False,
                        "racing_mode": "per_arm_observability_v1",
                        "racing_multiplier": 1.0,
                        "elapsed_s": 2.5,
                        "winner": True,
                        "cancelled": False,
                        "cancellation_observed": False,
                        "loser_billing_unknown": False,
                        "final_outcome": "success",
                        "usage_summary": {
                            "usage_available": True,
                            "input_tokens": 120,
                            "cached_input_tokens": 20,
                            "uncached_input_tokens": 100,
                            "output_tokens": 30,
                            "reasoning_tokens": 5,
                        },
                    }
                ),
            ]
        )
        + "\n",
        encoding="utf-8",
    )

    metrics = _model_racing_observability_metrics(run_dir)

    assert metrics["available"] is True
    assert metrics["source"] == "openai_agents_model_racing_observability_events"
    assert metrics["event_count"] == 2
    assert metrics["event_counts"] == {
        "model_racing_arm_finish": 1,
        "model_racing_arm_start": 1,
    }
    assert metrics["call_count"] == 1
    assert metrics["arm_count"] == 1
    assert metrics["max_arm_count_per_call"] == 1
    assert metrics["racing_enabled"] is False
    assert metrics["racing_multiplier"] == 1.0
    assert metrics["winner_count"] == 1
    assert metrics["cancelled_count"] == 0
    assert metrics["cancellation_observed_count"] == 0
    assert metrics["loser_billing_unknown_count"] == 0
    assert metrics["elapsed_s_total"] == 2.5
    assert metrics["max_elapsed_s"] == 2.5
    assert metrics["usage_available_count"] == 1
    assert metrics["usage_missing_count"] == 0
    assert metrics["total_input_tokens"] == 120
    assert metrics["total_cached_input_tokens"] == 20
    assert metrics["total_uncached_input_tokens"] == 100
    assert metrics["total_output_tokens"] == 30
    assert metrics["total_reasoning_tokens"] == 5
    assert metrics["methods"] == ["get_response"]
    assert metrics["racing_modes"] == ["per_arm_observability_v1"]
    assert metrics["final_outcomes"] == {"success": 1}
    assert metrics["attempted_models"] == ["xiaomi/mimo-v2.5"]
    assert metrics["attempted_provider_profiles"] == ["mimo-mify-responses"]
    assert metrics["attempted_wire_apis"] == ["responses"]
    assert "Raw prompts" in metrics["privacy_note"]


def test_openai_agents_span_recorder_writes_sanitized_span_events(tmp_path: Path) -> None:
    spans_path = tmp_path / "openai-agents-spans.jsonl"
    recorder = RoboclawsSpanRecorder(
        spans_path,
        runtime_config={
            "runtime": "openai-agents-live",
            "provider_profile": "codex-router-responses",
            "model": "gpt-5.5",
        },
    )

    class FakeSpanData:
        type = "function"

        def export(self) -> dict[str, object]:
            return {
                "type": "function",
                "name": "pickup_object",
                "input": '{"secret":"prompt text"}',
                "output": '{"private_target_truth": true}',
                "mcp_data": {"server": "cleanup", "tool_name": "pickup_object"},
            }

    class FakeSpan:
        trace_id = "trace_1"
        span_id = "span_1"
        parent_id = "span_parent"
        started_at = datetime.fromtimestamp(100, UTC).isoformat()
        ended_at = datetime.fromtimestamp(102.5, UTC).isoformat()
        span_data = FakeSpanData()
        error = {"message": "tool failed", "data": {"raw": "not persisted"}}

    recorder.on_span_end(FakeSpan())
    recorder.shutdown()
    recorder.on_span_end(FakeSpan())

    events = [json.loads(line) for line in spans_path.read_text(encoding="utf-8").splitlines()]

    assert len(events) == 1
    event = events[0]
    assert event["schema"] == "openai_agents_sanitized_span_v1"
    assert event["event"] == "span_end"
    assert event["runtime"] == "openai-agents-live"
    assert event["span_type"] == "function"
    assert event["span_name"] == "pickup_object"
    assert event["duration_s"] == 2.5
    assert event["mcp"] == {"server": "cleanup", "tool_name": "pickup_object"}
    assert event["error"] == {"message": "tool failed", "data_keys": ["raw"]}
    assert "input" not in event
    assert "output" not in event


def test_openai_agents_span_metrics_parse_span_artifacts(tmp_path: Path) -> None:
    run_dir = tmp_path / "run"
    run_dir.mkdir()
    (run_dir / "openai-agents-spans.jsonl").write_text(
        "\n".join(
            [
                json.dumps({"event": "trace_start", "trace_id": "trace_1"}),
                json.dumps({"event": "span_end", "span_type": "response"}),
                json.dumps({"event": "span_end", "span_type": "function"}),
                json.dumps(
                    {
                        "event": "span_capture_unavailable",
                        "reason": "sdk_trace_processor_registration_failed",
                        "error_type": "RuntimeError",
                        "message": "cannot register",
                    }
                ),
            ]
        )
        + "\n",
        encoding="utf-8",
    )

    metrics = _openai_agents_span_metrics(run_dir)

    assert metrics["available"] is True
    assert metrics["span_files"] == ["openai-agents-spans.jsonl"]
    assert metrics["event_counts"]["span_end"] == 2
    assert metrics["span_end_count"] == 2
    assert metrics["span_type_counts"] == {"function": 1, "response": 1}
    assert metrics["limitations"] == [
        {
            "reason": "sdk_trace_processor_registration_failed",
            "error_type": "RuntimeError",
            "message": "cannot register",
        }
    ]
    assert "Raw prompts" in metrics["sanitization_note"]


def test_openai_agents_span_metrics_fail_aloud_on_non_object_span_source(
    tmp_path: Path,
) -> None:
    run_dir = tmp_path / "run"
    run_dir.mkdir()
    (run_dir / "openai-agents-spans.jsonl").write_text(
        json.dumps(["not", "an", "event"]) + "\n",
        encoding="utf-8",
    )

    with pytest.raises(
        ValueError,
        match=r"OpenAI Agents metrics source row must contain a JSON object: "
        r".*openai-agents-spans\.jsonl:1",
    ):
        _openai_agents_span_metrics(run_dir)


def test_openai_agents_context_metrics_parse_response_span_usage(tmp_path: Path) -> None:
    run_dir = tmp_path / "run"
    run_dir.mkdir()
    (run_dir / "openai-agents-spans.jsonl").write_text(
        "\n".join(
            [
                json.dumps(
                    {
                        "event": "span_end",
                        "span_type": "response",
                        "duration_s": 1.5,
                        "usage": {
                            "input_tokens": 100,
                            "input_tokens_details": {"cached_tokens": 25},
                            "output_tokens": 10,
                            "output_tokens_details": {"reasoning_tokens": 4},
                        },
                    }
                ),
                json.dumps(
                    {
                        "event": "span_end",
                        "span_type": "custom",
                        "duration_s": 1.6,
                        "usage": {
                            "input_tokens": 100,
                            "cached_input_tokens": 25,
                            "output_tokens": 10,
                        },
                    }
                ),
                json.dumps(
                    {
                        "event": "span_end",
                        "span_type": "response",
                        "duration_s": 2.5,
                        "usage": {
                            "input_tokens": 400,
                            "cached_input_tokens": 100,
                            "output_tokens": 20,
                        },
                    }
                ),
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    (run_dir / "trace.jsonl").write_text(
        "\n".join(
            [
                json.dumps({"event": "request", "tool": "observe"}),
                json.dumps(
                    {
                        "event": "response",
                        "tool": "observe",
                        "payload": {"observation_id": "raw_fpv_1"},
                    }
                ),
                json.dumps({"event": "response", "tool": "done", "payload": {"ok": True}}),
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    timing = {
        "kickoff_prompt_chars": 80,
        "cache_tools_list": True,
        "sdk_model_settings": {"prompt_cache_retention": "in_memory"},
        "kickoff_prompt_stable_prefix": {"hash": "stable-hash"},
        "openai_agents_attempts": [
            {"attempt_index": 0, "continuation_prompt_chars": 0},
            {"attempt_index": 1, "continuation_prompt_chars": 40},
        ],
    }

    context = _context_metrics(run_dir, timing)
    cache = _cache_metrics(context, timing)
    growth = _context_growth_metrics(run_dir, timing)

    assert context["available"] is True
    assert context["source"] == "openai_agents_span_usage"
    assert context["response_span_count"] == 2
    assert context["total_input_tokens"] == 500
    assert context["total_cached_input_tokens"] == 125
    assert context["total_uncached_input_tokens"] == 375
    assert context["cache_hit_ratio"] == 0.25
    assert context["p50_input_tokens"] == 100
    assert context["p95_input_tokens"] == 400
    assert context["total_reasoning_tokens"] == 4
    assert context["response_span_duration_s"] == 4.0
    assert context["kickoff_prompt_estimated_tokens"] == 20
    assert context["continuation_prompt_estimated_tokens"] == 10
    assert cache["available"] is True
    assert cache["provider_prompt_cache_observed"] is True
    assert cache["first_response_cached_tokens"] == 25
    assert cache["prompt_cache_retention"] == "in_memory"
    assert cache["stable_prefix_hash"] == "stable-hash"
    assert cache["mcp_tool_catalog_cache_enabled"] is True
    assert growth["available"] is True
    assert growth["trace_event_count"] == 3
    assert growth["observe_response_count"] == 1
    assert growth["raw_fpv_observation_count"] == 1
    assert growth["continuation_attempt_count"] == 1
    assert growth["tool_response_bytes_total"] > 0


def test_openai_agents_context_growth_metrics_fail_aloud_on_malformed_trace_source(
    tmp_path: Path,
) -> None:
    run_dir = tmp_path / "run"
    run_dir.mkdir()
    (run_dir / "trace.jsonl").write_text(
        '{"event":"request","tool":"observe"}\n{bad-json}\n',
        encoding="utf-8",
    )

    with pytest.raises(
        ValueError,
        match=r"OpenAI Agents metrics source row must contain valid JSON object: .*trace\.jsonl:2",
    ):
        _context_growth_metrics(run_dir, {})


def test_openai_agents_context_metrics_missing_usage_is_unavailable(tmp_path: Path) -> None:
    run_dir = tmp_path / "run"
    run_dir.mkdir()
    (run_dir / "openai-agents-spans.jsonl").write_text(
        json.dumps({"event": "span_end", "span_type": "response"}) + "\n",
        encoding="utf-8",
    )

    context = _context_metrics(run_dir, {"cache_tools_list": True})
    cache = _cache_metrics(
        context,
        {
            "cache_tools_list": True,
            "sdk_model_settings": {"prompt_cache_retention": "in_memory"},
            "kickoff_prompt_stable_prefix": {"hash": "stable-hash"},
        },
    )

    assert context["available"] is False
    assert context["source"] == "openai_agents_span_usage"
    assert "response_span_usage_missing" in context["limitations"]
    assert "total_input_tokens" not in context
    assert cache["available"] is False
    assert cache["source"] == "openai_agents_span_usage"
    assert "response_span_usage_missing" in cache["limitations"]
    assert cache["prompt_cache_retention"] == "in_memory"
    assert cache["stable_prefix_hash"] == "stable-hash"


def test_openai_agents_model_input_filter_metrics_are_aggregate_only(tmp_path: Path) -> None:
    run_dir = tmp_path / "run"
    run_dir.mkdir()
    (run_dir / "openai-agents-events.jsonl").write_text(
        "\n".join(
            [
                json.dumps(
                    {
                        "schema": "openai_agents_model_input_filter_v1",
                        "event": "model_input_filter",
                        "provider_profile": "codex-router-responses",
                        "wire_api": "responses",
                        "model": "gpt-5.5",
                        "config": {
                            "enabled": True,
                            "mode": "public_tool_result_summary_v1",
                        },
                        "metrics": {
                            "input_item_count": 3,
                            "compacted_item_count": 2,
                            "unchanged_item_count": 1,
                            "repeated_item_count": 1,
                            "input_bytes_before": 2000,
                            "input_bytes_after": 800,
                            "input_bytes_reduced": 1200,
                            "metric_map_output_count": 2,
                            "repeated_metric_map_output_count": 1,
                            "metric_map_delta_compacted_count": 1,
                            "metric_map_bytes_before": 1400,
                            "metric_map_bytes_after": 500,
                            "metric_map_bytes_reduced": 900,
                            "raw_fpv_image_memory_enabled": True,
                            "raw_fpv_image_memory_mode": "retain_latest_full_frame",
                            "raw_fpv_image_item_count": 2,
                            "raw_fpv_image_retained_count": 1,
                            "raw_fpv_image_evicted_count": 1,
                            "raw_fpv_image_bytes_before": 1000,
                            "raw_fpv_image_bytes_after": 350,
                            "raw_fpv_image_bytes_reduced": 650,
                        },
                    }
                ),
                json.dumps(
                    {
                        "schema": "openai_agents_model_input_filter_v1",
                        "event": "model_input_filter",
                        "provider_profile": "codex-router-responses",
                        "wire_api": "responses",
                        "model": "gpt-5.5",
                        "config": {
                            "enabled": True,
                            "mode": "public_tool_result_summary_v1",
                        },
                        "metrics": {
                            "input_item_count": 2,
                            "compacted_item_count": 0,
                            "unchanged_item_count": 2,
                            "input_bytes_before": 500,
                            "input_bytes_after": 500,
                            "input_bytes_reduced": 0,
                            "metric_map_output_count": 1,
                            "metric_map_bytes_before": 300,
                            "metric_map_bytes_after": 300,
                            "metric_map_bytes_reduced": 0,
                        },
                    }
                ),
            ]
        )
        + "\n",
        encoding="utf-8",
    )

    metrics = _model_input_filter_metrics(run_dir)

    assert metrics["available"] is True
    assert metrics["source"] == "openai_agents_model_input_filter_events"
    assert metrics["event_count"] == 2
    assert metrics["enabled"] is True
    assert metrics["modes"] == ["public_tool_result_summary_v1"]
    assert metrics["attempted_provider_profiles"] == ["codex-router-responses"]
    assert metrics["attempted_wire_apis"] == ["responses"]
    assert metrics["compacted_item_count"] == 2
    assert metrics["unchanged_item_count"] == 3
    assert metrics["repeated_item_count"] == 1
    assert metrics["input_bytes_before"] == 2500
    assert metrics["input_bytes_after"] == 1300
    assert metrics["input_bytes_reduced"] == 1200
    assert metrics["input_byte_reduction_ratio"] == 0.48
    assert metrics["metric_map_output_count"] == 3
    assert metrics["repeated_metric_map_output_count"] == 1
    assert metrics["metric_map_delta_compacted_count"] == 1
    assert metrics["metric_map_bytes_before"] == 1700
    assert metrics["metric_map_bytes_after"] == 800
    assert metrics["metric_map_bytes_reduced"] == 900
    assert metrics["metric_map_byte_reduction_ratio"] == 0.529412
    assert metrics["raw_fpv_image_memory_enabled"] is True
    assert metrics["raw_fpv_image_memory_modes"] == ["retain_latest_full_frame"]
    assert metrics["raw_fpv_image_item_count"] == 2
    assert metrics["raw_fpv_image_retained_count"] == 1
    assert metrics["raw_fpv_image_evicted_count"] == 1
    assert metrics["raw_fpv_image_bytes_before"] == 1000
    assert metrics["raw_fpv_image_bytes_after"] == 350
    assert metrics["raw_fpv_image_bytes_reduced"] == 650
    assert metrics["raw_fpv_image_byte_reduction_ratio"] == 0.65
    assert "Raw prompts" in metrics["privacy_note"]
    assert "tool payload bodies" in metrics["privacy_note"]


def test_openai_agents_live_timing_timeline_partitions_runner_and_attribution() -> None:
    timing = {
        "surface": "household-world",
        "intent": "open-ended",
        "task_name": "household-world",
        "runtime": "openai-agents-live",
        "provider_profile": "codex-router-responses",
        "wire_api": "responses",
        "model": "gpt-5.5",
        "evidence_lane": "world-public-labels",
        "started_at_epoch": 100.0,
        "openai_agents_start_epoch": 105.0,
        "openai_agents_end_epoch": 145.0,
        "server_finished_epoch": 146.0,
        "checker_start_epoch": 146.5,
        "checker_end_epoch": 148.0,
        "finished_at_epoch": 149.0,
        "mcp_client_session_timeout_s": 30.0,
        "runner_timing": {
            "total_elapsed_s": 49.0,
            "openai_agents_elapsed_s": 40.0,
        },
        "mcp_trace_timing": {
            "total_elapsed_s": 33.0,
            "between_tool_gap_s": 20.0,
            "robot_view_capture_s": 6.0,
            "tool_handler_s": 5.0,
            "other_mcp_overhead_s": 2.0,
            "tool_call_count": 10,
        },
        "mcp_control_plane_metrics": {"list_tools_request_count": 2},
        "openai_agents_event_metrics": {
            "tool_error_count": 1,
            "tool_error_classifications": {"mcp_client_request_timeout": 1},
        },
        "openai_agents_span_metrics": {
            "available": True,
            "span_end_count": 3,
            "span_type_counts": {"function": 2, "response": 1},
            "limitations": [],
        },
        "model_service_fallback_metrics": {
            "available": True,
            "source": "openai_agents_model_service_fallback_events",
            "limitations": [],
            "attempt_event_count": 2,
            "retry_scheduled_count": 1,
            "failure_event_count": 1,
            "success_event_count": 1,
            "failure_classes": {"provider_transient_failure": 1},
            "provider_reasons": {"upstream_unavailable": 1},
            "attempted_models": ["gpt-5.5"],
            "attempted_provider_profiles": ["codex-router-responses"],
            "attempted_wire_apis": ["responses"],
            "retry_delay_s_total": 1.0,
            "retry_delay_count": 1,
            "retry_exhausted": False,
            "final_outcomes": {"success": 1},
        },
        "model_input_filter_metrics": {
            "available": True,
            "source": "openai_agents_model_input_filter_events",
            "limitations": [],
            "event_count": 2,
            "enabled": True,
            "modes": ["public_tool_result_summary_v1"],
            "attempted_models": ["gpt-5.5"],
            "attempted_provider_profiles": ["codex-router-responses"],
            "attempted_wire_apis": ["responses"],
            "compacted_item_count": 2,
            "unchanged_item_count": 3,
            "repeated_item_count": 1,
            "input_bytes_before": 2500,
            "input_bytes_after": 1300,
            "input_bytes_reduced": 1200,
            "input_byte_reduction_ratio": 0.48,
            "metric_map_output_count": 3,
            "repeated_metric_map_output_count": 1,
            "metric_map_delta_compacted_count": 1,
            "metric_map_bytes_before": 1700,
            "metric_map_bytes_after": 800,
            "metric_map_bytes_reduced": 900,
            "metric_map_byte_reduction_ratio": 0.529412,
            "raw_fpv_image_memory_enabled": True,
            "raw_fpv_image_memory_modes": ["retain_latest_full_frame"],
            "raw_fpv_image_item_count": 2,
            "raw_fpv_image_retained_count": 1,
            "raw_fpv_image_evicted_count": 1,
            "raw_fpv_image_bytes_before": 1000,
            "raw_fpv_image_bytes_after": 350,
            "raw_fpv_image_bytes_reduced": 650,
            "raw_fpv_image_byte_reduction_ratio": 0.65,
        },
        "model_racing_observability_metrics": {
            "available": True,
            "source": "openai_agents_model_racing_observability_events",
            "limitations": [],
            "event_count": 2,
            "call_count": 1,
            "arm_count": 1,
            "max_arm_count_per_call": 1,
            "racing_enabled": False,
            "racing_multiplier": 1.0,
            "winner_count": 1,
            "cancelled_count": 0,
            "cancellation_observed_count": 0,
            "loser_billing_unknown_count": 0,
            "elapsed_s_total": 2.5,
            "max_elapsed_s": 2.5,
            "usage_available_count": 1,
            "usage_missing_count": 0,
            "total_input_tokens": 120,
            "total_cached_input_tokens": 20,
            "total_uncached_input_tokens": 100,
            "total_output_tokens": 30,
            "total_reasoning_tokens": 5,
            "methods": ["get_response"],
            "racing_modes": ["per_arm_observability_v1"],
            "final_outcomes": {"success": 1},
        },
        "context_metrics": {
            "available": True,
            "source": "openai_agents_span_usage",
            "limitations": [],
            "total_input_tokens": 500,
            "total_cached_input_tokens": 125,
            "total_uncached_input_tokens": 375,
            "cache_hit_ratio": 0.25,
            "response_span_duration_s": 4.0,
        },
        "cache_metrics": {
            "available": True,
            "source": "openai_agents_span_usage",
            "limitations": [],
            "provider_prompt_cache_observed": True,
            "cached_input_token_ratio": 0.25,
        },
        "context_growth_metrics": {
            "available": True,
            "source": "live_timing_and_trace",
            "limitations": [],
            "trace_event_count": 10,
            "observe_response_count": 2,
            "raw_fpv_observation_count": 0,
            "tool_response_bytes_total": 1000,
            "continuation_attempt_count": 1,
        },
        "openai_agents_attempts": [
            {
                "attempt_index": 0,
                "attempt_role": "initial",
                "phase": "agent-turn-complete",
                "started_at_epoch": 105.0,
                "finished_at_epoch": 115.0,
                "run_result_present": False,
                "recovery_action": "continue",
                "recovery_reason": "incomplete_agent_turn",
            },
            {
                "attempt_index": 1,
                "attempt_role": "continuation",
                "phase": "finished",
                "started_at_epoch": 115.0,
                "finished_at_epoch": 145.0,
                "run_result_present": True,
            },
        ],
    }

    timeline = _live_timing_timeline(timing)

    assert timeline["schema"] == "live_agent_timeline_v1"
    assert timeline["surface"] == "household-world"
    assert timeline["intent"] == "open-ended"
    assert timeline["task_name"] == "household-world"
    assert timeline["runtime"] == "openai-agents-live"
    assert timeline["provider_profile"] == "codex-router-responses"
    assert timeline["wire_api"] == "responses"
    assert timeline["model"] == "gpt-5.5"
    assert timeline["evidence_lane"] == "world-public-labels"
    assert [segment["duration_s"] for segment in timeline["runner_segments"]] == [
        5.0,
        40.0,
        1.0,
        1.5,
        1.0,
    ]
    assert [segment["name"] for segment in timeline["openai_agents_attempt_segments"]] == [
        "sdk_attempt_0",
        "sdk_attempt_1",
    ]
    assert timeline["latency_attribution"]["model_or_sdk_unattributed_s"] == 3.0
    assert timeline["latency_attribution"]["openai_agents_tool_error_classifications"] == {
        "mcp_client_request_timeout": 1
    }
    assert timeline["latency_attribution"]["openai_agents_span_artifact_available"] is True
    assert timeline["latency_attribution"]["openai_agents_span_count"] == 3
    assert timeline["latency_attribution"]["openai_agents_span_type_counts"] == {
        "function": 2,
        "response": 1,
    }
    assert timeline["latency_attribution"]["model_service_fallback_metrics"] == {
        "available": True,
        "source": "openai_agents_model_service_fallback_events",
        "limitations": [],
        "attempt_event_count": 2,
        "retry_scheduled_count": 1,
        "failure_event_count": 1,
        "success_event_count": 1,
        "failure_classes": {"provider_transient_failure": 1},
        "provider_reasons": {"upstream_unavailable": 1},
        "attempted_models": ["gpt-5.5"],
        "attempted_provider_profiles": ["codex-router-responses"],
        "attempted_wire_apis": ["responses"],
        "retry_delay_s_total": 1.0,
        "retry_delay_count": 1,
        "retry_exhausted": False,
        "final_outcomes": {"success": 1},
    }
    assert timeline["latency_attribution"]["model_input_filter_metrics"] == {
        "available": True,
        "source": "openai_agents_model_input_filter_events",
        "limitations": [],
        "event_count": 2,
        "enabled": True,
        "modes": ["public_tool_result_summary_v1"],
        "attempted_models": ["gpt-5.5"],
        "attempted_provider_profiles": ["codex-router-responses"],
        "attempted_wire_apis": ["responses"],
        "compacted_item_count": 2,
        "unchanged_item_count": 3,
        "repeated_item_count": 1,
        "input_bytes_before": 2500,
        "input_bytes_after": 1300,
        "input_bytes_reduced": 1200,
        "input_byte_reduction_ratio": 0.48,
        "metric_map_output_count": 3,
        "repeated_metric_map_output_count": 1,
        "metric_map_delta_compacted_count": 1,
        "metric_map_bytes_before": 1700,
        "metric_map_bytes_after": 800,
        "metric_map_bytes_reduced": 900,
        "metric_map_byte_reduction_ratio": 0.529412,
        "raw_fpv_image_memory_enabled": True,
        "raw_fpv_image_memory_modes": ["retain_latest_full_frame"],
        "raw_fpv_image_item_count": 2,
        "raw_fpv_image_retained_count": 1,
        "raw_fpv_image_evicted_count": 1,
        "raw_fpv_image_bytes_before": 1000,
        "raw_fpv_image_bytes_after": 350,
        "raw_fpv_image_bytes_reduced": 650,
        "raw_fpv_image_byte_reduction_ratio": 0.65,
    }
    assert timeline["latency_attribution"]["model_racing_observability_metrics"] == {
        "available": True,
        "source": "openai_agents_model_racing_observability_events",
        "limitations": [],
        "event_count": 2,
        "call_count": 1,
        "arm_count": 1,
        "max_arm_count_per_call": 1,
        "racing_enabled": False,
        "racing_multiplier": 1.0,
        "winner_count": 1,
        "cancelled_count": 0,
        "cancellation_observed_count": 0,
        "loser_billing_unknown_count": 0,
        "elapsed_s_total": 2.5,
        "max_elapsed_s": 2.5,
        "usage_available_count": 1,
        "usage_missing_count": 0,
        "total_input_tokens": 120,
        "total_cached_input_tokens": 20,
        "total_uncached_input_tokens": 100,
        "total_output_tokens": 30,
        "total_reasoning_tokens": 5,
        "methods": ["get_response"],
        "racing_modes": ["per_arm_observability_v1"],
        "final_outcomes": {"success": 1},
    }
    assert timeline["latency_attribution"]["context_metrics"] == {
        "available": True,
        "source": "openai_agents_span_usage",
        "limitations": [],
        "total_input_tokens": 500,
        "total_cached_input_tokens": 125,
        "total_uncached_input_tokens": 375,
        "cache_hit_ratio": 0.25,
    }
    assert timeline["latency_attribution"]["cache_metrics"] == {
        "available": True,
        "source": "openai_agents_span_usage",
        "limitations": [],
        "cached_input_token_ratio": 0.25,
        "provider_prompt_cache_observed": True,
    }
    assert timeline["latency_attribution"]["context_growth_metrics"] == {
        "available": True,
        "source": "live_timing_and_trace",
        "limitations": [],
        "trace_event_count": 10,
        "observe_response_count": 2,
        "raw_fpv_observation_count": 0,
        "tool_response_bytes_total": 1000,
        "continuation_attempt_count": 1,
    }


@pytest.mark.parametrize(
    ("detail", "expected_error", "expected_kind"),
    [
        (
            '{"schema":',
            "detail must contain a valid JSON object: Expecting value",
            "invalid_json",
        ),
        (
            '["wrong-shape"]',
            "detail must contain a JSON object, got list",
            "non_object",
        ),
    ],
)
def test_openai_agents_live_timing_compact_metrics_surface_structured_detail_errors(
    detail: str,
    expected_error: str,
    expected_kind: str,
) -> None:
    timeline = _live_timing_timeline(
        {
            "runtime": "openai-agents-live",
            "provider_profile": "codex-router-responses",
            "wire_api": "responses",
            "model": "gpt-5.5",
            "runner_timing": {},
            "agent_sdk_budget_terminal": {
                "available": True,
                "reason": "raw_fpv_candidate_budget_exhausted",
                "detail": detail,
            },
        }
    )

    metrics = timeline["latency_attribution"]["agent_sdk_budget_terminal"]
    assert metrics == {
        "available": True,
        "reason": "raw_fpv_candidate_budget_exhausted",
        "detail_source_error": expected_error,
        "detail_source_error_kind": expected_kind,
    }


def test_openai_agents_live_timing_compact_metrics_tolerates_plaintext_detail() -> None:
    timeline = _live_timing_timeline(
        {
            "runtime": "openai-agents-live",
            "provider_profile": "codex-router-responses",
            "wire_api": "responses",
            "model": "gpt-5.5",
            "runner_timing": {},
            "agent_sdk_budget_terminal": {
                "available": True,
                "reason": "provider_transient_failure",
                "provider_reason": "rate_limit",
                "detail": "429 Too Many Requests",
            },
        }
    )

    metrics = timeline["latency_attribution"]["agent_sdk_budget_terminal"]
    assert metrics == {
        "available": True,
        "reason": "provider_transient_failure",
        "provider_reason": "rate_limit",
    }


def test_openai_agents_live_timing_compact_metrics_extracts_valid_budget_detail() -> None:
    timeline = _live_timing_timeline(
        {
            "runtime": "openai-agents-live",
            "provider_profile": "codex-router-responses",
            "wire_api": "responses",
            "model": "gpt-5.5",
            "runner_timing": {},
            "agent_sdk_budget_terminal": {
                "available": True,
                "reason": "raw_fpv_candidate_budget_exhausted",
                "detail": json.dumps(
                    {
                        "schema": "openai_agents_raw_fpv_budget_failure_v1",
                        "raw_fpv_candidate_budget": 2,
                        "raw_fpv_repeated_failure_limit": 3,
                        "max_observe_per_waypoint": 1,
                        "candidate_attempt_count": 2,
                        "repeated_failure_fingerprints": ["a", "b"],
                        "repeated_failure_limit_hits": ["a"],
                        "observe_count_by_waypoint": {"wp-a": 1, "wp-b": 2},
                    }
                ),
            },
        }
    )

    metrics = timeline["latency_attribution"]["agent_sdk_budget_terminal"]
    assert metrics == {
        "available": True,
        "reason": "raw_fpv_candidate_budget_exhausted",
        "detail_schema": "openai_agents_raw_fpv_budget_failure_v1",
        "raw_fpv_candidate_budget": 2,
        "raw_fpv_repeated_failure_limit": 3,
        "max_observe_per_waypoint": 1,
        "candidate_attempt_count": 2,
        "repeated_failure_count": 2,
        "repeated_failure_limit_hit_count": 1,
        "observe_waypoint_count": 2,
    }
