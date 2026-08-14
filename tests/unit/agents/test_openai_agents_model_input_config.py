from __future__ import annotations

import json
from argparse import Namespace
from pathlib import Path

import pytest

from roboclaws.agents.drivers.openai_agents_compaction import _compact_model_input_items
from roboclaws.agents.drivers.openai_agents_input_config import _input_compaction_config
from roboclaws.agents.drivers.openai_agents_perf_profile import resolve_agent_sdk_perf_profile
from roboclaws.agents.live_runtime import LiveAgentMCPServer, LiveAgentRequest


def _live_request_with_compaction(
    tmp_path: Path,
    min_chars: object | None = None,
) -> LiveAgentRequest:
    config: dict[str, object] = {"enabled": True}
    if min_chars is not None:
        config["min_chars"] = min_chars
    return LiveAgentRequest(
        run_id="household-world",
        skill_name="household-world",
        kickoff_prompt="clean the room",
        mcp_server=LiveAgentMCPServer(name="cleanup", url="http://127.0.0.1:18788/mcp"),
        run_dir=tmp_path / "run",
        metadata={"model_input_compaction": config},
    )


def _perf_profile_args(**overrides: object) -> Namespace:
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


@pytest.mark.parametrize(
    ("env_value", "expected_detail"),
    [
        ("0", "ROBOCLAWS_OPENAI_AGENTS_INPUT_COMPACTION_MIN_CHARS must be a positive integer"),
        ("-5", "ROBOCLAWS_OPENAI_AGENTS_INPUT_COMPACTION_MIN_CHARS must be a positive integer"),
    ],
)
def test_input_compaction_config_rejects_non_positive_min_chars_env(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    env_value: str,
    expected_detail: str,
) -> None:
    monkeypatch.setenv("ROBOCLAWS_OPENAI_AGENTS_INPUT_COMPACTION_MIN_CHARS", env_value)

    with pytest.raises(ValueError, match=expected_detail):
        _input_compaction_config(_live_request_with_compaction(tmp_path))


@pytest.mark.parametrize(
    ("min_chars", "expected_detail"),
    [
        (True, "model_input_compaction.min_chars must be a positive integer, got True"),
        (0, "model_input_compaction.min_chars must be a positive integer, got 0"),
        (-5, "model_input_compaction.min_chars must be a positive integer, got -5"),
    ],
)
def test_input_compaction_config_rejects_invalid_direct_min_chars(
    tmp_path: Path,
    min_chars: object,
    expected_detail: str,
) -> None:
    with pytest.raises(ValueError, match=expected_detail):
        _input_compaction_config(_live_request_with_compaction(tmp_path, min_chars))


@pytest.mark.parametrize(
    ("env_value", "direct_value", "expected_error"),
    [
        (
            "0",
            None,
            "OpenAI Agents SDK setting model_input_compaction_min_chars must be positive",
        ),
        (
            "",
            0,
            "OpenAI Agents SDK setting model_input_compaction_min_chars must be positive",
        ),
        (
            "",
            True,
            "OpenAI Agents SDK setting model_input_compaction_min_chars must be an integer",
        ),
    ],
)
def test_perf_profile_rejects_invalid_compaction_min_chars(
    monkeypatch: pytest.MonkeyPatch,
    env_value: str,
    direct_value: object | None,
    expected_error: str,
) -> None:
    if env_value:
        monkeypatch.setenv("ROBOCLAWS_OPENAI_AGENTS_INPUT_COMPACTION_MIN_CHARS", env_value)
    else:
        monkeypatch.delenv("ROBOCLAWS_OPENAI_AGENTS_INPUT_COMPACTION_MIN_CHARS", raising=False)

    with pytest.raises(ValueError, match=expected_error):
        resolve_agent_sdk_perf_profile(
            _perf_profile_args(model_input_compaction_min_chars=direct_value)
        )


