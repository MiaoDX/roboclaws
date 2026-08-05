"""Quality-first paired selection and sealed holdout rules for Eval Evolution."""

from __future__ import annotations

from collections.abc import Callable, Iterable
from typing import Any

from roboclaws.evals.evolution_contracts import Campaign

Trial = dict[str, Any]


def select_training_winner(
    campaign: Campaign,
    *,
    baseline_trials: Iterable[Trial],
    candidate_trials: dict[str, Iterable[Trial]],
) -> dict[str, Any]:
    baseline = _trials_by_pair(baseline_trials, label="baseline")
    eligible: list[dict[str, Any]] = []
    rejected: dict[str, str] = {}
    for candidate_id, raw_trials in candidate_trials.items():
        trials = _trials_by_pair(raw_trials, label=candidate_id)
        reason = _candidate_rejection_reason(campaign, baseline, trials)
        if reason:
            rejected[candidate_id] = reason
            continue
        improvement = _paired_improvement(campaign, baseline, trials)
        eligible.append(
            {
                "candidate_id": candidate_id,
                "improvement": improvement,
                "efficiency": _aggregate_efficiency(trials.values()),
            }
        )
    eligible.sort(key=_ranking_key)
    winner = eligible[0] if eligible else None
    return {
        "schema": "eval_evolution_training_selection_v1",
        "campaign_id": campaign.campaign_id,
        "status": "winner_selected" if winner else "no_improving_candidate",
        "winner": winner,
        "eligible": eligible,
        "rejected": rejected,
        "holdout_allowed": winner is not None,
    }


def run_sealed_holdout_once(
    campaign: Campaign,
    *,
    training_selection: dict[str, Any],
    runner: Callable[[str, str], dict[str, Any]],
) -> dict[str, Any]:
    winner = training_selection.get("winner")
    if training_selection.get("status") != "winner_selected" or not isinstance(winner, dict):
        raise ValueError("sealed holdout requires exactly one improving training winner")
    candidate_id = str(winner["candidate_id"])
    result = runner(candidate_id, campaign.sealed_holdout_ref)
    status = "accepted" if _holdout_passed(campaign, result) else "rejected"
    return {
        "schema": "eval_evolution_sealed_holdout_result_v1",
        "campaign_id": campaign.campaign_id,
        "candidate_id": candidate_id,
        "status": status,
        "quality_gates": dict(result.get("quality_gates") or {}),
        "minimum_improvement": dict(result.get("minimum_improvement") or {}),
        "terminal": True,
        "optimizer_feedback_allowed": False,
    }


def _trials_by_pair(trials: Iterable[Trial], *, label: str) -> dict[str, Trial]:
    paired: dict[str, Trial] = {}
    for trial in trials:
        pair_id = str(trial.get("pair_id") or "")
        if not pair_id or pair_id in paired:
            raise ValueError(f"{label} trials require unique non-empty pair_id")
        paired[pair_id] = dict(trial)
    if not paired:
        raise ValueError(f"{label} trials must not be empty")
    return paired


def _candidate_rejection_reason(
    campaign: Campaign, baseline: dict[str, Trial], candidate: dict[str, Trial]
) -> str:
    if baseline.keys() != candidate.keys():
        return "incomplete_paired_evidence"
    if any(str(trial.get("skill_delivery_cell")) == "no-skill" for trial in candidate.values()):
        return "negative_control_not_promotable"
    for trial in candidate.values():
        if trial.get("status") != "passed":
            return "authoritative_status_failed"
        gates = trial.get("quality_gates")
        if not isinstance(gates, dict) or not gates or not all(gates.values()):
            return "authoritative_quality_gate_failed"
    improvement = _paired_improvement(campaign, baseline, candidate)
    threshold = _minimum_improvement(campaign)
    if improvement < threshold:
        return "minimum_improvement_not_met"
    return ""


def _paired_improvement(
    campaign: Campaign, baseline: dict[str, Trial], candidate: dict[str, Trial]
) -> float:
    objective = str(campaign.selection.get("primary_objective") or "")
    if not objective:
        raise ValueError("selection.primary_objective is required")
    direction = str(campaign.selection.get("direction") or "maximize")
    baseline_mean = _metric_mean(baseline.values(), objective)
    candidate_mean = _metric_mean(candidate.values(), objective)
    if direction == "maximize":
        return candidate_mean - baseline_mean
    if direction == "minimize":
        return baseline_mean - candidate_mean
    raise ValueError("selection.direction must be maximize or minimize")


def _minimum_improvement(campaign: Campaign) -> float:
    value = campaign.selection.get("minimum_improvement")
    if not isinstance(value, (int, float)) or isinstance(value, bool) or value <= 0:
        raise ValueError("selection.minimum_improvement must be a positive number")
    return float(value)


def _metric_mean(trials: Iterable[Trial], objective: str) -> float:
    values: list[float] = []
    for trial in trials:
        metrics = trial.get("metrics")
        value = metrics.get(objective) if isinstance(metrics, dict) else None
        if not isinstance(value, (int, float)) or isinstance(value, bool):
            raise ValueError(f"trial metric {objective!r} must be numeric")
        values.append(float(value))
    return sum(values) / len(values)


def _aggregate_efficiency(trials: Iterable[Trial]) -> dict[str, float]:
    keys = ("model_calls", "tool_calls", "tokens", "cost_usd", "latency_s")
    totals = {key: 0.0 for key in keys}
    for trial in trials:
        metrics = trial.get("metrics") if isinstance(trial.get("metrics"), dict) else {}
        for key in keys:
            value = metrics.get(key, 0)
            if isinstance(value, (int, float)) and not isinstance(value, bool):
                totals[key] += float(value)
    return totals


def _ranking_key(candidate: dict[str, Any]) -> tuple[float, ...]:
    efficiency = candidate["efficiency"]
    return (
        -float(candidate["improvement"]),
        float(efficiency["model_calls"]),
        float(efficiency["tool_calls"]),
        float(efficiency["tokens"]),
        float(efficiency["cost_usd"]),
        float(efficiency["latency_s"]),
    )


def _holdout_passed(campaign: Campaign, result: dict[str, Any]) -> bool:
    gates = result.get("quality_gates")
    improvement = result.get("minimum_improvement")
    return bool(
        result.get("status") == "passed"
        and isinstance(gates, dict)
        and gates
        and all(gates.values())
        and isinstance(improvement, dict)
        and improvement.get("passed") is True
        and float(improvement.get("value", 0)) >= _minimum_improvement(campaign)
    )
