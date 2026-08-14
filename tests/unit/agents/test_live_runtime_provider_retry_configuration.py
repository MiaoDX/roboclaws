from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from roboclaws.agents.drivers.openai_agents_live import OpenAIAgentsLiveRuntime
from roboclaws.agents.drivers.openai_agents_perf_profile import (
    resolve_agent_sdk_perf_profile as _resolve_agent_sdk_perf_profile,
)
from roboclaws.agents.drivers.openai_agents_retry_model import (
    _RetryingModel,
)
from roboclaws.agents.drivers.openai_agents_run_config import (
    _default_sdk_model_settings_payload,
    _mcp_client_session_timeout_seconds,
)
from roboclaws.agents.household_live_runner import (
    parse_args as _parse_live_openai_agents_args,
)
from roboclaws.agents.live_runtime import (
    LiveAgentMCPServer,
    LiveAgentRequest,
)
from tests.unit.agents.live_runtime_support import (
    FakeModelSettings,
    FakeRunConfig,
    _openai_agents_perf_profile_base_args,
)


def test_openai_agents_default_model_settings_apply_provider_thinking_policy() -> None:
    responses = _default_sdk_model_settings_payload(
        provider_profile="minimax-responses",
        wire_api="responses",
        profile_id="baseline",
    )
    kimi_chat = _default_sdk_model_settings_payload(
        provider_profile="kimi-openai-chat",
        wire_api="chat-completions",
        profile_id="baseline",
    )
    assert responses["reasoning"] == {"effort": "medium"}
    assert responses["truncation"] == "auto"
    assert "extra_body" not in kimi_chat
    assert kimi_chat["extra_headers"] == {"User-Agent": "claude-code/1.0.0"}


