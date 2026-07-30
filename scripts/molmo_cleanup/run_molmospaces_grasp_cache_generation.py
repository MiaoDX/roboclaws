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

from roboclaws.household.grasp_cache_generation import (  # noqa: E402
    load_generation_preflight_from_manifest,
    run_grasp_cache_generation,
)
from roboclaws.household.report_planner import render_grasp_cache_generation_report  # noqa: E402


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Generate and install MolmoSpaces rigid grasp cache from a ready preflight."
    )
    parser.add_argument("--preflight-manifest", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--molmospaces-python", type=Path)
    parser.add_argument("--max-successful-grasps", type=int, default=1000)
    parser.add_argument("--num-workers", type=int, default=1)
    parser.add_argument("--approach-steps", type=int)
    parser.add_argument("--shake-steps", type=int)
    parser.add_argument("--timeout-s", type=float, default=3600.0)
    parser.add_argument("--skip-install", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    result = run_grasp_cache_generation(
        generation_preflight=load_generation_preflight_from_manifest(args.preflight_manifest),
        output_dir=args.output_dir,
        molmospaces_python=args.molmospaces_python,
        max_successful_grasps=args.max_successful_grasps,
        num_workers=args.num_workers,
        approach_steps=args.approach_steps,
        shake_steps=args.shake_steps,
        timeout_s=args.timeout_s,
        install=not args.skip_install,
        dry_run=args.dry_run,
    )
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(
            json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8"
        )
    report = render_grasp_cache_generation_report(output_dir=args.output_dir, result=result)
    print(
        json.dumps(
            {
                "status": result["status"],
                "output": str(args.output or ""),
                "report": str(report),
            }
        )
    )


if __name__ == "__main__":
    main()
