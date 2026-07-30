from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

from roboclaws.backends.isaaclab.b1_navigation_smoke import (
    navigation_smoke_has_distinct_pose_evidence,
    navigation_smoke_waypoints,
)
from roboclaws.backends.isaaclab.b1_readiness import (
    KNOWN_POOR_BBOX_SEED_SOURCE,
    readiness_artifact_with_alignment,
    validate_readiness_artifact,
    validate_waypoint_pose_requests_artifact,
)
from roboclaws.backends.isaaclab.b1_waypoint_pose_requests import (
    build_pose_request_artifact,
)
from roboclaws.maps.b1_alignment import (
    ALIGNMENT_ANCHOR_ROLE,
    B1_MAP12_ALIGNMENT_RESIDUALS_SCHEMA,
    B1_MAP12_CORRESPONDENCES_SCHEMA,
    SEMANTIC_ANCHOR_ROLE,
    build_alignment_residuals,
    validate_alignment_residual_artifact,
    validate_correspondence_manifest,
)
from roboclaws.maps.b1_manual_draft_promotion import (
    build_verification_manifest,
)
from roboclaws.maps.b1_semantic_anchor_suggestions import (
    build_semantic_review_packet,
    build_semantic_suggestions,
    render_semantic_review_report,
)
from roboclaws.maps.b1_semantic_projection import build_semantic_projection
from roboclaws.maps.b1_semantic_review_promotion import (
    PromotionError,
    build_reviewed_correspondence_manifest,
)
from scripts.maps.build_b1_map12_semantic_anchor_review_packet import (
    build_semantic_anchor_review_packet,
)
from scripts.maps.render_b1_map12_correspondence_review import (
    build_review_packet,
    render_review_report,
)
from scripts.maps.render_b1_map12_manual_alignment_overlay import (
    verified_transform as verified_overlay_transform,
)
from scripts.maps.render_b1_scene_gaussian_topdown import (
    TOPDOWN_RENDER_SCHEMA,
    build_topdown_camera_request,
)
from tests.contract.maps.test_b1_map12_digital_twin_readiness import static_readiness_payload

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


def test_manifest_rejects_accepted_anchor_from_known_poor_bbox_seed() -> None:
    anchor = accepted_anchor(
        "bbox_seed_prefill",
        (-1.0, 2.0),
        (3.0, -4.0),
        navigation_area_id="central_floor",
        asset_partition_id="meeting_room_b",
    )
    anchor["scene_coordinate_source"] = "known_poor_bbox_seed"
    manifest = correspondence_manifest(anchors=[anchor])

    errors = validate_correspondence_manifest(manifest)

    assert (
        "accepted anchor bbox_seed_prefill must not use known-poor bbox seed coordinates" in errors
    )


def test_manifest_rejects_legacy_y_up_xz_projection_policy() -> None:
    manifest = correspondence_manifest(anchors=passing_anchors()[:1])
    manifest["scene_projection_policy"] = {
        "horizontal_axes": ["x", "z"],
        "up_axis": "y",
        "source": "legacy_y_up_policy",
    }

    errors = validate_correspondence_manifest(manifest)

    assert "scene_projection_policy.horizontal_axes must be ['x', 'y']" in errors
    assert "scene_projection_policy.up_axis must be z" in errors


def test_fitter_keeps_alignment_candidate_without_six_reviewed_anchors(tmp_path: Path) -> None:
    manifest = correspondence_manifest(anchors=passing_anchors()[:3])

    payload = build_alignment_residuals(
        manifest,
        map_bundle=RAW_MAP12_BUNDLE,
        output_dir=tmp_path,
    )

    assert payload["schema"] == B1_MAP12_ALIGNMENT_RESIDUALS_SCHEMA
    assert payload["status"] == "insufficient_reviewed_anchors"
    assert payload["global_alignment_status"] == "candidate"
    assert payload["residual_evidence"]["status"] == "not_available"
    assert payload["previews"]["before_overlay"].endswith("alignment_before.png")


def test_fitter_selects_simple_verified_similarity_transform(tmp_path: Path) -> None:
    manifest = correspondence_manifest(anchors=passing_anchors())

    payload = build_alignment_residuals(
        manifest,
        map_bundle=RAW_MAP12_BUNDLE,
        output_dir=tmp_path,
    )

    assert validate_alignment_residual_artifact(payload) == []
    assert payload["global_alignment_status"] == "verified"
    assert payload["selected_transform_type"] == "similarity_2d"
    assert payload["residual_evidence"]["matched_anchor_count"] == 6
    assert payload["residual_evidence"]["max_residual_m"] == pytest.approx(0.0)
    assert payload["diagnostic_affine_transform"]["diagnostic_only"] is True


def test_fitter_verifies_geometry_alignment_anchors_without_semantic_ids(
    tmp_path: Path,
) -> None:
    anchors = []
    for anchor in passing_anchors():
        map_xy = anchor["map_xy"]
        scene_xyz = anchor["scene_xyz"]
        assert isinstance(map_xy, list)
        assert isinstance(scene_xyz, list)
        anchors.append(
            alignment_anchor(
                str(anchor["anchor_id"]),
                (float(map_xy[0]), float(map_xy[1])),
                (float(scene_xyz[0]), float(scene_xyz[1])),
            )
        )
    manifest = correspondence_manifest(anchors=anchors)

    payload = build_alignment_residuals(
        manifest,
        map_bundle=RAW_MAP12_BUNDLE,
        output_dir=tmp_path,
    )

    assert validate_alignment_residual_artifact(payload) == []
    assert payload["global_alignment_status"] == "verified"
    assert payload["accepted_navigation_area_count"] == 0
    assert payload["accepted_asset_partition_count"] == 0
    assert payload["area_alignment"] == []
    assert {row["anchor_role"] for row in payload["residuals"]} == {ALIGNMENT_ANCHOR_ROLE}


def test_readiness_promotes_verified_only_from_residual_artifact(tmp_path: Path) -> None:
    readiness = static_readiness_payload()
    readiness["map12_overlay"] = {
        "bbox_seed_policy": "known_poor_seed_only",
        "transform": {"source": KNOWN_POOR_BBOX_SEED_SOURCE},
    }
    alignment = build_alignment_residuals(
        correspondence_manifest(anchors=passing_anchors()),
        map_bundle=RAW_MAP12_BUNDLE,
        output_dir=tmp_path,
    )

    merged = readiness_artifact_with_alignment(
        readiness,
        alignment,
        alignment_artifact_path=tmp_path / "alignment_residuals.json",
    )

    assert merged["map12_overlay_status"] == "verified"
    assert merged["map12_to_b1_usd_transform_status"] == "verified"
    assert merged["residual_evidence"]["matched_anchor_count"] == 6
    assert validate_readiness_artifact(merged) == []


def test_waypoint_pose_requests_convert_verified_global_map12_points(tmp_path: Path) -> None:
    alignment = build_alignment_residuals(
        correspondence_manifest(anchors=passing_anchors()),
        map_bundle=RAW_MAP12_BUNDLE,
        output_dir=tmp_path,
    )
    alignment_path = tmp_path / "alignment_residuals.json"
    alignment_path.write_text(json.dumps(alignment), encoding="utf-8")

    payload = build_pose_request_artifact(
        alignment_artifact=alignment_path,
        points=[
            {"waypoint_id": "manual_point_a", "x": -8.0, "y": 0.0, "yaw_deg": 90.0},
            {"waypoint_id": "manual_point_b", "x": 1.0, "y": 4.0, "yaw": 0.25},
        ],
    )

    assert validate_waypoint_pose_requests_artifact(payload) == []
    assert payload["status"] == "ready"
    assert payload["waypoint_count"] == 2
    assert payload["blocked_request_count"] == 0
    assert payload["robot_navigation_supported"] is False
    assert payload["planner_backed"] is False
    assert payload["physical_robot"] is False
    first = payload["waypoints"][0]
    assert first["coverage_decision"]["status"] == "verified_global"
    assert first["alignment_transform_source"] == "reviewed_correspondence_fit"
    assert first["b1_pose"]["frame"] == "b1_rebuilt_scene_usd_world"
    assert first["b1_pose"]["x"] == pytest.approx(-6.6)
    assert first["b1_pose"]["y"] == pytest.approx(-8.0)
    assert first["b1_pose"]["yaw_deg"] == pytest.approx(90.0)


