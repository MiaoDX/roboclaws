from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest
from PIL import Image

from roboclaws.household.camera_control import (
    BALANCED_REVIEW_SCENE_PROBE_LIGHTING_PROFILE,
    CAMERA_CONTROL_API_NAME,
    DEFAULT_SCENE_PROBE_COLOR_PROFILE,
    DEFAULT_SCENE_PROBE_LIGHTING_PROFILE,
    SCENE_LIGHT_RIG_SCHEMA,
    SCENE_PROBE_LIGHTING_PROFILES,
    SHADOW_PARITY_SCENE_PROBE_LIGHTING_PROFILE,
    scene_light_rig,
    scene_light_rig_roles,
    scene_probe_camera_control_request,
)
from roboclaws.household.scene_camera_comparison import (
    ISAAC_LANE_ID,
    MOLMOSPACES_LANE_ID,
    SCENE_CAMERA_COMPARISON_SCHEMA,
    _backend_swap_geometry_contract,
    _candidate_color_calibrations,
    _canonical_camera_control_views,
    _contact_sheet_entries,
    _image_pair_visual_delta,
    _image_visual_metrics,
    _isaac_view_specs,
    _key_light_direction_diagnostics,
    _molmospaces_view_specs,
    _mujoco_render_contract_from_xml,
    _native_isaac_render_diagnostics,
    _normalize_color_profile_for_replay,
    _offline_color_profile_replay,
    _render_domain_calibration,
    _render_domain_contract_probe,
    _render_domain_source_diagnostics,
    _render_domain_view_triage,
    _room_camera_control_views,
    _room_wall_light_diagnostics,
    _scene_camera_lighting_profile,
    _shadow_parity_probe,
    render_scene_camera_comparison_report,
)
from roboclaws.household.scene_camera_geometry_contract import (
    camera_intrinsics_contract_from_capture,
    camera_pose_contract_from_capture,
    projection_diagnostics,
    room_scale_contract_from_scene_capture,
    scene_frame_transform_from_capture,
)

REPO_ROOT = Path(__file__).resolve().parents[3]
MOLMO_JUST = REPO_ROOT / "just" / "molmo.just"


def just_bin() -> str:
    path = shutil.which("just")
    if path:
        return path
    local_path = Path.home() / ".local/bin" / "just"
    if local_path.exists():
        return str(local_path)
    pytest.skip("just binary is not available")


def _require_official_render_sources() -> None:
    missing = [
        reference["path"]
        for reference in _render_domain_source_diagnostics(_manifest())["source_references"]
        if reference["status"] != "available"
    ]
    if missing:
        pytest.skip("MolmoSpaces official renderer source refs unavailable: " + ", ".join(missing))


