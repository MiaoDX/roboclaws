from __future__ import annotations

import argparse
import os
from typing import Any

from roboclaws.agents.drivers import openai_agents_retry_model as retry_model
from roboclaws.agents.drivers.openai_agents_profile_capture import (
    _robot_view_capture_policy_profile,
)
from roboclaws.agents.drivers.openai_agents_profile_runtime import (
    _sdk_model_settings_for_profile,
    _sdk_run_config_for_profile,
)
from roboclaws.agents.drivers.openai_agents_profile_settings import (
    _bool_arg_setting,
    _float_setting,
    _int_setting,
    _positive_int_setting,
    _raise_enabled_count_error,
    _string_setting,
    _validate_context_limits,
)
from roboclaws.agents.drivers.openai_agents_run_config import (
    DEFAULT_OPENAI_AGENTS_MAX_TURNS,
    MCP_CLIENT_SESSION_TIMEOUT_ENV,
)
from roboclaws.agents.thinking_policy import normalize_thinking_mode
from roboclaws.core.provider_catalog import (
    ROUTE_CAP_SUPPORTED,
    WIRE_RESPONSES,
    model_family_for_route_model,
    normalize_provider_route,
    provider_route_spec,
    route_capabilities_for_engine,
)
from roboclaws.core.robot_view_capture import (
    ROBOT_VIEW_CAPTURE_POLICY_FULL,
)

DEFAULT_INCOMPLETE_TURN_CONTINUATION_ATTEMPTS = 2
AGENT_SDK_PERF_PROFILE_BASELINE = "baseline"
AGENT_SDK_PERF_PROFILE_CONTEXT_MANAGED_V1 = "context_managed_v1"
AGENT_SDK_PERF_PROFILE_ENV = "ROBOCLAWS_OPENAI_AGENTS_PERF_PROFILE"
CONTINUATION_MODE_ENV = "ROBOCLAWS_OPENAI_AGENTS_CONTINUATION_MODE"
CONTEXT_SOFT_LIMIT_ENV = "ROBOCLAWS_OPENAI_AGENTS_CONTEXT_SOFT_LIMIT_TOKENS"
CONTEXT_HARD_LIMIT_ENV = "ROBOCLAWS_OPENAI_AGENTS_CONTEXT_HARD_LIMIT_TOKENS"
MODEL_INPUT_COMPACTION_ENV = "ROBOCLAWS_OPENAI_AGENTS_INPUT_COMPACTION"
MODEL_INPUT_COMPACTION_MIN_CHARS_ENV = "ROBOCLAWS_OPENAI_AGENTS_INPUT_COMPACTION_MIN_CHARS"
MODEL_RACING_ENV = "ROBOCLAWS_OPENAI_AGENTS_MODEL_RACING"
MODEL_RACING_ARM_COUNT_ENV = "ROBOCLAWS_OPENAI_AGENTS_MODEL_RACING_ARM_COUNT"
RAW_FPV_IMAGE_MEMORY_ENV = "ROBOCLAWS_OPENAI_AGENTS_RAW_FPV_IMAGE_MEMORY"
RAW_FPV_IMAGE_MEMORY_RETAIN_ENV = "ROBOCLAWS_OPENAI_AGENTS_RAW_FPV_IMAGE_MEMORY_RETAIN"
CAMERA_GROUNDED_HISTORY_COMPACTION_ENV = (
    "ROBOCLAWS_OPENAI_AGENTS_CAMERA_GROUNDED_HISTORY_COMPACTION"
)
CAMERA_GROUNDED_HISTORY_RETAIN_ENV = "ROBOCLAWS_OPENAI_AGENTS_CAMERA_GROUNDED_HISTORY_RETAIN"
CAMERA_GROUNDED_COMPOSITE_TOOLS_ENV = "ROBOCLAWS_OPENAI_AGENTS_CAMERA_GROUNDED_COMPOSITE_TOOLS"
ROBOT_VIEW_CAPTURE_POLICY_ENV = "ROBOCLAWS_OPENAI_AGENTS_ROBOT_VIEW_CAPTURE_POLICY"
MODEL_THINKING_MODE_ENV = "ROBOCLAWS_OPENAI_AGENTS_THINKING_MODE"
MAX_OBSERVE_PER_WAYPOINT_ENV = "ROBOCLAWS_OPENAI_AGENTS_MAX_OBSERVE_PER_WAYPOINT"
RAW_FPV_CANDIDATE_BUDGET_ENV = "ROBOCLAWS_OPENAI_AGENTS_RAW_FPV_CANDIDATE_BUDGET"
RAW_FPV_REPEATED_FAILURE_LIMIT_ENV = "ROBOCLAWS_OPENAI_AGENTS_RAW_FPV_REPEATED_FAILURE_LIMIT"
DONE_RETRY_BUDGET_ENV = "ROBOCLAWS_OPENAI_AGENTS_DONE_RETRY_BUDGET"
DEFAULT_MCP_CLIENT_SESSION_TIMEOUT_S = 30.0
RAW_FPV_IMAGE_MEMORY_POLICY = (
    "model-facing raw-FPV image memory only; MCP traces, reports, and image artifacts remain "
    "complete"
)
CAMERA_GROUNDED_HISTORY_POLICY = (
    "model-facing camera-grounded history compaction only; MCP traces, reports, and run "
    "artifacts remain complete"
)
MODEL_RACING_OBSERVABILITY_POLICY = (
    "records model-call arm lifecycle, winner/cancel fields, timing, provider/model ids, and "
    "usage availability only; raw prompts, model text, tool payload bodies, credentials, and "
    "private truth are not persisted"
)


