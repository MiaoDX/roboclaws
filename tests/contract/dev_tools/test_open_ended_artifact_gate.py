from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

REPO_ROOT = Path(__file__).resolve().parents[3]
MOLMO_JUST = REPO_ROOT / "just" / "molmo.just"
LIVE_OPENAI_AGENTS_RUNNER = REPO_ROOT / "scripts/molmo_cleanup/run_live_openai_agents_cleanup.py"


def test_molmo_open_ended_recipe_uses_artifact_gate_before_cleanup_checker() -> None:
    text = MOLMO_JUST.read_text(encoding="utf-8")
    assert "roboclaws.launch.open_ended_artifacts" in text
    live_gate = text.index('if [[ "$open_ended_intent" == "true" ]]; then')
    live_artifact_gate = text.index("roboclaws.launch.open_ended_artifacts", live_gate)
    live_cleanup_checker = text.index(
        "scripts/molmo_cleanup/check_molmo_realworld_cleanup_result.py",
        live_gate,
    )
    root_gate = text.index('if [[ "$open_ended_intent" == "true" ]]; then', live_cleanup_checker)
    root_artifact_gate = text.index("roboclaws.launch.open_ended_artifacts", root_gate)
    root_cleanup_checker = text.index(
        "scripts/molmo_cleanup/check_molmo_realworld_cleanup_result.py",
        root_gate,
    )

    assert live_artifact_gate < live_cleanup_checker
    assert root_artifact_gate < root_cleanup_checker


def test_openai_agents_open_ended_uses_artifact_gate_not_cleanup_checker(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    module = _load_script_module(
        LIVE_OPENAI_AGENTS_RUNNER,
        "run_live_openai_agents_cleanup_custom_gate_test",
    )
    run_dir = tmp_path / "openai-agents"
    _write_open_ended_artifacts(run_dir)
    captured_commands: list[list[str]] = []

    def fake_run_and_tee(command, *, cwd, stdout_path, stderr_path, env, **_kwargs):
        captured_commands.append(command)
        stdout_path.write_text("checker ok\n", encoding="utf-8")
        return 0

    monkeypatch.setattr(module, "_run_and_tee", fake_run_and_tee)
    runner = module.LiveOpenAIAgentsCleanupRunner(_open_ended_runner_args(tmp_path, run_dir))
    runner._check_result()

    assert captured_commands == []


def _write_open_ended_artifacts(run_dir: Path) -> None:
    run_dir.mkdir()
    goal_contract = {
        "schema": "roboclaws_goal_contract_v1",
        "surface": "household-world",
        "intent": "open-ended",
        "goal_scope": "agent-declared",
        "normalized_goal": "find something useful to drink",
    }
    (run_dir / "goal_contract.json").write_text(json.dumps(goal_contract) + "\n")
    (run_dir / "report.html").write_text("<html>report</html>\n")
    (run_dir / "trace.jsonl").write_text('{"event": "response", "tool": "done"}\n')
    (run_dir / "run_result.json").write_text(
        json.dumps(
            {
                "task_intent": "open-ended",
                "goal_contract": goal_contract,
                "agent_completion_claim": {
                    "schema": "roboclaws_agent_completion_claim_v1",
                    "completion_summary": "found a drink candidate",
                },
                "artifacts": {"goal_contract": str(run_dir / "goal_contract.json")},
            }
        )
        + "\n"
    )


def _open_ended_runner_args(tmp_path: Path, run_dir: Path) -> SimpleNamespace:
    return SimpleNamespace(
        run_dir=run_dir,
        repo_root=REPO_ROOT,
        status_path=run_dir / "live_status.json",
        client_url="http://127.0.0.1:18788/mcp",
        host="127.0.0.1",
        port=18788,
        lock_path=tmp_path / "openai-agents.lock",
        server_startup_timeout_s=1.0,
        kickoff_prompt="custom prompt",
        backend="molmospaces_subprocess",
        run_id="household-world",
        intent="open-ended",
        policy="openai_agents_agent",
        task="我渴了，帮我找些解渴的东西",
        min_generated_mess_count="5",
        profile="camera-raw-fpv",
        checker_profile="world-public-labels",
        server_arg=[],
        checker_visual_arg=["--require-clean-agent-run"],
        provider_profile="codex-router-responses",
        model="gpt-5.5",
        max_turns=128,
        incomplete_turn_continuation_attempts=0,
        cache_tools_list=True,
    )


def _load_script_module(path: Path, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module
