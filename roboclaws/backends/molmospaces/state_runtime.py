from __future__ import annotations

from typing import Any

import mujoco

from roboclaws.backends.molmospaces import placement, runtime_state, scenario_state
from roboclaws.backends.molmospaces.common import (
    _apply_qpos,
    _friendly_name,
    _primary_body_name,
    _xyz,
)
from roboclaws.backends.molmospaces.navigation_runtime import (
    _load_model_data_for_state,
    _set_free_body_position,
)
from roboclaws.backends.molmospaces.perception_runtime import _subtree_body_ids, _subtree_geom_ids

BACKEND = "molmospaces_subprocess"


def _collect_dynamic_objects(
    model: mujoco.MjModel,
    data: mujoco.MjData,
    metadata: dict[str, Any],
) -> list[dict[str, Any]]:
    return scenario_state.collect_dynamic_objects(
        model, data, metadata, hooks=_molmo_scenario_hooks()
    )


def _collect_receptacles(
    model: mujoco.MjModel,
    data: mujoco.MjData,
    metadata: dict[str, Any],
) -> list[dict[str, Any]]:
    return scenario_state.collect_receptacles(model, data, metadata, hooks=_molmo_scenario_hooks())


def _seed_misplaced_objects(
    model: mujoco.MjModel,
    data: mujoco.MjData,
    state: dict[str, Any],
    targets: list[dict[str, Any]],
) -> None:
    scenario_state.seed_misplaced_objects(
        model, data, state, targets, hooks=_molmo_scenario_hooks()
    )


