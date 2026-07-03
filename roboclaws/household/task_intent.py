"""Shared household task intent helpers."""

from __future__ import annotations

import os
from collections.abc import Mapping
from typing import Any

HOUSEHOLD_SURFACE = "household-world"
HOUSEHOLD_INTENT_CLEANUP = "cleanup"
HOUSEHOLD_INTENT_MAP_BUILD = "map-build"
HOUSEHOLD_INTENT_OPEN_ENDED = "open-ended"
HOUSEHOLD_INTENTS = frozenset(
    {HOUSEHOLD_INTENT_CLEANUP, HOUSEHOLD_INTENT_MAP_BUILD, HOUSEHOLD_INTENT_OPEN_ENDED}
)


def normalize_household_intent(value: str | None) -> str:
    """Normalize the first-class household intent.

    Current runtime semantics use explicit ``intent=...`` values.
    """

    normalized = str(value or "").strip().lower().replace("_", "-")
    if not normalized:
        return HOUSEHOLD_INTENT_CLEANUP
    if normalized == HOUSEHOLD_INTENT_OPEN_ENDED:
        return HOUSEHOLD_INTENT_OPEN_ENDED
    if normalized == HOUSEHOLD_INTENT_MAP_BUILD:
        return HOUSEHOLD_INTENT_MAP_BUILD
    if normalized == HOUSEHOLD_INTENT_CLEANUP:
        return HOUSEHOLD_INTENT_CLEANUP
    expected = ", ".join(sorted(HOUSEHOLD_INTENTS))
    raise ValueError(f"unsupported household intent {value!r} (expected one of: {expected})")


def household_intent_from_goal_contract(goal_contract: Any | None, *, fallback: str = "") -> str:
    if goal_contract is None:
        return normalize_household_intent(fallback)
    return normalize_household_intent(str(getattr(goal_contract, "intent", "") or fallback))


def household_runtime_intent(goal_contract: Any | None, intent: str | None) -> str:
    return household_intent_from_goal_contract(goal_contract, fallback=str(intent or ""))


def household_intent_from_args(
    args: Any,
    *,
    env: Mapping[str, str] | None = None,
    fallback: str = HOUSEHOLD_INTENT_CLEANUP,
) -> str:
    env = os.environ if env is None else env
    return normalize_household_intent(
        str(getattr(args, "intent", "") or env.get("ROBOCLAWS_TASK_INTENT", "") or fallback)
    )


def household_task_name(*, surface: str | None = None, intent: str | None = None) -> str:
    normalize_household_intent(intent)
    return str(surface or HOUSEHOLD_SURFACE)


def household_task_identity(
    *, surface: str | None = None, intent: str | None = None
) -> dict[str, str]:
    task_intent = normalize_household_intent(intent)
    task_surface = str(surface or HOUSEHOLD_SURFACE)
    return {
        "task_name": task_surface,
        "task_surface": task_surface,
        "task_intent": task_intent,
    }


def household_task_name_from_args(args: Any, *, env: Mapping[str, str] | None = None) -> str:
    return household_task_name(
        surface=str(getattr(args, "task_surface", "") or HOUSEHOLD_SURFACE),
        intent=household_intent_from_args(args, env=env),
    )


def household_task_identity_from_contract(
    contract: Any,
    *,
    surface: str | None,
    fallback_intent: str,
) -> tuple[str, str]:
    task_intent = normalize_household_intent(getattr(contract, "task_intent", fallback_intent))
    return task_intent, household_task_name(surface=surface, intent=task_intent)


def household_intent_is_open_ended(value: str | None) -> bool:
    return normalize_household_intent(value) == HOUSEHOLD_INTENT_OPEN_ENDED
