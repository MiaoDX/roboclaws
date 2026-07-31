"""Provider-facing runtime settings projected from Agent SDK profiles."""

from __future__ import annotations

from typing import Any

from roboclaws.agents.drivers.openai_agents_run_config import KIMI_CODING_USER_AGENT
from roboclaws.agents.provider_transport import compatible_model_settings
from roboclaws.core.provider_catalog import (
    PROVIDER_PROFILE_KIMI_OPENAI_CHAT,
    WIRE_CHAT_COMPLETIONS,
    WIRE_RESPONSES,
)


def _sdk_model_settings_for_profile(profile: dict[str, Any]) -> dict[str, Any]:
    wire_api = str(profile.get("wire_api") or "")
    provider_profile = str(profile.get("provider_profile") or "")
    settings: dict[str, Any] = {
        "tool_choice": "auto",
        "parallel_tool_calls": False,
        "model_thinking_mode": str(profile.get("model_thinking_mode") or "default"),
    }
    if wire_api == WIRE_RESPONSES:
        settings["store"] = False
        settings["truncation"] = "auto"
    elif wire_api == WIRE_CHAT_COMPLETIONS:
        settings["include_usage"] = True
        if provider_profile == PROVIDER_PROFILE_KIMI_OPENAI_CHAT:
            settings["extra_headers"] = {"User-Agent": KIMI_CODING_USER_AGENT}
    return compatible_model_settings(provider_profile, settings)


def _sdk_run_config_for_profile(_profile: dict[str, Any]) -> dict[str, Any]:
    return {
        "trace_include_sensitive_data": False,
        "workflow_name": "roboclaws-openai-agents-live",
    }
