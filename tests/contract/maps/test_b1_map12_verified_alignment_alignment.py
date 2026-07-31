from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

from roboclaws.backends.isaaclab.b1_readiness_artifacts import readiness_artifact_with_alignment
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
    ALIGNMENT_ANCHOR_ROLE,
    B1_MAP12_ALIGNMENT_RESIDUALS_SCHEMA,
    validate_alignment_residual_artifact,
    validate_correspondence_manifest,
)
from roboclaws.maps.b1_map12_correspondence_review import (
    build_review_packet,
)
from roboclaws.maps.b1_semantic_projection import build_semantic_projection
from roboclaws.maps.b1_semantic_review_promotion import (
    build_reviewed_correspondence_manifest,
)
from scripts.maps.render_b1_map12_manual_alignment_overlay import (
    verified_transform as verified_overlay_transform,
)
from tests.contract.maps.b1_map12_verified_alignment_support import (
    ALIGNMENT_MODULE,
    CHECK_REVIEW_PACKET_FIT_SCRIPT,
    RAW_MAP12_BUNDLE,
    REPO_ROOT,
    SEMANTIC_PROJECTION_MODULE,
    accepted_anchor,
    alignment_anchor,
    correspondence_manifest,
    passing_anchors,
    scene_topdown_render_packet,
    semantic_review_packet,
)
from tests.contract.maps.test_b1_map12_digital_twin_readiness import static_readiness_payload


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
