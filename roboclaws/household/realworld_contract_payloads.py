from __future__ import annotations

import copy
from collections.abc import Callable, Collection
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from roboclaws.household.household_runtime_contract import HouseholdRuntimeContract

from roboclaws.household import (
    agent_view as agent_view_module,
)
from roboclaws.household import (
    realworld_runtime_map_contract,
    realworld_runtime_map_targets,
    realworld_runtime_target_selection,
)
from roboclaws.household.semantic_acceptability import (
    public_source_requires_cleanup,
)
from roboclaws.mcp.profiles import (
    HOUSEHOLD_EPISODE_PROFILE,
    HOUSEHOLD_MANIPULATION_PROFILE,
    HOUSEHOLD_WORLD_PROFILE,
)


def runtime_metric_map_payload(
    contract: HouseholdRuntimeContract,
    *,
    metric_map: dict[str, Any] | None = None,
    static_fixture_projection: dict[str, Any] | None = None,
    cleanup_worklist: dict[str, Any] | None = None,
    realworld_contract: str,
    runtime_metric_map_schema: str,
    cleanup_worklist_schema: str,
    visible_object_detections_mode: str,
    sanitized_visible_object_detections_provenance: str,
    runtime_map_producer_summary: Callable[..., dict[str, Any]],
    merge_public_rooms: Callable[[Any, Any], list[dict[str, Any]]],
    room_category_hints_from_public_rooms: Callable[[Any, Any], list[dict[str, Any]]],
    candidate_actionability_status: Callable[[dict[str, Any]], str],
    candidate_state: Callable[[dict[str, Any]], str],
    public_destination_policy_for_category: Callable[[Any], dict[str, Any]],
    norm: Callable[[Any], str],
    assert_no_forbidden_agent_view_keys: Callable[[Any], None],
) -> dict[str, Any]:
    """Build the current-run map view from public map and observation evidence."""

    public_metric_map = metric_map if metric_map is not None else contract.metric_map()
    public_static_fixture_projection = (
        static_fixture_projection
        if static_fixture_projection is not None
        else contract.static_fixture_projection()
    )
    public_worklist = (
        cleanup_worklist
        if cleanup_worklist is not None
        else contract.cleanup_worklist_payload(
            static_fixture_projection=public_static_fixture_projection
        )
    )
    worklist_by_handle = {
        str(item.get("object_id") or ""): dict(item)
        for item in public_worklist.get("objects") or []
    }
    runtime_map_priors = [dict(item) for item in contract._runtime_map_priors]
    observed_objects = [
        realworld_runtime_map_contract.runtime_observed_object_payload(
            handle=handle,
            detection=dict(contract._detections_by_handle[handle]),
            worklist_item=worklist_by_handle.get(handle, {}),
            object_lifecycle=dict(contract._object_lifecycle.get(handle, {})),
            sanitize_world_labels=contract.sanitize_world_labels,
            perception_mode=contract.perception_mode,
            visible_object_detections_mode=visible_object_detections_mode,
            sanitized_visible_object_detections_provenance=(
                sanitized_visible_object_detections_provenance
            ),
            runtime_map_priors=runtime_map_priors,
            public_fixture_reference_id=lambda fixture_id: (
                realworld_runtime_map_targets.public_fixture_reference_id(
                    contract,
                    fixture_id,
                )
            ),
            visual_evidence_for_handle=contract._visual_evidence_for_handle,
            candidate_actionability_status=candidate_actionability_status,
            candidate_state=candidate_state,
            public_destination_policy_for_category=public_destination_policy_for_category,
            assert_no_forbidden_agent_view_keys=assert_no_forbidden_agent_view_keys,
            norm=norm,
        )
        for handle in sorted(contract._detections_by_handle)
    ]
    runtime_observed_objects = [
        *[dict(item) for item in contract._runtime_map_priors],
        *observed_objects,
    ]
    public_semantic_anchors = realworld_runtime_map_targets.runtime_public_semantic_anchors(
        contract,
        assert_no_forbidden_agent_view_keys=assert_no_forbidden_agent_view_keys,
    )
    map_update_candidates: list[dict[str, Any]] = []
    target_candidates = realworld_runtime_target_selection.runtime_target_candidates(
        contract,
        public_semantic_anchors=public_semantic_anchors,
        observed_objects=runtime_observed_objects,
        assert_no_forbidden_agent_view_keys=assert_no_forbidden_agent_view_keys,
    )
    payload = {
        "schema": runtime_metric_map_schema,
        "contract": realworld_contract,
        "freshness": "current_run",
        "source_map_mutated": False,
        "private_truth_included": False,
        "static_map": realworld_runtime_map_contract.runtime_static_map_payload(
            metric_map=public_metric_map,
            static_fixture_projection=public_static_fixture_projection,
            assert_no_forbidden_agent_view_keys=assert_no_forbidden_agent_view_keys,
        ),
        "rooms": [dict(item) for item in public_metric_map.get("rooms") or []],
        "room_category_hints": [
            dict(item) for item in public_metric_map.get("room_category_hints") or []
        ],
        "driveable_ways": [dict(item) for item in public_metric_map.get("driveable_ways") or []],
        "public_semantic_anchors": public_semantic_anchors,
        "observed_objects": runtime_observed_objects,
        "target_candidates": target_candidates,
        "target_search_summary": realworld_runtime_target_selection.target_search_summary(
            contract,
            target_candidates,
            assert_no_forbidden_agent_view_keys=assert_no_forbidden_agent_view_keys,
        ),
        "target_query_recovery": realworld_runtime_target_selection.target_query_recovery_summary(
            contract,
            target_candidates,
            assert_no_forbidden_agent_view_keys=assert_no_forbidden_agent_view_keys,
        ),
        "map_update_candidates": map_update_candidates,
        "producer_summary": runtime_map_producer_summary(
            runtime_observed_objects,
            public_semantic_anchors=public_semantic_anchors,
            map_update_candidates=map_update_candidates,
            target_candidates=target_candidates,
        ),
        "cleanup_worklist_summary": {
            "schema": cleanup_worklist_schema,
            "object_count": len(public_worklist.get("objects") or []),
            "pending_count": sum(
                1 for item in public_worklist.get("objects") or [] if item.get("state") == "pending"
            ),
            "held_object_id": public_worklist.get("held_object_id"),
            "prior_count": len(contract._runtime_map_priors),
        },
        "public_contract_note": (
            "Runtime Metric Map enriches the current run with public observed "
            "handles, public semantic anchors, and map-update candidates. It "
            "does not mutate the source Base Metric Map artifact or include "
            "private scoring truth."
        ),
        "generated_target_inspection_candidates": [
            {
                **dict(item),
                "visited": str(item.get("waypoint_id") or "") in contract._observed_waypoint_ids,
            }
            for item in contract._generated_inspection_waypoints.values()
        ],
    }
    digital_twin_capabilities = dict(contract._runtime_prior_digital_twin_capabilities)
    if digital_twin_capabilities:
        payload["digital_twin_capabilities"] = digital_twin_capabilities
        payload["capability_summary"] = (
            realworld_runtime_map_contract.digital_twin_capability_summary(
                digital_twin_capabilities
            )
        )
    if contract._runtime_map_room_priors:
        payload["rooms"] = merge_public_rooms(
            payload.get("rooms") or [],
            contract._runtime_map_room_priors,
        )
        payload["room_category_hints"] = room_category_hints_from_public_rooms(
            payload["rooms"],
            public_metric_map.get("inspection_waypoints") or [],
        )
        payload["static_map"]["rooms"] = [dict(item) for item in payload["rooms"]]
    payload["generated_exploration_candidates"] = [
        {
            **dict(item),
            "visited": str(item.get("waypoint_id") or "") in contract._observed_waypoint_ids,
        }
        for item in contract._public_waypoints
    ]
    payload["public_contract_note"] = (
        "Runtime Metric Map starts from Base Metric Map occupancy/free-space "
        "geometry and generated exploration candidates, then enriches the run "
        "with public observations and run-local semantic anchors without "
        "mutating source-map semantics."
    )
    assert_no_forbidden_agent_view_keys(payload)
    return payload


