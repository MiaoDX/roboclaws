#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import sys
import traceback
from pathlib import Path
from typing import Any, Callable

if __package__ in {None, ""}:
    repo_root = Path(__file__).resolve().parents[2]
    if str(repo_root) not in sys.path:
        sys.path.insert(0, str(repo_root))

from PIL import Image

from roboclaws.household.backend import HELD_LOCATION_ID
from roboclaws.household.camera_control import (
    DEFAULT_SCENE_PROBE_LIGHTING_PROFILE,
    normalize_camera_control_request,
)
from roboclaws.household.isaac_lab_backend import (
    ISAAC_SEMANTIC_POSE_EVENT_SCHEMA,
    ISAAC_SEMANTIC_POSE_STATE_SCHEMA,
    ISAAC_SEMANTIC_POSE_STATE_SOURCE,
)
from roboclaws.household.manipulation_contract import ISAAC_SEMANTIC_POSE_PROVENANCE
from roboclaws.household.types import (
    CleanupScenario,
)
from scripts.isaac_lab_cleanup import (
    isaac_camera_capture,
    isaac_camera_geometry,
    isaac_capture_quality,
    isaac_mapping_diagnostics,
    isaac_placement_resolution,
    isaac_render_diagnostics,
    isaac_robot_camera_stage,
    isaac_robot_import,
    isaac_robot_pose_focus,
    isaac_robot_view_artifacts,
    isaac_runtime_capture,
    isaac_runtime_diagnostics,
    isaac_runtime_smoke_usd,
    isaac_scenario_builders,
    isaac_scenario_state,
    isaac_scene_bindings,
    isaac_scene_camera_capture,
    isaac_scene_camera_geometry,
    isaac_scene_index_geometry,
    isaac_scene_index_metadata,
    isaac_segmentation_diagnostics,
    isaac_semantic_labels,
    isaac_semantic_pose_projection,
    isaac_semantic_pose_robot_view,
    isaac_semantic_pose_stage,
    isaac_semantic_pose_state,
    isaac_stage_lighting,
    isaac_support_surface_geometry,
    isaac_usd_xform,
    isaac_worker_cli,
    isaac_worker_commands,
    isaac_worker_context,
    isaac_worker_outputs,
    isaac_worker_protocol,
    isaac_worker_state,
)

