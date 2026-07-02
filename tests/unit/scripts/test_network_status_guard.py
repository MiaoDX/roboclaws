from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
SCRIPT = REPO_ROOT / "scripts" / "dev" / "network_status.sh"
CODING_AGENT_ENV = REPO_ROOT / "scripts" / "dev" / "coding_agent_env.sh"
JUST_DIR = REPO_ROOT / "just"


def _fake_curl(tmp_path: Path, http_code: str) -> dict[str, str]:
    fake = tmp_path / "curl"
    fake.write_text(
        f"#!/usr/bin/env bash\nprintf '%s' '{http_code}'\n",
        encoding="utf-8",
    )
    fake.chmod(0o755)
    env = os.environ.copy()
    env["PATH"] = f"{tmp_path}:{env['PATH']}"
    return env


def test_network_status_reports_work_when_probe_returns_http(tmp_path: Path) -> None:
    result = subprocess.run(
        ["bash", str(SCRIPT)],
        cwd=REPO_ROOT,
        env=_fake_curl(tmp_path, "403"),
        check=True,
        capture_output=True,
        text=True,
    )

    assert "network: work" in result.stdout
    assert "api-router.evad.mioffice.cn" in result.stdout
    assert "OpenClaw and system-provider Codex/Claude manual-debug recipes" in result.stdout
    assert "SDK live routes use repo-local CODEX_BASE_URL/CODEX_API_KEY" in result.stdout
    assert ("SDK mimo-mify-responses/minimax-responses require explicit") in result.stdout
    assert "system-provider Codex just recipes are blocked" not in result.stdout


def test_assert_off_work_blocks_when_probe_is_reachable(tmp_path: Path) -> None:
    result = subprocess.run(
        ["bash", str(SCRIPT), "--assert-off-work", "Claude Code"],
        cwd=REPO_ROOT,
        env=_fake_curl(tmp_path, "204"),
        capture_output=True,
        text=True,
    )

    assert result.returncode == 1
    assert "work network detected" in result.stderr


def test_assert_off_work_allows_when_probe_is_unreachable(tmp_path: Path) -> None:
    result = subprocess.run(
        ["bash", str(SCRIPT), "--assert-off-work", "OpenClaw"],
        cwd=REPO_ROOT,
        env=_fake_curl(tmp_path, "000"),
        check=True,
        capture_output=True,
        text=True,
    )

    assert "network guard ok" in result.stderr


def test_claude_provider_guard_blocks_system_provider_on_work_network(tmp_path: Path) -> None:
    env = _fake_curl(tmp_path, "204")
    env.pop("ROBOCLAWS_PROVIDER_PROFILE", None)
    env.pop("KIMI_API_KEY", None)
    env.pop("MIMO_TP_KEY", None)
    env.pop("XM_LLM_API_KEY", None)

    result = subprocess.run(
        [
            "bash",
            "-c",
            """
            set -euo pipefail
            source "$ROBOCLAWS_HELPER"
            roboclaws_assert_claude_code_network_allowed "Claude Code"
            """,
        ],
        cwd=REPO_ROOT,
        env={**env, "ROBOCLAWS_HELPER": str(CODING_AGENT_ENV)},
        capture_output=True,
        text=True,
    )

    assert result.returncode == 1
    assert "blocked while using system Claude Code provider" in result.stderr


def test_claude_provider_guard_allows_repo_local_provider_on_work_network(tmp_path: Path) -> None:
    env = _fake_curl(tmp_path, "204")
    env["MIMO_TP_KEY"] = "fake-mimo-key"

    result = subprocess.run(
        [
            "bash",
            "-c",
            """
            set -euo pipefail
            source "$ROBOCLAWS_HELPER"
            roboclaws_assert_claude_code_network_allowed "Claude Code"
            """,
        ],
        cwd=REPO_ROOT,
        env={**env, "ROBOCLAWS_HELPER": str(CODING_AGENT_ENV)},
        check=True,
        capture_output=True,
        text=True,
    )

    assert "repo-local Claude provider (mimo-tp-anthropic)" in result.stderr


