"""Campaign-wide provider budget accounting for Eval Evolution."""

from __future__ import annotations

import json
import time
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any

from roboclaws.agents.evolution_optimizer import OptimizerOutcome
from roboclaws.core.provider_catalog import resolve_model
from roboclaws.evals.evolution_contracts import Campaign


class CampaignBudgetExceeded(RuntimeError):
    def __init__(self, reason: str, usage: dict[str, Any]) -> None:
        super().__init__(reason)
        self.reason = reason
        self.usage = usage


@dataclass
class CampaignBudgetLedger:
    campaign: Campaign
    started_at: float
    live_trials: int = 0
    reserved_live_attempts: int = 0
    tokens: float = 0.0
    cost_usd: float = 0.0
    reserved_tokens: float = 0.0
    reserved_cost_usd: float = 0.0
    pending_tokens: float = 0.0
    pending_cost_usd: float = 0.0

    def campaign_for_optimizer(self) -> Campaign:
        if float(self.campaign.budgets["optimizer_turns"]) < 1:
            self._raise("optimizer_turns_exhausted")
        if float(self.campaign.budgets["candidates"]) < 1:
            self._raise("candidates_exhausted")
        if float(self.campaign.budgets["provider_concurrency"]) < 1:
            self._raise("provider_concurrency_exhausted")
        remaining_wall = self._remaining("wall_time_s", self.elapsed_wall_time_s)
        timeout_s = min(float(self.campaign.budgets["timeout_s"]), remaining_wall)
        if timeout_s <= 0:
            self._raise("timeout_s_exhausted")
        token_limit = float(self.campaign.budgets["optimizer_call_tokens"])
        cost_limit = float(self.campaign.budgets["optimizer_call_cost_usd"])
        self._reserve_provider_capacity(tokens=token_limit, cost_usd=cost_limit)
        return replace(
            self.campaign,
            budgets={
                **self.campaign.budgets,
                "tokens": token_limit,
                "cost_usd": cost_limit,
                "timeout_s": timeout_s,
            },
        )

    def record_optimizer(self, optimizer: OptimizerOutcome) -> None:
        tokens, cost_usd = _usage_values(
            optimizer.usage,
            model=str(optimizer.identity.get("model") or self.campaign.optimizer["model"]),
        )
        if tokens is None:
            self._raise("token_usage_evidence_unavailable")
        if cost_usd is None:
            self._raise("cost_usage_evidence_unavailable")
        self._finish_provider_reservation(tokens=tokens, cost_usd=cost_usd)

    def reserve_suite(self, trial_count: int, *, retry_limit: int = 0) -> dict[str, float]:
        if trial_count < 1:
            raise ValueError("campaign suite must reserve at least one live trial")
        if retry_limit not in {0, 1}:
            raise ValueError("campaign retry_limit must be 0 or 1")
        if self.reserved_live_attempts:
            raise RuntimeError("campaign suite attempt reservation is already active")
        attempt_capacity = trial_count * (retry_limit + 1)
        self._require_live_capacity(attempt_capacity)
        remaining_wall = self._remaining("wall_time_s", self.elapsed_wall_time_s)
        timeout_s = min(
            float(self.campaign.budgets["timeout_s"]),
            remaining_wall / trial_count,
        )
        attempt_tokens = float(self.campaign.budgets["robot_attempt_tokens"])
        attempt_cost_usd = float(self.campaign.budgets["robot_attempt_cost_usd"])
        self._reserve_provider_capacity(
            tokens=attempt_tokens * attempt_capacity,
            cost_usd=attempt_cost_usd * attempt_capacity,
        )
        self.reserved_live_attempts = attempt_capacity
        return {
            "timeout_s": timeout_s,
            "attempt_tokens": attempt_tokens,
            "attempt_cost_usd": attempt_cost_usd,
        }

    def campaign_for_unbounded_matrix(self) -> Campaign:
        attempt_capacity = int(float(self.campaign.budgets["live_trials"])) - self.live_trials
        self._require_live_capacity(attempt_capacity)
        attempt_tokens = float(self.campaign.budgets["robot_attempt_tokens"])
        attempt_cost_usd = float(self.campaign.budgets["robot_attempt_cost_usd"])
        token_limit = attempt_tokens * attempt_capacity
        cost_limit = attempt_cost_usd * attempt_capacity
        self._reserve_provider_capacity(tokens=token_limit, cost_usd=cost_limit)
        self.reserved_live_attempts = attempt_capacity
        return replace(
            self.campaign,
            budgets={
                **self.campaign.budgets,
                "tokens": token_limit,
                "cost_usd": cost_limit,
            },
        )

    def record_reserved_result(self, result: dict[str, Any]) -> None:
        self.live_trials += 1
        if self.live_trials > float(self.campaign.budgets["live_trials"]):
            self._raise("live_trials_exhausted")
        self._record_pending_result_usage(
            [result],
            require_evidence=True,
            per_result_tokens=float(self.campaign.budgets["robot_attempt_tokens"]),
            per_result_cost_usd=float(self.campaign.budgets["robot_attempt_cost_usd"]),
        )

    def record_reserved_suite(
        self,
        results: list[dict[str, Any]],
        *,
        trial_count: int,
        observed_count: int,
    ) -> None:
        if len(results) != trial_count:
            self._raise("suite_result_count_mismatch")
        if observed_count == 0:
            self.live_trials += len(results)
            self._record_pending_result_usage(results, require_evidence=True)
        elif observed_count != len(results):
            self._raise("suite_result_observer_mismatch")
        if self.live_trials > float(self.campaign.budgets["live_trials"]):
            self._raise("live_trials_exhausted")
        self._finish_provider_reservation(
            tokens=self.pending_tokens,
            cost_usd=self.pending_cost_usd,
        )
        self.reserved_live_attempts = 0

    def record_unbounded_matrix(self, trials: list[dict[str, Any]]) -> None:
        self.live_trials += len(trials)
        if self.live_trials > float(self.campaign.budgets["live_trials"]):
            self._raise("live_trials_exhausted")
        self._record_pending_result_usage(trials, require_evidence=False)
        self._finish_provider_reservation(
            tokens=self.pending_tokens,
            cost_usd=self.pending_cost_usd,
        )
        self.reserved_live_attempts = 0

    @property
    def elapsed_wall_time_s(self) -> float:
        return max(0.0, time.monotonic() - self.started_at)

    def packet(self) -> dict[str, Any]:
        return {
            "ceilings": {
                key: self.campaign.budgets[key]
                for key in (
                    "live_trials",
                    "provider_concurrency",
                    "tokens",
                    "cost_usd",
                    "wall_time_s",
                )
            },
            "used": {
                "live_trials": self.live_trials,
                "provider_concurrency": 1 if self.live_trials or self.reserved_live_attempts else 0,
                "tokens": self.tokens,
                "cost_usd": self.cost_usd,
                "wall_time_s": self.elapsed_wall_time_s,
            },
            "reserved": {
                "tokens": self.reserved_tokens,
                "cost_usd": self.reserved_cost_usd,
            },
            "pending": {
                "tokens": self.pending_tokens,
                "cost_usd": self.pending_cost_usd,
            },
        }

    def _require_live_capacity(self, trial_count: int) -> None:
        if trial_count < 1:
            self._raise("live_trials_exhausted")
        if float(self.campaign.budgets["provider_concurrency"]) < 1:
            self._raise("provider_concurrency_exhausted")
        if self.live_trials + self.reserved_live_attempts + trial_count > float(
            self.campaign.budgets["live_trials"]
        ):
            self._raise("live_trials_exhausted")
        if self.elapsed_wall_time_s >= float(self.campaign.budgets["wall_time_s"]):
            self._raise("wall_time_s_exhausted")
        if float(self.campaign.budgets["timeout_s"]) <= 0:
            self._raise("timeout_s_exhausted")

    def _record_pending_result_usage(
        self,
        results: list[dict[str, Any]],
        *,
        require_evidence: bool,
        per_result_tokens: float | None = None,
        per_result_cost_usd: float | None = None,
    ) -> None:
        for result in results:
            if _has_unaccounted_retry_usage(result):
                self._raise("retry_usage_evidence_unavailable")
            tokens, cost_usd = _result_usage(result, campaign=self.campaign)
            if require_evidence and tokens is None:
                self._raise("token_usage_evidence_unavailable")
            if require_evidence and cost_usd is None:
                self._raise("cost_usage_evidence_unavailable")
            if per_result_tokens is not None and tokens is not None and tokens > per_result_tokens:
                self._raise("tokens_exhausted")
            if (
                per_result_cost_usd is not None
                and cost_usd is not None
                and cost_usd > per_result_cost_usd
            ):
                self._raise("cost_usd_exhausted")
            self.pending_tokens += tokens or 0.0
            self.pending_cost_usd += cost_usd or 0.0
        if self.pending_tokens > self.reserved_tokens:
            self._raise("tokens_exhausted")
        if self.pending_cost_usd > self.reserved_cost_usd:
            self._raise("cost_usd_exhausted")

    def _reserve_provider_capacity(self, *, tokens: float, cost_usd: float) -> None:
        if self.reserved_tokens or self.reserved_cost_usd:
            raise RuntimeError("campaign provider budget reservation is already active")
        if tokens <= 0 or self.tokens + tokens > float(self.campaign.budgets["tokens"]):
            self._raise("tokens_exhausted")
        if cost_usd <= 0 or self.cost_usd + cost_usd > float(self.campaign.budgets["cost_usd"]):
            self._raise("cost_usd_exhausted")
        self.reserved_tokens = tokens
        self.reserved_cost_usd = cost_usd
        self.pending_tokens = 0.0
        self.pending_cost_usd = 0.0

    def _finish_provider_reservation(self, *, tokens: float, cost_usd: float) -> None:
        token_limit = self.reserved_tokens
        cost_limit = self.reserved_cost_usd
        self.tokens += tokens
        self.cost_usd += cost_usd
        self.reserved_tokens = 0.0
        self.reserved_cost_usd = 0.0
        self.pending_tokens = 0.0
        self.pending_cost_usd = 0.0
        if tokens > token_limit:
            self._raise("tokens_exhausted")
        if cost_usd > cost_limit:
            self._raise("cost_usd_exhausted")
        self._check_recorded_usage()

    def _check_recorded_usage(self) -> None:
        if self.tokens > float(self.campaign.budgets["tokens"]):
            self._raise("tokens_exhausted")
        if self.cost_usd > float(self.campaign.budgets["cost_usd"]):
            self._raise("cost_usd_exhausted")
        if self.elapsed_wall_time_s > float(self.campaign.budgets["wall_time_s"]):
            self._raise("wall_time_s_exhausted")

    def _remaining(self, key: str, used: float) -> float:
        remaining = float(self.campaign.budgets[key]) - used
        if remaining <= 0:
            self._raise(f"{key}_exhausted")
        return remaining

    def _raise(self, reason: str) -> None:
        raise CampaignBudgetExceeded(reason, self.packet())


