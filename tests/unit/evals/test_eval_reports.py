from __future__ import annotations

from pathlib import Path

import pytest

from roboclaws.evals.map_build_reports import (
    map_build_matrix_summary_from_bundles,
    render_map_build_matrix_report,
)
from roboclaws.evals.models import EvalResult, EvalSuite
from roboclaws.evals.reports import (
    render_eval_report,
    results_bundle,
)


def test_eval_report_links_existing_artifacts_under_output_dir(tmp_path: Path) -> None:
    output_dir = tmp_path / "eval"
    run_dir = output_dir / "runs" / "sample" / "trial-0000"
    run_dir.mkdir(parents=True)
    (run_dir / "run_result.json").write_text("{}\n", encoding="utf-8")
    (run_dir / "report.html").write_text("<html></html>\n", encoding="utf-8")

    html = render_eval_report(
        _bundle(
            output_dir=output_dir,
            artifacts={
                "run_result": str(run_dir / "run_result.json"),
                "report": str(run_dir / "report.html"),
            },
        )
    )

    assert 'href="runs/sample/trial-0000/run_result.json"' in html
    assert 'href="runs/sample/trial-0000/report.html"' in html
    assert "unavailable" not in html


def test_eval_report_marks_missing_or_escaping_artifacts_unavailable(tmp_path: Path) -> None:
    output_dir = tmp_path / "eval"
    output_dir.mkdir()
    outside_dir = tmp_path / "outside"
    outside_dir.mkdir()
    (outside_dir / "report.html").write_text("<html></html>\n", encoding="utf-8")

    html = render_eval_report(
        _bundle(
            output_dir=output_dir,
            artifacts={
                "run_result": "runs/sample/trial-0000/run_result.json",
                "report": "../outside/report.html",
            },
        )
    )

    assert 'href="runs/sample/trial-0000/run_result.json"' not in html
    assert 'href="../outside/report.html"' not in html
    assert (
        "run_result unavailable (missing artifact: runs/sample/trial-0000/run_result.json)" in html
    )
    assert "report unavailable (outside eval output: ../outside/report.html)" in html


def test_results_bundle_rejects_invalid_sampler_projection_counts(tmp_path: Path) -> None:
    suite = _suite_with_sampler_projection(
        source_payload={
            "support_status": "partial",
            "status": "partial_or_blocked",
            "target_count": "10",
            "ready_count": 5,
            "needed_count": 5,
            "blocked_count": 0,
            "rejected_count": 0,
            "sample_ids": ["scene.sample_1"],
        }
    )

    with pytest.raises(
        ValueError,
        match=(
            "eval suite sampler_projection scene source 'procthor-10k-val' "
            "target_count must be a non-negative integer"
        ),
    ):
        results_bundle(
            suite=suite,
            results=[_result()],
            output_dir=tmp_path,
            budget="smoke",
        )


def test_results_bundle_rejects_invalid_sampler_projection_sample_ids(tmp_path: Path) -> None:
    suite = _suite_with_sampler_projection(
        source_payload={
            "support_status": "partial",
            "status": "partial_or_blocked",
            "target_count": 10,
            "ready_count": 5,
            "needed_count": 5,
            "blocked_count": 0,
            "rejected_count": 0,
            "sample_ids": "scene.sample_1",
        }
    )

    with pytest.raises(
        ValueError,
        match=(
            "eval suite sampler_projection scene source 'procthor-10k-val' "
            "sample_ids must be a list of strings"
        ),
    ):
        results_bundle(
            suite=suite,
            results=[_result()],
            output_dir=tmp_path,
            budget="smoke",
        )


