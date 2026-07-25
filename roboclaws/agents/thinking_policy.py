from __future__ import annotations

from typing import Any, Literal

from roboclaws.agents.provider_registry import (
    PROVIDER_PROFILE_KIMI_OPENAI_CHAT,
    WIRE_CHAT_COMPLETIONS,
    WIRE_RESPONSES,
)

THINKING_MODE_DEFAULT = "default"
THINKING_MODE_ENABLED = "enabled"
THINKING_MODE_DISABLED = "disabled"
THINKING_MODES = (
    THINKING_MODE_DEFAULT,
    THINKING_MODE_ENABLED,
    THINKING_MODE_DISABLED,
)
ThinkingMode = Literal["default", "enabled", "disabled"]


def normalize_thinking_mode(value: Any, *, default: ThinkingMode = THINKING_MODE_DEFAULT) -> str:
    raw = str(value or "").strip().lower()
    if raw in {"", "auto", "provider-default"}:
        return default
    if raw in THINKING_MODES:
        return raw
    allowed = "|".join(THINKING_MODES)
    raise ValueError(f"unsupported thinking mode {value!r}; expected {allowed}")


def apply_model_thinking_policy(
    settings: dict[str, Any],
    *,
    provider_profile: str,
    wire_api: str,
    mode: str,
) -> dict[str, Any]:
    """Apply provider-aware thinking settings to an OpenAI Agents SDK settings dict."""

    normalized = normalize_thinking_mode(mode)
    if normalized == THINKING_MODE_DEFAULT:
        if wire_api in {WIRE_CHAT_COMPLETIONS, WIRE_RESPONSES}:
            return apply_model_thinking_policy(
                settings,
                provider_profile=provider_profile,
                wire_api=wire_api,
                mode=THINKING_MODE_ENABLED,
            )
        return settings
    if provider_profile == PROVIDER_PROFILE_KIMI_OPENAI_CHAT:
        if wire_api != WIRE_CHAT_COMPLETIONS:
            raise ValueError("Kimi K2.7 Code thinking policy is only supported on OpenAI Chat")
        if normalized == THINKING_MODE_DISABLED:
            raise ValueError("Kimi K2.7 Code is thinking-only and cannot disable thinking mode")
        return settings
    if wire_api == WIRE_CHAT_COMPLETIONS:
        extra_body = dict(settings.get("extra_body") or {})
        extra_body["thinking"] = _kimi_thinking_payload(normalized)
        settings["extra_body"] = extra_body
        return settings
    if wire_api == WIRE_RESPONSES:
        settings["reasoning"] = _responses_reasoning_payload(normalized)
        return settings
    raise ValueError(
        f"thinking mode {normalized!r} is unsupported for provider_profile={provider_profile!r} "
        f"wire_api={wire_api!r}"
    )


def thinking_request_body_for_wire(
    *,
    provider_profile: str,
    wire_api: str,
    mode: str,
) -> dict[str, Any]:
    """Return raw HTTP request-body fields for model-matrix/direct probes."""

    normalized = normalize_thinking_mode(mode)
    if normalized == THINKING_MODE_DEFAULT:
        if wire_api in {WIRE_CHAT_COMPLETIONS, WIRE_RESPONSES}:
            normalized = THINKING_MODE_ENABLED
        else:
            return {}
    if provider_profile == PROVIDER_PROFILE_KIMI_OPENAI_CHAT:
        if wire_api != WIRE_CHAT_COMPLETIONS:
            raise ValueError("Kimi K2.7 Code thinking policy is only supported on OpenAI Chat")
        if normalized == THINKING_MODE_DISABLED:
            raise ValueError("Kimi K2.7 Code is thinking-only and cannot disable thinking mode")
        return {}
    if wire_api == WIRE_CHAT_COMPLETIONS:
        return {"thinking": _kimi_thinking_payload(normalized)}
    if wire_api == WIRE_RESPONSES:
        return {"reasoning": _responses_reasoning_payload(normalized)}
    raise ValueError(
        f"thinking mode {normalized!r} is unsupported for provider_profile={provider_profile!r} "
        f"wire_api={wire_api!r}"
    )


def _kimi_thinking_payload(mode: str) -> dict[str, str]:
    if mode == THINKING_MODE_ENABLED:
        return {"type": "enabled", "keep": "all"}
    if mode == THINKING_MODE_DISABLED:
        return {"type": "disabled"}
    raise ValueError(f"unsupported Kimi thinking mode {mode!r}")


def _responses_reasoning_payload(mode: str) -> dict[str, str]:
    if mode == THINKING_MODE_ENABLED:
        return {"effort": "medium"}
    if mode == THINKING_MODE_DISABLED:
        return {"effort": "none"}
    raise ValueError(f"unsupported Responses reasoning mode {mode!r}")
