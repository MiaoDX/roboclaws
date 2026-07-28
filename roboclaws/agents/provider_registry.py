from __future__ import annotations

import argparse
import json
import os
from collections.abc import Callable
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from roboclaws.launch.retired_agent_engines import (
    is_retired_agent_engine,
    retired_agent_engine_message,
)

MODEL_CAP_TEXT = "text"
MODEL_CAP_IMAGE_INPUT = "image_input"

PROVIDER_PROFILE_CODEX_RESPONSES = "codex-router-responses"
PROVIDER_PROFILE_MIMO_MIFY_RESPONSES = "mimo-mify-responses"
PROVIDER_PROFILE_MINIMAX_RESPONSES = "minimax-responses"
PROVIDER_PROFILE_MIMO_OPENAI_CHAT = "mimo-tp-openai-chat"
PROVIDER_PROFILE_MIMO_INSIDE_OPENAI_CHAT = "mimo-inside-openai-chat"
PROVIDER_PROFILE_KIMI_OPENAI_CHAT = "kimi-openai-chat"
PROVIDER_PROFILE_MIMO_ANTHROPIC = "mimo-tp-anthropic"
PROVIDER_PROFILE_MIMO_MIFY_ANTHROPIC = "mimo-mify-anthropic"

ROUTE_CAP_SUPPORTED = "supported"
ROUTE_CAP_UNSUPPORTED = "unsupported"
ROUTE_CAP_UNKNOWN = "unknown"

WIRE_RESPONSES = "responses"
WIRE_CHAT_COMPLETIONS = "chat-completions"
WIRE_ANTHROPIC = "anthropic"

WIRE_SOURCE_NATIVE = "native"
WIRE_SOURCE_GATEWAY = "gateway"
WIRE_SOURCE_SHIM = "shim"
WIRE_SOURCE_UNKNOWN = "unknown"

ROUTE_HEALTHY = "healthy"
ROUTE_EXPERIMENTAL = "experimental"
ROUTE_PROVISIONAL = "provisional"
ROUTE_DEGRADED = "degraded"
ROUTE_BLOCKED = "blocked"


@dataclass(frozen=True)
class ModelSpec:
    model_id: str
    aliases: tuple[str, ...]
    family: str
    model_capabilities: frozenset[str]
    default_use: bool = False
    default_use_note: str = ""
    direct_provider_adapter: str | None = None
    direct_required_env_keys: tuple[str, ...] = ()
    cost_per_m: dict[str, float] = field(default_factory=dict)
    openclaw_model_id: str | None = None

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
        return overrides.get(
            capability,
            self.route_capabilities.get(capability, ROUTE_CAP_UNKNOWN),
        )


def _caps(*values: str) -> frozenset[str]:
    return frozenset(values)