STATE_SCHEMA = "isaac_lab_backend_state_v1"
DEFAULT_WIDTH = 540
DEFAULT_HEIGHT = 360
ROBOT_VIEW_KEYS = ("fpv", "chase", "topdown", "verify")
SCENE_BINDING_SCHEMA = isaac_scene_bindings.SCENE_BINDING_SCHEMA
_bind_public_scene_item = isaac_scene_bindings.bind_public_scene_item
_scene_binding_diagnostics = isaac_scene_bindings.scene_binding_diagnostics
_scene_index_match = isaac_scene_bindings.scene_index_match
_authored_reference_asset_paths = isaac_scene_index_geometry.authored_reference_asset_paths
_fallback_room_outlines_from_indices = (
    isaac_scene_index_geometry.fallback_room_outlines_from_indices
)
_is_local_reference_asset_path = isaac_scene_index_geometry.is_local_reference_asset_path
_local_reference_asset_missing = isaac_scene_index_geometry.local_reference_asset_missing
_room_outlines_from_scene_index_diagnostics = (
    isaac_scene_index_geometry.room_outlines_from_scene_index_diagnostics
)
_round_vec3 = isaac_scene_index_geometry.round_vec3
_usd_list_op_items = isaac_scene_index_geometry.usd_list_op_items
_category_from_usd_name = isaac_scene_index_metadata.category_from_usd_name
_contains_child_segment = isaac_scene_index_metadata.contains_child_segment
_is_molmospaces_object_metadata = isaac_scene_index_metadata.is_molmospaces_object_metadata
_is_molmospaces_receptacle_metadata = isaac_scene_index_metadata.is_molmospaces_receptacle_metadata
_is_object_prim_path = isaac_scene_index_metadata.is_object_prim_path
_is_receptacle_prim_path = isaac_scene_index_metadata.is_receptacle_prim_path
_load_molmospaces_scene_metadata = isaac_scene_index_metadata.load_molmospaces_scene_metadata
_merge_molmospaces_metadata_index = isaac_scene_index_metadata.merge_molmospaces_metadata_index
_metadata_room_id = isaac_scene_index_metadata.metadata_room_id
_molmospaces_metadata_prim_path = isaac_scene_index_metadata.molmospaces_metadata_prim_path
_molmospaces_prim_path_rank = isaac_scene_index_metadata.molmospaces_prim_path_rank
_usd_handle_from_prim = isaac_scene_index_metadata.usd_handle_from_prim
_usd_index_entry = isaac_scene_index_metadata.usd_index_entry
_usd_metadata_index_entry = isaac_scene_index_metadata.usd_metadata_index_entry
_usd_safe_name = isaac_scene_index_metadata.usd_safe_name
_MOLMOSPACES_SCENE_INDEX_RECEPTACLE_CATEGORY_NORMS = (
    isaac_scene_index_metadata.MOLMOSPACES_SCENE_INDEX_RECEPTACLE_CATEGORY_NORMS
)
_is_usd_renderable_support_candidate = (
    isaac_support_surface_geometry.is_usd_renderable_support_candidate
)
_support_pose_from_support_surface = (
    isaac_support_surface_geometry.support_pose_from_support_surface
)
_support_pose_from_usd_bounds = isaac_support_surface_geometry.support_pose_from_usd_bounds
_support_surface_from_usd_bounds = isaac_support_surface_geometry.support_surface_from_usd_bounds
_usd_support_surface_score = isaac_support_surface_geometry.usd_support_surface_score
_usd_support_surface_union = isaac_support_surface_geometry.usd_support_surface_union_entry
SEGMENTATION_SCHEMA = isaac_segmentation_diagnostics.SEGMENTATION_SCHEMA
ISAAC_NATIVE_RENDER_DIAGNOSTICS_SCHEMA = (
    isaac_render_diagnostics.ISAAC_NATIVE_RENDER_DIAGNOSTICS_SCHEMA
)
ISAAC_SEGMENTATION_DATA_TYPES = isaac_segmentation_diagnostics.ISAAC_SEGMENTATION_DATA_TYPES
MAX_SEGMENTATION_CANDIDATES = isaac_segmentation_diagnostics.MAX_SEGMENTATION_CANDIDATES
RBY1M_CHASE_CAMERA_OFFSET_M = isaac_camera_geometry.RBY1M_CHASE_CAMERA_OFFSET_M
RBY1M_CHASE_CAMERA_TARGET_OFFSET_M = isaac_camera_geometry.RBY1M_CHASE_CAMERA_TARGET_OFFSET_M
RBY1M_HEAD_CAMERA_ZERO_QUAT_WXYZ = isaac_camera_geometry.RBY1M_HEAD_CAMERA_ZERO_QUAT_WXYZ
RBY1M_HEAD_CAMERA_VERTICAL_FOV_DEG = isaac_camera_geometry.RBY1M_HEAD_CAMERA_VERTICAL_FOV_DEG
RBY1M_HEAD_CAMERA_FOCAL_LENGTH_MM = isaac_camera_geometry.RBY1M_HEAD_CAMERA_FOCAL_LENGTH_MM
REAL_SMOKE_CAPTURE_METHOD = "isaac_lab_camera_rgb"
REAL_ROBOT_VIEW_CAPTURE_METHOD = "isaac_lab_camera_rgb_static_robot_views"
REAL_ROBOT_VIEW_RERENDER_METHOD = "isaac_lab_camera_rgb_semantic_pose_robot_views"
REAL_SMOKE_RENDERER_MODE = "isaac_lab_headless_rtx"
PLACEMENT_DIAGNOSTIC_SCHEMA = isaac_placement_resolution.PLACEMENT_DIAGNOSTIC_SCHEMA
ISAAC_PLACEMENT_RESOLVER_SOURCE = isaac_placement_resolution.ISAAC_PLACEMENT_RESOLVER_SOURCE
ISAAC_DESCENDANT_SUPPORT_SURFACE_SOURCE = (
    isaac_support_surface_geometry.ISAAC_DESCENDANT_SUPPORT_SURFACE_SOURCE
)
ISAAC_DESCENDANT_SUPPORT_SURFACE_UNION_SOURCE = (
    isaac_support_surface_geometry.ISAAC_DESCENDANT_SUPPORT_SURFACE_UNION_SOURCE
)
ISAAC_WORLD_BOUNDS_SUPPORT_SURFACE_SOURCE = (
    isaac_support_surface_geometry.ISAAC_WORLD_BOUNDS_SUPPORT_SURFACE_SOURCE
)
ISAAC_RBY1M_ROBOT_IMPORT_SCHEMA = isaac_robot_import.ISAAC_RBY1M_ROBOT_IMPORT_SCHEMA
_DEFERRED_SIMULATION_APP: Any | None = None
_current_stage_bounds = isaac_stage_lighting.current_stage_bounds
_ensure_capture_lighting = isaac_stage_lighting.ensure_capture_lighting
_normalized_vec3 = isaac_stage_lighting.normalized_vec3
_isaac_distant_light_rotation_from_direction = (
    isaac_stage_lighting.isaac_distant_light_rotation_from_direction
)
_scale_stage_light_intensities = isaac_stage_lighting.scale_stage_light_intensities
_stage_light_paths = isaac_stage_lighting.stage_light_paths
_prim_type_is_light = isaac_stage_lighting.prim_type_is_light
_robot_view_color_profile = isaac_camera_geometry.robot_view_color_profile
_isaac_camera_view_poses = isaac_camera_geometry.isaac_camera_view_poses
_robot_relative_chase_eye_target = isaac_camera_geometry.robot_relative_chase_eye_target
_static_head_camera_pose_for_pitch = isaac_camera_geometry.static_head_camera_pose_for_pitch
_rotate_point_y_about_pivot = isaac_camera_geometry.rotate_point_y_about_pivot
_quat_from_axis_angle = isaac_camera_geometry.quat_from_axis_angle
_quat_multiply = isaac_camera_geometry.quat_multiply
_normalize_quat = isaac_camera_geometry.normalize_quat
_usd_camera_fov_metadata = isaac_camera_geometry.usd_camera_fov_metadata
_matrix4d_rowmajor = isaac_camera_geometry.matrix4d_rowmajor
_usd_attr_float = isaac_camera_geometry.usd_attr_float
_usd_vec = isaac_camera_geometry.usd_vec
_tensor_first_vec3 = isaac_camera_geometry.tensor_first_vec3
_robot_pose_yaw_deg = isaac_camera_geometry.robot_pose_yaw_deg
_optional_float = isaac_camera_geometry.optional_float
_load_camera_view_specs = isaac_scene_camera_geometry.load_camera_view_specs
_lane_camera_orbit = isaac_scene_camera_geometry.lane_camera_orbit
_backend_transform_for_lane = isaac_scene_camera_geometry.backend_transform_for_lane
_apply_scene_transform_to_point = isaac_scene_camera_geometry.apply_scene_transform_to_point
_camera_vec3 = isaac_scene_camera_geometry.camera_vec3
_image_has_variance = isaac_scene_camera_geometry.image_has_variance
_module_version = isaac_runtime_diagnostics.module_version
_generated_scene_filename = isaac_runtime_smoke_usd.generated_scene_filename
_isaac_native_render_diagnostics_unavailable = (
    isaac_render_diagnostics.native_render_diagnostics_unavailable
)
_native_setting_candidate_count = isaac_render_diagnostics.native_setting_candidate_count
_capture_quality_settings_unavailable = (
    isaac_render_diagnostics.capture_quality_settings_unavailable
)
_capture_quality_settings = isaac_render_diagnostics.capture_quality_settings
_isaac_setting_value = isaac_render_diagnostics.isaac_setting_value
_camera_render_product_paths = isaac_render_diagnostics.camera_render_product_paths
_render_product_paths_from_value = isaac_render_diagnostics.render_product_paths_from_value
_restore_isaac_capture_quality_overrides = (
    isaac_capture_quality.restore_isaac_capture_quality_overrides
)
_semantic_label_application_not_requested = (
    isaac_semantic_labels.semantic_label_application_not_requested
)
_semantic_label_target_prims = isaac_semantic_labels.semantic_label_target_prims
_set_usd_xform_translate = isaac_usd_xform.set_usd_xform_translate
_norm = isaac_worker_context.norm
_dict = isaac_worker_context.dict_value
_vec3 = isaac_worker_context.vec3
_has_xy = isaac_worker_context.has_xy
_index_or_default = isaac_worker_context.index_or_default
_objects_by_id = isaac_worker_context.objects_by_id
_receptacles_by_id = isaac_worker_context.receptacles_by_id
_object_index = isaac_worker_context.object_index
_receptacle_index = isaac_worker_context.receptacle_index
_pose_near = isaac_worker_context.pose_near
ISAAC_RBY1M_ROBOT_USD_PATH = isaac_robot_import.ISAAC_RBY1M_ROBOT_USD_PATH
ISAAC_RBY1M_ROBOT_IMPORT_SUMMARY_PATH = isaac_robot_import.ISAAC_RBY1M_ROBOT_IMPORT_SUMMARY_PATH


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    return isaac_worker_cli.build_arg_parser(
        default_width=DEFAULT_WIDTH,
        default_height=DEFAULT_HEIGHT,
        generated_scene_kinds=isaac_runtime_smoke_usd.GENERATED_SCENE_KINDS,
        segmentation_data_types=ISAAC_SEGMENTATION_DATA_TYPES,
    ).parse_args(argv)


type _IsaacWorkerCommand = Callable[[argparse.Namespace, dict[str, Any]], dict[str, Any]]


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    if args.command == "init":
        try:
            result = init_state(args)
        except Exception:
            traceback.print_exc()
            if _DEFERRED_SIMULATION_APP is not None:
                sys.stdout.flush()
                sys.stderr.flush()
                os._exit(1)
            raise
        return _finish_command(result)
    handler = _STATE_COMMANDS.get(args.command)
    if handler is None:  # pragma: no cover - argparse prevents this.
        raise ValueError(f"unsupported command: {args.command}")
    result = handler(args, read_state(args.state_path))
    return _finish_command(result)


def _finish_command(result: dict[str, Any]) -> int:
    print(json.dumps(result, sort_keys=True), flush=True)
    if _DEFERRED_SIMULATION_APP is not None:
        # Isaac/Omniverse shutdown can hang after the render artifacts and JSON
        # result are already written. The worker is one-shot, so prefer a hard
        # successful exit over turning completed captures into parent timeouts.
        sys.stdout.flush()
        sys.stderr.flush()
        os._exit(0)
    return 0


def _close_deferred_simulation_app() -> None:
    global _DEFERRED_SIMULATION_APP
    if _DEFERRED_SIMULATION_APP is None:
        return
    simulation_app = _DEFERRED_SIMULATION_APP
    _DEFERRED_SIMULATION_APP = None
    simulation_app.close(wait_for_replicator=False, skip_cleanup=True)


def init_state(args: argparse.Namespace) -> dict[str, Any]:
    return isaac_worker_state.init_state(
        args,
        hooks=_isaac_init_hooks(),
        state_schema=STATE_SCHEMA,
        default_width=DEFAULT_WIDTH,
        default_height=DEFAULT_HEIGHT,
    )


def _isaac_init_hooks() -> isaac_worker_state.IsaacInitHooks:
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


def _require_isaac_import() -> None:
    try:
        import isaaclab  # noqa: F401
    except Exception as exc:
        raise RuntimeError(
            "Isaac Lab runtime is unavailable. Install Isaac Sim / Isaac Lab in "
            ".venv-isaaclab/ or set ROBOCLAWS_ISAACLAB_RUNTIME_MODE=fake for "
            "CI protocol tests that do not claim renderer proof."
        ) from exc


