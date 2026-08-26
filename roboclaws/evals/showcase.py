"""Sanitized, versioned capability showcase summaries."""

from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import html
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any

SCHEMA = "roboclaws_showcase_summary_v1"
MANIFEST_SCHEMA = "roboclaws_showcase_manifest_v1"
STATUSES = {"passed", "failed", "blocked", "not_run"}
ALLOWED_METRICS = {"total", "passed", "failed", "blocked", "pass_at_1"}
PRIVATE_KEYS = {"prompt", "goal", "tool_body", "image", "map", "endpoint", "secret"}
EXECUTION_MODES = {"deterministic", "deterministic_and_manual_live", "manual_live_only"}


def manifest_digest(manifest: dict[str, Any]) -> str:
    return hashlib.sha256(
        json.dumps(manifest, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


def validate_manifest(manifest: dict[str, Any]) -> dict[str, Any]:
    from roboclaws.evals.suite_loading import load_suite

    if manifest.get("schema") != MANIFEST_SCHEMA or not isinstance(manifest.get("rows"), list):
        raise ValueError("showcase manifest has an invalid schema")
    seen: set[str] = set()
    for row in manifest["rows"]:
        if not isinstance(row, dict) or not isinstance(row.get("id"), str):
            raise ValueError("showcase manifest rows require an id")
        if row["id"] in seen:
            raise ValueError(f"duplicate showcase row id: {row['id']}")
        seen.add(row["id"])
        for key in (
            "suite",
            "version",
            "sample_ids",
            "agent_engine",
            "provider_profile",
            "seed",
            "evidence_lane",
            "budget",
            "timeout_s",
            "execution_mode",
        ):
            if key not in row:
                raise ValueError(f"showcase row {row['id']} missing {key}")
        if row["execution_mode"] not in EXECUTION_MODES:
            raise ValueError(f"showcase row {row['id']} has invalid execution_mode")
        suite, samples = load_suite(row["suite"])
        if suite.suite_id != row["id"] or suite.version != row["version"]:
            raise ValueError(f"showcase row {row['id']} does not match canonical suite identity")
        if [sample.sample_id for sample in samples] != row["sample_ids"]:
            raise ValueError(f"showcase row {row['id']} does not match canonical sample ids")
    return manifest


def execute_manifest(
    manifest: dict[str, Any], *, output_dir: Path, live_execution: str
) -> dict[str, Any]:
    """Run manifest rows serially through the canonical eval CLI without retries."""
    validate_manifest(manifest)
    if live_execution not in {"blocked", "run"}:
        raise ValueError("live_execution must be blocked or run")
    output_dir.mkdir(parents=True, exist_ok=True)
    results: dict[str, str] = {}
    attempts: list[dict[str, Any]] = []
    for row in manifest["rows"]:
        execution_identity = _row_execution_identity(row, live_execution=live_execution)
        command = _row_command(row, live_execution=live_execution, output_dir=output_dir)
        if command is None:
            attempts.append(
                {
                    "id": row["id"],
                    "state": "blocked",
                    "reason": "live_execution_not_requested",
                    **execution_identity,
                }
            )
            continue
        try:
            completed = subprocess.run(
                command,
                check=False,
                capture_output=True,
                text=True,
                timeout=int(row["timeout_s"]),
            )
        except subprocess.TimeoutExpired:
            attempts.append(
                {
                    "id": row["id"],
                    "state": "blocked",
                    "reason": "showcase_row_timeout",
                    **execution_identity,
                }
            )
            continue
        if completed.returncode != 0:
            attempts.append(
                {
                    "id": row["id"],
                    "state": "blocked",
                    "reason": "suite_command_failed",
                    **execution_identity,
                }
            )
            continue
        try:
            payload = json.loads(completed.stdout)
            results_path = Path(payload["results"])
        except (KeyError, TypeError, json.JSONDecodeError):
            attempts.append(
                {
                    "id": row["id"],
                    "state": "blocked",
                    "reason": "suite_output_invalid",
                    **execution_identity,
                }
            )
            continue
        if not results_path.is_file():
            attempts.append(
                {
                    "id": row["id"],
                    "state": "blocked",
                    "reason": "results_unavailable",
                    **execution_identity,
                }
            )
            continue
        results[row["id"]] = str(results_path)
        attempts.append(
            {"id": row["id"], "state": "completed", "reason": None, **execution_identity}
        )
    index = {"schema": "roboclaws_showcase_execution_v1", "results": results, "attempts": attempts}
    write_atomic(output_dir / "execution.json", index)
    return index


def _row_command(row: dict[str, Any], *, live_execution: str, output_dir: Path) -> list[str] | None:
    mode = row["execution_mode"]
    if live_execution == "blocked" and mode == "manual_live_only":
        return None
    use_live = live_execution == "run" and mode in {
        "manual_live_only",
        "deterministic_and_manual_live",
    }
    engine_key = "live_agent_engine" if use_live else "agent_engine"
    profile_key = "live_provider_profile" if use_live else "provider_profile"
    engine = row.get(engine_key) or (row.get("agent_engine") if use_live else None)
    if not isinstance(engine, str) or not engine:
        return None
    command = [
        sys.executable,
        "-m",
        "roboclaws.evals.cli",
        f"suite={row['suite']}",
        f"budget={row['budget']}",
        f"agent_engine={engine}",
        f"output_dir={output_dir / 'evals'}",
    ]
    profile = row.get(profile_key) or (row.get("provider_profile") if use_live else None)
    if isinstance(profile, str) and profile:
        command.append(f"provider_profile={profile}")
    if use_live:
        command.extend(("live_execution=run", f"live_timeout_s={row['timeout_s']}"))
    return command


def _row_execution_identity(row: dict[str, Any], *, live_execution: str) -> dict[str, Any]:
    use_live = live_execution == "run" and row["execution_mode"] in {
        "manual_live_only",
        "deterministic_and_manual_live",
    }
    engine_key = "live_agent_engine" if use_live else "agent_engine"
    profile_key = "live_provider_profile" if use_live else "provider_profile"
    if row["execution_mode"] == "manual_live_only" and live_execution == "blocked":
        # Manual-live rows keep their canonical provider identity in the main
        # fields; older manifests may still carry the live_* aliases.
        engine_key = "live_agent_engine" if row.get("live_agent_engine") else "agent_engine"
        profile_key = (
            "live_provider_profile" if row.get("live_provider_profile") else "provider_profile"
        )
    return {
        "agent_engine": row.get(engine_key) or (row.get("agent_engine") if use_live else None),
        "provider_profile": row.get(profile_key)
        or (row.get("provider_profile") if use_live else None),
    }


def derive_row(
    row: dict[str, Any],
    results: dict[str, Any] | None,
    *,
    source: str | None = None,
    missing_reason: str = "results_unavailable",
    execution_identity: dict[str, Any] | None = None,
) -> dict[str, Any]:
    aggregate = results.get("aggregate", {}) if isinstance(results, dict) else {}
    if not isinstance(aggregate, dict):
        aggregate = {}
    if results is None:
        status = "not_run" if missing_reason == "live_execution_not_requested" else "blocked"
        reason = missing_reason
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
    elif not aggregate.get("total"):
        status, reason = "blocked", "incomplete_attempt"
    else:
        status, reason = "passed", None
    metrics = {
        key: aggregate[key]
        for key in ALLOWED_METRICS
        if key in aggregate and isinstance(aggregate[key], (int, float))
    }
    identities = results.get("results", []) if isinstance(results, dict) else []
    canonical_identity = (
        identities[0].get("identity", {})
        if isinstance(identities, list) and identities and isinstance(identities[0], dict)
        else {}
    )
    selected_identity = execution_identity or {}
    result = {
        "id": row["id"],
        "suite": row["suite"],
        "version": row["version"],
        "sample_ids": list(row.get("sample_ids") or []),
        "agent_engine": canonical_identity.get("agent_engine")
        or selected_identity.get("agent_engine"),
        "provider_profile": canonical_identity.get("provider_profile")
        or selected_identity.get("provider_profile"),
        "evidence_lane": canonical_identity.get("evidence_lane") or row.get("evidence_lane"),
        "status": status,
        "reason": reason,
        "metrics": metrics,
    }
    if source:
        result["source_artifact"] = Path(source).name
    artifacts = results.get("artifacts", {}) if isinstance(results, dict) else {}
    if isinstance(artifacts, dict) and isinstance(artifacts.get("eval_report"), str):
        result["report_artifact"] = Path(artifacts["eval_report"]).name
    return result


def build_summary(
    manifest: dict[str, Any],
    rows: list[dict[str, Any]],
    *,
    commit: str,
    run_url: str,
    artifact_url: str | None = None,
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
                "artifact_url": artifact_url,
                "row": item,
            }
    summary = {
        "schema": SCHEMA,
        "manifest_digest": manifest_digest(manifest),
        "attempted_at": now,
        "commit": commit,
        "run_url": run_url,
        "artifact_url": artifact_url,
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
        "| Capability | Status | Reason | Report | Last successful evidence |",
        "| --- | --- | --- | --- | --- |",
    ]
    successes = summary.get("last_success", {})
    for row in summary["rows"]:
        success = successes.get(row["id"], {})
        last = success.get("attempted_at", "none")
        report = row.get("report_artifact") or "unavailable"
        report_link = (
            f"[{report}]({summary['artifact_url']})"
            if report != "unavailable" and summary.get("artifact_url")
            else report
        )
        lines.append(
            f"| {row['id']} | {row['status']} | {row.get('reason') or '-'} | "
            f"{report_link} | {last} |"
        )
    lines.extend(("", f"[Actions run]({summary['run_url']})", ""))
    if summary.get("artifact_url"):
        lines.extend((f"[Canonical artifacts]({summary['artifact_url']})", ""))
    lines.extend(
        (
            "Artifact drilldown is retained by GitHub Actions and becomes unavailable "
            "after retention expires.",
            "",
        )
    )
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
    parser.add_argument("--commit")
    parser.add_argument("--run-url")
    parser.add_argument("--artifact-url")
    parser.add_argument("--result", action="append", default=[], metavar="ROW_ID=PATH")
    parser.add_argument("--execution-index", type=Path)
    parser.add_argument("--execute", action="store_true")
    parser.add_argument("--live-execution", choices=("blocked", "run"), default="blocked")
    parser.add_argument("--previous", type=Path)
    args = parser.parse_args(argv)
    manifest = validate_manifest(json.loads(args.manifest.read_text(encoding="utf-8")))
    if args.execute:
        execute_manifest(manifest, output_dir=args.output, live_execution=args.live_execution)
        return 0
    if not args.commit or not args.run_url:
        parser.error("--commit and --run-url are required when building a summary")
    execution: dict[str, Any] = {}
    if args.execution_index and args.execution_index.is_file():
        execution = json.loads(args.execution_index.read_text(encoding="utf-8"))
    indexed_results = execution.get("results", {})
    result_paths = dict(indexed_results) if isinstance(indexed_results, dict) else {}
    result_paths.update(dict(item.split("=", 1) for item in args.result))
    attempt_reasons = {
        item["id"]: item.get("reason") or "results_unavailable"
        for item in execution.get("attempts", [])
        if isinstance(item, dict) and isinstance(item.get("id"), str)
    }
    attempt_identities = {
        item["id"]: {
            "agent_engine": item.get("agent_engine"),
            "provider_profile": item.get("provider_profile"),
        }
        for item in execution.get("attempts", [])
        if isinstance(item, dict) and isinstance(item.get("id"), str)
    }
    rows = []
    for row in manifest["rows"]:
        path_value = result_paths.get(row["id"])
        try:
            payload = (
                json.loads(Path(path_value).read_text(encoding="utf-8")) if path_value else None
            )
        except (OSError, json.JSONDecodeError):
            payload = None
            attempt_reasons[row["id"]] = "results_malformed"
        rows.append(
            derive_row(
                row,
                payload,
                source=path_value,
                missing_reason=attempt_reasons.get(row["id"], "results_unavailable"),
                execution_identity=attempt_identities.get(row["id"]),
            )
        )
    previous = None
    if args.previous and args.previous.is_file():
        previous = json.loads(args.previous.read_text(encoding="utf-8"))
    summary = build_summary(
        manifest,
        rows,
        commit=args.commit,
        run_url=args.run_url,
        artifact_url=args.artifact_url,
        previous=previous,
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
