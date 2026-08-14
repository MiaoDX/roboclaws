from __future__ import annotations

from roboclaws.household import agent_view as agent_view_module
from roboclaws.household import (
    realworld_done_readiness,
)
from roboclaws.household.household_backend_contract import HouseholdBackendSession
from roboclaws.household.household_runtime_contract import (
    CAMERA_MODEL_POLICY_MODE,
    CAMERA_MODEL_POLICY_SCHEMA,
    RAW_FPV_ONLY_MODE,
    SIMULATED_CAMERA_MODEL_PROVENANCE,
)
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
    _confirm_world_label_detection,
    _contract,
    _empty_cleanup_scenario,
    _first_detection_by_category,
    _first_non_empty_observation,
    _observe_raw_fpv_heading_sweep,
    _set_latest_raw_fpv_heading,
)


def test_world_labels_sanitized_destination_policy_is_public_category_guidance() -> None:
    contract = _contract(
        HouseholdBackendSession(build_cleanup_scenario(seed=7)),
        evidence_lane="world-public-labels",
    )

    policies_by_category = {}
    for waypoint in contract.metric_map()["inspection_waypoints"]:
        contract.navigate_to_waypoint(str(waypoint["waypoint_id"]))
        observation = contract.observe()
        for detection in observation["visible_object_detections"]:
            policies_by_category.setdefault(
                str(detection["category"]).lower(),
                detection["destination_policy"],
            )

    food_policy = policies_by_category["food"]
    dish_policy = policies_by_category["dish"]
    book_policy = policies_by_category["book"]

    assert food_policy["source"] == "public_category_fixture_affordance"
    assert food_policy["preferred_fixture_categories"] == ["fridge", "refrigerator"]
    assert food_policy["placement_tool"] == "place_inside"
    assert food_policy["placement_tool_by_fixture_category"] == {
        "fridge": "place_inside",
        "refrigerator": "place_inside",
    }
    assert food_policy["private_truth_included"] is False
    assert dish_policy["preferred_fixture_categories"] == ["sink", "countertop"]
    assert dish_policy["placement_tool"] == "place"
    assert book_policy["placement_tool_by_fixture_category"]["shelvingunit"] == "place_inside"
    assert book_policy["placement_tool_by_fixture_category"]["desk"] == "place"


def test_realworld_contract_rejects_done_with_pending_public_candidates() -> None:
    contract = _contract(HouseholdBackendSession(build_cleanup_scenario(seed=7)))
    observation = _first_non_empty_observation(contract)
    detection = observation["visible_object_detections"][0]
    contract._detections_by_handle[detection["object_id"]][  # noqa: SLF001
        "cleanup_recommended"
    ] = True

    done = contract.done("finished sweep")

    assert done["ok"] is False
    assert done["status"] == "blocked"
    assert done["error_reason"] == "pending_cleanup_candidates"
    assert done["required_tool"] == "adjust_camera"
    assert done["pending_observed_handles"]
    assert done["pending_cleanup_candidates"][0]["candidate_state"] == "visual_scan_required"
    assert done["completion"]["status"] == "blocked"
    assert done["completion"]["blockers"][0]["type"] == "pending_cleanup_candidates"
    assert done["completion"]["blockers"][0]["required_tool"] == "adjust_camera"
    recovery_hint = done["completion"]["blockers"][0]["recovery_hint"]
    assert "authoritative pending_cleanup_candidates list" in recovery_hint
    assert "Do not inspect unrelated handles or expand the waypoint sweep" in recovery_hint
    assert "target_receptacle_id" not in str(done)
    _assert_no_forbidden_keys(done)


