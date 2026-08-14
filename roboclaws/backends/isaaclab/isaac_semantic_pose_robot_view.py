"""Isaac Lab backend runtime support."""

from __future__ import annotations

import math
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable


@dataclass(frozen=True)
class SemanticPoseRobotViewHooks:
    capture_semantic_pose_robot_views: Callable[..., dict[str, Any]]
    has_required_robot_view_images: Callable[[dict[str, str]], bool]
    semantic_pose_robot_view_provenance: Callable[..., dict[str, Any]]
    write_state_from_state_arg: Callable[[dict[str, Any]], None]


@dataclass(frozen=True)
class SemanticPoseRobotViewRequest:
    state: dict[str, Any]
    target_images: dict[str, Path]
    width: int
    height: int
    camera_yaw_offset_deg: float = 0.0
    camera_pitch_offset_deg: float = 0.0
    render_settle_frames: int = 0
    isaac_aa_op: int | None = None
    isaac_tonemap_op: int | None = None
    isaac_exposure_bias: float | None = None
    isaac_colorcorr_gain: tuple[float, float, float] | None = None
    focus_object_id: str | None = None
    focus_receptacle_id: str | None = None


ROBOT_VIEW_KEYS = ("fpv", "chase", "topdown", "verify")


def real_semantic_pose_robot_view_images(
    request: SemanticPoseRobotViewRequest,
    *,
    hooks: SemanticPoseRobotViewHooks,
    real_robot_view_rerender_method: str,
    isaac_rby1m_head_camera_prim: str,
) -> dict[str, str]:
    state = request.state
    scene_usd = _real_scene_usd(state)
    if scene_usd is None:
        return {}
    capture = _capture_semantic_pose_robot_views(request, scene_usd=scene_usd, hooks=hooks)
    if capture is None:
        return {}
    images = _robot_view_images(capture)
    if not hooks.has_required_robot_view_images(images):
        return {}
    semantic_pose_application = _dict(capture.get("semantic_pose_stage_application"))
    robot_pose_application = _dict(capture.get("robot_pose_stage_application"))
    robot_pose_rendered = robot_pose_application.get("status") == "applied"
    if not _semantic_pose_stage_rendered(semantic_pose_application, robot_pose_rendered):
        _record_stage_application_gap(
            state,
            semantic_pose_application=semantic_pose_application,
            robot_pose_application=robot_pose_application,
            hooks=hooks,
            real_robot_view_rerender_method=real_robot_view_rerender_method,
        )
        return {}
    _accept_semantic_pose_robot_views(
        state,
        capture=capture,
        images=images,
        scene_usd=str(scene_usd),
        robot_pose_rendered=robot_pose_rendered,
        hooks=hooks,
        real_robot_view_rerender_method=real_robot_view_rerender_method,
        isaac_rby1m_head_camera_prim=isaac_rby1m_head_camera_prim,
    )
    return images


def _real_scene_usd(state: dict[str, Any]) -> Path | None:
    runtime = _dict(state.get("runtime"))
    scene_usd = str(state.get("scene_usd") or "")
    if runtime.get("runtime_mode") != "real" or not scene_usd:
        return None
    path = Path(scene_usd)
    return path if path.is_file() else None


def _capture_semantic_pose_robot_views(
    request: SemanticPoseRobotViewRequest,
    *,
    scene_usd: Path,
    hooks: SemanticPoseRobotViewHooks,
) -> dict[str, Any] | None:
    try:
        return hooks.capture_semantic_pose_robot_views(
            **_capture_kwargs(request, scene_usd=scene_usd)
        )
    except Exception as exc:
        request.state.setdefault("mapping_gaps", []).append(
            {
                "area": "semantic_pose_robot_view_rerender",
                "status": "blocked_capability",
                "source": str(scene_usd),
                "detail": str(exc),
            }
        )
        hooks.write_state_from_state_arg(request.state)
        return None


def _capture_kwargs(
    request: SemanticPoseRobotViewRequest,
    *,
    scene_usd: Path,
) -> dict[str, Any]:
    kwargs: dict[str, Any] = {
        "state": _state_with_camera_adjustment(request),
        "scene_usd": scene_usd,
        "view_paths": request.target_images,
        "width": request.width,
        "height": request.height,
        "focus_object_id": request.focus_object_id,
        "focus_receptacle_id": request.focus_receptacle_id,
    }
    optional = {
        "render_settle_frames": request.render_settle_frames or None,
        "isaac_aa_op": request.isaac_aa_op,
        "isaac_tonemap_op": request.isaac_tonemap_op,
        "isaac_exposure_bias": request.isaac_exposure_bias,
        "isaac_colorcorr_gain": request.isaac_colorcorr_gain,
        "color_profile_override": _dict(request.state.get("robot_view_color_profile_override"))
        or None,
    }
    kwargs.update({key: value for key, value in optional.items() if value is not None})
    return kwargs


