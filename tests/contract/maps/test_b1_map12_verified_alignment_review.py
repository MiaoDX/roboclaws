from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

from roboclaws.maps.b1_alignment_artifact import build_alignment_residuals
from roboclaws.maps.b1_alignment_contract import (
    ALIGNMENT_ANCHOR_ROLE,
    SEMANTIC_ANCHOR_ROLE,
)
from roboclaws.maps.b1_manual_draft_promotion import (
    build_verification_manifest,
)
from roboclaws.maps.b1_map12_correspondence_report import render_review_report
from roboclaws.maps.b1_map12_correspondence_review import (
    build_review_packet,
)
from roboclaws.maps.b1_semantic_review_promotion import (
    PromotionError,
    build_reviewed_correspondence_manifest,
)
from scripts.maps.build_b1_map12_semantic_anchor_review_packet import (
    build_semantic_anchor_review_packet,
)
from tests.contract.maps.b1_map12_verified_alignment_support import (
    PROMOTE_MANUAL_DRAFT_MODULE,
    RAW_MAP12_BUNDLE,
    REPO_ROOT,
    REVIEW_SCRIPT,
    SEMANTIC_ANCHOR_REVIEW_PACKET_SCRIPT,
    VENDOR_MAP12_BUNDLE,
    alignment_anchor,
    correspondence_manifest,
    passing_anchors,
    scene_topdown_render_packet,
    semantic_review_packet,
)


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


def test_strict_review_promotion_rejects_accepted_anchor_without_role() -> None:
    anchors = passing_anchors()
    anchors[0].pop("anchor_role")
    packet = semantic_review_packet(anchors=anchors)

    with pytest.raises(PromotionError, match="needs anchor_role"):
        build_reviewed_correspondence_manifest(packet)


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
