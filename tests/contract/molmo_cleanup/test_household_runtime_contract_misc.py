from __future__ import annotations

from roboclaws.household import agent_view as agent_view_module
from roboclaws.household.household_backend_contract import HouseholdBackendSession
from roboclaws.household.household_runtime_contract import (
    RAW_FPV_ONLY_MODE,
)
from roboclaws.household.scenario import build_cleanup_scenario
from tests.contract.molmo_cleanup.household_runtime_contract_support import (
    _assert_no_forbidden_keys,
    _confirm_world_label_detection,
    _contract,
    _first_detection_by_category,
    _first_non_empty_observation,
    _observe_all_public_waypoints,
    _public_destination_fixture_for_detection,
)


def _assert_waypoint_identity(
    candidate: dict[str, object], *, source_waypoint_id: str, generated_waypoint_id: str
) -> None:
    assert candidate["source_waypoint_id"] == source_waypoint_id
    assert candidate["generated_inspection_waypoint_id"] == generated_waypoint_id


def test_target_candidates_force_adaptive_public_reinspection_path() -> None:
    contract = _contract(HouseholdBackendSession(build_cleanup_scenario(seed=7)))
    first_observation = _first_non_empty_observation(contract)
    handle = first_observation["visible_object_detections"][0]["object_id"]

    pre_scan_map = agent_view_module.runtime_metric_map(contract.agent_view_payload())
    pre_scan_candidate = next(
        item for item in pre_scan_map["target_candidates"] if item.get("object_id") == handle
    )

    assert pre_scan_candidate["target_actionability_status"] == "visible_only"
    assert pre_scan_candidate["verified_navigation"] is False
    assert pre_scan_candidate["rejection_reason"] == "visual_evidence_not_reviewable"
    generated_waypoint_id = pre_scan_candidate["generated_inspection_waypoint_id"]
    generated_waypoint = next(
        item
        for item in pre_scan_map["generated_target_inspection_candidates"]
        if item["waypoint_id"] == generated_waypoint_id
    )
    generated_target_candidate = next(
        item
        for item in pre_scan_map["target_candidates"]
        if item["candidate_type"] == "generated_target_inspection_candidate"
        and item["waypoint_id"] == generated_waypoint_id
    )
    metric_waypoints = contract.metric_map()["inspection_waypoints"]
    worklist_candidate = next(
        item
        for item in contract.cleanup_worklist_payload()["objects"]
        if item["object_id"] == handle
    )

    assert generated_waypoint["waypoint_source"] == "generated_target_inspection_candidate"
    assert generated_waypoint["verified_navigation"] is True
    assert generated_waypoint["source_target_candidate_id"] == pre_scan_candidate["candidate_id"]
    assert generated_target_candidate["target_actionability_status"] == "needs_observe"
    assert (
        generated_target_candidate["source_target_candidate_id"]
        == pre_scan_candidate["candidate_id"]
    )
    assert generated_waypoint_id in {str(item["waypoint_id"]) for item in metric_waypoints}
    _assert_waypoint_identity(
        worklist_candidate,
        source_waypoint_id=str(first_observation["waypoint_id"]),
        generated_waypoint_id=generated_waypoint_id,
    )
    blocked_navigation = contract.navigate_to_object(handle)
    assert blocked_navigation["ok"] is False
    assert blocked_navigation["error_reason"] == "visual_evidence_not_reviewable"
    assert blocked_navigation["required_next_tool"] == "adjust_camera"
    assert "adjust_camera" in blocked_navigation["recovery_tool_options"]

    waypoint_navigation = contract.navigate_to_waypoint(generated_waypoint_id)
    waypoint_observation = contract.observe()
    waypoint_candidate = next(
        item
        for item in contract.agent_view_payload()["runtime_metric_map"]["target_candidates"]
        if item["candidate_type"] == "generated_target_inspection_candidate"
        and item["waypoint_id"] == generated_waypoint_id
    )

    assert waypoint_navigation["ok"] is True
    assert waypoint_navigation["pose_source"] == "inspection_waypoint"
    assert waypoint_observation["waypoint_id"] == generated_waypoint_id
    assert waypoint_candidate["target_actionability_status"] == "actionable"
    assert waypoint_candidate["inspection_budget"]["observed"] is True

    adjustment = contract.adjust_camera(yaw_delta_deg=15)
    assert adjustment["ok"] is True
    assert adjustment["camera_offset"]["yaw_delta_deg"] == 15.0
    confirmed_observation = contract.observe()
    confirmed = next(
        item
        for item in confirmed_observation["visible_object_detections"]
        if item["object_id"] == handle
    )
    post_scan_map = contract.agent_view_payload()["runtime_metric_map"]
    post_scan_candidate = next(
        item for item in post_scan_map["target_candidates"] if item.get("object_id") == handle
    )
    summary = post_scan_map["target_search_summary"]

    assert confirmed["candidate_state"] == "navigation_authorized"
    assert post_scan_candidate["target_actionability_status"] == "actionable"
    assert post_scan_candidate["verified_navigation"] is True
    assert post_scan_candidate["visual_grounding_evidence"]["reviewability_status"] == "reviewable"
    assert summary["camera_adjustment_budget"]["attempt_count"] == 1
    assert summary["inspection_observations"][-1]["camera_adjusted"] is True
    assert any(
        item["changed_candidate_state_count"] >= 1 for item in summary["inspection_observations"]
    )
    assert contract.navigate_to_object(handle)["ok"] is True
    _assert_no_forbidden_keys(post_scan_map)


