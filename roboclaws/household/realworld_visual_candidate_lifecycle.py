from __future__ import annotations

import copy
from collections.abc import Callable
from types import SimpleNamespace
from typing import Any

from roboclaws.household import (
    realworld_contract_projection,
    realworld_runtime_map_targets,
    realworld_visual_candidates,
    visual_scan_guidance,
)

MODEL_DECLARED_OBSERVATION_SCHEMA = "model_declared_observation_v1"
MODEL_DECLARED_OBSERVATION_SOURCE = "model_declared_observation"
CANDIDATE_STATE_NAVIGATION_AUTHORIZED = (
    realworld_visual_candidates.CANDIDATE_STATE_NAVIGATION_AUTHORIZED
)
CANDIDATE_STATE_VISUAL_SCAN_REQUIRED = (
    realworld_visual_candidates.CANDIDATE_STATE_VISUAL_SCAN_REQUIRED
)
CANDIDATE_STATE_VISUALLY_CONFIRMED = realworld_visual_candidates.CANDIDATE_STATE_VISUALLY_CONFIRMED
VISUAL_EVIDENCE_REQUIRED_ACTIONABILITY = (
    realworld_visual_candidates.VISUAL_EVIDENCE_REQUIRED_ACTIONABILITY
)
VISUAL_CANDIDATE_ALREADY_HANDLED_REASON = (
    realworld_visual_candidates.VISUAL_CANDIDATE_ALREADY_HANDLED_REASON
)
_NON_ACTIONABLE_HANDLE_STATES = frozenset({"placed", "placed_closed", "skipped", "stale"})
_recommended_place_tool = realworld_contract_projection._recommended_place_tool
_room_id = realworld_contract_projection._room_id


def register_model_declared_candidate(
    contract: Any,
    *,
    raw_observation: dict[str, Any],
    waypoint: dict[str, Any],
    candidate: dict[str, Any],
    producer_type: str,
    producer_id: str,
    assert_no_forbidden_agent_view_keys: Callable[[Any], None],
) -> dict[str, Any]:
    normalized = normalized_visual_candidate(
        contract,
        raw_observation=raw_observation,
        candidate=candidate,
        producer_type=producer_type,
        producer_id=producer_id,
    )
    match = resolve_visual_candidate(contract, waypoint, normalized)
    declaration = declaration_from_resolution(
        contract,
        normalized,
        match,
        assert_no_forbidden_agent_view_keys=assert_no_forbidden_agent_view_keys,
    )
    handle = str(declaration["object_id"])
    if match["status"] == "already_handled":
        return dict(declaration)
    if match["status"] == "resolved":
        _register_resolved_detection(
            contract,
            raw_observation=raw_observation,
            waypoint=waypoint,
            declaration=declaration,
            match=match,
            handle=handle,
            producer_type=producer_type,
            producer_id=producer_id,
            assert_no_forbidden_agent_view_keys=assert_no_forbidden_agent_view_keys,
        )
    else:
        _register_unresolved_detection(contract, waypoint=waypoint, declaration=declaration)
    contract._model_declared_observations.append(declaration)
    return dict(declaration)


