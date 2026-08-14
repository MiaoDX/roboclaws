from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

import pytest

from roboclaws.household import agent_view as agent_view_module
from roboclaws.household.agibot_map_bundle import write_agibot_nav2_map_bundle
from roboclaws.household.household_runtime_contract import (
    CAMERA_MODEL_POLICY_MODE,
    CAMERA_MODEL_POLICY_NAME,
    RAW_FPV_ONLY_MODE,
    REALWORLD_CONTRACT,
)
from roboclaws.household.isaac_lab_backend import (
    ISAAC_SCENE_INDEX_ARTIFACT_SCHEMA,
    ISAAC_SEMANTIC_POSE_STATE_SCHEMA,
    ISAACLAB_ROBOT_VIEW_VARIANT,
)
from roboclaws.household.semantic_timeline import (
    CANONICAL_BASE_CLEANUP_PHASES,
    CLOSE_RECEPTACLE_PHASE,
    PLACE_CLEANUP_PHASES,
    SEMANTIC_LOOP_VARIANT,
)
from roboclaws.household.tasks import HOUSEHOLD_TASK_SPECS
from roboclaws.launch.goals import normalize_goal_contract
from roboclaws.launch.intents import TASK_INTENT_SPECS
from scripts.molmo_cleanup import isaac_runtime_checker

REPO_ROOT = Path(__file__).resolve().parents[3]
DEMO_PATH = REPO_ROOT / "examples" / "molmo_cleanup" / "molmospaces_realworld_cleanup.py"
CHECKER_PATH = REPO_ROOT / "scripts" / "molmo_cleanup" / "check_molmo_realworld_cleanup_result.py"
AGIBOT_SEMANTIC_ACTIONS_PATH = (
    REPO_ROOT / "scripts" / "molmo_cleanup" / "run_agibot_robot_map_9_semantic_actions.py"
)
PREBUILT_BUNDLE = REPO_ROOT / "assets" / "maps" / "molmospaces" / "procthor-10k-val" / "0"
ROBOT_MAP_9_ARTIFACT = REPO_ROOT / "vendors" / "agibot_sdk" / "artifacts" / "maps" / "robot_map_9"
ROBOT_MAP_9_CONTEXT = REPO_ROOT / "tests" / "fixtures" / "agibot_robot_map_9_context.completed.json"
ROBOT_MAP_12_ARTIFACT = REPO_ROOT / "tests" / "fixtures" / "runtime_map_prior" / "robot_map_12"


def _require_robot_map_9_artifact() -> None:
    if not (
        (ROBOT_MAP_9_ARTIFACT / "source.json").is_file()
        or (ROBOT_MAP_9_ARTIFACT / "agibot" / "source.json").is_file()
    ):
        pytest.skip("Agibot robot_map_9 artifact is unavailable in this checkout")


def _load_demo_module():
    spec = importlib.util.spec_from_file_location("molmospaces_realworld_cleanup", DEMO_PATH)
    assert spec is not None
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def _load_checker_module():
    spec = importlib.util.spec_from_file_location(
        "check_molmo_realworld_cleanup_result",
        CHECKER_PATH,
    )
    assert spec is not None
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def _load_agibot_semantic_actions_module():
    spec = importlib.util.spec_from_file_location(
        "run_agibot_robot_map_9_semantic_actions",
        AGIBOT_SEMANTIC_ACTIONS_PATH,
    )
    assert spec is not None
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def test_realworld_cleanup_demo_writes_public_private_artifacts(tmp_path: Path) -> None:
    demo = _load_demo_module()

    result = demo.run_household_world_episode(
        output_dir=tmp_path,
        seed=7,
        map_bundle_dir=PREBUILT_BUNDLE,
    )

    run_result = json.loads((tmp_path / "run_result.json").read_text(encoding="utf-8"))
    trace_lines = (tmp_path / "trace.jsonl").read_text(encoding="utf-8").splitlines()
    report_text = (tmp_path / "report.html").read_text(encoding="utf-8")

    _assert_cleanup_result_contract(result, run_result)
    _assert_cleanup_public_private_artifacts(tmp_path)
    _assert_cleanup_report_and_trace(report_text, trace_lines)


