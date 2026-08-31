from __future__ import annotations

from pathlib import Path

from roboclaws.household.household_backend_contract import HouseholdBackendSession
from roboclaws.household.household_runtime_contract import (
    CAMERA_MODEL_POLICY_MODE,
    VISUAL_GROUNDING_CATEGORY_HINTS,
)
from roboclaws.household.realworld_done_readiness import _prioritized_next_actions
from roboclaws.household.realworld_visual_candidates import (
    VISUAL_GROUNDING_CATEGORY_HINT_GROUPS,
    merge_visual_grounding_candidates,
)
from roboclaws.household.scenario import build_cleanup_scenario
from roboclaws.household.visual_grounding import VISUAL_GROUNDING_RESPONSE_SCHEMA
from tests.contract.molmo_cleanup.household_runtime_contract_support import (
    _assert_no_forbidden_keys,
    _attach_raw_fpv_test_image,
    _contract,
    _observe_raw_fpv_category,
    _observe_raw_fpv_heading_sweep,
    _StaticVisualGroundingClient,
)


def test_realworld_camera_labels_http_failure_is_visible_without_sim_fallback(
    tmp_path: Path,
) -> None:
    client = _StaticVisualGroundingClient(
        {
            "schema": VISUAL_GROUNDING_RESPONSE_SCHEMA,
            "status": "failed",
            "pipeline": {
                "pipeline_id": "grounding-dino",
                "stages": [
                    {
                        "stage": "proposer",
                        "producer_id": "grounding-dino",
                        "model_id": "fake",
                        "status": "timeout",
                        "latency_ms": 20,
                    }
                ],
            },
            "candidates": [],
            "error": {"reason": "timeout", "message": "sidecar timeout"},
        }
    )
    contract = _contract(
        HouseholdBackendSession(build_cleanup_scenario(seed=7)),
        perception_mode=CAMERA_MODEL_POLICY_MODE,
        visual_grounding_client=client,
        visual_grounding_pipeline_id="grounding-dino",
    )
    observation = _observe_raw_fpv_category(contract, category="toy")
    _attach_raw_fpv_test_image(
        contract,
        tmp_path=tmp_path,
        relative_path="robot_views/raw_fpv_001.png",
    )
    response = contract.declare_visual_candidates(
        observation["raw_fpv_observation"]["observation_id"]
    )
    evidence = response["model_declared_observation_evidence"]
    policy = contract.camera_model_policy_payload()

    assert response["ok"] is True
    assert response["model_declared_observations"] == []
    assert response["camera_model_candidates"] == []
    assert evidence["visual_grounding_pipeline"]["status"] == "failed"
    assert evidence["visual_grounding_pipeline"]["failure_reason"] == "timeout"
    assert evidence["candidate_count"] == 0
    assert policy["model_provenance"] == "external_visual_grounding_service"
    assert policy["visual_grounding_failure_count"] == 1
    assert contract.model_declared_observations_payload()["observation_count"] == 0
    assert client.last_request is not None
    _assert_no_forbidden_keys(response)


def test_realworld_camera_labels_missing_raw_image_fails_before_sidecar() -> None:
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
                        "model_id": "fake",
                        "status": "ok",
                        "latency_ms": 4,
                    }
                ],
            },
            "candidates": [
                {
                    "category": "mug",
                    "image_region": {"type": "bbox", "value": [0.1, 0.2, 0.3, 0.4]},
                    "confidence": 0.8,
                }
            ],
        }
    )
    contract = _contract(
        HouseholdBackendSession(build_cleanup_scenario(seed=7)),
        perception_mode=CAMERA_MODEL_POLICY_MODE,
        visual_grounding_client=client,
        visual_grounding_pipeline_id="grounding-dino",
    )

    observation = contract.observe()
    response = contract.declare_visual_candidates(
        observation["raw_fpv_observation"]["observation_id"]
    )
    evidence = response["model_declared_observation_evidence"]
    policy = contract.camera_model_policy_payload()

    assert response["ok"] is True
    assert response["model_declared_observations"] == []
    assert evidence["visual_grounding_pipeline"]["status"] == "failed"
    assert evidence["visual_grounding_pipeline"]["failure_reason"] == "missing_raw_fpv_image"
    assert policy["visual_grounding_failure_count"] == 1
    assert client.last_request is None
    _assert_no_forbidden_keys(response)


