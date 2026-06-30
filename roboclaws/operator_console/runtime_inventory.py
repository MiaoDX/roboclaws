"""Background-task inventory for operator-console launch readiness."""

from __future__ import annotations

import json
import socket
import subprocess
import time
from pathlib import Path
from typing import Any
from urllib.parse import quote

from roboclaws.core.json_sources import read_json_object
from roboclaws.household.visual_backend_slots import (
    VisualBackendSlotError,
    list_visual_backend_slots,
)
from roboclaws.operator_console.launch_support import (
    DockerMountSourceError,
    docker_container_mount_sources,
)
from roboclaws.operator_console.locks import ResourceLock
from roboclaws.operator_console.paths import console_output_root, operator_output_request_path
from roboclaws.operator_console.process_status import pid_is_active
from roboclaws.operator_console.redaction import redact_text
from roboclaws.operator_console.routes import ConsoleLaunchSelection, selection_task_selector
from roboclaws.operator_console.state import resolve_display_run_dir
from roboclaws.operator_console.terminal_runs import TERMINAL_RUN_PHASES, task_phase_from_paths

DEFAULT_MCP_HOST, DEFAULT_MCP_PORT = "127.0.0.1", 18788
ACTIVE_STATUSES = {"running", "launched", "blocked"}
LIVE_MARKERS = (
    "live_status.json",
    "run_result.json",
    "driver.log",
    "tmux_session.txt",
    "server.pid",
    "report.html",
)


class JsonSourceError(dict[str, Any]):
    """Malformed JSON source details that remain mapping-compatible for callers."""


def runtime_inventory_payload(
    root: Path,
    *,
    ports: list[int] | None = None,
    include_recent_terminal: bool = True,
) -> dict[str, Any]:
    """Return a redacted inventory of repo-relevant local background tasks."""

    root = root.resolve()
    port_list = _dedupe_ints([DEFAULT_MCP_PORT] if ports is None else ports)
    tasks: list[dict[str, Any]] = []
    tasks.extend(_operator_console_tasks(root, include_recent_terminal=include_recent_terminal))
    tasks.extend(_eval_harness_tasks(root, include_recent_terminal=include_recent_terminal))
    tasks.extend(_visual_slot_tasks(root))
    if _host_probe_enabled(root):
        tasks.extend(_tmux_tasks(root))
        tasks.extend(_port_owner_tasks(root, port_list))
        tasks.extend(_docker_tasks(root))
    tasks = _dedupe_tasks(tasks)
    tasks.sort(key=lambda item: _sort_key(item), reverse=True)
    return {
        "schema": "roboclaws_operator_console_runtime_inventory_v1",
        "generated_at_epoch": time.time(),
        "tasks": tasks,
        "summary": _summary(tasks),
    }


def runtime_blockers_payload(
    root: Path,
    *,
    ports: list[int] | None = None,
) -> dict[str, Any]:
    """Return only background resources that matter to console/UI E2E startup."""

    inventory = runtime_inventory_payload(root, ports=ports, include_recent_terminal=False)
    return runtime_blockers_from_inventory(inventory)


def runtime_blockers_from_inventory(inventory: dict[str, Any]) -> dict[str, Any]:
    tasks = [
        task
        for task in inventory.get("tasks") or []
        if isinstance(task, dict)
        and (
            (_task_can_block(task) and _has_ui_e2e_blocking_resource(task))
            or _task_has_source_error(task)
        )
    ]
    return {
        "schema": "roboclaws_operator_console_runtime_blockers_v1",
        "generated_at_epoch": inventory.get("generated_at_epoch", time.time()),
        "tasks": tasks,
        "summary": _summary(tasks),
    }


def requested_mcp_endpoint(overrides: dict[str, str] | None = None) -> tuple[str, int]:
    overrides = overrides or {}
    host = str(overrides.get("host") or DEFAULT_MCP_HOST).strip() or DEFAULT_MCP_HOST
    return host, _parse_port(str(overrides.get("port") or DEFAULT_MCP_PORT))


def blocking_tasks_for_route(
    route: ConsoleLaunchSelection,
    tasks: list[dict[str, Any]],
    *,
    host: str,
    port: int,
) -> list[dict[str, Any]]:
    """Return inventory tasks that occupy resources needed by ``route``."""

    blockers: list[dict[str, Any]] = []
    for task in tasks:
        if not _task_can_block(task):
            continue
        if _task_blocks_route(task, route, host=host, port=port):
            blockers.append(compact_task(task))
    return _dedupe_blockers(blockers)


