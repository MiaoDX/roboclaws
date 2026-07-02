from __future__ import annotations

import json
from pathlib import Path

import pytest

from roboclaws.evals.models import (
    EVAL_RESULT_SCHEMA,
    EVAL_SAMPLE_SCHEMA,
    EVAL_SUITE_SCHEMA,
    EVAL_TRIAL_SCHEMA,
    FAILURE_CLASSES,
    MISSING_NOT_APPLICABLE,
    MISSING_UNAVAILABLE,
    EvalResult,
    EvalSample,
    EvalSuite,
    EvalTrial,
    load_eval_sample,
    load_eval_suite,
)

REPO_ROOT = Path(__file__).resolve().parents[3]
SMOKE_SUITE = REPO_ROOT / "evals" / "household_world" / "suites" / "smoke_regression.json"
MAP_BUILD_SUITE = REPO_ROOT / "evals" / "household_world" / "suites" / "map_build_consumer.json"
CLEANUP_SUITE = REPO_ROOT / "evals" / "household_world" / "suites" / "cleanup_capability.json"
OPEN_ENDED_SUITE = REPO_ROOT / "evals" / "household_world" / "suites" / "open_ended_goals.json"
SCENE_SAMPLER_SUITE = (
    REPO_ROOT / "evals" / "household_world" / "suites" / "scene_sampler_stress.json"
)
LONG_HORIZON_SUITE = REPO_ROOT / "evals" / "household_world" / "suites" / "long_horizon_tasks.json"
EVAL_FILE_LOADERS = [(load_eval_suite, "suite.json"), (load_eval_sample, "sample.json")]


def test_direct_runner_eval_sample_and_result_round_trip(tmp_path: Path) -> None:
    suite = EvalSuite.from_mapping(
        {
            "schema": EVAL_SUITE_SCHEMA,
            "suite_id": "household_world.smoke_regression",
            "version": "2026-06-15",
            "capability": "household_world",
            "sample_ids": ["cleanup.smoke_seed7"],
            "required_graders": ["artifacts", "privacy", "trajectory"],
            "thresholds": {"pass_at_1": 1.0},
        }
    )
    sample = EvalSample.from_mapping(
        {
            "schema": EVAL_SAMPLE_SCHEMA,
            "sample_id": "cleanup.smoke_seed7",
            "version": "2026-06-15",
            "surface": "household-world",
            "intent": "cleanup",
            "preset": "cleanup",
            "world": "molmospaces/val_0",
            "backend": "mujoco",
            "evidence_lane": "world-public-labels",
            "camera_labeler": MISSING_NOT_APPLICABLE,
            "scenario_setup": "relocate-cleanup-related-objects",
            "seed": 7,
            "prompt": MISSING_NOT_APPLICABLE,
            "goal_contract_hash": MISSING_UNAVAILABLE,
            "allowed_agent_engines": ["direct-runner"],
            "trial_count": 1,
            "required_graders": ["artifacts", "privacy", "trajectory"],
            "private_goal_reference": {
                "schema": "household_eval_private_goal_reference_v1",
                "scorer_input": "private",
            },
        }
    )
    trial = EvalTrial.from_sample(
        sample,
        suite=suite,
        trial_id="trial-cleanup-smoke-seed7-0001",
        repetition_index=0,
        agent_engine="direct-runner",
        runner_class="direct_runner",
        provider_profile=MISSING_NOT_APPLICABLE,
        model=MISSING_NOT_APPLICABLE,
        skill_name="molmo-realworld-cleanup",
        prompt_source=MISSING_NOT_APPLICABLE,
        mcp_profile="household_world+household_manipulation",
        tool_surface=["metric_map", "observe", "done"],
        budgets={"steps": 50, "time_s": 120, "token": MISSING_NOT_APPLICABLE},
        runtime={"host": MISSING_UNAVAILABLE, "network": MISSING_UNAVAILABLE},
        limitations=["simulator_not_executed_in_schema_slice"],
    )

    assert EvalSuite.from_mapping(suite.to_dict()) == suite
    assert EvalSample.from_mapping(sample.to_dict()) == sample
    assert EvalTrial.from_mapping(trial.to_dict()) == trial

    result = EvalResult.from_trial(
        trial,
        status="passed",
        failure_class=MISSING_NOT_APPLICABLE,
        grader_outputs={
            "artifacts": {"status": "passed", "required_artifacts": ["run_result.json"]},
            "privacy": {"status": "passed", "private_truth_leak_count": 0},
        },
        artifacts={
            "run_result": "runs/cleanup-smoke-seed7/run_result.json",
            "report": "runs/cleanup-smoke-seed7/report.html",
        },
        artifact_schema_versions={"run_result": MISSING_UNAVAILABLE},
        metrics={"pass": 1.0, "private_truth_leak_count": 0},
    )

    result_path = tmp_path / "eval_result.json"
    result_path.write_text(json.dumps(result.to_dict(), indent=2, sort_keys=True) + "\n")

    loaded = EvalResult.from_mapping(json.loads(result_path.read_text()))
    assert loaded == result
    payload = loaded.to_dict()
    assert payload["schema"] == EVAL_RESULT_SCHEMA
    assert trial.to_dict()["schema"] == EVAL_TRIAL_SCHEMA
    assert payload["identity"]["suite_id"] == suite.suite_id
    assert payload["identity"]["sample_id"] == sample.sample_id
    assert payload["identity"]["trial_id"] == trial.trial_id
    assert payload["identity"]["provider_profile"] == MISSING_NOT_APPLICABLE
    assert payload["identity"]["model"] == MISSING_NOT_APPLICABLE
    assert payload["identity"]["runtime"]["host"] == MISSING_UNAVAILABLE
    assert payload["identity"]["budgets"]["cost"] == MISSING_UNAVAILABLE
    assert payload["artifact_schema_versions"]["report"] == MISSING_UNAVAILABLE


