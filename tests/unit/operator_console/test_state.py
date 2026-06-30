from __future__ import annotations

import json
import os
from pathlib import Path

from roboclaws.operator_console.locks import ResourceLock
from roboclaws.operator_console.routes import get_selection
from roboclaws.operator_console.state import (
    derive_operator_state,
    redacted_artifact_text,
    resolve_display_run_dir,
)

MUJOCO_SDK_CLEANUP = (
    "molmospaces/procthor-objaverse-val/0::mujoco::cleanup::openai-agents-sdk::world-public-labels"
)
MUJOCO_SDK_MAP_BUILD = (
    "molmospaces/procthor-objaverse-val/0::mujoco::map-build::openai-agents-sdk::"
    "world-public-labels"
)
B1_OPENAI_AGENTS_OPEN_TASK = "b1-map12::isaaclab::open-task::openai-agents-sdk::world-public-labels"


def test_state_derives_latest_tool_checker_and_artifact_links(tmp_path: Path) -> None:
    run_dir = tmp_path / "output" / "operator-console" / "runs" / "run"
    run_dir.mkdir(parents=True)
    (run_dir / "operator_state.json").write_text(
        json.dumps(
            {
                "run_id": "run",
                "route": get_selection(MUJOCO_SDK_CLEANUP).to_payload(),
                "phase": "running",
                "backend_lock": "molmospaces_mujoco",
                "started_at_epoch": 1.0,
                "prompt_preview": {
                    "operator_prompt": "收拾桌面上的杯子",
                    "agent_kickoff_prompt": "Use cleanup tools for the cup.",
                    "source": "household-cleanup",
                    "summary": "household-cleanup kickoff prompt",
                    "wrapper_notes": ["Codex wrapper applies."],
                },
            }
        ),
        encoding="utf-8",
    )
    (run_dir / "trace.jsonl").write_text(
        json.dumps({"event": "request", "tool": "observe"})
        + "\n"
        + json.dumps(
            {
                "event": "response",
                "tool": "pick",
                "ok": True,
                "observation_summary": "saw a mug",
            }
        )
        + "\n",
        encoding="utf-8",
    )
    (run_dir / "run_result.json").write_text(
        json.dumps(
            {
                "task": "clean the room",
                "success": True,
                "private_target_truth": {"must_not": "leak"},
            }
        )
        + "\n",
        encoding="utf-8",
    )
    (run_dir / "report.html").write_text("<html></html>", encoding="utf-8")

    state = derive_operator_state(tmp_path, run_dir, get_selection(MUJOCO_SDK_CLEANUP))

    assert state["status"] == "passed"
    assert state["latest_action"] == "pick"
    assert state["latest_public_decision_evidence"]["observation_summary"] == "saw a mug"
    assert state["checker_status"]["status"] == "passed"
    assert "private_target_truth" not in json.dumps(state["public_run_result"])
    assert state["prompt_preview"]["operator_prompt"] == "收拾桌面上的杯子"
    assert state["agent_kickoff_prompt"] == "Use cleanup tools for the cup."
    assert any(item["label"] == "Report" for item in state["artifact_paths"])


def test_state_surfaces_malformed_operator_state_source_error(tmp_path: Path) -> None:
    run_dir = tmp_path / "output" / "operator-console" / "runs" / "broken-wrapper"
    run_dir.mkdir(parents=True)
    (run_dir / "operator_state.json").write_text("{not-json", encoding="utf-8")

    state = derive_operator_state(tmp_path, run_dir, get_selection(MUJOCO_SDK_CLEANUP))

    assert state["run_id"] == "broken-wrapper"
    assert state["phase"] == "failed"
    assert state["status"] == "failed"
    assert state["terminal_reason"] == "operator state source error: Operator State"
    assert state["checker_status"]["message"] == (
        "Launch failed: operator state source error: Operator State"
    )
    assert state["source_errors"] == [
        {
            "label": "Operator State",
            "path": str((run_dir / "operator_state.json").resolve()),
            "href": (
                f"/artifacts/{(run_dir / 'operator_state.json').relative_to(tmp_path)}"
                f"?v={(run_dir / 'operator_state.json').stat().st_mtime_ns}"
            ),
            "reason": "invalid JSON at line 1 column 2",
        }
    ]


def test_state_surfaces_malformed_nested_live_status_and_run_result(
    tmp_path: Path,
) -> None:
    run_dir = tmp_path / "output" / "operator-console" / "runs" / "wrapper-run"
    attempt_dir = run_dir / "0619_1200" / "seed-7"
    attempt_dir.mkdir(parents=True)
    (run_dir / "operator_state.json").write_text(
        json.dumps(
            {
                "run_id": "wrapper-run",
                "route": get_selection(MUJOCO_SDK_CLEANUP).to_payload(),
                "phase": "starting",
                "backend_lock": "molmospaces_mujoco",
            }
        ),
        encoding="utf-8",
    )
    (attempt_dir / "live_status.json").write_text("{bad-live-status", encoding="utf-8")
    (attempt_dir / "run_result.json").write_text('["not", "object"]', encoding="utf-8")

    state = derive_operator_state(tmp_path, run_dir, get_selection(MUJOCO_SDK_CLEANUP))

    assert state["display_run_id"] == "0619_1200/seed-7"
    assert state["phase"] == "failed"
    assert state["status"] == "failed"
    assert state["terminal_reason"] == "operator state source error: Live Status, Run Result"
    assert [(error["label"], error["reason"]) for error in state["source_errors"]] == [
        ("Live Status", "invalid JSON at line 1 column 2"),
        ("Run Result", "expected JSON object"),
    ]
    assert state["checker_status"]["message"] == (
        "Launch failed: operator state source error: Live Status, Run Result"
    )