def _result_usage(
    result: dict[str, Any], *, campaign: Campaign
) -> tuple[float | None, float | None]:
    metrics = result.get("metrics") if isinstance(result.get("metrics"), dict) else {}
    tokens, cost_usd = _usage_values(metrics, model=str(campaign.robot["model"]))
    if tokens is not None and cost_usd is not None:
        return tokens, cost_usd
    timing = _result_live_timing(result)
    context = (
        timing.get("context_metrics") if isinstance(timing.get("context_metrics"), dict) else {}
    )
    timing_tokens, timing_cost_usd = _usage_values(
        context,
        model=str(timing.get("model") or campaign.robot["model"]),
    )
    return tokens if tokens is not None else timing_tokens, (
        cost_usd if cost_usd is not None else timing_cost_usd
    )


def _has_unaccounted_retry_usage(result: dict[str, Any]) -> bool:
    """Fail closed when a retried trial has no exact failed-attempt usage ledger."""
    artifacts = result.get("artifacts") if isinstance(result.get("artifacts"), dict) else {}
    attempts_ref = artifacts.get("live_trial_attempts")
    if not attempts_ref:
        return False
    try:
        payload = json.loads(Path(str(attempts_ref)).read_text(encoding="utf-8"))
    except (OSError, TypeError, ValueError, json.JSONDecodeError):
        return True
    attempts = payload.get("attempts") if isinstance(payload, dict) else None
    if not isinstance(attempts, list) or not attempts:
        return True
    return any(
        not isinstance(attempt, dict) or str(attempt.get("status") or "") != "passed"
        for attempt in attempts
    )


