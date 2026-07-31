from __future__ import annotations

import json
from pathlib import Path

import pytest

from roboclaws.household.scene_camera_capture import (
    ISAAC_LANE_ID,
    MOLMOSPACES_LANE_ID,
    _canonical_camera_control_views,
    _isaac_view_specs,
    _molmospaces_view_specs,
    _room_camera_control_views,
)
from roboclaws.household.scene_camera_color_diagnostics import (
    _backend_swap_geometry_contract,
)
from roboclaws.household.scene_camera_geometry_contract import (
    camera_intrinsics_contract_from_capture,
    camera_pose_contract_from_capture,
    room_scale_contract_from_scene_capture,
    scene_frame_transform_from_capture,
)
from roboclaws.household.scene_camera_projection import projection_diagnostics
from tests.contract.molmo_cleanup.scene_camera_comparison_support import (
    _manifest,
)


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
