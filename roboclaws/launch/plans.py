"""Declarative launch plan types."""

from __future__ import annotations

from dataclasses import dataclass

from roboclaws.launch.goals import GoalContract


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
    mcp_server_id: str
    required_capabilities: tuple[str, ...]
    required_artifacts: tuple[str, ...]
    goal_contract: GoalContract
    evaluation_id: str
    evaluation_hard_gates: tuple[str, ...]
    evaluation_intent_gates: tuple[str, ...]
    completion_claim_required: bool
    supported_reports: tuple[str, ...]
    supported_profiles: tuple[str, ...]
    overrides: tuple[str, ...]
