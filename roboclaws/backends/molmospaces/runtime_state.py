from __future__ import annotations

import math
import tempfile
from pathlib import Path
from typing import Any, Callable

import mujoco


def set_free_body_position(
    model: mujoco.MjModel,
    data: mujoco.MjData,
    body_name: str,
    position: list[float],
) -> None:
    body_id = mujoco.mj_name2id(model, mujoco.mjtObj.mjOBJ_BODY, body_name)
    if body_id < 0:
        raise ValueError(f"unknown body: {body_name}")
    joint_id = int(model.body_jntadr[body_id])
    if joint_id < 0 or int(model.jnt_type[joint_id]) != int(mujoco.mjtJoint.mjJNT_FREE):
        raise ValueError(f"body does not have a free joint: {body_name}")
    qposadr = int(model.jnt_qposadr[joint_id])
    data.qpos[qposadr : qposadr + 3] = position


def refresh_object_positions(
    model: mujoco.MjModel,
    data: mujoco.MjData,
    state: dict[str, Any],
    *,
    xyz: Callable[[Any], list[float]],
) -> None:
    for obj in state.get("objects", {}).values():
        body_id = mujoco.mj_name2id(model, mujoco.mjtObj.mjOBJ_BODY, obj["body_name"])
        if body_id >= 0:
            obj["position"] = xyz(data.xpos[body_id])


def refresh_runtime_render_state(
    state: dict[str, Any],
    *,
    load_model_data_for_state: Callable[[dict[str, Any]], tuple[mujoco.MjModel, mujoco.MjData]],
    apply_qpos: Callable[[mujoco.MjData, list[float]], None],
    runtime_render_state: Callable[[mujoco.MjModel, mujoco.MjData, dict[str, Any]], dict[str, Any]],
) -> None:
    try:
        model, data = load_model_data_for_state(state)
        apply_qpos(data, state["qpos"])
        mujoco.mj_forward(model, data)
    except Exception as exc:
        state["runtime_render_state"] = {
            "schema": "molmospaces_runtime_render_state_v1",
            "status": "unavailable",
            "unavailable_reason": f"{type(exc).__name__}: {exc}",
        }
        return
    state["runtime_render_state"] = runtime_render_state(model, data, state)


def runtime_render_state(
    model: mujoco.MjModel,
    data: mujoco.MjData,
    state: dict[str, Any],
    *,
    runtime_subtree_joints: Callable[..., list[dict[str, Any]]],
    xyz: Callable[[Any], list[float]],
) -> dict[str, Any]:
    objects = {}
    articulated_count = 0
    try:
        for object_id, obj in sorted((state.get("objects") or {}).items()):
            if not isinstance(obj, dict):
                continue
            body_name = str(obj.get("body_name") or "")
            body_id = mujoco.mj_name2id(model, mujoco.mjtObj.mjOBJ_BODY, body_name)
            if body_id < 0:
                continue
            joints = runtime_subtree_joints(
                model,
                data,
                body_name,
                exclude_root_freejoint=True,
            )
            if joints:
                articulated_count += 1
            objects[str(object_id)] = {
                "object_key": str(object_id),
                "category": obj.get("category") or "",
                "body_name": body_name,
                "upstream_object_id": obj.get("upstream_object_id") or obj.get("object_id") or "",
                "position": xyz(data.xpos[body_id]),
                "subtree_joint_count": len(joints),
                "articulation_status": "articulated" if joints else "rigid_or_free_body",
                "articulation_joints": joints,
            }
    except Exception as exc:
        return {
            "schema": "molmospaces_runtime_render_state_v1",
            "status": "unavailable",
            "unavailable_reason": f"{type(exc).__name__}: {exc}",
        }
    return {
        "schema": "molmospaces_runtime_render_state_v1",
        "status": "computed",
        "source": "mujoco_live_model_data_qpos",
        "qpos_length": len(state.get("qpos") or []),
        "object_count": len(objects),
        "articulated_object_count": articulated_count,
        "objects": objects,
    }


