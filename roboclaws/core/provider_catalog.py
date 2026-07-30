from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

MODEL_CAP_TEXT = "text"
MODEL_CAP_IMAGE_INPUT = "image_input"

PROVIDER_PROFILE_CODEX_RESPONSES = "codex-responses"
PROVIDER_PROFILE_MIMO_RESPONSES = "mimo-responses"
PROVIDER_PROFILE_MINIMAX_RESPONSES = "minimax-responses"
PROVIDER_PROFILE_KIMI_OPENAI_CHAT = "kimi-openai-chat"

ROUTE_CAP_SUPPORTED = "supported"
ROUTE_CAP_UNSUPPORTED = "unsupported"
ROUTE_CAP_UNKNOWN = "unknown"

WIRE_RESPONSES = "responses"
WIRE_CHAT_COMPLETIONS = "chat-completions"
WIRE_SOURCE_NATIVE = "native"
WIRE_SOURCE_UNKNOWN = "unknown"

ROUTE_HEALTHY = "healthy"
ROUTE_EXPERIMENTAL = "experimental"


@dataclass(frozen=True)
class ModelSpec:
    model_id: str
    aliases: tuple[str, ...]
    family: str
    model_capabilities: frozenset[str]
    default_use: bool = False
    default_use_note: str = ""
    cost_per_m: dict[str, float] = field(default_factory=dict)

    @property
    def supports_image_input(self) -> bool:
        return MODEL_CAP_IMAGE_INPUT in self.model_capabilities


@dataclass(frozen=True)
class ProviderRouteSpec:
    route_id: str
    public_profile: str
    label: str
    supported_engines: tuple[str, ...]
    default_model_id: str
    required_env_keys: tuple[str, ...]
    api_key_env: str | None
    base_url_env: str | None
    base_url_default: str
    wire_api: str
    wire_source: str
    request_model_env: str | None = None
    default_use: bool = False
    default_use_note: str = ""
    aliases: tuple[str, ...] = ()
    compatible_model_ids: tuple[str, ...] = ()
    per_engine_status: dict[str, str] = field(default_factory=dict)
    route_capabilities: dict[str, str] = field(default_factory=dict)
    per_engine_route_capability_overrides: dict[str, dict[str, str]] = field(default_factory=dict)
    status_note: str = ""

    def status_for_engine(self, agent_engine: str) -> str:
        return self.per_engine_status.get(agent_engine, ROUTE_EXPERIMENTAL)

    def route_capability(self, capability: str, *, agent_engine: str) -> str:
        overrides = self.per_engine_route_capability_overrides.get(agent_engine, {})
        return overrides.get(capability, self.route_capabilities.get(capability, ROUTE_CAP_UNKNOWN))


def _caps(*values: str) -> frozenset[str]:
    return frozenset(values)


def _opaque_responses_route(profile: str, label: str, env: str) -> ProviderRouteSpec:
    required_env = tuple(f"{env}_{suffix}" for suffix in ("BASE_URL", "API_KEY", "MODEL"))
    return ProviderRouteSpec(
        route_id=profile,
        public_profile=profile,
        label=f"{label} Responses",
        supported_engines=("openai-agents-sdk",),
        default_model_id=label.lower(),
        required_env_keys=required_env,
        api_key_env=f"{env}_API_KEY",
        base_url_env=f"{env}_BASE_URL",
        base_url_default="",
        wire_api=WIRE_RESPONSES,
        wire_source=WIRE_SOURCE_NATIVE,
        request_model_env=f"{env}_MODEL",
        default_use=True,
        default_use_note=f"Environment-configured {label} Responses endpoint.",
        per_engine_status={"openai-agents-sdk": ROUTE_EXPERIMENTAL},
        route_capabilities={
            "image_transport": ROUTE_CAP_UNKNOWN,
            "tool_call_transport": ROUTE_CAP_SUPPORTED,
        },
        status_note="Tool calling requires route-specific live proof.",
    )


