"""Provider-specific HTTP transport compatibility."""

from __future__ import annotations

import uuid
from pathlib import Path
from typing import Any

from roboclaws.core.provider_catalog import PROVIDER_PROFILE_CODEX_RESPONSES

CODEX_WINDOW_ID_HEADER = "X-Codex-Window-Id"


def compatible_model_settings(
    provider_profile: str,
    settings: dict[str, Any],
) -> dict[str, Any]:
    """Return SDK model settings supported by the selected provider."""

    compatible = dict(settings)
    if provider_profile == PROVIDER_PROFILE_CODEX_RESPONSES:
        compatible.pop("truncation", None)
    return compatible


def provider_client_options(provider_profile: str, session_seed: Path) -> dict[str, Any]:
    """Return OpenAI client options required by the selected provider."""

    headers = provider_default_headers(provider_profile, session_seed=session_seed)
    return {"default_headers": headers} if headers else {}


def provider_default_headers(
    provider_profile: str,
    *,
    session_seed: Path | None = None,
) -> dict[str, str]:
    """Return unpersisted HTTP headers required by the selected provider."""

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
