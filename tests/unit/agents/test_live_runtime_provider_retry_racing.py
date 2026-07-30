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
from roboclaws.agents.household_live_runner import (
    _model_racing_observability_metrics,
)
from roboclaws.agents.live_runtime import (
    LiveAgentMCPServer,
    LiveAgentRequest,
)
from tests.unit.agents.live_runtime_support import (
    FakeModelSettings,
    FakeRunConfig,
    _expected_model_racing_observability,
    _openai_agents_perf_profile_base_args,
)


def test_openai_agents_runtime_applies_kimi_chat_transport_contract(
    tmp_path: Path, monkeypatch
) -> None:
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
    monkeypatch.setenv("KIMI_OPENAI_BASE_URL", "https://kimi.example.test/v1")
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
    wrapped_model = captured["agent_kwargs"]["model"]
    assert isinstance(wrapped_model, _RetryingModel)
    assert wrapped_model.base_model is captured["chat_model"]
    assert captured["agent_kwargs"]["model_settings"].include_usage is True
    assert captured["agent_kwargs"]["model_settings"].parallel_tool_calls is False
    assert not hasattr(captured["agent_kwargs"]["model_settings"], "extra_body")
    assert captured["agent_kwargs"]["model_settings"].extra_headers == {
        "User-Agent": "claude-code/1.0.0"
    }
    events = [
        json.loads(line)
        for line in (tmp_path / "run" / "openai-agents-events.jsonl").read_text().splitlines()
    ]
    assert events[0]["provider_profile"] == "kimi-openai-chat"
    assert events[0]["wire_api"] == "chat-completions"
    assert events[0]["sdk_model_settings"]["include_usage"] is True
    assert events[0]["agent_sdk_responses_features"]["available"] is False


@pytest.mark.parametrize(
    ("config", "setting_name"),
    [
        ({"enabled": "sometimes"}, "model_racing_observability.enabled"),
        (
            {"unknown_loser_billing": "sometimes"},
            "model_racing_observability.unknown_loser_billing",
        ),
    ],
)
def test_openai_agents_runtime_rejects_invalid_model_racing_boolean_settings(
    tmp_path: Path,
    monkeypatch,
    config: dict[str, object],
    setting_name: str,
) -> None:
    monkeypatch.setenv("KIMI_OPENAI_BASE_URL", "https://kimi.example.test/v1")
    monkeypatch.setenv("KIMI_API_KEY", "fake-kimi-key")
    request = LiveAgentRequest(
        run_id="household-world",
        skill_name="household-world",
        kickoff_prompt="clean the room",
        mcp_server=LiveAgentMCPServer(name="cleanup", url="http://127.0.0.1:18788/mcp"),
        run_dir=tmp_path / "run",
        metadata={"model_racing_observability": config},
    )

    result = OpenAIAgentsLiveRuntime().run(request)

    assert result.phase == "failed"
    assert result.reason == "provider_config_failure"
    payload = json.loads((tmp_path / "run" / "live_status.json").read_text(encoding="utf-8"))
    assert payload["reason"] == "provider_config_failure"
    assert setting_name in payload["detail"]
    assert "must be true or false" in payload["detail"]


@pytest.mark.parametrize(
    ("config", "setting_name", "message"),
    [
        (
            {"arm_count": "many"},
            "model_racing_observability.arm_count",
            "must be a positive integer",
        ),
        (
            {"arm_count": 0},
            "model_racing_observability.arm_count",
            "must be a positive integer",
        ),
        (
            {"racing_multiplier": "fast"},
            "model_racing_observability.racing_multiplier",
            "must be a positive finite number",
        ),
        (
            {"racing_multiplier": float("inf")},
            "model_racing_observability.racing_multiplier",
            "must be a positive finite number",
        ),
    ],
)
def test_openai_agents_runtime_rejects_invalid_model_racing_numeric_settings(
    tmp_path: Path,
    monkeypatch,
    config: dict[str, object],
    setting_name: str,
    message: str,
) -> None:
    monkeypatch.setenv("KIMI_OPENAI_BASE_URL", "https://kimi.example.test/v1")
    monkeypatch.setenv("KIMI_API_KEY", "fake-kimi-key")
    request = LiveAgentRequest(
        run_id="household-world",
        skill_name="household-world",
        kickoff_prompt="clean the room",
        mcp_server=LiveAgentMCPServer(name="cleanup", url="http://127.0.0.1:18788/mcp"),
        run_dir=tmp_path / "run",
        metadata={"model_racing_observability": config},
    )

    result = OpenAIAgentsLiveRuntime().run(request)

    assert result.phase == "failed"
    assert result.reason == "provider_config_failure"
    payload = json.loads((tmp_path / "run" / "live_status.json").read_text(encoding="utf-8"))
    assert payload["reason"] == "provider_config_failure"
    assert setting_name in payload["detail"]
    assert message in payload["detail"]


