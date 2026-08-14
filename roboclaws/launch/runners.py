"""Runner command builders for launch plans."""

from __future__ import annotations

from roboclaws.launch.agent_engines import AGENT_ENGINE_SPECS
from roboclaws.launch.environment_setup_metadata import (
    ENVIRONMENT_SETUP_METADATA_ENV,
    environment_setup_metadata_json,
)

_TASK_ENV_OVERRIDES = (
    ("goal_contract_json", "ROBOCLAWS_GOAL_CONTRACT_JSON"),
    ("goal_contract_path", "ROBOCLAWS_GOAL_CONTRACT_PATH"),
    ("operator_session_context_json", "ROBOCLAWS_OPERATOR_SESSION_CONTEXT_JSON"),
    ("task_surface", "ROBOCLAWS_TASK_SURFACE"),
    ("task_intent", "ROBOCLAWS_TASK_INTENT"),
    ("task_preset", "ROBOCLAWS_TASK_PRESET"),
    ("skill_name", "ROBOCLAWS_TASK_SKILL"),
)


def export_env_from_overrides(overrides: tuple[str, ...]) -> dict[str, str]:
    """Return environment variables implied by launch-only overrides."""

    env = _task_env_from_overrides(overrides)
    _export_provider_profile_env(env, overrides)
    _export_environment_setup_metadata_env(env, overrides)
    return env


def _task_env_from_overrides(overrides: tuple[str, ...]) -> dict[str, str]:
    env: dict[str, str] = {}
    for override_key, env_key in _TASK_ENV_OVERRIDES:
        value = _override_value(overrides, override_key)
        if value is not None:
            env[env_key] = value
    return env


def _export_provider_profile_env(env: dict[str, str], overrides: tuple[str, ...]) -> None:
    provider_profile = _override_value(overrides, "provider_profile")
    if not provider_profile:
        return
    agent_engine = _override_value(overrides, "agent_engine")
    spec = AGENT_ENGINE_SPECS.get(agent_engine or "")
    if spec and spec.provider_env_key:
        env[spec.provider_env_key] = provider_profile


def _export_environment_setup_metadata_env(
    env: dict[str, str],
    overrides: tuple[str, ...],
) -> None:
    setup = _override_value(overrides, "scenario_setup")
    if not setup:
        return
    env[ENVIRONMENT_SETUP_METADATA_ENV] = environment_setup_metadata_json(
        setup=setup,
        seed=_override_value(overrides, "seed"),
        relocation_count=_override_value(overrides, "relocation_count"),
    )


def _override_value(overrides: tuple[str, ...], key: str) -> str | None:
    prefix = f"{key}="
    for override in overrides:
        if override.startswith(prefix):
            return override.removeprefix(prefix)
    return None
