from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from roboclaws.agents.drivers.openai_agents_budget import raw_fpv_budget_failure
from roboclaws.household.raw_fpv_recovery import (
    raw_fpv_recovery_exhaustion,
    raw_fpv_recovery_gate,
    raw_fpv_recovery_state,
)


def test_same_progress_done_does_not_reopen_bounded_revisit_epoch() -> None:
    events = [
        _response(
            "metric_map",
            inspection_waypoints=[
                {"waypoint_id": "room_2_inspection"},
                {"waypoint_id": "room_3_inspection"},
            ],
        ),
        _blocked_done(current=2, required=4),
        _response("navigate_to_waypoint", waypoint_id="room_2_inspection"),
        _response(
            "navigate_to_relative_pose",
            applied_delta={"forward_m": 0, "lateral_m": 0, "yaw_delta_deg": 45},
        ),
        _response(
            "observe",
            waypoint_id="room_2_inspection",
            raw_fpv_observation={"observation_id": "raw_fpv_020"},
        ),
        _blocked_done(current=2, required=4),
    ]

    state = raw_fpv_recovery_state(
        events,
        evidence_lane="camera-raw-fpv",
        task_intent="cleanup",
    )

    assert state["epoch_event_index"] == 1
    assert state["consumed_waypoint_ids"] == ["room_2_inspection"]
    assert state["eligible_waypoint_ids"] == ["room_3_inspection"]
    blocked = raw_fpv_recovery_gate(
        events,
        evidence_lane="camera-raw-fpv",
        task_intent="cleanup",
        tool="navigate_to_waypoint",
        request={"waypoint_id": "room_2_inspection"},
    )
    assert blocked is not None
    assert blocked["error_reason"] == "raw_fpv_recovery_waypoint_consumed"


def test_revisit_candidate_requires_unused_fresh_observation() -> None:
    events = [
        _response(
            "metric_map",
            inspection_waypoints=[{"waypoint_id": "room_2_inspection"}],
        ),
        _blocked_done(current=1, required=2),
        _response("navigate_to_waypoint", waypoint_id="room_2_inspection"),
        _response(
            "navigate_to_relative_pose",
            applied_delta={"forward_m": 0, "lateral_m": 0, "yaw_delta_deg": 45},
        ),
        _response(
            "observe",
            waypoint_id="room_2_inspection",
            raw_fpv_observation={"observation_id": "raw_fpv_fresh"},
        ),
    ]

    stale = raw_fpv_recovery_gate(
        events,
        evidence_lane="camera-raw-fpv",
        task_intent="cleanup",
        tool="navigate_to_visual_candidate",
        request={"source_observation_id": "raw_fpv_old"},
    )
    assert stale is not None
    assert stale["error_reason"] == "raw_fpv_recovery_stale_observation"

    assert (
        raw_fpv_recovery_gate(
            events,
            evidence_lane="camera-raw-fpv",
            task_intent="cleanup",
            tool="navigate_to_visual_candidate",
            request={"source_observation_id": "raw_fpv_fresh"},
        )
        is None
    )
    events.append(
        {
            "event": "request",
            "tool": "navigate_to_visual_candidate",
            "request": {"source_observation_id": "raw_fpv_fresh"},
        }
    )
    repeated = raw_fpv_recovery_gate(
        events,
        evidence_lane="camera-raw-fpv",
        task_intent="cleanup",
        tool="navigate_to_visual_candidate",
        request={"source_observation_id": "raw_fpv_fresh"},
    )
    assert repeated is not None
    assert repeated["error_reason"] == "raw_fpv_recovery_observation_consumed"


def test_gate_is_inactive_outside_raw_fpv_cleanup() -> None:
    events = [_blocked_done(current=0, required=4)]
    for lane, intent in (
        ("world-public-labels", "cleanup"),
        ("camera-raw-fpv", "open-ended"),
    ):
        assert (
            raw_fpv_recovery_gate(
                events,
                evidence_lane=lane,
                task_intent=intent,
                tool="navigate_to_waypoint",
                request={"waypoint_id": "room_2_inspection"},
            )
            is None
        )


