from __future__ import annotations

import json
from types import SimpleNamespace

from roboclaws.agents.drivers.openai_agents_live import OpenAIAgentsLiveRuntime, _RetryingModel
from roboclaws.agents.live_runtime import LiveAgentMCPServer, LiveAgentRequest


class FakeModelSettings:
    def __init__(self, **kwargs) -> None:
        self.__dict__.update(kwargs)


class FakeRunConfig:
    def __init__(self, **kwargs) -> None:
        self.__dict__.update(kwargs)


def test_openai_agents_runtime_can_use_minimax_responses_profile(tmp_path, monkeypatch) -> None:
    captured: dict[str, object] = {}

    class FakeOpenAIResponsesModel:
        def __init__(self, model: str, *, openai_client: object) -> None:
            captured["responses_model"] = self
            captured["model"] = model
            captured["client"] = openai_client

    class FakeAsyncOpenAI:
        def __init__(self, *, api_key: str, base_url: str) -> None:
            captured["api_key"] = api_key
            captured["base_url"] = base_url

    monkeypatch.setenv("MM_API_KEY", "fake-mm-key")
    monkeypatch.setenv("MM_BASE_URL", "https://api.minimaxi.com/v1")
    monkeypatch.setattr(
        "roboclaws.agents.drivers.openai_agents_live._run_with_async_mcp_server",
        lambda *_args, **_kwargs: SimpleNamespace(final_output="done"),
    )
    monkeypatch.setitem(
        __import__("sys").modules,
        "agents",
        SimpleNamespace(
            Agent=lambda **kwargs: captured.setdefault("agent_kwargs", kwargs),
            Runner=SimpleNamespace(run_sync=lambda *_args, **_kwargs: SimpleNamespace()),
            ModelSettings=FakeModelSettings,
            RunConfig=FakeRunConfig,
            OpenAIResponsesModel=FakeOpenAIResponsesModel,
        ),
    )
    monkeypatch.setitem(
        __import__("sys").modules,
        "agents.mcp",
        SimpleNamespace(
            MCPServerStreamableHttp=lambda **kwargs: (
                captured.setdefault("mcp_server_kwargs", kwargs) or SimpleNamespace(kwargs=kwargs)
            )
        ),
    )
    monkeypatch.setitem(
        __import__("sys").modules,
        "openai",
        SimpleNamespace(AsyncOpenAI=FakeAsyncOpenAI),
    )
    request = LiveAgentRequest(
        run_id="household-world",
        skill_name="household-world",
        kickoff_prompt="clean the room",
        mcp_server=LiveAgentMCPServer(name="cleanup", url="http://127.0.0.1:18788/mcp"),
        run_dir=tmp_path / "run",
        provider_profile="minimax-responses",
    )

    OpenAIAgentsLiveRuntime().run(request)

    assert captured["model"] == "MiniMax-M3"
    assert captured["base_url"] == "https://api.minimaxi.com/v1"
    assert captured["api_key"] == "fake-mm-key"
    wrapped_model = captured["agent_kwargs"]["model"]
    assert isinstance(wrapped_model, _RetryingModel)
    assert wrapped_model.base_model is captured["responses_model"]
    assert captured["agent_kwargs"]["model_settings"].parallel_tool_calls is False
    events = [
        json.loads(line)
        for line in (tmp_path / "run" / "openai-agents-events.jsonl").read_text().splitlines()
    ]
    assert events[0]["provider_profile"] == "minimax-responses"
    assert events[0]["wire_api"] == "responses"
    assert events[0]["model"] == "MiniMax-M3"
    assert events[0]["agent_sdk_responses_features"]["available"] is True
