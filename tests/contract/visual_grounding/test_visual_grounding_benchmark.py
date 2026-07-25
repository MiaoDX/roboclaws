from __future__ import annotations

import json
import subprocess
import sys
import threading
from http.server import ThreadingHTTPServer
from pathlib import Path

from scripts.visual_grounding.adapters import (
    REAL_ROUTER_PIPELINE_ID,
    _set_yolo_classes_if_needed,
    _yolo_prompt_labels,
    effective_pipeline_id,
    pipeline_request_is_allowed,
    visual_grounding_adapter_catalog,
)
from scripts.visual_grounding.run_visual_grounding_benchmark import (
    _family_sweep_summary,
    _score_predictions,
)
from scripts.visual_grounding.serve_visual_grounding_service import (
    make_handler as make_configurable_handler,
)

REPO_ROOT = Path(__file__).resolve().parents[3]
CORPUS = REPO_ROOT / "harness" / "visual_grounding" / "smoke_corpus.json"
FIRST_WAVE_MATRIX = (
    REPO_ROOT / "harness" / "visual_grounding" / "first_wave_gpu_sidecar_matrix.json"
)
RUNNER = REPO_ROOT / "scripts" / "visual_grounding" / "run_visual_grounding_benchmark.py"
CHECKER = REPO_ROOT / "scripts" / "visual_grounding" / "check_visual_grounding_benchmark_result.py"


def test_visual_grounding_yolo_expands_cleanup_family_hints_for_open_vocab() -> None:
    labels = _yolo_prompt_labels(["food", "dish", "electronics", "pillow"])

    assert labels[:4] == ["food", "apple", "potato", "bread"]
    assert "plate" in labels
    assert "remote control" in labels
    assert "cushion" in labels
    assert len(labels) == len(set(labels))


def test_visual_grounding_yolo_world_reuses_class_prompts_without_rebuilding() -> None:
    class WorldModel:
        def __init__(self) -> None:
            self.clip_model = object()

    class FakeYoloWorld:
        def __init__(self) -> None:
            self.model = WorldModel()
            self.calls: list[list[str]] = []

        def set_classes(self, labels: list[str]) -> None:
            self.calls.append(list(labels))
            self.model.clip_model = object()

    model = FakeYoloWorld()

    _set_yolo_classes_if_needed(model, ["food", "dish"], producer_id="yolo-world")
    first_clip_model = model.model.clip_model
    _set_yolo_classes_if_needed(model, ["food", "dish"], producer_id="yolo-world")
    _set_yolo_classes_if_needed(model, ["food", "toy"], producer_id="yolo-world")

    assert model.calls == [["food", "dish"], ["food", "toy"]]
    assert model.model.clip_model is not first_clip_model


def test_visual_grounding_real_router_allows_requested_real_pipeline() -> None:
    selected = effective_pipeline_id(
        configured_pipeline_id=REAL_ROUTER_PIPELINE_ID,
        requested_pipeline_id="grounding-dino",
    )

    assert selected == "grounding-dino"
    assert pipeline_request_is_allowed(
        configured_pipeline_id=REAL_ROUTER_PIPELINE_ID,
        requested_pipeline_id="yoloe",
        effective_pipeline_id="yoloe",
    )
    catalog = visual_grounding_adapter_catalog()
    assert catalog["real_router_pipeline_id"] == REAL_ROUTER_PIPELINE_ID
    assert catalog["default_pipeline_id"] == "grounding-dino"
    assert "contract_fake_pipeline_id" not in catalog


