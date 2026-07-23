from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from roboclaws.household import agent_view as agent_view_module
from roboclaws.household.advisory_scoring import build_advisory_evaluation
from roboclaws.household.backend import API_SEMANTIC_PROVENANCE
from roboclaws.household.cleanup_primitive_evidence import (
    cleanup_primitive_evidence_from_substeps,
)
from roboclaws.household.household_runtime_contract import (
    CAMERA_MODEL_POLICY_MODE,
    REALWORLD_CONTRACT,
    cleanup_policy_trace_from_events,
    real_robot_readiness_from_events,
)
from roboclaws.household.isaac_lab_backend import (
    ISAACLAB_ROBOT_VIEW_VARIANT,
    ISAACLAB_SUBPROCESS_BACKEND,
)
from roboclaws.household.manipulation_provenance import (
    api_semantic_manipulation_evidence,
)
from roboclaws.household.nav2_map_bundle import attach_nav2_map_bundle_snapshot
from roboclaws.household.planner_proof_attachment import attach_planner_proof
from roboclaws.household.planner_proof_requests import write_planner_proof_requests
from roboclaws.household.profiles import (
    camera_labeler_from_visual_grounding_pipeline,
    evidence_lane_metadata_for_run,
)
from roboclaws.household.report import render_cleanup_report
from roboclaws.household.report_sections_timing import runtime_timing_from_trace
from roboclaws.household.semantic_timeline import (
    ROBOT_VIEW_VARIANT,
    SEMANTIC_LOOP_VARIANT,
    cleanup_plan_from_semantic_substeps,
    primitive_provenance_counts,
    robot_view_camera_control_summary,
    semantic_diagnostics,
    semantic_substeps,
)
from roboclaws.household.skill_scratchpad import read_or_create_skill_scratchpad
from roboclaws.household.task_intent import normalize_household_intent
from roboclaws.household.types import CleanupScenario
from roboclaws.launch.environment_setup_metadata import environment_setup_run_metadata_from_env
from roboclaws.launch.goals import (
    GoalContract,
    completion_claim_from_done_reason,
    write_goal_contract,
)


@dataclass(frozen=True)
class RealWorldMCPDoneArtifactInputs:
    run_dir: Path
    trace_path: Path
    run_result_path: Path
    base_contract: Any
    contract: Any
    scenario: CleanupScenario
    task_name: str
    task_prompt: str
    task_intent: str
    goal_contract: GoalContract | None
    policy: str
    agent_driven: bool
    policy_uses_private_truth: bool
    static_fixture_projection_mode: str
    perception_mode: str
    map_bundle_dir: Path | None
    runtime_map_prior_source: str
    evidence_lane: str | None
    record_robot_views: bool
    planner_proof_run_result: Path | None
    robot_view_steps: list[dict[str, Any]]
    robot_view_capture_policy: str
    before_snapshot: Path
    after_snapshot: Path
    trace_events: list[dict[str, Any]]
    agent_view: dict[str, Any]
    done_response: dict[str, Any]
    reason: str
    tool_event_counts: dict[str, int]
    rerun_command: str
    mcp_server_name: str


@dataclass(frozen=True)
class RealWorldMCPDoneArtifacts:
    run_result: dict[str, Any]
    report_path: Path
    intent_status: str


@dataclass(frozen=True)
class _MCPArtifactPaths:
    agent_view: Path
    runtime_metric_map: Path
    private_evaluation: Path
    advisory_evaluation: Path
    goal_contract: Path
    agent_scratchpad: Path
    planner_proof_requests: Path
    run_result: Path


@dataclass(frozen=True)
class _MCPDonePayloads:
    task_intent: str
    terminal_status: str
    intent_status: str
    runtime_timing: dict[str, Any]
    substeps: list[dict[str, Any]]
    cleanup_primitive_evidence: dict[str, Any]
    cleanup_plan: dict[str, Any]
    planner_proof_requests: dict[str, Any]
    diagnostics: dict[str, Any]
    primitive_counts: dict[str, int]
    cleanup_policy_trace: dict[str, Any]
    real_robot_readiness: dict[str, Any]
    private_evaluation: dict[str, Any]
    advisory_evaluation: dict[str, Any]
    goal_contract_payload: dict[str, Any]
    completion_claim: dict[str, Any]
    runtime_metric_map: dict[str, Any]
    runtime_prior_rows: list[dict[str, Any]]
    agent_scratchpad: dict[str, Any]
    agent_scratchpad_path: Path


