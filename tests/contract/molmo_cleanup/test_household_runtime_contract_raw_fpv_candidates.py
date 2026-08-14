from __future__ import annotations

import json
from pathlib import Path

from roboclaws.household import agent_view as agent_view_module
from roboclaws.household import (
    realworld_done_readiness,
    realworld_visual_candidate_declarations,
    realworld_visual_candidate_lifecycle,
)
from roboclaws.household.household_backend_contract import HouseholdBackendSession
from roboclaws.household.household_runtime_contract import (
    RAW_FPV_ONLY_MODE,
    VISUAL_CANDIDATE_ALREADY_HANDLED_REASON,
    _declared_category_matches_object,
)
from roboclaws.household.scenario import build_cleanup_scenario
from roboclaws.household.types import (
    CleanupObject,
    CleanupReceptacle,
    CleanupScenario,
    PrivateScoringManifest,
)
from tests.contract.molmo_cleanup.household_runtime_contract_support import (
    _assert_no_forbidden_keys,
    _contract,
    _live_style_alias_scenario,
    _observe_raw_fpv_category,
    _same_room_fallback_scenario,
)


def test_visual_candidate_exact_category_matching_does_not_cross_broad_family() -> None:
    plate = CleanupObject("plate_01", "Plate", "Plate", "table_01")
    mug = CleanupObject("mug_01", "ceramic mug", "dish", "sofa_01")
    ladle = CleanupObject("ladle_01", "Ladle", "Ladle", "counter_01")

    assert _declared_category_matches_object("plate", plate) is True
    assert _declared_category_matches_object("dish", plate) is True
    assert _declared_category_matches_object("cup", plate) is False
    assert _declared_category_matches_object("plate", mug) is False
    assert _declared_category_matches_object("dish", mug) is True
    assert _declared_category_matches_object("spoon", ladle) is True


def test_realworld_unresolved_model_declared_candidate_is_unpickable() -> None:
    contract = _contract(
        HouseholdBackendSession(build_cleanup_scenario(seed=7)),
        perception_mode=RAW_FPV_ONLY_MODE,
    )

    waypoint = contract.metric_map()["inspection_waypoints"][0]
    contract.navigate_to_waypoint(str(waypoint["waypoint_id"]))
    observation = contract.observe()
    declared = contract.declare_visual_candidates(
        observation["raw_fpv_observation"]["observation_id"],
        candidates=[
            {
                "category": "imaginary widget",
                "evidence_note": "ambiguous tiny object in the far corner",
                "image_region": {"type": "verbal_region", "value": "far corner"},
            }
        ],
        producer_type="main_cleanup_agent",
        producer_id="test_agent",
    )
    candidate = declared["model_declared_observations"][0]
    picked = contract.pick(candidate["object_id"])

    assert candidate["grounding_status"] == "unresolved"
    assert "No public actionable object matched" in candidate["recovery_hint"]
    assert picked["ok"] is False
    assert picked["error_reason"] == "visual_candidate_not_resolved"
    worklist_item = next(
        item
        for item in contract.cleanup_worklist_payload()["objects"]
        if item["object_id"] == candidate["object_id"]
    )
    assert worklist_item["state"] == "grounding_unresolved"
    assert worklist_item["cleanup_recommended"] is False
    assert candidate["private_truth_included"] is False
    _assert_no_forbidden_keys(declared)
    _assert_no_forbidden_keys(picked)


def test_realworld_navigate_to_unresolved_visual_candidate_says_continue_sweep() -> None:
    contract = _contract(
        HouseholdBackendSession(build_cleanup_scenario(seed=7)),
        perception_mode=RAW_FPV_ONLY_MODE,
    )

    waypoint = contract.metric_map()["inspection_waypoints"][0]
    contract.navigate_to_waypoint(str(waypoint["waypoint_id"]))
    observation = contract.observe()
    response = contract.navigate_to_visual_candidate(
        observation["raw_fpv_observation"]["observation_id"],
        category="imaginary widget",
        evidence_note="ambiguous tiny object in the far corner",
        image_region={"type": "verbal_region", "value": "far corner"},
        producer_type="main_cleanup_agent",
        producer_id="test_agent",
    )

    assert response["ok"] is False
    assert response["error_reason"] == "visual_candidate_not_resolved"
    assert response["required_next_tool"] == "navigate_to_relative_pose"
    assert "adjust_camera" in response["recovery_tool_options"]
    assert "unchanged pose" in response["recovery_hint"]
    assert "No public actionable object matched" in response["recovery_hint"]
    assert "instead of looping" in response["recovery_hint"]
    _assert_no_forbidden_keys(response)


