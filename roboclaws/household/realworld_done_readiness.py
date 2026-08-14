from __future__ import annotations

import math
from collections.abc import Callable, Mapping, Sequence
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from roboclaws.household.household_runtime_contract import HouseholdRuntimeContract

from roboclaws.core.map_build_scan_profile import map_build_scan_profile
from roboclaws.core.task_intents import (
    HOUSEHOLD_INTENT_CLEANUP,
    HOUSEHOLD_INTENT_MAP_BUILD,
    household_intent_is_open_ended,
    normalize_household_intent,
)
from roboclaws.household import (
    realworld_runtime_map_targets,
    realworld_visual_candidates,
)
from roboclaws.household.realworld_agent_view_contract import (
    nonnegative_int,
    positive_int,
    public_success_threshold,
)
from roboclaws.household.realworld_contract_fixture_projection import (
    _is_place_anchor,
    _normalize_fixture_category_label,
    _public_destination_policy_tool_for_fixture_category,
    _recommended_place_tool,
)
from roboclaws.household.semantic_acceptability import public_source_requires_cleanup
from roboclaws.household.visual_scan_guidance import visual_scan_done_recovery_hint

DONE_READINESS_POLICY_RAW_FPV = "raw_fpv_grounded_cleanup_chains"
DONE_READINESS_POLICY_EXPLICIT = "explicit_grounded_cleanup_chains"


_required_tool_for_candidate_state = realworld_visual_candidates._required_tool_for_candidate_state


def pending_cleanup_candidates(contract: HouseholdRuntimeContract) -> list[dict[str, Any]]:
    worklist = contract.cleanup_worklist_payload(
        static_fixture_projection=contract.static_fixture_projection()
    )
    pending = []
    for item in worklist.get("objects", []):
        state = str(item.get("state") or "")
        if state not in {"pending", "held"}:
            continue
        if item.get("grounding_status") in {"ambiguous", "unresolved"}:
            continue
        if contract.sanitize_world_labels:
            if state != "held" and not _public_source_requires_cleanup(contract, item):
                continue
            destination_options = destination_options_for_policy(
                contract,
                item.get("destination_policy") or {},
            )
            candidate_state = str(item.get("candidate_state") or "")
            if state != "held" and not destination_options:
                continue
            pending.append(
                {
                    "object_id": str(item.get("object_id") or ""),
                    "category": str(item.get("category") or ""),
                    "state": state,
                    "source_fixture_id": str(item.get("source_fixture_id") or ""),
                    "candidate_fixture_id": "",
                    "candidate_state": candidate_state,
                    "destination_policy_status": str(
                        item.get("destination_policy_status") or "policy_required"
                    ),
                    "destination_policy": dict(item.get("destination_policy") or {}),
                    "destination_options": destination_options,
                    "required_tool": "navigate_to_receptacle"
                    if state == "held"
                    else _required_tool_for_candidate_state(str(item.get("candidate_state") or "")),
                }
            )
            continue
        candidate_fixture_id = str(item.get("candidate_fixture_id") or "")
        source_fixture_id = str(item.get("source_fixture_id") or "")
        if state != "held" and item.get("cleanup_recommended") is not True:
            continue
        if not candidate_fixture_id or candidate_fixture_id == source_fixture_id:
            continue
        internal_candidate_fixture_id = (
            contract.internal_fixture_id_for_public_reference(candidate_fixture_id)
            or candidate_fixture_id
        )
        pending.append(
            {
                "object_id": str(item.get("object_id") or ""),
                "category": str(item.get("category") or ""),
                "state": state,
                "source_fixture_id": source_fixture_id,
                "candidate_fixture_id": candidate_fixture_id,
                "candidate_state": str(item.get("candidate_state") or ""),
                "required_tool": "navigate_to_receptacle"
                if state == "held"
                else _required_tool_for_candidate_state(str(item.get("candidate_state") or "")),
                "recommended_tool": _recommended_place_tool(
                    internal_candidate_fixture_id,
                    contract._fixtures,
                ),
            }
        )
    return pending


