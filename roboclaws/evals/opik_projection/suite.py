"""Closed projection of one persisted repo-native eval suite into Opik."""

from __future__ import annotations

import hashlib
import json
import os
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from roboclaws.core.json_sources import read_json_object
from roboclaws.evals.models import EvalResult, EvalSample, EvalSuite
from roboclaws.evals.opik_projection.client import (
    OpikHttp,
    _atomic_write_json,
    project_snapshot,
    write_receipt,
)
from roboclaws.evals.opik_projection.harness import (
    PROJECTION_SCHEMA,
    ProjectionError,
    _digest_json,
    _load_native_spans,
    _privacy_scan,
    _projection_key,
)
from roboclaws.evals.suite_loading import REPO_ROOT, load_suite, path_token

AUTOMATIC_DEADLINE_S = 60.0
RECEIPT_NAME = "opik_projection.json"


def project_completed_eval_to_opik(
    *,
    suite_ref: str,
    eval_results_path: Path,
    environ: Mapping[str, str] | None = None,
) -> dict[str, object]:
    """Fail-open automatic projection after canonical suite persistence."""
    values = os.environ if environ is None else environ
    endpoint = values.get("ROBOCLAWS_OPIK_ENDPOINT", "").strip()
    output_path = eval_results_path.with_name(RECEIPT_NAME)
    if not endpoint:
        receipt = _base_receipt("disabled", "endpoint_not_configured", eval_results_path)
        _atomic_write_json(output_path, receipt)
        return _summary(output_path, receipt)
    try:
        snapshot = build_suite_projection_snapshot(suite_ref, eval_results_path)
        result = project_snapshot(snapshot, OpikHttp(endpoint, deadline_s=AUTOMATIC_DEADLINE_S))
        write_receipt(snapshot, result, endpoint, eval_results_path.parent)
        receipt = read_json_object(output_path, label="Opik projection receipt")
    except Exception as exc:  # noqa: BLE001 - projection cannot change the eval outcome
        reason = _failure_reason(exc)
        privacy_state = "failed" if "privacy denial scan failed" in str(exc) else "unavailable"
        receipt = _base_receipt("unavailable", reason, eval_results_path, privacy_state)
        _atomic_write_json(output_path, receipt)
    return _summary(output_path, receipt)


def project_eval_to_opik(overrides: dict[str, str]) -> dict[str, object]:
    """Repair one explicitly named persisted suite bundle without running evaluation."""
    values = dict(overrides)
    suite_ref = values.pop("suite", "smoke_regression")
    results_ref = values.pop("eval_results", "")
    endpoint = values.pop("endpoint", os.environ.get("ROBOCLAWS_OPIK_ENDPOINT", ""))
    deadline_s = float(values.pop("deadline_s", str(AUTOMATIC_DEADLINE_S)))
    if values:
        raise ValueError(f"unsupported opik-project override(s): {', '.join(sorted(values))}")
    if not results_ref:
        raise ValueError("opik-project requires eval_results=<path>")
    path = Path(results_ref)
    snapshot = build_suite_projection_snapshot(suite_ref, path)
    result = project_snapshot(snapshot, OpikHttp(endpoint, deadline_s=deadline_s))
    receipt_path = write_receipt(snapshot, result, endpoint, path.resolve().parent)
    receipt = read_json_object(receipt_path, label="Opik projection receipt")
    return _summary(receipt_path, receipt)


def build_suite_projection_snapshot(suite_ref: str, eval_results_path: Path) -> dict[str, Any]:
    path = eval_results_path if eval_results_path.is_absolute() else REPO_ROOT / eval_results_path
    raw = path.read_bytes()
    source_digest = hashlib.sha256(raw).hexdigest()
    payload = json.loads(raw)
    if not isinstance(payload, dict):
        raise ProjectionError("eval_results must contain an object")
    suite, samples = load_suite(suite_ref)
    if payload.get("suite") != suite.to_dict():
        raise ProjectionError("eval_results does not match the exact suite release")
    rows = payload.get("results")
    if not isinstance(rows, list):
        raise ProjectionError("eval_results must contain a results list")
    results = [EvalResult.from_mapping(_mapping(row)) for row in rows]
    sample_by_id = {sample.sample_id: sample for sample in samples}
    public_samples = [_public_sample(sample) for sample in samples]
    item_identity_digest = _digest_json(
        {"suite_id": suite.suite_id, "suite_version": suite.version, "samples": public_samples}
    )
    source_files: dict[str, Any] = {}
    items: list[dict[str, Any]] = []
    traces: list[dict[str, Any]] = []
    configurations: set[str] = set()
    public_result_identities: list[dict[str, Any]] = []
    for result in results:
        identity = _public_result_identity(result, suite, sample_by_id)
        public_result_identities.append(identity)
        result_digest = _digest_json(
            {"identity": identity, "status": result.status, "failure_class": result.failure_class}
        )
        # A Dataset row represents one trial. Regrading that trial updates the
        # row through the deterministic PUT instead of appending a stale row.
        item_key = _projection_key("item", item_identity_digest, _digest_json(identity))
        spans = _result_spans(result, path.parent, source_files)
        fidelity = "native_span_trace" if spans else "experiment_only"
        metadata = {
            **identity,
            "failure_class": result.failure_class,
            "outcome": result.status,
            "trace_fidelity": fidelity,
        }
        items.append(
            {
                "projection_key": item_key,
                "metadata": metadata,
                "scores": _public_scores(result),
            }
        )
        configuration = _digest_json(
            {key: identity[key] for key in ("agent_engine", "provider_profile", "model")}
        )
        configurations.add(configuration)
        if spans:
            traces.append(
                {
                    "projection_key": _projection_key("trace", result_digest),
                    "item_projection_key": item_key,
                    "source_trace_id": spans[0]["trace_id"],
                    "spans": spans,
                }
            )
    dataset_digest = _digest_json(
        {
            "item_identity_schema": "trial-identity-v2",
            "suite_id": suite.suite_id,
            "suite_version": suite.version,
            "samples": public_samples,
            "projected_result_identities": public_result_identities,
        }
    )
    experiment_digest = _digest_json(
        {
            "dataset_digest": dataset_digest,
            "source_digest": source_digest,
            "configurations": sorted(configurations),
            "required_graders": list(suite.required_graders),
        }
    )
    snapshot = {
        "schema": PROJECTION_SCHEMA,
        "projection_purpose": "repo_native_eval_projection",
        "candidate_status": "canonical_local_evidence",
        "source_manifest_sha256": source_digest,
        "project": {"name": "roboclaws-eval", "projection_key": "roboclaws-eval"},
        "dataset": {
            "name": f"{path_token(suite.suite_id)}-{suite.version}-{dataset_digest[:16]}",
            "projection_key": _projection_key("dataset", dataset_digest),
        },
        "experiment": {
            "name": f"{path_token(suite.suite_id)}-{experiment_digest[:16]}",
            "projection_key": _projection_key("experiment", experiment_digest),
        },
        "items": items,
        "traces": traces,
        "trace_coverage": {
            "native_span_trace": len(traces),
            "experiment_only": len(items) - len(traces),
        },
        "source_files": [{"relative_path": path.name, "sha256": source_digest}],
    }
    findings = _privacy_scan(snapshot)
    if findings:
        raise ProjectionError("privacy denial scan failed: " + ", ".join(findings[:8]))
    snapshot["privacy_scan"] = {"state": "passed", "finding_count": 0}
    snapshot["snapshot_sha256"] = _digest_json(snapshot)
    return snapshot


