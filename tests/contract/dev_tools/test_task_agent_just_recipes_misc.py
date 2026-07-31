from __future__ import annotations

import json
import os
import re
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

from roboclaws.core.evaluation import checker_flags_for_household_intent
from tests.contract.dev_tools.task_agent_just_recipes_support import (
    AGENT_JUST,
    CODING_AGENT_ENV,
    JUST_DIR,
    LIVE_OPENAI_AGENTS_LIFECYCLE,
    LIVE_OPENAI_AGENTS_RUNNER,
    MOLMO_JUST,
    REPO_ROOT,
    clean_code_agent_env,
    just_bin,
    load_script_module,
)


def test_agent_eval_recommend_writes_eval_harness_manifest(tmp_path: Path) -> None:
    binary = just_bin()
    env = os.environ.copy()
    env["PATH"] = f"{Path(binary).parent}{os.pathsep}{env.get('PATH', '')}"
    output_dir = tmp_path / "eval-harness"
    result = subprocess.run(
        [
            binary,
            "agent::eval",
            "recommend",
            f"output_dir={output_dir}",
            "changed_file=roboclaws/agents/drivers/openai_agents_live.py",
            "budget=focused",
        ],
        cwd=REPO_ROOT,
        env=env,
        check=True,
        capture_output=True,
        text=True,
    )

    assert f"eval harness manifest: {output_dir / 'eval_harness.json'}" in result.stdout
    manifest = json.loads((output_dir / "eval_harness.json").read_text(encoding="utf-8"))
    assert manifest["schema"] == "roboclaws_eval_harness_manifest_v1"
    selected_row_ids = {row["row_id"] for row in manifest["rows"] if row["selected"]}
    assert "openai-agents-sdk-open-task-live-eval" in selected_row_ids
    assert (output_dir / "eval_harness.md").exists()
    assert (output_dir / "eval_harness.html").exists()


def test_old_codex_cleanup_harness_routes_are_unsupported() -> None:
    binary = just_bin()
    env = os.environ.copy()
    env["PATH"] = f"{Path(binary).parent}{os.pathsep}{env.get('PATH', '')}"

    agent_result = subprocess.run(
        [binary, "agent::harness", "codex-cleanup-harness8", "dry-run"],
        cwd=REPO_ROOT,
        env=env,
        capture_output=True,
        text=True,
    )
    molmo_result = subprocess.run(
        [binary, "molmo::codex-harness8", "dry-run"],
        cwd=REPO_ROOT,
        env=env,
        capture_output=True,
        text=True,
    )

    assert agent_result.returncode != 0
    assert "unsupported harness target 'codex-cleanup-harness8'" in agent_result.stderr
    assert molmo_result.returncode != 0


def test_agent_harness_no_longer_advertises_agent_validation() -> None:
    agent_text = AGENT_JUST.read_text(encoding="utf-8")
    harness_text = (JUST_DIR / "harness.just").read_text(encoding="utf-8")
    molmo_text = MOLMO_JUST.read_text(encoding="utf-8")

    assert "agent-validation" not in agent_text
    assert "agent-validation" not in harness_text
    assert re.search(r"^eval \*overrides:", agent_text, re.MULTILINE)
    assert "codex-cleanup-harness8" not in agent_text
    assert "codex-cleanup-harness8" not in harness_text
    assert "codex-harness8" not in molmo_text


def test_household_checker_flags_are_generated_from_intent_policy() -> None:
    cleanup_flags = checker_flags_for_household_intent(
        intent_id="cleanup",
        profile="world-public-labels",
        min_generated_mess_count="5",
    )
    open_flags = checker_flags_for_household_intent(
        intent_id="open-ended",
        profile="world-public-labels",
        min_generated_mess_count="5",
    )
    map_flags = checker_flags_for_household_intent(
        intent_id="map-build",
        profile="world-public-labels",
        min_generated_mess_count="5",
    )

    for flags in (cleanup_flags, open_flags, map_flags):
        assert "--require-goal-contract" in flags
        assert "--require-completion-claim" in flags
    assert "--require-clean-agent-run" in cleanup_flags
    assert "--allow-partial-cleanup" not in cleanup_flags
    assert "--require-clean-agent-run" not in open_flags
    assert "--allow-partial-cleanup" not in open_flags
    assert "--require-runtime-metric-map" in map_flags
    assert "--allow-partial-cleanup" in map_flags


