from types import SimpleNamespace

import pytest

from roboclaws.household.household_episode_prior_policy import (
    _open_ended_prior_stop,
    _open_ended_prior_waypoint_ids,
)
from roboclaws.household.target_query import resolve_target_query


def _candidate(index: int, *, observed: bool = False) -> dict:
    return {
        "label": f"Generated exploration candidate {index}",
        "candidate_type": "generated_exploration_candidate",
        "waypoint_id": f"room_{index + 1}_inspection",
        "target_actionability_status": "actionable" if observed else "needs_observe",
    }


@pytest.mark.parametrize(
    "query",
    [
        "请去 Generated exploration candidate 5 所在区域看一下。",
        "Find candidate 5",
        "Inspect candidate5",
        "Go to room_6_inspection",
    ],
)
def test_numbered_query_does_not_prefer_observed_wrong_target(query: str) -> None:
    candidates = [_candidate(1, observed=True), _candidate(4), _candidate(5), _candidate(15)]
    result = resolve_target_query({"target_candidates": candidates}, query)
    assert result["status"] == "matched"
    assert {r["waypoint_id"] for r in result["matches"]} == {"room_6_inspection"}


def test_unknown_numbered_candidate_cannot_fall_back_to_another_number() -> None:
    result = resolve_target_query({"target_candidates": [_candidate(1)]}, "candidate 99")
    assert result["status"] == "not_found"
    assert result["candidate_count"] == 1


def test_numbered_public_alias_is_an_identity_constraint() -> None:
    candidates = [
        {**_candidate(1, observed=True), "aliases": ["sector 2"]},
        {**_candidate(5), "aliases": ["sector 12"]},
    ]
    result = resolve_target_query({"target_candidates": candidates}, "Inspect sector-12")
    assert result["match_count"] == 1
    assert result["best_match"]["waypoint_id"] == "room_6_inspection"


def test_unnumbered_query_keeps_all_public_candidates() -> None:
    result = resolve_target_query(
        {"target_candidates": [_candidate(1), _candidate(5)]}, "exploration candidate"
    )
    assert result["match_count"] == 2


@pytest.mark.parametrize(
    "prompt",
    [
        "请去 Generated exploration candidate 5 所在区域看一下。",
        "Find candidate 5",
        "Inspect candidate5",
        "Go to room_6_inspection",
    ],
)
def test_prior_candidate_five_does_not_stop_after_candidate_one(prompt: str) -> None:
    waypoints = _open_ended_prior_waypoint_ids(
        runtime_map_prior={"public_semantic_anchors": [_candidate(i) for i in range(1, 8)]},
        task_prompt=prompt,
        goal_contract=SimpleNamespace(
            intent="open-ended", normalized_goal=prompt, raw_prompt=prompt
        ),
        run_metadata_overrides={"eval_sample_id": "open_ended.room4_anchor_seed7"},
    )
    assert waypoints == ("room_6_inspection",)
    stop = _open_ended_prior_stop(waypoints)
    assert stop is not None
    assert not stop(SimpleNamespace(_observed_waypoint_ids={"room_2_inspection"}))
    assert stop(SimpleNamespace(_observed_waypoint_ids={"room_6_inspection"}))
