"""Isaac Lab backend runtime support."""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any, Callable

from roboclaws.backends.isaaclab.isaac_support_surface_geometry import (
    ISAAC_DESCENDANT_SUPPORT_SURFACE_SOURCE,
    ISAAC_DESCENDANT_SUPPORT_SURFACE_UNION_SOURCE,
    ISAAC_WORLD_BOUNDS_SUPPORT_SURFACE_SOURCE,
)
from roboclaws.household.camera_control import MOLMOSPACES_SCENE_FRAME
from roboclaws.household.robot_view_pose import resolve_cleanup_robot_pose


@dataclass(frozen=True)
class IsaacRobotPoseHooks:
    binding_for_handle: Callable[..., Any]
    dict_value: Callable[..., Any]
    has_xy: Callable[..., Any]
    optional_float: Callable[..., Any]
    pose_near: Callable[..., Any]
    receptacle_support_pose: Callable[..., Any]
    receptacles_by_id: Callable[..., Any]
    round_vec3: Callable[..., Any]
    scene_index_center_xy: Callable[..., Any]
    semantic_object_pose_entry: Callable[..., Any]
    support_pose_position: Callable[..., Any]
    vec3: Callable[..., Any]


def target_room_id_from_pose_inputs(
    state: dict[str, Any],
    receptacle_id: str,
    support: dict[str, Any],
    *,
    hooks: IsaacRobotPoseHooks,
) -> str | None:
    scenario_receptacle = (
        hooks.dict_value(hooks.receptacles_by_id(state).get(receptacle_id))
        if isinstance(state.get("scenario"), dict)
        else {}
    )
    room_area = str(scenario_receptacle.get("room_area") or "")
    if room_area.startswith("room_"):
        return room_area
    metadata_room_id = str(support.get("metadata_room_id") or "")
    if metadata_room_id:
        return (
            metadata_room_id if metadata_room_id.startswith("room_") else f"room_{metadata_room_id}"
        )
    target = hooks.support_pose_position(support)
    if target is None:
        return None
    for outline in state.get("room_outlines") or []:
        center = outline.get("center")
        half_extents = outline.get("half_extents")
        if not isinstance(center, list | tuple) or not isinstance(half_extents, list | tuple):
            continue
        inside_x = (
            float(center[0]) - float(half_extents[0])
            <= target[0]
            <= float(center[0]) + float(half_extents[0])
        )
        inside_y = (
            float(center[1]) - float(half_extents[1])
            <= target[1]
            <= float(center[1]) + float(half_extents[1])
        )
        if inside_x and inside_y:
            return str(outline.get("room_id") or "") or None
    return None


def robot_pose_for_receptacle(
    state: dict[str, Any],
    receptacle_id: str,
    *,
    hooks: IsaacRobotPoseHooks,
) -> dict[str, Any]:
    support = receptacle_support_pose(state, receptacle_id, hooks=hooks)
    if not support:
        pose = hooks.pose_near(receptacle_id)
        pose["pose_source"] = "hash_fallback_pose_near_receptacle"
        return pose
    x = float(support["x"])
    y = float(support["y"])
    z = float(support.get("z", 0.0))
    pose = resolve_cleanup_robot_pose(
        target_position=[x, y, z],
        target_room_id=target_room_id_from_pose_inputs(
            state,
            receptacle_id,
            support,
            hooks=hooks,
        ),
        target_receptacle_id=receptacle_id,
        room_outlines=state.get("room_outlines") or [],
        scene_center=hooks.scene_index_center_xy(state),
        stand_off_m=1.15,
        frame=MOLMOSPACES_SCENE_FRAME,
    )
    pose["support_pose_source"] = str(support.get("source") or "")
    return pose


