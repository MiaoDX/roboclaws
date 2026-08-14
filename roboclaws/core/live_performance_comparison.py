"""Comparison policy for serialized live-performance metric packets."""

from __future__ import annotations

import math
from pathlib import Path
from typing import Any

from roboclaws.core.live_performance import extract_report_performance_metrics

COMPARISON_SCHEMA = "roboclaws_report_performance_comparison_v1"


def compare_report_performance_metrics(
    baseline: dict[str, Any],
    candidate: dict[str, Any],
    *,
    key: str = "",
    quality_waiver: str = "",
    diagnostic: bool = False,
) -> dict[str, Any]:
    """Compare current or historical serialized packets with speed-claim guardrails."""
    quality = _quality_comparison(baseline.get("quality"), candidate.get("quality"))
    timing = _timing_comparison(baseline.get("timing"), candidate.get("timing"))
    model_work = _model_work_comparison(baseline.get("model_work"), candidate.get("model_work"))
    call_counts = _call_count_comparison(baseline.get("call_counts"), candidate.get("call_counts"))
    identity = _identity_comparison(baseline.get("run_identity"), candidate.get("run_identity"))
    faster = timing.get("observed_wall_delta_s") is not None and timing["observed_wall_delta_s"] < 0
    status = "diagnostic"
    reasons: list[str] = []
    if identity["apples_to_oranges"] and not diagnostic:
        status = "rejected"
        reasons.append("apples-to-oranges comparison requires diagnostic=true")
    elif quality["regressed"] and not quality_waiver:
        status = "rejected"
        reasons.append("candidate is faster but worse" if faster else "behavior quality regressed")
    elif faster:
        status = "accepted"
        reasons.append("candidate faster with same-or-better recorded quality")
    else:
        reasons.append("no observed wall-time speed win")
    if quality_waiver:
        reasons.append(f"quality waiver: {quality_waiver}")
        if status == "rejected" and not identity["apples_to_oranges"]:
            status = "accepted"
    return {
        "schema": COMPARISON_SCHEMA,
        "key": key,
        "status": status,
        "reasons": reasons,
        "quality_policy": "same_or_better",
        "quality_waiver": quality_waiver,
        "identity_comparison": identity,
        "quality_comparison": quality,
        "call_count_comparison": call_counts,
        "model_work_comparison": model_work,
        "timing_comparison": timing,
        "baseline": {
            "run_dir": baseline.get("run_dir"),
            "run_identity": baseline.get("run_identity"),
        },
        "candidate": {
            "run_dir": candidate.get("run_dir"),
            "run_identity": candidate.get("run_identity"),
        },
    }


def compare_run_dirs(
    *,
    baseline_dir: Path,
    candidate_dir: Path,
    key: str = "",
    quality_waiver: str = "",
    diagnostic: bool = False,
    calibration: dict[str, Any] | None = None,
) -> dict[str, Any]:
    baseline = extract_report_performance_metrics(baseline_dir, calibration=calibration)
    candidate = extract_report_performance_metrics(candidate_dir, calibration=calibration)
    return compare_report_performance_metrics(
        baseline, candidate, key=key, quality_waiver=quality_waiver, diagnostic=diagnostic
    )


def _quality_comparison(baseline: Any, candidate: Any) -> dict[str, Any]:
    baseline, candidate = _dict(baseline), _dict(candidate)
    checks = {
        "checker_state": candidate.get("checker_state") == baseline.get("checker_state")
        or candidate.get("checker_state") == "result-present",
        "restored_count": _not_lower(
            candidate.get("restored_count"), baseline.get("restored_count")
        ),
        "mess_restoration_rate": _not_lower(
            candidate.get("mess_restoration_rate"), baseline.get("mess_restoration_rate")
        ),
        "sweep_coverage_rate": _not_lower_with_cap(
            candidate.get("sweep_coverage_rate"), baseline.get("sweep_coverage_rate"), cap=1.0
        ),
        "disturbance_count": _not_higher(
            candidate.get("disturbance_count"), baseline.get("disturbance_count")
        ),
        "failed_or_noop_tool_count": _not_higher(
            candidate.get("failed_or_noop_tool_count"), baseline.get("failed_or_noop_tool_count")
        ),
        "semantic_accepted_count": _not_lower(
            candidate.get("semantic_accepted_count"), baseline.get("semantic_accepted_count")
        ),
    }
    return {
        "policy": "same_or_better",
        "regressed": not all(checks.values()),
        "checks": checks,
        "baseline": baseline,
        "candidate": candidate,
    }


