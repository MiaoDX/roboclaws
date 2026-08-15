from __future__ import annotations

from pathlib import Path

from roboclaws.evals.evolution_candidates import materialize_mcp_description_candidate
from roboclaws.evals.evolution_contracts import Campaign
from roboclaws.evals.evolution_mcp_description import snapshot_public_mcp_profile
from roboclaws.mcp.profiles import HOUSEHOLD_WORLD_PROFILE


def _campaign(tmp_path: Path) -> Campaign:
    baseline = snapshot_public_mcp_profile(HOUSEHOLD_WORLD_PROFILE)
    return Campaign.from_mapping(
        {
            "schema": "eval_evolution_campaign_v1",
            "campaign_id": "mcp-description-test",
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
                "optimizer_call_tokens": 1,
                "optimizer_call_cost_usd": 1,
                "robot_attempt_tokens": 1,
                "robot_attempt_cost_usd": 1,
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


def test_materializes_description_candidate_content_addressed(tmp_path: Path) -> None:
    baseline = snapshot_public_mcp_profile(HOUSEHOLD_WORLD_PROFILE)
    candidate = baseline.to_target()
    candidate["parent_sha256"] = baseline.sha256
    candidate["tools"] = {name: dict(value) for name, value in baseline.tools.items()}
    candidate["tools"]["observe"]["summary"] += " Return public observations."

    record = materialize_mcp_description_candidate(
        _campaign(tmp_path), candidate=candidate, output_root=tmp_path / "output"
    )

    assert record["identity_frozen"] is True
    assert record["changed_tools"] == ["observe"]
    assert Path(record["workspace"], "candidate.json").is_file()
