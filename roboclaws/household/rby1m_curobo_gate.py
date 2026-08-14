from __future__ import annotations

from typing import Any

from roboclaws.household.manipulation_contract import (
    BLOCKED_CAPABILITY_PROVENANCE,
    PLANNER_BACKED_PROVENANCE,
)

RBY1M_CUROBO_GATE_SCHEMA = "rby1m_curobo_runtime_gate_v1"
RBY1M_EMBODIMENT = "rby1m"


def rby1m_curobo_gate_from_planner_probe(run_result: dict[str, Any]) -> dict[str, Any]:
    """Summarize whether a planner probe proves target RBY1M/CuRobo readiness."""
    evidence = run_result.get("manipulation_evidence") or {}
    runtime_diagnostics = evidence.get("runtime_diagnostics") or {}
    modules = runtime_diagnostics.get("modules") or {}
    curobo = modules.get("curobo") or {}
    embodiment = str(evidence.get("embodiment") or "")
    probe_mode = str(evidence.get("probe_mode") or "")
    execution_attempted = evidence.get("execution_attempted") is True
    planner_backed = (
        run_result.get("status") == PLANNER_BACKED_PROVENANCE
        and run_result.get("primitive_provenance") == PLANNER_BACKED_PROVENANCE
        and evidence.get("planner_backed") is True
        and evidence.get("strict_proof_eligible") is True
    )
    curobo_available = curobo.get("available") is True
    upstream_blockers = list(evidence.get("blockers") or [])
    gate_blockers = _gate_blockers(
        embodiment=embodiment,
        curobo_available=curobo_available,
        execution_attempted=execution_attempted,
        planner_backed=planner_backed,
        upstream_blockers=upstream_blockers,
    )
    ready = not gate_blockers
    status = PLANNER_BACKED_PROVENANCE if ready else BLOCKED_CAPABILITY_PROVENANCE
    return {
        "schema": RBY1M_CUROBO_GATE_SCHEMA,
        "status": status,
        "primitive_provenance": status,
        "rby1m_curobo_ready": ready,
        "embodiment": embodiment,
        "probe_mode": probe_mode,
        "curobo_available": curobo_available,
        "curobo_version": curobo.get("version"),
        "execution_attempted": execution_attempted,
        "planner_backed": planner_backed,
        "strict_proof_eligible": ready,
        "upstream_policy_class": evidence.get("upstream_policy_class"),
        "worker_returncode": evidence.get("worker_returncode"),
        "upstream_blockers": upstream_blockers,
        "blockers": gate_blockers,
        "evidence_note": (
            "RBY1M/CuRobo readiness requires an rby1m planner probe with CuRobo "
            "available, execution attempted, planner_backed provenance, and no "
            "capability blockers. Standalone Franka proof does not satisfy this gate."
        ),
    }


def validate_rby1m_curobo_gate(
    gate: dict[str, Any],
    *,
    require_ready: bool = False,
    accept_blocked: bool = False,
) -> None:
    assert gate.get("schema") == RBY1M_CUROBO_GATE_SCHEMA, gate
    if require_ready:
        assert gate.get("status") == PLANNER_BACKED_PROVENANCE, gate
        assert gate.get("primitive_provenance") == PLANNER_BACKED_PROVENANCE, gate
        assert gate.get("rby1m_curobo_ready") is True, gate
        assert gate.get("embodiment") == RBY1M_EMBODIMENT, gate
        assert gate.get("curobo_available") is True, gate
        assert gate.get("execution_attempted") is True, gate
        assert gate.get("planner_backed") is True, gate
        assert gate.get("strict_proof_eligible") is True, gate
        assert not gate.get("blockers"), gate
        return
    if accept_blocked:
        assert gate.get("status") in {
            BLOCKED_CAPABILITY_PROVENANCE,
            PLANNER_BACKED_PROVENANCE,
        }, gate
        if gate.get("status") == BLOCKED_CAPABILITY_PROVENANCE:
            assert gate.get("rby1m_curobo_ready") is False, gate
            assert gate.get("blockers"), gate


def _gate_blockers(
    *,
    embodiment: str,
    curobo_available: bool,
    execution_attempted: bool,
    planner_backed: bool,
    upstream_blockers: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    blockers = [dict(item) for item in upstream_blockers]
    if embodiment != RBY1M_EMBODIMENT:
        blockers.append(
            {
                "code": "wrong_embodiment",
                "message": (
                    f"RBY1M/CuRobo readiness requires embodiment={RBY1M_EMBODIMENT}; "
                    f"got {embodiment or 'unknown'}."
                ),
            }
        )
    if not curobo_available:
        blockers.append(
            {
                "code": "curobo_unavailable",
                "message": "CuRobo is not available in planner runtime diagnostics.",
            }
        )
    if not execution_attempted:
        blockers.append(
            {
                "code": "rby1m_execution_not_attempted",
                "message": "RBY1M planner execution was not attempted.",
            }
        )
    if not planner_backed:
        blockers.append(
            {
                "code": "rby1m_planner_not_backed",
                "message": "Planner probe did not produce strict planner_backed evidence.",
            }
        )
    return blockers
