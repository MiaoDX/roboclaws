from __future__ import annotations

import copy
from pathlib import Path
from typing import Any

from roboclaws.maps.b1_map12_label_geometry import (
    SourceMapTransform,
    _resolve_map_anchor,
    _room_centers_by_id,
    world_to_pixel,
)
from roboclaws.maps.navigation_memory import (
    navigation_memory_item,
    navigation_memory_items,
    navigation_memory_point_source,
    read_navigation_memory,
)


def source_map_layers_from_semantics(
    semantics: dict[str, Any],
    *,
    transform: SourceMapTransform,
    frame_id: str,
) -> dict[str, Any]:
    room_centers = _room_centers_by_id(semantics)
    fixtures, fixture_centers = _fixture_layer_rows(
        semantics,
        transform=transform,
        frame_id=frame_id,
    )
    waypoints, waypoint_centers = _inspection_waypoint_layer_rows(
        semantics,
        transform=transform,
        frame_id=frame_id,
    )
    driveable_ways = _driveable_way_layer_rows(
        semantics,
        transform=transform,
        room_centers=room_centers,
        waypoint_centers=waypoint_centers,
        fixture_centers=fixture_centers,
    )
    return {
        "coordinate_policy": "map_native_layers_use_source_map_frame_coordinates_only",
        "fixtures": fixtures,
        "inspection_waypoints": waypoints,
        "driveable_ways": driveable_ways,
    }


def _fixture_layer_rows(
    semantics: dict[str, Any],
    *,
    transform: SourceMapTransform,
    frame_id: str,
) -> tuple[list[dict[str, Any]], dict[str, dict[str, float]]]:
    fixture_centers: dict[str, dict[str, float]] = {}
    fixtures = []
    for raw_fixture in semantics.get("fixtures") or []:
        if not isinstance(raw_fixture, dict):
            continue
        pose = raw_fixture.get("pose") if isinstance(raw_fixture.get("pose"), dict) else {}
        center = _source_frame_point(pose, frame_id=frame_id)
        if center is None:
            continue
        fixture_id = str(raw_fixture.get("fixture_id") or "")
        if fixture_id:
            fixture_centers[fixture_id] = center
        fixtures.append(
            {
                "fixture_id": fixture_id,
                "label": str(raw_fixture.get("label") or raw_fixture.get("name") or fixture_id),
                "name": str(raw_fixture.get("name") or ""),
                "category": str(raw_fixture.get("category") or ""),
                "room_id": str(raw_fixture.get("room_id") or ""),
                "pose": {
                    "frame_id": frame_id,
                    "x": center["x"],
                    "y": center["y"],
                    "yaw": float(pose.get("yaw") or 0.0),
                },
                "pixel_center": world_to_pixel(center["x"], center["y"], transform),
                "footprint": copy.deepcopy(raw_fixture.get("footprint") or {}),
                "affordances": list(raw_fixture.get("affordances") or []),
                "position_detail": str(raw_fixture.get("position_detail") or ""),
                "coordinate_status": "source_map_frame_coordinate",
            }
        )
    return fixtures, fixture_centers


def _inspection_waypoint_layer_rows(
    semantics: dict[str, Any],
    *,
    transform: SourceMapTransform,
    frame_id: str,
) -> tuple[list[dict[str, Any]], dict[str, dict[str, float]]]:
    waypoint_centers: dict[str, dict[str, float]] = {}
    waypoints = []
    for raw_waypoint in semantics.get("inspection_waypoints") or []:
        if not isinstance(raw_waypoint, dict):
            continue
        center = _source_frame_point(raw_waypoint, frame_id=frame_id)
        if center is None:
            continue
        waypoint_id = str(raw_waypoint.get("waypoint_id") or "")
        if waypoint_id:
            waypoint_centers[waypoint_id] = center
        waypoints.append(
            {
                "waypoint_id": waypoint_id,
                "label": str(raw_waypoint.get("label") or waypoint_id),
                "room_id": str(raw_waypoint.get("room_id") or ""),
                "navigation_area_id": str(raw_waypoint.get("navigation_area_id") or ""),
                "fixture_id": str(raw_waypoint.get("fixture_id") or ""),
                "purpose": str(raw_waypoint.get("purpose") or ""),
                "reachability_status": str(raw_waypoint.get("reachability_status") or ""),
                "pose": {
                    "frame_id": frame_id,
                    "x": center["x"],
                    "y": center["y"],
                    "yaw": float(raw_waypoint.get("yaw") or 0.0),
                },
                "pixel_center": world_to_pixel(center["x"], center["y"], transform),
                "coordinate_status": "source_map_frame_coordinate",
            }
        )
    return waypoints, waypoint_centers


