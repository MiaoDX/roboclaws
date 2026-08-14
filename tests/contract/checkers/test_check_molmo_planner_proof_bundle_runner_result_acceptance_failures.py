from __future__ import annotations

import json
from pathlib import Path

from roboclaws.household.planner_proof_results import proof_result_summary_from_commands
from roboclaws.household.report_planner import render_planner_proof_bundle_runner_report
from tests.contract.checkers.check_molmo_planner_proof_bundle_runner_result_support import (
    _load_checker,
    _runner_manifest,
)


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
