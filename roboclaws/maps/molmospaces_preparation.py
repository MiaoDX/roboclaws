from __future__ import annotations

from pathlib import Path
from typing import Any

from roboclaws.maps.base_waypoints import BaseWaypointBuilder, BaseWaypointBuilderConfig
from roboclaws.maps.bundle import DEFAULT_ROBOT_PROFILE, metric_map_bundle_metadata
from roboclaws.maps.rasterize import occupancy_grid_from_metric_map
from roboclaws.maps.spatial_contract import (
    ALIGNMENT_STATUS_NATIVE,
    GEOMETRY_SOURCE_SCENE_ENGINE_PARTITION,
    POLYGON_ROLE_NAVIGATION_AREA,
    source_frame_spatial_contract,
)

BASE_METRIC_MAP_CONTRACT_SCHEMA = "base_metric_map_v1"
MOLMOSPACES_BASE_METRIC_PREPARATION_SCHEMA = "molmospaces_base_metric_map_preparation_v1"

_SEMANTIC_CATEGORY_RULES: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("kitchen", ("kitchen",)),
    ("living_room", ("living", "lounge")),
    ("dining_area", ("dining",)),
    ("bedroom", ("bed",)),
    ("bathroom", ("bath", "toilet")),
    ("corridor", ("corridor", "hall")),
    ("entry", ("entry", "foyer")),
    ("storage", ("storage", "closet")),
    ("utility", ("utility", "laundry")),
    ("meeting_room", ("meeting", "conference")),
)


def prepare_molmospaces_base_metric_map(
    *,
    backend_state: dict[str, Any],
    scene_source: str,
    scene_index: int,
    environment_id: str,
    map_id: str,
    map_version: str = "base-metric-map-v1",
    source_path: Path | str | None = None,
) -> dict[str, Any]:
    """Prepare a strict fixture-free Base Metric Map from simulator source evidence."""

    frame_id = "map"
    rooms = _navigation_areas_from_backend_state(backend_state, frame_id=frame_id)
    metric_map = {
        "schema": MOLMOSPACES_BASE_METRIC_PREPARATION_SCHEMA,
        "frame_id": frame_id,
        "map_id": map_id,
        "map_version": map_version,
        "resolution_m": 0.05,
        "origin": _origin_for_rooms(rooms),
        "width": 240,
        "height": 180,
        "occupancy_values": {"unknown": -1, "free": 0, "occupied": 100},
        "map_bundle": metric_map_bundle_metadata(
            environment_id=environment_id,
            map_id=map_id,
            map_version=map_version,
        ),
        "rooms": rooms,
        "inspection_waypoints": [],
        "driveable_ways": [
            {"from_room_id": room["room_id"], "to_room_id": room["room_id"]} for room in rooms
        ],
        "base_metric_map_contract": {
            "schema": BASE_METRIC_MAP_CONTRACT_SCHEMA,
            "navigation_area_count": len(rooms),
            "semantic_label_count": len(rooms),
            "inspection_waypoint_count": 0,
            "waypoint_generation_policy": "base_navigation_area_centroid_clearance_v1",
            "consumer_scope": "sim_real_robot_and_digital_twin",
        },
        "provenance": {
            "source": "molmospaces_scene_source_map_preparation",
            "scene_source": scene_source,
            "scene_index": int(scene_index),
            "source_artifact": f"molmospaces://{scene_source}/{int(scene_index)}",
            "room_label_source": "molmospaces_scene_room_outlines",
            "contains_static_fixtures": False,
            "contains_receptacles": False,
            "contains_movable_objects": False,
            "contains_runtime_observations": False,
            "contains_private_scoring_truth": False,
            "uses_navigation_memory_as_waypoint_source": False,
        },
    }
    grid = occupancy_grid_from_metric_map(metric_map, [])
    waypoints = BaseWaypointBuilder(
        grid=grid,
        config=BaseWaypointBuilderConfig(
            frame_id=frame_id,
            clearance_radius_m=float(DEFAULT_ROBOT_PROFILE["footprint"]["radius_m"]),
        ),
    ).build(rooms)
    metric_map["inspection_waypoints"] = waypoints
    metric_map["base_metric_map_contract"] = {
        **metric_map["base_metric_map_contract"],
        "inspection_waypoint_count": len(waypoints),
    }
    return metric_map


