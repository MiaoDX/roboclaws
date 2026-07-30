from __future__ import annotations

from pathlib import Path

from roboclaws.household.manipulation_contract import API_SEMANTIC_PROVENANCE
from roboclaws.household.manipulation_provenance import (
    api_semantic_manipulation_evidence,
)
from roboclaws.household.report import (
    render_cleanup_report,
)
from roboclaws.household.report_planner import (
    render_planner_proof_bundle_runner_report,
)
from roboclaws.household.report_snapshots import write_state_snapshot
from roboclaws.household.scenario import build_cleanup_scenario
from roboclaws.household.scoring import score_cleanup
from tests.contract.reports.molmo_cleanup_report_support import (
    _assert_planner_proof_bundle_runner_artifacts,
    _assert_planner_proof_bundle_runner_overview,
    _assert_planner_proof_bundle_runner_proof_results,
    _assert_planner_proof_bundle_runner_sampler_diagnostics,
    _assert_planner_proof_bundle_runner_selection,
    _proof_attachment,
)


def test_cleanup_report_renders_planner_proof_requests_before_agent_view(
    tmp_path: Path,
) -> None:
    scenario = build_cleanup_scenario(seed=7)
    score = score_cleanup(scenario.object_locations(), scenario.private_manifest)
    before = write_state_snapshot(
        scenario,
        scenario.object_locations(),
        tmp_path / "before.png",
        title="Before",
    )
    after = write_state_snapshot(
        scenario,
        scenario.object_locations(),
        tmp_path / "after.png",
        title="After",
    )
    run_result = {
        "contract": "realworld_cleanup_v1",
        "cleanup_status": "success",
        "primitive_provenance": API_SEMANTIC_PROVENANCE,
        "score": score.to_dict(),
        "planner_cleanup_bridge_evidence": {
            "status": "blocked_capability",
            "target_runtime": {"embodiment": "rby1m"},
            "cleanup_primitives": {"status": "blocked_capability", "subphase_count": 4},
            "blockers": [],
            "target_runtime_ready": True,
            "cleanup_primitives_ready": False,
            "planner_backed": False,
        },
        "planner_proof_requests": {
            "schema": "planner_cleanup_proof_requests_v1",
            "request_count": 2,
            "ready_count": 1,
            "agent_view_exposed": False,
            "blockers": [{"code": "planner_binding_backend_unavailable"}],
            "requests": [
                {
                    "request_id": "proof_001",
                    "ready": True,
                    "object_id": "observed_001",
                    "source_receptacle_id": "counter_01",
                    "target_receptacle_id": "sink_01",
                    "tools": [
                        "navigate_to_object",
                        "pick",
                        "navigate_to_receptacle",
                        "place",
                    ],
                    "binding": {
                        "planner_object_id": "pickup/body",
                        "planner_target_receptacle_id": "sink/body",
                    },
                    "planner_probe_args": {},
                    "blockers": [],
                },
                {
                    "request_id": "proof_002",
                    "ready": False,
                    "object_id": "observed_002",
                    "source_receptacle_id": "table_01",
                    "target_receptacle_id": "cabinet_01",
                    "tools": ["navigate_to_object"],
                    "binding": {},
                    "planner_probe_args": {},
                    "blockers": [{"code": "planner_binding_backend_unavailable"}],
                },
            ],
        },
        "agent_view": {
            "contract": "realworld_cleanup_v1",
            "metric_map": {"rooms": [], "inspection_waypoints": []},
            "static_fixture_projection": {"rooms": []},
            "observed_objects": [{"object_id": "observed_001", "category": "dish"}],
        },
        "private_evaluation": {
            "generated_mess_count": 1,
            "generated_mess_set": ["mug_01"],
            "acceptable_destination_sets": {"mug_01": ["sink_01"]},
        },
    }

    report_path = render_cleanup_report(
        run_dir=tmp_path,
        scenario=scenario,
        run_result=run_result,
        trace_events=[],
        before_snapshot=before,
        after_snapshot=after,
    )

    html = report_path.read_text(encoding="utf-8")
    ordered_headings = [
        "<h2>Planner Cleanup Bridge</h2>",
        "<h2>Planner Proof Requests</h2>",
        "<h2>Agent View</h2>",
    ]
    positions = [html.index(heading) for heading in ordered_headings]
    assert positions == sorted(positions)
    assert "Requests" in html
    assert "proof_001" in html
    assert "ready" in html
    assert "blocked" in html
    assert "observed_001" in html
    assert "counter_01" in html
    assert "sink_01" in html
    assert "navigate_to_object, pick, navigate_to_receptacle, place" in html
    assert "pickup/body" in html
    assert "sink/body" in html
    assert "planner_binding_backend_unavailable" in html
    agent_view_html = html[html.index("<h2>Agent View</h2>") :]
    assert "pickup/body" not in agent_view_html
    assert "sink/body" not in agent_view_html


