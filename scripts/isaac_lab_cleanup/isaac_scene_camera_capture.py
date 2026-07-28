from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from PIL import Image

from roboclaws.household.camera_control import CAMERA_CONTROL_API_NAME
from roboclaws.household.color_management import apply_camera_color_profile


@dataclass(frozen=True)
class IsaacSceneCameraCaptureRequest:
    scene_usd: Path
    camera_request: dict[str, Any] | list[dict[str, Any]]
    output_dir: Path
    width: int
    height: int
    simulation_app: Any
    semantic_pose_state: dict[str, Any]
    renderer_mode: str


@dataclass(frozen=True)
class IsaacSceneCameraCaptureHooks:
    normalize_camera_control_request: Callable[..., dict[str, Any]]
    wait_for_stage_load: Callable[..., None]
    load_current_stage_payloads: Callable[..., None]
    apply_semantic_pose_state_to_stage: Callable[..., dict[str, Any]]
    current_stage_bounds: Callable[[Any], dict[str, Any]]
    ensure_capture_lighting: Callable[..., dict[str, Any]]
    horizontal_aperture_from_lens: Callable[..., float]
    isaac_native_render_diagnostics: Callable[..., dict[str, Any]]
    camera_render_product_paths: Callable[[Any], list[str]]
    isaac_scene_camera_view_spec: Callable[..., dict[str, Any]]
    rgb_tensor_to_uint8: Callable[..., Any]
    image_has_variance: Callable[..., bool]


@dataclass(frozen=True)
class _SceneCameraSetup:
    normalized_request: dict[str, Any]
    width: int
    height: int
    scene_bounds: dict[str, Any]
    pose_apply: dict[str, Any]
    lighting_diagnostics: dict[str, Any]
    focal_length: float
    horizontal_aperture: float
    color_profile: dict[str, Any]


@dataclass(frozen=True)
class _SceneCameraRenderContext:
    sim: Any
    camera: Any
    torch: Any
    np: Any
    native_render_diagnostics: dict[str, Any]


@dataclass(frozen=True)
class _SceneViewCapture:
    spec: dict[str, Any]
    image_path: str
    shape: list[int]
    color_diagnostic: dict[str, Any]
    render_steps: int


def capture_isaac_lab_scene_camera_views(
    *,
    request: IsaacSceneCameraCaptureRequest,
    hooks: IsaacSceneCameraCaptureHooks,
) -> dict[str, Any]:
    import isaaclab.sim as sim_utils
    import isaacsim.core.experimental.utils.stage as stage_utils
    import numpy as np
    import torch
    from isaaclab.sensors.camera import Camera, CameraCfg

    setup = _prepare_scene_camera_capture(
        request=request,
        hooks=hooks,
        stage_utils=stage_utils,
    )
    context = _build_scene_camera_context(
        request=request,
        hooks=hooks,
        setup=setup,
        sim_utils=sim_utils,
        torch=torch,
        np=np,
        camera_type=Camera,
        camera_cfg_type=CameraCfg,
    )
    captures = _capture_scene_views(
        request=request,
        hooks=hooks,
        setup=setup,
        context=context,
        stage_utils=stage_utils,
    )
    return _scene_camera_payload(
        request=request,
        setup=setup,
        context=context,
        captures=captures,
    )


