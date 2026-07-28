from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any, Callable

import mujoco


@dataclass(frozen=True)
class MolmoActionHooks:
    api_semantic_provenance: str
    backend: str
    held_location_id: str
    apply_qpos: Callable[..., Any]
    close_receptacle_state_mutation: Callable[..., str]
    count: Callable[..., Any]
    error: Callable[..., dict[str, Any]]
    held_object_position: Callable[..., list[float]]
    load_model_data_for_state: Callable[..., tuple[Any, Any]]
    ok: Callable[..., dict[str, Any]]
    open_receptacle_state_mutation: Callable[..., str]
    openable_receptacle_joints: Callable[..., list[dict[str, Any]]]
    placement_diagnostic: Callable[..., dict[str, Any]]
    read_containment: Callable[..., dict[str, dict[str, str]]]
    read_locations: Callable[..., dict[str, str]]
    receptacle_requires_open: Callable[..., bool]
    refresh_object_positions: Callable[..., Any]
    resolve_placement: Callable[..., dict[str, Any]]
    robot_pose_for_open_receptacle: Callable[..., dict[str, Any]]
    robot_pose_for_waypoint: Callable[..., dict[str, Any]]
    robot_pose_near_object: Callable[..., dict[str, Any]]
    robot_pose_near_receptacle: Callable[..., dict[str, Any]]
    robot_pose_state_mutation: Callable[..., str]
    score: Callable[..., dict[str, Any]]
    set_free_body_position: Callable[..., Any]
    set_joint_qpos: Callable[..., Any]
    set_robot_pose: Callable[..., Any]
    sync_held_object_to_robot_pose: Callable[..., dict[str, Any] | None]
    waypoint_target_position: Callable[..., list[float]]


def navigate_to_receptacle(
    state: dict[str, Any],
    receptacle_id: str,
    *,
    hooks: MolmoActionHooks,
) -> dict[str, Any]:
    hooks.count(state, "navigate_to_receptacle")
    return navigate_to_receptacle_core(
        state,
        receptacle_id,
        tool="navigate_to_receptacle",
        hooks=hooks,
    )


def navigate_to_receptacle_core(
    state: dict[str, Any],
    receptacle_id: str,
    *,
    tool: str,
    hooks: MolmoActionHooks,
) -> dict[str, Any]:
    if receptacle_id not in state["receptacles"]:
        return hooks.error(tool, "stale_reference", receptacle_id=receptacle_id)
    previous = state.get("current_receptacle_id")
    state["current_receptacle_id"] = receptacle_id
    robot_pose = None
    held_object_pose = None
    qpos_changed = False
    state_mutation = "agent_pose_semantic"
    if state.get("robot_included"):
        model, data = hooks.load_model_data_for_state(state)
        hooks.apply_qpos(data, state["qpos"])
        robot_pose = hooks.robot_pose_near_receptacle(state, state["receptacles"][receptacle_id])
        hooks.set_robot_pose(model, data, robot_pose)
        state["robot_pose"] = robot_pose
        state.setdefault("robot_trajectory", []).append(robot_pose)
        held_object_pose = hooks.sync_held_object_to_robot_pose(model, data, state)
        mujoco.mj_forward(model, data)
        hooks.refresh_object_positions(model, data, state)
        state["qpos"] = [float(value) for value in data.qpos]
        qpos_changed = True
        state_mutation = hooks.robot_pose_state_mutation(held_object_pose is not None)
    return hooks.ok(
        tool,
        primitive_provenance=hooks.api_semantic_provenance,
        receptacle_id=receptacle_id,
        previous_receptacle_id=previous,
        state_mutation=state_mutation,
        held_object_pose=held_object_pose,
        robot_name=state.get("robot_name"),
        robot_pose=robot_pose,
        robot_control_provenance=state.get("robot_control_provenance"),
        qpos_changed=qpos_changed,
        backend=hooks.backend,
    )


