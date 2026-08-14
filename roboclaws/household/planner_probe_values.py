from __future__ import annotations

from typing import Any


def diagnostic_json_value(value: Any) -> Any:
    if isinstance(value, str | int | float | bool) or value is None:
        return value
    if isinstance(value, tuple | list):
        return [diagnostic_json_value(item) for item in value]
    if isinstance(value, dict):
        return {str(key): diagnostic_json_value(item) for key, item in value.items()}
    tolist = getattr(value, "tolist", None)
    if callable(tolist):
        return diagnostic_json_value(tolist())
    return str(value)
