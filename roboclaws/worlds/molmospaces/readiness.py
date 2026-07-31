"""MolmoSpaces readiness, profile, prefilter, and selection policy."""

from __future__ import annotations

import platform
import sys
from typing import Any

from roboclaws.worlds.molmospaces.contracts import (
    READINESS_BLOCKED,
    READINESS_READY,
    READINESS_REJECTED,
    SAMPLER_GENERATOR_VERSION,
)
from roboclaws.worlds.molmospaces.prefilter import (
    scene_only_prefilter_report as _scene_only_prefilter_report,
)
from roboclaws.worlds.molmospaces.preparation_io import (
    molmospaces_get_scenes_args as _molmospaces_get_scenes_args,
)
from roboclaws.worlds.molmospaces.preparation_io import (
    molmospaces_module_status as _molmospaces_module_status,
)
from roboclaws.worlds.molmospaces.preparation_io import (
    molmospaces_scene_index_map as _molmospaces_scene_index_map,
)
from roboclaws.worlds.molmospaces.preparation_io import (
    molmospaces_scene_root_status as _molmospaces_scene_root_status,
)
from roboclaws.worlds.molmospaces.preparation_io import (
    source_availability_blocked_reason as _source_availability_blocked_reason,
)
from roboclaws.worlds.molmospaces.preparation_io import (
    source_availability_summary as _source_availability_summary,
)
from roboclaws.worlds.molmospaces.profile import (
    candidate_profile_expanded_indices as _candidate_profile_expanded_indices,
)
from roboclaws.worlds.molmospaces.profile import (
    candidate_profile_report as _candidate_profile_report,
)
from roboclaws.worlds.molmospaces.sampling import (
    EVAL_TARGET_PER_SCENE_SOURCE,
    PRIMARY_MOLMOSPACES_BACKEND,
    SUPPORTED_SCENE_SOURCES,
    UI_TARGET_PER_SCENE_SOURCE,
    _assign_dynamic_candidate_lanes,
    _blocked_candidate_packet,
    _candidate_packet_from_sampler_row,
    _family_split,
    _rank_selection_candidates,
    _sampler_selection_policy,
    eval_sample_id,
    sampler_rows,
)


def readiness_report() -> dict[str, Any]:
    """Return per-source UI/eval readiness counts for scanner artifacts."""

    rows = sampler_rows()
    by_source: dict[str, dict[str, Any]] = {}
    for source in SUPPORTED_SCENE_SOURCES:
        scene_family, scene_split = _family_split(source)
        source_rows = [row for row in rows if row.scene_source == source]
        ui_rows = [row for row in source_rows if row.ui_ready]
        eval_rows = [row for row in source_rows if row.eval_ready]
        blocked_rows = [row for row in source_rows if row.blocked_reason]
        ready_rows = [row for row in source_rows if row.readiness_status == READINESS_READY]
        by_source[source] = {
            "scene_family": scene_family,
            "scene_split": scene_split,
            "ui_target_count": UI_TARGET_PER_SCENE_SOURCE,
            "ui_ready_count": len(ui_rows),
            "ui_status": ("ready" if len(ui_rows) == UI_TARGET_PER_SCENE_SOURCE else "not_visible"),
            "ui_world_ids": [row.world_id for row in ui_rows],
            "eval_target_count": EVAL_TARGET_PER_SCENE_SOURCE,
            "eval_ready_count": len(eval_rows),
            "eval_status": (
                "complete"
                if len(eval_rows) == EVAL_TARGET_PER_SCENE_SOURCE
                else "partial_or_blocked"
            ),
            "eval_sample_ids": [eval_sample_id(row) for row in eval_rows],
            "ready_rows": [row.to_dict() for row in ready_rows],
            "blocked_rows": [row.to_dict() for row in blocked_rows],
        }
    return {
        "schema": "molmospaces_scene_sampler_readiness_report_v1",
        "generator_version": SAMPLER_GENERATOR_VERSION,
        "primary_backend": PRIMARY_MOLMOSPACES_BACKEND,
        "selection_policy": _sampler_selection_policy(),
        "sources": by_source,
        "summary": {
            "source_count": len(SUPPORTED_SCENE_SOURCES),
            "ui_supported_source_count": sum(
                1 for source in SUPPORTED_SCENE_SOURCES if by_source[source]["ui_status"] == "ready"
            ),
            "eval_complete_source_count": sum(
                1
                for source in SUPPORTED_SCENE_SOURCES
                if by_source[source]["eval_status"] == "complete"
            ),
            "blocked_or_partial_source_count": sum(
                1
                for source in SUPPORTED_SCENE_SOURCES
                if by_source[source]["eval_status"] != "complete"
            ),
        },
    }


