from __future__ import annotations

import json
from argparse import Namespace
from pathlib import Path

from roboclaws.agents.household_live_lifecycle import (
    LiveOpenAIAgentsHouseholdRunner,
)
from roboclaws.agents.live_runtime import (
    LiveAgentRequest,
    LiveAgentResult,
)
from roboclaws.household.realworld_done_readiness import (
    COMPLETION_SNAPSHOT_SCHEMA,
    completion_snapshot_digest,
)
from tests.unit.agents.live_runtime_support import (
    _assert_context_managed_openai_agents_timing,
    _assert_openai_agents_timeline_and_checker,
    _isolated_repo_root,
)


def _completion(tool: str) -> dict:
    snapshot = {
        "schema": COMPLETION_SNAPSHOT_SCHEMA,
        "source_tool": tool,
        "response_id": 1,
        "task_intent": "cleanup",
        "status": "blocked",
        "blockers": [],
        "next_actions": [{"required_tool": "done"}],
        "policy_uses_private_truth": False,
    }
    snapshot["digest"] = completion_snapshot_digest(snapshot)
    return snapshot


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
            assert request.provider_profile == "kimi-openai-chat"
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

    def fake_run_and_tee(command, *, cwd, stdout_path, stderr_path, env):
        checker_commands.append(command)
        stdout_path.write_text("checker ok\n", encoding="utf-8")
        return 0

    monkeypatch.setattr(
        "roboclaws.agents.drivers.household_live.run_and_tee",
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
        provider_profile="kimi-openai-chat",
        model="kimi-k2.7-code",
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

    status = LiveOpenAIAgentsHouseholdRunner(args).run()

    assert status == 0
    status_payload = json.loads((run_dir / "live_status.json").read_text(encoding="utf-8"))
    assert status_payload["phase"] == "finished"
    assert status_payload["exit_status"] == 0
    timing = json.loads((run_dir / "live_timing.json").read_text(encoding="utf-8"))
    _assert_context_managed_openai_agents_timing(timing)
    _assert_openai_agents_timeline_and_checker(timing, checker_commands)


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

    def fake_run_and_tee(command, *, cwd, stdout_path, stderr_path, env):
        stdout_path.write_text("checker ok\n", encoding="utf-8")
        return 0

    monkeypatch.setattr(
        "roboclaws.agents.drivers.household_live.run_and_tee",
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
        provider_profile="kimi-openai-chat",
        model="kimi-k2.7-code",
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

    status = LiveOpenAIAgentsHouseholdRunner(args).run()

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
                (request.run_dir / "trace.jsonl").write_text(
                    json.dumps(
                        {
                            "event": "response",
                            "tool": "observe",
                            "response": {"ok": True, "completion": _completion("observe")},
                        }
                    )
                    + "\n",
                    encoding="utf-8",
                )
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

    def fake_run_and_tee(command, *, cwd, stdout_path, stderr_path, env):
        checker_commands.append(command)
        stdout_path.write_text("checker ok\n", encoding="utf-8")
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

    status = LiveOpenAIAgentsHouseholdRunner(args).run()

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
                                        "completion": _completion("observe"),
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

    def fake_run_and_tee(command, *, cwd, stdout_path, stderr_path, env):
        stdout_path.write_text("checker ok\n", encoding="utf-8")
        return 0

    monkeypatch.setattr(
        "roboclaws.agents.drivers.household_live.run_and_tee",
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
        provider_profile="kimi-openai-chat",
        model="kimi-k2.7-code",
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

    status = LiveOpenAIAgentsHouseholdRunner(args).run()

    assert status == 0
    assert len(prompts) == 2
    assert prompts[0] == full_prompt
    assert full_prompt not in prompts[1]
    assert "compact_continuation_state" in prompts[1]
    assert COMPLETION_SNAPSHOT_SCHEMA in prompts[1]
    assert _completion("observe")["digest"] in prompts[1]
    timing = json.loads((run_dir / "live_timing.json").read_text(encoding="utf-8"))
    assert timing["openai_agents_attempts"][0]["recovery_action"] == "continue"
    assert timing["openai_agents_attempts"][0]["continuation_prompt_chars"] == len(prompts[1])


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
                                        "completion": _completion(
                                            "observe_camera_grounded_candidates"
                                        ),
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
    monkeypatch.setattr(
        "roboclaws.agents.drivers.household_live.run_and_tee",
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
        provider_profile="minimax-responses",
        model="MiniMax-M3",
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

    status = LiveOpenAIAgentsHouseholdRunner(args).run()

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
