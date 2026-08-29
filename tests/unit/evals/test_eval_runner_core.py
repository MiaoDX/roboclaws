from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from roboclaws.evals.runner import run_eval_suite
from tests.unit.evals.eval_runner_support import (
    _missing_artifact_product_runner,
    _passing_product_runner,
    _run_result,
    _write_product_artifacts,
)


def test_eval_runner_writes_result_bundle_and_report(tmp_path: Path) -> None:
    run = run_eval_suite(
        "smoke_regression",
        output_root=tmp_path,
        stamp="unit",
        product_runner=_passing_product_runner,
    )

    assert run.results_path.exists()
    assert run.report_path.exists()
    assert run.opik_projection["state"] == "disabled"
    assert (run.output_dir / "opik_projection.json").is_file()
    payload = json.loads(run.results_path.read_text())
    assert payload["schema"] == "roboclaws_eval_results_bundle_v1"
    assert payload["suite"]["suite_id"] == "household_world.smoke_regression"
    assert payload["aggregate"]["total"] == 1
    assert payload["aggregate"]["trial_count"] == 1
    assert payload["aggregate"]["sample_count"] == 1
    assert payload["aggregate"]["passed"] == 1
    assert payload["aggregate"]["pass_at_1"] == 1.0
    assert payload["aggregate"]["pass_at_k"] == {"1": 1.0}
    assert payload["aggregate"]["pass_caret_k"] == {"1": 1.0}
    assert "sampler_projection" not in payload["aggregate"]

    result = payload["results"][0]
    assert result["status"] == "passed"
    assert result["failure_class"] == "not_applicable"
    assert result["grader_outputs"]["outcome"]["completion_status"] == "success"
    assert result["identity"]["agent_engine"] == "direct-runner"
    assert result["identity"]["provider_profile"] == "not_applicable"
    assert result["artifacts"]["run_result"].endswith("run_result.json")
    assert result["artifacts"]["report"].endswith("report.html")
    report_html = run.report_path.read_text()
    assert "run_result" in report_html
    assert 'href="runs/cleanup_smoke_seed7/trial-0000/run_result.json"' in report_html
    assert "Scene Sampler Projection" not in report_html


def test_eval_runner_default_stamp_is_unique_for_quick_repeated_runs(tmp_path: Path) -> None:
    first = run_eval_suite(
        "smoke_regression",
        output_root=tmp_path,
        product_runner=_passing_product_runner,
    )
    second = run_eval_suite(
        "smoke_regression",
        output_root=tmp_path,
        product_runner=_passing_product_runner,
    )

    assert first.output_dir != second.output_dir
    assert first.results_path.exists()
    assert second.results_path.exists()


def test_eval_runner_selects_one_cleanup_repetition(tmp_path: Path) -> None:
    run = run_eval_suite(
        "cleanup_capability",
        output_root=tmp_path,
        stamp="shard",
        sample_id="cleanup.repeated_seed7",
        repetition_index=1,
        product_runner=_passing_product_runner,
    )

    payload = json.loads(run.results_path.read_text())
    assert payload["selection"] == {
        "sample_id": "cleanup.repeated_seed7",
        "repetition_index": 1,
    }
    assert payload["aggregate"]["total"] == 1
    assert payload["results"][0]["identity"]["repetition_index"] == 1


def test_eval_runner_sample_selection_keeps_all_repetitions(tmp_path: Path) -> None:
    run = run_eval_suite(
        "cleanup_capability",
        output_root=tmp_path,
        stamp="sample-shard",
        sample_id="cleanup.repeated_seed7",
        product_runner=_passing_product_runner,
    )

    payload = json.loads(run.results_path.read_text())
    assert payload["selection"] == {
        "sample_id": "cleanup.repeated_seed7",
        "repetition_index": None,
    }
    assert payload["aggregate"]["total"] == 3


def test_cleanup_outcome_keeps_semantic_partial_success_diagnostic_only(
    tmp_path: Path,
) -> None:
    def product_runner(**kwargs: Any) -> dict[str, Any]:
        run_dir = Path(kwargs["output_dir"])
        _write_product_artifacts(run_dir, completion_status="partial_success")
        result = _run_result(run_dir, completion_status="partial_success")
        result["score"]["mess_restoration_rate"] = 0.4
        result["score"]["semantic_acceptability"] = {
            "status": "success",
            "accepted_count": 5,
            "total_targets": 5,
            "accepted_levels": ["acceptable", "preferred"],
            "counts": {
                "acceptable": 1,
                "preferred": 4,
                "questionable": 0,
                "unknown": 0,
                "wrong": 0,
            },
            "wrong_object_ids": [],
            "unknown_object_ids": [],
            "questionable_object_ids": [],
        }
        return result

    run = run_eval_suite(
        "smoke_regression",
        output_root=tmp_path,
        stamp="semantic-partial-success",
        product_runner=product_runner,
    )

    payload = json.loads(run.results_path.read_text())
    result = payload["results"][0]
    assert result["status"] == "failed"
    assert result["capability_status"] == "failed"
    assert result["diagnostic_status"] == "ready"
    assert result["failure_class"] == "private_goal_not_satisfied"
    outcome = result["grader_outputs"]["outcome"]
    assert outcome["completion_status"] == "partial_success"
    assert outcome["semantic_completion_status"] == "success"
    assert outcome["semantic_acceptability"]["accepted_count"] == 5


