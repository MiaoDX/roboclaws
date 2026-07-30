from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

from roboclaws.household.planner_proof_results import proof_result_summary_from_commands
from roboclaws.household.planner_proof_selection import proof_request_selection_from_summary
from roboclaws.household.report_planner import render_planner_proof_bundle_runner_report
from tests.contract.checkers.check_molmo_planner_proof_bundle_runner_result_support import (
    _load_checker,
    _runner_manifest,
    _write_manifest_and_report,
    _write_runner_artifact,
)


def test_checker_accepts_valid_runner_artifact(tmp_path: Path) -> None:
    checker = _load_checker()
    manifest = _write_runner_artifact(tmp_path)

    checker._assert_runner_result(manifest, tmp_path)


def test_checker_accepts_directory_path_via_main(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    checker = _load_checker()
    _write_runner_artifact(tmp_path)
    monkeypatch.setattr(
        sys,
        "argv",
        ["check_molmo_planner_proof_bundle_runner_result.py", str(tmp_path)],
    )

    checker.main()

    assert "molmo-planner-proof-bundle-runner ok" in capsys.readouterr().out


def test_checker_accepts_paths_relative_to_current_working_dir(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    checker = _load_checker()
    monkeypatch.chdir(tmp_path)
    base = Path("bundle")
    base.mkdir()
    manifest = _write_runner_artifact(base)

    checker._assert_runner_result(manifest, base)


def test_checker_accepts_generated_fallback_commands(tmp_path: Path) -> None:
    checker = _load_checker()
    manifest = _runner_manifest(tmp_path)
    manifest["ready_request_count"] = 0
    manifest["commands"][0]["request_id"] = "proof_001_fallback_01"
    manifest["commands"][0]["command"].extend(
        [
            "--cleanup-planner-object-id",
            "pickup/alt",
            "--cleanup-planner-target-receptacle-id",
            "sink/alt",
        ]
    )
    manifest["proof_request_selection"] = {
        "schema": "planner_cleanup_proof_request_selection_v1",
        "mode": "exclude_task_feasibility_blocked_with_fallbacks",
        "ready_request_count": 1,
        "selected_count": 1,
        "excluded_count": 1,
        "generated_fallback_request_count": 1,
        "fallback_required": False,
        "selected_request_ids": ["proof_001_fallback_01"],
        "selected_requests": [
            {
                "request_id": "proof_001_fallback_01",
                "request_type": "fallback_generated",
                "source_request_id": "proof_001",
                "object_id": "observed_001",
                "target_receptacle_id": "sink_01",
                "prior_task_feasibility_status": "blocked",
                "prior_task_feasibility_blocker_kind": "grasp_feasibility",
                "prior_result_match_kind": "request_id",
            }
        ],
        "excluded_requests": [
            {
                "request_id": "proof_001",
                "object_id": "observed_001",
                "target_receptacle_id": "sink_01",
                "reason": "prior_task_feasibility_blocked",
                "prior_task_feasibility_status": "blocked",
                "prior_task_feasibility_blocker_kind": "grasp_feasibility",
                "prior_task_feasibility_blocker_summary": (
                    "3 grasp failures; 1 candidate-removal calls"
                ),
                "prior_result_match_kind": "request_id",
                "prior_blockers": [{"code": "HouseInvalidForTask"}],
            }
        ],
        "target_feasibility_blocker_count": 2,
        "target_feasibility_blockers": [
            {
                "kind": "source_request",
                "source_request_id": "proof_001",
                "object_id": "observed_001",
                "target_receptacle_id": "sink_01",
                "reason": "prior_task_feasibility_blocked",
                "prior_task_feasibility_status": "blocked",
                "prior_task_feasibility_blocker_kind": "grasp_feasibility",
                "prior_task_feasibility_blocker_summary": (
                    "3 grasp failures; 1 candidate-removal calls"
                ),
                "prior_result_match_kind": "request_id",
                "prior_blockers": [{"code": "HouseInvalidForTask"}],
            },
            {
                "kind": "fallback_pair",
                "source_request_id": "proof_001",
                "object_alias": "pickup/body",
                "target_alias": "sink/body_alt",
                "derived_from": "proof_001_fallback_02",
                "reason": "prior_task_feasibility_blocked_pair",
                "prior_task_feasibility_status": "blocked",
                "prior_task_feasibility_blocker_kind": "grasp_feasibility",
                "prior_task_feasibility_blocker_summary": (
                    "3 grasp failures; 1 candidate-removal calls"
                ),
                "prior_result_match_kind": "request_id",
                "last_worker_stage": "worker_exception",
                "prior_report": str(tmp_path / "prior-proof" / "report.html"),
                "prior_blockers": [{"code": "HouseInvalidForTask"}],
            },
        ],
        "grasp_feasibility_blocker_count": 2,
        "grasp_feasibility_blockers": [
            {
                "kind": "source_request",
                "source_request_id": "proof_001",
                "object_id": "observed_001",
                "target_receptacle_id": "sink_01",
                "reason": "prior_task_feasibility_blocked",
                "prior_task_feasibility_status": "blocked",
                "prior_task_feasibility_blocker_kind": "grasp_feasibility",
                "prior_task_feasibility_blocker_summary": (
                    "3 grasp failures; 1 candidate-removal calls"
                ),
                "prior_result_match_kind": "request_id",
                "prior_blockers": [{"code": "HouseInvalidForTask"}],
            },
            {
                "kind": "fallback_pair",
                "source_request_id": "proof_001",
                "object_alias": "pickup/body",
                "target_alias": "sink/body_alt",
                "derived_from": "proof_001_fallback_02",
                "reason": "prior_task_feasibility_blocked_pair",
                "prior_task_feasibility_status": "blocked",
                "prior_task_feasibility_blocker_kind": "grasp_feasibility",
                "prior_task_feasibility_blocker_summary": (
                    "3 grasp failures; 1 candidate-removal calls"
                ),
                "prior_result_match_kind": "request_id",
                "last_worker_stage": "worker_exception",
                "prior_report": str(tmp_path / "prior-proof" / "report.html"),
                "prior_blockers": [{"code": "HouseInvalidForTask"}],
            },
        ],
        "fallback_generation": {
            "schema": "planner_cleanup_proof_request_fallback_generation_v1",
            "status": "generated",
            "enabled": True,
            "generated_request_count": 1,
            "discovered_alias_count": 1,
            "filtered_alias_count": 1,
            "filtered_pair_count": 1,
            "generated_requests": [
                {
                    "request_id": "proof_001_fallback_01",
                    "source_request_id": "proof_001",
                    "ready": True,
                    "object_id": "observed_001",
                    "target_receptacle_id": "sink_01",
                    "planner_probe_args": {
                        "--cleanup-planner-object-id": "pickup/alt",
                        "--cleanup-planner-target-receptacle-id": "sink/alt",
                    },
                    "fallback_request": {
                        "source_request_id": "proof_001",
                        "reason": "prior_task_feasibility_blocked",
                        "prior_task_feasibility_blocker_kind": "grasp_feasibility",
                        "prior_task_feasibility_blocker_summary": (
                            "3 grasp failures; 1 candidate-removal calls"
                        ),
                        "prior_result_match_kind": "request_id",
                        "prior_blockers": [{"code": "HouseInvalidForTask"}],
                    },
                }
            ],
            "discovered_aliases": [
                {
                    "source_request_id": "proof_001",
                    "axis": "target",
                    "alias": "sink/alt",
                    "derived_from": "proof_001_fallback_01",
                    "invalid_alias": "Sink|1|2",
                    "reason": "valid_name_sibling_from_prior_keyerror",
                }
            ],
            "filtered_aliases": [
                {
                    "source_request_id": "proof_001",
                    "axis": "target",
                    "alias": "Sink|1|2",
                    "reason": "not_exact_scene_runtime_alias",
                }
            ],
            "filtered_pairs": [
                {
                    "source_request_id": "proof_001",
                    "object_alias": "pickup/body",
                    "target_alias": "sink/body_alt",
                    "derived_from": "proof_001_fallback_02",
                    "reason": "prior_task_feasibility_blocked_pair",
                    "prior_task_feasibility_blocker_kind": "grasp_feasibility",
                    "prior_task_feasibility_blocker_summary": (
                        "3 grasp failures; 1 candidate-removal calls"
                    ),
                    "prior_result_match_kind": "request_id",
                    "prior_blockers": [{"code": "HouseInvalidForTask"}],
                }
            ],
        },
    }
    manifest["prior_proof_result_summary"] = {
        "schema": "merged_prior_planner_proof_result_summary_v1",
        "result_count": 1,
        "view_artifact_count": 1,
        "results": [
            {
                "request_id": "standalone_observed_001_to_shelf_01",
                "object_id": "observed_001",
                "target_receptacle_id": "shelf_01",
                "run_result": str(tmp_path / "prior-proof" / "run_result.json"),
                "report": str(tmp_path / "prior-proof" / "report.html"),
                "status": "blocked_capability",
                "task_feasibility_status": "blocked",
                "task_feasibility_blocker_kind": "grasp_feasibility",
                "task_feasibility_blocker_summary": (
                    "17 grasp failures; 15 candidate-removal calls"
                ),
                "grasp_feasibility_signature": {
                    "schema": "planner_grasp_feasibility_signature_v1",
                    "kind": "grasp_feasibility",
                    "subkind": "grasp_cache_missing",
                    "pattern_key": "prior-grasp-cache-missing",
                    "summary": (
                        "17 grasp failures; 15 candidate-removal calls; "
                        "17 grasp-load failures; missing grasp cache: PriorBread_1"
                    ),
                    "grasp_failure_count": 17,
                    "candidate_removal_count": 15,
                    "grasp_load_attempt_count": 17,
                    "grasp_load_failure_count": 17,
                    "grasp_collision_check_count": 0,
                    "zero_noncolliding_grasp_check_count": 0,
                    "grasp_load_exception_asset_uids": ["PriorBread_1"],
                    "grasp_load_exception_types": ["ValueError"],
                    "robot_placement_attempt_count": 17,
                    "robot_placement_failure_count": 0,
                    "place_robot_near_call_count": 17,
                    "object_name_count": 1,
                    "object_names": ["prior/pickup"],
                    "image_artifact_count": 1,
                },
                "views": [
                    {
                        "label": "final",
                        "path": str(tmp_path / "prior-proof" / "final.png"),
                    }
                ],
            }
        ],
    }
    manifest["proof_result_summary"] = proof_result_summary_from_commands(manifest["commands"])
    (tmp_path / "proof_bundle_run_manifest.json").write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    render_planner_proof_bundle_runner_report(output_dir=tmp_path, manifest=manifest)

    report = (tmp_path / "report.html").read_text(encoding="utf-8")
    assert 'src="prior-proof/final.png"' in report
    assert f'src="{tmp_path}/prior-proof/final.png"' not in report
    assert "PriorBread_1" in report
    checker._assert_runner_result(manifest, tmp_path)


def test_checker_accepts_partial_selection_with_exhausted_fallbacks(tmp_path: Path) -> None:
    checker = _load_checker()
    manifest = _runner_manifest(tmp_path)
    manifest["commands"][0]["request_id"] = "proof_002"
    manifest["commands"][0]["object_id"] = "observed_002"
    manifest["commands"][0]["target_receptacle_id"] = "sink_02"
    manifest["proof_request_selection"] = {
        "schema": "planner_cleanup_proof_request_selection_v1",
        "mode": "exclude_task_feasibility_blocked_with_fallbacks",
        "ready_request_count": 2,
        "selected_count": 1,
        "excluded_count": 1,
        "generated_fallback_request_count": 0,
        "fallback_required": False,
        "selected_request_ids": ["proof_002"],
        "selected_requests": [
            {
                "request_id": "proof_002",
                "request_type": "source",
                "source_request_id": "",
                "object_id": "observed_002",
                "target_receptacle_id": "sink_02",
                "prior_task_feasibility_status": "unknown",
            }
        ],
        "excluded_requests": [
            {
                "request_id": "proof_001",
                "object_id": "observed_001",
                "target_receptacle_id": "shelf_01",
                "reason": "prior_task_feasibility_blocked",
                "prior_task_feasibility_status": "blocked",
                "prior_task_feasibility_blocker_kind": "grasp_feasibility",
                "prior_task_feasibility_blocker_summary": (
                    "17 grasp failures; 15 candidate-removal calls"
                ),
                "prior_result_match_kind": "object_target",
                "prior_blockers": [{"code": "HouseInvalidForTask"}],
            }
        ],
        "target_feasibility_blocker_count": 1,
        "target_feasibility_blockers": [
            {
                "kind": "source_request",
                "source_request_id": "proof_001",
                "object_id": "observed_001",
                "target_receptacle_id": "shelf_01",
                "reason": "prior_task_feasibility_blocked",
                "prior_task_feasibility_status": "blocked",
                "prior_task_feasibility_blocker_kind": "grasp_feasibility",
                "prior_task_feasibility_blocker_summary": (
                    "17 grasp failures; 15 candidate-removal calls"
                ),
                "prior_result_match_kind": "object_target",
                "prior_blockers": [{"code": "HouseInvalidForTask"}],
            }
        ],
        "grasp_feasibility_blocker_count": 1,
        "grasp_feasibility_blockers": [
            {
                "kind": "source_request",
                "source_request_id": "proof_001",
                "object_id": "observed_001",
                "target_receptacle_id": "shelf_01",
                "reason": "prior_task_feasibility_blocked",
                "prior_task_feasibility_status": "blocked",
                "prior_task_feasibility_blocker_kind": "grasp_feasibility",
                "prior_task_feasibility_blocker_summary": (
                    "17 grasp failures; 15 candidate-removal calls"
                ),
                "prior_result_match_kind": "object_target",
                "prior_blockers": [{"code": "HouseInvalidForTask"}],
            }
        ],
        "fallback_generation": {
            "schema": "planner_cleanup_proof_request_fallback_generation_v1",
            "status": "exhausted",
            "enabled": True,
            "generated_request_count": 0,
            "generated_requests": [],
            "discovered_alias_count": 0,
            "discovered_aliases": [],
            "filtered_alias_count": 0,
            "filtered_aliases": [],
            "filtered_pair_count": 0,
            "filtered_pairs": [],
            "normalized_alias_count": 0,
            "normalized_aliases": [],
            "exhaustion_blocker_count": 1,
            "exhaustion_blockers": [
                {
                    "code": "no_fallback_candidate_available",
                    "count": 1,
                    "message": "Excluded source request has no remaining fallback candidate.",
                }
            ],
        },
    }
    manifest["proof_result_summary"] = proof_result_summary_from_commands(manifest["commands"])
    (tmp_path / "proof_bundle_run_manifest.json").write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    render_planner_proof_bundle_runner_report(output_dir=tmp_path, manifest=manifest)

    checker._assert_runner_result(manifest, tmp_path)
    report = (tmp_path / "report.html").read_text(encoding="utf-8")
    assert "Grasp Feasibility Blocker Matrix" in report


def test_checker_accepts_grasp_only_task_sampler_diagnostics(tmp_path: Path) -> None:
    checker = _load_checker()
    manifest = _runner_manifest(tmp_path)
    manifest["proof_request_selection"] = proof_request_selection_from_summary(
        {
            "schema": "planner_cleanup_proof_requests_v1",
            "requests": [
                {
                    "request_id": "proof_001",
                    "object_id": "observed_001",
                    "target_receptacle_id": "sink_01",
                    "ready": True,
                }
            ],
        }
    )
    manifest["proof_result_summary"] = {
        "schema": "planner_cleanup_proof_result_summary_v1",
        "expected_count": 1,
        "result_count": 1,
        "planner_backed_count": 0,
        "blocked_count": 1,
        "timeout_count": 0,
        "rby1m_config_import_timeout_count": 0,
        "missing_result_count": 0,
        "cleanup_binding_promoted_count": 0,
        "execution_attempted_count": 1,
        "task_feasibility_blocked_count": 1,
        "grasp_feasibility_blocked_count": 1,
        "worker_stage_event_count": 1,
        "last_worker_stage_counts": {"worker_exception": 1},
        "view_artifact_count": 0,
        "results": [
            {
                "request_id": "proof_001",
                "object_id": "observed_001",
                "target_receptacle_id": "sink_01",
                "run_result": str(tmp_path / "proofs" / "001" / "run_result.json"),
                "report": str(tmp_path / "proofs" / "001" / "report.html"),
                "run_result_exists": True,
                "report_exists": True,
                "status": "blocked_capability",
                "planner_backed": False,
                "cleanup_binding_promoted": False,
                "execution_attempted": True,
                "task_feasibility_status": "blocked",
                "task_feasibility_blocker_kind": "grasp_feasibility",
                "task_feasibility_blocker_summary": (
                    "17 grasp failures; 15 candidate-removal calls"
                ),
                "visual_status": "no_views_recorded",
                "blockers": [{"code": "HouseInvalidForTask"}],
                "cleanup_binding_blockers": [],
                "last_worker_stage": "worker_exception",
                "worker_stage_event_count": 1,
                "worker_stage_events": [
                    {"elapsed_s": 1.0, "event": "worker_exception", "stage": "worker_exception"}
                ],
                "task_sampler_failure_diagnostics": {
                    "grasp_failure_count": 17,
                    "candidate_removal_count": 15,
                    "candidate_name_miss_count": 0,
                    "grasp_failures": [
                        {
                            "object_name": "pickup/body",
                            "candidate_count_before": 17,
                            "candidate_count_after": 17,
                            "removed_candidate": False,
                        }
                    ],
                },
                "views": [],
            }
        ],
    }
    render_planner_proof_bundle_runner_report(output_dir=tmp_path, manifest=manifest)

    report = (tmp_path / "report.html").read_text(encoding="utf-8")
    assert "Post-placement grasp failures" in report
    assert "Post-Placement Rejection Views" in report
    assert "Post-placement rejection flow: pickup/body" in report
    assert "Task sampler placement failures" not in report
    checker._assert_runner_result(manifest, tmp_path)


def test_checker_accepts_visible_warmup_artifact(tmp_path: Path) -> None:
    checker = _load_checker()
    manifest = _runner_manifest(tmp_path)
    warmup_dir = tmp_path / "rby1m_curobo_warmup"
    manifest["warmup"] = {
        "kind": "rby1m_curobo_config_import",
        "output_dir": str(warmup_dir),
        "run_result": str(warmup_dir / "run_result.json"),
        "report": str(warmup_dir / "report.html"),
        "command": [
            "python",
            "probe.py",
            "--output-dir",
            str(warmup_dir),
            "--probe-mode",
            "config_import",
            "--torch-extensions-dir",
            str(tmp_path / "torch_extensions"),
        ],
    }
    _write_manifest_and_report(tmp_path, manifest)

    checker._assert_runner_result(manifest, tmp_path)

    with pytest.raises(AssertionError):
        checker._assert_runner_result(manifest, tmp_path, require_proof_outputs=True)

    warmup_dir.mkdir()
    (warmup_dir / "run_result.json").write_text("{}", encoding="utf-8")
    (warmup_dir / "report.html").write_text("<h1>warmup</h1>", encoding="utf-8")
    proof_dir = tmp_path / "proofs" / "001_observed_001_to_sink_01"
    proof_dir.mkdir(parents=True, exist_ok=True)
    (proof_dir / "run_result.json").write_text("{}", encoding="utf-8")
    (proof_dir / "report.html").write_text("<h1>proof</h1>", encoding="utf-8")
    manifest["proof_result_summary"] = proof_result_summary_from_commands(manifest["commands"])
    _write_manifest_and_report(tmp_path, manifest)

    checker._assert_runner_result(manifest, tmp_path, require_proof_outputs=True)
