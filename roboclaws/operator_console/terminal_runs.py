"""Terminal-state helpers for operator-console run artifacts."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Callable

from roboclaws.operator_console.state_summary import run_result_has_failure, run_result_success

TERMINAL_RUN_PHASES = {
    "failed",
    "finished",
    "passed",
    "stopped_by_operator",
    "human_takeover_stop",
}


JsonReader = Callable[[Path], dict[str, Any]]


def existing_terminal_phase(
    display_run_dir: Path,
    state: dict[str, Any],
    *,
    read_json: JsonReader,
) -> str:
    live_status = read_json(display_run_dir / "live_status.json")
    phase = terminal_status_phase(live_status, state)
    if phase:
        return phase
    return run_result_terminal_phase(read_json(display_run_dir / "run_result.json"))


def task_phase_from_payloads(
    live_status: dict[str, Any],
    state: dict[str, Any],
    run_result: dict[str, Any],
) -> str:
    phase = str(live_status.get("phase") or "").strip()
    if phase:
        return phase
    terminal_phase = run_result_terminal_phase(run_result)
    if terminal_phase:
        return terminal_phase
    return str(state.get("phase") or "unknown")


def task_phase_from_paths(
    display_run_dir: Path, state: dict[str, Any], *, read_json: JsonReader
) -> str:
    live_status = read_json(display_run_dir / "live_status.json")
    run_result = read_json(display_run_dir / "run_result.json")
    return task_phase_from_payloads(live_status, state, run_result)


def terminal_phase_from_payloads(
    live_status: dict[str, Any],
    state: dict[str, Any],
    run_result: dict[str, Any],
) -> str:
    return terminal_status_phase(live_status, state) or run_result_terminal_phase(run_result)


def terminal_status_phase(live_status: dict[str, Any], state: dict[str, Any]) -> str:
    for payload in (live_status, state):
        phase = str(payload.get("phase") or "").strip().lower()
        if phase in TERMINAL_RUN_PHASES:
            return phase
    return ""


def run_result_terminal_phase(run_result: dict[str, Any]) -> str:
    if run_result_success(run_result):
        return "finished"
    if run_result_has_failure(run_result):
        return "failed"
    return ""


def existing_terminal_reason(
    display_run_dir: Path,
    state: dict[str, Any],
    *,
    read_json: JsonReader,
) -> str:
    live_status = read_json(display_run_dir / "live_status.json")
    run_result = read_json(display_run_dir / "run_result.json")
    for payload in (live_status, state, run_result):
        for key in ("terminal_reason", "reason", "error_reason", "terminate_reason"):
            value = payload.get(key)
            if value:
                return str(value)
    return ""