def test_eval_result_requires_known_failure_class_for_failed_trials() -> None:
    sample = EvalSample.from_mapping(_minimal_sample_payload())
    suite = EvalSuite.from_mapping(_minimal_suite_payload(sample.sample_id))
    trial = EvalTrial.from_sample(
        sample,
        suite=suite,
        trial_id="trial-1",
        repetition_index=0,
        agent_engine="direct-runner",
        runner_class="direct_runner",
    )

    result = EvalResult.from_trial(
        trial,
        status="failed",
        failure_class="private_truth_leak",
        grader_outputs={"privacy": {"status": "failed"}},
    )

    assert result.failure_class == "private_truth_leak"
    assert result.identity["budgets"]["steps"] == MISSING_UNAVAILABLE
    assert result.identity["runtime"]["network"] == MISSING_UNAVAILABLE
    assert "private_truth_leak" in FAILURE_CLASSES
    with pytest.raises(ValueError, match="unknown failure_class"):
        EvalResult.from_trial(
            trial,
            status="failed",
            failure_class="vague_agent_failure",
            grader_outputs={},
        )
    with pytest.raises(ValueError, match="failed eval_result requires failure_class"):
        EvalResult.from_trial(
            trial,
            status="failed",
            failure_class=MISSING_NOT_APPLICABLE,
            grader_outputs={},
        )


def test_eval_result_from_mapping_validates_status_and_normalizes_artifact_schemas() -> None:
    sample = EvalSample.from_mapping(_minimal_sample_payload())
    suite = EvalSuite.from_mapping(_minimal_suite_payload(sample.sample_id))
    trial = EvalTrial.from_sample(
        sample,
        suite=suite,
        trial_id="trial-1",
        repetition_index=0,
        agent_engine="direct-runner",
        runner_class="direct_runner",
    )
    payload = EvalResult.from_trial(
        trial,
        status="passed",
        failure_class=MISSING_NOT_APPLICABLE,
        grader_outputs={"artifacts": {"status": "passed"}},
        artifacts={"report": "runs/trial-1/report.html"},
    ).to_dict()
    payload["artifact_schema_versions"] = {}

    loaded = EvalResult.from_mapping(payload)

    assert loaded.artifact_schema_versions["report"] == MISSING_UNAVAILABLE
    payload["status"] = "success"
    with pytest.raises(ValueError, match="unknown eval_result status"):
        EvalResult.from_mapping(payload)


def test_eval_identity_uses_explicit_tool_surface_sentinel() -> None:
    sample = EvalSample.from_mapping(_minimal_sample_payload())
    suite = EvalSuite.from_mapping(_minimal_suite_payload(sample.sample_id))
    trial = EvalTrial.from_sample(
        sample,
        suite=suite,
        trial_id="trial-1",
        repetition_index=0,
        agent_engine="direct-runner",
        runner_class="direct_runner",
    )

    assert trial.tool_surface == (MISSING_UNAVAILABLE,)

    payload = trial.to_dict()
    payload["tool_surface"] = []
    with pytest.raises(ValueError, match="tool_surface must not be empty"):
        EvalTrial.from_mapping(payload)


