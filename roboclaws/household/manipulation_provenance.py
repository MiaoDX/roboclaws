from __future__ import annotations

from typing import Any

from roboclaws.household.manipulation_contract import (
    API_SEMANTIC_PROVENANCE,
    BLOCKED_CAPABILITY_PROVENANCE,
    ISAAC_SEMANTIC_POSE_PROVENANCE,
    MANIPULATION_PROVENANCE_SCHEMA,
    PLANNER_BACKED_PROVENANCE,
)
from roboclaws.household.planner_proof_quality import planner_proof_quality_evidence


def api_semantic_manipulation_evidence(
    *,
    backend: str,
    primitive_summary: dict[str, int] | None = None,
) -> dict[str, Any]:
    """Describe the current cleanup primitive boundary without implying real manipulation."""
    summary = dict(primitive_summary or {})
    return {
        "schema": MANIPULATION_PROVENANCE_SCHEMA,
        "status": API_SEMANTIC_PROVENANCE,
        "primitive_provenance": API_SEMANTIC_PROVENANCE,
        "planner_backed": False,
        "strict_proof_eligible": False,
        "api_semantic_state_edits": True,
        "backend": backend,
        "primitive_provenance_summary": summary,
        "evidence_note": (
            "Cleanup effects are semantic backend state updates. This artifact "
            "does not prove planner-backed robot manipulation."
        ),
        "strict_proof_requirements": planner_backed_proof_requirements(),
    }


def isaac_semantic_pose_manipulation_evidence(
    *,
    backend: str,
    primitive_summary: dict[str, int] | None = None,
) -> dict[str, Any]:
    """Describe Isaac semantic-pose cleanup effects without planner claims."""
    summary = dict(primitive_summary or {})
    return {
        "schema": MANIPULATION_PROVENANCE_SCHEMA,
        "status": ISAAC_SEMANTIC_POSE_PROVENANCE,
        "primitive_provenance": ISAAC_SEMANTIC_POSE_PROVENANCE,
        "planner_backed": False,
        "strict_proof_eligible": False,
        "api_semantic_state_edits": False,
        "isaac_semantic_pose_edits": True,
        "physical_robot": False,
        "backend": backend,
        "primitive_provenance_summary": summary,
        "evidence_note": (
            "Cleanup effects are Isaac backend semantic pose edits over USD prim "
            "state. This artifact does not prove planner-backed manipulation or "
            "physical robot execution."
        ),
        "strict_proof_requirements": planner_backed_proof_requirements(),
    }


def planner_backed_cleanup_manipulation_evidence(
    *,
    backend: str,
    primitive_summary: dict[str, int] | None = None,
) -> dict[str, Any]:
    """Describe cleanup primitives backed by planner evidence with semantic sync."""
    summary = dict(primitive_summary or {})
    return {
        "schema": MANIPULATION_PROVENANCE_SCHEMA,
        "status": PLANNER_BACKED_PROVENANCE,
        "primitive_provenance": PLANNER_BACKED_PROVENANCE,
        "planner_backed": True,
        "strict_proof_eligible": True,
        "api_semantic_state_edits": False,
        "api_semantic_state_sync": True,
        "backend": backend,
        "primitive_provenance_summary": summary,
        "evidence_note": (
            "Cleanup-loop primitives emitted planner-backed per-call evidence. "
            "Semantic backend state sync remains recorded separately from the "
            "planner primitive proof."
        ),
        "strict_proof_requirements": planner_backed_proof_requirements(),
    }


def blocked_planner_probe_evidence(
    *,
    backend: str,
    embodiment: str,
    task: str,
    probe_mode: str,
    blockers: list[dict[str, Any]],
    upstream_policy_class: str | None = None,
    execution_attempted: bool = False,
) -> dict[str, Any]:
    return {
        "schema": MANIPULATION_PROVENANCE_SCHEMA,
        "status": BLOCKED_CAPABILITY_PROVENANCE,
        "primitive_provenance": BLOCKED_CAPABILITY_PROVENANCE,
        "planner_backed": False,
        "strict_proof_eligible": False,
        "api_semantic_state_edits": False,
        "backend": backend,
        "embodiment": embodiment,
        "task": task,
        "probe_mode": probe_mode,
        "upstream_policy_class": upstream_policy_class,
        "execution_attempted": execution_attempted,
        "blockers": blockers,
        "evidence_note": (
            "Planner-backed manipulation was not proven. See blockers and "
            "stdout/stderr artifacts for the capability gap."
        ),
        "strict_proof_requirements": planner_backed_proof_requirements(),
    }


def planner_backed_probe_evidence(
    *,
    backend: str,
    embodiment: str,
    task: str,
    probe_mode: str,
    upstream_policy_class: str,
    steps_requested: int,
    steps_executed: int,
    max_abs_qpos_delta: float,
    image_artifacts: dict[str, str] | None = None,
) -> dict[str, Any]:
    evidence = {
        "schema": MANIPULATION_PROVENANCE_SCHEMA,
        "status": PLANNER_BACKED_PROVENANCE,
        "primitive_provenance": PLANNER_BACKED_PROVENANCE,
        "planner_backed": True,
        "strict_proof_eligible": True,
        "api_semantic_state_edits": False,
        "backend": backend,
        "embodiment": embodiment,
        "task": task,
        "probe_mode": probe_mode,
        "upstream_policy_class": upstream_policy_class,
        "execution_attempted": True,
        "steps_requested": steps_requested,
        "steps_executed": steps_executed,
        "max_abs_qpos_delta": max_abs_qpos_delta,
        "image_artifacts": dict(image_artifacts or {}),
        "blockers": [],
        "evidence_note": (
            "A MolmoSpaces planner policy executed and changed robot state "
            "without an api_semantic state-edit fallback."
        ),
        "strict_proof_requirements": planner_backed_proof_requirements(),
    }
    evidence["proof_quality"] = planner_proof_quality_evidence(evidence)
    return evidence


def planner_backed_proof_requirements() -> list[str]:
    return [
        "planner policy class was instantiated",
        "planner policy execution was attempted",
        "at least one simulation step executed",
        "robot joint/base state changed by a nonzero amount",
        "api_semantic state edits were not used as the manipulation proof",
        "no capability blockers were recorded",
    ]
