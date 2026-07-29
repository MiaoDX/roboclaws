"""Shared helpers for maintainer agent CLI dispatchers."""

from __future__ import annotations

import os
import sys
from collections.abc import Sequence
from typing import NoReturn

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
        payload = _redact_trace_args(
            trace_cmd if prefix == "cmd" else trace_cmd[1:],
            keys=keys,
        )
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


def _has_raw_override_key(raw_overrides: Sequence[str], wanted: str) -> bool:
    return any(
        override.startswith(f"{wanted}=") or override.startswith(f"--{wanted}=")
        for override in raw_overrides
    )


def _get(kv: dict[str, str], key: str, default: str) -> str:
    value = kv.get(key)
    return value if value else default


def _strip_prefixes(value: str, *prefixes: str) -> str:
    for prefix in prefixes:
        if value.startswith(prefix):
            return value.removeprefix(prefix)
    return value


def _die(message: str) -> NoReturn:
    print(f"error: {message}", file=sys.stderr)
    raise SystemExit(1)
