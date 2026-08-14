from __future__ import annotations

import json
from pathlib import Path

import pytest

from roboclaws.household.planner_proof_results import proof_result_summary_from_commands
from roboclaws.household.report_planner import render_planner_proof_bundle_runner_report
from tests.contract.checkers.check_molmo_planner_proof_bundle_runner_result_support import (
    _load_checker,
    _runner_manifest,
    _write_manifest_and_report,
    _write_runner_artifact,
)


def test_checker_can_require_prior_covered_exclusion(tmp_path: Path) -> None:
    checker = _load_checker()
    manifest = _runner_manifest(tmp_path)
    manifest["commands"] = []
    manifest["command_count"] = 0
    manifest["proof_request_selection"] = {
        "schema": "planner_cleanup_proof_request_selection_v1",
        "mode": "exclude_prior_covered",
        "ready_request_count": 1,
        "selected_count": 0,
        "excluded_count": 1,
        "covered_request_count": 1,
        "generated_fallback_request_count": 0,
        "fallback_required": True,
        "selected_request_ids": [],
        "selected_requests": [],
        "excluded_requests": [
            {
                "request_id": "proof_001",
                "object_id": "observed_001",
                "target_receptacle_id": "sink_01",
                "reason": "prior_planner_proof_covered",
                "prior_status": "planner_backed",
                "prior_task_feasibility_status": "ready",
                "prior_result_match_kind": "request_id",
                "prior_blockers": [],
            }
        ],
        "target_feasibility_blocker_count": 0,
        "target_feasibility_blockers": [],
        "grasp_feasibility_blocker_count": 0,
        "grasp_feasibility_blockers": [],
        "fallback_generation": {
            "schema": "planner_cleanup_proof_request_fallback_generation_v1",
            "status": "disabled",
            "enabled": False,
            "generated_request_count": 0,
            "generated_requests": [],
            "filtered_alias_count": 0,
            "filtered_aliases": [],
            "discovered_alias_count": 0,
            "discovered_aliases": [],
            "filtered_pair_count": 0,
            "filtered_pairs": [],
            "normalized_alias_count": 0,
            "normalized_aliases": [],
        },
    }
    manifest["proof_result_summary"] = proof_result_summary_from_commands([])
    (tmp_path / "proof_bundle_run_manifest.json").write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    render_planner_proof_bundle_runner_report(output_dir=tmp_path, manifest=manifest)

    checker._assert_runner_result(
        manifest,
        tmp_path,
        max_selected_requests=0,
        require_prior_covered_exclusion=True,
    )


def test_checker_can_require_expected_proof_outputs(tmp_path: Path) -> None:
    checker = _load_checker()
    manifest = _write_runner_artifact(tmp_path)

    with pytest.raises(AssertionError):
        checker._assert_runner_result(manifest, tmp_path, require_proof_outputs=True)

    proof_dir = tmp_path / "proofs" / "001_observed_001_to_sink_01"
    proof_dir.mkdir(parents=True, exist_ok=True)
    (proof_dir / "run_result.json").write_text("{}", encoding="utf-8")
    (proof_dir / "report.html").write_text("<h1>proof</h1>", encoding="utf-8")
    manifest["proof_result_summary"] = proof_result_summary_from_commands(manifest["commands"])
    _write_manifest_and_report(tmp_path, manifest)

    checker._assert_runner_result(manifest, tmp_path, require_proof_outputs=True)
