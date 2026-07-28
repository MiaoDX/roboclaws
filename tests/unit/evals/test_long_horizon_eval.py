from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from roboclaws.evals.live_runtime import live_product_run_kwargs, live_surface_command
from roboclaws.evals.long_horizon import long_horizon_spec
from roboclaws.evals.long_horizon_manifest import generated_mess_manifest
from roboclaws.evals.models import load_eval_sample, load_eval_suite
from roboclaws.evals.runner import run_eval_suite
from roboclaws.launch.catalog import resolve_surface_launch

REPO_ROOT = Path(__file__).resolve().parents[3]
LONG_HORIZON_SUITE = REPO_ROOT / "evals" / "household_world" / "suites" / "long_horizon_tasks.json"
TARGET_A = "bread_5f50f53c9dcfbae4352335033a8b2bb4_1_0_2"
TARGET_B = "bread_dcb25a3fdc38be63308c7171e734e8a3_1_0_2"
SHELF = "shelf_140ccb7e1f5028c7d773229dfe6e1a04_1_0_2"
FRIDGE = "refrigerator_5e0d26d670a75ae0a52f2ceb08914b0e_1_0_2"
LIVING_DINING_TABLE = "diningtable_f113cf7f8367e89f709b53cbee1a1c05_2_0_3"
LIVING_SOFA = "sofa_26757136bf2f1a8029d685a42db38f2a_1_0_3"


def test_long_horizon_suite_fixture_declares_private_grader() -> None:
    suite = load_eval_suite(LONG_HORIZON_SUITE)

    assert suite.suite_id == "household_world.long_horizon_tasks"
    assert suite.sample_ids == ("long_horizon.snack_restock_val0_seed7",)
    assert "long_horizon" in suite.required_graders


def test_long_horizon_suite_records_manipulation_tool_surface_and_passes(
    tmp_path: Path,
) -> None:
    captured_kwargs: dict[str, Any] = {}

    def product_runner(**kwargs: Any) -> dict[str, Any]:
        captured_kwargs.update(kwargs)
        run_dir = Path(kwargs["output_dir"])
        _write_long_horizon_artifacts(run_dir)
        return _long_horizon_run_result(run_dir)

    run = run_eval_suite(
        "long_horizon_tasks",
        output_root=tmp_path,
        stamp="long-horizon-pass",
        product_runner=product_runner,
    )

    result = json.loads(run.results_path.read_text())["results"][0]
    assert result["status"] == "passed"
    assert result["failure_class"] == "not_applicable"
    assert result["identity"]["skill_name"] == "household-long-horizon"
    assert "pick" in result["identity"]["tool_surface"]
    assert captured_kwargs["evidence_lane"] == "world-public-labels"
    assert captured_kwargs["generated_mess_object_ids"] == (TARGET_A, TARGET_B)
    assert result["grader_outputs"]["long_horizon"]["subgoals"]["placed"] is True
    assert result["metrics"]["long_horizon_subgoals"]["hands_empty"] is True


def test_long_horizon_live_command_uses_private_task_targets(tmp_path: Path) -> None:
    sample = load_eval_sample(
        REPO_ROOT / "evals/household_world/samples/long_horizon/snack_restock_val0_seed7.json"
    )
    target_ids = (TARGET_A, TARGET_B)
    kwargs = live_product_run_kwargs(
        sample,
        run_dir=tmp_path / "trial-0000",
        budget="smoke",
        dependency_artifacts=None,
        agent_engine="openai-agents-sdk",
        provider_profile="codex-router-responses",
        model=None,
        live_timeout_s=None,
        live_stall_timeout_s=None,
    )

    command = live_surface_command(kwargs, output_dir=tmp_path / "surface-run")

    pinned_targets_arg = f"generated_mess_object_ids={','.join(target_ids)}"
    manifest_path = Path(kwargs["generated_mess_manifest_path"])
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    assert f"relocation_count={len(target_ids)}" in command
    assert pinned_targets_arg in command
    assert f"generated_mess_manifest_path={manifest_path}" in command
    assert [item["object_id"] for item in manifest["targets"]] == list(target_ids)
    assert [item["start_receptacle_id"] for item in manifest["targets"]] == [
        LIVING_DINING_TABLE,
        LIVING_SOFA,
    ]
    assert [item["valid_receptacle_ids"] for item in manifest["targets"]] == [
        [SHELF, FRIDGE],
        [SHELF, FRIDGE],
    ]
    plan = resolve_surface_launch(command[5:])
    assert f"generated_mess_count={len(target_ids)}" in plan.argv
    assert pinned_targets_arg in plan.argv
    assert f"generated_mess_manifest_path={manifest_path}" in plan.argv


