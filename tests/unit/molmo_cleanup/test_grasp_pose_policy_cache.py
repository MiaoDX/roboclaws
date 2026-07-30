from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pytest

from roboclaws.household import grasp_pose_policy_cache as pose_cache
from roboclaws.household.grasp_pose_policy_cache import (
    GRASP_POSE_POLICY_CACHE_SCHEMA,
    load_initial_contact_result,
    resolve_pose_policy,
    run_grasp_pose_policy_cache_generation,
)
from roboclaws.household.report_planner import render_grasp_pose_policy_cache_report


def test_resolve_pose_policy_uses_initial_contact_best_variant(tmp_path: Path) -> None:
    result_path = tmp_path / "initial_contact_result.json"
    result_path.write_text(
        json.dumps(
            {
                "best_variant": {
                    "name": "sign_1_dist_0.8_settle_1",
                    "approach_sign": 1,
                    "approach_distance": 0.8,
                    "settle_steps": 1,
                    "success_count": 9,
                }
            }
        ),
        encoding="utf-8",
    )

    policy = resolve_pose_policy(initial_contact_result_path=result_path)

    assert policy["status"] == "ready"
    assert policy["source"] == str(result_path)
    assert policy["name"] == "sign_1_dist_0.8_settle_1"
    assert policy["source_success_count"] == 9


def test_load_initial_contact_result_rejects_malformed_source(tmp_path: Path) -> None:
    result_path = tmp_path / "initial_contact_result.json"
    result_path.write_text("{not-json\n", encoding="utf-8")

    with pytest.raises(
        ValueError,
        match=(
            r"grasp initial-contact result source must contain valid JSON object: "
            r".*initial_contact_result\.json"
        ),
    ):
        load_initial_contact_result(result_path)


def test_load_initial_contact_result_rejects_non_object_source(tmp_path: Path) -> None:
    result_path = tmp_path / "initial_contact_result.json"
    result_path.write_text("[]\n", encoding="utf-8")

    with pytest.raises(
        ValueError,
        match=(
            r"grasp initial-contact result source must contain a JSON object: "
            r".*initial_contact_result\.json"
        ),
    ):
        load_initial_contact_result(result_path)


def test_pose_policy_cache_generation_installs_valid_generated_npz(
    tmp_path: Path,
    monkeypatch,
) -> None:
    generated_transforms = np.zeros((2, 4, 4))
    target = tmp_path / "assets" / "grasps" / "droid" / "Bread_1" / "Bread_1_grasps_filtered.npz"
    target.parent.mkdir(parents=True)
    np.savez(target, transforms=np.zeros((0, 4, 4)))
    candidate_grasps = tmp_path / "Bread_1_grasps.json"
    candidate_grasps.write_text(
        json.dumps({"transforms": generated_transforms.tolist()}),
        encoding="utf-8",
    )

    def fake_probe_command(command, **kwargs):
        cache_output = Path(command[command.index("--cache-output") + 1])
        probe_output = Path(command[command.index("--output") + 1])
        cache_output.parent.mkdir(parents=True, exist_ok=True)
        probe_output.parent.mkdir(parents=True, exist_ok=True)
        np.savez_compressed(cache_output, transforms=generated_transforms)
        probe_output.write_text(
            json.dumps(
                {
                    "status": "ready",
                    "candidate_count": 2,
                    "variants": [
                        {
                            "name": "sign_1_dist_0.8_settle_1",
                            "success_count": 2,
                            "cache_transform_count": 2,
                        }
                    ],
                }
            ),
            encoding="utf-8",
        )
        return {"status": "ready", "returncode": 0, "stdout": "ok", "stderr": ""}

    monkeypatch.setattr(pose_cache, "run_molmospaces_probe_command", fake_probe_command)

    result = run_grasp_pose_policy_cache_generation(
        generation_preflight=_generation_preflight(tmp_path, target_npz=target),
        output_dir=tmp_path / "out",
        candidate_grasps_path=candidate_grasps,
        approach_sign=1,
        approach_distance=0.8,
        settle_steps=1,
        install=True,
        timeout_s=1,
    )

    assert result["schema"] == GRASP_POSE_POLICY_CACHE_SCHEMA
    assert result["status"] == "ready"
    assert result["successful_transform_count"] == 2
    assert result["assets"][0]["generated_valid"] is True
    assert result["assets"][0]["installed"] is True
    assert result["assets"][0]["installed_validation"]["transform_count"] == 2
    assert result["availability_after_install"]["status"] == "ready"


def test_render_grasp_pose_policy_cache_report(tmp_path: Path) -> None:
    result = {
        "schema": GRASP_POSE_POLICY_CACHE_SCHEMA,
        "status": "ready",
        "ready": True,
        "object_name": "Bread_1",
        "candidate_count": 24,
        "successful_transform_count": 9,
        "install_requested": True,
        "pose_policy": {
            "name": "sign_1_dist_0.8_settle_1",
            "source": "initial_contact_result.json",
            "approach_sign": 1,
            "approach_distance": 0.8,
            "settle_steps": 1,
            "source_success_count": 9,
        },
        "assets_symlink": {"status": "ready", "path": "assets", "target": "assets"},
        "candidate_grasps_path": "Bread_1_grasps.json",
        "object_xml": "Bread_1_mesh.xml",
        "artifact_dir": str(tmp_path),
        "probe_script_path": str(tmp_path / "probe.py"),
        "probe_output_path": str(tmp_path / "result.json"),
        "generated_npz_path": str(tmp_path / "Bread_1_grasps_filtered.npz"),
        "command": ["python", "probe.py"],
        "command_result": {"status": "ready", "returncode": 0, "stdout": "", "stderr": ""},
        "assets": [
            {
                "asset_uid": "Bread_1",
                "generated_validation": {"validation_status": "valid", "transform_count": 9},
                "installed": True,
                "installed_validation": {"validation_status": "valid", "transform_count": 9},
                "generated_npz_path": "generated.npz",
                "cache_target_path": "cache.npz",
            }
        ],
        "blockers": [],
        "blocker_count": 0,
        "evidence_note": "pose policy cache",
    }

    report_path = render_grasp_pose_policy_cache_report(output_dir=tmp_path, result=result)
    text = report_path.read_text(encoding="utf-8")

    assert "MolmoSpaces Pose Policy Grasp Cache" in text
    assert "Pose Policy" in text
    assert "sign_1_dist_0.8_settle_1" in text
    assert "Generated Cache Assets" in text


def _generation_preflight(tmp_path: Path, *, target_npz: Path) -> dict:
    working_dir = tmp_path / "molmospaces" / "molmo_spaces" / "grasp_generation"
    working_dir.mkdir(parents=True, exist_ok=True)
    return {
        "status": "ready",
        "molmospaces_python": "/tmp/molmo/.venv/bin/python",
        "working_dir": str(working_dir),
        "assets_dir": str(tmp_path / "assets"),
        "assets": [
            {
                "asset_uid": "Bread_1",
                "objects_list_entry": {"name": "Bread_1", "xml": str(tmp_path / "Bread_1.xml")},
                "generated_npz_path": str(tmp_path / "unused.npz"),
                "cache_target_resolved_path": str(target_npz),
            }
        ],
    }
