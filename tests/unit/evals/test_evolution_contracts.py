from __future__ import annotations

import json
from hashlib import sha256
from pathlib import Path

import pytest

from roboclaws.evals.evolution_contracts import (
    Campaign,
    Candidate,
    Feedback,
    PromotionManifest,
    SelectionReport,
    campaign_terminal_status,
    load_campaign,
    validate_candidate_authority,
    validate_optimizer_visible_payload,
)


def _campaign_payload() -> dict[str, object]:
    return {
        "schema": "eval_evolution_campaign_v1",
        "campaign_id": "skill-smoke-1",
        "target": {
            "kind": "skill",
            "id": "household-cleanup",
            "mutable_paths": ["skills/household-cleanup/SKILL.md"],
            "baseline_commit": "a" * 40,
            "target_sha256": "b" * 64,
        },
        "optimizer": {
            "agent_engine": "openai-agents-sdk",
            "provider_profile": "codex-responses",
            "model": "codex-model",
            "settings": {},
        },
        "robot": {
            "agent_engine": "openai-agents-sdk",
            "provider_profile": "kimi-openai-chat",
            "model": "robot-model",
        },
        "training": {"suites": ["cleanup"], "scenes": ["scene-1", "scene-2"]},
        "sealed_holdout_ref": "maintainer-reference-1",
        "gates": {"deterministic": ["unit"], "quality": ["checker"]},
        "selection": {"primary_objective": "quality", "minimum_improvement": 0.1},
        "budgets": {
            "optimizer_turns": 2,
            "candidates": 1,
            "live_trials": 6,
            "provider_concurrency": 1,
            "tokens": 10000,
            "cost_usd": 5.0,
            "wall_time_s": 1800,
            "timeout_s": 600,
            "retries": 0,
        },
        "identity": {
            "agents_sdk_version": "1.0",
            "tool_surface_sha256": "c" * 64,
            "grader_versions": {"checker": "1"},
            "execution_placement": "local",
            "runtime": "repo-venv",
        },
        "feedback_schema": "eval_evolution_feedback_v1",
        "candidate_limits": {"max_patch_bytes": 4096, "max_changed_paths": 1},
        "promotion_policy": "human-only-v1",
    }


def test_campaign_requires_agents_sdk_for_both_roles(tmp_path: Path) -> None:
    payload = _campaign_payload()
    optimizer = dict(payload["optimizer"])  # type: ignore[arg-type]
    optimizer["agent_engine"] = "codex-cli"
    payload["optimizer"] = optimizer
    path = tmp_path / "campaign.json"
    path.write_text(json.dumps(payload), encoding="utf-8")

    with pytest.raises(ValueError, match="optimizer.agent_engine must be openai-agents-sdk"):
        load_campaign(path)


def test_campaign_is_strict_and_freezes_required_policy() -> None:
    payload = _campaign_payload()
    payload["unexpected"] = True
    with pytest.raises(ValueError, match="unsupported campaign field"):
        Campaign.from_mapping(payload)


@pytest.mark.parametrize(
    "mutable_path",
    ["../skills/example/SKILL.md", "roboclaws/evals/runner.py", "evals/private.json"],
)
def test_campaign_rejects_unauthorized_mutable_paths(mutable_path: str) -> None:
    payload = _campaign_payload()
    target = dict(payload["target"])  # type: ignore[arg-type]
    target["mutable_paths"] = [mutable_path]
    payload["target"] = target
    with pytest.raises(ValueError, match="path|skill campaigns"):
        Campaign.from_mapping(payload)


@pytest.mark.parametrize(
    ("payload", "match"),
    [
        ({"private_goal_reference": "hidden"}, "forbidden key"),
        ({"note": "read /home/example/repo/evals/private.json"}, "host path"),
        ({"note": "probe /proc/self/environ"}, "proc path"),
        ({"api_key": "secret"}, "forbidden key"),
        ({"holdout": {"scene": "secret"}}, "forbidden key"),
    ],
)
def test_optimizer_visible_payload_rejects_private_material(
    payload: dict[str, object], match: str
) -> None:
    with pytest.raises(ValueError, match=match):
        validate_optimizer_visible_payload(payload)


def test_sanitized_feedback_is_derivable_without_raw_eval_data() -> None:
    feedback = Feedback.from_mapping(
        {
            "schema": "eval_evolution_feedback_v1",
            "campaign_id": "skill-smoke-1",
            "target": {"kind": "skill", "id": "household-cleanup", "sha256": "b" * 64},
            "public_context": {"skill_text": "Clean visible household objects."},
            "failure": {"class": "partial_progress_only", "explanation": "One item remained."},
            "quality": {"status": "failed"},
            "work": {"tool_calls": 12, "tokens": 1000},
            "prior_candidate": None,
            "remaining_budget": {"candidates": 1, "tokens": 9000},
        }
    )
    validate_optimizer_visible_payload(feedback.to_dict())


