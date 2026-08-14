from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from roboclaws.household.camera_control import (
    BALANCED_REVIEW_SCENE_PROBE_LIGHTING_PROFILE,
    SHADOW_PARITY_SCENE_PROBE_LIGHTING_PROFILE,
    scene_light_rig,
)
from roboclaws.household.scene_camera_comparison import (
    ISAAC_LANE_ID,
    MOLMOSPACES_LANE_ID,
    SCENE_CAMERA_COMPARISON_SCHEMA,
)
from roboclaws.household.scene_camera_lighting_diagnostics import (
    shadow_parity_probe as _shadow_parity_probe,
)
from roboclaws.household.scene_camera_render_diagnostics import (
    mujoco_render_contract_from_xml as _mujoco_render_contract_from_xml,
)
from roboclaws.household.scene_camera_report import render_scene_camera_comparison_report
from roboclaws.household.scene_camera_results import (
    contact_sheet_entries as _contact_sheet_entries,
)
from tests.contract.molmo_cleanup.scene_camera_comparison_support import (
    REPO_ROOT,
    _assert_scene_camera_report_artifacts,
    _manifest,
    _write_image,
    _write_render_contract_probe_fixtures,
    _write_scene_camera_comparison_fixture_images,
)


def test_scene_camera_comparison_report_is_render_only_and_side_by_side(tmp_path: Path) -> None:
    manifest = _manifest()
    manifest["lane_registry"] = {  # type: ignore[index]
        "baseline": MOLMOSPACES_LANE_ID,
        "candidates": [ISAAC_LANE_ID],
    }
    _write_render_contract_probe_fixtures(tmp_path, manifest)
    _write_scene_camera_comparison_fixture_images(tmp_path, manifest)

    report_path = render_scene_camera_comparison_report(manifest, output_dir=tmp_path)
    html = report_path.read_text(encoding="utf-8")

    _assert_scene_camera_report_artifacts(report_path, tmp_path, manifest)
    assert "Render-only scene identity probe" in html
    assert "Contact Sheet" in html
    assert "contact_sheet.png" in html
    assert "Comparison Manifest" in html
    assert "scene_camera_visual_diagnostics_v1" in html
    assert "scene_camera_render_domain_contract_probe_v1" in html
    assert "Pick up" not in html
    assert manifest["lighting_tone_provenance"]["status"] == (  # type: ignore[index]
        "environment_light_configured"
    )
    assert manifest["lanes"][ISAAC_LANE_ID]["lighting_diagnostics"][  # type: ignore[index]
        "added_light_paths"
    ] == ["/RoboclawsSmokeDomeLight", "/RoboclawsSmokeKeyLight"]


def test_scene_camera_contact_sheet_entries_require_existing_lane_images(tmp_path: Path) -> None:
    manifest = _manifest()
    _write_image(
        tmp_path / "molmospaces/camera_views/room_01_room_2.png",
        color=(20, 80, 120),
    )
    _write_image(
        tmp_path / "isaaclab/camera_views/room_01_room_2.png",
        color=(100, 120, 140),
    )

    entries = _contact_sheet_entries(manifest, output_dir=tmp_path)

    assert [entry["view_id"] for entry in entries] == ["room_01_room_2"]
    assert set(entries[0]["images"]) == {MOLMOSPACES_LANE_ID, ISAAC_LANE_ID}


def test_scene_camera_comparison_manifest_is_json_serializable() -> None:
    encoded = json.dumps(_manifest(), sort_keys=True)

    assert SCENE_CAMERA_COMPARISON_SCHEMA in encoded
    assert "private_manifest" not in encoded
    assert "_state" not in encoded


def test_scene_camera_mujoco_render_contract_reports_light_direction(tmp_path: Path) -> None:
    scene_xml = tmp_path / "scene.xml"
    scene_xml.write_text(
        """
<mujoco>
  <worldbody>
    <light pos="1 -1 1.5" dir="-0.57735 0.57735 -0.57735"
           directional="true" diffuse="0.5 0.5 0.5" />
  </worldbody>
</mujoco>
""",
        encoding="utf-8",
    )

    contract = _mujoco_render_contract_from_xml(str(scene_xml))

    assert contract["status"] == "parsed"
    assert contract["lights"][0]["dir_vector"] == pytest.approx(
        [-0.577350269, 0.577350269, -0.577350269]
    )