def test_eval_trial_from_sample_rejects_disallowed_agent_engine() -> None:
    sample = EvalSample.from_mapping(_minimal_sample_payload())
    suite = EvalSuite.from_mapping(_minimal_suite_payload(sample.sample_id))

    with pytest.raises(ValueError, match="is not allowed for sample"):
        EvalTrial.from_sample(
            sample,
            suite=suite,
            trial_id="trial-1",
            repetition_index=0,
            agent_engine="codex-cli",
            runner_class="direct_runner",
        )


def test_eval_sample_requires_explicit_missing_identity_fields() -> None:
    payload = _minimal_sample_payload()
    payload.pop("goal_contract_hash")

    with pytest.raises(ValueError, match="goal_contract_hash"):
        EvalSample.from_mapping(payload)

    payload["goal_contract_hash"] = MISSING_UNAVAILABLE
    sample = EvalSample.from_mapping(payload)
    assert sample.goal_contract_hash == MISSING_UNAVAILABLE


def test_eval_sample_rejects_non_string_identity_values() -> None:
    payload = _minimal_sample_payload()
    payload["prompt"] = 123

    with pytest.raises(ValueError, match="prompt must be a non-empty string"):
        EvalSample.from_mapping(payload)

    payload = _minimal_sample_payload()
    payload["provider_profiles"] = ["not_applicable", 3]
    with pytest.raises(ValueError, match="provider_profiles must be a list of non-empty strings"):
        EvalSample.from_mapping(payload)


@pytest.mark.parametrize("loader, filename", EVAL_FILE_LOADERS)
def test_eval_file_sources_fail_when_missing(tmp_path: Path, loader, filename: str) -> None:
    path = tmp_path / filename

    with pytest.raises(FileNotFoundError, match=rf"eval JSON source is missing: .*{filename}"):
        loader(path)


@pytest.mark.parametrize("loader, filename", EVAL_FILE_LOADERS)
def test_eval_file_sources_reject_malformed_json(tmp_path: Path, loader, filename: str) -> None:
    path = tmp_path / filename
    path.write_text("{not-json\n", encoding="utf-8")

    with pytest.raises(
        ValueError,
        match=rf"eval JSON source must contain valid JSON object: .*{filename}",
    ):
        loader(path)


@pytest.mark.parametrize("loader, filename", EVAL_FILE_LOADERS)
def test_eval_file_sources_reject_non_object_json(tmp_path: Path, loader, filename: str) -> None:
    path = tmp_path / filename
    path.write_text("[]\n", encoding="utf-8")

    with pytest.raises(
        ValueError,
        match=rf"eval JSON source must contain a JSON object: .*{filename}",
    ):
        loader(path)


def test_direct_runner_fixture_suite_loads_sample_contract() -> None:
    suite = load_eval_suite(SMOKE_SUITE)
    sample = load_eval_sample(REPO_ROOT / suite.sample_refs[0])

    assert suite.schema == EVAL_SUITE_SCHEMA
    assert suite.suite_id == "household_world.smoke_regression"
    assert suite.sample_ids == ("cleanup.smoke_seed7",)
    assert suite.sample_refs == ("evals/household_world/samples/cleanup/smoke_seed7.json",)
    assert sample.schema == EVAL_SAMPLE_SCHEMA
    assert sample.sample_id == "cleanup.smoke_seed7"
    assert sample.allowed_agent_engines == ("direct-runner",)
    assert sample.provider_profiles == (MISSING_NOT_APPLICABLE,)
    assert sample.goal_contract_hash == MISSING_UNAVAILABLE
    assert "artifacts" in sample.required_graders


