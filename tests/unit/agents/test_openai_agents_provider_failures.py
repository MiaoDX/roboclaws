from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

from roboclaws.agents.drivers.openai_agents_live import (
    _RetryingModel,
    _run_with_async_mcp_server,
    _should_retry_model_service_failure,
)
from roboclaws.agents.live_runtime import LiveAgentMCPServer, LiveAgentRequest


def test_retrying_model_closes_base_model_and_explicit_client() -> None:
    closed = []

    class Closeable:
        def __init__(self, name: str) -> None:
            self.name = name

        async def close(self) -> None:
            closed.append(self.name)

    model = _RetryingModel(
        Closeable("model"),
        client=Closeable("client"),
        retry_attempts=0,
        retry_sleep_s=0,
        events_path=Path("unused-events.jsonl"),
        spans_path=Path("unused-spans.jsonl"),
        runtime_config={},
    )

    asyncio.run(model.close())

    assert closed == ["model", "client"]


def test_retrying_model_closes_client_when_base_model_close_fails() -> None:
    client_closed = []

    class FailingModel:
        async def close(self) -> None:
            raise RuntimeError("model close failed")

    class Client:
        async def close(self) -> None:
            client_closed.append(True)

    model = _RetryingModel(
        FailingModel(),
        client=Client(),
        retry_attempts=0,
        retry_sleep_s=0,
        events_path=Path("unused-events.jsonl"),
        spans_path=Path("unused-spans.jsonl"),
        runtime_config={},
    )

    with pytest.raises(RuntimeError, match="model close failed"):
        asyncio.run(model.close())

    assert client_closed == [True]


@pytest.mark.parametrize("runner_fails", [False, True])
def test_async_mcp_runner_closes_model_before_event_loop_exits(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, runner_fails: bool
) -> None:
    lifecycle = []

    class FakeServer:
        async def __aenter__(self):
            lifecycle.append("server-enter")
            return self

        async def __aexit__(self, *_args) -> None:
            lifecycle.append("server-exit")

    class FakeModel:
        async def close(self) -> None:
            asyncio.get_running_loop()
            lifecycle.append("model-close")

    class FakeRunner:
        @staticmethod
        async def run(*_args, **_kwargs):
            lifecycle.append("runner")
            if runner_fails:
                raise RuntimeError("provider failed")
            return SimpleNamespace(final_output="ok")

    monkeypatch.setitem(sys.modules, "agents", SimpleNamespace(Runner=FakeRunner))
    request = LiveAgentRequest(
        run_id="run",
        skill_name="household-world",
        kickoff_prompt="test",
        mcp_server=LiveAgentMCPServer(name="test", url="http://localhost/mcp"),
        run_dir=tmp_path,
    )

    if runner_fails:
        with pytest.raises(RuntimeError, match="provider failed"):
            _run_with_async_mcp_server(
                FakeServer(),
                SimpleNamespace(model=FakeModel()),
                request,
                tmp_path / "events.jsonl",
                run_config=object(),
            )
    else:
        result = _run_with_async_mcp_server(
            FakeServer(),
            SimpleNamespace(model=FakeModel()),
            request,
            tmp_path / "events.jsonl",
            run_config=object(),
        )
        assert result.final_output == "ok"
    assert lifecycle == ["server-enter", "runner", "server-exit", "model-close"]


def test_kimi_missing_choices_is_observable_and_retried_once(tmp_path: Path) -> None:
    message = "ChatCompletion response has no choices (possible provider error payload)"
    should_retry, failure = _should_retry_model_service_failure(
        RuntimeError(message),
        attempt_index=0,
        retry_attempts=1,
    )
    assert should_retry is True
    assert failure.reason == "provider_transient_failure"
    assert failure.provider_reason == "malformed_response"

    class FakeModel:
        def __init__(self) -> None:
            self.calls = 0

        async def get_response(self, *_args, **_kwargs):
            self.calls += 1
            if self.calls == 1:
                raise RuntimeError(message)
            return SimpleNamespace(output="ok", usage={})

    fake_model = FakeModel()
    events_path = tmp_path / "events.jsonl"
    model = _RetryingModel(
        fake_model,
        retry_attempts=1,
        retry_sleep_s=0,
        events_path=events_path,
        spans_path=tmp_path / "spans.jsonl",
        runtime_config={
            "runtime": "openai-agents-live",
            "provider_profile": "kimi-openai-chat",
            "wire_api": "chat-completions",
            "model": "kimi-k2.7-code",
        },
    )

    result = asyncio.run(
        model.get_response(
            None,
            "test",
            object(),
            [],
            None,
            [],
            object(),
            previous_response_id=None,
            conversation_id=None,
            prompt=None,
        )
    )

    failures = [
        event
        for line in events_path.read_text(encoding="utf-8").splitlines()
        if (event := json.loads(line)).get("event") == "model_service_failure"
    ]
    assert result.output == "ok"
    assert fake_model.calls == 2
    assert len(failures) == 1
    assert failures[0]["failure_class"] == "provider_transient_failure"
    assert failures[0]["provider_reason"] == "malformed_response"
    assert failures[0]["failure_detail"] == (
        "Provider response was missing required completion choices."
    )
    assert "final_outcome" not in failures[0]
    assert failures[0]["retryable"] is True
    assert failures[0]["retry_exhausted"] is False