def test_scene_camera_balanced_review_profile_reports_default_fill_profile_status() -> None:
    manifest = _manifest()
    profile = dict(BALANCED_REVIEW_SCENE_PROBE_LIGHTING_PROFILE)
    rig = scene_light_rig(profile)
    manifest["camera_control"]["lighting_profile"] = profile  # type: ignore[index]
    manifest["lanes"][ISAAC_LANE_ID]["lighting_diagnostics"].update(  # type: ignore[index]
        {
            "requested_dome_intensity": rig["ambient"]["isaac_dome_intensity"],
            "requested_key_intensity": rig["backend_overrides"]["isaac"]["key_intensity"],
            "existing_light_intensity_scale": rig["backend_overrides"]["isaac"][
                "existing_light_intensity_scale"
            ],
            "applied_key_light_direction": rig["key"]["direction"],
            "added_light_paths": ["/RoboclawsSmokeDomeLight", "/RoboclawsSmokeKeyLight"],
        }
    )
    manifest["candidate_visual_diagnostics"] = {
        "status": "computed",
        "degraded_candidates": [],
        "candidates": [],
    }
    manifest["render_domain_contract_probe"] = {
        "status": "computed",
        "high_priority_delta_count": 0,
        "mujoco_light_count": 1,
        "mujoco_lights": [
            {
                "dir": "-0.57735 0.57735 -0.57735",
                "dir_vector": [-0.577350269, 0.577350269, -0.577350269],
            }
        ],
        "isaac_light_count": 2,
        "isaac_shadow_disabled_prim_count": 18,
    }

    diagnostics = _shadow_parity_probe(manifest)

    assert diagnostics["status"] == "default_fill_profile_not_shadow_parity"
    assert diagnostics["is_shadow_capable_profile"] is False
    assert diagnostics["comparison_successful"] is True
    assert "lighting_profile=shadow-parity" in diagnostics["recommended_next_action"]


def test_scene_camera_shadow_parity_probe_reports_shadow_configuration(tmp_path: Path) -> None:
    manifest = _manifest()
    profile = dict(SHADOW_PARITY_SCENE_PROBE_LIGHTING_PROFILE)
    rig = scene_light_rig(profile)
    manifest["camera_control"]["lighting_profile"] = profile  # type: ignore[index]
    manifest["scene"]["lighting_profile_id"] = profile["profile_id"]  # type: ignore[index]
    manifest["lanes"][ISAAC_LANE_ID]["lighting_profile"] = profile  # type: ignore[index]
    manifest["lanes"][ISAAC_LANE_ID]["lighting_diagnostics"].update(  # type: ignore[index]
        {
            "requested_dome_intensity": rig["ambient"]["isaac_dome_intensity"],
            "requested_key_intensity": rig["backend_overrides"]["isaac"]["key_intensity"],
            "existing_light_intensity_scale": rig["backend_overrides"]["isaac"][
                "existing_light_intensity_scale"
            ],
            "applied_key_light_direction": rig["key"]["direction"],
            "added_light_paths": ["/RoboclawsSmokeDomeLight", "/RoboclawsSmokeKeyLight"],
        }
    )
    manifest["lane_registry"] = {  # type: ignore[index]
        "baseline": MOLMOSPACES_LANE_ID,
        "candidates": [ISAAC_LANE_ID],
    }
    manifest["render_domain_contract_probe"] = {
        "status": "computed",
        "high_priority_delta_count": 0,
        "mujoco_light_count": 1,
        "mujoco_lights": [
            {
                "dir": "-0.57735 0.57735 -0.57735",
                "dir_vector": [-0.577350269, 0.577350269, -0.577350269],
            }
        ],
        "isaac_light_count": 2,
        "isaac_shadow_disabled_prim_count": 18,
    }
    for lane in manifest["lanes"].values():  # type: ignore[index,union-attr]
        for image in lane["images"].values():  # type: ignore[index,union-attr]
            _write_image(tmp_path / str(image["path"]), color=(120, 120, 120))  # type: ignore[index]

    diagnostics = _shadow_parity_probe(manifest)
    manifest["shadow_parity_probe"] = diagnostics
    report = render_scene_camera_comparison_report(manifest, output_dir=tmp_path)
    html = report.read_text(encoding="utf-8")

    assert diagnostics["status"] == "shadow_parity_probe_configured"
    assert diagnostics["isaac_dome_intensity"] == pytest.approx(12.0)
    assert diagnostics["isaac_key_intensity"] == pytest.approx(1200.0)
    assert diagnostics["isaac_shadow_disabled_prim_count"] == 18
    assert diagnostics["comparison_successful"] is True
    assert diagnostics["key_light_direction"]["status"] == "key_light_direction_aligned"  # type: ignore[index]
    assert diagnostics["render_contract_high_priority_delta_count"] == 0
    assert "shadow_parity_probe" in html
    assert "scene_probe_shadow_parity_probe_v1" in html
    assert "shadow_parity_probe_configured" in html
    assert "key_light_direction_aligned" in html
    assert "Review bed/object views for cast-shadow return" in html


