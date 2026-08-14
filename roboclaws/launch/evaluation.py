"""Checker policy helpers for resolved launch intents."""

from __future__ import annotations

from roboclaws.household.generated_mess import generated_mess_success_threshold


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
