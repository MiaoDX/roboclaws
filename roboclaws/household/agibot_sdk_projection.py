"""Agibot public export projection, pilot trace, and readiness evidence."""

from __future__ import annotations

import time
from pathlib import Path
from typing import Any

from roboclaws.household import agent_view as agent_view_module
from roboclaws.household import profiles as evidence_profiles
from roboclaws.household.agibot_operator_gates import (
    human_takeover_stop_required,
    operator_localization_gate,
    operator_run_enablement_gate,
)
from roboclaws.household.agibot_sdk_contract import (
    AGIBOT_GDK_NORMAL_NAVI_PROVENANCE,
    AGIBOT_HEAD_COLOR_CAMERA_PROVENANCE,
    BLOCKED_MANIPULATION_TOOLS,
)
from roboclaws.household.household_runtime_contract import (
    CLEANUP_WORKLIST_SCHEMA,
    REALWORLD_CONTRACT,
    RUNTIME_METRIC_MAP_SCHEMA,
    forbidden_agent_view_keys,
)
from roboclaws.household.manipulation_contract import BLOCKED_CAPABILITY_PROVENANCE
from roboclaws.household.types import CleanupScenario
from roboclaws.mcp.profiles import (
    HOUSEHOLD_EPISODE_PROFILE,
    HOUSEHOLD_MANIPULATION_PROFILE,
    HOUSEHOLD_WORLD_PROFILE,
)


def _relpath(path: Path | str, root: Path) -> str:
    path = Path(path)
    try:
        return path.relative_to(root).as_posix()
    except ValueError:
        return str(path)


def _readiness_payload(
    *,
    context: dict[str, Any],
    metric_map: dict[str, Any],
    static_fixture_projection: dict[str, Any],
    observation: dict[str, Any],
    navigation: dict[str, Any],
    manipulation_results: list[dict[str, Any]],
    real_movement_enabled: bool,
) -> dict[str, Any]:
    all_manipulation_blocked = all(
        item.get("primitive_provenance") == BLOCKED_CAPABILITY_PROVENANCE
        and item.get("physical_cleanup_ready") is False
        for item in manipulation_results
    )
    navigation_complete = bool(navigation.get("ok"))
    observation_complete = bool(observation.get("ok"))
    complete = bool(navigation_complete and observation_complete and all_manipulation_blocked)
    backend = str(navigation.get("navigation_backend") or BLOCKED_CAPABILITY_PROVENANCE)
    pose_source = str(navigation.get("pose_source") or "")
    localization_gate = operator_localization_gate(context)
    run_gate = operator_run_enablement_gate(context, movement_enabled=real_movement_enabled)
    return {
        "schema": "real_robot_readiness_v1",
        "status": "physical_agibot_navigation_pilot_complete"
        if complete
        else "physical_agibot_navigation_pilot_rehearsal",
        "real_robot_ready": False,
        "navigation_perception_ready": complete,
        "backend_variant": evidence_profiles.AGIBOT_GDK_BACKEND_VARIANT,
        "movement_enabled": real_movement_enabled,
        "map_bundle_schema": metric_map.get("schema", ""),
        "map_bundle_fields_present": _map_fields_present(metric_map),
        "pose_stamped_waypoints": _pose_stamped_waypoints_present(metric_map),
        "static_fixture_projection": (
            static_fixture_projection.get("schema") == "static_fixture_projection_v1"
            and static_fixture_projection.get("contains_runtime_observations") is False
        ),
        "policy_view_chase_excluded": True,
        "report_only_simulation_view_count": 0,
        "report_only_simulation_view_label": "not_simulated",
        "navigation_backend_summary": {backend: 1},
        "pose_source_summary": {pose_source: 1} if pose_source else {},
        "semantic_navigation_only": False,
        "sim_costmap_route_validation": False,
        "physical_navigation_pilot": True,
        "physical_cleanup_ready": False,
        "inspection_waypoint_attempt_count": 1,
        "inspection_waypoint_total": len(metric_map.get("inspection_waypoints") or []),
        "fixture_preferred_waypoint_attempt_count": 0,
        "fixture_total": len(_fixtures(static_fixture_projection)),
        "reached_waypoint_count": 1 if navigation_complete else 0,
        "observed_reached_waypoint_count": 1 if observation_complete else 0,
        "observed_reached_waypoint_rate": 1.0 if complete else 0.0,
        "observed_waypoint_ids": [str(navigation.get("waypoint_id") or "")]
        if observation_complete
        else [],
        "manipulation_blocked": all_manipulation_blocked,
        "blocked_capabilities": list(BLOCKED_MANIPULATION_TOOLS),
        "operator_localization_gate": localization_gate,
        "operator_run_enablement_gate": run_gate,
        "human_takeover_stop": human_takeover_stop_required(observation, navigation),
        "public_contract_note": (
            "AgiBot Navigation + Perception Pilot: Roboclaws keeps the public "
            "household tool boundary stable while SDK runner artifacts own "
            "backend-specific GDK evidence."
        ),
    }


