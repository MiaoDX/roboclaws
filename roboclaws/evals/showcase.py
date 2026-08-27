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
        _validate_manifest_row_budgets(row)
        suite, samples = load_suite(row["suite"])
        canonical_suite_id = row.get("canonical_suite_id", row["id"])
        if suite.suite_id != canonical_suite_id or suite.version != row["version"]:
            raise ValueError(f"showcase row {row['id']} does not match canonical suite identity")
        _validate_manifest_row_selection(row, samples)
    return manifest


def _validate_manifest_row_budgets(row: dict[str, Any]) -> None:
    for budget_key in ("timeout_s", "stall_timeout_s"):
        value = row.get(budget_key)
        if value is not None and (not isinstance(value, (int, float)) or value <= 0):
            raise ValueError(f"showcase row {row['id']} has invalid {budget_key}")


def _validate_manifest_row_selection(row: dict[str, Any], samples: list[Any]) -> None:
    selected_sample_id = row.get("sample_id")
    expected_sample_ids = (
        [selected_sample_id]
        if isinstance(selected_sample_id, str) and selected_sample_id
        else [sample.sample_id for sample in samples]
    )
    if expected_sample_ids != row["sample_ids"]:
        raise ValueError(f"showcase row {row['id']} does not match canonical sample ids")
    if not selected_sample_id:
        return
    sample = next((sample for sample in samples if sample.sample_id == selected_sample_id), None)
    if sample is None:
        raise ValueError(f"showcase row {row['id']} selects an unknown sample")
    repetition_index = row.get("repetition_index")
    if repetition_index is not None and (
        not isinstance(repetition_index, int)
        or repetition_index < 0
        or repetition_index >= sample.trial_count
    ):
        raise ValueError(f"showcase row {row['id']} has invalid repetition_index")


