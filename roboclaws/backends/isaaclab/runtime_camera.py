"""Isaac Lab worker camera owner."""

from __future__ import annotations

import argparse
from pathlib import Path
from typing import Any

from roboclaws.backends.isaaclab import (
    isaac_camera_capture,
    isaac_camera_geometry,
    isaac_capture_quality,
    isaac_render_diagnostics,
    isaac_robot_camera_stage,
    isaac_scene_camera_capture,
    isaac_scene_camera_geometry,
    isaac_segmentation_diagnostics,
    isaac_semantic_labels,
    isaac_semantic_pose_stage,
    isaac_stage_lighting,
    isaac_usd_xform,
    isaac_worker_context,
)
from roboclaws.backends.isaaclab.isaac_segmentation_diagnostics import (
    ISAAC_SEGMENTATION_DATA_TYPES,
    MAX_SEGMENTATION_CANDIDATES,
)
from roboclaws.backends.isaaclab.runtime_lifecycle import DEFERRED_SIMULATION_APP
from roboclaws.backends.isaaclab.runtime_settings import (
    DEFAULT_HEIGHT,
    DEFAULT_WIDTH,
    REAL_ROBOT_VIEW_CAPTURE_METHOD,
    REAL_SMOKE_RENDERER_MODE,
    ROBOT_VIEW_KEYS,
)
from roboclaws.household.camera_control import (
    DEFAULT_SCENE_PROBE_LIGHTING_PROFILE,
    normalize_camera_control_request,
)

_camera_render_product_paths = isaac_render_diagnostics.camera_render_product_paths
_capture_quality_settings = isaac_render_diagnostics.capture_quality_settings
_current_stage_bounds = isaac_stage_lighting.current_stage_bounds
_dict = isaac_worker_context.dict_value
_ensure_capture_lighting = isaac_stage_lighting.ensure_capture_lighting
_has_xy = isaac_worker_context.has_xy
_image_has_variance = isaac_scene_camera_geometry.image_has_variance
_isaac_camera_view_poses = isaac_camera_geometry.isaac_camera_view_poses
_matrix4d_rowmajor = isaac_camera_geometry.matrix4d_rowmajor
_optional_float = isaac_camera_geometry.optional_float
_restore_isaac_capture_quality_overrides = (
    isaac_capture_quality.restore_isaac_capture_quality_overrides
)
_robot_pose_yaw_deg = isaac_camera_geometry.robot_pose_yaw_deg
_robot_relative_chase_eye_target = isaac_camera_geometry.robot_relative_chase_eye_target
_robot_view_color_profile = isaac_camera_geometry.robot_view_color_profile
_semantic_label_application_not_requested = (
    isaac_semantic_labels.semantic_label_application_not_requested
)
_semantic_label_target_prims = isaac_semantic_labels.semantic_label_target_prims
_set_usd_xform_translate = isaac_usd_xform.set_usd_xform_translate
_static_head_camera_pose_for_pitch = isaac_camera_geometry.static_head_camera_pose_for_pitch
_tensor_first_vec3 = isaac_camera_geometry.tensor_first_vec3
_usd_attr_float = isaac_camera_geometry.usd_attr_float
_usd_camera_fov_metadata = isaac_camera_geometry.usd_camera_fov_metadata
_usd_vec = isaac_camera_geometry.usd_vec
_vec3 = isaac_worker_context.vec3


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

    from roboclaws.backends.isaaclab.runtime_evidence import (
        _apply_isaac_capture_quality_overrides,
        _isaac_native_render_diagnostics,
        _isaac_settings_interface,
    )

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

    from roboclaws.backends.isaaclab.runtime_evidence import (
        _isaac_native_render_diagnostics,
    )

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
    DEFERRED_SIMULATION_APP[0] = simulation_app
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

    from roboclaws.backends.isaaclab.runtime_evidence import (
        _isaac_native_render_diagnostics,
    )

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

    from roboclaws.backends.isaaclab.runtime_state import (
        _semantic_pose_target_position,
    )

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
