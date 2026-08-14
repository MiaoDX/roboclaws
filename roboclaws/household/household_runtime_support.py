from __future__ import annotations

import re
from typing import Any

from roboclaws.core.task_intents import normalize_household_intent
from roboclaws.household import (
    realworld_agent_view_contract,
    realworld_done_readiness,
    realworld_runtime_map_contract,
    realworld_visual_candidates,
)
from roboclaws.household.manipulation_contract import API_SEMANTIC_PROVENANCE
from roboclaws.household.realworld_contract_fixture_projection import (
    _OBJECT_CATEGORY_TARGETS,
    _first_matching_fixture,
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

REALWORLD_CONTRACT = "realworld_cleanup_v1"
REAL_ROBOT_MAP_BUNDLE_SCHEMA = "real_robot_map_bundle_v1"
RUNTIME_METRIC_MAP_SCHEMA = "runtime_metric_map_v1"
INSPECTION_OBSERVATION_SCHEMA = "target_inspection_observation_v1"
CLEANUP_WORKLIST_SCHEMA = "cleanup_worklist_v1"
CLEANUP_POLICY_TRACE_SCHEMA = "cleanup_policy_trace_v1"
REAL_ROBOT_READINESS_SCHEMA = "real_robot_readiness_v1"
DETERMINISTIC_SWEEP_POLICY = "deterministic_sweep_baseline"
DEFAULT_REALWORLD_TASK = "帮我收拾这个房间"
VISIBLE_OBJECT_DETECTIONS_MODE = "visible_object_detections"
RAW_FPV_ONLY_MODE = "raw_fpv_only"
CAMERA_MODEL_POLICY_MODE = "camera_model_policy"
WORLD_LABELS_DETECTION_POLICY = "world_labels"
SANITIZED_VISIBLE_OBJECT_DETECTIONS_POLICY = "sanitized_visible_object_detections"
VISIBLE_DETECTION_EXPOSURE_POLICIES = frozenset(
    (WORLD_LABELS_DETECTION_POLICY, SANITIZED_VISIBLE_OBJECT_DETECTIONS_POLICY)
)
CAMERA_MODEL_POLICY_SCHEMA = "camera_model_policy_v1"
CAMERA_MODEL_POLICY_NAME = "camera_model_policy_baseline"
MODEL_DECLARED_OBSERVATION_SCHEMA = "model_declared_observation_v1"
MODEL_DECLARED_OBSERVATIONS_SCHEMA = "model_declared_observations_v1"
VISUAL_GROUNDING_EVIDENCE_SCHEMA = realworld_visual_candidates.VISUAL_GROUNDING_EVIDENCE_SCHEMA
DONE_READINESS_SCHEMA = "done_readiness_v1"
DONE_READINESS_POLICY_RAW_FPV = realworld_done_readiness.DONE_READINESS_POLICY_RAW_FPV
DONE_READINESS_POLICY_EXPLICIT = realworld_done_readiness.DONE_READINESS_POLICY_EXPLICIT
MODEL_DECLARED_OBSERVATION_SOURCE = "model_declared_observation"
MAIN_CLEANUP_AGENT_PRODUCER = realworld_visual_candidates.MAIN_CLEANUP_AGENT_PRODUCER
TEST_AGENT_PRODUCER = realworld_visual_candidates.TEST_AGENT_PRODUCER
SIMULATED_CAMERA_MODEL_PROVENANCE = realworld_visual_candidates.SIMULATED_CAMERA_MODEL_PROVENANCE
SANITIZED_VISIBLE_OBJECT_DETECTIONS_PROVENANCE = "sanitized_visible_object_detections"
WORLD_PUBLIC_LABELS_PROFILE = "world-public-labels"
_visual_candidates = realworld_visual_candidates
VISUAL_CANDIDATE_ALREADY_HANDLED_REASON = _visual_candidates.VISUAL_CANDIDATE_ALREADY_HANDLED_REASON
VISUAL_EVIDENCE_REVIEWABLE_STATUS = realworld_visual_candidates.VISUAL_EVIDENCE_REVIEWABLE_STATUS
VISUAL_EVIDENCE_NOT_REVIEWABLE_STATUS = _visual_candidates.VISUAL_EVIDENCE_NOT_REVIEWABLE_STATUS
CANDIDATE_STATE_SEMANTIC = realworld_visual_candidates.CANDIDATE_STATE_SEMANTIC
CANDIDATE_STATE_VISUALLY_CONFIRMED = realworld_visual_candidates.CANDIDATE_STATE_VISUALLY_CONFIRMED
CANDIDATE_STATE_NAVIGATION_AUTHORIZED = _visual_candidates.CANDIDATE_STATE_NAVIGATION_AUTHORIZED
VISUAL_GROUNDING_CATEGORY_HINTS = realworld_visual_candidates.VISUAL_GROUNDING_CATEGORY_HINTS
REALWORLD_PERCEPTION_MODES = frozenset(
    (VISIBLE_OBJECT_DETECTIONS_MODE, RAW_FPV_ONLY_MODE, CAMERA_MODEL_POLICY_MODE)
)
_NON_ACTIONABLE_HANDLE_STATES = frozenset({"placed", "placed_closed", "skipped", "stale"})
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


def infer_target_fixture_for_detection(
    detection: dict[str, Any],
    static_fixture_projection: dict[str, Any],
) -> dict[str, Any] | None:
    return realworld_runtime_map_contract.infer_target_fixture_for_detection(
        detection,
        static_fixture_projection,
        norm=_norm,
        object_category_targets=_OBJECT_CATEGORY_TARGETS,
        first_matching_fixture=_first_matching_fixture,
        fixture_requires_open=_fixture_requires_open,
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
