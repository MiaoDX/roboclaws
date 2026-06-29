"""Human-readable live timeout debug summary lines."""

from __future__ import annotations

from typing import Any


def debug_snapshot_lines(snapshot: dict[str, Any]) -> list[str]:
    if not snapshot:
        return []
    progress = snapshot.get("progress") if isinstance(snapshot.get("progress"), dict) else {}
    lines = [
        "debug snapshot: "
        f"elapsed={_format_duration(snapshot.get('elapsed_s'))} "
        f"result={snapshot.get('run_result_present', False)} "
        f"report={snapshot.get('report_present', False)} "
        f"signal={snapshot.get('timeout_signal', 'unknown')} "
        f"last={snapshot.get('last_trace_event', 'none')} "
        f"last_response={snapshot.get('last_trace_response', 'none')}",
        "debug progress: "
        f"metric_map={progress.get('metric_map', 0)} "
        f"resolve={progress.get('resolve_target_query', 0)} "
        f"observe={progress.get('observe', 0)} "
        f"nav_wp={progress.get('navigate_to_waypoint', 0)} "
        f"pick={progress.get('pick', 0)} "
        f"place={progress.get('place', 0)} "
        f"done={progress.get('done', 0)}",
    ]
    model_line = _debug_model_events_line(snapshot)
    if model_line:
        lines.append(model_line)
    return lines


def _debug_model_events_line(snapshot: dict[str, Any]) -> str:
    event_counts = (
        snapshot.get("openai_agents_event_counts")
        if isinstance(snapshot.get("openai_agents_event_counts"), dict)
        else {}
    )
    if not event_counts:
        return ""
    interesting = (
        "model_service_attempt",
        "model_service_success",
        "model_service_failure",
        "model_racing_arm_start",
        "model_racing_arm_finish",
    )
    counts = " ".join(f"{name}={event_counts.get(name, 0)}" for name in interesting)
    age = snapshot.get("last_openai_agents_event_age_s")
    suffix = f" last_sdk_age={_format_duration(age)}" if age is not None else ""
    return f"debug model events: {counts}{suffix}"


def _format_duration(value: Any) -> str:
    parsed = _float_or_none(value)
    if parsed is None:
        return "unknown"
    if parsed < 60:
        return f"{parsed:.1f}s"
    minutes, seconds = divmod(int(parsed), 60)
    hours, minutes = divmod(minutes, 60)
    if hours:
        return f"{hours}h{minutes:02d}m{seconds:02d}s"
    return f"{minutes}m{seconds:02d}s"


def _float_or_none(value: Any) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None
