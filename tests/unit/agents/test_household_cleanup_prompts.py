from __future__ import annotations

import json

from roboclaws.agents.prompts.household_cleanup import (
    render_kickoff_prompt,
    render_map_build_prompt,
)


def test_kickoff_prompt_requires_operator_message_checkpoints() -> None:
    prompt = render_kickoff_prompt("world-public-labels", intent="open-ended")

    assert "Operator steering checkpoint rule" in prompt
    assert "check_operator_messages after metric_map" in prompt
    assert "after each observe" in prompt
    assert "before done" in prompt
    assert "operator_message_pending" in prompt


def test_kickoff_prompt_appends_sanitized_operator_session_context() -> None:
    context = {
        "schema": "operator_console_next_goal_packet_v1",
        "operator_session_id": "session-test",
        "parent_run_id": "parent-run",
        "parent_public_summary": {"status": "done"},
        "artifact_scope": [{"label": "Report", "href": "/artifacts/report.html"}],
        "generated_mess_set": ["private"],
        "acceptable_destination_sets": {"cup": ["private"]},
        "private_manifest": {"secret": True},
        "private_target_truth": "secret",
        "global_movable_object_inventory": ["secret"],
    }

    prompt = render_kickoff_prompt(
        "world-public-labels",
        intent="open-ended",
        operator_session_context_json=json.dumps(context),
    )

    assert "Operator Session follow-up context" in prompt
    assert "operator_console_next_goal_packet_v1" in prompt
    assert "session-test" in prompt
    assert "parent-run" in prompt
    assert "parent_public_summary" in prompt
    assert "artifact_scope" in prompt
    assert "generated_mess_set" not in prompt
    assert "acceptable_destination_sets" not in prompt
    assert "private_manifest" not in prompt
    assert "private_target_truth" not in prompt
    assert "global_movable_object_inventory" not in prompt


def test_map_build_camera_grounded_prompt_uses_composite_cadence_when_enabled() -> None:
    prompt = render_map_build_prompt(
        "camera-grounded-labels",
        "build a Runtime Metric Map",
        camera_grounded_composite_tools=True,
        max_observe_per_waypoint=1,
    )

    assert "observe_camera_grounded_candidates" in prompt
    assert "after navigating to each public inspection waypoint" in prompt
    assert "Use at most one observe_camera_grounded_candidates response per waypoint_id" in prompt
    assert "move to the next public waypoint instead of adjusting pose" in prompt
    assert "do not use navigate_to_relative_pose or camera-adjustment scanning" in prompt
    assert "then observe again" not in prompt
    assert "Do not resume the older observe plus declare_visual_candidates cadence" in prompt
    assert "declare_visual_candidates for each raw FPV observation" not in prompt
    assert "Do not pick, place, place_inside" in prompt


def test_map_build_camera_grounded_baseline_prompt_keeps_two_step_cadence() -> None:
    prompt = render_map_build_prompt(
        "camera-grounded-labels",
        "build a Runtime Metric Map",
        camera_grounded_composite_tools=False,
    )

    assert "navigate_to_waypoint then observe" in prompt
    assert "declare_visual_candidates for each raw FPV observation" in prompt
    assert (
        "after navigating to each public inspection waypoint call "
        "observe_camera_grounded_candidates" not in prompt
    )
