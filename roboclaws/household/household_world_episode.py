#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import time
from pathlib import Path
from typing import Any

from roboclaws.core.goals import goal_contract_from_file, goal_contract_from_json
from roboclaws.core.map_build_scan_profile import (
    map_build_scan_profile,
)
from roboclaws.core.task_intents import (
    HOUSEHOLD_INTENT_CLEANUP,
    household_runtime_intent,
)
from roboclaws.household.household_backend_contract import (
    SYNTHETIC_BACKEND,
    build_household_backend_session,
    validate_cleanup_run_options,
)
from roboclaws.household.household_episode_execution import (
    _attach_raw_fpv_robot_view,
    _call_tool,
    _detections_for_policy,
    _map_build_done,
    _maybe_clean_visible_object,
    _planner_proof_paths,
    _view_index_after_raw_fpv,
    _write_snapshot,
)
from roboclaws.household.household_episode_prior_policy import (
    _failed_score,
    _load_runtime_map_prior,
    _open_ended_prior_stop,
    _open_ended_prior_waypoint_ids,
    _prior_waypoint_filter,
)
from roboclaws.household.household_runtime_contract import (
    CAMERA_MODEL_POLICY_MODE,
    DEFAULT_REALWORLD_TASK,
    RAW_FPV_ONLY_MODE,
    VISIBLE_OBJECT_DETECTIONS_MODE,
    HouseholdRuntimeContract,
)
from roboclaws.household.household_world_direct_policy import (
    DirectHouseholdEpisodePolicyHooks,
    complete_direct_household_episode,
    direct_household_episode_policy,
    direct_household_episode_scratchpad,
    record_direct_household_episode_robot_view,
    run_direct_household_episode_scan,
)
from roboclaws.household.isaac_lab_backend import (
    ISAACLAB_SUBPROCESS_BACKEND,
)
from roboclaws.household.nav2_map_bundle import (
    selected_nav2_map_bundle_dir,
)
from roboclaws.household.planner_proof_attachment import attach_planner_proof
from roboclaws.household.planner_proof_bundle import (
    attach_planner_proof_bundle,
)
from roboclaws.household.profiles import (
    evidence_lane_names,
)
from roboclaws.household.realworld_run_artifacts import (
    RealWorldRunArtifactInputs,
    finalize_realworld_cleanup_run,
)
from roboclaws.household.subprocess_backend import (
    MOLMOSPACES_SUBPROCESS_BACKEND,
)
from roboclaws.household.visual_grounding import (
    SIM_VISUAL_GROUNDING_PIPELINE_ID,
    visual_grounding_client_from_env,
)


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run the household-world direct product episode.")
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--seed", type=int, default=1)
    parser.add_argument("--task", default=DEFAULT_REALWORLD_TASK)
    parser.add_argument("--goal-contract", type=Path)
    parser.add_argument("--goal-contract-json")
    parser.add_argument(
        "--backend",
        choices=(SYNTHETIC_BACKEND, MOLMOSPACES_SUBPROCESS_BACKEND, ISAACLAB_SUBPROCESS_BACKEND),
        default=SYNTHETIC_BACKEND,
    )
    parser.add_argument(
        "--static-fixture-projection-mode",
        choices=("room_only", "exact_fixtures"),
        default="room_only",
    )
    parser.add_argument(
        "--perception-mode",
        choices=(VISIBLE_OBJECT_DETECTIONS_MODE, RAW_FPV_ONLY_MODE, CAMERA_MODEL_POLICY_MODE),
        default=VISIBLE_OBJECT_DETECTIONS_MODE,
    )
    parser.add_argument(
        "--visual-grounding",
        default=SIM_VISUAL_GROUNDING_PIPELINE_ID,
        help=(
            "Internal External Visual Grounding Service pipeline id. Public task "
            "commands should use camera_labeler instead."
        ),
    )
    parser.add_argument(
        "--visual-grounding-base-url",
        help="External Visual Grounding Service base URL for non-sim pipelines.",
    )
    parser.add_argument(
        "--visual-grounding-timeout-s",
        type=float,
        help="External Visual Grounding Service timeout in seconds.",
    )
    parser.add_argument(
        "--evidence-lane",
        choices=evidence_lane_names(),
        help="Public cleanup evidence lane or smoke preset selected by the command facade.",
    )
    parser.add_argument(
        "--intent",
        choices=("cleanup", "map-build", "open-ended"),
        help="Household task intent used to select the direct episode policy.",
    )
    parser.add_argument(
        "--runtime-map-prior",
        type=Path,
        help="Prior runtime_metric_map.json snapshot to seed this run as non-actionable priors.",
    )
    parser.add_argument("--include-robot", action="store_true")
    parser.add_argument("--robot-name", default="rby1m")
    parser.add_argument("--record-robot-views", action="store_true")
    parser.add_argument("--generated-mess-count", type=int, default=10)
    parser.add_argument(
        "--generated-mess-object-id",
        action="append",
        help="Private run-control object id to include in the generated mess set. Repeatable.",
    )
    parser.add_argument("--scene-source", default="procthor-10k-val")
    parser.add_argument("--scene-index", type=int, default=0)
    parser.add_argument(
        "--isaac-scene-usd-path",
        type=Path,
        help=(
            "Optional local USD/USDA scene for backend=isaaclab_subprocess real-mode "
            "scene parity checks."
        ),
    )
    parser.add_argument(
        "--isaac-enable-segmentation",
        action="store_true",
        help=(
            "Request Isaac semantic/instance segmentation tensors for "
            "backend=isaaclab_subprocess local probes."
        ),
    )
    parser.add_argument(
        "--isaac-segmentation-data-type",
        action="append",
        choices=(
            "semantic_segmentation",
            "instance_segmentation_fast",
            "instance_id_segmentation_fast",
        ),
        help=(
            "Isaac segmentation data type to request for backend=isaaclab_subprocess. "
            "Repeat to probe individual annotators."
        ),
    )
    parser.add_argument(
        "--isaac-segmentation-semantic-filter",
        action="append",
        help=(
            "Isaac camera semantic filter instance name for "
            "backend=isaaclab_subprocess. Repeat to probe prepared USD labels "
            "such as usd_prim_path."
        ),
    )
    parser.add_argument(
        "--map-bundle-dir",
        type=Path,
        help=(
            "Prebuilt Nav2 map bundle path, or environment id under assets/maps, "
            "to project metric_map/static_fixture_projection and snapshot into the run."
        ),
    )
    parser.add_argument(
        "--planner-proof-run-result",
        type=Path,
        action="append",
        help=(
            "Attach a strict planner proof run_result.json. Repeat to provide "
            "one bound proof per cleanup object."
        ),
    )
    parser.add_argument(
        "--use-planner-proof-for-cleanup-primitives",
        action="store_true",
        help=(
            "Opt in to using attached bound planner proof as cleanup primitive executor "
            "evidence when it matches the current observed handle and target."
        ),
    )
    return parser.parse_args(argv)