def _public_source_requires_cleanup(
    contract: HouseholdRuntimeContract,
    item: Mapping[str, Any],
) -> bool:
    source_fixture_id = str(item.get("source_fixture_id") or "")
    internal_source_fixture_id = (
        contract.internal_fixture_id_for_public_reference(source_fixture_id) or source_fixture_id
    )
    source_fixture = contract._fixtures.get(internal_source_fixture_id) or {}
    return public_source_requires_cleanup(
        item.get("category"),
        source_fixture.get("category") or source_fixture.get("name"),
    )


def held_cleanup_candidates(contract: HouseholdRuntimeContract) -> list[dict[str, Any]]:
    return [
        item
        for item in pending_cleanup_candidates(contract)
        if str(item.get("state") or "") == "held"
    ]


def destination_options_for_policy(
    contract: HouseholdRuntimeContract,
    policy: dict[str, Any],
) -> list[dict[str, Any]]:
    preferred = [
        _normalize_fixture_category_label(item)
        for item in policy.get("preferred_fixture_categories") or []
    ]
    if not preferred:
        return []
    options = []
    for anchor in realworld_runtime_map_targets.runtime_public_semantic_anchors(contract):
        if not _is_place_anchor(anchor):
            continue
        category = _normalize_fixture_category_label(anchor.get("category"))
        if category not in preferred:
            continue
        anchor_id = str(anchor.get("anchor_id") or "")
        if not anchor_id:
            continue
        tool_by_category = dict(policy.get("placement_tool_by_fixture_category") or {})
        recommended_tool = str(
            tool_by_category.get(category)
            or policy.get("placement_tool")
            or _public_destination_policy_tool_for_fixture_category(category)
        )
        options.append(
            {
                "candidate_fixture_id": anchor_id,
                "candidate_fixture_category": category,
                "recommended_tool": recommended_tool,
                "candidate_source": "runtime_public_semantic_anchor",
                "waypoint_id": str(anchor.get("waypoint_id") or ""),
            }
        )
    return options


def evaluate_done_readiness(
    contract: HouseholdRuntimeContract,
    *,
    semantic_cleanup_evidence: dict[str, Any] | None = None,
    schema: str,
    raw_fpv_only_mode: str,
    assert_no_forbidden_agent_view_keys: Callable[[Any], None],
) -> dict[str, Any]:
    blockers: list[dict[str, Any]] = []
    open_ended_task = open_ended_task_intent(contract)
    map_build_task = map_build_task_intent(contract)
    pending = []
    if not map_build_task:
        pending = (
            held_cleanup_candidates(contract)
            if open_ended_task
            else pending_cleanup_candidates(contract)
        )
    if pending:
        required_tool = str(pending[0].get("required_tool") or "navigate_to_object")
        if any(str(item.get("state") or "") == "held" for item in pending):
            required_tool = "navigate_to_receptacle"
        recovery_hint = pending_cleanup_recovery_hint(
            pending,
            required_tool=required_tool,
            visual_scan_hint=(
                visual_scan_done_recovery_hint() if required_tool == "adjust_camera" else ""
            ),
        )
        blockers.append(
            {
                "type": "pending_cleanup_candidates",
                "required_tool": required_tool,
                "pending_observed_handles": [str(item["object_id"]) for item in pending],
                "pending_cleanup_candidates": pending,
                "recovery_hint": recovery_hint,
            }
        )

    coverage = sweep_coverage(contract)
    if not open_ended_task and coverage["unvisited_waypoint_ids"]:
        next_waypoint_id = coverage["unvisited_waypoint_ids"][0]
        blockers.append(
            {
                "type": "insufficient_sweep_coverage",
                "required_tool": "navigate_to_waypoint",
                "next_waypoint_id": next_waypoint_id,
                "sweep_coverage_rate": coverage["sweep_coverage_rate"],
                "observed_waypoint_count": coverage["observed_waypoint_count"],
                "total_waypoints": coverage["total_waypoints"],
                "unvisited_waypoint_ids": coverage["unvisited_waypoint_ids"],
                "recovery_hint": (
                    "Continue the public sweep before done: call navigate_to_waypoint("
                    f"{next_waypoint_id}) and observe. Do not use done as a system "
                    "assessment while static-map inspection waypoints remain unvisited."
                ),
            }
        )

    grounded_chain_blocker = None
    if not map_build_task:
        grounded_chain_blocker = grounded_cleanup_chain_blocker(
            contract,
            semantic_cleanup_evidence,
            raw_fpv_only_mode=raw_fpv_only_mode,
            assert_no_forbidden_agent_view_keys=assert_no_forbidden_agent_view_keys,
        )
    if not open_ended_task and not map_build_task and contract.perception_mode == raw_fpv_only_mode:
        blockers.extend(
            raw_fpv_cleanup_readiness_blockers(
                contract,
                require_overlap_probe=grounded_chain_blocker is not None,
            )
        )
    if grounded_chain_blocker is not None:
        blockers.append(grounded_chain_blocker)

    readiness = {
        "schema": schema,
        "status": "blocked" if blockers else "ready",
        "blockers": blockers,
        "policy_uses_private_truth": False,
        "task_intent": contract.task_intent,
        "public_contract_note": (
            "Done readiness is evaluated from public Agent View state, public tool "
            "trace evidence, and public run acceptance configuration. It does not "
            "use private generated mess membership, hidden destinations, or scorer truth."
        ),
    }
    assert_no_forbidden_agent_view_keys(readiness)
    return readiness


