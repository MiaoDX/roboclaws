from __future__ import annotations

import json
import socket
from pathlib import Path

import pytest

from roboclaws.operator_console.launcher import route_readiness
from roboclaws.operator_console.locks import ResourceLock
from roboclaws.operator_console.paths import console_output_root
from roboclaws.operator_console.routes import get_selection
from roboclaws.operator_console.state import derive_operator_state
from tests.support.b1_robot_proof import write_b1_readiness_fixtures
from tests.unit.operator_console.conftest import (
    B1_OPENAI_AGENTS_OPEN_TASK,  # noqa: F401  re-exported for tests
    MUJOCO_OPENAI_AGENTS_OPEN_TASK,
    MUJOCO_SDK_MAP_BUILD,
)

KIMI_ENV = {
    "KIMI_OPENAI_BASE_URL": "https://kimi.example.test/v1",
    "KIMI_API_KEY": "key",
}


def test_state_marks_dead_wrapper_launch_without_live_artifacts_failed(
    tmp_path: Path, monkeypatch
) -> None:
    route = get_selection(B1_OPENAI_AGENTS_OPEN_TASK)
    run_dir = tmp_path / "output" / "operator-console" / "runs" / "wrapper-run"
    run_dir.mkdir(parents=True)
    _write_operator_state(
        run_dir,
        run_id="wrapper-run",
        route_payload=route.to_payload(),
        backend_lock=route.lock_name,
    )
    (run_dir / "console-launch.log").write_text(
        "==> Molmo cleanup matrix\n"
        "error: another non-Molmo live cleanup run appears to be active\n"
        "error: recipe `surface` failed with exit code 1\n",
        encoding="utf-8",
    )
    monkeypatch.setattr("roboclaws.operator_console.state.pid_is_active", lambda pid: False)

    state = derive_operator_state(tmp_path, run_dir, route)

    assert state["phase"] == "failed"
    assert state["status"] == "failed"
    assert state["terminal_reason"] == "another non-Molmo live cleanup run appears to be active"
    assert state["checker_status"]["status"] == "failed"
    assert state["checker_status"]["message"] == (
        "Launch failed: another non-Molmo live cleanup run appears to be active"
    )
    assert any(item["label"] == "Console Launch Log" for item in state["artifact_paths"])


def test_state_prefers_terminal_direct_result_over_wrapper_starting_phase(tmp_path: Path) -> None:
    route = get_selection(MUJOCO_SDK_MAP_BUILD)
    run_dir = tmp_path / "output" / "operator-console" / "runs" / "direct-run"
    run_dir.mkdir(parents=True)
    (run_dir / "operator_state.json").write_text(
        json.dumps({"run_id": "direct-run", "route": route.to_payload(), "phase": "starting"}),
        encoding="utf-8",
    )
    (run_dir / "run_result.json").write_text(
        json.dumps(
            {
                "task_intent": "map-build",
                "completion_status": "failed",
                "score": {"status": "success"},
                "terminate_reason": "map build complete",
            }
        ),
        encoding="utf-8",
    )
    (run_dir / "report.html").write_text("<html></html>", encoding="utf-8")

    state = derive_operator_state(tmp_path, run_dir, route)

    assert state["phase"] == "finished"
    assert state["status"] == "passed"
    assert state["terminal_reason"] == "map build complete"


def test_readiness_does_not_block_on_zombie_wrapper_lock(tmp_path: Path, monkeypatch) -> None:
    route = get_selection(B1_OPENAI_AGENTS_OPEN_TASK)
    b1_overrides = write_b1_readiness_fixtures(tmp_path)
    run_id = "zombie-wrapper-run"
    run_dir = console_output_root(tmp_path) / "runs" / run_id
    run_dir.mkdir(parents=True)
    _write_operator_state(
        run_dir,
        run_id=run_id,
        route_payload=route.to_payload(),
        backend_lock=route.lock_name,
        persisted_run_dir=run_dir,
    )
    ResourceLock(tmp_path, route.lock_name).acquire(run_id=run_id, pid=999_999_999)

    readiness = route_readiness(
        tmp_path,
        route,
        overrides={"port": _free_port(), **b1_overrides},
        env=KIMI_ENV,
    )

    assert readiness["can_start"] is True
    assert readiness["blocker_kind"] == ""
    assert readiness["attachable_run"] is None


@pytest.mark.parametrize("phase", ["done", "emergency_stopped"])
def test_readiness_releases_terminal_lock_without_exit_status(
    tmp_path: Path,
    phase: str,
) -> None:
    route = get_selection(MUJOCO_OPENAI_AGENTS_OPEN_TASK)
    run_id = f"{phase}-run"
    run_dir = console_output_root(tmp_path) / "runs" / run_id
    run_dir.mkdir(parents=True)
    _write_operator_state(
        run_dir,
        run_id=run_id,
        route_payload=route.to_payload(),
        backend_lock=route.lock_name,
        persisted_run_dir=run_dir,
        phase=phase,
    )
    ResourceLock(tmp_path, route.lock_name).acquire(run_id=run_id, pid=999_999_999)

    readiness = route_readiness(
        tmp_path,
        route,
        overrides={"port": _free_port()},
        env=KIMI_ENV,
    )

    assert readiness["can_start"] is True
    assert readiness["attachable_run"] is None
    assert ResourceLock(tmp_path, route.lock_name).read().held is False


def _write_operator_state(
    state_dir: Path,
    *,
    run_id: str,
    route_payload: dict[str, object],
    backend_lock: str,
    persisted_run_dir: Path | None = None,
    phase: str = "starting",
) -> None:
    state: dict[str, object] = {
        "run_id": run_id,
        "route": route_payload,
        "phase": phase,
        "pid": 999_999_999,
        "backend_lock": backend_lock,
        "started_at_epoch": 1.0,
    }
    if persisted_run_dir is not None:
        state["run_dir"] = str(persisted_run_dir)
    (state_dir / "operator_state.json").write_text(json.dumps(state), encoding="utf-8")


def _free_port() -> str:
    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        return str(listener.getsockname()[1])