def navigate_to_object(
    state: dict[str, Any],
    object_id: str,
    *,
    hooks: MolmoActionHooks,
) -> dict[str, Any]:
    hooks.count(state, "navigate_to_object")
    if object_id not in state["objects"]:
        return hooks.error("navigate_to_object", "stale_reference", object_id=object_id)
    if state.get("held_object_id") == object_id:
        return hooks.error("navigate_to_object", "object_already_held", object_id=object_id)
    locations = hooks.read_locations(state)
    source_receptacle_id = locations.get(object_id)
    if not source_receptacle_id or source_receptacle_id == hooks.held_location_id:
        return hooks.error(
            "navigate_to_object", "object_not_at_public_location", object_id=object_id
        )
    previous = state.get("current_receptacle_id")
    state["current_receptacle_id"] = source_receptacle_id
    robot_pose = None
    qpos_changed = False
    state_mutation = "agent_pose_semantic"
    if state.get("robot_included"):
        model, data = hooks.load_model_data_for_state(state)
        hooks.apply_qpos(data, state["qpos"])
        mujoco.mj_forward(model, data)
        hooks.refresh_object_positions(model, data, state)
        robot_pose = hooks.robot_pose_near_object(
            state,
            state["objects"][object_id],
            source_receptacle_id=source_receptacle_id,
        )
        hooks.set_robot_pose(model, data, robot_pose)
        mujoco.mj_forward(model, data)
        state["qpos"] = [float(value) for value in data.qpos]
        state["robot_pose"] = robot_pose
        state.setdefault("robot_trajectory", []).append(robot_pose)
        qpos_changed = True
        state_mutation = "robot_base_qpos"
    return hooks.ok(
        "navigate_to_object",
        primitive_provenance=hooks.api_semantic_provenance,
        object_id=object_id,
        source_receptacle_id=source_receptacle_id,
        previous_receptacle_id=previous,
        location_id=source_receptacle_id,
        state_mutation=state_mutation,
        robot_name=state.get("robot_name"),
        robot_pose=robot_pose,
        robot_control_provenance=state.get("robot_control_provenance"),
        qpos_changed=qpos_changed,
        backend=hooks.backend,
    )


def navigate_to_waypoint(
    state: dict[str, Any],
    waypoint: dict[str, Any],
    *,
    hooks: MolmoActionHooks,
) -> dict[str, Any]:
    hooks.count(state, "navigate_to_waypoint")
    waypoint_id = str(waypoint.get("waypoint_id") or "")
    room_id = str(waypoint.get("room_id") or "")
    previous = state.get("current_waypoint_id")
    state["current_waypoint_id"] = waypoint_id
    robot_pose = None
    held_object_pose = None
    qpos_changed = False
    state_mutation = "agent_pose_semantic"
    if state.get("robot_included"):
        model, data = hooks.load_model_data_for_state(state)
        hooks.apply_qpos(data, state["qpos"])
        mujoco.mj_forward(model, data)
        target = hooks.waypoint_target_position(state, waypoint)
        robot_pose = hooks.robot_pose_for_waypoint(state, waypoint, target)
        hooks.set_robot_pose(model, data, robot_pose)
        state["robot_pose"] = robot_pose
        state.setdefault("robot_trajectory", []).append(robot_pose)
        held_object_pose = hooks.sync_held_object_to_robot_pose(model, data, state)
        mujoco.mj_forward(model, data)
        hooks.refresh_object_positions(model, data, state)
        state["qpos"] = [float(value) for value in data.qpos]
        qpos_changed = True
        state_mutation = hooks.robot_pose_state_mutation(held_object_pose is not None)
    return hooks.ok(
        "navigate_to_waypoint",
        primitive_provenance=hooks.api_semantic_provenance,
        waypoint_id=waypoint_id,
        room_id=room_id,
        previous_waypoint_id=previous,
        state_mutation=state_mutation,
        held_object_pose=held_object_pose,
        robot_name=state.get("robot_name"),
        robot_pose=robot_pose,
        robot_control_provenance=state.get("robot_control_provenance"),
        qpos_changed=qpos_changed,
        backend=hooks.backend,
    )


