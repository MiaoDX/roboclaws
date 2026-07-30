from __future__ import annotations

from roboclaws.household.household_backend_contract import HouseholdBackendSession
from roboclaws.household.household_runtime_contract import (
    DONE_READINESS_POLICY_RAW_FPV,
    RAW_FPV_ONLY_MODE,
)
from tests.contract.molmo_cleanup.household_runtime_contract_support import (
    _assert_no_forbidden_keys,
    _contract,
    _empty_cleanup_scenario,
    _observe_raw_fpv_heading_sweep,
)


def test_camera_raw_requested_run_size_enables_grounded_chain_gate_after_sweep() -> None:
    contract = _contract(
        HouseholdBackendSession(_empty_cleanup_scenario("camera-raw-fpv-readiness-policy-test")),
        perception_mode=RAW_FPV_ONLY_MODE,
        public_acceptance_config={"requested_run_size": 5},
    )

    observation = _observe_raw_fpv_heading_sweep(contract)
    for index in range(5):
        declared = contract.declare_visual_candidates(
            observation["raw_fpv_observation"]["observation_id"],
            candidates=[
                {
                    "category": f"imaginary widget {index}",
                    "evidence_note": "unresolved visual guess for readiness policy",
                    "image_region": {"type": "verbal_region", "value": f"empty area {index}"},
                }
            ],
            producer_type="main_cleanup_agent",
            producer_id="test_agent",
        )
        assert declared["model_declared_observations"][0]["grounding_status"] == "unresolved"

    for waypoint in contract.metric_map()["inspection_waypoints"]:
        contract.navigate_to_waypoint(str(waypoint["waypoint_id"]))
        contract.adjust_camera(yaw_delta_deg=45, pitch_delta_deg=20)
        contract.observe()

    done = contract.done("camera-raw-fpv run finished without grounded cleanup chains")

    assert done["ok"] is False
    assert done["error_reason"] == "insufficient_grounded_cleanup_chains"
    assert done["required_tool"] == "navigate_to_visual_candidate"
    blocker = done["completion"]["blockers"][0]
    assert blocker["type"] == "insufficient_grounded_cleanup_chains"
    assert blocker["policy_id"] == DONE_READINESS_POLICY_RAW_FPV
    assert blocker["required"] == 4
    assert blocker["required_tool"] == "navigate_to_visual_candidate"
    _assert_no_forbidden_keys(done)
