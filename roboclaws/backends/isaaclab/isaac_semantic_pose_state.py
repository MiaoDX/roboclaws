"""Isaac Lab backend runtime support."""

from __future__ import annotations

from typing import Any, Callable

type RobotPoseForReceptacle = Callable[[dict[str, Any], str], dict[str, Any]]
type SemanticObjectPoses = Callable[[dict[str, Any]], dict[str, dict[str, Any]]]
type SemanticArticulations = Callable[[dict[str, Any]], dict[str, dict[str, Any]]]
type PrimPathResolver = Callable[[dict[str, Any], str], str]

SEMANTIC_POSE_EVIDENCE_NOTE = (
    "Semantic cleanup primitives update backend JSON pose/articulation state "
    "against public USD prim handles. These edits are not rendered back into "
    "the Isaac USD stage and are not planner-backed manipulation proof."
)

WAYPOINT_POSE_EVIDENCE_NOTE = (
    "Semantic cleanup primitives update backend JSON pose/articulation state "
    "against public USD prim handles. Waypoint navigation updates the robot "
    "pose used by Isaac robot-view rendering, but it is not planner-backed "
    "navigation proof."
)


def initial_semantic_pose_state(
    *,
    scenario: Any,
    object_index: dict[str, Any],
    receptacle_index: dict[str, Any],
    scene_binding_diagnostics: dict[str, Any] | None,
    initial_receptacle_id: str,
    semantic_pose_state_from_backend_state: Callable[..., dict[str, Any]],
) -> dict[str, Any]:
    state = {
        "scenario": scenario.public_payload(),
        "locations": scenario.object_locations(),
        "containment": {},
        "held_object_id": None,
        "current_receptacle_id": initial_receptacle_id,
        "open_receptacle_ids": [],
        "object_index": object_index,
        "receptacle_index": receptacle_index,
        "scene_binding_diagnostics": scene_binding_diagnostics or {},
        "object_pose_overrides": {},
    }
    return semantic_pose_state_from_backend_state(state, transform_events=[])


def semantic_pose_state_from_backend_state(
    state: dict[str, Any],
    *,
    transform_events: list[dict[str, Any]],
    state_schema: str,
    state_source: str,
    primitive_provenance: str,
    robot_pose_for_receptacle: RobotPoseForReceptacle,
    semantic_object_poses_from_state: SemanticObjectPoses,
    semantic_articulations_from_state: SemanticArticulations,
) -> dict[str, Any]:
    return {
        "schema": state_schema,
        "state_source": state_source,
        "primitive_provenance": primitive_provenance,
        "rendered_to_usd": False,
        "planner_backed": False,
        "physical_robot": False,
        "semantic_pose_only": True,
        "robot_pose": robot_pose_for_receptacle(
            state,
            str(state.get("current_receptacle_id") or ""),
        ),
        "held_object_id": state.get("held_object_id"),
        "open_receptacle_ids": sorted(state.get("open_receptacle_ids") or []),
        "object_poses": semantic_object_poses_from_state(state),
        "articulations": semantic_articulations_from_state(state),
        "object_pose_overrides": dict(_dict(state.get("object_pose_overrides"))),
        "transform_events": transform_events,
        "evidence_note": SEMANTIC_POSE_EVIDENCE_NOTE,
    }


