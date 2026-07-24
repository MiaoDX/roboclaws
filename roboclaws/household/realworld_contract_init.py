from __future__ import annotations

from pathlib import Path
from typing import Any

from roboclaws.household import (
    realworld_contract_projection,
    realworld_runtime_map_contract,
    realworld_runtime_map_targets,
)
from roboclaws.maps.bundle import validate_base_metric_map_v1_bundle
from roboclaws.maps.project import (
    metric_map_from_bundle,
    occupancy_grid_from_bundle,
    static_landmarks_from_bundle,
)


def validate_contract_options(
    *,
    static_fixture_projection_mode: str,
    perception_mode: str,
) -> None:
    helpers = _contract_helpers()
    if static_fixture_projection_mode not in {"room_only", "exact_fixtures"}:
        raise ValueError("static_fixture_projection_mode must be room_only or exact_fixtures")
    if perception_mode not in helpers.REALWORLD_PERCEPTION_MODES:
        allowed = ", ".join(sorted(helpers.REALWORLD_PERCEPTION_MODES))
        raise ValueError(f"perception_mode must be one of: {allowed}")


def init_profile_and_acceptance(
    target: Any,
    evidence_lane: str | None,
    public_acceptance_config: dict[str, Any] | None,
) -> None:
    helpers = _contract_helpers()
    target.evidence_lane = _default_public_evidence_lane(target, evidence_lane)
    target.public_acceptance_config = helpers._public_acceptance_config(public_acceptance_config)
    target.task_intent = helpers.normalize_household_intent(
        target.public_acceptance_config.get("task_intent")
    )
    target.sanitize_world_labels = (
        target.perception_mode == helpers.VISIBLE_OBJECT_DETECTIONS_MODE
        and target.evidence_lane == helpers.WORLD_PUBLIC_LABELS_PROFILE
    )
    target.visible_detection_exposure_policy = (
        helpers.SANITIZED_VISIBLE_OBJECT_DETECTIONS_POLICY
        if target.sanitize_world_labels
        else helpers.WORLD_LABELS_DETECTION_POLICY
    )


def init_visual_grounding(
    target: Any,
    *,
    visual_grounding_client: Any,
    visual_grounding_pipeline_id: str,
    visual_grounding_artifact_base_dir: str | Path | None,
    visual_grounding_run_id: str,
) -> None:
    helpers = _contract_helpers()
    target.visual_grounding_client = visual_grounding_client
    target.visual_grounding_pipeline_id = str(
        visual_grounding_pipeline_id
        or getattr(visual_grounding_client, "pipeline_id", "")
        or helpers.SIM_VISUAL_GROUNDING_PIPELINE_ID
    )
    target.visual_grounding_artifact_base_dir = (
        Path(visual_grounding_artifact_base_dir)
        if visual_grounding_artifact_base_dir is not None
        else None
    )
    target.visual_grounding_run_id = visual_grounding_run_id


def init_map_projection(
    target: Any,
    map_bundle_dir: str | Path | None,
) -> None:
    target.map_bundle_dir = Path(map_bundle_dir) if map_bundle_dir is not None else None
    target.map_bundle_validation = None
    target._bundle_metric_map_template = None
    target._bundle_occupancy_grid = None
    target._bundle_static_landmarks_template = None
    if target.map_bundle_dir is None:
        raise ValueError(
            "map_bundle_dir is required for product runtime base inspection_waypoints; "
            "generate or select a canonical Base Metric Map v1 bundle before launch"
        )
    _init_bundle_map_projection(target)


def init_public_map_projection(target: Any) -> None:
    _init_public_map_projection(target)


def initial_waypoint_id(target: Any) -> str:
    if target._public_waypoints:
        return str(target._public_waypoints[0]["waypoint_id"])
    first_waypoint = target._waypoints[0]["waypoint_id"] if target._waypoints else ""
    return str(first_waypoint)