def test_visual_grounding_benchmark_rejects_fake_http_pipeline(tmp_path: Path) -> None:
    result = subprocess.run(
        [
            sys.executable,
            str(RUNNER),
            "--corpus",
            str(CORPUS),
            "--output-dir",
            str(tmp_path),
            "--pipeline",
            "fake-http",
        ],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 1
    assert "retired fake visual-grounding pipeline 'fake-http'" in result.stderr


def test_visual_grounding_benchmark_rejects_non_positive_timeout(tmp_path: Path) -> None:
    result = subprocess.run(
        [
            sys.executable,
            str(RUNNER),
            "--corpus",
            str(CORPUS),
            "--output-dir",
            str(tmp_path),
            "--pipeline",
            "grounding-dino",
            "--timeout-s",
            "0",
        ],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 2
    assert "visual grounding benchmark timeout must be a positive finite number" in result.stderr
    assert not (tmp_path / "visual_grounding_benchmark_result.json").exists()


def test_visual_grounding_benchmark_rejects_contract_fake_matrix_row(
    tmp_path: Path,
) -> None:
    matrix = tmp_path / "matrix.json"
    matrix.write_text(
        json.dumps(
            {
                "schema": "visual_grounding_benchmark_matrix_v1",
                "rows": [{"row_id": "fake", "pipeline_id": "contract-fake"}],
            }
        ),
        encoding="utf-8",
    )

    result = subprocess.run(
        [
            sys.executable,
            str(RUNNER),
            "--corpus",
            str(CORPUS),
            "--output-dir",
            str(tmp_path / "benchmark"),
            "--matrix",
            str(matrix),
        ],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 1
    assert "retired fake visual-grounding pipeline 'contract-fake'" in result.stderr


def test_visual_grounding_checker_allows_zero_candidate_success_without_candidate_gate(
    tmp_path: Path,
) -> None:
    corpus = tmp_path / "corpus.json"
    corpus.write_text(
        json.dumps(
            {
                "schema": "visual_grounding_benchmark_corpus_v1",
                "name": "zero-candidate-success",
                "category_family_map": {"dish": "dish"},
                "observations": [
                    {
                        "observation_id": "raw_fpv_room_2_empty_001",
                        "waypoint_id": "room_2_scan_1",
                        "room_id": "room_2",
                        "capture_context": {"discovered_during": "waypoint_observe"},
                        "category_hints": ["dish"],
                        "static_fixture_projection": [],
                        "image": {
                            "source": "synthetic",
                            "width": 32,
                            "height": 24,
                            "background": [220, 220, 220],
                            "objects": [],
                        },
                        "private_labels": [{"category": "dish", "category_family": "dish"}],
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    server = _start_configurable_service(pipeline_id="grounding-dino", adapter_mode="real")
    try:
        base_url = f"http://127.0.0.1:{server.server_port}"
        subprocess.run(
            [
                sys.executable,
                str(RUNNER),
                "--corpus",
                str(corpus),
                "--output-dir",
                str(tmp_path / "benchmark"),
                "--pipeline",
                "grounding-dino",
                "--base-url",
                base_url,
                "--timeout-s",
                "2",
            ],
            cwd=REPO_ROOT,
            check=True,
        )
    finally:
        server.shutdown()
        server.server_close()

    candidate_gate = subprocess.run(
        [
            sys.executable,
            str(CHECKER),
            str(tmp_path / "benchmark"),
            "--expect-pipeline",
            "grounding-dino",
            "--require-success",
        ],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
    )
    assert candidate_gate.returncode == 1
    assert "pipeline failures present" in candidate_gate.stderr
    candidate_gate = subprocess.run(
        [
            sys.executable,
            str(CHECKER),
            str(tmp_path / "benchmark"),
            "--expect-pipeline",
            "grounding-dino",
            "--require-success",
            "--require-candidates",
        ],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
    )

    result_path = tmp_path / "benchmark" / "visual_grounding_benchmark_result.json"
    result = json.loads(result_path.read_text())
    assert result["pipelines"][0]["failure_count"] > 0
    assert result["pipelines"][0]["candidate_count"] == 0


def test_visual_grounding_benchmark_compares_named_contract_pipelines(tmp_path: Path) -> None:
    server = _start_configurable_service(pipeline_id="real-router", adapter_mode="unavailable")
    try:
        base_url = f"http://127.0.0.1:{server.server_port}"
        subprocess.run(
            [
                sys.executable,
                str(RUNNER),
                "--corpus",
                str(CORPUS),
                "--output-dir",
                str(tmp_path),
                "--pipeline",
                "grounding-dino,yoloe,omdet-turbo",
                "--base-url",
                base_url,
                "--timeout-s",
                "2",
            ],
            cwd=REPO_ROOT,
            check=True,
        )
    finally:
        server.shutdown()
        server.server_close()

    result = json.loads((tmp_path / "visual_grounding_benchmark_result.json").read_text())
    by_pipeline = {item["pipeline_id"]: item for item in result["pipelines"]}
    assert set(by_pipeline) == {
        "grounding-dino",
        "yoloe",
        "omdet-turbo",
    }
    assert by_pipeline["grounding-dino"]["stage_summary"][0]["producer_id"] == "grounding-dino"
    assert by_pipeline["grounding-dino"]["failure_count"] > 0
    assert by_pipeline["grounding-dino"]["evidence_level"] == "failure_only"
    assert by_pipeline["yoloe"]["stage_summary"][0]["producer_id"] == "yoloe"
    assert by_pipeline["yoloe"]["failure_count"] > 0
    assert by_pipeline["omdet-turbo"]["stage_summary"][0]["producer_id"] == "omdet-turbo"
    assert by_pipeline["omdet-turbo"]["failure_count"] > 0
    assert result["ranking"][0]["pipeline_id"] in {
        "grounding-dino",
        "yoloe",
        "omdet-turbo",
    }
    assert "actionability_proxy_rate" in result["ranking"][0]
    detector_probe = result["detector_probe_recommendation"]
    assert detector_probe["selected_end_to_end_pipelines"][0] == "sim"
    assert detector_probe["best_proposer_only_pipeline_id"] in {
        "grounding-dino",
        "yoloe",
        "omdet-turbo",
    }
    assert set(detector_probe["evidence_levels"].values()) == {"failure_only"}
    retired_slot_tokens = ("direct_vlm", "proposer_plus_refiner")
    for key in detector_probe:
        assert not any(token in key for token in retired_slot_tokens)
    for key in detector_probe["policy"]:
        assert not any(token in key for token in retired_slot_tokens)
    assert detector_probe["selected_real_stage_provenance_complete"] is False
    assert detector_probe["requires_real_stage_provenance_before_probe"] is True

    predictions = [
        json.loads(line)
        for line in (tmp_path / "visual_grounding_predictions.jsonl").read_text().splitlines()
    ]
    assert {stage["stage"] for item in predictions for stage in item["pipeline"]["stages"]} == {
        "proposer"
    }
    assert "private_labels" not in json.dumps(predictions)
    assert "bytes_base64" not in json.dumps(predictions)


def test_visual_grounding_benchmark_records_missing_sidecar_for_detector_routes(
    tmp_path: Path,
) -> None:
    server = _start_configurable_service(pipeline_id="real-router", adapter_mode="unavailable")
    try:
        base_url = f"http://127.0.0.1:{server.server_port}"
        subprocess.run(
            [
                sys.executable,
                str(RUNNER),
                "--corpus",
                str(CORPUS),
                "--output-dir",
                str(tmp_path),
                "--pipeline",
                "grounding-dino,yoloe",
                "--base-url",
                base_url,
                "--timeout-s",
                "2",
            ],
            cwd=REPO_ROOT,
            check=True,
        )
    finally:
        server.shutdown()
        server.server_close()

    result = json.loads((tmp_path / "visual_grounding_benchmark_result.json").read_text())
    assert {item["pipeline_id"] for item in result["pipelines"]} == {
        "grounding-dino",
        "yoloe",
    }
    assert all(item["failure_count"] > 0 for item in result["pipelines"])
    assert all(item["evidence_level"] == "failure_only" for item in result["pipelines"])


def test_visual_grounding_benchmark_matrix_versions_model_rows(tmp_path: Path) -> None:
    matrix = tmp_path / "matrix.json"
    matrix.write_text(
        json.dumps(
            {
                "schema": "visual_grounding_benchmark_matrix_v1",
                "rows": [
                    {
                        "row_id": "dino-tiny-default",
                        "pipeline_id": "grounding-dino",
                        "model_family": "grounding-dino",
                        "producer_id": "grounding-dino",
                        "model_id": "IDEA-Research/grounding-dino-tiny",
                        "size_tier": "tiny",
                        "runtime_parameters": {
                            "box_threshold": 0.35,
                            "text_threshold": 0.25,
                        },
                    },
                    {
                        "row_id": "dino-base-recall",
                        "pipeline_id": "grounding-dino",
                        "model_family": "grounding-dino",
                        "producer_id": "grounding-dino",
                        "model_id": "IDEA-Research/grounding-dino-base",
                        "size_tier": "base",
                        "runtime_parameters": {
                            "box_threshold": 0.25,
                            "text_threshold": 0.2,
                        },
                    },
                    {
                        "row_id": "yolo-world-small",
                        "pipeline_id": "yolo-world",
                        "model_family": "yolo-world",
                        "producer_id": "yolo-world",
                        "model_id": "yolov8s-world.pt",
                        "size_tier": "small",
                        "runtime_parameters": {
                            "confidence_threshold": 0.2,
                            "image_size": 960,
                            "prompt_expansion": True,
                        },
                        "under_sampled_reason": "unit test matrix intentionally has one row",
                    },
                ],
            }
        ),
        encoding="utf-8",
    )
    server = _start_configurable_service(pipeline_id="real-router", adapter_mode="unavailable")
    try:
        base_url = f"http://127.0.0.1:{server.server_port}"
        subprocess.run(
            [
                sys.executable,
                str(RUNNER),
                "--corpus",
                str(CORPUS),
                "--output-dir",
                str(tmp_path / "benchmark"),
                "--matrix",
                str(matrix),
                "--base-url",
                base_url,
                "--timeout-s",
                "2",
            ],
            cwd=REPO_ROOT,
            check=True,
        )
    finally:
        server.shutdown()
        server.server_close()

    result = json.loads(
        (tmp_path / "benchmark" / "visual_grounding_benchmark_result.json").read_text()
    )
    assert [item["benchmark_row_id"] for item in result["pipelines"]] == [
        "dino-tiny-default",
        "dino-base-recall",
        "yolo-world-small",
    ]
    by_row = {item["benchmark_row_id"]: item for item in result["pipelines"]}
    assert by_row["dino-base-recall"]["model_id"] == "IDEA-Research/grounding-dino-base"
    assert by_row["dino-base-recall"]["runtime_parameters"]["box_threshold"] == 0.25
    assert all(item["failure_count"] > 0 for item in result["pipelines"])
    family = {item["model_family"]: item for item in result["family_sweep"]}
    assert family["grounding-dino"]["under_sampled"] is True
    assert family["grounding-dino"]["successful_config_count"] == 0
    assert family["grounding-dino"]["under_sampled_reason"] == (
        "fewer than two successful configs (0); failure statuses: adapter_unavailable"
    )
    assert family["grounding-dino"]["size_tiers"] == ["base", "tiny"]
    assert family["yolo-world"]["under_sampled"] is True
    assert family["yolo-world"]["under_sampled_reason"] == (
        "unit test matrix intentionally has one row"
    )
    detector_probe = result["detector_probe_recommendation"]
    assert (
        detector_probe["selected"][1]["benchmark_row_id"]
        == (result["ranking"][0]["benchmark_row_id"])
    )
    predictions = [
        json.loads(line)
        for line in (tmp_path / "benchmark" / "visual_grounding_predictions.jsonl")
        .read_text(encoding="utf-8")
        .splitlines()
    ]
    assert {item["benchmark_row_id"] for item in predictions} == {
        "dino-tiny-default",
        "dino-base-recall",
        "yolo-world-small",
    }


def test_visual_grounding_family_sweep_marks_failed_family_under_sampled() -> None:
    summary = _family_sweep_summary(
        [
            {
                "benchmark_row_id": "omdet-tiny",
                "pipeline_id": "omdet-turbo",
                "model_family": "omdet-turbo",
                "model_id": "omdet-tiny",
                "size_tier": "tiny",
                "failure_count": 3,
                "parse_failure_count": 0,
                "timeout_count": 0,
                "stage_summary": [{"status_counts": {"missing_dependency": 3}}],
            },
            {
                "benchmark_row_id": "omdet-base",
                "pipeline_id": "omdet-turbo",
                "model_family": "omdet-turbo",
                "model_id": "omdet-base",
                "size_tier": "base",
                "failure_count": 3,
                "parse_failure_count": 0,
                "timeout_count": 0,
                "stage_summary": [{"status_counts": {"missing_dependency": 3}}],
            },
        ]
    )

    assert summary == [
        {
            "model_family": "omdet-turbo",
            "tested_config_count": 2,
            "successful_config_count": 0,
            "row_ids": ["omdet-tiny", "omdet-base"],
            "successful_row_ids": [],
            "size_tiers": ["base", "tiny"],
            "model_ids": ["omdet-base", "omdet-tiny"],
            "under_sampled": True,
            "under_sampled_reason": (
                "fewer than two successful configs (0); failure statuses: missing_dependency"
            ),
        }
    ]


def test_visual_grounding_bbox_metrics_require_iou_not_category_only() -> None:
    observations = {
        "bbox-dish": {
            "observation_id": "bbox-dish",
            "static_fixture_projection": [],
            "private_labels": [
                {
                    "category": "dish",
                    "category_family": "dish",
                    "bbox": [0.1, 0.1, 0.2, 0.2],
                    "visible": True,
                }
            ],
        },
        "bbox-book": {
            "observation_id": "bbox-book",
            "static_fixture_projection": [],
            "private_labels": [
                {
                    "category": "book",
                    "category_family": "book",
                    "bbox": [0.6, 0.6, 0.2, 0.2],
                    "visible": True,
                }
            ],
        },
    }
    predictions = [
        {
            "observation_id": "bbox-dish",
            "pipeline": {"parse_failed": False},
            "diagnostic_evidence": {},
            "candidates": [
                {
                    "category": "dish",
                    "bbox": [0.1, 0.1, 0.2, 0.2],
                    "image_region": {"type": "bbox", "value": [0.1, 0.1, 0.2, 0.2]},
                }
            ],
        },
        {
            "observation_id": "bbox-book",
            "pipeline": {"parse_failed": False},
            "diagnostic_evidence": {},
            "candidates": [
                {
                    "category": "book",
                    "bbox": [0.1, 0.1, 0.2, 0.2],
                    "image_region": {"type": "bbox", "value": [0.1, 0.1, 0.2, 0.2]},
                }
            ],
        },
    ]

    score = _score_predictions(
        predictions,
        observations,
        {"dish": "dish", "book": "book"},
    )
    metrics = score["metrics"]

    assert metrics["recall"] == 1.0
    assert metrics["precision"] == 1.0
    assert metrics["bbox_metrics_available"] is True
    assert metrics["bbox_iou_threshold"] == 0.3
    assert metrics["bbox_label_count"] == 2
    assert metrics["bbox_matched_label_count"] == 1
    assert metrics["bbox_recall_at_iou"] == 0.5
    assert metrics["bbox_precision_at_iou"] == 0.5
    assert metrics["bbox_category_family_accuracy_at_iou"] == 1.0
    assert metrics["bbox_false_positive_rate"] == 0.5


def test_visual_grounding_first_wave_matrix_covers_required_sweeps() -> None:
    matrix = json.loads(FIRST_WAVE_MATRIX.read_text(encoding="utf-8"))
    rows = matrix["rows"]
    by_row = {row["row_id"]: row for row in rows}

    assert len(rows) == 15
    for size in ("tiny", "base"):
        for mode, box_threshold, text_threshold in (
            ("default", 0.35, 0.25),
            ("recall", 0.25, 0.2),
            ("conservative", 0.4, 0.3),
        ):
            row = by_row[f"grounding-dino-{size}-{mode}"]
            assert row["model_family"] == "grounding-dino"
            assert row["runtime_parameters"]["box_threshold"] == box_threshold
            assert row["runtime_parameters"]["text_threshold"] == text_threshold

    for row_id in (
        "yoloe-11s-precision",
        "yoloe-11m-recall",
        "yolo-world-small-precision",
        "yolo-world-medium-recall",
    ):
        assert by_row[row_id]["runtime_parameters"]["prompt_expansion"] is True

    assert "yolo-custom-fast-placeholder" not in by_row
    assert "yolo-custom-large-placeholder" not in by_row
    for row_id in (
        "omdet-turbo-tiny-default",
        "omdet-turbo-tiny-recall",
        "omdet-turbo-tiny-precision",
    ):
        row = by_row[row_id]
        assert row["model_id"] == "omlab/omdet-turbo-swin-tiny-hf"
        assert row["runtime_parameters"]["device"] == "auto"
        assert row["runtime_parameters"]["torch_dtype"] == "auto"


def _start_configurable_service(
    *,
    pipeline_id: str,
    adapter_mode: str,
) -> ThreadingHTTPServer:
    server = ThreadingHTTPServer(
        ("127.0.0.1", 0),
        make_configurable_handler(
            pipeline_id=pipeline_id,
            adapter_mode=adapter_mode,
            latency_ms=1,
        ),
    )
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    return server
