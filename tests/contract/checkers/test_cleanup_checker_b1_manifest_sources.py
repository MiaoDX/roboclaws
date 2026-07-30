from __future__ import annotations

import json
from pathlib import Path

import pytest

from roboclaws.household import cleanup_validation_planner as checker_module


def _load_checker():
    return checker_module


@pytest.mark.parametrize(
    ("source", "message"),
    [
        (
            "{not-json\n",
            (
                r"B1 robot consumption manifest source must contain valid JSON object: "
                r".*b1_robot_consumption_manifest\.json"
            ),
        ),
        (
            "[]\n",
            (
                r"B1 robot consumption manifest source must contain a JSON object: "
                r".*b1_robot_consumption_manifest\.json"
            ),
        ),
    ],
)
def test_checker_rejects_malformed_b1_robot_consumption_manifest_source(
    tmp_path: Path,
    source: str,
    message: str,
) -> None:
    checker = _load_checker()
    (tmp_path / "b1_robot_consumption_manifest.json").write_text(source, encoding="utf-8")

    with pytest.raises(ValueError, match=message):
        checker._assert_b1_robot_consumption_manifest(tmp_path, _b1_proof())


def test_checker_rejects_missing_b1_robot_consumption_manifest_source(tmp_path: Path) -> None:
    checker = _load_checker()

    with pytest.raises(
        FileNotFoundError,
        match=(
            r"B1 robot consumption manifest source is missing: "
            r".*b1_robot_consumption_manifest\.json"
        ),
    ):
        checker._assert_b1_robot_consumption_manifest(tmp_path, _b1_proof())


@pytest.mark.parametrize(
    ("source", "message"),
    [
        (
            "{not-json\n",
            r"B1 Nav2 semantics source must contain valid JSON object: .*semantics\.json",
        ),
        (
            "[]\n",
            r"B1 Nav2 semantics source must contain a JSON object: .*semantics\.json",
        ),
    ],
)
def test_checker_rejects_malformed_b1_semantics_source(
    tmp_path: Path,
    source: str,
    message: str,
) -> None:
    checker = _load_checker()
    semantics_path = tmp_path / "map_bundle" / "semantics.json"
    semantics_path.parent.mkdir()
    semantics_path.write_text(source, encoding="utf-8")
    _write_b1_manifest(tmp_path)

    with pytest.raises(ValueError, match=message):
        checker._assert_b1_robot_consumption_proof(_b1_run_result(), tmp_path)


def test_checker_rejects_missing_b1_semantics_source(tmp_path: Path) -> None:
    checker = _load_checker()
    _write_b1_manifest(tmp_path)

    with pytest.raises(
        FileNotFoundError,
        match=r"B1 Nav2 semantics source is missing: .*map_bundle/semantics\.json",
    ):
        checker._assert_b1_robot_consumption_proof(_b1_run_result(), tmp_path)


def _b1_proof() -> dict[str, object]:
    return {
        "status": "robot_navigation_verified",
        "alignment_status": "verified",
        "navigation_status": "verified",
        "alignment_artifact": "alignment.json",
        "navigation_artifact": "navigation.json",
        "robot_navigation_provenance": "isaac_b1_map12_navigation_smoke",
        "navigation_waypoint_count": 1,
    }


def _b1_run_result() -> dict[str, object]:
    return {
        "nav2_map_bundle": {
            "schema": "nav2_map_bundle_snapshot_v1",
            "snapshot_complete": True,
            "artifact_paths": {"semantics_json": "map_bundle/semantics.json"},
            "artifact_hashes": {"semantics_json": "0" * 64},
        }
    }


def _write_b1_manifest(tmp_path: Path) -> None:
    manifest = {
        "schema": "b1_map12_robot_consumption_manifest_v1",
        "status": "robot_navigation_ready",
        "navigation": {
            "ready": True,
            **_b1_proof(),
        },
        "capabilities": {
            "robot_navigation": True,
            "manipulation": False,
        },
        "semantics": {
            "object_projection_status": "blocked_until_object_semantic_anchors",
        },
        "policy": {
            "no_output_directory_autodiscovery": True,
            "object_labels_are_not_inferred_from_room_anchors": True,
        },
    }
    (tmp_path / "b1_robot_consumption_manifest.json").write_text(
        json.dumps(manifest),
        encoding="utf-8",
    )
