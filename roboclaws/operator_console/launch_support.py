"""Focused helpers for operator-console launch validation and cleanup."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path
from typing import Any, Callable

from roboclaws.agents.provider_registry import normalize_provider_route, provider_route_spec
from roboclaws.operator_console.routes import ConsoleLaunchSelection

ALLOWED_ENV_OVERRIDES = {"ROBOCLAWS_PROVIDER_PROFILE"}
RunCommand = Callable[..., Any]


class DockerMountSourceError(RuntimeError):
    """Raised when Docker mount metadata exists but is not readable evidence."""


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