def _register_resolved_detection(
    contract: Any,
    *,
    raw_observation: dict[str, Any],
    waypoint: dict[str, Any],
    declaration: dict[str, Any],
    match: dict[str, Any],
    handle: str,
    producer_type: str,
    producer_id: str,
    assert_no_forbidden_agent_view_keys: Callable[[Any], None],
) -> None:
    obj = match["objects"][0]
    location_id = str(match["location_ids"][0])
    detection = detection_for_object_at_location(
        contract,
        obj,
        location_id=location_id,
        handle=handle,
        waypoint=waypoint,
        perception_source=MODEL_DECLARED_OBSERVATION_SOURCE,
        producer_type=producer_type,
        source_observation_id=str(raw_observation["observation_id"]),
        assert_no_forbidden_agent_view_keys=assert_no_forbidden_agent_view_keys,
    )
    detection.update(
        {
            "model_declared_observation": declaration,
            "model_declared_observation_id": declaration["declaration_id"],
            "producer_type": producer_type,
            "producer_id": producer_id,
            "image_region": declaration["image_region"],
            "evidence_note": declaration["evidence_note"],
            "grounding_status": declaration["grounding_status"],
            "grounding_confidence": declaration["grounding_confidence"],
            "grounding_basis": declaration["grounding_basis"],
            "visual_grounding_evidence": declaration["visual_grounding_evidence"],
        }
    )
    evidence = declaration["visual_grounding_evidence"]
    if isinstance(evidence, dict):
        detection["image_bbox"] = list(evidence.get("image_bbox") or [])
        detection["locality_status"] = str(
            evidence.get("locality_status") or "same_waypoint_source_observation"
        )
    _refresh_candidate_state(detection)
    detection.update(contract._public_candidate_hint(detection))
    _refresh_candidate_state(detection)
    if isinstance(detection.get("visual_grounding_evidence"), dict):
        detection["visual_grounding_evidence"]["candidate_state"] = detection["candidate_state"]
        detection["visual_grounding_evidence"]["actionability_status"] = detection[
            "actionability_status"
        ]
    assert_no_forbidden_agent_view_keys(detection)
    contract._detections_by_handle[handle] = detection
    contract._record_detection_lifecycle(handle, detection, waypoint)


def _refresh_candidate_state(detection: dict[str, Any]) -> None:
    detection["candidate_state"] = realworld_visual_candidates._candidate_state(detection)
    detection["candidate_state_history"] = realworld_visual_candidates._candidate_state_history(
        detection["candidate_state"]
    )
    detection["actionability_status"] = candidate_actionability_status(detection)


def _register_unresolved_detection(
    contract: Any,
    *,
    waypoint: dict[str, Any],
    declaration: dict[str, Any],
) -> None:
    handle = str(declaration["object_id"])
    contract._detections_by_handle[handle] = {
        "object_id": handle,
        "category": declaration["category"],
        "current_room_id": declaration["room_id"],
        "perception_source": MODEL_DECLARED_OBSERVATION_SOURCE,
        "model_declared_observation": declaration,
        "model_declared_observation_id": declaration["declaration_id"],
        "producer_type": declaration["producer_type"],
        "producer_id": declaration["producer_id"],
        "source_observation_id": declaration["source_observation_id"],
        "image_region": declaration["image_region"],
        "evidence_note": declaration["evidence_note"],
        "grounding_status": declaration["grounding_status"],
        "grounding_confidence": declaration["grounding_confidence"],
        "grounding_basis": declaration["grounding_basis"],
        "recovery_hint": declaration["recovery_hint"],
        "target_fixture_id": declaration["target_fixture_id"],
        "target_fixture_category": declaration["target_fixture_category"],
        "target_plausibility": declaration["target_plausibility"],
        "visual_grounding_evidence": declaration["visual_grounding_evidence"],
        "actionability_status": declaration["actionability_status"],
        "candidate_state": declaration["candidate_state"],
        "candidate_state_history": declaration["candidate_state_history"],
    }
    contract._set_handle_state(
        handle,
        f"grounding_{declaration['grounding_status']}",
        tool="declare_visual_candidates",
        waypoint_id=str(waypoint["waypoint_id"]),
        room_id=str(waypoint["room_id"]),
        source_fixture_id=declaration.get("source_fixture_id", ""),
        category=declaration["category"],
        perception_source=MODEL_DECLARED_OBSERVATION_SOURCE,
        grounding_status=declaration["grounding_status"],
    )


