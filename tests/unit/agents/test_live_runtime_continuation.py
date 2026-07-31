from __future__ import annotations

import json
from pathlib import Path

from roboclaws.agents.household_live_continuation import (
    IncompleteTurnRecoveryPolicy,
    _compact_continuation_prompt,
    _compact_continuation_state,
)
from roboclaws.agents.live_runtime import (
    LiveAgentResult,
)


def test_raw_fpv_compact_continuation_preserves_scan_progress_and_done_blockers(
    tmp_path: Path,
) -> None:
    run_dir = tmp_path / "run"
    run_dir.mkdir()
    events = [
        {
            "event": "molmo_realworld_cleanup_mcp_initialized",
            "evidence_lane": "camera-raw-fpv",
            "goal_contract": {
                "surface": "household-world",
                "intent": "cleanup",
                "normalized_goal": "clean the room",
            },
        },
        {
            "event": "response",
            "tool": "observe",
            "response": {"ok": True, "waypoint_id": "room_2_inspection"},
        },
        {
            "event": "response",
            "tool": "observe",
            "response": {"ok": True, "waypoint_id": "room_2_inspection"},
        },
        {
            "event": "response",
            "tool": "observe",
            "response": {"ok": True, "waypoint_id": "room_3_inspection"},
        },
        {
            "event": "response",
            "tool": "done",
            "response": {
                "ok": False,
                "status": "blocked",
                "completion": {
                    "blockers": [
                        {
                            "type": "insufficient_grounded_cleanup_chains",
                            "current": 2,
                            "required": 4,
                            "required_tool": "navigate_to_visual_candidate",
                            "recovery_hint": "continue the cleanup loop",
                        }
                    ]
                },
            },
        },
    ]
    (run_dir / "trace.jsonl").write_text(
        "\n".join(json.dumps(event) for event in events) + "\n",
        encoding="utf-8",
    )

    prompt = _compact_continuation_prompt(
        run_dir,
        profile={"profile_id": "context_managed_v1", "raw_fpv_candidate_budget": 24},
        context_metrics={},
    )

    assert "RAW-FPV continuation" in prompt
    assert "do not call done again" in prompt
    assert '"room_2_inspection": 2' in prompt
    assert '"room_3_inspection": 1' in prompt
    assert '"current": 2' in prompt
    assert '"required": 4' in prompt
    assert (
        prompt.count("navigate_to_relative_pose(forward_m=0, lateral_m=0, yaw_delta_deg=90)") == 1
    )
    assert (
        "visit each listed waypoint at most once, call "
        "navigate_to_relative_pose(forward_m=0, lateral_m=0, yaw_delta_deg=45) once" in prompt
    )
    assert "left, right, bottom, or top FPV edge" in prompt
    assert "for a left-edge candidate use yaw_delta_deg=45" in prompt
    assert "for a right-edge candidate use yaw_delta_deg=-45" in prompt
    assert "for a bottom-edge candidate use pitch_delta_deg=20" in prompt
    assert "for a top-edge candidate use pitch_delta_deg=-20" in prompt
    assert "overlap without a clear edge direction" in prompt
    assert "never reuse the original sliver bbox" in prompt
    assert "insufficient_raw_fpv_overlap_probe_coverage" in prompt
    assert "adjust_camera(yaw_delta_deg=45, pitch_delta_deg=20) once" in prompt
    assert "normal waypoint observe count is exhausted" in prompt


