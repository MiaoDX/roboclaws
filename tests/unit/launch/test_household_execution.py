from __future__ import annotations

import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

from roboclaws.launch import household, household_execution


def _execution(*, dispatch_runner: str = "direct", backend: str = "api_semantic_synthetic"):
    plan = SimpleNamespace(
        dispatch_runner=dispatch_runner,
        goal_contract=SimpleNamespace(to_json=lambda: '{"schema":"goal"}'),
        intent="cleanup",
        world="molmospaces/procthor-10k-val/0",
        relocation_count=2,
    )
    return household_execution.HouseholdExecution(
        plan=plan,
        kv={"generated_mess_object_ids": "cup_1,cup_2"},
        seeds=("7",),
        output_dir=Path("output/test"),
        task="put away the cups",
        profile="world-public-labels",
        backend=backend,
        evidence_lane="world-public-labels",
        perception_mode="visible_object_detections",
        visual_grounding="sim",
        visual_grounding_timeout_s=None,
        min_generated_mess_count=2,
        validation_options={"require_base_metric_map": True},
    )


def test_direct_episode_receives_typed_execution_options(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    captured: dict[str, object] = {}

    def fake_run(**kwargs):
        captured.update(kwargs)
        return {"status": "ok"}

    monkeypatch.setattr(household, "run_household_world_episode", fake_run)
    execution = _execution()

    status = household._run_deterministic(
        execution,
        seed=7,
        run_dir=tmp_path / "seed-7",
        map_bundle=tmp_path / "map",
    )

    assert status == 0
    assert captured["seed"] == 7
    assert captured["task_prompt"] == "put away the cups"
    assert captured["generated_mess_object_ids"] == ("cup_1", "cup_2")
    assert captured["map_bundle_dir"] == tmp_path / "map"
    assert captured["intent"] == "cleanup"


def test_mcp_smoke_receives_typed_execution_options(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    captured: dict[str, object] = {}

    def fake_run(**kwargs):
        captured.update(kwargs)
        return {"status": "ok"}

    monkeypatch.setattr(household, "run_smoke", fake_run)
    execution = _execution(dispatch_runner="mcp-smoke")

    status = household._run_deterministic(
        execution,
        seed=7,
        run_dir=tmp_path / "seed-7",
        map_bundle=tmp_path / "map",
    )

    assert status == 0
    assert captured["task"] == "put away the cups"
    assert captured["policy"] == "household_contract_smoke_agent"
    assert "task_prompt" not in captured
    assert "intent" not in captured


def test_execute_plan_uses_in_process_deterministic_owner(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    execution = _execution()
    calls: list[tuple[int, Path, Path]] = []
    monkeypatch.setattr(
        household_execution,
        "resolve_household_execution",
        lambda *_args, **_kwargs: execution,
    )
    monkeypatch.setattr(
        household, "_resolve_map_bundle", lambda *_args, **_kwargs: tmp_path / "map"
    )
    monkeypatch.setattr(household, "_run_root", lambda _execution: tmp_path / "runs")
    monkeypatch.setattr(household, "_sidecar_for", lambda _execution: None)
    monkeypatch.setattr(household, "_requires_process_boundary", lambda _execution: False)
    monkeypatch.setattr(
        household,
        "_run_deterministic",
        lambda _execution, *, seed, run_dir, map_bundle: (
            calls.append((seed, run_dir, map_bundle)) or 0
        ),
    )
    monkeypatch.setattr(household, "_validate_runs", lambda *_args, **_kwargs: 0)
    monkeypatch.setattr(
        household,
        "_run_subprocess",
        lambda _command: pytest.fail("local deterministic execution must stay in process"),
    )

    assert household.execute_household_plan(plan=execution.plan, kv={}) == 0
    assert calls == [(7, tmp_path / "runs" / "seed-7", tmp_path / "map")]


def test_cleanup_validation_calls_package_api_directly(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    execution = _execution()
    execution.validation_options.update(
        require_waypoint_honesty=True,
        min_sweep_coverage=1.0,
    )
    result_path = tmp_path / "seed-7" / "run_result.json"
    calls: list[tuple[dict[str, object], Path, dict[str, object]]] = []
    monkeypatch.setattr(
        household,
        "load_run_results",
        lambda _path: [({"seed": 7}, result_path)],
    )
    monkeypatch.setattr(
        household,
        "validate_run_result",
        lambda data, base, **options: calls.append((data, base, options)),
    )
    monkeypatch.setattr(
        household,
        "_run_subprocess",
        lambda _command: pytest.fail("validation must not start a CLI subprocess"),
    )

    assert household._validate_runs(execution, run_root=tmp_path) == 0
    assert calls[0][1] == result_path.parent
    assert calls[0][2]["expect_task"] == "put away the cups"
    assert calls[0][2]["require_waypoint_honesty"] is True
    assert calls[0][2]["min_sweep_coverage"] == 1.0


def test_external_python_and_isaac_keep_process_boundaries(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    execution = _execution()
    monkeypatch.setattr(household, "_REPO_PYTHON", sys.executable)
    assert not household._requires_process_boundary(execution)

    monkeypatch.setattr(household, "_REPO_PYTHON", "/opt/isolated/bin/python")
    assert household._requires_process_boundary(execution)

    monkeypatch.setattr(household, "_REPO_PYTHON", sys.executable)
    execution.backend = "isaaclab_subprocess"
    execution.plan.world = "b1-map12"
    assert household._requires_process_boundary(execution)
