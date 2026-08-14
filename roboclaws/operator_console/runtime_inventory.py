"""Composition and public API for operator-console runtime inventory."""

from __future__ import annotations

import time
from pathlib import Path
from typing import Any

from roboclaws.operator_console import runtime_host_probes
from roboclaws.operator_console.runtime_blocker_policy import runtime_blockers_from_inventory
from roboclaws.operator_console.runtime_host_probes import _dedupe_ints, _host_probe_enabled
from roboclaws.operator_console.runtime_inventory_sources import (
    _eval_harness_tasks,
    _operator_console_tasks,
    _port_owner_tasks,
    _tmux_tasks,
    _visual_slot_tasks,
)
from roboclaws.operator_console.runtime_task_model import (
    _dedupe_tasks,
    _sort_key,
    _summary,
)


def runtime_inventory_payload(
    root: Path,
    *,
    ports: list[int] | None = None,
    include_recent_terminal: bool = True,
) -> dict[str, Any]:
    """Return a redacted inventory of repo-relevant local background tasks."""

    root = root.resolve()
    port_list = _dedupe_ints([runtime_host_probes.DEFAULT_MCP_PORT] if ports is None else ports)
    tasks: list[dict[str, Any]] = []
    tasks.extend(_operator_console_tasks(root, include_recent_terminal=include_recent_terminal))
    tasks.extend(_eval_harness_tasks(root, include_recent_terminal=include_recent_terminal))
    tasks.extend(_visual_slot_tasks(root))
    if _host_probe_enabled(root):
        tasks.extend(_tmux_tasks(root))
        tasks.extend(_port_owner_tasks(root, port_list))
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
