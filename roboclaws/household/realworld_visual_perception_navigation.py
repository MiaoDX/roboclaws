from __future__ import annotations

import copy
from collections.abc import Callable
from typing import Any

from roboclaws.household import (
    realworld_contract_fixture_projection as fixture_projection,
)
from roboclaws.household import (
    realworld_runtime_map_targets,
    realworld_visual_candidates,
    visual_scan_guidance,
)
from roboclaws.household.realworld_visual_candidates import (
    CANDIDATE_STATE_NAVIGATION_AUTHORIZED,
    CANDIDATE_STATE_VISUAL_SCAN_REQUIRED,
    VISUAL_CANDIDATE_ALREADY_HANDLED_REASON,
    VISUAL_EVIDENCE_REQUIRED_ACTIONABILITY,
)

MODEL_DECLARED_OBSERVATION_SOURCE = "model_declared_observation"
_NON_ACTIONABLE_HANDLE_STATES = realworld_visual_candidates.NON_ACTIONABLE_HANDLE_STATES


def _refresh_candidate_state(detection: dict[str, Any]) -> None:
    detection["candidate_state"] = realworld_visual_candidates._candidate_state(detection)
    detection["candidate_state_history"] = realworld_visual_candidates._candidate_state_history(
        detection["candidate_state"]
    )
    detection["actionability_status"] = candidate_actionability_status(detection)


def target_plausibility_for_candidate(
    contract: Any,
    *,
    category: str,
    target_fixture_id: str,
) -> dict[str, Any]:
    internal_target_fixture_id = (
        contract.internal_fixture_id_for_public_reference(target_fixture_id) or target_fixture_id
    )
    fixture = contract._fixtures.get(internal_target_fixture_id)
    if fixture is None:
        return {
            "status": "unknown_fixture",
            "basis": "target fixture id is not in public static fixture projection",
        }
    pseudo_detection = {
        "category": category,
        "name": category,
        "support_estimate": {"fixture_id": ""},
    }
    public_target = realworld_runtime_map_targets.target_fixture_for_detection(
        contract,
        pseudo_detection,
        contract.static_fixture_projection(),
    )
    expected = str((public_target or {}).get("fixture_id") or "")
    return {
        "status": "plausible" if not expected or expected == target_fixture_id else "weak",
        "basis": "public category/fixture affordance",
        "expected_fixture_id": expected,
    }


def detection_for_object_at_location(
    contract: Any,
    obj: Any,
    *,
    location_id: str,
    handle: str,
    waypoint: dict[str, Any],
    perception_source: str,
    producer_type: str,
    source_observation_id: str,
    assert_no_forbidden_agent_view_keys: Callable[[Any], None],
) -> dict[str, Any]:
    fixture = contract._fixtures.get(location_id, {})
    room_id = fixture_projection._room_id(str(fixture.get("room_area", waypoint["room_id"])))
    detection = {
        "object_id": handle,
        "category": obj.category,
        "name": obj.name,
        "current_room_id": room_id,
        "visibility_confidence": visibility_confidence(handle),
        "image_bbox": image_bbox(handle),
        "image_region": {"type": "bbox", "value": image_bbox(handle)},
        "perception_source": perception_source,
        "producer_type": producer_type,
        "source_observation_id": source_observation_id,
        "candidate_source": MODEL_DECLARED_OBSERVATION_SOURCE
        if perception_source == MODEL_DECLARED_OBSERVATION_SOURCE
        else "raw_fpv_observation",
        "candidate_state": CANDIDATE_STATE_NAVIGATION_AUTHORIZED,
        "candidate_state_history": realworld_visual_candidates._candidate_state_history(
            CANDIDATE_STATE_NAVIGATION_AUTHORIZED
        ),
        "locality_status": "same_waypoint_source_observation",
        "support_estimate": {
            "fixture_id": location_id,
            "relation": contract.backend_location_relation(obj.object_id),
            "confidence": 0.68,
            "source": perception_source,
            "perception_source": perception_source,
            "producer_type": producer_type,
            "source_observation_id": source_observation_id,
        },
    }
    detection["model_provenance"] = producer_type
    detection["support_estimate"]["model_provenance"] = producer_type
    detection["visual_grounding_evidence"] = visual_grounding_evidence_for_candidate(
        detection,
        assert_no_forbidden_agent_view_keys=assert_no_forbidden_agent_view_keys,
    )
    _refresh_candidate_state(detection)
    detection.update(contract._public_candidate_hint(detection))
    assert_no_forbidden_agent_view_keys(detection)
    return detection


