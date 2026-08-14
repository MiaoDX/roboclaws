"""Operator-console presentation and control summaries."""

from __future__ import annotations

import time
from pathlib import Path
from typing import Any

from roboclaws.operator_console.locks import ResourceLock
from roboclaws.operator_console.routes import ConsoleLaunchSelection
from roboclaws.operator_console.state_artifacts import LIVE_RUN_MARKERS
from roboclaws.operator_console.state_summary import (
    is_active_run_phase,
    is_terminal_run_phase,
)


def _terminal_reason(
    status: dict[str, Any], live_status: dict[str, Any], run_result: dict[str, Any]
) -> str:
    for payload in (live_status, status, run_result):
        for key in ("terminal_reason", "terminate_reason", "error_reason", "reason", "status"):
            value = payload.get(key)
            if value:
                return str(value)
    return ""


def _status_from_phase(phase: str, checker: dict[str, Any], terminal_reason: str) -> str:
    lower = phase.lower()
    if _is_provider_transient_reason(terminal_reason):
        return "provider_transient_failed"
    if lower in {"stopped_by_operator", "human_takeover_stop", "failed", "passed"}:
        return lower
    if checker.get("status") == "passed":
        return "passed"
    if terminal_reason and lower in {"failed", "error", "terminated"}:
        return "failed"
    if is_active_run_phase(lower):
        return lower
    return "idle"


def _status_label(phase: str, terminal_reason: str) -> str:
    if _is_provider_transient_reason(terminal_reason):
        return "Provider transient failure"
    return phase


def _control_terminal_state(phase: str, status: str, terminal_reason: str) -> bool:
    return (
        is_terminal_run_phase(phase)
        or is_terminal_run_phase(status)
        or is_terminal_run_phase(terminal_reason)
    )


def _relative_control_startup_pending(phase: str) -> bool:
    return phase.lower() in {
        "queued",
        "starting",
        "starting-server",
    }


def _operator_handoff_paused(phase: str, terminal_reason: str) -> bool:
    return phase.lower() == "paused" and terminal_reason.lower() == "operator_handoff_requested"


def _is_provider_transient_reason(reason: str) -> bool:
    normalized = reason.lower()
    return "provider_transient_failure" in normalized or "provider transient" in normalized


def _elapsed_seconds(status: dict[str, Any]) -> float | None:
    value = status.get("started_at_epoch") or status.get("started_at")
    try:
        start = float(value)
    except (TypeError, ValueError):
        return None
    return max(0.0, time.time() - start)


def _latest_action(trace: dict[str, Any], run_result: dict[str, Any]) -> str:
    for payload in (trace, run_result):
        for key in ("action", "tool", "tool_name", "selected_action", "latest_action"):
            value = payload.get(key)
            if value:
                return str(value)
    return ""


def _stop_available(
    *,
    root: Path,
    run_id: str,
    route: ConsoleLaunchSelection | None,
    status: dict[str, Any],
    phase: str,
) -> bool:
    normalized = phase.lower()
    if is_active_run_phase(normalized):
        return True
    if not is_terminal_run_phase(normalized) or normalized in {"done", "emergency_stopped"}:
        return False
    lock_name = str(status.get("backend_lock") or (route.lock_name if route else ""))
    if not lock_name:
        return False
    lock_state = ResourceLock(root, lock_name).read()
    return lock_state.held and lock_state.owner_run_id == run_id


def _decision_evidence(
    trace: dict[str, Any], run_result: dict[str, Any], agent_message: str = ""
) -> dict[str, str]:
    evidence: dict[str, str] = {}
    for key in ("goal", "observation_summary", "reasoning", "decision", "blocked_reason"):
        value = trace.get(key) or run_result.get(key)
        if value:
            evidence[key] = str(value)
    if "observation_summary" not in evidence:
        summary = _trace_summary(trace)
        if summary:
            evidence["observation_summary"] = summary
    if agent_message:
        evidence.setdefault("decision", agent_message)
    return evidence


def _trace_summary(trace: dict[str, Any]) -> str:
    event = str(trace.get("event") or "")
    tool = str(trace.get("tool") or trace.get("tool_name") or trace.get("action") or "")
    if not tool:
        return ""
    response = trace.get("response") if isinstance(trace.get("response"), dict) else {}
    request = trace.get("request") if isinstance(trace.get("request"), dict) else {}
    if event == "request":
        args = _compact_tool_arguments(request)
        return f"Calling {tool}{args}."
    if event == "response" or response:
        status = response.get("status") or response.get("navigation_status") or ""
        ok = response.get("ok")
        suffix = _compact_response_detail(tool, response)
        if ok is True:
            return f"{tool} completed{suffix}."
        if ok is False:
            error = response.get("error") or response.get("error_reason") or "not ok"
            return f"{tool} failed: {error}."
        if status:
            return f"{tool} returned {status}{suffix}."
        return f"{tool} returned a response{suffix}."
    return f"Latest trace event: {tool}."


def _compact_tool_arguments(request: dict[str, Any]) -> str:
    for key in ("object_id", "fixture_id", "waypoint_id"):
        value = request.get(key)
        if value:
            return f" {key}={value}"
    return ""


def _compact_response_detail(tool: str, response: dict[str, Any]) -> str:
    for key in ("object_id", "fixture_id", "waypoint_id", "receptacle_id"):
        value = response.get(key)
        if value:
            return f" for {key}={value}"
    if tool == "observe":
        detections = response.get("visible_object_detections")
        if isinstance(detections, list):
            return f" with {len(detections)} visible detection(s)"
    return ""


def _tool_call_summary(trace: dict[str, Any]) -> dict[str, Any]:
    if not trace:
        return {}
    response = trace.get("response") if isinstance(trace.get("response"), dict) else {}
    request = trace.get("request") if isinstance(trace.get("request"), dict) else {}
    return {
        "name": trace.get("tool") or trace.get("tool_name") or trace.get("action") or "",
        "ok": trace.get("ok") if "ok" in trace else response.get("ok"),
        "arguments": request,
        "latency_ms": trace.get("latency_ms") or trace.get("duration_ms"),
        "error": trace.get("error") or trace.get("error_reason") or response.get("error") or "",
    }


def _public_run_result_summary(run_result: dict[str, Any]) -> dict[str, Any]:
    allowed = (
        "task",
        "backend",
        "policy",
        "profile",
        "task_surface",
        "task_intent",
        "status",
        "ok",
        "success",
        "cleanup_success",
        "runtime_map_success",
        "intent_status",
        "goal_status",
        "cleanup_status",
        "cleanup_status_role",
        "completion_status",
        "final_status",
        "terminate_reason",
        "primitive_provenance",
    )
    return {key: run_result[key] for key in allowed if key in run_result}


def _run_dir_activity_mtime(path: Path) -> float:
    mtimes: list[float] = []
    for marker in LIVE_RUN_MARKERS:
        marker_path = path / marker
        if marker_path.exists():
            try:
                mtimes.append(marker_path.stat().st_mtime)
            except OSError:
                pass
    if mtimes:
        return max(mtimes)
    try:
        return path.stat().st_mtime
    except OSError:
        return 0.0


def _safe_mtime(path: Path) -> float:
    try:
        return path.stat().st_mtime
    except OSError:
        return 0.0
