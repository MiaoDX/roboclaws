"""Isaac Lab worker state owner."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Callable

from roboclaws.backends.isaaclab import (
    isaac_camera_geometry,
    isaac_mapping_diagnostics,
    isaac_placement_resolution,
    isaac_robot_import,
    isaac_robot_pose_focus,
    isaac_scenario_state,
    isaac_scene_index_geometry,
    isaac_semantic_pose_projection,
    isaac_semantic_pose_stage,
    isaac_semantic_pose_state,
    isaac_support_surface_geometry,
    isaac_worker_context,
)
from roboclaws.household.backend import HELD_LOCATION_ID
from roboclaws.household.isaac_lab_backend import (
    ISAAC_SEMANTIC_POSE_EVENT_SCHEMA,
    ISAAC_SEMANTIC_POSE_STATE_SCHEMA,
    ISAAC_SEMANTIC_POSE_STATE_SOURCE,
)
from roboclaws.household.manipulation_contract import ISAAC_SEMANTIC_POSE_PROVENANCE
from roboclaws.household.types import CleanupScenario

ISAAC_RBY1M_ROBOT_IMPORT_SUMMARY_PATH = isaac_robot_import.ISAAC_RBY1M_ROBOT_IMPORT_SUMMARY_PATH
ISAAC_RBY1M_ROBOT_USD_PATH = isaac_robot_import.ISAAC_RBY1M_ROBOT_USD_PATH
_dict = isaac_worker_context.dict_value
_has_xy = isaac_worker_context.has_xy
_norm = isaac_worker_context.norm
_objects_by_id = isaac_worker_context.objects_by_id
_optional_float = isaac_camera_geometry.optional_float
_pose_near = isaac_worker_context.pose_near
_receptacles_by_id = isaac_worker_context.receptacles_by_id
_round_vec3 = isaac_scene_index_geometry.round_vec3
_support_surface_from_usd_bounds = isaac_support_surface_geometry.support_surface_from_usd_bounds
_vec3 = isaac_worker_context.vec3


def _semantic_pose_target_position(
    *,
    support_id: str,
    receptacle_index: dict[str, Any],
    fallback_pose: dict[str, Any],
) -> tuple[float, float, float] | None:

    return isaac_semantic_pose_stage.semantic_pose_target_position(
        support_id=support_id,
        receptacle_index=receptacle_index,
        fallback_pose=fallback_pose,
        dict_value=_dict,
        vec3=_vec3,
    )


def _initial_semantic_pose_state(
    *,
    scenario: CleanupScenario,
    object_index: dict[str, Any],
    receptacle_index: dict[str, Any],
    scene_binding_diagnostics: dict[str, Any] | None,
    initial_receptacle_id: str,
) -> dict[str, Any]:

    return isaac_semantic_pose_state.initial_semantic_pose_state(
        scenario=scenario,
        object_index=object_index,
        receptacle_index=receptacle_index,
        scene_binding_diagnostics=scene_binding_diagnostics,
        initial_receptacle_id=initial_receptacle_id,
        semantic_pose_state_from_backend_state=_semantic_pose_state_from_backend_state,
    )


def _initial_semantic_pose_state_from_state(state: dict[str, Any]) -> dict[str, Any]:

    return _semantic_pose_state_from_backend_state(state, transform_events=[])


def _semantic_pose_state_from_backend_state(
    state: dict[str, Any],
    *,
    transform_events: list[dict[str, Any]],
) -> dict[str, Any]:

    return isaac_semantic_pose_state.semantic_pose_state_from_backend_state(
        state,
        transform_events=transform_events,
        state_schema=ISAAC_SEMANTIC_POSE_STATE_SCHEMA,
        state_source=ISAAC_SEMANTIC_POSE_STATE_SOURCE,
        primitive_provenance=ISAAC_SEMANTIC_POSE_PROVENANCE,
        robot_pose_for_receptacle=_robot_pose_for_receptacle,
        semantic_object_poses_from_state=_semantic_object_poses_from_state,
        semantic_articulations_from_state=_semantic_articulations_from_state,
    )


def _record_semantic_pose_event(
    state: dict[str, Any],
    *,
    tool: str,
    state_mutation: str,
    object_id: str = "",
    receptacle_id: str = "",
    previous_location_id: str = "",
    location_id: str = "",
    relation: str = "",
    **extra: Any,
) -> dict[str, Any]:

    return isaac_semantic_pose_state.record_semantic_pose_event(
        state,
        tool=tool,
        state_mutation=state_mutation,
        event_schema=ISAAC_SEMANTIC_POSE_EVENT_SCHEMA,
        state_schema=ISAAC_SEMANTIC_POSE_STATE_SCHEMA,
        state_source=ISAAC_SEMANTIC_POSE_STATE_SOURCE,
        primitive_provenance=ISAAC_SEMANTIC_POSE_PROVENANCE,
        robot_pose_for_receptacle=_robot_pose_for_receptacle,
        semantic_object_poses_from_state=_semantic_object_poses_from_state,
        semantic_articulations_from_state=_semantic_articulations_from_state,
        object_usd_prim_path=_object_usd_prim_path,
        receptacle_usd_prim_path=_receptacle_usd_prim_path,
        object_id=object_id,
        receptacle_id=receptacle_id,
        previous_location_id=previous_location_id,
        location_id=location_id,
        relation=relation,
        **extra,
    )


def _record_waypoint_pose_event(
    state: dict[str, Any],
    *,
    waypoint: dict[str, Any],
    robot_pose: dict[str, Any],
    previous_waypoint_id: str = "",
    previous_room_id: str = "",
) -> dict[str, Any]:

    return isaac_semantic_pose_state.record_waypoint_pose_event(
        state,
        waypoint=waypoint,
        robot_pose=robot_pose,
        event_schema=ISAAC_SEMANTIC_POSE_EVENT_SCHEMA,
        state_schema=ISAAC_SEMANTIC_POSE_STATE_SCHEMA,
        state_source=ISAAC_SEMANTIC_POSE_STATE_SOURCE,
        primitive_provenance=ISAAC_SEMANTIC_POSE_PROVENANCE,
        semantic_object_poses_from_state=_semantic_object_poses_from_state,
        semantic_articulations_from_state=_semantic_articulations_from_state,
        previous_waypoint_id=previous_waypoint_id,
        previous_room_id=previous_room_id,
    )


def _isaac_semantic_pose_projection_hooks() -> (
    isaac_semantic_pose_projection.IsaacSemanticPoseProjectionHooks
):

    return isaac_semantic_pose_projection.IsaacSemanticPoseProjectionHooks(
        dict_value=_dict,
        robot_pose_for_receptacle=_robot_pose_for_receptacle,
        round_vec3=_round_vec3,
        semantic_pose_target_position=_semantic_pose_target_position,
        vec3=_vec3,
    )


def _isaac_scenario_state_hooks() -> isaac_scenario_state.IsaacScenarioStateHooks:

    return isaac_scenario_state.IsaacScenarioStateHooks(
        dict_value=_dict,
        isaac_placement_diagnostic=_isaac_placement_diagnostic,
        receptacle_prefers_inside=_receptacle_prefers_inside,
        receptacle_requires_open=_receptacle_requires_open,
        receptacles_by_id=_receptacles_by_id,
        resolve_isaac_placement=_resolve_isaac_placement,
        round_vec3=_round_vec3,
        vec3=_vec3,
    )


def _with_isaac_scenario_state_hooks(func: Callable[..., Any]) -> Callable[..., Any]:

    def call(*args: Any, **kwargs: Any) -> Any:
        return func(*args, **kwargs, hooks=_isaac_scenario_state_hooks())

    return call


_seed_generated_mess_placements = _with_isaac_scenario_state_hooks(
    isaac_scenario_state.seed_generated_mess_placements
)

_manifest_target_by_object_id = _with_isaac_scenario_state_hooks(
    isaac_scenario_state.manifest_target_by_object_id
)

_target_start_receptacle = _with_isaac_scenario_state_hooks(
    isaac_scenario_state.target_start_receptacle
)

_target_relation = _with_isaac_scenario_state_hooks(isaac_scenario_state.target_relation)


def _target_placement_index(index: int, manifest_target: dict[str, Any] | None) -> int:

    return isaac_scenario_state.target_placement_index(index, manifest_target)


_mess_wrong_receptacle_pool = _with_isaac_scenario_state_hooks(
    isaac_scenario_state.mess_wrong_receptacle_pool
)

_apply_object_location = _with_isaac_scenario_state_hooks(
    isaac_scenario_state.apply_object_location
)

_set_public_scenario_object_location = _with_isaac_scenario_state_hooks(
    isaac_scenario_state.set_public_scenario_object_location
)

_first_target_object_location = _with_isaac_scenario_state_hooks(
    isaac_scenario_state.first_target_object_location
)


def _isaac_placement_hooks() -> isaac_placement_resolution.IsaacPlacementHooks:

    return isaac_placement_resolution.IsaacPlacementHooks(
        aabb_xy_overlaps=_aabb_xy_overlaps,
        binding_for_handle=_binding_for_handle,
        candidate_has_direct_support=_candidate_has_direct_support,
        candidate_is_clear_of_dynamic_objects=_isaac_candidate_is_clear_of_dynamic_objects,
        dict_value=_dict,
        direct_support_clearance=_isaac_direct_support_clearance,
        direct_support_placement=_isaac_direct_support_placement,
        elevated_position_over_surface=_elevated_position_over_surface,
        fallback_placement_position=_isaac_fallback_placement_position,
        index_entry=_isaac_index_entry,
        normalize_support_surface=_normalize_support_surface,
        norm=_norm,
        object_bottom_offset=_isaac_object_bottom_offset,
        object_current_aabb=_isaac_object_current_aabb,
        object_footprint_half_extents=_isaac_object_footprint_half_extents,
        object_height=_isaac_object_height,
        object_surface_lift=_isaac_object_surface_lift,
        object_usd_prim_path=_object_usd_prim_path,
        object_world_bounds=_isaac_object_world_bounds,
        objects_by_id=_objects_by_id,
        pose_near=_pose_near,
        receptacle_support_pose=_receptacle_support_pose,
        receptacle_support_surface=_isaac_receptacle_support_surface,
        receptacle_support_surfaces=_isaac_receptacle_support_surfaces,
        receptacle_text=_receptacle_text,
        receptacle_usd_prim_path=_receptacle_usd_prim_path,
        receptacle_world_bounds=_isaac_receptacle_world_bounds,
        receptacles_by_id=_receptacles_by_id,
        round_vec3=_round_vec3,
        semantic_object_position_from_state=_semantic_object_position_from_state,
        state_objects_for_clearance=_isaac_state_objects_for_clearance,
        support_pose_position=_support_pose_position,
        support_surface_from_usd_bounds=_support_surface_from_usd_bounds,
        surface_candidate_positions=_surface_candidate_positions,
        vec3=_vec3,
    )


def _with_isaac_placement_hooks(func: Callable[..., Any]) -> Callable[..., Any]:

    def call(*args: Any, **kwargs: Any) -> Any:
        return func(*args, **kwargs, hooks=_isaac_placement_hooks())

    return call


_resolve_isaac_placement = _with_isaac_placement_hooks(
    isaac_placement_resolution.resolve_isaac_placement
)

_isaac_state_objects_for_clearance = _with_isaac_placement_hooks(
    isaac_placement_resolution.isaac_state_objects_for_clearance
)

_isaac_direct_support_placement = _with_isaac_placement_hooks(
    isaac_placement_resolution.isaac_direct_support_placement
)

_isaac_receptacle_support_surface = _with_isaac_placement_hooks(
    isaac_placement_resolution.isaac_receptacle_support_surface
)

_isaac_receptacle_support_surfaces = _with_isaac_placement_hooks(
    isaac_placement_resolution.isaac_receptacle_support_surfaces
)

_normalize_support_surface = isaac_placement_resolution.normalize_support_surface

_surface_candidate_positions = isaac_placement_resolution.surface_candidate_positions

_candidate_has_direct_support = isaac_placement_resolution.candidate_has_direct_support

_isaac_candidate_is_clear_of_dynamic_objects = _with_isaac_placement_hooks(
    isaac_placement_resolution.isaac_candidate_is_clear_of_dynamic_objects
)

_aabb_xy_overlaps = isaac_placement_resolution.aabb_xy_overlaps

_isaac_object_current_aabb = _with_isaac_placement_hooks(
    isaac_placement_resolution.isaac_object_current_aabb
)

_elevated_position_over_surface = isaac_placement_resolution.elevated_position_over_surface

_isaac_fallback_placement_position = _with_isaac_placement_hooks(
    isaac_placement_resolution.isaac_fallback_placement_position
)

_isaac_object_footprint_half_extents = _with_isaac_placement_hooks(
    isaac_placement_resolution.isaac_object_footprint_half_extents
)

_isaac_object_bottom_offset = _with_isaac_placement_hooks(
    isaac_placement_resolution.isaac_object_bottom_offset
)

_isaac_object_height = _with_isaac_placement_hooks(isaac_placement_resolution.isaac_object_height)

_isaac_object_world_bounds = _with_isaac_placement_hooks(
    isaac_placement_resolution.isaac_object_world_bounds
)

_isaac_receptacle_world_bounds = _with_isaac_placement_hooks(
    isaac_placement_resolution.isaac_receptacle_world_bounds
)

_isaac_index_entry = _with_isaac_placement_hooks(isaac_placement_resolution.isaac_index_entry)


def _isaac_object_surface_lift(category: Any) -> float:

    return isaac_placement_resolution.isaac_object_surface_lift(category, norm=_norm)


def _isaac_direct_support_clearance(
    obj: dict[str, Any],
    receptacle: dict[str, Any],
) -> float:

    return isaac_placement_resolution.isaac_direct_support_clearance(
        obj,
        receptacle,
        norm=_norm,
        receptacle_text=_receptacle_text,
    )


def _receptacle_requires_open(receptacle: dict[str, Any]) -> bool:

    text = _receptacle_text(receptacle)
    return "fridge" in text or "refrigerator" in text


def _receptacle_prefers_inside(receptacle: dict[str, Any]) -> bool:

    return _receptacle_requires_open(receptacle) or _receptacle_is_open_container(receptacle)


def _receptacle_is_open_container(receptacle: dict[str, Any]) -> bool:

    text = _receptacle_text(receptacle)
    return any(term in text for term in ("shelvingunit", "bookshelf", "bookcase", "shelf"))


def _receptacle_text(receptacle: dict[str, Any]) -> str:

    parts = (
        receptacle.get("receptacle_id", ""),
        receptacle.get("name", ""),
        receptacle.get("category", ""),
        receptacle.get("kind", ""),
    )
    return " ".join(str(part) for part in parts).lower()


def _isaac_placement_diagnostic(
    *,
    state: dict[str, Any],
    object_id: str,
    receptacle_id: str,
    relation: str,
    source: str,
    placement_index: int | None = None,
    placement_resolution: dict[str, Any] | None = None,
) -> dict[str, Any]:

    return isaac_placement_resolution.isaac_placement_diagnostic(
        state=state,
        object_id=object_id,
        receptacle_id=receptacle_id,
        relation=relation,
        source=source,
        placement_index=placement_index,
        placement_resolution=placement_resolution,
        hooks=_isaac_placement_hooks(),
    )


def _with_semantic_pose_projection_hooks(
    func: Callable[..., Any],
    **injected: Any,
) -> Callable[..., Any]:

    def call(*args: Any, **kwargs: Any) -> Any:
        return func(
            *args,
            **kwargs,
            hooks=_isaac_semantic_pose_projection_hooks(),
            **injected,
        )

    return call


_semantic_object_poses_from_state = _with_semantic_pose_projection_hooks(
    isaac_semantic_pose_projection.semantic_object_poses_from_state,
    held_location_id=HELD_LOCATION_ID,
    state_source=ISAAC_SEMANTIC_POSE_STATE_SOURCE,
)

_semantic_object_position_from_state = _with_semantic_pose_projection_hooks(
    isaac_semantic_pose_projection.semantic_object_position_from_state,
    held_location_id=HELD_LOCATION_ID,
)

_semantic_object_position_source = _with_semantic_pose_projection_hooks(
    isaac_semantic_pose_projection.semantic_object_position_source,
    held_location_id=HELD_LOCATION_ID,
)

_object_usd_world_bounds_center = _with_semantic_pose_projection_hooks(
    isaac_semantic_pose_projection.object_usd_world_bounds_center
)

_semantic_articulations_from_state = _with_semantic_pose_projection_hooks(
    isaac_semantic_pose_projection.semantic_articulations_from_state,
    state_source=ISAAC_SEMANTIC_POSE_STATE_SOURCE,
)

_object_usd_prim_path = _with_semantic_pose_projection_hooks(
    isaac_semantic_pose_projection.object_usd_prim_path
)

_receptacle_usd_prim_path = _with_semantic_pose_projection_hooks(
    isaac_semantic_pose_projection.receptacle_usd_prim_path
)

_binding_usd_prim_path = _with_semantic_pose_projection_hooks(
    isaac_semantic_pose_projection.binding_usd_prim_path
)

_index_usd_prim_path = _with_semantic_pose_projection_hooks(
    isaac_semantic_pose_projection.index_usd_prim_path
)


def _isaac_robot_pose_hooks() -> isaac_robot_pose_focus.IsaacRobotPoseHooks:

    return isaac_robot_pose_focus.IsaacRobotPoseHooks(
        binding_for_handle=_binding_for_handle,
        dict_value=_dict,
        has_xy=_has_xy,
        optional_float=_optional_float,
        pose_near=_pose_near,
        receptacle_support_pose=_receptacle_support_pose,
        receptacles_by_id=_receptacles_by_id,
        round_vec3=_round_vec3,
        scene_index_center_xy=_scene_index_center_xy,
        semantic_object_pose_entry=_semantic_object_pose_entry,
        support_pose_position=_support_pose_position,
        vec3=_vec3,
    )


def _with_isaac_robot_pose_hooks(func: Callable[..., Any]) -> Callable[..., Any]:

    def call(*args: Any, **kwargs: Any) -> Any:
        return func(*args, **kwargs, hooks=_isaac_robot_pose_hooks())

    return call


_robot_pose_for_receptacle = _with_isaac_robot_pose_hooks(
    isaac_robot_pose_focus.robot_pose_for_receptacle
)

_receptacle_support_pose = _with_isaac_robot_pose_hooks(
    isaac_robot_pose_focus.receptacle_support_pose
)


def _binding_for_handle(
    scene_binding_diagnostics: Any,
    handle: str,
    groups: tuple[str, ...],
) -> dict[str, Any]:

    return isaac_robot_pose_focus.binding_for_handle(
        scene_binding_diagnostics,
        handle,
        groups,
        dict_value=_dict,
    )


def _scene_index_center_xy(state: dict[str, Any]) -> tuple[float, float]:

    return isaac_robot_pose_focus.scene_index_center_xy(
        state,
        dict_value=_dict,
        vec3=_vec3,
    )


def _semantic_object_pose_entry(
    state: dict[str, Any],
    object_id: str | None,
) -> dict[str, Any]:

    return isaac_robot_pose_focus.semantic_object_pose_entry(
        state,
        object_id,
        dict_value=_dict,
    )


def _support_pose_position(pose: dict[str, Any]) -> list[float] | None:

    return isaac_robot_pose_focus.support_pose_position(
        pose,
        has_xy=_has_xy,
    )


def _rby1m_robot_import_plan(robot_name: str) -> dict[str, Any]:

    return isaac_robot_import.rby1m_robot_import_plan(
        robot_name,
        robot_usd_path=ISAAC_RBY1M_ROBOT_USD_PATH,
        import_summary_path=ISAAC_RBY1M_ROBOT_IMPORT_SUMMARY_PATH,
        find_urdf=_find_rby1m_isaac_urdf,
        repo_path=_repo_path,
        load_json_if_file=_load_json_if_file,
        head_camera_prim=isaac_camera_geometry.ISAAC_RBY1M_HEAD_CAMERA_PRIM,
    )


def _repo_path(path: Path) -> Path:

    return isaac_robot_import.repo_path(path, anchor_file=__file__)


def _load_json_if_file(path: Path) -> dict[str, Any]:

    return isaac_robot_import.load_json_if_file(path)


def _find_rby1m_isaac_urdf() -> Path | None:

    return isaac_robot_import.find_rby1m_isaac_urdf()


def _scene_usd_path(scene_source: str, scene_index: int) -> str:

    return isaac_mapping_diagnostics.scene_usd_path(scene_source, scene_index)