def _driveable_way_layer_rows(
    semantics: dict[str, Any],
    *,
    transform: SourceMapTransform,
    room_centers: dict[str, dict[str, float]],
    waypoint_centers: dict[str, dict[str, float]],
    fixture_centers: dict[str, dict[str, float]],
) -> list[dict[str, Any]]:
    driveable_ways = []
    for raw_way in semantics.get("driveable_ways") or []:
        if not isinstance(raw_way, dict):
            continue
        from_id = str(raw_way.get("from_room_id") or raw_way.get("from_waypoint_id") or "")
        to_id = str(raw_way.get("to_room_id") or raw_way.get("to_waypoint_id") or "")
        start = _resolve_map_anchor(
            from_id,
            room_centers=room_centers,
            waypoint_centers=waypoint_centers,
            fixture_centers=fixture_centers,
        )
        end = _resolve_map_anchor(
            to_id,
            room_centers=room_centers,
            waypoint_centers=waypoint_centers,
            fixture_centers=fixture_centers,
        )
        item = {
            "from_id": from_id,
            "to_id": to_id,
            "raw": copy.deepcopy(raw_way),
            "coordinate_status": "resolved_from_source_map_anchors",
        }
        if start and end:
            item.update(
                {
                    "from_kind": start["kind"],
                    "to_kind": end["kind"],
                    "from_center": start["center"],
                    "to_center": end["center"],
                    "from_pixel": world_to_pixel(
                        start["center"]["x"],
                        start["center"]["y"],
                        transform,
                    ),
                    "to_pixel": world_to_pixel(end["center"]["x"], end["center"]["y"], transform),
                }
            )
        driveable_ways.append(item)
    return driveable_ways


def _source_frame_point(payload: dict[str, Any], *, frame_id: str) -> dict[str, float] | None:
    if str(payload.get("frame_id") or frame_id) != frame_id:
        return None
    try:
        return {"x": float(payload["x"]), "y": float(payload["y"])}
    except (KeyError, TypeError, ValueError):
        return None


def navigation_memory_layer_from_path(
    navigation_memory_path: Path,
    *,
    transform: SourceMapTransform,
    frame_id: str,
) -> dict[str, Any]:
    path = Path(navigation_memory_path)
    payload = read_navigation_memory(path)
    items = [
        item
        for item in (
            navigation_memory_layer_item(
                navigation_memory_item(raw_item, index=index),
                index=index,
                transform=transform,
                frame_id=frame_id,
            )
            for index, raw_item in enumerate(navigation_memory_items(payload), start=1)
        )
        if item is not None
    ]
    if not items:
        raise ValueError(f"navigation_memory.json did not yield any label-layer items: {path}")
    return {
        "schema": "robot_map12_navigation_memory_layer_v1",
        "source": str(path),
        "coordinate_policy": "navigation_memory_pose_and_nav_goal_are_map_frame_priors",
        "items": items,
    }


def navigation_memory_layer_item(
    item: dict[str, Any],
    *,
    index: int,
    transform: SourceMapTransform,
    frame_id: str,
) -> dict[str, Any] | None:
    item_id = str(item.get("id") or f"navigation_memory_{index:03d}")
    pose = _navigation_memory_point(
        item.get("pose"),
        transform=transform,
        frame_id=frame_id,
        label=f"navigation_memory.json item {item_id} pose",
    )
    nav_goal = _navigation_memory_point(
        item.get("nav_goal"),
        transform=transform,
        frame_id=frame_id,
        label=f"navigation_memory.json item {item_id} nav_goal",
    )
    if pose is None and nav_goal is None:
        raise ValueError(f"navigation_memory.json item {item_id} must include pose or nav_goal")
    return {
        "id": item_id,
        "label": str(item.get("label") or item_id),
        "kind": str(item.get("kind") or ""),
        "scene_id": str(item.get("scene_id") or ""),
        "pose": pose,
        "nav_goal": nav_goal,
        "source": str(item.get("source") or ""),
        "confidence": _optional_float(item.get("confidence")),
        "coordinate_status": "map_frame_prior",
    }


def _navigation_memory_point(
    payload: Any,
    *,
    transform: SourceMapTransform,
    frame_id: str,
    label: str,
) -> dict[str, Any] | None:
    source = navigation_memory_point_source(payload, label=label, required=False)
    if not source:
        return None
    x = source["x"]
    y = source["y"]
    return {
        "frame_id": frame_id,
        "x": x,
        "y": y,
        "yaw": source.get("yaw"),
        "pixel_center": world_to_pixel(x, y, transform),
    }


def _optional_float(value: Any) -> float | None:
    try:
        return None if value is None else float(value)
    except (TypeError, ValueError):
        return None
