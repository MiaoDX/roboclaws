from __future__ import annotations

from roboclaws.agents.prompts.household_cleanup import (
    render_kickoff_prompt,
    render_map_build_prompt,
)
from tests.contract.dev_tools.task_agent_just_recipes_support import (
    MOLMO_JUST,
)


def test_molmo_camera_raw_prompt_contains_run_constraints_not_generic_strategy() -> None:
    prompt = render_kickoff_prompt("camera-raw-fpv")

    assert "cleanup MCP tool entries exactly as exposed by Codex" in prompt
    assert "namespace cleanup" in prompt
    assert "server named cleanup" not in prompt
    assert "never mcp__cleanup__" in prompt
    assert "Per-waypoint observation budget=4" in prompt
    assert "Evidence lane=camera-raw-fpv" in prompt
    assert "Raw-FPV candidate-attempt budget=24" in prompt
    assert "Cleanup target cap=7" in prompt
    assert "Done retry budget=1" in prompt
    assert "navigate_to_relative_pose" not in prompt
    assert "overlap probe" not in prompt
    assert "Required closeout artifacts" in prompt
    assert "place/place_inside" not in prompt


def test_molmo_camera_raw_prompt_scales_to_requested_cleanup_count() -> None:
    prompt = render_kickoff_prompt("camera-raw-fpv", target_cleanup_count=5)

    assert "Cleanup target cap=5" in prompt
    assert "at least seven grounded cleanup chains have succeeded" not in prompt


def test_molmo_live_kickoff_prompt_receives_success_threshold_for_camera_raw() -> None:
    text = MOLMO_JUST.read_text(encoding="utf-8")

    assert 'prompt_cleanup_count="$generated_mess_count"' in text
    assert 'prompt_cleanup_count="$generated_mess_success_threshold"' in text
    assert '--target-cleanup-count "$prompt_cleanup_count"' in text
    assert "--task-intent-mode" not in text


def test_molmo_world_labels_prompt_requires_nav2_bundle_checklist() -> None:
    prompt = render_kickoff_prompt("world-public-labels")

    assert "This run is surface=household-world intent=cleanup" in prompt
    assert "User task: clean up this room" in prompt
    assert "Evidence lane=world-public-labels" in prompt
    assert "visible_object_detections" in prompt
    assert "private destination truth" in prompt
    assert "cleanup MCP tool entries exactly as exposed by Codex" in prompt
    assert "namespace cleanup" in prompt
    assert "server named cleanup" not in prompt
    assert "never mcp__cleanup__" in prompt
    assert "roboclaws__" in prompt
    assert "Required closeout artifacts" in prompt
    assert "navigate_to_waypoint" not in prompt


def test_molmo_cleanup_live_prompt_includes_open_ended_user_task() -> None:
    prompt = render_kickoff_prompt(
        "world-public-labels",
        task="我渴了，帮我找些解渴的东西",
        intent="open-ended",
    )

    assert "This run is surface=household-world with no task preset" in prompt
    assert "custom operator task" not in prompt
    assert "The following operator task is authoritative" in prompt
    assert "我渴了，帮我找些解渴的东西" in prompt
    assert "Evidence lane=world-public-labels" in prompt
    assert "Use the MCP tools as a bounded household robot capability surface" in prompt
    assert "Use the household MCP tool entries exactly as exposed by Codex" in prompt
    assert "Use the bundled household-world skill instructions" in prompt
    assert "cleanup MCP tool entries exactly as exposed by Codex" not in prompt
    assert "room-cleanup routine" not in prompt
    assert "visual-scan prerequisite" not in prompt
    assert "unrelated pending cleanup candidates" not in prompt
    assert "cleanup goals from cleanup implementation details" not in prompt
    assert "build an exact waypoint checklist" not in prompt
    assert "sweep every waypoint" not in prompt
    assert "fresh same-handle source FPV observation" not in prompt
    assert "cleaned every public recommended candidate" not in prompt
    assert "call done only after every metric_map.inspection_waypoints" not in prompt


def test_molmo_open_ended_camera_grounded_prompt_requires_label_declaration() -> None:
    prompt = render_kickoff_prompt(
        "camera-grounded-labels",
        task=(
            "巡检 B1 / Map 12 digital twin，使用相机 grounded label "
            "证据报告你看到的至少一个公开候选目标，并在证据足够后调用 done。"
        ),
        intent="open-ended",
    )

    assert "This run is surface=household-world with no task preset" in prompt
    assert "Camera-grounded observation mode=observe plus" in prompt
    assert "declare_visual_candidates with observation_id only" in prompt
    assert "configured camera labeler labels the frame" not in prompt
    assert "Required closeout artifacts" in prompt


def test_molmo_open_ended_camera_grounded_prompt_can_use_composite_tool() -> None:
    prompt = render_kickoff_prompt(
        "camera-grounded-labels",
        task="inspect B1 camera grounded candidates",
        intent="open-ended",
        camera_grounded_composite_tools=True,
    )

    assert "Camera-grounded observation mode=composite" in prompt
    assert "observe_camera_grounded_candidates" in prompt
    assert "configured camera labeler labels the current FPV frame" not in prompt