_MODEL_SPECS: tuple[ModelSpec, ...] = (
    ModelSpec(
        model_id="mock",
        aliases=("mock",),
        family="mock",
        model_capabilities=_caps(MODEL_CAP_TEXT, MODEL_CAP_IMAGE_INPUT),
        direct_provider_adapter="mock",
    ),
    ModelSpec(
        model_id="gpt-5.5",
        aliases=("gpt-5.5",),
        family="gpt",
        model_capabilities=_caps(MODEL_CAP_TEXT, MODEL_CAP_IMAGE_INPUT),
        default_use_note="Previous Codex router model; retained for explicit compatibility checks.",
    ),
    ModelSpec(
        model_id="gpt-5.6-sol",
        aliases=("gpt-5.6-sol",),
        family="gpt",
        model_capabilities=_caps(MODEL_CAP_TEXT, MODEL_CAP_IMAGE_INPUT),
        default_use=True,
        default_use_note="Best current Codex router model and default Codex route model.",
    ),
    ModelSpec(
        model_id="gpt-4o",
        aliases=("gpt-4o",),
        family="gpt",
        model_capabilities=_caps(MODEL_CAP_TEXT, MODEL_CAP_IMAGE_INPUT),
        direct_provider_adapter="openai",
        direct_required_env_keys=("OPENAI_API_KEY",),
        cost_per_m={"input": 5.00, "output": 15.00},
    ),
    ModelSpec(
        model_id="gpt-4o-mini",
        aliases=("gpt-4o-mini",),
        family="gpt",
        model_capabilities=_caps(MODEL_CAP_TEXT, MODEL_CAP_IMAGE_INPUT),
        direct_provider_adapter="openai",
        direct_required_env_keys=("OPENAI_API_KEY",),
        cost_per_m={"input": 0.15, "output": 0.60},
    ),
    ModelSpec(
        model_id="kimi-k2-5",
        aliases=("kimi-k2-5", "k2p5"),
        family="kimi",
        model_capabilities=_caps(MODEL_CAP_TEXT, MODEL_CAP_IMAGE_INPUT),
        direct_provider_adapter="kimi",
        direct_required_env_keys=("KIMI_API_KEY",),
        cost_per_m={"input": 1.00, "output": 3.00},
        openclaw_model_id="anthropic_kimi/k2p5",
    ),
    ModelSpec(
        model_id="kimi-k2.7-code",
        aliases=("kimi", "kimi-k2.7-code", "k2.7-code", "kimi-code"),
        family="kimi",
        model_capabilities=_caps(MODEL_CAP_TEXT, MODEL_CAP_IMAGE_INPUT),
        default_use=True,
        default_use_note=(
            "Default Kimi coding model. Kimi K2.7 Code is a thinking-only route. "
            "The provider accepts arbitrary K2.7 suffixes and echoes them, so the "
            "catalog keeps the canonical model id only."
        ),
        direct_provider_adapter="kimi-coding",
        direct_required_env_keys=("KIMI_API_KEY",),
        cost_per_m={"input": 1.00, "output": 3.00},
    ),
    ModelSpec(
        model_id="kimi-for-coding",
        aliases=("kimi-coding", "kimi-for-coding"),
        family="kimi",
        model_capabilities=_caps(MODEL_CAP_TEXT, MODEL_CAP_IMAGE_INPUT),
        direct_provider_adapter="kimi-coding",
        direct_required_env_keys=("KIMI_API_KEY",),
        cost_per_m={"input": 1.00, "output": 3.00},
    ),
    ModelSpec(
        model_id="claude-3-5-sonnet-20241022",
        aliases=("anthropic", "claude-3-5-sonnet-20241022"),
        family="anthropic",
        model_capabilities=_caps(MODEL_CAP_TEXT, MODEL_CAP_IMAGE_INPUT),
        direct_provider_adapter="anthropic",
        direct_required_env_keys=("ANTHROPIC_API_KEY",),
        cost_per_m={"input": 3.00, "output": 15.00},
    ),
    ModelSpec(
        model_id="claude-3-haiku-20240307",
        aliases=("claude-3-haiku-20240307",),
        family="anthropic",
        model_capabilities=_caps(MODEL_CAP_TEXT, MODEL_CAP_IMAGE_INPUT),
        direct_provider_adapter="anthropic",
        direct_required_env_keys=("ANTHROPIC_API_KEY",),
        cost_per_m={"input": 0.25, "output": 1.25},
    ),
    ModelSpec(
        model_id="meta/llama-4-maverick-17b-128e-instruct",
        aliases=("nvidia", "meta/llama-4-maverick-17b-128e-instruct"),
        family="nvidia",
        model_capabilities=_caps(MODEL_CAP_TEXT, MODEL_CAP_IMAGE_INPUT),
        direct_provider_adapter="nvidia",
        direct_required_env_keys=("NVIDIA_API_KEY", "NV_API_KEY"),
        cost_per_m={"input": 0.0, "output": 0.0},
    ),
    ModelSpec(
        model_id="nvidia/llama-3.1-nemotron-nano-vl-8b-v1",
        aliases=("nvidia-nano-vl", "nvidia/llama-3.1-nemotron-nano-vl-8b-v1"),
        family="nvidia",
        model_capabilities=_caps(MODEL_CAP_TEXT, MODEL_CAP_IMAGE_INPUT),
        direct_provider_adapter="nvidia",
        direct_required_env_keys=("NVIDIA_API_KEY", "NV_API_KEY"),
        cost_per_m={"input": 0.0, "output": 0.0},
    ),
    ModelSpec(
        model_id="mimo-v2.5",
        aliases=("mimo", "mimo-v2.5"),
        family="mimo",
        model_capabilities=_caps(MODEL_CAP_TEXT, MODEL_CAP_IMAGE_INPUT),
        default_use=True,
        default_use_note="Default MiMo token-plan model.",
        direct_provider_adapter="mimo",
        direct_required_env_keys=("MIMO_TP_KEY",),
        cost_per_m={"input": 0.0, "output": 0.0},
        openclaw_model_id="mimo_openai/mimo-v2.5",
    ),
    ModelSpec(
        model_id="xiaomi/mimo-v2.5",
        aliases=("xiaomi/mimo-v2.5", "mimo-mify-v2.5"),
        family="mimo",
        model_capabilities=_caps(MODEL_CAP_TEXT, MODEL_CAP_IMAGE_INPUT),
        default_use=True,
        default_use_note="Default MiMo model through the mify gateway.",
    ),
    ModelSpec(
        model_id="mimo-1000",
        aliases=("mimo-1000", "mimo-inside-1000", "mimo-ultraspeed"),
        family="mimo",
        model_capabilities=_caps(MODEL_CAP_TEXT),
        default_use=True,
        default_use_note=(
            "Default-enabled MiMo inside UltraSpeed route for explicit on-demand "
            "benchmark and text-agent use; product cleanup promotion still requires "
            "a route decision."
        ),
    ),
    ModelSpec(
        model_id="MiniMax-M3",
        aliases=("minimax", "minimax-m3", "MiniMax-M3"),
        family="minimax",
        model_capabilities=_caps(MODEL_CAP_TEXT, MODEL_CAP_IMAGE_INPUT),
        default_use=True,
        default_use_note="Default MiniMax model for current cleanup evidence.",
    ),
)

