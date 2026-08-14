from __future__ import annotations

import json
from pathlib import Path

from roboclaws.household import planner_grasp_cache_generation
from roboclaws.household.planner_grasp_cache import grasp_cache_availability_preflight
from roboclaws.household.planner_grasp_cache_generation import grasp_cache_generation_preflight
from roboclaws.household.planner_task_feasibility import (
    grasp_feasibility_mitigation_decision,
    grasp_feasibility_signature,
    grasp_feasibility_signature_counts,
    task_feasibility_blocker_kind,
    task_feasibility_blocker_summary,
)


def test_task_feasibility_signature_groups_repeated_grasp_blockers() -> None:
    diagnostics = {
        "robot_placement_attempt_count": 17,
        "robot_placement_failure_count": 0,
        "place_robot_near_call_count": 17,
        "grasp_failure_count": 17,
        "candidate_removal_count": 15,
        "image_artifacts": {"post_placement_attempt_001_head_camera": "view.png"},
        "grasp_failures": [
            {"object_name": "bread_1", "count_before": 0, "count_after": 1},
            {"object_name": "bread_1", "count_before": 1, "count_after": 2},
        ],
    }

    kind = task_feasibility_blocker_kind([], diagnostics)
    signature = grasp_feasibility_signature(diagnostics)
    groups = grasp_feasibility_signature_counts(
        [
            {
                "request_id": "proof_001",
                "object_id": "observed_001",
                "target_receptacle_id": "fridge_01",
                "report": "proofs/001/report.html",
                "grasp_feasibility_signature": signature,
            },
            {
                "request_id": "proof_002",
                "object_id": "observed_002",
                "target_receptacle_id": "fridge_01",
                "report": "proofs/002/report.html",
                "grasp_feasibility_signature": {
                    **signature,
                    "object_names": ["bread_2"],
                },
            },
        ]
    )

    assert kind == "grasp_feasibility"
    assert task_feasibility_blocker_summary(kind, diagnostics) == (
        "17 grasp failures; 15 candidate-removal calls"
    )
    assert signature["pattern_key"] == (
        '{"candidate_removal_count":15,"grasp_failure_count":17,'
        '"place_robot_near_call_count":17,"robot_placement_failure_count":0,'
        '"subkind":"grasp_rejection"}'
    )
    assert signature["subkind"] == "grasp_rejection"
    assert signature["object_names"] == ["bread_1"]
    assert groups[0]["count"] == 2
    assert groups[0]["request_ids"] == ["proof_001", "proof_002"]
    assert groups[0]["object_names"] == ["bread_1", "bread_2"]


def test_grasp_summary_includes_candidate_removal_effectiveness_when_present() -> None:
    diagnostics = {
        "grasp_failure_count": 17,
        "candidate_removal_count": 15,
        "candidate_effective_removal_count": 0,
        "candidate_name_miss_count": 15,
        "grasp_threshold_exceeded_count": 15,
        "grasp_failures": [{"object_name": "bread_1"}],
    }

    kind = task_feasibility_blocker_kind([], diagnostics)
    signature = grasp_feasibility_signature(diagnostics)

    assert task_feasibility_blocker_summary(kind, diagnostics) == (
        "17 grasp failures; 15 candidate-removal calls; "
        "0 effective removals; 15 candidate-name misses"
    )
    assert signature["candidate_effective_removal_count"] == 0
    assert signature["candidate_name_miss_count"] == 15
    assert signature["grasp_threshold_exceeded_count"] == 15
    assert '"candidate_effective_removal_count":0' in signature["pattern_key"]


