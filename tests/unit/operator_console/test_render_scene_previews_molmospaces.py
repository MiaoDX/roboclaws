from __future__ import annotations

import json
from pathlib import Path

import pytest
from PIL import Image

from roboclaws.operator_console.scene_preview_b1 import render_b1_map12_preview
from roboclaws.operator_console.scene_preview_cli import parse_args
from roboclaws.operator_console.scene_preview_common import (
    PreviewSceneRef,
    _preview_metadata,
    _topdown_camera_request,
)
from roboclaws.operator_console.scene_preview_contract import (
    B1_MAP12_WORLD_ID,
    PREVIEW_METADATA_SCHEMA,
)
from roboclaws.operator_console.scene_preview_molmospaces import _molmospaces_scene_ref


def test_render_scene_previews_rejects_non_positive_dimensions() -> None:
    for flag in ("--width", "--height"):
        try:
            parse_args([flag, "0"])
        except SystemExit as exc:
            assert exc.code == 2
        else:  # pragma: no cover - argparse should exit for invalid input
            raise AssertionError(f"expected invalid {flag} to fail at parse time")


def test_render_scene_previews_accepts_positive_dimensions() -> None:
    args = parse_args(["--width", "1", "--height", "1"])

    assert args.width == 1
    assert args.height == 1


def test_topdown_preview_request_uses_scene_camera_not_semantic_map() -> None:
    state = {
        "room_outlines": [
            {"center": [1.0, 2.0, 0.0], "half_extents": [2.0, 3.0]},
            {"center": [5.0, 4.0, 0.0], "half_extents": [1.0, 1.5]},
        ],
        "objects": {"mug_01": {"position": [6.0, 5.0, 0.8]}},
        "receptacles": {"sink_01": {"position": [-1.0, -1.0, 0.9]}},
    }

    request = _topdown_camera_request(state, width=900, height=560)

    view = request["views"][0]
    assert request["camera_model"] == "canonical_eye_target_camera_v1"
    assert request["render_resolution"] == {"width": 900, "height": 560}
    assert view["view_id"] == "topdown_scene"
    assert view["camera_basis"] == "whole_scene_true_topdown_aligned_to_scene_bounds"
    assert view["eye"][2] > view["target"][2]
    assert view["eye"][:2] == pytest.approx(view["target"][:2])
    assert view["azimuth"] == pytest.approx(90.0)
    assert view["scene_alignment"]["schema"] == "operator_console_scene_alignment_v1"


def test_preview_metadata_marks_topdown_as_rendered_scene_not_map_fallback(
    tmp_path: Path,
) -> None:
    fpv_path = tmp_path / "molmospaces-val_9-fpv.png"
    map_path = tmp_path / "molmospaces-val_9-map.png"
    chase_path = tmp_path / "molmospaces-val_9-chase.png"
    topdown_path = tmp_path / "molmospaces-val_9-topdown.png"
    Image.new("RGB", (8, 8), (20, 30, 40)).save(fpv_path)
    Image.new("RGB", (8, 8), (30, 40, 50)).save(map_path)
    Image.new("RGB", (8, 8), (100, 120, 140)).save(chase_path)
    Image.new("RGB", (8, 8), (60, 90, 120)).save(topdown_path)
    scene_alignment = {
        "schema": "operator_console_scene_alignment_v1",
        "bounds": {"min_x": 0.0, "max_x": 4.0, "min_y": 0.0, "max_y": 3.0},
        "center": [2.0, 1.5, 0.4],
        "span_x_m": 4.0,
        "span_y_m": 3.0,
        "camera_span_m": 4.0,
        "screen_coordinate_convention": "screen_x_world_positive_x_screen_y_world_negative_y",
        "topdown_azimuth_deg": 90.0,
    }

    metadata = _preview_metadata(
        world_id="molmospaces/procthor-10k-val/9",
        scene_source="procthor-10k-val",
        scene_index=9,
        seed=7,
        width=900,
        height=560,
        waypoint={"waypoint_id": "generated_exploration_001"},
        navigation={"status": "ok"},
        robot_views={
            "camera_diagnostics": {
                "views": {
                    "fpv": {"status": "ready", "camera_name": "robot_0/head_camera"},
                    "chase": {
                        "status": "ready",
                        "camera_name": "robot_0/camera_follower",
                    },
                }
            }
        },
        topdown_result={
            "views": [
                {
                    "view_id": "topdown_scene",
                    "eye": [1.0, 2.0, 10.0],
                    "target": [1.0, 2.0, 0.4],
                    "azimuth": 90.0,
                    "elevation": -90.0,
                    "distance": 9.6,
                }
            ]
        },
        topdown_request={"camera_model": "canonical_eye_target_camera_v1"},
        fpv_path=fpv_path,
        map_path=map_path,
        chase_path=chase_path,
        chase_waypoint={"waypoint_id": "generated_exploration_004"},
        chase_navigation={"status": "ok"},
        chase_robot_views={
            "camera_diagnostics": {
                "views": {
                    "chase": {
                        "status": "ready",
                        "camera_name": "robot_0/camera_follower",
                    }
                }
            }
        },
        chase_selection={
            "status": "alternate_waypoint_reviewable",
            "candidate_count_evaluated": 4,
        },
        topdown_path=topdown_path,
        scene_alignment=scene_alignment,
    )

    assert metadata["schema"] == PREVIEW_METADATA_SCHEMA
    assert metadata["scene_source"] == "procthor-10k-val"
    assert metadata["views"]["fpv"]["view"] == "raw_fpv"
    assert metadata["views"]["fpv"]["provenance"] == (
        "mujoco_robot_head_camera_first_public_waypoint"
    )
    assert metadata["views"]["chase"]["view"] == "chase_camera"
    assert metadata["views"]["chase"]["provenance"] == (
        "mujoco_robot_camera_follower_public_waypoint"
    )
    assert metadata["views"]["chase"]["waypoint_id"] == "generated_exploration_004"
    assert metadata["views"]["chase"]["selection_status"] == "alternate_waypoint_reviewable"
    assert metadata["views"]["chase"]["candidate_count_evaluated"] == 4
    assert metadata["views"]["chase"]["path"].endswith("-chase.png")
    assert metadata["views"]["chase"]["camera_diagnostics"]["camera_name"] == (
        "robot_0/camera_follower"
    )
    assert metadata["views"]["map"]["view"] == "base_metric_map_preview"
    assert metadata["views"]["map"]["visual_role"] == "base_metric_map_preview"
    assert metadata["views"]["map"]["artifact_source_family"] == "base_metric_map_bundle"
    assert metadata["views"]["map"]["provenance"] == "map_bundle_preview_png"
    assert "scene_alignment" not in metadata["views"]["map"]
    assert "semantic_projection" not in metadata["views"]["map"]
    assert metadata["views"]["topdown"]["view"] == "topdown_scene_render"
    assert metadata["views"]["topdown"]["visual_role"] == "topdown_scene_render"
    assert metadata["views"]["topdown"]["artifact_source_family"] == "scene_camera_render"
    assert metadata["views"]["topdown"]["camera_pose"]["azimuth"] == pytest.approx(90.0)
    assert metadata["views"]["topdown"]["scene_alignment"] == scene_alignment
    assert metadata["views"]["topdown"]["path"].endswith("-topdown.png")
    assert metadata["views"]["topdown"]["image_diagnostics"]["visual_status"] == "low_detail"


