from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Callable

import pytest

from roboclaws.evals.runner import run_eval_suite
from tests.support import eval_runtime_map


def _passing_product_runner(**kwargs: Any) -> dict[str, Any]:
    run_dir = Path(kwargs["output_dir"])
    _write_product_artifacts(run_dir, completion_status="success")
    return _run_result(run_dir, completion_status="success")


def _missing_artifact_product_runner(**kwargs: Any) -> dict[str, Any]:
    run_dir = Path(kwargs["output_dir"])
    _write_product_artifacts(run_dir, completion_status="success")
    (run_dir / "report.html").unlink()
    return _run_result(run_dir, completion_status="success")


def _blocked_product_runner(**kwargs: Any) -> dict[str, Any]:
    raise RuntimeError("requested MCP port is already accepting connections")


def _live_surface_kwargs(
    run_dir: Path,
    *,
    live_timeout_s: float | None = None,
    live_stall_timeout_s: float | None = None,
) -> dict[str, Any]:
    return {
        "output_dir": run_dir,
        "seed": 7,
        "task_prompt": "帮我收拾这个房间",
        "backend": "api_semantic_synthetic",
        "cleanup_profile": "smoke",
        "scene_source": "procthor-10k-val",
        "scene_index": 0,
        "agent_engine": "openai-agents-sdk",
        "provider_profile": "kimi-openai-chat",
        "model": None,
        "live_timeout_s": live_timeout_s,
        "live_stall_timeout_s": live_stall_timeout_s,
    }


def _run_invalid_cleanup_sample(
    tmp_path: Path,
    *,
    sample_id: str,
    stamp: str,
    mutate: Callable[[dict[str, Any]], None],
    assertion_message: str,
    **run_kwargs: Any,
) -> dict[str, Any]:
    sample = json.loads(
        (
            Path(__file__).resolve().parents[3]
            / "evals"
            / "household_world"
            / "samples"
            / "cleanup"
            / "smoke_seed7.json"
        ).read_text(encoding="utf-8")
    )
    sample["sample_id"] = sample_id
    mutate(sample)
    path_token = sample_id.replace(".", "_")
    sample_path = tmp_path / f"{path_token}_sample.json"
    sample_path.write_text(json.dumps(sample), encoding="utf-8")
    suite_path = tmp_path / f"{path_token}_suite.json"
    suite_path.write_text(
        json.dumps(
            {
                "schema": "roboclaws_eval_suite_v1",
                "suite_id": f"household_world.{path_token}",
                "version": "2026-06-20",
                "capability": "household_world_cleanup",
                "sample_ids": [sample_id],
                "sample_refs": [str(sample_path)],
                "required_graders": ["artifacts"],
                "thresholds": {"pass_at_1": 1.0},
            }
        ),
        encoding="utf-8",
    )

    def product_runner(**_kwargs: Any) -> dict[str, Any]:
        raise AssertionError(assertion_message)

    run = run_eval_suite(
        str(suite_path),
        output_root=tmp_path,
        stamp=stamp,
        product_runner=product_runner,
        live_product_runner=product_runner,
        **run_kwargs,
    )
    return json.loads(run.results_path.read_text())["results"][0]


def _completed_process(*, returncode: int, stdout: str = "", stderr: str = "") -> Any:
    return type(
        "Completed",
        (),
        {
            "returncode": returncode,
            "stdout": stdout,
            "stderr": stderr,
        },
    )()


def _patch_live_surface_popen(
    monkeypatch: pytest.MonkeyPatch,
    live_runtime: Any,
    fake_run: Callable[..., Any],
) -> None:
    class FakePopen:
        def __init__(
            self,
            plan: Any,
            *,
            stdout: Any = None,
            stderr: Any = None,
            **kwargs: Any,
        ) -> None:
            kwargs.pop("cwd", None)
            kwargs.pop("env", None)
            self.completed = fake_run(
                [f"{key}={value}" for key, value in plan.adapter_options.items()],
                launch_plan=plan,
                **kwargs,
            )
            self.returncode = self.completed.returncode
            if stdout is not None:
                stdout.write(str(getattr(self.completed, "stdout", "") or ""))
            if stderr is not None:
                stderr.write(str(getattr(self.completed, "stderr", "") or ""))

        def poll(self) -> int:
            return self.returncode

        def terminate(self) -> None:
            return None

        def kill(self) -> None:
            return None

        def wait(self, timeout: float | None = None) -> int:
            return self.returncode

    monkeypatch.setattr(live_runtime, "spawn_launch_plan", FakePopen)


