from __future__ import annotations

from roboclaws.household.household_backend_contract import HouseholdBackendSession
from roboclaws.household.household_runtime_contract import (
    RAW_FPV_ONLY_MODE,
)
from roboclaws.household.scenario import build_cleanup_scenario
from tests.contract.molmo_cleanup.household_runtime_contract_support import (
    _assert_no_forbidden_keys,
    _contract,
)


def test_realworld_raw_fpv_camera_adjustment_is_bounded_and_resets() -> None:
    contract = _contract(
        HouseholdBackendSession(build_cleanup_scenario(seed=7)),
        perception_mode=RAW_FPV_ONLY_MODE,
    )

    waypoints = contract.metric_map()["inspection_waypoints"]
    contract.navigate_to_waypoint(str(waypoints[0]["waypoint_id"]))
    adjusted = contract.adjust_camera(yaw_delta_deg=90, pitch_delta_deg=-90)
    observation = contract.observe()
    contract.navigate_to_waypoint(str(waypoints[1]["waypoint_id"]))
    reset_observation = contract.observe()

    assert adjusted["camera_offset"] == {"yaw_delta_deg": 45.0, "pitch_delta_deg": -20.0}
    assert observation["raw_fpv_observation"]["camera_offset"] == adjusted["camera_offset"]
    assert reset_observation["raw_fpv_observation"]["camera_offset"] == {
        "yaw_delta_deg": 0.0,
        "pitch_delta_deg": 0.0,
    }


def test_minimal_raw_fpv_navigate_validation_returns_schema_recovery() -> None:
    contract = _contract(
        HouseholdBackendSession(build_cleanup_scenario(seed=7)),
        perception_mode=RAW_FPV_ONLY_MODE,
    )

    waypoint = contract.metric_map()["inspection_waypoints"][0]
    contract.navigate_to_waypoint(str(waypoint["waypoint_id"]))
    observation = contract.observe()
    response = contract.navigate_to_visual_candidate(
        observation["raw_fpv_observation"]["observation_id"],
        category="toy",
        evidence_note="small object on the bed",
    )

    assert response["ok"] is False
    assert response["error_reason"] == "invalid_visual_candidate"
    assert response["candidate_error"]["field"] == "image_region"
    recovery = response["raw_fpv_candidate_recovery"]
    assert recovery["required_next_action"] == "retry_navigate_to_visual_candidate"
    assert recovery["base_metric_map_target_fixture_rule"] == "omit_target_fixture_id"
    assert "target_fixture_id" not in recovery["valid_example"]
    assert "bbox_normalized" in recovery["invalid_fields_to_avoid"]
    assert 'target_fixture_id="None"' in recovery["invalid_fields_to_avoid"]
    _assert_no_forbidden_keys(response)

    invented_target = contract.navigate_to_visual_candidate(
        observation["raw_fpv_observation"]["observation_id"],
        category="toy",
        target_fixture_id="generated_area",
        evidence_note="small object on the bed",
        image_region={"type": "verbal_region", "value": "front of desk"},
    )

    assert invented_target["ok"] is False
    assert invented_target["error_reason"] == "invalid_visual_candidate"
    assert invented_target["candidate_error"]["field"] == "target_fixture_id"
    assert (
        "must be omitted in Base Metric Map RAW_FPV"
        in (invented_target["candidate_error"]["reason"])
    )
    assert (
        invented_target["raw_fpv_candidate_recovery"]["base_metric_map_target_fixture_rule"]
        == "omit_target_fixture_id"
    )
    _assert_no_forbidden_keys(invented_target)
