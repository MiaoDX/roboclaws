from __future__ import annotations

from roboclaws.agents.prompts.household_cleanup import (
    render_kickoff_prompt,
    render_map_build_prompt,
)


def test_cleanup_prompt_keeps_run_context_and_public_done_boundary() -> None:
    prompt = render_kickoff_prompt("world-public-labels")

    assert "This run is surface=household-world intent=cleanup" in prompt
    assert "Evidence lane=world-public-labels" in prompt
    assert "Required closeout artifacts" in prompt
    assert "only the MCP done response creates the authoritative run result" in prompt


def test_open_ended_prompt_uses_the_operator_task_as_goal() -> None:
    task = "我渴了，帮我找些解渴的东西"
    prompt = render_kickoff_prompt(
        "world-public-labels",
        task=task,
        intent="open-ended",
    )

    assert "This run is surface=household-world with no task preset" in prompt
    assert "The following operator task is authoritative" in prompt
    assert task in prompt
    assert "room-cleanup routine" not in prompt


def test_map_build_prompt_disables_manipulation_and_names_runtime_artifact() -> None:
    prompt = render_map_build_prompt(
        "camera-grounded-labels",
        "帮我建立这个房间的 Runtime Metric Map",
    )

    assert "This run is surface=household-world intent=map-build" in prompt
    assert "Manipulation tools are not entitled for this run" in prompt
    assert "Evidence lane=camera-grounded-labels" in prompt
    assert "runtime_metric_map.json" in prompt
