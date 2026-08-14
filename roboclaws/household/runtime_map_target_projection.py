"""Runtime-map semantic-anchor materialization and evidence ranking."""

from __future__ import annotations

import re
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from roboclaws.household.household_runtime_contract import HouseholdRuntimeContract

from roboclaws.household.realworld_contract_fixture_projection import (
    _anchor_affordances_for_fixture,
    _semantic_anchor_type_for_fixture,
)
from roboclaws.household.realworld_contract_projection import _room_category_from_label
from roboclaws.household.realworld_runtime_target_selection import safe_anchor_id

POSE_ROLE_INSPECTION_WAYPOINT = "inspection_waypoint"
POSE_ROLE_BEST_VIEW_POSE = "best_view_pose"
LOCALIZATION_STATUS_VIEWPOINT_ONLY = "viewpoint_only"


def _float_or_zero(value: Any) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


def _public_waypoint_id_for_private_fixture(contract: Any, fixture_id: str) -> str:
    private_id = contract._preferred_waypoint_for_fixture(fixture_id)
    for public_id, mapped in contract._private_waypoint_by_public_id.items():
        if str(mapped.get("waypoint_id") or "") == private_id:
            waypoint = contract._waypoint_by_id(public_id) or {}
            return str(waypoint.get("waypoint_id") or contract._current_waypoint_id)
    return contract._current_waypoint_id


def _append_generated_public_semantic_anchors(
    contract: HouseholdRuntimeContract,
    *,
    anchors: list[dict[str, Any]],
    seen: set[str],
) -> None:
    for waypoint in contract._public_waypoints:
        waypoint_id = str(waypoint.get("waypoint_id") or "")
        if waypoint_id not in contract._observed_waypoint_ids:
            continue
        for anchor in (
            _room_area_public_semantic_anchor(contract, waypoint),
            _waypoint_public_semantic_anchor(contract, waypoint),
        ):
            anchor_id = str(anchor.get("anchor_id") or "")
            if anchor_id and anchor_id not in seen:
                anchors.append(anchor)
                seen.add(anchor_id)


def _append_fixture_public_semantic_anchors(
    contract: HouseholdRuntimeContract,
    *,
    anchors: list[dict[str, Any]],
    seen: set[str],
) -> None:
    candidates_by_anchor_id: dict[str, dict[str, Any]] = {}
    for fixture_id, anchor_id in sorted(
        contract._public_anchor_ids_by_private_fixture_id.items(),
        key=lambda item: item[1],
    ):
        anchor = _fixture_public_semantic_anchor(contract, fixture_id, anchor_id)
        if not anchor:
            continue
        current = candidates_by_anchor_id.get(anchor_id)
        if current is None or _fixture_anchor_evidence_rank(anchor) > _fixture_anchor_evidence_rank(
            current
        ):
            candidates_by_anchor_id[anchor_id] = anchor
    seen_viewpoint_keys: set[tuple[str, str, str, str, str]] = set()
    for anchor_id, anchor in sorted(candidates_by_anchor_id.items()):
        if not anchor or anchor_id in seen:
            continue
        viewpoint_key = _fixture_anchor_viewpoint_key(anchor)
        if viewpoint_key in seen_viewpoint_keys:
            continue
        anchors.append(anchor)
        seen.add(anchor_id)
        seen_viewpoint_keys.add(viewpoint_key)


def _append_prior_public_semantic_anchors(
    contract: HouseholdRuntimeContract,
    *,
    anchors: list[dict[str, Any]],
    seen: set[str],
) -> None:
    for prior_anchor in contract._runtime_map_anchor_priors:
        anchor_id = str(prior_anchor.get("anchor_id") or "")
        if anchor_id and anchor_id in seen:
            continue
        waypoint_id = str(prior_anchor.get("waypoint_id") or "")
        if waypoint_id and contract._waypoint_by_id(waypoint_id) is None:
            continue
        anchors.append(dict(prior_anchor))
        if anchor_id:
            seen.add(anchor_id)


