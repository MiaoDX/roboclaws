from __future__ import annotations

import pytest

from roboclaws.household.manipulation_contract import MANIPULATION_PROBE_CONTRACT
from roboclaws.household.manipulation_provenance import (
    blocked_planner_probe_evidence,
    planner_backed_probe_evidence,
)
from roboclaws.household.rby1m_curobo_gate import (
    RBY1M_CUROBO_GATE_SCHEMA,
    rby1m_curobo_gate_from_planner_probe,
    validate_rby1m_curobo_gate,
)


def test_rby1m_curobo_gate_accepts_explicit_missing_curobo_blocker() -> None:
    evidence = blocked_planner_probe_evidence(
        backend="molmospaces_subprocess",
        embodiment="rby1m",
        task="pick_and_place",
        probe_mode="config_import",
        blockers=[{"code": "ModuleNotFoundError", "message": "No module named 'curobo'"}],
    )
    evidence["runtime_diagnostics"] = _diagnostics(curobo_available=False)
    gate = rby1m_curobo_gate_from_planner_probe(_run_result(evidence))

    validate_rby1m_curobo_gate(gate, accept_blocked=True)
    assert gate["schema"] == RBY1M_CUROBO_GATE_SCHEMA
    assert gate["status"] == "blocked_capability"
    assert gate["rby1m_curobo_ready"] is False
    assert gate["curobo_available"] is False
    assert "curobo_unavailable" in {item["code"] for item in gate["blockers"]}
    with pytest.raises(AssertionError):
        validate_rby1m_curobo_gate(gate, require_ready=True)


def test_rby1m_curobo_gate_rejects_franka_strict_proof_as_target_ready() -> None:
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
    evidence["runtime_diagnostics"] = _diagnostics(curobo_available=True)
    gate = rby1m_curobo_gate_from_planner_probe(_run_result(evidence, status="planner_backed"))

    validate_rby1m_curobo_gate(gate, accept_blocked=True)
    assert gate["status"] == "blocked_capability"
    assert "wrong_embodiment" in {item["code"] for item in gate["blockers"]}
    with pytest.raises(AssertionError):
        validate_rby1m_curobo_gate(gate, require_ready=True)


def test_rby1m_curobo_gate_accepts_strict_rby1m_ready_evidence() -> None:
    evidence = planner_backed_probe_evidence(
        backend="molmospaces_subprocess",
        embodiment="rby1m",
        task="pick_and_place",
        probe_mode="execute",
        upstream_policy_class="RBY1PickPlacePlannerPolicy",
        steps_requested=2,
        steps_executed=2,
        max_abs_qpos_delta=0.01,
    )
    evidence["runtime_diagnostics"] = _diagnostics(curobo_available=True)
    gate = rby1m_curobo_gate_from_planner_probe(_run_result(evidence, status="planner_backed"))

    validate_rby1m_curobo_gate(gate, require_ready=True)
    assert gate["status"] == "planner_backed"
    assert gate["rby1m_curobo_ready"] is True
    assert not gate["blockers"]


def _diagnostics(*, curobo_available: bool) -> dict[str, object]:
    return {
        "python_version": "3.11.8",
        "modules": {"curobo": {"available": curobo_available, "version": "1.0.0"}},
    }


def _run_result(
    evidence: dict[str, object],
    *,
    status: str = "blocked_capability",
) -> dict[str, object]:
    return {
        "contract": MANIPULATION_PROBE_CONTRACT,
        "status": status,
        "primitive_provenance": status,
        "manipulation_evidence": evidence,
    }
