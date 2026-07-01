"""Focused helpers for operator-console launch validation and cleanup."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path
from typing import Any, Callable

from roboclaws.agents.provider_registry import normalize_provider_route, provider_route_spec
from roboclaws.launch.environment_setup import (
    ENVIRONMENT_SETUP_BASELINE,
    ENVIRONMENT_SETUP_OPTIONS,
    RELOCATION_SETUP_OPTIONS,
)
from roboclaws.operator_console.routes import DEFAULT_PROMPTS, ConsoleLaunchSelection

ALLOWED_ENV_OVERRIDES = {"ROBOCLAWS_PROVIDER_PROFILE"}
ALLOWED_ROUTE_OVERRIDES = {
    "seed",
    "seeds",
    "scenario_setup",
    "provider_profile",
    "relocation_count",
    "context_json",
    "visual_grounding_timeout",
    "visual_grounding_timeout_s",
    "scene_source",
    "scene_index",
    "isaac_scene_usd_path",
    "map_bundle",
    "b1_alignment_artifact",
    "b1_navigation_artifact",
    "robot_views",
    "record_robot_views",
    "real_movement_enabled",
    "run_dir",
    "policy",
    "host",
    "port",
    "operator_messages_path",
    "operator_resume_requests_path",
    "operator_session_context_json",
    "runtime_map_prior",
}
RunCommand = Callable[..., Any]


class DockerMountSourceError(RuntimeError):
    """Raised when Docker mount metadata exists but is not readable evidence."""


def build_surface_launch_args(
    route: ConsoleLaunchSelection,
    *,
    selected_intent: str = "",
    prompt: str = "",
    overrides: dict[str, str] | None = None,
    output_dir: Path | None = None,
    require_route_overrides: bool = True,
    error_type: type[ValueError] = ValueError,
) -> list[str]:
    selected_intent = str(selected_intent or route.intent_id)
    selected_prompt = launch_prompt_for_intent(route, selected_intent, prompt)
    selected_preset = route.preset_id if selected_intent == route.intent_id else ""
    request_overrides = normalized_launch_overrides(
        route,
        overrides or {},
        selected_intent=selected_intent,
        error_type=error_type,
    )
    validate_route_overrides(route, request_overrides, error_type=error_type)
    overridden_keys = set(request_overrides)
    if request_overrides.get("scenario_setup") == ENVIRONMENT_SETUP_BASELINE:
        overridden_keys.add("relocation_count")
    default_overrides = [
        item for item in route.launch_default_overrides if override_key(item) not in overridden_keys
    ]
    args = _base_launch_args(
        route,
        selected_intent=selected_intent,
        selected_preset=selected_preset,
        scenario_setup=request_overrides.pop("scenario_setup", route.scenario_setup),
        default_overrides=default_overrides,
    )
    provider_profile = request_overrides.pop("provider_profile", route.provider_profile or "")
    if provider_profile:
        args.append(f"provider_profile={provider_profile}")
    if output_dir is not None:
        args.append(f"output_dir={output_dir}")
    _append_request_overrides(
        args,
        route,
        request_overrides,
        require_route_overrides=require_route_overrides,
        error_type=error_type,
    )
    if selected_prompt:
        if not route.supports_prompt:
            raise error_type(
                "This route cannot accept a custom prompt safely. Use the default task prompt."
            )
        args.append(f"prompt={selected_prompt}")
    return args


def _append_request_overrides(
    args: list[str],
    route: ConsoleLaunchSelection,
    request_overrides: dict[str, str],
    *,
    require_route_overrides: bool,
    error_type: type[ValueError],
) -> None:
    if require_route_overrides:
        for key in route.required_overrides:
            value = request_overrides.get(key)
            if not value:
                raise error_type(f"missing required route parameter: {key}")
            args.append(f"{key}={value}")
    for key in sorted(request_overrides):
        if key not in route.required_overrides:
            args.append(f"{key}={request_overrides[key]}")


def launch_prompt_for_intent(
    route: ConsoleLaunchSelection,
    selected_intent: str,
    prompt: str,
) -> str:
    text = str(prompt or "").strip()
    if text or selected_intent != "open-ended":
        return text
    return DEFAULT_PROMPTS.get(selected_intent, route.task_prompt_default)


def launch_overrides_from_run_state(state: dict[str, Any]) -> dict[str, str]:
    return {
        key: value
        for key, value in {
            "provider_profile": str(state.get("provider_profile") or "").strip(),
            "host": str(state.get("mcp_host") or "").strip(),
            "port": str(state.get("mcp_port") or "").strip(),
        }.items()
        if value
    }


def normalized_launch_overrides(
    route: ConsoleLaunchSelection,
    overrides: dict[str, str],
    *,
    selected_intent: str,
    error_type: type[ValueError] = ValueError,
) -> dict[str, str]:
    normalized = {str(key): str(value) for key, value in overrides.items()}
    if "generated_mess_count" in normalized:
        raise error_type(
            "generated_mess_count is no longer a public route parameter; "
            "use scenario_setup and relocation_count"
        )
    default_map = {
        override_key(item): item.split("=", 1)[1]
        for item in route.launch_default_overrides
        if "=" in item
    }
    setup = str(
        normalized.get("scenario_setup")
        or (
            default_map.get("scenario_setup")
            if selected_intent == route.intent_id
            else ENVIRONMENT_SETUP_BASELINE
        )
        or route.scenario_setup
    )
    if setup not in ENVIRONMENT_SETUP_OPTIONS:
        allowed_values = "|".join(ENVIRONMENT_SETUP_OPTIONS)
        raise error_type(f"unsupported scenario_setup: {setup}; expected {allowed_values}")
    normalized["scenario_setup"] = setup
    if setup in RELOCATION_SETUP_OPTIONS:
        relocation_count = str(
            normalized.get("relocation_count") or default_map.get("relocation_count") or "5"
        )
        _parse_nonnegative_int(relocation_count, "relocation_count", error_type=error_type)
        normalized["relocation_count"] = relocation_count
    else:
        normalized.pop("relocation_count", None)
    return normalized


def validate_route_overrides(
    route: ConsoleLaunchSelection,
    overrides: dict[str, str],
    *,
    error_type: type[ValueError] = ValueError,
) -> None:
    for key, value in overrides.items():
        if key not in ALLOWED_ROUTE_OVERRIDES:
            raise error_type(f"unsupported route parameter: {key}")
        if "\x00" in value:
            raise error_type(f"invalid NUL byte in route parameter: {key}")
        if key == "port":
            _parse_port(value, error_type=error_type)
        if key == "scenario_setup" and value not in ENVIRONMENT_SETUP_OPTIONS:
            allowed_values = "|".join(ENVIRONMENT_SETUP_OPTIONS)
            raise error_type(f"unsupported scenario_setup: {value}; expected {allowed_values}")
        if key == "relocation_count":
            _parse_nonnegative_int(value, key, error_type=error_type)
    for key in route.required_overrides:
        if key not in ALLOWED_ROUTE_OVERRIDES:
            raise error_type(f"route registry uses unsupported parameter: {key}")


def override_key(value: str) -> str:
    return value.split("=", 1)[0]


def validate_env_overrides(
    route: ConsoleLaunchSelection,
    env_overrides: dict[str, str],
    *,
    error_type: type[ValueError] = ValueError,
) -> None:
    if env_overrides and route.agent_engine_id != "openai-agents-sdk":
        raise error_type("provider overrides are only supported for OpenAI Agents SDK routes")
    for key, value in env_overrides.items():
        _validate_env_override(route, key, value, error_type=error_type)


def provider_env_overrides_for_route(
    route: ConsoleLaunchSelection,
    overrides: dict[str, str],
    env_overrides: dict[str, str],
    *,
    error_type: type[ValueError] = ValueError,
) -> dict[str, str]:
    merged = dict(env_overrides)
    selected_provider = _selected_provider_profile(route, overrides, error_type=error_type)
    if not selected_provider:
        return merged
    env_provider = str(merged.get("ROBOCLAWS_PROVIDER_PROFILE") or "").strip()
    if env_provider and _normalize_provider_profile(env_provider, error_type) != selected_provider:
        raise error_type(
            "conflicting provider profile selection: "
            f"provider_profile={selected_provider} but "
            f"ROBOCLAWS_PROVIDER_PROFILE={_normalize_provider_profile(env_provider, error_type)}"
        )
    merged["ROBOCLAWS_PROVIDER_PROFILE"] = selected_provider
    return merged


def apply_env_overrides(
    route: ConsoleLaunchSelection,
    env_map: dict[str, str],
    env_overrides: dict[str, str],
    *,
    error_type: type[ValueError] = ValueError,
) -> dict[str, str]:
    clean = {str(key): str(value) for key, value in env_overrides.items() if str(value) != ""}
    validate_env_overrides(route, clean, error_type=error_type)
    merged = dict(env_map)
    if not clean:
        return merged
    merged.update(clean)
    return merged


def public_env_overrides(env_overrides: dict[str, str]) -> dict[str, str]:
    return {
        str(key): str(value)
        for key, value in env_overrides.items()
        if key in ALLOWED_ENV_OVERRIDES and str(value) != ""
    }


def _validate_env_override(
    route: ConsoleLaunchSelection,
    key: str,
    value: str,
    *,
    error_type: type[ValueError],
) -> None:
    if key not in ALLOWED_ENV_OVERRIDES:
        raise error_type(f"unsupported provider override: {key}")
    if "\x00" in value or "\n" in value or "\r" in value:
        raise error_type(f"invalid control character in provider override: {key}")
    if key == "ROBOCLAWS_PROVIDER_PROFILE":
        _validate_provider_override(
            route,
            value,
            {"openai-agents-sdk"},
            provider_label="provider profile",
            error_type=error_type,
        )


def _validate_provider_override(
    route: ConsoleLaunchSelection,
    value: str,
    allowed_engines: set[str],
    *,
    provider_label: str,
    error_type: type[ValueError],
) -> None:
    if route.agent_engine_id not in allowed_engines:
        raise error_type(f"{provider_label} override is not supported for this route")
    try:
        route_spec = provider_route_spec(value)
    except KeyError:
        route_spec = None
    if route_spec is None or route.agent_engine_id not in route_spec.supported_engines:
        expected = ", ".join(route.to_payload()["supported_provider_profiles"])
        raise error_type(f"unsupported {provider_label} override: {value}; expected {expected}")


def _selected_provider_profile(
    route: ConsoleLaunchSelection,
    overrides: dict[str, str],
    *,
    error_type: type[ValueError],
) -> str:
    provider_profile = str(overrides.get("provider_profile") or route.provider_profile or "")
    if not provider_profile:
        return ""
    return _normalize_provider_profile(provider_profile, error_type)


def _normalize_provider_profile(
    provider_profile: str,
    error_type: type[ValueError],
) -> str:
    try:
        return normalize_provider_route(provider_profile)
    except KeyError as exc:
        raise error_type(f"unsupported provider profile override: {provider_profile}") from exc


def _base_launch_args(
    route: ConsoleLaunchSelection,
    *,
    selected_intent: str,
    selected_preset: str,
    scenario_setup: str,
    default_overrides: list[str],
) -> list[str]:
    args = [
        f"surface={route.surface}",
        f"world={route.world_id}",
        f"backend={route.backend_id}",
        f"agent_engine={route.agent_engine_id}",
        f"evidence_lane={route.evidence_lane}",
        f"scenario_setup={scenario_setup}",
        *default_overrides,
    ]
    if selected_preset:
        args.insert(3, f"preset={selected_preset}")
    elif selected_intent != "open-ended":
        args.insert(3, f"intent={selected_intent}")
    return args


def _parse_port(value: str, *, error_type: type[ValueError]) -> int:
    try:
        port = int(str(value).strip())
    except ValueError as exc:
        raise error_type(f"invalid MCP port: {value}") from exc
    if not 1 <= port <= 65535:
        raise error_type(f"invalid MCP port: {value}")
    return port


def _parse_nonnegative_int(
    raw: str,
    key: str,
    *,
    error_type: type[ValueError],
) -> int:
    try:
        value = int(str(raw).strip())
    except ValueError as exc:
        raise error_type(f"{key} must be an integer") from exc
    if value < 0:
        raise error_type(f"{key} must be >= 0")
    return value


def docker_container_ids_with_mount(
    source: Path,
    *,
    run_command: RunCommand = subprocess.run,
) -> list[str]:
    result = _docker_ps(run_command)
    if result is None:
        return []
    container_ids: list[str] = []
    for container_id in result.stdout.split():
        if _docker_container_mounts_source(container_id, source, run_command=run_command):
            container_ids.append(container_id)
    return container_ids


def docker_container_mount_sources(
    container_id: str,
    *,
    run_command: RunCommand = subprocess.run,
) -> list[Path]:
    sources: list[Path] = []
    for mount in _docker_container_mounts(container_id, run_command=run_command):
        mount_source = mount.get("Source")
        if not mount_source:
            continue
        try:
            sources.append(Path(str(mount_source)).resolve())
        except OSError:
            continue
    return sources


def _docker_ps(run_command: RunCommand) -> Any | None:
    try:
        result = run_command(
            ["docker", "ps", "-q"],
            check=False,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            text=True,
        )
    except (FileNotFoundError, OSError):
        return None
    return result if result.returncode == 0 else None


def _docker_container_mounts_source(
    container_id: str,
    source: Path,
    *,
    run_command: RunCommand,
) -> bool:
    return any(
        mount_source == source
        for mount_source in docker_container_mount_sources(container_id, run_command=run_command)
    )


def _docker_container_mounts(container_id: str, *, run_command: RunCommand) -> list[Any]:
    try:
        inspect = run_command(
            ["docker", "inspect", "--format", "{{json .Mounts}}", container_id],
            check=False,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            text=True,
        )
    except (FileNotFoundError, OSError):
        return []
    if inspect.returncode != 0:
        return []
    try:
        mounts = json.loads(inspect.stdout)
    except json.JSONDecodeError as exc:
        raise DockerMountSourceError(
            f"docker inspect mounts for {container_id} contain invalid JSON: {exc.msg}"
        ) from exc
    if not isinstance(mounts, list):
        raise DockerMountSourceError(
            f"docker inspect mounts for {container_id} must be a JSON array"
        )
    invalid_mount = next((mount for mount in mounts if not isinstance(mount, dict)), None)
    if invalid_mount is not None:
        raise DockerMountSourceError(
            "docker inspect mounts for "
            f"{container_id} must contain JSON objects; got {type(invalid_mount).__name__}"
        )
    return mounts