def navigate_to_relative_pose(
    state: dict[str, Any],
    *,
    forward_m: float = 0.0,
    lateral_m: float = 0.0,
    yaw_delta_deg: float = 0.0,
    hooks: MolmoActionHooks,
) -> dict[str, Any]:
    hooks.count(state, "navigate_to_relative_pose")
    requested = _relative_delta(forward_m, lateral_m, yaw_delta_deg)
    if not state.get("robot_included"):
        return hooks.error(
            "navigate_to_relative_pose",
            "relative_navigation_requires_robot",
            status="blocked_capability",
            requested_delta=requested,
            applied_delta=_relative_delta(),
            backend=hooks.backend,
        )
    previous_pose = dict(state.get("robot_pose") or {})
    if not previous_pose:
        return hooks.error(
            "navigate_to_relative_pose",
            "robot_pose_unavailable",
            status="blocked_capability",
            requested_delta=requested,
            applied_delta=_relative_delta(),
            backend=hooks.backend,
        )
    robot_pose = _pose_after_relative_delta(previous_pose, requested)
    model, data = hooks.load_model_data_for_state(state)
    hooks.apply_qpos(data, state["qpos"])
    mujoco.mj_forward(model, data)
    hooks.set_robot_pose(model, data, robot_pose)
    state["robot_pose"] = robot_pose
    state.setdefault("robot_trajectory", []).append(robot_pose)
    held_object_pose = hooks.sync_held_object_to_robot_pose(model, data, state)
    mujoco.mj_forward(model, data)
    hooks.refresh_object_positions(model, data, state)
    state["qpos"] = [float(value) for value in data.qpos]
    return hooks.ok(
        "navigate_to_relative_pose",
        primitive_provenance=hooks.api_semantic_provenance,
        requested_delta=requested,
        applied_delta=requested,
        applied_forward_m=requested["forward_m"],
        applied_lateral_m=requested["lateral_m"],
        applied_yaw_delta_deg=requested["yaw_delta_deg"],
        frame_id="base_link",
        pose_source="relative_robot_frame",
        state_mutation=hooks.robot_pose_state_mutation(held_object_pose is not None),
        held_object_pose=held_object_pose,
        robot_name=state.get("robot_name"),
        robot_pose=robot_pose,
        robot_control_provenance=state.get("robot_control_provenance"),
        qpos_changed=True,
        clamped=False,
        clamp_metadata={"backend_limits_enforced": False},
        requires_reobserve=True,
        backend=hooks.backend,
    )


def frame_comparison_object(
    state: dict[str, Any],
    object_id: str,
    *,
    hooks: MolmoActionHooks,
) -> dict[str, Any]:
    hooks.count(state, "frame_comparison_object")
    if object_id not in state["objects"]:
        return hooks.error("frame_comparison_object", "stale_reference", object_id=object_id)
    if not state.get("robot_included"):
        return hooks.error("frame_comparison_object", "robot_not_included")
    model, data = hooks.load_model_data_for_state(state)
    hooks.apply_qpos(data, state["qpos"])
    mujoco.mj_forward(model, data)
    hooks.refresh_object_positions(model, data, state)
    robot_pose = hooks.robot_pose_near_object(
        state,
        state["objects"][object_id],
        source_receptacle_id=None,
    )
    robot_pose["pose_source"] = "roboclaws_comparison_object_pose"
    hooks.set_robot_pose(model, data, robot_pose)
    mujoco.mj_forward(model, data)
    state["qpos"] = [float(value) for value in data.qpos]
    state["robot_pose"] = robot_pose
    state.setdefault("robot_trajectory", []).append(robot_pose)
    return hooks.ok(
        "frame_comparison_object",
        primitive_provenance=hooks.api_semantic_provenance,
        object_id=object_id,
        state_mutation="robot_base_qpos",
        robot_name=state.get("robot_name"),
        robot_pose=robot_pose,
        robot_control_provenance=state.get("robot_control_provenance"),
        qpos_changed=True,
        backend=hooks.backend,
    )