def runtime_subtree_joints(
    model: mujoco.MjModel,
    data: mujoco.MjData,
    body_name: str,
    *,
    exclude_root_freejoint: bool,
    subtree_body_ids: Callable[[mujoco.MjModel, str], list[int]],
    joint_qpos_width: Callable[[mujoco.MjModel, int], int],
    joint_type_name: Callable[[mujoco.MjModel, int], str],
) -> list[dict[str, Any]]:
    root_body_id = mujoco.mj_name2id(model, mujoco.mjtObj.mjOBJ_BODY, body_name)
    if root_body_id < 0:
        return []
    joints = []
    for body_id in subtree_body_ids(model, body_name):
        joint_count = int(model.body_jntnum[body_id])
        if joint_count <= 0:
            continue
        body_joint_start = int(model.body_jntadr[body_id])
        for offset in range(joint_count):
            joint_id = body_joint_start + offset
            joint_type = int(model.jnt_type[joint_id])
            if (
                exclude_root_freejoint
                and body_id == root_body_id
                and offset == 0
                and joint_type == int(mujoco.mjtJoint.mjJNT_FREE)
            ):
                continue
            joint_name = mujoco.mj_id2name(model, mujoco.mjtObj.mjOBJ_JOINT, joint_id)
            if not joint_name:
                continue
            qposadr = int(model.jnt_qposadr[joint_id])
            qpos_width = joint_qpos_width(model, joint_id)
            joints.append(
                {
                    "joint_name": joint_name,
                    "body_name": mujoco.mj_id2name(model, mujoco.mjtObj.mjOBJ_BODY, body_id) or "",
                    "joint_type": joint_type_name(model, joint_id),
                    "qposadr": qposadr,
                    "qpos": [
                        round(float(value), 6)
                        for value in data.qpos[qposadr : qposadr + qpos_width]
                    ],
                    "range": [
                        round(float(model.jnt_range[joint_id][0]), 6),
                        round(float(model.jnt_range[joint_id][1]), 6),
                    ]
                    if bool(model.jnt_limited[joint_id])
                    else [],
                }
            )
    return joints


def joint_qpos_width(model: mujoco.MjModel, joint_id: int) -> int:
    joint_type = int(model.jnt_type[joint_id])
    if joint_type == int(mujoco.mjtJoint.mjJNT_FREE):
        return 7
    if joint_type == int(mujoco.mjtJoint.mjJNT_BALL):
        return 4
    return 1


def joint_type_name(model: mujoco.MjModel, joint_id: int) -> str:
    joint_type = int(model.jnt_type[joint_id])
    if joint_type == int(mujoco.mjtJoint.mjJNT_FREE):
        return "free"
    if joint_type == int(mujoco.mjtJoint.mjJNT_BALL):
        return "ball"
    if joint_type == int(mujoco.mjtJoint.mjJNT_SLIDE):
        return "slide"
    if joint_type == int(mujoco.mjtJoint.mjJNT_HINGE):
        return "hinge"
    return str(joint_type)


def load_model_data(scene_xml: Path) -> tuple[mujoco.MjModel, mujoco.MjData]:
    model = mujoco.MjModel.from_xml_path(str(scene_xml))
    data = mujoco.MjData(model)
    mujoco.mj_forward(model, data)
    return model, data


def load_model_data_for_state(
    state: dict[str, Any],
    *,
    model_data_cache: dict[tuple[str, str], tuple[mujoco.MjModel, mujoco.MjData]],
    load_model_data: Callable[[Path], tuple[mujoco.MjModel, mujoco.MjData]],
    load_robot_model_data: Callable[[Path, Path], tuple[mujoco.MjModel, mujoco.MjData]],
) -> tuple[mujoco.MjModel, mujoco.MjData]:
    scene_xml = str(state["scene_xml"])
    if state.get("robot_included"):
        robot_xml = state.get("robot_xml")
        if not robot_xml:
            raise ValueError("robot_included state missing robot_xml")
        cache_key = (scene_xml, str(robot_xml))
        cached = model_data_cache.get(cache_key)
        if cached is None:
            cached = load_robot_model_data(Path(scene_xml), Path(robot_xml))
            model_data_cache[cache_key] = cached
        return cached
    cache_key = (scene_xml, "")
    cached = model_data_cache.get(cache_key)
    if cached is None:
        cached = load_model_data(Path(scene_xml))
        model_data_cache[cache_key] = cached
    return cached


