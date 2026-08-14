from __future__ import annotations

import base64
import io
from pathlib import Path
from typing import Any

from PIL import Image, ImageDraw

from roboclaws.evals.visual_grounding_benchmark.scoring import (
    category_family as _category_family,
)
from roboclaws.household.visual_grounding import (
    VisualGroundingClientConfig,
)


def _load_observation_image(
    observation: dict[str, Any],
    corpus_dir: Path,
) -> tuple[Image.Image, bytes]:
    image_spec = observation.get("image") or {}
    if image_spec.get("source") == "path":
        path = corpus_dir / str(image_spec.get("path") or "")
        image = Image.open(path).convert("RGB")
    elif image_spec.get("source") == "base64":
        data = base64.b64decode(str(image_spec.get("bytes_base64") or ""))
        image = Image.open(io.BytesIO(data)).convert("RGB")
    else:
        image = _synthetic_image(image_spec)
    buffer = io.BytesIO()
    image.save(buffer, format="JPEG", quality=80)
    return image, buffer.getvalue()


def _synthetic_image(image_spec: dict[str, Any]) -> Image.Image:
    width = int(image_spec.get("width") or 320)
    height = int(image_spec.get("height") or 240)
    background = _rgb(image_spec.get("background"), default=(220, 220, 220))
    image = Image.new("RGB", (width, height), background)
    draw = ImageDraw.Draw(image)
    for item in image_spec.get("objects") or []:
        bbox = item.get("bbox") or [0.25, 0.25, 0.25, 0.2]
        x, y, w, h = _bbox_pixels(bbox, width, height)
        color = _rgb(item.get("color"), default=(240, 80, 80))
        draw.rectangle((x, y, x + w, y + h), fill=color, outline=(34, 34, 34), width=2)
        label = str(item.get("label") or "")
        if label:
            draw.text((x + 4, y + 4), label, fill=(20, 20, 20))
    return image


def _write_jpeg(path: Path, image: Image.Image) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    image.save(path, format="JPEG", quality=80)


def _write_overlay(path: Path, image: Image.Image, candidates: list[dict[str, Any]]) -> None:
    overlay = image.copy()
    draw = ImageDraw.Draw(overlay)
    for candidate in candidates:
        region = candidate.get("image_region") or {}
        if region.get("type") != "bbox":
            continue
        x, y, w, h = _bbox_pixels(region.get("value") or [0, 0, 0, 0], image.width, image.height)
        draw.rectangle((x, y, x + w, y + h), outline=(26, 115, 232), width=3)
        label = str(candidate.get("category") or "candidate")
        draw.text((x + 4, max(0, y - 14)), label, fill=(26, 77, 160))
    _write_jpeg(path, overlay)


def _bbox_pixels(value: Any, width: int, height: int) -> tuple[int, int, int, int]:
    numbers = [float(item) for item in value]
    return (
        round(numbers[0] * width),
        round(numbers[1] * height),
        round(numbers[2] * width),
        round(numbers[3] * height),
    )


def _public_candidates(
    candidates: list[dict[str, Any]],
    category_family_map: dict[str, str],
) -> list[dict[str, Any]]:
    public: list[dict[str, Any]] = []
    for candidate in candidates:
        region = candidate.get("image_region") or {}
        bbox = region.get("value") if region.get("type") == "bbox" else None
        public.append(
            {
                "category": str(candidate.get("category") or ""),
                "category_family": _category_family(
                    str(candidate.get("category") or ""),
                    category_family_map,
                ),
                "image_region": region,
                "bbox": bbox,
                "confidence": candidate.get("confidence"),
                "evidence_note": str(candidate.get("evidence_note") or ""),
                "source_fixture_id": str(candidate.get("source_fixture_id") or ""),
                "destination_hint": dict(candidate.get("destination_hint") or {}),
            }
        )
    return public


def _public_diagnostics(diagnostics: dict[str, Any]) -> dict[str, Any]:
    if not diagnostics:
        return {
            "schema": "visual_grounding_diagnostics_v1",
            "raw_proposal_count": 0,
            "rejected_proposal_count": 0,
            "rejection_reasons": [],
            "raw_proposals": [],
            "rejected_proposals": [],
            "private_truth_included": False,
        }
    raw_proposals = list(diagnostics.get("raw_proposals") or [])
    rejected = list(diagnostics.get("rejected_proposals") or [])
    return {
        "schema": str(diagnostics.get("schema") or "visual_grounding_diagnostics_v1"),
        "diagnostic_mode": str(diagnostics.get("diagnostic_mode") or ""),
        "raw_proposal_count": len(raw_proposals),
        "rejected_proposal_count": len(rejected),
        "rejection_reasons": sorted(
            {str(item.get("reason") or "") for item in rejected if str(item.get("reason") or "")}
        ),
        "raw_proposals": raw_proposals,
        "rejected_proposals": rejected,
        "private_truth_included": bool(diagnostics.get("private_truth_included", False)),
    }