def test_realworld_raw_fpv_grounding_uses_source_observation_bbox_binding(
    tmp_path: Path,
    monkeypatch,
) -> None:
    scenario = build_cleanup_scenario(seed=7)
    session = HouseholdBackendSession(scenario)
    contract = _contract(session, perception_mode=RAW_FPV_ONLY_MODE)
    target = scenario.objects[0]
    target_location = session.object_locations()[target.object_id]
    waypoint = next(
        item
        for item in contract.metric_map()["inspection_waypoints"]
        if target_location
        not in set(contract._private_waypoint_for_public_waypoint(item).get("fixture_ids") or [])
    )
    contract.navigate_to_waypoint(str(waypoint["waypoint_id"]))
    observation = contract.observe()
    observation_id = observation["raw_fpv_observation"]["observation_id"]
    fpv_path = tmp_path / "raw_fpv_001.fpv.png"
    bindings_path = fpv_path.with_suffix(".bindings.private.json")
    bindings_path.write_text(
        json.dumps(
            {
                "schema": "raw_fpv_private_bindings_v1",
                "image_dimensions": {"width": 540, "height": 360},
                "bindings": [
                    {
                        "object_id": target.object_id,
                        "category": target.category,
                        "name": target.name,
                        "location_id": target_location,
                        "bbox": [100, 80, 80, 60],
                        "object_pixels": 3200,
                    },
                    {
                        "object_id": "low_pixel_bbox_distractor",
                        "category": target.category,
                        "name": f"distant {target.name}",
                        "location_id": target_location,
                        "bbox": [105, 85, 70, 50],
                        "object_pixels": 5,
                    },
                ],
            },
            sort_keys=True,
        ),
        encoding="utf-8",
    )
    contract.attach_raw_fpv_observation_artifact(
        observation_id,
        views={"fpv": str(fpv_path)},
    )

    match = realworld_visual_candidate_lifecycle.resolve_visual_candidate(
        contract,
        contract._private_waypoint_for_public_waypoint(waypoint),
        {
            "source_observation_id": observation_id,
            "category": target.category,
            "source_fixture_id": contract._public_fixture_reference_id(target_location),
            "image_region": {"type": "bbox", "value": [105, 85, 70, 50]},
        },
    )

    assert match["status"] == "resolved"
    assert match["objects"][0].object_id == target.object_id
    assert match["locality_status"] == "exact_source_fixture_in_source_observation"
    assert match["binding_source"] == "private_observation_segmentation"
    monkeypatch.setattr(
        realworld_visual_candidate_declarations.realworld_visual_perception_navigation,
        "objects_visible_from_waypoint",
        lambda _contract, _waypoint: [(target, target_location)],
    )
    simulated_inputs = (
        realworld_visual_candidate_declarations.simulated_raw_fpv_inputs_for_observation(
            contract,
            waypoint,
            observation_id=observation_id,
        )
    )
    assert simulated_inputs == [
        {
            "category": target.category,
            "source_fixture_id": contract._public_fixture_reference_id(target_location),
            "evidence_note": (
                "simulated camera model declared a public camera-derived "
                f"{target.category} candidate"
            ),
            "image_region": {"type": "bbox", "value": [100, 80, 80, 60]},
            "confidence": 0.9,
        }
    ]
    assert target.object_id not in json.dumps(simulated_inputs)
    assert target_location not in json.dumps(simulated_inputs)


