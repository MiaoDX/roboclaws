from __future__ import annotations

import json
from pathlib import Path

from PIL import Image

from roboclaws.backends.isaaclab.b1_readiness_artifacts import readiness_artifact_with_navigation
from roboclaws.backends.isaaclab.b1_readiness_inspection import inspect_scene_engine_asset_layout
from roboclaws.backends.isaaclab.b1_readiness_validation import (
    DEFAULT_B1_VISUAL_ROUTE_SCENE_USD,
    NAVIGATION_PROVENANCE,
    NAVIGATION_SMOKE_SCHEMA,
    READINESS_SCHEMA,
    SEMANTIC_SOURCE,
    SEMANTIC_USD_BLOCKED,
    validate_navigation_smoke_artifact,
    validate_readiness_artifact,
)


def static_readiness_payload() -> dict[str, object]:
    return {
        "schema": READINESS_SCHEMA,
        "static_precheck_only": True,
        "b1_geometry_loaded": True,
        "b1_geometry_source": "rebuilt_scene_engine_usd_meshes",
        "usd_object_index_ready": False,
        "usd_receptacle_index_ready": False,
        "map12_overlay_status": "candidate",
        "map12_to_b1_usd_transform_status": "unverified",
        "b1_geometry": {
            "renderable_robot_view_usd": {
                "path": "data/robot-data-lab/scene-engine/data/"
                "2rd_floor_seperated/storey_1/configuration/scene_base.usd"
            }
        },
        "semantic_source": SEMANTIC_SOURCE,
        "semantic_usd_binding_status": SEMANTIC_USD_BLOCKED,
        "semantic_anchors_are_usd_truth": False,
        "robot_navigation_supported": False,
        "robot_navigation_provenance": "pending_local_isaac_b1_map12_navigation_smoke",
        "navigation_waypoint_count": 0,
        "robot_view_evidence_status": "pending_local_isaac_navigation_smoke",
        "manipulation_supported": False,
    }


def navigation_payload(tmp_path: Path, *, same_pose: bool = False) -> dict[str, object]:
    first = tmp_path / "first.fpv.png"
    second = tmp_path / "second.fpv.png"
    _write_reviewable_image(first, offset=0)
    _write_reviewable_image(second, offset=40)
    pose_1 = {
        "frame": "b1_rebuilt_scene_usd_world_candidate",
        "x": -4.0,
        "y": -8.0,
        "z": 0.0,
        "yaw_deg": 0.0,
    }
    pose_2 = dict(pose_1 if same_pose else {**pose_1, "x": -2.0, "y": -7.0})
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
        "alignment_artifact": str(tmp_path / "alignment_residuals.json"),
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
            {
                "waypoint_id": "wp_1",
                "scene_usd": str(DEFAULT_B1_VISUAL_ROUTE_SCENE_USD),
                "robot_pose": pose_1,
                "robot_pose_applied": True,
                "alignment_artifact": str(tmp_path / "alignment_residuals.json"),
                "alignment_transform_source": "reviewed_correspondence_fit",
                "views": {"fpv": str(first)},
            },
            {
                "waypoint_id": "wp_2",
                "scene_usd": str(DEFAULT_B1_VISUAL_ROUTE_SCENE_USD),
                "robot_pose": pose_2,
                "robot_pose_applied": True,
                "alignment_artifact": str(tmp_path / "alignment_residuals.json"),
                "alignment_transform_source": "reviewed_correspondence_fit",
                "views": {"fpv": str(second)},
            },
        ],
    }


def _write_reviewable_image(path: Path, *, offset: int) -> None:
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


def _write_low_detail_gray_image(path: Path) -> None:
    Image.new("RGB", (32, 24), color=(73, 73, 73)).save(path)


def test_static_readiness_does_not_claim_navigation_or_manipulation() -> None:
    errors = validate_readiness_artifact(static_readiness_payload())

    assert errors == []


def test_scene_engine_layout_inventory_counts_rebuilt_partitions(tmp_path: Path) -> None:
    scene_root = tmp_path / "2rd_floor_seperated"
    for room_name in ("meeting_room_a", "storey_1"):
        room = scene_root / room_name
        (room / "configuration" / "materials").mkdir(parents=True)
        (room / "scene.usd").write_text("usd", encoding="utf-8")
        (room / "scene_gs.usda").write_text("gs", encoding="utf-8")
        (room / "config.yaml").write_text("config", encoding="utf-8")
        (room / "configuration" / "materials" / "chair.png").write_bytes(b"png")

    inventory = inspect_scene_engine_asset_layout(scene_root)

    assert inventory["schema"] == "scene_engine_rebuilt_asset_inventory_v1"
    assert inventory["partition_count"] == 2
    assert inventory["usd_scene_count"] == 2
    assert inventory["gaussian_layer_count"] == 2
    assert inventory["primary_scene_usd"].endswith("storey_1/scene_gs.usda")
    assert inventory["primary_mesh_scene_usd"].endswith("storey_1/scene.usd")
    assert inventory["partitions"][0]["material_count"] == 1