def test_results_bundle_rejects_invalid_sampler_projection_summary(tmp_path: Path) -> None:
    suite = _suite_with_sampler_projection(
        source_payload={
            "support_status": "partial",
            "status": "partial_or_blocked",
            "target_count": 10,
            "ready_count": 5,
            "needed_count": 5,
            "blocked_count": 0,
            "rejected_count": 0,
            "sample_ids": ["scene.sample_1"],
        },
        summary_overrides={"remaining_sample_count": "5"},
    )

    with pytest.raises(
        ValueError,
        match="eval suite sampler_projection.summary remaining_sample_count "
        "must be a non-negative integer",
    ):
        results_bundle(
            suite=suite,
            results=[_result()],
            output_dir=tmp_path,
            budget="smoke",
        )


def test_eval_report_rejects_invalid_sampler_projection_summary(tmp_path: Path) -> None:
    bundle = _bundle(output_dir=tmp_path, artifacts={})
    bundle["aggregate"]["sampler_projection"] = _sampler_projection()
    bundle["aggregate"]["sampler_projection"]["summary"]["ready_sample_count"] = False

    with pytest.raises(
        ValueError,
        match="eval report sampler_projection.summary ready_sample_count "
        "must be a non-negative integer",
    ):
        render_eval_report(bundle)


def test_eval_report_rejects_invalid_sampler_projection_source_row(tmp_path: Path) -> None:
    bundle = _bundle(output_dir=tmp_path, artifacts={})
    bundle["aggregate"]["sampler_projection"] = _sampler_projection()
    bundle["aggregate"]["sampler_projection"]["scene_sources"]["procthor-10k-val"] = []

    with pytest.raises(
        ValueError,
        match="eval report sampler_projection scene source 'procthor-10k-val' must be an object",
    ):
        render_eval_report(bundle)


def test_eval_report_rejects_invalid_sampler_projection_sample_ids(tmp_path: Path) -> None:
    bundle = _bundle(output_dir=tmp_path, artifacts={})
    bundle["aggregate"]["sampler_projection"] = _sampler_projection()
    bundle["aggregate"]["sampler_projection"]["scene_sources"]["procthor-10k-val"]["sample_ids"] = (
        "scene.sample_1"
    )

    with pytest.raises(
        ValueError,
        match=(
            "eval report sampler_projection scene source 'procthor-10k-val' "
            "sample_ids must be a list of strings"
        ),
    ):
        render_eval_report(bundle)


def test_map_build_matrix_report_renders_quality_costs_and_downstream_deltas(
    tmp_path: Path,
) -> None:
    run_dir = tmp_path / "eval" / "runs" / "map_build_fixture_focused_seed7" / "trial-0000"
    run_dir.mkdir(parents=True)
    for name in ("report.html", "run_result.json", "runtime_metric_map.json"):
        (run_dir / name).write_text("{}\n", encoding="utf-8")
    bundle = _map_build_bundle(tmp_path / "eval", provider_profile="custom&profile")
    bundle["results"][0]["artifacts"] = {
        "report": str(run_dir / "report.html"),
        "run_result": str(run_dir / "run_result.json"),
        "runtime_metric_map": str(run_dir / "runtime_metric_map.json"),
    }

    summary = map_build_matrix_summary_from_bundles([bundle])
    html = render_map_build_matrix_report(summary, output_dir=tmp_path / "matrix")

    assert summary["schema"] == "map_build_matrix_report_v1"
    assert summary["overview"]["profile_count"] == 1
    assert summary["overview"]["map_build_passed"] == 1
    assert summary["overview"]["richer_than_base"] == 1
    assert summary["overview"]["downstream_improved"] == 2
    quality = summary["map_build_rows"][0]
    assert quality["base_map_anchor_like_count"] == 14
    assert quality["public_semantic_anchor_count"] == 30
    assert quality["runtime_enrichment_anchor_count"] == 16
    assert quality["stable_semantic_anchor_categories"] == ["bed", "fridge"]
    assert quality["tool_call_count"] == 60
    assert quality["request_event_count"] == 60
    assert "MapBuild Quality Matrix" in html
    assert "base 14 -&gt; semantic 30 (+16 runtime)" in html
    assert "custom&amp;profile" in html
    assert "60 / 60" in html
    assert "obs -2, wp -1, turn 0, adj 0, calls -3" in html
    assert "report.html" in html
    assert "Without MapBuild prior" in html
    assert "With MapBuild prior" in html


