from __future__ import annotations

from pathlib import Path

import pytest

from roboclaws.household.camera_control import (
    BALANCED_REVIEW_SCENE_PROBE_LIGHTING_PROFILE,
    DEFAULT_SCENE_PROBE_LIGHTING_PROFILE,
    SCENE_LIGHT_RIG_SCHEMA,
    SCENE_PROBE_LIGHTING_PROFILES,
    SHADOW_PARITY_SCENE_PROBE_LIGHTING_PROFILE,
    scene_light_rig,
    scene_light_rig_roles,
)
from roboclaws.household.scene_camera_comparison import (
    _backend_swap_geometry_contract,
    _key_light_direction_diagnostics,
    _render_domain_contract_probe,
    _render_domain_source_diagnostics,
    _render_domain_view_triage,
    _room_wall_light_diagnostics,
    _scene_camera_lighting_profile,
)
from tests.contract.molmo_cleanup.scene_camera_comparison_support import (
    _manifest,
    _require_official_render_sources,
    _write_render_contract_probe_fixtures,
    _write_wall_proxy_image,
)


def test_scene_camera_room_wall_light_diagnostics_flag_wall_specific_delta(
    tmp_path: Path,
) -> None:
    manifest = _manifest()
    _write_wall_proxy_image(
        tmp_path / "molmospaces/camera_views/room_01_room_2.png",
        base=(120, 120, 120),
        wall_proxy=(170, 170, 170),
    )
    _write_wall_proxy_image(
        tmp_path / "isaaclab/camera_views/room_01_room_2.png",
        base=(120, 120, 120),
        wall_proxy=(70, 70, 70),
    )

    diagnostics = _room_wall_light_diagnostics(manifest, output_dir=tmp_path)

    assert diagnostics["status"] == "wall_light_or_shadow_delta"
    assert diagnostics["wall_specific_pair_count"] == 1
    assert diagnostics["pairs"][0]["classification"] == (
        "candidate_wall_proxy_darker_than_baseline"
    )
    assert diagnostics["pairs"][0]["wall_luminance_delta"] == pytest.approx(-100.0)
    assert "wall material albedo" in diagnostics["recommended_next_action"]


def test_backend_swap_geometry_contract_separates_camera_from_render_domain() -> None:
    manifest = _manifest()
    manifest["visual_diagnostics"] = {
        "schema": "scene_camera_visual_diagnostics_v1",
        "status": "computed",
        "view_count": 2,
        "mean_abs_mean_luminance_delta": 18.0,
        "mean_absolute_pixel_delta": 42.0,
        "render_domain_calibration": {
            "schema": "scene_camera_render_domain_calibration_v1",
            "status": "view_dependent_render_domain_delta",
            "recommended_next_action": (
                "A single global gain leaves large residuals; inspect per-room lights, "
                "material albedo, indirect lighting, and tone response before changing "
                "camera geometry."
            ),
        },
    }

    contract = _backend_swap_geometry_contract(manifest)

    checks = {item["check"]: item for item in contract["required_checks"]}
    assert contract["status"] == "geometry_swap_ready_render_domain_pending"
    assert contract["geometry_contract_status"] == "pass"
    assert contract["visual_residual_status"] == "render_domain_residual_high"
    assert contract["same_api_agent_swap_claim"] is True
    assert checks["same_camera_api"]["status"] == "pass"
    assert checks["same_explicit_eye_target_pose"]["max_delta_m"] == pytest.approx(0.0)
    assert checks["same_intrinsics"]["vertical_fov_deg"] == pytest.approx(45.0)
    assert checks["same_room_scale"]["status"] == "pass"
    assert checks["same_projected_geometry"]["max_pixel_delta"] == pytest.approx(0.0)
    assert "material albedo" in contract["recommended_next_action"]


