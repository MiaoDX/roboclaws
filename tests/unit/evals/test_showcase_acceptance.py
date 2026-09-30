"""Showcase acceptance must account for the exact requested cases."""

import copy
import json
from pathlib import Path

import pytest

from roboclaws.evals.showcase import derive_row
from roboclaws.evals.suite_loading import load_suite


@pytest.fixture
def cleanup_packet():
    manifest = json.loads(Path("config/showcase-manifest.json").read_text())
    row = next(row for row in manifest["rows"] if row["id"].endswith("cleanup_capability.minimax"))
    suite, samples = load_suite(row["suite"])
    sample = next(sample for sample in samples if sample.sample_id == row["sample_id"])
    identity = {
        **{
            field: row[field]
            for field in ("agent_engine", "provider_profile", "evidence_lane", "camera_labeler")
        },
        "suite_id": suite.suite_id,
        "suite_version": suite.version,
        "sample_id": sample.sample_id,
        "sample_version": sample.version,
        "seed": sample.seed,
        "world": sample.world,
        "backend": sample.backend,
        "repetition_index": row["repetition_index"],
    }
    return row, {"aggregate": {"total": 1, "passed": 1}, "results": [{"identity": identity}]}


def test_requested_case_passes(cleanup_packet):
    row, packet = cleanup_packet
    assert derive_row(row, packet)["status"] == "passed"


@pytest.mark.parametrize(
    "field,value",
    [
        ("sample_id", "another-case"),
        ("seed", 8),
        ("repetition_index", 1),
        ("world", "another-world"),
        ("suite_version", "old"),
        ("sample_version", "old"),
        ("suite_id", "another-suite"),
        ("backend", "another-backend"),
    ],
)
def test_wrong_case_cannot_pass(cleanup_packet, field, value):
    row, packet = cleanup_packet
    packet["results"][0]["identity"][field] = value
    result = derive_row(row, packet)
    assert result["status"] == "failed"
    assert result["reason"] == "showcase_case_identity_mismatch"


def test_duplicate_cannot_replace_missing_repetition(cleanup_packet):
    row, packet = cleanup_packet
    row.pop("repetition_index")
    packet["results"] *= 3
    packet["aggregate"] = {"total": 3, "passed": 3}
    assert derive_row(row, packet)["reason"] == "showcase_case_identity_mismatch"


def test_complete_aggregate_cannot_hide_missing_requested_cases(cleanup_packet):
    row, packet = cleanup_packet
    row.pop("repetition_index")
    result = derive_row(row, packet)
    assert result["status"] == "blocked"
    assert result["reason"] == "incomplete_case_set"


def test_all_requested_repetitions_pass(cleanup_packet):
    row, packet = cleanup_packet
    row.pop("repetition_index")
    _, samples = load_suite(row["suite"])
    count = next(sample.trial_count for sample in samples if sample.sample_id == row["sample_id"])
    template = packet["results"][0]
    packet["results"] = [copy.deepcopy(template) for _ in range(count)]
    for repetition, trial in enumerate(packet["results"]):
        trial["identity"]["repetition_index"] = repetition
    packet["aggregate"] = {"total": count, "passed": count}
    assert derive_row(row, packet)["status"] == "passed"


@pytest.mark.parametrize("identity", ["malformed", [1], True, 12])
def test_malformed_identity_is_blocked(cleanup_packet, identity):
    row, packet = cleanup_packet
    packet["results"][0]["identity"] = identity
    result = derive_row(row, packet)
    assert result["status"] == "blocked"
    assert result["reason"] == "incomplete_trial_identity"
