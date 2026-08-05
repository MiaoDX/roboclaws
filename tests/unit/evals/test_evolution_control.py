from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

from roboclaws.evals.evolution_control import run_evolution_command


def test_mcp_behavior_live_evolution_is_blocked_by_isolation(tmp_path: Path) -> None:
    payload = json.loads(
        Path("output/eval-evolution/20260805-skill-smoke-v4-input.json").read_text()
    )
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
    payload = json.loads(
        Path("output/eval-evolution/20260805-skill-smoke-v4-input.json").read_text()
    )
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
    payload = json.loads(
        Path("output/eval-evolution/20260805-skill-smoke-v4-input.json").read_text()
    )
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
