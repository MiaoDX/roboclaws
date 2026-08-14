# ruff: noqa: F403, F405, F841
from tests.support.cleanup_checker_planner import *


def test_checker_rejects_canonical_free_camera_when_head_camera_required(
    tmp_path: Path,
) -> None:
    demo = _load_module(DEMO_PATH, "molmospaces_realworld_cleanup")
    checker = cleanup_checker

    data = demo.run_household_world_episode(output_dir=tmp_path, seed=7)
    _add_isaac_robot_view_step(
        data,  # type: ignore[arg-type]
        tmp_path,
        capture_method="isaac_lab_camera_rgb_semantic_pose_robot_views",
        semantic_pose_state_refreshed=True,
        canonical_camera_control=True,
    )
    data["view_variant"] = MOLMOSPACES_ROBOT_VIEW_VARIANT

    with pytest.raises(AssertionError):
        checker.validate_run_result(
            data,
            tmp_path,
            expect_task=None,
            expect_backend="api_semantic_synthetic",
            min_generated_mess_count=0,
            allow_partial_cleanup=True,
            require_robot_head_camera_fpv=True,
        )


def test_checker_rejects_head_camera_contract_without_head_camera_source(
    tmp_path: Path,
) -> None:
    demo = _load_module(DEMO_PATH, "molmospaces_realworld_cleanup")
    checker = cleanup_checker

    data = demo.run_household_world_episode(output_dir=tmp_path, seed=7)
    _add_isaac_robot_view_step(
        data,  # type: ignore[arg-type]
        tmp_path,
        capture_method="isaac_lab_camera_rgb_semantic_pose_robot_views",
        semantic_pose_state_refreshed=True,
        head_camera_equivalent=True,
    )
    for step in data["robot_view_steps"]:
        step["camera_control_contract"]["agent_facing_fpv"] = {
            "source": "isaac_lab_scene_bounds_fpv",
            "canonical_camera_control": False,
        }
    data["view_variant"] = MOLMOSPACES_ROBOT_VIEW_VARIANT

    with pytest.raises(AssertionError):
        checker.validate_run_result(
            data,
            tmp_path,
            expect_task=None,
            expect_backend="api_semantic_synthetic",
            min_generated_mess_count=0,
            allow_partial_cleanup=True,
            require_robot_head_camera_fpv=True,
        )


def test_checker_rejects_refreshed_isaac_semantic_pose_without_refreshed_views(
    tmp_path: Path,
) -> None:
    checker = cleanup_checker
    scene_bindings = _isaac_selected_scene_bindings()
    semantic_pose_state = _isaac_semantic_pose_state_with_refreshed_robot_views()
    data = _isaac_runtime_result(
        tmp_path,
        scene_bindings,
        semantic_pose_state=semantic_pose_state,
    )
    _write_isaac_scene_index(tmp_path, scene_bindings)
    _add_isaac_robot_view_step(data, tmp_path)

    with pytest.raises(AssertionError):
        checker._assert_isaac_runtime(
            data,
            tmp_path,
            _isaac_report_text(scene_bindings, semantic_pose_state=semantic_pose_state),
            require_real_runtime=False,
            require_scene_loaded=False,
            require_selected_usd_bindings=True,
            require_semantic_pose=True,
            require_robot_view_provenance=True,
            require_segmentation_evidence=False,
            require_snapshot_provenance=False,
        )


def test_checker_rejects_isaac_semantic_pose_object_path_drift_from_scene_index(
    tmp_path: Path,
) -> None:
    checker = cleanup_checker
    scene_bindings = _isaac_selected_scene_bindings()
    semantic_pose_state = _isaac_semantic_pose_state()
    semantic_pose_state["object_poses"]["mug_01"]["usd_prim_path"] = "/World/Objects/other_mug"
    data = _isaac_runtime_result(
        tmp_path,
        scene_bindings,
        semantic_pose_state=semantic_pose_state,
    )
    _write_isaac_scene_index(tmp_path, scene_bindings)

    with pytest.raises(AssertionError):
        checker._assert_isaac_runtime(
            data,
            tmp_path,
            _isaac_report_text(scene_bindings, semantic_pose_state=semantic_pose_state),
            require_real_runtime=False,
            require_scene_loaded=False,
            require_selected_usd_bindings=True,
            require_semantic_pose=True,
            require_robot_view_provenance=False,
            require_segmentation_evidence=False,
            require_snapshot_provenance=False,
        )


