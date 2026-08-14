from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any, Callable

from roboclaws.household.backend import HELD_LOCATION_ID
from roboclaws.household.manipulation_contract import ISAAC_SEMANTIC_POSE_PROVENANCE
from scripts.isaac_lab_cleanup.isaac_support_surface_geometry import (
    ISAAC_DESCENDANT_SUPPORT_SURFACE_SOURCE,
    ISAAC_WORLD_BOUNDS_SUPPORT_SURFACE_SOURCE,
)

PLACEMENT_DIAGNOSTIC_SCHEMA = "molmospaces_semantic_placement_diagnostic_v1"
ISAAC_PLACEMENT_RESOLVER_SOURCE = "isaac_support_placement_resolver"


@dataclass(frozen=True)
class IsaacPlacementHooks:
    aabb_xy_overlaps: Callable[..., Any]
    binding_for_handle: Callable[..., Any]
    candidate_has_direct_support: Callable[..., Any]
    candidate_is_clear_of_dynamic_objects: Callable[..., Any]
    dict_value: Callable[..., Any]
    direct_support_clearance: Callable[..., Any]
    direct_support_placement: Callable[..., Any]
    elevated_position_over_surface: Callable[..., Any]
    fallback_placement_position: Callable[..., Any]
    index_entry: Callable[..., Any]
    normalize_support_surface: Callable[..., Any]
    norm: Callable[..., Any]
    object_bottom_offset: Callable[..., Any]
    object_current_aabb: Callable[..., Any]
    object_footprint_half_extents: Callable[..., Any]
    object_height: Callable[..., Any]
    object_surface_lift: Callable[..., Any]
    object_usd_prim_path: Callable[..., Any]
    object_world_bounds: Callable[..., Any]
    objects_by_id: Callable[..., Any]
    pose_near: Callable[..., Any]
    receptacle_support_pose: Callable[..., Any]
    receptacle_support_surface: Callable[..., Any]
    receptacle_support_surfaces: Callable[..., Any]
    receptacle_text: Callable[..., Any]
    receptacle_usd_prim_path: Callable[..., Any]
    receptacle_world_bounds: Callable[..., Any]
    receptacles_by_id: Callable[..., Any]
    round_vec3: Callable[..., Any]
    semantic_object_position_from_state: Callable[..., Any]
    state_objects_for_clearance: Callable[..., Any]
    support_pose_position: Callable[..., Any]
    support_surface_from_usd_bounds: Callable[..., Any]
    surface_candidate_positions: Callable[..., Any]
    vec3: Callable[..., Any]


def resolve_isaac_placement(
    state: dict[str, Any],
    *,
    object_id: str,
    receptacle_id: str,
    index: int,
    relation: str,
    source: str,
    hooks: IsaacPlacementHooks,
) -> dict[str, Any]:
    if relation == "on":
        direct = hooks.direct_support_placement(
            state,
            object_id=object_id,
            receptacle_id=receptacle_id,
            index=index,
        )
        if direct is not None:
            direct["source"] = source
            return direct
    position = hooks.fallback_placement_position(
        state,
        object_id=object_id,
        receptacle_id=receptacle_id,
        index=index,
        relation=relation,
    )
    support_status = (
        "semantic_contained_in_receptacle" if relation == "inside" else "degraded_elevated"
    )
    contact_proof = (
        "semantic_containment" if relation == "inside" else "degraded_no_direct_support_surface"
    )
    return {
        "position": position,
        "support_status": support_status,
        "contact_proof": contact_proof,
        "resolution_source": "isaac_category_fallback",
        "candidate_count": 0,
        "degraded": relation == "on",
        "source": source,
    }


def isaac_state_objects_for_clearance(
    state: dict[str, Any],
    *,
    hooks: IsaacPlacementHooks,
) -> dict[str, dict[str, Any]]:
    objects = dict(hooks.objects_by_id(state))
    for object_id, entry in hooks.dict_value(state.get("object_index")).items():
        object_id = str(object_id)
        if object_id in objects:
            continue
        item = hooks.dict_value(entry)
        if not item:
            continue
        objects[object_id] = {
            "object_id": object_id,
            "category": str(item.get("category") or ""),
            "name": str(item.get("public_label") or object_id),
            "location_id": str(item.get("parent") or ""),
            "pickupable": True,
        }
    return objects


