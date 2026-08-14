"""Isaac Lab backend runtime support."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class IsaacSemanticPoseProjectionHooks:
    dict_value: Callable[..., dict[str, Any]]
    robot_pose_for_receptacle: Callable[..., dict[str, Any]]
    round_vec3: Callable[..., list[float]]
    semantic_pose_target_position: Callable[..., tuple[float, float, float] | None]
    vec3: Callable[..., list[float] | None]


def semantic_object_poses_from_state(
    state: dict[str, Any],
    *,
    hooks: IsaacSemanticPoseProjectionHooks,
    held_location_id: str,
    state_source: str,
) -> dict[str, dict[str, Any]]:
    poses: dict[str, dict[str, Any]] = {}
    locations = state.get("locations") or {}
    containment = state.get("containment") or {}
    current_receptacle_id = str(state.get("current_receptacle_id") or "")
    for item in hooks.dict_value(state.get("scenario")).get("objects", []):
        if not isinstance(item, dict):
            continue
        object_id = str(item.get("object_id") or "")
        if not object_id:
            continue
        location_id = str(locations.get(object_id) or item.get("location_id") or "")
        support_receptacle_id = (
            current_receptacle_id if location_id == held_location_id else location_id
        )
        relation = hooks.dict_value(containment.get(object_id)).get("location_relation") or "on"
        pose_override = hooks.dict_value(
            hooks.dict_value(state.get("object_pose_overrides")).get(object_id)
        )
        position = semantic_object_position_from_state(
            state,
            object_id=object_id,
            location_id=location_id,
            original_location_id=str(item.get("location_id") or ""),
            support_receptacle_id=support_receptacle_id,
            hooks=hooks,
            held_location_id=held_location_id,
        )
        position_source = semantic_object_position_source(
            position,
            location_id=location_id,
            original_location_id=str(item.get("location_id") or ""),
            pose_override=pose_override,
            hooks=hooks,
            held_location_id=held_location_id,
        )
        poses[object_id] = {
            "object_id": object_id,
            "usd_prim_path": object_usd_prim_path(state, object_id, hooks=hooks),
            "location_id": location_id,
            "support_receptacle_id": support_receptacle_id,
            "support_usd_prim_path": receptacle_usd_prim_path(
                state,
                support_receptacle_id,
                hooks=hooks,
            ),
            "attached_to_robot": location_id == held_location_id,
            "location_relation": relation,
            "position": position,
            "position_source": position_source,
            "state_source": state_source,
            "rendered_to_usd": False,
        }
        if pose_override:
            poses[object_id]["placement_support_status"] = pose_override.get("support_status")
            poses[object_id]["placement_contact_proof"] = pose_override.get("contact_proof")
            poses[object_id]["placement_resolution_source"] = pose_override.get("resolution_source")
    return poses


def semantic_object_position_from_state(
    state: dict[str, Any],
    *,
    object_id: str,
    location_id: str,
    original_location_id: str,
    support_receptacle_id: str,
    hooks: IsaacSemanticPoseProjectionHooks,
    held_location_id: str,
) -> list[float] | None:
    if location_id != held_location_id:
        pose_override = hooks.dict_value(
            hooks.dict_value(state.get("object_pose_overrides")).get(object_id)
        )
        override_position = hooks.vec3(pose_override.get("position"))
        if override_position is not None:
            return hooks.round_vec3(override_position)
    if location_id == original_location_id:
        bounds_position = object_usd_world_bounds_center(state, object_id, hooks=hooks)
        if bounds_position is not None:
            return bounds_position
    if location_id == held_location_id:
        robot_pose = hooks.robot_pose_for_receptacle(
            state,
            str(state.get("current_receptacle_id") or support_receptacle_id),
        )
        held_target = hooks.vec3(robot_pose.get("target_position"))
        if held_target is not None:
            return hooks.round_vec3(held_target)
    target = hooks.semantic_pose_target_position(
        support_id=support_receptacle_id,
        receptacle_index=hooks.dict_value(state.get("receptacle_index")),
        fallback_pose={},
    )
    if target is not None:
        return hooks.round_vec3(list(target))
    return object_usd_world_bounds_center(state, object_id, hooks=hooks)


def semantic_object_position_source(
    position: list[float] | None,
    *,
    location_id: str,
    original_location_id: str,
    pose_override: dict[str, Any] | None = None,
    hooks: IsaacSemanticPoseProjectionHooks,
    held_location_id: str,
) -> str:
    if position is None:
        return ""
    if hooks.vec3(hooks.dict_value(pose_override).get("position")) is not None and (
        location_id != held_location_id
    ):
        return str(
            hooks.dict_value(pose_override).get("position_source")
            or "isaac_support_placement_resolver"
        )
    if location_id == held_location_id:
        return "isaac_robot_target_position"
    if location_id == original_location_id:
        return "usd_world_bounds_center"
    return "isaac_support_pose_semantic_location"


def object_usd_world_bounds_center(
    state: dict[str, Any],
    object_id: str,
    *,
    hooks: IsaacSemanticPoseProjectionHooks,
) -> list[float] | None:
    binding = binding_for_handle(
        state.get("scene_binding_diagnostics"),
        object_id,
        ("selected_object_bindings", "object_bindings"),
        hooks=hooks,
    )
    for handle in (binding.get("usd_handle"), object_id):
        entry = hooks.dict_value(hooks.dict_value(state.get("object_index")).get(str(handle)))
        center = hooks.vec3(hooks.dict_value(entry.get("usd_world_bounds")).get("center"))
        if center is not None:
            return hooks.round_vec3(center)
    return None


def semantic_articulations_from_state(
    state: dict[str, Any],
    *,
    hooks: IsaacSemanticPoseProjectionHooks,
    state_source: str,
) -> dict[str, dict[str, Any]]:
    open_ids = set(state.get("open_receptacle_ids") or [])
    articulations: dict[str, dict[str, Any]] = {}
    for item in hooks.dict_value(state.get("scenario")).get("receptacles", []):
        if not isinstance(item, dict):
            continue
        receptacle_id = str(item.get("receptacle_id") or "")
        if not receptacle_id:
            continue
        opened = receptacle_id in open_ids
        articulations[receptacle_id] = {
            "receptacle_id": receptacle_id,
            "usd_prim_path": receptacle_usd_prim_path(state, receptacle_id, hooks=hooks),
            "open": opened,
            "joint_state": "open" if opened else "closed",
            "state_source": state_source,
            "rendered_to_usd": False,
        }
    return articulations


def object_usd_prim_path(
    state: dict[str, Any],
    object_id: str,
    *,
    hooks: IsaacSemanticPoseProjectionHooks,
) -> str:
    return binding_usd_prim_path(
        state.get("scene_binding_diagnostics"),
        object_id,
        ("selected_object_bindings", "object_bindings"),
        hooks=hooks,
    ) or index_usd_prim_path(state.get("object_index"), object_id, hooks=hooks)


def receptacle_usd_prim_path(
    state: dict[str, Any],
    receptacle_id: str,
    *,
    hooks: IsaacSemanticPoseProjectionHooks,
) -> str:
    return binding_usd_prim_path(
        state.get("scene_binding_diagnostics"),
        receptacle_id,
        ("selected_target_receptacle_bindings", "receptacle_bindings"),
        hooks=hooks,
    ) or index_usd_prim_path(state.get("receptacle_index"), receptacle_id, hooks=hooks)


def binding_usd_prim_path(
    scene_binding_diagnostics: Any,
    public_id: str,
    binding_keys: tuple[str, ...],
    *,
    hooks: IsaacSemanticPoseProjectionHooks,
) -> str:
    if not public_id:
        return ""
    diagnostics = hooks.dict_value(scene_binding_diagnostics)
    for key in binding_keys:
        binding = hooks.dict_value(hooks.dict_value(diagnostics.get(key)).get(public_id))
        if binding.get("status") == "bound" and binding.get("usd_prim_path"):
            return str(binding["usd_prim_path"])
    return ""


def binding_for_handle(
    scene_binding_diagnostics: Any,
    handle: str,
    groups: tuple[str, ...],
    *,
    hooks: IsaacSemanticPoseProjectionHooks,
) -> dict[str, Any]:
    diagnostics = hooks.dict_value(scene_binding_diagnostics)
    for group in groups:
        binding = hooks.dict_value(hooks.dict_value(diagnostics.get(group)).get(handle))
        if binding:
            return binding
    return {}


def index_usd_prim_path(
    index: Any,
    handle: str,
    *,
    hooks: IsaacSemanticPoseProjectionHooks,
) -> str:
    if not handle:
        return ""
    entry = hooks.dict_value(hooks.dict_value(index).get(handle))
    return str(entry.get("usd_prim_path") or "")
