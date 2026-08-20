"""Pure artifact projection for Eval Harness maintainer decisions."""

from __future__ import annotations

import json
import statistics
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

SCHEMA = "roboclaws_observability_decision_report_v1"
TERMINAL_OUTCOMES = {"passed", "failed", "blocked"}
INELIGIBLE_QUALITY = {"failed", "blocked", "inconclusive", "operator_stopped"}
FORBIDDEN_PATH_PARTS = ("/tmp/roboclaws-cloudml/",)


def build_observability_decision_report(
    manifest: dict[str, Any], *, manifest_path: Path | None = None
) -> dict[str, Any]:
    """Project one explicit harness manifest into deterministic, render-ready data."""
    applicability = _applicability(manifest)
    if applicability is not None:
        return {"schema": SCHEMA, "state": "not_applicable", "reason": applicability}

    root = (manifest_path.parent if manifest_path else Path(str(manifest["output_dir"]))).resolve()
    selected = _report_rows(manifest)
    health = Counter(str(row.get("outcome") or row.get("status") or "unknown") for row in selected)
    eval_rows, triage = _collect_eval_rows(selected, root=root)

    cohorts = _provider_cohorts(eval_rows, manifest=manifest)
    coverage = _coverage(eval_rows, selected)
    limitations = _report_limitations(coverage)

    return {
        "schema": SCHEMA,
        "state": "ready_with_limitations" if limitations else "ready",
        "limitations": sorted(limitations),
        "harness_health": {
            "grain": "selected_harness_row",
            "total": len(selected),
            "passed": health["passed"],
            "failed": health["failed"],
            "blocked": health["blocked"],
            "candidate_status": manifest.get("candidate_status", "not_applicable"),
        },
        "capability_health": _capability_health(eval_rows, manifest=manifest),
        "provider_comparison": {"grain": "provider_treatment_cohort", "cohorts": cohorts},
        "triage": {"grain": "row_suite_sample_trial", "rows": triage},
        "telemetry_coverage": coverage,
    }


def regenerate_observability_decision_report(manifest_path: Path) -> dict[str, Any]:
    """Rebuild the derived object for one explicitly named manifest."""
    manifest = _read_object(manifest_path, "eval harness manifest")
    return build_observability_decision_report(manifest, manifest_path=manifest_path)


