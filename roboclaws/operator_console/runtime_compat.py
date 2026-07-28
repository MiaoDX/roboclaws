"""Small runtime helpers shared by operator-console subsystems."""

from __future__ import annotations

import os
from typing import Any


def pid_is_active(pid: Any) -> bool:
    try:
        parsed_pid = int(pid)
    except (TypeError, ValueError):
        return False
    if parsed_pid <= 0:
        return False
    try:
        os.kill(parsed_pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


def float_or_none(value: Any) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None
