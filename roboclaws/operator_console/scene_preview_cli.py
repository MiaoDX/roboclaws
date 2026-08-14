"""Command-line composition for operator-console scene previews."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from roboclaws.launch.worlds import MOLMOSPACES_CONSOLE_WORLD_IDS
from roboclaws.operator_console.scene_preview_b1 import render_b1_map12_preview
from roboclaws.operator_console.scene_preview_contract import (
    B1_MAP12_WORLD_ID,
    DEFAULT_HEIGHT,
    DEFAULT_OUTPUT_DIR,
    DEFAULT_WIDTH,
    DEFAULT_WORK_DIR,
)
from roboclaws.operator_console.scene_preview_molmospaces import render_molmospaces_preview


def main(argv: list[str] | None = None) -> int:
    report = render_previews(parse_args(argv))
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0 if report["status"] == "success" else 2


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Render real MolmoSpaces MuJoCo views and provenance-backed B1 / Map 12 "
            "operator-console scene previews."
        ),
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    parser.add_argument("--world", action="append", default=[])
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--work-dir", type=Path, default=DEFAULT_WORK_DIR)
    parser.add_argument("--seed", type=int, default=7)
    parser.add_argument("--width", type=_positive_int_arg, default=DEFAULT_WIDTH)
    parser.add_argument("--height", type=_positive_int_arg, default=DEFAULT_HEIGHT)
    parser.add_argument("--skip-existing", action="store_true")
    parser.add_argument("--b1-camera-artifact", type=Path)
    return parser.parse_args(argv)


def render_previews(args: argparse.Namespace) -> dict[str, Any]:
    args.output_dir.mkdir(parents=True, exist_ok=True)
    args.work_dir.mkdir(parents=True, exist_ok=True)
    results = []
    for world_id in _selected_world_ids(args.world):
        if world_id == B1_MAP12_WORLD_ID:
            result = render_b1_map12_preview(
                output_dir=args.output_dir,
                width=int(args.width),
                height=int(args.height),
                skip_existing=bool(args.skip_existing),
                camera_artifact=args.b1_camera_artifact,
            )
        else:
            result = render_molmospaces_preview(
                world_id=world_id,
                output_dir=args.output_dir,
                work_dir=args.work_dir,
                seed=int(args.seed),
                width=int(args.width),
                height=int(args.height),
                skip_existing=bool(args.skip_existing),
            )
        results.append(result)
    return {
        "schema": "operator_console_scene_preview_render_report_v1",
        "status": (
            "success"
            if all(item.get("status") in {"rendered", "skipped"} for item in results)
            else "failed"
        ),
        "generated_at": _utc_timestamp(),
        "output_dir": str(args.output_dir),
        "work_dir": str(args.work_dir),
        "results": results,
    }


def _selected_world_ids(raw_world_ids: list[str]) -> tuple[str, ...]:
    return (
        tuple(raw_world_ids)
        if raw_world_ids
        else (*MOLMOSPACES_CONSOLE_WORLD_IDS, B1_MAP12_WORLD_ID)
    )


def _utc_timestamp() -> str:
    import datetime as dt

    return dt.datetime.now(dt.UTC).isoformat()


def _positive_int_arg(value: str) -> int:
    parsed = int(value)
    if parsed <= 0:
        raise argparse.ArgumentTypeError("must be a positive integer")
    return parsed
