#!/usr/bin/env python3
"""Map one terminal Eval Harness decision report to closed Opik objects."""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import re
import sys
from collections.abc import Mapping
from pathlib import Path
from typing import Any, NamedTuple

PROJECTION_SCHEMA = "roboclaws_opik_eval_projection_v2"
PROJECT_NAME = "roboclaws-eval"
AUTOMATIC_DEADLINE_S = 60.0
RECEIPT_NAME = "opik_projection.json"
FORBIDDEN_KEYS = {
    "command",
    "command_display",
    "endpoint",
    "image",
    "map",
    "private_evaluation",
    "prompt",
    "tool_body",
    "trace",
}
SPAN_FIELDS = {
    "duration_s",
    "ended_at",
    "event",
    "model",
    "parent_id",
    "provider_profile",
    "runtime",
    "schema",
    "span_id",
    "span_name",
    "span_type",
    "started_at",
    "status",
    "trace_id",
    "ts_epoch",
}
AUXILIARY_SPAN_EVENTS = {
    "model_racing_arm_finish",
    "model_racing_arm_start",
    "model_service_attempt",
    "model_service_success",
}


class ProjectionError(ValueError):
    """Raised when the closed projection boundary cannot be proven."""


class SourceFile(NamedTuple):
    relative_path: str
    sha256: str


def _digest_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _digest_json(value: Any) -> str:
    encoded = json.dumps(value, sort_keys=True, separators=(",", ":")).encode()
    return _digest_bytes(encoded)


def _projection_key(kind: str, source_digest: str, *parts: str) -> str:
    digest = _digest_json([PROJECTION_SCHEMA, source_digest, kind, *parts])
    return f"rc-{kind}-{digest[:32]}"


def _read_json(path: Path) -> tuple[dict[str, Any], bytes]:
    raw = path.read_bytes()
    try:
        value = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise ProjectionError(f"malformed JSON: {path}") from exc
    if not isinstance(value, dict):
        raise ProjectionError(f"expected JSON object: {path}")
    return value, raw


def _resolve_relative(root: Path, value: str) -> Path:
    path = Path(value)
    if path.is_absolute() or ".." in path.parts:
        raise ProjectionError(f"artifact path must be relative and traversal-free: {value}")
    resolved = (root / path).resolve()
    if not resolved.is_relative_to(root.resolve()):
        raise ProjectionError(f"artifact escapes source root: {value}")
    return resolved


def _safe_number(value: Any) -> int | float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    if isinstance(value, float) and not math.isfinite(value):
        return None
    return value


def _row_axes(manifest: dict[str, Any]) -> dict[str, dict[str, str]]:
    result: dict[str, dict[str, str]] = {}
    for row in manifest.get("rows", []):
        if not isinstance(row, dict) or not isinstance(row.get("row_id"), str):
            raise ProjectionError("manifest row identity is malformed")
        axes = row.get("axes", {})
        result[row["row_id"]] = {
            key: value
            for key, value in axes.items()
            if key in {"agent_engine", "intent", "provider_profile", "suite"}
            and isinstance(value, str)
        }
    return result


def _load_native_spans(
    source_root: Path, run_dir: str, source_files: dict[str, SourceFile]
) -> list[dict[str, Any]]:
    run_path = _resolve_relative(source_root, run_dir)
    span_path = run_path / "openai-agents-spans.jsonl"
    if not span_path.is_file():
        return []
    relative = span_path.relative_to(source_root).as_posix()
    raw = span_path.read_bytes()
    source_files[relative] = SourceFile(relative, _digest_bytes(raw))
    starts: dict[str, dict[str, Any]] = {}
    ordered: list[str] = []
    for line_number, line in enumerate(raw.splitlines(), 1):
        try:
            record = json.loads(line)
        except json.JSONDecodeError as exc:
            raise ProjectionError(
                f"malformed sanitized span line {relative}:{line_number}"
            ) from exc
        if record.get("schema") != "openai_agents_sanitized_span_v1":
            raise ProjectionError(f"unexpected sanitized span schema: {relative}:{line_number}")
        if record.get("event") not in {
            "span_start",
            "span_end",
            "trace_start",
            "trace_end",
            *AUXILIARY_SPAN_EVENTS,
        }:
            raise ProjectionError(f"unexpected sanitized span event: {relative}:{line_number}")
        span_id = record.get("span_id")
        if not isinstance(span_id, str):
            continue
        projected = {key: record[key] for key in SPAN_FIELDS if key in record}
        if span_id not in starts:
            starts[span_id] = projected
            ordered.append(span_id)
        else:
            starts[span_id].update(projected)
    spans = [starts[span_id] for span_id in ordered]
    for span in spans:
        required = {"span_id", "trace_id", "started_at", "span_type"}
        if not required.issubset(span):
            raise ProjectionError(
                f"sanitized span lacks required identity/timing fields: {relative}"
            )
    return spans


