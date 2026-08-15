from __future__ import annotations

import json
import subprocess
from dataclasses import replace
from hashlib import sha256
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from roboclaws.agents.evolution_optimizer import OptimizerOutcome
from roboclaws.evals import evolution_campaign
from roboclaws.evals.evolution_campaign import run_skill_campaign
from roboclaws.evals.evolution_contracts import Campaign
from roboclaws.evals.suite_loading import load_suite


def _git(repo: Path, *args: str) -> str:
    return subprocess.run(
        ["git", *args], cwd=repo, check=True, capture_output=True, text=True
    ).stdout.strip()


def _setup(tmp_path: Path) -> tuple[Path, Campaign, str]:
    repo = tmp_path / "repo"
    skill = repo / "skills/example/SKILL.md"
    skill.parent.mkdir(parents=True)
    skill.write_text("# Example\n\nOriginal.\n", encoding="utf-8")
    other_skill = repo / "skills/other/SKILL.md"
    other_skill.parent.mkdir(parents=True)
    other_skill.write_text("# Example\n\nOriginal.\n", encoding="utf-8")
    _git(repo, "init")
    _git(repo, "config", "user.email", "test@example.com")
    _git(repo, "config", "user.name", "Test")
    _git(repo, "add", "skills/example/SKILL.md", "skills/other/SKILL.md")
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
                "optimizer_call_tokens": 100,
                "optimizer_call_cost_usd": 0.1,
                "robot_attempt_tokens": 100,
                "robot_attempt_cost_usd": 0.05,
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
        "metrics": {
            "quality": quality,
            "tool_calls": 10,
            "tokens": 100,
            "cost_usd": 0.01,
        },
    }


def _optimizer_outcome(
    patch: str,
    *,
    hypothesis: str = "Clarify order.",
    usage: dict[str, object] | None = None,
) -> OptimizerOutcome:
    return OptimizerOutcome(
        hypothesis=hypothesis,
        patch=patch,
        identity={
            "agent_engine": "openai-agents-sdk",
            "role": "optimizer",
            "model": "gpt-5.5",
        },
        usage=usage or {"tokens": 10, "cost_usd": 0.01},
        trace_id="trace-1",
    )


def _suite_results(
    suite_ref: str,
    *,
    quality: float,
    tokens: float = 10,
    cost_usd: float = 0.001,
) -> list[dict[str, object]]:
    suite, samples = load_suite(suite_ref)
    return [
        {
            "identity": {
                "suite_id": suite.suite_id,
                "sample_id": sample.sample_id,
                "seed": sample.seed,
                "repetition_index": repetition_index,
            },
            "status": "passed",
            "grader_outputs": {"authoritative": {"status": "passed"}},
            "metrics": {
                "quality": quality,
                "tokens": tokens,
                "cost_usd": cost_usd,
            },
        }
        for sample in samples
        for repetition_index in range(sample.trial_count)
    ]


def test_skill_campaign_runs_deterministic_gate_before_paired_matrix(tmp_path: Path) -> None:
    repo, campaign, patch = _setup(tmp_path)
    calls: list[tuple[str, bool]] = []

    def optimizer(*_args: object, **_kwargs: object) -> OptimizerOutcome:
        return _optimizer_outcome(patch)

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


def test_stale_baseline_commit_is_rejected_before_optimizer(tmp_path: Path) -> None:
    repo, campaign, _patch = _setup(tmp_path)
    (repo / "README.md").write_text("Unrelated change.\n", encoding="utf-8")
    _git(repo, "add", "README.md")
    _git(repo, "commit", "-m", "advance head without changing target")
    called = False

    def optimizer(*_args: object, **_kwargs: object) -> OptimizerOutcome:
        nonlocal called
        called = True
        raise AssertionError("stale campaign must fail before provider execution")

    with pytest.raises(ValueError, match="campaign baseline commit is stale"):
        run_skill_campaign(
            campaign,
            repo_root=repo,
            output_root=tmp_path / "output",
            optimizer_runner=optimizer,
            matrix_runner=lambda *_args: [],
        )

    assert called is False


