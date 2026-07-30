from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

from roboclaws.maps.b1_alignment import (
    ALIGNMENT_ANCHOR_ROLE,
    validate_correspondence_manifest,
)
from roboclaws.maps.b1_semantic_anchor_suggestions import (
    build_semantic_review_packet,
    render_semantic_review_report,
)
from roboclaws.maps.b1_semantic_projection import build_semantic_projection
from roboclaws.maps.b1_semantic_review_promotion import (
    PromotionError,
    build_reviewed_correspondence_manifest,
)
from tests.contract.maps.b1_map12_verified_alignment_support import (
    PROMOTE_REVIEW_PACKET_MODULE,
    REPO_ROOT,
    SEMANTIC_PROJECTION_MODULE,
    accepted_room_reference,
    correspondence_manifest,
    passing_anchors,
    pending_room_reference,
    room_semantics_reference,
    semantic_review_packet,
)


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