def test_state_surfaces_malformed_trace_source_error(tmp_path: Path) -> None:
    run_dir = tmp_path / "output" / "operator-console" / "runs" / "wrapper-run"
    attempt_dir = run_dir / "0619_1800" / "seed-7"
    attempt_dir.mkdir(parents=True)
    (run_dir / "operator_state.json").write_text(
        json.dumps(
            {
                "run_id": "wrapper-run",
                "route": get_selection(MUJOCO_SDK_CLEANUP).to_payload(),
                "phase": "starting",
                "backend_lock": "molmospaces_mujoco",
            }
        ),
        encoding="utf-8",
    )
    (attempt_dir / "live_status.json").write_text(
        json.dumps({"phase": "running-sdk"}),
        encoding="utf-8",
    )
    (attempt_dir / "trace.jsonl").write_text(
        json.dumps({"event": "response", "tool": "observe", "ok": True}) + "\n{not-json}\n[]\n",
        encoding="utf-8",
    )

    state = derive_operator_state(tmp_path, run_dir, get_selection(MUJOCO_SDK_CLEANUP))

    assert state["phase"] == "failed"
    assert state["status"] == "failed"
    assert state["terminal_reason"] == "operator state source error: Trace"
    assert state["latest_action"] == "observe"
    assert [(error["label"], error["reason"]) for error in state["source_errors"]] == [
        ("Trace", "invalid JSON at line 2 column 2"),
        ("Trace", "expected JSON object at line 3"),
    ]
    assert state["checker_status"]["message"] == (
        "Launch failed: operator state source error: Trace"
    )


def test_state_camera_summary_uses_validated_trace_rows(tmp_path: Path) -> None:
    run_dir = tmp_path / "output" / "operator-console" / "runs" / "wrapper-run"
    attempt_dir = run_dir / "0619_1900" / "seed-7"
    attempt_dir.mkdir(parents=True)
    (run_dir / "operator_state.json").write_text(
        json.dumps(
            {
                "run_id": "wrapper-run",
                "route": get_selection(MUJOCO_SDK_CLEANUP).to_payload(),
                "phase": "starting",
                "backend_lock": "molmospaces_mujoco",
            }
        ),
        encoding="utf-8",
    )
    (attempt_dir / "live_status.json").write_text(
        json.dumps({"phase": "running-sdk"}),
        encoding="utf-8",
    )
    (attempt_dir / "trace.jsonl").write_text(
        json.dumps(
            {
                "event": "response",
                "tool": "adjust_camera",
                "response": {
                    "ok": True,
                    "status": "ok",
                    "camera_offset": {"yaw_delta_deg": 15.0, "pitch_delta_deg": -5.0},
                },
            }
        )
        + "\n{not-json}\n",
        encoding="utf-8",
    )

    state = derive_operator_state(tmp_path, run_dir, get_selection(MUJOCO_SDK_CLEANUP))

    assert state["phase"] == "failed"
    assert state["terminal_reason"] == "operator state source error: Trace"
    assert state["camera_state"]["summary"] == "yaw 15 deg, pitch -5 deg (active)"
    assert [(error["label"], error["reason"]) for error in state["source_errors"]] == [
        ("Trace", "invalid JSON at line 2 column 2")
    ]


def test_state_follows_nested_live_attempt_under_console_wrapper(tmp_path: Path) -> None:
    run_dir = tmp_path / "output" / "operator-console" / "runs" / "wrapper-run"
    attempt_dir = run_dir / "0608_1807" / "seed-7"
    attempt_dir.mkdir(parents=True)
    (run_dir / "operator_state.json").write_text(
        json.dumps(
            {
                "run_id": "wrapper-run",
                "route": get_selection(MUJOCO_SDK_CLEANUP).to_payload(),
                "phase": "starting",
                "backend_lock": "molmospaces_mujoco",
                "started_at_epoch": 1.0,
            }
        ),
        encoding="utf-8",
    )
    (run_dir / "console-launch.log").write_text("foreground sdk\n", encoding="utf-8")
    (attempt_dir / "live_status.json").write_text(
        json.dumps(
            {
                "phase": "running-sdk",
                "started_at_epoch": 2.0,
            }
        ),
        encoding="utf-8",
    )
    (attempt_dir / "trace.jsonl").write_text(
        json.dumps({"tool": "observe", "ok": True, "observation_summary": "plate visible"}) + "\n",
        encoding="utf-8",
    )
    (attempt_dir / "driver.log").write_text("==> OpenAI Agents SDK turn 2/9\n", encoding="utf-8")

    state = derive_operator_state(tmp_path, run_dir, get_selection(MUJOCO_SDK_CLEANUP))

    assert resolve_display_run_dir(run_dir) == attempt_dir.resolve()
    assert state["run_id"] == "wrapper-run"
    assert state["display_run_id"] == "0608_1807/seed-7"
    assert state["run_dir"] == str(run_dir.resolve())
    assert state["display_run_dir"] == str(attempt_dir.resolve())
    assert state["phase"] == "running-sdk"
    assert state["latest_action"] == "observe"
    assert state["latest_public_decision_evidence"]["observation_summary"] == "plate visible"
    assert any(
        item["label"] == "Driver Log" and "0608_1807" in item["path"]
        for item in state["artifact_paths"]
    )
    assert any(item["label"] == "Console Launch Log" for item in state["artifact_paths"])


def test_state_exposes_wrapper_level_runtime_prior_artifacts(tmp_path: Path) -> None:
    run_dir = tmp_path / "output" / "operator-console" / "runs" / "b1-wrapper-run"
    attempt_dir = run_dir / "0618_1015" / "seed-7"
    attempt_dir.mkdir(parents=True)
    (run_dir / "operator_state.json").write_text(
        json.dumps(
            {
                "run_id": "b1-wrapper-run",
                "route": get_selection(B1_OPENAI_AGENTS_OPEN_TASK).to_payload(),
                "phase": "starting",
                "backend_lock": "b1_isaaclab",
                "started_at_epoch": 1.0,
            }
        ),
        encoding="utf-8",
    )
    (run_dir / "runtime_map_prior_snapshot.json").write_text(
        '{"schema":"runtime_map_prior_snapshot_v1"}\n',
        encoding="utf-8",
    )
    (run_dir / "runtime_map_prior_targets.json").write_text(
        '{"schema":"runtime_map_prior_materialized_targets_v1"}\n',
        encoding="utf-8",
    )
    (run_dir / "b1_robot_consumption_manifest.json").write_text(
        '{"schema":"b1_map12_robot_consumption_manifest_v1"}\n',
        encoding="utf-8",
    )
    (attempt_dir / "live_status.json").write_text(
        json.dumps({"phase": "running-sdk"}),
        encoding="utf-8",
    )

    state = derive_operator_state(tmp_path, run_dir, get_selection(B1_OPENAI_AGENTS_OPEN_TASK))

    labels = {item["label"] for item in state["artifact_paths"]}
    assert "B1 Robot Consumption" in labels
    assert "Runtime Map Prior" in labels
    assert "Runtime Map Prior Targets" in labels
    assert next(
        item for item in state["artifact_paths"] if item["label"] == "B1 Robot Consumption"
    )["path"] == str((run_dir / "b1_robot_consumption_manifest.json").resolve())
    assert next(item for item in state["artifact_paths"] if item["label"] == "Runtime Map Prior")[
        "path"
    ] == str((run_dir / "runtime_map_prior_snapshot.json").resolve())


