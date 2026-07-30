# ruff: noqa: F403, F405
from tests.support.cleanup_checker_planner import *


def test_checker_rejects_stale_prebuilt_map_bundle_for_isaac_scene_index(
    tmp_path: Path,
) -> None:
    checker = cleanup_checker
    scene_bindings = _isaac_selected_scene_bindings()
    data = _isaac_runtime_result(tmp_path, scene_bindings)
    _write_isaac_scene_index(tmp_path, scene_bindings)
    _add_isaac_scene_index_map_context(data, tmp_path)
    base_metric_map = agent_view_module.base_metric_map(data["agent_view"])
    stale_bundle = {
        **base_metric_map["map_bundle"],
        "environment_id": "molmospaces-procthor-val-0-7",
        "map_id": "molmospaces-procthor-val-0-7_base_metric_map",
    }
    base_metric_map["map_bundle"] = stale_bundle
    data["runtime_metric_map"]["static_map"]["map_bundle"] = stale_bundle
    data["nav2_map_bundle"]["environment_id"] = "molmospaces-procthor-val-0-7"
    data["nav2_map_bundle"]["map_id"] = "molmospaces-procthor-val-0-7_base_metric_map"
    data["nav2_map_bundle"]["source_bundle_root"] = "assets/maps/molmospaces-procthor-val-0-7"

    with pytest.raises(AssertionError):
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


def test_checker_accepts_isaac_real_runtime_when_diagnostics_are_present(
    tmp_path: Path,
) -> None:
    checker = cleanup_checker
    scene_bindings = _isaac_selected_scene_bindings()
    data = _isaac_runtime_result(tmp_path, scene_bindings)
    data["isaac_runtime"]["runtime"] = _isaac_real_runtime_diagnostics()

    checker._assert_isaac_runtime(
        data,
        tmp_path,
        _isaac_report_text(scene_bindings),
        require_real_runtime=True,
        require_scene_loaded=False,
        require_selected_usd_bindings=False,
        require_semantic_pose=False,
        require_robot_view_provenance=False,
        require_segmentation_evidence=False,
        require_snapshot_provenance=False,
    )


def test_checker_accepts_isaac_loaded_scene_when_usd_file_is_present(
    tmp_path: Path,
) -> None:
    checker = cleanup_checker
    scene_bindings = _isaac_selected_scene_bindings()
    data = _isaac_runtime_result(tmp_path, scene_bindings)
    _add_isaac_loaded_scene(data, tmp_path)

    checker._assert_isaac_runtime(
        data,
        tmp_path,
        _isaac_report_text(scene_bindings),
        require_real_runtime=False,
        require_scene_loaded=True,
        require_local_scene_usd=True,
        require_selected_usd_bindings=False,
        require_semantic_pose=False,
        require_robot_view_provenance=False,
        require_segmentation_evidence=False,
        require_snapshot_provenance=False,
    )


def test_checker_rejects_isaac_generated_usd_when_local_scene_required(
    tmp_path: Path,
) -> None:
    checker = cleanup_checker
    scene_bindings = _isaac_selected_scene_bindings()
    data = _isaac_runtime_result(tmp_path, scene_bindings)
    _add_isaac_loaded_scene(
        data,
        tmp_path,
        loaded_asset_kind="generated_runtime_smoke_usd",
    )

    with pytest.raises(AssertionError):
        checker._assert_isaac_runtime(
            data,
            tmp_path,
            _isaac_report_text(scene_bindings),
            require_real_runtime=False,
            require_scene_loaded=True,
            require_local_scene_usd=True,
            require_selected_usd_bindings=False,
            require_semantic_pose=False,
            require_robot_view_provenance=False,
            require_segmentation_evidence=False,
            require_snapshot_provenance=False,
        )


def test_checker_rejects_blank_isaac_robot_view_images(
    tmp_path: Path,
) -> None:
    checker = cleanup_checker
    scene_bindings = _isaac_selected_scene_bindings()
    data = _isaac_runtime_result(tmp_path, scene_bindings)
    _add_isaac_robot_view_step(data, tmp_path, blank_key="verify")

    with pytest.raises(AssertionError):
        checker._assert_isaac_runtime(
            data,
            tmp_path,
            _isaac_report_text(scene_bindings),
            require_real_runtime=False,
            require_scene_loaded=False,
            require_local_scene_usd=False,
            require_selected_usd_bindings=False,
            require_semantic_pose=False,
            require_robot_view_provenance=True,
            require_segmentation_evidence=False,
            require_snapshot_provenance=False,
        )


def test_checker_rejects_blank_isaac_snapshot_provenance(
    tmp_path: Path,
) -> None:
    checker = cleanup_checker
    scene_bindings = _isaac_selected_scene_bindings()
    data = _isaac_runtime_result(tmp_path, scene_bindings)
    _add_isaac_snapshot_artifacts(data, tmp_path, blank_output=True)

    with pytest.raises(AssertionError):
        checker._assert_isaac_runtime(
            data,
            tmp_path,
            _isaac_report_text(scene_bindings),
            require_real_runtime=False,
            require_scene_loaded=False,
            require_local_scene_usd=False,
            require_selected_usd_bindings=False,
            require_semantic_pose=False,
            require_robot_view_provenance=False,
            require_segmentation_evidence=False,
            require_snapshot_provenance=True,
        )