def source_availability_report(
    *,
    candidate_indices: tuple[int, ...] = tuple(range(10)),
) -> dict[str, Any]:
    """Return no-download source/asset visibility evidence for scanner readiness."""

    module_available, module_reason, module_stdout = _molmospaces_module_status()
    root, root_reason, root_stdout = _molmospaces_scene_root_status(
        module_available=module_available
    )
    sources: dict[str, dict[str, Any]] = {}
    for source in SUPPORTED_SCENE_SOURCES:
        dataset_name, split = _molmospaces_get_scenes_args(source)
        scene_index_map = _molmospaces_scene_index_map(
            source=source,
            dataset_name=dataset_name,
            split=split,
            candidate_indices=candidate_indices,
            module_available=module_available,
        )
        scene_refs_by_index = {
            item["scene_index"]: item for item in scene_index_map["candidate_scene_refs"]
        }
        source_dir = root / source if root is not None else None
        source_exists = bool(source_dir and source_dir.is_dir())
        candidate_files = []
        missing_files = []
        invalid_candidate_indices = []
        for index in candidate_indices:
            scene_ref = scene_refs_by_index.get(index)
            if scene_ref is not None:
                row = {
                    "scene_source": source,
                    "scene_index": index,
                    "path": scene_ref.get("primary_path", ""),
                    "exists": bool(scene_ref.get("all_paths_exist")),
                    "status": scene_ref.get("status", ""),
                    "source": "molmospaces_get_scenes",
                    "raw_ref_type": scene_ref.get("raw_ref_type", ""),
                    "paths": scene_ref.get("paths", []),
                    "missing_paths": scene_ref.get("missing_paths", []),
                }
                candidate_files.append(row)
                if scene_ref.get("status") == "missing_from_index_map":
                    invalid_candidate_indices.append(index)
                elif not row["exists"]:
                    missing_files.append(index)
                continue
            candidate_path = source_dir / f"val_{index}.xml" if source_dir else None
            row = {
                "scene_source": source,
                "scene_index": index,
                "path": str(candidate_path) if candidate_path else "",
                "exists": bool(candidate_path and candidate_path.is_file()),
                "status": "fallback_path_checked",
                "source": "legacy_val_xml_path",
            }
            candidate_files.append(row)
            if not row["exists"]:
                missing_files.append(index)
        status = (
            "available"
            if (
                source_exists
                and scene_index_map["status"] == "available"
                and not missing_files
                and not invalid_candidate_indices
            )
            else "blocked"
        )
        sources[source] = {
            "scene_source": source,
            "status": status,
            "module_available": module_available,
            "scene_root": str(root) if root is not None else "",
            "scene_root_available": bool(root and root.is_dir()),
            "molmospaces_dataset_name": dataset_name,
            "molmospaces_split": split,
            "molmospaces_scene_version": scene_index_map["version"],
            "scene_index_map_status": scene_index_map["status"],
            "scene_index_map_reason": scene_index_map["reason"],
            "scene_index_map_stdout": scene_index_map["stdout"],
            "source_dir": str(source_dir) if source_dir is not None else "",
            "source_dir_available": source_exists,
            "candidate_indices": list(candidate_indices),
            "candidate_files": candidate_files,
            "missing_candidate_indices": missing_files,
            "invalid_candidate_indices": invalid_candidate_indices,
            "blocked_reason": _source_availability_blocked_reason(
                module_available=module_available,
                module_reason=module_reason,
                root=root,
                root_reason=root_reason,
                source=source,
                source_exists=source_exists,
                missing_files=missing_files,
                invalid_candidate_indices=invalid_candidate_indices,
                scene_index_map=scene_index_map,
            ),
            "failure_class": "" if status == "available" else "environment_blocked",
        }
    return {
        "schema": "molmospaces_scene_source_availability_report_v1",
        "generator_version": SAMPLER_GENERATOR_VERSION,
        "probe_mode": "no_download_no_vlm",
        "python_executable": sys.executable,
        "python_version": platform.python_version(),
        "candidate_indices": list(candidate_indices),
        "molmospaces_module_available": module_available,
        "molmospaces_module_reason": module_reason,
        "molmospaces_module_stdout": module_stdout,
        "scene_root": str(root) if root is not None else "",
        "scene_root_reason": root_reason,
        "scene_root_stdout": root_stdout,
        "summary": _source_availability_summary(sources),
        "sources": sources,
    }


