from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import pytest

from roboclaws.core.live_performance import MODEL_CALL_METRIC_SCHEMA

CALIBRATE_SCRIPT = (
    Path(__file__).resolve().parents[3] / "scripts/reports/calibrate_model_latency.py"
)


def test_calibrate_model_latency_writes_error_statistics(tmp_path: Path) -> None:
    calibrator = _load_calibrator()
    metrics_path = tmp_path / "model_call_metrics.jsonl"
    rows = [
        _model_call_metric_row(
            uncached_input_tokens=100 + index,
            cached_input_tokens=20,
            output_tokens=10 + index % 3,
            reasoning_tokens=2,
            duration_s=1.0 + ((100 + index) * 0.01) + ((10 + index % 3) * 0.05),
        )
        for index in range(24)
    ]
    metrics_path.write_text(
        "".join(json.dumps(row, sort_keys=True) + "\n" for row in rows),
        encoding="utf-8",
    )

    packet = calibrator.build_calibration_packet(
        [metrics_path],
        dataset_name="unit-test-calibration",
        min_samples=20,
        min_group_samples=20,
    )

    assert packet["schema"] == "roboclaws_model_latency_calibration_v1"
    assert packet["available"] is True
    assert packet["dataset_name"] == "unit-test-calibration"
    assert packet["sample_count"] == 24
    assert packet["fit"]["error_stats"]["sample_count"] == 24
    assert packet["fit"]["error_stats"]["mae_s"] >= 0
    assert packet["fit"]["error_stats"]["rmse_s"] >= 0
    assert packet["coefficient_sets"][0]["provider_profile"] == "kimi-openai-chat"
    assert packet["coefficient_sets"][0]["model"] == "gpt-5.5"
    assert packet["validation"]["available"] is False
    assert "holdout_validation_not_requested" in packet["validation"]["limitations"]
    assert "diagnostic_same_dataset_fit_not_holdout_validated" in packet["limitations"]


def test_calibrate_model_latency_reports_holdout_validation(tmp_path: Path) -> None:
    calibrator = _load_calibrator()
    training_path = tmp_path / "train.jsonl"
    validation_path = tmp_path / "validation.jsonl"
    training_rows = [
        _model_call_metric_row(
            uncached_input_tokens=50 + index,
            cached_input_tokens=0,
            output_tokens=5 + ((index * 7) % 11),
            reasoning_tokens=0,
            duration_s=2.0 + ((50 + index) * 0.02) + ((5 + ((index * 7) % 11)) * 0.4),
        )
        for index in range(24)
    ]
    validation_rows = [
        _model_call_metric_row(
            uncached_input_tokens=80 + (index * 3),
            cached_input_tokens=0,
            output_tokens=6 + ((index * 5) % 7),
            reasoning_tokens=0,
            duration_s=2.0 + ((80 + (index * 3)) * 0.02) + ((6 + ((index * 5) % 7)) * 0.4),
        )
        for index in range(8)
    ]
    training_path.write_text(
        "".join(json.dumps(row, sort_keys=True) + "\n" for row in training_rows),
        encoding="utf-8",
    )
    validation_path.write_text(
        "".join(json.dumps(row, sort_keys=True) + "\n" for row in validation_rows),
        encoding="utf-8",
    )

    packet = calibrator.build_calibration_packet(
        [training_path],
        dataset_name="holdout-unit-test",
        min_samples=20,
        min_group_samples=20,
        validation_paths=[validation_path],
        min_validation_samples=5,
        min_group_validation_samples=5,
    )

    assert packet["available"] is True
    assert packet["validation"]["available"] is True
    assert packet["validation"]["sample_count"] == 8
    assert packet["validation"]["error_stats"]["sample_count"] == 8
    assert packet["coefficient_sets"][0]["validation"]["available"] is True
    assert packet["coefficient_sets"][0]["validation"]["error_stats"]["sample_count"] == 8
    assert "diagnostic_same_dataset_fit_not_holdout_validated" not in packet["limitations"]
    assert packet["limitations"] == ["not_repo_default_calibration"]


def test_calibrate_model_latency_flags_weak_holdout_explanatory_power(
    tmp_path: Path,
) -> None:
    calibrator = _load_calibrator()
    training_path = tmp_path / "train.jsonl"
    validation_path = tmp_path / "validation.jsonl"
    training_path.write_text(
        "".join(
            json.dumps(
                _model_call_metric_row(
                    uncached_input_tokens=100 + index,
                    output_tokens=10,
                    duration_s=1.0 + ((100 + index) * 0.01),
                ),
                sort_keys=True,
            )
            + "\n"
            for index in range(24)
        ),
        encoding="utf-8",
    )
    validation_path.write_text(
        "".join(
            json.dumps(
                _model_call_metric_row(
                    uncached_input_tokens=100 + index,
                    output_tokens=10,
                    duration_s=10.0 if index % 2 else 1.0,
                ),
                sort_keys=True,
            )
            + "\n"
            for index in range(8)
        ),
        encoding="utf-8",
    )

    packet = calibrator.build_calibration_packet(
        [training_path],
        dataset_name="weak-holdout",
        min_samples=20,
        validation_paths=[validation_path],
        min_validation_samples=5,
    )

    assert packet["validation"]["available"] is True
    assert packet["validation"]["error_stats"]["r2"] < 0.2
    assert "diagnostic_same_dataset_fit_not_holdout_validated" not in packet["limitations"]
    assert "holdout_validation_low_explanatory_power" in packet["limitations"]