def _bool_setting_value(raw: object) -> bool:
    if isinstance(raw, bool):
        return raw
    if (value := str(raw).strip().lower()) in {"1", "true", "yes", "on", "0", "false", "no", "off"}:
        return value in {"1", "true", "yes", "on"}
    raise ValueError(f"OpenAI Agents SDK boolean setting must be true or false, got {raw!r}")


def resolve_agent_sdk_perf_profile(args: argparse.Namespace) -> dict[str, Any]:
    provider_profile = _normal_provider_profile(str(getattr(args, "provider_profile", "") or ""))
    model = str(getattr(args, "model", "") or "")
    model_family = model_family_for_route_model(provider_profile, model or None)
    route = provider_route_spec(provider_profile)
    evidence_lane = _evidence_lane_for_args(args)
    profile_id, profile_source = _profile_id_with_source(args, provider_profile, model_family)
    defaults = _profile_defaults(
        profile_id,
        route=route,
        model_family=model_family,
        evidence_lane=evidence_lane,
    )
    payload = {
        "schema": "agent_sdk_perf_profile_v1",
        "profile_id": profile_id,
        "source": profile_source,
        "provider_profile": provider_profile,
        "wire_api": route.wire_api,
        "wire_source": route.wire_source,
        "route_status": route.status_for_engine("openai-agents-sdk"),
        "route_status_note": route.status_note,
        "route_capabilities": route_capabilities_for_engine(route, "openai-agents-sdk"),
        "model_family": model_family,
        "evidence_lane": evidence_lane,
        "context_policy": defaults["context_policy"],
        "model_thinking_mode": normalize_thinking_mode(
            getattr(args, "model_thinking_mode", "default"),
            default="default",
        ),
        "continuation_mode": _string_setting(
            args,
            "continuation_mode",
            CONTINUATION_MODE_ENV,
            default=defaults["continuation_mode"],
            allowed={"repeat_full_prompt", "state_summary_only"},
        ),
        "max_turns": _positive_int_setting(
            args,
            "max_turns",
            "ROBOCLAWS_OPENAI_AGENTS_MAX_TURNS",
            default=defaults["max_turns"],
        ),
        "max_continuations": _int_setting(
            args,
            "incomplete_turn_continuation_attempts",
            "ROBOCLAWS_OPENAI_AGENTS_INCOMPLETE_TURN_CONTINUATION_ATTEMPTS",
            default=defaults["max_continuations"],
        ),
        "cache_tools_list": _bool_arg_setting(
            args,
            "cache_tools_list",
            "ROBOCLAWS_OPENAI_AGENTS_CACHE_TOOLS_LIST",
            default=defaults["cache_tools_list"],
        ),
        "mcp_client_session_timeout_s": _float_setting(
            args,
            "mcp_client_session_timeout_s",
            MCP_CLIENT_SESSION_TIMEOUT_ENV,
            default=DEFAULT_MCP_CLIENT_SESSION_TIMEOUT_S,
        ),
        "raw_fpv_candidate_budget": _int_setting(
            args,
            "raw_fpv_candidate_budget",
            RAW_FPV_CANDIDATE_BUDGET_ENV,
            default=defaults["raw_fpv_candidate_budget"],
            allow_none=True,
        ),
        "raw_fpv_repeated_failure_limit": _int_setting(
            args,
            "raw_fpv_repeated_failure_limit",
            RAW_FPV_REPEATED_FAILURE_LIMIT_ENV,
            default=defaults["raw_fpv_repeated_failure_limit"],
            allow_none=True,
        ),
        "done_retry_budget": _int_setting(
            args,
            "done_retry_budget",
            DONE_RETRY_BUDGET_ENV,
            default=defaults["done_retry_budget"],
            allow_none=True,
        ),
        "max_observe_per_waypoint": _int_setting(
            args,
            "max_observe_per_waypoint",
            MAX_OBSERVE_PER_WAYPOINT_ENV,
            default=defaults["max_observe_per_waypoint"],
            allow_none=True,
        ),
        "context_soft_limit_tokens": _int_setting(
            args,
            "context_soft_limit_tokens",
            CONTEXT_SOFT_LIMIT_ENV,
            default=defaults["context_soft_limit_tokens"],
            allow_none=True,
        ),
        "context_hard_limit_tokens": _int_setting(
            args,
            "context_hard_limit_tokens",
            CONTEXT_HARD_LIMIT_ENV,
            default=defaults["context_hard_limit_tokens"],
            allow_none=True,
        ),
        "model_input_compaction": _model_input_compaction_profile(args, defaults),
        "camera_grounded_composite_tools": _camera_grounded_composite_tools_profile(
            args,
            defaults,
        ),
        "robot_view_capture_policy": _robot_view_capture_policy_profile(args, defaults),
        "model_racing_observability": _model_racing_observability_profile(args, defaults),
        "model_service_retry_attempts": _int_setting(
            args,
            "model_service_retry_attempts",
            retry_model.MODEL_SERVICE_RETRY_ATTEMPTS_ENV,
            default=retry_model.DEFAULT_MODEL_SERVICE_RETRY_ATTEMPTS,
        ),
        "model_service_retry_sleep_s": _float_setting(
            args,
            "model_service_retry_sleep_s",
            retry_model.MODEL_SERVICE_RETRY_SLEEP_ENV,
            default=retry_model.DEFAULT_MODEL_SERVICE_RETRY_SLEEP_S,
        ),
    }
    payload["sdk_model_settings"] = _sdk_model_settings_for_profile(payload)
    payload["sdk_run_config"] = _sdk_run_config_for_profile(payload)
    _validate_context_limits(payload)
    return payload


