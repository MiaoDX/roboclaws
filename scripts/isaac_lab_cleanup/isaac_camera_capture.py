from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from PIL import Image

from roboclaws.household.color_management import apply_camera_color_profile
from roboclaws.household.isaac_lab_backend import ISAACLAB_SUBPROCESS_BACKEND


@dataclass(frozen=True)
class IsaacCameraCaptureRequest:
    scene_usd: Path
    view_paths: dict[str, Path]
    width: int
    height: int
    simulation_app: Any
    robot_import: dict[str, Any]
    include_segmentation: bool
    segmentation_data_types: tuple[str, ...]
    semantic_filter: tuple[str, ...]
    scene_index_diagnostics: dict[str, Any] | None
    semantic_pose_state: dict[str, Any]
    color_profile_override: dict[str, Any] | None
    render_settle_frames: int
    isaac_aa_op: int | None
    isaac_tonemap_op: int | None
    isaac_exposure_bias: float | None
    isaac_colorcorr_gain: tuple[float, float, float] | None
    robot_view_keys: tuple[str, ...]
    head_camera_prim: str
    head_camera_vertical_fov_deg: float
    head_camera_focal_length_mm: float
    renderer_mode: str
    capture_method: str
    default_lighting_profile: dict[str, Any]


@dataclass(frozen=True)
class IsaacCameraCaptureHooks:
    wait_for_stage_load: Callable[..., None]
    load_current_stage_payloads: Callable[..., None]
    apply_semantic_pose_state_to_stage: Callable[..., dict[str, Any]]
    ensure_rby1m_robot_on_stage: Callable[..., dict[str, Any]]
    current_stage_bounds: Callable[..., dict[str, Any]]
    ensure_capture_lighting: Callable[..., dict[str, Any]]
    apply_scene_index_semantic_labels: Callable[..., dict[str, Any]]
    semantic_label_application_not_requested: Callable[..., dict[str, Any]]
    configure_rby1m_head_camera_lens: Callable[..., dict[str, Any]]
    horizontal_aperture_from_lens: Callable[..., float]
    isaac_camera_view_poses: Callable[..., dict[str, Any]]
    isaac_settings_interface: Callable[[], Any]
    apply_isaac_capture_quality_overrides: Callable[..., dict[str, Any]]
    isaac_native_render_diagnostics: Callable[..., dict[str, Any]]
    capture_quality_settings: Callable[..., dict[str, Any]]
    camera_render_product_paths: Callable[[Any], list[str]]
    position_robot_for_head_camera_view: Callable[..., dict[str, Any]]
    usd_camera_diagnostics: Callable[..., dict[str, Any]]
    isaac_eye_target_camera_diagnostics: Callable[..., dict[str, Any]]
    robot_relative_chase_eye_target: Callable[[dict[str, Any]], Any]
    rgb_tensor_to_uint8: Callable[..., Any]
    image_has_variance: Callable[..., bool]
    robot_view_color_profile: Callable[[dict[str, Any] | None], dict[str, Any]]
    camera_segmentation_view_diagnostics: Callable[..., dict[str, Any]]
    restore_isaac_capture_quality_overrides: Callable[..., dict[str, Any]]
    camera_segmentation_capture_diagnostics: Callable[..., dict[str, Any]]
    camera_segmentation_not_requested_diagnostics: Callable[[], dict[str, Any]]


@dataclass(frozen=True)
class _CaptureStage:
    pose_apply: dict[str, Any]
    robot_stage: dict[str, Any]
    scene_bounds: dict[str, Any]
    lighting_profile: dict[str, Any]
    lighting_diagnostics: dict[str, Any]
    semantic_label_application: dict[str, Any]
    camera_semantic_filter: str | list[str]
    mounted_head_camera: bool
    head_camera_lens: dict[str, Any]


@dataclass(frozen=True)
class _CaptureCameras:
    sim: Any
    head_camera: Any | None
    scene_camera: Any
    view_poses: dict[str, Any]


@dataclass(frozen=True)
class _RenderState:
    settings: Any
    settings_mutation: dict[str, Any]
    native_render_diagnostics: dict[str, Any]
    color_profile: dict[str, Any]
    render_settle_frames: int