def test_all_household_world_sample_fixtures_are_schema_valid() -> None:
    sample_paths = sorted((REPO_ROOT / "evals" / "household_world" / "samples").glob("*/*.json"))

    assert sample_paths
    suites = [
        load_eval_suite(SMOKE_SUITE),
        load_eval_suite(MAP_BUILD_SUITE),
        load_eval_suite(CLEANUP_SUITE),
        load_eval_suite(OPEN_ENDED_SUITE),
        load_eval_suite(SCENE_SAMPLER_SUITE),
        load_eval_suite(LONG_HORIZON_SUITE),
    ]
    loaded = [load_eval_sample(path) for path in sample_paths]
    assert {sample.sample_id for sample in loaded} == {
        "cleanup.consume_map_seed7",
        "cleanup.consumer_fixture_focused_prior_seed7",
        "cleanup.consumer_no_prior_seed7",
        "cleanup.repeated_seed7",
        "cleanup.smoke_seed7",
        "map_build.baseline_seed7",
        "map_build.fixture_focused_seed7",
        "open_ended.drink_seed7",
        "open_ended.living_waypoint_seed7",
        "open_ended.room4_anchor_seed7",
        "open_ended.stable_anchor_fixture_focused_prior_seed7",
        "open_ended.stable_anchor_no_prior_seed7",
        "long_horizon.snack_restock_val0_seed7",
        "long_horizon.food_restock_chinese_val0_seed7",
        "scene_sampler.procthor-10k-val.0.map_build",
        "scene_sampler.procthor-10k-val.10.map_build",
        "scene_sampler.procthor-10k-val.11.map_build",
        "scene_sampler.procthor-10k-val.12.map_build",
        "scene_sampler.procthor-10k-val.13.map_build",
        "scene_sampler.procthor-10k-val.15.map_build",
        "scene_sampler.procthor-objaverse-val.0.map_build",
        "scene_sampler.procthor-objaverse-val.1.map_build",
        "scene_sampler.procthor-objaverse-val.4.map_build",
        "scene_sampler.procthor-objaverse-val.5.map_build",
        "scene_sampler.procthor-objaverse-val.7.map_build",
        "scene_sampler.procthor-objaverse-val.10.map_build",
        "scene_sampler.procthor-objaverse-val.11.map_build",
        "scene_sampler.procthor-objaverse-val.12.map_build",
        "scene_sampler.procthor-objaverse-val.13.map_build",
        "scene_sampler.procthor-objaverse-val.14.map_build",
    }
    suite_sample_ids = {sample_id for suite in suites for sample_id in suite.sample_ids}
    standalone_sample_ids = {
        "cleanup.consume_map_seed7",
        "map_build.baseline_seed7",
    }
    assert {sample.sample_id for sample in loaded} <= suite_sample_ids | standalone_sample_ids

    map_build_sample = next(
        sample for sample in loaded if sample.sample_id == "map_build.baseline_seed7"
    )
    assert map_build_sample.evidence_lane == "camera-grounded-labels"
    assert map_build_sample.camera_labeler == "grounding-dino"
    assert map_build_sample.allowed_agent_engines == ("direct-runner", "openai-agents-sdk")
    assert map_build_sample.provider_profiles == (
        MISSING_NOT_APPLICABLE,
        "codex-router-responses",
        "minimax-responses",
    )

    map_build_consumer_suite = suites[1]
    assert map_build_consumer_suite.suite_id == "household_world.map_build_consumer"
    assert map_build_consumer_suite.sample_ids == (
        "map_build.fixture_focused_seed7",
        "open_ended.stable_anchor_no_prior_seed7",
        "open_ended.stable_anchor_fixture_focused_prior_seed7",
        "cleanup.consumer_no_prior_seed7",
        "cleanup.consumer_fixture_focused_prior_seed7",
    )
    assert map_build_consumer_suite.metadata["comparison_variants"] == [
        "no_prior",
        "fixture_focused_prior",
    ]
    assert map_build_consumer_suite.metadata["model_matrix_provider_profiles"] == [
        "codex-router-responses",
        "mimo-inside-openai-chat",
        "kimi-openai-chat",
        "minimax-responses",
    ]

    fixture_map_build_sample = next(
        sample for sample in loaded if sample.sample_id == "map_build.fixture_focused_seed7"
    )
    assert "map_build_scan_profile" not in fixture_map_build_sample.launch_overrides
    assert fixture_map_build_sample.provider_profiles == (
        MISSING_NOT_APPLICABLE,
        "codex-router-responses",
        "mimo-inside-openai-chat",
        "kimi-openai-chat",
        "minimax-responses",
    )

    open_ended_suite = suites[3]
    assert open_ended_suite.suite_id == "household_world.open_ended_goals"
    assert open_ended_suite.sample_ids == (
        "open_ended.drink_seed7",
        "open_ended.room4_anchor_seed7",
        "open_ended.living_waypoint_seed7",
    )
    open_ended_samples = {
        sample.sample_id: sample for sample in loaded if sample.sample_id.startswith("open_ended.")
    }
    open_ended_sample = open_ended_samples["open_ended.drink_seed7"]
    room_sample = open_ended_samples["open_ended.room4_anchor_seed7"]
    living_sample = open_ended_samples["open_ended.living_waypoint_seed7"]
    assert open_ended_sample.preset == MISSING_NOT_APPLICABLE
    assert open_ended_sample.allowed_agent_engines == (
        "direct-runner",
        "codex-cli",
        "openai-agents-sdk",
    )
    assert open_ended_sample.provider_profiles == (
        MISSING_NOT_APPLICABLE,
        "codex-router-responses",
        "minimax-responses",
    )
    assert open_ended_sample.grader_config["semantic_satisfaction_authoritative"] is False
    assert open_ended_sample.grader_config["open_ended_category"] == "negative_search"
    assert room_sample.grader_config["open_ended_category"] == "area_inspection"
    assert room_sample.grader_config["success_predicate"] == {
        "predicate_id": "waypoint_or_area_visited",
        "authoritative": True,
        "anchor_id": "anchor_waypoint_room_6_inspection",
        "waypoint_id": "room_6_inspection",
    }
    assert living_sample.grader_config["open_ended_category"] == "positive_observable"
    assert living_sample.grader_config["success_predicate"] == {
        "predicate_id": "waypoint_or_area_visited",
        "authoritative": True,
        "anchor_id": "anchor_waypoint_room_6_inspection",
        "waypoint_id": "room_6_inspection",
    }

    scene_suite = next(
        suite for suite in suites if suite.suite_id == "household_world.scene_sampler_stress"
    )
    assert scene_suite.suite_id == "household_world.scene_sampler_stress"
    assert "sampler_admission" in scene_suite.required_graders
    projection = scene_suite.metadata["sampler_projection"]
    assert projection["summary"]["ready_sample_count"] == 16
    assert projection["summary"]["partial_source_count"] == 1
    assert projection["summary"]["blocked_source_count"] == 0
    assert projection["summary"]["rejected_source_count"] == 2
    assert projection["scene_sources"]["procthor-10k-val"]["ready_count"] == 6
    assert projection["scene_sources"]["procthor-10k-val"]["target_count"] == 10
    assert projection["scene_sources"]["procthor-10k-val"]["support_status"] == "partial"
    assert projection["scene_sources"]["procthor-10k-val"]["partial_gap_count"] == 4
    assert projection["scene_sources"]["procthor-objaverse-val"]["ready_count"] == 10
    assert projection["scene_sources"]["procthor-objaverse-val"]["target_count"] == 10
    assert projection["scene_sources"]["procthor-objaverse-val"]["support_status"] == "complete"
    assert projection["scene_sources"]["procthor-objaverse-val"]["partial_gap_count"] == 0
    assert projection["scene_sources"]["ithor"]["blocked_rows"][0]["failure_class"] == (
        "map_actionability_failure"
    )
    assert projection["scene_sources"]["ithor"]["support_status"] == "rejected"


