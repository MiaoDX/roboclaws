#!/usr/bin/env python3
from __future__ import annotations

import time
from pathlib import Path
from typing import Any

from roboclaws.household import realworld_visual_candidate_declarations
from roboclaws.household.household_backend_contract import (
    HouseholdBackendSession,
)
from roboclaws.household.household_direct_cleanup_selection import (
    VisibleObjectCandidate,
    direct_policy_target_fixture,
    redirect_if_already_on_inferred_fixture,
    visible_object_candidate,
)
from roboclaws.household.household_runtime_contract import (
    CAMERA_MODEL_POLICY_MODE,
    CAMERA_MODEL_POLICY_NAME,
    MAIN_CLEANUP_AGENT_PRODUCER,
    RAW_FPV_ONLY_MODE,
    REALWORLD_CONTRACT,
    SIMULATED_CAMERA_MODEL_PROVENANCE,
    HouseholdRuntimeContract,
)
from roboclaws.household.planner_primitive_executor import (
    PlannerBackedCleanupContractAdapter,
)
from roboclaws.household.planner_probe_primitive_executor import (
    ProbeBackedCleanupPrimitiveExecutor,
)
from roboclaws.household.planner_proof_bundle import (
    planner_proof_attachment_for_target,
)
from roboclaws.household.report_snapshots import (
    write_state_snapshot,
)
from roboclaws.household.semantic_camera_timeline import (
    camera_offsets_from_raw_fpv_observation,
    robot_view_capture_for_tool,
)
from roboclaws.household.semantic_cleanup_loop import (
    run_semantic_cleanup_loop,
)


def _map_build_done(
    contract: HouseholdRuntimeContract,
    base_contract: HouseholdBackendSession,
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
    contract: HouseholdRuntimeContract,
    observation: dict[str, Any],
    perception_mode: str,
) -> list[dict[str, Any]]:
    if perception_mode not in {CAMERA_MODEL_POLICY_MODE, RAW_FPV_ONLY_MODE}:
        return list(observation.get("visible_object_detections", []))
    raw = observation.get("raw_fpv_observation") or {}
    if perception_mode == RAW_FPV_ONLY_MODE:
        waypoint = contract._waypoint_by_id(str(raw.get("waypoint_id") or ""))
        candidate_inputs = (
            realworld_visual_candidate_declarations.simulated_raw_fpv_inputs_for_observation(
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
    contract: HouseholdRuntimeContract,
    base_contract: HouseholdBackendSession,
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


def _maybe_clean_visible_object(
    *,
    trace_events: list[dict[str, Any]],
    started_at: float,
    contract: HouseholdRuntimeContract,
    base_contract: HouseholdBackendSession,
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
    handled_handles.add(handle)
    agent_scratchpad["observed_handles"].setdefault(handle, {"object_id": handle})
    live_detection = contract.inspect_visible_object(handle)
    if live_detection.get("ok") and isinstance(live_detection.get("detection"), dict):
        detection = dict(live_detection["detection"])
    target_fixture = direct_policy_target_fixture(
        contract=contract,
        detection=detection,
        static_fixture_projection=static_fixture_projection,
    )
    if target_fixture is None:
        contract._mark_visual_scan_unresolved(  # noqa: SLF001
            handle,
            reason="no_public_fixture_match",
        )
        agent_scratchpad["failed_attempts"].append(
            {"object_id": handle, "reason": "no_public_fixture_match"}
        )
        return view_index
    candidate = visible_object_candidate(
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
        candidate = redirect_if_already_on_inferred_fixture(
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


def _confirm_visual_scan_candidate(
    *,
    trace_events: list[dict[str, Any]],
    started_at: float,
    contract: HouseholdRuntimeContract,
    base_contract: HouseholdBackendSession,
    handle: str,
    candidate: VisibleObjectCandidate,
    static_fixture_projection: dict[str, Any],
    robot_view_steps: list[dict[str, Any]],
    output_dir: Path,
    view_index: int,
    record_robot_views: bool,
    agent_scratchpad: dict[str, Any],
) -> tuple[VisibleObjectCandidate | None, int]:
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
        contract._mark_visual_scan_unresolved(  # noqa: SLF001
            handle,
            reason="visual_scan_confirmation_missing",
        )
        agent_scratchpad["failed_attempts"].append(
            {"object_id": handle, "reason": "visual_scan_confirmation_missing"}
        )
        return None, view_index
    detection = dict(confirmed)
    target_fixture = direct_policy_target_fixture(
        contract=contract,
        detection=detection,
        static_fixture_projection=static_fixture_projection,
    )
    if target_fixture is None:
        contract._mark_visual_scan_unresolved(  # noqa: SLF001
            handle,
            reason="no_public_fixture_match_after_visual_scan",
        )
        agent_scratchpad["failed_attempts"].append(
            {"object_id": handle, "reason": "no_public_fixture_match_after_visual_scan"}
        )
        return None, view_index
    candidate = visible_object_candidate(
        detection=detection,
        target_fixture=target_fixture,
        view_index=view_index,
    )
    return (
        redirect_if_already_on_inferred_fixture(
            contract=contract,
            handle=handle,
            candidate=candidate,
            agent_scratchpad=agent_scratchpad,
        ),
        view_index,
    )


def _write_snapshot(
    *,
    contract: HouseholdBackendSession,
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


def _internal_object_id(contract: HouseholdRuntimeContract, handle: str) -> str | None:
    return contract._internal_object_id(handle)


def _cleanup_loop_contract_for_target(
    *,
    contract: HouseholdRuntimeContract,
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
    contract: HouseholdRuntimeContract,
    base_contract: HouseholdBackendSession,
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
        camera_control_contract=(
            step.get("camera_control_contract")
            if isinstance(step.get("camera_control_contract"), dict)
            else None
        ),
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
