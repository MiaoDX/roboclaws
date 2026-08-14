from __future__ import annotations

import json
from pathlib import Path

from roboclaws.operator_console.locks import ResourceLock
from roboclaws.operator_console.routes import get_selection
from roboclaws.operator_console.state import (
    derive_operator_state,
)
from tests.unit.operator_console.conftest import (  # noqa: F401  re-exported for tests
    B1_OPENAI_AGENTS_OPEN_TASK,
    MUJOCO_SDK_CLEANUP,
    MUJOCO_SDK_MAP_BUILD,
)


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
    (attempt_dir / "checker.log").write_text("household-world ok\n", encoding="utf-8")

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
    (attempt_dir / "checker.log").write_text("household-world ok\n", encoding="utf-8")

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