def _profile_id_with_source(
    args: argparse.Namespace,
    provider_profile: str,
    model_family: str,
) -> tuple[str, str]:
    cli_value = str(getattr(args, "agent_sdk_perf_profile", "") or "").strip()
    env_value = os.environ.get(AGENT_SDK_PERF_PROFILE_ENV, "").strip()
    if cli_value:
        profile_id = _validate_profile_id(cli_value)
        if env_value:
            env_profile_id = _validate_profile_id(env_value)
            if env_profile_id != profile_id:
                raise ValueError(
                    "conflicting OpenAI Agents SDK performance profile: "
                    f"--agent-sdk-perf-profile={profile_id!r} and "
                    f"{AGENT_SDK_PERF_PROFILE_ENV}={env_profile_id!r}"
                )
            return profile_id, "cli+environment"
        return profile_id, "cli"
    if env_value:
        return _validate_profile_id(env_value), "environment"
    return AGENT_SDK_PERF_PROFILE_CONTEXT_MANAGED_V1, "default"


def _validate_profile_id(value: str) -> str:
    profile_id = value.strip()
    if profile_id not in {
        AGENT_SDK_PERF_PROFILE_BASELINE,
        AGENT_SDK_PERF_PROFILE_CONTEXT_MANAGED_V1,
    }:
        supported = ", ".join(
            (AGENT_SDK_PERF_PROFILE_CONTEXT_MANAGED_V1, AGENT_SDK_PERF_PROFILE_BASELINE)
        )
        raise ValueError(
            f"unsupported OpenAI Agents SDK performance profile {value!r}; "
            f"supported values: {supported}"
        )
    return profile_id