def test_checker_rejects_isaac_semantic_pose_receptacle_path_drift_from_scene_index(
    tmp_path: Path,
) -> None:
    checker = cleanup_checker
    scene_bindings = _isaac_selected_scene_bindings()
    semantic_pose_state = _isaac_semantic_pose_state()
    semantic_pose_state["transform_events"][0]["receptacle_usd_prim_path"] = (
        "/World/Receptacles/other_sink"
    )
    data = _isaac_runtime_result(
        tmp_path,
        scene_bindings,
        semantic_pose_state=semantic_pose_state,
    )
    _write_isaac_scene_index(tmp_path, scene_bindings)

    with pytest.raises(AssertionError):
        checker._assert_isaac_runtime(
            data,
            tmp_path,
            _isaac_report_text(scene_bindings, semantic_pose_state=semantic_pose_state),
            require_real_runtime=False,
            require_scene_loaded=False,
            require_selected_usd_bindings=True,
            require_semantic_pose=True,
            require_robot_view_provenance=False,
            require_segmentation_evidence=False,
            require_snapshot_provenance=False,
        )


def test_checker_rejects_isaac_semantic_pose_when_report_omits_pose_rows(
    tmp_path: Path,
) -> None:
    checker = cleanup_checker
    scene_bindings = _isaac_selected_scene_bindings()
    semantic_pose_state = _isaac_semantic_pose_state()
    data = _isaac_runtime_result(
        tmp_path,
        scene_bindings,
        semantic_pose_state=semantic_pose_state,
    )
    _write_isaac_scene_index(tmp_path, scene_bindings)

    with pytest.raises(AssertionError):
        checker._assert_isaac_runtime(
            data,
            tmp_path,
            _isaac_report_text(
                scene_bindings,
                semantic_pose_state=semantic_pose_state,
                include_semantic_pose_rows=False,
            ),
            require_real_runtime=False,
            require_scene_loaded=False,
            require_selected_usd_bindings=True,
            require_semantic_pose=True,
            require_robot_view_provenance=False,
            require_segmentation_evidence=False,
            require_snapshot_provenance=False,
        )


def test_checker_rejects_isaac_semantic_pose_when_trace_omits_provenance(
    tmp_path: Path,
) -> None:
    checker = cleanup_checker
    scene_bindings = _isaac_selected_scene_bindings()
    semantic_pose_state = _isaac_semantic_pose_state()
    data = _isaac_runtime_result(
        tmp_path,
        scene_bindings,
        semantic_pose_state=semantic_pose_state,
    )
    _write_isaac_scene_index(tmp_path, scene_bindings)
    _write_trace(
        tmp_path / "trace.jsonl",
        _isaac_semantic_pose_trace_events(semantic_pose_state, include_provenance=False),
    )

    with pytest.raises(AssertionError):
        checker._assert_isaac_runtime(
            data,
            tmp_path,
            _isaac_report_text(scene_bindings, semantic_pose_state=semantic_pose_state),
            require_real_runtime=False,
            require_scene_loaded=False,
            require_selected_usd_bindings=True,
            require_semantic_pose=True,
            require_robot_view_provenance=False,
            require_segmentation_evidence=False,
            require_snapshot_provenance=False,
        )


def test_waypoint_honesty_allows_public_state_query_before_post_place_observe() -> None:
    checker = cleanup_checker

    count = post_place_observe_count_allowing_public_state_queries(
        {
            "events": [
                {"tool": "place", "role": "cleanup_action"},
                {"tool": "metric_map", "role": "setup_or_completion"},
                {"tool": "observe", "role": "coverage_scan_observe"},
            ]
        }
    )

    assert count == 1


def test_checker_accepts_waypoint_honesty_when_loop_is_survey_first(
    tmp_path: Path,
) -> None:
    demo = _load_module(DEMO_PATH, "molmospaces_realworld_cleanup")
    checker = cleanup_checker

    result = demo.run_household_world_episode(output_dir=tmp_path, seed=7)
    result["cleanup_policy_trace"]["loop_style"] = "survey_first_cleanup_loop"
    result["cleanup_policy_trace"]["first_cleanup_before_full_survey"] = False

    checker.validate_run_result(
        result,
        tmp_path,
        expect_task=None,
        expect_backend="api_semantic_synthetic",
        min_generated_mess_count=5,
        require_waypoint_honesty=True,
    )


