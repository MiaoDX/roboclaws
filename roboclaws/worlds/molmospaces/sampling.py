"""Source-aware MolmoSpaces scene sampler contract."""

from __future__ import annotations

import platform
import sys
from pathlib import Path
from typing import Any

from roboclaws.core.json_sources import read_json_object
from roboclaws.worlds.molmospaces.catalog import (
    SCANNER_READY_METADATA,
    SCENE_SAMPLER_SELECTION_SEED,
    SCENE_SAMPLER_SELECTION_STRATEGY,
    SOURCE_EVAL_CANDIDATE_INDICES,
    SOURCE_UI_CANDIDATE_INDICES,
    admitted_sources,
    category_manifest,
    category_provenance,
    known_indices_for_source,
    sampler_world_id,
    scanner_metadata,
    source_eval_indices,
    source_selection_metadata,
    source_ui_indices,
    uses_legacy_preview_assets,
)
from roboclaws.worlds.molmospaces.contracts import (
    EVAL_STRESS_LANE,
    READINESS_BLOCKED,
    READINESS_READY,
    READINESS_REJECTED,
    SAMPLER_GENERATOR_VERSION,
    UI_LANE,
    MolmoSpacesSceneRef,
    SceneSamplerRow,
)
from roboclaws.worlds.molmospaces.map_bundles import (
    SIM_MAP_BUNDLE_ASSET_ROOT,
    molmospaces_nav2_map_bundle_path,
)
from roboclaws.worlds.molmospaces.prefilter import (
    scene_only_prefilter_report as _scene_only_prefilter_report,
)
from roboclaws.worlds.molmospaces.prefilter import (
    scene_prefilter_expensive_proof_candidates as _scene_prefilter_expensive_proof_candidates,
)
from roboclaws.worlds.molmospaces.preparation import (
    molmospaces_get_scenes_args as _molmospaces_get_scenes_args,
)
from roboclaws.worlds.molmospaces.preparation import (
    molmospaces_module_status as _molmospaces_module_status,
)
from roboclaws.worlds.molmospaces.preparation import (
    molmospaces_scene_index_map as _molmospaces_scene_index_map,
)
from roboclaws.worlds.molmospaces.preparation import (
    molmospaces_scene_root_status as _molmospaces_scene_root_status,
)
from roboclaws.worlds.molmospaces.preparation import (
    source_availability_blocked_reason as _source_availability_blocked_reason,
)
from roboclaws.worlds.molmospaces.preparation import (
    source_availability_summary as _source_availability_summary,
)
from roboclaws.worlds.molmospaces.preparation import (
    source_prep_report as _source_prep_report,
)
from roboclaws.worlds.molmospaces.profile import (
    candidate_profile_expanded_indices as _candidate_profile_expanded_indices,
)
from roboclaws.worlds.molmospaces.profile import (
    candidate_profile_report as _candidate_profile_report,
)
from roboclaws.worlds.molmospaces.profile import (
    source_gate_mismatch_profile_rows as _source_gate_mismatch_profile_rows,
)
from roboclaws.worlds.molmospaces.scanner import (
    coverage_score as _scanner_coverage_score,
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
    scanner_admission_row,
    scanner_admission_summary,
    scanner_candidate_packet,
    scanner_execution_candidate,
    scanner_execution_summary,
    scanner_gate_mismatch_count,
    scanner_preview_assets,
    scanner_preview_metadata,
    scanner_product_smoke_artifacts,
    scanner_required_gates,
    world_id_slug,
)

SAMPLER_MANIFEST_SCHEMA = "molmospaces_scene_sampler_manifest_v1"
SAMPLER_LABEL_MANIFEST_SCHEMA = "molmospaces_scene_room_labels_v1"
SAMPLER_PROJECTION_SCHEMA = "molmospaces_scene_sampler_projection_v1"
PRIMARY_MOLMOSPACES_BACKEND = "mujoco"
UI_TARGET_PER_SCENE_SOURCE = 3
EVAL_TARGET_PER_SCENE_SOURCE = 10
SUPPORTED_SCENE_SOURCES: tuple[str, ...] = (
    "procthor-10k-val",
    "ithor",
    "procthor-objaverse-val",
    "holodeck-objaverse-val",
)

_PREVIEW_ROOT = Path(__file__).resolve().parents[2] / "operator_console" / "static" / "previews"
_CANONICAL_SCANNER_PREVIEW_ROOT = Path("output") / "scene-sampler-scanner" / "previews"
_SCANNER_OUTPUT_ROOT = Path("output") / "scene-sampler-scanner"
_SCANNER_PREVIEW_ROOT = _SCANNER_OUTPUT_ROOT / "previews"
_SCANNER_PRODUCT_SMOKE_ROOT = _SCANNER_OUTPUT_ROOT / "product-smoke"
_LABEL_MANIFEST_PATH = (
    Path(__file__).resolve().parents[3]
    / "data"
    / "molmospaces"
    / ("scene_sampler_room_labels.json")
)