def attach_completion_readiness_hint(
    server: Any,
    tool: str,
    response: dict[str, Any],
) -> dict[str, Any]:
    if (
        tool != "observe"
        or not response.get("ok")
        or server.task_intent != HOUSEHOLD_INTENT_CLEANUP
        or server.perception_mode != "visible_object_detections"
        or response.get("operator_message_pending")
    ):
        return response
    readiness = server.contract.evaluate_done_readiness(
        semantic_cleanup_evidence=server.done_readiness_evidence(),
    )
    if readiness.get("status") != "ready":
        return response
    augmented = dict(response)
    augmented["required_next_tool"] = "done"
    augmented["completion"] = {
        "schema": readiness.get("schema", "done_readiness_v1"),
        "status": "ready",
        "policy_uses_private_truth": False,
    }
    augmented["instruction"] = (
        "MCP-visible cleanup readiness is ready. Call done now before inspecting another "
        "object or waypoint; only done producing run_result.json completes the run."
    )
    return augmented


def pending_cleanup_recovery_hint(
    pending: Sequence[dict[str, Any]],
    *,
    required_tool: str,
    visual_scan_hint: str = "",
) -> str:
    handles = [str(item.get("object_id") or "") for item in pending if item.get("object_id")]
    first_handle = handles[0] if handles else "the first returned handle"
    ordered_handles = ", ".join(handles)
    prefix = f"{visual_scan_hint.rstrip()} " if visual_scan_hint else ""
    return (
        prefix + "Treat the authoritative pending_cleanup_candidates list as the bounded cleanup "
        f"worklist: [{ordered_handles}]. Start with {first_handle} using its returned "
        f"required_tool={required_tool}, then follow that candidate's destination_options and "
        "recommended_tool. Do not inspect unrelated handles or expand the waypoint sweep while "
        "a listed candidate remains actionable. Visit a generated inspection waypoint only when "
        "that same candidate explicitly returns its generated_inspection_waypoint_id. After a "
        "successful placement or a public terminal rejection, continue with the next returned "
        "handle; call done again only after this bounded list is exhausted."
    )


def done_readiness_blocked_response(
    readiness: dict[str, Any],
    *,
    schema: str,
    error_builder: Callable[..., dict[str, Any]],
) -> dict[str, Any]:
    blockers = [dict(item) for item in readiness.get("blockers") or []]
    first = blockers[0] if blockers else {"type": "done_readiness_blocked"}
    error_reason = str(first.get("type") or "done_readiness_blocked")
    payload = {key: value for key, value in first.items() if key not in {"type", "recovery_hint"}}
    if "recovery_hint" in first:
        payload["recovery_hint"] = first["recovery_hint"]
    payload["completion"] = {
        "schema": readiness.get("schema", schema),
        "status": "blocked",
        "blockers": blockers,
        "policy_uses_private_truth": False,
    }
    return error_builder("done", error_reason, status="blocked", **payload)


