from __future__ import annotations

import math
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from roboclaws.household.backend_contract import CleanupBackendSession
from roboclaws.household.map_build_scan_profile import (
    MapBuildScanProfile,
)
from roboclaws.household.map_build_scan_profile import (
    map_build_scan_profile as build_map_build_scan_profile,
)
from roboclaws.household.realworld_contract import (
    CAMERA_MODEL_POLICY_MODE,
    CAMERA_MODEL_POLICY_NAME,
    DETERMINISTIC_SWEEP_POLICY,
    RAW_FPV_ONLY_MODE,
    RealWorldCleanupContract,
)
from roboclaws.household.robot_view_camera_control import (
    ROBOT_VIEW_CAMERA_CONTROL_CONTRACT_SCHEMA,
)
from roboclaws.household.semantic_acceptability import (
    annotate_score_with_semantic_acceptability,
)
from roboclaws.household.skill_scratchpad import empty_skill_scratchpad

MAP_BUILD_POLICY = "map_build_baseline"

ToolCaller = Callable[..., dict[str, Any]]
ObservationPostprocessor = Callable[..., dict[str, Any]]
WaypointFilter = Callable[[list[dict[str, Any]]], list[dict[str, Any]]]
StopAfterWaypoint = Callable[[RealWorldCleanupContract], bool]


@dataclass(frozen=True)
class DirectHouseholdEpisodePolicy:
    policy_name: str
    artifact_kind: str
    cleanup_actions_enabled: bool

    @property
    def requires_map_artifacts(self) -> bool:
        return self.artifact_kind == "runtime_metric_map"


@dataclass(frozen=True)
class DirectHouseholdEpisodePolicyHooks:
    call_tool: ToolCaller
    attach_raw_fpv_robot_view: ObservationPostprocessor
    view_index_after_raw_fpv: Callable[[list[dict[str, Any]], int], int]
    detections_for_policy: Callable[..., list[dict[str, Any]]]
    maybe_clean_visible_object: Callable[..., int]
    map_build_done: Callable[..., dict[str, Any]]
    failed_score: Callable[[RealWorldCleanupContract], dict[str, Any]]


def record_direct_household_episode_robot_view(
    *,
    base_contract: CleanupBackendSession,
    robot_view_steps: list[dict[str, Any]],
    output_dir: Path,
    view_index: int,
    record_robot_views: bool,
    label_suffix: str,
    action: str,
) -> int:
    if not record_robot_views:
        return view_index
    return base_contract.record_robot_view_step(
        steps=robot_view_steps,
        output_dir=output_dir,
        index=view_index,
        label_suffix=label_suffix,
        action=action,
    )


def direct_household_episode_policy(
    *,
    intent: str,
    perception_mode: str,
) -> DirectHouseholdEpisodePolicy:
    if intent == "map-build":
        return DirectHouseholdEpisodePolicy(
            policy_name=MAP_BUILD_POLICY,
            artifact_kind="runtime_metric_map",
            cleanup_actions_enabled=False,
        )
    if perception_mode == CAMERA_MODEL_POLICY_MODE:
        policy_name = CAMERA_MODEL_POLICY_NAME
    else:
        policy_name = DETERMINISTIC_SWEEP_POLICY
    return DirectHouseholdEpisodePolicy(
        policy_name=policy_name,
        artifact_kind="household_episode",
        cleanup_actions_enabled=True,
    )


def direct_household_episode_scratchpad(policy_name: str) -> dict[str, Any]:
    scratchpad = empty_skill_scratchpad(
        note="Deterministic direct demo scratchpad; cleanup_worklist is authoritative."
    )
    scratchpad["policy"] = policy_name
    return scratchpad


