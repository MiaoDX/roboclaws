from __future__ import annotations

import json
from pathlib import Path

from roboclaws.agents.household_live_config import build_household_prompt_identity
from roboclaws.agents.prompts.household_cleanup import (
    render_kickoff_prompt,
    render_map_build_prompt,
)

REPO_ROOT = Path(__file__).resolve().parents[3]


def test_kickoff_prompt_requires_operator_message_checkpoints() -> None:
    prompt = render_kickoff_prompt("world-public-labels", intent="open-ended")

    assert "Operator steering checkpoint rule" in prompt
    assert "check_operator_messages after metric_map" in prompt
    assert "after each observe" in prompt
    assert "before done" in prompt
    assert "operator_message_pending" in prompt


def test_skill_owns_generic_strategy_while_kickoff_owns_run_context() -> None:
    skill = (REPO_ROOT / "skills" / "household-world" / "SKILL.md").read_text(encoding="utf-8")
    prompt = render_kickoff_prompt("world-public-labels")

    assert "canonical owner of generic search, sweep, manipulation" in skill
    assert "Build an exact checklist" in skill
    assert "navigate_to_object(object_id)" in skill
    assert "pending_cleanup_candidates" in skill
    assert "Evidence lane=world-public-labels" in prompt
    assert "Required closeout artifacts" in prompt
    assert "navigate_to_object" not in prompt
    assert "pending_cleanup_candidates" not in prompt


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


def test_composed_prompt_identity_contains_only_public_digests(monkeypatch) -> None:
    prompt = render_kickoff_prompt("world-public-labels", task="PRIVATE TASK BODY")
    monkeypatch.setattr(
        "roboclaws.agents.household_live_config._source_git_sha", lambda _root: "a" * 40
    )

    identity = build_household_prompt_identity(
        repo_root=REPO_ROOT,
        prompt=prompt,
        prompt_source="profile-rendered-lane-default",
        intent="cleanup",
        skill_context={"sha256": "b" * 64},
    )

    projection = identity.projection()
    assert projection["prompt_template_name"] == "household-cleanup-kickoff"
    assert projection["prompt_variable_schema"] == "household-cleanup-kickoff-variables/v1"
    assert projection["prompt_rendered_sha256"]
    assert "PRIVATE TASK BODY" not in json.dumps(projection)


def test_open_ended_prompt_identity_is_not_labeled_as_cleanup(monkeypatch) -> None:
    monkeypatch.setattr(
        "roboclaws.agents.household_live_config._source_git_sha", lambda _root: "a" * 40
    )

    identity = build_household_prompt_identity(
        repo_root=REPO_ROOT,
        prompt=render_kickoff_prompt("world-public-labels", intent="open-ended"),
        prompt_source="profile-rendered-lane-default",
        intent="open-ended",
        skill_context={"sha256": "b" * 64},
    )

    assert identity.template_name == "household-open-ended-kickoff"
    assert identity.variable_schema == "household-open-ended-kickoff-variables/v1"


def test_map_build_camera_grounded_prompt_uses_composite_cadence_when_enabled() -> None:
    prompt = render_map_build_prompt(
        "camera-grounded-labels",
        "build a Runtime Metric Map",
        camera_grounded_composite_tools=True,
        max_observe_per_waypoint=1,
    )

    assert "observe_camera_grounded_candidates" in prompt
    assert "Waypoint observation tool=observe_camera_grounded_candidates" in prompt
    assert "Per-waypoint observation budget=1" in prompt
    assert "Camera-grounded observation mode=composite" in prompt
    assert "response already includes the server-side declaration" in prompt
    assert (
        "do not call declare_visual_candidates again for the same source_observation_id" in prompt
    )
    assert "profile observe cadence=5 per waypoint" in prompt
    assert "effective observe cadence=1 per waypoint" in prompt
    assert "max_observe_per_waypoint override=true" in prompt
    assert "profile body-turn cadence overridden=true" in prompt
    assert "bounded re-observation" not in prompt
    assert "multi-heading scanning" not in prompt
    assert "Manipulation tools are not entitled for this run" in prompt
    assert "blocked_capability" not in prompt


def test_map_build_camera_grounded_baseline_prompt_keeps_two_step_cadence() -> None:
    prompt = render_map_build_prompt(
        "camera-grounded-labels",
        "build a Runtime Metric Map",
        camera_grounded_composite_tools=False,
    )

    assert "Waypoint observation tool=observe" in prompt
    assert "Camera-grounded observation mode=observe plus declare_visual_candidates" in prompt
    assert "Per-waypoint observation budget=5" in prompt
    assert "profile observe cadence=5 per waypoint" in prompt
    assert "effective observe cadence=5 per waypoint" in prompt
    assert "max_observe_per_waypoint override=false" in prompt
    assert "profile body-turn cadence overridden=false" in prompt
    assert "Waypoint observation tool=observe_camera_grounded_candidates" not in prompt


def test_cleanup_camera_grounded_composite_prompt_requires_bounded_heading_sweep() -> None:
    prompt = render_kickoff_prompt(
        "camera-grounded-labels",
        intent="cleanup",
        camera_grounded_composite_tools=True,
    )

    assert "At every public inspection waypoint" in prompt
    assert "three bounded 90-degree body turns" in prompt
    assert "calling the composite tool after each turn" in prompt