def objects_visible_from_waypoint(contract: Any, waypoint: dict[str, Any]) -> list[tuple[Any, str]]:
    waypoint = contract._private_waypoint_for_public_waypoint(waypoint)
    waypoint_id = str(waypoint.get("waypoint_id") or "")
    locations = contract.backend_object_locations()
    fixture_ids = set(waypoint.get("fixture_ids") or [])
    visible = []
    for obj in contract.scenario.objects:
        location_id = locations.get(obj.object_id)
        if not location_id or location_id == "held_by_agent":
            continue
        fixture = contract._fixtures.get(location_id)
        if fixture is None:
            continue
        if fixture_ids and location_id not in fixture_ids:
            continue
        if not fixture_ids and _fixture_best_view_waypoint_id(contract, location_id) != waypoint_id:
            continue
        visible.append((obj, str(location_id)))
    return visible


def _fixture_best_view_waypoint_id(contract: Any, fixture_id: str) -> str:
    preferred = getattr(contract, "_preferred_waypoint_for_fixture", None)
    if callable(preferred):
        return str(preferred(fixture_id) or "")
    fixture = contract._fixtures.get(fixture_id) or {}
    return str(
        fixture.get("preferred_inspection_waypoint_id")
        or fixture.get("preferred_manipulation_waypoint_id")
        or ""
    )


def objects_visible_from_room(contract: Any, waypoint: dict[str, Any]) -> list[tuple[Any, str]]:
    waypoint = contract._private_waypoint_for_public_waypoint(waypoint)
    locations = contract.backend_object_locations()
    visible = []
    for obj in contract.scenario.objects:
        location_id = locations.get(obj.object_id)
        if not location_id or location_id == "held_by_agent":
            continue
        fixture = contract._fixtures.get(location_id)
        if fixture is None:
            continue
        visible.append((obj, str(location_id)))
    return visible


def visible_detections_for_waypoint(
    contract: Any,
    waypoint: dict[str, Any],
    *,
    source_observation_id: str,
    visual_confirmation: bool,
    visual_scan_payload: Callable[[bool], dict[str, Any]],
    assert_no_forbidden_agent_view_keys: Callable[[Any], None],
) -> list[dict[str, Any]]:
    public_waypoint = waypoint
    waypoint = contract._private_waypoint_for_public_waypoint(waypoint)
    detections = []
    for obj, location_id in objects_visible_from_waypoint(contract, public_waypoint):
        fixture = contract._fixtures.get(location_id)
        if fixture is None:
            continue
        handle = contract._handle_for_object(obj.object_id)
        detection = _visible_detection_payload(
            contract,
            obj,
            handle=handle,
            fixture=fixture,
            location_id=location_id,
            public_waypoint=public_waypoint,
            source_observation_id=source_observation_id,
            visual_confirmation=visual_confirmation,
            visual_scan_payload=visual_scan_payload,
        )
        previous_state = str(
            (contract._detections_by_handle.get(handle) or {}).get("candidate_state") or ""
        )
        detection["visual_grounding_evidence"] = visual_grounding_evidence_for_candidate(
            detection,
            assert_no_forbidden_agent_view_keys=assert_no_forbidden_agent_view_keys,
        )
        _refresh_candidate_state(detection)
        detection["candidate_state_changed"] = previous_state != detection["candidate_state"]
        detection["previous_candidate_state"] = previous_state
        detection.update(contract._public_candidate_hint(detection))
        if detection["candidate_state"] == CANDIDATE_STATE_VISUAL_SCAN_REQUIRED:
            contract._ensure_generated_inspection_waypoint_for_detection(handle, detection)
        contract._detections_by_handle[handle] = detection
        contract._record_detection_lifecycle(handle, detection, public_waypoint)
        detections.append(dict(detection))
    return sorted(detections, key=lambda item: str(item["object_id"]))