def finalize_realworld_mcp_done(
    inputs: RealWorldMCPDoneArtifactInputs,
) -> RealWorldMCPDoneArtifacts:
    paths = _artifact_paths(inputs)
    payloads = _build_payloads(inputs, paths)
    _write_public_artifacts(inputs, paths, payloads)
    run_result = _base_run_result(inputs, paths, payloads)
    run_result = _attach_run_result_sections(inputs, run_result)
    report_path = render_cleanup_report(
        run_dir=inputs.run_dir,
        scenario=inputs.scenario,
        run_result=run_result,
        trace_events=inputs.trace_events,
        before_snapshot=inputs.before_snapshot,
        after_snapshot=inputs.after_snapshot,
        robot_view_steps=inputs.robot_view_steps,
    )
    run_result["artifacts"]["report"] = str(report_path)
    _write_json(paths.run_result, run_result)
    return RealWorldMCPDoneArtifacts(
        run_result=run_result,
        report_path=report_path,
        intent_status=payloads.intent_status,
    )


def _artifact_paths(inputs: RealWorldMCPDoneArtifactInputs) -> _MCPArtifactPaths:
    return _MCPArtifactPaths(
        agent_view=inputs.run_dir / "agent_view.json",
        runtime_metric_map=inputs.run_dir / "runtime_metric_map.json",
        private_evaluation=inputs.run_dir / "private_evaluation.json",
        advisory_evaluation=inputs.run_dir / "advisory_evaluation.json",
        goal_contract=inputs.run_dir / "goal_contract.json",
        agent_scratchpad=inputs.run_dir / "agent_scratchpad.json",
        planner_proof_requests=inputs.run_dir / "planner_proof_requests.json",
        run_result=inputs.run_result_path,
    )


def _build_payloads(
    inputs: RealWorldMCPDoneArtifactInputs,
    paths: _MCPArtifactPaths,
) -> _MCPDonePayloads:
    substeps = semantic_substeps(
        inputs.trace_events,
        inputs.contract.public_receptacles_by_id(),
    )
    private_evaluation = _private_evaluation(inputs)
    task_intent = _task_intent(inputs)
    terminal_status = _terminal_status(task_intent, inputs.done_response)
    agent_scratchpad, agent_scratchpad_path = read_or_create_skill_scratchpad(
        run_dir=inputs.run_dir,
        note=(
            "No live cleanup_scratch.json was present when the MCP server finalized; "
            "cleanup_worklist remains authoritative."
        ),
    )
    runtime_metric_map = agent_view_module.runtime_metric_map(inputs.agent_view)
    return _MCPDonePayloads(
        task_intent=task_intent,
        terminal_status=terminal_status,
        intent_status=terminal_status,
        runtime_timing=runtime_timing_from_trace(inputs.trace_events, inputs.robot_view_steps),
        substeps=substeps,
        cleanup_primitive_evidence=cleanup_primitive_evidence_from_substeps(substeps),
        cleanup_plan=cleanup_plan_from_semantic_substeps(substeps),
        planner_proof_requests=write_planner_proof_requests(
            output_path=paths.planner_proof_requests,
            contract=inputs.contract,
            substeps=substeps,
        ),
        diagnostics=_diagnostics(inputs, substeps),
        primitive_counts=primitive_provenance_counts(inputs.trace_events),
        cleanup_policy_trace=_cleanup_policy_trace(inputs),
        real_robot_readiness=_real_robot_readiness(inputs),
        private_evaluation=private_evaluation,
        advisory_evaluation=build_advisory_evaluation(
            score=inputs.done_response["score"],
            scenario_id=inputs.scenario.scenario_id,
        ),
        goal_contract_payload=_goal_contract_payload(inputs),
        completion_claim=_completion_claim(inputs),
        runtime_metric_map=runtime_metric_map,
        runtime_prior_rows=_runtime_prior_rows(runtime_metric_map),
        agent_scratchpad=agent_scratchpad,
        agent_scratchpad_path=agent_scratchpad_path,
    )


def _write_public_artifacts(
    inputs: RealWorldMCPDoneArtifactInputs,
    paths: _MCPArtifactPaths,
    payloads: _MCPDonePayloads,
) -> None:
    _write_json(paths.agent_view, inputs.agent_view)
    _write_json(paths.runtime_metric_map, payloads.runtime_metric_map)
    _write_json(paths.private_evaluation, payloads.private_evaluation)
    _write_json(paths.advisory_evaluation, payloads.advisory_evaluation)
    if inputs.goal_contract is not None:
        write_goal_contract(paths.goal_contract, inputs.goal_contract)


