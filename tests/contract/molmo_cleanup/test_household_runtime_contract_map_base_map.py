from __future__ import annotations

from pathlib import Path

from roboclaws.household import agent_view as agent_view_module
from roboclaws.household.household_backend_contract import HouseholdBackendSession
from roboclaws.household.household_runtime_contract import (
    RAW_FPV_ONLY_MODE,
    HouseholdRuntimeContract,
    cleanup_policy_trace_from_events,
)
from roboclaws.household.scenario import build_cleanup_scenario
from roboclaws.household.types import (
    CleanupObject,
    CleanupReceptacle,
    CleanupScenario,
    PrivateScoringManifest,
    TargetRule,
)
from roboclaws.maps.bundle import static_landmarks_from_fixture_projection
from roboclaws.maps.route import validate_metric_map_route
from tests.contract.molmo_cleanup.household_runtime_contract_support import (
    PREBUILT_BUNDLE,
    _assert_base_metric_agent_view_observed_object_anchors,
    _assert_base_metric_runtime_map_candidates,
    _assert_base_metric_runtime_map_public_anchors,
    _assert_base_metric_static_map_privacy,
    _assert_nav2_agent_runtime_map,
    _assert_nav2_navigation_provenance,
    _assert_nav2_shaped_metric_map,
    _assert_no_forbidden_keys,
    _confirm_pick_and_navigate_to_fixture,
    _confirm_world_label_detection,
    _contract,
    _first_detected_metric_map_waypoint,
    _first_detection_waypoint,
    _first_non_empty_observation,
    _policy_trace_agent_view,
    _PoseRecordingBackend,
    _public_destination_fixture_for_detection,
    _trace_response,
)


def test_realworld_contract_defaults_to_base_metric_map() -> None:
    contract = _contract(HouseholdBackendSession(build_cleanup_scenario(seed=7)))

    metric_map = contract.metric_map()
    static_fixture_projection = contract.static_fixture_projection()

    assert metric_map["base_metric_map"]["enabled"] is True
    assert metric_map["rooms"]
    assert all(room["room_label"] for room in metric_map["rooms"])
    assert static_fixture_projection["rooms"] == []


def test_realworld_contract_exposes_nav2_shaped_public_map_and_provenance() -> None:
    contract = _contract(HouseholdBackendSession(build_cleanup_scenario(seed=7)))

    metric_map = contract.metric_map()
    static_fixture_projection = contract.static_fixture_projection()
    waypoint, waypoint_nav, detection = _first_detected_metric_map_waypoint(
        contract,
        metric_map,
    )
    fixture = _public_destination_fixture_for_detection(contract, detection)
    blocked_nav = contract.navigate_to_object(detection["object_id"])
    object_nav, receptacle_nav = _confirm_pick_and_navigate_to_fixture(
        contract,
        detection,
        fixture,
    )
    agent_view = contract.agent_view_payload()
    live_metric_map = contract.metric_map()

    _assert_nav2_shaped_metric_map(metric_map, static_fixture_projection, waypoint)
    _assert_nav2_navigation_provenance(
        waypoint_nav,
        blocked_nav,
        object_nav,
        receptacle_nav,
    )
    _assert_nav2_agent_runtime_map(agent_view, live_metric_map)
    _assert_no_forbidden_keys(agent_view)


