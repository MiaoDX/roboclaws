from __future__ import annotations

import argparse
from pathlib import Path
from typing import Any

from roboclaws.household.cleanup_validation import load_run_results, validate_run_result
from roboclaws.household.cleanup_validation_args import parse_args
from roboclaws.household.household_runtime_contract import CAMERA_MODEL_POLICY_NAME


def validate_path(args: argparse.Namespace) -> list[tuple[dict[str, Any], Path]]:
    run_results = load_run_results(args.path)
    if args.expect_seeds:
        expected = {int(item) for item in args.expect_seeds.split(",") if item}
        actual = {int(data["seed"]) for data, _path in run_results}
        assert expected <= actual, (expected, actual)
    assert len(run_results) >= 1, args.path
    expect_policy = args.expect_policy
    if expect_policy is None:
        expect_policy = (
            "map_build_baseline"
            if args.require_map_build
            else CAMERA_MODEL_POLICY_NAME
            if args.require_camera_model_policy
            else "deterministic_sweep_baseline"
        )
    for data, path in run_results:
        validate_run_result(
            data,
            path.parent,
            expect_task=args.expect_task,
            expect_task_name=args.expect_task_name,
            expect_backend=args.expect_backend,
            expect_policy=expect_policy,
            expect_profile=args.expect_profile,
            expect_mcp_server=args.expect_mcp_server,
            min_generated_mess_count=args.min_generated_mess_count,
            require_agent_driven=args.require_agent_driven,
            require_clean_agent_run=args.require_clean_agent_run,
            allow_partial_cleanup=args.allow_partial_cleanup,
            require_robot_views=args.require_robot_views,
            require_raw_fpv_observations=args.require_raw_fpv_observations,
            require_camera_model_policy=args.require_camera_model_policy,
            require_runtime_metric_map=args.require_runtime_metric_map,
            require_goal_contract=args.require_goal_contract,
            require_completion_claim=args.require_completion_claim,
            require_map_build=args.require_map_build,
            require_agibot_g2_hardware=args.require_agibot_g2_hardware,
            require_base_metric_map=args.require_base_metric_map,
            expect_visual_grounding_pipeline=args.expect_visual_grounding_pipeline,
            require_visual_grounding_failure=args.require_visual_grounding_failure,
            require_model_declared_observations=args.require_model_declared_observations,
            min_model_declared_observations=args.min_model_declared_observations,
            min_model_declared_actions=args.min_model_declared_actions,
            min_restored_count=args.min_restored_count,
            min_semantic_accepted_count=args.min_semantic_accepted_count,
            min_sweep_coverage=args.min_sweep_coverage,
            min_adjust_camera_count=args.min_adjust_camera_count,
            expect_map_build_scan_profile=args.expect_map_build_scan_profile,
            min_map_build_body_turn_count=args.min_map_build_body_turn_count,
            min_generated_target_inspection_candidates=(
                args.min_generated_target_inspection_candidates
            ),
            require_planner_proof_attachment=args.require_planner_proof_attachment,
            require_planner_proof_quality=args.require_planner_proof_quality,
            require_planner_proof_min_steps=args.require_planner_proof_min_steps,
            accept_blocked_planner_cleanup_primitives=(
                args.accept_blocked_planner_cleanup_primitives
            ),
            require_planner_backed_cleanup_primitives=(
                args.require_planner_backed_cleanup_primitives
            ),
            require_bound_planner_cleanup_objects=args.require_bound_planner_cleanup_object,
            require_mixed_planner_cleanup_primitives=(
                args.require_mixed_planner_cleanup_primitives
            ),
            accept_blocked_planner_cleanup_bridge=(args.accept_blocked_planner_cleanup_bridge),
            require_planner_cleanup_bridge_ready=(args.require_planner_cleanup_bridge_ready),
            require_waypoint_honesty=args.require_waypoint_honesty,
            require_real_robot_alignment=args.require_real_robot_alignment,
            require_b1_robot_consumption_proof=args.require_b1_robot_consumption_proof,
            require_isaac_runtime=args.require_isaac_runtime,
            require_isaac_real_runtime=args.require_isaac_real_runtime,
            require_isaac_scene_loaded=args.require_isaac_scene_loaded,
            require_isaac_local_scene_usd=args.require_isaac_local_scene_usd,
            require_isaac_selected_usd_bindings=args.require_isaac_selected_usd_bindings,
            require_isaac_semantic_pose=args.require_isaac_semantic_pose,
            require_isaac_robot_view_provenance=args.require_isaac_robot_view_provenance,
            require_isaac_segmentation_evidence=args.require_isaac_segmentation_evidence,
            require_isaac_snapshot_provenance=args.require_isaac_snapshot_provenance,
            require_isaac_scene_index_map_context=(args.require_isaac_scene_index_map_context),
            require_robot_head_camera_fpv=args.require_robot_head_camera_fpv,
        )
    return run_results


def main() -> None:
    args = parse_args()
    run_results = validate_path(args)
    print(f"household-world ok: {args.path} ({len(run_results)} run(s))")


if __name__ == "__main__":
    main()
