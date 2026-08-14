"""Route-aware blocker policy for runtime inventory tasks."""

from __future__ import annotations

import time
from typing import Any

from roboclaws.mcp.endpoint import DEFAULT_MCP_HOST, DEFAULT_MCP_PORT
from roboclaws.operator_console.launch_contract import ConsoleLaunchError
from roboclaws.operator_console.routes import ConsoleLaunchSelection
from roboclaws.operator_console.runtime_host_probes import (
    _same_host,
)
from roboclaws.operator_console.runtime_task_model import _summary, _task_can_block


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
    raw_port = str(overrides.get("port") or DEFAULT_MCP_PORT)
    try:
        port = int(raw_port.strip())
    except ValueError as exc:
        raise ConsoleLaunchError(f"invalid MCP port: {raw_port}") from exc
    if not 1 <= port <= 65535:
        raise ConsoleLaunchError(f"invalid MCP port: {raw_port}")
    return host, port


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
        "run_dir",
        "display_run_dir",
        "started_at",
        "started_at_epoch",
        "actions",
        "artifacts",
    )
    return {key: task[key] for key in keys if key in task and task[key] not in (None, "")}


def _has_ui_e2e_blocking_resource(task: dict[str, Any]) -> bool:
    blocking_kinds = {
        "backend_lock",
        "mcp_port",
        "visual_slot",
        "tmux_session",
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