def port_owner_task(
    tasks: list[dict[str, Any]],
    *,
    host: str,
    port: int,
) -> dict[str, Any] | None:
    for task in tasks:
        if not _task_can_block(task):
            continue
        for resource in task.get("resources") or []:
            if (
                resource.get("kind") == "mcp_port"
                and int(resource.get("port") or 0) == port
                and _same_host(str(resource.get("host") or ""), host)
            ):
                return compact_task(task)
    return None


def background_blocker_message(blockers: list[dict[str, Any]]) -> str:
    if not blockers:
        return ""
    first = blockers[0]
    resources = _resource_phrase(first.get("resources") or [])
    if resources:
        return f"Background task {first['id']} is using {resources}."
    return f"Background task {first['id']} is active for this route."


def compact_task(task: dict[str, Any]) -> dict[str, Any]:
    keys = (
        "id",
        "status",
        "owner",
        "label",
        "row_id",
        "run_id",
        "route_id",
        "resource",
        "resources",
        "pid",
        "session_id",
        "container_id",
        "run_dir",
        "display_run_dir",
        "started_at",
        "started_at_epoch",
        "actions",
        "artifacts",
    )
    return {key: task[key] for key in keys if key in task and task[key] not in (None, "")}


def _operator_console_tasks(root: Path, *, include_recent_terminal: bool) -> list[dict[str, Any]]:
    output_root = console_output_root(root)
    runs_root = output_root / "runs"
    tasks: list[dict[str, Any]] = []
    if runs_root.is_dir():
        for state_path in _latest_paths(runs_root.glob("*/operator_state.json"), limit=100):
            if error_task := _json_source_error_task(root, state_path, owner="operator-console"):
                tasks.append(error_task)
                continue
            task = _operator_run_task(root, state_path.parent)
            if task and _include_task(task, include_recent_terminal=include_recent_terminal):
                tasks.append(task)
    locks_root = output_root / "locks"
    if locks_root.is_dir():
        for lock_path in sorted(locks_root.glob("*.json")):
            lock = ResourceLock(root, lock_path.stem).read()
            if not lock.held:
                continue
            if any(
                item.get("owner") == "operator-console" and item.get("run_id") == lock.owner_run_id
                for item in tasks
            ):
                continue
            resources = [_resource("backend_lock", lock.name, path=lock.path)]
            tasks.append(
                _task(
                    task_id=f"operator-lock:{lock.name}",
                    status="stale" if lock.stale else "unknown",
                    owner="operator-console",
                    label=f"Operator-console backend lock {lock.name}",
                    resource=f"backend lock {lock.name}",
                    resources=resources,
                    run_id=lock.owner_run_id,
                    pid=lock.pid,
                    started_at_epoch=lock.acquired_at,
                    artifacts=[_artifact(root, lock.path, "Lock JSON", kind="status")],
                )
            )
    return tasks


def _operator_run_task(root: Path, run_dir: Path) -> dict[str, Any] | None:
    state = _read_json(run_dir / "operator_state.json")
    if not state:
        return None
    display_run_dir = resolve_display_run_dir(run_dir)
    live_status = _read_json(display_run_dir / "live_status.json")
    phase = task_phase_from_paths(display_run_dir, state, read_json=_read_json)
    pid = _int_or_none(live_status.get("pid")) or _int_or_none(state.get("pid"))
    status = _status_from_phase(
        phase,
        pid=pid,
        tmux_session=_tmux_session_name(display_run_dir),
        has_child_evidence=display_run_dir != run_dir or _has_live_markers(display_run_dir),
    )
    active_task = _task_can_block({"status": status})
    route = state.get("route") if isinstance(state.get("route"), dict) else {}
    run_id = str(state.get("run_id") or run_dir.name)
    lock_name = str(state.get("backend_lock") or route.get("lock_name") or "")
    resources: list[dict[str, Any]] = []
    if lock_name:
        resources.append(
            _resource(
                "backend_lock",
                lock_name,
                path=console_output_root(root) / "locks" / f"{lock_name}.json",
                active=active_task,
            )
        )
    resources.extend(_run_dir_resources(display_run_dir))
    artifacts = _run_artifacts(root, run_dir, display_run_dir)
    actions = _run_actions(
        root,
        owner="operator-console",
        run_id=run_id,
        display_run_dir=display_run_dir,
        stop_available=active_task,
    )
    return _task(
        task_id=f"operator-run:{run_id}",
        status=status,
        owner="operator-console",
        label=str(route.get("label") or "Operator-console run"),
        resource=_primary_resource(resources),
        resources=resources,
        run_id=run_id,
        route_id=str(route.get("id") or ""),
        pid=pid,
        session_id=_tmux_session_name(display_run_dir),
        run_dir=run_dir,
        display_run_dir=display_run_dir,
        started_at=str(state.get("started_at") or ""),
        started_at_epoch=_float_or_none(state.get("started_at_epoch")),
        artifacts=artifacts,
        actions=actions,
    )


