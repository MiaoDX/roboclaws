from __future__ import annotations

import sys
from collections import defaultdict
from pathlib import Path
from typing import Any

if __package__ in {None, ""}:
    repo_root = Path(__file__).resolve().parents[2]
    if str(repo_root) not in sys.path:
        sys.path.insert(0, str(repo_root))

from roboclaws.evals.visual_grounding_benchmark.artifacts import (
    _api_cost_summary,
    _memory_profile_summary,
    _pipeline_evidence_level,
    _prediction_timed_out,
)
from roboclaws.evals.visual_grounding_benchmark.common import pipeline_family as _pipeline_family
from roboclaws.evals.visual_grounding_benchmark.scoring import (
    ratio as _ratio,
)
from roboclaws.evals.visual_grounding_benchmark.scoring import (
    score_predictions as _score_predictions,
)


def _summarize_pipeline(
    *,
    pipeline_id: str,
    benchmark_row: dict[str, Any],
    predictions: list[dict[str, Any]],
    corpus: dict[str, Any],
    auth_mode: str,
    service_config: dict[str, Any],
    include_private_label_details: bool,
) -> dict[str, Any]:
    observation_by_id = {
        str(item.get("observation_id") or ""): item for item in corpus.get("observations") or []
    }
    category_family_map = {
        str(key): str(value) for key, value in (corpus.get("category_family_map") or {}).items()
    }
    stage_summary = _stage_summary(predictions)
    score = _score_predictions(predictions, observation_by_id, category_family_map)
    failure_count = sum(1 for item in predictions if item["pipeline"].get("status") == "failed")
    parse_failure_count = sum(1 for item in predictions if item["pipeline"].get("parse_failed"))
    timeout_count = sum(1 for item in predictions if _prediction_timed_out(item))
    candidate_count = sum(int(item.get("candidate_count") or 0) for item in predictions)
    latencies = [int(item["pipeline"].get("request_latency_ms") or 0) for item in predictions]
    overlays = [str(item["overlay_path"]) for item in predictions]
    result = {
        "benchmark_row_id": str(benchmark_row.get("row_id") or pipeline_id),
        "pipeline_id": pipeline_id,
        "model_family": str(benchmark_row.get("model_family") or _pipeline_family(pipeline_id)),
        "model_id": str(benchmark_row.get("model_id") or ""),
        "size_tier": str(benchmark_row.get("size_tier") or "unspecified"),
        "runtime_parameters": dict(benchmark_row.get("runtime_parameters") or {}),
        "under_sampled_reason": str(benchmark_row.get("under_sampled_reason") or ""),
        "status": "completed",
        "auth_mode": _pipeline_auth_mode(predictions, fallback=auth_mode),
        "service_config": service_config,
        "observation_count": len(predictions),
        "candidate_count": candidate_count,
        "failure_count": failure_count,
        "parse_failure_count": parse_failure_count,
        "timeout_count": timeout_count,
        "failure_rate": _ratio(failure_count, len(predictions)),
        "timeout_rate": _ratio(timeout_count, len(predictions)),
        "latency_ms": {
            "total": sum(latencies),
            "avg": round(sum(latencies) / len(latencies), 3) if latencies else 0.0,
            "max": max(latencies) if latencies else 0,
        },
        "api_cost": _api_cost_summary(predictions),
        "memory_profile": _memory_profile_summary(predictions),
        "evidence_level": _pipeline_evidence_level(predictions),
        "stage_summary": stage_summary,
        "metrics": score["metrics"],
        "overlays": overlays,
    }
    if include_private_label_details:
        result["private_label_details"] = score["private_label_details"]
    return result


def _pipeline_auth_mode(predictions: list[dict[str, Any]], *, fallback: str) -> str:
    modes = [
        str((prediction.get("pipeline") or {}).get("auth_mode") or "") for prediction in predictions
    ]
    for mode in modes:
        if mode and mode != "none":
            return mode
    return fallback


def _stage_summary(predictions: list[dict[str, Any]]) -> list[dict[str, Any]]:
    summaries: dict[tuple[str, str, str], dict[str, Any]] = {}
    for prediction in predictions:
        for stage in prediction["pipeline"].get("stages") or []:
            key = (
                str(stage.get("stage") or ""),
                str(stage.get("producer_id") or ""),
                str(stage.get("model_id") or ""),
            )
            row = summaries.setdefault(
                key,
                {
                    "stage": key[0],
                    "producer_id": key[1],
                    "model_id": key[2],
                    "status_counts": defaultdict(int),
                    "latencies": [],
                    "observation_count": 0,
                    "runtime": {},
                    "runtime_parameters": {},
                },
            )
            row["observation_count"] += 1
            row["status_counts"][str(stage.get("status") or "ok")] += 1
            row["latencies"].append(int(stage.get("latency_ms") or 0))
            if isinstance(stage.get("runtime"), dict) and not row["runtime"]:
                row["runtime"] = dict(stage["runtime"])
            if isinstance(stage.get("runtime_parameters"), dict):
                row["runtime_parameters"].update(stage["runtime_parameters"])

    output: list[dict[str, Any]] = []
    for row in summaries.values():
        latencies = list(row.pop("latencies"))
        status_counts = dict(row.pop("status_counts"))
        output.append(
            {
                **row,
                "status": "ok" if set(status_counts) <= {"ok"} else "mixed",
                "status_counts": status_counts,
                "latency_ms_total": sum(latencies),
                "latency_ms_avg": round(sum(latencies) / len(latencies), 3) if latencies else 0.0,
                "latency_ms_max": max(latencies) if latencies else 0,
            }
        )
    return sorted(output, key=lambda item: (item["stage"], item["producer_id"]))


