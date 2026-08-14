from __future__ import annotations

import os
import subprocess
from pathlib import Path

from tests.contract.dev_tools.task_agent_just_recipes_support import (
    REPO_ROOT,
    just_bin,
    trace_surface_run_with_plan,
)

REPO_PYTHON = str(REPO_ROOT / ".venv" / "bin" / "python")


def test_agent_eval_routes_to_eval_cli_with_unchanged_arguments() -> None:
    args = (
        "suite=smoke_regression",
        "budget=smoke",
        "agent_engine=openai-agents-sdk",
        "provider_profile=kimi-openai-chat",
        "live_execution=run",
        "regrade_source=output/evals/household_world_cleanup_capability/source-run",
    )

    assert _trace_agent_eval(*args) == [
        "cmd",
        REPO_PYTHON,
        "-m",
        "roboclaws.evals.cli",
        *args,
    ]


def test_agent_eval_routes_evolution_commands_without_a_second_facade() -> None:
    args = (
        "evolve",
        "campaign=campaigns/skill-smoke.json",
        "live_execution=blocked",
    )

    assert _trace_agent_eval(*args) == [
        "cmd",
        REPO_PYTHON,
        "-m",
        "roboclaws.evals.cli",
        *args,
    ]


def test_surface_cleanup_live_run_dir_reaches_sdk_package_owner() -> None:
    route, plan_trace = trace_surface_run_with_plan(
        "surface=household-world",
        "preset=cleanup",
        "agent_engine=openai-agents-sdk",
        "provider_profile=kimi-openai-chat",
        "evidence_lane=world-public-labels",
        "seed=7",
        "output_dir=/tmp/roboclaws-eval-surface-test",
        "run_dir=/tmp/roboclaws-eval-surface-test/seed-7",
        "run_preset=smoke",
    )

    assert route[:4] == [
        "cmd",
        ".venv/bin/python",
        "-m",
        "roboclaws.agents.household_live_runner",
    ]
    assert route[route.index("--run-dir") + 1] == "/tmp/roboclaws-eval-surface-test/seed-7"
    assert "target=roboclaws.launch.executor" in plan_trace
    assert "intent=cleanup" in plan_trace


def _trace_agent_eval(*args: str) -> list[str]:
    binary = just_bin()
    env = os.environ.copy()
    env["ROBOCLAWS_JUST_TRACE"] = "1"
    env["PATH"] = f"{Path(binary).parent}{os.pathsep}{env.get('PATH', '')}"
    result = subprocess.run(
        [binary, "agent::eval", *args],
        cwd=REPO_ROOT,
        env=env,
        check=True,
        capture_output=True,
        text=True,
    )
    return result.stdout.strip().split("\t")
