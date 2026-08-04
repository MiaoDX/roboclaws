from __future__ import annotations

import asyncio
import io
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from roboclaws.agents.drivers.openai_agents_live import _openai_agents_run_parts
from roboclaws.agents.drivers.openai_agents_sandbox_skills import (
    READ_SELECTED_SKILL_TOOL,
    _NetworkDisabledContainers,
    sandbox_agent_kwargs,
)
from roboclaws.agents.live_runtime import LiveAgentMCPServer, LiveAgentRequest
from roboclaws.agents.skill_delivery import build_skill_delivery

SKILL = """---
name: household-world
description: Safely operate the household robot.
---

# Household World

Use atomic MCP tools.
"""


def _request(tmp_path: Path) -> LiveAgentRequest:
    delivery = build_skill_delivery(
        "sandbox-skills",
        full_content=SKILL,
        intent="cleanup",
        evidence_lane="world-public-labels",
    )
    return LiveAgentRequest(
        run_id="sandbox",
        skill_name="household-world",
        kickoff_prompt="clean the room",
        mcp_server=LiveAgentMCPServer(name="cleanup", url="http://127.0.0.1:18788/mcp"),
        run_dir=tmp_path,
        metadata={
            "skill_context": {
                "skill_name": "household-world",
                "sha256": delivery.artifact()["content_sha256"],
                "delivery_content_sha256": delivery.artifact()["content_sha256"],
                "delivery": delivery,
                "delivery_cell": "sandbox-skills",
            }
        },
    )


class _FakeSession:
    def __init__(self, content: str) -> None:
        self.content = content
        self.state = SimpleNamespace(manifest=SimpleNamespace(root="/workspace"))
        self.paths: list[Path] = []

    async def read(self, path: Path, *, user=None):
        self.paths.append(path)
        return io.BytesIO(self.content.encode("utf-8"))


def test_restricted_capabilities_materialize_only_selected_skill_and_read_exact_path(
    tmp_path: Path,
) -> None:
    kwargs = sandbox_agent_kwargs(_request(tmp_path))
    capabilities = kwargs["capabilities"]
    assert [capability.type for capability in capabilities] == ["skills", "selected_skill_reader"]
    assert kwargs["default_manifest"].entries == {}
    assert "no shell" in kwargs["base_instructions"].lower()

    manifest = kwargs["default_manifest"]
    for capability in capabilities:
        manifest = capability.process_manifest(manifest)
    assert [path.as_posix() for path in manifest.validated_entries()] == [".agents/household-world"]
    assert not manifest.extra_path_grants

    session = _FakeSession(SKILL)
    for capability in capabilities:
        capability.bind(session)
    tools = [tool for capability in capabilities for tool in capability.tools()]
    assert [tool.name for tool in tools] == [READ_SELECTED_SKILL_TOOL]
    assert "path" not in tools[0].params_json_schema["properties"]

    payload = asyncio.run(
        tools[0].on_invoke_tool(
            None,
            json.dumps({"skill_name": "household-world"}),
        )
    )
    assert payload["content"] == SKILL
    assert session.paths == [Path("/workspace/.agents/household-world/SKILL.md")]
    with pytest.raises(ValueError, match="only selected skill"):
        asyncio.run(
            tools[0].on_invoke_tool(
                None,
                json.dumps({"skill_name": "../other"}),
            )
        )


def test_network_disabled_container_proxy_forces_none_and_rejects_mounts() -> None:
    captured: dict[str, object] = {}

    class Containers:
        def create(self, *args, **kwargs):
            captured.update(kwargs)
            return object()

    proxy = _NetworkDisabledContainers(Containers())
    proxy.create(image="python:3.12-slim")
    assert captured["network_disabled"] is True
    assert captured["network_mode"] == "none"

    with pytest.raises(RuntimeError, match="forbids Docker mounts"):
        proxy.create(image="python:3.12-slim", mounts=[object()])


def test_sandbox_agent_kwargs_reject_tampered_skill_body(tmp_path: Path) -> None:
    request = _request(tmp_path)
    request.metadata["skill_context"]["delivery_content_sha256"] = "0" * 64
    with pytest.raises(ValueError, match="does not match source digest"):
        sandbox_agent_kwargs(request)


def test_live_run_parts_use_sandbox_agent_and_sandbox_run_config(
    tmp_path: Path,
    monkeypatch,
) -> None:
    from agents import ModelSettings
    from agents.sandbox import SandboxAgent

    sandbox_config = object()
    monkeypatch.setattr(
        "roboclaws.agents.drivers.openai_agents_sandbox_skills.sandbox_run_config",
        lambda: sandbox_config,
    )
    monkeypatch.setattr(
        "roboclaws.agents.drivers.openai_agents_live._model_for_request",
        lambda _request: "fake-model",
    )
    monkeypatch.setattr(
        "roboclaws.agents.drivers.openai_agents_live._sdk_model_settings_payload",
        lambda _request: {},
    )
    monkeypatch.setattr(
        "roboclaws.agents.drivers.openai_agents_live._sdk_run_config_payload",
        lambda _request, events_path=None: {"workflow_name": "sandbox-test"},
    )

    class RunConfig:
        def __init__(self, **kwargs) -> None:
            self.__dict__.update(kwargs)

    parts = _openai_agents_run_parts(
        _request(tmp_path),
        agent_cls=SandboxAgent,
        model_settings_cls=ModelSettings,
        run_config_cls=RunConfig,
        mcp_server_cls=lambda **kwargs: SimpleNamespace(**kwargs),
        events_path=tmp_path / "events.jsonl",
        skill_context_path=tmp_path / "skill-context.json",
    )

    assert isinstance(parts.agent, SandboxAgent)
    assert [capability.type for capability in parts.agent.capabilities] == [
        "skills",
        "selected_skill_reader",
    ]
    assert parts.agent.instructions is None
    assert parts.run_config.sandbox is sandbox_config