def capture_scene_camera_request_with_existing_sim(
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
    normalize_camera_control_request: Callable[..., dict[str, Any]],
    ensure_capture_lighting: Callable[..., dict[str, Any]],
    horizontal_aperture_from_lens: Callable[..., float],
    isaac_native_render_diagnostics: Callable[..., dict[str, Any]],
    camera_render_product_paths: Callable[[Any], list[str]],
    isaac_scene_camera_view_spec: Callable[..., dict[str, Any]],
    rgb_tensor_to_uint8: Callable[..., Any],
    image_has_variance: Callable[..., bool],
    renderer_mode: str,
) -> dict[str, Any]:
    camera_request = normalize_camera_control_request(camera_request, width=width, height=height)
    resolution = camera_request["render_resolution"]
    width = int(resolution["width"])
    height = int(resolution["height"])
    lighting_diagnostics = ensure_capture_lighting(
        stage_utils,
        profile=camera_request.get("lighting_profile"),
    )
    lens = _lens(camera_request)
    color_profile = dict(camera_request.get("color_profile") or {})
    focal_length = float(lens.get("focal_length_mm", 24.0))
    horizontal_aperture = horizontal_aperture_from_lens(
        lens,
        width=width,
        height=height,
        focal_length=focal_length,
    )
    sim_utils.create_prim("/World/RoboclawsSceneRequestCameraRig", "Xform")
    camera = camera_type(
        cfg=camera_cfg_type(
            prim_path="/World/RoboclawsSceneRequestCameraRig/Camera",
            update_period=0.0,
            height=height,
            width=width,
            data_types=["rgb"],
            spawn=sim_utils.PinholeCameraCfg(
                focal_length=focal_length,
                focus_distance=4.0,
                horizontal_aperture=horizontal_aperture,
            ),
        )
    )
    sim.reset()
    native_render_diagnostics = isaac_native_render_diagnostics(
        renderer_mode=renderer_mode,
        capture_method="isaac_lab_camera_rgb_scene_probe",
        view_kind="scene_camera_request",
        render_resolution={"width": width, "height": height},
        camera_prim_paths=["/World/RoboclawsSceneRequestCameraRig/Camera"],
        render_product_paths=camera_render_product_paths(camera),
        isaac_lab_isp_active=False,
    )
    output_dir.mkdir(parents=True, exist_ok=True)
    saved: dict[str, str] = {}
    shapes: dict[str, list[int]] = {}
    color_diagnostics: dict[str, dict[str, Any]] = {}
    views: list[dict[str, Any]] = []
    total_render_steps = 0
    for index, raw_spec in enumerate(camera_request.get("views") or [], start=1):
        spec = isaac_scene_camera_view_spec(raw_spec, index=index, stage_utils=stage_utils)
        position = torch.tensor([spec["eye"]], dtype=torch.float32, device=sim.device)
        target = torch.tensor([spec["target"]], dtype=torch.float32, device=sim.device)
        camera.set_world_poses_from_view(position, target)
        rgb_image, render_steps = _render_existing_sim_scene_rgb_image(
            view_id=str(spec["view_id"]),
            sim=sim,
            camera=camera,
            np=np,
            rgb_tensor_to_uint8=rgb_tensor_to_uint8,
            image_has_variance=image_has_variance,
        )
        total_render_steps += render_steps
        rgb_image, color_diagnostic = apply_camera_color_profile(
            rgb_image,
            np=np,
            profile=color_profile,
            backend="isaaclab-prepared-usd",
            view_id=str(spec["view_id"]),
        )
        output_path = output_dir / f"{spec['view_id']}.png"
        Image.fromarray(rgb_image, mode="RGB").save(output_path)
        saved[str(spec["view_id"])] = str(output_path)
        shapes[str(spec["view_id"])] = list(rgb_image.shape)
        color_diagnostics[str(spec["view_id"])] = color_diagnostic
        views.append(
            {
                **spec,
                "image_path": str(output_path),
                "shape": list(rgb_image.shape),
            }
        )
    return {
        "schema": "isaac_scene_camera_views_v1",
        "camera_control_api": camera_request.get("api_name") or CAMERA_CONTROL_API_NAME,
        "camera_request_schema": camera_request.get("schema"),
        "calibration_status": camera_request.get("calibration_status"),
        "lighting_profile": camera_request.get("lighting_profile") or {},
        "color_profile": color_profile,
        "color_management": color_diagnostics,
        "lighting_diagnostics": lighting_diagnostics,
        "native_render_diagnostics": native_render_diagnostics,
        "lens": camera_request.get("lens") or {},
        "derived_lens": {
            "focal_length_mm": focal_length,
            "horizontal_aperture_mm": horizontal_aperture,
        },
        "render_steps": total_render_steps,
        "scene_bounds": scene_bounds,
        "views": views,
        "images": saved,
        "shapes": shapes,
    }


