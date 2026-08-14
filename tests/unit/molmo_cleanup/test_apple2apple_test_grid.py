from __future__ import annotations

import argparse
import importlib.util
import json
import sys
from pathlib import Path

import pytest

from roboclaws.household.apple2apple_test_grid import (
    GRID_SCHEMA,
    RUNTIME_MAP_PRIOR_PLACEHOLDER,
    build_apple2apple_test_grid,
    write_grid_manifest,
)
from roboclaws.launch.catalog import resolve_surface_launch

REPO_ROOT = Path(__file__).resolve().parents[3]
RUN_GRID_PATH = REPO_ROOT / "scripts" / "molmo_cleanup" / "run_molmo_apple2apple_test_grid.py"


def _load_module(path: Path, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def _rows_by_id(grid: dict) -> dict[str, dict]:
    return {row["row_id"]: row for row in grid["rows"]}


def test_apple2apple_grid_axes_cover_requested_comparison(tmp_path: Path) -> None:
    grid = build_apple2apple_test_grid(output_dir=tmp_path / "grid", task="clean")

    assert grid["schema"] == GRID_SCHEMA
    assert grid["axes"]["prior_modes"] == ["online", "offline"]
    assert [item["route_id"] for item in grid["axes"]["agent_routes"]] == [
        "agents-sdk-kimi",
    ]
    assert [item["lane_id"] for item in grid["axes"]["evidence_lanes"]] == [
        "camera-grounded-labels-grounding-dino",
    ]
    assert len(grid["setup_rows"]) == 1
    assert len(grid["rows"]) == 2

    setup_command = grid["setup_rows"][0]["command"]
    assert setup_command[:8] == [
        "just",
        "run::surface",
        "surface=household-world",
        "world=molmospaces/procthor-10k-val/0",
        "backend=mujoco",
        "intent=map-build",
        "agent_engine=direct-runner",
        "evidence_lane=world-public-labels",
    ]
    assert "scenario_setup=baseline" in setup_command
    assert "map_bundle=assets/maps/molmospaces/procthor-10k-val/0" in setup_command


def test_apple2apple_grid_pins_provider_routes_and_perception(tmp_path: Path) -> None:
    grid = build_apple2apple_test_grid(output_dir=tmp_path / "grid", task="clean")
    rows = _rows_by_id(grid)

    kimi_dino = rows["online-agents-sdk-kimi-camera-grounded-labels-grounding-dino"]
    assert kimi_dino["env"] == {"ROBOCLAWS_PROVIDER_PROFILE": "kimi-openai-chat"}
    assert kimi_dino["required_env"] == ["KIMI_OPENAI_BASE_URL", "KIMI_API_KEY"]
    assert kimi_dino["command"][:9] == [
        "just",
        "run::surface",
        "surface=household-world",
        "world=molmospaces/procthor-10k-val/0",
        "backend=mujoco",
        "intent=cleanup",
        "agent_engine=openai-agents-sdk",
        "provider_profile=kimi-openai-chat",
        "evidence_lane=camera-grounded-labels",
    ]
    assert "camera_labeler=grounding-dino" in kimi_dino["command"]
    assert not any(item.startswith("runtime_map_prior=") for item in kimi_dino["command"])

    offline_dino = rows["offline-agents-sdk-kimi-camera-grounded-labels-grounding-dino"]
    assert f"runtime_map_prior={RUNTIME_MAP_PRIOR_PLACEHOLDER}" in offline_dino["command"]


def test_apple2apple_grid_cleanup_rows_resolve_through_launch_catalog(tmp_path: Path) -> None:
    grid = build_apple2apple_test_grid(output_dir=tmp_path / "grid", task="clean")

    for row in grid["rows"]:
        assert row["command"][:2] == ["just", "run::surface"]
        plan = resolve_surface_launch(row["command"][2:])
        axes = row["axes"]

        assert plan.surface == "household-world"
        assert plan.intent == "cleanup"
        assert plan.agent_engine == "openai-agents-sdk"
        assert plan.provider_profile == "kimi-openai-chat"
        assert plan.profile == axes["evidence_lane"]


def test_apple2apple_grid_accepts_explicit_offline_runtime_map_prior(tmp_path: Path) -> None:
    prior = "output/checks/household-world-map-build-final/seed-7/runtime_metric_map.json"
    grid = build_apple2apple_test_grid(
        output_dir=tmp_path / "grid",
        task="clean",
        runtime_map_prior=prior,
    )
    rows = _rows_by_id(grid)

    assert (
        f"runtime_map_prior={prior}"
        in rows["offline-agents-sdk-kimi-camera-grounded-labels-grounding-dino"]["command"]
    )
    assert RUNTIME_MAP_PRIOR_PLACEHOLDER not in " ".join(
        rows["offline-agents-sdk-kimi-camera-grounded-labels-grounding-dino"]["command"]
    )


def test_apple2apple_grid_script_dry_run_writes_manifest_and_report(tmp_path: Path) -> None:
    run_grid = _load_module(RUN_GRID_PATH, "run_molmo_apple2apple_test_grid")

    status = run_grid.main(["--output-dir", str(tmp_path / "grid"), "--task", "clean"])

    assert status == 0
    manifest_path = tmp_path / "grid" / "apple2apple_test_grid.json"
    report_path = tmp_path / "grid" / "apple2apple_test_grid.html"
    assert manifest_path.is_file()
    assert report_path.is_file()
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    assert manifest["schema"] == GRID_SCHEMA
    assert {row["status"] for row in manifest["rows"]} == {"dry_run"}
    assert "online-agents-sdk-kimi-camera-grounded-labels-grounding-dino" in report_path.read_text(
        encoding="utf-8"
    )


def test_apple2apple_grid_filtered_execute_preserves_existing_rows(tmp_path: Path) -> None:
    run_grid = _load_module(RUN_GRID_PATH, "run_molmo_apple2apple_test_grid_preserve")
    output_dir = tmp_path / "grid"
    existing = build_apple2apple_test_grid(output_dir=output_dir, task="clean")
    existing_rows = _rows_by_id(existing)
    preserved_row = existing_rows["offline-agents-sdk-kimi-camera-grounded-labels-grounding-dino"]
    preserved_row["status"] = "success"
    preserved_row["exit_status"] = 0
    preserved_row["run_result_path"] = str(output_dir / "online-kimi" / "run_result.json")
    preserved_row["report_path"] = str(output_dir / "online-kimi" / "report.html")
    write_grid_manifest(existing, output_dir)

    def fake_execute_row(row: dict, _args: argparse.Namespace) -> int:
        row["status"] = "success"
        row["exit_status"] = 0
        return 0

    run_grid._execute_row = fake_execute_row

    status = run_grid.main(
        [
            "--output-dir",
            str(output_dir),
            "--task",
            "clean",
            "--execute",
            "--row",
            "online-agents-sdk-kimi-camera-grounded-labels-grounding-dino",
        ]
    )

    manifest = json.loads((output_dir / "apple2apple_test_grid.json").read_text(encoding="utf-8"))
    rows = _rows_by_id(manifest)
    assert status == 0
    assert (
        rows["offline-agents-sdk-kimi-camera-grounded-labels-grounding-dino"]["status"] == "success"
    )
    assert rows["offline-agents-sdk-kimi-camera-grounded-labels-grounding-dino"][
        "run_result_path"
    ].endswith("run_result.json")
    assert rows["online-agents-sdk-kimi-camera-grounded-labels-grounding-dino"]["status"] == (
        "success"
    )


def test_apple2apple_grid_filtered_execute_fails_on_malformed_existing_manifest(
    tmp_path: Path,
) -> None:
    run_grid = _load_module(RUN_GRID_PATH, "run_molmo_apple2apple_test_grid_malformed_manifest")
    output_dir = tmp_path / "grid"
    output_dir.mkdir()
    (output_dir / "apple2apple_test_grid.json").write_text("{not json", encoding="utf-8")

    with pytest.raises(
        ValueError,
        match=r"grid manifest source must contain valid JSON object: .*apple2apple_test_grid",
    ):
        run_grid.main(
            [
                "--output-dir",
                str(output_dir),
                "--task",
                "clean",
                "--execute",
                "--row",
                "online-agents-sdk-kimi-camera-grounded-labels-grounding-dino",
            ]
        )


def test_apple2apple_grid_filtered_execute_fails_on_non_object_existing_manifest(
    tmp_path: Path,
) -> None:
    run_grid = _load_module(RUN_GRID_PATH, "run_molmo_apple2apple_test_grid_non_object_manifest")
    output_dir = tmp_path / "grid"
    output_dir.mkdir()
    (output_dir / "apple2apple_test_grid.json").write_text("[]", encoding="utf-8")

    with pytest.raises(
        ValueError,
        match=r"grid manifest source must contain a JSON object: .*apple2apple_test_grid",
    ):
        run_grid.main(
            [
                "--output-dir",
                str(output_dir),
                "--task",
                "clean",
                "--execute",
                "--row",
                "online-agents-sdk-kimi-camera-grounded-labels-grounding-dino",
            ]
        )


def test_apple2apple_grid_accepts_prior_artifact_when_setup_exits_nonzero(
    tmp_path: Path,
) -> None:
    run_grid = _load_module(RUN_GRID_PATH, "run_molmo_apple2apple_test_grid_prior_nonzero")
    output_dir = tmp_path / "grid" / "_offline-runtime-map-prior"
    run_dir = output_dir / "0528_1200" / "seed-7"
    run_dir.mkdir(parents=True)
    prior_path = run_dir / "runtime_metric_map.json"
    prior_path.write_text("{}", encoding="utf-8")
    row = {"output_dir": str(output_dir), "status": "pending", "reason": ""}
    grid = {"setup_rows": [row]}
    args = argparse.Namespace(seed=7)

    def fake_execute_row(_row: dict, _args: argparse.Namespace) -> int:
        _row["run_dir"] = str(run_dir)
        _row["exit_status"] = 1
        return 1

    run_grid._execute_row = fake_execute_row

    prior = run_grid._execute_prior_build(grid, args)

    assert prior == str(prior_path)
    assert row["runtime_map_prior"] == str(prior_path)
    assert row["status"] == "artifact_success"
    assert "exited with status 1" in row["reason"]


def test_apple2apple_grid_marks_explicit_prior_as_setup_evidence(tmp_path: Path) -> None:
    run_grid = _load_module(RUN_GRID_PATH, "run_molmo_apple2apple_test_grid_explicit_prior")
    run_dir = tmp_path / "prior" / "0528_1200" / "seed-7"
    run_dir.mkdir(parents=True)
    prior_path = run_dir / "runtime_metric_map.json"
    prior_path.write_text("{}", encoding="utf-8")
    (run_dir / "report.html").write_text("<html>prior</html>", encoding="utf-8")
    (run_dir / "run_result.json").write_text("{}", encoding="utf-8")
    grid = build_apple2apple_test_grid(
        output_dir=tmp_path / "grid",
        task="clean",
        runtime_map_prior=str(prior_path),
    )

    run_grid._mark_explicit_runtime_map_prior(grid, str(prior_path))

    row = grid["setup_rows"][0]
    assert row["status"] == "artifact_success"
    assert row["runtime_map_prior"] == str(prior_path)
    assert row["run_dir"] == str(run_dir)
    assert row["report_path"] == str(run_dir / "report.html")
    assert row["run_result_path"] == str(run_dir / "run_result.json")
    assert "explicit runtime_map_prior" in row["reason"]


def test_apple2apple_grid_execute_waits_for_detached_live_status(tmp_path: Path) -> None:
    run_grid = _load_module(RUN_GRID_PATH, "run_molmo_apple2apple_test_grid_live_wait")
    output_dir = tmp_path / "grid"
    run_dir = output_dir / "0528_1200" / "seed-7"
    run_dir.mkdir(parents=True)
    (run_dir / "live_status.json").write_text(
        json.dumps({"phase": "finished", "exit_status": 0}),
        encoding="utf-8",
    )
    (run_dir / "report.html").write_text("<html>ok</html>", encoding="utf-8")
    row = {
        "command": [sys.executable, "-c", ""],
        "env": {},
        "output_dir": str(output_dir),
    }
    args = argparse.Namespace(
        seed=7,
        just_bin="just",
        live_wait_timeout_s=0.1,
        live_wait_poll_s=0.1,
    )

    status = run_grid._execute_row(row, args)

    assert status == 0
    assert row["status"] == "success"
    assert row["run_dir"] == str(run_dir)
    assert row["report_path"] == str(run_dir / "report.html")
    assert row["live_status"]["phase"] == "finished"


def test_apple2apple_grid_execute_discovers_live_status_only_seed_dir(
    tmp_path: Path,
) -> None:
    run_grid = _load_module(RUN_GRID_PATH, "run_molmo_apple2apple_test_grid_live_status_only")
    output_dir = tmp_path / "grid"
    run_dir = output_dir / "0528_1200" / "seed-7"
    run_dir.mkdir(parents=True)
    (run_dir / "live_status.json").write_text(
        json.dumps({"phase": "finished", "exit_status": 0}),
        encoding="utf-8",
    )
    row = {
        "command": [sys.executable, "-c", ""],
        "env": {},
        "output_dir": str(output_dir),
    }
    args = argparse.Namespace(
        seed=7,
        just_bin="just",
        live_wait_timeout_s=0.1,
        live_wait_poll_s=0.1,
    )

    status = run_grid._execute_row(row, args)

    assert status == 0
    assert row["run_dir"] == str(run_dir)
    assert row["live_status"]["phase"] == "finished"
    assert row["status"] == "launched"


def test_apple2apple_grid_execute_fails_on_malformed_live_status_source(
    tmp_path: Path,
) -> None:
    run_grid = _load_module(RUN_GRID_PATH, "run_molmo_apple2apple_test_grid_malformed_live_status")
    output_dir = tmp_path / "grid"
    run_dir = output_dir / "0528_1200" / "seed-7"
    run_dir.mkdir(parents=True)
    (run_dir / "live_status.json").write_text("{bad", encoding="utf-8")
    row = {
        "command": [sys.executable, "-c", ""],
        "env": {},
        "output_dir": str(output_dir),
    }
    args = argparse.Namespace(
        seed=7,
        just_bin="just",
        live_wait_timeout_s=0.1,
        live_wait_poll_s=0.1,
    )

    with pytest.raises(
        ValueError,
        match=r"live status source must contain valid JSON object: .*live_status",
    ):
        run_grid._execute_row(row, args)


def test_apple2apple_grid_live_status_retry_allows_transient_partial_write(
    tmp_path: Path,
) -> None:
    run_grid = _load_module(RUN_GRID_PATH, "run_molmo_apple2apple_test_grid_live_status_retry")
    status_path = tmp_path / "live_status.json"
    status_path.write_text("{bad", encoding="utf-8")
    attempts = {"count": 0}
    real_read_json_object = run_grid.read_json_object

    def flaky_read_json_object(path: Path, *, label: str) -> dict:
        attempts["count"] += 1
        if attempts["count"] == 1:
            raise ValueError("transient partial write")
        status_path.write_text(
            json.dumps({"phase": "finished", "exit_status": 0}),
            encoding="utf-8",
        )
        return real_read_json_object(path, label=label)

    run_grid.read_json_object = flaky_read_json_object
    run_grid._sleep = lambda _seconds: None
    run_grid._monotonic = iter([0.0, 0.0, 0.01]).__next__

    status = run_grid._read_status(status_path, retry_deadline=1.0)

    assert status == {"phase": "finished", "exit_status": 0}
    assert attempts["count"] == 2
