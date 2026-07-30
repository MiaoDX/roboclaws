"""Isaac Lab backend runtime support."""

from __future__ import annotations

import argparse
import math
from dataclasses import dataclass
from typing import Any, Callable

from roboclaws.household.backend import HELD_LOCATION_ID
from roboclaws.household.scoring import score_cleanup
from roboclaws.household.semantic_acceptability import (
    annotate_score_with_semantic_acceptability,
)


@dataclass(frozen=True)
class IsaacWorkerCommandHooks:
    apply_object_location: Callable[..., Any]
    count: Callable[..., Any]
    dict_value: Callable[..., Any]
    error: Callable[..., Any]
    has_xy: Callable[..., Any]
    isaac_placement_diagnostic: Callable[..., Any]
    objects_by_id: Callable[..., Any]
    ok: Callable[..., Any]
    public_state: Callable[..., Any]
    receptacles_by_id: Callable[..., Any]
    record_semantic_pose_event: Callable[..., Any]
    record_waypoint_pose_event: Callable[..., Any]
    robot_pose_for_receptacle: Callable[..., Any]
    robot_pose_for_waypoint: Callable[..., Any]
    scenario_from_state: Callable[..., Any]
    write_state_from_state_arg: Callable[..., Any]


def observe(
    args: argparse.Namespace,
    state: dict[str, Any],
    *,
    hooks: IsaacWorkerCommandHooks,
) -> dict[str, Any]:
    del args
    hooks.count(state, "observe")
    hooks.write_state_from_state_arg(state)
    return hooks.ok(
        "observe",
        scenario=hooks.public_state(state),
        current_receptacle_id=state["current_receptacle_id"],
        held_object_id=state.get("held_object_id"),
        isaac_runtime=state["runtime"],
    )


def navigate_to_object(
    args: argparse.Namespace,
    state: dict[str, Any],
    *,
    hooks: IsaacWorkerCommandHooks,
) -> dict[str, Any]:
    hooks.count(state, "navigate_to_object")
    object_id = args.object_id
    if object_id not in hooks.objects_by_id(state):
        return hooks.error("navigate_to_object", "stale_reference", object_id=object_id)
    location_id = state["locations"].get(object_id)
    if location_id in {None, HELD_LOCATION_ID}:
        return hooks.error(
            "navigate_to_object",
            "object_not_at_public_location",
            object_id=object_id,
        )
    previous = state["current_receptacle_id"]
    state["current_receptacle_id"] = str(location_id)
    event = hooks.record_semantic_pose_event(
        state,
        tool="navigate_to_object",
        state_mutation="isaac_root_pose",
        object_id=object_id,
        receptacle_id=str(location_id),
        previous_location_id=previous,
        location_id=str(location_id),
    )
    hooks.write_state_from_state_arg(state)
    return hooks.ok(
        "navigate_to_object",
        object_id=object_id,
        source_receptacle_id=str(location_id),
        previous_receptacle_id=previous,
        location_id=str(location_id),
        robot_pose=hooks.robot_pose_for_receptacle(state, str(location_id)),
        state_mutation="isaac_root_pose",
        semantic_pose_event=event,
    )


def navigate_to_receptacle(
    args: argparse.Namespace,
    state: dict[str, Any],
    *,
    hooks: IsaacWorkerCommandHooks,
) -> dict[str, Any]:
    hooks.count(state, "navigate_to_receptacle")
    receptacle_id = args.receptacle_id
    if receptacle_id not in hooks.receptacles_by_id(state):
        return hooks.error(
            "navigate_to_receptacle",
            "stale_reference",
            receptacle_id=receptacle_id,
        )
    previous = state["current_receptacle_id"]
    state["current_receptacle_id"] = receptacle_id
    held_object_id = state.get("held_object_id")
    event = hooks.record_semantic_pose_event(
        state,
        tool="navigate_to_receptacle",
        state_mutation="isaac_root_pose",
        object_id=str(held_object_id or ""),
        receptacle_id=receptacle_id,
        previous_location_id=previous,
        location_id=receptacle_id,
    )
    hooks.write_state_from_state_arg(state)
    return hooks.ok(
        "navigate_to_receptacle",
        receptacle_id=receptacle_id,
        object_id=held_object_id,
        previous_receptacle_id=previous,
        robot_pose=hooks.robot_pose_for_receptacle(state, receptacle_id),
        state_mutation="isaac_root_pose",
        semantic_pose_event=event,
    )