def test_openai_agents_runtime_uses_explicit_codex_responses_profile(
    tmp_path: Path, monkeypatch
) -> None:
    captured: dict[str, object] = {}

    class FakeOpenAIResponsesModel:
        def __init__(self, model: str, *, openai_client: object) -> None:
            captured["responses_model"] = self
            captured["model"] = model
            captured["client"] = openai_client

    class FakeAsyncOpenAI:
        def __init__(
            self,
            *,
            api_key: str,
            base_url: str,
            default_headers: dict[str, str] | None = None,
        ) -> None:
            captured["api_key"] = api_key
            captured["base_url"] = base_url
            captured["default_headers"] = default_headers

    monkeypatch.setenv("CODEX_RESPONSES_BASE_URL", "https://codex.example.test/v1")
    monkeypatch.setenv("CODEX_RESPONSES_API_KEY", "fake-codex-key")
    monkeypatch.setenv("CODEX_RESPONSES_MODEL", "opaque-codex-model")
    monkeypatch.setattr(
        "roboclaws.agents.drivers.openai_agents_live._run_with_async_mcp_server",
        lambda *_args, **_kwargs: SimpleNamespace(final_output="done"),
    )
    monkeypatch.setitem(
        __import__("sys").modules,
        "agents",
        SimpleNamespace(
            Agent=lambda **kwargs: captured.setdefault("agent_kwargs", kwargs),
            Runner=SimpleNamespace(
                run_sync=lambda *_args, **kwargs: (
                    captured.setdefault("runner_kwargs", kwargs) or SimpleNamespace()
                )
            ),
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
        provider_profile="codex-responses",
    )

    OpenAIAgentsLiveRuntime().run(request)

    assert captured["model"] == "opaque-codex-model"
    assert captured["base_url"] == "https://codex.example.test/v1"
    assert captured["api_key"] == "fake-codex-key"
    assert captured["default_headers"]["X-Codex-Window-Id"].endswith(":0")
    wrapped_model = captured["agent_kwargs"]["model"]
    assert isinstance(wrapped_model, _RetryingModel)
    assert wrapped_model.base_model is captured["responses_model"]
    assert captured["agent_kwargs"]["model_settings"].tool_choice == "auto"
    assert captured["agent_kwargs"]["model_settings"].parallel_tool_calls is False
    assert not hasattr(captured["agent_kwargs"]["model_settings"], "truncation")
    assert not hasattr(captured["agent_kwargs"]["model_settings"], "extra_headers")
    assert captured["runner_kwargs"]["run_config"].trace_include_sensitive_data is False
    assert captured["runner_kwargs"]["run_config"].workflow_name == "roboclaws-openai-agents-live"
    assert captured["mcp_server_kwargs"]["cache_tools_list"] is True
    assert "client_session_timeout_seconds" not in captured["mcp_server_kwargs"]
    events_text = (tmp_path / "run" / "openai-agents-events.jsonl").read_text(encoding="utf-8")
    assert "x-codex" not in events_text.lower()
    assert captured["agent_kwargs"]["mcp_config"]["failure_error_function"]
    assert captured["runner_kwargs"]["max_turns"] == 128
    events = [
        json.loads(line)
        for line in (tmp_path / "run" / "openai-agents-events.jsonl").read_text().splitlines()
    ]
    assert events[0]["wire_api"] == "responses"
    assert events[0]["sdk_model_settings"]["store"] is False
    assert events[0]["sdk_model_settings"]["reasoning"] == {"effort": "medium"}
    assert events[0]["sdk_run_config"]["trace_include_sensitive_data"] is False
    assert events[0]["agent_sdk_responses_features"]["available"] is True
    assert events[0]["agent_sdk_responses_features"]["server_managed_continuation_default"] is False
    assert events[0]["model_input_compaction"]["enabled"] is False
    assert events[0]["model_input_compaction"]["mode"] == "off"
    assert events[0]["model_racing_observability"]["enabled"] is False
    assert events[0]["model_racing_observability"]["winner_selection"] == "single_arm_no_racing"


def test_openai_agents_runtime_applies_kimi_coding_user_agent(tmp_path: Path, monkeypatch) -> None:
    captured: dict[str, object] = {}

    class FakeOpenAIChatCompletionsModel:
        def __init__(self, model: str, *, openai_client: object) -> None:
            captured["chat_model"] = self
            captured["model"] = model
            captured["client"] = openai_client

    class FakeAsyncOpenAI:
        def __init__(
            self,
            *,
            api_key: str,
            base_url: str,
            default_headers: dict[str, str] | None = None,
        ) -> None:
            captured["api_key"] = api_key
            captured["base_url"] = base_url

    monkeypatch.setenv("KIMI_OPENAI_BASE_URL", "https://kimi.example.test/v1")
    monkeypatch.setenv("KIMI_API_KEY", "fake-kimi-key")
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
            OpenAIChatCompletionsModel=FakeOpenAIChatCompletionsModel,
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
        provider_profile="kimi-openai-chat",
        metadata={
            "agent_sdk_perf_profile": {
                "profile_id": "baseline",
                "provider_profile": "kimi-openai-chat",
                "wire_api": "chat-completions",
                "sdk_model_settings": {
                    "tool_choice": "auto",
                    "parallel_tool_calls": False,
                    "model_thinking_mode": "default",
                    "include_usage": True,
                },
            }
        },
    )

    OpenAIAgentsLiveRuntime().run(request)

    model_settings = captured["agent_kwargs"]["model_settings"]
    assert captured["model"] == "kimi-k2.7-code"
    assert captured["base_url"] == "https://kimi.example.test/v1"
    assert captured["api_key"] == "fake-kimi-key"
    assert model_settings.include_usage is True
    assert not hasattr(model_settings, "extra_body")
    assert model_settings.extra_headers == {"User-Agent": "claude-code/1.0.0"}
    events = [
        json.loads(line)
        for line in (tmp_path / "run" / "openai-agents-events.jsonl").read_text().splitlines()
    ]
    assert events[0]["provider_profile"] == "kimi-openai-chat"
    assert events[0]["sdk_model_settings"]["extra_headers"] == {"User-Agent": "claude-code/1.0.0"}


def test_openai_agents_runtime_preserves_zero_mcp_client_timeout_disable(
    tmp_path: Path,
) -> None:
    request = LiveAgentRequest(
        run_id="household-world",
        skill_name="household-world",
        kickoff_prompt="clean the room",
        mcp_server=LiveAgentMCPServer(name="cleanup", url="http://127.0.0.1:18788/mcp"),
        run_dir=tmp_path / "run",
        metadata={"mcp_client_session_timeout_s": 0},
    )

    assert _mcp_client_session_timeout_seconds(request) == (True, None)


