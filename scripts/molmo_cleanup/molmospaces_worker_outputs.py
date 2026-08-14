from __future__ import annotations

import math
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

import mujoco
from PIL import Image

from roboclaws.household.artifact_paths import resolve_home_relative_path
from roboclaws.household.camera_control import (
    CAMERA_CONTROL_API_NAME,
    CANONICAL_CAMERA_MODEL,
    canonical_scene_camera_control_request,
    normalize_camera_control_request,
)
from roboclaws.household.color_management import apply_camera_color_profile
from roboclaws.household.robot_view_camera_control import (
    robot_mounted_head_camera_control_contract,
    robot_view_display_color_profile,
)


@dataclass(frozen=True)
class MolmoWorkerOutputHooks:
    apply_qpos: Callable[..., Any]
    apply_robot_view_camera_offset: Callable[..., dict[str, Any]]
    annotate_focus_image: Callable[..., Any]
    annotate_focus_visual_grounding: Callable[..., dict[str, Any]]
    camera_from_view_spec: Callable[..., Any]
    camera_request_provenance: Callable[..., str]
    camera_request_variant: Callable[..., str]
    camera_view_spec: Callable[..., dict[str, Any]]
    count: Callable[..., Any]
    error: Callable[..., dict[str, Any]]
    fixed_camera_diagnostics: Callable[..., dict[str, Any]]
    focus_camera: Callable[..., Any]
    focus_payload: Callable[..., dict[str, Any]]
    focus_visibility: Callable[..., dict[str, Any]]
    free_camera_diagnostics: Callable[..., dict[str, Any]]
    load_model_data_for_state: Callable[..., tuple[Any, Any]]
    ok: Callable[..., dict[str, Any]]
    refresh_object_positions: Callable[..., Any]
    render_camera_views_with_model_data: Callable[..., dict[str, Any]]
    render_dimensions: Callable[..., tuple[int, int]]
    render_fixed_camera: Callable[..., Any]
    render_free_camera: Callable[..., Any]
    render_robot_map: Callable[..., Image.Image]
    should_use_fpv_as_verify_focus: Callable[..., bool]
    backend: str


def write_snapshot(
    state: dict[str, Any],
    output_path: Path,
    title: str,
    *,
    width: int,
    height: int,
    hooks: MolmoWorkerOutputHooks,
) -> dict[str, Any]:
    width, height = hooks.render_dimensions(width, height)
    model, data = hooks.load_model_data_for_state(state)
    hooks.apply_qpos(data, state["qpos"])
    mujoco.mj_forward(model, data)
    renderer = mujoco.Renderer(model, height=height, width=width)
    camera = mujoco.MjvCamera()
    camera.type = mujoco.mjtCamera.mjCAMERA_FREE
    camera.lookat[:] = [8.5, 6.5, 0.8]
    camera.distance = 9.5
    camera.azimuth = 225
    camera.elevation = -45
    renderer.update_scene(data, camera=camera)
    frame = renderer.render()
    renderer.close()
    output_path.parent.mkdir(parents=True, exist_ok=True)
    Image.fromarray(frame).save(output_path)
    return hooks.ok("snapshot", path=str(output_path), title=title, shape=list(frame.shape))


