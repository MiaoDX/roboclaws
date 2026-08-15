from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

import pytest

from roboclaws.evals.models import load_eval_sample
from roboclaws.evals.runner import run_eval_suite
from tests.unit.evals.eval_runner_support import (
    _completed_process,
    _live_surface_kwargs,
    _patch_live_surface_popen,
    _run_result,
    _write_product_artifacts,
)


def test_eval_runner_regrades_existing_live_artifacts_without_provider_call(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
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
        provider_profile="kimi-openai-chat",
        model="kimi-k2.7-code",
        live_execution="run",
        skill_name="source-skill",
        skill_delivery_cell="dynamic-routed",
        live_product_runner=live_product_runner,
    )

    def forbidden_live_product_runner(**_kwargs: Any) -> dict[str, Any]:
        raise AssertionError("regrade_source must not call the live provider route")

    def forbidden_model_resolution(**_kwargs: Any) -> str:
        raise AssertionError("regrade_source must not resolve the current model default")

    monkeypatch.setattr(
        "roboclaws.evals.runner.eval_model_identity",
        forbidden_model_resolution,
    )

    regrade = run_eval_suite(
        "cleanup_capability",
        output_root=tmp_path,
        stamp="live-source-regrade",
        agent_engine="openai-agents-sdk",
        provider_profile="kimi-openai-chat",
        regrade_source=source_run.output_dir,
        live_product_runner=forbidden_live_product_runner,
    )

    payload = json.loads(regrade.results_path.read_text())
    assert payload["aggregate"]["passed"] == 3
    result = payload["results"][0]
    source_identity = source_run.bundle["results"][0]["identity"]
    assert result["status"] == "passed"
    assert "live_eval_regraded_from_existing_artifacts" in result["limitations"]
    for field in (
        "agent_engine",
        "runner_class",
        "provider_profile",
        "model",
        "skill_name",
        "tool_surface",
        "budgets",
        "runtime",
    ):
        assert result["identity"][field] == source_identity[field]
    assert result["artifacts"]["run_result"].endswith(
        "live-source/runs/cleanup_repeated_seed7/trial-0000/surface-run/seed-7/run_result.json"
    )


@pytest.mark.parametrize(
    ("override", "message"),
    (
        ({"provider_profile": "codex-responses"}, "provider_profile"),
        ({"skill_name": "other-skill"}, "skill_name"),
        ({"skill_delivery_cell": "no-skill"}, "skill_delivery_cell"),
    ),
)
def test_eval_runner_rejects_regrade_execution_identity_override(
    tmp_path: Path,
    override: dict[str, str],
    message: str,
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
        stamp=f"identity-source-{message}",
        agent_engine="openai-agents-sdk",
        provider_profile="kimi-openai-chat",
        live_execution="run",
        skill_name="source-skill",
        skill_delivery_cell="dynamic-routed",
        live_product_runner=live_product_runner,
    )

    with pytest.raises(ValueError, match=message):
        run_eval_suite(
            "cleanup_capability",
            output_root=tmp_path,
            stamp=f"identity-regrade-{message}",
            agent_engine="openai-agents-sdk",
            regrade_source=source_run.output_dir,
            **override,
        )


def test_eval_runner_rejects_regrade_model_override(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
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
        stamp="model-source",
        agent_engine="openai-agents-sdk",
        provider_profile="kimi-openai-chat",
        live_execution="run",
        live_product_runner=live_product_runner,
    )
    monkeypatch.setattr(
        "roboclaws.evals.runner.eval_model_identity",
        lambda **_kwargs: "different-public-model",
    )

    with pytest.raises(ValueError, match="model does not match source execution identity"):
        run_eval_suite(
            "cleanup_capability",
            output_root=tmp_path,
            stamp="model-regrade",
            agent_engine="openai-agents-sdk",
            model="requested-model",
            regrade_source=source_run.output_dir,
        )


def test_eval_runner_rejects_regrade_source_suite_version_mismatch(tmp_path: Path) -> None:
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
        stamp="suite-version-source",
        agent_engine="openai-agents-sdk",
        provider_profile="kimi-openai-chat",
        live_execution="run",
        live_product_runner=live_product_runner,
    )
    source_payload = json.loads(source_run.results_path.read_text(encoding="utf-8"))
    source_payload["suite"]["version"] = "stale-suite-release"
    source_run.results_path.write_text(json.dumps(source_payload), encoding="utf-8")

    with pytest.raises(ValueError, match="exact suite release"):
        run_eval_suite(
            "cleanup_capability",
            output_root=tmp_path,
            stamp="suite-version-regrade",
            agent_engine="openai-agents-sdk",
            regrade_source=source_run.output_dir,
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
        provider_profile="kimi-openai-chat",
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
        provider_profile="kimi-openai-chat",
        live_execution="run",
        live_product_runner=live_product_runner,
    )

    payload = json.loads(run.results_path.read_text())
    assert payload["aggregate"]["failed"] == 3
    assert payload["aggregate"]["failure_classes"] == {"artifact_missing": 3}
    runner = payload["results"][0]["grader_outputs"]["runner"]
    assert runner["error_type"] == "ValueError"
    assert "eval_effective_run_dir must stay under trial run_dir" in runner["message"]