def candidate_readiness_report(
    *,
    candidate_indices: tuple[int, ...] = tuple(range(10)),
) -> dict[str, Any]:
    """Return no-download candidate packets for the next scanner/admission step."""

    availability = source_availability_report(candidate_indices=candidate_indices)
    rows_by_source_index = {
        (row.scene_source, row.scene_index): row
        for row in sampler_rows()
        if row.scene_index is not None
    }
    sources: dict[str, dict[str, Any]] = {}
    for source in SUPPORTED_SCENE_SOURCES:
        source_availability = availability["sources"][source]
        candidates = []
        source_candidate_indices = sorted(
            {
                *candidate_indices,
                *(
                    int(row.scene_index)
                    for row in sampler_rows()
                    if row.scene_source == source and row.scene_index is not None
                ),
            }
        )
        for index in source_candidate_indices:
            row = rows_by_source_index.get((source, index))
            if row is not None:
                candidates.append(_candidate_packet_from_sampler_row(row))
                continue
            candidates.append(
                _blocked_candidate_packet(
                    source=source,
                    scene_index=index,
                    source_availability=source_availability,
                )
            )
        candidates = _assign_dynamic_candidate_lanes(
            source=source,
            candidates=candidates,
        )
        ui_ready_count = sum(1 for item in candidates if item["ui_ready"])
        eval_ready_count = sum(1 for item in candidates if item["eval_ready"])
        sources[source] = {
            "scene_source": source,
            "ui_target_count": UI_TARGET_PER_SCENE_SOURCE,
            "ui_ready_count": ui_ready_count,
            "ui_status": "ready" if ui_ready_count == UI_TARGET_PER_SCENE_SOURCE else "not_visible",
            "eval_target_count": EVAL_TARGET_PER_SCENE_SOURCE,
            "eval_ready_count": eval_ready_count,
            "eval_status": (
                "complete"
                if eval_ready_count == EVAL_TARGET_PER_SCENE_SOURCE
                else "partial_or_blocked"
            ),
            "candidate_count": len(candidates),
            "ready_candidate_count": sum(
                1 for item in candidates if item["readiness_status"] == READINESS_READY
            ),
            "blocked_candidate_count": sum(
                1 for item in candidates if item["readiness_status"] == READINESS_BLOCKED
            ),
            "rejected_candidate_count": sum(
                1 for item in candidates if item["readiness_status"] == READINESS_REJECTED
            ),
            "source_availability": source_availability,
            "candidates": candidates,
        }
    return {
        "schema": "molmospaces_scene_sampler_candidate_readiness_v1",
        "generator_version": SAMPLER_GENERATOR_VERSION,
        "probe_mode": "no_download_no_vlm",
        "selection_policy": _sampler_selection_policy(),
        "candidate_indices": list(candidate_indices),
        "summary": _candidate_readiness_summary(sources),
        "sources": sources,
    }


