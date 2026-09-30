from __future__ import annotations

import math
from typing import Any

CLEANUP_ROBOT_POSE_REQUEST_SCHEMA = "cleanup_robot_pose_request_v1"
CLEANUP_ROBOT_POSE_RESULT_SCHEMA = "cleanup_robot_pose_result_v1"
CLEANUP_ROBOT_POSE_RESOLVER = "roboclaws.cleanup_robot_pose.near_target_v1"
CLEANUP_ROBOT_POSE_SOURCE = "roboclaws_shared_scene_frame_support_pose"


def cleanup_robot_pose_request(
    *,
    target_position: list[float] | tuple[float, ...],
    target_room_id: str | None = None,
    target_receptacle_id: str | None = None,
    target_object_id: str | None = None,
    room_outlines: list[dict[str, Any]] | None = None,
    scene_center: list[float] | tuple[float, ...] | None = None,
    stand_off_m: float = 1.15,
    frame: str = "molmospaces_scene_frame_v1",
) -> dict[str, Any]:
    return {
        "schema": CLEANUP_ROBOT_POSE_REQUEST_SCHEMA,
        "resolver": CLEANUP_ROBOT_POSE_RESOLVER,
        "frame": frame,
        "target_position": _round_vec3(target_position),
        "target_room_id": target_room_id,
        "target_receptacle_id": target_receptacle_id,
        "target_object_id": target_object_id,
        "stand_off_m": float(stand_off_m),
        "scene_center": _round_xy(scene_center) if scene_center is not None else None,
        "room_outline_count": len(room_outlines or []),
        "room_outline_source": _room_outline_source(room_outlines or []),
    }


def resolve_cleanup_robot_pose(
    *,
    target_position: list[float] | tuple[float, ...],
    target_room_id: str | None = None,
    target_receptacle_id: str | None = None,
    target_object_id: str | None = None,
    room_outlines: list[dict[str, Any]] | None = None,
    scene_center: list[float] | tuple[float, ...] | None = None,
    stand_off_m: float = 1.15,
    frame: str = "molmospaces_scene_frame_v1",
) -> dict[str, Any]:
    request = cleanup_robot_pose_request(
        target_position=target_position,
        target_room_id=target_room_id,
        target_receptacle_id=target_receptacle_id,
        target_object_id=target_object_id,
        room_outlines=room_outlines,
        scene_center=scene_center,
        stand_off_m=stand_off_m,
        frame=frame,
    )
    target = _vec3(target_position)
    center = _vec2(scene_center) if scene_center is not None else None
    if center is None:
        center = _scene_center_from_outlines(room_outlines or []) or (0.0, 0.0)
    preferred_angle = math.atan2(center[1] - target[1], center[0] - target[0])
    target_room = _room_outline_for_id(room_outlines or [], target_room_id)
    candidate_angles = [preferred_angle] + [index * math.tau / 24.0 for index in range(24)]
    candidates = []
    for angle in candidate_angles:
        x = target[0] + math.cos(angle) * float(stand_off_m)
        y = target[1] + math.sin(angle) * float(stand_off_m)
        robot_room = _room_for_point(room_outlines or [], [x, y])
        same_room = robot_room == target_room_id
        inside_target_room = target_room is not None and _point_inside_outline(
            [x, y],
            target_room,
            margin=0.08,
        )
        clearance = _outline_clearance([x, y], target_room) if target_room is not None else 0.0
        angle_penalty = _angle_delta(angle, preferred_angle)
        candidates.append(
            (
                1 if same_room or inside_target_room else 0,
                clearance,
                -angle_penalty,
                x,
                y,
                robot_room,
            )
        )
    _, clearance, _, x, y, robot_room = max(candidates)
    theta = math.atan2(target[1] - y, target[0] - x)
    head_pitch = robot_head_pitch_for_target(target, [x, y])
    return {
        "schema": CLEANUP_ROBOT_POSE_RESULT_SCHEMA,
        "frame": frame,
        "x": round(float(x), 6),
        "y": round(float(y), 6),
        "z": 0.0,
        "theta": round(float(theta), 6),
        "yaw_deg": round(math.degrees(theta), 6),
        "theta_source": "target_facing_base_yaw",
        "head_yaw": 0.0,
        "head_yaw_source": "base_yaw_handles_target_bearing",
        "head_pitch": head_pitch,
        "head_pitch_source": "target_framing_head_pitch",
        "target_position": _round_vec3(target),
        "target_receptacle_id": target_receptacle_id,
        "target_object_id": target_object_id,
        "target_room_id": target_room_id,
        "robot_room_id": robot_room,
        "same_room_as_target": robot_room == target_room_id if target_room_id else None,
        "room_relation_source": "shared_room_outline" if room_outlines else "missing_room_outline",
        "room_plausibility": "same_room"
        if target_room_id and robot_room == target_room_id
        else "room_mismatch"
        if target_room_id
        else "unknown",
        "room_clearance_m": round(float(clearance), 6),
        "pose_source": CLEANUP_ROBOT_POSE_SOURCE,
        "pose_request": request,
    }


