from __future__ import annotations

import json
from unittest.mock import MagicMock, patch

import pytest

from roboclaws.core.provider_factory import create_provider
from roboclaws.core.provider_retry import retry_delay_seconds
from roboclaws.core.provider_runtime import (
    NAVIGATION_ACTIONS,
    SAFE_FALLBACK_ACTION,
    ProviderHealthError,
    VLMProvider,
)
from roboclaws.core.providers.anthropic import AnthropicProvider
from roboclaws.core.providers.kimi import KimiCodingProvider, KimiProvider
from roboclaws.core.providers.mock import MockProvider
from roboclaws.core.providers.openai import OpenAIProvider

# ---------------------------------------------------------------------------
# Fixtures / helpers
# ---------------------------------------------------------------------------

SAMPLE_IMAGES = ["aGVsbG8=", "d29ybGQ="]  # arbitrary base64 strings
SAMPLE_STATE = {
    "position": {"x": 1.0, "y": 0.0, "z": -2.5},
    "facing": "East",
    "score": 10,
    "remaining_steps": 150,
}


def _mock_action_result(reasoning: str = "ok", action: str = "MoveAhead") -> MagicMock:
    """Return a mock AgentAction-like object with .reasoning and .action."""
    r = MagicMock()
    r.reasoning = reasoning
    r.action = action
    return r


def _mock_openai_usage(prompt_tokens: int = 100, completion_tokens: int = 50) -> MagicMock:
    usage = MagicMock()
    usage.prompt_tokens = prompt_tokens
    usage.completion_tokens = completion_tokens
    return usage


def _mock_anthropic_usage(input_tokens: int = 100, output_tokens: int = 50) -> MagicMock:
    usage = MagicMock()
    usage.input_tokens = input_tokens
    usage.output_tokens = output_tokens
    return usage


# ---------------------------------------------------------------------------
# MockProvider
# ---------------------------------------------------------------------------


def test_mock_provider_returns_valid_action():
    p = MockProvider(seed=42)
    result = p.get_action(SAMPLE_IMAGES, SAMPLE_STATE)
    assert result["action"] in NAVIGATION_ACTIONS
    assert "reasoning" in result


def test_mock_provider_cost_is_zero():
    p = MockProvider()
    p.get_action(SAMPLE_IMAGES, SAMPLE_STATE)
    assert p.cumulative_cost == 0.0


def test_mock_provider_reset_cost():
    p = MockProvider()
    p.reset_cost()  # no-op but must not raise
    assert p.cumulative_cost == 0.0


def test_mock_provider_deterministic_with_seed():
    p1 = MockProvider(seed=0)
    p2 = MockProvider(seed=0)
    r1 = p1.get_action(SAMPLE_IMAGES, SAMPLE_STATE)
    r2 = p2.get_action(SAMPLE_IMAGES, SAMPLE_STATE)
    assert r1["action"] == r2["action"]


def test_mock_provider_satisfies_protocol():
    p = MockProvider()
    assert isinstance(p, VLMProvider)


# ---------------------------------------------------------------------------
# create_provider factory
# ---------------------------------------------------------------------------


def test_create_provider_mock():
    p = create_provider("mock")
    assert isinstance(p, MockProvider)


def test_create_provider_mock_with_seed():
    p = create_provider("mock", seed=99)
    assert isinstance(p, MockProvider)


def test_create_provider_unknown_raises():
    with pytest.raises(ValueError, match="Unknown model"):
        create_provider("unknown-model")


def test_create_provider_gpt4o(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "test-key")
    with patch("roboclaws.core.provider_factory.OpenAIProvider.__init__", return_value=None):
        p = create_provider("gpt-4o")
    assert isinstance(p, OpenAIProvider)


def test_create_provider_gpt4o_mini(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "test-key")
    with patch("roboclaws.core.provider_factory.OpenAIProvider.__init__", return_value=None):
        p = create_provider("gpt-4o-mini")
    assert isinstance(p, OpenAIProvider)


