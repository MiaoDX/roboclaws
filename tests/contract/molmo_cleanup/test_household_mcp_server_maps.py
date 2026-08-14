from __future__ import annotations

import json
from pathlib import Path

import pytest

from roboclaws.household import agent_view as agent_view_module
from roboclaws.household.household_runtime_contract import (
    CAMERA_MODEL_POLICY_MODE,
    REALWORLD_CONTRACT,
)
from roboclaws.household.scenario import build_cleanup_scenario
from tests.contract.molmo_cleanup.household_mcp_server_support import (
    PREBUILT_BUNDLE,
    _first_destination_option_from_done,
    make_household_world_mcp,
)


def test_realworld_mcp_surface_uses_metric_map_and_visible_handles(tmp_path: Path) -> None:
    server = make_household_world_mcp(
        run_dir=tmp_path,
        scenario=build_cleanup_scenario(seed=7),
        port=0,
        map_bundle_dir=PREBUILT_BUNDLE,
    )
    try:
        metric_map = server.call_tool("metric_map")
        observation = {}
        for waypoint in metric_map["inspection_waypoints"]:
            waypoint_id = waypoint["waypoint_id"]
            server.call_tool("navigate_to_waypoint", waypoint_id=waypoint_id)
            observation = server.call_tool("observe")
            if observation["visible_object_detections"]:
                break
        with pytest.raises(ValueError, match="scene_objects"):
            server.call_tool("scene_objects")
    finally:
        server.close()

    assert metric_map["contract"] == REALWORLD_CONTRACT
    assert metric_map["schema"] == "real_robot_map_bundle_v1"
    assert metric_map["map_bundle"]["environment_id"] == "molmospaces-procthor-10k-val-0"
    assert "1-based sweep_index=N" in metric_map["instruction"]
    assert "objects" not in metric_map
    assert observation["visible_object_detections"]
    assert observation["visible_object_detections"][0]["object_id"].startswith("observed_")
    assert "target_receptacle_id" not in json.dumps(observation)
    assert "close_receptacle" in server.contract.public_tool_names()


def test_realworld_mcp_can_seed_runtime_metric_map_priors(tmp_path: Path) -> None:
    prior_server = make_household_world_mcp(
        run_dir=tmp_path / "prior",
        scenario=build_cleanup_scenario(seed=7),
        port=0,
        perception_mode=CAMERA_MODEL_POLICY_MODE,
    )
    try:
        metric_map = prior_server.call_tool("metric_map")
        for waypoint in metric_map["inspection_waypoints"]:
            prior_server.call_tool("navigate_to_waypoint", waypoint_id=waypoint["waypoint_id"])
            observation = prior_server.call_tool("observe")
            declared = prior_server.call_tool(
                "declare_visual_candidates",
                observation_id=observation["raw_fpv_observation"]["observation_id"],
            )
            if declared["model_declared_observations"]:
                break
        prior_snapshot = agent_view_module.runtime_metric_map(prior_server._agent_view_payload())
    finally:
        prior_server.close()

    server = make_household_world_mcp(
        run_dir=tmp_path / "consumer",
        scenario=build_cleanup_scenario(seed=7),
        port=0,
        perception_mode=CAMERA_MODEL_POLICY_MODE,
        runtime_map_prior=prior_snapshot,
        runtime_map_prior_source="prior/runtime_metric_map.json",
    )
    try:
        runtime_map = agent_view_module.runtime_metric_map(server._agent_view_payload())
        prior_rows = [
            item for item in runtime_map["observed_objects"] if item["freshness"] == "prior"
        ]
        metric_map = server.call_tool("metric_map")
        for waypoint in metric_map["inspection_waypoints"]:
            server.call_tool("navigate_to_waypoint", waypoint_id=waypoint["waypoint_id"])
            server.call_tool("observe")
        done = server.call_tool("done", reason="prior seeded smoke")
        run_result = json.loads(Path(done["run_result"]).read_text(encoding="utf-8"))
    finally:
        server.close()

    assert prior_rows
    assert all(item["actionability"] == "needs_confirm" for item in prior_rows)
    prior_summary = run_result["runtime_metric_map_prior"]
    assert prior_summary["loaded"] is True
    assert prior_summary["source_provided"] is True
    assert prior_summary["source"] == "prior/runtime_metric_map.json"
    assert prior_summary["observed_object_count"] == len(prior_rows)
    assert prior_summary["object_prior_count"] == len(prior_rows)
    assert prior_summary["anchor_prior_count"] >= 1


def test_realworld_mcp_reports_anchor_only_runtime_map_prior_as_loaded(tmp_path: Path) -> None:
    runtime_map_prior = {
        "schema": "runtime_metric_map_v1",
        "public_semantic_anchors": [
            {
                "anchor_id": "anchor_room_room_2",
                "anchor_type": "room_area",
                "category": "kitchen",
                "label": "Kitchen",
                "room_id": "room_2",
                "waypoint_id": "room_2_inspection",
                "pose": {"x": 6.4, "y": 7.5, "yaw": 0.0},
                "affordances": ["navigate", "observe"],
                "producer_type": "map-build",
                "producer_id": "map-build",
                "confidence": 0.8,
                "actionability": "actionable",
            }
        ],
        "observed_objects": [],
        "rooms": [],
        "private_truth_included": False,
        "source_map_mutated": False,
    }
    server = make_household_world_mcp(
        run_dir=tmp_path,
        scenario=build_cleanup_scenario(seed=7),
        port=0,
        perception_mode=CAMERA_MODEL_POLICY_MODE,
        runtime_map_prior=runtime_map_prior,
        runtime_map_prior_source="prior/runtime_metric_map.json",
    )
    try:
        metric_map = server.call_tool("metric_map")
        for waypoint in metric_map["inspection_waypoints"]:
            server.call_tool("navigate_to_waypoint", waypoint_id=waypoint["waypoint_id"])
            server.call_tool("observe")
        done = server.call_tool("done", reason="anchor-only prior smoke")
        run_result = json.loads(Path(done["run_result"]).read_text(encoding="utf-8"))
    finally:
        server.close()

    assert run_result["runtime_metric_map_prior"] == {
        "anchor_prior_count": 1,
        "loaded": True,
        "object_prior_count": 0,
        "room_prior_count": 0,
        "source": "prior/runtime_metric_map.json",
        "source_provided": True,
        "observed_object_count": 0,
    }


