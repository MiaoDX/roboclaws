"""Shared helpers for maintainer agent CLI dispatchers."""

from __future__ import annotations

import os
import sys
from collections.abc import Sequence
from typing import NoReturn


def _exec_or_trace(cmd: Sequence[str], *, env: dict[str, str] | None = None) -> int:
    if os.environ.get("ROBOCLAWS_JUST_TRACE") == "1":
        prefix = "cmd" if cmd and cmd[0] != "just" else "just"
        payload = list(cmd if prefix == "cmd" else cmd[1:])
        print("\t".join([prefix, *payload]))
        return 0
    if env:
        os.environ.update(env)
    os.execvp(cmd[0], list(cmd))
    return 1


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
