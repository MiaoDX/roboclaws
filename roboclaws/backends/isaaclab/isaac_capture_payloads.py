"""Assemble stable result payloads for Isaac camera captures."""

from __future__ import annotations

from typing import Any, Callable

from roboclaws.household.isaac_lab_backend import ISAACLAB_SUBPROCESS_BACKEND


def capture_payload(
    *,
    request: Any,
    stage: Any,
    render_state: Any,
    rendered: Any,
    segmentation_payload: Callable[[], dict[str, Any]],
) -> dict[str, Any]:
    return {
        "render_steps": rendered.total_render_steps,
        "robot_view_images": rendered.saved,
        "scene_bounds": stage.scene_bounds,
        "robot_stage": stage.robot_stage,
        "robot_view_uses_mounted_head_camera": stage.mounted_head_camera,
        "robot_pose_stage_application": rendered.robot_pose_application,
        "camera_diagnostics": camera_diagnostics_payload(
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
        "segmentation": segmentation_payload(),
    }


def camera_diagnostics_payload(
    *, request: Any, stage: Any, render_state: Any, rendered: Any
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
