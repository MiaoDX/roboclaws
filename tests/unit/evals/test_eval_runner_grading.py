from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from roboclaws.evals.runner import run_eval_suite
from tests.unit.evals.eval_runner_support import (
    _run_result,
    _write_product_artifacts,
)


def test_open_ended_positive_predicates_pass_with_public_runtime_evidence(
    tmp_path: Path,
) -> None:
    def product_runner(**kwargs: Any) -> dict[str, Any]:
        run_dir = Path(kwargs["output_dir"])
        _write_product_artifacts(
            run_dir,
            completion_status="success",
            include_goal_contract=True,
        )
        return _run_result(
            run_dir,
            completion_status="success",
            task_intent="open-ended",
            include_completion_claim=True,
            wall_time_s=1.25,
        )

    run = run_eval_suite(
        "open_ended_goals",
        output_root=tmp_path,
        stamp="open-ended-positive-predicate",
        product_runner=product_runner,
    )

    payload = json.loads(run.results_path.read_text())
    assert payload["aggregate"]["passed"] == 3
    assert payload["aggregate"]["failed"] == 0
    assert payload["aggregate"]["open_ended"]["by_category"]["negative_search"]["passed"] == 1
    assert payload["aggregate"]["open_ended"]["by_category"]["area_inspection"]["passed"] == 1
    assert payload["aggregate"]["open_ended"]["by_category"]["positive_observable"]["passed"] == 1
    assert payload["aggregate"]["open_ended"]["telemetry"]["tool_call_count"] == 3
    results = {result["identity"]["sample_id"]: result for result in payload["results"]}
    room_predicate = results["open_ended.room4_anchor_seed7"]["grader_outputs"]["open_ended"][
        "success_predicate"
    ]
    living_predicate = results["open_ended.living_waypoint_seed7"]["grader_outputs"]["open_ended"][
        "success_predicate"
    ]
    assert room_predicate["passed"] is True
    assert room_predicate["evidence"]["anchor_id"] == "anchor_waypoint_room_6_inspection"
    assert living_predicate["passed"] is True
    assert "room_6_inspection" in living_predicate["evidence"]["visited_waypoint_ids"]


def test_open_ended_authoritative_predicate_failure_is_behavior_failure(
    tmp_path: Path,
) -> None:
    def product_runner(**kwargs: Any) -> dict[str, Any]:
        run_dir = Path(kwargs["output_dir"])
        _write_product_artifacts(
            run_dir,
            completion_status="success",
            include_goal_contract=True,
            include_open_ended_public_evidence=False,
        )
        (run_dir / "trace.jsonl").write_text(
            "\n".join(
                [
                    '{"event": "request", "tool": "metric_map"}',
                    '{"event": "response", "tool": "metric_map"}',
                    '{"event": "request", "tool": "done"}',
                    '{"event": "response", "tool": "done"}',
                ]
            )
            + "\n"
        )
        return _run_result(
            run_dir,
            completion_status="success",
            task_intent="open-ended",
            include_completion_claim=True,
        )

    run = run_eval_suite(
        "open_ended_goals",
        output_root=tmp_path,
        stamp="open-ended-positive-predicate-fail",
        product_runner=product_runner,
    )

    payload = json.loads(run.results_path.read_text())
    assert payload["aggregate"]["passed"] == 1
    assert payload["aggregate"]["failed"] == 2
    assert payload["aggregate"]["failure_classes"] == {"private_goal_not_satisfied": 2}
    results = {result["identity"]["sample_id"]: result for result in payload["results"]}
    assert results["open_ended.drink_seed7"]["status"] == "passed"
    assert results["open_ended.room4_anchor_seed7"]["status"] == "failed"
    assert results["open_ended.room4_anchor_seed7"]["failure_class"] == (
        "private_goal_not_satisfied"
    )


@pytest.mark.parametrize(
    ("sample_id", "field_name", "expected_error"),
    [
        (
            "open_ended.room4_anchor_seed7",
            "public_semantic_anchors",
            "public_semantic_anchors:invalid_json_array",
        ),
        (
            "open_ended.living_waypoint_seed7",
            "generated_exploration_candidates",
            "generated_exploration_candidates:invalid_json_array",
        ),
        (
            "open_ended.living_waypoint_seed7",
            "target_search_summary",
            "target_search_summary:invalid_json_object",
        ),
    ],
)
def test_open_ended_predicates_reject_wrong_shaped_runtime_map_sources(
    tmp_path: Path,
    sample_id: str,
    field_name: str,
    expected_error: str,
) -> None:
    def product_runner(**kwargs: Any) -> dict[str, Any]:
        run_dir = Path(kwargs["output_dir"])
        current_sample_id = kwargs["run_metadata_overrides"]["eval_sample_id"]
        _write_product_artifacts(
            run_dir,
            completion_status="success",
            include_goal_contract=True,
        )
        result = _run_result(
            run_dir,
            completion_status="success",
            task_intent="open-ended",
            include_completion_claim=True,
            include_runtime_map=current_sample_id != sample_id,
        )
        if current_sample_id == sample_id:
            runtime_map = json.loads((run_dir / "runtime_metric_map.json").read_text())
            runtime_map[field_name] = "wrong-shape"
            (run_dir / "runtime_metric_map.json").write_text(
                json.dumps(runtime_map) + "\n",
                encoding="utf-8",
            )
        return result

    run = run_eval_suite(
        "open_ended_goals",
        output_root=tmp_path,
        stamp=f"wrong-shaped-open-ended-{field_name}",
        product_runner=product_runner,
    )

    payload = json.loads(run.results_path.read_text())
    result = {item["identity"]["sample_id"]: item for item in payload["results"]}[sample_id]
    open_ended = result["grader_outputs"]["open_ended"]
    assert result["status"] == "failed"
    assert result["failure_class"] == "artifact_missing"
    assert open_ended["status"] == "failed"
    assert open_ended["failure_class"] == "artifact_missing"
    assert open_ended["semantic_satisfaction_status"] == "source_error"
    assert open_ended["success_predicate"]["source_error"] is True
    assert open_ended["source_errors"] == [
        {
            "path": str(
                run.output_dir
                / "runs"
                / sample_id.replace(".", "_")
                / "trial-0000"
                / "runtime_metric_map.json"
            ),
            "reason": expected_error,
        }
    ]


