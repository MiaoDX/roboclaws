from __future__ import annotations

import json
from pathlib import Path

import pytest

from roboclaws.evals.models import (
    EVAL_RESULT_SCHEMA,
    EVAL_SUITE_SCHEMA,
    MISSING_NOT_APPLICABLE,
    MISSING_UNAVAILABLE,
)
from roboclaws.evals.regression import (
    promote_regression_from_cli_overrides,
    promote_regression_sample_from_eval_result,
)


def test_regression_promotion_rejects_malformed_eval_results_before_writing(
    tmp_path: Path,
) -> None:
    results_path = tmp_path / "eval_results.json"
    sample_output = tmp_path / "samples" / "should_not_exist.json"
    suite_output = tmp_path / "suites" / "should_not_exist.json"
    results_path.write_text("{", encoding="utf-8")

    with pytest.raises(
        ValueError,
        match=(
            r"eval regression promotion source must contain valid JSON object: "
            r".*eval_results\.json"
        ),
    ):
        promote_regression_sample_from_eval_result(
            results_path,
            sample_output_path=sample_output,
            suite_output_path=suite_output,
        )

    assert not sample_output.exists()
    assert not suite_output.exists()


def test_regression_promotion_rejects_non_object_eval_results_before_writing(
    tmp_path: Path,
) -> None:
    results_path = tmp_path / "eval_results.json"
    sample_output = tmp_path / "samples" / "should_not_exist.json"
    suite_output = tmp_path / "suites" / "should_not_exist.json"
    results_path.write_text("[]", encoding="utf-8")

    with pytest.raises(
        ValueError,
        match=r"eval regression promotion source must contain a JSON object: .*eval_results\.json",
    ):
        promote_regression_sample_from_eval_result(
            results_path,
            sample_output_path=sample_output,
            suite_output_path=suite_output,
        )

    assert not sample_output.exists()
    assert not suite_output.exists()


def test_regression_promotion_rejects_missing_eval_results_before_writing(
    tmp_path: Path,
) -> None:
    sample_output = tmp_path / "samples" / "should_not_exist.json"
    suite_output = tmp_path / "suites" / "should_not_exist.json"

    with pytest.raises(
        ValueError,
        match=r"eval regression promotion source is missing: .*missing_eval_results\.json",
    ):
        promote_regression_sample_from_eval_result(
            tmp_path / "missing_eval_results.json",
            sample_output_path=sample_output,
            suite_output_path=suite_output,
        )

    assert not sample_output.exists()
    assert not suite_output.exists()


def test_regression_promotion_rejects_malformed_suite_source_before_writing(
    tmp_path: Path,
) -> None:
    results_path = tmp_path / "eval_results.json"
    suite_path = tmp_path / "suite.json"
    sample_output = tmp_path / "samples" / "should_not_exist.json"
    suite_output = tmp_path / "suites" / "should_not_exist.json"
    _write_json(results_path, _eval_results_bundle())
    suite_path.write_text("{", encoding="utf-8")

    with pytest.raises(
        ValueError,
        match=r"eval regression suite source must contain valid JSON object: .*suite\.json",
    ):
        promote_regression_sample_from_eval_result(
            results_path,
            sample_output_path=sample_output,
            suite_path=suite_path,
            suite_output_path=suite_output,
        )

    assert not sample_output.exists()
    assert not suite_output.exists()


def test_regression_promotion_rejects_missing_suite_source_before_writing(
    tmp_path: Path,
) -> None:
    results_path = tmp_path / "eval_results.json"
    sample_output = tmp_path / "samples" / "should_not_exist.json"
    suite_output = tmp_path / "suites" / "should_not_exist.json"
    _write_json(results_path, _eval_results_bundle())

    with pytest.raises(
        ValueError,
        match=r"eval regression suite source is missing: .*missing_suite\.json",
    ):
        promote_regression_sample_from_eval_result(
            results_path,
            sample_output_path=sample_output,
            suite_path=tmp_path / "missing_suite.json",
            suite_output_path=suite_output,
        )

    assert not sample_output.exists()
    assert not suite_output.exists()


def test_regression_promotion_stop_label_does_not_read_or_write_sources(
    tmp_path: Path,
) -> None:
    sample_output = tmp_path / "samples" / "should_not_exist.json"
    suite_output = tmp_path / "suites" / "should_not_exist.json"

    with pytest.raises(ValueError, match="cannot write a sample"):
        promote_regression_from_cli_overrides(
            {
                "eval_results": str(tmp_path / "missing_eval_results.json"),
                "review_label": "eval-regression:do-not-promote",
                "sample_output_path": str(sample_output),
                "suite_output_path": str(suite_output),
            }
        )

    assert not sample_output.exists()
    assert not suite_output.exists()


def _eval_results_bundle() -> dict[str, object]:
    return {
        "schema": "roboclaws_eval_results_bundle_v1",
        "suite": _suite(),
        "results": [_failed_result()],
    }


def _suite() -> dict[str, object]:
    return {
        "schema": EVAL_SUITE_SCHEMA,
        "suite_id": "household_world.smoke_regression",
        "version": "2026-06-15",
        "capability": "household_world",
        "sample_ids": ["cleanup.smoke_seed7"],
        "sample_refs": ["evals/household_world/samples/cleanup/smoke_seed7.json"],
        "required_graders": ["artifacts", "privacy", "trajectory"],
        "thresholds": {"pass_at_1": 1.0},
    }


def _failed_result() -> dict[str, object]:
    return {
        "schema": EVAL_RESULT_SCHEMA,
        "identity": _identity(),
        "status": "failed",
        "failure_class": "artifact_missing",
        "grader_outputs": {"artifacts": {"report_present": False}},
        "artifacts": {"run_result": "run_result.json"},
        "artifact_schema_versions": {},
        "metrics": {},
        "limitations": [],
    }


def _identity() -> dict[str, object]:
    return {
        "schema": "roboclaws_eval_identity_v1",
        "suite_id": "household_world.smoke_regression",
        "suite_version": "2026-06-15",
        "sample_id": "cleanup.smoke_seed7",
        "sample_version": "2026-06-15",
        "trial_id": "cleanup.smoke_seed7.trial-0",
        "repetition_index": 0,
        "surface": "household-world",
        "intent": "cleanup",
        "preset": "cleanup",
        "world": "molmospaces/procthor-10k-val/0",
        "backend": "mujoco",
        "evidence_lane": "world-public-labels",
        "camera_labeler": MISSING_NOT_APPLICABLE,
        "scenario_setup": "relocate-cleanup-related-objects",
        "seed": 7,
        "prompt": MISSING_NOT_APPLICABLE,
        "goal_contract_hash": MISSING_UNAVAILABLE,
        "agent_engine": "direct-runner",
        "runner_class": "direct",
        "provider_profile": MISSING_NOT_APPLICABLE,
        "model": MISSING_NOT_APPLICABLE,
        "skill_name": MISSING_UNAVAILABLE,
        "prompt_source": MISSING_UNAVAILABLE,
        "mcp_profile": "household_world",
        "tool_surface": [MISSING_UNAVAILABLE],
        "budgets": {},
        "runtime": {},
    }


def _write_json(path: Path, payload: dict[str, object]) -> None:
    path.write_text(json.dumps(payload), encoding="utf-8")
