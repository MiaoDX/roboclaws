"""Provider-specific HTTP transport compatibility."""

from __future__ import annotations

import math
import uuid
from pathlib import Path
from typing import Any

from roboclaws.core.provider_catalog import (
    PROVIDER_PROFILE_CODEX_RESPONSES,
    maybe_resolve_model,
)

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


def bounded_output_tokens(
    *,
    model: str,
    token_budget: float,
    cost_budget_usd: float,
    max_model_calls: int,
) -> int:
    """Return a per-call output cap inside one reserved provider budget."""

    if not math.isfinite(token_budget) or token_budget <= 0:
        raise ValueError("provider token budget must be a positive finite number")
    if not math.isfinite(cost_budget_usd) or cost_budget_usd <= 0:
        raise ValueError("provider cost budget must be a positive finite number")
    if max_model_calls < 1:
        raise ValueError("provider max_model_calls must be positive")
    limit = math.floor(token_budget / max_model_calls)
    spec = maybe_resolve_model(model)
    output_rate = spec.cost_per_m.get("output") if spec is not None else None
    if output_rate is None or output_rate <= 0:
        raise ValueError(f"model {model!r} requires catalog output pricing for a cost budget")
    limit = min(
        limit,
        math.floor(cost_budget_usd * 1_000_000 / output_rate / max_model_calls),
    )
    if limit < 1:
        raise ValueError("reserved provider budget cannot fund one output token per model call")
    return limit


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
