from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pytest

from roboclaws.household import grasp_cache_generation as generation
from roboclaws.household.grasp_cache_generation import (
    GRASP_CACHE_GENERATION_SCHEMA,
    load_generation_preflight_from_manifest,
    run_grasp_cache_generation,
)
from roboclaws.household.report_planner import render_grasp_cache_generation_report


def test_generation_dry_run_writes_objects_list(tmp_path: Path) -> None:
    (tmp_path / "Bread_1_mesh.xml").write_text("<mujoco />", encoding="utf-8")
    output_dir = tmp_path / "out"
    result = run_grasp_cache_generation(
        generation_preflight=_generation_preflight(tmp_path),
        output_dir=output_dir,
        molmospaces_python=Path("/tmp/molmo/.venv/bin/python"),
        max_successful_grasps=12,
        approach_steps=30,
        shake_steps=10,
        dry_run=True,
    )

    assert result["schema"] == GRASP_CACHE_GENERATION_SCHEMA
    assert result["status"] == "dry_run"
    assert result["objects_list"] == [
        {"name": "Bread_1", "xml": str(tmp_path / "Bread_1_mesh.xml")}
    ]
    assert Path(result["objects_list_path"]).is_file()
    assert "--max_successful_grasps" in result["command"]
    assert "12" in result["command"]
    assert "--approach_steps" in result["command"]
    assert "30" in result["command"]
    assert "--shake_steps" in result["command"]
    assert "10" in result["command"]
    assert result["assets_symlink"]["status"] == "not_run"
    assert result["command_result"]["status"] == "not_run"


def test_generation_installs_valid_generated_npz(tmp_path: Path, monkeypatch) -> None:
    generated = tmp_path / "generated" / "Bread_1_grasps_filtered.npz"
    target = tmp_path / "assets" / "grasps" / "droid" / "Bread_1" / "Bread_1_grasps_filtered.npz"
    generated.parent.mkdir(parents=True)
    np.savez(generated, transforms=np.zeros((2, 4, 4)))
    target.parent.mkdir(parents=True)
    np.savez(target, transforms=np.zeros((0, 4, 4)))
    assets_dir = tmp_path / "assets"

    class Completed:
        returncode = 0
        stdout = "ok"
        stderr = ""

    monkeypatch.setattr(generation.subprocess, "run", lambda *args, **kwargs: Completed())

    result = run_grasp_cache_generation(
        generation_preflight=_generation_preflight(
            tmp_path,
            generated_npz=generated,
            target_npz=target,
            assets_dir=assets_dir,
        ),
        output_dir=tmp_path / "out2",
        molmospaces_python=Path("/tmp/molmo/.venv/bin/python"),
        install=True,
        dry_run=False,
        timeout_s=1,
    )
    assert result["status"] == "ready"
    assert Path(result["assets_symlink"]["path"]).resolve() == assets_dir.resolve()
    assert result["assets"][0]["generated_valid"] is True
    assert result["assets"][0]["installed"] is True
    assert result["assets"][0]["installed_validation"]["transform_count"] == 2


def test_load_generation_preflight_from_manifest(tmp_path: Path) -> None:
    manifest = tmp_path / "proof_bundle_run_manifest.json"
    manifest.write_text(
        json.dumps({"grasp_cache_generation_preflight": {"status": "ready"}}),
        encoding="utf-8",
    )

    assert load_generation_preflight_from_manifest(manifest) == {"status": "ready"}


def test_load_generation_preflight_rejects_missing_manifest_source(tmp_path: Path) -> None:
    with pytest.raises(
        FileNotFoundError,
        match=(
            r"grasp cache generation proof bundle manifest source is missing: "
            r".*proof_bundle_run_manifest\.json"
        ),
    ):
        load_generation_preflight_from_manifest(tmp_path / "proof_bundle_run_manifest.json")


def test_load_generation_preflight_rejects_malformed_manifest_source(tmp_path: Path) -> None:
    manifest = tmp_path / "proof_bundle_run_manifest.json"
    manifest.write_text("{not-json\n", encoding="utf-8")

    with pytest.raises(
        ValueError,
        match=(
            r"grasp cache generation proof bundle manifest source must contain valid JSON object: "
            r".*proof_bundle_run_manifest\.json"
        ),
    ):
        load_generation_preflight_from_manifest(manifest)


def test_load_generation_preflight_rejects_non_object_manifest_source(tmp_path: Path) -> None:
    manifest = tmp_path / "proof_bundle_run_manifest.json"
    manifest.write_text("[]\n", encoding="utf-8")

    with pytest.raises(
        ValueError,
        match=(
            r"grasp cache generation proof bundle manifest source must contain a JSON object: "
            r".*proof_bundle_run_manifest\.json"
        ),
    ):
        load_generation_preflight_from_manifest(manifest)


def test_render_grasp_cache_generation_report(tmp_path: Path) -> None:
    result = run_grasp_cache_generation(
        generation_preflight=_generation_preflight(tmp_path),
        output_dir=tmp_path / "out",
        molmospaces_python=Path("/tmp/molmo/.venv/bin/python"),
        dry_run=True,
    )

    report = render_grasp_cache_generation_report(output_dir=tmp_path / "out", result=result)
    text = report.read_text(encoding="utf-8")
    assert "MolmoSpaces Grasp Cache Generation" in text
    assert "Generated Cache Assets" in text
    assert "Generation Command" in text
    assert "Bread_1" in text


def _generation_preflight(
    tmp_path: Path,
    *,
    generated_npz: Path | None = None,
    target_npz: Path | None = None,
    assets_dir: Path | None = None,
) -> dict:
    working_dir = tmp_path / "molmospaces" / "molmo_spaces" / "grasp_generation"
    working_dir.mkdir(parents=True, exist_ok=True)
    return {
        "status": "ready",
        "molmospaces_python": "/tmp/molmo/.venv/bin/python",
        "working_dir": str(working_dir),
        "assets_dir": str(assets_dir or tmp_path / "assets"),
        "assets": [
            {
                "asset_uid": "Bread_1",
                "objects_list_entry": {"name": "Bread_1", "xml": str(tmp_path / "Bread_1.xml")},
                "generated_npz_path": str(
                    generated_npz or tmp_path / "generated" / "Bread_1_grasps_filtered.npz"
                ),
                "cache_target_resolved_path": str(
                    target_npz
                    or tmp_path
                    / "assets"
                    / "grasps"
                    / "droid"
                    / "Bread_1"
                    / "Bread_1_grasps_filtered.npz"
                ),
            }
        ],
    }
