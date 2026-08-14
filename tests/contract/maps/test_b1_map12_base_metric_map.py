from __future__ import annotations

import copy
import hashlib
import json
import subprocess
import sys
from pathlib import Path

import pytest

from roboclaws.maps.b1_base_metric_map import (
    B1_BASE_METRIC_LABELS_SCHEMA,
    B1_BASE_METRIC_MAP_MANIFEST_SCHEMA,
    WAYPOINT_GENERATION_POLICY,
    build_base_metric_map_bundle,
    validate_base_metric_labels,
)
from roboclaws.maps.bundle import validate_base_metric_map_v1_bundle, validate_nav2_map_bundle

REPO_ROOT = Path(__file__).resolve().parents[3]
MAP_BUNDLE = REPO_ROOT / "vendors" / "agibot_sdk" / "artifacts" / "maps" / "robot_map_12" / "agibot"
BASE_LABELS = REPO_ROOT / "assets" / "maps" / "b1-map12-base-metric-labels.json"
ROOM_SEMANTICS = REPO_ROOT / "assets" / "maps" / "b1-map12-room-semantics.json"
MODULE = "roboclaws.maps.b1_base_metric_map"


def test_checked_in_base_metric_labels_are_accepted_source_of_truth() -> None:
    labels = _read_json(BASE_LABELS)
    areas = {label["navigation_area_id"]: label for label in labels["labels"]}

    assert labels["schema"] == B1_BASE_METRIC_LABELS_SCHEMA
    assert labels["review_status"] == "accepted"
    assert labels["source_map_mutated"] is False
    assert labels["policy"]["source_of_truth"] == ("operator_reviewed_map12_navigation_area_labels")
    assert labels["policy"]["contains_static_fixtures"] is False
    assert labels["policy"]["contains_movable_objects"] is False
    assert set(areas) == {
        "meeting_room_a",
        "meeting_room_b",
        "meeting_room_c",
        "reception_area_a",
        "short_corridor_a",
        "storage_room_a",
        "open_kitchen_a",
        "long_corridor_a",
    }
    assert areas["meeting_room_b"]["label"] == "Meeting room B"
    assert areas["meeting_room_b"]["asset_partition_id"] == "meeting_room_b"
    assert areas["open_kitchen_a"]["asset_partition_id"] == ""
    assert areas["long_corridor_a"]["asset_partition_id"] == ""
    assert {
        area_id for area_id, label in areas.items() if label["polygon_usage"]["navigation"] is True
    } == {
        "meeting_room_b",
        "meeting_room_c",
        "reception_area_a",
        "open_kitchen_a",
        "long_corridor_a",
    }


