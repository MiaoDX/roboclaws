from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Callable

import mujoco

from roboclaws.backends.molmospaces import (
    actions,
    capture,
    initialization,
    protocol,
    scenario_state,
    state,
)
from roboclaws.backends.molmospaces.common import (
    DEFAULT_RENDER_HEIGHT,
    DEFAULT_RENDER_WIDTH,
    _apply_qpos,
    _count,
    _error,
    _ok,
    _render_dimensions,
)
from roboclaws.backends.molmospaces.navigation_runtime import (
    _apply_robot_view_camera_offset,
    _held_object_position,
    _load_model_data,
    _load_model_data_for_state,
    _load_robot_model_data,
    _openable_receptacle_joints,
    _robot_camera_names,
    _robot_pose_for_open_receptacle,
    _robot_pose_for_waypoint,
    _robot_pose_near_object,
    _robot_pose_near_receptacle,
    _robot_result_payload,
    _robot_xml_name,
    _set_free_body_position,
    _set_joint_qpos,
    _set_robot_pose,
    _sync_held_object_to_robot_pose,
    _waypoint_target_position,
)
from roboclaws.backends.molmospaces.perception_runtime import (
    _annotate_focus_image,
    _annotate_focus_visual_grounding,
    _camera_from_view_spec,
    _camera_request_provenance,
    _camera_request_variant,
    _camera_view_spec,
    _collect_room_outlines,
    _fixed_camera_diagnostics,
    _focus_camera,
    _focus_payload,
    _focus_visibility,
    _free_camera_diagnostics,
    _render_fixed_camera,
    _render_free_camera,
    _render_robot_map,
    _render_segmentation,
    _segmentation_box,
    _should_use_fpv_as_verify_focus,
)
from roboclaws.backends.molmospaces.state_runtime import (
    _collect_dynamic_objects,
    _collect_receptacles,
    _first_receptacle_id,
    _placement_diagnostic,
    _public_scenario,
    _read_containment,
    _read_locations,
    _receptacle_requires_open,
    _refresh_object_positions,
    _refresh_runtime_render_state,
    _resolve_placement,
    _score,
    _seed_misplaced_objects,
    _target_start_receptacle_id,
)
from roboclaws.household.artifact_paths import resolve_home_relative_path as _resolve_artifact_path

BACKEND = "molmospaces_subprocess"
API_SEMANTIC_PROVENANCE = "api_semantic"


def _write_state(path: Path, worker_state: dict[str, Any]) -> None:
    protocol.write_state(
        path,
        worker_state,
        refresh_runtime_render_state=_refresh_runtime_render_state,
    )


def _load_generated_mess_manifest(path: Path | None) -> dict[str, Any]:
    return initialization.load_generated_mess_manifest(path)


