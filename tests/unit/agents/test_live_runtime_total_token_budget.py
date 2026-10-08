from __future__ import annotations

import asyncio
import json
from concurrent.futures import ThreadPoolExecutor
from types import SimpleNamespace

import pytest

from roboclaws.agents.drivers.openai_agents_budget import OpenAIAgentsBudgetExceededError
from roboclaws.agents.drivers.openai_agents_retry_model import _RetryingModel
from roboclaws.agents.drivers.openai_agents_token_budget import ProviderTokenBudget

CONFIG = {"model": "MiniMax-M3", "provider_profile": "minimax-responses"}
RESERVATION = 2_000_000


def budget_at(path, limit=RESERVATION, **overrides):
    return ProviderTokenBudget(path, {**CONFIG, "total_token_budget": limit, **overrides})


def ledger(path):
    return json.loads((path / "provider_token_budget.json").read_text())


def test_settlement_releases_capacity_and_continuation_keeps_spend(tmp_path):
    budget = budget_at(tmp_path, RESERVATION + 110)
    budget.settle(budget.reserve(), SimpleNamespace(input_tokens=100, output_tokens=10))
    continued = budget_at(tmp_path, RESERVATION + 110, attempt_index=1)
    continued.settle(continued.reserve(), {"input_tokens": 90, "output_tokens": 20})
    with pytest.raises(OpenAIAgentsBudgetExceededError, match="budget_exhausted"):
        continued.reserve()
    assert ledger(tmp_path)["charged_tokens"] == 220
    assert ledger(tmp_path)["failure_reason"] == "provider_total_token_budget_exhausted"


@pytest.mark.parametrize(
    "usage",
    [
        None,
        {},
        {"input_tokens": 1},
        {"input_tokens": 0, "output_tokens": 0},
        {"input_tokens": True, "output_tokens": 1},
        {"input_tokens": -1, "output_tokens": 1},
    ],
)
def test_unknown_usage_never_refunds_and_stops_future_calls(tmp_path, usage):
    budget = budget_at(tmp_path, 3 * RESERVATION)
    with pytest.raises(OpenAIAgentsBudgetExceededError, match="usage_unavailable"):
        budget.settle(budget.reserve(), usage)
    assert ledger(tmp_path)["charged_tokens"] == RESERVATION
    with pytest.raises(OpenAIAgentsBudgetExceededError, match="usage_unavailable"):
        budget_at(tmp_path, 3 * RESERVATION, attempt_index=1).reserve()


def test_provider_exceeding_declared_bound_records_actual_usage_and_stops(tmp_path):
    budget = budget_at(tmp_path)
    with pytest.raises(OpenAIAgentsBudgetExceededError, match="reservation_exceeded"):
        budget.settle(budget.reserve(), {"input_tokens": RESERVATION, "output_tokens": 1})
    assert ledger(tmp_path)["charged_tokens"] == RESERVATION + 1
    with pytest.raises(OpenAIAgentsBudgetExceededError, match="reservation_exceeded"):
        budget_at(tmp_path).reserve()


def test_budget_cannot_be_disabled_changed_or_resumed_without_ledger(tmp_path):
    with pytest.raises(ValueError, match="missing"):
        budget_at(tmp_path, attempt_index=1)
    budget = budget_at(tmp_path)
    for override in (
        {"total_token_budget": None},
        {"total_token_budget": 10},
        {"model": "mimo-v2.6"},
    ):
        with pytest.raises(ValueError):
            budget_at(tmp_path, **override)
    budget.path.unlink()
    with pytest.raises(ValueError, match="disappeared"):
        budget.reserve()


@pytest.mark.parametrize(
    "corruption",
    [
        {"requests": [None]},
        {"requests": [{"charged_tokens": -1, "accounting": "reserved_usage_unknown"}]},
        {"requests": [{"charged_tokens": 0, "accounting": "reserved_usage_unknown"}]},
        {
            "requests": [
                {
                    "charged_tokens": 10,
                    "accounting": "provider_reported",
                    "usage": {"input_tokens": 100, "output_tokens": 10},
                }
            ]
        },
        {"charged_tokens": 0},
        {"remaining_tokens": RESERVATION},
    ],
)
def test_malformed_ledger_fails_closed_without_rewriting_it(tmp_path, corruption):
    budget = budget_at(tmp_path)
    budget.reserve()
    damaged = {**ledger(tmp_path), **corruption}
    budget.path.write_text(json.dumps(damaged))
    with pytest.raises(ValueError, match="malformed|inconsistent"):
        budget.reserve()
    assert ledger(tmp_path) == damaged


