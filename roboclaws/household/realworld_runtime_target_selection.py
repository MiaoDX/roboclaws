"""Runtime-map target candidate selection and public search summaries."""

from __future__ import annotations

import re
from typing import Any

from roboclaws.household import (
    realworld_runtime_map_contract,
    realworld_visual_candidates,
)
from roboclaws.household.target_query import resolve_target_query

RAW_FPV_ONLY_MODE = "raw_fpv_only"
CAMERA_MODEL_POLICY_MODE = "camera_model_policy"
TARGET_ACTIONABILITY_VISIBLE_ONLY = "visible_only"
TARGET_ACTIONABILITY_ANCHOR_UNBOUND = "anchor_unbound"
TARGET_ACTIONABILITY_NEEDS_OBSERVE = "needs_observe"
TARGET_ACTIONABILITY_ACTIONABLE = "actionable"
POSE_ROLE_INSPECTION_WAYPOINT = "inspection_waypoint"
POSE_ROLE_BEST_VIEW_POSE = "best_view_pose"
LOCALIZATION_STATUS_VIEWPOINT_ONLY = "viewpoint_only"
CANDIDATE_STATE_VISUAL_SCAN_REQUIRED = (
    realworld_visual_candidates.CANDIDATE_STATE_VISUAL_SCAN_REQUIRED
)
_float_or_zero = realworld_visual_candidates._float_or_zero


def _append_unique_candidate(
    candidates: list[dict[str, Any]],
    seen: set[str],
    candidate: dict[str, Any],
) -> None:
    candidate_id = str(candidate.get("candidate_id") or "")
    if candidate_id and candidate_id not in seen:
        candidates.append(candidate)
        seen.add(candidate_id)


def runtime_target_candidates(
    contract: Any,
    *,
    public_semantic_anchors: list[dict[str, Any]],
    observed_objects: list[dict[str, Any]],
    assert_no_forbidden_agent_view_keys: Any = None,
) -> list[dict[str, Any]]:
    assert_no_forbidden = assert_no_forbidden_agent_view_keys or (lambda _payload: None)
    candidates: list[dict[str, Any]] = []
    seen: set[str] = set()
    for waypoint in contract._public_navigation_waypoints():
        candidate = target_candidate_from_waypoint(contract, waypoint)
        _append_unique_candidate(candidates, seen, candidate)

    for anchor in public_semantic_anchors:
        candidate = target_candidate_from_anchor(contract, anchor)
        _append_unique_candidate(candidates, seen, candidate)

    for observed in observed_objects:
        candidate = target_candidate_from_observed_object(contract, observed)
        _append_unique_candidate(candidates, seen, candidate)

    for candidate in candidates:
        assert_no_forbidden(candidate)
    return candidates