def init_runtime_state(target: Any, runtime_map_prior: dict[str, Any] | None) -> None:
    helpers = _contract_helpers()
    target._observed_waypoint_ids = set()
    target._observed_handles_by_object_id = {}
    target._object_ids_by_handle = {}
    target._detections_by_handle = {}
    target._object_lifecycle = {}
    target._raw_fpv_observations = []
    target._private_raw_fpv_bindings_by_observation_id = {}
    target._visible_observation_count = 0
    target._camera_model_policy_events = []
    target._model_declared_observations = []
    target._runtime_map_priors = realworld_runtime_map_contract.runtime_map_priors_from_snapshot(
        runtime_map_prior,
        float_or_zero=helpers._float_or_zero,
        assert_no_forbidden_agent_view_keys=helpers._assert_no_forbidden_agent_view_keys,
    )
    target._runtime_map_anchor_priors = (
        realworld_runtime_map_contract.runtime_map_anchor_priors_from_snapshot(
            runtime_map_prior,
            float_or_zero=helpers._float_or_zero,
            assert_no_forbidden_agent_view_keys=helpers._assert_no_forbidden_agent_view_keys,
        )
    )
    target._runtime_map_room_priors = (
        realworld_runtime_map_contract.runtime_map_room_priors_from_snapshot(
            runtime_map_prior,
            public_room_hint_payload=realworld_contract_projection._public_room_hint_payload,
            assert_no_forbidden_agent_view_keys=helpers._assert_no_forbidden_agent_view_keys,
        )
    )
    target._runtime_prior_digital_twin_capabilities = (
        realworld_runtime_map_contract.runtime_prior_digital_twin_capabilities(
            runtime_map_prior,
            assert_no_forbidden_agent_view_keys=helpers._assert_no_forbidden_agent_view_keys,
        )
    )
    target._public_anchor_ids_by_private_fixture_id = {}
    target._fixture_observations_by_fixture_id = {}
    target._generated_inspection_waypoints = {}
    realworld_runtime_map_targets.seed_public_fixture_anchor_ids_from_prior_anchors(target)
    target._camera_yaw_offset_deg = 0.0
    target._camera_pitch_offset_deg = 0.0
    target._camera_adjustment_events = []
    target._inspection_observations = []
    target._handled_handles = set()
    target._held_handle = None
    target._current_object_handle = None
    target._current_receptacle_for_handle = None
    target._opened_receptacle_for_handle = None
    target._pending_close_receptacle_for_handle = None
    target._initial_locations = target.backend.object_locations()


def _init_bundle_map_projection(target: Any) -> None:
    validation = validate_base_metric_map_v1_bundle(target.map_bundle_dir)
    validation.raise_for_errors(label="Base Metric Map v1 bundle")
    target.map_bundle_validation = validation.as_dict()
    target._bundle_metric_map_template = metric_map_from_bundle(target.map_bundle_dir)
    target._bundle_occupancy_grid = occupancy_grid_from_bundle(target.map_bundle_dir)
    target._bundle_static_landmarks_template = static_landmarks_from_bundle(target.map_bundle_dir)
    target._fixtures = realworld_contract_projection._fixtures_from_bundle_static_landmarks(
        target._bundle_static_landmarks_template
    )
    if not target._fixtures:
        target._fixtures = realworld_contract_projection._fixtures_from_runtime_scenario(
            target.scenario,
            waypoints=target._bundle_metric_map_template.get("inspection_waypoints") or [],
        )
    target._rooms = realworld_contract_projection._rooms_from_bundle_projection(
        target._bundle_metric_map_template,
        target._bundle_static_landmarks_template,
    )
    realworld_contract_projection._attach_runtime_fixture_ids_to_rooms(
        target._rooms,
        target._fixtures,
    )
    target._waypoints = realworld_contract_projection._inspection_waypoints_from_bundle_projection(
        target._bundle_metric_map_template,
        target._bundle_static_landmarks_template,
    )
    target._scene_index_fixture_overlay = (
        realworld_contract_projection._scene_index_public_fixture_overlay(
            backend=target.backend,
            scenario=target.scenario,
            existing_fixtures=target._fixtures,
            fallback_waypoint_id=realworld_contract_projection._first_waypoint_id(
                target._waypoints
            ),
        )
    )
    target._fixtures.update(target._scene_index_fixture_overlay)


def _init_public_map_projection(target: Any) -> None:
    source_metric_map = target._bundle_metric_map_template
    if source_metric_map is None:
        raise AssertionError(
            "product runtime public map projection requires a canonical map bundle"
        )
    target._public_rooms = realworld_contract_projection._public_room_hints_from_metric_map(
        source_metric_map,
        fallback_rooms=target._rooms,
    )
    target._public_fixtures = {}
    target._public_waypoints = realworld_contract_projection._public_base_waypoints_from_artifact(
        source_metric_map,
        public_rooms=target._public_rooms,
    )
    target._private_waypoint_by_public_id = (
        realworld_contract_projection._private_waypoint_map_for_public_base_waypoints(
            target._public_waypoints,
            target._waypoints,
        )
    )


def _contract_helpers() -> Any:
    from roboclaws.household import household_runtime_contract as realworld_contract

    return realworld_contract


def _default_public_evidence_lane(target: Any, evidence_lane: str | None) -> str:
    helpers = _contract_helpers()
    if evidence_lane:
        return str(evidence_lane).strip().lower().replace("_", "-")
    if target.perception_mode == helpers.VISIBLE_OBJECT_DETECTIONS_MODE:
        return helpers.WORLD_PUBLIC_LABELS_PROFILE
    if target.perception_mode == helpers.RAW_FPV_ONLY_MODE:
        return "camera-raw-fpv"
    if target.perception_mode == helpers.CAMERA_MODEL_POLICY_MODE:
        return "camera-grounded-labels"
    return ""
