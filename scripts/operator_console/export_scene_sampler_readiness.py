#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

if __package__ in {None, ""}:
    REPO_ROOT = Path(__file__).resolve().parents[2]
    if str(REPO_ROOT) not in sys.path:
        sys.path.insert(0, str(REPO_ROOT))
else:
    REPO_ROOT = Path(__file__).resolve().parents[2]

from roboclaws.worlds.molmospaces.sampling import (  # noqa: E402
    candidate_profile_report,
    candidate_readiness_report,
    eval_projection_metadata,
    eval_sample_payload,
    eval_sampler_rows,
    eval_suite_payload,
    next_flow_worklist_report,
    readiness_report,
    sampler_manifest,
    scanner_admission_report,
    scanner_execution_plan,
    scene_only_prefilter_report,
    selection_gap_report,
    source_availability_report,
    source_prep_report,
    validate_sampler_manifest,
)

DEFAULT_OUTPUT_DIR = Path("output/scene-sampler-readiness")


@dataclass(frozen=True)
class _ReadinessPayloads:
    manifest: dict[str, Any]
    projection: dict[str, Any]
    readiness: dict[str, Any]
    selection: dict[str, Any]
    candidate_profile: dict[str, Any] | None
    scene_prefilter: dict[str, Any] | None
    availability: dict[str, Any] | None
    candidates: dict[str, Any] | None
    source_prep: dict[str, Any] | None
    scanner_admission: dict[str, Any] | None
    scanner_execution: dict[str, Any] | None
    next_flow_worklist: dict[str, Any] | None


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    try:
        candidate_indices = _candidate_indices(
            candidate_indexes=tuple(args.candidate_indexes),
            candidate_ranges=tuple(args.candidate_ranges),
        )
    except ValueError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    report = export_readiness_artifacts(
        output_dir=args.output_dir,
        candidate_indices=candidate_indices,
        write_manifest=not args.no_manifest,
        write_eval_projection=not args.no_eval_projection,
        write_readiness_report=not args.no_readiness_report,
        write_source_availability=not args.no_source_availability,
        write_candidate_readiness=not args.no_candidate_readiness,
        write_selection_gaps=not args.no_selection_gaps,
        write_candidate_profile=not args.no_candidate_profile,
        write_scene_prefilter=not args.no_scene_prefilter,
        write_source_prep=not args.no_source_prep,
        write_scanner_admission=not args.no_scanner_admission,
        write_scanner_execution_plan=not args.no_scanner_execution_plan,
        write_next_flow_worklist=not args.no_next_flow_worklist,
        write_generated_eval=not args.no_generated_eval,
        required_ui_supported_sources=tuple(args.require_ui_supported_sources),
        required_eval_complete_sources=tuple(args.require_eval_complete_sources),
        required_selection_capacity_sources=tuple(args.require_selection_capacity_sources),
        required_scanner_ready_sources=tuple(args.require_scanner_ready_sources),
    )
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0 if report["status"] == "success" else 2


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Export source-aware MolmoSpaces scene-sampler readiness artifacts "
            "without downloading assets or calling live labelers."
        ),
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--no-manifest", action="store_true")
    parser.add_argument("--no-eval-projection", action="store_true")
    parser.add_argument("--no-readiness-report", action="store_true")
    parser.add_argument("--no-source-availability", action="store_true")
    parser.add_argument("--no-candidate-readiness", action="store_true")
    parser.add_argument("--no-selection-gaps", action="store_true")
    parser.add_argument("--no-candidate-profile", action="store_true")
    parser.add_argument("--no-scene-prefilter", action="store_true")
    parser.add_argument("--no-source-prep", action="store_true")
    parser.add_argument("--no-scanner-admission", action="store_true")
    parser.add_argument("--no-scanner-execution-plan", action="store_true")
    parser.add_argument("--no-next-flow-worklist", action="store_true")
    parser.add_argument("--no-generated-eval", action="store_true")
    parser.add_argument(
        "--candidate-index",
        action="append",
        type=int,
        dest="candidate_indexes",
        default=[],
        metavar="INDEX",
        help=(
            "Candidate scene index to include in no-download availability, candidate, "
            "and selection-gap artifacts. Defaults to 0..9 when no index/range is passed."
        ),
    )
    parser.add_argument(
        "--candidate-range",
        action="append",
        dest="candidate_ranges",
        default=[],
        metavar="START:END",
        help=(
            "Inclusive candidate scene-index range to include, for example 0:19. "
            "May be passed multiple times."
        ),
    )
    parser.add_argument(
        "--require-ui-supported-source",
        action="append",
        dest="require_ui_supported_sources",
        default=[],
        metavar="SCENE_SOURCE",
        help=(
            "Fail unless SCENE_SOURCE has exactly the sampler UI target count ready. "
            "May be passed multiple times."
        ),
    )
    parser.add_argument(
        "--require-eval-complete-source",
        action="append",
        dest="require_eval_complete_sources",
        default=[],
        metavar="SCENE_SOURCE",
        help=(
            "Fail unless SCENE_SOURCE has exactly the sampler eval-stress target count ready. "
            "May be passed multiple times."
        ),
    )
    parser.add_argument(
        "--require-selection-capacity-source",
        action="append",
        dest="require_selection_capacity_sources",
        default=[],
        metavar="SCENE_SOURCE",
        help=(
            "Fail unless SCENE_SOURCE has enough next scan candidates to cover both "
            "current UI and eval-stress gaps. May be passed multiple times."
        ),
    )
    parser.add_argument(
        "--require-scanner-ready-source",
        action="append",
        dest="require_scanner_ready_sources",
        default=[],
        metavar="SCENE_SOURCE",
        help=(
            "Fail unless SCENE_SOURCE has at least one candidate ready for preview plus "
            "map-build product smoke. May be passed multiple times."
        ),
    )
    return parser.parse_args(argv)


