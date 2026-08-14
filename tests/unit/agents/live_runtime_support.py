from __future__ import annotations

import json
from argparse import Namespace
from pathlib import Path

from roboclaws.agents.drivers.openai_agents_live import OpenAIAgentsLiveRuntime
from roboclaws.agents.live_runtime import (
    LiveAgentMCPServer,
    LiveAgentRequest,
)
from roboclaws.household.cleanup_validation_args import parse_args as parse_cleanup_args


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
    assert timing["agent_sdk_perf_profile"]["context_hard_limit_tokens"] == 96_000
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
        "extra_headers": {"User-Agent": "claude-code/1.0.0"},
        "include_usage": True,
        "model_thinking_mode": "default",
        "parallel_tool_calls": False,
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
    assert checker_command[1:3] == ["-m", "roboclaws.household.cleanup_validation_cli"]
    parsed_checker_args = parse_cleanup_args(checker_command[3:])
    assert parsed_checker_args.path.name == "run_result.json"
    assert parsed_checker_args.expect_profile is None
    assert "--require-advisory-scoring" not in checker_command
    assert "--expect-policy" in checker_command
    assert "openai_agents_agent" in checker_command
    assert "--require-clean-agent-run" in checker_command


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
        provider_profile="kimi-openai-chat",
        model="kimi-k2.7-code",
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
