"""File-backed operator-message and resume queue protocol."""

from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any

from roboclaws.core.jsonl_sources import JsonlSourceIssue, collect_jsonl_objects

MESSAGE_LOG = "operator_messages.jsonl"
RESUME_REQUEST_LOG = "operator_resume_requests.jsonl"


def read_operator_message_rows(
    run_dir: Path,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    rows, issues = collect_jsonl_objects(run_dir / MESSAGE_LOG, label="operator message source")
    return rows, [_source_error(issue, source="operator_messages") for issue in issues]


def read_operator_resume_rows(
    run_dir: Path,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    rows, issues = collect_jsonl_objects(
        run_dir / RESUME_REQUEST_LOG,
        label="operator resume source",
    )
    return rows, [_source_error(issue, source="operator_resume_requests") for issue in issues]


def operator_message_state(run_dir: Path) -> dict[str, Any]:
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


def check_operator_messages_for_mcp(run_dir: Path, *, max_messages: int = 10) -> dict[str, Any]:
    """Return queued steer messages and mark them seen for MCP delivery."""

    wrapper_dir = _wrapper_dir_for_display(run_dir)
    rows, source_errors = read_operator_message_rows(wrapper_dir)
    if source_errors:
        return {
            "ok": False,
            "tool": "check_operator_messages",
            "status": "source_error",
            "error_reason": "operator_message_source_error",
            "operator_message_pending": False,
            "messages": [],
            "message_count": 0,
            "source_errors": source_errors,
            "instruction": (
                "Operator steering inbox exists but could not be parsed. Treat this as a "
                "source error and ask the operator to inspect operator_messages.jsonl."
            ),
        }
    selected: list[dict[str, Any]] = []
    next_rows: list[dict[str, Any]] = []
    now = _utc_now()
    for row in rows:
        if (
            row.get("command_type") == "steer"
            and row.get("status") == "queued"
            and len(selected) < max_messages
        ):
            updated = dict(row)
            updated["status"] = "seen"
            updated["seen_at_epoch"] = now
            updated["seen_at"] = _format_epoch(now)
            selected.append(_public_mcp_message(updated))
            next_rows.append(updated)
            continue
        next_rows.append(row)
    if selected:
        _rewrite_jsonl(wrapper_dir / MESSAGE_LOG, next_rows)
    return {
        "ok": True,
        "tool": "check_operator_messages",
        "status": "seen" if selected else "empty",
        "operator_message_pending": any(
            item.get("command_type") == "steer" and item.get("status") == "queued"
            for item in next_rows
        ),
        "messages": selected,
        "message_count": len(selected),
        "instruction": (
            "Treat seen operator messages as public steering hints. Acknowledge by "
            "following the safe checkpoint guidance or explain why a message cannot be applied."
        ),
    }


def consume_resume_request_for_runner(run_dir: Path, *, max_requests: int = 1) -> dict[str, Any]:
    """Return queued resume requests and mark them claimed by the live runner."""

    wrapper_dir = _wrapper_dir_for_display(run_dir)
    rows, source_errors = read_operator_resume_rows(wrapper_dir)
    if source_errors:
        return {
            "ok": False,
            "status": "source_error",
            "error_reason": "operator_resume_source_error",
            "requests": [],
            "request_count": 0,
            "source_errors": source_errors,
        }
    selected: list[dict[str, Any]] = []
    next_rows: list[dict[str, Any]] = []
    now = _utc_now()
    for row in rows:
        if (
            row.get("command_type") == "resume_with_prompt"
            and row.get("status") == "queued"
            and len(selected) < max_requests
        ):
            updated = dict(row)
            updated["status"] = "claimed"
            updated["claimed_at_epoch"] = now
            updated["claimed_at"] = _format_epoch(now)
            selected.append(updated)
            next_rows.append(updated)
            continue
        next_rows.append(row)
    if selected:
        _rewrite_jsonl(wrapper_dir / RESUME_REQUEST_LOG, next_rows)
    return {
        "ok": True,
        "status": "claimed" if selected else "empty",
        "requests": selected,
        "request_count": len(selected),
        "operator_resume_pending": any(
            item.get("command_type") == "resume_with_prompt" and item.get("status") == "queued"
            for item in next_rows
        ),
    }


def pending_operator_message_hint(run_dir: Path) -> dict[str, Any]:
    wrapper_dir = _wrapper_dir_for_display(run_dir)
    rows, source_errors = read_operator_message_rows(wrapper_dir)
    if source_errors:
        return {
            "operator_message_source_error": True,
            "operator_message_source_errors": source_errors,
            "operator_message_instruction": (
                "Operator steering inbox exists but could not be parsed. "
                "Call check_operator_messages to surface the source error."
            ),
        }
    pending = [
        row for row in rows if row.get("command_type") == "steer" and row.get("status") == "queued"
    ]
    if not pending:
        return {}
    return {
        "operator_message_pending": True,
        "pending_operator_message_count": len(pending),
        "operator_message_instruction": (
            "Unread operator steering exists. Call check_operator_messages at the next "
            "safe checkpoint to read and acknowledge it."
        ),
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


def _rewrite_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    temp_path = path.with_suffix(path.suffix + ".tmp")
    temp_path.write_text(
        "".join(json.dumps(row, sort_keys=True) + "\n" for row in rows),
        encoding="utf-8",
    )
    temp_path.replace(path)


def _utc_now() -> float:
    return time.time()


def _format_epoch(epoch: float) -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(epoch))


def _public_mcp_message(message: dict[str, Any]) -> dict[str, Any]:
    return {
        "message_id": str(message.get("message_id") or ""),
        "status": str(message.get("status") or ""),
        "body": str(message.get("body") or ""),
        "created_at": str(message.get("created_at") or ""),
    }


def _wrapper_dir_for_display(run_dir: Path) -> Path:
    run_dir = Path(run_dir).resolve()
    if (run_dir / "operator_state.json").exists():
        return run_dir
    for parent in run_dir.parents:
        if (parent / "operator_state.json").exists():
            return parent
    return run_dir
