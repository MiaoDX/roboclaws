from __future__ import annotations

import asyncio
from pathlib import Path
from types import SimpleNamespace

import pytest
from mcp.types import CallToolResult, TextContent

from roboclaws.agents.drivers.openai_agents_event_projection import (
    normalized_mcp_tool_event,
)
from roboclaws.agents.drivers.openai_agents_live import (
    _checkpoint_callback,
    _checkpointing_mcp_server_cls,
    _openai_agents_run_parts,
)
from roboclaws.agents.live_runtime import LiveAgentMCPServer, LiveAgentRequest
from roboclaws.agents.task_state import Checkpoint, TaskSnapshot


class _FakeTextContent:
    def __init__(self, text: str) -> None:
        self.text = text


class _FakeCallToolResult:
    def __init__(
        self,
        *,
        structured: dict[str, object] | None = None,
        text: str | None = None,
        is_error: bool = False,
    ) -> None:
        self.structuredContent = structured
        self.content = [] if text is None else [_FakeTextContent(text)]
        self.isError = is_error


class _FakeMCPServer:
    """Stand-in for the injected SDK MCP server class at the checkpoint seam."""

    def __init__(self, **kwargs) -> None:
        self.__dict__.update(kwargs)
        self.arguments: list[dict[str, object] | None] = []
        self.result = _FakeCallToolResult(structured={"objects": {"cup": "red"}})

    async def call_tool(
        self,
        tool_name: str,
        arguments: dict[str, object] | None,
        meta: dict[str, object] | None = None,
    ) -> object:
        self.arguments.append(arguments)
        return self.result


class _FakeAgent:
    def __init__(self, **kwargs) -> None:
        self.__dict__.update(kwargs)


class _FakeSettings:
    def __init__(self, **kwargs) -> None:
        self.__dict__.update(kwargs)


def _request(tmp_path: Path, *, checkpoint: bool) -> LiveAgentRequest:
    metadata: dict[str, object] = {}
    if checkpoint:
        metadata = {
            "checkpoint_path": str(tmp_path / "run" / "checkpoint.json"),
            "task_snapshot": TaskSnapshot("household-world", "cleanup"),
        }
    return LiveAgentRequest(
        run_id="checkpoint-seam",
        skill_name="household-world",
        kickoff_prompt="clean the room",
        mcp_server=LiveAgentMCPServer(name="cleanup", url="http://127.0.0.1:18788/mcp"),
        run_dir=tmp_path / "run",
        metadata=metadata,
    )


def _run_parts(tmp_path: Path, request: LiveAgentRequest):
    return _openai_agents_run_parts(
        request,
        agent_cls=_FakeAgent,
        model_settings_cls=_FakeSettings,
        run_config_cls=_FakeSettings,
        mcp_server_cls=_FakeMCPServer,
        events_path=tmp_path / "run" / "events.jsonl",
        skill_context_path=tmp_path / "run" / "skill-context.json",
        tool_result_callback=_checkpoint_callback(request),
    )


def test_tool_call_advances_the_configured_checkpoint(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        "roboclaws.agents.drivers.openai_agents_live._model_for_request",
        lambda _request: "fake-model",
    )
    checkpoint_path = tmp_path / "run" / "checkpoint.json"
    parts = _run_parts(tmp_path, _request(tmp_path, checkpoint=True))
    server = parts.server
    assert isinstance(server, _FakeMCPServer)

    result = asyncio.run(server.call_tool("observe", {"query": "cup"}))

    assert server.arguments == [{"query": "cup"}]
    assert result is server.result
    checkpoint = Checkpoint.from_json(checkpoint_path.read_text(encoding="utf-8"))
    assert checkpoint.snapshot.revision == 1
    assert checkpoint.snapshot.objects["cup"].value == "red"

    server.result = _FakeCallToolResult(structured={"waypoint": "kitchen"})
    asyncio.run(server.call_tool("navigate", None))

    checkpoint = Checkpoint.from_json(checkpoint_path.read_text(encoding="utf-8"))
    assert checkpoint.snapshot.revision == 2
    assert checkpoint.snapshot.waypoint == "kitchen"


