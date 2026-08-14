"""Filesystem, runtime-slot, tmux, and port inventory sources."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from roboclaws.agents.visual_backend_slots import (
    VisualBackendSlotError,
    list_visual_backend_slots,
)
from roboclaws.household.household_mcp_endpoint import DEFAULT_MCP_HOST
from roboclaws.operator_console.locks import ResourceLock
from roboclaws.operator_console.paths import console_output_root
from roboclaws.operator_console.runtime_compat import float_or_none
from roboclaws.operator_console.runtime_host_probes import (
    _has_live_markers,
    _int_or_none,
    _latest_paths,
    _listening_pid,
    _repo_tmux_session,
    _resolve_under_root,
    _run_command,
    _server_pid,
    _tcp_port_free,
    _tmux_session_name,
)
from roboclaws.operator_console.runtime_task_model import (
    _artifact,
    _has_active_resource,
    _include_task,
    _json_source_error_task,
    _primary_resource,
    _read_json,
    _resource,
    _route_id_from_axes,
    _run_actions,
    _run_artifacts,
    _run_dir_resources,
    _status_from_phase,
    _task,
    _task_can_block,
)
from roboclaws.operator_console.state import resolve_display_run_dir
from roboclaws.operator_console.state_summary import task_phase_from_paths


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
        started_at_epoch=float_or_none(state.get("started_at_epoch")),
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
        started = float_or_none(parts[1] if len(parts) > 1 else None)
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
