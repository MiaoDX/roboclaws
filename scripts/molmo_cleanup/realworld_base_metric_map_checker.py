from __future__ import annotations

from typing import Any

from roboclaws.household import agent_view as agent_view_module
from roboclaws.household.household_runtime_contract import forbidden_agent_view_keys
from roboclaws.maps.base_waypoints import (
    BASE_WAYPOINT_GENERATION_POLICY,
    BASE_WAYPOINT_PURPOSE,
    BASE_WAYPOINT_SOURCE,
)


def assert_base_metric_map(data: dict[str, Any], agent_view: dict[str, Any]) -> None:
    metric_map = agent_view_module.base_metric_map(agent_view)
    static_fixture_projection: dict[str, Any] = {"rooms": []}
    runtime_map = data.get("runtime_metric_map") or agent_view_module.runtime_metric_map(agent_view)
    static_map = runtime_map.get("static_map") or {}
    _assert_base_metric_core(metric_map, static_fixture_projection, runtime_map)
    _assert_rooms_and_static_map(metric_map, static_fixture_projection, static_map)
    _assert_waypoints(metric_map, runtime_map)
    _assert_no_forbidden_keys(metric_map)
    _assert_no_forbidden_keys(static_fixture_projection)


def _assert_base_metric_core(
    metric_map: dict[str, Any],
    static_fixture_projection: dict[str, Any],
    runtime_map: dict[str, Any],
) -> None:
    base_map = metric_map.get("base_metric_map") or {}
    assert base_map.get("enabled") is True, metric_map
    assert static_fixture_projection.get("rooms") == [], static_fixture_projection
    assert runtime_map.get("source_map_mutated") is False, runtime_map


def _assert_rooms_and_static_map(
    metric_map: dict[str, Any],
    static_fixture_projection: dict[str, Any],
    static_map: dict[str, Any],
) -> None:
    rooms = metric_map.get("rooms") or []
    driveable_ways = metric_map.get("driveable_ways") or []
    room_category_hints = metric_map.get("room_category_hints") or []
    assert isinstance(rooms, list), metric_map
    assert all(isinstance(room, dict) and room.get("room_label") for room in rooms), rooms
    assert isinstance(driveable_ways, list), metric_map
    assert isinstance(room_category_hints, list), metric_map
    assert all(
        isinstance(hint, dict) and hint.get("anchor_type") == "room_area"
        for hint in room_category_hints
    ), room_category_hints
    assert static_fixture_projection.get("rooms") == [], static_fixture_projection
    _assert_static_map(static_map)


def _assert_static_map(static_map: dict[str, Any]) -> None:
    static_rooms = static_map.get("rooms") or []
    static_driveable_ways = static_map.get("driveable_ways") or []
    assert isinstance(static_rooms, list), static_map
    assert all(isinstance(room, dict) and room.get("room_label") for room in static_rooms), (
        static_rooms
    )
    assert static_map.get("fixtures") == [], static_map
    assert isinstance(static_driveable_ways, list), static_map


def _assert_waypoints(
    metric_map: dict[str, Any],
    runtime_map: dict[str, Any],
) -> None:
    waypoints = metric_map.get("inspection_waypoints") or []
    assert waypoints, metric_map
    generated = runtime_map.get("generated_exploration_candidates") or []
    generated_target_inspection = runtime_map.get("generated_target_inspection_candidates") or []
    exploration_waypoints = _waypoints_by_source(waypoints, "generated_exploration_candidate")
    target_inspection_waypoints = _waypoints_by_source(
        waypoints,
        "generated_target_inspection_candidate",
    )
    assert len(generated) == len(exploration_waypoints), runtime_map
    assert len(generated_target_inspection) == len(target_inspection_waypoints), runtime_map
    _assert_public_anchors(runtime_map)
    for waypoint in exploration_waypoints:
        _assert_exploration_waypoint(waypoint)
    for waypoint in target_inspection_waypoints:
        _assert_target_inspection_waypoint(waypoint)


def _waypoints_by_source(waypoints: list[dict[str, Any]], source: str) -> list[dict[str, Any]]:
    return [item for item in waypoints if item.get("waypoint_source") == source]


def _assert_public_anchors(runtime_map: dict[str, Any]) -> None:
    anchors = runtime_map.get("public_semantic_anchors") or []
    assert anchors, runtime_map
    assert any(item.get("anchor_type") == "observation_waypoint" for item in anchors), anchors


def _assert_exploration_waypoint(waypoint: dict[str, Any]) -> None:
    assert waypoint.get("waypoint_source") == BASE_WAYPOINT_SOURCE, waypoint
    if waypoint.get("purpose") == BASE_WAYPOINT_PURPOSE:
        _assert_base_area_inspection_waypoint(waypoint)
        return
    assert waypoint.get("purpose") == "base_metric_map_exploration", waypoint
    assert str(waypoint.get("waypoint_id") or "").startswith("generated_"), waypoint
    provenance = waypoint.get("candidate_provenance") or {}
    assert provenance.get("source") == "public_occupancy_free_space", waypoint
    assert provenance.get("source_room_hidden") is False, waypoint
    assert provenance.get("source_room_label_available") is bool(waypoint.get("room_label")), (
        waypoint
    )
    assert provenance.get("source_fixtures_hidden") is True, waypoint
    assert provenance.get("source_waypoint_hidden") is True, waypoint
    assert "source_waypoint_id" not in provenance, waypoint


def _assert_base_area_inspection_waypoint(waypoint: dict[str, Any]) -> None:
    waypoint_id = str(waypoint.get("waypoint_id") or "")
    area_id = str(waypoint.get("navigation_area_id") or waypoint.get("area_id") or "")
    assert waypoint_id, waypoint
    assert area_id, waypoint
    assert waypoint_id == f"{area_id}_inspection", waypoint
    assert waypoint.get("generation_policy") == BASE_WAYPOINT_GENERATION_POLICY, waypoint
    assert int(waypoint.get("sweep_index") or 0) > 0, waypoint
    assert str(waypoint.get("frame_id") or ""), waypoint
    assert str(waypoint.get("room_id") or ""), waypoint
    assert str(waypoint.get("room_label") or waypoint.get("label") or ""), waypoint
    for key in ("x", "y", "yaw"):
        float(waypoint[key])
    for forbidden_key in (
        "fixture_id",
        "fixture_ids",
        "landmark_id",
        "object_id",
        "receptacle_id",
        "target_fixture_id",
        "target_receptacle_id",
        "valid_receptacle_ids",
    ):
        assert forbidden_key not in waypoint, waypoint


def _assert_target_inspection_waypoint(waypoint: dict[str, Any]) -> None:
    assert str(waypoint.get("waypoint_id") or "").startswith("generated_inspection_"), waypoint
    assert waypoint.get("purpose") == "target_inspection", waypoint
    assert waypoint.get("verified_navigation") is True, waypoint
    assert waypoint.get("source_observation_id"), waypoint
    assert waypoint.get("source_target_candidate_id"), waypoint
    provenance = waypoint.get("candidate_provenance") or {}
    assert provenance.get("source") == "server_verified_standoff_from_visible_evidence", waypoint
    assert provenance.get("source_waypoint_id"), waypoint
    assert provenance.get("source_observation_id"), waypoint


def _assert_no_forbidden_keys(payload: Any) -> None:
    if isinstance(payload, dict):
        forbidden = forbidden_agent_view_keys().intersection(payload)
        assert not forbidden, (sorted(forbidden), payload)
        for value in payload.values():
            _assert_no_forbidden_keys(value)
    elif isinstance(payload, list):
        for value in payload:
            _assert_no_forbidden_keys(value)
