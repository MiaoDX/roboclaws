"""Small state-summary predicates used by the operator console."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

TERMINAL_RUN_PHASES = {
    "failed",
    "finished",
    "passed",
    "stopped_by_operator",
    "human_takeover_stop",
}


@dataclass
class _CameraTraceState:
    offset: dict[str, float]
    latest_adjust: dict[str, Any]
    latest_event: str = ""
    current_waypoint_id: str = ""


def camera_angle_summary(rows: list[dict[str, Any]]) -> dict[str, Any]:
    state = _CameraTraceState(
        offset={"yaw_delta_deg": 0.0, "pitch_delta_deg": 0.0},
        latest_adjust={},
    )
    for payload in rows:
        _apply_camera_trace_payload(state, payload)

    if not state.latest_adjust and state.offset == {
        "yaw_delta_deg": 0.0,
        "pitch_delta_deg": 0.0,
    }:
        return {}
    active = bool(state.offset.get("yaw_delta_deg") or state.offset.get("pitch_delta_deg"))
    return {
        "camera_offset": state.offset,
        "active": active,
        "latest_adjust": state.latest_adjust,
        "latest_event": state.latest_event,
        "reset_on_navigation": True,
        "summary": _camera_angle_label(state.offset, active=active),
    }


def _apply_camera_trace_payload(state: _CameraTraceState, payload: dict[str, Any]) -> None:
    tool = str(payload.get("tool") or payload.get("tool_name") or "")
    event = str(payload.get("event") or "")
    response = payload.get("response") if isinstance(payload.get("response"), dict) else {}
    request = payload.get("request") if isinstance(payload.get("request"), dict) else {}
    if _camera_navigation_reset_tool(tool, event):
        _apply_camera_navigation_reset(state, tool, response)
    elif tool == "adjust_camera" and event == "request":
        _apply_camera_adjust_request(state, request)
    elif tool == "adjust_camera" and event == "response":
        _apply_camera_adjust_response(state, response)


def _camera_navigation_reset_tool(tool: str, event: str) -> bool:
    return event == "response" and tool in {
        "navigate_to_waypoint",
        "navigate_to_object",
        "navigate_to_receptacle",
    }


def _apply_camera_navigation_reset(
    state: _CameraTraceState,
    tool: str,
    response: dict[str, Any],
) -> None:
    if response.get("ok") is not True:
        return
    state.offset = {"yaw_delta_deg": 0.0, "pitch_delta_deg": 0.0}
    state.latest_event = f"{tool}_reset"
    waypoint_id = response.get("waypoint_id")
    if waypoint_id:
        state.current_waypoint_id = str(waypoint_id)


def _apply_camera_adjust_request(
    state: _CameraTraceState,
    request: dict[str, Any],
) -> None:
    state.latest_adjust = {
        "requested_yaw_delta_deg": _float_or_zero(request.get("yaw_delta_deg")),
        "requested_pitch_delta_deg": _float_or_zero(request.get("pitch_delta_deg")),
    }
    state.latest_event = "adjust_camera_request"


def _apply_camera_adjust_response(
    state: _CameraTraceState,
    response: dict[str, Any],
) -> None:
    state.offset = _camera_offset_from_response(response)
    previous = response.get("previous_camera_offset")
    state.latest_adjust.update(
        {
            "ok": response.get("ok"),
            "status": response.get("status"),
            "previous_camera_offset": previous if isinstance(previous, dict) else {},
            "camera_offset": dict(state.offset),
            "waypoint_id": str(response.get("waypoint_id") or state.current_waypoint_id),
        }
    )
    state.latest_event = "adjust_camera_response"
    if state.latest_adjust["waypoint_id"]:
        state.current_waypoint_id = state.latest_adjust["waypoint_id"]


def _camera_offset_from_response(response: dict[str, Any]) -> dict[str, float]:
    camera_offset = response.get("camera_offset")
    source = camera_offset if isinstance(camera_offset, dict) else response
    return {
        "yaw_delta_deg": _float_or_zero(source.get("yaw_delta_deg")),
        "pitch_delta_deg": _float_or_zero(source.get("pitch_delta_deg")),
    }


def _camera_angle_label(offset: dict[str, float], *, active: bool) -> str:
    yaw = _float_or_zero(offset.get("yaw_delta_deg"))
    pitch = _float_or_zero(offset.get("pitch_delta_deg"))
    status = "active" if active else "neutral"
    return f"yaw {yaw:g} deg, pitch {pitch:g} deg ({status})"


def _float_or_zero(value: Any) -> float:
    """Parse a float with full precision (no rounding). Distinct from
    state._float_or_zero which rounds to 3dp."""
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


def run_result_success(run_result: dict[str, Any]) -> bool:
    if not run_result:
        return False
    if run_result_has_failure(run_result):
        return False
    if is_open_ended_run_result(run_result):
        return _open_ended_run_result_success(run_result)
    return _standard_run_result_success(run_result)


def _open_ended_run_result_success(run_result: dict[str, Any]) -> bool:
    if _any_success_status(run_result, ("intent_status", "goal_status", "final_status", "status")):
        return True
    score = _dict_value(run_result, "score")
    return is_success_string(score.get("status"))


def _standard_run_result_success(run_result: dict[str, Any]) -> bool:
    if _any_true_status(run_result, ("ok", "success", "cleanup_success", "runtime_map_success")):
        return True
    if _any_success_status(
        run_result,
        ("cleanup_status", "completion_status", "final_status", "status"),
    ):
        return True
    score = _dict_value(run_result, "score")
    return _any_success_status(score, ("completion_status", "status"))


def run_result_has_failure(run_result: dict[str, Any]) -> bool:
    if is_open_ended_run_result(run_result):
        return _open_ended_run_result_failure(run_result)
    return _standard_run_result_failure(run_result)


def _open_ended_run_result_failure(run_result: dict[str, Any]) -> bool:
    return _any_false_status(run_result, ("ok", "success", "runtime_map_success")) or (
        _any_failure_status(run_result, ("intent_status", "goal_status", "status"))
    )


def _standard_run_result_failure(run_result: dict[str, Any]) -> bool:
    return _any_false_status(
        run_result,
        ("ok", "success", "cleanup_success", "runtime_map_success"),
    ) or _any_failure_status(
        run_result,
        ("cleanup_status", "completion_status", "final_status", "status"),
    )


def _any_true_status(payload: dict[str, Any], keys: tuple[str, ...]) -> bool:
    return any(payload.get(key) is True for key in keys)


def _any_false_status(payload: dict[str, Any], keys: tuple[str, ...]) -> bool:
    return any(payload.get(key) is False for key in keys)


def _any_success_status(payload: dict[str, Any], keys: tuple[str, ...]) -> bool:
    return any(is_success_string(payload.get(key)) for key in keys)


def _any_failure_status(payload: dict[str, Any], keys: tuple[str, ...]) -> bool:
    return any(is_failure_string(payload.get(key)) for key in keys)


def _dict_value(payload: dict[str, Any], key: str) -> dict[str, Any]:
    value = payload.get(key)
    return value if isinstance(value, dict) else {}


def is_open_ended_run_result(run_result: dict[str, Any]) -> bool:
    goal_contract = (
        run_result.get("goal_contract") if isinstance(run_result.get("goal_contract"), dict) else {}
    )
    intent = str(run_result.get("task_intent") or goal_contract.get("intent") or "").strip()
    return intent == "open-ended"


def is_success_string(value: Any) -> bool:
    return str(value).strip().lower() in {"success", "ok", "passed"}


def is_failure_string(value: Any) -> bool:
    return str(value).strip().lower() in {"failed", "failure", "error"}


def terminal_status_phase(live_status: dict[str, Any], state: dict[str, Any]) -> str:
    for payload in (live_status, state):
        phase = str(payload.get("phase") or "").strip().lower()
        if phase in TERMINAL_RUN_PHASES:
            return phase
    return ""


def run_result_terminal_phase(run_result: dict[str, Any]) -> str:
    if run_result_success(run_result):
        return "finished"
    if run_result_has_failure(run_result):
        return "failed"
    return ""


def terminal_phase_from_payloads(
    live_status: dict[str, Any],
    state: dict[str, Any],
    run_result: dict[str, Any],
) -> str:
    return terminal_status_phase(live_status, state) or run_result_terminal_phase(run_result)


def task_phase_from_payloads(
    live_status: dict[str, Any],
    state: dict[str, Any],
    run_result: dict[str, Any],
) -> str:
    phase = str(live_status.get("phase") or "").strip()
    if phase:
        return phase
    terminal_phase = run_result_terminal_phase(run_result)
    if terminal_phase:
        return terminal_phase
    return str(state.get("phase") or "unknown")


def task_phase_from_paths(
    display_run_dir: Path, state: dict[str, Any], *, read_json: Any
) -> str:
    live_status = read_json(display_run_dir / "live_status.json")
    run_result = read_json(display_run_dir / "run_result.json")
    return task_phase_from_payloads(live_status, state, run_result)


def existing_terminal_phase(
    display_run_dir: Path,
    state: dict[str, Any],
    *,
    read_json: Any,
) -> str:
    live_status = read_json(display_run_dir / "live_status.json")
    phase = terminal_status_phase(live_status, state)
    if phase:
        return phase
    return run_result_terminal_phase(read_json(display_run_dir / "run_result.json"))


def existing_terminal_reason(
    display_run_dir: Path,
    state: dict[str, Any],
    *,
    read_json: Any,
) -> str:
    live_status = read_json(display_run_dir / "live_status.json")
    run_result = read_json(display_run_dir / "run_result.json")
    for payload in (live_status, state, run_result):
        for key in ("terminal_reason", "reason", "error_reason", "terminate_reason"):
            value = payload.get(key)
            if value:
                return str(value)
    return ""