def test_candidate_authority_rejects_traversal_symlink_and_forbidden_path(tmp_path: Path) -> None:
    allowed = ("skills/household-cleanup/SKILL.md",)
    with pytest.raises(ValueError, match="relative normalized"):
        validate_candidate_authority(tmp_path, ("../evals/private.json",), allowed)

    target = tmp_path / allowed[0]
    target.parent.mkdir(parents=True)
    outside = tmp_path / "outside"
    outside.write_text("secret", encoding="utf-8")
    target.symlink_to(outside)
    with pytest.raises(ValueError, match="symlink"):
        validate_candidate_authority(tmp_path, allowed, allowed)

    with pytest.raises(ValueError, match="not campaign-authorized"):
        validate_candidate_authority(tmp_path, ("roboclaws/evals/runner.py",), allowed)


def test_candidate_rejects_stale_parent_and_mixed_patch_authority() -> None:
    campaign = Campaign.from_mapping(_campaign_payload())
    payload = {
        "schema": "eval_evolution_candidate_v1",
        "candidate_id": "candidate-1",
        "campaign_id": campaign.campaign_id,
        "target_kind": "skill",
        "parent_commit": "d" * 40,
        "parent_target_sha256": "b" * 64,
        "hypothesis": "Use a shorter ordered procedure.",
        "patch": "diff --git a/skills/household-cleanup/SKILL.md",
        "patch_sha256": sha256(b"diff --git a/skills/household-cleanup/SKILL.md").hexdigest(),
        "mutable_paths": ["skills/household-cleanup/SKILL.md"],
        "materialized_sha256": "f" * 64,
        "optimizer_identity": {"agent_engine": "openai-agents-sdk"},
        "optimizer_usage": {"tokens": 100},
        "gates": {},
        "eval_identities": [],
        "terminal_status": "proposed",
    }
    with pytest.raises(ValueError, match="stale baseline commit"):
        Candidate.from_mapping(payload).validate_for_campaign(campaign)

    payload["parent_commit"] = "a" * 40
    payload["mutable_paths"] = [
        allowed := "skills/household-cleanup/SKILL.md",
        "roboclaws/evals/runner.py",
    ]
    assert allowed
    with pytest.raises(ValueError, match="mutable paths do not match"):
        Candidate.from_mapping(payload).validate_for_campaign(campaign)


def test_candidate_rejects_oversized_and_binary_patches() -> None:
    campaign_payload = _campaign_payload()
    campaign_payload["candidate_limits"] = {"max_patch_bytes": 4, "max_changed_paths": 1}
    campaign = Campaign.from_mapping(campaign_payload)
    base = {
        "schema": "eval_evolution_candidate_v1",
        "candidate_id": "candidate-1",
        "campaign_id": campaign.campaign_id,
        "target_kind": "skill",
        "parent_commit": "a" * 40,
        "parent_target_sha256": "b" * 64,
        "hypothesis": "Shorten it.",
        "patch": "large",
        "patch_sha256": sha256(b"large").hexdigest(),
        "mutable_paths": ["skills/household-cleanup/SKILL.md"],
        "materialized_sha256": "f" * 64,
        "optimizer_identity": {"agent_engine": "openai-agents-sdk"},
        "optimizer_usage": {},
        "gates": {},
        "eval_identities": [],
        "terminal_status": "proposed",
    }
    with pytest.raises(ValueError, match="max_patch_bytes"):
        Candidate.from_mapping(base).validate_for_campaign(campaign)

    base["patch"] = "\x00"
    base["patch_sha256"] = sha256(b"\x00").hexdigest()
    with pytest.raises(ValueError, match="binary"):
        Candidate.from_mapping(base).validate_for_campaign(campaign)


def test_selection_and_promotion_require_human_approval() -> None:
    report = SelectionReport.from_mapping(
        {
            "schema": "eval_evolution_selection_report_v1",
            "campaign_id": "skill-smoke-1",
            "baseline_identity": {"commit": "a" * 40},
            "candidate_id": "candidate-1",
            "training": {"eligible": True},
            "holdout": {"status": "passed"},
            "quality_gates": {"passed": True},
            "minimum_improvement": {"passed": True},
            "status": "accepted",
            "digests": {"report": "b" * 64},
            "optimizer": {
                "identity": {"agent_engine": "openai-agents-sdk"},
                "usage": {},
            },
            "robot": {"agent_engine": "openai-agents-sdk"},
            "limitations": [],
        }
    )
    manifest = PromotionManifest.from_mapping(
        {
            "schema": "eval_evolution_promotion_manifest_v1",
            "campaign_id": report.campaign_id,
            "candidate_id": "candidate-1",
            "maintainer_approved": False,
            "bindings": {"report_sha256": "b" * 64},
            "reviewer": {"identity": "maintainer", "reviewed_at": "2026-08-05T00:00:00Z"},
        }
    )
    with pytest.raises(ValueError, match="maintainer_approved=true"):
        manifest.validate_for_report(report)


def test_budget_exhaustion_is_inconclusive() -> None:
    assert campaign_terminal_status(budget_exhausted=True, quality_failed=False) == "inconclusive"