def camera_model_candidates_for_waypoint(
    contract: Any,
    waypoint: dict[str, Any],
    *,
    observation_id: str,
    model_provenance: str,
    camera_model_policy_mode: str,
    assert_no_forbidden_agent_view_keys: Callable[[Any], None],
) -> list[dict[str, Any]]:
    public_waypoint = waypoint
    candidates = []
    for obj, location_id in objects_visible_from_waypoint(contract, public_waypoint):
        fixture = contract._fixtures.get(location_id)
        if fixture is None:
            continue
        handle = contract._handle_for_object(obj.object_id)
        detection = {
            "object_id": handle,
            "category": obj.category,
            "name": obj.name,
            "current_room_id": fixture_projection._room_id(
                str(fixture.get("room_area", "unknown"))
            ),
            "visibility_confidence": visibility_confidence(handle),
            "image_bbox": image_bbox(handle),
            "image_region": {"type": "bbox", "value": image_bbox(handle)},
            "perception_source": camera_model_policy_mode,
            "model_provenance": model_provenance,
            "source_observation_id": observation_id,
            "candidate_source": "raw_fpv_observation",
            "candidate_state": CANDIDATE_STATE_NAVIGATION_AUTHORIZED,
            "candidate_state_history": realworld_visual_candidates._candidate_state_history(
                CANDIDATE_STATE_NAVIGATION_AUTHORIZED
            ),
            "locality_status": "same_waypoint_source_observation",
            "support_estimate": {
                "fixture_id": location_id,
                "relation": contract.backend_location_relation(obj.object_id),
                "confidence": 0.68,
                "source": camera_model_policy_mode,
                "perception_source": camera_model_policy_mode,
                "model_provenance": model_provenance,
                "source_observation_id": observation_id,
            },
        }
        detection["visual_grounding_evidence"] = visual_grounding_evidence_for_candidate(
            detection,
            assert_no_forbidden_agent_view_keys=assert_no_forbidden_agent_view_keys,
        )
        _refresh_candidate_state(detection)
        detection.update(contract._public_candidate_hint(detection))
        assert_no_forbidden_agent_view_keys(detection)
        contract._detections_by_handle[handle] = detection
        contract._record_detection_lifecycle(handle, detection, public_waypoint)
        candidates.append(dict(detection))
    return sorted(candidates, key=lambda item: str(item["object_id"]))


def ensure_generated_inspection_waypoint_for_detection(
    contract: Any,
    handle: str,
    detection: dict[str, Any],
    *,
    safe_anchor_id: Callable[[str], str],
    assert_no_forbidden_agent_view_keys: Callable[[Any], None],
) -> dict[str, Any]:
    existing = contract._generated_inspection_waypoint_for_object(handle)
    if existing:
        return existing
    source_waypoint_id = str(detection.get("waypoint_id") or contract._current_waypoint_id)
    source_waypoint = contract._waypoint_by_id(source_waypoint_id) or {}
    if not source_waypoint:
        return {}
    index = len(contract._generated_inspection_waypoints) + 1
    waypoint_id = f"generated_inspection_{index:03d}"
    pose = contract._waypoint_pose(source_waypoint)
    waypoint = {
        "waypoint_id": waypoint_id,
        "frame_id": str(source_waypoint.get("frame_id") or "map"),
        "x": pose["x"],
        "y": pose["y"],
        "yaw": round(pose["yaw"] + 15.0, 3),
        "room_id": str(source_waypoint.get("room_id") or contract._current_room_id()),
        "label": f"Generated inspection candidate {index}",
        "purpose": "target_inspection",
        "waypoint_source": "generated_target_inspection_candidate",
        "coverage_estimate": 0.0,
        "source_observation_id": str(detection.get("source_observation_id") or ""),
        "source_target_candidate_id": f"target_candidate_object_{safe_anchor_id(handle)}",
        "source_object_id": handle,
        "verified_navigation": True,
        "candidate_provenance": {
            "source": "server_verified_standoff_from_visible_evidence",
            "source_waypoint_id": source_waypoint_id,
            "source_observation_id": str(detection.get("source_observation_id") or ""),
            "visible_candidate_state": str(detection.get("candidate_state") or ""),
            "backend_verification": "same_public_waypoint_standoff_pose",
        },
        "public_contract_note": (
            "Generated Target Inspection Candidate was produced by the server from "
            "public visible evidence and projected as a bounded waypoint for "
            "navigate_to_waypoint."
        ),
    }
    assert_no_forbidden_agent_view_keys(waypoint)
    contract._generated_inspection_waypoints[waypoint_id] = waypoint
    private_source = contract._private_waypoint_for_public_waypoint(source_waypoint)
    contract._private_waypoint_by_public_id[waypoint_id] = private_source
    return dict(waypoint)


