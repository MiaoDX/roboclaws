from __future__ import annotations

from pathlib import Path

from tests.contract.molmo_cleanup.test_molmo_realworld_mcp_server import (
    _complete_raw_fpv_heading_coverage,
    _raw_fpv_camera_raw_server,
)


def test_recovery_gate_consumes_overlap_probe_and_binds_fresh_view(tmp_path: Path) -> None:
    server = _raw_fpv_camera_raw_server(tmp_path)
    try:
        _complete_raw_fpv_heading_coverage(server)
        done = server.call_tool("done", reason="request bounded recovery")
        assert done["error_reason"] == "insufficient_raw_fpv_overlap_probe_coverage"
        overlap_waypoint = str(done["next_waypoint_id"])

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
        assert server.call_tool("observe")["ok"] is True

        repeated = server.call_tool("navigate_to_waypoint", waypoint_id=overlap_waypoint)
        assert repeated["error_reason"] == "raw_fpv_recovery_waypoint_consumed"

        next_waypoint = str(repeated["next_waypoint_id"])
        assert next_waypoint and next_waypoint != overlap_waypoint
        assert server.call_tool("navigate_to_waypoint", waypoint_id=next_waypoint)["ok"] is True
        assert (
            server.call_tool(
                "navigate_to_relative_pose",
                forward_m=0,
                lateral_m=0,
                yaw_delta_deg=45,
            )["ok"]
            is True
        )
        fresh = server.call_tool("observe")
        fresh_id = str(fresh["raw_fpv_observation"]["observation_id"])

        candidate_args = {
            "category": "imaginary widget",
            "evidence_note": "public fresh-view recovery test",
            "image_region": {"type": "verbal_region", "value": "front area"},
        }
        stale = server.call_tool(
            "navigate_to_visual_candidate",
            source_observation_id="raw_fpv_old",
            **candidate_args,
        )
        assert stale["error_reason"] == "raw_fpv_recovery_stale_observation"
        attempted = server.call_tool(
            "navigate_to_visual_candidate",
            source_observation_id=fresh_id,
            **candidate_args,
        )
        assert attempted["error_reason"] == "visual_candidate_not_resolved"
        retried = server.call_tool(
            "navigate_to_visual_candidate",
            source_observation_id=fresh_id,
            **candidate_args,
        )
        assert retried["error_reason"] == "raw_fpv_recovery_observation_consumed"
    finally:
        server.close()
