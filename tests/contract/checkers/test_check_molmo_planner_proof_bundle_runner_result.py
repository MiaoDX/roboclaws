from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

import pytest

from roboclaws.household.manipulation_provenance import planner_backed_probe_evidence
from roboclaws.household.planner_proof_contracts import PLANNER_PROOF_BUNDLE_RUN_MANIFEST_SCHEMA
from roboclaws.household.planner_proof_requests import (
    proof_execution_horizon,
)
from roboclaws.household.planner_proof_results import proof_result_summary_from_commands
from roboclaws.household.planner_proof_selection import proof_request_selection_from_summary
from roboclaws.household.report_planner import render_planner_proof_bundle_runner_report

REPO_ROOT = Path(__file__).resolve().parents[3]
CHECKER_PATH = (
    REPO_ROOT / "scripts" / "molmo_cleanup" / "check_molmo_planner_proof_bundle_runner_result.py"
)


def _load_checker():
    spec = importlib.util.spec_from_file_location(
        "check_molmo_planner_proof_bundle_runner_result",
        CHECKER_PATH,
    )
    assert spec is not None
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def test_checker_accepts_valid_runner_artifact(tmp_path: Path) -> None:
    checker = _load_checker()
    manifest = _write_runner_artifact(tmp_path)

    checker._assert_runner_result(manifest, tmp_path)


def test_checker_can_require_proof_execution_horizon(tmp_path: Path) -> None:
    checker = _load_checker()
    manifest = _write_runner_artifact(tmp_path)

    checker._assert_runner_result(manifest, tmp_path, require_proof_execution_horizon=True)


