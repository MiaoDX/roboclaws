"""Operator-console process lifecycle and run-directory ownership."""

from __future__ import annotations

import json
import os
import re
import signal
import subprocess
import time
from pathlib import Path
from typing import Any

from roboclaws.core.json_sources import read_json_object
from roboclaws.operator_console.launch_contract import ConsoleLaunchError
from roboclaws.operator_console.locks import ResourceLock
from roboclaws.operator_console.paths import console_output_root
from roboclaws.operator_console.routes import ConsoleLaunchSelection
from roboclaws.operator_console.runtime_compat import pid_is_active
from roboclaws.operator_console.state import resolve_display_run_dir
from roboclaws.operator_console.state_summary import (
    existing_terminal_phase,
    existing_terminal_reason,
)

RUN_ID_SAFE_RE = re.compile(r"[^A-Za-z0-9_.-]+")


class _JsonSourceError(ValueError):
    def __init__(self, path: Path, reason: str) -> None:
        self.path = path
        self.reason = reason
        super().__init__(f"{path}: {reason}")


def stop_console_run(root: Path, run_id: str, *, emergency: bool = False) -> dict[str, Any]:
    run_dir = console_output_root(root) / "runs" / run_id
    state_path = run_dir / "operator_state.json"
    if not state_path.exists():
        raise ConsoleLaunchError(f"unknown run id: {run_id}")
    try:
        state = _read_json_source(state_path)
    except _JsonSourceError as exc:
        raise _operator_stop_source_error(exc) from exc
    display_run_dir = resolve_display_run_dir(run_dir)
    terminal_phase = "human_takeover_stop" if emergency else "stopped_by_operator"
    try:
        existing_phase = _existing_terminal_phase(display_run_dir, state)
        terminal_reason = (
            _existing_terminal_reason(display_run_dir, state) if existing_phase else ""
        )
    except _JsonSourceError as exc:
        raise _operator_stop_source_error(exc) from exc
    _stop_live_child_run(display_run_dir)
    pid = state.get("pid")
    _terminate_process_group(pid if isinstance(pid, int) else None)
    if existing_phase:
        state["phase"] = existing_phase
        state["terminal_reason"] = terminal_reason or (
            state.get("terminal_reason") or existing_phase
        )
    else:
        try:
            _mark_live_child_stopped(display_run_dir, terminal_phase)
        except _JsonSourceError as exc:
            raise _operator_stop_source_error(exc) from exc
        state["phase"] = terminal_phase
        state["terminal_reason"] = state["phase"]
    state["stopped_at_epoch"] = time.time()
    state["display_run_dir"] = str(display_run_dir)
    state_path.write_text(json.dumps(state, indent=2), encoding="utf-8")
    route_payload = state.get("route") or {}
    lock_name = str(route_payload.get("lock_name") or state.get("backend_lock") or "")
    if lock_name:
        ResourceLock(root, lock_name).release(run_id=run_id, force=True)
    return state


def _operator_stop_source_error(error: _JsonSourceError) -> ConsoleLaunchError:
    return ConsoleLaunchError(f"operator stop source error: {error.path.name} {error.reason}")


def _existing_terminal_phase(display_run_dir: Path, state: dict[str, Any]) -> str:
    return existing_terminal_phase(
        display_run_dir,
        state,
        read_json=_read_optional_json_source,
    )


def _existing_terminal_reason(display_run_dir: Path, state: dict[str, Any]) -> str:
    return existing_terminal_reason(
        display_run_dir,
        state,
        read_json=_read_optional_json_source,
    )


def _live_run_pid(display_run_dir: Path) -> int | None:
    server_pid_path = display_run_dir / "server.pid"
    if not server_pid_path.is_file():
        return None
    try:
        pid = int(server_pid_path.read_text(encoding="utf-8").strip())
    except (OSError, ValueError):
        return None
    return pid if pid > 0 else None


def _stop_live_child_run(display_run_dir: Path) -> None:
    live_pid = _live_run_pid(display_run_dir)
    stop_pids = _live_run_stop_pids(live_pid)
    _kill_tmux_session(display_run_dir)
    for pid in stop_pids:
        _terminate_process_group(pid)


def _mark_live_child_stopped(display_run_dir: Path, phase: str) -> None:
    display_run_dir.mkdir(parents=True, exist_ok=True)
    status_path = display_run_dir / "live_status.json"
    payload = _read_optional_json_source(status_path)
    payload.update(
        {
            "phase": phase,
            "terminal_reason": phase,
            "finished_at_epoch": time.time(),
            "exit_status": 130,
        }
    )
    status_path.write_text(json.dumps(payload, sort_keys=True) + "\n", encoding="utf-8")


def _live_run_stop_pids(live_pid: int | None) -> list[int]:
    if not live_pid or live_pid <= 0:
        return []
    pids = [live_pid]
    parent_pid = _process_parent_pid(live_pid)
    if parent_pid and _safe_process_pid(parent_pid):
        pids.append(parent_pid)
        pids.extend(_descendant_pids(parent_pid))
    else:
        pids.extend(_descendant_pids(live_pid))
    return _dedupe_pids(pids)


