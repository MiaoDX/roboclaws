from __future__ import annotations

from typing import Any

from roboclaws.household import agent_view as agent_view_module
from roboclaws.household.household_runtime_contract import (
    CAMERA_MODEL_POLICY_MODE,
    CAMERA_MODEL_POLICY_SCHEMA,
    CLEANUP_WORKLIST_SCHEMA,
    MAIN_CLEANUP_AGENT_PRODUCER,
    MODEL_DECLARED_OBSERVATION_SOURCE,
    REALWORLD_CONTRACT,
    RUNTIME_METRIC_MAP_SCHEMA,
    SIMULATED_CAMERA_MODEL_PROVENANCE,
    forbidden_agent_view_keys,
)
from roboclaws.household.profiles import CAMERA_GROUNDED_LABELS_LANE
from roboclaws.household.visual_grounding import EXTERNAL_VISUAL_GROUNDING_PROVENANCE


def assert_public_agent_view(
    agent_view: dict[str, Any],
    *,
    open_ended_intent: bool = False,
    map_build: bool = False,
) -> None:
    agent_view_module.require_agent_view(agent_view)
    _assert_agent_view_core(agent_view)
    runtime_map = agent_view_module.runtime_metric_map(agent_view)
    if runtime_map:
        assert_runtime_metric_map(runtime_map, agent_view=agent_view, map_build=map_build)
    if not map_build:
        _assert_cleanup_worklist(agent_view)
    _assert_policy_view(agent_view)
    _assert_no_forbidden_keys(agent_view)
    if agent_view_module.perception_mode(agent_view) == "raw_fpv_only":
        _assert_raw_fpv_agent_view(agent_view)
        return
    if agent_view_module.perception_mode(agent_view) == CAMERA_MODEL_POLICY_MODE:
        _assert_camera_model_agent_view(
            agent_view,
            open_ended_intent=open_ended_intent,
            map_build=map_build,
        )
        return
    _assert_visible_detection_agent_view(
        agent_view,
        open_ended_intent=open_ended_intent,
        map_build=map_build,
    )


def assert_runtime_metric_map(
    runtime_metric_map: dict[str, Any],
    *,
    agent_view: dict[str, Any],
    map_build: bool = False,
) -> None:
    _assert_runtime_map_core(runtime_metric_map)
    _assert_static_map(runtime_metric_map)
    _assert_public_semantic_anchors(runtime_metric_map)
    _assert_runtime_observed_objects(runtime_metric_map, agent_view)
    if not map_build:
        _assert_target_candidates(runtime_metric_map)
        _assert_target_search_summary(runtime_metric_map)
    _assert_map_update_candidates(runtime_metric_map)
    _assert_no_forbidden_keys(runtime_metric_map)


def _assert_agent_view_core(agent_view: dict[str, Any]) -> None:
    assert agent_view.get("contract") == REALWORLD_CONTRACT, agent_view
    assert agent_view.get("schema") == agent_view_module.AGENT_VIEW_SCHEMA, agent_view
    assert agent_view.get("section_metadata"), agent_view
    assert agent_view_module.forbidden_private_fields_absent(agent_view), agent_view
    assert agent_view_module.base_metric_map(agent_view), agent_view
    assert "static_fixture_projection" not in agent_view, agent_view
    assert "observed_objects" not in agent_view, agent_view
    assert "objects" not in agent_view_module.base_metric_map(agent_view), agent_view


def _assert_cleanup_worklist(agent_view: dict[str, Any]) -> None:
    worklist = agent_view_module.cleanup_worklist(agent_view)
    if not worklist:
        return
    assert worklist.get("schema") == CLEANUP_WORKLIST_SCHEMA, worklist
    assert worklist.get("waypoint_source") == "generated_exploration_candidate", worklist


def _assert_policy_view(agent_view: dict[str, Any]) -> None:
    policy_view = agent_view_module.policy_view(agent_view)
    if policy_view:
        assert policy_view.get("chase_camera_policy_input", False) is False, policy_view


def _assert_raw_fpv_agent_view(agent_view: dict[str, Any]) -> None:
    assert agent_view_module.structured_detections_available(agent_view) is False, agent_view
    raw = agent_view_module.raw_fpv_observations(agent_view)
    assert raw, agent_view
    for item in raw:
        assert item.get("perception_mode") == "raw_fpv_only", item
        assert item.get("structured_detections_available") is False, item
        forbidden = {"category", "name", "support_estimate", "target_receptacle_id"}
        assert not forbidden.intersection(item), item
    declared = agent_view_module.model_declared_observations(agent_view)
    observed = agent_view_module.observed_objects(agent_view)
    if declared:
        assert observed, agent_view
        for item in observed:
            assert item.get("perception_source") == MODEL_DECLARED_OBSERVATION_SOURCE, item
            assert item.get("source_observation_id"), item
            assert "target_receptacle_id" not in item, item
    else:
        assert not observed, agent_view


