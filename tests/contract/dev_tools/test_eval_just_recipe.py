from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[3]


def test_agent_eval_public_facade_routes_to_eval_cli() -> None:
    trace = _trace_agent_eval(
        "suite=smoke_regression",
        "budget=smoke",
        "stamp=trace",
        "agent_engine=openai-agents-sdk",
        "provider_profile=kimi-openai-chat",
        "live_execution=run",
        "live_timeout_s=30",
        "regrade_source=output/evals/household_world_cleanup_capability/source-run",
    )

    assert trace[:5] == ["cmd", ".venv/bin/python", "-m", "roboclaws.cli.main", "eval"]
    assert "suite=smoke_regression" in trace
    assert "budget=smoke" in trace
    assert "agent_engine=openai-agents-sdk" in trace
    assert "provider_profile=kimi-openai-chat" in trace
    assert "live_execution=run" in trace
    assert "live_timeout_s=30" in trace
    assert "regrade_source=output/evals/household_world_cleanup_capability/source-run" in trace


def test_agent_eval_public_facade_routes_promotion_cli() -> None:
    trace = _trace_agent_eval(
        "promote-regression",
        "eval_results=output/evals/demo/eval_results.json",
        "source_sample_id=cleanup.smoke_seed7",
        "regression_sample_id=regression.cleanup_demo",
    )

    assert trace[:5] == ["cmd", ".venv/bin/python", "-m", "roboclaws.cli.main", "eval"]
    assert "promote-regression" in trace
    assert "eval_results=output/evals/demo/eval_results.json" in trace
    assert "source_sample_id=cleanup.smoke_seed7" in trace
    assert "regression_sample_id=regression.cleanup_demo" in trace


def test_agent_eval_public_facade_routes_map_build_report_cli() -> None:
    trace = _trace_agent_eval(
        "map-build-report",
        "eval_results=output/evals/a/eval_results.json,output/evals/b/eval_results.json",
        "output_dir=output/evals/map-build-matrix-report",
    )

    assert trace[:5] == ["cmd", ".venv/bin/python", "-m", "roboclaws.cli.main", "eval"]
    assert "map-build-report" in trace
    assert "eval_results=output/evals/a/eval_results.json,output/evals/b/eval_results.json" in trace
    assert "output_dir=output/evals/map-build-matrix-report" in trace


def test_agent_eval_public_facade_routes_runtime_prior_select_cli() -> None:
    trace = _trace_agent_eval(
        "runtime-prior-select",
        "manifest=output/evals/runtime-prior-selection/manifest.json",
        "eval_results=output/evals/a/eval_results.json",
        "output_dir=output/evals/runtime-prior-selection",
    )

    assert trace[:5] == ["cmd", ".venv/bin/python", "-m", "roboclaws.cli.main", "eval"]
    assert "runtime-prior-select" in trace
    assert "manifest=output/evals/runtime-prior-selection/manifest.json" in trace
    assert "eval_results=output/evals/a/eval_results.json" in trace
    assert "output_dir=output/evals/runtime-prior-selection" in trace


def test_agent_eval_public_facade_routes_session_live_cli() -> None:
    trace = _trace_agent_eval(
        "session-live",
        "budget=smoke",
        "stamp=openai-agents-sdk-session-live-eval",
        "agent_engine=openai-agents-sdk",
        "provider_profile=minimax-responses",
        "live_execution=run",
    )

    assert trace[:5] == ["cmd", ".venv/bin/python", "-m", "roboclaws.cli.main", "eval"]
    assert "session-live" in trace
    assert "stamp=openai-agents-sdk-session-live-eval" in trace
    assert "agent_engine=openai-agents-sdk" in trace
    assert "provider_profile=minimax-responses" in trace
    assert "live_execution=run" in trace


def test_agent_eval_public_facade_routes_eval_harness_recommend() -> None:
    trace = _trace_agent_eval(
        "recommend",
        "plan=docs/plans/2026-06-15-eval-harness-skill-entrypoint.md",
        "budget=focused",
        "profile=baseline-refresh",
        "output_dir=output/eval-harness/trace",
    )

    assert trace[:5] == ["cmd", ".venv/bin/python", "-m", "roboclaws.cli.main", "eval"]
    assert "recommend" in trace
    assert "plan=docs/plans/2026-06-15-eval-harness-skill-entrypoint.md" in trace
    assert "budget=focused" in trace
    assert "profile=baseline-refresh" in trace
    assert "output_dir=output/eval-harness/trace" in trace


def test_agent_eval_public_facade_routes_eval_harness_execute() -> None:
    trace = _trace_agent_eval("execute", "since=origin/main", "budget=focused")

    assert trace[:5] == ["cmd", ".venv/bin/python", "-m", "roboclaws.cli.main", "eval"]
    assert "execute" in trace
    assert "since=origin/main" in trace
    assert "budget=focused" in trace