def navigate_to_waypoint(
    args: argparse.Namespace,
    state: dict[str, Any],
    *,
    hooks: IsaacWorkerCommandHooks,
) -> dict[str, Any]:
    hooks.count(state, "navigate_to_waypoint")
    waypoint = hooks.dict_value(args.waypoint_json)
    robot_pose = hooks.robot_pose_for_waypoint(waypoint)
    if not hooks.has_xy(robot_pose):
        return hooks.error(
            "navigate_to_waypoint",
            "waypoint_pose_missing",
            waypoint_id=str(waypoint.get("waypoint_id") or ""),
        )
    previous_waypoint_id = str(state.get("current_waypoint_id") or "")
    previous_room_id = str(state.get("current_room_id") or "")
    waypoint_id = str(waypoint.get("waypoint_id") or "")
    room_id = str(waypoint.get("room_id") or "")
    fixture_ids = [str(item) for item in waypoint.get("fixture_ids") or [] if str(item)]
    state["current_waypoint_id"] = waypoint_id
    state["current_room_id"] = room_id
    if fixture_ids:
        state["current_receptacle_id"] = fixture_ids[0]
    event = hooks.record_waypoint_pose_event(
        state,
        waypoint=waypoint,
        robot_pose=robot_pose,
        previous_waypoint_id=previous_waypoint_id,
        previous_room_id=previous_room_id,
    )
    hooks.write_state_from_state_arg(state)
    return hooks.ok(
        "navigate_to_waypoint",
        waypoint_id=waypoint_id,
        room_id=room_id,
        fixture_ids=fixture_ids,
        previous_waypoint_id=previous_waypoint_id,
        previous_room_id=previous_room_id,
        robot_pose=robot_pose,
        state_mutation="isaac_waypoint_pose",
        semantic_pose_event=event,
        backend_pose_mutation_available=True,
    )


def navigate_to_relative_pose(
    args: argparse.Namespace,
    state: dict[str, Any],
    *,
    hooks: IsaacWorkerCommandHooks,
) -> dict[str, Any]:
    hooks.count(state, "navigate_to_relative_pose")
    requested = _relative_delta(args.forward_m, args.lateral_m, args.yaw_delta_deg)
    semantic_pose_state = state.get("semantic_pose_state") or {}
    previous_pose = semantic_pose_state.get("robot_pose") or state.get("robot_pose") or {}
    if not hooks.has_xy(previous_pose):
        return hooks.error(
            "navigate_to_relative_pose",
            "robot_pose_unavailable",
            status="blocked_capability",
            requested_delta=requested,
            applied_delta=_relative_delta(),
        )
    robot_pose = _pose_after_relative_delta(previous_pose, requested)
    state["robot_pose"] = robot_pose
    semantic_pose_state = dict(semantic_pose_state) if isinstance(semantic_pose_state, dict) else {}
    semantic_pose_state["robot_pose"] = robot_pose
    state["semantic_pose_state"] = semantic_pose_state
    state.setdefault("robot_trajectory", []).append(robot_pose)
    event = hooks.record_waypoint_pose_event(
        state,
        waypoint={
            "waypoint_id": str(state.get("current_waypoint_id") or "relative_pose"),
            "room_id": str(state.get("current_room_id") or ""),
        },
        robot_pose=robot_pose,
        previous_waypoint_id=str(state.get("current_waypoint_id") or ""),
        previous_room_id=str(state.get("current_room_id") or ""),
    )
    hooks.write_state_from_state_arg(state)
    return hooks.ok(
        "navigate_to_relative_pose",
        requested_delta=requested,
        applied_delta=requested,
        applied_forward_m=requested["forward_m"],
        applied_lateral_m=requested["lateral_m"],
        applied_yaw_delta_deg=requested["yaw_delta_deg"],
        frame_id="base_link",
        pose_source="relative_robot_frame",
        robot_pose=robot_pose,
        state_mutation="isaac_relative_robot_pose",
        semantic_pose_event=event,
        primitive_provenance="isaac_semantic_pose",
        backend_pose_mutation_available=True,
        clamped=False,
        clamp_metadata={"backend_limits_enforced": False},
        requires_reobserve=True,
    )