def test_scene_camera_shadow_parity_probe_reports_visual_gate_failure() -> None:
    manifest = _manifest()
    profile = dict(SHADOW_PARITY_SCENE_PROBE_LIGHTING_PROFILE)
    rig = scene_light_rig(profile)
    manifest["camera_control"]["lighting_profile"] = profile  # type: ignore[index]
    manifest["lanes"][ISAAC_LANE_ID]["lighting_diagnostics"].update(  # type: ignore[index]
        {
            "requested_dome_intensity": rig["ambient"]["isaac_dome_intensity"],
            "requested_key_intensity": rig["backend_overrides"]["isaac"]["key_intensity"],
            "added_light_paths": ["/RoboclawsSmokeDomeLight", "/RoboclawsSmokeKeyLight"],
        }
    )
    manifest["candidate_visual_diagnostics"] = {
        "status": "degraded_visual_fidelity",
        "degraded_candidates": [ISAAC_LANE_ID],
        "candidates": [
            {
                "candidate": ISAAC_LANE_ID,
                "warning_reasons": ["mean_absolute_pixel_delta_above_warning_threshold"],
            }
        ],
    }
    manifest["render_domain_contract_probe"] = {
        "status": "computed",
        "high_priority_delta_count": 1,
        "mujoco_light_count": 1,
        "isaac_light_count": 2,
        "isaac_shadow_disabled_prim_count": 18,
    }

    diagnostics = _shadow_parity_probe(manifest)

    assert diagnostics["status"] == "shadow_parity_probe_configured"
    assert diagnostics["comparison_successful"] is False
    assert diagnostics["candidate_visual_status"] == "degraded_visual_fidelity"
    assert diagnostics["candidate_visual_degraded_candidates"] == [ISAAC_LANE_ID]
    assert diagnostics["candidate_visual_warning_reasons"] == [
        "mean_absolute_pixel_delta_above_warning_threshold"
    ]
    assert diagnostics["render_contract_high_priority_delta_count"] == 1
    assert "do not promote it as the default" in diagnostics["recommended_next_action"]


def test_scene_camera_comparison_cli_rejects_non_positive_render_dimensions(
    tmp_path: Path,
) -> None:
    completed = subprocess.run(
        [
            sys.executable,
            "-m",
            "roboclaws.household.scene_camera_comparison",
            "--scene-usd-path",
            str(tmp_path / "missing.usda"),
            "--output-dir",
            str(tmp_path),
            "--render-width",
            "0",
        ],
        check=False,
        capture_output=True,
        text=True,
        cwd=REPO_ROOT,
    )

    assert completed.returncode == 2
    assert "expected a positive integer" in completed.stderr

    completed = subprocess.run(
        [
            sys.executable,
            "-m",
            "roboclaws.household.scene_camera_comparison",
            "--scene-usd-path",
            str(tmp_path / "missing.usda"),
            "--output-dir",
            str(tmp_path),
            "--render-height",
            "-1",
        ],
        check=False,
        capture_output=True,
        text=True,
        cwd=REPO_ROOT,
    )

    assert completed.returncode == 2
    assert "expected a positive integer" in completed.stderr


def test_scene_camera_comparison_recipe_checks_prepared_usd_before_running(tmp_path: Path) -> None:
    molmo_python = tmp_path / "molmo-python"
    isaac_python = tmp_path / "isaac-python"
    missing_usd = tmp_path / "missing.usda"
    for runtime in (molmo_python, isaac_python):
        runtime.write_text("#!/usr/bin/env sh\nexit 0\n", encoding="utf-8")
        runtime.chmod(0o755)

    env = os.environ.copy()
    env.pop("ROBOCLAWS_JUST_TRACE", None)
    env["ROBOCLAWS_MOLMOSPACES_PYTHON"] = str(molmo_python)
    env["ROBOCLAWS_ISAACLAB_PYTHON"] = str(isaac_python)
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "roboclaws.household.scene_camera_comparison",
            "--seed",
            "7",
            "--generated-mess-count",
            "1",
            "--output-dir",
            "output/molmo/scene-camera-comparison",
            "--scene-source",
            "procthor-10k-val",
            "--scene-index",
            "1",
            "--scene-usd-path",
            str(missing_usd),
        ],
        cwd=REPO_ROOT,
        env=env,
        check=False,
        capture_output=True,
        text=True,
    )

    assert result.returncode != 0
    assert "missing prepared scene USD" in result.stderr
    assert str(missing_usd) in result.stderr


def test_scene_camera_comparison_recipe_requires_explicit_eula_acceptance(tmp_path: Path) -> None:
    molmo_python = tmp_path / "molmo-python"
    isaac_python = tmp_path / "isaac-python"
    scene_usd = tmp_path / "scene.usda"
    scene_usd.write_text("#usda 1.0\n", encoding="utf-8")
    for runtime in (molmo_python, isaac_python):
        runtime.write_text("#!/usr/bin/env sh\nexit 0\n", encoding="utf-8")
        runtime.chmod(0o755)

    env = os.environ.copy()
    env.pop("OMNI_KIT_ACCEPT_EULA", None)
    env["ROBOCLAWS_MOLMOSPACES_PYTHON"] = str(molmo_python)
    env["ROBOCLAWS_ISAACLAB_PYTHON"] = str(isaac_python)
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "roboclaws.household.scene_camera_comparison",
            "--scene-usd-path",
            str(scene_usd),
        ],
        cwd=REPO_ROOT,
        env=env,
        check=False,
        capture_output=True,
        text=True,
    )

    assert result.returncode != 0
    assert "requires NVIDIA Omniverse EULA acceptance" in result.stderr
    assert "OMNI_KIT_ACCEPT_EULA=YES" in result.stderr
