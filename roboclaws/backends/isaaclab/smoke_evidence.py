"""Load Isaac runtime-smoke evidence emitted by noisy subprocesses."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from roboclaws.household.worker_runner import parse_last_json_object


def read_init_result(path: Path) -> dict[str, Any]:
    payload = _read_json_object(path)
    if payload is None:
        raise ValueError(
            f"Isaac runtime smoke init result source must contain a JSON object: {path}"
        )
    return payload


def read_sidecar_json(path: Path | None, *, label: str) -> dict[str, Any]:
    if path is None:
        return {}
    payload = _read_json_object(path)
    if payload is None:
        raise ValueError(f"{label} source must contain valid JSON object: {path}")
    return payload


def _read_json_object(path: Path) -> dict[str, Any] | None:
    text = path.read_text(encoding="utf-8")
    try:
        payload = json.loads(text)
    except json.JSONDecodeError:
        payload = parse_last_json_object(text)
    return payload if isinstance(payload, dict) else None