def real_runtime_smoke(
    args: argparse.Namespace,
    scenario: CleanupScenario,
) -> dict[str, Any]:
    return isaac_runtime_capture.real_runtime_smoke(
        args,
        scenario,
        hooks=_isaac_runtime_capture_hooks(),
        default_width=DEFAULT_WIDTH,
        default_height=DEFAULT_HEIGHT,
        robot_view_keys=ROBOT_VIEW_KEYS,
        segmentation_data_types=ISAAC_SEGMENTATION_DATA_TYPES,
        real_smoke_renderer_mode=REAL_SMOKE_RENDERER_MODE,
        real_smoke_capture_method=REAL_SMOKE_CAPTURE_METHOD,
        real_robot_view_capture_method=REAL_ROBOT_VIEW_CAPTURE_METHOD,
    )


def capture_semantic_pose_robot_views(
    *,
    state: dict[str, Any],
    scene_usd: Path,
    view_paths: dict[str, Path],
    width: int,
    height: int,
    focus_object_id: str | None = None,
    focus_receptacle_id: str | None = None,
    color_profile_override: dict[str, Any] | None = None,
    render_settle_frames: int = 0,
    isaac_aa_op: int | None = None,
    isaac_tonemap_op: int | None = None,
    isaac_exposure_bias: float | None = None,
    isaac_colorcorr_gain: tuple[float, float, float] | None = None,
) -> dict[str, Any]:
    return isaac_runtime_capture.capture_semantic_pose_robot_views(
        state=state,
        scene_usd=scene_usd,
        view_paths=view_paths,
        width=width,
        height=height,
        hooks=_isaac_runtime_capture_hooks(),
        focus_object_id=focus_object_id,
        focus_receptacle_id=focus_receptacle_id,
        color_profile_override=color_profile_override,
        render_settle_frames=render_settle_frames,
        isaac_aa_op=isaac_aa_op,
        isaac_tonemap_op=isaac_tonemap_op,
        isaac_exposure_bias=isaac_exposure_bias,
        isaac_colorcorr_gain=isaac_colorcorr_gain,
    )


def _isaac_runtime_capture_hooks() -> isaac_runtime_capture.IsaacRuntimeCaptureHooks:
    return isaac_runtime_capture.IsaacRuntimeCaptureHooks(
        capture_isaac_lab_camera_views=_capture_isaac_lab_camera_views,
        dict_value=_dict,
        generated_scene_filename=isaac_runtime_smoke_usd.generated_scene_filename,
        inspect_usd_scene_index=_inspect_usd_scene_index,
        isaac_app_launcher_args=_isaac_app_launcher_args,
        module_version=_module_version,
        rby1m_robot_import_plan=_rby1m_robot_import_plan,
        require_isaac_import=_require_isaac_import,
        runtime_smoke_robot_view_paths=_runtime_smoke_robot_view_paths,
        scene_usd_path=_scene_usd_path,
        set_deferred_simulation_app=_set_deferred_simulation_app,
        write_generated_runtime_smoke_usd=isaac_runtime_smoke_usd.write_generated_runtime_smoke_usd,
    )


def _set_deferred_simulation_app(simulation_app: Any) -> None:
    global _DEFERRED_SIMULATION_APP
    _DEFERRED_SIMULATION_APP = simulation_app


def _isaac_app_launcher_args(app_launcher_type: Any) -> argparse.Namespace:
    parser = argparse.ArgumentParser(add_help=False)
    parser.add_argument("--width", type=int, default=DEFAULT_WIDTH)
    parser.add_argument("--height", type=int, default=DEFAULT_HEIGHT)
    app_launcher_type.add_app_launcher_args(parser)
    return parser.parse_args(
        [
            "--headless",
            "--enable_cameras",
            "--width",
            str(DEFAULT_WIDTH),
            "--height",
            str(DEFAULT_HEIGHT),
        ]
    )


def _inspect_usd_scene_index(usd_path: Path) -> dict[str, Any]:
    return isaac_scene_index_geometry.inspect_usd_scene_index(
        usd_path,
        hooks=_isaac_usd_scene_index_hooks(),
    )


def _isaac_usd_scene_index_hooks() -> isaac_scene_index_geometry.IsaacUsdSceneIndexHooks:
    return isaac_scene_index_geometry.IsaacUsdSceneIndexHooks(
        annotate_usd_index_geometry=_annotate_usd_index_geometry,
        authored_reference_asset_paths=_authored_reference_asset_paths,
        dict_value=_dict,
        iter_usd_prim_range=_iter_usd_prim_range,
        is_object_prim_path=_is_object_prim_path,
        is_receptacle_prim_path=_is_receptacle_prim_path,
        local_reference_asset_missing=_local_reference_asset_missing,
        merge_molmospaces_metadata_index=_merge_molmospaces_metadata_index,
        pose_near=_pose_near,
        room_outline_from_usd_prim=_room_outline_from_usd_prim,
        round_vec3=_round_vec3,
        support_pose_from_support_surface=_support_pose_from_support_surface,
        support_pose_from_usd_bounds=_support_pose_from_usd_bounds,
        usd_handle_from_prim=_usd_handle_from_prim,
        usd_index_entry=_usd_index_entry,
        usd_receptacle_support_surfaces=_usd_receptacle_support_surfaces,
        usd_world_bounds=_usd_world_bounds,
        usd_world_root_position=_usd_world_root_position,
    )


def _annotate_usd_index_geometry(
    *,
    usd_path: Path,
    stage: Any,
    object_index: dict[str, dict[str, Any]],
    receptacle_index: dict[str, dict[str, Any]],
    usd_geom: Any,
) -> None:
    return isaac_scene_index_geometry.annotate_usd_index_geometry(
        usd_path=usd_path,
        stage=stage,
        object_index=object_index,
        receptacle_index=receptacle_index,
        usd_geom=usd_geom,
        hooks=_isaac_usd_scene_index_hooks(),
    )


def _usd_prim_geometry_diagnostics(*, usd_path: Path, prim: Any, usd_geom: Any) -> dict[str, Any]:
    return isaac_scene_index_geometry.usd_prim_geometry_diagnostics(
        usd_path=usd_path,
        prim=prim,
        usd_geom=usd_geom,
        hooks=_isaac_usd_scene_index_hooks(),
    )


def _usd_world_bounds(prim: Any, *, usd_geom: Any) -> dict[str, Any] | None:
    return isaac_scene_index_geometry.usd_world_bounds(
        prim,
        usd_geom=usd_geom,
        round_vec3=_round_vec3,
    )


def _usd_world_root_position(prim: Any, *, usd_geom: Any) -> list[float] | None:
    return isaac_scene_index_geometry.usd_world_root_position(
        prim,
        usd_geom=usd_geom,
        round_vec3=_round_vec3,
    )


def _usd_receptacle_support_surfaces(*, prim: Any, usd_geom: Any) -> list[dict[str, Any]]:
    return isaac_scene_index_geometry.receptacle_support_surfaces(
        prim=prim,
        usd_geom=usd_geom,
        world_bounds=_usd_world_bounds,
        iter_prim_range=_iter_usd_prim_range,
    )


def _room_outline_from_usd_prim(
    prim_path: str,
    prim: Any,
    *,
    usd_geom: Any,
) -> dict[str, Any] | None:
    return isaac_scene_index_geometry.room_outline_from_usd_prim(
        prim_path,
        prim,
        usd_geom=usd_geom,
        world_bounds=_usd_world_bounds,
    )


def _iter_usd_prim_range(prim: Any) -> Any:
    return isaac_scene_index_geometry.iter_usd_prim_range(prim)


def _runtime_smoke_robot_view_paths(
    run_dir: Path,
    *,
    smoke_image: Path,
) -> dict[str, Path]:
    return {
        "fpv": smoke_image,
        "chase": run_dir / "isaac_runtime_smoke.chase.png",
        "topdown": run_dir / "isaac_runtime_smoke.topdown.png",
        "verify": run_dir / "isaac_runtime_smoke.verify.png",
    }