def test_base_metric_map_builder_generates_shared_robot_and_dt_bundle(
    tmp_path: Path,
) -> None:
    result = build_base_metric_map_bundle(
        map_bundle=MAP_BUNDLE,
        labels_path=BASE_LABELS,
        room_semantics_path=ROOM_SEMANTICS,
        output_dir=tmp_path / "base-metric-map",
    )
    output_dir = Path(result["output_dir"])
    semantics = _read_json(output_dir / "semantics.json")
    manifest = _read_json(output_dir / "base_metric_map_manifest.json")
    rooms = {room["room_id"]: room for room in semantics["rooms"]}
    waypoints = {
        waypoint["navigation_area_id"]: waypoint for waypoint in semantics["inspection_waypoints"]
    }

    assert result["schema"] == B1_BASE_METRIC_MAP_MANIFEST_SCHEMA
    assert result["status"] == "generated"
    assert validate_nav2_map_bundle(output_dir).ok
    assert validate_base_metric_map_v1_bundle(output_dir).ok
    assert result["validation"]["metadata"]["base_metric_map_v1_ready"] is True
    assert manifest["policy"]["shared_by_real_robot_and_digital_twin"] is True
    assert manifest["policy"]["does_not_use_navigation_memory_as_waypoint_source"] is True
    assert manifest["base_metric_map"]["navigation_area_count"] == 5
    assert manifest["base_metric_map"]["semantic_label_count"] == 8
    assert manifest["base_metric_map"]["inspection_waypoint_count"] == 5
    assert semantics["base_metric_map_contract"] == {
        "schema": "base_metric_map_v1",
        "navigation_area_count": 5,
        "semantic_label_count": 8,
        "inspection_waypoint_count": 5,
        "waypoint_generation_policy": WAYPOINT_GENERATION_POLICY,
        "consumer_scope": "real_robot_and_digital_twin",
    }
    assert semantics["spatial_contract"]["alignment_status"] == "verified"
    assert semantics["frame_ids"]["map"] == labels_source_frame(BASE_LABELS)
    assert semantics["spatial_contract"]["source_map_frame"]["frame_id"] == labels_source_frame(
        BASE_LABELS
    )
    assert semantics["provenance"]["raw_map_bundle"] == str(MAP_BUNDLE)
    assert semantics["provenance"]["base_metric_labels"] == str(BASE_LABELS)
    assert semantics["provenance"]["uses_navigation_memory_as_waypoint_source"] is False
    assert semantics["provenance"]["contains_static_fixtures"] is False
    assert semantics["provenance"]["contains_movable_objects"] is False
    assert semantics["static_landmarks"] == []
    assert semantics["navigation_memory_anchors"] == []
    assert rooms["meeting_room_b"]["room_label"] == "Meeting room B"
    assert {room["source_map_frame_id"] for room in semantics["rooms"]} == {
        labels_source_frame(BASE_LABELS)
    }
    assert rooms["meeting_room_b"]["label_source"] == "digital_twin_room_semantic_reference"
    assert rooms["open_kitchen_a"]["label_source"] == "operator_reviewed_map12_base_label"
    assert rooms["meeting_room_a"]["polygon_usage"]["navigation"] is False
    assert set(waypoints) == {
        "meeting_room_b",
        "meeting_room_c",
        "reception_area_a",
        "open_kitchen_a",
        "long_corridor_a",
    }
    assert all(
        waypoint["waypoint_source"] == "generated_exploration_candidate"
        and waypoint["purpose"] == "base_navigation_area_inspection"
        and waypoint["generation_policy"] == WAYPOINT_GENERATION_POLICY
        and waypoint["frame_id"] == labels_source_frame(BASE_LABELS)
        for waypoint in waypoints.values()
    )
    assert waypoints["open_kitchen_a"]["x"] == pytest.approx(1.15)
    assert waypoints["open_kitchen_a"]["y"] == pytest.approx(-4.7)
    assert (output_dir / "preview.png").is_file()


def test_base_metric_map_cli_generates_bundle(tmp_path: Path) -> None:
    output_dir = tmp_path / "cli-base-metric-map"

    completed = subprocess.run(
        [
            sys.executable,
            "-m",
            MODULE,
            "--map-bundle",
            str(MAP_BUNDLE),
            "--labels",
            str(BASE_LABELS),
            "--room-semantics",
            str(ROOM_SEMANTICS),
            "--output-dir",
            str(output_dir),
        ],
        cwd=REPO_ROOT,
        check=True,
        capture_output=True,
        text=True,
    )
    payload = json.loads(completed.stdout)

    assert payload["status"] == "generated"
    assert payload["navigation_area_count"] == 5
    assert payload["inspection_waypoint_count"] == 5
    assert validate_nav2_map_bundle(output_dir).ok


def test_package_cli_rebuild_matches_api_assets_provenance_and_digests(tmp_path: Path) -> None:
    api_output = tmp_path / "api-bundle"
    cli_output = tmp_path / "cli-bundle"
    build_base_metric_map_bundle(
        map_bundle=MAP_BUNDLE,
        labels_path=BASE_LABELS,
        room_semantics_path=ROOM_SEMANTICS,
        output_dir=api_output,
    )
    subprocess.run(
        [
            sys.executable,
            "-m",
            MODULE,
            "--map-bundle",
            str(MAP_BUNDLE),
            "--labels",
            str(BASE_LABELS),
            "--room-semantics",
            str(ROOM_SEMANTICS),
            "--output-dir",
            str(cli_output),
        ],
        cwd=REPO_ROOT,
        check=True,
        capture_output=True,
        text=True,
    )

    deterministic_assets = (
        "map.yaml",
        "map.pgm",
        "raw_map.json.gz",
        "semantics.json",
        "source.json",
        "preview.png",
    )
    assert {name: _sha256(api_output / name) for name in deterministic_assets} == {
        name: _sha256(cli_output / name) for name in deterministic_assets
    }

    manifest = _read_json(cli_output / "base_metric_map_manifest.json")
    semantics = _read_json(cli_output / "semantics.json")
    assert semantics["provenance"]["b1_base_metric_map_builder"] == (
        "roboclaws/maps/b1_base_metric_map.py"
    )
    assert manifest["source_file_hashes"] == {
        str(path): _sha256(path)
        for path in (
            BASE_LABELS,
            ROOM_SEMANTICS,
            MAP_BUNDLE / "nav2.yaml",
            MAP_BUNDLE / "occupancy.pgm",
            MAP_BUNDLE / "source.json",
        )
    }