def test_checker_rejects_real_robot_alignment_when_chase_is_policy_input(
    tmp_path: Path,
) -> None:
    demo = _load_module(DEMO_PATH, "molmospaces_realworld_cleanup")
    checker = cleanup_checker

    result = demo.run_household_world_episode(output_dir=tmp_path, seed=7)
    result["agent_view"]["policy_view"]["chase_camera_policy_input"] = True
    result["real_robot_readiness"]["policy_view_chase_excluded"] = False

    with pytest.raises(AssertionError):
        checker.validate_run_result(
            result,
            tmp_path,
            expect_task=None,
            expect_backend="api_semantic_synthetic",
            min_generated_mess_count=5,
            require_real_robot_alignment=True,
        )


def test_checker_accepts_b1_robot_consumption_proof_without_rby1m_readiness(
    tmp_path: Path,
) -> None:
    checker = cleanup_checker
    run_result = _b1_robot_consumption_run_result(tmp_path, verified=True)

    checker._assert_b1_robot_consumption_proof(run_result, tmp_path)
    with pytest.raises(AssertionError):
        checker._assert_real_robot_alignment(run_result, tmp_path, "Nav2 Map Bundle")


def test_checker_rejects_b1_robot_consumption_without_verified_navigation(
    tmp_path: Path,
) -> None:
    checker = cleanup_checker
    run_result = _b1_robot_consumption_run_result(tmp_path, verified=False)

    with pytest.raises(AssertionError):
        checker._assert_b1_robot_consumption_proof(run_result, tmp_path)


def test_checker_rejects_b1_robot_consumption_without_manifest(
    tmp_path: Path,
) -> None:
    checker = cleanup_checker
    run_result = _b1_robot_consumption_run_result(tmp_path, verified=True)
    (tmp_path / "b1_robot_consumption_manifest.json").unlink()

    with pytest.raises(
        FileNotFoundError,
        match=(
            r"B1 robot consumption manifest source is missing: "
            r".*b1_robot_consumption_manifest\.json"
        ),
    ):
        checker._assert_b1_robot_consumption_proof(run_result, tmp_path)


def test_checker_rejects_b1_robot_consumption_manifest_drift(
    tmp_path: Path,
) -> None:
    checker = cleanup_checker
    run_result = _b1_robot_consumption_run_result(tmp_path, verified=True)
    manifest_path = tmp_path / "b1_robot_consumption_manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["navigation"]["navigation_artifact"] = "wrong.json"
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")

    with pytest.raises(AssertionError):
        checker._assert_b1_robot_consumption_proof(run_result, tmp_path)


def test_checker_rejects_too_small_generated_mess_set(tmp_path: Path) -> None:
    demo = _load_module(DEMO_PATH, "molmospaces_realworld_cleanup")
    checker = cleanup_checker

    result = demo.run_household_world_episode(output_dir=tmp_path, seed=7)

    with pytest.raises(AssertionError):
        checker.validate_run_result(
            result,
            tmp_path,
            expect_task=None,
            expect_backend="api_semantic_synthetic",
            min_generated_mess_count=6,
        )


def test_checker_accepts_realworld_mcp_smoke_policy(tmp_path: Path) -> None:
    smoke = _load_module(SMOKE_PATH, "run_molmo_realworld_agent_mcp_smoke")
    checker = cleanup_checker

    result = smoke.run_smoke(output_dir=tmp_path, seed=7)

    checker.validate_run_result(
        result,
        tmp_path,
        expect_task=None,
        expect_backend="api_semantic_synthetic",
        expect_policy="household_contract_smoke_agent",
        expect_mcp_server="household_world",
        min_generated_mess_count=5,
        require_agent_driven=True,
        require_clean_agent_run=True,
        min_semantic_accepted_count=4,
    )