def sampler_manifest() -> dict[str, Any]:
    """Return the canonical source-aware MolmoSpaces sampler manifest."""

    rows = [row.to_dict() for row in sampler_rows()]
    return {
        "schema": SAMPLER_MANIFEST_SCHEMA,
        "generator_version": SAMPLER_GENERATOR_VERSION,
        "primary_backend": PRIMARY_MOLMOSPACES_BACKEND,
        "ui_target_per_scene_source": UI_TARGET_PER_SCENE_SOURCE,
        "eval_target_per_scene_source": EVAL_TARGET_PER_SCENE_SOURCE,
        "supported_scene_sources": list(SUPPORTED_SCENE_SOURCES),
        "room_label_manifest": str(_LABEL_MANIFEST_PATH.relative_to(_repo_root())),
        "selection_policy": _sampler_selection_policy(),
        "rows": rows,
        "projections": {
            "ui_world_ids": [row.world_id for row in ui_sampler_rows()],
            "eval_sample_ids": [eval_sample_id(row) for row in eval_sampler_rows()],
            "blocked_scene_sources": [
                row.scene_source
                for row in sampler_rows()
                if row.readiness_status == READINESS_BLOCKED
            ],
        },
    }


def sampler_rows() -> tuple[SceneSamplerRow, ...]:
    """Return all known source rows, including blocked source-family packets."""

    rows: list[SceneSamplerRow] = []
    sources = admitted_sources(supported_sources=SUPPORTED_SCENE_SOURCES)
    for source in sources:
        rows.extend(
            _ready_row(source=source, scene_index=index)
            for index in known_indices_for_source(source)
        )
    rows.extend(
        _blocked_source_row(scene_source)
        for scene_source in SUPPORTED_SCENE_SOURCES
        if scene_source not in sources
    )
    return tuple(rows)


def ui_sampler_rows() -> tuple[SceneSamplerRow, ...]:
    """Return exactly the UI-visible MolmoSpaces sampler rows."""

    return tuple(row for row in sampler_rows() if row.ui_ready)


def eval_sampler_rows() -> tuple[SceneSamplerRow, ...]:
    """Return rows admitted to the static eval-stress projection."""

    return tuple(row for row in sampler_rows() if row.eval_ready)


def sampler_blocked_rows() -> tuple[SceneSamplerRow, ...]:
    """Return blocked or partial rows used by reports and eval-harness metadata."""

    return tuple(row for row in sampler_rows() if row.readiness_status != READINESS_READY)


def parse_molmospaces_world_id(world_id: str) -> MolmoSpacesSceneRef:
    """Parse a source-aware ``molmospaces/<scene_source>/<index>`` world id."""

    legacy_prefix = "molmospaces/val_"
    if world_id.startswith(legacy_prefix):
        index = _parse_scene_index(world_id.removeprefix(legacy_prefix), world_id=world_id)
        raise ValueError(
            f"legacy MolmoSpaces world id {world_id!r} is unsupported; "
            f"use 'molmospaces/procthor-10k-val/{index}'"
        )

    parts = world_id.split("/")
    if len(parts) == 3 and parts[0] == "molmospaces":
        scene_source = parts[1]
        if scene_source not in SUPPORTED_SCENE_SOURCES:
            raise ValueError(f"unsupported MolmoSpaces scene_source {scene_source!r}: {world_id}")
        return MolmoSpacesSceneRef(
            scene_source=scene_source,
            scene_index=_parse_scene_index(parts[2], world_id=world_id),
        )

    raise ValueError(f"unsupported world {world_id!r}")


def ui_molmospaces_world_ids() -> tuple[str, ...]:
    """Return the curated operator-console world ids."""

    return tuple(row.world_id for row in ui_sampler_rows())


def eval_sample_id(row: SceneSamplerRow) -> str:
    if row.scene_index is None:
        return f"scene_sampler.{row.scene_source}.blocked"
    return f"scene_sampler.{row.scene_source}.{row.scene_index}.map_build"


def eval_sample_ref(row: SceneSamplerRow) -> str:
    if row.scene_index is None:
        return ""
    return (
        "evals/household_world/samples/scene_sampler/"
        f"{row.scene_source}_{row.scene_index}_map_build.json"
    )