def _rank_pipelines(pipeline_results: list[dict[str, Any]]) -> list[dict[str, Any]]:
    ranking: list[dict[str, Any]] = []
    for result in pipeline_results:
        metrics = result.get("metrics") or {}
        if metrics.get("bbox_metrics_available"):
            score_basis = "bbox_iou"
            score = (
                0.60 * float(metrics.get("bbox_recall_at_iou") or 0.0)
                + 0.20 * float(metrics.get("bbox_precision_at_iou") or 0.0)
                + 0.10 * float(metrics.get("bbox_category_family_accuracy_at_iou") or 0.0)
                + 0.10 * (1.0 - float(result.get("failure_rate") or 0.0))
            )
        else:
            score_basis = "category_presence"
            score = (
                0.55 * float(metrics.get("recall") or 0.0)
                + 0.25 * float(metrics.get("precision") or 0.0)
                + 0.10 * float(metrics.get("category_family_accuracy") or 0.0)
                + 0.10 * (1.0 - float(result.get("failure_rate") or 0.0))
            )
        ranking.append(
            {
                "benchmark_row_id": result.get("benchmark_row_id", result.get("pipeline_id", "")),
                "pipeline_id": result.get("pipeline_id", ""),
                "model_family": result.get("model_family", ""),
                "model_id": result.get("model_id", ""),
                "size_tier": result.get("size_tier", ""),
                "runtime_parameters": result.get("runtime_parameters", {}),
                "score": round(score, 6),
                "score_basis": score_basis,
                "recall": metrics.get("recall", 0.0),
                "precision": metrics.get("precision", 0.0),
                "bbox_recall_at_iou": metrics.get("bbox_recall_at_iou", 0.0),
                "bbox_precision_at_iou": metrics.get("bbox_precision_at_iou", 0.0),
                "bbox_category_family_accuracy_at_iou": metrics.get(
                    "bbox_category_family_accuracy_at_iou",
                    0.0,
                ),
                "bbox_iou_threshold": metrics.get("bbox_iou_threshold"),
                "actionability_proxy_rate": metrics.get("actionability_proxy_rate", 0.0),
                "failure_rate": result.get("failure_rate", 0.0),
                "timeout_rate": result.get("timeout_rate", 0.0),
                "mean_latency_ms": (result.get("latency_ms") or {}).get("avg", 0.0),
                "api_cost_usd": (result.get("api_cost") or {}).get("total_usd"),
                "memory_peak_mb": (result.get("memory_profile") or {}).get("peak_mb"),
                "evidence_level": result.get("evidence_level", ""),
            }
        )
    return sorted(
        ranking,
        key=lambda item: (
            -float(item["score"]),
            float(item["failure_rate"]),
            float(item["mean_latency_ms"]),
            str(item["pipeline_id"]),
        ),
    )


def _family_sweep_summary(pipeline_results: list[dict[str, Any]]) -> list[dict[str, Any]]:
    families: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for result in pipeline_results:
        family = str(
            result.get("model_family") or _pipeline_family(str(result.get("pipeline_id") or ""))
        )
        families[family].append(result)

    summaries: list[dict[str, Any]] = []
    for family, rows in sorted(families.items()):
        size_tiers = sorted({str(row.get("size_tier") or "unspecified") for row in rows})
        model_ids = sorted({str(row.get("model_id") or "") for row in rows if row.get("model_id")})
        row_ids = [str(row.get("benchmark_row_id") or row.get("pipeline_id") or "") for row in rows]
        successful_rows = [row for row in rows if _benchmark_row_succeeded(row)]
        successful_row_ids = [
            str(row.get("benchmark_row_id") or row.get("pipeline_id") or "")
            for row in successful_rows
        ]
        under_sampled = len(successful_rows) < 2
        explicit_reasons = [
            str(row.get("under_sampled_reason") or "")
            for row in rows
            if str(row.get("under_sampled_reason") or "")
        ]
        reason = ""
        if under_sampled:
            reason = (
                explicit_reasons[0]
                if explicit_reasons
                else _family_under_sampled_reason(rows, len(successful_rows))
            )
        summaries.append(
            {
                "model_family": family,
                "tested_config_count": len(rows),
                "successful_config_count": len(successful_rows),
                "row_ids": row_ids,
                "successful_row_ids": successful_row_ids,
                "size_tiers": size_tiers,
                "model_ids": model_ids,
                "under_sampled": under_sampled,
                "under_sampled_reason": reason,
            }
        )
    return summaries


