"""Run and provider configuration for the OpenAI Agents runtime."""

from __future__ import annotations

import math
import os
from pathlib import Path
from typing import Any

from roboclaws.agents import provider_transport as pt
from roboclaws.agents.drivers.openai_agents_compaction import (
    _model_input_compaction_filter,
)
from roboclaws.agents.drivers.openai_agents_event_log import _write_json
from roboclaws.agents.drivers.openai_agents_event_projection import _drop_empty, _to_jsonable
from roboclaws.agents.drivers.openai_agents_input_config import _input_compaction_config
from roboclaws.agents.drivers.openai_agents_retry_model import _model_service_retry_config
from roboclaws.agents.live_runtime import LiveAgentRequest
from roboclaws.agents.provider_registry import openai_agents_runtime_settings
from roboclaws.agents.skill_delivery import render_instructions
from roboclaws.agents.thinking_policy import apply_model_thinking_policy
from roboclaws.core.provider_catalog import PROVIDER_PROFILE_KIMI_OPENAI_CHAT, WIRE_CHAT_COMPLETIONS

DEFAULT_OPENAI_AGENTS_MAX_TURNS = 128
MCP_CLIENT_SESSION_TIMEOUT_ENV = "ROBOCLAWS_OPENAI_AGENTS_MCP_CLIENT_SESSION_TIMEOUT_S"
KIMI_CODING_USER_AGENT = "claude-code/1.0.0"
MODEL_RACING_OBSERVABILITY_SCHEMA = "agent_sdk_model_racing_observability_v1"


def _instructions_with_skill_context(request: LiveAgentRequest) -> tuple[Any, dict[str, Any]]:
    context = request.metadata.get("skill_context") if isinstance(request.metadata, dict) else None
    if not isinstance(context, dict):
        return None, _skill_context_summary(
            {
                "skill_name": request.skill_name,
                "included": False,
                "reason": "not_configured",
            }
        )
    content = str(context.get("content") or "")
    summary = _skill_context_summary(
        {
            "skill_name": context.get("skill_name") or request.skill_name,
            "included": bool(content),
            "reason": context.get("reason") or ("included" if content else "empty"),
            "source_path": context.get("source_path"),
            "relative_path": context.get("relative_path"),
            "sha256": context.get("sha256"),
            "bytes": context.get("bytes"),
            "estimated_tokens": context.get("estimated_tokens"),
            "policy": context.get("policy"),
        }
    )
    if not content:
        return None, summary
    delivery = context.get("delivery")
    instructions = delivery.instructions() if delivery is not None else render_instructions(content)
    return instructions, summary


def _skill_context_summary(payload: dict[str, Any]) -> dict[str, Any]:
    return _drop_empty(_to_jsonable(payload))


def _write_skill_context_summary(
    path: Path,
    summary: dict[str, Any],
    *,
    request: LiveAgentRequest | None = None,
) -> None:
    payload: dict[str, Any] = {
        "schema": "openai_agents_skill_context_v1",
        **summary,
    }
    if request is not None:
        context = request.metadata.get("skill_context")
        delivery = context.get("delivery") if isinstance(context, dict) else None
        if isinstance(context, dict):
            payload.update(
                _skill_context_summary(
                    {
                        key: context.get(key)
                        for key in (
                            "skill_name",
                            "included",
                            "reason",
                            "source_path",
                            "relative_path",
                            "sha256",
                            "bytes",
                            "estimated_tokens",
                            "policy",
                        )
                    }
                )
            )
        if delivery is not None:
            delivery_payload = delivery.artifact(
                tool_surface=tuple(request.metadata.get("model_visible_tool_surface") or ())
            )
            delivery_payload.pop("schema", None)
            payload.update(delivery_payload)
    _write_json(path, _drop_empty(payload))


