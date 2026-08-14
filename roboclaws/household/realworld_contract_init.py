from __future__ import annotations

from collections.abc import Callable
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
    static_fixture_projection_mode: str,
    perception_mode: str,
    perception_modes: frozenset[str],
) -> None:
    if static_fixture_projection_mode not in {"room_only", "exact_fixtures"}:
        raise ValueError("static_fixture_projection_mode must be room_only or exact_fixtures")
    if perception_mode not in perception_modes:
        allowed = ", ".join(sorted(perception_modes))
        raise ValueError(f"perception_mode must be one of: {allowed}")


def init_profile_and_acceptance(
    target: Any,
    evidence_lane: str | None,
    public_acceptance_config: dict[str, Any] | None,
    *,
    acceptance_helpers: tuple[
        Callable[[dict[str, Any] | None], dict[str, Any]], Callable[[Any], Any]
    ],
    perception_values: tuple[str, str, str],
    exposure_values: tuple[str, str, str],
) -> None:
    public_acceptance_config_factory, normalize_household_intent = acceptance_helpers
    visible_mode, raw_fpv_mode, camera_model_mode = perception_values
    world_labels_profile, sanitized_policy, world_labels_policy = exposure_values
    target.evidence_lane = _default_public_evidence_lane(
        target,
        evidence_lane,
        perception_values=perception_values,
        world_labels_profile=world_labels_profile,
    )
    target.public_acceptance_config = public_acceptance_config_factory(public_acceptance_config)
    target.task_intent = normalize_household_intent(
        target.public_acceptance_config.get("task_intent")
    )
    target.sanitize_world_labels = (
        target.perception_mode == visible_mode and target.evidence_lane == world_labels_profile
    )
    target.visible_detection_exposure_policy = (
        sanitized_policy if target.sanitize_world_labels else world_labels_policy
    )


def init_visual_grounding(
    target: Any,
    *,
    visual_grounding_client: Any,
    visual_grounding_pipeline_id: str,
    visual_grounding_artifact_base_dir: str | Path | None,
    visual_grounding_run_id: str,
    default_pipeline_id: str,
) -> None:
    target.visual_grounding_client = visual_grounding_client
    target.visual_grounding_pipeline_id = str(
        visual_grounding_pipeline_id
        or getattr(visual_grounding_client, "pipeline_id", "")
        or default_pipeline_id
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


def init_runtime_state(
    target: Any,
    runtime_map_prior: dict[str, Any] | None,
    *,
    snapshot_helpers: tuple[Callable[[Any], float], Callable[[Any], None]],
) -> None:
    float_or_zero, assert_no_forbidden_agent_view_keys = snapshot_helpers
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
        float_or_zero=float_or_zero,
        assert_no_forbidden_agent_view_keys=assert_no_forbidden_agent_view_keys,
    )
    target._runtime_map_anchor_priors = (
        realworld_runtime_map_contract.runtime_map_anchor_priors_from_snapshot(
            runtime_map_prior,
            float_or_zero=float_or_zero,
            assert_no_forbidden_agent_view_keys=assert_no_forbidden_agent_view_keys,
        )
    )
    target._runtime_map_room_priors = (
        realworld_runtime_map_contract.runtime_map_room_priors_from_snapshot(
            runtime_map_prior,
            public_room_hint_payload=realworld_contract_projection._public_room_hint_payload,
            assert_no_forbidden_agent_view_keys=assert_no_forbidden_agent_view_keys,
        )
    )
    target._runtime_prior_digital_twin_capabilities = (
        realworld_runtime_map_contract.runtime_prior_digital_twin_capabilities(
            runtime_map_prior,
            assert_no_forbidden_agent_view_keys=assert_no_forbidden_agent_view_keys,
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
    target._initial_locations = target.contract.object_locations()


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
            session=target.contract,
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


def _default_public_evidence_lane(
    target: Any,
    evidence_lane: str | None,
    *,
    perception_values: tuple[str, str, str],
    world_labels_profile: str,
) -> str:
    visible_mode, raw_fpv_mode, camera_model_mode = perception_values
    if evidence_lane:
        return str(evidence_lane).strip().lower().replace("_", "-")
    if target.perception_mode == visible_mode:
        return world_labels_profile
    if target.perception_mode == raw_fpv_mode:
        return "camera-raw-fpv"
    if target.perception_mode == camera_model_mode:
        return "camera-grounded-labels"
    return ""