def _record(
    trace_events: list[dict[str, Any]],
    started_at: float,
    tool: str,
    arguments: dict[str, Any],
    response: dict[str, Any],
) -> None:
    elapsed = time.time() - started_at
    trace_events.append(
        {
            "tool": tool,
            "event": "request",
            "arguments": arguments,
            "wallclock_elapsed": elapsed,
        }
    )
    trace_events.append(
        {
            "tool": tool,
            "event": "response",
            "response": response,
            "wallclock_elapsed": time.time() - started_at,
        }
    )


def _observation_policy_progress(response: dict[str, Any]) -> str:
    camera = str(
        response.get("policy_observation_camera")
        or response.get("would_capture_camera")
        or "head_color"
    )
    if response.get("ok"):
        return f"Captured robot-local {camera} policy observation."
    if response.get("failure_type") == "live_camera_capture_not_enabled":
        return f"Dry-run observed {camera} policy boundary without calling live Agibot camera APIs."
    summary = str(response.get("backend_error_summary") or response.get("failure_type") or "")
    return f"Observation did not complete: {summary or 'no backend evidence'}."


def _navigation_policy_progress(
    response: dict[str, Any],
    *,
    waypoint_id: str,
    real_movement_enabled: bool,
) -> str:
    status = str(response.get("navigation_status") or response.get("status") or "")
    if response.get("ok"):
        return f"Visited public waypoint {waypoint_id} with Agibot GDK navigation evidence."
    if status == "dry_run_not_executed" or not real_movement_enabled:
        return (
            "Dry-run blocked by movement gate: "
            f"public waypoint {waypoint_id} was selected but no Pnc.normal_navi call was made."
        )
    summary = str(response.get("backend_error_summary") or response.get("failure_type") or status)
    return f"Public waypoint {waypoint_id} was not reached: {summary}."


def _skipped_waypoint_policy_events(
    *,
    policy_events: list[dict[str, Any]],
    metric_map: dict[str, Any],
    selected_waypoint_id: str,
) -> list[dict[str, Any]]:
    skipped_events: list[dict[str, Any]] = []
    for waypoint in metric_map.get("inspection_waypoints") or []:
        if not isinstance(waypoint, dict):
            continue
        waypoint_id = str(waypoint.get("waypoint_id") or "")
        if not waypoint_id or waypoint_id == selected_waypoint_id:
            continue
        skipped_events.append(
            _policy_event(
                len(policy_events) + len(skipped_events),
                {
                    "tool": "navigate_to_waypoint",
                    "waypoint_id": waypoint_id,
                    "fixture_id": waypoint.get("fixture_id", ""),
                    "status": "skipped",
                    "navigation_backend": waypoint.get("navigation_backend", ""),
                },
                "inspection_waypoint",
                decision="skip_public_waypoint",
                progress=(
                    f"Skipped public waypoint {waypoint_id}: "
                    "the pilot slice visits one generated/public waypoint before review."
                ),
                reason=(
                    "The first Agibot pilot keeps movement evidence bounded so the operator "
                    "can review each generated waypoint before broadening the route."
                ),
            )
        )
    return skipped_events


def _policy_event(
    index: int,
    response: dict[str, Any],
    role: str,
    *,
    decision: str = "",
    progress: str = "",
    reason: str = "",
) -> dict[str, Any]:
    event = {
        "index": index + 1,
        "tool": response.get("tool", ""),
        "role": role,
        "waypoint_id": response.get("waypoint_id", ""),
        "object_id": response.get("object_id", ""),
        "fixture_id": response.get("fixture_id", ""),
        "navigation_backend": response.get("navigation_backend", ""),
        "status": response.get("status") or response.get("navigation_status", ""),
    }
    if decision:
        event["decision"] = decision
    if progress:
        event["progress"] = progress
    if reason:
        event["reason"] = reason
    return event