def run_direct_household_episode_scan(
    *,
    trace_events: list[dict[str, Any]],
    started_at: float,
    contract: RealWorldCleanupContract,
    base_contract: CleanupBackendSession,
    metric_map: dict[str, Any],
    static_fixture_projection: dict[str, Any],
    robot_view_steps: list[dict[str, Any]],
    output_dir: Path,
    view_index: int,
    record_robot_views: bool,
    episode_policy: DirectHouseholdEpisodePolicy,
    perception_mode: str,
    planner_proof_evidence: dict[str, Any] | None,
    agent_scratchpad: dict[str, Any],
    hooks: DirectHouseholdEpisodePolicyHooks,
    map_build_scan_profile: MapBuildScanProfile | None = None,
    waypoint_filter: WaypointFilter | None = None,
    stop_after_waypoint: StopAfterWaypoint | None = None,
) -> int:
    scan_profile = map_build_scan_profile or default_map_build_scan_profile()
    handled_handles: set[str] = set()
    pending_detections: dict[str, dict[str, Any]] = {}
    waypoints = [dict(item) for item in metric_map["inspection_waypoints"]]
    if waypoint_filter is not None:
        waypoints = waypoint_filter(waypoints)
    for waypoint in waypoints:
        view_index = _scan_direct_cleanup_waypoint(
            trace_events=trace_events,
            started_at=started_at,
            contract=contract,
            base_contract=base_contract,
            waypoint=waypoint,
            static_fixture_projection=static_fixture_projection,
            robot_view_steps=robot_view_steps,
            output_dir=output_dir,
            view_index=view_index,
            record_robot_views=record_robot_views,
            episode_policy=episode_policy,
            perception_mode=perception_mode,
            planner_proof_evidence=planner_proof_evidence,
            agent_scratchpad=agent_scratchpad,
            handled_handles=handled_handles,
            pending_detections=pending_detections,
            hooks=hooks,
            map_build_scan_profile=scan_profile,
        )
        if stop_after_waypoint is not None and stop_after_waypoint(contract):
            break
    if episode_policy.cleanup_actions_enabled:
        return _clean_pending_detections(
            trace_events=trace_events,
            started_at=started_at,
            contract=contract,
            base_contract=base_contract,
            static_fixture_projection=static_fixture_projection,
            robot_view_steps=robot_view_steps,
            output_dir=output_dir,
            view_index=view_index,
            record_robot_views=record_robot_views,
            planner_proof_evidence=planner_proof_evidence,
            agent_scratchpad=agent_scratchpad,
            handled_handles=handled_handles,
            pending_detections=pending_detections,
            perception_mode=perception_mode,
            hooks=hooks,
        )
    return view_index


def default_map_build_scan_profile() -> MapBuildScanProfile:
    return build_map_build_scan_profile()


def _scan_direct_cleanup_waypoint(
    *,
    trace_events: list[dict[str, Any]],
    started_at: float,
    contract: RealWorldCleanupContract,
    base_contract: CleanupBackendSession,
    waypoint: dict[str, Any],
    static_fixture_projection: dict[str, Any],
    robot_view_steps: list[dict[str, Any]],
    output_dir: Path,
    view_index: int,
    record_robot_views: bool,
    episode_policy: DirectHouseholdEpisodePolicy,
    perception_mode: str,
    planner_proof_evidence: dict[str, Any] | None,
    agent_scratchpad: dict[str, Any],
    handled_handles: set[str],
    pending_detections: dict[str, dict[str, Any]],
    hooks: DirectHouseholdEpisodePolicyHooks,
    map_build_scan_profile: MapBuildScanProfile,
) -> int:
    waypoint_id = str(waypoint["waypoint_id"])
    hooks.call_tool(
        trace_events,
        started_at,
        "navigate_to_waypoint",
        {"waypoint_id": waypoint_id},
        lambda selected=waypoint_id: contract.navigate_to_waypoint(selected),
    )
    detections, view_index = _observe_direct_cleanup_waypoint(
        trace_events=trace_events,
        started_at=started_at,
        contract=contract,
        base_contract=base_contract,
        robot_view_steps=robot_view_steps,
        output_dir=output_dir,
        view_index=view_index,
        record_robot_views=record_robot_views,
        episode_policy=episode_policy,
        perception_mode=perception_mode,
        hooks=hooks,
        map_build_scan_profile=map_build_scan_profile,
    )
    if not episode_policy.cleanup_actions_enabled:
        return view_index
    return _handle_direct_cleanup_detections(
        trace_events=trace_events,
        started_at=started_at,
        contract=contract,
        base_contract=base_contract,
        detections=detections,
        static_fixture_projection=static_fixture_projection,
        robot_view_steps=robot_view_steps,
        output_dir=output_dir,
        view_index=view_index,
        record_robot_views=record_robot_views,
        planner_proof_evidence=planner_proof_evidence,
        agent_scratchpad=agent_scratchpad,
        handled_handles=handled_handles,
        pending_detections=pending_detections,
        perception_mode=perception_mode,
        hooks=hooks,
    )


