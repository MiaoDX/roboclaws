"""Build stable diagnostics for resolved Isaac placements."""

from __future__ import annotations

import math
from typing import Any

from roboclaws.household.manipulation_contract import ISAAC_SEMANTIC_POSE_PROVENANCE

PLACEMENT_DIAGNOSTIC_SCHEMA = "molmospaces_semantic_placement_diagnostic_v1"


def placement_diagnostic(
    *,
    state: dict[str, Any],
    object_id: str,
    receptacle_id: str,
    relation: str,
    source: str,
    placement_index: int | None,
    placement_resolution: dict[str, Any],
    hooks: Any,
) -> dict[str, Any]:
    obj = hooks.dict_value(hooks.objects_by_id(state).get(object_id))
    receptacle = hooks.dict_value(hooks.receptacles_by_id(state).get(receptacle_id))
    requested_position = hooks.vec3(placement_resolution.get("position")) or []
    object_position = requested_position or hooks.semantic_object_position_from_state(
        state,
        object_id=object_id,
        location_id=str(hooks.dict_value(state.get("locations")).get(object_id) or ""),
        original_location_id=str(obj.get("location_id") or ""),
        support_receptacle_id=receptacle_id,
    )
    object_position = object_position or []
    receptacle_pose = hooks.receptacle_support_pose(state, receptacle_id)
    receptacle_position = hooks.support_pose_position(receptacle_pose)
    receptacle_position = receptacle_position or hooks.vec3(
        hooks.dict_value(hooks.receptacle_world_bounds(state, receptacle_id)).get("center")
    )
    receptacle_position = receptacle_position or []
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
    default_status = (
        "semantic_contained_in_receptacle" if relation == "inside" else "semantic_on_receptacle"
    )
    support_status = str(placement_resolution.get("support_status") or default_status)
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
        for key in ("surface_id", "center", "half_extents", "top_z", "source"):
            diagnostic[f"support_surface_{key}"] = support_surface.get(key)
        if support_surface.get("member_count") is not None:
            diagnostic["support_surface_member_count"] = support_surface.get("member_count")
    for key in ("object_bottom_offset_m", "support_clearance_m", "object_footprint_half_extents_m"):
        if placement_resolution.get(key) is not None:
            diagnostic[key] = placement_resolution[key]
    return diagnostic
