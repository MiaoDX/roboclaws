"""Lightweight live-run snapshots for timeout diagnosis."""

from __future__ import annotations

import os
import time
from pathlib import Path
from typing import Any

from roboclaws.agents.live_timing import round_duration
from roboclaws.core.json_sources import read_jsonl_objects


def timeout_debug_snapshot(
    run_dir: Path,
    *,
    started_at_epoch: float,
    captured_at_epoch: float | None = None,
) -> dict[str, Any]:
    captured = captured_at_epoch or time.time()
    trace_events, trace_error = _read_jsonl_path_for_snapshot(run_dir / "trace.jsonl")
    agent_events, agent_errors = _openai_agents_events_for_snapshot(run_dir)
    trace_responses = [event for event in trace_events if event.get("event") == "response"]
    trace_requests = [event for event in trace_events if event.get("event") == "request"]
    tool_response_counts = _counts_by_field(trace_responses, "tool")
    agent_event_counts = _counts_by_field(agent_events, "event")
    last_trace = trace_events[-1] if trace_events else {}
    last_response = trace_responses[-1] if trace_responses else {}
    last_agent_event = agent_events[-1] if agent_events else {}
    last_agent_ts = _float_or_none(last_agent_event.get("ts_epoch"))
    progress = _progress_counts(tool_response_counts)
    snapshot: dict[str, Any] = {
        "schema": "molmo_live_timeout_debug_snapshot_v1",
        "captured_at_epoch": captured,
        "elapsed_s": round_duration(captured - started_at_epoch),
        "runner_pid": os.getpid(),
        "server_pid": _server_pid_from_file(run_dir / "server.pid"),
        "run_result_present": (run_dir / "run_result.json").is_file(),
        "report_present": (run_dir / "report.html").is_file(),
        "trace_event_count": len(trace_events),
        "trace_request_count": len(trace_requests),
        "trace_response_count": len(trace_responses),
        "last_trace_event": _snapshot_event_label(last_trace),
        "last_trace_response": _snapshot_event_label(last_response),
        "last_trace_wallclock_elapsed_s": _rounded_event_elapsed(last_trace),
        "tool_response_counts": tool_response_counts,
        "progress": progress,
        "openai_agents_event_count": len(agent_events),
        "openai_agents_event_counts": agent_event_counts,
        "last_openai_agents_event": str(last_agent_event.get("event") or "none"),
        "last_openai_agents_ts_epoch": last_agent_ts,
        "last_openai_agents_event_age_s": round_duration(captured - last_agent_ts)
        if last_agent_ts is not None
        else None,
        "model_service_attempt_count": agent_event_counts.get("model_service_attempt", 0),
        "model_service_success_count": agent_event_counts.get("model_service_success", 0),
        "model_service_failure_count": agent_event_counts.get("model_service_failure", 0),
        "model_racing_arm_start_count": agent_event_counts.get("model_racing_arm_start", 0),
        "model_racing_arm_finish_count": agent_event_counts.get("model_racing_arm_finish", 0),
    }
    snapshot["timeout_signal"] = _timeout_signal(snapshot, progress)
    if trace_error:
        snapshot["trace_source_error"] = trace_error
    if agent_errors:
        snapshot["openai_agents_source_errors"] = agent_errors
    return snapshot


def _read_jsonl_path_for_snapshot(path: Path) -> tuple[list[dict[str, Any]], str]:
    if not path.is_file():
        return [], ""
    try:
        return read_jsonl_objects(path, label="OpenAI Agents live timeout debug"), ""
    except (OSError, ValueError) as exc:
        return [], str(exc)


def _openai_agents_events_for_snapshot(run_dir: Path) -> tuple[list[dict[str, Any]], list[str]]:
    rows: list[dict[str, Any]] = []
    errors: list[str] = []
    for path in sorted(run_dir.glob("openai-agents-events*.jsonl")):
        path_rows, error = _read_jsonl_path_for_snapshot(path)
        rows.extend(path_rows)
        if error:
            errors.append(f"{path.name}: {error}")
    rows.sort(key=lambda item: _float_or_none(item.get("ts_epoch")) or 0.0)
    return rows, errors


def _counts_by_field(events: list[dict[str, Any]], field: str) -> dict[str, int]:
    counts: dict[str, int] = {}
    for event in events:
        value = str(event.get(field) or "")
        if value and not value.startswith("<"):
            counts[value] = counts.get(value, 0) + 1
    return counts


def _progress_counts(tool_counts: dict[str, int]) -> dict[str, int]:
    return {
        "metric_map": tool_counts.get("metric_map", 0),
        "resolve_target_query": tool_counts.get("resolve_target_query", 0),
        "observe": tool_counts.get("observe", 0),
        "navigate_to_waypoint": tool_counts.get("navigate_to_waypoint", 0),
        "navigate_to_object": tool_counts.get("navigate_to_object", 0),
        "pick": tool_counts.get("pick", 0),
        "navigate_to_receptacle": tool_counts.get("navigate_to_receptacle", 0),
        "open_receptacle": tool_counts.get("open_receptacle", 0),
        "place": tool_counts.get("place", 0),
        "place_inside": tool_counts.get("place_inside", 0),
        "close_receptacle": tool_counts.get("close_receptacle", 0),
        "done": tool_counts.get("done", 0),
    }


def _timeout_signal(snapshot: dict[str, Any], progress: dict[str, int]) -> str:
    if int(snapshot.get("model_service_failure_count") or 0) > 0:
        return "provider_failures_seen"
    if snapshot.get("last_openai_agents_event") in {
        "model_service_attempt",
        "model_racing_arm_start",
    }:
        return "model_call_in_flight"
    if progress.get("done", 0) == 0 and any(count > 0 for count in progress.values()):
        return "task_progress_without_completion"
    if not snapshot.get("trace_event_count") and not snapshot.get("openai_agents_event_count"):
        return "no_runtime_progress"
    return "runtime_active_without_completion"


def _snapshot_event_label(event: dict[str, Any]) -> str:
    if not event:
        return "none"
    return f"{event.get('tool', '?')}:{event.get('event', '?')}"


def _rounded_event_elapsed(event: dict[str, Any]) -> float | None:
    elapsed = _float_or_none(event.get("wallclock_elapsed"))
    return round_duration(elapsed) if elapsed is not None else None


def _server_pid_from_file(path: Path) -> int | None:
    try:
        return int(path.read_text(encoding="utf-8").strip())
    except (OSError, ValueError):
        return None


def _float_or_none(value: Any) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None