@pytest.mark.parametrize(
    ("metadata", "env", "expected_detail"),
    [
        (
            {"provider_profile": "kimi-openai-chat"},
            {"ROBOCLAWS_PROVIDER_PROFILE": "minimax-responses"},
            "conflicting OpenAI Agents SDK setting provider_profile",
        ),
        (
            {"model": "kimi-k2-5"},
            {"ROBOCLAWS_OPENAI_AGENTS_MODEL": "kimi-k2.7-code"},
            "conflicting OpenAI Agents SDK setting model",
        ),
        (
            {"base_url": "https://kimi-one.example.test/v1"},
            {"KIMI_OPENAI_BASE_URL": "https://kimi-two.example.test/v1"},
            "conflicting OpenAI Agents SDK setting base_url",
        ),
        (
            {"api_key": "metadata-key"},
            {"KIMI_API_KEY": "env-key"},
            "conflicting OpenAI Agents SDK setting api_key",
        ),
    ],
)
def test_openai_agents_runtime_rejects_conflicting_provider_model_env_settings(
    tmp_path: Path,
    monkeypatch,
    metadata: dict[str, object],
    env: dict[str, str],
    expected_detail: str,
) -> None:
    base_env = {
        "ROBOCLAWS_PROVIDER_PROFILE": "kimi-openai-chat",
        "KIMI_OPENAI_BASE_URL": "https://kimi.example.test/v1",
        "KIMI_API_KEY": "fake-kimi-key",
    }
    base_env.update(env)
    for key, value in base_env.items():
        monkeypatch.setenv(key, value)
    request = LiveAgentRequest(
        run_id="household-world",
        skill_name="household-world",
        kickoff_prompt="clean the room",
        mcp_server=LiveAgentMCPServer(name="cleanup", url="http://127.0.0.1:18788/mcp"),
        run_dir=tmp_path / "run",
        metadata=metadata,
    )

    result = OpenAIAgentsLiveRuntime().run(request)

    assert result.phase == "failed"
    assert result.reason == "provider_config_failure"
    payload = json.loads((tmp_path / "run" / "live_status.json").read_text(encoding="utf-8"))
    assert payload["reason"] == "provider_config_failure"
    assert expected_detail in payload["detail"]


def test_openai_agents_runtime_rejects_unknown_model_env(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("ROBOCLAWS_PROVIDER_PROFILE", "kimi-openai-chat")
    monkeypatch.setenv("KIMI_OPENAI_BASE_URL", "https://kimi.example.test/v1")
    monkeypatch.setenv("KIMI_API_KEY", "fake-kimi-key")
    monkeypatch.setenv("ROBOCLAWS_OPENAI_AGENTS_MODEL", "not-in-provider-catalog")
    request = LiveAgentRequest(
        run_id="household-world",
        skill_name="household-world",
        kickoff_prompt="clean the room",
        mcp_server=LiveAgentMCPServer(name="cleanup", url="http://127.0.0.1:18788/mcp"),
        run_dir=tmp_path / "run",
    )

    result = OpenAIAgentsLiveRuntime().run(request)

    assert result.phase == "failed"
    assert result.reason == "provider_config_failure"
    payload = json.loads((tmp_path / "run" / "live_status.json").read_text(encoding="utf-8"))
    assert payload["reason"] == "provider_config_failure"
    assert "OpenAI Agents SDK setting model is unknown" in payload["detail"]
    assert "not-in-provider-catalog" in payload["detail"]


def test_openai_agents_runtime_rejects_route_incompatible_model_env(
    tmp_path: Path, monkeypatch
) -> None:
    monkeypatch.setenv("MM_API_KEY", "fake-mm-key")
    monkeypatch.setenv("ROBOCLAWS_PROVIDER_PROFILE", "minimax-responses")
    monkeypatch.setenv("ROBOCLAWS_OPENAI_AGENTS_MODEL", "kimi-k2.7-code")
    request = LiveAgentRequest(
        run_id="household-world",
        skill_name="household-world",
        kickoff_prompt="clean the room",
        mcp_server=LiveAgentMCPServer(name="cleanup", url="http://127.0.0.1:18788/mcp"),
        run_dir=tmp_path / "run",
    )

    result = OpenAIAgentsLiveRuntime().run(request)

    assert result.phase == "failed"
    assert result.reason == "provider_config_failure"
    payload = json.loads((tmp_path / "run" / "live_status.json").read_text(encoding="utf-8"))
    assert payload["reason"] == "provider_config_failure"
    assert "OpenAI Agents SDK setting model is incompatible" in payload["detail"]
    assert (
        "model 'kimi-k2.7-code' is incompatible with provider_profile 'minimax-responses'"
        in (payload["detail"])
    )


def test_openai_agents_runtime_allows_matching_provider_model_env_aliases(
    tmp_path: Path,
    monkeypatch,
) -> None:
    captured: dict[str, object] = {}

    class FakeOpenAIResponsesModel:
        def __init__(self, model: str, *, openai_client: object) -> None:
            captured["model"] = model

    class FakeAsyncOpenAI:
        def __init__(
            self,
            *,
            api_key: str,
            base_url: str,
            default_headers: dict[str, str] | None = None,
        ) -> None:
            captured["api_key"] = api_key
            captured["base_url"] = base_url

    monkeypatch.setenv("MM_BASE_URL", "https://kimi.example.test/v1/")
    monkeypatch.setenv("MM_API_KEY", "fake-kimi-key")
    monkeypatch.setenv("ROBOCLAWS_PROVIDER_PROFILE", "minimax-responses")
    monkeypatch.setenv("ROBOCLAWS_OPENAI_AGENTS_MODEL", "MiniMax-M3")
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
        model="minimax",
        metadata={
            "provider_profile": "minimax-responses",
            "base_url": "https://kimi.example.test/v1",
            "api_key": "fake-kimi-key",
        },
    )

    result = OpenAIAgentsLiveRuntime().run(request)

    assert result.exit_status == 0
    assert captured["model"] == "MiniMax-M3"
    assert captured["base_url"] == "https://kimi.example.test/v1"
    assert captured["api_key"] == "fake-kimi-key"