def normalized_visual_candidate(
    contract: Any,
    *,
    raw_observation: dict[str, Any],
    candidate: dict[str, Any],
    producer_type: str,
    producer_id: str,
) -> dict[str, Any]:
    image_region = realworld_visual_candidates._normalize_image_region(
        candidate.get("image_region")
    )
    category = str(candidate.get("category") or "object").strip() or "object"
    target_fixture_id = str(candidate.get("target_fixture_id") or "")
    target_resolution_source = "model_declared_target_fixture"
    if not target_fixture_id:
        target_fixture_id = realworld_runtime_map_targets.resolve_runtime_anchor_target_fixture_id(
            contract,
            category,
        )
        if target_fixture_id:
            target_resolution_source = "runtime_metric_map_public_semantic_anchor"
    target_fixture = contract._fixtures.get(
        contract.internal_fixture_id_for_public_reference(target_fixture_id) or target_fixture_id,
        {},
    )
    confidence = candidate.get("confidence")
    try:
        confidence_value = float(confidence) if confidence is not None else None
    except (TypeError, ValueError):
        confidence_value = None
    return {
        "source_observation_id": str(raw_observation["observation_id"]),
        "waypoint_id": str(raw_observation["waypoint_id"]),
        "room_id": str(raw_observation["room_id"]),
        "category": category,
        "target_fixture_id": target_fixture_id,
        "target_fixture_category": str(
            target_fixture.get("category") or target_fixture.get("name") or ""
        ),
        "target_fixture_resolution_source": target_resolution_source
        if target_fixture_id
        else "unresolved",
        "source_fixture_id": str(candidate.get("source_fixture_id") or ""),
        "evidence_note": str(candidate.get("evidence_note") or ""),
        "image_region": image_region,
        "confidence": confidence_value,
        "producer_type": str(candidate.get("producer_type") or producer_type),
        "producer_id": str(candidate.get("producer_id") or producer_id),
        "supersedes_observation_id": str(candidate.get("supersedes_observation_id") or ""),
        "visual_grounding_pipeline": candidate.get("visual_grounding_pipeline") or {},
        "visual_grounding_stage_provenance": list(
            candidate.get("visual_grounding_stage_provenance") or []
        ),
        "visual_grounding_destination_hint": candidate.get("visual_grounding_destination_hint")
        or {},
        "tracking": candidate.get("tracking") or {},
        "image_dimensions": candidate.get("image_dimensions") or {},
        "visual_grounding_overlay": str(candidate.get("visual_grounding_overlay") or ""),
    }


def resolve_visual_candidate(
    contract: Any,
    waypoint: dict[str, Any],
    candidate: dict[str, Any],
) -> dict[str, Any]:
    category_norm = _norm(candidate.get("category"))
    source_fixture_id = str(candidate.get("source_fixture_id") or "")
    source_observation_id = str(candidate.get("source_observation_id") or "")
    private_bindings = getattr(
        contract,
        "_private_raw_fpv_bindings_by_observation_id",
        {},
    ).get(source_observation_id)
    if isinstance(private_bindings, dict):
        match = visual_candidate_match_for_observation_binding(
            contract,
            candidate,
            private_bindings,
            category_norm=category_norm,
            source_fixture_id=source_fixture_id,
        )
    else:
        match = visual_candidate_match_for_source(
            contract,
            waypoint,
            category_norm=category_norm,
            source_fixture_id=source_fixture_id,
            restrict_to_waypoint_fixtures=True,
        )
    match["locality_status"] = (
        "exact_source_fixture_in_source_observation"
        if source_fixture_id and match["status"] != "unresolved"
        else "same_source_observation_bbox"
        if match.get("binding_source") == "private_observation_segmentation"
        and match["status"] != "unresolved"
        else "same_waypoint_public_context"
        if match["status"] != "unresolved"
        else "source_observation_locality_unresolved"
    )
    if source_fixture_id and match["status"] == "unresolved":
        match["requested_source_fixture_id"] = source_fixture_id
    return match