def test_planner_proof_bundle_runner_report_renders_commands(tmp_path: Path) -> None:
    manifest = {
        "schema": "planner_cleanup_proof_bundle_run_manifest_v1",
        "status": "dry_run",
        "cleanup_run_result": str(tmp_path / "cleanup" / "run_result.json"),
        "output_dir": str(tmp_path),
        "proof_request_count": 1,
        "ready_request_count": 1,
        "proof_execution_horizon": {
            "schema": "planner_cleanup_proof_execution_horizon_v1",
            "status": "aligned",
            "command_steps": 2,
            "command_quality_target": "multi_step_motion",
            "prior_covered_min_proof_steps": 1,
            "prior_covered_quality_floor": "one_step_motion",
            "blockers": [],
            "evidence_note": "requested horizon",
        },
        "proof_request_selection": {
            "schema": "planner_cleanup_proof_request_selection_v1",
            "mode": "exclude_task_feasibility_blocked",
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
                            "--cleanup-object-id": "observed_001",
                            "--cleanup-target-receptacle-id": "sink_01",
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
                        "alias": "sink/body_alt",
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
        },
        "warmup": {
            "kind": "rby1m_curobo_config_import",
            "output_dir": str(tmp_path / "warmup"),
            "run_result": str(tmp_path / "warmup" / "run_result.json"),
            "report": str(tmp_path / "warmup" / "report.html"),
            "command": [
                "python",
                "probe.py",
                "--probe-mode",
                "config_import",
                "--torch-extensions-dir",
                str(tmp_path / "torch_extensions"),
            ],
        },
        "prior_proof_result_summary": {
            "schema": "merged_prior_planner_proof_result_summary_v1",
            "result_count": 1,
            "view_artifact_count": 2,
            "results": [
                {
                    "request_id": "standalone_observed_001_to_sink_01",
                    "object_id": "observed_001",
                    "target_receptacle_id": "sink_01",
                    "run_result": str(tmp_path / "prior-proof" / "run_result.json"),
                    "report": str(tmp_path / "prior-proof" / "report.html"),
                    "status": "blocked_capability",
                    "task_feasibility_status": "blocked",
                    "task_feasibility_blocker_kind": "grasp_feasibility",
                    "task_feasibility_blocker_summary": (
                        "3 grasp failures; 1 candidate-removal calls"
                    ),
                    "grasp_feasibility_signature": {
                        "schema": "planner_grasp_feasibility_signature_v1",
                        "kind": "grasp_feasibility",
                        "subkind": "grasp_cache_missing",
                        "pattern_key": "prior-grasp-cache-missing",
                        "summary": (
                            "3 grasp failures; 1 candidate-removal calls; "
                            "3 grasp-load failures; missing grasp cache: PriorBread_1"
                        ),
                        "grasp_failure_count": 3,
                        "candidate_removal_count": 1,
                        "grasp_load_attempt_count": 3,
                        "grasp_load_failure_count": 3,
                        "grasp_collision_check_count": 0,
                        "zero_noncolliding_grasp_check_count": 0,
                        "grasp_load_exception_asset_uids": ["PriorBread_1"],
                        "grasp_load_exception_types": ["ValueError"],
                        "robot_placement_attempt_count": 1,
                        "robot_placement_failure_count": 0,
                        "place_robot_near_call_count": 1,
                        "object_name_count": 1,
                        "object_names": ["prior/pickup"],
                        "image_artifact_count": 2,
                    },
                    "views": [
                        {
                            "label": "initial",
                            "path": str(tmp_path / "prior-proof" / "initial.png"),
                        },
                        {
                            "label": "final",
                            "path": str(tmp_path / "prior-proof" / "final.png"),
                        },
                    ],
                }
            ],
        },
        "command_count": 1,
        "commands": [
            {
                "request_id": "proof_001_fallback_01",
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
                "run_result": str(tmp_path / "proofs" / "001" / "run_result.json"),
                "report": str(tmp_path / "proofs" / "001" / "report.html"),
                "command": [
                    "python",
                    "probe.py",
                    "--cleanup-object-id",
                    "observed_001",
                    "--cleanup-planner-target-receptacle-id",
                    "sink/alt",
                ],
            }
        ],
        "proof_result_summary": {
            "schema": "planner_cleanup_proof_result_summary_v1",
            "expected_count": 1,
            "result_count": 1,
            "planner_backed_count": 0,
            "blocked_count": 1,
            "timeout_count": 1,
            "rby1m_config_import_timeout_count": 1,
            "missing_result_count": 0,
            "cleanup_binding_promoted_count": 0,
            "execution_attempted_count": 0,
            "task_feasibility_blocked_count": 1,
            "grasp_feasibility_blocked_count": 1,
            "grasp_feasibility_signature_count": 1,
            "grasp_feasibility_signature_counts": [
                {
                    "schema": "planner_grasp_feasibility_signature_group_v1",
                    "pattern_key": "grasp=3;removals=1",
                    "subkind": "grasp_cache_missing",
                    "summary": (
                        "3 grasp failures; 1 candidate-removal calls; "
                        "3 grasp-load failures; missing grasp cache: Bread_1"
                    ),
                    "count": 1,
                    "request_ids": ["proof_001"],
                    "object_names": ["pickup/body"],
                    "grasp_load_failure_count": 3,
                    "grasp_collision_check_count": 0,
                    "zero_noncolliding_grasp_check_count": 0,
                    "grasp_load_exception_asset_uids": ["Bread_1"],
                    "grasp_load_exception_types": ["ValueError"],
                    "robot_placement_failure_count": 1,
                    "place_robot_near_call_count": 1,
                    "image_artifact_count": 2,
                }
            ],
            "worker_stage_event_count": 2,
            "last_worker_stage_counts": {"rby1m_config_import": 1},
            "view_artifact_count": 2,
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
                    "execution_attempted": False,
                    "task_feasibility_status": "blocked",
                    "task_feasibility_blocker_kind": "grasp_feasibility",
                    "task_feasibility_blocker_summary": (
                        "3 grasp failures; 1 candidate-removal calls"
                    ),
                    "grasp_feasibility_signature": {
                        "schema": "planner_grasp_feasibility_signature_v1",
                        "kind": "grasp_feasibility",
                        "subkind": "grasp_cache_missing",
                        "pattern_key": "grasp=3;removals=1",
                        "summary": (
                            "3 grasp failures; 1 candidate-removal calls; "
                            "3 grasp-load failures; missing grasp cache: Bread_1"
                        ),
                        "grasp_failure_count": 3,
                        "candidate_removal_count": 1,
                        "grasp_load_attempt_count": 3,
                        "grasp_load_failure_count": 3,
                        "grasp_collision_check_count": 0,
                        "zero_noncolliding_grasp_check_count": 0,
                        "grasp_load_exception_asset_uids": ["Bread_1"],
                        "grasp_load_exception_types": ["ValueError"],
                        "robot_placement_attempt_count": 1,
                        "robot_placement_failure_count": 1,
                        "place_robot_near_call_count": 1,
                        "object_name_count": 1,
                        "object_names": ["pickup/body"],
                        "image_artifact_count": 2,
                    },
                    "visual_status": "views_recorded",
                    "blockers": [
                        {"code": "HouseInvalidForTask", "message": "robot placement"},
                        {"code": "timeout", "message": "Probe exceeded 1.0s"},
                    ],
                    "cleanup_binding_blockers": [],
                    "last_worker_stage": "rby1m_config_import",
                    "worker_stage_event_count": 2,
                    "worker_stage_events": [
                        {"elapsed_s": 0.1, "event": "worker_start", "stage": "worker_start"},
                        {
                            "elapsed_s": 3.2,
                            "event": "rby1m_config_import_start",
                            "stage": "rby1m_config_import",
                        },
                    ],
                    "stdout": str(tmp_path / "proofs" / "001" / "planner_probe_stdout.txt"),
                    "stderr": str(tmp_path / "proofs" / "001" / "planner_probe_stderr.txt"),
                    "requested_cleanup_primitive_binding": {
                        "scene_xml": "/tmp/scene.xml",
                        "planner_object_id": "pickup/body",
                        "planner_target_receptacle_id": "sink/body",
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
                        "candidate_name_miss_count": 0,
                        "grasp_failures": [
                            {
                                "object_name": "pickup/body",
                                "count_before": 2,
                                "count_after": 3,
                                "max_failures": 2,
                                "candidate_count_before": 1,
                                "candidate_count_after": 0,
                                "removed_candidate": True,
                            }
                        ],
                        "last_placement_scene_diagnostic": {
                            "target_name": "pickup/body",
                            "valid_free_point_count": 3,
                            "valid_neighborhood_fraction": 0.000017,
                            "nearest_free_point_distance_m": 0.42,
                        },
                        "last_robot_placement_failure": {
                            "pickup_obj_name": "pickup/body",
                            "message": "Failed to place robot near object: pickup/body",
                        },
                    },
                    "views": [
                        {
                            "label": "initial",
                            "path": str(tmp_path / "proofs" / "001" / "initial.png"),
                        },
                        {
                            "label": "final",
                            "path": str(tmp_path / "proofs" / "001" / "final.png"),
                        },
                    ],
                }
            ],
        },
        "grasp_feasibility_mitigation_decision": {
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
            "missing_grasp_asset_uids": ["Bread_1"],
            "grasp_load_exception_types": ["ValueError"],
            "evidence_request_ids": ["proof_001"],
            "signature_groups": [
                {
                    "source": "proof_result_summary",
                    "subkind": "grasp_cache_missing",
                    "count": 1,
                    "summary": "3 grasp-load failures; missing grasp cache: Bread_1",
                    "request_ids": ["proof_001"],
                    "object_names": ["pickup/body"],
                    "grasp_load_exception_asset_uids": ["Bread_1"],
                    "grasp_load_exception_types": ["ValueError"],
                }
            ],
        },
        "grasp_cache_availability_preflight": {
            "schema": "planner_grasp_cache_availability_preflight_v1",
            "status": "missing_cache",
            "assets_dir": str(tmp_path / "assets"),
            "assets_dir_source": "argument",
            "assets_dir_exists": True,
            "missing_grasp_asset_uids": ["Bread_1"],
            "asset_count": 1,
            "ready_asset_count": 0,
            "missing_cache_asset_count": 1,
            "cache_ready_asset_uids": [],
            "cache_missing_asset_uids": ["Bread_1"],
            "loader_sources": ["droid", "droid_objaverse", "rum"],
            "mitigation_recommendation": "generate_or_install_rigid_grasp_cache_before_retry",
            "upstream_loader": "molmo_spaces.utils.grasp_sample.load_grasps_for_object",
            "evidence_note": "Preflights the rigid-object grasp files used by MolmoSpaces.",
            "assets": [
                {
                    "asset_uid": "Bread_1",
                    "status": "missing_cache",
                    "loader_file_status": "missing",
                    "object_asset_status": "present",
                    "candidate_grasp_files": [
                        {
                            "asset_uid": "Bread_1",
                            "source": "droid",
                            "gripper": "droid",
                            "loader_role": "rigid_object_loader",
                            "path": str(
                                tmp_path
                                / "assets"
                                / "grasps"
                                / "droid"
                                / "Bread_1"
                                / "Bread_1_grasps_filtered.npz"
                            ),
                            "relative_path": ("grasps/droid/Bread_1/Bread_1_grasps_filtered.npz"),
                            "exists": False,
                            "size_bytes": 0,
                        },
                        {
                            "asset_uid": "Bread_1",
                            "source": "droid_objaverse",
                            "gripper": "droid",
                            "loader_role": "rigid_object_loader",
                            "path": str(
                                tmp_path
                                / "assets"
                                / "grasps"
                                / "droid_objaverse"
                                / "Bread_1"
                                / "Bread_1_grasps_filtered.npz"
                            ),
                            "relative_path": (
                                "grasps/droid_objaverse/Bread_1/Bread_1_grasps_filtered.npz"
                            ),
                            "exists": False,
                            "size_bytes": 0,
                        },
                        {
                            "asset_uid": "Bread_1",
                            "source": "rum",
                            "gripper": "rum",
                            "loader_role": "rigid_object_loader",
                            "path": str(
                                tmp_path
                                / "assets"
                                / "grasps"
                                / "rum"
                                / "Bread_1"
                                / "Bread_1_grasps_filtered.json"
                            ),
                            "relative_path": ("grasps/rum/Bread_1/Bread_1_grasps_filtered.json"),
                            "exists": False,
                            "size_bytes": 0,
                        },
                    ],
                    "folder_probe_files": [
                        {
                            "asset_uid": "Bread_1",
                            "source": "droid",
                            "gripper": "droid",
                            "loader_role": "has_grasp_folder_only",
                            "path": str(
                                tmp_path
                                / "assets"
                                / "grasps"
                                / "droid"
                                / "Bread_1"
                                / "Bread_1_joint_grasps_filtered.npz"
                            ),
                            "relative_path": (
                                "grasps/droid/Bread_1/Bread_1_joint_grasps_filtered.npz"
                            ),
                            "exists": False,
                            "size_bytes": 0,
                        }
                    ],
                    "object_asset_files": [
                        {
                            "kind": "xml",
                            "path": str(tmp_path / "assets" / "objects" / "thor" / "Bread_1.xml"),
                            "relative_path": "objects/thor/Bread_1.xml",
                            "exists": True,
                            "size_bytes": 10,
                        }
                    ],
                }
            ],
        },
        "grasp_cache_generation_preflight": {
            "schema": "planner_grasp_cache_generation_preflight_v1",
            "status": "blocked",
            "ready": False,
            "asset_count": 1,
            "blocker_count": 2,
            "molmospaces_python": str(tmp_path / "molmospaces-python"),
            "molmospaces_root": str(tmp_path / "molmospaces"),
            "assets_dir": str(tmp_path / "assets"),
            "objects_list_path": str(tmp_path / "grasp_generation" / "rigid_objects_list.json"),
            "working_dir": str(tmp_path / "molmospaces" / "molmo_spaces" / "grasp_generation"),
            "command": [
                str(tmp_path / "molmospaces-python"),
                str(
                    tmp_path / "molmospaces" / "molmo_spaces" / "grasp_generation" / "run_rigid.py"
                ),
                "--objects_list",
                str(tmp_path / "grasp_generation" / "rigid_objects_list.json"),
            ],
            "mitigation_recommendation": (
                "install_grasp_generation_prerequisites_before_cache_generation"
            ),
            "evidence_note": "Preflights rigid grasp generation.",
            "assets": [
                {
                    "asset_uid": "Bread_1",
                    "object_xml": str(tmp_path / "assets" / "objects" / "thor" / "Bread_1.xml"),
                    "object_xml_exists": True,
                    "generated_npz_path": str(
                        tmp_path
                        / "molmospaces"
                        / "grasp_results"
                        / "rigid_objects"
                        / "Bread_1"
                        / "Bread_1_grasps_filtered.npz"
                    ),
                    "cache_target_resolved_path": str(
                        tmp_path
                        / "assets"
                        / "grasps"
                        / "droid"
                        / "Bread_1"
                        / "Bread_1_grasps_filtered.npz"
                    ),
                }
            ],
            "checks": [
                {
                    "name": "python_module_sklearn",
                    "status": "blocked",
                    "code": "sklearn_missing",
                    "message": "No module named sklearn",
                },
                {
                    "name": "manifold_executable",
                    "status": "blocked",
                    "code": "manifold_executable_missing",
                    "path": str(
                        tmp_path
                        / "molmospaces"
                        / "external_src"
                        / "Manifold"
                        / "build"
                        / "manifold"
                    ),
                    "message": "Required path is not ready",
                },
            ],
            "blockers": [
                {
                    "code": "sklearn_missing",
                    "name": "python_module_sklearn",
                    "message": "No module named sklearn",
                },
                {
                    "code": "manifold_executable_missing",
                    "name": "manifold_executable",
                    "message": "Required path is not ready",
                },
            ],
        },
        "cleanup_command": ["python", "cleanup.py", "--planner-proof-run-result", "proof.json"],
    }

    report_path = render_planner_proof_bundle_runner_report(
        output_dir=tmp_path,
        manifest=manifest,
    )

    html = report_path.read_text(encoding="utf-8")
    _assert_planner_proof_bundle_runner_overview(html)
    _assert_planner_proof_bundle_runner_selection(html)
    _assert_planner_proof_bundle_runner_proof_results(html, tmp_path)
    _assert_planner_proof_bundle_runner_sampler_diagnostics(html)
    _assert_planner_proof_bundle_runner_artifacts(html)


