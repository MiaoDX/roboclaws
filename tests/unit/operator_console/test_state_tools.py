from __future__ import annotations

import json
from pathlib import Path

from roboclaws.operator_console.routes import get_selection
from roboclaws.operator_console.state import (
    derive_operator_state,
    redacted_artifact_text,
)
from tests.unit.operator_console.conftest import (  # noqa: F401  re-exported for tests
    B1_OPENAI_AGENTS_OPEN_TASK,
    MUJOCO_SDK_CLEANUP,
    MUJOCO_SDK_MAP_BUILD,
)


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