def _profile_defaults(
    profile_id: str,
    *,
    route: Any,
    model_family: str,
    evidence_lane: str,
) -> dict[str, Any]:
    baseline = {
        "context_policy": _context_policy(
            source_level_tool_output_reduction=False,
            deterministic_model_input_compaction=False,
        ),
        "continuation_mode": "repeat_full_prompt",
        "max_turns": DEFAULT_OPENAI_AGENTS_MAX_TURNS,
        "max_continuations": DEFAULT_INCOMPLETE_TURN_CONTINUATION_ATTEMPTS,
        "cache_tools_list": True,
        "raw_fpv_candidate_budget": None,
        "raw_fpv_repeated_failure_limit": None,
        "done_retry_budget": None,
        "max_observe_per_waypoint": None,
        "context_soft_limit_tokens": None,
        "context_hard_limit_tokens": None,
        "model_input_compaction": {
            "schema": "agent_sdk_model_input_compaction_v1",
            "enabled": False,
            "mode": "off",
            "min_chars": 1200,
            "completed_tool_history_limit": 0,
            "raw_fpv_image_memory": {
                "schema": "agent_sdk_raw_fpv_image_memory_policy_v1",
                "enabled": False,
                "mode": "off",
                "retained_full_frame_limit": 0,
                "candidate_ids": [],
                "private_artifact_policy": RAW_FPV_IMAGE_MEMORY_POLICY,
            },
            "camera_grounded_history": {
                "schema": "agent_sdk_camera_grounded_history_policy_v1",
                "enabled": False,
                "mode": "off",
                "retained_recent_outputs": 0,
                "candidate_ids": [],
                "private_artifact_policy": CAMERA_GROUNDED_HISTORY_POLICY,
            },
        },
        "camera_grounded_composite_tools": {
            "schema": "agent_sdk_camera_grounded_composite_tools_v1",
            "enabled": False,
            "tool_names": [],
            "candidate_ids": ["O"],
            "private_artifact_policy": (
                "SDK-private MCP tool addition only; default public MCP/profile tools remain "
                "unchanged"
            ),
        },
        "robot_view_capture_policy": {
            "schema": "agent_sdk_robot_view_capture_policy_v1",
            "policy": ROBOT_VIEW_CAPTURE_POLICY_FULL,
            "candidate_ids": [],
            "scope": "report-only robot-view capture",
            "private_artifact_policy": (
                "full report robot-view capture; default public route behavior unchanged"
            ),
        },
        "model_racing_observability": {
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
            "private_artifact_policy": MODEL_RACING_OBSERVABILITY_POLICY,
        },
    }
    if profile_id == AGENT_SDK_PERF_PROFILE_BASELINE:
        return baseline
    if profile_id == AGENT_SDK_PERF_PROFILE_CONTEXT_MANAGED_V1:
        soft_limit, hard_limit = _provider_context_limits(route=route, model_family=model_family)
        raw_fpv_enabled = _raw_fpv_context_management_enabled(
            route=route,
            evidence_lane=evidence_lane,
        )
        return {
            **baseline,
            "context_policy": _context_policy(
                source_level_tool_output_reduction=True,
                deterministic_model_input_compaction=True,
            ),
            "continuation_mode": "state_summary_only",
            "max_continuations": 2 if raw_fpv_enabled else 1,
            "done_retry_budget": 1,
            "max_observe_per_waypoint": 4 if raw_fpv_enabled else 1,
            "context_soft_limit_tokens": soft_limit,
            "context_hard_limit_tokens": hard_limit,
            "raw_fpv_candidate_budget": 24 if raw_fpv_enabled else None,
            "raw_fpv_repeated_failure_limit": 3 if raw_fpv_enabled else None,
            "model_input_compaction": {
                "schema": "agent_sdk_model_input_compaction_v1",
                "enabled": True,
                "mode": (
                    "public_tool_result_summary_v1+repeated_metric_map_delta_v1+"
                    "camera_grounded_history_v1"
                    + ("+raw_fpv_image_memory_v1" if raw_fpv_enabled else "")
                ),
                "min_chars": 1200,
                "completed_tool_history_limit": 24 if raw_fpv_enabled else 0,
                "raw_fpv_image_memory": {
                    "schema": "agent_sdk_raw_fpv_image_memory_policy_v1",
                    "enabled": raw_fpv_enabled,
                    "mode": "retain_latest_full_frame" if raw_fpv_enabled else "off",
                    "retained_full_frame_limit": 1 if raw_fpv_enabled else 0,
                    "candidate_ids": ["AA"] if raw_fpv_enabled else [],
                    "private_artifact_policy": RAW_FPV_IMAGE_MEMORY_POLICY,
                },
                "camera_grounded_history": {
                    "schema": "agent_sdk_camera_grounded_history_policy_v1",
                    "enabled": True,
                    "mode": "retain_latest_actionable_outputs",
                    "retained_recent_outputs": 4,
                    "candidate_ids": ["AC"],
                    "private_artifact_policy": CAMERA_GROUNDED_HISTORY_POLICY,
                },
            },
            "camera_grounded_composite_tools": {
                "schema": "agent_sdk_camera_grounded_composite_tools_v1",
                "enabled": True,
                "tool_names": ["observe_camera_grounded_candidates"],
                "candidate_ids": ["O"],
                "private_artifact_policy": (
                    "SDK-private MCP tool addition only; default public MCP/profile tools remain "
                    "unchanged"
                ),
            },
        }
    raise ValueError(f"unsupported OpenAI Agents SDK performance profile '{profile_id}'")