def isaac_direct_support_placement(
    state: dict[str, Any],
    *,
    object_id: str,
    receptacle_id: str,
    index: int,
    hooks: IsaacPlacementHooks,
) -> dict[str, Any] | None:
    surfaces = hooks.receptacle_support_surfaces(state, receptacle_id)
    if not surfaces:
        return None
    footprint = hooks.object_footprint_half_extents(state, object_id)
    bottom_offset = hooks.object_bottom_offset(state, object_id)
    clearance = hooks.direct_support_clearance(
        hooks.dict_value(hooks.objects_by_id(state).get(object_id)),
        hooks.dict_value(hooks.receptacles_by_id(state).get(receptacle_id)),
    )
    candidate_count = 0
    for surface in sorted(
        surfaces,
        key=lambda item: (
            float(item.get("area_m2") or 0.0),
            float(item.get("top_z") or 0.0),
        ),
        reverse=True,
    ):
        for candidate in hooks.surface_candidate_positions(
            surface,
            footprint=footprint,
            bottom_offset=bottom_offset,
            clearance=clearance,
            index=index,
        ):
            candidate_count += 1
            if not hooks.candidate_has_direct_support(candidate, surface, footprint):
                continue
            if not hooks.candidate_is_clear_of_dynamic_objects(
                state,
                object_id=object_id,
                position=candidate,
                footprint=footprint,
                bottom_offset=bottom_offset,
            ):
                continue
            return {
                "position": candidate,
                "support_status": "direct_support",
                "contact_proof": "usd_bounds_direct_support",
                "resolution_source": "isaac_support_surface",
                "candidate_count": candidate_count,
                "degraded": False,
                "support_surface": surface,
                "object_bottom_offset_m": round(float(bottom_offset), 6),
                "support_clearance_m": round(float(clearance), 6),
                "object_footprint_half_extents_m": [
                    round(float(footprint[0]), 6),
                    round(float(footprint[1]), 6),
                ],
            }
    surface = surfaces[0]
    return {
        "position": hooks.elevated_position_over_surface(surface, bottom_offset=bottom_offset),
        "support_status": "degraded_elevated",
        "contact_proof": "degraded_no_candidate_inside_support_surface",
        "resolution_source": "isaac_support_surface_elevated_fallback",
        "candidate_count": candidate_count,
        "degraded": True,
        "support_surface": surface,
        "object_bottom_offset_m": round(float(bottom_offset), 6),
        "support_clearance_m": round(float(clearance), 6),
        "object_footprint_half_extents_m": [
            round(float(footprint[0]), 6),
            round(float(footprint[1]), 6),
        ],
    }


def isaac_receptacle_support_surface(
    state: dict[str, Any],
    receptacle_id: str,
    *,
    hooks: IsaacPlacementHooks,
) -> dict[str, Any] | None:
    surfaces = hooks.receptacle_support_surfaces(state, receptacle_id)
    return surfaces[0] if surfaces else None


def isaac_receptacle_support_surfaces(
    state: dict[str, Any],
    receptacle_id: str,
    *,
    hooks: IsaacPlacementHooks,
) -> list[dict[str, Any]]:
    entry = hooks.index_entry(
        state,
        receptacle_id,
        index_name="receptacle_index",
        binding_groups=("selected_target_receptacle_bindings", "receptacle_bindings"),
    )
    surfaces = []
    for surface in entry.get("support_surfaces") or []:
        normalized = hooks.normalize_support_surface(surface)
        if normalized is not None:
            surfaces.append(normalized)
    if surfaces:
        return sorted(
            surfaces,
            key=lambda item: (
                float(item.get("area_m2") or 0.0),
                float(item.get("top_z") or 0.0),
            ),
            reverse=True,
        )
    surface = hooks.support_surface_from_usd_bounds(
        bounds=hooks.dict_value(entry.get("usd_world_bounds")),
        surface_id=hooks.receptacle_usd_prim_path(state, receptacle_id) or receptacle_id,
        source=ISAAC_WORLD_BOUNDS_SUPPORT_SURFACE_SOURCE,
    )
    if surface is not None:
        return [surface]
    support_pose = hooks.receptacle_support_pose(state, receptacle_id)
    center = hooks.support_pose_position(support_pose)
    radius = float(support_pose.get("support_radius_m") or 0.0) if support_pose else 0.0
    if center is None or radius <= 0.0:
        return []
    area = 4.0 * radius * radius
    return [
        {
            "surface_id": hooks.receptacle_usd_prim_path(state, receptacle_id) or receptacle_id,
            "center": [round(float(center[0]), 6), round(float(center[1]), 6)],
            "top_z": round(float(center[2]), 6),
            "half_extents": [round(float(radius), 6), round(float(radius), 6)],
            "area_m2": round(float(area), 6),
            "source": str(support_pose.get("source") or "isaac_support_pose"),
        }
    ]


