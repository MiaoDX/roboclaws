from __future__ import annotations

from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

from roboclaws.household.manipulation_contract import (
    PLANNER_BACKED_PROVENANCE,
    PLANNER_PROOF_ATTACHMENT_SCHEMA,
)
from roboclaws.household.planner_probe_primitive_executor import (
    cleanup_primitive_binding_from_attachment,
)
from roboclaws.household.planner_proof_attachment import (
    attach_planner_proof,
    validate_planner_proof_attachment,
)
from roboclaws.household.planner_proof_quality import planner_proof_quality_summary

PLANNER_PROOF_BUNDLE_SCHEMA = "planner_backed_cleanup_proof_bundle_v1"


def attach_planner_proof_bundle(
    *,
    proof_run_result_paths: Sequence[Path],
    cleanup_run_dir: Path,
) -> dict[str, Any]:
    """Attach multiple strict planner proofs to one cleanup artifact."""
    proof_paths = [Path(path) for path in proof_run_result_paths]
    if not proof_paths:
        raise ValueError("planner proof bundle requires at least one proof run result")
    attachments = []
    for index, proof_path in enumerate(proof_paths, start=1):
        proof_id = f"proof_{index:03d}"
        attachment = attach_planner_proof(
            proof_run_result_path=proof_path,
            cleanup_run_dir=cleanup_run_dir,
            attachment_id=proof_id,
        )
        attachment["proof_id"] = proof_id
        attachments.append(attachment)
    bundle = {
        "schema": PLANNER_PROOF_BUNDLE_SCHEMA,
        "status": PLANNER_BACKED_PROVENANCE,
        "primitive_provenance": PLANNER_BACKED_PROVENANCE,
        "planner_backed": True,
        "strict_proof_eligible": True,
        "proof_count": len(attachments),
        "attachments": attachments,
        "cleanup_primitive_bindings": [
            cleanup_primitive_binding_from_attachment(attachment) for attachment in attachments
        ],
        "proof_quality_summary": planner_proof_quality_summary(attachments),
        "evidence_note": (
            "Multiple strict planner-backed manipulation proofs attached for cleanup "
            "primitive coverage. Each cleanup object must match its own proof binding."
        ),
    }
    validate_planner_proof_bundle(bundle)
    return bundle


def validate_planner_proof_bundle(bundle: Mapping[str, Any]) -> None:
    assert bundle.get("schema") == PLANNER_PROOF_BUNDLE_SCHEMA, bundle
    assert bundle.get("status") == PLANNER_BACKED_PROVENANCE, bundle
    assert bundle.get("primitive_provenance") == PLANNER_BACKED_PROVENANCE, bundle
    assert bundle.get("planner_backed") is True, bundle
    assert bundle.get("strict_proof_eligible") is True, bundle
    attachments = planner_proof_attachments(bundle)
    assert attachments, bundle
    assert int(bundle.get("proof_count") or 0) == len(attachments), bundle
    for attachment in attachments:
        validate_planner_proof_attachment(attachment)


def planner_proof_attachments(proof_evidence: Mapping[str, Any]) -> list[dict[str, Any]]:
    if proof_evidence.get("schema") == PLANNER_PROOF_ATTACHMENT_SCHEMA:
        return [dict(proof_evidence)]
    if proof_evidence.get("schema") != PLANNER_PROOF_BUNDLE_SCHEMA:
        return []
    raw = proof_evidence.get("attachments") or []
    return [dict(item) for item in raw if isinstance(item, Mapping)]


def planner_proof_attachment_for_target(
    proof_evidence: Mapping[str, Any],
    *,
    object_id: str,
    target_receptacle_id: str,
) -> dict[str, Any] | None:
    for attachment in planner_proof_attachments(proof_evidence):
        binding = cleanup_primitive_binding_from_attachment(attachment)
        if _binding_matches_target(binding, object_id, target_receptacle_id):
            return attachment
    return None


def _binding_matches_target(
    binding: Mapping[str, Any],
    object_id: str,
    target_receptacle_id: str,
) -> bool:
    return (
        bool(binding)
        and str(binding.get("object_id") or "") == object_id
        and str(binding.get("target_receptacle_id") or "") == target_receptacle_id
    )
