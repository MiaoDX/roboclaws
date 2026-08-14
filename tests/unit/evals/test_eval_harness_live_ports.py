from __future__ import annotations

import os
import subprocess
from pathlib import Path
from typing import Any

from pytest import MonkeyPatch

from roboclaws.evals.harness import runner, selector

REPO_ROOT = Path(__file__).resolve().parents[3]
REPO_PYTHON = REPO_ROOT / ".venv" / "bin" / "python"


def _selected_rows(manifest: dict) -> dict[str, dict]:
    return {row["row_id"]: row for row in manifest["rows"] if row["selected"]}


def test_execute_assigns_isolated_mcp_port_to_live_rows(
    tmp_path: Path,
    monkeypatch: MonkeyPatch,
) -> None:
    captured: list[tuple[str, dict[str, str]]] = []
    monkeypatch.setattr(runner, "_row_blockers", lambda row, manifest: [])

    class FakeProcess:
        returncode = 0

        def __init__(self, command: list[str], **kwargs: Any) -> None:
            env = kwargs.get("env")
            assert isinstance(env, dict)
            captured.append((" ".join(command), env))

        def communicate(self, timeout: float | None = None) -> tuple[str, str]:
            return "", ""

    monkeypatch.setattr(runner.local_execution.subprocess, "Popen", FakeProcess)
    manifest = selector.build_eval_harness(
        mode="execute",
        budget="focused",
        changed_files=["roboclaws/agents/drivers/openai_agents_live.py"],
        output_dir=tmp_path,
    )

    runner._execute_harness(manifest)

    live_envs = [env for command, env in captured if "agent_engine=openai-agents-sdk" in command]
    live_commands = [
        command for command, _env in captured if "agent_engine=openai-agents-sdk" in command
    ]
    assert live_envs
    assert all(
        command.startswith(".venv/bin/python -m roboclaws.evals.cli ") for command in live_commands
    )
    assert all(env["ROBOCLAWS_EVAL_HARNESS_MCP_PORT"] != "18788" for env in live_envs)
    session_env = next(env for command, env in captured if "session-live" in command)
    assert (
        session_env["ROBOCLAWS_SESSION_LIVE_MCP_PORT"]
        == (session_env["ROBOCLAWS_EVAL_HARNESS_MCP_PORT"])
    )


def test_eval_harness_mcp_port_env_becomes_surface_default_port() -> None:
    trace = _trace_run_surface_with_env("19421")

    assert trace[:4] == [
        "cmd",
        ".venv/bin/python",
        "-m",
        "roboclaws.agents.household_live_runner",
    ]
    port_index = trace.index("--port")
    assert trace[port_index + 1] == "19421"
    assert "--server-arg=19421" in trace
    assert "18788" not in trace


def _trace_run_surface_with_env(port: str) -> list[str]:
    env = os.environ.copy()
    env["ROBOCLAWS_JUST_TRACE"] = "1"
    env["ROBOCLAWS_EVAL_HARNESS_MCP_PORT"] = port
    result = subprocess.run(
        [
            str(REPO_PYTHON),
            "-m",
            "roboclaws.cli.main",
            "run",
            "surface",
            "surface=household-world",
            "world=molmospaces/procthor-10k-val/0",
            "backend=mujoco",
            "preset=cleanup",
            "agent_engine=openai-agents-sdk",
            "provider_profile=kimi-openai-chat",
            "evidence_lane=world-public-labels",
        ],
        cwd=REPO_ROOT,
        check=False,
        capture_output=True,
        text=True,
        env=env,
    )
    assert result.returncode == 0, result.stderr
    return result.stdout.strip().split("\t")