def test_input_compaction_accepts_disabled_nested_zero_retention_from_perf_profile(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("ROBOCLAWS_OPENAI_AGENTS_PERF_PROFILE", raising=False)
    profile = resolve_agent_sdk_perf_profile(
        _perf_profile_args(
            provider_profile="minimax-responses",
            model="",
            agent_sdk_perf_profile="baseline",
        )
    )
    request = LiveAgentRequest(
        run_id="household-world",
        skill_name="household-world",
        kickoff_prompt="inspect the room",
        mcp_server=LiveAgentMCPServer(name="cleanup", url="http://127.0.0.1:18788/mcp"),
        run_dir=tmp_path / "run",
        metadata={"agent_sdk_perf_profile": profile},
    )

    config = _input_compaction_config(request)

    assert config["enabled"] is False
    assert config["raw_fpv_image_memory"]["enabled"] is False
    assert config["raw_fpv_image_memory"]["retained_full_frame_limit"] == 0
    assert config["camera_grounded_history"]["enabled"] is False
    assert config["camera_grounded_history"]["retained_recent_outputs"] == 0


def test_input_compaction_rejects_enabled_nested_zero_retention(tmp_path: Path) -> None:
    request = LiveAgentRequest(
        run_id="household-world",
        skill_name="household-world",
        kickoff_prompt="inspect the room",
        mcp_server=LiveAgentMCPServer(name="cleanup", url="http://127.0.0.1:18788/mcp"),
        run_dir=tmp_path / "run",
        metadata={
            "model_input_compaction": {
                "enabled": True,
                "raw_fpv_image_memory": {
                    "enabled": True,
                    "retained_full_frame_limit": 0,
                },
            }
        },
    )

    with pytest.raises(
        ValueError,
        match=(
            "OpenAI Agents SDK setting raw_fpv_image_memory.retained_full_frame_limit "
            "must be a positive integer"
        ),
    ):
        _input_compaction_config(request)


def test_model_input_camera_history_fails_aloud_on_malformed_mcp_text_content() -> None:
    items = [
        {
            "type": "mcp_call",
            "id": "mcp_1",
            "name": "roboclaws__observe_camera_grounded_candidates",
            "server_label": "roboclaws",
            "arguments": "{}",
            "output": {"content": [{"type": "text", "text": '{"ok": true'}]},
            "status": "completed",
        }
    ]

    with pytest.raises(
        ValueError,
        match=(
            "OpenAI Agents model-input camera-grounded output text content "
            "source must contain valid JSON object"
        ),
    ):
        _compact_model_input_items(
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


def test_model_input_camera_history_fails_aloud_on_non_object_json_mcp_output() -> None:
    items = [
        {
            "type": "mcp_call",
            "id": "mcp_1",
            "name": "roboclaws__observe_camera_grounded_candidates",
            "server_label": "roboclaws",
            "arguments": "{}",
            "output": json.dumps([{"ok": True}]),
            "status": "completed",
        }
    ]

    with pytest.raises(
        ValueError,
        match=(
            "OpenAI Agents model-input camera-grounded output source must contain a JSON object"
        ),
    ):
        _compact_model_input_items(
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


def test_model_input_camera_history_fails_aloud_on_double_encoded_non_object_output() -> None:
    items = [
        {
            "type": "mcp_call",
            "id": "mcp_1",
            "name": "roboclaws__observe_camera_grounded_candidates",
            "server_label": "roboclaws",
            "arguments": "{}",
            "output": json.dumps(json.dumps([{"ok": True}])),
            "status": "completed",
        }
    ]

    with pytest.raises(
        ValueError,
        match=(
            "OpenAI Agents model-input camera-grounded output source must contain a JSON object"
        ),
    ):
        _compact_model_input_items(
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


def test_model_input_camera_history_accepts_double_encoded_mcp_text_wrapper() -> None:
    output = json.dumps(
        {
            "content": [
                {
                    "type": "text",
                    "text": json.dumps(
                        {
                            "ok": True,
                            "tool": "observe_camera_grounded_candidates",
                            "observation_id": "raw_fpv_001",
                            "camera_model_candidates": [
                                {
                                    "object_id": "cup_1",
                                    "actionability_status": "actionable",
                                    "large_public_camera_payload": "x" * 5000,
                                }
                            ],
                        }
                    ),
                }
            ]
        }
    )
    items = [
        {
            "type": "mcp_call",
            "id": f"mcp_{idx}",
            "name": "roboclaws__observe_camera_grounded_candidates",
            "server_label": "roboclaws",
            "arguments": "{}",
            "output": json.dumps(output),
            "status": "completed",
        }
        for idx in range(1, 3)
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

    replacement = json.loads(filtered[0]["output"])
    assert replacement["schema"] == "roboclaws_camera_grounded_history_summary_v1"
    assert replacement["observation_id"] == "raw_fpv_001"
    assert replacement["candidate_count"] == 1
    assert replacement["actionable_candidate_count"] == 1
    assert metrics["camera_grounded_history_compacted_count"] == 1
    assert metrics["camera_grounded_history_retained_count"] == 1


def test_model_input_camera_history_still_tolerates_plaintext_mcp_output() -> None:
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
        for idx in range(1, 3)
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
    assert first_replacement["candidate_count"] == 0
    assert metrics["camera_grounded_history_item_count"] == 2
    assert metrics["camera_grounded_history_retained_count"] == 1
    assert metrics["camera_grounded_history_compacted_count"] == 1
