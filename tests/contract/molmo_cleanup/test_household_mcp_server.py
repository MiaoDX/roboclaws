from __future__ import annotations

import asyncio
import importlib.util
import json
import math
from pathlib import Path
from typing import Any

import pytest

from roboclaws.core.goals import normalize_goal_contract
from roboclaws.core.task_intents import TASK_INTENT_SPECS
from roboclaws.household import agent_view as agent_view_module
from roboclaws.household.backend import ApiSemanticCleanupBackend
from roboclaws.household.household_backend_contract import HouseholdBackendSession
from roboclaws.household.household_mcp_server import (
    ROBOT_VIEW_CAPTURE_POLICY_ACTION_TIMELINE,
)
from roboclaws.household.household_mcp_server import (
    make_household_world_mcp as _make_household_world_mcp,
)
from roboclaws.household.household_runtime_contract import (
    CAMERA_MODEL_POLICY_MODE,
    RAW_FPV_ONLY_MODE,
    REALWORLD_CONTRACT,
    HouseholdRuntimeContract,
)
from roboclaws.household.isaac_lab_backend import (
    ISAACLAB_ROBOT_VIEW_VARIANT,
    ISAACLAB_SUBPROCESS_BACKEND,
)
from roboclaws.household.profiles import WORLD_PUBLIC_LABELS_PROFILE
from roboclaws.household.realworld_mcp_atomic_tools import ATOMIC_CLEANUP_TOOL_NAMES
from roboclaws.household.realworld_mcp_semantic_tools import SEMANTIC_CLEANUP_TOOL_NAMES
from roboclaws.household.realworld_visual_candidate_declarations import (
    simulated_declaration_inputs_for_waypoint,
)
from roboclaws.household.scenario import build_cleanup_scenario
from roboclaws.household.types import (
    CleanupReceptacle,
    CleanupScenario,
    PrivateScoringManifest,
)
from roboclaws.launch.catalog import SURFACE_SPECS
from roboclaws.mcp.profiles import (
    HOUSEHOLD_EPISODE_PROFILE,
    HOUSEHOLD_MANIPULATION_PROFILE,
    HOUSEHOLD_WORLD_PROFILE,
    contract_profile,
)

REPO_ROOT = Path(__file__).resolve().parents[3]


def _open_ended_goal_contract(prompt: str):
    return normalize_goal_contract(
        surface=SURFACE_SPECS["household-world"],
        intent=TASK_INTENT_SPECS["open-ended"],
        raw_prompt=prompt,
        required_capabilities=TASK_INTENT_SPECS["open-ended"].required_capabilities,
    )


SMOKE_PATH = REPO_ROOT / "scripts" / "molmo_cleanup" / "run_molmo_realworld_agent_mcp_smoke.py"
PREBUILT_BUNDLE = REPO_ROOT / "assets" / "maps" / "molmospaces" / "procthor-10k-val" / "0"


def make_household_world_mcp(*args: Any, **kwargs: Any) -> Any:
    kwargs.setdefault("map_bundle_dir", PREBUILT_BUNDLE)
    kwargs.setdefault(
        "required_capability_profiles",
        (
            HOUSEHOLD_WORLD_PROFILE,
            HOUSEHOLD_MANIPULATION_PROFILE,
            HOUSEHOLD_EPISODE_PROFILE,
        ),
    )
    return _make_household_world_mcp(*args, **kwargs)


def _load_smoke_module():
    spec = importlib.util.spec_from_file_location("run_molmo_realworld_agent_mcp_smoke", SMOKE_PATH)
    assert spec is not None
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def _fastmcp_tool_names(server: Any) -> set[str]:
    return set(server._mcp._tool_manager._tools)


def _listed_fastmcp_tool_names(server: Any) -> set[str]:
    return {tool.name for tool in asyncio.run(server._mcp.list_tools())}


def _assert_run_evidence_lane(run_result: dict[str, Any], expected: str) -> None:
    assert run_result["evidence_lane"] == expected
    assert run_result["evidence_lane_metadata"]["evidence_lane"] == expected


def _first_destination_option_from_done(server: Any, object_id: str) -> dict[str, Any]:
    done = server.call_tool("done", reason="probe public destination options")
    pending = [
        dict(item)
        for blocker in (done.get("completion") or {}).get("blockers") or []
        if blocker.get("type") == "pending_cleanup_candidates"
        for item in blocker.get("pending_cleanup_candidates") or []
    ]
    item = next(item for item in pending if item.get("object_id") == object_id)
    options = item.get("destination_options") or []
    assert options, item
    return dict(options[0])


def test_realworld_mcp_registered_tools_match_profile_public_surface(tmp_path: Path) -> None:
    server = make_household_world_mcp(
        run_dir=tmp_path,
        scenario=build_cleanup_scenario(seed=7),
        port=0,
    )
    try:
        profiles = (
            contract_profile(HOUSEHOLD_WORLD_PROFILE),
            contract_profile(HOUSEHOLD_MANIPULATION_PROFILE),
            contract_profile(HOUSEHOLD_EPISODE_PROFILE),
        )
        public_tool_names = {name for profile in profiles for name in profile.public_tool_names()}

        assert _fastmcp_tool_names(server) == public_tool_names
        assert _listed_fastmcp_tool_names(server) == public_tool_names
        assert not any(profile.privileged_tool_names() for profile in profiles)
        assert "resolve_target_query" in public_tool_names
        agent_view = server._agent_view_payload()
        capabilities = agent_view_module.capabilities(agent_view)
        assert "resolve_target_query" in agent_view_module.public_tool_names(agent_view)
        assert capabilities["capability_profiles"] == [
            HOUSEHOLD_WORLD_PROFILE,
            HOUSEHOLD_MANIPULATION_PROFILE,
            HOUSEHOLD_EPISODE_PROFILE,
        ]
        assert set(capabilities["profile_public_tool_names"]) == public_tool_names
        descriptor_by_name = {
            item["name"]: item for item in capabilities["public_tool_descriptors"]
        }
        assert descriptor_by_name["resolve_target_query"]["source_profile_id"] == (
            HOUSEHOLD_WORLD_PROFILE
        )
        assert descriptor_by_name["pick"]["source_profile_id"] == HOUSEHOLD_MANIPULATION_PROFILE
    finally:
        server.close()