def test_agent_eval_public_facade_honors_container_python() -> None:
    binary = _just_bin()
    env = os.environ.copy()
    env["ROBOCLAWS_DEVTOOLS_PYTHON"] = "/opt/roboclaws/.venv/bin/python"
    result = subprocess.run(
        [binary, "--dry-run", "agent::eval", "execute", "since=origin/main"],
        cwd=REPO_ROOT,
        env=env,
        check=True,
        capture_output=True,
        text=True,
    )

    assert (result.stdout + result.stderr).startswith(
        "exec /opt/roboclaws/.venv/bin/python -m roboclaws.cli.main agent eval"
    )


def test_agent_eval_dispatch_honors_configured_python() -> None:
    trace = _trace_agent_eval("execute", "since=origin/main", python_bin=sys.executable)

    assert trace[:5] == ["cmd", sys.executable, "-m", "roboclaws.cli.main", "eval"]


def test_current_eval_docs_use_default_live_eval_budget() -> None:
    from roboclaws.evals import live_runtime

    current_docs = [
        REPO_ROOT / "docs" / "human" / "evaluation.md",
        REPO_ROOT / "evals" / "household_world" / "README.md",
    ]
    for path in current_docs:
        text = path.read_text(encoding="utf-8")
        assert "live_execution=run live_timeout_s=120" not in text
        assert f"{live_runtime.DEFAULT_LIVE_WALL_CLOCK_BUDGET_S:g}-second wall-clock budget" in text
        assert f"{live_runtime.DEFAULT_LIVE_STALL_TIMEOUT_S:g}-second" in text


def test_eval_harness_recommend_rejects_suite_override() -> None:
    python_bin = REPO_ROOT / ".venv" / "bin" / "python"
    if not python_bin.exists():
        python_bin = Path("python3")
    result = subprocess.run(
        [
            str(python_bin),
            "-m",
            "roboclaws.cli.main",
            "eval",
            "recommend",
            "suite=cleanup_capability",
        ],
        cwd=REPO_ROOT,
        check=False,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 2
    assert "recommend does not accept suite=<suite>" in result.stderr


def test_surface_cleanup_live_run_dir_reaches_molmo_impl() -> None:
    route, plan_trace = _trace_surface_run_with_plan(
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

    assert route[:5] == [
        "just",
        "molmo::household-world-impl",
        "openai-agents-live",
        "smoke",
        "7",
    ]
    assert route[-1] == "/tmp/roboclaws-eval-surface-test/seed-7"
    assert (
        "target=just agent::run household-world openai-agents-sdk smoke "
        "seed=7 output_dir=/tmp/roboclaws-eval-surface-test "
        "run_dir=/tmp/roboclaws-eval-surface-test/seed-7"
    ) in " ".join(plan_trace)
    assert "task_intent=cleanup" in " ".join(plan_trace)


def test_surface_live_smoke_uses_world_public_server_evidence_lane() -> None:
    recipe = (REPO_ROOT / "just" / "molmo.just").read_text(encoding="utf-8")

    assert 'implementation_evidence_lane="world-public-labels"' in recipe
    assert '--evidence-lane "$implementation_evidence_lane"' in recipe
    assert '--evidence-lane "$profile"' not in recipe
    assert '--checker-profile "$implementation_evidence_lane"' in recipe
    assert '--expect-profile "$implementation_evidence_lane"' in recipe


def _trace_agent_eval(*args: str, python_bin: str = "") -> list[str]:
    binary = _just_bin()
    env = os.environ.copy()
    env["ROBOCLAWS_JUST_TRACE"] = "1"
    if python_bin:
        env["ROBOCLAWS_DEVTOOLS_PYTHON"] = python_bin
    else:
        env.pop("ROBOCLAWS_DEVTOOLS_PYTHON", None)
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


def _trace_surface_run_with_plan(*args: str) -> tuple[list[str], list[str]]:
    binary = _just_bin()
    env = os.environ.copy()
    env["ROBOCLAWS_JUST_TRACE"] = "1"
    env["PATH"] = f"{Path(binary).parent}{os.pathsep}{env.get('PATH', '')}"
    result = subprocess.run(
        [binary, "run::surface", *args],
        cwd=REPO_ROOT,
        env=env,
        check=True,
        capture_output=True,
        text=True,
    )
    return result.stdout.strip().split("\t"), result.stderr.strip().split("\t")


def _just_bin() -> str:
    path = shutil.which("just")
    if path:
        return path
    local_path = Path.home() / ".local/bin" / "just"
    if local_path.exists():
        return str(local_path)
    pytest.skip("just binary is not available")