def _usage_values(payload: dict[str, Any], *, model: str) -> tuple[float | None, float | None]:
    tokens = _first_number(payload, ("tokens", "total_tokens"))
    input_tokens = _first_number(payload, ("input_tokens", "total_input_tokens"))
    output_tokens = _first_number(payload, ("output_tokens", "total_output_tokens"))
    if tokens is None and (input_tokens is not None or output_tokens is not None):
        tokens = (input_tokens or 0.0) + (output_tokens or 0.0)
    cost_usd = _first_number(payload, ("cost_usd", "total_cost_usd"))
    if cost_usd is None and (input_tokens is not None or output_tokens is not None):
        cost_usd = _estimated_model_cost(
            model,
            input_tokens=input_tokens or 0.0,
            output_tokens=output_tokens or 0.0,
        )
    return tokens, cost_usd


def _result_live_timing(result: dict[str, Any]) -> dict[str, Any]:
    artifacts = result.get("artifacts") if isinstance(result.get("artifacts"), dict) else {}
    timing_ref = artifacts.get("live_timing")
    if not timing_ref:
        run_dir = artifacts.get("run_dir")
        timing_ref = Path(str(run_dir)) / "live_timing.json" if run_dir else None
    if timing_ref is None:
        return {}
    try:
        payload = json.loads(Path(str(timing_ref)).read_text(encoding="utf-8"))
    except (OSError, ValueError, json.JSONDecodeError):
        return {}
    return payload if isinstance(payload, dict) else {}


def _estimated_model_cost(model: str, *, input_tokens: float, output_tokens: float) -> float | None:
    try:
        rates = resolve_model(model).cost_per_m
    except KeyError:
        return None
    input_rate = rates.get("input")
    output_rate = rates.get("output")
    if input_rate is None or output_rate is None:
        return None
    return (input_tokens * input_rate + output_tokens * output_rate) / 1_000_000


def _first_number(payload: dict[str, Any], keys: tuple[str, ...]) -> float | None:
    for key in keys:
        value = payload.get(key)
        if isinstance(value, (int, float)) and not isinstance(value, bool):
            return float(value)
    return None