def robot_pose_for_waypoint(
    waypoint: dict[str, Any],
    *,
    hooks: IsaacRobotPoseHooks,
) -> dict[str, Any]:
    for key in ("b1_pose", "robot_pose"):
        pose = hooks.dict_value(waypoint.get(key))
        if hooks.has_xy(pose):
            result = normalized_waypoint_robot_pose(
                pose,
                waypoint=waypoint,
                pose_source=str(pose.get("pose_source") or key),
                hooks=hooks,
            )
            result["waypoint_pose_key"] = key
            return result
    if not hooks.has_xy(waypoint):
        return {}
    return normalized_waypoint_robot_pose(
        waypoint,
        waypoint=waypoint,
        pose_source=str(waypoint.get("pose_source") or "public_waypoint_map_frame"),
        hooks=hooks,
    )


def normalized_waypoint_robot_pose(
    pose: dict[str, Any],
    *,
    waypoint: dict[str, Any],
    pose_source: str,
    hooks: IsaacRobotPoseHooks,
) -> dict[str, Any]:
    x = hooks.optional_float(pose.get("x"))
    y = hooks.optional_float(pose.get("y"))
    if x is None or y is None:
        return {}
    yaw = hooks.optional_float(pose.get("yaw"))
    yaw_deg = hooks.optional_float(pose.get("yaw_deg"))
    if yaw_deg is None and yaw is not None:
        yaw_deg = math.degrees(yaw)
    result: dict[str, Any] = {
        "frame": str(
            pose.get("frame") or pose.get("frame_id") or waypoint.get("frame_id") or "map"
        ),
        "x": round(float(x), 6),
        "y": round(float(y), 6),
        "z": round(float(hooks.optional_float(pose.get("z")) or 0.0), 6),
        "pose_source": pose_source,
        "waypoint_id": str(waypoint.get("waypoint_id") or ""),
        "room_id": str(waypoint.get("room_id") or ""),
    }
    if yaw_deg is not None:
        result["yaw_deg"] = round(float(yaw_deg), 6)
    if yaw is not None:
        result["theta"] = round(float(yaw), 6)
    target = hooks.vec3(pose.get("target_position"))
    if target is not None:
        result["target_position"] = hooks.round_vec3(target)
    fixture_ids = [str(item) for item in waypoint.get("fixture_ids") or [] if str(item)]
    if fixture_ids:
        result["fixture_ids"] = fixture_ids
    if pose.get("support_pose_source") is not None:
        result["support_pose_source"] = str(pose.get("support_pose_source"))
    return result


def receptacle_support_pose(
    state: dict[str, Any],
    receptacle_id: str,
    *,
    hooks: IsaacRobotPoseHooks,
) -> dict[str, Any]:
    binding = hooks.binding_for_handle(
        state.get("scene_binding_diagnostics"),
        receptacle_id,
        ("selected_target_receptacle_bindings", "receptacle_bindings"),
    )
    for handle in (binding.get("usd_handle"), receptacle_id):
        entry = hooks.dict_value(hooks.dict_value(state.get("receptacle_index")).get(str(handle)))
        support_pose = hooks.dict_value(entry.get("support_pose"))
        if hooks.has_xy(support_pose) and support_pose.get("source") in {
            "usd_world_bounds_top_center",
            ISAAC_DESCENDANT_SUPPORT_SURFACE_SOURCE,
            ISAAC_DESCENDANT_SUPPORT_SURFACE_UNION_SOURCE,
            ISAAC_WORLD_BOUNDS_SUPPORT_SURFACE_SOURCE,
        }:
            metadata_room_id = entry.get("metadata_room_id")
            if metadata_room_id is not None:
                support_pose["metadata_room_id"] = metadata_room_id
            return support_pose
    return {}


def binding_for_handle(
    scene_binding_diagnostics: Any,
    handle: str,
    groups: tuple[str, ...],
    *,
    dict_value: Callable[..., Any],
) -> dict[str, Any]:
    bindings = dict_value(scene_binding_diagnostics)
    for group in groups:
        item = dict_value(dict_value(bindings.get(group)).get(handle))
        if item:
            return item
    return {}


