from __future__ import annotations

from pathlib import Path
from typing import Any

import mujoco

from roboclaws.backends.molmospaces import capture, navigation, runtime_state
from roboclaws.backends.molmospaces.perception_runtime import _subtree_body_ids

_MODEL_DATA_CACHE: dict[tuple[str, str], tuple[mujoco.MjModel, mujoco.MjData]] = {}


def _load_model_data(scene_xml: Path) -> tuple[mujoco.MjModel, mujoco.MjData]:
    return runtime_state.load_model_data(scene_xml)


def _load_model_data_for_state(state: dict[str, Any]) -> tuple[mujoco.MjModel, mujoco.MjData]:
    return runtime_state.load_model_data_for_state(
        state,
        model_data_cache=_MODEL_DATA_CACHE,
        load_model_data=_load_model_data,
        load_robot_model_data=_load_robot_model_data,
    )


def _load_robot_model_data(
    scene_xml: Path,
    robot_xml: Path,
) -> tuple[mujoco.MjModel, mujoco.MjData]:
    return runtime_state.load_robot_model_data(
        scene_xml, robot_xml, load_model_data=_load_model_data
    )


def _robot_xml_name(robot_name: str) -> str:
    return runtime_state.robot_xml_name(robot_name)


def _robot_camera_names(model: mujoco.MjModel) -> list[str]:
    return runtime_state.robot_camera_names(model)


def _robot_result_payload(state: dict[str, Any], model: mujoco.MjModel) -> dict[str, Any]:
    return runtime_state.robot_result_payload(state, model, robot_camera_names=_robot_camera_names)


def _set_robot_pose(
    model: mujoco.MjModel,
    data: mujoco.MjData,
    pose: dict[str, float],
) -> None:
    runtime_state.set_robot_pose(model, data, pose, set_joint_qpos=_set_joint_qpos)


def _apply_robot_view_camera_offset(
    model: mujoco.MjModel,
    data: mujoco.MjData,
    *,
    yaw_offset_deg: float = 0.0,
    pitch_offset_deg: float = 0.0,
) -> dict[str, Any]:
    return runtime_state.apply_robot_view_camera_offset(
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
    return runtime_state.add_joint_qpos_if_present(model, data, joint_name, delta)


def _set_joint_qpos(
    model: mujoco.MjModel,
    data: mujoco.MjData,
    joint_name: str,
    value: float,
) -> None:
    runtime_state.set_joint_qpos(model, data, joint_name, value)


def _sync_held_object_to_robot_pose(
    model: mujoco.MjModel,
    data: mujoco.MjData,
    state: dict[str, Any],
) -> dict[str, Any] | None:
    return runtime_state.sync_held_object_to_robot_pose(
        model,
        data,
        state,
        held_object_position=_held_object_position,
        set_free_body_position=_set_free_body_position,
    )


def _held_object_position(state: dict[str, Any]) -> list[float]:
    return runtime_state.held_object_position(state)


def _openable_receptacle_joints(
    model: mujoco.MjModel,
    body_name: str,
) -> list[dict[str, Any]]:
    return runtime_state.openable_receptacle_joints(
        model, body_name, subtree_body_ids=_subtree_body_ids
    )


def _robot_pose_near_receptacle(
    state: dict[str, Any],
    receptacle: dict[str, Any],
) -> dict[str, Any]:
    return navigation.robot_pose_near_receptacle(state, receptacle)


def _robot_pose_for_open_receptacle(
    state: dict[str, Any],
    receptacle: dict[str, Any],
) -> dict[str, Any]:
    return navigation.robot_pose_for_open_receptacle(state, receptacle)


def _robot_pose_near_object(
    state: dict[str, Any],
    obj: dict[str, Any],
    *,
    source_receptacle_id: str | None = None,
) -> dict[str, Any]:
    return navigation.robot_pose_near_object(
        state,
        obj,
        source_receptacle_id=source_receptacle_id,
    )


def _robot_pose_for_waypoint(
    state: dict[str, Any],
    waypoint: dict[str, Any],
    target: list[float],
) -> dict[str, Any]:
    return navigation.robot_pose_for_waypoint(state, waypoint, target)


def _waypoint_target_position(
    state: dict[str, Any],
    waypoint: dict[str, Any],
) -> list[float]:
    return navigation.waypoint_target_position(state, waypoint)


def _robot_view_camera_adjustment(
    *,
    camera_yaw_offset_deg: float = 0.0,
    camera_pitch_offset_deg: float = 0.0,
    applied_joints: list[str] | None = None,
    unavailable_reason: str | None = None,
) -> dict[str, Any]:
    return capture.robot_view_camera_adjustment(
        camera_yaw_offset_deg=camera_yaw_offset_deg,
        camera_pitch_offset_deg=camera_pitch_offset_deg,
        applied_joints=applied_joints,
        unavailable_reason=unavailable_reason,
    )


def _set_free_body_position(
    model: mujoco.MjModel,
    data: mujoco.MjData,
    body_name: str,
    position: list[float],
) -> None:
    runtime_state.set_free_body_position(model, data, body_name, position)
