from __future__ import annotations

from types import SimpleNamespace

from roboclaws.household import agent_view as agent_view_module
from roboclaws.household import (
    realworld_runtime_map_targets,
)
from roboclaws.household.household_backend_contract import HouseholdBackendSession
from roboclaws.household.household_runtime_contract import (
    CAMERA_MODEL_POLICY_MODE,
    RUNTIME_METRIC_MAP_SCHEMA,
    SANITIZED_VISIBLE_OBJECT_DETECTIONS_PROVENANCE,
    SIMULATED_CAMERA_MODEL_PROVENANCE,
)
from roboclaws.household.scenario import build_cleanup_scenario
from roboclaws.household.target_query import resolve_target_query
from tests.contract.molmo_cleanup.household_runtime_contract_support import (
    _assert_no_forbidden_keys,
    _contract,
    _empty_cleanup_scenario,
    _observe_all_public_waypoints,
)


def test_runtime_metric_map_keeps_static_and_dynamic_semantics_separate() -> None:
    contract = _contract(
        HouseholdBackendSession(build_cleanup_scenario(seed=7)),
        perception_mode=CAMERA_MODEL_POLICY_MODE,
    )

    observation = {}
    declared = {}
    for waypoint in contract.metric_map()["inspection_waypoints"]:
        contract.navigate_to_waypoint(str(waypoint["waypoint_id"]))
        observation = contract.observe()
        declared = contract.declare_visual_candidates(
            observation["raw_fpv_observation"]["observation_id"]
        )
        if declared["model_declared_observations"]:
            break
    agent_view = contract.agent_view_payload()
    runtime_map = agent_view_module.runtime_metric_map(agent_view)

    assert declared["ok"] is True
    assert runtime_map["schema"] == RUNTIME_METRIC_MAP_SCHEMA
    assert runtime_map["private_truth_included"] is False
    assert runtime_map["source_map_mutated"] is False
    assert runtime_map["static_map"]["fixtures"] == []
    assert runtime_map["public_semantic_anchors"]
    assert runtime_map["map_update_candidates"] == []
    assert runtime_map["observed_objects"]
    observed = runtime_map["observed_objects"][0]
    assert observed["object_id"].startswith("observed_")
    assert observed["source_observation_id"] == observation["raw_fpv_observation"]["observation_id"]
    assert observed["producer_type"] == SIMULATED_CAMERA_MODEL_PROVENANCE
    assert observed["actionability"] in {"actionable", "pending"}
    _assert_no_forbidden_keys(runtime_map)


def test_runtime_metric_map_promotes_only_observed_fixture_viewpoints() -> None:
    contract = _contract(
        HouseholdBackendSession(_empty_cleanup_scenario("map-build-empty-observation-test")),
        evidence_lane="world-public-labels",
    )

    for waypoint in contract.metric_map()["inspection_waypoints"]:
        contract.navigate_to_waypoint(str(waypoint["waypoint_id"]))
        observation = contract.observe()
        assert observation["visible_object_detections"] == []

    runtime_map = agent_view_module.runtime_metric_map(contract.agent_view_payload())
    fixture_anchors = [
        item
        for item in runtime_map["public_semantic_anchors"]
        if item.get("anchor_type") in {"fixture", "surface", "receptacle"}
    ]

    assert runtime_map["observed_objects"] == []
    assert fixture_anchors
    assert all(anchor["source_observation_id"] for anchor in fixture_anchors)
    assert all(
        anchor["waypoint_id"] in contract._observed_waypoint_ids for anchor in fixture_anchors
    )
    assert all(
        anchor["producer_type"] == SANITIZED_VISIBLE_OBJECT_DETECTIONS_PROVENANCE
        for anchor in fixture_anchors
    )
    assert all("object_pose" not in anchor for anchor in fixture_anchors)
    _assert_no_forbidden_keys(runtime_map)