def eval_projection_metadata() -> dict[str, Any]:
    """Return machine-readable sampler stress metadata for suite JSON."""

    rows = eval_sampler_rows()
    by_source: dict[str, dict[str, Any]] = {}
    total_ready_count = 0
    total_blocked_count = 0
    total_rejected_count = 0
    total_blocked_or_rejected_row_count = 0
    total_remaining_count = 0
    for source in SUPPORTED_SCENE_SOURCES:
        ready = [row for row in rows if row.scene_source == source]
        blocked_or_rejected = [
            row for row in sampler_rows() if row.scene_source == source and row.blocked_reason
        ]
        blocked = [row for row in blocked_or_rejected if row.readiness_status == READINESS_BLOCKED]
        rejected = [
            row for row in blocked_or_rejected if row.readiness_status == READINESS_REJECTED
        ]
        ready_count = len(ready)
        blocked_count = len(blocked)
        rejected_count = len(rejected)
        blocked_or_rejected_row_count = len(blocked_or_rejected)
        remaining_count = max(0, EVAL_TARGET_PER_SCENE_SOURCE - ready_count)
        support_status = _eval_projection_support_status(
            ready_count=ready_count,
            blocked_count=blocked_count,
            rejected_count=rejected_count,
            target_count=EVAL_TARGET_PER_SCENE_SOURCE,
        )
        total_ready_count += ready_count
        total_blocked_count += blocked_count
        total_rejected_count += rejected_count
        total_blocked_or_rejected_row_count += blocked_or_rejected_row_count
        total_remaining_count += remaining_count
        by_source[source] = {
            "target_count": EVAL_TARGET_PER_SCENE_SOURCE,
            "ready_count": ready_count,
            "partial_gap_count": remaining_count,
            "needed_count": remaining_count,
            "blocked_count": blocked_count,
            "rejected_count": rejected_count,
            "blocked_or_rejected_row_count": blocked_or_rejected_row_count,
            "support_status": support_status,
            "status": (
                "complete"
                if ready_count == EVAL_TARGET_PER_SCENE_SOURCE
                else ("rejected" if support_status == "rejected" else "partial_or_blocked")
            ),
            "sample_ids": [eval_sample_id(row) for row in ready],
            "blocked_rows": [row.to_dict() for row in blocked_or_rejected],
        }
    return {
        "schema": SAMPLER_PROJECTION_SCHEMA,
        "projection": EVAL_STRESS_LANE,
        "generator_version": SAMPLER_GENERATOR_VERSION,
        "selection_policy": _sampler_selection_policy(),
        "scene_sources": by_source,
        "summary": {
            "source_count": len(SUPPORTED_SCENE_SOURCES),
            "target_sample_count": len(SUPPORTED_SCENE_SOURCES) * EVAL_TARGET_PER_SCENE_SOURCE,
            "ready_sample_count": total_ready_count,
            "partial_source_count": sum(
                1 for payload in by_source.values() if payload["support_status"] == "partial"
            ),
            "rejected_source_count": sum(
                1 for payload in by_source.values() if payload["support_status"] == "rejected"
            ),
            "blocked_source_count": sum(
                1 for payload in by_source.values() if payload["support_status"] == "blocked"
            ),
            "complete_source_count": sum(
                1 for payload in by_source.values() if payload["support_status"] == "complete"
            ),
            "blocked_row_count": total_blocked_count,
            "rejected_row_count": total_rejected_count,
            "blocked_or_rejected_row_count": total_blocked_or_rejected_row_count,
            "remaining_sample_count": total_remaining_count,
        },
    }


def eval_suite_payload() -> dict[str, Any]:
    """Return generated scene-sampler eval suite JSON from admitted rows."""

    rows = eval_sampler_rows()
    return {
        "schema": "roboclaws_eval_suite_v1",
        "suite_id": "household_world.scene_sampler_stress",
        "version": "2026-06-15",
        "capability": "household_world_scene_sampling",
        "sample_ids": [eval_sample_id(row) for row in rows],
        "sample_refs": [eval_sample_ref(row) for row in rows],
        "required_graders": [
            "artifacts",
            "privacy",
            "trajectory",
            "sampler_admission",
            "outcome",
        ],
        "thresholds": {
            "pass_at_1": 1.0,
            "private_truth_leak_count": 0,
            "trajectory_policy_violation_count": 0,
        },
        "metadata": {
            "runner_scope": "direct-runner source-aware MolmoSpaces map-build stress projection",
            "live_provider_required": False,
            "sampler_projection": eval_projection_metadata(),
        },
    }


def eval_sample_payload(row: SceneSamplerRow) -> dict[str, Any]:
    """Return generated scene-sampler eval sample JSON for one admitted row."""

    if not row.eval_ready or row.scene_index is None:
        raise ValueError("eval sample payload requires an eval-ready sampler row")
    return {
        "schema": "roboclaws_eval_sample_v1",
        "sample_id": eval_sample_id(row),
        "version": "2026-06-15",
        "surface": "household-world",
        "intent": "map-build",
        "preset": "map-build",
        "world": row.world_id,
        "backend": row.backend,
        "evidence_lane": "world-public-labels",
        "camera_labeler": "not_applicable",
        "scenario_setup": "baseline",
        "seed": 7,
        "prompt": "not_applicable",
        "goal_contract_hash": "unavailable",
        "allowed_agent_engines": ["direct-runner"],
        "provider_profiles": ["not_applicable"],
        "trial_count": 1,
        "required_graders": [
            "artifacts",
            "privacy",
            "trajectory",
            "sampler_admission",
            "outcome",
        ],
        "private_goal_reference": {
            "schema": "household_eval_private_goal_reference_v1",
            "private_truth_scope": "grader_only",
            "expected_runtime_metric_map": True,
        },
        "grader_config": {
            "min_public_semantic_anchors": 1,
            "min_generated_exploration_candidates": 1,
            "require_runtime_metric_map_schema": "runtime_metric_map_v1",
            "require_private_truth_absent": True,
            "require_source_map_not_mutated": True,
            "sampler_admission": {
                "schema": "molmospaces_scene_sampler_admission_v1",
                "scene_family": row.scene_family,
                "scene_split": row.scene_split,
                "scene_source": row.scene_source,
                "scene_index": row.scene_index,
                "room_count": row.room_count,
                "waypoint_count": row.waypoint_count,
                "category_provenance": row.category_provenance,
                "category_manifest": row.category_manifest,
                "generator_version": SAMPLER_GENERATOR_VERSION,
            },
        },
        "launch_overrides": _eval_sample_launch_overrides(row),
    }


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


def load_room_label_manifest(path: Path | None = None) -> dict[str, Any]:
    """Load the prepared room-category label manifest used for admission."""

    manifest_path = path or _LABEL_MANIFEST_PATH
    try:
        payload = read_json_object(manifest_path, label="room label manifest")
    except FileNotFoundError as exc:
        raise ValueError(f"room label manifest missing: {manifest_path}") from exc
    if payload.get("schema") != SAMPLER_LABEL_MANIFEST_SCHEMA:
        raise ValueError(
            "room label manifest must use schema "
            f"{SAMPLER_LABEL_MANIFEST_SCHEMA}, got {payload.get('schema')!r}"
        )
    return payload


