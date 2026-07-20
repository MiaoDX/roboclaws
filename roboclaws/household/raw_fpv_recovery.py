from __future__ import annotations

from typing import Any

RAW_FPV_RECOVERY_GATE_SCHEMA = "raw_fpv_recovery_gate_v1"


def raw_fpv_recovery_exhaustion(
    trace_events: list[dict[str, Any]],
    *,
    evidence_lane: str,
    task_intent: str = "",
) -> dict[str, Any] | None:
    state = raw_fpv_recovery_state(
        trace_events,
        evidence_lane=evidence_lane,
        task_intent=task_intent or _task_intent(trace_events),
    )
    if not state.get("terminal_exhausted"):
        return None
    return {
        "schema": "raw_fpv_recovery_exhausted_v1",
        "reason": "raw_fpv_recovery_exhausted",
        "progress_fingerprint": dict(state.get("progress_fingerprint") or {}),
        "consumed_waypoint_ids": list(state.get("consumed_waypoint_ids") or []),
        "eligible_waypoint_ids": [],
        "epoch_event_index": state.get("epoch_event_index"),
        "final_done_event_index": state.get("latest_done_event_index"),
        "policy_uses_private_truth": False,
    }


def raw_fpv_recovery_gate(
    trace_events: list[dict[str, Any]],
    *,
    evidence_lane: str,
    task_intent: str,
    tool: str,
    request: dict[str, Any],
) -> dict[str, Any] | None:
    state = raw_fpv_recovery_state(
        trace_events,
        evidence_lane=evidence_lane,
        task_intent=task_intent,
    )
    if not state["active"]:
        return None

    expected_tool = str(state.get("expected_tool") or "")
    if expected_tool and tool != expected_tool:
        return _unexpected_recovery_tool_gate(tool, state, trace_events)

    if state["phase"] == "overlap_probe":
        return _overlap_gate(tool, request, state)
    if state["phase"] != "bounded_revisit":
        return None
    if state.get("terminal_exhausted"):
        return _blocked(tool, state, "raw_fpv_recovery_exhausted")
    return _bounded_revisit_gate(tool, request, state)


