"""Camera and visual-grounding projection for semantic cleanup timelines."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import Any

from roboclaws.household.semantic_timeline import (
    CLOSE_RECEPTACLE_PHASE,
    NAVIGATE_TO_OBJECT_PHASE,
    NAVIGATE_TO_RECEPTACLE_PHASE,
    NAVIGATE_TO_VISUAL_CANDIDATE_TOOL,
    OPEN_RECEPTACLE_PHASE,
    PICK_PHASE,
    PLACE_CLEANUP_PHASES,
    _identity_optional_str,
    annotate_focus_visual_grounding,
    label_suffix,
    optional_str,
    relative_view_paths,
    response_or_request_id,
)


def record_robot_view_step(
    *,
    steps: list[dict[str, Any]],
    backend: Any,
    output_dir: Path,
    index: int,
    action: str,
    label_suffix: str,
    focus_object_id: str | None = None,
    focus_receptacle_id: str | None = None,
    semantic_phase: str | None = None,
    action_evidence: dict[str, Any] | None = None,
    camera_yaw_offset_deg: float = 0.0,
    camera_pitch_offset_deg: float = 0.0,
) -> int:
    writer = getattr(backend, "write_robot_views", None)
    if not callable(writer):
        raise RuntimeError("robot view capture requires backend.write_robot_views")
    label = f"{index:04d}_{label_suffix}"
    result = writer(
        output_dir / "robot_views",
        label=label,
        focus_object_id=focus_object_id,
        focus_receptacle_id=focus_receptacle_id,
        camera_yaw_offset_deg=camera_yaw_offset_deg,
        camera_pitch_offset_deg=camera_pitch_offset_deg,
    )
    if not result.get("ok"):
        raise RuntimeError(f"robot view capture failed: {result}")
    step = {
        "label": label,
        "action": action,
        "robot_pose": result.get("robot_pose"),
        "robot_trajectory_count": len(result.get("robot_trajectory", [])),
        "view_variant": result.get("view_variant"),
        "view_provenance": result.get("view_provenance"),
        "camera_control_contract": result.get("camera_control_contract"),
        "focus": annotate_focus_visual_grounding(result.get("focus")),
        "semantic_phase": semantic_phase,
        "room_outline_count": result.get("room_outline_count"),
        "views": relative_view_paths(output_dir, result["views"]),
    }
    if action_evidence:
        step["action_evidence"] = action_evidence
    steps.append(step)
    return index + 1


def camera_offsets_from_raw_fpv_observation(raw: dict[str, Any]) -> dict[str, float]:
    offset = raw.get("camera_offset")
    if not isinstance(offset, dict):
        offset = {}
    return {
        "camera_yaw_offset_deg": _float_or_zero(offset.get("yaw_delta_deg")),
        "camera_pitch_offset_deg": _float_or_zero(offset.get("pitch_delta_deg")),
    }


def _float_or_zero(value: Any) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


def robot_view_camera_control_summary(steps: list[dict[str, Any]]) -> dict[str, Any]:
    contracts = [
        step.get("camera_control_contract")
        for step in steps
        if isinstance(step.get("camera_control_contract"), dict)
    ]
    if not contracts:
        return {
            "schema": "robot_view_camera_control_summary_v1",
            "status": "missing_camera_control_contract",
            "same_pose_api": False,
            "step_count": len(steps),
            "contract_count": 0,
        }
    canonical_count = sum(1 for item in contracts if item.get("same_pose_api") is True)
    head_camera_count = sum(
        1
        for item in contracts
        if item.get("camera_model")
        in {"robot_mounted_head_camera_v1", "robot_head_camera_equivalent_v1"}
    )
    if head_camera_count == len(contracts):
        status = "all_robot_views_use_head_camera_fpv"
    elif canonical_count == len(contracts):
        status = "all_robot_views_use_canonical_camera_control"
    else:
        status = "mixed_or_backend_local_robot_views"
    return {
        "schema": "robot_view_camera_control_summary_v1",
        "status": status,
        "same_pose_api": canonical_count == len(contracts),
        "head_camera_fpv": head_camera_count == len(contracts),
        "step_count": len(steps),
        "contract_count": len(contracts),
        "canonical_contract_count": canonical_count,
        "head_camera_contract_count": head_camera_count,
        "backend_local_contract_count": len(contracts) - canonical_count,
    }


def robot_view_capture_for_tool(
    tool: str,
    request: dict[str, Any],
    response: dict[str, Any],
    *,
    object_id_transform: Callable[[str | None], str | None] | None = None,
) -> dict[str, Any] | None:
    transform_object_id = object_id_transform or _identity_optional_str
    if tool == "observe":
        raw = response.get("raw_fpv_observation") if isinstance(response, dict) else {}
        raw = raw if isinstance(raw, dict) else {}
        return {
            "action": "observe",
            "label_suffix": "observe",
            "focus_object_id": None,
            "focus_receptacle_id": None,
            "semantic_phase": None,
            **camera_offsets_from_raw_fpv_observation(raw),
        }
    if tool == "scene_objects":
        return {
            "action": "scene_objects",
            "label_suffix": "scene_objects",
            "focus_object_id": None,
            "focus_receptacle_id": None,
            "semantic_phase": None,
        }
    if tool == NAVIGATE_TO_VISUAL_CANDIDATE_TOOL:
        object_id = optional_str(response.get("object_id") or request.get("object_id"))
        return {
            "action": f"navigate_to_visual_candidate {object_id}",
            "label_suffix": label_suffix("navigate_visual_candidate", object_id),
            "focus_object_id": transform_object_id(object_id),
            "focus_receptacle_id": optional_str(
                response.get("source_receptacle_id") or response.get("location_id")
            ),
            "semantic_phase": NAVIGATE_TO_OBJECT_PHASE,
            "action_evidence": visual_candidate_action_evidence(tool, request, response),
        }
    if tool == NAVIGATE_TO_OBJECT_PHASE:
        object_id = optional_str(response.get("object_id") or request.get("object_id"))
        return {
            "action": f"navigate_to_object {object_id}",
            "label_suffix": label_suffix("navigate_object", object_id),
            "focus_object_id": transform_object_id(object_id),
            "focus_receptacle_id": optional_str(
                response.get("source_receptacle_id") or response.get("location_id")
            ),
            "semantic_phase": NAVIGATE_TO_OBJECT_PHASE,
            "action_evidence": object_navigation_action_evidence(tool, request, response),
        }
    if tool == PICK_PHASE:
        object_id = optional_str(response.get("object_id") or request.get("object_id"))
        return {
            "action": f"pick {object_id}",
            "label_suffix": label_suffix("pick", object_id),
            "focus_object_id": transform_object_id(object_id),
            "focus_receptacle_id": optional_str(
                response.get("previous_location_id") or response.get("source_receptacle_id")
            ),
            "semantic_phase": PICK_PHASE,
        }
    if tool == NAVIGATE_TO_RECEPTACLE_PHASE:
        object_id = optional_str(response.get("object_id"))
        receptacle_id = response_or_request_id(response, request, "receptacle_id", "fixture_id")
        return {
            "action": f"navigate_to_receptacle {receptacle_id}",
            "label_suffix": label_suffix("navigate_receptacle", receptacle_id),
            "focus_object_id": transform_object_id(object_id),
            "focus_receptacle_id": receptacle_id,
            "semantic_phase": NAVIGATE_TO_RECEPTACLE_PHASE,
        }
    if tool == OPEN_RECEPTACLE_PHASE:
        object_id = optional_str(response.get("object_id"))
        receptacle_id = response_or_request_id(response, request, "receptacle_id", "fixture_id")
        return {
            "action": f"open_receptacle {receptacle_id}",
            "label_suffix": label_suffix("open_receptacle", receptacle_id),
            "focus_object_id": transform_object_id(object_id),
            "focus_receptacle_id": receptacle_id,
            "semantic_phase": OPEN_RECEPTACLE_PHASE,
        }
    if tool == CLOSE_RECEPTACLE_PHASE:
        object_id = optional_str(response.get("object_id") or request.get("object_id"))
        receptacle_id = response_or_request_id(response, request, "receptacle_id", "fixture_id")
        return {
            "action": f"close_receptacle {receptacle_id}",
            "label_suffix": label_suffix("close_receptacle", receptacle_id),
            "focus_object_id": transform_object_id(object_id),
            "focus_receptacle_id": receptacle_id,
            "semantic_phase": CLOSE_RECEPTACLE_PHASE,
        }
    if tool in PLACE_CLEANUP_PHASES:
        object_id = optional_str(response.get("object_id"))
        receptacle_id = response_or_request_id(response, request, "receptacle_id", "fixture_id")
        return {
            "action": f"{tool} {object_id}",
            "label_suffix": label_suffix(tool, object_id),
            "focus_object_id": transform_object_id(object_id),
            "focus_receptacle_id": receptacle_id,
            "semantic_phase": tool,
        }
    return None


def visual_candidate_action_evidence(
    tool: str,
    request: dict[str, Any],
    response: dict[str, Any],
) -> dict[str, Any]:
    observation = response.get("model_declared_observation")
    if not isinstance(observation, dict):
        observation = {}
    evidence = visual_grounding_evidence_from_response(response, observation)
    source_observation_id = optional_str(
        evidence.get("source_observation_id")
        or observation.get("source_observation_id")
        or request.get("source_observation_id")
    )
    image_bbox = image_bbox_from_visual_grounding(evidence, observation)
    return _drop_empty_action_evidence(
        {
            "schema": "robot_timeline_action_evidence_v1",
            "agent_tool": tool,
            "agent_action": f"{tool} {optional_str(response.get('object_id'))}",
            "backend_primitive": NAVIGATE_TO_OBJECT_PHASE,
            "resolved_object_id": optional_str(response.get("object_id")),
            "source_observation_id": source_observation_id,
            "source_image_bbox": image_bbox,
            "bbox_coordinate_space": evidence.get("bbox_coordinate_space"),
            "camera_frame": evidence.get("camera_frame"),
            "reviewability_status": evidence.get("reviewability_status"),
            "reviewability_reason": evidence.get("reviewability_reason"),
            "locality_status": evidence.get("locality_status"),
            "candidate_state": observation.get("candidate_state")
            or evidence.get("candidate_state"),
            "actionability_status": observation.get("actionability_status")
            or evidence.get("actionability_status"),
            "grounding_status": observation.get("grounding_status")
            or evidence.get("grounding_status"),
            "grounding_confidence": observation.get("grounding_confidence"),
            "grounding_basis": observation.get("grounding_basis"),
            "declared_category": observation.get("category") or request.get("category"),
            "evidence_note": observation.get("evidence_note") or request.get("evidence_note"),
            "target_fixture_id": observation.get("target_fixture_id")
            or request.get("target_fixture_id"),
            "source_fixture_id": observation.get("source_fixture_id")
            or request.get("source_fixture_id"),
        }
    )


def object_navigation_action_evidence(
    tool: str,
    request: dict[str, Any],
    response: dict[str, Any],
) -> dict[str, Any]:
    object_id = optional_str(response.get("object_id") or request.get("object_id"))
    evidence = visual_grounding_evidence_from_response(response)
    source_observation_id = optional_str(
        evidence.get("source_observation_id") or response.get("source_observation_id")
    )
    return _drop_empty_action_evidence(
        {
            "schema": "robot_timeline_action_evidence_v1",
            "agent_tool": tool,
            "agent_action": f"{tool} {object_id}",
            "backend_primitive": NAVIGATE_TO_OBJECT_PHASE,
            "resolved_object_id": object_id,
            "source_observation_id": source_observation_id,
            "source_image_bbox": image_bbox_from_visual_grounding(evidence),
            "bbox_coordinate_space": evidence.get("bbox_coordinate_space"),
            "camera_frame": evidence.get("camera_frame"),
            "reviewability_status": evidence.get("reviewability_status"),
            "reviewability_reason": evidence.get("reviewability_reason"),
            "locality_status": evidence.get("locality_status"),
            "candidate_state": response.get("candidate_state") or evidence.get("candidate_state"),
            "actionability_status": response.get("actionability_status")
            or evidence.get("actionability_status"),
            "grounding_status": evidence.get("grounding_status"),
        }
    )


def visual_grounding_evidence_from_response(
    response: dict[str, Any],
    observation: dict[str, Any] | None = None,
) -> dict[str, Any]:
    evidence = response.get("visual_grounding_evidence")
    if not isinstance(evidence, dict) and observation:
        evidence = observation.get("visual_grounding_evidence")
    return evidence if isinstance(evidence, dict) else {}


def image_bbox_from_visual_grounding(
    evidence: dict[str, Any],
    observation: dict[str, Any] | None = None,
) -> Any:
    image_bbox = evidence.get("image_bbox")
    if image_bbox is not None:
        return image_bbox
    image_region = evidence.get("image_region")
    if not isinstance(image_region, dict) and observation:
        image_region = observation.get("image_region")
    if isinstance(image_region, dict):
        return image_region.get("value")
    return None


def _drop_empty_action_evidence(evidence: dict[str, Any]) -> dict[str, Any]:
    return {
        key: value
        for key, value in evidence.items()
        if value is not None and value != "" and value != []
    }