def _eval_harness_tasks(root: Path, *, include_recent_terminal: bool) -> list[dict[str, Any]]:
    harness_root = root / "output" / "eval-harness"
    if not harness_root.is_dir():
        return []
    tasks: list[dict[str, Any]] = []
    for manifest_path in _latest_paths(harness_root.glob("*/eval_harness.json"), limit=50):
        if error_task := _json_source_error_task(root, manifest_path, owner="eval-harness"):
            tasks.append(error_task)
            continue
        manifest = _read_json(manifest_path)
        for row in manifest.get("rows") or []:
            if not isinstance(row, dict) or not row.get("row_dir"):
                continue
            task = _eval_row_task(root, row, manifest_path)
            if task and _include_task(task, include_recent_terminal=include_recent_terminal):
                tasks.append(task)
    return tasks


def _eval_row_task(root: Path, row: dict[str, Any], manifest_path: Path) -> dict[str, Any] | None:
    row_dir = _resolve_under_root(root, row.get("row_dir"))
    if row_dir is None or not row_dir.exists():
        return None
    run_root = row_dir / "run"
    display_run_dir = resolve_display_run_dir(run_root if run_root.exists() else row_dir)
    if not _has_live_markers(display_run_dir):
        return None
    live_status = _read_json(display_run_dir / "live_status.json")
    phase = str(live_status.get("phase") or row.get("outcome") or row.get("status") or "unknown")
    pid = _server_pid(display_run_dir) or _int_or_none(live_status.get("pid"))
    session = _tmux_session_name(display_run_dir)
    resources = _run_dir_resources(display_run_dir)
    axes = row.get("axes") if isinstance(row.get("axes"), dict) else {}
    route_id = _route_id_from_axes(axes)
    artifacts = [
        _artifact(root, manifest_path, "Eval harness manifest", kind="status"),
        _artifact(root, row_dir / "stdout.log", "Stdout", kind="log"),
        _artifact(root, row_dir / "stderr.log", "Stderr", kind="log"),
        *_run_artifacts(root, row_dir, display_run_dir),
    ]
    status = _status_from_phase(
        phase,
        pid=pid,
        tmux_session=session,
        has_live_resource=_has_active_resource(resources),
    )
    actions = _run_actions(
        root,
        owner="eval-harness",
        display_run_dir=display_run_dir,
        require_live_tmux=True,
    )
    return _task(
        task_id=f"eval-row:{row.get('row_id')}",
        status=status,
        owner="eval-harness",
        label=f"Eval harness row {row.get('row_id')}",
        resource=_primary_resource(resources),
        resources=resources,
        row_id=str(row.get("row_id") or ""),
        route_id=route_id,
        pid=pid,
        session_id=session,
        run_dir=row_dir,
        display_run_dir=display_run_dir,
        artifacts=[item for item in artifacts if item],
        actions=actions,
    )


