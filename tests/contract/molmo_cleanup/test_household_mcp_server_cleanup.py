from __future__ import annotations

import json
from pathlib import Path

import pytest

from roboclaws.core.robot_view_capture import ROBOT_VIEW_CAPTURE_POLICY_ACTION_TIMELINE
from roboclaws.household.household_backend_contract import HouseholdBackendSession
from roboclaws.household.household_runtime_contract import (
    RAW_FPV_ONLY_MODE,
)
from roboclaws.household.profiles import WORLD_PUBLIC_LABELS_PROFILE
from roboclaws.household.realworld_done_readiness import completion_snapshot_digest
from roboclaws.household.scenario import build_cleanup_scenario
from tests.contract.molmo_cleanup.household_mcp_server_support import (
    _assert_run_evidence_lane,
    _complete_raw_fpv_cleanup_chains,
    _complete_raw_fpv_heading_coverage,
    _FakeVisualBackend,
    _load_smoke_module,
    _open_ended_goal_contract,
    _raw_fpv_camera_raw_server,
    _sweep_with_unresolved_raw_fpv_declarations,
    make_household_world_mcp,
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

        with pytest.raises(ValueError, match="trace source row must contain a JSON object"):
            server.call_tool("done", reason="source validation probe")
    finally:
        server.close()

    assert not (tmp_path / "run_result.json").exists()


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


def test_atomic_responses_project_canonical_completion_snapshot(tmp_path: Path) -> None:
    server = make_household_world_mcp(
        run_dir=tmp_path,
        scenario=build_cleanup_scenario(seed=7),
        port=0,
        evidence_lane=WORLD_PUBLIC_LABELS_PROFILE,
    )
    try:
        metric_map = server.call_tool("metric_map")
        recoverable_error = server.call_tool("pick", object_id="stale_public_handle")
        agent_view = json.loads((tmp_path / "agent_view.json").read_text(encoding="utf-8"))
        trace = [
            json.loads(line)
            for line in (tmp_path / "trace.jsonl").read_text(encoding="utf-8").splitlines()
        ]
    finally:
        server.close()

    first = metric_map["completion"]
    latest = recoverable_error["completion"]
    assert recoverable_error["ok"] is False
    assert first["source_tool"] == "metric_map"
    assert latest["source_tool"] == "pick"
    assert latest["response_id"] == first["response_id"] + 1
    assert first["digest"] == completion_snapshot_digest(first)
    assert latest["digest"] == completion_snapshot_digest(latest)
    assert agent_view["readiness"]["completion"] == latest
    traced = [
        event["response"]["completion"] for event in trace if event.get("event") == "response"
    ]
    assert traced == [first, latest]
    serialized = json.dumps(latest)
    assert "private_manifest" not in serialized
    assert "target_receptacle_id" not in serialized


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


def test_realworld_mcp_raw_fpv_camera_raw_done_requires_complete_live_chains(
    tmp_path: Path,
) -> None:
    server = _raw_fpv_camera_raw_server(tmp_path)
    try:
        _sweep_with_unresolved_raw_fpv_declarations(server, declaration_count=5)
        _complete_raw_fpv_heading_coverage(server)
        done = server.call_tool("done", reason="codex finished early after sweep")
        run_result = json.loads((tmp_path / "run_result.json").read_text(encoding="utf-8"))
        first_mtime = (tmp_path / "run_result.json").stat().st_mtime_ns
        done_response_count = server._tool_event_counts["done:response"]
        repeated = server.call_tool("done", reason="must not finalize twice")
    finally:
        server.close()

    assert done["ok"] is False
    assert done["tool"] == "done"
    assert done["status"] == "terminal_incomplete"
    assert done["error_reason"] == "terminal_incomplete"
    assert done["completion"]["status"] == "blocked"
    blocker = done["completion"]["blockers"][-1]
    assert blocker["type"] == "insufficient_grounded_cleanup_chains"
    assert blocker["current"] == 0
    assert blocker["required"] == 4
    assert blocker["required_tool"] == "navigate_to_visual_candidate"
    assert done["cleanup_status"] == "incomplete"
    assert run_result["intent_status"] == "terminal_incomplete"
    assert run_result["goal_status"] == "terminal_incomplete"
    assert run_result["final_status"] == "terminal_incomplete"
    assert "target_receptacle_id" not in str(done)
    assert "private_manifest" not in str(done)
    assert (tmp_path / "run_result.json").exists()
    assert repeated == done
    assert (tmp_path / "run_result.json").stat().st_mtime_ns == first_mtime
    assert server._tool_event_counts["done:response"] == done_response_count == 1


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


def test_realworld_mcp_full_capture_deduplicates_unchanged_observe_assets(
    tmp_path: Path,
) -> None:
    scenario = build_cleanup_scenario(seed=7)
    backend = _FakeVisualBackend(scenario)
    server = make_household_world_mcp(
        run_dir=tmp_path,
        scenario=scenario,
        base_contract=HouseholdBackendSession(scenario, backend=backend),
        port=0,
        record_robot_views=True,
    )
    try:
        response = {"ok": True, "room_id": "room_1", "waypoint_id": "room_1_scan_1"}
        server._record_tool_robot_view("observe", {}, response)
        server._record_tool_robot_view("observe", {}, response)
        steps = list(server.robot_view_steps)
    finally:
        server.close()

    first, repeated = steps[-2:]
    assert first["action"] == repeated["action"] == "observe"
    assert repeated["capture_status"] == "deduplicated"
    assert repeated["deduplicated_from"] == first["label"]
    assert repeated["label"] != first["label"]
    assert repeated["views"] == first["views"]
    assert all(not Path(path).is_absolute() for path in repeated["views"].values())

    trace_events = [
        json.loads(line)
        for line in (tmp_path / "trace.jsonl").read_text(encoding="utf-8").splitlines()
        if line
    ]
    assert any(
        item.get("event") == "robot_view_capture_deduplicated"
        and item.get("deduplicated_from") == first["label"]
        for item in trace_events
    )
