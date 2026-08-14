from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

from roboclaws.agents.drivers.openai_agents_budget import (
    raw_fpv_budget_metrics,
)
from roboclaws.agents.drivers.openai_agents_live import OpenAIAgentsLiveRuntime
from roboclaws.agents.drivers.openai_agents_provider_runtime import (
    failure_from_exception as _failure_from_exception,
)
from roboclaws.agents.live_runtime import (
    LiveAgentMCPServer,
    LiveAgentRequest,
)
from tests.unit.agents.live_runtime_support import (
    FakeModelSettings,
    FakeRunConfig,
    _assert_openai_agents_config_failure,
)


def test_openai_agents_runtime_classifies_context_window_before_502() -> None:
    failure = _failure_from_exception(
        RuntimeError(
            "Error code: 502 - {'error': {'message': 'Your input exceeds the context "
            "window of this model. Please adjust your input and try again.'}}"
        )
    )

    assert failure.reason == "provider_context_failure"
    assert failure.retryable is False
    assert failure.resume_available is False


@pytest.mark.parametrize(
    ("metadata", "env", "expected_detail"),
    [
        (
            {},
            {"ROBOCLAWS_OPENAI_AGENTS_MCP_CLIENT_SESSION_TIMEOUT_S": "eventually"},
            "mcp_client_session_timeout_s "
            "(ROBOCLAWS_OPENAI_AGENTS_MCP_CLIENT_SESSION_TIMEOUT_S) must be a "
            "finite non-negative number, got 'eventually'",
        ),
        (
            {"mcp_client_session_timeout_s": -1},
            {},
            "mcp_client_session_timeout_s (mcp_client_session_timeout_s) must be a "
            "finite non-negative number, got -1",
        ),
        (
            {"mcp_client_session_timeout_s": True},
            {},
            "mcp_client_session_timeout_s (mcp_client_session_timeout_s) must be a "
            "finite non-negative number, got True",
        ),
        (
            {"mcp_client_session_timeout_s": float("nan")},
            {},
            "mcp_client_session_timeout_s (mcp_client_session_timeout_s) must be a "
            "finite non-negative number, got nan",
        ),
        (
            {},
            {"ROBOCLAWS_OPENAI_AGENTS_MCP_CLIENT_SESSION_TIMEOUT_S": "inf"},
            "mcp_client_session_timeout_s "
            "(ROBOCLAWS_OPENAI_AGENTS_MCP_CLIENT_SESSION_TIMEOUT_S) must be a "
            "finite non-negative number, got 'inf'",
        ),
    ],
)
def test_openai_agents_runtime_rejects_invalid_mcp_timeout_numeric_values(
    tmp_path: Path,
    monkeypatch,
    metadata: dict[str, object],
    env: dict[str, str],
    expected_detail: str,
) -> None:
    for key, value in env.items():
        monkeypatch.setenv(key, value)

    _assert_openai_agents_config_failure(tmp_path, metadata=metadata, detail=expected_detail)


@pytest.mark.parametrize(
    ("value", "expected_detail"),
    [
        ("many", "must be a positive integer, got 'many'"),
        (0, "must be a positive integer, got 0"),
        (True, "must be a positive integer, got True"),
        (float("inf"), "must be a positive integer, got inf"),
    ],
)
def test_openai_agents_runtime_rejects_invalid_direct_max_turns(
    tmp_path: Path,
    value: object,
    expected_detail: str,
) -> None:
    _assert_openai_agents_config_failure(
        tmp_path,
        metadata={"max_turns": value},
        detail=f"OpenAI Agents SDK setting max_turns {expected_detail}",
    )


def test_openai_agents_runtime_allows_disabling_mcp_tool_list_cache(
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
        metadata={"cache_tools_list": False},
    )

    OpenAIAgentsLiveRuntime().run(request)

    assert captured["mcp_server_kwargs"]["cache_tools_list"] is False


def test_raw_fpv_repeated_failures_are_scoped_to_materially_same_view() -> None:
    def observe(source_id: str, yaw_delta_deg: float) -> dict[str, object]:
        return {
            "event": "response",
            "tool": "observe",
            "response": {
                "ok": True,
                "waypoint_id": "room_2_inspection",
                "raw_fpv_observation": {
                    "observation_id": source_id,
                    "camera_offset": {
                        "yaw_delta_deg": yaw_delta_deg,
                        "pitch_delta_deg": 0,
                    },
                },
            },
        }

    def failed_attempt(source_id: str) -> list[dict[str, object]]:
        return [
            {
                "event": "request",
                "tool": "navigate_to_visual_candidate",
                "request": {
                    "source_observation_id": source_id,
                    "category": "cup",
                    "image_region": {"type": "bbox", "value": [10, 20, 30, 40]},
                },
            },
            {
                "event": "response",
                "tool": "navigate_to_visual_candidate",
                "response": {"ok": False, "error_reason": "not_resolved"},
            },
        ]

    metrics = raw_fpv_budget_metrics(
        [
            observe("raw_fpv_001", 0),
            *failed_attempt("raw_fpv_001"),
            observe("raw_fpv_002", 45),
            *failed_attempt("raw_fpv_002"),
            observe("raw_fpv_003", 45),
            *failed_attempt("raw_fpv_003"),
        ]
    )

    assert len(metrics["repeated_failure_fingerprints"]) == 1
    assert metrics["repeated_failure_fingerprints"][0]["count"] == 2
