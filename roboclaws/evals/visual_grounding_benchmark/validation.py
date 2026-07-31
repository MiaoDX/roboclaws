from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from roboclaws.core.json_sources import read_json_object, read_jsonl_objects

RESULT_SCHEMA = "visual_grounding_benchmark_result_v1"
PREDICTION_SCHEMA = "visual_grounding_prediction_v1"
PIPELINE_SCHEMA = "visual_grounding_pipeline_v1"


def validate_benchmark_path(
    path: Path,
    *,
    expect_pipeline: str = "",
    require_success: bool = False,
    require_candidates: bool = False,
    allow_private_label_details: bool = False,
) -> Path:
    result_path = path
    if result_path.is_dir():
        result_path = result_path / "visual_grounding_benchmark_result.json"
    base_dir = result_path.parent
    result = _load_json(result_path)
    _assert(result.get("schema") == RESULT_SCHEMA, f"bad result schema: {result_path}")
    _assert((base_dir / "visual_grounding_benchmark_report.html").is_file(), "missing report")
    predictions_path = base_dir / "visual_grounding_predictions.jsonl"
    _assert(predictions_path.is_file(), "missing predictions JSONL")
    report_text = (base_dir / "visual_grounding_benchmark_report.html").read_text(encoding="utf-8")
    predictions_text = predictions_path.read_text(encoding="utf-8")
    _assert_no_secret_text(report_text, "report")
    _assert_no_secret_text(predictions_text, "predictions")
    _assert("private_labels" not in predictions_text, "predictions include private labels")
    _assert("bytes_base64" not in predictions_text, "predictions include image bytes")

    pipelines = list(result.get("pipelines") or [])
    _assert(pipelines, "result has no pipelines")
    if expect_pipeline:
        pipeline_ids = {str(item.get("pipeline_id") or "") for item in pipelines}
        benchmark_row_ids = {str(item.get("benchmark_row_id") or "") for item in pipelines}
        _assert(
            expect_pipeline in pipeline_ids or expect_pipeline in benchmark_row_ids,
            f"missing pipeline or benchmark row {expect_pipeline}",
        )
    _assert_private_label_detail_policy(result, allow=allow_private_label_details)
    _assert_family_sweep(result)

    predictions = _load_jsonl(predictions_path)
    _assert(predictions, "predictions JSONL is empty")
    for pipeline in pipelines:
        _assert_pipeline(
            base_dir,
            pipeline,
            require_success=require_success,
            require_candidates=require_candidates,
        )
    _assert_detector_probe_recommendation(result)
    for prediction in predictions:
        _assert_prediction(base_dir, prediction, result=result)

    artifact_paths = result.get("artifacts") or {}
    _assert(
        artifact_paths.get("predictions_jsonl") == predictions_path.name,
        "bad predictions path",
    )
    _assert(
        artifact_paths.get("report_html") == "visual_grounding_benchmark_report.html",
        "bad report path",
    )
    _assert("Visual Grounding Quality" in report_text, "report missing grounding section")
    _assert("Destination Hint Quality" in report_text, "report missing destination section")
    _assert("Cost And Resource Telemetry" in report_text, "report missing telemetry section")
    _assert("Family Sweep Coverage" in report_text, "report missing family sweep section")
    _assert(
        "End-To-End Probe Recommendation" in report_text,
        "report missing end-to-end probe recommendation",
    )
    _assert(
        "Real stage provenance present" in report_text,
        "report missing real-stage provenance gate",
    )
    _assert(
        "Requires real detector-sidecar provenance before full cleanup probe" in report_text,
        "report missing detector-probe provenance requirement",
    )
    return result_path