@dataclass(frozen=True)
class _RenderedViews:
    saved: dict[str, str]
    segmentation_views: list[dict[str, Any]]
    total_render_steps: int
    robot_pose_application: dict[str, Any]
    camera_diagnostics: dict[str, dict[str, Any]]
    color_management: dict[str, dict[str, Any]]


@dataclass(frozen=True)
class _ViewCapture:
    saved_path: str
    render_steps: int
    robot_pose_application: dict[str, Any]
    camera_diagnostics: dict[str, Any]
    color_management: dict[str, Any] | None
    segmentation_view: dict[str, Any] | None


def capture_isaac_lab_camera_views(
    *,
    request: IsaacCameraCaptureRequest,
    hooks: IsaacCameraCaptureHooks,
) -> dict[str, Any]:
    import isaaclab.sim as sim_utils
    import isaacsim.core.experimental.utils.stage as stage_utils
    import numpy as np
    import torch
    from isaaclab.sensors.camera import Camera, CameraCfg

    stage = _prepare_capture_stage(
        request=request,
        hooks=hooks,
        sim_utils=sim_utils,
        stage_utils=stage_utils,
    )
    device = "cuda:0" if torch.cuda.is_available() else "cpu"
    sim = sim_utils.SimulationContext(sim_utils.SimulationCfg(device=device))
    cameras = _build_capture_cameras(
        request=request,
        hooks=hooks,
        sim_utils=sim_utils,
        torch=torch,
        camera_type=Camera,
        camera_cfg_type=CameraCfg,
        sim=sim,
        stage=stage,
    )
    cameras.sim.reset()
    render_state = _begin_render_state(
        request=request,
        hooks=hooks,
        cameras=cameras,
        stage=stage,
    )
    try:
        rendered = _render_robot_views(
            request=request,
            hooks=hooks,
            np=np,
            stage_utils=stage_utils,
            stage=stage,
            cameras=cameras,
            render_state=render_state,
        )
    finally:
        hooks.restore_isaac_capture_quality_overrides(
            settings=render_state.settings,
            mutation=render_state.settings_mutation,
        )
    return _capture_payload(
        request=request,
        hooks=hooks,
        stage=stage,
        render_state=render_state,
        rendered=rendered,
    )


def _prepare_capture_stage(
    *,
    request: IsaacCameraCaptureRequest,
    hooks: IsaacCameraCaptureHooks,
    sim_utils: Any,
    stage_utils: Any,
) -> _CaptureStage:
    opened, _ = stage_utils.open_stage(str(request.scene_usd))
    if not opened:
        raise RuntimeError(f"Isaac Sim failed to open generated USD stage: {request.scene_usd}")
    hooks.wait_for_stage_load(stage_utils, request.simulation_app)
    hooks.load_current_stage_payloads(stage_utils)
    pose_apply = hooks.apply_semantic_pose_state_to_stage(
        stage_utils=stage_utils,
        semantic_pose_state=request.semantic_pose_state,
    )
    robot_stage = hooks.ensure_rby1m_robot_on_stage(
        stage_utils=stage_utils,
        robot_import=request.robot_import,
    )
    _standardize_head_camera_xform(
        sim_utils=sim_utils,
        stage_utils=stage_utils,
        robot_stage=robot_stage,
        head_camera_prim=request.head_camera_prim,
    )
    scene_bounds = hooks.current_stage_bounds(stage_utils)
    lighting_profile = dict(request.default_lighting_profile)
    lighting_diagnostics = hooks.ensure_capture_lighting(
        stage_utils,
        profile=lighting_profile,
    )
    semantic_label_application = _apply_semantic_labels(
        request=request,
        hooks=hooks,
        sim_utils=sim_utils,
        stage_utils=stage_utils,
    )
    mounted_head_camera = robot_stage.get("head_camera_prim_exists") is True
    head_camera_lens = (
        hooks.configure_rby1m_head_camera_lens(
            stage_utils=stage_utils,
            width=request.width,
            height=request.height,
        )
        if mounted_head_camera
        else {"status": "not_requested"}
    )
    return _CaptureStage(
        pose_apply=pose_apply,
        robot_stage=robot_stage,
        scene_bounds=scene_bounds,
        lighting_profile=lighting_profile,
        lighting_diagnostics=lighting_diagnostics,
        semantic_label_application=semantic_label_application,
        camera_semantic_filter=_camera_semantic_filter(request),
        mounted_head_camera=mounted_head_camera,
        head_camera_lens=head_camera_lens,
    )