def _privacy_scan(value: Any, path: str = "$") -> list[str]:
    findings: list[str] = []
    if isinstance(value, dict):
        for key, child in value.items():
            lowered = key.lower()
            if lowered in FORBIDDEN_KEYS or any(
                token in lowered for token in ("secret", "password", "credential")
            ):
                findings.append(f"{path}.{key}:forbidden_key")
            findings.extend(_privacy_scan(child, f"{path}.{key}"))
    elif isinstance(value, list):
        for index, child in enumerate(value):
            findings.extend(_privacy_scan(child, f"{path}[{index}]"))
    elif isinstance(value, str):
        if value.startswith(("http://", "https://")):
            findings.append(f"{path}:endpoint")
        if value.startswith("/") or re.match(r"^[A-Za-z]:[\\/]", value):
            findings.append(f"{path}:absolute_path")
        if re.search(r"\b(?:sk|key)-[A-Za-z0-9_-]{16,}\b", value):
            findings.append(f"{path}:credential_shape")
    return findings


def _validate_source(manifest: dict[str, Any]) -> dict[str, Any]:
    if manifest.get("schema") != "roboclaws_eval_harness_manifest_v1":
        raise ProjectionError("source is not an Eval Harness v1 manifest")
    if manifest.get("candidate_status") not in {"terminal", "terminal_with_failures"}:
        raise ProjectionError("source candidate is not terminal")
    if manifest.get("publication_authorized") is not False:
        raise ProjectionError("source must be an unaccepted terminal candidate")
    report = manifest.get("observability_decision_report")
    if (
        not isinstance(report, dict)
        or report.get("schema") != "roboclaws_observability_decision_report_v1"
    ):
        raise ProjectionError("canonical observability decision report is missing")
    if report.get("state") not in {"ready", "ready_with_limitations"}:
        raise ProjectionError("canonical observability decision report is not ready")
    return report


def _canonical_scores(triage: dict[str, Any], outcome: str) -> dict[str, int | float]:
    scores: dict[str, int | float] = {}
    if outcome in {"passed", "failed", "blocked"}:
        scores["roboclaws.passed"] = int(outcome == "passed")
    for source_key, score_key in (
        ("tool_call_count", "roboclaws.tool_call_count"),
        ("longest_model_call_s", "roboclaws.longest_model_call_s"),
        ("timeout_budget_s", "roboclaws.timeout_budget_s"),
    ):
        number = _safe_number(triage.get(source_key))
        if number is not None:
            scores[score_key] = number
    return scores


