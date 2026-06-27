from __future__ import annotations

import shlex
from pathlib import Path

from roboclaws.launch.catalog import resolve_surface_launch

REPO_ROOT = Path(__file__).resolve().parents[3]


def test_open_ended_status_rerun_command_uses_current_provider_profile() -> None:
    text = (
        REPO_ROOT / "docs" / "status" / "active" / "open-ended-household-default-architecture.md"
    ).read_text(encoding="utf-8")
    command = text.split("Next command/artifact: re-run", 1)[1].split("`", 2)[1]
    argv = shlex.split(command)

    assert argv[:2] == ["just", "run::surface"]
    plan = resolve_surface_launch(argv[2:])
    assert plan.agent_engine == "openai-agents-sdk"
    assert plan.provider_profile == "codex-router-responses"
    assert plan.intent == "open-ended"
