# ruff: noqa: F403, F405
from tests.support.cleanup_checker_planner import *


def test_checker_rejects_raw_fpv_when_structured_detections_leak(tmp_path: Path) -> None:
    demo = _load_module(DEMO_PATH, "molmospaces_realworld_cleanup")
    checker = cleanup_checker

    result = demo.run_household_world_episode(
        output_dir=tmp_path,
        seed=7,
        perception_mode="raw_fpv_only",
    )
    robot_views = tmp_path / "robot_views"
    robot_views.mkdir()
    fpv = robot_views / "raw.fpv.png"
    fpv.write_bytes(b"placeholder")
    result["artifacts"]["robot_views"] = str(robot_views)
    result["raw_fpv_observations"][0]["image_artifacts"] = {"fpv": "robot_views/raw.fpv.png"}
    result["raw_fpv_observations"][0]["support_estimate"] = {"fixture_id": "sink_01"}
    result["agent_view"]["raw_fpv_observations"] = result["raw_fpv_observations"]

    with pytest.raises(AssertionError):
        checker.validate_run_result(
            result,
            tmp_path,
            expect_task=None,
            expect_backend="api_semantic_synthetic",
            min_generated_mess_count=5,
            require_raw_fpv_observations=True,
        )


def test_checker_can_require_camera_model_policy(tmp_path: Path) -> None:
    demo = _load_module(DEMO_PATH, "molmospaces_realworld_cleanup")
    checker = cleanup_checker

    result = demo.run_household_world_episode(
        output_dir=tmp_path,
        seed=7,
        perception_mode=CAMERA_MODEL_POLICY_MODE,
    )

    checker.validate_run_result(
        result,
        tmp_path,
        expect_task=None,
        expect_backend="api_semantic_synthetic",
        expect_policy="camera_model_policy_baseline",
        min_generated_mess_count=5,
        require_camera_model_policy=True,
        accept_blocked_planner_cleanup_primitives=True,
    )


def test_checker_allows_main_agent_model_declared_camera_policy_retry(tmp_path: Path) -> None:
    checker = cleanup_checker
    raw_fpv = tmp_path / "robot_views" / "raw_fpv_001.jpg"
    raw_fpv.parent.mkdir(parents=True)
    raw_fpv.write_bytes(b"raw-fpv")
    overlay = tmp_path / "visual_grounding" / "overlays" / "raw_fpv_001" / "candidate_001.jpg"
    overlay.parent.mkdir(parents=True)
    overlay.write_bytes(b"overlay")
    result = _external_visual_grounding_checker_result(
        overlay="visual_grounding/overlays/raw_fpv_001/candidate_001.jpg"
    )
    result["model_declared_observations"][0]["perception_source"] = "model_declared_observation"
    main_agent_retry = dict(result["model_declared_observations"][0])
    main_agent_retry.update(
        {
            "object_id": "observed_002",
            "producer_type": "main_cleanup_agent",
            "producer_id": "cleanup_agent",
            "model_provenance": None,
            "support_estimate": None,
            "grounding_status": "unresolved",
            "grounding_confidence": 0.05,
            "grounding_basis": "no public camera-context object matched",
            "recovery_hint": "Reobserve from another waypoint.",
        }
    )
    main_agent_retry.pop("visual_grounding_overlay", None)
    main_agent_retry.pop("visual_grounding_pipeline", None)
    manual_event = dict(result["camera_model_policy_evidence"]["events"][0])
    manual_event.update(
        {
            "producer_type": "main_cleanup_agent",
            "producer_id": "cleanup_agent",
            "registered_observed_handles": ["observed_002"],
            "visual_grounding_pipeline": {
                "schema": "visual_grounding_pipeline_v1",
                "pipeline_id": "manual",
                "status": "ok",
                "candidate_count": 1,
                "unresolved_count": 0,
                "duplicate_rate": 0.0,
                "stages": [
                    {
                        "stage": "manual_declaration",
                        "producer_id": "cleanup_agent",
                        "model_id": "main_cleanup_agent",
                        "status": "ok",
                        "latency_ms": 0,
                    }
                ],
            },
        }
    )
    result["camera_model_policy_evidence"]["visual_grounding_pipeline_id"] = "manual"
    result["camera_model_policy_evidence"]["visual_grounding_pipeline_ids"] = [
        "grounding-dino",
        "manual",
    ]
    result["camera_model_policy_evidence"]["events"].append(manual_event)

    checker._assert_public_agent_view(
        _minimal_agent_view(
            perception_mode=CAMERA_MODEL_POLICY_MODE,
            structured_detections_available=False,
            raw_fpv_observations=result["raw_fpv_observations"],
            camera_model_policy_evidence=result["camera_model_policy_evidence"],
            observed_objects=[
                result["model_declared_observations"][0],
                main_agent_retry,
            ],
            model_declared_observations=[
                result["model_declared_observations"][0],
                main_agent_retry,
            ],
            model_declared_observation_evidence={
                **result["model_declared_observation_evidence"],
                "observations": [
                    result["model_declared_observations"][0],
                    main_agent_retry,
                ],
            },
        )
    )
    checker._assert_camera_model_policy(
        result,
        tmp_path,
        "Camera Labeler Evidence Raw FPV Observations grounding-dino manual Overlay",
        expect_pipeline_id="grounding-dino",
    )


