from __future__ import annotations

import json
from pathlib import Path

from PIL import Image

from scripts.isaac_lab_cleanup.check_b1_map12_readiness import (
    DEFAULT_B1_VISUAL_ROUTE_SCENE_USD,
    KNOWN_POOR_BBOX_SEED_POLICY,
    NAVIGATION_PROVENANCE,
    NAVIGATION_SMOKE_SCHEMA,
    SEMANTIC_SOURCE,
    SEMANTIC_USD_BLOCKED,
)


def write_b1_robot_proof_artifacts(root: Path) -> tuple[Path, Path]:
    alignment_path = root / "output/b1-map12/alignment/alignment_residuals.json"
    navigation_path = (
        root / "output/b1-map12/navigation-smoke/residual-overlay/navigation_smoke.json"
    )
    fpv_1 = navigation_path.parent / "waypoint_01_views/wp_1.fpv.png"
    fpv_2 = navigation_path.parent / "waypoint_02_views/wp_2.fpv.png"
    _write_reviewable_image(fpv_1, offset=0)
    _write_reviewable_image(fpv_2, offset=40)
    alignment_path.parent.mkdir(parents=True, exist_ok=True)
    navigation_path.parent.mkdir(parents=True, exist_ok=True)
    alignment_path.write_text(json.dumps(_alignment_payload()) + "\n", encoding="utf-8")
    navigation_path.write_text(
        json.dumps(_navigation_payload(alignment_path=alignment_path, fpv_1=fpv_1, fpv_2=fpv_2))
        + "\n",
        encoding="utf-8",
    )
    return alignment_path, navigation_path


def _alignment_payload() -> dict[str, object]:
    return {
        "schema": "b1_map12_scene_alignment_residuals_v1",
        "global_alignment_status": "verified",
        "bbox_seed_policy": KNOWN_POOR_BBOX_SEED_POLICY,
        "manipulation_supported": False,
        "object_receptacle_usd_binding_status": "blocked_out_of_scope",
        "selected_transform": {"source": "reviewed_correspondence_fit"},
        "selected_transform_type": "rigid_2d",
        "residual_evidence": {
            "status": "available",
            "matched_anchor_count": 6,
            "transform_source": "reviewed_correspondence_fit",
        },
        "area_alignment": [],
    }


def _navigation_payload(*, alignment_path: Path, fpv_1: Path, fpv_2: Path) -> dict[str, object]:
    pose_1 = {
        "frame": "b1_rebuilt_scene_usd_world_candidate",
        "x": -4.0,
        "y": -8.0,
        "z": 0.0,
        "yaw_deg": 0.0,
    }
    pose_2 = {**pose_1, "x": -2.0, "y": -7.0}
    return {
        "schema": NAVIGATION_SMOKE_SCHEMA,
        "status": "passed",
        "b1_scene_usd": str(DEFAULT_B1_VISUAL_ROUTE_SCENE_USD),
        "visual_route": {
            "scene_id": "B1_floor2_slow",
            "scene_usd": str(DEFAULT_B1_VISUAL_ROUTE_SCENE_USD),
            "selected": True,
            "status": "same_pose_render_verified",
        },
        "robot_navigation_supported": True,
        "robot_navigation_provenance": NAVIGATION_PROVENANCE,
        "navigation_provenance": "kinematic_pose_driven",
        "alignment_artifact": str(alignment_path),
        "alignment_transform_source": "reviewed_correspondence_fit",
        "planner_backed": False,
        "physical_robot": False,
        "semantic_source": SEMANTIC_SOURCE,
        "semantic_usd_binding_status": SEMANTIC_USD_BLOCKED,
        "semantic_anchors_are_usd_truth": False,
        "usd_object_index_ready": False,
        "usd_receptacle_index_ready": False,
        "manipulation_supported": False,
        "navigation_waypoint_count": 2,
        "robot_view_evidence_status": "available",
        "waypoint_evidence": [
            _waypoint("wp_1", pose=pose_1, alignment_path=alignment_path, fpv=fpv_1),
            _waypoint("wp_2", pose=pose_2, alignment_path=alignment_path, fpv=fpv_2),
        ],
    }


def _waypoint(
    waypoint_id: str,
    *,
    pose: dict[str, object],
    alignment_path: Path,
    fpv: Path,
) -> dict[str, object]:
    return {
        "waypoint_id": waypoint_id,
        "scene_usd": str(DEFAULT_B1_VISUAL_ROUTE_SCENE_USD),
        "robot_pose": pose,
        "robot_pose_applied": True,
        "alignment_artifact": str(alignment_path),
        "alignment_transform_source": "reviewed_correspondence_fit",
        "views": {"fpv": str(fpv)},
    }


def _write_reviewable_image(path: Path, *, offset: int) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    image = Image.new("RGB", (32, 24))
    pixels = image.load()
    for y in range(image.height):
        for x in range(image.width):
            pixels[x, y] = (
                (x * 7 + offset) % 256,
                (y * 11 + offset * 2) % 256,
                ((x + y) * 5 + offset * 3) % 256,
            )
    image.save(path)
