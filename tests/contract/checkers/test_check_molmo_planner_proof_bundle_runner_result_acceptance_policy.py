from __future__ import annotations

import json
from pathlib import Path

import pytest

from roboclaws.household import planner_proof_bundle_validation
from roboclaws.household.manipulation_provenance import planner_backed_probe_evidence
from tests.contract.checkers.check_molmo_planner_proof_bundle_runner_result_support import (
    _runner_manifest,
    _write_manifest_and_report,
    _write_runner_artifact,
)


def test_checker_can_require_proof_execution_horizon(tmp_path: Path) -> None:
    manifest = _write_runner_artifact(tmp_path)

    planner_proof_bundle_validation.assert_runner_result(
        manifest, tmp_path, require_proof_execution_horizon=True
    )


def test_checker_can_require_proof_quality_for_planner_backed_result(
    tmp_path: Path,
) -> None:
    manifest = _runner_manifest(tmp_path)
    proof_dir = tmp_path / "proofs" / "001_observed_001_to_sink_01"
    views_dir = proof_dir / "planner_views"
    views_dir.mkdir(parents=True)
    (views_dir / "initial.png").write_bytes(b"initial")
    (views_dir / "final.png").write_bytes(b"final")
    (proof_dir / "report.html").write_text("<h1>proof</h1>", encoding="utf-8")
    (proof_dir / "run_result.json").write_text(
        json.dumps(
            {
                "status": "planner_backed",
                "manipulation_evidence": planner_backed_probe_evidence(
                    backend="molmospaces_subprocess",
                    embodiment="rby1m",
                    task="pick_and_place",
                    probe_mode="execute",
                    upstream_policy_class="CuroboPickAndPlacePlannerPolicy",
                    steps_requested=2,
                    steps_executed=2,
                    max_abs_qpos_delta=0.01,
                    image_artifacts={
                        "initial": "planner_views/initial.png",
                        "final": "planner_views/final.png",
                    },
                ),
            }
        ),
        encoding="utf-8",
    )
    _write_manifest_and_report(tmp_path, manifest)

    report = (tmp_path / "report.html").read_text(encoding="utf-8")
    assert "Planner Proof Quality" in report
    assert "multi_step_motion" in report
    planner_proof_bundle_validation.assert_runner_result(
        manifest,
        tmp_path,
        require_proof_outputs=True,
        require_proof_quality=True,
        planner_backed_proof_min_steps=2,
    )
    with pytest.raises(AssertionError):
        planner_proof_bundle_validation.assert_runner_result(
            manifest,
            tmp_path,
            require_proof_outputs=True,
            require_proof_quality=True,
            planner_backed_proof_min_steps=3,
        )