def _visual_slot_tasks(root: Path) -> list[dict[str, Any]]:
    tasks: list[dict[str, Any]] = []
    try:
        slots = list_visual_backend_slots(repo_root=root)
    except VisualBackendSlotError as exc:
        return [_visual_slot_config_error_task(root, exc)]
    for slot in slots:
        if not slot.held:
            continue
        run_dir = _resolve_under_root(root, slot.output_dir)
        resources = [
            _resource(
                "visual_slot",
                f"Molmo visual slot {slot.slot_id}",
                path=slot.path,
                slot_id=slot.slot_id,
                port=slot.port,
                active=not slot.stale,
            )
        ]
        if slot.port:
            resources.append(
                _resource(
                    "mcp_port",
                    f"{DEFAULT_MCP_HOST}:{slot.port}",
                    host=DEFAULT_MCP_HOST,
                    port=slot.port,
                    active=not slot.stale,
                )
            )
        tasks.append(
            _task(
                task_id=f"visual-slot:{slot.slot_id}",
                status="stale" if slot.stale else "running",
                owner="molmo-live",
                label=f"Molmo visual backend slot {slot.slot_id}",
                resource=f"Molmo visual slot {slot.slot_id}",
                resources=resources,
                run_id=slot.run_id,
                pid=slot.pid,
                run_dir=run_dir,
                display_run_dir=run_dir,
                started_at_epoch=slot.acquired_at,
                artifacts=[
                    _artifact(root, slot.path, "Visual slot JSON", kind="status"),
                    _artifact(root, Path(slot.status_path), "Live status", kind="status"),
                ],
                actions=_run_actions(
                    root,
                    owner="molmo-live",
                    display_run_dir=run_dir,
                    require_live_tmux=True,
                ),
            )
        )
    return tasks


def _visual_slot_config_error_task(root: Path, error: VisualBackendSlotError) -> dict[str, Any]:
    message = f"MolmoSpaces visual backend slot config is invalid: {error}"
    return _task(
        task_id="source-error:molmo-live:visual-backend-slot-config",
        status="source_error",
        owner="molmo-live",
        label="Invalid MolmoSpaces visual backend slot config",
        resource="invalid MolmoSpaces visual backend slot config",
        resources=[
            _resource(
                "source_error",
                message,
                path=root / "output" / "molmo" / "visual-backend-slots",
                active=False,
                error_reason="invalid_config",
            )
        ],
        extra={
            "error_reason": "invalid_config",
            "message": message,
        },
    )


def _tmux_tasks(root: Path) -> list[dict[str, Any]]:
    result = _run_command(["tmux", "list-sessions", "-F", "#{session_name}\t#{session_created}"])
    if result is None:
        return []
    tasks: list[dict[str, Any]] = []
    for line in result.stdout.splitlines():
        parts = line.split("\t")
        name = parts[0].strip() if parts else ""
        if not _repo_tmux_session(name):
            continue
        started = _float_or_none(parts[1] if len(parts) > 1 else None)
        resources = [_resource("tmux_session", name, session_id=name, active=True)]
        tasks.append(
            _task(
                task_id=f"tmux:{name}",
                status="running",
                owner="manual-tmux",
                label=f"tmux session {name}",
                resource=f"tmux session {name}",
                resources=resources,
                session_id=name,
                started_at_epoch=started,
            )
        )
    return tasks


def _port_owner_tasks(root: Path, ports: list[int]) -> list[dict[str, Any]]:
    tasks: list[dict[str, Any]] = []
    for port in ports:
        if _tcp_port_free(DEFAULT_MCP_HOST, port):
            continue
        owner = _listening_pid(port)
        resources = [
            _resource(
                "mcp_port",
                f"{DEFAULT_MCP_HOST}:{port}",
                host=DEFAULT_MCP_HOST,
                port=port,
                active=True,
            )
        ]
        tasks.append(
            _task(
                task_id=f"port:{DEFAULT_MCP_HOST}:{port}",
                status="running",
                owner="port-owner",
                label=f"MCP port owner {DEFAULT_MCP_HOST}:{port}",
                resource=f"MCP port {DEFAULT_MCP_HOST}:{port}",
                resources=resources,
                pid=owner,
            )
        )
    return tasks


def _docker_tasks(root: Path) -> list[dict[str, Any]]:
    result = _run_command(
        ["docker", "ps", "--format", "{{.ID}}\t{{.Names}}\t{{.Image}}\t{{.Status}}"]
    )
    if result is None:
        return []
    tasks: list[dict[str, Any]] = []
    for line in result.stdout.splitlines():
        container_id, name, image, status = _split_docker_ps(line)
        if not container_id:
            continue
        mounts, source_error = _docker_mount_sources(container_id)
        if source_error:
            tasks.append(
                _docker_mount_source_error_task(
                    container_id=container_id,
                    name=name,
                    image=image,
                    status=status,
                    source_error=source_error,
                )
            )
            continue
        if not any(_path_is_repo_relevant(root, mount) for mount in mounts):
            continue
        resources = [
            _resource(
                "docker_container",
                name or container_id,
                container_id=container_id,
                active=True,
            )
        ]
        tasks.append(
            _task(
                task_id=f"docker:{container_id}",
                status="running",
                owner="docker",
                label=f"Docker container {name or container_id}",
                resource=f"Docker container {name or container_id}",
                resources=resources,
                container_id=container_id,
                artifacts=[],
                extra={"image": image, "docker_status": status},
            )
        )
    return tasks


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
                    active=not _tcp_port_free(DEFAULT_MCP_HOST, port),
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
    container_id: str = "",
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
        "container_id": container_id,
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
    if normalized in TERMINAL_RUN_PHASES:
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
    if port and _tcp_port_free(DEFAULT_MCP_HOST, port):
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


