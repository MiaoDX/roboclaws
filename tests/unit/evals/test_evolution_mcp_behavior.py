from __future__ import annotations

import difflib
import subprocess
from hashlib import sha256
from pathlib import Path

import pytest

from roboclaws.evals.evolution_contracts import Campaign
from roboclaws.evals.evolution_mcp_behavior import (
    BehaviorProposal,
    run_mcp_behavior_deterministic_gate,
    validate_behavior_source_delta,
)

TARGET = "roboclaws/household/household_mcp_projection.py"


def _baseline() -> tuple[str, str]:
    commit = subprocess.run(
        ["git", "rev-parse", "HEAD"], check=True, capture_output=True, text=True
    ).stdout.strip()
    source = subprocess.run(
        ["git", "show", f"{commit}:{TARGET}"],
        check=True,
        capture_output=True,
        text=True,
    ).stdout
    return commit, source


def _campaign() -> tuple[Campaign, str]:
    commit, source = _baseline()
    campaign = Campaign.from_mapping(
        {
            "schema": "eval_evolution_campaign_v1",
            "campaign_id": "mcp-behavior-test",
            "target": {
                "kind": "mcp-behavior",
                "id": "household-world",
                "mutable_paths": [TARGET],
                "baseline_commit": commit,
                "target_sha256": sha256(source.encode()).hexdigest(),
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
            "sealed_holdout_ref": "holdout",
            "gates": {},
            "selection": {},
            "budgets": {
                "optimizer_turns": 1,
                "candidates": 1,
                "live_trials": 1,
                "provider_concurrency": 1,
                "tokens": 1,
                "cost_usd": 1,
                "wall_time_s": 1,
                "timeout_s": 1,
                "retries": 0,
            },
            "identity": {},
            "feedback_schema": "eval_evolution_feedback_v1",
            "candidate_limits": {"max_patch_bytes": 24000, "max_changed_paths": 1},
            "promotion_policy": "human-only-v1",
        }
    )
    return campaign, source


def _proposal(campaign: Campaign, baseline: str) -> BehaviorProposal:
    candidate = baseline.replace(
        '"status": response.get("status", "ok"),',
        '"status": str(response.get("status") or "ok"),',
        1,
    )
    patch = "".join(
        difflib.unified_diff(
            baseline.splitlines(keepends=True),
            candidate.splitlines(keepends=True),
            fromfile=f"a/{TARGET}",
            tofile=f"b/{TARGET}",
        )
    )
    return BehaviorProposal.from_mapping(
        {
            "schema": "eval_evolution_mcp_behavior_proposal_v1",
            "campaign_id": campaign.campaign_id,
            "parent_sha256": campaign.target["target_sha256"],
            "hypothesis": "Normalize a missing public status without changing the tool surface.",
            "patch": patch,
        }
    )


def test_behavior_candidate_materializes_after_static_gate(tmp_path: Path) -> None:
    campaign, baseline = _campaign()
    result = run_mcp_behavior_deterministic_gate(
        campaign,
        proposal=_proposal(campaign, baseline),
        output_root=tmp_path,
        repo_root=Path.cwd(),
    )
    assert result["status"] == "gated"
    assert result["reason"] == "behavior_candidate_requires_isolated_live_eval"
    assert result["validation"]["imports_preserved"] is True
    assert Path(result["candidate"]["workspace"], "candidate.json").is_file()


@pytest.mark.parametrize(
    "candidate,error",
    [
        ("import os\n\ndef project():\n    return 1\n", "imports"),
        ("def project():\n    return open('/tmp/value')\n", "forbidden calls"),
        ("def project():\n    return '/proc/self/environ'\n", "private/path literals"),
        ("def project():\n    return 1\n\ndef added():\n    return 2\n", "definitions"),
    ],
)
def test_behavior_static_gate_rejects_authority_expansion(candidate: str, error: str) -> None:
    baseline = "def project():\n    return 1\n"
    with pytest.raises(ValueError, match=error):
        validate_behavior_source_delta(baseline, candidate)


def test_behavior_proposal_rejects_stale_parent() -> None:
    campaign, baseline = _campaign()
    proposal = _proposal(campaign, baseline)
    stale = BehaviorProposal(
        campaign_id=proposal.campaign_id,
        parent_sha256="0" * 64,
        hypothesis=proposal.hypothesis,
        patch=proposal.patch,
    )
    with pytest.raises(ValueError, match="stale parent"):
        stale.validate_for_campaign(campaign)