def test_checker_accepts_local_runtime_blocked_runner_artifact(tmp_path: Path) -> None:
    checker = _load_checker()
    manifest = _runner_manifest(tmp_path)
    manifest["status"] = "local_runtime_blocked"
    manifest["local_runtime_preflight"] = {
        "schema": "planner_proof_bundle_local_runtime_preflight_v1",
        "requested": True,
        "status": "blocked",
        "python_executable": str(tmp_path / "molmospaces-python"),
        "checks": [
            {
                "name": "molmo_spaces_import",
                "status": "blocked",
                "command": [str(tmp_path / "molmospaces-python"), "-c", "import molmo_spaces"],
                "returncode": 1,
                "code": "molmo_spaces_import_failed",
                "message": "No module named molmo_spaces",
            }
        ],
        "blockers": [
            {
                "code": "molmo_spaces_import_failed",
                "message": "No module named molmo_spaces",
            }
        ],
    }
    manifest["proof_result_summary"] = proof_result_summary_from_commands(manifest["commands"])
    manifest["grasp_feasibility_mitigation_decision"] = {
        "schema": "planner_grasp_feasibility_mitigation_decision_v1",
        "status": "action_required",
        "primary_route": "grasp_cache_mitigation",
        "recommendation": "mitigate_missing_grasp_cache_before_retry",
        "rationale": "Cached grasps could not be loaded for a requested asset.",
        "source_rotation_state": "available_for_unproven_requests",
        "selected_request_count": 1,
        "excluded_request_count": 1,
        "signature_group_count": 1,
        "subkind_counts": {"grasp_cache_missing": 1},
        "missing_grasp_asset_uids": ["PriorBread_1"],
        "grasp_load_exception_types": ["ValueError"],
        "evidence_request_ids": ["standalone_observed_001_to_shelf_01"],
        "signature_groups": [
            {
                "source": "prior_proof_result_summary",
                "subkind": "grasp_cache_missing",
                "count": 1,
                "summary": "17 grasp-load failures; missing grasp cache: PriorBread_1",
                "request_ids": ["standalone_observed_001_to_shelf_01"],
                "object_names": ["prior/pickup"],
                "grasp_load_exception_asset_uids": ["PriorBread_1"],
                "grasp_load_exception_types": ["ValueError"],
            }
        ],
    }
    manifest["grasp_cache_availability_preflight"] = {
        "schema": "planner_grasp_cache_availability_preflight_v1",
        "status": "missing_cache",
        "assets_dir": str(tmp_path / "assets"),
        "assets_dir_source": "argument",
        "assets_dir_exists": True,
        "missing_grasp_asset_uids": ["PriorBread_1"],
        "asset_count": 1,
        "ready_asset_count": 0,
        "missing_cache_asset_count": 1,
        "cache_ready_asset_uids": [],
        "cache_missing_asset_uids": ["PriorBread_1"],
        "loader_sources": ["droid", "droid_objaverse", "rum"],
        "mitigation_recommendation": "generate_or_install_rigid_grasp_cache_before_retry",
        "upstream_loader": "molmo_spaces.utils.grasp_sample.load_grasps_for_object",
        "evidence_note": "Preflights rigid-object grasp cache files.",
        "assets": [
            {
                "asset_uid": "PriorBread_1",
                "status": "missing_cache",
                "loader_file_status": "missing",
                "object_asset_status": "present",
                "candidate_grasp_files": [
                    {
                        "asset_uid": "PriorBread_1",
                        "source": "droid",
                        "gripper": "droid",
                        "loader_role": "rigid_object_loader",
                        "path": str(
                            tmp_path
                            / "assets"
                            / "grasps"
                            / "droid"
                            / "PriorBread_1"
                            / "PriorBread_1_grasps_filtered.npz"
                        ),
                        "relative_path": (
                            "grasps/droid/PriorBread_1/PriorBread_1_grasps_filtered.npz"
                        ),
                        "exists": False,
                        "size_bytes": 0,
                    },
                    {
                        "asset_uid": "PriorBread_1",
                        "source": "droid_objaverse",
                        "gripper": "droid",
                        "loader_role": "rigid_object_loader",
                        "path": str(
                            tmp_path
                            / "assets"
                            / "grasps"
                            / "droid_objaverse"
                            / "PriorBread_1"
                            / "PriorBread_1_grasps_filtered.npz"
                        ),
                        "relative_path": (
                            "grasps/droid_objaverse/PriorBread_1/PriorBread_1_grasps_filtered.npz"
                        ),
                        "exists": False,
                        "size_bytes": 0,
                    },
                    {
                        "asset_uid": "PriorBread_1",
                        "source": "rum",
                        "gripper": "rum",
                        "loader_role": "rigid_object_loader",
                        "path": str(
                            tmp_path
                            / "assets"
                            / "grasps"
                            / "rum"
                            / "PriorBread_1"
                            / "PriorBread_1_grasps_filtered.json"
                        ),
                        "relative_path": (
                            "grasps/rum/PriorBread_1/PriorBread_1_grasps_filtered.json"
                        ),
                        "exists": False,
                        "size_bytes": 0,
                    },
                ],
                "folder_probe_files": [
                    {
                        "asset_uid": "PriorBread_1",
                        "source": "droid",
                        "gripper": "droid",
                        "loader_role": "has_grasp_folder_only",
                        "path": str(
                            tmp_path
                            / "assets"
                            / "grasps"
                            / "droid"
                            / "PriorBread_1"
                            / "PriorBread_1_joint_grasps_filtered.npz"
                        ),
                        "relative_path": (
                            "grasps/droid/PriorBread_1/PriorBread_1_joint_grasps_filtered.npz"
                        ),
                        "exists": False,
                        "size_bytes": 0,
                    }
                ],
                "object_asset_files": [
                    {
                        "kind": "xml",
                        "path": str(tmp_path / "assets" / "objects" / "thor" / "PriorBread_1.xml"),
                        "relative_path": "objects/thor/PriorBread_1.xml",
                        "exists": True,
                        "size_bytes": 10,
                    }
                ],
            }
        ],
    }
    manifest["grasp_cache_generation_preflight"] = {
        "schema": "planner_grasp_cache_generation_preflight_v1",
        "status": "blocked",
        "ready": False,
        "asset_count": 1,
        "blocker_count": 1,
        "molmospaces_python": str(tmp_path / "molmospaces-python"),
        "molmospaces_root": str(tmp_path / "molmospaces"),
        "assets_dir": str(tmp_path / "assets"),
        "objects_list_path": str(tmp_path / "grasp_generation" / "rigid_objects_list.json"),
        "working_dir": str(tmp_path / "molmospaces" / "molmo_spaces" / "grasp_generation"),
        "command": [
            str(tmp_path / "molmospaces-python"),
            str(tmp_path / "molmospaces" / "molmo_spaces" / "grasp_generation" / "run_rigid.py"),
            "--objects_list",
            str(tmp_path / "grasp_generation" / "rigid_objects_list.json"),
        ],
        "mitigation_recommendation": (
            "install_grasp_generation_prerequisites_before_cache_generation"
        ),
        "assets": [
            {
                "asset_uid": "PriorBread_1",
                "object_xml": str(tmp_path / "assets" / "objects" / "thor" / "PriorBread_1.xml"),
                "object_xml_exists": True,
                "generated_npz_path": str(
                    tmp_path
                    / "molmospaces"
                    / "grasp_results"
                    / "rigid_objects"
                    / "PriorBread_1"
                    / "PriorBread_1_grasps_filtered.npz"
                ),
                "cache_target_resolved_path": str(
                    tmp_path
                    / "assets"
                    / "grasps"
                    / "droid"
                    / "PriorBread_1"
                    / "PriorBread_1_grasps_filtered.npz"
                ),
            }
        ],
        "checks": [
            {
                "name": "python_fcl_runtime",
                "status": "blocked",
                "code": "python_fcl_missing",
                "message": "No FCL Available",
            }
        ],
        "blockers": [
            {
                "code": "python_fcl_missing",
                "name": "python_fcl_runtime",
                "message": "No FCL Available",
            }
        ],
    }
    (tmp_path / "proof_bundle_run_manifest.json").write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    render_planner_proof_bundle_runner_report(output_dir=tmp_path, manifest=manifest)

    checker._assert_runner_result(manifest, tmp_path)


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