def export_readiness_artifacts(
    *,
    output_dir: Path,
    candidate_indices: tuple[int, ...] = tuple(range(10)),
    write_manifest: bool = True,
    write_eval_projection: bool = True,
    write_readiness_report: bool = True,
    write_source_availability: bool = True,
    write_candidate_readiness: bool = True,
    write_selection_gaps: bool = True,
    write_candidate_profile: bool = True,
    write_scene_prefilter: bool = True,
    write_source_prep: bool = True,
    write_scanner_admission: bool = True,
    write_scanner_execution_plan: bool = True,
    write_next_flow_worklist: bool = True,
    write_generated_eval: bool = True,
    required_ui_supported_sources: tuple[str, ...] = (),
    required_eval_complete_sources: tuple[str, ...] = (),
    required_selection_capacity_sources: tuple[str, ...] = (),
    required_scanner_ready_sources: tuple[str, ...] = (),
) -> dict[str, Any]:
    """Write deterministic sampler artifacts for review and later scanner slices."""

    payloads = _build_readiness_payloads(
        output_dir=output_dir,
        candidate_indices=candidate_indices,
        write_source_availability=write_source_availability,
        write_candidate_readiness=write_candidate_readiness,
        write_candidate_profile=write_candidate_profile,
        write_scene_prefilter=write_scene_prefilter,
        write_source_prep=write_source_prep,
        write_scanner_admission=write_scanner_admission,
        write_scanner_execution_plan=write_scanner_execution_plan,
        write_next_flow_worklist=write_next_flow_worklist,
        required_scanner_ready_sources=required_scanner_ready_sources,
    )
    output_dir.mkdir(parents=True, exist_ok=True)
    artifacts = _write_requested_artifacts(
        output_dir=output_dir,
        payloads=payloads,
        write_manifest=write_manifest,
        write_eval_projection=write_eval_projection,
        write_readiness_report=write_readiness_report,
        write_source_availability=write_source_availability,
        write_candidate_readiness=write_candidate_readiness,
        write_selection_gaps=write_selection_gaps,
        write_candidate_profile=write_candidate_profile,
        write_scene_prefilter=write_scene_prefilter,
        write_source_prep=write_source_prep,
        write_scanner_admission=write_scanner_admission,
        write_scanner_execution_plan=write_scanner_execution_plan,
        write_next_flow_worklist=write_next_flow_worklist,
        write_generated_eval=write_generated_eval,
    )
    failures = _threshold_failures(
        readiness=payloads.readiness,
        selection=payloads.selection,
        required_ui_supported_sources=required_ui_supported_sources,
        required_eval_complete_sources=required_eval_complete_sources,
        required_selection_capacity_sources=required_selection_capacity_sources,
        required_scanner_ready_sources=required_scanner_ready_sources,
        scanner_execution=payloads.scanner_execution,
    )
    return {
        "schema": "molmospaces_scene_sampler_readiness_export_v1",
        "status": "failed" if failures else "success",
        "output_dir": str(output_dir),
        "candidate_indices": list(candidate_indices),
        "artifacts": artifacts,
        "summary": _export_summary(payloads),
        "threshold_failures": failures,
    }


