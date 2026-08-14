from __future__ import annotations

from roboclaws.household import agent_view as agent_view_module
from roboclaws.household.household_backend_contract import HouseholdBackendSession
from roboclaws.household.household_runtime_contract import (
    SANITIZED_VISIBLE_OBJECT_DETECTIONS_POLICY,
    SANITIZED_VISIBLE_OBJECT_DETECTIONS_PROVENANCE,
    HouseholdRuntimeContract,
    cleanup_policy_trace_from_events,
)
from roboclaws.household.scenario import build_cleanup_scenario
from tests.contract.molmo_cleanup.household_runtime_contract_support import (
    _assert_no_forbidden_keys,
    _contract,
    _first_non_empty_observation,
    _policy_trace_agent_view,
    _trace_response,
)


def test_realworld_contract_requires_map_bundle_without_synthetic_opt_in() -> None:
    try:
        HouseholdRuntimeContract(HouseholdBackendSession(build_cleanup_scenario(seed=7)))
    except ValueError as exc:
        assert "map_bundle_dir is required for product runtime base inspection_waypoints" in str(
            exc
        )
    else:
        raise AssertionError("expected product runtime to reject missing map bundle")


def test_cleanup_policy_trace_rejects_cached_cleanup_after_later_map_query() -> None:
    trace = cleanup_policy_trace_from_events(
        [
            _trace_response("navigate_to_waypoint", {"ok": True, "waypoint_id": "room_1_scan_1"}),
            _trace_response(
                "observe",
                {
                    "ok": True,
                    "waypoint_id": "room_1_scan_1",
                    "visible_object_detections": [
                        {
                            "object_id": "observed_001",
                            "cleanup_recommended": True,
                        }
                    ],
                },
            ),
            _trace_response("navigate_to_waypoint", {"ok": True, "waypoint_id": "room_1_scan_2"}),
            _trace_response("observe", {"ok": True, "waypoint_id": "room_1_scan_2"}),
            _trace_response("navigate_to_object", {"ok": True, "object_id": "observed_001"}),
        ],
        _policy_trace_agent_view(
            [
                {"waypoint_id": "room_1_scan_1"},
                {"waypoint_id": "room_1_scan_2"},
            ]
        ),
    )

    assert trace["loop_style"] == "survey_first_cleanup_loop"
    assert trace["first_actionable_observation_index"] == 2
    assert trace["first_cleanup_index"] == 5


def test_world_labels_sanitized_runtime_map_keeps_detection_fields_without_destination() -> None:
    contract = _contract(
        HouseholdBackendSession(build_cleanup_scenario(seed=7)),
        evidence_lane="world-public-labels",
    )

    _first_non_empty_observation(contract)
    agent_view = contract.agent_view_payload()
    runtime_map = agent_view_module.runtime_metric_map(agent_view)
    observed = runtime_map["observed_objects"][0]
    worklist_item = agent_view_module.cleanup_worklist(agent_view)["objects"][0]

    assert (
        agent_view_module.detection_exposure_policy(agent_view)
        == SANITIZED_VISIBLE_OBJECT_DETECTIONS_POLICY
    )
    assert observed["producer_type"] == SANITIZED_VISIBLE_OBJECT_DETECTIONS_PROVENANCE
    assert observed["source_observation_id"]
    assert observed["image_region"]["type"] == "verbal_region"
    assert observed["grounding_status"] == "resolved"
    assert observed["candidate_state"] == "visual_scan_required"
    assert observed["actionability"] == "pending"
    assert observed["candidate_fixture_id"] == ""
    assert observed["candidate_source"] == "policy_required_destination_selection"
    assert observed["destination_policy_status"] == "policy_required"
    assert observed["destination_policy"]["preferred_fixture_categories"]
    assert observed["destination_policy"]["private_truth_included"] is False
    assert "cleanup_recommended" not in worklist_item
    assert worklist_item["candidate_fixture_id"] == ""
    assert worklist_item["candidate_state"] == "visual_scan_required"
    assert worklist_item["destination_policy_status"] == "policy_required"
    assert worklist_item["destination_policy"] == observed["destination_policy"]
    assert (
        runtime_map["producer_summary"]["producer_types"][
            SANITIZED_VISIBLE_OBJECT_DETECTIONS_PROVENANCE
        ]
        >= 1
    )
    _assert_no_forbidden_keys(runtime_map)


def test_map_build_done_still_requires_complete_sweep() -> None:
    contract = _contract(
        HouseholdBackendSession(build_cleanup_scenario(seed=7)),
        public_acceptance_config={"task_intent": "map-build"},
    )
    observation = _first_non_empty_observation(contract)
    assert observation["visible_object_detections"]

    done = contract.done("map sweep incomplete")

    assert done["ok"] is False
    assert done["error_reason"] == "insufficient_sweep_coverage"
    assert all(
        blocker["type"] != "pending_cleanup_candidates"
        for blocker in done["completion"]["blockers"]
    )
    _assert_no_forbidden_keys(done)