def test_waypoint_pose_requests_block_unverified_alignment_and_bad_point(
    tmp_path: Path,
) -> None:
    alignment = build_alignment_residuals(
        correspondence_manifest(anchors=passing_anchors()[:3]),
        map_bundle=RAW_MAP12_BUNDLE,
        output_dir=tmp_path,
    )
    alignment_path = tmp_path / "alignment_residuals.json"
    alignment_path.write_text(json.dumps(alignment), encoding="utf-8")

    payload = build_pose_request_artifact(
        alignment_artifact=alignment_path,
        points=[
            {"waypoint_id": "not_covered", "x": -8.0, "y": 0.0},
            {"waypoint_id": "bad_point", "x": "not-a-number", "y": 1.0},
        ],
    )

    assert validate_waypoint_pose_requests_artifact(payload) == []
    assert payload["status"] == "blocked"
    assert payload["waypoint_count"] == 0
    assert payload["blocked_request_count"] == 2
    assert payload["blocked_requests"][0]["request_status"] == "blocked"
    assert (
        "alignment artifact must be globally verified" in payload["blocked_requests"][0]["reason"]
    )
    assert payload["blocked_requests"][1]["request_status"] == "blocked"


def test_waypoint_pose_requests_convert_verified_local_area_points(tmp_path: Path) -> None:
    anchors = [
        accepted_anchor(
            "central_a",
            (0.0, 0.0),
            (10.0, -4.0),
            navigation_area_id="central_floor",
            asset_partition_id="meeting_room_b",
        ),
        accepted_anchor(
            "central_b",
            (1.0, 0.0),
            (11.0, -4.0),
            navigation_area_id="central_floor",
            asset_partition_id="meeting_room_b",
        ),
        accepted_anchor(
            "central_c",
            (0.0, 1.0),
            (10.0, -3.0),
            navigation_area_id="central_floor",
            asset_partition_id="meeting_room_b",
        ),
        accepted_anchor(
            "west_a",
            (10.0, 0.0),
            (-20.0, 30.0),
            navigation_area_id="west_corridor",
            asset_partition_id="meeting_room_a",
        ),
        accepted_anchor(
            "north_a",
            (0.0, 10.0),
            (35.0, 22.0),
            navigation_area_id="north_fixture_area",
            asset_partition_id="meeting_room_c",
        ),
        accepted_anchor(
            "south_a",
            (-10.0, -7.0),
            (-32.0, -24.0),
            navigation_area_id="south_fixture_area",
            asset_partition_id="reception_area_a",
        ),
    ]
    alignment = build_alignment_residuals(
        correspondence_manifest(anchors=anchors),
        map_bundle=RAW_MAP12_BUNDLE,
        output_dir=tmp_path,
    )
    alignment_path = tmp_path / "alignment_residuals.json"
    alignment_path.write_text(json.dumps(alignment), encoding="utf-8")

    payload = build_pose_request_artifact(
        alignment_artifact=alignment_path,
        points=[
            {
                "waypoint_id": "central_local_point",
                "navigation_area_id": "central_floor",
                "x": 0.5,
                "y": 0.5,
            }
        ],
    )

    assert validate_waypoint_pose_requests_artifact(payload) == []
    assert payload["status"] == "ready"
    point = payload["waypoints"][0]
    assert point["coverage_decision"]["status"] == "verified_local_area"
    assert point["coverage_decision"]["navigation_area_id"] == "central_floor"
    assert point["b1_pose"]["x"] == pytest.approx(10.5)
    assert point["b1_pose"]["y"] == pytest.approx(-3.5)


def test_waypoint_pose_requests_block_missing_or_unknown_local_area(tmp_path: Path) -> None:
    alignment = build_alignment_residuals(
        correspondence_manifest(
            anchors=[
                accepted_anchor(
                    "central_a",
                    (0.0, 0.0),
                    (10.0, -4.0),
                    navigation_area_id="central_floor",
                    asset_partition_id="meeting_room_b",
                ),
                accepted_anchor(
                    "central_b",
                    (1.0, 0.0),
                    (11.0, -4.0),
                    navigation_area_id="central_floor",
                    asset_partition_id="meeting_room_b",
                ),
                accepted_anchor(
                    "central_c",
                    (0.0, 1.0),
                    (10.0, -3.0),
                    navigation_area_id="central_floor",
                    asset_partition_id="meeting_room_b",
                ),
            ]
        ),
        map_bundle=RAW_MAP12_BUNDLE,
        output_dir=tmp_path,
    )
    alignment_path = tmp_path / "alignment_residuals.json"
    alignment_path.write_text(json.dumps(alignment), encoding="utf-8")

    payload = build_pose_request_artifact(
        alignment_artifact=alignment_path,
        points=[
            {"waypoint_id": "missing_area", "x": 0.5, "y": 0.5},
            {
                "waypoint_id": "unknown_area",
                "navigation_area_id": "not_verified_area",
                "x": 0.5,
                "y": 0.5,
            },
        ],
    )

    assert validate_waypoint_pose_requests_artifact(payload) == []
    assert payload["status"] == "blocked"
    assert payload["waypoint_count"] == 0
    assert payload["blocked_request_count"] == 2
    assert "point.navigation_area_id" in payload["blocked_requests"][0]["reason"]
    assert "not verified" in payload["blocked_requests"][1]["reason"]


def test_navigation_smoke_consumes_ready_pose_requests_and_blocks_bad_request_artifact(
    tmp_path: Path,
) -> None:
    alignment = build_alignment_residuals(
        correspondence_manifest(anchors=passing_anchors()),
        map_bundle=RAW_MAP12_BUNDLE,
        output_dir=tmp_path,
    )
    alignment_path = tmp_path / "alignment_residuals.json"
    alignment_path.write_text(json.dumps(alignment), encoding="utf-8")
    ready = build_pose_request_artifact(
        alignment_artifact=alignment_path,
        points=[
            {"waypoint_id": "manual_point_a", "x": -8.0, "y": 0.0},
            {"waypoint_id": "manual_point_b", "x": 1.0, "y": 4.0},
        ],
    )
    ready_path = tmp_path / "ready_pose_requests.json"
    ready_path.write_text(json.dumps(ready), encoding="utf-8")

    waypoints, blocker = navigation_smoke_waypoints(
        readiness={},
        waypoint_pose_requests=ready_path,
    )

    assert blocker == ""
    assert [item["waypoint_id"] for item in waypoints] == ["manual_point_a", "manual_point_b"]

    blocked = build_pose_request_artifact(
        alignment_artifact=alignment_path,
        points=[{"waypoint_id": "bad_point", "x": "not-a-number", "y": 1.0}],
    )
    blocked_path = tmp_path / "blocked_pose_requests.json"
    blocked_path.write_text(json.dumps(blocked), encoding="utf-8")

    waypoints, blocker = navigation_smoke_waypoints(
        readiness={"map12_overlay": {"candidate_waypoints": ready["waypoints"]}},
        waypoint_pose_requests=blocked_path,
    )

    assert waypoints == []
    assert "point must contain finite x/y" in blocker

    waypoints, blocker = navigation_smoke_waypoints(
        readiness={
            "map12_overlay": {
                "candidate_waypoints": [
                    {
                        "waypoint_id": "bbox_seed_waypoint",
                        "alignment_transform_source": KNOWN_POOR_BBOX_SEED_SOURCE,
                        "alignment_artifact": "",
                        "b1_pose": {"x": 0.0, "y": 0.0},
                    }
                ]
            }
        },
        waypoint_pose_requests=None,
    )

    assert waypoints == []
    assert "requires at least two residual-backed waypoint poses" in blocker