def test_agent_sdk_camera_grounded_composite_flag_cannot_expand_entitlement(
    tmp_path: Path,
) -> None:
    default_server = make_household_world_mcp(
        run_dir=tmp_path / "default",
        scenario=build_cleanup_scenario(seed=7),
        port=0,
        perception_mode=CAMERA_MODEL_POLICY_MODE,
    )
    try:
        assert "observe_camera_grounded_candidates" not in _fastmcp_tool_names(default_server)
        assert "observe_camera_grounded_candidates" not in agent_view_module.public_tool_names(
            default_server._agent_view_payload()
        )
        with pytest.raises(ValueError, match="not entitled"):
            default_server.call_tool("observe_camera_grounded_candidates")
    finally:
        default_server.close()

    server = make_household_world_mcp(
        run_dir=tmp_path / "opt-in",
        scenario=build_cleanup_scenario(seed=7),
        port=0,
        perception_mode=CAMERA_MODEL_POLICY_MODE,
        agent_sdk_camera_grounded_composite_tools=True,
    )
    try:
        assert "observe_camera_grounded_candidates" not in _fastmcp_tool_names(server)
        agent_view = server._agent_view_payload()
        capabilities = agent_view_module.capabilities(agent_view)
        assert "observe_camera_grounded_candidates" not in agent_view_module.public_tool_names(
            agent_view
        )
        assert capabilities["runtime_extra_public_tool_names"] == []
        with pytest.raises(ValueError, match="not entitled"):
            server.call_tool("observe_camera_grounded_candidates")
    finally:
        server.close()


