"""Eval-layer acceptance checks for showcase result packets."""

from typing import Any

from roboclaws.evals.suite_loading import load_suite


def aggregate_status(results, aggregate, missing_reason):
    if results is None:
        status = "not_run" if missing_reason == "live_execution_not_requested" else "blocked"
        reason = missing_reason
    elif aggregate.get("blocked", 0) and not aggregate.get("failed", 0):
        status, reason = (
            "blocked",
            next(iter(aggregate.get("failure_classes") or {"unavailable": 1})),
        )
    elif aggregate.get("failed", 0):
        status, reason = (
            "failed",
            next(iter(aggregate.get("failure_classes", {"evaluation_failed": 1}))),
        )
    elif not aggregate.get("total") or aggregate.get("passed", 0) != aggregate.get("total"):
        status, reason = "blocked", "incomplete_attempt"
    else:
        status, reason = "passed", None
    return status, reason


def _result_identity_mismatch(row: dict[str, Any], identity: dict[str, Any]) -> bool:
    if not isinstance(identity, dict) or not identity:
        return False
    return any(
        row.get(field) and identity.get(field) != row[field]
        for field in ("agent_engine", "provider_profile")
    ) or any(identity.get(field) != row.get(field) for field in ("evidence_lane", "camera_labeler"))


def validate_result_identities(row, identities, aggregate, status, reason):
    if any(_result_identity_mismatch(row, item) for item in identities):
        return "failed", "showcase_identity_mismatch"
    if not row.get("provider_profile") or status != "passed":
        return status, reason
    if len(identities) != aggregate.get("total") or not all(
        isinstance(item, dict) and item for item in identities
    ):
        return "blocked", "incomplete_trial_identity"
    return _validate_case_identities(row, identities)


def _validate_case_identities(row, identities):
    suite, samples = load_suite(row["suite"])
    samples = [sample for sample in samples if sample.sample_id in row["sample_ids"]]
    expected = {}
    for sample in samples:
        repetitions = (
            [row["repetition_index"]]
            if row.get("repetition_index") is not None
            else range(sample.trial_count)
        )
        for repetition in repetitions:
            expected[(sample.sample_id, repetition)] = {
                "suite_id": suite.suite_id,
                "suite_version": row["version"],
                "sample_version": sample.version,
                "seed": sample.seed,
                "world": sample.world,
                "backend": sample.backend,
            }
    observed = set()
    for identity in identities:
        sample_id, repetition = identity.get("sample_id"), identity.get("repetition_index")
        if not isinstance(sample_id, str) or type(repetition) is not int:
            return "blocked", "incomplete_trial_identity"
        key = (sample_id, repetition)
        if key not in expected or key in observed:
            return "failed", "showcase_case_identity_mismatch"
        if any(identity.get(field) != value for field, value in expected[key].items()):
            return "failed", "showcase_case_identity_mismatch"
        observed.add(key)
    if observed != set(expected):
        return "blocked", "incomplete_case_set"
    return "passed", None
