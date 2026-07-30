from __future__ import annotations

import json
from pathlib import Path

from PIL import Image

from scripts.operator_console.render_scene_previews import (
    PREVIEW_METADATA_SCHEMA,
    render_b1_map12_preview,
)
from tests.unit.operator_console.render_scene_previews_support import (
    _write_stale_b1_real_camera_preview_metadata,
)


def test_b1_map12_skip_existing_rewrites_stale_camera_preview_metadata(tmp_path: Path) -> None:
    Image.new("RGB", (16, 16), (1, 2, 3)).save(tmp_path / "b1-map12-fpv.png")
    Image.new("RGB", (16, 16), (4, 5, 6)).save(tmp_path / "b1-map12-chase.png")
    metadata_path = tmp_path / "b1-map12-preview.json"
    metadata_path.write_text(
        json.dumps(
            {
                "schema": PREVIEW_METADATA_SCHEMA,
                "views": {
                    "fpv": {"path": "b1-map12-fpv.png"},
                    "chase": {"path": "b1-map12-chase.png"},
                    "map": {
                        "path": "b1-map12-map.png",
                        "provenance": "b1_map12_base_metric_map_preview_png",
                    },
                    "topdown": {
                        "path": "b1-map12-topdown.png",
                        "provenance": "b1_map12_reviewed_semantic_topdown_png",
                    },
                },
            },
            indent=2,
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )

    result = render_b1_map12_preview(
        output_dir=tmp_path,
        width=320,
        height=200,
        skip_existing=True,
    )

    assert result["status"] == "rendered"
    assert not (tmp_path / "b1-map12-fpv.png").exists()
    assert not (tmp_path / "b1-map12-chase.png").exists()
    assert (tmp_path / "b1-map12-map.png").is_file()
    assert (tmp_path / "b1-map12-topdown.png").is_file()
    metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
    assert "fpv" not in metadata["views"]
    assert "chase" not in metadata["views"]
    assert "map" in metadata["views"]
    assert "topdown" in metadata["views"]
    assert metadata["views"]["topdown"]["provenance"] == "b1_scene_gaussian_topdown_crop_z1p8_png"
    assert metadata["views"]["topdown"]["artifact_source_family"] == "scene_camera_render"


def test_b1_map12_rewrites_prepared_nurec_scene_probe_camera_previews(tmp_path: Path) -> None:
    Image.new("RGB", (16, 16), (80, 90, 100)).save(tmp_path / "b1-map12-fpv.png")
    Image.new("RGB", (16, 16), (100, 90, 80)).save(tmp_path / "b1-map12-chase.png")
    metadata_path = tmp_path / "b1-map12-preview.json"
    metadata_path.write_text(
        json.dumps(
            {
                "schema": PREVIEW_METADATA_SCHEMA,
                "renderer": "static_b1_map12_with_prepared_nurec_camera_previews",
                "views": {
                    "fpv": {
                        "path": "b1-map12-fpv.png",
                        "provenance": "prepared_b1_nurec_scene_camera_preview",
                    },
                    "chase": {
                        "path": "b1-map12-chase.png",
                        "provenance": "prepared_b1_nurec_scene_camera_preview",
                    },
                    "map": {
                        "path": "b1-map12-map.png",
                        "provenance": "b1_map12_base_metric_map_preview_png",
                    },
                    "topdown": {
                        "path": "b1-map12-topdown.png",
                        "provenance": "b1_scene_gaussian_topdown_crop_z1p8_png",
                    },
                },
            },
            indent=2,
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )

    result = render_b1_map12_preview(output_dir=tmp_path, width=320, height=200)

    assert result["status"] == "rendered"
    assert not (tmp_path / "b1-map12-fpv.png").exists()
    assert not (tmp_path / "b1-map12-chase.png").exists()
    assert (tmp_path / "b1-map12-map.png").is_file()
    assert (tmp_path / "b1-map12-topdown.png").is_file()
    metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
    assert metadata["renderer"] == "b1_map12_static_gaussian_topdown_previews"
    assert "fpv" not in metadata["views"]
    assert "chase" not in metadata["views"]
    assert "map" in metadata["views"]
    assert "topdown" in metadata["views"]


def test_b1_map12_skip_existing_rewrites_missing_real_camera_files(tmp_path: Path) -> None:
    Image.new("RGB", (16, 16), (10, 20, 30)).save(tmp_path / "b1-map12-map.png")
    Image.new("RGB", (16, 16), (30, 20, 10)).save(tmp_path / "b1-map12-topdown.png")
    metadata_path = tmp_path / "b1-map12-preview.json"
    metadata_path.write_text(
        json.dumps(
            {
                "schema": PREVIEW_METADATA_SCHEMA,
                "views": {
                    "fpv": {
                        "path": "b1-map12-fpv.png",
                        "provenance": "isaac_runtime_robot_mounted_head_camera_fpv",
                    },
                    "chase": {
                        "path": "b1-map12-chase.png",
                        "provenance": "isaac_runtime_report_chase_camera",
                    },
                    "map": {
                        "path": "b1-map12-map.png",
                        "provenance": "b1_map12_base_metric_map_preview_png",
                    },
                    "topdown": {
                        "path": "b1-map12-topdown.png",
                        "provenance": "b1_scene_gaussian_topdown_crop_z1p8_png",
                    },
                },
            },
            indent=2,
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )

    result = render_b1_map12_preview(
        output_dir=tmp_path,
        width=320,
        height=200,
        skip_existing=True,
    )

    assert result["status"] == "rendered"
    metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
    assert metadata["renderer"] == "b1_map12_static_gaussian_topdown_previews"
    assert "fpv" not in metadata["views"]
    assert "chase" not in metadata["views"]
    assert "map" in metadata["views"]
    assert "topdown" in metadata["views"]


def test_b1_map12_skip_existing_rewrites_real_camera_metadata_without_alignment(
    tmp_path: Path,
) -> None:
    old_artifact = tmp_path / "old-run" / "run_result.json"
    metadata_path = _write_stale_b1_real_camera_preview_metadata(
        tmp_path,
        artifact_path=old_artifact,
    )

    result = render_b1_map12_preview(
        output_dir=tmp_path,
        width=320,
        height=200,
        skip_existing=True,
        camera_artifact=old_artifact,
    )

    assert result["status"] == "camera_preview_unavailable"
    assert not (tmp_path / "b1-map12-fpv.png").exists()
    assert not (tmp_path / "b1-map12-chase.png").exists()
    assert (tmp_path / "b1-map12-map.png").is_file()
    assert (tmp_path / "b1-map12-topdown.png").is_file()
    metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
    assert "fpv" not in metadata["views"]
    assert "chase" not in metadata["views"]
    assert "map" in metadata["views"]
    assert "topdown" in metadata["views"]


def test_b1_map12_skip_existing_keeps_complete_matching_camera_metadata(tmp_path: Path) -> None:
    artifact = tmp_path / "run" / "run_result.json"
    alignment_artifact = tmp_path / "run" / "alignment_residuals.json"
    metadata_path = _write_stale_b1_real_camera_preview_metadata(
        tmp_path,
        artifact_path=artifact,
        waypoint_id="generated_exploration_002",
        alignment_artifact=alignment_artifact,
        alignment_transform_source="reviewed_correspondence_fit",
    )

    result = render_b1_map12_preview(
        output_dir=tmp_path,
        width=320,
        height=200,
        skip_existing=True,
        camera_artifact=artifact,
    )

    assert result["status"] == "skipped"
    assert result["metadata"] == str(metadata_path)
    assert (tmp_path / "b1-map12-fpv.png").exists()
    assert (tmp_path / "b1-map12-chase.png").exists()


def test_b1_map12_static_preview_does_not_carry_forward_real_camera_previews(
    tmp_path: Path,
) -> None:
    metadata_path = _write_stale_b1_real_camera_preview_metadata(
        tmp_path,
        artifact_path=tmp_path / "old-run" / "run_result.json",
    )

    result = render_b1_map12_preview(output_dir=tmp_path, width=320, height=200)

    assert result["status"] == "rendered"
    assert set(result["removed_stale"]) == {
        str(tmp_path / "b1-map12-fpv.png"),
        str(tmp_path / "b1-map12-chase.png"),
    }
    assert not (tmp_path / "b1-map12-fpv.png").exists()
    assert not (tmp_path / "b1-map12-chase.png").exists()
    assert (tmp_path / "b1-map12-map.png").is_file()
    assert (tmp_path / "b1-map12-topdown.png").is_file()
    metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
    assert metadata["renderer"] == "b1_map12_static_gaussian_topdown_previews"
    assert "camera_preview_artifact" not in metadata
    assert set(metadata["views"]) == {"map", "topdown"}