def required_model_declared_observations(contract: HouseholdRuntimeContract) -> int:
    if open_ended_task_intent(contract):
        return 0
    configured = positive_int(
        contract.public_acceptance_config.get("required_model_declared_observations")
    )
    if configured is not None:
        return configured
    requested = positive_int(contract.public_acceptance_config.get("requested_run_size"))
    if requested is not None:
        return min(7, requested)
    return 0


def raw_fpv_cleanup_readiness_blockers(
    contract: HouseholdRuntimeContract,
    *,
    require_overlap_probe: bool = False,
) -> list[dict[str, Any]]:
    blockers: list[dict[str, Any]] = []
    heading_coverage_blocker = raw_fpv_heading_coverage_blocker(contract)
    if heading_coverage_blocker is not None:
        blockers.append(heading_coverage_blocker)
    elif require_overlap_probe:
        overlap_probe_blocker = raw_fpv_overlap_probe_blocker(contract)
        if overlap_probe_blocker is not None:
            blockers.append(overlap_probe_blocker)
    required_declaration_count = required_model_declared_observations(contract)
    declaration_count = len(contract._model_declared_observations)
    if declaration_count < required_declaration_count:
        blockers.append(
            {
                "type": "insufficient_model_declared_observations",
                "required_tool": "navigate_to_visual_candidate",
                "current": declaration_count,
                "required": required_declaration_count,
                "model_declared_observations": declaration_count,
                "raw_fpv_observations": len(contract._raw_fpv_observations),
                "required_model_declared_observations": required_declaration_count,
                "recovery_hint": (
                    "Continue sweeping public waypoints and use "
                    "navigate_to_visual_candidate for plausible cleanup objects "
                    "seen in raw FPV images before calling done."
                ),
            }
        )
    return blockers


def raw_fpv_overlap_probe_blocker(
    contract: HouseholdRuntimeContract,
) -> dict[str, Any] | None:
    recommended_waypoint_ids = {
        str(declaration.get("waypoint_id") or "")
        for declaration in contract._model_declared_observations
        if bool(
            (contract._detections_by_handle.get(str(declaration.get("object_id") or "")) or {}).get(
                "cleanup_recommended"
            )
        )
    }
    candidate_free_waypoint_ids = [
        str(waypoint.get("waypoint_id") or "")
        for waypoint in contract._public_waypoints
        if str(waypoint.get("waypoint_id") or "") not in recommended_waypoint_ids
    ]
    probed_waypoint_ids = {
        str(observation.get("waypoint_id") or "")
        for observation in contract._raw_fpv_observations
        if _is_bounded_overlap_probe(observation)
    }
    incomplete = [
        waypoint_id
        for waypoint_id in candidate_free_waypoint_ids
        if waypoint_id not in probed_waypoint_ids
    ]
    if not incomplete:
        return None
    next_waypoint_id = incomplete[0]
    return {
        "type": "insufficient_raw_fpv_overlap_probe_coverage",
        "policy_id": "candidate_free_bounded_overlap_probe_v1",
        "required_tool": "navigate_to_waypoint",
        "followup_tool": "adjust_camera",
        "next_waypoint_id": next_waypoint_id,
        "required_camera_adjustment": {
            "yaw_delta_deg": 45,
            "pitch_delta_deg": 20,
        },
        "candidate_free_waypoint_ids": candidate_free_waypoint_ids,
        "probed_candidate_free_waypoint_ids": [
            waypoint_id
            for waypoint_id in candidate_free_waypoint_ids
            if waypoint_id in probed_waypoint_ids
        ],
        "incomplete_waypoint_ids": incomplete,
        "recovery_hint": (
            f"Return to public waypoint {next_waypoint_id}, call "
            "adjust_camera(yaw_delta_deg=45, pitch_delta_deg=20) exactly once, then "
            "observe. This bounded diagonal overlap probe checks horizontal and vertical "
            "FPV edges without using private target truth. Inspect only the fresh image and "
            "use only its new reviewable bbox; do not repeat the probe at that waypoint."
        ),
    }