def _base_run_result(
    inputs: RealWorldMCPDoneArtifactInputs,
    paths: _MCPArtifactPaths,
    payloads: _MCPDonePayloads,
) -> dict[str, Any]:
    return {
        "backend": _backend_name(inputs),
        "task_name": inputs.task_name,
        "scenario_id": inputs.scenario.scenario_id,
        "seed": inputs.scenario.seed,
        "task_prompt": inputs.task_prompt,
        "task_surface": payloads.goal_contract_payload.get("surface", "household-world"),
        "task_intent": payloads.task_intent,
        "goal_contract": payloads.goal_contract_payload,
        "agent_completion_claim": payloads.completion_claim,
        "contract": REALWORLD_CONTRACT,
        "adr_0003_satisfied": True,
        "final_status": payloads.terminal_status,
        "intent_status": payloads.intent_status,
        "goal_status": payloads.intent_status,
        "cleanup_status_role": ("advisory" if payloads.task_intent == "open-ended" else "terminal"),
        "terminate_reason": inputs.reason,
        "cleanup_status": inputs.done_response["cleanup_status"],
        "completion_status": inputs.done_response["score"]["completion_status"],
        "primitive_provenance": API_SEMANTIC_PROVENANCE,
        "primitive_provenance_summary": payloads.primitive_counts,
        "manipulation_evidence": api_semantic_manipulation_evidence(
            backend=_backend_name(inputs),
            primitive_summary=payloads.primitive_counts,
        ),
        "policy": inputs.policy,
        "planner": inputs.policy,
        "agent_driven": inputs.agent_driven,
        "policy_uses_private_truth": inputs.policy_uses_private_truth,
        "planner_uses_private_manifest": False,
        "static_fixture_projection_mode": inputs.static_fixture_projection_mode,
        "perception_mode": inputs.perception_mode,
        "runtime_metric_map_prior": _runtime_map_prior_payload(inputs, payloads),
        "camera_labeler": _camera_labeler(inputs),
        "visual_grounding_pipeline_id": inputs.contract.visual_grounding_pipeline_id,
        "requested_generated_mess_count": payloads.private_evaluation[
            "requested_generated_mess_count"
        ],
        "generated_mess_count": payloads.private_evaluation["generated_mess_count"],
        "mcp_server": inputs.mcp_server_name,
        "mess_restoration_rate": inputs.done_response["score"]["mess_restoration_rate"],
        "sweep_coverage_rate": inputs.done_response["score"]["sweep_coverage_rate"],
        "disturbance_count": inputs.done_response["score"]["disturbance_count"],
        "semantic_loop_variant": SEMANTIC_LOOP_VARIANT,
        "semantic_substeps": payloads.substeps,
        "cleanup_primitive_evidence": payloads.cleanup_primitive_evidence,
        "planner_proof_requests": payloads.planner_proof_requests,
        "cleanup_plan": payloads.cleanup_plan,
        "cleanup_policy_trace": payloads.cleanup_policy_trace,
        "real_robot_readiness": payloads.real_robot_readiness,
        "agent_view": inputs.agent_view,
        "runtime_metric_map": payloads.runtime_metric_map,
        "raw_fpv_observations": agent_view_module.raw_fpv_observations(inputs.agent_view),
        "camera_model_policy_evidence": agent_view_module.camera_model_policy_evidence(
            inputs.agent_view
        ),
        "model_declared_observations": agent_view_module.model_declared_observations(
            inputs.agent_view
        ),
        "model_declared_observation_evidence": (
            agent_view_module.model_declared_observation_evidence(inputs.agent_view)
        ),
        "agent_scratchpad": payloads.agent_scratchpad,
        "private_evaluation": payloads.private_evaluation,
        "advisory_evaluation": payloads.advisory_evaluation,
        "score": inputs.done_response["score"],
        "final_locations": inputs.done_response["final_locations"],
        "final_containment": inputs.done_response.get("final_containment", {}),
        "tool_event_counts": dict(inputs.tool_event_counts),
        "backend_tool_event_counts": inputs.done_response["tool_event_counts"],
        "runtime_timing": payloads.runtime_timing,
        "agent_diagnostics": payloads.diagnostics,
        "rerun_command": inputs.rerun_command,
        "artifacts": _artifact_payload(inputs, paths, payloads),
    }


