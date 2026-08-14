"""Typed CLI/environment setting resolution for Agent SDK profiles."""

from __future__ import annotations

import argparse
import math
import os
from typing import Any


def _bool_setting_value(raw: object) -> bool:
    if isinstance(raw, bool):
        return raw
    if (value := str(raw).strip().lower()) in {
        "1",
        "true",
        "yes",
        "on",
        "0",
        "false",
        "no",
        "off",
    }:
        return value in {"1", "true", "yes", "on"}
    raise ValueError(f"OpenAI Agents SDK boolean setting must be true or false, got {raw!r}")


def _string_setting(
    args: argparse.Namespace,
    attr: str,
    env_name: str,
    *,
    default: str,
    allowed: set[str],
) -> str:
    arg_raw = getattr(args, attr, "")
    env_raw = os.environ.get(env_name, "")
    value = str(arg_raw or env_raw or default).strip()
    if arg_raw and env_raw and str(arg_raw).strip() != str(env_raw).strip():
        _raise_setting_conflict(attr, env_name, str(arg_raw).strip(), str(env_raw).strip())
    if value not in allowed:
        raise ValueError(f"unsupported OpenAI Agents SDK {attr.replace('_', '-')} '{value}'")
    return value


def _int_setting(
    args: argparse.Namespace,
    attr: str,
    env_name: str,
    *,
    default: int | None,
    allow_none: bool = False,
) -> int | None:
    raw = getattr(args, attr, None)
    env_raw = os.environ.get(env_name)
    if raw is not None and env_raw not in {None, ""}:
        value = _number_setting_value(attr, raw, int, "an integer")
        env_value = _number_setting_value(attr, env_raw, int, "an integer")
        if value != env_value:
            _raise_setting_conflict(attr, env_name, value, env_value)
        raw = value
    if raw is None:
        raw = env_raw if env_raw not in {None, ""} else default
    if raw is None:
        if allow_none:
            return None
        raise ValueError(f"{attr} is required")
    value = _number_setting_value(attr, raw, int, "an integer")
    if value < 0:
        raise ValueError(f"OpenAI Agents SDK setting {attr} must be non-negative, got {raw!r}")
    return value


def _positive_int_setting(
    args: argparse.Namespace,
    attr: str,
    env_name: str,
    *,
    default: int,
) -> int:
    raw = getattr(args, attr, None)
    env_raw = os.environ.get(env_name)
    if raw is not None and env_raw not in {None, ""}:
        value = _number_setting_value(attr, raw, int, "an integer")
        env_value = _number_setting_value(attr, env_raw, int, "an integer")
        if value != env_value:
            _raise_setting_conflict(attr, env_name, value, env_value)
        raw = value
    if raw is None:
        raw = env_raw if env_raw not in {None, ""} else default
    value = _number_setting_value(attr, raw, int, "an integer")
    if value < 1:
        raise ValueError(f"OpenAI Agents SDK setting {attr} must be positive, got {raw!r}")
    return value


def _float_setting(
    args: argparse.Namespace,
    attr: str,
    env_name: str,
    *,
    default: float,
) -> float:
    raw = getattr(args, attr, None)
    env_raw = os.environ.get(env_name)
    if raw is not None and env_raw not in {None, ""}:
        value = _number_setting_value(attr, raw, float, "a non-negative number")
        env_value = _number_setting_value(attr, env_raw, float, "a non-negative number")
        if value != env_value:
            _raise_setting_conflict(attr, env_name, value, env_value)
        raw = value
    if raw is None:
        raw = env_raw if env_raw not in {None, ""} else default
    value = _number_setting_value(attr, raw, float, "a non-negative number")
    if not math.isfinite(value) or value < 0:
        raise ValueError(f"{attr} must be a finite non-negative number")
    return round(max(0.0, value), 3)


def _number_setting_value(attr: str, raw: object, parser: Any, expected: str) -> Any:
    if isinstance(raw, bool):
        raise ValueError(f"OpenAI Agents SDK setting {attr} must be {expected}, got {raw!r}")
    try:
        return parser(raw)
    except (TypeError, ValueError) as exc:
        raise ValueError(
            f"OpenAI Agents SDK setting {attr} must be {expected}, got {raw!r}"
        ) from exc


def _bool_arg_setting(
    args: argparse.Namespace,
    attr: str,
    env_name: str,
    *,
    default: bool,
) -> bool:
    raw = getattr(args, attr, None)
    env_raw = os.environ.get(env_name)
    if raw is not None and env_raw not in {None, ""}:
        value = _bool_setting_value(raw)
        env_value = _bool_setting_value(env_raw)
        if value != env_value:
            _raise_setting_conflict(attr, env_name, value, env_value)
        raw = value
    raw = env_raw if raw is None and env_raw not in {None, ""} else raw
    if raw is None:
        return default
    return _bool_setting_value(raw)


def _raise_setting_conflict(attr: str, env_name: str, arg_value: object, env_value: object) -> None:
    cli_name = f"--{attr.replace('_', '-')}"
    raise ValueError(
        f"conflicting OpenAI Agents SDK setting {attr}: "
        f"{cli_name}={arg_value!r} and {env_name}={env_value!r}"
    )


def _raise_enabled_count_error(attr: str, enabled_attr: str) -> None:
    raise ValueError(
        f"OpenAI Agents SDK setting {attr} must be positive when {enabled_attr} is enabled"
    )


def _validate_context_limits(profile: dict[str, Any]) -> None:
    soft = profile.get("context_soft_limit_tokens")
    hard = profile.get("context_hard_limit_tokens")
    if soft is not None and hard is not None and int(soft) > int(hard):
        raise ValueError("context_soft_limit_tokens must be <= context_hard_limit_tokens")