def _assert_cleanup_result_contract(
    result: dict[str, object],
    run_result: dict[str, object],
) -> None:
    assert result["cleanup_status"] == "success"
    assert result["contract"] == REALWORLD_CONTRACT
    assert result["adr_0003_satisfied"] is True
    assert run_result["policy"] == "deterministic_sweep_baseline"
    assert run_result["policy_uses_private_truth"] is False
    assert run_result["planner_uses_private_manifest"] is False
    assert run_result["static_fixture_projection_mode"] == "room_only"
    assert run_result["requested_generated_mess_count"] == 10
    assert run_result["generated_mess_count"] == 5
    assert run_result["mess_restoration_rate"] >= 0.70
    assert run_result["sweep_coverage_rate"] >= 0.90
    assert run_result["disturbance_count"] <= 2
    assert run_result["semantic_loop_variant"] == SEMANTIC_LOOP_VARIANT
    for item in run_result["semantic_substeps"]:
        phases = [step["phase"] for step in item["steps"]]
        assert phases[:3] == list(CANONICAL_BASE_CLEANUP_PHASES)
        assert phases[-1] in {*PLACE_CLEANUP_PHASES, CLOSE_RECEPTACLE_PHASE}
    assert agent_view_module.observed_objects(run_result["agent_view"])
    assert "generated_mess_set" not in run_result["agent_view"]
    assert "acceptable_destination_sets" not in run_result["agent_view"]
    assert "planner_object_id" not in json.dumps(run_result["agent_view"])
    assert run_result["private_evaluation"]["generated_mess_set"]
    assert run_result["private_evaluation"]["requested_generated_mess_count"] == 10
    assert run_result["planner_proof_requests"]["schema"] == "planner_cleanup_proof_requests_v1"
    assert run_result["planner_proof_requests"]["agent_view_exposed"] is False
    assert run_result["artifacts"]["planner_proof_requests"].endswith("planner_proof_requests.json")
    assert run_result["nav2_map_bundle"]["snapshot_complete"] is True
    assert run_result["nav2_map_bundle"]["source_bundle_root"] == str(PREBUILT_BUNDLE)
    assert agent_view_module.base_metric_map(run_result["agent_view"])["map_bundle"][
        "environment_id"
    ] == ("molmospaces-procthor-10k-val-0")
    assert run_result["artifacts"]["nav2_map_yaml"].endswith("map_bundle/map.yaml")
    assert run_result["real_robot_readiness"]["map_bundle_snapshot_present"] is True
    assert run_result["advisory_evaluation"]["authoritative"] is False
    assert run_result["advisory_evaluation"]["object_reviews"]


def _assert_cleanup_public_private_artifacts(tmp_path: Path) -> None:
    assert (tmp_path / "agent_view.json").is_file()
    assert (tmp_path / "private_evaluation.json").is_file()
    assert (tmp_path / "advisory_evaluation.json").is_file()
    assert (tmp_path / "planner_proof_requests.json").is_file()
    assert (tmp_path / "map_bundle" / "map.yaml").is_file()
    assert (tmp_path / "map_bundle" / "map.pgm").is_file()
    assert (tmp_path / "map_bundle" / "semantics.json").is_file()
    assert (tmp_path / "map_bundle" / "profiles" / "rby1m.yaml").is_file()
    assert (tmp_path / "map_bundle" / "costmaps" / "rby1m.costmap_params.yaml").is_file()
    assert (tmp_path / "map_bundle" / "preview.png").is_file()
    assert (tmp_path / "before.png").is_file()
    assert (tmp_path / "after.png").is_file()
    assert (tmp_path / "report.html").is_file()


def _assert_cleanup_report_and_trace(
    report_text: str,
    trace_lines: list[str],
) -> None:
    assert "Planner Proof Requests" in report_text
    assert "Nav2 Map Bundle" in report_text
    assert "map_bundle/map.yaml" in report_text
    assert any('"tool": "metric_map"' in line for line in trace_lines)
    assert any('"tool": "observe"' in line for line in trace_lines)
    assert not any('"tool": "scene_objects"' in line for line in trace_lines)


