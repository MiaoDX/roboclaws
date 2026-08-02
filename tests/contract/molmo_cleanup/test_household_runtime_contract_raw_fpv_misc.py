from __future__ import annotations

from pathlib import Path

from roboclaws.household import agent_view as agent_view_module
from roboclaws.household import (
    realworld_done_readiness,
    realworld_visual_candidate_declarations,
)
from roboclaws.household.backend import ApiSemanticCleanupBackend
from roboclaws.household.household_backend_contract import HouseholdBackendSession
from roboclaws.household.household_runtime_contract import (
    CAMERA_MODEL_POLICY_MODE,
    DONE_READINESS_POLICY_EXPLICIT,
    RAW_FPV_ONLY_MODE,
)
from roboclaws.household.scenario import build_cleanup_scenario
from roboclaws.household.subprocess_backend import MOLMOSPACES_SUBPROCESS_BACKEND
from roboclaws.household.visual_grounding import VISUAL_GROUNDING_RESPONSE_SCHEMA
from tests.contract.molmo_cleanup.household_runtime_contract_support import (
    _assert_no_forbidden_keys,
    _attach_raw_fpv_test_image,
    _contract,
    _empty_cleanup_scenario,
    _observe_raw_fpv_category,
    _StaticVisualGroundingClient,
)


def test_realworld_raw_fpv_mode_suppresses_structured_detections() -> None:
    contract = _contract(
        HouseholdBackendSession(build_cleanup_scenario(seed=7)),
        perception_mode=RAW_FPV_ONLY_MODE,
    )

    waypoint = contract.metric_map()["inspection_waypoints"][0]
    contract.navigate_to_waypoint(str(waypoint["waypoint_id"]))
    observation = contract.observe()
    agent_view = contract.agent_view_payload()

    assert observation["perception_mode"] == RAW_FPV_ONLY_MODE
    assert observation["structured_detections_available"] is False
    assert observation["visible_object_detections"] == []
    assert observation["raw_fpv_observation"]["observation_id"].startswith("raw_fpv_")
    assert observation["raw_fpv_observation"]["image_artifacts"] == {}
    assert "inline_on_navigate" in observation["instruction"]
    assert "navigate_to_visual_candidate" in observation["instruction"]
    assert "omit target_fixture_id" in observation["instruction"]
    assert "candidate_fixture_id/recommended_tool" in observation["instruction"]
    assert "image_region={type:bbox,value:[x,y,width,height]}" in observation["instruction"]
    assert "left, right, bottom, or top FPV edge" in observation["instruction"]
    assert "for a bottom-edge candidate use pitch_delta_deg=20" in observation["instruction"]
    assert "for a top-edge candidate use pitch_delta_deg=-20" in observation["instruction"]
    assert "overlap without a clear edge direction" in observation["instruction"]
    assert "never reuse the original sliver bbox" in observation["instruction"]
    assert "declare_visual_candidates" not in observation["instruction"]
    assert agent_view_module.perception_mode(agent_view) == RAW_FPV_ONLY_MODE
    assert agent_view_module.structured_detections_available(agent_view) is False
    active_perception = agent_view_module.active_perception(agent_view)
    assert active_perception["raw_fpv_summary"]["observation_count"] == 1
    assert (
        active_perception["raw_fpv_summary"]["artifact_status_counts"]["pending_robot_view_capture"]
        == 1
    )
    assert active_perception["camera_grounded_labels"]["sidecar_status"] == "disabled"
    assert active_perception["visual_candidate_lifecycle"]["model_declared_observation_count"] == 0
    assert agent_view_module.observed_objects(agent_view) == []
    assert agent_view_module.raw_fpv_observations(agent_view)
    assert "support_estimate" not in str(agent_view_module.raw_fpv_observations(agent_view))
    assert "target_receptacle_id" not in str(agent_view_module.raw_fpv_observations(agent_view))
    _assert_no_forbidden_keys(observation)
    _assert_no_forbidden_keys(agent_view)


def test_simulated_raw_fpv_inputs_only_fall_back_for_synthetic_backend(monkeypatch) -> None:
    scenario = build_cleanup_scenario(seed=7)
    backend = ApiSemanticCleanupBackend(scenario)
    session = HouseholdBackendSession(scenario, backend=backend)
    contract = _contract(session, perception_mode=RAW_FPV_ONLY_MODE)
    target = scenario.objects[0]
    target_location = session.object_locations()[target.object_id]
    waypoint = contract.metric_map()["inspection_waypoints"][0]
    monkeypatch.setattr(
        realworld_visual_candidate_declarations.realworld_visual_perception_navigation,
        "objects_visible_from_waypoint",
        lambda _contract, _waypoint: [(target, target_location)],
    )

    synthetic_inputs = (
        realworld_visual_candidate_declarations.simulated_raw_fpv_inputs_for_observation(
            contract,
            waypoint,
            observation_id="synthetic-observation-without-bindings",
        )
    )

    assert len(synthetic_inputs) == 1
    assert synthetic_inputs[0]["category"] == target.category
    assert synthetic_inputs[0]["source_fixture_id"] == target_location
    assert synthetic_inputs[0]["image_region"]["type"] == "bbox"
    assert "target_fixture_id" not in synthetic_inputs[0]

    monkeypatch.setattr(backend, "backend_name", lambda: MOLMOSPACES_SUBPROCESS_BACKEND)
    real_backend_inputs = (
        realworld_visual_candidate_declarations.simulated_raw_fpv_inputs_for_observation(
            contract,
            waypoint,
            observation_id="real-observation-without-bindings",
        )
    )

    assert real_backend_inputs == []