def test_checker_allows_camera_grounded_label_lane_public_provenance() -> None:
    checker = cleanup_checker
    result = _external_visual_grounding_checker_result(
        overlay="visual_grounding/overlays/raw_fpv_001/candidate_001.jpg"
    )
    observed = dict(result["model_declared_observations"][0])
    observed.update(
        {
            "producer_type": "camera-grounded-labels",
            "model_provenance": "camera-grounded-labels",
            "perception_source": "model_declared_observation",
            "support_estimate": {
                "source": "public_semantic_anchor",
                "producer_type": "camera-grounded-labels",
                "model_provenance": "camera-grounded-labels",
                "perception_source": "model_declared_observation",
                "source_observation_id": "raw_fpv_001",
            },
        }
    )

    checker._assert_public_agent_view(
        _minimal_agent_view(
            perception_mode=CAMERA_MODEL_POLICY_MODE,
            structured_detections_available=False,
            raw_fpv_observations=result["raw_fpv_observations"],
            camera_model_policy_evidence=result["camera_model_policy_evidence"],
            observed_objects=[observed],
            model_declared_observations=[observed],
            model_declared_observation_evidence={
                **result["model_declared_observation_evidence"],
                "observations": [observed],
            },
        )
    )


def test_checker_requires_external_visual_grounding_bbox_overlay(tmp_path: Path) -> None:
    checker = cleanup_checker
    raw_fpv = tmp_path / "robot_views" / "raw_fpv_001.jpg"
    raw_fpv.parent.mkdir(parents=True)
    raw_fpv.write_bytes(b"raw-fpv")
    overlay = tmp_path / "visual_grounding" / "overlays" / "raw_fpv_001" / "candidate_001.jpg"
    overlay.parent.mkdir(parents=True)
    overlay.write_bytes(b"overlay")
    result = _external_visual_grounding_checker_result(
        overlay="visual_grounding/overlays/raw_fpv_001/candidate_001.jpg"
    )

    checker._assert_camera_model_policy(
        result,
        tmp_path,
        "Camera Labeler Evidence Raw FPV Observations grounding-dino Overlay",
        expect_pipeline_id="grounding-dino",
    )


def test_checker_rejects_external_visual_grounding_bbox_without_overlay(
    tmp_path: Path,
) -> None:
    checker = cleanup_checker
    raw_fpv = tmp_path / "robot_views" / "raw_fpv_001.jpg"
    raw_fpv.parent.mkdir(parents=True)
    raw_fpv.write_bytes(b"raw-fpv")
    result = _external_visual_grounding_checker_result(overlay="")

    with pytest.raises(AssertionError):
        checker._assert_camera_model_policy(
            result,
            tmp_path,
            "Camera Labeler Evidence Raw FPV Observations grounding-dino Overlay",
            expect_pipeline_id="grounding-dino",
        )


