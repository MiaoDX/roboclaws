"""Complete multiscene acceptance must preserve unsuccessful trial outcomes."""

import copy
from collections import Counter
from dataclasses import replace

import pytest

from roboclaws.evals.showcase import derive_row, validate_manifest
from roboclaws.evals.suite_loading import load_suite


@pytest.fixture
def cohort(monkeypatch):
    suite, samples = load_suite("cleanup_capability")
    samples = [
        replace(samples[0], sample_id=f"cleanup.scene{i}", world=f"molmospaces/test/{i}")
        for i in range(5)
    ]
    suite = replace(suite, sample_ids=tuple(sample.sample_id for sample in samples))
    monkeypatch.setattr("roboclaws.evals.suite_loading.load_suite", lambda _: (suite, samples))
    monkeypatch.setattr(
        "roboclaws.evals.showcase_acceptance.load_suite", lambda _: (suite, samples)
    )
    row = {
        "id": suite.suite_id,
        "suite": "cleanup_capability",
        "version": suite.version,
        "sample_ids": list(suite.sample_ids),
        "agent_engine": "openai-agents-sdk",
        "provider_profile": "minimax-responses",
        "seed": 7,
        "evidence_lane": "world-public-labels",
        "camera_labeler": "not_applicable",
        "budget": "focused",
        "timeout_s": 3600,
        "execution_timeout_s": 54030,
        "decision_call_budget": 100,
        "execution_mode": "manual_live_only",
        "cohort_acceptance": {
            "min_passed": 12,
            "min_per_world": 1,
            "reserved_worlds": [sample.world for sample in samples[-2:]],
            "min_reserved_passed": 5,
        },
    }
    trials = [
        {
            "status": "passed",
            "failure_class": "not_applicable",
            "identity": {
                **{
                    key: row[key]
                    for key in (
                        "agent_engine",
                        "provider_profile",
                        "evidence_lane",
                        "camera_labeler",
                    )
                },
                "suite_id": suite.suite_id,
                "suite_version": suite.version,
                "sample_id": sample.sample_id,
                "sample_version": sample.version,
                "world": sample.world,
                "backend": sample.backend,
                "seed": sample.seed,
                "repetition_index": repetition,
            },
        }
        for sample in samples
        for repetition in range(sample.trial_count)
    ]
    packet = {
        "aggregate": {"total": 15, "passed": 15, "failed": 0, "blocked": 0},
        "results": trials,
    }
    return row, packet


def fail_cases(packet, indices, *, status="failed", failure_class="private_goal_not_satisfied"):
    for index in indices:
        packet["results"][index].update(status=status, failure_class=failure_class)
    packet["aggregate"] = {
        "total": len(packet["results"]),
        **Counter(trial["status"] for trial in packet["results"]),
    }


def test_multitrial_row_requires_explicit_aggregate_runtime(cohort):
    row, _ = cohort
    row.pop("execution_timeout_s")
    with pytest.raises(ValueError, match="requires execution_timeout_s for 15 live trials"):
        validate_manifest({"schema": "roboclaws_showcase_manifest_v1", "rows": [row]})


@pytest.mark.parametrize("cap", [3630, 54029, True, float("inf")])
def test_aggregate_runtime_cannot_truncate_selected_trial_caps(cohort, cap):
    row, _ = cohort
    row["execution_timeout_s"] = cap
    with pytest.raises(ValueError, match="execution_timeout_s must be an integer >= 54030"):
        validate_manifest({"schema": "roboclaws_showcase_manifest_v1", "rows": [row]})


def test_execution_uses_aggregate_timeout_and_keeps_per_trial_cap(cohort, monkeypatch, tmp_path):
    import json
    from types import SimpleNamespace

    from roboclaws.evals.showcase import execute_manifest

    row, packet = cohort
    result_path = tmp_path / "eval_results.json"
    result_path.write_text(json.dumps(packet))
    calls = []

    def run(command, *, timeout_s):
        calls.append((command, timeout_s))
        return SimpleNamespace(
            returncode=0, stdout=json.dumps({"results": str(result_path)})
        ), False

    monkeypatch.setattr("roboclaws.evals.showcase.run_showcase_command", run)
    index = execute_manifest(
        {"schema": "roboclaws_showcase_manifest_v1", "rows": [row]},
        output_dir=tmp_path,
        live_execution="run",
    )
    assert len(calls) == 1
    assert calls[0][1] == 54030
    assert "live_timeout_s=3600" in calls[0][0]
    assert "live_retry_limit=0" in calls[0][0]
    assert index["attempts"][0]["state"] == "completed"