def test_realworld_mcp_resolves_profiles_from_private_runner_environment(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv(
        "ROBOCLAWS_REQUIRED_CAPABILITY_PROFILES",
        "household_world,household_episode",
    )
    server = _make_household_world_mcp(
        run_dir=tmp_path,
        scenario=build_cleanup_scenario(seed=7),
        map_bundle_dir=PREBUILT_BUNDLE,
        task_intent="map-build",
        port=0,
    )
    try:
        assert server.required_capability_profiles == (
            HOUSEHOLD_WORLD_PROFILE,
            HOUSEHOLD_EPISODE_PROFILE,
        )
        assert _listed_fastmcp_tool_names(server).isdisjoint(ATOMIC_CLEANUP_TOOL_NAMES)
    finally:
        server.close()


@pytest.mark.parametrize("evidence_lane", ("world-public-labels", "camera-raw-fpv"))
def test_map_build_entitlement_excludes_all_manipulation_tools_independent_of_evidence_lane(
    tmp_path: Path,
    evidence_lane: str,
) -> None:
    server = make_household_world_mcp(
        run_dir=tmp_path / evidence_lane,
        scenario=build_cleanup_scenario(seed=7),
        port=0,
        task_intent="map-build",
        evidence_lane=evidence_lane,
        required_capability_profiles=(HOUSEHOLD_WORLD_PROFILE, HOUSEHOLD_EPISODE_PROFILE),
    )
    try:
        registered = _fastmcp_tool_names(server)
        assert registered.isdisjoint(ATOMIC_CLEANUP_TOOL_NAMES)
        assert _listed_fastmcp_tool_names(server) == registered
        assert set(agent_view_module.public_tool_names(server._agent_view_payload())) == registered
        for tool_name in ATOMIC_CLEANUP_TOOL_NAMES:
            with pytest.raises(ValueError, match="not entitled"):
                server.call_tool(tool_name)
    finally:
        server.close()


def test_realworld_mcp_tool_files_are_layered_by_capability(tmp_path: Path) -> None:
    semantic = set(SEMANTIC_CLEANUP_TOOL_NAMES)
    atomic = set(ATOMIC_CLEANUP_TOOL_NAMES)

    assert semantic
    assert atomic
    assert semantic.isdisjoint(atomic)

    server = make_household_world_mcp(
        run_dir=tmp_path,
        scenario=build_cleanup_scenario(seed=7),
        port=0,
        evidence_lane=WORLD_PUBLIC_LABELS_PROFILE,
    )
    try:
        assert _fastmcp_tool_names(server) == semantic | atomic | {
            "check_operator_messages",
            "done",
        }
    finally:
        server.close()


def test_realworld_mcp_relative_pose_tool_traces_request_and_response(tmp_path: Path) -> None:
    server = make_household_world_mcp(
        run_dir=tmp_path,
        scenario=build_cleanup_scenario(seed=7),
        port=0,
        evidence_lane=WORLD_PUBLIC_LABELS_PROFILE,
    )
    try:
        response = server.call_tool(
            "navigate_to_relative_pose",
            forward_m=0.25,
            lateral_m=0.0,
            yaw_delta_deg=15.0,
        )
    finally:
        server.close()

    assert response["tool"] == "navigate_to_relative_pose"
    assert response["requires_reobserve"] is True
    assert response["requested_delta"] == {
        "forward_m": 0.25,
        "lateral_m": 0.0,
        "yaw_delta_deg": 15.0,
    }
    trace_events = [
        json.loads(line)
        for line in (tmp_path / "trace.jsonl").read_text(encoding="utf-8").splitlines()
        if line
    ]
    assert any(
        event.get("event") == "request" and event.get("tool") == "navigate_to_relative_pose"
        for event in trace_events
    )
    assert any(
        event.get("event") == "response" and event.get("tool") == "navigate_to_relative_pose"
        for event in trace_events
    )


def test_realworld_mcp_done_surfaces_corrupt_trace_source(tmp_path: Path) -> None:
    server = make_household_world_mcp(
        run_dir=tmp_path,
        scenario=build_cleanup_scenario(seed=7),
        port=0,
        evidence_lane=WORLD_PUBLIC_LABELS_PROFILE,
    )
    try:
        with (tmp_path / "trace.jsonl").open("a", encoding="utf-8") as stream:
            stream.write("[]\n")

        response = server.call_tool("done", reason="source validation probe")
    finally:
        server.close()

    assert response["ok"] is False
    assert response["status"] == "error"
    assert response["error_reason"] == "exception"
    assert "Molmo real-world MCP trace source row must contain a JSON object" in response["error"]
    assert "trace.jsonl:" in response["error"]


def test_realworld_mcp_operator_messages_pending_hint_and_seen(tmp_path: Path) -> None:
    operator_messages = tmp_path / "operator_messages.jsonl"
    operator_messages.write_text(
        json.dumps(
            {
                "schema": "operator_console_message_v1",
                "message_id": "msg-1",
                "command_type": "steer",
                "run_id": "run-a",
                "body": "Observe the desk again",
                "status": "queued",
                "created_at": "2026-06-09T00:00:00Z",
            }
        )
        + "\n",
        encoding="utf-8",
    )
    server = make_household_world_mcp(
        run_dir=tmp_path / "attempt",
        scenario=build_cleanup_scenario(seed=7),
        port=0,
        operator_messages_path=operator_messages,
    )
    try:
        metric_map = server.call_tool("metric_map")
        seen = server.call_tool("check_operator_messages")
        empty = server.call_tool("metric_map")
    finally:
        server.close()

    assert metric_map["operator_message_pending"] is True
    assert metric_map["pending_operator_message_count"] == 1
    assert seen["messages"][0]["body"] == "Observe the desk again"
    assert seen["messages"][0]["status"] == "seen"
    assert "operator_message_pending" not in empty


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


def test_realworld_mcp_done_persists_facade_rerun_command(
    tmp_path: Path,
    monkeypatch,
) -> None:
    smoke = _load_smoke_module()
    prior = "output/household/household-world/map-build/anchor/seed-7/runtime_metric_map.json"
    command = (
        "just run::surface surface=household-world world=molmospaces/procthor-10k-val/0 "
        "backend=mujoco intent=cleanup agent_engine=openai-agents-sdk "
        "provider_profile=kimi-openai-chat evidence_lane=world-public-labels seed=7 "
        "scenario_setup=relocate-cleanup-related-objects relocation_count=5 "
        "robot_views=on "
        f"runtime_map_prior={prior} "
        f"output_dir={tmp_path}"
    )
    monkeypatch.setenv(
        "ROBOCLAWS_REPORT_RERUN_COMMAND",
        "just run::surface surface=household-world agent_engine=direct-runner "
        "intent=cleanup evidence_lane=world-public-labels seed=7",
    )
    server = make_household_world_mcp(
        run_dir=tmp_path,
        scenario=build_cleanup_scenario(seed=7),
        port=0,
        rerun_command=command,
        task_prompt="report rerun command smoke",
        goal_contract=_open_ended_goal_contract("report rerun command smoke"),
    )
    try:
        smoke._drive_public_sweep(server)
        server.call_tool("done", reason="rerun command smoke")
    finally:
        server.close()

    run_result = json.loads((tmp_path / "run_result.json").read_text(encoding="utf-8"))
    report = (tmp_path / "report.html").read_text(encoding="utf-8")
    assert run_result["rerun_command"] == command
    assert run_result["task_intent"] == "open-ended"
    assert "MolmoSpaces Cleanup Pilot" in report
    assert "household-cleanup direct world-public-labels" not in report


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


def test_realworld_mcp_rejects_removed_cleanup_composite(
    tmp_path: Path,
) -> None:
    server = make_household_world_mcp(
        run_dir=tmp_path,
        scenario=build_cleanup_scenario(seed=7),
        port=0,
        evidence_lane=WORLD_PUBLIC_LABELS_PROFILE,
    )
    try:
        removed_tool = "clean_observed_object"
        assert removed_tool not in _fastmcp_tool_names(server)
        assert removed_tool not in agent_view_module.public_tool_names(server._agent_view_payload())
        with pytest.raises(ValueError, match=removed_tool):
            server.call_tool(
                removed_tool,
                object_id="observed_001",
                fixture_id="sink_01",
            )
    finally:
        server.close()


def test_realworld_mcp_rejects_removed_static_fixture_projection_tool(
    tmp_path: Path,
) -> None:
    server = make_household_world_mcp(
        run_dir=tmp_path,
        scenario=build_cleanup_scenario(seed=7),
        port=0,
        evidence_lane=WORLD_PUBLIC_LABELS_PROFILE,
    )
    try:
        assert "static_fixture_projection" not in _fastmcp_tool_names(server)
        assert "static_fixture_projection" not in agent_view_module.public_tool_names(
            server._agent_view_payload()
        )
        with pytest.raises(ValueError, match="static_fixture_projection"):
            server.call_tool("static_fixture_projection")
    finally:
        server.close()


def test_realworld_mcp_rejects_skipped_semantic_pick_with_public_guidance(
    tmp_path: Path,
) -> None:
    server = make_household_world_mcp(
        run_dir=tmp_path,
        scenario=build_cleanup_scenario(seed=7),
        port=0,
    )
    try:
        metric_map = server.call_tool("metric_map")
        detection = None
        for waypoint in metric_map["inspection_waypoints"]:
            server.call_tool("navigate_to_waypoint", waypoint_id=waypoint["waypoint_id"])
            observation = server.call_tool("observe")
            detections = observation.get("visible_object_detections", [])
            if detections:
                detection = detections[0]
                break
        assert detection is not None

        skipped = server.call_tool("pick", object_id=detection["object_id"])
    finally:
        server.close()

    assert skipped["ok"] is False
    assert "fresh source FPV evidence with a reviewable bbox" in metric_map["instruction"]
    assert skipped["error_reason"] == "visual_evidence_not_reviewable"
    assert skipped["required_next_tool"] == "adjust_camera"
    assert skipped["candidate_state"] == "visual_scan_required"
    assert "generated_mess_set" not in json.dumps(skipped)
    assert "target_receptacle_id" not in json.dumps(skipped)


class _FakeVisualBackend(ApiSemanticCleanupBackend):
    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self.robot_view_camera_offsets: list[dict[str, float]] = []

    def write_robot_views(
        self,
        output_dir: Path,
        *,
        label: str,
        focus_object_id: str | None = None,
        focus_receptacle_id: str | None = None,
        camera_yaw_offset_deg: float = 0.0,
        camera_pitch_offset_deg: float = 0.0,
    ) -> dict[str, Any]:
        self.robot_view_camera_offsets.append(
            {
                "yaw_delta_deg": camera_yaw_offset_deg,
                "pitch_delta_deg": camera_pitch_offset_deg,
            }
        )
        output_dir.mkdir(parents=True, exist_ok=True)
        views = {}
        for key in ("fpv", "chase", "topdown", "verify"):
            path = output_dir / f"{label}_{key}.png"
            path.write_bytes(b"fake png")
            views[key] = str(path)
        has_focus = bool(focus_object_id or focus_receptacle_id)
        return {
            "ok": True,
            "robot_pose": {
                "x": 1.0,
                "y": 2.0,
                "theta": 0.0,
                "head_pitch": -0.25,
                "theta_source": "target_facing_base_yaw",
                "head_pitch_source": "target_framing_head_pitch",
                "same_room_as_target": True,
            },
            "robot_trajectory": [{"x": 1.0, "y": 2.0}],
            "view_variant": "molmospaces-rby1m-fpv-topdown-chase-verify",
            "view_provenance": "test_fake_visual_backend",
            "camera_control_contract": {
                "schema": "robot_view_camera_control_contract_v1",
                "status": "backend_local_robot_camera",
                "camera_model": "backend_local_robot_view",
                "same_pose_api": False,
                "agent_facing_fpv": {
                    "source": "test_fake_fpv",
                    "canonical_camera_control": False,
                },
            },
            "focus": {
                "has_focus": has_focus,
                "object_id": focus_object_id,
                "receptacle_id": focus_receptacle_id,
                "provenance": "public_mujoco_state_report_aid" if has_focus else None,
                "fpv_visibility": {
                    "status": "ok",
                    "boxes": [{"label": focus_object_id or focus_receptacle_id}],
                    "object_pixels": 300,
                    "receptacle_pixels": 120,
                },
                "visibility": {
                    "status": "ok",
                    "boxes": [{"label": focus_object_id or focus_receptacle_id}],
                    "object_pixels": 150,
                    "receptacle_pixels": 120,
                },
            },
            "room_outline_count": 1,
            "views": views,
        }


class MolmoSpacesSubprocessBackend(_FakeVisualBackend):
    backend = "molmospaces_subprocess"
    requested_generated_mess_count = 5


class IsaacLabSubprocessBackend(_FakeVisualBackend):
    backend = ISAACLAB_SUBPROCESS_BACKEND
    requested_generated_mess_count = 5

    def write_robot_views(
        self,
        output_dir: Path,
        *,
        label: str,
        focus_object_id: str | None = None,
        focus_receptacle_id: str | None = None,
        camera_yaw_offset_deg: float = 0.0,
        camera_pitch_offset_deg: float = 0.0,
    ) -> dict[str, Any]:
        capture = super().write_robot_views(
            output_dir,
            label=label,
            focus_object_id=focus_object_id,
            focus_receptacle_id=focus_receptacle_id,
            camera_yaw_offset_deg=camera_yaw_offset_deg,
            camera_pitch_offset_deg=camera_pitch_offset_deg,
        )
        capture["view_variant"] = ISAACLAB_ROBOT_VIEW_VARIANT
        capture["view_provenance"] = "test_fake_isaac_visual_backend"
        return capture


def _empty_cleanup_scenario(scenario_id: str) -> CleanupScenario:
    return CleanupScenario(
        scenario_id=scenario_id,
        task="check MCP done readiness policy",
        seed=7,
        objects=(),
        receptacles=(
            CleanupReceptacle("sofa_01", "Sofa", "living_area", category="Sofa"),
            CleanupReceptacle("floor_01", "Floor", "living_area", category="Floor"),
            CleanupReceptacle("armchair_01", "Armchair", "living_area", category="Armchair"),
            CleanupReceptacle("desk_01", "Desk", "office", category="Desk"),
            CleanupReceptacle(
                "coffee_table_01", "Coffee Table", "living_area", category="CoffeeTable"
            ),
            CleanupReceptacle("sink_01", "Sink", "kitchen", category="Sink"),
            CleanupReceptacle("bookshelf_01", "Bookshelf", "living_area", category="ShelvingUnit"),
            CleanupReceptacle(
                "laundry_hamper_01", "Laundry Hamper", "bedroom", category="LaundryHamper"
            ),
            CleanupReceptacle("fridge_01", "Fridge", "kitchen", category="Fridge"),
            CleanupReceptacle("toy_bin_01", "Toy Bin", "living_area", category="ToyBin"),
        ),
        private_manifest=PrivateScoringManifest(
            scenario_id=scenario_id,
            targets=(),
            success_threshold=0,
        ),
    )


def _raw_fpv_camera_raw_server(tmp_path: Path) -> Any:
    scenario = build_cleanup_scenario(seed=7)
    backend = MolmoSpacesSubprocessBackend(scenario)
    return make_household_world_mcp(
        run_dir=tmp_path,
        scenario=scenario,
        base_contract=HouseholdBackendSession(scenario, backend=backend),
        port=0,
        policy="codex_agent",
        agent_driven=True,
        record_robot_views=True,
        perception_mode=RAW_FPV_ONLY_MODE,
        evidence_lane="camera-raw-fpv",
    )


def _complete_raw_fpv_heading_coverage(server: Any) -> None:
    metric_map = server.call_tool("metric_map")
    for waypoint in metric_map["inspection_waypoints"]:
        server.call_tool("navigate_to_waypoint", waypoint_id=waypoint["waypoint_id"])
        for heading in (0.0, 90.0, 180.0, 270.0):
            server.call_tool("observe")
            server.contract._raw_fpv_observations[-1][  # noqa: SLF001
                "camera_control_contract"
            ] = {
                "robot_pose": {
                    "pose_source": "relative_robot_frame",
                    "theta": math.radians(heading),
                }
            }


def _sweep_with_unresolved_raw_fpv_declarations(
    server: Any,
    *,
    declaration_count: int,
) -> None:
    metric_map = server.call_tool("metric_map")
    declarations = 0
    for waypoint in metric_map["inspection_waypoints"]:
        server.call_tool("navigate_to_waypoint", waypoint_id=waypoint["waypoint_id"])
        observation = server.call_tool("observe")
        if declarations < declaration_count:
            response = server.call_tool(
                "navigate_to_visual_candidate",
                source_observation_id=observation["raw_fpv_observation"]["observation_id"],
                category="imaginary widget",
                evidence_note="nonexistent public object declaration for done guard",
                image_region={"type": "verbal_region", "value": "front area"},
            )
            assert response["ok"] is False
            assert response["error_reason"] == "visual_candidate_not_resolved"
            declarations += 1
    assert declarations == declaration_count


def _clean_raw_fpv_candidate(
    server: Any,
    *,
    observation_id: str,
    candidate_input: dict[str, Any],
) -> str | None:
    candidate = server.call_tool(
        "navigate_to_visual_candidate",
        source_observation_id=observation_id,
        category=str(candidate_input["category"]),
        source_fixture_id=str(candidate_input.get("source_fixture_id") or ""),
        evidence_note=str(candidate_input.get("evidence_note") or ""),
        image_region=candidate_input.get("image_region")
        or {"type": "bbox", "value": [0.12, 0.24, 0.18, 0.16]},
    )
    if not candidate.get("ok"):
        return None
    object_id = str(candidate["object_id"])
    assert server.call_tool("pick", object_id=object_id)["ok"] is True
    fixture_id = str(candidate["candidate_fixture_id"])
    assert server.call_tool("navigate_to_receptacle", fixture_id=fixture_id)["ok"] is True
    if candidate["recommended_tool"] == "place_inside":
        placed = server.call_tool("place_inside", fixture_id=fixture_id)
        if (
            not placed.get("ok")
            and placed.get("error_reason") == "semantic_order"
            and placed.get("required_tool") == "open_receptacle"
        ):
            assert server.call_tool("open_receptacle", fixture_id=fixture_id)["ok"] is True
            placed = server.call_tool("place_inside", fixture_id=fixture_id)
            assert placed["ok"] is True
            assert server.call_tool("close_receptacle", fixture_id=fixture_id)["ok"] is True
    else:
        placed = server.call_tool("place", fixture_id=fixture_id)
    assert placed["ok"] is True
    server.call_tool("observe")
    return object_id


def _complete_raw_fpv_cleanup_chains(
    server: Any,
    *,
    required_count: int,
) -> set[str]:
    metric_map = server.call_tool("metric_map")
    handled: set[str] = set()
    for waypoint in metric_map["inspection_waypoints"]:
        waypoint_id = str(waypoint["waypoint_id"])
        server.call_tool("navigate_to_waypoint", waypoint_id=waypoint_id)
        observation = server.call_tool("observe")
        observation_id = observation["raw_fpv_observation"]["observation_id"]
        public_waypoint = server.contract._waypoint_by_id(waypoint_id)  # noqa: SLF001
        if public_waypoint is None:
            continue
        candidate_inputs = simulated_declaration_inputs_for_waypoint(
            server.contract,
            public_waypoint,
            observation_id=observation_id,
        )
        for candidate_input in candidate_inputs:
            object_id = _clean_raw_fpv_candidate(
                server,
                observation_id=observation_id,
                candidate_input=candidate_input,
            )
            if object_id is None or object_id in handled:
                continue
            handled.add(object_id)
            if len(handled) >= required_count:
                break
        if len(handled) >= required_count:
            break
    assert len(handled) >= required_count
    for waypoint in metric_map["inspection_waypoints"]:
        if waypoint.get("visited"):
            continue
        server.call_tool("navigate_to_waypoint", waypoint_id=waypoint["waypoint_id"])
        server.call_tool("observe")
    return handled


def test_realworld_mcp_raw_fpv_camera_raw_done_requires_complete_live_chains(
    tmp_path: Path,
) -> None:
    server = _raw_fpv_camera_raw_server(tmp_path)
    try:
        _sweep_with_unresolved_raw_fpv_declarations(server, declaration_count=5)
        _complete_raw_fpv_heading_coverage(server)
        done = server.call_tool("done", reason="codex finished early after sweep")
    finally:
        server.close()

    assert done["ok"] is False
    assert done["tool"] == "done"
    assert done["status"] == "blocked"
    assert done["error_reason"] == "insufficient_raw_fpv_overlap_probe_coverage"
    assert done["required_tool"] == "navigate_to_waypoint"
    assert done["completion"]["status"] == "blocked"
    blocker = done["completion"]["blockers"][-1]
    assert blocker["type"] == "insufficient_grounded_cleanup_chains"
    assert blocker["current"] == 0
    assert blocker["required"] == 4
    assert blocker["required_tool"] == "navigate_to_visual_candidate"
    assert "score" not in done
    assert "cleanup_status" not in done
    assert "target_receptacle_id" not in str(done)
    assert "private_manifest" not in str(done)
    assert not (tmp_path / "run_result.json").exists()


def test_realworld_mcp_world_labels_requested_run_size_does_not_use_raw_fpv_chain_gate(
    tmp_path: Path,
) -> None:
    scenario = _empty_cleanup_scenario("mcp-world-public-labels-readiness-policy-test")
    backend = MolmoSpacesSubprocessBackend(scenario)
    server = make_household_world_mcp(
        run_dir=tmp_path,
        scenario=scenario,
        base_contract=HouseholdBackendSession(scenario, backend=backend),
        port=0,
        policy="codex_agent",
        agent_driven=True,
        record_robot_views=True,
        evidence_lane=WORLD_PUBLIC_LABELS_PROFILE,
    )
    try:
        assert "cleanup_worklist" not in _fastmcp_tool_names(server)
        assert "check_done_ready" not in _fastmcp_tool_names(server)
        metric_map = server.call_tool("metric_map")
        for waypoint in metric_map["inspection_waypoints"]:
            server.call_tool("navigate_to_waypoint", waypoint_id=waypoint["waypoint_id"])
            server.call_tool("observe")
        done = server.call_tool("done", reason="world-public-labels sweep complete")
        run_result = json.loads(Path(done["run_result"]).read_text(encoding="utf-8"))
    finally:
        server.close()

    assert done["ok"] is True
    _assert_run_evidence_lane(run_result, WORLD_PUBLIC_LABELS_PROFILE)
    assert run_result["perception_mode"] != RAW_FPV_ONLY_MODE
    assert run_result["requested_generated_mess_count"] == 5
    assert run_result["agent_diagnostics"]["complete_semantic_substep_objects"] == 0


def test_realworld_mcp_open_ended_intent_is_recorded_in_run_result(
    tmp_path: Path,
) -> None:
    prompt = "我渴了，帮我找些解渴的东西"
    server = make_household_world_mcp(
        run_dir=tmp_path,
        scenario=build_cleanup_scenario(seed=7),
        port=0,
        policy="codex_agent",
        agent_driven=True,
        task_prompt=prompt,
        goal_contract=_open_ended_goal_contract(prompt),
    )
    try:
        assert set(ATOMIC_CLEANUP_TOOL_NAMES) <= _listed_fastmcp_tool_names(server)
        server.call_tool("metric_map")
        server.call_tool("observe")
        done = server.call_tool("done", reason="open-ended task complete")
        run_result = json.loads(Path(done["run_result"]).read_text(encoding="utf-8"))
    finally:
        server.close()

    assert done["ok"] is True
    assert done["intent_status"] == "success"
    assert done["goal_status"] == "success"
    assert run_result["task_prompt"] == prompt
    assert "task_intent_mode" not in run_result
    assert run_result["task_intent"] == "open-ended"
    assert run_result["goal_contract"]["intent"] == "open-ended"
    assert run_result["intent_status"] == "success"
    assert run_result["goal_status"] == "success"
    assert run_result["final_status"] == "success"
    assert run_result["cleanup_status_role"] == "advisory"
    assert run_result["cleanup_status"] == "failed"


def test_realworld_mcp_camera_grounded_isaac_closeout_writes_run_result(
    tmp_path: Path,
) -> None:
    prompt = "巡检 B1 / Map 12 digital twin，报告至少一个公开候选目标。"
    scenario = build_cleanup_scenario(seed=7)
    backend = IsaacLabSubprocessBackend(scenario)
    server = make_household_world_mcp(
        run_dir=tmp_path,
        scenario=scenario,
        base_contract=HouseholdBackendSession(scenario, backend=backend),
        port=0,
        policy="codex_agent",
        agent_driven=True,
        task_prompt=prompt,
        goal_contract=_open_ended_goal_contract(prompt),
        record_robot_views=True,
        perception_mode=CAMERA_MODEL_POLICY_MODE,
        evidence_lane="camera-grounded-labels",
        visual_grounding="grounding-dino",
    )
    try:
        metric_map = server.call_tool("metric_map")
        server.call_tool(
            "navigate_to_waypoint",
            waypoint_id=metric_map["inspection_waypoints"][0]["waypoint_id"],
        )
        observation = server.call_tool("observe")
        declaration = server.call_tool(
            "declare_visual_candidates",
            observation_id=observation["raw_fpv_observation"]["observation_id"],
            candidates=[
                {
                    "category": "mug",
                    "evidence_note": "Grounding DINO fixture detected mug from RAW_FPV pixels",
                    "image_region": {"type": "bbox", "value": [0.2, 0.2, 0.4, 0.4]},
                    "confidence": 0.8,
                }
            ],
        )
        done = server.call_tool("done", reason="open-ended camera-grounded proof complete")
        run_result = json.loads(Path(done["run_result"]).read_text(encoding="utf-8"))
    finally:
        server.close()

    assert done["ok"] is True
    assert declaration["ok"] is True
    assert run_result["backend"] == ISAACLAB_SUBPROCESS_BACKEND
    assert run_result["task_intent"] == "open-ended"
    assert run_result["intent_status"] == "success"
    assert run_result["evidence_lane"] == "camera-grounded-labels"
    assert run_result["camera_labeler"] == "grounding-dino"
    assert run_result["evidence_lane_metadata"]["backend"] == ISAACLAB_SUBPROCESS_BACKEND
    assert run_result["evidence_lane_metadata"]["world_backend"] == "isaac_sim"
    assert run_result["evidence_lane_metadata"]["camera_labeler"] == "grounding-dino"
    assert run_result["view_variant"] == ISAACLAB_ROBOT_VIEW_VARIANT
    assert run_result["robot_view_steps"]
    assert run_result["artifacts"]["robot_views"] == str(tmp_path / "robot_views")


def test_realworld_mcp_raw_fpv_camera_raw_done_allows_complete_live_chains(
    tmp_path: Path,
) -> None:
    server = _raw_fpv_camera_raw_server(tmp_path)
    try:
        handled = _complete_raw_fpv_cleanup_chains(server, required_count=5)
        _complete_raw_fpv_heading_coverage(server)
        done = server.call_tool("done", reason="enough grounded chains completed")
        run_result = json.loads(Path(done["run_result"]).read_text(encoding="utf-8"))
    finally:
        server.close()

    assert done["ok"] is True
    assert len(handled) >= 5
    _assert_run_evidence_lane(run_result, "camera-raw-fpv")
    assert run_result["agent_diagnostics"]["complete_semantic_substep_objects"] >= 4


def test_realworld_mcp_can_record_robot_view_timeline(tmp_path: Path) -> None:
    smoke = _load_smoke_module()
    scenario = build_cleanup_scenario(seed=7)
    backend = _FakeVisualBackend(scenario)
    base_contract = HouseholdBackendSession(scenario, backend=backend)
    server = make_household_world_mcp(
        run_dir=tmp_path,
        scenario=scenario,
        base_contract=base_contract,
        port=0,
        record_robot_views=True,
        task_prompt="record robot view timeline",
        goal_contract=_open_ended_goal_contract("record robot view timeline"),
    )
    try:
        smoke._drive_public_sweep(server)
        done = server.call_tool("done", reason="household_contract_smoke_agent cleanup complete")
    finally:
        server.close()

    run_result = json.loads((tmp_path / "run_result.json").read_text(encoding="utf-8"))
    report_text = (tmp_path / "report.html").read_text(encoding="utf-8")

    assert done["cleanup_status"] == "failed"
    assert run_result["cleanup_status_role"] == "advisory"
    assert run_result["view_variant"] == "molmospaces-rby1m-fpv-topdown-chase-verify"
    assert run_result["robot_view_camera_control"]["schema"] == (
        "robot_view_camera_control_summary_v1"
    )
    assert run_result["robot_view_camera_control"]["same_pose_api"] is False
    assert run_result["robot_view_steps"][0]["action"] == "before"
    assert any(step["action"] == "observe" for step in run_result["robot_view_steps"])
    assert "Robot View Timeline" in report_text
    assert "Robot-view camera" in report_text


def test_realworld_mcp_action_timeline_policy_skips_report_only_observe_capture(
    tmp_path: Path,
) -> None:
    scenario = build_cleanup_scenario(seed=7)
    backend = _FakeVisualBackend(scenario)
    base_contract = HouseholdBackendSession(scenario, backend=backend)
    server = make_household_world_mcp(
        run_dir=tmp_path,
        scenario=scenario,
        base_contract=base_contract,
        port=0,
        record_robot_views=True,
        perception_mode=RAW_FPV_ONLY_MODE,
        robot_view_capture_policy=ROBOT_VIEW_CAPTURE_POLICY_ACTION_TIMELINE,
    )
    try:
        metric_map = server.call_tool("metric_map")
        server.call_tool(
            "navigate_to_waypoint",
            waypoint_id=metric_map["inspection_waypoints"][0]["waypoint_id"],
        )
        observation = server.call_tool("observe")
        server._record_tool_robot_view(
            "navigate_to_object",
            {"object_id": "observed_test_object"},
            {"ok": True, "object_id": "observed_test_object"},
        )
        server._record_robot_view("after", label_suffix="after")
        steps = list(server.robot_view_steps)
    finally:
        server.close()

    assert observation["raw_fpv_observation"]["image_artifacts"]["fpv"].endswith(".png")

    actions = [step["action"] for step in steps]
    assert server.robot_view_capture_policy == ROBOT_VIEW_CAPTURE_POLICY_ACTION_TIMELINE
    assert actions[0] == "before"
    assert actions[-1] == "after"
    assert any(action.startswith("observe raw_fpv_") for action in actions)
    assert "observe" not in actions
    assert any(action.startswith("navigate_to_object ") for action in actions)

    trace_events = [
        json.loads(line)
        for line in (tmp_path / "trace.jsonl").read_text(encoding="utf-8").splitlines()
        if line
    ]
    assert any(
        item.get("event") == "robot_view_capture_skipped"
        and item.get("tool") == "<runtime>"
        and item.get("skipped_tool") == "observe"
        and item.get("policy") == ROBOT_VIEW_CAPTURE_POLICY_ACTION_TIMELINE
        for item in trace_events
    )


def test_realworld_mcp_raw_fpv_mode_delivers_fpv_image_blocks(tmp_path: Path) -> None:
    scenario = build_cleanup_scenario(seed=7)
    backend = _FakeVisualBackend(scenario)
    base_contract = HouseholdBackendSession(scenario, backend=backend)
    server = make_household_world_mcp(
        run_dir=tmp_path,
        scenario=scenario,
        base_contract=base_contract,
        port=0,
        record_robot_views=True,
        perception_mode=RAW_FPV_ONLY_MODE,
    )
    try:
        metric_map = server.call_tool("metric_map")
        server.call_tool(
            "navigate_to_waypoint",
            waypoint_id=metric_map["inspection_waypoints"][0]["waypoint_id"],
        )
        server.call_tool("adjust_camera", yaw_delta_deg=15, pitch_delta_deg=-5)
        observation_blocks = server._mcp_observe_response()
    finally:
        server.close()

    assert isinstance(observation_blocks, list)
    assert len(observation_blocks) == 2
    observation = json.loads(observation_blocks[0])
    raw = observation["raw_fpv_observation"]

    assert observation["schema"] == "raw_fpv_mcp_observe_state_v1"
    assert observation["perception_mode"] == RAW_FPV_ONLY_MODE
    assert observation["visible_object_detections"] == []
    assert observation["cleanup_worklist_summary"] == {
        "schema": "cleanup_worklist_summary_v1",
        "object_count": 0,
        "handled_object_handles": [],
        "pending_object_handles": [],
        "objects": [],
        "next_actions": [],
        "next_action_count": 0,
        "held_object_id": None,
    }
    assert "inline_on_navigate" in observation["instruction"]
    assert "navigate_to_visual_candidate" in observation["instruction"]
    assert "declare_visual_candidates" not in observation["instruction"]
    assert raw["image_artifacts"]["fpv"].endswith(".png")
    assert "camera_control_contract" not in raw
    assert raw["camera_control_summary"] == {
        "schema": "robot_view_camera_control_contract_summary_v1",
        "contract_schema": "robot_view_camera_control_contract_v1",
        "status": "backend_local_robot_camera",
        "camera_model": "backend_local_robot_view",
        "same_pose_api": False,
        "agent_facing_fpv_source": "test_fake_fpv",
        "canonical_camera_control": False,
    }
    assert raw["camera_offset"] == {"yaw_delta_deg": 15.0, "pitch_delta_deg": -5.0}
    assert backend.robot_view_camera_offsets[-1] == {
        "yaw_delta_deg": 15.0,
        "pitch_delta_deg": -5.0,
    }
    assert (tmp_path / raw["image_artifacts"]["fpv"]).is_file()
    image_block = observation_blocks[1]
    assert hasattr(image_block, "data")
    assert isinstance(image_block.data, bytes)
    assert len(image_block.data) > 0
    assert getattr(image_block, "_mime_type", "") == "image/png"


def test_realworld_mcp_raw_fpv_compact_state_includes_public_handled_handles(
    tmp_path: Path,
) -> None:
    scenario = build_cleanup_scenario(seed=7)
    backend = _FakeVisualBackend(scenario)
    base_contract = HouseholdBackendSession(scenario, backend=backend)
    server = make_household_world_mcp(
        run_dir=tmp_path,
        scenario=scenario,
        base_contract=base_contract,
        port=0,
        record_robot_views=True,
        perception_mode=RAW_FPV_ONLY_MODE,
    )
    try:
        work_waypoint = next(
            item
            for item in server.contract.metric_map()["inspection_waypoints"]
            if item["waypoint_id"] == "room_4_inspection"
        )
        server.call_tool("navigate_to_waypoint", waypoint_id=str(work_waypoint["waypoint_id"]))
        observation = server.call_tool("observe")
        candidate = server.call_tool(
            "navigate_to_visual_candidate",
            source_observation_id=observation["raw_fpv_observation"]["observation_id"],
            category="tomato",
            evidence_note="round produce item on the desk",
            image_region={"type": "bbox", "value": [0.12, 0.24, 0.18, 0.16]},
        )
        assert candidate["ok"] is True
        assert server.call_tool("pick", object_id=candidate["object_id"])["ok"] is True
        fixture_id = candidate["candidate_fixture_id"]
        assert server.call_tool("navigate_to_receptacle", fixture_id=fixture_id)["ok"] is True
        placed = server.call_tool("place_inside", fixture_id=fixture_id)
        if (
            not placed.get("ok")
            and placed.get("error_reason") == "semantic_order"
            and placed.get("required_tool") == "open_receptacle"
        ):
            assert server.call_tool("open_receptacle", fixture_id=fixture_id)["ok"] is True
            placed = server.call_tool("place_inside", fixture_id=fixture_id)
        assert placed["ok"] is True
        observation_blocks = server._mcp_observe_response()
    finally:
        server.close()

    assert isinstance(observation_blocks, list)
    observation_state = json.loads(observation_blocks[0])
    image_block = observation_blocks[1]
    summary = observation_state["cleanup_worklist_summary"]
    objects = {item["object_id"]: item for item in summary["objects"]}
    assert candidate["object_id"] in summary["handled_object_handles"]
    assert objects[candidate["object_id"]]["state"] == "placed"
    assert objects[candidate["object_id"]]["category"]
    assert len(image_block.data) > 0


def test_realworld_mcp_raw_fpv_trace_records_agent_facing_compact_state(
    tmp_path: Path,
) -> None:
    scenario = build_cleanup_scenario(seed=7)
    backend = _FakeVisualBackend(scenario)
    base_contract = HouseholdBackendSession(scenario, backend=backend)
    server = make_household_world_mcp(
        run_dir=tmp_path,
        scenario=scenario,
        base_contract=base_contract,
        port=0,
        record_robot_views=True,
        perception_mode=RAW_FPV_ONLY_MODE,
    )
    try:
        metric_map = server.call_tool("metric_map")
        server.call_tool(
            "navigate_to_waypoint",
            waypoint_id=metric_map["inspection_waypoints"][0]["waypoint_id"],
        )
        observation_blocks = server._mcp_observe_response()
    finally:
        server.close()

    observation_state = json.loads(observation_blocks[0])
    trace_events = [
        json.loads(line)
        for line in (tmp_path / "trace.jsonl").read_text(encoding="utf-8").splitlines()
    ]
    trace_observe = next(
        event
        for event in trace_events
        if event["tool"] == "observe" and event["event"] == "response"
    )
    compact_state = trace_observe["response"]["agent_facing_compact_state"]

    assert compact_state["schema"] == "raw_fpv_mcp_observe_state_v1"
    assert (
        compact_state["cleanup_worklist_summary"] == observation_state["cleanup_worklist_summary"]
    )
    assert (
        compact_state["raw_fpv_observation"]["observation_id"]
        == observation_state["raw_fpv_observation"]["observation_id"]
    )
    assert "camera_control_contract" not in compact_state["raw_fpv_observation"]


def test_realworld_mcp_raw_fpv_compact_state_lists_actionable_pending_handles(
    tmp_path: Path,
) -> None:
    scenario = build_cleanup_scenario(seed=7)
    backend = _FakeVisualBackend(scenario)
    base_contract = HouseholdBackendSession(scenario, backend=backend)
    server = make_household_world_mcp(
        run_dir=tmp_path,
        scenario=scenario,
        base_contract=base_contract,
        port=0,
        record_robot_views=True,
        perception_mode=RAW_FPV_ONLY_MODE,
    )
    try:
        server.call_tool("metric_map")
        server.call_tool("navigate_to_waypoint", waypoint_id="room_4_inspection")
        server.call_tool("observe")
        server.call_tool("navigate_to_waypoint", waypoint_id="room_4_inspection")
        observation = server.call_tool("observe")
        candidate = server.call_tool(
            "navigate_to_visual_candidate",
            source_observation_id=observation["raw_fpv_observation"]["observation_id"],
            category="tomato",
            evidence_note="round produce item on the desk",
            image_region={"type": "bbox", "value": [0.12, 0.24, 0.18, 0.16]},
        )
        assert candidate["ok"] is True
        assert candidate["required_next_tool"] == "pick"
        observation_blocks = server._mcp_observe_response()
    finally:
        server.close()

    observation_state = json.loads(observation_blocks[0])
    summary = observation_state["cleanup_worklist_summary"]
    next_action = summary["next_actions"][0]

    assert summary["next_action_count"] == 1
    assert next_action["object_id"] == candidate["object_id"]
    assert next_action["candidate_fixture_id"] == candidate["candidate_fixture_id"]
    assert next_action["recommended_tool"] == candidate["recommended_tool"]
    assert next_action["state"] == "navigating_to_object"
    assert next_action["tool_sequence"] == [
        "pick",
        "navigate_to_receptacle",
        candidate["recommended_tool"],
    ]


def test_realworld_mcp_raw_fpv_artifact_filters_private_camera_contract_keys(
    tmp_path: Path,
) -> None:
    scenario = build_cleanup_scenario(seed=7)
    contract = HouseholdRuntimeContract(
        HouseholdBackendSession(scenario),
        perception_mode=RAW_FPV_ONLY_MODE,
        map_bundle_dir=PREBUILT_BUNDLE,
    )
    metric_map = contract.metric_map()
    contract.navigate_to_waypoint(metric_map["inspection_waypoints"][0]["waypoint_id"])
    observation = contract.observe()
    observation_id = observation["raw_fpv_observation"]["observation_id"]

    attached = contract.attach_raw_fpv_observation_artifact(
        observation_id,
        views={"fpv": "robot_views/raw_fpv_001.fpv.png"},
        robot_view_label="0001_observe_raw_fpv_001",
        camera_control_contract={
            "schema": "robot_view_camera_control_contract_v1",
            "agent_facing_fpv": {"source": "robot_0/head_camera"},
            "robot_pose": {
                "target_receptacle_id": "private_sink_01",
                "pose_request": {"target_receptacle_id": "private_sink_01"},
            },
        },
    )

    assert attached is not None
    assert attached["camera_control_contract"]["schema"] == (
        "robot_view_camera_control_contract_v1"
    )
    assert "target_receptacle_id" not in json.dumps(attached)


def test_realworld_mcp_camera_labels_declare_response_is_agent_compact(
    tmp_path: Path,
) -> None:
    server = make_household_world_mcp(
        run_dir=tmp_path,
        scenario=build_cleanup_scenario(seed=7),
        port=0,
        perception_mode=CAMERA_MODEL_POLICY_MODE,
    )
    try:
        metric_map = server.call_tool("metric_map")
        declaration = {}
        for waypoint in metric_map["inspection_waypoints"]:
            server.call_tool("navigate_to_waypoint", waypoint_id=waypoint["waypoint_id"])
            observation = server.call_tool("observe")
            declaration = server.call_tool(
                "declare_visual_candidates",
                observation_id=observation["raw_fpv_observation"]["observation_id"],
            )
            if declaration["model_declared_observations"]:
                break
        agent_view = server._agent_view_payload()
    finally:
        server.close()

    assert declaration["ok"] is True
    assert declaration["visual_grounding_pipeline"]["pipeline_id"] == "sim"
    assert declaration["model_declared_observations"]
    assert declaration["camera_model_candidates"]
    assert "model_declared_observation_evidence" not in declaration
    assert "visual_grounding_pipeline" not in declaration["model_declared_observations"][0]
    assert "model_declared_observation" not in declaration["camera_model_candidates"][0]
    assert (
        agent_view_module.camera_model_policy_evidence(agent_view)["visual_grounding_pipeline_id"]
        == "sim"
    )