def _observe_direct_cleanup_waypoint(
    *,
    trace_events: list[dict[str, Any]],
    started_at: float,
    contract: RealWorldCleanupContract,
    base_contract: CleanupBackendSession,
    robot_view_steps: list[dict[str, Any]],
    output_dir: Path,
    view_index: int,
    record_robot_views: bool,
    episode_policy: DirectHouseholdEpisodePolicy,
    perception_mode: str,
    hooks: DirectHouseholdEpisodePolicyHooks,
    map_build_scan_profile: MapBuildScanProfile,
) -> tuple[list[dict[str, Any]], int]:
    detections = []
    body_heading_deg = 0.0
    camera_schedule = _camera_schedule_for_direct_scan(
        requires_map_artifacts=episode_policy.requires_map_artifacts,
        scan_profile=map_build_scan_profile,
    )
    for camera_index, camera_step in enumerate(camera_schedule):
        if episode_policy.requires_map_artifacts and camera_index > 0:
            hooks.call_tool(
                trace_events,
                started_at,
                "adjust_camera",
                dict(camera_step),
                lambda step=camera_step: contract.adjust_camera(**step),
            )
        observation = hooks.call_tool(
            trace_events,
            started_at,
            "observe",
            {},
            contract.observe,
            postprocess=lambda response: _attach_direct_raw_fpv_observation_evidence(
                response=hooks.attach_raw_fpv_robot_view(
                    response=response,
                    contract=contract,
                    base_contract=base_contract,
                    robot_view_steps=robot_view_steps,
                    output_dir=output_dir,
                    view_index_ref=[view_index],
                    record_robot_views=record_robot_views,
                ),
                contract=contract,
                body_heading_deg=body_heading_deg,
            ),
        )
        view_index = hooks.view_index_after_raw_fpv(robot_view_steps, view_index)
        detections.extend(
            hooks.detections_for_policy(
                trace_events=trace_events,
                started_at=started_at,
                contract=contract,
                observation=observation,
                perception_mode=perception_mode,
            )
        )
    uses_body_turn_scan = episode_policy.requires_map_artifacts or (
        perception_mode == RAW_FPV_ONLY_MODE
    )
    if uses_body_turn_scan and map_build_scan_profile.uses_robot_body_turns:
        turn_count = map_build_scan_profile.body_turn_count_per_waypoint
        if perception_mode == RAW_FPV_ONLY_MODE and not episode_policy.requires_map_artifacts:
            turn_count = min(3, turn_count)
        for turn_index in range(turn_count):
            turn_response = hooks.call_tool(
                trace_events,
                started_at,
                "navigate_to_relative_pose",
                {
                    "forward_m": 0.0,
                    "lateral_m": 0.0,
                    "yaw_delta_deg": map_build_scan_profile.body_turn_yaw_delta_deg,
                    "scan_profile": map_build_scan_profile.profile_id,
                    "turn_index": turn_index + 1,
                },
                lambda yaw=map_build_scan_profile.body_turn_yaw_delta_deg: (
                    contract.navigate_to_relative_pose(
                        forward_m=0.0,
                        lateral_m=0.0,
                        yaw_delta_deg=yaw,
                    )
                ),
            )
            if not turn_response.get("ok"):
                raise RuntimeError(
                    "map-build scan profile "
                    f"{map_build_scan_profile.profile_id!r} requires body-turn "
                    "navigate_to_relative_pose, but backend returned "
                    f"{turn_response.get('status') or turn_response.get('error_reason')}"
                )
            applied_delta = turn_response.get("applied_delta") or {}
            body_heading_deg = (
                body_heading_deg + float(applied_delta.get("yaw_delta_deg") or 0.0)
            ) % 360.0
            observation = hooks.call_tool(
                trace_events,
                started_at,
                "observe",
                {"scan_profile": map_build_scan_profile.profile_id, "turn_index": turn_index + 1},
                contract.observe,
                postprocess=lambda response: _attach_direct_raw_fpv_observation_evidence(
                    response=hooks.attach_raw_fpv_robot_view(
                        response=response,
                        contract=contract,
                        base_contract=base_contract,
                        robot_view_steps=robot_view_steps,
                        output_dir=output_dir,
                        view_index_ref=[view_index],
                        record_robot_views=record_robot_views,
                    ),
                    contract=contract,
                    body_heading_deg=body_heading_deg,
                ),
            )
            view_index = hooks.view_index_after_raw_fpv(robot_view_steps, view_index)
            detections.extend(
                hooks.detections_for_policy(
                    trace_events=trace_events,
                    started_at=started_at,
                    contract=contract,
                    observation=observation,
                    perception_mode=perception_mode,
                )
            )
    return detections, view_index