def test_realworld_unresolved_visual_candidates_do_not_count_as_model_declared_actions() -> None:
    contract = _contract(
        HouseholdBackendSession(build_cleanup_scenario(seed=7)),
        perception_mode=RAW_FPV_ONLY_MODE,
    )

    waypoint = contract.metric_map()["inspection_waypoints"][0]
    contract.navigate_to_waypoint(str(waypoint["waypoint_id"]))
    observation = contract.observe()
    response = contract.navigate_to_visual_candidate(
        observation["raw_fpv_observation"]["observation_id"],
        category="imaginary widget",
        evidence_note="ambiguous tiny object in the far corner",
        image_region={"type": "verbal_region", "value": "far corner"},
        producer_type="main_cleanup_agent",
        producer_id="test_agent",
    )
    evidence = contract.model_declared_observations_payload()

    assert response["ok"] is False
    assert response["error_reason"] == "visual_candidate_not_resolved"
    assert evidence["observation_count"] == 1
    assert evidence["acted_count"] == 0
    assert evidence["observations"][0]["grounding_status"] == "unresolved"
    assert evidence["observations"][0]["acted_on"] is False


def test_realworld_navigate_to_visual_candidate_returns_grounded_handle() -> None:
    contract = _contract(
        HouseholdBackendSession(build_cleanup_scenario(seed=7)),
        perception_mode=RAW_FPV_ONLY_MODE,
    )

    observation = _observe_raw_fpv_category(contract, category="food")
    response = contract.navigate_to_visual_candidate(
        observation["raw_fpv_observation"]["observation_id"],
        category="tomato",
        evidence_note="round produce item on the desk",
        image_region={"type": "bbox", "value": [0.12, 0.24, 0.18, 0.16]},
        producer_type="main_cleanup_agent",
        producer_id="test_agent",
    )

    assert response["ok"] is True
    assert response["tool"] == "navigate_to_visual_candidate"
    assert response["object_id"].startswith("observed_")
    assert response["declaration_strategy"] == "inline_on_navigate"
    assert response["required_next_tool"] == "pick"
    assert response["model_declared_observation"]["grounding_status"] == "resolved"
    assert response["actionability_status"] == "actionable"
    assert response["visual_grounding_evidence"]["reviewability_status"] == "reviewable"
    assert response["visual_grounding_evidence"]["bbox_coordinate_space"] == "normalized_xywh"
    assert contract.pick(response["object_id"])["ok"] is True
    _assert_no_forbidden_keys(response)


def test_realworld_raw_fpv_non_recommended_candidate_cannot_navigate_or_pick() -> None:
    scenario = CleanupScenario(
        scenario_id="raw-fpv-not-recommended-test",
        task="leave an already tidy mug in place",
        seed=7,
        objects=(CleanupObject("mug_01", "mug", "dish", "sink_01"),),
        receptacles=(CleanupReceptacle("sink_01", "Sink", "kitchen", category="Sink"),),
        private_manifest=PrivateScoringManifest(
            scenario_id="raw-fpv-not-recommended-test",
            targets=(),
            success_threshold=0,
        ),
    )
    contract = _contract(
        HouseholdBackendSession(scenario),
        perception_mode=RAW_FPV_ONLY_MODE,
    )

    observation = _observe_raw_fpv_category(contract, category="dish")
    response = contract.navigate_to_visual_candidate(
        observation["raw_fpv_observation"]["observation_id"],
        category="mug",
        evidence_note="mug already resting at its normal sink destination",
        image_region={"type": "bbox", "value": [0.2, 0.2, 0.2, 0.2]},
        producer_type="main_cleanup_agent",
        producer_id="test_agent",
    )

    assert response["ok"] is False
    assert response["error_reason"] == "visual_candidate_not_cleanup_recommended"
    assert response["cleanup_recommended"] is False
    assert "do not call navigate_to_waypoint again" in response["recovery_hint"]
    assert response["required_next_tool"] == "observe"
    object_id = response["object_id"]
    assert contract.navigate_to_object(object_id)["error_reason"] == (
        "visual_candidate_not_cleanup_recommended"
    )
    assert contract.pick(object_id)["error_reason"] == "visual_candidate_not_cleanup_recommended"
    _assert_no_forbidden_keys(response)