def test_scene_index_backend_public_map_uses_usd_room_outline_scale() -> None:
    scenario = CleanupScenario(
        scenario_id="isaac-scene-index-procthor-10k-val-1-7-1",
        task="Clean up this loaded Isaac scene.",
        seed=7,
        objects=(
            CleanupObject(
                object_id="bowl_847a24bfa9d8b1a1f26661ebbb850f56_1_0_2",
                name="Bowl (Bowl_12)",
                category="Bowl",
                location_id="diningtable_f113cf7f8367e89f709b53cbee1a1c05_1_0_2",
            ),
        ),
        receptacles=(
            CleanupReceptacle(
                "diningtable_f113cf7f8367e89f709b53cbee1a1c05_1_0_2",
                "DiningTable DiningTable|2|1|0 Dining_Table_203_1",
                "isaac_scene",
                category="DiningTable",
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
    session = HouseholdBackendSession(scenario)
    session.backend.scenario_source = "isaac_scene_index"
    session.backend.room_outlines = [
        {
            "room_id": "room_2",
            "label": "Room 2",
            "center": [2.99, 4.983],
            "half_extents": [2.99, 4.983],
            "provenance": "isaac_usd_room_mesh_world_bounds",
            "usd_prim_path": "/val_1/Geometry/room_2_visual_0",
        },
        {
            "room_id": "room_3",
            "label": "Room 3",
            "center": [7.973, 2.99],
            "half_extents": [1.993, 2.99],
            "provenance": "isaac_usd_room_mesh_world_bounds",
            "usd_prim_path": "/val_1/Geometry/room_3_visual_0",
        },
    ]
    session.backend.receptacle_index = {
        "diningtable_f113cf7f8367e89f709b53cbee1a1c05_1_0_2": {
            "usd_world_bounds": {"center": [2.717858, 5.93953, 0.374628]}
        },
        "sink_07e796f32d0d3efce9acf4be00f3bc53_1_0_3": {
            "usd_world_bounds": {"center": [9.578895, 1.843155, 0.52296]}
        },
    }

    contract = _contract(session)
    metric_map = contract.metric_map()
    assert metric_map["rooms"]
    assert all(room["room_label"] for room in metric_map["rooms"])
    assert contract.static_fixture_projection()["rooms"] == []
    assert metric_map["inspection_waypoints"]
    assert all(
        waypoint["waypoint_source"] == "generated_exploration_candidate"
        for waypoint in metric_map["inspection_waypoints"]
    )
    assert all(
        waypoint["generation_policy"] == "base_navigation_area_centroid_clearance_v1"
        for waypoint in metric_map["inspection_waypoints"]
    )
    assert all(waypoint["navigation_area_id"] for waypoint in metric_map["inspection_waypoints"])


def test_scene_index_backend_room_outline_waypoints_avoid_fixture_occupied_goals() -> None:
    scenario = CleanupScenario(
        scenario_id="isaac-scene-index-procthor-10k-val-1-7-1",
        task="Clean up this loaded Isaac scene.",
        seed=7,
        objects=(
            CleanupObject(
                object_id="bowl_847a24bfa9d8b1a1f26661ebbb850f56_1_0_2",
                name="Bowl (Bowl_12)",
                category="Bowl",
                location_id="diningtable_f113cf7f8367e89f709b53cbee1a1c05_1_0_2",
            ),
        ),
        receptacles=(
            CleanupReceptacle("bed_258d27d5fe50e324961c7a8698ace951_1_0_2", "Bed", "isaac_scene"),
            CleanupReceptacle(
                "bed_aed5602affd158c34e7eda83481af599_1_0_2",
                "Bed",
                "isaac_scene",
            ),
            CleanupReceptacle(
                "chair_bfd87bce6390b5a5bb5fcae097e899f7_1_0_2",
                "Chair",
                "isaac_scene",
            ),
            CleanupReceptacle(
                "chair_bfd87bce6390b5a5bb5fcae097e899f7_2_0_2",
                "Chair",
                "isaac_scene",
            ),
            CleanupReceptacle(
                "chair_bfd87bce6390b5a5bb5fcae097e899f7_3_0_2",
                "Chair",
                "isaac_scene",
            ),
            CleanupReceptacle(
                "chestofdrawers_7a2e462b2666d3558113b2d84da9dc74_1_0_2",
                "Dresser",
                "isaac_scene",
            ),
            CleanupReceptacle(
                "diningtable_f113cf7f8367e89f709b53cbee1a1c05_1_0_2",
                "DiningTable",
                "isaac_scene",
            ),
            CleanupReceptacle(
                "sink_07e796f32d0d3efce9acf4be00f3bc53_1_0_3",
                "Sink",
                "isaac_scene",
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
    session = HouseholdBackendSession(scenario)
    session.backend.scenario_source = "isaac_scene_index"
    session.backend.room_outlines = [
        {
            "room_id": "room_2",
            "label": "Room 2",
            "center": [2.99, 4.983],
            "half_extents": [2.99, 4.983],
            "provenance": "isaac_usd_room_mesh_world_bounds",
            "usd_prim_path": "/val_1/Geometry/room_2_visual_0",
        },
        {
            "room_id": "room_3",
            "label": "Room 3",
            "center": [7.973, 2.99],
            "half_extents": [1.993, 2.99],
            "provenance": "isaac_usd_room_mesh_world_bounds",
            "usd_prim_path": "/val_1/Geometry/room_3_visual_0",
        },
    ]
    session.backend.receptacle_index = {
        "bed_258d27d5fe50e324961c7a8698ace951_1_0_2": {
            "usd_world_bounds": {"center": [2.818349, 8.99204, 0.856923]}
        },
        "bed_aed5602affd158c34e7eda83481af599_1_0_2": {
            "usd_world_bounds": {"center": [2.809145, 1.200613, 0.5965]}
        },
        "chair_bfd87bce6390b5a5bb5fcae097e899f7_1_0_2": {
            "usd_world_bounds": {"center": [3.308217, 5.945434, 0.4]}
        },
        "chair_bfd87bce6390b5a5bb5fcae097e899f7_2_0_2": {
            "usd_world_bounds": {"center": [2.70468, 6.83613, 0.4]}
        },
        "chair_bfd87bce6390b5a5bb5fcae097e899f7_3_0_2": {
            "usd_world_bounds": {"center": [2.11708, 5.932897, 0.4]}
        },
        "chestofdrawers_7a2e462b2666d3558113b2d84da9dc74_1_0_2": {
            "usd_world_bounds": {"center": [5.716285, 0.639941, 0.5]}
        },
        "diningtable_f113cf7f8367e89f709b53cbee1a1c05_1_0_2": {
            "usd_world_bounds": {"center": [2.717858, 5.93953, 0.374628]}
        },
        "sink_07e796f32d0d3efce9acf4be00f3bc53_1_0_3": {
            "usd_world_bounds": {"center": [9.578895, 1.843155, 0.52296]}
        },
    }

    contract = _contract(session)
    metric_map = contract.metric_map()
    static_fixture_projection = contract.static_fixture_projection()
    static_landmarks = static_landmarks_from_fixture_projection(static_fixture_projection)
    waypoints = metric_map["inspection_waypoints"]
    routes = [
        validate_metric_map_route(
            metric_map,
            static_landmarks,
            start_waypoint_id=str(waypoints[0]["waypoint_id"]),
            goal_waypoint_id=str(waypoint["waypoint_id"]),
        )
        for waypoint in waypoints
    ]

    assert len(waypoints) == len(contract.metric_map()["rooms"])
    assert all(route.ok for route in routes), [route.as_dict() for route in routes]
    assert all(waypoint.get("fixture_ids", []) == [] for waypoint in waypoints)
    assert all(waypoint["navigation_area_id"] for waypoint in waypoints)
    for waypoint in waypoints:
        navigation = contract.navigate_to_waypoint(str(waypoint["waypoint_id"]))
        assert navigation["ok"] is True, navigation


def test_cleanup_policy_trace_allows_public_map_query_before_post_place_observe() -> None:
    trace = cleanup_policy_trace_from_events(
        [
            _trace_response("navigate_to_waypoint", {"ok": True, "waypoint_id": "room_1_scan_1"}),
            _trace_response("observe", {"ok": True, "waypoint_id": "room_1_scan_1"}),
            _trace_response("navigate_to_object", {"ok": True, "object_id": "observed_001"}),
            _trace_response("pick", {"ok": True, "object_id": "observed_001"}),
            _trace_response(
                "navigate_to_receptacle",
                {
                    "ok": True,
                    "object_id": "observed_001",
                    "fixture_id": "sink_01",
                },
            ),
            _trace_response(
                "place",
                {
                    "ok": True,
                    "object_id": "observed_001",
                    "fixture_id": "sink_01",
                },
            ),
            _trace_response("metric_map", {"ok": True}),
            _trace_response("observe", {"ok": True, "waypoint_id": "room_1_scan_1"}),
        ],
        _policy_trace_agent_view([{"waypoint_id": "room_1_scan_1"}]),
    )

    assert trace["placed_object_count"] == 1
    assert trace["post_place_observe_count"] == 1
    assert trace["post_place_observe_complete"] is True
    assert trace["events"][-1]["role"] == "post_place_observe"


def test_cleanup_policy_trace_treats_last_base_waypoint_discovery_as_survey_first() -> None:
    trace = cleanup_policy_trace_from_events(
        [
            _trace_response("navigate_to_waypoint", {"ok": True, "waypoint_id": "room_1_scan_1"}),
            _trace_response(
                "observe",
                {
                    "ok": True,
                    "waypoint_id": "room_1_scan_1",
                    "visible_object_detections": [],
                },
            ),
            _trace_response("navigate_to_waypoint", {"ok": True, "waypoint_id": "room_1_scan_2"}),
            _trace_response(
                "observe",
                {
                    "ok": True,
                    "waypoint_id": "room_1_scan_2",
                    "visible_object_detections": [
                        {
                            "object_id": "observed_001",
                            "cleanup_recommended": True,
                        }
                    ],
                },
            ),
            _trace_response("navigate_to_object", {"ok": True, "object_id": "observed_001"}),
            _trace_response("pick", {"ok": True, "object_id": "observed_001"}),
            _trace_response(
                "navigate_to_receptacle",
                {"ok": True, "object_id": "observed_001", "fixture_id": "sink_01"},
            ),
            _trace_response(
                "place",
                {"ok": True, "object_id": "observed_001", "fixture_id": "sink_01"},
            ),
            _trace_response("observe", {"ok": True, "waypoint_id": "room_1_scan_2"}),
        ],
        _policy_trace_agent_view(
            [
                {"waypoint_id": "room_1_scan_1"},
                {"waypoint_id": "room_1_scan_2"},
            ]
        ),
    )

    assert trace["loop_style"] == "survey_first_cleanup_loop"
    assert trace["first_cleanup_before_full_survey"] is False
    assert trace["first_actionable_observation_index"] == 4
    assert trace["first_cleanup_index"] == 5


def test_map_build_fixture_anchors_keep_best_view_waypoint_binding() -> None:
    contract = _contract(
        HouseholdBackendSession(build_cleanup_scenario(seed=7)),
        evidence_lane="world-public-labels",
    )

    for waypoint in contract.metric_map()["inspection_waypoints"]:
        contract.navigate_to_waypoint(str(waypoint["waypoint_id"]))
        contract.adjust_camera(yaw_delta_deg=15)
        contract.observe()

    runtime_map = agent_view_module.runtime_metric_map(contract.agent_view_payload())
    fixture_waypoints = {
        item["category"]: item["waypoint_id"]
        for item in runtime_map["public_semantic_anchors"]
        if item.get("anchor_type") in {"fixture", "surface", "receptacle"}
    }

    assert fixture_waypoints["kitchen sink"] == "room_2_inspection"
    assert fixture_waypoints["fridge"] == "room_2_inspection"
    assert fixture_waypoints["sofa"] == "room_3_inspection"
    assert fixture_waypoints["desk"] == "room_4_inspection"
    assert fixture_waypoints["laundry hamper"] in {
        "room_6_inspection",
        "room_7_inspection",
        "room_8_inspection",
    }
    assert len(set(fixture_waypoints.values())) >= 4
    _assert_no_forbidden_keys(runtime_map)


def test_base_metric_map_hides_authored_semantics_and_uses_generated_candidates() -> None:
    contract = _contract(
        HouseholdBackendSession(build_cleanup_scenario(seed=7)),
    )

    metric_map = contract.metric_map()
    static_fixture_projection = contract.static_fixture_projection()
    waypoint, navigation, observation = _first_detection_waypoint(contract, metric_map)
    agent_view = contract.agent_view_payload()
    runtime_map = agent_view_module.runtime_metric_map(agent_view)

    _assert_base_metric_static_map_privacy(metric_map, static_fixture_projection, waypoint)
    assert navigation["ok"] is True
    assert observation["visible_object_detections"]
    _assert_base_metric_runtime_map_candidates(runtime_map, waypoint)
    _assert_base_metric_runtime_map_public_anchors(runtime_map, waypoint)
    _assert_base_metric_agent_view_observed_object_anchors(agent_view, runtime_map)
    _assert_no_forbidden_keys(agent_view)


def test_base_metric_runtime_map_current_anchor_overrides_same_id_prior_anchor() -> None:
    seed_contract = _contract(
        HouseholdBackendSession(build_cleanup_scenario(seed=7)),
    )
    _first_non_empty_observation(seed_contract)
    seed_runtime_map = seed_contract.agent_view_payload()["runtime_metric_map"]
    seed_anchor = next(
        item
        for item in seed_runtime_map["public_semantic_anchors"]
        if item["anchor_type"] in {"fixture", "receptacle"}
    )
    prior_snapshot = {
        "public_semantic_anchors": [
            {
                **seed_anchor,
                "freshness": "current_run",
                "promotion_status": "run_local",
                "waypoint_id": "stale_prior_waypoint",
                "pose": {"x": 999.0, "y": 999.0, "yaw": 0.0},
            }
        ]
    }

    contract = _contract(
        HouseholdBackendSession(build_cleanup_scenario(seed=7)),
        runtime_map_prior=prior_snapshot,
    )
    _first_non_empty_observation(contract)
    runtime_map = contract.agent_view_payload()["runtime_metric_map"]
    stale_matches = [
        item
        for item in runtime_map["public_semantic_anchors"]
        if item["anchor_id"] == seed_anchor["anchor_id"]
    ]
    current_matches = [
        item
        for item in runtime_map["public_semantic_anchors"]
        if item["category"] == seed_anchor["category"] and item["freshness"] == "current_run"
    ]

    assert stale_matches == []
    assert current_matches
    assert all(item["waypoint_id"] != "stale_prior_waypoint" for item in current_matches)
    assert all(item["pose"] != {"x": 999.0, "y": 999.0, "yaw": 0.0} for item in current_matches)
    assert all(item["promotion_status"] == "run_local" for item in current_matches)
    _assert_no_forbidden_keys(runtime_map)


def test_runtime_map_prior_anchor_keeps_snapshot_waypoint_without_current_evidence() -> None:
    prior_anchor_id = "anchor_fixture_099"
    prior_snapshot = {
        "public_semantic_anchors": [
            {
                "anchor_id": prior_anchor_id,
                "anchor_type": "receptacle",
                "category": "Fridge",
                "label": "Fridge",
                "room_id": "room_8",
                "waypoint_id": "room_8_inspection",
                "pose": {"x": 10.7, "y": 3.2, "yaw": 0.0},
                "pose_source": "inspection_waypoint",
                "pose_role": "best_view_pose",
                "localization_status": "viewpoint_only",
                "affordances": ["observe", "place", "open", "place_inside", "close"],
                "producer_type": "visible_detection",
                "producer_id": "visible_detection",
                "confidence": 0.68,
                "freshness": "current_run",
                "actionability": "actionable",
                "source_observation_id": "waypoint_observation:room_8_inspection",
                "promotion_status": "run_local",
                "evidence": {
                    "type": "support_estimate",
                    "supporting_observed_object_ids": [],
                },
            }
        ]
    }

    contract = _contract(
        HouseholdBackendSession(build_cleanup_scenario(seed=7)),
        runtime_map_prior=prior_snapshot,
    )
    runtime_map = contract.agent_view_payload()["runtime_metric_map"]
    matching = [
        item
        for item in runtime_map["public_semantic_anchors"]
        if item["anchor_id"] == prior_anchor_id
    ]
    resolution = contract.resolve_target_query("Fridge")

    assert len(matching) == 1
    anchor = matching[0]
    assert anchor["freshness"] == "prior"
    assert anchor["promotion_status"] == "prior_runtime_snapshot"
    assert anchor["waypoint_id"] == "room_8_inspection"
    assert anchor["room_id"] == "room_8"
    assert anchor["pose"] == {"x": 10.7, "y": 3.2, "yaw": 0.0}
    assert resolution["best_match"]["anchor_id"] == prior_anchor_id
    assert resolution["best_match"]["waypoint_id"] == "room_8_inspection"

    contract.navigate_to_waypoint("room_2_inspection")
    contract.observe()
    post_observe_map = contract.agent_view_payload()["runtime_metric_map"]
    post_observe_anchor = next(
        item
        for item in post_observe_map["public_semantic_anchors"]
        if item["anchor_id"] == prior_anchor_id
    )
    post_observe_resolution = contract.resolve_target_query("Fridge")

    assert post_observe_anchor["freshness"] == "prior"
    assert post_observe_anchor["waypoint_id"] == "room_8_inspection"
    fresh_fridge_anchors = [
        item
        for item in post_observe_map["public_semantic_anchors"]
        if str(item.get("label") or item.get("category") or "").lower() == "fridge"
        and item["freshness"] == "current_run"
    ]
    assert fresh_fridge_anchors
    assert all(item["anchor_id"] != prior_anchor_id for item in fresh_fridge_anchors)
    assert post_observe_resolution["best_match"]["anchor_id"] in {
        prior_anchor_id,
        *(item["anchor_id"] for item in fresh_fridge_anchors),
    }
    _assert_no_forbidden_keys(runtime_map)
    _assert_no_forbidden_keys(post_observe_map)


def test_base_metric_map_keeps_public_waypoint_after_receptacle_navigation() -> None:
    contract = _contract(
        HouseholdBackendSession(build_cleanup_scenario(seed=7)),
    )

    observation = _first_non_empty_observation(contract)
    detection = _confirm_world_label_detection(
        contract,
        observation["visible_object_detections"][0],
    )
    fixture = _public_destination_fixture_for_detection(contract, detection)
    fixture_id = str(fixture["fixture_id"])

    assert contract.navigate_to_object(detection["object_id"])["ok"] is True
    assert contract.pick(detection["object_id"])["ok"] is True
    navigation = contract.navigate_to_receptacle(fixture_id)
    post_nav_map = contract.metric_map()

    assert navigation["ok"] is True
    assert str(post_nav_map["robot_pose"]["waypoint_id"]).startswith("room_")
    assert post_nav_map["robot_pose"]["room_id"]
    assert post_nav_map["robot_pose"]["room_id"] != "generated_area"
    assert post_nav_map["robot_pose"]["waypoint_id"] in {
        str(item["waypoint_id"]) for item in post_nav_map["inspection_waypoints"]
    }


def test_base_metric_map_observe_marks_placed_object_non_actionable() -> None:
    contract = _contract(
        HouseholdBackendSession(build_cleanup_scenario(seed=7)),
    )

    observation = _first_non_empty_observation(contract)
    detection = _confirm_world_label_detection(
        contract,
        observation["visible_object_detections"][0],
    )
    fixture = _public_destination_fixture_for_detection(contract, detection)
    fixture_id = str(fixture["fixture_id"])

    assert contract.navigate_to_object(detection["object_id"])["ok"] is True
    assert contract.pick(detection["object_id"])["ok"] is True
    assert contract.navigate_to_receptacle(fixture_id)["ok"] is True
    if detection.get("recommended_tool") == "place_inside":
        opened = contract.open_receptacle(fixture_id)
        if opened["ok"]:
            assert contract.place_inside(fixture_id)["ok"] is True
            closed = contract.close_receptacle(fixture_id)
            if closed["ok"]:
                expected_state = "placed_closed"
            else:
                expected_state = "placed"
        else:
            assert contract.place_inside(fixture_id)["ok"] is True
            expected_state = "placed"
    else:
        assert contract.place(fixture_id)["ok"] is True
        expected_state = "placed"

    later = contract.observe()
    later_detection = next(
        item
        for item in later["visible_object_detections"]
        if item["object_id"] == detection["object_id"]
    )
    worklist_item = next(
        item
        for item in contract.cleanup_worklist_payload()["objects"]
        if item["object_id"] == detection["object_id"]
    )
    duplicate_nav = contract.navigate_to_object(detection["object_id"])
    duplicate_pick = contract.pick(detection["object_id"])

    assert later_detection["actionability_status"] in {"already_handled", "needs_visual_evidence"}
    assert worklist_item["state"] == expected_state
    assert "cleanup_recommended" not in worklist_item
    assert duplicate_nav["ok"] is False
    assert duplicate_nav["error_reason"] == "already_handled"
    assert duplicate_pick["ok"] is False
    assert duplicate_pick["error_reason"] == "already_handled"


def test_base_metric_map_done_uses_generated_candidate_coverage() -> None:
    contract = _contract(
        HouseholdBackendSession(
            CleanupScenario(
                scenario_id="base-metric-map-done-gate-test",
                task="build base navigation map",
                seed=7,
                objects=(),
                receptacles=(
                    CleanupReceptacle("sink_01", "Sink", "kitchen", category="Sink"),
                    CleanupReceptacle("desk_01", "Desk", "office", category="Desk"),
                ),
                private_manifest=PrivateScoringManifest(
                    scenario_id="base-metric-map-done-gate-test",
                    targets=(),
                    success_threshold=0,
                ),
            )
        ),
    )

    waypoints = contract.metric_map()["inspection_waypoints"]
    for waypoint in waypoints[:-1]:
        contract.navigate_to_waypoint(str(waypoint["waypoint_id"]))
        contract.observe()

    early_done = contract.done("almost finished minimal sweep")

    assert early_done["ok"] is False
    assert early_done["error_reason"] == "insufficient_sweep_coverage"
    assert early_done["next_waypoint_id"] == waypoints[-1]["waypoint_id"]
    assert early_done["observed_waypoint_count"] == len(waypoints) - 1
    assert early_done["total_waypoints"] == len(waypoints)
    assert all(item.endswith("_inspection") for item in early_done["unvisited_waypoint_ids"])

    contract.navigate_to_waypoint(str(waypoints[-1]["waypoint_id"]))
    contract.observe()
    done = contract.done("finished minimal sweep")

    assert done["ok"] is True


def test_minimal_raw_fpv_waypoint_navigation_moves_backend_before_capture(
    tmp_path: Path,
) -> None:
    scenario = build_cleanup_scenario(seed=7)
    backend = _PoseRecordingBackend(scenario)
    contract = HouseholdRuntimeContract(
        HouseholdBackendSession(scenario, backend=backend),
        perception_mode=RAW_FPV_ONLY_MODE,
        map_bundle_dir=PREBUILT_BUNDLE,
    )
    waypoints = contract.metric_map()["inspection_waypoints"]
    first_waypoint = waypoints[0]
    second_waypoint = waypoints[1]

    first_nav = contract.navigate_to_waypoint(str(first_waypoint["waypoint_id"]))
    first_observation = contract.observe()
    first_raw = first_observation["raw_fpv_observation"]
    first_views = backend.write_robot_views(
        tmp_path,
        label=str(first_raw["observation_id"]),
    )["views"]
    first_artifact = contract.attach_raw_fpv_observation_artifact(
        first_raw["observation_id"],
        views=first_views,
    )

    second_nav = contract.navigate_to_waypoint(str(second_waypoint["waypoint_id"]))
    second_observation = contract.observe()
    second_raw = second_observation["raw_fpv_observation"]
    second_views = backend.write_robot_views(
        tmp_path,
        label=str(second_raw["observation_id"]),
    )["views"]
    second_artifact = contract.attach_raw_fpv_observation_artifact(
        second_raw["observation_id"],
        views=second_views,
    )

    assert first_nav["waypoint_id"] == first_waypoint["waypoint_id"]
    assert second_nav["waypoint_id"] == second_waypoint["waypoint_id"]
    assert backend.navigation_targets == []
    assert first_nav["backend_goal_pose"]["waypoint_id"] == first_waypoint["waypoint_id"]
    assert second_nav["backend_goal_pose"]["waypoint_id"] == second_waypoint["waypoint_id"]
    assert backend.view_poses[0] == {"receptacle_id": "unknown"}
    assert backend.view_poses[1] == {"receptacle_id": "unknown"}
    assert first_artifact is not None
    assert second_artifact is not None
    assert first_artifact["image_artifacts"]["fpv"] != second_artifact["image_artifacts"]["fpv"]
    assert first_views["verify"] != second_views["verify"]
    assert first_views["topdown"] != second_views["topdown"]
    assert str(first_raw["observation_id"]) in first_artifact["image_artifacts"]["fpv"]
    assert str(second_raw["observation_id"]) in second_artifact["image_artifacts"]["fpv"]


def test_realworld_done_rejects_one_missing_public_waypoint() -> None:
    contract = _contract(
        HouseholdBackendSession(
            CleanupScenario(
                scenario_id="missing-waypoint-gate-test",
                task="check full public sweep",
                seed=7,
                objects=(),
                receptacles=(
                    CleanupReceptacle("sink_01", "Sink", "kitchen", category="Sink"),
                    CleanupReceptacle("desk_01", "Desk", "office", category="Desk"),
                ),
                private_manifest=PrivateScoringManifest(
                    scenario_id="missing-waypoint-gate-test",
                    targets=(),
                    success_threshold=0,
                ),
            )
        ),
    )

    waypoints = contract.metric_map()["inspection_waypoints"]
    for waypoint in waypoints[:-1]:
        contract.navigate_to_waypoint(str(waypoint["waypoint_id"]))
        contract.observe()

    early_done = contract.done("finished after almost all waypoints")

    assert early_done["ok"] is False
    assert early_done["status"] == "blocked"
    assert early_done["error_reason"] == "insufficient_sweep_coverage"
    assert early_done["required_tool"] == "navigate_to_waypoint"
    assert early_done["next_waypoint_id"] == waypoints[-1]["waypoint_id"]
    assert early_done["observed_waypoint_count"] == len(waypoints) - 1
    assert early_done["total_waypoints"] == len(waypoints)
    assert early_done["completion"]["blockers"][0]["type"] == "insufficient_sweep_coverage"