def _state_with_camera_adjustment(request: SemanticPoseRobotViewRequest) -> dict[str, Any]:
    yaw_offset = float(request.camera_yaw_offset_deg or 0.0)
    pitch_offset = float(request.camera_pitch_offset_deg or 0.0)
    if not yaw_offset and not pitch_offset:
        return request.state
    adjusted = dict(request.state)
    semantic_pose_state = dict(_dict(adjusted.get("semantic_pose_state")))
    robot_pose = dict(_dict(semantic_pose_state.get("robot_pose")))
    if pitch_offset:
        base_pitch = float(robot_pose.get("head_pitch") or 0.0)
        robot_pose["head_pitch"] = base_pitch + math.radians(pitch_offset)
        robot_pose["head_pitch_source"] = "camera_pitch_offset_deg"
    robot_pose["camera_adjustment"] = {
        "yaw_delta_deg": yaw_offset,
        "pitch_delta_deg": pitch_offset,
        "pitch_applied_to_static_head_camera": bool(pitch_offset),
        "yaw_application": "not_applied_static_head_camera",
    }
    semantic_pose_state["robot_pose"] = robot_pose
    adjusted["semantic_pose_state"] = semantic_pose_state
    return adjusted


def _robot_view_images(capture: dict[str, Any]) -> dict[str, str]:
    return {
        key: str(value)
        for key, value in _dict(capture.get("robot_view_images")).items()
        if key in ROBOT_VIEW_KEYS and value
    }


def _semantic_pose_stage_rendered(
    semantic_pose_application: dict[str, Any],
    robot_pose_rendered: bool,
) -> bool:
    return semantic_pose_application.get("rendered_to_usd") is True or robot_pose_rendered


def _record_stage_application_gap(
    state: dict[str, Any],
    *,
    semantic_pose_application: dict[str, Any],
    robot_pose_application: dict[str, Any],
    hooks: SemanticPoseRobotViewHooks,
    real_robot_view_rerender_method: str,
) -> None:
    state.setdefault("mapping_gaps", []).append(
        {
            "area": "semantic_pose_robot_view_rerender",
            "status": "blocked_capability",
            "source": real_robot_view_rerender_method,
            "detail": (
                "Isaac produced robot-view images, but semantic pose state was not "
                "applied to the USD stage, so the images are not accepted as "
                "semantic-pose-synced robot-view evidence."
            ),
            "semantic_pose_stage_application": semantic_pose_application,
            "robot_pose_stage_application": robot_pose_application,
        }
    )
    hooks.write_state_from_state_arg(state)


def _accept_semantic_pose_robot_views(
    state: dict[str, Any],
    *,
    capture: dict[str, Any],
    images: dict[str, str],
    scene_usd: str,
    robot_pose_rendered: bool,
    hooks: SemanticPoseRobotViewHooks,
    real_robot_view_rerender_method: str,
    isaac_rby1m_head_camera_prim: str,
) -> None:
    mounted_head_camera = bool(capture.get("robot_view_uses_mounted_head_camera"))
    semantic_pose_application = _dict(capture.get("semantic_pose_stage_application"))
    robot_pose_application = _dict(capture.get("robot_pose_stage_application"))
    state["robot_view_images"] = images
    state["robot_view_provenance"] = hooks.semantic_pose_robot_view_provenance(
        mounted_head_camera=mounted_head_camera,
        head_camera_equivalent=not mounted_head_camera,
    )
    state["semantic_pose_view_capture"] = _semantic_pose_view_capture_payload(
        capture,
        scene_usd=scene_usd,
        mounted_head_camera=mounted_head_camera,
        semantic_pose_application=semantic_pose_application,
        robot_pose_application=robot_pose_application,
        real_robot_view_rerender_method=real_robot_view_rerender_method,
        isaac_rby1m_head_camera_prim=isaac_rby1m_head_camera_prim,
    )
    _copy_capture_state_fields(state, capture)
    _replace_robot_view_mapping_gap(state, real_robot_view_rerender_method)
    _update_semantic_pose_state(state, robot_pose_rendered=robot_pose_rendered)
    hooks.write_state_from_state_arg(state)


