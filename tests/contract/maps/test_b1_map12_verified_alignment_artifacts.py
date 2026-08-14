from __future__ import annotations

import json
from pathlib import Path

from roboclaws.backends.isaaclab.b1_navigation_smoke import (
    navigation_smoke_waypoints,
)
from roboclaws.backends.isaaclab.b1_readiness_artifacts import readiness_artifact_with_alignment
from roboclaws.backends.isaaclab.b1_readiness_validation import (
    KNOWN_POOR_BBOX_SEED_SOURCE,
    validate_readiness_artifact,
)
from roboclaws.backends.isaaclab.b1_waypoint_pose_requests import (
    build_pose_request_artifact,
)
from roboclaws.maps.b1_alignment_artifact import build_alignment_residuals
from tests.contract.maps.b1_map12_verified_alignment_support import (
    RAW_MAP12_BUNDLE,
    correspondence_manifest,
    passing_anchors,
)
from tests.contract.maps.test_b1_map12_digital_twin_readiness import static_readiness_payload


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
