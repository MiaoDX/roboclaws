"""Latest-run attachment for the operator console."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from roboclaws.core.json_sources import read_json_object
from roboclaws.operator_console.paths import console_output_root
from roboclaws.operator_console.state import (
    display_run_id,
    resolve_display_run_dir,
)
from roboclaws.operator_console.state_artifacts import LIVE_RUN_MARKERS


@dataclass(frozen=True)
class HistorySourceError:
    """Operator-visible source error for latest-run attachment."""

    path: Path
    label: str
    reason: str

    def to_payload(self) -> dict[str, str]:
        return {
            "label": self.label,
            "path": str(self.path),
            "reason": self.reason,
        }


def latest_run_payload(root: Path) -> dict[str, Any]:
    """Return the newest artifact-backed run payload."""

    candidates = [
        payload for run_dir in _run_dirs(root) if (payload := _candidate_payload(run_dir))
    ]
    if not candidates:
        return {}
    return max(candidates, key=lambda item: float(item.get("activity_epoch") or 0.0))


def _run_dirs(root: Path) -> list[Path]:
    runs_dir = console_output_root(root) / "runs"
    if not runs_dir.is_dir():
        return []
    return [path for path in runs_dir.iterdir() if path.is_dir()]


def _candidate_payload(run_dir: Path) -> dict[str, Any]:
    run_dir = run_dir.resolve()
    display_run_dir = resolve_display_run_dir(run_dir)
    if not _has_attachable_artifact(display_run_dir):
        return {}
    state, state_error = _read_json_source(run_dir / "operator_state.json", label="Operator State")
    if state_error:
        return _candidate_source_error_payload(
            run_dir=run_dir,
            display_run_dir=display_run_dir,
            source_errors=(state_error,),
        )
    route_payload = (
        state.get("launch_selection") if isinstance(state.get("launch_selection"), dict) else {}
    )
    if not route_payload:
        route_payload = state.get("route") if isinstance(state.get("route"), dict) else {}
    live_status, live_status_error = _read_json_source(
        display_run_dir / "live_status.json",
        label="Live Status",
    )
    source_errors = (live_status_error,) if live_status_error else ()
    payload = {
        "run_id": str(state.get("run_id") or run_dir.name),
        "selection_id": str(route_payload.get("selection_id") or route_payload.get("id") or ""),
        "launch_label": str(route_payload.get("label") or "Agent run"),
        "run_dir": str(run_dir),
        "display_run_dir": str(display_run_dir),
        "display_run_id": display_run_id(run_dir, display_run_dir),
        "activity_epoch": _run_activity_epoch(display_run_dir, run_dir),
        "started_at": str(state.get("started_at") or ""),
        "phase": _latest_phase(live_status, state, source_errors=source_errors),
    }
    if source_errors:
        payload.update(_source_error_fields(source_errors))
    return payload


def _has_attachable_artifact(display_run_dir: Path) -> bool:
    return any((display_run_dir / marker).exists() for marker in LIVE_RUN_MARKERS)


def _run_activity_epoch(display_run_dir: Path, run_dir: Path) -> float:
    mtimes: list[float] = []
    for marker in LIVE_RUN_MARKERS:
        marker_path = display_run_dir / marker
        if marker_path.exists():
            try:
                mtimes.append(marker_path.stat().st_mtime)
            except OSError:
                pass
    if mtimes:
        return max(mtimes)
    try:
        return run_dir.stat().st_mtime
    except OSError:
        return 0.0


def _latest_phase(
    live_status: dict[str, Any],
    state: dict[str, Any],
    *,
    source_errors: tuple[HistorySourceError, ...] = (),
) -> str:
    if source_errors:
        return "failed"
    return str(live_status.get("phase") or state.get("phase") or "")


def _read_json_source(
    path: Path,
    *,
    label: str,
) -> tuple[dict[str, Any], HistorySourceError | None]:
    if not path.exists():
        return {}, None
    try:
        return read_json_object(path, label=label), None
    except ValueError as exc:
        cause = exc.__cause__
        if isinstance(cause, json.JSONDecodeError):
            return {}, HistorySourceError(
                path=path.resolve(),
                label=label,
                reason=f"invalid JSON at line {cause.lineno} column {cause.colno}",
            )
        return {}, HistorySourceError(
            path=path.resolve(), label=label, reason="expected JSON object"
        )
    except OSError as exc:
        return {}, HistorySourceError(path=path.resolve(), label=label, reason=str(exc))


def _candidate_source_error_payload(
    *,
    run_dir: Path,
    display_run_dir: Path,
    source_errors: tuple[HistorySourceError, ...],
) -> dict[str, Any]:
    payload = {
        "run_id": run_dir.name,
        "selection_id": "",
        "launch_label": "Agent run",
        "run_dir": str(run_dir),
        "display_run_dir": str(display_run_dir),
        "display_run_id": display_run_id(run_dir, display_run_dir),
        "activity_epoch": _run_activity_epoch(display_run_dir, run_dir),
        "started_at": "",
        "phase": "failed",
    }
    payload.update(_source_error_fields(source_errors))
    return payload


def _source_error_fields(source_errors: tuple[HistorySourceError, ...]) -> dict[str, Any]:
    labels = ", ".join(dict.fromkeys(error.label for error in source_errors))
    return {
        "status": "source_error",
        "status_label": "Source error",
        "error": f"operator history source error: {labels}",
        "source_errors": [error.to_payload() for error in source_errors],
    }