def write_robot_views(
    state: dict[str, Any],
    output_dir: Path,
    label: str,
    *,
    focus_object_id: str | None = None,
    focus_receptacle_id: str | None = None,
    camera_yaw_offset_deg: float = 0.0,
    camera_pitch_offset_deg: float = 0.0,
    width: int,
    height: int,
    hooks: MolmoWorkerOutputHooks,
) -> dict[str, Any]:
    width, height = hooks.render_dimensions(width, height)
    hooks.count(state, "robot_views")
    if not state.get("robot_included"):
        return hooks.error("robot_views", "robot_not_included")
    if focus_object_id is not None and focus_object_id not in state["objects"]:
        return hooks.error("robot_views", "stale_reference", object_id=focus_object_id)
    if focus_receptacle_id is not None and focus_receptacle_id not in state["receptacles"]:
        return hooks.error("robot_views", "stale_reference", receptacle_id=focus_receptacle_id)
    model, data = hooks.load_model_data_for_state(state)
    hooks.apply_qpos(data, state["qpos"])
    camera_adjustment = hooks.apply_robot_view_camera_offset(
        model,
        data,
        yaw_offset_deg=camera_yaw_offset_deg,
        pitch_offset_deg=camera_pitch_offset_deg,
    )
    mujoco.mj_forward(model, data)
    hooks.refresh_object_positions(model, data, state)

    output_dir.mkdir(parents=True, exist_ok=True)
    safe_label = safe_file_stem(label)
    view_paths = _robot_view_paths(output_dir, safe_label)

    focus = hooks.focus_payload(state, focus_object_id, focus_receptacle_id)
    fpv = hooks.render_fixed_camera(model, data, "robot_0/head_camera", width=width, height=height)
    verify_camera = hooks.focus_camera(state, focus)
    verify = hooks.render_free_camera(model, data, verify_camera, width=width, height=height)
    chase = hooks.render_fixed_camera(
        model,
        data,
        "robot_0/camera_follower",
        width=width,
        height=height,
    )
    camera_diagnostics = {
        "schema": "mujoco_robot_view_camera_diagnostics_v1",
        "backend": hooks.backend,
        "render_resolution": {"width": width, "height": height},
        "camera_adjustment": camera_adjustment,
        "views": {
            "fpv": hooks.fixed_camera_diagnostics(model, data, "robot_0/head_camera"),
            "chase": hooks.fixed_camera_diagnostics(model, data, "robot_0/camera_follower"),
            "verify": hooks.free_camera_diagnostics(verify_camera),
        },
    }
    fpv_camera = "robot_0/head_camera"
    focus["fpv_visibility"] = hooks.focus_visibility(
        model,
        data,
        fpv_camera,
        focus,
        frame=fpv,
    )
    focus["visibility"] = hooks.focus_visibility(
        model,
        data,
        verify_camera,
        focus,
        frame=verify,
    )
    focus = hooks.annotate_focus_visual_grounding(focus)
    if hooks.should_use_fpv_as_verify_focus(focus):
        verify = fpv.copy()
        fallback_visibility = dict(focus["fpv_visibility"])
        fallback_visibility["fallback_source"] = "fpv_focus_visibility"
        fallback_visibility.setdefault(
            "evidence_note",
            "Verify frame reused FPV because the closeup camera missed the focused object.",
        )
        focus["visibility"] = fallback_visibility
    color_profile = robot_view_display_color_profile()
    import numpy as np

    color_management: dict[str, dict[str, Any]] = {}
    fpv, color_management["fpv"] = apply_camera_color_profile(
        fpv,
        np=np,
        profile=color_profile,
        backend=hooks.backend,
        view_id="fpv",
    )
    chase, color_management["chase"] = apply_camera_color_profile(
        chase,
        np=np,
        profile=color_profile,
        backend=hooks.backend,
        view_id="chase",
    )
    verify, color_management["verify"] = apply_camera_color_profile(
        verify,
        np=np,
        profile=color_profile,
        backend=hooks.backend,
        view_id="verify",
    )
    camera_control_contract = robot_mounted_head_camera_control_contract(
        backend="molmospaces-mujoco",
        fpv_source="robot_0/head_camera",
        verify_source="mujoco_focus_camera",
        chase_source="robot_0/camera_follower",
        pose_source="rby1m_robot_qpos",
        lens_source="mujoco_model_camera_defaults",
        robot_pose=dict(state.get("robot_pose") or {}),
        focus=focus,
        color_profile=color_profile,
        color_management=color_management,
    )
    camera_control_contract["camera_adjustment"] = camera_adjustment
    camera_control_contract["agent_facing_fpv"]["camera_adjustment"] = camera_adjustment
    Image.fromarray(fpv).save(view_paths["fpv"])
    Image.fromarray(chase).save(view_paths["chase"])
    verify_image = Image.fromarray(verify)
    hooks.annotate_focus_image(verify_image, focus)
    verify_image.save(view_paths["verify"])
    topdown_request = _robot_views_topdown_camera_request(state, width=width, height=height)
    topdown_result = hooks.render_camera_views_with_model_data(
        model,
        data,
        state=state,
        output_dir=output_dir / f"{safe_label}.topdown_scene",
        camera_request=topdown_request,
        width=width,
        height=height,
    )
    topdown_source = Path(
        resolve_home_relative_path(str(topdown_result.get("images", {}).get("topdown_scene") or ""))
    )
    if not topdown_source.is_file():
        return hooks.error(
            "robot_views",
            "topdown_scene_render_missing",
            topdown_result=topdown_result,
        )
    Image.open(topdown_source).convert("RGB").save(view_paths["topdown"])

    return hooks.ok(
        "robot_views",
        backend=hooks.backend,
        robot_name=state.get("robot_name"),
        robot_pose=state.get("robot_pose"),
        robot_trajectory=state.get("robot_trajectory", []),
        view_variant="molmospaces-rby1m-fpv-topdown-chase-verify",
        view_provenance=state.get("robot_view_provenance", {}),
        camera_control_contract=camera_control_contract,
        camera_diagnostics=camera_diagnostics,
        topdown_scene_render=topdown_result,
        camera_adjustment=camera_adjustment,
        color_profile=color_profile,
        color_management=color_management,
        focus=focus,
        room_outline_count=len(state.get("room_outlines", [])),
        views={key: str(path) for key, path in view_paths.items()},
        shapes={
            "fpv": list(fpv.shape),
            "chase": list(chase.shape),
            "verify": list(verify.shape),
            "topdown": list(Image.open(view_paths["topdown"]).size[::-1]) + [3],
        },
        render_resolution={"width": width, "height": height},
    )