def _prepare_scene_camera_capture(
    *,
    request: IsaacSceneCameraCaptureRequest,
    hooks: IsaacSceneCameraCaptureHooks,
    stage_utils: Any,
) -> _SceneCameraSetup:
    opened, _ = stage_utils.open_stage(str(request.scene_usd))
    if not opened:
        raise RuntimeError(f"Isaac Sim failed to open generated USD stage: {request.scene_usd}")
    hooks.wait_for_stage_load(stage_utils, request.simulation_app)
    hooks.load_current_stage_payloads(stage_utils)
    pose_apply = hooks.apply_semantic_pose_state_to_stage(
        stage_utils=stage_utils,
        semantic_pose_state=request.semantic_pose_state,
    )
    scene_bounds = hooks.current_stage_bounds(stage_utils)
    normalized = hooks.normalize_camera_control_request(
        request.camera_request,
        width=request.width,
        height=request.height,
    )
    width, height = _render_resolution(normalized)
    lighting_diagnostics = hooks.ensure_capture_lighting(
        stage_utils,
        profile=normalized.get("lighting_profile"),
    )
    lens = _lens(normalized)
    focal_length = float(lens.get("focal_length_mm", 24.0))
    return _SceneCameraSetup(
        normalized_request=normalized,
        width=width,
        height=height,
        scene_bounds=scene_bounds,
        pose_apply=pose_apply,
        lighting_diagnostics=lighting_diagnostics,
        focal_length=focal_length,
        horizontal_aperture=hooks.horizontal_aperture_from_lens(
            lens,
            width=width,
            height=height,
            focal_length=focal_length,
        ),
        color_profile=dict(normalized.get("color_profile") or {}),
    )


def _render_resolution(camera_request: dict[str, Any]) -> tuple[int, int]:
    resolution = camera_request["render_resolution"]
    return int(resolution["width"]), int(resolution["height"])


def _lens(camera_request: dict[str, Any]) -> dict[str, Any]:
    lens = camera_request.get("lens")
    return dict(lens) if isinstance(lens, dict) else {}


def _build_scene_camera_context(
    *,
    request: IsaacSceneCameraCaptureRequest,
    hooks: IsaacSceneCameraCaptureHooks,
    setup: _SceneCameraSetup,
    sim_utils: Any,
    torch: Any,
    np: Any,
    camera_type: Any,
    camera_cfg_type: Any,
) -> _SceneCameraRenderContext:
    device = "cuda:0" if torch.cuda.is_available() else "cpu"
    sim = sim_utils.SimulationContext(sim_utils.SimulationCfg(device=device))
    sim_utils.create_prim("/World/RoboclawsSceneProbeCameraRig", "Xform")
    camera = camera_type(
        cfg=camera_cfg_type(
            prim_path="/World/RoboclawsSceneProbeCameraRig/Camera",
            update_period=0.0,
            height=setup.height,
            width=setup.width,
            data_types=["rgb"],
            spawn=sim_utils.PinholeCameraCfg(
                focal_length=setup.focal_length,
                focus_distance=4.0,
                horizontal_aperture=setup.horizontal_aperture,
            ),
        )
    )
    sim.reset()
    return _SceneCameraRenderContext(
        sim=sim,
        camera=camera,
        torch=torch,
        np=np,
        native_render_diagnostics=hooks.isaac_native_render_diagnostics(
            renderer_mode=request.renderer_mode,
            capture_method="isaac_lab_camera_rgb_scene_probe",
            view_kind="scene_camera_views",
            render_resolution={"width": setup.width, "height": setup.height},
            camera_prim_paths=["/World/RoboclawsSceneProbeCameraRig/Camera"],
            render_product_paths=hooks.camera_render_product_paths(camera),
            isaac_lab_isp_active=False,
        ),
    )


def _capture_scene_views(
    *,
    request: IsaacSceneCameraCaptureRequest,
    hooks: IsaacSceneCameraCaptureHooks,
    setup: _SceneCameraSetup,
    context: _SceneCameraRenderContext,
    stage_utils: Any,
) -> list[_SceneViewCapture]:
    request.output_dir.mkdir(parents=True, exist_ok=True)
    captures = []
    for index, raw_spec in enumerate(setup.normalized_request.get("views") or [], start=1):
        captures.append(
            _capture_scene_view(
                raw_spec=raw_spec,
                index=index,
                request=request,
                hooks=hooks,
                setup=setup,
                context=context,
                stage_utils=stage_utils,
            )
        )
    return captures


