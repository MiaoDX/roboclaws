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


def test_molmo_cleanup_rejects_unknown_backend_from_catalog() -> None:
    result = subprocess.run(
        [
            just_bin(),
            "molmo::household-world-impl",
            "direct",
            "world-public-labels",
            "7",
            "output/test",
            "task",
            "1",
            "127.0.0.1",
            "18788",
            "auto",
            "auto",
            "auto",
            "",
            "auto",
            "off",
            "",
            "backend=missing_backend",
        ],
        cwd=REPO_ROOT,
        check=False,
        capture_output=True,
        text=True,
    )

    assert result.returncode != 0
    assert "unsupported backend 'missing_backend'" in result.stderr
    assert "expected api_semantic_synthetic|molmospaces_subprocess|isaaclab_subprocess" in (
        result.stderr
    )


def test_molmo_cleanup_rejects_unscoped_isaac_backend_from_private_impl() -> None:
    result = subprocess.run(
        [
            just_bin(),
            "molmo::household-world-impl",
            "direct",
            "world-public-labels",
            "7",
            "output/test",
            "task",
            "1",
            "127.0.0.1",
            "18788",
            "auto",
            "auto",
            "auto",
            "",
            "auto",
            "off",
            "",
            "backend=isaaclab_subprocess",
        ],
        cwd=REPO_ROOT,
        check=False,
        capture_output=True,
        text=True,
    )

    assert result.returncode != 0
    assert "backend=isaaclab_subprocess is scoped to world=b1-map12" in result.stderr


def test_sdk_map_build_rejects_unknown_backend_from_catalog() -> None:
    env = os.environ.copy()
    env["ROBOCLAWS_JUST_TRACE"] = "1"
    result = subprocess.run(
        [
            just_bin(),
            "agent::run",
            "household-world",
            "openai-agents-sdk",
            "world-public-labels",
            "task_intent=map-build",
            "backend=missing_backend",
        ],
        cwd=REPO_ROOT,
        env=env,
        check=False,
        capture_output=True,
        text=True,
    )

    assert result.returncode != 0
    assert "surface=household-world task_intent=map-build openai-agents-sdk" in result.stderr
    assert "unsupported backend 'missing_backend'" in result.stderr
    assert "expected auto|molmospaces_subprocess|isaaclab_subprocess|agibot_gdk" in result.stderr


def test_agent_run_rejects_retired_codex_map_build_engine() -> None:
    env = os.environ.copy()
    env["ROBOCLAWS_JUST_TRACE"] = "1"
    result = subprocess.run(
        [
            just_bin(),
            "agent::run",
            "household-world",
            "codex-cli",
            "world-public-labels",
            "task_intent=map-build",
            "backend=molmospaces_subprocess",
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
