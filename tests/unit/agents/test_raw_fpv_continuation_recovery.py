from __future__ import annotations

import json
from pathlib import Path

from roboclaws.agents.live_runtime import LiveAgentResult
from scripts.molmo_cleanup.run_live_openai_agents_cleanup import (
    IncompleteTurnRecoveryPolicy,
    _compact_continuation_state,
)


def test_turn_budget_result_recovers_with_compact_continuation(tmp_path: Path) -> None:
    run_dir = tmp_path / "run"
    run_dir.mkdir()
    _write_trace(
        run_dir,
        [
            {
                "event": "molmo_realworld_cleanup_mcp_initialized",
                "evidence_lane": "camera-raw-fpv",
                "goal_contract": {
                    "surface": "household-world",
                    "intent": "cleanup",
                    "normalized_goal": "clean the room",
                },
            }
        ],
    )
    result = LiveAgentResult(
        phase="failed",
        exit_status=1,
        reason="agent_sdk_turn_budget_exceeded",
    )

    prompt = IncompleteTurnRecoveryPolicy(max_attempts=2).continuation_prompt(
        original_prompt="ORIGINAL FULL PROMPT",
        result=result,
        run_dir=run_dir,
        attempt_index=0,
        profile={
            "profile_id": "context_managed_v1",
            "continuation_mode": "state_summary_only",
            "raw_fpv_candidate_budget": 24,
        },
        context_metrics={"available": True, "max_input_tokens": 53_694},
    )

    assert prompt is not None
    assert "compact_continuation_state" in prompt
    assert "RAW-FPV continuation" in prompt
    assert "ORIGINAL FULL PROMPT" not in prompt


def test_heading_blocker_overrides_raw_observe_exhaustion(tmp_path: Path) -> None:
    run_dir = tmp_path / "run"
    run_dir.mkdir()
    events: list[dict[str, object]] = [
        {
            "event": "response",
            "tool": "metric_map",
            "response": {
                "inspection_waypoints": [
                    {"waypoint_id": "room_2_inspection"},
                    {"waypoint_id": "room_3_inspection"},
                ]
            },
        }
    ]
    for waypoint_id in ("room_2_inspection", "room_3_inspection"):
        for _ in range(4):
            events.append(
                {
                    "event": "response",
                    "tool": "observe",
                    "response": {"ok": True, "waypoint_id": waypoint_id},
                }
            )
    events.append(
        {
            "event": "response",
            "tool": "done",
            "response": {
                "completion": {
                    "blockers": [
                        {
                            "type": "insufficient_raw_fpv_heading_coverage",
                            "current_distinct_heading_count": 3,
                            "required_distinct_heading_count": 4,
                            "distinct_heading_counts_by_waypoint": {
                                "room_2_inspection": 3,
                                "room_3_inspection": 4,
                            },
                            "incomplete_waypoint_ids": ["room_2_inspection"],
                            "next_waypoint_id": "room_2_inspection",
                            "required_tool": "navigate_to_waypoint",
                        }
                    ]
                }
            },
        }
    )
    _write_trace(run_dir, events)

    state = _compact_continuation_state(
        run_dir,
        profile={"max_observe_per_waypoint": 4, "raw_fpv_candidate_budget": 24},
        context_metrics={},
    )

    assert state["remaining_observes_by_waypoint"] == {
        "room_2_inspection": 1,
        "room_3_inspection": 0,
    }
    assert state["scan_exhausted_waypoints"] == ["room_3_inspection"]
    assert state["latest_done_blockers"][0]["distinct_heading_counts_by_waypoint"] == {
        "room_2_inspection": 3,
        "room_3_inspection": 4,
    }


def _write_trace(run_dir: Path, events: list[dict[str, object]]) -> None:
    (run_dir / "trace.jsonl").write_text(
        "\n".join(json.dumps(event) for event in events) + "\n",
        encoding="utf-8",
    )
