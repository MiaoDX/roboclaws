"""CLI adapter for the public surface runner."""

from __future__ import annotations

import os
import sys
from typing import NoReturn

from roboclaws.launch.catalog import LaunchError, resolve_surface_launch
from roboclaws.launch.executor import execute_launch_plan
from roboclaws.launch.plans import LaunchPlan
from roboclaws.launch.runners import export_env_from_overrides


def print_launch_trace(plan: LaunchPlan) -> None:
    """Emit a structured trace for the resolved launch plan."""

    fields = (
        "launch-plan",
        f"surface={plan.surface}",
        f"world={plan.world}",
        f"backend={plan.backend}",
        f"intent={plan.intent}",
        f"preset={plan.preset or ''}",
        f"agent_engine={plan.agent_engine}",
        f"provider_profile={plan.provider_profile or ''}",
        f"runner_class={plan.internal_runner_class}",
        f"dispatch_runner={plan.dispatch_runner}",
        f"dispatch_target={plan.dispatch_target}",
        f"mode={plan.evidence_mode}",
        f"profile={plan.profile or ''}",
        f"report={plan.report or ''}",
        f"prompt={plan.prompt_id}",
        f"checker={plan.checker_id}",
        f"skill={plan.skill_name}",
        f"goal={plan.goal_contract.normalized_goal}",
        "target=roboclaws.launch.executor",
    )
    print("\t".join(fields), file=sys.stderr)


def die(message: str) -> NoReturn:
    print(f"error: {message}", file=sys.stderr)
    raise SystemExit(1)


def surface_run_main(args: list[str]) -> int:
    """Resolve and execute ``roboclaws run surface`` arguments."""

    return _execute_plan(resolve_surface_launch, args)


def _execute_plan(resolver, args: list[str]) -> int:  # noqa: ANN001
    try:
        plan = resolver(args)
    except LaunchError as exc:
        print(f"error: {exc}", file=sys.stderr)
        if exc.hint:
            print(f"       {exc.hint}", file=sys.stderr)
        return 1

    if os.environ.get("ROBOCLAWS_JUST_TRACE") == "1":
        print_launch_trace(plan)
    os.environ.update(export_env_from_overrides(plan.overrides))
    return execute_launch_plan(plan)