def agent_view_payload(
    contract: HouseholdRuntimeContract,
    *,
    realworld_contract: str,
    visible_object_detections_mode: str,
    forbidden_keys: frozenset[str],
    assert_no_forbidden_agent_view_keys: Callable[[Any], None],
) -> dict[str, Any]:
    observed_objects = [
        contract._agent_visible_detection_payload(dict(contract._detections_by_handle[handle]))
        for handle in sorted(contract._detections_by_handle)
    ]
    metric_map = contract.metric_map()
    static_fixture_projection = contract.static_fixture_projection()
    cleanup_worklist = contract.cleanup_worklist_payload(
        static_fixture_projection=static_fixture_projection
    )
    model_declared = contract.model_declared_observations_payload()
    runtime_metric_map = dict(metric_map.get("runtime_metric_map") or {})
    if not runtime_metric_map:
        runtime_metric_map = contract.runtime_metric_map_payload(
            metric_map=metric_map,
            static_fixture_projection=static_fixture_projection,
            cleanup_worklist=cleanup_worklist,
        )
    payload = agent_view_module.build_agent_view(
        contract=realworld_contract,
        perception_mode=contract.perception_mode,
        detection_exposure_policy=contract.visible_detection_exposure_policy,
        structured_detections_available=contract.perception_mode == visible_object_detections_mode,
        base_metric_map=metric_map,
        runtime_metric_map=runtime_metric_map,
        observed_objects=observed_objects,
        raw_fpv_observations=[dict(item) for item in contract._raw_fpv_observations],
        camera_model_policy_evidence=contract.camera_model_policy_payload(),
        model_declared_observations=model_declared["observations"],
        model_declared_observation_evidence=model_declared,
        policy_view=contract.policy_view_payload(),
        cleanup_worklist=cleanup_worklist,
        observed_waypoint_ids=contract._observed_waypoint_ids,
        public_tool_names=contract.public_tool_names(),
        capability_profiles=(
            HOUSEHOLD_WORLD_PROFILE,
            HOUSEHOLD_MANIPULATION_PROFILE,
            HOUSEHOLD_EPISODE_PROFILE,
        ),
        public_acceptance_config=dict(getattr(contract, "public_acceptance_config", {}) or {}),
        forbidden_keys=forbidden_keys,
    )
    assert_no_forbidden_agent_view_keys(payload)
    return payload