def test_openai_agents_runtime_can_use_kimi_openai_chat_profile(
    tmp_path: Path, monkeypatch
) -> None:
    captured: dict[str, object] = {}

    class FakeOpenAIChatCompletionsModel:
        def __init__(self, model: str, *, openai_client: object) -> None:
            captured["model"] = model

    class FakeAsyncOpenAI:
        def __init__(
            self,
            *,
            api_key: str,
            base_url: str,
            default_headers: dict[str, str] | None = None,
        ) -> None:
            captured["api_key"] = api_key
            captured["base_url"] = base_url

    monkeypatch.setenv("KIMI_OPENAI_BASE_URL", "https://kimi.example.test/v1")
    monkeypatch.setenv("KIMI_API_KEY", "fake-kimi-key")
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
            OpenAIChatCompletionsModel=FakeOpenAIChatCompletionsModel,
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
        provider_profile="kimi-openai-chat",
    )

    OpenAIAgentsLiveRuntime().run(request)

    assert captured["model"] == "kimi-k2.7-code"
    assert captured["base_url"] == "https://kimi.example.test/v1"
    assert captured["api_key"] == "fake-kimi-key"
    assert captured["agent_kwargs"]["model_settings"].extra_headers == {
        "User-Agent": "claude-code/1.0.0"
    }
    assert not hasattr(captured["agent_kwargs"]["model_settings"], "extra_body")


def test_openai_agents_runtime_rejects_invalid_cache_tools_metadata(
    tmp_path: Path, monkeypatch
) -> None:
    monkeypatch.setenv("KIMI_OPENAI_BASE_URL", "https://kimi.example.test/v1")
    monkeypatch.setenv("KIMI_API_KEY", "fake-kimi-key")
    request = LiveAgentRequest(
        run_id="household-world",
        skill_name="household-world",
        kickoff_prompt="clean the room",
        mcp_server=LiveAgentMCPServer(name="cleanup", url="http://127.0.0.1:18788/mcp"),
        run_dir=tmp_path / "run",
        metadata={"cache_tools_list": "sometimes"},
    )

    result = OpenAIAgentsLiveRuntime().run(request)

    assert result.phase == "failed"
    assert result.exit_status == 1
    assert result.reason == "provider_config_failure"
    assert "OpenAI Agents SDK setting cache_tools_list must be true or false" in result.detail
    payload = json.loads((tmp_path / "run" / "live_status.json").read_text(encoding="utf-8"))
    assert payload["reason"] == "provider_config_failure"
    assert "OpenAI Agents SDK setting cache_tools_list must be true or false" in payload["detail"]


