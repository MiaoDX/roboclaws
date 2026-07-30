#!/usr/bin/env python3
"""Dry-run and preflight the private OpenAI Agents SDK speedup matrix."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

from roboclaws.core.json_sources import read_json_object
from roboclaws.core.live_performance import (
    ReportPerformanceSourceError,
    compare_report_performance_metrics,
    extract_report_performance_metrics,
    privacy_findings_for_packet,
    privacy_findings_for_run_dir,
    read_jsonl,
    read_model_latency_calibration,
)


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Build the no-provider Group 0 preflight packet for private "
            "openai-agents-live speedup experiments."
        ),
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--offline-preflight", action="store_true")
    parser.add_argument("--privacy-gate", action="store_true")
    parser.add_argument("--decision-packet", type=Path)
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    manifest = _load_manifest(args.manifest)
    if manifest is None:
        return 1

    run_all = not (args.dry_run or args.offline_preflight or args.privacy_gate)
    dry_run = _dry_run_packet(manifest)
    if args.dry_run or run_all:
        _print_dry_run(dry_run)

    if not (args.offline_preflight or args.privacy_gate or run_all or args.decision_packet):
        return 0

    packet = _decision_packet(manifest, dry_run=dry_run)
    if args.privacy_gate or args.offline_preflight or run_all or args.decision_packet:
        _apply_privacy_gate(packet)
    if args.offline_preflight or run_all or args.decision_packet:
        _apply_offline_preflight(packet)
        _apply_quality_gate(packet)
        _apply_reducible_bucket_reports(packet)
    _finalize_packet(packet)

    if args.decision_packet:
        args.decision_packet.parent.mkdir(parents=True, exist_ok=True)
        args.decision_packet.write_text(
            json.dumps(packet, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        print(f"decision packet: {args.decision_packet}")

    failed = [row for row in packet["rows"] if _is_unexpected_failure(row)]
    if failed:
        for row in failed:
            print(
                f"error: {row['row_id']} {row['status']}: {'; '.join(row.get('reasons') or [])}",
                file=sys.stderr,
            )
        return 1
    return 0


def _load_manifest(path: Path) -> dict[str, Any] | None:
    try:
        payload = read_json_object(path, label="matrix manifest")
    except FileNotFoundError as exc:
        print(f"error: could not read matrix manifest {path}: {exc}", file=sys.stderr)
        return None
    except ValueError as exc:
        message = str(exc)
        if "source must contain a JSON object" in message:
            print("error: matrix manifest must be a JSON object", file=sys.stderr)
            return None
        print(f"error: could not read matrix manifest {path}: {exc}", file=sys.stderr)
        return None
    if payload.get("schema") != "agent_sdk_speedup_matrix_v1":
        print("error: unsupported matrix manifest schema", file=sys.stderr)
        return None
    if rows_error := _matrix_rows_error(payload, source_path=path):
        print(f"error: {rows_error}", file=sys.stderr)
        return None
    return payload


def _matrix_rows_error(payload: dict[str, Any], *, source_path: Path) -> str:
    rows = payload.get("rows")
    if not isinstance(rows, list):
        return f"matrix manifest rows must be a non-empty JSON array: {source_path}"
    if not rows:
        return f"matrix manifest rows must be a non-empty JSON array: {source_path}"
    for index, row in enumerate(rows, start=1):
        if not isinstance(row, dict):
            return f"matrix manifest row {index} must be a JSON object: {source_path}"
    return ""


def _dry_run_packet(manifest: dict[str, Any]) -> dict[str, Any]:
    rows = _rows(manifest)
    budget_caps = _dict(manifest.get("budget_caps"))
    supported_rows = [row for row in rows if not row.get("unsupported_reason")]
    unsupported_rows = [row for row in rows if row.get("unsupported_reason")]
    planned_live_runs = sum(1 for row in supported_rows if bool(row.get("provider_calls")))
    return {
        "schema": "agent_sdk_speedup_matrix_dry_run_v1",
        "budget_caps": budget_caps,
        "concurrency": _int_or_none(budget_caps.get("concurrency")) or 1,
        "racing_multiplier": _float_or_none(budget_caps.get("racing_multiplier")) or 1.0,
        "planned_row_count": len(rows),
        "supported_row_count": len(supported_rows),
        "unsupported_row_count": len(unsupported_rows),
        "planned_live_run_count": planned_live_runs,
        "provider_calls_planned": planned_live_runs > 0,
        "candidate_groups": manifest.get("candidate_groups") or [],
        "rows": [_dry_run_row(row) for row in rows],
        "unsupported_rows": [_dry_run_row(row) for row in unsupported_rows],
    }


def _print_dry_run(packet: dict[str, Any]) -> None:
    print("Agent SDK speedup matrix dry-run")
    print(f"rows: {packet['planned_row_count']} supported={packet['supported_row_count']}")
    print(f"provider_calls_planned: {packet['provider_calls_planned']}")
    print(f"budget_caps: {json.dumps(packet['budget_caps'], sort_keys=True)}")
    for row in packet["rows"]:
        status = "unsupported" if row.get("unsupported_reason") else "planned"
        print(
            f"- {row['row_id']} | {row['provider_profile']} | {row['model']} | "
            f"{row['evidence_lane']} | {row['candidate_group']} | {status}"
        )
        if row.get("unsupported_reason"):
            print(f"  unsupported_reason: {row['unsupported_reason']}")
        print(f"  candidates: {','.join(row.get('candidate_ids') or [])}")
        print(f"  flags: {json.dumps(row.get('feature_flags') or {}, sort_keys=True)}")
        print(f"  dependencies: {','.join(row.get('dependency_candidate_ids') or []) or 'none'}")
        print(f"  stop_conditions: {len(row.get('stop_conditions') or [])}")


def _decision_packet(manifest: dict[str, Any], *, dry_run: dict[str, Any]) -> dict[str, Any]:
    return {
        "schema": "agent_sdk_speedup_decision_packet_v1",
        "matrix_schema": manifest.get("schema"),
        "budget_caps": dry_run["budget_caps"],
        "provider_calls_planned": dry_run["provider_calls_planned"],
        "candidate_groups": manifest.get("candidate_groups") or [],
        "candidate_queue": _candidate_queue(manifest),
        "rows": [_decision_row(row) for row in _rows(manifest)],
        "summary": {},
    }


def _decision_row(row: dict[str, Any]) -> dict[str, Any]:
    unsupported_reason = str(row.get("unsupported_reason") or "")
    payload = {
        "row_id": str(row.get("row_id") or ""),
        "provider_profile": str(row.get("provider_profile") or ""),
        "model": str(row.get("model") or ""),
        "evidence_lane": str(row.get("evidence_lane") or row.get("lane") or ""),
        "candidate_group": str(row.get("candidate_group") or ""),
        "candidate_ids": _str_list(row.get("candidate_ids")),
        "dependency_candidate_ids": _str_list(row.get("dependency_candidate_ids")),
        "feature_flags": _dict(row.get("feature_flags")),
        "stop_conditions": _str_list(row.get("stop_conditions")),
        "baseline_role": str(row.get("baseline_role") or ""),
        "baseline_run_dir": str(row.get("baseline_run_dir") or ""),
        "candidate_run_dir": str(row.get("candidate_run_dir") or ""),
        "calibration_path": str(row.get("calibration_path") or ""),
        "quality_policy": str(row.get("quality_policy") or "same_or_better"),
        "quality_waiver": str(row.get("quality_waiver") or ""),
        "expected_terminal": str(row.get("expected_terminal") or ""),
        "expected_decision_status": str(row.get("expected_decision_status") or ""),
        "unsupported_reason": unsupported_reason,
        "status": "unsupported" if unsupported_reason else "pending",
        "reasons": [unsupported_reason] if unsupported_reason else [],
        "quality_comparison": {},
        "speed_comparison": {},
        "reducible_bucket_report": {},
        "artifact_links": {},
    }
    return payload


def _apply_privacy_gate(packet: dict[str, Any]) -> None:
    findings = _privacy_findings(packet)
    for row in packet["rows"]:
        row_findings = [item for item in findings if item.get("row_id") in {"", row.get("row_id")}]
        if not row_findings:
            row["privacy_gate"] = {"status": "passed", "findings": []}
            continue
        row["privacy_gate"] = {"status": "failed", "findings": row_findings}
        _block(row, "privacy gate failed")


def _apply_offline_preflight(packet: dict[str, Any]) -> None:
    if packet["provider_calls_planned"]:
        for row in packet["rows"]:
            _block(row, "Group 0 foundation cannot plan provider calls")
    for row in packet["rows"]:
        if row["unsupported_reason"]:
            continue
        if not row["row_id"]:
            _block(row, "row_id is required")
        if not row["candidate_ids"]:
            _block(row, "candidate_ids are required")
        if not row["feature_flags"]:
            _block(row, "feature_flags are required")
        if not row["stop_conditions"]:
            _block(row, "stop_conditions are required")
        _load_row_runs(row)


def _apply_quality_gate(packet: dict[str, Any]) -> None:
    for row in packet["rows"]:
        if row["status"] in {"blocked", "unsupported"}:
            continue
        baseline = row.get("_baseline_summary")
        candidate = row.get("_candidate_summary")
        if not isinstance(baseline, dict) or not isinstance(candidate, dict):
            row["status"] = "inconclusive"
            row["reasons"].append("baseline/candidate summaries unavailable")
            continue
        speed = _speed_comparison(baseline, candidate)
        quality = _quality_comparison(baseline, candidate, lane=row["evidence_lane"])
        row["speed_comparison"] = speed
        row["quality_comparison"] = quality
        if row["quality_waiver"]:
            row["status"] = "accepted"
            row["reasons"].append(f"quality waiver: {row['quality_waiver']}")
        elif _expected_blocked_evidence(row, candidate):
            row["status"] = "blocked"
            row["reasons"].append("expected blocked evidence")
        elif _raw_fpv_classified_diagnostic(row, candidate):
            row["status"] = "accepted"
            row["reasons"].append("raw-FPV accepted as classified diagnostic evidence")
        elif quality["regressed"]:
            row["status"] = "rejected"
            row["reasons"].append("behavior quality regressed")
        else:
            row["status"] = "accepted"


def _apply_reducible_bucket_reports(packet: dict[str, Any]) -> None:
    for row in packet["rows"]:
        candidate = row.get("_candidate_summary")
        if not isinstance(candidate, dict):
            row["reducible_bucket_report"] = {"available": False, "recommendations": []}
            continue
        row["reducible_bucket_report"] = _reducible_bucket_report(
            candidate,
            lane=row["evidence_lane"],
        )


def _finalize_packet(packet: dict[str, Any]) -> None:
    for row in packet["rows"]:
        row.pop("_baseline_summary", None)
        row.pop("_candidate_summary", None)
        row.pop("_calibration", None)
    counts: dict[str, int] = {}
    for row in packet["rows"]:
        status = str(row.get("status") or "unknown")
        counts[status] = counts.get(status, 0) + 1
    packet["summary"] = {
        "status_counts": dict(sorted(counts.items())),
        "accepted": [row["row_id"] for row in packet["rows"] if row["status"] == "accepted"],
        "rejected": [row["row_id"] for row in packet["rows"] if row["status"] == "rejected"],
        "blocked": [row["row_id"] for row in packet["rows"] if row["status"] == "blocked"],
        "inconclusive": [
            row["row_id"] for row in packet["rows"] if row["status"] == "inconclusive"
        ],
        "unsupported": [row["row_id"] for row in packet["rows"] if row["status"] == "unsupported"],
        "recommendation_summary": _recommendation_summary(packet["rows"]),
        "candidate_coverage": _candidate_coverage(packet),
    }


def _load_row_runs(row: dict[str, Any]) -> None:
    baseline_dir = Path(row["baseline_run_dir"]) if row["baseline_run_dir"] else None
    candidate_dir = Path(row["candidate_run_dir"]) if row["candidate_run_dir"] else None
    if baseline_dir is None or candidate_dir is None:
        _block(row, "baseline_run_dir and candidate_run_dir are required")
        return
    if not baseline_dir.exists():
        _block(row, f"baseline run dir missing: {baseline_dir}")
        return
    if not candidate_dir.exists():
        _block(row, f"candidate run dir missing: {candidate_dir}")
        return
    calibration = _row_calibration(row)
    if row["calibration_path"] and calibration is None:
        return
    try:
        baseline_summary = _run_summary(baseline_dir, calibration=calibration)
        candidate_summary = _run_summary(candidate_dir, calibration=calibration)
    except ReportPerformanceSourceError as exc:
        _block(row, f"run source error: {exc}")
        return
    row["_calibration"] = calibration
    row["_baseline_summary"] = baseline_summary
    row["_candidate_summary"] = candidate_summary
    row["artifact_links"] = {
        "baseline_run_dir": str(baseline_dir),
        "candidate_run_dir": str(candidate_dir),
        "candidate_report": str(candidate_dir / "report.html"),
        "candidate_live_timing": str(candidate_dir / "live_timing.json"),
    }
    if row["calibration_path"]:
        row["artifact_links"]["calibration"] = row["calibration_path"]


def _row_calibration(row: dict[str, Any]) -> dict[str, Any] | None:
    path = row.get("calibration_path")
    if not path:
        return None
    calibration_path = Path(str(path))
    if not calibration_path.exists():
        _block(row, f"calibration_path missing: {calibration_path}")
        return None
    try:
        return read_model_latency_calibration(calibration_path)
    except ReportPerformanceSourceError as exc:
        _block(row, f"calibration source error: {exc}")
        return None


def _run_summary(run_dir: Path, *, calibration: dict[str, Any] | None = None) -> dict[str, Any]:
    metrics = extract_report_performance_metrics(run_dir, calibration=calibration)
    quality = _dict(metrics.get("quality"))
    timing = _dict(metrics.get("timing"))
    call_counts = _dict(metrics.get("call_counts"))
    trace_events = read_jsonl(run_dir / "trace.jsonl")
    return {
        "run_dir": str(run_dir),
        "elapsed_s": _float_or_none(timing.get("observed_wall_s")),
        "between_tool_gap_s": _float_or_none(timing.get("mcp_between_tool_gap_s")),
        "robot_view_capture_s": _float_or_none(timing.get("robot_view_capture_s")),
        "tool_handler_s": _float_or_none(timing.get("mcp_tool_handler_s")),
        "terminal": quality.get("terminal"),
        "checker": quality.get("checker_state"),
        "run_result_present": quality.get("checker_state") == "result-present",
        "cleanup_status": quality.get("cleanup_status"),
        "completion_status": quality.get("completion_status"),
        "restored_count": quality.get("restored_count"),
        "total_targets": quality.get("total_targets"),
        "mess_restoration_rate": quality.get("mess_restoration_rate"),
        "sweep_coverage_rate": quality.get("sweep_coverage_rate"),
        "disturbance_count": quality.get("disturbance_count"),
        "semantic_accepted_count": quality.get("semantic_accepted_count"),
        "failed_or_noop_tool_count": quality.get("failed_or_noop_tool_count"),
        "tool_counts": _dict(call_counts.get("mcp_tool_counts")),
        "camera_grounded_tool_breakdown": _camera_grounded_tool_breakdown(trace_events),
        "metrics": metrics,
    }


def _speed_comparison(baseline: dict[str, Any], candidate: dict[str, Any]) -> dict[str, Any]:
    comparison = compare_report_performance_metrics(baseline["metrics"], candidate["metrics"])
    timing = _dict(comparison.get("timing_comparison"))
    return {
        "elapsed_delta_s": timing.get("observed_wall_delta_s"),
        "between_tool_gap_delta_s": timing.get("mcp_between_tool_gap_delta_s"),
        "observed_model_api_delta_s": timing.get("observed_model_api_delta_s"),
        "estimated_model_work_delta_s": timing.get("estimated_model_work_delta_s"),
        "model_latency_residual_delta_s": timing.get("model_latency_residual_delta_s"),
        "baseline_estimated_model_work_s": _dict(timing.get("baseline")).get(
            "estimated_model_work_s"
        ),
        "candidate_estimated_model_work_s": _dict(timing.get("candidate")).get(
            "estimated_model_work_s"
        ),
    }


def _quality_comparison(
    baseline: dict[str, Any],
    candidate: dict[str, Any],
    *,
    lane: str,
) -> dict[str, Any]:
    comparison = compare_report_performance_metrics(baseline["metrics"], candidate["metrics"])
    quality = _dict(comparison.get("quality_comparison"))
    checks = _dict(quality.get("checks"))
    if lane == "camera-raw-fpv" and not candidate["run_result_present"]:
        checks["run_result_present"] = candidate["terminal"] not in {"unknown", "missing", ""}
    regressed = not all(checks.values())
    return {
        "policy": "same_or_better",
        "regressed": regressed,
        "checks": checks,
        "baseline": _quality_fields(baseline),
        "candidate": _quality_fields(candidate),
    }


def _quality_fields(summary: dict[str, Any]) -> dict[str, Any]:
    return {
        "run_result_present": summary["run_result_present"],
        "restored_count": summary.get("restored_count"),
        "total_targets": summary.get("total_targets"),
        "mess_restoration_rate": summary.get("mess_restoration_rate"),
        "sweep_coverage_rate": summary.get("sweep_coverage_rate"),
        "disturbance_count": summary.get("disturbance_count"),
        "semantic_accepted_count": summary.get("semantic_accepted_count"),
        "failed_or_noop_tool_count": summary.get("failed_or_noop_tool_count"),
        "terminal": summary.get("terminal"),
    }


def _raw_fpv_classified_diagnostic(row: dict[str, Any], candidate: dict[str, Any]) -> bool:
    if row.get("evidence_lane") != "camera-raw-fpv":
        return False
    terminal = str(candidate.get("terminal") or "")
    if terminal in {"", "unknown", "missing", "finished"}:
        return False
    expected = str(row.get("expected_terminal") or "")
    return not expected or terminal == expected


def _expected_blocked_evidence(row: dict[str, Any], candidate: dict[str, Any]) -> bool:
    flags = _dict(row.get("feature_flags"))
    if not flags.get("expected_blocked_evidence"):
        return False
    expected = str(row.get("expected_terminal") or "")
    terminal = str(candidate.get("terminal") or "")
    if not expected:
        return terminal not in {"", "unknown", "missing", "finished"}
    return terminal == expected


def _reducible_bucket_report(summary: dict[str, Any], *, lane: str) -> dict[str, Any]:
    recommendations: list[dict[str, Any]] = []
    elapsed = _float_or_none(summary.get("elapsed_s")) or 0.0
    between_gap = _float_or_none(summary.get("between_tool_gap_s")) or 0.0
    robot_view = _float_or_none(summary.get("robot_view_capture_s")) or 0.0
    tool_handler = _float_or_none(summary.get("tool_handler_s")) or 0.0
    failed_or_noop_tool_count = _int_or_none(summary.get("failed_or_noop_tool_count")) or 0
    tool_counts = _dict(summary.get("tool_counts"))
    camera_grounded_breakdown = _dict(summary.get("camera_grounded_tool_breakdown"))
    buckets = _latency_buckets(
        elapsed_s=elapsed,
        between_tool_gap_s=between_gap,
        robot_view_capture_s=robot_view,
        tool_handler_s=tool_handler,
    )
    if between_gap > 60 or (elapsed and between_gap / elapsed >= 0.45):
        recommendations.append(
            {
                "candidate_group": "group1_private_sdk_levers",
                "candidate_ids": ["A", "G", "J", "H", "I", "L"],
                "reason": "model/SDK between-tool gap remains a dominant bucket",
            }
        )
    standalone_declares = _int_or_none(
        camera_grounded_breakdown.get("standalone_declare_visual_candidates")
    )
    if (
        lane == "camera-grounded-labels"
        and (
            standalone_declares
            if standalone_declares is not None
            else tool_counts.get(
                "declare_visual_candidates",
                0,
            )
        )
        > 0
    ):
        recommendations.append(
            {
                "candidate_group": "group2_lane_specific_reductions",
                "candidate_ids": ["O"],
                "reason": "standalone camera-grounded observe/label two-step is present",
            }
        )
    if tool_counts.get("metric_map", 0) > 1:
        recommendations.append(
            {
                "candidate_group": "group2_lane_specific_reductions",
                "candidate_ids": ["N"],
                "reason": "metric_map is fetched repeatedly",
            }
        )
    if lane == "camera-raw-fpv" and failed_or_noop_tool_count > 0:
        recommendations.append(
            {
                "candidate_group": "group3_raw_fpv_stabilization",
                "candidate_ids": ["P", "AA"],
                "reason": "raw-FPV has repeated public failure evidence",
            }
        )
    if robot_view > 60:
        recommendations.append(
            {
                "candidate_group": "group2_lane_specific_reductions",
                "candidate_ids": ["F"],
                "reason": "robot-view capture is a material wall-clock bucket",
            }
        )
    return {
        "available": True,
        "elapsed_s": elapsed,
        "between_tool_gap_s": between_gap,
        "robot_view_capture_s": robot_view,
        "tool_handler_s": tool_handler,
        "latency_buckets": buckets,
        "dominant_bucket": _dominant_bucket(buckets),
        "tool_counts": tool_counts,
        "camera_grounded_tool_breakdown": camera_grounded_breakdown,
        "failed_or_noop_tool_count": failed_or_noop_tool_count,
        "recommendations": recommendations,
    }


def _latency_buckets(
    *,
    elapsed_s: float,
    between_tool_gap_s: float,
    robot_view_capture_s: float,
    tool_handler_s: float,
) -> dict[str, dict[str, Any]]:
    accounted = (
        max(0.0, between_tool_gap_s)
        + max(0.0, robot_view_capture_s)
        + max(
            0.0,
            tool_handler_s,
        )
    )
    residual = max(0.0, elapsed_s - accounted)
    return {
        "model_or_sdk_between_tool_gap": _bucket(between_tool_gap_s, elapsed_s, reducible=True),
        "visual_capture": _bucket(robot_view_capture_s, elapsed_s, reducible=True),
        "mcp_backend_tool_handler": _bucket(tool_handler_s, elapsed_s, reducible=False),
        "residual_or_unattributed": _bucket(residual, elapsed_s, reducible=False),
    }


def _bucket(seconds: float, elapsed_s: float, *, reducible: bool) -> dict[str, Any]:
    return {
        "seconds": round(max(0.0, seconds), 3),
        "share": _ratio(max(0.0, seconds), elapsed_s),
        "reducible": reducible,
    }


def _dominant_bucket(buckets: dict[str, dict[str, Any]]) -> str:
    if not buckets:
        return ""
    return max(buckets.items(), key=lambda item: float(item[1].get("seconds") or 0.0))[0]


def _recommendation_summary(rows: list[dict[str, Any]]) -> dict[str, Any]:
    candidate_counts: dict[str, int] = {}
    group_counts: dict[str, int] = {}
    dominant_bucket_counts: dict[str, int] = {}
    row_recommendations: list[dict[str, Any]] = []
    for row in rows:
        if row.get("status") not in {"accepted", "inconclusive"}:
            continue
        report = row.get("reducible_bucket_report")
        if not isinstance(report, dict) or not report.get("available"):
            continue
        dominant = str(report.get("dominant_bucket") or "")
        if dominant:
            dominant_bucket_counts[dominant] = dominant_bucket_counts.get(dominant, 0) + 1
        recommendations = [
            recommendation
            for recommendation in report.get("recommendations") or []
            if isinstance(recommendation, dict)
        ]
        if not recommendations:
            continue
        for recommendation in recommendations:
            group = str(recommendation.get("candidate_group") or "")
            if group:
                group_counts[group] = group_counts.get(group, 0) + 1
            for candidate_id in _str_list(recommendation.get("candidate_ids")):
                candidate_counts[candidate_id] = candidate_counts.get(candidate_id, 0) + 1
        row_recommendations.append(
            {
                "row_id": row.get("row_id"),
                "evidence_lane": row.get("evidence_lane"),
                "dominant_bucket": dominant,
                "candidate_groups": sorted(
                    {
                        str(item.get("candidate_group") or "")
                        for item in recommendations
                        if str(item.get("candidate_group") or "")
                    }
                ),
                "candidate_ids": sorted(
                    {
                        candidate_id
                        for item in recommendations
                        for candidate_id in _str_list(item.get("candidate_ids"))
                    }
                ),
            }
        )
    return {
        "source": "reducible_bucket_report",
        "claim_scope": "no-provider diagnostic recommendation evidence",
        "candidate_counts": dict(sorted(candidate_counts.items())),
        "candidate_group_counts": dict(sorted(group_counts.items())),
        "dominant_bucket_counts": dict(sorted(dominant_bucket_counts.items())),
        "top_candidate_ids": [
            item[0]
            for item in sorted(candidate_counts.items(), key=lambda item: (-item[1], item[0]))
        ],
        "top_candidate_groups": [
            item[0] for item in sorted(group_counts.items(), key=lambda item: (-item[1], item[0]))
        ],
        "row_recommendations": row_recommendations,
    }


def _candidate_coverage(packet: dict[str, Any]) -> dict[str, Any]:
    groups_by_candidate: dict[str, set[str]] = {}
    queue_by_candidate = _candidate_queue_by_id(packet)
    for group in packet.get("candidate_groups") or []:
        if not isinstance(group, dict):
            continue
        group_id = str(group.get("group_id") or "")
        for candidate_id in _str_list(group.get("candidate_ids")):
            groups_by_candidate.setdefault(candidate_id, set())
            if group_id:
                groups_by_candidate[candidate_id].add(group_id)
    for candidate_id in queue_by_candidate:
        groups_by_candidate.setdefault(candidate_id, set())

    rows_by_candidate: dict[str, list[dict[str, Any]]] = {}
    for row in packet.get("rows") or []:
        if not isinstance(row, dict):
            continue
        candidate_ids = set(_str_list(row.get("candidate_ids")))
        candidate_ids.update(_str_list(row.get("dependency_candidate_ids")))
        for candidate_id in candidate_ids:
            rows_by_candidate.setdefault(candidate_id, []).append(row)
            groups_by_candidate.setdefault(candidate_id, set())

    items: list[dict[str, Any]] = []
    state_counts: dict[str, int] = {}
    coverage_state_counts: dict[str, int] = {}
    for candidate_id in sorted(groups_by_candidate):
        rows = rows_by_candidate.get(candidate_id, [])
        statuses = _status_counts(rows)
        state = _candidate_evidence_state(statuses)
        queue = queue_by_candidate.get(candidate_id, {})
        coverage_state = _candidate_coverage_state(state, queue)
        state_counts[state] = state_counts.get(state, 0) + 1
        coverage_state_counts[coverage_state] = coverage_state_counts.get(coverage_state, 0) + 1
        items.append(
            {
                "candidate_id": candidate_id,
                "group_ids": sorted(groups_by_candidate.get(candidate_id) or []),
                "queue": str(queue.get("queue") or ""),
                "row_policy": str(queue.get("row_policy") or ""),
                "row_ids": [str(row.get("row_id") or "") for row in rows],
                "status_counts": statuses,
                "evidence_state": state,
                "coverage_state": coverage_state,
                "next_action": _candidate_next_action(coverage_state, queue=queue),
            }
        )

    return {
        "source": "candidate_groups_and_decision_rows",
        "candidate_count": len(items),
        "state_counts": dict(sorted(state_counts.items())),
        "coverage_state_counts": dict(sorted(coverage_state_counts.items())),
        "covered_candidate_ids": [
            item["candidate_id"] for item in items if item["evidence_state"] != "no_decision_row"
        ],
        "no_decision_row_candidate_ids": [
            item["candidate_id"] for item in items if item["evidence_state"] == "no_decision_row"
        ],
        "unresolved_no_row_candidate_ids": [
            item["candidate_id"]
            for item in items
            if item["evidence_state"] == "no_decision_row"
            and item["coverage_state"] == "no_decision_row"
        ],
        "items": items,
    }


def _candidate_queue(manifest: dict[str, Any]) -> list[dict[str, Any]]:
    rows = manifest.get("candidate_queue")
    if not isinstance(rows, list):
        return []
    candidates: list[dict[str, Any]] = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        candidate_id = str(row.get("candidate_id") or "")
        if not candidate_id:
            continue
        candidates.append(
            {
                "candidate_id": candidate_id,
                "queue": str(row.get("queue") or ""),
                "row_policy": str(row.get("row_policy") or ""),
                "coverage_state_when_no_row": str(row.get("coverage_state_when_no_row") or ""),
                "next_action": str(row.get("next_action") or ""),
            }
        )
    return candidates


def _candidate_queue_by_id(packet: dict[str, Any]) -> dict[str, dict[str, Any]]:
    rows = packet.get("candidate_queue")
    if not isinstance(rows, list):
        return {}
    by_id: dict[str, dict[str, Any]] = {}
    for row in rows:
        if not isinstance(row, dict):
            continue
        candidate_id = str(row.get("candidate_id") or "")
        if candidate_id:
            by_id[candidate_id] = row
    return by_id


def _status_counts(rows: list[dict[str, Any]]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for row in rows:
        status = str(row.get("status") or "unknown")
        counts[status] = counts.get(status, 0) + 1
    return dict(sorted(counts.items()))


def _candidate_evidence_state(status_counts: dict[str, int]) -> str:
    if not status_counts:
        return "no_decision_row"
    accepted = status_counts.get("accepted", 0)
    rejected = status_counts.get("rejected", 0)
    blocked = status_counts.get("blocked", 0)
    inconclusive = status_counts.get("inconclusive", 0)
    unsupported = status_counts.get("unsupported", 0)
    if accepted and not (rejected or blocked or inconclusive or unsupported):
        return "accepted_only"
    if rejected and not (accepted or blocked or inconclusive or unsupported):
        return "rejected_only"
    if blocked and not (accepted or rejected or inconclusive or unsupported):
        return "blocked_only"
    if unsupported and not (accepted or rejected or blocked or inconclusive):
        return "unsupported_only"
    if inconclusive and not (accepted or rejected or blocked or unsupported):
        return "inconclusive_only"
    return "mixed_evidence"


def _candidate_coverage_state(evidence_state: str, queue: dict[str, Any]) -> str:
    if evidence_state != "no_decision_row":
        return evidence_state
    return str(queue.get("coverage_state_when_no_row") or evidence_state)


def _candidate_next_action(state: str, *, queue: dict[str, Any] | None = None) -> str:
    if queue and queue.get("next_action"):
        return str(queue["next_action"])
    return {
        "accepted_only": (
            "maintain accepted evidence; rerun only for repeat, calibration, or broader coverage"
        ),
        "rejected_only": (
            "do not rerun unchanged; require a changed mechanism or behavior-preserving gate"
        ),
        "blocked_only": "retry only after the recorded provider/backend/capability blocker changes",
        "unsupported_only": "do not run until the route is supported",
        "inconclusive_only": "add stronger baseline/candidate evidence before claiming speedup",
        "mixed_evidence": (
            "inspect row variants before choosing the next arm; avoid treating one row as "
            "the whole candidate"
        ),
        "no_decision_row": (
            "no decision-row evidence yet; run only if refreshed Q/Y or plan gates justify it"
        ),
        "accepted_deterministic_no_live_refresh_row": (
            "deterministic proof exists; add live row only if the plan needs provider-backed speed "
            "evidence"
        ),
        "bypassed_no_live_refresh_row": "bypassed by current evidence; revisit only if Q/Y changes",
        "deferred_no_live_refresh_row": "deferred until the named dependency evidence appears",
        "merged_no_live_refresh_row": "covered by another candidate or summary path",
        "conditional_gate_no_live_refresh_row": "run only before promotion or contract change",
        "gate_no_live_refresh_row": (
            "guardrail candidate; maintain the gate rather than a speed row"
        ),
    }.get(state, "inspect candidate state before continuing")


def _privacy_findings(packet: dict[str, Any]) -> list[dict[str, Any]]:
    findings = privacy_findings_for_packet(packet)
    for row in packet["rows"]:
        for key in ("baseline_run_dir", "candidate_run_dir"):
            run_dir = row.get(key)
            if not run_dir:
                continue
            findings.extend(privacy_findings_for_run_dir(Path(str(run_dir)), row_id=row["row_id"]))
    return findings


def _rows(manifest: dict[str, Any]) -> list[dict[str, Any]]:
    rows = manifest.get("rows")
    return [row for row in rows if isinstance(row, dict)] if isinstance(rows, list) else []


def _dry_run_row(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "row_id": str(row.get("row_id") or ""),
        "provider_profile": str(row.get("provider_profile") or ""),
        "model": str(row.get("model") or ""),
        "evidence_lane": str(row.get("evidence_lane") or row.get("lane") or ""),
        "candidate_group": str(row.get("candidate_group") or ""),
        "candidate_ids": _str_list(row.get("candidate_ids")),
        "dependency_candidate_ids": _str_list(row.get("dependency_candidate_ids")),
        "feature_flags": _dict(row.get("feature_flags")),
        "stop_conditions": _str_list(row.get("stop_conditions")),
        "unsupported_reason": str(row.get("unsupported_reason") or ""),
        "provider_calls": bool(row.get("provider_calls")),
        "expected_decision_status": str(row.get("expected_decision_status") or ""),
        "calibration_path": str(row.get("calibration_path") or ""),
    }


def _block(row: dict[str, Any], reason: str) -> None:
    row["status"] = "blocked"
    if reason not in row["reasons"]:
        row["reasons"].append(reason)


def _is_unexpected_failure(row: dict[str, Any]) -> bool:
    status = str(row.get("status") or "")
    if status not in {"rejected", "blocked"}:
        return False
    return status != str(row.get("expected_decision_status") or "")


def _terminal_state(live_timing: dict[str, Any], status: dict[str, Any]) -> str:
    terminal = live_timing.get("agent_sdk_budget_terminal")
    if isinstance(terminal, dict) and terminal.get("reason"):
        return str(terminal["reason"])
    reason = status.get("reason")
    if reason:
        return str(reason)
    return str(status.get("phase") or "unknown")


def _semantic_accepted_count(score: dict[str, Any]) -> int | None:
    rows = score.get("object_results")
    if not isinstance(rows, list):
        return None
    accepted = 0
    for row in rows:
        if not isinstance(row, dict):
            continue
        if row.get("restored") or str(row.get("semantic_acceptability") or "") in {
            "preferred",
            "acceptable",
        }:
            accepted += 1
    return accepted


def _failed_or_noop_tool_count(events: list[dict[str, Any]]) -> int:
    count = 0
    for event in events:
        if event.get("event") != "response":
            continue
        response = event.get("response") if isinstance(event.get("response"), dict) else {}
        ok = response.get("ok")
        error_reason = str(response.get("error_reason") or response.get("failure_reason") or "")
        status = str(response.get("status") or "")
        if ok is False or error_reason or status in {"noop", "failed", "error"}:
            count += 1
    return count


def _tool_counts(events: list[dict[str, Any]]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for event in events:
        if event.get("event") != "response":
            continue
        tool = str(event.get("tool") or "")
        if not tool:
            continue
        counts[tool] = counts.get(tool, 0) + 1
    return dict(sorted(counts.items()))


def _camera_grounded_tool_breakdown(events: list[dict[str, Any]]) -> dict[str, int]:
    composite_requests = 0
    declare_requests = 0
    composite_internal_declares = 0
    standalone_declares = 0
    composite_open = 0
    for event in events:
        event_kind = event.get("event")
        if event_kind not in {"request", "response"}:
            continue
        tool = str(event.get("tool") or "")
        if event_kind == "request" and tool == "observe_camera_grounded_candidates":
            composite_requests += 1
            composite_open += 1
            continue
        if event_kind == "response" and tool == "observe_camera_grounded_candidates":
            composite_open = max(0, composite_open - 1)
            continue
        if event_kind == "request" and tool == "declare_visual_candidates":
            declare_requests += 1
            if composite_open > 0:
                composite_internal_declares += 1
            else:
                standalone_declares += 1
    return {
        "observe_camera_grounded_candidates": composite_requests,
        "declare_visual_candidates_requests": declare_requests,
        "composite_internal_declare_visual_candidates": composite_internal_declares,
        "standalone_declare_visual_candidates": standalone_declares,
    }


def _not_lower(candidate: Any, baseline: Any) -> bool:
    candidate_value = _float_or_none(candidate)
    baseline_value = _float_or_none(baseline)
    if candidate_value is None or baseline_value is None:
        return True
    return candidate_value >= baseline_value


def _not_higher(candidate: Any, baseline: Any) -> bool:
    candidate_value = _float_or_none(candidate)
    baseline_value = _float_or_none(baseline)
    if candidate_value is None or baseline_value is None:
        return True
    return candidate_value <= baseline_value


def _delta(candidate: Any, baseline: Any) -> float | None:
    candidate_value = _float_or_none(candidate)
    baseline_value = _float_or_none(baseline)
    if candidate_value is None or baseline_value is None:
        return None
    return round(candidate_value - baseline_value, 3)


def _dict(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _str_list(value: Any) -> list[str]:
    return [str(item) for item in value if str(item)] if isinstance(value, list) else []


def _float_or_none(value: Any) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _ratio(numerator: float, denominator: float) -> float | None:
    if denominator <= 0:
        return None
    return round(numerator / denominator, 4)


def _int_or_none(value: Any) -> int | None:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


if __name__ == "__main__":
    raise SystemExit(main())