def test_visual_scan_failure_removes_stale_candidate_from_done_blockers() -> None:
    contract = _contract(HouseholdBackendSession(build_cleanup_scenario(seed=7)))
    observation = _first_non_empty_observation(contract)
    candidate = observation["visible_object_detections"][0]

    contract._mark_visual_scan_unresolved(  # noqa: SLF001
        candidate["object_id"],
        reason="visual_scan_confirmation_missing",
    )
    readiness = contract.evaluate_done_readiness()
    blocked_handles = {
        handle
        for blocker in readiness["blockers"]
        for handle in blocker.get("pending_observed_handles", [])
    }

    assert candidate["object_id"] not in blocked_handles


def test_open_ended_done_ignores_unrelated_pending_public_candidates() -> None:
    contract = _contract(
        HouseholdBackendSession(build_cleanup_scenario(seed=7)),
        task_prompt="我渴了，帮我找些解渴的东西",
        public_acceptance_config={"task_intent": "open-ended"},
    )
    observation = _first_non_empty_observation(contract)
    assert observation["visible_object_detections"]

    done = contract.done("open-ended operator task satisfied")

    assert done["ok"] is True
    assert done["tool"] == "done"
    readiness = contract.evaluate_done_readiness()
    assert readiness["task_intent"] == "open-ended"
    _assert_no_forbidden_keys(done)


def test_cleanup_intent_keeps_cleanup_done_policy_for_prompt_text() -> None:
    contract = _contract(
        HouseholdBackendSession(build_cleanup_scenario(seed=7)),
        task_prompt="我渴了，帮我找些解渴的东西",
        public_acceptance_config={"task_intent": "cleanup"},
    )
    observation = _first_non_empty_observation(contract)
    assert observation["visible_object_detections"]

    done = contract.done("legacy custom-mode task finished")

    assert done["ok"] is False
    assert done["error_reason"] == "pending_cleanup_candidates"
    readiness = contract.evaluate_done_readiness()
    assert readiness["task_intent"] == "cleanup"
    _assert_no_forbidden_keys(done)


def test_world_labels_done_rejects_held_public_candidate_with_receptacle_hint() -> None:
    contract = _contract(HouseholdBackendSession(build_cleanup_scenario(seed=7)))
    detection = _confirm_world_label_detection(
        contract,
        _first_detection_by_category(contract, "food"),
    )

    assert contract.navigate_to_object(detection["object_id"])["ok"] is True
    assert contract.pick(detection["object_id"])["ok"] is True

    done = contract.done("finished while holding a public candidate")

    assert done["ok"] is False
    assert done["error_reason"] == "pending_cleanup_candidates"
    assert done["required_tool"] == "navigate_to_receptacle"
    pending = next(
        item
        for item in done["pending_cleanup_candidates"]
        if item["object_id"] == detection["object_id"]
    )
    assert pending["state"] == "held"
    assert pending["required_tool"] == "navigate_to_receptacle"
    assert pending["candidate_fixture_id"] == ""
    assert pending["destination_options"]
    blocker = done["completion"]["blockers"][0]
    assert blocker["required_tool"] == "navigate_to_receptacle"
    _assert_no_forbidden_keys(done)


def test_world_labels_done_rejects_navigated_public_candidate_until_pick() -> None:
    contract = _contract(HouseholdBackendSession(build_cleanup_scenario(seed=7)))
    detection = _confirm_world_label_detection(
        contract,
        _first_detection_by_category(contract, "food"),
    )

    assert contract.navigate_to_object(detection["object_id"])["ok"] is True

    done = contract.done("finished immediately after object navigation")

    assert done["ok"] is False
    assert done["error_reason"] == "pending_cleanup_candidates"
    pending = next(
        item
        for item in done["pending_cleanup_candidates"]
        if item["object_id"] == detection["object_id"]
    )
    assert pending["state"] == "navigating_to_object"
    assert pending["required_tool"] == "pick"
    _assert_no_forbidden_keys(done)