def _capture_scene_view(
    *,
    raw_spec: dict[str, Any],
    index: int,
    request: IsaacSceneCameraCaptureRequest,
    hooks: IsaacSceneCameraCaptureHooks,
    setup: _SceneCameraSetup,
    context: _SceneCameraRenderContext,
    stage_utils: Any,
) -> _SceneViewCapture:
    spec = hooks.isaac_scene_camera_view_spec(raw_spec, index=index, stage_utils=stage_utils)
    position = context.torch.tensor(
        [spec["eye"]],
        dtype=context.torch.float32,
        device=context.sim.device,
    )
    target = context.torch.tensor(
        [spec["target"]],
        dtype=context.torch.float32,
        device=context.sim.device,
    )
    context.camera.set_world_poses_from_view(position, target)
    rgb_image, render_steps = _render_scene_rgb_image(
        view_id=str(spec["view_id"]),
        hooks=hooks,
        context=context,
    )
    rgb_image, color_diagnostic = apply_camera_color_profile(
        rgb_image,
        np=context.np,
        profile=setup.color_profile,
        backend="isaaclab-prepared-usd",
        view_id=str(spec["view_id"]),
    )
    output_path = request.output_dir / f"{spec['view_id']}.png"
    Image.fromarray(rgb_image, mode="RGB").save(output_path)
    return _SceneViewCapture(
        spec=spec,
        image_path=str(output_path),
        shape=list(rgb_image.shape),
        color_diagnostic=color_diagnostic,
        render_steps=render_steps,
    )


def _render_scene_rgb_image(
    *,
    view_id: str,
    hooks: IsaacSceneCameraCaptureHooks,
    context: _SceneCameraRenderContext,
) -> tuple[Any, int]:
    rgb_image = None
    render_steps = 0
    for _ in range(24):
        context.sim.step()
        render_steps += 1
        context.camera.update(dt=context.sim.get_physics_dt())
        rgb_image = hooks.rgb_tensor_to_uint8(context.camera.data.output.get("rgb"), np=context.np)
        if rgb_image is not None and hooks.image_has_variance(rgb_image, np=context.np):
            break
    if rgb_image is None:
        raise RuntimeError(f"Isaac Lab camera did not produce an RGB tensor for {view_id}")
    if not hooks.image_has_variance(rgb_image, np=context.np):
        raise RuntimeError(f"Isaac Lab camera RGB tensor was blank for {view_id}")
    return rgb_image, render_steps


def _render_existing_sim_scene_rgb_image(
    *,
    view_id: str,
    sim: Any,
    camera: Any,
    np: Any,
    rgb_tensor_to_uint8: Callable[..., Any],
    image_has_variance: Callable[..., bool],
) -> tuple[Any, int]:
    rgb_image = None
    render_steps = 0
    for _ in range(24):
        sim.step()
        render_steps += 1
        camera.update(dt=sim.get_physics_dt())
        rgb_image = rgb_tensor_to_uint8(camera.data.output.get("rgb"), np=np)
        if rgb_image is not None and image_has_variance(rgb_image, np=np):
            break
    if rgb_image is None:
        raise RuntimeError(f"Isaac Lab camera did not produce an RGB tensor for {view_id}")
    if not image_has_variance(rgb_image, np=np):
        raise RuntimeError(f"Isaac Lab camera RGB tensor was blank for {view_id}")
    return rgb_image, render_steps


def _scene_camera_payload(
    *,
    request: IsaacSceneCameraCaptureRequest,
    setup: _SceneCameraSetup,
    context: _SceneCameraRenderContext,
    captures: list[_SceneViewCapture],
) -> dict[str, Any]:
    return {
        "schema": "isaac_scene_camera_views_v1",
        "camera_control_api": setup.normalized_request.get("api_name") or CAMERA_CONTROL_API_NAME,
        "camera_request_schema": setup.normalized_request.get("schema"),
        "calibration_status": setup.normalized_request.get("calibration_status"),
        "lighting_profile": setup.normalized_request.get("lighting_profile") or {},
        "color_profile": setup.color_profile,
        "color_management": {
            str(capture.spec["view_id"]): capture.color_diagnostic for capture in captures
        },
        "lighting_diagnostics": setup.lighting_diagnostics,
        "native_render_diagnostics": context.native_render_diagnostics,
        "lens": setup.normalized_request.get("lens") or {},
        "derived_lens": {
            "focal_length_mm": setup.focal_length,
            "horizontal_aperture_mm": setup.horizontal_aperture,
        },
        "render_steps": sum(capture.render_steps for capture in captures),
        "scene_bounds": setup.scene_bounds,
        "semantic_pose_stage_application": setup.pose_apply,
        "views": [
            {
                **capture.spec,
                "image_path": capture.image_path,
                "shape": capture.shape,
            }
            for capture in captures
        ],
        "images": {str(capture.spec["view_id"]): capture.image_path for capture in captures},
        "shapes": {str(capture.spec["view_id"]): capture.shape for capture in captures},
    }