def test_claude_provider_guard_allows_mify_anthropic_on_work_network(tmp_path: Path) -> None:
    env = _fake_curl(tmp_path, "204")
    env["ROBOCLAWS_PROVIDER_PROFILE"] = "mimo-mify-anthropic"
    env["XM_LLM_API_KEY"] = "fake-xm-key"

    result = subprocess.run(
        [
            "bash",
            "-c",
            """
            set -euo pipefail
            source "$ROBOCLAWS_HELPER"
            roboclaws_assert_claude_code_network_allowed "Claude Code"
            """,
        ],
        cwd=REPO_ROOT,
        env={**env, "ROBOCLAWS_HELPER": str(CODING_AGENT_ENV)},
        check=True,
        capture_output=True,
        text=True,
    )

    assert "repo-local Claude provider (mimo-mify-anthropic)" in result.stderr


def test_codex_provider_guard_defaults_to_codex_router_responses_on_work_network(
    tmp_path: Path,
) -> None:
    env = _fake_curl(tmp_path, "204")
    env.pop("ROBOCLAWS_PROVIDER_PROFILE", None)
    env.pop("CODEX_BASE_URL", None)
    env.pop("CODEX_API_KEY", None)
    env.pop("XM_LLM_BASE_URL", None)
    env.pop("XM_LLM_API_KEY", None)

    result = subprocess.run(
        [
            "bash",
            "-c",
            """
            set -euo pipefail
            source "$ROBOCLAWS_HELPER"
            roboclaws_assert_codex_network_allowed "Codex"
            """,
        ],
        cwd=REPO_ROOT,
        env={**env, "ROBOCLAWS_HELPER": str(CODING_AGENT_ENV)},
        check=True,
        capture_output=True,
        text=True,
    )

    assert "repo-local Codex provider (codex-router-responses)" in result.stderr


def test_codex_provider_guard_allows_mify_profile_on_work_network(tmp_path: Path) -> None:
    env = _fake_curl(tmp_path, "204")
    env["ROBOCLAWS_PROVIDER_PROFILE"] = "mimo-mify-responses"
    env["XM_LLM_API_KEY"] = "fake-xm-key"

    result = subprocess.run(
        [
            "bash",
            "-c",
            """
            set -euo pipefail
            source "$ROBOCLAWS_HELPER"
            roboclaws_assert_codex_network_allowed "Codex"
            """,
        ],
        cwd=REPO_ROOT,
        env={**env, "ROBOCLAWS_HELPER": str(CODING_AGENT_ENV)},
        check=True,
        capture_output=True,
        text=True,
    )

    assert "repo-local Codex provider (mimo-mify-responses)" in result.stderr


def test_codex_provider_guard_allows_minimax_profile_on_work_network(tmp_path: Path) -> None:
    env = _fake_curl(tmp_path, "204")
    env["ROBOCLAWS_PROVIDER_PROFILE"] = "minimax-responses"
    env["MM_API_KEY"] = "fake-mm-key"

    result = subprocess.run(
        [
            "bash",
            "-c",
            """
            set -euo pipefail
            source "$ROBOCLAWS_HELPER"
            roboclaws_assert_codex_network_allowed "Codex"
            """,
        ],
        cwd=REPO_ROOT,
        env={**env, "ROBOCLAWS_HELPER": str(CODING_AGENT_ENV)},
        check=True,
        capture_output=True,
        text=True,
    )

    assert "repo-local Codex provider (minimax-responses)" in result.stderr


def test_openai_agents_provider_guard_allows_minimax_profile_on_work_network(
    tmp_path: Path,
) -> None:
    env = _fake_curl(tmp_path, "204")
    env["ROBOCLAWS_PROVIDER_PROFILE"] = "minimax-responses"
    env["MM_API_KEY"] = "fake-mm-key"

    result = subprocess.run(
        [
            "bash",
            "-c",
            """
            set -euo pipefail
            source "$ROBOCLAWS_HELPER"
            roboclaws_assert_openai_agents_network_allowed "OpenAI Agents SDK"
            """,
        ],
        cwd=REPO_ROOT,
        env={**env, "ROBOCLAWS_HELPER": str(CODING_AGENT_ENV)},
        check=True,
        capture_output=True,
        text=True,
    )

    assert "repo-local OpenAI Agents SDK provider (minimax-responses)" in result.stderr


