from __future__ import annotations

import pytest

from roboclaws.agents.thinking_policy import (
    apply_model_thinking_policy,
    normalize_thinking_mode,
    thinking_request_body_for_wire,
)


def test_default_thinking_policy_maps_by_wire_api() -> None:
    responses = apply_model_thinking_policy(
        {"store": False},
        provider_profile="mimo-responses",
        wire_api="responses",
        mode="default",
    )
    mimo_chat = apply_model_thinking_policy(
        {"include_usage": True},
        provider_profile="mimo-tp-openai-chat",
        wire_api="chat-completions",
        mode="default",
    )

    assert responses["reasoning"] == {"effort": "medium"}
    assert mimo_chat["extra_body"] == {"thinking": {"type": "enabled", "keep": "all"}}
    assert thinking_request_body_for_wire(
        provider_profile="mimo-tp-openai-chat",
        wire_api="chat-completions",
        mode="default",
    ) == {"thinking": {"type": "enabled", "keep": "all"}}


def test_disabled_thinking_policy_maps_by_wire_api() -> None:
    assert thinking_request_body_for_wire(
        provider_profile="minimax-responses",
        wire_api="responses",
        mode="disabled",
    ) == {"reasoning": {"effort": "none"}}
    assert thinking_request_body_for_wire(
        provider_profile="mimo-tp-openai-chat", wire_api="chat-completions", mode="disabled"
    ) == {"thinking": {"type": "disabled"}}


def test_thinking_policy_rejects_unknown_wire_api() -> None:
    with pytest.raises(ValueError, match="unsupported"):
        thinking_request_body_for_wire(
            provider_profile="unknown",
            wire_api="anthropic",
            mode="enabled",
        )


def test_normalize_thinking_mode_accepts_provider_default_aliases() -> None:
    assert normalize_thinking_mode("") == "default"
    assert normalize_thinking_mode("auto") == "default"
    assert normalize_thinking_mode("provider-default") == "default"


@pytest.mark.parametrize("profile", ["kimi-openai-chat", "qwen-tp-responses"])
def test_retired_thinking_policy_is_not_executable(profile):
    with pytest.raises(ValueError, match="retired"):
        thinking_request_body_for_wire(
            provider_profile=profile, wire_api="responses", mode="default"
        )
