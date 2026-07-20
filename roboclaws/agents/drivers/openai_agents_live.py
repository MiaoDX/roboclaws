"""Experimental OpenAI Agents SDK live-agent runtime."""

from __future__ import annotations

import asyncio
import json
import math
import os
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from roboclaws.agents.drivers.openai_agents_budget import OpenAIAgentsBudgetExceededError
from roboclaws.agents.drivers.openai_agents_model_input import (
    _input_compaction_config,
    _model_input_compaction_filter,
)
from roboclaws.agents.drivers.openai_agents_spans import (
    RoboclawsSpanRecorder,
    append_span_limitation,
)
from roboclaws.agents.live_runtime import LiveAgentRequest, LiveAgentResult, LiveAgentRuntime
from roboclaws.agents.live_status import LiveAgentFailure
from roboclaws.agents.provider_registry import (
    PROVIDER_PROFILE_CODEX_RESPONSES,
    PROVIDER_PROFILE_KIMI_OPENAI_CHAT,
    WIRE_CHAT_COMPLETIONS,
    openai_agents_runtime_settings,
)
from roboclaws.agents.provider_transport import provider_default_headers
from roboclaws.agents.thinking_policy import apply_model_thinking_policy

try:
    from agents.models.interface import Model as _AgentsModel  # type: ignore[import-not-found]
except ImportError:
    _AgentsModel = object

DEFAULT_OPENAI_AGENTS_MAX_TURNS = 128
MCP_CLIENT_SESSION_TIMEOUT_ENV = "ROBOCLAWS_OPENAI_AGENTS_MCP_CLIENT_SESSION_TIMEOUT_S"
DEFAULT_MODEL_SERVICE_RETRY_ATTEMPTS = 1
DEFAULT_MODEL_SERVICE_RETRY_SLEEP_S = 1.0
MODEL_SERVICE_RETRY_ATTEMPTS_ENV = "ROBOCLAWS_OPENAI_AGENTS_MODEL_SERVICE_RETRY_ATTEMPTS"
MODEL_SERVICE_RETRY_SLEEP_ENV = "ROBOCLAWS_OPENAI_AGENTS_MODEL_SERVICE_RETRY_SLEEP_S"
MODEL_RACING_OBSERVABILITY_SCHEMA = "agent_sdk_model_racing_observability_v1"
MODEL_RACING_EVENT_SCHEMA = "openai_agents_model_racing_observability_v1"
KIMI_CODING_USER_AGENT = "claude-code/1.0.0"


class OpenAIAgentsLiveRuntime(LiveAgentRuntime):
    """Run one Roboclaws live-agent turn through the OpenAI Agents SDK.

    This runtime is intentionally private/experimental. It does not claim Codex
    CLI equivalence and it does not infer cleanup completion; the MCP server's
    ``done`` path still owns ``run_result.json`` and checker eligibility.
    """

    runtime_name = "openai-agents-live"

    def run(self, request: LiveAgentRequest) -> LiveAgentResult:
        started_at = time.time()
        request.run_dir.mkdir(parents=True, exist_ok=True)
        events_path = request.artifact_path("openai_agents_events", "openai-agents-events.jsonl")
        trace_path = request.artifact_path("openai_agents_trace", "openai-agents-trace.json")
        spans_path = request.artifact_path("openai_agents_spans", "openai-agents-spans.jsonl")
        skill_context_path = request.artifact_path(
            "openai_agents_skill_context",
            "openai-agents-skill-context.json",
        )
        status_path = request.artifact_path("live_status", "live_status.json")

        try:
            result = _run_openai_agents(
                request,
                events_path=events_path,
                spans_path=spans_path,
                skill_context_path=skill_context_path,
            )
        except asyncio.CancelledError as exc:
            run_result_path = request.run_dir / "run_result.json"
            if run_result_path.is_file():
                result = None
            else:
                failure = LiveAgentFailure(
                    "agent_runtime_cancelled",
                    retryable=False,
                    detail=str(exc) or "OpenAI Agents SDK runtime was cancelled before done",
                )
                normalized = LiveAgentResult.from_failure(
                    phase="failed",
                    exit_status=1,
                    failure=failure,
                    started_at_epoch=started_at,
                    finished_at_epoch=time.time(),
                    artifact_paths={
                        "openai_agents_events": events_path,
                        "openai_agents_spans": spans_path,
                        "openai_agents_skill_context": skill_context_path,
                        "live_status": status_path,
                    },
                )
                _write_json(status_path, normalized.to_live_status_payload())
                return normalized
        except ImportError:
            failure = LiveAgentFailure(
                "provider_config_failure",
                retryable=False,
                detail=(
                    "OpenAI Agents SDK is not installed. Install it in a local experimental "
                    "environment before running openai-agents-live."
                ),
            )
            normalized = LiveAgentResult.from_failure(
                phase="failed",
                exit_status=1,
                failure=failure,
                started_at_epoch=started_at,
                finished_at_epoch=time.time(),
                artifact_paths={
                    "openai_agents_events": events_path,
                    "openai_agents_spans": spans_path,
                    "openai_agents_skill_context": skill_context_path,
                    "live_status": status_path,
                },
            )
            _write_json(status_path, normalized.to_live_status_payload())
            return normalized
        except Exception as exc:
            failure = _failure_from_exception(exc)
            normalized = LiveAgentResult.from_failure(
                phase="failed",
                exit_status=1,
                failure=failure,
                started_at_epoch=started_at,
                finished_at_epoch=time.time(),
                artifact_paths={
                    "openai_agents_events": events_path,
                    "openai_agents_spans": spans_path,
                    "openai_agents_skill_context": skill_context_path,
                    "live_status": status_path,
                },
            )
            _write_json(status_path, normalized.to_live_status_payload())
            return normalized

        finished_at = time.time()
        run_result_path = request.run_dir / "run_result.json"
        artifact_paths = {
            "openai_agents_events": events_path,
            "openai_agents_trace": trace_path,
            "openai_agents_spans": spans_path,
            "openai_agents_skill_context": skill_context_path,
            "live_status": status_path,
        }
        if run_result_path.exists():
            artifact_paths["run_result"] = run_result_path
        sdk_result = _summarize_sdk_result(result)
        _write_json(trace_path, sdk_result)
        normalized = LiveAgentResult(
            phase="finished" if run_result_path.exists() else "agent-turn-complete",
            exit_status=0,
            started_at_epoch=started_at,
            finished_at_epoch=finished_at,
            artifact_paths=artifact_paths,
            provider_session_id=str(sdk_result.get("session_id") or ""),
            trace_id=str(sdk_result.get("trace_id") or ""),
            run_result_present=run_result_path.exists(),
            usage=sdk_result.get("usage") if isinstance(sdk_result.get("usage"), dict) else {},
            timing={"runtime_wall_seconds": round(finished_at - started_at, 3)},
        )
        _write_json(status_path, normalized.to_live_status_payload())
        return normalized


