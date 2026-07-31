from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest
from household_surface_trace import household_cleanup_args, household_map_build_args  # noqa: E402

REPO_ROOT = Path(__file__).resolve().parents[3]

CODING_AGENT_ENV = REPO_ROOT / "scripts" / "dev" / "coding_agent_env.sh"

HOUSEHOLD_AGENT_SERVER_MODULE = "roboclaws.cli.agent_server"

_TEST_DIR = Path(__file__).resolve().parent

if str(_TEST_DIR) not in sys.path:
    sys.path.insert(0, str(_TEST_DIR))


def just_bin() -> str:
    path = shutil.which("just")
    if path:
        return path
    local_path = Path.home() / ".local/bin" / "just"
    if local_path.exists():
        return str(local_path)
    pytest.skip("just binary is not available")


def just_summary() -> set[str]:
    result = subprocess.run(
        [just_bin(), "--summary"],
        cwd=REPO_ROOT,
        check=True,
        capture_output=True,
        text=True,
    )
    return set(result.stdout.split())


def trace_household_cleanup_run(
    agent_engine: str,
    evidence_lane: str = "",
    *overrides: str,
) -> list[str]:
    return trace_surface_run(*household_cleanup_args(agent_engine, evidence_lane, *overrides))


def trace_household_map_build_run(
    agent_engine: str,
    evidence_lane: str = "",
    *overrides: str,
) -> list[str]:
    return trace_surface_run(*household_map_build_args(agent_engine, evidence_lane, *overrides))


def agibot_dependency_overrides(tmp_path: Path) -> tuple[str, ...]:
    runner_script = tmp_path / "agibot_runner.py"
    runner_script.write_text("# synthetic optional-world runner\n", encoding="utf-8")
    map_dir = tmp_path / "agibot_map"
    map_dir.mkdir()
    return (
        f"runner_script={runner_script}",
        f"runner_python={sys.executable}",
        f"agibot_map_artifact_dir={map_dir}",
    )


def _run_just(recipe: str, *args: str) -> subprocess.CompletedProcess[str]:
    binary = just_bin()
    env = os.environ.copy()
    env["ROBOCLAWS_JUST_TRACE"] = "1"
    env["PATH"] = f"{Path(binary).parent}{os.pathsep}{env.get('PATH', '')}"
    return subprocess.run(
        [binary, recipe, *args],
        cwd=REPO_ROOT,
        env=env,
        check=True,
        capture_output=True,
        text=True,
    )


def trace_just(recipe: str, *args: str) -> list[str]:
    return _run_just(recipe, *args).stdout.strip().split("\t")


def trace_surface_run(*args: str) -> list[str]:
    return trace_just("run::surface", *args)


def trace_surface_run_with_plan(*args: str) -> tuple[list[str], list[str]]:
    result = _run_just("run::surface", *args)
    return result.stdout.strip().split("\t"), result.stderr.strip().split("\t")


def assert_household_map_build_run_fails(
    agent_engine: str,
    evidence_lane: str = "",
    *overrides: str,
) -> str:
    return assert_surface_run_fails(
        *household_map_build_args(agent_engine, evidence_lane, *overrides)
    )


def assert_surface_run_fails(*args: str) -> str:
    binary = just_bin()
    env = os.environ.copy()
    env["ROBOCLAWS_JUST_TRACE"] = "1"
    env["PATH"] = f"{Path(binary).parent}{os.pathsep}{env.get('PATH', '')}"
    result = subprocess.run(
        [binary, "run::surface", *args],
        cwd=REPO_ROOT,
        env=env,
        check=False,
        capture_output=True,
        text=True,
    )
    assert result.returncode != 0
    return result.stderr
