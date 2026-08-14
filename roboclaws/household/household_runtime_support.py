from __future__ import annotations

import re
from typing import Any

from roboclaws.core.task_intents import normalize_household_intent
from roboclaws.household import (
    realworld_agent_view_contract,
    realworld_runtime_map_contract,
    realworld_visual_candidates,
)
from roboclaws.household.manipulation_contract import API_SEMANTIC_PROVENANCE
from roboclaws.household.realworld_contract_fixture_projection import (
    _fixture_requires_open,
)
from roboclaws.household.realworld_contract_projection import (
    _map_bundle_fields_present,
    _pose_stamped_waypoints_present,
)
from roboclaws.household.realworld_policy_trace import (
    cleanup_policy_trace_from_events as _cleanup_policy_trace_from_events,
)
from roboclaws.maps.route import SIM_COSTMAP_PLANNER

CLEANUP_POLICY_TRACE_SCHEMA = "cleanup_policy_trace_v1"
REAL_ROBOT_READINESS_SCHEMA = "real_robot_readiness_v1"
VISIBLE_OBJECT_DETECTIONS_MODE = "visible_object_detections"
_FORBIDDEN_AGENT_VIEW_KEYS = frozenset(
    {
        "generated_mess_set",
        "generated_mess_count",
        "environment_setup",
        "relocation_policy",
        "relocation_count",
        "relocated_object_ids",
        "relocated_objects",
        "before_relocation_positions",
        "after_relocation_positions",
        "target_count",
        "acceptable_destination_sets",
        "valid_receptacle_ids",
        "private_manifest",
        "is_misplaced",
        "global_movable_object_inventory",
        "target_receptacle_id",
    }
)


def _relative_pose_delta(
    forward_m: Any = 0.0,
    lateral_m: Any = 0.0,
    yaw_delta_deg: Any = 0.0,
) -> dict[str, float]:
    return {
        "forward_m": round(_float_or_zero(forward_m), 4),
        "lateral_m": round(_float_or_zero(lateral_m), 4),
        "yaw_delta_deg": round(_float_or_zero(yaw_delta_deg), 4),
    }


def _runtime_map_producer_summary(
    observed_objects: list[dict[str, Any]],
    *,
    public_semantic_anchors: list[dict[str, Any]] | None = None,
    map_update_candidates: list[dict[str, Any]] | None = None,
    target_candidates: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    return realworld_runtime_map_contract.runtime_map_producer_summary(
        observed_objects,
        public_semantic_anchors=public_semantic_anchors,
        map_update_candidates=map_update_candidates,
        target_candidates=target_candidates,
    )


def _visual_grounding_evidence_for_candidate(
    candidate: dict[str, Any],
    *,
    fallback_image_bbox: Any = None,
    grounding_status: str = "",
) -> dict[str, Any]:
    return realworld_visual_candidates._visual_grounding_evidence_for_candidate(
        candidate,
        fallback_image_bbox=fallback_image_bbox,
        grounding_status=grounding_status,
        assert_no_forbidden_agent_view_keys=_assert_no_forbidden_agent_view_keys,
    )


_candidate_state = realworld_visual_candidates._candidate_state
_float_or_zero = realworld_visual_candidates._float_or_zero
_clamp = realworld_visual_candidates._clamp
_average_duplicate_rate = realworld_visual_candidates._average_duplicate_rate
_declared_category_matches_object = realworld_visual_candidates._declared_category_matches_object


def _candidate_actionability_status(candidate: dict[str, Any]) -> str:
    return realworld_visual_candidates._candidate_actionability_status(
        candidate,
        visual_grounding_evidence_builder=_visual_grounding_evidence_for_candidate,
    )


def _visual_candidate_validation_error(
    candidate: Any,
    *,
    require_target_fixture_id: bool = True,
    perception_mode: str = VISIBLE_OBJECT_DETECTIONS_MODE,
    producer_type: str = "",
) -> dict[str, str] | None:
    return realworld_visual_candidates._visual_candidate_validation_error(
        candidate,
        require_target_fixture_id=require_target_fixture_id,
        perception_mode=perception_mode,
        producer_type=producer_type,
    )


def _target_fixture_from_detection_anchor(detection: dict[str, Any]) -> dict[str, Any] | None:
    return realworld_runtime_map_contract.target_fixture_from_detection_anchor(
        detection,
        fixture_requires_open=_fixture_requires_open,
    )


def forbidden_agent_view_keys() -> set[str]:
    return realworld_agent_view_contract.forbidden_agent_view_keys(_FORBIDDEN_AGENT_VIEW_KEYS)


def cleanup_policy_trace_from_events(
    trace_events: list[dict[str, Any]],
    agent_view: dict[str, Any],
) -> dict[str, Any]:
    return realworld_agent_view_contract.cleanup_policy_trace_from_events(
        trace_events,
        agent_view,
        builder=_cleanup_policy_trace_from_events,
        schema=CLEANUP_POLICY_TRACE_SCHEMA,
    )


def real_robot_readiness_from_events(
    *,
    agent_view: dict[str, Any],
    trace_events: list[dict[str, Any]],
    robot_view_steps: list[dict[str, Any]],
) -> dict[str, Any]:
    return realworld_agent_view_contract.real_robot_readiness_from_events(
        agent_view=agent_view,
        trace_events=trace_events,
        robot_view_steps=robot_view_steps,
        schema=REAL_ROBOT_READINESS_SCHEMA,
        api_semantic_provenance=API_SEMANTIC_PROVENANCE,
        sim_costmap_planner=SIM_COSTMAP_PLANNER,
        map_bundle_fields_present=_map_bundle_fields_present,
        pose_stamped_waypoints_present=_pose_stamped_waypoints_present,
        assert_no_forbidden_agent_view_keys=_assert_no_forbidden_agent_view_keys,
    )


def _safe_anchor_id(value: str) -> str:
    safe = re.sub(r"[^a-zA-Z0-9_]+", "_", value).strip("_")
    return safe or "unknown"


def _vec2(value: Any) -> tuple[float, float] | None:
    if not isinstance(value, (list, tuple)) or len(value) < 2:
        return None
    try:
        return (float(value[0]), float(value[1]))
    except (TypeError, ValueError):
        return None


def _norm(value: Any) -> str:
    return re.sub(r"[^a-z0-9]+", "", str(value).lower())


def _assert_no_forbidden_agent_view_keys(payload: Any) -> None:
    realworld_agent_view_contract.assert_no_forbidden_agent_view_keys(
        payload,
        _FORBIDDEN_AGENT_VIEW_KEYS,
    )


def _strip_forbidden_agent_view_keys(payload: Any) -> Any:
    return realworld_agent_view_contract.strip_forbidden_agent_view_keys(
        payload,
        _FORBIDDEN_AGENT_VIEW_KEYS,
    )


def _public_acceptance_config(config: dict[str, Any] | None) -> dict[str, Any]:
    return realworld_agent_view_contract.public_acceptance_config(
        config,
        normalize_household_intent=normalize_household_intent,
        assert_no_forbidden_agent_view_keys=_assert_no_forbidden_agent_view_keys,
    )


def _public_success_threshold(count: int | None) -> int:
    return realworld_agent_view_contract.public_success_threshold(count)


def _positive_int(value: Any) -> int | None:
    return realworld_agent_view_contract.positive_int(value)


def _nonnegative_int(value: Any) -> int:
    return realworld_agent_view_contract.nonnegative_int(value)