def test_accepts_threshold_without_relabeling_failed_trials(cohort):
    row, packet = cohort
    validate_manifest({"schema": "roboclaws_showcase_manifest_v1", "rows": [row]})
    fail_cases(packet, [0, 3, 12])
    before = copy.deepcopy(packet)
    result = derive_row(row, packet)
    assert result["status"] == "passed"
    assert "12/15 passed; 3 failed; reserved 5/6" in result["reason"]
    assert result["metrics"]["failed"] == 3
    assert result["cohort"]["failure_classes"] == {"private_goal_not_satisfied": 3}
    assert result["cohort"]["per_world"]["molmospaces/test/0"]["passed"] == 2
    assert packet == before


@pytest.mark.parametrize(
    "indices,reason",
    [([0, 1, 2], "per_world"), ([9, 12], "reserved"), ([0, 1, 3, 6], "overall")],
)
def test_each_threshold_is_required(cohort, indices, reason):
    row, packet = cohort
    fail_cases(packet, indices)
    result = derive_row(row, packet)
    assert result["status"] == "failed"
    assert result["reason"] == f"cohort_{reason}_threshold_not_met"


def test_blocked_case_cannot_be_an_allowed_failure(cohort):
    row, packet = cohort
    fail_cases(packet, [0], status="blocked", failure_class="environment_blocked")
    result = derive_row(row, packet)
    assert result["status"] == "blocked"
    assert result["cohort"]["per_world"]["molmospaces/test/0"]["blocked"] == 1


@pytest.mark.parametrize(
    "failure_class",
    [
        "private_truth_leak",
        "trajectory_policy_violation",
        "artifact_missing",
        "checker_validation_failed",
        "model_or_provider_unavailable",
    ],
)
def test_safety_and_infrastructure_failures_cannot_be_averaged_away(cohort, failure_class):
    row, packet = cohort
    fail_cases(packet, [0], failure_class=failure_class)
    assert derive_row(row, packet)["reason"] == "cohort_nonbehavior_failure"


@pytest.mark.parametrize(
    "corruption", ["missing", "duplicate", "version", "provider", "aggregate", "unrun"]
)
def test_complete_cohort_identity_and_counts_are_required(cohort, corruption):
    row, packet = cohort
    fail_cases(packet, [0])
    if corruption == "missing":
        packet["results"].pop()
        packet["aggregate"].update(total=14, passed=13)
    elif corruption == "duplicate":
        packet["results"][-1] = copy.deepcopy(packet["results"][1])
    elif corruption in {"version", "provider"}:
        field = "suite_version" if corruption == "version" else "provider_profile"
        packet["results"][0]["identity"][field] = "different"
    elif corruption == "aggregate":
        packet["aggregate"]["passed"] = 15
    else:
        packet["results"][0]["status"] = "not_run"
    assert derive_row(row, packet)["status"] != "passed"


@pytest.mark.parametrize(
    "field,value",
    [
        ("min_passed", 16),
        ("min_passed", True),
        ("min_per_world", 0),
        ("min_reserved_passed", 7),
        ("reserved_worlds", []),
        ("reserved_worlds", ["unknown"]),
        ("reserved_worlds", ["molmospaces/test/3"] * 2),
    ],
)
def test_rejects_invalid_or_impossible_policy(cohort, field, value):
    row, _ = cohort
    row["cohort_acceptance"][field] = value
    with pytest.raises(ValueError, match="cohort"):
        validate_manifest({"schema": "roboclaws_showcase_manifest_v1", "rows": [row]})


def test_small_gate_keeps_all_pass_requirement(cohort):
    row, packet = cohort
    row.pop("cohort_acceptance")
    fail_cases(packet, [0])
    assert derive_row(row, packet)["status"] == "failed"


@pytest.mark.parametrize("value", [None, [], {}])
def test_malformed_failure_class_blocks_without_crashing(cohort, value):
    row, packet = cohort
    fail_cases(packet, [0], failure_class=value)
    assert derive_row(row, packet)["reason"] == "incomplete_failure_class"
