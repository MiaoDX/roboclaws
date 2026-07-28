"""Long-horizon household eval helpers."""

from __future__ import annotations

import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from roboclaws.evals.models import MISSING_NOT_APPLICABLE, EvalSample
from roboclaws.household.household_runtime_contract import HouseholdRuntimeContract
from roboclaws.household.semantic_timeline import robot_view_capture_for_tool

LONG_HORIZON_GRADER_NAME = "long_horizon"
SNACK_RESTOCK_SETUP = "long-horizon-snack-restock"


@dataclass(frozen=True)
class LongHorizonTaskSpec:
    """Private long-horizon task reference used only by eval harness/grader."""

    task_id: str
    target_object_ids: tuple[str, ...]
    accepted_destination_ids: tuple[str, ...]
    cold_object_ids: tuple[str, ...]
    source_room_ids: tuple[str, ...]
    source_receptacle_ids: tuple[str, ...]
    destination_room_ids: tuple[str, ...]
    required_tool_sequence: tuple[str, ...]


def is_long_horizon_sample(sample: EvalSample) -> bool:
    return LONG_HORIZON_GRADER_NAME in sample.required_graders or _task_ref(sample) is not None


def long_horizon_spec(sample: EvalSample) -> LongHorizonTaskSpec | None:
    reference = _task_ref(sample)
    if reference is None:
        return None
    return LongHorizonTaskSpec(
        task_id=str(reference.get("task_id") or sample.sample_id),
        target_object_ids=tuple(str(item) for item in reference.get("target_object_ids") or ()),
        accepted_destination_ids=tuple(
            str(item) for item in reference.get("accepted_destination_ids") or ()
        ),
        cold_object_ids=tuple(str(item) for item in reference.get("cold_object_ids") or ()),
        source_room_ids=tuple(str(item) for item in reference.get("source_room_ids") or ()),
        source_receptacle_ids=tuple(
            str(item) for item in reference.get("source_receptacle_ids") or ()
        ),
        destination_room_ids=tuple(
            str(item) for item in reference.get("destination_room_ids") or ()
        ),
        required_tool_sequence=tuple(
            str(item) for item in reference.get("required_tool_sequence") or ()
        ),
    )


def grade_long_horizon_task(
    sample: EvalSample,
    *,
    run_dir: Path,
    run_result: dict[str, Any],
) -> dict[str, Any]:
    from roboclaws.evals.long_horizon_grader import (
        grade_long_horizon_task as grade_long_horizon_task_impl,
    )

    return grade_long_horizon_task_impl(sample, run_dir=run_dir, run_result=run_result)


def generated_mess_object_ids(sample: EvalSample) -> tuple[str, ...]:
    launch_overrides = sample.launch_overrides or {}
    value = launch_overrides.get("generated_mess_object_ids")
    if isinstance(value, str):
        return tuple(item.strip() for item in value.split(",") if item.strip())
    if isinstance(value, list):
        return tuple(str(item) for item in value if str(item))
    spec = long_horizon_spec(sample)
    if spec is not None:
        return spec.target_object_ids
    return ()


def metric_fields(grader_outputs: dict[str, Any]) -> dict[str, Any]:
    grader = grader_outputs[LONG_HORIZON_GRADER_NAME]
    return {
        "long_horizon_subgoals": grader.get("subgoals", MISSING_NOT_APPLICABLE),
        "long_horizon_first_failure_step": grader.get(
            "first_failure_step",
            MISSING_NOT_APPLICABLE,
        ),
    }


def manipulation_required(sample: EvalSample, default: bool) -> bool:
    return default or is_long_horizon_sample(sample)


def _task_ref(sample: EvalSample) -> dict[str, Any] | None:
    reference = sample.private_goal_reference.get("long_horizon_task")
    return dict(reference) if isinstance(reference, dict) else None


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