def test_realworld_raw_fpv_visual_candidate_requires_reviewable_fpv_bbox() -> None:
    contract = _contract(
        HouseholdBackendSession(build_cleanup_scenario(seed=7)),
        perception_mode=RAW_FPV_ONLY_MODE,
    )

    observation = _observe_raw_fpv_category(contract, category="food")
    response = contract.navigate_to_visual_candidate(
        observation["raw_fpv_observation"]["observation_id"],
        category="tomato",
        evidence_note="round produce item on the desk",
        image_region={"type": "verbal_region", "value": "front of desk"},
        producer_type="main_cleanup_agent",
        producer_id="test_agent",
    )

    declaration = response["model_declared_observation"]
    evidence = response["visual_grounding_evidence"]
    assert response["ok"] is False
    assert response["error_reason"] == "visual_evidence_not_reviewable"
    assert response["required_next_tool"] == "observe"
    assert response["actionability_status"] == "needs_visual_evidence"
    assert declaration["grounding_status"] == "resolved"
    assert declaration["actionability_status"] == "needs_visual_evidence"
    assert evidence["schema"] == "visual_grounding_evidence_v1"
    assert evidence["camera_frame"] == "agent_facing_fpv"
    assert evidence["reviewability_status"] == "not_reviewable"
    assert evidence["reviewability_reason"] == "missing_bbox"
    assert contract.pick(response["object_id"])["error_reason"] == "visual_evidence_not_reviewable"
    worklist_item = next(
        item
        for item in contract.cleanup_worklist_payload()["objects"]
        if item["object_id"] == response["object_id"]
    )
    assert worklist_item["cleanup_recommended"] is False
    assert worklist_item["actionability_status"] == "needs_visual_evidence"
    _assert_no_forbidden_keys(response)


def test_minimal_raw_fpv_visual_candidate_can_omit_target_fixture_id() -> None:
    contract = _contract(
        HouseholdBackendSession(build_cleanup_scenario(seed=7)),
        perception_mode=RAW_FPV_ONLY_MODE,
    )

    observation = _observe_raw_fpv_category(contract, category="food")
    response = contract.navigate_to_visual_candidate(
        observation["raw_fpv_observation"]["observation_id"],
        category="tomato",
        evidence_note="round produce item on the desk",
        image_region={"type": "bbox", "value": [0.12, 0.24, 0.18, 0.16]},
        producer_type="main_cleanup_agent",
        producer_id="test_agent",
    )
    target_anchor_id = response["candidate_fixture_id"]

    declaration = response["model_declared_observation"]
    assert response["ok"] is True
    assert response["candidate_fixture_id"] == target_anchor_id
    assert response["candidate_fixture_category"] == "fridge"
    assert response["recommended_tool"] == "place_inside"
    assert declaration["target_fixture_id"] == ""
    assert declaration["target_fixture_category"] == ""
    assert declaration["target_plausibility"]["status"] == "unknown_fixture"
    worklist = contract.cleanup_worklist_payload()
    worklist_item = next(
        item for item in worklist["objects"] if item["object_id"] == response["object_id"]
    )
    assert worklist_item["cleanup_recommended"] is True
    assert worklist_item["actionability_status"] == "actionable"
    assert worklist_item["candidate_fixture_id"] == target_anchor_id
    assert worklist_item["recommended_tool"] == "place_inside"
    assert contract.pick(response["object_id"])["ok"] is True
    _assert_no_forbidden_keys(response)


def test_minimal_raw_fpv_visual_candidate_requires_public_destination() -> None:
    contract = _contract(
        HouseholdBackendSession(build_cleanup_scenario(seed=7)),
        perception_mode=RAW_FPV_ONLY_MODE,
    )

    waypoint = contract.metric_map()["inspection_waypoints"][0]
    contract.navigate_to_waypoint(str(waypoint["waypoint_id"]))
    observation = contract.observe()
    response = contract.navigate_to_visual_candidate(
        observation["raw_fpv_observation"]["observation_id"],
        category="plant",
        evidence_note="plant visible on nearby surface",
        image_region={"type": "bbox", "value": [0.2, 0.2, 0.2, 0.2]},
        producer_type="main_cleanup_agent",
        producer_id="test_agent",
    )

    assert response["ok"] is False
    assert response["error_reason"] == "visual_candidate_not_resolved"
    assert response["object_id"].startswith("observed_")
    assert response["grounding_status"] == "unresolved"
    assert response["required_next_tool"] == "navigate_to_relative_pose"
    assert "No public actionable object matched" in response["recovery_hint"]
    assert contract.pick(response["object_id"])["ok"] is False
    _assert_no_forbidden_keys(response)


