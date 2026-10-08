"""Eval-layer thresholds for complete, explicitly selected showcase cohorts."""

from collections import Counter
from typing import Any

from roboclaws.evals.showcase_acceptance import validate_result_identities

# Infrastructure, privacy, trajectory and checker failures cannot be traded
# against successful cases in a capability cohort.
BEHAVIOR_FAILURES = frozenset(
    {
        "agent_no_completion_claim",
        "private_goal_not_satisfied",
        "partial_progress_only",
        "tool_argument_invalid",
        "tool_noop_or_repeated_failure",
        "perception_miss",
        "manipulation_failure",
        "map_actionability_failure",
        "planner_proof_missing_or_failed",
    }
)


def validate_cohort_policy(row: dict[str, Any], samples: list[Any]) -> None:
    policy = row.get("cohort_acceptance")
    if policy is None:
        return
    fields = {"min_passed", "min_per_world", "reserved_worlds", "min_reserved_passed"}
    if not isinstance(policy, dict) or set(policy) != fields:
        raise ValueError("cohort_acceptance requires exact overall, per-world and reserved bounds")
    if not row.get("provider_profile") or row.get("repetition_index") is not None:
        raise ValueError("cohort_acceptance requires a complete provider-backed cohort")
    selected = [sample for sample in samples if sample.sample_id in row["sample_ids"]]
    counts: Counter[str] = Counter()
    for sample in selected:
        counts[sample.world] += sample.trial_count
    reserved = policy["reserved_worlds"]
    if (
        not isinstance(reserved, list)
        or not reserved
        or not all(isinstance(world, str) for world in reserved)
        or len(set(reserved)) != len(reserved)
        or not set(reserved) < set(counts)
    ):
        raise ValueError(
            "cohort reserved_worlds must select distinct known worlds and leave development"
        )
    limits = {
        "min_passed": sum(counts.values()),
        "min_per_world": min(counts.values()),
        "min_reserved_passed": sum(counts[world] for world in reserved),
    }
    for field, maximum in limits.items():
        value = policy[field]
        if type(value) is not int or not 1 <= value <= maximum:
            raise ValueError(f"cohort {field} must be positive and achievable (at most {maximum})")


def evaluate_cohort(row, packet):
    """Keep case outcomes intact; decide acceptance from their complete denominator."""
    if not isinstance(packet, dict) or not isinstance(packet.get("results"), list):
        return "blocked", "incomplete_case_set", {}
    trials = packet["results"]
    if not all(isinstance(trial, dict) for trial in trials):
        return "blocked", "incomplete_trial_identity", {}
    aggregate = packet.get("aggregate")
    if not isinstance(aggregate, dict):
        return "blocked", "incomplete_aggregate", {}
    identities = [trial.get("identity") for trial in trials]
    status, reason = validate_result_identities(row, identities, aggregate, "passed", None)
    if status != "passed":
        return status, reason, {}
    counts = Counter(str(trial.get("status")) for trial in trials)
    if set(counts) - {"passed", "failed", "blocked"}:
        return "blocked", "incomplete_case_outcome", {}
    if any(
        not isinstance(trial.get("failure_class"), str)
        for trial in trials
        if trial["status"] == "failed"
    ):
        return "blocked", "incomplete_failure_class", {}
    if any(aggregate.get(key, 0) != counts[key] for key in ("passed", "failed", "blocked")):
        return "blocked", "inconsistent_aggregate", {}
    breakdown = _cohort_breakdown(row["cohort_acceptance"], trials)
    if counts["blocked"]:
        return "blocked", "cohort_contains_blocked_cases", breakdown
    if any(
        trial.get("failure_class") not in BEHAVIOR_FAILURES
        for trial in trials
        if trial["status"] == "failed"
    ):
        return "failed", "cohort_nonbehavior_failure", breakdown
    return _threshold_verdict(row["cohort_acceptance"], breakdown)


def _cohort_breakdown(policy, trials):
    per_world = {}
    for trial in trials:
        world = trial["identity"]["world"]
        counts = per_world.setdefault(world, {"total": 0, "passed": 0, "failed": 0, "blocked": 0})
        counts["total"] += 1
        counts[trial["status"]] += 1
    return {
        "per_world": per_world,
        "reserved": {
            key: sum(per_world[world][key] for world in policy["reserved_worlds"])
            for key in ("total", "passed", "failed", "blocked")
        },
        "failure_classes": dict(
            Counter(trial["failure_class"] for trial in trials if trial["status"] == "failed")
        ),
    }


def _threshold_verdict(policy, breakdown):
    worlds = breakdown["per_world"]
    passed = sum(counts["passed"] for counts in worlds.values())
    total = sum(counts["total"] for counts in worlds.values())
    reserved = breakdown["reserved"]
    if any(counts["passed"] < policy["min_per_world"] for counts in worlds.values()):
        return "failed", "cohort_per_world_threshold_not_met", breakdown
    if reserved["passed"] < policy["min_reserved_passed"]:
        return "failed", "cohort_reserved_threshold_not_met", breakdown
    if passed < policy["min_passed"]:
        return "failed", "cohort_overall_threshold_not_met", breakdown
    return (
        "passed",
        f"cohort_thresholds_met: {passed}/{total} passed; {total - passed} failed; "
        f"reserved {reserved['passed']}/{reserved['total']}",
        breakdown,
    )
