#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from roboclaws.reports.household_showcase import DEFAULT_SIZE, render_showcase
from roboclaws.reports.household_showcase_plan import DEFAULT_DURATION_MS, DEFAULT_HOLD_MS


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Render a chaptered household cleanup showcase GIF from a completed run."
    )
    parser.add_argument("--run-dir", type=Path, required=True)
    parser.add_argument("--out-dir", type=Path, default=None)
    parser.add_argument("--basename", default="showcase")
    parser.add_argument("--width", type=int, default=DEFAULT_SIZE[0])
    parser.add_argument("--height", type=int, default=DEFAULT_SIZE[1])
    parser.add_argument("--duration-ms", type=int, default=DEFAULT_DURATION_MS)
    parser.add_argument("--hold-ms", type=int, default=DEFAULT_HOLD_MS)
    parser.add_argument("--no-bbox", action="store_true", help="Use raw FPV frames.")
    parser.add_argument("--skip-gif", action="store_true")
    parser.add_argument(
        "--max-chain-frames",
        type=int,
        default=0,
        help="Optional cap per object chain. Zero keeps every action frame.",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    try:
        manifest = render_showcase(
            run_dir=args.run_dir,
            out_dir=args.out_dir or args.run_dir / "showcase",
            basename=args.basename,
            size=(args.width, args.height),
            duration_ms=args.duration_ms,
            hold_ms=args.hold_ms,
            prefer_bbox=not args.no_bbox,
            write_gif=not args.skip_gif,
            max_chain_frames=args.max_chain_frames,
        )
    except (OSError, ValueError) as exc:
        raise SystemExit(str(exc)) from exc
    print(json.dumps(manifest, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