def test_world_labels_rejects_destination_outside_public_policy() -> None:
    contract = _contract(HouseholdBackendSession(build_cleanup_scenario(seed=7)))
    detection = _confirm_world_label_detection(
        contract,
        _first_detection_by_category(contract, "food"),
    )
    assert contract.navigate_to_object(detection["object_id"])["ok"] is True
    picked = contract.pick(detection["object_id"])
    assert picked["ok"] is True
    assert picked["required_next_tool"] == "navigate_to_receptacle"
    assert {option["candidate_fixture_category"] for option in picked["destination_options"]} == {
        "fridge"
    }
    stale = contract.navigate_to_receptacle("invented_fixture")
    assert stale["error_reason"] == "stale_reference"
    assert stale["object_id"] == detection["object_id"]
    assert stale["destination_options"] == picked["destination_options"]
    wrong_fixture_id = next(
        fixture_id
        for fixture_id, fixture in contract.public_receptacles_by_id().items()
        if str(fixture.get("category") or "").lower() == "bookshelf"
    )

    rejected = contract.navigate_to_receptacle(wrong_fixture_id)

    assert rejected["ok"] is False
    assert rejected["error_reason"] == "destination_policy_mismatch"
    assert rejected["object_id"] == detection["object_id"]
    assert rejected["required_tool"] == "navigate_to_receptacle"
    assert rejected["destination_options"]
    assert {option["candidate_fixture_category"] for option in rejected["destination_options"]} == {
        "fridge"
    }
    correct_fixture_id = rejected["destination_options"][0]["candidate_fixture_id"]
    assert contract.navigate_to_receptacle(correct_fixture_id)["ok"] is True
    _assert_no_forbidden_keys(rejected)


def test_world_labels_destination_options_are_executable_public_receptacles() -> None:
    contract = _contract(HouseholdBackendSession(build_cleanup_scenario(seed=7)))
    detection = _confirm_world_label_detection(
        contract,
        _first_detection_by_category(contract, "dish"),
    )
    assert contract.navigate_to_object(detection["object_id"])["ok"] is True
    picked = contract.pick(detection["object_id"])

    public_receptacles = contract.public_receptacles_by_id()
    option_ids = {str(option["candidate_fixture_id"]) for option in picked["destination_options"]}

    assert option_ids
    assert option_ids <= public_receptacles.keys()
    for option_id in option_ids:
        internal_id = contract.internal_fixture_id_for_public_reference(option_id)
        assert internal_id in contract._fixtures  # noqa: SLF001


def test_open_ended_done_still_rejects_held_public_candidate() -> None:
    contract = _contract(
        HouseholdBackendSession(build_cleanup_scenario(seed=7)),
        task_prompt="我渴了，帮我找些解渴的东西",
        public_acceptance_config={"task_intent": "open-ended"},
    )
    detection = _confirm_world_label_detection(
        contract,
        _first_detection_by_category(contract, "food"),
    )

    assert contract.navigate_to_object(detection["object_id"])["ok"] is True
    assert contract.pick(detection["object_id"])["ok"] is True

    done = contract.done("open-ended task finished while holding an object")

    assert done["ok"] is False
    assert done["error_reason"] == "pending_cleanup_candidates"
    assert done["required_tool"] == "navigate_to_receptacle"
    assert done["pending_cleanup_candidates"][0]["state"] == "held"
    _assert_no_forbidden_keys(done)