def test_double_settlement_and_invalid_index_cannot_refund(tmp_path):
    budget = budget_at(tmp_path)
    index = budget.reserve()
    for bad in [-1, 1, True]:
        with pytest.raises(ValueError, match="index"):
            budget.settle(bad, {"input_tokens": 1, "output_tokens": 0})
    budget.settle(index, {"input_tokens": 100, "output_tokens": 10})
    with pytest.raises(ValueError, match="already settled"):
        budget.settle(index, {"input_tokens": 1, "output_tokens": 0})
    assert ledger(tmp_path)["charged_tokens"] == 110


def test_concurrent_reservations_share_one_limit(tmp_path):
    def reserve(_):
        try:
            return budget_at(tmp_path).reserve()
        except OpenAIAgentsBudgetExceededError:
            return None

    with ThreadPoolExecutor(max_workers=4) as pool:
        outcomes = list(pool.map(reserve, range(8)))
    assert outcomes.count(0) == 1
    assert len(ledger(tmp_path)["requests"]) == 1


@pytest.mark.parametrize(
    "overrides,match",
    [
        ({"model": "unknown"}, "declared context"),
        ({"model_racing_observability": {"enabled": True, "arm_count": 2}}, "single-arm"),
    ],
)
def test_unsupported_budget_config_rejected(tmp_path, overrides, match):
    with pytest.raises(ValueError, match=match):
        budget_at(tmp_path, **overrides)


class FakeModel:
    def __init__(self, *, fail_first=False, usage=None, cancel=False, completed=True):
        self.calls = 0
        self.fail_first = fail_first
        self.cancel = cancel
        self.completed = completed
        self.usage = usage or {"input_tokens": 100, "output_tokens": 10}

    async def get_response(self, *args, **kwargs):
        self.calls += 1
        if self.cancel:
            raise asyncio.CancelledError()
        if self.fail_first and self.calls == 1:
            raise RuntimeError("503 service unavailable")
        return SimpleNamespace(output=[], usage=self.usage)

    async def stream_response(self, *args, **kwargs):
        result = await self.get_response()
        if self.completed:
            yield SimpleNamespace(type="response.completed", response=result)


def wrapped(path, base, limit):
    return _RetryingModel(
        base,
        retry_attempts=1,
        retry_sleep_s=0,
        events_path=path / "events.jsonl",
        spans_path=path / "spans.jsonl",
        runtime_config={**CONFIG, "total_token_budget": limit},
    )


async def call(model, *, stream=False):
    args = (None, "private test prompt", object(), [], None, [], object())
    kwargs = {"previous_response_id": None, "conversation_id": None, "prompt": None}
    if stream:
        return [event async for event in model.stream_response(*args, **kwargs)]
    return await model.get_response(*args, **kwargs)


@pytest.mark.parametrize("stream", [False, True])
def test_budget_denies_outbound_call_before_provider_is_touched(tmp_path, stream):
    base = FakeModel()
    with pytest.raises(OpenAIAgentsBudgetExceededError, match="budget_exhausted"):
        asyncio.run(call(wrapped(tmp_path, base, RESERVATION - 1), stream=stream))
    assert base.calls == 0
    assert ledger(tmp_path)["charged_tokens"] == 0


@pytest.mark.parametrize(
    "limit,calls,charge",
    [
        (RESERVATION, 1, RESERVATION),
        (2 * RESERVATION, 2, RESERVATION + 110),
    ],
)
@pytest.mark.parametrize("stream", [False, True])
def test_transport_retry_requires_a_second_reservation(tmp_path, limit, calls, charge, stream):
    base = FakeModel(fail_first=True)
    model = wrapped(tmp_path, base, limit)
    if calls == 1:
        with pytest.raises(OpenAIAgentsBudgetExceededError, match="budget_exhausted"):
            asyncio.run(call(model, stream=stream))
    else:
        asyncio.run(call(model, stream=stream))
    assert base.calls == calls
    assert ledger(tmp_path)["charged_tokens"] == charge
    assert "private test prompt" not in model.token_budget.path.read_text()


def test_cancellation_leaves_full_reservation(tmp_path):
    with pytest.raises(asyncio.CancelledError):
        asyncio.run(call(wrapped(tmp_path, FakeModel(cancel=True), RESERVATION)))
    assert ledger(tmp_path)["charged_tokens"] == RESERVATION


