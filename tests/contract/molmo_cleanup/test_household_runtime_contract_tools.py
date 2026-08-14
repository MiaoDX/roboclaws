from __future__ import annotations

from roboclaws.household import agent_view as agent_view_module
from roboclaws.household.household_backend_contract import HouseholdBackendSession
from roboclaws.household.household_runtime_contract import (
    SANITIZED_VISIBLE_OBJECT_DETECTIONS_POLICY,
    SANITIZED_VISIBLE_OBJECT_DETECTIONS_PROVENANCE,
)
from roboclaws.household.scenario import build_cleanup_scenario
from tests.contract.molmo_cleanup.household_runtime_contract_support import (
    _assert_no_forbidden_keys,
    _confirm_world_label_detection,
    _contract,
    _first_detection_by_category,
    _first_non_empty_observation,
    _public_destination_fixture_for_detection,
)


def test_world_label_candidate_without_reviewable_fpv_bbox_is_not_actionable() -> None:
    contract = _contract(HouseholdBackendSession(build_cleanup_scenario(seed=7)))
    observation = _first_non_empty_observation(contract)
    detection = observation["visible_object_detections"][0]
    handle = detection["object_id"]

    navigation = contract.navigate_to_object(handle)
    picked = contract.pick(handle)
    worklist_item = next(
        item
        for item in contract.cleanup_worklist_payload()["objects"]
        if item["object_id"] == handle
    )

    assert navigation["ok"] is False
    assert navigation["error_reason"] == "visual_evidence_not_reviewable"
    assert navigation["required_next_tool"] == "adjust_camera"
    assert navigation["candidate_state"] == "visual_scan_required"
    assert navigation["visual_grounding_evidence"]["reviewability_status"] == "not_reviewable"
    assert picked["ok"] is False
    assert picked["error_reason"] == "visual_evidence_not_reviewable"
    assert "cleanup_recommended" not in worklist_item
    assert worklist_item["candidate_state"] == "visual_scan_required"
    assert worklist_item["actionability_status"] == "needs_visual_evidence"
    _assert_no_forbidden_keys(navigation)


def test_zero_camera_adjustment_does_not_confirm_world_label_candidate() -> None:
    contract = _contract(HouseholdBackendSession(build_cleanup_scenario(seed=7)))
    first_observation = _first_non_empty_observation(contract)
    handle = first_observation["visible_object_detections"][0]["object_id"]

    adjusted = contract.adjust_camera(yaw_delta_deg=0, pitch_delta_deg=0)
    second_observation = contract.observe()
    still_pending = next(
        item
        for item in second_observation["visible_object_detections"]
        if item["object_id"] == handle
    )
    navigation = contract.navigate_to_object(handle)

    assert adjusted["ok"] is False
    assert adjusted["error_reason"] == "noop_camera_adjustment"
    assert adjusted["required_next_tool"] == "adjust_camera"
    assert adjusted["followup_tool"] == "observe"
    assert adjusted["camera_offset"] == {"yaw_delta_deg": 0.0, "pitch_delta_deg": 0.0}
    assert adjusted["no_camera_motion"] is True
    assert adjusted["fresh_fpv_observation_required"] is True
    assert "does not create a fresh source FPV view" in adjusted["recovery_hint"]
    assert still_pending["candidate_state"] == "visual_scan_required"
    assert still_pending["visual_scan"]["fresh_fpv_observation_required"] is True
    assert navigation["ok"] is False
    assert navigation["required_next_tool"] == "adjust_camera"


def test_world_labels_sanitized_observations_omit_destination_oracle_fields() -> None:
    public_anchor_contract = _contract(HouseholdBackendSession(build_cleanup_scenario(seed=7)))
    public_anchor_observation = _first_non_empty_observation(public_anchor_contract)
    public_anchor_detection = public_anchor_observation["visible_object_detections"][0]

    sanitized_contract = _contract(
        HouseholdBackendSession(build_cleanup_scenario(seed=7)),
        evidence_lane="world-public-labels",
    )
    sanitized_observation = _first_non_empty_observation(sanitized_contract)
    detection = sanitized_observation["visible_object_detections"][0]

    assert "candidate_fixture_id" not in public_anchor_detection
    assert "recommended_tool" not in public_anchor_detection
    assert sanitized_observation["perception_source"] == (
        SANITIZED_VISIBLE_OBJECT_DETECTIONS_PROVENANCE
    )
    assert sanitized_observation["detection_exposure_policy"] == (
        SANITIZED_VISIBLE_OBJECT_DETECTIONS_POLICY
    )
    assert detection["object_id"].startswith("observed_")
    assert detection["category"]
    assert detection["image_region"]["type"] == "verbal_region"
    assert detection["source_observation_id"]
    assert detection["candidate_state"] == "visual_scan_required"
    assert detection["visual_grounding_evidence"]["reviewability_status"] == "not_reviewable"
    assert detection["producer_type"] == SANITIZED_VISIBLE_OBJECT_DETECTIONS_PROVENANCE
    assert detection["support_estimate"]
    assert "cleanup_recommended" not in detection
    assert detection["destination_policy_status"] == "policy_required"
    assert detection["destination_policy"]["private_truth_included"] is False
    assert detection["destination_policy"]["preferred_fixture_categories"]
    assert "candidate_fixture_id" not in detection["destination_policy"]
    assert "candidate_fixture_id" not in detection
    assert "recommended_tool" not in detection
    _assert_no_forbidden_keys(sanitized_observation)


