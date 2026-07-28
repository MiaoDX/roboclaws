#!/usr/bin/env python3
"""Run-local non-authoritative scratchpad helpers for cleanup agents."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

SCRATCHPAD_SCHEMA = "molmo_cleanup_skill_scratchpad_v1"
DEFAULT_PATH = Path("cleanup_scratch.json")


def empty_scratchpad() -> dict[str, Any]:
    return {
        "schema": SCRATCHPAD_SCHEMA,
        "authoritative": False,
        "observed_handles": {},
        "waypoints": {},
        "current_intent": None,
        "failed_attempts": [],
        "reconciliation_notes": [],
        "notes": [],
    }


def load_scratchpad(path: Path = DEFAULT_PATH) -> dict[str, Any]:
    if not path.exists():
        return empty_scratchpad()
    data = _read_json_object(path, label="skill scratchpad")
    validate_scratchpad(data)
    return data


def save_scratchpad(data: dict[str, Any], path: Path = DEFAULT_PATH) -> None:
    validate_scratchpad(data)
    path.write_text(json.dumps(data, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def validate_scratchpad(data: dict[str, Any]) -> None:
    if data.get("schema") != SCRATCHPAD_SCHEMA:
        raise ValueError(f"scratchpad schema must be {SCRATCHPAD_SCHEMA}")
    if data.get("authoritative") is not False:
        raise ValueError("skill scratchpad must be non-authoritative")
    for key, expected in (
        ("observed_handles", dict),
        ("waypoints", dict),
        ("failed_attempts", list),
        ("reconciliation_notes", list),
        ("notes", list),
    ):
        if not isinstance(data.get(key), expected):
            raise ValueError(f"scratchpad field {key} must be {expected.__name__}")


def parse_routine_result_json(text: str) -> dict[str, Any]:
    return _parse_json_object_text(
        text,
        label="routine result JSON",
        source="--result-json",
    )


def _read_json_object(path: Path, *, label: str) -> dict[str, Any]:
    try:
        return _parse_json_object_text(
            path.read_text(encoding="utf-8"),
            label=label,
            source=str(path),
        )
    except OSError as exc:
        raise ValueError(f"{label} source cannot be read: {path}: {exc}") from exc


def _parse_json_object_text(text: str, *, label: str, source: str) -> dict[str, Any]:
    try:
        payload = json.loads(text)
    except json.JSONDecodeError as exc:
        raise ValueError(f"{label} source must contain valid JSON object: {source}") from exc
    if not isinstance(payload, dict):
        raise ValueError(f"{label} source must contain a JSON object: {source}")
    return payload


def record_intent(
    data: dict[str, Any],
    *,
    object_id: str,
    fixture_id: str,
    note: str = "",
) -> dict[str, Any]:
    validate_scratchpad(data)
    data["current_intent"] = {
        "object_id": object_id,
        "fixture_id": fixture_id,
        "note": note,
    }
    return data


def record_routine_result(data: dict[str, Any], result: dict[str, Any]) -> dict[str, Any]:
    validate_scratchpad(data)
    object_id = str(result.get("object_id") or "")
    if object_id:
        data["observed_handles"][object_id] = {
            "object_id": object_id,
            "fixture_id": str(result.get("fixture_id") or ""),
            "ok": bool(result.get("ok")),
            "routine": str(result.get("routine") or ""),
            "failed_phase": str(result.get("failed_phase") or ""),
            "error_reason": str(result.get("error_reason") or ""),
        }
    if not result.get("ok"):
        data["failed_attempts"].append(
            {
                "object_id": object_id,
                "fixture_id": str(result.get("fixture_id") or ""),
                "failed_phase": str(result.get("failed_phase") or ""),
                "error_reason": str(result.get("error_reason") or ""),
            }
        )
    data["current_intent"] = None
    return data


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    init = sub.add_parser("init")
    init.add_argument("--path", type=Path, default=DEFAULT_PATH)
    validate = sub.add_parser("validate")
    validate.add_argument("--path", type=Path, default=DEFAULT_PATH)
    intent = sub.add_parser("intent")
    intent.add_argument("--path", type=Path, default=DEFAULT_PATH)
    intent.add_argument("--object-id", required=True)
    intent.add_argument("--fixture-id", required=True)
    intent.add_argument("--note", default="")
    result = sub.add_parser("record-result")
    result.add_argument("--path", type=Path, default=DEFAULT_PATH)
    result.add_argument("--result-json", required=True)

    args = parser.parse_args(argv)
    try:
        if args.command == "init":
            save_scratchpad(empty_scratchpad(), args.path)
            return 0
        data = load_scratchpad(args.path)
        if args.command == "validate":
            validate_scratchpad(data)
            print(json.dumps(data, indent=2, sort_keys=True))
            return 0
        if args.command == "intent":
            save_scratchpad(
                record_intent(
                    data,
                    object_id=args.object_id,
                    fixture_id=args.fixture_id,
                    note=args.note,
                ),
                args.path,
            )
            return 0
        save_scratchpad(
            record_routine_result(data, parse_routine_result_json(args.result_json)),
            args.path,
        )
        return 0
    except ValueError as exc:
        raise SystemExit(str(exc)) from exc


if __name__ == "__main__":
    raise SystemExit(main())
