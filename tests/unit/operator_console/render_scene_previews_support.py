from __future__ import annotations

import hashlib
import json
from pathlib import Path

from PIL import Image

from scripts.operator_console.render_scene_previews import (
    PREVIEW_METADATA_SCHEMA,
)


def _write_stale_b1_real_camera_preview_metadata(
    tmp_path: Path,
    *,
    artifact_path: Path,
    waypoint_id: str = "",
    alignment_artifact: Path | None = None,
    alignment_transform_source: str = "",
) -> Path:
    alignment_artifact_raw = str(alignment_artifact or "")
    Image.new("RGB", (16, 16), (10, 20, 30)).save(tmp_path / "b1-map12-map.png")
    Image.new("RGB", (16, 16), (30, 20, 10)).save(tmp_path / "b1-map12-topdown.png")
    Image.new("RGB", (16, 16), (120, 130, 140)).save(tmp_path / "b1-map12-fpv.png")
    Image.new("RGB", (16, 16), (80, 90, 100)).save(tmp_path / "b1-map12-chase.png")
    metadata_path = tmp_path / "b1-map12-preview.json"
    metadata_path.write_text(
        json.dumps(
            {
                "schema": PREVIEW_METADATA_SCHEMA,
                "renderer": "static_b1_map12_with_isaac_runtime_camera_previews",
                "camera_preview_artifact": {
                    "path": str(artifact_path),
                    "selected_waypoint_id": waypoint_id,
                    "alignment_artifact": alignment_artifact_raw,
                    "alignment_transform_source": alignment_transform_source,
                },
                "views": {
                    "fpv": {
                        "path": "b1-map12-fpv.png",
                        "waypoint_id": waypoint_id,
                        "alignment_artifact": alignment_artifact_raw,
                        "alignment_transform_source": alignment_transform_source,
                        "provenance": "isaac_runtime_robot_mounted_head_camera_fpv",
                    },
                    "chase": {
                        "path": "b1-map12-chase.png",
                        "waypoint_id": waypoint_id,
                        "alignment_artifact": alignment_artifact_raw,
                        "alignment_transform_source": alignment_transform_source,
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
    return metadata_path


def _file_sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _write_b1_camera_artifact(run_dir: Path, *, label: str) -> Path:
    views_dir = run_dir / "robot_views"
    views_dir.mkdir(parents=True)
    _write_pattern_image(views_dir / f"{label}.fpv.png", accent=(220, 220, 220))
    _write_pattern_image(views_dir / f"{label}.chase.png", accent=(120, 90, 60))
    artifact = run_dir / "run_result.json"
    artifact.write_text(
        json.dumps(
            {
                "alignment_artifact": str(run_dir / "alignment_residuals.json"),
                "alignment_transform_source": "reviewed_correspondence_fit",
                "robot_view_steps": [
                    {
                        "label": label,
                        "waypoint_id": "generated_exploration_002",
                        "robot_pose_applied": True,
                        "alignment_artifact": str(run_dir / "alignment_residuals.json"),
                        "alignment_transform_source": "reviewed_correspondence_fit",
                        "camera_control_contract": _robot_camera_control_contract(),
                        "views": {
                            "fpv": f"robot_views/{label}.fpv.png",
                            "chase": f"robot_views/{label}.chase.png",
                        },
                    }
                ],
            },
            indent=2,
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )
    return artifact


def _write_b1_navigation_smoke_artifact(
    run_dir: Path,
    *,
    fpv_path: str,
    chase_path: str,
) -> Path:
    run_dir.mkdir(parents=True, exist_ok=True)
    artifact = run_dir / "navigation_smoke.json"
    artifact.write_text(
        json.dumps(
            {
                "schema": "b1_map12_navigation_smoke_v1",
                "alignment_artifact": str(run_dir / "alignment_residuals.json"),
                "alignment_transform_source": "reviewed_correspondence_fit",
                "waypoint_evidence": [
                    {
                        "waypoint_id": "point_a",
                        "robot_pose_applied": True,
                        "alignment_artifact": str(run_dir / "alignment_residuals.json"),
                        "alignment_transform_source": "reviewed_correspondence_fit",
                        "views": {"fpv": fpv_path, "chase": chase_path},
                    }
                ],
            },
            indent=2,
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )
    return artifact


def _robot_camera_control_contract() -> dict[str, object]:
    return {
        "agent_facing_fpv": {
            "camera_prim_path": "/World/robot_0/head_camera",
            "robot_mounted": True,
            "source": "isaac_lab_camera_rgb_robot_mounted_head_camera:fpv",
        },
        "report_chase_view": {
            "source": "isaac_lab_camera_rgb_scene_camera:chase",
        },
    }


def _write_pattern_image(path: Path, *, accent: tuple[int, int, int]) -> None:
    image = Image.new("RGB", (96, 64), (48, 56, 64))
    pixels = image.load()
    for y in range(image.height):
        for x in range(image.width):
            if (x // 6 + y // 4) % 2 == 0:
                pixels[x, y] = accent
            elif x == y or x + y == image.width - 1:
                pixels[x, y] = (20, 24, 28)
    image.save(path)