def test_grasp_summary_classifies_missing_grasp_cache() -> None:
    diagnostics = {
        "grasp_failure_count": 3,
        "candidate_removal_count": 1,
        "candidate_effective_removal_count": 1,
        "candidate_name_miss_count": 0,
        "grasp_load_attempt_count": 3,
        "grasp_load_failure_count": 3,
        "grasp_collision_check_count": 0,
        "grasp_load_attempts": [
            {
                "asset_uid": "Bread_1",
                "exception_type": "ValueError",
                "result": "exception",
            },
            {
                "asset_uid": "Bread_1",
                "exception_type": "ValueError",
                "result": "exception",
            },
        ],
        "grasp_failures": [{"object_name": "bread/body"}],
    }

    kind = task_feasibility_blocker_kind([], diagnostics)
    signature = grasp_feasibility_signature(diagnostics)

    assert task_feasibility_blocker_summary(kind, diagnostics) == (
        "3 grasp failures; 1 candidate-removal calls; 1 effective removals; "
        "0 candidate-name misses; 3 grasp-load failures; missing grasp cache: Bread_1"
    )
    assert signature["subkind"] == "grasp_cache_missing"
    assert signature["grasp_load_failure_count"] == 3
    assert signature["grasp_collision_check_count"] == 0
    assert signature["grasp_load_exception_asset_uids"] == ["Bread_1"]
    assert signature["grasp_load_exception_types"] == ["ValueError"]
    assert '"subkind":"grasp_cache_missing"' in signature["pattern_key"]
    assert '"grasp_load_exception_asset_uids":["Bread_1"]' in signature["pattern_key"]


def test_grasp_mitigation_decision_routes_missing_cache_before_retry() -> None:
    decision = grasp_feasibility_mitigation_decision(
        prior_proof_result_summary={
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
                        "count": 1,
                        "request_ids": ["proof_001"],
                        "object_names": ["bread/body"],
                        "grasp_failure_count": 3,
                        "candidate_removal_count": 1,
                        "grasp_load_exception_asset_uids": ["Bread_1"],
                        "grasp_load_exception_types": ["ValueError"],
                    },
                }
            ]
        },
        proof_request_selection={"selected_count": 2, "excluded_count": 1},
    )

    assert decision["primary_route"] == "grasp_cache_mitigation"
    assert decision["status"] == "action_required"
    assert decision["recommendation"] == "mitigate_missing_grasp_cache_before_retry"
    assert decision["source_rotation_state"] == "available_for_unproven_requests"
    assert decision["missing_grasp_asset_uids"] == ["Bread_1"]
    assert decision["grasp_load_exception_types"] == ["ValueError"]
    assert decision["subkind_counts"] == {"grasp_cache_missing": 1}


def test_grasp_cache_preflight_distinguishes_object_asset_from_missing_cache(
    tmp_path: Path,
) -> None:
    object_dir = tmp_path / "objects" / "thor" / "20251117" / "Kitchen Objects" / "Bread"
    object_dir.mkdir(parents=True)
    (object_dir / "Bread_1.xml").write_text("<mujoco />", encoding="utf-8")
    (object_dir / "Bread_1.obj").write_text("o Bread_1\n", encoding="utf-8")

    preflight = grasp_cache_availability_preflight(
        {"missing_grasp_asset_uids": ["Bread_1"]},
        assets_dir=tmp_path,
    )

    assert preflight["schema"] == "planner_grasp_cache_availability_preflight_v1"
    assert preflight["status"] == "missing_cache"
    assert preflight["assets_dir_source"] == "argument"
    assert preflight["assets_dir_resolved"] == str(tmp_path)
    assert preflight["missing_cache_asset_count"] == 1
    assert preflight["cache_missing_asset_uids"] == ["Bread_1"]
    asset = preflight["assets"][0]
    assert asset["asset_uid"] == "Bread_1"
    assert asset["loader_file_status"] == "missing"
    assert asset["object_asset_status"] == "present"
    assert len(asset["candidate_grasp_files"]) == 3
    assert asset["candidate_grasp_files"][0]["relative_path"] == (
        "grasps/droid/Bread_1/Bread_1_grasps_filtered.npz"
    )
    assert asset["candidate_grasp_files"][1]["relative_path"] == (
        "grasps/droid_objaverse/Bread_1/Bread_1_grasps_filtered.npz"
    )
    assert asset["candidate_grasp_files"][2]["relative_path"] == (
        "grasps/rum/Bread_1/Bread_1_grasps_filtered.json"
    )
    assert asset["folder_probe_files"][0]["loader_role"] == "has_grasp_folder_only"
    assert {item["kind"] for item in asset["object_asset_files"]} == {"xml", "obj"}