def navigate_to_visual_candidate(
    contract: Any,
    source_observation_id: str | None = None,
    category: str = "",
    target_fixture_id: str = "",
    evidence_note: str = "",
    image_region: dict[str, Any] | str | None = None,
    *,
    source_fixture_id: str = "",
    confidence: float | None = None,
    producer_type: str,
    producer_id: str,
    raw_fpv_declaration_strategy: str,
) -> dict[str, Any]:
    declaration_response = contract.declare_visual_candidates(
        source_observation_id,
        candidates=[
            {
                "category": category,
                "target_fixture_id": target_fixture_id,
                "evidence_note": evidence_note,
                "image_region": image_region,
                "source_fixture_id": source_fixture_id,
                "confidence": confidence,
            }
        ],
        producer_type=producer_type,
        producer_id=producer_id,
    )
    if not declaration_response.get("ok"):
        return contract._error(
            "navigate_to_visual_candidate",
            str(declaration_response.get("error_reason") or "declaration_failed"),
            candidate_error=declaration_response.get("candidate_error", {}),
            raw_fpv_candidate_recovery=declaration_response.get("raw_fpv_candidate_recovery", {}),
            recovery_hint=declaration_response.get("recovery_hint", ""),
        )
    declarations = declaration_response.get("model_declared_observations") or []
    declaration = declarations[0] if declarations else {}
    handle = str(declaration.get("object_id") or "")
    if response := _visual_candidate_declaration_blocker(contract, declaration, handle):
        return response
    detection = contract._detections_by_handle.get(handle, {})
    candidate_fixture_id = contract._public_fixture_reference_id(
        str(detection.get("candidate_fixture_id") or "")
    )
    cleanup_recommended = bool(detection.get("cleanup_recommended", False))
    recommended_tool = str(detection.get("recommended_tool") or "")
    if response := _visual_candidate_actionability_blocker(
        contract,
        declaration=declaration,
        detection=detection,
        handle=handle,
        candidate_fixture_id=candidate_fixture_id,
        cleanup_recommended=cleanup_recommended,
        recommended_tool=recommended_tool,
    ):
        return response
    navigation = contract.navigate_to_object(handle)
    if not navigation.get("ok"):
        return contract._error(
            "navigate_to_visual_candidate",
            str(navigation.get("error_reason") or "navigation_failed"),
            model_declared_observation=contract._public_fixture_reference_payload(declaration),
            object_id=handle,
            visual_grounding_evidence=navigation.get("visual_grounding_evidence", {}),
            actionability_status=navigation.get("actionability_status", ""),
            recovery_hint=navigation.get("recovery_hint", ""),
        )
    return _visual_candidate_navigation_response(
        contract,
        navigation=navigation,
        declaration=declaration,
        handle=handle,
        cleanup_recommended=cleanup_recommended,
        recommended_tool=recommended_tool,
        raw_fpv_declaration_strategy=raw_fpv_declaration_strategy,
    )


def _visual_candidate_declaration_blocker(
    contract: Any,
    declaration: dict[str, Any],
    handle: str,
) -> dict[str, Any] | None:
    if declaration.get("actionability_status") == "already_handled":
        return contract._error(
            "navigate_to_visual_candidate",
            VISUAL_CANDIDATE_ALREADY_HANDLED_REASON,
            model_declared_observation=contract._public_fixture_reference_payload(declaration),
            object_id=handle,
            grounding_status=declaration.get("grounding_status", "unresolved"),
            actionability_status="already_handled",
            required_next_tool="observe",
            recovery_hint=declaration.get(
                "recovery_hint",
                "This observed handle was already handled; continue the waypoint sweep.",
            ),
        )
    if declaration.get("grounding_status") != "resolved":
        ambiguous = declaration.get("grounding_status") == "ambiguous"
        return contract._error(
            "navigate_to_visual_candidate",
            "visual_candidate_not_resolved",
            model_declared_observation=contract._public_fixture_reference_payload(declaration),
            object_id=handle,
            grounding_status=declaration.get("grounding_status", "unresolved"),
            grounding_confidence=declaration.get("grounding_confidence", 0.0),
            required_next_tool="adjust_camera" if ambiguous else "navigate_to_relative_pose",
            recovery_tool_options=[
                "adjust_camera",
                "navigate_to_relative_pose",
                "navigate_to_waypoint",
            ],
            recovery_hint=declaration.get(
                "recovery_hint",
                "Change the public camera view before observing again. Do not call observe at "
                "an unchanged pose. If one retry from a different view still does not resolve, "
                "continue to another waypoint.",
            ),
        )
    return None