def visual_candidate_match_for_observation_binding(
    contract: Any,
    candidate: dict[str, Any],
    private_bindings: dict[str, Any],
    *,
    category_norm: str,
    source_fixture_id: str,
) -> dict[str, Any]:
    candidate_bbox = _candidate_bbox_pixels(candidate, private_bindings)
    if candidate_bbox is None:
        return {
            "status": "unresolved",
            "objects": [],
            "location_ids": [],
            "binding_source": "private_observation_segmentation",
        }
    ranked: list[tuple[int, float, int, Any, str]] = []
    handled: list[tuple[int, float, int, Any, str]] = []
    for item in private_bindings.get("bindings") or []:
        if not isinstance(item, dict):
            continue
        object_id = str(item.get("object_id") or "")
        location_id = str(item.get("location_id") or "")
        obj = SimpleNamespace(
            object_id=object_id,
            category=str(item.get("category") or "object"),
            name=str(item.get("name") or item.get("category") or "object"),
        )
        category_rank = realworld_visual_candidates._declared_category_match_rank(
            category_norm, obj
        )
        if not object_id or category_rank <= 0:
            continue
        if source_fixture_id and source_fixture_id not in {
            location_id,
            contract._public_fixture_reference_id(location_id),
        }:
            continue
        binding_bbox = _bbox_xywh(item.get("bbox"))
        if binding_bbox is None:
            continue
        score = _bbox_binding_score(candidate_bbox, binding_bbox)
        if score <= 0.0:
            continue
        existing_handle = contract._observed_handles_by_object_id.get(object_id)
        target = (
            handled
            if existing_handle and handle_is_non_actionable(contract, existing_handle)
            else ranked
        )
        target.append((category_rank, score, int(item.get("object_pixels") or 0), obj, location_id))
    ranked.sort(key=lambda item: (item[0], item[1], item[2]), reverse=True)
    handled.sort(key=lambda item: (item[0], item[1], item[2]), reverse=True)
    selected = ranked if ranked else handled
    if not selected:
        status = "unresolved"
    elif (
        len(selected) == 1
        or selected[0][0] > selected[1][0]
        or selected[0][1] >= selected[1][1] + 0.15
        or (selected[0][2] >= 32 and selected[0][2] >= 4 * max(1, selected[1][2]))
    ):
        status = "resolved" if ranked else "already_handled"
        selected = selected[:1]
    else:
        status = "ambiguous"
    return {
        "status": status,
        "objects": [item[3] for item in selected],
        "location_ids": [item[4] for item in selected],
        "binding_source": "private_observation_segmentation",
    }


def _candidate_bbox_pixels(
    candidate: dict[str, Any],
    private_bindings: dict[str, Any],
) -> tuple[float, float, float, float] | None:
    image_region = candidate.get("image_region")
    if not isinstance(image_region, dict) or image_region.get("type") != "bbox":
        return None
    bbox = _bbox_xywh(image_region.get("value"))
    if bbox is None:
        return None
    dimensions = private_bindings.get("image_dimensions") or {}
    width = float(dimensions.get("width") or 0)
    height = float(dimensions.get("height") or 0)
    if width > 0 and height > 0 and max(abs(value) for value in bbox) <= 1.0:
        return (bbox[0] * width, bbox[1] * height, bbox[2] * width, bbox[3] * height)
    return bbox


def _bbox_xywh(value: Any) -> tuple[float, float, float, float] | None:
    if not isinstance(value, (list, tuple)) or len(value) != 4:
        return None
    try:
        x, y, width, height = (float(item) for item in value)
    except (TypeError, ValueError):
        return None
    if width <= 0 or height <= 0:
        return None
    return x, y, width, height


def _bbox_binding_score(
    candidate: tuple[float, float, float, float],
    binding: tuple[float, float, float, float],
) -> float:
    cx, cy, cw, ch = candidate
    bx, by, bw, bh = binding
    intersection_width = max(0.0, min(cx + cw, bx + bw) - max(cx, bx))
    intersection_height = max(0.0, min(cy + ch, by + bh) - max(cy, by))
    intersection = intersection_width * intersection_height
    if intersection <= 0.0:
        return 0.0
    candidate_area = cw * ch
    binding_area = bw * bh
    return intersection / max(1.0, min(candidate_area, binding_area))