def _run_openai_agents(
    request: LiveAgentRequest,
    *,
    events_path: Path,
    spans_path: Path,
    skill_context_path: Path,
) -> Any:
    try:
        from agents import Agent, ModelSettings, RunConfig, Runner  # type: ignore[import-not-found]
        from agents.mcp import MCPServerStreamableHttp  # type: ignore[import-not-found]
    except ImportError:
        raise
    try:
        from agents import add_trace_processor, flush_traces  # type: ignore[import-not-found]
    except ImportError:
        add_trace_processor = None
        flush_traces = None

    parts = _openai_agents_run_parts(
        request,
        agent_cls=Agent,
        model_settings_cls=ModelSettings,
        run_config_cls=RunConfig,
        mcp_server_cls=MCPServerStreamableHttp,
        events_path=events_path,
        skill_context_path=skill_context_path,
    )
    events_path.parent.mkdir(parents=True, exist_ok=True)
    events_path.write_text("", encoding="utf-8")
    spans_path.parent.mkdir(parents=True, exist_ok=True)
    spans_path.write_text("", encoding="utf-8")
    _append_event(
        events_path,
        {
            "event": "start",
            "ts_epoch": time.time(),
            **parts.runtime_config,
            "skill_context": parts.skill_context_summary,
        },
    )
    span_processor = RoboclawsSpanRecorder(spans_path, runtime_config=parts.runtime_config)
    if add_trace_processor is None:
        append_span_limitation(
            spans_path,
            runtime_config=parts.runtime_config,
            reason="sdk_trace_processor_api_unavailable",
        )
        span_processor = None
    else:
        try:
            add_trace_processor(span_processor)
        except Exception as exc:
            append_span_limitation(
                spans_path,
                runtime_config=parts.runtime_config,
                reason="sdk_trace_processor_registration_failed",
                exc=exc,
            )
            span_processor = None

    try:
        if hasattr(parts.server, "__aenter__"):
            return _run_with_async_mcp_server(
                parts.server,
                parts.agent,
                request,
                events_path,
                run_config=parts.run_config,
            )
        runner_kwargs: dict[str, Any] = {"max_turns": _max_turns(request)}
        runner_kwargs["run_config"] = parts.run_config
        result = Runner.run_sync(parts.agent, request.kickoff_prompt, **runner_kwargs)
        _append_event(
            events_path,
            {"event": "result", "ts_epoch": time.time(), "summary": _summarize_sdk_result(result)},
        )
        return result
    finally:
        if flush_traces is not None:
            try:
                flush_traces()
            except Exception as exc:
                _append_event(
                    events_path,
                    {
                        "event": "trace_flush_error",
                        "ts_epoch": time.time(),
                        "error_type": exc.__class__.__name__,
                        "message": str(exc),
                    },
                )
        if span_processor is not None:
            span_processor.force_flush()
            span_processor.shutdown()


@dataclass(frozen=True)
class _OpenAIAgentsRunParts:
    agent: Any
    server: Any
    run_config: Any
    runtime_config: dict[str, Any]
    skill_context_summary: dict[str, Any]


def _openai_agents_run_parts(
    request: LiveAgentRequest,
    *,
    agent_cls: Any,
    model_settings_cls: Any,
    run_config_cls: Any,
    mcp_server_cls: Any,
    events_path: Path,
    skill_context_path: Path,
) -> _OpenAIAgentsRunParts:
    timeout_configured, timeout_s = _mcp_client_session_timeout_seconds(request)
    runtime_config = _runtime_config(
        request,
        mcp_client_session_timeout_configured=timeout_configured,
        mcp_client_session_timeout_s=timeout_s,
    )
    model_settings = model_settings_cls(**_sdk_model_settings_payload(request))
    run_config = run_config_cls(
        model_settings=model_settings,
        **_sdk_run_config_payload(request, events_path=events_path),
    )
    server = mcp_server_cls(
        **_mcp_server_kwargs(
            request,
            timeout_configured=timeout_configured,
            timeout_s=timeout_s,
        )
    )
    instructions, skill_context_summary = _instructions_with_skill_context(request)
    _write_skill_context_summary(skill_context_path, skill_context_summary)
    agent = agent_cls(
        **_agent_kwargs(
            request,
            model=_model_for_request(request),
            model_settings=model_settings,
            server=server,
            instructions=instructions,
            events_path=events_path,
            runtime_config=runtime_config,
        )
    )
    return _OpenAIAgentsRunParts(
        agent=agent,
        server=server,
        run_config=run_config,
        runtime_config=runtime_config,
        skill_context_summary=skill_context_summary,
    )