def _capture_isaac_lab_camera_views(
    *,
    scene_usd: Path,
    view_paths: dict[str, Path],
    width: int,
    height: int,
    simulation_app: Any,
    robot_import: dict[str, Any] | None = None,
    include_segmentation: bool = False,
    segmentation_data_types: tuple[str, ...] = ISAAC_SEGMENTATION_DATA_TYPES,
    semantic_filter: tuple[str, ...] = ("class",),
    scene_index_diagnostics: dict[str, Any] | None = None,
    semantic_pose_state: dict[str, Any] | None = None,
    color_profile_override: dict[str, Any] | None = None,
    render_settle_frames: int = 0,
    isaac_aa_op: int | None = None,
    isaac_tonemap_op: int | None = None,
    isaac_exposure_bias: float | None = None,
    isaac_colorcorr_gain: tuple[float, float, float] | None = None,
) -> dict[str, Any]:
    return isaac_camera_capture.capture_isaac_lab_camera_views(
        request=isaac_camera_capture.IsaacCameraCaptureRequest(
            scene_usd=scene_usd,
            view_paths=view_paths,
            width=width,
            height=height,
            simulation_app=simulation_app,
            robot_import=_dict(robot_import),
            include_segmentation=include_segmentation,
            segmentation_data_types=segmentation_data_types,
            semantic_filter=semantic_filter,
            scene_index_diagnostics=scene_index_diagnostics,
            semantic_pose_state=_dict(semantic_pose_state),
            color_profile_override=color_profile_override,
            render_settle_frames=render_settle_frames,
            isaac_aa_op=isaac_aa_op,
            isaac_tonemap_op=isaac_tonemap_op,
            isaac_exposure_bias=isaac_exposure_bias,
            isaac_colorcorr_gain=isaac_colorcorr_gain,
            robot_view_keys=ROBOT_VIEW_KEYS,
            head_camera_prim=isaac_camera_geometry.ISAAC_RBY1M_HEAD_CAMERA_PRIM,
            head_camera_vertical_fov_deg=(isaac_camera_geometry.RBY1M_HEAD_CAMERA_VERTICAL_FOV_DEG),
            head_camera_focal_length_mm=isaac_camera_geometry.RBY1M_HEAD_CAMERA_FOCAL_LENGTH_MM,
            renderer_mode=REAL_SMOKE_RENDERER_MODE,
            capture_method=REAL_ROBOT_VIEW_CAPTURE_METHOD,
            default_lighting_profile=DEFAULT_SCENE_PROBE_LIGHTING_PROFILE,
        ),
        hooks=isaac_camera_capture.IsaacCameraCaptureHooks(
            wait_for_stage_load=_wait_for_stage_load,
            load_current_stage_payloads=_load_current_stage_payloads,
            apply_semantic_pose_state_to_stage=_apply_semantic_pose_state_to_stage,
            ensure_rby1m_robot_on_stage=_ensure_rby1m_robot_on_stage,
            current_stage_bounds=_current_stage_bounds,
            ensure_capture_lighting=_ensure_capture_lighting,
            apply_scene_index_semantic_labels=_apply_scene_index_semantic_labels,
            semantic_label_application_not_requested=_semantic_label_application_not_requested,
            configure_rby1m_head_camera_lens=_configure_rby1m_head_camera_lens,
            horizontal_aperture_from_lens=_horizontal_aperture_from_lens,
            isaac_camera_view_poses=_isaac_camera_view_poses,
            isaac_settings_interface=_isaac_settings_interface,
            apply_isaac_capture_quality_overrides=_apply_isaac_capture_quality_overrides,
            isaac_native_render_diagnostics=_isaac_native_render_diagnostics,
            capture_quality_settings=_capture_quality_settings,
            camera_render_product_paths=_camera_render_product_paths,
            position_robot_for_head_camera_view=_position_robot_for_head_camera_view,
            usd_camera_diagnostics=_usd_camera_diagnostics,
            isaac_eye_target_camera_diagnostics=_isaac_eye_target_camera_diagnostics,
            robot_relative_chase_eye_target=_robot_relative_chase_eye_target,
            rgb_tensor_to_uint8=_rgb_tensor_to_uint8,
            image_has_variance=_image_has_variance,
            robot_view_color_profile=_robot_view_color_profile,
            camera_segmentation_view_diagnostics=_camera_segmentation_view_diagnostics,
            restore_isaac_capture_quality_overrides=_restore_isaac_capture_quality_overrides,
            camera_segmentation_capture_diagnostics=_camera_segmentation_capture_diagnostics,
            camera_segmentation_not_requested_diagnostics=(
                _camera_segmentation_not_requested_diagnostics
            ),
        ),
    )


def _capture_scene_camera_request_with_existing_sim(
    *,
    camera_request: dict[str, Any],
    output_dir: Path,
    width: int,
    height: int,
    sim: Any,
    sim_utils: Any,
    stage_utils: Any,
    camera_type: Any,
    camera_cfg_type: Any,
    torch: Any,
    np: Any,
    scene_bounds: dict[str, Any],
) -> dict[str, Any]:
    return isaac_scene_camera_capture.capture_scene_camera_request_with_existing_sim(
        camera_request=camera_request,
        output_dir=output_dir,
        width=width,
        height=height,
        sim=sim,
        sim_utils=sim_utils,
        stage_utils=stage_utils,
        camera_type=camera_type,
        camera_cfg_type=camera_cfg_type,
        torch=torch,
        np=np,
        scene_bounds=scene_bounds,
        normalize_camera_control_request=normalize_camera_control_request,
        ensure_capture_lighting=_ensure_capture_lighting,
        horizontal_aperture_from_lens=_horizontal_aperture_from_lens,
        isaac_native_render_diagnostics=_isaac_native_render_diagnostics,
        camera_render_product_paths=_camera_render_product_paths,
        isaac_scene_camera_view_spec=_isaac_scene_camera_view_spec,
        rgb_tensor_to_uint8=_rgb_tensor_to_uint8,
        image_has_variance=_image_has_variance,
        renderer_mode=REAL_SMOKE_RENDERER_MODE,
    )


def capture_scene_camera_views(
    *,
    scene_usd: Path,
    camera_request: dict[str, Any] | list[dict[str, Any]],
    output_dir: Path,
    width: int,
    height: int,
    semantic_pose_state: dict[str, Any] | None = None,
) -> dict[str, Any]:
    from isaaclab.app import AppLauncher

    launcher_args = _isaac_app_launcher_args(AppLauncher)
    app_launcher = AppLauncher(launcher_args)
    simulation_app = app_launcher.app
    global _DEFERRED_SIMULATION_APP
    _DEFERRED_SIMULATION_APP = simulation_app
    return _capture_isaac_lab_scene_camera_views(
        scene_usd=scene_usd,
        camera_request=camera_request,
        output_dir=output_dir,
        width=width,
        height=height,
        simulation_app=simulation_app,
        semantic_pose_state=semantic_pose_state,
    )


