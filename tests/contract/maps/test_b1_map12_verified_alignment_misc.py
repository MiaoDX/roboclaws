from __future__ import annotations

import json
from pathlib import Path

import pytest

from roboclaws.backends.isaaclab.b1_navigation_smoke import (
    navigation_smoke_has_distinct_pose_evidence,
)
from roboclaws.backends.isaaclab.b1_readiness_validation import (
    KNOWN_POOR_BBOX_SEED_SOURCE,
    validate_readiness_artifact,
    validate_waypoint_pose_requests_artifact,
)
from roboclaws.backends.isaaclab.b1_waypoint_pose_requests import (
    build_pose_request_artifact,
)
from roboclaws.maps.b1_alignment_artifact import build_alignment_residuals
from roboclaws.maps.b1_alignment_contract import (
    B1_MAP12_ALIGNMENT_RESIDUALS_SCHEMA,
    validate_alignment_residual_artifact,
    validate_correspondence_manifest,
)
from roboclaws.maps.b1_semantic_anchor_suggestions import (
    build_semantic_suggestions,
)
from tests.contract.maps.b1_map12_verified_alignment_support import (
    RAW_MAP12_BUNDLE,
    _test_map_polygon,
    accepted_anchor,
    correspondence_manifest,
    passing_anchors,
)
from tests.contract.maps.test_b1_map12_digital_twin_readiness import static_readiness_payload


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
