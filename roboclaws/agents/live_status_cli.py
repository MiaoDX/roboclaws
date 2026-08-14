"""Command-line entrypoint for current OpenAI Agents SDK run status."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from roboclaws.agents.live_status_summary import (
    DEFAULT_SEARCH_ROOT,
    _is_live_run_dir,
    _print_summary,
    _resolve_run_dir,
    _summarize,
)


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Probe a current OpenAI Agents SDK household run.",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    parser.add_argument(
        "path",
        nargs="?",
        default="",
        help="run directory, run root, or run_result.json; defaults to the latest SDK run",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    run_dir = _resolve_run_dir(Path(args.path) if args.path else None)
    if run_dir is None:
        print(f"error: no run found under {DEFAULT_SEARCH_ROOT}", file=sys.stderr)
        return 1
    if not run_dir.exists():
        print(f"error: run path does not exist: {run_dir}", file=sys.stderr)
        return 1
    if not _is_live_run_dir(run_dir):
        print(f"error: run path has no live-run evidence: {run_dir}", file=sys.stderr)
        return 1
    try:
        summary = _summarize(run_dir)
    except ValueError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    _print_summary(summary)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
