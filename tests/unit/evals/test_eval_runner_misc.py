from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Callable

import pytest

from roboclaws.evals.runner import run_eval_suite
from tests.unit.evals.eval_runner_support import (
    _blocked_product_runner,
    _passing_product_runner,
    _run_invalid_cleanup_sample,
)


def test_eval_runner_classifies_environment_blocked_exception(tmp_path: Path) -> None:
    run = run_eval_suite(
        "smoke_regression",
        output_root=tmp_path,
        stamp="blocked",
        product_runner=_blocked_product_runner,
    )

    payload = json.loads(run.results_path.read_text())
    result = payload["results"][0]
    assert result["status"] == "blocked"
    assert result["failure_class"] == "environment_blocked"
    assert result["grader_outputs"]["runner"]["error_type"] == "RuntimeError"


def test_eval_runner_records_repetition_metrics(tmp_path: Path) -> None:
    run = run_eval_suite(
        "cleanup_capability",
        output_root=tmp_path,
        stamp="repeat",
        product_runner=_passing_product_runner,
    )

    payload = json.loads(run.results_path.read_text())
    assert payload["aggregate"]["total"] == 3
    assert payload["aggregate"]["sample_count"] == 1
    assert payload["aggregate"]["max_repetition_count"] == 3
    assert payload["aggregate"]["pass_at_k"] == {"1": 1.0, "2": 1.0, "3": 1.0}
    assert payload["aggregate"]["pass_caret_k"] == {"1": 1.0, "2": 1.0, "3": 1.0}
    assert payload["aggregate"]["pass_caret_k_eligible"] == {"1": 1, "2": 1, "3": 1}
    sample = payload["aggregate"]["samples"]["cleanup.repeated_seed7"]
    assert sample["trial_count"] == 3
    assert sample["pass_all"] is True
    assert [
        result["identity"]["repetition_index"]
        for result in payload["results"]
        if result["identity"]["sample_id"] == "cleanup.repeated_seed7"
    ] == [0, 1, 2]


@pytest.mark.parametrize(
    ("case_name", "mutate", "expected_error"),
    [
        (
            "generated-mess-count",
            lambda sample: sample["private_goal_reference"].__setitem__(
                "generated_mess_count",
                "five",
            ),
            "private_goal_reference.generated_mess_count must be a non-negative integer",
        ),
        (
            "scene-index",
            lambda sample: sample["launch_overrides"].__setitem__("scene_index", True),
            "launch_overrides.scene_index must be a non-negative integer",
        ),
        (
            "scene-source",
            lambda sample: sample["launch_overrides"].__setitem__("scene_source", ""),
            "launch_overrides.scene_source must be a non-empty string",
        ),
    ],
)
def test_eval_runner_rejects_invalid_sample_launch_metadata(
    tmp_path: Path,
    case_name: str,
    mutate: Callable[[dict[str, Any]], None],
    expected_error: str,
) -> None:
    result = _run_invalid_cleanup_sample(
        tmp_path,
        sample_id=f"cleanup.invalid_{case_name.replace('-', '_')}",
        stamp=f"invalid-{case_name}",
        mutate=mutate,
        assertion_message=f"product runner should not launch with invalid {case_name}",
    )

    assert result["status"] == "failed"
    assert result["failure_class"] == "artifact_missing"
    assert result["grader_outputs"]["runner"]["error_type"] == "ValueError"
    assert expected_error in result["grader_outputs"]["runner"]["message"]