def load_robot_model_data(
    scene_xml: Path,
    robot_xml: Path,
    *,
    load_model_data: Callable[[Path], tuple[mujoco.MjModel, mujoco.MjData]],
) -> tuple[mujoco.MjModel, mujoco.MjData]:
    xml_content = scene_xml.read_text(encoding="utf-8")
    mujoco_tag_end = xml_content.find(">") + 1
    include_line = f'\n  <include file="{robot_xml}"/>\n'
    modified_xml = xml_content[:mujoco_tag_end] + include_line + xml_content[mujoco_tag_end:]
    temp_path: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            "w",
            suffix=".xml",
            prefix="roboclaws_robot_scene_",
            dir=str(scene_xml.parent),
            delete=False,
            encoding="utf-8",
        ) as temp:
            temp.write(modified_xml)
            temp_path = Path(temp.name)
        return load_model_data(temp_path)
    finally:
        if temp_path is not None:
            temp_path.unlink(missing_ok=True)


def robot_xml_name(robot_name: str) -> str:
    if robot_name == "rby1m":
        return "rby1_v1.2_site_control.xml"
    if robot_name == "rby1":
        return "rby1_site_control.xml"
    raise ValueError(f"unsupported robot for visual cleanup demo: {robot_name}")


def robot_camera_names(model: mujoco.MjModel) -> list[str]:
    names = []
    for camera_id in range(model.ncam):
        name = mujoco.mj_id2name(model, mujoco.mjtObj.mjOBJ_CAMERA, camera_id)
        if name and name.startswith("robot_0/"):
            names.append(name)
    return names


def robot_result_payload(
    state: dict[str, Any],
    model: mujoco.MjModel,
    *,
    robot_camera_names: Callable[[mujoco.MjModel], list[str]],
) -> dict[str, Any]:
    return {
        "robot_included": True,
        "robot_name": state.get("robot_name"),
        "robot_xml": state.get("robot_xml"),
        "robot_body_name": state.get("robot_body_name"),
        "robot_camera_names": state.get("robot_camera_names") or robot_camera_names(model),
        "robot_control_provenance": state.get("robot_control_provenance"),
        "robot_view_provenance": state.get("robot_view_provenance"),
        "robot_pose": state.get("robot_pose"),
        "room_outline_count": len(state.get("room_outlines", [])),
        "robot_model_stats": {
            "nbody": int(model.nbody),
            "ngeom": int(model.ngeom),
            "njnt": int(model.njnt),
            "nq": int(model.nq),
            "nu": int(model.nu),
        },
    }


def set_robot_pose(
    model: mujoco.MjModel,
    data: mujoco.MjData,
    pose: dict[str, float],
    *,
    set_joint_qpos: Callable[[mujoco.MjModel, mujoco.MjData, str, float], None],
) -> None:
    set_joint_qpos(model, data, "robot_0/base_x", pose["x"])
    set_joint_qpos(model, data, "robot_0/base_y", pose["y"])
    set_joint_qpos(model, data, "robot_0/base_theta", pose["theta"])
    if mujoco.mj_name2id(model, mujoco.mjtObj.mjOBJ_JOINT, "robot_0/head_0") >= 0:
        set_joint_qpos(model, data, "robot_0/head_0", float(pose.get("head_yaw", 0.0)))
    if mujoco.mj_name2id(model, mujoco.mjtObj.mjOBJ_JOINT, "robot_0/head_1") >= 0:
        set_joint_qpos(model, data, "robot_0/head_1", float(pose.get("head_pitch", 0.0)))


