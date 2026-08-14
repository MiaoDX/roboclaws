# ruff: noqa: F403, F405
from tests.support.cleanup_checker_planner import *


def test_checker_rejects_agibot_hardware_without_runtime_metric_map(
    tmp_path: Path,
) -> None:
    checker = cleanup_checker
    run_dir = _write_agibot_map_build_fixture(tmp_path)
    data, path = checker.load_run_results(run_dir / "run_result.json")[0]
    _promote_agibot_fixture_to_hardware_shape(data, run_dir)
    data.pop("runtime_metric_map", None)
    agent_view = data["agent_view"]
    assert isinstance(agent_view, dict)
    agent_view.pop("runtime_metric_map", None)

    with pytest.raises(AssertionError):
        checker.validate_run_result(
            data,
            path.parent,
            expect_task=None,
            expect_backend="agibot_sdk_runner",
            min_generated_mess_count=0,
            require_map_build=True,
            require_agibot_g2_hardware=True,
            min_sweep_coverage=1.0,
        )


def test_checker_can_require_base_metric_map_map_build(tmp_path: Path) -> None:
    demo = _load_module(DEMO_PATH, "molmospaces_realworld_cleanup")
    checker = cleanup_checker

    result = demo.run_household_world_episode(
        output_dir=tmp_path,
        seed=7,
        intent="map-build",
    )

    checker.validate_run_result(
        result,
        tmp_path,
        expect_task=None,
        expect_backend="api_semantic_synthetic",
        min_generated_mess_count=5,
        require_runtime_metric_map=True,
        require_map_build=True,
        require_base_metric_map=True,
    )
    base_metric_map = agent_view_module.base_metric_map(result["agent_view"])
    assert base_metric_map["rooms"]
    assert base_metric_map["room_category_hints"]
    assert "static_fixture_projection" not in result["agent_view"]
    assert result["runtime_metric_map"]["static_map"]["fixtures"] == []
    assert result["runtime_metric_map"]["generated_exploration_candidates"]
    anchors = result["runtime_metric_map"]["public_semantic_anchors"]
    assert anchors
    assert any(item["anchor_type"] == "observation_waypoint" for item in anchors)
    assert any(item["anchor_type"] in {"fixture", "receptacle"} for item in anchors)


def test_checker_allows_map_build_robot_timeline_without_cleanup_actions(
    tmp_path: Path,
) -> None:
    demo = _load_module(DEMO_PATH, "molmospaces_realworld_cleanup")
    checker = cleanup_checker

    result = demo.run_household_world_episode(
        output_dir=tmp_path,
        seed=7,
        intent="map-build",
    )
    _add_molmospaces_robot_view_artifacts(result, tmp_path, prefix="scene")
    result["robot_view_steps"] = [
        _scene_context_robot_step("before"),
        _scene_context_robot_step("after"),
    ]

    checker.validate_run_result(
        result,
        tmp_path,
        expect_task=None,
        expect_backend="api_semantic_synthetic",
        min_generated_mess_count=5,
        require_runtime_metric_map=True,
        require_map_build=True,
        require_base_metric_map=True,
        require_robot_views=True,
    )
    assert not any(
        step.get("action", "").startswith(("pick ", "place "))
        for step in result["robot_view_steps"]
    )


def test_checker_rejects_runtime_metric_map_private_leak(tmp_path: Path) -> None:
    demo = _load_module(DEMO_PATH, "molmospaces_realworld_cleanup")
    checker = cleanup_checker

    result = demo.run_household_world_episode(output_dir=tmp_path, seed=7)
    result["runtime_metric_map"]["observed_objects"][0]["target_receptacle_id"] = "sink_01"
    result["agent_view"]["runtime_metric_map"] = result["runtime_metric_map"]

    with pytest.raises(AssertionError):
        checker.validate_run_result(
            result,
            tmp_path,
            expect_task=None,
            expect_backend="api_semantic_synthetic",
            min_generated_mess_count=5,
            require_runtime_metric_map=True,
        )


