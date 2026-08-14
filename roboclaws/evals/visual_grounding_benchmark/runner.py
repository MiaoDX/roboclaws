from __future__ import annotations

import argparse
import base64
import json
import math
import os
import sys
import time
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from roboclaws.core.json_sources import read_json_object
from roboclaws.evals.visual_grounding_benchmark.artifacts import (
    _load_observation_image,
    _proposer_request,
    _public_benchmark_row,
    _public_candidates,
    _public_diagnostics,
    _recommendation_reason,
    _write_jpeg,
    _write_overlay,
)
from roboclaws.evals.visual_grounding_benchmark.common import (
    pipeline_family as _pipeline_family,
)
from roboclaws.evals.visual_grounding_benchmark.common import (
    safe_id as _safe_id,
)
from roboclaws.evals.visual_grounding_benchmark.common import (
    timestamp as _stamp,
)
from roboclaws.evals.visual_grounding_benchmark.report import _render_report
from roboclaws.evals.visual_grounding_benchmark.summary import (
    _detector_probe_recommendation,
    _family_sweep_summary,
    _rank_pipelines,
    _summarize_pipeline,
)
from roboclaws.evals.visual_grounding_benchmark.validation import validate_benchmark_path
from roboclaws.household.visual_grounding import (
    DEFAULT_VISUAL_GROUNDING_BASE_URL,
    DEFAULT_VISUAL_GROUNDING_TIMEOUT_S,
    HttpVisualGroundingClient,
    VisualGroundingClientConfig,
    VisualGroundingContractError,
    pipeline_summary_from_response,
    safe_runtime_parameters,
    validate_visual_grounding_response,
    visual_grounding_failure_response,
    visual_grounding_request,
)

CORPUS_SCHEMA = "visual_grounding_benchmark_corpus_v1"
RESULT_SCHEMA = "visual_grounding_benchmark_result_v1"
PREDICTION_SCHEMA = "visual_grounding_prediction_v1"
RETIRED_FAKE_PIPELINE_IDS = frozenset({"fake-http", "contract-fake"})


@dataclass(frozen=True)
class BenchmarkRequest:
    corpus: Path
    output_dir: Path
    pipelines: tuple[str, ...]
    matrix: Path | None
    base_url: str
    timeout_s: float
    include_private_label_details: bool = False


@dataclass(frozen=True)
class BenchmarkRunResult:
    output_dir: Path
    result_path: Path
    predictions_path: Path
    report_path: Path


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Run a perception-isolated visual-grounding HTTP benchmark."
    )
    parser.add_argument(
        "--corpus",
        type=Path,
        default=Path("harness/visual_grounding/smoke_corpus.json"),
        help="Visual-grounding benchmark corpus manifest.",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=None,
        help="Output directory for result, report, predictions, and overlays.",
    )
    parser.add_argument(
        "--pipeline",
        action="append",
        default=[],
        help="Pipeline id to run. May be repeated or comma-separated.",
    )
    parser.add_argument(
        "--matrix",
        type=Path,
        default=None,
        help=(
            "Optional benchmark matrix JSON. Rows version model ids, size tiers, "
            "and runtime knobs; --pipeline then acts as a row/pipeline filter."
        ),
    )
    parser.add_argument(
        "--base-url",
        default=os.environ.get("VISUAL_GROUNDING_BASE_URL", DEFAULT_VISUAL_GROUNDING_BASE_URL),
        help="External visual-grounding service base URL.",
    )
    parser.add_argument(
        "--timeout-s",
        type=_positive_seconds,
        default=_positive_seconds(
            os.environ.get("VISUAL_GROUNDING_TIMEOUT_S", DEFAULT_VISUAL_GROUNDING_TIMEOUT_S),
        ),
    )
    parser.add_argument(
        "--include-private-label-details",
        action="store_true",
        help="Include per-observation private label details in the benchmark result/report.",
    )
    parser.add_argument("--expect-pipeline", default="")
    parser.add_argument("--require-success", action="store_true")
    parser.add_argument("--require-candidates", action="store_true")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    output_dir = args.output_dir or Path("output/visual-grounding-benchmark") / _stamp()
    run = run_benchmark(
        BenchmarkRequest(
            corpus=args.corpus,
            output_dir=output_dir,
            pipelines=tuple(args.pipeline),
            matrix=args.matrix,
            base_url=args.base_url,
            timeout_s=args.timeout_s,
            include_private_label_details=args.include_private_label_details,
        )
    )
    validate_benchmark_path(
        run.result_path,
        expect_pipeline=args.expect_pipeline,
        require_success=args.require_success,
        require_candidates=args.require_candidates,
        allow_private_label_details=args.include_private_label_details,
    )
    print(f"ok: visual grounding benchmark artifacts passed ({run.output_dir})")
    return 0


