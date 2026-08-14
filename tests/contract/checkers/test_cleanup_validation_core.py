# ruff: noqa: F403, F405, F841
from tests.support.cleanup_checker_planner import *


def test_checker_parses_robot_head_camera_fpv_flag(monkeypatch: pytest.MonkeyPatch) -> None:
    checker = cleanup_checker
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "check_molmo_realworld_cleanup_result.py",
            "run_result.json",
            "--require-robot-head-camera-fpv",
        ],
    )

    args = cleanup_validation_args.parse_args()

    assert args.require_robot_head_camera_fpv is True


def test_checker_rejects_legacy_canonical_robot_view_camera_control_flag(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    checker = cleanup_checker

    monkeypatch.setattr(
        sys,
        "argv",
        [
            "check_molmo_realworld_cleanup_result.py",
            "run_result.json",
            "--require-canonical-robot-view-camera-control",
        ],
    )

    with pytest.raises(SystemExit) as exc_info:
        cleanup_validation_args.parse_args()

    assert exc_info.value.code == 2
    stderr = capsys.readouterr().err
    assert "--require-canonical-robot-view-camera-control is obsolete" in stderr
    assert "use --require-robot-head-camera-fpv" in stderr


def test_checker_rejects_legacy_canonical_robot_view_camera_control_override() -> None:
    checker = cleanup_checker

    with pytest.raises(ValueError, match="use require_robot_head_camera_fpv"):
        checker._result_assert_options({"require_canonical_robot_view_camera_control": True})


def test_checker_accepts_single_realworld_run(tmp_path: Path) -> None:
    demo = _load_module(DEMO_PATH, "molmospaces_realworld_cleanup")
    checker = cleanup_checker

    demo.run_household_world_episode(output_dir=tmp_path, seed=7)

    data, path = checker.load_run_results(tmp_path / "run_result.json")[0]
    checker.validate_run_result(
        data,
        path.parent,
        expect_task=None,
        expect_backend="api_semantic_synthetic",
        min_generated_mess_count=5,
    )


def test_checker_can_require_runtime_metric_map(tmp_path: Path) -> None:
    demo = _load_module(DEMO_PATH, "molmospaces_realworld_cleanup")
    checker = cleanup_checker

    result = demo.run_household_world_episode(output_dir=tmp_path, seed=7)

    checker.validate_run_result(
        result,
        tmp_path,
        expect_task=None,
        expect_backend="api_semantic_synthetic",
        min_generated_mess_count=5,
        require_runtime_metric_map=True,
    )
    runtime_map = json.loads((tmp_path / "runtime_metric_map.json").read_text())
    assert runtime_map["schema"] == checker.RUNTIME_METRIC_MAP_SCHEMA
    assert runtime_map["target_candidates"]
    assert runtime_map["target_search_summary"]["schema"] == "target_search_summary_v1"
    assert (tmp_path / "runtime_metric_map_preview.png").is_file()
    assert result["artifacts"]["runtime_metric_map_preview"].endswith(
        "runtime_metric_map_preview.png"
    )
    assert "Runtime Metric Map" in (tmp_path / "report.html").read_text()
    assert "Runtime Metric Map preview" in (tmp_path / "report.html").read_text()
    assert "Target Candidates" in (tmp_path / "report.html").read_text()


def test_checker_rejects_duplicate_current_run_fixture_anchor_viewpoints(tmp_path: Path) -> None:
    demo = _load_module(DEMO_PATH, "molmospaces_realworld_cleanup")
    checker = cleanup_checker

    result = demo.run_household_world_episode(output_dir=tmp_path, seed=7)
    runtime_map = result["runtime_metric_map"]
    anchor = next(
        item
        for item in runtime_map["public_semantic_anchors"]
        if item["anchor_type"] in {"fixture", "surface", "receptacle"}
    )
    duplicate = {**anchor, "anchor_id": f"{anchor['anchor_id']}_duplicate"}
    runtime_map["public_semantic_anchors"].append(duplicate)
    result["agent_view"]["runtime_metric_map"] = runtime_map

    with pytest.raises(AssertionError, match="duplicate_fixture_anchor_viewpoints"):
        checker.validate_run_result(
            result,
            tmp_path,
            expect_task=None,
            expect_backend="api_semantic_synthetic",
            min_generated_mess_count=5,
            require_runtime_metric_map=True,
        )


def test_checker_rejects_rgb_only_runtime_map_object_pose(tmp_path: Path) -> None:
    demo = _load_module(DEMO_PATH, "molmospaces_realworld_cleanup")
    checker = cleanup_checker

    result = demo.run_household_world_episode(
        output_dir=tmp_path,
        seed=7,
        perception_mode=CAMERA_MODEL_POLICY_MODE,
    )
    observed = result["runtime_metric_map"]["observed_objects"][0]
    observed["object_pose"] = {"x": 1.0, "y": 2.0, "yaw": 0.0}
    result["agent_view"]["runtime_metric_map"] = result["runtime_metric_map"]

    with pytest.raises(AssertionError, match="RGB-only current-run map evidence"):
        checker.validate_run_result(
            result,
            tmp_path,
            expect_task=None,
            expect_backend="api_semantic_synthetic",
            expect_policy="camera_model_policy_baseline",
            min_generated_mess_count=5,
            require_runtime_metric_map=True,
        )


def test_checker_can_require_map_build_mode(tmp_path: Path) -> None:
    demo = _load_module(DEMO_PATH, "molmospaces_realworld_cleanup")
    checker = cleanup_checker

    result = demo.run_household_world_episode(
        output_dir=tmp_path,
        seed=7,
        intent="map-build",
        perception_mode=CAMERA_MODEL_POLICY_MODE,
    )

    checker.validate_run_result(
        result,
        tmp_path,
        expect_task=None,
        expect_backend="api_semantic_synthetic",
        min_generated_mess_count=5,
        require_runtime_metric_map=True,
        require_map_build=True,
        require_camera_model_policy=True,
    )
    counts = result["tool_event_counts"]
    assert result["map_build"]["scan_profile_id"] == "fixture-focused"
    assert result["map_build"]["uses_robot_body_turns"] is True
    assert counts["navigate_to_relative_pose:request"] >= 1
    assert counts.get("pick:request") is None
    assert result["runtime_metric_map"]["observed_objects"]


def test_checker_adaptive_adjust_camera_threshold_is_opt_in(tmp_path: Path) -> None:
    demo = _load_module(DEMO_PATH, "molmospaces_realworld_cleanup")
    checker = cleanup_checker

    result = demo.run_household_world_episode(
        output_dir=tmp_path,
        seed=7,
        intent="map-build",
        perception_mode=CAMERA_MODEL_POLICY_MODE,
    )
    result["tool_event_counts"]["adjust_camera:request"] = 0

    checker.validate_run_result(
        result,
        tmp_path,
        expect_task=None,
        expect_backend="api_semantic_synthetic",
        min_generated_mess_count=5,
        require_runtime_metric_map=True,
        require_map_build=True,
        require_camera_model_policy=True,
    )
    with pytest.raises(AssertionError):
        checker.validate_run_result(
            result,
            tmp_path,
            expect_task=None,
            expect_backend="api_semantic_synthetic",
            min_generated_mess_count=5,
            require_runtime_metric_map=True,
            require_map_build=True,
            require_camera_model_policy=True,
            min_adjust_camera_count=1,
        )


def test_checker_can_require_generated_target_inspection_candidates(tmp_path: Path) -> None:
    demo = _load_module(DEMO_PATH, "molmospaces_realworld_cleanup")
    checker = cleanup_checker

    result = demo.run_household_world_episode(
        output_dir=tmp_path,
        seed=7,
        intent="map-build",
        perception_mode=CAMERA_MODEL_POLICY_MODE,
    )
    result["runtime_metric_map"]["generated_target_inspection_candidates"] = []
    result["agent_view"]["runtime_metric_map"] = result["runtime_metric_map"]

    checker.validate_run_result(
        result,
        tmp_path,
        expect_task=None,
        expect_backend="api_semantic_synthetic",
        min_generated_mess_count=5,
        require_runtime_metric_map=True,
        require_map_build=True,
        require_camera_model_policy=True,
    )
    with pytest.raises(AssertionError):
        checker.validate_run_result(
            result,
            tmp_path,
            expect_task=None,
            expect_backend="api_semantic_synthetic",
            min_generated_mess_count=5,
            require_runtime_metric_map=True,
            require_map_build=True,
            require_camera_model_policy=True,
            min_generated_target_inspection_candidates=1,
        )


def test_checker_allows_camera_model_policy_map_build_with_no_object_detections(
    tmp_path: Path,
) -> None:
    demo = _load_module(DEMO_PATH, "molmospaces_realworld_cleanup")
    checker = cleanup_checker

    result = demo.run_household_world_episode(
        output_dir=tmp_path,
        seed=7,
        intent="map-build",
        perception_mode=CAMERA_MODEL_POLICY_MODE,
    )
    result["observed_objects"] = []
    result["model_declared_observations"] = []
    result["runtime_metric_map"]["observed_objects"] = []
    active_perception = agent_view_module.active_perception(result["agent_view"])
    active_perception["observed_objects"] = []
    active_perception["model_declared_observations"] = []
    agent_view_module.runtime_metric_map(result["agent_view"])["observed_objects"] = []
    evidence = result["camera_model_policy_evidence"]
    evidence["candidate_count"] = 0
    for event in evidence["events"]:
        event["candidate_count"] = 0
        event["registered_observed_handles"] = []
        pipeline = event.get("visual_grounding_pipeline") or {}
        pipeline["candidate_count"] = 0
    active_perception["camera_model_policy_evidence"] = evidence

    checker.validate_run_result(
        result,
        tmp_path,
        expect_task=None,
        expect_backend="api_semantic_synthetic",
        min_generated_mess_count=5,
        require_runtime_metric_map=True,
        require_map_build=True,
        require_camera_model_policy=True,
        require_base_metric_map=True,
    )
    assert result["runtime_metric_map"]["target_candidates"]


def test_checker_accepts_agibot_map_build_artifact(tmp_path: Path) -> None:
    checker = cleanup_checker
    run_dir = _write_agibot_map_build_fixture(tmp_path)

    data, path = checker.load_run_results(run_dir / "run_result.json")[0]
    checker.validate_run_result(
        data,
        path.parent,
        expect_task=None,
        expect_backend="agibot_sdk_runner",
        expect_policy="household_contract_smoke_agent",
        expect_mcp_server="household_world",
        min_generated_mess_count=0,
        require_agent_driven=True,
        require_camera_model_policy=True,
        require_runtime_metric_map=True,
        require_map_build=True,
        expect_visual_grounding_pipeline="grounding-dino",
        require_visual_grounding_failure=True,
        min_sweep_coverage=1.0,
    )


def test_checker_rejects_agibot_rehearsal_as_hardware_validation(
    tmp_path: Path,
) -> None:
    checker = cleanup_checker
    run_dir = _write_agibot_map_build_fixture(tmp_path)

    data, path = checker.load_run_results(run_dir / "run_result.json")[0]
    with pytest.raises(AssertionError):
        checker.validate_run_result(
            data,
            path.parent,
            expect_task=None,
            expect_backend="agibot_sdk_runner",
            expect_policy="household_contract_smoke_agent",
            expect_mcp_server="household_world",
            min_generated_mess_count=0,
            require_agent_driven=True,
            require_camera_model_policy=True,
            require_runtime_metric_map=True,
            require_map_build=True,
            require_agibot_g2_hardware=True,
            expect_visual_grounding_pipeline="grounding-dino",
            min_sweep_coverage=1.0,
        )


def test_checker_accepts_agibot_hardware_map_build_shape(
    tmp_path: Path,
) -> None:
    checker = cleanup_checker
    run_dir = _write_agibot_map_build_fixture(tmp_path)
    data, path = checker.load_run_results(run_dir / "run_result.json")[0]
    _promote_agibot_fixture_to_hardware_shape(data, run_dir)

    checker.validate_run_result(
        data,
        path.parent,
        expect_task=None,
        expect_backend="agibot_sdk_runner",
        expect_policy="household_contract_smoke_agent",
        expect_mcp_server="household_world",
        min_generated_mess_count=0,
        require_agent_driven=True,
        require_camera_model_policy=True,
        require_runtime_metric_map=True,
        require_map_build=True,
        require_agibot_g2_hardware=True,
        expect_visual_grounding_pipeline="grounding-dino",
        min_sweep_coverage=1.0,
    )


def test_checker_rejects_sim_visual_grounding_as_agibot_hardware_evidence(
    tmp_path: Path,
) -> None:
    checker = cleanup_checker
    run_dir = _write_agibot_map_build_fixture(tmp_path)
    data, path = checker.load_run_results(run_dir / "run_result.json")[0]
    _promote_agibot_fixture_to_hardware_shape(data, run_dir)

    camera_policy = data["camera_model_policy_evidence"]
    assert isinstance(camera_policy, dict)
    camera_policy["visual_grounding_pipeline_id"] = "sim"
    camera_policy["visual_grounding_pipeline_ids"] = ["sim"]
    for event in camera_policy["events"]:
        assert isinstance(event, dict)
        pipeline = event["visual_grounding_pipeline"]
        assert isinstance(pipeline, dict)
        pipeline["pipeline_id"] = "sim"
    agent_view = data["agent_view"]
    assert isinstance(agent_view, dict)
    agent_view_module.active_perception(agent_view)["camera_model_policy_evidence"] = camera_policy

    with pytest.raises(AssertionError):
        checker.validate_run_result(
            data,
            path.parent,
            expect_task=None,
            expect_backend="agibot_sdk_runner",
            expect_policy="household_contract_smoke_agent",
            expect_mcp_server="household_world",
            min_generated_mess_count=0,
            require_agent_driven=True,
            require_camera_model_policy=True,
            require_runtime_metric_map=True,
            require_map_build=True,
            require_agibot_g2_hardware=True,
            min_sweep_coverage=1.0,
        )


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("agent_driven", False),
        ("mcp_server", "other"),
        ("evidence_lane", "world-oracle-labels"),
        ("perception_mode", "visible_object_detections"),
    ],
)
def test_checker_rejects_non_codex_camera_labels_shape_as_agibot_hardware(
    tmp_path: Path,
    field: str,
    value: object,
) -> None:
    checker = cleanup_checker
    run_dir = _write_agibot_map_build_fixture(tmp_path)
    data, path = checker.load_run_results(run_dir / "run_result.json")[0]
    _promote_agibot_fixture_to_hardware_shape(data, run_dir)
    data[field] = value

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
