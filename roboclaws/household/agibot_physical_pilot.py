#!/usr/bin/env python3
from __future__ import annotations

import argparse
import datetime as dt
import json
from pathlib import Path

from roboclaws.household.agibot_sdk_runner import run_physical_agibot_cleanup_pilot


def main() -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Run the AgiBot SDK-backed household navigation/perception "
            "pilot through the SDK CLI boundary."
        )
    )
    parser.add_argument(
        "--context-json",
        type=Path,
        required=True,
        help="Completed agibot_gdk_map_context_authoring_v1 JSON.",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=Path("output/agibot/physical-cleanup-pilot"),
        help="Root output directory for timestamped pilot artifacts.",
    )
    parser.add_argument("--run-dir", type=Path, help="Exact output run directory.")
    parser.add_argument("--waypoint-id", help="Waypoint id to use for the pilot navigation stage.")
    parser.add_argument("--runner-python", required=True, help="Injected SDK Python executable.")
    parser.add_argument(
        "--runner-script",
        type=Path,
        required=True,
        help="Path to the injected AgiBot SDK runner script.",
    )
    parser.add_argument(
        "--agibot-map-artifact-dir",
        type=Path,
        required=True,
        help="Path to the injected AgiBot map artifact root.",
    )
    parser.add_argument(
        "--real-movement-enabled",
        action="store_true",
        help=(
            "Allow the SDK runner to pass --execute for observation/navigation. "
            "Without this, navigation is a dry-run blocked-capability rehearsal."
        ),
    )
    args = parser.parse_args()

    run_dir = args.run_dir or args.output_dir / _stamp()
    result = run_physical_agibot_cleanup_pilot(
        run_dir=run_dir,
        context_json=args.context_json,
        runner_script=args.runner_script,
        runner_python=args.runner_python,
        real_movement_enabled=args.real_movement_enabled,
        agibot_map_artifact_dir=args.agibot_map_artifact_dir,
        waypoint_id=args.waypoint_id,
    )
    print(
        json.dumps(
            {
                "run_dir": str(run_dir),
                "status": result["cleanup_status"],
                "report": str(run_dir / "report.html"),
                "subphase_reports": [
                    item["report"] for item in result["agibot_sdk_runner"]["subphase_reports"]
                ],
            },
            indent=2,
        )
    )
    return 0


def _stamp() -> str:
    return dt.datetime.now(dt.timezone(dt.timedelta(hours=8))).strftime("%Y%m%d%H%M%S")


if __name__ == "__main__":
    raise SystemExit(main())
