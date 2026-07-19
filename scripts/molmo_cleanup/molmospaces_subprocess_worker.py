#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Callable

if __package__ in {None, ""}:
    repo_root = Path(__file__).resolve().parents[2]
    if str(repo_root) not in sys.path:
        sys.path.insert(0, str(repo_root))

import mujoco
from PIL import Image

from roboclaws.core.json_sources import read_json_value
from roboclaws.household.camera_control import (
    load_camera_control_request,
    normalize_camera_control_request,
)
from scripts.molmo_cleanup import (
    molmospaces_actions,
    molmospaces_focus_camera,
    molmospaces_placement,
    molmospaces_rendering,
    molmospaces_robot_pose,
    molmospaces_room_map,
    molmospaces_runtime_state,
    molmospaces_scenario_state,
    molmospaces_worker_cli,
    molmospaces_worker_init,
    molmospaces_worker_outputs,
    molmospaces_worker_protocol,
    molmospaces_worker_state,
)

BACKEND = "molmospaces_subprocess"
API_SEMANTIC_PROVENANCE = "api_semantic"
DEFAULT_RENDER_WIDTH = 540
DEFAULT_RENDER_HEIGHT = 360
_MODEL_DATA_CACHE: dict[tuple[str, str], tuple[mujoco.MjModel, mujoco.MjData]] = {}
_STATE_MUTATING_COMMANDS = {
    "observe",
    "navigate_to_object",
    "navigate_to_waypoint",
    "navigate_to_relative_pose",
    "navigate_to_receptacle",
    "frame_comparison_object",
    "pick",
    "open_receptacle",
    "close_receptacle",
    "place",
    "place_inside",
}
type _WorkerCommandHandler = molmospaces_worker_protocol.WorkerCommandHandler


def main(argv: list[str] | None = None) -> None:
    args = _parse_args(argv)
    if args.command == "serve":
        serve(args.state_path)
        return
    if args.command == "init":
        result = _init_command(args)
    else:
        result = _run_worker_command(args.state_path, args.command, _cli_command_kwargs(args))
    print(json.dumps(result, sort_keys=True))


def _parse_args(argv: list[str] | None) -> argparse.Namespace:
    return molmospaces_worker_cli.build_arg_parser(
        default_render_width=DEFAULT_RENDER_WIDTH,
        default_render_height=DEFAULT_RENDER_HEIGHT,
    ).parse_args(argv)


def _init_command(args: argparse.Namespace) -> dict[str, Any]:
    return init_state(
        state_path=args.state_path,
        seed=args.seed,
        scene_source=args.scene_source,
        scene_index=args.scene_index,
        include_robot=args.include_robot,
        robot_name=args.robot_name,
        generated_mess_count=args.generated_mess_count,
        generated_mess_object_ids=tuple(args.generated_mess_object_id or ()),
        generated_mess_manifest_path=args.generated_mess_manifest_path,
    )


def serve(state_path: Path) -> None:
    molmospaces_worker_protocol.serve_worker(
        state_path,
        run_state_command=run_state_command,
        ok=_ok,
    )


def run_state_command(
    state_path: Path,
    command: str,
    kwargs: dict[str, Any],
) -> dict[str, Any]:
    return _run_worker_command(state_path, command, kwargs)


def _run_worker_command(
    state_path: Path,
    command: str,
    kwargs: dict[str, Any],
) -> dict[str, Any]:
    return molmospaces_worker_protocol.run_worker_command(
        state_path,
        command,
        kwargs,
        read_state=_read_state,
        write_state=_write_state,
        run_loaded_state_command=_run_loaded_state_command,
    )


def _run_loaded_state_command(
    state: dict[str, Any],
    command: str,
    kwargs: dict[str, Any],
) -> tuple[dict[str, Any], bool]:
    return molmospaces_worker_protocol.run_loaded_state_command(
        state,
        command,
        kwargs,
        handlers=_WORKER_COMMAND_HANDLERS,
        mutating_commands=_STATE_MUTATING_COMMANDS,
    )


def _cli_command_kwargs(args: argparse.Namespace) -> dict[str, Any]:
    return molmospaces_worker_protocol.cli_command_kwargs(args)


def _snapshot_command(state: dict[str, Any], kwargs: dict[str, Any]) -> dict[str, Any]:
    return write_snapshot(
        state,
        Path(str(kwargs["output_path"])),
        str(kwargs.get("title") or ""),
        width=_positive_int(
            kwargs.get("render_width"),
            DEFAULT_RENDER_WIDTH,
            setting_name="render_width",
        ),
        height=_positive_int(
            kwargs.get("render_height"),
            DEFAULT_RENDER_HEIGHT,
            setting_name="render_height",
        ),
    )


def _robot_views_command(state: dict[str, Any], kwargs: dict[str, Any]) -> dict[str, Any]:
    return write_robot_views(
        state,
        Path(str(kwargs["output_dir"])),
        str(kwargs["label"]),
        focus_object_id=_optional_str(kwargs.get("focus_object_id")),
        focus_receptacle_id=_optional_str(kwargs.get("focus_receptacle_id")),
        camera_yaw_offset_deg=_float_or_zero(
            kwargs.get("camera_yaw_offset_deg"),
            setting_name="camera_yaw_offset_deg",
        ),
        camera_pitch_offset_deg=_float_or_zero(
            kwargs.get("camera_pitch_offset_deg"),
            setting_name="camera_pitch_offset_deg",
        ),
        width=_positive_int(
            kwargs.get("render_width"),
            DEFAULT_RENDER_WIDTH,
            setting_name="render_width",
        ),
        height=_positive_int(
            kwargs.get("render_height"),
            DEFAULT_RENDER_HEIGHT,
            setting_name="render_height",
        ),
    )


def _camera_views_command(state: dict[str, Any], kwargs: dict[str, Any]) -> dict[str, Any]:
    width = _positive_int(
        kwargs.get("render_width"),
        DEFAULT_RENDER_WIDTH,
        setting_name="render_width",
    )
    height = _positive_int(
        kwargs.get("render_height"),
        DEFAULT_RENDER_HEIGHT,
        setting_name="render_height",
    )
    camera_request = _load_camera_request_from_kwargs(kwargs, width=width, height=height)
    return write_camera_views(
        state,
        Path(str(kwargs["output_dir"])),
        camera_request,
        width=width,
        height=height,
    )


def _observe_command(state: dict[str, Any], kwargs: dict[str, Any]) -> dict[str, Any]:
    del kwargs
    return observe(state)


def _locations_command(state: dict[str, Any], kwargs: dict[str, Any]) -> dict[str, Any]:
    del kwargs
    return _ok("locations", final_locations=_read_locations(state))


def _navigate_to_object_command(state: dict[str, Any], kwargs: dict[str, Any]) -> dict[str, Any]:
    return navigate_to_object(state, str(kwargs["object_id"]))


def _navigate_to_waypoint_command(state: dict[str, Any], kwargs: dict[str, Any]) -> dict[str, Any]:
    return navigate_to_waypoint(state, _json_object_from_text(str(kwargs["waypoint_json"])))


def _navigate_to_relative_pose_command(
    state: dict[str, Any],
    kwargs: dict[str, Any],
) -> dict[str, Any]:
    return navigate_to_relative_pose(
        state,
        forward_m=_float_or_zero(kwargs.get("forward_m"), setting_name="forward_m"),
        lateral_m=_float_or_zero(kwargs.get("lateral_m"), setting_name="lateral_m"),
        yaw_delta_deg=_float_or_zero(kwargs.get("yaw_delta_deg"), setting_name="yaw_delta_deg"),
    )


def _navigate_to_receptacle_command(
    state: dict[str, Any],
    kwargs: dict[str, Any],
) -> dict[str, Any]:
    return navigate_to_receptacle(state, str(kwargs["receptacle_id"]))


