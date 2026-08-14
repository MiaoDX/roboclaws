from __future__ import annotations

import json
from pathlib import Path

import pytest

from roboclaws.evals.visual_grounding_benchmark.validation import validate_benchmark_path

REPO_ROOT = Path(__file__).resolve().parents[3]


def test_visual_grounding_checker_rejects_malformed_result_source(tmp_path: Path) -> None:
    result_path = tmp_path / "visual_grounding_benchmark_result.json"
    result_path.write_text("{not json", encoding="utf-8")

    with pytest.raises(AssertionError) as exc_info:
        validate_benchmark_path(tmp_path)

    message = str(exc_info.value)
    assert "JSON file must contain valid JSON object" in message
    assert "visual_grounding_benchmark_result.json" in message


def test_visual_grounding_checker_rejects_non_object_result_source(tmp_path: Path) -> None:
    result_path = tmp_path / "visual_grounding_benchmark_result.json"
    result_path.write_text("[]", encoding="utf-8")

    with pytest.raises(AssertionError) as exc_info:
        validate_benchmark_path(tmp_path)

    message = str(exc_info.value)
    assert "JSON file must contain a JSON object" in message
    assert "visual_grounding_benchmark_result.json" in message


def test_visual_grounding_checker_rejects_malformed_predictions_source(tmp_path: Path) -> None:
    _write_minimal_visual_grounding_checker_sources(tmp_path, predictions_text="{not json\n")

    with pytest.raises(AssertionError) as exc_info:
        validate_benchmark_path(tmp_path)

    message = str(exc_info.value)
    assert "JSONL row must contain valid JSON object" in message
    assert "visual_grounding_predictions.jsonl:1" in message


def test_visual_grounding_checker_rejects_non_object_predictions_source(tmp_path: Path) -> None:
    _write_minimal_visual_grounding_checker_sources(tmp_path, predictions_text="[]\n")

    with pytest.raises(AssertionError) as exc_info:
        validate_benchmark_path(tmp_path)

    message = str(exc_info.value)
    assert "JSONL row must contain a JSON object" in message
    assert "visual_grounding_predictions.jsonl:1" in message


def _write_minimal_visual_grounding_checker_sources(
    output_dir: Path,
    *,
    predictions_text: str,
) -> None:
    (output_dir / "visual_grounding_benchmark_result.json").write_text(
        json.dumps(
            {
                "schema": "visual_grounding_benchmark_result_v1",
                "corpus": {"private_label_details_included": False},
                "pipelines": [
                    {
                        "benchmark_row_id": "grounding-dino",
                        "pipeline_id": "grounding-dino",
                    }
                ],
                "family_sweep": [
                    {
                        "model_family": "grounding-dino",
                        "tested_config_count": 1,
                        "successful_config_count": 0,
                        "row_ids": ["grounding-dino"],
                        "successful_row_ids": [],
                        "size_tiers": ["tiny"],
                        "under_sampled": True,
                        "under_sampled_reason": "fixture",
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    (output_dir / "visual_grounding_benchmark_report.html").write_text(
        "<html><body>fixture</body></html>",
        encoding="utf-8",
    )
    (output_dir / "visual_grounding_predictions.jsonl").write_text(
        predictions_text,
        encoding="utf-8",
    )