def test_checker_rejects_missing_report(tmp_path: Path) -> None:
    checker = _load_checker()
    manifest = _write_runner_artifact(tmp_path)
    (tmp_path / "report.html").unlink()

    with pytest.raises(AssertionError):
        checker._assert_runner_result(manifest, tmp_path)


def test_checker_rejects_missing_command_report_path(tmp_path: Path) -> None:
    checker = _load_checker()
    manifest = _runner_manifest(tmp_path)
    del manifest["commands"][0]["report"]
    _write_manifest_and_report(tmp_path, manifest)

    with pytest.raises(AssertionError):
        checker._assert_runner_result(manifest, tmp_path)


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


def test_checker_can_require_proof_quality_for_planner_backed_result(
    tmp_path: Path,
) -> None:
    checker = _load_checker()
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
    checker._assert_runner_result(
        manifest,
        tmp_path,
        require_proof_outputs=True,
        require_proof_quality=True,
        planner_backed_proof_min_steps=2,
    )
    with pytest.raises(AssertionError):
        checker._assert_runner_result(
            manifest,
            tmp_path,
            require_proof_outputs=True,
            require_proof_quality=True,
            planner_backed_proof_min_steps=3,
        )


def test_checker_requires_timeout_stage_evidence_in_report(tmp_path: Path) -> None:
    checker = _load_checker()
    manifest = _runner_manifest(tmp_path)
    proof_dir = tmp_path / "proofs" / "001_observed_001_to_sink_01"
    proof_dir.mkdir(parents=True)
    (proof_dir / "planner_probe_stdout.txt").write_text("stdout", encoding="utf-8")
    (proof_dir / "planner_probe_stderr.txt").write_text("stderr", encoding="utf-8")
    (proof_dir / "report.html").write_text("<h1>proof</h1>", encoding="utf-8")
    (proof_dir / "run_result.json").write_text(
        json.dumps(
            {
                "status": "blocked_capability",
                "artifacts": {
                    "stdout": "planner_probe_stdout.txt",
                    "stderr": "planner_probe_stderr.txt",
                },
                "manipulation_evidence": {
                    "execution_attempted": False,
                    "blockers": [{"code": "timeout", "message": "Probe exceeded 1.0s"}],
                    "last_worker_stage": "rby1m_config_import",
                    "worker_stage_events": [
                        {"elapsed_s": 0.1, "event": "worker_start", "stage": "worker_start"},
                        {
                            "elapsed_s": 3.2,
                            "event": "rby1m_config_import_start",
                            "stage": "rby1m_config_import",
                        },
                    ],
                },
            }
        ),
        encoding="utf-8",
    )
    _write_manifest_and_report(tmp_path, manifest)

    checker._assert_runner_result(manifest, tmp_path, require_proof_outputs=True)


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