def _sdk_model_settings_payload(request: LiveAgentRequest) -> dict[str, Any]:
    metadata = dict(request.metadata)
    profile = metadata.get("agent_sdk_perf_profile")
    configured = profile.get("sdk_model_settings") if isinstance(profile, dict) else None
    if not isinstance(configured, dict):
        configured = metadata.get("sdk_model_settings")
    settings = _safe_model_settings(request)
    provider_profile = str(settings.get("provider_profile") or request.provider_profile or "")
    wire_api = str(settings.get("wire_api") or "")
    if isinstance(configured, dict):
        payload = _drop_empty(_to_jsonable(configured))
        thinking_mode = str(
            payload.pop("model_thinking_mode", None)
            or metadata.get("model_thinking_mode")
            or "default"
        )
        return _apply_provider_default_model_settings(
            apply_model_thinking_policy(
                payload,
                provider_profile=provider_profile,
                wire_api=wire_api,
                mode=thinking_mode,
            ),
            provider_profile=provider_profile,
            wire_api=wire_api,
        )
    profile_id = str(profile.get("profile_id") if isinstance(profile, dict) else "baseline")
    thinking_mode = str(metadata.get("model_thinking_mode") or "default")
    return _apply_provider_default_model_settings(
        _default_sdk_model_settings_payload(
            provider_profile=provider_profile,
            wire_api=wire_api,
            profile_id=profile_id,
            thinking_mode=thinking_mode,
        ),
        provider_profile=provider_profile,
        wire_api=wire_api,
    )


def _apply_provider_default_model_settings(
    payload: dict[str, Any],
    *,
    provider_profile: str,
    wire_api: str,
) -> dict[str, Any]:
    if provider_profile == PROVIDER_PROFILE_KIMI_OPENAI_CHAT and wire_api == WIRE_CHAT_COMPLETIONS:
        headers = dict(payload.get("extra_headers") or {})
        headers.setdefault("User-Agent", KIMI_CODING_USER_AGENT)
        payload["extra_headers"] = headers
    return pt.compatible_model_settings(provider_profile, payload)


def _sdk_run_config_payload(
    request: LiveAgentRequest,
    *,
    events_path: Path | None = None,
) -> dict[str, Any]:
    metadata = dict(request.metadata)
    profile = metadata.get("agent_sdk_perf_profile")
    configured = profile.get("sdk_run_config") if isinstance(profile, dict) else None
    if not isinstance(configured, dict):
        configured = metadata.get("sdk_run_config")
    allowed = {"trace_include_sensitive_data", "workflow_name", "trace_metadata"}
    if not isinstance(configured, dict):
        configured = _default_sdk_run_config_payload()
    payload = {
        key: value for key, value in _drop_empty(_to_jsonable(configured)).items() if key in allowed
    }
    filter_config = _input_compaction_config(request)
    budget_profile = profile if isinstance(profile, dict) else {}
    if (
        filter_config.get("enabled") or _model_input_budget_guard_configured(budget_profile)
    ) and events_path is not None:
        payload["call_model_input_filter"] = _model_input_compaction_filter(
            events_path,
            run_dir=request.run_dir,
            runtime_config=_runtime_config(
                request,
                mcp_client_session_timeout_configured=_mcp_client_session_timeout_seconds(request)[
                    0
                ],
                mcp_client_session_timeout_s=_mcp_client_session_timeout_seconds(request)[1],
            ),
            config=filter_config,
            budget_profile=budget_profile,
            budget_timing={
                "evidence_lane": metadata.get("evidence_lane") or metadata.get("profile") or "",
                "profile": metadata.get("profile") or "",
            },
        )
    return payload


def _default_sdk_model_settings_payload(
    *,
    provider_profile: str,
    wire_api: str,
    profile_id: str,
    thinking_mode: str = "default",
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "tool_choice": "auto",
        "parallel_tool_calls": False,
    }
    if wire_api == "chat-completions":
        payload["include_usage"] = True
        if provider_profile == PROVIDER_PROFILE_KIMI_OPENAI_CHAT:
            payload["extra_headers"] = {"User-Agent": KIMI_CODING_USER_AGENT}
    else:
        payload["store"] = False
        payload["truncation"] = "auto"
    return apply_model_thinking_policy(
        payload,
        provider_profile=provider_profile,
        wire_api=wire_api,
        mode=thinking_mode,
    )


def _default_sdk_run_config_payload() -> dict[str, Any]:
    return {
        "trace_include_sensitive_data": False,
        "workflow_name": "roboclaws-openai-agents-live",
    }


def _model_input_budget_guard_configured(profile: dict[str, Any]) -> bool:
    return any(
        profile.get(key) is not None
        for key in (
            "context_hard_limit_tokens",
            "max_observe_per_waypoint",
            "raw_fpv_candidate_budget",
            "raw_fpv_repeated_failure_limit",
        )
    )


