from __future__ import annotations

import json
from pathlib import Path

import pytest

from roboclaws.household.manipulation_contract import (
    MANIPULATION_PROBE_CONTRACT,
    PLANNER_BACKED_PROVENANCE,
    PLANNER_PROOF_ATTACHMENT_SCHEMA,
)
from roboclaws.household.manipulation_provenance import (
    planner_backed_probe_evidence,
)
from roboclaws.household.planner_proof_attachment import (
    attach_planner_proof,
    validate_planner_proof_attachment,
)
from roboclaws.household.planner_proof_bundle import (
    PLANNER_PROOF_BUNDLE_SCHEMA,
    attach_planner_proof_bundle,
    planner_proof_attachment_for_target,
    validate_planner_proof_bundle,
)
from roboclaws.household.planner_proof_quality import planner_proof_quality_evidence


def test_attach_planner_proof_validates_and_copies_strict_images(tmp_path: Path) -> None:
    proof_path = _write_strict_planner_proof(tmp_path / "proof")
    cleanup_dir = tmp_path / "cleanup"

    attachment = attach_planner_proof(
        proof_run_result_path=proof_path,
        cleanup_run_dir=cleanup_dir,
    )

    validate_planner_proof_attachment(attachment)
    assert attachment["schema"] == PLANNER_PROOF_ATTACHMENT_SCHEMA
    assert attachment["status"] == PLANNER_BACKED_PROVENANCE
    assert attachment["planner_backed"] is True
    assert attachment["strict_proof_eligible"] is True
    assert attachment["steps_executed"] == 2
    assert attachment["max_abs_qpos_delta"] == 0.01
    assert attachment["proof_quality"]["quality_tier"] == "multi_step_motion"
    assert attachment["proof_quality"]["containment_proven"] is False
    assert (cleanup_dir / attachment["image_artifacts"]["initial"]).is_file()
    assert (cleanup_dir / attachment["image_artifacts"]["final"]).is_file()


def test_attach_planner_proof_rejects_missing_source(tmp_path: Path) -> None:
    proof_path = tmp_path / "proof" / "run_result.json"

    with pytest.raises(FileNotFoundError) as excinfo:
        attach_planner_proof(
            proof_run_result_path=proof_path,
            cleanup_run_dir=tmp_path / "cleanup",
        )

    message = str(excinfo.value)
    assert "planner proof run result source is missing" in message
    assert str(proof_path) in message


def test_attach_planner_proof_rejects_malformed_source(tmp_path: Path) -> None:
    proof_dir = tmp_path / "proof"
    proof_dir.mkdir()
    proof_path = proof_dir / "run_result.json"
    proof_path.write_text("{", encoding="utf-8")

    with pytest.raises(ValueError) as excinfo:
        attach_planner_proof(
            proof_run_result_path=proof_path,
            cleanup_run_dir=tmp_path / "cleanup",
        )

    message = str(excinfo.value)
    assert "planner proof run result source must contain valid JSON object" in message
    assert str(proof_path) in message


def test_attach_planner_proof_rejects_non_object_source(tmp_path: Path) -> None:
    proof_dir = tmp_path / "proof"
    proof_dir.mkdir()
    proof_path = proof_dir / "run_result.json"
    proof_path.write_text("[]", encoding="utf-8")

    with pytest.raises(ValueError) as excinfo:
        attach_planner_proof(
            proof_run_result_path=proof_path,
            cleanup_run_dir=tmp_path / "cleanup",
        )

    message = str(excinfo.value)
    assert "planner proof run result source must contain a JSON object" in message
    assert str(proof_path) in message


def test_attach_planner_proof_rejects_non_strict_probe(tmp_path: Path) -> None:
    proof_path = _write_strict_planner_proof(tmp_path / "proof")
    data = json.loads(proof_path.read_text(encoding="utf-8"))
    data["manipulation_evidence"]["max_abs_qpos_delta"] = 0.0
    proof_path.write_text(json.dumps(data), encoding="utf-8")

    with pytest.raises(ValueError, match="not strict planner-backed evidence"):
        attach_planner_proof(
            proof_run_result_path=proof_path,
            cleanup_run_dir=tmp_path / "cleanup",
        )


def test_attach_planner_proof_preserves_cleanup_primitive_binding(tmp_path: Path) -> None:
    binding = {
        "schema": "planner_probe_cleanup_primitive_binding_v1",
        "object_id": "observed_001",
        "target_receptacle_id": "sink_01",
        "tools": ["navigate_to_object", "pick", "navigate_to_receptacle", "place"],
    }
    proof_path = _write_strict_planner_proof(tmp_path / "proof", cleanup_binding=binding)

    attachment = attach_planner_proof(
        proof_run_result_path=proof_path,
        cleanup_run_dir=tmp_path / "cleanup",
    )

    assert attachment["cleanup_primitive_binding"] == binding
    assert attachment["proof_quality"]["cleanup_primitive_binding_present"] is True