def pick(
    args: argparse.Namespace,
    state: dict[str, Any],
    *,
    hooks: IsaacWorkerCommandHooks,
) -> dict[str, Any]:
    hooks.count(state, "pick")
    object_id = args.object_id
    obj = hooks.objects_by_id(state).get(object_id)
    if obj is None:
        return hooks.error("pick", "stale_reference", object_id=object_id)
    if not obj.get("pickupable", True):
        return hooks.error("pick", "not_pickupable", object_id=object_id)
    if state.get("held_object_id") is not None:
        return hooks.error("pick", "already_holding", held_object_id=state["held_object_id"])
    previous_location_id = state["locations"][object_id]
    state["held_object_id"] = object_id
    state["locations"][object_id] = HELD_LOCATION_ID
    event = hooks.record_semantic_pose_event(
        state,
        tool="pick",
        state_mutation="isaac_prim_attach",
        object_id=object_id,
        receptacle_id=str(previous_location_id),
        previous_location_id=previous_location_id,
        location_id=HELD_LOCATION_ID,
    )
    hooks.write_state_from_state_arg(state)
    return hooks.ok(
        "pick",
        object_id=object_id,
        previous_location_id=previous_location_id,
        location_id=HELD_LOCATION_ID,
        state_mutation="isaac_prim_attach",
        semantic_pose_event=event,
    )


def open_receptacle(
    args: argparse.Namespace,
    state: dict[str, Any],
    *,
    hooks: IsaacWorkerCommandHooks,
) -> dict[str, Any]:
    hooks.count(state, "open_receptacle")
    receptacle_id = args.receptacle_id
    receptacle = hooks.receptacles_by_id(state).get(receptacle_id)
    if receptacle is None:
        return hooks.error("open_receptacle", "stale_reference", receptacle_id=receptacle_id)
    opened = "fridge" in str(receptacle.get("name", "")).lower()
    open_ids = set(state.get("open_receptacle_ids") or [])
    if opened:
        open_ids.add(receptacle_id)
    state["open_receptacle_ids"] = sorted(open_ids)
    event = hooks.record_semantic_pose_event(
        state,
        tool="open_receptacle",
        state_mutation="isaac_articulation_joint_pose",
        object_id=str(state.get("held_object_id") or ""),
        receptacle_id=receptacle_id,
        location_id=receptacle_id,
        articulation_open=opened,
        requested_open=True,
    )
    hooks.write_state_from_state_arg(state)
    return hooks.ok(
        "open_receptacle",
        receptacle_id=receptacle_id,
        object_id=state.get("held_object_id"),
        opened=opened,
        state_mutation="isaac_articulation_joint_pose",
        semantic_pose_event=event,
    )


def close_receptacle(
    args: argparse.Namespace,
    state: dict[str, Any],
    *,
    hooks: IsaacWorkerCommandHooks,
) -> dict[str, Any]:
    hooks.count(state, "close_receptacle")
    receptacle_id = args.receptacle_id
    if receptacle_id not in hooks.receptacles_by_id(state):
        return hooks.error("close_receptacle", "stale_reference", receptacle_id=receptacle_id)
    open_ids = set(state.get("open_receptacle_ids") or [])
    was_open = receptacle_id in open_ids
    open_ids.discard(receptacle_id)
    state["open_receptacle_ids"] = sorted(open_ids)
    event = hooks.record_semantic_pose_event(
        state,
        tool="close_receptacle",
        state_mutation="isaac_articulation_joint_pose",
        object_id=str(state.get("held_object_id") or ""),
        receptacle_id=receptacle_id,
        location_id=receptacle_id,
        articulation_open=False,
        was_open=was_open,
    )
    hooks.write_state_from_state_arg(state)
    return hooks.ok(
        "close_receptacle",
        receptacle_id=receptacle_id,
        object_id=state.get("held_object_id"),
        closed=was_open,
        state_mutation="isaac_articulation_joint_pose",
        semantic_pose_event=event,
    )