def test_world_labels_sanitized_done_rejects_held_policy_required_object() -> None:
    contract = _contract(
        HouseholdBackendSession(build_cleanup_scenario(seed=7)),
        evidence_lane="world-public-labels",
    )
    detection = _confirm_world_label_detection(
        contract,
        _first_detection_by_category(contract, "food"),
    )

    assert contract.navigate_to_object(detection["object_id"])["ok"] is True
    assert contract.pick(detection["object_id"])["ok"] is True
    for waypoint in contract.metric_map()["inspection_waypoints"]:
        if waypoint["visited"]:
            continue
        contract.navigate_to_waypoint(str(waypoint["waypoint_id"]))
        contract.observe()

    done = contract.done("finished while holding")

    assert done["ok"] is False
    assert done["error_reason"] == "pending_cleanup_candidates"
    assert done["required_tool"] == "navigate_to_receptacle"
    pending = next(
        item
        for item in done["pending_cleanup_candidates"]
        if item["object_id"] == detection["object_id"]
    )
    assert pending["object_id"] == detection["object_id"]
    assert pending["state"] == "held"
    assert pending["candidate_fixture_id"] == ""
    assert pending["destination_policy"]["preferred_fixture_categories"] == [
        "fridge",
        "refrigerator",
    ]
    assert any(
        option["candidate_fixture_category"] == "fridge"
        and option["recommended_tool"] == "place_inside"
        and option["candidate_fixture_id"].startswith("anchor_fixture_")
        for option in pending["destination_options"]
    )
    _assert_no_forbidden_keys(done)


def test_world_labels_sanitized_done_rejects_policy_required_pending_objects() -> None:
    contract = _contract(
        HouseholdBackendSession(build_cleanup_scenario(seed=7)),
        evidence_lane="world-public-labels",
    )
    observation = _first_non_empty_observation(contract)
    detection = observation["visible_object_detections"][0]
    source_fixture_id = detection["support_estimate"]["fixture_id"]
    internal_source_fixture_id = contract.internal_fixture_id_for_public_reference(
        source_fixture_id
    )
    contract._fixtures[internal_source_fixture_id]["category"] = "bed"  # noqa: SLF001
    detection = _confirm_world_label_detection(contract, detection)
    assert (
        contract._detections_by_handle[detection["object_id"]][  # noqa: SLF001
            "cleanup_recommended"
        ]
        is True
    )
    source_waypoint_id = detection["waypoint_id"]
    other_waypoint_id = next(
        waypoint["waypoint_id"]
        for waypoint in contract.metric_map()["inspection_waypoints"]
        if waypoint["waypoint_id"] != source_waypoint_id
    )
    contract.navigate_to_waypoint(other_waypoint_id)
    contract.observe()
    contract.navigate_to_waypoint(source_waypoint_id)
    contract.observe()
    assert (
        contract._detections_by_handle[detection["object_id"]][  # noqa: SLF001
            "cleanup_recommended"
        ]
        is False
    )

    done = contract.done("finished without cleaning sanitized detections")

    assert done["ok"] is False
    assert done["error_reason"] == "pending_cleanup_candidates"
    assert done["required_tool"] == "adjust_camera"
    assert detection["object_id"] in done["pending_observed_handles"]
    pending = next(
        item
        for item in done["pending_cleanup_candidates"]
        if item["object_id"] == detection["object_id"]
    )
    assert pending["destination_policy_status"] == "policy_required"
    assert pending["candidate_fixture_id"] == ""
    assert pending["candidate_state"] == "visual_scan_required"
    _assert_no_forbidden_keys(done)


def test_world_labels_sanitized_done_ignores_not_recommended_pending_objects() -> None:
    contract = _contract(
        HouseholdBackendSession(build_cleanup_scenario(seed=7)),
        evidence_lane="world-public-labels",
    )
    detection = _first_detection_by_category(contract, "electronics")
    handle = detection["object_id"]

    pending = realworld_done_readiness.pending_cleanup_candidates(contract)

    assert handle not in {item["object_id"] for item in pending}


