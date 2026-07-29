from __future__ import annotations

import copy
from collections import defaultdict
from typing import Any

from roboclaws.household.realworld_contract_fixture_projection import (
    _driveable_ways,
    _fixture_affordances,
    _fixture_footprint,
    _polygon_center_world,
    _room_id,
    _vec3,
)
from roboclaws.household.types import CleanupScenario
from roboclaws.maps.bundle import metric_map_bundle_metadata
from roboclaws.maps.spatial_contract import (
    ALIGNMENT_STATUS_NATIVE,
    GEOMETRY_SOURCE_GENERATED_CANDIDATE,
    GEOMETRY_SOURCE_OPERATOR_NAVIGATION_ZONE,
    POLYGON_ROLE_NAVIGATION_AREA,
    normalize_spatial_room,
)

_PROJECTION_FORBIDDEN_AGENT_VIEW_KEYS = frozenset(
    {
        "generated_mess_set",
        "generated_mess_count",
        "environment_setup",
        "relocation_policy",
        "relocation_count",
        "relocated_object_ids",
        "relocated_objects",
        "before_relocation_positions",
        "after_relocation_positions",
        "target_count",
        "acceptable_destination_sets",
        "valid_receptacle_ids",
        "private_manifest",
        "is_misplaced",
        "global_movable_object_inventory",
        "target_receptacle_id",
    }
)


def _map_bundle_fields_present(metric_map: dict[str, Any]) -> bool:
    required = {
        "schema",
        "frame_id",
        "map_id",
        "map_version",
        "resolution_m",
        "origin",
        "width",
        "height",
        "occupancy_values",
        "map_bundle",
        "robot_pose",
        "inspection_waypoints",
    }
    return required <= set(metric_map)


def _pose_stamped_waypoints_present(metric_map: dict[str, Any]) -> bool:
    waypoints = metric_map.get("inspection_waypoints") or []
    required = {
        "waypoint_id",
        "frame_id",
        "x",
        "y",
        "yaw",
        "room_id",
        "label",
        "visited",
        "purpose",
    }
    return bool(waypoints) and all(required <= set(item) for item in waypoints)


def _metric_map(
    contract: Any,
    *,
    realworld_contract: str,
    real_robot_map_bundle_schema: str,
    assert_no_forbidden_agent_view_keys: Any,
) -> dict[str, Any]:
    if contract._bundle_metric_map_template is None:
        raise AssertionError("product runtime metric_map requires a canonical map bundle")
    source = copy.deepcopy(contract._bundle_metric_map_template)
    frame_id = str(source.get("frame_id") or "map")
    map_id = str(source.get("map_id") or f"{contract.scenario.scenario_id}_base_metric_map")
    map_version = str(source.get("map_version") or "base-metric-map-v1")
    metric_map = {
        "ok": True,
        "tool": "metric_map",
        "status": "ok",
        "contract": realworld_contract,
        "schema": real_robot_map_bundle_schema,
        "frame_id": frame_id,
        "map_id": map_id,
        "map_version": map_version,
        "resolution_m": float(source.get("resolution_m") or 0.05),
        "origin": dict(source.get("origin") or {"x": 0.0, "y": 0.0, "yaw": 0.0}),
        "width": int(source.get("width") or 240),
        "height": int(source.get("height") or 180),
        "occupancy_values": dict(
            source.get("occupancy_values") or {"unknown": -1, "free": 0, "occupied": 100}
        ),
        "occupancy_grid_artifact": source.get("occupancy_grid_artifact"),
        "map_bundle": dict(
            source.get("map_bundle")
            or metric_map_bundle_metadata(
                environment_id=contract.scenario.scenario_id,
                map_id=map_id,
                map_version=map_version,
            )
        ),
        "rooms": [dict(item) for item in contract._public_rooms],
        "room_category_hints": _room_category_hints_from_public_rooms(
            contract._public_rooms,
            contract._public_waypoints,
        ),
        "driveable_ways": _public_driveable_ways(source, contract._public_rooms),
        "robot_pose": {
            "frame_id": frame_id,
            **contract._current_pose(),
            "room_id": contract._current_room_id(),
            "waypoint_id": contract._current_waypoint_id,
            "pose_source": _current_pose_source(contract),
        },
        "inspection_waypoints": _public_navigation_waypoints_with_visits(contract),
        "generated_exploration_candidates": _public_waypoints_with_visits(
            contract._public_waypoints,
            contract,
        ),
        "generated_target_inspection_candidates": _public_waypoints_with_visits(
            contract._generated_inspection_waypoints.values(),
            contract,
        ),
        "base_metric_map": {
            "enabled": True,
            "source": _base_metric_map_source(contract),
            "generated_candidate_count": len(contract._public_waypoints),
            "source_rooms_hidden": False,
            "source_room_labels_visible": bool(contract._public_rooms),
            "source_fixtures_hidden": True,
            "source_inspection_waypoints_hidden": False,
            "public_contract_note": (
                "Base Metric Map exposes occupancy geometry, artifact-authored "
                "inspection waypoints, and public room labels, not authored fixture "
                "tables or movable-object semantics."
            ),
        },
        "public_contract_note": (
            "Base Metric Map projection: public room labels and artifact-authored "
            "inspection waypoints are visible. Static fixture tables, movable-object "
            "inventory, and private scoring truth are hidden; Runtime Metric Map "
            "observations enrich the run."
        ),
    }
    metric_map["runtime_metric_map"] = contract.runtime_metric_map_payload(
        metric_map=metric_map,
        static_fixture_projection=contract.static_fixture_projection(),
    )
    assert_no_forbidden_agent_view_keys(metric_map)
    return metric_map