def test_realworld_raw_fpv_rejects_already_handled_visual_candidate_without_navigation() -> None:
    contract = _contract(
        HouseholdBackendSession(build_cleanup_scenario(seed=7)),
        perception_mode=RAW_FPV_ONLY_MODE,
    )

    observation = _observe_raw_fpv_category(contract, category="food")
    raw_observation_id = observation["raw_fpv_observation"]["observation_id"]
    first = contract.navigate_to_visual_candidate(
        raw_observation_id,
        category="tomato",
        evidence_note="round produce item on the desk",
        image_region={"type": "bbox", "value": [0.12, 0.24, 0.18, 0.16]},
        producer_type="main_cleanup_agent",
        producer_id="test_agent",
    )
    retry_before_place = contract.navigate_to_visual_candidate(
        raw_observation_id,
        category="tomato",
        evidence_note="same produce item before pick",
        image_region={"type": "bbox", "value": [0.12, 0.24, 0.18, 0.16]},
        producer_type="main_cleanup_agent",
        producer_id="test_agent",
    )

    handle = first["object_id"]
    assert first["ok"] is True
    assert retry_before_place["ok"] is True
    assert retry_before_place["object_id"] == handle
    fixture_id = str(first["candidate_fixture_id"])
    declared_before_place = contract.model_declared_observations_payload()["observation_count"]
    assert contract.pick(handle)["ok"] is True
    assert contract.navigate_to_receptacle(fixture_id)["ok"] is True
    assert contract.open_receptacle(fixture_id)["ok"] is True
    assert contract.place_inside(fixture_id)["ok"] is True
    if "close" in contract.public_receptacles_by_id()[fixture_id].get("affordances", []):
        assert contract.close_receptacle(fixture_id)["ok"] is True

    contract.navigate_to_waypoint(
        str(contract.public_receptacles_by_id()[fixture_id]["preferred_inspection_waypoint_id"])
    )
    later_observation = contract.observe()
    lifecycle_before = dict(contract._object_lifecycle[handle])
    current_handle_before = contract._current_object_handle
    held_handle_before = contract._held_handle
    duplicate = contract.navigate_to_visual_candidate(
        later_observation["raw_fpv_observation"]["observation_id"],
        category="food",
        evidence_note="produce-like object already in the fridge area",
        image_region={"type": "bbox", "value": [0.2, 0.2, 0.2, 0.2]},
        producer_type="main_cleanup_agent",
        producer_id="test_agent",
    )

    assert duplicate["ok"] is False
    assert duplicate["error_reason"] == VISUAL_CANDIDATE_ALREADY_HANDLED_REASON
    assert duplicate["object_id"] == handle
    assert duplicate["required_next_tool"] == "observe"
    assert duplicate["model_declared_observation"]["actionability_status"] == "already_handled"
    assert contract.model_declared_observations_payload()["observation_count"] == (
        declared_before_place
    )
    assert contract._current_object_handle == current_handle_before
    assert contract._held_handle == held_handle_before
    assert contract._object_lifecycle[handle] == lifecycle_before
    _assert_no_forbidden_keys(duplicate)