def test_realworld_raw_fpv_done_gate_scales_to_small_generated_mess_count() -> None:
    scenario = CleanupScenario(
        scenario_id="small-raw-fpv-done-gate-test",
        task="clean a small room",
        seed=7,
        objects=(
            CleanupObject("mug_01", "mug", "dish", "sofa_01"),
            CleanupObject("book_01", "book", "book", "floor_01"),
            CleanupObject("apple_01", "apple", "food", "desk_01"),
        ),
        receptacles=(
            CleanupReceptacle("sofa_01", "Sofa", "living"),
            CleanupReceptacle("floor_01", "Floor", "living", kind="surface"),
            CleanupReceptacle("desk_01", "Desk", "office", kind="surface"),
            CleanupReceptacle("sink_01", "Sink", "kitchen"),
            CleanupReceptacle("bookshelf_01", "Bookshelf", "living"),
            CleanupReceptacle("fridge_01", "Fridge", "kitchen"),
        ),
        private_manifest=PrivateScoringManifest(
            scenario_id="small-raw-fpv-done-gate-test",
            targets=(
                TargetRule("mug_01", ("sink_01",)),
                TargetRule("book_01", ("bookshelf_01",)),
                TargetRule("apple_01", ("fridge_01",)),
            ),
            success_threshold=2,
        ),
    )
    contract = _contract(
        HouseholdBackendSession(scenario),
        perception_mode=RAW_FPV_ONLY_MODE,
        public_acceptance_config={"required_model_declared_observations": 3},
    )

    _observe_raw_fpv_heading_sweep(contract)

    contract._model_declared_observations = [{}, {}]  # noqa: SLF001
    shortfall = contract.done("small raw-fpv rehearsal shortfall")
    contract._model_declared_observations.append({})  # noqa: SLF001
    done = contract.done("small raw-fpv rehearsal complete")

    assert shortfall["ok"] is False
    assert shortfall["status"] == "blocked"
    assert shortfall["error_reason"] == "insufficient_model_declared_observations"
    assert shortfall["required_model_declared_observations"] == 3
    assert shortfall["completion"]["status"] == "blocked"
    assert shortfall["completion"]["blockers"][0]["type"] == (
        "insufficient_model_declared_observations"
    )
    assert done["ok"] is True
    assert done["cleanup_status"] == "failed"


def test_realworld_done_does_not_require_unresolved_visual_candidates() -> None:
    contract = _contract(
        HouseholdBackendSession(build_cleanup_scenario(seed=7)),
        perception_mode=RAW_FPV_ONLY_MODE,
    )

    waypoint = contract.metric_map()["inspection_waypoints"][0]
    contract.navigate_to_waypoint(str(waypoint["waypoint_id"]))
    observation = contract.observe()
    for index in range(7):
        declared = contract.declare_visual_candidates(
            observation["raw_fpv_observation"]["observation_id"],
            candidates=[
                {
                    "category": f"imaginary widget {index}",
                    "evidence_note": "unresolved visual guess",
                    "image_region": {"type": "verbal_region", "value": f"far corner {index}"},
                }
            ],
            producer_type="main_cleanup_agent",
            producer_id="test_agent",
        )
        assert declared["model_declared_observations"][0]["grounding_status"] == "unresolved"

    early_done = contract.done("finished with unresolved false positives")

    assert early_done["ok"] is False
    assert early_done["error_reason"] == "insufficient_sweep_coverage"
    assert early_done["required_tool"] == "navigate_to_waypoint"
    assert early_done["next_waypoint_id"]
    assert early_done["sweep_coverage_rate"] < 0.90

    _observe_raw_fpv_heading_sweep(contract)

    done = contract.done("finished with unresolved false positives")

    assert done["ok"] is True
    assert done["tool"] == "done"
    _assert_no_forbidden_keys(done)