def test_world_labels_requested_run_size_does_not_enable_raw_fpv_grounded_chain_gate() -> None:
    contract = _contract(
        HouseholdBackendSession(
            _empty_cleanup_scenario("world-public-labels-readiness-policy-test")
        ),
        public_acceptance_config={"requested_run_size": 5},
    )

    for waypoint in contract.metric_map()["inspection_waypoints"]:
        contract.navigate_to_waypoint(str(waypoint["waypoint_id"]))
        contract.observe()

    done = contract.done("world-public-labels run completed after public sweep")

    assert done["ok"] is True
    assert done["tool"] == "done"
    _assert_no_forbidden_keys(done)


def test_world_labels_explicit_grounded_chain_gate_uses_world_label_tooling() -> None:
    contract = _contract(
        HouseholdBackendSession(
            _empty_cleanup_scenario("world-public-labels-explicit-readiness-test")
        ),
        public_acceptance_config={"required_grounded_cleanup_chains": 2},
    )

    for waypoint in contract.metric_map()["inspection_waypoints"]:
        contract.navigate_to_waypoint(str(waypoint["waypoint_id"]))
        contract.observe()

    done = contract.done("world-public-labels run explicitly requires public chains")

    assert done["ok"] is False
    assert done["error_reason"] == "insufficient_grounded_cleanup_chains"
    assert done["required_tool"] == "navigate_to_object"
    blocker = done["completion"]["blockers"][0]
    assert blocker["policy_id"] == DONE_READINESS_POLICY_EXPLICIT
    assert blocker["required_tool"] == "navigate_to_object"
    assert "navigate_to_visual_candidate" not in blocker["recovery_hint"]
    _assert_no_forbidden_keys(done)


def test_grounded_chain_gate_counts_only_cleanup_recommended_handles() -> None:
    contract = _contract(
        HouseholdBackendSession(_empty_cleanup_scenario("recommended-chain-count-test")),
        perception_mode=RAW_FPV_ONLY_MODE,
        public_acceptance_config={"required_grounded_cleanup_chains": 2},
    )
    contract._detections_by_handle = {  # noqa: SLF001
        "observed_recommended": {"cleanup_recommended": True},
        "observed_not_recommended": {"cleanup_recommended": False},
    }

    blocker = realworld_done_readiness.grounded_cleanup_chain_blocker(
        contract,
        {
            "complete_semantic_substep_objects": 2,
            "complete_semantic_substep_object_ids": [
                "observed_recommended",
                "observed_not_recommended",
            ],
            "semantic_substep_count": 2,
        },
        raw_fpv_only_mode=RAW_FPV_ONLY_MODE,
        assert_no_forbidden_agent_view_keys=_assert_no_forbidden_keys,
    )

    assert blocker is not None
    assert blocker["current"] == 1
    assert blocker["complete_semantic_substep_object_ids"] == ["observed_recommended"]
    assert blocker["required"] == 2


def test_b1_isaac_raw_fpv_artifact_can_feed_camera_grounded_labels(
    tmp_path: Path,
) -> None:
    client = _StaticVisualGroundingClient(
        {
            "schema": VISUAL_GROUNDING_RESPONSE_SCHEMA,
            "status": "ok",
            "pipeline": {
                "pipeline_id": "grounding-dino",
                "stages": [
                    {
                        "stage": "proposer",
                        "producer_id": "grounding-dino",
                        "model_id": "fixture:grounding-dino",
                        "status": "ok",
                        "latency_ms": 4,
                    }
                ],
            },
            "candidates": [
                {
                    "category": "mug",
                    "image_region": {"type": "bbox", "value": [0.2, 0.2, 0.4, 0.4]},
                    "confidence": 0.8,
                }
            ],
        }
    )
    contract = _contract(
        HouseholdBackendSession(build_cleanup_scenario(seed=7)),
        perception_mode=CAMERA_MODEL_POLICY_MODE,
        evidence_lane="camera-grounded-labels",
        visual_grounding_client=client,
        visual_grounding_pipeline_id="grounding-dino",
        visual_grounding_artifact_base_dir=tmp_path,
        public_acceptance_config={
            "backend": "isaaclab_subprocess",
            "task_intent": "open-ended",
        },
    )
    observation = _observe_raw_fpv_category(contract, category="mug")
    _attach_raw_fpv_test_image(
        contract,
        tmp_path=tmp_path,
        relative_path="robot_views/b1_raw_fpv_001.png",
    )

    response = contract.declare_visual_candidates(
        observation["raw_fpv_observation"]["observation_id"]
    )
    evidence = contract.camera_model_policy_payload()

    assert client.last_request is not None
    assert client.last_request["schema"] == "visual_grounding_request_v2"
    assert client.last_request["image"]["bytes_base64"]
    assert client.last_request["pipeline_request"]["pipeline_id"] == "grounding-dino"
    assert client.last_request["public_map_hints"]["private_truth_included"] is False
    assert response["ok"] is True
    assert response["model_declared_observations"]
    assert evidence["enabled"] is True
    assert evidence["visual_grounding_pipeline_id"] == "grounding-dino"
    assert evidence["visual_grounding_failure_count"] == 0
    assert evidence["candidate_count"] >= 1
    agent_view = contract.agent_view_payload()
    assert (
        agent_view_module.camera_model_policy_evidence(agent_view)["visual_grounding_pipeline_id"]
        == "grounding-dino"
    )
    _assert_no_forbidden_keys(response)