def _bool_setting(
    value: Any,
    setting_name: str,
    *,
    default: bool,
    empty_uses_default: bool = True,
) -> bool:
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    if value == "" and empty_uses_default:
        return default
    true_values = {"1", "true", "yes", "on"}
    false_values = {"0", "false", "no", "off"}
    if (normalized := str(value).strip().lower()) in true_values | false_values:
        return normalized in true_values
    raise ValueError(
        f"OpenAI Agents SDK setting {setting_name} must be true or false, got {value!r}"
    )


def _positive_int(value: Any, setting_name: str, *, default: int) -> int:
    if value is None or value == "":
        return default
    if isinstance(value, bool):
        raise ValueError(
            f"OpenAI Agents SDK setting {setting_name} must be a positive integer, got {value!r}"
        )
    try:
        parsed = int(value)
    except (OverflowError, TypeError, ValueError) as exc:
        raise ValueError(
            f"OpenAI Agents SDK setting {setting_name} must be a positive integer, got {value!r}"
        ) from exc
    if parsed < 1:
        raise ValueError(
            f"OpenAI Agents SDK setting {setting_name} must be a positive integer, got {value!r}"
        )
    return parsed


def _positive_float(value: Any, setting_name: str, *, default: float) -> float:
    if value is None or value == "":
        return default
    if isinstance(value, bool):
        raise ValueError(
            f"OpenAI Agents SDK setting {setting_name} must be a positive finite number, "
            f"got {value!r}"
        )
    try:
        parsed = float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(
            f"OpenAI Agents SDK setting {setting_name} must be a positive finite number, "
            f"got {value!r}"
        ) from exc
    if not math.isfinite(parsed) or parsed <= 0:
        raise ValueError(
            f"OpenAI Agents SDK setting {setting_name} must be a positive finite number, "
            f"got {value!r}"
        )
    return parsed


def _max_turns(request: LiveAgentRequest) -> int:
    if request.max_turns is not None:
        return request.max_turns
    configured = request.metadata.get("max_turns") if isinstance(request.metadata, dict) else None
    if configured is None:
        return DEFAULT_OPENAI_AGENTS_MAX_TURNS
    return _positive_int(configured, "max_turns", default=DEFAULT_OPENAI_AGENTS_MAX_TURNS)


def _cache_tools_list(request: LiveAgentRequest) -> bool:
    source = "cache_tools_list"
    configured = request.metadata.get(source) if isinstance(request.metadata, dict) else None
    if configured is None:
        source = "ROBOCLAWS_OPENAI_AGENTS_CACHE_TOOLS_LIST"
        configured = os.environ.get("ROBOCLAWS_OPENAI_AGENTS_CACHE_TOOLS_LIST")
    return _bool_setting(configured, source, default=True, empty_uses_default=False)


def _mcp_client_session_timeout_seconds(request: LiveAgentRequest) -> tuple[bool, float | None]:
    configured = None
    if isinstance(request.metadata, dict):
        configured = request.metadata.get("mcp_client_session_timeout_s")
    if configured is None:
        raw_env = os.environ.get(MCP_CLIENT_SESSION_TIMEOUT_ENV)
        if raw_env is None or str(raw_env).strip() == "":
            return False, None
        value = _non_negative_float(
            None,
            setting_name="mcp_client_session_timeout_s",
            env_name=MCP_CLIENT_SESSION_TIMEOUT_ENV,
            default=0.0,
        )
        return (True, None) if value == 0 else (True, round(value, 3))
    if configured is None or str(configured).strip() == "":
        return False, None
    value = _non_negative_float(
        configured,
        setting_name="mcp_client_session_timeout_s",
        env_name=MCP_CLIENT_SESSION_TIMEOUT_ENV,
        default=0.0,
    )
    if value == 0:
        return True, None
    return True, round(value, 3)


