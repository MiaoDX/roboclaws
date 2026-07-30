#!/usr/bin/env python3
"""Compare sanitized live report performance metrics."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

from roboclaws.core.json_sources import read_json_object
from roboclaws.core.live_performance import compare_run_dirs, read_model_latency_calibration


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Compare roboclaws_report_performance_metrics_v1 packets from live run dirs.",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    parser.add_argument("--baseline-run-dir", type=Path)
    parser.add_argument("--candidate-run-dir", type=Path)
    parser.add_argument("--manifest", type=Path)
    parser.add_argument("--output", type=Path)
    parser.add_argument(
        "--calibration",
        type=Path,
        help="Optional roboclaws_model_latency_calibration_v1 packet for normalized timing.",
    )
    parser.add_argument("--diagnostic", action="store_true")
    parser.add_argument("--quality-waiver", default="")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    calibration = read_model_latency_calibration(args.calibration) if args.calibration else None
    if args.manifest:
        payload = _compare_manifest(
            args.manifest,
            diagnostic=args.diagnostic,
            calibration=calibration,
        )
    elif args.baseline_run_dir and args.candidate_run_dir:
        payload = compare_run_dirs(
            baseline_dir=args.baseline_run_dir,
            candidate_dir=args.candidate_run_dir,
            quality_waiver=args.quality_waiver,
            diagnostic=args.diagnostic,
            calibration=calibration,
        )
    else:
        print(
            "error: provide --manifest or both --baseline-run-dir and --candidate-run-dir",
            file=sys.stderr,
        )
        return 2

    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(
            json.dumps(payload, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        print(f"comparison: {args.output}")
    else:
        print(json.dumps(payload, indent=2, sort_keys=True))
    _print_summary(payload)
    return 1 if _has_rejections(payload) else 0


def _compare_manifest(
    path: Path,
    *,
    diagnostic: bool,
    calibration: dict[str, Any] | None,
) -> dict[str, Any]:
    manifest = read_json_object(path, label="report performance comparison manifest")
    entries = manifest.get("comparisons")
    if not isinstance(entries, list):
        raise SystemExit("manifest must contain comparisons list")
    rows = []
    for entry in entries:
        if not isinstance(entry, dict):
            continue
        rows.append(
            compare_run_dirs(
                baseline_dir=Path(str(entry.get("baseline_run_dir") or "")),
                candidate_dir=Path(str(entry.get("candidate_run_dir") or "")),
                key=str(entry.get("key") or ""),
                quality_waiver=str(entry.get("quality_waiver") or ""),
                calibration=calibration,
                diagnostic=diagnostic
                or bool(entry.get("diagnostic"))
                or str(entry.get("baseline_role") or "") == "diagnostic",
            )
        )
    return {
        "schema": "roboclaws_report_performance_manifest_comparison_v1",
        "manifest": str(path),
        "comparisons": rows,
        "summary": {
            "status_counts": _status_counts(rows),
            "rejected": [row.get("key") for row in rows if row.get("status") == "rejected"],
            "accepted": [row.get("key") for row in rows if row.get("status") == "accepted"],
            "diagnostic": [row.get("key") for row in rows if row.get("status") == "diagnostic"],
        },
    }


def _print_summary(payload: dict[str, Any]) -> None:
    rows = payload.get("comparisons") if isinstance(payload.get("comparisons"), list) else [payload]
    print("report performance comparison")
    for row in rows:
        timing = row.get("timing_comparison") or {}
        quality = row.get("quality_comparison") or {}
        model_work = row.get("model_work_comparison") or {}
        print(
            f"- {row.get('key') or '<pair>'}: {row.get('status')} "
            f"wall_delta={_signed_duration(timing.get('observed_wall_delta_s'))} "
            f"uncached_delta={model_work.get('total_uncached_input_tokens_delta')} "
            f"quality_regressed={quality.get('regressed')}"
        )


def _has_rejections(payload: dict[str, Any]) -> bool:
    rows = payload.get("comparisons") if isinstance(payload.get("comparisons"), list) else [payload]
    return any(row.get("status") == "rejected" for row in rows if isinstance(row, dict))


def _status_counts(rows: list[dict[str, Any]]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for row in rows:
        status = str(row.get("status") or "unknown")
        counts[status] = counts.get(status, 0) + 1
    return dict(sorted(counts.items()))


def _signed_duration(value: Any) -> str:
    if value is None:
        return "unknown"
    try:
        numeric = float(value)
    except (TypeError, ValueError):
        return "unknown"
    sign = "+" if numeric >= 0 else ""
    return f"{sign}{numeric:.1f}s"


if __name__ == "__main__":
    raise SystemExit(main())