def test_realworld_cleanup_demo_writes_open_ended_goal_status(
    tmp_path: Path,
) -> None:
    demo = _load_demo_module()
    prompt = "我渴了，帮我找些解渴的东西"
    goal_contract = normalize_goal_contract(
        surface=HOUSEHOLD_TASK_SPECS["household-world"],
        intent=TASK_INTENT_SPECS["open-ended"],
        raw_prompt=prompt,
    )

    result = demo.run_household_world_episode(
        output_dir=tmp_path,
        seed=7,
        task_prompt=prompt,
        goal_contract_json=goal_contract.to_json(),
        generated_mess_count=1,
        map_bundle_dir=PREBUILT_BUNDLE,
    )
    run_result = json.loads((tmp_path / "run_result.json").read_text(encoding="utf-8"))
    goal_artifact = json.loads((tmp_path / "goal_contract.json").read_text(encoding="utf-8"))

    assert result["task_intent"] == "open-ended"
    assert run_result["goal_contract"]["intent"] == "open-ended"
    assert goal_artifact["normalized_goal"] == prompt
    assert result["agent_completion_claim"]["completion_summary"]
    assert result["intent_status"] == result["goal_status"] == result["final_status"] == "success"
    assert result["cleanup_status_role"] == "advisory"


def test_realworld_cleanup_product_gate_rejects_legacy_agibot_robot_map_9_bundle(
    tmp_path: Path,
) -> None:
    _require_robot_map_9_artifact()
    demo = _load_demo_module()
    bundle_dir = tmp_path / "agibot-robot-map-9-bundle"
    write_agibot_nav2_map_bundle(
        source_map_dir=ROBOT_MAP_9_ARTIFACT,
        context_json=ROBOT_MAP_9_CONTEXT,
        bundle_dir=bundle_dir,
    )

    with pytest.raises(ValueError, match="invalid Base Metric Map v1 bundle"):
        demo.run_household_world_episode(
            output_dir=tmp_path / "run",
            seed=7,
            map_bundle_dir=bundle_dir,
            generated_mess_count=5,
        )


def test_agibot_semantic_actions_rehearsal_uses_legacy_rich_bundle_and_is_not_product_runtime(
    tmp_path: Path,
) -> None:
    _require_robot_map_9_artifact()
    rehearsal = _load_agibot_semantic_actions_module()

    with pytest.raises(ValueError, match="invalid Base Metric Map v1 bundle"):
        rehearsal.run_agibot_robot_map_9_semantic_actions(
            run_dir=tmp_path / "run",
            context_json=ROBOT_MAP_9_CONTEXT,
            agibot_map_artifact_dir=ROBOT_MAP_9_ARTIFACT,
        )


def test_realworld_cleanup_live_bundle_gate_requires_selected_bundle(tmp_path: Path) -> None:
    demo = _load_demo_module()

    try:
        demo.run_household_world_episode(output_dir=tmp_path, seed=7)
    except ValueError as exc:
        assert "map_bundle_dir is required" in str(exc)
    else:  # pragma: no cover - assertion branch
        raise AssertionError("expected missing map bundle to fail")


def test_realworld_cleanup_live_bundle_gate_rejects_invalid_bundle(tmp_path: Path) -> None:
    demo = _load_demo_module()
    invalid_bundle = tmp_path / "invalid-bundle"
    invalid_bundle.mkdir()

    try:
        demo.run_household_world_episode(
            output_dir=tmp_path / "run",
            seed=7,
            map_bundle_dir=invalid_bundle,
        )
    except ValueError as exc:
        assert "invalid Base Metric Map v1 bundle" in str(exc)
    else:  # pragma: no cover - assertion branch
        raise AssertionError("expected invalid selected bundle to fail before cleanup")


def test_realworld_cleanup_report_separates_agent_view_and_private_eval(
    tmp_path: Path,
) -> None:
    demo = _load_demo_module()

    demo.run_household_world_episode(
        output_dir=tmp_path,
        seed=7,
        map_bundle_dir=PREBUILT_BUNDLE,
    )

    report = (tmp_path / "report.html").read_text(encoding="utf-8")
    assert "Agent View" in report
    assert "Private Evaluation" in report
    assert "Advisory Review" in report
    assert "Generated mess" in report
    assert "ADR-0003 real-world-style cleanup run" not in report


