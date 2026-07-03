#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import re
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

from roboclaws.household import realworld_visual_candidate_declarations
from roboclaws.household.backend_contract import (
    SYNTHETIC_BACKEND,
    CleanupBackendSession,
    build_cleanup_backend_session,
    validate_cleanup_run_options,
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
from roboclaws.household.map_build_scan_profile import (
    map_build_scan_profile,
)
from roboclaws.household.nav2_map_bundle import (
    selected_nav2_map_bundle_dir,
)
from roboclaws.household.planner_primitive_executor import (
    PlannerBackedCleanupContractAdapter,
)
from roboclaws.household.planner_probe_primitive_executor import (
    ProbeBackedCleanupPrimitiveExecutor,
)
from roboclaws.household.planner_proof_attachment import attach_planner_proof
from roboclaws.household.planner_proof_bundle import (
    attach_planner_proof_bundle,
    planner_proof_attachment_for_target,
)
from roboclaws.household.profiles import (
    evidence_lane_names,
)
from roboclaws.household.realworld_contract import (
    CAMERA_MODEL_POLICY_MODE,
    CAMERA_MODEL_POLICY_NAME,
    DEFAULT_REALWORLD_TASK,
    MAIN_CLEANUP_AGENT_PRODUCER,
    RAW_FPV_ONLY_MODE,
    REALWORLD_CONTRACT,
    SIMULATED_CAMERA_MODEL_PROVENANCE,
    VISIBLE_OBJECT_DETECTIONS_MODE,
    RealWorldCleanupContract,
)
from roboclaws.household.realworld_run_artifacts import (
    RealWorldRunArtifactInputs,
    finalize_realworld_cleanup_run,
)
from roboclaws.household.report import (
    write_state_snapshot,
)
from roboclaws.household.semantic_cleanup_loop import (
    run_semantic_cleanup_loop,
)
from roboclaws.household.semantic_timeline import (
    camera_offsets_from_raw_fpv_observation,
    robot_view_capture_for_tool,
)
from roboclaws.household.subprocess_backend import (
    MOLMOSPACES_SUBPROCESS_BACKEND,
)
from roboclaws.household.task_intent import (
    HOUSEHOLD_INTENT_CLEANUP,
    HOUSEHOLD_INTENT_OPEN_ENDED,
    household_runtime_intent,
)
from roboclaws.household.visual_grounding import (
    SIM_VISUAL_GROUNDING_PIPELINE_ID,
    visual_grounding_client_from_env,
)
from roboclaws.launch.goals import goal_contract_from_file, goal_contract_from_json
from roboclaws.maps.runtime_prior_snapshot import read_runtime_map_prior_artifact


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

    base_contract = build_cleanup_backend_session(
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
    contract = RealWorldCleanupContract(
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


def _load_runtime_map_prior(path: str | Path | None) -> dict[str, Any] | None:
    return read_runtime_map_prior_artifact(path)


def _open_ended_prior_waypoint_ids(
    *,
    runtime_map_prior: dict[str, Any] | None,
    task_prompt: str,
    goal_contract: Any | None,
    run_metadata_overrides: dict[str, Any] | None,
) -> tuple[str, ...]:
    if not runtime_map_prior:
        return ()
    sample_id = str((run_metadata_overrides or {}).get("eval_sample_id") or "")
    if not sample_id.startswith("open_ended."):
        return ()
    if str(getattr(goal_contract, "intent", "") or "") != HOUSEHOLD_INTENT_OPEN_ENDED:
        return ()
    prompt_tokens = _search_tokens(
        [
            task_prompt,
            str(getattr(goal_contract, "normalized_goal", "") or ""),
            str(getattr(goal_contract, "raw_prompt", "") or ""),
        ]
    )
    if not prompt_tokens:
        return ()
    matches: list[str] = []
    for anchor in runtime_map_prior.get("public_semantic_anchors") or []:
        if not isinstance(anchor, dict):
            continue
        waypoint_id = str(anchor.get("waypoint_id") or "")
        if not waypoint_id:
            continue
        anchor_tokens = _search_tokens(
            [
                str(anchor.get("label") or ""),
                str(anchor.get("category") or ""),
                str(anchor.get("anchor_type") or ""),
                *[str(item) for item in anchor.get("aliases") or []],
            ]
        )
        if prompt_tokens.intersection(anchor_tokens) and waypoint_id not in matches:
            matches.append(waypoint_id)
    return tuple(matches)


def _search_tokens(values: list[str]) -> set[str]:
    ignored = {
        "and",
        "area",
        "find",
        "it",
        "is",
        "report",
        "room",
        "the",
        "there",
        "to",
        "where",
    }
    tokens: set[str] = set()
    for value in values:
        for token in re.findall(r"[a-zA-Z0-9]+", value.lower()):
            if len(token) > 2 and token not in ignored:
                tokens.add(token)
    return tokens


def _prior_waypoint_filter(
    waypoint_ids: tuple[str, ...],
) -> Callable[[list[dict[str, Any]]], list[dict[str, Any]]] | None:
    if not waypoint_ids:
        return None
    priority = {waypoint_id: index for index, waypoint_id in enumerate(waypoint_ids)}

    def filter_waypoints(waypoints: list[dict[str, Any]]) -> list[dict[str, Any]]:
        return sorted(
            waypoints,
            key=lambda waypoint: priority.get(
                str(waypoint.get("waypoint_id") or ""),
                len(priority),
            ),
        )

    return filter_waypoints


def _open_ended_prior_stop(
    waypoint_ids: tuple[str, ...],
) -> Callable[[RealWorldCleanupContract], bool] | None:
    if not waypoint_ids:
        return None
    priority = set(waypoint_ids)

    def stop_after_current_confirmation(contract: RealWorldCleanupContract) -> bool:
        return bool(priority.intersection(contract._observed_waypoint_ids))  # noqa: SLF001

    return stop_after_current_confirmation


def _failed_score(contract: RealWorldCleanupContract) -> dict[str, Any]:
    total_targets = len(contract.scenario.private_manifest.targets)
    return {
        "status": "failed",
        "restored_count": 0,
        "total_targets": total_targets,
        "success_threshold": contract.scenario.private_manifest.success_threshold,
        "restored_object_ids": [],
        "missed_object_ids": [
            target.object_id for target in contract.scenario.private_manifest.targets
        ],
        "object_results": [],
        "mess_restoration_rate": 0.0,
        "sweep_coverage_rate": 0.0,
        "disturbance_count": 0,
        "completion_status": "failed",
        "semantic_acceptability": {
            "accepted_count": 0,
            "total_targets": total_targets,
            "rate": 0.0,
            "status": "failed",
        },
    }


def _map_build_done(
    contract: RealWorldCleanupContract,
    base_contract: CleanupBackendSession,
    reason: str,
) -> dict[str, Any]:
    done = base_contract.done(reason=reason)
    score = dict(done["score"])
    final_locations = dict(done["final_locations"])
    metrics = contract._realworld_metrics(score, final_locations)  # noqa: SLF001
    score.update(metrics)
    return {
        "ok": True,
        "tool": "done",
        "status": "ok",
        "reason": reason,
        "cleanup_status": "map_build_complete",
        "score": score,
        "final_locations": final_locations,
        "final_containment": done.get("final_containment", {}),
        "tool_event_counts": done.get("tool_event_counts", {}),
        "contract": REALWORLD_CONTRACT,
        "policy_uses_private_truth": False,
        "map_build_mode": True,
        "cleanup_actions_disabled": True,
    }


def _detections_for_policy(
    *,
    trace_events: list[dict[str, Any]],
    started_at: float,
    contract: RealWorldCleanupContract,
    observation: dict[str, Any],
    perception_mode: str,
) -> list[dict[str, Any]]:
    if perception_mode not in {CAMERA_MODEL_POLICY_MODE, RAW_FPV_ONLY_MODE}:
        return list(observation.get("visible_object_detections", []))
    raw = observation.get("raw_fpv_observation") or {}
    if perception_mode == RAW_FPV_ONLY_MODE:
        waypoint = contract._waypoint_by_id(str(raw.get("waypoint_id") or ""))
        candidate_inputs = (
            realworld_visual_candidate_declarations.simulated_declaration_inputs_for_waypoint(
                contract,
                waypoint,
                observation_id=str(raw.get("observation_id", "")),
            )
            if waypoint is not None
            else []
        )
        detections: list[dict[str, Any]] = []
        for candidate in candidate_inputs:
            response = _call_tool(
                trace_events,
                started_at,
                "navigate_to_visual_candidate",
                {
                    "source_observation_id": raw.get("observation_id", ""),
                    "category": candidate.get("category", ""),
                    "producer_type": MAIN_CLEANUP_AGENT_PRODUCER,
                    "producer_id": "deterministic_raw_fpv_agent",
                },
                lambda item=candidate: contract.navigate_to_visual_candidate(
                    str(raw.get("observation_id", "")),
                    category=str(item.get("category") or ""),
                    evidence_note=str(item.get("evidence_note") or ""),
                    image_region=item.get("image_region") or {},
                    source_fixture_id=str(item.get("source_fixture_id") or ""),
                    confidence=item.get("confidence"),
                    producer_type=MAIN_CLEANUP_AGENT_PRODUCER,
                    producer_id="deterministic_raw_fpv_agent",
                ),
            )
            if not response.get("ok"):
                continue
            detection = contract.inspect_visible_object(str(response.get("object_id") or ""))
            if detection.get("ok") and isinstance(detection.get("detection"), dict):
                detections.append(dict(detection["detection"]))
        return detections
    candidate_inputs = None
    producer_type = (
        SIMULATED_CAMERA_MODEL_PROVENANCE
        if perception_mode == CAMERA_MODEL_POLICY_MODE
        else MAIN_CLEANUP_AGENT_PRODUCER
    )
    producer_id = (
        CAMERA_MODEL_POLICY_NAME
        if perception_mode == CAMERA_MODEL_POLICY_MODE
        else "deterministic_raw_fpv_agent"
    )
    candidates = _call_tool(
        trace_events,
        started_at,
        "declare_visual_candidates",
        {
            "observation_id": raw.get("observation_id", ""),
            "producer_type": producer_type,
            "producer_id": producer_id,
            "candidate_count": len(candidate_inputs or []),
        },
        lambda: contract.declare_visual_candidates(
            str(raw.get("observation_id", "")),
            candidates=candidate_inputs,
            producer_type=producer_type,
            producer_id=producer_id,
        ),
    )
    return list(candidates.get("camera_model_candidates", []))


def _decision_reason(perception_mode: str) -> str:
    if perception_mode == CAMERA_MODEL_POLICY_MODE:
        return "camera model category/fixture affordance heuristic"
    if perception_mode == RAW_FPV_ONLY_MODE:
        return "model-declared raw FPV category/fixture affordance heuristic"
    return "public category/fixture affordance heuristic"


def _clean_visible_object(
    *,
    trace_events: list[dict[str, Any]],
    started_at: float,
    contract: RealWorldCleanupContract,
    base_contract: CleanupBackendSession,
    detection: dict[str, Any],
    target_fixture: dict[str, Any],
    robot_view_steps: list[dict[str, Any]],
    output_dir: Path,
    view_index: int,
    record_robot_views: bool,
    planner_proof_evidence: dict[str, Any] | None = None,
) -> int:
    handle = str(detection["object_id"])
    target_fixture_id = str(target_fixture["fixture_id"])

    def record_loop_robot_view(
        tool: str,
        request: dict[str, Any],
        response: dict[str, Any],
    ) -> None:
        nonlocal view_index
        if not record_robot_views or not response.get("ok"):
            return
        capture = robot_view_capture_for_tool(
            tool,
            request,
            response,
            object_id_transform=lambda value: (
                _internal_object_id(contract, value) if value is not None else None
            ),
        )
        if capture is None:
            return
        view_index = base_contract.record_robot_view_step(
            steps=robot_view_steps,
            output_dir=output_dir,
            index=view_index,
            action=str(capture["action"]),
            label_suffix=str(capture["label_suffix"]),
            focus_object_id=capture.get("focus_object_id"),
            focus_receptacle_id=contract.internal_fixture_id_for_public_reference(
                capture.get("focus_receptacle_id")
            ),
            semantic_phase=capture.get("semantic_phase"),
            action_evidence=capture.get("action_evidence"),
        )

    loop_contract = _cleanup_loop_contract_for_target(
        contract=contract,
        planner_proof_evidence=planner_proof_evidence,
        object_id=handle,
        target_receptacle_id=target_fixture_id,
    )

    run_semantic_cleanup_loop(
        targets=[
            {
                "object_id": handle,
                "target_receptacle_id": target_fixture_id,
                "target_receptacle": target_fixture,
            }
        ],
        contract=loop_contract,
        call_tool=lambda tool, request, fn: _call_tool(
            trace_events,
            started_at,
            tool,
            request,
            fn,
        ),
        record_tool_view=record_loop_robot_view,
        target_request_key="fixture_id",
        include_object_id_in_receptacle_request=False,
        include_object_id_in_target_requests=False,
    )
    post_place_observation = _call_tool(
        trace_events,
        started_at,
        "observe",
        {},
        contract.observe,
        postprocess=lambda response: _attach_raw_fpv_robot_view(
            response=response,
            contract=contract,
            base_contract=base_contract,
            robot_view_steps=robot_view_steps,
            output_dir=output_dir,
            view_index_ref=[view_index],
            record_robot_views=record_robot_views,
        ),
    )
    if post_place_observation.get("ok"):
        view_index = _view_index_after_raw_fpv(robot_view_steps, view_index)

    return view_index


@dataclass(frozen=True)
class _VisibleObjectCandidate:
    detection: dict[str, Any]
    target_fixture: dict[str, Any]
    support: dict[str, Any]
    target_fixture_id: str
    view_index: int


def _visible_object_candidate(
    *,
    detection: dict[str, Any],
    target_fixture: dict[str, Any],
    view_index: int,
) -> _VisibleObjectCandidate:
    return _VisibleObjectCandidate(
        detection=detection,
        target_fixture=target_fixture,
        support=detection.get("support_estimate") or {},
        target_fixture_id=str(target_fixture["fixture_id"]),
        view_index=view_index,
    )


def _maybe_clean_visible_object(
    *,
    trace_events: list[dict[str, Any]],
    started_at: float,
    contract: RealWorldCleanupContract,
    base_contract: CleanupBackendSession,
    detection: dict[str, Any],
    static_fixture_projection: dict[str, Any],
    robot_view_steps: list[dict[str, Any]],
    output_dir: Path,
    view_index: int,
    record_robot_views: bool,
    planner_proof_evidence: dict[str, Any] | None,
    agent_scratchpad: dict[str, Any],
    handled_handles: set[str],
    perception_mode: str,
) -> int:
    handle = str(detection["object_id"])
    if handle in handled_handles:
        return view_index
    agent_scratchpad["observed_handles"].setdefault(handle, {"object_id": handle})
    live_detection = contract.inspect_visible_object(handle)
    if live_detection.get("ok") and isinstance(live_detection.get("detection"), dict):
        detection = dict(live_detection["detection"])
    target_fixture = contract.target_fixture_for_detection(
        detection,
        static_fixture_projection,
        include_runtime_backend_fixtures=True,
    )
    if target_fixture is None:
        agent_scratchpad["failed_attempts"].append(
            {"object_id": handle, "reason": "no_public_fixture_match"}
        )
        return view_index
    candidate = _visible_object_candidate(
        detection=detection,
        target_fixture=target_fixture,
        view_index=view_index,
    )
    if str(candidate.detection.get("candidate_state") or "") == "visual_scan_required":
        candidate, view_index = _confirm_visual_scan_candidate(
            trace_events=trace_events,
            started_at=started_at,
            contract=contract,
            base_contract=base_contract,
            handle=handle,
            candidate=candidate,
            static_fixture_projection=static_fixture_projection,
            robot_view_steps=robot_view_steps,
            output_dir=output_dir,
            view_index=candidate.view_index,
            record_robot_views=record_robot_views,
            agent_scratchpad=agent_scratchpad,
        )
        if candidate is None:
            return view_index
    else:
        candidate = _redirect_if_already_on_inferred_fixture(
            contract=contract,
            handle=handle,
            candidate=candidate,
            agent_scratchpad=agent_scratchpad,
        )
        if candidate is None:
            return view_index
    next_view_index = _clean_visible_object(
        trace_events=trace_events,
        started_at=started_at,
        contract=contract,
        base_contract=base_contract,
        detection=candidate.detection,
        target_fixture=candidate.target_fixture,
        robot_view_steps=robot_view_steps,
        output_dir=output_dir,
        view_index=candidate.view_index,
        record_robot_views=record_robot_views,
        planner_proof_evidence=planner_proof_evidence,
    )
    handled_handles.add(handle)
    agent_scratchpad["observed_handles"][handle].update(
        {
            "object_id": handle,
            "category": candidate.detection.get("category"),
            "from_fixture_id": candidate.support.get("fixture_id"),
            "to_fixture_id": candidate.target_fixture_id,
            "reason": _decision_reason(perception_mode),
            "perception_source": candidate.detection.get("perception_source", "visible_detection"),
            "model_provenance": candidate.detection.get("model_provenance"),
            "source_observation_id": candidate.detection.get("source_observation_id"),
            "handled": True,
        }
    )
    return next_view_index


def _redirect_if_already_on_inferred_fixture(
    *,
    contract: RealWorldCleanupContract,
    handle: str,
    candidate: _VisibleObjectCandidate,
    agent_scratchpad: dict[str, Any],
) -> _VisibleObjectCandidate | None:
    if candidate.support.get("fixture_id") != candidate.target_fixture_id:
        return candidate
    refreshed_target = _current_worklist_target_fixture(
        contract=contract,
        object_id=handle,
        source_fixture_id=str(candidate.support.get("fixture_id") or ""),
    )
    if refreshed_target is None:
        agent_scratchpad["notes"].append(
            {"object_id": handle, "reason": "already_on_inferred_fixture"}
        )
        return None
    return _visible_object_candidate(
        detection=candidate.detection,
        target_fixture=refreshed_target,
        view_index=candidate.view_index,
    )


def _confirm_visual_scan_candidate(
    *,
    trace_events: list[dict[str, Any]],
    started_at: float,
    contract: RealWorldCleanupContract,
    base_contract: CleanupBackendSession,
    handle: str,
    candidate: _VisibleObjectCandidate,
    static_fixture_projection: dict[str, Any],
    robot_view_steps: list[dict[str, Any]],
    output_dir: Path,
    view_index: int,
    record_robot_views: bool,
    agent_scratchpad: dict[str, Any],
) -> tuple[_VisibleObjectCandidate | None, int]:
    source_waypoint_id = str(
        candidate.detection.get("waypoint_id")
        or candidate.detection.get("last_waypoint_id")
        or candidate.support.get("waypoint_id")
        or ""
    )
    if source_waypoint_id:
        _call_tool(
            trace_events,
            started_at,
            "navigate_to_waypoint",
            {"waypoint_id": source_waypoint_id, "reason": "source_fpv_scan_confirm"},
            lambda selected=source_waypoint_id: contract.navigate_to_waypoint(selected),
        )
    _call_tool(
        trace_events,
        started_at,
        "adjust_camera",
        {"yaw_delta_deg": 15.0, "pitch_delta_deg": 0.0},
        lambda: contract.adjust_camera(yaw_delta_deg=15.0, pitch_delta_deg=0.0),
    )
    confirmed_observation = _call_tool(
        trace_events,
        started_at,
        "observe",
        {},
        contract.observe,
        postprocess=lambda response: _attach_raw_fpv_robot_view(
            response=response,
            contract=contract,
            base_contract=base_contract,
            robot_view_steps=robot_view_steps,
            output_dir=output_dir,
            view_index_ref=[view_index],
            record_robot_views=record_robot_views,
        ),
    )
    view_index = _view_index_after_raw_fpv(robot_view_steps, view_index)
    confirmed = next(
        (
            item
            for item in confirmed_observation.get("visible_object_detections", [])
            if item.get("object_id") == handle
        ),
        None,
    )
    if confirmed is None:
        agent_scratchpad["failed_attempts"].append(
            {"object_id": handle, "reason": "visual_scan_confirmation_missing"}
        )
        return None, view_index
    detection = dict(confirmed)
    target_fixture = contract.target_fixture_for_detection(
        detection,
        static_fixture_projection,
        include_runtime_backend_fixtures=True,
    )
    if target_fixture is None:
        agent_scratchpad["failed_attempts"].append(
            {"object_id": handle, "reason": "no_public_fixture_match_after_visual_scan"}
        )
        return None, view_index
    candidate = _visible_object_candidate(
        detection=detection,
        target_fixture=target_fixture,
        view_index=view_index,
    )
    return (
        _redirect_if_already_on_inferred_fixture(
            contract=contract,
            handle=handle,
            candidate=candidate,
            agent_scratchpad=agent_scratchpad,
        ),
        view_index,
    )


def _current_worklist_target_fixture(
    *,
    contract: RealWorldCleanupContract,
    object_id: str,
    source_fixture_id: str,
) -> dict[str, Any] | None:
    worklist = contract.cleanup_worklist_payload(
        static_fixture_projection=contract.static_fixture_projection()
    )
    for item in worklist.get("objects", []):
        if str(item.get("object_id") or "") != object_id:
            continue
        candidate_fixture_id = str(item.get("candidate_fixture_id") or "")
        if not candidate_fixture_id or candidate_fixture_id == source_fixture_id:
            return None
        target = contract.public_receptacles_by_id().get(candidate_fixture_id)
        return dict(target) if target else None
    return None


def _write_snapshot(
    *,
    contract: CleanupBackendSession,
    scenario: Any,
    output_path: Path,
    title: str,
) -> Path:
    visual_snapshot = contract.write_visual_snapshot(output_path, title=title)
    if visual_snapshot is not None:
        return visual_snapshot
    return write_state_snapshot(
        scenario,
        contract.object_locations(),
        output_path,
        title=title,
    )


def _internal_object_id(contract: RealWorldCleanupContract, handle: str) -> str | None:
    return contract._internal_object_id(handle)


def _cleanup_loop_contract_for_target(
    *,
    contract: RealWorldCleanupContract,
    planner_proof_evidence: dict[str, Any] | None,
    object_id: str,
    target_receptacle_id: str,
) -> Any:
    if planner_proof_evidence is None:
        return contract
    planner_proof_attachment = planner_proof_attachment_for_target(
        planner_proof_evidence,
        object_id=object_id,
        target_receptacle_id=target_receptacle_id,
    )
    if planner_proof_attachment is None:
        return contract
    executor = ProbeBackedCleanupPrimitiveExecutor(
        planner_proof_attachment,
        executor_name="probe_backed_realworld_cleanup_executor",
    )
    return PlannerBackedCleanupContractAdapter(
        contract,
        executor=executor,
        executor_name="probe_backed_realworld_cleanup_executor",
    )


def _planner_proof_paths(
    *,
    planner_proof_run_result: Path | None,
    planner_proof_run_results: list[Path] | None,
) -> list[Path]:
    paths = []
    if planner_proof_run_result is not None:
        paths.append(planner_proof_run_result)
    paths.extend(planner_proof_run_results or [])
    return paths


def _call_tool(
    events: list[dict[str, Any]],
    started_at: float,
    tool: str,
    request: dict[str, Any],
    fn: Any,
    *,
    postprocess: Any | None = None,
) -> dict[str, Any]:
    events.append(_trace_event(started_at, tool=tool, event="request", request=request))
    response = fn()
    if postprocess is not None:
        response = postprocess(response)
    events.append(_trace_event(started_at, tool=tool, event="response", response=response))
    return response


def _attach_raw_fpv_robot_view(
    *,
    response: dict[str, Any],
    contract: RealWorldCleanupContract,
    base_contract: CleanupBackendSession,
    robot_view_steps: list[dict[str, Any]],
    output_dir: Path,
    view_index_ref: list[int],
    record_robot_views: bool,
) -> dict[str, Any]:
    if (
        contract.perception_mode not in {RAW_FPV_ONLY_MODE, CAMERA_MODEL_POLICY_MODE}
        or not record_robot_views
        or not response.get("ok")
    ):
        return response
    raw = response.get("raw_fpv_observation")
    if not isinstance(raw, dict):
        return response
    observation_id = str(raw.get("observation_id", ""))
    if not observation_id:
        return response
    view_index_ref[0] = base_contract.record_robot_view_step(
        steps=robot_view_steps,
        output_dir=output_dir,
        index=view_index_ref[0],
        label_suffix=observation_id,
        action=f"observe {observation_id}",
        **camera_offsets_from_raw_fpv_observation(raw),
    )
    step = robot_view_steps[-1]
    attached = contract.attach_raw_fpv_observation_artifact(
        observation_id,
        views=step.get("views") or {},
        robot_view_label=str(step.get("label", "")),
    )
    if attached is None:
        return response
    updated = dict(response)
    updated["raw_fpv_observation"] = attached
    return updated


def _view_index_after_raw_fpv(steps: list[dict[str, Any]], fallback_index: int) -> int:
    if not steps:
        return fallback_index
    try:
        label = str(steps[-1].get("label", ""))
        return max(fallback_index, int(label.split("_", 1)[0]) + 1)
    except (TypeError, ValueError):
        return fallback_index


def _trace_event(started_at: float, *, tool: str, event: str, **payload: Any) -> dict[str, Any]:
    now = time.time()
    return {
        "ts": now,
        "wallclock_elapsed": round(now - started_at, 6),
        "tool": tool,
        "event": event,
        **payload,
    }


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
