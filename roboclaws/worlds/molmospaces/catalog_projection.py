"""Eval and catalog projections for the MolmoSpaces scene sampler."""

from __future__ import annotations

from typing import Any

from roboclaws.worlds.molmospaces.contracts import (
    EVAL_STRESS_LANE,
    READINESS_BLOCKED,
    READINESS_REJECTED,
    SAMPLER_GENERATOR_VERSION,
    SceneSamplerRow,
)
from roboclaws.worlds.molmospaces.sampling import (
    EVAL_TARGET_PER_SCENE_SOURCE,
    SAMPLER_PROJECTION_SCHEMA,
    SUPPORTED_SCENE_SOURCES,
    _sampler_selection_policy,
    eval_sample_id,
    eval_sampler_rows,
    sampler_rows,
)


def eval_sample_ref(row: SceneSamplerRow) -> str:
    if row.scene_index is None:
        return ""
    return (
        "evals/household_world/samples/scene_sampler/"
        f"{row.scene_source}_{row.scene_index}_map_build.json"
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