def _room_area_public_semantic_anchor(
    contract: HouseholdRuntimeContract,
    waypoint: dict[str, Any],
) -> dict[str, Any]:
    room_id = str(waypoint.get("room_id") or "generated_area")
    room_label = str(waypoint.get("room_label") or room_id.replace("_", " ").title())
    waypoint_id = str(waypoint.get("waypoint_id") or "")
    observation_id = contract._observation_id_for_waypoint(waypoint_id)
    return {
        "anchor_id": f"anchor_room_{safe_anchor_id(room_id)}",
        "anchor_type": "room_area",
        "category": _room_category_from_label(room_label, room_id),
        "label": room_label,
        "room_id": room_id,
        "room_label": room_label,
        "waypoint_id": waypoint_id,
        "pose": contract._waypoint_pose(waypoint),
        "pose_source": POSE_ROLE_INSPECTION_WAYPOINT,
        "pose_role": POSE_ROLE_INSPECTION_WAYPOINT,
        "localization_status": LOCALIZATION_STATUS_VIEWPOINT_ONLY,
        "affordances": ["navigate", "observe"],
        "aliases": [room_id, room_label],
        "producer_type": "generated_exploration_candidate",
        "producer_id": "base_metric_map_exploration",
        "confidence": 0.8 if room_label else 0.6,
        "freshness": "current_run",
        "actionability": "actionable",
        "source_observation_id": observation_id,
        "promotion_status": "run_local",
        "evidence": {
            "type": "visited_generated_area",
            "visited": True,
            "candidate_provenance": dict(waypoint.get("candidate_provenance") or {}),
        },
    }


def _waypoint_public_semantic_anchor(
    contract: HouseholdRuntimeContract,
    waypoint: dict[str, Any],
) -> dict[str, Any]:
    waypoint_id = str(waypoint.get("waypoint_id") or "")
    observation_id = contract._observation_id_for_waypoint(waypoint_id)
    return {
        "anchor_id": f"anchor_waypoint_{safe_anchor_id(waypoint_id)}",
        "anchor_type": "observation_waypoint",
        "category": "observation_waypoint",
        "label": str(waypoint.get("label") or waypoint_id),
        "room_id": str(waypoint.get("room_id") or ""),
        "room_label": str(waypoint.get("room_label") or ""),
        "waypoint_id": waypoint_id,
        "pose": contract._waypoint_pose(waypoint),
        "pose_source": POSE_ROLE_INSPECTION_WAYPOINT,
        "pose_role": POSE_ROLE_INSPECTION_WAYPOINT,
        "localization_status": LOCALIZATION_STATUS_VIEWPOINT_ONLY,
        "affordances": ["observe"],
        "producer_type": "generated_exploration_candidate",
        "producer_id": "base_metric_map_exploration",
        "confidence": 1.0,
        "freshness": "current_run",
        "actionability": "actionable",
        "source_observation_id": observation_id,
        "promotion_status": "run_local",
        "evidence": {
            "type": "visited_generated_exploration_candidate",
            "visited": True,
            "candidate_provenance": dict(waypoint.get("candidate_provenance") or {}),
        },
    }


