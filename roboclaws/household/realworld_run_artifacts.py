from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from roboclaws.core.environment_setup_metadata import environment_setup_run_metadata_from_env
from roboclaws.core.goals import (
    GoalContract,
    completion_claim_from_done_reason,
    write_goal_contract,
)
from roboclaws.core.map_build_scan_profile import MapBuildScanProfile
from roboclaws.core.rerun import report_rerun_command_from_env
from roboclaws.household import agent_view as agent_view_module
from roboclaws.household.advisory_scoring import build_advisory_evaluation
from roboclaws.household.cleanup_primitive_evidence import (
    cleanup_primitive_evidence_from_substeps,
)
from roboclaws.household.household_backend_contract import HouseholdBackendSession
from roboclaws.household.household_runtime_contract import (
    CAMERA_MODEL_POLICY_MODE,
    REALWORLD_CONTRACT,
    HouseholdRuntimeContract,
    cleanup_policy_trace_from_events,
    real_robot_readiness_from_events,
)
from roboclaws.household.isaac_lab_backend import (
    ISAACLAB_ROBOT_VIEW_VARIANT,
    ISAACLAB_SUBPROCESS_BACKEND,
)
from roboclaws.household.manipulation_contract import (
    API_SEMANTIC_PROVENANCE,
    ISAAC_SEMANTIC_POSE_PROVENANCE,
)
from roboclaws.household.manipulation_provenance import (
    api_semantic_manipulation_evidence,
    isaac_semantic_pose_manipulation_evidence,
    planner_backed_cleanup_manipulation_evidence,
)
from roboclaws.household.nav2_map_bundle import attach_nav2_map_bundle_snapshot
from roboclaws.household.planner_cleanup_bridge import planner_cleanup_bridge_evidence
from roboclaws.household.planner_proof_requests import write_planner_proof_requests
from roboclaws.household.profiles import (
    camera_labeler_from_visual_grounding_pipeline,
    evidence_lane_metadata_for_run,
)
from roboclaws.household.report import render_cleanup_report
from roboclaws.household.report_snapshots import write_trace_jsonl
from roboclaws.household.semantic_camera_timeline import robot_view_camera_control_summary
from roboclaws.household.semantic_timeline import (
    ROBOT_VIEW_VARIANT,
    SEMANTIC_LOOP_VARIANT,
    primitive_provenance_counts,
    semantic_substeps,
)
from roboclaws.household.types import CleanupScenario
from roboclaws.maps.preview import render_runtime_metric_map_preview


def goal_result_payload(
    goal_contract: GoalContract | None,
    *,
    done_reason: str,
) -> tuple[dict[str, Any], dict[str, Any]]:
    if goal_contract is None:
        return {}, {}
    return (
        goal_contract.to_payload(),
        completion_claim_from_done_reason(done_reason, goal_contract=goal_contract),
    )


def terminal_status_payload(task_intent: str, cleanup_status: str) -> dict[str, str]:
    status = "success" if task_intent == "open-ended" else cleanup_status
    return {
        "intent_status": status,
        "goal_status": status,
        "final_status": status,
        "cleanup_status_role": "advisory" if task_intent == "open-ended" else "terminal",
    }


def public_agent_view_result_payload(agent_view: dict[str, Any]) -> dict[str, Any]:
    return {
        "raw_fpv_observations": agent_view_module.raw_fpv_observations(agent_view),
        "camera_model_policy_evidence": agent_view_module.camera_model_policy_evidence(agent_view),
        "model_declared_observations": agent_view_module.model_declared_observations(agent_view),
        "model_declared_observation_evidence": (
            agent_view_module.model_declared_observation_evidence(agent_view)
        ),
    }


def runtime_map_prior_summary(
    *,
    source: str,
    object_prior_count: int,
    anchor_prior_count: int,
    room_prior_count: int,
    loaded: bool | None = None,
) -> dict[str, Any]:
    return {
        "loaded": (
            bool(source or object_prior_count or anchor_prior_count or room_prior_count)
            if loaded is None
            else loaded
        ),
        "source_provided": bool(source),
        "source": source,
        "observed_object_count": object_prior_count,
        "object_prior_count": object_prior_count,
        "anchor_prior_count": anchor_prior_count,
        "room_prior_count": room_prior_count,
    }


