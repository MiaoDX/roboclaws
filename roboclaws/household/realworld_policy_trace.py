from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from roboclaws.household import agent_view as agent_view_module
from roboclaws.household.semantic_timeline import (
    CLOSE_RECEPTACLE_PHASE,
    PLACE_INSIDE_PHASE,
    PLACE_PHASE,
)


@dataclass(frozen=True)
class _TraceWaypoints:
    source: str
    coverage_ids: set[str]
    target_inspection_ids: set[str]
    total: int


@dataclass
class _PolicyTraceAccumulator:
    waypoints: _TraceWaypoints
    events: list[dict[str, Any]] = field(default_factory=list)
    visited_waypoints: set[str] = field(default_factory=set)
    visited_target_inspection_waypoints: set[str] = field(default_factory=set)
    previous_success_tool: str = ""
    first_cleanup_index: int | None = None
    first_actionable_observation_index: int | None = None
    last_coverage_observation_index: int | None = None
    actionable_observation_indexes: dict[str, int] = field(default_factory=dict)
    observed_waypoints_at_first_cleanup: int = 0
    scan_observe_count: int = 0
    post_place_observe_count: int = 0
    cleanup_action_count: int = 0
    placed_object_count: int = 0

    def record_response(self, raw: dict[str, Any]) -> None:
        tool = str(raw.get("tool") or "")
        response = raw.get("response") if isinstance(raw.get("response"), dict) else {}
        if not response.get("ok"):
            return
        role = _policy_event_role(
            tool,
            self.previous_success_tool,
        )
        waypoint_id = str(response.get("waypoint_id") or "")
        self._record_waypoint(waypoint_id)
        self._record_role(role, tool, response)
        self.events.append(_policy_trace_event(len(self.events) + 1, tool, role, response))
        self.previous_success_tool = tool

    def _record_waypoint(self, waypoint_id: str) -> None:
        if waypoint_id and waypoint_id in self.waypoints.coverage_ids:
            self.visited_waypoints.add(waypoint_id)
        if waypoint_id and waypoint_id in self.waypoints.target_inspection_ids:
            self.visited_target_inspection_waypoints.add(waypoint_id)

    def _record_role(self, role: str, tool: str, response: dict[str, Any]) -> None:
        if role == "coverage_scan_observe":
            self.scan_observe_count += 1
            self.last_coverage_observation_index = len(self.events)
            for handle in _actionable_handles(response):
                self.actionable_observation_indexes.setdefault(handle, len(self.events))
        if role == "post_place_observe":
            self.post_place_observe_count += 1
        if role != "cleanup_action":
            return
        self.cleanup_action_count += 1
        if tool in {PLACE_PHASE, PLACE_INSIDE_PHASE}:
            self.placed_object_count += 1
        if self.first_cleanup_index is None:
            self.first_cleanup_index = len(self.events)
            handle = str(response.get("object_id") or "")
            self.first_actionable_observation_index = self.actionable_observation_indexes.get(
                handle, self.last_coverage_observation_index
            )
            self.observed_waypoints_at_first_cleanup = len(self.visited_waypoints)

    def first_cleanup_before_full_survey(self) -> bool:
        return (
            self.cleanup_action_count > 0
            and self.observed_waypoints_at_first_cleanup < self.waypoints.total
        )

    def loop_style(self) -> str:
        first_cleanup_before_full_survey = self.first_cleanup_before_full_survey()
        if self.cleanup_action_count == 0:
            return "scan_only"
        if not first_cleanup_before_full_survey:
            return "survey_first_cleanup_loop"
        if _cleanup_started_after_first_actionable_observation(
            first_cleanup_index=self.first_cleanup_index,
            first_actionable_observation_index=self.first_actionable_observation_index,
            events=self.events,
        ):
            return "interleaved_cleanup_loop"
        return "delayed_cleanup_loop"


def cleanup_policy_trace_from_events(
    trace_events: list[dict[str, Any]],
    agent_view: dict[str, Any],
    *,
    schema: str,
) -> dict[str, Any]:
    metric_map = agent_view_module.base_metric_map(agent_view)
    accumulator = _PolicyTraceAccumulator(waypoints=_trace_waypoints(metric_map))
    for raw in trace_events:
        if raw.get("event") == "response":
            accumulator.record_response(raw)
    return _policy_trace_payload(
        schema=schema,
        accumulator=accumulator,
    )


def _trace_waypoints(metric_map: dict[str, Any]) -> _TraceWaypoints:
    inspection_waypoints = metric_map.get("inspection_waypoints") or []
    target_inspection_waypoints = [
        item
        for item in inspection_waypoints
        if item.get("waypoint_source") == "generated_target_inspection_candidate"
    ]
    coverage_waypoints = [
        item
        for item in inspection_waypoints
        if item.get("waypoint_source") == "generated_exploration_candidate"
    ]
    waypoint_source = "generated_exploration_candidate"
    return _TraceWaypoints(
        source=waypoint_source,
        coverage_ids=_waypoint_ids(coverage_waypoints),
        target_inspection_ids=_waypoint_ids(target_inspection_waypoints),
        total=len(coverage_waypoints),
    )