def test_checker_rejects_agent_driven_run_without_public_tool_use(tmp_path: Path) -> None:
    smoke = _load_module(SMOKE_PATH, "run_molmo_realworld_agent_mcp_smoke")
    checker = cleanup_checker

    result = smoke.run_smoke(output_dir=tmp_path, seed=7)
    result["tool_event_counts"] = {}

    with pytest.raises(AssertionError):
        checker.validate_run_result(
            result,
            tmp_path,
            expect_task=None,
            expect_backend="api_semantic_synthetic",
            expect_policy="household_contract_smoke_agent",
            expect_mcp_server="household_world",
            min_generated_mess_count=5,
            require_agent_driven=True,
        )


def test_checker_rejects_scene_objects_in_realworld_trace(tmp_path: Path) -> None:
    smoke = _load_module(SMOKE_PATH, "run_molmo_realworld_agent_mcp_smoke")
    checker = cleanup_checker

    result = smoke.run_smoke(output_dir=tmp_path, seed=7)
    trace_path = tmp_path / "trace.jsonl"
    with trace_path.open("a", encoding="utf-8") as fp:
        fp.write('{"tool": "scene_objects", "event": "request"}\n')

    with pytest.raises(AssertionError):
        checker.validate_run_result(
            result,
            tmp_path,
            expect_task=None,
            expect_backend="api_semantic_synthetic",
            expect_policy="household_contract_smoke_agent",
            expect_mcp_server="household_world",
            min_generated_mess_count=5,
            require_agent_driven=True,
            require_clean_agent_run=True,
        )


def test_checker_rejects_clean_run_with_semantic_order_errors(tmp_path: Path) -> None:
    smoke = _load_module(SMOKE_PATH, "run_molmo_realworld_agent_mcp_smoke")
    checker = cleanup_checker

    result = smoke.run_smoke(output_dir=tmp_path, seed=7)
    result["agent_diagnostics"]["semantic_order_errors"] = 1
    result["agent_diagnostics"]["semantic_order_unrecovered_errors"] = 1

    with pytest.raises(AssertionError):
        checker.validate_run_result(
            result,
            tmp_path,
            expect_task=None,
            expect_backend="api_semantic_synthetic",
            expect_policy="household_contract_smoke_agent",
            expect_mcp_server="household_world",
            min_generated_mess_count=5,
            require_agent_driven=True,
            require_clean_agent_run=True,
        )


def test_checker_accepts_clean_run_with_recovered_semantic_order_error(
    tmp_path: Path,
) -> None:
    smoke = _load_module(SMOKE_PATH, "run_molmo_realworld_agent_mcp_smoke")
    checker = cleanup_checker

    result = smoke.run_smoke(output_dir=tmp_path, seed=7)
    retried_item = result["semantic_substeps"][0]
    placement_index = next(
        index
        for index, step in enumerate(retried_item["steps"])
        if step.get("phase") in {"place", "place_inside"} and step.get("ok") is True
    )
    recovered_tool = retried_item["steps"][placement_index]["phase"]
    failed_placement = dict(retried_item["steps"][placement_index])
    failed_placement.update(
        {
            "ok": False,
            "status": "error",
            "error_reason": "semantic_order",
            "required_tool": recovered_tool,
            "primitive_provenance": None,
            "location_id": None,
            "contained_in": None,
        }
    )
    retried_item["steps"].insert(placement_index, failed_placement)
    result["agent_diagnostics"]["semantic_order_errors"] = 1
    result["agent_diagnostics"].pop("semantic_order_recovered_errors", None)
    result["agent_diagnostics"].pop("semantic_order_unrecovered_errors", None)

    checker.validate_run_result(
        result,
        tmp_path,
        expect_task=None,
        expect_backend="api_semantic_synthetic",
        expect_policy="household_contract_smoke_agent",
        expect_mcp_server="household_world",
        min_generated_mess_count=5,
        require_agent_driven=True,
        require_clean_agent_run=True,
        min_semantic_accepted_count=4,
    )


