from __future__ import annotations

from typing import Any

from roboclaws.agents.provider_registry import model_aliases, resolve_model
from roboclaws.core.provider_runtime import VLMProvider
from roboclaws.core.providers.anthropic import AnthropicProvider
from roboclaws.core.providers.kimi import KimiCodingProvider, KimiProvider
from roboclaws.core.providers.mock import MockProvider
from roboclaws.core.providers.openai import OpenAIProvider

_PROVIDER_CLASSES: dict[str, type[Any]] = {
    "mock": MockProvider,
    "openai": OpenAIProvider,
    "kimi": KimiProvider,
    "kimi-coding": KimiCodingProvider,
    "anthropic": AnthropicProvider,
}


def create_provider(model: str = "mock", **kwargs: Any) -> VLMProvider:
    """Map a ``--model`` CLI flag to a provider instance."""
    try:
        metadata = resolve_model(model)
    except KeyError:
        raise ValueError(f"Unknown model: {model!r}. Choose from {list(model_aliases())}") from None
    adapter = metadata.direct_provider_adapter
    if adapter is None:
        raise ValueError(f"Model {metadata.model_id!r} has no direct provider adapter")
    provider_class = _PROVIDER_CLASSES[adapter]
    return provider_class(
        **({} if metadata.model_id == "mock" else {"model": metadata.model_id}),
        **kwargs,
    )