def _standardize_head_camera_xform(
    *,
    sim_utils: Any,
    stage_utils: Any,
    robot_stage: dict[str, Any],
    head_camera_prim: str,
) -> None:
    if robot_stage.get("head_camera_prim_exists") is not True:
        return
    if not hasattr(sim_utils, "standardize_xform_ops"):
        return
    current_stage = stage_utils.get_current_stage()
    if current_stage is not None:
        sim_utils.standardize_xform_ops(current_stage.GetPrimAtPath(head_camera_prim))


def _apply_semantic_labels(
    *,
    request: IsaacCameraCaptureRequest,
    hooks: IsaacCameraCaptureHooks,
    sim_utils: Any,
    stage_utils: Any,
) -> dict[str, Any]:
    if not request.include_segmentation:
        return hooks.semantic_label_application_not_requested()
    return hooks.apply_scene_index_semantic_labels(
        stage_utils=stage_utils,
        sim_utils=sim_utils,
        scene_index_diagnostics=request.scene_index_diagnostics,
    )


def _camera_semantic_filter(request: IsaacCameraCaptureRequest) -> str | list[str]:
    if request.include_segmentation:
        return list(request.semantic_filter)
    return "*:*"


def _build_capture_cameras(
    *,
    request: IsaacCameraCaptureRequest,
    hooks: IsaacCameraCaptureHooks,
    sim_utils: Any,
    torch: Any,
    camera_type: Any,
    camera_cfg_type: Any,
    sim: Any,
    stage: _CaptureStage,
) -> _CaptureCameras:
    data_types = ["rgb", *(request.segmentation_data_types if request.include_segmentation else ())]
    camera_spawn = _robot_view_camera_spawn(
        request=request,
        hooks=hooks,
        sim_utils=sim_utils,
    )
    head_camera = _build_head_camera(
        request=request,
        camera_type=camera_type,
        camera_cfg_type=camera_cfg_type,
        data_types=data_types,
        camera_semantic_filter=stage.camera_semantic_filter,
        mounted_head_camera=stage.mounted_head_camera,
    )
    sim_utils.create_prim("/World/RoboclawsSmokeCameraRig", "Xform")
    scene_camera = camera_type(
        cfg=camera_cfg_type(
            prim_path="/World/RoboclawsSmokeCameraRig/Camera",
            update_period=0.0,
            height=request.height,
            width=request.width,
            data_types=data_types,
            semantic_filter=stage.camera_semantic_filter,
            colorize_semantic_segmentation=False,
            colorize_instance_segmentation=False,
            colorize_instance_id_segmentation=False,
            spawn=camera_spawn,
        )
    )
    view_poses = hooks.isaac_camera_view_poses(
        torch=torch,
        device=sim.device,
        scene_bounds=stage.scene_bounds,
        semantic_pose_state=request.semantic_pose_state,
    )
    return _CaptureCameras(
        sim=sim,
        head_camera=head_camera,
        scene_camera=scene_camera,
        view_poses=view_poses,
    )


def _robot_view_camera_spawn(
    *,
    request: IsaacCameraCaptureRequest,
    hooks: IsaacCameraCaptureHooks,
    sim_utils: Any,
) -> Any:
    horizontal_aperture = hooks.horizontal_aperture_from_lens(
        {"vertical_fov_deg": request.head_camera_vertical_fov_deg},
        width=request.width,
        height=request.height,
        focal_length=request.head_camera_focal_length_mm,
    )
    return sim_utils.PinholeCameraCfg(
        focal_length=request.head_camera_focal_length_mm,
        focus_distance=4.0,
        horizontal_aperture=horizontal_aperture,
    )


