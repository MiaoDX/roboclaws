from __future__ import annotations

from roboclaws.household.household_backend_contract import HouseholdBackendSession
from roboclaws.household.household_runtime_contract import HouseholdRuntimeContract
from roboclaws.household.planner_observed_binding import (
    OBSERVED_HANDLE_PLANNER_BINDING_SCHEMA,
    backend_planner_task_binding_from_state,
)
from roboclaws.household.scenario import build_cleanup_scenario

PREBUILT_BUNDLE = "assets/maps/molmospaces/procthor-10k-val/0"


def test_realworld_observed_handle_planner_binding_stays_private() -> None:
    contract = HouseholdRuntimeContract(
        HouseholdBackendSession(build_cleanup_scenario(seed=7)),
        map_bundle_dir=PREBUILT_BUNDLE,
    )
    detection = _first_detection_by_category(contract, "dish")
    target_fixture = contract.target_fixture_for_detection(
        detection,
    )
    assert target_fixture is not None

    binding = contract.planner_observed_handle_binding(
        detection["object_id"],
        str(target_fixture["fixture_id"]),
        tools=["pick", "place"],
    )
    agent_view = contract.agent_view_payload()

    assert binding["schema"] == OBSERVED_HANDLE_PLANNER_BINDING_SCHEMA
    assert binding["ok"] is True
    assert binding["object_id"] == detection["object_id"]
    assert binding["object_id"].startswith("observed_")
    assert binding["internal_object_id"] != binding["object_id"]
    assert binding["requested_cleanup_primitive_binding"]["object_id"] == detection["object_id"]
    assert (
        binding["requested_cleanup_primitive_binding"]["planner_object_id"]
        == binding["planner_object_id"]
    )
    assert binding["planner_probe_args"]["--cleanup-object-id"] == detection["object_id"]
    assert "--cleanup-planner-object-id" in binding["planner_probe_args"]
    assert binding["agent_view_exposed"] is False
    assert "planner_object_id" not in str(agent_view)
    assert binding["internal_object_id"] not in str(agent_view)


def test_observed_handle_planner_binding_requires_registered_handle() -> None:
    contract = HouseholdRuntimeContract(
        HouseholdBackendSession(build_cleanup_scenario(seed=7)),
        map_bundle_dir=PREBUILT_BUNDLE,
    )

    binding = contract.planner_observed_handle_binding("observed_999", "sink_01")

    assert binding["ok"] is False
    assert binding["status"] == "blocked_capability"
    assert binding["blockers"][0]["code"] == "observed_handle_not_registered"


def test_backend_planner_task_binding_prefers_runtime_body_names() -> None:
    binding = backend_planner_task_binding_from_state(
        {
            "objects": {
                "apple_01": {
                    "body_name": "apple/body",
                    "upstream_object_id": "Apple|+01",
                }
            },
            "receptacles": {
                "sink_01": {
                    "body_name": "sink/body",
                    "upstream_object_id": "Sink|+01",
                }
            },
            "object_locations": {"apple_01": "counter_01"},
        },
        object_id="apple_01",
        target_receptacle_id="sink_01",
    )

    assert binding["ok"] is True
    assert binding["pickup_obj_name"] == "apple/body"
    assert binding["place_receptacle_name"] == "sink/body"
    assert binding["candidate_pickup_names"] == ["apple/body", "Apple|+01", "apple_01"]
    assert binding["candidate_place_receptacle_names"] == ["sink/body", "Sink|+01", "sink_01"]
    assert binding["source_receptacle_id"] == "counter_01"


def _first_detection_by_category(
    contract: HouseholdRuntimeContract,
    category: str,
) -> dict:
    for waypoint in contract.metric_map()["inspection_waypoints"]:
        contract.navigate_to_waypoint(str(waypoint["waypoint_id"]))
        observation = contract.observe()
        for detection in observation["visible_object_detections"]:
            if detection["category"] == category:
                return detection
    raise AssertionError(f"expected visible object with category={category}")
