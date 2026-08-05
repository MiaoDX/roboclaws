from __future__ import annotations

import json
from pathlib import Path

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
