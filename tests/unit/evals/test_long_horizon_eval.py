from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from roboclaws.evals.live_runtime import live_product_run_kwargs, live_surface_command
from roboclaws.evals.long_horizon import _call_tool_with_robot_view, long_horizon_spec
from roboclaws.evals.long_horizon_manifest import generated_mess_manifest
from roboclaws.evals.models import load_eval_sample, load_eval_suite
from roboclaws.evals.runner import run_eval_suite
from roboclaws.launch.catalog import resolve_surface_launch

REPO_ROOT = Path(__file__).resolve().parents[3]
LONG_HORIZON_SUITE = REPO_ROOT / "evals" / "household_world" / "suites" / "long_horizon_tasks.json"
TARGET_A = "bread_5f50f53c9dcfbae4352335033a8b2bb4_1_0_2"
TARGET_B = "bread_dcb25a3fdc38be63308c7171e734e8a3_1_0_2"
TARGET_APPLE = "apple_9f56af06d43fe8692531302b5e0dc1df_1_0_2"
SHELF = "shelf_140ccb7e1f5028c7d773229dfe6e1a04_1_0_2"
FRIDGE = "refrigerator_5e0d26d670a75ae0a52f2ceb08914b0e_1_0_2"
LIVING_DINING_TABLE = "diningtable_f113cf7f8367e89f709b53cbee1a1c05_2_0_3"
LIVING_SOFA = "sofa_26757136bf2f1a8029d685a42db38f2a_1_0_3"
BEDROOM_DESK = "desk_767b7ce268898119aaeb97804ba52bdd_1_0_7"


def test_long_horizon_suite_fixture_declares_private_grader() -> None:
    suite = load_eval_suite(LONG_HORIZON_SUITE)

    assert suite.suite_id == "household_world.long_horizon_tasks"
    assert suite.sample_ids == (
        "long_horizon.snack_restock_val0_seed7",
        "long_horizon.food_restock_chinese_val0_seed7",
    )
    assert "long_horizon" in suite.required_graders


def test_long_horizon_suite_records_manipulation_tool_surface_and_passes(
    tmp_path: Path,
) -> None:
    captured_kwargs: dict[str, Any] = {}

    def product_runner(**kwargs: Any) -> dict[str, Any]:
        captured_kwargs.update(kwargs)
        run_dir = Path(kwargs["output_dir"])
        object_ids = tuple(kwargs["generated_mess_object_ids"])
        _write_long_horizon_artifacts(run_dir, object_ids=object_ids)
        return _long_horizon_run_result(run_dir, object_ids=object_ids)

    run = run_eval_suite(
        "long_horizon_tasks",
        output_root=tmp_path,
        budget="focused",
        stamp="long-horizon-pass",
        product_runner=product_runner,
    )

    result = json.loads(run.results_path.read_text())["results"][0]
    assert result["status"] == "passed"
    assert result["failure_class"] == "not_applicable"
    assert result["identity"]["skill_name"] == "household-world"
    assert "pick" in result["identity"]["tool_surface"]
    assert captured_kwargs["evidence_lane"] == "world-public-labels"
    assert captured_kwargs["generated_mess_object_ids"] == (
        TARGET_A,
        TARGET_B,
        TARGET_APPLE,
    )
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


def test_long_horizon_chinese_food_restock_manifest_adds_cold_branch() -> None:
    sample = load_eval_sample(
        REPO_ROOT
        / "evals/household_world/samples/long_horizon/food_restock_chinese_val0_seed7.json"
    )

    spec = long_horizon_spec(sample)
    assert spec is not None

    manifest = generated_mess_manifest(sample, spec)

    assert sample.intent == "open-ended"
    assert sample.prompt.startswith("客厅、餐区和卧室里有一些食物")
    assert spec.task_id == "food_restock_chinese"
    assert spec.cold_object_ids == (TARGET_APPLE,)
    assert [item["object_id"] for item in manifest["targets"]] == [
        TARGET_A,
        TARGET_B,
        TARGET_APPLE,
    ]
    assert [item["start_receptacle_id"] for item in manifest["targets"]] == [
        LIVING_DINING_TABLE,
        LIVING_SOFA,
        BEDROOM_DESK,
    ]
    assert [item["target_receptacle_id"] for item in manifest["targets"]] == [
        SHELF,
        SHELF,
        FRIDGE,
    ]