def _assert_pipeline(
    base_dir: Path,
    pipeline: dict[str, Any],
    *,
    require_success: bool,
    require_candidates: bool,
) -> None:
    _assert(pipeline.get("benchmark_row_id"), f"benchmark row id missing: {pipeline}")
    pipeline_id = str(pipeline.get("pipeline_id") or "")
    _assert(pipeline_id, f"pipeline id missing: {pipeline}")
    _assert(pipeline.get("model_family"), f"model family missing: {pipeline_id}")
    _assert("size_tier" in pipeline, f"size tier missing: {pipeline_id}")
    _assert(
        isinstance(pipeline.get("runtime_parameters"), dict),
        f"runtime knobs missing: {pipeline_id}",
    )
    _assert(pipeline.get("status") == "completed", f"pipeline not completed: {pipeline_id}")
    _assert(int(pipeline.get("observation_count") or 0) >= 1, f"no observations: {pipeline_id}")
    candidate_count = int(pipeline.get("candidate_count") or 0)
    failure_count = int(pipeline.get("failure_count") or 0)
    if require_success:
        _assert(failure_count == 0, f"pipeline failures present: {pipeline_id}")
    if require_candidates:
        _assert(candidate_count >= 1, f"pipeline has no candidates: {pipeline_id}")
    _assert("auth_mode" in pipeline, f"auth mode missing: {pipeline_id}")
    _assert("api_key" not in json.dumps(pipeline).lower(), f"api key leaked: {pipeline_id}")
    _assert("timeout_count" in pipeline, f"timeout count missing: {pipeline_id}")
    _assert("timeout_rate" in pipeline, f"timeout rate missing: {pipeline_id}")
    _assert(
        0.0 <= float(pipeline.get("timeout_rate") or 0.0) <= 1.0,
        f"bad timeout rate: {pipeline_id}",
    )
    _assert(pipeline.get("evidence_level"), f"evidence level missing: {pipeline_id}")
    metrics = pipeline.get("metrics") or {}
    for key in (
        "recall",
        "precision",
        "category_family_accuracy",
        "duplicate_rate",
        "bbox_metrics_available",
        "bbox_recall_at_iou",
        "bbox_precision_at_iou",
        "bbox_category_family_accuracy_at_iou",
        "bbox_false_positive_rate",
        "destination_hint_rate",
        "destination_hint_known_fixture_rate",
        "destination_hint_plausible_rate",
        "actionability_proxy_rate",
        "structured_output_parse_failure_rate",
    ):
        _assert(key in metrics, f"metric {key} missing for {pipeline_id}")
    _assert_api_cost(pipeline)
    _assert_memory_profile(pipeline)
    stages = list(pipeline.get("stage_summary") or [])
    _assert(stages, f"stage summary missing for {pipeline_id}")
    for stage in stages:
        _assert(stage.get("stage"), f"stage name missing: {stage}")
        _assert("producer_id" in stage, f"producer id missing: {stage}")
        _assert("model_id" in stage, f"model id missing: {stage}")
        _assert("latency_ms_avg" in stage, f"stage latency missing: {stage}")
        _assert(stage.get("status"), f"stage status missing: {stage}")
    for overlay in pipeline.get("overlays") or []:
        overlay_path = base_dir / str(overlay)
        _assert(overlay_path.is_file(), f"missing overlay: {overlay_path}")
        _assert(overlay_path.stat().st_size > 0, f"empty overlay: {overlay_path}")


def _assert_prediction(
    base_dir: Path,
    prediction: dict[str, Any],
    *,
    result: dict[str, Any],
) -> None:
    _assert(prediction.get("schema") == PREDICTION_SCHEMA, f"bad prediction schema: {prediction}")
    pipeline_id = str(prediction.get("pipeline_id") or "")
    _assert(pipeline_id, f"prediction pipeline missing: {prediction}")
    _assert(prediction.get("benchmark_row_id"), f"prediction row id missing: {prediction}")
    _assert(prediction.get("observation_id"), f"prediction observation missing: {prediction}")
    capture_context = prediction.get("capture_context") or {}
    _assert(
        capture_context.get("discovered_during"),
        f"discovered_during provenance missing: {prediction}",
    )
    _assert("private_labels" not in prediction, f"private labels in prediction: {prediction}")
    _assert("image" not in prediction, f"raw image in prediction: {prediction}")
    overlay_path = base_dir / str(prediction.get("overlay_path") or "")
    _assert(overlay_path.is_file(), f"prediction overlay missing: {overlay_path}")
    raw_path = base_dir / str(prediction.get("raw_fpv_path") or "")
    _assert(raw_path.is_file(), f"raw FPV artifact missing: {raw_path}")
    pipeline = prediction.get("pipeline") or {}
    _assert(pipeline.get("schema") == PIPELINE_SCHEMA, f"bad pipeline schema: {prediction}")
    _assert(pipeline.get("pipeline_id") == pipeline_id, f"pipeline mismatch: {prediction}")
    _assert(pipeline.get("status") in {"ok", "failed"}, f"bad status: {prediction}")
    stages = list(pipeline.get("stages") or [])
    _assert(stages, f"prediction stages missing: {prediction}")
    for stage in stages:
        _assert(stage.get("stage"), f"stage name missing: {stage}")
        _assert("latency_ms" in stage, f"stage latency missing: {stage}")
        _assert(stage.get("status"), f"stage status missing: {stage}")
    if pipeline.get("status") == "failed":
        _assert(not prediction.get("candidates"), f"failed response has candidates: {prediction}")
        _assert(
            (prediction.get("error") or {}).get("reason"),
            f"failure reason missing: {prediction}",
        )
    else:
        for candidate in prediction.get("candidates") or []:
            _assert_candidate(candidate)
    _assert_diagnostic_evidence(prediction)

    private_allowed = bool((result.get("corpus") or {}).get("private_label_details_included"))
    _assert(private_allowed in {True, False}, "private-label detail flag must be boolean")