def _robot_view_paths(output_dir: Path, safe_label: str) -> dict[str, Path]:
    return {
        view_id: output_dir / f"{safe_label}.{view_id}.png"
        for view_id in ("fpv", "chase", "topdown", "verify")
    }


def robot_view_camera_adjustment(
    *,
    camera_yaw_offset_deg: float = 0.0,
    camera_pitch_offset_deg: float = 0.0,
    applied_joints: list[str] | None = None,
    unavailable_reason: str | None = None,
) -> dict[str, Any]:
    yaw = round(float(camera_yaw_offset_deg), 3)
    pitch = round(float(camera_pitch_offset_deg), 3)
    requested = bool(yaw or pitch)
    applied_joints = list(applied_joints or [])
    applied = requested and bool(applied_joints) and unavailable_reason is None
    if not requested:
        apply_status = "not_requested"
    elif applied:
        apply_status = "robot_head_joints_render_only"
    elif unavailable_reason:
        apply_status = "unavailable"
    else:
        apply_status = "no_matching_mujoco_head_joints"
    return {
        "schema": "robot_view_camera_adjustment_v1",
        "yaw_delta_deg": yaw,
        "pitch_delta_deg": pitch,
        "requested": requested,
        "applied": applied,
        "apply_status": apply_status,
        "applied_joints": applied_joints,
        "unavailable_reason": unavailable_reason,
        "evidence_note": (
            "Camera offset requests are applied to robot head joints for this render "
            "without persisting the adjusted qpos to worker state."
        ),
    }


def write_camera_views(
    state: dict[str, Any],
    output_dir: Path,
    camera_request: dict[str, Any] | list[dict[str, Any]],
    *,
    width: int,
    height: int,
    hooks: MolmoWorkerOutputHooks,
) -> dict[str, Any]:
    hooks.count(state, "camera_views")
    camera_request = normalize_camera_control_request(camera_request, width=width, height=height)
    resolution = camera_request["render_resolution"]
    width, height = hooks.render_dimensions(resolution["width"], resolution["height"])
    model, data = hooks.load_model_data_for_state(state)
    hooks.apply_qpos(data, state["qpos"])
    mujoco.mj_forward(model, data)
    hooks.refresh_object_positions(model, data, state)
    return hooks.render_camera_views_with_model_data(
        model,
        data,
        state=state,
        output_dir=output_dir,
        camera_request=camera_request,
        width=width,
        height=height,
    )


