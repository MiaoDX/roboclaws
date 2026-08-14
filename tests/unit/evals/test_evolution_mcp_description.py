from __future__ import annotations

import pytest

from roboclaws.evals.evolution_mcp_description import (
    snapshot_public_mcp_profile,
    validate_description_candidate,
)
from roboclaws.mcp.profiles import HOUSEHOLD_WORLD_PROFILE


def test_description_candidate_allows_only_public_summary_delta() -> None:
    baseline = snapshot_public_mcp_profile(HOUSEHOLD_WORLD_PROFILE)
    candidate = baseline.to_target()
    candidate["parent_sha256"] = baseline.sha256
    candidate["tools"] = {name: dict(value) for name, value in baseline.tools.items()}
    candidate["tools"]["observe"]["summary"] += " Return current public observations."

    report = validate_description_candidate(baseline, candidate)

    assert report["changed_tools"] == ["observe"]
    assert report["token_delta"]["delta"] > 0


@pytest.mark.parametrize("mutation", ["add", "immutable", "private", "stale"])
def test_description_candidate_rejects_unsafe_delta(mutation: str) -> None:
    baseline = snapshot_public_mcp_profile(HOUSEHOLD_WORLD_PROFILE)
    candidate = baseline.to_target()
    candidate["parent_sha256"] = baseline.sha256
    candidate["tools"] = {name: dict(value) for name, value in baseline.tools.items()}
    if mutation == "add":
        candidate["tools"]["new_tool"] = dict(candidate["tools"]["observe"])
    elif mutation == "immutable":
        candidate["tools"]["observe"]["family"] = "manipulation"
    elif mutation == "private":
        candidate["tools"]["observe"]["summary"] = "Read hidden grader fixture data."
    else:
        candidate["parent_sha256"] = "0" * 64

    with pytest.raises(ValueError):
        validate_description_candidate(baseline, candidate)
