from __future__ import annotations

from collections.abc import Callable, Collection, Mapping, Sequence
from typing import Any, Protocol

from roboclaws.household import (
    realworld_contract_projection,
    realworld_runtime_map_targets,
    realworld_visual_candidates,
)
from roboclaws.household.realworld_agent_view_contract import (
    nonnegative_int,
    positive_int,
    public_success_threshold,
)
from roboclaws.household.task_intent import (
    HOUSEHOLD_INTENT_MAP_BUILD,
    household_intent_is_open_ended,
    normalize_household_intent,
)
from roboclaws.household.visual_scan_guidance import visual_scan_done_recovery_hint

DONE_READINESS_POLICY_RAW_FPV = "raw_fpv_grounded_cleanup_chains"
DONE_READINESS_POLICY_EXPLICIT = "explicit_grounded_cleanup_chains"


class DoneReadinessContract(Protocol):
    task_intent: str
    perception_mode: str
    public_acceptance_config: Mapping[str, Any]
    sanitize_world_labels: bool
    _fixtures: dict[str, dict[str, Any]]
    _model_declared_observations: Sequence[dict[str, Any]]
    _observed_waypoint_ids: Collection[str]
    _public_waypoints: Sequence[dict[str, Any]]
    _raw_fpv_observations: Sequence[dict[str, Any]]

    def cleanup_worklist_payload(
        self,
        *,
        static_fixture_projection: dict[str, Any] | None = None,
    ) -> dict[str, Any]: ...
    def static_fixture_projection(self) -> dict[str, Any]: ...
    def internal_fixture_id_for_public_reference(self, fixture_id: str | None) -> str | None: ...


_is_place_anchor = realworld_contract_projection._is_place_anchor
_normalize_fixture_category_label = realworld_contract_projection._normalize_fixture_category_label
_public_destination_policy_tool_for_fixture_category = (
    realworld_contract_projection._public_destination_policy_tool_for_fixture_category
)
_recommended_place_tool = realworld_contract_projection._recommended_place_tool
_required_tool_for_candidate_state = realworld_visual_candidates._required_tool_for_candidate_state


def pending_cleanup_candidates(contract: DoneReadinessContract) -> list[dict[str, Any]]:
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


def held_cleanup_candidates(contract: DoneReadinessContract) -> list[dict[str, Any]]:
    return [
        item
        for item in pending_cleanup_candidates(contract)
        if str(item.get("state") or "") == "held"
    ]


def destination_options_for_policy(
    contract: DoneReadinessContract,
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
    contract: DoneReadinessContract,
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
        if required_tool == "adjust_camera":
            recovery_hint = visual_scan_done_recovery_hint()
        else:
            recovery_hint = (
                "Clean pending observed handles before done. For held objects, select a "
                "public destination_options.candidate_fixture_id and call "
                "navigate_to_receptacle -> open? -> place/place_inside. For pending "
                "objects, call navigate_to_object -> pick first. Use "
                "destination_options.recommended_tool when candidate_fixture_id is empty."
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

    if not map_build_task and contract.perception_mode == raw_fpv_only_mode:
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

    grounded_chain_blocker = None
    if not map_build_task:
        grounded_chain_blocker = grounded_cleanup_chain_blocker(
            contract,
            semantic_cleanup_evidence,
            raw_fpv_only_mode=raw_fpv_only_mode,
            assert_no_forbidden_agent_view_keys=assert_no_forbidden_agent_view_keys,
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


def required_model_declared_observations(contract: DoneReadinessContract) -> int:
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


def grounded_cleanup_chain_blocker(
    contract: DoneReadinessContract,
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
    complete_handles = [
        str(item)
        for item in evidence.get("complete_semantic_substep_object_ids") or []
        if str(item)
    ]
    complete_count = positive_int(evidence.get("complete_semantic_substep_objects"))
    if complete_count is None:
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


def grounded_cleanup_chain_requirement(
    contract: DoneReadinessContract,
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


def sweep_coverage(contract: DoneReadinessContract) -> dict[str, Any]:
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


def open_ended_task_intent(contract: DoneReadinessContract) -> bool:
    return household_intent_is_open_ended(contract.task_intent)


def map_build_task_intent(contract: DoneReadinessContract) -> bool:
    return normalize_household_intent(contract.task_intent) == HOUSEHOLD_INTENT_MAP_BUILD