_MODEL_SPECS: tuple[ModelSpec, ...] = (
    ModelSpec("mock", ("mock",), "mock", _caps(MODEL_CAP_TEXT, MODEL_CAP_IMAGE_INPUT)),
    ModelSpec(
        "gpt-4o",
        ("gpt-4o",),
        "gpt",
        _caps(MODEL_CAP_TEXT, MODEL_CAP_IMAGE_INPUT),
        cost_per_m={"input": 5.00, "output": 15.00},
    ),
    ModelSpec(
        "gpt-4o-mini",
        ("gpt-4o-mini",),
        "gpt",
        _caps(MODEL_CAP_TEXT, MODEL_CAP_IMAGE_INPUT),
        cost_per_m={"input": 0.15, "output": 0.60},
    ),
    ModelSpec(
        "kimi-k2-5",
        ("kimi-k2-5", "k2p5"),
        "kimi",
        _caps(MODEL_CAP_TEXT, MODEL_CAP_IMAGE_INPUT),
        cost_per_m={"input": 1.00, "output": 3.00},
    ),
    ModelSpec(
        "kimi-k2.7-code",
        ("kimi", "kimi-k2.7-code", "k2.7-code", "kimi-code"),
        "kimi",
        _caps(MODEL_CAP_TEXT, MODEL_CAP_IMAGE_INPUT),
        default_use=True,
        default_use_note=(
            "Default Kimi coding model. Kimi K2.7 Code is a thinking-only route. "
            "The provider accepts arbitrary K2.7 suffixes and echoes them, so the "
            "catalog keeps the canonical model id only."
        ),
        cost_per_m={"input": 1.00, "output": 3.00},
    ),
    ModelSpec(
        "kimi-for-coding",
        ("kimi-coding", "kimi-for-coding"),
        "kimi",
        _caps(MODEL_CAP_TEXT, MODEL_CAP_IMAGE_INPUT),
        cost_per_m={"input": 1.00, "output": 3.00},
    ),
    ModelSpec(
        "claude-3-5-sonnet-20241022",
        ("anthropic", "claude-3-5-sonnet-20241022"),
        "anthropic",
        _caps(MODEL_CAP_TEXT, MODEL_CAP_IMAGE_INPUT),
        cost_per_m={"input": 3.00, "output": 15.00},
    ),
    ModelSpec(
        "claude-3-haiku-20240307",
        ("claude-3-haiku-20240307",),
        "anthropic",
        _caps(MODEL_CAP_TEXT, MODEL_CAP_IMAGE_INPUT),
        cost_per_m={"input": 0.25, "output": 1.25},
    ),
    ModelSpec(
        "MiniMax-M3",
        ("minimax", "minimax-m3", "MiniMax-M3"),
        "minimax",
        _caps(MODEL_CAP_TEXT, MODEL_CAP_IMAGE_INPUT),
        default_use=True,
        default_use_note="Default MiniMax model for current cleanup evidence.",
    ),
)

