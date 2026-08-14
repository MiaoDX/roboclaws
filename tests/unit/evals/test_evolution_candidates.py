from __future__ import annotations

import subprocess
from hashlib import sha256
from pathlib import Path

import pytest

from roboclaws.evals.evolution_candidates import materialize_skill_candidate
from roboclaws.evals.evolution_contracts import Campaign


def _git(repo: Path, *args: str) -> str:
    return subprocess.run(
        ["git", *args], cwd=repo, check=True, capture_output=True, text=True
    ).stdout.strip()


def _campaign(repo: Path, skill: Path) -> Campaign:
    commit = _git(repo, "rev-parse", "HEAD")
    return Campaign.from_mapping(
        {
            "schema": "eval_evolution_campaign_v1",
            "campaign_id": "skill-candidate-test",
            "target": {
                "kind": "skill",
                "id": "example",
                "mutable_paths": ["skills/example/SKILL.md"],
                "baseline_commit": commit,
                "target_sha256": sha256(skill.read_bytes()).hexdigest(),
            },
            "optimizer": {
                "agent_engine": "openai-agents-sdk",
                "provider_profile": "codex-responses",
                "model": "optimizer",
                "settings": {},
            },
            "robot": {
                "agent_engine": "openai-agents-sdk",
                "provider_profile": "kimi-openai-chat",
                "model": "robot",
            },
            "training": {},
            "sealed_holdout_ref": "sealed-1",
            "gates": {},
            "selection": {},
            "budgets": {
                "optimizer_turns": 1,
                "candidates": 1,
                "live_trials": 1,
                "provider_concurrency": 1,
                "tokens": 100,
                "cost_usd": 1,
                "wall_time_s": 60,
                "timeout_s": 30,
                "retries": 0,
            },
            "identity": {},
            "feedback_schema": "eval_evolution_feedback_v1",
            "candidate_limits": {"max_patch_bytes": 4096, "max_changed_paths": 1},
            "promotion_policy": "human-only-v1",
        }
    )


@pytest.fixture
def baseline_repo(tmp_path: Path) -> tuple[Path, Path]:
    repo = tmp_path / "repo"
    skill = repo / "skills/example/SKILL.md"
    skill.parent.mkdir(parents=True)
    skill.write_text("# Example\n\nOriginal.\n", encoding="utf-8")
    _git(repo, "init")
    _git(repo, "config", "user.email", "test@example.com")
    _git(repo, "config", "user.name", "Test")
    _git(repo, "add", "skills/example/SKILL.md")
    _git(repo, "commit", "-m", "baseline")
    return repo, skill


def test_materializes_full_snapshot_and_freezes_identity(
    baseline_repo: tuple[Path, Path], tmp_path: Path
) -> None:
    repo, skill = baseline_repo
    campaign = _campaign(repo, skill)
    # Generate a normal tracked-file patch without mutating the committed baseline.
    skill.write_text("# Example\n\nImproved.\n", encoding="utf-8")
    patch = _git(repo, "diff", "--", "skills/example/SKILL.md") + "\n"
    skill.write_text("# Example\n\nOriginal.\n", encoding="utf-8")

    record = materialize_skill_candidate(
        campaign, patch=patch, output_root=tmp_path / "output", repo_root=repo
    )
    workspace = Path(record["workspace"])
    assert (
        (workspace / "skills/example/SKILL.md").read_text(encoding="utf-8").endswith("Improved.\n")
    )
    assert skill.read_text(encoding="utf-8").endswith("Original.\n")
    assert record["identity_frozen"] is True
    assert Path(record["workspace"]).is_absolute()
    assert (
        materialize_skill_candidate(
            campaign, patch=patch, output_root=tmp_path / "output", repo_root=repo
        )
        == record
    )


def test_materializes_when_output_root_is_inside_source_repo(
    baseline_repo: tuple[Path, Path],
) -> None:
    repo, skill = baseline_repo
    campaign = _campaign(repo, skill)
    skill.write_text("# Example\n\nImproved in nested output.\n", encoding="utf-8")
    patch = _git(repo, "diff", "--", "skills/example/SKILL.md") + "\n"
    skill.write_text("# Example\n\nOriginal.\n", encoding="utf-8")

    record = materialize_skill_candidate(
        campaign, patch=patch, output_root=repo / "output", repo_root=repo
    )

    materialized = Path(record["workspace"]) / "skills/example/SKILL.md"
    assert materialized.read_text(encoding="utf-8").endswith("Improved in nested output.\n")


def test_rejects_patch_outside_allowlist(baseline_repo: tuple[Path, Path], tmp_path: Path) -> None:
    repo, skill = baseline_repo
    other = repo / "roboclaws/evals/runner.py"
    other.parent.mkdir(parents=True)
    other.write_text("before\n", encoding="utf-8")
    _git(repo, "add", "roboclaws/evals/runner.py")
    _git(repo, "commit", "-m", "other")
    campaign = _campaign(repo, skill)
    other.write_text("after\n", encoding="utf-8")
    patch = _git(repo, "diff", "--", "roboclaws/evals/runner.py") + "\n"

    with pytest.raises(ValueError, match="not campaign-authorized"):
        materialize_skill_candidate(
            campaign, patch=patch, output_root=tmp_path / "output", repo_root=repo
        )
