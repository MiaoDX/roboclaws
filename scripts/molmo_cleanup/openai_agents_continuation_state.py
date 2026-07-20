from __future__ import annotations

from typing import Any


def waypoints_by_observation_recency(trace_events: list[dict[str, Any]]) -> list[str]:
    waypoint_ids: list[str] = []
    for event in reversed(trace_events):
        if event.get("event") != "response" or event.get("tool") != "observe":
            continue
        response = event.get("response") if isinstance(event.get("response"), dict) else {}
        if response.get("ok") is not True:
            continue
        waypoint_id = str(response.get("waypoint_id") or "")
        if waypoint_id and waypoint_id not in waypoint_ids:
            waypoint_ids.append(waypoint_id)
    return waypoint_ids


def latest_done_completion_blockers(
    trace_events: list[dict[str, Any]],
) -> tuple[int | None, list[dict[str, Any]]]:
    for event_index in range(len(trace_events) - 1, -1, -1):
        event = trace_events[event_index]
        if event.get("event") != "response" or event.get("tool") != "done":
            continue
        response = event.get("response") if isinstance(event.get("response"), dict) else {}
        completion = (
            response.get("completion") if isinstance(response.get("completion"), dict) else {}
        )
        blockers = completion.get("blockers")
        if not isinstance(blockers, list):
            return event_index, []
        return event_index, [item for item in blockers if isinstance(item, dict)]
    return None, []


def remaining_observes_by_waypoint(
    waypoint_ids: list[str],
    observe_counts: dict[str, int],
    *,
    max_observes: int | None,
) -> dict[str, int | None]:
    return {
        waypoint_id: max(0, max_observes - int(observe_counts.get(waypoint_id, 0)))
        if max_observes is not None
        else None
        for waypoint_id in waypoint_ids
    }


def reconcile_remaining_observes_with_heading_blocker(
    remaining_observes: dict[str, int | None],
    blockers: list[dict[str, Any]],
) -> None:
    blocker = next(
        (item for item in blockers if item.get("type") == "insufficient_raw_fpv_heading_coverage"),
        None,
    )
    if blocker is None:
        return
    required = _int_or_none(blocker.get("required_distinct_heading_count"))
    raw_counts = blocker.get("distinct_heading_counts_by_waypoint")
    counts = raw_counts if isinstance(raw_counts, dict) else {}
    if required is not None:
        for waypoint_id, raw_count in counts.items():
            count = _int_or_none(raw_count)
            if waypoint_id in remaining_observes and count is not None:
                remaining_observes[waypoint_id] = max(0, required - count)
    next_waypoint_id = str(blocker.get("next_waypoint_id") or "")
    current = _int_or_none(blocker.get("current_distinct_heading_count"))
    if required is not None and current is not None and next_waypoint_id in remaining_observes:
        remaining_observes[next_waypoint_id] = max(0, required - current)


def _int_or_none(value: Any) -> int | None:
    if isinstance(value, bool) or value is None:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None