def pick_object(
    state: dict[str, Any],
    object_id: str,
    *,
    hooks: MolmoActionHooks,
) -> dict[str, Any]:
    hooks.count(state, "pick")
    if object_id not in state["objects"]:
        return hooks.error("pick", "stale_reference", object_id=object_id)
    if state.get("held_object_id") is not None:
        return hooks.error("pick", "already_holding", held_object_id=state["held_object_id"])
    locations = hooks.read_locations(state)
    qpos_changed = False
    state_mutation = "held_state_only"
    if state.get("robot_included"):
        model, data = hooks.load_model_data_for_state(state)
        hooks.apply_qpos(data, state["qpos"])
        target_position = hooks.held_object_position(state)
        hooks.set_free_body_position(
            model, data, state["objects"][object_id]["body_name"], target_position
        )
        mujoco.mj_forward(model, data)
        hooks.refresh_object_positions(model, data, state)
        state["qpos"] = [float(value) for value in data.qpos]
        qpos_changed = True
        state_mutation = "mujoco_freejoint_qpos_held_pose"
    state["held_object_id"] = object_id
    state["objects"][object_id]["contained_in"] = None
    state["objects"][object_id]["location_relation"] = "held"
    return hooks.ok(
        "pick",
        primitive_provenance=hooks.api_semantic_provenance,
        object_id=object_id,
        previous_location_id=locations.get(object_id),
        location_id=hooks.held_location_id,
        state_mutation=state_mutation,
        qpos_changed=qpos_changed,
        backend=hooks.backend,
    )


def place_object(
    state: dict[str, Any],
    receptacle_id: str,
    *,
    hooks: MolmoActionHooks,
) -> dict[str, Any]:
    hooks.count(state, "place")
    return place_object_at_receptacle(
        state, receptacle_id, tool="place", relation="on", hooks=hooks
    )


def place_inside_object(
    state: dict[str, Any],
    receptacle_id: str,
    *,
    hooks: MolmoActionHooks,
) -> dict[str, Any]:
    hooks.count(state, "place_inside")
    return place_object_at_receptacle(
        state,
        receptacle_id,
        tool="place_inside",
        relation="inside",
        hooks=hooks,
    )


def _placement_index_for_object(state: dict[str, Any], object_id: str) -> int:
    selected_object_ids = [str(value) for value in state.get("selected_object_ids", [])]
    if object_id in selected_object_ids:
        return selected_object_ids.index(object_id)

    selected = set(selected_object_ids)
    other_pickupable_ids = sorted(
        str(candidate_id)
        for candidate_id, candidate in state.get("objects", {}).items()
        if str(candidate_id) not in selected and bool(candidate.get("pickupable", True))
    )
    if object_id not in other_pickupable_ids:
        raise ValueError(f"unknown pickupable object: {object_id}")
    return len(selected_object_ids) + other_pickupable_ids.index(object_id)


def place_object_at_receptacle(
    state: dict[str, Any],
    receptacle_id: str,
    *,
    tool: str,
    relation: str,
    hooks: MolmoActionHooks,
) -> dict[str, Any]:
    if receptacle_id not in state["receptacles"]:
        return hooks.error(tool, "stale_reference", receptacle_id=receptacle_id)
    object_id = state.get("held_object_id")
    if object_id is None:
        return hooks.error(tool, "not_holding")
    receptacle = state["receptacles"][receptacle_id]
    if (
        relation == "inside"
        and hooks.receptacle_requires_open(receptacle)
        and receptacle_id not in set(state.get("open_receptacle_ids", []))
    ):
        return hooks.error(tool, "receptacle_closed", receptacle_id=receptacle_id)

    model, data = hooks.load_model_data_for_state(state)
    hooks.apply_qpos(data, state["qpos"])
    obj = state["objects"][object_id]
    placement_resolution = hooks.resolve_placement(
        model,
        data,
        state=state,
        object_id=object_id,
        receptacle_id=receptacle_id,
        index=_placement_index_for_object(state, object_id),
        relation=relation,
    )
    target_position = placement_resolution["position"]
    hooks.set_free_body_position(model, data, obj["body_name"], target_position)
    mujoco.mj_forward(model, data)
    hooks.refresh_object_positions(model, data, state)
    diagnostic = hooks.placement_diagnostic(
        state=state,
        object_id=object_id,
        receptacle_id=receptacle_id,
        relation=relation,
        requested_position=target_position,
        source="cleanup_place",
        placement_resolution=placement_resolution,
    )
    state.setdefault("placement_diagnostics", []).append(diagnostic)

    state["qpos"] = [float(value) for value in data.qpos]
    state["held_object_id"] = None
    state["current_receptacle_id"] = receptacle_id
    state["objects"][object_id]["contained_in"] = receptacle_id if relation == "inside" else None
    state["objects"][object_id]["location_relation"] = relation
    final_locations = hooks.read_locations(state)
    return hooks.ok(
        tool,
        primitive_provenance=hooks.api_semantic_provenance,
        object_id=object_id,
        receptacle_id=receptacle_id,
        location_id=final_locations.get(object_id),
        contained_in=receptacle_id if relation == "inside" else None,
        location_relation=relation,
        placement_diagnostic=diagnostic,
        placement_support_status=diagnostic["support_status"],
        mujoco_body_name=obj["body_name"],
        qpos_changed=True,
        state_mutation="mujoco_freejoint_qpos",
        backend=hooks.backend,
    )


