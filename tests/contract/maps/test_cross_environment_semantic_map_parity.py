from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

from roboclaws.maps.bundle import validate_nav2_map_bundle
from roboclaws.maps.spatial_contract import (
    DISPLAY_FRAME_STATUS_ABSENT,
    GEOMETRY_SOURCE_OPERATOR_NAVIGATION_ZONE,
    MAP_SPATIAL_CONTRACT_SCHEMA,
    POLYGON_ROLE_NAVIGATION_AREA,
    POLYGON_ROLE_ROOM_BOUNDARY,
    validate_spatial_room_contract,
)

REPO_ROOT = Path(__file__).resolve().parents[3]
STATIC_MAP_BUNDLES = tuple(
    sorted(
        path
        for path in (REPO_ROOT / "assets" / "maps").iterdir()
        if (path / "map.yaml").is_file() and (path / "semantics.json").is_file()
    )
)


@pytest.mark.parametrize("bundle_dir", STATIC_MAP_BUNDLES, ids=lambda path: path.name)
def test_all_static_map_bundles_declare_source_frame_spatial_contract(
    bundle_dir: Path,
) -> None:
    semantics = _semantics(bundle_dir)

    validation = validate_nav2_map_bundle(bundle_dir)

    assert validation.ok, validation.as_dict()
    assert semantics["display_frame"] is None
    assert semantics["spatial_contract"]["schema"] == MAP_SPATIAL_CONTRACT_SCHEMA
    assert semantics["spatial_contract"]["semantic_geometry_frame"] == "source_map_frame"
    assert semantics["spatial_contract"]["display_frame_status"] == DISPLAY_FRAME_STATUS_ABSENT
    assert (
        semantics["spatial_contract"]["source_map_frame"]["frame_id"]
        == (semantics["frame_ids"]["map"])
    )
    assert semantics["rooms"]
    for room in semantics["rooms"]:
        assert room["polygon_role"] == POLYGON_ROLE_NAVIGATION_AREA
        assert room["geometry_source"] == GEOMETRY_SOURCE_OPERATOR_NAVIGATION_ZONE
        assert room["source_map_frame_id"] == semantics["frame_ids"]["map"]
        assert room["polygon_usage"]["review"] is True


def test_static_map_bundle_inventory_is_not_empty() -> None:
    assert STATIC_MAP_BUNDLES


def test_semantic_map_spatial_contract_normalizer_reports_missing_semantics_without_traceback(
    tmp_path: Path,
) -> None:
    bundle_dir = tmp_path / "bundle"
    bundle_dir.mkdir()

    completed = _run_normalizer(bundle_dir)

    assert completed.returncode == 2
    assert "semantics source is missing" in completed.stderr
    assert str(bundle_dir / "semantics.json") in completed.stderr
    assert "Traceback" not in completed.stderr


@pytest.mark.parametrize(
    ("source", "message"),
    (
        ("{not-json\n", "semantics source must contain valid JSON object"),
        ("[]\n", "semantics source must contain a JSON object"),
    ),
)
def test_semantic_map_spatial_contract_normalizer_reports_bad_semantics_without_traceback(
    tmp_path: Path,
    source: str,
    message: str,
) -> None:
    bundle_dir = tmp_path / "bundle"
    bundle_dir.mkdir()
    semantics_path = bundle_dir / "semantics.json"
    semantics_path.write_text(source, encoding="utf-8")

    completed = _run_normalizer(bundle_dir)

    assert completed.returncode == 2
    assert message in completed.stderr
    assert str(semantics_path) in completed.stderr
    assert "Traceback" not in completed.stderr


def test_b1_uses_dt_room_reference_and_alignment_correspondence_manifest() -> None:
    room_semantics = json.loads(
        (REPO_ROOT / "assets" / "maps" / "b1-map12-room-semantics.json").read_text(encoding="utf-8")
    )
    correspondences = json.loads(
        (REPO_ROOT / "assets" / "maps" / "b1-map12-scene-correspondences.json").read_text(
            encoding="utf-8"
        )
    )
    raw_map = (
        REPO_ROOT / "vendors" / "agibot_sdk" / "artifacts" / "maps" / "robot_map_12" / "agibot"
    )
    removed_authored_bundle = REPO_ROOT / "assets" / "maps" / "agibot-robot-map-12"
    rooms = {room["asset_partition_id"]: room for room in room_semantics["rooms"]}

    assert room_semantics["schema"] == "scene_room_semantic_overlay_overrides_v1"
    assert room_semantics["policy"]["source_of_truth"] == "digital_twin_scene_partitions"
    assert room_semantics["policy"]["contains_map12_candidate_polygons"] is False
    assert rooms["meeting_room_b"]["room_label"] == "Meeting room B"
    assert rooms["meeting_room_b"]["review_status"] == "accepted"
    assert correspondences["schema"] == "b1_map12_scene_correspondences_v1"
    assert len(correspondences["anchors"]) == 7
    assert {anchor["review_status"] for anchor in correspondences["anchors"]} == {"accepted"}
    assert {anchor["anchor_role"] for anchor in correspondences["anchors"]} == {"alignment"}
    assert {anchor["anchor_type"] for anchor in correspondences["anchors"]} == {
        "operator_correspondence"
    }
    assert {anchor["navigation_area_id"] for anchor in correspondences["anchors"]} == {""}
    assert {anchor["asset_partition_id"] for anchor in correspondences["anchors"]} == {""}
    assert (raw_map / "nav2.yaml").is_file()
    assert (raw_map / "occupancy.pgm").is_file()
    assert not removed_authored_bundle.exists()
    assert not (REPO_ROOT / "assets" / "maps" / "b1-map12-alignment-review.json").exists()


def test_candidate_navigation_zone_cannot_be_validated_as_room_boundary() -> None:
    room = {
        "room_id": "candidate_box",
        "room_label": "Candidate box",
        "polygon": [
            {"x": 0.0, "y": 0.0},
            {"x": 1.0, "y": 0.0},
            {"x": 1.0, "y": 1.0},
        ],
        "polygon_role": POLYGON_ROLE_ROOM_BOUNDARY,
        "geometry_source": GEOMETRY_SOURCE_OPERATOR_NAVIGATION_ZONE,
        "alignment_status": "candidate",
        "source_map_frame_id": "map",
        "polygon_usage": {"navigation": True, "semantic_labeling": "candidate", "review": True},
    }
    errors: list[str] = []

    validate_spatial_room_contract(room, index=0, errors=errors)

    assert any("operator navigation zone" in error for error in errors)
    assert any("candidate geometry" in error for error in errors)


def _semantics(bundle_dir: Path) -> dict:
    return json.loads((bundle_dir / "semantics.json").read_text(encoding="utf-8"))


def _run_normalizer(bundle_dir: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, "-m", "roboclaws.maps.spatial_contract", str(bundle_dir)],
        cwd=REPO_ROOT,
        text=True,
        capture_output=True,
        check=False,
    )