def selection_gap_report(
    *,
    candidate_indices: tuple[int, ...] = tuple(range(10)),
) -> dict[str, Any]:
    """Return deterministic scanner worklist gaps toward UI/eval source targets."""

    candidates = candidate_readiness_report(candidate_indices=candidate_indices)
    sources: dict[str, dict[str, Any]] = {}
    for source in SUPPORTED_SCENE_SOURCES:
        source_payload = candidates["sources"][source]
        source_candidates = source_payload["candidates"]
        ui_ready_count = int(source_payload["ui_ready_count"])
        eval_ready_count = int(source_payload["eval_ready_count"])
        ui_needed = max(0, UI_TARGET_PER_SCENE_SOURCE - ui_ready_count)
        eval_needed = max(0, EVAL_TARGET_PER_SCENE_SOURCE - eval_ready_count)
        scanner_candidates = _rank_selection_candidates(
            source=source,
            lane="scanner",
            candidates=[
                item
                for item in source_candidates
                if (
                    item["readiness_status"] == READINESS_BLOCKED
                    and not item["eval_ready"]
                    and (item.get("candidate_file") or {}).get("status") != "missing_from_index_map"
                )
            ],
        )
        rejected_candidate_indices = [
            item["scene_index"]
            for item in source_candidates
            if item["readiness_status"] == READINESS_REJECTED
        ]
        if (
            eval_ready_count == 0
            and len(rejected_candidate_indices) >= EVAL_TARGET_PER_SCENE_SOURCE
        ):
            scanner_candidates = []
        ui_scan_candidates = scanner_candidates[:ui_needed]
        eval_scan_candidates = scanner_candidates[:eval_needed]
        source_availability_status = (source_payload.get("source_availability") or {}).get("status")
        capacity_status = _selection_capacity_status(
            ui_needed=ui_needed,
            ui_available=len(ui_scan_candidates),
            eval_needed=eval_needed,
            eval_available=len(eval_scan_candidates),
            rejected_count=len(rejected_candidate_indices),
        )
        sources[source] = {
            "scene_source": source,
            "ui_target_count": UI_TARGET_PER_SCENE_SOURCE,
            "ui_ready_count": ui_ready_count,
            "ui_needed_count": ui_needed,
            "ui_scan_candidate_count": len(ui_scan_candidates),
            "eval_target_count": EVAL_TARGET_PER_SCENE_SOURCE,
            "eval_ready_count": eval_ready_count,
            "eval_needed_count": eval_needed,
            "eval_scan_candidate_count": len(eval_scan_candidates),
            "status": "complete" if ui_needed == 0 and eval_needed == 0 else "incomplete",
            "source_availability_status": source_availability_status,
            "selection_capacity_status": capacity_status,
            "next_action": _selection_next_action(
                capacity_status=capacity_status,
                source_availability_status=source_availability_status,
            ),
            "next_ui_scan_world_ids": [item["world_id"] for item in ui_scan_candidates],
            "next_eval_scan_world_ids": [item["world_id"] for item in eval_scan_candidates],
            "next_scan_candidates": [
                _selection_candidate_summary(item)
                for item in _unique_candidates([*ui_scan_candidates, *eval_scan_candidates])
            ],
            "rejected_candidate_indices": rejected_candidate_indices,
        }
    return {
        "schema": "molmospaces_scene_sampler_selection_gaps_v1",
        "generator_version": SAMPLER_GENERATOR_VERSION,
        "probe_mode": "no_download_no_vlm",
        "selection_policy": _sampler_selection_policy(),
        "candidate_indices": list(candidate_indices),
        "summary": _selection_gap_summary(sources),
        "sources": sources,
    }


