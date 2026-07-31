"""Compose the package-owned B1 / Map 12 navigation proof lifecycle."""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from roboclaws.backends.isaaclab import (
    b1_navigation_smoke,
    b1_readiness,
    rby1m_robot_usd,
)
from roboclaws.backends.isaaclab.b1_readiness_validation import DEFAULT_B1_VISUAL_ROUTE_SCENE_USD
from roboclaws.backends.isaaclab.isaac_robot_import import ISAAC_RBY1M_ROBOT_USD_PATH
from roboclaws.core import nvidia_eula as eula


@dataclass(frozen=True)
class B1NavigationProofRequest:
    project_python: Path = Path(".venv/bin/python")
    b1_root: Path = Path("data/robot-data-lab/scene-engine/data/2rd_floor_seperated")
    map12_root: Path = Path("vendors/agibot_sdk/artifacts/maps/robot_map_12")
    output_dir: Path = Path("output/b1-map12/navigation-smoke")
    readiness_output: Path | None = None
    alignment_artifact: Path = Path("output/b1-map12/alignment/alignment_residuals.json")
    waypoint_pose_requests: Path | None = None
    render_scene_usd: Path = DEFAULT_B1_VISUAL_ROUTE_SCENE_USD
    stamp: str = ""
    robot_name: str = "rby1m"
    prepare_robot_usd: bool = True
    require_navigation_success: bool = True
    accept_nvidia_eula: bool = False


def parse_args(argv: list[str] | None = None) -> B1NavigationProofRequest:
    parser = argparse.ArgumentParser(description="Run the B1 / Map 12 navigation proof lifecycle.")
    parser.add_argument("--project-python", type=Path, default=Path(".venv/bin/python"))
    parser.add_argument(
        "--b1-root",
        type=Path,
        default=Path("data/robot-data-lab/scene-engine/data/2rd_floor_seperated"),
    )
    parser.add_argument(
        "--map12-root",
        type=Path,
        default=Path("vendors/agibot_sdk/artifacts/maps/robot_map_12"),
    )
    parser.add_argument("--output-dir", type=Path, default=Path("output/b1-map12/navigation-smoke"))
    parser.add_argument("--readiness-output", type=Path)
    parser.add_argument(
        "--alignment-artifact",
        type=Path,
        default=Path("output/b1-map12/alignment/alignment_residuals.json"),
    )
    parser.add_argument("--waypoint-pose-requests", type=Path)
    parser.add_argument(
        "--render-scene-usd",
        type=Path,
        default=DEFAULT_B1_VISUAL_ROUTE_SCENE_USD,
    )
    parser.add_argument("--stamp", default="")
    parser.add_argument("--robot-name", default="rby1m")
    parser.add_argument("--prepare-robot-usd", action=argparse.BooleanOptionalAction, default=True)
    parser.add_argument(
        "--require-navigation-success",
        action=argparse.BooleanOptionalAction,
        default=True,
    )
    parser.add_argument("--accept-nvidia-eula", action="store_true")
    return B1NavigationProofRequest(**vars(parser.parse_args(argv)))


def main(argv: list[str] | None = None) -> int:
    return run_navigation_proof(parse_args(argv))


def run_navigation_proof(request: B1NavigationProofRequest) -> int:
    if not eula.accepted(explicit=request.accept_nvidia_eula):
        print(f"error: {eula.required_message('B1 navigation proof')}", file=sys.stderr)
        return 2
    eula.record_acceptance()

    run_dir = request.output_dir / (request.stamp or _timestamp())
    run_dir.mkdir(parents=True, exist_ok=True)
    readiness_before = request.readiness_output or run_dir / "readiness.json"
    navigation_artifact = run_dir / "navigation_smoke.json"
    readiness_after = run_dir / "readiness_with_navigation.json"

    readiness_request = b1_readiness.B1ReadinessRequest(
        b1_root=request.b1_root,
        map12_root=request.map12_root,
        alignment_artifact=request.alignment_artifact,
        output=readiness_before,
    )
    if b1_readiness.run_b1_readiness(readiness_request) != 0:
        return 2
    if request.prepare_robot_usd and not ISAAC_RBY1M_ROBOT_USD_PATH.is_file():
        robot_request = rby1m_robot_usd.Rby1mRobotUsdRequest(
            output_usd_path=ISAAC_RBY1M_ROBOT_USD_PATH,
            robot_name=request.robot_name,
            static_only=True,
        )
        if rby1m_robot_usd.import_rby1m_robot_usd(robot_request).get("status") != "ready":
            return 2
    navigation_request = b1_navigation_smoke.B1NavigationSmokeRequest(
        output_dir=run_dir,
        readiness_artifact=readiness_before,
        waypoint_pose_requests=request.waypoint_pose_requests,
        robot_name=request.robot_name,
        render_scene_usd=request.render_scene_usd,
    )
    if b1_navigation_smoke.run_navigation_smoke(navigation_request) != 0:
        return 2
    final_readiness_request = b1_readiness.B1ReadinessRequest(
        b1_root=request.b1_root,
        map12_root=request.map12_root,
        alignment_artifact=request.alignment_artifact,
        output=readiness_after,
        navigation_artifact=navigation_artifact,
        require_navigation_success=request.require_navigation_success,
    )
    if b1_readiness.run_b1_readiness(final_readiness_request) != 0:
        return 2
    if (
        _run_project_stage(_report_command(request, run_dir, navigation_artifact, readiness_after))
        != 0
    ):
        return 2
    preview_dir = run_dir / "operator-preview"
    if _run_project_stage(_preview_command(request, preview_dir, navigation_artifact)) != 0:
        return 2
    print(
        json.dumps(
            {
                "schema": "b1_map12_navigation_proof_v1",
                "status": "passed",
                "run_dir": str(run_dir),
                "readiness_before": str(readiness_before),
                "navigation_artifact": str(navigation_artifact),
                "readiness_after": str(readiness_after),
                "report": str(run_dir / "report.html"),
                "preview": str(preview_dir / "b1-map12-preview.json"),
            },
            sort_keys=True,
        )
    )
    return 0


def _report_command(
    request: B1NavigationProofRequest,
    run_dir: Path,
    navigation_artifact: Path,
    readiness_artifact: Path,
) -> list[str]:
    result = [
        str(request.project_python),
        "-m",
        "roboclaws.backends.isaaclab.b1_navigation_report",
        "--run-dir",
        str(run_dir),
        "--navigation-artifact",
        str(navigation_artifact),
        "--readiness-artifact",
        str(readiness_artifact),
    ]
    if request.waypoint_pose_requests is not None:
        result.extend(("--waypoint-pose-requests", str(request.waypoint_pose_requests)))
    return result


def _preview_command(
    request: B1NavigationProofRequest,
    preview_dir: Path,
    navigation_artifact: Path,
) -> list[str]:
    return [
        str(request.project_python),
        "-m",
        "roboclaws.operator_console.scene_preview_cli",
        "--world",
        "b1-map12",
        "--b1-camera-artifact",
        str(navigation_artifact),
        "--output-dir",
        str(preview_dir),
    ]


def _run_project_stage(command: list[str]) -> int:
    return subprocess.run(command, check=False).returncode


def _timestamp() -> str:
    return datetime.now(ZoneInfo("Asia/Shanghai")).strftime("%m%d_%H%M%S")


if __name__ == "__main__":
    raise SystemExit(main())
