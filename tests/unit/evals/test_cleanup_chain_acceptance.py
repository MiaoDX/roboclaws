"""Convergence outcome acceptance requires successful, distinct cleanup chains."""

import json
from dataclasses import replace

import pytest

from roboclaws.evals.grading import _outcome_grader
from roboclaws.evals.suite_loading import load_suite


@pytest.mark.parametrize(
    "objects,failed_pick,duplicate,expected",
    [
        (4, False, False, "passed"),
        (3, False, False, "failed"),
        (4, True, False, "failed"),
        (3, False, True, "failed"),
    ],
)
def test_complete_chain_requirement_uses_successful_distinct_trace_objects(
    tmp_path, objects, failed_pick, duplicate, expected
):
    _, samples = load_suite("cleanup_capability")
    sample = replace(samples[0], grader_config={"min_complete_cleanup_chains": 4})
    events = []
    for i in range(objects):
        for tool in ("navigate_to_object", "pick", "navigate_to_receptacle", "place"):
            events.append(
                {
                    "event": "response",
                    "tool": tool,
                    "response": {
                        "ok": not (failed_pick and i == 0 and tool == "pick"),
                        "object_id": f"observed_{i}",
                    },
                }
            )
    if duplicate:
        events.extend(events[:4])
    events.append({"event": "response", "tool": "done", "response": {"ok": True}})
    (tmp_path / "trace.jsonl").write_text("\n".join(json.dumps(e) for e in events) + "\n")
    result = _outcome_grader(
        sample=sample,
        run_dir=tmp_path,
        run_result={
            "score": {
                "completion_status": "success",
                "mess_restoration_rate": 1,
                "sweep_coverage_rate": 1,
                "disturbance_count": 0,
            },
        },
    )
    assert result["status"] == expected
