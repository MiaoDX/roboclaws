"""Active and retired public agent-engine identifiers."""

from __future__ import annotations

ACTIVE_AGENT_ENGINE_IDS: tuple[str, ...] = ("direct-runner", "openai-agents-sdk")
RETIRED_AGENT_ENGINE_IDS: tuple[str, ...] = ("codex-cli", "claude-code")


def retired_agent_engine_message(agent_engine: str) -> str:
    """Return the shared fail-loud message for retired live-agent engines."""

    expected = "|".join(ACTIVE_AGENT_ENGINE_IDS)
    return f"unsupported agent_engine '{agent_engine}'; expected {expected}"


def is_retired_agent_engine(agent_engine: str) -> bool:
    """Return whether an engine id is retired from active product support."""

    return agent_engine in RETIRED_AGENT_ENGINE_IDS