def _mcp_server_kwargs(
    request: LiveAgentRequest,
    *,
    timeout_configured: bool,
    timeout_s: float,
) -> dict[str, Any]:
    server_kwargs: dict[str, Any] = {
        "name": request.mcp_server.name,
        "params": {"url": request.mcp_server.url},
        "cache_tools_list": _cache_tools_list(request),
    }
    if timeout_configured:
        server_kwargs["client_session_timeout_seconds"] = timeout_s
    return server_kwargs


def _agent_kwargs(
    request: LiveAgentRequest,
    *,
    model: Any,
    model_settings: Any,
    server: Any,
    instructions: str,
    events_path: Path,
    runtime_config: dict[str, Any],
) -> dict[str, Any]:
    return {
        "name": f"roboclaws-{request.run_id}",
        "instructions": instructions,
        "mcp_servers": [server],
        "mcp_config": {
            "failure_error_function": _recording_tool_error_function(
                events_path,
                runtime_config=runtime_config,
            )
        },
        "model": model,
        "model_settings": model_settings,
    }


def _run_with_async_mcp_server(
    server: Any,
    agent: Any,
    request: LiveAgentRequest,
    events_path: Path,
    *,
    run_config: Any,
) -> Any:
    import asyncio

    async def _run() -> Any:
        from agents import Runner  # type: ignore[import-not-found]

        async with server:
            runner_kwargs: dict[str, Any] = {
                "max_turns": _max_turns(request),
                "run_config": run_config,
            }
            result = await Runner.run(agent, request.kickoff_prompt, **runner_kwargs)
        _append_event(
            events_path,
            {"event": "result", "ts_epoch": time.time(), "summary": _summarize_sdk_result(result)},
        )
        return result

    return asyncio.run(_run())


