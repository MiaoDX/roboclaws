"""Semantic/context Molmo cleanup MCP tools.

These tools expose public map, waypoint, observation, and visual-grounding
services. They are broader than single actuator primitives, but still describe
bounded robot capabilities rather than whole cleanup tasks.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from roboclaws.household.household_runtime_contract import (
    CAMERA_MODEL_POLICY_MODE,
    MAIN_CLEANUP_AGENT_PRODUCER,
    SIMULATED_CAMERA_MODEL_PROVENANCE,
)

SEMANTIC_CLEANUP_TOOL_NAMES = (
    "metric_map",
    "navigate_to_room",
    "navigate_to_waypoint",
    "navigate_to_relative_pose",
    "observe",
    "adjust_camera",
    "declare_visual_candidates",
    "navigate_to_visual_candidate",
    "inspect_visible_object",
    "resolve_target_query",
)
AGENT_SDK_CAMERA_GROUNDED_COMPOSITE_TOOL_NAMES = ("observe_camera_grounded_candidates",)


def register_semantic_cleanup_tools(server: Any) -> tuple[str, ...]:
    """Register context, navigation, observation, and visual-grounding tools."""
    _register_map_navigation_tools(server)
    _register_observation_tools(server)
    _register_visual_grounding_tools(server)
    _register_target_resolution_tools(server)
    return SEMANTIC_CLEANUP_TOOL_NAMES


def _register_map_navigation_tools(server: Any) -> None:
    """Register public map and navigation context tools."""

    @server._mcp.tool()
    def metric_map() -> dict:
        """Return public room topology and inspection waypoints."""
        return server.call_tool("metric_map")

    @server._mcp.tool()
    def navigate_to_room(room_id: str) -> dict:
        """Navigate to the first public waypoint in a room."""
        return server.call_tool("navigate_to_room", room_id=room_id)

    @server._mcp.tool()
    def navigate_to_waypoint(waypoint_id: str) -> dict:
        """Navigate to a public inspection waypoint before observing."""
        return server.call_tool("navigate_to_waypoint", waypoint_id=waypoint_id)

    @server._mcp.tool()
    def navigate_to_relative_pose(
        forward_m: float = 0.0,
        lateral_m: float = 0.0,
        yaw_delta_deg: float = 0.0,
    ) -> dict:
        """Move or turn by a bounded robot-local pose delta before observing."""
        return server.call_tool(
            "navigate_to_relative_pose",
            forward_m=forward_m,
            lateral_m=lateral_m,
            yaw_delta_deg=yaw_delta_deg,
        )


def _register_observation_tools(server: Any) -> None:
    """Register public observation and camera-control tools."""

    @server._mcp.tool()
    def observe() -> Any:
        """Observe robot-local visible objects at the current waypoint."""
        return server._mcp_observe_response()

    @server._mcp.tool()
    def adjust_camera(yaw_delta_deg: float = 0.0, pitch_delta_deg: float = 0.0) -> dict:
        """Adjust bounded active camera yaw/pitch at the current waypoint."""
        return server.call_tool(
            "adjust_camera",
            yaw_delta_deg=yaw_delta_deg,
            pitch_delta_deg=pitch_delta_deg,
        )


def _register_visual_grounding_tools(server: Any) -> None:
    """Register visual-grounding declaration and navigation tools."""

    @server._mcp.tool()
    def declare_visual_candidates(
        observation_id: str = "",
        candidates: list[dict[str, Any]] | None = None,
        producer_type: str = "",
        producer_id: str = "",
    ) -> dict:
        """Register model-declared cleanup candidates from raw FPV evidence."""
        return server.call_tool(
            "declare_visual_candidates",
            observation_id=observation_id,
            candidates=candidates or [],
            producer_type=producer_type,
            producer_id=producer_id,
        )

    @server._mcp.tool()
    def navigate_to_visual_candidate(
        source_observation_id: str = "",
        category: str = "",
        target_fixture_id: str = "",
        evidence_note: str = "",
        image_region: dict[str, Any] | str | None = None,
        source_fixture_id: str = "",
        confidence: float | None = None,
    ) -> dict:
        """Declare one visual candidate and navigate to it when grounded."""
        return server.call_tool(
            "navigate_to_visual_candidate",
            source_observation_id=source_observation_id,
            category=category,
            target_fixture_id=target_fixture_id,
            evidence_note=evidence_note,
            image_region=image_region,
            source_fixture_id=source_fixture_id,
            confidence=confidence,
        )


def _register_target_resolution_tools(server: Any) -> None:
    """Register observed-object inspection and runtime-map query tools."""

    @server._mcp.tool()
    def inspect_visible_object(object_id: str) -> dict:
        """Inspect a previously observed object handle."""
        return server.call_tool("inspect_visible_object", object_id=object_id)

    @server._mcp.tool()
    def resolve_target_query(
        query: str,
        operation: str = "inspect",
        max_results: int = 8,
    ) -> dict:
        """Resolve a target query against public runtime-map target candidates."""
        return server.call_tool(
            "resolve_target_query",
            query=query,
            operation=operation,
            max_results=max_results,
        )


def register_agent_sdk_camera_grounded_composite_tools(server: Any) -> None:
    """Register opt-in private Agent SDK camera-grounded shortcuts."""

    @server._mcp.tool()
    def observe_camera_grounded_candidates() -> dict:
        """Observe and register configured camera-grounded candidates in one call."""
        return server.call_tool("observe_camera_grounded_candidates")


def semantic_cleanup_handlers(
    server: Any,
    kwargs: dict[str, Any],
) -> dict[str, Callable[[], dict[str, Any]]]:
    return {
        "metric_map": server.contract.metric_map,
        "navigate_to_room": lambda: server.contract.navigate_to_room(
            str(kwargs.get("room_id", ""))
        ),
        "navigate_to_waypoint": lambda: server.contract.navigate_to_waypoint(
            str(kwargs.get("waypoint_id", ""))
        ),
        "navigate_to_relative_pose": lambda: server.contract.navigate_to_relative_pose(
            kwargs.get("forward_m") or 0.0,
            kwargs.get("lateral_m") or 0.0,
            kwargs.get("yaw_delta_deg") or 0.0,
        ),
        "observe": server.contract.observe,
        "adjust_camera": lambda: server.contract.adjust_camera(
            float(kwargs.get("yaw_delta_deg") or 0.0),
            float(kwargs.get("pitch_delta_deg") or 0.0),
        ),
        "declare_visual_candidates": lambda: server.contract.declare_visual_candidates(
            str(kwargs.get("observation_id", "")),
            candidates=list(kwargs.get("candidates") or []),
            producer_type=str(
                kwargs.get("producer_type")
                or (
                    SIMULATED_CAMERA_MODEL_PROVENANCE
                    if server.perception_mode == CAMERA_MODEL_POLICY_MODE
                    else MAIN_CLEANUP_AGENT_PRODUCER
                )
            ),
            producer_id=str(
                kwargs.get("producer_id")
                or (
                    "camera_labels_agent"
                    if server.perception_mode == CAMERA_MODEL_POLICY_MODE
                    else "cleanup_agent"
                )
            ),
        ),
        "navigate_to_visual_candidate": lambda: server.contract.navigate_to_visual_candidate(
            str(kwargs.get("source_observation_id", "")),
            category=str(kwargs.get("category", "")),
            target_fixture_id=str(kwargs.get("target_fixture_id", "")),
            evidence_note=str(kwargs.get("evidence_note", "")),
            image_region=kwargs.get("image_region"),
            source_fixture_id=str(kwargs.get("source_fixture_id", "")),
            confidence=kwargs.get("confidence"),
        ),
        "inspect_visible_object": lambda: server.contract.inspect_visible_object(
            str(kwargs.get("object_id", ""))
        ),
        "resolve_target_query": lambda: server.contract.resolve_target_query(
            str(kwargs.get("query", "")),
            operation=str(kwargs.get("operation", "inspect")),
            max_results=int(kwargs.get("max_results") or 8),
        ),
    }


def agent_sdk_camera_grounded_composite_handlers(
    server: Any,
    _kwargs: dict[str, Any],
) -> dict[str, Callable[[], dict[str, Any]]]:
    return {
        "observe_camera_grounded_candidates": server.observe_camera_grounded_candidates,
    }