def _robot_views_topdown_camera_request(
    state: dict[str, Any],
    *,
    width: int,
    height: int,
) -> dict[str, Any]:
    alignment = _scene_alignment(state, width=width, height=height)
    center = alignment["center"]
    vertical_fov_deg = 45.0
    camera_distance = (
        float(alignment["span_y_m"]) / (2.0 * math.tan(math.radians(vertical_fov_deg / 2.0))) * 1.04
    )
    camera_height = float(center[2]) + max(1.0, camera_distance)
    return canonical_scene_camera_control_request(
        [
            {
                "view_id": "topdown_scene",
                "label": "Top-down Scene View",
                "camera_basis": "whole_scene_true_topdown_aligned_to_scene_bounds",
                "eye": [center[0], center[1], camera_height],
                "target": center,
                "azimuth": 90.0,
                "scene_alignment": alignment,
                "calibration_status": "mujoco_scene_rendered",
                "robot_view_role": "topdown",
            }
        ],
        lens={"vertical_fov_deg": vertical_fov_deg, "focal_length_mm": 24.0},
        width=width,
        height=height,
    )


def _scene_alignment(
    state: dict[str, Any],
    *,
    width: int,
    height: int,
) -> dict[str, Any]:
    points = _scene_points(state)
    if not points:
        min_x = min_y = -0.5
        max_x = max_y = 0.5
    else:
        xs = [point[0] for point in points]
        ys = [point[1] for point in points]
        min_x, max_x = min(xs), max(xs)
        min_y, max_y = min(ys), max(ys)
    pad = 0.35
    min_x -= pad
    max_x += pad
    min_y -= pad
    max_y += pad
    span_x = max(max_x - min_x, 1.0)
    span_y = max(max_y - min_y, 1.0)
    target_aspect = max(float(width) / max(float(height), 1.0), 0.001)
    current_aspect = span_x / span_y
    if current_aspect < target_aspect:
        expanded_span_x = span_y * target_aspect
        extra = (expanded_span_x - span_x) / 2.0
        min_x -= extra
        max_x += extra
        span_x = expanded_span_x
    elif current_aspect > target_aspect:
        expanded_span_y = span_x / target_aspect
        extra = (expanded_span_y - span_y) / 2.0
        min_y -= extra
        max_y += extra
        span_y = expanded_span_y
    center = [(min_x + max_x) / 2.0, (min_y + max_y) / 2.0, 0.4]
    return {
        "schema": "molmospaces_robot_view_scene_alignment_v1",
        "bounds": {
            "min_x": round(min_x, 6),
            "max_x": round(max_x, 6),
            "min_y": round(min_y, 6),
            "max_y": round(max_y, 6),
        },
        "center": [round(float(value), 6) for value in center],
        "span_x_m": round(float(span_x), 6),
        "span_y_m": round(float(span_y), 6),
        "screen_coordinate_convention": "screen_x_world_positive_x_screen_y_world_negative_y",
        "topdown_azimuth_deg": 90.0,
    }


def _scene_points(state: dict[str, Any]) -> list[tuple[float, float]]:
    points: list[tuple[float, float]] = []
    points.extend(_room_outline_points(state.get("room_outlines") or []))
    points.extend(_collection_position_points(state.get("objects")))
    points.extend(_collection_position_points(state.get("receptacles")))
    points.extend(_pose_points(state.get("robot_trajectory") or []))
    points.extend(_pose_points([state.get("robot_pose")]))
    return points


def _room_outline_points(room_outlines: Any) -> list[tuple[float, float]]:
    points: list[tuple[float, float]] = []
    for outline in room_outlines:
        if not isinstance(outline, dict):
            continue
        center = outline.get("center")
        half_extents = outline.get("half_extents")
        if not (_is_xy(center) and _is_xy(half_extents)):
            continue
        points.append(
            (
                float(center[0]) - float(half_extents[0]),
                float(center[1]) - float(half_extents[1]),
            )
        )
        points.append(
            (
                float(center[0]) + float(half_extents[0]),
                float(center[1]) + float(half_extents[1]),
            )
        )
    return points


def _collection_position_points(collection: Any) -> list[tuple[float, float]]:
    if not isinstance(collection, dict):
        return []
    points: list[tuple[float, float]] = []
    for item in collection.values():
        if isinstance(item, dict) and _is_xy(item.get("position")):
            position = item["position"]
            points.append((float(position[0]), float(position[1])))
    return points