def _fixture_public_semantic_anchor(
    contract: HouseholdRuntimeContract,
    fixture_id: str,
    anchor_id: str,
) -> dict[str, Any]:
    fixture = contract._fixtures.get(fixture_id)
    if fixture is None:
        return {}
    supporting = _supporting_detections_for_fixture(contract, fixture_id)
    fixture_observation = dict(contract._fixture_observations_by_fixture_id.get(fixture_id) or {})
    if not supporting and not fixture_observation:
        return {}
    best_detection = supporting[0] if supporting else {}
    best_lifecycle = contract._object_lifecycle.get(
        str(best_detection.get("object_id") or ""),
        {},
    )
    waypoint_id = str(fixture_observation.get("waypoint_id") or "")
    if not waypoint_id:
        waypoint_id = _public_waypoint_id_for_private_fixture(contract, fixture_id)
    if not waypoint_id:
        waypoint_id = str(best_lifecycle.get("waypoint_id") or contract._current_waypoint_id)
    waypoint = contract._waypoint_by_id(waypoint_id) or {}
    source_observation_id = str(
        fixture_observation.get("source_observation_id")
        or contract._observation_id_for_waypoint(waypoint_id)
        or best_detection.get("source_observation_id")
        or best_lifecycle.get("source_observation_id")
    )
    confidence_values = [
        _float_or_zero(item.get("visibility_confidence"))
        or _float_or_zero((item.get("support_estimate") or {}).get("confidence"))
        for item in supporting
    ]
    confidence = max(confidence_values) if confidence_values else 0.68
    return {
        "anchor_id": anchor_id,
        "anchor_type": _semantic_anchor_type_for_fixture(fixture),
        "category": str(
            fixture_observation.get("category")
            or fixture.get("category")
            or fixture.get("name")
            or "fixture"
        ),
        "label": str(
            fixture_observation.get("label")
            or fixture.get("category")
            or fixture.get("name")
            or "Observed fixture"
        ),
        "room_id": str(
            fixture_observation.get("room_id")
            or (waypoint or {}).get("room_id")
            or fixture.get("room_id")
            or best_lifecycle.get("room_id")
            or ""
        ),
        "waypoint_id": waypoint_id,
        "pose": contract._waypoint_pose(waypoint),
        "pose_source": POSE_ROLE_INSPECTION_WAYPOINT,
        "pose_role": POSE_ROLE_BEST_VIEW_POSE,
        "localization_status": LOCALIZATION_STATUS_VIEWPOINT_ONLY,
        "affordances": _anchor_affordances_for_fixture(fixture),
        "producer_type": str(
            best_detection.get("producer_type")
            or best_detection.get("perception_source")
            or fixture_observation.get("producer_type")
            or "visible_detection"
        ),
        "producer_id": str(
            best_detection.get("producer_id")
            or best_detection.get("model_provenance")
            or best_detection.get("producer_type")
            or fixture_observation.get("producer_id")
            or "visible_detection"
        ),
        "confidence": round(float(confidence), 6),
        "freshness": "current_run",
        "actionability": "actionable",
        "source_observation_id": source_observation_id,
        "promotion_status": "run_local",
        "evidence": {
            "type": "support_estimate",
            "relation": str((best_detection.get("support_estimate") or {}).get("relation") or ""),
            "supporting_observed_object_ids": [
                str(item.get("object_id") or "") for item in supporting
            ],
            "fixture_observation_id": str(fixture_observation.get("source_observation_id") or ""),
            "image_region": (
                best_detection.get("image_region")
                or {"type": "bbox", "value": best_detection.get("image_bbox") or []}
            ),
        },
    }


def _supporting_detections_for_fixture(
    contract: HouseholdRuntimeContract,
    fixture_id: str,
) -> list[dict[str, Any]]:
    supporting = []
    for handle in sorted(contract._detections_by_handle):
        detection = contract._detections_by_handle[handle]
        support = detection.get("support_estimate") or {}
        if str(support.get("fixture_id") or "") != fixture_id:
            continue
        supporting.append(dict(detection))
    return supporting


def _fixture_anchor_evidence_rank(anchor: dict[str, Any]) -> tuple[int, int, float]:
    evidence = anchor.get("evidence") if isinstance(anchor.get("evidence"), dict) else {}
    supporting_count = len(evidence.get("supporting_observed_object_ids") or [])
    image_region = (
        evidence.get("image_region") if isinstance(evidence.get("image_region"), dict) else {}
    )
    has_image_region = int(bool(image_region.get("value")))
    return (
        supporting_count,
        has_image_region,
        _float_or_zero(anchor.get("confidence")),
    )


def _fixture_anchor_viewpoint_key(anchor: dict[str, Any]) -> tuple[str, str, str, str, str]:
    pose = anchor.get("pose") if isinstance(anchor.get("pose"), dict) else {}
    pose_key = ",".join(str(round(_float_or_zero(pose.get(key)), 4)) for key in ("x", "y", "yaw"))
    return (
        str(anchor.get("category") or ""),
        str(anchor.get("room_id") or ""),
        str(anchor.get("waypoint_id") or ""),
        pose_key,
        str(anchor.get("source_observation_id") or ""),
    )


def _norm(value: Any) -> str:
    return re.sub(r"[^a-z0-9]+", "", str(value).lower())