def _assert_camera_model_agent_view(
    agent_view: dict[str, Any],
    *,
    open_ended_intent: bool,
    map_build: bool,
) -> None:
    assert agent_view_module.structured_detections_available(agent_view) is False, agent_view
    raw = agent_view_module.raw_fpv_observations(agent_view)
    assert raw, agent_view
    evidence = agent_view_module.camera_model_policy_evidence(agent_view)
    assert evidence.get("schema") == CAMERA_MODEL_POLICY_SCHEMA, evidence
    assert evidence.get("enabled") is True, evidence
    observed = agent_view_module.observed_objects(agent_view)
    if not observed and (open_ended_intent or map_build):
        assert agent_view_module.model_declared_observations(agent_view) == [], agent_view
        if open_ended_intent:
            assert agent_view_module.runtime_metric_map(agent_view).get("target_candidates"), (
                agent_view
            )
        return
    assert observed, agent_view
    for item in observed:
        _assert_camera_model_observed_object(item)


def _assert_camera_model_observed_object(item: dict[str, Any]) -> None:
    allowed_producer_types = {
        CAMERA_GROUNDED_LABELS_LANE,
        SIMULATED_CAMERA_MODEL_PROVENANCE,
        EXTERNAL_VISUAL_GROUNDING_PROVENANCE,
        MAIN_CLEANUP_AGENT_PRODUCER,
    }
    assert str(item.get("object_id", "")).startswith("observed_"), item
    assert item.get("perception_source") in {
        CAMERA_MODEL_POLICY_MODE,
        MODEL_DECLARED_OBSERVATION_SOURCE,
    }, item
    assert item.get("producer_type") in allowed_producer_types, item
    assert item.get("model_provenance") in {
        CAMERA_GROUNDED_LABELS_LANE,
        SIMULATED_CAMERA_MODEL_PROVENANCE,
        EXTERNAL_VISUAL_GROUNDING_PROVENANCE,
        MAIN_CLEANUP_AGENT_PRODUCER,
        None,
    }, item
    assert item.get("source_observation_id"), item
    _assert_observed_object_support(item)
    assert "is_misplaced" not in item, item
    assert "target_receptacle_id" not in item, item


def _assert_observed_object_support(item: dict[str, Any]) -> None:
    support = item.get("support_estimate") or {}
    if support:
        assert support.get("source") in {
            CAMERA_MODEL_POLICY_MODE,
            MODEL_DECLARED_OBSERVATION_SOURCE,
            "public_semantic_anchor",
        }, item
    else:
        assert item.get("producer_type") in {
            EXTERNAL_VISUAL_GROUNDING_PROVENANCE,
            MAIN_CLEANUP_AGENT_PRODUCER,
        }, item


def _assert_visible_detection_agent_view(
    agent_view: dict[str, Any],
    *,
    open_ended_intent: bool,
    map_build: bool,
) -> None:
    observed = agent_view_module.observed_objects(agent_view)
    if not observed and (open_ended_intent or map_build):
        assert agent_view_module.perception_mode(agent_view) == "visible_object_detections", (
            agent_view
        )
        assert agent_view_module.structured_detections_available(agent_view) is True, agent_view
        assert agent_view_module.raw_fpv_observations(agent_view) == [], agent_view
        assert agent_view_module.model_declared_observations(agent_view) == [], agent_view
        assert agent_view_module.runtime_metric_map(agent_view).get("target_candidates"), agent_view
        return
    assert observed, agent_view
    for item in observed:
        assert str(item.get("object_id", "")).startswith("observed_"), item
        assert "support_estimate" in item, item
        assert "is_misplaced" not in item, item
        assert "target_receptacle_id" not in item, item


def _assert_runtime_map_core(runtime_metric_map: dict[str, Any]) -> None:
    assert runtime_metric_map.get("schema") == RUNTIME_METRIC_MAP_SCHEMA, runtime_metric_map
    assert runtime_metric_map.get("contract") == REALWORLD_CONTRACT, runtime_metric_map
    assert runtime_metric_map.get("source_map_mutated") is False, runtime_metric_map
    assert runtime_metric_map.get("private_truth_included") is False, runtime_metric_map


def _assert_static_map(runtime_metric_map: dict[str, Any]) -> None:
    static_map = runtime_metric_map.get("static_map") or {}
    assert isinstance(static_map.get("rooms") or [], list), runtime_metric_map
    assert isinstance(static_map.get("fixtures") or [], list), runtime_metric_map
    assert isinstance(static_map.get("inspection_waypoints") or [], list), runtime_metric_map
    assert static_map.get("contains_runtime_observations") is False, static_map
    for fixture in static_map.get("fixtures") or []:
        assert "observed_objects" not in fixture, fixture
        assert "objects" not in fixture, fixture
        assert not str(fixture.get("fixture_id") or "").startswith("observed_"), fixture


