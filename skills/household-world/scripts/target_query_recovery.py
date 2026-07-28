#!/usr/bin/env python3
"""Skill helper for public Runtime Metric Map target-query recovery."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from roboclaws.core.json_sources import read_json_object
from roboclaws.household.target_query import resolve_target_query


def resolve_from_runtime_map(
    runtime_metric_map: dict[str, Any],
    query: str,
    *,
    operation: str = "inspect",
    max_results: int = 8,
) -> dict[str, Any]:
    return resolve_target_query(
        runtime_metric_map,
        query,
        operation=operation,
        max_results=max_results,
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Resolve a target query against public runtime_metric_map target candidates.",
    )
    parser.add_argument("runtime_metric_map", type=Path)
    parser.add_argument("query")
    parser.add_argument("--operation", default="inspect")
    parser.add_argument("--max-results", type=int, default=8)
    args = parser.parse_args(argv)

    try:
        runtime_map = read_json_object(args.runtime_metric_map, label="runtime_metric_map")
    except (OSError, ValueError) as exc:
        raise SystemExit(str(exc)) from exc
    resolution = resolve_from_runtime_map(
        runtime_map,
        args.query,
        operation=args.operation,
        max_results=args.max_results,
    )
    print(json.dumps(resolution, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
