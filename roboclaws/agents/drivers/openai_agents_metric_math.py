"""Small derived values shared by OpenAI Agents metric projections."""

from typing import Any


def estimated_tokens_from_chars(char_count: int) -> int:
    if char_count <= 0:
        return 0
    return max(1, round(char_count / 4))


def continuation_attempt_count(timing: dict[str, Any]) -> int:
    attempts = timing.get("openai_agents_attempts")
    if not isinstance(attempts, list):
        return 0
    return sum(
        1
        for attempt in attempts
        if isinstance(attempt, dict) and int(attempt.get("attempt_index") or 0) > 0
    )