def _build_head_camera(
    *,
    request: IsaacCameraCaptureRequest,
    camera_type: Any,
    camera_cfg_type: Any,
    data_types: list[str],
    camera_semantic_filter: str | list[str],
    mounted_head_camera: bool,
) -> Any | None:
    if not mounted_head_camera:
        return None
    return camera_type(
        cfg=camera_cfg_type(
            prim_path=request.head_camera_prim,
            update_period=0.0,
            height=request.height,
            width=request.width,
            data_types=data_types,
            semantic_filter=camera_semantic_filter,
            colorize_semantic_segmentation=False,
            colorize_instance_segmentation=False,
            colorize_instance_id_segmentation=False,
            spawn=None,
        )
    )


def _begin_render_state(
    *,
    request: IsaacCameraCaptureRequest,
    hooks: IsaacCameraCaptureHooks,
    cameras: _CaptureCameras,
    stage: _CaptureStage,
) -> _RenderState:
    settings = hooks.isaac_settings_interface()
    render_settle_frames = max(0, int(request.render_settle_frames))
    settings_mutation = hooks.apply_isaac_capture_quality_overrides(
        settings=settings,
        isaac_aa_op=request.isaac_aa_op,
        isaac_tonemap_op=request.isaac_tonemap_op,
        isaac_exposure_bias=request.isaac_exposure_bias,
        isaac_colorcorr_gain=request.isaac_colorcorr_gain,
    )
    native_render_diagnostics = hooks.isaac_native_render_diagnostics(
        renderer_mode=request.renderer_mode,
        capture_method=request.capture_method,
        view_kind="robot_views",
        render_resolution={"width": request.width, "height": request.height},
        camera_prim_paths=[
            request.head_camera_prim if stage.mounted_head_camera else "",
            "/World/RoboclawsSmokeCameraRig/Camera",
        ],
        render_product_paths=[
            *(
                hooks.camera_render_product_paths(cameras.head_camera)
                if cameras.head_camera
                else []
            ),
            *hooks.camera_render_product_paths(cameras.scene_camera),
        ],
        isaac_lab_isp_active=False,
        capture_quality_settings=hooks.capture_quality_settings(
            render_settle_frames=render_settle_frames,
            settings=settings,
            settings_mutation=settings_mutation,
        ),
    )
    return _RenderState(
        settings=settings,
        settings_mutation=settings_mutation,
        native_render_diagnostics=native_render_diagnostics,
        color_profile=hooks.robot_view_color_profile(request.color_profile_override),
        render_settle_frames=render_settle_frames,
    )


def _render_robot_views(
    *,
    request: IsaacCameraCaptureRequest,
    hooks: IsaacCameraCaptureHooks,
    np: Any,
    stage_utils: Any,
    stage: _CaptureStage,
    cameras: _CaptureCameras,
    render_state: _RenderState,
) -> _RenderedViews:
    saved: dict[str, str] = {}
    segmentation_views: list[dict[str, Any]] = []
    total_render_steps = 0
    robot_pose_application: dict[str, Any] = {}
    camera_diagnostics: dict[str, dict[str, Any]] = {}
    color_management: dict[str, dict[str, Any]] = {}
    for view_name in request.robot_view_keys:
        capture = _capture_robot_view(
            view_name=view_name,
            request=request,
            hooks=hooks,
            np=np,
            stage_utils=stage_utils,
            stage=stage,
            cameras=cameras,
            render_state=render_state,
        )
        saved[view_name] = capture.saved_path
        total_render_steps += capture.render_steps
        camera_diagnostics[view_name] = capture.camera_diagnostics
        if capture.robot_pose_application:
            robot_pose_application = capture.robot_pose_application
        if capture.color_management is not None:
            color_management[view_name] = capture.color_management
        if capture.segmentation_view is not None:
            segmentation_views.append(capture.segmentation_view)
    return _RenderedViews(
        saved=saved,
        segmentation_views=segmentation_views,
        total_render_steps=total_render_steps,
        robot_pose_application=robot_pose_application,
        camera_diagnostics=camera_diagnostics,
        color_management=color_management,
    )


