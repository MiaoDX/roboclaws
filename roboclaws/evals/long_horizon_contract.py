"""Pure value contracts for long-horizon household evals."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from roboclaws.evals.models import MISSING_NOT_APPLICABLE, EvalSample

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