def _subphase_reports(results: list[dict[str, Any]], run_dir: Path) -> list[dict[str, Any]]:
    reports = []
    for result in results:
        report_path = Path(str(result.get("report_path") or ""))
        reports.append(
            {
                "stage": result.get("stage", ""),
                "status": result.get("status", ""),
                "ok": result.get("ok", False),
                "report": _relpath(report_path, run_dir),
                "run_result": _relpath(report_path.with_name("run_result.json"), run_dir),
            }
        )
    return reports


def _agent_view_from_agibot_export(
    *,
    metric_map: dict[str, Any],
    static_fixture_projection: dict[str, Any],
    vendor_agent_view: dict[str, Any],
) -> dict[str, Any]:
    runtime_metric_map = _runtime_metric_map_from_agibot_export(
        metric_map=metric_map,
        static_fixture_projection=static_fixture_projection,
    )
    policy_view = dict(vendor_agent_view.get("policy_view") or {})
    return agent_view_module.build_agent_view(
        contract=REALWORLD_CONTRACT,
        perception_mode=str(vendor_agent_view.get("perception_mode") or "robot_policy_camera"),
        detection_exposure_policy="agibot_g2_head_color_policy_camera",
        structured_detections_available=bool(
            vendor_agent_view.get("structured_detections_available")
        ),
        base_metric_map=metric_map,
        runtime_metric_map=runtime_metric_map,
        observed_objects=list(vendor_agent_view.get("observed_objects") or []),
        raw_fpv_observations=list(vendor_agent_view.get("raw_fpv_observations") or []),
        camera_model_policy_evidence={
            "schema": "camera_model_policy_v1",
            "perception_mode": str(
                vendor_agent_view.get("perception_mode") or "robot_policy_camera"
            ),
            "enabled": False,
            "private_truth_included": False,
        },
        model_declared_observations=[],
        model_declared_observation_evidence={
            "schema": "model_declared_observations_v1",
            "perception_mode": str(
                vendor_agent_view.get("perception_mode") or "robot_policy_camera"
            ),
            "observation_count": 0,
            "resolved_count": 0,
            "acted_count": 0,
            "observations": [],
            "private_truth_included": False,
        },
        policy_view={
            "schema": "realworld_cleanup_policy_view_v1",
            "policy_observation_camera": str(
                policy_view.get("policy_observation_camera") or "head_color"
            ),
            "allowed_inputs": [
                "base_metric_map",
                "runtime_metric_map",
                "raw_fpv_observations",
                "navigation_status",
            ],
            "excluded_report_only_views": ["private_operator_evidence"],
            "chase_camera_policy_input": False,
        },
        cleanup_worklist=_cleanup_worklist_from_agibot_export(metric_map=metric_map),
        observed_waypoint_ids=[],
        public_tool_names=[
            "metric_map",
            "observe",
            "navigate_to_waypoint",
            *BLOCKED_MANIPULATION_TOOLS,
        ],
        blocked_capabilities=BLOCKED_MANIPULATION_TOOLS,
        capability_profiles=(
            HOUSEHOLD_WORLD_PROFILE,
            HOUSEHOLD_MANIPULATION_PROFILE,
            HOUSEHOLD_EPISODE_PROFILE,
        ),
        forbidden_keys=forbidden_agent_view_keys(),
    )


def _runtime_metric_map_from_agibot_export(
    *,
    metric_map: dict[str, Any],
    static_fixture_projection: dict[str, Any],
) -> dict[str, Any]:
    return {
        "schema": RUNTIME_METRIC_MAP_SCHEMA,
        "contract": REALWORLD_CONTRACT,
        "freshness": "current_run",
        "source_map_mutated": False,
        "private_truth_included": False,
        "static_fixture_projection": {
            "static_fixture_projection_mode": static_fixture_projection.get(
                "static_fixture_projection_mode",
                "",
            ),
            "contains_runtime_observations": static_fixture_projection.get(
                "contains_runtime_observations",
            ),
            "generated_exploration_candidate_count": static_fixture_projection.get(
                "generated_exploration_candidate_count",
                0,
            ),
        },
        "static_map": {
            "rooms": [dict(item) for item in metric_map.get("rooms") or []],
            "fixtures": [
                dict(fixture)
                for room in static_fixture_projection.get("rooms") or []
                for fixture in room.get("fixtures") or []
                if isinstance(fixture, dict)
            ],
            "inspection_waypoints": [
                dict(item) for item in metric_map.get("inspection_waypoints") or []
            ],
            "driveable_ways": [dict(item) for item in metric_map.get("driveable_ways") or []],
            "map_bundle": dict(metric_map.get("map_bundle") or {}),
            "contains_runtime_observations": False,
        },
        "public_semantic_anchors": [],
        "observed_objects": [],
        "target_candidates": [],
        "map_update_candidates": [],
        "visited_waypoint_ids": [],
        "observed_waypoint_ids": [],
        "generated_exploration_candidates": [
            dict(item)
            for item in metric_map.get("generated_exploration_candidates")
            or metric_map.get("inspection_waypoints")
            or []
        ],
        "cleanup_worklist_summary": {
            "schema": CLEANUP_WORKLIST_SCHEMA,
            "object_count": 0,
            "pending_count": 0,
            "held_object_id": None,
            "prior_count": 0,
        },
        "producer_summary": {
            "observed_object_count": 0,
            "public_semantic_anchor_count": 0,
            "map_update_candidate_count": 0,
        },
    }