def agent_visible_detection_payload(
    contract: HouseholdRuntimeContract,
    detection: dict[str, Any],
    *,
    sanitized_visible_object_detections_provenance: str,
    sanitized_visible_object_detections_policy: str,
    public_destination_policy_for_category: Callable[[Any], dict[str, Any]],
    assert_no_forbidden_agent_view_keys: Callable[[Any], None],
) -> dict[str, Any]:
    payload = contract._public_fixture_reference_payload(copy.deepcopy(detection))
    support = dict(payload.get("support_estimate") or {})
    public_fixture_id = str(support.get("fixture_id") or "")
    if public_fixture_id:
        support["source_fixture_hidden"] = True
        support["source"] = "public_semantic_anchor"
        payload["support_estimate"] = support
    if contract.sanitize_world_labels:
        payload = sanitized_visible_detection_payload(
            payload,
            sanitized_visible_object_detections_provenance=(
                sanitized_visible_object_detections_provenance
            ),
            sanitized_visible_object_detections_policy=sanitized_visible_object_detections_policy,
            public_destination_policy_for_category=public_destination_policy_for_category,
        )
    assert_no_forbidden_agent_view_keys(payload)
    return payload


def sanitized_visible_detection_payload(
    payload: dict[str, Any],
    *,
    sanitized_visible_object_detections_provenance: str,
    sanitized_visible_object_detections_policy: str,
    public_destination_policy_for_category: Callable[[Any], dict[str, Any]],
) -> dict[str, Any]:
    payload = copy.deepcopy(payload)
    for key in (
        "candidate_fixture_id",
        "candidate_fixture_category",
        "cleanup_recommended",
        "recommended_tool",
    ):
        payload.pop(key, None)
    payload["producer_type"] = sanitized_visible_object_detections_provenance
    payload["producer_id"] = sanitized_visible_object_detections_provenance
    payload["perception_source"] = sanitized_visible_object_detections_provenance
    payload["detection_exposure_policy"] = sanitized_visible_object_detections_policy
    payload["destination_policy_status"] = "policy_required"
    payload["destination_policy"] = public_destination_policy_for_category(payload.get("category"))
    support = dict(payload.get("support_estimate") or {})
    if support:
        support["source"] = "public_support_evidence"
        support["perception_source"] = sanitized_visible_object_detections_provenance
        support["model_provenance"] = sanitized_visible_object_detections_provenance
        payload["support_estimate"] = support
    return payload