def test_realworld_contract_rejects_skipped_semantic_phases_without_private_truth() -> None:
    contract = _contract(HouseholdBackendSession(build_cleanup_scenario(seed=7)))
    detection = _first_detection_by_category(contract, "dish")
    detection = _confirm_world_label_detection(contract, detection)
    target_fixture = _public_destination_fixture_for_detection(contract, detection)

    skipped_pick = contract.pick(detection["object_id"])
    assert skipped_pick["ok"] is False
    assert skipped_pick["error_reason"] == "semantic_order"
    assert skipped_pick["required_tool"] == "navigate_to_object"
    assert skipped_pick["object_id"] == detection["object_id"]
    _assert_no_forbidden_keys(skipped_pick)

    assert contract.navigate_to_object(detection["object_id"])["ok"] is True
    assert contract.pick(detection["object_id"])["ok"] is True

    skipped_place = contract.place(str(target_fixture["fixture_id"]))
    assert skipped_place["ok"] is False
    assert skipped_place["error_reason"] == "semantic_order"
    assert skipped_place["required_tool"] == "navigate_to_receptacle"
    assert skipped_place["fixture_id"] == target_fixture["fixture_id"]
    _assert_no_forbidden_keys(skipped_place)

    assert contract.navigate_to_receptacle(str(target_fixture["fixture_id"]))["ok"] is True
    assert contract.place(str(target_fixture["fixture_id"]))["ok"] is True


def test_realworld_contract_rejects_place_inside_before_opening_fridge() -> None:
    contract = _contract(HouseholdBackendSession(build_cleanup_scenario(seed=7)))
    detection = _confirm_world_label_detection(
        contract,
        _first_detection_by_category(contract, "food"),
    )
    target_fixture = _public_destination_fixture_for_detection(contract, detection)
    fixture_id = str(target_fixture["fixture_id"])

    assert fixture_id.startswith("anchor_fixture_")
    assert target_fixture["category"] == "fridge"
    assert contract.navigate_to_object(detection["object_id"])["ok"] is True
    assert contract.pick(detection["object_id"])["ok"] is True
    assert contract.navigate_to_receptacle(fixture_id)["ok"] is True

    skipped_open = contract.place_inside(fixture_id)
    assert skipped_open["ok"] is False
    assert skipped_open["error_reason"] == "semantic_order"
    assert skipped_open["required_tool"] == "open_receptacle"
    _assert_no_forbidden_keys(skipped_open)

    assert contract.open_receptacle(fixture_id)["ok"] is True
    placed = contract.place_inside(fixture_id)
    closed = contract.close_receptacle(fixture_id)

    assert placed["ok"] is True
    assert placed["object_id"] == detection["object_id"]
    assert placed["location_relation"] == "inside"
    assert placed["placement_diagnostic"]["relation"] == "inside"
    assert closed["ok"] is True
    assert closed["tool"] == "close_receptacle"
    assert closed["object_id"] == detection["object_id"]


def test_realworld_contract_routes_bookshelf_as_inside_without_close() -> None:
    contract = _contract(HouseholdBackendSession(build_cleanup_scenario(seed=7)))
    detection = _confirm_world_label_detection(
        contract,
        _first_detection_by_category(contract, "book"),
    )
    target_fixture = _public_destination_fixture_for_detection(contract, detection)
    fixture_id = str(target_fixture["fixture_id"])

    assert fixture_id.startswith("anchor_fixture_")
    assert str(target_fixture["category"]).lower() in {"bookshelf", "shelvingunit"}
    assert "place_inside" in target_fixture["affordances"]
    assert "open" not in target_fixture["affordances"]
    assert "close" not in target_fixture["affordances"]
    assert contract.navigate_to_object(detection["object_id"])["ok"] is True
    assert contract.pick(detection["object_id"])["ok"] is True
    assert contract.navigate_to_receptacle(fixture_id)["ok"] is True

    surface_place = contract.place(fixture_id)
    assert surface_place["ok"] is False
    assert surface_place["error_reason"] == "semantic_order"
    assert surface_place["required_tool"] == "place_inside"

    placed = contract.place_inside(fixture_id)
    assert placed["ok"] is True
    assert placed["location_relation"] == "inside"
    assert placed["placement_diagnostic"]["relation"] == "inside"

    skipped_close = contract.close_receptacle(fixture_id)
    assert skipped_close["ok"] is False
    assert skipped_close["required_tool"] == "place_inside"


def test_realworld_agent_view_payload_keeps_private_evaluation_out() -> None:
    contract = _contract(HouseholdBackendSession(build_cleanup_scenario(seed=7)))

    contract.metric_map()
    for waypoint in contract.metric_map()["inspection_waypoints"]:
        contract.navigate_to_waypoint(str(waypoint["waypoint_id"]))
        contract.observe()
    agent_view = contract.agent_view_payload()

    assert agent_view["schema"] == agent_view_module.AGENT_VIEW_SCHEMA
    assert agent_view_module.forbidden_private_fields_absent(agent_view) is True
    assert agent_view_module.observed_objects(agent_view)
    assert "generated_mess_set" not in agent_view
    assert "acceptable_destination_sets" not in agent_view
    assert "static_fixture_projection" not in agent_view
    _assert_no_forbidden_keys(agent_view)