def test_realworld_cleanup_demo_persists_facade_rerun_command(
    tmp_path: Path,
    monkeypatch,
) -> None:
    demo = _load_demo_module()
    prior = "output/household/household-world/map-build/anchor/seed-7/runtime_metric_map.json"
    command = (
        "just run::surface surface=household-world world=molmospaces/procthor-10k-val/0 "
        "backend=mujoco intent=cleanup agent_engine=openai-agents-sdk "
        "provider_profile=kimi-openai-chat evidence_lane=world-public-labels seed=7 "
        "scenario_setup=relocate-cleanup-related-objects relocation_count=5 "
        "robot_views=on "
        f"runtime_map_prior={prior} "
        f"output_dir={tmp_path}"
    )
    monkeypatch.setenv("ROBOCLAWS_REPORT_RERUN_COMMAND", command)

    demo.run_household_world_episode(
        output_dir=tmp_path,
        seed=7,
        generated_mess_count=5,
        map_bundle_dir=PREBUILT_BUNDLE,
    )

    run_result = json.loads((tmp_path / "run_result.json").read_text(encoding="utf-8"))
    report = (tmp_path / "report.html").read_text(encoding="utf-8")
    assert run_result["rerun_command"] == command
    assert "just run::surface \\\n" in report
    for arg in (
        "surface=household-world",
        "world=molmospaces/procthor-10k-val/0",
        "backend=mujoco",
        "intent=cleanup",
        "agent_engine=openai-agents-sdk",
        "provider_profile=kimi-openai-chat",
        "evidence_lane=world-public-labels",
        f"output_dir={tmp_path}",
    ):
        assert arg in report
    assert "household-cleanup direct world-public-labels" not in report


def test_realworld_cleanup_demo_can_run_raw_fpv_evidence_mode(tmp_path: Path) -> None:
    demo = _load_demo_module()

    result = demo.run_household_world_episode(
        output_dir=tmp_path,
        seed=7,
        perception_mode=RAW_FPV_ONLY_MODE,
        map_bundle_dir=PREBUILT_BUNDLE,
    )
    report = (tmp_path / "report.html").read_text(encoding="utf-8")

    assert result["perception_mode"] == RAW_FPV_ONLY_MODE
    assert result["cleanup_status"] == "success"
    assert agent_view_module.observed_objects(result["agent_view"])
    assert agent_view_module.raw_fpv_observations(result["agent_view"])
    assert result["model_declared_observations"]
    evidence = result["model_declared_observation_evidence"]
    assert evidence["observation_count"] >= result["generated_mess_count"]
    assert evidence["resolved_count"] >= result["generated_mess_count"]
    assert all(
        item.get("actionability_status") in {"actionable", "already_handled"}
        for item in result["model_declared_observations"]
    )
    assert result["raw_fpv_observations"]
    assert "Raw FPV Observations" in report
    assert "Model-Declared Observations" in report


def test_realworld_cleanup_demo_can_run_camera_model_policy_mode(tmp_path: Path) -> None:
    demo = _load_demo_module()

    result = demo.run_household_world_episode(
        output_dir=tmp_path,
        seed=7,
        perception_mode=CAMERA_MODEL_POLICY_MODE,
        map_bundle_dir=PREBUILT_BUNDLE,
    )
    report = (tmp_path / "report.html").read_text(encoding="utf-8")

    assert result["perception_mode"] == CAMERA_MODEL_POLICY_MODE
    assert result["policy"] == CAMERA_MODEL_POLICY_NAME
    assert result["cleanup_status"] == "success"
    assert agent_view_module.observed_objects(result["agent_view"])
    assert result["raw_fpv_observations"]
    assert result["camera_model_policy_evidence"]["enabled"] is True
    assert result["camera_model_policy_evidence"]["candidate_count"] >= 1
    assert result["tool_event_counts"]["declare_visual_candidates:request"] >= 1
    assert "Camera Labeler Evidence" in report
    assert "Model-Declared Observations" in report
    assert "Raw FPV Observations" in report
    assert "Semantic Substeps" in report


