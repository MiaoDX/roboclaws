from __future__ import annotations

import json
from pathlib import Path

from roboclaws.household.manipulation_provenance import planner_backed_probe_evidence
from roboclaws.household.planner_proof_results import proof_result_summary_from_commands


def test_proof_result_summary_classifies_task_feasibility_and_views(tmp_path: Path) -> None:
    proof_dir = tmp_path / "proofs" / "001_observed_001_to_sink_01"
    views_dir = proof_dir / "planner_views"
    views_dir.mkdir(parents=True)
    (views_dir / "initial.png").write_bytes(b"initial")
    (views_dir / "final.png").write_bytes(b"final")
    (proof_dir / "report.html").write_text("<h1>proof</h1>", encoding="utf-8")
    (proof_dir / "run_result.json").write_text(
        json.dumps(
            {
                "status": "blocked_capability",
                "manipulation_evidence": {
                    "execution_attempted": True,
                    "blockers": [
                        {
                            "code": "HouseInvalidForTask",
                            "message": "robot placement failed near object",
                        }
                    ],
                    "cleanup_task_config": {
                        "scene_xml": "/tmp/scene.xml",
                        "planner_object_id": "pickup/body",
                    },
                    "task_sampler_robot_placement_profile": {
                        "profile": "relaxed",
                        "requested": True,
                        "applied": True,
                        "place_robot_near_overrides": {"max_tries": 50},
                    },
                    "cleanup_task_sampler_adapter": {
                        "applied": True,
                        "task_sampler_class": "PickAndPlaceTaskSampler",
                        "planner_target_receptacle_id": "sink/body",
                    },
                    "task_sampler_failure_diagnostics": {
                        "applied": True,
                        "task_sampler_class": "PickAndPlaceTaskSampler",
                        "robot_placement_attempt_count": 1,
                        "robot_placement_failure_count": 1,
                        "asset_failure_count": 1,
                        "grasp_failure_count": 3,
                        "grasp_failures": [
                            {
                                "object_name": "pickup/body",
                                "count_after": 3,
                                "removed_candidate": True,
                            }
                        ],
                        "last_placement_scene_diagnostic": {
                            "target_name": "pickup/body",
                            "valid_free_point_count": 3,
                            "valid_neighborhood_fraction": 0.000017,
                        },
                        "last_robot_placement_failure": {
                            "pickup_obj_name": "pickup/body",
                            "message": "Failed to place robot near object: pickup/body",
                        },
                    },
                    "requested_cleanup_primitive_binding": {
                        "scene_xml": "/tmp/scene.xml",
                        "planner_object_id": "pickup/body",
                        "planner_target_receptacle_id": "sink/body",
                    },
                    "image_artifacts": {
                        "initial": "planner_views/initial.png",
                        "final": "planner_views/final.png",
                    },
                },
            }
        ),
        encoding="utf-8",
    )
    commands = [
        {
            "request_id": "proof_001",
            "object_id": "observed_001",
            "target_receptacle_id": "sink_01",
            "run_result": str(proof_dir / "run_result.json"),
            "report": str(proof_dir / "report.html"),
        },
        {
            "request_id": "proof_002",
            "object_id": "observed_002",
            "target_receptacle_id": "shelf_01",
            "run_result": str(tmp_path / "missing" / "run_result.json"),
            "report": str(tmp_path / "missing" / "report.html"),
        },
    ]

    summary = proof_result_summary_from_commands(commands)

    assert summary["schema"] == "planner_cleanup_proof_result_summary_v1"
    assert summary["expected_count"] == 2
    assert summary["result_count"] == 1
    assert summary["missing_result_count"] == 1
    assert summary["task_feasibility_blocked_count"] == 1
    assert summary["view_artifact_count"] == 2
    assert summary["proof_quality_summary"]["quality_tier_counts"] == {"unknown": 1}
    result = summary["results"][0]
    assert result["proof_quality"]["quality_tier"] == "unknown"
    assert result["task_feasibility_status"] == "blocked"
    assert result["task_feasibility_blocker_kind"] == "robot_placement"
    assert result["task_feasibility_blocker_summary"] == "1 robot-placement failures"
    assert result["visual_status"] == "views_recorded"
    assert result["blockers"][0]["code"] == "HouseInvalidForTask"
    assert result["cleanup_task_sampler_adapter"]["applied"] is True
    assert result["cleanup_task_sampler_adapter"]["planner_target_receptacle_id"] == "sink/body"
    assert result["task_sampler_robot_placement_profile"]["profile"] == "relaxed"
    assert (
        result["task_sampler_robot_placement_profile"]["place_robot_near_overrides"]["max_tries"]
        == 50
    )
    assert result["task_sampler_failure_diagnostics"]["robot_placement_failure_count"] == 1
    assert result["task_sampler_failure_diagnostics"]["grasp_failure_count"] == 3
    assert (
        result["task_sampler_failure_diagnostics"]["last_placement_scene_diagnostic"][
            "valid_free_point_count"
        ]
        == 3
    )
    assert (
        result["task_sampler_failure_diagnostics"]["last_robot_placement_failure"][
            "pickup_obj_name"
        ]
        == "pickup/body"
    )
    assert result["views"][0]["path"].endswith("planner_views/final.png")
    assert summary["results"][1]["task_feasibility_status"] == "not_run"