def test_cleanup_report_renders_attached_planner_proof(tmp_path: Path) -> None:
    scenario = build_cleanup_scenario(seed=7)
    score = score_cleanup(scenario.object_locations(), scenario.private_manifest)
    before = write_state_snapshot(
        scenario,
        scenario.object_locations(),
        tmp_path / "before.png",
        title="Before",
    )
    after = write_state_snapshot(
        scenario,
        scenario.object_locations(),
        tmp_path / "after.png",
        title="After",
    )
    proof_dir = tmp_path / "planner_proof"
    proof_dir.mkdir()
    (proof_dir / "initial.png").write_bytes(b"initial")
    (proof_dir / "final.png").write_bytes(b"final")
    run_result = {
        "contract": "realworld_cleanup_v1",
        "cleanup_status": score.status,
        "primitive_provenance": API_SEMANTIC_PROVENANCE,
        "manipulation_evidence": api_semantic_manipulation_evidence(
            backend="api_semantic_synthetic",
            primitive_summary={API_SEMANTIC_PROVENANCE: 1},
        ),
        "score": score.to_dict(),
        "planner_backed_manipulation_proof": {
            "schema": "planner_backed_cleanup_attachment_v1",
            "status": "planner_backed",
            "primitive_provenance": "planner_backed",
            "planner_backed": True,
            "strict_proof_eligible": True,
            "embodiment": "franka",
            "steps_executed": 2,
            "max_abs_qpos_delta": 0.01,
            "runtime_diagnostics": {"renderer_adapter_enabled": True},
            "image_artifacts": {
                "initial": "planner_proof/initial.png",
                "final": "planner_proof/final.png",
            },
        },
    }

    report_path = render_cleanup_report(
        run_dir=tmp_path,
        scenario=scenario,
        run_result=run_result,
        trace_events=[],
        before_snapshot=before,
        after_snapshot=after,
    )

    html = report_path.read_text(encoding="utf-8")
    assert "Attached Planner-Backed Proof" in html
    assert "Proof Quality" in html
    assert "multi_step_motion" in html
    assert "Containment proven" in html
    assert "Planner Initial" in html
    assert "Planner Final" in html
    assert "Cleanup object moves" in html
    assert "api_semantic" in html
    assert "planner_proof/initial.png" in html
    assert "planner_proof/final.png" in html


