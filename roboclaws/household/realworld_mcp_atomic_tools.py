"""Atomic public cleanup MCP tools."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

ATOMIC_CLEANUP_TOOL_NAMES = (
    "navigate_to_object",
    "pick",
    "navigate_to_receptacle",
    "open_receptacle",
    "place",
    "place_inside",
    "close_receptacle",
)


def register_atomic_cleanup_tools(server: Any) -> tuple[str, ...]:
    """Register object/receptacle manipulation tools."""

    @server._mcp.tool()
    def navigate_to_object(object_id: str) -> dict:
        """Navigate to a previously observed object handle before pick."""
        return server.call_tool("navigate_to_object", object_id=object_id)

    @server._mcp.tool()
    def pick(object_id: str) -> dict:
        """Pick one previously observed object handle."""
        return server.call_tool("pick", object_id=object_id)

    @server._mcp.tool()
    def navigate_to_receptacle(fixture_id: str) -> dict:
        """Navigate to a public fixture before place or place_inside."""
        return server.call_tool("navigate_to_receptacle", fixture_id=fixture_id)

    @server._mcp.tool()
    def open_receptacle(fixture_id: str) -> dict:
        """Open fridge-like public fixtures before place_inside."""
        return server.call_tool("open_receptacle", fixture_id=fixture_id)

    @server._mcp.tool()
    def place(fixture_id: str) -> dict:
        """Place the held object on/at a public fixture."""
        return server.call_tool("place", fixture_id=fixture_id)

    @server._mcp.tool()
    def place_inside(fixture_id: str) -> dict:
        """Place the held object inside an opened public fixture."""
        return server.call_tool("place_inside", fixture_id=fixture_id)

    @server._mcp.tool()
    def close_receptacle(fixture_id: str) -> dict:
        """Close a public fixture after place_inside."""
        return server.call_tool("close_receptacle", fixture_id=fixture_id)

    return ATOMIC_CLEANUP_TOOL_NAMES


def atomic_cleanup_handlers(
    server: Any,
    kwargs: dict[str, Any],
) -> dict[str, Callable[[], dict[str, Any]]]:
    return {
        "navigate_to_object": lambda: server.contract.navigate_to_object(
            str(kwargs.get("object_id", ""))
        ),
        "pick": lambda: server.contract.pick(str(kwargs.get("object_id", ""))),
        "navigate_to_receptacle": lambda: server.contract.navigate_to_receptacle(
            str(kwargs.get("fixture_id", ""))
        ),
        "open_receptacle": lambda: server.contract.open_receptacle(
            str(kwargs.get("fixture_id", ""))
        ),
        "place": lambda: server.contract.place(str(kwargs.get("fixture_id", ""))),
        "place_inside": lambda: server.contract.place_inside(str(kwargs.get("fixture_id", ""))),
        "close_receptacle": lambda: server.contract.close_receptacle(
            str(kwargs.get("fixture_id", ""))
        ),
    }