def test_checker_rejects_unlabelled_camera_model_candidates(tmp_path: Path) -> None:
    demo = _load_module(DEMO_PATH, "molmospaces_realworld_cleanup")
    checker = cleanup_checker

    result = demo.run_household_world_episode(
        output_dir=tmp_path,
        seed=7,
        perception_mode=CAMERA_MODEL_POLICY_MODE,
    )
    observed_objects = agent_view_module.active_perception(result["agent_view"])["observed_objects"]
    observed_objects[0].pop("model_provenance")
    observed_objects[0].pop("producer_type")

    with pytest.raises(AssertionError):
        checker.validate_run_result(
            result,
            tmp_path,
            expect_task=None,
            expect_backend="api_semantic_synthetic",
            expect_policy="camera_model_policy_baseline",
            min_generated_mess_count=5,
            require_camera_model_policy=True,
        )


def test_checker_can_require_robot_view_report_artifacts(tmp_path: Path) -> None:
    demo = _load_module(DEMO_PATH, "molmospaces_realworld_cleanup")
    checker = cleanup_checker

    result = demo.run_household_world_episode(output_dir=tmp_path, seed=7)
    _add_molmospaces_robot_view_artifacts(result, tmp_path)
    result["robot_view_steps"] = [
        _robot_step("navigate_to_object observed_001"),
        _robot_step("pick observed_001"),
        _robot_step("navigate_to_receptacle refrigerator_01"),
        _robot_step("open_receptacle refrigerator_01"),
        _robot_step("place_inside observed_001"),
        _robot_step("close_receptacle refrigerator_01"),
        _robot_step("place observed_002"),
    ]

    checker.validate_run_result(
        result,
        tmp_path,
        expect_task=None,
        expect_backend="api_semantic_synthetic",
        require_robot_views=True,
    )


def test_checker_counts_visual_candidate_robot_view_as_object_navigation(
    tmp_path: Path,
) -> None:
    demo = _load_module(DEMO_PATH, "molmospaces_realworld_cleanup")
    checker = cleanup_checker

    result = demo.run_household_world_episode(output_dir=tmp_path, seed=7)
    _add_molmospaces_robot_view_artifacts(result, tmp_path)
    result["robot_view_steps"] = [
        {
            **_robot_step("navigate_to_visual_candidate observed_001"),
            "semantic_phase": "navigate_to_object",
            "action_evidence": {
                "backend_primitive": "navigate_to_object",
                "agent_tool": "navigate_to_visual_candidate",
            },
        },
        _robot_step("pick observed_001"),
        _robot_step("navigate_to_receptacle refrigerator_01"),
        _robot_step("open_receptacle refrigerator_01"),
        _robot_step("place_inside observed_001"),
        _robot_step("close_receptacle refrigerator_01"),
        _robot_step("place observed_002"),
    ]

    checker.validate_run_result(
        result,
        tmp_path,
        expect_task=None,
        expect_backend="api_semantic_synthetic",
        require_robot_views=True,
    )


def test_checker_rejects_zero_pixel_focused_surface_action(tmp_path: Path) -> None:
    smoke = _load_module(SMOKE_PATH, "run_molmo_realworld_agent_mcp_smoke")
    checker = cleanup_checker

    result = smoke.run_smoke(output_dir=tmp_path, seed=7)
    _add_molmospaces_robot_view_artifacts(result, tmp_path)
    result["robot_view_steps"] = [
        {
            **_robot_step("navigate_to_object observed_001"),
            "focus": {
                "has_focus": True,
                "object_id": "observed_001",
                "receptacle_id": "table_01",
                "fpv_visibility": {
                    "status": "ok",
                    "object_pixels": 0,
                    "receptacle_pixels": 100,
                },
                "visibility": {
                    "status": "ok",
                    "object_pixels": 0,
                    "receptacle_pixels": 100,
                },
            },
        },
        _robot_step("pick observed_001"),
    ]

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
            allow_partial_cleanup=True,
            require_robot_views=True,
        )