def test_openai_agents_runner_script_uses_runtime_contract_and_checker() -> None:
    runner_text = LIVE_OPENAI_AGENTS_RUNNER.read_text(encoding="utf-8")
    lifecycle_text = LIVE_OPENAI_AGENTS_LIFECYCLE.read_text(encoding="utf-8")

    assert "LiveOpenAIAgentsHouseholdRunner" in runner_text
    assert "OpenAIAgentsLiveRuntime" in lifecycle_text
    assert "household_server_argv" in lifecycle_text
    assert 'CHECKER_MODULE = "roboclaws.household.cleanup_validation_cli"' in lifecycle_text
    assert "CHECKER_SCRIPT" not in lifecycle_text


def test_openai_agents_cleanup_checker_policy_uses_checker_profile(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    module = load_script_module(
        LIVE_OPENAI_AGENTS_LIFECYCLE,
        "household_live_lifecycle_checker_profile_test",
    )
    run_dir = tmp_path / "openai-agents"
    run_dir.mkdir()
    (run_dir / "run_result.json").write_text("{}\n", encoding="utf-8")
    captured_commands: list[list[str]] = []

    def fake_run_and_tee(command, *, cwd, stdout_path, stderr_path, env, **_kwargs):
        captured_commands.append(command)
        stdout_path.write_text("checker ok\n", encoding="utf-8")
        return 0

    monkeypatch.setattr(module.household_live_driver, "run_and_tee", fake_run_and_tee)
    args = SimpleNamespace(
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
        intent="cleanup",
        policy="openai_agents_agent",
        task="帮我收拾这个房间",
        min_generated_mess_count="5",
        profile="smoke",
        checker_profile="world-public-labels",
        server_arg=[],
        checker_visual_arg=[],
        provider_profile="kimi-openai-chat",
        model="kimi-k2.7-code",
        max_turns=128,
        incomplete_turn_continuation_attempts=0,
        cache_tools_list=True,
    )

    runner = module.LiveOpenAIAgentsHouseholdRunner(args)
    runner._check_result()

    assert captured_commands
    checker_command = captured_commands[0]
    assert checker_command[checker_command.index("--expect-profile") + 1] == ("world-public-labels")
    assert "--require-clean-agent-run" in checker_command
    assert "--require-waypoint-honesty" in checker_command
    assert "--require-real-robot-alignment" in checker_command
    assert checker_command[checker_command.index("--min-semantic-accepted-count") + 1] == "5"
    assert checker_command[checker_command.index("--min-sweep-coverage") + 1] == "1.0"


def test_coding_agent_env_shell_profile_facts_match_python_registry() -> None:
    env = clean_code_agent_env()
    env["ROBOCLAWS_HELPER"] = str(CODING_AGENT_ENV)
    result = subprocess.run(
        [
            "bash",
            "-c",
            """
            set -euo pipefail
            source "$ROBOCLAWS_HELPER"
            roboclaws_code_agent_profile_default_model minimax-responses
            roboclaws_code_agent_profile_wire_api kimi-openai-chat
            roboclaws_code_agent_profile_key_env codex-responses
            roboclaws_code_agent_profile_key_env mimo-responses
            """,
        ],
        cwd=REPO_ROOT,
        env=env,
        check=True,
        capture_output=True,
        text=True,
    )
    python_result = subprocess.run(
        [
            sys.executable,
            "-m",
            "roboclaws.agents.provider_registry",
            "default-model",
            "minimax-responses",
        ],
        cwd=REPO_ROOT,
        check=True,
        capture_output=True,
        text=True,
    )

    assert result.stdout.splitlines() == [
        python_result.stdout.strip(),
        "chat-completions",
        "CODEX_RESPONSES_API_KEY",
        "MIMO_RESPONSES_API_KEY",
    ]