def test_openai_agents_perf_profile_resolves_managed_and_racing_defaults(monkeypatch) -> None:
    monkeypatch.delenv("ROBOCLAWS_OPENAI_AGENTS_PERF_PROFILE", raising=False)
    kimi_managed = _resolve_agent_sdk_perf_profile(
        _openai_agents_perf_profile_base_args(agent_sdk_perf_profile="context_managed_v1")
    )

    assert kimi_managed["source"] == "cli"
    assert kimi_managed["continuation_mode"] == "state_summary_only"
    assert kimi_managed["max_turns"] == 128
    assert kimi_managed["max_continuations"] == 1
    assert kimi_managed["context_soft_limit_tokens"] == 64_000
    assert kimi_managed["context_hard_limit_tokens"] == 96_000
    assert kimi_managed["done_retry_budget"] == 1
    assert "truncation" not in kimi_managed["sdk_model_settings"]
    assert kimi_managed["sdk_model_settings"]["extra_headers"] == {
        "User-Agent": "claude-code/1.0.0"
    }
    assert kimi_managed["model_input_compaction"]["candidate_ids"] == ["I", "N", "AC"]
    assert kimi_managed["model_input_compaction"]["repeated_metric_map_delta"] is True
    assert kimi_managed["model_input_compaction"]["camera_grounded_history"] == {
        "schema": "agent_sdk_camera_grounded_history_policy_v1",
        "enabled": True,
        "mode": "retain_latest_actionable_outputs",
        "retained_recent_outputs": 4,
        "candidate_ids": ["AC"],
        "private_artifact_policy": (
            "model-facing camera-grounded history compaction only; MCP traces, reports, "
            "and run artifacts remain complete"
        ),
    }
    assert kimi_managed["camera_grounded_composite_tools"]["candidate_ids"] == ["O"]
    assert kimi_managed["camera_grounded_composite_tools"]["enabled"] is True

    racing = _resolve_agent_sdk_perf_profile(
        _openai_agents_perf_profile_base_args(model_racing=True, model_racing_arm_count=None)
    )
    assert racing["model_racing_observability"] == _expected_model_racing_observability(
        enabled=True,
        mode="get_response_racing_v1",
        candidate_ids=["D", "C"],
        arm_count=2,
        racing_multiplier=2.0,
        winner_selection="first_successful_sdk_response",
        loser_cancellation="cancel_pending_losers",
        unknown_loser_billing=True,
    )


def test_openai_agents_model_racing_observability_metrics_are_aggregate_only(
    tmp_path: Path,
) -> None:
    run_dir = tmp_path / "run"
    run_dir.mkdir()
    (run_dir / "openai-agents-events.jsonl").write_text(
        "\n".join(
            [
                json.dumps(
                    {
                        "schema": "openai_agents_model_racing_observability_v1",
                        "event": "model_racing_arm_start",
                        "provider_profile": "minimax-responses",
                        "wire_api": "responses",
                        "model": "MiniMax-M3",
                        "call_index": 0,
                        "arm_id": "call-0-attempt-0-arm-0",
                        "arm_count": 1,
                        "method": "get_response",
                        "racing_enabled": False,
                        "racing_mode": "per_arm_observability_v1",
                        "racing_multiplier": 1.0,
                    }
                ),
                json.dumps(
                    {
                        "schema": "openai_agents_model_racing_observability_v1",
                        "event": "model_racing_arm_finish",
                        "provider_profile": "minimax-responses",
                        "wire_api": "responses",
                        "model": "MiniMax-M3",
                        "call_index": 0,
                        "arm_id": "call-0-attempt-0-arm-0",
                        "arm_count": 1,
                        "method": "get_response",
                        "racing_enabled": False,
                        "racing_mode": "per_arm_observability_v1",
                        "racing_multiplier": 1.0,
                        "elapsed_s": 2.5,
                        "winner": True,
                        "cancelled": False,
                        "cancellation_observed": False,
                        "loser_billing_unknown": False,
                        "final_outcome": "success",
                        "usage_summary": {
                            "usage_available": True,
                            "input_tokens": 120,
                            "cached_input_tokens": 20,
                            "uncached_input_tokens": 100,
                            "output_tokens": 30,
                            "reasoning_tokens": 5,
                        },
                    }
                ),
            ]
        )
        + "\n",
        encoding="utf-8",
    )

    metrics = _model_racing_observability_metrics(run_dir)

    assert metrics["available"] is True
    assert metrics["source"] == "openai_agents_model_racing_observability_events"
    assert metrics["event_count"] == 2
    assert metrics["event_counts"] == {
        "model_racing_arm_finish": 1,
        "model_racing_arm_start": 1,
    }
    assert metrics["call_count"] == 1
    assert metrics["arm_count"] == 1
    assert metrics["max_arm_count_per_call"] == 1
    assert metrics["racing_enabled"] is False
    assert metrics["racing_multiplier"] == 1.0
    assert metrics["winner_count"] == 1
    assert metrics["cancelled_count"] == 0
    assert metrics["cancellation_observed_count"] == 0
    assert metrics["loser_billing_unknown_count"] == 0
    assert metrics["elapsed_s_total"] == 2.5
    assert metrics["max_elapsed_s"] == 2.5
    assert metrics["usage_available_count"] == 1
    assert metrics["usage_missing_count"] == 0
    assert metrics["total_input_tokens"] == 120
    assert metrics["total_cached_input_tokens"] == 20
    assert metrics["total_uncached_input_tokens"] == 100
    assert metrics["total_output_tokens"] == 30
    assert metrics["total_reasoning_tokens"] == 5
    assert metrics["methods"] == ["get_response"]
    assert metrics["racing_modes"] == ["per_arm_observability_v1"]
    assert metrics["final_outcomes"] == {"success": 1}
    assert metrics["attempted_models"] == ["MiniMax-M3"]
    assert metrics["attempted_provider_profiles"] == ["minimax-responses"]
    assert metrics["attempted_wire_apis"] == ["responses"]
    assert "Raw prompts" in metrics["privacy_note"]
