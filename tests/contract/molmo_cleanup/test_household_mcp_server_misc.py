from __future__ import annotations

import json
from pathlib import Path

import pytest

from roboclaws.household import agent_view as agent_view_module
from roboclaws.household.household_backend_contract import HouseholdBackendSession
from roboclaws.household.household_mcp_server import (
    make_household_world_mcp as _make_household_world_mcp,
)
from roboclaws.household.household_runtime_contract import (
    CAMERA_MODEL_POLICY_MODE,
    RAW_FPV_ONLY_MODE,
    HouseholdRuntimeContract,
)
from roboclaws.household.isaac_lab_backend import (
    ISAACLAB_ROBOT_VIEW_VARIANT,
    ISAACLAB_SUBPROCESS_BACKEND,
)
from roboclaws.household.profiles import WORLD_PUBLIC_LABELS_PROFILE
from roboclaws.household.realworld_mcp_atomic_tools import ATOMIC_CLEANUP_TOOL_NAMES
from roboclaws.household.scenario import build_cleanup_scenario
from roboclaws.mcp.profiles import (
    HOUSEHOLD_EPISODE_PROFILE,
    HOUSEHOLD_WORLD_PROFILE,
)
from tests.contract.molmo_cleanup.household_mcp_server_support import (
    PREBUILT_BUNDLE,
    IsaacLabSubprocessBackend,
    MolmoSpacesSubprocessBackend,
    _assert_run_evidence_lane,
    _empty_cleanup_scenario,
    _FakeVisualBackend,
    _fastmcp_tool_names,
    _listed_fastmcp_tool_names,
    _load_smoke_module,
    _open_ended_goal_contract,
    make_household_world_mcp,
)


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
