#!/usr/bin/env python3
"""Extract sanitized live report performance metrics."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from roboclaws.core.live_performance import (
    extract_report_performance_metrics,
    read_model_latency_calibration,
)


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Extract roboclaws_report_performance_metrics_v1 from run directories.",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    parser.add_argument("run_dir", type=Path, nargs="+")
    parser.add_argument("--output", type=Path)
    parser.add_argument(
        "--calibration",
        type=Path,
        help="Optional roboclaws_model_latency_calibration_v1 packet for normalized timing.",
    )
    parser.add_argument(
        "--write-model-call-metrics",
        action="store_true",
        help="Also write model_call_metrics.jsonl into each run directory.",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    calibration = read_model_latency_calibration(args.calibration) if args.calibration else None
    packets = [
        extract_report_performance_metrics(
            run_dir,
            write_model_call_metrics=args.write_model_call_metrics,
            calibration=calibration,
        )
        for run_dir in args.run_dir
    ]
    payload = packets[0] if len(packets) == 1 else {"runs": packets}
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(
            json.dumps(payload, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        print(f"metrics: {args.output}")
    else:
        print(json.dumps(payload, indent=2, sort_keys=True))
    if args.write_model_call_metrics:
        for packet in packets:
            run_dir = Path(str(packet["run_dir"]))
            print(f"model calls: {run_dir / 'model_call_metrics.jsonl'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
