"""Canonical runtime task and resource payload model."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any
from urllib.parse import quote

from roboclaws.core.json_sources import read_json_object
from roboclaws.operator_console import runtime_host_probes
from roboclaws.operator_console.paths import operator_output_request_path
from roboclaws.operator_console.redaction import redact_text
from roboclaws.operator_console.routes import selection_task_selector
from roboclaws.operator_console.runtime_compat import float_or_none, pid_is_active
from roboclaws.operator_console.runtime_host_probes import (
    DEFAULT_MCP_HOST,
    _age_seconds,
    _int_or_none,
    _recent_epoch,
    _relative_to_root,
    _server_pid,
    _tmux_session_exists,
    _tmux_session_name,
)
from roboclaws.operator_console.state_summary import is_terminal_run_phase

ACTIVE_STATUSES = {"running", "launched", "blocked"}


class JsonSourceError(dict[str, Any]):
    """Malformed JSON source details that remain mapping-compatible for callers."""


def _run_dir_resources(display_run_dir: Path | None) -> list[dict[str, Any]]:
    if display_run_dir is None:
        return []
    resources: list[dict[str, Any]] = []
    session = _tmux_session_name(display_run_dir)
    if session:
        session_active = _tmux_session_exists(session)
        resources.append(
            _resource(
                "tmux_session",
                session,
                path=display_run_dir / "tmux_session.txt",
                session_id=session,
                active=session_active,
            )
        )
    server_pid = _server_pid(display_run_dir)
    if server_pid:
        resources.append(
            _resource(
                "server_pid",
                str(server_pid),
                path=display_run_dir / "server.pid",
                pid=server_pid,
                active=pid_is_active(server_pid),
            )
        )
    slot = _read_json(display_run_dir / "visual_backend_slot.json")
    if isinstance(slot, JsonSourceError):
        resources.append(_json_source_error_resource(slot))
    elif slot:
        slot_id = slot.get("slot_id")
        resources.append(
            _resource(
                "visual_slot",
                f"Molmo visual slot {slot_id}",
                path=Path(str(slot.get("path") or "")),
                slot_id=slot_id,
                port=slot.get("port"),
                active=_visual_slot_payload_active(slot),
            )
        )
    live_status = _read_json(display_run_dir / "live_status.json")
    if isinstance(live_status, JsonSourceError):
        resources.append(_json_source_error_resource(live_status))
        status_slot = None
    else:
        status_slot = live_status.get("visual_backend_slot")
    if isinstance(status_slot, dict) and status_slot.get("slot_id"):
        resources.append(
            _resource(
                "visual_slot",
                f"Molmo visual slot {status_slot.get('slot_id')}",
                path=Path(str(status_slot.get("path") or "")),
                slot_id=status_slot.get("slot_id"),
                port=status_slot.get("port"),
                active=_visual_slot_payload_active(status_slot),
            )
        )
    for payload in (slot, status_slot if isinstance(status_slot, dict) else {}):
        port = _int_or_none(payload.get("port") if isinstance(payload, dict) else None)
        if port:
            resources.append(
                _resource(
                    "mcp_port",
                    f"{DEFAULT_MCP_HOST}:{port}",
                    host=DEFAULT_MCP_HOST,
                    port=port,
                    active=not runtime_host_probes._tcp_port_free(DEFAULT_MCP_HOST, port),
                )
            )
    return _dedupe_resources(resources)


def _run_artifacts(root: Path, run_dir: Path, display_run_dir: Path) -> list[dict[str, Any]]:
    candidates = [
        (run_dir / "operator_state.json", "Operator state", "status"),
        (run_dir / "console-launch.log", "Console launch log", "log"),
        (display_run_dir / "live_status.json", "Live status", "status"),
        (display_run_dir / "driver.log", "Driver log", "log"),
        (display_run_dir / "report.html", "Report", "report"),
        (display_run_dir / "run_result.json", "Run result", "result"),
        (display_run_dir / "trace.jsonl", "Trace", "trace"),
    ]
    return [
        artifact
        for path, label, kind in candidates
        if (artifact := _artifact(root, path, label, kind=kind))
    ]


def _run_actions(
    root: Path,
    *,
    owner: str,
    run_id: str = "",
    display_run_dir: Path | None,
    stop_available: bool = False,
    require_live_tmux: bool = False,
) -> list[dict[str, Any]]:
    actions: list[dict[str, Any]] = []
    if owner == "operator-console" and run_id and stop_available:
        actions.append(
            {
                "type": "api_post",
                "label": "Stop",
                "method": "POST",
                "href": f"/api/runs/{quote(run_id, safe='')}/stop",
            }
        )
    session = _tmux_session_name(display_run_dir) if display_run_dir else ""
    if session and require_live_tmux and not _tmux_session_exists(session):
        session = ""
    driver_log = display_run_dir / "driver.log" if display_run_dir else None
    if driver_log and driver_log.is_file():
        request_path = operator_output_request_path(root, driver_log)
        if request_path:
            actions.append(
                {
                    "type": "link",
                    "label": "Open Log",
                    "href": f"/api/raw/{quote(request_path, safe='/')}",
                }
            )
    return actions


def _task(
    *,
    task_id: str,
    status: str,
    owner: str,
    label: str,
    resource: str,
    resources: list[dict[str, Any]],
    run_id: str = "",
    row_id: str = "",
    route_id: str = "",
    pid: int | None = None,
    session_id: str = "",
    run_dir: Path | None = None,
    display_run_dir: Path | None = None,
    started_at: str = "",
    started_at_epoch: float | None = None,
    artifacts: list[dict[str, Any]] | None = None,
    actions: list[dict[str, Any]] | None = None,
    extra: dict[str, Any] | None = None,
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "id": task_id,
        "status": status,
        "owner": owner,
        "label": redact_text(label),
        "resource": redact_text(resource),
        "resources": resources,
        "run_id": run_id,
        "row_id": row_id,
        "route_id": route_id,
        "pid": pid,
        "session_id": session_id,
        "run_dir": str(run_dir) if run_dir else "",
        "display_run_dir": str(display_run_dir) if display_run_dir else "",
        "started_at": started_at,
        "started_at_epoch": started_at_epoch,
        "age_seconds": _age_seconds(started_at_epoch),
        "artifacts": artifacts or [],
        "actions": actions or [],
    }
    if extra:
        payload.update(extra)
    return {key: value for key, value in payload.items() if value not in (None, "", [])}


def _resource(kind: str, label: str, **extra: Any) -> dict[str, Any]:
    payload = {"kind": kind, "label": redact_text(str(label))}
    for key, value in extra.items():
        if isinstance(value, Path):
            value = str(value)
        if value not in (None, ""):
            payload[key] = value
    return payload


def _artifact(root: Path, path: Path, label: str, *, kind: str) -> dict[str, Any]:
    if not path or not path.is_file():
        return {}
    request_path = operator_output_request_path(root, path)
    href = f"/artifacts/{quote(request_path, safe='/?=&')}" if request_path else ""
    if kind == "log" and request_path:
        href = f"/api/raw/{quote(request_path, safe='/')}"
    return {
        "label": label,
        "kind": kind,
        "path": str(path),
        "href": href,
    }


def _status_from_phase(
    phase: str,
    *,
    pid: int | None,
    tmux_session: str,
    has_child_evidence: bool = True,
    has_live_resource: bool | None = None,
) -> str:
    normalized = str(phase or "").strip().lower()
    if is_terminal_run_phase(normalized):
        return "terminal"
    if tmux_session and _tmux_session_exists(tmux_session):
        return "running"
    if pid and pid_is_active(pid):
        return "running"
    if has_live_resource is False and normalized:
        return "stale"
    if has_live_resource is True:
        return "running"
    if pid and normalized in {"queued", "starting", "launched"} and not has_child_evidence:
        return "stale"
    if normalized in {"queued", "starting", "launched"}:
        return "launched"
    if normalized:
        return "running"
    return "unknown"


def _has_active_resource(resources: list[dict[str, Any]]) -> bool:
    return any(resource.get("active") is True for resource in resources)


def _visual_slot_payload_active(payload: dict[str, Any]) -> bool:
    if not payload.get("slot_id") or payload.get("stale"):
        return False
    path = Path(str(payload.get("path") or ""))
    current_payload = _read_json(path) if path.is_file() else payload
    if isinstance(current_payload, JsonSourceError):
        return False
    current_run_id = str(current_payload.get("run_id") or "")
    payload_run_id = str(payload.get("run_id") or "")
    if current_run_id and payload_run_id and current_run_id != payload_run_id:
        return False
    current_pid = _int_or_none(current_payload.get("pid")) or _int_or_none(payload.get("pid"))
    if current_pid:
        return pid_is_active(current_pid)
    port = _int_or_none(current_payload.get("port")) or _int_or_none(payload.get("port"))
    if port and runtime_host_probes._tcp_port_free(DEFAULT_MCP_HOST, port):
        return False
    return bool(current_pid or port or current_payload)


def _include_task(task: dict[str, Any], *, include_recent_terminal: bool) -> bool:
    if task.get("status") != "terminal":
        return True
    if not include_recent_terminal:
        return False
    return _recent_epoch(task.get("started_at_epoch"), window_s=24 * 60 * 60) or _recent_epoch(
        _mtime_for_task(task),
        window_s=24 * 60 * 60,
    )


def _primary_resource(resources: list[dict[str, Any]]) -> str:
    if not resources:
        return "background resource"
    return str(resources[0].get("label") or resources[0].get("kind") or "background resource")


def _route_id_from_axes(axes: dict[str, Any]) -> str:
    world = str(axes.get("world") or "")
    backend = str(axes.get("backend") or "")
    intent = str(axes.get("preset") or axes.get("intent") or "")
    engine = str(axes.get("agent_engine") or "")
    lane = str(axes.get("evidence_lane") or "")
    if not all((world, backend, intent, engine, lane)):
        return ""
    return "::".join((world, backend, selection_task_selector(intent), engine, lane))


def _summary(tasks: list[dict[str, Any]]) -> dict[str, Any]:
    active = [item for item in tasks if _task_can_block(item)]
    by_owner: dict[str, int] = {}
    by_status: dict[str, int] = {}
    for task in tasks:
        owner = str(task.get("owner") or "unknown")
        status = str(task.get("status") or "unknown")
        by_owner[owner] = by_owner.get(owner, 0) + 1
        by_status[status] = by_status.get(status, 0) + 1
    return {
        "total": len(tasks),
        "active": len(active),
        "by_owner": by_owner,
        "by_status": by_status,
    }


def _task_can_block(task: dict[str, Any]) -> bool:
    return str(task.get("status") or "") in ACTIVE_STATUSES


def _dedupe_tasks(tasks: list[dict[str, Any]]) -> list[dict[str, Any]]:
    seen: set[str] = set()
    output: list[dict[str, Any]] = []
    for task in tasks:
        task_id = str(task.get("id") or "")
        if not task_id or task_id in seen:
            continue
        seen.add(task_id)
        output.append(task)
    return output


def _dedupe_resources(resources: list[dict[str, Any]]) -> list[dict[str, Any]]:
    seen: set[tuple[str, str]] = set()
    output: list[dict[str, Any]] = []
    for resource in resources:
        key = (str(resource.get("kind") or ""), str(resource.get("label") or ""))
        if key in seen:
            continue
        seen.add(key)
        output.append(resource)
    return output


def _sort_key(task: dict[str, Any]) -> tuple[float, str]:
    epoch = float_or_none(task.get("started_at_epoch")) or _mtime_for_task(task)
    return epoch, str(task.get("id") or "")


def _mtime_for_task(task: dict[str, Any]) -> float:
    for key in ("display_run_dir", "run_dir"):
        value = task.get(key)
        if value:
            try:
                return Path(str(value)).stat().st_mtime
            except OSError:
                pass
    return 0.0


def _json_source_error_task(root: Path, path: Path, *, owner: str) -> dict[str, Any]:
    error = _read_json(path)
    if not isinstance(error, JsonSourceError):
        return {}
    rel = _relative_to_root(root, path)
    source_label = rel or path.name
    return _task(
        task_id=f"source-error:{owner}:{source_label}",
        status="source_error",
        owner=owner,
        label=f"Invalid runtime inventory JSON: {source_label}",
        resource=f"invalid JSON source {source_label}",
        resources=[_json_source_error_resource(error)],
        run_dir=path.parent,
        artifacts=[_artifact(root, path, "Invalid JSON source", kind="status")],
        extra={
            "error_reason": error["error_reason"],
            "source_path": str(path),
            "message": error["message"],
        },
    )


def _json_source_error_resource(error: JsonSourceError) -> dict[str, Any]:
    return _resource(
        "source_error",
        error["message"],
        path=Path(str(error["source_path"])),
        active=False,
        error_reason=error["error_reason"],
    )


def _read_json(path: Path) -> dict[str, Any] | JsonSourceError:
    if not path or not path.exists():
        return {}
    if not path.is_file():
        return JsonSourceError(
            {
                "error_reason": "unreadable_json",
                "source_path": str(path),
                "message": f"{path.name} could not be read: Is a directory",
            }
        )
    try:
        return read_json_object(path, label=path.name)
    except FileNotFoundError as exc:
        return JsonSourceError(
            {
                "error_reason": "unreadable_json",
                "source_path": str(path),
                "message": f"{path.name} could not be read: {exc}",
            }
        )
    except ValueError as exc:
        cause = exc.__cause__
        if isinstance(cause, json.JSONDecodeError):
            return JsonSourceError(
                {
                    "error_reason": "invalid_json",
                    "source_path": str(path),
                    "message": f"{path.name} is not readable JSON: {cause.msg}",
                }
            )
        return JsonSourceError(
            {
                "error_reason": "invalid_json_object",
                "source_path": str(path),
                "message": f"{path.name} must contain a JSON object",
            }
        )
    except OSError as exc:
        return JsonSourceError(
            {
                "error_reason": "unreadable_json",
                "source_path": str(path),
                "message": f"{path.name} could not be read: {exc.strerror or exc}",
            }
        )