def test_checker_rejects_target_candidate_private_leak(tmp_path: Path) -> None:
    demo = _load_module(DEMO_PATH, "molmospaces_realworld_cleanup")
    checker = cleanup_checker

    result = demo.run_household_world_episode(output_dir=tmp_path, seed=7)
    result["runtime_metric_map"]["target_candidates"][0]["target_receptacle_id"] = "sink_01"
    result["agent_view"]["runtime_metric_map"] = result["runtime_metric_map"]

    with pytest.raises(AssertionError):
        checker.validate_run_result(
            result,
            tmp_path,
            expect_task=None,
            expect_backend="api_semantic_synthetic",
            min_generated_mess_count=5,
            require_runtime_metric_map=True,
            require_base_metric_map=True,
        )


def test_checker_rejects_non_actionable_target_candidate_without_reason(
    tmp_path: Path,
) -> None:
    demo = _load_module(DEMO_PATH, "molmospaces_realworld_cleanup")
    checker = cleanup_checker

    result = demo.run_household_world_episode(output_dir=tmp_path, seed=7)
    candidate = next(
        item
        for item in result["runtime_metric_map"]["target_candidates"]
        if item["target_actionability_status"] != "actionable"
    )
    candidate["rejection_reason"] = ""
    result["agent_view"]["runtime_metric_map"] = result["runtime_metric_map"]

    with pytest.raises(AssertionError):
        checker.validate_run_result(
            result,
            tmp_path,
            expect_task=None,
            expect_backend="api_semantic_synthetic",
            min_generated_mess_count=5,
            require_runtime_metric_map=True,
            require_base_metric_map=True,
        )


def test_checker_rejects_promoted_runtime_semantic_anchor(tmp_path: Path) -> None:
    demo = _load_module(DEMO_PATH, "molmospaces_realworld_cleanup")
    checker = cleanup_checker

    result = demo.run_household_world_episode(
        output_dir=tmp_path,
        seed=7,
        intent="map-build",
    )
    result["runtime_metric_map"]["public_semantic_anchors"][0]["promotion_status"] = "promoted"
    result["agent_view"]["runtime_metric_map"] = result["runtime_metric_map"]

    with pytest.raises(AssertionError):
        checker.validate_run_result(
            result,
            tmp_path,
            expect_task=None,
            expect_backend="api_semantic_synthetic",
            min_generated_mess_count=5,
            require_runtime_metric_map=True,
            require_map_build=True,
            require_base_metric_map=True,
        )


def test_checker_rejects_actionable_runtime_map_prior(tmp_path: Path) -> None:
    demo = _load_module(DEMO_PATH, "molmospaces_realworld_cleanup")
    checker = cleanup_checker

    sweep = demo.run_household_world_episode(
        output_dir=tmp_path / "sweep",
        seed=7,
        intent="map-build",
        perception_mode=CAMERA_MODEL_POLICY_MODE,
    )
    result = demo.run_household_world_episode(
        output_dir=tmp_path / "cleanup",
        seed=7,
        runtime_map_prior_path=sweep["artifacts"]["runtime_metric_map"],
    )
    prior = next(
        item
        for item in result["runtime_metric_map"]["observed_objects"]
        if item["freshness"] == "prior"
    )
    prior["actionability"] = "actionable"
    result["agent_view"]["runtime_metric_map"] = result["runtime_metric_map"]

    with pytest.raises(AssertionError):
        checker.validate_run_result(
            result,
            tmp_path / "cleanup",
            expect_task=None,
            expect_backend="api_semantic_synthetic",
            min_generated_mess_count=5,
            require_runtime_metric_map=True,
        )


def test_checker_allows_actionable_current_run_confirmation_of_prior(tmp_path: Path) -> None:
    demo = _load_module(DEMO_PATH, "molmospaces_realworld_cleanup")
    checker = cleanup_checker

    result = demo.run_household_world_episode(output_dir=tmp_path, seed=7)
    current = result["runtime_metric_map"]["observed_objects"][0]
    current["freshness"] = "current_run"
    current["prior_object_id"] = "observed_prior_001"
    current["snapshot_object_id"] = "observed_prior_001"
    current["actionability"] = "actionable"
    result["agent_view"]["runtime_metric_map"] = result["runtime_metric_map"]

    checker.validate_run_result(
        result,
        tmp_path,
        expect_task=None,
        expect_backend="api_semantic_synthetic",
        min_generated_mess_count=5,
        require_runtime_metric_map=True,
    )


