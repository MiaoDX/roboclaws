from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from roboclaws.core.json_sources import read_json_object

SCRATCHPAD_SCHEMA = "molmo_cleanup_skill_scratchpad_v1"


def empty_skill_scratchpad(*, note: str = "") -> dict[str, Any]:
    scratchpad = {
        "schema": SCRATCHPAD_SCHEMA,
        "authoritative": False,
        "observed_handles": {},
        "waypoints": {},
        "current_intent": None,
        "failed_attempts": [],
        "reconciliation_notes": [],
        "notes": [],
    }
    if note:
        scratchpad["notes"].append(note)
    return scratchpad


def validate_skill_scratchpad(data: dict[str, Any]) -> None:
    if data.get("schema") != SCRATCHPAD_SCHEMA:
        raise ValueError(f"scratchpad schema must be {SCRATCHPAD_SCHEMA}")
    if data.get("authoritative") is not False:
        raise ValueError("skill scratchpad must be non-authoritative")


def read_or_create_skill_scratchpad(
    *,
    run_dir: Path,
    note: str = "",
) -> tuple[dict[str, Any], Path]:
    path = run_dir / "agent_scratchpad.json"
    if path.is_file():
        data = read_json_object(path, label="skill scratchpad")
        validate_skill_scratchpad(data)
        return data, path
    data = empty_skill_scratchpad(note=note)
    path.write_text(json.dumps(data, indent=2, sort_keys=True) + "\n")
    return data, path