def test_state_marks_dead_live_status_owner_as_failed(tmp_path: Path, monkeypatch) -> None:
    run_dir = tmp_path / "output" / "operator-console" / "runs" / "wrapper-run"
    attempt_dir = run_dir / "0617_1606" / "seed-7"
    attempt_dir.mkdir(parents=True)
    dead_pid = 99999999
    (run_dir / "operator_state.json").write_text(
        json.dumps(
            {
                "run_id": "wrapper-run",
                "route": get_selection(MUJOCO_SDK_CLEANUP).to_payload(),
                "phase": "starting",
                "backend_lock": "molmospaces_mujoco",
                "started_at_epoch": 1.0,
            }
        ),
        encoding="utf-8",
    )
    (attempt_dir / "live_status.json").write_text(
        json.dumps(
            {
                "phase": "running-sdk",
                "started_at_epoch": 2.0,
                "visual_backend_slot": {"pid": dead_pid, "held": True},
            }
        ),
        encoding="utf-8",
    )
    (attempt_dir / "driver.log").write_text("==> OpenAI Agents SDK turn 1/1\n", encoding="utf-8")
    monkeypatch.setattr("roboclaws.operator_console.state.pid_is_active", lambda pid: False)

    state = derive_operator_state(tmp_path, run_dir, get_selection(MUJOCO_SDK_CLEANUP))

    assert state["phase"] == "failed"
    assert state["status"] == "failed"
    assert state["terminal_reason"] == "live runner process exited before terminal status"
    assert state["checker_status"]["status"] == "failed"
    assert state["checker_status"]["message"] == (
        "Launch failed: live runner process exited before terminal status"
    )


def test_state_summarizes_nested_mcp_trace_responses_for_live_decision(
    tmp_path: Path,
) -> None:
    run_dir = tmp_path / "output" / "operator-console" / "runs" / "wrapper-run"
    attempt_dir = run_dir / "0608_2103" / "seed-7"
    attempt_dir.mkdir(parents=True)
    (run_dir / "operator_state.json").write_text(
        json.dumps(
            {
                "run_id": "wrapper-run",
                "route": get_selection(MUJOCO_SDK_CLEANUP).to_payload(),
                "phase": "starting",
                "backend_lock": "molmospaces_mujoco",
                "started_at_epoch": 1.0,
            }
        ),
        encoding="utf-8",
    )
    (attempt_dir / "live_status.json").write_text(
        json.dumps({"phase": "running-sdk", "started_at_epoch": 2.0}),
        encoding="utf-8",
    )
    (attempt_dir / "trace.jsonl").write_text(
        json.dumps(
            {
                "event": "response",
                "tool": "navigate_to_waypoint",
                "request": {"waypoint_id": "generated_exploration_005"},
                "response": {
                    "ok": True,
                    "status": "ok",
                    "tool": "navigate_to_waypoint",
                    "waypoint_id": "generated_exploration_005",
                },
            }
        )
        + "\n",
        encoding="utf-8",
    )
    (attempt_dir / "openai-agents-events.jsonl").write_text(
        json.dumps(
            {
                "type": "item.completed",
                "item": {
                    "type": "agent_message",
                    "text": "Moving to waypoint 005 and continuing the sweep.",
                },
            }
        )
        + "\n",
        encoding="utf-8",
    )

    state = derive_operator_state(tmp_path, run_dir, get_selection(MUJOCO_SDK_CLEANUP))

    assert state["status"] == "running-sdk"
    assert state["latest_action"] == "navigate_to_waypoint"
    assert (
        state["latest_public_decision_evidence"]["observation_summary"]
        == "navigate_to_waypoint completed for waypoint_id=generated_exploration_005."
    )
    assert (
        state["latest_public_decision_evidence"]["decision"]
        == "Moving to waypoint 005 and continuing the sweep."
    )
    assert state["latest_tool_call"]["ok"] is True
    assert state["latest_tool_call"]["arguments"] == {"waypoint_id": "generated_exploration_005"}
    assert state["checker_status"]["status"] == "waiting"
    assert (
        state["checker_status"]["message"]
        == "Checker will run when the live agent hands off to result checking."
    )


def test_state_surfaces_malformed_agent_event_source_error(tmp_path: Path) -> None:
    run_dir = tmp_path / "output" / "operator-console" / "runs" / "wrapper-run"
    attempt_dir = run_dir / "0608_2110" / "seed-7"
    attempt_dir.mkdir(parents=True)
    (run_dir / "operator_state.json").write_text(
        json.dumps(
            {
                "run_id": "wrapper-run",
                "route": get_selection(MUJOCO_SDK_CLEANUP).to_payload(),
                "phase": "starting",
                "backend_lock": "molmospaces_mujoco",
            }
        ),
        encoding="utf-8",
    )
    (attempt_dir / "live_status.json").write_text(
        json.dumps({"phase": "running-sdk"}),
        encoding="utf-8",
    )
    (attempt_dir / "trace.jsonl").write_text(
        json.dumps({"event": "response", "tool": "observe", "ok": True}) + "\n",
        encoding="utf-8",
    )
    (attempt_dir / "openai-agents-events.jsonl").write_text(
        "{not-json}\n"
        + json.dumps(
            {
                "type": "item.completed",
                "item": {
                    "type": "agent_message",
                    "text": "I found a cup and will inspect it.",
                },
            }
        )
        + "\n",
        encoding="utf-8",
    )

    state = derive_operator_state(tmp_path, run_dir, get_selection(MUJOCO_SDK_CLEANUP))

    assert state["phase"] == "failed"
    assert state["status"] == "failed"
    assert state["terminal_reason"] == "operator state source error: Agent Events"
    assert state["latest_public_decision_evidence"]["decision"] == (
        "I found a cup and will inspect it."
    )
    assert [(error["label"], error["reason"]) for error in state["source_errors"]] == [
        ("Agent Events", "invalid JSON at line 1 column 2")
    ]