def test_target_query_recovery_not_found_includes_public_search_budget() -> None:
    contract = _contract(
        HouseholdBackendSession(build_cleanup_scenario(seed=7)),
    )
    metric_map = _observe_all_public_waypoints(contract)

    resolution = contract.resolve_target_query("purple piano", operation="inspect")

    assert resolution["ok"] is True
    assert resolution["status"] == "not_found"
    assert resolution["match_count"] == 0
    assert resolution["exhausted_public_search_budget"] is True
    assert resolution["missing_target_reason"] == "public_search_budget_exhausted"
    assert resolution["public_search_budget"]["inspection_observation_count"] >= len(
        metric_map["inspection_waypoints"]
    )
    _assert_no_forbidden_keys(resolution)


def test_realworld_detected_handle_can_be_cleaned_without_private_manifest() -> None:
    contract = _contract(HouseholdBackendSession(build_cleanup_scenario(seed=7)))
    detection = _confirm_world_label_detection(
        contract,
        _first_detection_by_category(contract, "dish"),
    )
    target_fixture = _public_destination_fixture_for_detection(contract, detection)
    navigated_object = contract.navigate_to_object(detection["object_id"])
    picked = contract.pick(detection["object_id"])
    navigated_target = contract.navigate_to_receptacle(str(target_fixture["fixture_id"]))
    placed = contract.place(str(target_fixture["fixture_id"]))

    assert navigated_object["ok"] is True
    assert picked["ok"] is True
    assert picked["object_id"].startswith("observed_")
    assert navigated_target["ok"] is True
    assert placed["ok"] is True
    assert str(placed["fixture_id"]).startswith("anchor_fixture_")
    assert placed["location_id"] == "sink_01"


def test_realworld_camera_raw_empty_declare_does_not_fall_back_to_sim_labels() -> None:
    contract = _contract(
        HouseholdBackendSession(build_cleanup_scenario(seed=7)),
        perception_mode=RAW_FPV_ONLY_MODE,
    )

    observation = contract.observe()
    response = contract.declare_visual_candidates(
        observation["raw_fpv_observation"]["observation_id"],
    )

    assert response["ok"] is False
    assert response["error_reason"] == "empty_raw_fpv_candidate_registration"
    assert contract.model_declared_observations_payload()["observation_count"] == 0
    assert contract.camera_model_policy_payload()["event_count"] == 0
    _assert_no_forbidden_keys(response)
