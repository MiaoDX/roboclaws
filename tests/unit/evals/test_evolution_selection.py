from __future__ import annotations

import pytest

from roboclaws.evals.evolution_contracts import Campaign
from roboclaws.evals.evolution_selection import run_sealed_holdout_once, select_training_winner
from tests.unit.evals.test_evolution_contracts import _campaign_payload


def _campaign() -> Campaign:
    payload = _campaign_payload()
    payload["selection"] = {
        "primary_objective": "quality",
        "direction": "maximize",
        "minimum_improvement": 0.1,
    }
    return Campaign.from_mapping(payload)


def _trial(pair_id: str, quality: float, **overrides: object) -> dict[str, object]:
    trial: dict[str, object] = {
        "pair_id": pair_id,
        "status": "passed",
        "skill_delivery_cell": "static-full",
        "quality_gates": {"privacy": True, "checker": True, "trajectory": True},
        "metrics": {"quality": quality, "tool_calls": 10, "tokens": 100},
    }
    trial.update(overrides)
    return trial


def test_quality_first_selection_rejects_neutral_and_gate_failure() -> None:
    campaign = _campaign()
    selection = select_training_winner(
        campaign,
        baseline_trials=[_trial("scene-1", 0.8), _trial("scene-2", 0.7)],
        candidate_trials={
            "neutral": [_trial("scene-1", 0.8), _trial("scene-2", 0.7)],
            "leaky": [
                _trial("scene-1", 1.0, quality_gates={"privacy": False}),
                _trial("scene-2", 1.0),
            ],
            "winner": [_trial("scene-1", 1.0), _trial("scene-2", 0.9)],
        },
    )
    assert selection["winner"]["candidate_id"] == "winner"
    assert selection["rejected"] == {
        "leaky": "authoritative_quality_gate_failed",
        "neutral": "minimum_improvement_not_met",
    }


def test_no_skill_negative_control_cannot_win() -> None:
    selection = select_training_winner(
        _campaign(),
        baseline_trials=[_trial("scene-1", 0.5)],
        candidate_trials={"no-skill": [_trial("scene-1", 1.0, skill_delivery_cell="no-skill")]},
    )
    assert selection["status"] == "no_improving_candidate"
    assert selection["holdout_allowed"] is False


@pytest.mark.parametrize(
    ("baseline", "reason"),
    [
        (
            _trial(
                "scene-1",
                0.0,
                status="blocked",
                metrics={"pass": 0.0},
                quality_gates={"runner": False},
            ),
            "baseline_execution_inconclusive",
        ),
        (
            _trial("scene-1", 0.0, metrics={"pass": 1.0}),
            "baseline_primary_objective_unavailable",
        ),
    ],
)
def test_inconclusive_baseline_writes_terminal_selection_packet(
    baseline: dict[str, object], reason: str
) -> None:
    selection = select_training_winner(
        _campaign(),
        baseline_trials=[baseline],
        candidate_trials={"candidate": [_trial("scene-1", 1.0)]},
    )

    assert selection["status"] == "inconclusive"
    assert selection["reason"] == reason
    assert selection["winner"] is None
    assert selection["holdout_allowed"] is False


def test_failed_behavior_baseline_remains_eligible_for_improvement() -> None:
    selection = select_training_winner(
        _campaign(),
        baseline_trials=[
            _trial(
                "scene-1",
                0.2,
                status="failed",
                failure_class="private_goal_not_satisfied",
                quality_gates={"checker": False},
            )
        ],
        candidate_trials={"candidate": [_trial("scene-1", 0.8)]},
    )

    assert selection["status"] == "winner_selected"
    assert selection["winner"]["candidate_id"] == "candidate"


def test_infrastructure_failed_baseline_is_inconclusive() -> None:
    selection = select_training_winner(
        _campaign(),
        baseline_trials=[
            _trial(
                "scene-1",
                0.2,
                status="failed",
                failure_class="artifact_missing",
                quality_gates={"artifacts": False},
            )
        ],
        candidate_trials={"candidate": [_trial("scene-1", 0.8)]},
    )

    assert selection["status"] == "inconclusive"
    assert selection["reason"] == "baseline_execution_inconclusive"
    assert selection["holdout_allowed"] is False


def test_holdout_runs_once_and_never_returns_feedback() -> None:
    calls: list[tuple[str, str]] = []

    def runner(candidate_id: str, sealed_ref: str) -> dict[str, object]:
        calls.append((candidate_id, sealed_ref))
        return {
            "status": "passed",
            "quality_gates": {"privacy": True, "checker": True},
            "minimum_improvement": {"passed": True, "value": 0.2},
            "private_detail": "not projected",
        }

    training = {
        "status": "winner_selected",
        "winner": {"candidate_id": "winner"},
    }
    result = run_sealed_holdout_once(_campaign(), training_selection=training, runner=runner)
    assert calls == [("winner", "maintainer-reference-1")]
    assert result["status"] == "accepted"
    assert result["optimizer_feedback_allowed"] is False
    assert "private_detail" not in result


@pytest.mark.parametrize("status", ["no_improving_candidate", "inconclusive"])
def test_holdout_cannot_run_without_one_winner(status: str) -> None:
    def runner(*_args: str) -> dict[str, object]:
        return {}

    with pytest.raises(ValueError, match="exactly one"):
        run_sealed_holdout_once(
            _campaign(), training_selection={"status": status, "winner": None}, runner=runner
        )