def evidence_lane_result_payload(
    *,
    evidence_lane: str | None,
    backend: str,
    perception_mode: str,
    record_robot_views: bool,
    camera_labeler: str,
) -> dict[str, Any]:
    if evidence_lane is None:
        return {}
    metadata = evidence_lane_metadata_for_run(
        evidence_lane_name=evidence_lane,
        backend=backend,
        perception_mode=perception_mode,
        record_robot_views=record_robot_views,
        camera_labeler=(camera_labeler if perception_mode == CAMERA_MODEL_POLICY_MODE else None),
    )
    return {
        "evidence_lane": metadata["evidence_lane"],
        "evidence_lane_metadata": metadata,
    }


def attach_robot_view_result_metadata(
    run_result: dict[str, Any],
    *,
    run_dir: Path,
    backend: str,
    robot_view_steps: list[dict[str, Any]],
    capture_policy: str | None = None,
) -> None:
    if not robot_view_steps:
        return
    run_result["view_variant"] = (
        ISAACLAB_ROBOT_VIEW_VARIANT
        if backend == ISAACLAB_SUBPROCESS_BACKEND
        else ROBOT_VIEW_VARIANT
    )
    run_result["robot_view_steps"] = robot_view_steps
    if capture_policy is not None:
        run_result["robot_view_capture_policy"] = capture_policy
    run_result["robot_view_camera_control"] = robot_view_camera_control_summary(robot_view_steps)
    run_result["artifacts"]["robot_views"] = str(run_dir / "robot_views")


@dataclass(frozen=True)
class RealWorldRunArtifactInputs:
    output_dir: Path
    backend: str
    base_contract: HouseholdBackendSession
    contract: HouseholdRuntimeContract
    scenario: CleanupScenario
    seed: int
    task_prompt: str
    policy_name: str
    done: dict[str, Any]
    trace_events: list[dict[str, Any]]
    before_snapshot: Path
    after_snapshot: Path
    robot_view_steps: list[dict[str, Any]]
    generated_mess_count: int
    goal_contract: GoalContract | None
    agent_scratchpad: dict[str, Any]
    map_build: bool
    runtime_map_prior: dict[str, Any] | None
    runtime_map_prior_path: str | Path | None
    evidence_lane: str | None
    perception_mode: str
    record_robot_views: bool
    selected_bundle_dir: Path | None
    planner_proof_evidence: dict[str, Any] | None
    use_planner_proof_for_cleanup_primitives: bool
    map_build_scan_profile: MapBuildScanProfile
    run_metadata_overrides: dict[str, Any] | None = None


@dataclass(frozen=True)
class _RunArtifactPaths:
    trace: Path
    agent_view: Path
    runtime_metric_map: Path
    runtime_metric_map_preview: Path
    private_evaluation: Path
    advisory_evaluation: Path
    goal_contract: Path
    agent_scratchpad: Path
    planner_proof_requests: Path
    run_result: Path


@dataclass(frozen=True)
class _PrimitiveEvidence:
    provenance: str
    summary: dict[str, Any]
    manipulation: dict[str, Any]


@dataclass(frozen=True)
class _RunPayloads:
    agent_view: dict[str, Any]
    runtime_metric_map: dict[str, Any]
    cleanup_policy_trace: dict[str, Any]
    real_robot_readiness: dict[str, Any]
    private_evaluation: dict[str, Any]
    advisory_evaluation: dict[str, Any]
    goal_contract_payload: dict[str, Any]
    agent_completion_claim: dict[str, Any]
    substeps: list[dict[str, Any]]
    cleanup_primitive_evidence: dict[str, Any]
    planner_proof_requests: dict[str, Any]
    primitive: _PrimitiveEvidence
    public_tool_counts: dict[str, int]
    profile_metadata: dict[str, Any] | None


