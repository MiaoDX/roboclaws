from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from roboclaws.evals.runner import run_eval_suite
from tests.unit.evals.eval_runner_support import (
    _completed_process,
    _live_surface_kwargs,
    _patch_live_surface_popen,
    _run_invalid_cleanup_sample,
    _run_result,
    _write_molmospaces_map_build_artifacts,
    _write_product_artifacts,
)


def test_live_surface_product_requires_sdk_run_result_after_foreground_success(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    from roboclaws.evals import live_execution as live_exec

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

    _patch_live_surface_popen(monkeypatch, live_exec, fake_run)
    monkeypatch.setattr(live_exec.time, "sleep", fake_sleep)

    with pytest.raises(RuntimeError, match="live surface run finished without"):
        live_exec.run_live_surface_product(
            **_live_surface_kwargs(tmp_path / "trial-0000", live_timeout_s=5.0)
        )

    assert sleeps == []


def test_live_surface_product_fails_aloud_on_malformed_run_result(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    from roboclaws.evals import live_execution as live_exec

    def fake_run(command: list[str], **_kwargs: Any) -> Any:
        output_arg = next(item for item in command if item.startswith("output_dir="))
        run_dir = Path(output_arg.removeprefix("output_dir=")) / "seed-7"
        _write_product_artifacts(run_dir, completion_status="success")
        (run_dir / "run_result.json").write_text("{", encoding="utf-8")
        return _completed_process(returncode=0)

    _patch_live_surface_popen(monkeypatch, live_exec, fake_run)

    run = run_eval_suite(
        "cleanup_capability",
        output_root=tmp_path,
        stamp="live-malformed-run-result",
        agent_engine="openai-agents-sdk",
        provider_profile="kimi-openai-chat",
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
                "provider_profiles": ["kimi-openai-chat"],
                "artifact_dependencies": artifact_dependencies,
            }
        ),
        assertion_message=f"live product runner should not launch with invalid {case_name}",
        agent_engine="openai-agents-sdk",
        provider_profile="kimi-openai-chat",
        live_execution="run",
    )

    assert result["status"] == "failed"
    assert result["failure_class"] == "artifact_missing"
    assert result["identity"]["agent_engine"] == "openai-agents-sdk"
    assert result["grader_outputs"]["runner"]["error_type"] == "ValueError"
    assert expected_error in result["grader_outputs"]["runner"]["message"]