def _frame_comparison_object_command(
    state: dict[str, Any],
    kwargs: dict[str, Any],
) -> dict[str, Any]:
    return frame_comparison_object(state, str(kwargs["object_id"]))


def _pick_command(state: dict[str, Any], kwargs: dict[str, Any]) -> dict[str, Any]:
    return pick_object(state, str(kwargs["object_id"]))


def _open_receptacle_command(state: dict[str, Any], kwargs: dict[str, Any]) -> dict[str, Any]:
    return open_receptacle(state, str(kwargs["receptacle_id"]))


def _close_receptacle_command(state: dict[str, Any], kwargs: dict[str, Any]) -> dict[str, Any]:
    return close_receptacle(state, str(kwargs["receptacle_id"]))


def _place_command(state: dict[str, Any], kwargs: dict[str, Any]) -> dict[str, Any]:
    return place_object(state, str(kwargs["receptacle_id"]))


def _place_inside_command(state: dict[str, Any], kwargs: dict[str, Any]) -> dict[str, Any]:
    return place_inside_object(state, str(kwargs["receptacle_id"]))


def _done_command(state: dict[str, Any], kwargs: dict[str, Any]) -> dict[str, Any]:
    return done_cleanup(state, str(kwargs.get("reason") or ""))


_WORKER_COMMAND_HANDLERS: dict[str, _WorkerCommandHandler] = {
    "observe": _observe_command,
    "locations": _locations_command,
    "snapshot": _snapshot_command,
    "robot_views": _robot_views_command,
    "camera_views": _camera_views_command,
    "navigate_to_object": _navigate_to_object_command,
    "navigate_to_waypoint": _navigate_to_waypoint_command,
    "navigate_to_relative_pose": _navigate_to_relative_pose_command,
    "navigate_to_receptacle": _navigate_to_receptacle_command,
    "frame_comparison_object": _frame_comparison_object_command,
    "pick": _pick_command,
    "open_receptacle": _open_receptacle_command,
    "close_receptacle": _close_receptacle_command,
    "place": _place_command,
    "place_inside": _place_inside_command,
    "done": _done_command,
}


def _load_generated_mess_manifest(path: Path | None) -> dict[str, Any]:
    return molmospaces_worker_init.load_generated_mess_manifest(path)


def _source_room_labels(scene_xml: Path) -> dict[str, dict[str, str]]:
    return molmospaces_worker_init.source_room_labels(scene_xml)


def init_state(
    *,
    state_path: Path,
    seed: int,
    scene_source: str,
    scene_index: int,
    include_robot: bool = False,
    robot_name: str = "rby1m",
    generated_mess_count: int = 5,
    generated_mess_object_ids: tuple[str, ...] = (),
    generated_mess_manifest_path: Path | None = None,
) -> dict[str, Any]:
    return molmospaces_worker_state.init_state(
        state_path=state_path,
        seed=seed,
        scene_source=scene_source,
        scene_index=scene_index,
        include_robot=include_robot,
        robot_name=robot_name,
        generated_mess_count=generated_mess_count,
        generated_mess_object_ids=generated_mess_object_ids,
        generated_mess_manifest_path=generated_mess_manifest_path,
        hooks=_molmo_init_hooks(),
    )


def observe(state: dict[str, Any]) -> dict[str, Any]:
    _count(state, "observe")
    state["scenario_public"] = _public_scenario(state)
    return _ok(
        "observe",
        backend=BACKEND,
        scenario=state["scenario_public"],
        current_receptacle_id=state.get("current_receptacle_id"),
        held_object_id=state.get("held_object_id"),
        inventory_source="molmospaces_metadata+mujoco_state",
        metadata_object_count=state["metadata_object_count"],
    )


def _prepare_molmospaces_scene(
    *,
    scene_source: str,
    scene_index: int,
    get_scenes: Callable[..., Any],
    get_scenes_root: Callable[[], Any],
    install_scene_with_objects_and_grasps_from_path: Callable[[Path], Any],
) -> tuple[Path, dict[str, Any]]:
    return molmospaces_worker_init.prepare_molmospaces_scene(
        scene_source=scene_source,
        scene_index=scene_index,
        get_scenes=get_scenes,
        get_scenes_root=get_scenes_root,
        install_scene_with_objects_and_grasps_from_path=(
            install_scene_with_objects_and_grasps_from_path
        ),
    )


def _resolve_molmospaces_scene_xml(
    *,
    scene_source: str,
    scene_index: int,
    get_scenes: Callable[..., Any],
    scenes_root: Path,
) -> tuple[Path, dict[str, Any]]:
    return molmospaces_worker_init.resolve_molmospaces_scene_xml(
        scene_source=scene_source,
        scene_index=scene_index,
        get_scenes=get_scenes,
        scenes_root=scenes_root,
    )


def _scene_xml_path_from_ref(
    raw_ref: Any,
    *,
    scenes_root: Path,
) -> tuple[Path | None, str, bool]:
    return molmospaces_worker_init.scene_xml_path_from_ref(raw_ref, scenes_root=scenes_root)


def _scene_ref_candidate_xml_path(
    raw_path: Any,
    *,
    scenes_root: Path,
) -> tuple[Path, bool] | None:
    return molmospaces_worker_init.scene_ref_candidate_xml_path(raw_path, scenes_root=scenes_root)


def _normalize_molmospaces_scene_ref_path(
    raw_path: Any,
    *,
    scenes_root: Path,
) -> tuple[Path, bool]:
    return molmospaces_worker_init.normalize_molmospaces_scene_ref_path(
        raw_path, scenes_root=scenes_root
    )


def _scenario_id(*, scene_source: str, scene_index: int, seed: int) -> str:
    return molmospaces_worker_init.scenario_id(
        scene_source=scene_source, scene_index=scene_index, seed=seed
    )


def _molmo_worker_output_hooks() -> molmospaces_worker_outputs.MolmoWorkerOutputHooks:
    return molmospaces_worker_outputs.MolmoWorkerOutputHooks(
        apply_qpos=_apply_qpos,
        apply_robot_view_camera_offset=_apply_robot_view_camera_offset,
        annotate_focus_image=_annotate_focus_image,
        annotate_focus_visual_grounding=_annotate_focus_visual_grounding,
        camera_from_view_spec=_camera_from_view_spec,
        camera_request_provenance=_camera_request_provenance,
        camera_request_variant=_camera_request_variant,
        camera_view_spec=_camera_view_spec,
        count=_count,
        error=_error,
        fixed_camera_diagnostics=_fixed_camera_diagnostics,
        focus_camera=_focus_camera,
        focus_payload=_focus_payload,
        focus_visibility=_focus_visibility,
        free_camera_diagnostics=_free_camera_diagnostics,
        load_model_data_for_state=_load_model_data_for_state,
        ok=_ok,
        refresh_object_positions=_refresh_object_positions,
        render_camera_views_with_model_data=_render_camera_views_with_model_data,
        render_dimensions=_render_dimensions,
        render_fixed_camera=_render_fixed_camera,
        render_free_camera=_render_free_camera,
        render_robot_map=_render_robot_map,
        should_use_fpv_as_verify_focus=_should_use_fpv_as_verify_focus,
        backend=BACKEND,
    )


