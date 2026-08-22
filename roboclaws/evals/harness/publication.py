"""Atomic publication of terminal Eval Harness report artifacts."""

from __future__ import annotations

import datetime as dt
import hashlib
import json
import os
import tempfile
from pathlib import Path
from typing import Any

COMPLETION_MARKER_SCHEMA = "roboclaws_eval_harness_completion_v1"
COMPLETION_MARKER_NAME = "eval_harness.completed.json"
REPORT_FILENAMES = ("eval_harness.json", "eval_harness.md", "eval_harness.html")


def publish_reports(manifest: dict[str, Any], output_dir: Path, rendered: dict[Path, str]) -> None:
    """Publish report files and expose a marker only after all are complete."""
    marker_path = output_dir / COMPLETION_MARKER_NAME
    marker_path.unlink(missing_ok=True)
    for path, content in rendered.items():
        _atomic_write_text(path, content)
    report = manifest.get("observability_decision_report")
    if not isinstance(report, dict) or report.get("state") not in {
        "ready",
        "ready_with_limitations",
    }:
        return
    marker = {
        "schema": COMPLETION_MARKER_SCHEMA,
        "run_id": output_dir.name,
        "finalized_at": dt.datetime.now(dt.UTC)
        .replace(microsecond=0)
        .isoformat()
        .replace("+00:00", "Z"),
        "artifacts": {
            path.name: hashlib.sha256(content.encode("utf-8")).hexdigest()
            for path, content in rendered.items()
        },
    }
    _atomic_write_text(marker_path, json.dumps(marker, indent=2, sort_keys=True) + "\n")


def _atomic_write_text(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary_path: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            dir=path.parent,
            prefix=f".{path.name}.",
            suffix=".tmp",
            delete=False,
        ) as handle:
            temporary_path = Path(handle.name)
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary_path, path)
    finally:
        if temporary_path is not None:
            temporary_path.unlink(missing_ok=True)