def _build_readiness_payloads(
    *,
    output_dir: Path,
    candidate_indices: tuple[int, ...],
    write_source_availability: bool,
    write_candidate_readiness: bool,
    write_candidate_profile: bool,
    write_scene_prefilter: bool,
    write_source_prep: bool,
    write_scanner_admission: bool,
    write_scanner_execution_plan: bool,
    write_next_flow_worklist: bool,
    required_scanner_ready_sources: tuple[str, ...],
) -> _ReadinessPayloads:
    validate_sampler_manifest()
    manifest = sampler_manifest()
    projection = eval_projection_metadata()
    readiness = readiness_report()
    selection = selection_gap_report(candidate_indices=candidate_indices)
    availability = (
        source_availability_report(candidate_indices=candidate_indices)
        if write_source_availability
        else None
    )
    candidates = (
        candidate_readiness_report(candidate_indices=candidate_indices)
        if write_candidate_readiness
        else None
    )
    candidate_profile = (
        candidate_profile_report(candidate_indices=candidate_indices)
        if write_candidate_profile
        else None
    )
    scene_prefilter = (
        scene_only_prefilter_report(candidate_indices=candidate_indices)
        if write_scene_prefilter
        else None
    )
    source_prep = (
        source_prep_report(candidate_indices=candidate_indices) if write_source_prep else None
    )
    scanner_admission = (
        scanner_admission_report(candidate_indices=candidate_indices)
        if write_scanner_admission
        else None
    )
    scanner_execution: dict[str, Any] | None = None
    if write_scanner_execution_plan or required_scanner_ready_sources:
        scanner_execution = scanner_execution_plan(candidate_indices=candidate_indices)
    next_flow_worklist = (
        next_flow_worklist_report(candidate_indices=candidate_indices, output_dir=output_dir)
        if write_next_flow_worklist
        else None
    )
    return _ReadinessPayloads(
        manifest=manifest,
        projection=projection,
        readiness=readiness,
        selection=selection,
        candidate_profile=candidate_profile,
        scene_prefilter=scene_prefilter,
        availability=availability,
        candidates=candidates,
        source_prep=source_prep,
        scanner_admission=scanner_admission,
        scanner_execution=scanner_execution,
        next_flow_worklist=next_flow_worklist,
    )


def _write_requested_artifacts(
    *,
    output_dir: Path,
    payloads: _ReadinessPayloads,
    write_manifest: bool,
    write_eval_projection: bool,
    write_readiness_report: bool,
    write_source_availability: bool,
    write_candidate_readiness: bool,
    write_selection_gaps: bool,
    write_candidate_profile: bool,
    write_scene_prefilter: bool,
    write_source_prep: bool,
    write_scanner_admission: bool,
    write_scanner_execution_plan: bool,
    write_next_flow_worklist: bool,
    write_generated_eval: bool,
) -> dict[str, str | list[str]]:
    artifacts = _write_named_artifacts(
        output_dir,
        (
            ("manifest", write_manifest, "scene_sampler_manifest.json", payloads.manifest),
            (
                "eval_projection",
                write_eval_projection,
                "scene_sampler_eval_projection.json",
                payloads.projection,
            ),
            (
                "readiness_report",
                write_readiness_report,
                "scene_sampler_readiness_report.json",
                payloads.readiness,
            ),
            (
                "source_availability",
                write_source_availability,
                "scene_sampler_source_availability.json",
                payloads.availability,
            ),
            (
                "candidate_readiness",
                write_candidate_readiness,
                "scene_sampler_candidate_readiness.json",
                payloads.candidates,
            ),
            (
                "selection_gaps",
                write_selection_gaps,
                "scene_sampler_selection_gaps.json",
                payloads.selection,
            ),
            (
                "candidate_profile",
                write_candidate_profile,
                "scene_sampler_candidate_profile.json",
                payloads.candidate_profile,
            ),
            (
                "scene_prefilter",
                write_scene_prefilter,
                "scene_sampler_scene_prefilter.json",
                payloads.scene_prefilter,
            ),
            (
                "source_prep",
                write_source_prep,
                "scene_sampler_source_prep.json",
                payloads.source_prep,
            ),
            (
                "scanner_admission",
                write_scanner_admission,
                "scene_sampler_scanner_admission.json",
                payloads.scanner_admission,
            ),
            (
                "scanner_execution_plan",
                write_scanner_execution_plan,
                "scene_sampler_scanner_execution_plan.json",
                payloads.scanner_execution,
            ),
            (
                "next_flow_worklist",
                write_next_flow_worklist,
                "scene_sampler_next_flow_worklist.json",
                payloads.next_flow_worklist,
            ),
        ),
    )
    if write_generated_eval:
        artifacts.update(_write_generated_eval_artifacts(output_dir))
    return artifacts