def test_live_surface_product_discovers_timestamped_run_dir(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    import roboclaws.evals.live_execution as live_exec

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

    _patch_live_surface_popen(monkeypatch, live_exec, fake_run)

    result = live_exec.run_live_surface_product(**_live_surface_kwargs(tmp_path / "trial-0000"))

    assert command_log
    assert result["eval_effective_run_dir"].endswith("surface-run/0615_0305/seed-7")
    assert (tmp_path / "trial-0000" / "live_eval_command.json").exists()


def test_live_surface_product_rejects_stale_sibling_run_artifacts(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    import roboclaws.evals.live_execution as live_exec

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

    _patch_live_surface_popen(monkeypatch, live_exec, fake_run)
    kwargs = _live_surface_kwargs(trial_dir, live_timeout_s=1.0)
    kwargs["agent_engine"] = "openai-agents-sdk"

    with pytest.raises(RuntimeError, match="stale live surface run artifacts"):
        live_exec.run_live_surface_product(**kwargs)


def test_live_surface_product_rejects_mixed_fresh_and_stale_artifacts(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    import roboclaws.evals.live_execution as live_exec

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

    _patch_live_surface_popen(monkeypatch, live_exec, fake_run)
    kwargs = _live_surface_kwargs(trial_dir, live_timeout_s=1.0)
    kwargs["agent_engine"] = "openai-agents-sdk"

    with pytest.raises(RuntimeError, match="stale live surface run artifacts"):
        live_exec.run_live_surface_product(**kwargs)


def test_live_surface_product_rejects_stdout_artifacts_path_outside_surface_root(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    import roboclaws.evals.live_execution as live_exec

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

    _patch_live_surface_popen(monkeypatch, live_exec, fake_run)
    kwargs = _live_surface_kwargs(trial_dir, live_timeout_s=1.0)
    kwargs["agent_engine"] = "openai-agents-sdk"

    with pytest.raises(RuntimeError, match="stdout live surface artifacts path must stay under"):
        live_exec.run_live_surface_product(**kwargs)


def test_live_surface_product_rejects_stdout_artifacts_path_without_seed_leaf(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    import roboclaws.evals.live_execution as live_exec

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

    _patch_live_surface_popen(monkeypatch, live_exec, fake_run)
    kwargs = _live_surface_kwargs(trial_dir, live_timeout_s=1.0)
    kwargs["agent_engine"] = "openai-agents-sdk"

    with pytest.raises(
        RuntimeError, match="stdout live surface artifacts path must end with seed-7"
    ):
        live_exec.run_live_surface_product(**kwargs)


def test_live_surface_discovery_fails_on_ambiguous_current_sibling_artifacts(
    tmp_path: Path,
) -> None:
    import roboclaws.evals.live_execution as live_exec

    output_dir = tmp_path / "surface-run"
    for stamp in ("0615_0305", "0615_0306"):
        _write_product_artifacts(
            output_dir / stamp / "seed-7",
            completion_status="success",
        )

    with pytest.raises(RuntimeError, match="ambiguous live surface run artifacts"):
        live_exec.discover_live_surface_run_dir(
            {"seed": 7},
            output_dir=output_dir,
            fallback_run_dir=output_dir / "seed-7",
            started_wall_time_s=0.0,
        )


def test_live_open_ended_eval_fails_after_checker_nonzero_exit(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    import roboclaws.evals.live_execution as live_exec

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
            '"failure_class": "checker_validation_failed", '
            '"reason": "cleanup checker exited with status 1"}\n'
        )
        return _completed_process(
            returncode=1,
            stderr="mcp session closed\ncleanup checker exited with status 1",
        )

    _patch_live_surface_popen(monkeypatch, live_exec, fake_run)

    run = run_eval_suite(
        "open_ended_goals",
        output_root=tmp_path,
        stamp="live-open-ended-checker-nonzero",
        agent_engine="openai-agents-sdk",
        provider_profile="kimi-openai-chat",
        live_execution="run",
        live_timeout_s=12.5,
    )

    payload = json.loads(run.results_path.read_text())
    assert payload["aggregate"]["passed"] == 0
    assert payload["aggregate"]["failed"] == 3
    result = payload["results"][0]
    assert result["status"] == "failed"
    assert result["failure_class"] == "checker_validation_failed"
    assert result["grader_outputs"]["runner"]["status"] == "failed"
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
    import roboclaws.evals.live_execution as live_exec

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

    _patch_live_surface_popen(monkeypatch, live_exec, fake_run)
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

    with pytest.raises(RuntimeError, match="live surface run failed with exit 1"):
        live_exec.run_live_surface_product(**kwargs)

    command_record = json.loads((tmp_path / "trial-0000" / "live_eval_command.json").read_text())
    assert command_record["returncode"] == 1


def test_live_cleanup_eval_fails_after_checker_nonzero_exit(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    import roboclaws.evals.live_execution as live_exec

    def fake_run(command: list[str], **_kwargs: Any) -> Any:
        output_arg = next(item for item in command if item.startswith("output_dir="))
        output_dir = Path(output_arg.removeprefix("output_dir="))
        run_dir = output_dir / "seed-7"
        launch_plan = _kwargs["launch_plan"]
        if launch_plan.preset == "map-build":
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
        if launch_plan.preset != "cleanup":
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
            '"failure_class": "checker_validation_failed", '
            '"reason": "cleanup checker exited with status 1"}\n'
        )
        return _completed_process(returncode=1, stderr="cleanup checker exited with status 1")

    _patch_live_surface_popen(monkeypatch, live_exec, fake_run)

    run = run_eval_suite(
        "map_build_consumer",
        output_root=tmp_path,
        stamp="live-cleanup-checker-nonzero",
        agent_engine="openai-agents-sdk",
        provider_profile="kimi-openai-chat",
        live_execution="run",
        live_timeout_s=12.5,
    )

    payload = json.loads(run.results_path.read_text())
    result = next(
        item
        for item in payload["results"]
        if item["identity"]["sample_id"] == "cleanup.consumer_no_prior_seed7"
    )
    assert result["status"] == "failed"
    assert result["failure_class"] == "checker_validation_failed"
    assert result["grader_outputs"]["runner"]["status"] == "failed"
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