def record_semantic_pose_event(
    state: dict[str, Any],
    *,
    tool: str,
    state_mutation: str,
    event_schema: str,
    state_schema: str,
    state_source: str,
    primitive_provenance: str,
    robot_pose_for_receptacle: RobotPoseForReceptacle,
    semantic_object_poses_from_state: SemanticObjectPoses,
    semantic_articulations_from_state: SemanticArticulations,
    object_usd_prim_path: PrimPathResolver,
    receptacle_usd_prim_path: PrimPathResolver,
    object_id: str = "",
    receptacle_id: str = "",
    previous_location_id: str = "",
    location_id: str = "",
    relation: str = "",
    **extra: Any,
) -> dict[str, Any]:
    semantic_pose_state = _dict(state.get("semantic_pose_state"))
    events = [
        dict(item)
        for item in semantic_pose_state.get("transform_events", [])
        if isinstance(item, dict)
    ]
    robot_pose = robot_pose_for_receptacle(
        state,
        str(state.get("current_receptacle_id") or receptacle_id),
    )
    event = {
        "schema": event_schema,
        "sequence": len(events) + 1,
        "tool": tool,
        "state_mutation": state_mutation,
        "state_source": state_source,
        "primitive_provenance": primitive_provenance,
        "rendered_to_usd": False,
        "planner_backed": False,
        "physical_robot": False,
        "object_id": object_id,
        "object_usd_prim_path": object_usd_prim_path(state, object_id),
        "receptacle_id": receptacle_id,
        "receptacle_usd_prim_path": receptacle_usd_prim_path(state, receptacle_id),
        "previous_location_id": previous_location_id,
        "location_id": location_id,
        "location_relation": relation,
        "robot_pose": robot_pose,
    }
    event.update({key: value for key, value in extra.items() if value is not None})
    events.append(event)
    semantic_pose_state.update(
        semantic_pose_payload(
            state,
            state_schema=state_schema,
            state_source=state_source,
            primitive_provenance=primitive_provenance,
            robot_pose=robot_pose,
            semantic_object_poses_from_state=semantic_object_poses_from_state,
            semantic_articulations_from_state=semantic_articulations_from_state,
            transform_events=events,
            evidence_note=SEMANTIC_POSE_EVIDENCE_NOTE,
        )
    )
    state["semantic_pose_state"] = semantic_pose_state
    return event


def record_waypoint_pose_event(
    state: dict[str, Any],
    *,
    waypoint: dict[str, Any],
    robot_pose: dict[str, Any],
    event_schema: str,
    state_schema: str,
    state_source: str,
    primitive_provenance: str,
    semantic_object_poses_from_state: SemanticObjectPoses,
    semantic_articulations_from_state: SemanticArticulations,
    previous_waypoint_id: str = "",
    previous_room_id: str = "",
) -> dict[str, Any]:
    semantic_pose_state = _dict(state.get("semantic_pose_state"))
    events = [
        dict(item)
        for item in semantic_pose_state.get("transform_events", [])
        if isinstance(item, dict)
    ]
    waypoint_id = str(waypoint.get("waypoint_id") or "")
    room_id = str(waypoint.get("room_id") or "")
    fixture_ids = [str(item) for item in waypoint.get("fixture_ids") or [] if str(item)]
    event = {
        "schema": event_schema,
        "sequence": len(events) + 1,
        "tool": "navigate_to_waypoint",
        "state_mutation": "isaac_waypoint_pose",
        "state_source": state_source,
        "primitive_provenance": primitive_provenance,
        "rendered_to_usd": False,
        "planner_backed": False,
        "physical_robot": False,
        "waypoint_id": waypoint_id,
        "room_id": room_id,
        "fixture_ids": fixture_ids,
        "previous_waypoint_id": previous_waypoint_id,
        "previous_room_id": previous_room_id,
        "robot_pose": dict(robot_pose),
    }
    events.append(event)
    semantic_pose_state.update(
        semantic_pose_payload(
            state,
            state_schema=state_schema,
            state_source=state_source,
            primitive_provenance=primitive_provenance,
            robot_pose=dict(robot_pose),
            semantic_object_poses_from_state=semantic_object_poses_from_state,
            semantic_articulations_from_state=semantic_articulations_from_state,
            transform_events=events,
            evidence_note=WAYPOINT_POSE_EVIDENCE_NOTE,
        )
    )
    state["semantic_pose_state"] = semantic_pose_state
    return event


def semantic_pose_payload(
    state: dict[str, Any],
    *,
    state_schema: str,
    state_source: str,
    primitive_provenance: str,
    robot_pose: dict[str, Any],
    semantic_object_poses_from_state: SemanticObjectPoses,
    semantic_articulations_from_state: SemanticArticulations,
    transform_events: list[dict[str, Any]],
    evidence_note: str,
) -> dict[str, Any]:
    return {
        "schema": state_schema,
        "state_source": state_source,
        "primitive_provenance": primitive_provenance,
        "rendered_to_usd": False,
        "planner_backed": False,
        "physical_robot": False,
        "semantic_pose_only": True,
        "robot_pose": robot_pose,
        "held_object_id": state.get("held_object_id"),
        "open_receptacle_ids": sorted(state.get("open_receptacle_ids") or []),
        "object_poses": semantic_object_poses_from_state(state),
        "articulations": semantic_articulations_from_state(state),
        "object_pose_overrides": dict(_dict(state.get("object_pose_overrides"))),
        "transform_events": transform_events,
        "evidence_note": evidence_note,
    }


def _dict(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}