def _write_named_artifacts(
    output_dir: Path,
    entries: tuple[tuple[str, bool, str, dict[str, Any] | None], ...],
) -> dict[str, str]:
    artifacts: dict[str, str] = {}
    for key, enabled, filename, payload in entries:
        if not enabled:
            continue
        if payload is None:
            raise ValueError(f"enabled artifact {key!r} has no payload")
        path = output_dir / filename
        _write_json(path, payload)
        artifacts[key] = str(path)
    return artifacts


def _write_generated_eval_artifacts(output_dir: Path) -> dict[str, str | list[str]]:
    generated_eval_dir = output_dir / "generated_eval"
    generated_samples_dir = generated_eval_dir / "samples" / "scene_sampler"
    generated_samples_dir.mkdir(parents=True, exist_ok=True)
    generated_suite_path = generated_eval_dir / "scene_sampler_stress.json"
    _write_json(generated_suite_path, eval_suite_payload())
    sample_paths = []
    for row in eval_sampler_rows():
        sample_path = generated_samples_dir / (
            f"{row.scene_source}_{row.scene_index}_map_build.json"
        )
        _write_json(sample_path, eval_sample_payload(row))
        sample_paths.append(str(sample_path))
    return {
        "generated_eval_suite": str(generated_suite_path),
        "generated_eval_samples": sample_paths,
    }


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _export_summary(payloads: _ReadinessPayloads) -> dict[str, Any]:
    return {
        "supported_scene_sources": payloads.manifest.get("supported_scene_sources", []),
        "ui_world_ids": (payloads.manifest.get("projections") or {}).get("ui_world_ids", []),
        "eval_sample_ids": (payloads.manifest.get("projections") or {}).get("eval_sample_ids", []),
        "eval_projection": payloads.projection.get("summary", {}),
        "readiness": payloads.readiness.get("summary", {}),
        "source_availability": (payloads.availability or {}).get("summary", {}),
        "candidate_readiness": (payloads.candidates or {}).get("summary", {}),
        "selection_gaps": (payloads.selection or {}).get("summary", {}),
        "candidate_profile": (payloads.candidate_profile or {}).get("summary", {}),
        "scene_prefilter": (payloads.scene_prefilter or {}).get("summary", {}),
        "source_prep": (payloads.source_prep or {}).get("summary", {}),
        "scanner_admission": (payloads.scanner_admission or {}).get("summary", {}),
        "scanner_execution": (payloads.scanner_execution or {}).get("summary", {}),
        "next_flow_worklist": (payloads.next_flow_worklist or {}).get("summary", {}),
    }


def _candidate_indices(
    *,
    candidate_indexes: tuple[int, ...],
    candidate_ranges: tuple[str, ...],
) -> tuple[int, ...]:
    values: set[int] = set()
    for index in candidate_indexes:
        if index < 0:
            raise ValueError(f"candidate-index must be >= 0, got {index}")
        values.add(index)
    for raw_range in candidate_ranges:
        values.update(_parse_candidate_range(raw_range))
    if not values:
        values.update(range(10))
    return tuple(sorted(values))


def _parse_candidate_range(raw_range: str) -> range:
    try:
        raw_start, raw_end = raw_range.split(":", 1)
        start = int(raw_start)
        end = int(raw_end)
    except ValueError as exc:
        raise ValueError(
            f"candidate-range must be START:END with integer bounds, got {raw_range!r}"
        ) from exc
    if start < 0 or end < 0:
        raise ValueError(f"candidate-range bounds must be >= 0, got {raw_range!r}")
    if end < start:
        raise ValueError(f"candidate-range end must be >= start, got {raw_range!r}")
    return range(start, end + 1)