def normalize_support_surface(surface: Any) -> dict[str, Any] | None:
    raw = dict_value(surface)
    center = raw.get("center")
    half_extents = raw.get("half_extents")
    if not isinstance(center, (list, tuple)) or len(center) < 2:
        return None
    if not isinstance(half_extents, (list, tuple)) or len(half_extents) < 2:
        return None
    try:
        center_xy = [round(float(center[0]), 6), round(float(center[1]), 6)]
        top_z = round(float(raw["top_z"]), 6)
        half_xy = [
            round(abs(float(half_extents[0])), 6),
            round(abs(float(half_extents[1])), 6),
        ]
    except (KeyError, TypeError, ValueError):
        return None
    if min(half_xy) < 0.03:
        return None
    area = float(raw.get("area_m2") or (4.0 * half_xy[0] * half_xy[1]))
    if area <= 0.0:
        return None
    normalized = {
        "surface_id": str(raw.get("surface_id") or ""),
        "center": center_xy,
        "top_z": top_z,
        "half_extents": half_xy,
        "area_m2": round(area, 6),
        "source": str(raw.get("source") or ISAAC_DESCENDANT_SUPPORT_SURFACE_SOURCE),
    }
    if raw.get("selection_score") is not None:
        try:
            normalized["selection_score"] = round(float(raw["selection_score"]), 6)
        except (TypeError, ValueError):
            pass
    return normalized


def surface_candidate_positions(
    surface: dict[str, Any],
    *,
    footprint: tuple[float, float],
    bottom_offset: float,
    clearance: float,
    index: int,
) -> list[list[float]]:
    center = surface["center"]
    half_extents = surface["half_extents"]
    margin_x = float(footprint[0]) + 0.04
    margin_y = float(footprint[1]) + 0.04
    available_x = max(float(half_extents[0]) - margin_x, 0.0)
    available_y = max(float(half_extents[1]) - margin_y, 0.0)
    slot_x = min(available_x * 0.55, 0.28)
    slot_y = min(available_y * 0.55, 0.28)
    offsets = [
        (0.0, 0.0),
        (-slot_x, 0.0),
        (slot_x, 0.0),
        (0.0, -slot_y),
        (0.0, slot_y),
        (-slot_x, -slot_y),
        (slot_x, -slot_y),
        (-slot_x, slot_y),
        (slot_x, slot_y),
    ]
    if len(offsets) > 1:
        shift = index % len(offsets)
        offsets = offsets[shift:] + offsets[:shift]
    z = float(surface["top_z"]) + float(bottom_offset) + float(clearance)
    return [
        [
            round(float(center[0]) + float(dx), 6),
            round(float(center[1]) + float(dy), 6),
            round(z, 6),
        ]
        for dx, dy in offsets
    ]


def candidate_has_direct_support(
    position: list[float],
    surface: dict[str, Any],
    footprint: tuple[float, float],
) -> bool:
    center = surface["center"]
    half_extents = surface["half_extents"]
    margin_x = float(footprint[0]) + 0.015
    margin_y = float(footprint[1]) + 0.015
    return abs(float(position[0]) - float(center[0])) + margin_x <= float(half_extents[0]) and abs(
        float(position[1]) - float(center[1])
    ) + margin_y <= float(half_extents[1])


def isaac_candidate_is_clear_of_dynamic_objects(
    state: dict[str, Any],
    *,
    object_id: str,
    position: list[float],
    footprint: tuple[float, float],
    bottom_offset: float,
    hooks: IsaacPlacementHooks,
) -> bool:
    candidate_bottom = float(position[2]) - float(bottom_offset)
    candidate_height = max(hooks.object_height(state, object_id), 0.04)
    candidate_top = candidate_bottom + candidate_height
    candidate_aabb = {
        "min_x": float(position[0]) - float(footprint[0]),
        "max_x": float(position[0]) + float(footprint[0]),
        "min_y": float(position[1]) - float(footprint[1]),
        "max_y": float(position[1]) + float(footprint[1]),
        "min_z": candidate_bottom,
        "max_z": candidate_top,
    }
    for other_id in hooks.state_objects_for_clearance(state):
        if other_id == object_id:
            continue
        if hooks.dict_value(state.get("locations")).get(other_id) == HELD_LOCATION_ID:
            continue
        other_aabb = hooks.object_current_aabb(state, other_id)
        if other_aabb is None:
            continue
        if not hooks.aabb_xy_overlaps(
            (
                candidate_aabb["min_x"],
                candidate_aabb["max_x"],
                candidate_aabb["min_y"],
                candidate_aabb["max_y"],
            ),
            other_aabb,
            margin=0.025,
        ):
            continue
        if (
            candidate_bottom - 0.015 <= other_aabb["max_z"]
            and candidate_top + 0.015 >= other_aabb["min_z"]
        ):
            return False
    return True


