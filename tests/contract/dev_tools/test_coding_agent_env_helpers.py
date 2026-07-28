from __future__ import annotations

import subprocess
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
CODING_AGENT_ENV = REPO_ROOT / "scripts" / "dev" / "coding_agent_env.sh"


def clean_code_agent_env() -> dict[str, str]:
    return {
        "PATH": "/usr/bin:/bin",
        "ROBOCLAWS_PYTHON": str(REPO_ROOT / ".venv" / "bin" / "python"),
    }


def run_helper(script: str) -> subprocess.CompletedProcess[str]:
    env = clean_code_agent_env()
    env["ROBOCLAWS_HELPER"] = str(CODING_AGENT_ENV)
    return subprocess.run(
        ["bash", "-c", script],
        cwd=REPO_ROOT,
        env=env,
        check=False,
        capture_output=True,
        text=True,
    )


def test_sdk_model_helper_rejects_route_incompatible_model_override() -> None:
    result = run_helper(
        """
        set -euo pipefail
        source "$ROBOCLAWS_HELPER"
        ROBOCLAWS_PROVIDER_PROFILE=minimax-responses
        ROBOCLAWS_OPENAI_AGENTS_MODEL=kimi-k2.7-code
        MM_BASE_URL=https://minimax.example.test/v1
        MM_API_KEY=fake-mm-key
        roboclaws_code_agent_model \
          ROBOCLAWS_OPENAI_AGENTS_MODEL ROBOCLAWS_PROVIDER_PROFILE
        """
    )

    assert result.returncode == 2
    expected = (
        "coding-agent model 'kimi-k2.7-code' is incompatible with provider 'minimax-responses'"
    )
    assert expected in result.stderr
    assert "incompatible with provider_profile 'minimax-responses'" in result.stderr


def test_sdk_model_helper_rejects_removed_minimax_highspeed_override() -> None:
    result = run_helper(
        """
        set -euo pipefail
        source "$ROBOCLAWS_HELPER"
        ROBOCLAWS_PROVIDER_PROFILE=minimax-responses
        ROBOCLAWS_OPENAI_AGENTS_MODEL=MiniMax-M2.7-highspeed
        MM_BASE_URL=https://minimax.example.test/v1
        MM_API_KEY=fake-mm-key
        roboclaws_code_agent_model \
          ROBOCLAWS_OPENAI_AGENTS_MODEL ROBOCLAWS_PROVIDER_PROFILE
        """
    )

    assert result.returncode == 2
    assert "unknown coding-agent model 'MiniMax-M2.7-highspeed'" in result.stderr


def test_provider_helper_rejects_unknown_profile_without_raw_fallback() -> None:
    result = run_helper(
        """
        set -euo pipefail
        source "$ROBOCLAWS_HELPER"
        ROBOCLAWS_PROVIDER_PROFILE=not-a-provider-route
        roboclaws_code_agent_provider ROBOCLAWS_PROVIDER_PROFILE
        """
    )

    assert result.returncode == 2
    assert result.stdout == ""
    assert "unsupported provider profile 'not-a-provider-route'" in result.stderr
    assert "Traceback" not in result.stderr


def test_profile_summary_rejects_unknown_profile_without_traceback() -> None:
    result = run_helper(
        """
        set -euo pipefail
        source "$ROBOCLAWS_HELPER"
        ROBOCLAWS_PROVIDER_PROFILE=not-a-provider-route
        roboclaws_code_agent_profile_summary \
          ROBOCLAWS_PROVIDER_PROFILE ROBOCLAWS_OPENAI_AGENTS_MODEL
        """
    )

    assert result.returncode == 2
    assert result.stdout == ""
    assert "unsupported provider profile 'not-a-provider-route'" in result.stderr
    assert "Traceback" not in result.stderr


def test_provider_helper_requires_explicit_profile_selection() -> None:
    result = run_helper(
        """
        set -euo pipefail
        source "$ROBOCLAWS_HELPER"
        unset ROBOCLAWS_PROVIDER_PROFILE
        roboclaws_code_agent_provider ROBOCLAWS_PROVIDER_PROFILE
        """
    )

    assert result.returncode == 2
    assert result.stdout == ""
    assert "requires explicit ROBOCLAWS_PROVIDER_PROFILE selection" in result.stderr
    assert "Traceback" not in result.stderr


def test_profile_summary_uses_final_kimi_contract() -> None:
    result = run_helper(
        """
        set -euo pipefail
        source "$ROBOCLAWS_HELPER"
        ROBOCLAWS_PROVIDER_PROFILE=kimi-openai-chat
        KIMI_OPENAI_BASE_URL=https://kimi.example.test/v1
        KIMI_API_KEY=fake-kimi-key
        roboclaws_code_agent_profile_summary \
          ROBOCLAWS_PROVIDER_PROFILE ROBOCLAWS_OPENAI_AGENTS_MODEL
        """
    )

    assert result.returncode == 0
    assert "kimi-openai-chat model=kimi-k2.7-code" in result.stdout
    assert "protocol=chat-completions" in result.stdout


def test_python_helper_requires_repo_venv_without_system_fallback() -> None:
    result = subprocess.run(
        [
            "bash",
            "-c",
            """
            set -euo pipefail
            source "$ROBOCLAWS_HELPER"
            unset ROBOCLAWS_PYTHON
            roboclaws_python
            """,
        ],
        cwd=REPO_ROOT,
        env={"PATH": "/usr/bin:/bin", "ROBOCLAWS_HELPER": str(CODING_AGENT_ENV)},
        check=False,
        capture_output=True,
        text=True,
    )

    if (REPO_ROOT / ".venv" / "bin" / "python").is_file():
        assert result.returncode == 0
        assert result.stdout.strip() == ".venv/bin/python"
    else:
        assert result.returncode == 2
        assert "missing repo Python at .venv/bin/python" in result.stderr
    assert "python3" not in result.stdout