def _static_fixture_projection(
    contract: Any,
    *,
    realworld_contract: str,
    assert_no_forbidden_agent_view_keys: Any,
) -> dict[str, Any]:
    payload = contract._ok(
        "static_fixture_projection",
        contract=realworld_contract,
        schema="static_fixture_projection_v1",
        static_fixture_projection_mode=contract.static_fixture_projection_mode,
        contains_runtime_observations=False,
        rooms=[],
        generated_exploration_candidate_count=len(contract._public_waypoints),
        public_contract_note=(
            "Base Metric Map intentionally hides authored fixture tables. "
            "Public room labels live on metric_map.rooms and room_category_hints. "
            "Runtime observed handles and map update candidates must come from "
            "public observations, not source-map semantics."
        ),
    )
    assert_no_forbidden_agent_view_keys(payload)
    return payload


def _source_map_static_fixture_projection(contract: Any) -> dict[str, Any]:
    public_waypoints_by_room = _first_public_waypoint_by_room(contract._public_waypoints)
    return {
        "schema": "static_fixture_projection_v1",
        "static_fixture_projection_mode": "source_map_static_landmarks",
        "contains_runtime_observations": False,
        "rooms": [
            _source_map_static_fixture_room(
                room,
                contract,
                contract._fixtures,
                public_waypoints_by_room,
            )
            for room in contract._rooms
            if isinstance(room, dict)
        ],
    }


def _source_map_static_fixture_room(
    room: dict[str, Any],
    contract: Any,
    fixtures: dict[str, dict[str, Any]],
    public_waypoints_by_room: dict[str, str],
) -> dict[str, Any]:
    room_id = str(room.get("room_id") or "")
    room_label = str(room.get("room_label") or room_id.replace("_", " "))
    return {
        "room_id": room_id,
        "room_label": room_label,
        "polygon": [dict(point) for point in room.get("polygon") or [] if isinstance(point, dict)],
        "fixtures": [
            _source_map_static_fixture_row(
                fixture_id,
                fixtures[fixture_id],
                contract,
                public_waypoints_by_room,
            )
            for fixture_id in room.get("fixture_ids") or []
            if fixture_id in fixtures
        ],
    }