def policy_view_payload(
    *,
    assert_no_forbidden_agent_view_keys: Callable[[Any], None],
) -> dict[str, Any]:
    payload = {
        "schema": "realworld_cleanup_policy_view_v1",
        "allowed_inputs": [
            "base_metric_map",
            "runtime_metric_map",
            "observed_objects",
            "raw_fpv_observations",
            "camera_model_policy_evidence",
            "model_declared_observations",
            "navigation_status",
        ],
        "excluded_report_only_views": [
            "chase_camera",
            "third_person_simulation_view",
            "private_evaluation",
        ],
        "chase_camera_policy_input": False,
        "public_contract_note": (
            "Policy inputs are robot-local observations, Base Metric Map "
            "context, and Runtime Metric Map evidence. Chase and third-person "
            "simulation views are report-only evidence."
        ),
    }
    assert_no_forbidden_agent_view_keys(payload)
    return payload


def camera_model_policy_payload(
    contract: HouseholdRuntimeContract,
    *,
    camera_model_policy_schema: str,
    camera_model_policy_mode: str,
    simulated_camera_model_provenance: str,
    sim_visual_grounding_pipeline_id: str,
    external_visual_grounding_provenance: str,
    average_duplicate_rate: Callable[[list[dict[str, Any]]], float],
) -> dict[str, Any]:
    events = [dict(item) for item in contract._camera_model_policy_events]
    pipeline_ids = [
        str((item.get("visual_grounding_pipeline") or {}).get("pipeline_id") or "")
        for item in events
    ]
    pipeline_ids = [item for item in pipeline_ids if item]
    failure_count = sum(
        1
        for item in events
        if (item.get("visual_grounding_pipeline") or {}).get("status") == "failed"
    )
    model_provenance = (
        simulated_camera_model_provenance
        if not pipeline_ids or set(pipeline_ids) == {sim_visual_grounding_pipeline_id}
        else external_visual_grounding_provenance
    )
    return {
        "schema": camera_model_policy_schema,
        "perception_mode": contract.perception_mode,
        "enabled": contract.perception_mode == camera_model_policy_mode,
        "model_provenance": model_provenance
        if contract.perception_mode == camera_model_policy_mode
        else "",
        "visual_grounding_pipeline_id": pipeline_ids[-1]
        if pipeline_ids
        else sim_visual_grounding_pipeline_id,
        "visual_grounding_pipeline_ids": sorted(set(pipeline_ids)),
        "visual_grounding_failure_count": failure_count,
        "event_count": len(events),
        "candidate_count": sum(int(item.get("candidate_count") or 0) for item in events),
        "unresolved_count": sum(
            int((item.get("visual_grounding_pipeline") or {}).get("unresolved_count") or 0)
            for item in events
        ),
        "duplicate_rate": average_duplicate_rate(events),
        "events": events,
        "private_truth_included": False,
        "policy_note": (
            "Camera-model policy candidates must be explicitly labelled and "
            "must not include private scoring truth."
        ),
    }


def model_declared_observations_payload(
    contract: HouseholdRuntimeContract,
    *,
    model_declared_observations_schema: str,
) -> dict[str, Any]:
    observations = [dict(item) for item in contract._model_declared_observations]
    acted_handles = {
        handle
        for handle, lifecycle in contract._object_lifecycle.items()
        if lifecycle.get("state") in {"navigating_to_object", "held", "placed", "placed_closed"}
    }
    for item in observations:
        item["acted_on"] = str(item.get("object_id") or "") in acted_handles
    return {
        "schema": model_declared_observations_schema,
        "perception_mode": contract.perception_mode,
        "observation_count": len(observations),
        "resolved_count": sum(
            1 for item in observations if item.get("grounding_status") == "resolved"
        ),
        "acted_count": sum(1 for item in observations if item.get("acted_on")),
        "observations": observations,
        "private_truth_included": False,
    }


def record_raw_fpv_observation(
    contract: HouseholdRuntimeContract,
    waypoint: dict[str, Any],
    *,
    perception_mode: str,
) -> dict[str, Any]:
    observation_id = f"raw_fpv_{len(contract._raw_fpv_observations) + 1:03d}"
    item = {
        "observation_id": observation_id,
        "waypoint_id": str(waypoint["waypoint_id"]),
        "room_id": str(waypoint["room_id"]),
        "held_object_id": contract._held_handle,
        "perception_mode": perception_mode,
        "structured_detections_available": False,
        "camera_offset": contract._camera_offset(),
        "image_artifacts": {},
        "artifact_status": "pending_robot_view_capture",
        "public_contract_note": (
            "No structured movable-object detections, categories, support estimates, "
            "target labels, or private scoring truth are included."
        ),
    }
    contract._raw_fpv_observations.append(item)
    return dict(item)