def test_realworld_rejects_malformed_model_declared_candidate() -> None:
    contract = _contract(
        HouseholdBackendSession(build_cleanup_scenario(seed=7)),
        perception_mode=RAW_FPV_ONLY_MODE,
    )

    waypoint = contract.metric_map()["inspection_waypoints"][0]
    contract.navigate_to_waypoint(str(waypoint["waypoint_id"]))
    observation = contract.observe()
    declared = contract.declare_visual_candidates(
        observation["raw_fpv_observation"]["observation_id"],
        candidates=[
            {
                "category": "mug",
                "target_fixture_id": "sink_01",
                "evidence_note": "small item near the sink",
                "image_region": {"type": "polygon", "value": [1, 2, 3]},
            }
        ],
        producer_type="main_cleanup_agent",
        producer_id="test_agent",
    )

    assert declared["ok"] is False
    assert declared["error_reason"] == "invalid_visual_candidate"
    assert declared["candidate_error"]["field"] == "image_region.type"
    recovery = declared["raw_fpv_candidate_recovery"]
    assert recovery["schema"] == "raw_fpv_visual_candidate_recovery_v1"
    assert recovery["required_tool"] == "navigate_to_visual_candidate"
    assert recovery["base_metric_map_target_fixture_rule"] == "omit_target_fixture_id"
    assert (
        recovery["valid_example"]["source_observation_id"]
        == (observation["raw_fpv_observation"]["observation_id"])
    )
    assert "target_fixture_id" not in recovery["valid_example"]
    assert {
        "type": "bbox",
        "value": [0.1, 0.2, 0.3, 0.4],
    } in recovery["accepted_image_region_forms"]
    agent_view = contract.agent_view_payload()
    assert (
        agent_view_module.model_declared_observation_evidence(agent_view)["observation_count"] == 0
    )
    _assert_no_forbidden_keys(declared)

    missing_region = contract.declare_visual_candidates(
        observation["raw_fpv_observation"]["observation_id"],
        candidates=[
            {
                "category": "mug",
                "target_fixture_id": "sink_01",
                "evidence_note": "small item near the sink",
            }
        ],
        producer_type="main_cleanup_agent",
        producer_id="test_agent",
    )

    assert missing_region["ok"] is False
    assert missing_region["error_reason"] == "invalid_visual_candidate"
    assert missing_region["candidate_error"]["field"] == "image_region"
    assert "valid navigate_to_visual_candidate example" in missing_region["recovery_hint"]
    assert missing_region["raw_fpv_candidate_recovery"]["valid_example"]["image_region"] == {
        "type": "bbox",
        "value": [0.1, 0.2, 0.3, 0.4],
    }
    _assert_no_forbidden_keys(missing_region)


def test_realworld_model_declared_grounding_accepts_public_category_families() -> None:
    contract = _contract(
        HouseholdBackendSession(build_cleanup_scenario(seed=7)),
        perception_mode=RAW_FPV_ONLY_MODE,
    )

    observation = _observe_raw_fpv_category(contract, category="food")
    declared = contract.declare_visual_candidates(
        observation["raw_fpv_observation"]["observation_id"],
        candidates=[
            {
                "category": "tomato",
                "evidence_note": "round produce item on the desk",
                "image_region": {"type": "bbox", "value": [0.12, 0.24, 0.18, 0.16]},
            }
        ],
        producer_type="main_cleanup_agent",
        producer_id="test_agent",
    )

    candidate = declared["model_declared_observations"][0]
    assert candidate["grounding_status"] == "resolved"
    assert candidate["target_plausibility"]["status"] == "unknown_fixture"
    _assert_no_forbidden_keys(declared)


def test_realworld_model_declared_grounding_keeps_target_mismatch_as_metadata() -> None:
    contract = _contract(
        HouseholdBackendSession(build_cleanup_scenario(seed=7)),
        perception_mode=RAW_FPV_ONLY_MODE,
    )

    observation = _observe_raw_fpv_category(contract, category="toy")
    declared = contract.declare_visual_candidates(
        observation["raw_fpv_observation"]["observation_id"],
        candidates=[
            {
                "category": "toy",
                "evidence_note": "toy-like object on the coffee table",
                "image_region": {"type": "bbox", "value": [0.2, 0.2, 0.2, 0.2]},
            }
        ],
        producer_type="main_cleanup_agent",
        producer_id="test_agent",
    )

    candidate = declared["model_declared_observations"][0]
    assert candidate["grounding_status"] == "resolved"
    assert candidate["target_plausibility"]["status"] == "unknown_fixture"
    _assert_no_forbidden_keys(declared)


