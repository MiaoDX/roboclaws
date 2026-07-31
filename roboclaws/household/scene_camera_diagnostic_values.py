from __future__ import annotations

import json
from typing import Any


def optional_float(value: Any) -> float | None:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def optional_int(value: Any) -> int | None:
    if value is None or value == "":
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def positive_number(value: Any) -> bool:
    try:
        return float(value) > 0.0
    except (TypeError, ValueError):
        return False


def non_unity_gain(value: Any) -> bool:
    try:
        return abs(float(value) - 1.0) > 1e-6
    except (TypeError, ValueError):
        return False


def float_text(value: Any) -> str:
    if value is None or value == "":
        return ""
    try:
        return f"{float(value):.2f}"
    except (TypeError, ValueError):
        return str(value)


def cell_text(value: Any) -> str:
    if isinstance(value, list):
        return short_list_text(value, limit=6)
    if isinstance(value, dict):
        return json.dumps(value, sort_keys=True)
    return "" if value is None else str(value)


def short_list_text(value: Any, *, limit: int = 4) -> str:
    if not isinstance(value, list):
        return ""
    items = [str(item) for item in value if item is not None and str(item) != ""]
    if len(items) <= limit:
        return ", ".join(items)
    return f"{', '.join(items[:limit])}, ... (+{len(items) - limit})"
