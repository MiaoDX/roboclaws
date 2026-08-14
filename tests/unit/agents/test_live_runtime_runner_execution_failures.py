from __future__ import annotations

import json
from argparse import Namespace
from pathlib import Path
from types import SimpleNamespace

from roboclaws.agents.drivers.openai_agents_live import OpenAIAgentsLiveRuntime
from roboclaws.agents.household_live_lifecycle import (
    LiveOpenAIAgentsHouseholdRunner,
)
from roboclaws.agents.live_runtime import (
    LiveAgentMCPServer,
    LiveAgentRequest,
    LiveAgentResult,
)
from tests.unit.agents.live_runtime_support import (
    FakeModelSettings,
    FakeRunConfig,
    _isolated_repo_root,
)


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

    monkeypatch.setenv("MIMO_RESPONSES_BASE_URL", "https://mimo.example.test/v1")
    monkeypatch.setenv("MIMO_RESPONSES_API_KEY", "fake-mimo-key")
    monkeypatch.setenv("MIMO_RESPONSES_MODEL", "opaque-mimo-model")
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
        provider_profile="mimo-responses",
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
    assert "otherwise the canonical Skill owns task strategy" in instructions
    assert "override any conflicting generic skill-context" not in instructions
    assert skill_text in instructions
    assert "clean the room" not in instructions
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
        "roboclaws.agents.household_live_lifecycle.subprocess.Popen",
        FakeProcess,
    )
    port_checks = iter([False, True])
    monkeypatch.setattr(
        "roboclaws.agents.drivers.household_live.port_accepting",
        lambda *_args, **_kwargs: next(port_checks),
    )
    monkeypatch.setattr(
        "roboclaws.agents.household_live_lifecycle.OpenAIAgentsLiveRuntime",
        lambda: FakeRuntime(),
    )

    def fake_run_and_tee(*_args, **_kwargs):
        nonlocal checker_called
        checker_called = True
        return 0

    monkeypatch.setattr(
        "roboclaws.agents.drivers.household_live.run_and_tee",
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
        provider_profile="kimi-openai-chat",
        model="kimi-k2.7-code",
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

    status = LiveOpenAIAgentsHouseholdRunner(args).run()

    assert status == 1
    assert len(prompts) == 1
    assert checker_called is False
    status_payload = json.loads((run_dir / "live_status.json").read_text(encoding="utf-8"))
    assert status_payload["phase"] == "failed"
    assert status_payload["exit_status"] == 1
    assert status_payload["reason"] == (
        "terminal-incomplete: missing completion continuation state"
    )
    timing = json.loads((run_dir / "live_timing.json").read_text(encoding="utf-8"))
    assert len(timing["openai_agents_attempts"]) == 1
    assert "openai_agents" not in timing
