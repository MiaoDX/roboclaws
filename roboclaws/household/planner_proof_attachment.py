from __future__ import annotations

import shutil
from pathlib import Path
from typing import Any

from roboclaws.core.json_sources import read_json_object
from roboclaws.household.manipulation_contract import (
    MANIPULATION_PROBE_CONTRACT,
    PLANNER_BACKED_PROVENANCE,
    PLANNER_PROOF_ATTACHMENT_SCHEMA,
)
from roboclaws.household.planner_proof_quality import (
    planner_proof_quality_evidence,
    validate_planner_proof_quality_evidence,
)


def attach_planner_proof(
    *,
    proof_run_result_path: Path,
    cleanup_run_dir: Path,
    attachment_id: str | None = None,
) -> dict[str, Any]:
    """Validate and copy a strict planner proof into a cleanup run directory."""
    proof_path = Path(proof_run_result_path)
    proof = read_json_object(proof_path, label="planner proof run result")
    evidence = _strict_planner_evidence(proof)
    copied_images = _copy_proof_images(
        proof_base=proof_path.parent,
        cleanup_run_dir=cleanup_run_dir,
        image_artifacts=evidence.get("image_artifacts") or {},
        attachment_id=attachment_id,
    )
    runtime = evidence.get("runtime_diagnostics") or {}
    worker_payload = evidence.get("worker_payload") or {}
    attachment = {
        "schema": PLANNER_PROOF_ATTACHMENT_SCHEMA,
        "proof_id": attachment_id or "",
        "source_run_result": str(proof_path),
        "contract": proof.get("contract"),
        "status": PLANNER_BACKED_PROVENANCE,
        "primitive_provenance": PLANNER_BACKED_PROVENANCE,
        "planner_backed": True,
        "strict_proof_eligible": True,
        "embodiment": evidence.get("embodiment"),
        "task": evidence.get("task"),
        "probe_mode": evidence.get("probe_mode"),
        "upstream_policy_class": evidence.get("upstream_policy_class"),
        "steps_executed": int(evidence.get("steps_executed") or 0),
        "max_abs_qpos_delta": float(evidence.get("max_abs_qpos_delta") or 0.0),
        "image_artifacts": copied_images,
        "runtime_diagnostics": runtime,
        "renderer_adapter": worker_payload.get("renderer_adapter") or {},
        "evidence_note": (
            "Strict standalone planner-backed manipulation proof attached for "
            "review. Cleanup-loop object moves keep their own primitive provenance."
        ),
    }
    cleanup_binding = _cleanup_primitive_binding(evidence)
    if cleanup_binding:
        attachment["cleanup_primitive_binding"] = cleanup_binding
    attachment["proof_quality"] = planner_proof_quality_evidence(attachment)
    return attachment


def validate_planner_proof_attachment(attachment: dict[str, Any]) -> None:
    """Raise AssertionError if a cleanup planner proof attachment is not strict."""
    assert attachment.get("schema") == PLANNER_PROOF_ATTACHMENT_SCHEMA, attachment
    assert attachment.get("status") == PLANNER_BACKED_PROVENANCE, attachment
    assert attachment.get("primitive_provenance") == PLANNER_BACKED_PROVENANCE, attachment
    assert attachment.get("planner_backed") is True, attachment
    assert attachment.get("strict_proof_eligible") is True, attachment
    assert int(attachment.get("steps_executed") or 0) >= 1, attachment
    assert float(attachment.get("max_abs_qpos_delta") or 0.0) > 0.0, attachment
    validate_planner_proof_quality_evidence(
        planner_proof_quality_evidence(attachment),
        min_steps_executed=1,
    )
    images = attachment.get("image_artifacts") or {}
    assert images.get("initial"), attachment
    assert images.get("final"), attachment


def _strict_planner_evidence(proof: dict[str, Any]) -> dict[str, Any]:
    if proof.get("contract") != MANIPULATION_PROBE_CONTRACT:
        raise ValueError("planner proof attachment must use the planner probe contract")
    if proof.get("status") != PLANNER_BACKED_PROVENANCE:
        raise ValueError("planner proof attachment must have status=planner_backed")
    if proof.get("primitive_provenance") != PLANNER_BACKED_PROVENANCE:
        raise ValueError("planner proof attachment must have primitive_provenance=planner_backed")
    evidence = proof.get("manipulation_evidence") or {}
    try:
        validate_planner_proof_attachment(
            {
                "schema": PLANNER_PROOF_ATTACHMENT_SCHEMA,
                "status": evidence.get("status"),
                "primitive_provenance": evidence.get("primitive_provenance"),
                "planner_backed": evidence.get("planner_backed"),
                "strict_proof_eligible": evidence.get("strict_proof_eligible"),
                "steps_executed": evidence.get("steps_executed"),
                "max_abs_qpos_delta": evidence.get("max_abs_qpos_delta"),
                "image_artifacts": evidence.get("image_artifacts") or {},
            }
        )
    except AssertionError as exc:
        raise ValueError("planner proof attachment is not strict planner-backed evidence") from exc
    if evidence.get("blockers"):
        raise ValueError("planner proof attachment must not contain blockers")
    return evidence


def _copy_proof_images(
    *,
    proof_base: Path,
    cleanup_run_dir: Path,
    image_artifacts: dict[str, str],
    attachment_id: str | None = None,
) -> dict[str, str]:
    copied: dict[str, str] = {}
    destination_dir = cleanup_run_dir / "planner_proof"
    if attachment_id:
        destination_dir = destination_dir / attachment_id
    destination_dir.mkdir(parents=True, exist_ok=True)
    for key in ("initial", "final"):
        value = image_artifacts.get(key)
        if not value:
            continue
        source = _resolve_path(proof_base, value)
        if not source.is_file():
            raise ValueError(f"planner proof image missing: {source}")
        destination = destination_dir / f"{key}_{source.name}"
        shutil.copy2(source, destination)
        copied[key] = str(destination.relative_to(cleanup_run_dir))
    if {"initial", "final"} - set(copied):
        raise ValueError("planner proof attachment requires initial and final proof images")
    return copied


def _resolve_path(base: Path, value: str) -> Path:
    path = Path(value)
    if path.is_absolute():
        return path
    return base / path


def _cleanup_primitive_binding(evidence: dict[str, Any]) -> dict[str, Any]:
    raw = (
        evidence.get("cleanup_primitive_binding") or evidence.get("planner_primitive_binding") or {}
    )
    return dict(raw) if isinstance(raw, dict) else {}