def _timing_comparison(baseline: Any, candidate: Any) -> dict[str, Any]:
    baseline, candidate = _dict(baseline), _dict(candidate)
    return {
        "observed_wall_delta_s": _delta(
            candidate.get("observed_wall_s"), baseline.get("observed_wall_s")
        ),
        "mcp_between_tool_gap_delta_s": _delta(
            candidate.get("mcp_between_tool_gap_s"), baseline.get("mcp_between_tool_gap_s")
        ),
        "observed_model_api_delta_s": _delta(
            candidate.get("observed_model_api_s"), baseline.get("observed_model_api_s")
        ),
        "estimated_model_work_delta_s": _delta(
            _dict(candidate.get("estimated_model_work_s")).get("estimated_s"),
            _dict(baseline.get("estimated_model_work_s")).get("estimated_s"),
        ),
        "model_latency_residual_delta_s": _delta(
            candidate.get("model_latency_residual_s"), baseline.get("model_latency_residual_s")
        ),
        "model_or_sdk_residual_delta_s": _delta(
            candidate.get("model_or_sdk_residual_s"), baseline.get("model_or_sdk_residual_s")
        ),
        "baseline": baseline,
        "candidate": candidate,
    }


def _model_work_comparison(baseline: Any, candidate: Any) -> dict[str, Any]:
    baseline, candidate = _dict(baseline), _dict(candidate)
    return {
        "total_uncached_input_tokens_delta": _int_delta(
            candidate.get("total_uncached_input_tokens"),
            baseline.get("total_uncached_input_tokens"),
        ),
        "total_output_tokens_delta": _int_delta(
            candidate.get("total_output_tokens"), baseline.get("total_output_tokens")
        ),
        "available": bool(baseline.get("available")) and bool(candidate.get("available")),
        "baseline": baseline,
        "candidate": candidate,
    }


def _call_count_comparison(baseline: Any, candidate: Any) -> dict[str, Any]:
    baseline, candidate = _dict(baseline), _dict(candidate)
    return {
        "model_call_count_delta": _int_delta(
            candidate.get("model_call_count"), baseline.get("model_call_count")
        ),
        "mcp_tool_call_count_delta": _int_delta(
            candidate.get("mcp_tool_call_count"), baseline.get("mcp_tool_call_count")
        ),
        "baseline": baseline,
        "candidate": candidate,
    }


def _identity_comparison(baseline: Any, candidate: Any) -> dict[str, Any]:
    baseline, candidate = _dict(baseline), _dict(candidate)
    keys = (
        "surface",
        "intent",
        "task_name",
        "agent_engine",
        "provider_profile",
        "wire_api",
        "model",
        "evidence_lane",
        "seed",
        "profile_id",
    )
    mismatches = [
        key
        for key in keys
        if baseline.get(key) not in {None, ""}
        and candidate.get(key) not in {None, ""}
        and baseline.get(key) != candidate.get(key)
    ]
    return {
        "apples_to_oranges": bool(mismatches),
        "mismatched_fields": mismatches,
        "baseline": baseline,
        "candidate": candidate,
    }


def _dict(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _float(value: Any) -> float | None:
    try:
        result = float(value)
    except (TypeError, ValueError):
        return None
    return None if math.isnan(result) or math.isinf(result) else result


def _integer(value: Any) -> int | None:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _delta(candidate: Any, baseline: Any) -> float | None:
    candidate_value, baseline_value = _float(candidate), _float(baseline)
    return (
        None
        if candidate_value is None or baseline_value is None
        else round(candidate_value - baseline_value, 3)
    )


def _int_delta(candidate: Any, baseline: Any) -> int | None:
    candidate_value, baseline_value = _integer(candidate), _integer(baseline)
    return (
        None
        if candidate_value is None or baseline_value is None
        else candidate_value - baseline_value
    )


def _not_lower(candidate: Any, baseline: Any) -> bool:
    candidate_value, baseline_value = _float(candidate), _float(baseline)
    return candidate_value is None or baseline_value is None or candidate_value >= baseline_value


def _not_lower_with_cap(candidate: Any, baseline: Any, *, cap: float) -> bool:
    candidate_value, baseline_value = _float(candidate), _float(baseline)
    return (
        candidate_value is None
        or baseline_value is None
        or min(candidate_value, cap) >= min(baseline_value, cap)
    )


def _not_higher(candidate: Any, baseline: Any) -> bool:
    candidate_value, baseline_value = _float(candidate), _float(baseline)
    return candidate_value is None or baseline_value is None or candidate_value <= baseline_value
