from __future__ import annotations

from roboclaws.household.backend import ApiSemanticCleanupBackend
from roboclaws.household.household_backend_contract import HouseholdBackendSession
from roboclaws.household.scenario import build_cleanup_scenario
from roboclaws.household.types import (
    CleanupObject,
    CleanupReceptacle,
    CleanupScenario,
    PrivateScoringManifest,
    TargetRule,
)
from tests.contract.molmo_cleanup.household_runtime_contract_support import (
    _assert_no_forbidden_keys,
    _contract,
    _public_destination_fixture_for_detection,
)


def test_scene_index_backend_prefers_public_usd_fixture_overlay_over_stale_map_bundle() -> None:
    scenario = CleanupScenario(
        scenario_id="isaac-scene-index-procthor-10k-val-1-7-1",
        task="Clean up this loaded Isaac scene.",
        seed=7,
        objects=(
            CleanupObject(
                object_id="bowl_847a24bfa9d8b1a1f26661ebbb850f56_1_0_2",
                name="Bowl (Bowl_12)",
                category="Bowl",
                location_id="bed_f113cf7f8367e89f709b53cbee1a1c05_1_0_2",
            ),
        ),
        receptacles=(
            CleanupReceptacle(
                "bed_f113cf7f8367e89f709b53cbee1a1c05_1_0_2",
                "Bed Bed|2|1|0 Bed_203_1",
                "isaac_scene",
                category="Bed",
            ),
            CleanupReceptacle(
                "sink_07e796f32d0d3efce9acf4be00f3bc53_1_0_3",
                "Sink Sink|3|1|0 Sink_1",
                "isaac_scene",
                category="Sink",
            ),
        ),
        private_manifest=PrivateScoringManifest(
            scenario_id="isaac-scene-index-procthor-10k-val-1-7-1",
            targets=(
                TargetRule(
                    object_id="bowl_847a24bfa9d8b1a1f26661ebbb850f56_1_0_2",
                    valid_receptacle_ids=("sink_07e796f32d0d3efce9acf4be00f3bc53_1_0_3",),
                ),
            ),
            success_threshold=1,
        ),
    )
    backend = ApiSemanticCleanupBackend(scenario)
    backend.scenario_source = "isaac_scene_index"
    session = HouseholdBackendSession(scenario, backend=backend)
    contract = _contract(session)

    detection = None
    inspection_waypoints = contract.metric_map()["inspection_waypoints"]
    for waypoint in inspection_waypoints:
        contract.navigate_to_waypoint(str(waypoint["waypoint_id"]))
        observation = contract.observe()
        if observation["visible_object_detections"]:
            detection = observation["visible_object_detections"][0]
            break

    assert detection is not None
    target_fixture = _public_destination_fixture_for_detection(contract, detection)
    assert str(target_fixture["fixture_id"]).startswith("anchor_fixture_")
    assert str(target_fixture["category"]).lower() in {"countertop", "sink"}
    assert target_fixture["public_fixture_source"] == "runtime_semantic_anchor"

    _assert_no_forbidden_keys(target_fixture)


def test_map_build_done_ignores_cleanup_candidates_after_complete_sweep() -> None:
    contract = _contract(
        HouseholdBackendSession(build_cleanup_scenario(seed=7)),
        public_acceptance_config={"task_intent": "map-build"},
    )
    for waypoint in contract.metric_map()["inspection_waypoints"]:
        assert contract.navigate_to_waypoint(waypoint["waypoint_id"])["ok"] is True
        assert contract.observe()["ok"] is True

    done = contract.done("map sweep complete")

    assert done["ok"] is True
    assert contract.evaluate_done_readiness()["status"] == "ready"
    _assert_no_forbidden_keys(done)
