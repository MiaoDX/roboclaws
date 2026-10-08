"""Eval-owned cleanup chain acceptance from authoritative public tool traces."""

from pathlib import Path
from typing import Any

from roboclaws.evals.grading_sources import read_trace_events_with_errors
from roboclaws.household.semantic_timeline import (
    has_complete_semantic_sequence,
    semantic_substeps,
    successful_semantic_phases,
)


def grade_cleanup_chains(run_dir: Path, *, minimum: int) -> dict[str, Any]:
    if type(minimum) is not int or minimum < 0:
        raise ValueError("min_complete_cleanup_chains must be a non-negative integer")
    events, errors = read_trace_events_with_errors(run_dir / "trace.jsonl")
    completed = sum(
        has_complete_semantic_sequence(successful_semantic_phases(item["steps"]))
        for item in semantic_substeps(events, {})
    )
    return {
        "complete_cleanup_chains": completed,
        "required_complete_cleanup_chains": minimum,
        "complete_cleanup_chains_satisfied": not minimum or (not errors and completed >= minimum),
    }