def test_attach_planner_proof_classifies_one_step_motion(tmp_path: Path) -> None:
    proof_path = _write_strict_planner_proof(
        tmp_path / "proof",
        steps_executed=1,
        max_abs_qpos_delta=0.018,
    )

    attachment = attach_planner_proof(
        proof_run_result_path=proof_path,
        cleanup_run_dir=tmp_path / "cleanup",
    )

    quality = planner_proof_quality_evidence(attachment)
    assert quality["quality_tier"] == "one_step_motion"
    assert quality["one_step_motion"] is True
    assert quality["multi_step_motion"] is False
    assert quality["containment_proven"] is False


def test_attach_planner_proof_bundle_keeps_distinct_bound_proofs(tmp_path: Path) -> None:
    first_binding = {
        "schema": "planner_probe_cleanup_primitive_binding_v1",
        "object_id": "observed_001",
        "target_receptacle_id": "sink_01",
        "tools": ["navigate_to_object", "pick", "navigate_to_receptacle", "place"],
    }
    second_binding = {
        "schema": "planner_probe_cleanup_primitive_binding_v1",
        "object_id": "observed_002",
        "target_receptacle_id": "toy_bin_01",
        "tools": ["navigate_to_object", "pick", "navigate_to_receptacle", "place"],
    }
    proof_paths = [
        _write_strict_planner_proof(tmp_path / "proof-1", cleanup_binding=first_binding),
        _write_strict_planner_proof(tmp_path / "proof-2", cleanup_binding=second_binding),
    ]
    cleanup_dir = tmp_path / "cleanup"

    bundle = attach_planner_proof_bundle(
        proof_run_result_paths=proof_paths,
        cleanup_run_dir=cleanup_dir,
    )

    validate_planner_proof_bundle(bundle)
    assert bundle["schema"] == PLANNER_PROOF_BUNDLE_SCHEMA
    assert bundle["proof_count"] == 2
    assert bundle["proof_quality_summary"]["quality_tier_counts"] == {"multi_step_motion": 2}
    attachments = bundle["attachments"]
    assert attachments[0]["proof_id"] == "proof_001"
    assert attachments[1]["proof_id"] == "proof_002"
    assert attachments[0]["cleanup_primitive_binding"] == first_binding
    assert attachments[1]["cleanup_primitive_binding"] == second_binding
    assert attachments[0]["image_artifacts"]["initial"].startswith("planner_proof/proof_001/")
    assert attachments[1]["image_artifacts"]["initial"].startswith("planner_proof/proof_002/")
    matched = planner_proof_attachment_for_target(
        bundle,
        object_id="observed_002",
        target_receptacle_id="toy_bin_01",
    )
    assert matched is not None
    assert matched["proof_id"] == "proof_002"


def _write_strict_planner_proof(
    base: Path,
    *,
    cleanup_binding: dict[str, object] | None = None,
    steps_executed: int = 2,
    max_abs_qpos_delta: float = 0.01,
) -> Path:
    base.mkdir(parents=True)
    views = base / "planner_views"
    views.mkdir()
    (views / "initial_wrist_camera.png").write_bytes(b"initial")
    (views / "final_wrist_camera.png").write_bytes(b"final")
    evidence = planner_backed_probe_evidence(
        backend="molmospaces_subprocess",
        embodiment="franka",
        task="pick_and_place",
        probe_mode="execute",
        upstream_policy_class="PickAndPlacePlannerPolicy",
        steps_requested=2,
        steps_executed=steps_executed,
        max_abs_qpos_delta=max_abs_qpos_delta,
        image_artifacts={
            "initial": "planner_views/initial_wrist_camera.png",
            "final": "planner_views/final_wrist_camera.png",
        },
    )
    evidence["runtime_diagnostics"] = {"renderer_adapter_enabled": True}
    evidence["worker_payload"] = {"renderer_adapter": {"camera": "wrist"}}
    if cleanup_binding is not None:
        evidence["cleanup_primitive_binding"] = cleanup_binding
    data = {
        "contract": MANIPULATION_PROBE_CONTRACT,
        "status": PLANNER_BACKED_PROVENANCE,
        "primitive_provenance": PLANNER_BACKED_PROVENANCE,
        "manipulation_evidence": evidence,
    }
    path = base / "run_result.json"
    path.write_text(json.dumps(data), encoding="utf-8")
    return path