def test_molmo_cleanup_live_prompt_uses_cleanup_intent_without_open_ended_intent() -> None:
    prompt = render_kickoff_prompt(
        "world-public-labels",
        task="我渴了，帮我找些解渴的东西",
    )

    assert "This run is surface=household-world intent=cleanup" in prompt
    assert "This run is surface=household-world with no task preset" not in prompt
    assert "The operator task is the only goal" not in prompt
    assert "Use the bundled household-world skill instructions" in prompt


def test_molmo_world_labels_prompt_uses_single_lane_default() -> None:
    prompt = render_kickoff_prompt("world-public-labels")

    assert "Evidence lane=world-public-labels" in prompt
    assert "visible_object_detections" in prompt
    assert "navigate_to_waypoint then observe" not in prompt
    assert "pending_cleanup_candidates" not in prompt
    assert "cleanup_recommended" not in prompt
    assert "first complete an anchor discovery sweep" not in prompt


def test_molmo_label_prompts_keep_public_done_boundary() -> None:
    world_prompt = render_kickoff_prompt("world-public-labels")
    camera_prompt = render_kickoff_prompt("camera-grounded-labels")

    assert "Evidence lane=world-public-labels" in world_prompt
    assert "observe -> candidate decision" not in world_prompt
    assert "pending_cleanup_candidates" not in world_prompt
    assert "only the MCP done response creates the authoritative run result" in world_prompt
    assert "Evidence lane=camera-grounded-labels" in camera_prompt
    assert "declare_visual_candidates with observation_id only" in camera_prompt
    assert "only the MCP done response creates the authoritative run result" in camera_prompt


def test_molmo_compact_camera_prompt_can_prefer_composite_observe_tool() -> None:
    prompt = render_kickoff_prompt(
        "camera-grounded-labels",
        camera_grounded_composite_tools=True,
    )

    assert "Camera-grounded observation mode=composite" in prompt
    assert "observe_camera_grounded_candidates" in prompt
    assert "response already includes the server-side declaration" in prompt
    assert (
        "do not call declare_visual_candidates again for the same source_observation_id" in prompt
    )
    assert "only the MCP done response creates the authoritative run result" in prompt


def test_molmo_just_openai_agents_composite_env_forwards_prompt_flag() -> None:
    text = MOLMO_JUST.read_text(encoding="utf-8")

    assert "ROBOCLAWS_OPENAI_AGENTS_CAMERA_GROUNDED_COMPOSITE_TOOLS" in text
    assert "prompt_args+=(--camera-grounded-composite-tools)" in text
    assert (
        '[[ "$driver" == "openai-agents-live" && "$profile" == "camera-grounded-labels" ]]' in text
    )


def test_molmo_raw_fpv_compact_prompt_includes_budget_contract() -> None:
    prompt = render_kickoff_prompt(
        "camera-raw-fpv",
        target_cleanup_count=5,
        raw_fpv_candidate_budget=3,
        max_observe_per_waypoint=2,
        done_retry_budget=1,
    )

    assert "Evidence lane=camera-raw-fpv" in prompt
    assert "Raw-FPV candidate-attempt budget=3" in prompt
    assert "Per-waypoint observation budget=2" in prompt
    assert "Done retry budget=1" in prompt
    assert "adjust_camera" not in prompt
    assert "distinct robot-body heading" not in prompt
    assert "only the MCP done response creates the authoritative run result" in prompt


def test_molmo_live_openai_agents_uses_single_lane_default_prompt() -> None:
    text = MOLMO_JUST.read_text(encoding="utf-8")

    assert "ROBOCLAWS_OPENAI_AGENTS_PROMPT_MODE" not in text
    assert "--prompt-mode" not in text
    assert '--raw-fpv-candidate-budget "$prompt_raw_fpv_candidate_budget"' in text
    assert '--max-observe-per-waypoint "$prompt_max_observe_per_waypoint"' in text
    assert 'prompt_max_observe_per_waypoint="4"' in text
    assert '--done-retry-budget "$prompt_done_retry_budget"' in text
    assert 'runner_args+=(--max-turns "${ROBOCLAWS_OPENAI_AGENTS_MAX_TURNS}")' in text
    assert '--max-turns "${ROBOCLAWS_OPENAI_AGENTS_MAX_TURNS:-128}"' not in text


def test_map_build_live_prompt_disables_cleanup_actions() -> None:
    prompt = render_map_build_prompt(
        "camera-grounded-labels",
        "帮我建立这个房间的 Runtime Metric Map",
    )

    assert "This run is surface=household-world intent=map-build" in prompt
    assert "User task: 帮我建立这个房间的 Runtime Metric Map" in prompt
    assert "Use the bundled household-world skill instructions" in prompt
    assert "Manipulation tools are not entitled for this run" in prompt
    assert "Evidence lane=camera-grounded-labels" in prompt
    assert "Waypoint observation tool=observe" in prompt
    assert "scan_profile=fixture-focused" in prompt
    assert "body-turn count per waypoint=4" in prompt
    assert "body-turn yaw delta deg=90" in prompt
    assert "profile observe cadence=5 per waypoint" in prompt
    assert "effective observe cadence=5 per waypoint" in prompt
    assert "max_observe_per_waypoint override=false" in prompt
    assert "profile body-turn cadence overridden=false" in prompt
    assert "stable-anchor priority=true" in prompt
    assert "fixtures, surfaces, receptacles" in prompt
    assert "movable-prior policy=" in prompt
    assert "navigate_to_relative_pose" not in prompt
    assert "runtime_metric_map.json" in prompt