def visual_candidate_match_for_source(
    contract: Any,
    waypoint: dict[str, Any],
    *,
    category_norm: str,
    source_fixture_id: str,
    restrict_to_waypoint_fixtures: bool,
) -> dict[str, Any]:
    candidates = []
    location_ids = []
    handled_candidates = []
    handled_location_ids = []
    visible = (
        objects_visible_from_waypoint(contract, waypoint)
        if restrict_to_waypoint_fixtures
        else objects_visible_from_room(contract, waypoint)
    )
    for obj, location_id in visible:
        if category_norm and not realworld_visual_candidates._declared_category_matches_object(
            category_norm,
            obj,
        ):
            continue
        if source_fixture_id and location_id != source_fixture_id:
            continue
        existing_handle = contract._observed_handles_by_object_id.get(obj.object_id)
        if existing_handle and handle_is_non_actionable(contract, existing_handle):
            handled_candidates.append(obj)
            handled_location_ids.append(location_id)
            continue
        candidates.append(obj)
        location_ids.append(location_id)
    if len(candidates) == 1:
        return {"status": "resolved", "objects": candidates, "location_ids": location_ids}
    if len(candidates) > 1:
        return {"status": "ambiguous", "objects": candidates, "location_ids": location_ids}
    if handled_candidates:
        return {
            "status": "already_handled",
            "objects": handled_candidates,
            "location_ids": handled_location_ids,
        }
    return {"status": "unresolved", "objects": [], "location_ids": []}