def test_navigation_smoke_pass_gate_requires_two_distinct_applied_poses() -> None:
    first = {
        "waypoint_id": "manual_point_a",
        "robot_pose_applied": True,
        "robot_pose": {"x": -4.0, "y": -8.0, "z": 0.0, "yaw_deg": 0.0},
    }
    duplicate = {
        "waypoint_id": "manual_point_b",
        "robot_pose_applied": True,
        "robot_pose": {"x": -4.0, "y": -8.0, "z": 0.0, "yaw_deg": 90.0},
    }
    second = {
        "waypoint_id": "manual_point_c",
        "robot_pose_applied": True,
        "robot_pose": {"x": -2.5, "y": -7.0, "z": 0.0, "yaw_deg": 90.0},
    }

    assert navigation_smoke_has_distinct_pose_evidence([first]) is False
    assert navigation_smoke_has_distinct_pose_evidence([first, duplicate]) is False
    assert navigation_smoke_has_distinct_pose_evidence([first, second]) is True
    assert (
        navigation_smoke_has_distinct_pose_evidence(
            [first, {**second, "robot_pose_applied": False}]
        )
        is False
    )


def test_readiness_records_area_verified_only_when_global_fit_fails(tmp_path: Path) -> None:
    anchors = [
        accepted_anchor(
            "central_a",
            (0.0, 0.0),
            (10.0, -4.0),
            navigation_area_id="central_floor",
            asset_partition_id="meeting_room_b",
        ),
        accepted_anchor(
            "central_b",
            (1.0, 0.0),
            (11.0, -4.0),
            navigation_area_id="central_floor",
            asset_partition_id="meeting_room_b",
        ),
        accepted_anchor(
            "central_c",
            (0.0, 1.0),
            (10.0, -3.0),
            navigation_area_id="central_floor",
            asset_partition_id="meeting_room_b",
        ),
        accepted_anchor(
            "west_a",
            (10.0, 0.0),
            (-20.0, 30.0),
            navigation_area_id="west_corridor",
            asset_partition_id="meeting_room_a",
        ),
        accepted_anchor(
            "north_a",
            (0.0, 10.0),
            (35.0, 22.0),
            navigation_area_id="north_fixture_area",
            asset_partition_id="meeting_room_c",
        ),
        accepted_anchor(
            "south_a",
            (-10.0, -7.0),
            (-32.0, -24.0),
            navigation_area_id="south_fixture_area",
            asset_partition_id="reception_area_a",
        ),
    ]
    alignment = build_alignment_residuals(
        correspondence_manifest(anchors=anchors),
        map_bundle=RAW_MAP12_BUNDLE,
        output_dir=tmp_path,
    )

    merged = readiness_artifact_with_alignment(
        {
            **static_readiness_payload(),
            "map12_overlay": {
                "bbox_seed_policy": "known_poor_seed_only",
                "transform": {"source": KNOWN_POOR_BBOX_SEED_SOURCE},
            },
        },
        alignment,
        alignment_artifact_path=tmp_path / "alignment_residuals.json",
    )

    assert alignment["global_alignment_status"] == "candidate"
    assert alignment["residual_evidence"]["passed"] is False
    assert any(
        item["navigation_area_id"] == "central_floor"
        and item["alignment_status"] == "verified"
        and item["matched_anchor_count"] == 3
        for item in alignment["area_alignment"]
    )
    assert merged["map12_overlay_status"] == "candidate"
    assert merged["map12_to_b1_usd_transform_status"] == "area_verified_only"
    assert validate_readiness_artifact(merged) == []


def test_readiness_rejects_verified_overlay_without_residual_evidence() -> None:
    payload = static_readiness_payload()
    payload["map12_overlay"] = {
        "bbox_seed_policy": "known_poor_seed_only",
        "transform": {"source": KNOWN_POOR_BBOX_SEED_SOURCE},
        "verified_transform": {"source": "reviewed_correspondence_fit"},
    }
    payload["map12_overlay_status"] = "verified"
    payload["map12_to_b1_usd_transform_status"] = "verified"

    errors = validate_readiness_artifact(payload)

    assert "verified overlay requires residual evidence" in errors
    assert "verified overlay requires at least six matched anchors" in errors


def test_readiness_rejects_verified_overlay_from_bbox_seed() -> None:
    payload = static_readiness_payload()
    payload["map12_overlay"] = {
        "bbox_seed_policy": "known_poor_seed_only",
        "transform": {"source": KNOWN_POOR_BBOX_SEED_SOURCE},
        "verified_transform": {"source": KNOWN_POOR_BBOX_SEED_SOURCE},
    }
    payload["map12_overlay_status"] = "verified"
    payload["map12_to_b1_usd_transform_status"] = "verified"
    payload["residual_evidence"] = {
        "status": "available",
        "matched_anchor_count": 6,
        "transform_source": KNOWN_POOR_BBOX_SEED_SOURCE,
    }

    errors = validate_readiness_artifact(payload)

    assert "verified overlay must not use known-poor bbox seed" in errors
    assert "verified overlay cannot use the bbox-fit transform as its verified transform" in errors


def test_area_verified_only_requires_verified_area_with_three_anchors() -> None:
    payload = static_readiness_payload()
    payload["map12_overlay"] = {
        "bbox_seed_policy": "known_poor_seed_only",
        "transform": {"source": KNOWN_POOR_BBOX_SEED_SOURCE},
    }
    payload["map12_to_b1_usd_transform_status"] = "area_verified_only"
    payload["area_alignment"] = [
        {
            "navigation_area_id": "central_floor",
            "alignment_status": "verified",
            "matched_anchor_count": 3,
            "max_residual_m": 0.3,
        }
    ]

    assert validate_readiness_artifact(payload) == []

    payload["area_alignment"][0]["matched_anchor_count"] = 2
    alignment_errors = validate_alignment_residual_artifact(
        {
            "schema": B1_MAP12_ALIGNMENT_RESIDUALS_SCHEMA,
            "bbox_seed_policy": "known_poor_seed_only",
            "manipulation_supported": False,
            "object_receptacle_usd_binding_status": "blocked_out_of_scope",
            "global_alignment_status": "candidate",
            "residual_evidence": {"status": "not_available", "matched_anchor_count": 0},
            "selected_transform": {},
            "area_alignment": payload["area_alignment"],
        }
    )

    assert "area verified alignment requires at least three matched anchors" in alignment_errors


def test_alignment_fitter_cli_writes_residual_artifact(tmp_path: Path) -> None:
    manifest_path = tmp_path / "scene_correspondences.json"
    output_dir = tmp_path / "alignment"
    manifest_path.write_text(
        json.dumps(correspondence_manifest(anchors=passing_anchors())),
        encoding="utf-8",
    )

    subprocess.run(
        [
            sys.executable,
            "-m",
            ALIGNMENT_MODULE,
            "--correspondences",
            str(manifest_path),
            "--map-bundle",
            str(RAW_MAP12_BUNDLE),
            "--output-dir",
            str(output_dir),
        ],
        check=True,
    )

    payload = json.loads((output_dir / "alignment_residuals.json").read_text(encoding="utf-8"))
    assert payload["global_alignment_status"] == "verified"
    assert payload["validation"]["status"] == "passed"


def test_review_packet_keeps_proposed_anchor_pending(tmp_path: Path) -> None:
    manifest = correspondence_manifest(
        anchors=[
            {
                "anchor_id": "draft_anchor",
                "anchor_type": "door_center",
                "navigation_area_id": "central_floor",
                "asset_partition_id": "meeting_room_b",
                "map_xy": None,
                "scene_xyz": None,
                "review_status": "proposed",
                "evidence": {"operator_note": "needs explicit picks"},
            }
        ]
    )

    packet = build_review_packet(
        manifest,
        map_bundle=RAW_MAP12_BUNDLE,
        scene_topdown_render_path=scene_topdown_render_packet(tmp_path),
    )

    assert packet["schema"] == "b1_map12_correspondence_review_packet_v1"
    assert packet["review_status"] == "review_pending"
    assert packet["accepted_anchor_count"] == 0
    assert packet["fit_ready_anchor_count"] == 0
    assert packet["anchors"][0]["anchor_role"] == ALIGNMENT_ANCHOR_ROLE
    assert packet["anchors"][0]["review_action"] == (
        "pick explicit map_xy and scene_xyz, then mark accepted after operator review"
    )