def test_realworld_camera_labels_http_success_uses_destination_resolver(
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
                        "model_id": "fake",
                        "status": "ok",
                        "latency_ms": 4,
                    }
                ],
            },
            "candidates": [
                {
                    "category": "mug",
                    "image_region": {"type": "bbox", "value": [0.1, 0.2, 0.3, 0.4]},
                    "confidence": 0.8,
                    "evidence_note": "static mug on sofa from public camera frame",
                    "source_fixture_id": "sofa_01",
                    "destination_hint": {
                        "candidate_fixture_id": "bookshelf_01",
                        "confidence": 0.9,
                    },
                }
            ],
        }
    )
    contract = _contract(
        HouseholdBackendSession(build_cleanup_scenario(seed=7)),
        perception_mode=CAMERA_MODEL_POLICY_MODE,
        visual_grounding_client=client,
        visual_grounding_pipeline_id="grounding-dino",
        visual_grounding_artifact_base_dir=tmp_path,
    )
    contract.navigate_to_waypoint(contract._preferred_waypoint_for_fixture("sofa_01"))  # noqa: SLF001
    observation = contract.observe()
    _attach_raw_fpv_test_image(
        contract,
        tmp_path=tmp_path,
        relative_path="robot_views/raw_fpv_001.png",
    )
    response = contract.declare_visual_candidates(
        observation["raw_fpv_observation"]["observation_id"]
    )
    declaration = response["model_declared_observations"][0]

    assert client.last_request is not None
    assert [request["category_hints"] for request in client.requests] == (
        VISUAL_GROUNDING_CATEGORY_HINT_GROUPS
    )
    assert (
        list(
            dict.fromkeys(hint for request in client.requests for hint in request["category_hints"])
        )
        == VISUAL_GROUNDING_CATEGORY_HINTS
    )
    assert "static_fixture_projection" not in client.last_request
    assert client.last_request["public_map_hints"]["source"] == "public_agent_view_map_evidence"
    assert isinstance(client.last_request["public_map_hints"]["fixture_hints"], list)
    assert client.last_request["public_map_hints"]["private_truth_included"] is False
    assert client.last_request["image"]["bytes_base64"]
    assert client.last_request["image"]["width"] == 20
    assert client.last_request["image"]["height"] == 10
    assert declaration["producer_type"] == "external_visual_grounding_service"
    assert declaration["visual_grounding_pipeline"]["pipeline_id"] == "grounding-dino"
    assert declaration["visual_grounding_evidence"]["schema"] == "visual_grounding_evidence_v1"
    assert declaration["visual_grounding_evidence"]["producer_id"] == "grounding-dino"
    assert declaration["visual_grounding_evidence"]["reviewability_status"] == "reviewable"
    assert declaration["visual_grounding_evidence"]["bbox_coordinate_space"] == "normalized_xywh"
    assert declaration["actionability_status"] == "actionable"
    assert str(declaration["visual_grounding_destination_hint"]["candidate_fixture_id"]).startswith(
        "anchor_fixture_"
    )
    assert str(declaration["target_fixture_id"]).startswith("anchor_fixture_")
    assert declaration["visual_grounding_overlay"] == (
        "visual_grounding/overlays/raw_fpv_001/candidate_001.jpg"
    )
    assert (tmp_path / declaration["visual_grounding_overlay"]).is_file()
    assert (
        response["model_declared_observation_evidence"]["visual_grounding_pipeline"][
            "candidate_count"
        ]
        == 1
    )
    runtime_observed = contract.agent_view_payload()["runtime_metric_map"]["observed_objects"][0]
    assert runtime_observed["producer_type"] == "external_visual_grounding_service"
    assert runtime_observed["producer_id"] == "grounding-dino"
    assert runtime_observed["source_observation_id"] == declaration["source_observation_id"]
    assert runtime_observed["image_region"]["type"] == "bbox"
    assert runtime_observed["visual_grounding_evidence"]["reviewability_status"] == "reviewable"
    assert runtime_observed["actionability"] == "pending"
    _assert_no_forbidden_keys(response)


def test_camera_grounded_requested_run_size_requires_four_cleanup_chains() -> None:
    contract = _contract(
        HouseholdBackendSession(build_cleanup_scenario(seed=7)),
        perception_mode=CAMERA_MODEL_POLICY_MODE,
        public_acceptance_config={"requested_run_size": 5},
    )

    contract.navigate_to_waypoint(
        str(contract.metric_map()["inspection_waypoints"][0]["waypoint_id"])
    )
    contract.observe()

    heading_blocked = contract.done("camera-grounded run attempted without heading sweep")

    assert heading_blocked["ok"] is False
    assert heading_blocked["error_reason"] == "insufficient_camera_grounded_heading_coverage"
    assert heading_blocked["followup_tool"] == "observe_camera_grounded_candidates"
    assert heading_blocked["required_distinct_heading_count"] == 4
    assert "three times" in heading_blocked["recovery_hint"]

    _observe_raw_fpv_heading_sweep(contract)

    done = contract.done("camera-grounded run attempted early completion")

    assert done["ok"] is False
    assert done["error_reason"] == "insufficient_grounded_cleanup_chains"
    assert done["required_tool"] == "navigate_to_object"
    blocker = done["completion"]["blockers"][0]
    assert blocker["policy_id"] == "camera_model_grounded_cleanup_chains"
    assert blocker["current"] == 0
    assert blocker["required"] == 4
    _assert_no_forbidden_keys(done)


