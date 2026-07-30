#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

if __package__ in {None, ""}:
    repo_root = Path(__file__).resolve().parents[2]
    if str(repo_root) not in sys.path:
        sys.path.insert(0, str(repo_root))

from roboclaws.maps.runtime_prior_conversion import (  # noqa: E402
    runtime_prior_snapshot_from_agibot_navigation_memory,
)
from roboclaws.maps.runtime_prior_materialization import (  # noqa: E402
    materialize_runtime_prior_targets,
)


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Convert an Agibot navigation_memory map folder into an "
            "runtime_map_prior_snapshot_v1 artifact."
        )
    )
    parser.add_argument(
        "map_dir",
        type=Path,
        help="Map folder containing navigation_memory.json and agibot/nav2.yaml.",
    )
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument(
        "--summary-json",
        type=Path,
        help="Optional path for a compact materialized-target summary.",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> None:
    args = parse_args(argv)
    snapshot = runtime_prior_snapshot_from_agibot_navigation_memory(args.map_dir)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(snapshot, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    materialized = materialize_runtime_prior_targets(snapshot)
    if args.summary_json is not None:
        args.summary_json.parent.mkdir(parents=True, exist_ok=True)
        args.summary_json.write_text(
            json.dumps(materialized, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
    print(
        "runtime-map-prior snapshot exported: "
        f"{args.output} anchors={snapshot['summary']['anchor_count']} "
        f"fixtures={snapshot['summary']['fixture_candidate_count']} "
        f"waypoints={snapshot['summary']['inspection_waypoint_count']}"
    )


if __name__ == "__main__":
    main()
