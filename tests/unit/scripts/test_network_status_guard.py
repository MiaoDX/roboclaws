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
    env["ROBOCLAWS_WORK_NETWORK_PROBE_URL"] = "https://work-probe.example.test/"
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
    assert "work-probe.example.test" in result.stdout
    assert "system-provider Codex/Claude manual-debug recipes" in result.stdout
    assert "repo-local OpenAI Agents SDK provider routes are allowed" in result.stdout
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
        ["bash", str(SCRIPT), "--assert-off-work", "Claude Code"],
        cwd=REPO_ROOT,
        env=_fake_curl(tmp_path, "000"),
        check=True,
        capture_output=True,
        text=True,
    )

    assert "network guard ok" in result.stderr


def test_openai_agents_provider_gate_allows_minimax_without_network_probe() -> None:
    env = os.environ.copy()
    env.pop("ROBOCLAWS_WORK_NETWORK_PROBE_URL", None)
    env["ROBOCLAWS_PROVIDER_PROFILE"] = "minimax-responses"
    env["MM_API_KEY"] = "fake-mm-key"

    result = subprocess.run(
        [
            "bash",
            "-c",
            """
            set -euo pipefail
            source "$ROBOCLAWS_HELPER"
            roboclaws_assert_openai_agents_provider_allowed
            """,
        ],
        cwd=REPO_ROOT,
        env={**env, "ROBOCLAWS_HELPER": str(CODING_AGENT_ENV)},
        check=True,
        capture_output=True,
        text=True,
    )

    assert "OpenAI Agents SDK provider gate ok (minimax-responses)" in result.stderr


def test_openai_agents_provider_gate_requires_explicit_profile() -> None:
    env = os.environ.copy()
    env.pop("ROBOCLAWS_WORK_NETWORK_PROBE_URL", None)
    env.pop("ROBOCLAWS_PROVIDER_PROFILE", None)

    result = subprocess.run(
        [
            "bash",
            "-c",
            """
            set -euo pipefail
            source "$ROBOCLAWS_HELPER"
            roboclaws_assert_openai_agents_provider_allowed
            """,
        ],
        cwd=REPO_ROOT,
        env={**env, "ROBOCLAWS_HELPER": str(CODING_AGENT_ENV)},
        capture_output=True,
        text=True,
    )

    assert result.returncode == 2
    assert "requires explicit ROBOCLAWS_PROVIDER_PROFILE selection" in result.stderr


def test_openai_agents_provider_gate_allows_chat_without_network_probe() -> None:
    env = os.environ.copy()
    env.pop("ROBOCLAWS_WORK_NETWORK_PROBE_URL", None)
    env["ROBOCLAWS_PROVIDER_PROFILE"] = "kimi-openai-chat"
    env["KIMI_OPENAI_BASE_URL"] = "https://kimi.example.test/v1"
    env["KIMI_API_KEY"] = "fake-kimi-key"

    result = subprocess.run(
        [
            "bash",
            "-c",
            """
            set -euo pipefail
            source "$ROBOCLAWS_HELPER"
            roboclaws_assert_openai_agents_provider_allowed
            """,
        ],
        cwd=REPO_ROOT,
        env={**env, "ROBOCLAWS_HELPER": str(CODING_AGENT_ENV)},
        check=True,
        capture_output=True,
        text=True,
    )

    assert "OpenAI Agents SDK provider gate ok (kimi-openai-chat)" in result.stderr


def test_retired_local_runtime_recipes_are_absent() -> None:
    assert not (JUST_DIR / "appliance.just").exists()
    assert not (REPO_ROOT / "Dockerfile.railway").exists()
    assert not (REPO_ROOT / "railway.toml").exists()
    assert not (REPO_ROOT / "deploy" / "railway").exists()
    assert not (REPO_ROOT / "scripts" / "appliance").exists()
    assert not (REPO_ROOT / "scripts" / "appliance-run-interactive.sh").exists()
    assert not (REPO_ROOT / "scripts" / "appliance_control_ui_smoke.py").exists()

    assert not (JUST_DIR / "openclaw.just").exists()
    assert not (JUST_DIR / "chat.just").exists()

    assert not (JUST_DIR / "code.just").exists()

    env = os.environ.copy()
    env["ROBOCLAWS_JUST_TRACE"] = "1"
    just_binary = shutil.which("just") or str(Path.home() / ".local/bin" / "just")
    for engine in ("codex-cli", "claude-code"):
        result = subprocess.run(
            [
                just_binary,
                "run::surface",
                "surface=household-world",
                f"agent_engine={engine}",
                "evidence_lane=world-public-labels",
            ],
            cwd=REPO_ROOT,
            env=env,
            check=False,
            capture_output=True,
            text=True,
        )
        assert result.returncode != 0
        assert f"unsupported agent_engine '{engine}'" in result.stderr

    assert not (JUST_DIR / "dev.just").exists()
    assert (REPO_ROOT / "scripts" / "dev" / "network_status.sh").is_file()