def _capture_isaac_lab_scene_camera_views(
    *,
    scene_usd: Path,
    camera_request: dict[str, Any] | list[dict[str, Any]],
    output_dir: Path,
    width: int,
    height: int,
    simulation_app: Any,
    semantic_pose_state: dict[str, Any] | None = None,
) -> dict[str, Any]:
    return isaac_scene_camera_capture.capture_isaac_lab_scene_camera_views(
        request=isaac_scene_camera_capture.IsaacSceneCameraCaptureRequest(
            scene_usd=scene_usd,
            camera_request=camera_request,
            output_dir=output_dir,
            width=width,
            height=height,
            simulation_app=simulation_app,
            semantic_pose_state=_dict(semantic_pose_state),
            renderer_mode=REAL_SMOKE_RENDERER_MODE,
        ),
        hooks=isaac_scene_camera_capture.IsaacSceneCameraCaptureHooks(
            normalize_camera_control_request=normalize_camera_control_request,
            wait_for_stage_load=_wait_for_stage_load,
            load_current_stage_payloads=_load_current_stage_payloads,
            apply_semantic_pose_state_to_stage=_apply_semantic_pose_state_to_stage,
            current_stage_bounds=_current_stage_bounds,
            ensure_capture_lighting=_ensure_capture_lighting,
            horizontal_aperture_from_lens=_horizontal_aperture_from_lens,
            isaac_native_render_diagnostics=_isaac_native_render_diagnostics,
            camera_render_product_paths=_camera_render_product_paths,
            isaac_scene_camera_view_spec=_isaac_scene_camera_view_spec,
            rgb_tensor_to_uint8=_rgb_tensor_to_uint8,
            image_has_variance=_image_has_variance,
        ),
    )


def _apply_semantic_pose_state_to_stage(
    *,
    stage_utils: Any,
    semantic_pose_state: dict[str, Any] | None,
) -> dict[str, Any]:
    return isaac_semantic_pose_stage.apply_semantic_pose_state_to_stage(
        stage_utils=stage_utils,
        semantic_pose_state=semantic_pose_state,
        hooks=isaac_semantic_pose_stage.IsaacSemanticPoseStageHooks(
            dict_value=_dict,
            set_usd_xform_translate=_set_usd_xform_translate,
            semantic_pose_target_position=_semantic_pose_target_position,
            vec3=_vec3,
            world_position_to_parent_local_translate=_world_position_to_parent_local_translate,
        ),
    )


def _world_position_to_parent_local_translate(
    *,
    UsdGeom: Any,
    prim: Any,
    world_position: tuple[float, float, float],
) -> tuple[float, float, float]:
    return isaac_semantic_pose_stage.world_position_to_parent_local_translate(
        UsdGeom=UsdGeom,
        prim=prim,
        world_position=world_position,
    )


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


def _load_current_stage_payloads(stage_utils: Any) -> None:
    get_current_stage = getattr(stage_utils, "get_current_stage", None)
    if not callable(get_current_stage):
        return
    stage = get_current_stage()
    if stage is None:
        return
    try:
        stage.Load()
    except Exception:
        return


def _apply_scene_index_semantic_labels(
    *,
    stage_utils: Any,
    sim_utils: Any,
    scene_index_diagnostics: dict[str, Any] | None,
) -> dict[str, Any]:
    return isaac_semantic_labels.apply_scene_index_semantic_labels(
        stage_utils=stage_utils,
        sim_utils=sim_utils,
        scene_index_diagnostics=scene_index_diagnostics,
        target_prim_resolver=_semantic_label_target_prims,
    )


def _camera_segmentation_view_diagnostics(
    camera: Any,
    *,
    data_types: tuple[str, ...] = ISAAC_SEGMENTATION_DATA_TYPES,
    view_name: str,
    np: Any,
) -> dict[str, Any]:
    return isaac_segmentation_diagnostics.camera_segmentation_view_diagnostics(
        camera,
        data_types=data_types,
        view_name=view_name,
        np=np,
        max_candidates=MAX_SEGMENTATION_CANDIDATES,
    )


def _camera_segmentation_capture_diagnostics(
    views: list[dict[str, Any]],
    *,
    requested_data_types: tuple[str, ...] = ISAAC_SEGMENTATION_DATA_TYPES,
    semantic_label_application: dict[str, Any] | None = None,
    semantic_filter: str | list[str] | None = None,
) -> dict[str, Any]:
    return isaac_segmentation_diagnostics.camera_segmentation_capture_diagnostics(
        views,
        requested_data_types=requested_data_types,
        semantic_label_application=semantic_label_application,
        semantic_filter=semantic_filter,
        max_candidates=MAX_SEGMENTATION_CANDIDATES,
    )


def _camera_segmentation_not_requested_diagnostics() -> dict[str, Any]:
    return isaac_segmentation_diagnostics.camera_segmentation_not_requested_diagnostics(
        requested_data_types=ISAAC_SEGMENTATION_DATA_TYPES,
    )


def _ensure_rby1m_robot_on_stage(
    *,
    stage_utils: Any,
    robot_import: dict[str, Any],
) -> dict[str, Any]:
    return isaac_robot_camera_stage.ensure_rby1m_robot_on_stage(
        stage_utils=stage_utils,
        robot_import=robot_import,
    )


def _isaac_robot_camera_stage_hooks() -> isaac_robot_camera_stage.IsaacRobotCameraStageHooks:
    return isaac_robot_camera_stage.IsaacRobotCameraStageHooks(
        dict_value=_dict,
        has_xy=_has_xy,
        horizontal_aperture_from_lens=_horizontal_aperture_from_lens,
        matrix4d_rowmajor=_matrix4d_rowmajor,
        optional_float=_optional_float,
        robot_pose_yaw_deg=_robot_pose_yaw_deg,
        static_head_camera_pose_for_pitch=_static_head_camera_pose_for_pitch,
        tensor_first_vec3=_tensor_first_vec3,
        usd_attr_float=_usd_attr_float,
        usd_camera_fov_metadata=_usd_camera_fov_metadata,
        usd_vec=_usd_vec,
    )


def _position_robot_for_head_camera_view(
    *,
    stage_utils: Any,
    scene_bounds: dict[str, list[float]] | None,
    semantic_pose_state: dict[str, Any] | None = None,
) -> dict[str, Any]:
    return isaac_robot_camera_stage.position_robot_for_head_camera_view(
        stage_utils=stage_utils,
        scene_bounds=scene_bounds,
        semantic_pose_state=semantic_pose_state,
        hooks=_isaac_robot_camera_stage_hooks(),
    )


def _apply_static_head_camera_pitch(
    *,
    stage: Any,
    head_pitch: float | None,
) -> dict[str, Any]:
    return isaac_robot_camera_stage.apply_static_head_camera_pitch(
        stage=stage,
        head_pitch=head_pitch,
        hooks=_isaac_robot_camera_stage_hooks(),
    )


def _static_head_pitch_note(head_pitch_application: dict[str, Any]) -> str:
    return isaac_robot_camera_stage.static_head_pitch_note(head_pitch_application)


def _usd_camera_diagnostics(
    *,
    stage_utils: Any,
    prim_path: str,
    view_name: str,
    width: int,
    height: int,
    robot_pose_application: dict[str, Any] | None = None,
    lens_application: dict[str, Any] | None = None,
) -> dict[str, Any]:
    return isaac_robot_camera_stage.usd_camera_diagnostics(
        stage_utils=stage_utils,
        prim_path=prim_path,
        view_name=view_name,
        width=width,
        height=height,
        robot_pose_application=robot_pose_application,
        lens_application=lens_application,
        hooks=_isaac_robot_camera_stage_hooks(),
    )


def _isaac_eye_target_camera_diagnostics(
    *,
    view_name: str,
    positions: Any,
    targets: Any,
    width: int,
    height: int,
    camera_basis: str = "scene_bounds_eye_target",
) -> dict[str, Any]:
    return isaac_robot_camera_stage.isaac_eye_target_camera_diagnostics(
        view_name=view_name,
        positions=positions,
        targets=targets,
        width=width,
        height=height,
        camera_basis=camera_basis,
        hooks=_isaac_robot_camera_stage_hooks(),
    )


def _configure_rby1m_head_camera_lens(
    *,
    stage_utils: Any,
    width: int,
    height: int,
) -> dict[str, Any]:
    return isaac_robot_camera_stage.configure_rby1m_head_camera_lens(
        stage_utils=stage_utils,
        width=width,
        height=height,
        hooks=_isaac_robot_camera_stage_hooks(),
    )


def _wait_for_stage_load(stage_utils: Any, simulation_app: Any) -> None:
    is_loading = getattr(stage_utils, "is_stage_loading", None)
    if not callable(is_loading):
        return
    for _ in range(240):
        if not is_loading():
            return
        simulation_app.update()
    raise RuntimeError("Isaac Sim did not finish loading the generated USD stage")