def test_calibrate_model_latency_keeps_same_dataset_limit_when_holdout_too_small(
    tmp_path: Path,
) -> None:
    calibrator = _load_calibrator()
    training_path = tmp_path / "train.jsonl"
    validation_path = tmp_path / "validation.jsonl"
    training_path.write_text(
        "".join(
            json.dumps(_model_call_metric_row(uncached_input_tokens=100 + index, duration_s=2.0))
            + "\n"
            for index in range(24)
        ),
        encoding="utf-8",
    )
    validation_path.write_text(
        json.dumps(_model_call_metric_row(uncached_input_tokens=1, duration_s=1.0)) + "\n",
        encoding="utf-8",
    )

    packet = calibrator.build_calibration_packet(
        [training_path],
        dataset_name="small-holdout",
        min_samples=20,
        validation_paths=[validation_path],
        min_validation_samples=5,
    )

    assert packet["available"] is True
    assert packet["validation"]["available"] is False
    assert "insufficient_holdout_validation_samples" in packet["validation"]["limitations"]
    assert "diagnostic_same_dataset_fit_not_holdout_validated" in packet["limitations"]


def test_calibrate_model_latency_fails_closed_on_too_few_rows(tmp_path: Path) -> None:
    calibrator = _load_calibrator()
    metrics_path = tmp_path / "model_call_metrics.jsonl"
    metrics_path.write_text(
        "".join(
            json.dumps(_model_call_metric_row(uncached_input_tokens=index + 1, duration_s=1.0))
            + "\n"
            for index in range(3)
        ),
        encoding="utf-8",
    )

    packet = calibrator.build_calibration_packet(
        [metrics_path],
        dataset_name="too-small",
        min_samples=20,
    )

    assert packet["available"] is False
    assert packet["sample_count"] == 3
    assert "insufficient_calibration_samples" in packet["limitations"]


def test_calibrate_model_latency_fails_aloud_on_malformed_metrics_source(
    tmp_path: Path,
) -> None:
    calibrator = _load_calibrator()
    metrics_path = tmp_path / "model_call_metrics.jsonl"
    metrics_path.write_text(
        json.dumps(_model_call_metric_row(uncached_input_tokens=1, duration_s=1.0)) + "\n"
        '{"schema":"roboclaws_model_call_metric_v1"',
        encoding="utf-8",
    )

    with pytest.raises(
        ValueError,
        match=r"model-call metrics source row must contain valid JSON object: "
        r".*model_call_metrics\.jsonl:2",
    ):
        calibrator.build_calibration_packet(
            [metrics_path],
            dataset_name="malformed-source",
            min_samples=1,
        )


def test_calibrate_model_latency_fails_aloud_on_non_object_metrics_source(
    tmp_path: Path,
) -> None:
    calibrator = _load_calibrator()
    metrics_path = tmp_path / "model_call_metrics.jsonl"
    metrics_path.write_text(
        json.dumps(["not", "a", "metric"]) + "\n",
        encoding="utf-8",
    )

    with pytest.raises(
        ValueError,
        match=r"model-call metrics source row must contain a JSON object: "
        r".*model_call_metrics\.jsonl:1",
    ):
        calibrator.build_calibration_packet(
            [metrics_path],
            dataset_name="non-object-source",
            min_samples=1,
        )


def test_calibrate_model_latency_treats_missing_metrics_source_as_empty(
    tmp_path: Path,
) -> None:
    calibrator = _load_calibrator()

    packet = calibrator.build_calibration_packet(
        [tmp_path / "missing-model-call-metrics.jsonl"],
        dataset_name="missing-source",
        min_samples=1,
    )

    assert packet["available"] is False
    assert packet["sample_count"] == 0
    assert packet["total_row_count"] == 0
    assert packet["rejected_row_count"] == 0
    assert "insufficient_calibration_samples" in packet["limitations"]


def _load_calibrator():
    spec = importlib.util.spec_from_file_location("calibrate_model_latency", CALIBRATE_SCRIPT)
    assert spec is not None
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def _model_call_metric_row(
    *,
    uncached_input_tokens: int,
    duration_s: float,
    cached_input_tokens: int = 0,
    output_tokens: int = 1,
    reasoning_tokens: int = 0,
) -> dict[str, object]:
    return {
        "schema": MODEL_CALL_METRIC_SCHEMA,
        "agent_engine": "openai-agents-sdk",
        "provider_profile": "kimi-openai-chat",
        "wire_api": "responses",
        "model": "gpt-5.5",
        "attempt_index": 0,
        "call_index": 0,
        "duration_s": duration_s,
        "input_tokens": uncached_input_tokens + cached_input_tokens,
        "cached_input_tokens": cached_input_tokens,
        "uncached_input_tokens": uncached_input_tokens,
        "output_tokens": output_tokens,
        "reasoning_tokens": reasoning_tokens,
        "image_input_count": 0,
        "image_input_pixels": 0,
        "status": "success",
        "failure_class": "",
        "source": "unit_test",
        "limitations": [],
    }