def test_manual_draft_promotion_is_explicit_verification_only() -> None:
    draft = correspondence_manifest(
        anchors=[
            {
                "anchor_id": "manual_draft_anchor",
                "anchor_type": "operator_correspondence",
                "navigation_area_id": "",
                "asset_partition_id": "",
                "map_xy": [1.0, 2.0],
                "scene_xyz": [3.0, 4.0, 0.0],
                "review_status": "proposed",
                "evidence": {"source": "two_map_anchor_picker"},
            }
        ]
    )

    payload = build_verification_manifest(draft)

    assert payload["verification_only"] is True
    assert payload["anchors"][0]["review_status"] == "accepted"
    assert payload["anchors"][0]["anchor_role"] == ALIGNMENT_ANCHOR_ROLE
    assert payload["anchors"][0]["navigation_area_id"] == ""
    assert payload["anchors"][0]["asset_partition_id"] == ""
    assert "geometry only" in payload["anchors"][0]["evidence"]["verification_note"]


@pytest.mark.parametrize(
    ("source_text", "expected_error"),
    [
        (None, "manual draft source is missing"),
        ("{not-json\n", "manual draft source must contain valid JSON object"),
        ("[]\n", "manual draft source must contain a JSON object"),
    ],
)
def test_manual_draft_promotion_cli_rejects_bad_source_json(
    tmp_path: Path,
    source_text: str | None,
    expected_error: str,
) -> None:
    draft_path = tmp_path / "manual_draft.json"
    output = tmp_path / "verification-only.json"
    if source_text is not None:
        draft_path.write_text(source_text, encoding="utf-8")

    completed = subprocess.run(
        [
            sys.executable,
            "-m",
            PROMOTE_MANUAL_DRAFT_MODULE,
            "--draft",
            str(draft_path),
            "--output",
            str(output),
        ],
        capture_output=True,
        text=True,
    )

    assert (completed.returncode, output.exists()) == (2, False)
    assert expected_error in completed.stderr and str(draft_path) in completed.stderr


def test_manual_anchor_semantic_suggestions_do_not_accept_anchors() -> None:
    draft = correspondence_manifest(
        anchors=[
            {
                "anchor_id": "manual_draft_anchor",
                "anchor_type": "operator_correspondence",
                "navigation_area_id": "",
                "asset_partition_id": "",
                "map_xy": [1.0, 1.0],
                "scene_xyz": [1.0, 1.0, 0.0],
                "review_status": "proposed",
            }
        ]
    )
    room_projection = {
        "schema": "b1_map12_semantic_projection_v1",
        "rooms": [
            {
                "room_id": "room_a",
                "navigation_area_id": "area_a",
                "asset_partition_id": "partition_a",
                "room_label": "Room A",
                "review_status": "accepted",
                "map_polygon": _test_map_polygon(),
            }
        ],
    }
    scene_diagnostic = {
        "partitions": [
            {
                "partition_id": "partition_a",
                "scene_frame_bounds": {
                    "min_x": 0.0,
                    "min_y": 0.0,
                    "max_x": 2.0,
                    "max_y": 2.0,
                },
            }
        ]
    }

    payload = build_semantic_suggestions(
        draft=draft,
        room_projection=room_projection,
        scene_diagnostic=scene_diagnostic,
    )

    suggestion = payload["suggestions"][0]
    assert payload["policy"]["accepted_manifest_mutated"] is False
    assert suggestion["review_status"] == "proposed_suggestion"
    assert suggestion["suggestion_status"] == "strong_candidate_needs_review"
    assert suggestion["recommended_navigation_area_id"] == "area_a"
    assert suggestion["recommended_asset_partition_id"] == "partition_a"


def test_manual_anchor_semantic_review_packet_keeps_anchors_proposed() -> None:
    draft = correspondence_manifest(
        anchors=[
            {
                "anchor_id": "manual_draft_anchor",
                "anchor_type": "operator_correspondence",
                "navigation_area_id": "",
                "asset_partition_id": "",
                "map_xy": [1.0, 1.0],
                "scene_xyz": [1.0, 1.0, 0.0],
                "review_status": "proposed",
            }
        ]
    )
    suggestions = {
        "schema": "b1_map12_manual_anchor_semantic_suggestions_v1",
        "strong_candidate_count": 1,
        "suggestions": [
            {
                "anchor_id": "manual_draft_anchor",
                "suggestion_status": "strong_candidate_needs_review",
                "recommended_navigation_area_id": "area_a",
                "recommended_asset_partition_id": "partition_a",
                "map_candidates": [{"map_area_id": "area_a", "distance_m": 0.0}],
                "scene_candidates": [{"partition_id": "partition_a", "distance_m": 0.0}],
            }
        ],
    }

    packet = build_semantic_review_packet(draft=draft, suggestions=suggestions)

    assert packet["schema"] == "b1_map12_manual_anchor_semantic_review_packet_v1"
    assert packet["status"] == "needs_human_review"
    assert packet["accepted_manifest_mutated"] is False
    assert packet["accepted_anchor_count"] == 0
    assert packet["proposed_anchor_count"] == 1
    anchor = packet["anchors"][0]
    assert anchor["review_status"] == "proposed"
    assert anchor["anchor_role"] == ALIGNMENT_ANCHOR_ROLE
    assert anchor["navigation_area_id"] == "area_a"
    assert anchor["asset_partition_id"] == "partition_a"
    assert anchor["semantic_review"]["status"] == "needs_human_review"
    assert anchor["semantic_review"]["acceptance_instructions"].startswith("Use anchor_role")


def test_manual_anchor_semantic_review_report_is_read_only() -> None:
    packet = {
        "schema": "b1_map12_manual_anchor_semantic_review_packet_v1",
        "status": "needs_human_review",
        "accepted_manifest_mutated": False,
        "accepted_anchor_count": 0,
        "proposed_anchor_count": 1,
        "strong_candidate_count": 1,
        "anchors": [
            {
                "anchor_id": "manual_draft_anchor",
                "review_status": "proposed",
                "navigation_area_id": "area_a",
                "asset_partition_id": "partition_a",
                "map_xy": [1.0, 1.0],
                "scene_xyz": [1.0, 1.0, 0.0],
                "semantic_review": {
                    "suggestion_status": "strong_candidate_needs_review",
                    "map_candidates": [{"map_area_id": "area_a", "distance_m": 0.0}],
                    "scene_candidates": [{"partition_id": "partition_a", "distance_m": 0.0}],
                },
            }
        ],
    }

    html = render_semantic_review_report(packet)

    assert 'id="semantic-review-report"' in html
    assert "Review aid only" in html
    assert "manual_draft_anchor" in html
    assert "area_a" in html
    assert "partition_a" in html
    assert "Accepted: <strong>0</strong>" in html
    assert "mark accepted" not in html


def test_strict_semantic_review_promotion_rejects_proposed_packet() -> None:
    packet = semantic_review_packet(
        anchors=[
            {
                "anchor_id": "manual_draft_anchor",
                "anchor_type": "operator_correspondence",
                "navigation_area_id": "area_a",
                "asset_partition_id": "partition_a",
                "map_xy": [1.0, 1.0],
                "scene_xyz": [1.0, 1.0, 0.0],
                "review_status": "proposed",
            }
        ]
    )

    with pytest.raises(PromotionError, match="no human-accepted anchors"):
        build_reviewed_correspondence_manifest(packet)


def test_strict_semantic_review_promotion_rejects_partial_accepted_packet() -> None:
    packet = semantic_review_packet(anchors=passing_anchors()[:5])

    with pytest.raises(PromotionError, match="at least 6 human-accepted anchors"):
        build_reviewed_correspondence_manifest(packet)