def test_static_readiness_rejects_robot_navigation_claim() -> None:
    payload = static_readiness_payload()
    payload["robot_navigation_supported"] = True
    payload["robot_navigation_provenance"] = NAVIGATION_PROVENANCE
    payload["navigation_waypoint_count"] = 2
    payload["robot_view_evidence_status"] = "available"

    errors = validate_readiness_artifact(payload)

    assert "static-only readiness must not claim robot navigation support" in errors


def test_readiness_rejects_usd_semantic_and_manipulation_claims() -> None:
    payload = static_readiness_payload()
    payload["usd_object_index_ready"] = True
    payload["usd_receptacle_index_ready"] = True
    payload["semantic_source"] = "usd_segmentation"
    payload["semantic_usd_binding_status"] = "ready"
    payload["semantic_anchors_are_usd_truth"] = True
    payload["manipulation_supported"] = True

    errors = validate_readiness_artifact(payload)

    assert "B1 USD object index must remain false until segmentation or manifest exists" in errors
    assert (
        "B1 USD receptacle index must remain false until segmentation or manifest exists" in errors
    )
    assert "semantic source must be Map 12 navigation-memory overlay" in errors
    assert "semantic USD binding must remain blocked" in errors
    assert "semantic anchors must not be presented as USD prim truth" in errors
    assert "manipulation must not be presented as supported" in errors


def test_navigation_artifact_accepts_distinct_pose_robot_view_evidence(tmp_path: Path) -> None:
    payload = navigation_payload(tmp_path)

    errors = validate_navigation_smoke_artifact(payload, require_files=True)

    assert errors == []


def test_navigation_artifact_rejects_same_pose_evidence(tmp_path: Path) -> None:
    payload = navigation_payload(tmp_path, same_pose=True)

    errors = validate_navigation_smoke_artifact(payload, require_files=True)

    assert "navigation waypoint robot poses must be distinct" in errors


def test_navigation_artifact_rejects_low_detail_gray_fpv_evidence(tmp_path: Path) -> None:
    payload = navigation_payload(tmp_path)
    _write_low_detail_gray_image(Path(payload["waypoint_evidence"][0]["views"]["fpv"]))

    errors = validate_navigation_smoke_artifact(payload, require_files=True)

    assert "waypoint 1 fpv: image has too little visual detail" in errors
    assert "waypoint 1 fpv: image has too few distinct colors" in errors


def test_navigation_artifact_rejects_missing_residual_alignment_provenance(
    tmp_path: Path,
) -> None:
    payload = navigation_payload(tmp_path)
    payload["alignment_artifact"] = ""
    payload["alignment_transform_source"] = "known_poor_bbox_seed"
    payload["waypoint_evidence"][0]["robot_pose_applied"] = False
    payload["waypoint_evidence"][0]["alignment_artifact"] = ""
    payload["waypoint_evidence"][0]["alignment_transform_source"] = "known_poor_bbox_seed"

    errors = validate_navigation_smoke_artifact(payload, require_files=True)

    assert "navigation artifact requires residual-backed alignment artifact provenance" in errors
    assert "navigation artifact requires reviewed correspondence transform source" in errors
    assert "waypoint 1 robot pose must be applied in Isaac" in errors
    assert "waypoint 1 missing alignment artifact provenance" in errors
    assert "waypoint 1 requires reviewed correspondence transform source" in errors


def test_navigation_artifact_rejects_semantic_usd_or_manipulation_claim(tmp_path: Path) -> None:
    payload = navigation_payload(tmp_path)
    payload["semantic_source"] = "usd_segmentation"
    payload["semantic_usd_binding_status"] = "ready"
    payload["manipulation_supported"] = True

    errors = validate_navigation_smoke_artifact(payload, require_files=True)

    assert "navigation semantic source must remain Map 12 overlay" in errors
    assert "navigation artifact must not claim semantic USD binding" in errors
    assert "navigation artifact must not claim manipulation support" in errors


def test_readiness_merge_only_claims_navigation_after_valid_smoke(tmp_path: Path) -> None:
    readiness = static_readiness_payload()
    navigation = navigation_payload(tmp_path)

    merged = readiness_artifact_with_navigation(
        readiness,
        navigation,
        navigation_artifact_path=tmp_path / "navigation_smoke.json",
    )

    assert merged["robot_navigation_supported"] is True
    assert merged["robot_navigation_provenance"] == NAVIGATION_PROVENANCE
    assert merged["robot_view_evidence_status"] == "available"
    assert validate_readiness_artifact(merged, require_navigation_success=True) == []
    json.dumps(merged)