def candidate_profile_report(
    *,
    candidate_indices: tuple[int, ...] = tuple(range(10)),
) -> dict[str, Any]:
    """Return a metadata-first source-scoped candidate profile.

    This artifact is deliberately weaker than scanner admission: it suggests
    small source-specific worklists for human/metadata review, but it does not
    make any candidate UI- or eval-ready.
    """

    selection = selection_gap_report(candidate_indices=candidate_indices)
    expanded_candidate_indices = _candidate_profile_expanded_indices(
        selection=selection,
        supported_sources=SUPPORTED_SCENE_SOURCES,
        candidate_indices=candidate_indices,
        module_status=_molmospaces_module_status,
        get_scenes_args=_molmospaces_get_scenes_args,
        scene_index_map=_molmospaces_scene_index_map,
    )
    candidates = candidate_readiness_report(candidate_indices=expanded_candidate_indices)
    return _candidate_profile_report(
        selection=selection,
        candidates=candidates,
        supported_sources=SUPPORTED_SCENE_SOURCES,
        candidate_indices=candidate_indices,
        selection_policy=_sampler_selection_policy(),
        module_status=_molmospaces_module_status,
        get_scenes_args=_molmospaces_get_scenes_args,
        scene_index_map=_molmospaces_scene_index_map,
    )


def scene_only_prefilter_report(
    *,
    candidate_indices: tuple[int, ...] = tuple(range(10)),
) -> dict[str, Any]:
    """Return no-download scene-only ranking before expensive source prep.

    The prefilter never admits a scene. It only narrows metadata worklists to a
    capped subset that is worth object/grasp installation plus scanner proof.
    """

    candidate_profile = candidate_profile_report(candidate_indices=candidate_indices)
    return _scene_only_prefilter_report(
        candidate_profile=candidate_profile,
        supported_sources=SUPPORTED_SCENE_SOURCES,
        candidate_indices=candidate_indices,
        selection_policy=_sampler_selection_policy(),
    )


def _selection_candidate_summary(candidate: dict[str, Any]) -> dict[str, Any]:
    return {
        "scene_source": candidate["scene_source"],
        "scene_index": candidate["scene_index"],
        "world_id": candidate["world_id"],
        "readiness_status": candidate["readiness_status"],
        "failure_class": candidate["failure_class"],
        "blocked_reason": candidate["blocked_reason"],
        "source_availability_status": candidate.get("source_availability_status", ""),
        "candidate_file": candidate.get("candidate_file", {}),
    }


def _candidate_readiness_summary(sources: dict[str, dict[str, Any]]) -> dict[str, Any]:
    return {
        "source_count": len(sources),
        "candidate_count": sum(
            int(source.get("candidate_count") or 0) for source in sources.values()
        ),
        "ready_candidate_count": sum(
            int(source.get("ready_candidate_count") or 0) for source in sources.values()
        ),
        "blocked_candidate_count": sum(
            int(source.get("blocked_candidate_count") or 0) for source in sources.values()
        ),
        "rejected_candidate_count": sum(
            int(source.get("rejected_candidate_count") or 0) for source in sources.values()
        ),
        "ui_ready_count": sum(
            int(source.get("ui_ready_count") or 0) for source in sources.values()
        ),
        "ui_needed_count": sum(
            max(
                0,
                UI_TARGET_PER_SCENE_SOURCE - int(source.get("ui_ready_count") or 0),
            )
            for source in sources.values()
        ),
        "eval_ready_count": sum(
            int(source.get("eval_ready_count") or 0) for source in sources.values()
        ),
        "eval_needed_count": sum(
            max(
                0,
                EVAL_TARGET_PER_SCENE_SOURCE - int(source.get("eval_ready_count") or 0),
            )
            for source in sources.values()
        ),
        "ui_supported_source_count": sum(
            1 for source in sources.values() if source.get("ui_status") == "ready"
        ),
        "eval_complete_source_count": sum(
            1 for source in sources.values() if source.get("eval_status") == "complete"
        ),
        "blocked_source_count": sum(
            1 for source in sources.values() if int(source.get("blocked_candidate_count") or 0) > 0
        ),
    }