def _is_bounded_overlap_probe(observation: dict[str, Any]) -> bool:
    offset = observation.get("camera_offset")
    if not isinstance(offset, dict):
        return False
    try:
        yaw = float(offset.get("yaw_delta_deg") or 0.0)
        pitch = float(offset.get("pitch_delta_deg") or 0.0)
    except (TypeError, ValueError):
        return False
    return math.isclose(abs(yaw), 45.0, abs_tol=1e-6) and math.isclose(
        abs(pitch),
        20.0,
        abs_tol=1e-6,
    )


def grounded_cleanup_chain_blocker(
    contract: HouseholdRuntimeContract,
    semantic_cleanup_evidence: dict[str, Any] | None,
    *,
    raw_fpv_only_mode: str,
    assert_no_forbidden_agent_view_keys: Callable[[Any], None],
) -> dict[str, Any] | None:
    required_count, policy_id = grounded_cleanup_chain_requirement(
        contract,
        raw_fpv_only_mode=raw_fpv_only_mode,
    )
    if required_count <= 0:
        return None
    evidence = semantic_cleanup_evidence or {}
    traced_complete_handles = [
        str(item)
        for item in evidence.get("complete_semantic_substep_object_ids") or []
        if str(item)
    ]
    complete_handles = [
        handle
        for handle in traced_complete_handles
        if bool((contract._detections_by_handle.get(handle) or {}).get("cleanup_recommended"))
    ]
    complete_count = len(complete_handles)
    if complete_count >= required_count:
        return None
    required_tool = grounded_cleanup_chain_required_tool(
        contract.perception_mode,
        raw_fpv_only_mode=raw_fpv_only_mode,
    )
    blocker = {
        "type": "insufficient_grounded_cleanup_chains",
        "policy_id": policy_id,
        "current": complete_count,
        "required": required_count,
        "required_tool": required_tool,
        "complete_semantic_substep_objects": complete_count,
        "complete_semantic_substep_object_ids": complete_handles,
        "required_complete_semantic_substep_objects": required_count,
        "semantic_substep_count": nonnegative_int(evidence.get("semantic_substep_count")),
        "recovery_hint": grounded_cleanup_chain_recovery_hint(required_tool),
    }
    assert_no_forbidden_agent_view_keys(blocker)
    return blocker


def raw_fpv_heading_coverage_blocker(contract: HouseholdRuntimeContract) -> dict[str, Any] | None:
    profile = map_build_scan_profile()
    required_count = min(4, max(1, profile.observe_count_per_waypoint))
    heading_buckets = _raw_fpv_heading_buckets_by_waypoint(
        contract._raw_fpv_observations,
        turn_degrees=abs(float(profile.body_turn_yaw_delta_deg or 90.0)),
    )
    waypoint_ids = [str(item.get("waypoint_id") or "") for item in contract._public_waypoints]
    counts = {
        waypoint_id: len(heading_buckets.get(waypoint_id, set())) for waypoint_id in waypoint_ids
    }
    incomplete = [
        waypoint_id for waypoint_id in waypoint_ids if counts[waypoint_id] < required_count
    ]
    if not incomplete:
        return None
    next_waypoint_id = incomplete[0]
    return {
        "type": "insufficient_raw_fpv_heading_coverage",
        "policy_id": profile.profile_id,
        "required_tool": "navigate_to_waypoint",
        "next_waypoint_id": next_waypoint_id,
        "required_distinct_heading_count": required_count,
        "current_distinct_heading_count": counts[next_waypoint_id],
        "distinct_heading_counts_by_waypoint": counts,
        "incomplete_waypoint_ids": incomplete,
        "recovery_hint": (
            f"Return to {next_waypoint_id}, observe from its canonical inspection pose, then "
            f"use navigate_to_relative_pose with yaw_delta_deg={profile.body_turn_yaw_delta_deg:g} "
            "and observe until the required distinct body headings are covered. Repeated "
            "observations at the same body heading do not add coverage."
        ),
    }


