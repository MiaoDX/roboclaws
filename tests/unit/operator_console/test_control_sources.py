from __future__ import annotations

import json
import socket
import threading
import urllib.error
import urllib.request
from contextlib import contextmanager
from functools import partial
from http.server import ThreadingHTTPServer
from pathlib import Path
from unittest.mock import patch

import pytest
from mcp.types import CallToolResult, TextContent

from roboclaws.operator_console.control import _serialize_tool_result
from roboclaws.operator_console.routes import get_selection
from roboclaws.operator_console.server import ConsoleRequestHandler

MUJOCO_OPENAI_AGENTS_OPEN_TASK = (
    "molmospaces/procthor-objaverse-val/0::mujoco::open-task::openai-agents-sdk::"
    "world-public-labels"
)


def test_control_endpoint_rejects_malformed_tool_response_text(tmp_path: Path) -> None:
    run_id = "malformed-tool-response-run"
    run_dir = _write_running_operator_control_state(tmp_path, run_id)

    async def fake_call_mcp_tool(mcp_url, action, arguments):  # noqa: ANN001, ANN202
        assert mcp_url == "http://127.0.0.1:19999/mcp"
        assert action == "observe"
        assert arguments == {}
        return _serialize_tool_result(
            CallToolResult(content=[TextContent(type="text", text="{not-json")])
        )

    with _console_server(tmp_path) as (host, port):
        with patch("roboclaws.operator_console.control._call_mcp_tool", fake_call_mcp_tool):
            payload = _blocked_operator_control_payload(
                host,
                port,
                run_id,
                {"action": "observe"},
            )

    assert (
        payload["error"] == "control call failed: operator control MCP tool response "
        "source must contain valid JSON object"
    )
    rows = _jsonl_rows(run_dir / "operator_control.jsonl")
    assert [row["event"] for row in rows] == ["request", "response"]
    assert (
        "operator control MCP tool response source must contain valid JSON object"
        in rows[1]["error"]
    )
    assert "response" not in rows[1]
    persisted = json.loads((run_dir / "operator_state.json").read_text(encoding="utf-8"))
    assert (
        "operator control MCP tool response source must contain valid JSON object"
        in persisted["latest_operator_control"]["error"]
    )


def test_control_tool_response_rejects_non_object_json_text() -> None:
    result = CallToolResult(content=[TextContent(type="text", text="[]")])

    with pytest.raises(ValueError, match="operator control MCP tool response source"):
        _serialize_tool_result(result)


def test_control_endpoint_expands_mcp_connection_exception_group(tmp_path: Path) -> None:
    run_id = "unreachable-mcp-run"
    mcp_url = f"http://127.0.0.1:{_closed_local_port()}/mcp"
    run_dir = _write_running_operator_control_state(tmp_path, run_id, mcp_url=mcp_url)

    with _console_server(tmp_path) as (host, port):
        payload = _blocked_operator_control_payload(host, port, run_id, {"action": "observe"})

    assert payload["error"] == (
        f"control call failed: MCP endpoint is not reachable at {mcp_url}: "
        "All connection attempts failed"
    )
    rows = _jsonl_rows(run_dir / "operator_control.jsonl")
    assert "unhandled errors in a TaskGroup" not in rows[1]["error"]
    assert rows[1]["error"] == (
        f"MCP endpoint is not reachable at {mcp_url}: All connection attempts failed"
    )


def _write_running_operator_control_state(
    root: Path,
    run_id: str,
    *,
    mcp_url: str = "http://127.0.0.1:19999/mcp",
) -> Path:
    route = get_selection(MUJOCO_OPENAI_AGENTS_OPEN_TASK)
    run_dir = root / "output" / "operator-console" / "runs" / run_id
    run_dir.mkdir(parents=True)
    (run_dir / "operator_state.json").write_text(
        json.dumps(
            {
                "run_id": run_id,
                "route": route.to_payload(),
                "phase": "running",
                "backend_lock": route.lock_name,
                "mcp_url": mcp_url,
            }
        ),
        encoding="utf-8",
    )
    return run_dir


def _closed_local_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def _blocked_operator_control_payload(
    host: str,
    port: int,
    run_id: str,
    body: dict[str, object],
) -> dict[str, object]:
    request = urllib.request.Request(
        f"http://{host}:{port}/api/runs/{run_id}/control",
        method="POST",
        data=json.dumps(body).encode("utf-8"),
        headers={"Content-Type": "application/json"},
    )
    with pytest.raises(urllib.error.HTTPError) as exc_info:
        urllib.request.urlopen(request)
    assert exc_info.value.code == 502
    return json.loads(exc_info.value.read().decode("utf-8"))


@contextmanager
def _console_server(root: Path):
    handler = partial(ConsoleRequestHandler, root=root)
    server = ThreadingHTTPServer(("127.0.0.1", 0), handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield server.server_address
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)


def _jsonl_rows(path: Path) -> list[dict[str, object]]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]