def _source_room_labels(scene_xml: Path) -> dict[str, dict[str, str]]:
    return initialization.source_room_labels(scene_xml)


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
    return state.init_state(
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
    return initialization.prepare_molmospaces_scene(
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
    return initialization.resolve_molmospaces_scene_xml(
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
    return initialization.scene_xml_path_from_ref(raw_ref, scenes_root=scenes_root)


def _scene_ref_candidate_xml_path(
    raw_path: Any,
    *,
    scenes_root: Path,
) -> tuple[Path, bool] | None:
    return initialization.scene_ref_candidate_xml_path(raw_path, scenes_root=scenes_root)


def _normalize_molmospaces_scene_ref_path(
    raw_path: Any,
    *,
    scenes_root: Path,
) -> tuple[Path, bool]:
    return initialization.normalize_molmospaces_scene_ref_path(raw_path, scenes_root=scenes_root)


def _scenario_id(*, scene_source: str, scene_index: int, seed: int) -> str:
    return initialization.scenario_id(scene_source=scene_source, scene_index=scene_index, seed=seed)


def _molmo_worker_output_hooks() -> capture.MolmoWorkerOutputHooks:
    return capture.MolmoWorkerOutputHooks(
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


def _molmo_action_hooks() -> actions.MolmoActionHooks:
    return actions.MolmoActionHooks(
        api_semantic_provenance=API_SEMANTIC_PROVENANCE,
        backend=BACKEND,
        held_location_id=scenario_state.HELD_LOCATION_ID,
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
    return capture.write_snapshot(
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
    result = capture.write_robot_views(
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
        fpv_path = Path(_resolve_artifact_path(str((result.get("views") or {}).get("fpv") or "")))
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


def write_camera_views(
    state: dict[str, Any],
    output_dir: Path,
    camera_request: dict[str, Any] | list[dict[str, Any]],
    *,
    width: int = DEFAULT_RENDER_WIDTH,
    height: int = DEFAULT_RENDER_HEIGHT,
) -> dict[str, Any]:
    return capture.write_camera_views(
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
    return capture.render_camera_views_with_model_data(
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
    return actions.navigate_to_receptacle(state, receptacle_id, hooks=_molmo_action_hooks())


def _navigate_to_receptacle(
    state: dict[str, Any],
    receptacle_id: str,
    *,
    tool: str,
) -> dict[str, Any]:
    return actions.navigate_to_receptacle_core(
        state,
        receptacle_id,
        tool=tool,
        hooks=_molmo_action_hooks(),
    )


def navigate_to_object(state: dict[str, Any], object_id: str) -> dict[str, Any]:
    return actions.navigate_to_object(state, object_id, hooks=_molmo_action_hooks())


def navigate_to_waypoint(state: dict[str, Any], waypoint: dict[str, Any]) -> dict[str, Any]:
    return actions.navigate_to_waypoint(state, waypoint, hooks=_molmo_action_hooks())


def navigate_to_relative_pose(
    state: dict[str, Any],
    *,
    forward_m: float = 0.0,
    lateral_m: float = 0.0,
    yaw_delta_deg: float = 0.0,
) -> dict[str, Any]:
    return actions.navigate_to_relative_pose(
        state,
        forward_m=forward_m,
        lateral_m=lateral_m,
        yaw_delta_deg=yaw_delta_deg,
        hooks=_molmo_action_hooks(),
    )


def frame_comparison_object(state: dict[str, Any], object_id: str) -> dict[str, Any]:
    return actions.frame_comparison_object(state, object_id, hooks=_molmo_action_hooks())


def pick_object(state: dict[str, Any], object_id: str) -> dict[str, Any]:
    return actions.pick_object(state, object_id, hooks=_molmo_action_hooks())


def place_object(state: dict[str, Any], receptacle_id: str) -> dict[str, Any]:
    return actions.place_object(state, receptacle_id, hooks=_molmo_action_hooks())


def place_inside_object(state: dict[str, Any], receptacle_id: str) -> dict[str, Any]:
    return actions.place_inside_object(state, receptacle_id, hooks=_molmo_action_hooks())


def _place_object_at_receptacle(
    state: dict[str, Any],
    receptacle_id: str,
    *,
    tool: str,
    relation: str,
) -> dict[str, Any]:
    return actions.place_object_at_receptacle(
        state,
        receptacle_id,
        tool=tool,
        relation=relation,
        hooks=_molmo_action_hooks(),
    )


def open_receptacle(state: dict[str, Any], receptacle_id: str) -> dict[str, Any]:
    return actions.open_receptacle(state, receptacle_id, hooks=_molmo_action_hooks())


def close_receptacle(state: dict[str, Any], receptacle_id: str) -> dict[str, Any]:
    return actions.close_receptacle(state, receptacle_id, hooks=_molmo_action_hooks())


def _robot_pose_state_mutation(held_object_changed: bool) -> str:
    return actions.robot_pose_state_mutation(held_object_changed)


def _open_receptacle_state_mutation(
    joints_changed: bool,
    robot_pose_changed: bool,
    held_object_changed: bool,
) -> str:
    return actions.open_receptacle_state_mutation(
        joints_changed,
        robot_pose_changed,
        held_object_changed,
    )


def _close_receptacle_state_mutation(
    joints_changed: bool,
    held_object_changed: bool,
) -> str:
    return actions.close_receptacle_state_mutation(joints_changed, held_object_changed)


def done_cleanup(state: dict[str, Any], reason: str) -> dict[str, Any]:
    return actions.done_cleanup(state, reason, hooks=_molmo_action_hooks())


def _molmo_init_hooks() -> state.MolmoInitHooks:
    return state.MolmoInitHooks(
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
