"""Isaac Lab worker commands owner."""

from __future__ import annotations

import argparse
from pathlib import Path
from typing import Any, Callable

from PIL import Image

from roboclaws.backends.isaaclab import (
    isaac_camera_geometry,
    isaac_render_diagnostics,
    isaac_robot_import,
    isaac_robot_pose_focus,
    isaac_robot_view_artifacts,
    isaac_scenario_builders,
    isaac_semantic_pose_robot_view,
    isaac_worker_commands,
    isaac_worker_context,
    isaac_worker_outputs,
    isaac_worker_protocol,
)
from roboclaws.backends.isaaclab.runtime_settings import (
    REAL_ROBOT_VIEW_CAPTURE_METHOD,
    REAL_ROBOT_VIEW_RERENDER_METHOD,
    REAL_SMOKE_CAPTURE_METHOD,
    ROBOT_VIEW_KEYS,
)
from roboclaws.backends.isaaclab.runtime_state import (
    _with_isaac_robot_pose_hooks,
)

_dict = isaac_worker_context.dict_value
_has_xy = isaac_worker_context.has_xy
_isaac_native_render_diagnostics_unavailable = (
    isaac_render_diagnostics.native_render_diagnostics_unavailable
)
_objects_by_id = isaac_worker_context.objects_by_id
_receptacles_by_id = isaac_worker_context.receptacles_by_id

type _IsaacWorkerCommand = Callable[[argparse.Namespace, dict[str, Any]], dict[str, Any]]


def _isaac_worker_command_hooks() -> isaac_worker_commands.IsaacWorkerCommandHooks:

    from roboclaws.backends.isaaclab.runtime_state import (
        _apply_object_location,
        _isaac_placement_diagnostic,
        _record_semantic_pose_event,
        _record_waypoint_pose_event,
        _robot_pose_for_receptacle,
    )

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

    from roboclaws.backends.isaaclab.runtime_camera import (
        _load_camera_request_from_args,
        capture_scene_camera_views,
    )
    from roboclaws.backends.isaaclab.runtime_state import (
        _robot_pose_for_receptacle,
    )

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


_target_room_id_from_pose_inputs = _with_isaac_robot_pose_hooks(
    isaac_robot_pose_focus.target_room_id_from_pose_inputs
)

_robot_pose_for_waypoint = _with_isaac_robot_pose_hooks(
    isaac_robot_pose_focus.robot_pose_for_waypoint
)

_normalized_waypoint_robot_pose = _with_isaac_robot_pose_hooks(
    isaac_robot_pose_focus.normalized_waypoint_robot_pose
)

_robot_view_focus = _with_isaac_robot_pose_hooks(isaac_robot_pose_focus.robot_view_focus)

_focus_payload = _with_isaac_robot_pose_hooks(isaac_robot_pose_focus.focus_payload)

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

    from roboclaws.backends.isaaclab.runtime_capture import (
        capture_semantic_pose_robot_views,
    )

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

    from roboclaws.backends.isaaclab.runtime_state import (
        _rby1m_robot_import_plan,
    )

    return isaac_robot_import.robot_payload(robot_name, _rby1m_robot_import_plan(robot_name))