def aabb_xy_overlaps(
    first: tuple[float, float, float, float],
    second: dict[str, float],
    *,
    margin: float,
) -> bool:
    min_x, max_x, min_y, max_y = first
    return (
        min_x - margin <= float(second["max_x"])
        and max_x + margin >= float(second["min_x"])
        and min_y - margin <= float(second["max_y"])
        and max_y + margin >= float(second["min_y"])
    )


def isaac_object_current_aabb(
    state: dict[str, Any],
    object_id: str,
    *,
    hooks: IsaacPlacementHooks,
) -> dict[str, float] | None:
    bounds = hooks.object_world_bounds(state, object_id)
    size = hooks.vec3(hooks.dict_value(bounds).get("size"))
    center = hooks.vec3(hooks.dict_value(bounds).get("center"))
    if center is None or size is None:
        return None
    override = hooks.dict_value(hooks.dict_value(state.get("object_pose_overrides")).get(object_id))
    override_position = hooks.vec3(override.get("position"))
    if override_position is not None:
        center = override_position
    half_x = max(abs(float(size[0])) / 2.0, 0.025)
    half_y = max(abs(float(size[1])) / 2.0, 0.025)
    half_z = max(abs(float(size[2])) / 2.0, 0.02)
    return {
        "min_x": float(center[0]) - half_x,
        "max_x": float(center[0]) + half_x,
        "min_y": float(center[1]) - half_y,
        "max_y": float(center[1]) + half_y,
        "min_z": float(center[2]) - half_z,
        "max_z": float(center[2]) + half_z,
    }


def elevated_position_over_surface(
    surface: dict[str, Any],
    *,
    bottom_offset: float,
) -> list[float]:
    center = surface["center"]
    return [
        round(float(center[0]), 6),
        round(float(center[1]), 6),
        round(float(surface["top_z"]) + float(bottom_offset) + 0.08, 6),
    ]


def isaac_fallback_placement_position(
    state: dict[str, Any],
    *,
    object_id: str,
    receptacle_id: str,
    index: int,
    relation: str,
    hooks: IsaacPlacementHooks,
) -> list[float]:
    receptacle = hooks.dict_value(hooks.receptacles_by_id(state).get(receptacle_id))
    support = hooks.receptacle_support_pose(state, receptacle_id)
    base = hooks.support_pose_position(support)
    if base is None:
        receptacle_bounds = hooks.dict_value(hooks.receptacle_world_bounds(state, receptacle_id))
        base = hooks.vec3(receptacle_bounds.get("center"))
    if base is None:
        pose = hooks.pose_near(receptacle_id)
        base = [float(pose["x"]), float(pose["y"]), float(pose.get("z", 0.0))]
    text = hooks.receptacle_text(receptacle)
    if relation == "inside" and ("fridge" in text or "refrigerator" in text):
        return hooks.round_vec3([base[0] + 0.08, base[1] - 0.16, base[2] + 0.35])
    offset = ((index % 3) - 1) * 0.12
    y_offset = 0.08 * (index % 2)
    object_entry = hooks.dict_value(hooks.objects_by_id(state).get(object_id))
    category = str(object_entry.get("category") or "")
    if hooks.norm(category) in {"apple", "food"}:
        y_offset = 0.16
    return hooks.round_vec3([base[0] + offset, base[1] + y_offset, base[2] + 0.18])


