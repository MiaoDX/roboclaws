from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest
from PIL import Image

from roboclaws.maps.b1_map12_correspondence_review import SCENE_TOPDOWN_PICK_SOURCE
from scripts.maps.render_b1_scene_gaussian_topdown import TOPDOWN_RENDER_SCHEMA

REPO_ROOT = Path(__file__).resolve().parents[3]
SCRIPT = REPO_ROOT / "scripts" / "maps" / "render_b1_map12_correspondence_review.py"
VENDOR_MAP12_BUNDLE = (
    REPO_ROOT / "vendors" / "agibot_sdk" / "artifacts" / "maps" / "robot_map_12" / "agibot"
)


@pytest.mark.parametrize(
    ("filename", "source", "message"),
    (
        (
            "scene_correspondences.json",
            "{not-json\n",
            "correspondence manifest source must contain valid JSON object",
        ),
        (
            "scene_correspondences.json",
            "[]\n",
            "correspondence manifest source must contain a JSON object",
        ),
    ),
)
def test_correspondence_review_cli_rejects_bad_correspondence_manifest(
    tmp_path: Path,
    filename: str,
    source: str,
    message: str,
) -> None:
    manifest_path = tmp_path / filename
    render_path = _write_scene_topdown_render_packet(tmp_path)
    output_dir = tmp_path / "review"
    manifest_path.write_text(source, encoding="utf-8")

    completed = _run_review_cli(
        correspondences=manifest_path,
        scene_topdown_render=render_path,
        output_dir=output_dir,
    )

    assert completed.returncode == 2
    assert message in completed.stderr
    assert str(manifest_path) in completed.stderr
    assert not (output_dir / "correspondence_review_packet.json").exists()
    assert not (output_dir / "correspondence_review.html").exists()


def test_correspondence_review_cli_rejects_missing_correspondence_manifest(
    tmp_path: Path,
) -> None:
    manifest_path = tmp_path / "missing_scene_correspondences.json"
    render_path = _write_scene_topdown_render_packet(tmp_path)
    output_dir = tmp_path / "review"

    completed = _run_review_cli(
        correspondences=manifest_path,
        scene_topdown_render=render_path,
        output_dir=output_dir,
    )

    assert completed.returncode == 2
    assert "correspondence manifest source is missing" in completed.stderr
    assert str(manifest_path) in completed.stderr
    assert not (output_dir / "correspondence_review_packet.json").exists()
    assert not (output_dir / "correspondence_review.html").exists()


@pytest.mark.parametrize(
    ("filename", "source", "message"),
    (
        (
            "scene_gaussian_topdown.json",
            "{not-json\n",
            "scene top-down render source must contain valid JSON object",
        ),
        (
            "scene_gaussian_topdown.json",
            "[]\n",
            "scene top-down render source must contain a JSON object",
        ),
    ),
)
def test_correspondence_review_cli_rejects_bad_scene_topdown_render(
    tmp_path: Path,
    filename: str,
    source: str,
    message: str,
) -> None:
    manifest_path = tmp_path / "scene_correspondences.json"
    render_path = tmp_path / filename
    output_dir = tmp_path / "review"
    manifest_path.write_text(json.dumps(_correspondence_manifest()), encoding="utf-8")
    render_path.write_text(source, encoding="utf-8")

    completed = _run_review_cli(
        correspondences=manifest_path,
        scene_topdown_render=render_path,
        output_dir=output_dir,
    )

    assert completed.returncode == 2
    assert message in completed.stderr
    assert str(render_path) in completed.stderr
    assert not (output_dir / "correspondence_review_packet.json").exists()
    assert not (output_dir / "correspondence_review.html").exists()


def test_correspondence_review_cli_rejects_missing_scene_topdown_render(
    tmp_path: Path,
) -> None:
    manifest_path = tmp_path / "scene_correspondences.json"
    render_path = tmp_path / "missing_scene_gaussian_topdown.json"
    output_dir = tmp_path / "review"
    manifest_path.write_text(json.dumps(_correspondence_manifest()), encoding="utf-8")

    completed = _run_review_cli(
        correspondences=manifest_path,
        scene_topdown_render=render_path,
        output_dir=output_dir,
    )

    assert completed.returncode == 2
    assert "scene top-down render source is missing" in completed.stderr
    assert str(render_path) in completed.stderr
    assert not (output_dir / "correspondence_review_packet.json").exists()
    assert not (output_dir / "correspondence_review.html").exists()


def _run_review_cli(
    *,
    correspondences: Path,
    scene_topdown_render: Path,
    output_dir: Path,
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [
            sys.executable,
            str(SCRIPT),
            "--correspondences",
            str(correspondences),
            "--map-bundle",
            str(VENDOR_MAP12_BUNDLE),
            "--scene-topdown-render",
            str(scene_topdown_render),
            "--output-dir",
            str(output_dir),
        ],
        capture_output=True,
        text=True,
    )


def _correspondence_manifest() -> dict[str, object]:
    return {
        "schema": "b1_map12_correspondences_v1",
        "source_map_frame": "map",
        "target_scene_frame": "scene_usd",
        "bbox_seed_policy": "known_poor_seed_only",
        "anchors": [],
    }


def _write_scene_topdown_render_packet(tmp_path: Path) -> Path:
    image_path = tmp_path / "scene_topdown.png"
    Image.new("RGB", (8, 8), color=(12, 24, 48)).save(image_path)
    render_path = tmp_path / "scene_gaussian_topdown.json"
    render_path.write_text(
        json.dumps(
            {
                "schema": TOPDOWN_RENDER_SCHEMA,
                "geometry_status": "rendered_gaussian_scene_topdown",
                "topdown_image": str(image_path),
                "up_axis": "z",
                "horizontal_axes": ["x", "y"],
                "scene_xy_bounds": {"min_x": 0.0, "min_y": 0.0, "max_x": 1.0, "max_y": 1.0},
                "camera": {},
                "pixel_to_scene_xyz": {
                    "status": "perspective_ray_plane_z0",
                    "source": SCENE_TOPDOWN_PICK_SOURCE,
                    "z_plane": 0.0,
                },
            }
        ),
        encoding="utf-8",
    )
    return render_path