def _molmo_action_hooks() -> molmospaces_actions.MolmoActionHooks:
    return molmospaces_actions.MolmoActionHooks(
        api_semantic_provenance=API_SEMANTIC_PROVENANCE,
        backend=BACKEND,
        held_location_id=molmospaces_scenario_state.HELD_LOCATION_ID,
        apply_qpos=_apply_qpos,
        close_receptacle_state_mutation=_close_receptacle_state_mutation,
        count=_count,
        error=_error,
        held_object_position=_held_object_position,
        load_model_data_for_state=_load_model_data_for_state,
        ok=_ok,
        open_receptacle_state_mutation=_open_receptacle_state_mutation,
        openable_receptacle_joints=_openable_receptacle_joints,
        placement_diagnostic=_placement_diagnostic,
        read_containment=_read_containment,
        read_locations=_read_locations,
        receptacle_requires_open=_receptacle_requires_open,
        refresh_object_positions=_refresh_object_positions,
        resolve_placement=_resolve_placement,
        robot_pose_for_open_receptacle=_robot_pose_for_open_receptacle,
        robot_pose_for_waypoint=_robot_pose_for_waypoint,
        robot_pose_near_object=_robot_pose_near_object,
        robot_pose_near_receptacle=_robot_pose_near_receptacle,
        robot_pose_state_mutation=_robot_pose_state_mutation,
        score=_score,
        set_free_body_position=_set_free_body_position,
        set_joint_qpos=_set_joint_qpos,
        set_robot_pose=_set_robot_pose,
        sync_held_object_to_robot_pose=_sync_held_object_to_robot_pose,
        waypoint_target_position=_waypoint_target_position,
    )


def write_snapshot(
    state: dict[str, Any],
    output_path: Path,
    title: str,
    *,
    width: int = DEFAULT_RENDER_WIDTH,
    height: int = DEFAULT_RENDER_HEIGHT,
) -> dict[str, Any]:
    return molmospaces_worker_outputs.write_snapshot(
        state,
        output_path,
        title,
        width=width,
        height=height,
        hooks=_molmo_worker_output_hooks(),
    )


def write_robot_views(
    state: dict[str, Any],
    output_dir: Path,
    label: str,
    *,
    focus_object_id: str | None = None,
    focus_receptacle_id: str | None = None,
    camera_yaw_offset_deg: float = 0.0,
    camera_pitch_offset_deg: float = 0.0,
    width: int = DEFAULT_RENDER_WIDTH,
    height: int = DEFAULT_RENDER_HEIGHT,
) -> dict[str, Any]:
    result = molmospaces_worker_outputs.write_robot_views(
        state,
        output_dir,
        label,
        focus_object_id=focus_object_id,
        focus_receptacle_id=focus_receptacle_id,
        camera_yaw_offset_deg=camera_yaw_offset_deg,
        camera_pitch_offset_deg=camera_pitch_offset_deg,
        width=width,
        height=height,
        hooks=_molmo_worker_output_hooks(),
    )
    if result.get("ok") and state.get("objects"):
        fpv_path = Path(str((result.get("views") or {}).get("fpv") or ""))
        if fpv_path:
            bindings_path = fpv_path.with_suffix(".bindings.private.json")
            bindings_path.write_text(
                json.dumps(
                    _raw_fpv_private_bindings(
                        state,
                        camera_yaw_offset_deg=camera_yaw_offset_deg,
                        camera_pitch_offset_deg=camera_pitch_offset_deg,
                        width=width,
                        height=height,
                    ),
                    indent=2,
                    sort_keys=True,
                )
                + "\n",
                encoding="utf-8",
            )
    return result


def _raw_fpv_private_bindings(
    state: dict[str, Any],
    *,
    camera_yaw_offset_deg: float,
    camera_pitch_offset_deg: float,
    width: int,
    height: int,
) -> dict[str, Any]:
    width, height = _render_dimensions(width, height)
    model, data = _load_model_data_for_state(state)
    _apply_qpos(data, state["qpos"])
    _apply_robot_view_camera_offset(
        model,
        data,
        yaw_offset_deg=camera_yaw_offset_deg,
        pitch_offset_deg=camera_pitch_offset_deg,
    )
    mujoco.mj_forward(model, data)
    segmentation = _render_segmentation(
        model,
        data,
        "robot_0/head_camera",
        width=width,
        height=height,
    )
    locations = _read_locations(state)
    bindings = []
    for object_id, obj in state.get("objects", {}).items():
        if not bool(obj.get("pickupable", True)) or object_id == state.get("held_object_id"):
            continue
        box = _segmentation_box(
            model,
            segmentation,
            str(obj.get("body_name") or object_id),
            label=str(obj.get("category") or object_id),
            color=[239, 68, 68],
        )
        if box is None or int(box.get("pixels") or 0) <= 0:
            continue
        left, top, right, bottom = [int(value) for value in box["bbox"]]
        bindings.append(
            {
                "object_id": str(object_id),
                "name": str(obj.get("name") or obj.get("category") or "object"),
                "category": str(obj.get("category") or "object"),
                "location_id": str(locations.get(object_id) or ""),
                "bbox": [left, top, right - left + 1, bottom - top + 1],
                "object_pixels": int(box["pixels"]),
            }
        )
    return {
        "schema": "raw_fpv_private_bindings_v1",
        "image_dimensions": {"width": width, "height": height},
        "bindings": bindings,
    }


def _robot_view_camera_adjustment(
    *,
    camera_yaw_offset_deg: float = 0.0,
    camera_pitch_offset_deg: float = 0.0,
    applied_joints: list[str] | None = None,
    unavailable_reason: str | None = None,
) -> dict[str, Any]:
    return molmospaces_worker_outputs.robot_view_camera_adjustment(
        camera_yaw_offset_deg=camera_yaw_offset_deg,
        camera_pitch_offset_deg=camera_pitch_offset_deg,
        applied_joints=applied_joints,
        unavailable_reason=unavailable_reason,
    )


def write_camera_views(
    state: dict[str, Any],
    output_dir: Path,
    camera_request: dict[str, Any] | list[dict[str, Any]],
    *,
    width: int = DEFAULT_RENDER_WIDTH,
    height: int = DEFAULT_RENDER_HEIGHT,
) -> dict[str, Any]:
    return molmospaces_worker_outputs.write_camera_views(
        state,
        output_dir,
        camera_request,
        width=width,
        height=height,
        hooks=_molmo_worker_output_hooks(),
    )


def _render_camera_views_with_model_data(
    model: mujoco.MjModel,
    data: mujoco.MjData,
    *,
    state: dict[str, Any],
    output_dir: Path,
    camera_request: dict[str, Any] | list[dict[str, Any]],
    width: int,
    height: int,
) -> dict[str, Any]:
    return molmospaces_worker_outputs.render_camera_views_with_model_data(
        model,
        data,
        state=state,
        output_dir=output_dir,
        camera_request=camera_request,
        width=width,
        height=height,
        hooks=_molmo_worker_output_hooks(),
    )


def navigate_to_receptacle(state: dict[str, Any], receptacle_id: str) -> dict[str, Any]:
    return molmospaces_actions.navigate_to_receptacle(
        state, receptacle_id, hooks=_molmo_action_hooks()
    )


def _navigate_to_receptacle(
    state: dict[str, Any],
    receptacle_id: str,
    *,
    tool: str,
) -> dict[str, Any]:
    return molmospaces_actions.navigate_to_receptacle_core(
        state,
        receptacle_id,
        tool=tool,
        hooks=_molmo_action_hooks(),
    )


def navigate_to_object(state: dict[str, Any], object_id: str) -> dict[str, Any]:
    return molmospaces_actions.navigate_to_object(state, object_id, hooks=_molmo_action_hooks())


def navigate_to_waypoint(state: dict[str, Any], waypoint: dict[str, Any]) -> dict[str, Any]:
    return molmospaces_actions.navigate_to_waypoint(state, waypoint, hooks=_molmo_action_hooks())


def navigate_to_relative_pose(
    state: dict[str, Any],
    *,
    forward_m: float = 0.0,
    lateral_m: float = 0.0,
    yaw_delta_deg: float = 0.0,
) -> dict[str, Any]:
    return molmospaces_actions.navigate_to_relative_pose(
        state,
        forward_m=forward_m,
        lateral_m=lateral_m,
        yaw_delta_deg=yaw_delta_deg,
        hooks=_molmo_action_hooks(),
    )


