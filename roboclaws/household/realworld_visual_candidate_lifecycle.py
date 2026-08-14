from __future__ import annotations

from collections.abc import Callable
from types import SimpleNamespace
from typing import Any

from roboclaws.household import (
    realworld_contract_fixture_projection as fixture_projection,
)
from roboclaws.household import (
    realworld_runtime_map_targets,
    realworld_visual_candidates,
    visual_scan_guidance,
)
from roboclaws.household.realworld_visual_perception_navigation import (
    _refresh_candidate_state,
    candidate_actionability_status,
    detection_for_object_at_location,
    handle_is_non_actionable,
    objects_visible_from_room,
    objects_visible_from_waypoint,
    target_plausibility_for_candidate,
    visual_grounding_evidence_for_candidate,
)

MODEL_DECLARED_OBSERVATION_SOURCE = "model_declared_observation"
CANDIDATE_STATE_NAVIGATION_AUTHORIZED = (
    realworld_visual_candidates.CANDIDATE_STATE_NAVIGATION_AUTHORIZED
)
CANDIDATE_STATE_VISUAL_SCAN_REQUIRED = (
    realworld_visual_candidates.CANDIDATE_STATE_VISUAL_SCAN_REQUIRED
)
VISUAL_EVIDENCE_REQUIRED_ACTIONABILITY = (
    realworld_visual_candidates.VISUAL_EVIDENCE_REQUIRED_ACTIONABILITY
)
VISUAL_CANDIDATE_ALREADY_HANDLED_REASON = (
    realworld_visual_candidates.VISUAL_CANDIDATE_ALREADY_HANDLED_REASON
)
_NON_ACTIONABLE_HANDLE_STATES = frozenset({"placed", "placed_closed", "skipped", "stale"})


def _norm(value: Any) -> str:
    return str(value or "").strip().lower()


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
        "schema": "model_declared_observation_v1",
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
                "recommended_tool": fixture_projection._recommended_place_tool(
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
