from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from roboclaws.launch import scene_sampler_scanner_runner


def _repo_root() -> Path:
    for parent in Path(__file__).resolve().parents:
        if (parent / "justfile").is_file():
            return parent
    raise AssertionError("could not locate repo root")


REPO_ROOT = _repo_root()


def _load_runner():
    return scene_sampler_scanner_runner


def _write_plan(path: Path, candidates: list[dict[str, object]]) -> None:
    path.write_text(
        json.dumps(
            {
                "schema": "molmospaces_scene_sampler_scanner_execution_plan_v1",
                "sources": {
                    "ithor": {
                        "candidates": candidates,
                    }
                },
            },
            indent=2,
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )


def _write_worklist(
    path: Path,
    *,
    next_action: str = "run_scanner_plan_for_ready_candidates",
) -> None:
    path.write_text(
        json.dumps(
            {
                "schema": "molmospaces_scene_sampler_next_flow_worklist_v1",
                "sources": {
                    "ithor": {
                        "scene_source": "ithor",
                        "next_action": next_action,
                        "next_scan_world_ids": ["molmospaces/ithor/1"],
                        "scanner_ready_world_ids": ["molmospaces/ithor/1"]
                        if next_action == "run_scanner_plan_for_ready_candidates"
                        else [],
                    }
                },
            },
            indent=2,
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )


def _candidate(*, scanner_status: str = "blocked_missing_resources") -> dict[str, object]:
    return {
        "scene_family": "ithor",
        "scene_split": "not_applicable",
        "scene_source": "ithor",
        "scene_index": 1,
        "world_id": "molmospaces/ithor/1",
        "scanner_status": scanner_status,
        "admission_status": "blocked",
        "readiness_status": "blocked",
        "lanes": [],
        "failure_class": "environment_blocked",
        "blocked_reason": "source assets missing",
        "selected_reason": "scanner_candidate_ready_for_product_smoke",
        "room_count": 4,
        "waypoint_count": 4,
        "category_provenance": "prepared_visual_label_manifest",
        "preview_statuses": {
            "fpv": "reviewable",
            "map": "reviewable",
            "chase": "reviewable",
            "topdown": "reviewable",
        },
        "passed_gates": ["preview_metadata", "public_room_count"],
        "required_gates": [
            "source_asset_available",
            "preview_metadata",
            "public_room_count",
            "public_waypoints",
            "trusted_category_provenance",
            "map_build_artifacts",
        ],
        "missing_gates": (
            ["source_asset_available"] if scanner_status != "ready_for_product_smoke" else []
        ),
        "missing_paths": ["/tmp/FloorPlan1_physics.xml"]
        if scanner_status != "ready_for_product_smoke"
        else [],
        "candidate_file": {
            "exists": scanner_status == "ready_for_product_smoke",
            "path": "/tmp/FloorPlan1_physics.xml",
        },
        "primary_path": "/tmp/FloorPlan1_physics.xml",
        "path_status": "available",
        "preview_command": (
            ".venv/bin/python -m roboclaws.operator_console.scene_preview_cli "
            "--world molmospaces/ithor/1"
        ),
        "launch_args": [
            "surface=household-world",
            "world=molmospaces/ithor/1",
            "backend=mujoco",
            "preset=map-build",
            "agent_engine=direct-runner",
            "evidence_lane=world-public-labels",
        ],
        "map_build_product_smoke_command": (
            "just run::surface surface=household-world world=molmospaces/ithor/1 "
            "backend=mujoco preset=map-build agent_engine=direct-runner "
            "evidence_lane=world-public-labels"
        ),
    }


def test_scanner_runner_skips_blocked_candidates_without_running_commands(tmp_path: Path) -> None:
    runner = _load_runner()
    plan_path = tmp_path / "plan.json"
    output_path = tmp_path / "scanner_run.json"
    _write_plan(plan_path, [_candidate()])
    calls = []

    result = runner.run_scanner_plan(
        plan_path=plan_path,
        output_path=output_path,
        run_command=lambda *_args, **_kwargs: calls.append(_args),
    )

    assert result["schema"] == "molmospaces_scene_sampler_scanner_run_v1"
    assert result["status"] == "no_ready_candidates"
    assert result["skipped_candidate_count"] == 1
    assert result["sources"]["ithor"] == {
        "scene_source": "ithor",
        "status": "no_ready_candidates",
        "candidate_count": 1,
        "ready_candidate_count": 0,
        "executed_candidate_count": 0,
        "skipped_candidate_count": 1,
        "failed_candidate_count": 0,
        "world_ids": ["molmospaces/ithor/1"],
    }
    assert result["rows"][0]["status"] == "skipped_blocked_candidate"
    assert result["rows"][0]["scene_family"] == "ithor"
    assert result["rows"][0]["failure_class"] == "environment_blocked"
    assert result["rows"][0]["room_count"] == 4
    assert result["rows"][0]["waypoint_count"] == 4
    assert result["rows"][0]["category_provenance"] == "prepared_visual_label_manifest"
    assert result["rows"][0]["preview_statuses"]["fpv"] == "reviewable"
    assert result["rows"][0]["candidate_file"]["path"] == "/tmp/FloorPlan1_physics.xml"
    assert calls == []
    assert json.loads(output_path.read_text(encoding="utf-8")) == result


def test_scanner_runner_rejects_missing_plan_source(tmp_path: Path) -> None:
    runner = _load_runner()

    with pytest.raises(
        FileNotFoundError,
        match=r"scene sampler scanner execution plan source is missing: .*plan\.json",
    ):
        runner.run_scanner_plan(
            plan_path=tmp_path / "plan.json",
            output_path=tmp_path / "scanner_run.json",
        )


def test_scanner_runner_rejects_malformed_plan_source(tmp_path: Path) -> None:
    runner = _load_runner()
    plan_path = tmp_path / "plan.json"
    plan_path.write_text("{not-json\n", encoding="utf-8")

    with pytest.raises(
        ValueError,
        match=(
            r"scene sampler scanner execution plan source must contain valid JSON object: "
            r".*plan\.json"
        ),
    ):
        runner.run_scanner_plan(
            plan_path=plan_path,
            output_path=tmp_path / "scanner_run.json",
        )


def test_scanner_runner_rejects_non_object_plan_source(tmp_path: Path) -> None:
    runner = _load_runner()
    plan_path = tmp_path / "plan.json"
    plan_path.write_text("[]\n", encoding="utf-8")

    with pytest.raises(
        ValueError,
        match=(
            r"scene sampler scanner execution plan source must contain a JSON object: "
            r".*plan\.json"
        ),
    ):
        runner.run_scanner_plan(
            plan_path=plan_path,
            output_path=tmp_path / "scanner_run.json",
        )


def test_scanner_runner_dry_run_records_ready_commands_without_execution(tmp_path: Path) -> None:
    runner = _load_runner()
    plan_path = tmp_path / "plan.json"
    output_path = tmp_path / "scanner_run.json"
    _write_plan(plan_path, [_candidate(scanner_status="ready_for_product_smoke")])
    calls = []

    result = runner.run_scanner_plan(
        plan_path=plan_path,
        output_path=output_path,
        dry_run=True,
        run_command=lambda *_args, **_kwargs: calls.append(_args),
    )

    assert result["status"] == "dry_run"
    assert result["ready_candidate_count"] == 1
    assert result["sources"]["ithor"]["status"] == "ready_not_executed"
    assert result["sources"]["ithor"]["ready_candidate_count"] == 1
    assert result["sources"]["ithor"]["executed_candidate_count"] == 0
    assert [item["name"] for item in result["rows"][0]["commands"]] == [
        "preview",
        "map_build_product_smoke",
    ]
    assert {item["status"] for item in result["rows"][0]["commands"]} == {"dry_run"}
    assert calls == []


def test_scanner_runner_records_worklist_alignment(tmp_path: Path) -> None:
    runner = _load_runner()
    plan_path = tmp_path / "plan.json"
    worklist_path = tmp_path / "next_flow_worklist.json"
    output_path = tmp_path / "scanner_run.json"
    _write_plan(plan_path, [_candidate(scanner_status="ready_for_product_smoke")])
    _write_worklist(worklist_path)

    result = runner.run_scanner_plan(
        plan_path=plan_path,
        worklist_path=worklist_path,
        output_path=output_path,
        dry_run=True,
    )

    alignment = result["worklist_alignment"]
    assert alignment["schema"] == "molmospaces_scene_sampler_runner_worklist_alignment_v1"
    assert alignment["runner"] == "scanner"
    assert alignment["status"] == "aligned"
    assert alignment["sources"]["ithor"]["status"] == "aligned"
    assert alignment["sources"]["ithor"]["expected_world_ids"] == ["molmospaces/ithor/1"]
    assert alignment["sources"]["ithor"]["run_world_ids"] == ["molmospaces/ithor/1"]


def test_scanner_runner_marks_run_before_worklist_action(tmp_path: Path) -> None:
    runner = _load_runner()
    plan_path = tmp_path / "plan.json"
    worklist_path = tmp_path / "next_flow_worklist.json"
    output_path = tmp_path / "scanner_run.json"
    _write_plan(plan_path, [_candidate(scanner_status="blocked_missing_resources")])
    _write_worklist(worklist_path, next_action="run_manual_source_prep")

    result = runner.run_scanner_plan(
        plan_path=plan_path,
        worklist_path=worklist_path,
        output_path=output_path,
    )

    alignment = result["worklist_alignment"]
    assert alignment["status"] == "ran_before_worklist_action"
    assert alignment["sources"]["ithor"]["status"] == "ran_before_worklist_action"
    assert alignment["sources"]["ithor"]["worklist_next_action"] == "run_manual_source_prep"


def test_scanner_runner_rejects_malformed_worklist_source(tmp_path: Path) -> None:
    runner = _load_runner()
    plan_path = tmp_path / "plan.json"
    worklist_path = tmp_path / "next_flow_worklist.json"
    _write_plan(plan_path, [_candidate(scanner_status="ready_for_product_smoke")])
    worklist_path.write_text("{not-json\n", encoding="utf-8")

    with pytest.raises(
        ValueError,
        match=(
            r"scene sampler next-flow worklist source must contain valid JSON object: "
            r".*next_flow_worklist\.json"
        ),
    ):
        runner.run_scanner_plan(
            plan_path=plan_path,
            worklist_path=worklist_path,
            output_path=tmp_path / "scanner_run.json",
            dry_run=True,
        )


def test_scanner_runner_rejects_non_object_worklist_source(tmp_path: Path) -> None:
    runner = _load_runner()
    plan_path = tmp_path / "plan.json"
    worklist_path = tmp_path / "next_flow_worklist.json"
    _write_plan(plan_path, [_candidate(scanner_status="ready_for_product_smoke")])
    worklist_path.write_text("[]\n", encoding="utf-8")

    with pytest.raises(
        ValueError,
        match=(
            r"scene sampler next-flow worklist source must contain a JSON object: "
            r".*next_flow_worklist\.json"
        ),
    ):
        runner.run_scanner_plan(
            plan_path=plan_path,
            worklist_path=worklist_path,
            output_path=tmp_path / "scanner_run.json",
            dry_run=True,
        )


def test_scanner_runner_executes_ready_preview_then_typed_map_build(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    runner = _load_runner()
    plan_path = tmp_path / "plan.json"
    output_path = tmp_path / "scanner_run.json"
    _write_plan(plan_path, [_candidate(scanner_status="ready_for_product_smoke")])
    preview_calls = []
    launch_calls = []

    def fake_run(argv, **kwargs):
        preview_calls.append((argv, kwargs))
        return SimpleNamespace(returncode=0, stdout="ok\n", stderr="")

    def fake_spawn(plan, **kwargs):
        launch_calls.append((plan, kwargs))
        kwargs["stdout"].write("map build ok\n")
        return SimpleNamespace(wait=lambda: 0)

    monkeypatch.setattr(runner, "spawn_launch_plan", fake_spawn)
    result = runner.run_scanner_plan(
        plan_path=plan_path,
        output_path=output_path,
        run_command=fake_run,
    )

    assert result["status"] == "success"
    assert result["executed_candidate_count"] == 1
    assert result["sources"]["ithor"]["status"] == "executed"
    assert result["sources"]["ithor"]["executed_candidate_count"] == 1
    assert result["sources"]["ithor"]["failed_candidate_count"] == 0
    assert result["rows"][0]["status"] == "passed"
    assert [item["name"] for item in result["rows"][0]["commands"]] == [
        "preview",
        "map_build_product_smoke",
    ]
    assert len(preview_calls) == 1
    assert preview_calls[0][0][:3] == [
        ".venv/bin/python",
        "-m",
        "roboclaws.operator_console.scene_preview_cli",
    ]
    assert len(launch_calls) == 1
    plan, launch_kwargs = launch_calls[0]
    assert plan.surface == "household-world"
    assert plan.world == "molmospaces/ithor/1"
    assert plan.preset == "map-build"
    assert plan.agent_engine == "direct-runner"
    assert launch_kwargs["cwd"] == REPO_ROOT
    assert launch_kwargs["env"]["ROBOCLAWS_TASK_SURFACE"] == "household-world"
    assert result["rows"][0]["commands"][1]["argv"][:2] == ["just", "run::surface"]
    assert result["rows"][0]["commands"][1]["stdout_tail"] == "map build ok\n"


def test_scanner_runner_does_not_execute_map_build_provenance_without_launch_args(
    tmp_path: Path,
) -> None:
    runner = _load_runner()
    plan_path = tmp_path / "plan.json"
    output_path = tmp_path / "scanner_run.json"
    candidate = _candidate(scanner_status="ready_for_product_smoke")
    candidate.pop("launch_args")
    _write_plan(plan_path, [candidate])
    preview_calls = []

    def fake_run(argv, **kwargs):
        preview_calls.append((argv, kwargs))
        return SimpleNamespace(returncode=0, stdout="ok\n", stderr="")

    result = runner.run_scanner_plan(
        plan_path=plan_path,
        output_path=output_path,
        run_command=fake_run,
    )

    assert len(preview_calls) == 1
    assert result["status"] == "failed"
    assert result["rows"][0]["failed_command"] == "map_build_product_smoke"
    assert result["rows"][0]["commands"][1]["argv"] == []
    assert result["rows"][0]["commands"][1]["stderr_tail"] == (
        "candidate launch_args must be a non-empty list of strings"
    )


def test_scanner_runner_source_summary_records_failures(tmp_path: Path) -> None:
    runner = _load_runner()
    plan_path = tmp_path / "plan.json"
    output_path = tmp_path / "scanner_run.json"
    _write_plan(plan_path, [_candidate(scanner_status="ready_for_product_smoke")])

    def fake_run(argv, **kwargs):
        return SimpleNamespace(returncode=17, stdout="", stderr="preview failed")

    result = runner.run_scanner_plan(
        plan_path=plan_path,
        output_path=output_path,
        run_command=fake_run,
    )

    assert result["status"] == "failed"
    assert result["failed_candidate_count"] == 1
    assert result["sources"]["ithor"]["status"] == "failed"
    assert result["sources"]["ithor"]["executed_candidate_count"] == 1
    assert result["sources"]["ithor"]["failed_candidate_count"] == 1
    assert result["rows"][0]["failed_command"] == "preview"
