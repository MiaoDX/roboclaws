from __future__ import annotations

from typing import Any

from roboclaws.household.manipulation_contract import (
    BLOCKED_CAPABILITY_PROVENANCE,
    PLANNER_BACKED_PROVENANCE,
    PLANNER_PROOF_ATTACHMENT_SCHEMA,
)
from roboclaws.household.planner_proof_bundle import (
    PLANNER_PROOF_BUNDLE_SCHEMA,
    planner_proof_attachments,
)

PLANNER_CLEANUP_BRIDGE_SCHEMA = "planner_cleanup_bridge_v1"


def planner_cleanup_bridge_evidence(
    *,
    planner_proof_attachment: dict[str, Any] | None,
    cleanup_primitive_evidence: dict[str, Any] | None,
) -> dict[str, Any]:
    """Join target planner proof with cleanup subphase primitive evidence."""
    attachment = dict(planner_proof_attachment or {})
    cleanup_gate = dict(cleanup_primitive_evidence or {})
    target_runtime = _target_runtime_evidence(attachment)
    cleanup_primitives = _cleanup_primitives_evidence(cleanup_gate)
    blockers = []
    if not attachment:
        blockers.append(
            {
                "code": "missing_planner_proof_attachment",
                "message": "Planner cleanup bridge requires an attached strict planner proof.",
            }
        )
    elif not target_runtime["rby1m_curobo_ready"]:
        blockers.append(
            {
                "code": "target_runtime_not_rby1m_curobo_ready",
                "message": (
                    "Attached planner proof is not strict target RBY1M/CuRobo execute evidence."
                ),
            }
        )
    if not cleanup_gate:
        blockers.append(
            {
                "code": "missing_cleanup_primitive_evidence",
                "message": "Planner cleanup bridge requires cleanup primitive gate evidence.",
            }
        )
    elif not cleanup_primitives["planner_backed"]:
        blockers.append(
            {
                "code": "cleanup_subphases_not_planner_backed",
                "message": ("Cleanup subphases are not all primitive_provenance=planner_backed."),
            }
        )
    ready = target_runtime["rby1m_curobo_ready"] and cleanup_primitives["planner_backed"]
    status = PLANNER_BACKED_PROVENANCE if ready and not blockers else BLOCKED_CAPABILITY_PROVENANCE
    return {
        "schema": PLANNER_CLEANUP_BRIDGE_SCHEMA,
        "status": status,
        "primitive_provenance": status,
        "planner_backed": status == PLANNER_BACKED_PROVENANCE,
        "strict_proof_eligible": status == PLANNER_BACKED_PROVENANCE,
        "target_runtime_ready": target_runtime["rby1m_curobo_ready"],
        "cleanup_primitives_ready": cleanup_primitives["planner_backed"],
        "target_runtime": target_runtime,
        "cleanup_primitives": cleanup_primitives,
        "blockers": blockers,
        "evidence_note": (
            "Planner cleanup bridge readiness requires both strict target RBY1M/CuRobo "
            "planner proof and planner-backed cleanup-loop subphases."
        ),
    }


def validate_planner_cleanup_bridge_evidence(
    evidence: dict[str, Any],
    *,
    accept_blocked_capability: bool = False,
    require_ready: bool = False,
) -> None:
    assert evidence.get("schema") == PLANNER_CLEANUP_BRIDGE_SCHEMA, evidence
    assert evidence.get("status") in {
        BLOCKED_CAPABILITY_PROVENANCE,
        PLANNER_BACKED_PROVENANCE,
    }, evidence
    if require_ready:
        assert evidence.get("status") == PLANNER_BACKED_PROVENANCE, evidence
        assert evidence.get("primitive_provenance") == PLANNER_BACKED_PROVENANCE, evidence
        assert evidence.get("planner_backed") is True, evidence
        assert evidence.get("strict_proof_eligible") is True, evidence
        assert evidence.get("target_runtime_ready") is True, evidence
        assert evidence.get("cleanup_primitives_ready") is True, evidence
        assert not evidence.get("blockers"), evidence
        return
    if accept_blocked_capability and evidence.get("status") == BLOCKED_CAPABILITY_PROVENANCE:
        assert evidence.get("planner_backed") is False, evidence
        assert evidence.get("strict_proof_eligible") is False, evidence
        assert evidence.get("blockers"), evidence


def _target_runtime_evidence(attachment: dict[str, Any]) -> dict[str, Any]:
    if attachment.get("schema") == PLANNER_PROOF_BUNDLE_SCHEMA:
        proof_items = [
            _single_target_runtime_evidence(item) for item in planner_proof_attachments(attachment)
        ]
        ready = bool(proof_items) and all(item["rby1m_curobo_ready"] for item in proof_items)
        return {
            "attached": bool(proof_items),
            "schema": PLANNER_PROOF_BUNDLE_SCHEMA,
            "planner_backed": attachment.get("planner_backed") is True,
            "embodiment": "proof_bundle",
            "probe_mode": "execute",
            "task": "multi_proof_cleanup",
            "upstream_policy_class": "proof_bundle",
            "curobo_available": ready,
            "rby1m_curobo_ready": ready,
            "proof_count": len(proof_items),
            "proofs": proof_items,
        }
    return _single_target_runtime_evidence(attachment)


def _single_target_runtime_evidence(attachment: dict[str, Any]) -> dict[str, Any]:
    runtime = attachment.get("runtime_diagnostics") or {}
    modules = runtime.get("modules") or {}
    curobo = modules.get("curobo") or {}
    curobo_available = curobo.get("available") is True
    upstream_policy_class = str(attachment.get("upstream_policy_class") or "")
    ready = (
        attachment.get("schema") == PLANNER_PROOF_ATTACHMENT_SCHEMA
        and attachment.get("planner_backed") is True
        and attachment.get("primitive_provenance") == PLANNER_BACKED_PROVENANCE
        and attachment.get("embodiment") == "rby1m"
        and attachment.get("probe_mode") == "execute"
        and curobo_available
        and "Curobo" in upstream_policy_class
    )
    return {
        "attached": bool(attachment),
        "schema": attachment.get("schema"),
        "planner_backed": attachment.get("planner_backed") is True,
        "embodiment": attachment.get("embodiment"),
        "probe_mode": attachment.get("probe_mode"),
        "task": attachment.get("task"),
        "upstream_policy_class": attachment.get("upstream_policy_class"),
        "curobo_available": curobo_available,
        "rby1m_curobo_ready": ready,
    }


def _cleanup_primitives_evidence(evidence: dict[str, Any]) -> dict[str, Any]:
    return {
        "schema": evidence.get("schema"),
        "status": evidence.get("status"),
        "primitive_provenance": evidence.get("primitive_provenance"),
        "planner_backed": evidence.get("planner_backed") is True,
        "strict_proof_eligible": evidence.get("strict_proof_eligible") is True,
        "object_count": int(evidence.get("object_count") or 0),
        "subphase_count": int(evidence.get("subphase_count") or 0),
        "primitive_provenance_summary": dict(evidence.get("primitive_provenance_summary") or {}),
    }