def target_candidate_from_waypoint(
    contract: Any,
    waypoint: dict[str, Any],
) -> dict[str, Any]:
    waypoint_id = str(waypoint.get("waypoint_id") or "")
    visited = waypoint_id in contract._observed_waypoint_ids
    actionability = (
        TARGET_ACTIONABILITY_ACTIONABLE if visited else TARGET_ACTIONABILITY_NEEDS_OBSERVE
    )
    candidate = {
        "candidate_id": f"target_candidate_waypoint_{safe_anchor_id(waypoint_id)}",
        "candidate_type": realworld_runtime_map_contract.target_candidate_type_for_waypoint(
            waypoint
        ),
        "query": str(waypoint.get("label") or waypoint_id),
        "label": str(waypoint.get("label") or waypoint_id),
        "category": "inspection_area",
        "room_id": str(waypoint.get("room_id") or ""),
        "room_label": str(waypoint.get("room_label") or ""),
        "aliases": [str(item) for item in waypoint.get("aliases") or []],
        "evidence_lane": target_candidate_evidence_lane(contract),
        "producer_type": str(
            (waypoint.get("candidate_provenance") or {}).get("source")
            or waypoint.get("waypoint_source")
            or "public_metric_map"
        ),
        "producer_id": str(waypoint.get("waypoint_source") or "public_metric_map"),
        "source_observation_id": contract._observation_id_for_waypoint(waypoint_id)
        if visited
        else "",
        "waypoint_id": waypoint_id,
        "pose": contract._waypoint_pose(waypoint),
        "pose_source": POSE_ROLE_INSPECTION_WAYPOINT,
        "pose_role": POSE_ROLE_INSPECTION_WAYPOINT,
        "localization_status": LOCALIZATION_STATUS_VIEWPOINT_ONLY,
        "waypoint_source": str(waypoint.get("waypoint_source") or ""),
        "verified_navigation": True,
        "actionability": actionability,
        "target_actionability_status": actionability,
        "confidence": 1.0 if visited else 0.72,
        "rank": int((waypoint.get("candidate_provenance") or {}).get("candidate_index") or 0),
        "visited": visited,
        "inspection_budget": candidate_inspection_budget(contract, waypoint_id),
        "rejection_reason": "" if visited else "needs_observe_from_public_waypoint",
        "provenance": dict(waypoint.get("candidate_provenance") or {}),
    }
    if waypoint.get("source_target_candidate_id"):
        candidate["source_target_candidate_id"] = str(waypoint["source_target_candidate_id"])
    if waypoint.get("source_observation_id"):
        candidate["source_observation_id"] = str(
            candidate.get("source_observation_id") or waypoint.get("source_observation_id")
        )
    return candidate


def target_candidate_from_anchor(
    contract: Any,
    anchor: dict[str, Any],
) -> dict[str, Any]:
    anchor_id = str(anchor.get("anchor_id") or "")
    waypoint_id = str(anchor.get("waypoint_id") or "")
    verified_navigation = bool(waypoint_id and contract._waypoint_by_id(waypoint_id) is not None)
    actionability = (
        TARGET_ACTIONABILITY_ACTIONABLE
        if verified_navigation
        else TARGET_ACTIONABILITY_ANCHOR_UNBOUND
    )
    return {
        "candidate_id": f"target_candidate_anchor_{safe_anchor_id(anchor_id)}",
        "candidate_type": "public_semantic_anchor",
        "query": str(anchor.get("label") or anchor.get("category") or anchor_id),
        "label": str(anchor.get("label") or anchor_id),
        "category": str(anchor.get("category") or ""),
        "anchor_id": anchor_id,
        "anchor_type": str(anchor.get("anchor_type") or ""),
        "room_id": str(anchor.get("room_id") or ""),
        "room_label": str(anchor.get("room_label") or ""),
        "aliases": [str(item) for item in anchor.get("aliases") or []],
        "evidence_lane": target_candidate_evidence_lane(contract),
        "producer_type": str(anchor.get("producer_type") or ""),
        "producer_id": str(anchor.get("producer_id") or ""),
        "source_observation_id": str(anchor.get("source_observation_id") or ""),
        "waypoint_id": waypoint_id,
        "pose": dict(anchor.get("pose") or {}),
        "pose_source": str(anchor.get("pose_source") or POSE_ROLE_BEST_VIEW_POSE),
        "pose_role": str(anchor.get("pose_role") or POSE_ROLE_BEST_VIEW_POSE),
        "localization_status": str(
            anchor.get("localization_status") or LOCALIZATION_STATUS_VIEWPOINT_ONLY
        ),
        "verified_navigation": verified_navigation,
        "affordances": list(anchor.get("affordances") or []),
        "actionability": actionability,
        "target_actionability_status": actionability,
        "confidence": _float_or_zero(anchor.get("confidence")),
        "rank": 0,
        "visited": waypoint_id in contract._observed_waypoint_ids,
        "inspection_budget": candidate_inspection_budget(contract, waypoint_id),
        "rejection_reason": "" if verified_navigation else "anchor_missing_verified_waypoint",
    }


