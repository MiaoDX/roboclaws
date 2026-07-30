from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[3]
MODULE = "roboclaws.backends.isaaclab.b1_waypoint_pose_requests"


@pytest.mark.parametrize(
    ("source", "message"),
    (
        ("{not-json\n", "points must contain valid JSON array"),
        ('{"x": 1.0, "y": 2.0}\n', "points must contain a JSON array"),
    ),
)
def test_waypoint_pose_request_cli_rejects_malformed_points_source(
    tmp_path: Path,
    source: str,
    message: str,
) -> None:
    alignment_path = tmp_path / "alignment_residuals.json"
    alignment_path.write_text(
        json.dumps({"schema": "b1_map12_alignment_residuals_v1"}),
        encoding="utf-8",
    )
    points_path = tmp_path / "points.json"
    points_path.write_text(source, encoding="utf-8")
    output_path = tmp_path / "waypoint_pose_requests.json"

    completed = _run_builder(
        tmp_path,
        alignment_path=alignment_path,
        points_path=points_path,
        output_path=output_path,
    )

    assert completed.returncode != 0
    assert message in completed.stderr
    assert not output_path.exists()


def test_waypoint_pose_request_cli_rejects_missing_points_source(tmp_path: Path) -> None:
    alignment_path = tmp_path / "alignment_residuals.json"
    alignment_path.write_text(
        json.dumps({"schema": "b1_map12_alignment_residuals_v1"}),
        encoding="utf-8",
    )
    points_path = tmp_path / "missing_points.json"
    output_path = tmp_path / "waypoint_pose_requests.json"

    completed = _run_builder(
        tmp_path,
        alignment_path=alignment_path,
        points_path=points_path,
        output_path=output_path,
    )

    assert completed.returncode != 0
    assert "points missing:" in completed.stderr
    assert not output_path.exists()


@pytest.mark.parametrize(
    ("source", "message"),
    (
        ("{not-json\n", "alignment artifact source must contain valid JSON object"),
        ("[]\n", "alignment artifact source must contain a JSON object"),
    ),
)
def test_waypoint_pose_request_cli_rejects_malformed_alignment_source(
    tmp_path: Path,
    source: str,
    message: str,
) -> None:
    alignment_path = tmp_path / "alignment_residuals.json"
    alignment_path.write_text(source, encoding="utf-8")
    points_path = tmp_path / "points.json"
    points_path.write_text('[{"waypoint_id": "manual_point", "x": 1.0, "y": 2.0}]\n')
    output_path = tmp_path / "waypoint_pose_requests.json"

    completed = _run_builder(
        tmp_path,
        alignment_path=alignment_path,
        points_path=points_path,
        output_path=output_path,
    )

    assert completed.returncode != 0
    assert message in completed.stderr
    assert not output_path.exists()


def test_waypoint_pose_request_cli_rejects_missing_alignment_source(tmp_path: Path) -> None:
    alignment_path = tmp_path / "missing_alignment.json"
    points_path = tmp_path / "points.json"
    points_path.write_text('[{"waypoint_id": "manual_point", "x": 1.0, "y": 2.0}]\n')
    output_path = tmp_path / "waypoint_pose_requests.json"

    completed = _run_builder(
        tmp_path,
        alignment_path=alignment_path,
        points_path=points_path,
        output_path=output_path,
    )

    assert completed.returncode != 0
    assert "alignment artifact source is missing:" in completed.stderr
    assert not output_path.exists()


def _run_builder(
    cwd: Path,
    *,
    alignment_path: Path,
    points_path: Path,
    output_path: Path,
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [
            sys.executable,
            "-m",
            MODULE,
            "--alignment-artifact",
            str(alignment_path),
            "--points",
            str(points_path),
            "--output",
            str(output_path),
        ],
        cwd=cwd,
        capture_output=True,
        text=True,
    )
