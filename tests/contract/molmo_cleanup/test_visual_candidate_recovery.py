from __future__ import annotations

from roboclaws.household.household_backend_contract import HouseholdBackendSession
from roboclaws.household.scenario import build_cleanup_scenario
from tests.contract.molmo_cleanup.household_runtime_contract_support import (
    _confirm_world_label_detection,
    _contract,
    _first_detection_by_category,
)


def test_not_recommended_candidate_advances_base_map_sweep() -> None:
    contract = _contract(
        HouseholdBackendSession(build_cleanup_scenario(seed=7)),
        evidence_lane="world-public-labels",
    )
    detection = _confirm_world_label_detection(
        contract,
        _first_detection_by_category(contract, "electronics"),
    )
    unvisited_waypoint_ids = [
        str(item["waypoint_id"])
        for item in contract.metric_map()["inspection_waypoints"]
        if not item["visited"]
    ]

    response = contract.navigate_to_object(detection["object_id"])

    assert unvisited_waypoint_ids
    assert response["error_reason"] == "visual_candidate_not_cleanup_recommended"
    assert response["required_next_tool"] == "navigate_to_waypoint"
    assert response["next_waypoint_id"] == unvisited_waypoint_ids[0]

    for waypoint_id in unvisited_waypoint_ids:
        contract.navigate_to_waypoint(waypoint_id)
        contract.observe()

    completed_sweep_response = contract.navigate_to_object(detection["object_id"])

    assert completed_sweep_response["required_next_tool"] == "done"
    assert completed_sweep_response["recovery_tool_options"] == ["done"]
