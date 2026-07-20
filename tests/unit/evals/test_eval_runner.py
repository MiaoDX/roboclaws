from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any, Callable

import pytest

from roboclaws.evals.dependencies import dependency_failure, resolve_artifact_dependencies
from roboclaws.evals.live_runtime import live_surface_command, live_surface_env
from roboclaws.evals.models import load_eval_sample
from roboclaws.evals.regression import (
    promote_regression_from_cli_overrides,
    promote_regression_sample_from_eval_result,
)
from roboclaws.evals.runner import run_eval_suite
from roboclaws.launch.catalog import resolve_surface_launch
from tests.support import eval_runtime_map


def test_eval_runner_writes_result_bundle_and_report(tmp_path: Path) -> None:
    run = run_eval_suite(
        "smoke_regression",
        output_root=tmp_path,
        stamp="unit",
        product_runner=_passing_product_runner,
    )

    assert run.results_path.exists()
    assert run.report_path.exists()
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


def test_cleanup_outcome_accepts_semantic_success_when_exact_private_goal_is_partial(
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
    assert result["status"] == "passed"
    assert result["failure_class"] == "not_applicable"
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


def test_eval_runner_does_not_expose_map_build_scan_profile_override(
    tmp_path: Path,
) -> None:
    map_build_kwargs: dict[str, Any] = {}

    def product_runner(**kwargs: Any) -> dict[str, Any]:
        if kwargs.get("intent") == "map-build":
            map_build_kwargs.update(kwargs)
        return _passing_product_runner(**kwargs)

    run_eval_suite(
        "map_build_consumer",
        output_root=tmp_path,
        stamp="scan-profile-default",
        product_runner=product_runner,
    )

    assert map_build_kwargs["run_metadata_overrides"]["eval_sample_id"] == (
        "map_build.fixture_focused_seed7"
    )
    assert "map_build_scan_profile" not in map_build_kwargs


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


@pytest.mark.parametrize(
    ("artifact_name", "file_name"),
    [
        ("run_result", "run_result.json"),
        ("agent_view", "agent_view.json"),
        ("runtime_metric_map", "runtime_metric_map.json"),
        ("private_evaluation", "private_evaluation.json"),
    ],
)
def test_eval_runner_fails_aloud_on_malformed_required_json_artifact(
    tmp_path: Path,
    artifact_name: str,
    file_name: str,
) -> None:
    def product_runner(**kwargs: Any) -> dict[str, Any]:
        run_dir = Path(kwargs["output_dir"])
        _write_product_artifacts(run_dir, completion_status="success")
        result = _run_result(run_dir, completion_status="success")
        (run_dir / file_name).write_text('["not-an-object"]\n', encoding="utf-8")
        return result

    run = run_eval_suite(
        "smoke_regression",
        output_root=tmp_path,
        stamp=f"malformed-{artifact_name}",
        product_runner=product_runner,
    )

    payload = json.loads(run.results_path.read_text())
    assert payload["aggregate"]["failed"] == 1
    assert payload["aggregate"]["failure_classes"] == {"artifact_missing": 1}
    result = payload["results"][0]
    assert result["status"] == "failed"
    assert result["failure_class"] == "artifact_missing"
    artifacts = result["grader_outputs"]["artifacts"]
    assert artifacts["status"] == "failed"
    assert artifacts["failure_class"] == "artifact_missing"
    assert artifacts["source_errors"] == [
        {
            "artifact": artifact_name,
            "path": str(run.output_dir / "runs" / "cleanup_smoke_seed7" / "trial-0000" / file_name),
            "reason": "invalid_json_object",
        }
    ]


@pytest.mark.parametrize("sidecar_name", ["live_status.json", "live_timing.json"])
def test_eval_runner_fails_aloud_on_malformed_efficiency_sidecars(
    tmp_path: Path,
    sidecar_name: str,
) -> None:
    def product_runner(**kwargs: Any) -> dict[str, Any]:
        run_dir = Path(kwargs["output_dir"])
        _write_product_artifacts(run_dir, completion_status="success")
        (run_dir / sidecar_name).write_text("{", encoding="utf-8")
        return _run_result(run_dir, completion_status="success")

    run = run_eval_suite(
        "smoke_regression",
        output_root=tmp_path,
        stamp=f"malformed-{sidecar_name}",
        product_runner=product_runner,
    )

    payload = json.loads(run.results_path.read_text())
    result = payload["results"][0]
    efficiency = result["grader_outputs"]["efficiency"]
    assert result["status"] == "failed"
    assert result["failure_class"] == "artifact_missing"
    assert efficiency["status"] == "failed"
    assert efficiency["failure_class"] == "artifact_missing"
    assert efficiency["source_errors"][0]["path"].endswith(sidecar_name)
    assert efficiency["source_errors"][0]["reason"].startswith(
        "invalid_json:Expecting property name enclosed in double quotes"
    )


def test_eval_runner_classifies_environment_blocked_exception(tmp_path: Path) -> None:
    run = run_eval_suite(
        "smoke_regression",
        output_root=tmp_path,
        stamp="blocked",
        product_runner=_blocked_product_runner,
    )

    payload = json.loads(run.results_path.read_text())
    result = payload["results"][0]
    assert result["status"] == "blocked"
    assert result["failure_class"] == "environment_blocked"
    assert result["grader_outputs"]["runner"]["error_type"] == "RuntimeError"


def test_eval_runner_records_repetition_metrics(tmp_path: Path) -> None:
    run = run_eval_suite(
        "cleanup_capability",
        output_root=tmp_path,
        stamp="repeat",
        product_runner=_passing_product_runner,
    )

    payload = json.loads(run.results_path.read_text())
    assert payload["aggregate"]["total"] == 3
    assert payload["aggregate"]["sample_count"] == 1
    assert payload["aggregate"]["max_repetition_count"] == 3
    assert payload["aggregate"]["pass_at_k"] == {"1": 1.0, "2": 1.0, "3": 1.0}
    assert payload["aggregate"]["pass_caret_k"] == {"1": 1.0, "2": 1.0, "3": 1.0}
    assert payload["aggregate"]["pass_caret_k_eligible"] == {"1": 1, "2": 1, "3": 1}
    sample = payload["aggregate"]["samples"]["cleanup.repeated_seed7"]
    assert sample["trial_count"] == 3
    assert sample["pass_all"] is True
    assert [
        result["identity"]["repetition_index"]
        for result in payload["results"]
        if result["identity"]["sample_id"] == "cleanup.repeated_seed7"
    ] == [0, 1, 2]


def test_eval_runner_records_live_agent_blocked_identity(tmp_path: Path) -> None:
    run = run_eval_suite(
        "cleanup_capability",
        output_root=tmp_path,
        stamp="live-blocked",
        agent_engine="openai-agents-sdk",
        provider_profile="codex-router-responses",
        product_runner=_passing_product_runner,
    )

    payload = json.loads(run.results_path.read_text())
    assert payload["aggregate"]["total"] == 3
    assert payload["aggregate"]["blocked"] == 3
    assert payload["aggregate"]["pass_at_k"] == {"1": 0.0, "2": 0.0, "3": 0.0}
    assert payload["aggregate"]["pass_caret_k"] == {"1": 0.0, "2": 0.0, "3": 0.0}
    assert payload["aggregate"]["failure_classes"] == {"model_or_provider_unavailable": 3}
    result = payload["results"][0]
    assert result["status"] == "blocked"
    assert result["failure_class"] == "model_or_provider_unavailable"
    assert result["identity"]["agent_engine"] == "openai-agents-sdk"
    assert result["identity"]["runner_class"] == "live-agent"
    assert result["identity"]["provider_profile"] == "codex-router-responses"
    assert result["grader_outputs"]["runner"]["error_type"] == "LiveAgentEvalNotExecuted"
    preflight = result["grader_outputs"]["runner"]["preflight"]
    assert preflight["schema"] == "roboclaws_live_eval_preflight_v1"
    assert preflight["provider_readiness"]["provider_profile"] == "codex-router-responses"
    assert preflight["provider_readiness"]["required_env"] == ["CODEX_BASE_URL", "CODEX_API_KEY"]
    assert preflight["runtime_readiness"]["required_runtime"] == "OpenAI Agents SDK cleanup runner"
    assert preflight["blocker"] == "live_execution_not_requested"
    assert preflight["runtime_readiness"]["repo_native_live_eval_runner"] == (
        "opt_in_via_live_execution_run"
    )
    assert "live_agent_eval_execution_not_requested" in result["limitations"]


def test_eval_runner_runs_live_agent_when_explicitly_enabled(tmp_path: Path) -> None:
    seen_kwargs: list[dict[str, Any]] = []

    def live_product_runner(**kwargs: Any) -> dict[str, Any]:
        seen_kwargs.append(kwargs)
        surface_run_dir = Path(kwargs["output_dir"]) / "surface-run" / f"seed-{kwargs['seed']}"
        _write_product_artifacts(surface_run_dir, completion_status="success")
        result = _run_result(surface_run_dir, completion_status="success")
        result["eval_effective_run_dir"] = str(surface_run_dir)
        return result

    run = run_eval_suite(
        "cleanup_capability",
        output_root=tmp_path,
        stamp="live-run",
        agent_engine="openai-agents-sdk",
        provider_profile="codex-router-responses",
        live_execution="run",
        live_timeout_s=12.5,
        live_stall_timeout_s=6.25,
        live_product_runner=live_product_runner,
    )

    payload = json.loads(run.results_path.read_text())
    assert payload["aggregate"]["passed"] == 3
    assert payload["aggregate"]["blocked"] == 0
    assert seen_kwargs[0]["agent_engine"] == "openai-agents-sdk"
    assert seen_kwargs[0]["provider_profile"] == "codex-router-responses"
    assert seen_kwargs[0]["live_timeout_s"] == 12.5
    assert seen_kwargs[0]["live_stall_timeout_s"] == 6.25
    result = payload["results"][0]
    assert result["identity"]["runner_class"] == "live-agent"
    assert result["artifacts"]["run_result"].endswith(
        "runs/cleanup_repeated_seed7/trial-0000/surface-run/seed-7/run_result.json"
    )


def test_eval_runner_regrades_existing_live_artifacts_without_provider_call(
    tmp_path: Path,
) -> None:
    def live_product_runner(**kwargs: Any) -> dict[str, Any]:
        surface_run_dir = Path(kwargs["output_dir"]) / "surface-run" / f"seed-{kwargs['seed']}"
        _write_product_artifacts(surface_run_dir, completion_status="success")
        result = _run_result(surface_run_dir, completion_status="success")
        (surface_run_dir / "run_result.json").write_text(json.dumps(result) + "\n")
        result["eval_effective_run_dir"] = str(surface_run_dir)
        return result

    source_run = run_eval_suite(
        "cleanup_capability",
        output_root=tmp_path,
        stamp="live-source",
        agent_engine="openai-agents-sdk",
        provider_profile="codex-router-responses",
        live_execution="run",
        live_product_runner=live_product_runner,
    )

    def forbidden_live_product_runner(**_kwargs: Any) -> dict[str, Any]:
        raise AssertionError("regrade_source must not call the live provider route")

    regrade = run_eval_suite(
        "cleanup_capability",
        output_root=tmp_path,
        stamp="live-source-regrade",
        agent_engine="openai-agents-sdk",
        provider_profile="codex-router-responses",
        regrade_source=source_run.output_dir,
        live_product_runner=forbidden_live_product_runner,
    )

    payload = json.loads(regrade.results_path.read_text())
    assert payload["aggregate"]["passed"] == 3
    result = payload["results"][0]
    assert result["status"] == "passed"
    assert "live_eval_regraded_from_existing_artifacts" in result["limitations"]
    assert result["artifacts"]["run_result"].endswith(
        "live-source/runs/cleanup_repeated_seed7/trial-0000/surface-run/seed-7/run_result.json"
    )


def test_eval_runner_rejects_live_result_without_effective_run_dir(tmp_path: Path) -> None:
    def live_product_runner(**kwargs: Any) -> dict[str, Any]:
        stale_trial_dir = Path(kwargs["output_dir"])
        _write_product_artifacts(stale_trial_dir, completion_status="success")
        surface_run_dir = stale_trial_dir / "surface-run" / f"seed-{kwargs['seed']}"
        _write_product_artifacts(surface_run_dir, completion_status="success")
        return _run_result(surface_run_dir, completion_status="success")

    run = run_eval_suite(
        "cleanup_capability",
        output_root=tmp_path,
        stamp="live-missing-effective-run-dir",
        agent_engine="openai-agents-sdk",
        provider_profile="codex-router-responses",
        live_execution="run",
        live_product_runner=live_product_runner,
    )

    payload = json.loads(run.results_path.read_text())
    assert payload["aggregate"]["failed"] == 3
    assert payload["aggregate"]["failure_classes"] == {"artifact_missing": 3}
    result = payload["results"][0]
    assert result["status"] == "failed"
    assert result["failure_class"] == "artifact_missing"
    runner = result["grader_outputs"]["runner"]
    assert runner["status"] == "failed"
    assert runner["error_type"] == "ValueError"
    assert "missing eval_effective_run_dir" in runner["message"]
    assert result["artifacts"] == {}


def test_eval_runner_rejects_live_effective_run_dir_outside_trial(tmp_path: Path) -> None:
    external_run_dir = tmp_path / "external-live-route" / "seed-7"

    def live_product_runner(**kwargs: Any) -> dict[str, Any]:
        surface_run_dir = Path(kwargs["output_dir"]) / "surface-run" / f"seed-{kwargs['seed']}"
        _write_product_artifacts(surface_run_dir, completion_status="success")
        _write_product_artifacts(external_run_dir, completion_status="success")
        result = _run_result(surface_run_dir, completion_status="success")
        result["eval_effective_run_dir"] = str(external_run_dir)
        return result

    run = run_eval_suite(
        "cleanup_capability",
        output_root=tmp_path,
        stamp="live-escaped-effective-run-dir",
        agent_engine="openai-agents-sdk",
        provider_profile="codex-router-responses",
        live_execution="run",
        live_product_runner=live_product_runner,
    )

    payload = json.loads(run.results_path.read_text())
    assert payload["aggregate"]["failed"] == 3
    assert payload["aggregate"]["failure_classes"] == {"artifact_missing": 3}
    runner = payload["results"][0]["grader_outputs"]["runner"]
    assert runner["error_type"] == "ValueError"
    assert "eval_effective_run_dir must stay under trial run_dir" in runner["message"]


def test_eval_runner_classifies_live_provider_failures_as_blocked(tmp_path: Path) -> None:
    def live_product_runner(**_kwargs: Any) -> dict[str, Any]:
        raise RuntimeError(
            "OpenAI Agents SDK runtime failed: provider_transient_failure; "
            "Error code: 502 - bad_response_status_code"
        )

    run = run_eval_suite(
        "cleanup_capability",
        output_root=tmp_path,
        stamp="live-provider-blocked",
        agent_engine="openai-agents-sdk",
        provider_profile="codex-router-responses",
        live_execution="run",
        live_product_runner=live_product_runner,
    )

    payload = json.loads(run.results_path.read_text())
    assert payload["aggregate"]["blocked"] == 3
    assert payload["aggregate"]["failed"] == 0
    assert payload["aggregate"]["failure_classes"] == {"model_or_provider_unavailable": 3}
    result = payload["results"][0]
    assert result["status"] == "blocked"
    assert result["failure_class"] == "model_or_provider_unavailable"
    assert result["grader_outputs"]["runner"]["status"] == "blocked"


def test_eval_runner_classifies_live_tool_argument_failures_as_agent_failures(
    tmp_path: Path,
) -> None:
    def live_product_runner(**_kwargs: Any) -> dict[str, Any]:
        raise RuntimeError(
            "OpenAI Agents SDK runtime failed: agent_cli_failure; "
            "Error code: 400 - {'error': {'message': "
            "'invalid params, invalid function arguments json string, "
            "tool_call_id: call_function_1 (2013)', 'code': 'invalid_prompt'}}"
        )

    run = run_eval_suite(
        "cleanup_capability",
        output_root=tmp_path,
        stamp="live-tool-argument-invalid",
        agent_engine="openai-agents-sdk",
        provider_profile="minimax-responses",
        live_execution="run",
        live_product_runner=live_product_runner,
    )

    payload = json.loads(run.results_path.read_text())
    assert payload["aggregate"]["failed"] == 3
    assert payload["aggregate"]["blocked"] == 0
    assert payload["aggregate"]["failure_classes"] == {"tool_argument_invalid": 3}
    result = payload["results"][0]
    assert result["status"] == "failed"
    assert result["failure_class"] == "tool_argument_invalid"
    assert result["grader_outputs"]["runner"]["status"] == "failed"


def test_live_surface_product_discovers_timestamped_run_dir(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    from roboclaws.evals import live_runtime

    command_log: list[list[str]] = []

    def fake_run(
        command: list[str],
        **_kwargs: Any,
    ) -> Any:
        command_log.append(command)
        output_arg = next(item for item in command if item.startswith("output_dir="))
        output_dir = Path(output_arg.removeprefix("output_dir="))
        timestamped_run_dir = output_dir / "0615_0305" / "seed-7"
        _write_product_artifacts(timestamped_run_dir, completion_status="success")
        (timestamped_run_dir / "run_result.json").write_text(
            json.dumps(_run_result(timestamped_run_dir, completion_status="success")) + "\n"
        )
        (timestamped_run_dir / "live_status.json").write_text(
            '{"phase": "finished", "exit_status": 0}\n'
        )
        return _completed_process(returncode=0)

    _patch_live_surface_popen(monkeypatch, live_runtime, fake_run)

    result = live_runtime.run_live_surface_product(**_live_surface_kwargs(tmp_path / "trial-0000"))

    assert command_log
    assert result["eval_effective_run_dir"].endswith("surface-run/0615_0305/seed-7")
    assert (tmp_path / "trial-0000" / "live_eval_command.json").exists()


def test_live_surface_product_rejects_stale_sibling_run_artifacts(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    from roboclaws.evals import live_runtime

    trial_dir = tmp_path / "trial-0000"
    stale_run_dir = trial_dir / "surface-run" / "old-run" / "seed-7"
    _write_product_artifacts(stale_run_dir, completion_status="success")
    (stale_run_dir / "run_result.json").write_text(
        json.dumps(_run_result(stale_run_dir, completion_status="success")) + "\n"
    )
    for artifact in (stale_run_dir, *stale_run_dir.iterdir()):
        os.utime(artifact, (1.0, 1.0))

    def fake_run(
        _command: list[str],
        **_kwargs: Any,
    ) -> Any:
        return _completed_process(returncode=0)

    _patch_live_surface_popen(monkeypatch, live_runtime, fake_run)
    kwargs = _live_surface_kwargs(trial_dir, live_timeout_s=1.0)
    kwargs["agent_engine"] = "openai-agents-sdk"

    with pytest.raises(RuntimeError, match="stale live surface run artifacts"):
        live_runtime.run_live_surface_product(**kwargs)


def test_live_surface_product_rejects_mixed_fresh_and_stale_artifacts(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    from roboclaws.evals import live_runtime

    trial_dir = tmp_path / "trial-0000"
    run_dir = trial_dir / "surface-run" / "seed-7"
    _write_product_artifacts(run_dir, completion_status="success")
    (run_dir / "run_result.json").write_text(
        json.dumps(_run_result(run_dir, completion_status="success")) + "\n"
    )
    os.utime(run_dir / "run_result.json", (1.0, 1.0))

    def fake_run(
        _command: list[str],
        **_kwargs: Any,
    ) -> Any:
        (run_dir / "live_status.json").write_text('{"phase": "finished", "exit_status": 0}\n')
        return _completed_process(returncode=0)

    _patch_live_surface_popen(monkeypatch, live_runtime, fake_run)
    kwargs = _live_surface_kwargs(trial_dir, live_timeout_s=1.0)
    kwargs["agent_engine"] = "openai-agents-sdk"

    with pytest.raises(RuntimeError, match="stale live surface run artifacts"):
        live_runtime.run_live_surface_product(**kwargs)


def test_live_surface_product_rejects_stdout_artifacts_path_outside_surface_root(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    from roboclaws.evals import live_runtime

    trial_dir = tmp_path / "trial-0000"
    stale_trial_dir = trial_dir
    _write_product_artifacts(stale_trial_dir, completion_status="success")

    def fake_run(
        _command: list[str],
        **_kwargs: Any,
    ) -> Any:
        return _completed_process(
            returncode=0,
            stdout=f"Artifacts: {stale_trial_dir}\n",
        )

    _patch_live_surface_popen(monkeypatch, live_runtime, fake_run)
    kwargs = _live_surface_kwargs(trial_dir, live_timeout_s=1.0)
    kwargs["agent_engine"] = "openai-agents-sdk"

    with pytest.raises(RuntimeError, match="stdout live surface artifacts path must stay under"):
        live_runtime.run_live_surface_product(**kwargs)


def test_live_surface_product_rejects_stdout_artifacts_path_without_seed_leaf(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    from roboclaws.evals import live_runtime

    trial_dir = tmp_path / "trial-0000"
    wrong_leaf_dir = trial_dir / "surface-run" / "0615_0305"
    _write_product_artifacts(wrong_leaf_dir, completion_status="success")

    def fake_run(
        _command: list[str],
        **_kwargs: Any,
    ) -> Any:
        return _completed_process(
            returncode=0,
            stdout=f"Artifacts: {wrong_leaf_dir}\n",
        )

    _patch_live_surface_popen(monkeypatch, live_runtime, fake_run)
    kwargs = _live_surface_kwargs(trial_dir, live_timeout_s=1.0)
    kwargs["agent_engine"] = "openai-agents-sdk"

    with pytest.raises(
        RuntimeError, match="stdout live surface artifacts path must end with seed-7"
    ):
        live_runtime.run_live_surface_product(**kwargs)


def test_live_surface_discovery_fails_on_ambiguous_current_sibling_artifacts(
    tmp_path: Path,
) -> None:
    from roboclaws.evals import live_runtime

    output_dir = tmp_path / "surface-run"
    for stamp in ("0615_0305", "0615_0306"):
        _write_product_artifacts(
            output_dir / stamp / "seed-7",
            completion_status="success",
        )

    with pytest.raises(RuntimeError, match="ambiguous live surface run artifacts"):
        live_runtime.discover_live_surface_run_dir(
            {"seed": 7},
            output_dir=output_dir,
            fallback_run_dir=output_dir / "seed-7",
            started_wall_time_s=0.0,
        )


def test_live_surface_product_requires_sdk_run_result_after_foreground_success(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    from roboclaws.evals import live_runtime

    sleeps: list[float] = []

    def fake_run(
        command: list[str],
        **_kwargs: Any,
    ) -> Any:
        output_arg = next(item for item in command if item.startswith("output_dir="))
        output_dir = Path(output_arg.removeprefix("output_dir="))
        run_dir = output_dir / "0615_0310" / "seed-7"
        run_dir.mkdir(parents=True, exist_ok=True)
        (run_dir / "live_status.json").write_text('{"phase": "queued"}\n')
        return _completed_process(returncode=0)

    def fake_sleep(seconds: float) -> None:
        sleeps.append(seconds)

    _patch_live_surface_popen(monkeypatch, live_runtime, fake_run)
    monkeypatch.setattr(live_runtime.time, "sleep", fake_sleep)

    with pytest.raises(RuntimeError, match="live surface run finished without"):
        live_runtime.run_live_surface_product(
            **_live_surface_kwargs(tmp_path / "trial-0000", live_timeout_s=5.0)
        )

    assert sleeps == []


def test_live_surface_product_uses_default_live_budgets(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    from roboclaws.evals import live_runtime

    def fake_run(command: list[str], **kwargs: Any) -> Any:
        assert "timeout" not in kwargs
        output_arg = next(item for item in command if item.startswith("output_dir="))
        run_dir = Path(output_arg.removeprefix("output_dir=")) / "0615_0310" / "seed-7"
        _write_product_artifacts(run_dir, completion_status="success")
        (run_dir / "run_result.json").write_text(
            json.dumps(_run_result(run_dir, completion_status="success")) + "\n"
        )
        (run_dir / "live_status.json").write_text('{"phase": "finished", "exit_status": 0}\n')
        return _completed_process(returncode=0)

    _patch_live_surface_popen(monkeypatch, live_runtime, fake_run)

    live_runtime.run_live_surface_product(**_live_surface_kwargs(tmp_path / "trial-0000"))

    command_record = json.loads((tmp_path / "trial-0000" / "live_eval_command.json").read_text())
    assert command_record["wall_clock_budget_s"] == 1200.0
    assert command_record["stall_timeout_s"] == 120.0


def test_live_surface_product_fails_aloud_on_malformed_run_result(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    from roboclaws.evals import live_runtime

    def fake_run(command: list[str], **_kwargs: Any) -> Any:
        output_arg = next(item for item in command if item.startswith("output_dir="))
        run_dir = Path(output_arg.removeprefix("output_dir=")) / "seed-7"
        _write_product_artifacts(run_dir, completion_status="success")
        (run_dir / "run_result.json").write_text("{", encoding="utf-8")
        return _completed_process(returncode=0)

    _patch_live_surface_popen(monkeypatch, live_runtime, fake_run)

    run = run_eval_suite(
        "cleanup_capability",
        output_root=tmp_path,
        stamp="live-malformed-run-result",
        agent_engine="openai-agents-sdk",
        provider_profile="codex-router-responses",
        live_execution="run",
        live_timeout_s=12.5,
    )

    payload = json.loads(run.results_path.read_text())
    assert payload["aggregate"]["failed"] == 3
    assert payload["aggregate"]["failure_classes"] == {"artifact_missing": 3}
    result = payload["results"][0]
    assert result["status"] == "failed"
    assert result["failure_class"] == "artifact_missing"
    runner = result["grader_outputs"]["runner"]
    assert runner["status"] == "failed"
    assert runner["error_type"] == "ValueError"
    assert "invalid live eval JSON artifact" in runner["message"]


def test_live_timeout_completion_grace_env_override(monkeypatch: pytest.MonkeyPatch) -> None:
    from roboclaws.evals import live_runtime

    monkeypatch.delenv("ROBOCLAWS_LIVE_EVAL_TIMEOUT_COMPLETION_GRACE_S", raising=False)
    assert live_runtime.live_timeout_completion_grace_s() == 30.0

    monkeypatch.setenv("ROBOCLAWS_LIVE_EVAL_TIMEOUT_COMPLETION_GRACE_S", "0")
    assert live_runtime.live_timeout_completion_grace_s() == 0.0

    monkeypatch.setenv("ROBOCLAWS_LIVE_EVAL_TIMEOUT_COMPLETION_GRACE_S", "7.5")
    assert live_runtime.live_timeout_completion_grace_s() == 7.5


@pytest.mark.parametrize("value", ["bad", "nan", "inf", "-1"])
def test_live_timeout_completion_grace_rejects_invalid_env(
    monkeypatch: pytest.MonkeyPatch,
    value: str,
) -> None:
    from roboclaws.evals import live_runtime

    monkeypatch.setenv("ROBOCLAWS_LIVE_EVAL_TIMEOUT_COMPLETION_GRACE_S", value)

    with pytest.raises(
        ValueError,
        match=r"ROBOCLAWS_LIVE_EVAL_TIMEOUT_COMPLETION_GRACE_S must be a non-negative finite",
    ):
        live_runtime.live_timeout_completion_grace_s()


@pytest.mark.parametrize("value", ["0", "-1", "nan", "inf", "soon"])
def test_live_surface_timeout_rejects_invalid_config(value: str) -> None:
    from roboclaws.evals import live_runtime

    kwargs = _live_surface_kwargs(Path("trial-0000"), live_timeout_s=value)  # type: ignore[arg-type]

    with pytest.raises(
        ValueError,
        match=r"live_timeout_s must be a positive finite number of seconds",
    ):
        live_runtime.live_surface_timeout_s(kwargs)


@pytest.mark.parametrize("value", ["0", "-1", "nan", "inf", "soon"])
def test_live_stall_timeout_rejects_invalid_config(value: str) -> None:
    from roboclaws.evals import live_runtime

    kwargs = _live_surface_kwargs(
        Path("trial-0000"),
        live_stall_timeout_s=value,  # type: ignore[arg-type]
    )

    with pytest.raises(
        ValueError,
        match=r"live_stall_timeout_s must be a positive finite number of seconds",
    ):
        live_runtime.live_stall_timeout_s(kwargs)


def test_live_surface_timeout_accessors_use_split_defaults_and_overrides() -> None:
    from roboclaws.evals import live_runtime

    defaults = _live_surface_kwargs(Path("trial-0000"))
    assert live_runtime.live_wall_clock_budget_s(defaults) == 1200.0
    assert live_runtime.live_surface_timeout_s(defaults) == 1200.0
    assert live_runtime.explicit_live_surface_timeout_s(defaults) == 1200.0
    assert live_runtime.live_stall_timeout_s(defaults) == 120.0

    explicit = _live_surface_kwargs(
        Path("trial-0000"),
        live_timeout_s=300.0,
        live_stall_timeout_s=7.5,
    )
    assert live_runtime.live_wall_clock_budget_s(explicit) == 300.0
    assert live_runtime.live_stall_timeout_s(explicit) == 7.5


def test_live_surface_product_does_not_wait_after_sdk_process_success(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    from roboclaws.evals import live_runtime

    sleep_count = {"value": 0}

    def fake_run(command: list[str], **_kwargs: Any) -> Any:
        output_arg = next(item for item in command if item.startswith("output_dir="))
        output_dir = Path(output_arg.removeprefix("output_dir="))
        run_dir = output_dir / "0615_0312" / "seed-7"
        run_dir.mkdir(parents=True, exist_ok=True)
        (run_dir / "live_status.json").write_text('{"phase": "running-sdk"}\n')
        return _completed_process(returncode=0)

    def fake_sleep(seconds: float) -> None:
        sleep_count["value"] += 1

    _patch_live_surface_popen(monkeypatch, live_runtime, fake_run)
    monkeypatch.setattr(live_runtime.time, "sleep", fake_sleep)

    with pytest.raises(RuntimeError, match="live surface run finished without"):
        live_runtime.run_live_surface_product(
            **_live_surface_kwargs(tmp_path / "trial-0000", live_timeout_s=1.0)
        )

    assert sleep_count["value"] == 0


def test_live_surface_product_accepts_sdk_run_result_without_terminal_status(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    from roboclaws.evals import live_runtime

    sleeps: list[float] = []

    def fake_run(command: list[str], **_kwargs: Any) -> Any:
        output_arg = next(item for item in command if item.startswith("output_dir="))
        output_dir = Path(output_arg.removeprefix("output_dir="))
        run_dir = output_dir / "0615_0313" / "seed-7"
        _write_product_artifacts(run_dir, completion_status="success")
        (run_dir / "run_result.json").write_text(
            json.dumps(_run_result(run_dir, completion_status="success")) + "\n"
        )
        (run_dir / "live_status.json").write_text('{"phase": "finishing-sdk"}\n')
        return _completed_process(returncode=0)

    def fake_sleep(seconds: float) -> None:
        sleeps.append(seconds)

    _patch_live_surface_popen(monkeypatch, live_runtime, fake_run)
    monkeypatch.setattr(live_runtime.time, "sleep", fake_sleep)

    result = live_runtime.run_live_surface_product(
        **_live_surface_kwargs(tmp_path / "trial-0000", live_timeout_s=1.0)
    )

    assert sleeps == []
    assert result["eval_effective_run_dir"].endswith("surface-run/0615_0313/seed-7")


def test_live_surface_product_rejects_failed_live_status(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    from roboclaws.evals import live_runtime

    def fake_run(command: list[str], **_kwargs: Any) -> Any:
        output_arg = next(item for item in command if item.startswith("output_dir="))
        output_dir = Path(output_arg.removeprefix("output_dir="))
        run_dir = output_dir / "0615_0314" / "seed-7"
        _write_product_artifacts(run_dir, completion_status="success")
        (run_dir / "run_result.json").write_text(
            json.dumps(_run_result(run_dir, completion_status="success")) + "\n"
        )
        (run_dir / "live_status.json").write_text(
            '{"phase": "failed", "exit_status": 1, "reason": "provider failure"}\n'
        )
        return _completed_process(returncode=0)

    _patch_live_surface_popen(monkeypatch, live_runtime, fake_run)

    with pytest.raises(RuntimeError, match="live surface run reported failed status 1"):
        live_runtime.run_live_surface_product(
            **_live_surface_kwargs(tmp_path / "trial-0000", live_timeout_s=1.0)
        )


@pytest.mark.parametrize(
    "reason",
    [
        "observe_budget_exhausted",
        "agent_sdk_turn_budget_exceeded",
        "provider_context_budget_exceeded",
    ],
)
def test_live_eval_classifies_budget_runtime_failure(tmp_path: Path, reason: str) -> None:
    def live_product_runner(**_kwargs: Any) -> dict[str, Any]:
        raise RuntimeError(f"OpenAI Agents SDK runtime failed: {reason}")

    run = run_eval_suite(
        "open_ended_goals",
        output_root=tmp_path,
        stamp="live-open-ended-observe-budget",
        agent_engine="openai-agents-sdk",
        provider_profile="codex-router-responses",
        live_execution="run",
        live_product_runner=live_product_runner,
    )

    payload = json.loads(run.results_path.read_text())
    result = payload["results"][0]

    assert payload["aggregate"]["failed"] == 3
    assert payload["aggregate"]["failure_classes"] == {"budget_exhausted": 3}
    assert result["status"] == "failed"
    assert result["failure_class"] == "budget_exhausted"
    assert result["limitations"] == ["product_run_failed_before_grading"]


def test_live_open_ended_eval_grades_artifacts_after_checker_nonzero_exit(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    from roboclaws.evals import live_runtime

    def fake_run(command: list[str], **_kwargs: Any) -> Any:
        output_arg = next(item for item in command if item.startswith("output_dir="))
        output_dir = Path(output_arg.removeprefix("output_dir="))
        run_dir = output_dir / "seed-7"
        _write_product_artifacts(
            run_dir,
            completion_status="failed",
            include_goal_contract=True,
        )
        (run_dir / "run_result.json").write_text(
            json.dumps(
                _run_result(
                    run_dir,
                    completion_status="failed",
                    task_intent="open-ended",
                    include_completion_claim=True,
                )
            )
            + "\n"
        )
        (run_dir / "live_status.json").write_text(
            '{"phase": "failed", "exit_status": 1, '
            '"reason": "cleanup checker exited with status 1"}\n'
        )
        return _completed_process(
            returncode=1,
            stderr="cleanup checker exited with status 1",
        )

    _patch_live_surface_popen(monkeypatch, live_runtime, fake_run)

    run = run_eval_suite(
        "open_ended_goals",
        output_root=tmp_path,
        stamp="live-open-ended-checker-nonzero",
        agent_engine="openai-agents-sdk",
        provider_profile="codex-router-responses",
        live_execution="run",
        live_timeout_s=12.5,
    )

    payload = json.loads(run.results_path.read_text())
    assert payload["aggregate"]["passed"] == 3
    assert payload["aggregate"]["failed"] == 0
    result = payload["results"][0]
    assert result["status"] == "passed"
    assert result["failure_class"] == "not_applicable"
    assert result["identity"]["agent_engine"] == "openai-agents-sdk"
    command_record = json.loads(
        (
            tmp_path
            / "household_world_open_ended_goals"
            / "live-open-ended-checker-nonzero"
            / "runs"
            / "open_ended_drink_seed7"
            / "trial-0000"
            / "live_eval_command.json"
        ).read_text()
    )
    assert command_record["returncode"] == 1


def test_live_open_ended_eval_rejects_failed_foreground_status_even_with_artifacts(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    from roboclaws.evals import live_runtime
    from roboclaws.evals.models import load_eval_sample

    def fake_run(command: list[str], **_kwargs: Any) -> Any:
        output_arg = next(item for item in command if item.startswith("output_dir="))
        output_dir = Path(output_arg.removeprefix("output_dir="))
        run_dir = output_dir / "0616_1405" / "seed-7"
        _write_product_artifacts(
            run_dir,
            completion_status="failed",
            include_goal_contract=True,
        )
        (run_dir / "run_result.json").write_text(
            json.dumps(
                _run_result(
                    run_dir,
                    completion_status="failed",
                    task_intent="open-ended",
                    include_completion_claim=True,
                )
            )
            + "\n"
        )
        (run_dir / "live_status.json").write_text(
            '{"phase": "failed", "exit_status": 1, "reason": "provider failure"}\n'
        )
        return _completed_process(returncode=1, stderr="provider failure")

    _patch_live_surface_popen(monkeypatch, live_runtime, fake_run)
    sample = load_eval_sample(
        Path(__file__).resolve().parents[3]
        / "evals"
        / "household_world"
        / "samples"
        / "open_ended"
        / "drink_seed7.json"
    )
    kwargs = _live_surface_kwargs(tmp_path / "trial-0000", live_timeout_s=12.5)
    kwargs["eval_sample"] = sample

    with pytest.raises(RuntimeError, match="live surface run reported failed status 1"):
        live_runtime.run_live_surface_product(**kwargs)

    command_record = json.loads((tmp_path / "trial-0000" / "live_eval_command.json").read_text())
    assert command_record["returncode"] == 1


def test_live_cleanup_eval_grades_artifacts_after_checker_nonzero_exit(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    from roboclaws.evals import live_runtime

    def fake_run(command: list[str], **_kwargs: Any) -> Any:
        output_arg = next(item for item in command if item.startswith("output_dir="))
        output_dir = Path(output_arg.removeprefix("output_dir="))
        run_dir = output_dir / "seed-7"
        command_text = " ".join(command)
        if "preset=map-build" in command_text:
            _write_product_artifacts(run_dir, completion_status="map_build_complete")
            (run_dir / "live_status.json").write_text('{"phase": "finished", "exit_status": 0}\n')
            (run_dir / "run_result.json").write_text(
                json.dumps(
                    _run_result(
                        run_dir,
                        completion_status="map_build_complete",
                        map_build=True,
                    )
                )
                + "\n"
            )
            return _completed_process(returncode=0)
        if "preset=cleanup" not in command_text:
            _write_product_artifacts(
                run_dir,
                completion_status="success",
                include_goal_contract=True,
            )
            (run_dir / "live_status.json").write_text('{"phase": "finished", "exit_status": 0}\n')
            (run_dir / "run_result.json").write_text(
                json.dumps(
                    _run_result(
                        run_dir,
                        completion_status="success",
                        task_intent="open-ended",
                        include_completion_claim=True,
                    )
                )
                + "\n"
            )
            return _completed_process(returncode=0)
        _write_product_artifacts(run_dir, completion_status="partial_success")
        result = _run_result(
            run_dir,
            completion_status="partial_success",
            task_intent="cleanup",
        )
        result["score"]["semantic_acceptability"] = {
            "status": "success",
            "accepted_count": 5,
            "total_targets": 5,
        }
        (run_dir / "run_result.json").write_text(json.dumps(result) + "\n")
        (run_dir / "live_status.json").write_text(
            '{"phase": "failed", "exit_status": 1, '
            '"reason": "cleanup checker exited with status 1"}\n'
        )
        return _completed_process(returncode=1, stderr="cleanup checker exited with status 1")

    _patch_live_surface_popen(monkeypatch, live_runtime, fake_run)

    run = run_eval_suite(
        "map_build_consumer",
        output_root=tmp_path,
        stamp="live-cleanup-checker-nonzero",
        agent_engine="openai-agents-sdk",
        provider_profile="codex-router-responses",
        live_execution="run",
        live_timeout_s=12.5,
    )

    payload = json.loads(run.results_path.read_text())
    result = next(
        item
        for item in payload["results"]
        if item["identity"]["sample_id"] == "cleanup.consumer_no_prior_seed7"
    )
    assert result["status"] == "passed"
    assert result["failure_class"] == "not_applicable"
    assert result["grader_outputs"]["outcome"]["semantic_completion_status"] == "success"
    command_record = json.loads(
        (
            tmp_path
            / "household_world_map_build_consumer"
            / "live-cleanup-checker-nonzero"
            / "runs"
            / "cleanup_consumer_no_prior_seed7"
            / "trial-0000"
            / "live_eval_command.json"
        ).read_text()
    )
    assert command_record["returncode"] == 1


def test_open_ended_positive_predicates_pass_with_public_runtime_evidence(
    tmp_path: Path,
) -> None:
    def product_runner(**kwargs: Any) -> dict[str, Any]:
        run_dir = Path(kwargs["output_dir"])
        _write_product_artifacts(
            run_dir,
            completion_status="success",
            include_goal_contract=True,
        )
        return _run_result(
            run_dir,
            completion_status="success",
            task_intent="open-ended",
            include_completion_claim=True,
            wall_time_s=1.25,
        )

    run = run_eval_suite(
        "open_ended_goals",
        output_root=tmp_path,
        stamp="open-ended-positive-predicate",
        product_runner=product_runner,
    )

    payload = json.loads(run.results_path.read_text())
    assert payload["aggregate"]["passed"] == 3
    assert payload["aggregate"]["failed"] == 0
    assert payload["aggregate"]["open_ended"]["by_category"]["negative_search"]["passed"] == 1
    assert payload["aggregate"]["open_ended"]["by_category"]["area_inspection"]["passed"] == 1
    assert payload["aggregate"]["open_ended"]["by_category"]["positive_observable"]["passed"] == 1
    assert payload["aggregate"]["open_ended"]["telemetry"]["tool_call_count"] == 3
    results = {result["identity"]["sample_id"]: result for result in payload["results"]}
    room_predicate = results["open_ended.room4_anchor_seed7"]["grader_outputs"]["open_ended"][
        "success_predicate"
    ]
    living_predicate = results["open_ended.living_waypoint_seed7"]["grader_outputs"]["open_ended"][
        "success_predicate"
    ]
    assert room_predicate["passed"] is True
    assert room_predicate["evidence"]["anchor_id"] == "anchor_waypoint_room_6_inspection"
    assert living_predicate["passed"] is True
    assert "room_6_inspection" in living_predicate["evidence"]["visited_waypoint_ids"]


def test_open_ended_authoritative_predicate_failure_is_behavior_failure(
    tmp_path: Path,
) -> None:
    def product_runner(**kwargs: Any) -> dict[str, Any]:
        run_dir = Path(kwargs["output_dir"])
        _write_product_artifacts(
            run_dir,
            completion_status="success",
            include_goal_contract=True,
            include_open_ended_public_evidence=False,
        )
        (run_dir / "trace.jsonl").write_text(
            "\n".join(
                [
                    '{"event": "request", "tool": "metric_map"}',
                    '{"event": "response", "tool": "metric_map"}',
                    '{"event": "request", "tool": "done"}',
                    '{"event": "response", "tool": "done"}',
                ]
            )
            + "\n"
        )
        return _run_result(
            run_dir,
            completion_status="success",
            task_intent="open-ended",
            include_completion_claim=True,
        )

    run = run_eval_suite(
        "open_ended_goals",
        output_root=tmp_path,
        stamp="open-ended-positive-predicate-fail",
        product_runner=product_runner,
    )

    payload = json.loads(run.results_path.read_text())
    assert payload["aggregate"]["passed"] == 1
    assert payload["aggregate"]["failed"] == 2
    assert payload["aggregate"]["failure_classes"] == {"private_goal_not_satisfied": 2}
    results = {result["identity"]["sample_id"]: result for result in payload["results"]}
    assert results["open_ended.drink_seed7"]["status"] == "passed"
    assert results["open_ended.room4_anchor_seed7"]["status"] == "failed"
    assert results["open_ended.room4_anchor_seed7"]["failure_class"] == (
        "private_goal_not_satisfied"
    )


@pytest.mark.parametrize(
    ("sample_id", "field_name", "expected_error"),
    [
        (
            "open_ended.room4_anchor_seed7",
            "public_semantic_anchors",
            "public_semantic_anchors:invalid_json_array",
        ),
        (
            "open_ended.living_waypoint_seed7",
            "generated_exploration_candidates",
            "generated_exploration_candidates:invalid_json_array",
        ),
        (
            "open_ended.living_waypoint_seed7",
            "target_search_summary",
            "target_search_summary:invalid_json_object",
        ),
    ],
)
def test_open_ended_predicates_reject_wrong_shaped_runtime_map_sources(
    tmp_path: Path,
    sample_id: str,
    field_name: str,
    expected_error: str,
) -> None:
    def product_runner(**kwargs: Any) -> dict[str, Any]:
        run_dir = Path(kwargs["output_dir"])
        current_sample_id = kwargs["run_metadata_overrides"]["eval_sample_id"]
        _write_product_artifacts(
            run_dir,
            completion_status="success",
            include_goal_contract=True,
        )
        result = _run_result(
            run_dir,
            completion_status="success",
            task_intent="open-ended",
            include_completion_claim=True,
            include_runtime_map=current_sample_id != sample_id,
        )
        if current_sample_id == sample_id:
            runtime_map = json.loads((run_dir / "runtime_metric_map.json").read_text())
            runtime_map[field_name] = "wrong-shape"
            (run_dir / "runtime_metric_map.json").write_text(
                json.dumps(runtime_map) + "\n",
                encoding="utf-8",
            )
        return result

    run = run_eval_suite(
        "open_ended_goals",
        output_root=tmp_path,
        stamp=f"wrong-shaped-open-ended-{field_name}",
        product_runner=product_runner,
    )

    payload = json.loads(run.results_path.read_text())
    result = {item["identity"]["sample_id"]: item for item in payload["results"]}[sample_id]
    open_ended = result["grader_outputs"]["open_ended"]
    assert result["status"] == "failed"
    assert result["failure_class"] == "artifact_missing"
    assert open_ended["status"] == "failed"
    assert open_ended["failure_class"] == "artifact_missing"
    assert open_ended["semantic_satisfaction_status"] == "source_error"
    assert open_ended["success_predicate"]["source_error"] is True
    assert open_ended["source_errors"] == [
        {
            "path": str(
                run.output_dir
                / "runs"
                / sample_id.replace(".", "_")
                / "trial-0000"
                / "runtime_metric_map.json"
            ),
            "reason": expected_error,
        }
    ]


def test_open_ended_waypoint_predicate_accepts_trace_visit_without_runtime_anchor(
    tmp_path: Path,
) -> None:
    def product_runner(**kwargs: Any) -> dict[str, Any]:
        run_dir = Path(kwargs["output_dir"])
        sample_id = kwargs["run_metadata_overrides"]["eval_sample_id"]
        _write_product_artifacts(
            run_dir,
            completion_status="success",
            include_goal_contract=True,
            include_open_ended_public_evidence=sample_id != "open_ended.living_waypoint_seed7",
        )
        if sample_id == "open_ended.room4_anchor_seed7":
            (run_dir / "trace.jsonl").write_text(
                "\n".join(
                    [
                        '{"event": "request", "tool": "resolve_target_query"}',
                        '{"event": "response", "tool": "resolve_target_query"}',
                        (
                            '{"event": "request", "tool": "navigate_to_waypoint", '
                            '"request": {"waypoint_id": "room_6_inspection"}}'
                        ),
                        '{"event": "response", "tool": "navigate_to_waypoint"}',
                        '{"event": "request", "tool": "observe"}',
                        '{"event": "response", "tool": "observe"}',
                        '{"event": "request", "tool": "done"}',
                        '{"event": "response", "tool": "done"}',
                    ]
                )
                + "\n"
            )
        if sample_id == "open_ended.living_waypoint_seed7":
            (run_dir / "trace.jsonl").write_text(
                "\n".join(
                    [
                        '{"event": "request", "tool": "metric_map"}',
                        '{"event": "response", "tool": "metric_map"}',
                        (
                            '{"event": "request", "tool": "navigate_to_waypoint", '
                            '"request": {"waypoint_id": "room_6_inspection"}}'
                        ),
                        '{"event": "response", "tool": "navigate_to_waypoint"}',
                        '{"event": "request", "tool": "done"}',
                        '{"event": "response", "tool": "done"}',
                    ]
                )
                + "\n"
            )
        return _run_result(
            run_dir,
            completion_status="success",
            task_intent="open-ended",
            include_completion_claim=True,
        )

    run = run_eval_suite(
        "open_ended_goals",
        output_root=tmp_path,
        stamp="open-ended-trace-visit",
        product_runner=product_runner,
    )

    payload = json.loads(run.results_path.read_text())
    assert payload["aggregate"]["passed"] == 3
    results = {result["identity"]["sample_id"]: result for result in payload["results"]}
    assert results["open_ended.room4_anchor_seed7"]["grader_outputs"]["trajectory"]["status"] == (
        "passed"
    )
    assert (
        results["open_ended.living_waypoint_seed7"]["grader_outputs"]["open_ended"][
            "success_predicate"
        ]["passed"]
        is True
    )


def test_eval_runner_fails_trajectory_when_trace_contains_malformed_json(
    tmp_path: Path,
) -> None:
    def product_runner(**kwargs: Any) -> dict[str, Any]:
        run_dir = Path(kwargs["output_dir"])
        _write_product_artifacts(
            run_dir,
            completion_status="success",
            include_goal_contract=True,
        )
        (run_dir / "trace.jsonl").write_text(
            "\n".join(
                [
                    '{"event": "response", "tool": "metric_map"}',
                    "{",
                    '{"event": "response", "tool": "done"}',
                ]
            )
            + "\n",
            encoding="utf-8",
        )
        return _run_result(
            run_dir,
            completion_status="success",
            task_intent="open-ended",
            include_completion_claim=True,
        )

    run = run_eval_suite(
        "open_ended_goals",
        output_root=tmp_path,
        stamp="malformed-trace",
        product_runner=product_runner,
    )

    payload = json.loads(run.results_path.read_text())
    results = {result["identity"]["sample_id"]: result for result in payload["results"]}
    result = results["open_ended.drink_seed7"]
    trajectory = result["grader_outputs"]["trajectory"]
    assert result["status"] == "failed"
    assert result["failure_class"] == "trajectory_policy_violation"
    assert trajectory["missing_required_tools"] == []
    assert trajectory["violations"] == ["trace_json_invalid"]
    assert trajectory["trace_parse_errors"][0].startswith(
        "line 2: invalid_json:Expecting property name enclosed in double quotes"
    )


def test_eval_runner_fails_trajectory_when_trace_contains_non_object_json(
    tmp_path: Path,
) -> None:
    def product_runner(**kwargs: Any) -> dict[str, Any]:
        run_dir = Path(kwargs["output_dir"])
        _write_product_artifacts(
            run_dir,
            completion_status="success",
            include_goal_contract=True,
        )
        (run_dir / "trace.jsonl").write_text(
            "\n".join(
                [
                    '{"event": "response", "tool": "metric_map"}',
                    "[]",
                    '{"event": "response", "tool": "done"}',
                ]
            )
            + "\n",
            encoding="utf-8",
        )
        return _run_result(
            run_dir,
            completion_status="success",
            task_intent="open-ended",
            include_completion_claim=True,
        )

    run = run_eval_suite(
        "open_ended_goals",
        output_root=tmp_path,
        stamp="non-object-trace",
        product_runner=product_runner,
    )

    payload = json.loads(run.results_path.read_text())
    results = {result["identity"]["sample_id"]: result for result in payload["results"]}
    trajectory = results["open_ended.drink_seed7"]["grader_outputs"]["trajectory"]
    assert trajectory["violations"] == ["trace_json_invalid"]
    assert trajectory["trace_parse_errors"] == ["line 2: invalid_json_object"]


@pytest.mark.parametrize("sidecar_name", ["advisory_evaluation.json", "runtime_metric_map.json"])
def test_open_ended_eval_fails_aloud_on_malformed_source_sidecars(
    tmp_path: Path,
    sidecar_name: str,
) -> None:
    def product_runner(**kwargs: Any) -> dict[str, Any]:
        run_dir = Path(kwargs["output_dir"])
        sample_id = kwargs["run_metadata_overrides"]["eval_sample_id"]
        _write_product_artifacts(
            run_dir,
            completion_status="success",
            include_goal_contract=True,
        )
        result = _run_result(
            run_dir,
            completion_status="success",
            task_intent="open-ended",
            include_completion_claim=True,
            include_runtime_map=sidecar_name != "runtime_metric_map.json",
        )
        if sample_id == "open_ended.room4_anchor_seed7":
            if sidecar_name == "advisory_evaluation.json":
                result.pop("advisory_evaluation")
            (run_dir / sidecar_name).write_text("{", encoding="utf-8")
        return result

    run = run_eval_suite(
        "open_ended_goals",
        output_root=tmp_path,
        stamp=f"malformed-{sidecar_name}",
        product_runner=product_runner,
    )

    payload = json.loads(run.results_path.read_text())
    result = {item["identity"]["sample_id"]: item for item in payload["results"]}[
        "open_ended.room4_anchor_seed7"
    ]
    open_ended = result["grader_outputs"]["open_ended"]
    assert result["status"] == "failed"
    assert result["failure_class"] == "artifact_missing"
    assert open_ended["status"] == "failed"
    assert open_ended["failure_class"] == "artifact_missing"
    assert open_ended["semantic_satisfaction_status"] == "source_error"
    assert open_ended["source_errors"][0]["path"].endswith(sidecar_name)
    assert open_ended["source_errors"][0]["reason"].startswith(
        "invalid_json:Expecting property name enclosed in double quotes"
    )


def test_live_surface_command_uses_current_public_launch_axes(tmp_path: Path) -> None:
    seen_kwargs: list[dict[str, Any]] = []

    def live_product_runner(**kwargs: Any) -> dict[str, Any]:
        seen_kwargs.append(kwargs)
        run_dir = Path(kwargs["output_dir"])
        _write_product_artifacts(run_dir, completion_status="success")
        return _run_result(run_dir, completion_status="success")

    run_eval_suite(
        "cleanup_capability",
        output_root=tmp_path,
        stamp="live-command",
        agent_engine="openai-agents-sdk",
        provider_profile="codex-router-responses",
        live_execution="run",
        live_product_runner=live_product_runner,
    )

    command = live_surface_command(seen_kwargs[0], output_dir=tmp_path / "surface-run")
    assert "backend=mujoco" in command
    assert "agent_engine=openai-agents-sdk" in command
    assert "provider_profile=codex-router-responses" in command
    assert "evidence_lane=world-public-labels" in command
    assert "run_preset=smoke" in command
    assert "preset=cleanup" in command
    assert not any(item.startswith("generated_mess_count=") for item in command)
    plan = resolve_surface_launch(command[5:])
    assert plan.agent_engine == "openai-agents-sdk"
    assert plan.dispatch_runner == "openai-agents-live"
    assert plan.backend == "mujoco"
    assert plan.evidence_mode == "smoke"


def test_live_surface_command_passes_map_build_camera_labeler(tmp_path: Path) -> None:
    sample = load_eval_sample(
        Path(__file__).resolve().parents[3]
        / "evals"
        / "household_world"
        / "samples"
        / "map_build"
        / "baseline_seed7.json"
    )
    kwargs = _live_surface_kwargs(tmp_path / "trial-0000")
    kwargs.update(
        {
            "eval_sample": sample,
            "agent_engine": "openai-agents-sdk",
            "provider_profile": "codex-router-responses",
            "evidence_lane": sample.evidence_lane,
            "visual_grounding": sample.camera_labeler,
            "map_build": True,
            "task_prompt": "帮我建立这个房间的 Runtime Metric Map",
        }
    )

    command = live_surface_command(kwargs, output_dir=tmp_path / "surface-run")

    assert "preset=map-build" in command
    assert "evidence_lane=camera-grounded-labels" in command
    assert "camera_labeler=grounding-dino" in command
    assert "agent_engine=openai-agents-sdk" in command
    plan = resolve_surface_launch(command[5:])
    assert plan.intent == "map-build"
    assert plan.dispatch_runner == "openai-agents-live"
    assert plan.evidence_mode == "camera-grounded-labels"


def test_live_surface_command_uses_no_preset_public_open_task_route(tmp_path: Path) -> None:
    seen_kwargs: list[dict[str, Any]] = []

    def live_product_runner(**kwargs: Any) -> dict[str, Any]:
        seen_kwargs.append(kwargs)
        run_dir = Path(kwargs["output_dir"])
        _write_product_artifacts(
            run_dir,
            completion_status="success",
            include_goal_contract=True,
        )
        return _run_result(
            run_dir,
            completion_status="success",
            task_intent="open-ended",
            include_completion_claim=True,
        )

    run_eval_suite(
        "open_ended_goals",
        output_root=tmp_path,
        stamp="live-open-task-command",
        agent_engine="openai-agents-sdk",
        provider_profile="codex-router-responses",
        live_execution="run",
        live_product_runner=live_product_runner,
    )

    command = live_surface_command(seen_kwargs[0], output_dir=tmp_path / "surface-run")
    assert "surface=household-world" in command
    assert "agent_engine=openai-agents-sdk" in command
    assert "provider_profile=codex-router-responses" in command
    assert "run_preset=smoke" in command
    assert not any(item.startswith("preset=") for item in command)
    assert any(item.startswith("prompt=") for item in command)
    plan = resolve_surface_launch(command[5:])
    assert plan.intent == "open-ended"
    assert plan.preset is None


@pytest.mark.parametrize(
    ("field_name", "value", "expected_error"),
    [
        ("generated_mess_count", "bad", "generated_mess_count must be a non-negative integer"),
        ("generated_mess_count", "-1", "generated_mess_count must be a non-negative integer"),
        ("generated_mess_count", "5.5", "generated_mess_count must be a non-negative integer"),
        ("generated_mess_count", 5.0, "generated_mess_count must be a non-negative integer"),
        ("generated_mess_count", True, "generated_mess_count must be a non-negative integer"),
        ("scene_index", "bad", "scene_index must be a non-negative integer"),
        ("scene_index", "-1", "scene_index must be a non-negative integer"),
        ("scene_index", "5.5", "scene_index must be a non-negative integer"),
        ("scene_index", 5.0, "scene_index must be a non-negative integer"),
        ("scene_index", True, "scene_index must be a non-negative integer"),
        ("scene_source", "", "scene_source must be a non-empty string"),
        ("scene_source", "  ", "scene_source must be a non-empty string"),
        ("scene_source", 7, "scene_source must be a non-empty string"),
        ("scene_source", True, "scene_source must be a non-empty string"),
    ],
)
def test_live_surface_command_rejects_invalid_launch_metadata(
    tmp_path: Path,
    field_name: str,
    value: object,
    expected_error: str,
) -> None:
    kwargs = _live_surface_kwargs(tmp_path / "trial-0000")
    if field_name == "generated_mess_count":
        kwargs["evidence_lane"] = "world-public-labels"
    kwargs[field_name] = value

    with pytest.raises(ValueError, match=expected_error):
        live_surface_command(kwargs, output_dir=tmp_path / "surface-run")


@pytest.mark.parametrize(
    ("case_name", "mutate", "expected_error"),
    [
        (
            "generated-mess-count",
            lambda sample: sample["private_goal_reference"].__setitem__(
                "generated_mess_count",
                "five",
            ),
            "private_goal_reference.generated_mess_count must be a non-negative integer",
        ),
        (
            "scene-index",
            lambda sample: sample["launch_overrides"].__setitem__("scene_index", True),
            "launch_overrides.scene_index must be a non-negative integer",
        ),
        (
            "scene-source",
            lambda sample: sample["launch_overrides"].__setitem__("scene_source", ""),
            "launch_overrides.scene_source must be a non-empty string",
        ),
    ],
)
def test_eval_runner_rejects_invalid_sample_launch_metadata(
    tmp_path: Path,
    case_name: str,
    mutate: Callable[[dict[str, Any]], None],
    expected_error: str,
) -> None:
    result = _run_invalid_cleanup_sample(
        tmp_path,
        sample_id=f"cleanup.invalid_{case_name.replace('-', '_')}",
        stamp=f"invalid-{case_name}",
        mutate=mutate,
        assertion_message=f"product runner should not launch with invalid {case_name}",
    )

    assert result["status"] == "failed"
    assert result["failure_class"] == "artifact_missing"
    assert result["grader_outputs"]["runner"]["error_type"] == "ValueError"
    assert expected_error in result["grader_outputs"]["runner"]["message"]


def test_live_surface_env_sets_provider_and_model_keys(tmp_path: Path) -> None:
    kwargs: dict[str, Any] = {
        "agent_engine": "openai-agents-sdk",
        "provider_profile": "codex-router-responses",
        "model": "gpt-5.5",
    }

    env = live_surface_env(kwargs, base_env={"PATH": "/bin"})

    assert env["PATH"] == "/bin"
    assert env["ROBOCLAWS_PROVIDER_PROFILE"] == "codex-router-responses"
    assert env["ROBOCLAWS_CODEX_MODEL"] == "gpt-5.5"


def test_map_build_consumer_suite_passes_runtime_map_prior_between_samples(
    tmp_path: Path,
) -> None:
    seen_runtime_priors: dict[str, str] = {}

    def product_runner(**kwargs: Any) -> dict[str, Any]:
        run_dir = Path(kwargs["output_dir"])
        sample_id = kwargs["run_metadata_overrides"]["eval_sample_id"]
        if "runtime_map_prior_path" in kwargs:
            seen_runtime_priors[sample_id] = str(kwargs["runtime_map_prior_path"])
        if sample_id == "map_build.fixture_focused_seed7":
            _write_product_artifacts(run_dir, completion_status="map_build_complete")
            return _run_result(
                run_dir,
                completion_status="map_build_complete",
                map_build=True,
            )
        if sample_id.startswith("open_ended."):
            _write_product_artifacts(
                run_dir,
                completion_status="success",
                include_goal_contract=True,
            )
            return _run_result(
                run_dir,
                completion_status="success",
                task_intent="open-ended",
                final_status="success",
                include_completion_claim=True,
            )
        _write_product_artifacts(run_dir, completion_status="success")
        return _run_result(run_dir, completion_status="success")

    run = run_eval_suite(
        "map_build_consumer",
        output_root=tmp_path,
        stamp="map-consumer",
        product_runner=product_runner,
    )

    payload = json.loads(run.results_path.read_text())
    assert payload["aggregate"]["passed"] == 5
    assert payload["aggregate"]["failed"] == 0
    assert seen_runtime_priors == {
        "open_ended.stable_anchor_fixture_focused_prior_seed7": (
            str(run.output_dir)
            + "/runs/map_build_fixture_focused_seed7/trial-0000/runtime_metric_map.json"
        ),
        "cleanup.consumer_fixture_focused_prior_seed7": (
            str(run.output_dir)
            + "/runs/map_build_fixture_focused_seed7/trial-0000/runtime_metric_map.json"
        ),
    }
    results = {result["identity"]["sample_id"]: result for result in payload["results"]}
    map_result = results["map_build.fixture_focused_seed7"]
    assert map_result["grader_outputs"]["outcome"]["runtime_metric_map_schema"] == (
        "runtime_metric_map_v1"
    )
    assert map_result["grader_outputs"]["outcome"]["public_semantic_anchor_count"] >= 20
    open_result = results["open_ended.stable_anchor_fixture_focused_prior_seed7"]
    assert open_result["status"] == "passed"
    assert open_result["grader_outputs"]["outcome"]["completion_claim_present"] is True
    assert open_result["grader_outputs"]["outcome"]["artifact_readiness"] == "ready"
    assert (
        open_result["grader_outputs"]["open_ended"]["semantic_satisfaction_authoritative"] is False
    )


def test_focused_map_build_eval_passes_camera_labeler_to_product_runner(
    tmp_path: Path,
) -> None:
    captured_kwargs: dict[str, Any] = {}
    suite_path = tmp_path / "camera_grounded_map_build_suite.json"
    suite_path.write_text(
        json.dumps(
            {
                "schema": "roboclaws_eval_suite_v1",
                "suite_id": "household_world.camera_grounded_map_build",
                "version": "2026-06-24",
                "capability": "household_world",
                "sample_ids": ["map_build.baseline_seed7"],
                "sample_refs": ["evals/household_world/samples/map_build/baseline_seed7.json"],
                "required_graders": ["artifacts", "privacy", "trajectory", "outcome"],
                "thresholds": {"pass_at_1": 1.0},
            }
        ),
        encoding="utf-8",
    )

    def product_runner(**kwargs: Any) -> dict[str, Any]:
        if kwargs["run_metadata_overrides"]["eval_sample_id"] == "map_build.baseline_seed7":
            captured_kwargs.update(kwargs)
        run_dir = Path(kwargs["output_dir"])
        _write_product_artifacts(run_dir, completion_status="map_build_complete")
        return _run_result(
            run_dir,
            completion_status="map_build_complete",
            map_build=True,
        )

    run_eval_suite(
        str(suite_path),
        output_root=tmp_path,
        stamp="map-build-camera-labeler",
        budget="focused",
        product_runner=product_runner,
    )

    assert captured_kwargs["evidence_lane"] == "camera-grounded-labels"
    assert captured_kwargs["visual_grounding"] == "grounding-dino"


def test_map_build_eval_catches_unusable_runtime_metric_map(tmp_path: Path) -> None:
    def product_runner(**kwargs: Any) -> dict[str, Any]:
        run_dir = Path(kwargs["output_dir"])
        _write_product_artifacts(run_dir, completion_status="map_build_complete")
        if kwargs["run_metadata_overrides"]["eval_sample_id"] == "map_build.fixture_focused_seed7":
            (run_dir / "runtime_metric_map.json").write_text('{"schema": "wrong"}\n')
        return _run_result(run_dir, completion_status="map_build_complete")

    run = run_eval_suite(
        "evals/household_world/suites/map_build_consumer.json",
        output_root=tmp_path,
        stamp="bad-map",
        product_runner=product_runner,
    )

    payload = json.loads(run.results_path.read_text())
    result = payload["results"][0]
    assert result["identity"]["sample_id"] == "map_build.fixture_focused_seed7"
    assert result["status"] == "failed"
    assert result["failure_class"] == "map_actionability_failure"
    assert result["grader_outputs"]["outcome"]["schema_ok"] is False


def test_map_build_eval_uses_molmospaces_backend_fixture_truth_for_live_backend(
    tmp_path: Path,
) -> None:
    def product_runner(**kwargs: Any) -> dict[str, Any]:
        run_dir = Path(kwargs["output_dir"])
        _write_product_artifacts(run_dir, completion_status="map_build_complete")
        if kwargs["run_metadata_overrides"]["eval_sample_id"] == "map_build.fixture_focused_seed7":
            _write_molmospaces_map_build_artifacts(run_dir)
            return _run_result(
                run_dir,
                completion_status="map_build_complete",
                map_build=True,
                backend="molmospaces_subprocess",
            )
        return _run_result(run_dir, completion_status="success")

    run = run_eval_suite(
        "evals/household_world/suites/map_build_consumer.json",
        output_root=tmp_path,
        stamp="molmospaces-truth",
        budget="focused",
        product_runner=product_runner,
    )

    payload = json.loads(run.results_path.read_text())
    result = payload["results"][0]
    outcome = result["grader_outputs"]["outcome"]
    assert result["identity"]["sample_id"] == "map_build.fixture_focused_seed7"
    assert result["status"] == "passed"
    assert outcome["sim_truth_fixture_category_recall"] == 1.0
    assert outcome["sim_truth_fixture_category_precision"] == 1.0
    assert outcome["sim_truth_best_view_waypoint_accuracy"] == 1.0
    assert outcome["sim_truth_expected_fixture_categories"] == [
        "bed",
        "countertop",
        "desk",
        "diningtable",
        "fridge",
        "shelvingunit",
        "sink",
        "sofa",
        "tvstand",
    ]


def test_map_build_eval_keeps_molmospaces_best_view_waypoint_gate(tmp_path: Path) -> None:
    def product_runner(**kwargs: Any) -> dict[str, Any]:
        run_dir = Path(kwargs["output_dir"])
        _write_product_artifacts(run_dir, completion_status="map_build_complete")
        if kwargs["run_metadata_overrides"]["eval_sample_id"] == "map_build.fixture_focused_seed7":
            _write_molmospaces_map_build_artifacts(run_dir, wrong_waypoint_category="desk")
            return _run_result(
                run_dir,
                completion_status="map_build_complete",
                map_build=True,
                backend="molmospaces_subprocess",
            )
        return _run_result(run_dir, completion_status="success")

    run = run_eval_suite(
        "evals/household_world/suites/map_build_consumer.json",
        output_root=tmp_path,
        stamp="molmospaces-bad-waypoint",
        budget="focused",
        product_runner=product_runner,
    )

    payload = json.loads(run.results_path.read_text())
    result = payload["results"][0]
    outcome = result["grader_outputs"]["outcome"]
    assert result["identity"]["sample_id"] == "map_build.fixture_focused_seed7"
    assert result["status"] == "failed"
    assert result["failure_class"] == "map_actionability_failure"
    assert outcome["sim_truth_fixture_category_recall"] == 1.0
    assert outcome["sim_truth_best_view_waypoint_accuracy"] < 1.0
    assert outcome["sim_truth_best_view_waypoint_mismatches"]


@pytest.mark.parametrize(
    ("runtime_map_text", "expected_error"),
    [
        ("{", "invalid_json:Expecting property name enclosed in double quotes"),
        ("[]", "invalid_json_object"),
    ],
)
def test_map_build_eval_classifies_malformed_runtime_metric_map_as_invalid_artifact(
    tmp_path: Path,
    runtime_map_text: str,
    expected_error: str,
) -> None:
    def product_runner(**kwargs: Any) -> dict[str, Any]:
        run_dir = Path(kwargs["output_dir"])
        _write_product_artifacts(run_dir, completion_status="map_build_complete")
        (run_dir / "runtime_metric_map.json").write_text(runtime_map_text, encoding="utf-8")
        return _run_result(
            run_dir,
            completion_status="map_build_complete",
            include_runtime_map=False,
        )

    run = run_eval_suite(
        "evals/household_world/suites/map_build_consumer.json",
        output_root=tmp_path,
        stamp="malformed-map",
        product_runner=product_runner,
    )

    payload = json.loads(run.results_path.read_text())
    result = payload["results"][0]
    outcome = result["grader_outputs"]["outcome"]
    assert result["identity"]["sample_id"] == "map_build.fixture_focused_seed7"
    assert result["status"] == "failed"
    assert result["failure_class"] == "artifact_missing"
    assert outcome["failure_class"] == "artifact_missing"
    assert outcome["runtime_metric_map_exists"] is True
    assert outcome["runtime_metric_map_error"].startswith(expected_error)
    assert outcome["runtime_metric_map_schema"] == "unavailable"


@pytest.mark.parametrize(
    ("field_name", "expected_error"),
    [
        ("public_semantic_anchors", "public_semantic_anchors:invalid_json_array"),
        (
            "generated_exploration_candidates",
            "generated_exploration_candidates:invalid_json_array",
        ),
    ],
)
def test_map_build_eval_rejects_wrong_shaped_runtime_map_lists(
    tmp_path: Path,
    field_name: str,
    expected_error: str,
) -> None:
    def product_runner(**kwargs: Any) -> dict[str, Any]:
        run_dir = Path(kwargs["output_dir"])
        _write_product_artifacts(run_dir, completion_status="map_build_complete")
        runtime_map = json.loads((run_dir / "runtime_metric_map.json").read_text())
        runtime_map[field_name] = "looks-like-many-items"
        (run_dir / "runtime_metric_map.json").write_text(
            json.dumps(runtime_map) + "\n",
            encoding="utf-8",
        )
        return _run_result(
            run_dir,
            completion_status="map_build_complete",
            include_runtime_map=False,
        )

    run = run_eval_suite(
        "evals/household_world/suites/map_build_consumer.json",
        output_root=tmp_path,
        stamp=f"wrong-shaped-{field_name}",
        product_runner=product_runner,
    )

    payload = json.loads(run.results_path.read_text())
    result = payload["results"][0]
    outcome = result["grader_outputs"]["outcome"]
    assert result["identity"]["sample_id"] == "map_build.fixture_focused_seed7"
    assert result["status"] == "failed"
    assert result["failure_class"] == "artifact_missing"
    assert outcome["failure_class"] == "artifact_missing"
    assert outcome["runtime_metric_map_error"] == expected_error
    assert outcome["runtime_metric_map_schema"] == "runtime_metric_map_v1"


def test_scene_sampler_stress_records_sampler_admission(tmp_path: Path) -> None:
    def product_runner(**kwargs: Any) -> dict[str, Any]:
        run_dir = Path(kwargs["output_dir"])
        _write_product_artifacts(
            run_dir,
            completion_status="map_build_complete",
            generated_exploration_candidate_count=20,
        )
        return _run_result(
            run_dir,
            completion_status="map_build_complete",
            map_build=True,
        )

    run = run_eval_suite(
        "scene_sampler_stress",
        output_root=tmp_path,
        stamp="scene-sampler",
        product_runner=product_runner,
    )

    payload = json.loads(run.results_path.read_text())
    assert payload["aggregate"]["sample_count"] == 16
    assert payload["aggregate"]["passed"] == 16
    assert payload["aggregate"]["failed"] == 0
    sampler_projection = payload["aggregate"]["sampler_projection"]
    assert sampler_projection["summary"]["ready_sample_count"] == 16
    assert sampler_projection["summary"]["remaining_sample_count"] == 24
    assert sampler_projection["summary"]["partial_source_count"] == 1
    assert sampler_projection["summary"]["blocked_source_count"] == 0
    assert sampler_projection["summary"]["rejected_source_count"] == 2
    assert sampler_projection["scene_sources"]["procthor-10k-val"]["ready_count"] == 6
    assert sampler_projection["scene_sources"]["procthor-10k-val"]["needed_count"] == 4
    assert sampler_projection["scene_sources"]["procthor-objaverse-val"]["ready_count"] == 10
    assert sampler_projection["scene_sources"]["procthor-objaverse-val"]["needed_count"] == 0
    assert sampler_projection["scene_sources"]["ithor"]["support_status"] == "rejected"
    result = payload["results"][0]
    assert result["grader_outputs"]["sampler_admission"]["status"] == "passed"
    assert result["grader_outputs"]["sampler_admission"]["scene_source"] == "procthor-10k-val"
    assert result["grader_outputs"]["sampler_admission"]["category_provenance"] == (
        "prepared_visual_label_manifest"
    )
    report_html = run.report_path.read_text()
    assert "Scene Sampler Projection" in report_html
    assert "Ready samples: 16 /" in report_html
    assert "remaining:\n    24" in report_html


def test_sampler_admission_rejects_heuristic_category_provenance(tmp_path: Path) -> None:
    sample = json.loads(
        (
            Path(__file__).resolve().parents[3]
            / "evals/household_world/samples/scene_sampler/procthor-10k-val_10_map_build.json"
        ).read_text(encoding="utf-8")
    )
    sample["sample_id"] = "scene_sampler.heuristic_rejected"
    sample["grader_config"]["sampler_admission"]["category_provenance"] = "room_area_fallback"
    sample_path = tmp_path / "heuristic_scene_sampler_sample.json"
    sample_path.write_text(json.dumps(sample), encoding="utf-8")
    suite_path = tmp_path / "heuristic_scene_sampler_suite.json"
    suite_path.write_text(
        json.dumps(
            {
                "schema": "roboclaws_eval_suite_v1",
                "suite_id": "household_world.scene_sampler_heuristic_rejected",
                "version": "2026-06-15",
                "capability": "household_world_scene_sampling",
                "sample_ids": [sample["sample_id"]],
                "sample_refs": [str(sample_path)],
                "required_graders": [
                    "artifacts",
                    "privacy",
                    "trajectory",
                    "sampler_admission",
                    "outcome",
                ],
                "thresholds": {"pass_at_1": 1.0},
            }
        ),
        encoding="utf-8",
    )

    def product_runner(**kwargs: Any) -> dict[str, Any]:
        run_dir = Path(kwargs["output_dir"])
        _write_product_artifacts(
            run_dir,
            completion_status="map_build_complete",
            generated_exploration_candidate_count=20,
        )
        return _run_result(
            run_dir,
            completion_status="map_build_complete",
            map_build=True,
        )

    run = run_eval_suite(
        str(suite_path),
        output_root=tmp_path,
        stamp="heuristic-rejected",
        product_runner=product_runner,
    )

    result = json.loads(run.results_path.read_text())["results"][0]
    assert result["status"] == "failed"
    assert result["failure_class"] == "map_actionability_failure"
    assert result["grader_outputs"]["sampler_admission"]["failures"] == [
        "untrusted_room_category_provenance"
    ]


def test_cleanup_consumer_fails_when_runtime_map_dependency_is_missing(tmp_path: Path) -> None:
    launched_samples: list[str] = []

    def product_runner(**kwargs: Any) -> dict[str, Any]:
        run_dir = Path(kwargs["output_dir"])
        sample_id = kwargs["run_metadata_overrides"]["eval_sample_id"]
        launched_samples.append(sample_id)
        if sample_id == "map_build.fixture_focused_seed7":
            raise RuntimeError("provider_config_failure: missing CODEX_API_KEY")
        if sample_id.startswith("open_ended."):
            _write_product_artifacts(
                run_dir,
                completion_status="success",
                include_goal_contract=True,
            )
            return _run_result(
                run_dir,
                completion_status="success",
                task_intent="open-ended",
                final_status="success",
                include_completion_claim=True,
            )
        if sample_id in {
            "cleanup.consumer_no_prior_seed7",
        }:
            _write_product_artifacts(run_dir, completion_status="success")
            return _run_result(run_dir, completion_status="success")
        raise AssertionError("fixture-prior consumer should not launch without a runtime map")

    run = run_eval_suite(
        "evals/household_world/suites/map_build_consumer.json",
        output_root=tmp_path,
        stamp="missing-map-prior",
        product_runner=product_runner,
    )

    results = json.loads(run.results_path.read_text())["results"]
    cleanup_result = next(
        result
        for result in results
        if result["identity"]["sample_id"] == "cleanup.consumer_fixture_focused_prior_seed7"
    )
    open_ended_result = next(
        result
        for result in results
        if result["identity"]["sample_id"]
        == ("open_ended.stable_anchor_fixture_focused_prior_seed7")
    )
    assert launched_samples == [
        "map_build.fixture_focused_seed7",
        "open_ended.stable_anchor_no_prior_seed7",
        "cleanup.consumer_no_prior_seed7",
    ]
    for result in (cleanup_result, open_ended_result):
        assert result["status"] == "blocked"
        assert result["failure_class"] == "model_or_provider_unavailable"
        assert result["grader_outputs"]["runner"]["error_type"] == "EvalDependencyError"
        assert result["grader_outputs"]["artifacts"]["missing_dependencies"] == [
            "runtime_map_prior_path"
        ]


def test_eval_dependency_resolver_propagates_blocked_source_sample() -> None:
    sample = load_eval_sample(
        Path(__file__).resolve().parents[3]
        / "evals/household_world/samples/cleanup/consumer_fixture_focused_prior_seed7.json"
    )

    dependencies = resolve_artifact_dependencies(
        sample,
        repetition_index=0,
        sample_artifacts={
            "map_build.fixture_focused_seed7": {
                "source_status": "blocked",
                "source_failure_class": "model_or_provider_unavailable",
            }
        },
    )
    failure = dependency_failure(dependencies)

    assert failure is not None
    assert failure["failure_class"] == "model_or_provider_unavailable"
    assert "source sample was blocked" in failure["message"]


def test_eval_runner_fails_before_launch_when_explicit_runtime_map_prior_is_missing(
    tmp_path: Path,
) -> None:
    sample = json.loads(
        (
            Path(__file__).resolve().parents[3]
            / "evals/household_world/samples/cleanup/smoke_seed7.json"
        ).read_text(encoding="utf-8")
    )
    sample["sample_id"] = "cleanup.explicit_missing_prior"
    sample["artifact_dependencies"] = {
        "runtime_map_prior": str(tmp_path / "missing-runtime-map-prior.json")
    }
    sample_path = tmp_path / "explicit_missing_prior_sample.json"
    sample_path.write_text(json.dumps(sample), encoding="utf-8")
    suite_path = tmp_path / "explicit_missing_prior_suite.json"
    suite_path.write_text(
        json.dumps(
            {
                "schema": "roboclaws_eval_suite_v1",
                "suite_id": "household_world.explicit_missing_prior",
                "version": "2026-06-19",
                "capability": "household_world_cleanup",
                "sample_ids": [sample["sample_id"]],
                "sample_refs": [str(sample_path)],
                "required_graders": ["artifacts"],
                "thresholds": {"pass_at_1": 1.0},
            }
        ),
        encoding="utf-8",
    )

    def product_runner(**_kwargs: Any) -> dict[str, Any]:
        raise AssertionError("product runner should not launch with missing runtime_map_prior")

    run = run_eval_suite(
        str(suite_path),
        output_root=tmp_path,
        stamp="explicit-missing-prior",
        product_runner=product_runner,
    )

    result = json.loads(run.results_path.read_text())["results"][0]
    assert result["status"] == "failed"
    assert result["failure_class"] == "artifact_missing"
    assert result["grader_outputs"]["runner"]["error_type"] == "EvalDependencyError"
    assert result["grader_outputs"]["runner"]["message"].startswith(
        "runtime_map_prior_path does not exist:"
    )
    assert (
        result["grader_outputs"]["artifacts"]["resolved_dependencies"]["runtime_map_prior_source"]
        == "explicit_path"
    )


def test_eval_dependency_resolver_preserves_empty_explicit_runtime_map_prior() -> None:
    sample = load_eval_sample(
        Path(__file__).resolve().parents[3]
        / "evals/household_world/samples/cleanup/smoke_seed7.json"
    )
    sample = sample.__class__.from_mapping(
        {
            **sample.to_dict(),
            "artifact_dependencies": {"runtime_map_prior": ""},
        }
    )

    dependencies = resolve_artifact_dependencies(
        sample,
        repetition_index=0,
        sample_artifacts={},
    )
    failure = dependency_failure(dependencies)

    assert dependencies == {
        "runtime_map_prior_path": "",
        "runtime_map_prior_source": "explicit_path",
    }
    assert failure is not None
    assert failure["message"] == "explicit runtime_map_prior path was empty"


@pytest.mark.parametrize("value", [None, True, 7, 1.5, ["prior.json"], {"path": "prior.json"}])
def test_eval_runner_rejects_invalid_explicit_runtime_map_prior_value(
    tmp_path: Path,
    value: object,
) -> None:
    result = _run_invalid_cleanup_sample(
        tmp_path,
        sample_id="cleanup.invalid_runtime_map_prior",
        stamp=f"invalid-runtime-map-prior-{type(value).__name__}",
        mutate=lambda sample: sample.__setitem__(
            "artifact_dependencies",
            {"runtime_map_prior": value},
        ),
        assertion_message="product runner should not launch with invalid runtime_map_prior",
    )

    assert result["status"] == "failed"
    assert result["failure_class"] == "artifact_missing"
    assert result["grader_outputs"]["runner"]["error_type"] == "ValueError"
    assert (
        "runtime_map_prior must be a string path" in result["grader_outputs"]["runner"]["message"]
    )


def test_eval_runner_rejects_empty_explicit_runtime_map_prior_launch_override(
    tmp_path: Path,
) -> None:
    result = _run_invalid_cleanup_sample(
        tmp_path,
        sample_id="cleanup.invalid_runtime_map_prior_override",
        stamp="invalid-runtime-map-prior-override-empty",
        mutate=lambda sample: sample.setdefault("launch_overrides", {}).__setitem__(
            "runtime_map_prior",
            "",
        ),
        assertion_message="product runner should not launch with empty runtime_map_prior",
    )

    assert result["status"] == "failed"
    assert result["failure_class"] == "artifact_missing"
    assert result["grader_outputs"]["runner"]["error_type"] == "EvalDependencyError"
    assert (
        result["grader_outputs"]["runner"]["message"] == "explicit runtime_map_prior path was empty"
    )


@pytest.mark.parametrize(
    ("container_key", "value"),
    [
        ("artifact_dependencies", True),
        ("artifact_dependencies", 7),
        ("artifact_dependencies", ["map_build.baseline_seed7"]),
        ("artifact_dependencies", {"sample_id": "map_build.baseline_seed7"}),
        ("launch_overrides", ""),
    ],
)
def test_eval_runner_rejects_invalid_runtime_map_prior_source_sample(
    tmp_path: Path,
    container_key: str,
    value: object,
) -> None:
    result = _run_invalid_cleanup_sample(
        tmp_path,
        sample_id="cleanup.invalid_runtime_map_prior_source",
        stamp=f"invalid-runtime-map-prior-source-{container_key}-{type(value).__name__}",
        mutate=lambda sample: sample.setdefault(container_key, {}).__setitem__(
            "runtime_map_prior_from_sample",
            value,
        ),
        assertion_message=(
            "product runner should not launch with invalid runtime_map_prior_from_sample"
        ),
    )

    assert result["status"] == "failed"
    assert result["failure_class"] == "artifact_missing"
    assert result["grader_outputs"]["runner"]["error_type"] == "ValueError"
    assert (
        "runtime_map_prior_from_sample must be a non-empty string"
        in result["grader_outputs"]["runner"]["message"]
    )


@pytest.mark.parametrize(
    ("case_name", "artifact_dependencies", "expected_error"),
    [
        (
            "runtime-map-prior",
            {"runtime_map_prior": ["prior.json"]},
            "runtime_map_prior must be a string path",
        ),
        (
            "runtime-map-prior-source",
            {"runtime_map_prior_from_sample": {"id": "map-build"}},
            "runtime_map_prior_from_sample must be a non-empty string",
        ),
    ],
)
def test_live_eval_rejects_invalid_runtime_map_dependency_before_launch(
    tmp_path: Path,
    case_name: str,
    artifact_dependencies: dict[str, object],
    expected_error: str,
) -> None:
    result = _run_invalid_cleanup_sample(
        tmp_path,
        sample_id=f"cleanup.live_invalid_{case_name.replace('-', '_')}",
        stamp=f"live-invalid-{case_name}",
        mutate=lambda sample: sample.update(
            {
                "allowed_agent_engines": ["openai-agents-sdk"],
                "provider_profiles": ["codex-router-responses"],
                "artifact_dependencies": artifact_dependencies,
            }
        ),
        assertion_message=f"live product runner should not launch with invalid {case_name}",
        agent_engine="openai-agents-sdk",
        provider_profile="codex-router-responses",
        live_execution="run",
    )

    assert result["status"] == "failed"
    assert result["failure_class"] == "artifact_missing"
    assert result["identity"]["agent_engine"] == "openai-agents-sdk"
    assert result["grader_outputs"]["runner"]["error_type"] == "ValueError"
    assert expected_error in result["grader_outputs"]["runner"]["message"]


def test_open_ended_eval_separates_claim_from_artifact_readiness(tmp_path: Path) -> None:
    def product_runner(**kwargs: Any) -> dict[str, Any]:
        run_dir = Path(kwargs["output_dir"])
        sample_id = kwargs["run_metadata_overrides"]["eval_sample_id"]
        if sample_id == "map_build.fixture_focused_seed7":
            _write_product_artifacts(run_dir, completion_status="map_build_complete")
            return _run_result(
                run_dir,
                completion_status="map_build_complete",
                map_build=True,
            )
        if sample_id.startswith("cleanup."):
            _write_product_artifacts(run_dir, completion_status="success")
            return _run_result(run_dir, completion_status="success")
        _write_product_artifacts(run_dir, completion_status="failed")
        return _run_result(run_dir, completion_status="failed", task_intent="open-ended")

    run = run_eval_suite(
        "evals/household_world/suites/map_build_consumer.json",
        output_root=tmp_path,
        stamp="open-ended-missing-claim",
        product_runner=product_runner,
    )

    results = json.loads(run.results_path.read_text())["results"]
    open_result = next(
        result
        for result in results
        if result["identity"]["sample_id"] == "open_ended.stable_anchor_no_prior_seed7"
    )
    assert open_result["status"] == "failed"
    assert open_result["failure_class"] == "agent_no_completion_claim"
    assert open_result["grader_outputs"]["open_ended"]["completion_claim_present"] is False
    assert open_result["grader_outputs"]["open_ended"]["artifact_readiness"] == "missing"


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


def _passing_product_runner(**kwargs: Any) -> dict[str, Any]:
    run_dir = Path(kwargs["output_dir"])
    _write_product_artifacts(run_dir, completion_status="success")
    return _run_result(run_dir, completion_status="success")


def _missing_artifact_product_runner(**kwargs: Any) -> dict[str, Any]:
    run_dir = Path(kwargs["output_dir"])
    _write_product_artifacts(run_dir, completion_status="success")
    (run_dir / "report.html").unlink()
    return _run_result(run_dir, completion_status="success")


def _blocked_product_runner(**kwargs: Any) -> dict[str, Any]:
    raise RuntimeError("requested MCP port is already accepting connections")


def _live_surface_kwargs(
    run_dir: Path,
    *,
    live_timeout_s: float | None = None,
    live_stall_timeout_s: float | None = None,
) -> dict[str, Any]:
    return {
        "output_dir": run_dir,
        "seed": 7,
        "task_prompt": "帮我收拾这个房间",
        "backend": "api_semantic_synthetic",
        "cleanup_profile": "smoke",
        "scene_source": "procthor-10k-val",
        "scene_index": 0,
        "agent_engine": "openai-agents-sdk",
        "provider_profile": "codex-router-responses",
        "model": None,
        "live_timeout_s": live_timeout_s,
        "live_stall_timeout_s": live_stall_timeout_s,
    }


def _run_invalid_cleanup_sample(
    tmp_path: Path,
    *,
    sample_id: str,
    stamp: str,
    mutate: Callable[[dict[str, Any]], None],
    assertion_message: str,
    **run_kwargs: Any,
) -> dict[str, Any]:
    sample = json.loads(
        (
            Path(__file__).resolve().parents[3]
            / "evals"
            / "household_world"
            / "samples"
            / "cleanup"
            / "smoke_seed7.json"
        ).read_text(encoding="utf-8")
    )
    sample["sample_id"] = sample_id
    mutate(sample)
    path_token = sample_id.replace(".", "_")
    sample_path = tmp_path / f"{path_token}_sample.json"
    sample_path.write_text(json.dumps(sample), encoding="utf-8")
    suite_path = tmp_path / f"{path_token}_suite.json"
    suite_path.write_text(
        json.dumps(
            {
                "schema": "roboclaws_eval_suite_v1",
                "suite_id": f"household_world.{path_token}",
                "version": "2026-06-20",
                "capability": "household_world_cleanup",
                "sample_ids": [sample_id],
                "sample_refs": [str(sample_path)],
                "required_graders": ["artifacts"],
                "thresholds": {"pass_at_1": 1.0},
            }
        ),
        encoding="utf-8",
    )

    def product_runner(**_kwargs: Any) -> dict[str, Any]:
        raise AssertionError(assertion_message)

    run = run_eval_suite(
        str(suite_path),
        output_root=tmp_path,
        stamp=stamp,
        product_runner=product_runner,
        live_product_runner=product_runner,
        **run_kwargs,
    )
    return json.loads(run.results_path.read_text())["results"][0]


def _completed_process(*, returncode: int, stdout: str = "", stderr: str = "") -> Any:
    return type(
        "Completed",
        (),
        {
            "returncode": returncode,
            "stdout": stdout,
            "stderr": stderr,
        },
    )()


def _patch_live_surface_popen(
    monkeypatch: pytest.MonkeyPatch,
    live_runtime: Any,
    fake_run: Callable[..., Any],
) -> None:
    class FakePopen:
        def __init__(
            self,
            command: list[str],
            *,
            stdout: Any = None,
            stderr: Any = None,
            **kwargs: Any,
        ) -> None:
            kwargs.pop("cwd", None)
            kwargs.pop("env", None)
            kwargs.pop("text", None)
            self.completed = fake_run(command, **kwargs)
            self.returncode = self.completed.returncode
            if stdout is not None:
                stdout.write(str(getattr(self.completed, "stdout", "") or ""))
            if stderr is not None:
                stderr.write(str(getattr(self.completed, "stderr", "") or ""))

        def poll(self) -> int:
            return self.returncode

        def terminate(self) -> None:
            return None

        def kill(self) -> None:
            return None

        def wait(self, timeout: float | None = None) -> int:
            return self.returncode

    monkeypatch.setattr(live_runtime.subprocess, "Popen", FakePopen)


def _write_product_artifacts(
    run_dir: Path,
    *,
    completion_status: str,
    include_goal_contract: bool = False,
    generated_exploration_candidate_count: int = 7,
    include_open_ended_public_evidence: bool = True,
) -> None:
    run_dir.mkdir(parents=True, exist_ok=True)
    (run_dir / "run_result.json").write_text("{}\n")
    (run_dir / "report.html").write_text("<html>report</html>\n")
    (run_dir / "agent_view.json").write_text("{}\n")
    public_anchors = [{"anchor_id": "anchor_fridge"}]
    generated_candidates = [
        {"waypoint_id": f"generated_exploration_{index:03d}"}
        for index in range(1, generated_exploration_candidate_count + 1)
    ]
    target_search_summary: dict[str, Any] = {}
    if include_open_ended_public_evidence:
        public_anchors.extend(
            [
                {
                    "anchor_id": "anchor_room_kitchen",
                    "anchor_type": "room_area",
                    "room_id": "kitchen",
                    "waypoint_id": "generated_exploration_003",
                    "evidence": {"visited": True},
                },
                {
                    "anchor_id": "anchor_room_living_area",
                    "anchor_type": "room_area",
                    "room_id": "living_area",
                    "waypoint_id": "room_6_inspection",
                    "evidence": {"visited": True},
                },
                {
                    "anchor_id": "anchor_fixture_006",
                    "anchor_type": "receptacle",
                    "category": "fridge",
                    "label": "fridge",
                    "room_id": "room_2",
                    "waypoint_id": "room_2_inspection",
                    "evidence": {"visited": True},
                },
            ]
        )
        public_anchors.extend(eval_runtime_map.quality_public_anchors())
        generated_candidates.extend(
            [
                {
                    "waypoint_id": "generated_exploration_003",
                    "room_id": "kitchen",
                    "visited": True,
                },
                {
                    "waypoint_id": "room_2_inspection",
                    "room_id": "room_2",
                    "visited": True,
                },
            ]
        )
        target_search_summary = {
            "viewpoint_budget": {
                "observed_waypoint_ids": [
                    "generated_exploration_003",
                    "room_6_inspection",
                ],
            },
            "inspection_observations": [
                {"room_id": "kitchen", "waypoint_id": "generated_exploration_003"},
                {"room_id": "room_2", "waypoint_id": "room_2_inspection"},
            ],
        }
    (run_dir / "runtime_metric_map.json").write_text(
        json.dumps(
            {
                "schema": "runtime_metric_map_v1",
                "public_semantic_anchors": public_anchors,
                "generated_exploration_candidates": generated_candidates,
                "observed_objects": eval_runtime_map.quality_observed_objects(),
                "target_candidates": eval_runtime_map.quality_target_candidates(),
                "target_search_summary": target_search_summary,
                "private_truth_included": False,
                "source_map_mutated": False,
            }
        )
        + "\n"
    )
    (run_dir / "private_evaluation.json").write_text("{}\n")
    (run_dir / "advisory_evaluation.json").write_text('{"authoritative": false}\n')
    if include_goal_contract:
        (run_dir / "goal_contract.json").write_text(
            json.dumps(
                {
                    "schema": "roboclaws_goal_contract_v1",
                    "surface": "household-world",
                    "intent": "open-ended",
                    "normalized_goal": "find something useful to drink",
                    "goal_scope": "agent-declared",
                }
            )
            + "\n"
        )
    (run_dir / "trace.jsonl").write_text(
        "\n".join(
            [
                '{"event": "request", "tool": "metric_map"}',
                '{"event": "response", "tool": "metric_map"}',
                (
                    '{"event": "request", "tool": "navigate_to_waypoint", '
                    '"request": {"waypoint_id": "room_6_inspection"}}'
                ),
                '{"event": "response", "tool": "done"}',
            ]
        )
        + "\n"
    )


def _write_molmospaces_map_build_artifacts(
    run_dir: Path,
    *,
    wrong_waypoint_category: str = "",
) -> None:
    fixtures = [
        ("CounterTop", "room_2"),
        ("DiningTable", "room_2"),
        ("Fridge", "room_2"),
        ("ShelvingUnit", "room_2"),
        ("DiningTable", "room_3"),
        ("Sofa", "room_3"),
        ("TVStand", "room_3"),
        ("DiningTable", "room_4"),
        ("TVStand", "room_4"),
        ("Sink", "room_5"),
        ("Bed", "room_6"),
        ("TVStand", "room_6"),
        ("Bed", "room_7"),
        ("Desk", "room_7"),
        ("Bed", "room_8"),
        ("Desk", "room_8"),
    ]
    public_anchors = [
        {
            "anchor_id": f"anchor_room_{index:03d}",
            "anchor_type": "room_area",
            "category": "room_area",
            "room_id": f"room_{index}",
            "waypoint_id": f"room_{index}_inspection",
            "source_observation_id": f"room_observation_{index:03d}",
        }
        for index in range(2, 9)
    ]
    for index, (category, room_id) in enumerate(fixtures, start=1):
        waypoint_id = f"{room_id}_inspection"
        if category.lower() == wrong_waypoint_category.lower():
            waypoint_id = "room_2_inspection"
        public_anchors.append(
            {
                "anchor_id": f"anchor_fixture_{index:03d}",
                "anchor_type": (
                    "receptacle" if category in {"Fridge", "Sink", "ShelvingUnit"} else "surface"
                ),
                "category": category,
                "label": category,
                "room_id": room_id,
                "waypoint_id": waypoint_id,
                "pose": {"x": float(index), "y": float(index), "yaw": 0.0},
                "pose_source": "inspection_waypoint",
                "pose_role": "best_view_pose",
                "localization_status": "viewpoint_only",
                "source_observation_id": f"world_label_fpv_{index:03d}",
                "evidence": {
                    "fixture_observation_id": f"world_label_fpv_{index:03d}",
                    "supporting_observed_object_ids": [],
                },
            }
        )
    generated = [
        {"waypoint_id": f"room_{index}_inspection", "room_id": f"room_{index}", "visited": True}
        for index in range(2, 9)
    ]
    runtime_map = {
        "schema": "runtime_metric_map_v1",
        "public_semantic_anchors": public_anchors,
        "generated_exploration_candidates": generated,
        "observed_objects": eval_runtime_map.quality_observed_objects(),
        "target_candidates": eval_runtime_map.quality_target_candidates()
        + [
            {
                "candidate_id": f"target_candidate_molmospaces_{index:03d}",
                "candidate_type": "public_semantic_anchor",
                "category": category,
                "waypoint_id": f"{room_id}_inspection",
                "localization_status": "viewpoint_only",
            }
            for index, (category, room_id) in enumerate(fixtures, start=1)
        ],
        "private_truth_included": False,
        "source_map_mutated": False,
    }
    (run_dir / "runtime_metric_map.json").write_text(json.dumps(runtime_map) + "\n")
    receptacles = {
        f"{category.lower()}_{index}_0_{room_id.removeprefix('room_')}": {
            "category": category,
            "room_area": room_id,
            "position": [float(index), float(index), 0.5],
        }
        for index, (category, room_id) in enumerate(fixtures, start=1)
    }
    (run_dir / "molmospaces_backend_state.json").write_text(
        json.dumps({"backend": "molmospaces_subprocess", "receptacles": receptacles}) + "\n"
    )


def _run_result(
    run_dir: Path,
    *,
    completion_status: str,
    map_build: bool = False,
    task_intent: str = "cleanup",
    final_status: str | None = None,
    include_completion_claim: bool = False,
    include_runtime_map: bool = True,
    wall_time_s: float | None = None,
    backend: str = "api_semantic_synthetic",
) -> dict[str, Any]:
    completion_claim = (
        {
            "schema": "roboclaws_agent_completion_claim_v1",
            "completion_summary": "direct runner declared task complete",
        }
        if include_completion_claim
        else {}
    )
    result = {
        "score": {
            "completion_status": completion_status,
            "mess_restoration_rate": 1.0,
            "disturbance_count": 0,
            "failed_or_noop_tool_count": 0,
        },
        "completion_status": completion_status,
        "cleanup_status": completion_status,
        "task_intent": task_intent,
        "backend": backend,
        "final_status": final_status or completion_status,
        "map_build_mode": map_build,
        "agent_completion_claim": completion_claim,
        "tool_event_counts": {
            "metric_map:request": 1,
            "metric_map:response": 1,
            "done:response": 1,
        },
        "artifacts": {
            "run_result": str(run_dir / "run_result.json"),
            "report": str(run_dir / "report.html"),
        },
        "runtime_metric_map": (
            json.loads((run_dir / "runtime_metric_map.json").read_text())
            if include_runtime_map and (run_dir / "runtime_metric_map.json").exists()
            else {}
        ),
        "advisory_evaluation": json.loads((run_dir / "advisory_evaluation.json").read_text()),
        "policy_uses_private_truth": False,
        "planner_uses_private_manifest": False,
        "agent_view": {},
    }
    if wall_time_s is not None:
        result["wall_time_s"] = wall_time_s
    return result