def _instructions_with_skill_context(request: LiveAgentRequest) -> tuple[str, dict[str, Any]]:
    context = request.metadata.get("skill_context") if isinstance(request.metadata, dict) else None
    if not isinstance(context, dict):
        return request.kickoff_prompt, _skill_context_summary(
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
        return request.kickoff_prompt, summary
    instructions = (
        "Canonical skill context for this private OpenAI Agents SDK run:\n\n"
        f"{content.rstrip()}\n\n"
        "Run-specific kickoff instructions override any conflicting generic skill-context "
        "guidance for this run:\n\n"
        f"{request.kickoff_prompt}"
    )
    return instructions, summary


def _skill_context_summary(payload: dict[str, Any]) -> dict[str, Any]:
    return _drop_empty(_to_jsonable(payload))


def _write_skill_context_summary(path: Path, summary: dict[str, Any]) -> None:
    payload = {
        "schema": "openai_agents_skill_context_v1",
        **summary,
    }
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
    return payload


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
        if provider_profile != PROVIDER_PROFILE_CODEX_RESPONSES:
            payload["truncation"] = "auto"
        if provider_profile == PROVIDER_PROFILE_CODEX_RESPONSES and profile_id != "baseline":
            payload["prompt_cache_retention"] = "in_memory"
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


def _recording_tool_error_function(
    events_path: Path,
    *,
    runtime_config: dict[str, Any],
) -> Any:
    def _format_tool_error(_context: Any, error: Exception) -> str:
        message = str(error)
        _append_event(
            events_path,
            {
                "event": "tool_error",
                "ts_epoch": time.time(),
                "error_type": error.__class__.__name__,
                "classification": _classify_tool_error(message),
                "message": message,
                "mcp_client_session_timeout_s": runtime_config.get("mcp_client_session_timeout_s"),
            },
        )
        return f"An error occurred while running the tool. Please try again. Error: {message}"

    return _format_tool_error


def _classify_tool_error(message: str) -> str:
    lowered = message.lower()
    if "timed out while waiting for response to clientrequest" in lowered:
        return "mcp_client_request_timeout"
    if "connection timeout" in lowered or "timed out" in lowered or "timeout" in lowered:
        return "timeout"
    if "connection lost" in lowered or "connection reset" in lowered:
        return "connection_lost"
    return "tool_error"


def _summarize_sdk_result(result: Any) -> dict[str, Any]:
    payload: dict[str, Any] = {}
    final_output = getattr(result, "final_output", None)
    if final_output is not None:
        final_output_text = str(final_output)
        payload["final_output_present"] = True
        payload["final_output_chars"] = len(final_output_text)
        payload["message"] = (
            "OpenAI Agents SDK result captured; assistant output redacted by "
            "artifact privacy policy."
        )
    last_agent = getattr(result, "last_agent", None)
    if last_agent is not None:
        name = getattr(last_agent, "name", None)
        if name:
            payload["last_agent_name"] = str(name)
        payload["last_agent_class"] = last_agent.__class__.__name__
    trace_id = getattr(result, "trace_id", None)
    if trace_id is not None:
        payload["trace_id"] = str(trace_id)
    usage = getattr(result, "usage", None)
    if usage is not None:
        payload["usage"] = _to_jsonable(usage)
    session_id = getattr(result, "session_id", None)
    if session_id:
        payload["session_id"] = str(session_id)
    return payload


def _drop_empty(payload: dict[str, Any]) -> dict[str, Any]:
    return {key: value for key, value in payload.items() if not _is_empty_json_value(value)}


def _is_empty_json_value(value: Any) -> bool:
    if value is None:
        return True
    if isinstance(value, str) and value == "":
        return True
    if isinstance(value, (list, tuple, dict)) and not value:
        return True
    return False


def _model_for_request(request: LiveAgentRequest) -> Any:
    from openai import AsyncOpenAI  # type: ignore[import-not-found]

    settings = _model_settings(request)
    client_kwargs: dict[str, Any] = {
        "api_key": settings["api_key"],
        "base_url": settings["base_url"],
    }
    default_headers = provider_default_headers(
        settings["provider_profile"],
        session_seed=request.run_dir,
    )
    if default_headers:
        client_kwargs["default_headers"] = default_headers
    client = AsyncOpenAI(
        **client_kwargs,
    )
    if settings["wire_api"] == "responses":
        from agents import OpenAIResponsesModel  # type: ignore[import-not-found]

        base_model = OpenAIResponsesModel(settings["model"], openai_client=client)
    elif settings["wire_api"] == "chat-completions":
        from agents import OpenAIChatCompletionsModel  # type: ignore[import-not-found]

        base_model = OpenAIChatCompletionsModel(settings["model"], openai_client=client)
    else:  # pragma: no cover - guarded by _model_settings.
        raise RuntimeError(f"unsupported OpenAI Agents wire API: {settings['wire_api']}")
    retry_config = _model_service_retry_config(request)
    return _RetryingModel(
        base_model,
        retry_attempts=int(retry_config["retry_attempts"]),
        retry_sleep_s=float(retry_config["retry_sleep_s"]),
        events_path=request.artifact_path("openai_agents_events", "openai-agents-events.jsonl"),
        spans_path=request.artifact_path("openai_agents_spans", "openai-agents-spans.jsonl"),
        runtime_config=_runtime_config(
            request,
            mcp_client_session_timeout_configured=_mcp_client_session_timeout_seconds(request)[0],
            mcp_client_session_timeout_s=_mcp_client_session_timeout_seconds(request)[1],
        ),
    )


def _model_service_retry_config(request: LiveAgentRequest) -> dict[str, int | float]:
    metadata = dict(request.metadata)
    attempts = _non_negative_int(
        metadata.get("model_service_retry_attempts"),
        setting_name="model_service_retry_attempts",
        env_name=MODEL_SERVICE_RETRY_ATTEMPTS_ENV,
        default=DEFAULT_MODEL_SERVICE_RETRY_ATTEMPTS,
    )
    sleep_s = _non_negative_float(
        metadata.get("model_service_retry_sleep_s"),
        setting_name="model_service_retry_sleep_s",
        env_name=MODEL_SERVICE_RETRY_SLEEP_ENV,
        default=DEFAULT_MODEL_SERVICE_RETRY_SLEEP_S,
    )
    return {"retry_attempts": attempts, "retry_sleep_s": sleep_s}


def _safe_model_settings(request: LiveAgentRequest) -> dict[str, str]:
    try:
        return _model_settings(request)
    except Exception:
        return {}


@dataclass(frozen=True)
class _ModelRacingArmOutcome:
    arm_index: int
    arm_id: str
    elapsed_s: float
    result: Any = None
    exc: Exception | None = None


class _RetryingModel(_AgentsModel):
    """Retry transient provider failures at the SDK model request boundary."""

    def __init__(
        self,
        base_model: Any,
        *,
        retry_attempts: int,
        retry_sleep_s: float,
        events_path: Path,
        spans_path: Path,
        runtime_config: dict[str, Any],
    ) -> None:
        self.base_model = base_model
        self.retry_attempts = max(0, retry_attempts)
        self.retry_sleep_s = max(0.0, retry_sleep_s)
        self.events_path = events_path
        self.spans_path = spans_path
        self.runtime_config = dict(runtime_config)
        self._model_call_index = 0

    async def close(self) -> None:
        close = getattr(self.base_model, "close", None)
        if close is None:
            return None
        result = close()
        if hasattr(result, "__await__"):
            await result
        return None

    def get_retry_advice(self, request: Any) -> Any:
        get_retry_advice = getattr(self.base_model, "get_retry_advice", None)
        if get_retry_advice is None:
            return None
        return get_retry_advice(request)

    async def get_response(
        self,
        system_instructions: str | None,
        input: Any,
        model_settings: Any,
        tools: list[Any],
        output_schema: Any,
        handoffs: list[Any],
        tracing: Any,
        *,
        previous_response_id: str | None,
        conversation_id: str | None,
        prompt: Any,
    ) -> Any:
        attempt_index = 0
        while True:
            started = time.time()
            call_index = self._next_model_call_index()
            racing_enabled = self._get_response_racing_enabled()
            _append_model_service_event(
                self.events_path,
                self.spans_path,
                "model_service_attempt",
                runtime_config=self.runtime_config,
                attempt_index=attempt_index,
                retry_budget=self.retry_attempts,
                method="get_response",
            )
            try:
                if racing_enabled:
                    result = await self._race_get_response(
                        call_index=call_index,
                        attempt_index=attempt_index,
                        system_instructions=system_instructions,
                        input=input,
                        model_settings=model_settings,
                        tools=tools,
                        output_schema=output_schema,
                        handoffs=handoffs,
                        tracing=tracing,
                        previous_response_id=previous_response_id,
                        conversation_id=conversation_id,
                        prompt=prompt,
                    )
                else:
                    arm_id = _model_racing_arm_id(
                        call_index=call_index,
                        attempt_index=attempt_index,
                        arm_index=0,
                    )
                    _append_model_racing_event(
                        self.events_path,
                        self.spans_path,
                        "model_racing_arm_start",
                        runtime_config=self.runtime_config,
                        call_index=call_index,
                        attempt_index=attempt_index,
                        arm_id=arm_id,
                        arm_index=0,
                        method="get_response",
                        arm_role="single",
                    )
                    result = await self.base_model.get_response(
                        system_instructions,
                        input,
                        model_settings,
                        tools,
                        output_schema,
                        handoffs,
                        tracing,
                        previous_response_id=previous_response_id,
                        conversation_id=conversation_id,
                        prompt=prompt,
                    )
            except Exception as exc:
                should_retry, failure = _should_retry_model_service_failure(
                    exc,
                    attempt_index=attempt_index,
                    retry_attempts=self.retry_attempts,
                )
                _append_model_service_failure_events(
                    self.events_path,
                    self.spans_path,
                    runtime_config=self.runtime_config,
                    attempt_index=attempt_index,
                    retry_budget=self.retry_attempts,
                    method="get_response",
                    started_at=started,
                    failure=failure,
                    will_retry=should_retry,
                    retry_delay_s=self.retry_sleep_s if should_retry else None,
                    safe_to_replay=True,
                )
                if not racing_enabled:
                    _append_model_racing_event(
                        self.events_path,
                        self.spans_path,
                        "model_racing_arm_failure",
                        runtime_config=self.runtime_config,
                        call_index=call_index,
                        attempt_index=attempt_index,
                        arm_id=_model_racing_arm_id(
                            call_index=call_index,
                            attempt_index=attempt_index,
                            arm_index=0,
                        ),
                        arm_index=0,
                        method="get_response",
                        arm_role="single",
                        elapsed_s=_round_duration(time.time() - started),
                        final_outcome="retry_scheduled" if should_retry else "failure",
                        failure_class=failure.reason,
                        provider_reason=failure.provider_reason,
                        retryable=failure.retryable,
                        winner=False,
                        cancelled=False,
                        cancellation_observed=False,
                        loser_billing_unknown=False,
                        safe_to_replay=True,
                    )
                if not should_retry:
                    raise
                if self.retry_sleep_s:
                    await asyncio.sleep(self.retry_sleep_s)
                attempt_index += 1
                continue
            _append_model_service_event(
                self.events_path,
                self.spans_path,
                "model_service_success",
                runtime_config=self.runtime_config,
                attempt_index=attempt_index,
                retry_budget=self.retry_attempts,
                method="get_response",
                elapsed_s=_round_duration(time.time() - started),
                final_outcome="success",
            )
            if not racing_enabled:
                _append_model_racing_event(
                    self.events_path,
                    self.spans_path,
                    "model_racing_arm_finish",
                    runtime_config=self.runtime_config,
                    call_index=call_index,
                    attempt_index=attempt_index,
                    arm_id=_model_racing_arm_id(
                        call_index=call_index,
                        attempt_index=attempt_index,
                        arm_index=0,
                    ),
                    arm_index=0,
                    method="get_response",
                    arm_role="single",
                    elapsed_s=_round_duration(time.time() - started),
                    final_outcome="success",
                    winner=True,
                    cancelled=False,
                    cancellation_observed=False,
                    loser_billing_unknown=False,
                    usage_summary=_usage_summary(result),
                )
            return result

    def _get_response_racing_enabled(self) -> bool:
        config = (
            self.runtime_config.get("model_racing_observability")
            if isinstance(self.runtime_config.get("model_racing_observability"), dict)
            else {}
        )
        return bool(config.get("enabled")) and self._racing_arm_count() > 1

    def _racing_arm_count(self) -> int:
        config = (
            self.runtime_config.get("model_racing_observability")
            if isinstance(self.runtime_config.get("model_racing_observability"), dict)
            else {}
        )
        return _positive_int(
            config.get("arm_count"), "model_racing_observability.arm_count", default=1
        )

    async def _race_get_response(
        self,
        *,
        call_index: int,
        attempt_index: int,
        system_instructions: str | None,
        input: Any,
        model_settings: Any,
        tools: list[Any],
        output_schema: Any,
        handoffs: list[Any],
        tracing: Any,
        previous_response_id: str | None,
        conversation_id: str | None,
        prompt: Any,
    ) -> Any:
        tasks = [
            asyncio.create_task(
                self._get_response_racing_arm(
                    arm_index=arm_index,
                    call_index=call_index,
                    attempt_index=attempt_index,
                    system_instructions=system_instructions,
                    input=input,
                    model_settings=model_settings,
                    tools=tools,
                    output_schema=output_schema,
                    handoffs=handoffs,
                    tracing=tracing,
                    previous_response_id=previous_response_id,
                    conversation_id=conversation_id,
                    prompt=prompt,
                )
            )
            for arm_index in range(self._racing_arm_count())
        ]
        pending = set(tasks)
        failures: list[_ModelRacingArmOutcome] = []
        try:
            while pending:
                done, pending = await asyncio.wait(pending, return_when=asyncio.FIRST_COMPLETED)
                successful = [
                    outcome for task in done for outcome in [task.result()] if outcome.exc is None
                ]
                failures.extend(
                    outcome
                    for task in done
                    for outcome in [task.result()]
                    if outcome.exc is not None
                )
                if not successful:
                    continue

                winner = min(successful, key=lambda outcome: outcome.arm_index)
                for outcome in successful:
                    _append_model_racing_event(
                        self.events_path,
                        self.spans_path,
                        "model_racing_arm_finish",
                        runtime_config=self.runtime_config,
                        call_index=call_index,
                        attempt_index=attempt_index,
                        arm_id=outcome.arm_id,
                        arm_index=outcome.arm_index,
                        method="get_response",
                        arm_role="winner" if outcome is winner else "loser",
                        elapsed_s=outcome.elapsed_s,
                        final_outcome="success" if outcome is winner else "success_loser",
                        winner=outcome is winner,
                        cancelled=False,
                        cancellation_observed=False,
                        loser_billing_unknown=outcome is not winner,
                        usage_summary=_usage_summary(outcome.result),
                    )
                for task in pending:
                    task.cancel()
                if pending:
                    await asyncio.gather(*pending, return_exceptions=True)
                return winner.result
            if failures and failures[-1].exc is not None:
                raise failures[-1].exc
            raise RuntimeError("model racing completed without a winning arm")
        finally:
            for task in tasks:
                if not task.done():
                    task.cancel()
            if any(not task.done() for task in tasks):
                await asyncio.gather(*tasks, return_exceptions=True)

    async def _get_response_racing_arm(
        self,
        *,
        arm_index: int,
        call_index: int,
        attempt_index: int,
        system_instructions: str | None,
        input: Any,
        model_settings: Any,
        tools: list[Any],
        output_schema: Any,
        handoffs: list[Any],
        tracing: Any,
        previous_response_id: str | None,
        conversation_id: str | None,
        prompt: Any,
    ) -> "_ModelRacingArmOutcome":
        started = time.time()
        arm_id = _model_racing_arm_id(
            call_index=call_index,
            attempt_index=attempt_index,
            arm_index=arm_index,
        )
        _append_model_racing_event(
            self.events_path,
            self.spans_path,
            "model_racing_arm_start",
            runtime_config=self.runtime_config,
            call_index=call_index,
            attempt_index=attempt_index,
            arm_id=arm_id,
            arm_index=arm_index,
            method="get_response",
            arm_role="candidate",
        )
        try:
            result = await self.base_model.get_response(
                system_instructions,
                input,
                model_settings,
                tools,
                output_schema,
                handoffs,
                tracing,
                previous_response_id=previous_response_id,
                conversation_id=conversation_id,
                prompt=prompt,
            )
        except asyncio.CancelledError:
            _append_model_racing_event(
                self.events_path,
                self.spans_path,
                "model_racing_arm_cancelled",
                runtime_config=self.runtime_config,
                call_index=call_index,
                attempt_index=attempt_index,
                arm_id=arm_id,
                arm_index=arm_index,
                method="get_response",
                arm_role="loser",
                elapsed_s=_round_duration(time.time() - started),
                final_outcome="cancelled",
                winner=False,
                cancelled=True,
                cancellation_observed=True,
                loser_billing_unknown=True,
            )
            raise
        except Exception as exc:
            failure = _failure_from_exception(exc)
            _append_model_racing_event(
                self.events_path,
                self.spans_path,
                "model_racing_arm_failure",
                runtime_config=self.runtime_config,
                call_index=call_index,
                attempt_index=attempt_index,
                arm_id=arm_id,
                arm_index=arm_index,
                method="get_response",
                arm_role="candidate",
                elapsed_s=_round_duration(time.time() - started),
                final_outcome="failure",
                failure_class=failure.reason,
                provider_reason=failure.provider_reason,
                retryable=failure.retryable,
                winner=False,
                cancelled=False,
                cancellation_observed=False,
                loser_billing_unknown=False,
                safe_to_replay=True,
            )
            return _ModelRacingArmOutcome(
                arm_index=arm_index,
                arm_id=arm_id,
                elapsed_s=_round_duration(time.time() - started),
                exc=exc,
            )
        return _ModelRacingArmOutcome(
            arm_index=arm_index,
            arm_id=arm_id,
            elapsed_s=_round_duration(time.time() - started),
            result=result,
        )

    async def stream_response(
        self,
        system_instructions: str | None,
        input: Any,
        model_settings: Any,
        tools: list[Any],
        output_schema: Any,
        handoffs: list[Any],
        tracing: Any,
        *,
        previous_response_id: str | None,
        conversation_id: str | None,
        prompt: Any,
    ) -> Any:
        attempt_index = 0
        while True:
            started = time.time()
            yielded_event = False
            call_index = self._next_model_call_index()
            arm_id = _model_racing_arm_id(call_index=call_index, attempt_index=attempt_index)
            _append_model_racing_event(
                self.events_path,
                self.spans_path,
                "model_racing_arm_start",
                runtime_config=self.runtime_config,
                call_index=call_index,
                attempt_index=attempt_index,
                arm_id=arm_id,
                method="stream_response",
                arm_role="single",
                arm_count=1,
                racing_enabled=False,
                racing_mode="stream_response_single_arm_no_racing",
                racing_multiplier=1.0,
                winner_selection="stream_response_single_arm_no_racing",
                loser_cancellation="not_applicable_stream_response",
            )
            _append_model_service_event(
                self.events_path,
                self.spans_path,
                "model_service_attempt",
                runtime_config=self.runtime_config,
                attempt_index=attempt_index,
                retry_budget=self.retry_attempts,
                method="stream_response",
            )
            try:
                stream = self.base_model.stream_response(
                    system_instructions,
                    input,
                    model_settings,
                    tools,
                    output_schema,
                    handoffs,
                    tracing,
                    previous_response_id=previous_response_id,
                    conversation_id=conversation_id,
                    prompt=prompt,
                )
                async for event in stream:
                    yielded_event = True
                    yield event
            except Exception as exc:
                safe_to_replay = not yielded_event
                should_retry, failure = _should_retry_model_service_failure(
                    exc,
                    attempt_index=attempt_index,
                    retry_attempts=self.retry_attempts,
                    safe_to_replay=safe_to_replay,
                )
                _append_model_service_failure_events(
                    self.events_path,
                    self.spans_path,
                    runtime_config=self.runtime_config,
                    attempt_index=attempt_index,
                    retry_budget=self.retry_attempts,
                    method="stream_response",
                    started_at=started,
                    failure=failure,
                    will_retry=should_retry,
                    retry_delay_s=self.retry_sleep_s if should_retry else None,
                    safe_to_replay=safe_to_replay,
                )
                _append_model_racing_event(
                    self.events_path,
                    self.spans_path,
                    "model_racing_arm_failure",
                    runtime_config=self.runtime_config,
                    call_index=call_index,
                    attempt_index=attempt_index,
                    arm_id=arm_id,
                    method="stream_response",
                    arm_role="single",
                    arm_count=1,
                    racing_enabled=False,
                    racing_mode="stream_response_single_arm_no_racing",
                    racing_multiplier=1.0,
                    winner_selection="stream_response_single_arm_no_racing",
                    loser_cancellation="not_applicable_stream_response",
                    elapsed_s=_round_duration(time.time() - started),
                    final_outcome="retry_scheduled" if should_retry else "failure",
                    failure_class=failure.reason,
                    provider_reason=failure.provider_reason,
                    retryable=failure.retryable,
                    winner=False,
                    cancelled=False,
                    cancellation_observed=False,
                    loser_billing_unknown=False,
                    safe_to_replay=safe_to_replay,
                )
                if not should_retry:
                    raise
                if self.retry_sleep_s:
                    await asyncio.sleep(self.retry_sleep_s)
                attempt_index += 1
                continue
            _append_model_service_event(
                self.events_path,
                self.spans_path,
                "model_service_success",
                runtime_config=self.runtime_config,
                attempt_index=attempt_index,
                retry_budget=self.retry_attempts,
                method="stream_response",
                elapsed_s=_round_duration(time.time() - started),
                final_outcome="success",
            )
            _append_model_racing_event(
                self.events_path,
                self.spans_path,
                "model_racing_arm_finish",
                runtime_config=self.runtime_config,
                call_index=call_index,
                attempt_index=attempt_index,
                arm_id=arm_id,
                method="stream_response",
                arm_role="single",
                arm_count=1,
                racing_enabled=False,
                racing_mode="stream_response_single_arm_no_racing",
                racing_multiplier=1.0,
                winner_selection="stream_response_single_arm_no_racing",
                loser_cancellation="not_applicable_stream_response",
                elapsed_s=_round_duration(time.time() - started),
                final_outcome="success",
                winner=True,
                cancelled=False,
                cancellation_observed=False,
                loser_billing_unknown=False,
            )
            return

    def _next_model_call_index(self) -> int:
        value = self._model_call_index
        self._model_call_index += 1
        return value


def _should_retry_model_service_failure(
    exc: Exception,
    *,
    attempt_index: int,
    retry_attempts: int,
    safe_to_replay: bool = True,
) -> tuple[bool, LiveAgentFailure]:
    failure = _failure_from_exception(exc)
    should_retry = (
        safe_to_replay
        and failure.reason == "provider_transient_failure"
        and failure.retryable
        and attempt_index < retry_attempts
    )
    return should_retry, failure


def _append_model_service_failure_events(
    events_path: Path,
    spans_path: Path,
    *,
    runtime_config: dict[str, Any],
    attempt_index: int,
    retry_budget: int,
    method: str,
    started_at: float,
    failure: LiveAgentFailure,
    will_retry: bool,
    retry_delay_s: float | None,
    safe_to_replay: bool,
) -> None:
    base_payload = {
        "attempt_index": attempt_index,
        "retry_budget": retry_budget,
        "method": method,
        "failure_class": failure.reason,
        "provider_reason": failure.provider_reason,
        "retryable": failure.retryable,
        "safe_to_replay": safe_to_replay,
        "elapsed_s": _round_duration(time.time() - started_at),
        "final_outcome": "" if will_retry else "failure",
        "retry_exhausted": (
            failure.reason == "provider_transient_failure"
            and failure.retryable
            and not will_retry
            and safe_to_replay
        ),
    }
    _append_model_service_event(
        events_path,
        spans_path,
        "model_service_failure",
        runtime_config=runtime_config,
        **base_payload,
    )
    if will_retry:
        _append_model_service_event(
            events_path,
            spans_path,
            "model_service_retry_scheduled",
            runtime_config=runtime_config,
            **{
                **base_payload,
                "retry_delay_s": retry_delay_s,
                "next_attempt_index": attempt_index + 1,
                "final_outcome": "",
                "retry_exhausted": False,
            },
        )


def _append_model_service_event(
    events_path: Path,
    spans_path: Path,
    event: str,
    *,
    runtime_config: dict[str, Any],
    attempt_index: int,
    retry_budget: int,
    method: str,
    **extra: Any,
) -> None:
    payload = _drop_empty(
        {
            "schema": "openai_agents_model_service_fallback_v1",
            "event": event,
            "ts_epoch": time.time(),
            "runtime": runtime_config.get("runtime"),
            "provider_profile": runtime_config.get("provider_profile"),
            "wire_api": runtime_config.get("wire_api"),
            "model": runtime_config.get("model"),
            "attempt_index": attempt_index,
            "retry_budget": retry_budget,
            "method": method,
            **extra,
        }
    )
    _append_event(events_path, payload)
    span_payload = {
        **payload,
        "schema": "openai_agents_sanitized_span_v1",
        "span_type": "model_service_fallback",
    }
    _append_event(spans_path, span_payload)


def _model_racing_arm_id(
    *,
    call_index: int,
    attempt_index: int,
    arm_index: int = 0,
) -> str:
    return f"call-{call_index}-attempt-{attempt_index}-arm-{arm_index}"


def _append_model_racing_event(
    events_path: Path,
    spans_path: Path,
    event: str,
    *,
    runtime_config: dict[str, Any],
    call_index: int,
    attempt_index: int,
    arm_id: str,
    method: str,
    arm_role: str,
    arm_index: int = 0,
    **extra: Any,
) -> None:
    config = (
        runtime_config.get("model_racing_observability")
        if isinstance(runtime_config.get("model_racing_observability"), dict)
        else {}
    )
    payload = _drop_empty(
        {
            "schema": MODEL_RACING_EVENT_SCHEMA,
            "event": event,
            "ts_epoch": time.time(),
            "runtime": runtime_config.get("runtime"),
            "provider_profile": runtime_config.get("provider_profile"),
            "wire_api": runtime_config.get("wire_api"),
            "model": runtime_config.get("model"),
            "call_index": call_index,
            "attempt_index": attempt_index,
            "arm_id": arm_id,
            "arm_index": arm_index,
            "arm_count": config.get("arm_count", 1),
            "arm_role": arm_role,
            "method": method,
            "racing_enabled": bool(config.get("enabled")),
            "racing_mode": config.get("mode") or "off",
            "racing_multiplier": config.get("racing_multiplier", 1.0),
            "winner_selection": config.get("winner_selection") or "single_arm_no_racing",
            "loser_cancellation": config.get("loser_cancellation")
            or "not_applicable_until_racing_enabled",
            **extra,
        }
    )
    _append_event(events_path, payload)
    span_payload = {
        **payload,
        "schema": "openai_agents_sanitized_span_v1",
        "span_type": "model_racing_observability",
    }
    _append_event(spans_path, span_payload)


def _usage_summary(result: Any) -> dict[str, Any]:
    raw_usage = getattr(result, "usage", None)
    usage = _to_jsonable(raw_usage) if raw_usage is not None else {}
    if not isinstance(usage, dict) or not usage:
        return {"usage_available": False}
    input_tokens = _int_from_any(usage.get("input_tokens"))
    cached_tokens = _cached_input_tokens_from_usage(usage)
    output_tokens = _int_from_any(usage.get("output_tokens"))
    reasoning_tokens = _reasoning_tokens_from_usage(usage)
    payload: dict[str, Any] = {
        "usage_available": True,
        "input_tokens": input_tokens,
        "cached_input_tokens": cached_tokens,
        "output_tokens": output_tokens,
        "reasoning_tokens": reasoning_tokens,
    }
    if input_tokens is not None and cached_tokens is not None:
        payload["uncached_input_tokens"] = max(0, input_tokens - cached_tokens)
    return _drop_empty(payload)


def _cached_input_tokens_from_usage(usage: dict[str, Any]) -> int | None:
    details = usage.get("input_tokens_details")
    if isinstance(details, dict):
        cached = _int_from_any(details.get("cached_tokens"))
        if cached is not None:
            return cached
    return _int_from_any(usage.get("cached_input_tokens"))


def _reasoning_tokens_from_usage(usage: dict[str, Any]) -> int | None:
    details = usage.get("output_tokens_details")
    if isinstance(details, dict):
        reasoning = _int_from_any(details.get("reasoning_tokens"))
        if reasoning is not None:
            return reasoning
    return _int_from_any(usage.get("reasoning_tokens"))


def _int_from_any(value: Any) -> int | None:
    if isinstance(value, bool):
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


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
    if settings["base_url_env"] == "CODEX_BASE_URL":
        _require_setting(
            settings["provider_profile"], settings["base_url_env"], settings["base_url"]
        )
    if settings["api_key_env"]:
        _require_setting(settings["provider_profile"], settings["api_key_env"], settings["api_key"])
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


def _failure_from_exception(exc: Exception) -> LiveAgentFailure:
    if isinstance(exc, OpenAIAgentsBudgetExceededError):
        return exc.failure
    detail = str(exc)
    if exc.__class__.__name__ == "MaxTurnsExceeded":
        return LiveAgentFailure(
            "agent_sdk_turn_budget_exceeded",
            retryable=False,
            resume_available=False,
            detail=detail,
        )
    lowered = detail.lower()
    if any(
        item in lowered
        for item in (
            "roboclaws_openai_agents_",
            "openai agents sdk setting",
        )
    ):
        return LiveAgentFailure("provider_config_failure", retryable=False, detail=detail)
    if any(item in lowered for item in ("requires codex_base_url", "requires codex_api_key")):
        return LiveAgentFailure("provider_config_failure", retryable=False, detail=detail)
    if any(
        item in lowered
        for item in (
            "requires xm_llm_api_key",
            "requires mm_api_key",
            "supports responses provider",
        )
    ):
        return LiveAgentFailure("provider_config_failure", retryable=False, detail=detail)
    if any(
        item in lowered for item in ("authentication", "unauthorized", "invalid api key", "401")
    ):
        return LiveAgentFailure("provider_auth_failure", retryable=False, detail=detail)
    if any(
        item in lowered
        for item in (
            "context length",
            "context_length",
            "context window",
            "maximum context",
            "input exceeds the context",
            "too large",
        )
    ):
        return LiveAgentFailure("provider_context_failure", retryable=False, detail=detail)
    if any(
        item in lowered
        for item in (
            "429",
            "rate limit",
            "too many requests",
            "500",
            "502",
            "503",
            "504",
            "model unavailable",
            "model_unavailable",
            "temporarily unavailable",
            "service unavailable",
            "internal server error",
            "bad gateway",
            "gateway timeout",
        )
    ):
        provider_reason = (
            "rate_limit" if "429" in lowered or "rate limit" in lowered else "upstream_unavailable"
        )
        return LiveAgentFailure(
            "provider_transient_failure",
            retryable=True,
            provider_reason=provider_reason,
            resume_available=True,
            detail=detail,
        )
    if any(
        item in lowered
        for item in (
            "timed out",
            "timeout",
            "connection reset",
            "connection refused",
            "connection error",
            "transport error",
            "broken pipe",
            "econnreset",
        )
    ):
        return LiveAgentFailure(
            "provider_transient_failure",
            retryable=True,
            provider_reason="upstream_timeout",
            resume_available=True,
            detail=detail,
        )
    return LiveAgentFailure("agent_cli_failure", retryable=False, detail=detail)


def _append_event(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(payload, sort_keys=True) + "\n")


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _round_duration(value: float) -> float:
    return round(max(0.0, value), 3)


def _to_jsonable(value: Any) -> Any:
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    if isinstance(value, dict):
        return {str(key): _to_jsonable(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_to_jsonable(item) for item in value]
    if hasattr(value, "model_dump"):
        return _to_jsonable(value.model_dump())
    if hasattr(value, "__dict__"):
        return _to_jsonable(vars(value))
    return str(value)
