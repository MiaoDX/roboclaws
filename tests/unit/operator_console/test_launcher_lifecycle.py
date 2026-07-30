from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

from roboclaws.operator_console.launcher import (
    _terminate_process_group,
    stop_console_run,
)
from roboclaws.operator_console.locks import ResourceLock
from roboclaws.operator_console.paths import console_output_root
from roboclaws.operator_console.routes import get_selection
from tests.unit.operator_console.conftest import (  # noqa: F401  re-exported for tests
    AGIBOT_SDK_MAP_BUILD,
    B1_OPENAI_AGENTS_CAMERA_GROUNDED,
    B1_OPENAI_AGENTS_OPEN_TASK,
    MUJOCO_OPENAI_AGENTS_OPEN_TASK,
    MUJOCO_SDK_CLEANUP,
)


def test_stop_console_run_targets_nested_live_attempt(tmp_path: Path) -> None:
    route = get_selection(MUJOCO_OPENAI_AGENTS_OPEN_TASK)
    run_id = "wrapper-run"
    wrapper_pid = 123450
    server_pid = 123451
    run_dir = console_output_root(tmp_path) / "runs" / run_id
    attempt_dir = run_dir / "0608_1807" / "seed-7"
    attempt_dir.mkdir(parents=True)
    (run_dir / "operator_state.json").write_text(
        json.dumps(
            {
                "run_id": run_id,
                "route": route.to_payload(),
                "phase": "starting",
                "pid": wrapper_pid,
                "backend_lock": route.lock_name,
                "run_dir": str(run_dir),
            }
        ),
        encoding="utf-8",
    )
    (attempt_dir / "live_status.json").write_text(
        json.dumps({"phase": "running-sdk"}),
        encoding="utf-8",
    )
    (attempt_dir / "server.pid").write_text(f"{server_pid}\n", encoding="utf-8")
    (attempt_dir / "tmux_session.txt").write_text("roboclaws-test\n", encoding="utf-8")
    ResourceLock(tmp_path, route.lock_name).acquire(run_id=run_id, pid=wrapper_pid)

    killed_pids: list[int] = []
    tmux_commands: list[list[str]] = []

    def fake_run(command, **kwargs):  # noqa: ANN001, ANN003, ANN202
        del kwargs
        tmux_commands.append(list(command))

        class Result:
            returncode = 0

        return Result()

    with (
        patch("roboclaws.operator_console.launcher._process_parent_pid") as parent_pid,
        patch("roboclaws.operator_console.launcher._descendant_pids") as descendant_pids,
        patch("roboclaws.operator_console.launcher.os.getpgid", side_effect=lambda pid: pid),
        patch("roboclaws.operator_console.launcher.os.killpg") as killpg,
        patch("roboclaws.operator_console.launcher.subprocess.run", side_effect=fake_run),
    ):
        parent_pid.return_value = wrapper_pid
        descendant_pids.return_value = [server_pid]
        killpg.side_effect = lambda pid, signal: killed_pids.append(pid)
        state = stop_console_run(tmp_path, run_id)

    assert state["phase"] == "stopped_by_operator"
    assert state["display_run_dir"] == str(attempt_dir.resolve())
    assert server_pid in killed_pids
    assert wrapper_pid in killed_pids
    assert ["tmux", "kill-session", "-t", "roboclaws-test"] in tmux_commands
    live_status = json.loads((attempt_dir / "live_status.json").read_text(encoding="utf-8"))
    assert live_status["phase"] == "stopped_by_operator"
    assert live_status["exit_status"] == 130
    assert ResourceLock(tmp_path, route.lock_name).read().held is False


