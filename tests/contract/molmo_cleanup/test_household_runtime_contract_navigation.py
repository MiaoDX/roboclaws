from __future__ import annotations

import json

from roboclaws.household.household_backend_contract import HouseholdBackendSession
from roboclaws.household.household_runtime_contract import (
    REALWORLD_CONTRACT,
)
from roboclaws.household.scenario import build_cleanup_scenario
from tests.contract.molmo_cleanup.household_runtime_contract_support import (
    _assert_no_forbidden_keys,
    _contract,
    _first_non_empty_observation,
    _RelativePoseBackend,
)


def test_realworld_public_tools_do_not_expose_private_targets_or_global_inventory() -> None:
    contract = _contract(HouseholdBackendSession(build_cleanup_scenario(seed=7)))

    metric_map = contract.metric_map()
    static_fixture_projection = contract.static_fixture_projection()
    observation = _first_non_empty_observation(contract)

    assert metric_map["contract"] == REALWORLD_CONTRACT
    assert "objects" not in metric_map
    assert "objects" not in static_fixture_projection
    assert observation["private_target_truth_included"] is False
    assert observation["visible_object_detections"]
    assert observation["visible_fixture_detections"]
    for fixture in observation["visible_fixture_detections"]:
        assert fixture["fixture_id"] == fixture["anchor_id"]
        assert fixture["fixture_id"].startswith("anchor_fixture_")
    serialized_observation = json.dumps(observation)
    assert not any(fixture_id in serialized_observation for fixture_id in contract._fixtures)
    fixture_navigation = contract.navigate_to_receptacle(
        observation["visible_fixture_detections"][0]["fixture_id"]
    )
    assert fixture_navigation["error_reason"] == "semantic_order"
    assert fixture_navigation["required_tool"] == "pick"
    for detection in observation["visible_object_detections"]:
        assert detection["object_id"].startswith("observed_")
        assert "support_estimate" in detection
        assert detection["destination_policy_status"] == "policy_required"
        assert "destination_policy" in detection
        assert "target_receptacle_id" not in detection
        assert "is_misplaced" not in detection
    _assert_no_forbidden_keys(metric_map)
    _assert_no_forbidden_keys(static_fixture_projection)
    _assert_no_forbidden_keys(observation)


def test_world_label_candidate_requires_scan_then_observe_before_navigation() -> None:
    contract = _contract(HouseholdBackendSession(build_cleanup_scenario(seed=7)))
    first_observation = _first_non_empty_observation(contract)
    handle = first_observation["visible_object_detections"][0]["object_id"]

    blocked = contract.navigate_to_object(handle)
    contract.adjust_camera(yaw_delta_deg=15)
    confirmed_observation = contract.observe()
    confirmed = next(
        item
        for item in confirmed_observation["visible_object_detections"]
        if item["object_id"] == handle
    )
    navigation = contract.navigate_to_object(handle)

    assert blocked["ok"] is False
    assert confirmed["source_observation_id"].startswith("world_label_fpv_")
    assert confirmed["source_observation_id"] != first_observation["source_observation_id"]
    assert confirmed["candidate_state"] == "navigation_authorized"
    assert confirmed["visual_grounding_evidence"]["reviewability_status"] == "reviewable"
    assert navigation["ok"] is True
    assert navigation["candidate_state"] == "navigation_authorized"
    assert (
        navigation["visual_grounding_evidence"]["source_observation_id"]
        == (confirmed["source_observation_id"])
    )
    _assert_no_forbidden_keys(navigation)


def test_relative_pose_navigation_rejects_noop_and_out_of_bounds_requests() -> None:
    contract = _contract(HouseholdBackendSession(build_cleanup_scenario(seed=7)))

    noop = contract.navigate_to_relative_pose()
    too_far = contract.navigate_to_relative_pose(forward_m=1.25)
    too_much_turn = contract.navigate_to_relative_pose(yaw_delta_deg=120)

    assert noop["ok"] is False
    assert noop["tool"] == "navigate_to_relative_pose"
    assert noop["error_reason"] == "noop_relative_pose_request"
    assert noop["frame_id"] == "base_link"
    assert noop["requires_reobserve"] is True
    assert too_far["error_reason"] == "relative_pose_delta_out_of_bounds"
    assert too_far["applied_delta"] == {"forward_m": 0.0, "lateral_m": 0.0, "yaw_delta_deg": 0.0}
    assert too_much_turn["error_reason"] == "relative_pose_delta_out_of_bounds"


def test_relative_pose_navigation_reports_public_delta_and_reobserve_requirement() -> None:
    scenario = build_cleanup_scenario(seed=7)
    backend = _RelativePoseBackend(scenario)
    contract = _contract(HouseholdBackendSession(backend=backend))

    response = contract.navigate_to_relative_pose(
        forward_m=0.25,
        lateral_m=-0.125,
        yaw_delta_deg=15,
    )

    assert response["ok"] is True
    assert response["tool"] == "navigate_to_relative_pose"
    assert response["frame_id"] == "base_link"
    assert response["requested_delta"] == {
        "forward_m": 0.25,
        "lateral_m": -0.125,
        "yaw_delta_deg": 15.0,
    }
    assert response["applied_delta"] == response["requested_delta"]
    assert response["pose_source"] == "relative_robot_frame"
    assert response["backend_provenance"] == "api_semantic"
    assert response["requires_reobserve"] is True
    assert response["clamped"] is False
    assert backend.relative_pose_calls == [
        {"forward_m": 0.25, "lateral_m": -0.125, "yaw_delta_deg": 15.0}
    ]


def test_relative_pose_navigation_strips_private_backend_pose_fields() -> None:
    scenario = build_cleanup_scenario(seed=7)
    backend = _RelativePoseBackend(scenario)
    contract = _contract(HouseholdBackendSession(backend=backend))

    response = contract.navigate_to_relative_pose(forward_m=0.25)

    assert response["ok"] is True
    assert response["backend_pose_mutation"]["robot_pose"] == {
        "x": 1.25,
        "y": 2.0,
        "pose_source": "relative_robot_frame",
    }
    assert "target_receptacle_id" not in str(response)