def open_receptacle(
    state: dict[str, Any],
    receptacle_id: str,
    *,
    hooks: MolmoActionHooks,
) -> dict[str, Any]:
    hooks.count(state, "open_receptacle")
    if receptacle_id not in state["receptacles"]:
        return hooks.error("open_receptacle", "stale_reference", receptacle_id=receptacle_id)

    model, data = hooks.load_model_data_for_state(state)
    hooks.apply_qpos(data, state["qpos"])
    receptacle = state["receptacles"][receptacle_id]
    joints = hooks.openable_receptacle_joints(model, receptacle["body_name"])
    for joint in joints:
        hooks.set_joint_qpos(model, data, joint["joint_name"], joint["open_value"])
    robot_pose = None
    robot_pose_changed = False
    if state.get("robot_included") and joints:
        robot_pose = hooks.robot_pose_for_open_receptacle(state, receptacle)
        hooks.set_robot_pose(model, data, robot_pose)
        state["robot_pose"] = robot_pose
        state.setdefault("robot_trajectory", []).append(robot_pose)
        held_object_pose = hooks.sync_held_object_to_robot_pose(model, data, state)
        robot_pose_changed = True
    else:
        held_object_pose = None
    mujoco.mj_forward(model, data)
    hooks.refresh_object_positions(model, data, state)
    state["qpos"] = [float(value) for value in data.qpos]
    open_ids = set(state.get("open_receptacle_ids", []))
    if joints:
        open_ids.add(receptacle_id)
    state["open_receptacle_ids"] = sorted(open_ids)
    return hooks.ok(
        "open_receptacle",
        primitive_provenance=hooks.api_semantic_provenance,
        receptacle_id=receptacle_id,
        opened=bool(joints),
        open_joints=joints,
        robot_pose=robot_pose,
        held_object_pose=held_object_pose,
        qpos_changed=bool(joints) or robot_pose_changed,
        state_mutation=hooks.open_receptacle_state_mutation(
            bool(joints),
            robot_pose_changed,
            held_object_pose is not None,
        ),
        backend=hooks.backend,
    )


def close_receptacle(
    state: dict[str, Any],
    receptacle_id: str,
    *,
    hooks: MolmoActionHooks,
) -> dict[str, Any]:
    hooks.count(state, "close_receptacle")
    if receptacle_id not in state["receptacles"]:
        return hooks.error("close_receptacle", "stale_reference", receptacle_id=receptacle_id)

    model, data = hooks.load_model_data_for_state(state)
    hooks.apply_qpos(data, state["qpos"])
    receptacle = state["receptacles"][receptacle_id]
    joints = hooks.openable_receptacle_joints(model, receptacle["body_name"])
    closed_joints = []
    for joint in joints:
        hooks.set_joint_qpos(model, data, joint["joint_name"], joint["close_value"])
        closed_joints.append(joint)
    held_object_pose = hooks.sync_held_object_to_robot_pose(model, data, state)
    mujoco.mj_forward(model, data)
    hooks.refresh_object_positions(model, data, state)
    state["qpos"] = [float(value) for value in data.qpos]
    open_ids = set(state.get("open_receptacle_ids", []))
    was_open = receptacle_id in open_ids
    open_ids.discard(receptacle_id)
    state["open_receptacle_ids"] = sorted(open_ids)
    return hooks.ok(
        "close_receptacle",
        primitive_provenance=hooks.api_semantic_provenance,
        receptacle_id=receptacle_id,
        closed=was_open or bool(closed_joints),
        closed_joints=closed_joints,
        held_object_pose=held_object_pose,
        qpos_changed=bool(closed_joints) or held_object_pose is not None,
        state_mutation=hooks.close_receptacle_state_mutation(
            bool(closed_joints),
            held_object_pose is not None,
        ),
        backend=hooks.backend,
    )


