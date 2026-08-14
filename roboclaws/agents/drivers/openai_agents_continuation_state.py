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


def candidate_attempt_counts_by_waypoint(trace_events: list[dict[str, Any]]) -> dict[str, int]:
    observation_waypoints = _observation_waypoint_index(trace_events)
    counts: dict[str, int] = {}
    for event in trace_events:
        if event.get("event") != "request" or event.get("tool") != "navigate_to_visual_candidate":
            continue
        request = event.get("request") if isinstance(event.get("request"), dict) else {}
        waypoint_id = observation_waypoints.get(str(request.get("source_observation_id") or ""), "")
        if waypoint_id:
            counts[waypoint_id] = counts.get(waypoint_id, 0) + 1
    return dict(sorted(counts.items()))


def candidate_outcomes_by_waypoint(
    trace_events: list[dict[str, Any]],
    known_waypoints: list[str],
) -> dict[str, dict[str, int]]:
    observation_waypoints = _observation_waypoint_index(trace_events)
    outcomes = {waypoint_id: _empty_candidate_outcome() for waypoint_id in known_waypoints}
    pending_waypoints: list[str] = []
    for event in trace_events:
        if event.get("tool") != "navigate_to_visual_candidate":
            continue
        if event.get("event") == "request":
            _record_candidate_request(event, observation_waypoints, outcomes, pending_waypoints)
        elif event.get("event") == "response":
            _record_candidate_response(event, outcomes, pending_waypoints)
    return outcomes


def raw_fpv_revisit_waypoints(
    trace_events: list[dict[str, Any]],
    *,
    known_waypoints: list[str],
    candidate_outcomes: dict[str, dict[str, int]],
    latest_done_blockers: list[dict[str, Any]],
    has_pending_candidates: bool,
) -> list[str]:
    chain_blocker = next(
        (
            blocker
            for blocker in latest_done_blockers
            if blocker.get("type") == "insufficient_grounded_cleanup_chains"
        ),
        None,
    )
    if chain_blocker is None or has_pending_candidates:
        return []
    current = _int_or_none(chain_blocker.get("current"))
    required = _int_or_none(chain_blocker.get("required"))
    if current is not None and required is not None and current >= required:
        return []

    latest_done_index, _ = latest_done_completion_blockers(trace_events)
    observed_after_done = (
        set(_completed_waypoints(trace_events[latest_done_index + 1 :]))
        if latest_done_index is not None
        else set()
    )

    def eligible(waypoint_id: str) -> bool:
        return waypoint_id not in observed_after_done

    unresolved = [
        waypoint_id
        for waypoint_id in known_waypoints
        if eligible(waypoint_id)
        and (candidate_outcomes.get(waypoint_id) or {}).get("unresolved", 0) > 0
    ]
    candidate_free = [
        waypoint_id
        for waypoint_id in known_waypoints
        if eligible(waypoint_id)
        and (candidate_outcomes.get(waypoint_id) or {}).get("attempted", 0) == 0
    ]
    previously_authorized = [
        waypoint_id
        for waypoint_id in known_waypoints
        if eligible(waypoint_id)
        and (candidate_outcomes.get(waypoint_id) or {}).get("authorized", 0) > 0
        and waypoint_id not in unresolved
        and waypoint_id not in candidate_free
    ]
    return unresolved + candidate_free + previously_authorized


def _observation_waypoint_index(trace_events: list[dict[str, Any]]) -> dict[str, str]:
    observation_waypoints: dict[str, str] = {}
    for event in trace_events:
        if event.get("event") != "response" or event.get("tool") != "observe":
            continue
        response = event.get("response") if isinstance(event.get("response"), dict) else {}
        if response.get("ok") is not True:
            continue
        raw_observation = response.get("raw_fpv_observation")
        if not isinstance(raw_observation, dict):
            compact = response.get("compact_observation")
            compact = compact if isinstance(compact, dict) else {}
            raw_observation = compact.get("raw_fpv_observation")
        raw_observation = raw_observation if isinstance(raw_observation, dict) else {}
        observation_id = str(raw_observation.get("observation_id") or "")
        waypoint_id = str(response.get("waypoint_id") or raw_observation.get("waypoint_id") or "")
        if observation_id and waypoint_id:
            observation_waypoints[observation_id] = waypoint_id
    return observation_waypoints


def _record_candidate_request(
    event: dict[str, Any],
    observation_waypoints: dict[str, str],
    outcomes: dict[str, dict[str, int]],
    pending_waypoints: list[str],
) -> None:
    request = event.get("request") if isinstance(event.get("request"), dict) else {}
    waypoint_id = observation_waypoints.get(str(request.get("source_observation_id") or ""), "")
    pending_waypoints.append(waypoint_id)
    if waypoint_id:
        outcomes.setdefault(waypoint_id, _empty_candidate_outcome())["attempted"] += 1


def _record_candidate_response(
    event: dict[str, Any],
    outcomes: dict[str, dict[str, int]],
    pending_waypoints: list[str],
) -> None:
    waypoint_id = pending_waypoints.pop(0) if pending_waypoints else ""
    if not waypoint_id:
        return
    response = event.get("response") if isinstance(event.get("response"), dict) else {}
    if response.get("ok") is True:
        outcomes[waypoint_id]["authorized"] += 1
        return
    outcome_key = {
        "visual_candidate_not_resolved": "unresolved",
        "visual_candidate_not_cleanup_recommended": "not_recommended",
    }.get(response.get("error_reason"))
    if outcome_key:
        outcomes[waypoint_id][outcome_key] += 1


def _completed_waypoints(trace_events: list[dict[str, Any]]) -> list[str]:
    return [
        str(event["response"].get("waypoint_id"))
        for event in trace_events
        if event.get("event") == "response"
        and event.get("tool") == "observe"
        and isinstance(event.get("response"), dict)
        and event["response"].get("ok") is True
        and event["response"].get("waypoint_id")
    ]


def _empty_candidate_outcome() -> dict[str, int]:
    return {"attempted": 0, "authorized": 0, "unresolved": 0, "not_recommended": 0}


def _int_or_none(value: Any) -> int | None:
    if isinstance(value, bool) or value is None:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None