def test_realworld_cleanup_demo_can_run_isaaclab_fake_backend(
    tmp_path: Path,
    monkeypatch,
) -> None:
    demo = _load_demo_module()
    checker = _load_checker_module()
    monkeypatch.setenv("ROBOCLAWS_ISAACLAB_PYTHON", sys.executable)
    monkeypatch.setenv("ROBOCLAWS_ISAACLAB_RUNTIME_MODE", "fake")

    result = demo.run_household_world_episode(
        output_dir=tmp_path,
        seed=7,
        backend="isaaclab_subprocess",
        include_robot=True,
        record_robot_views=True,
        generated_mess_count=1,
        evidence_lane="world-public-labels",
        map_bundle_dir=PREBUILT_BUNDLE,
    )

    run_result = json.loads((tmp_path / "run_result.json").read_text(encoding="utf-8"))
    report_text = (tmp_path / "report.html").read_text(encoding="utf-8")
    isaac_scene_index = json.loads(
        (tmp_path / "isaac_scene_index.json").read_text(encoding="utf-8")
    )

    _assert_isaac_fake_cleanup_result(result, run_result)
    _assert_isaac_fake_scene_index(tmp_path, run_result, isaac_scene_index)
    _assert_isaac_fake_semantic_pose_and_robot_views(run_result)
    _assert_isaac_fake_report(report_text, run_result, isaac_scene_index)
    _assert_isaac_fake_checker_contract(checker, run_result, tmp_path)


def _assert_isaac_fake_cleanup_result(
    result: dict[str, object],
    run_result: dict[str, object],
) -> None:
    assert result["backend"] == "isaaclab_subprocess"
    assert result["generated_mess_count"] == 1
    assert result["primitive_provenance"] == "isaac_semantic_pose"
    assert result["manipulation_evidence"]["isaac_semantic_pose_edits"] is True
    assert result["manipulation_evidence"]["planner_backed"] is False
    assert agent_view_module.observed_objects(result["agent_view"])
    assert result["semantic_substeps"]
    assert result["score"]["semantic_acceptability"]["accepted_count"] >= 1
    assert run_result["isaac_runtime"]["runtime"]["runtime_mode"] == "fake"
    assert run_result["isaac_runtime"]["runtime"]["rendering"]["status"] == "fake_protocol"
    assert run_result["isaac_runtime"]["runtime"]["rendering"]["real_rendering_proven"] is False
    assert run_result["isaac_runtime"]["scene_load"]["status"] == "fake_protocol"
    assert run_result["isaac_runtime"]["scene_load"]["usd_stage_loaded"] is False
    assert run_result["isaac_runtime"]["scene_binding_diagnostics"]["status"] == (
        "placeholder_mapping"
    )


def _assert_isaac_fake_scene_index(
    tmp_path: Path,
    run_result: dict[str, object],
    isaac_scene_index: dict[str, object],
) -> None:
    assert run_result["isaac_runtime"]["scene_index_artifact"] == str(
        tmp_path / "isaac_scene_index.json"
    )
    assert run_result["artifacts"]["isaac_scene_index"] == str(tmp_path / "isaac_scene_index.json")
    assert isaac_scene_index["schema"] == ISAAC_SCENE_INDEX_ARTIFACT_SCHEMA
    assert isaac_scene_index["backend"] == "isaaclab_subprocess"
    assert isaac_scene_index["agent_facing"] is False
    assert isaac_scene_index["private_manifest_exposed_to_agent"] is False
    assert "private_manifest" not in isaac_scene_index
    assert isaac_scene_index["scene_load"]["status"] == "fake_protocol"
    assert isaac_scene_index["generated_mess_count"] == 1
    assert isaac_scene_index["object_index"]
    assert isaac_scene_index["receptacle_index"]
    assert run_result["isaac_runtime"]["object_index"] == isaac_scene_index["object_index"]
    assert run_result["isaac_runtime"]["receptacle_index"] == isaac_scene_index["receptacle_index"]
    assert (
        run_result["isaac_runtime"]["scene_binding_diagnostics"][
            "private_manifest_exposed_to_agent"
        ]
        is False
    )
    assert run_result["isaac_runtime"]["mapping_gaps"]
    assert run_result["isaac_runtime"]["segmentation"]["status"] == "blocked_capability"
    assert run_result["isaac_runtime"]["segmentation"]["agent_facing"] is False
    assert run_result["isaac_runtime"]["segmentation"]["no_simulator_label_fallback"] is True
    assert len(run_result["isaac_runtime"]["snapshot_artifacts"]) == 2
    assert all(
        item["placeholder_visuals"] is True
        for item in run_result["isaac_runtime"]["snapshot_artifacts"]
    )


