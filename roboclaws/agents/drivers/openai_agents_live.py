"""OpenAI Agents SDK live-runtime composition."""

from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from roboclaws.agents import provider_transport as pt
from roboclaws.agents.drivers.openai_agents_event_log import (
    _append_event,
    _recording_tool_error_function,
    _write_json,
)
from roboclaws.agents.drivers.openai_agents_event_projection import _summarize_sdk_result
from roboclaws.agents.drivers.openai_agents_provider_runtime import (
    close_async_resource as _close_async_resource,
)
from roboclaws.agents.drivers.openai_agents_provider_runtime import (
    failure_from_exception as _classify_provider_failure,
)
from roboclaws.agents.drivers.openai_agents_retry_model import (
    _model_service_retry_config as _retry_config,
)
from roboclaws.agents.drivers.openai_agents_retry_model import (
    _RetryingModel as _RetryModelImpl,
)
from roboclaws.agents.drivers.openai_agents_run_config import (
    _cache_tools_list,
    _instructions_with_skill_context,
    _max_turns,
    _mcp_client_session_timeout_seconds,
    _model_settings,
    _runtime_config,
    _sdk_model_settings_payload,
    _sdk_run_config_payload,
    _write_skill_context_summary,
)
from roboclaws.agents.drivers.openai_agents_spans import (
    RoboclawsSpanRecorder,
    append_span_limitation,
)
from roboclaws.agents.live_runtime import LiveAgentRequest, LiveAgentResult, LiveAgentRuntime
from roboclaws.agents.live_status import LiveAgentFailure


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
            failure = _classify_provider_failure(exc)
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

        try:
            async with server:
                runner_kwargs: dict[str, Any] = {
                    "max_turns": _max_turns(request),
                    "run_config": run_config,
                }
                result = await Runner.run(agent, request.kickoff_prompt, **runner_kwargs)
            _append_event(
                events_path,
                {
                    "event": "result",
                    "ts_epoch": time.time(),
                    "summary": _summarize_sdk_result(result),
                },
            )
            return result
        finally:
            await _close_async_resource(getattr(agent, "model", None))

    return asyncio.run(_run())


def _model_for_request(request: LiveAgentRequest) -> Any:
    from openai import AsyncOpenAI  # type: ignore[import-not-found]

    settings = _model_settings(request)
    client_kwargs: dict[str, Any] = {
        "api_key": settings["api_key"],
        "base_url": settings["base_url"],
    }
    client_kwargs.update(pt.provider_client_options(settings["provider_profile"], request.run_dir))
    client = AsyncOpenAI(**client_kwargs)
    if settings["wire_api"] == "responses":
        from agents import OpenAIResponsesModel  # type: ignore[import-not-found]

        base_model = OpenAIResponsesModel(settings["request_model"], openai_client=client)
    elif settings["wire_api"] == "chat-completions":
        from agents import OpenAIChatCompletionsModel  # type: ignore[import-not-found]

        base_model = OpenAIChatCompletionsModel(settings["request_model"], openai_client=client)
    else:  # pragma: no cover - guarded by _model_settings.
        raise RuntimeError(f"unsupported OpenAI Agents wire API: {settings['wire_api']}")
    retry_config = _retry_config(request)
    return _RetryModelImpl(
        base_model,
        client=client,
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
