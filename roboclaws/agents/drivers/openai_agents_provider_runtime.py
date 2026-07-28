"""Provider failure classification and resource lifecycle helpers."""

from __future__ import annotations

from typing import Any

from roboclaws.agents.drivers.openai_agents_budget import OpenAIAgentsBudgetExceededError
from roboclaws.agents.live_status import LiveAgentFailure


async def close_async_resource(resource: Any) -> None:
    close = getattr(resource, "close", None)
    if close is None:
        return
    result = close()
    if hasattr(result, "__await__"):
        await result


def model_service_failure_detail(failure: LiveAgentFailure) -> str:
    if failure.provider_reason == "malformed_response":
        return "Provider response was missing required completion choices."
    return ""


def failure_from_exception(exc: Exception) -> LiveAgentFailure:
    if isinstance(exc, OpenAIAgentsBudgetExceededError):
        return exc.failure
    detail = str(exc)
    if exc.__class__.__name__ == "MaxTurnsExceeded":
        return LiveAgentFailure(
            "agent_sdk_turn_budget_exceeded",
            retryable=False,
            resume_available=False,
            detail=detail,
        )
    lowered = detail.lower()
    failure = _configuration_or_auth_failure(lowered, detail)
    if failure is not None:
        return failure
    failure = _response_shape_or_context_failure(lowered, detail)
    if failure is not None:
        return failure
    failure = _provider_quota_failure(lowered, detail)
    if failure is not None:
        return failure
    failure = _transient_provider_failure(lowered, detail)
    if failure is not None:
        return failure
    return LiveAgentFailure("agent_cli_failure", retryable=False, detail=detail)


def _configuration_or_auth_failure(lowered: str, detail: str) -> LiveAgentFailure | None:
    config_markers = (
        "roboclaws_openai_agents_",
        "openai agents sdk setting",
        "requires codex_responses_base_url",
        "requires codex_responses_api_key",
        "requires codex_responses_model",
        "requires mimo_responses_base_url",
        "requires mimo_responses_api_key",
        "requires mimo_responses_model",
        "requires kimi_openai_base_url",
        "requires kimi_api_key",
        "requires mm_base_url",
        "requires mm_api_key",
        "supports responses provider",
    )
    if any(item in lowered for item in config_markers):
        return LiveAgentFailure("provider_config_failure", retryable=False, detail=detail)
    auth_markers = ("authentication", "unauthorized", "invalid api key", "401")
    if any(item in lowered for item in auth_markers):
        return LiveAgentFailure("provider_auth_failure", retryable=False, detail=detail)
    return None


def _response_shape_or_context_failure(lowered: str, detail: str) -> LiveAgentFailure | None:
    malformed_markers = (
        "response has no choices",
        "possible provider error payload",
    )
    if any(item in lowered for item in malformed_markers):
        return LiveAgentFailure(
            "provider_transient_failure",
            retryable=True,
            provider_reason="malformed_response",
            resume_available=True,
            detail=detail,
        )
    context_markers = (
        "context length",
        "context_length",
        "context window",
        "maximum context",
        "input exceeds the context",
        "too large",
    )
    if any(item in lowered for item in context_markers):
        return LiveAgentFailure("provider_context_failure", retryable=False, detail=detail)
    return None


def _provider_quota_failure(lowered: str, detail: str) -> LiveAgentFailure | None:
    quota_markers = (
        "access_terminated_error",
        "usage limit for this billing cycle",
        "reached your usage limit",
    )
    if any(item in lowered for item in quota_markers):
        return LiveAgentFailure(
            "provider_quota_failure",
            retryable=False,
            provider_reason="billing_limit",
            resume_available=False,
            detail=detail,
        )
    return None


def _transient_provider_failure(lowered: str, detail: str) -> LiveAgentFailure | None:
    unavailable_markers = (
        "429",
        "rate limit",
        "too many requests",
        "500",
        "502",
        "503",
        "504",
        "model unavailable",
        "model_unavailable",
        "temporarily unavailable",
        "service unavailable",
        "internal server error",
        "bad gateway",
        "gateway timeout",
    )
    if any(item in lowered for item in unavailable_markers):
        reason = (
            "rate_limit" if "429" in lowered or "rate limit" in lowered else "upstream_unavailable"
        )
        return _retryable_provider_failure(reason, detail)
    timeout_markers = (
        "timed out",
        "timeout",
        "connection reset",
        "connection refused",
        "connection error",
        "transport error",
        "broken pipe",
        "econnreset",
    )
    if any(item in lowered for item in timeout_markers):
        return _retryable_provider_failure("upstream_timeout", detail)
    return None


def _retryable_provider_failure(reason: str, detail: str) -> LiveAgentFailure:
    return LiveAgentFailure(
        "provider_transient_failure",
        retryable=True,
        provider_reason=reason,
        resume_available=True,
        detail=detail,
    )