def _attach_run_result_sections(
    inputs: RealWorldMCPDoneArtifactInputs,
    run_result: dict[str, Any],
) -> dict[str, Any]:
    _attach_profile_metadata(inputs, run_result)
    run_result = _with_run_metadata(inputs, run_result)
    attach_nav2_map_bundle_snapshot(
        run_result=run_result,
        run_dir=inputs.run_dir,
        source_bundle_dir=inputs.map_bundle_dir,
    )
    _attach_backend_runtime_metadata(inputs, run_result)
    _attach_robot_view_metadata(inputs, run_result)
    _attach_planner_proof_metadata(inputs, run_result)
    return run_result


def _attach_profile_metadata(
    inputs: RealWorldMCPDoneArtifactInputs,
    run_result: dict[str, Any],
) -> None:
    if inputs.evidence_lane is None:
        return
    profile_metadata = evidence_lane_metadata_for_run(
        evidence_lane_name=inputs.evidence_lane,
        backend=_backend_name(inputs),
        perception_mode=inputs.perception_mode,
        record_robot_views=inputs.record_robot_views,
        camera_labeler=(
            _camera_labeler(inputs) if inputs.perception_mode == CAMERA_MODEL_POLICY_MODE else None
        ),
    )
    run_result["evidence_lane"] = profile_metadata["evidence_lane"]
    run_result["evidence_lane_metadata"] = profile_metadata


def _with_run_metadata(
    inputs: RealWorldMCPDoneArtifactInputs,
    run_result: dict[str, Any],
) -> dict[str, Any]:
    run_metadata = environment_setup_run_metadata_from_env()
    override_hook = getattr(inputs.contract, "run_result_overrides", None)
    if callable(override_hook):
        run_metadata = _merge_run_metadata(run_metadata, override_hook())
    if not run_metadata:
        return run_result
    return _merge_run_metadata(run_result, run_metadata)


def _attach_backend_runtime_metadata(
    inputs: RealWorldMCPDoneArtifactInputs,
    run_result: dict[str, Any],
) -> None:
    attach = getattr(inputs.base_contract, "attach_runtime_metadata", None)
    if callable(attach):
        attach(run_result, run_dir=inputs.run_dir)


def _attach_robot_view_metadata(
    inputs: RealWorldMCPDoneArtifactInputs,
    run_result: dict[str, Any],
) -> None:
    if not inputs.robot_view_steps:
        return
    run_result["view_variant"] = (
        ISAACLAB_ROBOT_VIEW_VARIANT
        if _backend_name(inputs) == ISAACLAB_SUBPROCESS_BACKEND
        else ROBOT_VIEW_VARIANT
    )
    run_result["robot_view_steps"] = inputs.robot_view_steps
    run_result["robot_view_capture_policy"] = inputs.robot_view_capture_policy
    run_result["robot_view_camera_control"] = robot_view_camera_control_summary(
        inputs.robot_view_steps
    )
    run_result["artifacts"]["robot_views"] = str(inputs.run_dir / "robot_views")


def _attach_planner_proof_metadata(
    inputs: RealWorldMCPDoneArtifactInputs,
    run_result: dict[str, Any],
) -> None:
    if inputs.planner_proof_run_result is None:
        return
    run_result["planner_backed_manipulation_proof"] = attach_planner_proof(
        proof_run_result_path=inputs.planner_proof_run_result,
        cleanup_run_dir=inputs.run_dir,
    )
    run_result["artifacts"]["planner_proof_views"] = str(inputs.run_dir / "planner_proof")


def _diagnostics(
    inputs: RealWorldMCPDoneArtifactInputs,
    substeps: list[dict[str, Any]],
) -> dict[str, Any]:
    diagnostics = semantic_diagnostics(inputs.trace_events, substeps, inputs.done_response)
    diagnostics["premature_done"] = (
        inputs.done_response["score"].get("sweep_coverage_rate", 0) < 0.90
    )
    diagnostics["premature_done_source"] = "sweep_coverage_rate"
    return diagnostics


def _real_robot_readiness(inputs: RealWorldMCPDoneArtifactInputs) -> dict[str, Any]:
    readiness_hook = getattr(inputs.contract, "real_robot_readiness_payload", None)
    if callable(readiness_hook):
        return readiness_hook(inputs.trace_events)
    return real_robot_readiness_from_events(
        agent_view=inputs.agent_view,
        trace_events=inputs.trace_events,
        robot_view_steps=inputs.robot_view_steps,
    )