def test_cleanup_outcome_rejects_partial_exact_goal_without_semantic_success(
    tmp_path: Path,
) -> None:
    def product_runner(**kwargs: Any) -> dict[str, Any]:
        run_dir = Path(kwargs["output_dir"])
        _write_product_artifacts(run_dir, completion_status="partial_success")
        result = _run_result(run_dir, completion_status="partial_success")
        result["score"]["mess_restoration_rate"] = 0.4
        result["score"]["semantic_acceptability"] = {
            "status": "partial_success",
            "accepted_count": 2,
            "total_targets": 5,
        }
        return result

    run = run_eval_suite(
        "smoke_regression",
        output_root=tmp_path,
        stamp="semantic-partial-failure",
        product_runner=product_runner,
    )

    payload = json.loads(run.results_path.read_text())
    result = payload["results"][0]
    assert result["status"] == "failed"
    assert result["failure_class"] == "private_goal_not_satisfied"
    outcome = result["grader_outputs"]["outcome"]
    assert outcome["completion_status"] == "partial_success"
    assert outcome["semantic_completion_status"] == "partial_success"


def test_eval_runner_classifies_missing_product_artifacts(tmp_path: Path) -> None:
    run = run_eval_suite(
        "smoke_regression",
        output_root=tmp_path,
        stamp="artifact-failure",
        product_runner=_missing_artifact_product_runner,
    )

    payload = json.loads(run.results_path.read_text())
    result = payload["results"][0]
    assert result["status"] == "failed"
    assert result["failure_class"] == "artifact_missing"
    assert payload["aggregate"]["failure_classes"] == {"artifact_missing": 1}
    assert "report" in result["grader_outputs"]["artifacts"]["missing"]


def test_focused_eval_passes_real_molmospaces_map_bundle_to_product_runner(
    tmp_path: Path,
) -> None:
    captured_kwargs: dict[str, Any] = {}

    def product_runner(**kwargs: Any) -> dict[str, Any]:
        captured_kwargs.update(kwargs)
        return _passing_product_runner(**kwargs)

    run_eval_suite(
        "smoke_regression",
        output_root=tmp_path,
        stamp="focused-real-backend",
        budget="focused",
        product_runner=product_runner,
    )

    assert captured_kwargs["backend"] == "molmospaces_subprocess"
    assert captured_kwargs["evidence_lane"] == "world-public-labels"
    assert captured_kwargs["map_bundle_dir"] == "assets/maps/molmospaces/procthor-10k-val/0"


def test_smoke_eval_uses_canonical_map_bundle(
    tmp_path: Path,
) -> None:
    captured_kwargs: dict[str, Any] = {}

    def product_runner(**kwargs: Any) -> dict[str, Any]:
        captured_kwargs.update(kwargs)
        return _passing_product_runner(**kwargs)

    run_eval_suite(
        "smoke_regression",
        output_root=tmp_path,
        stamp="smoke-synthetic",
        product_runner=product_runner,
    )

    assert captured_kwargs["backend"] == "api_semantic_synthetic"
    assert captured_kwargs["evidence_lane"] == "smoke"
    assert captured_kwargs["map_bundle_dir"] == "assets/maps/molmospaces/procthor-10k-val/0"


def test_map_build_consumer_report_records_comparison_metrics(tmp_path: Path) -> None:
    def product_runner(**kwargs: Any) -> dict[str, Any]:
        run_dir = Path(kwargs["output_dir"])
        sample_id = str(kwargs["run_metadata_overrides"]["eval_sample_id"])
        if sample_id.startswith("map_build."):
            _write_product_artifacts(run_dir, completion_status="map_build_complete")
            return _run_result(
                run_dir,
                completion_status="map_build_complete",
                map_build=True,
            )
        _write_product_artifacts(
            run_dir,
            completion_status="success",
            include_goal_contract=sample_id.startswith("open_ended."),
        )
        result = _run_result(
            run_dir,
            completion_status="success",
            task_intent="open-ended" if sample_id.startswith("open_ended.") else "cleanup",
            final_status="success",
            include_completion_claim=sample_id.startswith("open_ended."),
        )
        if kwargs.get("runtime_map_prior_path"):
            result["runtime_metric_map_prior"] = {
                "loaded": True,
                "source": str(kwargs["runtime_map_prior_path"]),
                "anchor_prior_count": 1,
                "object_prior_count": 1,
            }
            result["runtime_metric_map"]["observed_objects"] = [
                {
                    "object_id": "cup_1",
                    "freshness": "current_run",
                    "actionability": "actionable",
                    "prior_match_basis": "category_room_source_fixture",
                }
            ]
        return result

    run = run_eval_suite(
        "map_build_consumer",
        output_root=tmp_path,
        stamp="comparison",
        product_runner=product_runner,
    )

    payload = json.loads(run.results_path.read_text())
    comparison = payload["aggregate"]["comparison"]
    assert comparison["schema"] == "map_build_consumer_comparison_summary_v1"
    assert comparison["variant_ids"] == [
        "fixture_focused_prior",
        "no_prior",
    ]
    rows = {row["sample_id"]: row for row in comparison["rows"]}
    fixture_row = rows["cleanup.consumer_fixture_focused_prior_seed7"]
    assert fixture_row["variant_id"] == "fixture_focused_prior"
    assert fixture_row["prior_use_verdict"] == "movable_hint_rechecked"
    assert fixture_row["comparison_label"] == "no_regression"
    assert set(fixture_row["tool_counts"]) == {
        "observe",
        "adjust_camera",
        "navigate_to_waypoint",
        "navigate_to_relative_pose",
    }
    assert (
        rows["open_ended.stable_anchor_fixture_focused_prior_seed7"]["comparison_label"]
        == "no_regression"
    )
    report_text = run.report_path.read_text()
    assert "MapBuild Review" in report_text
    assert "MapBuild Consumer Comparison" in report_text