def finalize_realworld_cleanup_run(inputs: RealWorldRunArtifactInputs) -> dict[str, Any]:
    artifacts = _artifact_paths(inputs.output_dir)
    write_trace_jsonl(artifacts.trace, inputs.trace_events)
    payloads = _build_payloads(inputs, artifacts)
    _write_public_artifacts(inputs, artifacts, payloads)
    run_result = _base_run_result(inputs, artifacts, payloads)
    _attach_run_result_sections(inputs, run_result, payloads)
    run_result = _with_run_metadata(run_result, inputs.run_metadata_overrides)
    report_path = render_cleanup_report(
        run_dir=inputs.output_dir,
        scenario=inputs.scenario,
        run_result=run_result,
        trace_events=inputs.trace_events,
        before_snapshot=inputs.before_snapshot,
        after_snapshot=inputs.after_snapshot,
        robot_view_steps=inputs.robot_view_steps,
    )
    run_result["artifacts"]["report"] = str(report_path)
    _write_json(artifacts.run_result, run_result)
    return run_result


def _artifact_paths(
    output_dir: Path,
    *,
    trace_path: Path | None = None,
    run_result_path: Path | None = None,
) -> _RunArtifactPaths:
    return _RunArtifactPaths(
        trace=trace_path or output_dir / "trace.jsonl",
        agent_view=output_dir / "agent_view.json",
        runtime_metric_map=output_dir / "runtime_metric_map.json",
        runtime_metric_map_preview=output_dir / "runtime_metric_map_preview.png",
        private_evaluation=output_dir / "private_evaluation.json",
        advisory_evaluation=output_dir / "advisory_evaluation.json",
        goal_contract=output_dir / "goal_contract.json",
        agent_scratchpad=output_dir / "agent_scratchpad.json",
        planner_proof_requests=output_dir / "planner_proof_requests.json",
        run_result=run_result_path or output_dir / "run_result.json",
    )


def _build_payloads(
    inputs: RealWorldRunArtifactInputs,
    artifacts: _RunArtifactPaths,
) -> _RunPayloads:
    agent_view = inputs.contract.agent_view_payload()
    runtime_metric_map = agent_view_module.runtime_metric_map(agent_view)
    cleanup_policy_trace = cleanup_policy_trace_from_events(inputs.trace_events, agent_view)
    real_robot_readiness = real_robot_readiness_from_events(
        agent_view=agent_view,
        trace_events=inputs.trace_events,
        robot_view_steps=inputs.robot_view_steps,
    )
    private_evaluation = inputs.contract.private_evaluation_payload(inputs.done["score"])
    private_evaluation["requested_generated_mess_count"] = inputs.generated_mess_count
    substeps = semantic_substeps(
        inputs.trace_events,
        inputs.contract.public_receptacles_by_id(),
    )
    cleanup_primitive_evidence = cleanup_primitive_evidence_from_substeps(substeps)
    goal_contract_payload, agent_completion_claim = goal_result_payload(
        inputs.goal_contract,
        done_reason=str(inputs.done.get("reason") or f"{inputs.policy_name} complete"),
    )
    return _RunPayloads(
        agent_view=agent_view,
        runtime_metric_map=runtime_metric_map,
        cleanup_policy_trace=cleanup_policy_trace,
        real_robot_readiness=real_robot_readiness,
        private_evaluation=private_evaluation,
        advisory_evaluation=build_advisory_evaluation(
            score=inputs.done["score"],
            scenario_id=inputs.scenario.scenario_id,
        ),
        goal_contract_payload=goal_contract_payload,
        agent_completion_claim=agent_completion_claim,
        substeps=substeps,
        cleanup_primitive_evidence=cleanup_primitive_evidence,
        planner_proof_requests=write_planner_proof_requests(
            output_path=artifacts.planner_proof_requests,
            contract=inputs.contract,
            substeps=substeps,
        ),
        primitive=_primitive_evidence(inputs, cleanup_primitive_evidence),
        public_tool_counts=_tool_event_counts(inputs.trace_events),
        profile_metadata=_profile_metadata(inputs),
    )