def _manifest_target_by_object_id(state: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return scenario_state.manifest_target_by_object_id(state)


def _target_receptacle_id(
    target: dict[str, Any],
    manifest_target: dict[str, Any] | None,
) -> str:
    return scenario_state.target_receptacle_id(target, manifest_target)


def _target_start_receptacle(
    state: dict[str, Any],
    target: dict[str, Any],
    wrong_pool: list[dict[str, Any]],
    index: int,
    manifest_target: dict[str, Any] | None,
) -> dict[str, Any]:
    return scenario_state.target_start_receptacle(state, target, wrong_pool, index, manifest_target)


def _target_start_receptacle_id(state: dict[str, Any], target: dict[str, Any]) -> str:
    return scenario_state.target_start_receptacle_id(state, target)


def _target_relation(
    receptacle: dict[str, Any],
    manifest_target: dict[str, Any] | None,
) -> str:
    return scenario_state.target_relation(
        receptacle, manifest_target, hooks=_molmo_scenario_hooks()
    )


def _target_placement_index(index: int, manifest_target: dict[str, Any] | None) -> int:
    return scenario_state.target_placement_index(index, manifest_target)


def _public_scenario(state: dict[str, Any]) -> dict[str, Any]:
    return scenario_state.public_scenario(state, read_locations=_read_locations, backend=BACKEND)


def _read_locations(state: dict[str, Any]) -> dict[str, str]:
    return scenario_state.read_locations(state, hooks=_molmo_scenario_hooks())


def _read_containment(state: dict[str, Any]) -> dict[str, dict[str, str]]:
    return scenario_state.read_containment(state)


def _score(final_locations: dict[str, str], manifest: dict[str, Any]) -> dict[str, Any]:
    return scenario_state.score(final_locations, manifest)


def _nearest_receptacle(position: list[float], receptacles: list[dict[str, Any]]) -> str:
    return scenario_state.nearest_receptacle(position, receptacles)


def _first_wrong_receptacle(state: dict[str, Any], target: dict[str, Any]) -> str:
    return scenario_state.first_wrong_receptacle(state, target)


def _first_receptacle_id(state: dict[str, Any]) -> str | None:
    return scenario_state.first_receptacle_id(state)


def _refresh_object_positions(
    model: mujoco.MjModel,
    data: mujoco.MjData,
    state: dict[str, Any],
) -> None:
    runtime_state.refresh_object_positions(model, data, state, xyz=_xyz)


def _refresh_runtime_render_state(state: dict[str, Any]) -> None:
    runtime_state.refresh_runtime_render_state(
        state,
        load_model_data_for_state=_load_model_data_for_state,
        apply_qpos=_apply_qpos,
        runtime_render_state=_runtime_render_state,
    )


def _runtime_render_state(
    model: mujoco.MjModel,
    data: mujoco.MjData,
    state: dict[str, Any],
) -> dict[str, Any]:
    return runtime_state.runtime_render_state(
        model,
        data,
        state,
        runtime_subtree_joints=_runtime_subtree_joints,
        xyz=_xyz,
    )


def _runtime_subtree_joints(
    model: mujoco.MjModel,
    data: mujoco.MjData,
    body_name: str,
    *,
    exclude_root_freejoint: bool,
) -> list[dict[str, Any]]:
    return runtime_state.runtime_subtree_joints(
        model,
        data,
        body_name,
        exclude_root_freejoint=exclude_root_freejoint,
        subtree_body_ids=_subtree_body_ids,
        joint_qpos_width=_joint_qpos_width,
        joint_type_name=_joint_type_name,
    )


def _joint_qpos_width(model: mujoco.MjModel, joint_id: int) -> int:
    return runtime_state.joint_qpos_width(model, joint_id)


def _joint_type_name(model: mujoco.MjModel, joint_id: int) -> str:
    return runtime_state.joint_type_name(model, joint_id)


def _molmo_placement_hooks() -> placement.MolmoPlacementHooks:
    return placement.MolmoPlacementHooks(
        subtree_geom_ids=_subtree_geom_ids,
        xyz=_xyz,
    )


def _molmo_scenario_hooks() -> scenario_state.MolmoScenarioHooks:
    return scenario_state.MolmoScenarioHooks(
        primary_body_name=_primary_body_name,
        friendly_name=_friendly_name,
        xyz=_xyz,
        receptacle_support_surfaces=_receptacle_support_surfaces,
        support_top_z=_support_top_z,
        receptacle_requires_open=_receptacle_requires_open,
        receptacle_prefers_inside=_receptacle_prefers_inside,
        resolve_placement=_resolve_placement,
        set_free_body_position=_set_free_body_position,
        refresh_object_positions=_refresh_object_positions,
        placement_diagnostic=_placement_diagnostic,
        load_model_data_for_state=_load_model_data_for_state,
        apply_qpos=_apply_qpos,
    )


def _resolve_placement(
    model: mujoco.MjModel,
    data: mujoco.MjData,
    *,
    state: dict[str, Any],
    object_id: str,
    receptacle_id: str,
    index: int,
    relation: str,
) -> dict[str, Any]:
    return placement.resolve_placement(
        model,
        data,
        state=state,
        object_id=object_id,
        receptacle_id=receptacle_id,
        index=index,
        relation=relation,
        hooks=_molmo_placement_hooks(),
    )


def _direct_support_placement(
    model: mujoco.MjModel,
    data: mujoco.MjData,
    state: dict[str, Any],
    obj: dict[str, Any],
    receptacle: dict[str, Any],
    *,
    index: int,
) -> dict[str, Any] | None:
    return placement.direct_support_placement(
        model,
        data,
        state,
        obj,
        receptacle,
        index=index,
        hooks=_molmo_placement_hooks(),
    )


def _surface_candidate_positions(
    surface: dict[str, Any],
    *,
    footprint: tuple[float, float],
    bottom_offset: float,
    clearance: float,
    index: int,
) -> list[list[float]]:
    return placement.surface_candidate_positions(
        surface,
        footprint=footprint,
        bottom_offset=bottom_offset,
        clearance=clearance,
        index=index,
    )


def _candidate_has_direct_support(
    position: list[float],
    surface: dict[str, Any],
    footprint: tuple[float, float],
) -> bool:
    return placement.candidate_has_direct_support(position, surface, footprint)


def _candidate_is_clear_of_dynamic_objects(
    model: mujoco.MjModel,
    data: mujoco.MjData,
    state: dict[str, Any],
    obj: dict[str, Any],
    position: list[float],
    *,
    footprint: tuple[float, float],
    bottom_offset: float,
) -> bool:
    return placement.candidate_is_clear_of_dynamic_objects(
        model,
        data,
        state,
        obj,
        position,
        footprint=footprint,
        bottom_offset=bottom_offset,
        hooks=_molmo_placement_hooks(),
    )


def _elevated_position_over_surface(
    surface: dict[str, Any],
    *,
    bottom_offset: float,
) -> list[float]:
    return placement.elevated_position_over_surface(surface, bottom_offset=bottom_offset)


def _placement_position(
    receptacle: dict[str, Any],
    *,
    index: int,
    relation: str = "on",
    object_category: str | None = None,
) -> list[float]:
    return placement.placement_position(
        receptacle,
        index=index,
        relation=relation,
        object_category=object_category,
    )


def _object_surface_lift(object_category: str | None) -> float:
    return placement.object_surface_lift(object_category)


def _direct_support_clearance(obj: dict[str, Any], receptacle: dict[str, Any]) -> float:
    return placement.direct_support_clearance(obj, receptacle)


def _receptacle_support_surfaces(
    model: mujoco.MjModel,
    data: mujoco.MjData,
    body_name: str,
) -> list[dict[str, Any]]:
    return placement.receptacle_support_surfaces(
        model,
        data,
        body_name,
        hooks=_molmo_placement_hooks(),
    )


def _support_surface_from_geom(
    model: mujoco.MjModel,
    data: mujoco.MjData,
    geom_id: int,
) -> dict[str, Any] | None:
    return placement.support_surface_from_geom(
        model,
        data,
        geom_id,
        hooks=_molmo_placement_hooks(),
    )


def _geom_has_upward_support_normal(data: mujoco.MjData, geom_id: int) -> bool:
    return placement.geom_has_upward_support_normal(data, geom_id)


def _geom_world_half_extents(
    model: mujoco.MjModel,
    data: mujoco.MjData,
    geom_id: int,
) -> tuple[float, float, float] | None:
    return placement.geom_world_half_extents(model, data, geom_id)


def _oriented_half_extents(
    xmat: Any,
    local: tuple[float, float, float],
) -> tuple[float, float, float]:
    return placement.oriented_half_extents(xmat, local)


def _support_top_z(surfaces: list[dict[str, Any]]) -> float | None:
    return placement.support_top_z(surfaces)


def _object_bottom_offset(
    model: mujoco.MjModel,
    data: mujoco.MjData,
    obj: dict[str, Any],
) -> float:
    return placement.object_bottom_offset(model, data, obj, hooks=_molmo_placement_hooks())


def _object_height(
    model: mujoco.MjModel,
    data: mujoco.MjData,
    obj: dict[str, Any],
) -> float:
    return placement.object_height(model, data, obj, hooks=_molmo_placement_hooks())


def _object_world_aabb(
    model: mujoco.MjModel,
    data: mujoco.MjData,
    obj: dict[str, Any],
) -> dict[str, float] | None:
    return placement.object_world_aabb(model, data, obj, hooks=_molmo_placement_hooks())


def _aabb_xy_overlaps(
    first: tuple[float, float, float, float],
    second: dict[str, float],
    *,
    margin: float,
) -> bool:
    return placement.aabb_xy_overlaps(first, second, margin=margin)


def _object_footprint_half_extents(
    model: mujoco.MjModel,
    data: mujoco.MjData,
    obj: dict[str, Any],
) -> tuple[float, float]:
    return placement.object_footprint_half_extents(model, data, obj, hooks=_molmo_placement_hooks())


def _receptacle_requires_open(receptacle: dict[str, Any]) -> bool:
    return placement.receptacle_requires_open(receptacle)


def _receptacle_prefers_inside(receptacle: dict[str, Any]) -> bool:
    return placement.receptacle_prefers_inside(receptacle)


def _receptacle_is_open_container(receptacle: dict[str, Any]) -> bool:
    return placement.receptacle_is_open_container(receptacle)


def _receptacle_text(receptacle: dict[str, Any]) -> str:
    return placement.receptacle_text(receptacle)


def _placement_diagnostic(
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
    return placement.placement_diagnostic(
        state=state,
        object_id=object_id,
        receptacle_id=receptacle_id,
        relation=relation,
        requested_position=requested_position,
        source=source,
        placement_index=placement_index,
        placement_resolution=placement_resolution,
    )
