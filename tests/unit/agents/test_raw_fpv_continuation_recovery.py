from __future__ import annotations

import json
from pathlib import Path

from roboclaws.agents.household_live_continuation import IncompleteTurnRecoveryPolicy
from roboclaws.agents.live_runtime import LiveAgentResult
from roboclaws.household.realworld_done_readiness import (
    COMPLETION_SNAPSHOT_SCHEMA,
    completion_snapshot_digest,
)


def test_turn_budget_continuation_carries_public_completion_snapshot(tmp_path: Path) -> None:
    run_dir = tmp_path / "run"
    run_dir.mkdir()
    snapshot = {
        "schema": COMPLETION_SNAPSHOT_SCHEMA,
        "source_tool": "observe",
        "response_id": 3,
        "task_intent": "cleanup",
        "status": "blocked",
        "blockers": [
            {
                "type": "insufficient_raw_fpv_heading_coverage",
                "required_tool": "navigate_to_waypoint",
                "next_waypoint_id": "room_2_inspection",
            }
        ],
        "next_actions": [
            {
                "required_tool": "navigate_to_waypoint",
                "next_waypoint_id": "room_2_inspection",
            }
        ],
        "policy_uses_private_truth": False,
    }
    snapshot["digest"] = completion_snapshot_digest(snapshot)
    (run_dir / "trace.jsonl").write_text(
        json.dumps(
            {
                "event": "response",
                "tool": "observe",
                "response": {"ok": True, "completion": snapshot},
            }
        )
        + "\n",
        encoding="utf-8",
    )

    prompt = IncompleteTurnRecoveryPolicy(max_attempts=2).continuation_prompt(
        original_prompt="ORIGINAL FULL PROMPT",
        result=LiveAgentResult(
            phase="failed",
            exit_status=1,
            reason="agent_sdk_turn_budget_exceeded",
        ),
        run_dir=run_dir,
        attempt_index=0,
        profile={"profile_id": "context_managed_v1"},
        context_metrics={"available": True},
    )

    assert prompt is not None
    assert snapshot["digest"] in prompt
    assert "room_2_inspection" in prompt
    assert "ORIGINAL FULL PROMPT" not in prompt
