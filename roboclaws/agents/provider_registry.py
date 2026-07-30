from __future__ import annotations

import argparse
import json
import os
from collections.abc import Callable
from dataclasses import asdict
from pathlib import Path
from typing import Any

import roboclaws.core.provider_catalog as provider_catalog
from roboclaws.launch.retired_agent_engines import (
    is_retired_agent_engine,
    retired_agent_engine_message,
)


def provider_env_key(agent_engine: str) -> str | None:
    if agent_engine == "openai-agents-sdk":
        return "ROBOCLAWS_PROVIDER_PROFILE"
    return None


def route_base_url(
    route: provider_catalog.ProviderRouteSpec,
    env: dict[str, str] | None = None,
) -> str:
    env_map = os.environ if env is None else env
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
    selected = str(
        provider_profile or provider_catalog.default_provider_profile(agent_engine) or ""
    )
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
        route = provider_catalog.resolve_provider_route_for_engine(agent_engine, provider_profile)
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
    has_opaque_model = bool(route.request_model_env)
    selected_model = route.default_model_id if has_opaque_model else model or route.default_model_id
    request_model = _explicit_string(env_map.get(route.request_model_env or ""))
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
        model_spec = provider_catalog.resolve_route_model(
            route.public_profile,
            request_model if has_opaque_model else selected_model,
        )
    except KeyError:
        model_spec = None
        message = (
            f"unknown model {selected_model!r} for provider_profile "
            f"{route.public_profile}; add it to the provider registry or use a catalog model."
        )
    except ValueError as exc:
        model_spec = None
        if not missing_env:
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
        "route_capabilities": provider_catalog.route_capabilities_for_engine(route, agent_engine),
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
        default="",
        normalizer=_normal_provider_profile,
    )
    if not provider:
        supported = ", ".join(provider_catalog.supported_provider_profiles("openai-agents-sdk"))
        raise ValueError(
            f"OpenAI Agents SDK setting provider_profile is required; expected one of {supported}"
        )
    try:
        route = provider_catalog.resolve_provider_route_for_engine("openai-agents-sdk", provider)
    except (KeyError, ValueError) as exc:
        raise ValueError(
            f"OpenAI Agents SDK setting provider_profile is unsupported, got {provider!r}"
        ) from exc
    if route.request_model_env:
        explicit_model = _conflict_checked_value(
            "model",
            [("model", model), ("LiveAgentRequest.model", request_model)],
            default="",
            normalizer=lambda value: value,
        )
        if explicit_model and explicit_model != route.default_model_id:
            raise ValueError(
                f"OpenAI Agents SDK {route.public_profile} model is configured only through "
                f"{route.request_model_env}"
            )
        provider_request_model = _explicit_string(env_map.get(route.request_model_env))
        selected_model = route.default_model_id
    else:
        selected_model = _conflict_checked_value(
            "model",
            [
                ("model", model),
                ("LiveAgentRequest.model", request_model),
                (
                    "ROBOCLAWS_OPENAI_AGENTS_MODEL",
                    env_map.get("ROBOCLAWS_OPENAI_AGENTS_MODEL"),
                ),
            ],
            default=route.default_model_id,
            normalizer=_normal_model_id,
        )
        try:
            selected_model = provider_catalog.resolve_route_model(
                route.public_profile, selected_model
            ).model_id
        except ValueError as exc:
            raise ValueError(f"OpenAI Agents SDK setting model is incompatible: {exc}") from exc
        provider_request_model = selected_model
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
        "request_model": provider_request_model,
        "request_model_env": route.request_model_env or "",
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
        return provider_catalog.normalize_provider_route(value)
    except KeyError as exc:
        raise ValueError(
            f"OpenAI Agents SDK setting provider_profile is unsupported, got {value!r}"
        ) from exc


def _normal_model_id(value: str) -> str:
    model = provider_catalog.maybe_resolve_model(value)
    if model is None:
        raise ValueError(f"OpenAI Agents SDK setting model is unknown, got {value!r}")
    return model.model_id


def _explicit_string(value: Any) -> str:
    if value is None:
        return ""
    return str(value).strip()


def _driver_for_agent_engine(agent_engine: str) -> str:
    return {
        "openai-agents-sdk": "openai-agents-sdk",
    }.get(agent_engine, agent_engine)


def _engine_label(agent_engine: str) -> str:
    return {
        "openai-agents-sdk": "OpenAI Agents SDK",
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
            for spec in provider_catalog.model_specs()
        ],
        "provider_routes": [asdict(spec) for spec in provider_catalog.provider_route_specs()],
    }


def _write_registry_json(output: Path | None) -> None:
    text = json.dumps(_registry_json_payload(), indent=2, sort_keys=True)
    if output:
        output.write_text(text + "\n", encoding="utf-8")
    else:
        print(text)


def _provider_route_command_text(command: str, route: provider_catalog.ProviderRouteSpec) -> str:
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
    route: provider_catalog.ProviderRouteSpec,
) -> None:
    try:
        print(_provider_route_command_text(command, route))
    except ValueError as exc:
        parser.error(str(exc))


def _model_command_text(model_name: str) -> str:
    return provider_catalog.resolve_model(model_name).model_id


def _supports_engine_exit_code(
    route: provider_catalog.ProviderRouteSpec,
    agent_engine: str,
) -> int:
    return 0 if agent_engine in route.supported_engines else 1


def _provider_route_for_cli(
    parser: argparse.ArgumentParser, route_id: str
) -> provider_catalog.ProviderRouteSpec:
    try:
        return provider_catalog.provider_route_spec(route_id)
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
        model = provider_catalog.resolve_route_model(args.route_id, args.agent_engine)
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
    route: provider_catalog.ProviderRouteSpec,
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
