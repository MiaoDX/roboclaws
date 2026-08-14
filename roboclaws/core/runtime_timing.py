"""Pure runtime timing projection from MCP trace events."""

from __future__ import annotations

from typing import Any


def runtime_timing_from_trace(
    trace_events: list[dict[str, Any]],
    robot_view_steps: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    robot_view_steps = robot_view_steps or []
    timed_events = _timed_trace_events(trace_events)
    if not timed_events:
        return {}
    total_elapsed = max(float(event["wallclock_elapsed"]) for event in timed_events)
    tool_events = _tool_timing_events(timed_events)
    handler_total, breakdown = _tool_handler_breakdown(tool_events)
    raw_gap_total, gaps = _between_tool_gaps(tool_events)
    robot_view_capture = _robot_view_capture_seconds(timed_events, robot_view_steps)
    robot_view_overlap = _subtract_robot_view_capture_from_gaps(timed_events, gaps)
    gap_total = max(0.0, raw_gap_total - robot_view_overlap)
    other_mcp_overhead = max(0.0, total_elapsed - handler_total - robot_view_capture - gap_total)
    return {
        "total_elapsed_s": round(total_elapsed, 3),
        "tool_handler_s": round(handler_total, 3),
        "robot_view_capture_s": round(robot_view_capture, 3),
        "between_tool_gap_s": round(gap_total, 3),
        "raw_between_tool_gap_s": round(raw_gap_total, 3),
        "other_mcp_overhead_s": round(other_mcp_overhead, 3),
        "tool_call_count": sum(int(item["calls"]) for item in breakdown),
        "tool_breakdown": breakdown,
        "longest_between_tool_gaps": gaps[:8],
    }


def robot_view_capture_overlap_seconds(
    trace_events: list[dict[str, Any]], gaps: list[dict[str, Any]]
) -> float:
    intervals = []
    for event in trace_events:
        if event.get("tool") != "<runtime>" or event.get("event") != "robot_view_capture":
            continue
        elapsed = float(event.get("elapsed_s") or 0.0)
        end = float(event.get("wallclock_elapsed") or 0.0)
        if elapsed > 0 and end > 0:
            intervals.append((max(0.0, end - elapsed), end))
    if not intervals or not gaps:
        return 0.0
    overlap_total = 0.0
    for gap in gaps:
        gap_start = float(gap.get("start_s") or 0.0)
        gap_end = float(gap.get("end_s") or 0.0)
        if gap_end <= gap_start:
            continue
        for capture_start, capture_end in intervals:
            overlap_total += max(0.0, min(gap_end, capture_end) - max(gap_start, capture_start))
    return overlap_total


def _timed_trace_events(trace_events: list[dict[str, Any]]) -> list[dict[str, Any]]:
    timed_events = [
        event for event in trace_events if isinstance(event.get("wallclock_elapsed"), (int, float))
    ]
    timed_events.sort(key=lambda event: float(event["wallclock_elapsed"]))
    return timed_events


def _tool_timing_events(timed_events: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [
        event
        for event in timed_events
        if event.get("tool") != "<runtime>" and event.get("event") in {"request", "response"}
    ]


def _tool_handler_breakdown(
    tool_events: list[dict[str, Any]],
) -> tuple[float, list[dict[str, Any]]]:
    pending_requests: dict[str, list[dict[str, Any]]] = {}
    tool_breakdown: dict[str, dict[str, float | int | str]] = {}
    handler_total = 0.0
    for event in tool_events:
        tool = str(event.get("tool", ""))
        if event.get("event") == "request":
            pending_requests.setdefault(tool, []).append(event)
            continue
        if event.get("event") != "response":
            continue
        requests = pending_requests.get(tool) or []
        request = requests.pop(0) if requests else None
        duration = 0.0
        if request is not None:
            duration = max(
                0.0,
                float(event["wallclock_elapsed"]) - float(request["wallclock_elapsed"]),
            )
        item = tool_breakdown.setdefault(tool, {"tool": tool, "calls": 0, "handler_s": 0.0})
        item["calls"] = int(item["calls"]) + 1
        item["handler_s"] = float(item["handler_s"]) + duration
        handler_total += duration
    breakdown = []
    for item in tool_breakdown.values():
        calls = int(item["calls"])
        handler_s = float(item["handler_s"])
        breakdown.append(
            {
                "tool": str(item["tool"]),
                "calls": calls,
                "handler_s": round(handler_s, 3),
                "avg_handler_s": round(handler_s / calls, 3) if calls else 0.0,
            }
        )
    breakdown.sort(key=lambda item: (-float(item["handler_s"]), str(item["tool"])))
    return handler_total, breakdown


def _between_tool_gaps(
    tool_events: list[dict[str, Any]],
) -> tuple[float, list[dict[str, Any]]]:
    raw_gap_total = 0.0
    gaps = []
    previous_response: dict[str, Any] | None = None
    for event in tool_events:
        if event.get("event") == "response":
            previous_response = event
            continue
        if event.get("event") == "request" and previous_response is not None:
            gap = max(
                0.0,
                float(event["wallclock_elapsed"]) - float(previous_response["wallclock_elapsed"]),
            )
            if gap > 0:
                raw_gap_total += gap
                gaps.append(
                    {
                        "after_tool": str(previous_response.get("tool", "")),
                        "before_tool": str(event.get("tool", "")),
                        "start_s": float(previous_response["wallclock_elapsed"]),
                        "end_s": float(event["wallclock_elapsed"]),
                        "gap_s": round(gap, 3),
                    }
                )
            previous_response = None
    return raw_gap_total, gaps


def _subtract_robot_view_capture_from_gaps(
    timed_events: list[dict[str, Any]], gaps: list[dict[str, Any]]
) -> float:
    robot_view_overlap = robot_view_capture_overlap_seconds(timed_events, gaps)
    for gap in gaps:
        overlap = robot_view_capture_overlap_seconds(timed_events, [gap])
        raw_gap = float(gap["gap_s"])
        gap["raw_gap_s"] = round(raw_gap, 3)
        gap["robot_view_capture_s"] = round(overlap, 3)
        gap["gap_s"] = round(max(0.0, raw_gap - overlap), 3)
        gap.pop("start_s", None)
        gap.pop("end_s", None)
    gaps.sort(key=lambda item: -float(item["gap_s"]))
    return robot_view_overlap


def _robot_view_capture_seconds(
    timed_events: list[dict[str, Any]], robot_view_steps: list[dict[str, Any]]
) -> float:
    event_total = sum(
        float(event.get("elapsed_s") or 0.0)
        for event in timed_events
        if event.get("tool") == "<runtime>" and event.get("event") == "robot_view_capture"
    )
    if event_total > 0:
        return event_total
    return sum(float(step.get("capture_elapsed_s") or 0.0) for step in robot_view_steps)


def _float_or_none(value: Any) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None