def test_compact_continuation_preserves_latest_public_actionable_done_state(
    tmp_path: Path,
) -> None:
    run_dir = tmp_path / "run"
    run_dir.mkdir()
    destination = {
        "candidate_fixture_id": "anchor_fixture_fridge",
        "candidate_fixture_category": "fridge",
        "recommended_tool": "place_inside",
        "candidate_source": "runtime_public_semantic_anchor",
        "waypoint_id": "room_3_inspection",
        "private_fixture_id": "fixture_private_1",
    }
    events = [
        {
            "event": "response",
            "tool": "done",
            "response": {
                "ok": False,
                "completion": {
                    "blockers": [
                        {
                            "type": "pending_cleanup_candidates",
                            "pending_cleanup_candidates": [
                                {"object_id": "stale_object", "state": "pending"}
                            ],
                        }
                    ]
                },
            },
        },
        {
            "event": "response",
            "tool": "done",
            "response": {
                "ok": False,
                "completion": {
                    "blockers": [
                        {
                            "type": "pending_cleanup_candidates",
                            "required_tool": "navigate_to_receptacle",
                            "pending_cleanup_candidates": [
                                {
                                    "object_id": "observed_pending",
                                    "category": "cup",
                                    "state": "pending",
                                    "candidate_state": "navigation_authorized",
                                    "required_tool": "navigate_to_object",
                                    "private_target_id": "target_private_1",
                                },
                                {
                                    "object_id": "observed_held",
                                    "category": "food",
                                    "state": "held",
                                    "candidate_state": "navigation_authorized",
                                    "required_tool": "navigate_to_receptacle",
                                    "destination_options": [destination],
                                },
                            ],
                        },
                        {
                            "type": "insufficient_sweep_coverage",
                            "required_tool": "navigate_to_waypoint",
                            "next_waypoint_id": "room_4_inspection",
                            "unvisited_waypoint_ids": [
                                "room_4_inspection",
                                "room_5_inspection",
                            ],
                        },
                    ]
                },
            },
        },
    ]
    (run_dir / "trace.jsonl").write_text(
        "\n".join(json.dumps(event) for event in events) + "\n",
        encoding="utf-8",
    )

    state = _compact_continuation_state(run_dir, profile={}, context_metrics={})
    prompt = _compact_continuation_prompt(run_dir, profile={}, context_metrics={})

    assert [item["object_id"] for item in state["actionable_pending_candidates"]] == [
        "observed_held",
        "observed_pending",
    ]
    assert state["actionable_pending_candidates"][0]["destination_options"] == [
        {key: value for key, value in destination.items() if key != "private_fixture_id"}
    ]
    assert "private_target_id" not in json.dumps(state)
    assert "stale_object" not in json.dumps(state)
    assert state["next_unvisited_waypoint"] == "room_4_inspection"
    assert state["unvisited_waypoint_ids"] == [
        "room_4_inspection",
        "room_5_inspection",
    ]
    assert state["next_requested_action"] == (
        "finish held candidates using public destination_options before other work"
    )
    assert "first finish held entries" in prompt
    assert "then advance pending entries" in prompt
    assert "then continue the public sweep" in prompt


def test_raw_fpv_compact_continuation_reconciles_scan_and_candidate_progress(
    tmp_path: Path,
) -> None:
    run_dir = tmp_path / "run"
    run_dir.mkdir()
    events: list[dict[str, object]] = []
    for waypoint_id in ("room_2_inspection", "room_3_inspection"):
        for _ in range(4):
            events.append(
                {
                    "event": "response",
                    "tool": "observe",
                    "response": {"ok": True, "waypoint_id": waypoint_id},
                }
            )
    events.extend(
        [
            {
                "event": "response",
                "tool": "observe",
                "response": {"ok": False, "waypoint_id": "room_4_inspection"},
            },
            {
                "event": "request",
                "tool": "navigate_to_visual_candidate",
                "request": {
                    "source_observation_id": "raw_fpv_001",
                    "category": "cup",
                    "image_region": {"type": "bbox", "value": [10, 20, 30, 40]},
                },
            },
            {
                "event": "response",
                "tool": "navigate_to_visual_candidate",
                "response": {
                    "ok": False,
                    "status": "error",
                    "error_reason": "visual_candidate_not_resolved",
                    "object_id": "observed_001",
                },
            },
            {
                "event": "response",
                "tool": "done",
                "response": {
                    "ok": False,
                    "status": "blocked",
                    "completion": {
                        "blockers": [
                            {
                                "type": "insufficient_grounded_cleanup_chains",
                                "current": 1,
                                "required": 4,
                            },
                            {
                                "type": "insufficient_waypoint_coverage",
                                "current": 1,
                                "required": 3,
                            },
                        ]
                    },
                },
            },
            {
                "event": "response",
                "tool": "place",
                "response": {"ok": True, "status": "ok", "object_id": "observed_002"},
            },
            {
                "event": "response",
                "tool": "place",
                "response": {"ok": False, "status": "error", "object_id": "observed_bad"},
            },
        ]
    )
    (run_dir / "trace.jsonl").write_text(
        "\n".join(json.dumps(event) for event in events) + "\n",
        encoding="utf-8",
    )
    profile = {
        "profile_id": "context_managed_v1",
        "raw_fpv_candidate_budget": 24,
        "max_observe_per_waypoint": 4,
    }

    state = _compact_continuation_state(run_dir, profile=profile, context_metrics={})
    prompt = _compact_continuation_prompt(run_dir, profile=profile, context_metrics={})

    assert state["completed_waypoints"] == ["room_2_inspection", "room_3_inspection"]
    assert state["scan_exhausted_waypoints"] == ["room_2_inspection", "room_3_inspection"]
    assert state["remaining_observes_by_waypoint"] == {
        "room_2_inspection": 0,
        "room_3_inspection": 0,
    }
    assert state["raw_fpv_candidate_budget"] == {
        "attempted": 1,
        "limit": 24,
        "remaining": 23,
    }
    assert state["handled_object_handles"] == ["observed_002"]
    assert state["latest_done_blockers"][0]["current"] == 2
    assert state["latest_done_blockers"][0]["progress_source"] == ("trace_reconciled_after_done")
    assert state["latest_done_blockers"][1] == {
        "type": "insufficient_waypoint_coverage",
        "current": 1,
        "required": 3,
    }
    assert state["recent_failed_candidate_attempts"][0]["error_reason"] == (
        "visual_candidate_not_resolved"
    )
    assert "do not broad re-sweep exhausted waypoints" in prompt.lower()


