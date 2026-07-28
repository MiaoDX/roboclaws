"""Regression tests for the retired Docker-backed Codex/Claude route."""

from __future__ import annotations

from pathlib import Path


def _repo_root() -> Path:
    for parent in Path(__file__).resolve().parents:
        if (parent / "justfile").is_file():
            return parent
    raise AssertionError("could not locate repo root")


REPO_ROOT = _repo_root()
JUST_DIR = REPO_ROOT / "just"
CI_WORKFLOW = REPO_ROOT / ".github" / "workflows" / "ci.yml"


def test_retired_docker_coding_agent_files_are_absent() -> None:
    retired_paths = [
        REPO_ROOT / "Dockerfile.coding-agents",
        JUST_DIR / "code.just",
        REPO_ROOT / "scripts" / "dev" / "coding_agent_docker.sh",
        REPO_ROOT / "scripts" / "dev" / "coding_agent_toolchain.env",
        REPO_ROOT / "scripts" / "dev" / "probe_codex_mcp_image_compare.sh",
        REPO_ROOT / "scripts" / "dev" / "probe_codex_mcp_image_server.py",
        REPO_ROOT / "scripts" / "molmo_cleanup" / "run_live_codex_cleanup.py",
        REPO_ROOT / "scripts" / "molmo_cleanup" / "run_live_claude_cleanup.py",
        REPO_ROOT / "scripts" / "molmo_cleanup" / "run_live_codex_agibot_map_build.py",
    ]

    assert [path for path in retired_paths if path.exists()] == []


def test_current_live_dispatch_does_not_reference_retired_route() -> None:
    justfile = (REPO_ROOT / "justfile").read_text(encoding="utf-8")
    molmo_text = (JUST_DIR / "molmo.just").read_text(encoding="utf-8")
    ci_text = CI_WORKFLOW.read_text(encoding="utf-8")

    combined = "\n".join([justfile, molmo_text, ci_text])
    assert "mod code" not in justfile
    assert "scripts/molmo_cleanup/run_live_openai_agents_cleanup.py" in molmo_text
    for retired in (
        "Build pinned coding-agent CLI image",
        "Dockerfile.coding-agents",
        "scripts/dev/coding_agent_docker.sh",
        ".tmp/coding-agent-bin",
        "scripts/molmo_cleanup/run_live_codex_cleanup.py",
        "scripts/molmo_cleanup/run_live_claude_cleanup.py",
        "scripts/molmo_cleanup/run_live_codex_agibot_map_build.py",
        "codex-provider-smoke",
    ):
        assert retired not in combined
