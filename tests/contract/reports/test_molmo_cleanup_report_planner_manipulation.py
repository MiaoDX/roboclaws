from __future__ import annotations

from pathlib import Path

from roboclaws.household.manipulation_provenance import (
    blocked_planner_probe_evidence,
    planner_backed_probe_evidence,
)
from roboclaws.household.rby1m_curobo_gate import (
    rby1m_curobo_gate_from_planner_probe,
)
from roboclaws.household.report_planner import (
    render_planner_manipulation_report,
)
from tests.contract.reports.molmo_cleanup_report_support import (
    _assert_planner_manipulation_probe_cleanup_binding,
    _assert_planner_manipulation_probe_overview,
    _assert_planner_manipulation_probe_runtime_diagnostics,
    _assert_planner_manipulation_probe_sampler_failures,
)


def test_planner_manipulation_probe_report_uses_shared_underlay(tmp_path: Path) -> None:
    stdout = tmp_path / "planner_probe_stdout.txt"
    stderr = tmp_path / "planner_probe_stderr.txt"
    stdout.write_text("{}", encoding="utf-8")
    stderr.write_text("", encoding="utf-8")
    run_result = {
        "contract": "planner_backed_manipulation_probe_v1",
        "backend": "molmospaces_subprocess",
        "status": "blocked_capability",
        "primitive_provenance": "blocked_capability",
        "manipulation_evidence": blocked_planner_probe_evidence(
            backend="molmospaces_subprocess",
            embodiment="franka",
            task="pick_and_place",
            probe_mode="config_import",
            blockers=[
                {
                    "code": "execution_not_attempted",
                    "message": "Planner execution was not attempted.",
                }
            ],
            upstream_policy_class="PickAndPlacePlannerPolicy",
        ),
        "artifacts": {
            "stdout": str(stdout),
            "stderr": str(stderr),
        },
    }
    run_result["manipulation_evidence"]["runtime_diagnostics"] = {
        "python_executable": "/tmp/molmospaces/.venv/bin/python",
        "python_version": "3.11.8",
        "faulthandler_enabled": True,
        "renderer_adapter_enabled": True,
        "renderer_device_id": 0,
        "mujoco_gl_env": "egl",
        "pyopengl_platform_env": "egl",
        "cuda_home_env": "/usr/local/cuda",
        "torch_cuda_arch_list_env": "8.9",
        "torch": {
            "available": True,
            "version": "2.7.1+cu128",
            "cuda_version": "12.8",
            "cuda_available": True,
            "cpp_extension_cuda_home": "/usr/local/cuda",
        },
        "cuda_visible_devices_env": "0",
        "pytorch_cuda_alloc_conf_env": "expandable_segments:True",
        "cuda_memory": {
            "available": True,
            "device_count": 1,
            "current_device_index": 0,
            "devices": [
                {
                    "index": 0,
                    "name": "NVIDIA RTX 3500 Ada Generation Laptop GPU",
                    "total_memory_bytes": 12884901888,
                    "compute_capability": "8.9",
                }
            ],
            "current_snapshot": {
                "stage": "runtime_diagnostics",
                "elapsed_s": 0.02,
                "device_index": 0,
                "device_name": "NVIDIA RTX 3500 Ada Generation Laptop GPU",
                "free_bytes": 298844160,
                "total_bytes": 12455405158,
                "torch_allocated_bytes": 10458234880,
                "torch_reserved_bytes": 11408506880,
            },
        },
        "modules": {
            "curobo": {"available": False, "version": None},
            "molmo_spaces": {"available": True, "version": "0.1.0"},
        },
        "curobo_extension_cache": {
            "configured_dir": "output/cache",
            "extensions": {
                "lbfgs_step_cu": {
                    "build_dir": "output/cache/lbfgs_step_cu",
                    "so_exists": False,
                    "lock_exists": True,
                    "files": [{"name": "lock", "size_bytes": 0}],
                },
                "geom_cu": {
                    "build_dir": "output/cache/geom_cu",
                    "so_exists": True,
                    "lock_exists": False,
                    "files": [{"name": "geom_cu.so", "size_bytes": 12}],
                },
            },
        },
        "warp_compatibility": {
            "available": True,
            "version": "1.13.0",
            "has_torch_attr": True,
            "has_device_from_torch": True,
            "has_from_torch": True,
            "has_stream_from_torch": True,
            "adapter": {
                "applied": True,
                "provided": ["warp.torch.device_from_torch"],
            },
        },
    }
    run_result["manipulation_evidence"]["worker_stage_events"] = [
        {
            "event": "worker_start",
            "stage": "worker_start",
            "elapsed_s": 0.01,
            "embodiment": "rby1m",
            "probe_mode": "config_import",
        },
        {
            "event": "rby1m_config_import_start",
            "stage": "rby1m_config_import",
            "elapsed_s": 0.02,
        },
    ]
    run_result["manipulation_evidence"]["cuda_memory_snapshots"] = [
        {
            "stage": "execute_policy_construct_before",
            "elapsed_s": 10.2,
            "device_index": 0,
            "device_name": "NVIDIA RTX 3500 Ada Generation Laptop GPU",
            "free_bytes": 2147483648,
            "total_bytes": 12884901888,
            "torch_allocated_bytes": 1073741824,
            "torch_reserved_bytes": 2147483648,
        },
        {
            "stage": "execute_policy_run_start",
            "elapsed_s": 24.5,
            "device_index": 0,
            "device_name": "NVIDIA RTX 3500 Ada Generation Laptop GPU",
            "free_bytes": 298844160,
            "total_bytes": 12455405158,
            "torch_allocated_bytes": 10458234880,
            "torch_reserved_bytes": 11408506880,
        },
    ]
    run_result["manipulation_evidence"]["curobo_memory_profile"] = {
        "profile": "low",
        "applied": True,
        "before": {
            "policy": {
                "batch_size": 4,
                "max_batch_plan_attempts": 4,
                "enable_collision_avoidance": True,
            },
            "planners": {
                "left": {
                    "num_trajopt_seeds": 12,
                    "num_ik_seeds": 128,
                    "max_attempts": 15,
                    "trajopt_tsteps": 48,
                    "enable_finetune_trajopt": True,
                }
            },
        },
        "after": {
            "policy": {
                "batch_size": 1,
                "max_batch_plan_attempts": 1,
                "enable_collision_avoidance": True,
            },
            "planners": {
                "left": {
                    "num_trajopt_seeds": 1,
                    "num_ik_seeds": 16,
                    "max_attempts": 1,
                    "trajopt_tsteps": 24,
                    "enable_finetune_trajopt": False,
                }
            },
        },
    }
    run_result["manipulation_evidence"]["cleanup_task_config"] = {
        "schema": "planner_probe_exact_cleanup_task_config_v1",
        "applied": True,
        "scene_xml": "/tmp/scene.xml",
        "planner_object_id": "pickup/body",
        "planner_target_receptacle_id": "sink/body",
        "blockers": [{"code": "cleanup_scene_xml_missing", "message": "missing stale scene"}],
    }
    run_result["manipulation_evidence"]["task_sampler_robot_placement_profile"] = {
        "schema": "planner_probe_task_sampler_robot_placement_profile_v1",
        "profile": "relaxed",
        "requested": True,
        "applied": True,
        "before": {
            "base_pose_sampling_radius_range": [0.0, 0.7],
            "robot_safety_radius": 0.35,
            "check_robot_placement_visibility": True,
            "max_robot_placement_attempts": 10,
        },
        "after": {
            "base_pose_sampling_radius_range": [0.0, 1.2],
            "robot_safety_radius": 0.15,
            "check_robot_placement_visibility": False,
            "max_robot_placement_attempts": 50,
        },
        "applied_overrides": {"robot_safety_radius": 0.15},
        "place_robot_near_overrides": {"max_tries": 50},
    }
    run_result["manipulation_evidence"]["cleanup_task_sampler_adapter"] = {
        "schema": "planner_probe_exact_cleanup_task_sampler_adapter_v1",
        "applied": True,
        "task_sampler_class": "PickAndPlaceTaskSampler",
        "planner_object_id": "pickup/body",
        "planner_target_receptacle_id": "sink/body",
        "exact_pickup_candidate_binding": {
            "schema": "planner_probe_exact_pickup_candidate_binding_v1",
            "planner_object_id": "pickup/body",
            "candidate_count_before": 17,
            "candidate_count_after": 3,
            "retry_budget": 3,
            "retry_budget_applied": True,
            "requested_present_before": False,
            "requested_present_after": True,
            "action": "injected_requested_candidate_name",
        },
    }
    run_result["manipulation_evidence"]["task_sampler_failure_diagnostics"] = {
        "schema": "planner_probe_task_sampler_failure_diagnostics_v1",
        "applied": True,
        "task_sampler_class": "PickAndPlaceTaskSampler",
        "robot_placement_config": {
            "base_pose_sampling_radius_range": [0.0, 0.7],
            "robot_safety_radius": 0.15,
            "check_robot_placement_visibility": True,
            "max_robot_placement_attempts": 10,
        },
        "hooks": ["_sample_and_place_robot", "report_asset_failure"],
        "robot_placement_attempt_count": 1,
        "robot_placement_failure_count": 1,
        "asset_failure_count": 1,
        "candidate_removal_count": 1,
        "candidate_effective_removal_count": 0,
        "candidate_name_miss_count": 1,
        "grasp_threshold_exceeded_count": 1,
        "robot_placement_attempts": [
            {
                "attempt_index": 1,
                "pickup_obj_name": "pickup/body",
                "asset_uid": "asset-book",
                "result": "failed",
                "exception_type": "RobotPlacementError",
                "message": "Failed to place robot near object: pickup/body",
            }
        ],
        "asset_failures": [
            {
                "asset_uid": "asset-book",
                "reason": "robot placement failed",
            }
        ],
        "grasp_load_attempt_count": 1,
        "grasp_collision_check_count": 1,
        "zero_noncolliding_grasp_check_count": 1,
        "grasp_load_attempts": [
            {
                "schema": "planner_probe_grasp_load_attempt_v1",
                "asset_uid": "asset-book",
                "pickup_obj_name": "pickup/body",
                "requested_grasp_count": 512,
                "result": "loaded",
                "gripper": "droid",
                "cached_grasp_count": 512,
            }
        ],
        "grasp_collision_checks": [
            {
                "schema": "planner_probe_grasp_collision_check_v1",
                "asset_uid": "asset-book",
                "pickup_obj_name": "pickup/body",
                "grasp_pose_count": 512,
                "batch_size": 64,
                "result": "checked",
                "noncolliding_grasp_count": 0,
                "colliding_grasp_count": 512,
                "zero_noncolliding": True,
            }
        ],
        "last_grasp_load_attempt": {
            "schema": "planner_probe_grasp_load_attempt_v1",
            "asset_uid": "asset-book",
            "pickup_obj_name": "pickup/body",
            "requested_grasp_count": 512,
            "result": "loaded",
            "gripper": "droid",
            "cached_grasp_count": 512,
        },
        "last_grasp_collision_check": {
            "schema": "planner_probe_grasp_collision_check_v1",
            "asset_uid": "asset-book",
            "pickup_obj_name": "pickup/body",
            "grasp_pose_count": 512,
            "batch_size": 64,
            "result": "checked",
            "noncolliding_grasp_count": 0,
            "colliding_grasp_count": 512,
            "zero_noncolliding": True,
        },
        "grasp_failure_count": 1,
        "grasp_failures": [
            {
                "object_name": "pickup/body",
                "count_before": 2,
                "count_after": 3,
                "max_failures": 2,
                "threshold_exceeded": True,
                "threshold_crossed": True,
                "candidate_count_before": 1,
                "candidate_count_after": 1,
                "candidate_name_present_before": False,
                "candidate_name_present_after": False,
                "candidate_removal_call_count_delta": 1,
                "removed_candidate": False,
            }
        ],
        "place_robot_near_calls": [
            {
                "call_index": 1,
                "requested": {"max_tries": 10},
                "effective": {
                    "max_tries": 50,
                    "robot_safety_radius": 0.15,
                    "check_camera_visibility": False,
                },
                "result": False,
            }
        ],
        "placement_scene_diagnostic_count": 1,
        "placement_scene_diagnostics": [
            {
                "schema": "planner_probe_placement_scene_diagnostic_v1",
                "call_index": 1,
                "target_name": "pickup/body",
                "target_position": [1.0, 2.0, 0.5],
                "sampling_radius_range": [0.0, 1.2],
                "sampling_area_m2": 4.523893,
                "robot_safety_radius": 0.15,
                "px_per_m": 200,
                "total_free_point_count": 100,
                "valid_free_point_count": 3,
                "valid_neighborhood_fraction": 0.000017,
                "low_free_space": True,
                "nearest_free_point_distance_m": 0.42,
                "nearest_free_point": [1.42, 2.0, 0.0],
                "radius_band_counts": [
                    {"radius_min_m": 0.0, "radius_max_m": 0.25, "free_point_count": 0},
                    {"radius_min_m": 0.25, "radius_max_m": 0.5, "free_point_count": 1},
                ],
            }
        ],
        "last_placement_scene_diagnostic": {
            "schema": "planner_probe_placement_scene_diagnostic_v1",
            "call_index": 1,
            "target_name": "pickup/body",
            "target_position": [1.0, 2.0, 0.5],
            "sampling_radius_range": [0.0, 1.2],
            "sampling_area_m2": 4.523893,
            "robot_safety_radius": 0.15,
            "px_per_m": 200,
            "total_free_point_count": 100,
            "valid_free_point_count": 3,
            "valid_neighborhood_fraction": 0.000017,
            "low_free_space": True,
            "nearest_free_point_distance_m": 0.42,
            "nearest_free_point": [1.42, 2.0, 0.0],
            "radius_band_counts": [
                {"radius_min_m": 0.0, "radius_max_m": 0.25, "free_point_count": 0},
                {"radius_min_m": 0.25, "radius_max_m": 0.5, "free_point_count": 1},
            ],
        },
        "candidate_removals": [
            {
                "object_name": "pickup/body",
                "candidate_count_before": 1,
                "candidate_count_after": 1,
                "candidate_name_present_before": False,
                "candidate_name_present_after": False,
                "effective_removal": False,
            }
        ],
        "last_robot_placement_failure": {
            "pickup_obj_name": "pickup/body",
            "message": "Failed to place robot near object: pickup/body",
        },
    }
    run_result["manipulation_evidence"]["sampled_task_binding"] = {
        "schema": "planner_probe_sampled_task_binding_v1",
        "pickup_obj_name": "pickup/body",
        "place_receptacle_name": "sink/body",
        "place_target_name": "sink/body",
    }
    run_result["manipulation_evidence"]["requested_cleanup_primitive_binding"] = {
        "schema": "planner_probe_cleanup_primitive_binding_v1",
        "requested": True,
        "object_id": "pickup/body",
        "target_receptacle_id": "sink/body",
        "source_receptacle_id": "counter/body",
        "planner_object_id": "pickup/body",
        "planner_target_receptacle_id": "sink/body",
        "tools": ["navigate_to_object", "pick", "navigate_to_receptacle", "place"],
    }
    run_result["manipulation_evidence"]["cleanup_primitive_binding"] = {
        "schema": "planner_probe_cleanup_primitive_binding_v1",
        "object_id": "pickup/body",
        "target_receptacle_id": "sink/body",
        "source_receptacle_id": "counter/body",
        "planner_object_id": "pickup/body",
        "planner_target_receptacle_id": "sink/body",
        "tools": ["navigate_to_object", "pick", "navigate_to_receptacle", "place"],
    }
    run_result["manipulation_evidence"]["policy_exception_context"] = {
        "schema": "planner_probe_policy_exception_context_v1",
        "stage": "execute_policy_run",
        "steps_requested": 1,
        "exception_type": "ValueError",
        "message": "_execute_trajectory was called with no planned trajectory",
        "failure_kind": "curobo_no_planned_trajectory",
        "no_planned_trajectory": True,
        "policy_class": "PickAndPlacePlannerPolicy",
        "policy_current_phase": "pre_grasp",
        "action_primitive_count": 1,
        "action_primitives": [
            {
                "index": 0,
                "primitive_class": "PickAndPlacePrimitive",
                "current_phase": "pre_grasp",
                "planned_trajectory_present": True,
                "planned_trajectory_len": 0,
                "trajectory_index": 0,
            }
        ],
    }
    run_result["manipulation_evidence"]["last_worker_stage"] = "rby1m_config_import"
    run_result["rby1m_curobo_gate"] = rby1m_curobo_gate_from_planner_probe(run_result)

    report_path = render_planner_manipulation_report(run_dir=tmp_path, run_result=run_result)
    html = report_path.read_text(encoding="utf-8")

    _assert_planner_manipulation_probe_overview(html)
    _assert_planner_manipulation_probe_cleanup_binding(html)
    _assert_planner_manipulation_probe_sampler_failures(html)
    _assert_planner_manipulation_probe_runtime_diagnostics(html)