_PROVIDER_ROUTE_SPECS: tuple[ProviderRouteSpec, ...] = (
    _opaque_responses_route(PROVIDER_PROFILE_CODEX_RESPONSES, "Codex", "CODEX_RESPONSES"),
    _opaque_responses_route(PROVIDER_PROFILE_MIMO_RESPONSES, "MiMo", "MIMO_RESPONSES"),
    ProviderRouteSpec(
        route_id=PROVIDER_PROFILE_MINIMAX_RESPONSES,
        public_profile=PROVIDER_PROFILE_MINIMAX_RESPONSES,
        label="MiniMax M3",
        supported_engines=("openai-agents-sdk",),
        default_model_id="MiniMax-M3",
        required_env_keys=("MM_BASE_URL", "MM_API_KEY"),
        api_key_env="MM_API_KEY",
        base_url_env="MM_BASE_URL",
        base_url_default="",
        wire_api=WIRE_RESPONSES,
        wire_source=WIRE_SOURCE_NATIVE,
        default_use=True,
        default_use_note="Default-enabled MiniMax route; uses MiniMax-M3.",
        compatible_model_ids=("MiniMax-M3",),
        per_engine_status={"openai-agents-sdk": ROUTE_HEALTHY},
        route_capabilities={
            "image_transport": ROUTE_CAP_UNKNOWN,
            "tool_call_transport": ROUTE_CAP_SUPPORTED,
        },
        status_note="OpenAI Agents SDK structured cleanup works.",
    ),
    ProviderRouteSpec(
        route_id=PROVIDER_PROFILE_KIMI_OPENAI_CHAT,
        public_profile=PROVIDER_PROFILE_KIMI_OPENAI_CHAT,
        label="Kimi K2.7",
        supported_engines=("openai-agents-sdk",),
        default_model_id="kimi-k2.7-code",
        required_env_keys=("KIMI_OPENAI_BASE_URL", "KIMI_API_KEY"),
        api_key_env="KIMI_API_KEY",
        base_url_env="KIMI_OPENAI_BASE_URL",
        base_url_default="",
        wire_api=WIRE_CHAT_COMPLETIONS,
        wire_source=WIRE_SOURCE_NATIVE,
        default_use=True,
        default_use_note=(
            "Default-enabled Kimi coding route. K2.7 Code is thinking-only; keep "
            "the canonical kimi-k2.7-code id because the provider accepts and "
            "echoes arbitrary suffixes."
        ),
        compatible_model_ids=("kimi-k2.7-code",),
        per_engine_status={"openai-agents-sdk": ROUTE_EXPERIMENTAL},
        route_capabilities={
            "image_transport": ROUTE_CAP_UNSUPPORTED,
            "tool_call_transport": ROUTE_CAP_SUPPORTED,
        },
    ),
)


def _normalize_model_name(model_name: str) -> str:
    normalized = str(model_name or "").strip()
    if normalized.startswith("anthropic_kimi/"):
        normalized = normalized.split("/", 1)[1]
    return normalized


_MODEL_BY_ID = {spec.model_id: spec for spec in _MODEL_SPECS}
_MODEL_BY_ALIAS = {
    _normalize_model_name(alias): spec for spec in _MODEL_SPECS for alias in spec.aliases
}
_ROUTE_BY_ALIAS = {
    alias: spec for spec in _PROVIDER_ROUTE_SPECS for alias in (spec.route_id, *spec.aliases)
}


def model_specs() -> tuple[ModelSpec, ...]:
    return _MODEL_SPECS


def provider_route_specs() -> tuple[ProviderRouteSpec, ...]:
    return _PROVIDER_ROUTE_SPECS


def default_enabled_models() -> tuple[ModelSpec, ...]:
    return tuple(spec for spec in _MODEL_SPECS if spec.default_use)


def default_enabled_provider_routes() -> tuple[ProviderRouteSpec, ...]:
    return tuple(spec for spec in _PROVIDER_ROUTE_SPECS if spec.default_use)


def model_aliases() -> dict[str, str]:
    return {alias: spec.model_id for spec in _MODEL_SPECS for alias in spec.aliases}


def resolve_model(model_name: str) -> ModelSpec:
    normalized = _normalize_model_name(model_name)
    spec = _MODEL_BY_ALIAS.get(normalized) or _MODEL_BY_ID.get(normalized)
    if spec is None:
        raise KeyError(model_name)
    return spec


def maybe_resolve_model(model_name: str | None) -> ModelSpec | None:
    if not model_name:
        return None
    try:
        return resolve_model(model_name)
    except KeyError:
        return None


def cost_table_by_model() -> dict[str, dict[str, float]]:
    return {spec.model_id: dict(spec.cost_per_m) for spec in _MODEL_SPECS if spec.cost_per_m}


def provider_route_spec(route_id: str) -> ProviderRouteSpec:
    spec = _ROUTE_BY_ALIAS.get(route_id)
    if spec is None:
        raise KeyError(route_id)
    return spec


def normalize_provider_route(route_id: str | None, *, default: str = "") -> str:
    raw = str(route_id or default).strip()
    if not raw:
        return ""
    return provider_route_spec(raw).public_profile