def _assert_candidate(candidate: dict[str, Any]) -> None:
    _assert(candidate.get("category"), f"candidate category missing: {candidate}")
    region = candidate.get("image_region") or {}
    _assert(region.get("type") in {"bbox", "point", "verbal_region"}, f"bad region: {candidate}")
    if region.get("type") == "bbox":
        bbox = region.get("value")
        _assert(isinstance(bbox, list) and len(bbox) == 4, f"bad bbox: {candidate}")
        for value in bbox:
            number = float(value)
            _assert(0.0 <= number <= 1.0, f"bbox value out of range: {candidate}")
    _assert("destination_hint" in candidate, f"destination hint evidence missing: {candidate}")


def _assert_family_sweep(result: dict[str, Any]) -> None:
    rows = list(result.get("family_sweep") or [])
    _assert(rows, "family sweep summary missing")
    for row in rows:
        family = str(row.get("model_family") or "")
        _assert(family, f"family sweep row missing family: {row}")
        tested = int(row.get("tested_config_count") or 0)
        _assert(tested >= 1, f"family has no tested configs: {family}")
        successful = int(row.get("successful_config_count") or 0)
        _assert(
            0 <= successful <= tested,
            f"bad successful config count for family {family}: {row}",
        )
        _assert(isinstance(row.get("row_ids"), list), f"family row ids missing: {family}")
        _assert(
            isinstance(row.get("successful_row_ids"), list),
            f"family successful row ids missing: {family}",
        )
        _assert(isinstance(row.get("size_tiers"), list), f"family size tiers missing: {family}")
        _assert(isinstance(row.get("under_sampled"), bool), f"under-sampled flag bad: {family}")
        if successful < 2:
            _assert(row.get("under_sampled") is True, f"family not marked under-sampled: {family}")
        if row.get("under_sampled"):
            _assert(row.get("under_sampled_reason"), f"under-sampled reason missing: {family}")


def _assert_diagnostic_evidence(prediction: dict[str, Any]) -> None:
    diagnostics = prediction.get("diagnostic_evidence") or {}
    _assert(
        diagnostics.get("schema") == "visual_grounding_diagnostics_v1",
        f"bad diagnostics schema: {prediction}",
    )
    _assert(
        diagnostics.get("private_truth_included") is False,
        f"private truth leaked in diagnostics: {prediction}",
    )
    for key in ("raw_proposal_count", "rejected_proposal_count"):
        _assert(key in diagnostics, f"{key} missing in diagnostics: {prediction}")
    text = json.dumps(diagnostics).lower()
    for forbidden in ("private_labels", "bytes_base64", "visual_grounding_api_key", "api_key"):
        _assert(forbidden not in text, f"diagnostics contain forbidden token {forbidden}")


