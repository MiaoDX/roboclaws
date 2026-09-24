"""Pure, privacy-bounded pre-call context reconstruction."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from roboclaws.agents.task_state import Checkpoint


@dataclass(frozen=True)
class ContextBudgetPolicy:
    hard_limit_tokens: int
    expected_output_tokens: int = 1024
    safety_reserve_tokens: int = 256

    def __post_init__(self) -> None:
        if (
            self.hard_limit_tokens <= 0
            or self.expected_output_tokens < 0
            or self.safety_reserve_tokens < 0
        ):
            raise ValueError("budget limits must be positive and reserves non-negative")


@dataclass(frozen=True)
class ContextAssemblyResult:
    items: list[Any]
    estimated_input_tokens: int
    expected_output_tokens: int
    safety_reserve_tokens: int
    hard_limit_tokens: int
    admitted: bool


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


def _serialized_state(critical: dict[str, Any]) -> str:
    """Serialize snapshot state as model-message text.

    Model inputs accept only supported roles carrying text content, so the
    snapshot travels as compact JSON under the system role instead of as a raw
    mapping under a ``state`` role the SDK and provider reject.
    """
    return json.dumps(critical, sort_keys=True, separators=(",", ":"), default=str)


def assemble_context(
    checkpoint: Checkpoint,
    *,
    fixed_instructions: Any = None,
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
    items.append({"role": "system", "content": _serialized_state(critical)})
    raw_count = len(recent_raw or [])
    raw_start = len(items)
    items.extend(recent_raw or [])
    total = sum(estimate_tokens(item) for item in items)
    reserve = policy.expected_output_tokens + policy.safety_reserve_tokens
    while total + reserve > policy.hard_limit_tokens and raw_count:
        raw_count -= _evict_oldest_raw_bundle(items, raw_start)
        total = sum(estimate_tokens(item) for item in items)
    return ContextAssemblyResult(
        items,
        total,
        policy.expected_output_tokens,
        policy.safety_reserve_tokens,
        policy.hard_limit_tokens,
        total + reserve <= policy.hard_limit_tokens,
    )


def _evict_oldest_raw_bundle(items: list[Any], raw_start: int) -> int:
    """Evict one oldest context unit without orphaning a tool response."""
    candidate = items[raw_start]
    if isinstance(candidate, dict):
        call_id = str(candidate.get("call_id") or "")
        if call_id:
            indexes = [
                index
                for index in range(raw_start, len(items))
                if isinstance(items[index], dict)
                and str(items[index].get("call_id") or "") == call_id
            ]
            for index in reversed(indexes):
                items.pop(index)
            return len(indexes)
    items.pop(raw_start)
    return 1
