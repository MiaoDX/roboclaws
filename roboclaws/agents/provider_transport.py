"""Private transport compatibility for provider routes."""

from __future__ import annotations

import uuid
from pathlib import Path

from roboclaws.agents.provider_registry import PROVIDER_PROFILE_CODEX_RESPONSES

CODEX_WINDOW_ID_HEADER = "X-Codex-Window-Id"


def provider_default_headers(
    provider_profile: str,
    *,
    session_seed: Path | None = None,
) -> dict[str, str]:
    """Return internal headers required by a provider transport."""

    if provider_profile != PROVIDER_PROFILE_CODEX_RESPONSES:
        return {}
    if session_seed is None:
        thread_id = uuid.uuid4()
    else:
        thread_id = uuid.uuid5(
            uuid.NAMESPACE_URL,
            f"roboclaws-codex-window:{session_seed.resolve().as_uri()}",
        )
    return {CODEX_WINDOW_ID_HEADER: f"{thread_id}:0"}