def _assert_isaac_fake_semantic_pose_and_robot_views(run_result: dict[str, object]) -> None:
    semantic_pose_state = run_result["isaac_runtime"]["semantic_pose_state"]
    assert semantic_pose_state["schema"] == ISAAC_SEMANTIC_POSE_STATE_SCHEMA
    assert semantic_pose_state["rendered_to_usd"] is False
    assert semantic_pose_state["planner_backed"] is False
    assert semantic_pose_state["physical_robot"] is False
    assert len(semantic_pose_state["transform_events"]) >= 4
    assert semantic_pose_state["object_poses"]
    assert any(
        event["state_mutation"] == "isaac_prim_transform"
        for event in semantic_pose_state["transform_events"]
    )
    assert run_result["evidence_lane_metadata"]["backend"] == "isaaclab_subprocess"
    assert run_result["evidence_lane_metadata"]["world_backend"] == "isaac_sim"
    assert run_result["view_variant"] == ISAACLAB_ROBOT_VIEW_VARIANT
    assert run_result["robot_view_steps"]
    assert run_result["robot_view_camera_control"]["schema"] == (
        "robot_view_camera_control_summary_v1"
    )
    assert run_result["robot_view_camera_control"]["step_count"] == len(
        run_result["robot_view_steps"]
    )


def _assert_isaac_fake_report(
    report_text: str,
    run_result: dict[str, object],
    isaac_scene_index: dict[str, object],
) -> None:
    assert "Isaac Runtime Diagnostics" in report_text
    assert "Mapping gaps" in report_text
    assert "Selected USD bindings" in report_text
    assert "Scene index artifact" in report_text
    assert "Scene Index Artifact Rows" in report_text
    assert "Selected USD Binding Rows" in report_text
    assert "Selected USD Index Rows" in report_text
    assert "isaac_scene_index.json" in report_text
    selected_object_binding = next(
        iter(isaac_scene_index["scene_binding_diagnostics"]["selected_object_bindings"].values())
    )
    selected_receptacle_binding = next(
        iter(
            isaac_scene_index["scene_binding_diagnostics"][
                "selected_target_receptacle_bindings"
            ].values()
        )
    )
    semantic_pose_state = run_result["isaac_runtime"]["semantic_pose_state"]
    first_pose_object_id = next(iter(semantic_pose_state["object_poses"]))
    assert selected_object_binding["usd_prim_path"] in report_text
    assert selected_receptacle_binding["usd_prim_path"] in report_text
    assert "placeholder_visuals" in report_text
    assert "Semantic pose events" in report_text
    assert "Semantic Pose State" in report_text
    assert "Semantic Pose Events" in report_text
    assert "Rendered to USD" in report_text
    assert "Planner backed" in report_text
    assert "isaac_prim_transform" in report_text
    assert first_pose_object_id in report_text
    assert "isaac_semantic_pose" in report_text
    isaac_runtime_checker._assert_isaac_scene_index_report_rows(
        run_result["isaac_runtime"]["scene_binding_diagnostics"],
        report_text,
    )


def _assert_isaac_fake_checker_contract(
    checker,
    run_result: dict[str, object],
    tmp_path: Path,
) -> None:
    checker._assert_result(
        run_result,
        tmp_path,
        expect_task=None,
        expect_backend="isaaclab_subprocess",
        expect_policy="deterministic_sweep_baseline",
        expect_profile="world-public-labels",
        min_generated_mess_count=1,
        require_robot_views=True,
        require_advisory_scoring=True,
        min_semantic_accepted_count=1,
        min_sweep_coverage=1.0,
        require_waypoint_honesty=True,
        require_real_robot_alignment=True,
        require_isaac_runtime=True,
        require_isaac_semantic_pose=True,
    )
    with pytest.raises(AssertionError):
        checker._assert_result(
            run_result,
            tmp_path,
            expect_task=None,
            expect_backend="isaaclab_subprocess",
            require_isaac_runtime=True,
            require_isaac_snapshot_provenance=True,
        )
    with pytest.raises(AssertionError):
        checker._assert_result(
            run_result,
            tmp_path,
            expect_task=None,
            expect_backend="isaaclab_subprocess",
            expect_policy="deterministic_sweep_baseline",
            expect_profile="world-public-labels",
            min_generated_mess_count=1,
            require_robot_views=True,
            require_isaac_runtime=True,
            require_isaac_real_runtime=True,
            require_isaac_selected_usd_bindings=True,
            require_isaac_robot_view_provenance=True,
            require_isaac_segmentation_evidence=True,
            require_isaac_snapshot_provenance=True,
        )