def _rgb_tensor_to_uint8(value: Any, *, np: Any) -> Any:
    if value is None:
        return None
    if hasattr(value, "detach"):
        value = value.detach().cpu().numpy()
    array = np.asarray(value)
    if array.ndim == 4:
        array = array[0]
    if array.ndim != 3:
        raise RuntimeError(f"unexpected Isaac camera RGB tensor shape: {array.shape}")
    if array.shape[-1] > 3:
        array = array[..., :3]
    if array.shape[-1] != 3:
        raise RuntimeError(f"unexpected Isaac camera RGB channel count: {array.shape}")
    if array.dtype.kind == "f":
        scale = 255.0 if float(array.max(initial=0.0)) <= 1.0 else 1.0
        array = array * scale
    return np.clip(array, 0, 255).astype("uint8")


def _load_camera_request_from_args(
    *,
    view_specs_path: Path | None,
    camera_request_path: Path | None,
    width: int,
    height: int,
) -> dict[str, Any]:
    return isaac_scene_camera_geometry.load_camera_request_from_args(
        view_specs_path=view_specs_path,
        camera_request_path=camera_request_path,
        width=width,
        height=height,
    )


def _isaac_scene_camera_view_spec(
    raw_spec: dict[str, Any],
    *,
    index: int,
    stage_utils: Any | None = None,
) -> dict[str, Any]:
    return isaac_scene_camera_geometry.isaac_scene_camera_view_spec(
        raw_spec,
        index=index,
        stage_utils=stage_utils,
    )


def _horizontal_aperture_from_lens(
    lens: dict[str, Any],
    *,
    width: int,
    height: int,
    focal_length: float,
) -> float:
    return isaac_camera_geometry.horizontal_aperture_from_lens(
        lens,
        width=width,
        height=height,
        focal_length=focal_length,
    )


def _bounds_from_usd_prim_path(
    *,
    stage_utils: Any | None,
    usd_prim_path: str,
    min_target_z: float,
) -> dict[str, Any] | None:
    return isaac_scene_camera_geometry.bounds_from_usd_prim_path(
        stage_utils=stage_utils,
        usd_prim_path=usd_prim_path,
        min_target_z=min_target_z,
    )


def _eye_from_lookat_spec(
    *,
    target: list[float],
    distance: float,
    azimuth: float,
    elevation: float,
) -> list[float]:
    return isaac_scene_camera_geometry.eye_from_lookat_spec(
        target=target,
        distance=distance,
        azimuth=azimuth,
        elevation=elevation,
    )


def runtime_diagnostics(
    runtime_mode: str,
    *,
    real_smoke: dict[str, Any] | None = None,
) -> dict[str, Any]:
    return isaac_runtime_diagnostics.runtime_diagnostics(
        runtime_mode,
        real_smoke=real_smoke,
        default_width=DEFAULT_WIDTH,
        default_height=DEFAULT_HEIGHT,
        primitive_provenance=ISAAC_SEMANTIC_POSE_PROVENANCE,
        real_smoke_renderer_mode=REAL_SMOKE_RENDERER_MODE,
        real_smoke_capture_method=REAL_SMOKE_CAPTURE_METHOD,
    )


def rendering_diagnostics(
    runtime_mode: str,
    *,
    real_smoke: dict[str, Any] | None = None,
) -> dict[str, Any]:
    return isaac_runtime_diagnostics.rendering_diagnostics(
        runtime_mode,
        real_smoke=real_smoke,
        real_smoke_renderer_mode=REAL_SMOKE_RENDERER_MODE,
        real_smoke_capture_method=REAL_SMOKE_CAPTURE_METHOD,
    )


def _isaac_native_render_diagnostics(
    *,
    renderer_mode: str,
    capture_method: str,
    view_kind: str,
    render_resolution: dict[str, Any],
    camera_prim_paths: list[str],
    render_product_paths: list[str] | None = None,
    isaac_lab_isp_active: bool = False,
    capture_quality_settings: dict[str, Any] | None = None,
) -> dict[str, Any]:
    return isaac_render_diagnostics.native_render_diagnostics(
        renderer_mode=renderer_mode,
        capture_method=capture_method,
        view_kind=view_kind,
        render_resolution=render_resolution,
        camera_prim_paths=camera_prim_paths,
        settings=_isaac_settings_interface(),
        render_product_paths=render_product_paths,
        isaac_lab_isp_active=isaac_lab_isp_active,
        capture_quality_settings=capture_quality_settings,
    )


def _apply_isaac_capture_quality_overrides(
    *,
    settings: Any | None,
    isaac_aa_op: int | None,
    isaac_tonemap_op: int | None = None,
    isaac_exposure_bias: float | None = None,
    isaac_colorcorr_gain: tuple[float, float, float] | None = None,
) -> dict[str, Any]:
    return isaac_capture_quality.apply_isaac_capture_quality_overrides(
        settings=settings,
        setting_paths=isaac_render_diagnostics.ISAAC_NATIVE_RENDER_SETTING_PATHS,
        capture_quality_fields=isaac_render_diagnostics.ISAAC_CAPTURE_QUALITY_SETTING_FIELDS,
        isaac_aa_op=isaac_aa_op,
        isaac_tonemap_op=isaac_tonemap_op,
        isaac_exposure_bias=isaac_exposure_bias,
        isaac_colorcorr_gain=isaac_colorcorr_gain,
    )


def _isaac_settings_interface() -> Any | None:
    try:
        import carb.settings  # type: ignore[import-untyped]

        return carb.settings.get_settings()
    except Exception:
        return None


def scene_load_diagnostics(
    runtime_mode: str,
    scene_source: str,
    scene_index: int,
    *,
    real_smoke: dict[str, Any] | None = None,
) -> dict[str, Any]:
    return isaac_mapping_diagnostics.scene_load_diagnostics(
        runtime_mode,
        scene_source,
        scene_index,
        real_smoke=real_smoke,
    )


def segmentation_diagnostics(
    runtime_mode: str,
    *,
    real_smoke: dict[str, Any] | None = None,
    scene_binding_diagnostics: dict[str, Any] | None = None,
) -> dict[str, Any]:
    return isaac_segmentation_diagnostics.segmentation_diagnostics(
        runtime_mode,
        real_smoke=real_smoke,
        scene_binding_diagnostics=scene_binding_diagnostics,
        requested_data_types=ISAAC_SEGMENTATION_DATA_TYPES,
        max_candidates=MAX_SEGMENTATION_CANDIDATES,
    )


