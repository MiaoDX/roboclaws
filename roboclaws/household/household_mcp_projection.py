"""Public MCP response projection and artifact serialization."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from roboclaws.core.robot_view_capture import (
    ROBOT_VIEW_CAPTURE_POLICIES,
    ROBOT_VIEW_CAPTURE_POLICY_FULL,
)
from roboclaws.household.household_backend_contract import HouseholdBackendSession
from roboclaws.household.household_runtime_contract import (
    REALWORLD_CONTRACT,
    HouseholdRuntimeContract,
)
from roboclaws.household.scenario import build_cleanup_scenario
from roboclaws.household.semantic_timeline import (
    has_complete_semantic_sequence,
    successful_semantic_phases,
)
from roboclaws.household.types import CleanupScenario
from roboclaws.household.visual_grounding import visual_grounding_client_from_env


def _compact_declare_visual_candidates_response(response: dict[str, Any]) -> dict[str, Any]:
    evidence = response.get("model_declared_observation_evidence") or {}
    declarations = list(response.get("model_declared_observations") or [])
    candidates = list(response.get("camera_model_candidates") or [])
    pipeline = evidence.get("visual_grounding_pipeline") or {}
    if not pipeline:
        for item in declarations:
            candidate_pipeline = item.get("visual_grounding_pipeline")
            if isinstance(candidate_pipeline, dict) and candidate_pipeline:
                pipeline = candidate_pipeline
                break

    return {
        "ok": response.get("ok", True),
        "tool": response.get("tool", "declare_visual_candidates"),
        "status": response.get("status", "ok"),
        "contract": response.get("contract", REALWORLD_CONTRACT),
        "observation_id": evidence.get("observation_id", ""),
        "waypoint_id": evidence.get("waypoint_id", ""),
        "room_id": evidence.get("room_id", ""),
        "producer_type": evidence.get("producer_type", ""),
        "producer_id": evidence.get("producer_id", ""),
        "candidate_count": evidence.get("candidate_count", len(declarations)),
        "registered_observed_handles": list(evidence.get("registered_observed_handles") or []),
        "visual_grounding_pipeline": _compact_visual_grounding_pipeline(pipeline),
        "model_declared_observations": [
            _compact_model_declared_observation(item) for item in declarations
        ],
        "camera_model_candidates": [_compact_camera_model_candidate(item) for item in candidates],
        "visible_object_detections": [],
        "private_target_truth_included": False,
    }


def _complete_semantic_substep_handles(substeps: list[dict[str, Any]]) -> list[str]:
    handles = []
    for item in substeps:
        phases = successful_semantic_phases(item.get("steps", []))
        if has_complete_semantic_sequence(phases):
            handles.append(str(item.get("object_id") or ""))
    return [handle for handle in handles if handle]


def _build_realworld_mcp_contract(
    *,
    contract: HouseholdRuntimeContract | None,
    scenario: CleanupScenario | None,
    base_contract: HouseholdBackendSession | None,
    task_prompt: str,
    static_fixture_projection_mode: str,
    perception_mode: str,
    map_bundle_dir: Path | None,
    runtime_map_prior: dict[str, Any] | None,
    evidence_lane: str | None,
    task_intent: str,
    visual_grounding: str,
    visual_grounding_base_url: str | None,
    visual_grounding_timeout_s: float | None,
    run_dir: Path,
) -> HouseholdRuntimeContract:
    if contract is not None:
        return contract

    scenario = scenario or build_cleanup_scenario()
    base_contract = base_contract or HouseholdBackendSession(scenario)
    acceptance_config = _public_acceptance_config_from_backend(base_contract)
    acceptance_config["task_intent"] = task_intent
    return HouseholdRuntimeContract(
        base_contract,
        task_prompt=task_prompt,
        static_fixture_projection_mode=static_fixture_projection_mode,
        perception_mode=perception_mode,
        map_bundle_dir=map_bundle_dir,
        runtime_map_prior=runtime_map_prior,
        evidence_lane=evidence_lane,
        public_acceptance_config=acceptance_config,
        visual_grounding_client=visual_grounding_client_from_env(
            visual_grounding,
            base_url=visual_grounding_base_url,
            timeout_s=visual_grounding_timeout_s,
        ),
        visual_grounding_pipeline_id=visual_grounding,
        visual_grounding_artifact_base_dir=run_dir,
        visual_grounding_run_id=f"seed-{scenario.seed}",
    )


def _compact_visual_grounding_pipeline(pipeline: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(pipeline, dict):
        return {}
    compact = _select_keys(
        pipeline,
        (
            "schema",
            "pipeline_id",
            "status",
            "candidate_count",
            "unresolved_count",
            "duplicate_rate",
            "failure_reason",
            "failure_message",
            "auth_mode",
        ),
    )
    compact["stages"] = [
        _select_keys(
            stage,
            ("stage", "status", "producer_id", "model_id", "latency_ms", "version"),
        )
        for stage in pipeline.get("stages") or []
        if isinstance(stage, dict)
    ]
    return compact


def _compact_model_declared_observation(item: dict[str, Any]) -> dict[str, Any]:
    compact = _select_keys(
        item,
        (
            "declaration_id",
            "object_id",
            "source_observation_id",
            "waypoint_id",
            "room_id",
            "category",
            "target_fixture_id",
            "target_fixture_category",
            "source_fixture_id",
            "evidence_note",
            "image_region",
            "confidence",
            "producer_type",
            "producer_id",
            "grounding_status",
            "grounding_confidence",
            "grounding_basis",
            "recovery_hint",
            "actionability_status",
            "visual_grounding_destination_hint",
            "image_dimensions",
            "visual_grounding_overlay",
        ),
    )
    target_plausibility = item.get("target_plausibility")
    if isinstance(target_plausibility, dict):
        compact["target_plausibility"] = _select_keys(
            target_plausibility,
            ("status", "basis", "expected_fixture_id"),
        )
    compact["visual_grounding_evidence"] = _compact_visual_grounding_evidence(
        item.get("visual_grounding_evidence")
    )
    return compact


def _compact_camera_model_candidate(item: dict[str, Any]) -> dict[str, Any]:
    compact = _select_keys(
        item,
        (
            "object_id",
            "category",
            "name",
            "current_room_id",
            "visibility_confidence",
            "image_bbox",
            "perception_source",
            "producer_type",
            "producer_id",
            "source_observation_id",
            "candidate_source",
            "candidate_fixture_id",
            "candidate_fixture_category",
            "cleanup_recommended",
            "recommended_tool",
            "model_declared_observation_id",
            "image_region",
            "evidence_note",
            "grounding_status",
            "grounding_confidence",
            "grounding_basis",
            "actionability_status",
        ),
    )
    support_estimate = item.get("support_estimate")
    if isinstance(support_estimate, dict):
        compact["support_estimate"] = _select_keys(
            support_estimate,
            ("fixture_id", "relation", "confidence", "source", "perception_source"),
        )
    compact["visual_grounding_evidence"] = _compact_visual_grounding_evidence(
        item.get("visual_grounding_evidence")
    )
    return compact


def _compact_visual_grounding_evidence(evidence: Any) -> dict[str, Any]:
    if not isinstance(evidence, dict):
        return {}
    return _select_keys(
        evidence,
        (
            "schema",
            "camera_frame",
            "source_observation_id",
            "producer_type",
            "producer_id",
            "image_region",
            "image_bbox",
            "bbox_coordinate_space",
            "reviewability_status",
            "reviewability_reason",
            "grounding_status",
            "locality_status",
            "actionability_status",
            "candidate_state",
            "visual_grounding_pipeline_id",
            "visual_grounding_pipeline_status",
        ),
    )


def _compact_raw_fpv_mcp_observe_state(
    response: dict[str, Any],
    *,
    cleanup_worklist: dict[str, Any] | None = None,
) -> dict[str, Any]:
    raw = response.get("raw_fpv_observation") if isinstance(response, dict) else {}
    raw = raw if isinstance(raw, dict) else {}
    return {
        "schema": "raw_fpv_mcp_observe_state_v1",
        "ok": response.get("ok"),
        "tool": response.get("tool"),
        "status": response.get("status"),
        "contract": response.get("contract"),
        "perception_mode": response.get("perception_mode"),
        "waypoint_id": response.get("waypoint_id") or raw.get("waypoint_id"),
        "current_room_id": response.get("current_room_id") or raw.get("room_id"),
        "held_object_id": response.get("held_object_id") or raw.get("held_object_id"),
        "visible_object_detections": response.get("visible_object_detections") or [],
        "raw_fpv_observation": _compact_raw_fpv_observation(raw),
        "cleanup_worklist_summary": _compact_cleanup_worklist_summary(cleanup_worklist),
        "instruction": response.get("instruction"),
    }


def _compact_raw_fpv_observation(raw: dict[str, Any]) -> dict[str, Any]:
    return {
        "observation_id": raw.get("observation_id"),
        "waypoint_id": raw.get("waypoint_id"),
        "room_id": raw.get("room_id"),
        "held_object_id": raw.get("held_object_id"),
        "perception_mode": raw.get("perception_mode"),
        "structured_detections_available": raw.get("structured_detections_available"),
        "camera_offset": raw.get("camera_offset"),
        "image_artifacts": raw.get("image_artifacts") or {},
        "artifact_status": raw.get("artifact_status"),
        "robot_view_label": raw.get("robot_view_label"),
        "public_contract_note": raw.get("public_contract_note"),
        "camera_control_summary": _compact_camera_control_contract(
            raw.get("camera_control_contract")
        ),
    }


def _compact_camera_control_contract(contract: Any) -> dict[str, Any]:
    if not isinstance(contract, dict):
        return {
            "schema": "robot_view_camera_control_contract_summary_v1",
            "status": "missing_camera_control_contract",
            "same_pose_api": False,
        }
    agent_facing_fpv = contract.get("agent_facing_fpv")
    agent_facing_fpv = agent_facing_fpv if isinstance(agent_facing_fpv, dict) else {}
    return {
        "schema": "robot_view_camera_control_contract_summary_v1",
        "contract_schema": contract.get("schema"),
        "status": contract.get("status"),
        "camera_model": contract.get("camera_model"),
        "same_pose_api": contract.get("same_pose_api") is True,
        "agent_facing_fpv_source": agent_facing_fpv.get("source"),
        "canonical_camera_control": agent_facing_fpv.get("canonical_camera_control") is True,
    }


def _normalize_robot_view_capture_policy(value: str) -> str:
    policy = str(value or ROBOT_VIEW_CAPTURE_POLICY_FULL).strip() or ROBOT_VIEW_CAPTURE_POLICY_FULL
    if policy not in ROBOT_VIEW_CAPTURE_POLICIES:
        allowed = ", ".join(sorted(ROBOT_VIEW_CAPTURE_POLICIES))
        raise ValueError(f"unsupported robot_view_capture_policy '{value}' (expected {allowed})")
    return policy


def _compact_cleanup_worklist_summary(worklist: dict[str, Any] | None) -> dict[str, Any]:
    worklist = worklist if isinstance(worklist, dict) else {}
    objects = [item for item in worklist.get("objects") or [] if isinstance(item, dict)]
    next_actions = _compact_worklist_next_actions(objects)
    return {
        "schema": "cleanup_worklist_summary_v1",
        "object_count": len(objects),
        "handled_object_handles": [
            str(item.get("object_id") or "")
            for item in objects
            if str(item.get("state") or "") in {"placed", "placed_closed", "skipped"}
        ],
        "pending_object_handles": [
            str(item.get("object_id") or "")
            for item in objects
            if str(item.get("state") or "") == "pending"
        ],
        "objects": [_compact_worklist_object(item) for item in objects],
        "next_actions": next_actions,
        "next_action_count": len(next_actions),
        "held_object_id": worklist.get("held_object_id"),
    }


def _compact_worklist_next_actions(objects: list[dict[str, Any]]) -> list[dict[str, Any]]:
    actions = []
    for item in objects:
        state = str(item.get("state") or "")
        object_id = str(item.get("object_id") or "")
        candidate_fixture_id = str(item.get("candidate_fixture_id") or "")
        if (
            state not in {"pending", "navigating_to_object", "held"}
            or not object_id
            or not candidate_fixture_id
            or not bool(item.get("cleanup_recommended"))
        ):
            continue
        recommended_tool = str(item.get("recommended_tool") or "place")
        if state == "held":
            tool_sequence = ["navigate_to_receptacle", recommended_tool]
        elif state == "navigating_to_object":
            tool_sequence = ["pick", "navigate_to_receptacle", recommended_tool]
        else:
            tool_sequence = [
                "navigate_to_object",
                "pick",
                "navigate_to_receptacle",
                recommended_tool,
            ]
        actions.append(
            {
                "object_id": object_id,
                "category": str(item.get("category") or ""),
                "candidate_fixture_id": candidate_fixture_id,
                "recommended_tool": recommended_tool,
                "state": state,
                "tool_sequence": tool_sequence,
                "source": "cleanup_worklist_summary",
            }
        )
    return actions


def _compact_worklist_object(item: dict[str, Any]) -> dict[str, Any]:
    compact = _select_keys(
        item,
        (
            "object_id",
            "state",
            "category",
            "room_id",
            "last_waypoint_id",
            "candidate_fixture_id",
            "candidate_source",
            "actionability_status",
            "cleanup_recommended",
            "recommended_tool",
        ),
    )
    compact["visual_grounding_evidence"] = _compact_visual_grounding_evidence(
        item.get("visual_grounding_evidence")
    )
    return compact


def _select_keys(source: dict[str, Any], keys: tuple[str, ...]) -> dict[str, Any]:
    return {key: source[key] for key in keys if key in source}


def _json_safe(value: Any) -> Any:
    try:
        json.dumps(value)
        return value
    except TypeError:
        if isinstance(value, dict):
            return {str(key): _json_safe(item) for key, item in value.items()}
        if isinstance(value, (list, tuple)):
            return [_json_safe(item) for item in value]
        return str(value)


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(_json_safe(payload), indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def _public_acceptance_config_from_backend(
    base_contract: HouseholdBackendSession | None,
) -> dict[str, int]:
    if base_contract is None:
        return {}
    requested = base_contract.requested_generated_mess_count()
    try:
        requested_run_size = int(requested)
    except (TypeError, ValueError):
        return {}
    if requested_run_size <= 0:
        return {}
    return {"requested_run_size": requested_run_size}
