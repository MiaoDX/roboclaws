from roboclaws.agents.drivers.openai_agents_context_assembler import (
    ContextBudgetPolicy,
    assemble_context,
)
from roboclaws.agents.task_state import Checkpoint, TaskSnapshot


def test_assembly_retains_snapshot_and_evictions_are_ordered() -> None:
    result = assemble_context(
        Checkpoint(TaskSnapshot("t", "clean", pose={"x": 1})),
        fixed_instructions="fixed",
        optional_retrieval=["retrieval"],
        recent_raw=["old", "new"],
        policy=ContextBudgetPolicy(30, expected_output_tokens=1, safety_reserve_tokens=1),
    )
    assert result.items[1]["content"]["pose"] == {"x": 1}
    assert result.evicted[:1] == ("optional_retrieval",)


def test_estimator_is_conservative_and_reserve_is_admitted() -> None:
    result = assemble_context(
        Checkpoint(TaskSnapshot("t", "clean")),
        policy=ContextBudgetPolicy(100, expected_output_tokens=10, safety_reserve_tokens=5),
    )
    assert result.admitted
    assert result.estimated_input_tokens + 15 <= 100


def test_raw_eviction_does_not_remove_subgoal_evidence_without_retrieval() -> None:
    result = assemble_context(
        Checkpoint(TaskSnapshot("t", "clean")),
        subgoal_evidence=["critical-subgoal"],
        recent_raw=["old", "new"],
        policy=ContextBudgetPolicy(30, expected_output_tokens=1, safety_reserve_tokens=1),
    )
    assert "critical-subgoal" in result.items
    assert "old" not in result.items