def _attach_direct_raw_fpv_observation_evidence(
    *,
    response: dict[str, Any],
    contract: RealWorldCleanupContract,
    body_heading_deg: float,
) -> dict[str, Any]:
    raw = response.get("raw_fpv_observation")
    if not isinstance(raw, dict) or not response.get("ok"):
        return response
    if isinstance(raw.get("camera_control_contract"), dict):
        return response
    observation_id = str(raw.get("observation_id") or "")
    if not observation_id:
        return response
    attached = contract.attach_raw_fpv_observation_artifact(
        observation_id,
        views={},
        camera_control_contract={
            "schema": ROBOT_VIEW_CAMERA_CONTROL_CONTRACT_SCHEMA,
            "status": "direct_runner_action_derived_pose",
            "camera_control_api": None,
            "camera_model": "direct_runner_action_derived_pose",
            "same_pose_api": False,
            "robot_pose": {
                "pose_source": "relative_robot_frame",
                "theta": math.radians(body_heading_deg),
            },
        },
    )
    if attached is None:
        return response
    updated = dict(response)
    updated["raw_fpv_observation"] = attached
    return updated


def _camera_schedule_for_direct_scan(
    *,
    requires_map_artifacts: bool,
    scan_profile: MapBuildScanProfile,
) -> tuple[dict[str, float], ...]:
    if requires_map_artifacts:
        return scan_profile.camera_schedule
    return ({"yaw_delta_deg": 0.0, "pitch_delta_deg": 0.0},)


def _handle_direct_cleanup_detections(
    *,
    trace_events: list[dict[str, Any]],
    started_at: float,
    contract: RealWorldCleanupContract,
    base_contract: CleanupBackendSession,
    detections: list[dict[str, Any]],
    static_fixture_projection: dict[str, Any],
    robot_view_steps: list[dict[str, Any]],
    output_dir: Path,
    view_index: int,
    record_robot_views: bool,
    planner_proof_evidence: dict[str, Any] | None,
    agent_scratchpad: dict[str, Any],
    handled_handles: set[str],
    pending_detections: dict[str, dict[str, Any]],
    perception_mode: str,
    hooks: DirectHouseholdEpisodePolicyHooks,
) -> int:
    for detection in detections:
        pending_detections[str(detection["object_id"])] = dict(detection)
    return view_index


def _clean_direct_cleanup_detections(
    *,
    trace_events: list[dict[str, Any]],
    started_at: float,
    contract: RealWorldCleanupContract,
    base_contract: CleanupBackendSession,
    detections: list[dict[str, Any]],
    static_fixture_projection: dict[str, Any],
    robot_view_steps: list[dict[str, Any]],
    output_dir: Path,
    view_index: int,
    record_robot_views: bool,
    planner_proof_evidence: dict[str, Any] | None,
    agent_scratchpad: dict[str, Any],
    handled_handles: set[str],
    perception_mode: str,
    hooks: DirectHouseholdEpisodePolicyHooks,
) -> int:
    for detection in detections:
        view_index = hooks.maybe_clean_visible_object(
            trace_events=trace_events,
            started_at=started_at,
            contract=contract,
            base_contract=base_contract,
            detection=detection,
            static_fixture_projection=static_fixture_projection,
            robot_view_steps=robot_view_steps,
            output_dir=output_dir,
            view_index=view_index,
            record_robot_views=record_robot_views,
            planner_proof_evidence=planner_proof_evidence,
            agent_scratchpad=agent_scratchpad,
            handled_handles=handled_handles,
            perception_mode=perception_mode,
        )
    return view_index