def test_realworld_model_declared_grounding_accepts_live_broad_categories() -> None:
    contract = _contract(
        HouseholdBackendSession(_live_style_alias_scenario()),
        perception_mode=RAW_FPV_ONLY_MODE,
    )

    observation = _observe_raw_fpv_category(contract, category="electronics")

    bad_source_fixture = contract.navigate_to_visual_candidate(
        observation["raw_fpv_observation"]["observation_id"],
        category="electronics",
        source_fixture_id="tvstand_01",
        evidence_note="black laptop on the sofa cushion",
        image_region={"type": "bbox", "value": [0.18, 0.22, 0.22, 0.18]},
        producer_type="main_cleanup_agent",
        producer_id="test_agent",
    )
    electronics = contract.navigate_to_visual_candidate(
        observation["raw_fpv_observation"]["observation_id"],
        category="electronics",
        evidence_note="black laptop on the sofa cushion",
        image_region={"type": "bbox", "value": [0.18, 0.22, 0.22, 0.18]},
        producer_type="main_cleanup_agent",
        producer_id="test_agent",
    )
    toy = contract.navigate_to_visual_candidate(
        observation["raw_fpv_observation"]["observation_id"],
        category="toy",
        evidence_note="teddy bear plush on the sofa",
        image_region={"type": "bbox", "value": [0.48, 0.34, 0.22, 0.2]},
        producer_type="main_cleanup_agent",
        producer_id="test_agent",
    )

    assert bad_source_fixture["ok"] is False
    assert bad_source_fixture["error_reason"] == "visual_candidate_not_resolved"
    assert bad_source_fixture["grounding_status"] == "unresolved"
    assert electronics["ok"] is False
    assert electronics["error_reason"] == "visual_candidate_not_cleanup_recommended"
    assert electronics["model_declared_observation"]["grounding_status"] == "resolved"
    assert (
        "waypoint-local public context"
        in electronics["model_declared_observation"]["grounding_basis"]
    )
    assert str(electronics["candidate_fixture_id"]).startswith("anchor_fixture_")
    assert electronics["recommended_tool"] == ""
    assert electronics["cleanup_recommended"] is False
    electronics_worklist_item = next(
        item
        for item in contract.cleanup_worklist_payload()["objects"]
        if item["object_id"] == electronics["object_id"]
    )
    assert electronics_worklist_item["cleanup_recommended"] is False
    assert electronics_worklist_item["candidate_fixture_id"] == electronics["candidate_fixture_id"]
    assert electronics_worklist_item["recommended_tool"] == "place"
    pending_handles = {
        item["object_id"] for item in realworld_done_readiness.pending_cleanup_candidates(contract)
    }
    assert electronics["object_id"] not in pending_handles
    assert toy["ok"] is False
    assert toy["error_reason"] == "visual_candidate_not_cleanup_recommended"
    assert toy["model_declared_observation"]["grounding_status"] == "resolved"
    assert str(toy["candidate_fixture_id"]).startswith("anchor_fixture_")
    assert toy["cleanup_recommended"] is False
    assert toy["required_next_tool"] == "observe"
    _assert_no_forbidden_keys(bad_source_fixture)
    _assert_no_forbidden_keys(electronics)
    _assert_no_forbidden_keys(toy)


def test_realworld_raw_fpv_grounding_blocks_same_room_fallback() -> None:
    contract = _contract(
        HouseholdBackendSession(_same_room_fallback_scenario()),
        perception_mode=RAW_FPV_ONLY_MODE,
    )

    waypoint = contract.metric_map()["inspection_waypoints"][0]

    contract.navigate_to_waypoint(str(waypoint["waypoint_id"]))
    observation = contract.observe()
    response = contract.navigate_to_visual_candidate(
        observation["raw_fpv_observation"]["observation_id"],
        category="book",
        evidence_note="book visible on a neighboring shelf in the same room",
        image_region={"type": "bbox", "value": [0.62, 0.28, 0.16, 0.18]},
        source_fixture_id="desk_01",
        producer_type="main_cleanup_agent",
        producer_id="test_agent",
    )

    assert response["ok"] is False
    assert response["object_id"].startswith("observed_")
    assert response["error_reason"] == "visual_candidate_not_resolved"
    assert response["grounding_status"] == "unresolved"
    declaration = response["model_declared_observation"]
    assert declaration["grounding_status"] == "unresolved"
    assert "same-room object matched category" not in declaration["grounding_basis"]
    _assert_no_forbidden_keys(response)