def test_state_pairs_split_request_response_tool_trace_for_latest_tool(
    tmp_path: Path,
) -> None:
    run_dir = tmp_path / "output" / "operator-console" / "runs" / "wrapper-run"
    attempt_dir = run_dir / "0609_1025" / "seed-7"
    attempt_dir.mkdir(parents=True)
    (run_dir / "operator_state.json").write_text(
        json.dumps(
            {
                "run_id": "wrapper-run",
                "route": get_selection(MUJOCO_SDK_CLEANUP).to_payload(),
                "phase": "starting",
                "backend_lock": "molmospaces_mujoco",
            }
        ),
        encoding="utf-8",
    )
    (attempt_dir / "live_status.json").write_text(
        json.dumps({"phase": "running-sdk"}),
        encoding="utf-8",
    )
    (attempt_dir / "trace.jsonl").write_text(
        json.dumps(
            {
                "event": "request",
                "tool": "navigate_to_waypoint",
                "request": {"waypoint_id": "generated_exploration_005"},
                "ts": 100.0,
            }
        )
        + "\n"
        + json.dumps(
            {
                "event": "response",
                "tool": "navigate_to_waypoint",
                "response": {
                    "ok": True,
                    "status": "ok",
                    "tool": "navigate_to_waypoint",
                    "waypoint_id": "generated_exploration_005",
                },
                "ts": 100.125,
            }
        )
        + "\n",
        encoding="utf-8",
    )

    state = derive_operator_state(tmp_path, run_dir, get_selection(MUJOCO_SDK_CLEANUP))

    assert state["latest_tool_call"] == {
        "name": "navigate_to_waypoint",
        "ok": True,
        "arguments": {"waypoint_id": "generated_exploration_005"},
        "latency_ms": 125.0,
        "error": "",
    }


def test_state_ignores_runtime_capture_when_selecting_latest_robot_tool(
    tmp_path: Path,
) -> None:
    run_dir = tmp_path / "output" / "operator-console" / "runs" / "wrapper-run"
    attempt_dir = run_dir / "0608_2103" / "seed-7"
    attempt_dir.mkdir(parents=True)
    (run_dir / "operator_state.json").write_text(
        json.dumps(
            {
                "run_id": "wrapper-run",
                "route": get_selection(MUJOCO_SDK_CLEANUP).to_payload(),
                "phase": "starting",
                "backend_lock": "molmospaces_mujoco",
            }
        ),
        encoding="utf-8",
    )
    (attempt_dir / "live_status.json").write_text(
        json.dumps({"phase": "running-sdk"}),
        encoding="utf-8",
    )
    (attempt_dir / "trace.jsonl").write_text(
        json.dumps(
            {
                "event": "response",
                "tool": "observe",
                "request": {},
                "response": {
                    "ok": True,
                    "status": "ok",
                    "tool": "observe",
                    "visible_object_detections": [{"object_id": "observed_004"}],
                },
            }
        )
        + "\n"
        + json.dumps(
            {
                "event": "robot_view_capture",
                "tool": "<runtime>",
                "action": "observe",
                "label": "0042_observe",
            }
        )
        + "\n",
        encoding="utf-8",
    )

    state = derive_operator_state(tmp_path, run_dir, get_selection(MUJOCO_SDK_CLEANUP))

    assert state["latest_action"] == "observe"
    assert (
        state["latest_public_decision_evidence"]["observation_summary"]
        == "observe completed with 1 visible detection(s)."
    )
    assert state["latest_tool_call"]["name"] == "observe"
    assert state["latest_tool_call"]["ok"] is True


def test_state_reports_camera_angles_and_navigation_reset(tmp_path: Path) -> None:
    run_dir = tmp_path / "output" / "operator-console" / "runs" / "wrapper-run"
    attempt_dir = run_dir / "0609_1110" / "seed-7"
    attempt_dir.mkdir(parents=True)
    (run_dir / "operator_state.json").write_text(
        json.dumps(
            {
                "run_id": "wrapper-run",
                "route": get_selection(MUJOCO_SDK_CLEANUP).to_payload(),
                "phase": "starting",
                "backend_lock": "molmospaces_mujoco",
            }
        ),
        encoding="utf-8",
    )
    (attempt_dir / "live_status.json").write_text(
        json.dumps({"phase": "running-sdk"}),
        encoding="utf-8",
    )
    (attempt_dir / "trace.jsonl").write_text(
        json.dumps(
            {
                "event": "request",
                "tool": "adjust_camera",
                "request": {"yaw_delta_deg": 0, "pitch_delta_deg": -10},
            }
        )
        + "\n"
        + json.dumps(
            {
                "event": "response",
                "tool": "adjust_camera",
                "response": {
                    "ok": True,
                    "status": "ok",
                    "camera_offset": {"yaw_delta_deg": 0.0, "pitch_delta_deg": -10.0},
                    "previous_camera_offset": {"yaw_delta_deg": 0.0, "pitch_delta_deg": 0.0},
                    "waypoint_id": "generated_exploration_001",
                },
            }
        )
        + "\n",
        encoding="utf-8",
    )

    state = derive_operator_state(tmp_path, run_dir, get_selection(MUJOCO_SDK_CLEANUP))

    assert state["camera_state"]["active"] is True
    assert state["camera_state"]["summary"] == "yaw 0 deg, pitch -10 deg (active)"
    assert state["camera_state"]["latest_adjust"]["requested_pitch_delta_deg"] == -10.0

    with (attempt_dir / "trace.jsonl").open("a", encoding="utf-8") as stream:
        stream.write(
            json.dumps(
                {
                    "event": "response",
                    "tool": "navigate_to_object",
                    "response": {"ok": True, "status": "ok", "object_id": "observed_001"},
                }
            )
            + "\n"
        )

    reset_state = derive_operator_state(tmp_path, run_dir, get_selection(MUJOCO_SDK_CLEANUP))

    assert reset_state["camera_state"]["active"] is False
    assert reset_state["camera_state"]["summary"] == "yaw 0 deg, pitch 0 deg (neutral)"
    assert reset_state["camera_state"]["latest_event"] == "navigate_to_object_reset"