def test_runtime_metric_map_snapshot_priors_require_current_confirmation() -> None:
    sweep_contract = _contract(
        HouseholdBackendSession(build_cleanup_scenario(seed=7)),
        perception_mode=CAMERA_MODEL_POLICY_MODE,
    )
    for waypoint in sweep_contract.metric_map()["inspection_waypoints"]:
        sweep_contract.navigate_to_waypoint(str(waypoint["waypoint_id"]))
        observation = sweep_contract.observe()
        declared = sweep_contract.declare_visual_candidates(
            observation["raw_fpv_observation"]["observation_id"]
        )
        if declared["model_declared_observations"]:
            break
    prior_snapshot = sweep_contract.agent_view_payload()["runtime_metric_map"]

    contract = _contract(
        HouseholdBackendSession(build_cleanup_scenario(seed=7)),
        perception_mode=CAMERA_MODEL_POLICY_MODE,
        runtime_map_prior=prior_snapshot,
    )
    prior_only_map = contract.agent_view_payload()["runtime_metric_map"]

    prior_rows = [
        item for item in prior_only_map["observed_objects"] if item["freshness"] == "prior"
    ]
    assert prior_rows
    assert all(item["actionability"] == "needs_confirm" for item in prior_rows)
    assert agent_view_module.observed_objects(contract.agent_view_payload()) == []

    for waypoint in contract.metric_map()["inspection_waypoints"]:
        contract.navigate_to_waypoint(str(waypoint["waypoint_id"]))
        observation = contract.observe()
        declared = contract.declare_visual_candidates(
            observation["raw_fpv_observation"]["observation_id"]
        )
        if declared["model_declared_observations"]:
            break

    runtime_map = contract.agent_view_payload()["runtime_metric_map"]
    current_rows = [
        item for item in runtime_map["observed_objects"] if item["freshness"] == "current_run"
    ]
    assert current_rows
    assert current_rows[0]["prior_object_id"] == prior_rows[0]["prior_object_id"]
    assert current_rows[0]["snapshot_object_id"] == prior_rows[0]["snapshot_object_id"]
    _assert_no_forbidden_keys(runtime_map)


def test_b1_runtime_prior_capabilities_are_agent_visible_through_mcp_flow() -> None:
    prior_snapshot = {
        "schema": "runtime_map_prior_snapshot_v1",
        "runtime_metric_map": {
            "schema": RUNTIME_METRIC_MAP_SCHEMA,
            "rooms": [],
            "public_semantic_anchors": [],
            "observed_objects": [],
            "digital_twin_capabilities": {
                "robot_consumption_proof": {
                    "status": "robot_navigation_verified",
                    "robot_navigation_supported": True,
                    "planner_backed": False,
                    "physical_robot": False,
                    "manipulation_supported": False,
                    "object_receptacle_usd_binding_status": "blocked_out_of_scope",
                },
                "render_observation_proof": {
                    "status": "same_pose_render_observation_verified",
                    "render_observation_supported": True,
                    "same_pose_fpv_supported": True,
                    "same_pose_chase_supported": True,
                    "same_pose_topdown_supported": True,
                    "default_visual_route": {
                        "scene_id": "B1_floor2_slow",
                        "scene_root": "data/robot-data-lab/scene-engine/data/B1_floor2_slow",
                        "selected": False,
                        "status": "blocked_missing_verified_b1_floor2_slow_render_proof",
                    },
                },
                "room_semantic_projection_proof": {
                    "status": "blocked_missing_accepted_semantic_anchors",
                    "room_semantics_supported": False,
                    "object_semantics_supported": False,
                    "object_projection_status": "blocked_until_object_semantic_anchors",
                },
            },
        },
    }
    raw_prior = prior_snapshot["runtime_metric_map"]
    contract = _contract(
        HouseholdBackendSession(build_cleanup_scenario(seed=7)),
        runtime_map_prior=raw_prior,
    )

    metric_map = contract.metric_map()
    waypoint = metric_map["inspection_waypoints"][0]
    navigation = contract.navigate_to_waypoint(str(waypoint["waypoint_id"]))
    observation = contract.observe()
    runtime_map = contract.agent_view_payload()["runtime_metric_map"]
    capabilities = runtime_map["digital_twin_capabilities"]
    summary = runtime_map["capability_summary"]

    assert navigation["ok"] is True
    assert observation["ok"] is True
    assert capabilities["robot_consumption_proof"]["robot_navigation_supported"] is True
    assert summary["robot_navigation_supported"] is True
    assert summary["render_observation_supported"] is True
    assert summary["same_pose_fpv_supported"] is True
    assert summary["same_pose_chase_supported"] is True
    assert summary["same_pose_topdown_supported"] is True
    assert summary["default_visual_route_status"] == (
        "blocked_missing_verified_b1_floor2_slow_render_proof"
    )
    assert summary["default_visual_route_selected"] is False
    assert summary["room_semantics_supported"] is False
    assert summary["object_semantics_supported"] is False
    assert summary["object_projection_status"] == "blocked_until_object_semantic_anchors"
    assert summary["manipulation_supported"] is False
    assert summary["planner_backed_navigation_supported"] is False
    assert summary["physical_robot_supported"] is False
    assert "rooms" in runtime_map
    assert not any(
        anchor.get("anchor_role") == "semantic"
        for anchor in runtime_map.get("public_semantic_anchors") or []
    )
    _assert_no_forbidden_keys(runtime_map)


