from __future__ import annotations

import math
from typing import Any

from roboclaws.household.robot_view_pose import (
    angle_delta,
    point_inside_room_outline,
    resolve_cleanup_robot_pose,
    robot_head_pitch_for_target,
    room_for_point,
    room_outline_clearance,
)


def robot_pose_near_receptacle(
    state: dict[str, Any],
    receptacle: dict[str, Any],
) -> dict[str, Any]:
    target = receptacle["position"]
    target_room_id = target_room_id_for_receptacle(state, receptacle)
    pose = robot_pose_near_position(
        state,
        target,
        target_room_id=target_room_id,
        target_receptacle_id=receptacle["receptacle_id"],
    )
    pose["robot_room_id"] = pose.get("robot_room_id")
    pose.update(room_relation_payload(state, receptacle, [pose["x"], pose["y"]]))
    return pose


def robot_pose_for_open_receptacle(
    state: dict[str, Any],
    receptacle: dict[str, Any],
) -> dict[str, Any]:
    if receptacle.get("category") != "Fridge":
        return robot_pose_near_receptacle(state, receptacle)

    base = receptacle["position"]
    target_room_id = target_room_id_for_receptacle(state, receptacle)
    candidates = [
        (float(base[0]) - 0.76, float(base[1]) + 0.20),
        (float(base[0]) - 0.72, float(base[1]) + 0.36),
        (float(base[0]) - 0.90, float(base[1]) + 0.08),
    ]
    x, y = first_same_room_point(state, candidates, target_room_id)
    target = [float(base[0]), float(base[1]), float(base[2]) + 0.35]
    theta = math.atan2(target[1] - y, target[0] - x)
    pose = {
        "x": round(float(x), 6),
        "y": round(float(y), 6),
        "z": 0.0,
        "theta": round(float(theta), 6),
        "theta_source": "opened_receptacle_access_yaw",
        "head_yaw": 0.0,
        "head_yaw_source": "base_yaw_handles_target_bearing",
        "head_pitch": robot_head_pitch_for_target_value(target, [x, y]),
        "head_pitch_source": "target_framing_head_pitch",
        "target_receptacle_id": receptacle["receptacle_id"],
        "robot_room_id": room_for_state_point(state, [x, y]) or target_room_id,
    }
    pose.update(room_relation_payload(state, receptacle, [pose["x"], pose["y"]]))
    return {key: value for key, value in pose.items() if value is not None}


def first_same_room_point(
    state: dict[str, Any],
    candidates: list[tuple[float, float]],
    target_room_id: str | None,
) -> tuple[float, float]:
    for x, y in candidates:
        if room_for_state_point(state, [x, y]) == target_room_id:
            return x, y
    return candidates[0]


def robot_pose_near_object(
    state: dict[str, Any],
    obj: dict[str, Any],
    *,
    source_receptacle_id: str | None = None,
) -> dict[str, Any]:
    target = obj["position"]
    source_receptacle = state["receptacles"].get(
        source_receptacle_id or obj.get("seeded_start_receptacle_id", "")
    )
    source_room_id = (
        target_room_id_for_receptacle(state, source_receptacle) if source_receptacle else None
    )
    target_room_id = room_for_state_point(state, target) or source_room_id
    pose = robot_pose_near_position(
        state,
        target,
        target_room_id=target_room_id,
        target_object_id=obj["object_id"],
    )
    robot_room_id = pose.get("robot_room_id")
    pose.update(
        {
            "target_room_id": target_room_id,
            "same_room_as_target": robot_room_id == target_room_id,
            "room_plausibility": "same_room"
            if robot_room_id == target_room_id
            else "room_mismatch",
        }
    )
    return pose


def robot_pose_for_waypoint(
    state: dict[str, Any],
    waypoint: dict[str, Any],
    target: list[float],
) -> dict[str, Any]:
    room_id = str(waypoint.get("room_id") or "")
    room_outline = room_outline_for_id(state, room_id)
    scene_focus = room_outline_center_xy(room_outline) or scene_center(
        list(state["receptacles"].values())
    )
    theta = math.atan2(float(scene_focus[1]) - target[1], float(scene_focus[0]) - target[0])
    head_target = [float(scene_focus[0]), float(scene_focus[1]), 1.2]
    robot_room_id = room_for_state_point(state, target) or room_id
    return {
        "x": round(target[0], 6),
        "y": round(target[1], 6),
        "z": 0.0,
        "theta": round(float(theta), 6),
        "theta_source": "waypoint_room_outline_focus_yaw",
        "head_yaw": 0.0,
        "head_yaw_source": "base_yaw_handles_waypoint_focus",
        "head_pitch": robot_head_pitch_for_target_value(head_target, [target[0], target[1]]),
        "head_pitch_source": "room_center_framing_head_pitch",
        "target_waypoint_id": str(waypoint.get("waypoint_id") or ""),
        "target_room_id": room_id,
        "robot_room_id": robot_room_id,
        "same_room_as_target": robot_room_id == room_id,
        "room_plausibility": "same_room" if robot_room_id == room_id else "room_mismatch",
        "pose_source": "waypoint_room_outline_projection",
        "target_position": [round(target[0], 6), round(target[1], 6), round(target[2], 6)],
        "pose_request": {
            "schema": "cleanup_waypoint_pose_request_v1",
            "waypoint_id": str(waypoint.get("waypoint_id") or ""),
            "room_id": room_id,
            "waypoint_xy": [float(waypoint.get("x", 0.0)), float(waypoint.get("y", 0.0))],
            "source_room_bounds": waypoint.get("source_room_bounds") or {},
            "room_outline": room_outline or {},
            "resolver": "roboclaws.cleanup_robot_pose.waypoint_room_projection_v1",
        },
    }


