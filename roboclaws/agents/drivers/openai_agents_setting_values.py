"""Validated scalar settings used by OpenAI Agents run configuration."""

from __future__ import annotations

import os
from typing import Any


def _bool_setting(value: Any, setting_name: str, *, default: bool) -> bool:
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    if value == "":
        return default
    true_values = {"1", "true", "yes", "on"}
    false_values = {"0", "false", "no", "off"}
    if (normalized := str(value).strip().lower()) in true_values | false_values:
        return normalized in true_values
    raise ValueError(
        f"OpenAI Agents SDK setting {setting_name} must be true or false, got {value!r}"
    )


def _positive_int(
    value: Any,
    *,
    default: int,
    setting_name: str,
    env_name: str | None = None,
) -> int:
    source_name = env_name or f"OpenAI Agents SDK setting {setting_name}"
    if value is None or value == "":
        return default
    if isinstance(value, bool):
        raise ValueError(f"{source_name} must be a positive integer, got {value!r}")
    try:
        parsed = int(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{source_name} must be a positive integer, got {value!r}") from exc
    if parsed < 1:
        raise ValueError(f"{source_name} must be a positive integer, got {value!r}")
    return parsed


def _nonnegative_int(value: Any, *, default: int, setting_name: str) -> int:
    if value is None or value == "":
        return default
    if isinstance(value, bool):
        raise ValueError(
            f"OpenAI Agents SDK setting {setting_name} must be zero or a positive integer, "
            f"got {value!r}"
        )
    try:
        parsed = int(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(
            f"OpenAI Agents SDK setting {setting_name} must be zero or a positive integer, "
            f"got {value!r}"
        ) from exc
    if parsed < 0:
        raise ValueError(
            f"OpenAI Agents SDK setting {setting_name} must be zero or a positive integer, "
            f"got {value!r}"
        )
    return parsed


def _positive_int_from_value_or_env(
    value: Any,
    *,
    env_name: str,
    default: int,
    setting_name: str,
) -> int:
    if value is None:
        raw_env = os.environ.get(env_name)
        if raw_env not in {None, ""}:
            return _positive_int(
                raw_env,
                default=default,
                setting_name=setting_name,
                env_name=env_name,
            )
        value = default
    if value == "":
        value = default
    return _positive_int(value, default=default, setting_name=setting_name)
