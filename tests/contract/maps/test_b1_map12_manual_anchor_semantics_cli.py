from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[3]
MODULE = "roboclaws.maps.b1_semantic_anchor_suggestions"


@pytest.mark.parametrize(
    ("filename", "source", "message"),
    (
        ("draft.json", None, "manual draft source is missing:"),
        (
            "draft.json",
            "{not-json\n",
            "manual draft source must contain valid JSON object",
        ),
        ("draft.json", "[]\n", "manual draft source must contain a JSON object"),
        ("projection.json", "{not-json\n", "room projection source must contain valid JSON object"),
        ("projection.json", "[]\n", "room projection source must contain a JSON object"),
        (
            "scene.json",
            "{not-json\n",
            "scene diagnostic source must contain valid JSON object",
        ),
        (
            "scene.json",
            "[]\n",
            "scene diagnostic source must contain a JSON object",
        ),
    ),
)
def test_manual_anchor_semantics_cli_rejects_bad_source_json(
    tmp_path: Path,
    filename: str,
    source: str | None,
    message: str,
) -> None:
    draft = tmp_path / "draft.json"
    projection = tmp_path / "projection.json"
    scene = tmp_path / "scene.json"
    output = tmp_path / "suggestions.json"
    review_packet = tmp_path / "review_packet.json"
    review_report = tmp_path / "review.html"
    draft.write_text(json.dumps(_draft()), encoding="utf-8")
    projection.write_text(json.dumps(_room_projection()), encoding="utf-8")
    scene.write_text(json.dumps(_scene_diagnostic()), encoding="utf-8")
    target = tmp_path / filename
    if source is None:
        target.unlink()
    else:
        target.write_text(source, encoding="utf-8")

    completed = _run_suggester(
        draft=draft,
        projection=projection,
        scene=scene,
        output=output,
        review_packet=review_packet,
        review_report=review_report,
    )

    assert completed.returncode == 2
    assert message in completed.stderr
    assert str(target) in completed.stderr
    assert not output.exists()
    assert not review_packet.exists()
    assert not review_report.exists()


def test_manual_anchor_semantics_cli_writes_review_outputs_from_loaded_sources(
    tmp_path: Path,
) -> None:
    draft = tmp_path / "draft.json"
    projection = tmp_path / "projection.json"
    scene = tmp_path / "scene.json"
    output = tmp_path / "suggestions.json"
    review_packet = tmp_path / "review_packet.json"
    review_report = tmp_path / "review.html"
    draft.write_text(json.dumps(_draft()), encoding="utf-8")
    projection.write_text(json.dumps(_room_projection()), encoding="utf-8")
    scene.write_text(json.dumps(_scene_diagnostic()), encoding="utf-8")

    completed = _run_suggester(
        draft=draft,
        projection=projection,
        scene=scene,
        output=output,
        review_packet=review_packet,
        review_report=review_report,
    )

    assert completed.returncode == 0, completed.stderr
    payload = json.loads(output.read_text(encoding="utf-8"))
    packet = json.loads(review_packet.read_text(encoding="utf-8"))
    assert payload["schema"] == "b1_map12_manual_anchor_semantic_suggestions_v1"
    assert payload["strong_candidate_count"] == 1
    assert packet["schema"] == "b1_map12_manual_anchor_semantic_review_packet_v1"
    assert packet["proposed_anchor_count"] == 1
    assert "B1 Map12 Manual Anchor Semantic Review" in review_report.read_text(encoding="utf-8")


def _run_suggester(
    *,
    draft: Path,
    projection: Path,
    scene: Path,
    output: Path,
    review_packet: Path,
    review_report: Path,
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [
            sys.executable,
            "-m",
            MODULE,
            "--draft",
            str(draft),
            "--room-projection",
            str(projection),
            "--scene-diagnostic",
            str(scene),
            "--output",
            str(output),
            "--review-packet-output",
            str(review_packet),
            "--review-report-output",
            str(review_report),
        ],
        capture_output=True,
        text=True,
    )


def _draft() -> dict[str, object]:
    return {
        "schema": "b1_map12_correspondences_v1",
        "source_map_frame": "robot_map_12_map",
        "target_scene_frame": "b1_rebuilt_scene_usd_world",
        "anchors": [
            {
                "anchor_id": "manual_draft_anchor",
                "anchor_type": "operator_correspondence",
                "map_xy": [1.0, 1.0],
                "scene_xyz": [1.0, 1.0, 0.0],
                "review_status": "proposed",
            }
        ],
    }


def _room_projection() -> dict[str, object]:
    return {
        "schema": "b1_map12_semantic_projection_v1",
        "rooms": [
            {
                "room_id": "room_a",
                "navigation_area_id": "area_a",
                "asset_partition_id": "partition_a",
                "room_label": "Room A",
                "review_status": "accepted",
                "map_polygon": [
                    {"x": 0.0, "y": 0.0},
                    {"x": 2.0, "y": 0.0},
                    {"x": 2.0, "y": 2.0},
                    {"x": 0.0, "y": 2.0},
                ],
            }
        ],
    }


def _scene_diagnostic() -> dict[str, object]:
    return {
        "schema": "b1_scene_topdown_diagnostic_v1",
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
        ],
    }
