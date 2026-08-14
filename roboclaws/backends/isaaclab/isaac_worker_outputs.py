"""Isaac Lab backend runtime support."""

from __future__ import annotations

import argparse
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

from roboclaws.household.camera_control import CAMERA_CONTROL_API_NAME, CANONICAL_CAMERA_MODEL
from roboclaws.household.isaac_lab_backend import (
    ISAACLAB_ROBOT_VIEW_VARIANT,
    ISAACLAB_SUBPROCESS_BACKEND,
)
from roboclaws.household.robot_view_camera_control import (
    backend_local_robot_view_camera_control_contract,
    robot_mounted_head_camera_control_contract,
)


@dataclass(frozen=True)
class IsaacWorkerOutputHooks:
    camera_capture_provenance: Callable[..., str]
    camera_capture_variant: Callable[..., str]
    capture_scene_camera_views: Callable[..., dict[str, Any]]
    copy_real_robot_view_images: Callable[..., dict[str, list[int]]]
    copy_real_snapshot_image: Callable[..., list[int]]
    count: Callable[..., Any]
    dict_value: Callable[..., dict[str, Any]]
    error: Callable[..., dict[str, Any]]
    has_xy: Callable[..., bool]
    load_camera_request_from_args: Callable[..., Any]
    native_render_diagnostics_from_state: Callable[..., dict[str, Any]]
    ok: Callable[..., dict[str, Any]]
    real_rendering_proven: Callable[..., bool]
    real_robot_view_images: Callable[..., dict[str, str]]
    real_semantic_pose_robot_view_images: Callable[..., dict[str, str]]
    real_snapshot_source_image: Callable[..., Path]
    robot_pose_for_receptacle: Callable[..., dict[str, Any]]
    robot_view_camera_control_contract: Callable[..., dict[str, Any]]
    robot_view_command_provenance: Callable[..., dict[str, Any]]
    robot_view_focus: Callable[..., dict[str, Any]]
    robot_view_rendered_robot_pose: Callable[..., dict[str, Any]]
    safe_file_stem: Callable[..., str]
    write_placeholder_image: Callable[..., Any]
    write_state_from_state_arg: Callable[..., Any]
    real_smoke_capture_method: str


def write_snapshot(
    args: argparse.Namespace,
    state: dict[str, Any],
    *,
    hooks: IsaacWorkerOutputHooks,
) -> dict[str, Any]:
    hooks.count(state, "snapshot")
    if hooks.real_rendering_proven(state):
        try:
            source_path = hooks.real_snapshot_source_image(state)
            shape = hooks.copy_real_snapshot_image(
                source_path,
                args.output_path,
                width=args.render_width,
                height=args.render_height,
            )
        except RuntimeError as exc:
            return hooks.error("snapshot", "real_snapshot_image_invalid", reason=str(exc))
        hooks.write_state_from_state_arg(state)
        return hooks.ok(
            "snapshot",
            output_path=str(args.output_path),
            visual_artifact_provenance=hooks.real_smoke_capture_method,
            placeholder_visuals=False,
            native_render_diagnostics=hooks.native_render_diagnostics_from_state(state),
            snapshot_provenance={
                "source": "isaac_runtime_rgb_capture",
                "source_path": str(source_path),
                "output_path": str(args.output_path),
                "visual_artifact_provenance": hooks.real_smoke_capture_method,
                "placeholder_visuals": False,
                "static_isaac_capture": True,
                "semantic_pose_rendered": False,
                "shape": shape,
                "reason": (
                    "Snapshot reuses a real Isaac RGB capture. Semantic pose edits "
                    "are not rendered back into the USD stage yet."
                ),
            },
        )
    hooks.write_placeholder_image(
        args.output_path,
        title=args.title,
        subtitle=state["runtime"]["renderer_mode"],
        state=state,
        width=args.render_width,
        height=args.render_height,
    )
    hooks.write_state_from_state_arg(state)
    return hooks.ok(
        "snapshot",
        output_path=str(args.output_path),
        visual_artifact_provenance=state["runtime"]["visual_artifact_provenance"],
        placeholder_visuals=True,
        native_render_diagnostics=hooks.native_render_diagnostics_from_state(state),
        snapshot_provenance={
            "source": "placeholder_protocol_image",
            "output_path": str(args.output_path),
            "visual_artifact_provenance": state["runtime"]["visual_artifact_provenance"],
            "placeholder_visuals": True,
            "static_isaac_capture": False,
            "semantic_pose_rendered": False,
            "reason": "Snapshot is a CI-safe placeholder because real Isaac rendering is unproven.",
        },
    )


