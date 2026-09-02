from __future__ import annotations

from types import SimpleNamespace

from roboclaws.agents.drivers.openai_agents_event_projection import (
    _usage_summary,
    project_tool_event,
)
from roboclaws.agents.task_state import TaskSnapshot


def test_usage_summary_reads_agents_sdk_context_wrapper_usage() -> None:
    result = SimpleNamespace(
        context_wrapper=SimpleNamespace(
            usage=SimpleNamespace(
                input_tokens=120,
                input_tokens_details=SimpleNamespace(cached_tokens=20),
                output_tokens=30,
                output_tokens_details=SimpleNamespace(reasoning_tokens=10),
            )
        )
    )

    assert _usage_summary(result) == {
        "usage_available": True,
        "input_tokens": 120,
        "cached_input_tokens": 20,
        "uncached_input_tokens": 100,
        "output_tokens": 30,
        "reasoning_tokens": 10,
    }


def test_project_tool_event_allowlists_public_fields_and_advances_once() -> None:
    snapshot = TaskSnapshot("tid", "clean")
    updated = project_tool_event(
        snapshot,
        {
            "tool_name": "observe",
            "success": True,
            "result": {"objects": {"cup": "red"}, "private_score": 99, "credential": "secret"},
        },
    )
    assert updated.revision == 1
    assert updated.objects["cup"].value == "red"
    assert "private_score" not in updated.to_json()
    assert (
        project_tool_event(updated, {"tool_name": "unknown", "success": True, "result": {"x": 1}})
        == updated
    )