def _visual_candidate_actionability_blocker(
    contract: Any,
    *,
    declaration: dict[str, Any],
    detection: dict[str, Any],
    handle: str,
    candidate_fixture_id: str,
    cleanup_recommended: bool,
    recommended_tool: str,
) -> dict[str, Any] | None:
    visual_evidence_error = contract._visual_evidence_actionability_error(
        "navigate_to_visual_candidate",
        handle,
    )
    if visual_evidence_error is not None:
        return contract._error(
            "navigate_to_visual_candidate",
            str(visual_evidence_error.get("error_reason") or "visual_evidence_not_reviewable"),
            model_declared_observation=contract._public_fixture_reference_payload(declaration),
            object_id=handle,
            candidate_fixture_id=candidate_fixture_id,
            candidate_fixture_category=detection.get("candidate_fixture_category", ""),
            cleanup_recommended=bool(visual_evidence_error.get("cleanup_recommended", False)),
            recommended_tool=str(visual_evidence_error.get("recommended_tool") or ""),
            grounding_status=declaration.get("grounding_status", "resolved"),
            required_next_tool="observe",
            recovery_tool_options=visual_evidence_error.get("recovery_tool_options", []),
            actionability_status=visual_evidence_error.get(
                "actionability_status",
                VISUAL_EVIDENCE_REQUIRED_ACTIONABILITY,
            ),
            candidate_state=visual_evidence_error.get(
                "candidate_state",
                CANDIDATE_STATE_VISUAL_SCAN_REQUIRED,
            ),
            visual_grounding_evidence=visual_evidence_error.get(
                "visual_grounding_evidence",
                {},
            ),
            recovery_hint=visual_evidence_error.get("recovery_hint", ""),
        )
    if not candidate_fixture_id or not recommended_tool:
        return contract._error(
            "navigate_to_visual_candidate",
            "visual_candidate_not_actionable",
            model_declared_observation=contract._public_fixture_reference_payload(declaration),
            object_id=handle,
            candidate_fixture_id=candidate_fixture_id,
            candidate_fixture_category=detection.get("candidate_fixture_category", ""),
            cleanup_recommended=cleanup_recommended,
            recommended_tool=recommended_tool,
            grounding_status=declaration.get("grounding_status", "resolved"),
            required_next_tool="observe",
            recovery_hint=(
                "This grounded object has no public cleanup destination from the current "
                "map context. Do not pick it; continue the waypoint sweep and observe for "
                "other cleanup objects."
            ),
        )
    return None


def _visual_candidate_navigation_response(
    contract: Any,
    *,
    navigation: dict[str, Any],
    declaration: dict[str, Any],
    handle: str,
    cleanup_recommended: bool,
    recommended_tool: str,
    raw_fpv_declaration_strategy: str,
) -> dict[str, Any]:
    payload = {
        key: value
        for key, value in navigation.items()
        if key
        not in {
            "tool",
            "ok",
            "status",
            "object_id",
            "visual_grounding_evidence",
            "actionability_status",
            "candidate_state",
        }
    }
    detection = contract._detections_by_handle.get(handle, {})
    return contract._ok(
        "navigate_to_visual_candidate",
        **payload,
        object_id=handle,
        model_declared_observation=contract._public_fixture_reference_payload(declaration),
        candidate_fixture_id=contract._public_fixture_reference_id(
            str(detection.get("candidate_fixture_id") or "")
        ),
        candidate_fixture_category=detection.get("candidate_fixture_category", ""),
        cleanup_recommended=cleanup_recommended,
        recommended_tool=recommended_tool,
        visual_grounding_evidence=contract._visual_evidence_for_handle(handle),
        actionability_status="actionable",
        candidate_state=CANDIDATE_STATE_NAVIGATION_AUTHORIZED,
        declaration_strategy=raw_fpv_declaration_strategy,
        required_next_tool="pick",
    )