def raw_fpv_recovery_state(
    trace_events: list[dict[str, Any]],
    *,
    evidence_lane: str,
    task_intent: str,
) -> dict[str, Any]:
    inactive = {
        "schema": RAW_FPV_RECOVERY_GATE_SCHEMA,
        "active": False,
        "phase": "inactive",
    }
    if evidence_lane != "camera-raw-fpv" or task_intent != "cleanup":
        return inactive

    done_events = _blocked_done_events(trace_events)
    if not done_events:
        return inactive
    latest_index, latest_blockers = done_events[-1]
    chain = _blocker(latest_blockers, "insufficient_grounded_cleanup_chains")
    overlap_events = [
        (index, blocker)
        for index, blockers in done_events
        if (blocker := _blocker(blockers, "insufficient_raw_fpv_overlap_probe_coverage"))
    ]
    completed_overlap_waypoints = {
        str(blocker.get("next_waypoint_id") or "")
        for index, blocker in overlap_events
        if _overlap_probe_completed(trace_events[index + 1 :], blocker)
    }
    pending_overlap = next(
        (
            (index, blocker)
            for index, blocker in overlap_events
            if not _overlap_probe_completed(trace_events[index + 1 :], blocker)
        ),
        None,
    )
    common = {
        "schema": RAW_FPV_RECOVERY_GATE_SCHEMA,
        "active": True,
        "latest_done_event_index": latest_index,
        "public_progress_since_latest_done": _has_public_progress(trace_events[latest_index + 1 :]),
        "completed_overlap_waypoint_ids": sorted(completed_overlap_waypoints),
    }
    if pending_overlap is not None:
        index, blocker = pending_overlap
        step = _overlap_step(trace_events[index + 1 :], blocker)
        return {
            **common,
            "phase": "overlap_probe",
            "epoch_event_index": index,
            "next_waypoint_id": str(blocker.get("next_waypoint_id") or ""),
            "expected_tool": step,
            "required_camera_adjustment": dict(blocker.get("required_camera_adjustment") or {}),
        }
    if chain is None:
        return {**common, "phase": "ready_for_done", "expected_tool": ""}

    current = _int_or_zero(chain.get("current"))
    epoch_index = _chain_epoch_index(done_events, current)
    epoch_events = trace_events[epoch_index + 1 :]
    known_waypoints = _known_waypoint_ids(trace_events)
    authorized_waypoints = _authorized_candidate_waypoints(trace_events)
    revisit_observations = _bounded_revisit_observations(epoch_events)
    attempted_observation_ids = _candidate_attempt_observation_ids(epoch_events)
    consumed = set(revisit_observations) | completed_overlap_waypoints
    eligible = [
        waypoint_id
        for waypoint_id in known_waypoints
        if waypoint_id not in authorized_waypoints and waypoint_id not in consumed
    ]
    pending = _pending_revisit_step(epoch_events, eligible)
    fresh_observation_id = str(pending.get("fresh_observation_id") or "")
    if not fresh_observation_id and revisit_observations:
        latest_revisit_observation_id = next(reversed(revisit_observations.values()))
        if (
            latest_revisit_observation_id not in attempted_observation_ids
            and _latest_recovery_action_observation_id(epoch_events)
            == latest_revisit_observation_id
        ):
            fresh_observation_id = latest_revisit_observation_id
    latest_pending_candidates = _blocker(latest_blockers, "pending_cleanup_candidates")
    terminal_exhausted = bool(
        latest_index > epoch_index
        and not eligible
        and not pending.get("expected_tool")
        and latest_pending_candidates is None
        and current < _int_or_zero(chain.get("required"))
    )
    return {
        **common,
        "phase": "bounded_revisit",
        "epoch_event_index": epoch_index,
        "progress_fingerprint": {
            "grounded_cleanup_chains": current,
            "required": _int_or_zero(chain.get("required")),
        },
        "expected_tool": pending.get("expected_tool") or "",
        "next_waypoint_id": pending.get("waypoint_id") or (eligible[0] if eligible else ""),
        "active_waypoint_id": (
            pending.get("waypoint_id") or ""
            if pending.get("expected_tool") in {"navigate_to_relative_pose", "observe"}
            else ""
        ),
        "fresh_observation_id": fresh_observation_id,
        "consumed_waypoint_ids": sorted(consumed),
        "eligible_waypoint_ids": eligible,
        "attempted_fresh_observation_ids": sorted(attempted_observation_ids),
        "terminal_exhausted": terminal_exhausted,
    }


_ALWAYS_ALLOWED_RECOVERY_TOOLS = frozenset(
    {"check_operator_messages", "resolve_target_query", "inspect_visible_object"}
)
_MANIPULATION_TOOLS = frozenset(
    {
        "navigate_to_object",
        "pick",
        "navigate_to_receptacle",
        "open_receptacle",
        "place",
        "place_inside",
        "close_receptacle",
    }
)


def _overlap_gate(
    tool: str, request: dict[str, Any], state: dict[str, Any]
) -> dict[str, Any] | None:
    waypoint_id = str(state.get("next_waypoint_id") or "")
    if tool == "navigate_to_waypoint" and str(request.get("waypoint_id") or "") != waypoint_id:
        return _blocked(tool, state, "raw_fpv_recovery_wrong_waypoint")
    if tool == "adjust_camera":
        required = state.get("required_camera_adjustment") or {}
        if not _same_number(request.get("yaw_delta_deg"), required.get("yaw_delta_deg")) or not (
            _same_number(request.get("pitch_delta_deg"), required.get("pitch_delta_deg"))
        ):
            return _blocked(tool, state, "raw_fpv_recovery_wrong_camera_adjustment")
    return None


def _bounded_revisit_gate(
    tool: str, request: dict[str, Any], state: dict[str, Any]
) -> dict[str, Any] | None:
    if tool == "done":
        return _bounded_revisit_done_gate(tool, state)
    if tool in _MANIPULATION_TOOLS:
        return None
    if tool == "navigate_to_waypoint":
        return _bounded_revisit_waypoint_gate(tool, request, state)
    if tool == "navigate_to_relative_pose":
        return _bounded_revisit_relative_pose_gate(tool, request, state)
    if tool == "navigate_to_visual_candidate":
        return _bounded_revisit_candidate_gate(tool, request, state)
    if tool in {"metric_map", "navigate_to_room", "adjust_camera", "declare_visual_candidates"}:
        return _blocked(tool, state, "raw_fpv_recovery_step_required")
    return None