def test_long_horizon_robot_view_capture_resolves_public_handle_to_internal_id(
    tmp_path: Path,
) -> None:
    base_contract = _RecordingRobotViewBaseContract()
    contract = _RobotViewContractStub(
        internal_object_ids={"observed_003": TARGET_A},
        internal_fixture_ids={SHELF: SHELF},
    )
    events: list[dict[str, Any]] = []
    steps: list[dict[str, Any]] = []

    response, next_index = _call_tool_with_robot_view(
        events,
        0.0,
        "pick",
        {"object_id": "observed_003"},
        lambda: {
            "ok": True,
            "tool": "pick",
            "object_id": "observed_003",
            "previous_location_id": SHELF,
        },
        base_contract=base_contract,
        contract=contract,
        robot_view_steps=steps,
        output_dir=tmp_path,
        view_index=4,
        record_robot_views=True,
    )

    assert response["ok"] is True
    assert next_index == 5
    assert len(base_contract.recorded_steps) == 1
    assert base_contract.recorded_steps[0]["focus_object_id"] == TARGET_A
    assert base_contract.recorded_steps[0]["focus_receptacle_id"] == SHELF
    assert base_contract.recorded_steps[0]["semantic_phase"] == "pick"
    assert steps == [
        {
            "label": "0004_pick_observed_003",
            "focus_object_id": TARGET_A,
            "focus_receptacle_id": SHELF,
        }
    ]


def test_long_horizon_live_aggregate_records_finished_open_task_status(
    tmp_path: Path,
) -> None:
    def live_product_runner(**kwargs: Any) -> dict[str, Any]:
        run_dir = Path(kwargs["output_dir"])
        object_ids = tuple(kwargs["generated_mess_object_ids"])
        _write_long_horizon_artifacts(run_dir, object_ids=object_ids)
        (run_dir / "live_status.json").write_text('{"phase": "finished", "exit_status": 0}\n')
        result = _long_horizon_run_result(run_dir, object_ids=object_ids)
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

    assert aggregate["passed"] == 2
    assert aggregate["failed"] == 0
    assert aggregate["open_ended"]["live_statuses"] == {"finished": 2}


def test_long_horizon_grader_rejects_incomplete_final_state(tmp_path: Path) -> None:
    def product_runner(**kwargs: Any) -> dict[str, Any]:
        run_dir = Path(kwargs["output_dir"])
        object_ids = tuple(kwargs["generated_mess_object_ids"])
        _write_long_horizon_artifacts(run_dir, object_ids=object_ids)
        result = _long_horizon_run_result(run_dir, object_ids=object_ids)
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
        object_ids = tuple(kwargs["generated_mess_object_ids"])
        _write_long_horizon_artifacts(run_dir, object_ids=object_ids)
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
        return _long_horizon_run_result(run_dir, object_ids=object_ids)

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


def _write_long_horizon_artifacts(
    run_dir: Path,
    *,
    object_ids: tuple[str, ...] = (TARGET_A, TARGET_B),
) -> None:
    run_dir.mkdir(parents=True, exist_ok=True)
    (run_dir / "run_result.json").write_text("{}\n")
    (run_dir / "report.html").write_text("<html>report</html>\n")
    (run_dir / "agent_view.json").write_text('{"schema": "agent_view"}\n')
    (run_dir / "private_evaluation.json").write_text("{}\n")
    (run_dir / "advisory_evaluation.json").write_text('{"authoritative": false}\n')
    (run_dir / "goal_contract.json").write_text('{"intent": "open-ended"}\n')
    (run_dir / "runtime_metric_map.json").write_text(
        json.dumps(_runtime_metric_map(object_ids=object_ids)) + "\n"
    )
    (run_dir / "trace.jsonl").write_text("\n".join(_trace_lines(object_ids=object_ids)) + "\n")


