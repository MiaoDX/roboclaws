"""Agent-engine and provider-profile metadata."""

from __future__ import annotations

from dataclasses import dataclass

from roboclaws.agents.provider_registry import (
    provider_env_key,
)
from roboclaws.core.provider_catalog import default_provider_profile, supported_provider_profiles


@dataclass(frozen=True)
class AgentEngineSpec:
    """Operator-facing agent engine with derived private runner metadata."""

    id: str
    label: str
    dispatch_runner: str
    internal_runner_class: str
    supported_provider_profiles: tuple[str, ...]
    default_provider_profile: str | None
    provider_env_key: str | None = None
    availability: str = "enabled"
    experimental: bool = False


AGENT_ENGINE_SPECS: dict[str, AgentEngineSpec] = {
    "openai-agents-sdk": AgentEngineSpec(
        id="openai-agents-sdk",
        label="OpenAI Agents SDK",
        dispatch_runner="openai-agents-live",
        internal_runner_class="live-agent",
        supported_provider_profiles=supported_provider_profiles("openai-agents-sdk"),
        default_provider_profile=default_provider_profile("openai-agents-sdk"),
        provider_env_key=provider_env_key("openai-agents-sdk"),
        availability="experimental",
        experimental=True,
    ),
    "direct-runner": AgentEngineSpec(
        id="direct-runner",
        label="Direct Runner",
        dispatch_runner="direct",
        internal_runner_class="deterministic",
        supported_provider_profiles=(),
        default_provider_profile=None,
    ),
}


def agent_engine_spec(agent_engine_id: str) -> AgentEngineSpec:
    """Return an agent engine spec by id."""

    return AGENT_ENGINE_SPECS[agent_engine_id]