def test_planner_manipulation_probe_report_renders_proof_quality(tmp_path: Path) -> None:
    views = tmp_path / "planner_views"
    views.mkdir()
    (views / "initial.png").write_bytes(b"initial")
    (views / "final.png").write_bytes(b"final")
    run_result = {
        "contract": "planner_backed_manipulation_probe_v1",
        "backend": "molmospaces_subprocess",
        "status": "planner_backed",
        "primitive_provenance": "planner_backed",
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
        "artifacts": {},
    }

    report_path = render_planner_manipulation_report(run_dir=tmp_path, run_result=run_result)
    html = report_path.read_text(encoding="utf-8")

    assert "Planner Proof Quality" in html
    assert "multi_step_motion" in html
    assert "Containment proven" in html
    assert "Planner Probe Views" in html


def test_planner_manipulation_probe_report_renders_diagnostic_image_artifacts(
    tmp_path: Path,
) -> None:
    views = tmp_path / "planner_views"
    views.mkdir()
    image = views / "post_placement_attempt_001_head_camera.png"
    image.write_bytes(b"not a real image but enough for an html src")
    run_result = {
        "contract": "planner_backed_manipulation_probe_v1",
        "backend": "molmospaces_subprocess",
        "status": "blocked_capability",
        "primitive_provenance": "blocked_capability",
        "manipulation_evidence": blocked_planner_probe_evidence(
            backend="molmospaces_subprocess",
            embodiment="rby1m",
            task="pick_and_place",
            probe_mode="execute",
            blockers=[{"code": "HouseInvalidForTask", "message": "candidate removed"}],
            execution_attempted=True,
        ),
        "artifacts": {"stdout": "stdout.txt", "stderr": "stderr.txt"},
    }
    run_result["manipulation_evidence"]["image_artifacts"] = {
        "post_placement_attempt_001_head_camera": (
            "planner_views/post_placement_attempt_001_head_camera.png"
        )
    }
    run_result["rby1m_curobo_gate"] = rby1m_curobo_gate_from_planner_probe(run_result)

    report_path = render_planner_manipulation_report(run_dir=tmp_path, run_result=run_result)

    html = report_path.read_text(encoding="utf-8")
    assert "Planner Probe Views" in html
    assert "Post Placement Attempt 001 Head Camera" in html
    assert 'src="planner_views/post_placement_attempt_001_head_camera.png"' in html
    assert "diagnostic-view" in html
