from __future__ import annotations

import json
from pathlib import Path

from roboclaws.maps.b1_alignment import (
    ALIGNMENT_ANCHOR_ROLE,
    B1_MAP12_CORRESPONDENCES_SCHEMA,
    SEMANTIC_ANCHOR_ROLE,
)
from scripts.maps.render_b1_scene_gaussian_topdown import (
    TOPDOWN_RENDER_SCHEMA,
    build_topdown_camera_request,
)

REPO_ROOT = Path(__file__).resolve().parents[3]

ALIGNMENT_MODULE = "roboclaws.maps.b1_alignment"

REVIEW_SCRIPT = REPO_ROOT / "scripts" / "maps" / "render_b1_map12_correspondence_review.py"

PROMOTE_REVIEW_PACKET_MODULE = "roboclaws.maps.b1_semantic_review_promotion"

PROMOTE_MANUAL_DRAFT_MODULE = "roboclaws.maps.b1_manual_draft_promotion"

CHECK_REVIEW_PACKET_FIT_SCRIPT = (
    REPO_ROOT / "scripts" / "maps" / "check_b1_map12_semantic_review_packet_fit.py"
)

SEMANTIC_ANCHOR_REVIEW_PACKET_SCRIPT = (
    REPO_ROOT / "scripts" / "maps" / "build_b1_map12_semantic_anchor_review_packet.py"
)

SEMANTIC_PROJECTION_MODULE = "roboclaws.maps.b1_semantic_projection"

RAW_MAP12_BUNDLE = REPO_ROOT / "assets" / "maps" / "agibot-robot-map-12"

VENDOR_MAP12_BUNDLE = (
    REPO_ROOT / "vendors" / "agibot_sdk" / "artifacts" / "maps" / ("robot_map_12") / "agibot"
)


def correspondence_manifest(*, anchors: list[dict[str, object]]) -> dict[str, object]:
    return {
        "schema": B1_MAP12_CORRESPONDENCES_SCHEMA,
        "source_map_frame": "robot_map_12_map",
        "target_scene_frame": "b1_rebuilt_scene_usd_world",
        "bbox_seed_policy": "known_poor_seed_only",
        "scene_projection_policy": {
            "horizontal_axes": ["x", "y"],
            "up_axis": "z",
            "source": "2rd_floor_seperated_scene_topdown_policy",
        },
        "anchors": anchors,
    }


def accepted_anchor(
    anchor_id: str,
    map_xy: tuple[float, float],
    scene_xy: tuple[float, float],
    *,
    navigation_area_id: str,
    asset_partition_id: str,
) -> dict[str, object]:
    anchor: dict[str, object] = {
        "anchor_id": anchor_id,
        "anchor_type": "door_center",
        "anchor_role": SEMANTIC_ANCHOR_ROLE,
        "navigation_area_id": navigation_area_id,
        "asset_partition_id": asset_partition_id,
        "map_xy": [map_xy[0], map_xy[1]],
        "scene_xyz": [scene_xy[0], scene_xy[1], 0.0],
        "evidence": {
            "map_image": "output/b1-map12/alignment/map_anchor.png",
            "scene_image": "output/b1-map12/alignment/scene_anchor.png",
            "operator_note": f"reviewed {anchor_id}",
        },
        "confidence": 0.85,
        "review_status": "accepted",
        "map_coordinate_source": "operator_map_pick",
        "scene_coordinate_source": "operator_scene_pick",
    }
    if asset_partition_id:
        anchor["map_polygon"] = _test_map_polygon()
    return anchor


def alignment_anchor(
    anchor_id: str,
    map_xy: tuple[float, float],
    scene_xy: tuple[float, float],
) -> dict[str, object]:
    anchor = accepted_anchor(
        anchor_id,
        map_xy,
        scene_xy,
        navigation_area_id="",
        asset_partition_id="",
    )
    anchor["anchor_role"] = ALIGNMENT_ANCHOR_ROLE
    anchor.pop("map_polygon", None)
    return anchor