def test_open_ended_waypoint_predicate_accepts_trace_visit_without_runtime_anchor(
    tmp_path: Path,
) -> None:
    def product_runner(**kwargs: Any) -> dict[str, Any]:
        run_dir = Path(kwargs["output_dir"])
        sample_id = kwargs["run_metadata_overrides"]["eval_sample_id"]
        _write_product_artifacts(
            run_dir,
            completion_status="success",
            include_goal_contract=True,
            include_open_ended_public_evidence=sample_id != "open_ended.living_waypoint_seed7",
        )
        if sample_id == "open_ended.room4_anchor_seed7":
            (run_dir / "trace.jsonl").write_text(
                "\n".join(
                    [
                        '{"event": "request", "tool": "resolve_target_query"}',
                        '{"event": "response", "tool": "resolve_target_query"}',
                        (
                            '{"event": "request", "tool": "navigate_to_waypoint", '
                            '"request": {"waypoint_id": "room_6_inspection"}}'
                        ),
                        '{"event": "response", "tool": "navigate_to_waypoint"}',
                        '{"event": "request", "tool": "observe"}',
                        '{"event": "response", "tool": "observe"}',
                        '{"event": "request", "tool": "done"}',
                        '{"event": "response", "tool": "done"}',
                    ]
                )
                + "\n"
            )
        if sample_id == "open_ended.living_waypoint_seed7":
            (run_dir / "trace.jsonl").write_text(
                "\n".join(
                    [
                        '{"event": "request", "tool": "metric_map"}',
                        '{"event": "response", "tool": "metric_map"}',
                        (
                            '{"event": "request", "tool": "navigate_to_waypoint", '
                            '"request": {"waypoint_id": "room_6_inspection"}}'
                        ),
                        '{"event": "response", "tool": "navigate_to_waypoint"}',
                        '{"event": "request", "tool": "done"}',
                        '{"event": "response", "tool": "done"}',
                    ]
                )
                + "\n"
            )
        return _run_result(
            run_dir,
            completion_status="success",
            task_intent="open-ended",
            include_completion_claim=True,
        )

    run = run_eval_suite(
        "open_ended_goals",
        output_root=tmp_path,
        stamp="open-ended-trace-visit",
        product_runner=product_runner,
    )

    payload = json.loads(run.results_path.read_text())
    assert payload["aggregate"]["passed"] == 3
    results = {result["identity"]["sample_id"]: result for result in payload["results"]}
    assert results["open_ended.room4_anchor_seed7"]["grader_outputs"]["trajectory"]["status"] == (
        "passed"
    )
    assert (
        results["open_ended.living_waypoint_seed7"]["grader_outputs"]["open_ended"][
            "success_predicate"
        ]["passed"]
        is True
    )


def test_eval_runner_fails_trajectory_when_trace_contains_malformed_json(
    tmp_path: Path,
) -> None:
    def product_runner(**kwargs: Any) -> dict[str, Any]:
        run_dir = Path(kwargs["output_dir"])
        _write_product_artifacts(
            run_dir,
            completion_status="success",
            include_goal_contract=True,
        )
        (run_dir / "trace.jsonl").write_text(
            "\n".join(
                [
                    '{"event": "response", "tool": "metric_map"}',
                    "{",
                    '{"event": "response", "tool": "done"}',
                ]
            )
            + "\n",
            encoding="utf-8",
        )
        return _run_result(
            run_dir,
            completion_status="success",
            task_intent="open-ended",
            include_completion_claim=True,
        )

    run = run_eval_suite(
        "open_ended_goals",
        output_root=tmp_path,
        stamp="malformed-trace",
        product_runner=product_runner,
    )

    payload = json.loads(run.results_path.read_text())
    results = {result["identity"]["sample_id"]: result for result in payload["results"]}
    result = results["open_ended.drink_seed7"]
    trajectory = result["grader_outputs"]["trajectory"]
    assert result["status"] == "failed"
    assert result["failure_class"] == "trajectory_policy_violation"
    assert trajectory["missing_required_tools"] == []
    assert trajectory["violations"] == ["trace_json_invalid"]
    assert trajectory["trace_parse_errors"][0].startswith(
        "line 2: invalid_json:Expecting property name enclosed in double quotes"
    )