def _write_image(path: Path, color: tuple[int, int, int]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    Image.new("RGB", (64, 48), color=color).save(path)


def _write_wall_proxy_image(
    path: Path,
    *,
    base: tuple[int, int, int],
    wall_proxy: tuple[int, int, int],
) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    image = Image.new("RGB", (100, 100), color=base)
    for x in range(30, 70):
        for y in range(8, 42):
            image.putpixel((x, y), wall_proxy)
    image.save(path)


def _visual_metric_pair(
    view_id: str,
    *,
    molmo_luminance: float,
    isaac_luminance: float,
) -> dict[str, object]:
    return {
        "view_id": view_id,
        "lanes": {
            MOLMOSPACES_LANE_ID: {"mean_luminance": molmo_luminance},
            ISAAC_LANE_ID: {"mean_luminance": isaac_luminance},
        },
    }


def _write_render_contract_probe_fixtures(
    tmp_path: Path,
    manifest: dict[str, object],
) -> None:
    xml_path = tmp_path / "scene.xml"
    xml_path.write_text(
        """
<mujoco>
  <asset>
    <texture type="2d" name="CarpetTex" file="textures/Carpet.png" />
    <material name="material_Carpet" texture="CarpetTex" rgba="1 0.8 0.6 1" />
  </asset>
  <worldbody>
    <light pos="1 -1 1.5" directional="true" diffuse="0.5 0.5 0.5" />
    <body name="bed_01">
      <geom name="bed_01_visual_0" class="__VISUAL_MJT__" type="mesh"
            material="material_Carpet" mesh="BedMesh" />
    </body>
  </worldbody>
</mujoco>
""",
        encoding="utf-8",
    )
    usd_path = tmp_path / "scene.usda"
    usd_path.write_text(
        """
#usda 1.0
def Xform "val_1"
{
  def Scope "Geometry"
  {
    def Xform "bed_01"
    {
      def Scope "Geometry"
      {
        def Mesh "BedMesh"
        {
          rel material:binding = </val_1/Geometry/bed_01/Materials/material_Carpet>
        }
      }
      def Scope "Materials"
      {
        def Material "material_Carpet"
        {
          token outputs:surface.connect =
              </val_1/Geometry/bed_01/Materials/material_Carpet/PreviewSurface.outputs:surface>
          def Shader "PreviewSurface"
          {
            uniform token info:id = "UsdPreviewSurface"
            color3f inputs:diffuseColor.connect =
                </val_1/Geometry/bed_01/Materials/material_Carpet/DiffuseTexture.outputs:rgb>
          }
          def Shader "DiffuseTexture"
          {
            asset inputs:file = @textures/Carpet.png@
          }
        }
      }
    }
    def Mesh "wall_01"
    {
      bool primvars:doNotCastShadows = 1
    }
  }
  def DomeLight "scene_skybox_light"
  {
    float inputs:intensity = 2000
  }
  def DistantLight "scene_dir_light"
  {
    float inputs:intensity = 500
  }
}
""",
        encoding="utf-8",
    )
    manifest["lanes"][MOLMOSPACES_LANE_ID]["scene_xml"] = str(xml_path)  # type: ignore[index]
    manifest["lanes"][ISAAC_LANE_ID]["scene_usd"] = str(usd_path)  # type: ignore[index]
    manifest["canonical_camera_views"][1]["anchor_id"] = "bed_01"  # type: ignore[index]
    manifest["canonical_camera_views"][1]["usd_prim_path"] = "/val_1/Geometry/bed_01"  # type: ignore[index]
    manifest["lanes"][ISAAC_LANE_ID]["views"][1]["anchor_id"] = "bed_01"  # type: ignore[index]
    manifest["lanes"][ISAAC_LANE_ID]["views"][1]["usd_prim_path"] = (  # type: ignore[index]
        "/val_1/Geometry/bed_01"
    )


def _native_isaac_diagnostics() -> dict[str, object]:
    return {
        "schema": "isaac_native_render_diagnostics_v1",
        "status": "captured",
        "renderer_mode": "RayTracedLighting",
        "capture_method": "isaac_scene_camera_rgb",
        "view_kind": "scene_camera",
        "settings_api_available": True,
        "available_setting_count": 3,
        "missing_setting_count": 1,
        "camera_prim_paths": ["/World/scene_camera"],
        "render_product_paths": ["/Render/Products/scene_camera"],
        "render_resolution": {"width": 960, "height": 640},
        "isaac_lab_isp_active": False,
        "default_render_settings_changed": False,
        "post_render_comparison_profile": {
            "applied": True,
            "profile_id": "display_srgb_soft_highlight_v1",
            "source": "not_a_native_renderer_setting",
        },
        "tone_mapping": {
            "operator": {
                "status": "available",
                "value": "ACES",
                "setting_path": "/rtx/post/tonemap/op",
            },
        },
        "camera_exposure": {
            "auto_exposure_enabled": {
                "status": "available",
                "value": False,
                "setting_path": "/rtx/post/tonemap/autoExposure/enabled",
            },
        },
        "renderer": {
            "mode": {
                "status": "available",
                "value": "RayTracedLighting",
                "setting_path": "/rtx/rendermode",
            },
        },
    }


def _manifest() -> dict[str, object]:
    return {
        "schema": SCENE_CAMERA_COMPARISON_SCHEMA,
        "purpose": (
            "Render-only scene identity probe. This does not execute household cleanup, "
            "pick, place, or scoring."
        ),
        "frame_mapping_note": (
            "MuJoCo and prepared Isaac USD expose different world frames for this scene. "
            "Views are matched by MolmoSpaces metadata handles and category anchors, then "
            "rendered through one Roboclaws camera-control request using the same anchor "
            "lens, lighting profile, color profile, and view ids."
        ),
        "camera_control": {
            "api_name": CAMERA_CONTROL_API_NAME,
            "camera_model": "canonical_eye_target_camera_v1",
            "coordinate_frame": "molmospaces_scene_frame_v1",
            "lens": {
                "vertical_fov_deg": 45.0,
                "focal_length_mm": 24.0,
            },
            "lighting_profile": dict(DEFAULT_SCENE_PROBE_LIGHTING_PROFILE),
            "color_profile": {
                "profile_id": "display_srgb_soft_highlight_v1",
                "highlight_knee": 225.0,
                "highlight_compression": 0.55,
            },
            "calibration_status": "canonical_scene_frame_similarity_fit_v1",
            "calibration_note": (
                "One Roboclaws camera-control request carries explicit eye/target/up poses."
            ),
            "request_artifact": "camera_control_request.json",
            "view_count": 2,
            "same_pose_contract": True,
        },
        "official_molmospaces_source": {
            "package": "molmo-spaces",
            "status": "installed",
            "url": "https://github.com/allenai/molmospaces.git",
            "vcs": "git",
            "commit_id": "3c50ae6093f7e4a4ef32529f8a773715da410a2f",
            "requested_revision": "3c50ae6093f7e4a4ef32529f8a773715da410a2f",
        },
        "artifacts": {
            "comparison_manifest": "comparison_manifest.json",
            "report": "report.html",
        },
        "scene_frame_transform": {
            "schema": "molmospaces_to_isaac_scene_transform_v1",
            "source_frame": "molmospaces_scene_frame_v1",
            "target_frame": "isaac_prepared_usd_world_frame",
            "diagnostic_kind": "camera_target_vs_isaac_usd_bounds",
            "status": "identity_checked_against_usd_bounds",
            "parity_status": "target_matches_usd_bounds_within_threshold",
            "target_residual_status": "target_matches_usd_bounds_within_threshold",
            "interpretation": "Target/geometry residual diagnostic, not camera pose residual.",
            "pair_count": 2,
            "xy_scale": 1.0,
            "rotation_z_deg": 0.0,
            "translation": [0.0, 0.0, 0.0],
            "residual_threshold_m": 0.08,
            "mean_residual_m": 0.03,
            "max_residual_m": 0.04,
            "mean_xy_residual_m": 0.02,
            "max_xy_residual_m": 0.022,
            "mean_z_residual_m": 0.0,
            "max_z_residual_m": 0.0,
            "pairs": [
                {
                    "anchor_id": "bed_01",
                    "category": "Bed",
                    "source": [2.8, 9.0, 0.8],
                    "target": [2.82, 9.01, 0.8],
                    "fitted": [2.8, 9.0, 0.8],
                    "residual_m": 0.022,
                    "xy_residual_m": 0.022,
                    "z_residual_m": 0.0,
                }
            ],
        },
        "camera_pose_contract": {
            "schema": "canonical_camera_pose_contract_v1",
            "camera_model": "canonical_eye_target_camera_v1",
            "coordinate_frame": "molmospaces_scene_frame_v1",
            "status": "same_backend_pose_within_threshold",
            "pair_count": 2,
            "pose_threshold_m": 0.005,
            "max_pose_delta_m": 0.0,
            "interpretation": "Backends reported the requested eye/target pose.",
            "pairs": [
                {
                    "view_id": "view_01_bed",
                    "anchor_id": "bed_01",
                    "category": "Bed",
                    "requested_eye": [0.2, 6.4, 2.6],
                    "requested_target": [2.8, 9.0, 0.8],
                    "molmospaces_backend_eye": [0.2, 6.4, 2.6],
                    "molmospaces_backend_target": [2.8, 9.0, 0.8],
                    "isaac_backend_eye": [0.2, 6.4, 2.6],
                    "isaac_backend_target": [2.8, 9.0, 0.8],
                    "backend_eye_delta_m": 0.0,
                    "backend_target_delta_m": 0.0,
                }
            ],
        },
        "camera_intrinsics_contract": {
            "schema": "canonical_camera_intrinsics_contract_v1",
            "status": "intrinsics_consistent",
            "camera_model": "canonical_eye_target_camera_v1",
            "resolution": {"width": 960, "height": 640},
            "requested_lens": {
                "vertical_fov_deg": 45.0,
                "focal_length_mm": 24.0,
            },
            "molmospaces_lens": {
                "vertical_fov_deg": 45.0,
                "focal_length_mm": 24.0,
            },
            "isaac_lens": {
                "vertical_fov_deg": 45.0,
                "focal_length_mm": 24.0,
            },
            "isaac_derived_lens": {
                "focal_length_mm": 24.0,
                "horizontal_aperture_mm": 29.82337649086285,
            },
            "intrinsics_precedence": "vertical_fov_deg",
            "derived_from_vertical_fov": {
                "horizontal_aperture_mm": 29.82337649086285,
                "horizontal_fov_deg": 63.707,
            },
            "requested_vs_derived_horizontal_aperture_delta_mm": None,
            "interpretation": "The scene probe treats vertical_fov_deg as canonical.",
        },
        "projection_diagnostics": {
            "schema": "canonical_cameraprojection_diagnostics_v1",
            "status": "same_projected_geometry_within_threshold",
            "projection_threshold_px": 0.5,
            "resolution": {"width": 960, "height": 640},
            "vertical_fov_deg": 45.0,
            "pair_count": 1,
            "max_pixel_delta": 0.0,
            "interpretation": "Projection geometry check.",
            "pairs": [
                {
                    "view_id": "view_01_bed",
                    "anchor_id": "bed_01",
                    "category": "Bed",
                    "point_count": 1,
                    "max_pixel_delta": 0.0,
                    "all_points_inside_frame": True,
                    "points": [
                        {
                            "label": "camera_target",
                            "world": [2.8, 9.0, 0.8],
                            "molmospaces_pixel": [480.0, 320.0],
                            "isaac_pixel": [480.0, 320.0],
                            "pixel_delta": 0.0,
                            "depth_m": 4.0,
                            "inside_frame": True,
                        }
                    ],
                }
            ],
        },
        "room_scale_contract": {
            "schema": "room_scale_contract_v1",
            "status": "same_room_outlines_within_threshold",
            "room_count": 1,
            "matched_room_outline_count": 1,
            "room_outline_source": "molmospaces_room_outlines",
            "isaac_scene_bounds": {
                "size": [9.976, 10.097, 3.154],
                "center": [4.983, 5.043, 1.475],
            },
            "max_room_to_scene_width_ratio": 0.599,
            "max_room_to_scene_depth_ratio": 0.987,
            "max_room_outline_center_delta_m": 0.0,
            "max_room_outline_size_delta_m": 0.0,
            "max_room_outline_half_extent_delta_m": 0.0,
            "room_outline_threshold_m": 0.005,
            "interpretation": "Room-level camera poses are derived from room mesh world bounds.",
            "rooms": [
                {
                    "view_id": "room_01_room_2",
                    "room_id": "room_2",
                    "center": [2.99, 4.983],
                    "size": [5.98, 9.966],
                    "half_extents": [2.99, 4.983],
                    "provenance": "mujoco_room_mesh_world_bounds",
                }
            ],
        },
        "scene": {
            "scene_source": "procthor-10k-val",
            "scene_index": 1,
            "seed": 7,
            "generated_mess_count": 1,
            "scene_usd_path": "/tmp/scene_semantic.usda",
            "render_width": 960,
            "render_height": 640,
        },
        "canonical_camera_views": [
            {
                "view_id": "room_01_room_2",
                "anchor_id": "room_2",
                "anchor_kind": "room",
                "category": "Room",
                "room_id": "room_2",
                "camera_basis": "room_center_inset_eye_target",
            },
            {
                "view_id": "view_01_bed",
                "anchor_id": "bed_01",
                "anchor_kind": "receptacle",
                "category": "Bed",
                "room_id": "room_2",
                "camera_basis": "near_topdown_anchor_orbit",
            },
            {
                "view_id": "view_02_sink",
                "anchor_id": "sink_01",
                "anchor_kind": "receptacle",
                "category": "Sink",
                "room_id": "room_3",
                "camera_basis": "near_topdown_anchor_orbit",
            },
        ],
        "room_camera_views": [
            {
                "view_id": "room_01_room_2",
                "anchor_id": "room_2",
                "anchor_kind": "room",
                "category": "Room",
                "room_id": "room_2",
                "camera_basis": "room_center_inset_eye_target",
                "room_outline": {
                    "center": [2.99, 4.983],
                    "half_extents": [2.99, 4.983],
                    "provenance": "mujoco_room_mesh_world_bounds",
                },
            }
        ],
        "anchors": [
            {
                "anchor_id": "bed_01",
                "anchor_kind": "receptacle",
                "category": "Bed",
                "room_id": "room_2",
                "molmospaces_position": [2.8, 9.0, 0.8],
                "room_center_xy": [2.7, 4.5],
                "isaac_support_position": [2.8, 9.0, 0.8],
                "isaac_usd_prim_path": "/val_1/Geometry/bed_01",
                "isaac_target_source": "Canonical explicit target",
            },
            {
                "anchor_id": "sink_01",
                "anchor_kind": "receptacle",
                "category": "Sink",
                "room_id": "room_3",
                "molmospaces_position": [9.6, 1.8, 0.5],
                "room_center_xy": [8.0, 3.0],
                "isaac_support_position": [9.6, 1.8, 0.5],
                "isaac_usd_prim_path": "/val_1/Geometry/sink_01",
                "isaac_target_source": "Canonical explicit target",
            },
        ],
        "lanes": {
            MOLMOSPACES_LANE_ID: {
                "status": "success",
                "python_executable": ".venv/bin/python",
                "runtime": {"python_version": "3.12.9", "mujoco_version": "3.3.0"},
                "scene_xml": "/tmp/val_1.xml",
                "visual_artifact_provenance": "mujoco_camera_control_canonical_eye_target",
                "camera_control_api": CAMERA_CONTROL_API_NAME,
                "calibration_status": "canonical_scene_frame_similarity_fit_v1",
                "lighting_profile": dict(DEFAULT_SCENE_PROBE_LIGHTING_PROFILE),
                "color_profile": {"profile_id": "display_srgb_soft_highlight_v1"},
                "images": {
                    "room_01_room_2": {
                        "path": "molmospaces/camera_views/room_01_room_2.png",
                        "dimensions": {"width": 64, "height": 48, "channels": 3},
                    },
                    "view_01_bed": {
                        "path": "molmospaces/camera_views/view_01_bed.png",
                        "dimensions": {"width": 64, "height": 48, "channels": 3},
                    },
                    "view_02_sink": {
                        "path": "molmospaces/camera_views/view_02_sink.png",
                        "dimensions": {"width": 64, "height": 48, "channels": 3},
                    },
                },
                "views": [
                    {
                        "view_id": "room_01_room_2",
                        "eye": [1.0, 2.0, 1.45],
                        "target": [2.0, 3.0, 1.45],
                        "backend_eye": [1.0, 2.0, 1.45],
                        "backend_target": [2.0, 3.0, 1.45],
                    },
                    {
                        "view_id": "view_01_bed",
                        "eye": [0.2, 6.4, 2.6],
                        "target": [2.8, 9.0, 0.8],
                        "backend_eye": [0.2, 6.4, 2.6],
                        "backend_target": [2.8, 9.0, 0.8],
                    },
                    {
                        "view_id": "view_02_sink",
                        "eye": [7.0, -1.4, 2.6],
                        "target": [9.6, 1.8, 0.6],
                        "backend_eye": [7.0, -1.4, 2.6],
                        "backend_target": [9.6, 1.8, 0.6],
                    },
                ],
            },
            ISAAC_LANE_ID: {
                "status": "success",
                "python_executable": ".venv-isaaclab/bin/python",
                "runtime": {"python_version": "3.12.9", "isaac_lab_version": "2.2.0"},
                "scene_usd": "/tmp/scene_semantic.usda",
                "visual_artifact_provenance": (
                    "isaac_lab_camera_rgb_canonical_eye_target_scene_probe"
                ),
                "camera_control_api": CAMERA_CONTROL_API_NAME,
                "calibration_status": "canonical_scene_frame_similarity_fit_v1",
                "lighting_profile": dict(DEFAULT_SCENE_PROBE_LIGHTING_PROFILE),
                "color_profile": {"profile_id": "display_srgb_soft_highlight_v1"},
                "lighting_diagnostics": {
                    "status": "added_capture_lights",
                    "scene_light_rig": scene_light_rig(DEFAULT_SCENE_PROBE_LIGHTING_PROFILE),
                    "scene_light_rig_schema": SCENE_LIGHT_RIG_SCHEMA,
                    "scene_light_rig_roles": scene_light_rig_roles(
                        scene_light_rig(DEFAULT_SCENE_PROBE_LIGHTING_PROFILE)
                    ),
                    "authored_scene_lights_policy": "disabled_for_comparison",
                    "existing_light_count": 2,
                    "existing_light_intensity_scale": 0.0,
                    "added_light_count": 2,
                    "added_light_paths": [
                        "/RoboclawsSmokeDomeLight",
                        "/RoboclawsSmokeKeyLight",
                    ],
                    "requested_dome_intensity": 120.0,
                    "requested_key_intensity": 900.0,
                    "applied_key_light_direction": [-0.57735, 0.57735, -0.57735],
                },
                "native_render_diagnostics": _native_isaac_diagnostics(),
                "images": {
                    "room_01_room_2": {
                        "path": "isaaclab/camera_views/room_01_room_2.png",
                        "dimensions": {"width": 64, "height": 48, "channels": 3},
                    },
                    "view_01_bed": {
                        "path": "isaaclab/camera_views/view_01_bed.png",
                        "dimensions": {"width": 64, "height": 48, "channels": 3},
                    },
                    "view_02_sink": {
                        "path": "isaaclab/camera_views/view_02_sink.png",
                        "dimensions": {"width": 64, "height": 48, "channels": 3},
                    },
                },
                "views": [
                    {
                        "view_id": "room_01_room_2",
                        "eye": [1.0, 2.0, 1.45],
                        "target": [2.0, 3.0, 1.45],
                        "backend_eye": [1.0, 2.0, 1.45],
                        "backend_target": [2.0, 3.0, 1.45],
                    },
                    {
                        "view_id": "view_01_bed",
                        "eye": [0.2, 6.4, 2.6],
                        "target": [2.8, 9.0, 0.8],
                        "backend_eye": [0.2, 6.4, 2.6],
                        "backend_target": [2.8, 9.0, 0.8],
                    },
                    {
                        "view_id": "view_02_sink",
                        "eye": [7.0, -1.4, 2.6],
                        "target": [9.6, 1.8, 0.6],
                        "backend_eye": [7.0, -1.4, 2.6],
                        "backend_target": [9.6, 1.8, 0.6],
                    },
                ],
            },
        },
        "view_specs": {
            "room-level-canonical": [],
            MOLMOSPACES_LANE_ID: [],
            ISAAC_LANE_ID: [],
        },
    }


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


def _write_scene_camera_comparison_fixture_images(
    tmp_path: Path,
    manifest: dict[str, object],
) -> None:
    for lane in manifest["lanes"].values():  # type: ignore[index,union-attr]
        for image in lane["images"].values():  # type: ignore[index,union-attr]
            path = str(image["path"])  # type: ignore[index]
            _write_image(tmp_path / path, color=_scene_camera_fixture_color(path))


def _scene_camera_fixture_color(path: str) -> tuple[int, int, int]:
    if "molmospaces" in path and "room_01" in path:
        return (80, 80, 80)
    if "isaaclab" in path and "room_01" in path:
        return (180, 180, 180)
    if "molmospaces" in path and "view_01" in path:
        return (180, 180, 180)
    if "isaaclab" in path and "view_01" in path:
        return (80, 80, 80)
    if "molmospaces" in path:
        return (120, 70, 50)
    return (200, 160, 120)


def _assert_scene_camera_report_artifacts(
    report_path: Path,
    tmp_path: Path,
    manifest: dict[str, object],
) -> None:
    assert report_path == tmp_path / "report.html"
    assert (tmp_path / "contact_sheet.png").is_file()
    assert manifest["artifacts"]["contact_sheet"] == "contact_sheet.png"  # type: ignore[index]
    assert manifest["contact_sheet"]["view_count"] == 3  # type: ignore[index]


def test_scene_camera_visual_metrics_quantify_brightness_delta(tmp_path: Path) -> None:
    dark = tmp_path / "dark.png"
    bright = tmp_path / "bright.png"
    _write_image(dark, color=(10, 20, 30))
    _write_image(bright, color=(110, 120, 130))

    dark_metrics = _image_visual_metrics(dark)
    bright_metrics = _image_visual_metrics(bright)
    delta = _image_pair_visual_delta(dark, bright)

    assert dark_metrics["mean_rgb"] == pytest.approx([10.0, 20.0, 30.0])
    assert bright_metrics["mean_luminance"] > dark_metrics["mean_luminance"]
    assert dark_metrics["overexposed_fraction"] == 0.0
    assert delta["mean_absolute_pixel_delta"] == pytest.approx(100.0)


def test_scene_camera_color_profile_replay_applies_backend_gain(tmp_path: Path) -> None:
    molmo = tmp_path / "molmo.png"
    isaac = tmp_path / "isaac.png"
    _write_image(molmo, color=(100, 100, 100))
    _write_image(isaac, color=(200, 200, 200))

    replay = _offline_color_profile_replay(
        view_id="view_1",
        label="View 1",
        molmo_path=molmo,
        isaac_path=isaac,
        color_profile={
            "profile_id": "display_srgb_soft_highlight_v1",
            "highlight_knee": 225.0,
            "highlight_compression": 0.55,
            "gamma": 1.0,
            "backend_luminance_gain": {
                MOLMOSPACES_LANE_ID: 1.0,
                ISAAC_LANE_ID: 0.5,
            },
        },
    )

    assert replay["lanes"][MOLMOSPACES_LANE_ID]["mean_luminance"] == pytest.approx(100.0)
    assert replay["lanes"][ISAAC_LANE_ID]["mean_luminance"] == pytest.approx(100.0)
    assert replay["delta"]["mean_luminance_delta"] == pytest.approx(0.0)
    assert (tmp_path / "isaac.color_profile_replay.png").is_file()


def test_scene_camera_color_profile_replay_prefers_view_gain(tmp_path: Path) -> None:
    molmo = tmp_path / "molmo.png"
    isaac = tmp_path / "isaac.png"
    _write_image(molmo, color=(100, 100, 100))
    _write_image(isaac, color=(200, 200, 200))

    replay = _offline_color_profile_replay(
        view_id="room_02_room_3",
        label="Room 3",
        molmo_path=molmo,
        isaac_path=isaac,
        color_profile={
            "profile_id": "display_srgb_soft_highlight_v1",
            "backend_luminance_gain": {
                MOLMOSPACES_LANE_ID: 1.0,
                ISAAC_LANE_ID: 0.5,
            },
            "backend_view_luminance_gain": {ISAAC_LANE_ID: {"room_02_room_3": 0.25}},
        },
    )

    assert replay["lanes"][ISAAC_LANE_ID]["mean_luminance"] == pytest.approx(50.0)
    assert replay["delta"]["mean_luminance_delta"] == pytest.approx(-50.0)


def test_scene_camera_color_profile_replay_prefers_view_rgb_gain(tmp_path: Path) -> None:
    molmo = tmp_path / "molmo.png"
    isaac = tmp_path / "isaac.png"
    _write_image(molmo, color=(100, 100, 100))
    _write_image(isaac, color=(200, 200, 200))

    replay = _offline_color_profile_replay(
        view_id="room_02_room_3",
        label="Room 3",
        molmo_path=molmo,
        isaac_path=isaac,
        color_profile={
            "profile_id": "display_srgb_soft_highlight_v1",
            "backend_rgb_gain": {ISAAC_LANE_ID: [1.0, 1.0, 1.0]},
            "backend_view_rgb_gain": {ISAAC_LANE_ID: {"room_02_room_3": [0.5, 0.25, 0.1]}},
        },
    )

    assert replay["lanes"][ISAAC_LANE_ID]["mean_rgb"] == pytest.approx([100.0, 50.0, 20.0])
    assert replay["delta"]["mean_absolute_pixel_delta"] == pytest.approx(43.333333333333336)


def test_scene_camera_color_profile_replay_normalizes_legacy_profile() -> None:
    profile = _normalize_color_profile_for_replay({"profile_id": "display_srgb_soft_highlight_v1"})

    assert profile["backend_luminance_gain"][MOLMOSPACES_LANE_ID] == pytest.approx(1.0)
    assert profile["backend_luminance_gain"][ISAAC_LANE_ID] == pytest.approx(0.7161647108631373)


def test_scene_camera_color_profile_replay_normalizes_view_gain() -> None:
    profile = _normalize_color_profile_for_replay(
        {
            "profile_id": "display_srgb_soft_highlight_v1",
            "backend_view_luminance_gain": {
                ISAAC_LANE_ID: {"room_02_room_3": "0.25", "bad": "not-a-float"}
            },
            "backend_view_luminance_gain_source": "unit",
        }
    )

    assert profile["backend_view_luminance_gain"][ISAAC_LANE_ID]["room_02_room_3"] == (
        pytest.approx(0.25)
    )
    assert "bad" not in profile["backend_view_luminance_gain"][ISAAC_LANE_ID]
    assert profile["backend_view_luminance_gain_source"] == "unit"


def test_scene_camera_color_profile_replay_normalizes_rgb_gain() -> None:
    profile = _normalize_color_profile_for_replay(
        {
            "profile_id": "display_srgb_soft_highlight_v1",
            "backend_rgb_gain": {ISAAC_LANE_ID: ["0.5", "0.25", "0.1"]},
            "backend_view_rgb_gain": {
                ISAAC_LANE_ID: {
                    "room_02_room_3": ["0.4", "0.3", "0.2"],
                    "bad": ["not-a-float", "0.3", "0.2"],
                }
            },
            "backend_view_rgb_gain_source": "unit-rgb",
        }
    )

    assert profile["backend_rgb_gain"][ISAAC_LANE_ID] == pytest.approx([0.5, 0.25, 0.1])
    assert profile["backend_view_rgb_gain"][ISAAC_LANE_ID]["room_02_room_3"] == pytest.approx(
        [0.4, 0.3, 0.2]
    )
    assert "bad" not in profile["backend_view_rgb_gain"][ISAAC_LANE_ID]
    assert profile["backend_view_rgb_gain_source"] == "unit-rgb"


def test_scene_camera_candidate_color_calibrations_compare_gain_strategies(
    tmp_path: Path,
) -> None:
    molmo = tmp_path / "molmo.png"
    isaac = tmp_path / "isaac.png"
    _write_image(molmo, color=(100, 100, 100))
    _write_image(isaac, color=(200, 160, 120))
    view_results = [
        {
            "view_id": "view_1",
            "label": "View 1",
            "lanes": {
                MOLMOSPACES_LANE_ID: _image_visual_metrics(molmo),
                ISAAC_LANE_ID: _image_visual_metrics(isaac),
            },
            "delta": _image_pair_visual_delta(molmo, isaac),
        }
    ]
    summary = _candidate_color_calibrations(
        view_results,
        entries=[
            {
                "view_id": "view_1",
                "label": "View 1",
                "images": {MOLMOSPACES_LANE_ID: molmo, ISAAC_LANE_ID: isaac},
            }
        ],
        base_color_profile={
            "profile_id": "display_srgb_soft_highlight_v1",
            "backend_luminance_gain": {MOLMOSPACES_LANE_ID: 1.0, ISAAC_LANE_ID: 1.0},
        },
    )

    candidates = {item["candidate_id"]: item for item in summary["candidates"]}
    assert summary["best_candidate"] in candidates
    assert candidates["current_profile"]["mean_absolute_pixel_delta"] > 0.0
    assert candidates["ideal_per_view_luminance_gain"]["mean_absolute_pixel_delta"] > 0.0
    assert candidates["ideal_per_view_rgb_gain"]["gain_delta"]["backend_view_rgb_gain"][
        ISAAC_LANE_ID
    ]["view_1"] == pytest.approx([0.5, 0.625, 0.8333333333333334])
    assert candidates["ideal_per_view_rgb_gain"]["gain_delta"]["backend_view_luminance_gain"][
        ISAAC_LANE_ID
    ]["view_1"] == pytest.approx(1.0)


def test_scene_camera_render_domain_calibration_detects_global_gain() -> None:
    calibration = _render_domain_calibration(
        [
            _visual_metric_pair("view_1", molmo_luminance=50.0, isaac_luminance=100.0),
            _visual_metric_pair("view_2", molmo_luminance=100.0, isaac_luminance=200.0),
        ]
    )

    assert calibration["status"] == "global_luminance_gain_sufficient"
    assert calibration["global_isaac_luminance_gain"] == pytest.approx(0.5)
    assert calibration["mean_abs_calibrated_luminance_residual"] == pytest.approx(0.0)


def test_scene_camera_render_domain_calibration_flags_view_dependent_delta() -> None:
    calibration = _render_domain_calibration(
        [
            _visual_metric_pair("view_1", molmo_luminance=50.0, isaac_luminance=100.0),
            _visual_metric_pair("view_2", molmo_luminance=180.0, isaac_luminance=200.0),
        ]
    )

    assert calibration["status"] == "view_dependent_render_domain_delta"
    assert calibration["mean_abs_calibrated_luminance_residual"] > 12.0
    assert "material" in calibration["recommended_next_action"]


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


def test_scene_camera_projection_diagnostics_quantify_same_pinhole_geometry() -> None:
    manifest = _manifest()
    diagnostics = projection_diagnostics(manifest)

    assert diagnostics["status"] == "same_projected_geometry_within_threshold"
    assert diagnostics["max_pixel_delta"] == pytest.approx(0.0)
    assert diagnostics["vertical_fov_deg"] == pytest.approx(45.0)
    assert diagnostics["resolution"] == {"width": 960, "height": 640}
    bed = next(item for item in diagnostics["pairs"] if item["view_id"] == "view_01_bed")
    target = next(point for point in bed["points"] if point["label"] == "camera_target")
    assert target["molmospaces_pixel"] == pytest.approx(target["isaac_pixel"])
    assert target["inside_frame"] is True


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


def test_backend_swap_geometry_contract_blocks_room_scale_mismatch() -> None:
    manifest = _manifest()
    manifest["room_scale_contract"] = {
        **manifest["room_scale_contract"],  # type: ignore[index]
        "status": "room_outline_mismatch",
        "max_room_outline_center_delta_m": 0.26,
    }

    contract = _backend_swap_geometry_contract(manifest)

    checks = {item["check"]: item for item in contract["required_checks"]}
    assert contract["status"] == "geometry_swap_not_ready"
    assert contract["geometry_contract_status"] == "fail"
    assert contract["same_api_agent_swap_claim"] is False
    assert checks["same_room_scale"]["status"] == "fail"


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


def test_scene_camera_native_isaac_render_diagnostics_are_summarized() -> None:
    manifest = _manifest()

    diagnostics = _native_isaac_render_diagnostics(manifest)

    assert diagnostics["status"] == "native_settings_recorded"
    assert diagnostics["native_settings_recorded"] is True
    assert diagnostics["default_render_settings_changed"] is False
    assert diagnostics["settings_api_available"] is True
    assert diagnostics["camera_prim_paths"] == ["/World/scene_camera"]
    assert diagnostics["render_product_paths"] == ["/Render/Products/scene_camera"]
    assert diagnostics["post_render_comparison_profile"]["source"] == (
        "not_a_native_renderer_setting"
    )
    assert diagnostics["tone_mapping"]["operator"] == {
        "status": "available",
        "value": "ACES",
        "setting_path": "/rtx/post/tonemap/op",
    }
    assert diagnostics["camera_exposure"]["auto_exposure_enabled"] == {
        "status": "available",
        "value": False,
        "setting_path": "/rtx/post/tonemap/autoExposure/enabled",
    }


def test_scene_camera_comparison_default_color_profile_contract() -> None:
    assert DEFAULT_SCENE_PROBE_COLOR_PROFILE["profile_id"] == "display_srgb_soft_highlight_v1"
    assert DEFAULT_SCENE_PROBE_COLOR_PROFILE["highlight_knee"] == 225.0
    assert DEFAULT_SCENE_PROBE_COLOR_PROFILE["highlight_compression"] == 0.55
    assert DEFAULT_SCENE_PROBE_COLOR_PROFILE["backend_luminance_gain"][
        "molmospaces-mujoco"
    ] == pytest.approx(1.0)
    assert DEFAULT_SCENE_PROBE_COLOR_PROFILE["backend_luminance_gain"][
        "isaaclab-prepared-usd"
    ] == pytest.approx(0.7161647108631373)
    assert "0530_0009" in DEFAULT_SCENE_PROBE_COLOR_PROFILE["backend_luminance_gain_source"]


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


def test_scene_camera_color_profile_normalizes_backend_tone_adjustment() -> None:
    request = scene_probe_camera_control_request(
        [{"view_id": "room_01", "target": [0.0, 0.0, 0.0]}],
        width=64,
        height=48,
        color_profile={
            "backend_tone_adjustment": {
                "unit-test-renderer": {
                    "shadow_lift": 8,
                    "shadow_floor": 135,
                    "gamma": 1.1,
                    "saturation": 1.0,
                    "gain": 1.2,
                }
            },
            "backend_tone_adjustment_source": "unit-tone",
        },
    )

    assert request["color_profile"]["backend_tone_adjustment"]["unit-test-renderer"] == {
        "shadow_lift": pytest.approx(8.0),
        "shadow_floor": pytest.approx(135.0),
        "gamma": pytest.approx(1.1),
        "saturation": pytest.approx(1.0),
        "gain": pytest.approx(1.2),
    }
    assert request["color_profile"]["backend_tone_adjustment_source"] == "unit-tone"


def test_isaac_view_specs_record_support_pose_for_transform_but_not_camera_target(
    tmp_path: Path,
) -> None:
    scene_dir = tmp_path / "flattened-semantic-usd" / "scene"
    scene_dir.mkdir(parents=True)
    scene_usd = scene_dir / "scene_semantic.usda"
    scene_usd.write_text("#usda 1.0\n", encoding="utf-8")
    (scene_dir / "scene_metadata.json").write_text(
        json.dumps({"objects": {"sink_01": {"category": "Sink", "is_static": True}}}),
        encoding="utf-8",
    )
    index_dir = tmp_path / "cleanup-smoke" / "latest"
    index_dir.mkdir(parents=True)
    (index_dir / "isaac_scene_index.json").write_text(
        json.dumps(
            {
                "scene_usd": str(scene_usd),
                "receptacle_index": {
                    "sink_01": {
                        "usd_prim_path": "/val_1/Geometry/sink_01",
                        "support_pose": {"x": 123.0, "y": 456.0, "z": 0.0},
                    }
                },
            }
        ),
        encoding="utf-8",
    )
    anchors = [
        {
            "anchor_id": "sink_01",
            "anchor_kind": "receptacle",
            "category": "Sink",
            "room_id": "room_3",
            "molmospaces_position": [9.5, 1.8, 0.5],
        }
    ]

    specs = _isaac_view_specs(anchors, scene_usd_path=scene_usd, scene_index=1)

    assert specs == [
        {
            "view_id": "view_01_sink",
            "label": "room_3 Sink sink_01",
            "anchor_id": "sink_01",
            "anchor_kind": "receptacle",
            "usd_prim_path": "/val_1/Geometry/sink_01",
            "target_source": "isaac_worker_usd_prim_world_bounds_diagnostic",
            "isaac_support_position": [123.0, 456.0, 0.0],
            "min_target_z": 0.6,
        }
    ]
    assert "target" not in specs[0]
    assert "eye" not in specs[0]
    assert anchors[0]["isaac_usd_prim_path"] == "/val_1/Geometry/sink_01"
    assert anchors[0]["isaac_support_position"] == [123.0, 456.0, 0.0]


@pytest.mark.parametrize(
    ("payload", "error"),
    [
        ("{", "malformed scene metadata JSON"),
        (json.dumps([]), "scene metadata JSON must be a JSON object"),
        (json.dumps({"objects": []}), "scene metadata JSON objects must be a JSON object"),
        (
            json.dumps({"objects": {"sink_01": []}}),
            "scene metadata JSON objects values must be JSON objects",
        ),
    ],
)
def test_isaac_view_specs_fail_on_corrupt_scene_metadata_source(
    tmp_path: Path,
    payload: str,
    error: str,
) -> None:
    scene_dir = tmp_path / "flattened-semantic-usd" / "scene"
    scene_dir.mkdir(parents=True)
    scene_usd = scene_dir / "scene_semantic.usda"
    scene_usd.write_text("#usda 1.0\n", encoding="utf-8")
    (scene_dir / "scene_metadata.json").write_text(payload, encoding="utf-8")
    anchors = [
        {
            "anchor_id": "sink_01",
            "anchor_kind": "receptacle",
            "category": "Sink",
            "room_id": "room_3",
            "molmospaces_position": [9.5, 1.8, 0.5],
        }
    ]

    with pytest.raises(RuntimeError, match=error):
        _isaac_view_specs(anchors, scene_usd_path=scene_usd, scene_index=1)


def test_isaac_view_specs_allow_missing_optional_scene_metadata(tmp_path: Path) -> None:
    scene_dir = tmp_path / "flattened-semantic-usd" / "scene"
    scene_dir.mkdir(parents=True)
    scene_usd = scene_dir / "scene_semantic.usda"
    scene_usd.write_text("#usda 1.0\n", encoding="utf-8")
    anchors = [
        {
            "anchor_id": "sink_01",
            "anchor_kind": "receptacle",
            "category": "Sink",
            "room_id": "room_3",
            "molmospaces_position": [9.5, 1.8, 0.5],
        }
    ]

    specs = _isaac_view_specs(anchors, scene_usd_path=scene_usd, scene_index=1)

    assert specs[0]["target_source"] == "missing_isaac_usd_prim_path"
    assert specs[0]["usd_prim_path"] == ""


def test_canonical_camera_control_views_carry_explicit_pose_not_lane_orbit() -> None:
    anchors = [
        {
            "anchor_id": "table_01",
            "anchor_kind": "receptacle",
            "category": "DiningTable",
            "room_id": "room_2",
            "molmospaces_position": [2.7, 5.9, 0.37],
            "molmospaces_support_top_z": 0.75,
            "room_center_xy": [2.7, 4.5],
        }
    ]
    molmo_specs = _molmospaces_view_specs(anchors)
    isaac_specs = [
        {
            "view_id": "view_01_diningtable",
            "label": "room_2 DiningTable table_01",
            "anchor_id": "table_01",
            "anchor_kind": "receptacle",
            "usd_prim_path": "/val_1/Geometry/table_01",
            "target_source": "isaac_worker_usd_prim_world_bounds_diagnostic",
            "isaac_support_position": [2.7, 5.9, 0.37],
            "min_target_z": 0.6,
        }
    ]

    views = _canonical_camera_control_views(
        anchors,
        molmo_specs=molmo_specs,
        isaac_specs=isaac_specs,
        scene_transform={
            "status": "identity_pending_render_diagnostics",
            "xy_scale": 1.0,
            "rotation_z_deg": 0.0,
            "translation": [0.0, 0.0, 0.0],
        },
    )

    assert views[0]["camera_model"] == "canonical_eye_target_camera_v1"
    assert views[0]["coordinate_frame"] == "molmospaces_scene_frame_v1"
    assert views[0]["target"] == pytest.approx([2.7, 5.9, 1.0])
    assert views[0]["eye"][2] > views[0]["target"][2]
    assert views[0]["camera_basis"] == "near_topdown_anchor_orbit"
    assert "lane_camera_orbits" not in views[0]


def test_room_camera_control_views_use_same_canonical_pose_contract() -> None:
    views = _room_camera_control_views(
        {
            "room_outlines": [
                {
                    "room_id": "room_2",
                    "label": "Room 2",
                    "center": [2.0, 4.0],
                    "half_extents": [3.0, 2.0],
                    "provenance": "mujoco_room_geom",
                }
            ]
        }
    )

    assert views == [
        {
            "view_id": "room_01_room_2",
            "label": "Room 2 canonical room view",
            "anchor_id": "room_2",
            "anchor_kind": "room",
            "category": "Room",
            "room_id": "room_2",
            "camera_mode": "canonical_eye_target",
            "camera_model": "canonical_eye_target_camera_v1",
            "coordinate_frame": "molmospaces_scene_frame_v1",
            "coordinate_convention": "molmospaces_scene_frame_v1",
            "calibration_status": "canonical_scene_frame_similarity_fit_v1",
            "eye": pytest.approx([0.95, 3.3, 1.45]),
            "target": pytest.approx([2.0, 4.0, 1.45]),
            "lookat": pytest.approx([2.0, 4.0, 1.45]),
            "up": [0.0, 0.0, 1.0],
            "camera_basis": "room_center_inset_eye_target",
            "target_source": {
                MOLMOSPACES_LANE_ID: "molmospaces_room_outline_center",
                ISAAC_LANE_ID: "canonical_explicit_room_target_from_molmospaces_scene_frame",
            },
            "lane_targets": {
                MOLMOSPACES_LANE_ID: {
                    "lookat": pytest.approx([2.0, 4.0, 1.45]),
                    "room_id": "room_2",
                },
                ISAAC_LANE_ID: {"room_id": "room_2"},
            },
            "room_outline": {
                "center": [2.0, 4.0],
                "half_extents": [3.0, 2.0],
                "provenance": "mujoco_room_geom",
            },
        }
    ]
    assert "lane_camera_orbits" not in views[0]


def test_scene_frame_transform_from_capture_uses_usd_bounds_distance() -> None:
    transform = scene_frame_transform_from_capture(
        canonical_views=[
            {
                "view_id": "view_01_table",
                "anchor_id": "table_01",
                "category": "DiningTable",
                "target": [2.7, 5.9, 1.0],
            }
        ],
        isaac_lane={
            "views": [
                {
                    "view_id": "view_01_table",
                    "usd_bounds_target": [2.72, 5.94, 0.6],
                    "usd_bounds": {
                        "min": [2.0, 5.0, 0.3],
                        "max": [3.0, 6.0, 1.2],
                        "center": [2.5, 5.5, 0.75],
                    },
                }
            ]
        },
    )

    assert transform["status"] == "identity_checked_against_usd_bounds"
    assert transform["diagnostic_kind"] == "camera_target_vs_isaac_usd_bounds"
    assert (
        transform["target_residual_status"]
        == "target_inside_or_near_usd_bounds_with_surface_aim_allowance"
    )
    assert transform["max_residual_m"] == pytest.approx(0.402492, rel=1e-4)
    assert transform["max_xy_residual_m"] == pytest.approx(0.044721, rel=1e-4)
    assert transform["max_z_residual_m"] == pytest.approx(0.4)
    assert transform["max_distance_to_usd_bounds_m"] == pytest.approx(0.0)
    assert transform["max_surface_aim_distance_to_usd_bounds_m"] == pytest.approx(0.0)
    assert transform["target_inside_usd_xy_bounds_count"] == 1
    assert transform["target_inside_usd_xyz_bounds_count"] == 1


def test_scene_frame_transform_from_capture_flags_targets_outside_usd_bounds() -> None:
    transform = scene_frame_transform_from_capture(
        canonical_views=[
            {
                "view_id": "view_01_table",
                "anchor_id": "table_01",
                "category": "DiningTable",
                "target": [4.0, 5.9, 1.0],
            }
        ],
        isaac_lane={
            "views": [
                {
                    "view_id": "view_01_table",
                    "usd_bounds_target": [2.72, 5.94, 0.6],
                    "usd_bounds": {
                        "min": [2.0, 5.0, 0.3],
                        "max": [3.0, 6.0, 1.2],
                        "center": [2.5, 5.5, 0.75],
                    },
                }
            ]
        },
    )

    assert transform["target_residual_status"] == "target_definition_residual_high"
    assert transform["max_distance_to_usd_bounds_m"] == pytest.approx(1.0)
    assert transform["target_inside_usd_xy_bounds_count"] == 0


def test_scene_frame_transform_from_capture_accepts_surface_aim_above_usd_bounds() -> None:
    transform = scene_frame_transform_from_capture(
        canonical_views=[
            {
                "view_id": "view_01_table",
                "anchor_id": "table_01",
                "category": "DiningTable",
                "target": [2.7, 5.9, 1.0],
            }
        ],
        isaac_lane={
            "views": [
                {
                    "view_id": "view_01_table",
                    "usd_bounds_target": [2.72, 5.94, 0.6],
                    "usd_bounds": {
                        "min": [2.0, 5.0, 0.3],
                        "max": [3.0, 6.0, 0.75],
                        "center": [2.5, 5.5, 0.525],
                    },
                }
            ]
        },
    )

    assert (
        transform["target_residual_status"]
        == "target_inside_or_near_usd_bounds_with_surface_aim_allowance"
    )
    assert transform["max_distance_to_usd_bounds_m"] == pytest.approx(0.25)
    assert transform["max_surface_aim_distance_to_usd_bounds_m"] == pytest.approx(0.0)
    assert transform["target_inside_usd_xy_bounds_count"] == 1
    assert transform["target_inside_usd_xyz_bounds_count"] == 0


def test_camera_pose_contract_from_capture_checks_backend_pose_delta() -> None:
    contract = camera_pose_contract_from_capture(
        canonical_views=[
            {
                "view_id": "view_01_table",
                "anchor_id": "table_01",
                "category": "DiningTable",
                "eye": [1.0, 2.0, 3.0],
                "target": [2.7, 5.9, 1.0],
            }
        ],
        molmospaces_lane={
            "views": [
                {
                    "view_id": "view_01_table",
                    "backend_eye": [1.0, 2.0, 3.0],
                    "backend_target": [2.7, 5.9, 1.0],
                }
            ]
        },
        isaac_lane={
            "views": [
                {
                    "view_id": "view_01_table",
                    "backend_eye": [1.0, 2.0, 3.0],
                    "backend_target": [2.7, 5.9, 1.0],
                    "usd_bounds_target": [2.72, 5.94, 0.6],
                }
            ]
        },
    )

    assert contract["status"] == "same_backend_pose_within_threshold"
    assert contract["max_pose_delta_m"] == pytest.approx(0.0)
    assert contract["pairs"][0]["backend_eye_delta_m"] == pytest.approx(0.0)
    assert contract["pairs"][0]["backend_target_delta_m"] == pytest.approx(0.0)


def test_camera_intrinsics_contract_declares_vertical_fov_precedence() -> None:
    contract = camera_intrinsics_contract_from_capture(
        requested_lens={
            "vertical_fov_deg": 45.0,
            "focal_length_mm": 24.0,
        },
        requested_resolution={"width": 960, "height": 640},
        molmospaces_lane={
            "lens": {
                "vertical_fov_deg": 45.0,
                "focal_length_mm": 24.0,
            }
        },
        isaac_lane={
            "lens": {
                "vertical_fov_deg": 45.0,
                "focal_length_mm": 24.0,
            },
            "derived_lens": {
                "focal_length_mm": 24.0,
                "horizontal_aperture_mm": 29.82337649086285,
            },
        },
    )

    assert contract["status"] == "intrinsics_consistent"
    assert contract["intrinsics_precedence"] == "vertical_fov_deg"
    assert contract["derived_from_vertical_fov"]["horizontal_aperture_mm"] == pytest.approx(
        29.82337649
    )
    assert contract["requested_vs_derived_horizontal_aperture_delta_mm"] is None


def test_room_scale_contract_compares_room_outline_to_isaac_scene_bounds() -> None:
    contract = room_scale_contract_from_scene_capture(
        room_views=[
            {
                "view_id": "room_01_room_2",
                "room_id": "room_2",
                "room_outline": {
                    "center": [2.99, 4.983],
                    "half_extents": [2.99, 4.983],
                    "provenance": "mujoco_room_mesh_world_bounds",
                },
            }
        ],
        isaac_lane={
            "scene_bounds": {"size": [9.976, 10.097, 3.154]},
            "scene_index_diagnostics": {
                "room_outlines": [
                    {
                        "room_id": "room_2",
                        "center": [2.99, 4.983],
                        "half_extents": [2.99, 4.983],
                        "provenance": "isaac_usd_room_mesh_world_bounds",
                        "usd_prim_path": "/val_1/Geometry/room_2_visual_0",
                    }
                ],
            },
        },
    )

    assert contract["status"] == "same_room_outlines_within_threshold"
    assert contract["room_count"] == 1
    assert contract["matched_room_outline_count"] == 1
    assert contract["rooms"][0]["size"] == pytest.approx([5.98, 9.966])
    assert contract["room_outline_pairs"][0]["center_delta_m"] == pytest.approx(0.0)
    assert contract["room_outline_pairs"][0]["size_delta_m"] == pytest.approx(0.0)
    assert contract["room_outline_pairs"][0]["isaac_usd_prim_path"] == (
        "/val_1/Geometry/room_2_visual_0"
    )
    assert contract["max_room_to_scene_width_ratio"] == pytest.approx(0.5994, rel=1e-3)
    assert contract["max_room_to_scene_depth_ratio"] == pytest.approx(0.987, rel=1e-3)


def test_room_scale_contract_flags_room_outline_mismatch() -> None:
    contract = room_scale_contract_from_scene_capture(
        room_views=[
            {
                "view_id": "room_01_room_2",
                "room_id": "room_2",
                "room_outline": {
                    "center": [2.99, 4.983],
                    "half_extents": [2.99, 4.983],
                    "provenance": "mujoco_room_mesh_world_bounds",
                },
            }
        ],
        isaac_lane={
            "scene_bounds": {"size": [9.976, 10.097, 3.154]},
            "scene_index_diagnostics": {
                "room_outlines": [
                    {
                        "room_id": "room_2",
                        "center": [3.25, 4.983],
                        "half_extents": [2.5, 4.0],
                        "provenance": "isaac_usd_room_mesh_world_bounds",
                    }
                ],
            },
        },
    )

    assert contract["status"] == "room_outline_mismatch"
    assert contract["max_room_outline_center_delta_m"] == pytest.approx(0.26)
    assert contract["max_room_outline_size_delta_m"] > 1.0


def test_molmospaces_view_specs_use_anchor_orbit_not_focus_camera_heuristic() -> None:
    anchors = [
        {
            "anchor_id": "table_01",
            "anchor_kind": "receptacle",
            "category": "DiningTable",
            "room_id": "room_2",
            "molmospaces_position": [2.7, 5.9, 0.37],
            "molmospaces_support_top_z": 0.75,
        }
    ]

    specs = _molmospaces_view_specs(anchors)

    assert specs[0] == {
        "view_id": "view_01_diningtable",
        "label": "room_2 DiningTable table_01",
        "anchor_id": "table_01",
        "anchor_kind": "receptacle",
        "camera_mode": "anchor_orbit",
        "focus_receptacle_id": "table_01",
        "lookat": [2.7, 5.9, 1.0],
        "target_source": "molmospaces_metadata_anchor_position",
        "camera_orbit": {"distance_m": 4.4, "azimuth_deg": 90.0, "elevation_deg": 28.0},
    }
    assert "robot_pose" not in specs[0]


def test_scene_camera_comparison_cli_rejects_non_positive_render_dimensions(
    tmp_path: Path,
) -> None:
    script = REPO_ROOT / "scripts" / "molmo_cleanup" / "run_molmospaces_scene_camera_comparison.py"

    completed = subprocess.run(
        [
            sys.executable,
            str(script),
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
    )

    assert completed.returncode == 2
    assert "expected a positive integer" in completed.stderr

    completed = subprocess.run(
        [
            sys.executable,
            str(script),
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
            just_bin(),
            "-f",
            str(MOLMO_JUST),
            "scene-camera-comparison",
            "seed=7",
            "generated_mess_count=1",
            "output_dir=output/molmo/scene-camera-comparison",
            "scene_source=procthor-10k-val",
            "scene_index=1",
            f"scene_usd_path={missing_usd}",
        ],
        cwd=tmp_path,
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
            just_bin(),
            "-f",
            str(MOLMO_JUST),
            "scene-camera-comparison",
            f"scene_usd_path={scene_usd}",
        ],
        cwd=tmp_path,
        env=env,
        check=False,
        capture_output=True,
        text=True,
    )

    assert result.returncode != 0
    assert "requires explicit prior Omniverse EULA acceptance" in result.stderr
    assert "OMNI_KIT_ACCEPT_EULA=YES" in result.stderr
