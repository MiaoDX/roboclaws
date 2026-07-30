from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path

import pytest

from scripts.isaac_lab_cleanup.run_b1_map12_navigation_smoke import run_navigation_smoke

REPO_ROOT = Path(__file__).resolve().parents[3]
SCRIPT = REPO_ROOT / "scripts" / "isaac_lab_cleanup" / "run_b1_map12_navigation_smoke.py"


@pytest.mark.parametrize(
    ("source", "message"),
    (
        ("{not-json\n", "readiness artifact source must contain valid JSON object"),
        ("[]\n", "readiness artifact source must contain a JSON object"),
    ),
)
def test_navigation_smoke_cli_rejects_malformed_readiness_source(
    tmp_path: Path,
    source: str,
    message: str,
) -> None:
    readiness_path = tmp_path / "readiness.json"
    readiness_path.write_text(source, encoding="utf-8")
    waypoint_path = tmp_path / "waypoint_pose_requests.json"
    waypoint_path.write_text(json.dumps(_ready_waypoint_pose_requests()), encoding="utf-8")
    output_dir = tmp_path / "navigation-smoke"

    completed = _run_smoke(
        readiness_path=readiness_path,
        waypoint_path=waypoint_path,
        output_dir=output_dir,
    )

    assert completed.returncode != 0
    assert message in completed.stderr
    assert not (output_dir / "navigation_smoke.json").exists()


def test_navigation_smoke_cli_rejects_missing_readiness_source(tmp_path: Path) -> None:
    readiness_path = tmp_path / "missing_readiness.json"
    waypoint_path = tmp_path / "waypoint_pose_requests.json"
    waypoint_path.write_text(json.dumps(_ready_waypoint_pose_requests()), encoding="utf-8")
    output_dir = tmp_path / "navigation-smoke"

    completed = _run_smoke(
        readiness_path=readiness_path,
        waypoint_path=waypoint_path,
        output_dir=output_dir,
    )

    assert completed.returncode != 0
    assert "readiness artifact source is missing:" in completed.stderr
    assert not (output_dir / "navigation_smoke.json").exists()


@pytest.mark.parametrize(
    ("source", "message"),
    (
        (
            "{not-json\n",
            "waypoint pose request artifact source must contain valid JSON object",
        ),
        ("[]\n", "waypoint pose request artifact source must contain a JSON object"),
    ),
)
def test_navigation_smoke_cli_rejects_malformed_waypoint_request_source(
    tmp_path: Path,
    source: str,
    message: str,
) -> None:
    readiness_path = tmp_path / "readiness.json"
    readiness_path.write_text(json.dumps(_readiness()), encoding="utf-8")
    waypoint_path = tmp_path / "waypoint_pose_requests.json"
    waypoint_path.write_text(source, encoding="utf-8")
    output_dir = tmp_path / "navigation-smoke"

    completed = _run_smoke(
        readiness_path=readiness_path,
        waypoint_path=waypoint_path,
        output_dir=output_dir,
    )

    assert completed.returncode != 0
    assert message in completed.stderr
    assert not (output_dir / "navigation_smoke.json").exists()


def test_navigation_smoke_cli_rejects_missing_waypoint_request_source(tmp_path: Path) -> None:
    readiness_path = tmp_path / "readiness.json"
    readiness_path.write_text(json.dumps(_readiness()), encoding="utf-8")
    waypoint_path = tmp_path / "missing_waypoint_pose_requests.json"
    output_dir = tmp_path / "navigation-smoke"

    completed = _run_smoke(
        readiness_path=readiness_path,
        waypoint_path=waypoint_path,
        output_dir=output_dir,
    )

    assert completed.returncode != 0
    assert "waypoint pose request artifact source is missing:" in completed.stderr
    assert not (output_dir / "navigation_smoke.json").exists()


@pytest.mark.parametrize(
    ("source", "message"),
    (
        (
            "{not-json\n",
            "navigation smoke capture request source must contain valid JSON object",
        ),
        ("[]\n", "navigation smoke capture request source must contain a JSON object"),
    ),
)
def test_navigation_smoke_capture_one_rejects_malformed_request_source(
    tmp_path: Path,
    source: str,
    message: str,
) -> None:
    request_path = tmp_path / "capture_request.json"
    result_path = tmp_path / "capture_result.json"
    request_path.write_text(source, encoding="utf-8")

    completed = subprocess.run(
        [
            sys.executable,
            str(SCRIPT),
            "_capture-one",
            "--request",
            str(request_path),
            "--output",
            str(result_path),
        ],
        capture_output=True,
        text=True,
    )

    assert completed.returncode != 0
    assert message in completed.stderr
    assert not result_path.exists()


