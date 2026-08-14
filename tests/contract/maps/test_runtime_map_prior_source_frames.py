from __future__ import annotations

import json
from pathlib import Path

import pytest

from roboclaws.maps.runtime_prior_conversion import runtime_prior_snapshot_from_nav2_cleanup_bundle
from roboclaws.maps.runtime_prior_snapshot import runtime_prior_snapshot_from_runtime_metric_map
from roboclaws.maps.spatial_contract import source_frame_spatial_contract


def test_online_runtime_prior_preserves_runtime_map_frame() -> None:
    runtime_map = {
        "schema": "runtime_metric_map_v1",
        "static_map": {"map_id": "operator-map", "map_frame": "operator_map"},
        "public_semantic_anchors": [
            {
                "anchor_id": "anchor_a",
                "anchor_type": "fixture",
                "category": "table",
                "label": "Table",
                "waypoint_id": "wp_table",
                "pose": {"x": 1.0, "y": 2.0, "yaw": 0.0},
                "affordances": ["place"],
                "actionability": "actionable",
            }
        ],
        "generated_exploration_candidates": [
            {
                "waypoint_id": "wp_scan",
                "x": 2.0,
                "y": 3.0,
                "yaw": 0.0,
                "waypoint_source": "generated_exploration_candidate",
            }
        ],
    }

    snapshot = runtime_prior_snapshot_from_runtime_metric_map(runtime_map)

    assert snapshot["source_navigation_map"]["map_frame"] == "operator_map"
    assert {item["frame_id"] for item in snapshot["inspection_waypoints"]} == {"operator_map"}


def test_online_runtime_prior_rejects_static_map_frame_drift() -> None:
    runtime_map = {
        "schema": "runtime_metric_map_v1",
        "frame_id": "runtime_map",
        "static_map": {"map_id": "operator-map", "map_frame": "operator_map"},
    }

    with pytest.raises(
        ValueError,
        match="runtime metric map frame_id must match static_map frame",
    ):
        runtime_prior_snapshot_from_runtime_metric_map(runtime_map)


def test_online_runtime_prior_rejects_anchor_frame_drift() -> None:
    runtime_map = {
        "schema": "runtime_metric_map_v1",
        "static_map": {"map_id": "operator-map", "map_frame": "operator_map"},
        "public_semantic_anchors": [
            {
                "anchor_id": "anchor_a",
                "anchor_type": "fixture",
                "waypoint_id": "wp_table",
                "pose": {"frame_id": "map", "x": 1.0, "y": 2.0, "yaw": 0.0},
            }
        ],
    }

    with pytest.raises(
        ValueError,
        match=r"runtime metric map anchor anchor_a frame_id must match runtime metric map frame",
    ):
        runtime_prior_snapshot_from_runtime_metric_map(runtime_map)


def test_online_runtime_prior_rejects_generated_waypoint_frame_drift() -> None:
    runtime_map = {
        "schema": "runtime_metric_map_v1",
        "static_map": {"map_id": "operator-map", "map_frame": "operator_map"},
        "generated_exploration_candidates": [
            {
                "waypoint_id": "wp_scan",
                "frame_id": "map",
                "x": 2.0,
                "y": 3.0,
                "yaw": 0.0,
            }
        ],
    }

    with pytest.raises(
        ValueError,
        match=(
            r"runtime metric map generated waypoint wp_scan frame_id must match "
            r"runtime metric map frame"
        ),
    ):
        runtime_prior_snapshot_from_runtime_metric_map(runtime_map)


def test_nav2_cleanup_bundle_preserves_declared_map_frame(tmp_path: Path) -> None:
    bundle_dir = _write_minimal_nav2_cleanup_bundle(tmp_path / "bundle")
    semantics_path = bundle_dir / "semantics.json"
    semantics = _read_json(semantics_path)
    semantics["frame_ids"]["map"] = "operator_map"
    semantics["spatial_contract"]["source_map_frame"]["frame_id"] = "operator_map"
    semantics["rooms"][0]["source_map_frame_id"] = "operator_map"
    semantics["inspection_waypoints"][0].pop("frame_id")
    semantics_path.write_text(json.dumps(semantics), encoding="utf-8")

    snapshot = runtime_prior_snapshot_from_nav2_cleanup_bundle(bundle_dir)

    assert snapshot["source_navigation_map"]["map_frame"] == "operator_map"
    assert snapshot["runtime_metric_map"]["static_map"]["map_frame"] == "operator_map"
    assert {room["source_map_frame_id"] for room in snapshot["runtime_metric_map"]["rooms"]} == {
        "operator_map"
    }
    assert {waypoint["frame_id"] for waypoint in snapshot["inspection_waypoints"]} == {
        "operator_map"
    }
    assert {
        anchor["materialization"]["waypoint"]["frame_id"]
        for anchor in snapshot["public_semantic_anchors"]
    } == {"operator_map"}


def test_nav2_cleanup_bundle_rejects_missing_frame_ids_map(tmp_path: Path) -> None:
    bundle_dir = _write_minimal_nav2_cleanup_bundle(tmp_path / "bundle")
    semantics_path = bundle_dir / "semantics.json"
    semantics = _read_json(semantics_path)
    semantics["frame_ids"].pop("map")
    semantics_path.write_text(json.dumps(semantics), encoding="utf-8")

    with pytest.raises(
        ValueError,
        match="Nav2 cleanup semantics must contain frame_ids.map",
    ):
        runtime_prior_snapshot_from_nav2_cleanup_bundle(bundle_dir)


