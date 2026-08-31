"""Backend and lifecycle glue for profile-composed household MCP tools."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from roboclaws.core.raw_fpv_recovery import raw_fpv_recovery_gate
from roboclaws.household.realworld_mcp_atomic_tools import (
    atomic_cleanup_handlers,
    register_atomic_cleanup_tools,
)
from roboclaws.household.realworld_mcp_semantic_tools import (
    agent_sdk_camera_grounded_composite_handlers,
    register_agent_sdk_camera_grounded_composite_tools,
    register_semantic_cleanup_tools,
    semantic_cleanup_handlers,
)
from roboclaws.mcp.entrypoint import MCPProfileRouter
from roboclaws.mcp.profiles import (
    HOUSEHOLD_EPISODE_PROFILE,
    HOUSEHOLD_MANIPULATION_PROFILE,
    HOUSEHOLD_WORLD_PROFILE,
)


def register_household_mcp_tools(server: Any) -> None:
    """Register exactly the immutable capability-profile union for this run."""

    handlers = tool_handlers_for_call(server, {})
    router = MCPProfileRouter(
        server.required_capability_profiles,
        handlers,
        allow_extra_handlers=True,
    )
    registrars = {
        HOUSEHOLD_WORLD_PROFILE: register_semantic_cleanup_tools,
        HOUSEHOLD_MANIPULATION_PROFILE: register_atomic_cleanup_tools,
        HOUSEHOLD_EPISODE_PROFILE: register_lifecycle_tools,
    }
    registered = tuple(
        name
        for profile_id in server.required_capability_profiles
        for name in registrars[profile_id](server)
    )
    composite_enabled = (
        bool(getattr(server, "agent_sdk_camera_grounded_composite_tools", False))
        and str(getattr(server, "evidence_lane", "") or "") == "camera-grounded-labels"
    )
    if composite_enabled:
        register_agent_sdk_camera_grounded_composite_tools(server)
        registered += ("observe_camera_grounded_candidates",)
    if registered != router.public_tool_names() + (
        ("observe_camera_grounded_candidates",) if composite_enabled else ()
    ):
        raise AssertionError("household MCP registration drifted from composed profile tools")
    server.registered_public_tool_names = registered


def register_lifecycle_tools(server: Any) -> tuple[str, ...]:
    @server._mcp.tool()
    def check_operator_messages(max_messages: int = 10) -> dict:
        """Read queued public operator steering messages at a safe checkpoint."""
        return server.call_tool("check_operator_messages", max_messages=max_messages)

    @server._mcp.tool()
    def done(reason: str) -> dict:
        """Finish the run and write trace, run_result, and report."""
        return server.call_tool("done", reason=reason)

    return ("check_operator_messages", "done")


def dispatch_household_mcp_tool(
    server: Any,
    name: str,
    kwargs: dict[str, Any],
) -> dict[str, Any]:
    validate_household_mcp_tool_call(server, name)
    if server.done_event.is_set() and name != "done":
        return {"ok": False, "tool": name, "status": "error", "error_reason": "run_done"}

    trace_events = server._read_trace_events()
    recovery_response = raw_fpv_recovery_gate(
        _completion_recovery_events(trace_events[:-1]),
        evidence_lane=str(server.evidence_lane or ""),
        task_intent=str(server.task_intent or ""),
        tool=name,
        request=kwargs,
    )
    if recovery_response is not None:
        return recovery_response

    handlers = tool_handlers_for_call(server, kwargs)
    return handlers[name]()


def _completion_recovery_events(trace_events: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Adapt canonical completion snapshots to the existing pure recovery policy."""

    adapted = []
    recovery_started = False
    for event in trace_events:
        response = event.get("response")
        completion = response.get("completion") if isinstance(response, dict) else None
        blockers = completion.get("blockers") if isinstance(completion, dict) else []
        recovery_started = recovery_started or any(
            isinstance(blocker, dict)
            and blocker.get("type") == "insufficient_raw_fpv_overlap_probe_coverage"
            for blocker in blockers or []
        )
        if (
            recovery_started
            and event.get("event") == "response"
            and event.get("tool") != "done"
            and isinstance(completion, dict)
            and completion.get("schema") == "household_completion_snapshot_v1"
            and completion.get("status") == "blocked"
        ):
            adapted.append(event)
            event = {**event, "tool": "done", "response": {**response, "ok": False}}
        adapted.append(event)
    return adapted


def validate_household_mcp_tool_call(server: Any, name: str) -> None:
    if name == "scene_objects":
        raise ValueError("scene_objects is not part of the ADR-0003 real-world MCP contract")
    if name not in server.registered_public_tool_names:
        raise ValueError(f"MCP tool {name!r} is not entitled for this Robot Run")


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
