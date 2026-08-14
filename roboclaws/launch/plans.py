"""Declarative launch plan types."""

from __future__ import annotations

from dataclasses import dataclass

from roboclaws.core.goals import GoalContract


@dataclass(frozen=True)
class LaunchPlan:
    """Resolved public surface/intent route before execution.

    Named canonical and implementation fields cross directly into the launch
    executor; no second command parser reconstructs this state.
    """

    surface: str
    intent: str
    preset: str | None
    world: str
    backend: str
    implementation_backend: str
    agent_engine: str
    provider_profile: str | None
    internal_runner_class: str
    dispatch_runner: str
    dispatch_target: str
    evidence_mode: str
    profile: str | None
    report: str | None
    prompt_id: str
    checker_id: str
    skill_name: str
    required_capabilities: tuple[str, ...]
    goal_contract: GoalContract
    scenario_setup: str | None
    relocation_count: int | None
    overrides: tuple[str, ...]