def waypoint_target_position(
    state: dict[str, Any],
    waypoint: dict[str, Any],
) -> list[float]:
    room_id = str(waypoint.get("room_id") or "")
    outline = room_outline_for_id(state, room_id)
    if outline is None:
        return [float(waypoint.get("x", 0.0)), float(waypoint.get("y", 0.0)), 0.0]
    center = outline.get("center") or [0.0, 0.0]
    half_extents = outline.get("half_extents") or [1.0, 1.0]
    bounds = waypoint.get("source_room_bounds") or {}
    source_min_x = float_or_zero(bounds.get("min_x"))
    source_max_x = float_or_zero(bounds.get("max_x"))
    source_min_y = float_or_zero(bounds.get("min_y"))
    source_max_y = float_or_zero(bounds.get("max_y"))
    source_width = source_max_x - source_min_x
    source_height = source_max_y - source_min_y
    if source_width <= 0.001 or source_height <= 0.001:
        nx = 0.5
        ny = 0.5
    else:
        nx = (float(waypoint.get("x", 0.0)) - source_min_x) / source_width
        ny = (float(waypoint.get("y", 0.0)) - source_min_y) / source_height
    nx = min(max(nx, 0.08), 0.92)
    ny = min(max(ny, 0.08), 0.92)
    margin = 0.35
    half_x = max(float(half_extents[0]) - margin, 0.1)
    half_y = max(float(half_extents[1]) - margin, 0.1)
    x = float(center[0]) + (nx - 0.5) * 2.0 * half_x
    y = float(center[1]) + (ny - 0.5) * 2.0 * half_y
    return [round(x, 6), round(y, 6), 0.0]


def room_outline_center_xy(outline: dict[str, Any] | None) -> tuple[float, float] | None:
    if outline is None:
        return None
    center = outline.get("center")
    if not isinstance(center, list | tuple) or len(center) < 2:
        return None
    return (float(center[0]), float(center[1]))


def robot_pose_near_position(
    state: dict[str, Any],
    target: list[float],
    *,
    target_room_id: str | None,
    target_receptacle_id: str | None = None,
    target_object_id: str | None = None,
) -> dict[str, Any]:
    stand_off = robot_stand_off_for_target(state, target_object_id)
    pose = resolve_cleanup_robot_pose(
        target_position=target,
        target_room_id=target_room_id,
        target_receptacle_id=target_receptacle_id,
        target_object_id=target_object_id,
        room_outlines=state.get("room_outlines") or [],
        scene_center=scene_center(list(state["receptacles"].values())),
        stand_off_m=stand_off,
    )
    return {key: value for key, value in pose.items() if value is not None}


def robot_stand_off_for_target(state: dict[str, Any], target_object_id: str | None) -> float:
    obj = state.get("objects", {}).get(target_object_id or "")
    if not obj:
        return 1.15
    if obj.get("category") == "RemoteControl":
        return 0.85
    if obj.get("category") == "Apple":
        return 1.0
    return 1.15


def robot_head_pitch_for_target_value(target: list[float], robot_xy: list[float]) -> float:
    return robot_head_pitch_for_target(target, robot_xy)


def scene_center(items: list[dict[str, Any]]) -> tuple[float, float]:
    if not items:
        return (0.0, 0.0)
    return (
        sum(float(item["position"][0]) for item in items) / len(items),
        sum(float(item["position"][1]) for item in items) / len(items),
    )


def room_relation_payload(
    state: dict[str, Any],
    receptacle: dict[str, Any],
    robot_point: list[float],
) -> dict[str, Any]:
    target_room_id = target_room_id_for_receptacle(state, receptacle)
    robot_room_id = room_for_state_point(state, robot_point)
    same_room = robot_room_id == target_room_id
    return {
        "target_room_id": target_room_id,
        "same_room_as_target": same_room,
        "room_relation_source": "mujoco_room_outline",
        "room_plausibility": "same_room" if same_room else "room_mismatch",
    }


def target_room_id_for_receptacle(state: dict[str, Any], receptacle: dict[str, Any]) -> str:
    return room_for_state_point(state, receptacle["position"]) or str(
        receptacle.get("room_area") or "room_unknown"
    )


def room_outline_for_id(
    state: dict[str, Any],
    room_id: Any,
) -> dict[str, Any] | None:
    if room_id is None:
        return None
    for outline in state.get("room_outlines", []):
        if str(outline.get("room_id") or "") == str(room_id):
            return outline
    return None


def room_for_state_point(state: dict[str, Any], point: list[float]) -> str | None:
    return room_for_point(state.get("room_outlines") or [], point)


def point_inside_outline(
    point: list[float],
    outline: dict[str, Any],
    *,
    margin: float,
) -> bool:
    return point_inside_room_outline(point, outline, margin=margin)


def outline_clearance(point: list[float], outline: dict[str, Any] | None) -> float:
    return room_outline_clearance(point, outline)


def angle_delta_value(a: float, b: float) -> float:
    return angle_delta(a, b)


def float_or_zero(value: Any) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0