def _context_policy(
    *,
    source_level_tool_output_reduction: bool,
    deterministic_model_input_compaction: bool,
) -> dict[str, Any]:
    return {
        "schema": "agent_sdk_context_policy_v1",
        "source_level_tool_output_reduction": source_level_tool_output_reduction,
        "deterministic_model_input_compaction": deterministic_model_input_compaction,
        "provider_native_compaction": {
            "mode": "off",
            "threshold_tokens": None,
            "provider_capability": "",
            "proof_artifact": "",
        },
    }


def _provider_context_limits(*, route: Any, model_family: str) -> tuple[int, int]:
    if route.wire_api == WIRE_RESPONSES and model_family == "gpt":
        return 96_000, 128_000
    return 64_000, 96_000


def _raw_fpv_context_management_enabled(*, route: Any, evidence_lane: str) -> bool:
    if evidence_lane != "camera-raw-fpv":
        return False
    return (
        route.route_capability("image_transport", agent_engine="openai-agents-sdk")
        == ROUTE_CAP_SUPPORTED
    )


def _evidence_lane_for_args(args: argparse.Namespace) -> str:
    for attr in ("evidence_lane", "profile"):
        value = str(getattr(args, attr, "") or "").strip()
        if value:
            return value
    return ""


def _model_input_compaction_profile(
    args: argparse.Namespace,
    defaults: dict[str, Any],
) -> dict[str, Any]:
    default_config = (
        defaults.get("model_input_compaction")
        if isinstance(defaults.get("model_input_compaction"), dict)
        else {}
    )
    default_enabled = bool(default_config.get("enabled", False))
    enabled = _bool_arg_setting(
        args,
        "model_input_compaction",
        MODEL_INPUT_COMPACTION_ENV,
        default=default_enabled,
    )
    min_chars = _positive_int_setting(
        args,
        "model_input_compaction_min_chars",
        MODEL_INPUT_COMPACTION_MIN_CHARS_ENV,
        default=int(default_config.get("min_chars") or 1200),
    )
    raw_fpv_image_memory = _raw_fpv_image_memory_profile(args, default_config)
    camera_grounded_history = _camera_grounded_history_profile(args, default_config)
    completed_tool_history_limit = int(default_config.get("completed_tool_history_limit") or 0)
    mode_parts = []
    candidate_ids = []
    if enabled:
        mode_parts.extend(["public_tool_result_summary_v1", "repeated_metric_map_delta_v1"])
        candidate_ids.extend(["I", "N"])
    if raw_fpv_image_memory["enabled"]:
        mode_parts.append("raw_fpv_image_memory_v1")
        candidate_ids.append("AA")
    if camera_grounded_history["enabled"]:
        mode_parts.append("camera_grounded_history_v1")
        candidate_ids.append("AC")
    if completed_tool_history_limit > 0:
        mode_parts.append("completed_tool_history_window_v1")
        candidate_ids.append("AH")
    hook_enabled = (
        enabled
        or bool(raw_fpv_image_memory["enabled"])
        or bool(camera_grounded_history["enabled"])
        or completed_tool_history_limit > 0
    )
    return {
        "schema": "agent_sdk_model_input_compaction_v1",
        "enabled": hook_enabled,
        "mode": "+".join(mode_parts) if mode_parts else "off",
        "min_chars": min_chars,
        "completed_tool_history_limit": completed_tool_history_limit,
        "candidate_ids": candidate_ids,
        "hook": "RunConfig.call_model_input_filter",
        "repeated_metric_map_delta": enabled,
        "raw_fpv_image_memory": raw_fpv_image_memory,
        "camera_grounded_history": camera_grounded_history,
        "private_artifact_policy": (
            "model-facing compaction only; MCP traces, reports, and run artifacts remain complete"
        ),
    }