def test_raw_fpv_done_requires_canonical_distinct_heading_coverage() -> None:
    contract = _contract(
        HouseholdBackendSession(_empty_cleanup_scenario("raw-fpv-heading-coverage-test")),
        perception_mode=RAW_FPV_ONLY_MODE,
    )

    for waypoint in contract.metric_map()["inspection_waypoints"]:
        contract.navigate_to_waypoint(str(waypoint["waypoint_id"]))
        for _ in range(4):
            contract.observe()
            _set_latest_raw_fpv_heading(contract, 0.0)

    repeated_pose_done = contract.done("repeated the same camera heading")

    assert repeated_pose_done["ok"] is False
    assert repeated_pose_done["error_reason"] == "insufficient_raw_fpv_heading_coverage"
    assert repeated_pose_done["required_distinct_heading_count"] == 4
    assert repeated_pose_done["current_distinct_heading_count"] == 1
    assert repeated_pose_done["required_tool"] == "navigate_to_waypoint"

    _observe_raw_fpv_heading_sweep(contract, headings=(90.0, 180.0, 270.0))

    done = contract.done("covered four distinct headings per public waypoint")
    assert done["ok"] is True
    _assert_no_forbidden_keys(done)


def test_raw_fpv_done_requires_bounded_overlap_probe_for_candidate_free_closeout() -> None:
    contract = _contract(
        HouseholdBackendSession(_empty_cleanup_scenario("raw-fpv-overlap-probe-test")),
        perception_mode=RAW_FPV_ONLY_MODE,
        public_acceptance_config={"required_grounded_cleanup_chains": 1},
    )
    _observe_raw_fpv_heading_sweep(contract)

    pitch_only_waypoint = str(contract.metric_map()["inspection_waypoints"][0]["waypoint_id"])
    contract.navigate_to_waypoint(pitch_only_waypoint)
    contract.observe()
    contract._raw_fpv_observations[-1]["camera_offset"] = {  # noqa: SLF001
        "yaw_delta_deg": 90,
        "pitch_delta_deg": 40,
    }
    contract.adjust_camera(pitch_delta_deg=20)
    contract.observe()

    overlap_blocked = contract.done("covered headings but only made a pitch probe")
    assert overlap_blocked["ok"] is False
    assert overlap_blocked["error_reason"] == "insufficient_raw_fpv_overlap_probe_coverage"
    assert overlap_blocked["required_camera_adjustment"] == {
        "yaw_delta_deg": 45,
        "pitch_delta_deg": 20,
    }
    assert overlap_blocked["required_tool"] == "navigate_to_waypoint"
    assert overlap_blocked["followup_tool"] == "adjust_camera"
    assert overlap_blocked["probed_candidate_free_waypoint_ids"] == []
    assert "private target truth" in overlap_blocked["recovery_hint"]

    for waypoint in contract.metric_map()["inspection_waypoints"]:
        contract.navigate_to_waypoint(str(waypoint["waypoint_id"]))
        contract.adjust_camera(yaw_delta_deg=45, pitch_delta_deg=20)
        contract.observe()

    still_blocked = contract.done("covered headings and bounded overlap probes")
    assert still_blocked["ok"] is False
    assert still_blocked["error_reason"] == "insufficient_grounded_cleanup_chains"
    assert all(
        blocker["type"] != "insufficient_raw_fpv_overlap_probe_coverage"
        for blocker in still_blocked["completion"]["blockers"]
    )
    _assert_no_forbidden_keys(still_blocked)


def test_open_ended_raw_fpv_done_does_not_require_whole_room_heading_coverage() -> None:
    contract = _contract(
        HouseholdBackendSession(_empty_cleanup_scenario("open-ended-raw-fpv-heading-test")),
        perception_mode=RAW_FPV_ONLY_MODE,
        public_acceptance_config={"task_intent": "open-ended"},
    )

    done = contract.done("task-scoped public search is complete")

    assert done["ok"] is True
    assert all(
        blocker["type"] != "insufficient_raw_fpv_heading_coverage"
        for blocker in contract.evaluate_done_readiness()["blockers"]
    )
    _assert_no_forbidden_keys(done)


