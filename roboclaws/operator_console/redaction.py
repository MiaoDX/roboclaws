"""Secret redaction for operator-console raw evidence endpoints."""

from __future__ import annotations

import os
import re
from collections.abc import Iterable, Mapping

SECRET_ENV_KEYS = (
    "CODEX_RESPONSES_API_KEY",
    "CODEX_RESPONSES_BASE_URL",
    "CODEX_RESPONSES_MODEL",
    "MIMO_RESPONSES_API_KEY",
    "MIMO_RESPONSES_BASE_URL",
    "MIMO_RESPONSES_MODEL",
    "OPENAI_API_KEY",
    "ANTHROPIC_API_KEY",
    "KIMI_API_KEY",
    "KIMI_OPENAI_BASE_URL",
    "MM_API_KEY",
    "MM_BASE_URL",
)

SECRET_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(r"(?i)(authorization:\s*bearer\s+)[^\s'\"<>]+"),
    re.compile(r"(?i)(api[_-]?key['\"]?\s*[:=]\s*['\"]?)[^\s'\",}]+"),
    re.compile(r"(?i)(token['\"]?\s*[:=]\s*['\"]?)[^\s'\",}]+"),
    re.compile(r"\b(?:sk-[A-Za-z0-9_-]{12,})\b"),
)


def redact_text(text: str, *, env: Mapping[str, str] | None = None) -> str:
    """Return text with known local secrets and provider headers removed."""

    env_map = os.environ if env is None else env
    redacted = text
    for value in _secret_values(env_map):
        redacted = redacted.replace(value, "[REDACTED]")
    for pattern in SECRET_PATTERNS[:3]:
        redacted = pattern.sub(r"\1[REDACTED]", redacted)
    redacted = SECRET_PATTERNS[3].sub("[REDACTED]", redacted)
    return redacted


def _secret_values(env: Mapping[str, str]) -> Iterable[str]:
    for key in SECRET_ENV_KEYS:
        value = env.get(key)
        if value and len(value) >= 6:
            yield value
