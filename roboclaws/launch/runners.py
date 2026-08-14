"""Runner command builders for launch plans."""

from __future__ import annotations

import os
import sys
from collections.abc import Mapping, Sequence
from typing import NoReturn

from roboclaws.core.environment_setup_metadata import (
    ENVIRONMENT_SETUP_METADATA_ENV,
    environment_setup_metadata_json,
)
from roboclaws.launch.agent_engines import AGENT_ENGINE_SPECS
from roboclaws.launch.plans import LaunchPlan

_ADAPTER_ENV_OVERRIDES = (
    ("goal_contract_path", "ROBOCLAWS_GOAL_CONTRACT_PATH"),
    ("operator_session_context_json", "ROBOCLAWS_OPERATOR_SESSION_CONTEXT_JSON"),
)
PRIVATE_DEPENDENCY_TRACE_REDACTION_KEYS = frozenset(
    {
        "agibot_map_artifact_dir",
        "b1_alignment_artifact",
        "b1_navigation_artifact",
        "isaac_scene_usd_path",
        "runner_python",
        "runner_script",
    }
)
OPTIONAL_WORLD_TRACE_REDACTION_KEYS = PRIVATE_DEPENDENCY_TRACE_REDACTION_KEYS | {"map_bundle"}


def _exec_or_trace(
    cmd: Sequence[str],
    *,
    env: dict[str, str] | None = None,
    trace_args: Sequence[str] | None = None,
) -> int:
    if os.environ.get("ROBOCLAWS_JUST_TRACE") == "1":
        prefix = "cmd" if cmd and cmd[0] != "just" else "just"
        keys = (
            OPTIONAL_WORLD_TRACE_REDACTION_KEYS
            if os.environ.get("ROBOCLAWS_LAUNCH_WORLD_ID") in {"agibot-g2/map-12", "b1-map12"}
            else PRIVATE_DEPENDENCY_TRACE_REDACTION_KEYS
        )
        trace_cmd = trace_args if trace_args is not None else cmd
        payload = _redact_trace_args(trace_cmd if prefix == "cmd" else trace_cmd[1:], keys=keys)
        print("\t".join([prefix, *payload]))
        return 0
    if env:
        os.environ.update(env)
    os.execvp(cmd[0], list(cmd))
    return 1


def _redact_trace_args(
    args: Sequence[str],
    *,
    keys: frozenset[str] = PRIVATE_DEPENDENCY_TRACE_REDACTION_KEYS,
) -> list[str]:
    redacted: list[str] = []
    redact_next = False
    for arg in args:
        if redact_next:
            redacted.append("<configured>")
            redact_next = False
            continue
        normalized = arg.removeprefix("--")
        if normalized in keys:
            redacted.append(arg)
            redact_next = True
            continue
        key, separator, _value = normalized.partition("=")
        if separator and key in keys:
            prefix = "--" if arg.startswith("--") else ""
            redacted.append(f"{prefix}{key}=<configured>")
            continue
        redacted.append(arg)
    return redacted


def _append_optional(cmd: list[str], kv: dict[str, str], key: str, flag: str) -> None:
    value = _get(kv, key, "")
    if value:
        cmd.extend([flag, value])


def _get(kv: dict[str, str], key: str, default: str) -> str:
    value = kv.get(key)
    return value if value else default


def _die(message: str) -> NoReturn:
    print(f"error: {message}", file=sys.stderr)
    raise SystemExit(1)


def export_env_from_plan(plan: LaunchPlan) -> dict[str, str]:
    """Return environment variables implied by a resolved launch plan."""

    env = {
        "ROBOCLAWS_GOAL_CONTRACT_JSON": plan.goal_contract.to_json(),
        "ROBOCLAWS_TASK_SURFACE": plan.surface,
        "ROBOCLAWS_TASK_INTENT": plan.intent,
        "ROBOCLAWS_TASK_SKILL": plan.skill_name,
        "ROBOCLAWS_REQUIRED_CAPABILITY_PROFILES": ",".join(plan.required_capabilities),
    }
    if plan.preset:
        env["ROBOCLAWS_TASK_PRESET"] = plan.preset
    _export_adapter_env(env, plan.adapter_options)
    _export_provider_profile_env(env, plan)
    _export_environment_setup_metadata_env(env, plan)
    return env


def _export_adapter_env(env: dict[str, str], options: Mapping[str, str]) -> None:
    for override_key, env_key in _ADAPTER_ENV_OVERRIDES:
        value = options.get(override_key)
        if value is not None:
            env[env_key] = value


def _export_provider_profile_env(env: dict[str, str], plan: LaunchPlan) -> None:
    if not plan.provider_profile:
        return
    spec = AGENT_ENGINE_SPECS.get(plan.agent_engine)
    if spec and spec.provider_env_key:
        env[spec.provider_env_key] = plan.provider_profile


def _export_environment_setup_metadata_env(
    env: dict[str, str],
    plan: LaunchPlan,
) -> None:
    if not plan.scenario_setup:
        return
    env[ENVIRONMENT_SETUP_METADATA_ENV] = environment_setup_metadata_json(
        setup=plan.scenario_setup,
        seed=plan.adapter_options.get("seed"),
        relocation_count=(
            str(plan.relocation_count) if plan.relocation_count is not None else None
        ),
    )
