"""Backend/lifecycle glue for layered Molmo cleanup MCP tools."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from roboclaws.household.raw_fpv_recovery import raw_fpv_recovery_gate
from roboclaws.household.realworld_mcp_atomic_tools import (
    ATOMIC_CLEANUP_TOOL_NAMES,
    atomic_cleanup_handlers,
    register_atomic_cleanup_tools,
)
from roboclaws.household.realworld_mcp_semantic_tools import (
    AGENT_SDK_CAMERA_GROUNDED_COMPOSITE_TOOL_NAMES,
    SEMANTIC_CLEANUP_TOOL_NAMES,
    agent_sdk_camera_grounded_composite_handlers,
    register_agent_sdk_camera_grounded_composite_tools,
    register_semantic_cleanup_tools,
    semantic_cleanup_handlers,
)


def register_realworld_mcp_tools(server: Any) -> None:
    """Register public tools in explicit layer order."""

    register_semantic_cleanup_tools(server)
    register_atomic_cleanup_tools(server)
    register_lifecycle_tools(server)
    if _agent_sdk_camera_grounded_composite_enabled(server):
        register_agent_sdk_camera_grounded_composite_tools(server)


def register_lifecycle_tools(server: Any) -> None:
    @server._mcp.tool()
    def check_operator_messages(max_messages: int = 10) -> dict:
        """Read queued public operator steering messages at a safe checkpoint."""
        return server.call_tool("check_operator_messages", max_messages=max_messages)

    @server._mcp.tool()
    def done(reason: str) -> dict:
        """Finish the run and write trace, run_result, and report."""
        return server.call_tool("done", reason=reason)


def dispatch_realworld_mcp_tool(
    server: Any,
    name: str,
    kwargs: dict[str, Any],
) -> dict[str, Any]:
    validate_realworld_mcp_tool_call(server, name)
    if server.done_event.is_set() and name != "done":
        return {"ok": False, "tool": name, "status": "error", "error_reason": "run_done"}

    trace_events = server._read_trace_events()
    recovery_response = raw_fpv_recovery_gate(
        trace_events[:-1],
        evidence_lane=str(server.evidence_lane or ""),
        task_intent=str(server.task_intent or ""),
        tool=name,
        request=kwargs,
    )
    if recovery_response is not None:
        return recovery_response

    handlers = tool_handlers_for_call(server, kwargs)
    return handlers[name]()


def validate_realworld_mcp_tool_call(server: Any, name: str) -> None:
    if name == "scene_objects":
        raise ValueError("scene_objects is not part of the ADR-0003 real-world MCP contract")
    if name in _extra_tool_names_for_server(server):
        return
    if name not in public_tool_names_for_evidence_lane(server.evidence_lane):
        raise ValueError(f"unknown Molmo real-world cleanup MCP tool {name!r}")


def public_tool_names_for_evidence_lane(
    evidence_lane: str | None,
) -> tuple[str, ...]:
    return (
        *SEMANTIC_CLEANUP_TOOL_NAMES,
        *ATOMIC_CLEANUP_TOOL_NAMES,
        "check_operator_messages",
        "done",
    )


def tool_handlers_for_call(
    server: Any,
    kwargs: dict[str, Any],
) -> dict[str, Callable[[], dict[str, Any]]]:
    def done() -> dict[str, Any]:
        readiness_evidence = getattr(server, "done_readiness_evidence", None)
        evidence = readiness_evidence() if callable(readiness_evidence) else {}
        return server.contract.done(
            str(kwargs.get("reason", "")),
            semantic_cleanup_evidence=evidence,
        )

    def check_operator_messages() -> dict[str, Any]:
        return server.check_operator_messages(int(kwargs.get("max_messages") or 10))

    return {
        **semantic_cleanup_handlers(server, kwargs),
        **atomic_cleanup_handlers(server, kwargs),
        **agent_sdk_camera_grounded_composite_handlers(server, kwargs),
        "check_operator_messages": check_operator_messages,
        "done": done,
    }


def agent_view_public_tool_names(server: Any, base_tool_names: list[str]) -> list[str]:
    return [*base_tool_names, *_extra_tool_names_for_server(server)]


def _extra_tool_names_for_server(server: Any) -> tuple[str, ...]:
    if _agent_sdk_camera_grounded_composite_enabled(server):
        return AGENT_SDK_CAMERA_GROUNDED_COMPOSITE_TOOL_NAMES
    return ()


def _agent_sdk_camera_grounded_composite_enabled(server: Any) -> bool:
    return bool(getattr(server, "agent_sdk_camera_grounded_composite_tools", False))