def test_cleanup_report_renders_attached_planner_proof_bundle(tmp_path: Path) -> None:
    scenario = build_cleanup_scenario(seed=7)
    score = score_cleanup(scenario.object_locations(), scenario.private_manifest)
    before = write_state_snapshot(
        scenario,
        scenario.object_locations(),
        tmp_path / "before.png",
        title="Before",
    )
    after = write_state_snapshot(
        scenario,
        scenario.object_locations(),
        tmp_path / "after.png",
        title="After",
    )
    for proof_id in ("proof_001", "proof_002"):
        proof_dir = tmp_path / "planner_proof" / proof_id
        proof_dir.mkdir(parents=True)
        (proof_dir / "initial.png").write_bytes(b"initial")
        (proof_dir / "final.png").write_bytes(b"final")
    run_result = {
        "contract": "realworld_cleanup_v1",
        "cleanup_status": score.status,
        "primitive_provenance": "planner_backed",
        "manipulation_evidence": api_semantic_manipulation_evidence(
            backend="api_semantic_synthetic",
            primitive_summary={"planner_backed": 8},
        ),
        "score": score.to_dict(),
        "planner_backed_manipulation_proof": {
            "schema": "planner_backed_cleanup_proof_bundle_v1",
            "status": "planner_backed",
            "primitive_provenance": "planner_backed",
            "planner_backed": True,
            "strict_proof_eligible": True,
            "proof_count": 2,
            "attachments": [
                _proof_attachment("proof_001", "observed_001", "sink_01"),
                _proof_attachment("proof_002", "observed_002", "toy_bin_01"),
            ],
        },
    }

    report_path = render_cleanup_report(
        run_dir=tmp_path,
        scenario=scenario,
        run_result=run_result,
        trace_events=[],
        before_snapshot=before,
        after_snapshot=after,
    )

    html = report_path.read_text(encoding="utf-8")
    assert "Attached Planner-Backed Proofs" in html
    assert "Proof Quality" in html
    assert "multi_step_motion=2" in html
    assert "proof_001 Planner Initial" in html
    assert "proof_002 Planner Final" in html
    assert "observed_001" in html
    assert "toy_bin_01" in html
    assert "planner_proof/proof_001/initial.png" in html
    assert "planner_proof/proof_002/final.png" in html
