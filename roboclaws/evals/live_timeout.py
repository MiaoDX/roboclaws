"""Timeout diagnostics and cleanup helpers for live eval runs."""

from __future__ import annotations

import json
import os
import signal
import time
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[2]


class LiveEvalTimeoutError(TimeoutError):
    """Raised when the foreground live eval process exceeds a live eval budget."""

    def __init__(
        self,
        message: str,
        *,
        timeout_s: float | None,
        effective_run_dir: Path,
        live_status: dict[str, Any],
        timeout_debug_snapshot: dict[str, Any],
        command_record: dict[str, Any],
        timeout_kind: str = "timeout",
        wall_clock_budget_s: float | None = None,
        stall_timeout_s: float | None = None,
    ) -> None:
        super().__init__(message)
        self.timeout_s = timeout_s
        self.timeout_kind = timeout_kind
        self.wall_clock_budget_s = wall_clock_budget_s
        self.stall_timeout_s = stall_timeout_s
        self.effective_run_dir = str(effective_run_dir)
        self.live_status = live_status
        self.timeout_debug_snapshot = timeout_debug_snapshot
        self.command_record = command_record
        self.live_trial_attempts: list[dict[str, Any]] = []
        self.live_trial_attempts_path = ""


def live_timeout_snapshot(
    effective_run_dir: Path,
    *,
    live_status: dict[str, Any],
    timeout_s: float | None,
    timeout_kind: str = "timeout",
    wall_clock_budget_s: float | None = None,
    stall_timeout_s: float | None = None,
) -> dict[str, Any]:
    status_snapshot = live_status.get("debug_snapshot")
    if isinstance(status_snapshot, dict):
        snapshot = dict(status_snapshot)
    else:
        snapshot = {
            "schema": "molmo_live_timeout_debug_snapshot_v1",
            "run_result_present": (effective_run_dir / "run_result.json").is_file(),
            "report_present": (effective_run_dir / "report.html").is_file(),
        }
    snapshot["eval_timeout_s"] = timeout_s
    snapshot["timeout_kind"] = timeout_kind
    snapshot["eval_wall_clock_budget_s"] = wall_clock_budget_s
    snapshot["eval_stall_timeout_s"] = stall_timeout_s
    snapshot["effective_run_dir"] = str(effective_run_dir)
    snapshot["live_status_phase"] = str(live_status.get("phase") or "")
    if "elapsed_s" not in snapshot and live_status.get("elapsed_s") is not None:
        snapshot["elapsed_s"] = live_status.get("elapsed_s")
    return snapshot


def live_exception_debug_fields(exc: Exception) -> dict[str, Any]:
    fields: dict[str, Any] = {}
    effective_run_dir = getattr(exc, "effective_run_dir", "")
    if effective_run_dir:
        fields["effective_run_dir"] = str(effective_run_dir)
    timeout_debug_snapshot = getattr(exc, "timeout_debug_snapshot", None)
    if isinstance(timeout_debug_snapshot, dict) and timeout_debug_snapshot:
        fields["timeout_debug_snapshot"] = timeout_debug_snapshot
    live_status = getattr(exc, "live_status", None)
    if isinstance(live_status, dict) and live_status:
        fields["live_status_phase"] = str(live_status.get("phase") or "")
    timeout_kind = getattr(exc, "timeout_kind", "")
    if timeout_kind:
        fields["timeout_kind"] = str(timeout_kind)
    for name in ("timeout_s", "wall_clock_budget_s", "stall_timeout_s"):
        value = getattr(exc, name, None)
        if value is not None:
            fields[name] = value
    live_trial_attempts = getattr(exc, "live_trial_attempts", None)
    if isinstance(live_trial_attempts, list) and live_trial_attempts:
        fields["live_trial_attempts"] = live_trial_attempts
    live_trial_attempts_path = getattr(exc, "live_trial_attempts_path", "")
    if live_trial_attempts_path:
        fields["live_trial_attempts_path"] = str(live_trial_attempts_path)
    return fields


def cleanup_timed_out_live_children(effective_run_dir: Path) -> dict[str, Any]:
    pid_path = effective_run_dir / "server.pid"
    payload: dict[str, Any] = {"server_pid_path": str(pid_path), "server_pid": None}
    try:
        pid = int(pid_path.read_text(encoding="utf-8").strip())
    except (OSError, ValueError) as exc:
        payload["status"] = "server_pid_unavailable"
        payload["error_type"] = exc.__class__.__name__
        payload["visual_backend_slot_cleanup"] = _cleanup_visual_backend_slot_for_run(
            effective_run_dir
        )
        return payload
    payload["server_pid"] = pid
    if not _process_exists(pid):
        payload["status"] = "server_not_running"
        payload["visual_backend_slot_cleanup"] = _cleanup_visual_backend_slot_for_run(
            effective_run_dir
        )
        return payload
    try:
        os.kill(pid, signal.SIGTERM)
    except OSError as exc:
        payload["status"] = "terminate_failed"
        payload["error_type"] = exc.__class__.__name__
        payload["message"] = str(exc)
        payload["visual_backend_slot_cleanup"] = _cleanup_visual_backend_slot_for_run(
            effective_run_dir
        )
        return payload
    deadline = time.monotonic() + 5.0
    while time.monotonic() < deadline:
        if not _process_exists(pid):
            payload["status"] = "terminated"
            payload["visual_backend_slot_cleanup"] = _cleanup_visual_backend_slot_for_run(
                effective_run_dir
            )
            return payload
        time.sleep(0.1)
    try:
        os.kill(pid, signal.SIGKILL)
    except OSError as exc:
        payload["status"] = "kill_failed"
        payload["error_type"] = exc.__class__.__name__
        payload["message"] = str(exc)
        payload["visual_backend_slot_cleanup"] = _cleanup_visual_backend_slot_for_run(
            effective_run_dir
        )
        return payload
    payload["status"] = "killed" if not _process_exists(pid) else "kill_sent"
    payload["visual_backend_slot_cleanup"] = _cleanup_visual_backend_slot_for_run(effective_run_dir)
    return payload


def _process_exists(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


def _cleanup_visual_backend_slot_for_run(effective_run_dir: Path) -> dict[str, Any]:
    slot_root = REPO_ROOT / "output" / "molmo" / "visual-backend-slots"
    target = _resolved_path(effective_run_dir)
    removed: list[str] = []
    errors: list[dict[str, str]] = []
    for path in sorted(slot_root.glob("slot-*.json")):
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            errors.append({"path": str(path), "error_type": exc.__class__.__name__})
            continue
        if not isinstance(payload, dict):
            continue
        slot_output = str(payload.get("output_dir") or "")
        if not slot_output or _resolved_path(Path(slot_output)) != target:
            continue
        try:
            path.unlink()
        except OSError as exc:
            errors.append(
                {
                    "path": str(path),
                    "error_type": exc.__class__.__name__,
                    "message": str(exc),
                }
            )
            continue
        removed.append(str(path))
    return {
        "slot_root": str(slot_root),
        "target_output_dir": str(effective_run_dir),
        "removed": removed,
        "errors": errors,
    }


def _resolved_path(path: Path) -> Path:
    return (REPO_ROOT / path).resolve() if not path.is_absolute() else path.resolve()