def _unexpected_recovery_tool_gate(
    tool: str,
    state: dict[str, Any],
    trace_events: list[dict[str, Any]],
) -> dict[str, Any] | None:
    if tool == "done":
        if state.get("public_progress_since_latest_done"):
            return None
        if state.get("phase") == "bounded_revisit":
            return _blocked(tool, state, "done_without_public_progress")
    if state.get("phase") == "bounded_revisit" and tool in _MANIPULATION_TOOLS:
        return None
    if state.get("phase") == "bounded_revisit" and tool == "observe":
        if _latest_successful_tool(trace_events) in {"place", "place_inside", "close_receptacle"}:
            return None
    if tool in _ALWAYS_ALLOWED_RECOVERY_TOOLS:
        return None
    return _blocked(tool, state, "raw_fpv_recovery_step_required")


def _bounded_revisit_done_gate(tool: str, state: dict[str, Any]) -> dict[str, Any] | None:
    if state.get("public_progress_since_latest_done"):
        return None
    return _blocked(tool, state, "done_without_public_progress")


def _bounded_revisit_waypoint_gate(
    tool: str, request: dict[str, Any], state: dict[str, Any]
) -> dict[str, Any] | None:
    waypoint_id = str(request.get("waypoint_id") or "")
    if waypoint_id in set(state.get("consumed_waypoint_ids") or []):
        return _blocked(tool, state, "raw_fpv_recovery_waypoint_consumed")
    if waypoint_id not in set(state.get("eligible_waypoint_ids") or []):
        return _blocked(tool, state, "raw_fpv_recovery_waypoint_not_eligible")
    return None


def _bounded_revisit_relative_pose_gate(
    tool: str, request: dict[str, Any], state: dict[str, Any]
) -> dict[str, Any] | None:
    valid = (
        _same_number(request.get("forward_m"), 0)
        and _same_number(request.get("lateral_m"), 0)
        and _same_number(abs(_number(request.get("yaw_delta_deg"))), 45)
    )
    return None if valid else _blocked(tool, state, "raw_fpv_recovery_wrong_relative_pose")


def _bounded_revisit_candidate_gate(
    tool: str, request: dict[str, Any], state: dict[str, Any]
) -> dict[str, Any] | None:
    source_id = str(request.get("source_observation_id") or "")
    if source_id in set(state.get("attempted_fresh_observation_ids") or []):
        return _blocked(tool, state, "raw_fpv_recovery_observation_consumed")
    if not source_id or source_id != str(state.get("fresh_observation_id") or ""):
        return _blocked(tool, state, "raw_fpv_recovery_stale_observation")
    return None


def _blocked(tool: str, state: dict[str, Any], reason: str) -> dict[str, Any]:
    required_tool = str(state.get("expected_tool") or "")
    if not required_tool:
        required_tool = "navigate_to_waypoint" if state.get("next_waypoint_id") else "done"
    return {
        "ok": False,
        "tool": tool,
        "status": "blocked",
        "error_reason": reason,
        "required_tool": required_tool,
        "next_waypoint_id": str(state.get("next_waypoint_id") or ""),
        "recovery_phase": str(state.get("phase") or ""),
        "recovery_gate_schema": RAW_FPV_RECOVERY_GATE_SCHEMA,
        "policy_uses_private_truth": False,
        "recovery_hint": (
            f"Continue the bounded public recovery with {required_tool}. "
            "Do not repeat consumed waypoints or reuse an older observation."
        ),
    }


def _blocked_done_events(
    events: list[dict[str, Any]],
) -> list[tuple[int, list[dict[str, Any]]]]:
    result = []
    for index, event in enumerate(events):
        if event.get("event") != "response" or event.get("tool") != "done":
            continue
        response = event.get("response") if isinstance(event.get("response"), dict) else {}
        completion = (
            response.get("completion") if isinstance(response.get("completion"), dict) else {}
        )
        blockers = completion.get("blockers")
        if response.get("ok") is False and isinstance(blockers, list):
            result.append((index, [item for item in blockers if isinstance(item, dict)]))
    return result