def test_render_domain_source_diagnostics_cite_official_renderer_paths() -> None:
    _require_official_render_sources()
    manifest = _manifest()
    manifest["visual_diagnostics"] = {
        "render_domain_calibration": {"status": "view_dependent_render_domain_delta"},
    }

    diagnostics = _render_domain_source_diagnostics(manifest)

    refs = {item["evidence_id"]: item for item in diagnostics["source_references"]}
    assert diagnostics["status"] == "official_sources_available"
    assert diagnostics["root_cause_status"] == "render_contract_mismatch_evidence"
    assert diagnostics["available_source_reference_count"] == diagnostics["source_reference_count"]
    assert refs["mujoco_housegen_materials"]["status"] == "available"
    assert refs["mujoco_housegen_materials"]["path"] == (
        "vendors/molmospaces/molmo_spaces/housegen/builder.py"
    )
    assert "texture" in refs["mujoco_asset_texture_material_collection"]["snippet_summary"].lower()
    assert refs["isaac_preview_surface_material_conversion"]["status"] == "available"
    assert "opacity" in refs["isaac_preview_surface_material_conversion"]["snippet_summary"].lower()
    assert "shadow" in refs["isaac_default_lights_and_shadow_flags"]["claim"].lower()
    assert "material/light/texture" in diagnostics["recommended_next_action"]


def test_render_domain_view_triage_separates_geometry_from_renderer_contracts() -> None:
    manifest = _manifest()
    manifest["projection_diagnostics"] = {
        "pairs": [
            {"view_id": "room_01_room_2", "max_pixel_delta": 0.0},
            {"view_id": "view_01_bed", "max_pixel_delta": 0.0},
        ]
    }
    manifest["visual_diagnostics"] = {
        "views": [
            {
                "view_id": "room_01_room_2",
                "label": "Room 2",
                "delta": {
                    "mean_absolute_pixel_delta": 58.0,
                    "mean_luminance_delta": 36.0,
                },
            },
            {
                "view_id": "view_01_bed",
                "label": "Bed",
                "delta": {
                    "mean_absolute_pixel_delta": 72.0,
                    "mean_luminance_delta": -64.0,
                },
            },
        ]
    }
    manifest["canonical_camera_views"][1].pop("usd_prim_path", None)  # type: ignore[index,union-attr]

    triage = _render_domain_view_triage(manifest)

    rows = {item["view_id"]: item for item in triage["views"]}
    assert triage["status"] == "computed"
    assert triage["top_residual_view_id"] == "view_01_bed"
    assert triage["high_residual_view_count"] == 2
    assert rows["view_01_bed"]["geometry_status"] == "projection_pass"
    assert rows["view_01_bed"]["suspected_contract"] == ("object_material_texture_binding_contract")
    assert rows["view_01_bed"]["usd_prim_path"] == "/val_1/Geometry/bed_01"
    assert rows["room_01_room_2"]["geometry_status"] == "projection_pass"
    assert rows["room_01_room_2"]["suspected_contract"] == "room_light_wall_shadow_contract"
    assert "camera geometry separate" in triage["interpretation"]


def test_render_domain_contract_probe_reads_mjcf_and_usda_contracts(tmp_path: Path) -> None:
    manifest = _manifest()
    _write_render_contract_probe_fixtures(tmp_path, manifest)
    manifest["render_domain_view_triage"] = {
        "views": [
            {
                "view_id": "view_01_bed",
                "anchor_kind": "receptacle",
                "suspected_contract": "object_material_texture_binding_contract",
                "render_residual_class": "high_pixel_and_luminance",
                "mean_absolute_pixel_delta": 72.0,
                "abs_mean_luminance_delta": 64.0,
                "usd_prim_path": "/val_1/Geometry/bed_01",
            },
            {
                "view_id": "room_01_room_2",
                "anchor_kind": "room",
                "suspected_contract": "room_light_wall_shadow_contract",
                "render_residual_class": "high_pixel_and_luminance",
                "mean_absolute_pixel_delta": 58.0,
                "abs_mean_luminance_delta": 36.0,
                "usd_prim_path": "",
            },
        ]
    }

    probe = _render_domain_contract_probe(manifest)

    rows = {item["view_id"]: item for item in probe["views"]}
    bed = rows["view_01_bed"]
    room = rows["room_01_room_2"]
    assert probe["status"] == "computed"
    assert probe["mujoco_parse_status"] == "parsed"
    assert probe["isaac_parse_status"] == "parsed"
    assert bed["mujoco"]["materials"] == ["material_Carpet"]
    assert bed["isaac"]["materials"] == ["material_Carpet"]
    assert Path(bed["mujoco"]["texture_files"][0]).name == "Carpet.png"
    assert Path(bed["isaac"]["texture_files"][0]).name == "Carpet.png"
    assert bed["contract_delta"]["status"] == "material_texture_names_match"
    assert room["contract_delta"]["status"] == "light_or_shadow_contract_delta"
    assert room["contract_delta"]["mujoco_light_count"] == 1
    assert room["contract_delta"]["isaac_light_count"] == 2
    assert probe["isaac_shadow_disabled_prim_count"] == 1