def test_recovery_allows_public_manipulation_chain_but_blocks_no_progress_done() -> None:
    events = [
        _response(
            "metric_map",
            inspection_waypoints=[{"waypoint_id": "room_2_inspection"}],
        ),
        _blocked_done(current=1, required=2),
    ]
    assert (
        raw_fpv_recovery_gate(
            events,
            evidence_lane="camera-raw-fpv",
            task_intent="cleanup",
            tool="pick",
            request={"object_id": "observed_001"},
        )
        is None
    )
    blocked_done = raw_fpv_recovery_gate(
        events,
        evidence_lane="camera-raw-fpv",
        task_intent="cleanup",
        tool="done",
        request={"reason": "retry without public progress"},
    )
    assert blocked_done is not None
    assert blocked_done["error_reason"] == "done_without_public_progress"


def test_final_same_progress_done_marks_empty_recovery_epoch_exhausted(
    tmp_path: Path,
) -> None:
    events = [
        {
            "event": "molmo_realworld_cleanup_mcp_initialized",
            "goal_contract": {"intent": "cleanup"},
        },
        _response(
            "metric_map",
            inspection_waypoints=[{"waypoint_id": "room_2_inspection"}],
        ),
        _blocked_done(current=2, required=4),
        _response("navigate_to_waypoint", waypoint_id="room_2_inspection"),
        _response(
            "navigate_to_relative_pose",
            applied_delta={"forward_m": 0, "lateral_m": 0, "yaw_delta_deg": 45},
        ),
        _response(
            "observe",
            waypoint_id="room_2_inspection",
            raw_fpv_observation={"observation_id": "raw_fpv_final"},
        ),
        _blocked_done(current=2, required=4),
    ]

    exhaustion = raw_fpv_recovery_exhaustion(
        events,
        evidence_lane="camera-raw-fpv",
    )
    assert exhaustion is not None
    assert exhaustion["reason"] == "raw_fpv_recovery_exhausted"
    assert exhaustion["consumed_waypoint_ids"] == ["room_2_inspection"]
    assert exhaustion["policy_uses_private_truth"] is False

    run_dir = tmp_path / "run"
    run_dir.mkdir()
    (run_dir / "trace.jsonl").write_text(
        "\n".join(json.dumps(event) for event in events) + "\n",
        encoding="utf-8",
    )
    failure = raw_fpv_budget_failure(
        run_dir,
        {"evidence_lane": "camera-raw-fpv"},
        {"profile_id": "context_managed_v1"},
    )
    assert failure is not None
    assert failure.reason == "raw_fpv_recovery_exhausted"
    assert failure.retryable is False
    detail = json.loads(failure.detail)
    assert detail["schema"] == "raw_fpv_recovery_exhausted_v1"
    assert detail["progress_fingerprint"] == {
        "grounded_cleanup_chains": 2,
        "required": 4,
    }

    pending_events = json.loads(json.dumps(events))
    pending_events[-1]["response"]["completion"]["blockers"].insert(
        0,
        {
            "type": "pending_cleanup_candidates",
            "pending_cleanup_candidates": [{"object_id": "observed_public", "state": "held"}],
        },
    )
    assert (
        raw_fpv_recovery_exhaustion(
            pending_events,
            evidence_lane="camera-raw-fpv",
        )
        is None
    )


def _response(tool: str, **payload: Any) -> dict[str, Any]:
    return {"event": "response", "tool": tool, "response": {"ok": True, **payload}}


def _blocked_done(*, current: int, required: int) -> dict[str, Any]:
    return {
        "event": "response",
        "tool": "done",
        "response": {
            "ok": False,
            "status": "blocked",
            "completion": {
                "blockers": [
                    {
                        "type": "insufficient_grounded_cleanup_chains",
                        "current": current,
                        "required": required,
                    }
                ]
            },
        },
    }