def _write_product_artifacts(
    run_dir: Path,
    *,
    completion_status: str,
    include_goal_contract: bool = False,
    generated_exploration_candidate_count: int = 7,
    include_open_ended_public_evidence: bool = True,
) -> None:
    run_dir.mkdir(parents=True, exist_ok=True)
    (run_dir / "run_result.json").write_text("{}\n")
    (run_dir / "report.html").write_text("<html>report</html>\n")
    (run_dir / "agent_view.json").write_text("{}\n")
    public_anchors = [{"anchor_id": "anchor_fridge"}]
    generated_candidates = [
        {"waypoint_id": f"generated_exploration_{index:03d}"}
        for index in range(1, generated_exploration_candidate_count + 1)
    ]
    target_search_summary: dict[str, Any] = {}
    if include_open_ended_public_evidence:
        public_anchors.extend(
            [
                {
                    "anchor_id": "anchor_room_kitchen",
                    "anchor_type": "room_area",
                    "room_id": "kitchen",
                    "waypoint_id": "generated_exploration_003",
                    "evidence": {"visited": True},
                },
                {
                    "anchor_id": "anchor_room_living_area",
                    "anchor_type": "room_area",
                    "room_id": "living_area",
                    "waypoint_id": "room_6_inspection",
                    "evidence": {"visited": True},
                },
                {
                    "anchor_id": "anchor_fixture_006",
                    "anchor_type": "receptacle",
                    "category": "fridge",
                    "label": "fridge",
                    "room_id": "room_2",
                    "waypoint_id": "room_2_inspection",
                    "evidence": {"visited": True},
                },
            ]
        )
        public_anchors.extend(eval_runtime_map.quality_public_anchors())
        generated_candidates.extend(
            [
                {
                    "waypoint_id": "generated_exploration_003",
                    "room_id": "kitchen",
                    "visited": True,
                },
                {
                    "waypoint_id": "room_2_inspection",
                    "room_id": "room_2",
                    "visited": True,
                },
            ]
        )
        target_search_summary = {
            "viewpoint_budget": {
                "observed_waypoint_ids": [
                    "generated_exploration_003",
                    "room_6_inspection",
                ],
            },
            "inspection_observations": [
                {"room_id": "kitchen", "waypoint_id": "generated_exploration_003"},
                {"room_id": "room_2", "waypoint_id": "room_2_inspection"},
            ],
        }
    (run_dir / "runtime_metric_map.json").write_text(
        json.dumps(
            {
                "schema": "runtime_metric_map_v1",
                "public_semantic_anchors": public_anchors,
                "generated_exploration_candidates": generated_candidates,
                "observed_objects": eval_runtime_map.quality_observed_objects(),
                "target_candidates": eval_runtime_map.quality_target_candidates(),
                "target_search_summary": target_search_summary,
                "private_truth_included": False,
                "source_map_mutated": False,
            }
        )
        + "\n"
    )
    (run_dir / "private_evaluation.json").write_text("{}\n")
    (run_dir / "advisory_evaluation.json").write_text('{"authoritative": false}\n')
    if include_goal_contract:
        (run_dir / "goal_contract.json").write_text(
            json.dumps(
                {
                    "schema": "roboclaws_goal_contract_v1",
                    "surface": "household-world",
                    "intent": "open-ended",
                    "normalized_goal": "find something useful to drink",
                    "goal_scope": "agent-declared",
                }
            )
            + "\n"
        )
    (run_dir / "trace.jsonl").write_text(
        "\n".join(
            [
                '{"event": "request", "tool": "metric_map"}',
                '{"event": "response", "tool": "metric_map"}',
                (
                    '{"event": "request", "tool": "navigate_to_waypoint", '
                    '"request": {"waypoint_id": "room_6_inspection"}}'
                ),
                '{"event": "response", "tool": "done"}',
            ]
        )
        + "\n"
    )


