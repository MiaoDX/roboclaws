"""Evaluation policy helpers for resolved launch intents."""

from __future__ import annotations

from dataclasses import dataclass

from roboclaws.household.generated_mess import generated_mess_success_threshold
from roboclaws.launch.intents import TaskIntentSpec


@dataclass(frozen=True)
class EvaluationSpec:
    """Layered verification semantics for a resolved run."""

    evaluation_id: str
    hard_gates: tuple[str, ...]
    intent_gates: tuple[str, ...]
    completion_claim_required: bool
    advisory_evaluators: tuple[str, ...] = ()


def evaluation_spec_for_intent(intent: TaskIntentSpec) -> EvaluationSpec:
    """Return the evaluation policy for an intent."""

    hard = ("mcp_done", "run_result", "report", "trace", "goal_contract")
    if intent.intent_id == "cleanup":
        return EvaluationSpec(
            evaluation_id="cleanup_v1",
            hard_gates=hard,
            intent_gates=("cleanup_checker",),
            completion_claim_required=True,
            advisory_evaluators=("advisory_scoring",),
        )
    if intent.intent_id == "map-build":
        return EvaluationSpec(
            evaluation_id="map_build_v1",
            hard_gates=(*hard, "runtime_metric_map"),
            intent_gates=("runtime_metric_map_checker",),
            completion_claim_required=True,
            advisory_evaluators=("advisory_scoring",),
        )
    if intent.intent_id == "open-ended":
        return EvaluationSpec(
            evaluation_id="open_ended_v1",
            hard_gates=hard,
            intent_gates=("open_ended_artifact_checker",),
            completion_claim_required=True,
            advisory_evaluators=("advisory_scoring",),
        )
    return EvaluationSpec(
        evaluation_id=f"{intent.intent_id}_v1",
        hard_gates=("completion_claim", *intent.required_artifacts),
        intent_gates=(intent.checker_policy,),
        completion_claim_required=True,
    )


def checker_flags_for_household_intent(
    *,
    intent_id: str,
    profile: str,
    min_generated_mess_count: str,
) -> tuple[str, ...]:
    """Return base checker flags for a household live-agent intent."""

    flags = [
        "--require-agent-driven",
        "--require-advisory-scoring",
        "--require-completion-claim",
        "--require-goal-contract",
    ]
    if intent_id == "open-ended":
        return tuple(flags)
    if intent_id == "map-build":
        flags.append("--require-runtime-metric-map")
        flags.append("--allow-partial-cleanup")
        return tuple(flags)
    if intent_id == "cleanup" and profile in {
        "smoke",
        "world-public-labels",
        "camera-grounded-labels",
        "camera-raw-fpv",
    }:
        flags.append("--require-clean-agent-run")
    if intent_id == "cleanup" and profile == "world-public-labels":
        flags.extend(
            (
                "--require-waypoint-honesty",
                "--require-real-robot-alignment",
                "--min-semantic-accepted-count",
                "5",
                "--min-sweep-coverage",
                "1.0",
            )
        )
    if intent_id == "cleanup" and profile == "camera-raw-fpv":
        raw_fpv_required_cleanup_count = str(
            generated_mess_success_threshold(int(min_generated_mess_count))
        )
        flags.extend(
            (
                "--require-model-declared-observations",
                "--min-model-declared-observations",
                raw_fpv_required_cleanup_count,
                "--min-model-declared-actions",
                raw_fpv_required_cleanup_count,
                "--min-semantic-accepted-count",
                raw_fpv_required_cleanup_count,
                "--min-sweep-coverage",
                "1.0",
            )
        )
    return tuple(flags)


def household_intent_id_for_checker(
    *,
    task_intent: str = "",
    open_ended_task: bool = False,
) -> str:
    """Return the canonical household intent for live-run checker calls."""

    if task_intent:
        return task_intent
    if open_ended_task:
        return "open-ended"
    return "cleanup"


VALUE_CHECKER_FLAGS = frozenset(
    {
        "--min-semantic-accepted-count",
        "--min-model-declared-observations",
        "--min-model-declared-actions",
        "--min-sweep-coverage",
    }
)


def merge_checker_flags(*groups: tuple[str, ...] | list[str]) -> tuple[str, ...]:
    """Merge checker flags, de-duplicating value-bearing flags as a unit."""

    merged: list[str] = []
    seen_flags: set[str] = set()
    for group in groups:
        index = 0
        items = list(group)
        while index < len(items):
            item = items[index]
            value = ""
            has_value = item in VALUE_CHECKER_FLAGS
            if has_value and index + 1 < len(items):
                value = items[index + 1]
            if item in seen_flags:
                index += 2 if has_value else 1
                continue
            merged.append(item)
            seen_flags.add(item)
            if has_value:
                merged.append(value)
                index += 2
            else:
                index += 1
    return tuple(merged)