def _project_triage(
    report: dict[str, Any],
    axes_by_row: dict[str, dict[str, str]],
    source_root: Path,
    source_digest: str,
    source_files: dict[str, SourceFile],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    items: list[dict[str, Any]] = []
    traces: list[dict[str, Any]] = []
    for triage in report.get("triage", {}).get("rows", []):
        if not isinstance(triage, dict):
            raise ProjectionError("canonical triage row is malformed")
        row_id = triage.get("row_id")
        if not isinstance(row_id, str) or row_id not in axes_by_row:
            raise ProjectionError("canonical triage row has contradictory row identity")
        sample_id = triage.get("sample_id") or "not_applicable"
        trial_id = triage.get("trial_id") or "not_applicable"
        suite_id = triage.get("suite_id") or "not_applicable"
        item_key = _projection_key("item", source_digest, row_id, suite_id, sample_id, trial_id)
        local_artifacts = triage.get("local_artifacts", {})
        run_dir = local_artifacts.get("run_dir") if isinstance(local_artifacts, dict) else None
        spans = (
            _load_native_spans(source_root, run_dir, source_files)
            if isinstance(run_dir, str)
            else []
        )
        fidelity = "native_span_trace" if spans else "experiment_only"
        metadata = {
            "candidate_status": "unaccepted",
            "execution_target": triage.get("execution_target") or "unavailable",
            "failure_class": triage.get("failure_class") or "not_applicable",
            "outcome": triage.get("outcome") or "unavailable",
            "projection_purpose": "historical_candidate_projection",
            "row_id": row_id,
            "sample_id": sample_id,
            "suite_id": suite_id,
            "terminal_reason": triage.get("terminal_reason") or "not_applicable",
            "trace_fidelity": fidelity,
            "trial_id": trial_id,
            **axes_by_row[row_id],
        }
        scores = _canonical_scores(triage, metadata["outcome"])
        items.append({"projection_key": item_key, "metadata": metadata, "scores": scores})
        if spans:
            trace_id = spans[0]["trace_id"]
            if any(span["trace_id"] != trace_id for span in spans):
                raise ProjectionError(
                    f"one trial span file contains multiple trace identities: {row_id}"
                )
            traces.append(
                {
                    "projection_key": _projection_key(
                        "trace", source_digest, row_id, sample_id, trial_id, trace_id
                    ),
                    "item_projection_key": item_key,
                    "source_trace_id": trace_id,
                    "spans": spans,
                }
            )
    return items, traces


def _project_provider_views(report: dict[str, Any], source_digest: str) -> list[dict[str, Any]]:
    provider_views = []
    for index, cohort in enumerate(report.get("provider_comparison", {}).get("cohorts", [])):
        if not isinstance(cohort, dict):
            raise ProjectionError("canonical provider cohort is malformed")
        invariants = cohort.get("invariants", {})
        claims = cohort.get("claims", {})
        metrics = cohort.get("metrics", {})
        copied_metrics = {}
        for name, metric in metrics.items():
            if not isinstance(metric, dict):
                continue
            copied_metrics[name] = {
                "availability": metric.get("availability", "unavailable"),
                "claim_eligibility": metric.get("claim_eligibility", "unavailable"),
                "limitations": metric.get("limitations", []),
                "value": metric.get("value"),
            }
        provider_views.append(
            {
                "projection_key": _projection_key("cohort", source_digest, str(index)),
                "sample_id": invariants.get("sample_id", "unavailable"),
                "treatments": cohort.get("treatments", []),
                "claims": claims,
                "metrics": copied_metrics,
            }
        )
    return provider_views


def build_projection_snapshot(manifest_path: Path) -> dict[str, Any]:
    manifest_path = manifest_path.resolve()
    manifest, raw = _read_json(manifest_path)
    source_digest = _digest_bytes(raw)
    report = _validate_source(manifest)
    source_files = {manifest_path.name: SourceFile(manifest_path.name, source_digest)}
    items, traces = _project_triage(
        report,
        _row_axes(manifest),
        manifest_path.parent,
        source_digest,
        source_files,
    )

    snapshot = {
        "schema": PROJECTION_SCHEMA,
        "projection_purpose": "historical_candidate_projection",
        "candidate_status": "unaccepted",
        "source_manifest_sha256": source_digest,
        "project": {
            "name": PROJECT_NAME,
            "projection_key": _projection_key("project", source_digest),
        },
        "dataset": {
            "name": f"roboclaws-eval-harness-{source_digest[:16]}",
            "projection_key": _projection_key("dataset", source_digest),
        },
        "experiment": {
            "name": "unaccepted-historical-candidate-20260817T072338Z",
            "projection_key": _projection_key("experiment", source_digest),
        },
        "canonical_summary": {
            "capability_health": report["capability_health"],
            "harness_health": report["harness_health"],
            "limitations": report["limitations"],
            "telemetry_coverage": report["telemetry_coverage"],
        },
        "provider_views": _project_provider_views(report, source_digest),
        "items": items,
        "traces": traces,
        "trace_coverage": {
            "native_span_trace": len(traces),
            "experiment_only": len(items) - len(traces),
        },
        "source_files": [
            {"relative_path": source.relative_path, "sha256": source.sha256}
            for source in sorted(source_files.values(), key=lambda item: item.relative_path)
        ],
    }
    findings = _privacy_scan(
        {key: value for key, value in snapshot.items() if key != "source_files"}
    )
    if findings:
        raise ProjectionError("privacy denial scan failed: " + ", ".join(findings[:8]))
    snapshot["privacy_scan"] = {"state": "passed", "finding_count": 0}
    snapshot["snapshot_sha256"] = _digest_json(snapshot)
    return snapshot


def project_completed_harness_to_opik(
    manifest_path: Path,
    *,
    environ: Mapping[str, str] | None = None,
) -> dict[str, object]:
    """Fail-open automatic projection after authoritative terminal publication."""
    from roboclaws.evals.opik_projection.client import (
        OpikHttp,
        _atomic_write_json,
        project_snapshot,
        write_receipt,
    )

    values = os.environ if environ is None else environ
    endpoint = values.get("ROBOCLAWS_OPIK_ENDPOINT", "").strip()
    receipt_path = manifest_path.with_name(RECEIPT_NAME)
    source_digest = _digest_bytes(manifest_path.read_bytes())
    if not endpoint:
        receipt = _automatic_receipt("disabled", "endpoint_not_configured", source_digest)
        _atomic_write_json(receipt_path, receipt)
        return _automatic_summary(receipt_path, receipt)
    try:
        snapshot = build_projection_snapshot(manifest_path)
        result = project_snapshot(snapshot, OpikHttp(endpoint, deadline_s=AUTOMATIC_DEADLINE_S))
        write_receipt(snapshot, result, endpoint, manifest_path.parent)
        receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
    except Exception as exc:  # noqa: BLE001 - observability cannot change publication
        reason = (
            "opik_unavailable"
            if exc.__class__.__name__ == "OpikClientError"
            else "opik_projection_failed"
        )
        receipt = _automatic_receipt("unavailable", reason, source_digest)
        _atomic_write_json(receipt_path, receipt)
    return _automatic_summary(receipt_path, receipt)


def _automatic_receipt(state: str, reason: str, source_digest: str) -> dict[str, object]:
    return {
        "schema": PROJECTION_SCHEMA,
        "state": state,
        "reason": reason,
        "projection_purpose": "historical_candidate_projection",
        "candidate_status": "unaccepted",
        "source_manifest_sha256": source_digest,
    }


def _automatic_summary(path: Path, receipt: dict[str, Any]) -> dict[str, object]:
    return {
        "receipt": str(path),
        "state": str(receipt["state"]),
        "reason": str(receipt["reason"]),
    }


def _parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--manifest", required=True, type=Path)
    parser.add_argument("--endpoint")
    parser.add_argument("--deadline-s", type=float, default=60.0)
    parser.add_argument("--snapshot-output", type=Path)
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(sys.argv[1:] if argv is None else argv)
    snapshot = build_projection_snapshot(args.manifest)
    if args.endpoint:
        from roboclaws.evals.opik_projection.client import OpikHttp, project_snapshot, write_receipt

        result = project_snapshot(snapshot, OpikHttp(args.endpoint, deadline_s=args.deadline_s))
        receipt = write_receipt(snapshot, result, args.endpoint, args.manifest.resolve().parent)
        print(receipt)
        return 0
    output = args.snapshot_output
    if output:
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(json.dumps(snapshot, indent=2, sort_keys=True) + "\n")
    else:
        json.dump(snapshot, sys.stdout, indent=2, sort_keys=True)
        sys.stdout.write("\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