def _assert_detector_probe_recommendation(result: dict[str, Any]) -> None:
    detector_probe = result.get("detector_probe_recommendation")
    _assert(isinstance(detector_probe, dict), "detector probe recommendation missing")
    _assert(
        detector_probe.get("schema") == "visual_grounding_detector_probe_recommendation_v1",
        "bad detector probe recommendation schema",
    )
    policy = detector_probe.get("policy") or {}
    _assert(policy.get("control_pipeline_id") == "sim", "detector probe control must be sim")
    selected = list(detector_probe.get("selected_end_to_end_pipelines") or [])
    _assert(selected and selected[0] == "sim", "detector probe set must include sim control first")
    _assert(
        len(selected) <= int(policy.get("max_total_pipelines") or 0),
        "detector probe set exceeds cap",
    )
    for key in detector_probe:
        _assert(
            "direct_vlm" not in key and "proposer_plus_refiner" not in key,
            f"detector probe includes retired slot key: {key}",
        )
    for key in policy:
        _assert(
            "direct_vlm" not in key and "proposer_plus_refiner" not in key,
            f"detector probe policy includes retired slot key: {key}",
        )
    selected_rows = list(detector_probe.get("selected") or [])
    _assert(len(selected_rows) == len(selected), "detector probe selected rows do not match ids")
    for row in selected_rows:
        _assert(row.get("slot"), f"detector probe slot missing: {row}")
        _assert(row.get("pipeline_id"), f"detector probe pipeline missing: {row}")
        _assert(row.get("reason"), f"detector probe reason missing: {row}")
    _assert(
        isinstance(detector_probe.get("real_stage_provenance_present"), bool),
        "detector probe real-stage flag must be boolean",
    )
    _assert(
        isinstance(detector_probe.get("selected_real_stage_provenance_complete"), bool),
        "detector probe selected real-stage completion flag must be boolean",
    )
    _assert(
        isinstance(detector_probe.get("requires_real_stage_provenance_before_probe"), bool),
        "detector probe real-stage requirement flag must be boolean",
    )


def _assert_api_cost(pipeline: dict[str, Any]) -> None:
    pipeline_id = str(pipeline.get("pipeline_id") or "")
    api_cost = pipeline.get("api_cost")
    _assert(isinstance(api_cost, dict), f"api cost summary missing for {pipeline_id}")
    for key in (
        "available",
        "source",
        "reported_stage_count",
        "total_usd",
        "token_usage_available",
        "token_usage_reported_stage_count",
        "token_usage",
    ):
        _assert(key in api_cost, f"api cost key {key} missing for {pipeline_id}")
    if api_cost.get("total_usd") is not None:
        _assert(float(api_cost["total_usd"]) >= 0.0, f"negative api cost for {pipeline_id}")
    token_usage = api_cost.get("token_usage") or {}
    _assert(isinstance(token_usage, dict), f"token usage summary must be an object: {pipeline_id}")


def _assert_memory_profile(pipeline: dict[str, Any]) -> None:
    pipeline_id = str(pipeline.get("pipeline_id") or "")
    memory = pipeline.get("memory_profile")
    _assert(isinstance(memory, dict), f"memory profile summary missing for {pipeline_id}")
    for key in ("available", "source", "reported_stage_count", "peak_mb"):
        _assert(key in memory, f"memory profile key {key} missing for {pipeline_id}")
    if memory.get("peak_mb") is not None:
        _assert(float(memory["peak_mb"]) >= 0.0, f"negative memory peak for {pipeline_id}")


def _assert_private_label_detail_policy(result: dict[str, Any], *, allow: bool) -> None:
    included = bool((result.get("corpus") or {}).get("private_label_details_included"))
    has_details = any(
        "private_label_details" in pipeline for pipeline in result.get("pipelines") or []
    )
    _assert(included == has_details, "private label detail flag does not match artifacts")
    if has_details and not allow:
        _assert(False, "private label details require --allow-private-label-details")


def _assert_no_secret_text(text: str, label: str) -> None:
    lowered = text.lower()
    forbidden = ("bearer ", "visual_grounding_api_key", "api_key", "secret-token")
    for token in forbidden:
        _assert(token not in lowered, f"{label} contains forbidden token {token!r}")


def _load_json(path: Path) -> dict[str, Any]:
    _assert(path.is_file(), f"missing JSON file: {path}")
    try:
        return read_json_object(path, label="JSON file")
    except ValueError as exc:
        message = str(exc).replace("JSON file source", "JSON file", 1)
        raise AssertionError(message) from exc


def _load_jsonl(path: Path) -> list[dict[str, Any]]:
    try:
        return read_jsonl_objects(path, label="JSONL")
    except (FileNotFoundError, ValueError) as exc:
        message = str(exc).replace("JSONL source row", "JSONL row", 1)
        raise AssertionError(message) from exc


def _assert(condition: Any, message: str) -> None:
    if not condition:
        raise AssertionError(message)