def test_state_splits_semantic_map_from_top_down_scene_preview(
    tmp_path: Path,
) -> None:
    run_dir = tmp_path / "output" / "operator-console" / "runs" / "run"
    robot_views = run_dir / "robot_views"
    map_bundle = run_dir / "map_bundle"
    robot_views.mkdir(parents=True)
    map_bundle.mkdir()
    (run_dir / "operator_state.json").write_text(
        json.dumps(
            {
                "run_id": "run",
                "route": get_selection(MUJOCO_SDK_CLEANUP).to_payload(),
                "phase": "running",
                "backend_lock": "molmospaces_mujoco",
            }
        ),
        encoding="utf-8",
    )
    robot_map = robot_views / "0042_observe.map.png"
    robot_topdown = robot_views / "0042_observe.topdown.png"
    stale_report_map = map_bundle / "report_static_navigation_map.png"
    bundle_preview = map_bundle / "preview.png"
    semantic_map = run_dir / "semantic_map.png"
    robot_map.write_bytes(b"robot map")
    robot_topdown.write_bytes(b"robot topdown")
    stale_report_map.write_bytes(b"stale report map")
    bundle_preview.write_bytes(b"bundle preview")
    semantic_map.write_bytes(b"semantic map")
    runtime_preview = run_dir / "runtime_metric_map_preview.png"
    runtime_preview.write_bytes(b"runtime map preview")
    os.utime(robot_map, (1, 1))
    os.utime(robot_topdown, (4, 4))
    os.utime(stale_report_map, (2, 2))
    os.utime(bundle_preview, (3, 3))
    os.utime(semantic_map, (3, 3))
    os.utime(runtime_preview, (5, 5))
    (run_dir / "run_result.json").write_text(
        json.dumps(
            {
                "agent_view": {
                    "metric_map": {
                        "robot_pose": {
                            "frame_id": "map",
                            "x": 8.544,
                            "y": 6.408,
                            "yaw": 90.0,
                        }
                    }
                }
            }
        ),
        encoding="utf-8",
    )

    state = derive_operator_state(tmp_path, run_dir, get_selection(MUJOCO_SDK_CLEANUP))

    assert state["latest_view_assets"]["map"]["path"] == str(bundle_preview.resolve())
    assert state["latest_view_assets"]["map"]["visual_role"] == "base_metric_map_preview"
    assert state["latest_view_assets"]["map"]["artifact_source_family"] == (
        "base_metric_map_bundle"
    )
    assert state["latest_view_assets"]["runtime_map"]["path"] == str(runtime_preview.resolve())
    assert state["latest_view_assets"]["runtime_map"]["visual_role"] == (
        "runtime_metric_map_preview"
    )
    assert state["latest_view_assets"]["runtime_map"]["artifact_source_family"] == (
        "runtime_metric_map"
    )
    assert state["latest_view_assets"]["topdown"]["path"] == str(robot_topdown.resolve())
    assert state["latest_view_assets"]["topdown"]["visual_role"] == "topdown_scene_render"
    assert state["latest_view_assets"]["topdown"]["artifact_source_family"] == (
        "scene_camera_render"
    )
    assert state["latest_view_assets"]["map"]["href"].startswith("/artifacts/")
    assert "?v=" in state["latest_view_assets"]["map"]["href"]


def test_state_does_not_use_map_artifacts_as_top_down_scene_view(
    tmp_path: Path,
) -> None:
    run_dir = tmp_path / "output" / "operator-console" / "runs" / "run"
    run_dir.mkdir(parents=True)
    (run_dir / "operator_state.json").write_text(
        json.dumps(
            {
                "run_id": "run",
                "route": get_selection(MUJOCO_SDK_MAP_BUILD).to_payload(),
                "phase": "running",
                "backend_lock": "molmospaces_mujoco",
            }
        ),
        encoding="utf-8",
    )
    semantic_map = run_dir / "semantic_map.png"
    semantic_map.write_bytes(b"semantic map")

    state = derive_operator_state(tmp_path, run_dir, get_selection(MUJOCO_SDK_MAP_BUILD))

    assert "map" not in state["latest_view_assets"]
    assert "topdown" not in state["latest_view_assets"]


def test_state_does_not_synthesize_topdown_from_pose_trace(
    tmp_path: Path,
) -> None:
    run_dir = tmp_path / "output" / "operator-console" / "runs" / "run"
    run_dir.mkdir(parents=True)
    (run_dir / "operator_state.json").write_text(
        json.dumps(
            {
                "run_id": "run",
                "route": get_selection(MUJOCO_SDK_CLEANUP).to_payload(),
                "phase": "running",
                "backend_lock": "molmospaces_mujoco",
            }
        ),
        encoding="utf-8",
    )
    (run_dir / "trace.jsonl").write_text(
        json.dumps(
            {
                "event": "response",
                "tool": "navigate_to_waypoint",
                "response": {
                    "backend_pose_mutation": {
                        "robot_pose": {"x": 8.544, "y": 6.408, "theta": 1.570796}
                    }
                },
            }
        )
        + "\n"
        + json.dumps({"event": "response", "tool": "observe", "response": {"ok": True}})
        + "\n",
        encoding="utf-8",
    )

    state = derive_operator_state(tmp_path, run_dir, get_selection(MUJOCO_SDK_CLEANUP))

    assert "topdown" not in state["latest_view_assets"]


def test_state_uses_latest_grounding_overlay_as_fpv_when_available(
    tmp_path: Path,
) -> None:
    run_dir = tmp_path / "output" / "operator-console" / "runs" / "run"
    robot_views = run_dir / "robot_views"
    overlays = run_dir / "visual_grounding" / "overlays" / "raw_fpv_001"
    robot_views.mkdir(parents=True)
    overlays.mkdir(parents=True)
    (run_dir / "operator_state.json").write_text(
        json.dumps(
            {
                "run_id": "run",
                "route": get_selection(MUJOCO_SDK_CLEANUP).to_payload(),
                "phase": "running",
                "backend_lock": "molmospaces_mujoco",
            }
        ),
        encoding="utf-8",
    )
    raw_fpv = robot_views / "raw_fpv_001.fpv.png"
    first_overlay = overlays / "candidate_001.jpg"
    latest_overlay = overlays / "candidate_002.jpg"
    raw_fpv.write_bytes(b"raw fpv")
    first_overlay.write_bytes(b"first dino overlay")
    latest_overlay.write_bytes(b"latest dino overlay")
    os.utime(raw_fpv, (1, 1))
    os.utime(first_overlay, (2, 2))
    os.utime(latest_overlay, (3, 3))

    state = derive_operator_state(tmp_path, run_dir, get_selection(MUJOCO_SDK_CLEANUP))

    assert state["latest_view_assets"]["grounding"]["path"] == str(latest_overlay.resolve())
    assert state["latest_view_assets"]["fpv"]["path"] == str(latest_overlay.resolve())
    assert state["latest_view_assets"]["fpv"]["display_source"] == "visual_grounding_overlay"