def _terminate_process_group(pid: int | None) -> None:
    if not pid or pid <= 0:
        return
    _signal_process_group_or_pid(pid, signal.SIGTERM)
    deadline = time.monotonic() + 1.0
    while pid_is_active(pid) and time.monotonic() < deadline:
        time.sleep(0.05)
    if pid_is_active(pid):
        _signal_process_group_or_pid(pid, signal.SIGKILL)


def _signal_process_group_or_pid(pid: int, sig: signal.Signals) -> None:
    try:
        pgid = os.getpgid(pid)
    except ProcessLookupError:
        pgid = pid
    except (PermissionError, OSError):
        pgid = None
    if pgid and pgid > 0:
        try:
            os.killpg(pgid, int(sig))
            return
        except ProcessLookupError:
            pass
        except (PermissionError, OSError):
            pass
    try:
        os.kill(pid, int(sig))
    except (ProcessLookupError, PermissionError, OSError):
        pass


def _process_parent_pid(pid: int) -> int | None:
    try:
        raw = (Path("/proc") / str(pid) / "stat").read_text(encoding="utf-8")
    except OSError:
        return None
    return _parse_proc_stat_parent_pid(raw)


def _descendant_pids(root_pid: int) -> list[int]:
    children_by_parent: dict[int, list[int]] = {}
    try:
        stat_paths = list(Path("/proc").glob("[0-9]*/stat"))
    except OSError:
        return []
    for stat_path in stat_paths:
        try:
            pid = int(stat_path.parent.name)
            parent_pid = _parse_proc_stat_parent_pid(stat_path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        if parent_pid is None:
            continue
        children_by_parent.setdefault(parent_pid, []).append(pid)
    descendants: list[int] = []
    queue = list(children_by_parent.get(root_pid, []))
    while queue:
        pid = queue.pop(0)
        if not _safe_process_pid(pid):
            continue
        descendants.append(pid)
        queue.extend(children_by_parent.get(pid, []))
    return descendants


def _parse_proc_stat_parent_pid(raw: str) -> int | None:
    try:
        suffix = raw.rsplit(") ", 1)[1]
        fields = suffix.split()
        return int(fields[1])
    except (IndexError, ValueError):
        return None


def _safe_process_pid(pid: int) -> bool:
    return pid > 1 and pid not in {os.getpid(), os.getppid()}


def _dedupe_pids(pids: list[int]) -> list[int]:
    seen: set[int] = set()
    output: list[int] = []
    for pid in pids:
        if pid in seen or not _safe_process_pid(pid):
            continue
        seen.add(pid)
        output.append(pid)
    return output


def _read_optional_json_source(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    return _read_json_source(path)


def _read_json_source(path: Path) -> dict[str, Any]:
    try:
        return read_json_object(path, label=path.name)
    except ValueError as exc:
        cause = exc.__cause__
        if isinstance(cause, json.JSONDecodeError):
            raise _JsonSourceError(path, f"contains invalid JSON at line {cause.lineno}") from exc
        raise _JsonSourceError(path, "must contain a JSON object") from exc
    except FileNotFoundError as exc:
        raise _JsonSourceError(path, "cannot be read: missing source") from exc
    except OSError as exc:
        raise _JsonSourceError(path, f"cannot be read: {exc}") from exc


def _tmux_session_active(display_run_dir: Path) -> bool:
    session_path = display_run_dir / "tmux_session.txt"
    if not session_path.is_file():
        return False
    try:
        session_name = session_path.read_text(encoding="utf-8").strip()
    except OSError:
        return False
    if not session_name:
        return False
    result = subprocess.run(
        ["tmux", "has-session", "-t", session_name],
        check=False,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    return result.returncode == 0


def _kill_tmux_session(display_run_dir: Path) -> None:
    session_path = display_run_dir / "tmux_session.txt"
    if not session_path.is_file():
        return
    try:
        session_name = session_path.read_text(encoding="utf-8").strip()
    except OSError:
        return
    if not session_name:
        return
    subprocess.run(
        ["tmux", "kill-session", "-t", session_name],
        check=False,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )


def _new_run_id(route: ConsoleLaunchSelection) -> str:
    timestamp = time.strftime("%Y%m%d-%H%M%S", time.localtime())
    return f"{timestamp}-{_safe_run_id_suffix(route.id)}"


def _reserve_new_run_dir(root: Path, route: ConsoleLaunchSelection) -> tuple[str, Path]:
    runs_dir = console_output_root(root) / "runs"
    runs_dir.mkdir(parents=True, exist_ok=True)
    base_run_id = _new_run_id(route)
    for suffix in ("", *(f"-{index}" for index in range(2, 100))):
        run_id = f"{base_run_id}{suffix}"
        run_dir = runs_dir / run_id
        try:
            run_dir.mkdir()
        except FileExistsError:
            continue
        return run_id, run_dir
    raise ConsoleLaunchError(f"could not allocate unique operator-console run id: {base_run_id}")


def _remove_empty_reserved_run_dir(run_dir: Path) -> None:
    try:
        run_dir.rmdir()
    except OSError:
        pass


def _safe_run_id_suffix(raw: str) -> str:
    """Return a readable id fragment that is safe in paths."""

    slug = RUN_ID_SAFE_RE.sub("-", raw).strip("-._")
    slug = re.sub(r"-{2,}", "-", slug)
    return slug or "run"