def _source_map_static_fixture_row(
    fixture_id: str,
    fixture: dict[str, Any],
    contract: Any,
    public_waypoints_by_room: dict[str, str],
) -> dict[str, Any]:
    pose = contract._fixture_pose(fixture_id)
    room_id = str(fixture.get("room_id") or _room_id(str(fixture.get("room_area") or "")))
    preferred_waypoint_id = public_waypoints_by_room.get(
        room_id
    ) or contract._preferred_waypoint_for_fixture(fixture_id)
    payload = {
        "fixture_id": fixture_id,
        "category": str(fixture.get("category") or fixture.get("name") or fixture_id),
        "name": str(fixture.get("name") or fixture_id),
        "room_id": room_id,
        "affordances": _fixture_affordances(fixture),
        "footprint": _fixture_footprint(fixture_id),
        "pose": {
            "frame_id": str(pose.get("frame_id") or "map"),
            "x": float(pose.get("x", 0.0)),
            "y": float(pose.get("y", 0.0)),
            "yaw": float(pose.get("yaw", 0.0)),
        },
        "manipulation_frame": f"{fixture_id}_manipulation",
        "preferred_inspection_waypoint_id": str(
            fixture.get("preferred_inspection_waypoint_id") or preferred_waypoint_id
        ),
        "preferred_manipulation_waypoint_id": str(
            fixture.get("preferred_manipulation_waypoint_id") or preferred_waypoint_id
        ),
        "position_detail": str(fixture.get("position_detail") or "room_only"),
    }
    if isinstance(fixture.get("scene_room_outline"), dict):
        payload["scene_room_outline"] = dict(fixture["scene_room_outline"])
    return payload


def _first_public_waypoint_by_room(waypoints: list[dict[str, Any]]) -> dict[str, str]:
    result: dict[str, str] = {}
    for waypoint in waypoints:
        room_id = str(waypoint.get("room_id") or "")
        waypoint_id = str(waypoint.get("waypoint_id") or "")
        if room_id and waypoint_id:
            result.setdefault(room_id, waypoint_id)
    return result


def _public_navigation_waypoints_with_visits(contract: Any) -> list[dict[str, Any]]:
    return _public_waypoints_with_visits(contract._public_navigation_waypoints(), contract)


def _public_waypoints_with_visits(waypoints: Any, contract: Any) -> list[dict[str, Any]]:
    return [
        {
            **dict(item),
            "visited": str(item.get("waypoint_id") or "") in contract._observed_waypoint_ids,
        }
        for item in waypoints
    ]


def _current_pose_source(contract: Any) -> str:
    waypoint = contract._waypoint_by_id(contract._current_waypoint_id) or {}
    return str(waypoint.get("waypoint_source") or "inspection_waypoint")


def _base_metric_map_source(contract: Any) -> str:
    if getattr(contract, "_bundle_metric_map_template", None) is not None:
        return "map_artifact_inspection_waypoints"
    return "synthetic_map_projection"


def _fixtures_from_bundle_static_landmarks(
    static_landmarks: list[dict[str, Any]],
) -> dict[str, dict[str, Any]]:
    fixtures: dict[str, dict[str, Any]] = {}
    for raw_landmark in static_landmarks:
        if not isinstance(raw_landmark, dict):
            continue
        fixture = dict(raw_landmark)
        fixture_id = str(fixture.get("fixture_id") or fixture.get("landmark_id") or "")
        if not fixture_id:
            continue
        room_id = str(fixture.get("room_id") or "")
        fixture.setdefault("fixture_id", fixture_id)
        fixture.setdefault("receptacle_id", fixture_id)
        fixture.setdefault("room_id", room_id)
        fixture.setdefault("room_area", room_id.replace("_", " ") or room_id)
        fixture.setdefault("kind", "receptacle")
        fixture.setdefault("name", fixture_id)
        fixture.setdefault("category", fixture.get("name", fixture_id))
        fixtures[fixture_id] = fixture
    return fixtures