def _threshold_failures(
    readiness: dict[str, Any],
    selection: dict[str, Any],
    *,
    required_ui_supported_sources: tuple[str, ...],
    required_eval_complete_sources: tuple[str, ...],
    required_selection_capacity_sources: tuple[str, ...],
    required_scanner_ready_sources: tuple[str, ...],
    scanner_execution: dict[str, Any] | None,
) -> list[dict[str, Any]]:
    readiness_sources = _source_payloads(readiness)
    failures: list[dict[str, Any]] = []
    failures.extend(
        _readiness_status_failures(
            readiness_sources,
            required_sources=required_ui_supported_sources,
            threshold="ui_supported",
            status_key="ui_status",
            ready_status="ready",
            reason="ui_not_ready",
            ready_count_key="ui_ready_count",
            target_count_key="ui_target_count",
        )
    )
    failures.extend(
        _readiness_status_failures(
            readiness_sources,
            required_sources=required_eval_complete_sources,
            threshold="eval_complete",
            status_key="eval_status",
            ready_status="complete",
            reason="eval_not_complete",
            ready_count_key="eval_ready_count",
            target_count_key="eval_target_count",
        )
    )
    failures.extend(
        _selection_capacity_failures(
            _source_payloads(selection),
            required_sources=required_selection_capacity_sources,
        )
    )
    failures.extend(
        _scanner_ready_failures(
            _source_payloads(scanner_execution),
            required_sources=required_scanner_ready_sources,
        )
    )
    return failures


def _source_payloads(payload: dict[str, Any] | None) -> dict[str, Any]:
    if not isinstance(payload, dict):
        return {}
    sources = payload.get("sources")
    return sources if isinstance(sources, dict) else {}


def _unknown_source_failure(source: str, threshold: str) -> dict[str, str]:
    return {
        "scene_source": source,
        "threshold": threshold,
        "reason": "unknown_scene_source",
    }


def _readiness_status_failures(
    sources: dict[str, Any],
    *,
    required_sources: tuple[str, ...],
    threshold: str,
    status_key: str,
    ready_status: str,
    reason: str,
    ready_count_key: str,
    target_count_key: str,
) -> list[dict[str, Any]]:
    failures: list[dict[str, Any]] = []
    for source in required_sources:
        payload = sources.get(source)
        if not isinstance(payload, dict):
            failures.append(_unknown_source_failure(source, threshold))
            continue
        if payload.get(status_key) == ready_status:
            continue
        failures.append(
            {
                "scene_source": source,
                "threshold": threshold,
                "reason": reason,
                "ready_count": payload.get(ready_count_key),
                "target_count": payload.get(target_count_key),
            }
        )
    return failures


def _selection_capacity_failures(
    sources: dict[str, Any],
    *,
    required_sources: tuple[str, ...],
) -> list[dict[str, Any]]:
    failures: list[dict[str, Any]] = []
    for source in required_sources:
        payload = sources.get(source)
        if not isinstance(payload, dict):
            failures.append(_unknown_source_failure(source, "selection_capacity"))
            continue
        ui_needed = int(payload.get("ui_needed_count") or 0)
        eval_needed = int(payload.get("eval_needed_count") or 0)
        ui_available = len(payload.get("next_ui_scan_world_ids") or [])
        eval_available = len(payload.get("next_eval_scan_world_ids") or [])
        if ui_available >= ui_needed and eval_available >= eval_needed:
            continue
        failures.append(
            {
                "scene_source": source,
                "threshold": "selection_capacity",
                "reason": "insufficient_candidate_scan_capacity",
                "ui_needed_count": ui_needed,
                "ui_available_count": ui_available,
                "eval_needed_count": eval_needed,
                "eval_available_count": eval_available,
            }
        )
    return failures


def _scanner_ready_failures(
    sources: dict[str, Any],
    *,
    required_sources: tuple[str, ...],
) -> list[dict[str, Any]]:
    failures: list[dict[str, Any]] = []
    for source in required_sources:
        payload = sources.get(source)
        if not isinstance(payload, dict):
            failures.append(_unknown_source_failure(source, "scanner_ready"))
            continue
        ready_count = int(payload.get("ready_for_product_smoke_count") or 0)
        if ready_count >= 1:
            continue
        failures.append(
            {
                "scene_source": source,
                "threshold": "scanner_ready",
                "reason": "no_ready_product_smoke_candidates",
                "ready_for_product_smoke_count": ready_count,
                "candidate_count": int(payload.get("candidate_count") or 0),
                "blocked_count": int(payload.get("blocked_count") or 0),
                "prep_status": payload.get("prep_status", ""),
            }
        )
    return failures


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