def frame_comparison_object(state: dict[str, Any], object_id: str) -> dict[str, Any]:
    return molmospaces_actions.frame_comparison_object(
        state, object_id, hooks=_molmo_action_hooks()
    )


def pick_object(state: dict[str, Any], object_id: str) -> dict[str, Any]:
    return molmospaces_actions.pick_object(state, object_id, hooks=_molmo_action_hooks())


def place_object(state: dict[str, Any], receptacle_id: str) -> dict[str, Any]:
    return molmospaces_actions.place_object(state, receptacle_id, hooks=_molmo_action_hooks())


def place_inside_object(state: dict[str, Any], receptacle_id: str) -> dict[str, Any]:
    return molmospaces_actions.place_inside_object(
        state, receptacle_id, hooks=_molmo_action_hooks()
    )


def _place_object_at_receptacle(
    state: dict[str, Any],
    receptacle_id: str,
    *,
    tool: str,
    relation: str,
) -> dict[str, Any]:
    return molmospaces_actions.place_object_at_receptacle(
        state,
        receptacle_id,
        tool=tool,
        relation=relation,
        hooks=_molmo_action_hooks(),
    )


def open_receptacle(state: dict[str, Any], receptacle_id: str) -> dict[str, Any]:
    return molmospaces_actions.open_receptacle(state, receptacle_id, hooks=_molmo_action_hooks())


def close_receptacle(state: dict[str, Any], receptacle_id: str) -> dict[str, Any]:
    return molmospaces_actions.close_receptacle(state, receptacle_id, hooks=_molmo_action_hooks())


def _robot_pose_state_mutation(held_object_changed: bool) -> str:
    return molmospaces_actions.robot_pose_state_mutation(held_object_changed)


def _open_receptacle_state_mutation(
    joints_changed: bool,
    robot_pose_changed: bool,
    held_object_changed: bool,
) -> str:
    return molmospaces_actions.open_receptacle_state_mutation(
        joints_changed,
        robot_pose_changed,
        held_object_changed,
    )


def _close_receptacle_state_mutation(
    joints_changed: bool,
    held_object_changed: bool,
) -> str:
    return molmospaces_actions.close_receptacle_state_mutation(joints_changed, held_object_changed)


def done_cleanup(state: dict[str, Any], reason: str) -> dict[str, Any]:
    return molmospaces_actions.done_cleanup(state, reason, hooks=_molmo_action_hooks())


def _collect_dynamic_objects(
    model: mujoco.MjModel,
    data: mujoco.MjData,
    metadata: dict[str, Any],
) -> list[dict[str, Any]]:
    return molmospaces_scenario_state.collect_dynamic_objects(
        model, data, metadata, hooks=_molmo_scenario_hooks()
    )


def _collect_receptacles(
    model: mujoco.MjModel,
    data: mujoco.MjData,
    metadata: dict[str, Any],
) -> list[dict[str, Any]]:
    return molmospaces_scenario_state.collect_receptacles(
        model, data, metadata, hooks=_molmo_scenario_hooks()
    )


def _seed_misplaced_objects(
    model: mujoco.MjModel,
    data: mujoco.MjData,
    state: dict[str, Any],
    targets: list[dict[str, Any]],
) -> None:
    molmospaces_scenario_state.seed_misplaced_objects(
        model, data, state, targets, hooks=_molmo_scenario_hooks()
    )