def test_eval_runner_fails_trajectory_when_trace_contains_non_object_json(
    tmp_path: Path,
) -> None:
    def product_runner(**kwargs: Any) -> dict[str, Any]:
        run_dir = Path(kwargs["output_dir"])
        _write_product_artifacts(
            run_dir,
            completion_status="success",
            include_goal_contract=True,
        )
        (run_dir / "trace.jsonl").write_text(
            "\n".join(
                [
                    '{"event": "response", "tool": "metric_map"}',
                    "[]",
                    '{"event": "response", "tool": "done"}',
                ]
            )
            + "\n",
            encoding="utf-8",
        )
        return _run_result(
            run_dir,
            completion_status="success",
            task_intent="open-ended",
            include_completion_claim=True,
        )

    run = run_eval_suite(
        "open_ended_goals",
        output_root=tmp_path,
        stamp="non-object-trace",
        product_runner=product_runner,
    )

    payload = json.loads(run.results_path.read_text())
    results = {result["identity"]["sample_id"]: result for result in payload["results"]}
    trajectory = results["open_ended.drink_seed7"]["grader_outputs"]["trajectory"]
    assert trajectory["violations"] == ["trace_json_invalid"]
    assert trajectory["trace_parse_errors"] == ["line 2: invalid_json_object"]


@pytest.mark.parametrize("sidecar_name", ["advisory_evaluation.json", "runtime_metric_map.json"])
def test_open_ended_eval_fails_aloud_on_malformed_source_sidecars(
    tmp_path: Path,
    sidecar_name: str,
) -> None:
    def product_runner(**kwargs: Any) -> dict[str, Any]:
        run_dir = Path(kwargs["output_dir"])
        sample_id = kwargs["run_metadata_overrides"]["eval_sample_id"]
        _write_product_artifacts(
            run_dir,
            completion_status="success",
            include_goal_contract=True,
        )
        result = _run_result(
            run_dir,
            completion_status="success",
            task_intent="open-ended",
            include_completion_claim=True,
            include_runtime_map=sidecar_name != "runtime_metric_map.json",
        )
        if sample_id == "open_ended.room4_anchor_seed7":
            if sidecar_name == "advisory_evaluation.json":
                result.pop("advisory_evaluation")
            (run_dir / sidecar_name).write_text("{", encoding="utf-8")
        return result

    run = run_eval_suite(
        "open_ended_goals",
        output_root=tmp_path,
        stamp=f"malformed-{sidecar_name}",
        product_runner=product_runner,
    )

    payload = json.loads(run.results_path.read_text())
    result = {item["identity"]["sample_id"]: item for item in payload["results"]}[
        "open_ended.room4_anchor_seed7"
    ]
    open_ended = result["grader_outputs"]["open_ended"]
    assert result["status"] == "failed"
    assert result["failure_class"] == "artifact_missing"
    assert open_ended["status"] == "failed"
    assert open_ended["failure_class"] == "artifact_missing"
    assert open_ended["semantic_satisfaction_status"] == "source_error"
    assert open_ended["source_errors"][0]["path"].endswith(sidecar_name)
    assert open_ended["source_errors"][0]["reason"].startswith(
        "invalid_json:Expecting property name enclosed in double quotes"
    )


def test_open_ended_eval_separates_claim_from_artifact_readiness(tmp_path: Path) -> None:
    def product_runner(**kwargs: Any) -> dict[str, Any]:
        run_dir = Path(kwargs["output_dir"])
        sample_id = kwargs["run_metadata_overrides"]["eval_sample_id"]
        if sample_id == "map_build.fixture_focused_seed7":
            _write_product_artifacts(run_dir, completion_status="map_build_complete")
            return _run_result(
                run_dir,
                completion_status="map_build_complete",
                map_build=True,
            )
        if sample_id.startswith("cleanup."):
            _write_product_artifacts(run_dir, completion_status="success")
            return _run_result(run_dir, completion_status="success")
        _write_product_artifacts(run_dir, completion_status="failed")
        return _run_result(run_dir, completion_status="failed", task_intent="open-ended")

    run = run_eval_suite(
        "evals/household_world/suites/map_build_consumer.json",
        output_root=tmp_path,
        stamp="open-ended-missing-claim",
        product_runner=product_runner,
    )

    results = json.loads(run.results_path.read_text())["results"]
    open_result = next(
        result
        for result in results
        if result["identity"]["sample_id"] == "open_ended.stable_anchor_no_prior_seed7"
    )
    assert open_result["status"] == "failed"
    assert open_result["failure_class"] == "agent_no_completion_claim"
    assert open_result["grader_outputs"]["open_ended"]["completion_claim_present"] is False
    assert open_result["grader_outputs"]["open_ended"]["artifact_readiness"] == "missing"
