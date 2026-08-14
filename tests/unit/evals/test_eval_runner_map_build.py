from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from roboclaws.evals.dependencies import dependency_failure, resolve_artifact_dependencies
from roboclaws.evals.models import load_eval_sample
from roboclaws.evals.runner import run_eval_suite
from tests.unit.evals.eval_runner_support import (
    _passing_product_runner,
    _run_invalid_cleanup_sample,
    _run_result,
    _write_molmospaces_map_build_artifacts,
    _write_product_artifacts,
)


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


def test_no_prior_control_suite_never_launches_map_build(tmp_path: Path) -> None:
    seen_intents: list[str] = []

    def product_runner(**kwargs: Any) -> dict[str, Any]:
        run_dir = Path(kwargs["output_dir"])
        seen_intents.append(str(kwargs["intent"]))
        if kwargs["intent"] == "open-ended":
            _write_product_artifacts(
                run_dir, completion_status="success", include_goal_contract=True
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

    run_eval_suite(
        "map_consumer_no_prior",
        output_root=tmp_path,
        stamp="no-prior",
        product_runner=product_runner,
    )

    assert seen_intents == ["open-ended", "cleanup"]


def test_fixed_prior_suite_reuses_one_digest_without_map_build(tmp_path: Path) -> None:
    prior = tmp_path / "runtime_map_prior_snapshot.json"
    prior.write_text('{"schema":"runtime_map_prior_snapshot_v1"}\n', encoding="utf-8")
    seen: list[tuple[str, str]] = []

    def product_runner(**kwargs: Any) -> dict[str, Any]:
        run_dir = Path(kwargs["output_dir"])
        seen.append((str(kwargs["intent"]), str(kwargs["runtime_map_prior_path"])))
        if kwargs["intent"] == "open-ended":
            _write_product_artifacts(
                run_dir, completion_status="success", include_goal_contract=True
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
        "map_consumer_fixed_prior",
        output_root=tmp_path,
        stamp="fixed",
        runtime_map_prior=prior,
        product_runner=product_runner,
    )

    assert seen == [("open-ended", str(prior)), ("cleanup", str(prior))]
    payload = json.loads(run.results_path.read_text())
    dependencies = [
        result["grader_outputs"]["artifacts"]["resolved_dependencies"]
        for result in payload["results"]
    ]
    assert len({item["runtime_map_prior_sha256"] for item in dependencies}) == 1
    assert {item["runtime_map_prior_source"] for item in dependencies} == {"suite_override"}


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
            raise RuntimeError("provider_config_failure: missing KIMI_API_KEY")
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