def validate_sampler_manifest(manifest: dict[str, Any] | None = None) -> None:
    """Validate sampler rows against source-count and provenance gates."""

    payload = manifest or sampler_manifest()
    rows = _manifest_rows(payload)
    label_manifest = load_room_label_manifest()
    _validate_label_manifest(label_manifest)
    by_source: dict[str, list[dict[str, Any]]] = {source: [] for source in SUPPORTED_SCENE_SOURCES}
    for row in rows:
        source = _validate_sampler_row(row, label_manifest=label_manifest)
        by_source[source].append(row)

    for source, source_rows in by_source.items():
        _validate_source_lane_counts(source=source, source_rows=source_rows)


def _ready_row(*, source: str, scene_index: int) -> SceneSamplerRow:
    metadata = scanner_metadata(source=source, scene_index=scene_index)
    preview = _ready_row_preview_metadata(source=source, scene_index=scene_index)
    bundle_counts = _base_metric_map_bundle_counts(source=source, scene_index=scene_index)
    room_ids = _room_ids(preview)
    room_count = int((metadata or {}).get("room_count") or bundle_counts[0] or len(room_ids))
    waypoint_count = int(
        (metadata or {}).get("waypoint_count") or bundle_counts[1] or _waypoint_count(preview)
    )
    view_statuses = _view_statuses(preview)
    all_views_reviewable = all(
        view_statuses.get(view) == "reviewable" for view in _required_views()
    )
    ui_ready = scene_index in source_ui_indices(source)
    eval_ready = scene_index in source_eval_indices(source)
    rejected_reason = str((metadata or {}).get("blocked_reason") or "")
    if room_count < 3 and not rejected_reason:
        rejected_reason = "fewer_than_three_public_navigation_areas"
    elif not all_views_reviewable and not rejected_reason:
        rejected_reason = "preview_not_reviewable"
    status = (
        READINESS_READY if (ui_ready or eval_ready) and not rejected_reason else READINESS_REJECTED
    )
    lanes: list[str] = []
    if ui_ready and status == READINESS_READY:
        lanes.append(UI_LANE)
    if eval_ready and status == READINESS_READY:
        lanes.append(EVAL_STRESS_LANE)
    selected_reason = (
        "selected_by_preview_scanner_for_source_diversity_and_map_actionability_seed"
        if lanes
        else rejected_reason or "candidate_not_selected"
    )
    failure_class = str((metadata or {}).get("failure_class") or "")
    if rejected_reason and not failure_class:
        failure_class = "map_actionability_failure"
    return SceneSamplerRow(
        scene_family=_family_split(source)[0],
        scene_split=_family_split(source)[1],
        scene_source=source,
        scene_index=scene_index,
        backend=PRIMARY_MOLMOSPACES_BACKEND,
        readiness_status=status,
        lanes=tuple(lanes),
        world_id=sampler_world_id(source=source, scene_index=scene_index),
        room_count=room_count,
        waypoint_count=waypoint_count,
        category_provenance=category_provenance(source),
        category_manifest=category_manifest(
            source,
            default_manifest=str(_LABEL_MANIFEST_PATH.relative_to(_repo_root())),
        ),
        preview_assets=_ready_row_preview_assets(source=source, scene_index=scene_index),
        selected_reason=selected_reason,
        blocked_reason=rejected_reason,
        failure_class=failure_class,
        quality_score=float((metadata or {}).get("quality_score") or _quality_score(preview)),
        coverage_score=float(
            (metadata or {}).get("coverage_score")
            or _coverage_score(room_count=room_count, waypoint_count=waypoint_count)
        ),
    )


def _eval_sample_launch_overrides(row: SceneSamplerRow) -> dict[str, Any]:
    overrides: dict[str, Any] = {
        "agent_engine": "direct-runner",
        "evidence_lane": "world-public-labels",
        "seed": 7,
        "scenario_setup": "baseline",
        "scene_source": row.scene_source,
        "scene_index": int(row.scene_index),
    }
    return overrides


def _blocked_source_row(scene_source: str) -> SceneSamplerRow:
    family, split = _family_split(scene_source)
    return SceneSamplerRow(
        scene_family=family,
        scene_split=split,
        scene_source=scene_source,
        scene_index=None,
        backend=PRIMARY_MOLMOSPACES_BACKEND,
        readiness_status=READINESS_BLOCKED,
        lanes=(),
        world_id=f"molmospaces/{scene_source}/blocked",
        room_count=0,
        waypoint_count=0,
        category_provenance="unavailable",
        category_manifest="",
        preview_assets=(),
        selected_reason="blocked_until_assets_and_preview_readiness_exist",
        blocked_reason=(
            "MolmoSpaces source assets or loader metadata are not locally verified by the "
            "no-download sampler fixture; run scene preparation before admission."
        ),
        failure_class="environment_blocked",
    )


def _eval_projection_support_status(
    *,
    ready_count: int,
    blocked_count: int,
    rejected_count: int,
    target_count: int,
) -> str:
    if ready_count == target_count:
        return "complete"
    if ready_count > 0:
        return "partial"
    if blocked_count > 0:
        return "blocked"
    if rejected_count > 0:
        return "rejected"
    return "not_started"


