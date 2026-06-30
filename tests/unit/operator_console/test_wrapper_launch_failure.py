from __future__ import annotations

import json
import socket
from pathlib import Path

from roboclaws.operator_console.launcher import route_readiness
from roboclaws.operator_console.locks import ResourceLock
from roboclaws.operator_console.paths import console_output_root
from roboclaws.operator_console.routes import get_selection
from roboclaws.operator_console.state import derive_operator_state
from tests.support.b1_robot_proof import write_b1_robot_proof_artifacts

from tests.unit.operator_console.conftest import B1_OPENAI_AGENTS_OPEN_TASK  # noqa: F401  re-exported for tests

CODEX_ENV = {
    "CODEX_BASE_URL": "https://codex.example.test/v1",
    "CODEX_API_KEY": "key",
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


def test_readiness_does_not_block_on_zombie_wrapper_lock(tmp_path: Path, monkeypatch) -> None:
    route = get_selection(B1_OPENAI_AGENTS_OPEN_TASK)
    write_b1_robot_proof_artifacts(tmp_path)
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
    ResourceLock(tmp_path, route.lock_name).acquire(run_id=run_id, pid=12345)
    monkeypatch.setattr("roboclaws.operator_console.locks.pid_is_active", lambda pid: False)

    readiness = route_readiness(
        tmp_path,
        route,
        overrides={"port": _free_port()},
        env=CODEX_ENV,
    )

    assert readiness["can_start"] is True
    assert readiness["blocker_kind"] == ""
    assert readiness["attachable_run"] is None


def _write_operator_state(
    state_dir: Path,
    *,
    run_id: str,
    route_payload: dict[str, object],
    backend_lock: str,
    persisted_run_dir: Path | None = None,
) -> None:
    state: dict[str, object] = {
        "run_id": run_id,
        "route": route_payload,
        "phase": "starting",
        "pid": 12345,
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