def run_benchmark(request: BenchmarkRequest) -> BenchmarkRunResult:
    output_dir = request.output_dir
    output_dir.mkdir(parents=True, exist_ok=True)

    corpus = _load_corpus(request.corpus)
    benchmark_rows = _benchmark_rows(request)
    predictions_path = output_dir / "visual_grounding_predictions.jsonl"
    all_predictions: list[dict[str, Any]] = []
    pipeline_results: list[dict[str, Any]] = []

    with predictions_path.open("w", encoding="utf-8") as predictions_file:
        for row in benchmark_rows:
            pipeline_id = str(row["pipeline_id"])
            config = VisualGroundingClientConfig(
                pipeline_id=pipeline_id,
                base_url=request.base_url,
                timeout_s=request.timeout_s,
                api_key=os.environ.get("VISUAL_GROUNDING_API_KEY", ""),
                proposer_id=str(
                    row.get("producer_id")
                    or row.get("proposer_id")
                    or os.environ.get("VISUAL_GROUNDING_PROPOSER_ID", "")
                ),
                proposer_model_id=str(
                    row.get("model_id")
                    or row.get("proposer_model_id")
                    or os.environ.get("VISUAL_GROUNDING_PROPOSER_MODEL_ID", "")
                ),
            )
            client = HttpVisualGroundingClient(config)
            predictions = _run_pipeline(
                corpus=corpus,
                corpus_path=request.corpus,
                output_dir=output_dir,
                benchmark_row=row,
                client=client,
            )
            for prediction in predictions:
                predictions_file.write(json.dumps(prediction, sort_keys=True) + "\n")
            all_predictions.extend(predictions)
            pipeline_results.append(
                _summarize_pipeline(
                    pipeline_id=pipeline_id,
                    benchmark_row=row,
                    predictions=predictions,
                    corpus=corpus,
                    auth_mode=config.auth_mode,
                    service_config=config.redacted_metadata(),
                    include_private_label_details=request.include_private_label_details,
                )
            )

    ranking = _rank_pipelines(pipeline_results)
    recommendation = ranking[0] if ranking else {}
    detector_probe_recommendation = _detector_probe_recommendation(pipeline_results, ranking)
    result = {
        "schema": RESULT_SCHEMA,
        "generated_at": datetime.now(UTC).isoformat(timespec="seconds"),
        "corpus": {
            "path": str(request.corpus),
            "schema": corpus["schema"],
            "name": corpus.get("name", ""),
            "observation_count": len(corpus["observations"]),
            "private_labels_in_requests": False,
            "private_label_details_included": request.include_private_label_details,
        },
        "pipelines": pipeline_results,
        "family_sweep": _family_sweep_summary(pipeline_results),
        "ranking": ranking,
        "recommendation": {
            "pipeline_id": recommendation.get("pipeline_id", ""),
            "score": recommendation.get("score", 0.0),
            "reason": _recommendation_reason(recommendation),
        },
        "detector_probe_recommendation": detector_probe_recommendation,
        "artifacts": {
            "predictions_jsonl": predictions_path.name,
            "report_html": "visual_grounding_benchmark_report.html",
            "overlays_dir": "overlays",
        },
    }
    result_path = output_dir / "visual_grounding_benchmark_result.json"
    result_path.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    report_path = output_dir / "visual_grounding_benchmark_report.html"
    report_path.write_text(
        _render_report(result=result, predictions=all_predictions),
        encoding="utf-8",
    )
    print(f"visual grounding benchmark result: {result_path}")
    print(f"visual grounding benchmark report: {report_path}")
    return BenchmarkRunResult(
        output_dir=output_dir,
        result_path=result_path,
        predictions_path=predictions_path,
        report_path=report_path,
    )


def _load_corpus(path: Path) -> dict[str, Any]:
    corpus = _read_source_json_object(path, label="visual grounding benchmark corpus")
    if corpus.get("schema") != CORPUS_SCHEMA:
        raise SystemExit(f"unsupported corpus schema in {path}")
    observations = corpus.get("observations")
    if not isinstance(observations, list) or not observations:
        raise SystemExit(f"corpus has no observations: {path}")
    return corpus


