from __future__ import annotations

from datetime import UTC, datetime


def pipeline_family(pipeline_id: str) -> str:
    first = pipeline_id.split("+", maxsplit=1)[0]
    return first.removesuffix("-direct")


def safe_id(value: str) -> str:
    safe = [char if char.isalnum() or char in {"-", "_"} else "-" for char in value]
    return "".join(safe).strip("-") or "item"


def timestamp() -> str:
    return datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