def test_camera_grounded_completion_actions_do_not_invite_stale_handle_retries() -> None:
    heading = {
        "type": "insufficient_camera_grounded_heading_coverage",
        "required_tool": "navigate_to_waypoint",
        "next_waypoint_id": "room_3_inspection",
        "incomplete_waypoint_ids": ["room_3_inspection"],
    }
    chain = {
        "type": "insufficient_grounded_cleanup_chains",
        "required_tool": "navigate_to_object",
        "current": 3,
        "required": 4,
    }

    assert _prioritized_next_actions([heading, chain]) == [
        {
            "required_tool": "navigate_to_waypoint",
            "next_waypoint_id": "room_3_inspection",
            "incomplete_waypoint_ids": ["room_3_inspection"],
        }
    ]
    assert _prioritized_next_actions([chain]) == []


def test_camera_grounded_heading_recovery_stops_after_chain_gate_is_met(monkeypatch) -> None:
    contract = _contract(
        HouseholdBackendSession(build_cleanup_scenario(seed=7)),
        perception_mode=CAMERA_MODEL_POLICY_MODE,
        public_acceptance_config={"requested_run_size": 5},
    )
    for waypoint in contract.metric_map()["inspection_waypoints"]:
        contract.navigate_to_waypoint(str(waypoint["waypoint_id"]))
        contract.observe()

    monkeypatch.setattr(
        "roboclaws.household.realworld_done_readiness.grounded_cleanup_chain_blocker",
        lambda *_args, **_kwargs: None,
    )

    readiness = contract.evaluate_done_readiness(semantic_cleanup_evidence={})

    assert readiness["status"] == "ready"
    assert all(
        blocker["type"] != "insufficient_camera_grounded_heading_coverage"
        for blocker in readiness["blockers"]
    )


def test_camera_grounded_merge_keeps_overlapping_candidates_from_different_families() -> None:
    candidates = [
        {
            "category": "potato",
            "confidence": 0.52,
            "image_region": {"type": "bbox", "value": [0.2, 0.2, 0.1, 0.1]},
        },
        {
            "category": "teddy bear",
            "confidence": 0.6,
            "image_region": {"type": "bbox", "value": [0.2, 0.2, 0.1, 0.1]},
        },
        {
            "category": "food",
            "confidence": 0.3,
            "image_region": {"type": "bbox", "value": [0.2, 0.2, 0.1, 0.1]},
        },
    ]

    selected = merge_visual_grounding_candidates(candidates)

    assert [candidate["category"] for candidate in selected] == ["teddy bear", "potato"]


def test_realworld_camera_labels_http_destination_hint_is_evidence_only(
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
                        "model_id": "fake",
                        "status": "ok",
                        "latency_ms": 4,
                    }
                ],
            },
            "candidates": [
                {
                    "category": "unknown_movable",
                    "image_region": {"type": "bbox", "value": [0.1, 0.2, 0.3, 0.4]},
                    "confidence": 0.7,
                    "evidence_note": "static unknown item with service-suggested destination",
                    "source_fixture_id": "",
                    "destination_hint": {
                        "candidate_fixture_id": "bookshelf_01",
                        "confidence": 0.9,
                    },
                }
            ],
        }
    )
    contract = _contract(
        HouseholdBackendSession(build_cleanup_scenario(seed=7)),
        perception_mode=CAMERA_MODEL_POLICY_MODE,
        visual_grounding_client=client,
        visual_grounding_pipeline_id="grounding-dino",
    )

    observation = contract.observe()
    _attach_raw_fpv_test_image(
        contract,
        tmp_path=tmp_path,
        relative_path="robot_views/raw_fpv_001.png",
    )
    response = contract.declare_visual_candidates(
        observation["raw_fpv_observation"]["observation_id"]
    )
    declaration = response["model_declared_observations"][0]

    assert str(declaration["visual_grounding_destination_hint"]["candidate_fixture_id"]).startswith(
        "anchor_fixture_"
    )
    assert declaration["target_fixture_id"] == ""
    assert declaration["target_plausibility"]["status"] == "unknown_fixture"
    assert declaration["grounding_status"] == "unresolved"
    _assert_no_forbidden_keys(response)