def _task_intent(events: list[dict[str, Any]]) -> str:
    for event in events:
        goal_contract = event.get("goal_contract")
        if isinstance(goal_contract, dict) and goal_contract.get("intent"):
            return str(goal_contract["intent"])
        if event.get("task_intent"):
            return str(event["task_intent"])
    return ""


def _blocker(blockers: list[dict[str, Any]], blocker_type: str) -> dict[str, Any] | None:
    return next((item for item in blockers if item.get("type") == blocker_type), None)


def _chain_epoch_index(done_events: list[tuple[int, list[dict[str, Any]]]], current: int) -> int:
    matching = []
    for index, blockers in done_events:
        blocker = _blocker(blockers, "insufficient_grounded_cleanup_chains")
        if blocker is not None and _int_or_zero(blocker.get("current")) == current:
            matching.append(index)
    return matching[0] if matching else done_events[-1][0]


def _overlap_step(events: list[dict[str, Any]], blocker: dict[str, Any]) -> str:
    waypoint_id = str(blocker.get("next_waypoint_id") or "")
    adjustment = blocker.get("required_camera_adjustment") or {}
    step = "navigate_to_waypoint"
    for event in events:
        if step == "navigate_to_waypoint" and _successful_response(event, "navigate_to_waypoint"):
            if str(event["response"].get("waypoint_id") or "") == waypoint_id:
                step = "adjust_camera"
        elif step == "adjust_camera" and _successful_response(event, "adjust_camera"):
            if _response_matches(
                event["response"],
                {
                    "yaw_delta_deg": adjustment.get("yaw_delta_deg"),
                    "pitch_delta_deg": adjustment.get("pitch_delta_deg"),
                },
            ):
                step = "observe"
        elif step == "observe" and _successful_response(event, "observe"):
            if str(event["response"].get("waypoint_id") or "") == waypoint_id:
                return ""
    return step


def _overlap_probe_completed(events: list[dict[str, Any]], blocker: dict[str, Any]) -> bool:
    return _overlap_step(events, blocker) == ""


def _pending_revisit_step(events: list[dict[str, Any]], eligible: list[str]) -> dict[str, str]:
    consumed, active_waypoint, expected_tool = _bounded_revisit_progress(events)
    if active_waypoint in eligible and active_waypoint not in consumed:
        return {"expected_tool": expected_tool, "waypoint_id": active_waypoint}
    if consumed:
        return {"expected_tool": "", "waypoint_id": eligible[0] if eligible else ""}
    return {
        "expected_tool": "navigate_to_waypoint",
        "waypoint_id": eligible[0] if eligible else "",
    }


def _bounded_revisit_observations(events: list[dict[str, Any]]) -> dict[str, str]:
    return _bounded_revisit_progress(events)[0]


def _bounded_revisit_progress(
    events: list[dict[str, Any]],
) -> tuple[dict[str, str], str, str]:
    consumed: dict[str, str] = {}
    active_waypoint = ""
    expected_tool = "navigate_to_waypoint"
    for event in events:
        if _successful_response(event, "navigate_to_waypoint"):
            active_waypoint = str(event["response"].get("waypoint_id") or "")
            expected_tool = "navigate_to_relative_pose"
        elif (
            active_waypoint
            and expected_tool == "navigate_to_relative_pose"
            and _successful_response(event, "navigate_to_relative_pose")
        ):
            response = event["response"]
            delta = response.get("applied_delta") or response.get("requested_delta") or {}
            if _same_number(abs(_number(delta.get("yaw_delta_deg"))), 45):
                expected_tool = "observe"
        elif (
            active_waypoint
            and expected_tool == "observe"
            and _successful_response(event, "observe")
        ):
            waypoint_id = str(event["response"].get("waypoint_id") or "")
            if waypoint_id == active_waypoint:
                consumed[waypoint_id] = _observation_id(event)
            active_waypoint = ""
            expected_tool = "navigate_to_waypoint"
    return consumed, active_waypoint, expected_tool


def _known_waypoint_ids(events: list[dict[str, Any]]) -> list[str]:
    for event in events:
        if not _successful_response(event, "metric_map"):
            continue
        waypoints = event["response"].get("inspection_waypoints")
        if isinstance(waypoints, list):
            return [
                str(item.get("waypoint_id") or "")
                for item in waypoints
                if isinstance(item, dict) and item.get("waypoint_id")
            ]
    return []