def test_checker_accepts_authorized_source_fpv_evidence_for_weak_nav_view(
    tmp_path: Path,
) -> None:
    smoke = _load_module(SMOKE_PATH, "run_molmo_realworld_agent_mcp_smoke")
    checker = cleanup_checker

    result = smoke.run_smoke(output_dir=tmp_path, seed=7)
    _add_molmospaces_robot_view_artifacts(result, tmp_path)
    result["robot_view_steps"] = [
        {
            **_robot_step("navigate_to_object observed_001"),
            "semantic_phase": "navigate_to_object",
            "action_evidence": {
                "schema": "robot_timeline_action_evidence_v1",
                "agent_tool": "navigate_to_object",
                "agent_action": "navigate_to_object observed_001",
                "backend_primitive": "navigate_to_object",
                "source_observation_id": "world_label_fpv_002",
                "source_image_bbox": [81.0, 65.0, 42.0, 31.0],
                "reviewability_status": "reviewable",
                "locality_status": "same_waypoint_source_observation",
                "candidate_state": "navigation_authorized",
                "actionability_status": "actionable",
            },
            "focus": {
                "has_focus": True,
                "object_id": "observed_001",
                "receptacle_id": "table_01",
                "fpv_visibility": {
                    "status": "weak_object_visibility",
                    "object_pixels": 0,
                    "receptacle_pixels": 100,
                },
                "visibility": {
                    "status": "weak_object_visibility",
                    "object_pixels": 0,
                    "receptacle_pixels": 100,
                },
            },
        },
        _robot_step("pick observed_001"),
    ]

    checker.validate_run_result(
        result,
        tmp_path,
        expect_task=None,
        expect_backend="api_semantic_synthetic",
        expect_policy="household_contract_smoke_agent",
        expect_mcp_server="household_world",
        min_generated_mess_count=5,
        require_agent_driven=True,
        allow_partial_cleanup=True,
        require_robot_views=True,
    )


def test_checker_rejects_weak_nav_view_without_authorized_source_fpv_evidence(
    tmp_path: Path,
) -> None:
    smoke = _load_module(SMOKE_PATH, "run_molmo_realworld_agent_mcp_smoke")
    checker = cleanup_checker

    result = smoke.run_smoke(output_dir=tmp_path, seed=7)
    _add_molmospaces_robot_view_artifacts(result, tmp_path)
    result["robot_view_steps"] = [
        {
            **_robot_step("navigate_to_object observed_001"),
            "semantic_phase": "navigate_to_object",
            "action_evidence": {
                "schema": "robot_timeline_action_evidence_v1",
                "agent_tool": "navigate_to_object",
                "agent_action": "navigate_to_object observed_001",
                "backend_primitive": "navigate_to_object",
                "source_observation_id": "world_label_fpv_001",
                "source_image_bbox": [],
                "reviewability_status": "not_reviewable",
                "locality_status": "semantic_hint_requires_source_fpv_scan",
                "candidate_state": "visual_scan_required",
                "actionability_status": "needs_visual_evidence",
            },
            "focus": {
                "has_focus": True,
                "object_id": "observed_001",
                "receptacle_id": "table_01",
                "fpv_visibility": {
                    "status": "weak_object_visibility",
                    "object_pixels": 0,
                    "receptacle_pixels": 100,
                },
                "visibility": {
                    "status": "weak_object_visibility",
                    "object_pixels": 0,
                    "receptacle_pixels": 100,
                },
            },
        },
        _robot_step("pick observed_001"),
    ]

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
            allow_partial_cleanup=True,
            require_robot_views=True,
        )


