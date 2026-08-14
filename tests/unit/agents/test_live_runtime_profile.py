from __future__ import annotations

import pytest

from roboclaws.agents.drivers.openai_agents_perf_profile import (
    resolve_agent_sdk_perf_profile as _resolve_agent_sdk_perf_profile,
)
from tests.unit.agents.live_runtime_support import (
    _expected_model_racing_observability,
    _openai_agents_perf_profile_base_args,
)


def test_openai_agents_perf_profile_resolves_context_managed_defaults(monkeypatch) -> None:
    monkeypatch.delenv("ROBOCLAWS_OPENAI_AGENTS_PERF_PROFILE", raising=False)
    monkeypatch.delenv("ROBOCLAWS_OPENAI_AGENTS_MCP_CLIENT_SESSION_TIMEOUT_S", raising=False)
    profile = _resolve_agent_sdk_perf_profile(
        _openai_agents_perf_profile_base_args(profile="camera-grounded-labels")
    )

    assert profile["profile_id"] == "context_managed_v1"
    assert profile["source"] == "default"
    assert profile["provider_profile"] == "kimi-openai-chat"
    assert profile["wire_api"] == "chat-completions"
    assert profile["model_family"] == "kimi"
    assert profile["evidence_lane"] == "camera-grounded-labels"
    assert profile["model_thinking_mode"] == "default"
    assert profile["continuation_mode"] == "state_summary_only"
    assert profile["max_turns"] == 128
    assert profile["max_continuations"] == 1
    assert profile["cache_tools_list"] is True
    assert profile["mcp_client_session_timeout_s"] == 30.0
    assert profile["context_soft_limit_tokens"] == 64_000
    assert profile["context_hard_limit_tokens"] == 96_000
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
        "include_usage": True,
        "extra_headers": {"User-Agent": "claude-code/1.0.0"},
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


def test_openai_agents_perf_profile_rejects_unknown_profile_id(monkeypatch) -> None:
    monkeypatch.delenv("ROBOCLAWS_OPENAI_AGENTS_PERF_PROFILE", raising=False)

    with pytest.raises(ValueError, match="unsupported OpenAI Agents SDK performance profile"):
        _resolve_agent_sdk_perf_profile(
            _openai_agents_perf_profile_base_args(agent_sdk_perf_profile="unknown_profile")
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


def test_openai_agents_perf_profile_rejects_route_incompatible_model(monkeypatch) -> None:
    monkeypatch.delenv("ROBOCLAWS_OPENAI_AGENTS_PERF_PROFILE", raising=False)

    with pytest.raises(
        ValueError,
        match=("model 'kimi-k2.7-code' is incompatible with provider_profile 'minimax-responses'"),
    ):
        _resolve_agent_sdk_perf_profile(
            _openai_agents_perf_profile_base_args(
                provider_profile="minimax-responses",
                model="kimi-k2.7-code",
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
        _openai_agents_perf_profile_base_args(model_thinking_mode="enabled")
    )

    assert profile["model_thinking_mode"] == "enabled"
    assert profile["sdk_model_settings"]["model_thinking_mode"] == "enabled"


def test_openai_agents_perf_profile_does_not_infer_raw_fpv_support(monkeypatch) -> None:
    monkeypatch.delenv("ROBOCLAWS_OPENAI_AGENTS_PERF_PROFILE", raising=False)
    raw = _resolve_agent_sdk_perf_profile(
        _openai_agents_perf_profile_base_args(
            agent_sdk_perf_profile="context_managed_v1",
            profile="camera-raw-fpv",
        )
    )

    assert raw["max_turns"] == 128
    assert raw["max_continuations"] == 1
    assert raw["raw_fpv_candidate_budget"] is None
    assert raw["raw_fpv_repeated_failure_limit"] is None
    assert raw["max_observe_per_waypoint"] == 1
    assert raw["model_input_compaction"]["enabled"] is True
    assert raw["model_input_compaction"]["raw_fpv_image_memory"]["enabled"] is False
    assert raw["model_input_compaction"]["completed_tool_history_limit"] == 0
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