def _write_public_artifacts(
    inputs: RealWorldRunArtifactInputs,
    artifacts: _RunArtifactPaths,
    payloads: _RunPayloads,
) -> None:
    _write_json(artifacts.agent_view, payloads.agent_view)
    _write_json(artifacts.runtime_metric_map, payloads.runtime_metric_map)
    write_runtime_metric_map_preview_artifact(
        output_dir=inputs.output_dir,
        runtime_metric_map=payloads.runtime_metric_map,
    )
    _write_json(artifacts.private_evaluation, payloads.private_evaluation)
    _write_json(artifacts.advisory_evaluation, payloads.advisory_evaluation)
    _write_json(artifacts.agent_scratchpad, inputs.agent_scratchpad)
    if inputs.goal_contract is not None:
        write_goal_contract(artifacts.goal_contract, inputs.goal_contract)


def _base_run_result(
    inputs: RealWorldRunArtifactInputs,
    artifacts: _RunArtifactPaths,
    payloads: _RunPayloads,
) -> dict[str, Any]:
    task_intent = str(
        payloads.goal_contract_payload.get("intent")
        or ("map-build" if inputs.map_build else "cleanup")
    )
    cleanup_status = inputs.done["cleanup_status"]
    return {
        "backend": inputs.backend,
        "scenario_id": inputs.scenario.scenario_id,
        "seed": inputs.seed,
        "task_prompt": inputs.task_prompt,
        "task_surface": payloads.goal_contract_payload.get("surface", "household-world"),
        "task_intent": task_intent,
        "goal_contract": payloads.goal_contract_payload,
        "agent_completion_claim": payloads.agent_completion_claim,
        "contract": REALWORLD_CONTRACT,
        "adr_0003_satisfied": True,
        **terminal_status_payload(task_intent, cleanup_status),
        "terminate_reason": f"{inputs.policy_name} complete",
        "cleanup_status": cleanup_status,
        "completion_status": inputs.done["score"]["completion_status"],
        "primitive_provenance": payloads.primitive.provenance,
        "primitive_provenance_summary": payloads.primitive.summary,
        "manipulation_evidence": payloads.primitive.manipulation,
        "policy": inputs.policy_name,
        "planner": inputs.policy_name,
        "agent_driven": False,
        "policy_uses_private_truth": False,
        "planner_uses_private_manifest": False,
        "planner_proof_cleanup_executor_enabled": (inputs.use_planner_proof_for_cleanup_primitives),
        "static_fixture_projection_mode": inputs.contract.static_fixture_projection_mode,
        "perception_mode": inputs.perception_mode,
        "map_build_mode": inputs.map_build,
        "cleanup_actions_disabled": inputs.map_build,
        "runtime_metric_map_prior": _runtime_map_prior_summary(inputs),
        "camera_labeler": _camera_labeler(inputs),
        "visual_grounding_pipeline_id": inputs.contract.visual_grounding_pipeline_id,
        "requested_generated_mess_count": inputs.generated_mess_count,
        "generated_mess_count": payloads.private_evaluation["generated_mess_count"],
        "mess_restoration_rate": inputs.done["score"]["mess_restoration_rate"],
        "sweep_coverage_rate": inputs.done["score"]["sweep_coverage_rate"],
        "disturbance_count": inputs.done["score"]["disturbance_count"],
        "semantic_loop_variant": SEMANTIC_LOOP_VARIANT,
        "semantic_substeps": payloads.substeps,
        "cleanup_primitive_evidence": payloads.cleanup_primitive_evidence,
        "planner_proof_requests": payloads.planner_proof_requests,
        "cleanup_policy_trace": payloads.cleanup_policy_trace,
        "real_robot_readiness": payloads.real_robot_readiness,
        "agent_view": payloads.agent_view,
        "runtime_metric_map": payloads.runtime_metric_map,
        **public_agent_view_result_payload(payloads.agent_view),
        "map_build": _map_build_payload(inputs, artifacts),
        "agent_scratchpad": inputs.agent_scratchpad,
        "private_evaluation": payloads.private_evaluation,
        "advisory_evaluation": payloads.advisory_evaluation,
        "score": inputs.done["score"],
        "final_locations": inputs.done["final_locations"],
        "final_containment": inputs.done.get("final_containment", {}),
        "tool_event_counts": payloads.public_tool_counts,
        "backend_tool_event_counts": inputs.done["tool_event_counts"],
        "rerun_command": report_rerun_command_from_env(),
        "artifacts": _base_artifacts_payload(artifacts, inputs),
    }