def test_long_horizon_generated_mess_manifest_comes_from_private_task_spec() -> None:
    sample = load_eval_sample(
        REPO_ROOT / "evals/household_world/samples/long_horizon/snack_restock_val0_seed7.json"
    )

    spec = long_horizon_spec(sample)
    assert spec is not None

    manifest = generated_mess_manifest(sample, spec)

    assert manifest["provenance"] == "long_horizon_task_private_goal_reference"
    assert manifest["generated_mess_count"] == 2
    assert [item["object_id"] for item in manifest["targets"]] == [TARGET_A, TARGET_B]
    assert [item["start_receptacle_id"] for item in manifest["targets"]] == [
        LIVING_DINING_TABLE,
        LIVING_SOFA,
    ]
    assert {tuple(item["valid_receptacle_ids"]) for item in manifest["targets"]} == {
        (SHELF, FRIDGE)
    }


def test_long_horizon_live_aggregate_records_finished_open_task_status(
    tmp_path: Path,
) -> None:
    def live_product_runner(**kwargs: Any) -> dict[str, Any]:
        run_dir = Path(kwargs["output_dir"])
        _write_long_horizon_artifacts(run_dir)
        (run_dir / "live_status.json").write_text('{"phase": "finished", "exit_status": 0}\n')
        result = _long_horizon_run_result(run_dir)
        result["eval_effective_run_dir"] = str(run_dir)
        return result

    run = run_eval_suite(
        "long_horizon_tasks",
        output_root=tmp_path,
        stamp="long-horizon-live-checker-sidecar",
        agent_engine="openai-agents-sdk",
        provider_profile="codex-router-responses",
        live_execution="run",
        live_product_runner=live_product_runner,
    )

    aggregate = json.loads(run.results_path.read_text())["aggregate"]

    assert aggregate["passed"] == 1
    assert aggregate["failed"] == 0
    assert aggregate["open_ended"]["live_statuses"] == {"finished": 1}


def test_long_horizon_grader_rejects_incomplete_final_state(tmp_path: Path) -> None:
    def product_runner(**kwargs: Any) -> dict[str, Any]:
        run_dir = Path(kwargs["output_dir"])
        _write_long_horizon_artifacts(run_dir)
        result = _long_horizon_run_result(run_dir)
        result["final_locations"][TARGET_B] = "diningtable_f113cf7f8367e89f709b53cbee1a1c05_2_0_3"
        return result

    run = run_eval_suite(
        "long_horizon_tasks",
        output_root=tmp_path,
        stamp="long-horizon-fail",
        product_runner=product_runner,
    )

    result = json.loads(run.results_path.read_text())["results"][0]
    assert result["status"] == "failed"
    assert result["failure_class"] == "private_goal_not_satisfied"
    assert "placed" in result["grader_outputs"]["long_horizon"]["failures"]


def test_long_horizon_grader_rejects_tool_response_private_truth_leak(
    tmp_path: Path,
) -> None:
    def product_runner(**kwargs: Any) -> dict[str, Any]:
        run_dir = Path(kwargs["output_dir"])
        _write_long_horizon_artifacts(run_dir)
        with (run_dir / "trace.jsonl").open("a", encoding="utf-8") as trace_file:
            trace_file.write(
                json.dumps(
                    {
                        "event": "response",
                        "tool": "debug",
                        "response": {"accepted_destination_ids": [SHELF]},
                    }
                )
                + "\n"
            )
        return _long_horizon_run_result(run_dir)

    run = run_eval_suite(
        "long_horizon_tasks",
        output_root=tmp_path,
        stamp="long-horizon-leak",
        product_runner=product_runner,
    )

    result = json.loads(run.results_path.read_text())["results"][0]
    assert result["status"] == "failed"
    assert result["failure_class"] == "private_truth_leak"
    assert "private_truth_leak" in result["grader_outputs"]["long_horizon"]["failures"]