def test_grasp_cache_preflight_resolves_runtime_symlink_root(tmp_path: Path) -> None:
    assets_dir = tmp_path / "assets"
    cache_dir = tmp_path / "cache" / "grasps" / "droid" / "20251116"
    cache_dir.mkdir(parents=True)
    (assets_dir / "grasps").mkdir(parents=True)
    (assets_dir / "grasps" / "droid").symlink_to(cache_dir, target_is_directory=True)

    preflight = grasp_cache_availability_preflight(
        {"missing_grasp_asset_uids": ["Bread_1"]},
        assets_dir=assets_dir,
        assets_dir_source="planner_scene",
    )

    probe = preflight["assets"][0]["candidate_grasp_files"][0]
    assert preflight["assets_dir_source"] == "planner_scene"
    assert probe["relative_path"] == "grasps/droid/Bread_1/Bread_1_grasps_filtered.npz"
    assert probe["path"] == str(
        assets_dir / "grasps" / "droid" / "Bread_1" / "Bread_1_grasps_filtered.npz"
    )
    assert probe["resolved_path"] == str(cache_dir / "Bread_1" / "Bread_1_grasps_filtered.npz")
    assert probe["parent_resolved_path"] == str(cache_dir / "Bread_1")


def test_grasp_cache_preflight_ready_when_rigid_loader_file_exists(tmp_path: Path) -> None:
    import numpy as np

    grasp_dir = tmp_path / "grasps" / "droid" / "Bread_1"
    grasp_dir.mkdir(parents=True)
    np.savez(grasp_dir / "Bread_1_grasps_filtered.npz", transforms=np.zeros((1, 4, 4)))

    preflight = grasp_cache_availability_preflight(
        {"missing_grasp_asset_uids": ["Bread_1"]},
        assets_dir=tmp_path,
    )

    assert preflight["status"] == "ready"
    assert preflight["ready_asset_count"] == 1
    assert preflight["missing_cache_asset_count"] == 0
    assert preflight["cache_ready_asset_uids"] == ["Bread_1"]
    assert preflight["assets"][0]["loader_file_status"] == "valid"
    assert preflight["assets"][0]["object_asset_status"] == "missing"
    assert preflight["assets"][0]["candidate_grasp_files"][0]["valid"] is True
    assert preflight["assets"][0]["candidate_grasp_files"][0]["transform_count"] == 1


def test_grasp_cache_preflight_rejects_empty_loader_file(tmp_path: Path) -> None:
    import numpy as np

    grasp_dir = tmp_path / "grasps" / "droid" / "Bread_1"
    grasp_dir.mkdir(parents=True)
    np.savez(grasp_dir / "Bread_1_grasps_filtered.npz", transforms=np.zeros((0,)))

    preflight = grasp_cache_availability_preflight(
        {"missing_grasp_asset_uids": ["Bread_1"]},
        assets_dir=tmp_path,
    )

    probe = preflight["assets"][0]["candidate_grasp_files"][0]
    assert preflight["status"] == "missing_cache"
    assert preflight["ready_asset_count"] == 0
    assert preflight["missing_cache_asset_count"] == 1
    assert preflight["assets"][0]["loader_file_status"] == "present_but_invalid"
    assert probe["exists"] is True
    assert probe["valid"] is False
    assert probe["validation_status"] == "empty"
    assert probe["transform_count"] == 0