def test_checker_rejects_isaac_loaded_scene_when_manual_editor_steps_remain(
    tmp_path: Path,
) -> None:
    checker = cleanup_checker
    scene_bindings = _isaac_selected_scene_bindings()
    data = _isaac_runtime_result(tmp_path, scene_bindings)
    _add_isaac_loaded_scene(data, tmp_path, manual_editor_steps_required=True)

    with pytest.raises(AssertionError):
        checker._assert_isaac_runtime(
            data,
            tmp_path,
            _isaac_report_text(scene_bindings),
            require_real_runtime=False,
            require_scene_loaded=True,
            require_local_scene_usd=False,
            require_selected_usd_bindings=False,
            require_semantic_pose=False,
            require_robot_view_provenance=False,
            require_segmentation_evidence=False,
            require_snapshot_provenance=False,
        )


def test_checker_rejects_isaac_real_runtime_when_diagnostics_are_missing(
    tmp_path: Path,
) -> None:
    checker = cleanup_checker
    scene_bindings = _isaac_selected_scene_bindings()
    data = _isaac_runtime_result(tmp_path, scene_bindings)
    data["isaac_runtime"]["runtime"] = {
        "runtime_mode": "real",
        "primitive_provenance": "isaac_semantic_pose",
        "rendering": {
            "status": "real_rendering_proven",
            "real_rendering_proven": True,
            "placeholder_visuals": False,
        },
    }

    with pytest.raises(AssertionError):
        checker._assert_isaac_runtime(
            data,
            tmp_path,
            _isaac_report_text(scene_bindings),
            require_real_runtime=True,
            require_scene_loaded=False,
            require_selected_usd_bindings=False,
            require_semantic_pose=False,
            require_robot_view_provenance=False,
            require_segmentation_evidence=False,
            require_snapshot_provenance=False,
        )


def test_checker_rejects_isaac_selected_binding_rows_without_usd_handle(
    tmp_path: Path,
) -> None:
    checker = cleanup_checker
    scene_bindings = _isaac_selected_scene_bindings()
    scene_bindings["selected_object_bindings"]["mug_01"].pop("usd_handle")
    data = _isaac_runtime_result(tmp_path, scene_bindings)
    _write_isaac_scene_index(tmp_path, scene_bindings)

    with pytest.raises(AssertionError):
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


def test_checker_rejects_isaac_selected_binding_index_mismatch(
    tmp_path: Path,
) -> None:
    checker = cleanup_checker
    scene_bindings = _isaac_selected_scene_bindings()
    data = _isaac_runtime_result(tmp_path, scene_bindings)
    _write_isaac_scene_index(
        tmp_path,
        scene_bindings,
        object_prim_path="/World/Objects/other_mug",
    )

    with pytest.raises(AssertionError):
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


@pytest.mark.parametrize(
    ("source", "message"),
    [
        (
            "{not-json\n",
            r"valid JSON object: .*isaac_scene_index\.json",
        ),
        (
            "[]\n",
            r"source must contain a JSON object: .*isaac_scene_index\.json",
        ),
    ],
)
def test_checker_rejects_bad_isaac_scene_index_artifact_source(
    tmp_path: Path,
    source: str,
    message: str,
) -> None:
    checker = cleanup_checker
    scene_bindings = _isaac_selected_scene_bindings()
    data = _isaac_runtime_result(tmp_path, scene_bindings)
    (tmp_path / "isaac_scene_index.json").write_text(source, encoding="utf-8")

    with pytest.raises(AssertionError, match=message):
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


def test_checker_rejects_missing_isaac_scene_index_artifact_source(tmp_path: Path) -> None:
    checker = cleanup_checker
    scene_bindings = _isaac_selected_scene_bindings()
    data = _isaac_runtime_result(tmp_path, scene_bindings)

    with pytest.raises(
        AssertionError,
        match=r"Isaac scene-index artifact source is missing: .*isaac_scene_index\.json",
    ):
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


def test_checker_rejects_isaac_scene_index_binding_drift_from_run_result(
    tmp_path: Path,
) -> None:
    checker = cleanup_checker
    scene_bindings = _isaac_selected_scene_bindings()
    artifact_scene_bindings = json.loads(json.dumps(scene_bindings))
    artifact_scene_bindings["selected_object_bindings"]["mug_01"]["usd_prim_path"] = (
        "/World/Objects/other_mug"
    )
    data = _isaac_runtime_result(tmp_path, scene_bindings)
    _write_isaac_scene_index(
        tmp_path,
        scene_bindings,
        artifact_scene_bindings=artifact_scene_bindings,
        object_prim_path="/World/Objects/other_mug",
    )

    with pytest.raises(AssertionError):
        checker._assert_isaac_runtime(
            data,
            tmp_path,
            _isaac_report_text(artifact_scene_bindings),
            require_real_runtime=False,
            require_scene_loaded=False,
            require_selected_usd_bindings=True,
            require_semantic_pose=False,
            require_robot_view_provenance=False,
            require_segmentation_evidence=False,
            require_snapshot_provenance=False,
        )