def _model_racing_observability_profile(
    args: argparse.Namespace,
    defaults: dict[str, Any],
) -> dict[str, Any]:
    config = (
        defaults.get("model_racing_observability")
        if isinstance(defaults.get("model_racing_observability"), dict)
        else {}
    )
    enabled = _bool_arg_setting(
        args,
        "model_racing",
        MODEL_RACING_ENV,
        default=bool(config.get("enabled", False)),
    )
    default_arm_count = int(config.get("arm_count") or 1)
    if enabled and default_arm_count < 2:
        default_arm_count = 2
    arm_count = _int_setting(
        args,
        "model_racing_arm_count",
        MODEL_RACING_ARM_COUNT_ENV,
        default=default_arm_count,
    )
    if not enabled:
        arm_count = 1
    else:
        if arm_count is None or int(arm_count) < 1:
            _raise_enabled_count_error("model_racing_arm_count", "model_racing")
        arm_count = max(2, arm_count)
    candidate_ids = (
        ["D", "C"] if enabled else [str(item) for item in config.get("candidate_ids", ["D"])]
    )
    return {
        "schema": "agent_sdk_model_racing_observability_v1",
        "enabled": enabled,
        "mode": (
            "get_response_racing_v1"
            if enabled
            else str(config.get("mode") or "per_arm_observability_v1")
        ),
        "candidate_ids": candidate_ids,
        "arm_count": arm_count,
        "racing_multiplier": float(
            arm_count if enabled else config.get("racing_multiplier") or 1.0
        ),
        "winner_selection": (
            "first_successful_sdk_response"
            if enabled
            else str(config.get("winner_selection") or "single_arm_no_racing")
        ),
        "loser_cancellation": str(
            "cancel_pending_losers"
            if enabled
            else config.get("loser_cancellation") or "not_applicable_until_racing_enabled"
        ),
        "unknown_loser_billing": True
        if enabled
        else bool(config.get("unknown_loser_billing", False)),
        "hook": str(config.get("hook") or "OpenAI Agents SDK model request boundary"),
        "private_artifact_policy": MODEL_RACING_OBSERVABILITY_POLICY,
    }