def test_stream_without_terminal_usage_stops_without_refund(tmp_path):
    base = FakeModel(completed=False)
    with pytest.raises(OpenAIAgentsBudgetExceededError, match="usage_unavailable"):
        asyncio.run(call(wrapped(tmp_path, base, 3 * RESERVATION), stream=True))
    assert base.calls == 1
    assert ledger(tmp_path)["charged_tokens"] == RESERVATION


def test_real_sdk_client_cannot_retry_outside_ledger(tmp_path, monkeypatch):
    import httpx
    import openai
    from agents import ModelSettings
    from agents.models.interface import ModelTracing

    from roboclaws.agents.drivers.openai_agents_live import _model_for_request
    from roboclaws.agents.live_runtime import LiveAgentMCPServer, LiveAgentRequest

    attempts = []

    def unavailable(request):
        attempts.append(request.url.path)
        return httpx.Response(503, json={"error": {"message": "service unavailable"}})

    real_client = openai.AsyncOpenAI
    monkeypatch.setattr(
        openai,
        "AsyncOpenAI",
        lambda **kw: real_client(
            **kw, http_client=httpx.AsyncClient(transport=httpx.MockTransport(unavailable))
        ),
    )
    monkeypatch.setenv("MM_BASE_URL", "https://provider.example.test/v1")
    monkeypatch.setenv("MM_API_KEY", "test-key")
    request = LiveAgentRequest(
        run_id="budget-test",
        skill_name="household-world",
        kickoff_prompt="test",
        mcp_server=LiveAgentMCPServer(name="unused", url="http://127.0.0.1:1/mcp"),
        run_dir=tmp_path,
        provider_profile="minimax-responses",
        metadata={"agent_sdk_perf_profile": {"total_token_budget": RESERVATION}},
    )
    model = _model_for_request(request)

    async def run():
        try:
            await model.get_response(
                None,
                "hello",
                ModelSettings(),
                [],
                None,
                [],
                ModelTracing.DISABLED,
                previous_response_id=None,
                conversation_id=None,
                prompt=None,
            )
        finally:
            await model.close()

    with pytest.raises(OpenAIAgentsBudgetExceededError, match="budget_exhausted"):
        asyncio.run(run())
    assert len(attempts) == 1
    assert ledger(tmp_path)["charged_tokens"] == RESERVATION


@pytest.mark.parametrize("fail_first", [False, True])
def test_decision_limit_survives_continuation_and_counts_retries_once(tmp_path, fail_first):
    base = FakeModel(fail_first=fail_first)

    def continuation(attempt):
        filename = (
            "openai-agents-events.jsonl"
            if not attempt
            else f"openai-agents-events.continuation-{attempt}.jsonl"
        )
        return _RetryingModel(
            base,
            retry_attempts=1,
            retry_sleep_s=0,
            events_path=tmp_path / filename,
            spans_path=tmp_path / f"spans-{attempt}.jsonl",
            runtime_config={**CONFIG, "decision_call_budget": 2, "attempt_index": attempt},
        )

    asyncio.run(call(continuation(0)))
    resumed = continuation(1)
    asyncio.run(call(resumed))
    assert resumed.runtime_config["decision_calls_used"] == 2
    with pytest.raises(OpenAIAgentsBudgetExceededError, match="decision_call_budget_exhausted"):
        asyncio.run(call(continuation(2)))
    assert base.calls == (3 if fail_first else 2)


@pytest.mark.parametrize("prior_log", [None, "{truncated", '{"event":"model_service_attempt"}'])
def test_continuation_rejects_missing_or_corrupt_decision_accounting(tmp_path, prior_log):
    if prior_log is not None:
        (tmp_path / "openai-agents-events.jsonl").write_text(prior_log)
    # The current attempt's fresh start event cannot stand in for missing history.
    current = tmp_path / "openai-agents-events.continuation-1.jsonl"
    current.write_text('{"event":"start"}\n')
    with pytest.raises(OpenAIAgentsBudgetExceededError, match="accounting_unavailable"):
        _RetryingModel(
            FakeModel(),
            retry_attempts=0,
            retry_sleep_s=0,
            events_path=current,
            spans_path=tmp_path / "spans.jsonl",
            runtime_config={**CONFIG, "decision_call_budget": 1, "attempt_index": 1},
        )
