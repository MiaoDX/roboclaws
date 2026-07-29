from __future__ import annotations

import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
ACTIVE_STATUS_ROOT = REPO_ROOT / "docs" / "status" / "active"
CURRENT_DOCS = (
    REPO_ROOT / "README.md",
    REPO_ROOT / "ARCHITECTURE.md",
    REPO_ROOT / "docs" / "agents" / "operating-runbook.md",
    REPO_ROOT / "docs" / "human" / "contributing.md",
    REPO_ROOT / "just" / "README.md",
)
TERMINAL_STATUS = re.compile(r"(?im)^status:\s*(?:done|complete|completed)\s*$")


def test_active_markdown_capsules_are_not_terminal() -> None:
    terminal = [
        path.relative_to(REPO_ROOT).as_posix()
        for path in ACTIVE_STATUS_ROOT.glob("*.md")
        if TERMINAL_STATUS.search(path.read_text(encoding="utf-8"))
    ]

    assert terminal == []


def test_current_sdk_command_lines_select_a_provider_profile() -> None:
    missing_profile: list[str] = []
    for path in CURRENT_DOCS:
        for line_number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
            if "just run::surface" not in line or "agent_engine=openai-agents-sdk" not in line:
                continue
            if "provider_profile=" not in line:
                missing_profile.append(f"{path.relative_to(REPO_ROOT)}:{line_number}")

    assert missing_profile == []


def test_empty_pytest_regression_layer_is_absent() -> None:
    pytest_config = (REPO_ROOT / "pyproject.toml").read_text(encoding="utf-8")
    test_docs = (REPO_ROOT / "tests" / "README.md").read_text(encoding="utf-8")
    dev_recipes = (REPO_ROOT / "just" / "dev.just").read_text(encoding="utf-8")

    assert '"regression:' not in pytest_config
    assert "-m regression" not in test_docs
    assert "-m regression" not in dev_recipes