def _attach_run_result_sections(
    inputs: RealWorldRunArtifactInputs,
    run_result: dict[str, Any],
    payloads: _RunPayloads,
) -> None:
    if payloads.profile_metadata is not None:
        run_result.update(
            {
                "evidence_lane": payloads.profile_metadata["evidence_lane"],
                "evidence_lane_metadata": payloads.profile_metadata,
            }
        )
    attach_nav2_map_bundle_snapshot(
        run_result=run_result,
        run_dir=inputs.output_dir,
        source_bundle_dir=inputs.selected_bundle_dir,
    )
    inputs.base_contract.attach_runtime_metadata(run_result, run_dir=inputs.output_dir)
    attach_robot_view_result_metadata(
        run_result,
        run_dir=inputs.output_dir,
        backend=inputs.backend,
        robot_view_steps=inputs.robot_view_steps,
    )
    _attach_planner_proof_metadata(inputs, run_result, payloads)


def _attach_planner_proof_metadata(
    inputs: RealWorldRunArtifactInputs,
    run_result: dict[str, Any],
    payloads: _RunPayloads,
) -> None:
    if inputs.planner_proof_evidence is None:
        return
    run_result["planner_backed_manipulation_proof"] = inputs.planner_proof_evidence
    run_result["planner_cleanup_bridge_evidence"] = planner_cleanup_bridge_evidence(
        planner_proof_attachment=run_result["planner_backed_manipulation_proof"],
        cleanup_primitive_evidence=payloads.cleanup_primitive_evidence,
    )
    run_result["artifacts"]["planner_proof_views"] = str(inputs.output_dir / "planner_proof")


def _primitive_evidence(
    inputs: RealWorldRunArtifactInputs,
    cleanup_primitive_evidence: dict[str, Any],
) -> _PrimitiveEvidence:
    primitive_summary = primitive_provenance_counts(inputs.trace_events)
    if cleanup_primitive_evidence.get("planner_backed") is True:
        return _PrimitiveEvidence(
            provenance="planner_backed",
            summary=primitive_summary,
            manipulation=planner_backed_cleanup_manipulation_evidence(
                backend=inputs.backend,
                primitive_summary=primitive_summary,
            ),
        )
    if inputs.backend == ISAACLAB_SUBPROCESS_BACKEND:
        return _PrimitiveEvidence(
            provenance=ISAAC_SEMANTIC_POSE_PROVENANCE,
            summary=primitive_summary,
            manipulation=isaac_semantic_pose_manipulation_evidence(
                backend=inputs.backend,
                primitive_summary=primitive_summary,
            ),
        )
    return _PrimitiveEvidence(
        provenance=API_SEMANTIC_PROVENANCE,
        summary=primitive_summary,
        manipulation=api_semantic_manipulation_evidence(
            backend=inputs.backend,
            primitive_summary=primitive_summary,
        ),
    )


def _profile_metadata(inputs: RealWorldRunArtifactInputs) -> dict[str, Any] | None:
    if inputs.evidence_lane is None:
        return None
    return evidence_lane_result_payload(
        evidence_lane=inputs.evidence_lane,
        backend=inputs.backend,
        perception_mode=inputs.perception_mode,
        record_robot_views=inputs.record_robot_views,
        camera_labeler=_camera_labeler(inputs),
    )["evidence_lane_metadata"]


def _camera_labeler(inputs: RealWorldRunArtifactInputs) -> str:
    if inputs.perception_mode != CAMERA_MODEL_POLICY_MODE:
        return ""
    return camera_labeler_from_visual_grounding_pipeline(
        inputs.contract.visual_grounding_pipeline_id
    )


