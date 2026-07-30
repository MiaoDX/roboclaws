"""Task intent declarations shared by launch and product runtimes."""

from __future__ import annotations

import os
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

HOUSEHOLD_SURFACE = "household-world"
HOUSEHOLD_INTENT_CLEANUP = "cleanup"
HOUSEHOLD_INTENT_MAP_BUILD = "map-build"
HOUSEHOLD_INTENT_OPEN_ENDED = "open-ended"
HOUSEHOLD_INTENTS = frozenset(
    {HOUSEHOLD_INTENT_CLEANUP, HOUSEHOLD_INTENT_MAP_BUILD, HOUSEHOLD_INTENT_OPEN_ENDED}
)


@dataclass(frozen=True)
class TaskIntentSpec:
    """Goal-type metadata inside one or more execution surfaces."""

    intent_id: str
    surface_ids: tuple[str, ...]
    supported_dispatch_runners: tuple[str, ...]
    dispatch_target: str
    prompt_id: str
    checker_id: str
    default_goal_scope: str
    done_readiness_policy: str
    checker_policy: str
    evaluation_policy: str
    skill_name: str
    required_capabilities: tuple[str, ...] = ()


GOAL_SCOPE_WHOLE_ROOM = "whole-room"
GOAL_SCOPE_PROMPT_SCOPED = "prompt-scoped"
GOAL_SCOPE_AGENT_DECLARED = "agent-declared"

TASK_INTENT_SPECS: dict[str, TaskIntentSpec] = {
    "cleanup": TaskIntentSpec(
        intent_id="cleanup",
        surface_ids=("household-world",),
        supported_dispatch_runners=(
            "direct",
            "mcp-smoke",
            "openai-agents-live",
        ),
        dispatch_target="household-world",
        prompt_id="household_cleanup",
        checker_id="cleanup_report",
        default_goal_scope=GOAL_SCOPE_WHOLE_ROOM,
        done_readiness_policy="cleanup_sweep_and_pending_candidates",
        checker_policy="cleanup_success",
        evaluation_policy="cleanup",
        skill_name="household-world",
        required_capabilities=(
            "household_world",
            "household_manipulation",
            "household_episode",
        ),
    ),
    "map-build": TaskIntentSpec(
        intent_id="map-build",
        surface_ids=("household-world",),
        supported_dispatch_runners=("direct", "openai-agents-live"),
        dispatch_target="household-world",
        prompt_id="map_build",
        checker_id="runtime_metric_map",
        default_goal_scope=GOAL_SCOPE_WHOLE_ROOM,
        done_readiness_policy="map_sweep",
        checker_policy="runtime_metric_map",
        evaluation_policy="map_build",
        skill_name="household-world",
        required_capabilities=("household_world", "household_episode"),
    ),
    "open-ended": TaskIntentSpec(
        intent_id="open-ended",
        surface_ids=("household-world",),
        supported_dispatch_runners=("mcp-smoke", "openai-agents-live"),
        dispatch_target="household-world",
        prompt_id="household_open_ended",
        checker_id="open_ended_report",
        default_goal_scope=GOAL_SCOPE_AGENT_DECLARED,
        done_readiness_policy="agent_declared_goal",
        checker_policy="open_ended_advisory",
        evaluation_policy="open_ended",
        skill_name="household-world",
        required_capabilities=(
            "household_world",
            "household_manipulation",
            "household_episode",
        ),
    ),
    "planner-proof": TaskIntentSpec(
        intent_id="planner-proof",
        surface_ids=("planner-proof",),
        supported_dispatch_runners=("direct", "mcp-smoke"),
        dispatch_target="planner-proof.planner-proof",
        prompt_id="molmo_planner_proof",
        checker_id="planner_proof_report",
        default_goal_scope=GOAL_SCOPE_AGENT_DECLARED,
        done_readiness_policy="planner_proof",
        checker_policy="planner_proof_report",
        evaluation_policy="planner_proof",
        skill_name="molmo-planner-proof",
        required_capabilities=("planner_proof",),
    ),
}


def intent_spec(intent_id: str) -> TaskIntentSpec:
    """Return an intent spec by id."""

    return TASK_INTENT_SPECS[intent_id]


def normalize_household_intent(value: str | None) -> str:
    normalized = str(value or "").strip().lower().replace("_", "-")
    if not normalized:
        return HOUSEHOLD_INTENT_CLEANUP
    if normalized in HOUSEHOLD_INTENTS:
        return normalized
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
