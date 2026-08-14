from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[3]


def just_bin() -> str:
    path = shutil.which("just")
    if path:
        return path
    local_path = Path.home() / ".local/bin" / "just"
    if local_path.exists():
        return str(local_path)
    pytest.skip("just binary is not available")


def test_sdk_map_build_rejects_unknown_backend_from_catalog() -> None:
    env = os.environ.copy()
    env["ROBOCLAWS_JUST_TRACE"] = "1"
    result = subprocess.run(
        [
            just_bin(),
            "run::surface",
            "surface=household-world",
            "agent_engine=openai-agents-sdk",
            "provider_profile=kimi-openai-chat",
            "preset=map-build",
            "backend=missing_backend",
        ],
        cwd=REPO_ROOT,
        env=env,
        check=False,
        capture_output=True,
        text=True,
    )

    assert result.returncode != 0
    assert "unsupported backend 'missing_backend'" in result.stderr


def test_surface_rejects_retired_codex_map_build_engine() -> None:
    env = os.environ.copy()
    env["ROBOCLAWS_JUST_TRACE"] = "1"
    result = subprocess.run(
        [
            just_bin(),
            "run::surface",
            "surface=household-world",
            "agent_engine=codex-cli",
            "preset=map-build",
        ],
        cwd=REPO_ROOT,
        env=env,
        check=False,
        capture_output=True,
        text=True,
    )

    assert result.returncode != 0
    assert "unsupported agent_engine 'codex-cli'" in result.stderr
    assert "expected direct-runner|openai-agents-sdk" in result.stderr