def test_json_text_content_advances_when_structured_content_is_absent(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        "roboclaws.agents.drivers.openai_agents_live._model_for_request",
        lambda _request: "fake-model",
    )
    checkpoint_path = tmp_path / "run" / "checkpoint.json"
    server = _run_parts(tmp_path, _request(tmp_path, checkpoint=True)).server
    server.result = _FakeCallToolResult(text='{"safety": {"clear": true}}')

    asyncio.run(server.call_tool("safety_check", {}))

    checkpoint = Checkpoint.from_json(checkpoint_path.read_text(encoding="utf-8"))
    assert checkpoint.snapshot.revision == 1
    assert checkpoint.snapshot.safety == {"clear": True}


def test_failed_tool_call_does_not_advance_the_checkpoint(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        "roboclaws.agents.drivers.openai_agents_live._model_for_request",
        lambda _request: "fake-model",
    )
    checkpoint_path = tmp_path / "run" / "checkpoint.json"
    server = _run_parts(tmp_path, _request(tmp_path, checkpoint=True)).server
    server.result = _FakeCallToolResult(
        structured={"waypoint": "kitchen", "objects": {"cup": "red"}},
        is_error=True,
    )

    asyncio.run(server.call_tool("observe", {}))

    assert not checkpoint_path.exists()


def test_unconfigured_checkpoint_leaves_the_mcp_server_untouched(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        "roboclaws.agents.drivers.openai_agents_live._model_for_request",
        lambda _request: "fake-model",
    )
    request = _request(tmp_path, checkpoint=False)
    assert _checkpoint_callback(request) is None

    parts = _run_parts(tmp_path, request)

    assert type(parts.server) is _FakeMCPServer
    asyncio.run(parts.server.call_tool("observe", {}))
    assert not (tmp_path / "run" / "checkpoint.json").exists()


def test_checkpoint_callback_requires_both_launcher_fields(tmp_path: Path) -> None:
    request = _request(tmp_path, checkpoint=True)
    assert callable(_checkpoint_callback(request))

    partial = _request(tmp_path, checkpoint=False)
    partial.metadata["checkpoint_path"] = str(tmp_path / "run" / "checkpoint.json")
    assert _checkpoint_callback(partial) is None

    partial.metadata["task_snapshot"] = TaskSnapshot("household-world", "cleanup")
    assert callable(_checkpoint_callback(partial))


def test_real_mcp_call_tool_result_advances_the_checkpoint_of_a_real_model_snapshot(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        "roboclaws.agents.drivers.openai_agents_live._model_for_request",
        lambda _request: "fake-model",
    )
    checkpoint_path = tmp_path / "run" / "checkpoint.json"
    server = _run_parts(tmp_path, _request(tmp_path, checkpoint=True)).server
    server.result = CallToolResult(
        content=[TextContent(type="text", text="Agent-facing prose about the cup.")],
        structuredContent={"objects": {"cup": "red"}},
    )

    asyncio.run(server.call_tool("observe", {}))

    checkpoint = Checkpoint.from_json(checkpoint_path.read_text(encoding="utf-8"))
    assert checkpoint.snapshot.revision == 1
    assert checkpoint.snapshot.objects["cup"].value == "red"


def test_normalized_mcp_tool_event_prefers_structured_content() -> None:
    structured = CallToolResult(
        content=[TextContent(type="text", text='{"objects": {"cup": "blue"}}')],
        structuredContent={"objects": {"cup": "red"}},
    )
    assert normalized_mcp_tool_event("observe", structured) == {
        "tool": "observe",
        "success": True,
        "result": {"objects": {"cup": "red"}},
    }
    text_only = CallToolResult(content=[TextContent(type="text", text='{"waypoint": "hall"}')])
    assert normalized_mcp_tool_event("navigate", text_only)["result"] == {"waypoint": "hall"}
    unparseable = CallToolResult(content=[TextContent(type="text", text="prose only")])
    assert normalized_mcp_tool_event("navigate", unparseable)["result"] == {}
    failed = CallToolResult(content=[], structuredContent={"a": 1}, isError=True)
    assert normalized_mcp_tool_event("observe", failed)["success"] is False


def test_checkpointing_requires_a_subclassable_mcp_server_cls() -> None:
    def factory(**kwargs) -> SimpleNamespace:
        return SimpleNamespace(**kwargs)

    with pytest.raises(TypeError, match="requires an MCP server class"):
        _checkpointing_mcp_server_cls(factory, lambda _: None)