def test_checker_accepts_clean_run_with_successful_retry_after_failed_attempt(
    tmp_path: Path,
) -> None:
    smoke = _load_module(SMOKE_PATH, "run_molmo_realworld_agent_mcp_smoke")
    checker = cleanup_checker

    result = smoke.run_smoke(output_dir=tmp_path, seed=7)
    retried_item = result["semantic_substeps"][0]
    pick_index = next(
        index for index, step in enumerate(retried_item["steps"]) if step.get("phase") == "pick"
    )
    failed_pick = dict(retried_item["steps"][pick_index])
    failed_pick.update(
        {
            "ok": False,
            "status": "error",
            "error_reason": "exception",
            "object_id": None,
            "primitive_provenance": None,
        }
    )
    retried_item["steps"].insert(pick_index, failed_pick)
    result["agent_diagnostics"]["complete_semantic_substep_objects"] = (
        int(result["generated_mess_count"]) - 1
    )

    checker.validate_run_result(
        result,
        tmp_path,
        expect_task=None,
        expect_backend="api_semantic_synthetic",
        expect_policy="household_contract_smoke_agent",
        expect_mcp_server="household_world",
        min_generated_mess_count=5,
        require_agent_driven=True,
        require_clean_agent_run=True,
        min_semantic_accepted_count=4,
    )


def test_checker_rejects_clean_run_when_failed_attempt_never_recovers(
    tmp_path: Path,
) -> None:
    smoke = _load_module(SMOKE_PATH, "run_molmo_realworld_agent_mcp_smoke")
    checker = cleanup_checker

    result = smoke.run_smoke(output_dir=tmp_path, seed=7)
    failed_item = result["semantic_substeps"][0]
    pick_step = next(step for step in failed_item["steps"] if step.get("phase") == "pick")
    pick_step.update(
        {
            "ok": False,
            "status": "error",
            "error_reason": "exception",
            "object_id": None,
            "primitive_provenance": None,
        }
    )

    with pytest.raises(AssertionError):
        checker.validate_run_result(
            result,
            tmp_path,
            expect_task=None,
            expect_backend="api_semantic_synthetic",
            expect_policy="household_contract_smoke_agent",
            expect_mcp_server="household_world",
            min_generated_mess_count=5,
            require_agent_driven=True,
            require_clean_agent_run=True,
        )


def test_checker_can_require_advisory_scoring(tmp_path: Path) -> None:
    smoke = _load_module(SMOKE_PATH, "run_molmo_realworld_agent_mcp_smoke")
    checker = cleanup_checker

    result = smoke.run_smoke(output_dir=tmp_path, seed=7)

    checker.validate_run_result(
        result,
        tmp_path,
        expect_task=None,
        expect_backend="api_semantic_synthetic",
        expect_policy="household_contract_smoke_agent",
        expect_mcp_server="household_world",
        min_generated_mess_count=5,
        require_agent_driven=True,
        require_clean_agent_run=True,
        min_semantic_accepted_count=4,
    )
    report_text = (tmp_path / "report.html").read_text(encoding="utf-8")
    assert_advisory_scoring(result, tmp_path, report_text)


def test_checker_can_require_raw_fpv_observation_artifacts(tmp_path: Path) -> None:
    demo = _load_module(DEMO_PATH, "molmospaces_realworld_cleanup")
    checker = cleanup_checker

    result = demo.run_household_world_episode(
        output_dir=tmp_path,
        seed=7,
        perception_mode="raw_fpv_only",
    )
    _add_molmospaces_robot_view_artifacts(result, tmp_path, prefix="raw")
    for item in result["raw_fpv_observations"]:
        item["image_artifacts"] = {"fpv": "robot_views/raw.fpv.png"}
    for item in agent_view_module.raw_fpv_observations(result["agent_view"]):
        item["image_artifacts"] = {"fpv": "robot_views/raw.fpv.png"}
    result["robot_view_steps"] = [
        {
            "action": "before",
            "room_outline_count": 1,
            "views": {
                "fpv": "robot_views/raw.fpv.png",
                "chase": "robot_views/raw.chase.png",
                "topdown": "robot_views/raw.topdown.png",
                "verify": "robot_views/raw.verify.png",
            },
            "focus": {"has_focus": False},
        },
        {
            "action": "observe raw_fpv_001",
            "room_outline_count": 1,
            "views": {
                "fpv": "robot_views/raw.fpv.png",
                "chase": "robot_views/raw.chase.png",
                "topdown": "robot_views/raw.topdown.png",
                "verify": "robot_views/raw.verify.png",
            },
            "focus": {"has_focus": False},
        },
    ]

    checker.validate_run_result(
        result,
        tmp_path,
        expect_task=None,
        expect_backend="api_semantic_synthetic",
        min_generated_mess_count=5,
        require_robot_views=True,
        require_raw_fpv_observations=True,
    )