def test_raw_fpv_compact_continuation_prioritizes_candidate_free_waypoints(
    tmp_path: Path,
) -> None:
    run_dir = tmp_path / "run"
    run_dir.mkdir()
    events = [
        {
            "event": "response",
            "tool": "metric_map",
            "response": {
                "ok": True,
                "inspection_waypoints": [
                    {"waypoint_id": "room_2_inspection"},
                    {"waypoint_id": "room_3_inspection"},
                    {"waypoint_id": "room_8_inspection"},
                ],
            },
        },
        {
            "event": "response",
            "tool": "observe",
            "response": {
                "ok": True,
                "waypoint_id": "room_2_inspection",
                "raw_fpv_observation": {"observation_id": "raw_fpv_001"},
            },
        },
        {
            "event": "request",
            "tool": "navigate_to_visual_candidate",
            "request": {"source_observation_id": "raw_fpv_001", "category": "plate"},
        },
        {
            "event": "response",
            "tool": "observe",
            "response": {
                "ok": True,
                "waypoint_id": "room_3_inspection",
                "raw_fpv_observation": {"observation_id": "raw_fpv_003"},
            },
        },
        {
            "event": "response",
            "tool": "observe",
            "response": {
                "ok": True,
                "waypoint_id": "room_8_inspection",
                "compact_observation": {"raw_fpv_observation": {"observation_id": "raw_fpv_002"}},
            },
        },
    ]
    (run_dir / "trace.jsonl").write_text(
        "\n".join(json.dumps(event) for event in events) + "\n",
        encoding="utf-8",
    )
    profile = {
        "profile_id": "context_managed_v1",
        "raw_fpv_candidate_budget": 24,
        "max_observe_per_waypoint": 4,
    }

    state = _compact_continuation_state(run_dir, profile=profile, context_metrics={})
    prompt = _compact_continuation_prompt(run_dir, profile=profile, context_metrics={})

    assert state["candidate_attempt_counts_by_waypoint"] == {"room_2_inspection": 1}
    assert state["candidate_free_scan_waypoints"] == [
        "room_8_inspection",
        "room_3_inspection",
    ]
    assert "Prefer candidate_free_scan_waypoints" in prompt
    assert "empty default fpv view is not evidence" in prompt.lower()


def test_incomplete_turn_recovery_compacts_after_context_soft_limit(tmp_path: Path) -> None:
    run_dir = tmp_path / "run"
    run_dir.mkdir()
    (run_dir / "trace.jsonl").write_text(
        json.dumps(
            {
                "event": "molmo_realworld_cleanup_mcp_initialized",
                "evidence_lane": "world-public-labels",
                "goal_contract": {
                    "surface": "household-world",
                    "intent": "cleanup",
                    "normalized_goal": "clean the room",
                },
            }
        )
        + "\n",
        encoding="utf-8",
    )
    result = LiveAgentResult(phase="agent-turn-complete", exit_status=0)

    prompt = IncompleteTurnRecoveryPolicy(max_attempts=1).continuation_prompt(
        original_prompt="ORIGINAL FULL PROMPT",
        result=result,
        run_dir=run_dir,
        attempt_index=0,
        profile={
            "profile_id": "baseline",
            "continuation_mode": "repeat_full_prompt",
            "context_soft_limit_tokens": 100,
        },
        context_metrics={"available": True, "total_input_tokens": 100},
    )

    assert prompt is not None
    assert "compact_continuation_state" in prompt
    assert "ORIGINAL FULL PROMPT" not in prompt


def test_compact_continuation_preserves_map_build_intent(tmp_path: Path) -> None:
    run_dir = tmp_path / "run"
    run_dir.mkdir()
    (run_dir / "trace.jsonl").write_text(
        json.dumps(
            {
                "event": "molmo_realworld_cleanup_mcp_initialized",
                "evidence_lane": "world-public-labels",
                "goal_contract": {
                    "surface": "household-world",
                    "intent": "map-build",
                    "normalized_goal": "build runtime map evidence",
                },
            }
        )
        + "\n",
        encoding="utf-8",
    )

    prompt = _compact_continuation_prompt(
        run_dir,
        profile={"profile_id": "context_managed_v1"},
        context_metrics={},
    )

    assert "same live household map-build run" in prompt
    assert "Continue only missing public map sweep" in prompt
    assert "Do not pick, place, or perform cleanup manipulation" in prompt
    assert "continue only missing cleanup work" not in prompt