def test_molmospaces_preview_scene_ref_accepts_procthor_source_aware_world_id() -> None:
    assert _molmospaces_scene_ref("molmospaces/procthor-10k-val/9") == PreviewSceneRef(
        scene_source="procthor-10k-val",
        scene_index=9,
    )


def test_molmospaces_preview_scene_ref_accepts_source_aware_world_id() -> None:
    assert _molmospaces_scene_ref("molmospaces/ithor/3") == PreviewSceneRef(
        scene_source="ithor",
        scene_index=3,
    )
    assert _molmospaces_scene_ref("molmospaces/procthor-objaverse-val/12") == (
        PreviewSceneRef(scene_source="procthor-objaverse-val", scene_index=12)
    )


def test_molmospaces_preview_scene_ref_rejects_unknown_source_or_index() -> None:
    with pytest.raises(ValueError, match="unsupported MolmoSpaces scene_source"):
        _molmospaces_scene_ref("molmospaces/unknown-source/1")
    with pytest.raises(ValueError, match="unsupported MolmoSpaces scene index"):
        _molmospaces_scene_ref("molmospaces/ithor/not-an-index")
    with pytest.raises(ValueError, match="negative MolmoSpaces scene index"):
        _molmospaces_scene_ref("molmospaces/ithor/-1")


def test_b1_map12_preview_generates_static_map_and_gaussian_topdown_assets(
    tmp_path: Path,
) -> None:
    Image.new("RGB", (16, 16), (10, 20, 30)).save(tmp_path / "b1-map12-map.png")
    Image.new("RGB", (16, 16), (30, 20, 10)).save(tmp_path / "b1-map12-topdown.png")

    result = render_b1_map12_preview(output_dir=tmp_path, width=320, height=200)

    assert result["world_id"] == B1_MAP12_WORLD_ID
    assert result["status"] == "rendered"
    assert (tmp_path / "b1-map12-map.png").is_file()
    assert (tmp_path / "b1-map12-topdown.png").is_file()
    assert not (tmp_path / "b1-map12-fpv.png").exists()
    assert not (tmp_path / "b1-map12-chase.png").exists()
    metadata = json.loads((tmp_path / "b1-map12-preview.json").read_text(encoding="utf-8"))
    assert metadata["schema"] == PREVIEW_METADATA_SCHEMA
    assert metadata["backend"] == "isaaclab"
    assert metadata["renderer"] == "b1_map12_static_gaussian_topdown_previews"
    assert set(metadata["views"]) == {"map", "topdown"}
    assert metadata["views"]["map"]["view"] == "base_metric_map_preview"
    assert metadata["views"]["map"]["artifact_source_family"] == "base_metric_map_bundle"
    assert metadata["views"]["topdown"]["view"] == "topdown_scene_render"
    assert metadata["views"]["topdown"]["artifact_source_family"] == "scene_camera_render"
    assert metadata["views"]["topdown"]["provenance"] == "b1_scene_gaussian_topdown_crop_z1p8_png"
    assert metadata["views"]["topdown"]["alignment_status"] == (
        "height_cropped_gaussian_scene_topdown"
    )
    assert metadata["views"]["topdown"]["source_packet"] == (
        "output/b1-map12/scene-gaussian-topdown-crop-z1p8/scene_gaussian_topdown.json"
    )
    assert metadata["views"]["topdown"]["source_status"] in {
        "captured_gaussian_topdown_packet",
        "checked_in_operator_preview_png",
    }
    assert "first_waypoint_id" not in metadata["views"]["topdown"]
    assert "diagnostic_views" not in metadata
    assert "runtime_map_bundle" not in metadata