def _raw_fpv_image_memory_profile(
    args: argparse.Namespace,
    default_config: dict[str, Any],
) -> dict[str, Any]:
    default_policy = (
        default_config.get("raw_fpv_image_memory")
        if isinstance(default_config.get("raw_fpv_image_memory"), dict)
        else {}
    )
    default_enabled = bool(default_policy.get("enabled", False))
    enabled = _bool_arg_setting(
        args,
        "raw_fpv_image_memory",
        RAW_FPV_IMAGE_MEMORY_ENV,
        default=default_enabled,
    )
    retain = _int_setting(
        args,
        "raw_fpv_image_memory_retain",
        RAW_FPV_IMAGE_MEMORY_RETAIN_ENV,
        default=int(default_policy.get("retained_full_frame_limit") or (1 if enabled else 0)),
    )
    if enabled:
        if retain is None or int(retain) < 1:
            _raise_enabled_count_error("raw_fpv_image_memory_retain", "raw_fpv_image_memory")
    else:
        retain = 0
    return {
        "schema": "agent_sdk_raw_fpv_image_memory_policy_v1",
        "enabled": enabled,
        "mode": "retain_latest_full_frame" if enabled else "off",
        "retained_full_frame_limit": retain,
        "candidate_ids": ["AA"] if enabled else [],
        "private_artifact_policy": RAW_FPV_IMAGE_MEMORY_POLICY,
    }


def _camera_grounded_history_profile(
    args: argparse.Namespace,
    default_config: dict[str, Any],
) -> dict[str, Any]:
    default_policy = (
        default_config.get("camera_grounded_history")
        if isinstance(default_config.get("camera_grounded_history"), dict)
        else {}
    )
    default_enabled = bool(default_policy.get("enabled", False))
    enabled = _bool_arg_setting(
        args,
        "camera_grounded_history_compaction",
        CAMERA_GROUNDED_HISTORY_COMPACTION_ENV,
        default=default_enabled,
    )
    retain = _int_setting(
        args,
        "camera_grounded_history_retain",
        CAMERA_GROUNDED_HISTORY_RETAIN_ENV,
        default=int(default_policy.get("retained_recent_outputs") or (4 if enabled else 0)),
    )
    if enabled:
        if retain is None or int(retain) < 1:
            _raise_enabled_count_error(
                "camera_grounded_history_retain", "camera_grounded_history_compaction"
            )
    else:
        retain = 0
    return {
        "schema": "agent_sdk_camera_grounded_history_policy_v1",
        "enabled": enabled,
        "mode": "retain_latest_actionable_outputs" if enabled else "off",
        "retained_recent_outputs": retain,
        "candidate_ids": ["AC"] if enabled else [],
        "private_artifact_policy": CAMERA_GROUNDED_HISTORY_POLICY,
    }


def _camera_grounded_composite_tools_profile(
    args: argparse.Namespace,
    defaults: dict[str, Any],
) -> dict[str, Any]:
    default_config = (
        defaults.get("camera_grounded_composite_tools")
        if isinstance(defaults.get("camera_grounded_composite_tools"), dict)
        else {}
    )
    default_enabled = bool(default_config.get("enabled", False))
    enabled = _bool_arg_setting(
        args,
        "camera_grounded_composite_tools",
        CAMERA_GROUNDED_COMPOSITE_TOOLS_ENV,
        default=default_enabled,
    )
    return {
        "schema": "agent_sdk_camera_grounded_composite_tools_v1",
        "enabled": enabled,
        "tool_names": ["observe_camera_grounded_candidates"] if enabled else [],
        "candidate_ids": ["O"],
        "scope": "camera-grounded-labels only",
        "hook": "cleanup MCP server private extra tool",
        "private_artifact_policy": (
            "SDK-private MCP tool addition only; default public MCP/profile tools remain unchanged"
        ),
    }


def camera_grounded_composite_tools_enabled_for_run(
    profile: dict[str, Any],
    *,
    evidence_lane: str,
) -> bool:
    config = profile.get("camera_grounded_composite_tools")
    if not isinstance(config, dict) or not config.get("enabled"):
        return False
    return evidence_lane == "camera-grounded-labels"


def _normal_provider_profile(provider_profile: str) -> str:
    return normalize_provider_route(provider_profile)