def _benchmark_row_succeeded(row: dict[str, Any]) -> bool:
    return (
        int(row.get("failure_count") or 0) == 0
        and int(row.get("parse_failure_count") or 0) == 0
        and int(row.get("timeout_count") or 0) == 0
    )


def _family_under_sampled_reason(rows: list[dict[str, Any]], successful_count: int) -> str:
    failure_reasons: set[str] = set()
    for row in rows:
        if _benchmark_row_succeeded(row):
            continue
        for stage in row.get("stage_summary") or []:
            status_counts = stage.get("status_counts") or {}
            for status, count in status_counts.items():
                if str(status) != "ok" and int(count or 0) > 0:
                    failure_reasons.add(str(status))
    if failure_reasons:
        return (
            f"fewer than two successful configs ({successful_count}); "
            f"failure statuses: {', '.join(sorted(failure_reasons))}"
        )
    return f"fewer than two successful configs ({successful_count})"


def _detector_probe_recommendation(
    pipeline_results: list[dict[str, Any]],
    ranking: list[dict[str, Any]],
) -> dict[str, Any]:
    by_row_id = {str(item.get("benchmark_row_id") or ""): item for item in pipeline_results}

    def result_for_rank(row: dict[str, Any]) -> dict[str, Any]:
        row_id = str(row.get("benchmark_row_id") or "")
        if row_id in by_row_id:
            return by_row_id[row_id]
        pipeline_id = str(row.get("pipeline_id") or "")
        return next(
            (
                result
                for result in pipeline_results
                if str(result.get("pipeline_id") or "") == pipeline_id
            ),
            {},
        )

    def best_for(kind: str) -> dict[str, Any]:
        for row in ranking:
            result = result_for_rank(row)
            if _pipeline_kind(result) == kind:
                return row
        return {}

    best_proposer = best_for("proposer_only")
    selected = [
        {
            "slot": "control",
            "pipeline_id": "sim",
            "benchmark_row_id": "sim",
            "reason": "Pipeline-control baseline for end-to-end cleanup comparison.",
        }
    ]
    for slot, row, reason in (
        (
            "best_proposer_only",
            best_proposer,
            "Highest-ranked proposer-only benchmark pipeline.",
        ),
    ):
        pipeline_id = str(row.get("pipeline_id") or "")
        if pipeline_id and pipeline_id not in {item["pipeline_id"] for item in selected}:
            selected.append(
                {
                    "slot": slot,
                    "pipeline_id": pipeline_id,
                    "benchmark_row_id": str(row.get("benchmark_row_id") or pipeline_id),
                    "reason": reason,
                }
            )

    selected_pipeline_ids = [item["pipeline_id"] for item in selected]
    evidence_levels = {
        str(row.get("pipeline_id") or ""): str(result_for_rank(row).get("evidence_level") or "")
        for row in (best_proposer,)
        if str(row.get("pipeline_id") or "") in selected_pipeline_ids
    }
    non_sim_evidence_levels = list(evidence_levels.values())
    real_stage_provenance_present = any(
        level == "real_detector_sidecar" for level in non_sim_evidence_levels
    )
    selected_real_stage_provenance_complete = bool(non_sim_evidence_levels) and all(
        level == "real_detector_sidecar" for level in non_sim_evidence_levels
    )
    return {
        "schema": "visual_grounding_detector_probe_recommendation_v1",
        "policy": {
            "control_pipeline_id": "sim",
            "max_proposer_only_pipelines": 1,
            "max_total_pipelines": 2,
        },
        "selected_end_to_end_pipelines": selected_pipeline_ids,
        "selected": selected,
        "best_proposer_only_pipeline_id": str(best_proposer.get("pipeline_id") or ""),
        "evidence_levels": evidence_levels,
        "real_stage_provenance_present": real_stage_provenance_present,
        "selected_real_stage_provenance_complete": selected_real_stage_provenance_complete,
        "requires_real_stage_provenance_before_probe": (
            not selected_real_stage_provenance_complete
        ),
        "rationale": (
            "End-to-end probes stay capped to the sim control and one detector-only "
            "proposer pipeline."
        ),
    }


def _pipeline_kind(pipeline: dict[str, Any]) -> str:
    pipeline_id = str(pipeline.get("pipeline_id") or "")
    if pipeline_id == "sim":
        return "control"
    return "proposer_only"