def test_state_does_not_promote_report_bbox_images_as_grounding_overlay(
    tmp_path: Path,
) -> None:
    run_dir = tmp_path / "output" / "operator-console" / "runs" / "run"
    robot_views = run_dir / "robot_views"
    report_assets = run_dir / "report_assets"
    robot_views.mkdir(parents=True)
    report_assets.mkdir(parents=True)
    (run_dir / "operator_state.json").write_text(
        json.dumps(
            {
                "run_id": "run",
                "route": get_selection(MUJOCO_SDK_CLEANUP).to_payload(),
                "phase": "running",
                "backend_lock": "molmospaces_mujoco",
            }
        ),
        encoding="utf-8",
    )
    raw_fpv = robot_views / "raw_fpv_001.fpv.png"
    report_bbox = report_assets / "raw_fpv_001.bbox.png"
    raw_fpv.write_bytes(b"raw fpv")
    report_bbox.write_bytes(b"report bbox")
    os.utime(raw_fpv, (1, 1))
    os.utime(report_bbox, (3, 3))

    state = derive_operator_state(tmp_path, run_dir, get_selection(MUJOCO_SDK_CLEANUP))

    assert state["latest_view_assets"]["fpv"]["path"] == str(raw_fpv.resolve())
    assert "display_source" not in state["latest_view_assets"]["fpv"]
    assert "grounding" not in state["latest_view_assets"]


def test_state_surfaces_provider_transient_reason(tmp_path: Path) -> None:
    run_dir = tmp_path / "output" / "operator-console" / "runs" / "wrapper-run"
    attempt_dir = run_dir / "0608_1921" / "seed-7"
    attempt_dir.mkdir(parents=True)
    (run_dir / "operator_state.json").write_text(
        json.dumps(
            {
                "run_id": "wrapper-run",
                "route": get_selection(MUJOCO_SDK_CLEANUP).to_payload(),
                "phase": "starting",
                "backend_lock": "molmospaces_mujoco",
            }
        ),
        encoding="utf-8",
    )
    (attempt_dir / "live_status.json").write_text(
        json.dumps(
            {
                "phase": "failed",
                "exit_status": 1,
                "reason": "provider_transient_failure",
                "provider_reason": "rate_limit",
                "retryable": True,
                "resume_available": True,
            }
        ),
        encoding="utf-8",
    )

    state = derive_operator_state(tmp_path, run_dir, get_selection(MUJOCO_SDK_CLEANUP))

    assert state["phase"] == "failed"
    assert state["status"] == "provider_transient_failed"
    assert state["status_label"] == "Provider transient failure"
    assert state["terminal_reason"] == "provider_transient_failure"


def test_state_treats_cleanup_status_success_as_passed(tmp_path: Path) -> None:
    run_dir = tmp_path / "output" / "operator-console" / "runs" / "wrapper-run"
    attempt_dir = run_dir / "0608_2017" / "seed-7"
    attempt_dir.mkdir(parents=True)
    (run_dir / "operator_state.json").write_text(
        json.dumps(
            {
                "run_id": "wrapper-run",
                "route": get_selection(MUJOCO_SDK_CLEANUP).to_payload(),
                "phase": "starting",
                "backend_lock": "molmospaces_mujoco",
            }
        ),
        encoding="utf-8",
    )
    (attempt_dir / "live_status.json").write_text(
        json.dumps({"phase": "finished", "exit_status": 0}),
        encoding="utf-8",
    )
    (attempt_dir / "run_result.json").write_text(
        json.dumps(
            {
                "cleanup_status": "success",
                "completion_status": "success",
                "final_status": "success",
                "score": {
                    "completion_status": "success",
                    "status": "success",
                },
            }
        ),
        encoding="utf-8",
    )
    (attempt_dir / "report.html").write_text("<html></html>", encoding="utf-8")

    state = derive_operator_state(tmp_path, run_dir, get_selection(MUJOCO_SDK_CLEANUP))

    assert state["status"] == "passed"
    assert state["checker_status"]["status"] == "passed"
    assert state["public_run_result"]["cleanup_status"] == "success"


def test_state_treats_open_ended_cleanup_score_failure_as_advisory(
    tmp_path: Path,
) -> None:
    run_dir = tmp_path / "output" / "operator-console" / "runs" / "wrapper-run"
    attempt_dir = run_dir / "0611_1232" / "seed-7"
    route = get_selection(B1_OPENAI_AGENTS_OPEN_TASK)
    attempt_dir.mkdir(parents=True)
    (run_dir / "operator_state.json").write_text(
        json.dumps(
            {
                "run_id": "wrapper-run",
                "route": route.to_payload(),
                "phase": "starting",
                "backend_lock": route.lock_name,
            }
        ),
        encoding="utf-8",
    )
    (attempt_dir / "live_status.json").write_text(
        json.dumps({"phase": "finished", "exit_status": 0}),
        encoding="utf-8",
    )
    (attempt_dir / "run_result.json").write_text(
        json.dumps(
            {
                "task_intent": "open-ended",
                "goal_contract": {"intent": "open-ended"},
                "cleanup_status": "failed",
                "completion_status": "failed",
                "final_status": "failed",
                "score": {
                    "status": "success",
                    "completion_status": "failed",
                    "total_targets": 0,
                    "sweep_coverage_rate": 1.0,
                },
            }
        ),
        encoding="utf-8",
    )
    (attempt_dir / "report.html").write_text("<html></html>", encoding="utf-8")
    (attempt_dir / "checker.log").write_text("molmo-realworld-cleanup ok\n", encoding="utf-8")

    state = derive_operator_state(tmp_path, run_dir, route)

    assert state["status"] == "passed"
    assert state["checker_status"]["status"] == "passed"
    assert state["checker_status"]["message"] == "Checker passed."
    assert state["public_run_result"]["cleanup_status"] == "failed"


