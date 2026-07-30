from __future__ import annotations

import json
from pathlib import Path

import pytest

from roboclaws.maps.b1_base_metric_map import build_base_metric_map_bundle
from roboclaws.maps.bundle import validate_nav2_map_bundle
from roboclaws.maps.room_semantics import (
    ROOM_SEMANTIC_OVERLAY_SCHEMA,
    build_scene_room_semantic_overlay,
)

REPO_ROOT = Path(__file__).resolve().parents[3]
SCENE_ROOT = (
    REPO_ROOT / "data" / "robot-data-lab" / "scene-engine" / "data" / ("2rd_floor_seperated")
)
MAP12_BUNDLE = (
    REPO_ROOT / "vendors" / "agibot_sdk" / "artifacts" / "maps" / ("robot_map_12") / "agibot"
)
BASE_LABELS = REPO_ROOT / "assets" / "maps" / "b1-map12-base-metric-labels.json"
ROOM_SEMANTICS = REPO_ROOT / "assets" / "maps" / "b1-map12-room-semantics.json"


def test_scene_room_overlay_labels_gaussian_partitions_as_public_room_semantics() -> None:
    _require_scene_root()

    overlay = build_scene_room_semantic_overlay(SCENE_ROOT, source_bundle_dir=MAP12_BUNDLE)
    rooms = {item["asset_partition_id"]: item for item in overlay["rooms"]}

    assert overlay["schema"] == ROOM_SEMANTIC_OVERLAY_SCHEMA
    assert set(rooms) == {
        "meeting_room_a",
        "meeting_room_b",
        "meeting_room_c",
        "reception_area_a",
        "short_corridor_a",
        "storage_room_a",
    }
    assert rooms["meeting_room_a"]["category"] == "meeting_room"
    assert rooms["reception_area_a"]["category"] == "reception_area"
    assert rooms["short_corridor_a"]["category"] == "corridor"
    assert rooms["storage_room_a"]["category"] == "storage_room"
    assert rooms["meeting_room_a"]["room_label"] != "Room A"
    assert rooms["reception_area_a"]["room_label"] == "Lobby / reception area"
    assert "room_category_hints" in overlay
    assert all(item["category"] for item in overlay["room_category_hints"])


def test_scene_room_overlay_accepts_operator_overrides_for_reviewed_room_labels() -> None:
    _require_scene_root()

    overlay = build_scene_room_semantic_overlay(
        SCENE_ROOT,
        source_bundle_dir=MAP12_BUNDLE,
        overrides={
            "rooms": [
                {
                    "asset_partition_id": "meeting_room_a",
                    "room_label": "Meeting room A",
                    "category": "meeting_room",
                    "confidence": 0.86,
                    "semantic_source": "operator_authored_room_overlay",
                    "review_status": "accepted",
                },
                {
                    "asset_partition_id": "meeting_room_b",
                    "room_label": "Meeting room B",
                    "category": "meeting_room",
                    "confidence": 0.88,
                    "semantic_source": "operator_authored_room_overlay",
                    "review_status": "accepted",
                },
                {
                    "asset_partition_id": "reception_area_a",
                    "room_label": "Living room / main hall",
                    "category": "living_room",
                    "confidence": 0.9,
                    "semantic_source": "operator_authored_room_overlay",
                    "review_status": "accepted",
                },
                {
                    "asset_partition_id": "meeting_room_c",
                    "room_label": "Meeting room C",
                    "category": "meeting_room",
                    "confidence": 0.86,
                    "semantic_source": "operator_authored_room_overlay",
                    "review_status": "accepted",
                },
            ]
        },
    )
    rooms = {item["asset_partition_id"]: item for item in overlay["rooms"]}

    assert rooms["meeting_room_b"]["room_label"] == "Meeting room B"
    assert rooms["meeting_room_b"]["category"] == "meeting_room"
    assert rooms["meeting_room_b"]["semantic_source"] == "operator_authored_room_overlay"
    assert rooms["meeting_room_a"]["room_label"] == "Meeting room A"
    assert rooms["meeting_room_a"]["category"] == "meeting_room"
    assert rooms["meeting_room_c"]["room_label"] == "Meeting room C"
    assert rooms["meeting_room_c"]["category"] == "meeting_room"
    assert rooms["reception_area_a"]["category"] == "living_room"


def test_scene_room_overlay_does_not_fabricate_geometry_without_source_semantics(
    tmp_path: Path,
) -> None:
    scene_root = _minimal_scene_root(tmp_path)
    source_bundle = tmp_path / "bundle"
    source_bundle.mkdir()

    overlay = build_scene_room_semantic_overlay(
        scene_root,
        source_bundle_dir=source_bundle,
        overrides={
            "scene_map_correspondence": [
                {
                    "asset_partition_id": "meeting_room_a",
                    "navigation_area_id": "nav_room_a",
                }
            ]
        },
    )

    room = overlay["rooms"][0]
    assert room["navigation_area_id"] == "nav_room_a"
    assert "polygon" not in room
    assert "map_center" not in room
    assert "geometry_source" not in room
    assert "polygon_usage" not in room
    assert room["scene_map_correspondence"]["map_polygon_provided"] is False


