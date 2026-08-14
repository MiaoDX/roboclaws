"""Long-horizon household eval helpers."""

from __future__ import annotations

import time
from pathlib import Path
from typing import Any

from roboclaws.household.household_runtime_contract import HouseholdRuntimeContract
from roboclaws.household.semantic_camera_timeline import robot_view_capture_for_tool


def _call_tool(
    events: list[dict[str, Any]],
    started_at: float,
    tool: str,
    request: dict[str, Any],
    fn: Any,
) -> dict[str, Any]:
    events.append(_trace_event(started_at, tool=tool, event="request", request=request))
    response = fn()
    events.append(_trace_event(started_at, tool=tool, event="response", response=response))
    return response


def _call_tool_with_robot_view(
    events: list[dict[str, Any]],
    started_at: float,
    tool: str,
    request: dict[str, Any],
    fn: Any,
    *,
    base_contract: Any,
    contract: HouseholdRuntimeContract,
    robot_view_steps: list[dict[str, Any]],
    output_dir: Path,
    view_index: int,
    record_robot_views: bool,
) -> tuple[dict[str, Any], int]:
    response = _call_tool(events, started_at, tool, request, fn)
    if not response.get("ok"):
        return response, view_index
    capture = robot_view_capture_for_tool(
        tool,
        request,
        response,
        object_id_transform=lambda value: (
            _internal_object_id(contract, value) if value is not None else None
        ),
    )
    if capture is None:
        return response, view_index
    view_index = _record_long_horizon_robot_view(
        base_contract=base_contract,
        robot_view_steps=robot_view_steps,
        output_dir=output_dir,
        view_index=view_index,
        action=str(capture["action"]),
        label_suffix=str(capture["label_suffix"]),
        record_robot_views=record_robot_views,
        focus_object_id=capture.get("focus_object_id"),
        focus_receptacle_id=contract.internal_fixture_id_for_public_reference(
            capture.get("focus_receptacle_id")
        ),
        semantic_phase=capture.get("semantic_phase"),
        action_evidence=capture.get("action_evidence"),
        camera_yaw_offset_deg=float(capture.get("camera_yaw_offset_deg") or 0.0),
        camera_pitch_offset_deg=float(capture.get("camera_pitch_offset_deg") or 0.0),
    )
    return response, view_index


def _record_long_horizon_robot_view(
    *,
    base_contract: Any,
    robot_view_steps: list[dict[str, Any]],
    output_dir: Path,
    view_index: int,
    action: str,
    label_suffix: str,
    record_robot_views: bool,
    focus_object_id: str | None = None,
    focus_receptacle_id: str | None = None,
    semantic_phase: str | None = None,
    action_evidence: dict[str, Any] | None = None,
    camera_yaw_offset_deg: float = 0.0,
    camera_pitch_offset_deg: float = 0.0,
) -> int:
    if not record_robot_views:
        return view_index
    return base_contract.record_robot_view_step(
        steps=robot_view_steps,
        output_dir=output_dir,
        index=view_index,
        action=action,
        label_suffix=label_suffix,
        focus_object_id=focus_object_id,
        focus_receptacle_id=focus_receptacle_id,
        semantic_phase=semantic_phase,
        action_evidence=action_evidence,
        camera_yaw_offset_deg=camera_yaw_offset_deg,
        camera_pitch_offset_deg=camera_pitch_offset_deg,
    )


def _internal_object_id(contract: HouseholdRuntimeContract, handle: str) -> str | None:
    return contract._internal_object_id(handle)  # noqa: SLF001


def _trace_event(started_at: float, *, tool: str, event: str, **payload: Any) -> dict[str, Any]:
    return {
        "ts": round(time.time() - started_at, 6),
        "tool": tool,
        "event": event,
        **payload,
    }