def _semantic_pose_view_capture_payload(
    capture: dict[str, Any],
    *,
    scene_usd: str,
    mounted_head_camera: bool,
    semantic_pose_application: dict[str, Any],
    robot_pose_application: dict[str, Any],
    real_robot_view_rerender_method: str,
    isaac_rby1m_head_camera_prim: str,
) -> dict[str, Any]:
    return {
        "schema": "isaac_semantic_pose_robot_view_capture_v1",
        "capture_method": real_robot_view_rerender_method,
        "scene_usd": scene_usd,
        "rendered_to_usd": True,
        "render_steps": int(capture.get("render_steps") or 0),
        "render_settle_frames": int(capture.get("render_settle_frames") or 0),
        "scene_bounds": _dict(capture.get("scene_bounds")),
        "canonical_camera_control": False,
        "robot_mounted_head_camera": mounted_head_camera,
        "head_camera_equivalent": not mounted_head_camera,
        "head_camera_prim_path": isaac_rby1m_head_camera_prim if mounted_head_camera else "",
        "robot_stage": _dict(capture.get("robot_stage")),
        "semantic_pose_stage_application": semantic_pose_application,
        "robot_pose_stage_application": robot_pose_application,
        "camera_diagnostics": _dict(capture.get("camera_diagnostics")),
        "lighting_profile": _dict(capture.get("lighting_profile")),
        "lighting_diagnostics": _dict(capture.get("lighting_diagnostics")),
        "color_profile": _dict(capture.get("color_profile")),
        "color_management": _dict(capture.get("color_management")),
        "native_render_diagnostics": _dict(capture.get("native_render_diagnostics")),
    }


def _copy_capture_state_fields(state: dict[str, Any], capture: dict[str, Any]) -> None:
    state["scene_bounds"] = _dict(capture.get("scene_bounds")) or None
    state["robot_view_color_profile"] = _dict(capture.get("color_profile"))
    state["robot_view_color_management"] = _dict(capture.get("color_management"))
    state["robot_view_camera_diagnostics"] = _dict(capture.get("camera_diagnostics"))
    state["native_render_diagnostics"] = _dict(capture.get("native_render_diagnostics"))
    state["robot_view_lighting_profile"] = _dict(capture.get("lighting_profile"))
    state["robot_view_lighting_diagnostics"] = _dict(capture.get("lighting_diagnostics"))
    state.pop("canonical_robot_view_camera_control_request", None)
    state.pop("canonical_robot_view_camera_control_capture", None)


def _replace_robot_view_mapping_gap(
    state: dict[str, Any],
    real_robot_view_rerender_method: str,
) -> None:
    mapping_gaps = [
        item
        for item in state.get("mapping_gaps", [])
        if not (isinstance(item, dict) and item.get("area") == "robot_view_variants")
    ]
    mapping_gaps.append(
        {
            "area": "robot_view_variants",
            "status": "real_rendering_proven",
            "source": real_robot_view_rerender_method,
            "detail": (
                "Robot-view images were recaptured from the loaded USD scene after "
                "applying backend semantic pose state. FPV uses the imported RBY1M "
                "mounted head camera when the robot USD import artifact is present; "
                "otherwise it is explicitly marked as a head-camera equivalent. "
                "Chase/map remain auxiliary report views. This is semantic pose "
                "report evidence, not planner-backed or physics-backed "
                "manipulation proof."
            ),
        }
    )
    state["mapping_gaps"] = mapping_gaps


def _update_semantic_pose_state(
    state: dict[str, Any],
    *,
    robot_pose_rendered: bool,
) -> None:
    semantic_pose_state = _dict(state.get("semantic_pose_state"))
    semantic_pose_state["rendered_to_usd"] = True
    semantic_pose_state["semantic_pose_view_capture"] = dict(state["semantic_pose_view_capture"])
    if robot_pose_rendered:
        semantic_pose_state["robot_pose_rendered_to_usd"] = True
    semantic_pose_state["evidence_note"] = (
        "Semantic cleanup primitives still update backend JSON pose/articulation state "
        "and are not planner-backed manipulation proof. The current report robot-view "
        "images were recaptured from Isaac after applying that semantic pose state to "
        "the loaded USD stage."
    )
    state["semantic_pose_state"] = semantic_pose_state


def _dict(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}