def _write_long_horizon_artifacts(run_dir: Path) -> None:
    run_dir.mkdir(parents=True, exist_ok=True)
    (run_dir / "run_result.json").write_text("{}\n")
    (run_dir / "report.html").write_text("<html>report</html>\n")
    (run_dir / "agent_view.json").write_text('{"schema": "agent_view"}\n')
    (run_dir / "private_evaluation.json").write_text("{}\n")
    (run_dir / "advisory_evaluation.json").write_text('{"authoritative": false}\n')
    (run_dir / "goal_contract.json").write_text('{"intent": "open-ended"}\n')
    (run_dir / "runtime_metric_map.json").write_text(json.dumps(_runtime_metric_map()) + "\n")
    (run_dir / "trace.jsonl").write_text("\n".join(_trace_lines()) + "\n")


def _runtime_metric_map() -> dict[str, Any]:
    return {
        "schema": "runtime_metric_map_v1",
        "public_semantic_anchors": [],
        "generated_exploration_candidates": [
            {"waypoint_id": "room_2_inspection", "room_id": "room_2", "visited": True},
            {"waypoint_id": "room_3_inspection", "room_id": "room_3", "visited": True},
        ],
        "observed_objects": [
            {"object_id": "observed_001", "category": "Bread"},
            {"object_id": "observed_002", "category": "Bread"},
        ],
        "target_candidates": [],
        "target_search_summary": {
            "inspection_observations": [
                {"room_id": "room_2", "waypoint_id": "room_2_inspection"},
                {"room_id": "room_3", "waypoint_id": "room_3_inspection"},
            ]
        },
        "private_truth_included": False,
        "source_map_mutated": False,
    }


def _trace_lines() -> list[str]:
    events = [
        {"event": "request", "tool": "metric_map"},
        {"event": "response", "tool": "metric_map"},
        {"event": "response", "tool": "observe", "response": {"current_room_id": "room_3"}},
        _event("navigate_to_object", object_id="observed_001"),
        _event("pick", object_id="observed_001"),
        _event("navigate_to_receptacle", fixture_id=SHELF),
        _event("place_inside", object_id="observed_001", location_id=SHELF),
        _event("navigate_to_object", object_id="observed_002"),
        _event("pick", object_id="observed_002"),
        _event("navigate_to_receptacle", fixture_id=SHELF),
        _event("place_inside", object_id="observed_002", location_id=SHELF),
        {"event": "response", "tool": "done"},
    ]
    return [json.dumps(event) for event in events]


def _event(tool: str, **response: Any) -> dict[str, Any]:
    return {"event": "response", "tool": tool, "response": response}


def _long_horizon_run_result(run_dir: Path) -> dict[str, Any]:
    return {
        "score": {"completion_status": "success", "mess_restoration_rate": 1.0},
        "completion_status": "success",
        "cleanup_status": "success",
        "task_intent": "open-ended",
        "backend": "molmospaces_subprocess",
        "final_status": "success",
        "intent_status": "success",
        "agent_completion_claim": {
            "schema": "roboclaws_agent_completion_claim_v1",
            "completion_summary": "snack restock complete",
        },
        "tool_event_counts": {"place_inside:request": 2, "place_inside:response": 2},
        "artifacts": {
            "run_result": str(run_dir / "run_result.json"),
            "report": str(run_dir / "report.html"),
        },
        "runtime_metric_map": _runtime_metric_map(),
        "advisory_evaluation": json.loads((run_dir / "advisory_evaluation.json").read_text()),
        "policy_uses_private_truth": False,
        "planner_uses_private_manifest": False,
        "agent_view": {"schema": "agent_view"},
        "final_locations": {TARGET_A: SHELF, TARGET_B: SHELF},
        "final_containment": {},
    }