def _clean_pending_detections(
    *,
    trace_events: list[dict[str, Any]],
    started_at: float,
    contract: RealWorldCleanupContract,
    base_contract: CleanupBackendSession,
    static_fixture_projection: dict[str, Any],
    robot_view_steps: list[dict[str, Any]],
    output_dir: Path,
    view_index: int,
    record_robot_views: bool,
    planner_proof_evidence: dict[str, Any] | None,
    agent_scratchpad: dict[str, Any],
    handled_handles: set[str],
    pending_detections: dict[str, dict[str, Any]],
    perception_mode: str,
    hooks: DirectHouseholdEpisodePolicyHooks,
) -> int:
    view_index = _clean_direct_cleanup_detections(
        trace_events=trace_events,
        started_at=started_at,
        contract=contract,
        base_contract=base_contract,
        detections=list(pending_detections.values()),
        static_fixture_projection=static_fixture_projection,
        robot_view_steps=robot_view_steps,
        output_dir=output_dir,
        view_index=view_index,
        record_robot_views=record_robot_views,
        planner_proof_evidence=planner_proof_evidence,
        agent_scratchpad=agent_scratchpad,
        handled_handles=handled_handles,
        perception_mode=perception_mode,
        hooks=hooks,
    )
    while True:
        newly_observed = _unhandled_worklist_detections(
            contract,
            handled_handles=handled_handles,
        )
        if not newly_observed:
            return view_index
        view_index = _clean_direct_cleanup_detections(
            trace_events=trace_events,
            started_at=started_at,
            contract=contract,
            base_contract=base_contract,
            detections=newly_observed,
            static_fixture_projection=static_fixture_projection,
            robot_view_steps=robot_view_steps,
            output_dir=output_dir,
            view_index=view_index,
            record_robot_views=record_robot_views,
            planner_proof_evidence=planner_proof_evidence,
            agent_scratchpad=agent_scratchpad,
            handled_handles=handled_handles,
            perception_mode=perception_mode,
            hooks=hooks,
        )


def _unhandled_worklist_detections(
    contract: RealWorldCleanupContract,
    *,
    handled_handles: set[str],
) -> list[dict[str, Any]]:
    worklist = contract.cleanup_worklist_payload(
        static_fixture_projection=contract.static_fixture_projection()
    )
    detections = []
    for item in worklist.get("objects", []):
        handle = str(item.get("object_id") or "")
        if not handle or handle in handled_handles or item.get("state") != "pending":
            continue
        inspected = contract.inspect_visible_object(handle)
        detection = inspected.get("detection") if inspected.get("ok") else None
        if isinstance(detection, dict):
            detections.append(dict(detection))
        else:
            handled_handles.add(handle)
            contract._mark_visual_scan_unresolved(  # noqa: SLF001
                handle,
                reason="worklist_candidate_not_inspectable",
            )
    return detections


def complete_direct_household_episode(
    *,
    trace_events: list[dict[str, Any]],
    started_at: float,
    contract: RealWorldCleanupContract,
    base_contract: CleanupBackendSession,
    episode_policy: DirectHouseholdEpisodePolicy,
    hooks: DirectHouseholdEpisodePolicyHooks,
) -> dict[str, Any]:
    reason = f"{episode_policy.policy_name} complete"
    done = hooks.call_tool(
        trace_events,
        started_at,
        "done",
        {"reason": reason},
        lambda: (
            hooks.map_build_done(contract, base_contract, reason)
            if episode_policy.requires_map_artifacts
            else contract.done(reason)
        ),
    )
    if "score" in done:
        return done
    return _done_with_failed_score(
        contract=contract,
        base_contract=base_contract,
        done=done,
        reason=f"{episode_policy.policy_name} incomplete",
        hooks=hooks,
    )


def _done_with_failed_score(
    *,
    contract: RealWorldCleanupContract,
    base_contract: CleanupBackendSession,
    done: dict[str, Any],
    reason: str,
    hooks: DirectHouseholdEpisodePolicyHooks,
) -> dict[str, Any]:
    base_done = base_contract.done(reason=reason)
    score = dict(base_done.get("score") or {})
    final_locations = base_contract.final_locations(base_done.get("final_locations"))
    if score:
        score = annotate_score_with_semantic_acceptability(score, contract.scenario)
        metrics = contract._realworld_metrics(score, final_locations)  # noqa: SLF001
        score.update(metrics)
    else:
        score = hooks.failed_score(contract)
    return {
        **done,
        "cleanup_status": "failed",
        "score": score,
        "final_locations": final_locations,
        "final_containment": base_done.get("final_containment", {}),
        "tool_event_counts": base_done.get("tool_event_counts", {}),
    }
