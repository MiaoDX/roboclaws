from __future__ import annotations

from typing import Any

from roboclaws.household import agent_view as agent_view_module
from roboclaws.household.household_runtime_contract import (
    CLEANUP_POLICY_TRACE_SCHEMA,
    CLEANUP_WORKLIST_SCHEMA,
    REAL_ROBOT_MAP_BUNDLE_SCHEMA,
)


def assert_waypoint_honesty(
    data: dict[str, Any],
    report_text: str,
    *,
    open_ended_intent: bool,
    map_build: bool,
) -> None:
    agent_view = data.get("agent_view") or {}
    metric_map = agent_view_module.base_metric_map(agent_view)
    _assert_metric_map(metric_map)
    _assert_waypoints(metric_map)

    worklist = agent_view_module.cleanup_worklist(agent_view)
    trace = data.get("cleanup_policy_trace") or {}
    _assert_worklist(
        worklist,
        trace,
        open_ended_intent=open_ended_intent,
        map_build=map_build,
    )
    assert trace.get("schema") == CLEANUP_POLICY_TRACE_SCHEMA, trace

    if _is_base_metric_map(metric_map):
        _assert_base_metric_map_trace(
            trace,
            report_text,
            open_ended_intent=open_ended_intent,
            map_build=map_build,
        )
        return
    _assert_static_trace(trace, report_text)


def _assert_metric_map(metric_map: dict[str, Any]) -> None:
    assert metric_map.get("schema") == REAL_ROBOT_MAP_BUNDLE_SCHEMA, metric_map
    assert metric_map.get("public_contract_note"), metric_map


def _assert_waypoints(metric_map: dict[str, Any]) -> None:
    waypoints = metric_map.get("inspection_waypoints") or []
    assert waypoints, metric_map
    for waypoint in waypoints:
        _assert_waypoint(metric_map, waypoint)


def _assert_waypoint(metric_map: dict[str, Any], waypoint: dict[str, Any]) -> None:
    allowed_sources = {
        "static_map_coverage",
        "fixture_coverage",
        "static_map_fixture_coverage",
        "agibot_robot_map_9_static_rehearsal",
    }
    if _is_base_metric_map(metric_map):
        allowed_sources.add("generated_exploration_candidate")
        allowed_sources.add("generated_target_inspection_candidate")
    assert waypoint.get("waypoint_source") in allowed_sources, waypoint
    assert waypoint.get("purpose"), waypoint
    if waypoint.get("waypoint_source") == "generated_target_inspection_candidate":
        _assert_generated_target_inspection_waypoint(waypoint)
    else:
        _assert_public_waypoint_label(waypoint)


def _assert_generated_target_inspection_waypoint(waypoint: dict[str, Any]) -> None:
    assert waypoint.get("purpose") == "target_inspection", waypoint
    assert waypoint.get("verified_navigation") is True, waypoint
    assert waypoint.get("source_observation_id"), waypoint
    assert waypoint.get("source_target_candidate_id"), waypoint
    provenance = waypoint.get("candidate_provenance") or {}
    assert provenance.get("source") == "server_verified_standoff_from_visible_evidence", waypoint


def _assert_public_waypoint_label(waypoint: dict[str, Any]) -> None:
    forbidden_words = ("mess", "target", "acceptable")
    label_text = f"{waypoint.get('waypoint_source', '')} {waypoint.get('purpose', '')}".lower()
    assert not any(word in label_text for word in forbidden_words), waypoint


def _assert_worklist(
    worklist: dict[str, Any],
    trace: dict[str, Any],
    *,
    open_ended_intent: bool,
    map_build: bool,
) -> None:
    assert worklist.get("schema") == CLEANUP_WORKLIST_SCHEMA, worklist
    if _is_scan_only_trace(
        trace,
        open_ended_intent=open_ended_intent,
        map_build=map_build,
    ):
        assert isinstance(worklist.get("objects") or [], list), worklist
    else:
        assert worklist.get("objects"), worklist
    assert worklist.get("waypoints"), worklist


def _is_scan_only_trace(
    trace: dict[str, Any],
    *,
    open_ended_intent: bool,
    map_build: bool,
) -> bool:
    cleanup_action_count = int(trace.get("cleanup_action_count") or 0)
    return cleanup_action_count == 0 and (open_ended_intent or map_build)


