from __future__ import annotations

import json
from argparse import Namespace
from pathlib import Path

from roboclaws.agents.drivers.openai_agents_compaction import _compact_model_input_items
from roboclaws.agents.household_live_continuation import (
    _kickoff_prompt_source,
    _profiled_kickoff_prompt,
)
from roboclaws.agents.household_live_lifecycle import LiveOpenAIAgentsHouseholdRunner
from roboclaws.agents.live_runtime import (
    LiveAgentRequest,
    LiveAgentResult,
)
from roboclaws.agents.prompts.household_cleanup import (
    render_kickoff_prompt,
    render_map_build_prompt,
)
from tests.unit.agents.live_runtime_support import (
    _isolated_repo_root,
)


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

    status = LiveOpenAIAgentsHouseholdRunner(args).run()

    assert status == 0
    assert server_commands
    assert prompts
    assert "Camera-grounded observation mode=composite" in prompts[0]
    assert "observe_camera_grounded_candidates" in prompts[0]
    assert "do not call declare_visual_candidates again" in prompts[0]
    assert "--agent-sdk-camera-grounded-composite-tools" in server_commands[0]
    timing = json.loads((run_dir / "live_timing.json").read_text(encoding="utf-8"))
    composite = timing["agent_sdk_perf_profile"]["camera_grounded_composite_tools"]
    assert composite["enabled"] is True
    assert composite["tool_names"] == ["observe_camera_grounded_candidates"]
    assert timing["agent_sdk_camera_grounded_composite_tools"] == composite


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
    assert "Camera-grounded observation mode=composite" in prompt
    assert "declare_visual_candidates with observation_id only" not in prompt
    assert "response already includes the server-side declaration" in prompt
    assert "do not call declare_visual_candidates again" in prompt
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

    assert "Waypoint observation tool=observe" in stale_prompt
    assert "observe_camera_grounded_candidates" in prompt
    assert "Waypoint observation tool=observe_camera_grounded_candidates" in prompt
    assert "Per-waypoint observation budget=1" in prompt
    assert "bounded re-observation" not in prompt
    assert "profile observe cadence=5 per waypoint" in prompt
    assert "effective observe cadence=1 per waypoint" in prompt
    assert "max_observe_per_waypoint override=true" in prompt
    assert "profile body-turn cadence overridden=true" in prompt
    assert "do not call declare_visual_candidates again" in prompt
    assert "Manipulation tools are not entitled for this run" in prompt


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
    stale_prompt = render_kickoff_prompt("camera-grounded-labels")
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

    status = LiveOpenAIAgentsHouseholdRunner(args).run()

    assert status == 0
    assert "declare_visual_candidates with observation_id only" in stale_prompt
    assert prompts
    assert "Camera-grounded observation mode=composite" in prompts[0]
    assert "declare_visual_candidates with observation_id only" not in prompts[0]
    assert "do not call declare_visual_candidates again" in prompts[0]
    timing = json.loads((run_dir / "live_timing.json").read_text(encoding="utf-8"))
    assert timing["kickoff_prompt_source"] == "profile-rendered-lane-default"