def test_base_metric_map_rejects_dt_label_mismatch(tmp_path: Path) -> None:
    labels_path = _write_modified_labels(tmp_path)
    labels = _read_json(labels_path)
    for label in labels["labels"]:
        if label["asset_partition_id"] == "meeting_room_b":
            label["label"] = "Open kitchen"
            break
    labels_path.write_text(json.dumps(labels), encoding="utf-8")

    with pytest.raises(ValueError, match="label .* must match DT room_label"):
        build_base_metric_map_bundle(
            map_bundle=MAP_BUNDLE,
            labels_path=labels_path,
            room_semantics_path=ROOM_SEMANTICS,
            output_dir=tmp_path / "bundle",
        )


def test_base_metric_map_rejects_navigation_area_without_safe_waypoint(
    tmp_path: Path,
) -> None:
    labels_path = _write_modified_labels(tmp_path)
    labels = _read_json(labels_path)
    for label in labels["labels"]:
        if label["navigation_area_id"] == "meeting_room_a":
            label["polygon_usage"]["navigation"] = True
            break
    labels_path.write_text(json.dumps(labels), encoding="utf-8")

    with pytest.raises(ValueError, match="navigation=true but no clearance-safe free waypoint"):
        build_base_metric_map_bundle(
            map_bundle=MAP_BUNDLE,
            labels_path=labels_path,
            room_semantics_path=ROOM_SEMANTICS,
            output_dir=tmp_path / "bundle",
        )


def test_base_metric_map_rejects_missing_label_source_frame(tmp_path: Path) -> None:
    labels_path = _write_modified_labels(tmp_path)
    labels = _read_json(labels_path)
    labels.pop("source_map_frame_id")
    labels_path.write_text(json.dumps(labels), encoding="utf-8")

    with pytest.raises(ValueError, match="source_map_frame_id must be set"):
        build_base_metric_map_bundle(
            map_bundle=MAP_BUNDLE,
            labels_path=labels_path,
            room_semantics_path=ROOM_SEMANTICS,
            output_dir=tmp_path / "bundle",
        )


def test_base_metric_map_rejects_label_source_frame_drift(tmp_path: Path) -> None:
    labels_path = _write_modified_labels(tmp_path)
    labels = _read_json(labels_path)
    labels["labels"][0]["source_map_frame_id"] = "operator_map"
    labels_path.write_text(json.dumps(labels), encoding="utf-8")

    with pytest.raises(
        ValueError,
        match="label scene_bbox_seed_meeting_room_a source_map_frame_id must match "
        "top-level source_map_frame_id",
    ):
        build_base_metric_map_bundle(
            map_bundle=MAP_BUNDLE,
            labels_path=labels_path,
            room_semantics_path=ROOM_SEMANTICS,
            output_dir=tmp_path / "bundle",
        )


def test_base_metric_label_validator_reports_all_fail_loud_errors(tmp_path: Path) -> None:
    labels = _read_json(BASE_LABELS)
    room_semantics = _read_json(ROOM_SEMANTICS)
    map_yaml = _read_map_yaml(MAP_BUNDLE / "nav2.yaml")
    from roboclaws.maps.rasterize import load_pgm

    origin = (map_yaml["origin"] + [0.0, 0.0, 0.0])[:3]
    grid = load_pgm(
        MAP_BUNDLE / "occupancy.pgm",
        resolution_m=float(map_yaml["resolution"]),
        origin_x=float(origin[0]),
        origin_y=float(origin[1]),
    )
    labels["labels"][0]["review_status"] = "draft"
    labels["labels"][1]["label"] = "Open kitchen"

    errors = validate_base_metric_labels(
        labels,
        room_semantics=room_semantics,
        grid=grid,
        labels_path=tmp_path / "missing.json",
        map_bundle=MAP_BUNDLE,
    )

    assert any("labels missing" in error for error in errors)
    assert any("review_status must be accepted" in error for error in errors)
    assert any("must match DT room_label" in error for error in errors)


def _write_modified_labels(tmp_path: Path) -> Path:
    path = tmp_path / "labels.json"
    path.write_text(json.dumps(copy.deepcopy(_read_json(BASE_LABELS))), encoding="utf-8")
    return path


def labels_source_frame(path: Path) -> str:
    return str(_read_json(path)["source_map_frame_id"])


def _read_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _read_map_yaml(path: Path) -> dict:
    from roboclaws.maps.bundle_validation import parse_map_yaml

    return parse_map_yaml(path.read_text(encoding="utf-8"))
