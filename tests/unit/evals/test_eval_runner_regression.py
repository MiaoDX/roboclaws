from __future__ import annotations

import json
from pathlib import Path

import pytest

from roboclaws.evals.regression import (
    promote_regression_from_cli_overrides,
    promote_regression_sample_from_eval_result,
)
from roboclaws.evals.runner import run_eval_suite
from tests.unit.evals.eval_runner_support import (
    _missing_artifact_product_runner,
    _passing_product_runner,
)


def test_failed_eval_result_promotes_to_regression_sample_and_suite(tmp_path: Path) -> None:
    run = run_eval_suite(
        "smoke_regression",
        output_root=tmp_path,
        stamp="artifact-failure",
        product_runner=_missing_artifact_product_runner,
    )
    sample_output = tmp_path / "samples" / "regression_cleanup_missing_report.json"
    suite_output = tmp_path / "suites" / "smoke_regression_with_regression.json"

    promotion = promote_regression_sample_from_eval_result(
        run.results_path,
        regression_sample_id="regression.cleanup_missing_report",
        sample_output_path=sample_output,
        suite_output_path=suite_output,
        review_label="eval-regression:accepted",
        version="2026-06-15",
    )

    assert promotion["schema"] == "roboclaws_eval_regression_promotion_v1"
    assert promotion["source"]["failure_class"] == "artifact_missing"
    sample = json.loads(sample_output.read_text())
    assert sample["sample_id"] == "regression.cleanup_missing_report"
    assert sample["trial_count"] == 1
    assert sample["private_goal_reference"]["private_truth_scope"] == "grader_only"
    regression = sample["private_goal_reference"]["regression_promotion"]
    assert regression["review_label"] == "eval-regression:accepted"
    assert regression["source_failure_class"] == "artifact_missing"
    assert regression["agent_input_policy"] == "do_not_expose_private_goal_reference"
    assert "run_result" in regression["source_artifacts"]
    suite = json.loads(suite_output.read_text())
    assert "regression.cleanup_missing_report" in suite["sample_ids"]
    assert str(sample_output) in suite["sample_refs"]
    assert suite["metadata"]["regression_sample_count"] == 1
    assert suite["metadata"]["regression_promotions"][0]["private_truth_scope"] == "grader_only"


def test_regression_promotion_rejects_passed_results(tmp_path: Path) -> None:
    run = run_eval_suite(
        "smoke_regression",
        output_root=tmp_path,
        stamp="passed",
        product_runner=_passing_product_runner,
    )

    with pytest.raises(ValueError, match="no failed, blocked, or inconclusive"):
        promote_regression_sample_from_eval_result(run.results_path)


def test_regression_promotion_requires_declared_source_sample_ref(tmp_path: Path) -> None:
    run = run_eval_suite(
        "smoke_regression",
        output_root=tmp_path,
        stamp="artifact-failure",
        product_runner=_missing_artifact_product_runner,
    )
    sample_output = tmp_path / "samples" / "should_not_exist.json"
    suite_output = tmp_path / "suites" / "should_not_exist.json"
    results_path = tmp_path / "eval_results_without_sample_refs.json"
    bundle = json.loads(run.results_path.read_text())
    bundle["suite"].pop("sample_refs")
    results_path.write_text(json.dumps(bundle), encoding="utf-8")

    with pytest.raises(ValueError, match="sample_refs must include source sample"):
        promote_regression_sample_from_eval_result(
            results_path,
            sample_output_path=sample_output,
            suite_output_path=suite_output,
        )

    assert not sample_output.exists()
    assert not suite_output.exists()


def test_regression_promotion_rejects_invalid_result_identity_before_writing(
    tmp_path: Path,
) -> None:
    run = run_eval_suite(
        "smoke_regression",
        output_root=tmp_path,
        stamp="artifact-failure",
        product_runner=_missing_artifact_product_runner,
    )
    sample_output = tmp_path / "samples" / "should_not_exist.json"
    suite_output = tmp_path / "suites" / "should_not_exist.json"
    results_path = tmp_path / "eval_results_with_invalid_identity.json"
    bundle = json.loads(run.results_path.read_text())
    bundle["results"][0]["identity"]["trial_id"] = 7
    results_path.write_text(json.dumps(bundle), encoding="utf-8")

    with pytest.raises(
        ValueError, match="eval result identity trial_id must be a non-empty string"
    ):
        promote_regression_sample_from_eval_result(
            results_path,
            sample_output_path=sample_output,
            suite_output_path=suite_output,
        )

    assert not sample_output.exists()
    assert not suite_output.exists()


