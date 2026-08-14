"""Intent declarations for public launch surfaces."""

from __future__ import annotations

from dataclasses import dataclass


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
            "openclaw",
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