def _waypoint_ids(waypoints: list[dict[str, Any]]) -> set[str]:
    return {str(item.get("waypoint_id") or "") for item in waypoints}


def _policy_trace_payload(
    *,
    schema: str,
    accumulator: _PolicyTraceAccumulator,
) -> dict[str, Any]:
    first_cleanup_before_full_survey = accumulator.first_cleanup_before_full_survey()
    return {
        "schema": schema,
        "waypoint_source": accumulator.waypoints.source,
        "loop_style": accumulator.loop_style(),
        "total_waypoints": accumulator.waypoints.total,
        "observed_waypoint_count": len(accumulator.visited_waypoints),
        "target_inspection_waypoint_count": len(accumulator.waypoints.target_inspection_ids),
        "observed_target_inspection_waypoint_count": len(
            accumulator.visited_target_inspection_waypoints
        ),
        "scan_observe_count": accumulator.scan_observe_count,
        "cleanup_action_count": accumulator.cleanup_action_count,
        "placed_object_count": accumulator.placed_object_count,
        "post_place_observe_count": accumulator.post_place_observe_count,
        "first_actionable_observation_index": _public_index(
            accumulator.first_actionable_observation_index
        ),
        "first_cleanup_index": _public_index(accumulator.first_cleanup_index),
        "first_cleanup_before_full_survey": first_cleanup_before_full_survey,
        "events": accumulator.events,
        "public_contract_note": (
            "Waypoint scans are static-map coverage checks. Cleanup actions use "
            "observed_* handles discovered by observe or camera-model policy."
        ),
    }


def _policy_trace_event(
    index: int,
    tool: str,
    role: str,
    response: dict[str, Any],
) -> dict[str, Any]:
    return {
        "index": index,
        "tool": tool,
        "role": role,
        "waypoint_id": str(response.get("waypoint_id") or ""),
        "object_id": response.get("object_id", ""),
        "fixture_id": response.get("fixture_id", response.get("receptacle_id", "")),
    }


def _policy_event_role(
    tool: str,
    previous_success_tool: str,
) -> str:
    if tool == "navigate_to_waypoint":
        return "coverage_scan_navigation"
    if tool == "observe":
        return (
            "post_place_observe"
            if previous_success_tool in {PLACE_PHASE, PLACE_INSIDE_PHASE, CLOSE_RECEPTACLE_PHASE}
            else "coverage_scan_observe"
        )
    if tool in _CLEANUP_ACTION_TOOLS:
        return "cleanup_action"
    return "setup_or_completion"


def _actionable_handles(response: dict[str, Any]) -> set[str]:
    blockers = (response.get("completion") or {}).get("blockers") or []
    worklist_candidates = [
        candidate
        for blocker in blockers
        if isinstance(blocker, dict)
        for candidate in (blocker.get("pending_cleanup_candidates") or [])
    ]
    detections = [
        *(response.get("visible_object_detections") or []),
        *(response.get("camera_model_candidates") or []),
        *worklist_candidates,
    ]
    return {
        str(item.get("object_id") or "")
        for item in detections
        if isinstance(item, dict)
        and (
            item.get("candidate_state") == "navigation_authorized"
            or item.get("actionability_status") == "actionable"
            or (
                "candidate_state" not in item
                and "actionability_status" not in item
                and bool(item.get("cleanup_recommended"))
            )
        )
        and item.get("object_id")
    }


def _cleanup_started_after_first_actionable_observation(
    *,
    first_cleanup_index: int | None,
    first_actionable_observation_index: int | None,
    events: list[dict[str, Any]],
) -> bool:
    if first_cleanup_index is None or first_actionable_observation_index is None:
        return False
    source_waypoint_id = str(events[first_actionable_observation_index].get("waypoint_id") or "")
    between = events[first_actionable_observation_index + 1 : first_cleanup_index]
    return not any(
        event.get("role") in {"coverage_scan_navigation", "coverage_scan_observe"}
        and str(event.get("waypoint_id") or "") != source_waypoint_id
        for event in between
    )


def _public_index(index: int | None) -> int | None:
    return None if index is None else index + 1


_CLEANUP_ACTION_TOOLS = frozenset(
    {
        "navigate_to_object",
        "navigate_to_visual_candidate",
        "pick",
        "navigate_to_receptacle",
        "open_receptacle",
        "place",
        "place_inside",
        "close_receptacle",
    }
)