def _runtime_metric_map(*, object_ids: tuple[str, ...] = (TARGET_A, TARGET_B)) -> dict[str, Any]:
    return {
        "schema": "runtime_metric_map_v1",
        "public_semantic_anchors": [],
        "generated_exploration_candidates": [
            {"waypoint_id": "room_2_inspection", "room_id": "room_2", "visited": True},
            {"waypoint_id": "room_3_inspection", "room_id": "room_3", "visited": True},
        ],
        "observed_objects": [
            {"object_id": f"observed_{index:03d}", "category": _category_for_object_id(object_id)}
            for index, object_id in enumerate(object_ids, start=1)
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


def _trace_lines(*, object_ids: tuple[str, ...] = (TARGET_A, TARGET_B)) -> list[str]:
    events = [
        {"event": "request", "tool": "metric_map"},
        {"event": "response", "tool": "metric_map"},
        {"event": "response", "tool": "observe", "response": {"current_room_id": "room_3"}},
    ]
    for index, object_id in enumerate(object_ids, start=1):
        observed_id = f"observed_{index:03d}"
        destination = FRIDGE if object_id == TARGET_APPLE else SHELF
        events.extend(
            [
                _event("navigate_to_object", object_id=observed_id),
                _event("pick", object_id=observed_id),
                _event("navigate_to_receptacle", fixture_id=destination),
            ]
        )
        if destination == FRIDGE:
            events.extend(
                [
                    _event("open_receptacle", fixture_id=FRIDGE),
                    _event("place_inside", object_id=observed_id, location_id=FRIDGE),
                    _event("close_receptacle", fixture_id=FRIDGE),
                ]
            )
        else:
            events.append(_event("place_inside", object_id=observed_id, location_id=SHELF))
    events.append({"event": "response", "tool": "done"})
    return [json.dumps(event) for event in events]


def _event(tool: str, **response: Any) -> dict[str, Any]:
    return {"event": "response", "tool": tool, "response": response}


def _long_horizon_run_result(
    run_dir: Path,
    *,
    object_ids: tuple[str, ...] = (TARGET_A, TARGET_B),
) -> dict[str, Any]:
    final_locations = {
        object_id: (FRIDGE if object_id == TARGET_APPLE else SHELF) for object_id in object_ids
    }
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
        "tool_event_counts": {
            "place_inside:request": len(object_ids),
            "place_inside:response": len(object_ids),
        },
        "artifacts": {
            "run_result": str(run_dir / "run_result.json"),
            "report": str(run_dir / "report.html"),
        },
        "runtime_metric_map": _runtime_metric_map(object_ids=object_ids),
        "advisory_evaluation": json.loads((run_dir / "advisory_evaluation.json").read_text()),
        "policy_uses_private_truth": False,
        "planner_uses_private_manifest": False,
        "agent_view": {"schema": "agent_view"},
        "final_locations": final_locations,
        "final_containment": {},
    }


def _category_for_object_id(object_id: str) -> str:
    if object_id == TARGET_APPLE:
        return "Apple"
    return "Bread"


class _RecordingRobotViewBaseContract:
    def __init__(self) -> None:
        self.recorded_steps: list[dict[str, Any]] = []

    def record_robot_view_step(self, **kwargs: Any) -> int:
        self.recorded_steps.append(dict(kwargs))
        kwargs["steps"].append(
            {
                "label": f"{kwargs['index']:04d}_{kwargs['label_suffix']}",
                "focus_object_id": kwargs.get("focus_object_id"),
                "focus_receptacle_id": kwargs.get("focus_receptacle_id"),
            }
        )
        return int(kwargs["index"]) + 1


class _RobotViewContractStub:
    def __init__(
        self,
        *,
        internal_object_ids: dict[str, str],
        internal_fixture_ids: dict[str, str],
    ) -> None:
        self._internal_object_ids = internal_object_ids
        self._internal_fixture_ids = internal_fixture_ids

    def _internal_object_id(self, handle: str) -> str | None:
        return self._internal_object_ids.get(handle)

    def _handle_for_object(self, object_id: str) -> str:
        raise AssertionError(f"robot-view capture must not mint handles for {object_id}")

    def internal_fixture_id_for_public_reference(self, fixture_id: str | None) -> str | None:
        if fixture_id is None:
            return None
        return self._internal_fixture_ids.get(fixture_id)