@pytest.mark.parametrize(
    ("source_text", "message"),
    [
        ("{not-json\n", r"room semantics source must contain valid JSON object: .*semantics\.json"),
        ("[]\n", r"room semantics source must contain a JSON object: .*semantics\.json"),
    ],
)
def test_scene_room_overlay_rejects_bad_source_bundle_semantics(
    tmp_path: Path,
    source_text: str,
    message: str,
) -> None:
    scene_root = _minimal_scene_root(tmp_path)
    source_bundle = tmp_path / "bundle"
    source_bundle.mkdir()
    (source_bundle / "semantics.json").write_text(source_text, encoding="utf-8")

    with pytest.raises(ValueError, match=message):
        build_scene_room_semantic_overlay(scene_root, source_bundle_dir=source_bundle)


def test_scene_room_overlay_uses_source_bundle_room_geometry(tmp_path: Path) -> None:
    scene_root = _minimal_scene_root(tmp_path)
    source_bundle = tmp_path / "bundle"
    source_bundle.mkdir()
    (source_bundle / "semantics.json").write_text(
        json.dumps(
            {
                "rooms": [
                    {
                        "room_id": "nav_room_a",
                        "polygon": [
                            {"x": 0, "y": 0},
                            {"x": 2, "y": 0},
                            {"x": 2, "y": 2},
                            {"x": 0, "y": 2},
                        ],
                        "source_map_frame_id": "map",
                    }
                ]
            }
        ),
        encoding="utf-8",
    )

    overlay = build_scene_room_semantic_overlay(
        scene_root,
        source_bundle_dir=source_bundle,
        overrides={
            "scene_map_correspondence": [
                {
                    "asset_partition_id": "meeting_room_a",
                    "navigation_area_id": "nav_room_a",
                }
            ]
        },
    )

    room = overlay["rooms"][0]
    assert room["navigation_area_id"] == "nav_room_a"
    assert room["polygon"] == [
        {"x": 0, "y": 0},
        {"x": 2, "y": 0},
        {"x": 2, "y": 2},
        {"x": 0, "y": 2},
    ]
    assert room["map_center"] == {"x": 1.0, "y": 1.0}


def test_b1_base_metric_map_materializes_review_labels_without_retargeting_map(
    tmp_path: Path,
) -> None:
    result = build_base_metric_map_bundle(
        map_bundle=MAP12_BUNDLE,
        labels_path=BASE_LABELS,
        room_semantics_path=ROOM_SEMANTICS,
        output_dir=tmp_path / "base-metric-map",
    )
    bundle_dir = Path(result["output_dir"])
    semantics = json.loads((bundle_dir / "semantics.json").read_text(encoding="utf-8"))

    assert result["validation"]["ok"] is True
    assert validate_nav2_map_bundle(bundle_dir).ok
    assert len(semantics["rooms"]) == 8
    assert semantics["fixtures"] == []
    assert semantics["navigation_memory_anchors"] == []
    assert semantics["provenance"]["base_metric_labels"] == str(BASE_LABELS)
    assert semantics["provenance"]["uses_navigation_memory_as_waypoint_source"] is False
    assert semantics["provenance"]["room_semantics_reference"] == str(ROOM_SEMANTICS)


def test_scene_room_overlay_builder_writes_review_overlay_without_bundle_side_effect(
    tmp_path: Path,
) -> None:
    _require_scene_root()

    output = tmp_path / "room_semantic_overlay.json"
    overlay = build_scene_room_semantic_overlay(
        SCENE_ROOT,
        source_bundle_dir=MAP12_BUNDLE,
        overrides={
            "rooms": [
                {
                    "asset_partition_id": "meeting_room_b",
                    "room_label": "Meeting room B",
                    "category": "meeting_room",
                    "semantic_source": "operator_authored_room_overlay",
                    "confidence": 0.88,
                    "review_status": "accepted",
                }
            ]
        },
    )
    output.write_text(json.dumps(overlay, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    written_overlay = json.loads(output.read_text(encoding="utf-8"))

    assert written_overlay["schema"] == ROOM_SEMANTIC_OVERLAY_SCHEMA
    assert {item["asset_partition_id"] for item in written_overlay["rooms"]} >= {
        "meeting_room_a",
        "storage_room_a",
    }
    assert any(item["room_label"] == "Meeting room B" for item in written_overlay["rooms"])
    assert not (tmp_path / "bundle").exists()


def test_checked_in_b1_room_semantics_is_dt_label_reference_only() -> None:
    payload = json.loads(ROOM_SEMANTICS.read_text(encoding="utf-8"))
    rooms = {item["asset_partition_id"]: item for item in payload["rooms"]}

    assert payload["schema"] == "scene_room_semantic_overlay_overrides_v1"
    assert payload["policy"]["source_of_truth"] == "digital_twin_scene_partitions"
    assert payload["policy"]["contains_map12_candidate_polygons"] is False
    assert payload["policy"]["contains_navigation_area_bindings"] is False
    assert rooms["meeting_room_b"]["room_label"] == "Meeting room B"
    assert rooms["meeting_room_b"]["review_status"] == "accepted"
    assert rooms["meeting_room_b"]["semantic_source"] == "digital_twin_room_semantic_reference"
    assert rooms["reception_area_a"]["category"] == "living_room"
    assert {room["review_status"] for room in rooms.values()} == {"accepted"}
    assert all(
        "map_polygon" not in room and "navigation_area_id" not in room for room in rooms.values()
    )


def _require_scene_root() -> None:
    if not SCENE_ROOT.is_dir():
        pytest.skip("robot-data-lab scene-engine data is unavailable in this checkout")


def _minimal_scene_root(tmp_path: Path) -> Path:
    partition = tmp_path / "scene" / "meeting_room_a"
    partition.mkdir(parents=True)
    (partition / "scene.usd").write_text("#usda 1.0\n", encoding="utf-8")
    return tmp_path / "scene"