def _cleanup_policy_trace(inputs: RealWorldMCPDoneArtifactInputs) -> dict[str, Any]:
    trace_hook = getattr(inputs.contract, "cleanup_policy_trace_payload", None)
    if callable(trace_hook):
        return trace_hook(inputs.trace_events)
    return cleanup_policy_trace_from_events(inputs.trace_events, inputs.agent_view)


def _private_evaluation(inputs: RealWorldMCPDoneArtifactInputs) -> dict[str, Any]:
    private_evaluation = inputs.contract.private_evaluation_payload(inputs.done_response["score"])
    backend = getattr(inputs.base_contract, "backend", None)
    requested_count = getattr(
        backend,
        "requested_generated_mess_count",
        private_evaluation["generated_mess_count"],
    )
    private_evaluation["requested_generated_mess_count"] = requested_count
    return private_evaluation


def _goal_contract_payload(inputs: RealWorldMCPDoneArtifactInputs) -> dict[str, Any]:
    if inputs.goal_contract is None:
        return {}
    return inputs.goal_contract.to_payload()


def _completion_claim(inputs: RealWorldMCPDoneArtifactInputs) -> dict[str, Any]:
    if inputs.goal_contract is None:
        return {}
    return completion_claim_from_done_reason(
        inputs.reason,
        goal_contract=inputs.goal_contract,
    )


def _task_intent(inputs: RealWorldMCPDoneArtifactInputs) -> str:
    goal_contract_payload = _goal_contract_payload(inputs)
    return normalize_household_intent(
        goal_contract_payload.get("intent") or inputs.task_intent,
    )


def _terminal_status(task_intent: str, done_response: dict[str, Any]) -> str:
    return "success" if task_intent == "open-ended" else done_response["cleanup_status"]


def _runtime_prior_rows(runtime_metric_map: dict[str, Any]) -> list[dict[str, Any]]:
    return [
        item
        for item in runtime_metric_map.get("observed_objects", [])
        if item.get("freshness") == "prior"
    ]


def _runtime_map_prior_payload(
    inputs: RealWorldMCPDoneArtifactInputs,
    payloads: _MCPDonePayloads,
) -> dict[str, Any]:
    object_prior_count = len(payloads.runtime_prior_rows)
    anchor_prior_count = len(getattr(inputs.contract, "_runtime_map_anchor_priors", []) or [])
    room_prior_count = len(getattr(inputs.contract, "_runtime_map_room_priors", []) or [])
    return {
        "loaded": bool(
            inputs.runtime_map_prior_source
            or object_prior_count
            or anchor_prior_count
            or room_prior_count
        ),
        "source_provided": bool(inputs.runtime_map_prior_source),
        "source": inputs.runtime_map_prior_source,
        "observed_object_count": object_prior_count,
        "object_prior_count": object_prior_count,
        "anchor_prior_count": anchor_prior_count,
        "room_prior_count": room_prior_count,
    }


def _camera_labeler(inputs: RealWorldMCPDoneArtifactInputs) -> str:
    if inputs.perception_mode != CAMERA_MODEL_POLICY_MODE:
        return ""
    return camera_labeler_from_visual_grounding_pipeline(
        inputs.contract.visual_grounding_pipeline_id
    )


def _artifact_payload(
    inputs: RealWorldMCPDoneArtifactInputs,
    paths: _MCPArtifactPaths,
    payloads: _MCPDonePayloads,
) -> dict[str, str]:
    artifacts = {
        "agent_view": str(paths.agent_view),
        "runtime_metric_map": str(paths.runtime_metric_map),
        "private_evaluation": str(paths.private_evaluation),
        "advisory_evaluation": str(paths.advisory_evaluation),
        "agent_scratchpad": str(payloads.agent_scratchpad_path),
        "planner_proof_requests": str(paths.planner_proof_requests),
        "trace": str(inputs.trace_path),
        "before_snapshot": str(inputs.before_snapshot),
        "after_snapshot": str(inputs.after_snapshot),
    }
    if inputs.goal_contract is not None:
        artifacts["goal_contract"] = str(paths.goal_contract)
    return artifacts


def _backend_name(inputs: RealWorldMCPDoneArtifactInputs) -> str:
    contract_backend_name = getattr(inputs.contract, "backend_name", None)
    if callable(contract_backend_name):
        return str(contract_backend_name())
    session_backend_name = getattr(inputs.base_contract, "backend_name", None)
    if callable(session_backend_name):
        return str(session_backend_name())
    return ""


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


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