def _fixtures_from_runtime_scenario(
    scenario: CleanupScenario,
    *,
    waypoints: list[dict[str, Any]],
) -> dict[str, dict[str, Any]]:
    """Build internal runtime fixture handles without adding them to Base Metric Map."""

    waypoint_by_room: dict[str, str] = _runtime_scenario_waypoint_by_room(waypoints)
    fallback_waypoint_id = _first_waypoint_id(waypoints)
    fixtures: dict[str, dict[str, Any]] = {}
    for receptacle in scenario.receptacles:
        fixture_id = str(receptacle.receptacle_id)
        if not fixture_id:
            continue
        room_id = _room_id(str(receptacle.room_area or "runtime_area"))
        preferred_waypoint_id = waypoint_by_room.get(room_id) or fallback_waypoint_id
        fixtures[fixture_id] = {
            "fixture_id": fixture_id,
            "receptacle_id": fixture_id,
            "room_id": room_id,
            "room_area": room_id,
            "kind": receptacle.kind,
            "name": receptacle.name,
            "category": str(receptacle.category or receptacle.name or fixture_id),
            "preferred_inspection_waypoint_id": preferred_waypoint_id,
            "preferred_manipulation_waypoint_id": preferred_waypoint_id,
            "position_detail": "runtime_backend_fixture",
            "public_fixture_source": "runtime_observation_backend",
        }
    return fixtures


def _runtime_scenario_waypoint_by_room(
    waypoints: list[dict[str, Any]],
) -> dict[str, str]:
    waypoint_by_room: dict[str, str] = {}
    public_rooms_by_category: dict[str, list[str]] = defaultdict(list)
    public_rooms_by_label: dict[str, list[str]] = defaultdict(list)
    for waypoint in waypoints:
        room_id = str(waypoint.get("room_id") or "")
        waypoint_id = str(waypoint.get("waypoint_id") or "")
        if not room_id or not waypoint_id:
            continue
        waypoint_by_room.setdefault(room_id, waypoint_id)
        label = str(waypoint.get("room_label") or waypoint.get("label") or room_id)
        public_rooms_by_category[_room_category_from_label(label, room_id)].append(waypoint_id)
        public_rooms_by_label[_room_id(label)].append(waypoint_id)
    for scenario_room, public_room, waypoint_index in (
        ("kitchen", "kitchen", 0),
        ("living_area", "living_room", 0),
        ("work_area", "living_room", 1),
        ("bedroom", "bedroom", 0),
        ("bathroom", "bathroom", 0),
    ):
        waypoint_id = _available_waypoint_id(
            waypoint_index,
            public_rooms_by_category.get(public_room, []),
            public_rooms_by_label.get(public_room, []),
        )
        if waypoint_id:
            waypoint_by_room.setdefault(scenario_room, waypoint_id)
    return waypoint_by_room


def _available_waypoint_id(index: int, *groups: list[str]) -> str:
    for group in groups:
        if len(group) > index and group[index]:
            return group[index]
        for waypoint_id in group:
            if waypoint_id:
                return waypoint_id
    return ""


def _attach_runtime_fixture_ids_to_rooms(
    rooms: list[dict[str, Any]],
    fixtures: dict[str, dict[str, Any]],
) -> None:
    fixture_ids_by_room: dict[str, list[str]] = defaultdict(list)
    for fixture_id, fixture in fixtures.items():
        room_id = str(fixture.get("room_id") or "")
        if room_id:
            fixture_ids_by_room[room_id].append(fixture_id)
    for room in rooms:
        room_id = str(room.get("room_id") or "")
        if not room_id:
            continue
        room["fixture_ids"] = sorted(
            set(room.get("fixture_ids") or []) | set(fixture_ids_by_room.get(room_id, []))
        )


def _scene_index_public_fixture_overlay(
    *,
    backend: Any,
    scenario: CleanupScenario,
    existing_fixtures: dict[str, dict[str, Any]],
    fallback_waypoint_id: str,
) -> dict[str, dict[str, Any]]:
    if str(getattr(backend, "scenario_source", "")) != "isaac_scene_index":
        return {}

    overlay: dict[str, dict[str, Any]] = {}
    for receptacle in scenario.receptacles:
        fixture_id = str(receptacle.receptacle_id)
        if not fixture_id:
            continue
        fixture = dict(existing_fixtures.get(fixture_id, {}))
        fixture["fixture_id"] = fixture_id
        fixture["receptacle_id"] = fixture_id
        fixture["category"] = str(
            receptacle.category or fixture.get("category") or receptacle.name or fixture_id
        )
        fixture["name"] = str(receptacle.name or fixture.get("name") or fixture_id)
        fixture.setdefault("kind", receptacle.kind)
        fixture.setdefault("room_area", receptacle.room_area)
        fixture.setdefault("room_id", _room_id(str(receptacle.room_area)))
        fixture.setdefault("preferred_inspection_waypoint_id", fallback_waypoint_id)
        fixture.setdefault("preferred_manipulation_waypoint_id", fallback_waypoint_id)
        fixture["public_fixture_source"] = "isaac_scene_index"
        overlay[fixture_id] = fixture
    return overlay