def _benchmark_rows(request: BenchmarkRequest) -> list[dict[str, Any]]:
    filters = set(_pipeline_ids(request.pipelines)) if request.pipelines else set()
    if request.matrix is None:
        pipeline_ids = _pipeline_ids(request.pipelines)
        return [_default_benchmark_row(pipeline_id) for pipeline_id in pipeline_ids]

    matrix = _read_source_json_object(request.matrix, label="visual grounding benchmark matrix")
    if matrix.get("schema") != "visual_grounding_benchmark_matrix_v1":
        raise SystemExit(f"unsupported benchmark matrix schema in {request.matrix}")
    raw_rows = matrix.get("rows")
    if not isinstance(raw_rows, list):
        raise SystemExit(f"benchmark matrix rows must be a list: {request.matrix}")
    rows = [_normalize_benchmark_row(row, source=request.matrix) for row in raw_rows]
    if not rows:
        raise SystemExit(f"benchmark matrix has no rows: {request.matrix}")
    if filters:
        rows = [
            row
            for row in rows
            if str(row.get("row_id") or "") in filters
            or str(row.get("pipeline_id") or "") in filters
            or str(row.get("model_family") or "") in filters
        ]
    if not rows:
        raise SystemExit(f"benchmark matrix filters selected no rows: {sorted(filters)}")
    return rows


def _read_source_json_object(path: Path, *, label: str) -> dict[str, Any]:
    try:
        return read_json_object(path, label=label)
    except (FileNotFoundError, ValueError) as exc:
        raise SystemExit(str(exc)) from exc


def _default_benchmark_row(pipeline_id: str) -> dict[str, Any]:
    _reject_retired_fake_pipeline(pipeline_id)
    family = _pipeline_family(pipeline_id)
    return {
        "row_id": pipeline_id,
        "pipeline_id": pipeline_id,
        "model_family": family,
        "model_id": "",
        "size_tier": "unspecified",
        "runtime_parameters": {},
        "under_sampled_reason": "ad-hoc pipeline run without a matrix row",
    }


def _normalize_benchmark_row(row: Any, *, source: Path) -> dict[str, Any]:
    if not isinstance(row, dict):
        raise SystemExit(f"benchmark matrix rows must contain JSON objects: {source}")
    pipeline_id = str(row.get("pipeline_id") or "").strip()
    if not pipeline_id:
        raise SystemExit(f"benchmark matrix row missing pipeline_id: {row}")
    _reject_retired_fake_pipeline(pipeline_id)
    runtime_parameters = safe_runtime_parameters(
        row.get("runtime_parameters") or row.get("knobs") or {}
    )
    model_family = str(
        row.get("model_family") or row.get("family") or _pipeline_family(pipeline_id)
    )
    model_id = str(row.get("model_id") or row.get("proposer_model_id") or "")
    size_tier = str(row.get("size_tier") or row.get("size") or "unspecified")
    row_id = str(row.get("row_id") or "").strip()
    if not row_id:
        row_id = _safe_id("-".join(part for part in (pipeline_id, model_family, size_tier) if part))
    normalized = {
        "row_id": row_id,
        "pipeline_id": pipeline_id,
        "model_family": model_family,
        "model_id": model_id,
        "size_tier": size_tier,
        "producer_id": str(row.get("producer_id") or row.get("proposer_id") or ""),
        "proposer_model_id": model_id,
        "runtime_parameters": runtime_parameters,
        "under_sampled_reason": str(row.get("under_sampled_reason") or ""),
        "notes": str(row.get("notes") or ""),
    }
    return normalized


def _positive_seconds(value: Any) -> float:
    try:
        parsed = float(value)
    except (TypeError, ValueError) as exc:
        raise argparse.ArgumentTypeError(
            f"visual grounding benchmark timeout must be a positive finite number, got {value!r}"
        ) from exc
    if not math.isfinite(parsed) or parsed <= 0:
        raise argparse.ArgumentTypeError(
            f"visual grounding benchmark timeout must be a positive finite number, got {value!r}"
        )
    return parsed


def _pipeline_ids(raw_values: Sequence[str]) -> list[str]:
    values = raw_values or [os.environ.get("VISUAL_GROUNDING_PIPELINE_ID", "grounding-dino")]
    pipeline_ids: list[str] = []
    for value in values:
        pipeline_ids.extend(part.strip() for part in str(value).split(",") if part.strip())
    seen: set[str] = set()
    unique = [item for item in pipeline_ids if not (item in seen or seen.add(item))]
    selected = unique or ["grounding-dino"]
    for pipeline_id in selected:
        _reject_retired_fake_pipeline(pipeline_id)
    return selected


