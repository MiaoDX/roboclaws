"""Generic structured JSONL source helpers."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

JsonlIssueKind = Literal["read_error", "invalid_json", "non_object"]


@dataclass(frozen=True)
class JsonlSourceIssue:
    """Structured source issue for a present JSONL artifact."""

    path: Path
    label: str
    kind: JsonlIssueKind
    message: str
    line_number: int | None = None
    column_number: int | None = None

    def state_reason(self) -> str:
        if self.kind == "invalid_json":
            return f"invalid JSON at line {self.line_number} column {self.column_number}"
        if self.kind == "non_object":
            return f"expected JSON object at line {self.line_number}"
        return self.message

    def history_reason(self) -> str:
        if self.kind == "non_object":
            return f"line {self.line_number} expected JSON object"
        return self.state_reason()


def collect_jsonl_objects(
    path: Path,
    *,
    label: str,
    encoding_errors: str = "replace",
) -> tuple[list[dict[str, Any]], tuple[JsonlSourceIssue, ...]]:
    """Return valid object rows and row-level source issues from a JSONL artifact."""

    if not path.exists():
        return [], ()
    resolved = path.resolve()
    try:
        lines = path.read_text(encoding="utf-8", errors=encoding_errors).splitlines()
    except (OSError, UnicodeError) as exc:
        return [], (
            JsonlSourceIssue(path=resolved, label=label, kind="read_error", message=str(exc)),
        )

    rows: list[dict[str, Any]] = []
    issues: list[JsonlSourceIssue] = []
    for line_number, line in enumerate(lines, start=1):
        if not line.strip():
            continue
        try:
            payload = json.loads(line)
        except json.JSONDecodeError as exc:
            issues.append(
                JsonlSourceIssue(
                    path=resolved,
                    label=label,
                    kind="invalid_json",
                    message=exc.msg,
                    line_number=line_number,
                    column_number=exc.colno,
                )
            )
            continue
        if not isinstance(payload, dict):
            issues.append(
                JsonlSourceIssue(
                    path=resolved,
                    label=label,
                    kind="non_object",
                    message="row must be a JSON object",
                    line_number=line_number,
                )
            )
            continue
        rows.append(payload)
    return rows, tuple(issues)