def test_proof_result_summary_surfaces_non_object_run_result_source_error(
    tmp_path: Path,
) -> None:
    proof_dir = tmp_path / "proofs" / "001_observed_001_to_sink_01"
    proof_dir.mkdir(parents=True)
    (proof_dir / "run_result.json").write_text('["not", "a", "packet"]', encoding="utf-8")

    summary = proof_result_summary_from_commands(
        [
            {
                "request_id": "proof_001",
                "object_id": "observed_001",
                "target_receptacle_id": "sink_01",
                "run_result": str(proof_dir / "run_result.json"),
                "report": str(proof_dir / "report.html"),
            }
        ]
    )

    assert summary["result_count"] == 1
    assert summary["missing_result_count"] == 0
    result = summary["results"][0]
    assert result["run_result_exists"] is True
    assert result["status"] == "unreadable"
    assert result["task_feasibility_status"] == "unknown"
    assert result["visual_status"] == "unknown"
    assert result["blockers"][0]["code"] == "proof_run_result_unreadable"
    assert "non-object JSON: list" in result["blockers"][0]["message"]


def test_proof_result_summary_surfaces_malformed_run_result_source_error(
    tmp_path: Path,
) -> None:
    proof_dir = tmp_path / "proofs" / "001_observed_001_to_sink_01"
    proof_dir.mkdir(parents=True)
    (proof_dir / "run_result.json").write_text("{bad json\n", encoding="utf-8")

    summary = proof_result_summary_from_commands(
        [
            {
                "request_id": "proof_001",
                "object_id": "observed_001",
                "target_receptacle_id": "sink_01",
                "run_result": str(proof_dir / "run_result.json"),
                "report": str(proof_dir / "report.html"),
            }
        ]
    )

    result = summary["results"][0]
    assert result["run_result_exists"] is True
    assert result["status"] == "unreadable"
    assert result["blockers"][0]["code"] == "proof_run_result_unreadable"
    assert "JSONDecodeError:" in result["blockers"][0]["message"]


def test_proof_result_summary_carries_planner_proof_quality(tmp_path: Path) -> None:
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

    summary = proof_result_summary_from_commands(
        [
            {
                "request_id": "proof_001",
                "object_id": "observed_001",
                "target_receptacle_id": "sink_01",
                "run_result": str(proof_dir / "run_result.json"),
                "report": str(proof_dir / "report.html"),
            }
        ]
    )

    result = summary["results"][0]
    assert result["proof_quality"]["quality_tier"] == "multi_step_motion"
    assert result["steps_executed"] == 2
    assert summary["proof_quality_summary"]["quality_tier_counts"] == {"multi_step_motion": 1}


def test_proof_result_summary_classifies_grasp_feasibility_blocker(tmp_path: Path) -> None:
    proof_dir = tmp_path / "proofs" / "001_observed_001_to_shelf_01"
    proof_dir.mkdir(parents=True)
    (proof_dir / "run_result.json").write_text(
        json.dumps(
            {
                "status": "blocked_capability",
                "manipulation_evidence": {
                    "execution_attempted": True,
                    "blockers": [
                        {
                            "code": "HouseInvalidForTask",
                            "message": "House invalid for tasks due to physics constraints",
                        }
                    ],
                    "task_sampler_failure_diagnostics": {
                        "applied": True,
                        "robot_placement_attempt_count": 17,
                        "robot_placement_failure_count": 0,
                        "grasp_failure_count": 17,
                        "candidate_removal_count": 15,
                        "grasp_failures": [
                            {
                                "object_name": "book/body",
                                "count_after": 17,
                                "removed_candidate": False,
                            }
                        ],
                    },
                },
            }
        ),
        encoding="utf-8",
    )
    commands = [
        {
            "request_id": "proof_001",
            "object_id": "observed_001",
            "target_receptacle_id": "shelf_01",
            "run_result": str(proof_dir / "run_result.json"),
            "report": str(proof_dir / "report.html"),
        }
    ]

    summary = proof_result_summary_from_commands(commands)

    assert summary["grasp_feasibility_blocked_count"] == 1
    result = summary["results"][0]
    assert result["task_feasibility_status"] == "blocked"
    assert result["task_feasibility_blocker_kind"] == "grasp_feasibility"
    assert result["task_feasibility_blocker_summary"] == (
        "17 grasp failures; 15 candidate-removal calls"
    )


def test_proof_result_summary_surfaces_timeout_worker_stage_evidence(
    tmp_path: Path,
) -> None:
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
                        {
                            "event": "worker_start",
                            "stage": "worker_start",
                            "elapsed_s": 0.1,
                            "runtime_diagnostics": {"large": "omitted from bundle"},
                        },
                        {
                            "event": "rby1m_config_import_start",
                            "stage": "rby1m_config_import",
                            "elapsed_s": 3.2,
                        },
                    ],
                },
            }
        ),
        encoding="utf-8",
    )
    commands = [
        {
            "request_id": "proof_001_fallback_01",
            "object_id": "observed_001",
            "target_receptacle_id": "sink_01",
            "run_result": str(proof_dir / "run_result.json"),
            "report": str(proof_dir / "report.html"),
        }
    ]

    summary = proof_result_summary_from_commands(commands)

    assert summary["timeout_count"] == 1
    assert summary["rby1m_config_import_timeout_count"] == 1
    assert summary["execution_attempted_count"] == 0
    assert summary["worker_stage_event_count"] == 2
    assert summary["last_worker_stage_counts"] == {"rby1m_config_import": 1}
    result = summary["results"][0]
    assert result["task_feasibility_status"] == "not_reached"
    assert result["last_worker_stage"] == "rby1m_config_import"
    assert result["worker_stage_event_count"] == 2
    assert result["worker_stage_events"][0] == {
        "elapsed_s": 0.1,
        "event": "worker_start",
        "stage": "worker_start",
    }
    assert "runtime_diagnostics" not in result["worker_stage_events"][0]
    assert result["stdout"].endswith("planner_probe_stdout.txt")
    assert result["stderr"].endswith("planner_probe_stderr.txt")