def test_grasp_cache_preflight_reads_json_loader_file(tmp_path: Path) -> None:
    grasp_dir = tmp_path / "grasps" / "rum" / "Bread_1"
    grasp_dir.mkdir(parents=True)
    (grasp_dir / "Bread_1_grasps_filtered.json").write_text(
        json.dumps({"transforms": [[[1.0]]]}),
        encoding="utf-8",
    )

    preflight = grasp_cache_availability_preflight(
        {"missing_grasp_asset_uids": ["Bread_1"]},
        assets_dir=tmp_path,
    )

    probe = _grasp_cache_probe(preflight, "grasps/rum/Bread_1/Bread_1_grasps_filtered.json")
    assert probe["valid"] is True
    assert probe["validation_status"] == "valid"
    assert probe["transform_count"] == 1


def test_grasp_cache_preflight_treats_non_object_json_loader_file_as_empty(
    tmp_path: Path,
) -> None:
    grasp_dir = tmp_path / "grasps" / "rum" / "Bread_1"
    grasp_dir.mkdir(parents=True)
    (grasp_dir / "Bread_1_grasps_filtered.json").write_text("[]", encoding="utf-8")

    preflight = grasp_cache_availability_preflight(
        {"missing_grasp_asset_uids": ["Bread_1"]},
        assets_dir=tmp_path,
    )

    probe = _grasp_cache_probe(preflight, "grasps/rum/Bread_1/Bread_1_grasps_filtered.json")
    assert probe["valid"] is False
    assert probe["validation_status"] == "empty"
    assert probe["transform_count"] == 0


def test_grasp_cache_preflight_reports_malformed_json_loader_file(
    tmp_path: Path,
) -> None:
    grasp_dir = tmp_path / "grasps" / "rum" / "Bread_1"
    grasp_dir.mkdir(parents=True)
    (grasp_dir / "Bread_1_grasps_filtered.json").write_text("{bad json\n", encoding="utf-8")

    preflight = grasp_cache_availability_preflight(
        {"missing_grasp_asset_uids": ["Bread_1"]},
        assets_dir=tmp_path,
    )

    probe = _grasp_cache_probe(preflight, "grasps/rum/Bread_1/Bread_1_grasps_filtered.json")
    assert probe["valid"] is False
    assert probe["validation_status"] == "error"
    assert probe["transform_count"] == 0
    assert probe["validation_error_type"] == "ValueError"
    assert "planner grasp cache source must contain valid JSON" in probe["validation_error"]


def _grasp_cache_probe(preflight: dict, relative_path: str) -> dict:
    for probe in preflight["assets"][0]["candidate_grasp_files"]:
        if probe["relative_path"] == relative_path:
            return probe
    raise AssertionError(f"missing grasp cache probe: {relative_path}")


def test_grasp_cache_generation_preflight_reports_missing_prerequisites(
    tmp_path: Path,
) -> None:
    object_dir = tmp_path / "objects" / "thor" / "Kitchen Objects" / "Bread" / "Prefabs"
    object_dir.mkdir(parents=True)
    (object_dir / "Bread_1.xml").write_text("<mujoco />", encoding="utf-8")

    availability = grasp_cache_availability_preflight(
        {"missing_grasp_asset_uids": ["Bread_1"]},
        assets_dir=tmp_path,
    )

    preflight = grasp_cache_generation_preflight(
        availability,
        output_dir=tmp_path / "runner",
        molmospaces_python=None,
    )

    assert preflight["schema"] == "planner_grasp_cache_generation_preflight_v1"
    assert preflight["status"] == "blocked"
    assert preflight["asset_count"] == 1
    assert preflight["blocker_count"] >= 1
    assert preflight["assets"][0]["asset_uid"] == "Bread_1"
    assert preflight["assets"][0]["object_xml_exists"] is True
    assert preflight["assets"][0]["cache_target_relative_path"] == (
        "grasps/droid/Bread_1/Bread_1_grasps_filtered.npz"
    )
    assert preflight["objects_list_path"].endswith("grasp_generation/rigid_objects_list.json")
    assert any(
        blocker["code"] == "molmospaces_python_not_configured" for blocker in preflight["blockers"]
    )