def _visible_detection_payload(
    contract: Any,
    obj: Any,
    *,
    handle: str,
    fixture: dict[str, Any],
    location_id: str,
    public_waypoint: dict[str, Any],
    source_observation_id: str,
    visual_confirmation: bool,
    visual_scan_payload: Callable[[bool], dict[str, Any]],
) -> dict[str, Any]:
    room_id = fixture_projection._room_id(str(fixture.get("room_area", "unknown")))
    image_region = (
        {"type": "bbox", "value": image_bbox(handle)}
        if visual_confirmation
        else {
            "type": "verbal_region",
            "value": (
                "structured semantic candidate; run adjust_camera then observe "
                "to bind a source FPV bbox before navigation"
            ),
        }
    )
    candidate_state = (
        CANDIDATE_STATE_NAVIGATION_AUTHORIZED
        if visual_confirmation
        else CANDIDATE_STATE_VISUAL_SCAN_REQUIRED
    )
    return {
        "object_id": handle,
        "category": obj.category,
        "name": obj.name,
        "current_room_id": room_id,
        "visibility_confidence": visibility_confidence(handle),
        "image_bbox": image_bbox(handle) if visual_confirmation else [],
        "image_region": image_region,
        "perception_source": "visible_detection",
        "producer_type": "visible_object_detections",
        "producer_id": "simulator_visible_object_detections",
        "source_observation_id": source_observation_id,
        "waypoint_id": str(public_waypoint.get("waypoint_id") or ""),
        "candidate_state": candidate_state,
        "candidate_state_history": realworld_visual_candidates._candidate_state_history(
            candidate_state
        ),
        "visual_scan": visual_scan_payload(visual_confirmation),
        "locality_status": "same_waypoint_source_observation"
        if visual_confirmation
        else "semantic_hint_requires_source_fpv_scan",
        "support_estimate": {
            "fixture_id": location_id,
            "relation": contract.backend_location_relation(obj.object_id),
            "confidence": 0.74,
            "source": "visible_detection",
            "perception_source": "visible_detection",
            "model_provenance": "visible_object_detections",
            "source_observation_id": source_observation_id,
        },
    }


def unresolved_visual_candidate_error(
    contract: Any,
    tool: str,
    object_id: str,
) -> dict[str, Any] | None:
    detection = contract._detections_by_handle.get(object_id)
    if not detection:
        return None
    declaration = detection.get("model_declared_observation") or {}
    status = declaration.get("grounding_status") or detection.get("grounding_status")
    if status not in {"ambiguous", "unresolved"}:
        return None
    return contract._error(
        tool,
        "visual_candidate_not_resolved",
        object_id=object_id,
        grounding_status=status,
        grounding_confidence=declaration.get(
            "grounding_confidence",
            detection.get("grounding_confidence", 0.0),
        ),
        grounding_basis=declaration.get(
            "grounding_basis",
            detection.get("grounding_basis", ""),
        ),
        recovery_hint=declaration.get(
            "recovery_hint",
            detection.get(
                "recovery_hint",
                "Declare a tighter image_region or source_fixture_id before picking.",
            ),
        ),
    )


def visual_evidence_for_handle(
    contract: Any,
    handle: str,
    *,
    assert_no_forbidden_agent_view_keys: Callable[[Any], None],
) -> dict[str, Any]:
    detection = contract._detections_by_handle.get(handle) or {}
    evidence = detection.get("visual_grounding_evidence")
    if isinstance(evidence, dict) and evidence:
        return copy.deepcopy(evidence)
    declaration = detection.get("model_declared_observation") or {}
    return visual_grounding_evidence_for_candidate(
        {
            **detection,
            "image_region": detection.get("image_region") or declaration.get("image_region"),
            "producer_type": detection.get("producer_type") or declaration.get("producer_type"),
            "producer_id": detection.get("producer_id") or declaration.get("producer_id"),
            "source_observation_id": detection.get("source_observation_id")
            or declaration.get("source_observation_id"),
            "grounding_status": detection.get("grounding_status")
            or declaration.get("grounding_status"),
        },
        assert_no_forbidden_agent_view_keys=assert_no_forbidden_agent_view_keys,
    )