def test_scene_camera_comparison_default_lighting_profile_contract() -> None:
    profile = DEFAULT_SCENE_PROBE_LIGHTING_PROFILE
    rig = scene_light_rig(profile)
    roles = scene_light_rig_roles(rig)

    assert profile["profile_id"] == "scene_probe_balanced_review_light_v1"
    assert rig["schema"] == SCENE_LIGHT_RIG_SCHEMA
    assert rig["frame"] == "molmospaces_scene_frame_v1"
    assert rig["key"]["enabled"] is True
    assert rig["key"]["shadow"] is True
    assert rig["key"]["direction"] == pytest.approx([-0.57735, 0.57735, -0.57735])
    assert rig["ambient"]["enabled"] is True
    assert rig["ambient"]["mujoco_headlight_ambient"] == pytest.approx([0.35, 0.35, 0.35])
    assert rig["ambient"]["mujoco_headlight_diffuse"] == pytest.approx([0.4, 0.4, 0.4])
    assert rig["ambient"]["isaac_dome_intensity"] == pytest.approx(120.0)
    assert rig["fill"]["enabled"] is False
    assert rig["authored_scene_lights_policy"] == "disabled_for_comparison"
    assert rig["backend_overrides"]["isaac"]["key_intensity"] == pytest.approx(900.0)
    assert rig["backend_overrides"]["isaac"]["existing_light_intensity_scale"] == pytest.approx(0.0)
    assert roles["key_enabled"] is True
    assert roles["ambient_enabled"] is True
    assert roles["fill_enabled"] is False


def test_scene_camera_shadow_parity_lighting_profile_is_probe_profile() -> None:
    default = DEFAULT_SCENE_PROBE_LIGHTING_PROFILE
    profile = SHADOW_PARITY_SCENE_PROBE_LIGHTING_PROFILE
    rig = scene_light_rig(profile)

    assert default["profile_id"] == "scene_probe_balanced_review_light_v1"
    assert profile["profile_id"] == "scene_probe_shadow_parity_probe_v1"
    assert rig["schema"] == SCENE_LIGHT_RIG_SCHEMA
    assert rig["key"]["shadow"] is True
    assert rig["ambient"]["isaac_dome_intensity"] == pytest.approx(12.0)
    assert rig["backend_overrides"]["isaac"]["key_intensity"] == pytest.approx(1200.0)
    assert rig["fill"]["enabled"] is False
    assert SCENE_PROBE_LIGHTING_PROFILES["shadow-parity"] is profile
    assert _scene_camera_lighting_profile("shadow-parity") == profile


def test_scene_camera_balanced_review_lighting_profile_is_default() -> None:
    default = DEFAULT_SCENE_PROBE_LIGHTING_PROFILE
    profile = BALANCED_REVIEW_SCENE_PROBE_LIGHTING_PROFILE
    rig = scene_light_rig(profile)

    assert default is profile
    assert profile["profile_id"] == "scene_probe_balanced_review_light_v1"
    assert rig["key"]["enabled"] is True
    assert rig["key"]["direction"] == pytest.approx([-0.57735, 0.57735, -0.57735])
    assert rig["fill"]["enabled"] is False
    assert SCENE_PROBE_LIGHTING_PROFILES["default"] is profile
    assert SCENE_PROBE_LIGHTING_PROFILES["balanced-review"] is profile
    assert _scene_camera_lighting_profile("default") == profile
    assert _scene_camera_lighting_profile("balanced-review") == profile


def test_scene_camera_key_light_direction_diagnostics_accepts_aligned_vectors() -> None:
    profile = dict(BALANCED_REVIEW_SCENE_PROBE_LIGHTING_PROFILE)
    render_probe = {
        "mujoco_lights": [
            {
                "dir": "-0.57735 0.57735 -0.57735",
                "dir_vector": [-0.577350269, 0.577350269, -0.577350269],
            }
        ]
    }
    isaac_lighting = {"applied_key_light_direction": [-0.577350269, 0.577350269, -0.577350269]}

    diagnostics = _key_light_direction_diagnostics(
        lighting_profile=profile,
        render_probe=render_probe,
        isaac_lighting=isaac_lighting,
    )

    assert diagnostics["status"] == "key_light_direction_aligned"
    assert diagnostics["isaac_angle_delta_deg"] == pytest.approx(0.0)