def apply_robot_view_camera_offset(
    model: mujoco.MjModel,
    data: mujoco.MjData,
    *,
    yaw_offset_deg: float,
    pitch_offset_deg: float,
    add_joint_qpos_if_present: Callable[[mujoco.MjModel, mujoco.MjData, str, float], bool],
    robot_view_camera_adjustment: Callable[..., dict[str, Any]],
) -> dict[str, Any]:
    applied_joints: list[str] = []
    unavailable_reason = None
    if yaw_offset_deg:
        try:
            if add_joint_qpos_if_present(
                model,
                data,
                "robot_0/head_0",
                math.radians(float(yaw_offset_deg)),
            ):
                applied_joints.append("robot_0/head_0")
        except TypeError as exc:
            unavailable_reason = f"{type(exc).__name__}: {exc}"
    if pitch_offset_deg:
        try:
            if add_joint_qpos_if_present(
                model,
                data,
                "robot_0/head_1",
                math.radians(float(pitch_offset_deg)),
            ):
                applied_joints.append("robot_0/head_1")
        except TypeError as exc:
            unavailable_reason = f"{type(exc).__name__}: {exc}"
    return robot_view_camera_adjustment(
        camera_yaw_offset_deg=yaw_offset_deg,
        camera_pitch_offset_deg=pitch_offset_deg,
        applied_joints=applied_joints,
        unavailable_reason=unavailable_reason,
    )


def add_joint_qpos_if_present(
    model: mujoco.MjModel,
    data: mujoco.MjData,
    joint_name: str,
    delta: float,
) -> bool:
    joint_id = mujoco.mj_name2id(model, mujoco.mjtObj.mjOBJ_JOINT, joint_name)
    if joint_id < 0:
        return False
    qposadr = int(model.jnt_qposadr[joint_id])
    data.qpos[qposadr] = float(data.qpos[qposadr]) + float(delta)
    return True


def set_joint_qpos(
    model: mujoco.MjModel,
    data: mujoco.MjData,
    joint_name: str,
    value: float,
) -> None:
    joint_id = mujoco.mj_name2id(model, mujoco.mjtObj.mjOBJ_JOINT, joint_name)
    if joint_id < 0:
        raise ValueError(f"missing robot joint: {joint_name}")
    qposadr = int(model.jnt_qposadr[joint_id])
    data.qpos[qposadr] = float(value)


def sync_held_object_to_robot_pose(
    model: mujoco.MjModel,
    data: mujoco.MjData,
    state: dict[str, Any],
    *,
    held_object_position: Callable[[dict[str, Any]], list[float]],
    set_free_body_position: Callable[[mujoco.MjModel, mujoco.MjData, str, list[float]], None],
) -> dict[str, Any] | None:
    object_id = state.get("held_object_id")
    if not object_id:
        return None
    obj = state["objects"].get(str(object_id))
    if obj is None:
        return None
    target_position = held_object_position(state)
    set_free_body_position(model, data, obj["body_name"], target_position)
    obj["position"] = target_position
    return {
        "object_id": object_id,
        "position": target_position,
        "position_source": "robot_relative_held_pose",
    }


def held_object_position(state: dict[str, Any]) -> list[float]:
    pose = state.get("robot_pose") or {}
    if "x" not in pose or "y" not in pose or "theta" not in pose:
        return [0.0, 0.0, 1.0]
    theta = float(pose["theta"])
    distance_m = 0.8
    return [
        round(float(pose["x"]) + math.cos(theta) * distance_m, 6),
        round(float(pose["y"]) + math.sin(theta) * distance_m, 6),
        1.22,
    ]


def openable_receptacle_joints(
    model: mujoco.MjModel,
    body_name: str,
    *,
    subtree_body_ids: Callable[[mujoco.MjModel, str], list[int]],
) -> list[dict[str, Any]]:
    joints = []
    for body_id in subtree_body_ids(model, body_name):
        joint_count = int(model.body_jntnum[body_id])
        if joint_count <= 0:
            continue
        for offset in range(joint_count):
            joint_id = int(model.body_jntadr[body_id]) + offset
            joint_type = int(model.jnt_type[joint_id])
            if joint_type not in {
                int(mujoco.mjtJoint.mjJNT_HINGE),
                int(mujoco.mjtJoint.mjJNT_SLIDE),
            }:
                continue
            joint_name = mujoco.mj_id2name(model, mujoco.mjtObj.mjOBJ_JOINT, joint_id)
            if not joint_name:
                continue
            open_value = float(model.jnt_range[joint_id][1])
            close_value = float(model.jnt_range[joint_id][0])
            joints.append(
                {
                    "joint_name": joint_name,
                    "joint_type": "hinge"
                    if joint_type == int(mujoco.mjtJoint.mjJNT_HINGE)
                    else "slide",
                    "open_value": round(open_value, 6),
                    "close_value": round(close_value, 6),
                }
            )
    return joints