def _assert_public_semantic_anchors(runtime_metric_map: dict[str, Any]) -> None:
    anchors = runtime_metric_map.get("public_semantic_anchors") or []
    assert isinstance(anchors, list), runtime_metric_map
    for anchor in anchors:
        assert str(anchor.get("anchor_id") or ""), anchor
        assert str(anchor.get("anchor_id") or "").startswith("anchor_"), anchor
        assert anchor.get("anchor_type") in {
            "room_area",
            "surface",
            "receptacle",
            "fixture",
            "observation_waypoint",
        }, anchor
        for key in (
            "category",
            "label",
            "waypoint_id",
            "affordances",
            "producer_type",
            "producer_id",
            "confidence",
            "source_observation_id",
            "promotion_status",
        ):
            assert key in anchor, anchor

        assert isinstance(anchor.get("affordances") or [], list), anchor
        assert anchor.get("promotion_status") != "promoted", anchor
        assert not str(anchor.get("anchor_id") or "").startswith("observed_"), anchor
        assert "target_receptacle_id" not in anchor, anchor
        assert "is_misplaced" not in anchor, anchor


def _assert_runtime_observed_objects(
    runtime_metric_map: dict[str, Any],
    agent_view: dict[str, Any],
) -> None:
    observed = runtime_metric_map.get("observed_objects") or []
    agent_observed = agent_view_module.observed_objects(agent_view)
    current_observed = [item for item in observed if item.get("freshness") != "prior"]
    assert len(current_observed) == len(agent_observed), (runtime_metric_map, agent_view)
    for item in observed:
        assert str(item.get("object_id", "")).startswith("observed_"), item
        for key in (
            "category",
            "room_id",
            "waypoint_id",
            "source_observation_id",
            "image_region",
            "producer_type",
            "producer_id",
            "confidence",
            "freshness",
            "actionability",
            "state",
        ):
            assert key in item, item
        assert item.get("freshness") in {"current_run", "prior"}, item
        if item.get("freshness") == "prior":
            assert item.get("actionability") != "actionable", item
        assert "target_receptacle_id" not in item, item
        assert "is_misplaced" not in item, item


def _assert_target_candidates(runtime_metric_map: dict[str, Any]) -> None:
    target_candidates = runtime_metric_map.get("target_candidates") or []
    assert isinstance(target_candidates, list), runtime_metric_map
    assert target_candidates, runtime_metric_map
    allowed_actionability = {
        "query_unmatched",
        "visible_only",
        "anchor_unbound",
        "unreachable",
        "needs_observe",
        "actionable",
    }
    for candidate in target_candidates:
        _assert_target_candidate(candidate, allowed_actionability)


def _assert_target_candidate(candidate: dict[str, Any], allowed_actionability: set[str]) -> None:
    for key in (
        "candidate_id",
        "candidate_type",
        "query",
        "label",
        "category",
        "evidence_lane",
        "producer_type",
        "producer_id",
        "target_actionability_status",
        "confidence",
        "inspection_budget",
    ):
        assert key in candidate, candidate
    assert candidate.get("target_actionability_status") in allowed_actionability, candidate
    assert candidate.get("actionability") == candidate.get("target_actionability_status"), candidate
    assert isinstance(candidate.get("inspection_budget") or {}, dict), candidate
    assert "target_receptacle_id" not in candidate, candidate
    assert "is_misplaced" not in candidate, candidate
    if candidate.get("target_actionability_status") != "actionable":
        assert candidate.get("rejection_reason"), candidate


def _assert_target_search_summary(runtime_metric_map: dict[str, Any]) -> None:
    target_candidates = runtime_metric_map.get("target_candidates") or []
    target_search = runtime_metric_map.get("target_search_summary") or {}
    assert target_search.get("schema") == "target_search_summary_v1", runtime_metric_map
    assert target_search.get("private_truth_included") is False, target_search
    assert target_search.get("candidate_count") == len(target_candidates), target_search
    viewpoint_budget = target_search.get("viewpoint_budget") or {}
    assert "total_public_waypoints" in viewpoint_budget, target_search
    assert "visited_waypoint_count" in viewpoint_budget, target_search
    camera_budget = target_search.get("camera_adjustment_budget") or {}
    assert "attempt_count" in camera_budget, target_search
    assert isinstance(target_search.get("inspection_observations") or [], list), target_search


def _assert_map_update_candidates(runtime_metric_map: dict[str, Any]) -> None:
    assert isinstance(runtime_metric_map.get("map_update_candidates") or [], list), (
        runtime_metric_map
    )
    for candidate in runtime_metric_map.get("map_update_candidates") or []:
        assert "target_receptacle_id" not in candidate, candidate
        assert "is_misplaced" not in candidate, candidate
        assert candidate.get("promotion_status") != "promoted", candidate


def _assert_no_forbidden_keys(payload: Any) -> None:
    if isinstance(payload, dict):
        forbidden = forbidden_agent_view_keys().intersection(payload)
        assert not forbidden, (sorted(forbidden), payload)
        for value in payload.values():
            _assert_no_forbidden_keys(value)
    elif isinstance(payload, list):
        for value in payload:
            _assert_no_forbidden_keys(value)