def test_state_keeps_cleanup_score_failure_authoritative_for_cleanup(
    tmp_path: Path,
) -> None:
    run_dir = tmp_path / "output" / "operator-console" / "runs" / "wrapper-run"
    attempt_dir = run_dir / "0611_1232" / "seed-7"
    route = get_selection(MUJOCO_SDK_CLEANUP)
    attempt_dir.mkdir(parents=True)
    (run_dir / "operator_state.json").write_text(
        json.dumps(
            {
                "run_id": "wrapper-run",
                "route": route.to_payload(),
                "phase": "starting",
                "backend_lock": route.lock_name,
            }
        ),
        encoding="utf-8",
    )
    (attempt_dir / "live_status.json").write_text(
        json.dumps({"phase": "finished", "exit_status": 0}),
        encoding="utf-8",
    )
    (attempt_dir / "run_result.json").write_text(
        json.dumps(
            {
                "task_intent": "cleanup",
                "cleanup_status": "failed",
                "completion_status": "failed",
                "final_status": "failed",
                "score": {
                    "status": "success",
                    "completion_status": "failed",
                    "total_targets": 0,
                    "sweep_coverage_rate": 1.0,
                },
            }
        ),
        encoding="utf-8",
    )
    (attempt_dir / "report.html").write_text("<html></html>", encoding="utf-8")
    (attempt_dir / "checker.log").write_text("molmo-realworld-cleanup ok\n", encoding="utf-8")

    state = derive_operator_state(tmp_path, run_dir, route)

    assert state["status"] == "idle"
    assert state["checker_status"]["status"] == "failed"
    assert state["checker_status"]["message"] == "Checker failed. Open Checker Output for details."


def test_state_keeps_failed_phase_when_result_contains_success(tmp_path: Path) -> None:
    run_dir = tmp_path / "output" / "operator-console" / "runs" / "wrapper-run"
    attempt_dir = run_dir / "0609_1025" / "seed-7"
    attempt_dir.mkdir(parents=True)
    (run_dir / "operator_state.json").write_text(
        json.dumps(
            {
                "run_id": "wrapper-run",
                "route": get_selection(MUJOCO_SDK_CLEANUP).to_payload(),
                "phase": "starting",
                "backend_lock": "molmospaces_mujoco",
            }
        ),
        encoding="utf-8",
    )
    (attempt_dir / "live_status.json").write_text(
        json.dumps(
            {
                "phase": "failed",
                "exit_status": 1,
                "reason": "cleanup checker exited with status 1",
            }
        ),
        encoding="utf-8",
    )
    (attempt_dir / "run_result.json").write_text(
        json.dumps(
            {
                "cleanup_status": "success",
                "score": {"status": "success"},
                "agent_diagnostics": {"fridge_inside_sequence_ok": False},
            }
        ),
        encoding="utf-8",
    )
    (attempt_dir / "report.html").write_text("<html></html>", encoding="utf-8")
    (attempt_dir / "checker.log").write_text("checker failed\n", encoding="utf-8")

    state = derive_operator_state(tmp_path, run_dir, get_selection(MUJOCO_SDK_CLEANUP))

    assert state["status"] == "failed"
    assert state["checker_status"]["status"] == "failed"
    assert state["checker_status"]["reason"] == (
        "fridge cleanup sequence incomplete; call close_receptacle with the same "
        "fridge fixture_id after place_inside before moving on or done."
    )
    assert state["checker_status"]["message"].startswith(
        "Checker failed: fridge cleanup sequence incomplete"
    )
    assert state["terminal_reason"] == "cleanup checker exited with status 1"
    assert state["controls"]["stop_available"] is False


def test_state_allows_stop_to_release_lock_for_failed_terminal_run(tmp_path: Path) -> None:
    run_dir = tmp_path / "output" / "operator-console" / "runs" / "wrapper-run"
    attempt_dir = run_dir / "0609_1025" / "seed-7"
    route = get_selection(MUJOCO_SDK_CLEANUP)
    attempt_dir.mkdir(parents=True)
    (run_dir / "operator_state.json").write_text(
        json.dumps(
            {
                "run_id": "wrapper-run",
                "route": route.to_payload(),
                "phase": "starting",
                "backend_lock": route.lock_name,
            }
        ),
        encoding="utf-8",
    )
    (attempt_dir / "live_status.json").write_text(
        json.dumps(
            {
                "phase": "failed",
                "exit_status": 1,
                "reason": "cleanup checker exited with status 1",
            }
        ),
        encoding="utf-8",
    )
    (attempt_dir / "run_result.json").write_text(
        json.dumps(
            {
                "cleanup_status": "success",
                "agent_diagnostics": {"fridge_inside_sequence_ok": False},
            }
        ),
        encoding="utf-8",
    )
    (attempt_dir / "checker.log").write_text("checker failed\n", encoding="utf-8")
    ResourceLock(tmp_path, route.lock_name).acquire(run_id="wrapper-run", pid=12345)

    state = derive_operator_state(tmp_path, run_dir, route)

    assert state["status"] == "failed"
    assert state["checker_status"]["status"] == "failed"
    assert state["controls"]["stop_available"] is True


def test_state_keeps_manual_control_available_for_paused_handoff_attempt(
    tmp_path: Path,
) -> None:
    run_dir = tmp_path / "output" / "operator-console" / "runs" / "wrapper-run"
    attempt_dir = run_dir / "0617_1126" / "seed-7"
    route = get_selection(B1_OPENAI_AGENTS_OPEN_TASK)
    attempt_dir.mkdir(parents=True)
    (run_dir / "operator_state.json").write_text(
        json.dumps(
            {
                "run_id": "wrapper-run",
                "route": route.to_payload(),
                "phase": "starting",
                "backend_lock": route.lock_name,
                "mcp_url": "http://127.0.0.1:18788/mcp",
            }
        ),
        encoding="utf-8",
    )
    (attempt_dir / "live_status.json").write_text(
        json.dumps(
            {
                "phase": "paused",
                "reason": "operator_handoff_requested",
                "resume_available": True,
            }
        ),
        encoding="utf-8",
    )
    (attempt_dir / "server.pid").write_text("12345\n", encoding="utf-8")
    (attempt_dir / "trace.jsonl").write_text(
        json.dumps(
            {
                "event": "response",
                "tool": "navigate_to_waypoint",
                "response": {"ok": True, "waypoint_id": "generated_exploration_001"},
            }
        )
        + "\n",
        encoding="utf-8",
    )

    state = derive_operator_state(tmp_path, run_dir, route)

    assert state["phase"] == "paused"
    assert state["status"] == "paused"
    assert state["terminal_reason"] == "operator_handoff_requested"
    assert state["operator_handoff_paused"] is True
    assert state["live_resume_available"] is True
    assert state["latest_action"] == "navigate_to_waypoint"
    assert state["controls"]["relative_navigation_control_available"] is True
    assert state["controls"]["next_goal_available"] is False
    assert state["controls"]["steer_available"] is False
    assert state["controls"]["resume_available"] is True
    assert state["controls"]["supports_paused_handoff_resume"] is True


