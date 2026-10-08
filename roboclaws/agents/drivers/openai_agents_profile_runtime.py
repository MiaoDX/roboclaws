"""Provider-facing runtime settings projected from Agent SDK profiles."""

from __future__ import annotations

from typing import Any

from roboclaws.agents.provider_transport import (
    bounded_output_tokens,
)
from roboclaws.core.provider_catalog import (
    WIRE_CHAT_COMPLETIONS,
    WIRE_RESPONSES,
)


def _sdk_model_settings_for_profile(profile: dict[str, Any]) -> dict[str, Any]:
    wire_api = str(profile.get("wire_api") or "")
    settings: dict[str, Any] = {
        "tool_choice": "auto",
        "parallel_tool_calls": False,
        "model_thinking_mode": str(profile.get("model_thinking_mode") or "default"),
    }
    token_budget = float(profile.get("provider_token_budget") or 0.0)
    cost_budget_usd = float(profile.get("provider_cost_budget_usd") or 0.0)
    if bool(token_budget) != bool(cost_budget_usd):
        raise ValueError("provider token and cost budgets must be configured together")
    if token_budget:
        settings["max_tokens"] = bounded_output_tokens(
            model=str(profile.get("model") or ""),
            token_budget=token_budget,
            cost_budget_usd=cost_budget_usd,
            max_model_calls=int(profile.get("max_turns") or 0),
        )
    if wire_api == WIRE_RESPONSES:
        settings["store"] = False
        settings["truncation"] = "auto"
    elif wire_api == WIRE_CHAT_COMPLETIONS:
        settings["include_usage"] = True
    return settings


def _sdk_run_config_for_profile(_profile: dict[str, Any]) -> dict[str, Any]:
    return {
        "trace_include_sensitive_data": False,
        "workflow_name": "roboclaws-openai-agents-live",
    }