def mapping_gap_diagnostics(
    *,
    runtime_mode: str,
    map_bundle_dir: Path | None,
    real_smoke: dict[str, Any] | None = None,
    scene_binding_diagnostics: dict[str, Any] | None = None,
    segmentation: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
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


def _isaac_worker_command_hooks() -> isaac_worker_commands.IsaacWorkerCommandHooks:
    return isaac_worker_commands.IsaacWorkerCommandHooks(
        apply_object_location=_apply_object_location,
        count=_count,
        dict_value=_dict,
        error=_error,
        has_xy=_has_xy,
        isaac_placement_diagnostic=_isaac_placement_diagnostic,
        objects_by_id=_objects_by_id,
        ok=_ok,
        public_state=_public_state,
        receptacles_by_id=_receptacles_by_id,
        record_semantic_pose_event=_record_semantic_pose_event,
        record_waypoint_pose_event=_record_waypoint_pose_event,
        robot_pose_for_receptacle=_robot_pose_for_receptacle,
        robot_pose_for_waypoint=_robot_pose_for_waypoint,
        scenario_from_state=scenario_from_state,
        write_state_from_state_arg=write_state_from_state_arg,
    )


def _with_isaac_worker_command_hooks(func: Callable[..., Any]) -> Callable[..., Any]:
    def call(*args: Any, **kwargs: Any) -> Any:
        return func(*args, **kwargs, hooks=_isaac_worker_command_hooks())

    return call


observe = _with_isaac_worker_command_hooks(isaac_worker_commands.observe)
navigate_to_object = _with_isaac_worker_command_hooks(isaac_worker_commands.navigate_to_object)
navigate_to_receptacle = _with_isaac_worker_command_hooks(
    isaac_worker_commands.navigate_to_receptacle
)
navigate_to_waypoint = _with_isaac_worker_command_hooks(isaac_worker_commands.navigate_to_waypoint)
navigate_to_relative_pose = _with_isaac_worker_command_hooks(
    isaac_worker_commands.navigate_to_relative_pose
)
pick = _with_isaac_worker_command_hooks(isaac_worker_commands.pick)
open_receptacle = _with_isaac_worker_command_hooks(isaac_worker_commands.open_receptacle)
close_receptacle = _with_isaac_worker_command_hooks(isaac_worker_commands.close_receptacle)
done = _with_isaac_worker_command_hooks(isaac_worker_commands.done)


def place(args: argparse.Namespace, state: dict[str, Any], *, relation: str) -> dict[str, Any]:
    return isaac_worker_commands.place(
        args, state, relation=relation, hooks=_isaac_worker_command_hooks()
    )


def _isaac_worker_output_hooks() -> isaac_worker_outputs.IsaacWorkerOutputHooks:
    return isaac_worker_outputs.IsaacWorkerOutputHooks(
        camera_capture_provenance=_camera_capture_provenance,
        camera_capture_variant=_camera_capture_variant,
        capture_scene_camera_views=capture_scene_camera_views,
        copy_real_robot_view_images=_copy_real_robot_view_images,
        copy_real_snapshot_image=_copy_real_snapshot_image,
        count=_count,
        dict_value=_dict,
        error=_error,
        has_xy=_has_xy,
        load_camera_request_from_args=_load_camera_request_from_args,
        native_render_diagnostics_from_state=_native_render_diagnostics_from_state,
        ok=_ok,
        real_rendering_proven=_real_rendering_proven,
        real_robot_view_images=_real_robot_view_images,
        real_semantic_pose_robot_view_images=_real_semantic_pose_robot_view_images,
        real_snapshot_source_image=_real_snapshot_source_image,
        robot_pose_for_receptacle=_robot_pose_for_receptacle,
        robot_view_camera_control_contract=_robot_view_camera_control_contract,
        robot_view_command_provenance=_robot_view_command_provenance,
        robot_view_focus=_robot_view_focus,
        robot_view_rendered_robot_pose=_robot_view_rendered_robot_pose,
        safe_file_stem=_safe_file_stem,
        write_placeholder_image=_write_placeholder_image,
        write_state_from_state_arg=write_state_from_state_arg,
        real_smoke_capture_method=REAL_SMOKE_CAPTURE_METHOD,
    )


def _with_isaac_worker_output_hooks(func: Callable[..., Any]) -> Callable[..., Any]:
    def call(*args: Any, **kwargs: Any) -> Any:
        return func(*args, **kwargs, hooks=_isaac_worker_output_hooks())

    return call


write_snapshot = _with_isaac_worker_output_hooks(isaac_worker_outputs.write_snapshot)
write_robot_views = _with_isaac_worker_output_hooks(isaac_worker_outputs.write_robot_views)
_robot_view_rendered_robot_pose = _with_isaac_worker_output_hooks(
    isaac_worker_outputs.robot_view_rendered_robot_pose
)
write_camera_views = _with_isaac_worker_output_hooks(isaac_worker_outputs.write_camera_views)


def _locations_command(args: argparse.Namespace, state: dict[str, Any]) -> dict[str, Any]:
    return isaac_worker_outputs.locations_command(args, state)


_STATE_COMMANDS: dict[str, _IsaacWorkerCommand] = {
    "locations": _locations_command,
    "snapshot": write_snapshot,
    "robot_views": write_robot_views,
    "camera_views": write_camera_views,
    "observe": observe,
    "navigate_to_object": navigate_to_object,
    "navigate_to_waypoint": navigate_to_waypoint,
    "navigate_to_relative_pose": navigate_to_relative_pose,
    "navigate_to_receptacle": navigate_to_receptacle,
    "pick": pick,
    "open_receptacle": open_receptacle,
    "place": lambda args, state: place(args, state, relation="on"),
    "place_inside": lambda args, state: place(args, state, relation="inside"),
    "close_receptacle": close_receptacle,
    "done": done,
}


def _robot_view_camera_control_contract(
    state: dict[str, Any],
    *,
    robot_pose: dict[str, Any] | None = None,
    focus: dict[str, Any] | None = None,
) -> dict[str, Any]:
    return isaac_worker_outputs.robot_view_camera_control_contract(
        state,
        robot_pose=robot_pose,
        focus=focus,
        hooks=_isaac_worker_output_hooks(),
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


_target_room_id_from_pose_inputs = _with_isaac_robot_pose_hooks(
    isaac_robot_pose_focus.target_room_id_from_pose_inputs
)
_robot_pose_for_receptacle = _with_isaac_robot_pose_hooks(
    isaac_robot_pose_focus.robot_pose_for_receptacle
)
_robot_pose_for_waypoint = _with_isaac_robot_pose_hooks(
    isaac_robot_pose_focus.robot_pose_for_waypoint
)
_normalized_waypoint_robot_pose = _with_isaac_robot_pose_hooks(
    isaac_robot_pose_focus.normalized_waypoint_robot_pose
)
_receptacle_support_pose = _with_isaac_robot_pose_hooks(
    isaac_robot_pose_focus.receptacle_support_pose
)
_robot_view_focus = _with_isaac_robot_pose_hooks(isaac_robot_pose_focus.robot_view_focus)
_focus_payload = _with_isaac_robot_pose_hooks(isaac_robot_pose_focus.focus_payload)


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


_camera_capture_variant = isaac_worker_outputs.camera_capture_variant
_camera_capture_provenance = isaac_worker_outputs.camera_capture_provenance


def _real_semantic_pose_robot_view_images(
    state: dict[str, Any],
    target_images: dict[str, Path],
    *,
    width: int,
    height: int,
    camera_yaw_offset_deg: float = 0.0,
    camera_pitch_offset_deg: float = 0.0,
    render_settle_frames: int = 0,
    isaac_aa_op: int | None = None,
    isaac_tonemap_op: int | None = None,
    isaac_exposure_bias: float | None = None,
    isaac_colorcorr_gain: tuple[float, float, float] | None = None,
    focus_object_id: str | None = None,
    focus_receptacle_id: str | None = None,
) -> dict[str, str]:
    return isaac_semantic_pose_robot_view.real_semantic_pose_robot_view_images(
        isaac_semantic_pose_robot_view.SemanticPoseRobotViewRequest(
            state=state,
            target_images=target_images,
            width=width,
            height=height,
            camera_yaw_offset_deg=camera_yaw_offset_deg,
            camera_pitch_offset_deg=camera_pitch_offset_deg,
            render_settle_frames=render_settle_frames,
            isaac_aa_op=isaac_aa_op,
            isaac_tonemap_op=isaac_tonemap_op,
            isaac_exposure_bias=isaac_exposure_bias,
            isaac_colorcorr_gain=isaac_colorcorr_gain,
            focus_object_id=focus_object_id,
            focus_receptacle_id=focus_receptacle_id,
        ),
        hooks=isaac_semantic_pose_robot_view.SemanticPoseRobotViewHooks(
            capture_semantic_pose_robot_views=capture_semantic_pose_robot_views,
            has_required_robot_view_images=_has_required_robot_view_images,
            semantic_pose_robot_view_provenance=_semantic_pose_robot_view_provenance,
            write_state_from_state_arg=write_state_from_state_arg,
        ),
        real_robot_view_rerender_method=REAL_ROBOT_VIEW_RERENDER_METHOD,
        isaac_rby1m_head_camera_prim=isaac_camera_geometry.ISAAC_RBY1M_HEAD_CAMERA_PRIM,
    )


def _real_robot_view_images(state: dict[str, Any]) -> dict[str, str]:
    return isaac_robot_view_artifacts.real_robot_view_images(state, robot_view_keys=ROBOT_VIEW_KEYS)


def _native_render_diagnostics_from_state(state: dict[str, Any]) -> dict[str, Any]:
    diagnostics = _dict(state.get("native_render_diagnostics"))
    if diagnostics:
        return diagnostics
    diagnostics = _dict(
        _dict(state.get("robot_view_camera_diagnostics")).get("native_render_diagnostics")
    )
    if diagnostics:
        return diagnostics
    diagnostics = _dict(
        _dict(_dict(state.get("runtime")).get("rendering")).get("native_render_diagnostics")
    )
    if diagnostics:
        return diagnostics
    return _isaac_native_render_diagnostics_unavailable(
        runtime_mode=str(_dict(state.get("runtime")).get("runtime_mode") or "fake"),
        reason="worker state did not contain native render diagnostics",
    )


def _real_smoke_robot_view_images(real_smoke: dict[str, Any] | None) -> dict[str, str]:
    return isaac_robot_view_artifacts.real_smoke_robot_view_images(
        real_smoke, robot_view_keys=ROBOT_VIEW_KEYS
    )


def _has_required_robot_view_images(images: dict[str, str]) -> bool:
    return isaac_robot_view_artifacts.has_required_robot_view_images(
        images, robot_view_keys=ROBOT_VIEW_KEYS
    )


def _copy_real_robot_view_images(
    source_images: dict[str, str],
    target_images: dict[str, Path],
    *,
    width: int,
    height: int,
) -> dict[str, list[int]]:
    return isaac_robot_view_artifacts.copy_real_robot_view_images(
        source_images,
        target_images,
        width=width,
        height=height,
        robot_view_keys=ROBOT_VIEW_KEYS,
    )


def _real_snapshot_source_image(state: dict[str, Any]) -> Path:
    return isaac_robot_view_artifacts.real_snapshot_source_image(
        state, robot_view_keys=ROBOT_VIEW_KEYS
    )


def _copy_real_snapshot_image(
    source: Path,
    target: Path,
    *,
    width: int,
    height: int,
) -> list[int]:
    return isaac_robot_view_artifacts.copy_real_snapshot_image(
        source, target, width=width, height=height
    )


def _copy_nonblank_rgb_image(
    source: Path,
    target: Path,
    *,
    width: int,
    height: int,
    description: str,
) -> list[int]:
    return isaac_robot_view_artifacts.copy_nonblank_rgb_image(
        source,
        target,
        width=width,
        height=height,
        description=description,
    )


def _pil_image_has_variance(image: Image.Image) -> bool:
    return isaac_robot_view_artifacts.pil_image_has_variance(image)


def _real_rendering_proven(state: dict[str, Any]) -> bool:
    return isaac_robot_view_artifacts.real_rendering_proven(state)


def _robot_view_provenance(
    runtime_mode: str,
    real_smoke: dict[str, Any] | None,
) -> dict[str, Any]:
    return isaac_robot_view_artifacts.robot_view_provenance(
        runtime_mode,
        real_smoke,
        robot_view_keys=ROBOT_VIEW_KEYS,
        real_robot_view_capture_method=REAL_ROBOT_VIEW_CAPTURE_METHOD,
    )


def _robot_view_command_provenance(
    state: dict[str, Any],
    *,
    semantic_pose_state_refreshed: bool,
) -> dict[str, Any]:
    return isaac_robot_view_artifacts.robot_view_command_provenance(
        state,
        semantic_pose_state_refreshed=semantic_pose_state_refreshed,
        robot_view_keys=ROBOT_VIEW_KEYS,
        real_robot_view_rerender_method=REAL_ROBOT_VIEW_RERENDER_METHOD,
    )


def _semantic_pose_robot_view_provenance(
    *,
    mounted_head_camera: bool = False,
    head_camera_equivalent: bool = False,
) -> dict[str, Any]:
    return isaac_robot_view_artifacts.semantic_pose_robot_view_provenance(
        mounted_head_camera=mounted_head_camera,
        head_camera_equivalent=head_camera_equivalent,
        robot_view_keys=ROBOT_VIEW_KEYS,
        real_robot_view_rerender_method=REAL_ROBOT_VIEW_RERENDER_METHOD,
    )


_safe_file_stem = isaac_worker_protocol.safe_file_stem
_write_placeholder_image = isaac_worker_protocol.write_placeholder_image
_ok = isaac_worker_protocol.ok_response
_error = isaac_worker_protocol.error_response
read_state = isaac_worker_protocol.read_state
write_state = isaac_worker_protocol.write_state
write_state_from_state_arg = isaac_worker_protocol.write_state_from_state_arg
_count = isaac_worker_protocol.count_tool_request
_public_state = isaac_worker_protocol.public_state
scenario_from_state = isaac_scenario_builders.scenario_from_state
_load_generated_mess_manifest = isaac_scenario_builders.load_generated_mess_manifest
_scenario_for_init = isaac_scenario_builders.scenario_for_init
_scenario_source = isaac_scenario_builders.scenario_source
_effective_scene_index = isaac_scenario_builders.effective_scene_index
_scene_index_from_usd_path = isaac_scenario_builders.scene_index_from_usd_path
_scene_specific_scenario_if_needed = isaac_scenario_builders.scene_specific_scenario_if_needed
_scenario_from_scene_index = isaac_scenario_builders.scenario_from_scene_index
_cleanup_receptacle_index_for_mess_generation = (
    isaac_scenario_builders.cleanup_receptacle_index_for_mess_generation
)
_cleanup_receptacle_from_scene_index = isaac_scenario_builders.cleanup_receptacle_from_scene_index
_scene_object_name = isaac_scenario_builders.scene_object_name
_scene_object_category = isaac_scenario_builders.scene_object_category
_scene_cleanup_object_category = isaac_scenario_builders.scene_cleanup_object_category
_canonical_cleanup_category = isaac_scenario_builders.canonical_cleanup_category
_scene_target_receptacle_id = isaac_scenario_builders.scene_target_receptacle_id
_first_receptacle_matching_aliases = isaac_scenario_builders.first_receptacle_matching_aliases
_scene_source_receptacle_id = isaac_scenario_builders.scene_source_receptacle_id
_scene_entry_tokens = isaac_scenario_builders.scene_entry_tokens
_SCENE_CLEANUP_TARGET_ALIASES = isaac_scenario_builders.SCENE_CLEANUP_TARGET_ALIASES
_SCENE_STRICT_CLEANUP_TARGET_ALIASES = isaac_scenario_builders.SCENE_STRICT_CLEANUP_TARGET_ALIASES
_CANONICAL_CLEANUP_CATEGORY_ALIASES = isaac_scenario_builders.CANONICAL_CLEANUP_CATEGORY_ALIASES
_scenario_from_generated_mess_manifest_or_limit = (
    isaac_scenario_builders.scenario_from_generated_mess_manifest_or_limit
)
_limit_scenario_to_generated_mess_count = (
    isaac_scenario_builders.limit_scenario_to_generated_mess_count
)
_scenario_without_private_targets = isaac_scenario_builders.scenario_without_private_targets
_scenario_from_map_bundle = isaac_scenario_builders.scenario_from_map_bundle
_initial_receptacle_id = isaac_scenario_builders.initial_receptacle_id
_cleanup_receptacle_from_fixture = isaac_scenario_builders.cleanup_receptacle_from_fixture
_map_aligned_target_specs = isaac_scenario_builders.map_aligned_target_specs
_first_fixture_matching = isaac_scenario_builders.first_fixture_matching


def _robot_payload(robot_name: str) -> dict[str, Any]:
    return isaac_robot_import.robot_payload(robot_name, _rby1m_robot_import_plan(robot_name))


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


if __name__ == "__main__":
    raise SystemExit(main())
