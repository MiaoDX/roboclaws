"""Canonical local MCP endpoint defaults and ephemeral-port allocation."""

from __future__ import annotations

import socket

DEFAULT_MCP_HOST = "127.0.0.1"
DEFAULT_MCP_PORT = 18788
EVAL_HARNESS_MCP_PORT_ENV = "ROBOCLAWS_EVAL_HARNESS_MCP_PORT"


def free_mcp_port(host: str = DEFAULT_MCP_HOST) -> int:
    with socket.socket() as listener:
        listener.bind((host, 0))
        return int(listener.getsockname()[1])
