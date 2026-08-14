"""Privacy-preserving event logging for the OpenAI Agents runtime."""

from __future__ import annotations

import hashlib
import json
import time
from pathlib import Path
from typing import Any

from roboclaws.agents.drivers.openai_agents_event_projection import (
    _budget_detail_summary,
    _drop_empty,
    _model_input_shape_summary,
    _to_jsonable,
)
from roboclaws.agents.drivers.openai_agents_provider_runtime import (
    model_service_failure_detail as _model_service_failure_detail,
)
from roboclaws.agents.live_status import LiveAgentFailure

MODEL_RACING_EVENT_SCHEMA = "openai_agents_model_racing_observability_v1"


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
        "failure_detail": _model_service_failure_detail(failure),
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


def _append_event(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(payload, sort_keys=True) + "\n")


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _round_duration(value: float) -> float:
    return round(max(0.0, value), 3)


def _append_model_input_filter_event(
    events_path: Path,
    *,
    runtime_config: dict[str, Any],
    config: dict[str, Any],
    metrics: dict[str, Any],
    input_items: list[Any] | None = None,
) -> None:
    _append_event(
        events_path,
        _drop_empty(
            {
                "schema": "openai_agents_model_input_filter_v1",
                "event": "model_input_filter",
                "ts_epoch": time.time(),
                "runtime": runtime_config.get("runtime"),
                "provider_profile": runtime_config.get("provider_profile"),
                "wire_api": runtime_config.get("wire_api"),
                "model": runtime_config.get("model"),
                "config": _drop_empty(_to_jsonable(config)),
                "metrics": _drop_empty(_to_jsonable(metrics)),
                "input_shape_summary": _model_input_shape_summary(input_items or []),
                "privacy_note": (
                    "Only aggregate counts, byte sizes, hashes, and policy metadata are persisted. "
                    "Raw prompts, model text, tool payload bodies, credentials, and private truth "
                    "are not stored by this event."
                ),
            }
        ),
    )


def _append_model_input_budget_event(
    events_path: Path,
    *,
    runtime_config: dict[str, Any],
    profile: dict[str, Any],
    timing: dict[str, Any],
    failure: Any,
) -> None:
    detail: dict[str, Any] = {}
    if getattr(failure, "detail", ""):
        try:
            parsed = json.loads(failure.detail)
        except json.JSONDecodeError:
            detail = {"detail_text_sha256": hashlib.sha256(failure.detail.encode()).hexdigest()}
        else:
            detail = parsed if isinstance(parsed, dict) else {}
    _append_event(
        events_path,
        _drop_empty(
            {
                "schema": "openai_agents_model_input_budget_guard_v1",
                "event": "model_input_budget_guard",
                "ts_epoch": time.time(),
                "runtime": runtime_config.get("runtime"),
                "provider_profile": runtime_config.get("provider_profile"),
                "wire_api": runtime_config.get("wire_api"),
                "model": runtime_config.get("model"),
                "profile_id": profile.get("profile_id") or "baseline",
                "evidence_lane": timing.get("evidence_lane") or timing.get("profile") or "",
                "reason": getattr(failure, "reason", ""),
                "retryable": getattr(failure, "retryable", False),
                "resume_available": getattr(failure, "resume_available", False),
                "detail_schema": detail.get("schema"),
                "detail_summary": _budget_detail_summary(detail),
                "privacy_note": (
                    "Aggregate budget guard metadata only. Raw prompts, model text, tool "
                    "payload bodies, image payloads, credentials, and private truth are "
                    "not stored by this event."
                ),
            }
        ),
    )


def _append_model_input_budget_advisory_event(
    events_path: Path,
    *,
    runtime_config: dict[str, Any],
    advisory: dict[str, Any],
) -> None:
    _append_event(
        events_path,
        _drop_empty(
            {
                "schema": "openai_agents_model_input_budget_advisory_v1",
                "event": "model_input_budget_advisory",
                "ts_epoch": time.time(),
                "runtime": runtime_config.get("runtime"),
                "provider_profile": runtime_config.get("provider_profile"),
                "wire_api": runtime_config.get("wire_api"),
                "model": runtime_config.get("model"),
                "profile_id": advisory.get("profile_id"),
                "evidence_lane": advisory.get("evidence_lane"),
                "reason": advisory.get("reason"),
                "detail_schema": advisory.get("schema"),
                "detail_summary": _budget_detail_summary(advisory),
                "privacy_note": (
                    "Public waypoint ids and aggregate observation counts only. Raw prompts, "
                    "model text, tool payload bodies, image payloads, credentials, and private "
                    "truth are not stored by this event."
                ),
            }
        ),
    )