def _preview_metadata(scene_index: int) -> dict[str, Any]:
    path = _PREVIEW_ROOT / f"molmospaces-val_{scene_index}-preview.json"
    try:
        payload = read_json_object(path, label="scene sampler preview metadata")
    except FileNotFoundError as exc:
        raise ValueError(f"missing preview metadata for scene {scene_index}: {path}") from exc
    except ValueError as exc:
        raise ValueError(str(exc)) from exc
    if payload.get("scene_source") != "procthor-10k-val":
        raise ValueError(f"preview {path} is not procthor-10k-val")
    if payload.get("backend") != PRIMARY_MOLMOSPACES_BACKEND:
        raise ValueError(f"preview {path} is not for backend={PRIMARY_MOLMOSPACES_BACKEND}")
    return payload


def _ready_row_preview_metadata(*, source: str, scene_index: int) -> dict[str, Any]:
    if source != "procthor-10k-val" or scene_index in SCANNER_READY_METADATA.get(source, {}):
        preview = _scanner_preview_metadata(source, scene_index)
        return preview or _static_scanner_preview_metadata(source=source, scene_index=scene_index)
    return _preview_metadata(scene_index)


def _static_scanner_preview_metadata(*, source: str, scene_index: int) -> dict[str, Any]:
    metadata = scanner_metadata(source=source, scene_index=scene_index)
    room_count = int(metadata["room_count"])
    waypoint_count = int(metadata["waypoint_count"])
    views = {
        view: {"image_diagnostics": {"visual_status": "reviewable"}} for view in _required_views()
    }
    return {
        "scene_source": source,
        "scene_index": scene_index,
        "backend": PRIMARY_MOLMOSPACES_BACKEND,
        "room_count": room_count,
        "waypoint_count": waypoint_count,
        "views": views,
    }


def _view_statuses(preview: dict[str, Any]) -> dict[str, str]:
    views = preview.get("views") if isinstance(preview.get("views"), dict) else {}
    return {
        view: str((payload.get("image_diagnostics") or {}).get("visual_status") or "")
        for view, payload in views.items()
        if isinstance(payload, dict)
    }


def _room_ids(preview: dict[str, Any]) -> tuple[str, ...]:
    count = int(preview.get("room_count") or 0)
    return tuple(f"room_{index}" for index in range(count))


def _waypoint_count(preview: dict[str, Any]) -> int:
    return int(preview.get("waypoint_count") or 0)


def _quality_score(preview: dict[str, Any]) -> float:
    statuses = _view_statuses(preview)
    reviewable_count = sum(1 for view in _required_views() if statuses.get(view) == "reviewable")
    return round(reviewable_count / len(_required_views()), 3)


def _coverage_score(*, room_count: int, waypoint_count: int) -> float:
    return _scanner_coverage_score(room_count=room_count, waypoint_count=waypoint_count)


def _preview_assets(scene_index: int) -> tuple[tuple[str, str], ...]:
    scene_name = f"val_{scene_index}"
    return (
        ("fpv", f"/previews/molmospaces-{scene_name}-fpv.png"),
        ("map", f"/previews/molmospaces-{scene_name}-map.png"),
        ("chase", f"/previews/molmospaces-{scene_name}-chase.png"),
        ("topdown", f"/previews/molmospaces-{scene_name}-topdown.png"),
    )


def _ready_row_preview_assets(*, source: str, scene_index: int) -> tuple[tuple[str, str], ...]:
    if uses_legacy_preview_assets(source=source, scene_index=scene_index):
        return _preview_assets(scene_index)
    static_assets = _static_console_preview_assets(source=source, scene_index=scene_index)
    if static_assets:
        return static_assets
    bundle_preview = _base_metric_map_bundle_preview_asset(source=source, scene_index=scene_index)
    if bundle_preview and scene_index in source_ui_indices(source):
        return (("map", bundle_preview),)
    if scene_index in source_ui_indices(source):
        slug = _world_id_slug(f"molmospaces/{source}/{scene_index}")
        return tuple((view, f"/previews/{slug}-{view}.png") for view in _required_views())
    slug = _world_id_slug(f"molmospaces/{source}/{scene_index}")
    return tuple(
        (view, str(_CANONICAL_SCANNER_PREVIEW_ROOT / f"{slug}-{view}.png"))
        for view in _required_views()
    )


def _required_views() -> tuple[str, ...]:
    return ("fpv", "map", "chase", "topdown")


def _static_console_preview_assets(
    *,
    source: str,
    scene_index: int,
) -> tuple[tuple[str, str], ...]:
    slug = _world_id_slug(f"molmospaces/{source}/{scene_index}")
    assets = tuple((view, f"/previews/{slug}-{view}.png") for view in _required_views())
    if all((_PREVIEW_ROOT / Path(path).name).is_file() for _view, path in assets):
        return assets
    return ()


def _base_metric_map_bundle_counts(*, source: str, scene_index: int) -> tuple[int, int]:
    bundle_dir = molmospaces_nav2_map_bundle_path(
        scene_source=source,
        scene_index=scene_index,
    )
    semantics_path = _repo_root() / bundle_dir / "semantics.json"
    try:
        semantics = read_json_object(semantics_path, label="Base Metric Map semantics")
    except (FileNotFoundError, ValueError):
        return (0, 0)
    contract = semantics.get("base_metric_map_contract")
    if not isinstance(contract, dict):
        return (0, 0)
    return (
        int(contract.get("navigation_area_count") or 0),
        int(contract.get("inspection_waypoint_count") or 0),
    )


