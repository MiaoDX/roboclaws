"""Candidate-profile helpers for the MolmoSpaces scene sampler."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from roboclaws.launch.scene_sampler_prep import (
    molmospaces_get_scenes_args,
    molmospaces_module_status,
    molmospaces_scene_index_map,
)
from roboclaws.launch.scene_sampler_sources import (
    CURRENT_CURATED_INDICES,
    SCENE_SAMPLER_SELECTION_SEED,
    SCENE_SAMPLER_SELECTION_STRATEGY,
    known_indices_for_source,
    scanner_metadata,
    source_eval_indices,
    source_selection_metadata,
    source_ui_indices,
)
from roboclaws.launch.scene_sampler_types import (
    READINESS_READY,
    READINESS_REJECTED,
    SAMPLER_GENERATOR_VERSION,
)

CANDIDATE_PROFILE_WORKLIST_TARGET_PER_SCENE_SOURCE = 10
CANDIDATE_PROFILE_POOL_SIZE_PER_SCENE_SOURCE = 40
CANDIDATE_PROFILE_SOURCE_MAP_SCAN_LIMIT_PER_SCENE_SOURCE = 500
CANDIDATE_PROFILE_LANE = "metadata_profile"

ModuleStatusFn = Callable[[], tuple[bool, str, str]]
GetScenesArgsFn = Callable[[str], tuple[str, str]]
SceneIndexMapFn = Callable[..., dict[str, Any]]


def candidate_profile_report(
    *,
    selection: dict[str, Any],
    candidates: dict[str, Any],
    supported_sources: tuple[str, ...],
    candidate_indices: tuple[int, ...],
    selection_policy: dict[str, Any],
    module_status: ModuleStatusFn = molmospaces_module_status,
    get_scenes_args: GetScenesArgsFn = molmospaces_get_scenes_args,
    scene_index_map: SceneIndexMapFn = molmospaces_scene_index_map,
) -> dict[str, Any]:
    """Return a metadata-first source-scoped candidate profile."""

    profile_indices_by_source = _candidate_profile_indices_by_source(
        selection=selection,
        supported_sources=supported_sources,
        candidate_indices=candidate_indices,
        module_status=module_status,
        get_scenes_args=get_scenes_args,
        scene_index_map=scene_index_map,
    )
    expanded_candidate_indices = _expanded_candidate_indices(profile_indices_by_source)
    sources: dict[str, dict[str, Any]] = {}
    for source in supported_sources:
        source_selection = selection["sources"][source]
        source_profile_indices = set(profile_indices_by_source[source])
        worklist_indices = metadata_profile_worklist_indices(
            source=source,
            candidate_indices=candidate_indices,
            selection_source=source_selection,
            module_status=module_status,
            get_scenes_args=get_scenes_args,
            scene_index_map=scene_index_map,
        )
        worklist_index_set = set(worklist_indices)
        profile_rows = [
            candidate_profile_row(
                candidate,
                worklist_rank=(
                    worklist_indices.index(int(candidate.get("scene_index")))
                    if candidate.get("scene_index") in worklist_index_set
                    else None
                ),
            )
            for candidate in candidates["sources"][source].get("candidates") or []
            if candidate.get("scene_index") in source_profile_indices
        ]
        worklist_rows = [
            row
            for row in profile_rows
            if row.get("metadata_worklist_rank") is not None
            and row.get("next_action")
            not in {
                "none",
                "do_not_scan_without_gate_change_or_new_curation",
            }
        ]
        sources[source] = {
            "scene_source": source,
            "scene_family": _family_split(source)[0],
            "scene_split": _family_split(source)[1],
            "profile_status": candidate_profile_status(
                selection_source=source_selection,
                worklist_rows=worklist_rows,
            ),
            "next_action": candidate_profile_next_action(
                selection_source=source_selection,
                worklist_rows=worklist_rows,
            ),
            "selection_capacity_status": source_selection.get("selection_capacity_status", ""),
            "ui_needed_count": int(source_selection.get("ui_needed_count") or 0),
            "eval_needed_count": int(source_selection.get("eval_needed_count") or 0),
            "known_ready_indices": [
                row["scene_index"] for row in profile_rows if row["profile_status"] == "known_ready"
            ],
            "known_rejected_indices": [
                row["scene_index"]
                for row in profile_rows
                if row["profile_status"] == "known_rejected"
            ],
            "requested_candidate_indices": list(candidate_indices),
            "profile_candidate_indices": list(profile_indices_by_source[source]),
            "metadata_worklist_indices": list(worklist_indices),
            "metadata_worklist_world_ids": [row["world_id"] for row in worklist_rows],
            "metadata_worklist_candidate_count": len(worklist_rows),
            "candidates": profile_rows,
            "metadata_worklist_candidates": worklist_rows,
        }
    return {
        "schema": "molmospaces_scene_sampler_candidate_profile_v1",
        "generator_version": SAMPLER_GENERATOR_VERSION,
        "probe_mode": "no_download_no_backend_no_vlm",
        "download_policy": "manual_operator_only",
        "candidate_profile_policy": candidate_profile_policy(
            supported_sources=supported_sources,
            get_scenes_args=get_scenes_args,
        ),
        "candidate_indices": list(candidate_indices),
        "expanded_candidate_indices": list(expanded_candidate_indices),
        "selection_policy": selection_policy,
        "summary": candidate_profile_summary(sources),
        "sources": sources,
    }


def candidate_profile_expanded_indices(
    *,
    selection: dict[str, Any],
    supported_sources: tuple[str, ...],
    candidate_indices: tuple[int, ...],
    module_status: ModuleStatusFn = molmospaces_module_status,
    get_scenes_args: GetScenesArgsFn = molmospaces_get_scenes_args,
    scene_index_map: SceneIndexMapFn = molmospaces_scene_index_map,
) -> tuple[int, ...]:
    profile_indices_by_source = _candidate_profile_indices_by_source(
        selection=selection,
        supported_sources=supported_sources,
        candidate_indices=candidate_indices,
        module_status=module_status,
        get_scenes_args=get_scenes_args,
        scene_index_map=scene_index_map,
    )
    return _expanded_candidate_indices(profile_indices_by_source)


def _candidate_profile_indices_by_source(
    *,
    selection: dict[str, Any],
    supported_sources: tuple[str, ...],
    candidate_indices: tuple[int, ...],
    module_status: ModuleStatusFn,
    get_scenes_args: GetScenesArgsFn,
    scene_index_map: SceneIndexMapFn,
) -> dict[str, tuple[int, ...]]:
    profile_indices_by_source = {
        source: candidate_profile_indices_for_source(
            source=source,
            candidate_indices=candidate_indices,
            selection_source=selection["sources"][source],
            module_status=module_status,
            get_scenes_args=get_scenes_args,
            scene_index_map=scene_index_map,
        )
        for source in supported_sources
    }
    return profile_indices_by_source


def _expanded_candidate_indices(
    profile_indices_by_source: dict[str, tuple[int, ...]],
) -> tuple[int, ...]:
    return tuple(
        sorted(
            {
                index
                for profile_indices in profile_indices_by_source.values()
                for index in profile_indices
            }
        )
    )


def candidate_profile_policy(
    *,
    supported_sources: tuple[str, ...],
    get_scenes_args: GetScenesArgsFn = molmospaces_get_scenes_args,
) -> dict[str, Any]:
    return {
        "schema": "molmospaces_scene_sampler_candidate_profile_policy_v1",
        "selection_seed": SCENE_SAMPLER_SELECTION_SEED,
        "selection_strategy": SCENE_SAMPLER_SELECTION_STRATEGY,
        "lane": CANDIDATE_PROFILE_LANE,
        "worklist_target_per_scene_source": CANDIDATE_PROFILE_WORKLIST_TARGET_PER_SCENE_SOURCE,
        "pool_size_per_scene_source": CANDIDATE_PROFILE_POOL_SIZE_PER_SCENE_SOURCE,
        "admission_effect": "none_profile_only",
        "download_policy": "manual_operator_only",
        "sources": {
            source: {
                "dataset_name": get_scenes_args(source)[0],
                "split": get_scenes_args(source)[1],
            }
            for source in supported_sources
        },
    }


def candidate_profile_indices_for_source(
    *,
    source: str,
    candidate_indices: tuple[int, ...],
    selection_source: dict[str, Any],
    module_status: ModuleStatusFn = molmospaces_module_status,
    get_scenes_args: GetScenesArgsFn = molmospaces_get_scenes_args,
    scene_index_map: SceneIndexMapFn = molmospaces_scene_index_map,
) -> tuple[int, ...]:
    return tuple(
        sorted(
            {
                *candidate_indices,
                *_known_profile_indices(source),
                *metadata_profile_worklist_indices(
                    source=source,
                    candidate_indices=candidate_indices,
                    selection_source=selection_source,
                    module_status=module_status,
                    get_scenes_args=get_scenes_args,
                    scene_index_map=scene_index_map,
                ),
            }
        )
    )


def metadata_profile_worklist_indices(
    *,
    source: str,
    candidate_indices: tuple[int, ...],
    selection_source: dict[str, Any],
    module_status: ModuleStatusFn = molmospaces_module_status,
    get_scenes_args: GetScenesArgsFn = molmospaces_get_scenes_args,
    scene_index_map: SceneIndexMapFn = molmospaces_scene_index_map,
) -> tuple[int, ...]:
    if (
        int(selection_source.get("ui_needed_count") or 0) <= 0
        and int(selection_source.get("eval_needed_count") or 0) <= 0
    ):
        return ()
    excluded = set(_known_profile_indices(source))
    excluded.update(
        int(index)
        for index in candidate_indices
        if scanner_metadata(source=source, scene_index=int(index))
    )
    pool = [
        index
        for index in _metadata_profile_candidate_pool(
            source,
            module_status=module_status,
            get_scenes_args=get_scenes_args,
            scene_index_map=scene_index_map,
        )
        if index not in excluded
    ]
    ranked = source_selection_metadata(
        source=source,
        lane=CANDIDATE_PROFILE_LANE,
        target_count=len(pool),
        candidates=tuple(pool),
    )["selected_indices"]
    return tuple(
        int(index) for index in ranked[:CANDIDATE_PROFILE_WORKLIST_TARGET_PER_SCENE_SOURCE]
    )


def candidate_profile_row(
    candidate: dict[str, Any],
    *,
    worklist_rank: int | None,
) -> dict[str, Any]:
    scene_index = int(candidate.get("scene_index") or 0)
    known_status = _candidate_known_profile_status(candidate)
    blocked_reason = str(candidate.get("blocked_reason") or "")
    if worklist_rank is not None and known_status == "unprofiled":
        profile_status = "metadata_worklist"
        next_action = "metadata_first_human_curation"
        selected_reason = "selected_for_metadata_first_source_curation"
    else:
        profile_status = known_status
        next_action = _candidate_profile_row_next_action(candidate, known_status=known_status)
        selected_reason = str(candidate.get("selected_reason") or "")
    return {
        "scene_source": candidate.get("scene_source", ""),
        "scene_family": candidate.get("scene_family", ""),
        "scene_split": candidate.get("scene_split", ""),
        "scene_index": scene_index,
        "world_id": candidate.get("world_id", ""),
        "profile_status": profile_status,
        "readiness_status": candidate.get("readiness_status", ""),
        "next_action": next_action,
        "metadata_worklist_rank": worklist_rank,
        "known_room_count": int(candidate.get("room_count") or 0),
        "known_waypoint_count": int(candidate.get("waypoint_count") or 0),
        "known_failure_class": candidate.get("failure_class", ""),
        "known_blocked_reason": blocked_reason,
        "known_source_outcome": candidate.get("source_outcome", ""),
        "known_prefilter_status": candidate.get("prefilter_status", ""),
        "known_prefilter_reason": candidate.get("prefilter_reason", ""),
        "known_cheap_room_count": int(candidate.get("cheap_room_count") or 0),
        "known_product_smoke_run_dir": candidate.get("product_smoke_run_dir", ""),
        "candidate_file_status": (candidate.get("candidate_file") or {}).get("status", ""),
        "candidate_file_exists": bool((candidate.get("candidate_file") or {}).get("exists")),
        "candidate_file": candidate.get("candidate_file") or {},
        "selected_reason": selected_reason,
        "download_policy": "manual_operator_only",
        "admission_effect": "none_profile_only",
    }


def source_gate_mismatch_profile_rows(
    source_candidate_profile: dict[str, Any],
) -> list[dict[str, Any]]:
    return [
        row
        for row in source_candidate_profile.get("candidates") or []
        if isinstance(row, dict) and row.get("known_source_outcome") == "gate_mismatch"
    ]


def _known_profile_indices(source: str) -> tuple[int, ...]:
    known: set[int] = set()
    for index in known_indices_for_source(source):
        if scanner_metadata(source=source, scene_index=index):
            known.add(index)
    known.update(source_ui_indices(source))
    known.update(source_eval_indices(source))
    if source == "procthor-10k-val":
        known.update(CURRENT_CURATED_INDICES)
    return tuple(sorted(known))


def _metadata_profile_candidate_pool(
    source: str,
    *,
    module_status: ModuleStatusFn,
    get_scenes_args: GetScenesArgsFn,
    scene_index_map: SceneIndexMapFn,
) -> tuple[int, ...]:
    module_available, _, _ = module_status()
    dataset_name, split = get_scenes_args(source)
    candidate_indices = tuple(range(CANDIDATE_PROFILE_SOURCE_MAP_SCAN_LIMIT_PER_SCENE_SOURCE))
    source_index_map = scene_index_map(
        source=source,
        dataset_name=dataset_name,
        split=split,
        candidate_indices=candidate_indices,
        module_available=module_available,
    )
    if source_index_map.get("status") == "available":
        concrete_indices = [
            int(item["scene_index"])
            for item in source_index_map.get("candidate_scene_refs") or []
            if isinstance(item, dict)
            and item.get("status") == "available"
            and (item.get("primary_path") or item.get("paths") or item.get("missing_paths"))
        ]
        if concrete_indices:
            return tuple(sorted(concrete_indices))
    return tuple(range(CANDIDATE_PROFILE_POOL_SIZE_PER_SCENE_SOURCE))


def _candidate_known_profile_status(candidate: dict[str, Any]) -> str:
    readiness_status = str(candidate.get("readiness_status") or "")
    if readiness_status == READINESS_READY:
        return "known_ready"
    if readiness_status == READINESS_REJECTED:
        return "known_rejected"
    if int(candidate.get("room_count") or 0) > 0 or int(candidate.get("waypoint_count") or 0) > 0:
        return "known_blocked"
    return "unprofiled"


def _candidate_profile_row_next_action(
    candidate: dict[str, Any],
    *,
    known_status: str,
) -> str:
    if known_status == "known_ready":
        return "none"
    if known_status == "known_rejected":
        return "do_not_scan_without_gate_change_or_new_curation"
    candidate_file = candidate.get("candidate_file")
    if (
        isinstance(candidate_file, dict)
        and candidate_file.get("status") == "missing_from_index_map"
    ):
        return "choose_valid_source_specific_candidate_index"
    if not isinstance(candidate_file, dict) or not candidate_file.get("exists"):
        return "inspect_source_index_before_download"
    return "render_preview_then_map_build_product_smoke"


def candidate_profile_status(
    *,
    selection_source: dict[str, Any],
    worklist_rows: list[dict[str, Any]],
) -> str:
    if selection_source.get("selection_capacity_status") == "complete":
        return "complete"
    if worklist_rows:
        return "metadata_worklist_ready"
    if selection_source.get("selection_capacity_status") == "rejected_exhausted":
        return "known_rejected_exhausted"
    return "needs_candidate_range"


def candidate_profile_next_action(
    *,
    selection_source: dict[str, Any],
    worklist_rows: list[dict[str, Any]],
) -> str:
    if selection_source.get("selection_capacity_status") == "complete":
        return "none"
    if worklist_rows:
        return "metadata_first_human_curation"
    if selection_source.get("selection_capacity_status") == "rejected_exhausted":
        return "choose_new_candidate_indices_or_gate_change"
    return "expand_candidate_range"


def candidate_profile_summary(sources: dict[str, dict[str, Any]]) -> dict[str, Any]:
    worklist = [
        _candidate_profile_worklist_item(source)
        for source in sources.values()
        if source.get("next_action") != "none"
    ]
    return {
        "source_count": len(sources),
        "complete_source_count": sum(
            1 for source in sources.values() if source.get("profile_status") == "complete"
        ),
        "metadata_worklist_source_count": sum(
            1
            for source in sources.values()
            if source.get("profile_status") == "metadata_worklist_ready"
        ),
        "metadata_worklist_candidate_count": sum(
            int(source.get("metadata_worklist_candidate_count") or 0) for source in sources.values()
        ),
        "known_ready_candidate_count": sum(
            len(source.get("known_ready_indices") or []) for source in sources.values()
        ),
        "known_rejected_candidate_count": sum(
            len(source.get("known_rejected_indices") or []) for source in sources.values()
        ),
        "next_actions": _selection_action_counts(worklist),
        "worklist": worklist,
    }


def _candidate_profile_worklist_item(source: dict[str, Any]) -> dict[str, Any]:
    return {
        "scene_source": source.get("scene_source", ""),
        "profile_status": source.get("profile_status", ""),
        "next_action": source.get("next_action", ""),
        "selection_capacity_status": source.get("selection_capacity_status", ""),
        "ui_needed_count": int(source.get("ui_needed_count") or 0),
        "eval_needed_count": int(source.get("eval_needed_count") or 0),
        "metadata_worklist_candidate_count": int(
            source.get("metadata_worklist_candidate_count") or 0
        ),
        "metadata_worklist_world_ids": source.get("metadata_worklist_world_ids") or [],
    }


def _selection_action_counts(worklist: list[dict[str, Any]]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for item in worklist:
        action = str(item.get("next_action") or "unknown")
        counts[action] = counts.get(action, 0) + 1
    return dict(sorted(counts.items()))


def _family_split(scene_source: str) -> tuple[str, str]:
    if scene_source == "ithor":
        return "ithor", "not_applicable"
    for split in ("-train", "-val", "-test"):
        if scene_source.endswith(split):
            return scene_source[: -len(split)], split.removeprefix("-")
    return scene_source, "not_applicable"