def _write_molmospaces_map_build_artifacts(
    run_dir: Path,
    *,
    wrong_waypoint_category: str = "",
) -> None:
    fixtures = [
        ("CounterTop", "room_2"),
        ("DiningTable", "room_2"),
        ("Fridge", "room_2"),
        ("ShelvingUnit", "room_2"),
        ("DiningTable", "room_3"),
        ("Sofa", "room_3"),
        ("TVStand", "room_3"),
        ("DiningTable", "room_4"),
        ("TVStand", "room_4"),
        ("Sink", "room_5"),
        ("Bed", "room_6"),
        ("TVStand", "room_6"),
        ("Bed", "room_7"),
        ("Desk", "room_7"),
        ("Bed", "room_8"),
        ("Desk", "room_8"),
    ]
    public_anchors = [
        {
            "anchor_id": f"anchor_room_{index:03d}",
            "anchor_type": "room_area",
            "category": "room_area",
            "room_id": f"room_{index}",
            "waypoint_id": f"room_{index}_inspection",
            "source_observation_id": f"room_observation_{index:03d}",
        }
        for index in range(2, 9)
    ]
    for index, (category, room_id) in enumerate(fixtures, start=1):
        waypoint_id = f"{room_id}_inspection"
        if category.lower() == wrong_waypoint_category.lower():
            waypoint_id = "room_2_inspection"
        public_anchors.append(
            {
                "anchor_id": f"anchor_fixture_{index:03d}",
                "anchor_type": (
                    "receptacle" if category in {"Fridge", "Sink", "ShelvingUnit"} else "surface"
                ),
                "category": category,
                "label": category,
                "room_id": room_id,
                "waypoint_id": waypoint_id,
                "pose": {"x": float(index), "y": float(index), "yaw": 0.0},
                "pose_source": "inspection_waypoint",
                "pose_role": "best_view_pose",
                "localization_status": "viewpoint_only",
                "source_observation_id": f"world_label_fpv_{index:03d}",
                "evidence": {
                    "fixture_observation_id": f"world_label_fpv_{index:03d}",
                    "supporting_observed_object_ids": [],
                },
            }
        )
    generated = [
        {"waypoint_id": f"room_{index}_inspection", "room_id": f"room_{index}", "visited": True}
        for index in range(2, 9)
    ]
    runtime_map = {
        "schema": "runtime_metric_map_v1",
        "public_semantic_anchors": public_anchors,
        "generated_exploration_candidates": generated,
        "observed_objects": eval_runtime_map.quality_observed_objects(),
        "target_candidates": eval_runtime_map.quality_target_candidates()
        + [
            {
                "candidate_id": f"target_candidate_molmospaces_{index:03d}",
                "candidate_type": "public_semantic_anchor",
                "category": category,
                "waypoint_id": f"{room_id}_inspection",
                "localization_status": "viewpoint_only",
            }
            for index, (category, room_id) in enumerate(fixtures, start=1)
        ],
        "private_truth_included": False,
        "source_map_mutated": False,
    }
    (run_dir / "runtime_metric_map.json").write_text(json.dumps(runtime_map) + "\n")
    receptacles = {
        f"{category.lower()}_{index}_0_{room_id.removeprefix('room_')}": {
            "category": category,
            "room_area": room_id,
            "position": [float(index), float(index), 0.5],
        }
        for index, (category, room_id) in enumerate(fixtures, start=1)
    }
    (run_dir / "molmospaces_backend_state.json").write_text(
        json.dumps({"backend": "molmospaces_subprocess", "receptacles": receptacles}) + "\n"
    )


def _run_result(
    run_dir: Path,
    *,
    completion_status: str,
    map_build: bool = False,
    task_intent: str = "cleanup",
    final_status: str | None = None,
    include_completion_claim: bool = False,
    include_runtime_map: bool = True,
    wall_time_s: float | None = None,
    backend: str = "api_semantic_synthetic",
) -> dict[str, Any]:
    completion_claim = (
        {
            "schema": "roboclaws_agent_completion_claim_v1",
            "completion_summary": "direct runner declared task complete",
        }
        if include_completion_claim
        else {}
    )
    result = {
        "score": {
            "completion_status": completion_status,
            "mess_restoration_rate": 1.0,
            "disturbance_count": 0,
            "failed_or_noop_tool_count": 0,
        },
        "completion_status": completion_status,
        "cleanup_status": completion_status,
        "task_intent": task_intent,
        "backend": backend,
        "final_status": final_status or completion_status,
        "map_build_mode": map_build,
        "agent_completion_claim": completion_claim,
        "tool_event_counts": {
            "metric_map:request": 1,
            "metric_map:response": 1,
            "done:response": 1,
        },
        "artifacts": {
            "run_result": str(run_dir / "run_result.json"),
            "report": str(run_dir / "report.html"),
        },
        "runtime_metric_map": (
            json.loads((run_dir / "runtime_metric_map.json").read_text())
            if include_runtime_map and (run_dir / "runtime_metric_map.json").exists()
            else {}
        ),
        "advisory_evaluation": json.loads((run_dir / "advisory_evaluation.json").read_text()),
        "policy_uses_private_truth": False,
        "planner_uses_private_manifest": False,
        "agent_view": {},
    }
    if wall_time_s is not None:
        result["wall_time_s"] = wall_time_s
    return result
