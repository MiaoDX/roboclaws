"""Checker policy values shared by launch and agent runtimes."""

from __future__ import annotations

from roboclaws.core.generated_mess import generated_mess_success_threshold


def checker_flags_for_household_intent(
    *,
    intent_id: str,
    profile: str,
    min_generated_mess_count: str,
) -> tuple[str, ...]:
    """Return base checker flags for a household live-agent intent."""

    flags = [
        "--require-agent-driven",
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