def write_robot_views(
    args: argparse.Namespace,
    state: dict[str, Any],
    *,
    hooks: IsaacWorkerOutputHooks,
) -> dict[str, Any]:
    hooks.count(state, "robot_views")
    if state.get("robot") is None:
        return hooks.error("robot_views", "robot_not_included")
    args.output_dir.mkdir(parents=True, exist_ok=True)
    safe_label = hooks.safe_file_stem(args.label)
    views = {
        "fpv": args.output_dir / f"{safe_label}.fpv.png",
        "chase": args.output_dir / f"{safe_label}.chase.png",
        "topdown": args.output_dir / f"{safe_label}.topdown.png",
        "verify": args.output_dir / f"{safe_label}.verify.png",
    }
    real_views = hooks.real_semantic_pose_robot_view_images(
        state,
        views,
        width=args.render_width,
        height=args.render_height,
        camera_yaw_offset_deg=float(args.camera_yaw_offset_deg or 0.0),
        camera_pitch_offset_deg=float(args.camera_pitch_offset_deg or 0.0),
        render_settle_frames=int(args.render_settle_frames or 0),
        isaac_aa_op=args.isaac_aa_op,
        isaac_tonemap_op=args.isaac_tonemap_op,
        isaac_exposure_bias=args.isaac_exposure_bias,
        isaac_colorcorr_gain=args.isaac_colorcorr_gain,
        focus_object_id=args.focus_object_id,
        focus_receptacle_id=args.focus_receptacle_id,
    )
    semantic_pose_state_refreshed = bool(real_views)
    if not real_views:
        real_views = hooks.real_robot_view_images(state)
    shapes: dict[str, list[int]] = {}
    if real_views:
        try:
            shapes = hooks.copy_real_robot_view_images(
                real_views,
                views,
                width=args.render_width,
                height=args.render_height,
            )
        except RuntimeError as exc:
            return hooks.error(
                "robot_views",
                "real_robot_view_images_invalid",
                reason=str(exc),
            )
    elif hooks.real_rendering_proven(state):
        return hooks.error(
            "robot_views",
            "real_robot_view_images_unavailable",
            reason=(
                "Real Isaac rendering was proven, but FPV/chase/map/verify view images "
                "were not recorded in worker state."
            ),
        )
    else:
        for view_name, path in views.items():
            hooks.write_placeholder_image(
                path,
                title=f"{args.label} {view_name}",
                subtitle=state["runtime"]["renderer_mode"],
                state=state,
                width=args.render_width,
                height=args.render_height,
                focus_object_id=args.focus_object_id,
                focus_receptacle_id=args.focus_receptacle_id,
            )
            shapes[view_name] = [args.render_height, args.render_width, 3]
    hooks.write_state_from_state_arg(state)
    robot_pose = hooks.robot_view_rendered_robot_pose(state)
    focus = hooks.robot_view_focus(
        state,
        robot_pose,
        focus_object_id=args.focus_object_id,
        focus_receptacle_id=args.focus_receptacle_id,
    )
    return hooks.ok(
        "robot_views",
        output_dir=str(args.output_dir),
        view_variant=ISAACLAB_ROBOT_VIEW_VARIANT,
        view_provenance=hooks.robot_view_command_provenance(
            state,
            semantic_pose_state_refreshed=semantic_pose_state_refreshed,
        ),
        camera_control_contract=hooks.robot_view_camera_control_contract(
            state,
            robot_pose=robot_pose,
            focus=focus,
        ),
        robot_pose=robot_pose,
        robot_trajectory=[robot_pose],
        room_outline_count=len(state.get("room_outlines") or []),
        color_profile=hooks.dict_value(state.get("robot_view_color_profile")),
        color_management=hooks.dict_value(state.get("robot_view_color_management")),
        lighting_profile=hooks.dict_value(state.get("robot_view_lighting_profile")),
        lighting_diagnostics=hooks.dict_value(state.get("robot_view_lighting_diagnostics")),
        camera_diagnostics=hooks.dict_value(state.get("robot_view_camera_diagnostics")),
        native_render_diagnostics=hooks.native_render_diagnostics_from_state(state),
        focus=focus,
        views={key: str(path) for key, path in views.items()},
        shapes=shapes,
        render_resolution={"width": args.render_width, "height": args.render_height},
        render_settle_frames=int(args.render_settle_frames or 0),
    )