def _runtime_map_prior_summary(inputs: RealWorldRunArtifactInputs) -> dict[str, Any]:
    object_prior_count = len((inputs.runtime_map_prior or {}).get("observed_objects") or [])
    anchor_prior_count = len((inputs.runtime_map_prior or {}).get("public_semantic_anchors") or [])
    room_prior_count = len((inputs.runtime_map_prior or {}).get("rooms") or [])
    source = str(inputs.runtime_map_prior_path or "")
    return runtime_map_prior_summary(
        source=source,
        object_prior_count=object_prior_count,
        anchor_prior_count=anchor_prior_count,
        room_prior_count=room_prior_count,
        loaded=bool(inputs.runtime_map_prior),
    )


def _map_build_payload(
    inputs: RealWorldRunArtifactInputs,
    artifacts: _RunArtifactPaths,
) -> dict[str, Any]:
    scan_profile = inputs.map_build_scan_profile.to_payload()
    return {
        "enabled": inputs.map_build,
        "scan_profile": scan_profile,
        "scan_profile_id": scan_profile["profile"],
        "camera_schedule": scan_profile["camera_schedule"] if inputs.map_build else [],
        "body_turn_yaw_delta_deg": (
            scan_profile["body_turn_yaw_delta_deg"] if inputs.map_build else 0.0
        ),
        "body_turn_count_per_waypoint": (
            scan_profile["body_turn_count_per_waypoint"] if inputs.map_build else 0
        ),
        "uses_robot_body_turns": bool(inputs.map_build and scan_profile["uses_robot_body_turns"]),
        "snapshot_artifact": str(artifacts.runtime_metric_map) if inputs.map_build else "",
        "cleanup_actions_disabled": inputs.map_build,
        "stable_anchor_priority": bool(inputs.map_build and scan_profile["stable_anchor_priority"]),
        "movable_prior_policy": scan_profile["movable_prior_policy"] if inputs.map_build else "",
    }


def _base_artifacts_payload(
    artifacts: _RunArtifactPaths,
    inputs: RealWorldRunArtifactInputs,
) -> dict[str, str]:
    payload = {
        "agent_view": str(artifacts.agent_view),
        "runtime_metric_map": str(artifacts.runtime_metric_map),
        "runtime_metric_map_preview": str(artifacts.runtime_metric_map_preview),
        "private_evaluation": str(artifacts.private_evaluation),
        "advisory_evaluation": str(artifacts.advisory_evaluation),
        "agent_scratchpad": str(artifacts.agent_scratchpad),
        "planner_proof_requests": str(artifacts.planner_proof_requests),
        "trace": str(artifacts.trace),
        "before_snapshot": str(inputs.before_snapshot),
        "after_snapshot": str(inputs.after_snapshot),
    }
    if inputs.goal_contract is not None:
        payload["goal_contract"] = str(artifacts.goal_contract)
    return payload


def _with_run_metadata(
    run_result: dict[str, Any],
    overrides: dict[str, Any] | None,
) -> dict[str, Any]:
    run_metadata = _merge_run_metadata(
        environment_setup_run_metadata_from_env(),
        overrides or {},
    )
    if not run_metadata:
        return run_result
    return _merge_run_metadata(run_result, run_metadata)


def _merge_run_metadata(
    run_result: dict[str, Any],
    overrides: dict[str, Any],
) -> dict[str, Any]:
    merged = dict(run_result)
    for key, value in overrides.items():
        if isinstance(value, dict) and isinstance(merged.get(key), dict):
            merged[key] = {**merged[key], **value}
        else:
            merged[key] = value
    return merged


def _tool_event_counts(events: list[dict[str, Any]]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for event in events:
        tool = event.get("tool")
        event_name = event.get("event")
        if not tool or not event_name:
            continue
        key = f"{tool}:{event_name}"
        counts[key] = counts.get(key, 0) + 1
    return counts


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n")


def write_runtime_metric_map_preview_artifact(
    *,
    output_dir: Path,
    runtime_metric_map: dict[str, Any],
) -> Path:
    path = Path(output_dir) / "runtime_metric_map_preview.png"
    render_runtime_metric_map_preview(
        runtime_metric_map=runtime_metric_map,
        output_path=path,
    )
    return path