def test_state_holds_manual_control_until_live_mcp_phase_is_ready(
    tmp_path: Path,
) -> None:
    run_dir = tmp_path / "output" / "operator-console" / "runs" / "wrapper-run"
    route = get_selection(B1_OPENAI_AGENTS_OPEN_TASK)
    run_dir.mkdir(parents=True)
    (run_dir / "operator_state.json").write_text(
        json.dumps(
            {
                "run_id": "wrapper-run",
                "route": route.to_payload(),
                "phase": "starting",
                "backend_lock": route.lock_name,
                "mcp_url": "http://127.0.0.1:18788/mcp",
            }
        ),
        encoding="utf-8",
    )

    state = derive_operator_state(tmp_path, run_dir, route)

    assert state["phase"] == "starting"
    assert state["controls"]["relative_navigation_control_available"] is False
    assert state["controls"]["relative_navigation_control_pending"] is True
    assert state["controls"]["next_goal_available"] is False


def test_state_reports_blocked_resume_for_paused_handoff_without_runner_support(
    tmp_path: Path,
) -> None:
    run_dir = tmp_path / "output" / "operator-console" / "runs" / "wrapper-run"
    attempt_dir = run_dir / "0617_1126" / "seed-7"
    route = get_selection(
        "agibot-g2/map-12::agibot-gdk::map-build::openai-agents-sdk::camera-grounded-labels"
    )
    attempt_dir.mkdir(parents=True)
    (run_dir / "operator_state.json").write_text(
        json.dumps(
            {
                "run_id": "wrapper-run",
                "route": route.to_payload(),
                "phase": "starting",
                "backend_lock": route.lock_name,
            }
        ),
        encoding="utf-8",
    )
    (attempt_dir / "live_status.json").write_text(
        json.dumps(
            {
                "phase": "paused",
                "reason": "operator_handoff_requested",
                "resume_available": True,
            }
        ),
        encoding="utf-8",
    )

    state = derive_operator_state(tmp_path, run_dir, route)

    assert state["operator_handoff_paused"] is True
    assert state["live_resume_available"] is True
    assert state["controls"]["steer_available"] is False
    assert state["controls"]["resume_available"] is False
    assert state["controls"]["resume_blocked"] is True
    assert state["controls"]["supports_paused_handoff_resume"] is False


def test_state_summarizes_checker_log_failure_when_structured_diagnostic_missing(
    tmp_path: Path,
) -> None:
    run_dir = tmp_path / "output" / "operator-console" / "runs" / "wrapper-run"
    attempt_dir = run_dir / "0609_1030" / "seed-7"
    attempt_dir.mkdir(parents=True)
    (run_dir / "operator_state.json").write_text(
        json.dumps(
            {
                "run_id": "wrapper-run",
                "route": get_selection(MUJOCO_SDK_CLEANUP).to_payload(),
                "phase": "starting",
                "backend_lock": "molmospaces_mujoco",
            }
        ),
        encoding="utf-8",
    )
    (attempt_dir / "live_status.json").write_text(
        json.dumps({"phase": "failed", "exit_status": 1}),
        encoding="utf-8",
    )
    (attempt_dir / "run_result.json").write_text(
        json.dumps({"cleanup_status": "success"}),
        encoding="utf-8",
    )
    (attempt_dir / "report.html").write_text("<html></html>", encoding="utf-8")
    (attempt_dir / "checker.log").write_text(
        "AssertionError: {'agent_diagnostics': {'fridge_inside_sequence_ok': False}}\n",
        encoding="utf-8",
    )

    state = derive_operator_state(tmp_path, run_dir, get_selection(MUJOCO_SDK_CLEANUP))

    assert state["checker_status"]["status"] == "failed"
    assert state["checker_status"]["message"] == (
        "Checker failed: fridge cleanup sequence incomplete; call close_receptacle with "
        "the same fridge fixture_id after place_inside before moving on or done."
    )


def test_state_surfaces_openai_agents_artifacts(tmp_path: Path) -> None:
    run_dir = tmp_path / "output" / "operator-console" / "runs" / "sdk-run"
    run_dir.mkdir(parents=True)
    (run_dir / "operator_state.json").write_text(
        json.dumps(
            {
                "run_id": "sdk-run",
                "route": get_selection(MUJOCO_SDK_CLEANUP).to_payload(),
                "phase": "starting",
                "backend_lock": "molmospaces_mujoco",
            }
        ),
        encoding="utf-8",
    )
    (run_dir / "live_status.json").write_text(
        json.dumps({"phase": "running-sdk"}),
        encoding="utf-8",
    )
    (run_dir / "openai-agents-events.jsonl").write_text('{"event":"result"}\n', encoding="utf-8")
    (run_dir / "openai-agents-trace.json").write_text('{"trace_id":"trace_1"}\n', encoding="utf-8")

    state = derive_operator_state(tmp_path, run_dir, get_selection(MUJOCO_SDK_CLEANUP))

    assert state["status"] == "running-sdk"
    labels = {item["label"] for item in state["artifact_paths"]}
    assert "Agent Events" in labels
    assert "OpenAI Agents Trace" in labels


def test_redacted_artifact_text_redacts_secrets(tmp_path: Path) -> None:
    log = tmp_path / "driver.log"
    log.write_text("Authorization: Bearer top-secret\n", encoding="utf-8")
    assert "top-secret" not in redacted_artifact_text(log)


def test_redacted_artifact_text_truncates_with_tail_visible(tmp_path: Path) -> None:
    log = tmp_path / "driver.log"
    log.write_text(
        "start\n" + ("middle\n" * 20) + "final molmospaces import error\n",
        encoding="utf-8",
    )

    text = redacted_artifact_text(log, max_bytes=80)

    assert "start" in text
    assert "operator console truncated" in text
    assert "final molmospaces import error" in text