def _public_sample(sample: EvalSample) -> dict[str, str]:
    return {
        "sample_id": sample.sample_id,
        "sample_version": sample.version,
        "prompt_sha256": hashlib.sha256(sample.prompt.encode()).hexdigest(),
    }


def _public_result_identity(
    result: EvalResult, suite: EvalSuite, samples: dict[str, EvalSample]
) -> dict[str, Any]:
    identity = result.identity
    sample_id = str(identity.get("sample_id") or "")
    sample = samples.get(sample_id)
    if sample is None:
        raise ProjectionError("eval result sample is not part of the exact suite release")
    expected = {
        "suite_id": suite.suite_id,
        "suite_version": suite.version,
        "sample_version": sample.version,
    }
    if any(identity.get(key) != value for key, value in expected.items()):
        raise ProjectionError("eval result identity does not match the exact suite release")
    allowed = (
        "suite_id",
        "suite_version",
        "sample_id",
        "sample_version",
        "trial_id",
        "repetition_index",
        "surface",
        "intent",
        "preset",
        "world",
        "backend",
        "evidence_lane",
        "camera_labeler",
        "scenario_setup",
        "seed",
        "agent_engine",
        "runner_class",
        "provider_profile",
        "model",
        "skill_name",
    )
    return {key: identity[key] for key in allowed if key in identity}


def _result_spans(
    result: EvalResult, source_root: Path, source_files: dict[str, Any]
) -> list[dict[str, Any]]:
    run_dir = result.artifacts.get("run_dir")
    if not isinstance(run_dir, str) or not run_dir:
        return []
    run_path = Path(run_dir)
    if not run_path.is_absolute():
        run_path = REPO_ROOT / run_path
    try:
        relative = run_path.resolve().relative_to(source_root.resolve()).as_posix()
    except ValueError:
        return []
    return _load_native_spans(source_root, relative, source_files)


def _public_scores(result: EvalResult) -> dict[str, int | float]:
    scores: dict[str, int | float] = {"roboclaws.passed": int(result.status == "passed")}
    for source, target in (
        ("tool_call_count", "roboclaws.tool_call_count"),
        ("wall_time_s", "roboclaws.wall_time_s"),
        ("private_truth_leak_count", "roboclaws.private_truth_leak_count"),
        ("trajectory_policy_violation_count", "roboclaws.trajectory_policy_violation_count"),
    ):
        value = result.metrics.get(source)
        if isinstance(value, (int, float)) and not isinstance(value, bool):
            scores[target] = value
    return scores


def _base_receipt(
    state: str, reason: str, source: Path, privacy_state: str = "unavailable"
) -> dict[str, Any]:
    digest = hashlib.sha256(source.read_bytes()).hexdigest() if source.is_file() else "unavailable"
    return {
        "schema": PROJECTION_SCHEMA,
        "state": state,
        "reason": reason,
        "source_manifest_sha256": digest,
        "privacy_scan": {"state": privacy_state, "finding_count": 0},
    }


def _failure_reason(exc: Exception) -> str:
    message = str(exc).lower()
    if "deadline expired" in message:
        return "projection_deadline_expired"
    if "endpoint" in message or "loopback" in message:
        return "invalid_projection_configuration"
    if isinstance(exc, (OSError, TimeoutError)):
        return "opik_unavailable"
    return "opik_projection_failed"


def _summary(path: Path, receipt: dict[str, Any]) -> dict[str, object]:
    return {"receipt": str(path), "state": receipt["state"], "reason": receipt["reason"]}


def _mapping(value: Any) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ProjectionError("eval result row must be an object")
    return value