def test_grasp_cache_generation_preflight_blocks_malformed_runtime_probe_stdout(
    monkeypatch,
    tmp_path: Path,
) -> None:
    python_path = tmp_path / "python"
    python_path.write_text("#!/bin/sh\n", encoding="utf-8")
    availability = {
        "assets_dir": str(tmp_path / "assets"),
        "assets": [{"asset_uid": "Bread_1", "status": "missing_cache"}],
    }

    monkeypatch.setattr(
        planner_grasp_cache_generation,
        "_run_preflight_command",
        lambda _command, *, timeout_s: {"status": "ready", "stdout": "{not-json\n", "stderr": ""},
    )

    preflight = grasp_cache_generation_preflight(
        availability,
        output_dir=tmp_path / "runner",
        molmospaces_python=python_path,
    )

    runtime_check = preflight["checks"][0]
    assert preflight["status"] == "blocked"
    assert runtime_check["status"] == "blocked"
    assert runtime_check["code"] == "molmo_spaces_runtime_probe_invalid_stdout"
    assert (
        "MolmoSpaces runtime probe stdout source must contain valid JSON object"
        in (runtime_check["message"])
    )


def test_grasp_cache_generation_preflight_blocks_non_object_runtime_probe_stdout(
    monkeypatch,
    tmp_path: Path,
) -> None:
    python_path = tmp_path / "python"
    python_path.write_text("#!/bin/sh\n", encoding="utf-8")
    availability = {
        "assets_dir": str(tmp_path / "assets"),
        "assets": [{"asset_uid": "Bread_1", "status": "missing_cache"}],
    }

    monkeypatch.setattr(
        planner_grasp_cache_generation,
        "_run_preflight_command",
        lambda _command, *, timeout_s: {"status": "ready", "stdout": "[]\n", "stderr": ""},
    )

    preflight = grasp_cache_generation_preflight(
        availability,
        output_dir=tmp_path / "runner",
        molmospaces_python=python_path,
    )

    runtime_check = preflight["checks"][0]
    assert preflight["status"] == "blocked"
    assert runtime_check["status"] == "blocked"
    assert runtime_check["code"] == "molmo_spaces_runtime_probe_invalid_stdout"
    assert (
        "MolmoSpaces runtime probe stdout source must contain a JSON object"
        in (runtime_check["message"])
    )


def test_grasp_cache_generation_preflight_blocks_missing_runtime_probe_paths(
    monkeypatch,
    tmp_path: Path,
) -> None:
    python_path = tmp_path / "python"
    python_path.write_text("#!/bin/sh\n", encoding="utf-8")
    availability = {
        "assets_dir": str(tmp_path / "assets"),
        "assets": [{"asset_uid": "Bread_1", "status": "missing_cache"}],
    }

    monkeypatch.setattr(
        planner_grasp_cache_generation,
        "_run_preflight_command",
        lambda _command, *, timeout_s: {
            "status": "ready",
            "stdout": '{"molmospaces_root": "", "assets_dir": "/tmp/assets"}\n',
            "stderr": "",
        },
    )

    preflight = grasp_cache_generation_preflight(
        availability,
        output_dir=tmp_path / "runner",
        molmospaces_python=python_path,
    )

    runtime_check = preflight["checks"][0]
    assert preflight["status"] == "blocked"
    assert runtime_check["status"] == "blocked"
    assert runtime_check["code"] == "molmo_spaces_runtime_probe_missing_paths"
    assert runtime_check["message"] == (
        "MolmoSpaces runtime probe stdout must include molmospaces_root and assets_dir."
    )
