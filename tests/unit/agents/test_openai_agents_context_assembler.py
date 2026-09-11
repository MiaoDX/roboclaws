from roboclaws.agents.drivers.openai_agents_context_assembler import (
    ContextBudgetPolicy,
    assemble_context,
)
from roboclaws.agents.task_state import Checkpoint, TaskSnapshot


def test_assembly_retains_snapshot() -> None:
    result = assemble_context(
        Checkpoint(TaskSnapshot("t", "clean", pose={"x": 1})),
        fixed_instructions="fixed",
        recent_raw=["old", "new"],
        policy=ContextBudgetPolicy(30, expected_output_tokens=1, safety_reserve_tokens=1),
    )
    assert result.items[1]["content"]["pose"] == {"x": 1}


def test_estimator_is_conservative_and_reserve_is_admitted() -> None:
    result = assemble_context(
        Checkpoint(TaskSnapshot("t", "clean")),
        policy=ContextBudgetPolicy(100, expected_output_tokens=10, safety_reserve_tokens=5),
    )
    assert result.admitted
    assert result.estimated_input_tokens + 15 <= 100


def test_recent_raw_eviction_drops_oldest_first() -> None:
    result = assemble_context(
        Checkpoint(TaskSnapshot("t", "clean")),
        recent_raw=["old", "new"],
        policy=ContextBudgetPolicy(47, expected_output_tokens=1, safety_reserve_tokens=1),
    )
    assert result.admitted
    assert "new" in result.items
    assert "old" not in result.items