def _task_can_block(task: dict[str, Any]) -> bool:
    return str(task.get("status") or "") in ACTIVE_STATUSES


def _has_ui_e2e_blocking_resource(task: dict[str, Any]) -> bool:
    blocking_kinds = {
        "backend_lock",
        "mcp_port",
        "visual_slot",
        "tmux_session",
        "docker_container",
    }
    for resource in task.get("resources") or []:
        if resource.get("active") is False:
            continue
        if resource.get("kind") in blocking_kinds:
            return True
    return False


def _task_has_source_error(task: dict[str, Any]) -> bool:
    if task.get("status") == "source_error":
        return True
    return any(resource.get("kind") == "source_error" for resource in task.get("resources") or [])


def _task_blocks_route(
    task: dict[str, Any],
    route: ConsoleLaunchSelection,
    *,
    host: str,
    port: int,
) -> bool:
    for resource in task.get("resources") or []:
        if resource.get("active") is False:
            continue
        kind = resource.get("kind")
        if kind == "backend_lock" and resource.get("label") == route.lock_name:
            return True
        if (
            kind == "mcp_port"
            and int(resource.get("port") or 0) == port
            and _same_host(str(resource.get("host") or ""), host)
        ):
            return True
        if kind == "visual_slot" and _route_uses_molmo_live_visual(route):
            return True
        if (
            kind == "tmux_session"
            and _route_uses_sdk_molmo_singleton(route)
            and str(resource.get("session_id") or resource.get("label") or "").startswith(
                "roboclaws-molmo-openai-agents-sdk-"
            )
        ):
            return True
    return False


def _route_uses_molmo_live_visual(route: ConsoleLaunchSelection) -> bool:
    return (
        route.world_id.startswith("molmospaces/")
        and route.backend_id == "mujoco"
        and route.agent_engine_id == "openai-agents-sdk"
    )


def _route_uses_sdk_molmo_singleton(route: ConsoleLaunchSelection) -> bool:
    return False


def _resource_phrase(resources: list[dict[str, Any]]) -> str:
    labels = [str(item.get("label") or "") for item in resources if item.get("label")]
    return " and ".join(labels[:3])


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


def _dedupe_blockers(blockers: list[dict[str, Any]]) -> list[dict[str, Any]]:
    seen: set[str] = set()
    output: list[dict[str, Any]] = []
    for blocker in blockers:
        task_id = str(blocker.get("id") or "")
        if task_id in seen:
            continue
        seen.add(task_id)
        output.append(blocker)
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
    epoch = _float_or_none(task.get("started_at_epoch")) or _mtime_for_task(task)
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


def _latest_paths(paths: Any, *, limit: int) -> list[Path]:
    existing = [path for path in paths if path.is_file()]
    existing.sort(key=lambda item: item.stat().st_mtime, reverse=True)
    return existing[:limit]


def _has_live_markers(path: Path) -> bool:
    return any((path / marker).exists() for marker in LIVE_MARKERS)


def _tmux_session_name(display_run_dir: Path | None) -> str:
    if display_run_dir is None:
        return ""
    path = display_run_dir / "tmux_session.txt"
    if not path.is_file():
        return ""
    try:
        return path.read_text(encoding="utf-8", errors="replace").strip()
    except OSError:
        return ""


def _server_pid(display_run_dir: Path | None) -> int | None:
    if display_run_dir is None:
        return None
    path = display_run_dir / "server.pid"
    if not path.is_file():
        return None
    try:
        value = int(path.read_text(encoding="utf-8").strip())
    except (OSError, ValueError):
        return None
    return value if value > 0 else None


def _repo_tmux_session(name: str) -> bool:
    return name.startswith(("roboclaws-molmo-", "roboclaws-agibot-", "roboclaws-"))


