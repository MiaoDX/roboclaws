"""Isaac Lab worker initialization owner."""

from __future__ import annotations

from roboclaws.backends.isaaclab.runtime_dependencies import (
    DEFAULT_HEIGHT,
    DEFAULT_WIDTH,
    REAL_ROBOT_VIEW_CAPTURE_METHOD,
    REAL_SMOKE_CAPTURE_METHOD,
    STATE_SCHEMA,
    Any,
    Path,
    _dict,
    _fallback_room_outlines_from_indices,
    _index_or_default,
    _object_index,
    _receptacle_index,
    _room_outlines_from_scene_index_diagnostics,
    _scene_binding_diagnostics,
    argparse,
    isaac_mapping_diagnostics,
    isaac_scene_index_geometry,
    isaac_worker_state,
)


def init_state(args: argparse.Namespace) -> dict[str, Any]:

    return isaac_worker_state.init_state(
        args,
        hooks=_isaac_init_hooks(),
        state_schema=STATE_SCHEMA,
        default_width=DEFAULT_WIDTH,
        default_height=DEFAULT_HEIGHT,
    )


def _isaac_init_hooks() -> isaac_worker_state.IsaacInitHooks:

    from roboclaws.backends.isaaclab.runtime_capture import (
        real_runtime_smoke,
    )
    from roboclaws.backends.isaaclab.runtime_commands import (
        _effective_scene_index,
        _initial_receptacle_id,
        _load_generated_mess_manifest,
        _real_smoke_robot_view_images,
        _robot_payload,
        _robot_view_provenance,
        _scenario_for_init,
        _scenario_source,
        _scene_specific_scenario_if_needed,
        _write_placeholder_image,
        write_state,
    )
    from roboclaws.backends.isaaclab.runtime_evidence import (
        runtime_diagnostics,
        scene_load_diagnostics,
        segmentation_diagnostics,
    )
    from roboclaws.backends.isaaclab.runtime_state import (
        _first_target_object_location,
        _initial_semantic_pose_state_from_state,
        _rby1m_robot_import_plan,
        _seed_generated_mess_placements,
    )

    return isaac_worker_state.IsaacInitHooks(
        dict_value=_dict,
        effective_scene_index=_effective_scene_index,
        fallback_room_outlines_from_indices=_fallback_room_outlines_from_indices,
        first_target_object_location=_first_target_object_location,
        index_or_default=_index_or_default,
        initial_receptacle_id=_initial_receptacle_id,
        initial_semantic_pose_state_from_state=_initial_semantic_pose_state_from_state,
        load_generated_mess_manifest=_load_generated_mess_manifest,
        mapping_gap_diagnostics=mapping_gap_diagnostics,
        object_index=_object_index,
        rby1m_robot_import_plan=_rby1m_robot_import_plan,
        real_runtime_smoke=real_runtime_smoke,
        real_smoke_robot_view_images=_real_smoke_robot_view_images,
        receptacle_index=_receptacle_index,
        robot_payload=_robot_payload,
        robot_view_provenance=_robot_view_provenance,
        room_outlines_from_scene_index_diagnostics=(_room_outlines_from_scene_index_diagnostics),
        runtime_diagnostics=runtime_diagnostics,
        scenario_for_init=_scenario_for_init,
        scenario_source=_scenario_source,
        scene_binding_diagnostics=_scene_binding_diagnostics,
        scene_load_diagnostics=scene_load_diagnostics,
        scene_specific_scenario_if_needed=_scene_specific_scenario_if_needed,
        seed_generated_mess_placements=_seed_generated_mess_placements,
        segmentation_diagnostics=segmentation_diagnostics,
        write_placeholder_image=_write_placeholder_image,
        write_state=write_state,
    )


def _usd_prim_geometry_diagnostics(*, usd_path: Path, prim: Any, usd_geom: Any) -> dict[str, Any]:

    from roboclaws.backends.isaaclab.runtime_capture import (
        _isaac_usd_scene_index_hooks,
    )

    return isaac_scene_index_geometry.usd_prim_geometry_diagnostics(
        usd_path=usd_path,
        prim=prim,
        usd_geom=usd_geom,
        hooks=_isaac_usd_scene_index_hooks(),
    )


def mapping_gap_diagnostics(
    *,
    runtime_mode: str,
    map_bundle_dir: Path | None,
    real_smoke: dict[str, Any] | None = None,
    scene_binding_diagnostics: dict[str, Any] | None = None,
    segmentation: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:

    from roboclaws.backends.isaaclab.runtime_commands import (
        _has_required_robot_view_images,
        _real_smoke_robot_view_images,
    )

    return isaac_mapping_diagnostics.mapping_gap_diagnostics(
        runtime_mode=runtime_mode,
        map_bundle_dir=map_bundle_dir,
        real_smoke=real_smoke,
        scene_binding_diagnostics=scene_binding_diagnostics,
        segmentation=segmentation,
        real_smoke_robot_view_images=_real_smoke_robot_view_images,
        has_required_robot_view_images=_has_required_robot_view_images,
        real_smoke_capture_method=REAL_SMOKE_CAPTURE_METHOD,
        real_robot_view_capture_method=REAL_ROBOT_VIEW_CAPTURE_METHOD,
    )
