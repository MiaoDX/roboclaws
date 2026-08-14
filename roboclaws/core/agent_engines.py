"""Canonical public agent-engine identifiers."""

from __future__ import annotations

ACTIVE_AGENT_ENGINE_IDS: tuple[str, ...] = ("direct-runner", "openai-agents-sdk")


def unsupported_agent_engine_message(agent_engine: str) -> str:
    """Return the canonical error for any unsupported agent engine."""

    expected = "|".join(ACTIVE_AGENT_ENGINE_IDS)
    return f"unsupported agent_engine '{agent_engine}'; expected {expected}"