def test_stop_console_run_releases_failed_terminal_lock_without_relabeling_failure(
    tmp_path: Path,
) -> None:
    route = get_selection(MUJOCO_OPENAI_AGENTS_OPEN_TASK)
    run_id = "failed-wrapper-run"
    run_dir = console_output_root(tmp_path) / "runs" / run_id
    attempt_dir = run_dir / "0609_1025" / "seed-7"
    attempt_dir.mkdir(parents=True)
    (run_dir / "operator_state.json").write_text(
        json.dumps(
            {
                "run_id": run_id,
                "route": route.to_payload(),
                "phase": "starting",
                "pid": 123450,
                "backend_lock": route.lock_name,
                "run_dir": str(run_dir),
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
    ResourceLock(tmp_path, route.lock_name).acquire(run_id=run_id, pid=123450)

    with (
        patch("roboclaws.operator_console.launcher._stop_live_child_run") as stop_child,
        patch("roboclaws.operator_console.launcher._terminate_process_group") as stop_wrapper,
    ):
        state = stop_console_run(tmp_path, run_id)

    assert state["phase"] == "failed"
    assert state["terminal_reason"] == "cleanup checker exited with status 1"
    assert state["display_run_dir"] == str(attempt_dir.resolve())
    stop_child.assert_called_once_with(attempt_dir.resolve())
    stop_wrapper.assert_called_once_with(123450)
    assert ResourceLock(tmp_path, route.lock_name).read().held is False
    live_status = json.loads((attempt_dir / "live_status.json").read_text(encoding="utf-8"))
    assert live_status["phase"] == "failed"
    assert live_status["exit_status"] == 1


def test_stop_console_run_never_invokes_docker_for_attempt_workspace(
    tmp_path: Path,
) -> None:
    route = get_selection(MUJOCO_OPENAI_AGENTS_OPEN_TASK)
    run_id = "wrapper-run"
    wrapper_pid = 123450
    server_pid = 123451
    run_dir = console_output_root(tmp_path) / "runs" / run_id
    attempt_dir = run_dir / "0608_1807" / "seed-7"
    workspace = attempt_dir / "agent-docker-workspace"
    workspace.mkdir(parents=True)
    (run_dir / "operator_state.json").write_text(
        json.dumps(
            {
                "run_id": run_id,
                "route": route.to_payload(),
                "phase": "starting",
                "pid": wrapper_pid,
                "backend_lock": route.lock_name,
                "run_dir": str(run_dir),
            }
        ),
        encoding="utf-8",
    )
    (attempt_dir / "live_status.json").write_text(
        json.dumps({"phase": "running-sdk"}),
        encoding="utf-8",
    )
    (attempt_dir / "server.pid").write_text(f"{server_pid}\n", encoding="utf-8")
    ResourceLock(tmp_path, route.lock_name).acquire(run_id=run_id, pid=wrapper_pid)

    def fake_run(command, **kwargs):  # noqa: ANN001, ANN003, ANN202
        del kwargs
        assert command[0] != "docker"

        class Result:
            returncode = 0
            stdout = ""

        result = Result()
        return result

    with (
        patch("roboclaws.operator_console.launcher._process_parent_pid", return_value=wrapper_pid),
        patch("roboclaws.operator_console.launcher._descendant_pids", return_value=[server_pid]),
        patch("roboclaws.operator_console.launcher.os.getpgid", side_effect=lambda pid: pid),
        patch("roboclaws.operator_console.launcher.os.killpg"),
        patch("roboclaws.operator_console.launcher.subprocess.run", side_effect=fake_run),
    ):
        stop_console_run(tmp_path, run_id)

    state = json.loads((run_dir / "operator_state.json").read_text(encoding="utf-8"))
    assert state["phase"] == "stopped_by_operator"


def test_stop_console_run_ignores_retired_docker_workspace_metadata(
    tmp_path: Path,
) -> None:
    route = get_selection(MUJOCO_OPENAI_AGENTS_OPEN_TASK)
    run_id = "wrapper-run"
    wrapper_pid = 123450
    server_pid = 123451
    run_dir = console_output_root(tmp_path) / "runs" / run_id
    attempt_dir = run_dir / "0608_1807" / "seed-7"
    workspace = attempt_dir / "agent-docker-workspace"
    workspace.mkdir(parents=True)
    state_path = run_dir / "operator_state.json"
    state_path.write_text(
        json.dumps(
            {
                "run_id": run_id,
                "route": route.to_payload(),
                "phase": "starting",
                "pid": wrapper_pid,
                "backend_lock": route.lock_name,
                "run_dir": str(run_dir),
            }
        ),
        encoding="utf-8",
    )
    live_status_path = attempt_dir / "live_status.json"
    live_status_path.write_text(
        json.dumps({"phase": "running-sdk"}),
        encoding="utf-8",
    )
    (attempt_dir / "server.pid").write_text(f"{server_pid}\n", encoding="utf-8")
    ResourceLock(tmp_path, route.lock_name).acquire(run_id=run_id, pid=wrapper_pid)

    def fake_run(command, **kwargs):  # noqa: ANN001, ANN003, ANN202
        del kwargs
        assert command[0] != "docker"

        class Result:
            returncode = 0
            stdout = ""

        result = Result()
        return result

    with (
        patch("roboclaws.operator_console.launcher._process_parent_pid", return_value=wrapper_pid),
        patch("roboclaws.operator_console.launcher._descendant_pids", return_value=[server_pid]),
        patch("roboclaws.operator_console.launcher.os.getpgid", side_effect=lambda pid: pid),
        patch("roboclaws.operator_console.launcher.os.killpg"),
        patch("roboclaws.operator_console.launcher.subprocess.run", side_effect=fake_run),
    ):
        stop_console_run(tmp_path, run_id)

    assert json.loads(state_path.read_text(encoding="utf-8"))["phase"] == "stopped_by_operator"
    assert (
        json.loads(live_status_path.read_text(encoding="utf-8"))["phase"] == "stopped_by_operator"
    )
    assert ResourceLock(tmp_path, route.lock_name).read().held is False


def test_terminate_process_group_falls_back_to_single_pid_when_group_lookup_fails() -> None:
    signals: list[tuple[int, int]] = []

    def fake_kill(pid: int, sig: int) -> None:
        if sig == 0:
            raise ProcessLookupError
        signals.append((pid, sig))

    with (
        patch(
            "roboclaws.operator_console.launcher.os.getpgid",
            side_effect=ProcessLookupError,
        ),
        patch(
            "roboclaws.operator_console.launcher.os.killpg",
            side_effect=ProcessLookupError,
        ),
        patch("roboclaws.operator_console.launcher.os.kill", side_effect=fake_kill),
    ):
        _terminate_process_group(12345)

    assert signals == [(12345, 15)]