def target_candidate_from_observed_object(
    contract: Any,
    observed: dict[str, Any],
) -> dict[str, Any]:
    object_id = str(observed.get("object_id") or "")
    source_status = str(observed.get("actionability_status") or observed.get("actionability") or "")
    candidate_state = str(observed.get("candidate_state") or "")
    if source_status == "actionable" or observed.get("actionability") == "actionable":
        actionability = TARGET_ACTIONABILITY_ACTIONABLE
        rejection_reason = ""
    elif candidate_state == CANDIDATE_STATE_VISUAL_SCAN_REQUIRED:
        actionability = TARGET_ACTIONABILITY_VISIBLE_ONLY
        rejection_reason = "visual_evidence_not_reviewable"
    elif source_status in {"needs_clarification", "needs_confirm"}:
        actionability = TARGET_ACTIONABILITY_VISIBLE_ONLY
        rejection_reason = source_status
    elif observed.get("freshness") == "prior":
        actionability = TARGET_ACTIONABILITY_NEEDS_OBSERVE
        rejection_reason = "prior_requires_current_observation"
    else:
        actionability = TARGET_ACTIONABILITY_NEEDS_OBSERVE
        rejection_reason = source_status or "needs_fresh_observation"
    candidate = {
        "candidate_id": f"target_candidate_object_{safe_anchor_id(object_id)}",
        "candidate_type": "observed_object",
        "query": str(observed.get("category") or object_id),
        "label": str(observed.get("category") or object_id),
        "category": str(observed.get("category") or ""),
        "object_id": object_id,
        "evidence_lane": target_candidate_evidence_lane(contract),
        "producer_type": str(observed.get("producer_type") or ""),
        "producer_id": str(observed.get("producer_id") or ""),
        "source_observation_id": str(observed.get("source_observation_id") or ""),
        "waypoint_id": str(observed.get("waypoint_id") or ""),
        "source_fixture_id": str(observed.get("source_fixture_id") or ""),
        "candidate_fixture_id": str(observed.get("candidate_fixture_id") or ""),
        "visual_grounding_evidence": dict(observed.get("visual_grounding_evidence") or {}),
        "localization_status": str(
            observed.get("localization_status") or LOCALIZATION_STATUS_VIEWPOINT_ONLY
        ),
        "verified_navigation": actionability == TARGET_ACTIONABILITY_ACTIONABLE,
        "actionability": actionability,
        "target_actionability_status": actionability,
        "source_actionability_status": source_status,
        "candidate_state": candidate_state,
        "confidence": _float_or_zero(observed.get("confidence")),
        "rank": 0,
        "visited": bool(observed.get("source_observation_id")),
        "inspection_budget": candidate_inspection_budget(
            contract,
            str(observed.get("waypoint_id") or ""),
        ),
        "rejection_reason": rejection_reason,
    }
    generated = contract._generated_inspection_waypoint_for_object(object_id)
    if generated:
        candidate["generated_inspection_waypoint_id"] = str(generated.get("waypoint_id") or "")
        candidate["generated_inspection_candidate"] = {
            key: generated[key]
            for key in (
                "waypoint_id",
                "label",
                "waypoint_source",
                "source_observation_id",
                "verified_navigation",
            )
            if key in generated
        }
    return candidate


