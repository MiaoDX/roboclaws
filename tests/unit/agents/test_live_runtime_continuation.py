from __future__ import annotations

import json
from pathlib import Path

import pytest

from roboclaws.agents.household_live_continuation import (
    IncompleteTurnRecoveryPolicy,
    _compact_continuation_profile_guidance,
    _compact_continuation_prompt,
    _compact_continuation_state,
)
from roboclaws.agents.live_runtime import LiveAgentResult
from roboclaws.household.realworld_done_readiness import (
    COMPLETION_SNAPSHOT_SCHEMA,
    completion_snapshot_digest,
)


def _snapshot(*, response_id: int = 1, source_tool: str = "observe") -> dict:
    value = {
        "schema": COMPLETION_SNAPSHOT_SCHEMA,
        "source_tool": source_tool,
        "response_id": response_id,
        "task_intent": "cleanup",
        "status": "blocked",
        "blockers": [
            {
                "type": "pending_cleanup_candidates",
                "required_tool": "navigate_to_waypoint",
                "pending_cleanup_candidates": [
                    {
                        "object_id": "observed_cup",
                        "source_waypoint_id": "room_2_inspection",
                        "generated_inspection_waypoint_id": "generated_inspection_1",
                    }
                ],
            }
        ],
        "next_actions": [
            {
                "required_tool": "navigate_to_waypoint",
                "pending_cleanup_candidates": [
                    {
                        "object_id": "observed_cup",
                        "source_waypoint_id": "room_2_inspection",
                        "generated_inspection_waypoint_id": "generated_inspection_1",
                    }
                ],
            }
        ],
        "policy_uses_private_truth": False,
    }
    value["digest"] = completion_snapshot_digest(value)
    return value


def _write_response(run_dir: Path, snapshot: dict, *, tool: str = "observe") -> None:
    run_dir.mkdir()
    (run_dir / "trace.jsonl").write_text(
        json.dumps(
            {
                "event": "response",
                "tool": tool,
                "response": {"ok": True, "completion": snapshot},
            }
        )
        + "\n",
        encoding="utf-8",
    )


def test_compact_continuation_carries_canonical_snapshot_and_digest(tmp_path: Path) -> None:
    run_dir = tmp_path / "run"
    snapshot = _snapshot()
    _write_response(run_dir, snapshot)

    state = _compact_continuation_state(run_dir, profile={}, context_metrics={})
    prompt = _compact_continuation_prompt(run_dir, profile={}, context_metrics={})

    assert state["completion"] == snapshot
    assert state["completion_digest"] == snapshot["digest"]
    assert "generated_inspection_1" in prompt
    assert "room_2_inspection" in prompt
    assert "latest_done_blockers" not in prompt


@pytest.mark.parametrize("failure", ["missing", "malformed", "stale"])
def test_continuation_state_fails_terminal_incomplete(failure: str, tmp_path: Path) -> None:
    run_dir = tmp_path / "run"
    run_dir.mkdir()
    if failure == "missing":
        response = {"ok": True}
        tool = "observe"
    else:
        snapshot = _snapshot(source_tool="observe")
        if failure == "malformed":
            snapshot["digest"] = "sha256:not-canonical"
            tool = "observe"
        else:
            tool = "metric_map"
        response = {"ok": True, "completion": snapshot}
    (run_dir / "trace.jsonl").write_text(
        json.dumps({"event": "response", "tool": tool, "response": response}) + "\n",
        encoding="utf-8",
    )

    with pytest.raises(RuntimeError, match="terminal-incomplete"):
        _compact_continuation_state(run_dir, profile={}, context_metrics={})


def test_every_sdk_continuation_uses_snapshot_state(tmp_path: Path) -> None:
    run_dir = tmp_path / "run"
    _write_response(run_dir, _snapshot())

    prompt = IncompleteTurnRecoveryPolicy(max_attempts=1).continuation_prompt(
        original_prompt="ORIGINAL FULL PROMPT",
        result=LiveAgentResult(phase="agent-turn-complete", exit_status=0),
        run_dir=run_dir,
        attempt_index=0,
        profile={"continuation_mode": "repeat_full_prompt"},
        context_metrics={},
    )

    assert prompt is not None
    assert "compact_continuation_state" in prompt
    assert "ORIGINAL FULL PROMPT" not in prompt


def test_camera_grounded_continuation_preserves_composite_heading_recovery() -> None:
    guidance = _compact_continuation_profile_guidance(
        {
            "camera_grounded_composite_tools": {
                "enabled": True,
                "tool_names": ["observe_camera_grounded_candidates"],
            }
        }
    )

    assert "insufficient_camera_grounded_heading_coverage" in guidance
    assert "three consecutive" in guidance
    assert "navigate_to_relative_pose(yaw_delta_deg=90)" in guidance
    assert "observe plus declare_visual_candidates" in guidance
    assert "ignore all previously seen object handles" in guidance
    assert "latest completion snapshot returns that handle" in guidance
    assert "Never retry a handle" in guidance