def test_checker_accepts_smoke_profile_metadata_and_report_note(tmp_path: Path) -> None:
    demo = _load_module(DEMO_PATH, "molmospaces_realworld_cleanup")
    checker = cleanup_checker

    result = demo.run_household_world_episode(
        output_dir=tmp_path,
        seed=7,
        evidence_lane="smoke",
    )

    checker.validate_run_result(
        result,
        tmp_path,
        expect_task=None,
        expect_backend="api_semantic_synthetic",
        expect_profile="smoke",
        min_generated_mess_count=5,
    )


def test_checker_can_require_waypoint_honesty_and_real_robot_alignment(
    tmp_path: Path,
) -> None:
    demo = _load_module(DEMO_PATH, "molmospaces_realworld_cleanup")
    checker = cleanup_checker

    result = demo.run_household_world_episode(output_dir=tmp_path, seed=7)

    checker.validate_run_result(
        result,
        tmp_path,
        expect_task=None,
        expect_backend="api_semantic_synthetic",
        min_generated_mess_count=5,
        require_waypoint_honesty=True,
        require_real_robot_alignment=True,
    )


def test_checker_allows_base_metric_map_waypoint_honesty_for_scan_only_sweep(
    tmp_path: Path,
) -> None:
    demo = _load_module(DEMO_PATH, "molmospaces_realworld_cleanup")
    checker = cleanup_checker

    result = demo.run_household_world_episode(
        output_dir=tmp_path,
        seed=7,
        intent="map-build",
    )

    checker.validate_run_result(
        result,
        tmp_path,
        expect_task=None,
        expect_backend="api_semantic_synthetic",
        min_generated_mess_count=5,
        require_runtime_metric_map=True,
        require_map_build=True,
        require_base_metric_map=True,
        require_waypoint_honesty=True,
    )


def test_checker_allows_base_metric_map_waypoint_honesty_for_open_ended_scan_only(
    tmp_path: Path,
) -> None:
    demo = _load_module(DEMO_PATH, "molmospaces_realworld_cleanup")
    checker = cleanup_checker

    result = demo.run_household_world_episode(
        output_dir=tmp_path,
        seed=7,
    )
    result["task_intent"] = "open-ended"
    result["terminated_by"] = "agent_done"
    result["goal_contract"] = {
        "schema": "roboclaws_goal_contract_v1",
        "surface": "household-world",
        "intent": "open-ended",
        "normalized_goal": "我渴了，帮我找些解渴的东西",
        "goal_scope": "agent-declared",
    }
    trace = result["cleanup_policy_trace"]
    trace["loop_style"] = "scan_only"
    trace["cleanup_action_count"] = 0
    trace["placed_object_count"] = 0
    trace["post_place_observe_count"] = 0
    trace["events"] = [
        {"tool": "metric_map", "role": "setup_or_completion"},
        {"tool": "observe", "role": "coverage_scan_observe"},
        {"tool": "done", "role": "setup_or_completion"},
    ]

    checker.validate_run_result(
        result,
        tmp_path,
        expect_task=None,
        expect_backend="api_semantic_synthetic",
        min_generated_mess_count=5,
        allow_partial_cleanup=True,
        require_runtime_metric_map=True,
        require_base_metric_map=True,
        require_waypoint_honesty=True,
    )


