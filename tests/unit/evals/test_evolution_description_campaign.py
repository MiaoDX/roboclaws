from __future__ import annotations

from pathlib import Path

from roboclaws.evals.evolution_campaign import run_mcp_description_campaign
from roboclaws.evals.evolution_contracts import Campaign
from roboclaws.evals.evolution_mcp_description import snapshot_public_mcp_profile
from roboclaws.mcp.profiles import HOUSEHOLD_WORLD_PROFILE


def test_description_campaign_is_deterministic_and_behavior_free(tmp_path: Path) -> None:
    baseline = snapshot_public_mcp_profile(HOUSEHOLD_WORLD_PROFILE)
    candidate = baseline.to_target()
    candidate["parent_sha256"] = baseline.sha256
    candidate["tools"] = {name: dict(value) for name, value in baseline.tools.items()}
    candidate["tools"]["observe"]["summary"] += " Return public observations."
    campaign = Campaign.from_mapping(
        {
            "schema": "eval_evolution_campaign_v1",
            "campaign_id": "description-campaign",
            "target": {
                "kind": "mcp-description",
                "id": HOUSEHOLD_WORLD_PROFILE,
                "mutable_paths": ["roboclaws/mcp/profiles.py"],
                "baseline_commit": "f" * 40,
                "target_sha256": baseline.sha256,
            },
            "optimizer": {
                "agent_engine": "openai-agents-sdk",
                "provider_profile": "codex-responses",
                "model": "o",
                "settings": {},
            },
            "robot": {
                "agent_engine": "openai-agents-sdk",
                "provider_profile": "kimi-openai-chat",
                "model": "r",
            },
            "training": {},
            "sealed_holdout_ref": "h",
            "gates": {},
            "selection": {},
            "budgets": {
                "optimizer_turns": 1,
                "candidates": 1,
                "live_trials": 0,
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
    result = run_mcp_description_campaign(campaign, candidate=candidate, output_root=tmp_path)
    assert result["status"] == "gated"
    assert result["live_execution"] == "blocked"
    assert result["candidate"]["identity_frozen"] is True
