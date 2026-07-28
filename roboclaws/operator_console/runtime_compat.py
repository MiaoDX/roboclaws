"""Small runtime helpers shared by operator-console subsystems."""

from __future__ import annotations

import os
import sys
from pathlib import Path
from typing import Any


def pid_is_active(pid: Any) -> bool:
    try:
        parsed_pid = int(pid)
    except (TypeError, ValueError):
        return False
    if parsed_pid <= 0:
        return False
    if _linux_process_state(parsed_pid) in {"Z", "X"}:
        return False
    try:
        os.kill(parsed_pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


def _linux_process_state(pid: int) -> str | None:
    if not sys.platform.startswith("linux"):
        return None
    try:
        stat = Path(f"/proc/{pid}/stat").read_text(encoding="utf-8")
    except (OSError, UnicodeError):
        return None
    closing_paren = stat.rfind(")")
    fields = stat[closing_paren + 1 :].split() if closing_paren >= 0 else []
    return fields[0] if fields else None


def float_or_none(value: Any) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None