def _capture_robot_view(
    *,
    view_name: str,
    request: IsaacCameraCaptureRequest,
    hooks: IsaacCameraCaptureHooks,
    np: Any,
    stage_utils: Any,
    stage: _CaptureStage,
    cameras: _CaptureCameras,
    render_state: _RenderState,
) -> _ViewCapture:
    camera, robot_pose_application, camera_diagnostics = _select_camera_for_view(
        view_name=view_name,
        request=request,
        hooks=hooks,
        stage_utils=stage_utils,
        stage=stage,
        cameras=cameras,
    )
    rgb_image, render_steps = _render_rgb_image(
        view_name=view_name,
        hooks=hooks,
        np=np,
        sim=cameras.sim,
        camera=camera,
        render_settle_frames=render_state.render_settle_frames,
    )
    rgb_image, color_management = _apply_view_color_profile(
        view_name=view_name,
        request=request,
        np=np,
        render_state=render_state,
        rgb_image=rgb_image,
    )
    output_path = request.view_paths[view_name]
    output_path.parent.mkdir(parents=True, exist_ok=True)
    Image.fromarray(rgb_image, mode="RGB").save(output_path)
    segmentation_view = _segmentation_view(
        view_name=view_name,
        request=request,
        hooks=hooks,
        np=np,
        camera=camera,
    )
    return _ViewCapture(
        saved_path=str(output_path),
        render_steps=render_steps,
        robot_pose_application=robot_pose_application,
        camera_diagnostics=camera_diagnostics,
        color_management=color_management,
        segmentation_view=segmentation_view,
    )


def _select_camera_for_view(
    *,
    view_name: str,
    request: IsaacCameraCaptureRequest,
    hooks: IsaacCameraCaptureHooks,
    stage_utils: Any,
    stage: _CaptureStage,
    cameras: _CaptureCameras,
) -> tuple[Any, dict[str, Any], dict[str, Any]]:
    if view_name == "fpv" and stage.mounted_head_camera:
        if cameras.head_camera is None:
            raise RuntimeError("mounted head camera was requested but Camera sensor is absent")
        robot_pose_application = hooks.position_robot_for_head_camera_view(
            stage_utils=stage_utils,
            scene_bounds=stage.scene_bounds,
            semantic_pose_state=request.semantic_pose_state,
        )
        diagnostics = hooks.usd_camera_diagnostics(
            stage_utils=stage_utils,
            prim_path=request.head_camera_prim,
            view_name=view_name,
            width=request.width,
            height=request.height,
            robot_pose_application=robot_pose_application,
            lens_application=stage.head_camera_lens,
        )
        return cameras.head_camera, robot_pose_application, diagnostics
    positions, targets = cameras.view_poses[view_name]
    cameras.scene_camera.set_world_poses_from_view(positions, targets)
    diagnostics = hooks.isaac_eye_target_camera_diagnostics(
        view_name=view_name,
        positions=positions,
        targets=targets,
        width=request.width,
        height=request.height,
        camera_basis=_camera_basis(view_name, request, hooks),
    )
    return cameras.scene_camera, {}, diagnostics


def _camera_basis(
    view_name: str,
    request: IsaacCameraCaptureRequest,
    hooks: IsaacCameraCaptureHooks,
) -> str:
    robot_pose = _dict(request.semantic_pose_state.get("robot_pose"))
    if view_name == "chase" and hooks.robot_relative_chase_eye_target(robot_pose) is not None:
        return "robot_relative_camera_follower"
    return "scene_bounds_eye_target"


def _render_rgb_image(
    *,
    view_name: str,
    hooks: IsaacCameraCaptureHooks,
    np: Any,
    sim: Any,
    camera: Any,
    render_settle_frames: int,
) -> tuple[Any, int]:
    rgb_image = None
    render_steps = 0
    for _ in range(24):
        sim.step()
        render_steps += 1
        camera.update(dt=sim.get_physics_dt())
        rgb_image = hooks.rgb_tensor_to_uint8(camera.data.output.get("rgb"), np=np)
        if rgb_image is not None and hooks.image_has_variance(rgb_image, np=np):
            break
    for _ in range(render_settle_frames):
        sim.step()
        render_steps += 1
        camera.update(dt=sim.get_physics_dt())
        settled_rgb_image = hooks.rgb_tensor_to_uint8(camera.data.output.get("rgb"), np=np)
        if settled_rgb_image is not None:
            rgb_image = settled_rgb_image
    if rgb_image is None:
        raise RuntimeError(f"Isaac Lab camera did not produce an RGB tensor for {view_name}")
    if not hooks.image_has_variance(rgb_image, np=np):
        raise RuntimeError(f"Isaac Lab camera RGB tensor was blank for {view_name}")
    return rgb_image, render_steps