def _reject_retired_fake_pipeline(pipeline_id: str) -> None:
    if pipeline_id in RETIRED_FAKE_PIPELINE_IDS:
        expected = "grounding-dino, yoloe, yolo-world, or omdet-turbo"
        raise SystemExit(
            f"retired fake visual-grounding pipeline {pipeline_id!r} is not valid "
            f"benchmark evidence; use {expected}, or record missing-sidecar evidence."
        )


def _run_pipeline(
    *,
    corpus: dict[str, Any],
    corpus_path: Path,
    output_dir: Path,
    benchmark_row: dict[str, Any],
    client: HttpVisualGroundingClient,
) -> list[dict[str, Any]]:
    predictions: list[dict[str, Any]] = []
    pipeline_id = str(benchmark_row["pipeline_id"])
    category_family_map = {
        str(key): str(value) for key, value in (corpus.get("category_family_map") or {}).items()
    }
    for observation in corpus["observations"]:
        observation_id = _safe_id(str(observation.get("observation_id") or "observation"))
        image, image_bytes = _load_observation_image(observation, corpus_path.parent)
        raw_rel = Path("raw_fpv") / f"{observation_id}.jpg"
        _write_jpeg(output_dir / raw_rel, image)
        request = visual_grounding_request(
            run_id=str(corpus.get("name") or "visual-grounding-benchmark"),
            raw_observation={
                "observation_id": str(observation.get("observation_id") or ""),
                "waypoint_id": str(observation.get("waypoint_id") or ""),
                "room_id": str(observation.get("room_id") or ""),
                "artifact_status": "benchmark_fixture",
            },
            category_hints=[str(item) for item in observation.get("category_hints") or []],
            public_map_hints={
                "schema": "visual_grounding_public_map_hints_v1",
                "source": "visual_grounding_benchmark_public_fixture_hints",
                "fixture_hints": list(observation.get("static_fixture_projection") or []),
                "private_truth_included": False,
            },
            pipeline_id=pipeline_id,
            image={
                "mime_type": "image/jpeg",
                "bytes_base64": base64.b64encode(image_bytes).decode("ascii"),
                "width": int(image.width),
                "height": int(image.height),
            },
            proposer=_proposer_request(benchmark_row, client.config),
        )

        started = time.monotonic()
        parse_failed = False
        try:
            response = client.request_candidates(request)
            validate_visual_grounding_response(response)
        except VisualGroundingContractError as exc:
            parse_failed = True
            response = visual_grounding_failure_response(
                pipeline_id=pipeline_id,
                reason="parse_failure",
                message=str(exc),
                latency_ms=round((time.monotonic() - started) * 1000),
            )
        elapsed_ms = round((time.monotonic() - started) * 1000)
        pipeline_summary = pipeline_summary_from_response(
            response,
            auth_mode=client.config.auth_mode,
        )
        pipeline_summary["request_latency_ms"] = elapsed_ms
        pipeline_summary["parse_failed"] = parse_failed
        candidates = list(response.get("candidates") or [])
        diagnostics = _public_diagnostics(response.get("diagnostics") or {})
        overlay_rel = Path("overlays") / observation_id / f"{_safe_id(pipeline_id)}.jpg"
        _write_overlay(output_dir / overlay_rel, image, candidates)
        prediction = {
            "schema": PREDICTION_SCHEMA,
            "benchmark_row_id": str(benchmark_row.get("row_id") or pipeline_id),
            "pipeline_id": pipeline_id,
            "observation_id": str(observation.get("observation_id") or ""),
            "waypoint_id": str(observation.get("waypoint_id") or ""),
            "room_id": str(observation.get("room_id") or ""),
            "capture_context": dict(observation.get("capture_context") or {}),
            "public_context": {
                "category_hints": list(observation.get("category_hints") or []),
                "static_fixture_projection_count": len(
                    observation.get("static_fixture_projection") or []
                ),
            },
            "raw_fpv_path": str(raw_rel),
            "overlay_path": str(overlay_rel),
            "pipeline": pipeline_summary,
            "benchmark_row": _public_benchmark_row(benchmark_row),
            "candidate_count": len(candidates),
            "candidates": _public_candidates(candidates, category_family_map),
            "diagnostic_evidence": diagnostics,
        }
        if response.get("status") == "failed":
            prediction["error"] = dict(response.get("error") or {})
        predictions.append(prediction)
    return predictions


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except AssertionError as exc:
        print(f"error: {exc}", file=sys.stderr)
        raise SystemExit(1) from exc