def record_inspection_observation(
    contract: HouseholdRuntimeContract,
    response: dict[str, Any],
    *,
    detections: list[dict[str, Any]],
    source_observation_id: str,
    inspection_observation_schema: str,
    target_candidate_evidence_lane: Callable[[Any], str],
    assert_no_forbidden_agent_view_keys: Callable[[Any], None],
) -> None:
    state_counts: dict[str, int] = {}
    actionability_counts: dict[str, int] = {}
    changed = 0
    for detection in detections:
        state = str(detection.get("candidate_state") or "")
        if state:
            state_counts[state] = state_counts.get(state, 0) + 1
        actionability = str(detection.get("actionability_status") or "")
        if actionability:
            actionability_counts[actionability] = actionability_counts.get(actionability, 0) + 1
        if detection.get("candidate_state_changed") is True:
            changed += 1
    camera_offset = contract._camera_offset()
    observation = {
        "schema": inspection_observation_schema,
        "observation_id": str(source_observation_id),
        "waypoint_id": str(response.get("waypoint_id") or contract._current_waypoint_id),
        "room_id": str(response.get("current_room_id") or ""),
        "perception_mode": contract.perception_mode,
        "evidence_lane": target_candidate_evidence_lane(contract),
        "camera_offset": camera_offset,
        "camera_adjusted": bool(
            camera_offset.get("yaw_delta_deg") or camera_offset.get("pitch_delta_deg")
        ),
        "structured_detections_available": bool(response.get("structured_detections_available")),
        "candidate_count": len(detections),
        "candidate_state_counts": state_counts,
        "actionability_status_counts": actionability_counts,
        "changed_candidate_state_count": changed,
        "private_truth_included": False,
    }
    assert_no_forbidden_agent_view_keys(observation)
    contract._inspection_observations.append(observation)