def _cleanup_worklist_from_agibot_export(*, metric_map: dict[str, Any]) -> dict[str, Any]:
    return {
        "schema": CLEANUP_WORKLIST_SCHEMA,
        "waypoint_source": "agibot_sdk_agent_view_export",
        "held_object_id": None,
        "objects": [],
        "waypoints": [
            {
                "waypoint_id": str(item.get("waypoint_id") or ""),
                "room_id": str(item.get("room_id") or ""),
                "state": "unvisited",
                "purpose": str(item.get("purpose") or ""),
                "waypoint_source": str(item.get("waypoint_source") or ""),
            }
            for item in metric_map.get("inspection_waypoints") or []
        ],
        "rooms": [],
    }


def _fixtures(static_fixture_projection: dict[str, Any]) -> list[dict[str, Any]]:
    fixtures: list[dict[str, Any]] = []
    for room in static_fixture_projection.get("rooms") or []:
        for fixture in room.get("fixtures") or []:
            if isinstance(fixture, dict):
                fixtures.append(fixture)
    return fixtures


def _fixture_by_id(
    static_fixture_projection: dict[str, Any], fixture_id: str
) -> dict[str, Any] | None:
    for fixture in _fixtures(static_fixture_projection):
        if str(fixture.get("fixture_id") or fixture.get("receptacle_id") or "") == fixture_id:
            return fixture
    return None


def _preferred_verified_waypoint_id(waypoints: list[dict[str, Any]]) -> str:
    for waypoint in waypoints:
        if str(waypoint.get("reachability_status") or "") == "verified":
            return str(waypoint.get("waypoint_id") or "")
    return ""


def _map_fields_present(metric_map: dict[str, Any]) -> bool:
    required = {
        "schema",
        "frame_id",
        "resolution_m",
        "origin",
        "width",
        "height",
        "rooms",
        "driveable_ways",
        "inspection_waypoints",
    }
    return required <= set(metric_map)


def _pose_stamped_waypoints_present(metric_map: dict[str, Any]) -> bool:
    waypoints = metric_map.get("inspection_waypoints") or []
    return bool(waypoints) and all(
        {"frame_id", "x", "y", "yaw", "waypoint_id"} <= set(item) for item in waypoints
    )


def _dominant_primitive_provenance(items: list[dict[str, Any]]) -> str:
    if any(item.get("primitive_provenance") == AGIBOT_GDK_NORMAL_NAVI_PROVENANCE for item in items):
        return AGIBOT_GDK_NORMAL_NAVI_PROVENANCE
    if any(
        item.get("primitive_provenance") == AGIBOT_HEAD_COLOR_CAMERA_PROVENANCE for item in items
    ):
        return AGIBOT_HEAD_COLOR_CAMERA_PROVENANCE
    return BLOCKED_CAPABILITY_PROVENANCE


def _first_waypoint_id(metric_map: dict[str, Any]) -> str:
    waypoints = metric_map.get("inspection_waypoints") or []
    if not waypoints:
        raise ValueError("AgiBot agent view does not contain any inspection waypoints")
    return str(waypoints[0].get("waypoint_id") or "")


def _empty_score() -> dict[str, Any]:
    return {
        "restored_count": 0,
        "total_targets": 0,
        "object_results": [],
        "semantic_acceptability": {
            "accepted_count": 0,
            "total_targets": 0,
            "acceptance_rate": 0.0,
        },
    }


def _initial_locations(scenario: CleanupScenario) -> dict[str, str]:
    return {item.object_id: item.location_id for item in scenario.objects}