def test_map_build_matrix_report_keeps_repo_relative_artifacts_relative(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(tmp_path)
    output_dir = tmp_path / "output" / "evals" / "run"
    run_dir = output_dir / "runs" / "cleanup_consumer_no_prior_seed7" / "trial-0000"
    run_dir.mkdir(parents=True)
    (run_dir / "report.html").write_text("{}\n", encoding="utf-8")
    (run_dir / "run_result.json").write_text("{}\n", encoding="utf-8")
    bundle = _map_build_bundle(output_dir, provider_profile="kimi-openai-chat")
    bundle["artifacts"]["output_dir"] = str(output_dir)
    bundle["results"][1]["artifacts"] = {
        "report": "output/evals/run/runs/cleanup_consumer_no_prior_seed7/trial-0000/report.html",
        "run_result": (
            "output/evals/run/runs/cleanup_consumer_no_prior_seed7/trial-0000/run_result.json"
        ),
    }

    summary = map_build_matrix_summary_from_bundles([bundle])
    html = render_map_build_matrix_report(summary, output_dir=tmp_path / "matrix")

    assert "missing artifact" not in html
    assert "output/evals/run/output/evals/run" not in html


def test_map_build_matrix_marks_failed_baseline_pair_inconclusive(tmp_path: Path) -> None:
    bundle = _map_build_bundle(tmp_path / "eval", provider_profile="minimax-responses")
    no_prior = bundle["results"][1]
    no_prior["status"] = "failed"
    no_prior["failure_class"] = "artifact_missing"
    no_prior["metrics"] = {}

    summary = map_build_matrix_summary_from_bundles([bundle])

    open_row = next(row for row in summary["downstream_rows"] if row["task_family"] == "open-ended")
    assert open_row["comparison_label"] == "inconclusive"
    assert open_row["reason"] == "without MapBuild prior baseline failed: artifact_missing"
    assert summary["overview"]["downstream_regressed"] == 0
    assert summary["overview"]["downstream_inconclusive"] == 1


def test_eval_report_includes_map_build_review_section(tmp_path: Path) -> None:
    bundle = _map_build_bundle(tmp_path / "eval", provider_profile="not_applicable")

    html = render_eval_report(bundle)

    assert "MapBuild Review" in html
    assert "Profiles: 1" in html
    assert "base 14 -&gt; semantic 30 (+16 runtime)" in html


def _bundle(*, output_dir: Path, artifacts: dict[str, str]) -> dict[str, object]:
    return {
        "suite": {"suite_id": "household_world.report_links"},
        "aggregate": {
            "pass_at_1": 1.0,
            "passed": 1,
            "total": 1,
        },
        "results": [
            {
                "identity": {
                    "sample_id": "sample",
                    "trial_id": "trial-0000",
                    "agent_engine": "direct-runner",
                    "provider_profile": "not_applicable",
                },
                "artifacts": artifacts,
                "status": "passed",
                "failure_class": "not_applicable",
                "metrics": {},
                "grader_outputs": {},
            }
        ],
        "artifacts": {"output_dir": str(output_dir)},
    }


def _map_build_bundle(output_dir: Path, *, provider_profile: str) -> dict[str, object]:
    return {
        "schema": "roboclaws_eval_results_bundle_v1",
        "suite": {"suite_id": "household_world.map_build_consumer"},
        "aggregate": {
            "pass_at_1": 1.0,
            "passed": 5,
            "total": 5,
        },
        "results": [
            _map_build_result(provider_profile=provider_profile),
            _consumer_result(
                "open_ended.stable_anchor_no_prior_seed7",
                provider_profile=provider_profile,
                variant="no_prior",
                observe=5,
                waypoint=2,
                relative=0,
                adjust=1,
                calls=12,
                restoration=0,
                prior_verdict="prior_ignored",
            ),
            _consumer_result(
                "open_ended.stable_anchor_fixture_focused_prior_seed7",
                provider_profile=provider_profile,
                variant="fixture_focused_prior",
                observe=3,
                waypoint=1,
                relative=0,
                adjust=1,
                calls=9,
                restoration=0,
                prior_verdict="stable_anchor_used",
            ),
            _consumer_result(
                "cleanup.consumer_no_prior_seed7",
                provider_profile=provider_profile,
                variant="no_prior",
                observe=9,
                waypoint=4,
                relative=0,
                adjust=2,
                calls=30,
                restoration=0.6,
                prior_verdict="prior_ignored",
            ),
            _consumer_result(
                "cleanup.consumer_fixture_focused_prior_seed7",
                provider_profile=provider_profile,
                variant="fixture_focused_prior",
                observe=6,
                waypoint=3,
                relative=0,
                adjust=2,
                calls=26,
                restoration=0.8,
                prior_verdict="stable_anchor_used",
            ),
        ],
        "artifacts": {"output_dir": str(output_dir)},
    }


def _identity(sample_id: str, *, provider_profile: str) -> dict[str, object]:
    return {
        "sample_id": sample_id,
        "trial_id": f"{sample_id}-0000",
        "agent_engine": "openai-agents-sdk",
        "provider_profile": provider_profile,
        "model": "not_applicable",
        "seed": 7,
    }


def _map_build_result(*, provider_profile: str) -> dict[str, object]:
    return {
        "identity": _identity("map_build.fixture_focused_seed7", provider_profile=provider_profile),
        "status": "passed",
        "failure_class": "not_applicable",
        "metrics": {
            "comparison_tool_counts": {
                "observe": 28,
                "navigate_to_waypoint": 7,
                "navigate_to_relative_pose": 21,
                "adjust_camera": 0,
            },
            "tool_call_count": 60,
            "tool_event_count": 120,
            "wall_time_s": 488.086,
            "model_attempt_summary": {"attempt_count": 61},
            "tool_event_counts": {
                "done:request": 1,
                "done:response": 1,
                "metric_map:request": 1,
                "metric_map:response": 1,
                "navigate_to_relative_pose:request": 21,
                "navigate_to_relative_pose:response": 21,
                "navigate_to_waypoint:request": 7,
                "navigate_to_waypoint:response": 7,
                "observe:request": 30,
                "observe:response": 30,
            },
        },
        "grader_outputs": {
            "outcome": {
                "status": "passed",
                "base_map_anchor_like_count": 14,
                "public_semantic_anchor_count": 30,
                "runtime_enrichment_anchor_count": 16,
                "semantic_enrichment_over_base": True,
                "generated_exploration_candidate_count": 7,
                "observed_object_count": 0,
                "target_candidate_count": 37,
                "stable_semantic_anchor_category_count": 2,
                "stable_semantic_anchor_categories": ["bed", "fridge"],
                "duplicate_fixture_viewpoint_group_count": 0,
                "rgb_only_object_pose_claim_count": 0,
                "sim_truth_fixture_category_recall": 1.0,
                "sim_truth_fixture_category_precision": 1.0,
                "sim_truth_best_view_waypoint_accuracy": 1.0,
                "private_truth_absent": True,
                "source_map_not_mutated": True,
            }
        },
        "artifacts": {},
    }


def _consumer_result(
    sample_id: str,
    *,
    provider_profile: str,
    variant: str,
    observe: int,
    waypoint: int,
    relative: int,
    adjust: int,
    calls: int,
    restoration: float,
    prior_verdict: str,
) -> dict[str, object]:
    return {
        "identity": {
            **_identity(sample_id, provider_profile=provider_profile),
            "sample_metadata": {"variant_id": variant},
        },
        "status": "passed",
        "failure_class": "not_applicable",
        "metrics": {
            "comparison_tool_counts": {
                "observe": observe,
                "navigate_to_waypoint": waypoint,
                "navigate_to_relative_pose": relative,
                "adjust_camera": adjust,
            },
            "tool_call_count": calls,
            "tool_event_count": calls * 2,
            "wall_time_s": calls + 0.5,
            "mess_restoration_rate": restoration,
            "prior_use_verdict": prior_verdict,
        },
        "grader_outputs": {},
        "artifacts": {},
    }


def _suite_with_sampler_projection(
    *,
    source_payload: dict[str, object],
    summary_overrides: dict[str, object] | None = None,
) -> EvalSuite:
    summary = _sampler_projection_summary()
    summary.update(summary_overrides or {})
    return EvalSuite.from_mapping(
        {
            "schema": "roboclaws_eval_suite_v1",
            "suite_id": "household_world.scene_sampler_projection",
            "version": "2026-06-20",
            "capability": "household_world",
            "sample_ids": ["scene.sample_1"],
            "required_graders": ["sampler_admission"],
            "thresholds": {"pass_at_1": 1.0},
            "metadata": {
                "sampler_projection": {
                    "schema": "molmospaces_scene_sampler_projection_v1",
                    "projection": "camera-grounded-labels",
                    "generator_version": "unit",
                    "scene_sources": {"procthor-10k-val": source_payload},
                    "summary": summary,
                }
            },
        }
    )


def _sampler_projection() -> dict[str, object]:
    return {
        "schema": "molmospaces_scene_sampler_projection_v1",
        "projection": "camera-grounded-labels",
        "generator_version": "unit",
        "summary": _sampler_projection_summary(),
        "scene_sources": {
            "procthor-10k-val": {
                "support_status": "partial",
                "status": "partial_or_blocked",
                "target_count": 10,
                "ready_count": 5,
                "needed_count": 5,
                "blocked_count": 0,
                "rejected_count": 0,
                "sample_ids": ["scene.sample_1"],
            }
        },
    }


def _sampler_projection_summary() -> dict[str, object]:
    return {
        "source_count": 1,
        "target_sample_count": 10,
        "ready_sample_count": 5,
        "partial_source_count": 1,
        "rejected_source_count": 0,
        "blocked_source_count": 0,
        "complete_source_count": 0,
        "blocked_row_count": 0,
        "rejected_row_count": 0,
        "blocked_or_rejected_row_count": 0,
        "remaining_sample_count": 5,
    }


def _result() -> EvalResult:
    return EvalResult.from_mapping(
        {
            "schema": "roboclaws_eval_result_v1",
            "identity": {
                "suite_id": "household_world.scene_sampler_projection",
                "suite_version": "2026-06-20",
                "sample_id": "scene.sample_1",
                "sample_version": "2026-06-20",
                "trial_id": "trial-0000",
                "repetition_index": 0,
                "surface": "household-world",
                "intent": "map-build",
                "preset": "map-build",
                "world": "molmospaces/procthor-10k-val/0",
                "backend": "mujoco",
                "evidence_lane": "camera-grounded-labels",
                "camera_labeler": "grounding-dino",
                "scenario_setup": "baseline",
                "seed": 7,
                "prompt": "not_applicable",
                "goal_contract_hash": "unit",
                "agent_engine": "direct-runner",
                "runner_class": "direct",
                "provider_profile": "not_applicable",
                "model": "not_applicable",
                "skill_name": "not_applicable",
                "prompt_source": "not_applicable",
                "mcp_profile": "household_world",
                "tool_surface": ["observe"],
                "budgets": {},
                "runtime": {},
            },
            "status": "passed",
            "failure_class": "not_applicable",
            "grader_outputs": {},
            "artifacts": {},
            "metrics": {},
        }
    )
