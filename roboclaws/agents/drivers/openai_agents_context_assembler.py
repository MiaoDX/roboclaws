"""Pure, privacy-bounded pre-call context reconstruction."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

from roboclaws.agents.task_state import Checkpoint


@dataclass(frozen=True)
class ContextBudgetPolicy:
    hard_limit_tokens: int
    soft_limit_tokens: int | None = None
    expected_output_tokens: int = 1024
    safety_reserve_tokens: int = 256
    estimator: Callable[[Any], int] | None = None

    def __post_init__(self) -> None:
        if (
            self.hard_limit_tokens <= 0
            or self.expected_output_tokens < 0
            or self.safety_reserve_tokens < 0
        ):
            raise ValueError("budget limits must be positive and reserves non-negative")
        soft = (
            self.soft_limit_tokens if self.soft_limit_tokens is not None else self.hard_limit_tokens
        )
        if soft <= 0 or soft > self.hard_limit_tokens:
            raise ValueError("context_soft_limit_tokens must be <= context_hard_limit_tokens")

    @property
    def soft_limit(self) -> int:
        return self.soft_limit_tokens or self.hard_limit_tokens


@dataclass(frozen=True)
class ContextAssemblyResult:
    items: list[Any]
    estimated_input_tokens: int
    expected_output_tokens: int
    safety_reserve_tokens: int
    hard_limit_tokens: int
    reconstruction_requested: bool
    eviction_occurred: bool
    admitted: bool
    evicted: tuple[str, ...] = ()


def estimate_tokens(value: Any) -> int:
    """Conservative dependency-free estimate (JSON bytes at four chars/token)."""
    text = (
        value
        if isinstance(value, str)
        else json.dumps(value, sort_keys=True, default=str, separators=(",", ":"))
    )
    return max(1, (len(text) + 3) // 4)


def load_checkpoint(path: str | Path) -> Checkpoint:
    return Checkpoint.from_json(Path(path).read_text(encoding="utf-8"))


def assemble_context(
    checkpoint: Checkpoint,
    *,
    fixed_instructions: Any = None,
    subgoal_evidence: list[Any] | None = None,
    optional_retrieval: list[Any] | None = None,
    recent_raw: list[Any] | None = None,
    policy: ContextBudgetPolicy,
) -> ContextAssemblyResult:
    snapshot = checkpoint.snapshot.to_dict()
    critical = {
        k: snapshot.get(k)
        for k in (
            "task",
            "intent",
            "pose",
            "waypoint",
            "objects",
            "action_outcomes",
            "safety",
            "completion",
            "evidence",
            "revision",
        )
    }
    items: list[Any] = []
    if fixed_instructions is not None:
        items.append({"role": "system", "content": fixed_instructions})
    items.append({"role": "state", "content": critical})
    items.extend(subgoal_evidence or [])
    retrieval_start = len(items)
    retrieval_count = len(optional_retrieval or [])
    items.extend(optional_retrieval or [])
    raw_count = len(recent_raw or [])
    raw_start = len(items)
    items.extend(recent_raw or [])
    estimator = policy.estimator or estimate_tokens
    total = sum(estimator(item) for item in items)
    evicted: list[str] = []
    reserve = policy.expected_output_tokens + policy.safety_reserve_tokens
    while total + reserve > policy.hard_limit_tokens and retrieval_count:
        items.pop(retrieval_start + retrieval_count - 1)
        retrieval_count -= 1
        raw_start -= 1
        evicted.append("optional_retrieval")
        total = sum(estimator(item) for item in items)
    while total + reserve > policy.hard_limit_tokens and raw_count:
        items.pop(raw_start)
        evicted.append("oldest_raw_overlap")
        raw_count -= 1
        total = sum(estimator(item) for item in items)
    return ContextAssemblyResult(
        items,
        total,
        policy.expected_output_tokens,
        policy.safety_reserve_tokens,
        policy.hard_limit_tokens,
        total > policy.soft_limit,
        bool(evicted),
        total + reserve <= policy.hard_limit_tokens,
        tuple(evicted),
    )