def test_strict_semantic_review_promotion_promotes_human_accepted_real_ids() -> None:
    packet = semantic_review_packet(anchors=passing_anchors())
    for anchor in packet["anchors"]:
        anchor["semantic_review"] = {
            "status": "needs_human_review",
            "map_candidates": [{"map_area_id": "candidate_only"}],
        }

    payload = build_reviewed_correspondence_manifest(packet)

    assert payload["schema"] == "b1_map12_scene_correspondences_v1"
    assert payload["promotion_policy"]["auto_accept"] is False
    assert len(payload["anchors"]) == 6
    assert "semantic_review" not in payload["anchors"][0]
    assert payload["anchors"][0]["navigation_area_id"]
    assert payload["anchors"][0]["asset_partition_id"]
    assert validate_correspondence_manifest(payload) == []


def test_semantic_anchor_review_packet_generates_proposed_room_interior_anchors() -> None:
    room_projection = {
        "schema": "b1_map12_semantic_projection_v1",
        "rooms": [
            {
                "room_id": "meeting_room_b",
                "navigation_area_id": "central_floor",
                "asset_partition_id": "meeting_room_b",
                "review_status": "accepted",
                "room_label": "Open kitchen",
                "category": "kitchen",
                "map_polygon": [
                    {"x": -4.0, "y": -1.0},
                    {"x": 2.0, "y": -1.0},
                    {"x": 2.0, "y": 5.0},
                    {"x": -4.0, "y": 5.0},
                ],
            },
            {
                "room_id": "draft_label",
                "navigation_area_id": "draft_area",
                "asset_partition_id": "draft_partition",
                "review_status": "draft",
                "map_polygon": [
                    {"x": 0.0, "y": 0.0},
                    {"x": 1.0, "y": 0.0},
                    {"x": 1.0, "y": 1.0},
                ],
            },
        ],
    }
    alignment = build_alignment_residuals(
        correspondence_manifest(
            anchors=[
                alignment_anchor("a1", (0.0, 0.0), (1.0, 2.0)),
                alignment_anchor("a2", (2.0, 0.0), (3.0, 2.0)),
                alignment_anchor("a3", (0.0, 2.0), (1.0, 4.0)),
                alignment_anchor("a4", (2.0, 2.0), (3.0, 4.0)),
                alignment_anchor("a5", (1.0, 3.0), (2.0, 5.0)),
                alignment_anchor("a6", (3.0, 1.0), (4.0, 3.0)),
            ]
        ),
        map_bundle=Path("map12"),
        output_dir=Path("output/test-b1-map12-semantic-anchor-review-packet"),
    )

    packet = build_semantic_anchor_review_packet(
        room_projection=room_projection,
        alignment=alignment,
        room_projection_path=Path("output/b1-map12/semantic-projection/semantic_projection.json"),
        alignment_artifact_path=Path("output/b1-map12/alignment/alignment_residuals.json"),
    )

    assert packet["schema"] == "b1_map12_manual_anchor_semantic_review_packet_v1"
    assert packet["status"] == "needs_human_review"
    assert packet["accepted_anchor_count"] == 0
    assert packet["proposed_anchor_count"] == 1
    anchor = packet["anchors"][0]
    assert anchor["anchor_role"] == SEMANTIC_ANCHOR_ROLE
    assert anchor["review_status"] == "proposed"
    assert anchor["navigation_area_id"] == "central_floor"
    assert anchor["asset_partition_id"] == "meeting_room_b"
    assert anchor["map_xy"] == pytest.approx([-1.0, 2.0])
    assert anchor["scene_xyz"] == pytest.approx([0.0, 4.0, 0.0])
    assert anchor["map_coordinate_source"] == "accepted_room_projection_polygon_center"
    assert anchor["scene_coordinate_source"] == "reviewed_correspondence_fit_projection"

    with pytest.raises(PromotionError, match="no human-accepted anchors"):
        build_reviewed_correspondence_manifest(packet)


@pytest.mark.parametrize(
    ("source_arg", "source_text", "expected_error"),
    [
        (
            "--room-projection",
            "{not-json\n",
            "room projection source must contain valid JSON object",
        ),
        (
            "--room-projection",
            "[]\n",
            "room projection source must contain a JSON object",
        ),
        (
            "--alignment-artifact",
            "{not-json\n",
            "alignment artifact source must contain valid JSON object",
        ),
        (
            "--alignment-artifact",
            "[]\n",
            "alignment artifact source must contain a JSON object",
        ),
    ],
)
def test_semantic_anchor_review_packet_cli_rejects_bad_source_json(
    tmp_path: Path,
    source_arg: str,
    source_text: str,
    expected_error: str,
) -> None:
    bad_path = tmp_path / "bad.json"
    output_path = tmp_path / "semantic_anchor_review_packet.json"
    bad_path.write_text(source_text, encoding="utf-8")
    args = [
        sys.executable,
        str(SEMANTIC_ANCHOR_REVIEW_PACKET_SCRIPT),
        "--room-projection",
        str(REPO_ROOT / "assets" / "maps" / "b1-map12-room-semantics.json"),
        "--alignment-artifact",
        str(REPO_ROOT / "assets" / "maps" / "b1-map12-room-semantics.json"),
        "--output",
        str(output_path),
    ]
    args[args.index(source_arg) + 1] = str(bad_path)

    completed = subprocess.run(args, capture_output=True, text=True)

    assert completed.returncode == 2
    assert not output_path.exists()
    assert "error: " in completed.stderr
    assert expected_error in completed.stderr
    assert str(bad_path) in completed.stderr


def test_semantic_projection_rejects_current_alignment_only_manifest() -> None:
    correspondences = json.loads(
        (REPO_ROOT / "assets" / "maps" / "b1-map12-scene-correspondences.json").read_text(
            encoding="utf-8"
        )
    )
    room_semantics = json.loads(
        (REPO_ROOT / "assets" / "maps" / "b1-map12-room-semantics.json").read_text(encoding="utf-8")
    )

    with pytest.raises(ValueError, match="accepted semantic anchors are required"):
        build_semantic_projection(
            correspondences=correspondences,
            room_semantics=room_semantics,
        )


def test_semantic_projection_cli_rejects_current_alignment_only_manifest(
    tmp_path: Path,
) -> None:
    output_path = tmp_path / "semantic_projection.json"

    completed = subprocess.run(
        [
            sys.executable,
            "-m",
            SEMANTIC_PROJECTION_MODULE,
            "--correspondences",
            str(REPO_ROOT / "assets" / "maps" / "b1-map12-scene-correspondences.json"),
            "--room-semantics",
            str(REPO_ROOT / "assets" / "maps" / "b1-map12-room-semantics.json"),
            "--output",
            str(output_path),
        ],
        capture_output=True,
        text=True,
    )

    assert completed.returncode == 2
    assert "accepted semantic anchors are required" in completed.stderr
    assert not output_path.exists()


@pytest.mark.parametrize(
    ("source_arg", "source_text", "expected_error"),
    [
        (
            "--correspondences",
            "{not-json\n",
            "correspondence manifest source must contain valid JSON object",
        ),
        (
            "--correspondences",
            "[]\n",
            "correspondence manifest source must contain a JSON object",
        ),
        (
            "--room-semantics",
            "{not-json\n",
            "room semantics source must contain valid JSON object",
        ),
        (
            "--room-semantics",
            "[]\n",
            "room semantics source must contain a JSON object",
        ),
    ],
)
def test_semantic_projection_cli_rejects_bad_source_json(
    tmp_path: Path,
    source_arg: str,
    source_text: str,
    expected_error: str,
) -> None:
    bad_path = tmp_path / "bad.json"
    output_path = tmp_path / "semantic_projection.json"
    bad_path.write_text(source_text, encoding="utf-8")
    args = [
        sys.executable,
        "-m",
        SEMANTIC_PROJECTION_MODULE,
        "--correspondences",
        str(REPO_ROOT / "assets" / "maps" / "b1-map12-scene-correspondences.json"),
        "--room-semantics",
        str(REPO_ROOT / "assets" / "maps" / "b1-map12-room-semantics.json"),
        "--output",
        str(output_path),
    ]
    args[args.index(source_arg) + 1] = str(bad_path)

    completed = subprocess.run(args, capture_output=True, text=True)

    assert completed.returncode == 2
    assert not output_path.exists()
    assert "error: " in completed.stderr
    assert expected_error in completed.stderr
    assert str(bad_path) in completed.stderr


