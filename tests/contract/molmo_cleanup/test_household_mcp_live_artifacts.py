from __future__ import annotations

import json
from pathlib import Path

from roboclaws.household.household_mcp_server import make_household_world_mcp
from roboclaws.household.scenario import build_cleanup_scenario
from roboclaws.mcp.profiles import HOUSEHOLD_EPISODE_PROFILE, HOUSEHOLD_WORLD_PROFILE
from tests.contract.molmo_cleanup.household_mcp_server_support import _empty_cleanup_scenario

REPO_ROOT = Path(__file__).resolve().parents[3]
PREBUILT_BUNDLE = REPO_ROOT / "assets" / "maps" / "molmospaces" / "procthor-10k-val" / "0"


def test_observe_prioritizes_done_when_cleanup_readiness_is_ready(tmp_path: Path) -> None:
    server = make_household_world_mcp(
        run_dir=tmp_path,
        scenario=_empty_cleanup_scenario("completion-ready-observe"),
        port=0,
        map_bundle_dir=PREBUILT_BUNDLE,
        required_capability_profiles=(HOUSEHOLD_WORLD_PROFILE, HOUSEHOLD_EPISODE_PROFILE),
    )
    try:
        metric_map = server.call_tool("metric_map")
        observations = []
        for waypoint in metric_map["inspection_waypoints"]:
            server.call_tool("navigate_to_waypoint", waypoint_id=waypoint["waypoint_id"])
            observations.append(server.call_tool("observe"))
        done = server.call_tool("done", reason="MCP-visible cleanup readiness is ready")
    finally:
        server.close()

    assert metric_map["inspection_waypoints"][4]["label"] == "Generated exploration candidate 5"
    assert metric_map["inspection_waypoints"][4]["room_label"] == "Bedroom"
    assert all("required_next_tool" not in item for item in observations[:-1])
    assert observations[-1]["required_next_tool"] == "done"
    assert observations[-1]["completion"]["schema"] == "household_completion_snapshot_v1"
    assert observations[-1]["completion"]["status"] == "ready"
    assert observations[-1]["completion"]["source_tool"] == "observe"
    assert observations[-1]["completion"]["next_actions"] == [{"required_tool": "done"}]
    assert observations[-1]["completion"]["policy_uses_private_truth"] is False
    assert "Call done now" in observations[-1]["instruction"]
    assert done["ok"] is True


def test_open_ended_metric_map_does_not_recommend_done_before_goal_evidence(
    tmp_path: Path,
) -> None:
    server = make_household_world_mcp(
        run_dir=tmp_path,
        scenario=_empty_cleanup_scenario("open-ended-completion-guidance"),
        port=0,
        task_intent="open-ended",
        task_prompt="Find Generated exploration candidate 5 and report its location.",
        map_bundle_dir=PREBUILT_BUNDLE,
        required_capability_profiles=(HOUSEHOLD_WORLD_PROFILE, HOUSEHOLD_EPISODE_PROFILE),
    )
    try:
        metric_map = server.call_tool("metric_map")
    finally:
        server.close()

    assert metric_map["inspection_waypoints"][4]["waypoint_id"] == "room_6_inspection"
    assert metric_map["completion"]["status"] == "ready"
    assert metric_map["completion"]["next_actions"] == []
    assert "required_next_tool" not in metric_map
    assert "Call done now" not in str(metric_map.get("instruction") or "")


def test_household_mcp_writes_live_public_map_artifacts_before_done(tmp_path: Path) -> None:
    server = make_household_world_mcp(
        run_dir=tmp_path,
        scenario=build_cleanup_scenario(seed=7),
        port=0,
        map_bundle_dir=PREBUILT_BUNDLE,
        required_capability_profiles=(HOUSEHOLD_WORLD_PROFILE, HOUSEHOLD_EPISODE_PROFILE),
    )
    try:
        metric_map = server.call_tool("metric_map")
        waypoint_id = str(metric_map["inspection_waypoints"][0]["waypoint_id"])
        server.call_tool("navigate_to_waypoint", waypoint_id=waypoint_id)
        server.call_tool("observe")
    finally:
        server.close()

    agent_view_path = tmp_path / "agent_view.json"
    runtime_map_path = tmp_path / "runtime_metric_map.json"
    runtime_preview_path = tmp_path / "runtime_metric_map_preview.png"
    map_preview_path = tmp_path / "map_bundle" / "preview.png"
    semantic_map_path = tmp_path / "semantic_map.png"
    overlay_path = tmp_path / "map_overlay.json"

    assert agent_view_path.is_file()
    assert runtime_map_path.is_file()
    assert runtime_preview_path.is_file()
    assert runtime_preview_path.read_bytes().startswith(b"\x89PNG\r\n\x1a\n")
    assert map_preview_path.is_file()
    assert not semantic_map_path.exists()
    assert not overlay_path.exists()
    assert not (tmp_path / "run_result.json").exists()

    agent_view = json.loads(agent_view_path.read_text(encoding="utf-8"))
    runtime_map = json.loads(runtime_map_path.read_text(encoding="utf-8"))
    trace_events = [
        json.loads(line) for line in (tmp_path / "trace.jsonl").read_text().splitlines()
    ]

    assert waypoint_id in agent_view["readiness"]["observed_waypoint_ids"]
    assert runtime_map["schema"] == "runtime_metric_map_v1"
    assert not any(
        event.get("event") == "live_public_artifact_write_failed" for event in trace_events
    )
