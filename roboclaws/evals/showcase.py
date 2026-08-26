"""Sanitized, versioned capability showcase summaries."""

from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import html
import json
import os
import tempfile
from pathlib import Path
from typing import Any

SCHEMA = "roboclaws_showcase_summary_v1"
MANIFEST_SCHEMA = "roboclaws_showcase_manifest_v1"
STATUSES = {"passed", "failed", "blocked"}
ALLOWED_METRICS = {"total", "passed", "failed", "blocked", "pass_at_1"}
PRIVATE_KEYS = {"prompt", "goal", "tool_body", "image", "map", "endpoint", "secret"}


def manifest_digest(manifest: dict[str, Any]) -> str:
    return hashlib.sha256(
        json.dumps(manifest, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


def validate_manifest(manifest: dict[str, Any]) -> dict[str, Any]:
    if manifest.get("schema") != MANIFEST_SCHEMA or not isinstance(manifest.get("rows"), list):
        raise ValueError("showcase manifest has an invalid schema")
    seen: set[str] = set()
    for row in manifest["rows"]:
        if not isinstance(row, dict) or not isinstance(row.get("id"), str):
            raise ValueError("showcase manifest rows require an id")
        if row["id"] in seen:
            raise ValueError(f"duplicate showcase row id: {row['id']}")
        seen.add(row["id"])
        for key in ("suite", "version", "seed", "budget", "timeout_s", "execution_mode"):
            if key not in row:
                raise ValueError(f"showcase row {row['id']} missing {key}")
    return manifest


def derive_row(
    row: dict[str, Any], results: dict[str, Any] | None, *, source: str | None = None
) -> dict[str, Any]:
    aggregate = results.get("aggregate", {}) if isinstance(results, dict) else {}
    if not isinstance(aggregate, dict):
        aggregate = {}
    if results is None:
        status, reason = "blocked", "results_unavailable"
    elif (
        aggregate.get("blocked", 0)
        and not aggregate.get("failed", 0)
        and not aggregate.get("passed", 0)
    ):
        status, reason = "blocked", next(iter(aggregate.get("failure_classes", {"unavailable": 1})))
    elif aggregate.get("failed", 0):
        status, reason = (
            "failed",
            next(iter(aggregate.get("failure_classes", {"evaluation_failed": 1}))),
        )
    else:
        status, reason = "passed", None
    metrics = {
        key: aggregate[key]
        for key in ALLOWED_METRICS
        if key in aggregate and isinstance(aggregate[key], (int, float))
    }
    result = {
        "id": row["id"],
        "suite": row["suite"],
        "version": row["version"],
        "status": status,
        "reason": reason,
        "metrics": metrics,
    }
    if source:
        result["source_artifact"] = source
    return result


def build_summary(
    manifest: dict[str, Any],
    rows: list[dict[str, Any]],
    *,
    commit: str,
    run_url: str,
    attempted_at: str | None = None,
    previous: dict[str, Any] | None = None,
) -> dict[str, Any]:
    validate_manifest(manifest)
    now = attempted_at or dt.datetime.now(dt.UTC).replace(microsecond=0).isoformat().replace(
        "+00:00", "Z"
    )
    prior = (previous or {}).get("last_success", {})
    last_success = dict(prior) if isinstance(prior, dict) else {}
    for item in rows:
        if item.get("status") == "passed":
            last_success[item["id"]] = {
                "attempted_at": now,
                "commit": commit,
                "run_url": run_url,
                "row": item,
            }
    summary = {
        "schema": SCHEMA,
        "manifest_digest": manifest_digest(manifest),
        "attempted_at": now,
        "commit": commit,
        "run_url": run_url,
        "rows": rows,
        "last_success": last_success,
    }
    _reject_private(summary)
    return summary


def write_atomic(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temp = tempfile.mkstemp(dir=path.parent, prefix=f".{path.name}.", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(payload, handle, indent=2, sort_keys=True)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temp, path)
    finally:
        Path(temp).unlink(missing_ok=True)


def render_markdown(summary: dict[str, Any]) -> str:
    lines = [
        "# Roboclaws capability showcase",
        "",
        "Advisory evidence only; this showcase is not a merge gate.",
        "",
        f"Latest attempt: `{summary['attempted_at']}` at `{summary['commit']}`",
        "",
        "| Capability | Status | Reason | Last successful evidence |",
        "| --- | --- | --- | --- |",
    ]
    successes = summary.get("last_success", {})
    for row in summary["rows"]:
        success = successes.get(row["id"], {})
        last = success.get("attempted_at", "none")
        lines.append(f"| {row['id']} | {row['status']} | {row.get('reason') or '-'} | {last} |")
    lines.extend(("", f"[Actions run]({summary['run_url']})", ""))
    return "\n".join(lines)


def render_html(summary: dict[str, Any]) -> str:
    markdown = render_markdown(summary)
    return (
        "<!doctype html><meta charset=utf-8><title>Roboclaws capability showcase</title>"
        "<style>body{font:16px system-ui;max-width:960px;margin:3rem auto;padding:0 1rem}"
        "pre{white-space:pre-wrap}a{color:#075985}</style>"
        f"<pre>{html.escape(markdown)}</pre>"
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Build the sanitized capability showcase.")
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--commit", required=True)
    parser.add_argument("--run-url", required=True)
    parser.add_argument("--result", action="append", default=[], metavar="ROW_ID=PATH")
    parser.add_argument("--previous", type=Path)
    args = parser.parse_args(argv)
    manifest = validate_manifest(json.loads(args.manifest.read_text(encoding="utf-8")))
    result_paths = dict(item.split("=", 1) for item in args.result)
    rows = []
    for row in manifest["rows"]:
        path_value = result_paths.get(row["id"])
        payload = json.loads(Path(path_value).read_text(encoding="utf-8")) if path_value else None
        rows.append(derive_row(row, payload, source=path_value))
    previous = None
    if args.previous and args.previous.is_file():
        previous = json.loads(args.previous.read_text(encoding="utf-8"))
    summary = build_summary(
        manifest, rows, commit=args.commit, run_url=args.run_url, previous=previous
    )
    write_atomic(args.output / "showcase-summary-v1.json", summary)
    _atomic_write_text(args.output / "index.md", render_markdown(summary))
    _atomic_write_text(args.output / "index.html", render_html(summary))
    return 0


def _atomic_write_text(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temp = tempfile.mkstemp(dir=path.parent, prefix=f".{path.name}.", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temp, path)
    finally:
        Path(temp).unlink(missing_ok=True)


def _reject_private(value: Any, path: str = "summary") -> None:
    if isinstance(value, dict):
        for key, child in value.items():
            if key.lower() in PRIVATE_KEYS:
                raise ValueError(f"private field is not publishable: {path}.{key}")
            _reject_private(child, f"{path}.{key}")
    elif isinstance(value, list):
        for index, child in enumerate(value):
            _reject_private(child, f"{path}[{index}]")


if __name__ == "__main__":
    raise SystemExit(main())