def visual_evidence_actionability_error(
    contract: Any,
    tool: str,
    object_id: str,
    *,
    assert_no_forbidden_agent_view_keys: Callable[[Any], None],
) -> dict[str, Any] | None:
    detection = contract._detections_by_handle.get(object_id)
    if not detection:
        return None
    if handle_is_non_actionable(contract, object_id):
        return None
    status = candidate_actionability_status(
        detection,
        assert_no_forbidden_agent_view_keys=assert_no_forbidden_agent_view_keys,
    )
    candidate_state = realworld_visual_candidates._candidate_state(detection)
    if status == "actionable" and candidate_state == CANDIDATE_STATE_NAVIGATION_AUTHORIZED:
        return None
    evidence = visual_evidence_for_handle(
        contract,
        object_id,
        assert_no_forbidden_agent_view_keys=assert_no_forbidden_agent_view_keys,
    )
    declaration = detection.get("model_declared_observation") or {}
    if detection.get("cleanup_recommended") is False and status == "actionable":
        recovery = visual_scan_guidance.non_recommended_candidate_recovery(contract)
        return contract._error(
            tool,
            "visual_candidate_not_cleanup_recommended",
            object_id=object_id,
            candidate_fixture_id=str(detection.get("candidate_fixture_id") or ""),
            candidate_fixture_category=str(detection.get("candidate_fixture_category") or ""),
            cleanup_recommended=False,
            recommended_tool="",
            **recovery,
            actionability_status="not_recommended",
            candidate_state=realworld_visual_candidates.CANDIDATE_STATE_VISUALLY_CONFIRMED,
            visual_grounding_evidence=evidence,
            grounding_status=detection.get("grounding_status")
            or declaration.get("grounding_status")
            or "resolved",
            source_observation_id=evidence.get("source_observation_id", ""),
            recovery_hint=visual_scan_guidance.non_recommended_candidate_recovery_hint(
                contract.perception_mode
            ),
        )
    return contract._error(
        tool,
        "visual_evidence_not_reviewable",
        object_id=object_id,
        required_next_tool="adjust_camera"
        if candidate_state == CANDIDATE_STATE_VISUAL_SCAN_REQUIRED
        else "observe",
        recovery_tool_options=["observe", "adjust_camera"],
        actionability_status=status,
        candidate_state=candidate_state,
        visual_grounding_evidence=evidence,
        grounding_status=detection.get("grounding_status")
        or declaration.get("grounding_status")
        or "resolved",
        grounding_confidence=detection.get("grounding_confidence")
        or declaration.get("grounding_confidence")
        or 0.0,
        source_observation_id=evidence.get("source_observation_id", ""),
        recovery_hint=visual_scan_guidance.visual_evidence_recovery_hint(),
    )


def handle_is_non_actionable(contract: Any, handle: str) -> bool:
    if handle in contract._handled_handles:
        return True
    state = str((contract._object_lifecycle.get(handle) or {}).get("state") or "")
    return state in _NON_ACTIONABLE_HANDLE_STATES


def visual_grounding_evidence_for_candidate(
    candidate: dict[str, Any],
    *,
    fallback_image_bbox: Any = None,
    grounding_status: str = "",
    assert_no_forbidden_agent_view_keys: Callable[[Any], None] | None = None,
) -> dict[str, Any]:
    return realworld_visual_candidates._visual_grounding_evidence_for_candidate(
        candidate,
        fallback_image_bbox=fallback_image_bbox,
        grounding_status=grounding_status,
        assert_no_forbidden_agent_view_keys=assert_no_forbidden_agent_view_keys,
    )


def candidate_actionability_status(
    candidate: dict[str, Any],
    *,
    assert_no_forbidden_agent_view_keys: Callable[[Any], None] | None = None,
) -> str:
    return realworld_visual_candidates._candidate_actionability_status(
        candidate,
        visual_grounding_evidence_builder=lambda value: visual_grounding_evidence_for_candidate(
            value,
            assert_no_forbidden_agent_view_keys=assert_no_forbidden_agent_view_keys,
        ),
    )


def visibility_confidence(handle: str) -> float:
    suffix = int(handle.rsplit("_", 1)[-1])
    return round(0.78 + (suffix % 5) * 0.03, 2)


def image_bbox(handle: str) -> list[int]:
    suffix = int(handle.rsplit("_", 1)[-1])
    return [72 + suffix * 9, 58 + suffix * 7, 42, 31]
