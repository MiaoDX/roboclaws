from __future__ import annotations

import pytest

from roboclaws.agents.drivers.openai_agents_profile_runtime import (
    _sdk_model_settings_for_profile,
)
from roboclaws.agents.provider_transport import (
    bounded_output_tokens,
)


def test_provider_budget_caps_each_model_call_by_tokens_and_cost() -> None:
    assert (
        bounded_output_tokens(
            model="k3",
            token_budget=4_000,
            cost_budget_usd=0.006,
            max_model_calls=4,
        )
        == 500
    )

    settings = _sdk_model_settings_for_profile(
        {
            "provider_profile": "kimi-openai-chat",
            "wire_api": "chat-completions",
            "model": "k3",
            "model_thinking_mode": "default",
            "max_turns": 4,
            "provider_token_budget": 4_000,
            "provider_cost_budget_usd": 0.006,
        }
    )
    assert settings["max_tokens"] == 500


def test_provider_cost_budget_requires_catalog_pricing() -> None:
    with pytest.raises(ValueError, match="requires catalog output pricing"):
        bounded_output_tokens(
            model="opaque-provider-model",
            token_budget=4_000,
            cost_budget_usd=0.006,
            max_model_calls=4,
        )
