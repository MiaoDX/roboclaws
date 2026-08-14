from __future__ import annotations

from roboclaws.household.manipulation_contract import (
    API_SEMANTIC_PROVENANCE,
    BLOCKED_CAPABILITY_PROVENANCE,
    PLANNER_BACKED_PROVENANCE,
)
from roboclaws.household.manipulation_provenance import (
    api_semantic_manipulation_evidence,
    blocked_planner_probe_evidence,
    planner_backed_probe_evidence,
)


def test_api_semantic_evidence_is_not_strict_planner_proof() -> None:
    evidence = api_semantic_manipulation_evidence(
        backend="api_semantic_synthetic",
        primitive_summary={API_SEMANTIC_PROVENANCE: 3},
    )

    assert evidence["primitive_provenance"] == API_SEMANTIC_PROVENANCE
    assert evidence["planner_backed"] is False
    assert evidence["strict_proof_eligible"] is False
    assert evidence["api_semantic_state_edits"] is True


def test_blocked_probe_evidence_keeps_api_semantic_false() -> None:
    evidence = blocked_planner_probe_evidence(
        backend="molmospaces_subprocess",
        embodiment="rby1m",
        task="pick_and_place",
        probe_mode="execute",
        blockers=[{"code": "ModuleNotFoundError", "message": "No module named curobo"}],
        execution_attempted=True,
    )

    assert evidence["primitive_provenance"] == BLOCKED_CAPABILITY_PROVENANCE
    assert evidence["planner_backed"] is False
    assert evidence["api_semantic_state_edits"] is False
    assert evidence["blockers"]


def test_planner_backed_probe_evidence_is_strict_proof_eligible() -> None:
    evidence = planner_backed_probe_evidence(
        backend="molmospaces_subprocess",
        embodiment="franka",
        task="pick_and_place",
        probe_mode="execute",
        upstream_policy_class="PickAndPlacePlannerPolicy",
        steps_requested=2,
        steps_executed=2,
        max_abs_qpos_delta=0.01,
    )

    assert evidence["primitive_provenance"] == PLANNER_BACKED_PROVENANCE
    assert evidence["planner_backed"] is True
    assert evidence["strict_proof_eligible"] is True
    assert evidence["api_semantic_state_edits"] is False
