from __future__ import annotations

import json

from roboclaws.agents.prompts.household_cleanup import render_kickoff_prompt


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