def test_checker_rejects_isaac_scene_index_object_index_drift_from_run_result(
    tmp_path: Path,
) -> None:
    checker = cleanup_checker
    scene_bindings = _isaac_selected_scene_bindings()
    data = _isaac_runtime_result(tmp_path, scene_bindings)
    isaac_runtime = data["isaac_runtime"]
    assert isinstance(isaac_runtime, dict)
    object_index = isaac_runtime["object_index"]
    assert isinstance(object_index, dict)
    object_index["book_01"] = {"usd_prim_path": "/World/Objects/book_01"}
    isaac_runtime["object_index_count"] = 2
    _write_isaac_scene_index(
        tmp_path,
        scene_bindings,
        extra_object_index={"book_01": {"usd_prim_path": "/World/Objects/book_renamed"}},
    )

    with pytest.raises(AssertionError):
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


def test_checker_rejects_isaac_scene_index_segmentation_drift_from_run_result(
    tmp_path: Path,
) -> None:
    checker = cleanup_checker
    scene_bindings = _isaac_selected_scene_bindings()
    runtime_segmentation = _isaac_available_segmentation()
    artifact_segmentation = json.loads(json.dumps(runtime_segmentation))
    artifact_segmentation["candidate_bbox_count"] = 2
    data = _isaac_runtime_result(
        tmp_path,
        scene_bindings,
        segmentation=runtime_segmentation,
    )
    _write_isaac_scene_index(
        tmp_path,
        scene_bindings,
        segmentation=artifact_segmentation,
    )

    with pytest.raises(AssertionError):
        checker._assert_isaac_runtime(
            data,
            tmp_path,
            _isaac_report_text(scene_bindings),
            require_real_runtime=False,
            require_scene_loaded=False,
            require_selected_usd_bindings=True,
            require_semantic_pose=False,
            require_robot_view_provenance=False,
            require_segmentation_evidence=True,
            require_snapshot_provenance=False,
        )


def test_checker_accepts_isaac_semantic_pose_paths_when_rows_match_scene_index(
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


def test_checker_accepts_isaac_semantic_pose_rerendered_robot_views(
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
    _add_isaac_robot_view_step(
        data,
        tmp_path,
        capture_method="isaac_lab_camera_rgb_semantic_pose_robot_views",
        semantic_pose_state_refreshed=True,
    )

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


def test_checker_accepts_isaac_head_camera_equivalent_robot_view(
    tmp_path: Path,
) -> None:
    checker = cleanup_checker
    scene_bindings = _isaac_selected_scene_bindings()
    semantic_pose_state = _isaac_semantic_pose_state_with_refreshed_robot_views(
        head_camera_equivalent=True
    )
    data = _isaac_runtime_result(
        tmp_path,
        scene_bindings,
        semantic_pose_state=semantic_pose_state,
    )
    _write_isaac_scene_index(tmp_path, scene_bindings)
    _add_isaac_robot_view_step(
        data,
        tmp_path,
        capture_method="isaac_lab_camera_rgb_semantic_pose_robot_views",
        semantic_pose_state_refreshed=True,
        head_camera_equivalent=True,
    )

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


def test_checker_accepts_isaac_mounted_head_camera_robot_view(
    tmp_path: Path,
) -> None:
    checker = cleanup_checker
    scene_bindings = _isaac_selected_scene_bindings()
    semantic_pose_state = _isaac_semantic_pose_state_with_refreshed_robot_views(
        mounted_head_camera=True
    )
    data = _isaac_runtime_result(
        tmp_path,
        scene_bindings,
        semantic_pose_state=semantic_pose_state,
    )
    _write_isaac_scene_index(tmp_path, scene_bindings)
    _add_isaac_robot_view_step(
        data,
        tmp_path,
        capture_method="isaac_lab_camera_rgb_semantic_pose_robot_views",
        semantic_pose_state_refreshed=True,
        mounted_head_camera=True,
    )

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


def test_checker_requires_robot_head_camera_fpv(
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
    data["view_variant"] = MOLMOSPACES_ROBOT_VIEW_VARIANT

    checker.validate_run_result(
        data,
        tmp_path,
        expect_task=None,
        expect_backend="api_semantic_synthetic",
        min_generated_mess_count=0,
        allow_partial_cleanup=True,
        require_robot_head_camera_fpv=True,
    )


def test_checker_rejects_backend_local_robot_view_when_head_camera_required(
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
        canonical_camera_control=False,
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