def cleanup_worklist_payload(
    contract: HouseholdRuntimeContract,
    *,
    static_fixture_projection: dict[str, Any] | None = None,
    cleanup_worklist_schema: str,
    non_actionable_handle_states: Collection[str],
    candidate_actionability_status: Callable[[dict[str, Any]], str],
    candidate_state: Callable[[dict[str, Any]], str],
    public_destination_policy_for_category: Callable[[Any], dict[str, Any]],
    recommended_place_tool: Callable[[str, dict[str, dict[str, Any]]], str],
    assert_no_forbidden_agent_view_keys: Callable[[Any], None],
) -> dict[str, Any]:
    public_fixtures = (
        static_fixture_projection
        if static_fixture_projection is not None
        else contract.static_fixture_projection()
    )
    lifecycle_rows = []
    for handle in sorted(contract._detections_by_handle):
        detection = contract._detections_by_handle[handle]
        lifecycle = dict(contract._object_lifecycle.get(handle, {}))
        support = detection.get("support_estimate") or {}
        declaration = detection.get("model_declared_observation") or {}
        grounding_status = str(
            detection.get("grounding_status") or declaration.get("grounding_status") or ""
        )
        visual_grounding_evidence = contract._visual_evidence_for_handle(handle)
        actionability_status = candidate_actionability_status(
            {
                **detection,
                "visual_grounding_evidence": visual_grounding_evidence,
                "grounding_status": grounding_status,
            }
        )
        public_candidate = realworld_runtime_map_targets.target_fixture_for_detection(
            contract,
            detection,
            public_fixtures,
            include_runtime_backend_fixtures=True,
        )
        candidate_fixture_id = (public_candidate or {}).get("fixture_id", "")
        source_fixture_id = str(support.get("fixture_id") or "")
        public_candidate_fixture_id = realworld_runtime_map_targets.public_fixture_reference_id(
            contract,
            str(candidate_fixture_id),
        )
        public_source_fixture_id = realworld_runtime_map_targets.public_fixture_reference_id(
            contract,
            source_fixture_id,
        )
        internal_source_fixture_id = (
            contract.internal_fixture_id_for_public_reference(source_fixture_id)
            or source_fixture_id
        )
        source_fixture = contract._fixtures.get(internal_source_fixture_id) or {}
        source_requires_cleanup = public_source_requires_cleanup(
            detection.get("category"),
            source_fixture.get("category") or source_fixture.get("name"),
        )
        state = str(lifecycle.get("state", "pending"))
        cleanup_recommended = bool(
            grounding_status not in {"ambiguous", "unresolved"}
            and actionability_status == "actionable"
            and public_candidate_fixture_id
            and public_candidate_fixture_id != public_source_fixture_id
            and source_requires_cleanup
            and state not in non_actionable_handle_states
        )
        candidate_source = (
            "public_semantic_anchor"
            if candidate_fixture_id
            else "public_category_fixture_affordance"
        )
        destination_policy_status = "candidate_inferred"
        if contract.sanitize_world_labels:
            public_candidate_fixture_id = ""
            cleanup_recommended = False
            candidate_source = "policy_required_destination_selection"
            destination_policy_status = "policy_required"
        destination_policy = public_destination_policy_for_category(detection.get("category"))
        generated_waypoint = contract._generated_inspection_waypoint_for_object(handle)
        row = {
            "object_id": handle,
            "state": state,
            "category": detection.get("category", ""),
            "room_id": detection.get("current_room_id", lifecycle.get("room_id", "")),
            "source_fixture_id": public_source_fixture_id,
            "candidate_fixture_id": public_candidate_fixture_id,
            "grounding_status": grounding_status,
            "actionability_status": actionability_status,
            "candidate_state": candidate_state(
                {
                    **detection,
                    "visual_grounding_evidence": visual_grounding_evidence,
                    "grounding_status": grounding_status,
                }
            ),
            "visual_grounding_evidence": visual_grounding_evidence,
            "candidate_source": candidate_source,
            "last_waypoint_id": lifecycle.get("waypoint_id", ""),
            "source_waypoint_id": str(
                detection.get("waypoint_id") or lifecycle.get("waypoint_id") or ""
            ),
            "generated_inspection_waypoint_id": str(
                generated_waypoint.get("waypoint_id") if generated_waypoint else ""
            ),
            "perception_source": lifecycle.get("perception_source", "visible_detection"),
            "destination_policy_status": destination_policy_status,
        }
        if contract.sanitize_world_labels:
            row["destination_policy"] = destination_policy
        if not contract.sanitize_world_labels:
            row["cleanup_recommended"] = cleanup_recommended
            internal_candidate_fixture_id = contract.internal_fixture_id_for_public_reference(
                public_candidate_fixture_id
            ) or str(candidate_fixture_id)
            row["recommended_tool"] = (
                recommended_place_tool(
                    internal_candidate_fixture_id,
                    contract._fixtures,
                )
                if public_candidate_fixture_id
                else ""
            )
        lifecycle_rows.append(row)
    waypoint_rows = []
    for waypoint in contract._public_navigation_waypoints():
        waypoint_id = str(waypoint["waypoint_id"])
        waypoint_rows.append(
            {
                "waypoint_id": waypoint_id,
                "room_id": waypoint["room_id"],
                "state": "visited"
                if waypoint_id in contract._observed_waypoint_ids
                else "unvisited",
                "purpose": waypoint.get("purpose", "fixture_coverage"),
                "waypoint_source": waypoint.get("waypoint_source", "static_map_coverage"),
            }
        )
    rooms = []
    for room in contract._public_rooms:
        room_waypoints = [item for item in waypoint_rows if item.get("room_id") == room["room_id"]]
        visited = sum(1 for item in room_waypoints if item.get("state") == "visited")
        pending = [
            item
            for item in lifecycle_rows
            if item.get("room_id") == room["room_id"] and item.get("state") == "pending"
        ]
        rooms.append(
            {
                "room_id": room["room_id"],
                "scan_state": "scanned"
                if room_waypoints and visited == len(room_waypoints)
                else "partially_scanned"
                if visited
                else "unvisited",
                "visited_waypoints": visited,
                "total_waypoints": len(room_waypoints),
                "pending_observed_handles": [item["object_id"] for item in pending],
            }
        )
    payload = {
        "schema": cleanup_worklist_schema,
        "waypoint_source": "generated_exploration_candidate",
        "held_object_id": contract._held_handle,
        "objects": lifecycle_rows,
        "waypoints": waypoint_rows,
        "rooms": rooms,
        "public_policy_note": (
            "Observed handles come from observe or model-declared camera evidence. "
            "Candidate fixtures are public category/fixture-affordance guesses, "
            "not private acceptable-destination truth."
        ),
    }
    assert_no_forbidden_agent_view_keys(payload)
    return payload