def robot_pose_state_mutation(held_object_changed: bool) -> str:
    parts = ["robot_base_qpos"]
    if held_object_changed:
        parts.append("held_object_freejoint_qpos")
    return "+".join(parts)


def open_receptacle_state_mutation(
    joints_changed: bool,
    robot_pose_changed: bool,
    held_object_changed: bool,
) -> str:
    parts = []
    if joints_changed:
        parts.append("mujoco_receptacle_joint_qpos")
    if robot_pose_changed:
        parts.append("robot_base_qpos")
    if held_object_changed:
        parts.append("held_object_freejoint_qpos")
    return "+".join(parts) if parts else "no_openable_joint"


def close_receptacle_state_mutation(
    joints_changed: bool,
    held_object_changed: bool,
) -> str:
    parts = []
    if joints_changed:
        parts.append("mujoco_receptacle_joint_qpos")
    if held_object_changed:
        parts.append("held_object_freejoint_qpos")
    return "+".join(parts) if parts else "no_openable_joint"


def _relative_delta(
    forward_m: float = 0.0,
    lateral_m: float = 0.0,
    yaw_delta_deg: float = 0.0,
) -> dict[str, float]:
    return {
        "forward_m": round(float(forward_m), 4),
        "lateral_m": round(float(lateral_m), 4),
        "yaw_delta_deg": round(float(yaw_delta_deg), 4),
    }


def _pose_after_relative_delta(
    pose: dict[str, Any],
    delta: dict[str, float],
) -> dict[str, Any]:
    yaw_rad = _pose_yaw_rad(pose)
    forward = delta["forward_m"]
    lateral = delta["lateral_m"]
    result = dict(pose)
    result["x"] = round(
        float(pose.get("x") or 0.0) + forward * math.cos(yaw_rad) - lateral * math.sin(yaw_rad),
        4,
    )
    result["y"] = round(
        float(pose.get("y") or 0.0) + forward * math.sin(yaw_rad) + lateral * math.cos(yaw_rad),
        4,
    )
    if "theta" in result:
        result["theta"] = round(
            float(result.get("theta") or 0.0) + math.radians(delta["yaw_delta_deg"]),
            6,
        )
    else:
        result["yaw_deg"] = round(_pose_yaw_deg(pose) + delta["yaw_delta_deg"], 4)
    result["pose_source"] = "relative_robot_frame"
    result["relative_pose_delta"] = dict(delta)
    return result


def _pose_yaw_rad(pose: dict[str, Any]) -> float:
    if pose.get("theta") is not None:
        return float(pose.get("theta") or 0.0)
    return math.radians(_pose_yaw_deg(pose))


def _pose_yaw_deg(pose: dict[str, Any]) -> float:
    if pose.get("yaw_deg") is not None:
        return float(pose.get("yaw_deg") or 0.0)
    return math.degrees(float(pose.get("theta") or 0.0))


def done_cleanup(
    state: dict[str, Any],
    reason: str,
    *,
    hooks: MolmoActionHooks,
) -> dict[str, Any]:
    hooks.count(state, "done")
    final_locations = hooks.read_locations(state)
    score = hooks.score(final_locations, state["private_manifest"])
    return hooks.ok(
        "done",
        reason=reason,
        cleanup_status=score["status"],
        score=score,
        final_locations=final_locations,
        final_containment=hooks.read_containment(state),
        tool_event_counts=state["tool_event_counts"],
        backend=hooks.backend,
    )