def declaration_from_resolution(
    contract: Any,
    candidate: dict[str, Any],
    match: dict[str, Any],
    *,
    assert_no_forbidden_agent_view_keys: Callable[[Any], None],
) -> dict[str, Any]:
    status = str(match["status"])
    objects = match.get("objects") or []
    if status == "resolved":
        handle = contract._handle_for_object(objects[0].object_id)
        basis = (
            "single public camera-context object matched source observation bbox"
            if match.get("binding_source") == "private_observation_segmentation"
            else "single public camera-context object matched waypoint-local public context"
        )
        confidence = realworld_visual_candidates._grounding_confidence(candidate, "resolved")
        recovery_hint = ""
        grounding_status = "resolved"
        actionability_status = "actionable"
    elif status == "already_handled":
        handle = contract._handle_for_object(objects[0].object_id)
        lifecycle = contract._object_lifecycle.get(handle, {})
        basis = "only matching public camera-context object was already handled"
        confidence = realworld_visual_candidates._grounding_confidence(candidate, "unresolved")
        recovery_hint = (
            "The matching observed handle has already been placed or otherwise "
            "handled. Continue the waypoint sweep and observe for other objects."
        )
        grounding_status = "unresolved"
        actionability_status = "already_handled"
    else:
        handle = contract._new_unresolved_handle()
        basis = (
            "multiple public camera-context objects matched"
            if status == "ambiguous"
            else "no public camera-context object matched"
        )
        confidence = realworld_visual_candidates._grounding_confidence(candidate, status)
        recovery_hint = (
            "Adjust the camera to a materially different view, observe, then provide a tighter "
            "bbox/point before picking. Do not observe again at an unchanged pose."
            if status == "ambiguous"
            else (
                "No public actionable object matched this declaration. Rotate the robot body, "
                "adjust the camera, or move to another waypoint before observing again; an "
                "unchanged pose is not fresh evidence. Retry at most once from a materially "
                "different view, then continue the waypoint sweep instead of looping."
            )
        )
        grounding_status = status
        actionability_status = "needs_clarification"
    target_fixture_id = str(candidate.get("target_fixture_id") or "")
    internal_target_fixture_id = (
        contract.internal_fixture_id_for_public_reference(target_fixture_id) or target_fixture_id
    )
    target_fixture = contract._fixtures.get(internal_target_fixture_id, {})
    visual_grounding_evidence = visual_grounding_evidence_for_candidate(
        {**candidate, "locality_status": match.get("locality_status", "")},
        fallback_image_bbox=candidate.get("image_bbox"),
        grounding_status=grounding_status,
        assert_no_forbidden_agent_view_keys=assert_no_forbidden_agent_view_keys,
    )
    if actionability_status == "actionable":
        actionability_status = candidate_actionability_status(
            {
                "visual_grounding_evidence": visual_grounding_evidence,
                "grounding_status": grounding_status,
            },
            assert_no_forbidden_agent_view_keys=assert_no_forbidden_agent_view_keys,
        )
        if actionability_status != "actionable":
            recovery_hint = visual_scan_guidance.visual_evidence_recovery_hint()
    target_plausibility = target_plausibility_for_candidate(
        contract,
        category=str(candidate.get("category") or ""),
        target_fixture_id=target_fixture_id,
    )
    declaration = {
        "schema": MODEL_DECLARED_OBSERVATION_SCHEMA,
        "declaration_id": f"declared_{len(contract._model_declared_observations) + 1:03d}",
        "object_id": handle,
        "source_observation_id": str(candidate["source_observation_id"]),
        "waypoint_id": str(candidate["waypoint_id"]),
        "room_id": str(candidate["room_id"]),
        "category": str(candidate["category"]),
        "target_fixture_id": target_fixture_id,
        "target_fixture_category": str(
            target_fixture.get("category") or target_fixture.get("name") or ""
        ),
        "source_fixture_id": str(candidate.get("source_fixture_id") or ""),
        "evidence_note": str(candidate.get("evidence_note") or ""),
        "image_region": candidate["image_region"],
        "confidence": candidate.get("confidence"),
        "producer_type": str(candidate["producer_type"]),
        "producer_id": str(candidate["producer_id"]),
        "supersedes_observation_id": str(candidate.get("supersedes_observation_id") or ""),
        "grounding_status": grounding_status,
        "grounding_confidence": confidence,
        "grounding_basis": basis,
        "recovery_hint": recovery_hint,
        "target_plausibility": target_plausibility,
        "actionability_status": actionability_status,
        "candidate_state": realworld_visual_candidates._candidate_state(
            {
                **candidate,
                "visual_grounding_evidence": visual_grounding_evidence,
                "grounding_status": grounding_status,
                "actionability_status": actionability_status,
                "candidate_fixture_id": target_fixture_id,
                "recommended_tool": _recommended_place_tool(
                    internal_target_fixture_id,
                    contract._fixtures,
                )
                if target_fixture_id
                else "",
            }
        ),
        "visual_grounding_evidence": visual_grounding_evidence,
        "private_truth_included": False,
    }
    declaration["candidate_state_history"] = realworld_visual_candidates._candidate_state_history(
        str(declaration["candidate_state"])
    )
    declaration["visual_grounding_evidence"]["candidate_state"] = declaration["candidate_state"]
    declaration["visual_grounding_evidence"]["actionability_status"] = declaration[
        "actionability_status"
    ]
    for key in (
        "visual_grounding_pipeline",
        "visual_grounding_stage_provenance",
        "visual_grounding_destination_hint",
        "tracking",
        "image_dimensions",
        "visual_grounding_overlay",
    ):
        value = candidate.get(key)
        if value:
            declaration[key] = value
    if status == "already_handled":
        declaration["handled_state"] = str(lifecycle.get("state") or "handled")
    assert_no_forbidden_agent_view_keys(declaration)
    return declaration


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
    room_id = _room_id(str(fixture.get("room_area", waypoint["room_id"])))
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
            "relation": location_relation(obj.object_id, contract.backend),
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
    locations = contract.backend.object_locations()
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
    locations = contract.backend.object_locations()
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
            "current_room_id": _room_id(str(fixture.get("room_area", "unknown"))),
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
                "relation": location_relation(obj.object_id, contract.backend),
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
    room_id = _room_id(str(fixture.get("room_area", "unknown")))
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
            "relation": location_relation(obj.object_id, contract.backend),
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
            candidate_state=CANDIDATE_STATE_VISUALLY_CONFIRMED,
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


def location_relation(object_id: str, backend: Any) -> str:
    containment = getattr(backend, "_containment", {})
    relation = containment.get(object_id, {}).get("location_relation")
    return str(relation or "on")


def visibility_confidence(handle: str) -> float:
    suffix = int(handle.rsplit("_", 1)[-1])
    return round(0.78 + (suffix % 5) * 0.03, 2)


def image_bbox(handle: str) -> list[int]:
    suffix = int(handle.rsplit("_", 1)[-1])
    return [72 + suffix * 9, 58 + suffix * 7, 42, 31]


def _norm(value: Any) -> str:
    return str(value or "").strip().lower()