def robot_view_rendered_robot_pose(
    state: dict[str, Any],
    *,
    hooks: IsaacWorkerOutputHooks,
) -> dict[str, Any]:
    semantic_robot_pose = hooks.dict_value(
        hooks.dict_value(state.get("semantic_pose_state")).get("robot_pose")
    )
    if hooks.has_xy(semantic_robot_pose):
        return semantic_robot_pose
    return hooks.robot_pose_for_receptacle(
        state,
        str(state.get("current_receptacle_id") or "floor_01"),
    )


def write_camera_views(
    args: argparse.Namespace,
    state: dict[str, Any],
    *,
    hooks: IsaacWorkerOutputHooks,
) -> dict[str, Any]:
    hooks.count(state, "camera_views")
    runtime = hooks.dict_value(state.get("runtime"))
    scene_usd = str(state.get("scene_usd") or "")
    if runtime.get("runtime_mode") != "real":
        return hooks.error("camera_views", "real_runtime_required")
    if not scene_usd or not Path(scene_usd).is_file():
        return hooks.error("camera_views", "local_scene_usd_required", scene_usd=scene_usd)
    camera_request = hooks.load_camera_request_from_args(
        view_specs_path=args.view_specs_path,
        camera_request_path=args.camera_request_path,
        width=args.render_width,
        height=args.render_height,
    )
    capture = hooks.capture_scene_camera_views(
        scene_usd=Path(scene_usd),
        camera_request=camera_request,
        output_dir=args.output_dir,
        width=args.render_width,
        height=args.render_height,
        semantic_pose_state=hooks.dict_value(state.get("semantic_pose_state")),
    )
    semantic_pose_application = hooks.dict_value(capture.get("semantic_pose_stage_application"))
    state["scene_camera_view_capture"] = {
        "schema": "isaac_scene_camera_view_capture_v1",
        "capture_method": "isaac_lab_camera_rgb_scene_probe",
        "scene_usd": scene_usd,
        "render_steps": int(capture.get("render_steps") or 0),
        "view_count": len(capture.get("views") or []),
        "semantic_pose_stage_application": semantic_pose_application,
        "semantic_pose_rendered": semantic_pose_application.get("rendered_to_usd") is True,
    }
    semantic_pose_state = hooks.dict_value(state.get("semantic_pose_state"))
    if semantic_pose_application.get("rendered_to_usd") is True:
        semantic_pose_state["rendered_to_usd"] = True
        semantic_pose_state["scene_camera_view_capture"] = dict(state["scene_camera_view_capture"])
        state["semantic_pose_state"] = semantic_pose_state
    hooks.write_state_from_state_arg(state)
    view_variant = hooks.camera_capture_variant(capture)
    provenance = hooks.camera_capture_provenance(capture)
    return hooks.ok(
        "camera_views",
        camera_control_api=capture.get("camera_control_api") or CAMERA_CONTROL_API_NAME,
        camera_request_schema=capture.get("camera_request_schema"),
        calibration_status=capture.get("calibration_status"),
        lighting_profile=capture.get("lighting_profile") or {},
        lighting_diagnostics=capture.get("lighting_diagnostics") or {},
        color_profile=capture.get("color_profile") or {},
        color_management=capture.get("color_management") or {},
        native_render_diagnostics=capture.get("native_render_diagnostics") or {},
        lens=capture.get("lens") or {},
        derived_lens=capture.get("derived_lens") or {},
        view_variant=view_variant,
        visual_artifact_provenance=provenance,
        scene_usd=scene_usd,
        views=capture.get("views") or [],
        images=capture.get("images") or {},
        shapes=capture.get("shapes") or {},
        scene_bounds=capture.get("scene_bounds"),
        semantic_pose_stage_application=semantic_pose_application,
        semantic_pose_rendered=semantic_pose_application.get("rendered_to_usd") is True,
        render_steps=int(capture.get("render_steps") or 0),
        render_resolution={"width": args.render_width, "height": args.render_height},
    )


def locations_command(_: argparse.Namespace, state: dict[str, Any]) -> dict[str, Any]:
    return {"ok": True, "tool": "locations", "final_locations": state["locations"]}