def test_checker_allows_open_ended_agent_view_with_no_visible_objects(
    tmp_path: Path,
) -> None:
    demo = _load_module(DEMO_PATH, "molmospaces_realworld_cleanup")
    checker = cleanup_checker

    result = demo.run_household_world_episode(
        output_dir=tmp_path,
        seed=7,
    )
    result["generated_mess_count"] = 0
    result["requested_generated_mess_count"] = 0
    result["task_intent"] = "open-ended"
    result["terminated_by"] = "agent_done"
    result["goal_contract"] = {
        "schema": "roboclaws_goal_contract_v1",
        "surface": "household-world",
        "intent": "open-ended",
        "normalized_goal": "扫描下这个房间",
        "goal_scope": "agent-declared",
    }
    result["agent_completion_claim"] = {
        "schema": "roboclaws_agent_completion_claim_v1",
        "completion_summary": "完成扫描，未发现可见物体检测。",
        "why_done": "已观察公开探索点并提交结果。",
        "evidence_used": ["metric_map", "observe"],
        "remaining_risks": [],
    }
    result["private_evaluation"]["generated_mess_count"] = 0
    result["private_evaluation"]["acceptable_destination_sets"] = {}
    agent_view = result["agent_view"]
    agent_view_module.active_perception(agent_view)["observed_objects"] = []
    agent_view_module.active_perception(agent_view)["raw_fpv_observations"] = []
    agent_view_module.active_perception(agent_view)["model_declared_observations"] = []
    agent_view_module.task(agent_view)["perception_mode"] = "visible_object_detections"
    agent_view_module.task(agent_view)["structured_detections_available"] = True
    agent_view_module.active_perception(agent_view)["perception_mode"] = "visible_object_detections"
    agent_view_module.active_perception(agent_view)["structured_detections_available"] = True
    agent_view_module.runtime_metric_map(agent_view)["observed_objects"] = []

    checker.validate_run_result(
        result,
        tmp_path,
        expect_task=None,
        expect_backend="api_semantic_synthetic",
        min_generated_mess_count=0,
        allow_partial_cleanup=True,
        require_runtime_metric_map=True,
        require_base_metric_map=True,
        require_completion_claim=True,
    )


def test_checker_rejects_base_metric_map_waypoint_honesty_for_cleanup_scan_only(
    tmp_path: Path,
) -> None:
    demo = _load_module(DEMO_PATH, "molmospaces_realworld_cleanup")
    checker = cleanup_checker

    result = demo.run_household_world_episode(
        output_dir=tmp_path,
        seed=7,
    )
    trace = result["cleanup_policy_trace"]
    trace["loop_style"] = "scan_only"
    trace["cleanup_action_count"] = 0

    with pytest.raises(AssertionError):
        checker.validate_run_result(
            result,
            tmp_path,
            expect_task=None,
            expect_backend="api_semantic_synthetic",
            min_generated_mess_count=5,
            allow_partial_cleanup=True,
            require_runtime_metric_map=True,
            require_base_metric_map=True,
            require_waypoint_honesty=True,
        )


def test_checker_allows_base_metric_map_waypoint_honesty_for_survey_first_cleanup(
    tmp_path: Path,
) -> None:
    demo = _load_module(DEMO_PATH, "molmospaces_realworld_cleanup")
    checker = cleanup_checker

    result = demo.run_household_world_episode(
        output_dir=tmp_path,
        seed=7,
    )
    result["cleanup_policy_trace"]["post_place_observe_count"] = 0

    checker.validate_run_result(
        result,
        tmp_path,
        expect_task=None,
        expect_backend="api_semantic_synthetic",
        min_generated_mess_count=5,
        require_runtime_metric_map=True,
        require_base_metric_map=True,
        require_waypoint_honesty=True,
    )
    trace = result["cleanup_policy_trace"]
    assert trace["waypoint_source"] == "generated_exploration_candidate"
    assert trace["loop_style"] == "survey_first_cleanup_loop"
    assert trace["first_cleanup_before_full_survey"] is False
    assert trace["placed_object_count"] == 5


def test_checker_allows_base_metric_map_waypoint_honesty_for_online_interleaved_cleanup(
    tmp_path: Path,
) -> None:
    demo = _load_module(DEMO_PATH, "molmospaces_realworld_cleanup")
    checker = cleanup_checker

    result = demo.run_household_world_episode(
        output_dir=tmp_path,
        seed=7,
    )
    trace = result["cleanup_policy_trace"]
    trace["loop_style"] = "interleaved_cleanup_loop"
    trace["first_cleanup_before_full_survey"] = True

    checker.validate_run_result(
        result,
        tmp_path,
        expect_task=None,
        expect_backend="api_semantic_synthetic",
        min_generated_mess_count=5,
        require_runtime_metric_map=True,
        require_base_metric_map=True,
        require_waypoint_honesty=True,
    )