def _pose_points(poses: Any) -> list[tuple[float, float]]:
    points: list[tuple[float, float]] = []
    for pose in poses:
        if isinstance(pose, dict) and pose.get("x") is not None and pose.get("y") is not None:
            points.append((float(pose["x"]), float(pose["y"])))
    return points


def _is_xy(value: Any) -> bool:
    if not isinstance(value, (list, tuple)) or len(value) < 2:
        return False
    try:
        float(value[0])
        float(value[1])
    except (TypeError, ValueError):
        return False
    return True


def render_camera_views_with_model_data(
    model: Any,
    data: Any,
    *,
    state: dict[str, Any],
    output_dir: Path,
    camera_request: dict[str, Any] | list[dict[str, Any]],
    width: int,
    height: int,
    hooks: MolmoWorkerOutputHooks,
) -> dict[str, Any]:
    camera_request = normalize_camera_control_request(camera_request, width=width, height=height)
    resolution = camera_request["render_resolution"]
    width, height = hooks.render_dimensions(resolution["width"], resolution["height"])
    lens = camera_request.get("lens") if isinstance(camera_request.get("lens"), dict) else {}
    previous_fovy = float(model.vis.global_.fovy)
    model.vis.global_.fovy = float(lens.get("vertical_fov_deg", previous_fovy))
    output_dir.mkdir(parents=True, exist_ok=True)
    color_profile = camera_request.get("color_profile") or {}

    try:
        saved: dict[str, str] = {}
        shapes: dict[str, list[int]] = {}
        color_diagnostics: dict[str, dict[str, Any]] = {}
        views: list[dict[str, Any]] = []
        for index, raw_spec in enumerate(camera_request.get("views") or [], start=1):
            spec = hooks.camera_view_spec(raw_spec, index=index)
            camera = hooks.camera_from_view_spec(state, spec)
            frame = hooks.render_free_camera(model, data, camera, width=width, height=height)
            import numpy as np

            frame, color_diagnostic = apply_camera_color_profile(
                frame,
                np=np,
                profile=color_profile,
                backend="molmospaces-mujoco",
                view_id=str(spec["view_id"]),
            )
            output_path = output_dir / f"{spec['view_id']}.png"
            Image.fromarray(frame).save(output_path)
            saved[str(spec["view_id"])] = str(output_path)
            shapes[str(spec["view_id"])] = list(frame.shape)
            color_diagnostics[str(spec["view_id"])] = color_diagnostic
            views.append(
                {
                    **spec,
                    "image_path": str(output_path),
                    "shape": list(frame.shape),
                }
            )
    finally:
        model.vis.global_.fovy = previous_fovy
    return hooks.ok(
        "camera_views",
        backend=hooks.backend,
        camera_control_api=camera_request.get("api_name") or CAMERA_CONTROL_API_NAME,
        camera_request_schema=camera_request.get("schema"),
        calibration_status=camera_request.get("calibration_status"),
        lighting_profile=camera_request.get("lighting_profile") or {},
        color_profile=color_profile,
        color_management=color_diagnostics,
        lens=camera_request.get("lens") or {},
        view_variant=hooks.camera_request_variant(camera_request),
        visual_artifact_provenance=hooks.camera_request_provenance(camera_request),
        views=views,
        images=saved,
        shapes=shapes,
        render_resolution={"width": width, "height": height},
    )


def camera_request_variant(camera_request: dict[str, Any]) -> str:
    if camera_request.get("camera_model") == CANONICAL_CAMERA_MODEL:
        return "molmospaces-canonical-eye-target-camera-control-v1"
    return "molmospaces-anchor-orbit-camera-control-v1"


def camera_request_provenance(camera_request: dict[str, Any]) -> str:
    if camera_request.get("camera_model") == CANONICAL_CAMERA_MODEL:
        return "mujoco_camera_control_canonical_eye_target"
    return "mujoco_camera_control_anchor_orbit"


def safe_file_stem(value: str) -> str:
    return "".join(ch if ch.isalnum() or ch in {"-", "_"} else "_" for ch in value)
