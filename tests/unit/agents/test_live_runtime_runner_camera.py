from __future__ import annotations

import json
from argparse import Namespace
from pathlib import Path

from roboclaws.agents.household_live_runner import (
    LiveOpenAIAgentsHouseholdRunner,
)
from roboclaws.agents.live_runtime import (
    LiveAgentRequest,
    LiveAgentResult,
)
from tests.unit.agents.live_runtime_support import (
    _isolated_repo_root,
)


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
        "roboclaws.agents.household_live_runner.subprocess.Popen",
        FakeProcess,
    )
    port_checks = iter([False, True])
    monkeypatch.setattr(
        "roboclaws.agents.drivers.household_live.port_accepting",
        lambda *_args, **_kwargs: next(port_checks),
    )
    monkeypatch.setattr(
        "roboclaws.agents.household_live_runner.OpenAIAgentsLiveRuntime",
        lambda: FakeRuntime(),
    )
    monkeypatch.setattr(
        "roboclaws.agents.drivers.household_live.run_and_tee",
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
        provider_profile="kimi-openai-chat",
        model="kimi-k2.7-code",
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

    status = LiveOpenAIAgentsHouseholdRunner(args).run()

    assert status == 0
    assert server_commands
    assert "--robot-view-capture-policy" in server_commands[0]
    policy_index = server_commands[0].index("--robot-view-capture-policy")
    assert server_commands[0][policy_index + 1] == "action_timeline"
    timing = json.loads((run_dir / "live_timing.json").read_text(encoding="utf-8"))
    policy = timing["agent_sdk_perf_profile"]["robot_view_capture_policy"]
    assert policy["policy"] == "action_timeline"
    assert timing["agent_sdk_robot_view_capture_policy"] == policy