def robot_view_camera_control_contract(
    state: dict[str, Any],
    *,
    robot_pose: dict[str, Any] | None = None,
    focus: dict[str, Any] | None = None,
    hooks: IsaacWorkerOutputHooks,
) -> dict[str, Any]:
    provenance = hooks.dict_value(state.get("robot_view_provenance"))
    semantic_pose_state_refreshed = provenance.get("semantic_pose_state_refreshed")
    robot_import = hooks.dict_value(state.get("robot_import"))
    mounted_head_camera = bool(
        provenance.get("robot_mounted_head_camera")
        or robot_import.get("status") == "imported"
        or hooks.dict_value(state.get("semantic_pose_view_capture")).get(
            "robot_mounted_head_camera"
        )
    )
    head_camera_equivalent = (
        bool(provenance.get("head_camera_equivalent")) and not mounted_head_camera
    )
    if mounted_head_camera or head_camera_equivalent or robot_import:
        status = (
            "robot_mounted_head_camera_robot_view"
            if mounted_head_camera
            else "robot_head_camera_equivalent_robot_view"
        )
        camera_model = (
            "robot_mounted_head_camera_v1"
            if mounted_head_camera
            else "robot_head_camera_equivalent_v1"
        )
        contract = robot_mounted_head_camera_control_contract(
            backend=ISAACLAB_SUBPROCESS_BACKEND,
            status=status,
            camera_model=camera_model,
            fpv_source=str(
                provenance.get("fpv")
                or (
                    "isaac_lab_camera_rgb_robot_mounted_head_camera:fpv"
                    if mounted_head_camera
                    else "isaac_lab_head_camera_equivalent:fpv"
                )
            ),
            verify_source=str(provenance.get("verify") or "isaac_lab_semantic_pose_verify_camera"),
            chase_source="robot_relative_camera_follower",
            pose_source=str(
                hooks.dict_value(robot_pose).get("pose_source")
                or "roboclaws_shared_scene_frame_support_pose"
            ),
            lens_source=(
                "rby1m_mujoco_robot_0/head_camera_extrinsics_and_fov"
                if mounted_head_camera
                else "rby1m_head_camera_contract_pending_isaac_robot_import"
            ),
            camera_prim_path=str(robot_import.get("head_camera_prim_path") or ""),
            robot_asset=robot_import,
            robot_pose=dict(robot_pose or {}),
            focus=dict(focus or {}),
            color_profile=hooks.dict_value(state.get("robot_view_color_profile")),
            color_management=hooks.dict_value(state.get("robot_view_color_management")),
            lighting_profile=hooks.dict_value(state.get("robot_view_lighting_profile")),
        )
        contract.update(
            {
                "semantic_pose_state_refreshed": semantic_pose_state_refreshed,
                "evidence_note": (
                    "Isaac cleanup FPV uses the imported RBY1M mounted head camera "
                    "when the robot USD import artifact is present. Without that "
                    "artifact it remains explicitly marked as head-camera-equivalent. "
                    "Chase is rendered from a robot-relative rear/high report camera; "
                    "map remains auxiliary report evidence."
                ),
            }
        )
        return contract
    contract = backend_local_robot_view_camera_control_contract(
        backend=ISAACLAB_SUBPROCESS_BACKEND,
        status="backend_local_scene_bounds_camera",
        fpv_source=str(provenance.get("fpv") or "isaac_lab_scene_bounds_fpv"),
        verify_source=str(provenance.get("verify") or "isaac_lab_scene_bounds_verify"),
        pose_source="isaac_support_pose_near_current_receptacle",
        lens_source="isaac_robot_view_pinhole_defaults_24mm_20.955mm_aperture",
    )
    contract.update(
        {
            "semantic_pose_state_refreshed": semantic_pose_state_refreshed,
            "robot_pose": dict(robot_pose or {}),
            "focus": dict(focus or {}),
            "evidence_note": (
                "Isaac cleanup robot views currently use backend-local "
                "scene-bounds/support-pose camera placement, not "
                "roboclaws.camera_control.render_views. They are useful report "
                "evidence, but they are not yet proof that the agent-facing FPV is "
                "backend-swappable at identical scene-frame pose/FOV."
            ),
        }
    )
    return contract


def camera_capture_variant(capture: dict[str, Any]) -> str:
    if any(
        isinstance(item, dict) and item.get("camera_model") == CANONICAL_CAMERA_MODEL
        for item in capture.get("views") or []
    ):
        return "isaaclab-canonical-eye-target-camera-control-v1"
    return "isaaclab-anchor-orbit-camera-control-v1"


def camera_capture_provenance(capture: dict[str, Any]) -> str:
    if any(
        isinstance(item, dict) and item.get("camera_model") == CANONICAL_CAMERA_MODEL
        for item in capture.get("views") or []
    ):
        return "isaac_lab_camera_rgb_canonical_eye_target_scene_probe"
    return "isaac_lab_camera_rgb_anchor_orbit_scene_probe"