def _apply_view_color_profile(
    *,
    view_name: str,
    request: IsaacCameraCaptureRequest,
    np: Any,
    render_state: _RenderState,
    rgb_image: Any,
) -> tuple[Any, dict[str, Any] | None]:
    if view_name == "topdown":
        return rgb_image, None
    return apply_camera_color_profile(
        rgb_image,
        np=np,
        profile=render_state.color_profile,
        backend=ISAACLAB_SUBPROCESS_BACKEND,
        view_id=view_name,
    )


def _segmentation_view(
    *,
    view_name: str,
    request: IsaacCameraCaptureRequest,
    hooks: IsaacCameraCaptureHooks,
    np: Any,
    camera: Any,
) -> dict[str, Any] | None:
    if not request.include_segmentation:
        return None
    return hooks.camera_segmentation_view_diagnostics(
        camera,
        data_types=request.segmentation_data_types,
        view_name=view_name,
        np=np,
    )


def _capture_payload(
    *,
    request: IsaacCameraCaptureRequest,
    hooks: IsaacCameraCaptureHooks,
    stage: _CaptureStage,
    render_state: _RenderState,
    rendered: _RenderedViews,
) -> dict[str, Any]:
    return {
        "render_steps": rendered.total_render_steps,
        "robot_view_images": rendered.saved,
        "scene_bounds": stage.scene_bounds,
        "robot_stage": stage.robot_stage,
        "robot_view_uses_mounted_head_camera": stage.mounted_head_camera,
        "robot_pose_stage_application": rendered.robot_pose_application,
        "camera_diagnostics": _camera_diagnostics_payload(
            request=request,
            stage=stage,
            render_state=render_state,
            rendered=rendered,
        ),
        "native_render_diagnostics": render_state.native_render_diagnostics,
        "lighting_profile": stage.lighting_profile,
        "lighting_diagnostics": stage.lighting_diagnostics,
        "color_profile": render_state.color_profile,
        "color_management": rendered.color_management,
        "semantic_pose_stage_application": stage.pose_apply,
        "segmentation": _segmentation_payload(
            request=request,
            hooks=hooks,
            stage=stage,
            rendered=rendered,
        ),
    }


def _camera_diagnostics_payload(
    *,
    request: IsaacCameraCaptureRequest,
    stage: _CaptureStage,
    render_state: _RenderState,
    rendered: _RenderedViews,
) -> dict[str, Any]:
    return {
        "schema": "isaac_robot_view_camera_diagnostics_v1",
        "backend": ISAACLAB_SUBPROCESS_BACKEND,
        "render_resolution": {"width": request.width, "height": request.height},
        "render_settle_frames": render_state.render_settle_frames,
        "lighting_profile": stage.lighting_profile,
        "lighting_diagnostics": stage.lighting_diagnostics,
        "native_render_diagnostics": render_state.native_render_diagnostics,
        "views": rendered.camera_diagnostics,
    }


def _segmentation_payload(
    *,
    request: IsaacCameraCaptureRequest,
    hooks: IsaacCameraCaptureHooks,
    stage: _CaptureStage,
    rendered: _RenderedViews,
) -> dict[str, Any]:
    if not request.include_segmentation:
        return hooks.camera_segmentation_not_requested_diagnostics()
    return hooks.camera_segmentation_capture_diagnostics(
        rendered.segmentation_views,
        requested_data_types=request.segmentation_data_types,
        semantic_label_application=stage.semantic_label_application,
        semantic_filter=stage.camera_semantic_filter,
    )


def _dict(value: Any) -> dict[str, Any]:
    return dict(value) if isinstance(value, dict) else {}
