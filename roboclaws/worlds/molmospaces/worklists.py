"""MolmoSpaces preparation, scanner, and next-flow worklists."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from roboclaws.worlds.molmospaces.catalog_projection import eval_projection_metadata
from roboclaws.worlds.molmospaces.contracts import SAMPLER_GENERATOR_VERSION
from roboclaws.worlds.molmospaces.prefilter import (
    scene_prefilter_expensive_proof_candidates as _scene_prefilter_expensive_proof_candidates,
)
from roboclaws.worlds.molmospaces.preparation import source_prep_report as _source_prep_report
from roboclaws.worlds.molmospaces.profile import (
    source_gate_mismatch_profile_rows as _source_gate_mismatch_profile_rows,
)
from roboclaws.worlds.molmospaces.readiness import (
    candidate_profile_report,
    candidate_readiness_report,
    readiness_report,
    scene_only_prefilter_report,
    selection_gap_report,
    source_availability_report,
)
from roboclaws.worlds.molmospaces.sampling import (
    EVAL_TARGET_PER_SCENE_SOURCE,
    SUPPORTED_SCENE_SOURCES,
    UI_TARGET_PER_SCENE_SOURCE,
    _family_split,
    _sampler_selection_policy,
    _scanner_admission_row,
    _scanner_execution_candidate_indices,
    _scanner_required_gates,
)
from roboclaws.worlds.molmospaces.scanner import (
    next_flow_artifact_paths,
    next_flow_blocked_reason_samples,
    next_flow_missing_gate_counts,
    next_flow_next_action,
    next_flow_recommended_commands,
    next_flow_scan_world_ids,
    next_flow_status,
    next_flow_summary,
    scanner_admission_summary,
    scanner_execution_candidate,
    scanner_execution_summary,
    scanner_gate_mismatch_count,
)


def source_prep_report(
    *,
    candidate_indices: tuple[int, ...] = tuple(range(10)),
) -> dict[str, Any]:
    """Return a no-download source-preparation plan for scanner admission work."""

    availability = source_availability_report(candidate_indices=candidate_indices)
    selection = selection_gap_report(candidate_indices=candidate_indices)
    candidate_profile = candidate_profile_report(candidate_indices=candidate_indices)
    scene_prefilter = scene_only_prefilter_report(candidate_indices=candidate_indices)
    return _source_prep_report(
        availability=availability,
        selection=selection,
        candidate_profile=candidate_profile,
        scene_prefilter=scene_prefilter,
        supported_sources=SUPPORTED_SCENE_SOURCES,
        candidate_indices=candidate_indices,
        generator_version=SAMPLER_GENERATOR_VERSION,
        selection_policy=_sampler_selection_policy(),
        family_split=_family_split,
        gate_mismatch_profile_rows=_source_gate_mismatch_profile_rows,
        expensive_proof_candidates=_scene_prefilter_expensive_proof_candidates,
    )


def scanner_execution_plan(
    *,
    candidate_indices: tuple[int, ...] = tuple(range(10)),
) -> dict[str, Any]:
    """Return a no-download executable plan for the next scanner/product-smoke step."""

    source_prep = source_prep_report(candidate_indices=candidate_indices)
    scanner_candidate_indices = _scanner_execution_candidate_indices(
        candidate_indices=candidate_indices,
        source_prep=source_prep,
    )
    scanner_admission = scanner_admission_report(candidate_indices=scanner_candidate_indices)
    sources: dict[str, dict[str, Any]] = {}
    for source in SUPPORTED_SCENE_SOURCES:
        prep_source = source_prep["sources"][source]
        admission_by_world_id = {
            row.get("world_id"): row
            for row in scanner_admission["sources"][source].get("admission_rows") or []
            if isinstance(row, dict)
        }
        candidates = []
        for install_candidate in prep_source.get("install_candidates") or []:
            if not isinstance(install_candidate, dict):
                continue
            world_id = str(install_candidate.get("world_id") or "")
            admission = admission_by_world_id.get(world_id) or {}
            candidates.append(
                scanner_execution_candidate(
                    install_candidate=install_candidate,
                    admission=admission,
                )
            )
        gate_mismatch_count = int(prep_source.get("gate_mismatch_candidate_count") or 0)
        sources[source] = {
            "scene_source": source,
            "prep_status": prep_source.get("prep_status", ""),
            "download_policy": "manual_operator_only",
            "candidate_count": len(candidates),
            "ready_for_product_smoke_count": sum(
                1 for item in candidates if item["scanner_status"] == "ready_for_product_smoke"
            ),
            "blocked_count": sum(
                1
                for item in candidates
                if item["scanner_status"].startswith("blocked_")
                or item["scanner_status"] == "rejected_by_admission"
            ),
            "gate_mismatch_count": gate_mismatch_count
            + scanner_gate_mismatch_count({"candidates": candidates}),
            "candidates": candidates,
        }
    return {
        "schema": "molmospaces_scene_sampler_scanner_execution_plan_v1",
        "generator_version": SAMPLER_GENERATOR_VERSION,
        "probe_mode": "no_download_no_backend_no_vlm",
        "download_policy": "manual_operator_only",
        "selection_policy": _sampler_selection_policy(),
        "candidate_indices": list(scanner_candidate_indices),
        "summary": scanner_execution_summary(sources),
        "sources": sources,
    }


def next_flow_worklist_report(
    *,
    candidate_indices: tuple[int, ...] = tuple(range(10)),
    output_dir: Path | None = None,
) -> dict[str, Any]:
    """Return one next-Flow worklist across sampler selection, prep, and scanner gates."""

    artifact_paths = next_flow_artifact_paths(output_dir=output_dir)
    projection = eval_projection_metadata()
    readiness = readiness_report()
    selection = selection_gap_report(candidate_indices=candidate_indices)
    candidate_profile = candidate_profile_report(candidate_indices=candidate_indices)
    source_prep = source_prep_report(candidate_indices=candidate_indices)
    scanner_admission = scanner_admission_report(candidate_indices=candidate_indices)
    scanner_execution = scanner_execution_plan(candidate_indices=candidate_indices)
    sources: dict[str, dict[str, Any]] = {}
    for source in SUPPORTED_SCENE_SOURCES:
        source_projection = projection["scene_sources"][source]
        source_readiness = readiness["sources"][source]
        source_selection = selection["sources"][source]
        source_candidate_profile = candidate_profile["sources"][source]
        source_prep_payload = source_prep["sources"][source]
        source_admission = scanner_admission["sources"][source]
        source_execution = scanner_execution["sources"][source]
        scanner_ready_world_ids = [
            item.get("world_id")
            for item in source_execution.get("candidates") or []
            if isinstance(item, dict)
            and item.get("scanner_status") == "ready_for_product_smoke"
            and item.get("world_id")
        ]
        scanner_gate_mismatch_count = int(source_execution.get("gate_mismatch_count") or 0)
        missing_gate_counts = next_flow_missing_gate_counts(source_admission)
        next_action = next_flow_next_action(
            readiness_source=source_readiness,
            selection_source=source_selection,
            candidate_profile_source=source_candidate_profile,
            prep_source=source_prep_payload,
            scanner_source=source_execution,
        )
        sources[source] = {
            "scene_source": source,
            "scene_family": source_prep_payload.get("scene_family", ""),
            "scene_split": source_prep_payload.get("scene_split", ""),
            "flow_status": next_flow_status(
                readiness_source=source_readiness,
                prep_source=source_prep_payload,
                scanner_source=source_execution,
            ),
            "next_action": next_action,
            "ui_target_count": UI_TARGET_PER_SCENE_SOURCE,
            "ui_ready_count": int(source_readiness.get("ui_ready_count") or 0),
            "ui_needed_count": int(source_selection.get("ui_needed_count") or 0),
            "ui_status": source_readiness.get("ui_status", ""),
            "ui_world_ids": source_readiness.get("ui_world_ids") or [],
            "eval_target_count": EVAL_TARGET_PER_SCENE_SOURCE,
            "eval_ready_count": int(source_readiness.get("eval_ready_count") or 0),
            "eval_needed_count": int(source_selection.get("eval_needed_count") or 0),
            "eval_status": source_readiness.get("eval_status", ""),
            "eval_support_status": source_projection.get("support_status", ""),
            "eval_sample_ids": source_readiness.get("eval_sample_ids") or [],
            "selection_capacity_status": source_selection.get("selection_capacity_status", ""),
            "candidate_profile_status": source_candidate_profile.get("profile_status", ""),
            "candidate_profile_next_action": source_candidate_profile.get("next_action", ""),
            "metadata_worklist_world_ids": source_candidate_profile.get(
                "metadata_worklist_world_ids", []
            ),
            "metadata_worklist_candidate_count": int(
                source_candidate_profile.get("metadata_worklist_candidate_count") or 0
            ),
            "scene_prefilter_status": source_prep_payload.get("scene_prefilter_status", ""),
            "scene_prefilter_next_action": source_prep_payload.get(
                "scene_prefilter_next_action", ""
            ),
            "scene_prefilter_candidate_count": int(
                source_prep_payload.get("scene_prefilter_candidate_count") or 0
            ),
            "scene_prefilter_high_confidence_candidate_count": int(
                source_prep_payload.get("scene_prefilter_high_confidence_candidate_count") or 0
            ),
            "scene_prefilter_expensive_proof_candidate_count": int(
                source_prep_payload.get("scene_prefilter_expensive_proof_candidate_count") or 0
            ),
            "scene_prefilter_expensive_proof_world_ids": source_prep_payload.get(
                "scene_prefilter_expensive_proof_world_ids", []
            ),
            "source_availability_status": source_selection.get("source_availability_status", ""),
            "prep_status": source_prep_payload.get("prep_status", ""),
            "scanner_candidate_count": int(source_execution.get("candidate_count") or 0),
            "scanner_ready_candidate_count": int(
                source_execution.get("ready_for_product_smoke_count") or 0
            ),
            "scanner_gate_mismatch_count": scanner_gate_mismatch_count,
            "scanner_blocked_candidate_count": int(source_execution.get("blocked_count") or 0),
            "scanner_ready_world_ids": scanner_ready_world_ids,
            "next_scan_world_ids": next_flow_scan_world_ids(source_selection),
            "missing_resource_count": int(source_prep_payload.get("missing_resource_count") or 0),
            "missing_resource_summary": source_prep_payload.get("missing_resource_summary") or {},
            "missing_gate_counts": missing_gate_counts,
            "blocked_reason_samples": next_flow_blocked_reason_samples(
                projection_source=source_projection,
                prep_source=source_prep_payload,
                scanner_source=source_execution,
            ),
            "operator_command_names": [
                command.get("name")
                for command in source_prep_payload.get("operator_commands") or []
                if isinstance(command, dict) and command.get("name")
            ],
            "recommended_candidate_range": source_prep_payload.get(
                "recommended_candidate_range", ""
            ),
            "recommended_commands": next_flow_recommended_commands(
                source=source,
                next_action=next_action,
                recommended_candidate_range=str(
                    source_prep_payload.get("recommended_candidate_range") or ""
                ),
                artifact_paths=artifact_paths,
            ),
        }
    summary = next_flow_summary(sources)
    return {
        "schema": "molmospaces_scene_sampler_next_flow_worklist_v1",
        "generator_version": SAMPLER_GENERATOR_VERSION,
        "probe_mode": "no_download_no_backend_no_vlm",
        "download_policy": "manual_operator_only",
        "selection_policy": _sampler_selection_policy(),
        "candidate_indices": list(candidate_indices),
        "artifact_paths": artifact_paths,
        "worklist": summary["worklist"],
        "summary": summary,
        "sources": sources,
    }


def scanner_admission_report(
    *,
    candidate_indices: tuple[int, ...] = tuple(range(10)),
) -> dict[str, Any]:
    """Return no-download scanner admission rows for candidate readiness work."""

    candidates = candidate_readiness_report(candidate_indices=candidate_indices)
    selection = selection_gap_report(candidate_indices=candidate_indices)
    sources: dict[str, dict[str, Any]] = {}
    for source in SUPPORTED_SCENE_SOURCES:
        source_candidates = candidates["sources"][source]
        source_selection = selection["sources"][source]
        admission_rows = [
            _scanner_admission_row(candidate)
            for candidate in source_candidates.get("candidates") or []
        ]
        sources[source] = {
            "scene_source": source,
            "ui_target_count": UI_TARGET_PER_SCENE_SOURCE,
            "eval_target_count": EVAL_TARGET_PER_SCENE_SOURCE,
            "ready_ui_count": int(source_candidates.get("ui_ready_count") or 0),
            "ready_eval_count": int(source_candidates.get("eval_ready_count") or 0),
            "needed_ui_count": int(source_selection.get("ui_needed_count") or 0),
            "needed_eval_count": int(source_selection.get("eval_needed_count") or 0),
            "next_scan_world_ids": [
                item.get("world_id") for item in source_selection.get("next_scan_candidates") or []
            ],
            "admission_rows": admission_rows,
            "summary": {
                "admitted_count": sum(
                    1 for item in admission_rows if item["admission_status"] == "admitted"
                ),
                "rejected_count": sum(
                    1 for item in admission_rows if item["admission_status"] == "rejected"
                ),
                "blocked_count": sum(
                    1 for item in admission_rows if item["admission_status"] == "blocked"
                ),
            },
        }
    return {
        "schema": "molmospaces_scene_sampler_scanner_admission_v1",
        "generator_version": SAMPLER_GENERATOR_VERSION,
        "probe_mode": "no_download_no_backend_no_vlm",
        "selection_policy": _sampler_selection_policy(),
        "candidate_indices": list(candidate_indices),
        "required_gates": list(_scanner_required_gates()),
        "summary": scanner_admission_summary(sources),
        "sources": sources,
    }