_PROVIDER_ROUTE_SPECS: tuple[ProviderRouteSpec, ...] = (
    ProviderRouteSpec(
        route_id=PROVIDER_PROFILE_CODEX_RESPONSES,
        public_profile=PROVIDER_PROFILE_CODEX_RESPONSES,
        label="Codex GPT-5.6 Sol",
        supported_engines=("openai-agents-sdk",),
        default_model_id="gpt-5.6-sol",
        required_env_keys=("CODEX_BASE_URL", "CODEX_API_KEY"),
        api_key_env="CODEX_API_KEY",
        base_url_env="CODEX_BASE_URL",
        base_url_default="",
        wire_api=WIRE_RESPONSES,
        wire_source=WIRE_SOURCE_NATIVE,
        default_use=True,
        default_use_note="Default Codex router route; uses gpt-5.6-sol.",
        compatible_model_ids=("gpt-5.6-sol", "gpt-5.5"),
        per_engine_status={
            "openai-agents-sdk": ROUTE_EXPERIMENTAL,
        },
        route_capabilities={
            "image_transport": ROUTE_CAP_SUPPORTED,
            "tool_call_transport": ROUTE_CAP_SUPPORTED,
        },
    ),
    ProviderRouteSpec(
        route_id=PROVIDER_PROFILE_MIMO_MIFY_RESPONSES,
        public_profile=PROVIDER_PROFILE_MIMO_MIFY_RESPONSES,
        label="Mimo MIFY v2.5",
        supported_engines=("openai-agents-sdk",),
        default_model_id="xiaomi/mimo-v2.5",
        required_env_keys=("XM_LLM_API_KEY",),
        api_key_env="XM_LLM_API_KEY",
        base_url_env="XM_LLM_BASE_URL",
        base_url_default="https://api.llm.mioffice.cn/v1",
        wire_api=WIRE_RESPONSES,
        wire_source=WIRE_SOURCE_GATEWAY,
        default_use=True,
        default_use_note=(
            "Default-enabled MiMo mify route; uses xiaomi/mimo-v2.5 unless explicitly overridden."
        ),
        compatible_model_ids=("xiaomi/mimo-v2.5",),
        per_engine_status={
            "openai-agents-sdk": ROUTE_PROVISIONAL,
        },
        route_capabilities={
            "image_transport": ROUTE_CAP_UNKNOWN,
            "tool_call_transport": ROUTE_CAP_SUPPORTED,
        },
        status_note=("MiMo via mify is SDK-provisional until broader live route proof is healthy."),
    ),
    ProviderRouteSpec(
        route_id=PROVIDER_PROFILE_MINIMAX_RESPONSES,
        public_profile=PROVIDER_PROFILE_MINIMAX_RESPONSES,
        label="MiniMax M3",
        supported_engines=("openai-agents-sdk",),
        default_model_id="MiniMax-M3",
        required_env_keys=("MM_API_KEY",),
        api_key_env="MM_API_KEY",
        base_url_env="MM_BASE_URL",
        base_url_default="https://api.minimaxi.com/v1",
        wire_api=WIRE_RESPONSES,
        wire_source=WIRE_SOURCE_NATIVE,
        default_use=True,
        default_use_note="Default-enabled MiniMax route; uses MiniMax-M3.",
        compatible_model_ids=("MiniMax-M3",),
        per_engine_status={
            "openai-agents-sdk": ROUTE_HEALTHY,
        },
        route_capabilities={
            "image_transport": ROUTE_CAP_UNKNOWN,
            "tool_call_transport": ROUTE_CAP_SUPPORTED,
        },
        status_note=("OpenAI Agents SDK structured cleanup works."),
    ),
    ProviderRouteSpec(
        route_id=PROVIDER_PROFILE_MIMO_OPENAI_CHAT,
        public_profile=PROVIDER_PROFILE_MIMO_OPENAI_CHAT,
        label="Mimo TP v2.5",
        supported_engines=("openai-agents-sdk",),
        default_model_id="mimo-v2.5",
        required_env_keys=("MIMO_TP_KEY",),
        api_key_env="MIMO_TP_KEY",
        base_url_env="MIMO_OPENAI_BASE_URL",
        base_url_default="https://token-plan-cn.xiaomimimo.com/v1",
        wire_api=WIRE_CHAT_COMPLETIONS,
        wire_source=WIRE_SOURCE_NATIVE,
        default_use=True,
        default_use_note="Default-enabled MiMo token-plan chat route; uses mimo-v2.5.",
        compatible_model_ids=("mimo-v2.5",),
        per_engine_status={"openai-agents-sdk": ROUTE_HEALTHY},
        route_capabilities={
            "image_transport": ROUTE_CAP_UNSUPPORTED,
            "tool_call_transport": ROUTE_CAP_SUPPORTED,
        },
    ),
    ProviderRouteSpec(
        route_id=PROVIDER_PROFILE_MIMO_INSIDE_OPENAI_CHAT,
        public_profile=PROVIDER_PROFILE_MIMO_INSIDE_OPENAI_CHAT,
        label="Mimo Inside 1000",
        supported_engines=("openai-agents-sdk",),
        default_model_id="mimo-1000",
        required_env_keys=("MIMO_BASE_URL", "MIMO_API_KEY"),
        api_key_env="MIMO_API_KEY",
        base_url_env="MIMO_BASE_URL",
        base_url_default="",
        wire_api=WIRE_CHAT_COMPLETIONS,
        wire_source=WIRE_SOURCE_NATIVE,
        default_use=True,
        default_use_note=(
            "Default-enabled on-demand MiMo inside route for speed benchmarks and "
            "explicit text-agent experiments. Not a product cleanup default until "
            "a separate route decision promotes it."
        ),
        compatible_model_ids=("mimo-1000",),
        per_engine_status={"openai-agents-sdk": ROUTE_PROVISIONAL},
        route_capabilities={
            "image_transport": ROUTE_CAP_UNKNOWN,
            "tool_call_transport": ROUTE_CAP_SUPPORTED,
        },
    ),
    ProviderRouteSpec(
        route_id="kimi-openai-chat",
        public_profile=PROVIDER_PROFILE_KIMI_OPENAI_CHAT,
        label="Kimi K2.7",
        supported_engines=("openai-agents-sdk",),
        default_model_id="kimi-k2.7-code",
        required_env_keys=("KIMI_API_KEY",),
        api_key_env="KIMI_API_KEY",
        base_url_env="KIMI_OPENAI_BASE_URL",
        base_url_default="https://api.kimi.com/coding/v1",
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
    ProviderRouteSpec(
        route_id=PROVIDER_PROFILE_MIMO_ANTHROPIC,
        public_profile=PROVIDER_PROFILE_MIMO_ANTHROPIC,
        label="MiMo token plan Anthropic",
        supported_engines=(),
        default_model_id="mimo-v2.5",
        required_env_keys=("MIMO_TP_KEY",),
        api_key_env="MIMO_TP_KEY",
        base_url_env="MIMO_ANTHROPIC_BASE_URL",
        base_url_default="https://token-plan-cn.xiaomimimo.com/anthropic",
        wire_api=WIRE_ANTHROPIC,
        wire_source=WIRE_SOURCE_SHIM,
        compatible_model_ids=("mimo-v2.5",),
        route_capabilities={
            "image_transport": ROUTE_CAP_SUPPORTED,
            "tool_call_transport": ROUTE_CAP_SUPPORTED,
        },
        status_note="Retained for historical Claude Code route metadata; not an active engine.",
    ),
    ProviderRouteSpec(
        route_id=PROVIDER_PROFILE_MIMO_MIFY_ANTHROPIC,
        public_profile=PROVIDER_PROFILE_MIMO_MIFY_ANTHROPIC,
        label="MiMo mify Anthropic Gateway",
        supported_engines=(),
        default_model_id="xiaomi/mimo-v2.5",
        required_env_keys=("XM_LLM_API_KEY",),
        api_key_env="XM_LLM_API_KEY",
        base_url_env="XM_LLM_ANTHROPIC_BASE_URL",
        base_url_default="https://api.llm.mioffice.cn/anthropic",
        wire_api=WIRE_ANTHROPIC,
        wire_source=WIRE_SOURCE_GATEWAY,
        compatible_model_ids=("xiaomi/mimo-v2.5",),
        route_capabilities={
            "image_transport": ROUTE_CAP_SUPPORTED,
            "tool_call_transport": ROUTE_CAP_SUPPORTED,
        },
        status_note="Retained for historical Claude Code route metadata; not an active engine.",
    ),
)


def _normalize_model_name(model_name: str) -> str:
    normalized = str(model_name or "").strip()
    if normalized.startswith(("mimo_openai/", "mimo_anthropic/", "anthropic_kimi/")):
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


def required_env_keys(model_name: str) -> tuple[str, ...]:
    return resolve_model(model_name).direct_required_env_keys


def openclaw_model_id(model_name: str) -> str:
    spec = resolve_model(model_name)
    return spec.openclaw_model_id or spec.model_id


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
    defaults = {
        "openai-agents-sdk": PROVIDER_PROFILE_CODEX_RESPONSES,
        "openclaw-gateway": "kimi",
    }
    return defaults.get(agent_engine)


def provider_env_key(agent_engine: str) -> str | None:
    if agent_engine == "openai-agents-sdk":
        return "ROBOCLAWS_PROVIDER_PROFILE"
    return None


def resolve_provider_route_for_engine(
    agent_engine: str,
    provider_profile: str | None,
) -> ProviderRouteSpec:
    selected = normalize_provider_route(
        provider_profile,
        default=default_provider_profile(agent_engine) or "",
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


def route_base_url(route: ProviderRouteSpec, env: dict[str, str] | None = None) -> str:
    env_map = os.environ if env is None else env
    if route.route_id == PROVIDER_PROFILE_MIMO_MIFY_ANTHROPIC:
        return _mify_anthropic_base_url(env_map)
    if route.base_url_env and env_map.get(route.base_url_env):
        return str(env_map[route.base_url_env])
    return route.base_url_default


def provider_readiness(
    *,
    agent_engine: str,
    provider_profile: str | None,
    model: str | None = None,
    env: dict[str, str] | None = None,
) -> dict[str, Any]:
    env_map = os.environ if env is None else env
    selected = str(provider_profile or default_provider_profile(agent_engine) or "")
    if is_retired_agent_engine(agent_engine):
        return {
            "driver": _driver_for_agent_engine(agent_engine),
            "agent_engine": agent_engine,
            "provider": selected,
            "provider_profile": selected,
            "model": model or "",
            "required_env": [],
            "missing_env": [],
            "ok": False,
            "message": retired_agent_engine_message(agent_engine),
            "route_status": "retired",
        }
    try:
        route = resolve_provider_route_for_engine(agent_engine, provider_profile)
    except KeyError:
        message = (
            f"provider_profile {selected!r} is unknown for agent_engine {agent_engine!r}; "
            "add it to the provider registry or use a supported provider profile."
        )
        return {
            "driver": _driver_for_agent_engine(agent_engine),
            "agent_engine": agent_engine,
            "provider": selected,
            "provider_profile": selected,
            "model": model or "",
            "required_env": [],
            "missing_env": [],
            "ok": False,
            "message": message,
        }
    except ValueError as exc:
        return {
            "driver": _driver_for_agent_engine(agent_engine),
            "agent_engine": agent_engine,
            "provider": selected,
            "provider_profile": selected,
            "model": model or "",
            "required_env": [],
            "missing_env": [],
            "ok": False,
            "message": str(exc),
        }
    selected_model = model or route.default_model_id
    required_env = list(route.required_env_keys)
    missing_env = [key for key in required_env if not env_map.get(key)]
    if missing_env:
        required = " and ".join(required_env)
        message = (
            f"{_engine_label(agent_engine)} provider {route.public_profile} requires {required}."
        )
    else:
        message = ""
    try:
        model_spec = resolve_route_model(route.public_profile, selected_model)
    except KeyError:
        model_spec = None
        message = (
            f"unknown model {selected_model!r} for provider_profile "
            f"{route.public_profile}; add it to the provider registry or use a catalog model."
        )
    except ValueError as exc:
        model_spec = None
        message = str(exc)
    try:
        route_base_url(route, env=dict(env_map))
        base_url_ok = True
    except ValueError as exc:
        base_url_ok = False
        message = str(exc)
    return {
        "driver": _driver_for_agent_engine(agent_engine),
        "agent_engine": agent_engine,
        "provider": route.public_profile,
        "provider_profile": route.public_profile,
        "label": route.label,
        "model": selected_model,
        "model_family": model_spec.family if model_spec else "unknown",
        "model_capabilities": sorted(model_spec.model_capabilities) if model_spec else [],
        "model_default_use": bool(model_spec.default_use) if model_spec else False,
        "model_default_use_note": model_spec.default_use_note if model_spec else "",
        "compatible_models": list(route.compatible_model_ids or (route.default_model_id,)),
        "wire_api": route.wire_api,
        "wire_source": route.wire_source,
        "default_use": route.default_use,
        "default_use_note": route.default_use_note,
        "route_status": route.status_for_engine(agent_engine),
        "route_status_note": route.status_note,
        "route_capabilities": route_capabilities_for_engine(route, agent_engine),
        "required_env": required_env,
        "missing_env": missing_env,
        "base_url_env": route.base_url_env or "",
        "base_url_default": route.base_url_default,
        "ok": not missing_env and model_spec is not None and base_url_ok,
        "message": message,
    }


def openai_agents_runtime_settings(
    *,
    provider_profile: str | None,
    request_provider_profile: str | None,
    model: str | None,
    request_model: str | None,
    base_url: str | None,
    api_key: str | None,
    env: dict[str, str] | None = None,
) -> dict[str, str]:
    env_map = os.environ if env is None else env
    provider = _conflict_checked_value(
        "provider_profile",
        [
            ("provider_profile", provider_profile),
            ("LiveAgentRequest.provider_profile", request_provider_profile),
            (
                "ROBOCLAWS_OPENAI_AGENTS_PROVIDER",
                env_map.get("ROBOCLAWS_OPENAI_AGENTS_PROVIDER"),
            ),
            ("ROBOCLAWS_PROVIDER_PROFILE", env_map.get("ROBOCLAWS_PROVIDER_PROFILE")),
        ],
        default=PROVIDER_PROFILE_CODEX_RESPONSES,
        normalizer=_normal_provider_profile,
    )
    try:
        route = resolve_provider_route_for_engine("openai-agents-sdk", provider)
    except (KeyError, ValueError) as exc:
        raise ValueError(
            f"OpenAI Agents SDK setting provider_profile is unsupported, got {provider!r}"
        ) from exc
    selected_model = _conflict_checked_value(
        "model",
        [
            ("model", model),
            ("LiveAgentRequest.model", request_model),
            ("ROBOCLAWS_OPENAI_AGENTS_MODEL", env_map.get("ROBOCLAWS_OPENAI_AGENTS_MODEL")),
            ("ROBOCLAWS_CODEX_MODEL", env_map.get("ROBOCLAWS_CODEX_MODEL")),
        ],
        default=route.default_model_id,
        normalizer=_normal_model_id,
    )
    try:
        selected_model = resolve_route_model(route.public_profile, selected_model).model_id
    except ValueError as exc:
        raise ValueError(f"OpenAI Agents SDK setting model is incompatible: {exc}") from exc
    return {
        "provider_profile": route.public_profile,
        "wire_api": route.wire_api,
        "wire_source": route.wire_source,
        "route_status": route.status_for_engine("openai-agents-sdk"),
        "base_url_env": route.base_url_env or "",
        "base_url": _conflict_checked_pair(
            "base_url",
            "base_url",
            base_url,
            route.base_url_env or "",
            env_map.get(route.base_url_env or ""),
            default=route_base_url(route, env=dict(env_map)),
            normalizer=lambda item: item.rstrip("/"),
        ),
        "api_key_env": route.api_key_env or "",
        "api_key": _conflict_checked_pair(
            "api_key",
            "api_key",
            api_key,
            route.api_key_env or "",
            env_map.get(route.api_key_env or ""),
            default="",
            redact=True,
        ),
        "model": selected_model,
    }


def route_payload(route: ProviderRouteSpec, *, agent_engine: str) -> dict[str, Any]:
    model = resolve_model(route.default_model_id)
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


def _conflict_checked_value(
    setting_name: str,
    candidates: list[tuple[str, Any]],
    *,
    default: str,
    normalizer: Callable[[str], str],
) -> str:
    selected_source = ""
    selected_raw = ""
    selected_normalized = ""
    for source, raw_value in candidates:
        value = _explicit_string(raw_value)
        if not value:
            continue
        normalized = normalizer(value)
        if not selected_normalized:
            selected_source = source
            selected_raw = value
            selected_normalized = normalized
            continue
        if normalized != selected_normalized:
            raise ValueError(
                f"conflicting OpenAI Agents SDK setting {setting_name}: "
                f"{selected_source}={selected_raw!r} and {source}={value!r}"
            )
    return selected_normalized or default


def _conflict_checked_pair(
    setting_name: str,
    direct_source: str,
    direct_raw: Any,
    env_source: str,
    env_raw: Any,
    *,
    default: str,
    normalizer: Callable[[str], str] = lambda item: item,
    redact: bool = False,
) -> str:
    direct_value = _explicit_string(direct_raw)
    env_value = _explicit_string(env_raw) if env_source else ""
    if direct_value and env_value and normalizer(direct_value) != normalizer(env_value):
        detail = (
            f"{direct_source} and {env_source} are both set with different values"
            if redact
            else f"{direct_source}={direct_value!r} and {env_source}={env_value!r}"
        )
        raise ValueError(f"conflicting OpenAI Agents SDK setting {setting_name}: {detail}")
    return direct_value or env_value or default


def _normal_provider_profile(value: str) -> str:
    try:
        return normalize_provider_route(value, default=PROVIDER_PROFILE_CODEX_RESPONSES)
    except KeyError as exc:
        raise ValueError(
            f"OpenAI Agents SDK setting provider_profile is unsupported, got {value!r}"
        ) from exc


def _normal_model_id(value: str) -> str:
    model = maybe_resolve_model(value)
    if model is None:
        raise ValueError(f"OpenAI Agents SDK setting model is unknown, got {value!r}")
    return model.model_id


def _explicit_string(value: Any) -> str:
    if value is None:
        return ""
    return str(value).strip()


def _mify_anthropic_base_url(env_map: dict[str, str]) -> str:
    anthropic_base = _explicit_string(env_map.get("XM_LLM_ANTHROPIC_BASE_URL"))
    generic_base = _explicit_string(env_map.get("XM_LLM_BASE_URL"))
    derived_generic_base = _mify_anthropic_base_url_from_generic(generic_base)
    if anthropic_base and derived_generic_base:
        if anthropic_base.rstrip("/") != derived_generic_base.rstrip("/"):
            raise ValueError(
                "conflicting provider route base_url for mimo-mify-anthropic: "
                f"XM_LLM_ANTHROPIC_BASE_URL={anthropic_base!r} and "
                f"XM_LLM_BASE_URL derives {derived_generic_base!r}"
            )
        return anthropic_base
    if anthropic_base:
        return anthropic_base
    if derived_generic_base:
        return derived_generic_base
    return "https://api.llm.mioffice.cn/anthropic"


def _mify_anthropic_base_url_from_generic(base: str) -> str:
    if not base:
        return ""
    base = base.rstrip("/")
    if base.endswith("/anthropic"):
        return base
    if base.endswith("/v1"):
        return f"{base[:-3]}/anthropic"
    return f"{base}/anthropic"


def _driver_for_agent_engine(agent_engine: str) -> str:
    return {
        "openai-agents-sdk": "openai-agents-sdk",
        "openclaw-gateway": "openclaw",
    }.get(agent_engine, agent_engine)


def _engine_label(agent_engine: str) -> str:
    return {
        "openai-agents-sdk": "OpenAI Agents SDK",
        "openclaw-gateway": "OpenClaw",
    }.get(agent_engine, agent_engine)


def _build_registry_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Print Roboclaws provider registry facts.")
    parser.add_argument(
        "command",
        choices=[
            "base-url",
            "default-model",
            "json",
            "key-env",
            "model-id",
            "provider-model-id",
            "public-profile",
            "supports-engine",
            "wire-api",
        ],
    )
    parser.add_argument("route_id", nargs="?")
    parser.add_argument("agent_engine", nargs="?")
    parser.add_argument("--output", type=Path)
    return parser


def _registry_json_payload() -> dict[str, Any]:
    return {
        "models": [
            asdict(spec) | {"model_capabilities": sorted(spec.model_capabilities)}
            for spec in _MODEL_SPECS
        ],
        "provider_routes": [asdict(spec) for spec in _PROVIDER_ROUTE_SPECS],
    }


def _write_registry_json(output: Path | None) -> None:
    text = json.dumps(_registry_json_payload(), indent=2, sort_keys=True)
    if output:
        output.write_text(text + "\n", encoding="utf-8")
    else:
        print(text)


def _provider_route_command_text(command: str, route: ProviderRouteSpec) -> str:
    if command == "default-model":
        return route.default_model_id
    if command == "base-url":
        return route_base_url(route)
    if command == "key-env":
        return route.api_key_env or ""
    if command == "public-profile":
        return route.public_profile
    if command == "wire-api":
        return route.wire_api
    raise ValueError(f"unsupported provider route command: {command}")


def _print_provider_route_command(
    parser: argparse.ArgumentParser,
    command: str,
    route: ProviderRouteSpec,
) -> None:
    try:
        print(_provider_route_command_text(command, route))
    except ValueError as exc:
        parser.error(str(exc))


def _model_command_text(model_name: str) -> str:
    return resolve_model(model_name).model_id


def _supports_engine_exit_code(
    route: ProviderRouteSpec,
    agent_engine: str,
) -> int:
    return 0 if agent_engine in route.supported_engines else 1


def _provider_route_for_cli(parser: argparse.ArgumentParser, route_id: str) -> ProviderRouteSpec:
    try:
        return provider_route_spec(route_id)
    except KeyError:
        parser.error(f"provider_profile {route_id!r} is unknown; use a supported provider profile.")
    raise AssertionError("argparse parser.error should exit")


def _route_id_required_error(command: str) -> str:
    if command in {"model-id", "provider-model-id"}:
        return "model_id is required"
    return "route_id is required"


def _print_model_cli(parser: argparse.ArgumentParser, args: argparse.Namespace) -> int:
    if args.command == "model-id":
        try:
            print(_model_command_text(args.route_id))
        except KeyError as exc:
            parser.error(f"unknown model {exc.args[0]!r}; use a catalog model id or alias")
        return 0

    if not args.agent_engine:
        parser.error("model_id is required")
    try:
        model = resolve_route_model(args.route_id, args.agent_engine)
    except KeyError as exc:
        parser.error(
            f"unknown provider/model id {exc.args[0]!r}; use a provider route and catalog model"
        )
    except ValueError as exc:
        parser.error(str(exc))
    print(model.model_id)
    return 0


def _print_route_cli(
    parser: argparse.ArgumentParser,
    args: argparse.Namespace,
    route: ProviderRouteSpec,
) -> int:
    if args.command == "supports-engine":
        if not args.agent_engine:
            parser.error("agent_engine is required")
        return _supports_engine_exit_code(route, args.agent_engine)
    _print_provider_route_command(parser, args.command, route)
    return 0


def _main(argv: list[str] | None = None) -> int:
    parser = _build_registry_parser()
    args = parser.parse_args(argv)

    if args.command == "json":
        _write_registry_json(args.output)
        return 0

    if not args.route_id:
        parser.error(_route_id_required_error(args.command))
    if args.command in {"model-id", "provider-model-id"}:
        return _print_model_cli(parser, args)

    route = _provider_route_for_cli(parser, args.route_id)
    return _print_route_cli(parser, args, route)


if __name__ == "__main__":  # pragma: no cover - exercised through shell helpers.
    raise SystemExit(_main())