def _manifest_target_by_object_id(state: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return molmospaces_scenario_state.manifest_target_by_object_id(state)


def _target_receptacle_id(
    target: dict[str, Any],
    manifest_target: dict[str, Any] | None,
) -> str:
    return molmospaces_scenario_state.target_receptacle_id(target, manifest_target)


def _target_start_receptacle(
    state: dict[str, Any],
    target: dict[str, Any],
    wrong_pool: list[dict[str, Any]],
    index: int,
    manifest_target: dict[str, Any] | None,
) -> dict[str, Any]:
    return molmospaces_scenario_state.target_start_receptacle(
        state, target, wrong_pool, index, manifest_target
    )


def _target_start_receptacle_id(state: dict[str, Any], target: dict[str, Any]) -> str:
    return molmospaces_scenario_state.target_start_receptacle_id(state, target)


def _target_relation(
    receptacle: dict[str, Any],
    manifest_target: dict[str, Any] | None,
) -> str:
    return molmospaces_scenario_state.target_relation(
        receptacle, manifest_target, hooks=_molmo_scenario_hooks()
    )


def _target_placement_index(index: int, manifest_target: dict[str, Any] | None) -> int:
    return molmospaces_scenario_state.target_placement_index(index, manifest_target)


def _public_scenario(state: dict[str, Any]) -> dict[str, Any]:
    return molmospaces_scenario_state.public_scenario(
        state, read_locations=_read_locations, backend=BACKEND
    )


def _read_locations(state: dict[str, Any]) -> dict[str, str]:
    return molmospaces_scenario_state.read_locations(state, hooks=_molmo_scenario_hooks())


def _read_containment(state: dict[str, Any]) -> dict[str, dict[str, str]]:
    return molmospaces_scenario_state.read_containment(state)


def _score(final_locations: dict[str, str], manifest: dict[str, Any]) -> dict[str, Any]:
    return molmospaces_scenario_state.score(final_locations, manifest)


def _nearest_receptacle(position: list[float], receptacles: list[dict[str, Any]]) -> str:
    return molmospaces_scenario_state.nearest_receptacle(position, receptacles)


def _first_wrong_receptacle(state: dict[str, Any], target: dict[str, Any]) -> str:
    return molmospaces_scenario_state.first_wrong_receptacle(state, target)


def _first_receptacle_id(state: dict[str, Any]) -> str | None:
    return molmospaces_scenario_state.first_receptacle_id(state)


def _set_free_body_position(
    model: mujoco.MjModel,
    data: mujoco.MjData,
    body_name: str,
    position: list[float],
) -> None:
    molmospaces_runtime_state.set_free_body_position(model, data, body_name, position)


def _refresh_object_positions(
    model: mujoco.MjModel,
    data: mujoco.MjData,
    state: dict[str, Any],
) -> None:
    molmospaces_runtime_state.refresh_object_positions(model, data, state, xyz=_xyz)


def _refresh_runtime_render_state(state: dict[str, Any]) -> None:
    molmospaces_runtime_state.refresh_runtime_render_state(
        state,
        load_model_data_for_state=_load_model_data_for_state,
        apply_qpos=_apply_qpos,
        runtime_render_state=_runtime_render_state,
    )


def _runtime_render_state(
    model: mujoco.MjModel,
    data: mujoco.MjData,
    state: dict[str, Any],
) -> dict[str, Any]:
    return molmospaces_runtime_state.runtime_render_state(
        model,
        data,
        state,
        runtime_subtree_joints=_runtime_subtree_joints,
        xyz=_xyz,
    )


def _runtime_subtree_joints(
    model: mujoco.MjModel,
    data: mujoco.MjData,
    body_name: str,
    *,
    exclude_root_freejoint: bool,
) -> list[dict[str, Any]]:
    return molmospaces_runtime_state.runtime_subtree_joints(
        model,
        data,
        body_name,
        exclude_root_freejoint=exclude_root_freejoint,
        subtree_body_ids=_subtree_body_ids,
        joint_qpos_width=_joint_qpos_width,
        joint_type_name=_joint_type_name,
    )


def _joint_qpos_width(model: mujoco.MjModel, joint_id: int) -> int:
    return molmospaces_runtime_state.joint_qpos_width(model, joint_id)


def _joint_type_name(model: mujoco.MjModel, joint_id: int) -> str:
    return molmospaces_runtime_state.joint_type_name(model, joint_id)


def _molmo_placement_hooks() -> molmospaces_placement.MolmoPlacementHooks:
    return molmospaces_placement.MolmoPlacementHooks(
        subtree_geom_ids=_subtree_geom_ids,
        xyz=_xyz,
    )


def _molmo_scenario_hooks() -> molmospaces_scenario_state.MolmoScenarioHooks:
    return molmospaces_scenario_state.MolmoScenarioHooks(
        primary_body_name=_primary_body_name,
        friendly_name=_friendly_name,
        xyz=_xyz,
        receptacle_support_surfaces=_receptacle_support_surfaces,
        support_top_z=_support_top_z,
        receptacle_requires_open=_receptacle_requires_open,
        receptacle_prefers_inside=_receptacle_prefers_inside,
        resolve_placement=_resolve_placement,
        set_free_body_position=_set_free_body_position,
        refresh_object_positions=_refresh_object_positions,
        placement_diagnostic=_placement_diagnostic,
        load_model_data_for_state=_load_model_data_for_state,
        apply_qpos=_apply_qpos,
    )


def _molmo_init_hooks() -> molmospaces_worker_state.MolmoInitHooks:
    return molmospaces_worker_state.MolmoInitHooks(
        backend=BACKEND,
        collect_dynamic_objects=_collect_dynamic_objects,
        collect_receptacles=_collect_receptacles,
        collect_room_outlines=_collect_room_outlines,
        first_receptacle_id=_first_receptacle_id,
        load_generated_mess_manifest=_load_generated_mess_manifest,
        load_model_data=_load_model_data,
        load_robot_model_data=_load_robot_model_data,
        ok=_ok,
        prepare_molmospaces_scene=_prepare_molmospaces_scene,
        public_scenario=_public_scenario,
        refresh_object_positions=_refresh_object_positions,
        robot_camera_names=_robot_camera_names,
        robot_pose_near_receptacle=_robot_pose_near_receptacle,
        robot_result_payload=_robot_result_payload,
        robot_xml_name=_robot_xml_name,
        scenario_id=_scenario_id,
        seed_misplaced_objects=_seed_misplaced_objects,
        set_robot_pose=_set_robot_pose,
        source_room_labels=_source_room_labels,
        target_start_receptacle_id=_target_start_receptacle_id,
        write_state=_write_state,
    )


def _resolve_placement(
    model: mujoco.MjModel,
    data: mujoco.MjData,
    *,
    state: dict[str, Any],
    object_id: str,
    receptacle_id: str,
    index: int,
    relation: str,
) -> dict[str, Any]:
    return molmospaces_placement.resolve_placement(
        model,
        data,
        state=state,
        object_id=object_id,
        receptacle_id=receptacle_id,
        index=index,
        relation=relation,
        hooks=_molmo_placement_hooks(),
    )


def _direct_support_placement(
    model: mujoco.MjModel,
    data: mujoco.MjData,
    state: dict[str, Any],
    obj: dict[str, Any],
    receptacle: dict[str, Any],
    *,
    index: int,
) -> dict[str, Any] | None:
    return molmospaces_placement.direct_support_placement(
        model,
        data,
        state,
        obj,
        receptacle,
        index=index,
        hooks=_molmo_placement_hooks(),
    )


def _surface_candidate_positions(
    surface: dict[str, Any],
    *,
    footprint: tuple[float, float],
    bottom_offset: float,
    clearance: float,
    index: int,
) -> list[list[float]]:
    return molmospaces_placement.surface_candidate_positions(
        surface,
        footprint=footprint,
        bottom_offset=bottom_offset,
        clearance=clearance,
        index=index,
    )


def _candidate_has_direct_support(
    position: list[float],
    surface: dict[str, Any],
    footprint: tuple[float, float],
) -> bool:
    return molmospaces_placement.candidate_has_direct_support(position, surface, footprint)


def _candidate_is_clear_of_dynamic_objects(
    model: mujoco.MjModel,
    data: mujoco.MjData,
    state: dict[str, Any],
    obj: dict[str, Any],
    position: list[float],
    *,
    footprint: tuple[float, float],
    bottom_offset: float,
) -> bool:
    return molmospaces_placement.candidate_is_clear_of_dynamic_objects(
        model,
        data,
        state,
        obj,
        position,
        footprint=footprint,
        bottom_offset=bottom_offset,
        hooks=_molmo_placement_hooks(),
    )


def _elevated_position_over_surface(
    surface: dict[str, Any],
    *,
    bottom_offset: float,
) -> list[float]:
    return molmospaces_placement.elevated_position_over_surface(
        surface, bottom_offset=bottom_offset
    )


def _placement_position(
    receptacle: dict[str, Any],
    *,
    index: int,
    relation: str = "on",
    object_category: str | None = None,
) -> list[float]:
    return molmospaces_placement.placement_position(
        receptacle,
        index=index,
        relation=relation,
        object_category=object_category,
    )


def _object_surface_lift(object_category: str | None) -> float:
    return molmospaces_placement.object_surface_lift(object_category)


def _direct_support_clearance(obj: dict[str, Any], receptacle: dict[str, Any]) -> float:
    return molmospaces_placement.direct_support_clearance(obj, receptacle)


def _receptacle_support_surfaces(
    model: mujoco.MjModel,
    data: mujoco.MjData,
    body_name: str,
) -> list[dict[str, Any]]:
    return molmospaces_placement.receptacle_support_surfaces(
        model,
        data,
        body_name,
        hooks=_molmo_placement_hooks(),
    )


def _support_surface_from_geom(
    model: mujoco.MjModel,
    data: mujoco.MjData,
    geom_id: int,
) -> dict[str, Any] | None:
    return molmospaces_placement.support_surface_from_geom(
        model,
        data,
        geom_id,
        hooks=_molmo_placement_hooks(),
    )


def _geom_has_upward_support_normal(data: mujoco.MjData, geom_id: int) -> bool:
    return molmospaces_placement.geom_has_upward_support_normal(data, geom_id)


def _geom_world_half_extents(
    model: mujoco.MjModel,
    data: mujoco.MjData,
    geom_id: int,
) -> tuple[float, float, float] | None:
    return molmospaces_placement.geom_world_half_extents(model, data, geom_id)


def _oriented_half_extents(
    xmat: Any,
    local: tuple[float, float, float],
) -> tuple[float, float, float]:
    return molmospaces_placement.oriented_half_extents(xmat, local)


def _support_top_z(surfaces: list[dict[str, Any]]) -> float | None:
    return molmospaces_placement.support_top_z(surfaces)


def _object_bottom_offset(
    model: mujoco.MjModel,
    data: mujoco.MjData,
    obj: dict[str, Any],
) -> float:
    return molmospaces_placement.object_bottom_offset(
        model, data, obj, hooks=_molmo_placement_hooks()
    )


def _object_height(
    model: mujoco.MjModel,
    data: mujoco.MjData,
    obj: dict[str, Any],
) -> float:
    return molmospaces_placement.object_height(model, data, obj, hooks=_molmo_placement_hooks())


def _object_world_aabb(
    model: mujoco.MjModel,
    data: mujoco.MjData,
    obj: dict[str, Any],
) -> dict[str, float] | None:
    return molmospaces_placement.object_world_aabb(model, data, obj, hooks=_molmo_placement_hooks())


def _aabb_xy_overlaps(
    first: tuple[float, float, float, float],
    second: dict[str, float],
    *,
    margin: float,
) -> bool:
    return molmospaces_placement.aabb_xy_overlaps(first, second, margin=margin)


def _object_footprint_half_extents(
    model: mujoco.MjModel,
    data: mujoco.MjData,
    obj: dict[str, Any],
) -> tuple[float, float]:
    return molmospaces_placement.object_footprint_half_extents(
        model, data, obj, hooks=_molmo_placement_hooks()
    )


def _receptacle_requires_open(receptacle: dict[str, Any]) -> bool:
    return molmospaces_placement.receptacle_requires_open(receptacle)


def _receptacle_prefers_inside(receptacle: dict[str, Any]) -> bool:
    return molmospaces_placement.receptacle_prefers_inside(receptacle)


def _receptacle_is_open_container(receptacle: dict[str, Any]) -> bool:
    return molmospaces_placement.receptacle_is_open_container(receptacle)


def _receptacle_text(receptacle: dict[str, Any]) -> str:
    return molmospaces_placement.receptacle_text(receptacle)


def _placement_diagnostic(
    *,
    state: dict[str, Any],
    object_id: str,
    receptacle_id: str,
    relation: str,
    requested_position: list[float],
    source: str,
    placement_index: int | None = None,
    placement_resolution: dict[str, Any] | None = None,
) -> dict[str, Any]:
    return molmospaces_placement.placement_diagnostic(
        state=state,
        object_id=object_id,
        receptacle_id=receptacle_id,
        relation=relation,
        requested_position=requested_position,
        source=source,
        placement_index=placement_index,
        placement_resolution=placement_resolution,
    )


def _load_model_data(scene_xml: Path) -> tuple[mujoco.MjModel, mujoco.MjData]:
    return molmospaces_runtime_state.load_model_data(scene_xml)


def _load_model_data_for_state(state: dict[str, Any]) -> tuple[mujoco.MjModel, mujoco.MjData]:
    return molmospaces_runtime_state.load_model_data_for_state(
        state,
        model_data_cache=_MODEL_DATA_CACHE,
        load_model_data=_load_model_data,
        load_robot_model_data=_load_robot_model_data,
    )


def _load_robot_model_data(
    scene_xml: Path,
    robot_xml: Path,
) -> tuple[mujoco.MjModel, mujoco.MjData]:
    return molmospaces_runtime_state.load_robot_model_data(
        scene_xml, robot_xml, load_model_data=_load_model_data
    )


def _robot_xml_name(robot_name: str) -> str:
    return molmospaces_runtime_state.robot_xml_name(robot_name)


def _robot_camera_names(model: mujoco.MjModel) -> list[str]:
    return molmospaces_runtime_state.robot_camera_names(model)


def _robot_result_payload(state: dict[str, Any], model: mujoco.MjModel) -> dict[str, Any]:
    return molmospaces_runtime_state.robot_result_payload(
        state, model, robot_camera_names=_robot_camera_names
    )


def _set_robot_pose(
    model: mujoco.MjModel,
    data: mujoco.MjData,
    pose: dict[str, float],
) -> None:
    molmospaces_runtime_state.set_robot_pose(model, data, pose, set_joint_qpos=_set_joint_qpos)


def _apply_robot_view_camera_offset(
    model: mujoco.MjModel,
    data: mujoco.MjData,
    *,
    yaw_offset_deg: float = 0.0,
    pitch_offset_deg: float = 0.0,
) -> dict[str, Any]:
    return molmospaces_runtime_state.apply_robot_view_camera_offset(
        model,
        data,
        yaw_offset_deg=yaw_offset_deg,
        pitch_offset_deg=pitch_offset_deg,
        add_joint_qpos_if_present=_add_joint_qpos_if_present,
        robot_view_camera_adjustment=_robot_view_camera_adjustment,
    )


def _add_joint_qpos_if_present(
    model: mujoco.MjModel,
    data: mujoco.MjData,
    joint_name: str,
    delta: float,
) -> bool:
    return molmospaces_runtime_state.add_joint_qpos_if_present(model, data, joint_name, delta)


def _set_joint_qpos(
    model: mujoco.MjModel,
    data: mujoco.MjData,
    joint_name: str,
    value: float,
) -> None:
    molmospaces_runtime_state.set_joint_qpos(model, data, joint_name, value)


def _sync_held_object_to_robot_pose(
    model: mujoco.MjModel,
    data: mujoco.MjData,
    state: dict[str, Any],
) -> dict[str, Any] | None:
    return molmospaces_runtime_state.sync_held_object_to_robot_pose(
        model,
        data,
        state,
        held_object_position=_held_object_position,
        set_free_body_position=_set_free_body_position,
    )


def _held_object_position(state: dict[str, Any]) -> list[float]:
    return molmospaces_runtime_state.held_object_position(state)


def _openable_receptacle_joints(
    model: mujoco.MjModel,
    body_name: str,
) -> list[dict[str, Any]]:
    return molmospaces_runtime_state.openable_receptacle_joints(
        model, body_name, subtree_body_ids=_subtree_body_ids
    )


def _robot_pose_near_receptacle(
    state: dict[str, Any],
    receptacle: dict[str, Any],
) -> dict[str, Any]:
    return molmospaces_robot_pose.robot_pose_near_receptacle(state, receptacle)


def _robot_pose_for_open_receptacle(
    state: dict[str, Any],
    receptacle: dict[str, Any],
) -> dict[str, Any]:
    return molmospaces_robot_pose.robot_pose_for_open_receptacle(state, receptacle)


def _first_same_room_point(
    state: dict[str, Any],
    candidates: list[tuple[float, float]],
    target_room_id: str | None,
) -> tuple[float, float]:
    return molmospaces_robot_pose.first_same_room_point(state, candidates, target_room_id)


def _robot_pose_near_object(
    state: dict[str, Any],
    obj: dict[str, Any],
    *,
    source_receptacle_id: str | None = None,
) -> dict[str, Any]:
    return molmospaces_robot_pose.robot_pose_near_object(
        state,
        obj,
        source_receptacle_id=source_receptacle_id,
    )


def _robot_pose_for_waypoint(
    state: dict[str, Any],
    waypoint: dict[str, Any],
    target: list[float],
) -> dict[str, Any]:
    return molmospaces_robot_pose.robot_pose_for_waypoint(state, waypoint, target)


def _waypoint_target_position(
    state: dict[str, Any],
    waypoint: dict[str, Any],
) -> list[float]:
    return molmospaces_robot_pose.waypoint_target_position(state, waypoint)


def _room_outline_center_xy(outline: dict[str, Any] | None) -> tuple[float, float] | None:
    return molmospaces_robot_pose.room_outline_center_xy(outline)


def _robot_pose_near_position(
    state: dict[str, Any],
    target: list[float],
    *,
    target_room_id: str | None,
    target_receptacle_id: str | None = None,
    target_object_id: str | None = None,
) -> dict[str, Any]:
    return molmospaces_robot_pose.robot_pose_near_position(
        state,
        target,
        target_room_id=target_room_id,
        target_receptacle_id=target_receptacle_id,
        target_object_id=target_object_id,
    )


def _robot_stand_off_for_target(state: dict[str, Any], target_object_id: str | None) -> float:
    return molmospaces_robot_pose.robot_stand_off_for_target(state, target_object_id)


def _robot_head_pitch_for_target(target: list[float], robot_xy: list[float]) -> float:
    return molmospaces_robot_pose.robot_head_pitch_for_target_value(target, robot_xy)


def _scene_center(items: list[dict[str, Any]]) -> tuple[float, float]:
    return molmospaces_robot_pose.scene_center(items)


def _render_fixed_camera(
    model: mujoco.MjModel,
    data: mujoco.MjData,
    camera_name: str,
    *,
    width: int = DEFAULT_RENDER_WIDTH,
    height: int = DEFAULT_RENDER_HEIGHT,
) -> Any:
    return molmospaces_rendering.render_fixed_camera(
        model,
        data,
        camera_name,
        width=width,
        height=height,
        render_dimensions=_render_dimensions,
        ensure_offscreen_framebuffer=_ensure_offscreen_framebuffer,
    )


def _fixed_camera_diagnostics(
    model: mujoco.MjModel,
    data: mujoco.MjData,
    camera_name: str,
) -> dict[str, Any]:
    return molmospaces_rendering.fixed_camera_diagnostics(model, data, camera_name)


def _free_camera_diagnostics(camera: mujoco.MjvCamera) -> dict[str, Any]:
    return molmospaces_rendering.free_camera_diagnostics(camera)


def _focus_camera(state: dict[str, Any], focus: dict[str, Any]) -> mujoco.MjvCamera:
    return molmospaces_focus_camera.focus_camera(
        state,
        focus,
        scene_focus_position=_scene_focus_position,
        focus_camera_azimuth=_focus_camera_azimuth,
    )


def _render_free_camera(
    model: mujoco.MjModel,
    data: mujoco.MjData,
    camera: mujoco.MjvCamera,
    *,
    width: int = DEFAULT_RENDER_WIDTH,
    height: int = DEFAULT_RENDER_HEIGHT,
) -> Any:
    return molmospaces_rendering.render_free_camera(
        model,
        data,
        camera,
        width=width,
        height=height,
        render_dimensions=_render_dimensions,
        ensure_offscreen_framebuffer=_ensure_offscreen_framebuffer,
    )


def _load_rendered_robot_view_image(camera_views: dict[str, Any], *, role: str) -> Any:
    return molmospaces_rendering.load_rendered_robot_view_image(camera_views, role=role)


def _image_to_array(path: Path) -> Any:
    return molmospaces_rendering.image_to_array(path)


def _load_camera_view_specs(path: Path) -> list[dict[str, Any]]:
    payload = read_json_value(path, label="camera view spec")
    raw_views = payload.get("views") if isinstance(payload, dict) else payload
    if not isinstance(raw_views, list):
        raise ValueError("camera view spec must be a list or an object with a views list")
    return [dict(item) for item in raw_views if isinstance(item, dict)]


def _load_camera_request_from_args(
    *,
    view_specs_path: Path | None,
    camera_request_path: Path | None,
    width: int,
    height: int,
) -> dict[str, Any]:
    if camera_request_path is not None:
        return load_camera_control_request(camera_request_path, width=width, height=height)
    if view_specs_path is not None:
        return normalize_camera_control_request(
            _load_camera_view_specs(view_specs_path),
            width=width,
            height=height,
        )
    raise ValueError("camera_views requires --camera-request-path or --view-specs-path")


def _load_camera_request_from_kwargs(
    kwargs: dict[str, Any],
    *,
    width: int,
    height: int,
) -> dict[str, Any]:
    camera_request_path = kwargs.get("camera_request_path")
    if camera_request_path:
        return load_camera_control_request(
            Path(str(camera_request_path)), width=width, height=height
        )
    view_specs_path = kwargs.get("view_specs_path")
    if view_specs_path:
        return normalize_camera_control_request(
            _load_camera_view_specs(Path(str(view_specs_path))),
            width=width,
            height=height,
        )
    raise ValueError("camera_views requires camera_request_path or view_specs_path")


def _camera_view_spec(raw_spec: dict[str, Any], *, index: int) -> dict[str, Any]:
    return molmospaces_focus_camera.camera_view_spec(raw_spec, index=index)


def _lane_camera_orbit(raw_spec: dict[str, Any], lane_id: str) -> dict[str, Any]:
    return molmospaces_focus_camera.lane_camera_orbit(raw_spec, lane_id)


def _camera_request_variant(camera_request: dict[str, Any]) -> str:
    return molmospaces_worker_outputs.camera_request_variant(camera_request)


def _camera_request_provenance(camera_request: dict[str, Any]) -> str:
    return molmospaces_worker_outputs.camera_request_provenance(camera_request)


def _camera_vec3(value: Any, *, field_name: str = "camera vector") -> list[float]:
    return molmospaces_focus_camera.camera_vec3(value, field_name=field_name)


def _eye_from_mujoco_free_camera(
    *,
    lookat: list[float],
    distance: float,
    azimuth: float,
    elevation: float,
) -> list[float]:
    return molmospaces_focus_camera.eye_from_mujoco_free_camera(
        lookat=lookat,
        distance=distance,
        azimuth=azimuth,
        elevation=elevation,
    )


def _free_camera_from_lookat_spec(spec: dict[str, Any]) -> mujoco.MjvCamera:
    return molmospaces_focus_camera.free_camera_from_lookat_spec(spec)


def _camera_from_view_spec(state: dict[str, Any], spec: dict[str, Any]) -> mujoco.MjvCamera:
    return molmospaces_focus_camera.camera_from_view_spec(
        state,
        spec,
        free_camera_from_lookat_spec=_free_camera_from_lookat_spec,
        focus_payload=_focus_payload,
        focus_camera=_focus_camera,
    )


def _annotate_focus_image(image: Image.Image, focus: dict[str, Any]) -> None:
    molmospaces_focus_camera.annotate_focus_image(image, focus)


def _focus_camera_azimuth(
    state: dict[str, Any],
    focus_position: list[float],
    focus: dict[str, Any] | None = None,
) -> float:
    return molmospaces_focus_camera.default_focus_camera_azimuth(state, focus_position, focus)


def _focus_payload(
    state: dict[str, Any],
    focus_object_id: str | None,
    focus_receptacle_id: str | None,
) -> dict[str, Any]:
    return molmospaces_focus_camera.focus_payload(
        state,
        focus_object_id,
        focus_receptacle_id,
        label_item=_item_label,
        average_position=_average_position,
        scene_focus_position=_scene_focus_position,
    )


def _average_position(positions: list[list[float]]) -> list[float]:
    return molmospaces_focus_camera.default_average_position(positions)


def _scene_focus_position(state: dict[str, Any]) -> list[float]:
    return molmospaces_focus_camera.default_scene_focus_position(state)


def _item_label(item: dict[str, Any] | None, id_key: str) -> str:
    return molmospaces_room_map.item_label(item, id_key)


def _focus_visibility(
    model: mujoco.MjModel,
    data: mujoco.MjData,
    camera: mujoco.MjvCamera | str,
    focus: dict[str, Any],
    *,
    frame: Any | None = None,
) -> dict[str, Any]:
    return molmospaces_rendering.focus_visibility(
        model,
        data,
        camera,
        focus,
        frame=frame,
        render_segmentation=_render_segmentation,
        segmentation_box=_segmentation_box,
        highlight_diff_box=_highlight_diff_box,
        shape_width=_shape_width,
        shape_height=_shape_height,
    )


def _annotate_focus_visual_grounding(focus: dict[str, Any]) -> dict[str, Any]:
    return molmospaces_focus_camera.annotate_focus_visual_grounding(
        focus,
        visual_grounding_status=_visual_grounding_status,
    )


def _should_use_fpv_as_verify_focus(focus: dict[str, Any]) -> bool:
    return molmospaces_focus_camera.should_use_fpv_as_verify_focus(
        focus,
        focus_visibility_is_grounded=_focus_visibility_is_grounded,
    )


def _focus_visibility_is_grounded(
    visibility: dict[str, Any],
    focus: dict[str, Any],
) -> bool:
    return molmospaces_focus_camera.default_focus_visibility_is_grounded(visibility, focus)


def _visual_grounding_status(focus: dict[str, Any], visibility: dict[str, Any]) -> str:
    return molmospaces_focus_camera.default_visual_grounding_status(
        focus,
        visibility,
        can_hide_contents=_focus_receptacle_can_hide_contents,
    )


def _focus_receptacle_can_hide_contents(focus: dict[str, Any]) -> bool:
    return molmospaces_focus_camera.focus_receptacle_can_hide_contents(focus)


def _render_segmentation(
    model: mujoco.MjModel,
    data: mujoco.MjData,
    camera: mujoco.MjvCamera | str,
    *,
    width: int = DEFAULT_RENDER_WIDTH,
    height: int = DEFAULT_RENDER_HEIGHT,
) -> Any:
    return molmospaces_rendering.render_segmentation(
        model,
        data,
        camera,
        width=width,
        height=height,
        render_dimensions=_render_dimensions,
        ensure_offscreen_framebuffer=_ensure_offscreen_framebuffer,
    )


def _segmentation_box(
    model: mujoco.MjModel,
    segmentation: Any,
    body_name: str,
    *,
    label: str,
    color: list[int],
) -> dict[str, Any] | None:
    return molmospaces_rendering.segmentation_box(
        model,
        segmentation,
        body_name,
        label=label,
        color=color,
        subtree_geom_ids=_subtree_geom_ids,
        inflate_bbox=_inflate_bbox,
    )


def _highlight_diff_box(
    model: mujoco.MjModel,
    data: mujoco.MjData,
    camera: mujoco.MjvCamera | str,
    body_name: str,
    *,
    label: str,
    color: list[int],
    frame: Any | None,
) -> dict[str, Any] | None:
    return molmospaces_rendering.highlight_diff_box(
        model,
        data,
        camera,
        body_name,
        label=label,
        color=color,
        frame=frame,
        subtree_geom_ids=_subtree_geom_ids,
        render_color_frame=_render_color_frame,
        shape_width=_shape_width,
        shape_height=_shape_height,
        inflate_bbox=_inflate_bbox,
    )


def _render_color_frame(
    model: mujoco.MjModel,
    data: mujoco.MjData,
    camera: mujoco.MjvCamera | str,
    *,
    width: int = DEFAULT_RENDER_WIDTH,
    height: int = DEFAULT_RENDER_HEIGHT,
) -> Any:
    return molmospaces_rendering.render_color_frame(
        model,
        data,
        camera,
        width=width,
        height=height,
        render_dimensions=_render_dimensions,
        ensure_offscreen_framebuffer=_ensure_offscreen_framebuffer,
    )


def _ensure_offscreen_framebuffer(
    model: mujoco.MjModel,
    *,
    width: int,
    height: int,
) -> None:
    molmospaces_rendering.ensure_offscreen_framebuffer(model, width=width, height=height)


def _subtree_geom_ids(model: mujoco.MjModel, body_name: str) -> list[int]:
    return molmospaces_rendering.subtree_geom_ids(
        model, body_name, subtree_body_ids=_subtree_body_ids
    )


def _subtree_body_ids(model: mujoco.MjModel, body_name: str) -> list[int]:
    return molmospaces_rendering.subtree_body_ids(model, body_name)


def _inflate_bbox(
    left: int,
    top: int,
    right: int,
    bottom: int,
    shape: Any,
    *,
    min_size: int = 32,
    pad: int = 8,
) -> tuple[int, int, int, int]:
    return molmospaces_rendering.inflate_bbox(
        left,
        top,
        right,
        bottom,
        shape,
        min_size=min_size,
        pad=pad,
    )


def _render_robot_map(state: dict[str, Any], *, focus: dict[str, Any] | None = None) -> Image.Image:
    return molmospaces_room_map.render_robot_map(state, focus=focus)


def _map_points(state: dict[str, Any], focus: dict[str, Any]) -> list[list[float]]:
    return molmospaces_room_map.map_points(state, focus)


def _room_relation_payload(
    state: dict[str, Any],
    receptacle: dict[str, Any],
    robot_point: list[float],
) -> dict[str, Any]:
    return molmospaces_robot_pose.room_relation_payload(state, receptacle, robot_point)


def _target_room_id(state: dict[str, Any], receptacle: dict[str, Any]) -> str:
    return molmospaces_robot_pose.target_room_id_for_receptacle(state, receptacle)


def _room_outline_for_id(
    state: dict[str, Any],
    room_id: Any,
) -> dict[str, Any] | None:
    return molmospaces_robot_pose.room_outline_for_id(state, room_id)


def _room_for_point(state: dict[str, Any], point: list[float]) -> str | None:
    return molmospaces_robot_pose.room_for_state_point(state, point)


def _point_inside_outline(
    point: list[float],
    outline: dict[str, Any],
    *,
    margin: float,
) -> bool:
    return molmospaces_robot_pose.point_inside_outline(point, outline, margin=margin)


def _outline_clearance(point: list[float], outline: dict[str, Any] | None) -> float:
    return molmospaces_robot_pose.outline_clearance(point, outline)


def _angle_delta(a: float, b: float) -> float:
    return molmospaces_robot_pose.angle_delta_value(a, b)


def _collect_room_outlines(
    model: mujoco.MjModel,
    data: mujoco.MjData,
    state: dict[str, Any],
) -> list[dict[str, Any]]:
    return molmospaces_room_map.collect_room_outlines(model, data, state, xyz=_xyz)


def _geom_xy_bounds(
    model: mujoco.MjModel,
    data: mujoco.MjData,
    geom_id: int,
) -> tuple[list[float], list[float]] | None:
    return molmospaces_room_map.geom_xy_bounds(model, data, geom_id, xyz=_xyz)


def _fallback_room_outlines(state: dict[str, Any]) -> list[dict[str, Any]]:
    return molmospaces_room_map.fallback_room_outlines(state)


def _map_bounds(points: list[list[float]]) -> tuple[float, float, float, float]:
    return molmospaces_room_map.map_bounds(points)


def _apply_qpos(data: mujoco.MjData, qpos: list[float]) -> None:
    data.qpos[:] = qpos


def _optional_str(value: Any) -> str | None:
    return molmospaces_worker_protocol.optional_str(value)


def _positive_int(value: Any, default: int, *, setting_name: str = "value") -> int:
    return molmospaces_worker_protocol.positive_int(
        value,
        default,
        setting_name=setting_name,
    )


def _float_or_zero(value: Any, *, setting_name: str = "value") -> float:
    return molmospaces_worker_protocol.float_or_zero(value, setting_name=setting_name)


def _json_object_from_text(text: str) -> dict[str, Any]:
    return molmospaces_worker_protocol.json_object_from_text(text)


def _render_dimensions(width: int, height: int) -> tuple[int, int]:
    return molmospaces_rendering.render_dimensions(
        width,
        height,
        default_width=DEFAULT_RENDER_WIDTH,
        default_height=DEFAULT_RENDER_HEIGHT,
    )


def _shape_width(shape: Any) -> int:
    return molmospaces_rendering.shape_width(shape, default_width=DEFAULT_RENDER_WIDTH)


def _shape_height(shape: Any) -> int:
    return molmospaces_rendering.shape_height(shape, default_height=DEFAULT_RENDER_HEIGHT)


def _primary_body_name(info: dict[str, Any], *, fallback: str) -> str:
    bodies = info.get("name_map", {}).get("bodies", {})
    return next(iter(bodies), fallback)


def _friendly_name(category: str, upstream_id: Any) -> str:
    return f"{category} ({upstream_id})"


def _xyz(values: Any) -> list[float]:
    return [round(float(values[0]), 6), round(float(values[1]), 6), round(float(values[2]), 6)]


def _read_state(path: Path) -> dict[str, Any]:
    return molmospaces_worker_protocol.read_state(path)


def _write_state(path: Path, state: dict[str, Any]) -> None:
    molmospaces_worker_protocol.write_state(
        path, state, refresh_runtime_render_state=_refresh_runtime_render_state
    )


def _count(state: dict[str, Any], tool: str) -> None:
    molmospaces_worker_protocol.count_tool_request(state, tool)


def _ok(tool: str, **payload: Any) -> dict[str, Any]:
    return molmospaces_worker_protocol.ok_response(tool, **payload)


def _error(tool: str, error_reason: str, **payload: Any) -> dict[str, Any]:
    return molmospaces_worker_protocol.error_response(tool, error_reason, **payload)


if __name__ == "__main__":
    main()