def execute_manifest(
    manifest: dict[str, Any],
    *,
    output_dir: Path,
    live_execution: str,
    row_ids: set[str] | None = None,
) -> dict[str, Any]:
    """Run manifest rows serially through the canonical eval CLI without retries."""
    validate_manifest(manifest)
    if live_execution not in {"blocked", "run"}:
        raise ValueError("live_execution must be blocked or run")
    output_dir.mkdir(parents=True, exist_ok=True)
    results: dict[str, str] = {}
    attempts: list[dict[str, Any]] = []
    for row in manifest["rows"]:
        if row_ids is not None and row["id"] not in row_ids:
            continue
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
                timeout=int(row["timeout_s"]) + 30,
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
        command.extend(
            (
                "live_execution=run",
                f"live_timeout_s={row['timeout_s']}",
                f"live_stall_timeout_s={row.get('stall_timeout_s', row['timeout_s'])}",
            )
        )
    if isinstance(row.get("sample_id"), str) and row["sample_id"]:
        command.append(f"sample_id={row['sample_id']}")
    if isinstance(row.get("repetition_index"), int):
        command.append(f"repetition_index={row['repetition_index']}")
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
    report_href: str | None = None,
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
        if report_href:
            result["report_href"] = report_href
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
        report_link = f"[{report}]({row['report_href']})" if row.get("report_href") else report
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
    rows = summary["rows"]
    status_counts = {
        status: sum(row["status"] == status for row in rows)
        for status in ("passed", "failed", "blocked", "not_run")
    }
    table_rows = "".join(_render_html_row(summary, row) for row in rows)
    attempted_at = html.escape(str(summary["attempted_at"]))
    commit = html.escape(str(summary["commit"]))
    run_url = html.escape(str(summary["run_url"]), quote=True)
    artifact_url = html.escape(str(summary.get("artifact_url") or ""), quote=True)
    artifact_link = (
        f'<a class="button secondary" href="{artifact_url}">Canonical artifacts</a>'
        if artifact_url
        else ""
    )
    return f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Roboclaws capability showcase</title>
  <style>
    :root {{ color-scheme: light; --ink:#18212b; --muted:#5f6b76; --line:#d8dee4;
      --surface:#fff; --canvas:#f4f6f8; --green:#157347; --green-bg:#e8f5ee;
      --red:#b42318; --red-bg:#fcebea; --amber:#8a5700; --amber-bg:#fff4d6;
      --gray:#56616c; --gray-bg:#edf0f2; --accent:#075985; }}
    * {{ box-sizing:border-box; }}
    body {{ margin:0; background:var(--canvas); color:var(--ink);
      font:15px/1.5 system-ui,-apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif; }}
    main {{ width:min(1120px,calc(100% - 32px)); margin:40px auto 64px; }}
    header {{ display:flex; justify-content:space-between; gap:24px; align-items:flex-end;
      padding-bottom:24px; border-bottom:1px solid var(--line); }}
    h1 {{ margin:0 0 6px; font-size:30px; line-height:1.2; letter-spacing:0; }}
    p {{ margin:0; color:var(--muted); }}
    .actions {{ display:flex; gap:8px; flex-wrap:wrap; }}
    .button {{ display:inline-flex; align-items:center; min-height:36px; padding:7px 12px;
      border:1px solid var(--accent); border-radius:6px; background:var(--accent); color:#fff;
      text-decoration:none; font-weight:600; white-space:nowrap; }}
    .button.secondary {{ background:var(--surface); color:var(--accent); }}
    .summary {{ display:grid; grid-template-columns:repeat(4,minmax(0,1fr)); gap:12px;
      margin:24px 0; }}
    .metric {{ padding:14px 16px; border:1px solid var(--line); border-radius:6px;
      background:var(--surface); }}
    .metric strong {{ display:block; font-size:24px; line-height:1.1; }}
    .metric span {{ color:var(--muted); }}
    .panel {{ overflow:hidden; border:1px solid var(--line); border-radius:6px;
      background:var(--surface); }}
    table {{ width:100%; min-width:1040px; border-collapse:collapse; }}
    th,td {{ padding:13px 14px; border-bottom:1px solid var(--line); text-align:left;
      vertical-align:top; }}
    th {{ background:#f8f9fa; color:var(--muted); font-size:12px; text-transform:uppercase; }}
    tr:last-child td {{ border-bottom:0; }}
    code {{ font:13px ui-monospace,SFMono-Regular,Consolas,monospace; overflow-wrap:anywhere; }}
    td code {{ white-space:nowrap; }}
    td:last-child {{ white-space:nowrap; }}
    .status {{ display:inline-block; min-width:72px; padding:3px 8px; border-radius:999px;
      text-align:center; font-size:12px; font-weight:700; }}
    .passed {{ color:var(--green); background:var(--green-bg); }}
    .failed {{ color:var(--red); background:var(--red-bg); }}
    .blocked {{ color:var(--amber); background:var(--amber-bg); }}
    .not_run {{ color:var(--gray); background:var(--gray-bg); }}
    td a {{ color:var(--accent); }}
    footer {{ display:flex; justify-content:space-between; gap:16px; margin-top:16px;
      color:var(--muted); font-size:13px; }}
    @media (max-width:760px) {{
      main {{ width:min(100% - 20px,1120px); margin-top:24px; }}
      header {{ display:block; }} .actions {{ margin-top:16px; }}
      .summary {{ grid-template-columns:repeat(2,minmax(0,1fr)); }}
      .panel {{ overflow:visible; border:0; background:transparent; }}
      table,tbody,tr,td {{ display:block; width:100%; min-width:0; }}
      thead {{ display:none; }}
      tr {{ margin-bottom:10px; border:1px solid var(--line); border-radius:6px;
        background:var(--surface); overflow:hidden; }}
      td {{ display:grid; grid-template-columns:92px minmax(0,1fr); gap:10px; padding:9px 12px;
        border-bottom:1px solid var(--line); }}
      td::before {{ content:attr(data-label); color:var(--muted); font-size:11px;
        font-weight:700; text-transform:uppercase; }}
      td code,td:last-child {{ white-space:normal; overflow-wrap:anywhere; }}
      td .status {{ justify-self:start; }}
      footer {{ display:block; }} footer span {{ display:block; margin-top:4px; }}
    }}
  </style>
</head>
<body>
  <main>
    <header>
      <div><h1>Roboclaws capability showcase</h1>
        <p>Latest advisory evidence from model-backed and deterministic household runs.</p></div>
      <div class="actions">
        <a class="button" href="{run_url}">View Actions run</a>{artifact_link}
      </div>
    </header>
    <section class="summary" aria-label="Status summary">
      <div class="metric"><strong>{status_counts["passed"]}</strong><span>Passed</span></div>
      <div class="metric"><strong>{status_counts["failed"]}</strong><span>Failed</span></div>
      <div class="metric"><strong>{status_counts["blocked"]}</strong><span>Blocked</span></div>
      <div class="metric"><strong>{status_counts["not_run"]}</strong><span>Not run</span></div>
    </section>
    <section class="panel">
      <table>
        <thead><tr><th>Capability</th><th>Provider</th><th>Status</th><th>Reason</th>
          <th>Evidence</th><th>Last success</th></tr></thead>
        <tbody>{table_rows}</tbody>
      </table>
    </section>
    <footer><span>Advisory evidence only; this showcase is not a merge gate.</span>
      <span>Attempted {attempted_at} at <code>{commit}</code></span></footer>
  </main>
</body>
</html>
"""


def _render_html_row(summary: dict[str, Any], row: dict[str, Any]) -> str:
    status = str(row["status"])
    capability = html.escape(str(row["id"]))
    provider = html.escape(str(row.get("provider_profile") or "deterministic"))
    reason = html.escape(str(row.get("reason") or "-"))
    report = row.get("report_artifact")
    evidence = "Unavailable"
    if report and row.get("report_href"):
        safe_url = html.escape(str(row["report_href"]), quote=True)
        evidence = f'<a href="{safe_url}">{html.escape(str(report))}</a>'
    last_success = summary.get("last_success", {}).get(row["id"], {}).get("attempted_at", "None")
    status_label = html.escape(status.replace("_", " ").title())
    return (
        f'<tr><td data-label="Capability"><code>{capability}</code></td>'
        f'<td data-label="Provider"><code>{provider}</code></td>'
        f'<td data-label="Status"><span class="status {status}">{status_label}</span></td>'
        f'<td data-label="Reason">{reason}</td><td data-label="Evidence">{evidence}</td>'
        f'<td data-label="Last success">{html.escape(str(last_success))}</td></tr>'
    )


def _published_report_href(execution_path: Path, result_path: str) -> str | None:
    try:
        relative_result = Path(result_path).relative_to(execution_path.parent)
    except (TypeError, ValueError):
        return None
    if not relative_result.parts or relative_result.parts[0] != "evals":
        return None
    return (
        Path("reports") / execution_path.parent.name / relative_result.with_name("eval_report.html")
    ).as_posix()


def _load_execution_indexes(
    paths: list[Path],
) -> tuple[list[dict[str, Any]], dict[str, str], dict[str, str]]:
    sources = [
        (path, json.loads(path.read_text(encoding="utf-8"))) for path in paths if path.is_file()
    ]
    executions = [execution for _, execution in sources]
    result_paths: dict[str, str] = {}
    report_hrefs: dict[str, str] = {}
    for execution_path, execution in sources:
        indexed_results = execution.get("results", {})
        if not isinstance(indexed_results, dict):
            continue
        result_paths.update(indexed_results)
        for row_id, result_path in indexed_results.items():
            report_href = _published_report_href(execution_path, result_path)
            if report_href:
                report_hrefs[row_id] = report_href
    return executions, result_paths, report_hrefs


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Build the sanitized capability showcase.")
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--commit")
    parser.add_argument("--run-url")
    parser.add_argument("--artifact-url")
    parser.add_argument("--result", action="append", default=[], metavar="ROW_ID=PATH")
    parser.add_argument("--execution-index", type=Path, action="append", default=[])
    parser.add_argument("--row-id", action="append", default=[])
    parser.add_argument("--execute", action="store_true")
    parser.add_argument("--live-execution", choices=("blocked", "run"), default="blocked")
    parser.add_argument("--previous", type=Path)
    args = parser.parse_args(argv)
    manifest = validate_manifest(json.loads(args.manifest.read_text(encoding="utf-8")))
    if args.execute:
        requested_rows = set(args.row_id) if args.row_id else None
        if requested_rows is not None:
            known_rows = {row["id"] for row in manifest["rows"]}
            unknown_rows = requested_rows - known_rows
            if unknown_rows:
                parser.error(f"unknown --row-id values: {', '.join(sorted(unknown_rows))}")
        execute_manifest(
            manifest,
            output_dir=args.output,
            live_execution=args.live_execution,
            row_ids=requested_rows,
        )
        return 0
    if not args.commit or not args.run_url:
        parser.error("--commit and --run-url are required when building a summary")
    executions, result_paths, report_hrefs = _load_execution_indexes(args.execution_index)
    result_paths.update(dict(item.split("=", 1) for item in args.result))
    attempt_reasons = {
        item["id"]: item.get("reason") or "results_unavailable"
        for execution in executions
        for item in execution.get("attempts", [])
        if isinstance(item, dict) and isinstance(item.get("id"), str)
    }
    attempt_identities = {
        item["id"]: {
            "agent_engine": item.get("agent_engine"),
            "provider_profile": item.get("provider_profile"),
        }
        for execution in executions
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
                report_href=report_hrefs.get(row["id"]),
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