def test_neutral_campaign_does_not_run_holdout(tmp_path: Path) -> None:
    repo, campaign, patch = _setup(tmp_path)
    calls: list[str] = []

    def optimizer(*_args: object, **_kwargs: object) -> OptimizerOutcome:
        return _optimizer_outcome(patch, hypothesis="Neutral")

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
        return _optimizer_outcome(
            "diff --git a/skills/example/SKILL.md b/skills/example/SKILL.md\n"
            "--- a/skills/example/SKILL.md\n+++ b/skills/example/SKILL.md\n"
            "@@ -1 +1,2 @@\n # Example\n",
            hypothesis="Malformed",
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


@pytest.mark.parametrize(
    ("patch", "reason"),
    [
        ("x" * 4097, "candidate patch exceeds max_patch_bytes"),
        ("\x00", "candidate patch must not contain binary data"),
    ],
    ids=["oversized", "binary"],
)
def test_invalid_candidate_content_writes_terminal_rejection(
    tmp_path: Path,
    patch: str,
    reason: str,
) -> None:
    repo, campaign, _valid_patch = _setup(tmp_path)
    calls: list[str] = []

    def optimizer(*_args: object, **_kwargs: object) -> OptimizerOutcome:
        return _optimizer_outcome(patch)

    def matrix(_campaign: Campaign, _workspace: Path | None, lane: str) -> list[dict[str, object]]:
        calls.append(lane)
        return []

    result = run_skill_campaign(
        campaign,
        repo_root=repo,
        output_root=tmp_path / "output",
        optimizer_runner=optimizer,
        matrix_runner=matrix,
    )

    assert result["status"] == "rejected"
    assert result["quality_gates"] == {
        "candidate_materialization": False,
        "reason": reason,
    }
    assert result["training"]["status"] == "not_run"
    assert result["holdout"]["status"] == "not_run"
    assert calls == []
    assert Path(result["report_path"]).is_file()


def test_suite_runner_uses_campaign_output_root_and_target_skill(tmp_path: Path) -> None:
    repo, campaign, patch = _setup(tmp_path)
    campaign = replace(
        campaign,
        training={"suites": ["evolution_skill_smoke_training"], "budget": "focused"},
        sealed_holdout_ref="evolution_skill_smoke_holdout",
    )
    output_root = tmp_path / "custom-output"
    calls: list[tuple[str, Path, str, bool, float, float]] = []

    def optimizer(*_args: object, **_kwargs: object) -> OptimizerOutcome:
        return _optimizer_outcome(patch)

    def suite_runner(suite_ref: str, **kwargs: Any) -> SimpleNamespace:
        calls.append(
            (
                suite_ref,
                Path(kwargs["output_root"]),
                str(kwargs["skill_name"]),
                bool(kwargs["skill_source_root"]),
                float(kwargs["live_token_budget"]),
                float(kwargs["live_cost_budget_usd"]),
            )
        )
        quality = 0.9 if kwargs["skill_source_root"] else 0.7
        return SimpleNamespace(bundle={"results": _suite_results(suite_ref, quality=quality)})

    result = run_skill_campaign(
        campaign,
        repo_root=repo,
        output_root=output_root,
        optimizer_runner=optimizer,
        suite_runner=suite_runner,
    )

    campaign_eval_root = output_root / campaign.campaign_id / "evals"
    assert result["status"] == "accepted"
    assert [call[2] for call in calls] == ["example"] * 4
    assert [call[3] for call in calls] == [False, True, False, True]
    assert [call[4] for call in calls] == [100.0] * 4
    assert [call[5] for call in calls] == [0.05] * 4
    assert calls[0][1] == campaign_eval_root / "training-baseline"
    assert calls[1][1] == campaign_eval_root / "training-candidate"
    assert calls[2][1] == campaign_eval_root / "holdout-baseline"
    assert calls[3][1].parent == campaign_eval_root
    assert calls[3][1].name.startswith("holdout-")


def test_live_trial_budget_blocks_before_matrix_execution(tmp_path: Path) -> None:
    repo, campaign, patch = _setup(tmp_path)
    campaign = replace(campaign, budgets=campaign.budgets | {"live_trials": 0})
    calls: list[str] = []

    def optimizer(*_args: object, **_kwargs: object) -> OptimizerOutcome:
        return _optimizer_outcome(patch)

    def matrix(_campaign: Campaign, _workspace: Path | None, lane: str) -> list[dict[str, object]]:
        calls.append(lane)
        return [_trial("scene-1", 0.7)]

    result = run_skill_campaign(
        campaign,
        repo_root=repo,
        output_root=tmp_path / "output",
        optimizer_runner=optimizer,
        matrix_runner=matrix,
    )

    assert result["status"] == "inconclusive"
    assert result["training"]["reason"] == "live_trials_exhausted"
    assert calls == []


@pytest.mark.parametrize(
    ("budget_override", "reason"),
    [
        ({"tokens": 99}, "tokens_exhausted"),
        ({"cost_usd": 0.09}, "cost_usd_exhausted"),
    ],
)
def test_optimizer_reservation_blocks_before_provider_execution(
    tmp_path: Path,
    budget_override: dict[str, object],
    reason: str,
) -> None:
    repo, campaign, _patch = _setup(tmp_path)
    campaign = replace(campaign, budgets=campaign.budgets | budget_override)
    called = False

    def optimizer(*_args: object, **_kwargs: object) -> OptimizerOutcome:
        nonlocal called
        called = True
        raise AssertionError("insufficient reservation must block before provider execution")

    result = run_skill_campaign(
        campaign,
        repo_root=repo,
        output_root=tmp_path / "output",
        optimizer_runner=optimizer,
        matrix_runner=lambda *_args: [],
    )

    assert called is False
    assert result["status"] == "inconclusive"
    assert result["training"]["reason"] == reason


def test_suite_trial_budget_is_reserved_before_provider_execution(tmp_path: Path) -> None:
    repo, campaign, patch = _setup(tmp_path)
    campaign = replace(
        campaign,
        training={"suites": ["evolution_skill_smoke_training"], "budget": "focused"},
        budgets=campaign.budgets | {"live_trials": 1},
    )
    calls: list[str] = []

    def optimizer(*_args: object, **_kwargs: object) -> OptimizerOutcome:
        return _optimizer_outcome(patch)

    def suite_runner(suite_ref: str, **_kwargs: Any) -> SimpleNamespace:
        calls.append(suite_ref)
        raise AssertionError("insufficient campaign budget must block before the suite starts")

    result = run_skill_campaign(
        campaign,
        repo_root=repo,
        output_root=tmp_path / "output",
        optimizer_runner=optimizer,
        suite_runner=suite_runner,
    )

    assert result["status"] == "inconclusive"
    assert result["training"]["reason"] == "live_trials_exhausted"
    assert calls == []


def test_suite_reserves_retry_attempts_before_provider_execution(tmp_path: Path) -> None:
    repo, campaign, patch = _setup(tmp_path)
    campaign = replace(
        campaign,
        training={"suites": ["evolution_skill_smoke_training"], "budget": "focused"},
        budgets=campaign.budgets | {"live_trials": 2, "retries": 1},
    )
    calls: list[str] = []

    def optimizer(*_args: object, **_kwargs: object) -> OptimizerOutcome:
        return _optimizer_outcome(patch)

    def suite_runner(suite_ref: str, **_kwargs: Any) -> SimpleNamespace:
        calls.append(suite_ref)
        raise AssertionError("retry attempts must fit before the suite starts")

    result = run_skill_campaign(
        campaign,
        repo_root=repo,
        output_root=tmp_path / "output",
        optimizer_runner=optimizer,
        suite_runner=suite_runner,
    )

    assert result["status"] == "inconclusive"
    assert result["training"]["reason"] == "live_trials_exhausted"
    assert calls == []


@pytest.mark.parametrize(
    ("budget_override", "usage", "reason"),
    [
        (
            {"tokens": 5},
            {"input_tokens": 4, "output_tokens": 2, "cost_usd": 0.0},
            "tokens_exhausted",
        ),
        (
            {"cost_usd": 0.001},
            {"tokens": 1, "cost_usd": 0.002},
            "cost_usd_exhausted",
        ),
        ({}, {"usage_available": False}, "token_usage_evidence_unavailable"),
    ],
)
def test_optimizer_budget_exhaustion_is_terminal_before_robot_trials(
    tmp_path: Path,
    budget_override: dict[str, object],
    usage: dict[str, object],
    reason: str,
) -> None:
    repo, campaign, patch = _setup(tmp_path)
    campaign = replace(campaign, budgets=campaign.budgets | budget_override)
    calls: list[str] = []

    def optimizer(*_args: object, **_kwargs: object) -> OptimizerOutcome:
        return _optimizer_outcome(patch, usage=usage)

    def matrix(_campaign: Campaign, _workspace: Path | None, lane: str) -> list[dict[str, object]]:
        calls.append(lane)
        return [_trial("scene-1", 0.7)]

    result = run_skill_campaign(
        campaign,
        repo_root=repo,
        output_root=tmp_path / "output",
        optimizer_runner=optimizer,
        matrix_runner=matrix,
    )

    assert result["status"] == "inconclusive"
    assert result["training"]["reason"] == reason
    assert calls == []


def test_optimizer_provider_failure_writes_terminal_inconclusive_report(tmp_path: Path) -> None:
    repo, campaign, _patch = _setup(tmp_path)
    calls: list[str] = []

    def optimizer(*_args: object, **_kwargs: object) -> OptimizerOutcome:
        raise RuntimeError("503 service unavailable")

    def matrix(_campaign: Campaign, _workspace: Path | None, lane: str) -> list[dict[str, object]]:
        calls.append(lane)
        return []

    result = run_skill_campaign(
        campaign,
        repo_root=repo,
        output_root=tmp_path / "output",
        optimizer_runner=optimizer,
        matrix_runner=matrix,
    )

    assert result["status"] == "inconclusive"
    assert result["training"]["reason"] == "optimizer_provider_transient_failure"
    assert result["quality_gates"] == {"optimizer_execution": False}
    assert result["holdout"]["status"] == "not_run"
    assert calls == []
    assert Path(result["report_path"]).is_file()


@pytest.mark.parametrize("failing_lane", ["training-baseline", "training-candidate"])
def test_training_matrix_failure_writes_terminal_inconclusive_report(
    tmp_path: Path,
    failing_lane: str,
) -> None:
    repo, campaign, patch = _setup(tmp_path)
    calls: list[str] = []

    def optimizer(*_args: object, **_kwargs: object) -> OptimizerOutcome:
        return _optimizer_outcome(patch)

    def matrix(_campaign: Campaign, workspace: Path | None, lane: str) -> list[dict[str, object]]:
        calls.append(lane)
        if lane == failing_lane:
            raise RuntimeError("503 service unavailable")
        return [_trial("scene-1", 0.9 if workspace else 0.7)]

    result = run_skill_campaign(
        campaign,
        repo_root=repo,
        output_root=tmp_path / "output",
        optimizer_runner=optimizer,
        matrix_runner=matrix,
    )

    expected_calls = ["training-baseline"]
    if failing_lane == "training-candidate":
        expected_calls.append("training-candidate")
    assert calls == expected_calls
    assert result["status"] == "inconclusive"
    assert result["training"]["reason"] == "training_provider_transient_failure"
    assert result["quality_gates"]["training_execution"] is False
    assert result["holdout"]["status"] == "not_run"
    assert Path(result["report_path"]).is_file()


def test_holdout_matrix_failure_writes_terminal_inconclusive_report(tmp_path: Path) -> None:
    repo, campaign, patch = _setup(tmp_path)
    calls: list[str] = []

    def optimizer(*_args: object, **_kwargs: object) -> OptimizerOutcome:
        return _optimizer_outcome(patch)

    def matrix(_campaign: Campaign, workspace: Path | None, lane: str) -> list[dict[str, object]]:
        calls.append(lane)
        if lane == "holdout-baseline":
            raise RuntimeError("503 service unavailable")
        return [_trial("scene-1", 0.9 if workspace else 0.7)]

    result = run_skill_campaign(
        campaign,
        repo_root=repo,
        output_root=tmp_path / "output",
        optimizer_runner=optimizer,
        matrix_runner=matrix,
    )

    assert calls == ["training-baseline", "training-candidate", "holdout-baseline"]
    assert result["status"] == "inconclusive"
    assert result["holdout"]["status"] == "inconclusive"
    assert result["holdout"]["reason"] == "holdout_provider_transient_failure"
    assert Path(result["report_path"]).is_file()


def test_suite_token_reservation_blocks_before_provider_execution(tmp_path: Path) -> None:
    repo, campaign, patch = _setup(tmp_path)
    campaign = replace(
        campaign,
        training={"suites": ["evolution_skill_smoke_training"], "budget": "focused"},
        budgets=campaign.budgets
        | {"tokens": 25, "optimizer_call_tokens": 1, "robot_attempt_tokens": 20},
    )
    calls: list[str] = []

    def optimizer(*_args: object, **_kwargs: object) -> OptimizerOutcome:
        return _optimizer_outcome(patch, usage={"tokens": 1, "cost_usd": 0.001})

    def suite_runner(suite_ref: str, **_kwargs: Any) -> SimpleNamespace:
        calls.append(suite_ref)
        return SimpleNamespace(
            bundle={"results": _suite_results(suite_ref, quality=0.7, tokens=20)}
        )

    result = run_skill_campaign(
        campaign,
        repo_root=repo,
        output_root=tmp_path / "output",
        optimizer_runner=optimizer,
        suite_runner=suite_runner,
    )

    assert result["status"] == "inconclusive"
    assert result["training"]["reason"] == "tokens_exhausted"
    assert calls == []


def test_optimizer_timeout_is_capped_by_campaign_wall_budget(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    repo, campaign, patch = _setup(tmp_path)
    campaign = replace(campaign, budgets=campaign.budgets | {"wall_time_s": 5, "timeout_s": 30})
    seen_timeout_s: list[float] = []
    monkeypatch.setattr(evolution_campaign.time, "monotonic", lambda: 100.0)

    def optimizer(optimizer_campaign: Campaign, **_kwargs: object) -> OptimizerOutcome:
        seen_timeout_s.append(float(optimizer_campaign.budgets["timeout_s"]))
        return _optimizer_outcome(patch)

    def matrix(_campaign: Campaign, workspace: Path | None, _lane: str) -> list[dict[str, object]]:
        return [_trial("scene-1", 0.9 if workspace else 0.7)]

    result = run_skill_campaign(
        campaign,
        repo_root=repo,
        output_root=tmp_path / "output",
        optimizer_runner=optimizer,
        matrix_runner=matrix,
    )

    assert result["status"] == "accepted"
    assert seen_timeout_s == [5.0]


def test_zero_wall_budget_blocks_before_optimizer_provider_call(tmp_path: Path) -> None:
    repo, campaign, _patch = _setup(tmp_path)
    campaign = replace(campaign, budgets=campaign.budgets | {"wall_time_s": 0})
    called = False

    def optimizer(*_args: object, **_kwargs: object) -> OptimizerOutcome:
        nonlocal called
        called = True
        raise AssertionError("zero wall budget must block before provider execution")

    result = run_skill_campaign(
        campaign,
        repo_root=repo,
        output_root=tmp_path / "output",
        optimizer_runner=optimizer,
        matrix_runner=lambda *_args: [],
    )

    assert called is False
    assert result["status"] == "inconclusive"
    assert result["training"]["reason"] == "wall_time_s_exhausted"


def test_suite_usage_is_enforced_after_each_live_trial(tmp_path: Path) -> None:
    repo, campaign, patch = _setup(tmp_path)
    campaign = replace(
        campaign,
        training={"suites": ["evolution_skill_smoke_training"], "budget": "focused"},
        budgets=campaign.budgets
        | {"tokens": 15, "optimizer_call_tokens": 1, "robot_attempt_tokens": 5},
    )
    executed_results = 0

    def optimizer(*_args: object, **_kwargs: object) -> OptimizerOutcome:
        return _optimizer_outcome(patch, usage={"tokens": 1, "cost_usd": 0.001})

    def suite_runner(suite_ref: str, **kwargs: Any) -> SimpleNamespace:
        nonlocal executed_results
        observer = kwargs["result_observer"]
        # Six tokens exceed one attempt's reservation but still fit the suite's
        # aggregate ten-token reservation. The second trial must not start.
        results = _suite_results(suite_ref, quality=0.7, tokens=6)
        for result in results:
            executed_results += 1
            observer(result)
        return SimpleNamespace(bundle={"results": results})

    result = run_skill_campaign(
        campaign,
        repo_root=repo,
        output_root=tmp_path / "output",
        optimizer_runner=optimizer,
        suite_runner=suite_runner,
    )

    assert result["status"] == "inconclusive"
    assert result["training"]["reason"] == "tokens_exhausted"
    assert executed_results == 1


def test_retry_without_failed_attempt_usage_fails_closed(tmp_path: Path) -> None:
    repo, campaign, patch = _setup(tmp_path)
    campaign = replace(
        campaign,
        training={"suites": ["evolution_skill_smoke_training"], "budget": "focused"},
    )
    attempts_path = tmp_path / "live_trial_attempts.json"
    attempts_path.write_text(
        json.dumps(
            {
                "schema": "roboclaws_live_trial_attempts_v1",
                "attempts": [
                    {"attempt_index": 0, "status": "stalled"},
                    {"attempt_index": 1, "status": "passed"},
                ],
            }
        ),
        encoding="utf-8",
    )

    def optimizer(*_args: object, **_kwargs: object) -> OptimizerOutcome:
        return _optimizer_outcome(patch)

    def suite_runner(suite_ref: str, **_kwargs: Any) -> SimpleNamespace:
        results = _suite_results(suite_ref, quality=0.7)
        results[0]["artifacts"] = {"live_trial_attempts": str(attempts_path)}
        return SimpleNamespace(bundle={"results": results})

    result = run_skill_campaign(
        campaign,
        repo_root=repo,
        output_root=tmp_path / "output",
        optimizer_runner=optimizer,
        suite_runner=suite_runner,
    )

    assert result["status"] == "inconclusive"
    assert result["training"]["reason"] == "retry_usage_evidence_unavailable"