def _authorized_candidate_waypoints(events: list[dict[str, Any]]) -> set[str]:
    observations = {}
    pending_waypoints: list[str] = []
    authorized = set()
    for event in events:
        if _successful_response(event, "observe"):
            observation_id = _observation_id(event)
            waypoint_id = str(event["response"].get("waypoint_id") or "")
            if observation_id:
                observations[observation_id] = waypoint_id
        elif (
            event.get("event") == "request" and event.get("tool") == "navigate_to_visual_candidate"
        ):
            request = event.get("request") if isinstance(event.get("request"), dict) else {}
            observation_id = str(request.get("source_observation_id") or "")
            pending_waypoints.append(observations.get(observation_id, ""))
        elif (
            event.get("event") == "response" and event.get("tool") == "navigate_to_visual_candidate"
        ):
            waypoint_id = pending_waypoints.pop(0) if pending_waypoints else ""
            response = event.get("response") if isinstance(event.get("response"), dict) else {}
            if response.get("ok") is True and waypoint_id:
                authorized.add(waypoint_id)
    return authorized


def _candidate_attempt_observation_ids(events: list[dict[str, Any]]) -> set[str]:
    return {
        str(request.get("source_observation_id") or "")
        for event in events
        if event.get("event") == "request" and event.get("tool") == "navigate_to_visual_candidate"
        for request in [event.get("request") if isinstance(event.get("request"), dict) else {}]
        if request.get("source_observation_id")
    }


def _has_public_progress(events: list[dict[str, Any]]) -> bool:
    return any(
        event.get("event") == "response"
        and isinstance(event.get("response"), dict)
        and event["response"].get("ok") is True
        and event.get("tool")
        in {"observe", "navigate_to_visual_candidate", "place", "place_inside", "close_receptacle"}
        for event in events
    )


def _latest_successful_tool(events: list[dict[str, Any]]) -> str:
    for event in reversed(events):
        response = event.get("response") if isinstance(event.get("response"), dict) else {}
        if event.get("event") == "response" and response.get("ok") is True:
            return str(event.get("tool") or "")
    return ""


def _latest_recovery_action_observation_id(events: list[dict[str, Any]]) -> str:
    latest_tool = ""
    latest_observation_id = ""
    recovery_actions = {
        "navigate_to_waypoint",
        "navigate_to_relative_pose",
        "observe",
        "navigate_to_visual_candidate",
        *_MANIPULATION_TOOLS,
    }
    for event in events:
        if event.get("tool") not in recovery_actions:
            continue
        response = event.get("response") if isinstance(event.get("response"), dict) else {}
        if event.get("event") != "response" or response.get("ok") is not True:
            continue
        latest_tool = str(event.get("tool") or "")
        latest_observation_id = _observation_id(event) if latest_tool == "observe" else ""
    return latest_observation_id


def _successful_response(event: dict[str, Any], tool: str) -> bool:
    return (
        event.get("event") == "response"
        and event.get("tool") == tool
        and isinstance(event.get("response"), dict)
        and event["response"].get("ok") is True
    )


def _response_matches(response: dict[str, Any], matches: dict[str, Any]) -> bool:
    for key, expected in matches.items():
        if key == "abs_yaw_delta_deg":
            delta = response.get("applied_delta") or response.get("requested_delta") or {}
            if not _same_number(abs(_number(delta.get("yaw_delta_deg"))), expected):
                return False
        elif key in {"yaw_delta_deg", "pitch_delta_deg"}:
            offset = response.get("camera_offset") or {}
            if not _same_number(offset.get(key), expected):
                return False
        elif str(response.get(key) or "") != str(expected or ""):
            return False
    return True


def _observation_id(event: dict[str, Any]) -> str:
    response = event.get("response") if isinstance(event.get("response"), dict) else {}
    raw = response.get("raw_fpv_observation")
    raw = raw if isinstance(raw, dict) else {}
    return str(raw.get("observation_id") or "")


def _same_number(value: Any, expected: Any) -> bool:
    return abs(_number(value) - _number(expected)) <= 1e-6


def _number(value: Any) -> float:
    try:
        return float(value or 0.0)
    except (TypeError, ValueError):
        return 0.0


def _int_or_zero(value: Any) -> int:
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return 0