def test_checker_allows_base_metric_map_without_map_build_metadata(
    tmp_path: Path,
) -> None:
    demo = _load_module(DEMO_PATH, "molmospaces_realworld_cleanup")
    checker = cleanup_checker

    result = demo.run_household_world_episode(
        output_dir=tmp_path,
        seed=7,
    )
    result["map_build"] = None
    result["map_build_mode"] = None

    checker.validate_run_result(
        result,
        tmp_path,
        expect_task=None,
        expect_backend="api_semantic_synthetic",
        min_generated_mess_count=5,
        require_runtime_metric_map=True,
        require_base_metric_map=True,
        require_waypoint_honesty=True,
    )


def test_checker_rejects_minimal_interleaved_cleanup_without_full_sweep(
    tmp_path: Path,
) -> None:
    demo = _load_module(DEMO_PATH, "molmospaces_realworld_cleanup")
    checker = cleanup_checker

    result = demo.run_household_world_episode(
        output_dir=tmp_path,
        seed=7,
    )
    trace = result["cleanup_policy_trace"]
    trace["loop_style"] = "interleaved_cleanup_loop"
    trace["first_cleanup_before_full_survey"] = True
    trace["observed_waypoint_count"] = max(0, int(trace["total_waypoints"]) - 1)

    with pytest.raises(AssertionError):
        checker.validate_run_result(
            result,
            tmp_path,
            expect_task=None,
            expect_backend="api_semantic_synthetic",
            min_generated_mess_count=5,
            require_runtime_metric_map=True,
            require_base_metric_map=True,
            require_waypoint_honesty=True,
        )


def test_checker_accepts_isaac_selected_bindings_when_rows_match_scene_index(
    tmp_path: Path,
) -> None:
    checker = cleanup_checker
    scene_bindings = _isaac_selected_scene_bindings()
    data = _isaac_runtime_result(tmp_path, scene_bindings)
    _write_isaac_scene_index(tmp_path, scene_bindings)

    checker._assert_isaac_runtime(
        data,
        tmp_path,
        _isaac_report_text(scene_bindings),
        require_real_runtime=False,
        require_scene_loaded=False,
        require_selected_usd_bindings=True,
        require_semantic_pose=False,
        require_robot_view_provenance=False,
        require_segmentation_evidence=False,
        require_snapshot_provenance=False,
    )


def test_checker_accepts_isaac_scene_index_map_context(
    tmp_path: Path,
) -> None:
    checker = cleanup_checker
    scene_bindings = _isaac_selected_scene_bindings()
    data = _isaac_runtime_result(tmp_path, scene_bindings)
    _write_isaac_scene_index(tmp_path, scene_bindings)
    _add_isaac_scene_index_map_context(data, tmp_path)

    checker._assert_isaac_runtime(
        data,
        tmp_path,
        _isaac_report_text(scene_bindings),
        require_real_runtime=False,
        require_scene_loaded=False,
        require_selected_usd_bindings=False,
        require_semantic_pose=False,
        require_robot_view_provenance=False,
        require_segmentation_evidence=False,
        require_snapshot_provenance=False,
        require_scene_index_map_context=True,
    )


def test_checker_accepts_isaac_scene_index_base_metric_map_context(
    tmp_path: Path,
) -> None:
    checker = cleanup_checker
    scene_bindings = _isaac_selected_scene_bindings()
    data = _isaac_runtime_result(tmp_path, scene_bindings)
    _write_isaac_scene_index(tmp_path, scene_bindings)
    _add_isaac_scene_index_base_metric_map_context(data, tmp_path)

    checker._assert_isaac_runtime(
        data,
        tmp_path,
        _isaac_report_text(scene_bindings),
        require_real_runtime=False,
        require_scene_loaded=False,
        require_selected_usd_bindings=False,
        require_semantic_pose=False,
        require_robot_view_provenance=False,
        require_segmentation_evidence=False,
        require_snapshot_provenance=False,
        require_scene_index_map_context=True,
    )
