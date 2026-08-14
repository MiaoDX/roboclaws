"""Pure generated-mess policy shared by runtime and evaluation owners."""

from __future__ import annotations

import math


def generated_mess_success_threshold(target_count: int) -> int:
    """Return the cleanup success threshold for a generated target count."""

    return max(1, math.ceil(target_count * 0.70))