def test_navigation_smoke_records_malformed_child_result_as_source_failure(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    output_dir = tmp_path / "navigation-smoke"
    scene_usd = tmp_path / "scene.usd"
    readiness_path = tmp_path / "readiness.json"
    scene_usd.write_text("#usda 1.0\n", encoding="utf-8")
    readiness_path.write_text(json.dumps(_readiness_with_waypoints()), encoding="utf-8")

    def fake_run(*args: object, **kwargs: object) -> subprocess.CompletedProcess[str]:
        command = list(args[0]) if args else list(kwargs["args"])
        result_path = Path(command[command.index("--output") + 1])
        result_path.write_text("{bad json\n", encoding="utf-8")
        return subprocess.CompletedProcess(command, 0, stdout="", stderr="child stderr")

    monkeypatch.setattr(subprocess, "run", fake_run)
    monkeypatch.setattr(
        "roboclaws.backends.isaaclab.runtime_state._rby1m_robot_import_plan",
        lambda robot_name: {"status": "imported", "robot_name": robot_name},
    )

    rc = run_navigation_smoke(
        argparse.Namespace(
            output_dir=output_dir,
            readiness_artifact=readiness_path,
            b1_root=None,
            map12_root=None,
            waypoint_pose_requests=None,
            render_scene_usd=scene_usd,
            robot_name="rby1m",
            render_width=64,
            render_height=64,
        )
    )

    artifact = json.loads((output_dir / "navigation_smoke.json").read_text(encoding="utf-8"))
    assert rc == 2
    assert artifact["status"] == "blocked"
    assert artifact["child_failures"]
    assert (
        "navigation smoke child result source must contain valid JSON object"
        in artifact["child_failures"][0]["source_error"]
    )
    assert artifact["waypoint_evidence"] == []


def _run_smoke(
    *,
    readiness_path: Path,
    waypoint_path: Path,
    output_dir: Path,
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [
            sys.executable,
            str(SCRIPT),
            "--readiness-artifact",
            str(readiness_path),
            "--waypoint-pose-requests",
            str(waypoint_path),
            "--output-dir",
            str(output_dir),
        ],
        capture_output=True,
        text=True,
    )


def _readiness() -> dict[str, object]:
    return {"schema": "b1_map12_digital_twin_readiness_v1"}


def _ready_waypoint_pose_requests() -> dict[str, object]:
    return {
        "schema": "b1_map12_waypoint_pose_requests_v1",
        "status": "ready",
        "semantic_source": "b1_map12_reviewed_alignment_overlay",
        "alignment_transform_source": "reviewed_correspondence_fit",
        "planner_backed": False,
        "physical_robot": False,
        "robot_navigation_supported": False,
        "waypoint_count": 2,
        "blocked_request_count": 0,
        "blocked_requests": [],
        "waypoints": [
            {
                "waypoint_id": "manual_point_a",
                "alignment_transform_source": "reviewed_correspondence_fit",
                "alignment_artifact": "alignment_residuals.json",
                "b1_pose": {"x": 1.0, "y": 2.0},
            },
            {
                "waypoint_id": "manual_point_b",
                "alignment_transform_source": "reviewed_correspondence_fit",
                "alignment_artifact": "alignment_residuals.json",
                "b1_pose": {"x": 2.0, "y": 3.0},
            },
        ],
    }


def _readiness_with_waypoints() -> dict[str, object]:
    readiness = _readiness()
    readiness["map12_overlay"] = {
        "candidate_waypoints": [
            {
                "waypoint_id": "manual_point_a",
                "alignment_transform_source": "reviewed_correspondence_fit",
                "alignment_artifact": "alignment_residuals.json",
                "b1_pose": {"x": 1.0, "y": 2.0},
            },
            {
                "waypoint_id": "manual_point_b",
                "alignment_transform_source": "reviewed_correspondence_fit",
                "alignment_artifact": "alignment_residuals.json",
                "b1_pose": {"x": 2.0, "y": 3.0},
            },
        ]
    }
    return readiness