def _tmux_session_exists(name: str) -> bool:
    if not name:
        return False
    result = _run_command(["tmux", "has-session", "-t", name])
    return result is not None and result.returncode == 0


def _tcp_port_free(host: str, port: int) -> bool:
    try:
        with socket.create_connection((host, port), timeout=0.2):
            return False
    except OSError:
        return True


def _listening_pid(port: int) -> int | None:
    result = _run_command(["lsof", "-nP", f"-iTCP:{port}", "-sTCP:LISTEN", "-Fp"])
    if result is None:
        return None
    for line in result.stdout.splitlines():
        if line.startswith("p") and line[1:].isdigit():
            return int(line[1:])
    return None


def _run_command(command: list[str]) -> Any | None:
    try:
        return subprocess.run(
            command,
            check=False,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            text=True,
            timeout=1.0,
        )
    except (FileNotFoundError, OSError, subprocess.TimeoutExpired):
        return None


def _split_docker_ps(line: str) -> tuple[str, str, str, str]:
    parts = line.split("\t")
    parts.extend([""] * (4 - len(parts)))
    return parts[0], parts[1], parts[2], parts[3]


def _docker_mount_sources(container_id: str) -> tuple[list[Path], str]:
    try:
        return docker_container_mount_sources(container_id, run_command=subprocess.run), ""
    except DockerMountSourceError as exc:
        return [], _docker_mount_source_error_reason(exc)


def _docker_mount_source_error_reason(error: DockerMountSourceError) -> str:
    message = str(error)
    if "contain invalid JSON" in message:
        return "invalid_json"
    if "must be a JSON array" in message:
        return "invalid_json_array"
    object_marker = "must contain JSON objects; got "
    if object_marker in message:
        return f"invalid_json_object:{message.rsplit(object_marker, 1)[1]}"
    return "invalid_docker_mounts"


def _docker_mount_source_error_task(
    *,
    container_id: str,
    name: str,
    image: str,
    status: str,
    source_error: str,
) -> dict[str, Any]:
    label = f"Docker container {name or container_id} mount metadata source error"
    message = f"docker inspect mounts for {container_id} are unreadable: {source_error}"
    return _task(
        task_id=f"source-error:docker:{container_id}:mounts",
        status="source_error",
        owner="docker",
        label=label,
        resource=message,
        resources=[
            _resource(
                "source_error",
                message,
                active=False,
                error_reason="invalid_docker_mounts",
                container_id=container_id,
            )
        ],
        container_id=container_id,
        extra={
            "image": image,
            "docker_status": status,
            "error_reason": "invalid_docker_mounts",
            "message": message,
        },
    )


def _path_is_repo_relevant(root: Path, path: Path) -> bool:
    try:
        path.relative_to(root)
        return True
    except ValueError:
        return False


def _host_probe_enabled(root: Path) -> bool:
    return (root / "pyproject.toml").is_file() and (root / "roboclaws").is_dir()


def _resolve_under_root(root: Path, value: Any) -> Path | None:
    text = str(value or "").strip()
    if not text:
        return None
    path = Path(text)
    if not path.is_absolute():
        path = root / path
    try:
        return path.resolve()
    except OSError:
        return path


def _relative_to_root(root: Path, path: Path) -> str:
    try:
        return path.resolve().relative_to(root).as_posix()
    except (OSError, ValueError):
        return ""


def _same_host(left: str, right: str) -> bool:
    normalize = {"0.0.0.0": "127.0.0.1", "::": "127.0.0.1", "localhost": "127.0.0.1"}
    return normalize.get(left, left) == normalize.get(right, right)


def _parse_port(value: str) -> int:
    try:
        port = int(str(value).strip())
    except ValueError:
        return DEFAULT_MCP_PORT
    if not 1 <= port <= 65535:
        return DEFAULT_MCP_PORT
    return port


def _int_or_none(value: Any) -> int | None:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return None
    return parsed if parsed > 0 else None


def _float_or_none(value: Any) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _age_seconds(started_at_epoch: float | None) -> float | None:
    if started_at_epoch is None:
        return None
    return max(0.0, time.time() - started_at_epoch)


def _recent_epoch(value: Any, *, window_s: float) -> bool:
    epoch = _float_or_none(value)
    return bool(epoch and time.time() - epoch <= window_s)


def _dedupe_ints(values: list[int]) -> list[int]:
    output: list[int] = []
    for value in values:
        if value not in output:
            output.append(value)
    return output
