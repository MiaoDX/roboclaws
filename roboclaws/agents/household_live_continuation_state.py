"""Trace-derived continuation state for household SDK recovery."""

from __future__ import annotations

from typing import Any

from roboclaws.agents.drivers.openai_agents_continuation_state import (
    latest_done_completion_blockers,
)


def _observe_counts_by_waypoint(trace_events: list[dict[str, Any]]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for event in trace_events:
        if event.get("event") != "response" or event.get("tool") != "observe":
            continue
        response = event.get("response") if isinstance(event.get("response"), dict) else {}
        if response.get("ok") is not True:
            continue
        waypoint_id = str(response.get("waypoint_id") or "")
        if waypoint_id:
            counts[waypoint_id] = counts.get(waypoint_id, 0) + 1
    return dict(sorted(counts.items()))


def _latest_done_blockers(trace_events: list[dict[str, Any]]) -> list[dict[str, Any]]:
    event_index, blockers = latest_done_completion_blockers(trace_events)
    if event_index is None:
        return []
    normalized = [
        {
            key: blocker[key]
            for key in (
                "type",
                "current",
                "required",
                "required_tool",
                "next_waypoint_id",
                "policy_id",
                "sweep_coverage_rate",
                "observed_waypoint_count",
                "total_waypoints",
                "current_distinct_heading_count",
                "required_distinct_heading_count",
                "distinct_heading_counts_by_waypoint",
                "incomplete_waypoint_ids",
                "followup_tool",
                "required_camera_adjustment",
                "candidate_free_waypoint_ids",
                "probed_candidate_free_waypoint_ids",
                "recovery_hint",
            )
            if key in blocker
        }
        for blocker in blockers
    ]
    progress_after_done = len(_successful_placement_handles(trace_events[event_index + 1 :]))
    if progress_after_done:
        _reconcile_grounded_chain_progress(normalized, progress_after_done)
    return normalized


def _reconcile_grounded_chain_progress(
    blockers: list[dict[str, Any]], progress_after_done: int
) -> None:
    for blocker in blockers:
        if blocker.get("type") != "insufficient_grounded_cleanup_chains":
            continue
        current = _int_or_none(blocker.get("current"))
        required = _int_or_none(blocker.get("required"))
        if current is None:
            continue
        blocker["current"] = (
            min(required, current + progress_after_done)
            if required
            else (current + progress_after_done)
        )
        blocker["progress_since_latest_done"] = progress_after_done
        blocker["progress_source"] = "trace_reconciled_after_done"


def _latest_done_public_action_state(trace_events: list[dict[str, Any]]) -> dict[str, Any]:
    _, blockers = latest_done_completion_blockers(trace_events)
    pending_blockers = [
        item for item in blockers if item.get("type") == "pending_cleanup_candidates"
    ]
    pending = [
        candidate
        for blocker in pending_blockers
        for candidates in [blocker.get("pending_cleanup_candidates")]
        if isinstance(candidates, list)
        for candidate in candidates
        if isinstance(candidate, dict)
    ]
    sweep = next(
        (item for item in blockers if item.get("type") == "insufficient_sweep_coverage"),
        {},
    )
    raw_unvisited = sweep.get("unvisited_waypoint_ids")
    unvisited_waypoints = (
        [str(item) for item in raw_unvisited if str(item)][:32]
        if isinstance(raw_unvisited, list)
        else []
    )
    next_waypoint = str(sweep.get("next_waypoint_id") or "")
    if not next_waypoint and unvisited_waypoints:
        next_waypoint = unvisited_waypoints[0]
    return {
        "actionable_pending_candidates": _public_actionable_pending_candidates(pending),
        "next_unvisited_waypoint": next_waypoint,
        "unvisited_waypoint_ids": unvisited_waypoints,
    }


def _public_actionable_pending_candidates(
    pending: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    sanitized: list[dict[str, Any]] = []
    seen_ids: set[str] = set()
    for candidate in pending:
        public_id = str(candidate.get("object_id") or "")
        if not public_id or public_id in seen_ids:
            continue
        seen_ids.add(public_id)
        item = {
            key: candidate[key]
            for key in (
                "object_id",
                "category",
                "state",
                "candidate_state",
                "required_tool",
            )
            if key in candidate
        }
        options = candidate.get("destination_options")
        if isinstance(options, list):
            item["destination_options"] = [
                {
                    key: option[key]
                    for key in (
                        "candidate_fixture_id",
                        "candidate_fixture_category",
                        "recommended_tool",
                        "candidate_source",
                        "waypoint_id",
                    )
                    if key in option
                }
                for option in options[:8]
                if isinstance(option, dict)
            ]
        sanitized.append(item)
        if len(sanitized) >= 12:
            break
    sanitized.sort(key=lambda item: 0 if item.get("state") == "held" else 1)
    return sanitized


def _inspection_waypoint_ids(trace_events: list[dict[str, Any]]) -> list[str]:
    for event in trace_events:
        if event.get("event") != "response" or event.get("tool") != "metric_map":
            continue
        response = event.get("response") if isinstance(event.get("response"), dict) else {}
        raw_waypoints = response.get("inspection_waypoints")
        if not isinstance(raw_waypoints, list):
            continue
        return [
            str(item.get("waypoint_id") or "")
            for item in raw_waypoints
            if isinstance(item, dict) and item.get("waypoint_id")
        ]
    return []


def _compact_failed_candidate_attempts(
    attempts: list[dict[str, Any]],
) -> list[dict[str, str]]:
    return [
        {
            "source_observation_id": str(item.get("source_observation_id") or ""),
            "waypoint_id": str(item.get("waypoint_id") or ""),
            "category": str(item.get("category") or ""),
            "region": str(item.get("region") or ""),
            "error_reason": str(item.get("failure_reason") or "tool_failed"),
        }
        for item in attempts[-12:]
        if isinstance(item, dict)
    ]


def _successful_placement_handles(trace_events: list[dict[str, Any]]) -> list[str]:
    handles: list[str] = []
    for event in trace_events:
        if event.get("event") != "response" or event.get("tool") not in {"place", "place_inside"}:
            continue
        response = event.get("response") if isinstance(event.get("response"), dict) else {}
        if response.get("ok") is not True:
            continue
        handle = str(response.get("object_id") or response.get("held_object_id") or "")
        if handle and handle not in handles:
            handles.append(handle)
    return handles


def _goal_contract_summary(trace_events: list[dict[str, Any]]) -> dict[str, Any]:
    for event in trace_events:
        goal_contract = event.get("goal_contract")
        if isinstance(goal_contract, dict):
            return {
                "surface": goal_contract.get("surface"),
                "intent": goal_contract.get("intent"),
                "normalized_goal": goal_contract.get("normalized_goal"),
                "goal_scope": goal_contract.get("goal_scope"),
            }
    return {}


def _trace_field(trace_events: list[dict[str, Any]], field: str) -> str:
    for event in trace_events:
        value = event.get(field)
        if value:
            return str(value)
    return ""


def _completed_waypoints(trace_events: list[dict[str, Any]]) -> list[str]:
    completed: list[str] = []
    for event in trace_events:
        if event.get("event") != "response" or event.get("tool") != "observe":
            continue
        response = event.get("response") if isinstance(event.get("response"), dict) else {}
        if response.get("ok") is not True:
            continue
        waypoint_id = str(response.get("waypoint_id") or "")
        if waypoint_id and waypoint_id not in completed:
            completed.append(waypoint_id)
    return completed


def _handled_object_handles(trace_events: list[dict[str, Any]]) -> list[str]:
    return _successful_placement_handles(trace_events)


def _public_pending_object_handles(trace_events: list[dict[str, Any]]) -> list[str]:
    pending: list[str] = []
    for event in trace_events:
        if event.get("event") != "response":
            continue
        response = event.get("response") if isinstance(event.get("response"), dict) else {}
        pending_candidates = response.get("pending_cleanup_candidates")
        if not isinstance(pending_candidates, list):
            continue
        for item in pending_candidates:
            if not isinstance(item, dict):
                continue
            public_id = str(
                item.get("object_id") or item.get("public_id") or item.get("handle") or ""
            )
            if public_id and public_id not in pending:
                pending.append(public_id)
    return pending


def _blocked_candidates(trace_events: list[dict[str, Any]]) -> list[dict[str, str]]:
    blocked: list[dict[str, str]] = []
    for event in trace_events:
        if event.get("event") != "response":
            continue
        tool = str(event.get("tool") or "")
        response = event.get("response") if isinstance(event.get("response"), dict) else {}
        status = str(response.get("status") or "")
        ok = response.get("ok")
        if ok is not False and status not in {"blocked", "failed", "error"}:
            continue
        public_id = str(
            response.get("object_id")
            or response.get("candidate_id")
            or response.get("public_id")
            or response.get("source_observation_id")
            or ""
        )
        reason = str(
            response.get("error_reason")
            or response.get("failure_reason")
            or response.get("reason")
            or response.get("error")
            or status
            or "tool_failed"
        )
        item = {
            "public_id": public_id,
            "reason": reason[:160],
            "last_failure_tool": tool,
        }
        if item not in blocked:
            blocked.append(item)
    return blocked


def _recent_tool_failures(trace_events: list[dict[str, Any]]) -> list[dict[str, str]]:
    failures: list[dict[str, str]] = []
    for event in trace_events:
        if event.get("event") != "response":
            continue
        response = event.get("response") if isinstance(event.get("response"), dict) else {}
        ok = response.get("ok")
        status = str(response.get("status") or "")
        if ok is not False and status not in {"blocked", "failed", "error"}:
            continue
        failures.append(
            {
                "tool": str(event.get("tool") or ""),
                "public_error_class": status or "tool_failed",
                "public_target": str(
                    response.get("object_id")
                    or response.get("candidate_id")
                    or response.get("waypoint_id")
                    or response.get("source_observation_id")
                    or ""
                ),
            }
        )
    return failures


def _remaining_public_gates(completed_waypoints: list[str], pending: list[str]) -> list[str]:
    gates: list[str] = []
    if not completed_waypoints:
        gates.append("inspect public waypoint checklist with metric_map and observe waypoints")
    if pending:
        gates.append("clean public pending handles returned by done")
    gates.append("call done only after public cleanup gates are satisfied")
    return gates


def _next_requested_action(
    completed_waypoints: list[str],
    pending: list[str],
    *,
    actionable_pending: list[dict[str, Any]] | None = None,
    next_unvisited_waypoint: str = "",
) -> str:
    actionable_pending = actionable_pending or []
    if any(item.get("state") == "held" for item in actionable_pending):
        return "finish held candidates using public destination_options before other work"
    if actionable_pending or pending:
        return "clean the public pending handles before broad re-sweep"
    if next_unvisited_waypoint:
        return f"navigate_to_waypoint({next_unvisited_waypoint}), then observe"
    if not completed_waypoints:
        return "call metric_map, navigate_to_waypoint, then observe"
    return "inspect public MCP state, finish missing objects or waypoints, then call done"


def _int_or_none(value: Any) -> int | None:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None
