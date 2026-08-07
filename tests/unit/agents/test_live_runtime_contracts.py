from __future__ import annotations

import asyncio
import json
from pathlib import Path

import pytest

from roboclaws.agents.drivers.openai_agents_live import OpenAIAgentsLiveRuntime
from roboclaws.agents.household_live_config import (
    MAX_AGENT_SDK_SKILL_CONTEXT_BYTES,
    _load_agent_sdk_skill_context,
)
from roboclaws.agents.household_live_continuation import IncompleteTurnRecoveryPolicy
from roboclaws.agents.household_live_handoff import _eval_telemetry_identity
from roboclaws.agents.live_runtime import (
    LiveAgentMCPServer,
    LiveAgentRequest,
    LiveAgentResult,
    live_agent_result_from_artifacts,
)
from roboclaws.agents.live_status import LiveAgentFailure
from roboclaws.household.realworld_done_readiness import (
    COMPLETION_SNAPSHOT_SCHEMA,
    completion_snapshot_digest,
)


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


def test_openai_agents_runtime_accepts_post_done_sdk_cancellation(
    tmp_path: Path, monkeypatch
) -> None:
    def cancel_after_done(request, **_kwargs):  # noqa: ANN001
        request.run_dir.mkdir(parents=True, exist_ok=True)
        (request.run_dir / "run_result.json").write_text("{}\n", encoding="utf-8")
        raise asyncio.CancelledError("cancelled while draining completed tool calls")

    monkeypatch.setattr(
        "roboclaws.agents.drivers.openai_agents_live._run_openai_agents",
        cancel_after_done,
    )
    request = LiveAgentRequest(
        run_id="household-world",
        skill_name="household-world",
        kickoff_prompt="clean the room",
        mcp_server=LiveAgentMCPServer(name="cleanup", url="http://127.0.0.1:18788/mcp"),
        run_dir=tmp_path / "run",
    )

    result = OpenAIAgentsLiveRuntime().run(request)

    assert result.phase == "finished"
    assert result.exit_status == 0
    assert result.run_result_present is True


def test_openai_agents_runtime_fails_cancellation_before_done(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(
        "roboclaws.agents.drivers.openai_agents_live._run_openai_agents",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(asyncio.CancelledError("early")),
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
    assert result.reason == "agent_runtime_cancelled"


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


def test_agent_sdk_skill_context_loader_reports_missing_source(tmp_path: Path) -> None:
    context = _load_agent_sdk_skill_context(
        tmp_path / "repo",
        skill_name="household-world",
    )

    assert context["included"] is False
    assert context["reason"] == "source_unavailable"
    assert context["relative_path"] == "skills/household-world/SKILL.md"
    assert "content" not in context


def test_agent_sdk_skill_context_records_digest_of_truncated_delivery(tmp_path: Path) -> None:
    skill_path = tmp_path / "repo" / "skills" / "household-world" / "SKILL.md"
    skill_path.parent.mkdir(parents=True)
    skill_path.write_text("# Household World\n" + "x" * MAX_AGENT_SDK_SKILL_CONTEXT_BYTES)

    context = _load_agent_sdk_skill_context(
        tmp_path / "repo",
        skill_name="household-world",
        delivery_cell="sandbox-skills",
    )

    assert context["truncated"] is True
    assert context["delivery_content_sha256"] == context["delivery"].artifact()["content_sha256"]
    assert context["delivery_content_sha256"] != context["sha256"]


def test_context_budget_result_recovers_with_compact_continuation(tmp_path: Path) -> None:
    run_dir = tmp_path / "run"
    run_dir.mkdir()
    snapshot = {
        "schema": COMPLETION_SNAPSHOT_SCHEMA,
        "source_tool": "observe",
        "response_id": 1,
        "task_intent": "cleanup",
        "status": "blocked",
        "blockers": [],
        "next_actions": [{"required_tool": "navigate_to_waypoint"}],
        "policy_uses_private_truth": False,
    }
    snapshot["digest"] = completion_snapshot_digest(snapshot)
    (run_dir / "trace.jsonl").write_text(
        json.dumps(
            {
                "event": "response",
                "tool": "observe",
                "response": {"ok": True, "completion": snapshot},
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


def test_eval_telemetry_identity_is_closed_and_fail_disabled(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv(
        "ROBOCLAWS_EVAL_TELEMETRY_IDENTITY",
        '{"suite_id":"suite-1","trial_id":"trial-1","repetition":0}',
    )
    assert _eval_telemetry_identity() == {
        "suite_id": "suite-1",
        "trial_id": "trial-1",
        "repetition": 0,
    }

    monkeypatch.setenv("ROBOCLAWS_EVAL_TELEMETRY_IDENTITY", '{"api_key":"secret"}')
    assert _eval_telemetry_identity() == {}

    monkeypatch.setenv("ROBOCLAWS_EVAL_TELEMETRY_IDENTITY", "not-json")
    assert _eval_telemetry_identity() == {}
