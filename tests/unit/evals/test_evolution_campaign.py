from __future__ import annotations

import subprocess
from hashlib import sha256
from pathlib import Path

from roboclaws.agents.evolution_optimizer import OptimizerOutcome
from roboclaws.evals.evolution_campaign import run_skill_campaign
from roboclaws.evals.evolution_contracts import Campaign


def _git(repo: Path, *args: str) -> str:
    return subprocess.run(
        ["git", *args], cwd=repo, check=True, capture_output=True, text=True
    ).stdout.strip()


def _setup(tmp_path: Path) -> tuple[Path, Campaign, str]:
    repo = tmp_path / "repo"
    skill = repo / "skills/example/SKILL.md"
    skill.parent.mkdir(parents=True)
    skill.write_text("# Example\n\nOriginal.\n", encoding="utf-8")
    _git(repo, "init")
    _git(repo, "config", "user.email", "test@example.com")
    _git(repo, "config", "user.name", "Test")
    _git(repo, "add", "skills/example/SKILL.md")
    _git(repo, "commit", "-m", "baseline")
    commit = _git(repo, "rev-parse", "HEAD")
    skill.write_text("# Example\n\nImproved.\n", encoding="utf-8")
    patch = _git(repo, "diff", "--", "skills/example/SKILL.md") + "\n"
    skill.write_text("# Example\n\nOriginal.\n", encoding="utf-8")
    campaign = Campaign.from_mapping(
        {
            "schema": "eval_evolution_campaign_v1",
            "campaign_id": "campaign-1",
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
            "training": {"suites": ["train-a", "train-b"], "budget": "focused"},
            "sealed_holdout_ref": "sealed-suite",
            "gates": {},
            "selection": {
                "primary_objective": "quality",
                "direction": "maximize",
                "minimum_improvement": 0.1,
            },
            "budgets": {
                "optimizer_turns": 1,
                "candidates": 1,
                "live_trials": 8,
                "provider_concurrency": 1,
                "tokens": 1000,
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
    return repo, campaign, patch


def _trial(pair_id: str, quality: float) -> dict[str, object]:
    return {
        "pair_id": pair_id,
        "status": "passed",
        "skill_delivery_cell": "static-full",
        "quality_gates": {"privacy": True, "checker": True},
        "metrics": {"quality": quality, "tool_calls": 10, "tokens": 100},
    }


def test_skill_campaign_runs_deterministic_gate_before_paired_matrix(tmp_path: Path) -> None:
    repo, campaign, patch = _setup(tmp_path)
    calls: list[tuple[str, bool]] = []

    def optimizer(*_args: object, **_kwargs: object) -> OptimizerOutcome:
        return OptimizerOutcome(
            hypothesis="Clarify order.",
            patch=patch,
            identity={"agent_engine": "openai-agents-sdk", "role": "optimizer"},
            usage={"tokens": 10},
            trace_id="trace-1",
        )

    def matrix(_campaign: Campaign, workspace: Path | None, lane: str) -> list[dict[str, object]]:
        calls.append((lane, workspace is not None))
        quality = 0.9 if workspace is not None else 0.7
        return [_trial("scene-1", quality), _trial("scene-2", quality)]

    result = run_skill_campaign(
        campaign,
        repo_root=repo,
        output_root=tmp_path / "output",
        optimizer_runner=optimizer,
        matrix_runner=matrix,
    )
    assert result["status"] == "accepted"
    assert result["optimizer"]["identity"]["agent_engine"] == "openai-agents-sdk"
    assert calls == [
        ("training-baseline", False),
        ("training-candidate", True),
        ("holdout-baseline", False),
        (f"holdout-{result['candidate_id']}", True),
    ]
    assert Path(result["report_path"]).is_file()
    assert (repo / "skills/example/SKILL.md").read_text(encoding="utf-8").endswith("Original.\n")


def test_neutral_campaign_does_not_run_holdout(tmp_path: Path) -> None:
    repo, campaign, patch = _setup(tmp_path)
    calls: list[str] = []

    def optimizer(*_args: object, **_kwargs: object) -> OptimizerOutcome:
        return OptimizerOutcome(
            "Neutral",
            patch,
            {"agent_engine": "openai-agents-sdk", "role": "optimizer"},
            {},
            "",
        )

    def matrix(_campaign: Campaign, _workspace: Path | None, lane: str) -> list[dict[str, object]]:
        calls.append(lane)
        return [_trial("scene-1", 0.7), _trial("scene-2", 0.7)]

    result = run_skill_campaign(
        campaign,
        repo_root=repo,
        output_root=tmp_path / "output",
        optimizer_runner=optimizer,
        matrix_runner=matrix,
    )
    assert result["status"] == "no_improving_candidate"
    assert calls == ["training-baseline", "training-candidate"]
    assert result["holdout"]["status"] == "not_run"


def test_malformed_candidate_writes_terminal_rejection_before_robot_eval(tmp_path: Path) -> None:
    repo, campaign, _patch = _setup(tmp_path)
    calls: list[str] = []

    def optimizer(*_args: object, **_kwargs: object) -> OptimizerOutcome:
        return OptimizerOutcome(
            "Malformed",
            "diff --git a/skills/example/SKILL.md b/skills/example/SKILL.md\n"
            "--- a/skills/example/SKILL.md\n+++ b/skills/example/SKILL.md\n"
            "@@ -1 +1,2 @@\n # Example\n",
            {"agent_engine": "openai-agents-sdk", "role": "optimizer"},
            {},
            "",
        )

    def matrix(_campaign: Campaign, _workspace: Path | None, lane: str) -> list[dict[str, object]]:
        calls.append(lane)
        return []

    result = run_skill_campaign(
        campaign,
        repo_root=repo,
        output_root=repo / "output",
        optimizer_runner=optimizer,
        matrix_runner=matrix,
    )

    assert result["status"] == "rejected"
    assert result["quality_gates"]["candidate_materialization"] is False
    assert result["training"]["status"] == "not_run"
    assert result["holdout"]["status"] == "not_run"
    assert calls == []
    assert Path(result["report_path"]).is_file()
