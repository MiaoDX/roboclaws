"""Composite evidence must not compete with its latest completion snapshot."""

import json
from pathlib import Path

from roboclaws.household.household_runtime_contract import CAMERA_MODEL_POLICY_MODE
from tests.contract.molmo_cleanup.household_mcp_server_support import (
    _empty_cleanup_scenario,
    make_household_world_mcp,
)


def test_completed_observation_steps_do_not_reissue_obsolete_control(tmp_path: Path):
    server = make_household_world_mcp(
        run_dir=tmp_path,
        scenario=_empty_cleanup_scenario("composite-completion"),
        port=0,
        perception_mode=CAMERA_MODEL_POLICY_MODE,
        evidence_lane="camera-grounded-labels",
        agent_sdk_camera_grounded_composite_tools=True,
    )
    try:
        waypoints = server.call_tool("metric_map")["inspection_waypoints"]
        server.call_tool("navigate_to_waypoint", waypoint_id=waypoints[0]["waypoint_id"])
        result = server.call_tool("observe_camera_grounded_candidates")
    finally:
        server.close()

    assert result["ok"] is True
    assert result["completion"]["status"] == "blocked"
    assert result["completion"]["source_tool"] == "observe_camera_grounded_candidates"
    assert result["completion"]["next_actions"][0]["required_tool"] == "navigate_to_waypoint"
    assert not result.get("instruction")
    for step in ("observation", "declaration"):
        assert not {"instruction", "required_next_tool", "completion"} & result[step].keys()
    assert (
        result["observation"]["raw_fpv_observation"]["observation_id"] == result["observation_id"]
    )
    assert result["candidate_count"] == result["declaration"]["candidate_count"]

    trace = [json.loads(line) for line in (tmp_path / "trace.jsonl").read_text().splitlines()]
    observation = next(
        e["response"] for e in trace if e.get("event") == "response" and e.get("tool") == "observe"
    )
    declaration = next(
        e["response"]
        for e in trace
        if e.get("event") == "response" and e.get("tool") == "declare_visual_candidates"
    )
    assert "declare_visual_candidates" in observation["instruction"]
    assert "completion" in observation and "completion" in declaration
    assert "navigate_to_object" not in declaration.get("instruction", "")