def _base_metric_map_bundle_preview_asset(*, source: str, scene_index: int) -> str:
    bundle_dir = molmospaces_nav2_map_bundle_path(
        scene_source=source,
        scene_index=scene_index,
    )
    preview_path = _repo_root() / bundle_dir / "preview.png"
    if not preview_path.is_file():
        return ""
    asset_relative = bundle_dir.relative_to(SIM_MAP_BUNDLE_ASSET_ROOT)
    return f"/asset-previews/maps/{asset_relative.as_posix()}/preview.png"


def _family_split(scene_source: str) -> tuple[str, str]:
    if scene_source == "ithor":
        return "ithor", "not_applicable"
    for split in ("-train", "-val", "-test"):
        if scene_source.endswith(split):
            return scene_source[: -len(split)], split.removeprefix("-")
    return scene_source, "not_applicable"


def _scanner_required_gates() -> tuple[str, ...]:
    return scanner_required_gates()


def _scanner_admission_row(candidate: dict[str, Any]) -> dict[str, Any]:
    return scanner_admission_row(candidate=candidate, required_views=_required_views())


def _world_id_slug(world_id: str) -> str:
    return world_id_slug(world_id)


def _scanner_preview_metadata(source: str, scene_index: int) -> dict[str, Any] | None:
    return scanner_preview_metadata(
        source=source,
        scene_index=scene_index,
        preview_root=_SCANNER_PREVIEW_ROOT,
        backend=PRIMARY_MOLMOSPACES_BACKEND,
    )


def _scanner_product_smoke_artifacts(source: str, scene_index: int) -> dict[str, Any]:
    return scanner_product_smoke_artifacts(
        source=source,
        scene_index=scene_index,
        product_smoke_root=_SCANNER_PRODUCT_SMOKE_ROOT,
    )


def _scanner_candidate_packet(
    *,
    packet: dict[str, Any],
    preview: dict[str, Any],
    smoke: dict[str, Any],
) -> dict[str, Any]:
    return scanner_candidate_packet(
        packet=packet,
        preview=preview,
        smoke=smoke,
        preview_root=_SCANNER_PREVIEW_ROOT,
        required_views=_required_views(),
    )


def _sampler_selection_policy() -> dict[str, Any]:
    return {
        "schema": "molmospaces_scene_sampler_selection_policy_v1",
        "selection_seed": SCENE_SAMPLER_SELECTION_SEED,
        "selection_strategy": SCENE_SAMPLER_SELECTION_STRATEGY,
        "ui_target_per_scene_source": UI_TARGET_PER_SCENE_SOURCE,
        "eval_target_per_scene_source": EVAL_TARGET_PER_SCENE_SOURCE,
        "sources": {
            source: {
                "ui": source_selection_metadata(
                    source=source,
                    lane=UI_LANE,
                    target_count=UI_TARGET_PER_SCENE_SOURCE,
                    candidates=SOURCE_UI_CANDIDATE_INDICES.get(source, ()),
                ),
                "eval_stress": source_selection_metadata(
                    source=source,
                    lane=EVAL_STRESS_LANE,
                    target_count=EVAL_TARGET_PER_SCENE_SOURCE,
                    candidates=SOURCE_EVAL_CANDIDATE_INDICES.get(source, ()),
                ),
            }
            for source in SUPPORTED_SCENE_SOURCES
        },
    }


