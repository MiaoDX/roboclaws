from __future__ import annotations

from pathlib import Path

from tests.contract.molmo_cleanup.household_mcp_server_support import (
    _complete_raw_fpv_heading_coverage,
    _raw_fpv_camera_raw_server,
)


def test_recovery_gate_consumes_overlap_probe_and_binds_fresh_view(tmp_path: Path) -> None:
    server = _raw_fpv_camera_raw_server(tmp_path)
    try:
        _complete_raw_fpv_heading_coverage(server)
        server.call_tool("check_operator_messages")
        completion = server._agent_view_payload()["readiness"]["completion"]
        overlap = next(
            blocker
            for blocker in completion["blockers"]
            if blocker["type"] == "insufficient_raw_fpv_overlap_probe_coverage"
        )
        overlap_waypoint = str(overlap["next_waypoint_id"])

        wrong = server.call_tool(
            "navigate_to_waypoint",
            waypoint_id=next(
                str(item["waypoint_id"])
                for item in server.contract.metric_map()["inspection_waypoints"]
                if str(item["waypoint_id"]) != overlap_waypoint
            ),
        )
        assert wrong["error_reason"] == "raw_fpv_recovery_wrong_waypoint"

        assert server.call_tool("navigate_to_waypoint", waypoint_id=overlap_waypoint)["ok"] is True
        wrong_adjustment = server.call_tool("adjust_camera", yaw_delta_deg=45, pitch_delta_deg=0)
        assert wrong_adjustment["error_reason"] == "raw_fpv_recovery_wrong_camera_adjustment"
        assert server.call_tool("adjust_camera", yaw_delta_deg=45, pitch_delta_deg=20)["ok"] is True
        fresh = server.call_tool("observe")
        assert fresh["ok"] is True
        assert fresh["completion"]["source_tool"] == "observe"
        assert fresh["completion"]["response_id"] > completion["response_id"]
    finally:
        server.close()