def test_semantic_projection_rejects_proposed_review_packet_input() -> None:
    proposed_packet = semantic_review_packet(
        anchors=[{**passing_anchors()[0], "review_status": "proposed"}]
    )
    room_semantics = room_semantics_reference(
        rooms=[
            accepted_room_reference(
                asset_partition_id="meeting_room_a",
                room_label="Meeting room A",
            ),
            accepted_room_reference(
                asset_partition_id="meeting_room_b",
                room_label="Meeting room B",
            ),
            accepted_room_reference(
                asset_partition_id="meeting_room_c",
                room_label="Meeting room C",
            ),
            accepted_room_reference(
                asset_partition_id="reception_area_a",
                room_label="Main hall",
            ),
            accepted_room_reference(
                asset_partition_id="storage_room_a",
                room_label="Storage room",
            ),
        ]
    )

    with pytest.raises(ValueError, match="unexpected correspondence schema"):
        build_semantic_projection(
            correspondences=proposed_packet,
            room_semantics=room_semantics,
        )


def test_semantic_projection_projects_only_accepted_room_semantics() -> None:
    promoted = build_reviewed_correspondence_manifest(
        semantic_review_packet(anchors=passing_anchors())
    )
    room_semantics = room_semantics_reference(
        rooms=[
            accepted_room_reference(
                asset_partition_id="meeting_room_a",
                room_label="Meeting room A",
                category="meeting_room",
            ),
            accepted_room_reference(
                asset_partition_id="meeting_room_b",
                room_label="Meeting room B",
                category="meeting_room",
            ),
            accepted_room_reference(
                asset_partition_id="meeting_room_c",
                room_label="Meeting room C",
                category="meeting_room",
            ),
            accepted_room_reference(
                asset_partition_id="reception_area_a",
                room_label="Main hall",
                category="living_room",
            ),
            accepted_room_reference(
                asset_partition_id="storage_room_a",
                room_label="Storage room",
                category="storage_room",
            ),
        ]
    )

    payload = build_semantic_projection(
        correspondences=promoted,
        room_semantics=room_semantics,
        correspondences_path=Path("assets/maps/b1-map12-scene-correspondences.json"),
        room_semantics_path=Path("assets/maps/b1-map12-room-semantics.json"),
    )

    assert payload["schema"] == "b1_map12_semantic_projection_v1"
    assert payload["status"] == "verified_room_semantics"
    assert payload["semantic_anchor_count"] == 6
    assert payload["room_projection_count"] == 5
    assert payload["object_projection_status"] == "blocked_until_object_semantic_anchors"
    assert payload["objects"] == []
    rooms = {room["room_id"]: room for room in payload["rooms"]}
    assert rooms["meeting_room_a"]["semantic_anchor_count"] == 2
    assert rooms["meeting_room_a"]["navigation_area_id"] == "west_corridor"
    assert rooms["meeting_room_a"]["source_anchor_ids"] == ["anchor_1", "anchor_2"]
    assert rooms["meeting_room_b"]["room_label"] == "Meeting room B"
    assert rooms["meeting_room_b"]["category"] == "meeting_room"
    assert rooms["meeting_room_b"]["map_polygon"] == [
        {"x": 0.0, "y": 0.0},
        {"x": 2.0, "y": 0.0},
        {"x": 2.0, "y": 2.0},
        {"x": 0.0, "y": 2.0},
    ]


def test_semantic_projection_rejects_pending_room_semantics() -> None:
    promoted = build_reviewed_correspondence_manifest(
        semantic_review_packet(anchors=passing_anchors())
    )
    room_semantics = room_semantics_reference(
        rooms=[
            accepted_room_reference(
                asset_partition_id="meeting_room_a",
                room_label="Meeting room A",
            ),
            pending_room_reference(
                asset_partition_id="meeting_room_b",
                room_label="Meeting room B",
                category="meeting_room",
            ),
        ]
    )

    with pytest.raises(
        ValueError,
        match=(
            "accepted semantic anchors reference missing accepted DT room semantics: "
            ".*meeting_room_b"
        ),
    ):
        build_semantic_projection(
            correspondences=promoted,
            room_semantics=room_semantics,
        )


def test_semantic_projection_rejects_mixed_area_ids_for_one_partition() -> None:
    promoted = build_reviewed_correspondence_manifest(
        semantic_review_packet(anchors=passing_anchors())
    )
    promoted["anchors"][1]["navigation_area_id"] = "wrong_area"
    room_semantics = room_semantics_reference(
        rooms=[
            accepted_room_reference(
                asset_partition_id="meeting_room_a",
                room_label="Meeting room A",
            ),
            accepted_room_reference(
                asset_partition_id="meeting_room_b",
                room_label="Meeting room B",
            ),
            accepted_room_reference(
                asset_partition_id="meeting_room_c",
                room_label="Meeting room C",
            ),
            accepted_room_reference(
                asset_partition_id="reception_area_a",
                room_label="Main hall",
            ),
            accepted_room_reference(
                asset_partition_id="storage_room_a",
                room_label="Storage room",
            ),
        ]
    )

    with pytest.raises(ValueError, match="must share one navigation_area_id"):
        build_semantic_projection(
            correspondences=promoted,
            room_semantics=room_semantics,
        )


def test_semantic_projection_rejects_malformed_anchor_map_polygon() -> None:
    promoted = build_reviewed_correspondence_manifest(
        semantic_review_packet(anchors=passing_anchors())
    )
    promoted["anchors"][0]["map_polygon"][0].pop("y")
    room_semantics = room_semantics_reference(
        rooms=[
            accepted_room_reference(
                asset_partition_id="meeting_room_a",
                room_label="Meeting room A",
            ),
            accepted_room_reference(
                asset_partition_id="meeting_room_b",
                room_label="Meeting room B",
            ),
            accepted_room_reference(
                asset_partition_id="meeting_room_c",
                room_label="Meeting room C",
            ),
            accepted_room_reference(
                asset_partition_id="reception_area_a",
                room_label="Main hall",
            ),
            accepted_room_reference(
                asset_partition_id="storage_room_a",
                room_label="Storage room",
            ),
        ]
    )

    with pytest.raises(ValueError, match="map_polygon points must contain x/y"):
        build_semantic_projection(
            correspondences=promoted,
            room_semantics=room_semantics,
        )


def test_strict_review_promotion_promotes_alignment_anchors_without_semantic_ids() -> None:
    anchors = []
    for anchor in passing_anchors():
        map_xy = anchor["map_xy"]
        scene_xyz = anchor["scene_xyz"]
        assert isinstance(map_xy, list)
        assert isinstance(scene_xyz, list)
        anchors.append(
            alignment_anchor(
                str(anchor["anchor_id"]),
                (float(map_xy[0]), float(map_xy[1])),
                (float(scene_xyz[0]), float(scene_xyz[1])),
            )
        )
    packet = semantic_review_packet(anchors=anchors)

    payload = build_reviewed_correspondence_manifest(packet)

    assert len(payload["anchors"]) == 6
    assert {anchor["anchor_role"] for anchor in payload["anchors"]} == {ALIGNMENT_ANCHOR_ROLE}
    assert {anchor["navigation_area_id"] for anchor in payload["anchors"]} == {""}
    assert {anchor["asset_partition_id"] for anchor in payload["anchors"]} == {""}
    assert validate_correspondence_manifest(payload) == []


def test_strict_review_promotion_rejects_accepted_anchor_without_role() -> None:
    anchors = passing_anchors()
    anchors[0].pop("anchor_role")
    packet = semantic_review_packet(anchors=anchors)

    with pytest.raises(PromotionError, match="needs anchor_role"):
        build_reviewed_correspondence_manifest(packet)