def test_create_provider_kimi(monkeypatch):
    monkeypatch.setenv("KIMI_API_KEY", "test-key")
    with patch("roboclaws.core.provider_factory.KimiCodingProvider.__init__", return_value=None):
        p = create_provider("kimi")
    assert isinstance(p, KimiCodingProvider)


def test_create_provider_kimi_alias(monkeypatch):
    monkeypatch.setenv("KIMI_API_KEY", "test-key")
    with patch("roboclaws.core.provider_factory.KimiProvider.__init__", return_value=None):
        p = create_provider("kimi-k2-5")
    assert isinstance(p, KimiProvider)


def test_create_provider_anthropic(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
    with patch("roboclaws.core.provider_factory.AnthropicProvider.__init__", return_value=None):
        p = create_provider("anthropic")
    assert isinstance(p, AnthropicProvider)


def test_create_provider_claude_sonnet(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
    with patch("roboclaws.core.provider_factory.AnthropicProvider.__init__", return_value=None):
        p = create_provider("claude-3-5-sonnet-20241022")
    assert isinstance(p, AnthropicProvider)


# ---------------------------------------------------------------------------
# OpenAIProvider (mocked)
# ---------------------------------------------------------------------------


@pytest.fixture()
def openai_provider(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "test-key")
    mock_raw_client = MagicMock()
    mock_instructor_client = MagicMock()

    mock_openai_mod = MagicMock()
    mock_openai_mod.OpenAI.return_value = mock_raw_client

    mock_instructor_mod = MagicMock()
    mock_instructor_mod.from_openai.return_value = mock_instructor_client

    with patch.dict("sys.modules", {"openai": mock_openai_mod, "instructor": mock_instructor_mod}):
        provider = OpenAIProvider(model="gpt-4o-mini", api_key="test-key")
    provider._cost_table = {"input": 0.15, "output": 0.60}
    return provider, mock_instructor_client


def test_openai_get_action_calls_api(openai_provider):
    provider, mock_client = openai_provider
    mock_response = MagicMock()
    mock_response.usage = _mock_openai_usage()
    mock_client.chat.completions.create_with_completion.return_value = (
        _mock_action_result("Move ahead", "MoveAhead"),
        mock_response,
    )
    result = provider.get_action(SAMPLE_IMAGES, SAMPLE_STATE)
    assert result["action"] == "MoveAhead"
    mock_client.chat.completions.create_with_completion.assert_called_once()


def test_openai_get_action_uses_shared_decision_fallback(openai_provider):
    provider, mock_client = openai_provider
    mock_response = MagicMock()
    mock_response.usage = _mock_openai_usage()
    mock_client.chat.completions.create_with_completion.return_value = (
        _mock_action_result("bad action", "WalkIntoWall"),
        mock_response,
    )

    result = provider.get_action(SAMPLE_IMAGES, SAMPLE_STATE)

    assert result == {"reasoning": "bad action", "action": SAFE_FALLBACK_ACTION}


def test_openai_accumulates_cost(openai_provider):
    provider, mock_client = openai_provider
    mock_response = MagicMock()
    mock_response.usage = _mock_openai_usage(prompt_tokens=1_000_000, completion_tokens=1_000_000)
    mock_client.chat.completions.create_with_completion.return_value = (
        _mock_action_result("ok", "RotateLeft"),
        mock_response,
    )
    provider.get_action(SAMPLE_IMAGES, SAMPLE_STATE)
    # 1M input @ $0.15/M + 1M output @ $0.60/M = $0.75
    assert abs(provider.cumulative_cost - 0.75) < 1e-9


def test_openai_reset_cost(openai_provider):
    provider, mock_client = openai_provider
    mock_response = MagicMock()
    mock_response.usage = _mock_openai_usage(100, 50)
    mock_client.chat.completions.create_with_completion.return_value = (
        _mock_action_result("ok", "Done"),
        mock_response,
    )
    provider.get_action(SAMPLE_IMAGES, SAMPLE_STATE)
    assert provider.cumulative_cost > 0
    provider.reset_cost()
    assert provider.cumulative_cost == 0.0


def test_openai_build_messages_includes_images(openai_provider):
    provider, _ = openai_provider
    messages = provider._build_messages(SAMPLE_IMAGES, SAMPLE_STATE)
    assert len(messages) == 1
    content = messages[0]["content"]
    image_entries = [c for c in content if c.get("type") == "image_url"]
    assert len(image_entries) == len(SAMPLE_IMAGES)
    text_entries = [c for c in content if c.get("type") == "text"]
    assert len(text_entries) == 1


def test_openai_missing_api_key_raises(monkeypatch):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    mock_openai = MagicMock()
    mock_openai.OpenAI.side_effect = KeyError("OPENAI_API_KEY")
    with patch.dict("sys.modules", {"openai": mock_openai, "instructor": MagicMock()}):
        with pytest.raises(KeyError):
            OpenAIProvider(model="gpt-4o-mini")


# ---------------------------------------------------------------------------
# KimiProvider (mocked)
# ---------------------------------------------------------------------------


@pytest.fixture()
def kimi_provider(monkeypatch):
    monkeypatch.setenv("KIMI_API_KEY", "test-key")
    mock_raw_client = MagicMock()
    mock_instructor_client = MagicMock()

    mock_anthropic_mod = MagicMock()
    mock_anthropic_mod.Anthropic.return_value = mock_raw_client

    mock_instructor_mod = MagicMock()
    mock_instructor_mod.from_anthropic.return_value = mock_instructor_client

    with patch.dict(
        "sys.modules", {"anthropic": mock_anthropic_mod, "instructor": mock_instructor_mod}
    ):
        provider = KimiProvider(model="kimi-k2-5", api_key="test-key")
    provider._client = mock_instructor_client
    provider._cost_table = {"input": 1.00, "output": 3.00}
    return provider, mock_instructor_client


def test_kimi_get_action_calls_api(kimi_provider):
    provider, mock_client = kimi_provider
    mock_response = MagicMock()
    mock_response.usage = _mock_anthropic_usage()
    mock_client.messages.create_with_completion.return_value = (
        _mock_action_result("Rotate", "RotateRight"),
        mock_response,
    )
    result = provider.get_action(SAMPLE_IMAGES, SAMPLE_STATE)
    assert result["action"] == "RotateRight"
    mock_client.messages.create_with_completion.assert_called_once()


def test_kimi_accumulates_cost(kimi_provider):
    provider, mock_client = kimi_provider
    mock_response = MagicMock()
    mock_response.usage = _mock_anthropic_usage(input_tokens=1_000_000, output_tokens=1_000_000)
    mock_client.messages.create_with_completion.return_value = (
        _mock_action_result("ok", "MoveAhead"),
        mock_response,
    )
    provider.get_action(SAMPLE_IMAGES, SAMPLE_STATE)
    # 1M input @ $1.00/M + 1M output @ $3.00/M = $4.00
    assert abs(provider.cumulative_cost - 4.00) < 1e-9


def test_kimi_reset_cost(kimi_provider):
    provider, mock_client = kimi_provider
    mock_response = MagicMock()
    mock_response.usage = _mock_anthropic_usage(100, 50)
    mock_client.messages.create_with_completion.return_value = (
        _mock_action_result("ok", "Done"),
        mock_response,
    )
    provider.get_action(SAMPLE_IMAGES, SAMPLE_STATE)
    assert provider.cumulative_cost > 0
    provider.reset_cost()
    assert provider.cumulative_cost == 0.0


def test_kimi_retries_transient_overload(kimi_provider):
    provider, mock_client = kimi_provider

    class RateLimitError(Exception):
        pass

    transient_error = RateLimitError("The engine is currently overloaded, please try again later")
    mock_response = MagicMock()
    mock_response.usage = _mock_anthropic_usage()
    mock_client.messages.create_with_completion.side_effect = [
        transient_error,
        (_mock_action_result("retry ok", "MoveRight"), mock_response),
    ]

    with patch("roboclaws.core.providers.anthropic.time.sleep") as sleep:
        result = provider.get_action(SAMPLE_IMAGES, SAMPLE_STATE)

    assert result == {"reasoning": "retry ok", "action": "MoveRight"}
    assert mock_client.messages.create_with_completion.call_count == 2
    sleep.assert_called_once_with(retry_delay_seconds(0, base=1.0, cap=4.0))


def test_kimi_status_tracks_retries(kimi_provider):
    provider, mock_client = kimi_provider

    class RateLimitError(Exception):
        pass

    transient_error = RateLimitError("The engine is currently overloaded, please try again later")
    mock_response = MagicMock()
    mock_response.usage = _mock_anthropic_usage()
    mock_client.messages.create_with_completion.side_effect = [
        transient_error,
        (_mock_action_result("retry ok", "MoveRight"), mock_response),
    ]

    with patch("roboclaws.core.providers.anthropic.time.sleep"):
        provider.get_action(SAMPLE_IMAGES, SAMPLE_STATE)

    status = provider.get_status()
    assert status["successful_calls"] == 1
    assert status["retry_events"] == 1
    assert status["transient_errors"] == 1
    assert status["calls_with_retries"] == 1


def test_kimi_stops_after_transient_error_budget(kimi_provider):
    provider, mock_client = kimi_provider
    provider._status.max_transient_errors = 2
    provider._status.max_calls_with_retries = None

    class RateLimitError(Exception):
        pass

    transient_error = RateLimitError("The engine is currently overloaded, please try again later")
    mock_client.messages.create_with_completion.side_effect = [
        transient_error,
        transient_error,
        (_mock_action_result("too late", "MoveAhead"), MagicMock()),
    ]

    with patch("roboclaws.core.providers.anthropic.time.sleep") as sleep:
        with pytest.raises(ProviderHealthError, match="transient_error_budget_exceeded"):
            provider.get_action(SAMPLE_IMAGES, SAMPLE_STATE)

    status = provider.get_status()
    assert status["stop_reason"] == "transient_error_budget_exceeded"
    assert status["failed_calls"] == 1
    assert mock_client.messages.create_with_completion.call_count == 2
    sleep.assert_called_once_with(retry_delay_seconds(0, base=1.0, cap=4.0))


def test_kimi_does_not_retry_non_transient_error(kimi_provider):
    provider, mock_client = kimi_provider
    mock_client.messages.create_with_completion.side_effect = ValueError("bad request")

    with patch("roboclaws.core.providers.anthropic.time.sleep") as sleep:
        with pytest.raises(ValueError, match="bad request"):
            provider.get_action(SAMPLE_IMAGES, SAMPLE_STATE)

    sleep.assert_not_called()
    assert mock_client.messages.create_with_completion.call_count == 1


def test_kimi_missing_api_key_raises(monkeypatch):
    monkeypatch.delenv("KIMI_API_KEY", raising=False)
    with patch.dict("sys.modules", {"anthropic": MagicMock(), "instructor": MagicMock()}):
        with pytest.raises(KeyError):
            KimiProvider(model="kimi-k2-5")


def test_kimi_coding_get_action_uses_shared_decision_fallback(monkeypatch):
    monkeypatch.setenv("KIMI_API_KEY", "test-key")
    provider = KimiCodingProvider(api_key="test-key", retry_attempts=1)

    response = MagicMock()
    response.raise_for_status.return_value = None
    response.text = json.dumps(
        {
            "choices": [{"message": {"content": "not json", "reasoning_content": ""}}],
            "usage": {},
        }
    )
    provider._client = MagicMock()
    provider._client.post.return_value = response

    result = provider.get_action(SAMPLE_IMAGES, SAMPLE_STATE)

    assert result["action"] == SAFE_FALLBACK_ACTION
    assert "not json" in result["reasoning"]


@pytest.mark.parametrize(
    ("response_text", "expected_error"),
    [
        ("{not-json", "Kimi coding provider response source must contain valid JSON object"),
        ("[]", "Kimi coding provider response source must contain a JSON object"),
    ],
)
def test_kimi_coding_get_action_rejects_bad_provider_response_source(
    monkeypatch,
    response_text: str,
    expected_error: str,
) -> None:
    monkeypatch.setenv("KIMI_API_KEY", "test-key")
    provider = KimiCodingProvider(api_key="test-key", retry_attempts=1)

    response = MagicMock()
    response.raise_for_status.return_value = None
    response.text = response_text
    provider._client = MagicMock()
    provider._client.post.return_value = response

    with pytest.raises(ValueError, match=expected_error):
        provider.get_action(SAMPLE_IMAGES, SAMPLE_STATE)

    status = provider.get_status()
    assert status["failed_calls"] == 1
    assert status["last_error_kind"] == "ValueError"
    assert expected_error in status["last_error"]


# ---------------------------------------------------------------------------
# AnthropicProvider (mocked)
# ---------------------------------------------------------------------------


@pytest.fixture()
def anthropic_provider(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
    mock_raw_client = MagicMock()
    mock_instructor_client = MagicMock()

    mock_anthropic_mod = MagicMock()
    mock_anthropic_mod.Anthropic.return_value = mock_raw_client

    mock_instructor_mod = MagicMock()
    mock_instructor_mod.from_anthropic.return_value = mock_instructor_client

    with patch.dict(
        "sys.modules", {"anthropic": mock_anthropic_mod, "instructor": mock_instructor_mod}
    ):
        provider = AnthropicProvider(model="claude-3-5-sonnet-20241022", api_key="test-key")
    provider._client = mock_instructor_client
    provider._cost_table = {"input": 3.00, "output": 15.00}
    return provider, mock_instructor_client


def test_anthropic_get_action_calls_api(anthropic_provider):
    provider, mock_client = anthropic_provider
    mock_response = MagicMock()
    mock_response.usage = _mock_anthropic_usage()
    mock_client.messages.create_with_completion.return_value = (
        _mock_action_result("Explore", "MoveAhead"),
        mock_response,
    )
    result = provider.get_action(SAMPLE_IMAGES, SAMPLE_STATE)
    assert result["action"] == "MoveAhead"
    assert result["reasoning"] == "Explore"
    mock_client.messages.create_with_completion.assert_called_once()


def test_anthropic_accumulates_cost(anthropic_provider):
    provider, mock_client = anthropic_provider
    mock_response = MagicMock()
    mock_response.usage = _mock_anthropic_usage(input_tokens=1_000_000, output_tokens=1_000_000)
    mock_client.messages.create_with_completion.return_value = (
        _mock_action_result("ok", "RotateLeft"),
        mock_response,
    )
    provider.get_action(SAMPLE_IMAGES, SAMPLE_STATE)
    # 1M input @ $3.00/M + 1M output @ $15.00/M = $18.00
    assert abs(provider.cumulative_cost - 18.00) < 1e-9


def test_anthropic_reset_cost(anthropic_provider):
    provider, mock_client = anthropic_provider
    mock_response = MagicMock()
    mock_response.usage = _mock_anthropic_usage(100, 50)
    mock_client.messages.create_with_completion.return_value = (
        _mock_action_result("ok", "Done"),
        mock_response,
    )
    provider.get_action(SAMPLE_IMAGES, SAMPLE_STATE)
    assert provider.cumulative_cost > 0
    provider.reset_cost()
    assert provider.cumulative_cost == 0.0


def test_anthropic_missing_api_key_raises(monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    with patch.dict("sys.modules", {"anthropic": MagicMock(), "instructor": MagicMock()}):
        with pytest.raises(KeyError):
            AnthropicProvider(model="claude-3-5-sonnet-20241022")


def test_anthropic_satisfies_protocol(anthropic_provider):
    provider, _ = anthropic_provider
    assert isinstance(provider, VLMProvider)