def _unique_candidates(candidates: list[dict[str, Any]]) -> list[dict[str, Any]]:
    seen: set[tuple[str, int]] = set()
    unique: list[dict[str, Any]] = []
    for candidate in candidates:
        key = (str(candidate["scene_source"]), int(candidate["scene_index"]))
        if key in seen:
            continue
        seen.add(key)
        unique.append(candidate)
    return unique


def _selection_capacity_status(
    *,
    ui_needed: int,
    ui_available: int,
    eval_needed: int,
    eval_available: int,
    rejected_count: int = 0,
) -> str:
    if ui_needed == 0 and eval_needed == 0:
        return "complete"
    if rejected_count and ui_available == 0 and eval_available == 0:
        return "rejected_exhausted"
    if ui_available < ui_needed or eval_available < eval_needed:
        return "candidate_range_insufficient"
    return "candidate_range_sufficient"


def _selection_next_action(
    *,
    capacity_status: str,
    source_availability_status: Any,
) -> str:
    if capacity_status == "complete":
        return "none"
    if capacity_status == "rejected_exhausted":
        return "do_not_scan_without_new_human_curation"
    if capacity_status == "candidate_range_insufficient":
        return "expand_candidate_range"
    if source_availability_status != "available":
        return "run_source_prep_before_scanner"
    return "run_scanner_admission"


def _selection_gap_summary(sources: dict[str, dict[str, Any]]) -> dict[str, Any]:
    worklist = [
        _selection_source_worklist_item(source)
        for source in sources.values()
        if source.get("status") != "complete"
    ]
    return {
        "source_count": len(sources),
        "complete_source_count": sum(
            1 for source in sources.values() if source.get("status") == "complete"
        ),
        "incomplete_source_count": sum(
            1 for source in sources.values() if source.get("status") != "complete"
        ),
        "ui_needed_count": sum(
            int(source.get("ui_needed_count") or 0) for source in sources.values()
        ),
        "eval_needed_count": sum(
            int(source.get("eval_needed_count") or 0) for source in sources.values()
        ),
        "ui_scan_candidate_count": sum(
            int(source.get("ui_scan_candidate_count") or 0) for source in sources.values()
        ),
        "eval_scan_candidate_count": sum(
            int(source.get("eval_scan_candidate_count") or 0) for source in sources.values()
        ),
        "candidate_range_sufficient_source_count": sum(
            1
            for source in sources.values()
            if source.get("selection_capacity_status") == "candidate_range_sufficient"
        ),
        "candidate_range_insufficient_source_count": sum(
            1
            for source in sources.values()
            if source.get("selection_capacity_status") == "candidate_range_insufficient"
        ),
        "source_prep_required_count": sum(
            1
            for source in sources.values()
            if source.get("next_action") == "run_source_prep_before_scanner"
        ),
        "next_actions": _selection_action_counts(worklist),
        "worklist": worklist,
    }


def _selection_source_worklist_item(source: dict[str, Any]) -> dict[str, Any]:
    return {
        "scene_source": source.get("scene_source", ""),
        "next_action": source.get("next_action", ""),
        "selection_capacity_status": source.get("selection_capacity_status", ""),
        "source_availability_status": source.get("source_availability_status", ""),
        "ui_needed_count": int(source.get("ui_needed_count") or 0),
        "ui_scan_candidate_count": int(source.get("ui_scan_candidate_count") or 0),
        "eval_needed_count": int(source.get("eval_needed_count") or 0),
        "eval_scan_candidate_count": int(source.get("eval_scan_candidate_count") or 0),
        "next_scan_world_ids": [
            item.get("world_id")
            for item in source.get("next_scan_candidates") or []
            if isinstance(item, dict) and item.get("world_id")
        ],
    }


def _selection_action_counts(worklist: list[dict[str, Any]]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for item in worklist:
        action = str(item.get("next_action") or "unknown")
        counts[action] = counts.get(action, 0) + 1
    return dict(sorted(counts.items()))