def _rank_selection_candidates(
    *,
    source: str,
    lane: str,
    candidates: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    metadata = source_selection_metadata(
        source=source,
        lane=lane,
        target_count=len(candidates),
        candidates=tuple(int(candidate.get("scene_index") or 0) for candidate in candidates),
    )
    rank = {scene_index: offset for offset, scene_index in enumerate(metadata["selected_indices"])}
    return sorted(
        candidates,
        key=lambda item: (
            rank.get(int(item.get("scene_index") or 0), len(rank)),
            int(item.get("scene_index") or 0),
        ),
    )


def _scanner_execution_candidate_indices(
    *,
    candidate_indices: tuple[int, ...],
    source_prep: dict[str, Any],
) -> tuple[int, ...]:
    indices = {int(index) for index in candidate_indices}
    for source in source_prep.get("sources", {}).values():
        if not isinstance(source, dict):
            continue
        for candidate in source.get("install_candidates") or []:
            if not isinstance(candidate, dict) or candidate.get("scene_index") is None:
                continue
            indices.add(int(candidate["scene_index"]))
    return tuple(sorted(indices))


def _assign_dynamic_candidate_lanes(
    *,
    source: str,
    candidates: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    static_ui_ids = set(source_ui_indices(source))
    static_eval_ids = set(source_eval_indices(source))
    if static_ui_ids or static_eval_ids:
        return _assign_candidate_lanes(
            candidates=candidates,
            ui_ids=static_ui_ids,
            eval_ids=static_eval_ids,
        )
    eligible = [
        candidate
        for candidate in candidates
        if candidate.get("readiness_status") == READINESS_READY
        and candidate.get("eval_ready")
        and candidate.get("scene_index") is not None
    ]
    eligible = _rank_selection_candidates(
        source=source,
        lane=EVAL_STRESS_LANE,
        candidates=eligible,
    )
    ui_ids = {
        int(candidate.get("scene_index") or 0)
        for candidate in _rank_selection_candidates(
            source=source,
            lane=UI_LANE,
            candidates=eligible,
        )[:UI_TARGET_PER_SCENE_SOURCE]
        if len(eligible) >= UI_TARGET_PER_SCENE_SOURCE
    }
    eval_ids = {
        int(candidate.get("scene_index") or 0)
        for candidate in eligible[:EVAL_TARGET_PER_SCENE_SOURCE]
    }
    return _assign_candidate_lanes(
        candidates=candidates,
        ui_ids=ui_ids,
        eval_ids=eval_ids,
    )


def _assign_candidate_lanes(
    *,
    candidates: list[dict[str, Any]],
    ui_ids: set[int],
    eval_ids: set[int],
) -> list[dict[str, Any]]:
    updated: list[dict[str, Any]] = []
    for candidate in candidates:
        scene_index = candidate.get("scene_index")
        lanes: list[str] = []
        if candidate.get("readiness_status") == READINESS_READY and scene_index is not None:
            parsed_index = int(scene_index)
            if parsed_index in ui_ids:
                lanes.append(UI_LANE)
            if parsed_index in eval_ids:
                lanes.append(EVAL_STRESS_LANE)
        updated.append(
            {
                **candidate,
                "lanes": lanes,
                "ui_ready": UI_LANE in lanes,
                "eval_ready": EVAL_STRESS_LANE in lanes,
            }
        )
    return updated


def _scanner_preview_assets(source: str, scene_index: int) -> list[dict[str, str]]:
    return scanner_preview_assets(
        source=source,
        scene_index=scene_index,
        preview_root=_SCANNER_PREVIEW_ROOT,
        required_views=_required_views(),
    )


def _candidate_packet_from_sampler_row(row: SceneSamplerRow) -> dict[str, Any]:
    preview_statuses: dict[str, str] = {}
    if row.scene_index is not None:
        preview_statuses = _view_statuses(
            _ready_row_preview_metadata(source=row.scene_source, scene_index=row.scene_index)
        )
    metadata = (
        scanner_metadata(source=row.scene_source, scene_index=row.scene_index)
        if row.scene_index is not None
        else {}
    )
    return {
        "scene_family": row.scene_family,
        "scene_split": row.scene_split,
        "scene_source": row.scene_source,
        "scene_index": row.scene_index,
        "backend": row.backend,
        "world_id": row.world_id,
        "readiness_status": row.readiness_status,
        "lanes": list(row.lanes),
        "ui_ready": row.ui_ready,
        "eval_ready": row.eval_ready,
        "room_count": row.room_count,
        "waypoint_count": row.waypoint_count,
        "category_provenance": row.category_provenance,
        "category_manifest": row.category_manifest,
        "preview_statuses": preview_statuses,
        "preview_assets": [{"view": view, "path": path} for view, path in row.preview_assets],
        "selected_reason": row.selected_reason,
        "blocked_reason": row.blocked_reason,
        "failure_class": row.failure_class,
        "quality_score": row.quality_score,
        "coverage_score": row.coverage_score,
        "source_outcome": str(metadata.get("source_outcome") or ""),
        "prefilter_status": str(metadata.get("prefilter_status") or ""),
        "prefilter_reason": str(metadata.get("prefilter_reason") or ""),
        "cheap_room_count": int(metadata.get("cheap_room_count") or 0),
        "product_smoke_run_dir": str(metadata.get("product_smoke_run_dir") or ""),
    }


def _blocked_candidate_packet(
    *,
    source: str,
    scene_index: int,
    source_availability: dict[str, Any],
) -> dict[str, Any]:
    family, split = _family_split(source)
    candidate_file = next(
        (
            item
            for item in source_availability.get("candidate_files") or []
            if item.get("scene_index") == scene_index
        ),
        {},
    )
    blocked_reason = str(source_availability.get("blocked_reason") or "")
    if not blocked_reason:
        blocked_reason = (
            f"{source}/{scene_index} has no sampler preview, room, waypoint, or "
            "map-build readiness packet yet; run scene preparation before admission."
        )
    packet = {
        "scene_family": family,
        "scene_split": split,
        "scene_source": source,
        "scene_index": scene_index,
        "backend": PRIMARY_MOLMOSPACES_BACKEND,
        "world_id": f"molmospaces/{source}/{scene_index}",
        "readiness_status": READINESS_BLOCKED,
        "lanes": [],
        "ui_ready": False,
        "eval_ready": False,
        "room_count": 0,
        "waypoint_count": 0,
        "category_provenance": "unavailable",
        "category_manifest": "",
        "preview_statuses": {},
        "preview_assets": [],
        "selected_reason": "blocked_until_candidate_readiness_packet_exists",
        "blocked_reason": blocked_reason,
        "failure_class": "environment_blocked",
        "quality_score": 0.0,
        "coverage_score": 0.0,
        "source_availability_status": source_availability.get("status"),
        "candidate_file": candidate_file,
    }
    if not isinstance(candidate_file, dict) or not candidate_file.get("exists"):
        return packet
    preview = _scanner_preview_metadata(source, scene_index)
    if preview is None:
        return packet
    return _scanner_candidate_packet(
        packet=packet,
        preview=preview,
        smoke=_scanner_product_smoke_artifacts(source, scene_index),
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


def _parse_scene_index(raw_value: str, *, world_id: str) -> int:
    try:
        scene_index = int(raw_value)
    except ValueError as exc:
        raise ValueError(f"unsupported MolmoSpaces scene index {raw_value!r}: {world_id}") from exc
    if scene_index < 0:
        raise ValueError(f"unsupported negative MolmoSpaces scene index {scene_index}: {world_id}")
    return scene_index


def _manifest_rows(payload: dict[str, Any]) -> list[dict[str, Any]]:
    if payload.get("schema") != SAMPLER_MANIFEST_SCHEMA:
        raise ValueError("invalid sampler manifest schema")
    rows = payload.get("rows")
    if not isinstance(rows, list):
        raise ValueError("sampler manifest rows must be a list")
    if not all(isinstance(row, dict) for row in rows):
        raise ValueError("sampler row must be an object")
    return rows


def _validate_sampler_row(
    row: dict[str, Any],
    *,
    label_manifest: dict[str, Any],
) -> str:
    source = str(row.get("scene_source") or "")
    if source not in SUPPORTED_SCENE_SOURCES:
        raise ValueError(f"unsupported scene_source {source!r}")
    status = str(row.get("readiness_status") or "")
    if status == READINESS_READY:
        _validate_ready_row(row, label_manifest=label_manifest)
    elif status == READINESS_BLOCKED:
        _validate_blocked_row(row, source=source)
    elif status != READINESS_REJECTED:
        raise ValueError(f"unknown readiness_status {status!r}")
    return source


def _validate_blocked_row(row: dict[str, Any], *, source: str) -> None:
    if not row.get("blocked_reason") or not row.get("failure_class"):
        raise ValueError(f"blocked sampler row for {source} needs reason and failure_class")


def _validate_source_lane_counts(
    *,
    source: str,
    source_rows: list[dict[str, Any]],
) -> None:
    ui_ready = _rows_in_lane(source_rows, lane=UI_LANE)
    if 0 < len(ui_ready) < 3:
        raise ValueError(f"scene_source {source} exposes fewer than three UI-ready samples")
    if len(ui_ready) > UI_TARGET_PER_SCENE_SOURCE:
        raise ValueError(
            f"scene_source {source} exposes more than {UI_TARGET_PER_SCENE_SOURCE} UI samples"
        )
    eval_ready = _rows_in_lane(source_rows, lane=EVAL_STRESS_LANE)
    if len(eval_ready) > EVAL_TARGET_PER_SCENE_SOURCE:
        raise ValueError(
            f"scene_source {source} exposes more than "
            f"{EVAL_TARGET_PER_SCENE_SOURCE} eval-stress samples"
        )


def _rows_in_lane(source_rows: list[dict[str, Any]], *, lane: str) -> list[dict[str, Any]]:
    return [
        row
        for row in source_rows
        if row.get("readiness_status") == READINESS_READY and lane in row.get("lanes", [])
    ]


def _validate_ready_row(row: dict[str, Any], *, label_manifest: dict[str, Any]) -> None:
    source = str(row.get("scene_source") or "")
    index = row.get("scene_index")
    if not isinstance(index, int):
        raise ValueError(f"ready sampler row for {source} needs integer scene_index")
    if int(row.get("room_count") or 0) < 3:
        raise ValueError(f"{source}/{index} has fewer than three public rooms")
    if int(row.get("waypoint_count") or 0) < int(row.get("room_count") or 0):
        raise ValueError(f"{source}/{index} lacks one waypoint per public room")
    if str(row.get("category_provenance") or "") not in {
        "source_metadata",
        "prepared_visual_label_manifest",
    }:
        raise ValueError(f"{source}/{index} lacks trusted room-category provenance")
    _validate_no_heuristic_category_provenance(row)
    if not _labels_for_scene(label_manifest, source=source, scene_index=index):
        raise ValueError(f"{source}/{index} lacks prepared room labels")
    views = {item.get("view"): item.get("path") for item in row.get("preview_assets") or []}
    if not views.get("map"):
        raise ValueError(f"{source}/{index} lacks Base Metric Map preview path")


def _validate_no_heuristic_category_provenance(row: dict[str, Any]) -> None:
    forbidden = {"heuristic_room_label", "heuristic_room_count", "room_area_fallback"}
    provenance = str(row.get("category_provenance") or "")
    if provenance in forbidden:
        raise ValueError("heuristic room-category provenance cannot satisfy sampler admission")


def _validate_label_manifest(payload: dict[str, Any]) -> None:
    rows = payload.get("labels")
    if not isinstance(rows, list):
        raise ValueError("room label manifest labels must be a list")
    for row in rows:
        if not isinstance(row, dict):
            raise ValueError("room label rows must be objects")
        _validate_no_heuristic_category_provenance(row)
        provenance = str(row.get("category_provenance") or "")
        if provenance not in {"prepared_visual_label_manifest", "source_metadata"}:
            raise ValueError("room label row must use trusted provenance")


def _labels_for_scene(
    payload: dict[str, Any],
    *,
    source: str,
    scene_index: int,
) -> list[dict[str, Any]]:
    return [
        row
        for row in payload.get("labels") or []
        if isinstance(row, dict)
        and row.get("scene_source") == source
        and row.get("scene_index") == scene_index
    ]


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[3]