def _api_cost_summary(predictions: list[dict[str, Any]]) -> dict[str, Any]:
    total_cost = 0.0
    cost_count = 0
    usage_totals = {
        "prompt_tokens": 0,
        "completion_tokens": 0,
        "total_tokens": 0,
    }
    usage_count = 0
    for stage in _prediction_stages(predictions):
        cost = _float_or_none(stage.get("api_cost_usd"))
        if cost is not None:
            total_cost += cost
            cost_count += 1
        usage = stage.get("token_usage") or {}
        if isinstance(usage, dict):
            collected = False
            for key in usage_totals:
                value = _int_or_none(usage.get(key))
                if value is not None:
                    usage_totals[key] += value
                    collected = True
            if collected:
                usage_count += 1
    return {
        "available": cost_count > 0,
        "source": "service_stage_metadata" if cost_count else "not_reported_by_service",
        "reported_stage_count": cost_count,
        "total_usd": round(total_cost, 8) if cost_count else None,
        "token_usage_available": usage_count > 0,
        "token_usage_reported_stage_count": usage_count,
        "token_usage": usage_totals if usage_count else {},
    }


def _memory_profile_summary(predictions: list[dict[str, Any]]) -> dict[str, Any]:
    peak_values: list[float] = []
    for stage in _prediction_stages(predictions):
        memory = stage.get("memory_profile") or {}
        if isinstance(memory, dict):
            value = _float_or_none(memory.get("peak_mb") or memory.get("rss_peak_mb"))
            if value is not None:
                peak_values.append(value)
        value = _float_or_none(stage.get("memory_peak_mb"))
        if value is not None:
            peak_values.append(value)
    return {
        "available": bool(peak_values),
        "source": "service_stage_metadata" if peak_values else "not_reported_by_service",
        "reported_stage_count": len(peak_values),
        "peak_mb": round(max(peak_values), 3) if peak_values else None,
    }


def _prediction_stages(predictions: list[dict[str, Any]]) -> list[dict[str, Any]]:
    stages: list[dict[str, Any]] = []
    for prediction in predictions:
        pipeline = prediction.get("pipeline") or {}
        for stage in pipeline.get("stages") or []:
            if isinstance(stage, dict):
                stages.append(stage)
    return stages


def _prediction_timed_out(prediction: dict[str, Any]) -> bool:
    pipeline = prediction.get("pipeline") or {}
    if str(pipeline.get("failure_reason") or "") == "timeout":
        return True
    if str((prediction.get("error") or {}).get("reason") or "") == "timeout":
        return True
    return any(
        str(stage.get("status") or "") == "timeout" for stage in pipeline.get("stages") or []
    )


def _pipeline_evidence_level(predictions: list[dict[str, Any]]) -> str:
    diagnostics_modes = {
        str((prediction.get("diagnostic_evidence") or {}).get("diagnostic_mode") or "")
        for prediction in predictions
    }
    stage_versions = {
        str(stage.get("version") or "")
        for stage in _prediction_stages(predictions)
        if str(stage.get("version") or "")
    }
    if "real-sidecar-adapter-v1" in stage_versions:
        return "real_detector_sidecar"
    if any(mode.startswith("real_") for mode in diagnostics_modes):
        return "real_detector_sidecar"
    if all(
        (prediction.get("pipeline") or {}).get("status") == "failed" for prediction in predictions
    ):
        return "failure_only"
    return "service_reported"


def _public_benchmark_row(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "row_id": str(row.get("row_id") or ""),
        "pipeline_id": str(row.get("pipeline_id") or ""),
        "model_family": str(row.get("model_family") or ""),
        "model_id": str(row.get("model_id") or ""),
        "size_tier": str(row.get("size_tier") or ""),
        "runtime_parameters": dict(row.get("runtime_parameters") or {}),
    }


def _proposer_request(
    benchmark_row: dict[str, Any],
    config: VisualGroundingClientConfig,
) -> dict[str, Any]:
    pipeline_id = str(benchmark_row["pipeline_id"])
    first = pipeline_id.split("+", maxsplit=1)[0]
    request = {
        "producer_id": config.proposer_id or first,
        "model_id": config.proposer_model_id or str(benchmark_row.get("model_id") or ""),
    }
    runtime_parameters = dict(benchmark_row.get("runtime_parameters") or {})
    if runtime_parameters:
        request["runtime_parameters"] = runtime_parameters
    return request


def _float_or_none(value: Any) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _int_or_none(value: Any) -> int | None:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _recommendation_reason(row: dict[str, Any]) -> str:
    if not row:
        return "No successful pipeline result was available."
    if row.get("score_basis") == "bbox_iou":
        return (
            "Highest weighted bbox-aware benchmark score from visible-object "
            "recall at IoU threshold, bbox precision, category-family accuracy, "
            "and failure-rate metrics."
        )
    return (
        "Highest weighted benchmark score from recall, precision, category-family "
        "accuracy, and failure-rate metrics."
    )


def _rgb(value: Any, *, default: tuple[int, int, int]) -> tuple[int, int, int]:
    if isinstance(value, list) and len(value) == 3:
        return tuple(max(0, min(255, int(item))) for item in value)
    return default