@pytest.mark.parametrize(
    ("field", "value", "message"),
    [
        ("navigation_area_id", "", "needs navigation_area_id"),
        ("asset_partition_id", "", "needs asset_partition_id"),
        ("navigation_area_id", "manual_draft_area_1", "uses synthetic navigation_area_id"),
        ("asset_partition_id", "manual_draft_region_1", "uses synthetic asset_partition_id"),
    ],
)
def test_strict_semantic_review_promotion_rejects_missing_or_synthetic_ids(
    field: str,
    value: str,
    message: str,
) -> None:
    anchors = passing_anchors()
    anchors[0][field] = value
    packet = semantic_review_packet(anchors=anchors)

    with pytest.raises(PromotionError, match=message):
        build_reviewed_correspondence_manifest(packet)


def test_strict_semantic_review_promotion_rejects_bbox_seed_coordinates() -> None:
    anchors = passing_anchors()
    anchors[0]["scene_coordinate_source"] = "known_poor_bbox_seed"
    packet = semantic_review_packet(anchors=anchors)

    with pytest.raises(PromotionError, match="must not use bbox seed coordinates"):
        build_reviewed_correspondence_manifest(packet)


@pytest.mark.parametrize(
    ("packet_update", "message"),
    [
        ({"accepted_anchor_count": 0}, "accepted_anchor_count does not match accepted anchors"),
        ({"proposed_anchor_count": 9}, "proposed_anchor_count does not match proposed anchors"),
        ({"accepted_manifest_mutated": True}, "accepted_manifest_mutated=false"),
        ({"policy": {"auto_accept": True, "review_required": True}}, "auto_accept=false"),
        ({"policy": {"auto_accept": False, "review_required": False}}, "review_required=true"),
    ],
)
def test_strict_semantic_review_promotion_rejects_inconsistent_packet_metadata(
    packet_update: dict[str, object],
    message: str,
) -> None:
    packet = semantic_review_packet(anchors=passing_anchors())
    packet.update(packet_update)

    with pytest.raises(PromotionError, match=message):
        build_reviewed_correspondence_manifest(packet)


def test_strict_semantic_review_promotion_check_mode_does_not_write(tmp_path: Path) -> None:
    packet = semantic_review_packet(anchors=passing_anchors())
    packet_path = tmp_path / "review_packet.json"
    output_path = tmp_path / "b1-map12-scene-correspondences.json"
    packet_path.write_text(json.dumps(packet), encoding="utf-8")

    completed = subprocess.run(
        [
            sys.executable,
            "-m",
            PROMOTE_REVIEW_PACKET_MODULE,
            "--review-packet",
            str(packet_path),
            "--output",
            str(output_path),
            "--check",
        ],
        check=True,
        capture_output=True,
        text=True,
    )

    summary = json.loads(completed.stdout)
    assert summary["accepted_anchor_count"] == 6
    assert summary["output_written"] is False
    assert summary["output"] == ""
    assert not output_path.exists()


def test_strict_semantic_review_promotion_cli_rejects_current_proposed_packet(
    tmp_path: Path,
) -> None:
    packet = semantic_review_packet(anchors=[{**passing_anchors()[0], "review_status": "proposed"}])
    packet_path = tmp_path / "review_packet.json"
    packet_path.write_text(json.dumps(packet), encoding="utf-8")

    completed = subprocess.run(
        [
            sys.executable,
            "-m",
            PROMOTE_REVIEW_PACKET_MODULE,
            "--review-packet",
            str(packet_path),
            "--output",
            str(tmp_path / "out.json"),
            "--check",
        ],
        capture_output=True,
        text=True,
    )

    assert completed.returncode == 2
    assert "no human-accepted anchors" in completed.stderr


@pytest.mark.parametrize(
    ("source_text", "expected_error"),
    [
        (None, "review packet source is missing"),
        ("{not-json\n", "review packet source must contain valid JSON object"),
        ("[]\n", "review packet source must contain a JSON object"),
    ],
)
def test_strict_semantic_review_promotion_cli_rejects_bad_packet_source_json(
    tmp_path: Path,
    source_text: str | None,
    expected_error: str,
) -> None:
    packet_path = tmp_path / "bad_review_packet.json"
    output_path = tmp_path / "b1-map12-scene-correspondences.json"
    if source_text is not None:
        packet_path.write_text(source_text, encoding="utf-8")

    completed = subprocess.run(
        [
            sys.executable,
            "-m",
            PROMOTE_REVIEW_PACKET_MODULE,
            "--review-packet",
            str(packet_path),
            "--output",
            str(output_path),
            "--check",
        ],
        capture_output=True,
        text=True,
    )

    assert completed.returncode == 2
    assert not output_path.exists()
    assert "error: " in completed.stderr
    assert expected_error in completed.stderr
    assert str(packet_path) in completed.stderr


def test_semantic_review_packet_fit_check_writes_preview_not_committed_manifest(
    tmp_path: Path,
) -> None:
    packet = semantic_review_packet(anchors=passing_anchors())
    packet_path = tmp_path / "review_packet.json"
    output_dir = tmp_path / "fit-check"
    committed_path = tmp_path / "b1-map12-scene-correspondences.json"
    packet_path.write_text(json.dumps(packet), encoding="utf-8")

    completed = subprocess.run(
        [
            sys.executable,
            str(CHECK_REVIEW_PACKET_FIT_SCRIPT),
            "--review-packet",
            str(packet_path),
            "--map-bundle",
            str(RAW_MAP12_BUNDLE),
            "--output-dir",
            str(output_dir),
        ],
        check=True,
        capture_output=True,
        text=True,
    )

    summary = json.loads(completed.stdout)
    assert summary["committed_manifest_written"] is False
    assert summary["accepted_anchor_count"] == 6
    assert summary["global_alignment_status"] == "verified"
    assert (output_dir / "promoted_correspondences.preview.json").is_file()
    assert (output_dir / "alignment_residuals.json").is_file()
    assert not committed_path.exists()


def test_semantic_review_packet_fit_check_rejects_proposed_packet(tmp_path: Path) -> None:
    packet = semantic_review_packet(anchors=[{**passing_anchors()[0], "review_status": "proposed"}])
    packet_path = tmp_path / "review_packet.json"
    packet_path.write_text(json.dumps(packet), encoding="utf-8")

    completed = subprocess.run(
        [
            sys.executable,
            str(CHECK_REVIEW_PACKET_FIT_SCRIPT),
            "--review-packet",
            str(packet_path),
            "--map-bundle",
            str(RAW_MAP12_BUNDLE),
            "--output-dir",
            str(tmp_path / "fit-check"),
        ],
        capture_output=True,
        text=True,
    )

    assert completed.returncode == 2
    assert "no human-accepted anchors" in completed.stderr


@pytest.mark.parametrize(
    ("source_text", "expected_error"),
    [
        (None, "review packet source is missing"),
        ("{not-json\n", "review packet source must contain valid JSON object"),
        ("[]\n", "review packet source must contain a JSON object"),
    ],
)
def test_semantic_review_packet_fit_check_rejects_bad_packet_source_json(
    tmp_path: Path,
    source_text: str | None,
    expected_error: str,
) -> None:
    packet_path = tmp_path / "bad_review_packet.json"
    output_dir = tmp_path / "fit-check"
    if source_text is not None:
        packet_path.write_text(source_text, encoding="utf-8")

    completed = subprocess.run(
        [
            sys.executable,
            str(CHECK_REVIEW_PACKET_FIT_SCRIPT),
            "--review-packet",
            str(packet_path),
            "--map-bundle",
            str(RAW_MAP12_BUNDLE),
            "--output-dir",
            str(output_dir),
        ],
        capture_output=True,
        text=True,
    )

    assert completed.returncode == 2
    assert not output_dir.exists()
    assert "error: " in completed.stderr
    assert expected_error in completed.stderr
    assert str(packet_path) in completed.stderr


