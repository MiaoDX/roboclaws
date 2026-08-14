"""Artifact and trace source loading for eval grading."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from roboclaws.core.json_sources import collect_jsonl_object_rows, read_json_object


def artifact_paths(run_dir: Path) -> dict[str, Any]:
    paths = {
        "run_dir": run_dir,
        "run_result": run_dir / "run_result.json",
        "report": run_dir / "report.html",
        "trace": run_dir / "trace.jsonl",
        "agent_view": run_dir / "agent_view.json",
        "runtime_metric_map": run_dir / "runtime_metric_map.json",
        "private_evaluation": run_dir / "private_evaluation.json",
    }
    return {key: str(path) for key, path in paths.items()}


def list_of_mappings(value: Any) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        return []
    return [item for item in value if isinstance(item, dict)]


def read_trace_events_with_errors(path: Path) -> tuple[list[dict[str, Any]], list[str]]:
    rows, issues = collect_jsonl_object_rows(path, label="eval trace")
    errors: list[str] = []
    for issue in issues:
        if issue.kind == "invalid_json":
            errors.append(f"line {issue.line_number}: invalid_json:{issue.message}")
        elif issue.kind == "non_object":
            errors.append(f"line {issue.line_number}: invalid_json_object")
        else:
            errors.append(f"read_error:{issue.message}")
    return [row for _, row in rows], errors


def load_optional_json_mapping(path: Path) -> tuple[dict[str, Any], str]:
    return _load_json_mapping(path, missing_reason="")


def json_source_error(path: Path, reason: str) -> dict[str, str]:
    if not reason:
        return {}
    return {"path": str(path), "reason": reason}


def required_json_artifact_source_errors(
    paths: dict[str, Path],
) -> list[dict[str, str]]:
    errors: list[dict[str, str]] = []
    for name, path in paths.items():
        _payload, reason = load_optional_json_mapping(path)
        if reason:
            errors.append({"artifact": name, "path": str(path), "reason": reason})
    return errors


def load_required_json_mapping(path: Path) -> tuple[dict[str, Any], str]:
    return _load_json_mapping(path, missing_reason="missing")


def _load_json_mapping(path: Path, *, missing_reason: str) -> tuple[dict[str, Any], str]:
    try:
        return read_json_object(path, label="eval runner JSON artifact"), ""
    except FileNotFoundError:
        return {}, missing_reason
    except ValueError as exc:
        return {}, _json_artifact_error_reason(exc)
    except OSError as exc:
        return {}, f"read_error:{exc.strerror or exc}"


def _json_artifact_error_reason(exc: ValueError) -> str:
    cause = exc.__cause__
    if isinstance(cause, json.JSONDecodeError):
        return f"invalid_json:{cause.msg}"
    if "must contain a JSON object" in str(exc):
        return "invalid_json_object"
    return str(exc)