def robot_head_pitch_for_target(
    target: list[float] | tuple[float, ...],
    robot_xy: list[float] | tuple[float, ...],
) -> float:
    target_vec = _vec3(target)
    robot = _vec2(robot_xy)
    horizontal = math.hypot(target_vec[0] - robot[0], target_vec[1] - robot[1])
    horizontal = max(horizontal, 0.25)
    camera_height = 1.55
    focus_height = target_vec[2] + 0.2
    pitch = math.atan2(camera_height - focus_height, horizontal)
    return round(max(0.25, min(0.75, pitch)), 6)


def room_for_point(
    room_outlines: list[dict[str, Any]] | None,
    point: list[float] | tuple[float, ...],
) -> str | None:
    return _room_for_point(room_outlines or [], point)


def point_inside_room_outline(
    point: list[float] | tuple[float, ...],
    outline: dict[str, Any],
    *,
    margin: float,
) -> bool:
    return _point_inside_outline(point, outline, margin=margin)


def room_outline_clearance(
    point: list[float] | tuple[float, ...],
    outline: dict[str, Any] | None,
) -> float:
    return _outline_clearance(point, outline)


def angle_delta(a: float, b: float) -> float:
    return _angle_delta(a, b)


def _room_outline_for_id(
    room_outlines: list[dict[str, Any]],
    room_id: Any,
) -> dict[str, Any] | None:
    if room_id is None:
        return None
    for outline in room_outlines:
        if outline.get("room_id") == room_id:
            return outline
    return None


def _room_for_point(
    room_outlines: list[dict[str, Any]],
    point: list[float] | tuple[float, ...],
) -> str | None:
    containing = [
        outline for outline in room_outlines if _point_inside_outline(point, outline, margin=0.0)
    ]
    if not containing:
        return None
    return max(containing, key=lambda outline: _outline_clearance(point, outline)).get("room_id")


def _point_inside_outline(
    point: list[float] | tuple[float, ...],
    outline: dict[str, Any],
    *,
    margin: float,
) -> bool:
    center = outline["center"]
    half_x, half_y = outline["half_extents"]
    return (
        float(center[0]) - float(half_x) + margin
        <= float(point[0])
        <= float(center[0]) + float(half_x) - margin
        and float(center[1]) - float(half_y) + margin
        <= float(point[1])
        <= float(center[1]) + float(half_y) - margin
    )


def _outline_clearance(
    point: list[float] | tuple[float, ...],
    outline: dict[str, Any] | None,
) -> float:
    if outline is None:
        return 0.0
    center = outline["center"]
    half_x, half_y = outline["half_extents"]
    return min(
        float(point[0]) - (float(center[0]) - float(half_x)),
        (float(center[0]) + float(half_x)) - float(point[0]),
        float(point[1]) - (float(center[1]) - float(half_y)),
        (float(center[1]) + float(half_y)) - float(point[1]),
    )


def _angle_delta(a: float, b: float) -> float:
    return abs((a - b + math.pi) % math.tau - math.pi)


def _scene_center_from_outlines(
    room_outlines: list[dict[str, Any]],
) -> tuple[float, float] | None:
    weighted_x = 0.0
    weighted_y = 0.0
    total_weight = 0.0
    for outline in room_outlines:
        center = outline.get("center")
        half_extents = outline.get("half_extents")
        if not isinstance(center, list | tuple) or not isinstance(half_extents, list | tuple):
            continue
        weight = max(float(half_extents[0]) * float(half_extents[1]) * 4.0, 0.001)
        weighted_x += float(center[0]) * weight
        weighted_y += float(center[1]) * weight
        total_weight += weight
    if total_weight <= 0:
        return None
    return (weighted_x / total_weight, weighted_y / total_weight)


def _room_outline_source(room_outlines: list[dict[str, Any]]) -> str:
    sources = sorted(
        {
            str(outline.get("provenance") or outline.get("source") or "")
            for outline in room_outlines
            if isinstance(outline, dict)
        }
    )
    return ",".join(source for source in sources if source)


def _vec2(values: list[float] | tuple[float, ...]) -> tuple[float, float]:
    return (float(values[0]), float(values[1]))


def _vec3(values: list[float] | tuple[float, ...]) -> tuple[float, float, float]:
    return (float(values[0]), float(values[1]), float(values[2]) if len(values) > 2 else 0.0)


def _round_xy(values: list[float] | tuple[float, ...]) -> list[float]:
    return [round(float(values[0]), 6), round(float(values[1]), 6)]


def _round_vec3(values: list[float] | tuple[float, ...]) -> list[float]:
    return [
        round(float(values[0]), 6),
        round(float(values[1]), 6),
        round(float(values[2]) if len(values) > 2 else 0.0, 6),
    ]