def isaac_object_footprint_half_extents(
    state: dict[str, Any],
    object_id: str,
    *,
    hooks: IsaacPlacementHooks,
) -> tuple[float, float]:
    size = hooks.vec3(hooks.dict_value(hooks.object_world_bounds(state, object_id)).get("size"))
    if size is not None:
        return (max(abs(float(size[0])) / 2.0, 0.025), max(abs(float(size[1])) / 2.0, 0.025))
    object_entry = hooks.dict_value(hooks.objects_by_id(state).get(object_id))
    category = hooks.norm(object_entry.get("category"))
    if category in {"remotecontrol", "remote", "electronics"}:
        return (0.09, 0.045)
    if category in {"plate", "dish"}:
        return (0.13, 0.13)
    if category in {"apple", "potato", "food"}:
        return (0.065, 0.065)
    if category == "book":
        return (0.12, 0.08)
    if category == "pillow":
        return (0.22, 0.16)
    return (0.08, 0.08)


def isaac_object_bottom_offset(
    state: dict[str, Any],
    object_id: str,
    *,
    hooks: IsaacPlacementHooks,
) -> float:
    entry = hooks.index_entry(
        state,
        object_id,
        index_name="object_index",
        binding_groups=("selected_object_bindings", "object_bindings"),
    )
    bounds = hooks.dict_value(entry.get("usd_world_bounds"))
    root_position = hooks.vec3(entry.get("usd_world_root_position"))
    min_point = hooks.vec3(bounds.get("min"))
    if root_position is not None and min_point is not None:
        offset = float(root_position[2]) - float(min_point[2])
        if 0.0 < offset <= 1.0:
            return max(offset, 0.01)
    center = hooks.vec3(bounds.get("center"))
    if center is not None and min_point is not None:
        offset = float(center[2]) - float(min_point[2])
        if 0.0 < offset <= 1.0:
            return max(offset, 0.01)
    object_entry = hooks.dict_value(hooks.objects_by_id(state).get(object_id))
    return hooks.object_surface_lift(object_entry.get("category"))


def isaac_object_height(
    state: dict[str, Any],
    object_id: str,
    *,
    hooks: IsaacPlacementHooks,
) -> float:
    size = hooks.vec3(hooks.dict_value(hooks.object_world_bounds(state, object_id)).get("size"))
    if size is not None:
        return max(abs(float(size[2])), 0.01)
    object_entry = hooks.dict_value(hooks.objects_by_id(state).get(object_id))
    return hooks.object_surface_lift(object_entry.get("category"))


def isaac_object_surface_lift(category: Any, *, norm: Callable[..., Any]) -> float:
    normalized = norm(category)
    if normalized in {"book", "plate", "remotecontrol", "remote", "electronics"}:
        return 0.04
    if normalized in {"apple", "potato", "food"}:
        return 0.08
    if normalized == "pillow":
        return 0.12
    return 0.06


def isaac_direct_support_clearance(
    obj: dict[str, Any],
    receptacle: dict[str, Any],
    *,
    norm: Callable[..., Any],
    receptacle_text: Callable[..., Any],
) -> float:
    receptacle_text_value = receptacle_text(receptacle)
    object_category = norm(obj.get("category"))
    if "bed" in receptacle_text_value or "sofa" in receptacle_text_value:
        return 0.035
    if object_category in {"book", "plate", "remotecontrol", "remote", "electronics"}:
        return 0.02
    return 0.015


def isaac_object_world_bounds(
    state: dict[str, Any],
    object_id: str,
    *,
    hooks: IsaacPlacementHooks,
) -> dict[str, Any]:
    return hooks.dict_value(
        hooks.index_entry(
            state,
            object_id,
            index_name="object_index",
            binding_groups=("selected_object_bindings", "object_bindings"),
        ).get("usd_world_bounds")
    )


def isaac_receptacle_world_bounds(
    state: dict[str, Any],
    receptacle_id: str,
    *,
    hooks: IsaacPlacementHooks,
) -> dict[str, Any]:
    return hooks.dict_value(
        hooks.index_entry(
            state,
            receptacle_id,
            index_name="receptacle_index",
            binding_groups=("selected_target_receptacle_bindings", "receptacle_bindings"),
        ).get("usd_world_bounds")
    )


def isaac_index_entry(
    state: dict[str, Any],
    public_id: str,
    *,
    index_name: str,
    binding_groups: tuple[str, ...],
    hooks: IsaacPlacementHooks,
) -> dict[str, Any]:
    binding = hooks.binding_for_handle(
        state.get("scene_binding_diagnostics"),
        public_id,
        binding_groups,
    )
    index = hooks.dict_value(state.get(index_name))
    for handle in (binding.get("usd_handle"), public_id):
        entry = hooks.dict_value(index.get(str(handle)))
        if entry:
            return entry
    return {}


