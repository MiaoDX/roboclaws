"""Read operator-message JSONL artifacts for console consumers."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from roboclaws.operator_console.jsonl_sources import (
    JsonlSourceIssue,
    collect_jsonl_objects,
)


def read_operator_message_rows(
    run_dir: Path,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Read valid operator-message rows and normalize source errors."""

    rows, issues = collect_jsonl_objects(
        run_dir / "operator_messages.jsonl",
        label="operator message source",
    )
    return rows, [_source_error(issue, source="operator_messages") for issue in issues]


def read_operator_resume_rows(
    run_dir: Path,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Read valid operator-resume rows and normalize source errors."""

    rows, issues = collect_jsonl_objects(
        run_dir / "operator_resume_requests.jsonl",
        label="operator resume source",
    )
    return rows, [_source_error(issue, source="operator_resume_requests") for issue in issues]


def operator_message_state(run_dir: Path) -> dict[str, Any]:
    """Summarize operator-message artifacts for the normalized run payload."""

    rows, source_errors = read_operator_message_rows(run_dir)
    resume_rows, resume_source_errors = read_operator_resume_rows(run_dir)
    pending_steer = [
        item
        for item in rows
        if item.get("command_type") == "steer" and item.get("status") == "queued"
    ]
    pending_resume = [
        item
        for item in resume_rows
        if item.get("command_type") == "resume_with_prompt" and item.get("status") == "queued"
    ]
    return {
        "operator_session_id": _operator_session_id(run_dir),
        "message_count": len(rows),
        "pending_steer_count": len(pending_steer),
        "operator_message_pending": bool(pending_steer),
        "pending_resume_count": len(pending_resume),
        "operator_resume_pending": bool(pending_resume),
        "source_errors": [*source_errors, *resume_source_errors],
        "source_error": bool(source_errors or resume_source_errors),
    }


def _operator_session_id(run_dir: Path) -> str:
    try:
        state = json.loads((run_dir / "operator_state.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return ""
    return str(state.get("operator_session_id") or "") if isinstance(state, dict) else ""


def _source_error(issue: JsonlSourceIssue, *, source: str) -> dict[str, Any]:
    if issue.kind == "read_error":
        artifact = "message" if source == "operator_messages" else "resume"
        message = f"cannot read operator {artifact} source: {issue.message}"
    elif issue.kind == "invalid_json":
        message = f"invalid JSON: {issue.message}"
    else:
        message = issue.message
    payload: dict[str, Any] = {
        "source": source,
        "path": str(issue.path),
        "message": message,
    }
    if issue.line_number is not None:
        payload["line"] = issue.line_number
    return payload
