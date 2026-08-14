from __future__ import annotations

import copy
from typing import Any

from roboclaws.maps.runtime_prior_contracts import RUNTIME_MAP_PRIOR_SNAPSHOT_SCHEMA
from roboclaws.maps.runtime_prior_snapshot import runtime_prior_snapshot_from_runtime_metric_map


def materialize_runtime_prior_targets(snapshot: dict[str, Any]) -> dict[str, Any]:
    """Return consumer-facing waypoint and fixture targets from either producer path."""

    if snapshot.get("schema") == RUNTIME_MAP_PRIOR_SNAPSHOT_SCHEMA:
        waypoints = [dict(item) for item in snapshot.get("inspection_waypoints") or []]
        fixtures = [dict(item) for item in snapshot.get("fixture_candidates") or []]
        capabilities = _snapshot_digital_twin_capabilities(snapshot)
    else:
        wrapped = runtime_prior_snapshot_from_runtime_metric_map(snapshot)
        waypoints = [dict(item) for item in wrapped.get("inspection_waypoints") or []]
        fixtures = [dict(item) for item in wrapped.get("fixture_candidates") or []]
        capabilities = _snapshot_digital_twin_capabilities(wrapped)
    return {
        "schema": "runtime_map_prior_materialized_targets_v1",
        "inspection_waypoints": waypoints,
        "fixture_candidates": fixtures,
        "actionable_waypoint_ids": [
            str(item.get("waypoint_id") or "")
            for item in waypoints
            if item.get("actionability") == "actionable"
        ],
        "actionable_fixture_ids": [
            str(item.get("fixture_id") or "")
            for item in fixtures
            if item.get("actionability") == "actionable"
        ],
        "digital_twin_capabilities": capabilities,
        "capability_summary": _digital_twin_capability_summary(capabilities),
    }


def _snapshot_digital_twin_capabilities(snapshot: dict[str, Any]) -> dict[str, Any]:
    runtime_map = (
        snapshot.get("runtime_metric_map")
        if isinstance(snapshot.get("runtime_metric_map"), dict)
        else {}
    )
    source_map = (
        snapshot.get("source_navigation_map")
        if isinstance(snapshot.get("source_navigation_map"), dict)
        else {}
    )
    capabilities = runtime_map.get("digital_twin_capabilities")
    if not isinstance(capabilities, dict):
        capabilities = source_map.get("digital_twin_capabilities")
    return copy.deepcopy(capabilities if isinstance(capabilities, dict) else {})


def _digital_twin_capability_summary(capabilities: dict[str, Any]) -> dict[str, Any]:
    robot_proof = (
        capabilities.get("robot_consumption_proof")
        if isinstance(capabilities.get("robot_consumption_proof"), dict)
        else {}
    )
    room_proof = (
        capabilities.get("room_semantic_projection_proof")
        if isinstance(capabilities.get("room_semantic_projection_proof"), dict)
        else {}
    )
    render_proof = (
        capabilities.get("render_observation_proof")
        if isinstance(capabilities.get("render_observation_proof"), dict)
        else {}
    )
    visual_route = (
        render_proof.get("default_visual_route")
        if isinstance(render_proof.get("default_visual_route"), dict)
        else {}
    )
    return {
        "robot_navigation_supported": bool(robot_proof.get("robot_navigation_supported")),
        "robot_consumption_status": str(robot_proof.get("status") or ""),
        "planner_backed_navigation_supported": bool(robot_proof.get("planner_backed")),
        "physical_robot_supported": bool(robot_proof.get("physical_robot")),
        "room_semantics_supported": bool(room_proof.get("room_semantics_supported")),
        "room_semantics_status": str(room_proof.get("status") or ""),
        "object_semantics_supported": bool(room_proof.get("object_semantics_supported")),
        "object_projection_status": str(room_proof.get("object_projection_status") or ""),
        "manipulation_supported": bool(robot_proof.get("manipulation_supported")),
        "render_observation_supported": bool(render_proof.get("render_observation_supported")),
        "render_observation_status": str(render_proof.get("status") or ""),
        "same_pose_fpv_supported": bool(render_proof.get("same_pose_fpv_supported")),
        "same_pose_chase_supported": bool(render_proof.get("same_pose_chase_supported")),
        "same_pose_topdown_supported": bool(render_proof.get("same_pose_topdown_supported")),
        "default_visual_route_status": str(visual_route.get("status") or ""),
        "default_visual_route_scene": str(visual_route.get("scene_root") or ""),
        "default_visual_route_selected": bool(visual_route.get("selected")),
    }