def provider_routes_for_engine(agent_engine: str) -> tuple[ProviderRouteSpec, ...]:
    return tuple(spec for spec in _PROVIDER_ROUTE_SPECS if agent_engine in spec.supported_engines)


def supported_provider_profiles(agent_engine: str) -> tuple[str, ...]:
    return tuple(spec.public_profile for spec in provider_routes_for_engine(agent_engine))


def default_provider_profile(agent_engine: str) -> str | None:
    return None


def resolve_provider_route_for_engine(
    agent_engine: str, provider_profile: str | None
) -> ProviderRouteSpec:
    selected = normalize_provider_route(
        provider_profile, default=default_provider_profile(agent_engine) or ""
    )
    spec = provider_route_spec(selected)
    if agent_engine not in spec.supported_engines:
        raise ValueError(
            f"provider_profile '{selected}' is unsupported for agent_engine '{agent_engine}'"
        )
    return spec


def model_family_for_route_model(provider_profile: str, model_id: str | None = None) -> str:
    route = provider_route_spec(provider_profile)
    selected_model = model_id or route.default_model_id
    try:
        return resolve_route_model(route.public_profile, selected_model).family
    except KeyError as exc:
        raise ValueError(
            f"unknown model {selected_model!r} for provider_profile "
            f"{route.public_profile}; add it to the provider registry or use a catalog model."
        ) from exc


def resolve_route_model(route_id: str, model_id: str | None) -> ModelSpec:
    route = provider_route_spec(route_id)
    if route.request_model_env:
        selected = str(model_id or "").strip()
        if not selected:
            raise ValueError(f"{route.public_profile} requires {route.request_model_env}")
        return _opaque_model_spec(route)
    selected = resolve_model(model_id or route.default_model_id)
    compatible_ids = route.compatible_model_ids or (route.default_model_id,)
    compatible_models = tuple(resolve_model(item) for item in compatible_ids)
    compatible_model_ids = tuple(model.model_id for model in compatible_models)
    if selected.model_id not in compatible_model_ids:
        raise ValueError(
            f"model {selected.model_id!r} is incompatible with provider_profile "
            f"{route.public_profile!r}; expected one of {', '.join(compatible_model_ids)}"
        )
    return selected


def route_capabilities_for_engine(route: ProviderRouteSpec, agent_engine: str) -> dict[str, str]:
    keys = set(route.route_capabilities)
    keys.update(route.per_engine_route_capability_overrides.get(agent_engine, {}).keys())
    return {key: route.route_capability(key, agent_engine=agent_engine) for key in sorted(keys)}


def route_payload(route: ProviderRouteSpec, *, agent_engine: str) -> dict[str, Any]:
    model = (
        _opaque_model_spec(route)
        if route.request_model_env
        else resolve_model(route.default_model_id)
    )
    return {
        "provider_profile": route.public_profile,
        "route_id": route.route_id,
        "label": route.label,
        "default_model_id": route.default_model_id,
        "model_family": model.family,
        "model_capabilities": sorted(model.model_capabilities),
        "model_default_use": model.default_use,
        "model_default_use_note": model.default_use_note,
        "compatible_models": list(route.compatible_model_ids or (route.default_model_id,)),
        "required_env": list(route.required_env_keys),
        "wire_api": route.wire_api,
        "wire_source": route.wire_source,
        "default_use": route.default_use,
        "default_use_note": route.default_use_note,
        "route_status": route.status_for_engine(agent_engine),
        "route_status_note": route.status_note,
        "route_capabilities": route_capabilities_for_engine(route, agent_engine),
    }


def _opaque_model_spec(route: ProviderRouteSpec) -> ModelSpec:
    assert route.request_model_env
    return ModelSpec(
        model_id=route.default_model_id,
        aliases=(),
        family=route.default_model_id,
        model_capabilities=_caps(MODEL_CAP_TEXT),
        default_use=True,
        default_use_note=f"Opaque model configured by {route.request_model_env}.",
    )