def _navigation_areas_from_backend_state(
    backend_state: dict[str, Any],
    *,
    frame_id: str,
) -> list[dict[str, Any]]:
    room_outlines = [
        item for item in backend_state.get("room_outlines") or [] if isinstance(item, dict)
    ]
    if not room_outlines:
        raise ValueError("MolmoSpaces source-map preparation requires room_outlines")
    rooms: list[dict[str, Any]] = []
    for index, outline in enumerate(room_outlines, start=1):
        room_id = str(outline.get("room_id") or f"room_{index}")
        label = str(outline.get("room_label") or outline.get("label") or room_id.replace("_", " "))
        polygon = _polygon_from_outline(outline)
        if len(polygon) < 3:
            raise ValueError(f"MolmoSpaces room outline {room_id} has no source-frame polygon")
        rooms.append(
            {
                "room_id": room_id,
                "navigation_area_id": room_id,
                "map_area_id": room_id,
                "room_label": label,
                "category": _semantic_category_from_label(
                    label,
                    room_id=room_id,
                    room_type=str(outline.get("room_type") or ""),
                ),
                "polygon": polygon,
                "source_map_frame_id": frame_id,
                "polygon_role": POLYGON_ROLE_NAVIGATION_AREA,
                "geometry_source": GEOMETRY_SOURCE_SCENE_ENGINE_PARTITION,
                "alignment_status": ALIGNMENT_STATUS_NATIVE,
                "polygon_usage": {
                    "navigation": True,
                    "semantic_labeling": "accepted",
                    "review": True,
                },
                "semantic_source": str(
                    outline.get("room_label_provenance") or "molmospaces_scene_room_outline"
                ),
                "label_source": str(
                    outline.get("room_label_provenance") or "molmospaces_scene_room_outline"
                ),
                "source_label_id": room_id,
                "source_polygon_index": index,
                "review_status": "accepted",
            }
        )
    return rooms


def _polygon_from_outline(outline: dict[str, Any]) -> list[dict[str, float]]:
    center = outline.get("center") if isinstance(outline.get("center"), list) else []
    half_extents = (
        outline.get("half_extents") if isinstance(outline.get("half_extents"), list) else []
    )
    if len(center) < 2 or len(half_extents) < 2:
        return []
    cx = float(center[0])
    cy = float(center[1])
    hx = abs(float(half_extents[0]))
    hy = abs(float(half_extents[1]))
    return [
        {"x": round(cx - hx, 6), "y": round(cy - hy, 6)},
        {"x": round(cx + hx, 6), "y": round(cy - hy, 6)},
        {"x": round(cx + hx, 6), "y": round(cy + hy, 6)},
        {"x": round(cx - hx, 6), "y": round(cy + hy, 6)},
    ]


def _origin_for_rooms(rooms: list[dict[str, Any]]) -> dict[str, float]:
    xs = [
        float(point["x"])
        for room in rooms
        for point in room.get("polygon") or []
        if isinstance(point, dict) and "x" in point
    ]
    ys = [
        float(point["y"])
        for room in rooms
        for point in room.get("polygon") or []
        if isinstance(point, dict) and "y" in point
    ]
    min_x = min(xs) if xs else 0.0
    min_y = min(ys) if ys else 0.0
    return {
        "x": round(min(0.0, min_x - 0.5), 3),
        "y": round(min(0.0, min_y - 0.5), 3),
        "yaw": 0.0,
    }


def _semantic_category_from_label(label: str, *, room_id: str, room_type: str) -> str:
    text = f"{label} {room_id} {room_type}".lower().replace("_", " ")
    for category, terms in _SEMANTIC_CATEGORY_RULES:
        if any(term in text for term in terms):
            return category
    return "open_area"


def base_metric_spatial_contract(frame_id: str = "map") -> dict[str, Any]:
    return source_frame_spatial_contract(
        frame_id=frame_id,
        alignment_status=ALIGNMENT_STATUS_NATIVE,
    )
