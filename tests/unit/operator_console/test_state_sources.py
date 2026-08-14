from __future__ import annotations

import json
from pathlib import Path

from roboclaws.operator_console.routes import get_selection
from roboclaws.operator_console.state import (
    derive_operator_state,
)
from tests.unit.operator_console.conftest import (  # noqa: F401  re-exported for tests
    B1_OPENAI_AGENTS_OPEN_TASK,
    MUJOCO_SDK_CLEANUP,
    MUJOCO_SDK_MAP_BUILD,
)


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