def isaac_placement_diagnostic(
    *,
    state: dict[str, Any],
    object_id: str,
    receptacle_id: str,
    relation: str,
    source: str,
    placement_index: int | None = None,
    placement_resolution: dict[str, Any] | None = None,
    hooks: IsaacPlacementHooks,
) -> dict[str, Any]:
    obj = hooks.dict_value(hooks.objects_by_id(state).get(object_id))
    receptacle = hooks.dict_value(hooks.receptacles_by_id(state).get(receptacle_id))
    placement_resolution = placement_resolution or {}
    requested_position = hooks.vec3(placement_resolution.get("position")) or []
    object_position = requested_position or hooks.semantic_object_position_from_state(
        state,
        object_id=object_id,
        location_id=str(hooks.dict_value(state.get("locations")).get(object_id) or ""),
        original_location_id=str(obj.get("location_id") or ""),
        support_receptacle_id=receptacle_id,
    )
    if object_position is None:
        object_position = []
    receptacle_pose = hooks.receptacle_support_pose(state, receptacle_id)
    receptacle_position = hooks.support_pose_position(receptacle_pose)
    if receptacle_position is None:
        receptacle_position = hooks.vec3(
            hooks.dict_value(hooks.receptacle_world_bounds(state, receptacle_id)).get("center")
        )
    if receptacle_position is None:
        receptacle_position = []
    xy_distance = (
        math.dist(object_position[:2], receptacle_position[:2])
        if len(object_position) >= 2 and len(receptacle_position) >= 2
        else None
    )
    z_delta = (
        float(object_position[2]) - float(receptacle_position[2])
        if len(object_position) >= 3 and len(receptacle_position) >= 3
        else None
    )
    default_support_status = (
        "semantic_contained_in_receptacle" if relation == "inside" else "semantic_on_receptacle"
    )
    support_status = str(placement_resolution.get("support_status") or default_support_status)
    diagnostic = {
        "schema": PLACEMENT_DIAGNOSTIC_SCHEMA,
        "status": support_status,
        "object_id": object_id,
        "object_category": obj.get("category"),
        "object_usd_prim_path": hooks.object_usd_prim_path(state, object_id),
        "receptacle_id": receptacle_id,
        "receptacle_category": receptacle.get("category") or receptacle.get("kind"),
        "receptacle_usd_prim_path": hooks.receptacle_usd_prim_path(state, receptacle_id),
        "relation": relation,
        "placement_index": placement_index,
        "requested_position": hooks.round_vec3(requested_position) if requested_position else [],
        "object_position": hooks.round_vec3(object_position) if object_position else [],
        "receptacle_position": hooks.round_vec3(receptacle_position) if receptacle_position else [],
        "xy_distance_m": round(float(xy_distance), 6) if xy_distance is not None else None,
        "z_delta_m": round(float(z_delta), 6) if z_delta is not None else None,
        "support_status": support_status,
        "placement_support_status": support_status,
        "direct_support_proven": support_status == "direct_support",
        "contact_proof": str(
            placement_resolution.get("contact_proof") or "not_measured_isaac_semantic_pose"
        ),
        "diagnostic_source": source,
        "resolution_source": placement_resolution.get("resolution_source", "isaac_semantic"),
        "candidate_count": int(placement_resolution.get("candidate_count") or 0),
        "degraded": bool(placement_resolution.get("degraded", False)),
        "state_mutation": "isaac_prim_transform",
        "primitive_provenance": ISAAC_SEMANTIC_POSE_PROVENANCE,
        "planner_backed": False,
        "physical_robot": False,
    }
    support_surface = placement_resolution.get("support_surface")
    if isinstance(support_surface, dict):
        diagnostic["support_surface_id"] = support_surface.get("surface_id")
        diagnostic["support_surface_center"] = support_surface.get("center")
        diagnostic["support_surface_half_extents"] = support_surface.get("half_extents")
        diagnostic["support_surface_top_z"] = support_surface.get("top_z")
        diagnostic["support_surface_source"] = support_surface.get("source")
        if support_surface.get("member_count") is not None:
            diagnostic["support_surface_member_count"] = support_surface.get("member_count")
    for key in (
        "object_bottom_offset_m",
        "support_clearance_m",
        "object_footprint_half_extents_m",
    ):
        if placement_resolution.get(key) is not None:
            diagnostic[key] = placement_resolution[key]
    return diagnostic


def dict_value(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}