def test_checker_requires_cleanup_rerun_outputs_for_cleanup_rerun_status(
    tmp_path: Path,
) -> None:
    checker = _load_checker()
    cleanup_dir = tmp_path / "cleanup_rerun"
    manifest = _runner_manifest(tmp_path)
    manifest["status"] = "cleanup_rerun"
    manifest["cleanup_command"] = [
        "python",
        "cleanup.py",
        "--output-dir",
        str(cleanup_dir),
    ]
    manifest["cleanup_rerun"] = {
        "output_dir": str(cleanup_dir),
        "run_result": str(cleanup_dir / "run_result.json"),
        "report": str(cleanup_dir / "report.html"),
    }
    _write_manifest_and_report(tmp_path, manifest)

    with pytest.raises(AssertionError):
        checker._assert_runner_result(manifest, tmp_path)

    cleanup_dir.mkdir()
    (cleanup_dir / "run_result.json").write_text("{}", encoding="utf-8")
    (cleanup_dir / "report.html").write_text("<h1>cleanup</h1>", encoding="utf-8")

    checker._assert_runner_result(manifest, tmp_path)
    checker._assert_runner_result(
        manifest,
        tmp_path,
        require_cleanup_rerun_output=True,
    )


def _write_runner_artifact(base: Path) -> dict[str, object]:
    manifest = _runner_manifest(base)
    _write_manifest_and_report(base, manifest)
    return manifest


def _write_manifest_and_report(base: Path, manifest: dict[str, object]) -> None:
    manifest["proof_request_selection"] = proof_request_selection_from_summary(
        {
            "schema": "planner_cleanup_proof_requests_v1",
            "requests": [
                {
                    "request_id": command["request_id"],
                    "object_id": command["object_id"],
                    "target_receptacle_id": command["target_receptacle_id"],
                    "ready": True,
                }
                for command in manifest["commands"]
            ],
        }
    )
    manifest["proof_result_summary"] = proof_result_summary_from_commands(manifest["commands"])
    (base / "proof_bundle_run_manifest.json").write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    render_planner_proof_bundle_runner_report(output_dir=base, manifest=manifest)


def _runner_manifest(base: Path) -> dict[str, object]:
    proof_dir = base / "proofs" / "001_observed_001_to_sink_01"
    command = [
        "python",
        "probe.py",
        "--output-dir",
        str(proof_dir),
        "--cleanup-object-id",
        "observed_001",
        "--cleanup-target-receptacle-id",
        "sink_01",
    ]
    return {
        "schema": PLANNER_PROOF_BUNDLE_RUN_MANIFEST_SCHEMA,
        "status": "dry_run",
        "cleanup_run_result": str(base / "cleanup" / "run_result.json"),
        "output_dir": str(base),
        "proof_request_count": 1,
        "ready_request_count": 1,
        "proof_execution_horizon": proof_execution_horizon(
            command_steps=2,
            prior_covered_min_proof_steps=1,
        ),
        "command_count": 1,
        "commands": [
            {
                "request_id": "proof_001",
                "object_id": "observed_001",
                "target_receptacle_id": "sink_01",
                "tools": [
                    "navigate_to_object",
                    "pick",
                    "navigate_to_receptacle",
                    "place",
                ],
                "semantic_subphases": [
                    {"phase": "navigate_to_object", "label": "nav", "detail": "object"},
                    {"phase": "pick", "label": "pick", "detail": "object"},
                    {"phase": "navigate_to_receptacle", "label": "nav", "detail": "target"},
                    {"phase": "place", "label": "place", "detail": "surface"},
                ],
                "output_dir": str(proof_dir),
                "run_result": str(proof_dir / "run_result.json"),
                "report": str(proof_dir / "report.html"),
                "command": command,
            }
        ],
        "cleanup_command": [],
        "report": str(base / "report.html"),
    }
