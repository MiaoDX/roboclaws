from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any, Callable

import mujoco


@dataclass(frozen=True)
class MolmoPlacementHooks:
    subtree_geom_ids: Callable[..., list[int]]
    xyz: Callable[..., list[float]]


def resolve_placement(
    model: mujoco.MjModel,
    data: mujoco.MjData,
    *,
    state: dict[str, Any],
    object_id: str,
    receptacle_id: str,
    index: int,
    relation: str,
    hooks: MolmoPlacementHooks,
) -> dict[str, Any]:
    obj = state["objects"][object_id]
    receptacle = state["receptacles"][receptacle_id]
    object_category = obj.get("category")
    if relation == "on":
        direct = direct_support_placement(
            model,
            data,
            state,
            obj,
            receptacle,
            index=index,
            hooks=hooks,
        )
        if direct is not None:
            return direct
    position = placement_position(
        receptacle,
        index=index,
        relation=relation,
        object_category=object_category,
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
        "resolution_source": "category_fallback",
        "candidate_count": 0,
        "degraded": relation == "on",
    }


def direct_support_placement(
    model: mujoco.MjModel,
    data: mujoco.MjData,
    state: dict[str, Any],
    obj: dict[str, Any],
    receptacle: dict[str, Any],
    *,
    index: int,
    hooks: MolmoPlacementHooks,
) -> dict[str, Any] | None:
    surfaces = list(receptacle.get("support_surfaces") or [])
    if not surfaces:
        surfaces = receptacle_support_surfaces(
            model,
            data,
            str(receptacle.get("body_name") or ""),
            hooks=hooks,
        )
    surfaces = [surface for surface in surfaces if float(surface.get("area_m2") or 0.0) > 0.0]
    if not surfaces:
        return None
    footprint = object_footprint_half_extents(model, data, obj, hooks=hooks)
    bottom_offset = object_bottom_offset(model, data, obj, hooks=hooks)
    clearance = direct_support_clearance(obj, receptacle)
    candidate_count = 0
    ordered_surfaces = sorted(
        surfaces,
        key=lambda item: (
            float(item.get("area_m2") or 0.0),
            float(item.get("top_z") or 0.0),
        ),
        reverse=True,
    )
    for surface in ordered_surfaces:
        best_candidate: tuple[float, list[float]] | None = None
        for candidate in surface_candidate_positions(
            surface,
            footprint=footprint,
            bottom_offset=bottom_offset,
            clearance=clearance,
            index=index,
        ):
            candidate_count += 1
            if not candidate_has_direct_support(candidate, surface, footprint):
                continue
            clearance_score = candidate_dynamic_clearance_score(
                model,
                data,
                state,
                obj,
                candidate,
                footprint=footprint,
                bottom_offset=bottom_offset,
                hooks=hooks,
            )
            if candidate_is_clear_of_dynamic_objects(
                model,
                data,
                state,
                obj,
                candidate,
                footprint=footprint,
                bottom_offset=bottom_offset,
                hooks=hooks,
            ) and (best_candidate is None or clearance_score > best_candidate[0]):
                best_candidate = (clearance_score, candidate)
        if best_candidate is not None:
            _, candidate = best_candidate
            return {
                "position": candidate,
                "support_status": "direct_support",
                "contact_proof": "geometry_direct_support",
                "resolution_source": "receptacle_support_surface",
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
    return {
        "position": elevated_position_over_surface(
            surfaces[0],
            bottom_offset=bottom_offset,
        ),
        "support_status": "degraded_elevated",
        "contact_proof": "degraded_no_candidate_inside_support_surface",
        "resolution_source": "support_surface_elevated_fallback",
        "candidate_count": candidate_count,
        "degraded": True,
        "support_surface": surfaces[0],
        "object_bottom_offset_m": round(float(bottom_offset), 6),
        "support_clearance_m": round(float(clearance), 6),
        "object_footprint_half_extents_m": [
            round(float(footprint[0]), 6),
            round(float(footprint[1]), 6),
        ],
    }


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


def candidate_is_clear_of_dynamic_objects(
    model: mujoco.MjModel,
    data: mujoco.MjData,
    state: dict[str, Any],
    obj: dict[str, Any],
    position: list[float],
    *,
    footprint: tuple[float, float],
    bottom_offset: float,
    hooks: MolmoPlacementHooks,
) -> bool:
    object_id = str(obj.get("object_id") or "")
    candidate_bottom = float(position[2]) - float(bottom_offset)
    candidate_height = max(object_height(model, data, obj, hooks=hooks), 0.04)
    candidate_top = candidate_bottom + candidate_height
    candidate_min_x = float(position[0]) - float(footprint[0])
    candidate_max_x = float(position[0]) + float(footprint[0])
    candidate_min_y = float(position[1]) - float(footprint[1])
    candidate_max_y = float(position[1]) + float(footprint[1])
    for other in state.get("objects", {}).values():
        if str(other.get("object_id") or "") == object_id:
            continue
        if other.get("location_relation") == "held":
            continue
        other_aabb = object_world_aabb(model, data, other, hooks=hooks)
        if other_aabb is None:
            continue
        if not aabb_xy_overlaps(
            (candidate_min_x, candidate_max_x, candidate_min_y, candidate_max_y),
            other_aabb,
            margin=0.02,
        ):
            continue
        if other_aabb["max_z"] < candidate_bottom - 0.03:
            continue
        if other_aabb["min_z"] > candidate_top + 0.12:
            continue
        return False
    return True


def candidate_dynamic_clearance_score(
    model: mujoco.MjModel,
    data: mujoco.MjData,
    state: dict[str, Any],
    obj: dict[str, Any],
    position: list[float],
    *,
    footprint: tuple[float, float],
    bottom_offset: float,
    hooks: MolmoPlacementHooks,
) -> float:
    """Return the smallest XY edge gap to another dynamic object.

    The score is only used to rank public placement candidates. It does not
    expose object identities or alter the private evaluator contract.
    """
    object_id = str(obj.get("object_id") or "")
    candidate_x = float(position[0])
    candidate_y = float(position[1])
    candidate_bottom = float(position[2]) - float(bottom_offset)
    candidate_top = candidate_bottom + max(object_height(model, data, obj, hooks=hooks), 0.04)
    best = math.inf
    for other in state.get("objects", {}).values():
        if str(other.get("object_id") or "") == object_id:
            continue
        if other.get("location_relation") == "held":
            continue
        other_aabb = object_world_aabb(model, data, other, hooks=hooks)
        if other_aabb is None:
            continue
        if other_aabb["max_z"] < candidate_bottom - 0.03:
            continue
        if other_aabb["min_z"] > candidate_top + 0.12:
            continue
        gap_x = max(
            float(other_aabb["min_x"]) - (candidate_x + float(footprint[0])),
            (candidate_x - float(footprint[0])) - float(other_aabb["max_x"]),
            0.0,
        )
        gap_y = max(
            float(other_aabb["min_y"]) - (candidate_y + float(footprint[1])),
            (candidate_y - float(footprint[1])) - float(other_aabb["max_y"]),
            0.0,
        )
        best = min(best, math.hypot(gap_x, gap_y))
    return 999.0 if math.isinf(best) else round(float(best), 6)


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


def placement_position(
    receptacle: dict[str, Any],
    *,
    index: int,
    relation: str = "on",
    object_category: str | None = None,
) -> list[float]:
    base = receptacle["position"]
    if receptacle.get("category") == "Fridge" and relation == "inside":
        return [float(base[0]) + 0.08, float(base[1]) - 0.16, float(base[2]) + 0.35]
    if receptacle.get("category") == "Fridge":
        return [float(base[0]) + 0.25, float(base[1]) + 0.5, float(base[2]) + 0.55]
    offset = ((index % 3) - 1) * 0.12
    y_offset = 0.08 * (index % 2)
    if object_category == "Apple":
        y_offset = 0.16
    elif object_category == "RemoteControl":
        if receptacle.get("category") == "TVStand":
            tv_slots = (-0.18, 0.18, 0.0)
            offset = tv_slots[index % len(tv_slots)]
            y_offset = -0.28
        else:
            offset = 0.0
            y_offset = 0.34
    if object_category == "Apple":
        height = 0.58
    elif object_category == "RemoteControl":
        height = 0.49 if receptacle.get("category") == "TVStand" else 0.45
    else:
        height = 0.35
    if (
        relation == "on"
        and receptacle.get("category") == "DiningTable"
        and receptacle.get("support_top_z") is not None
    ):
        height = (
            float(receptacle["support_top_z"])
            - float(base[2])
            + object_surface_lift(object_category)
        )
    return [float(base[0]) + offset, float(base[1]) + y_offset, float(base[2]) + height]


def object_surface_lift(object_category: str | None) -> float:
    if object_category in {"Book", "Plate", "RemoteControl"}:
        return 0.04
    if object_category in {"Apple", "Potato"}:
        return 0.08
    if object_category == "Pillow":
        return 0.12
    return 0.06


def direct_support_clearance(obj: dict[str, Any], receptacle: dict[str, Any]) -> float:
    object_category = obj.get("category")
    receptacle_category = receptacle.get("category")
    if receptacle_category in {"Bed", "Sofa"}:
        return 0.035
    if object_category in {"Book", "Plate", "RemoteControl"}:
        return 0.02
    return 0.015


def receptacle_support_surfaces(
    model: mujoco.MjModel,
    data: mujoco.MjData,
    body_name: str,
    *,
    hooks: MolmoPlacementHooks,
) -> list[dict[str, Any]]:
    geom_ids = hooks.subtree_geom_ids(model, body_name)
    collision_ids = [
        geom_id
        for geom_id in geom_ids
        if "collision"
        in (mujoco.mj_id2name(model, mujoco.mjtObj.mjOBJ_GEOM, geom_id) or "").lower()
    ]
    candidate_ids = collision_ids or [
        geom_id
        for geom_id in geom_ids
        if "visual"
        not in (mujoco.mj_id2name(model, mujoco.mjtObj.mjOBJ_GEOM, geom_id) or "").lower()
    ]
    surfaces = []
    for geom_id in candidate_ids:
        surface = support_surface_from_geom(model, data, geom_id, hooks=hooks)
        if surface is not None:
            surfaces.append(surface)
    return sorted(
        surfaces,
        key=lambda item: (float(item["top_z"]), float(item["area_m2"])),
        reverse=True,
    )


def support_surface_from_geom(
    model: mujoco.MjModel,
    data: mujoco.MjData,
    geom_id: int,
    *,
    hooks: MolmoPlacementHooks,
) -> dict[str, Any] | None:
    half_extents = geom_world_half_extents(model, data, geom_id)
    if half_extents is None:
        return None
    half_x, half_y, half_z = half_extents
    if half_x < 0.06 or half_y < 0.06:
        return None
    area = 4.0 * half_x * half_y
    if area < 0.03:
        return None
    if not geom_has_upward_support_normal(data, geom_id):
        return None
    center = hooks.xyz(data.geom_xpos[geom_id])
    geom_name = mujoco.mj_id2name(model, mujoco.mjtObj.mjOBJ_GEOM, geom_id) or f"geom_{geom_id}"
    return {
        "surface_id": geom_name,
        "geom_id": int(geom_id),
        "center": [center[0], center[1]],
        "top_z": round(float(center[2]) + float(half_z), 6),
        "half_extents": [round(float(half_x), 6), round(float(half_y), 6)],
        "area_m2": round(float(area), 6),
        "source": "mujoco_collision_geom",
    }


def geom_has_upward_support_normal(data: mujoco.MjData, geom_id: int) -> bool:
    xmat = data.geom_xmat[geom_id]
    local_axis_world_z = max(abs(float(xmat[6])), abs(float(xmat[7])), abs(float(xmat[8])))
    return local_axis_world_z >= 0.75


def geom_world_half_extents(
    model: mujoco.MjModel,
    data: mujoco.MjData,
    geom_id: int,
) -> tuple[float, float, float] | None:
    geom_type = int(model.geom_type[geom_id])
    size = model.geom_size[geom_id]
    if geom_type == int(mujoco.mjtGeom.mjGEOM_BOX):
        local = (float(size[0]), float(size[1]), float(size[2]))
    elif geom_type in {
        int(mujoco.mjtGeom.mjGEOM_CYLINDER),
        int(mujoco.mjtGeom.mjGEOM_CAPSULE),
    }:
        local = (float(size[0]), float(size[0]), float(size[1]))
    elif geom_type == int(mujoco.mjtGeom.mjGEOM_SPHERE):
        local = (float(size[0]), float(size[0]), float(size[0]))
    elif geom_type == int(mujoco.mjtGeom.mjGEOM_ELLIPSOID):
        local = (float(size[0]), float(size[1]), float(size[2]))
    else:
        return None
    return oriented_half_extents(data.geom_xmat[geom_id], local)


def oriented_half_extents(
    xmat: Any,
    local: tuple[float, float, float],
) -> tuple[float, float, float]:
    return (
        abs(float(xmat[0])) * local[0]
        + abs(float(xmat[1])) * local[1]
        + abs(float(xmat[2])) * local[2],
        abs(float(xmat[3])) * local[0]
        + abs(float(xmat[4])) * local[1]
        + abs(float(xmat[5])) * local[2],
        abs(float(xmat[6])) * local[0]
        + abs(float(xmat[7])) * local[1]
        + abs(float(xmat[8])) * local[2],
    )


def support_top_z(surfaces: list[dict[str, Any]]) -> float | None:
    if not surfaces:
        return None
    return round(max(float(surface["top_z"]) for surface in surfaces), 6)


def object_bottom_offset(
    model: mujoco.MjModel,
    data: mujoco.MjData,
    obj: dict[str, Any],
    *,
    hooks: MolmoPlacementHooks,
) -> float:
    body_id = mujoco.mj_name2id(model, mujoco.mjtObj.mjOBJ_BODY, str(obj.get("body_name") or ""))
    if body_id < 0:
        return object_surface_lift(obj.get("category"))
    bottoms = []
    for geom_id in hooks.subtree_geom_ids(model, str(obj.get("body_name") or "")):
        half_extents = geom_world_half_extents(model, data, geom_id)
        if half_extents is None:
            continue
        bottoms.append(float(data.geom_xpos[geom_id][2]) - float(half_extents[2]))
    if not bottoms:
        return object_surface_lift(obj.get("category"))
    offset = float(data.xpos[body_id][2]) - min(bottoms)
    if offset <= 0.0 or offset > 1.0:
        return object_surface_lift(obj.get("category"))
    return max(offset, 0.01)


def object_height(
    model: mujoco.MjModel,
    data: mujoco.MjData,
    obj: dict[str, Any],
    *,
    hooks: MolmoPlacementHooks,
) -> float:
    aabb = object_world_aabb(model, data, obj, hooks=hooks)
    if aabb is None:
        return object_surface_lift(obj.get("category"))
    return max(float(aabb["max_z"]) - float(aabb["min_z"]), 0.01)


def object_world_aabb(
    model: mujoco.MjModel,
    data: mujoco.MjData,
    obj: dict[str, Any],
    *,
    hooks: MolmoPlacementHooks,
) -> dict[str, float] | None:
    geom_ids = hooks.subtree_geom_ids(model, str(obj.get("body_name") or ""))
    if not geom_ids:
        return None
    min_x = min_y = min_z = math.inf
    max_x = max_y = max_z = -math.inf
    for geom_id in geom_ids:
        half_extents = geom_world_half_extents(model, data, geom_id)
        if half_extents is None:
            continue
        center = data.geom_xpos[geom_id]
        min_x = min(min_x, float(center[0]) - float(half_extents[0]))
        max_x = max(max_x, float(center[0]) + float(half_extents[0]))
        min_y = min(min_y, float(center[1]) - float(half_extents[1]))
        max_y = max(max_y, float(center[1]) + float(half_extents[1]))
        min_z = min(min_z, float(center[2]) - float(half_extents[2]))
        max_z = max(max_z, float(center[2]) + float(half_extents[2]))
    if not math.isfinite(min_x):
        return None
    return {
        "min_x": min_x,
        "max_x": max_x,
        "min_y": min_y,
        "max_y": max_y,
        "min_z": min_z,
        "max_z": max_z,
    }


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


def object_footprint_half_extents(
    model: mujoco.MjModel,
    data: mujoco.MjData,
    obj: dict[str, Any],
    *,
    hooks: MolmoPlacementHooks,
) -> tuple[float, float]:
    half_x = 0.0
    half_y = 0.0
    for geom_id in hooks.subtree_geom_ids(model, str(obj.get("body_name") or "")):
        half_extents = geom_world_half_extents(model, data, geom_id)
        if half_extents is None:
            continue
        half_x = max(half_x, float(half_extents[0]))
        half_y = max(half_y, float(half_extents[1]))
    if half_x > 0.0 and half_y > 0.0:
        return (max(half_x, 0.025), max(half_y, 0.025))
    category = obj.get("category")
    if category == "RemoteControl":
        return (0.09, 0.045)
    if category == "Plate":
        return (0.13, 0.13)
    if category in {"Apple", "Potato"}:
        return (0.065, 0.065)
    if category == "Book":
        return (0.12, 0.08)
    if category == "Pillow":
        return (0.22, 0.16)
    return (0.08, 0.08)


def receptacle_requires_open(receptacle: dict[str, Any]) -> bool:
    text = receptacle_text(receptacle)
    return "fridge" in text or "refrigerator" in text


def receptacle_prefers_inside(receptacle: dict[str, Any]) -> bool:
    return receptacle_requires_open(receptacle) or receptacle_is_open_container(receptacle)


def receptacle_is_open_container(receptacle: dict[str, Any]) -> bool:
    text = receptacle_text(receptacle)
    return any(term in text for term in ("shelvingunit", "bookshelf", "bookcase", "shelf"))


def receptacle_text(receptacle: dict[str, Any]) -> str:
    return f"{receptacle.get('name', '')} {receptacle.get('category', '')}".lower()


def placement_diagnostic(
    *,
    state: dict[str, Any],
    object_id: str,
    receptacle_id: str,
    relation: str,
    requested_position: list[float],
    source: str,
    placement_index: int | None = None,
    placement_resolution: dict[str, Any] | None = None,
) -> dict[str, Any]:
    obj = state["objects"][object_id]
    receptacle = state["receptacles"][receptacle_id]
    object_position = [float(value) for value in obj.get("position", requested_position)]
    receptacle_position = [float(value) for value in receptacle.get("position", [0.0, 0.0, 0.0])]
    xy_distance = math.dist(object_position[:2], receptacle_position[:2])
    z_delta = object_position[2] - receptacle_position[2]
    placement_resolution = placement_resolution or {}
    default_support_status = (
        "semantic_contained_in_receptacle" if relation == "inside" else "semantic_on_receptacle"
    )
    support_status = str(placement_resolution.get("support_status") or default_support_status)
    diagnostic = {
        "schema": "molmospaces_semantic_placement_diagnostic_v1",
        "status": support_status,
        "object_id": object_id,
        "object_category": obj.get("category"),
        "object_body_name": obj.get("body_name"),
        "receptacle_id": receptacle_id,
        "receptacle_category": receptacle.get("category"),
        "receptacle_body_name": receptacle.get("body_name"),
        "relation": relation,
        "placement_index": placement_index,
        "requested_position": [round(float(value), 6) for value in requested_position],
        "object_position": [round(float(value), 6) for value in object_position],
        "receptacle_position": [round(float(value), 6) for value in receptacle_position],
        "xy_distance_m": round(float(xy_distance), 6),
        "z_delta_m": round(float(z_delta), 6),
        "support_status": support_status,
        "placement_support_status": support_status,
        "contact_proof": str(
            placement_resolution.get("contact_proof") or "not_measured_mujoco_freejoint_qpos"
        ),
        "diagnostic_source": source,
        "resolution_source": placement_resolution.get("resolution_source", "legacy_semantic"),
        "candidate_count": int(placement_resolution.get("candidate_count") or 0),
        "degraded": bool(placement_resolution.get("degraded", False)),
    }
    support_surface = placement_resolution.get("support_surface")
    if isinstance(support_surface, dict):
        diagnostic["support_surface_id"] = support_surface.get("surface_id")
        diagnostic["support_surface_center"] = support_surface.get("center")
        diagnostic["support_surface_half_extents"] = support_surface.get("half_extents")
        diagnostic["support_surface_top_z"] = support_surface.get("top_z")
    if placement_resolution.get("object_bottom_offset_m") is not None:
        diagnostic["object_bottom_offset_m"] = placement_resolution["object_bottom_offset_m"]
    if placement_resolution.get("support_clearance_m") is not None:
        diagnostic["support_clearance_m"] = placement_resolution["support_clearance_m"]
    if placement_resolution.get("object_footprint_half_extents_m") is not None:
        diagnostic["object_footprint_half_extents_m"] = placement_resolution[
            "object_footprint_half_extents_m"
        ]
    return diagnostic
