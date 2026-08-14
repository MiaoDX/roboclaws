from __future__ import annotations

from pathlib import Path

import pytest
from PIL import Image

from roboclaws.household.camera_control import (
    CAMERA_CONTROL_API_NAME,
    DEFAULT_SCENE_PROBE_LIGHTING_PROFILE,
    SCENE_LIGHT_RIG_SCHEMA,
    scene_light_rig,
    scene_light_rig_roles,
)
from roboclaws.household.scene_camera_color_diagnostics import (
    _render_domain_source_diagnostics,
)
from roboclaws.household.scene_camera_comparison import (
    ISAAC_LANE_ID,
    MOLMOSPACES_LANE_ID,
    SCENE_CAMERA_COMPARISON_SCHEMA,
)

REPO_ROOT = Path(__file__).resolve().parents[3]


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
