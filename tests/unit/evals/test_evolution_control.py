from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

from roboclaws.evals.evolution_control import run_evolution_command


def _campaign_payload() -> dict[str, object]:
    return {
        "schema": "eval_evolution_campaign_v1",
        "campaign_id": "behavior-test",
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
            "model": "k3",
        },
        "training": {"suites": ["cleanup"], "scenes": ["scene-1"]},
        "sealed_holdout_ref": "maintainer-reference-1",
        "gates": {"deterministic": ["unit"], "quality": ["checker"]},
        "selection": {"primary_objective": "quality", "minimum_improvement": 0.1},
        "budgets": {
            "optimizer_turns": 2,
            "candidates": 1,
            "live_trials": 2,
            "provider_concurrency": 1,
            "tokens": 30_000,
            "cost_usd": 5.0,
            "optimizer_call_tokens": 20_000,
            "optimizer_call_cost_usd": 1.0,
            "robot_attempt_tokens": 10_000,
            "robot_attempt_cost_usd": 0.5,
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


def test_mcp_behavior_live_evolution_is_blocked_by_isolation(tmp_path: Path) -> None:
    payload = _campaign_payload()
    payload["campaign_id"] = "behavior-isolation-test"
    payload["target"] = {
        **payload["target"],
        "kind": "mcp-behavior",
        "id": "household-world",
        "mutable_paths": ["roboclaws/household/household_mcp_projection.py"],
    }
    campaign_path = tmp_path / "campaign.json"
    campaign_path.write_text(json.dumps(payload))

    result = run_evolution_command(
        "evolve", {"campaign": str(campaign_path), "live_execution": "run"}
    )

    assert result["status"] == "blocked"
    assert result["reason"] == "blocked_by_candidate_isolation"


def test_mcp_behavior_accepts_campaign_bound_isolation_attestation(
    tmp_path: Path, monkeypatch
) -> None:
    payload = _campaign_payload()
    payload["campaign_id"] = "behavior-isolation-passed"
    payload["target"] = {
        **payload["target"],
        "kind": "mcp-behavior",
        "id": "household-world",
        "mutable_paths": ["roboclaws/household/household_mcp_projection.py"],
    }
    payload["identity"]["candidate_isolation_attestation_sha256"] = "a" * 64
    payload["identity"]["execution_placement"] = "cloudml-native-container"
    campaign_path = tmp_path / "campaign.json"
    campaign_path.write_text(json.dumps(payload))
    attestation_path = tmp_path / "attestation.json"
    attestation_path.write_text("{}")
    monkeypatch.setattr(
        "roboclaws.evals.evolution_control.load_isolation_attestation",
        lambda path, expected_sha256: SimpleNamespace(
            summary=lambda: {
                "schema": "candidate_isolation_attestation_v1",
                "placement": "cloudml-native-container",
                "verdict": "passed",
            }
        ),
    )

    result = run_evolution_command(
        "evolve",
        {
            "campaign": str(campaign_path),
            "isolation_attestation": str(attestation_path),
            "live_execution": "run",
        },
    )

    assert result["status"] == "blocked"
    assert result["reason"] == "behavior_campaign_requires_candidate_artifact"
    assert result["candidate_isolation"]["verdict"] == "passed"


def test_mcp_behavior_routes_candidate_to_static_gate(tmp_path: Path, monkeypatch) -> None:
    payload = _campaign_payload()
    payload["campaign_id"] = "behavior-candidate-gated"
    payload["target"] = {
        **payload["target"],
        "kind": "mcp-behavior",
        "id": "household-world",
        "mutable_paths": ["roboclaws/household/household_mcp_projection.py"],
    }
    payload["identity"]["candidate_isolation_attestation_sha256"] = "a" * 64
    payload["identity"]["execution_placement"] = "cloudml-native-container"
    campaign_path = tmp_path / "campaign.json"
    campaign_path.write_text(json.dumps(payload))
    attestation_path = tmp_path / "attestation.json"
    attestation_path.write_text("{}")
    candidate_path = tmp_path / "candidate.json"
    candidate_path.write_text(
        json.dumps(
            {
                "schema": "eval_evolution_mcp_behavior_proposal_v1",
                "campaign_id": payload["campaign_id"],
                "parent_sha256": payload["target"]["target_sha256"],
                "hypothesis": "Bounded public response normalization.",
                "patch": "candidate patch",
            }
        )
    )
    monkeypatch.setattr(
        "roboclaws.evals.evolution_control.load_isolation_attestation",
        lambda path, expected_sha256: SimpleNamespace(
            summary=lambda: {
                "schema": "candidate_isolation_attestation_v1",
                "placement": "cloudml-native-container",
                "verdict": "passed",
            }
        ),
    )
    monkeypatch.setattr(
        "roboclaws.evals.evolution_control.run_mcp_behavior_deterministic_gate",
        lambda campaign, proposal, output_root, repo_root: {
            "schema": "eval_evolution_mcp_behavior_deterministic_gate_v1",
            "campaign_id": campaign.campaign_id,
            "status": "gated",
            "reason": "behavior_candidate_requires_isolated_live_eval",
        },
    )

    result = run_evolution_command(
        "evolve",
        {
            "campaign": str(campaign_path),
            "candidate": str(candidate_path),
            "isolation_attestation": str(attestation_path),
            "live_execution": "run",
        },
    )

    assert result["status"] == "gated"
    assert result["reason"] == "behavior_candidate_requires_isolated_live_eval"
    assert result["candidate_isolation"]["verdict"] == "passed"
