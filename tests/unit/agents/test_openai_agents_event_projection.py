from __future__ import annotations

from types import SimpleNamespace

from roboclaws.agents.drivers.openai_agents_event_projection import (
    _usage_summary,
    checkpointing_tool_result_callback,
    project_tool_event,
)
from roboclaws.agents.task_state import Checkpoint, Observation, TaskSnapshot


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


def test_projection_covers_actions_safety_completion_and_bounded_evidence() -> None:
    snapshot = TaskSnapshot("tid", "clean")
    for event in (
        {"tool": "navigate", "success": True, "call_id": "n1", "result": {"waypoint": "kitchen"}},
        {"tool": "pick", "success": True, "call_id": "p1", "result": {}},
        {"tool": "safety_check", "success": True, "result": {"safety": {"clear": True}}},
        {
            "tool": "done",
            "success": True,
            "result": {
                "completed": True,
                "artifact_ref": "artifacts/result.json",
                "raw_prompt": "SECRET",
            },
        },
    ):
        snapshot = project_tool_event(snapshot, event)
    assert snapshot.revision == 4
    assert snapshot.waypoint == "kitchen"
    assert snapshot.safety == {"clear": True}
    assert snapshot.completion is True
    assert snapshot.evidence[0].ref == "artifacts/result.json"
    assert "SECRET" not in snapshot.to_json()


def test_projection_ignores_failed_oversized_and_stale_observations() -> None:
    snapshot = TaskSnapshot(
        "tid",
        "clean",
        objects={"cup": Observation("red", "2026-09-02T03:00:00Z", "observe-1")},
    )
    stale = project_tool_event(
        snapshot,
        {
            "tool": "observe",
            "success": True,
            "ts": "2026-09-02T02:00:00Z",
            "result": {"objects": {"cup": "blue"}, "pose": "x" * 5000},
        },
    )
    assert stale is snapshot
    assert project_tool_event(snapshot, {"tool": "pick", "success": False}) is snapshot


def test_checkpoint_callback_advances_and_persists_each_event(tmp_path) -> None:
    path = tmp_path / "checkpoint.json"
    callback = checkpointing_tool_result_callback(path, TaskSnapshot("tid", "clean"))
    assert (
        callback({"tool": "navigate", "success": True, "result": {"waypoint": "a"}}).revision == 1
    )
    assert callback({"tool": "pick", "success": True, "result": {}}).revision == 2
    checkpoint = Checkpoint.from_json(path.read_text(encoding="utf-8"))
    assert checkpoint.snapshot.revision == 2
    assert checkpoint.snapshot.waypoint == "a"
