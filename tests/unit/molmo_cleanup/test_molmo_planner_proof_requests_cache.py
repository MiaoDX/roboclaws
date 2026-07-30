from __future__ import annotations

from pathlib import Path

from roboclaws.household.planner_proof_contracts import PLANNER_PROOF_REQUESTS_SCHEMA
from roboclaws.household.planner_proof_requests import (
    proof_bundle_run_manifest,
)


def test_proof_bundle_manifest_includes_grasp_cache_preflight(
    tmp_path: Path,
    monkeypatch,
) -> None:
    object_dir = tmp_path / "assets" / "objects" / "thor" / "Kitchen Objects" / "Bread"
    object_dir.mkdir(parents=True)
    (object_dir / "Bread_1.xml").write_text("<mujoco />", encoding="utf-8")
    monkeypatch.setenv("MLSPACES_ASSETS_DIR", str(tmp_path / "wrong-assets"))

    manifest = proof_bundle_run_manifest(
        cleanup_run_result=tmp_path / "cleanup" / "run_result.json",
        output_dir=tmp_path / "bundle",
        proof_requests={
            "schema": PLANNER_PROOF_REQUESTS_SCHEMA,
            "request_count": 1,
            "ready_count": 1,
            "requests": [
                {
                    "request_id": "proof_001",
                    "ready": True,
                    "object_id": "observed_001",
                    "target_receptacle_id": "fridge_01",
                    "planner_probe_args": {"--cleanup-object-id": "observed_001"},
                }
            ],
            "planner_scene": {
                "schema": "planner_cleanup_proof_scene_v1",
                "available": True,
                "scene_xml": str(tmp_path / "assets" / "scenes" / "procthor-val" / "val_0.xml"),
            },
        },
        commands=[],
        prior_proof_result_summary={
            "schema": "planner_cleanup_proof_result_summary_v1",
            "results": [
                {
                    "request_id": "proof_001",
                    "object_id": "observed_001",
                    "target_receptacle_id": "fridge_01",
                    "grasp_feasibility_signature": {
                        "schema": "planner_grasp_feasibility_signature_v1",
                        "kind": "grasp_feasibility",
                        "subkind": "grasp_cache_missing",
                        "pattern_key": "missing-cache",
                        "summary": "3 grasp-load failures; missing grasp cache: Bread_1",
                        "grasp_failure_count": 3,
                        "candidate_removal_count": 1,
                        "grasp_load_exception_asset_uids": ["Bread_1"],
                        "grasp_load_exception_types": ["ValueError"],
                    },
                }
            ],
        },
        proof_request_selection={
            "schema": "planner_cleanup_proof_request_selection_v1",
            "selected_count": 0,
            "excluded_count": 1,
            "selected_request_ids": [],
        },
    )

    decision = manifest["grasp_feasibility_mitigation_decision"]
    preflight = manifest["grasp_cache_availability_preflight"]
    assert decision["primary_route"] == "grasp_cache_mitigation"
    assert preflight["status"] == "missing_cache"
    assert preflight["assets_dir"] == str(tmp_path / "assets")
    assert preflight["assets_dir_source"] == "planner_scene"
    assert preflight["cache_missing_asset_uids"] == ["Bread_1"]
    assert preflight["assets"][0]["object_asset_status"] == "present"
    assert preflight["assets"][0]["candidate_grasp_files"][0]["relative_path"] == (
        "grasps/droid/Bread_1/Bread_1_grasps_filtered.npz"
    )