def _metric_map_room_payload(room: dict[str, Any]) -> dict[str, Any]:
    payload = normalize_spatial_room(
        {
            "room_id": room["room_id"],
            "room_label": room["room_label"],
            "fixture_count": len(room["fixture_ids"]),
            "polygon": room.get("polygon", []),
        },
        frame_id="map",
        polygon_role=POLYGON_ROLE_NAVIGATION_AREA,
        geometry_source=GEOMETRY_SOURCE_OPERATOR_NAVIGATION_ZONE,
        alignment_status=ALIGNMENT_STATUS_NATIVE,
    )
    if isinstance(room.get("scene_room_outline"), dict):
        payload["scene_room_outline"] = dict(room["scene_room_outline"])
    return payload


def _public_room_hints_from_metric_map(
    metric_map: dict[str, Any],
    *,
    fallback_rooms: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    source_rooms = [item for item in metric_map.get("rooms") or [] if isinstance(item, dict)] or [
        item for item in fallback_rooms if isinstance(item, dict)
    ]
    rooms: list[dict[str, Any]] = []
    seen: set[str] = set()
    for raw_room in source_rooms:
        room = _public_room_hint_payload(raw_room)
        room_id = str(room.get("room_id") or "")
        if not room_id or room_id in seen:
            continue
        rooms.append(room)
        seen.add(room_id)
    return rooms


def _public_room_hint_payload(room: dict[str, Any]) -> dict[str, Any]:
    room_id = str(room.get("room_id") or _room_id(str(room.get("room_label") or "room_area")))
    room_label = str(room.get("room_label") or room_id.replace("_", " "))
    polygon = [dict(point) for point in room.get("polygon") or [] if isinstance(point, dict)]
    map_center = (
        dict(room.get("map_center") or {})
        if isinstance(room.get("map_center"), dict)
        else _polygon_center_world(polygon)
    )
    payload: dict[str, Any] = {
        "room_id": room_id,
        "room_label": room_label,
        "category": str(room.get("category") or _room_category_from_label(room_label, room_id)),
        "polygon": polygon,
        "map_center": map_center,
        "public_room_source": "base_metric_map",
    }
    payload = normalize_spatial_room(
        payload,
        frame_id=str(room.get("source_map_frame_id") or "map"),
        polygon_role=POLYGON_ROLE_NAVIGATION_AREA,
        geometry_source=str(room.get("geometry_source") or GEOMETRY_SOURCE_GENERATED_CANDIDATE),
        alignment_status=str(room.get("alignment_status") or ALIGNMENT_STATUS_NATIVE),
    )
    if isinstance(room.get("scene_room_outline"), dict):
        payload["scene_room_outline"] = dict(room["scene_room_outline"])
    return payload


def _room_category_hints_from_public_rooms(
    rooms: list[dict[str, Any]],
    waypoints: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    waypoint_by_room: dict[str, str] = {}
    for waypoint in waypoints:
        room_id = str(waypoint.get("room_id") or "")
        waypoint_id = str(waypoint.get("waypoint_id") or "")
        if room_id and waypoint_id:
            waypoint_by_room.setdefault(room_id, waypoint_id)
    hints = []
    for room in rooms:
        room_id = str(room.get("room_id") or "")
        room_label = str(room.get("room_label") or room_id.replace("_", " "))
        if not room_id:
            continue
        hint = {
            "anchor_type": "room_area",
            "category": str(room.get("category") or _room_category_from_label(room_label, room_id)),
            "label": room_label,
            "room_id": room_id,
            "room_label": room_label,
            "waypoint_id": waypoint_by_room.get(room_id, ""),
            "affordances": ["navigate", "observe"],
            "classification_status": "map_prior",
            "confidence": 0.8,
            "aliases": [room_id, room_label],
            "producer_type": "base_metric_map",
        }
        _assert_no_forbidden_agent_view_keys(hint)
        hints.append(hint)
    return hints


def _merge_public_rooms(
    base_rooms: list[dict[str, Any]],
    prior_rooms: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    merged: list[dict[str, Any]] = []
    seen: set[str] = set()
    for raw_room in [*base_rooms, *prior_rooms]:
        if not isinstance(raw_room, dict):
            continue
        room = _public_room_hint_payload(raw_room)
        room_id = str(room.get("room_id") or "")
        if not room_id or room_id in seen:
            continue
        merged.append(room)
        seen.add(room_id)
    return merged


def _public_driveable_ways(
    metric_map: dict[str, Any],
    rooms: list[dict[str, Any]],
) -> list[dict[str, str]]:
    public_room_ids = {str(room.get("room_id") or "") for room in rooms}
    ways = []
    for way in metric_map.get("driveable_ways") or []:
        if not isinstance(way, dict):
            continue
        start = str(way.get("from_room_id") or "")
        goal = str(way.get("to_room_id") or "")
        if start in public_room_ids and goal in public_room_ids:
            ways.append({"from_room_id": start, "to_room_id": goal})
    if ways:
        return ways
    return _driveable_ways(rooms)


def _room_label_by_id(rooms: list[dict[str, Any]]) -> dict[str, str]:
    return {
        str(room.get("room_id") or ""): str(room.get("room_label") or "")
        for room in rooms
        if str(room.get("room_id") or "")
    }


def _room_category_from_label(room_label: str, room_id: str = "") -> str:
    text = f"{room_label} {room_id}".lower()
    if any(term in text for term in ("kitchen", "dining", "bar", "counter", "厨房", "吧台")):
        return "kitchen"
    if any(term in text for term in ("living", "sofa", "lounge", "客厅", "沙发")):
        return "living_room"
    if any(term in text for term in ("storage", "store", "utility", "储藏", "库房")):
        return "storage_room"
    if any(term in text for term in ("meeting", "conference", "会议")):
        return "meeting_room"
    if any(term in text for term in ("bed", "卧室")):
        return "bedroom"
    if any(term in text for term in ("bath", "toilet", "卫生间")):
        return "bathroom"
    return "room_area"


def _scene_room_outlines_from_backend(backend: Any) -> list[dict[str, Any]]:
    if str(getattr(backend, "scenario_source", "")) != "isaac_scene_index":
        return []
    outlines = getattr(backend, "room_outlines", None)
    if outlines is None:
        diagnostics = getattr(backend, "scene_index_diagnostics", {})
        if isinstance(diagnostics, dict):
            outlines = diagnostics.get("room_outlines")
    return [
        dict(item)
        for item in (outlines or [])
        if isinstance(item, dict) and item.get("center") and item.get("half_extents")
    ]


def _scene_index_fixture_pose(backend: Any, fixture_id: str) -> list[float] | None:
    receptacle_index = getattr(backend, "receptacle_index", {})
    if not isinstance(receptacle_index, dict):
        return None
    entry = receptacle_index.get(fixture_id)
    if not isinstance(entry, dict):
        return None
    support_pose = entry.get("support_pose")
    if isinstance(support_pose, dict):
        position = support_pose.get("position")
        pose = _vec3(position)
        if pose is not None:
            return pose
    bounds = entry.get("usd_world_bounds")
    if isinstance(bounds, dict):
        pose = _vec3(bounds.get("center"))
        if pose is not None:
            return pose
    return None


def _room_outline_by_id(
    room_outlines: list[dict[str, Any]],
    room_id: str,
) -> dict[str, Any] | None:
    return next((item for item in room_outlines if str(item.get("room_id") or "") == room_id), None)


def _static_fixture_projection_with_scene_index_overlay(
    rooms: list[Any],
    overlay_fixtures: dict[str, dict[str, Any]],
    *,
    static_fixture_projection_mode: str,
) -> list[dict[str, Any]]:
    overlay_room = {
        "room_id": "isaac_scene_index",
        "room_label": "Isaac scene index fixtures",
        "fixture_source": "isaac_scene_index",
        "fixtures": [
            _scene_index_static_fixture_projection_row(
                fixture_id, fixture, static_fixture_projection_mode
            )
            for fixture_id, fixture in sorted(overlay_fixtures.items())
        ],
    }
    return [overlay_room] + [dict(room) for room in rooms if isinstance(room, dict)]


def _scene_index_static_fixture_projection_row(
    fixture_id: str,
    fixture: dict[str, Any],
    static_fixture_projection_mode: str,
) -> dict[str, Any]:
    pose = fixture.get("pose") if isinstance(fixture.get("pose"), dict) else {}
    return {
        "fixture_id": fixture_id,
        "category": str(fixture.get("category") or fixture.get("name") or fixture_id),
        "name": str(fixture.get("name") or fixture_id),
        "room_id": "isaac_scene_index",
        "affordances": _fixture_affordances(fixture),
        "footprint": _fixture_footprint(fixture_id),
        "pose": {
            "frame_id": str(pose.get("frame_id") or "map"),
            "x": float(pose.get("x", 0.0)),
            "y": float(pose.get("y", 0.0)),
            "yaw": float(pose.get("yaw", 0.0)),
        },
        "manipulation_frame": f"{fixture_id}_manipulation",
        "preferred_inspection_waypoint_id": str(
            fixture.get("preferred_inspection_waypoint_id") or ""
        ),
        "preferred_manipulation_waypoint_id": str(
            fixture.get("preferred_manipulation_waypoint_id") or ""
        ),
        "position_detail": static_fixture_projection_mode,
        "public_fixture_source": "isaac_scene_index",
    }


def _first_waypoint_id(waypoints: list[dict[str, Any]]) -> str:
    if not waypoints:
        return ""
    return str(waypoints[0].get("waypoint_id") or "")


def _rooms_from_bundle_projection(
    metric_map: dict[str, Any],
    static_landmarks: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    fixture_ids_by_room: dict[str, list[str]] = defaultdict(list)
    for fixture in static_landmarks:
        if not isinstance(fixture, dict):
            continue
        room_id = str(fixture.get("room_id") or "")
        fixture_id = str(fixture.get("fixture_id") or fixture.get("landmark_id") or "")
        if fixture_id:
            fixture_ids_by_room[room_id].append(fixture_id)

    rooms = []
    for raw_room in metric_map.get("rooms") or []:
        if not isinstance(raw_room, dict):
            continue
        room = dict(raw_room)
        room_id = str(room.get("room_id") or "")
        room["fixture_ids"] = sorted(fixture_ids_by_room.get(room_id, []))
        room.setdefault("room_label", room_id.replace("_", " "))
        room.setdefault("map_center", _polygon_center_world(room.get("polygon") or []))
        rooms.append(room)
    return rooms


def _inspection_waypoints_from_bundle_projection(
    metric_map: dict[str, Any],
    static_landmarks: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    fixture_waypoint_ids, room_fixture_ids = _bundle_landmark_indexes(static_landmarks)
    waypoints = []
    frame_id = str(metric_map.get("frame_id") or "map")
    for raw_waypoint in metric_map.get("inspection_waypoints") or []:
        if not isinstance(raw_waypoint, dict):
            continue
        waypoints.append(
            _bundle_inspection_waypoint(
                raw_waypoint=raw_waypoint,
                frame_id=frame_id,
                fixture_waypoint_ids=fixture_waypoint_ids,
                room_fixture_ids=room_fixture_ids,
            )
        )
    return waypoints


def _bundle_landmark_indexes(
    static_landmarks: list[dict[str, Any]],
) -> tuple[dict[str, list[str]], dict[str, list[str]]]:
    fixture_waypoint_ids: dict[str, list[str]] = defaultdict(list)
    room_fixture_ids: dict[str, list[str]] = defaultdict(list)
    for landmark in static_landmarks:
        if not isinstance(landmark, dict):
            continue
        _add_bundle_static_landmark_indexes(
            landmark=landmark,
            fixture_waypoint_ids=fixture_waypoint_ids,
            room_fixture_ids=room_fixture_ids,
        )
    return fixture_waypoint_ids, room_fixture_ids


def _add_bundle_static_landmark_indexes(
    *,
    landmark: dict[str, Any],
    fixture_waypoint_ids: dict[str, list[str]],
    room_fixture_ids: dict[str, list[str]],
) -> None:
    room_id = str(landmark.get("room_id") or "")
    fixture_id = str(landmark.get("fixture_id") or landmark.get("landmark_id") or "")
    if not fixture_id:
        return
    room_fixture_ids[room_id].append(fixture_id)
    for key in ("preferred_inspection_waypoint_id", "preferred_manipulation_waypoint_id"):
        waypoint_id = str(landmark.get(key) or "")
        if waypoint_id and fixture_id not in fixture_waypoint_ids[waypoint_id]:
            fixture_waypoint_ids[waypoint_id].append(fixture_id)


def _bundle_inspection_waypoint(
    *,
    raw_waypoint: dict[str, Any],
    frame_id: str,
    fixture_waypoint_ids: dict[str, list[str]],
    room_fixture_ids: dict[str, list[str]],
) -> dict[str, Any]:
    waypoint = dict(raw_waypoint)
    waypoint_id = str(waypoint.get("waypoint_id") or "")
    room_id = str(waypoint.get("room_id") or "")
    waypoint.setdefault("frame_id", frame_id)
    waypoint["visited"] = False
    if not waypoint.get("fixture_ids"):
        waypoint["fixture_ids"] = sorted(
            fixture_waypoint_ids.get(waypoint_id) or room_fixture_ids.get(room_id, [])
        )
    return waypoint


def _public_base_waypoints_from_artifact(
    metric_map: dict[str, Any],
    *,
    public_rooms: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    source_waypoints = [
        item for item in metric_map.get("inspection_waypoints") or [] if isinstance(item, dict)
    ]
    if not source_waypoints:
        raise AssertionError("metric map artifact must contain inspection_waypoints")
    frame_id = str(metric_map.get("frame_id") or "map")
    room_labels = _room_label_by_id(public_rooms)
    public_waypoints = []
    for index, source in enumerate(source_waypoints, start=1):
        waypoint = dict(source)
        waypoint_id = str(waypoint.get("waypoint_id") or "")
        if not waypoint_id:
            raise AssertionError("inspection waypoint missing waypoint_id")
        room_id = str(source.get("room_id") or "generated_area")
        room_label = str(room_labels.get(room_id) or source.get("room_label") or "")
        waypoint["waypoint_id"] = waypoint_id
        waypoint.setdefault("frame_id", frame_id)
        waypoint["x"] = float(source.get("x", 0.0))
        waypoint["y"] = float(source.get("y", 0.0))
        waypoint["yaw"] = float(source.get("yaw", 0.0))
        waypoint["room_id"] = room_id
        waypoint["room_label"] = room_label
        waypoint["label"] = f"Generated exploration candidate {int(source['sweep_index'])}"
        waypoint.setdefault("purpose", "base_metric_map_exploration")
        waypoint.setdefault("waypoint_source", "map_artifact_inspection_waypoint")
        waypoint.setdefault("coverage_estimate", round(1.0 / max(len(source_waypoints), 1), 6))
        waypoint.pop("fixture_ids", None)
        public_waypoints.append(waypoint)
    return public_waypoints


def _private_waypoint_map_for_public_base_waypoints(
    public_waypoints: list[dict[str, Any]],
    private_waypoints: list[dict[str, Any]],
) -> dict[str, dict[str, Any]]:
    private_by_id = {str(item.get("waypoint_id") or ""): item for item in private_waypoints}
    return {
        str(public.get("waypoint_id") or ""): private_by_id.get(
            str(public.get("waypoint_id") or ""),
            public,
        )
        for public in public_waypoints
    }


def _assert_no_forbidden_agent_view_keys(payload: Any) -> None:
    if isinstance(payload, dict):
        forbidden = _PROJECTION_FORBIDDEN_AGENT_VIEW_KEYS.intersection(payload)
        if forbidden:
            raise AssertionError(f"forbidden agent-view keys present: {sorted(forbidden)}")
        for value in payload.values():
            _assert_no_forbidden_agent_view_keys(value)
    elif isinstance(payload, list):
        for value in payload:
            _assert_no_forbidden_agent_view_keys(value)