def _collect_eval_rows(
    selected: list[dict[str, Any]], *, root: Path
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    eval_rows: list[dict[str, Any]] = []
    triage: list[dict[str, Any]] = []
    for row in selected:
        bundle_path = _attached_file(row, "eval_results.json", root=root)
        if bundle_path is None:
            triage.append(_row_only_triage(row, root=root))
            continue
        bundle = _read_object(bundle_path, "eval results bundle")
        if bundle.get("schema") not in {None, "roboclaws_eval_results_bundle_v1"}:
            raise ValueError(f"{bundle_path}: unsupported eval results schema")
        phoenix_runs = _phoenix_runs(row, bundle_path=bundle_path, root=root)
        trial_ids: set[str] = set()
        for result in bundle.get("results") or []:
            if not isinstance(result, dict):
                raise ValueError(f"{bundle_path}: eval results must contain objects")
            normalized = _normalize_trial(
                row, result, bundle_path=bundle_path, root=root, phoenix_runs=phoenix_runs
            )
            trial_id = normalized["triage"]["trial_id"]
            if not trial_id or trial_id in trial_ids:
                raise ValueError(f"{bundle_path}: missing or duplicate trial identity {trial_id!r}")
            trial_ids.add(trial_id)
            _validate_bundle_identity(bundle, normalized["identity"], bundle_path=bundle_path)
            eval_rows.append(normalized)
            triage.append(normalized["triage"])
    return eval_rows, triage


def _report_limitations(coverage: dict[str, Any]) -> list[str]:
    checks = (
        ("eval_bundle", "some_selected_rows_have_no_eval_bundle"),
        ("model_duration", "model_duration_coverage_incomplete"),
        ("token_usage", "token_usage_coverage_incomplete"),
        ("phoenix_mapping", "phoenix_drilldown_coverage_incomplete"),
    )
    return [
        limitation
        for field, limitation in checks
        if coverage[field]["numerator"] < coverage[field]["denominator"]
    ]


def _applicability(manifest: dict[str, Any]) -> str | None:
    if manifest.get("mode") != "execute":
        return "recommend_manifest"
    execution = manifest.get("execution") if isinstance(manifest.get("execution"), dict) else {}
    shard_id = str(execution.get("shard_id") or manifest.get("shard_id") or "")
    if shard_id and shard_id != "local-main":
        return "worker_shard_manifest"
    selected = _report_rows(manifest)
    if not selected or any(
        str(row.get("outcome") or "") not in TERMINAL_OUTCOMES for row in selected
    ):
        return "nonterminal_manifest"
    return None


def _report_rows(manifest: dict[str, Any]) -> list[dict[str, Any]]:
    execution = manifest.get("execution") if isinstance(manifest.get("execution"), dict) else {}
    scoped_ids = {str(value) for value in execution.get("row_ids") or []}
    rows = [row for row in manifest.get("rows", []) if row.get("selected")]
    return [row for row in rows if str(row.get("row_id")) in scoped_ids] if scoped_ids else rows


def _attached_file(row: dict[str, Any], filename: str, *, root: Path) -> Path | None:
    candidates: list[Path] = []
    for raw in row.get("output_artifacts") or []:
        value = str(raw)
        if not value.endswith(filename) or any(part in value for part in FORBIDDEN_PATH_PARTS):
            continue
        path = Path(value)
        if not path.is_absolute():
            path = Path.cwd() / path
        resolved = path.resolve()
        if resolved.is_relative_to(root) and resolved.is_file():
            candidates.append(resolved)
    if not candidates and filename == "eval_results.json":
        projection = _attached_file(row, "phoenix_projection.json", root=root)
        adjacent = projection.with_name(filename) if projection else None
        if adjacent is not None and adjacent.is_file():
            candidates.append(adjacent)
    if len(candidates) > 1:
        raise ValueError(f"row {row.get('row_id')!r} declares multiple canonical {filename} files")
    return candidates[0] if candidates else None


def _read_object(path: Path, label: str) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(f"{path}: {label} must contain valid JSON") from exc
    if not isinstance(value, dict):
        raise ValueError(f"{path}: {label} must contain a JSON object")
    return value


def _normalize_trial(
    row: dict[str, Any],
    result: dict[str, Any],
    *,
    bundle_path: Path,
    root: Path,
    phoenix_runs: dict[str, str],
) -> dict[str, Any]:
    identity = result.get("identity") if isinstance(result.get("identity"), dict) else {}
    metrics = result.get("metrics") if isinstance(result.get("metrics"), dict) else {}
    graders = result.get("grader_outputs") if isinstance(result.get("grader_outputs"), dict) else {}
    runner = graders.get("runner") if isinstance(graders.get("runner"), dict) else {}
    trial_id = str(identity.get("trial_id") or "")
    run_dir = _bundle_relative_run_dir(result, bundle_path=bundle_path)
    calls = _model_calls(run_dir)
    _validate_model_call_identity(calls, identity, bundle_path=bundle_path)
    prompt_identity = _optional_object(run_dir / "prompt-identity.json" if run_dir else None)
    resolved_dependencies = (
        (graders.get("artifacts") or {}).get("resolved_dependencies")
        if isinstance(graders.get("artifacts"), dict)
        else {}
    ) or {}
    call_count = len(calls)
    duration_values = [
        float(call["duration_s"]) for call in calls if call.get("duration_s") is not None
    ]
    token_fields = (
        "input_tokens",
        "uncached_input_tokens",
        "cached_input_tokens",
        "output_tokens",
        "reasoning_tokens",
    )
    tokens = {
        field: _metric_cell(
            sum(int(call[field]) for call in calls if call.get(field) is not None)
            if any(call.get(field) is not None for call in calls)
            else None,
            numerator=sum(call.get(field) is not None for call in calls),
            denominator=call_count,
            source="model_call_metrics.jsonl",
        )
        for field in token_fields
    }
    status = str(result.get("status") or row.get("outcome") or "inconclusive")
    quality = "eligible" if status == "passed" else "incomparable"
    provider = str(
        identity.get("provider_profile") or row.get("axes", {}).get("provider_profile") or ""
    )
    model = str(identity.get("model") or "")
    wire_api = str(calls[0].get("wire_api") or "") if calls else ""
    local_links = {
        key: _relative_link(value, bundle_path=bundle_path, root=root)
        for key, value in (result.get("artifacts") or {}).items()
        if key in {"run_dir", "run_result", "report", "trace"}
    }
    attempts = metrics.get("model_attempt_summary") or {}
    triage = {
        "row_id": str(row.get("row_id") or ""),
        "suite_id": str(identity.get("suite_id") or ""),
        "sample_id": str(identity.get("sample_id") or ""),
        "trial_id": trial_id,
        "outcome": status,
        "failure_class": str(result.get("failure_class") or row.get("failure_class") or ""),
        "terminal_reason": str(
            (metrics.get("live_status") or {}).get("reason") or runner.get("message") or ""
        ),
        "live_phase": str(
            (metrics.get("live_status") or {}).get("phase") or runner.get("live_status_phase") or ""
        ),
        "execution_target": _execution_target(row, identity),
        "model_attempts": attempts,
        "longest_model_call_s": max(duration_values) if duration_values else None,
        "timeout_budget_s": runner.get("stall_timeout_s"),
        "timeout_kind": str(runner.get("timeout_kind") or ""),
        "timeout_signal": str(
            (runner.get("timeout_debug_snapshot") or {}).get("timeout_signal") or ""
        ),
        "tool_call_count": metrics.get("tool_call_count"),
        "tool_breakdown": metrics.get("tool_event_counts") or {},
        "first_relevant_evidence": metrics.get("first_relevant_evidence") or {},
        "first_actionable_object_discovery": metrics.get("first_actionable_object_discovery") or {},
        "local_artifacts": local_links,
        "phoenix_run": phoenix_runs.get(trial_id),
    }
    return {
        "row_id": triage["row_id"],
        "identity": identity,
        "status": status,
        "provider_profile": provider,
        "model": model,
        "wire_api": wire_api,
        "wall_time_s": metrics.get("wall_time_s"),
        "tool_call_count": metrics.get("tool_call_count"),
        "model_call_count": call_count,
        "model_duration_s": _metric_cell(
            sum(duration_values) if duration_values else None,
            numerator=len(duration_values),
            denominator=call_count,
            source="model_call_metrics.jsonl",
            claim=quality if duration_values else "incomparable",
        ),
        "tokens": tokens,
        "quality_eligibility": quality,
        "execution_target": triage["execution_target"],
        "slice_values": _slice_values(row, identity),
        "cohort_invariants": {
            "prompt_source_git_sha": prompt_identity.get("prompt_source_git_sha"),
            "prompt_skill_sha256": prompt_identity.get("prompt_skill_sha256"),
            "prompt_rendered_sha256": prompt_identity.get("prompt_rendered_sha256"),
            "runtime_map_prior_sha256": resolved_dependencies.get("runtime_map_prior_sha256"),
        },
        "triage": triage,
    }


def _bundle_relative_run_dir(result: dict[str, Any], *, bundle_path: Path) -> Path | None:
    graders = result.get("grader_outputs") if isinstance(result.get("grader_outputs"), dict) else {}
    runner = graders.get("runner") if isinstance(graders.get("runner"), dict) else {}
    raw = str(
        (result.get("artifacts") or {}).get("run_dir") or runner.get("effective_run_dir") or ""
    )
    marker = "/runs/"
    normalized = raw.replace("\\", "/")
    if marker not in normalized:
        return None
    suffix = normalized.split(marker, 1)[1]
    candidate = (bundle_path.parent / "runs" / suffix).resolve()
    return (
        candidate
        if candidate.is_relative_to(bundle_path.parent.resolve()) and candidate.is_dir()
        else None
    )


def _model_calls(run_dir: Path | None) -> list[dict[str, Any]]:
    if run_dir is None:
        return []
    path = run_dir / "model_call_metrics.jsonl"
    if not path.is_file():
        return []
    calls: list[dict[str, Any]] = []
    for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        try:
            value = json.loads(line)
        except json.JSONDecodeError as exc:
            raise ValueError(f"{path}:{number}: malformed model-call metric") from exc
        if not isinstance(value, dict) or value.get("schema") != "roboclaws_model_call_metric_v1":
            raise ValueError(f"{path}:{number}: unsupported model-call metric")
        calls.append(value)
    return calls


def _optional_object(path: Path | None) -> dict[str, Any]:
    if path is None or not path.is_file():
        return {}
    return _read_object(path, path.name)


def _validate_model_call_identity(
    calls: list[dict[str, Any]], identity: dict[str, Any], *, bundle_path: Path
) -> None:
    expected = {
        "provider_profile": str(identity.get("provider_profile") or ""),
        "model": str(identity.get("model") or ""),
        "agent_engine": str(identity.get("agent_engine") or ""),
    }
    for call in calls:
        for field, value in expected.items():
            if value and str(call.get(field) or "") != value:
                raise ValueError(
                    f"{bundle_path}: model-call {field} contradicts EvalTrial identity"
                )


def _validate_bundle_identity(
    bundle: dict[str, Any], identity: dict[str, Any], *, bundle_path: Path
) -> None:
    suite = bundle.get("suite") if isinstance(bundle.get("suite"), dict) else {}
    for bundle_field, identity_field in (("suite_id", "suite_id"), ("version", "suite_version")):
        declared = str(suite.get(bundle_field) or "")
        actual = str(identity.get(identity_field) or "")
        if declared and actual and declared != actual:
            raise ValueError(f"{bundle_path}: bundle {bundle_field} contradicts EvalTrial identity")


def _phoenix_runs(row: dict[str, Any], *, bundle_path: Path, root: Path) -> dict[str, str]:
    path = _attached_file(row, "phoenix_projection.json", root=root)
    if path is None:
        adjacent = bundle_path.with_name("phoenix_projection.json")
        path = adjacent if adjacent.is_file() else None
    if path is None:
        return {}
    receipt = _read_object(path, "Phoenix projection receipt")
    if receipt.get("state") != "ready":
        return {}
    bundle = _read_object(bundle_path, "eval results bundle")
    receipt_suite = receipt.get("suite") if isinstance(receipt.get("suite"), dict) else {}
    bundle_suite = bundle.get("suite") if isinstance(bundle.get("suite"), dict) else {}
    for field, bundle_field in (("suite_id", "suite_id"), ("suite_version", "version")):
        declared = str(receipt_suite.get(field) or "")
        actual = str(bundle_suite.get(bundle_field) or "")
        if declared and actual and declared != actual:
            raise ValueError(f"{path}: Phoenix receipt {field} contradicts eval bundle")
    runs: dict[str, str] = {}
    for item in receipt.get("runs") or []:
        if not isinstance(item, dict) or not item.get("trial_id") or not item.get("url"):
            continue
        trial_id = str(item["trial_id"])
        if trial_id in runs:
            raise ValueError(f"{path}: duplicate Phoenix run mapping for {trial_id!r}")
        runs[trial_id] = str(item["url"])
    return runs


def _provider_cohorts(
    rows: list[dict[str, Any]], *, manifest: dict[str, Any]
) -> list[dict[str, Any]]:
    grouped: dict[tuple[Any, ...], list[dict[str, Any]]] = defaultdict(list)
    invariant_fields = (
        "suite_id",
        "suite_version",
        "sample_id",
        "sample_version",
        "seed",
        "agent_engine",
        "surface",
        "intent",
        "preset",
        "world",
        "backend",
        "evidence_lane",
        "camera_labeler",
        "scenario_setup",
        "skill_name",
        "prompt_source",
        "goal_contract_hash",
        "mcp_profile",
        "tool_surface",
        "budgets",
        "runtime",
        "execution_target",
        "prompt_source_git_sha",
        "prompt_skill_sha256",
        "prompt_rendered_sha256",
        "runtime_map_prior_sha256",
    )
    for row in rows:
        identity = row["identity"]
        extras = row["cohort_invariants"]
        values = {
            **identity,
            **extras,
            "execution_target": row["execution_target"],
        }
        grouped[tuple(_freeze(values.get(field)) for field in invariant_fields)].append(row)
    peak = int((manifest.get("execution") or {}).get("authorized_max_active_tasks") or 1)
    cohorts = []
    for key, members in sorted(grouped.items(), key=lambda item: repr(item[0])):
        quality_ok = all(member["quality_eligibility"] == "eligible" for member in members)
        model_available = any(member["model_call_count"] for member in members)
        execution_targets = {member["execution_target"] for member in members}
        latency_ok = quality_ok and peak == 1 and len(execution_targets) <= 1 and len(members) > 1
        cohorts.append(
            {
                "invariants": dict(zip(invariant_fields, key, strict=True)),
                "treatments": sorted(
                    {(m["provider_profile"], m["model"], m["wire_api"]) for m in members}
                ),
                "claims": {
                    "quality": _claim("eligible" if quality_ok else "incomparable", "quality_gate"),
                    "model_work": _claim(
                        "eligible" if quality_ok and model_available else "diagnostic_only",
                        "sanitized_model_calls",
                    ),
                    "latency": _claim(
                        "eligible" if latency_ok else "incomparable",
                        (
                            "comparable_serial_execution"
                            if latency_ok
                            else "concurrent_execution"
                            if peak > 1
                            else "insufficient_comparable_rows"
                        ),
                    ),
                },
                "metrics": _cohort_metrics(members),
            }
        )
    return cohorts


def _cohort_metrics(rows: list[dict[str, Any]]) -> dict[str, Any]:
    wall = [
        float(row["wall_time_s"])
        for row in rows
        if isinstance(row.get("wall_time_s"), (int, float))
    ]
    model = [
        float(row["model_duration_s"]["value"])
        for row in rows
        if row["model_duration_s"]["value"] is not None
    ]
    metrics = {
        "wall_time_s": _distribution_cell(wall, len(rows), "eval_results.metrics.wall_time_s"),
        "observed_model_time_s": _distribution_cell(model, len(rows), "model_call_metrics.jsonl"),
        "model_call_count": _metric_cell(
            sum(row["model_call_count"] for row in rows),
            numerator=len(rows),
            denominator=len(rows),
            source="model_call_metrics.jsonl",
        ),
        "tool_call_count": _metric_cell(
            sum(int(row["tool_call_count"] or 0) for row in rows),
            numerator=sum(row["tool_call_count"] is not None for row in rows),
            denominator=len(rows),
            source="eval_results.metrics.tool_call_count",
        ),
    }
    for field in (
        "input_tokens",
        "uncached_input_tokens",
        "cached_input_tokens",
        "output_tokens",
        "reasoning_tokens",
    ):
        cells = [row["tokens"][field] for row in rows]
        available = [cell["value"] for cell in cells if cell["value"] is not None]
        metrics[field] = _metric_cell(
            sum(available) if available else None,
            numerator=sum(cell["coverage"]["numerator"] for cell in cells),
            denominator=sum(cell["coverage"]["denominator"] for cell in cells),
            source="model_call_metrics.jsonl",
        )
    return metrics


def _distribution_cell(values: list[float], denominator: int, source: str) -> dict[str, Any]:
    value = None
    if values:
        ordered = sorted(values)
        value = {
            "p50": statistics.median(ordered),
            "p95": ordered[max(0, int(0.95 * len(ordered)) - 1)],
            "n": len(ordered),
        }
    return _metric_cell(value, numerator=len(values), denominator=denominator, source=source)


def _capability_health(rows: list[dict[str, Any]], *, manifest: dict[str, Any]) -> dict[str, Any]:
    status = Counter(row["status"] for row in rows)
    samples: dict[str, list[str]] = defaultdict(list)
    failure_classes = Counter()
    for row in rows:
        identity = row["identity"]
        samples[str(identity.get("sample_id") or "")].append(row["status"])
        failure = str(row["triage"].get("failure_class") or "")
        if failure and failure != "not_applicable":
            failure_classes[failure] += 1
    return {
        "grain": "eval_trial_and_sample",
        "trial_count": len(rows),
        "passed": status["passed"],
        "failed": status["failed"],
        "blocked": status["blocked"],
        "pass_at_1": (status["passed"] / len(rows)) if rows else None,
        "samples": {
            key: {
                "trial_count": len(values),
                "pass_at_k": any(v == "passed" for v in values),
                "pass_caret_k": all(v == "passed" for v in values),
            }
            for key, values in sorted(samples.items())
        },
        "failure_classes": dict(sorted(failure_classes.items())),
        "slices": _capability_slices(rows),
        "baseline_regressions": _baseline_regressions(manifest),
    }


def _slice_values(row: dict[str, Any], identity: dict[str, Any]) -> dict[str, str]:
    axes = row.get("axes") if isinstance(row.get("axes"), dict) else {}
    runtime = identity.get("runtime") if isinstance(identity.get("runtime"), dict) else {}
    return {
        "suite": str(identity.get("suite_id") or axes.get("suite") or "not_applicable"),
        "sample": str(identity.get("sample_id") or "not_applicable"),
        "provider_route": "/".join(
            filter(
                None,
                (str(identity.get("provider_profile") or ""), str(identity.get("model") or "")),
            )
        )
        or "not_applicable",
        "world_scene": str(identity.get("world") or axes.get("world") or "not_applicable"),
        "intent": str(identity.get("intent") or axes.get("intent") or "not_applicable"),
        "evidence_lane": str(
            identity.get("evidence_lane") or axes.get("evidence_lane") or "not_applicable"
        ),
        "skill_delivery": str(
            runtime.get("skill_delivery_cell") or row.get("skill_delivery_cell") or "not_applicable"
        ),
    }


def _capability_slices(rows: list[dict[str, Any]]) -> dict[str, Any]:
    slices: dict[str, dict[str, Counter[str]]] = defaultdict(lambda: defaultdict(Counter))
    for row in rows:
        for dimension, value in row["slice_values"].items():
            slices[dimension][value][row["status"]] += 1
    return {
        dimension: {
            value: {
                "total": sum(counts.values()),
                "passed": counts["passed"],
                "failed": counts["failed"],
                "blocked": counts["blocked"],
            }
            for value, counts in sorted(values.items())
        }
        for dimension, values in sorted(slices.items())
    }


def _baseline_regressions(manifest: dict[str, Any]) -> list[dict[str, Any]]:
    regressions = []
    for comparison in manifest.get("comparisons") or []:
        if not isinstance(comparison, dict):
            continue
        row_ids = sorted(
            {
                str(value)
                for key in ("behavior_regression_row_ids", "outcome_regression_row_ids")
                for value in comparison.get(key) or []
            }
        )
        regressions.append(
            {
                "label": str(comparison.get("label") or "prior_baseline"),
                "manifest_sha256": str(comparison.get("manifest_sha256") or ""),
                "common_row_count": int(comparison.get("common_row_count") or 0),
                "common_passed_row_count": int(comparison.get("common_passed_row_count") or 0),
                "regressed_row_ids": row_ids,
            }
        )
    return regressions


def _coverage(rows: list[dict[str, Any]], selected: list[dict[str, Any]]) -> dict[str, Any]:
    calls = sum(row["model_call_count"] for row in rows)
    duration = sum(row["model_duration_s"]["coverage"]["numerator"] for row in rows)
    token = sum(row["tokens"]["input_tokens"]["coverage"]["numerator"] for row in rows)
    return {
        "eval_bundle": _coverage_cell(len({row["row_id"] for row in rows}), len(selected)),
        "run_artifacts": _coverage_cell(
            sum(bool(row["triage"]["local_artifacts"].get("run_dir")) for row in rows), len(rows)
        ),
        "model_duration": _coverage_cell(duration, calls),
        "token_usage": _coverage_cell(token, calls),
        "phoenix_mapping": _coverage_cell(
            sum(bool(row["triage"].get("phoenix_run")) for row in rows), len(rows)
        ),
        "trace_linkage": _coverage_cell(
            sum(bool(row["triage"]["local_artifacts"].get("trace")) for row in rows), len(rows)
        ),
        "by_provider": _provider_coverage(rows),
    }


def _provider_coverage(rows: list[dict[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for provider in sorted({row["provider_profile"] for row in rows if row["provider_profile"]}):
        provider_rows = [row for row in rows if row["provider_profile"] == provider]
        calls = sum(row["model_call_count"] for row in provider_rows)
        durations = sum(row["model_duration_s"]["coverage"]["numerator"] for row in provider_rows)
        tokens = sum(
            row["tokens"]["input_tokens"]["coverage"]["numerator"] for row in provider_rows
        )
        result[provider] = {
            "model_duration": _coverage_cell(durations, calls),
            "token_usage": _coverage_cell(tokens, calls),
        }
    return result


def _metric_cell(
    value: Any, *, numerator: int, denominator: int, source: str, claim: str = "diagnostic_only"
) -> dict[str, Any]:
    availability = (
        "not_applicable"
        if denominator == 0
        else (
            "available" if numerator == denominator else ("partial" if numerator else "unavailable")
        )
    )
    return {
        "value": value,
        "availability": availability,
        "source": source,
        "coverage": _coverage_cell(numerator, denominator),
        "claim_eligibility": claim,
        "limitations": [] if availability == "available" else ["incomplete_coverage"],
    }


def _coverage_cell(numerator: int, denominator: int) -> dict[str, int]:
    return {"numerator": int(numerator), "denominator": int(denominator)}


def _claim(state: str, reason: str) -> dict[str, str]:
    return {"state": state, "reason": reason}


def _execution_target(row: dict[str, Any], identity: dict[str, Any]) -> str:
    runtime = identity.get("runtime") if isinstance(identity.get("runtime"), dict) else {}
    return str(
        (row.get("execution") or {}).get("execution_target")
        or runtime.get("hardware")
        or "unavailable"
    )


def _row_only_triage(row: dict[str, Any], *, root: Path) -> dict[str, Any]:
    artifacts = {}
    for raw in row.get("output_artifacts") or []:
        value = str(raw)
        if any(part in value for part in FORBIDDEN_PATH_PARTS):
            continue
        path = Path(value)
        if not path.is_absolute():
            path = Path.cwd() / path
        resolved = path.resolve()
        if resolved.is_relative_to(root) and resolved.is_file():
            artifacts[resolved.name] = resolved.relative_to(root).as_posix()
    return {
        "row_id": str(row.get("row_id") or ""),
        "suite_id": "",
        "sample_id": "",
        "trial_id": "",
        "outcome": str(row.get("outcome") or row.get("status") or ""),
        "failure_class": str(row.get("failure_class") or row.get("blocker_category") or ""),
        "terminal_reason": str(row.get("failure_reason") or ""),
        "execution_target": str(
            (row.get("execution") or {}).get("execution_target") or "unavailable"
        ),
        "local_artifacts": artifacts,
        "phoenix_run": None,
    }


def _relative_link(value: Any, *, bundle_path: Path, root: Path) -> str | None:
    raw = str(value or "")
    if not raw:
        return None
    marker = "/runs/"
    normalized = raw.replace("\\", "/")
    if marker in normalized:
        candidate = (bundle_path.parent / "runs" / normalized.split(marker, 1)[1]).resolve()
        if candidate.is_relative_to(root) and candidate.exists():
            return candidate.relative_to(root).as_posix()
    return None


def _freeze(value: Any) -> Any:
    if isinstance(value, list):
        return tuple(_freeze(item) for item in value)
    if isinstance(value, dict):
        return tuple(sorted((str(key), _freeze(child)) for key, child in value.items()))
    return value