def scene_index_center_xy(
    state: dict[str, Any],
    *,
    dict_value: Callable[..., Any],
    vec3: Callable[..., Any],
) -> tuple[float, float]:
    centers: list[list[float]] = []
    for index_name in ("receptacle_index", "object_index"):
        for entry in dict_value(state.get(index_name)).values():
            center = vec3(dict_value(dict_value(entry).get("usd_world_bounds")).get("center"))
            if center is not None:
                centers.append(center)
    if not centers:
        return (0.0, 0.0)
    return (
        sum(center[0] for center in centers) / len(centers),
        sum(center[1] for center in centers) / len(centers),
    )


def robot_view_focus(
    state: dict[str, Any],
    robot_pose: dict[str, Any],
    *,
    focus_object_id: str | None,
    focus_receptacle_id: str | None,
    hooks: IsaacRobotPoseHooks,
) -> dict[str, Any]:
    focus = focus_payload(
        state=state,
        focus_object_id=focus_object_id,
        focus_receptacle_id=focus_receptacle_id,
        hooks=hooks,
    )
    target = hooks.vec3(focus.get("focus_position"))
    source = str(focus.get("source") or "")
    if target is None:
        target = hooks.vec3(robot_pose.get("target_position"))
        source = "isaac_usd_world_bounds_robot_pose"
    if target is None:
        target = [0.0, 0.0, 0.0]
        source = "isaac_semantic_pose_default_origin"
    return {
        **focus,
        "has_focus": True,
        "focus_position": target,
        "object_id": focus_object_id,
        "receptacle_id": focus_receptacle_id,
        "source": source,
    }


def focus_payload(
    *,
    state: dict[str, Any] | None = None,
    focus_object_id: str | None,
    focus_receptacle_id: str | None,
    hooks: IsaacRobotPoseHooks,
) -> dict[str, Any]:
    state = state if isinstance(state, dict) else {}
    object_pose = (
        hooks.semantic_object_pose_entry(state, focus_object_id) if focus_object_id else {}
    )
    receptacle_pose = (
        hooks.receptacle_support_pose(state, focus_receptacle_id) if focus_receptacle_id else {}
    )
    object_position = hooks.vec3(object_pose.get("position"))
    receptacle_position = hooks.support_pose_position(receptacle_pose)
    focus_position = (
        object_position
        if object_position is not None
        else receptacle_position
        if receptacle_position is not None
        else None
    )
    has_focus = bool(focus_object_id or focus_receptacle_id)
    focus_mode = "object_closeup" if object_position is not None else "receptacle_context"
    source = (
        "isaac_semantic_pose_object_pose"
        if object_position is not None
        else "isaac_usd_world_bounds_support_pose"
        if receptacle_position is not None
        else "isaac_semantic_pose"
    )
    segmentation_unavailable = {
        "status": "segmentation_unavailable",
        "reason": "Isaac semantic-pose worker has no segmentation mask evidence.",
    }
    return {
        "has_focus": has_focus,
        "object_id": focus_object_id,
        "receptacle_id": focus_receptacle_id,
        "source": source,
        "focus_mode": focus_mode,
        "focus_position": focus_position,
        "object_position": object_position,
        "receptacle_position": receptacle_position,
        "visibility": dict(segmentation_unavailable),
        "fpv_visibility": dict(segmentation_unavailable),
    }


def semantic_object_pose_entry(
    state: dict[str, Any],
    object_id: str | None,
    *,
    dict_value: Callable[..., Any],
) -> dict[str, Any]:
    if not object_id:
        return {}
    semantic_pose = dict_value(state.get("semantic_pose_state"))
    object_poses = dict_value(semantic_pose.get("object_poses"))
    return dict_value(object_poses.get(object_id))


def support_pose_position(
    pose: dict[str, Any],
    *,
    has_xy: Callable[..., Any],
) -> list[float] | None:
    if not has_xy(pose):
        return None
    try:
        return [
            float(pose["x"]),
            float(pose["y"]),
            float(pose.get("z", 0.0)),
        ]
    except (TypeError, ValueError):
        return None