def _minimal_suite_payload(sample_id: str) -> dict:
    return {
        "schema": EVAL_SUITE_SCHEMA,
        "suite_id": "household_world.smoke_regression",
        "version": "2026-06-15",
        "capability": "household_world",
        "sample_ids": [sample_id],
        "required_graders": ["artifacts"],
        "thresholds": {"pass_at_1": 1.0},
    }


def _minimal_sample_payload() -> dict:
    return {
        "schema": EVAL_SAMPLE_SCHEMA,
        "sample_id": "cleanup.smoke_seed7",
        "version": "2026-06-15",
        "surface": "household-world",
        "intent": "cleanup",
        "preset": "cleanup",
        "world": "molmospaces/val_0",
        "backend": "mujoco",
        "evidence_lane": "world-public-labels",
        "camera_labeler": MISSING_NOT_APPLICABLE,
        "scenario_setup": "relocate-cleanup-related-objects",
        "seed": 7,
        "prompt": MISSING_NOT_APPLICABLE,
        "goal_contract_hash": MISSING_UNAVAILABLE,
        "allowed_agent_engines": ["direct-runner"],
        "trial_count": 1,
        "required_graders": ["artifacts"],
        "private_goal_reference": {
            "schema": "household_eval_private_goal_reference_v1",
            "scorer_input": "private",
        },
    }
