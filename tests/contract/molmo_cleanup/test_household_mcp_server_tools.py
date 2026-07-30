from __future__ import annotations

import json
from pathlib import Path

import pytest

from roboclaws.household import agent_view as agent_view_module
from roboclaws.household.household_backend_contract import HouseholdBackendSession
from roboclaws.household.household_runtime_contract import (
    RAW_FPV_ONLY_MODE,
)
from roboclaws.household.profiles import WORLD_PUBLIC_LABELS_PROFILE
from roboclaws.household.realworld_mcp_atomic_tools import ATOMIC_CLEANUP_TOOL_NAMES
from roboclaws.household.realworld_mcp_semantic_tools import SEMANTIC_CLEANUP_TOOL_NAMES
from roboclaws.household.scenario import build_cleanup_scenario
from roboclaws.mcp.profiles import (
    HOUSEHOLD_EPISODE_PROFILE,
    HOUSEHOLD_MANIPULATION_PROFILE,
    HOUSEHOLD_WORLD_PROFILE,
    contract_profile,
)
from tests.contract.molmo_cleanup.household_mcp_server_support import (
    _FakeVisualBackend,
    _fastmcp_tool_names,
    _listed_fastmcp_tool_names,
    make_household_world_mcp,
)


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