def test_checker_allows_weak_fpv_when_verify_view_is_grounded(tmp_path: Path) -> None:
    smoke = _load_module(SMOKE_PATH, "run_molmo_realworld_agent_mcp_smoke")
    checker = cleanup_checker

    result = smoke.run_smoke(output_dir=tmp_path, seed=7)
    _add_molmospaces_robot_view_artifacts(result, tmp_path)
    result["robot_view_steps"] = [
        {
            **_robot_step("navigate_to_object observed_001"),
            "focus": {
                "has_focus": True,
                "object_id": "observed_001",
                "receptacle_id": "table_01",
                "fpv_visibility": {
                    "status": "ok",
                    "object_pixels": 0,
                    "receptacle_pixels": 100,
                },
                "visibility": {
                    "status": "ok",
                    "object_pixels": 42,
                    "receptacle_pixels": 100,
                },
            },
        },
        _robot_step("pick observed_001"),
    ]

    checker.validate_run_result(
        result,
        tmp_path,
        expect_task=None,
        expect_backend="api_semantic_synthetic",
        expect_policy="household_contract_smoke_agent",
        expect_mcp_server="household_world",
        min_generated_mess_count=5,
        require_agent_driven=True,
        allow_partial_cleanup=True,
        require_robot_views=True,
    )


def test_checker_allows_weak_place_view_when_surface_evidence_is_grounded() -> None:
    _assert_focused_robot_step(
        {
            "action": "place observed_001",
            "semantic_phase": "place",
            "focus": {
                "has_focus": True,
                "object_id": "observed_001",
                "object_location_relation": "on",
                "receptacle_id": "table_01",
                "fpv_visibility": {
                    "status": "weak_object_visibility",
                    "object_pixels": 0,
                    "receptacle_pixels": 100,
                },
                "visibility": {
                    "status": "weak_object_visibility",
                    "object_pixels": 0,
                    "receptacle_pixels": 100,
                },
            },
        }
    )


def test_checker_allows_segmentation_unavailable_focused_surface_action(tmp_path: Path) -> None:
    smoke = _load_module(SMOKE_PATH, "run_molmo_realworld_agent_mcp_smoke")
    checker = cleanup_checker

    result = smoke.run_smoke(output_dir=tmp_path, seed=7)
    _add_molmospaces_robot_view_artifacts(result, tmp_path)
    result["robot_view_steps"] = [
        {
            **_robot_step("navigate_to_object observed_001"),
            "focus": {
                "has_focus": True,
                "object_id": "observed_001",
                "receptacle_id": "table_01",
                "fpv_visibility": {
                    "status": "segmentation_unavailable",
                    "error": "IndexError",
                    "object_pixels": 0,
                    "receptacle_pixels": 0,
                },
                "visibility": {
                    "status": "segmentation_unavailable",
                    "error": "IndexError",
                    "object_pixels": 0,
                    "receptacle_pixels": 0,
                },
            },
        },
        _robot_step("pick observed_001"),
    ]

    checker.validate_run_result(
        result,
        tmp_path,
        expect_task=None,
        expect_backend="api_semantic_synthetic",
        expect_policy="household_contract_smoke_agent",
        expect_mcp_server="household_world",
        min_generated_mess_count=5,
        require_agent_driven=True,
        allow_partial_cleanup=True,
        require_robot_views=True,
    )


def test_checker_rejects_agent_view_private_leak(tmp_path: Path) -> None:
    demo = _load_module(DEMO_PATH, "molmospaces_realworld_cleanup")
    checker = cleanup_checker

    result = demo.run_household_world_episode(output_dir=tmp_path, seed=7)
    result["agent_view"]["generated_mess_set"] = ["leak"]

    with pytest.raises(AssertionError):
        checker.validate_run_result(
            result,
            tmp_path,
            expect_task=None,
            expect_backend="api_semantic_synthetic",
        )
