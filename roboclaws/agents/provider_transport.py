"""Provider output budget calculation."""

from __future__ import annotations

import math

from roboclaws.core.provider_catalog import maybe_resolve_model


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