def place(
    args: argparse.Namespace,
    state: dict[str, Any],
    *,
    relation: str,
    hooks: IsaacWorkerCommandHooks,
) -> dict[str, Any]:
    tool = "place_inside" if relation == "inside" else "place"
    hooks.count(state, tool)
    receptacle_id = args.receptacle_id
    if receptacle_id not in hooks.receptacles_by_id(state):
        return hooks.error(tool, "stale_reference", receptacle_id=receptacle_id)
    object_id = state.get("held_object_id")
    if object_id is None:
        return hooks.error(tool, "not_holding")
    object_id = str(object_id)
    state["held_object_id"] = None
    state["current_receptacle_id"] = receptacle_id
    placement_resolution = hooks.apply_object_location(
        state,
        object_id=object_id,
        receptacle_id=receptacle_id,
        relation=relation,
        placement_index=len(state.get("placement_diagnostics") or []),
        source="cleanup_place",
    )
    diagnostic = hooks.isaac_placement_diagnostic(
        state=state,
        object_id=object_id,
        receptacle_id=receptacle_id,
        relation=relation,
        source="cleanup_place",
        placement_resolution=placement_resolution,
    )
    state.setdefault("placement_diagnostics", []).append(diagnostic)
    event = hooks.record_semantic_pose_event(
        state,
        tool=tool,
        state_mutation="isaac_prim_transform",
        object_id=object_id,
        receptacle_id=receptacle_id,
        previous_location_id=HELD_LOCATION_ID,
        location_id=receptacle_id,
        relation=relation,
        placement_support_status=diagnostic.get("placement_support_status"),
        direct_support_proven=diagnostic.get("direct_support_proven"),
        placement_contact_proof=diagnostic.get("contact_proof"),
        placement_resolution_source=diagnostic.get("resolution_source"),
    )
    hooks.write_state_from_state_arg(state)
    return hooks.ok(
        tool,
        object_id=object_id,
        receptacle_id=receptacle_id,
        location_id=receptacle_id,
        contained_in=receptacle_id if relation == "inside" else None,
        location_relation=relation,
        placement_diagnostic=diagnostic,
        placement_support_status=diagnostic.get("placement_support_status"),
        direct_support_proven=diagnostic.get("direct_support_proven"),
        state_mutation="isaac_prim_transform",
        semantic_pose_event=event,
    )


def done(
    args: argparse.Namespace,
    state: dict[str, Any],
    *,
    hooks: IsaacWorkerCommandHooks,
) -> dict[str, Any]:
    hooks.count(state, "done")
    scenario = hooks.scenario_from_state(state)
    score = score_cleanup(state["locations"], scenario.private_manifest)
    annotated_score = annotate_score_with_semantic_acceptability(
        score.to_dict(),
        scenario,
    )
    hooks.write_state_from_state_arg(state)
    return hooks.ok(
        "done",
        reason=args.reason,
        cleanup_status=score.status,
        score=annotated_score,
        final_locations=dict(state["locations"]),
        final_containment=dict(state.get("containment") or {}),
        tool_event_counts=dict(state.get("tool_event_counts") or {}),
    )


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
    yaw_rad = math.radians(float(pose.get("yaw_deg") or 0.0))
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
    result["yaw_deg"] = round(float(pose.get("yaw_deg") or 0.0) + delta["yaw_delta_deg"], 4)
    result["pose_source"] = "relative_robot_frame"
    result["relative_pose_delta"] = dict(delta)
    return result
