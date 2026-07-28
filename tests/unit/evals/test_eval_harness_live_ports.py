from __future__ import annotations

import importlib.util
import os
import shutil
import subprocess
from pathlib import Path
from typing import Any

from pytest import MonkeyPatch

REPO_ROOT = Path(__file__).resolve().parents[3]
SELECTOR_PATH = REPO_ROOT / "skills" / "eval-harness" / "scripts" / "select_eval_harness.py"
RUNNER_PATH = REPO_ROOT / "skills" / "eval-harness" / "scripts" / "run_eval_harness.py"


def _load_module(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


selector = _load_module("eval_harness_port_selector_test", SELECTOR_PATH)
runner = _load_module("eval_harness_port_runner_test", RUNNER_PATH)


def _selected_rows(manifest: dict) -> dict[str, dict]:
    return {row["row_id"]: row for row in manifest["rows"] if row["selected"]}


def test_execute_assigns_isolated_mcp_port_to_live_rows(
    tmp_path: Path,
    monkeypatch: MonkeyPatch,
) -> None:
    captured: list[tuple[str, dict[str, str]]] = []
    monkeypatch.setattr(runner, "_row_blockers", lambda row, manifest: [])

    def fake_run(command: list[str], **kwargs: Any) -> Any:
        env = kwargs.get("env")
        assert isinstance(env, dict)
        captured.append((" ".join(command), env))

        class _Result:
            returncode = 0
            stdout = ""
            stderr = ""

        return _Result()

    monkeypatch.setattr(runner.subprocess, "run", fake_run)
    manifest = selector.build_eval_harness(
        mode="execute",
        budget="focused",
        changed_files=["roboclaws/agents/drivers/openai_agents_live.py"],
        output_dir=tmp_path,
    )

    runner._execute_harness(manifest)

    live_envs = [env for command, env in captured if "agent_engine=openai-agents-sdk" in command]
    assert live_envs
    assert all(env["ROBOCLAWS_EVAL_HARNESS_MCP_PORT"] != "18788" for env in live_envs)
    session_env = next(env for command, env in captured if "session-live" in command)
    assert (
        session_env["ROBOCLAWS_SESSION_LIVE_MCP_PORT"]
        == (session_env["ROBOCLAWS_EVAL_HARNESS_MCP_PORT"])
    )


def test_eval_harness_mcp_port_env_becomes_surface_default_port() -> None:
    trace = _trace_run_surface_with_env("19421")

    assert trace[:5] == [
        "just",
        "molmo::household-world-impl",
        "openai-agents-live",
        "world-public-labels",
        "7",
    ]
    assert trace[9] == "19421"
    assert "18788" not in trace


def _trace_run_surface_with_env(port: str) -> list[str]:
    binary = _just_bin()
    env = os.environ.copy()
    env["ROBOCLAWS_JUST_TRACE"] = "1"
    env["ROBOCLAWS_EVAL_HARNESS_MCP_PORT"] = port
    env["PATH"] = f"{Path(binary).parent}{os.pathsep}{env.get('PATH', '')}"
    result = subprocess.run(
        [
            binary,
            "run::surface",
            "surface=household-world",
            "world=molmospaces/val_0",
            "backend=mujoco",
            "preset=cleanup",
            "agent_engine=openai-agents-sdk",
            "provider_profile=codex-router-responses",
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


def _just_bin() -> str:
    path = shutil.which("just")
    if path:
        return path
    local_path = Path.home() / ".local/bin" / "just"
    assert local_path.exists(), "just binary is not available"
    return str(local_path)