def test_public_fixture_anchor_allocator_skips_prior_anchor_id_collisions() -> None:
    anchor_mapping = {
        **{f"fixture_{index:03d}": f"anchor_fixture_{index:03d}" for index in range(1, 10)},
        "shelf_01": "anchor_fixture_011",
    }
    contract = SimpleNamespace(
        _runtime_map_anchor_priors=[
            {"anchor_id": f"anchor_fixture_{index:03d}"} for index in range(1, 17)
        ],
        _public_anchor_ids_by_private_fixture_id=anchor_mapping,
    )

    anchor_id = realworld_runtime_map_targets.public_anchor_id_for_fixture(
        contract,
        "bed_01",
    )

    public_ids = list(anchor_mapping.values())
    assert anchor_id == "anchor_fixture_017"
    assert len(public_ids) == len(set(public_ids))


def test_target_query_recovery_resolves_stale_fixture_id_through_public_anchor() -> None:
    contract = _contract(
        HouseholdBackendSession(build_cleanup_scenario(seed=7)),
    )
    _observe_all_public_waypoints(contract)

    runtime_map = contract.agent_view_payload()["runtime_metric_map"]
    direct = resolve_target_query(runtime_map, "sink_01", operation="destination")
    room_query = resolve_target_query(runtime_map, "kitchen", operation="inspect")
    tool = contract.resolve_target_query("sink_01", operation="destination")

    assert direct["status"] == "matched"
    assert direct["best_match"]["anchor_id"].startswith("anchor_fixture_")
    assert "sink" in direct["best_match"]["category"].lower()
    assert direct["best_match"]["actionable_for_operation"] is True
    assert direct["best_match"]["required_next_tool"] in {
        "navigate_to_waypoint",
        "navigate_to_receptacle",
    }
    assert room_query["status"] == "matched"
    assert room_query["best_match"]["waypoint_id"]
    assert room_query["best_match"]["actionable_for_operation"] is True
    assert any("kitchen" in basis for basis in room_query["best_match"]["match_basis"])
    assert direct["public_search_budget"]["viewpoint_budget"]["unvisited_waypoint_count"] == 0
    assert tool["ok"] is True
    assert tool["schema"] == "target_query_resolution_v1"
    assert tool["best_match"]["anchor_id"] == direct["best_match"]["anchor_id"]
    _assert_no_forbidden_keys(tool)


def test_runtime_metric_map_clusters_same_view_fixture_anchors_and_keeps_view_pose_prior() -> None:
    contract = _contract(
        HouseholdBackendSession(build_cleanup_scenario(seed=7)),
        perception_mode=CAMERA_MODEL_POLICY_MODE,
    )

    for waypoint in contract.metric_map()["inspection_waypoints"]:
        contract.navigate_to_waypoint(str(waypoint["waypoint_id"]))
        observation = contract.observe()
        contract.declare_visual_candidates(observation["raw_fpv_observation"]["observation_id"])

    runtime_map = contract.agent_view_payload()["runtime_metric_map"]
    fixture_anchors = [
        item
        for item in runtime_map["public_semantic_anchors"]
        if item["anchor_type"] in {"fixture", "surface", "receptacle"}
    ]
    duplicate_keys: dict[tuple[str, str, str, tuple[float, float, float], str], list[str]] = {}
    for anchor in fixture_anchors:
        pose = anchor["pose"]
        key = (
            anchor["category"],
            anchor["room_id"],
            anchor["waypoint_id"],
            (pose["x"], pose["y"], pose["yaw"]),
            anchor["source_observation_id"],
        )
        duplicate_keys.setdefault(key, []).append(anchor["anchor_id"])
        assert anchor["pose_source"] == "inspection_waypoint"
        assert anchor["pose_role"] == "best_view_pose"
        assert anchor["localization_status"] == "viewpoint_only"
        assert "object_pose" not in anchor
    assert not {key: ids for key, ids in duplicate_keys.items() if len(set(ids)) > 1}

    observed_objects = runtime_map["observed_objects"]
    assert observed_objects
    assert any(
        str(item.get("candidate_fixture_id", "")).startswith("anchor_fixture_")
        for item in observed_objects
    )
    for observed in observed_objects:
        assert "object_pose" not in observed

    anchor_candidates = [
        item
        for item in runtime_map["target_candidates"]
        if item["candidate_type"] == "public_semantic_anchor"
        and item["anchor_type"] in {"fixture", "surface", "receptacle"}
    ]
    assert anchor_candidates
    assert any(item["verified_navigation"] is True for item in anchor_candidates)
    for candidate in anchor_candidates:
        assert candidate["pose_source"] == "inspection_waypoint"
        assert candidate["pose_role"] == "best_view_pose"
        assert candidate["localization_status"] == "viewpoint_only"
        assert candidate["waypoint_id"]
        assert "object_pose" not in candidate
    _assert_no_forbidden_keys(runtime_map)