def test_realworld_camera_model_policy_registers_model_labelled_candidates() -> None:
    contract = _contract(
        HouseholdBackendSession(build_cleanup_scenario(seed=7)),
        perception_mode=CAMERA_MODEL_POLICY_MODE,
    )

    observation = {}
    candidate_response = {}
    for waypoint in contract.metric_map()["inspection_waypoints"]:
        contract.navigate_to_waypoint(str(waypoint["waypoint_id"]))
        observation = contract.observe()
        candidate_response = contract.declare_visual_candidates(
            observation["raw_fpv_observation"]["observation_id"]
        )
        if candidate_response["camera_model_candidates"]:
            break
    agent_view = contract.agent_view_payload()

    assert observation["perception_mode"] == CAMERA_MODEL_POLICY_MODE
    assert observation["structured_detections_available"] is False
    assert observation["visible_object_detections"] == []
    assert observation["raw_fpv_observation"]["perception_mode"] == CAMERA_MODEL_POLICY_MODE
    assert candidate_response["ok"] is True
    assert candidate_response["visible_object_detections"] == []
    assert candidate_response["camera_model_candidates"]
    assert candidate_response["model_declared_observations"]
    candidate = candidate_response["camera_model_candidates"][0]
    assert candidate["object_id"].startswith("observed_")
    assert candidate["perception_source"] == "model_declared_observation"
    assert candidate["model_provenance"] == SIMULATED_CAMERA_MODEL_PROVENANCE
    assert candidate["source_observation_id"].startswith("raw_fpv_")
    assert candidate["support_estimate"]["source"] == "public_semantic_anchor"
    declaration = candidate_response["model_declared_observations"][0]
    assert declaration["source_observation_id"].startswith("raw_fpv_")
    assert declaration["producer_type"] == SIMULATED_CAMERA_MODEL_PROVENANCE
    assert declaration["grounding_status"] == "resolved"
    assert declaration["target_plausibility"]["status"] in {
        "plausible",
        "weak",
        "unknown_fixture",
    }
    evidence = agent_view_module.camera_model_policy_evidence(agent_view)
    active_perception = agent_view_module.active_perception(agent_view)
    assert evidence["schema"] == CAMERA_MODEL_POLICY_SCHEMA
    assert evidence["enabled"] is True
    assert evidence["event_count"] >= 1
    assert evidence["candidate_count"] >= len(candidate_response["camera_model_candidates"])
    assert evidence["events"][0]["schema"] == "model_declared_observations_v1"
    assert active_perception["raw_fpv_summary"]["observation_count"] >= 1
    assert active_perception["camera_grounded_labels"]["sidecar_status"] == "available"
    assert active_perception["camera_grounded_labels"]["candidate_count"] >= len(
        candidate_response["camera_model_candidates"]
    )
    assert active_perception["visual_candidate_lifecycle"]["model_declared_observation_count"] >= 1
    model_evidence = agent_view_module.model_declared_observation_evidence(agent_view)
    assert model_evidence["schema"] == "model_declared_observations_v1"
    assert model_evidence["resolved_count"] >= 1
    assert agent_view_module.observed_objects(agent_view)
    _assert_no_forbidden_keys(observation)
    _assert_no_forbidden_keys(candidate_response)
    _assert_no_forbidden_keys(agent_view)


def test_realworld_camera_model_policy_records_sim_pipeline_provenance() -> None:
    contract = _contract(
        HouseholdBackendSession(build_cleanup_scenario(seed=7)),
        perception_mode=CAMERA_MODEL_POLICY_MODE,
    )

    observation = contract.observe()
    response = contract.declare_visual_candidates(
        observation["raw_fpv_observation"]["observation_id"]
    )
    evidence = response["model_declared_observation_evidence"]
    pipeline = evidence["visual_grounding_pipeline"]

    assert pipeline["pipeline_id"] == "sim"
    assert pipeline["stages"][0]["stage"] == "simulated_camera_model"
    assert pipeline["candidate_count"] == evidence["candidate_count"]
    assert contract.camera_model_policy_payload()["visual_grounding_pipeline_id"] == "sim"
    _assert_no_forbidden_keys(response)