def target_search_summary(
    contract: Any,
    target_candidates: list[dict[str, Any]],
    *,
    schema: str = "target_search_summary_v1",
    assert_no_forbidden_agent_view_keys: Any = None,
) -> dict[str, Any]:
    actionability_counts: dict[str, int] = {}
    for candidate in target_candidates:
        actionability = str(candidate.get("target_actionability_status") or "")
        actionability_counts[actionability] = actionability_counts.get(actionability, 0) + 1
    visited_waypoints = sorted(contract._observed_waypoint_ids)
    public_waypoints = contract._public_navigation_waypoints()
    summary = {
        "schema": schema,
        "candidate_count": len(target_candidates),
        "actionability_counts": actionability_counts,
        "viewpoint_budget": {
            "total_public_waypoints": len(public_waypoints),
            "visited_waypoint_count": len(visited_waypoints),
            "unvisited_waypoint_count": max(len(public_waypoints) - len(visited_waypoints), 0),
            "observed_waypoint_ids": visited_waypoints,
            "unvisited_waypoint_ids": [
                str(item.get("waypoint_id") or "")
                for item in public_waypoints
                if str(item.get("waypoint_id") or "") not in contract._observed_waypoint_ids
            ],
        },
        "camera_adjustment_budget": {
            "max_yaw_delta_deg": 45,
            "max_pitch_delta_deg": 20,
            "recommended_attempts_per_waypoint": 1,
            "attempt_count": len(contract._camera_adjustment_events),
            "attempts": [dict(item) for item in contract._camera_adjustment_events],
        },
        "inspection_observations": [dict(item) for item in contract._inspection_observations],
        "missing_target_policy": (
            "A missing target claim must be based on inspected public waypoints, "
            "recorded camera-adjustment attempts when needed, and exhausted public "
            "candidate budget rather than private inventory."
        ),
        "private_truth_included": False,
    }
    if assert_no_forbidden_agent_view_keys is not None:
        assert_no_forbidden_agent_view_keys(summary)
    return summary


def target_query_recovery_summary(
    contract: Any,
    target_candidates: list[dict[str, Any]],
    *,
    assert_no_forbidden_agent_view_keys: Any = None,
) -> dict[str, Any]:
    runtime_map = {
        "target_candidates": target_candidates,
        "target_search_summary": target_search_summary(contract, target_candidates),
    }
    summary = {
        "schema": "target_query_recovery_summary_v1",
        "source": "runtime_metric_map_target_candidates",
        "status": "available",
        "supported_operations": [
            "inspect",
            "map-build",
            "destination",
            "place",
            "navigate",
            "open-ended",
        ],
        "recovery_policy": (
            "Resolve stale labels, raw fixture ids, and open-ended target names "
            "through public target_candidates. Navigation may use only returned "
            "public waypoint ids, anchor ids, observed object handles, or "
            "candidate_fixture_id fields; not-found claims must include the "
            "public_search_budget from a resolution."
        ),
        "example_queries": [
            resolve_target_query(runtime_map, query, operation="destination")
            for query in target_query_recovery_examples(target_candidates)
        ],
        "private_truth_included": False,
    }
    if assert_no_forbidden_agent_view_keys is not None:
        assert_no_forbidden_agent_view_keys(summary)
    return summary


def target_query_recovery_examples(target_candidates: list[dict[str, Any]]) -> list[str]:
    examples: list[str] = []
    for candidate in target_candidates:
        for key in ("label", "category", "waypoint_id", "anchor_id", "object_id"):
            value = str(candidate.get(key) or "").strip()
            if value and value not in examples:
                examples.append(value)
            if len(examples) >= 3:
                return examples
    return examples


def candidate_inspection_budget(
    contract: Any,
    waypoint_id: str,
) -> dict[str, Any]:
    observations = [
        item
        for item in contract._inspection_observations
        if str(item.get("waypoint_id") or "") == waypoint_id
    ]
    adjustments = [
        item
        for item in contract._camera_adjustment_events
        if str(item.get("waypoint_id") or "") == waypoint_id
    ]
    return {
        "schema": "target_candidate_inspection_budget_v1",
        "observed": bool(observations),
        "observation_count": len(observations),
        "camera_adjustment_attempt_count": len(adjustments),
        "max_camera_adjustment_attempts": 1,
    }


def target_candidate_evidence_lane(contract: Any) -> str:
    if contract.sanitize_world_labels:
        return "world-public-labels"
    if contract.perception_mode == RAW_FPV_ONLY_MODE:
        return "camera-raw-fpv"
    if contract.perception_mode == CAMERA_MODEL_POLICY_MODE:
        return "camera-grounded-labels"
    return "world-public-labels"


def safe_anchor_id(value: str) -> str:
    safe = re.sub(r"[^a-zA-Z0-9_]+", "_", value).strip("_")
    return safe or "unknown"