def test_regression_promotion_fails_aloud_on_missing_declared_source_sample(
    tmp_path: Path,
) -> None:
    run = run_eval_suite(
        "smoke_regression",
        output_root=tmp_path,
        stamp="artifact-failure",
        product_runner=_missing_artifact_product_runner,
    )
    sample_output = tmp_path / "samples" / "should_not_exist.json"
    suite_output = tmp_path / "suites" / "should_not_exist.json"
    results_path = tmp_path / "eval_results_with_missing_sample_ref.json"
    bundle = json.loads(run.results_path.read_text())
    bundle["suite"]["sample_refs"] = ["evals/household_world/samples/cleanup/missing_sample.json"]
    results_path.write_text(json.dumps(bundle), encoding="utf-8")

    with pytest.raises(ValueError, match="source sample ref .* is unreadable"):
        promote_regression_sample_from_eval_result(
            results_path,
            sample_output_path=sample_output,
            suite_output_path=suite_output,
        )

    assert not sample_output.exists()
    assert not suite_output.exists()


def test_regression_promotion_fails_aloud_on_invalid_declared_source_sample(
    tmp_path: Path,
) -> None:
    run = run_eval_suite(
        "smoke_regression",
        output_root=tmp_path,
        stamp="artifact-failure",
        product_runner=_missing_artifact_product_runner,
    )
    sample_output = tmp_path / "samples" / "should_not_exist.json"
    suite_output = tmp_path / "suites" / "should_not_exist.json"
    invalid_sample_path = tmp_path / "invalid_sample.json"
    invalid_sample_path.write_text('{"schema":"wrong"}\n', encoding="utf-8")
    suite_path = tmp_path / "suite_with_invalid_sample_ref.json"
    suite = json.loads(run.results_path.read_text())["suite"]
    suite["sample_refs"] = [str(invalid_sample_path)]
    suite_path.write_text(json.dumps(suite), encoding="utf-8")

    with pytest.raises(ValueError, match="source sample ref .* is invalid"):
        promote_regression_sample_from_eval_result(
            run.results_path,
            sample_output_path=sample_output,
            suite_path=suite_path,
            suite_output_path=suite_output,
        )

    assert not sample_output.exists()
    assert not suite_output.exists()


def test_regression_promotion_fails_aloud_on_mismatched_declared_source_sample(
    tmp_path: Path,
) -> None:
    run = run_eval_suite(
        "smoke_regression",
        output_root=tmp_path,
        stamp="artifact-failure",
        product_runner=_missing_artifact_product_runner,
    )
    sample_output = tmp_path / "samples" / "should_not_exist.json"
    suite_output = tmp_path / "suites" / "should_not_exist.json"
    mismatched_sample_path = tmp_path / "mismatched_sample.json"
    source_sample_path = (
        Path(__file__).resolve().parents[3]
        / "evals/household_world/samples/cleanup/smoke_seed7.json"
    )
    source_sample = json.loads(source_sample_path.read_text(encoding="utf-8"))
    source_sample["sample_id"] = "cleanup.different_sample"
    mismatched_sample_path.write_text(json.dumps(source_sample), encoding="utf-8")
    suite_path = tmp_path / "suite_with_mismatched_sample_ref.json"
    suite = json.loads(run.results_path.read_text())["suite"]
    suite["sample_refs"] = [str(mismatched_sample_path)]
    suite_path.write_text(json.dumps(suite), encoding="utf-8")

    with pytest.raises(ValueError, match="resolved to sample_id"):
        promote_regression_sample_from_eval_result(
            run.results_path,
            sample_output_path=sample_output,
            suite_path=suite_path,
            suite_output_path=suite_output,
        )

    assert not sample_output.exists()
    assert not suite_output.exists()


def test_regression_promotion_validates_suite_before_writing_sample(
    tmp_path: Path,
) -> None:
    run = run_eval_suite(
        "smoke_regression",
        output_root=tmp_path,
        stamp="artifact-failure",
        product_runner=_missing_artifact_product_runner,
    )
    sample_output = tmp_path / "samples" / "should_not_exist.json"
    suite_output = tmp_path / "suites" / "should_not_exist.json"
    suite_path = tmp_path / "suite_with_missing_thresholds.json"
    suite = json.loads(run.results_path.read_text())["suite"]
    suite.pop("thresholds")
    suite_path.write_text(json.dumps(suite), encoding="utf-8")

    with pytest.raises(ValueError, match="thresholds"):
        promote_regression_sample_from_eval_result(
            run.results_path,
            sample_output_path=sample_output,
            suite_path=suite_path,
            suite_output_path=suite_output,
        )

    assert not sample_output.exists()
    assert not suite_output.exists()


def test_regression_promotion_stop_label_does_not_write_outputs(tmp_path: Path) -> None:
    run = run_eval_suite(
        "smoke_regression",
        output_root=tmp_path,
        stamp="artifact-failure",
        product_runner=_missing_artifact_product_runner,
    )
    sample_output = tmp_path / "samples" / "should_not_exist.json"
    suite_output = tmp_path / "suites" / "should_not_exist.json"

    with pytest.raises(ValueError, match="cannot write a sample"):
        promote_regression_from_cli_overrides(
            {
                "eval_results": str(run.results_path),
                "review_label": "eval-regression:do-not-promote",
                "sample_output_path": str(sample_output),
                "suite_output_path": str(suite_output),
            }
        )

    assert not sample_output.exists()
    assert not suite_output.exists()