def test_realworld_mcp_prior_summary_uses_normalized_construction_snapshot(tmp_path: Path) -> None:
    runtime_map_prior = {
        "schema": "runtime_metric_map_v1",
        "public_semantic_anchors": [
            {"anchor_id": "anchor_1", "anchor_type": "room_area"},
            None,
        ],
        "observed_objects": [],
        "rooms": [{"room_id": "room_1"}, None],
    }
    server = make_household_world_mcp(
        run_dir=tmp_path,
        scenario=build_cleanup_scenario(seed=7),
        port=0,
        perception_mode=CAMERA_MODEL_POLICY_MODE,
        runtime_map_prior=runtime_map_prior,
        runtime_map_prior_source="prior/runtime_metric_map.json",
    )
    runtime_map_prior["public_semantic_anchors"].append({"anchor_id": "late_anchor"})
    runtime_map_prior["rooms"].append({"room_id": "late_room"})
    try:
        metric_map = server.call_tool("metric_map")
        for waypoint in metric_map["inspection_waypoints"]:
            server.call_tool("navigate_to_waypoint", waypoint_id=waypoint["waypoint_id"])
            server.call_tool("observe")
        done = server.call_tool("done", reason="normalized prior summary")
        run_result = json.loads(Path(done["run_result"]).read_text(encoding="utf-8"))
    finally:
        server.close()

    assert run_result["runtime_metric_map_prior"]["anchor_prior_count"] == 1
    assert run_result["runtime_metric_map_prior"]["room_prior_count"] == 1


def test_realworld_mcp_defaults_to_base_metric_map(tmp_path: Path) -> None:
    server = make_household_world_mcp(
        run_dir=tmp_path,
        scenario=build_cleanup_scenario(seed=7),
        port=0,
    )
    try:
        metric_map = server.call_tool("metric_map")
        runtime_map = agent_view_module.runtime_metric_map(server._agent_view_payload())
        for waypoint in metric_map["inspection_waypoints"]:
            server.call_tool("navigate_to_waypoint", waypoint_id=waypoint["waypoint_id"])
            server.call_tool("observe")
        agent_view = server._agent_view_payload()
    finally:
        server.close()

    assert metric_map["base_metric_map"]["enabled"] is True
    assert metric_map["rooms"]
    assert all(room["room_label"] for room in metric_map["rooms"])
    assert metric_map["room_category_hints"]
    assert metric_map["driveable_ways"]
    assert runtime_map["static_map"]["fixtures"] == []
    assert agent_view_module.cleanup_worklist(agent_view)["objects"]


def test_realworld_mcp_base_metric_map_exposes_actionable_runtime_anchors(
    tmp_path: Path,
) -> None:
    server = make_household_world_mcp(
        run_dir=tmp_path,
        scenario=build_cleanup_scenario(seed=7),
        port=0,
    )
    try:
        metric_map = server.call_tool("metric_map")
        observed = None
        for waypoint in metric_map["inspection_waypoints"]:
            server.call_tool("navigate_to_waypoint", waypoint_id=waypoint["waypoint_id"])
            observation = server.call_tool("observe")
            if observation["visible_object_detections"]:
                observed = observation["visible_object_detections"][0]
        assert observed is not None

        agent_view = server._agent_view_payload()
        assert any(
            item["object_id"] == observed["object_id"]
            for item in agent_view_module.cleanup_worklist(agent_view)["objects"]
        )
        target_anchor_id = _first_destination_option_from_done(server, str(observed["object_id"]))[
            "candidate_fixture_id"
        ]
        server.call_tool("navigate_to_object", object_id=observed["object_id"])
        server.call_tool("pick", object_id=observed["object_id"])
        navigation = server.call_tool("navigate_to_receptacle", fixture_id=target_anchor_id)
    finally:
        server.close()

    assert target_anchor_id.startswith("anchor_fixture_")
    assert navigation["fixture_id"] == target_anchor_id


def test_realworld_mcp_resolves_stale_target_query_to_public_anchor(
    tmp_path: Path,
) -> None:
    server = make_household_world_mcp(
        run_dir=tmp_path,
        scenario=build_cleanup_scenario(seed=7),
        port=0,
    )
    try:
        metric_map = server.call_tool("metric_map")
        for waypoint in metric_map["inspection_waypoints"]:
            server.call_tool("navigate_to_waypoint", waypoint_id=waypoint["waypoint_id"])
            server.call_tool("observe")
        resolution = server.call_tool(
            "resolve_target_query",
            query="sink_01",
            operation="destination",
        )
    finally:
        server.close()

    assert resolution["ok"] is True
    assert resolution["schema"] == "target_query_resolution_v1"
    assert resolution["status"] == "matched"
    assert resolution["best_match"]["anchor_id"].startswith("anchor_fixture_")
    assert "sink" in resolution["best_match"]["category"].lower()
    assert resolution["best_match"]["private_truth_included"] is False
    assert "target_receptacle_id" not in json.dumps(resolution)
