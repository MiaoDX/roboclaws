"""Run-wide token reservations at the SDK provider boundary (agent engine layer)."""

from __future__ import annotations

import fcntl
import json
from contextlib import contextmanager
from pathlib import Path
from typing import Any

from roboclaws.agents.drivers.openai_agents_budget import OpenAIAgentsBudgetExceededError
from roboclaws.agents.live_status import LiveAgentFailure
from roboclaws.core.provider_catalog import maybe_resolve_model

TOTAL_TOKEN_BUDGET_ENV = "ROBOCLAWS_EVAL_TOTAL_TOKEN_BUDGET"


def total_token_budget(value: Any) -> int | None:
    if value is None or value == "":
        return None
    if isinstance(value, str) and value.isdecimal():
        value = int(value)
    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        raise ValueError("total_token_budget must be a positive integer")
    return value


class ProviderTokenBudget:
    """Persist reservations so retries, cancellation and continuation cannot reset spend.

    Reserve a native context window for input and another for output before each
    request. This intentionally conservative bound avoids treating chars/4 as an
    exact tokenizer. Unknown usage remains charged at the reserved amount. The
    guarantee depends on the provider honoring its declared model limits.
    """

    def __init__(self, run_dir: Path, config: dict[str, Any]) -> None:
        self.limit = total_token_budget(config.get("total_token_budget"))
        self.path = run_dir / "provider_token_budget.json"
        self.identity: dict[str, Any] = {}
        self.reservation = 0
        self._initialized = False
        if self.limit is None:
            if self.path.exists():
                raise ValueError("cannot disable total_token_budget on an existing budgeted run")
            return
        request_model = config.get("request_model") or config.get("model")
        spec = maybe_resolve_model(request_model)
        if spec is None or not spec.context_window_tokens:
            raise ValueError("total_token_budget requires a model with a declared context window")
        racing = config.get("model_racing_observability") or {}
        if racing.get("enabled") and int(racing.get("arm_count") or 1) > 1:
            raise ValueError("total_token_budget requires single-arm model execution")
        self.reservation = 2 * spec.context_window_tokens
        self.identity = {
            "schema": "agent_sdk_total_token_budget_v1",
            "limit_tokens": self.limit,
            "provider_profile": config.get("provider_profile"),
            "model": config.get("model"),
            "request_model": request_model,
            "reservation_tokens_per_request": self.reservation,
            "reservation_basis": "native_context_window_for_each_of_input_and_output",
        }
        if config.get("attempt_index", 0) and not self.path.exists():
            raise ValueError("continuation is missing its provider token budget ledger")
        with self._ledger():
            pass
        self._initialized = True

    def _validate(self, state: Any) -> None:
        if not isinstance(state, dict) or not isinstance(state.get("requests"), list):
            raise ValueError("provider token budget ledger is malformed")
        if any(state.get(k) != v for k, v in self.identity.items()):
            raise ValueError("provider token budget identity changed within a run")
        for row in state["requests"]:
            if not isinstance(row, dict):
                raise ValueError("provider token budget ledger request is malformed")
            charge = row.get("charged_tokens")
            if type(charge) is not int or charge < 0:
                raise ValueError("provider token budget ledger charge is malformed")
            if row.get("accounting") == "reserved_usage_unknown":
                valid = charge == self.reservation and "usage" not in row
            elif row.get("accounting") == "provider_reported":
                counts = _usage_counts(row.get("usage"))
                bounded = charge <= self.reservation or state.get("failure_reason") == (
                    "provider_token_reservation_exceeded"
                )
                valid = bounded and counts is not None and charge == sum(counts.values())
            else:
                valid = False
            if not valid:
                raise ValueError("provider token budget ledger accounting is malformed")
        used = sum(r["charged_tokens"] for r in state["requests"])
        if state.get("charged_tokens") != used or state.get("remaining_tokens") != max(
            0, self.limit - used
        ):
            raise ValueError("provider token budget ledger totals are inconsistent")

    @contextmanager
    def _ledger(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.path.with_suffix(".lock").open("a") as lock:
            fcntl.flock(lock, fcntl.LOCK_EX)
            if self.path.exists():
                state = json.loads(self.path.read_text(encoding="utf-8"))
                self._validate(state)
            else:
                if self._initialized:
                    raise ValueError("provider token budget ledger disappeared within a run")
                state = {**self.identity, "requests": []}
            try:
                yield state
            finally:
                state["charged_tokens"] = sum(r["charged_tokens"] for r in state["requests"])
                state["remaining_tokens"] = max(0, self.limit - state["charged_tokens"])
                temp = self.path.with_suffix(".tmp")
                temp.write_text(json.dumps(state, indent=2) + "\n", encoding="utf-8")
                temp.replace(self.path)

    def reserve(self) -> int | None:
        if self.limit is None:
            if self.path.exists():
                raise ValueError("cannot disable total_token_budget on an existing budgeted run")
            return None
        with self._ledger() as state:
            used = sum(r["charged_tokens"] for r in state["requests"])
            if state.get("failure_reason"):
                self._fail(state["failure_reason"], used=used)
            if used + self.reservation > self.limit:
                state["failure_reason"] = "provider_total_token_budget_exhausted"
                self._fail("provider_total_token_budget_exhausted", used=used)
            index = len(state["requests"])
            state["requests"].append(
                {"charged_tokens": self.reservation, "accounting": "reserved_usage_unknown"}
            )
            return index

    def settle(self, index: int | None, usage: Any) -> None:
        if index is None:
            return
        counts = _usage_counts(usage)
        with self._ledger() as state:
            if type(index) is not int or not 0 <= index < len(state["requests"]):
                raise ValueError("provider token reservation index is invalid")
            row = state["requests"][index]
            if row["accounting"] != "reserved_usage_unknown":
                raise ValueError("provider token reservation was already settled")
            if counts is None:
                state["failure_reason"] = "provider_token_usage_unavailable"
                self._fail("provider_token_usage_unavailable")
            actual = sum(counts.values())
            row.update(charged_tokens=actual, accounting="provider_reported", usage=counts)
            if actual > self.reservation:
                state["failure_reason"] = "provider_token_reservation_exceeded"
                self._fail("provider_token_reservation_exceeded", reported_tokens=actual)

    def _fail(self, reason: str, **detail: Any) -> None:
        raise OpenAIAgentsBudgetExceededError(
            LiveAgentFailure(
                reason,
                retryable=False,
                resume_available=False,
                detail=json.dumps({**self.identity, **detail}, sort_keys=True),
            )
        )


def _usage_counts(usage: Any) -> dict[str, int] | None:
    if hasattr(usage, "model_dump"):
        usage = usage.model_dump()
    if not isinstance(usage, dict):
        usage = vars(usage) if hasattr(usage, "__dict__") else {}
    counts = {key: usage.get(key) for key in ("input_tokens", "output_tokens")}
    if any(type(n) is not int or n < 0 for n in counts.values()):
        return None
    # The SDK's empty Usage object defaults to zero/zero when telemetry is absent.
    return counts if counts["input_tokens"] > 0 else None