def scene_topdown_render_packet(tmp_path: Path) -> Path:
    scene_image = tmp_path / "scene_topdown.png"
    scene_image.write_bytes(b"P5\n2 2\n255\n" + bytes([0, 80, 160, 255]))
    request = build_topdown_camera_request(
        scene_bounds=(-2.0, -1.0, 4.0, 5.0),
        width=2,
        height=2,
        camera_height_m=28.0,
        camera_y_offset_m=0.05,
        target_z_m=0.6,
        fov_deg=65.0,
        camera_mode="near-vertical-topdown",
    )
    scene_packet_path = tmp_path / "scene_gaussian_topdown.json"
    scene_packet_path.write_text(
        json.dumps(
            {
                "schema": TOPDOWN_RENDER_SCHEMA,
                "topdown_image": str(scene_image),
                "geometry_status": "rendered_gaussian_scene_topdown",
                "up_axis": "z",
                "horizontal_axes": ["x", "y"],
                "scene_xy_bounds": {"min_x": -2.0, "min_y": -1.0, "max_x": 4.0, "max_y": 5.0},
                "pixel_to_scene_xyz": request["topdown_pixel_to_scene_xyz"],
                "camera": request["views"][0],
            }
        ),
        encoding="utf-8",
    )
    return scene_packet_path


def passing_anchors() -> list[dict[str, object]]:
    source_points = [
        (-8.0, 0.0),
        (-5.0, 0.5),
        (-2.0, 2.0),
        (1.0, 4.0),
        (3.0, -2.0),
        (5.0, 3.5),
    ]
    areas = [
        ("west_corridor", "meeting_room_a"),
        ("west_corridor", "meeting_room_a"),
        ("central_floor", "meeting_room_b"),
        ("north_fixture_area", "meeting_room_c"),
        ("south_fixture_area", "reception_area_a"),
        ("storage_room_a", "storage_room_a"),
    ]
    anchors = []
    for index, ((x, y), (area_id, partition_id)) in enumerate(
        zip(source_points, areas, strict=True),
        start=1,
    ):
        scene = (1.2 * x + 3.0, 1.2 * y - 8.0)
        anchors.append(
            accepted_anchor(
                f"anchor_{index}",
                (x, y),
                scene,
                navigation_area_id=area_id,
                asset_partition_id=partition_id,
            )
        )
    return anchors


def semantic_review_packet(*, anchors: list[dict[str, object]]) -> dict[str, object]:
    packet = correspondence_manifest(anchors=anchors)
    accepted_count = sum(anchor.get("review_status") == "accepted" for anchor in anchors)
    proposed_count = sum(anchor.get("review_status") == "proposed" for anchor in anchors)
    packet.update(
        {
            "schema": "b1_map12_manual_anchor_semantic_review_packet_v1",
            "status": "human_reviewed" if accepted_count else "needs_human_review",
            "accepted_manifest_mutated": False,
            "accepted_anchor_count": accepted_count,
            "proposed_anchor_count": proposed_count,
            "policy": {
                "auto_accept": False,
                "review_required": True,
            },
        }
    )
    return packet


def room_semantics_reference(*, rooms: list[dict[str, object]]) -> dict[str, object]:
    return {
        "schema": "scene_room_semantic_overlay_overrides_v1",
        "rooms": rooms,
    }


def accepted_room_reference(
    *,
    asset_partition_id: str,
    room_label: str,
    category: str = "room",
) -> dict[str, object]:
    return {
        "asset_partition_id": asset_partition_id,
        "review_status": "accepted",
        "room_label": room_label,
        "category": category,
    }


def pending_room_reference(
    *,
    asset_partition_id: str,
    room_label: str,
    category: str = "room",
) -> dict[str, object]:
    return {
        "asset_partition_id": asset_partition_id,
        "review_status": "needs_review",
        "room_label": room_label,
        "category": category,
    }


def _test_map_polygon() -> list[dict[str, float]]:
    return [
        {"x": 0.0, "y": 0.0},
        {"x": 2.0, "y": 0.0},
        {"x": 2.0, "y": 2.0},
        {"x": 0.0, "y": 2.0},
    ]