def _raw_fpv_heading_buckets_by_waypoint(
    observations: Sequence[dict[str, Any]],
    *,
    turn_degrees: float,
) -> dict[str, set[int]]:
    headings_by_waypoint: dict[str, list[float]] = {}
    for observation in observations:
        waypoint_id = str(observation.get("waypoint_id") or "")
        heading = _raw_fpv_body_heading_degrees(observation)
        if waypoint_id and heading is not None:
            headings_by_waypoint.setdefault(waypoint_id, []).append(heading)

    buckets_by_waypoint: dict[str, set[int]] = {}
    for waypoint_id, headings in headings_by_waypoint.items():
        origin = headings[0]
        buckets_by_waypoint[waypoint_id] = {
            int(math.floor((((heading - origin) % 360.0) + turn_degrees / 2.0) / turn_degrees))
            % max(1, round(360.0 / turn_degrees))
            for heading in headings
        }
    return buckets_by_waypoint


def _raw_fpv_body_heading_degrees(observation: dict[str, Any]) -> float | None:
    camera_contract = observation.get("camera_control_contract")
    camera_contract = camera_contract if isinstance(camera_contract, dict) else {}
    robot_pose = camera_contract.get("robot_pose")
    robot_pose = robot_pose if isinstance(robot_pose, dict) else {}
    pose_source = str(robot_pose.get("pose_source") or "")
    if pose_source and pose_source not in {
        "waypoint_room_outline_projection",
        "relative_robot_frame",
    }:
        return None
    try:
        theta = float(robot_pose["theta"])
    except (KeyError, TypeError, ValueError):
        return None
    return math.degrees(theta) % 360.0


def grounded_cleanup_chain_requirement(
    contract: HouseholdRuntimeContract,
    *,
    raw_fpv_only_mode: str,
) -> tuple[int, str]:
    if open_ended_task_intent(contract):
        return 0, ""
    explicit_count = positive_int(
        contract.public_acceptance_config.get("required_grounded_cleanup_chains")
    )
    if explicit_count is not None:
        return explicit_count, str(
            contract.public_acceptance_config.get("done_readiness_policy")
            or DONE_READINESS_POLICY_EXPLICIT
        )
    if contract.perception_mode != raw_fpv_only_mode:
        return 0, ""
    requested = positive_int(contract.public_acceptance_config.get("requested_run_size"))
    if requested is None:
        return 0, ""
    return public_success_threshold(requested), DONE_READINESS_POLICY_RAW_FPV


def grounded_cleanup_chain_required_tool(
    perception_mode: str,
    *,
    raw_fpv_only_mode: str,
) -> str:
    if perception_mode == raw_fpv_only_mode:
        return "navigate_to_visual_candidate"
    return "navigate_to_object"


def grounded_cleanup_chain_recovery_hint(required_tool: str) -> str:
    if required_tool == "navigate_to_visual_candidate":
        return (
            "Continue the cleanup loop before done. For each plausible object in a "
            "public observation, call navigate_to_visual_candidate when required; "
            "when it returns ok=true, call pick, navigate_to_receptacle with the "
            "public candidate fixture, then the recommended placement tool. Call "
            "done only after enough grounded cleanup chains have completed."
        )
    return (
        "Continue the cleanup loop before done. For each pending public observed "
        "handle, call navigate_to_object, pick, navigate_to_receptacle with a public "
        "candidate fixture, then the recommended placement tool. Call done only after "
        "enough grounded cleanup chains have completed."
    )


def sweep_coverage(contract: HouseholdRuntimeContract) -> dict[str, Any]:
    waypoints = contract._public_waypoints
    total_waypoints = len(waypoints)
    unvisited = [
        str(item["waypoint_id"])
        for item in waypoints
        if str(item["waypoint_id"]) not in contract._observed_waypoint_ids
    ]
    observed_count = total_waypoints - len(unvisited)
    rate = observed_count / total_waypoints if total_waypoints else 1.0
    return {
        "sweep_coverage_rate": round(rate, 6),
        "observed_waypoint_count": observed_count,
        "total_waypoints": total_waypoints,
        "unvisited_waypoint_ids": unvisited,
    }


def open_ended_task_intent(contract: HouseholdRuntimeContract) -> bool:
    return household_intent_is_open_ended(contract.task_intent)


def map_build_task_intent(contract: HouseholdRuntimeContract) -> bool:
    return normalize_household_intent(contract.task_intent) == HOUSEHOLD_INTENT_MAP_BUILD