def _is_base_metric_map(metric_map: dict[str, Any]) -> bool:
    return bool((metric_map.get("base_metric_map") or {}).get("enabled"))


def _assert_base_metric_map_trace(
    trace: dict[str, Any],
    report_text: str,
    *,
    open_ended_intent: bool,
    map_build: bool,
) -> None:
    assert trace.get("waypoint_source") == "generated_exploration_candidate", trace
    if map_build:
        _assert_map_build_scan_only_trace(trace)
    elif open_ended_intent and int(trace.get("cleanup_action_count") or 0) == 0:
        assert trace.get("loop_style") == "scan_only", trace
    else:
        _assert_base_metric_map_cleanup_trace(trace)
    assert "Waypoint Honesty & Cleanup Loop" in report_text, report_text[:500]
    assert "generated_exploration_candidate" in report_text, report_text[:500]


def _assert_map_build_scan_only_trace(trace: dict[str, Any]) -> None:
    assert trace.get("first_cleanup_before_full_survey") is False, trace
    assert trace.get("loop_style") == "scan_only", trace
    assert trace.get("cleanup_action_count") == 0, trace


def _assert_base_metric_map_cleanup_trace(trace: dict[str, Any]) -> None:
    assert trace.get("loop_style") in {
        "survey_first_cleanup_loop",
        "interleaved_cleanup_loop",
    }, trace
    if trace.get("loop_style") == "survey_first_cleanup_loop":
        assert trace.get("first_cleanup_before_full_survey") is False, trace
    else:
        assert trace.get("first_cleanup_before_full_survey") is True, trace
    assert int(trace.get("cleanup_action_count") or 0) > 0, trace
    _assert_observed_all_waypoints(trace)
    _assert_post_place_observe_coverage(trace)


def _assert_observed_all_waypoints(trace: dict[str, Any]) -> None:
    observed_waypoint_count = int(trace.get("observed_waypoint_count") or 0)
    total_waypoints = int(trace.get("total_waypoints") or 0)
    assert total_waypoints > 0, trace
    assert observed_waypoint_count >= total_waypoints, trace


def _assert_post_place_observe_coverage(trace: dict[str, Any]) -> None:
    placed_object_count = int(trace.get("placed_object_count") or 0)
    post_place_observe_count = int(trace.get("post_place_observe_count") or 0)
    if trace.get("post_place_observe_complete") is not True:
        post_place_observe_count = max(
            post_place_observe_count,
            post_place_observe_count_allowing_public_state_queries(trace),
        )
    assert placed_object_count > 0, trace
    assert post_place_observe_count >= placed_object_count, trace


def _assert_static_trace(trace: dict[str, Any], report_text: str) -> None:
    assert trace.get("waypoint_source") == "static_map_fixture_coverage", trace
    assert trace.get("loop_style") == "interleaved_cleanup_loop", trace
    assert _trace_started_cleanup_after_first_actionable_observation(trace), trace
    _assert_post_place_observe_coverage(trace)
    assert "Waypoint Honesty & Cleanup Loop" in report_text, report_text[:500]
    assert "static_map_fixture_coverage" in report_text, report_text[:500]
    assert "post_place_observe" in report_text, report_text[:500]


def _trace_started_cleanup_after_first_actionable_observation(trace: dict[str, Any]) -> bool:
    first_cleanup = trace.get("first_cleanup_index")
    first_actionable = trace.get("first_actionable_observation_index")
    if first_cleanup is not None or first_actionable is not None:
        try:
            return int(first_cleanup) == int(first_actionable) + 1
        except (TypeError, ValueError):
            return False
    return trace.get("first_cleanup_before_full_survey") is True


def post_place_observe_count_allowing_public_state_queries(trace: dict[str, Any]) -> int:
    pending = 0
    count = 0
    for event in trace.get("events") or []:
        if not isinstance(event, dict):
            continue
        tool = str(event.get("tool") or "")
        role = str(event.get("role") or "")
        if tool in {"place", "place_inside"} and role == "cleanup_action":
            pending += 1
            continue
        if tool == "observe" and pending > 0:
            count += 1
            pending -= 1
            continue
        if pending > 0 and role in {"coverage_scan_navigation", "cleanup_action"}:
            if tool != "close_receptacle":
                pending = 0
    return count