def test_nav2_cleanup_bundle_rejects_mismatched_spatial_contract_frame(
    tmp_path: Path,
) -> None:
    bundle_dir = _write_minimal_nav2_cleanup_bundle(tmp_path / "bundle")
    semantics_path = bundle_dir / "semantics.json"
    semantics = _read_json(semantics_path)
    semantics["spatial_contract"] = {
        "source_map_frame": {"frame_id": "display_map"},
    }
    semantics_path.write_text(json.dumps(semantics), encoding="utf-8")

    with pytest.raises(
        ValueError,
        match=r"spatial_contract\.source_map_frame\.frame_id must match frame_ids\.map",
    ):
        runtime_prior_snapshot_from_nav2_cleanup_bundle(bundle_dir)


def test_nav2_cleanup_bundle_rejects_mismatched_room_source_frame(
    tmp_path: Path,
) -> None:
    bundle_dir = _write_minimal_nav2_cleanup_bundle(tmp_path / "bundle")
    semantics_path = bundle_dir / "semantics.json"
    semantics = _read_json(semantics_path)
    semantics["frame_ids"]["map"] = "operator_map"
    semantics["spatial_contract"]["source_map_frame"]["frame_id"] = "operator_map"
    semantics["rooms"][0]["source_map_frame_id"] = "map"
    semantics_path.write_text(json.dumps(semantics), encoding="utf-8")

    with pytest.raises(
        ValueError,
        match="Nav2 cleanup room source_map_frame_id must match semantics.json frame_ids.map",
    ):
        runtime_prior_snapshot_from_nav2_cleanup_bundle(bundle_dir)


def test_nav2_cleanup_bundle_rejects_non_object_room_source(tmp_path: Path) -> None:
    bundle_dir = _write_minimal_nav2_cleanup_bundle(tmp_path / "bundle")
    semantics_path = bundle_dir / "semantics.json"
    semantics = _read_json(semantics_path)
    semantics["rooms"] = [[]]
    semantics_path.write_text(json.dumps(semantics), encoding="utf-8")

    with pytest.raises(
        ValueError,
        match="Nav2 cleanup room 1 must be a JSON object",
    ):
        runtime_prior_snapshot_from_nav2_cleanup_bundle(bundle_dir)


def test_nav2_cleanup_bundle_rejects_mismatched_waypoint_frame(tmp_path: Path) -> None:
    bundle_dir = _write_minimal_nav2_cleanup_bundle(tmp_path / "bundle")
    semantics_path = bundle_dir / "semantics.json"
    semantics = _read_json(semantics_path)
    semantics["frame_ids"]["map"] = "operator_map"
    semantics["spatial_contract"]["source_map_frame"]["frame_id"] = "operator_map"
    semantics["rooms"][0]["source_map_frame_id"] = "operator_map"
    semantics["inspection_waypoints"][0]["frame_id"] = "map"
    semantics_path.write_text(json.dumps(semantics), encoding="utf-8")

    with pytest.raises(
        ValueError,
        match="Nav2 cleanup waypoint frame_id must match semantics.json frame_ids.map",
    ):
        runtime_prior_snapshot_from_nav2_cleanup_bundle(bundle_dir)


def _write_minimal_nav2_cleanup_bundle(bundle_dir: Path) -> Path:
    bundle_dir.mkdir(parents=True)
    (bundle_dir / "map.yaml").write_text(
        "\n".join(
            [
                "image: map.pgm",
                "resolution: 0.05",
                "origin: [0, 0, 0]",
                "negate: 0",
                "occupied_thresh: 0.65",
                "free_thresh: 0.196",
                "",
            ]
        ),
        encoding="utf-8",
    )
    (bundle_dir / "map.pgm").write_text(
        "\n".join(["P2", "2 2", "255", "0 0", "0 0", ""]),
        encoding="ascii",
    )
    semantics = {
        "schema": "nav2_cleanup_semantics_v1",
        "environment_id": "test-b1-map12",
        "map_id": "test-b1-map12_base_metric_map",
        "frame_ids": {"map": "map", "base": "base_link", "camera": "camera"},
        "spatial_contract": source_frame_spatial_contract(frame_id="map"),
        "display_frame": None,
        "rooms": [
            {
                "room_id": "room_a",
                "room_label": "Room A",
                "category": "meeting_room",
                "source_map_frame_id": "map",
                "polygon": [
                    {"x": 0.0, "y": 0.0},
                    {"x": 1.0, "y": 0.0},
                    {"x": 1.0, "y": 1.0},
                ],
            }
        ],
        "inspection_waypoints": [
            {
                "waypoint_id": "room_a_center",
                "frame_id": "map",
                "x": 0.5,
                "y": 0.5,
                "yaw": 0.0,
                "room_id": "room_a",
                "label": "Room A",
                "waypoint_source": "generated_exploration_candidate",
            }
        ],
        "provenance": {
            "source": "test_nav2_cleanup_bundle",
            "contains_private_scoring_truth": False,
            "contains_runtime_observations": False,
        },
    }
    (bundle_dir / "semantics.json").write_text(json.dumps(semantics), encoding="utf-8")
    return bundle_dir


def _read_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))