def test_openai_agents_provider_guard_allows_chat_profile_on_work_network(tmp_path: Path) -> None:
    env = _fake_curl(tmp_path, "204")
    env["ROBOCLAWS_PROVIDER_PROFILE"] = "mimo-tp-openai-chat"
    env["MIMO_TP_KEY"] = "fake-mimo-key"

    result = subprocess.run(
        [
            "bash",
            "-c",
            """
            set -euo pipefail
            source "$ROBOCLAWS_HELPER"
            roboclaws_assert_openai_agents_network_allowed "OpenAI Agents SDK"
            """,
        ],
        cwd=REPO_ROOT,
        env={**env, "ROBOCLAWS_HELPER": str(CODING_AGENT_ENV)},
        check=True,
        capture_output=True,
        text=True,
    )

    assert "repo-local OpenAI Agents SDK provider (mimo-tp-openai-chat)" in result.stderr


def test_codex_provider_guard_allows_repo_local_endpoint_on_work_network(tmp_path: Path) -> None:
    env = _fake_curl(tmp_path, "204")
    env.pop("XM_LLM_BASE_URL", None)
    env.pop("XM_LLM_API_KEY", None)
    env["CODEX_BASE_URL"] = "https://codex.example.test/v1"
    env["CODEX_API_KEY"] = "fake-codex-key"

    result = subprocess.run(
        [
            "bash",
            "-c",
            """
            set -euo pipefail
            source "$ROBOCLAWS_HELPER"
            roboclaws_assert_codex_network_allowed "Codex"
            """,
        ],
        cwd=REPO_ROOT,
        env={**env, "ROBOCLAWS_HELPER": str(CODING_AGENT_ENV)},
        check=True,
        capture_output=True,
        text=True,
    )

    assert "repo-local Codex provider (codex-router-responses)" in result.stderr


def test_current_and_manual_debug_just_recipes_use_network_guard() -> None:
    assert not (JUST_DIR / "appliance.just").exists()
    assert not (REPO_ROOT / "Dockerfile.railway").exists()
    assert not (REPO_ROOT / "railway.toml").exists()
    assert not (REPO_ROOT / "deploy" / "railway").exists()
    assert not (REPO_ROOT / "scripts" / "appliance").exists()
    assert not (REPO_ROOT / "scripts" / "appliance-run-interactive.sh").exists()
    assert not (REPO_ROOT / "scripts" / "appliance_control_ui_smoke.py").exists()

    openclaw_guarded_files = (
        JUST_DIR / "openclaw.just",
        JUST_DIR / "chat.just",
        JUST_DIR / "dev.just",
    )

    for path in openclaw_guarded_files:
        text = path.read_text(encoding="utf-8")
        assert "bash scripts/dev/network_status.sh --assert-off-work" in text, path

    molmo_text = (JUST_DIR / "molmo.just").read_text(encoding="utf-8")
    assert "roboclaws_assert_openai_agents_network_allowed" in molmo_text

    assert not (JUST_DIR / "code.just").exists()

    env = os.environ.copy()
    env["ROBOCLAWS_JUST_TRACE"] = "1"
    just_binary = shutil.which("just") or str(Path.home() / ".local/bin" / "just")
    for engine in ("codex-cli", "claude-code"):
        result = subprocess.run(
            [
                just_binary,
                "agent::run",
                "household-world.cleanup",
                engine,
                "world-public-labels",
            ],
            cwd=REPO_ROOT,
            env=env,
            check=False,
            capture_output=True,
            text=True,
        )
        assert result.returncode != 0
        assert f"unsupported agent_engine '{engine}'" in result.stderr

    assert "network-status:" in (JUST_DIR / "dev.just").read_text(encoding="utf-8")