def _runtime_config(
    request: LiveAgentRequest,
    *,
    mcp_client_session_timeout_configured: bool,
    mcp_client_session_timeout_s: float | None,
) -> dict[str, Any]:
    model_retry = _model_service_retry_config(request)
    model_settings = _safe_model_settings(request)
    sdk_model_settings = _sdk_model_settings_payload(request)
    sdk_run_config = _sdk_run_config_payload(request, events_path=None)
    input_compaction = _input_compaction_config(request)
    racing_observability = _model_racing_observability_config(request)
    responses_feature_surface = _responses_feature_surface(model_settings)
    return {
        "runtime": "openai-agents-live",
        "provider_profile": model_settings.get("provider_profile") or request.provider_profile,
        "model": model_settings.get("model") or request.model,
        "wire_api": model_settings.get("wire_api") or "",
        "max_turns": _max_turns(request),
        "cache_tools_list": _cache_tools_list(request),
        "mcp_server": {
            "name": request.mcp_server.name,
            "transport": request.mcp_server.transport,
            "url": request.mcp_server.url,
        },
        "mcp_client_session_timeout_configured": mcp_client_session_timeout_configured,
        "mcp_client_session_timeout_s": mcp_client_session_timeout_s,
        "model_service_retry_attempts": model_retry["retry_attempts"],
        "model_service_retry_sleep_s": model_retry["retry_sleep_s"],
        "sdk_model_settings": sdk_model_settings,
        "sdk_run_config": sdk_run_config,
        "agent_sdk_responses_features": responses_feature_surface,
        "model_input_compaction": input_compaction,
        "model_racing_observability": racing_observability,
        "prompt_cache_retention": sdk_model_settings.get("prompt_cache_retention") or "",
        "trace_include_sensitive_data": sdk_run_config.get("trace_include_sensitive_data"),
    }


def _responses_feature_surface(model_settings: dict[str, Any]) -> dict[str, Any]:
    wire_api = str(model_settings.get("wire_api") or "")
    enabled = wire_api == "responses"
    return {
        "schema": "agent_sdk_responses_feature_surface_v1",
        "wire_api": wire_api,
        "available": enabled,
        "previous_response_id": enabled,
        "auto_previous_response_id": enabled,
        "conversation_id": enabled,
        "session": enabled,
        "server_managed_continuation_default": False,
        "decision": (
            "available_but_gated_for_live_ab"
            if enabled
            else "unavailable_for_chat_completions_wire_api"
        ),
        "privacy_note": (
            "Responses continuation/session levers are recorded as capability surface only; "
            "they are not enabled by default because task state and report completeness must "
            "remain MCP-visible."
        ),
    }


def _model_racing_observability_config(request: LiveAgentRequest) -> dict[str, Any]:
    metadata = dict(request.metadata)
    profile = metadata.get("agent_sdk_perf_profile")
    config = profile.get("model_racing_observability") if isinstance(profile, dict) else None
    if not isinstance(config, dict):
        config = metadata.get("model_racing_observability")
    if not isinstance(config, dict):
        config = {}
    enabled = _bool_setting(
        config.get("enabled"), "model_racing_observability.enabled", default=False
    )
    arm_count = _positive_int(
        config.get("arm_count"), "model_racing_observability.arm_count", default=1
    )
    if not enabled:
        arm_count = 1
    else:
        arm_count = max(2, arm_count)
    configured_multiplier = _positive_float(
        config.get("racing_multiplier"),
        "model_racing_observability.racing_multiplier",
        default=float(arm_count),
    )
    racing_multiplier = max(float(arm_count), configured_multiplier) if enabled else 1.0
    racing_mode = str(
        config.get("mode") or ("get_response_racing_v1" if enabled else "per_arm_observability_v1")
    )
    candidate_ids = (
        config.get("candidate_ids") if isinstance(config.get("candidate_ids"), list) else []
    )
    return {
        "schema": MODEL_RACING_OBSERVABILITY_SCHEMA,
        "enabled": enabled,
        "mode": racing_mode,
        "candidate_ids": [str(item) for item in candidate_ids],
        "arm_count": arm_count,
        "racing_multiplier": racing_multiplier,
        "winner_selection": str(
            config.get("winner_selection")
            or ("first_successful_sdk_response" if enabled else "single_arm_no_racing")
        ),
        "loser_cancellation": str(
            config.get("loser_cancellation")
            or ("cancel_pending_losers" if enabled else "not_applicable_until_racing_enabled")
        ),
        "unknown_loser_billing": True
        if enabled
        else _bool_setting(
            config.get("unknown_loser_billing"),
            "model_racing_observability.unknown_loser_billing",
            default=False,
        ),
        "private_artifact_policy": (
            "records model-call arm lifecycle, winner/cancel fields, timing, provider/model ids, "
            "and usage availability only; raw prompts, model text, tool payload bodies, "
            "credentials, and private truth are not persisted"
        ),
    }


