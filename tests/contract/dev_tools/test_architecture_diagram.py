from __future__ import annotations

from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]


def test_architecture_diagram_matches_current_agent_engine_docs() -> None:
    diagram = (REPO_ROOT / "docs" / "architecture.svg").read_text(encoding="utf-8")
    agent_engine_layer = "\n".join(line for line in diagram.splitlines() if 'y="4' in line)

    assert "direct-runner" in agent_engine_layer
    assert "openai-agents-sdk" in agent_engine_layer
    assert "Retired coding-agent engines" in agent_engine_layer
    assert "codex-cli" not in agent_engine_layer
    assert "claude-code" not in agent_engine_layer