def run_household_world_episode(
    *,
    output_dir: Path,
    seed: int = 1,
    task_prompt: str = DEFAULT_REALWORLD_TASK,
    backend: str = SYNTHETIC_BACKEND,
    static_fixture_projection_mode: str = "room_only",
    perception_mode: str = VISIBLE_OBJECT_DETECTIONS_MODE,
    include_robot: bool = False,
    robot_name: str = "rby1m",
    molmospaces_python: str | Path | None = None,
    record_robot_views: bool = False,
    generated_mess_count: int = 10,
    generated_mess_object_ids: tuple[str, ...] = (),
    scene_source: str = "procthor-10k-val",
    scene_index: int = 0,
    isaac_scene_usd_path: str | Path | None = None,
    isaac_enable_segmentation: bool = False,
    isaac_segmentation_data_types: tuple[str, ...] | None = None,
    isaac_segmentation_semantic_filter: tuple[str, ...] | None = None,
    map_bundle_dir: str | Path | None = None,
    evidence_lane: str | None = None,
    intent: str | None = None,
    runtime_map_prior_path: str | Path | None = None,
    planner_proof_run_result: Path | None = None,
    planner_proof_run_results: list[Path] | None = None,
    use_planner_proof_for_cleanup_primitives: bool = False,
    visual_grounding: str = SIM_VISUAL_GROUNDING_PIPELINE_ID,
    visual_grounding_base_url: str | None = None,
    visual_grounding_timeout_s: float | None = None,
    goal_contract_json: str | None = None,
    goal_contract_path: str | Path | None = None,
    run_metadata_overrides: dict[str, Any] | None = None,
) -> dict[str, Any]:
    output_dir.mkdir(parents=True, exist_ok=True)
    validate_cleanup_run_options(
        backend_name=backend,
        include_robot=include_robot,
        record_robot_views=record_robot_views,
        generated_mess_count=generated_mess_count,
    )
    selected_bundle_dir = selected_nav2_map_bundle_dir(
        map_bundle_dir,
        required=True,
    )
    planner_proof_paths = _planner_proof_paths(
        planner_proof_run_result=planner_proof_run_result,
        planner_proof_run_results=planner_proof_run_results,
    )
    if use_planner_proof_for_cleanup_primitives and not planner_proof_paths:
        raise ValueError(
            "use_planner_proof_for_cleanup_primitives requires planner_proof_run_result"
        )
    runtime_map_prior = _load_runtime_map_prior(runtime_map_prior_path)
    selected_map_build_scan_profile = map_build_scan_profile()
    goal_contract = goal_contract_from_json(goal_contract_json) or goal_contract_from_file(
        goal_contract_path
    )
    task_intent = household_runtime_intent(goal_contract, intent or HOUSEHOLD_INTENT_CLEANUP)

    base_contract = build_household_backend_session(
        backend_name=backend,
        run_dir=output_dir,
        seed=seed,
        molmospaces_python=molmospaces_python,
        include_robot=include_robot,
        robot_name=robot_name,
        generated_mess_count=generated_mess_count,
        generated_mess_object_ids=generated_mess_object_ids,
        scene_source=scene_source,
        scene_index=scene_index,
        map_bundle_dir=selected_bundle_dir,
        isaac_scene_usd_path=isaac_scene_usd_path,
        isaac_enable_segmentation=isaac_enable_segmentation,
        isaac_segmentation_data_types=isaac_segmentation_data_types,
        isaac_segmentation_semantic_filter=isaac_segmentation_semantic_filter,
    )
    scenario = base_contract.scenario
    contract = HouseholdRuntimeContract(
        base_contract,
        task_prompt=task_prompt,
        static_fixture_projection_mode=static_fixture_projection_mode,
        perception_mode=perception_mode,
        map_bundle_dir=selected_bundle_dir,
        visual_grounding_client=visual_grounding_client_from_env(
            visual_grounding,
            base_url=visual_grounding_base_url,
            timeout_s=visual_grounding_timeout_s,
        ),
        visual_grounding_pipeline_id=visual_grounding,
        visual_grounding_artifact_base_dir=output_dir,
        visual_grounding_run_id=f"seed-{seed}",
        runtime_map_prior=runtime_map_prior,
        evidence_lane=evidence_lane,
        public_acceptance_config=(goal_contract and {"task_intent": goal_contract.intent}),
    )
    planner_proof_evidence: dict[str, Any] | None = None
    if len(planner_proof_paths) == 1:
        planner_proof_evidence = attach_planner_proof(
            proof_run_result_path=planner_proof_paths[0],
            cleanup_run_dir=output_dir,
        )
    elif len(planner_proof_paths) > 1:
        planner_proof_evidence = attach_planner_proof_bundle(
            proof_run_result_paths=planner_proof_paths,
            cleanup_run_dir=output_dir,
        )
    trace_events: list[dict[str, Any]] = []
    started_at = time.time()

    before_snapshot = _write_snapshot(
        contract=base_contract,
        scenario=scenario,
        output_path=output_dir / "before.png",
        title="Before household-world episode",
    )
    robot_view_steps: list[dict[str, Any]] = []
    view_index = 0
    direct_loop_hooks = DirectHouseholdEpisodePolicyHooks(
        call_tool=_call_tool,
        attach_raw_fpv_robot_view=_attach_raw_fpv_robot_view,
        view_index_after_raw_fpv=_view_index_after_raw_fpv,
        detections_for_policy=_detections_for_policy,
        maybe_clean_visible_object=_maybe_clean_visible_object,
        map_build_done=_map_build_done,
        failed_score=_failed_score,
    )
    view_index = record_direct_household_episode_robot_view(
        base_contract=base_contract,
        robot_view_steps=robot_view_steps,
        output_dir=output_dir,
        view_index=view_index,
        record_robot_views=record_robot_views,
        label_suffix="before",
        action="before",
    )

    metric_map = _call_tool(trace_events, started_at, "metric_map", {}, contract.metric_map)
    static_fixture_projection = _call_tool(
        trace_events,
        started_at,
        "static_fixture_projection",
        {},
        contract.static_fixture_projection,
    )
    open_ended_prior_waypoints = _open_ended_prior_waypoint_ids(
        runtime_map_prior=runtime_map_prior,
        task_prompt=task_prompt,
        goal_contract=goal_contract,
        run_metadata_overrides=run_metadata_overrides,
    )

    episode_policy = direct_household_episode_policy(
        intent=task_intent,
        perception_mode=perception_mode,
    )
    agent_scratchpad = direct_household_episode_scratchpad(episode_policy.policy_name)
    view_index = run_direct_household_episode_scan(
        trace_events=trace_events,
        started_at=started_at,
        contract=contract,
        base_contract=base_contract,
        metric_map=metric_map,
        static_fixture_projection=static_fixture_projection,
        robot_view_steps=robot_view_steps,
        output_dir=output_dir,
        view_index=view_index,
        record_robot_views=record_robot_views,
        episode_policy=episode_policy,
        perception_mode=perception_mode,
        planner_proof_evidence=(
            planner_proof_evidence if use_planner_proof_for_cleanup_primitives else None
        ),
        agent_scratchpad=agent_scratchpad,
        hooks=direct_loop_hooks,
        map_build_scan_profile=selected_map_build_scan_profile,
        waypoint_filter=_prior_waypoint_filter(open_ended_prior_waypoints),
        stop_after_waypoint=_open_ended_prior_stop(open_ended_prior_waypoints),
    )

    done = complete_direct_household_episode(
        trace_events=trace_events,
        started_at=started_at,
        contract=contract,
        base_contract=base_contract,
        episode_policy=episode_policy,
        hooks=direct_loop_hooks,
    )

    after_snapshot = _write_snapshot(
        contract=base_contract,
        scenario=scenario,
        output_path=output_dir / "after.png",
        title="After household-world episode",
    )
    view_index = record_direct_household_episode_robot_view(
        base_contract=base_contract,
        robot_view_steps=robot_view_steps,
        output_dir=output_dir,
        view_index=view_index,
        record_robot_views=record_robot_views,
        label_suffix="after",
        action="after",
    )
    run_result = finalize_realworld_cleanup_run(
        RealWorldRunArtifactInputs(
            output_dir=output_dir,
            backend=backend,
            base_contract=base_contract,
            contract=contract,
            scenario=scenario,
            seed=seed,
            task_prompt=task_prompt,
            policy_name=episode_policy.policy_name,
            done=done,
            trace_events=trace_events,
            before_snapshot=before_snapshot,
            after_snapshot=after_snapshot,
            robot_view_steps=robot_view_steps,
            generated_mess_count=generated_mess_count,
            goal_contract=goal_contract,
            agent_scratchpad=agent_scratchpad,
            map_build=episode_policy.requires_map_artifacts,
            runtime_map_prior=runtime_map_prior,
            runtime_map_prior_path=runtime_map_prior_path,
            evidence_lane=evidence_lane,
            perception_mode=perception_mode,
            record_robot_views=record_robot_views,
            selected_bundle_dir=selected_bundle_dir,
            planner_proof_evidence=planner_proof_evidence,
            use_planner_proof_for_cleanup_primitives=(use_planner_proof_for_cleanup_primitives),
            map_build_scan_profile=selected_map_build_scan_profile,
            run_metadata_overrides=run_metadata_overrides,
        )
    )
    base_contract.close()
    return run_result


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    result = run_household_world_episode(
        output_dir=args.output_dir,
        seed=args.seed,
        task_prompt=args.task,
        backend=args.backend,
        static_fixture_projection_mode=args.static_fixture_projection_mode,
        perception_mode=args.perception_mode,
        include_robot=args.include_robot,
        robot_name=args.robot_name,
        molmospaces_python=None,
        record_robot_views=args.record_robot_views,
        generated_mess_count=args.generated_mess_count,
        generated_mess_object_ids=tuple(args.generated_mess_object_id or ()),
        scene_source=args.scene_source,
        scene_index=args.scene_index,
        isaac_scene_usd_path=args.isaac_scene_usd_path,
        isaac_enable_segmentation=args.isaac_enable_segmentation,
        isaac_segmentation_data_types=tuple(args.isaac_segmentation_data_type or ()),
        isaac_segmentation_semantic_filter=tuple(args.isaac_segmentation_semantic_filter or ()),
        map_bundle_dir=args.map_bundle_dir,
        evidence_lane=args.evidence_lane,
        intent=args.intent,
        runtime_map_prior_path=args.runtime_map_prior,
        planner_proof_run_results=args.planner_proof_run_result,
        use_planner_proof_for_cleanup_primitives=args.use_planner_proof_for_cleanup_primitives,
        visual_grounding=args.visual_grounding,
        visual_grounding_base_url=args.visual_grounding_base_url,
        visual_grounding_timeout_s=args.visual_grounding_timeout_s,
        goal_contract_json=args.goal_contract_json,
        goal_contract_path=args.goal_contract,
    )
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