def _model_settings(request: LiveAgentRequest) -> dict[str, str]:
    metadata = dict(request.metadata)
    settings = openai_agents_runtime_settings(
        provider_profile=metadata.get("provider_profile"),
        request_provider_profile=request.provider_profile,
        model=metadata.get("model"),
        request_model=request.model,
        base_url=metadata.get("base_url"),
        api_key=metadata.get("api_key"),
    )
    if settings["base_url_env"]:
        _require_setting(
            settings["provider_profile"], settings["base_url_env"], settings["base_url"]
        )
    if settings["api_key_env"]:
        _require_setting(settings["provider_profile"], settings["api_key_env"], settings["api_key"])
    if settings["request_model_env"]:
        _require_setting(
            settings["provider_profile"],
            settings["request_model_env"],
            settings["request_model"],
        )
    return settings


def _require_setting(provider: str, name: str, value: str) -> None:
    if not value:
        raise RuntimeError(f"{provider} requires {name}")


def _non_negative_int(value: Any, *, setting_name: str, env_name: str, default: int) -> int:
    source = setting_name
    if value is None:
        raw_env = os.environ.get(env_name)
        if raw_env not in {None, ""}:
            value = raw_env
            source = env_name
        else:
            value = default
    if isinstance(value, bool):
        raise ValueError(
            f"OpenAI Agents SDK setting {setting_name} ({source}) must be a "
            f"non-negative integer, got {value!r}"
        )
    try:
        parsed = int(value)
    except (OverflowError, TypeError, ValueError) as exc:
        raise ValueError(
            f"OpenAI Agents SDK setting {setting_name} ({source}) must be a "
            f"non-negative integer, got {value!r}"
        ) from exc
    if parsed < 0:
        raise ValueError(
            f"OpenAI Agents SDK setting {setting_name} ({source}) must be a "
            f"non-negative integer, got {value!r}"
        )
    return parsed


def _non_negative_float(value: Any, *, setting_name: str, env_name: str, default: float) -> float:
    source = setting_name
    if value is None:
        raw_env = os.environ.get(env_name)
        if raw_env not in {None, ""}:
            value = raw_env
            source = env_name
        else:
            value = default
    if isinstance(value, bool):
        raise ValueError(
            f"OpenAI Agents SDK setting {setting_name} ({source}) must be a "
            f"finite non-negative number, got {value!r}"
        )
    try:
        parsed = float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(
            f"OpenAI Agents SDK setting {setting_name} ({source}) must be a "
            f"finite non-negative number, got {value!r}"
        ) from exc
    if not math.isfinite(parsed) or parsed < 0:
        raise ValueError(
            f"OpenAI Agents SDK setting {setting_name} ({source}) must be a "
            f"finite non-negative number, got {value!r}"
        )
    return parsed


def _safe_model_settings(request: LiveAgentRequest) -> dict[str, str]:
    try:
        return _model_settings(request)
    except Exception:
        return {}


def _model_settings(request: LiveAgentRequest) -> dict[str, str]:
    metadata = dict(request.metadata)
    settings = openai_agents_runtime_settings(
        provider_profile=metadata.get("provider_profile"),
        request_provider_profile=request.provider_profile,
        model=metadata.get("model"),
        request_model=request.model,
        base_url=metadata.get("base_url"),
        api_key=metadata.get("api_key"),
    )
    if settings["base_url_env"]:
        _require_setting(
            settings["provider_profile"], settings["base_url_env"], settings["base_url"]
        )
    if settings["api_key_env"]:
        _require_setting(settings["provider_profile"], settings["api_key_env"], settings["api_key"])
    if settings["request_model_env"]:
        _require_setting(
            settings["provider_profile"],
            settings["request_model_env"],
            settings["request_model"],
        )
    return settings


def _require_setting(provider: str, name: str, value: str) -> None:
    if not value:
        raise RuntimeError(f"{provider} requires {name}")