def test_review_packet_loads_vendor_map_and_scene_diagnostic_export_template(
    tmp_path: Path,
) -> None:
    scene_packet_path = scene_topdown_render_packet(tmp_path)
    scene_image = tmp_path / "scene_topdown.png"

    packet = build_review_packet(
        correspondence_manifest(anchors=[]),
        map_bundle=VENDOR_MAP12_BUNDLE,
        correspondences_path=REPO_ROOT / "assets" / "maps" / "b1-map12-scene-correspondences.json",
        scene_topdown_render_path=scene_packet_path,
        output_dir=tmp_path,
    )

    assert packet["source_map"]["map_yaml"].endswith("nav2.yaml")
    assert packet["source_map"]["source_image"].endswith("occupancy.pgm")
    assert packet["source_map"]["image"].endswith("map12_source_map.png")
    assert packet["source_map"]["image_role"] == "browser_ready_picker_preview"
    assert Path(packet["source_map"]["image"]).is_file()
    assert packet["source_map"]["width_px"] > 0
    assert packet["source_map"]["height_px"] > 0
    assert packet["source_map"]["pixel_to_map_xy"]["origin_x"] == pytest.approx(-35.1000022888)
    assert packet["scene_topdown"]["status"] == "available"
    assert packet["scene_topdown"]["source_image"] == str(scene_image)
    assert packet["scene_topdown"]["image"].endswith("scene_topdown.png")
    assert Path(packet["scene_topdown"]["image"]).is_file()
    assert packet["scene_topdown"]["geometry_status"] == "rendered_gaussian_scene_topdown"
    assert packet["scene_topdown"]["display_role"] == "rendered_gaussian_scene_topdown"
    assert packet["scene_topdown"]["pixel_to_scene_xyz"]["status"] == "perspective_ray_plane_z0"
    assert packet["scene_topdown"]["pixel_to_scene_xyz"]["source"] == (
        "rendered_gaussian_scene_topdown_ray_plane_pick"
    )
    assert packet["scene_topdown"]["pixel_to_scene_xyz"]["z_plane"] == 0.0
    assert packet["export_manifest_template"]["scene_projection_policy"] == {
        "horizontal_axes": ["x", "y"],
        "source": "2rd_floor_seperated_scene_topdown_policy",
        "up_axis": "z",
    }
    assert packet["export_manifest_template"]["anchors"] == []


def test_manual_alignment_overlay_rejects_non_reviewed_transform_source() -> None:
    alignment = {
        "global_alignment_status": "verified",
        "selected_transform": {
            "type": "rigid_2d",
            "source": "auto_contour_min_area_rect_similarity_seed",
        },
    }

    with pytest.raises(ValueError, match="reviewed_correspondence_fit"):
        verified_overlay_transform(alignment)


def test_review_report_contains_two_map_picker_and_export_contract(tmp_path: Path) -> None:
    scene_packet_path = scene_topdown_render_packet(tmp_path)
    packet = build_review_packet(
        correspondence_manifest(anchors=[]),
        map_bundle=VENDOR_MAP12_BUNDLE,
        correspondences_path=tmp_path / "b1-map12-scene-correspondences.json",
        scene_topdown_render_path=scene_packet_path,
        output_dir=tmp_path,
    )

    html = render_review_report(
        packet,
        output_dir=tmp_path,
        packet_path=tmp_path / "correspondence_review_packet.json",
        correspondences_path=tmp_path / "b1-map12-scene-correspondences.json",
    )

    assert 'id="two-map-anchor-picker"' in html
    assert "map12_source_map.png" in html
    assert "scene_topdown.png" in html
    assert 'id="mapImage"' in html
    assert 'id="sceneImage"' in html
    assert "B1 Gaussian Scene Top-Down" in html
    assert "Rendered Gaussian scene picks may be accepted" in html
    assert '<option value="accepted">accepted</option>' in html
    assert 'scenePolicy.status === "non_metric"' not in html
    assert "function mapPixelToMapXY" in html
    assert "function scenePixelToSceneXYZ" in html
    assert "function downloadCorrespondenceManifest" in html
    assert "b1-map12-scene-correspondences.draft.json" in html
    assert "map_xy" in html
    assert "scene_xyz" in html
    assert "anchor_role" in html
    assert "scene_pick_policy" in html
    assert "rendered_gaussian_scene_topdown_ray_plane_pick" in html


def test_review_packet_rejects_label_inventory_scene_context(tmp_path: Path) -> None:
    scene_image = tmp_path / "scene_topdown.png"
    scene_image.write_bytes(b"P5\n2 2\n255\n" + bytes([0, 80, 160, 255]))
    scene_packet_path = tmp_path / "scene_topdown_diagnostic.json"
    scene_packet_path.write_text(
        json.dumps(
            {
                "schema": "b1_scene_topdown_diagnostic_v1",
                "topdown_image": str(scene_image),
                "geometry_status": "label_inventory_only",
                "up_axis": "z",
                "horizontal_axes": ["x", "y"],
            }
        ),
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="scene top-down render must use schema"):
        build_review_packet(
            correspondence_manifest(anchors=[]),
            map_bundle=VENDOR_MAP12_BUNDLE,
            scene_topdown_render_path=scene_packet_path,
            output_dir=tmp_path,
        )


def test_review_packet_requires_scene_topdown_render_file(tmp_path: Path) -> None:
    with pytest.raises(FileNotFoundError, match="scene top-down render source is missing"):
        build_review_packet(
            correspondence_manifest(anchors=[]),
            map_bundle=VENDOR_MAP12_BUNDLE,
            scene_topdown_render_path=tmp_path / "missing.json",
            output_dir=tmp_path,
        )


def test_review_packet_flags_seed_derived_accepted_anchor_not_fit_ready(tmp_path: Path) -> None:
    anchor = accepted_anchor(
        "seed_anchor",
        (-1.0, 2.0),
        (3.0, -4.0),
        navigation_area_id="central_floor",
        asset_partition_id="meeting_room_b",
    )
    anchor["scene_coordinate_source"] = "known_poor_bbox_seed"
    manifest = correspondence_manifest(anchors=[anchor])

    packet = build_review_packet(
        manifest,
        map_bundle=RAW_MAP12_BUNDLE,
        scene_topdown_render_path=scene_topdown_render_packet(tmp_path),
    )

    assert packet["review_status"] == "manifest_needs_fix"
    assert packet["accepted_anchor_count"] == 1
    assert packet["fit_ready_anchor_count"] == 0
    assert packet["anchors"][0]["uses_known_poor_bbox_seed"] is True
    assert "replace seed-derived coordinates" in packet["anchors"][0]["review_action"]


def test_review_cli_requires_scene_topdown_render_argument(tmp_path: Path) -> None:
    manifest_path = tmp_path / "scene_correspondences.json"
    manifest_path.write_text(
        json.dumps(correspondence_manifest(anchors=[])),
        encoding="utf-8",
    )

    completed = subprocess.run(
        [
            sys.executable,
            str(REVIEW_SCRIPT),
            "--correspondences",
            str(manifest_path),
            "--map-bundle",
            str(VENDOR_MAP12_BUNDLE),
            "--output-dir",
            str(tmp_path / "review"),
        ],
        capture_output=True,
        text=True,
    )

    assert completed.returncode != 0
    assert "--scene-topdown-render" in completed.stderr


def test_review_cli_writes_packet_with_rendered_scene_topdown(tmp_path: Path) -> None:
    manifest_path = tmp_path / "scene_correspondences.json"
    manifest_path.write_text(
        json.dumps(correspondence_manifest(anchors=[])),
        encoding="utf-8",
    )
    output_dir = tmp_path / "review"

    completed = subprocess.run(
        [
            sys.executable,
            str(REVIEW_SCRIPT),
            "--correspondences",
            str(manifest_path),
            "--map-bundle",
            str(VENDOR_MAP12_BUNDLE),
            "--scene-topdown-render",
            str(scene_topdown_render_packet(tmp_path)),
            "--output-dir",
            str(output_dir),
        ],
        check=True,
        capture_output=True,
        text=True,
    )

    summary = json.loads(completed.stdout)
    packet = json.loads((output_dir / "correspondence_review_packet.json").read_text())
    assert summary["status"] == "review_pending"
    assert packet["scene_topdown"]["geometry_status"] == "rendered_gaussian_scene_topdown"
    assert (output_dir / "correspondence_review.html").is_file()
