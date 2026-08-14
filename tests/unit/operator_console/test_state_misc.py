from __future__ import annotations

import json
from pathlib import Path

from roboclaws.operator_console.routes import get_selection
from roboclaws.operator_console.state import (
    derive_operator_state,
    resolve_display_run_dir,
)
from tests.unit.operator_console.conftest import (  # noqa: F401  re-exported for tests
    B1_OPENAI_AGENTS_OPEN_TASK,
    MUJOCO_SDK_CLEANUP,
    MUJOCO_SDK_MAP_BUILD,
)


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