def test_openai_agents_live_runner_rejects_invalid_cache_tools_env(monkeypatch) -> None:
    monkeypatch.setenv("ROBOCLAWS_OPENAI_AGENTS_CACHE_TOOLS_LIST", "sometimes")

    with pytest.raises(ValueError, match="ROBOCLAWS_OPENAI_AGENTS_CACHE_TOOLS_LIST"):
        _parse_live_openai_agents_args([])


def test_openai_agents_runtime_configures_mcp_client_session_timeout(
    tmp_path: Path, monkeypatch
) -> None:
    captured: dict[str, object] = {}

    class FakeOpenAIResponsesModel:
        def __init__(self, model: str, *, openai_client: object) -> None:
            captured["model"] = model

    class FakeAsyncOpenAI:
        def __init__(
            self,
            *,
            api_key: str,
            base_url: str,
            default_headers: dict[str, str] | None = None,
        ) -> None:
            pass

    monkeypatch.setenv("MM_BASE_URL", "https://minimax.example.test/v1")
    monkeypatch.setenv("MM_API_KEY", "fake-minimax-key")
    monkeypatch.setenv("ROBOCLAWS_OPENAI_AGENTS_MCP_CLIENT_SESSION_TIMEOUT_S", "30")
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

    assert captured["mcp_server_kwargs"]["client_session_timeout_seconds"] == 30.0
    events = [
        json.loads(line)
        for line in (tmp_path / "run" / "openai-agents-events.jsonl").read_text().splitlines()
    ]
    assert events[0]["event"] == "start"
    assert events[0]["mcp_client_session_timeout_s"] == 30.0


def test_openai_agents_perf_profile_rejects_invalid_cache_tools_env(monkeypatch) -> None:
    monkeypatch.setenv("ROBOCLAWS_OPENAI_AGENTS_CACHE_TOOLS_LIST", "sometimes")

    with pytest.raises(
        ValueError,
        match="OpenAI Agents SDK boolean setting must be true or false",
    ):
        _resolve_agent_sdk_perf_profile(
            _openai_agents_perf_profile_base_args(cache_tools_list=None)
        )


def test_openai_agents_perf_profile_uses_cache_tools_env(monkeypatch) -> None:
    monkeypatch.setenv("ROBOCLAWS_OPENAI_AGENTS_CACHE_TOOLS_LIST", "off")

    profile = _resolve_agent_sdk_perf_profile(
        _openai_agents_perf_profile_base_args(cache_tools_list=None)
    )

    assert profile["cache_tools_list"] is False


def test_openai_agents_perf_profile_resolves_minimax_and_kimi_defaults(monkeypatch) -> None:
    monkeypatch.delenv("ROBOCLAWS_OPENAI_AGENTS_PERF_PROFILE", raising=False)
    minimax = _resolve_agent_sdk_perf_profile(
        _openai_agents_perf_profile_base_args(
            provider_profile="minimax-responses",
            model="MiniMax-M3",
            agent_sdk_perf_profile="context_managed_v1",
        )
    )

    assert minimax["provider_profile"] == "minimax-responses"
    assert minimax["wire_api"] == "responses"
    assert minimax["model_family"] == "minimax"
    assert minimax["max_continuations"] == 1
    assert minimax["context_soft_limit_tokens"] == 64_000
    assert minimax["context_hard_limit_tokens"] == 96_000
    assert minimax["sdk_model_settings"]["truncation"] == "auto"

    chat = _resolve_agent_sdk_perf_profile(
        _openai_agents_perf_profile_base_args(
            provider_profile="kimi-openai-chat",
            model="kimi-k2.7-code",
        )
    )
    assert chat["provider_profile"] == "kimi-openai-chat"
    assert chat["wire_api"] == "chat-completions"
    assert chat["model_family"] == "kimi"
    assert chat["sdk_model_settings"] == {
        "tool_choice": "auto",
        "parallel_tool_calls": False,
        "model_thinking_mode": "default",
        "include_usage": True,
        "extra_headers": {"User-Agent": "claude-code/1.0.0"},
    }

    kimi = _resolve_agent_sdk_perf_profile(
        _openai_agents_perf_profile_base_args(
            provider_profile="kimi-openai-chat",
            model="kimi-k2.7-code",
        )
    )
    assert kimi["provider_profile"] == "kimi-openai-chat"
    assert kimi["wire_api"] == "chat-completions"
    assert kimi["sdk_model_settings"]["extra_headers"] == {"User-Agent": "claude-code/1.0.0"}
