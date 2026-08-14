# ruff: noqa: F403, F405
from tests.support.cleanup_checker_planner import *


def test_checker_accepts_live_raw_fpv_map_build_shape(tmp_path: Path) -> None:
    demo = _load_module(DEMO_PATH, "molmospaces_realworld_cleanup")
    checker = cleanup_checker

    result = demo.run_household_world_episode(
        output_dir=tmp_path,
        seed=7,
        perception_mode="raw_fpv_only",
        intent="map-build",
    )
    result["task_name"] = "household-world"
    result["task_intent"] = "map-build"
    result["policy"] = "codex_agent"
    result["agent_driven"] = True
    result["mcp_server"] = "household_world"
    result["map_build"] = None
    result["map_build_mode"] = None
    result["cleanup_actions_disabled"] = None
    result["generated_mess_count"] = 0
    result["semantic_substeps"] = []
    result["private_evaluation"]["generated_mess_count"] = 0
    result["private_evaluation"]["acceptable_destination_sets"] = {}
    result["score"]["total_targets"] = 0
    result["score"]["sweep_coverage_rate"] = 1.0
    result["sweep_coverage_rate"] = 1.0
    trace = result["cleanup_policy_trace"]
    trace["loop_style"] = "scan_only"
    trace["cleanup_action_count"] = 0
    trace["placed_object_count"] = 0
    trace["post_place_observe_count"] = 0
    trace["first_cleanup_before_full_survey"] = False
    result["tool_event_counts"] = {
        key: value
        for key, value in result["tool_event_counts"].items()
        if not key.startswith(
            (
                "navigate_to_object:",
                "navigate_to_visual_candidate:",
                "pick:",
                "navigate_to_receptacle:",
                "open_receptacle:",
                "place:",
                "place_inside:",
                "close_receptacle:",
            )
        )
    }
    robot_views = tmp_path / "robot_views"
    robot_views.mkdir(exist_ok=True)
    (robot_views / "raw.fpv.png").write_bytes(b"placeholder")
    result["artifacts"]["robot_views"] = str(robot_views)
    for item in result["raw_fpv_observations"]:
        item["image_artifacts"] = {"fpv": "robot_views/raw.fpv.png"}
    for item in agent_view_module.raw_fpv_observations(result["agent_view"]):
        item["image_artifacts"] = {"fpv": "robot_views/raw.fpv.png"}

    checker.validate_run_result(
        result,
        tmp_path,
        expect_task=None,
        expect_backend="api_semantic_synthetic",
        expect_task_name="household-world",
        expect_policy="codex_agent",
        expect_mcp_server="household_world",
        min_generated_mess_count=0,
        require_agent_driven=True,
        require_runtime_metric_map=True,
        require_map_build=True,
        require_base_metric_map=True,
        require_raw_fpv_observations=True,
        min_sweep_coverage=1.0,
    )


def test_checker_can_require_raw_fpv_model_declared_success_gate(tmp_path: Path) -> None:
    smoke = _load_module(SMOKE_PATH, "run_molmo_realworld_agent_mcp_smoke")
    checker = cleanup_checker

    result = smoke.run_smoke(
        output_dir=tmp_path,
        seed=7,
        perception_mode=CAMERA_MODEL_POLICY_MODE,
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
        require_model_declared_observations=True,
        min_model_declared_observations=5,
        min_model_declared_actions=4,
        min_semantic_accepted_count=4,
    )


def test_checker_rejects_raw_fpv_model_declared_semantic_shortfall(tmp_path: Path) -> None:
    smoke = _load_module(SMOKE_PATH, "run_molmo_realworld_agent_mcp_smoke")
    checker = cleanup_checker

    result = smoke.run_smoke(
        output_dir=tmp_path,
        seed=7,
        perception_mode=CAMERA_MODEL_POLICY_MODE,
    )
    result["score"]["semantic_acceptability"] = {
        "accepted_count": 4,
        "total_targets": 5,
        "accepted_levels": ["acceptable", "preferred"],
        "counts": {
            "preferred": 2,
            "acceptable": 2,
            "questionable": 1,
            "wrong": 0,
            "unknown": 0,
        },
        "status": "success",
        "accepted_object_ids": ["mug_01", "book_01", "apple_01", "towel_01"],
        "questionable_object_ids": ["toy_car_01"],
        "wrong_object_ids": [],
        "unknown_object_ids": [],
    }

    with pytest.raises(AssertionError):
        checker.validate_run_result(
            result,
            tmp_path,
            expect_task=None,
            expect_backend="api_semantic_synthetic",
            min_generated_mess_count=5,
            require_model_declared_observations=True,
            min_model_declared_observations=5,
            min_model_declared_actions=5,
            min_semantic_accepted_count=5,
        )


def test_checker_rejects_raw_fpv_model_declared_action_shortfall(tmp_path: Path) -> None:
    smoke = _load_module(SMOKE_PATH, "run_molmo_realworld_agent_mcp_smoke")
    checker = cleanup_checker

    result = smoke.run_smoke(
        output_dir=tmp_path,
        seed=7,
        perception_mode=CAMERA_MODEL_POLICY_MODE,
    )
    evidence = result["model_declared_observation_evidence"]
    evidence["acted_count"] = 3
    for index, item in enumerate(evidence["observations"]):
        item["acted_on"] = index < 3
    result["model_declared_observations"] = evidence["observations"]

    with pytest.raises(AssertionError):
        checker.validate_run_result(
            result,
            tmp_path,
            expect_task=None,
            expect_backend="api_semantic_synthetic",
            min_generated_mess_count=5,
            require_model_declared_observations=True,
            min_model_declared_observations=5,
            min_model_declared_actions=5,
            min_semantic_accepted_count=5,
        )


def test_checker_rejects_duplicate_post_place_visual_navigation(tmp_path: Path) -> None:
    checker = cleanup_checker
    trace_path = tmp_path / "trace.jsonl"
    _write_trace(
        trace_path,
        [
            _trace_response("observe", {"ok": True, "tool": "observe"}),
            _trace_response(
                "navigate_to_visual_candidate",
                {
                    "ok": True,
                    "tool": "navigate_to_visual_candidate",
                    "object_id": "observed_001",
                },
            ),
            _trace_response("pick", {"ok": True, "tool": "pick", "object_id": "observed_001"}),
            _trace_response("place", {"ok": True, "tool": "place", "object_id": "observed_001"}),
            _trace_response(
                "navigate_to_visual_candidate",
                {
                    "ok": True,
                    "tool": "navigate_to_visual_candidate",
                    "object_id": "observed_001",
                },
            ),
        ],
    )

    with pytest.raises(AssertionError):
        checker._assert_no_duplicate_post_place_navigation(trace_path)


def test_checker_allows_normal_visual_cleanup_trace(tmp_path: Path) -> None:
    checker = cleanup_checker
    trace_path = tmp_path / "trace.jsonl"
    _write_trace(
        trace_path,
        [
            _trace_response("observe", {"ok": True, "tool": "observe"}),
            _trace_response(
                "navigate_to_visual_candidate",
                {
                    "ok": True,
                    "tool": "navigate_to_visual_candidate",
                    "object_id": "observed_001",
                },
            ),
            _trace_response("pick", {"ok": True, "tool": "pick", "object_id": "observed_001"}),
            _trace_response(
                "navigate_to_receptacle",
                {
                    "ok": True,
                    "tool": "navigate_to_receptacle",
                    "object_id": "observed_001",
                    "receptacle_id": "sink_01",
                },
            ),
            _trace_response("place", {"ok": True, "tool": "place", "object_id": "observed_001"}),
        ],
    )

    checker._assert_no_duplicate_post_place_navigation(trace_path)


def test_checker_can_require_attached_planner_proof(tmp_path: Path) -> None:
    demo = _load_module(DEMO_PATH, "molmospaces_realworld_cleanup")
    checker = cleanup_checker
    proof_path = _write_strict_planner_proof(tmp_path / "proof")
    cleanup_dir = tmp_path / "cleanup"

    result = demo.run_household_world_episode(
        output_dir=cleanup_dir,
        seed=7,
        planner_proof_run_result=proof_path,
    )

    assert result["primitive_provenance"] == "api_semantic"
    checker.validate_run_result(
        result,
        cleanup_dir,
        expect_task=None,
        expect_backend="api_semantic_synthetic",
        min_generated_mess_count=5,
        require_planner_proof_attachment=True,
        require_planner_proof_quality=True,
        require_planner_proof_min_steps=2,
    )


def test_checker_rejects_attached_proof_below_min_steps(tmp_path: Path) -> None:
    demo = _load_module(DEMO_PATH, "molmospaces_realworld_cleanup")
    checker = cleanup_checker
    proof_path = _write_strict_planner_proof(tmp_path / "proof", steps_executed=1)
    cleanup_dir = tmp_path / "cleanup"

    result = demo.run_household_world_episode(
        output_dir=cleanup_dir,
        seed=7,
        planner_proof_run_result=proof_path,
    )

    with pytest.raises(AssertionError):
        checker.validate_run_result(
            result,
            cleanup_dir,
            expect_task=None,
            expect_backend="api_semantic_synthetic",
            min_generated_mess_count=5,
            require_planner_proof_attachment=True,
            require_planner_proof_quality=True,
            require_planner_proof_min_steps=2,
        )


def test_checker_accepts_blocked_planner_cleanup_bridge(tmp_path: Path) -> None:
    demo = _load_module(DEMO_PATH, "molmospaces_realworld_cleanup")
    checker = cleanup_checker
    proof_path = _write_strict_planner_proof(
        tmp_path / "proof",
        embodiment="rby1m",
        upstream_policy_class="CuroboPickAndPlacePlannerPolicy",
        curobo_available=True,
    )
    cleanup_dir = tmp_path / "cleanup"

    result = demo.run_household_world_episode(
        output_dir=cleanup_dir,
        seed=7,
        planner_proof_run_result=proof_path,
    )

    bridge = result["planner_cleanup_bridge_evidence"]
    assert bridge["status"] == "blocked_capability"
    assert bridge["target_runtime_ready"] is True
    assert bridge["cleanup_primitives_ready"] is False
    checker.validate_run_result(
        result,
        cleanup_dir,
        expect_task=None,
        expect_backend="api_semantic_synthetic",
        min_generated_mess_count=5,
        require_planner_proof_attachment=True,
        accept_blocked_planner_cleanup_primitives=True,
        accept_blocked_planner_cleanup_bridge=True,
    )


def test_realworld_cleanup_can_use_matching_probe_backed_executor(
    tmp_path: Path,
) -> None:
    demo = _load_module(DEMO_PATH, "molmospaces_realworld_cleanup")
    anchor_probe = demo.run_household_world_episode(
        output_dir=tmp_path / "anchor-probe",
        seed=7,
    )
    toy_anchor = _candidate_fixture_id_for_object(anchor_probe, "observed_001")
    proof_path = _write_strict_planner_proof(
        tmp_path / "proof",
        embodiment="rby1m",
        upstream_policy_class="CuroboPickAndPlacePlannerPolicy",
        curobo_available=True,
        cleanup_binding={
            "schema": "planner_probe_cleanup_primitive_binding_v1",
            "object_id": "observed_001",
            "target_receptacle_id": toy_anchor,
            "source_receptacle_id": "coffee_table_01",
            "planner_object_id": "pickup/body",
            "planner_target_receptacle_id": "dropoff/body",
            "tools": [
                "navigate_to_object",
                "pick",
                "navigate_to_receptacle",
                "place",
            ],
        },
    )
    cleanup_dir = tmp_path / "cleanup"

    result = demo.run_household_world_episode(
        output_dir=cleanup_dir,
        seed=7,
        planner_proof_run_result=proof_path,
        use_planner_proof_for_cleanup_primitives=True,
    )

    assert result["cleanup_status"] == "success"
    assert result["planner_proof_cleanup_executor_enabled"] is True
    evidence = result["cleanup_primitive_evidence"]
    assert evidence["status"] == "blocked_capability"
    bounded_object = next(
        item for item in evidence["objects"] if item["object_id"] == "observed_001"
    )
    assert bounded_object["planner_backed"] is True
    assert bounded_object["strict_proof_eligible"] is True
    for step in bounded_object["subphases"]:
        assert step["primitive_provenance"] == "planner_backed"
        assert step["planner_backed"] is True
        assert step["strict_proof_eligible"] is True
    normal_object = next(
        item for item in evidence["objects"] if item["object_id"] == "observed_002"
    )
    assert normal_object["planner_backed"] is False
    assert {step["primitive_provenance"] for step in normal_object["subphases"]} == {"api_semantic"}
    bridge = result["planner_cleanup_bridge_evidence"]
    assert bridge["target_runtime_ready"] is True
    assert bridge["cleanup_primitives_ready"] is False
    report = (cleanup_dir / "report.html").read_text(encoding="utf-8")
    assert "Cleanup Primitive Gate" in report
    assert "Planner Cleanup Bridge" in report
    checker = cleanup_checker
    checker.validate_run_result(
        result,
        cleanup_dir,
        expect_task=None,
        expect_backend="api_semantic_synthetic",
        require_planner_proof_attachment=True,
        accept_blocked_planner_cleanup_primitives=True,
        require_bound_planner_cleanup_objects=[f"observed_001:{toy_anchor}"],
        require_mixed_planner_cleanup_primitives=True,
        accept_blocked_planner_cleanup_bridge=True,
    )


def test_realworld_cleanup_mismatched_probe_binding_keeps_semantic_path(
    tmp_path: Path,
) -> None:
    demo = _load_module(DEMO_PATH, "molmospaces_realworld_cleanup")
    proof_path = _write_strict_planner_proof(
        tmp_path / "proof",
        embodiment="rby1m",
        upstream_policy_class="CuroboPickAndPlacePlannerPolicy",
        curobo_available=True,
        cleanup_binding={
            "schema": "planner_probe_cleanup_primitive_binding_v1",
            "object_id": "observed_999",
            "target_receptacle_id": "toy_bin_01",
            "tools": [
                "navigate_to_object",
                "pick",
                "navigate_to_receptacle",
                "place",
            ],
        },
    )

    result = demo.run_household_world_episode(
        output_dir=tmp_path / "cleanup",
        seed=7,
        planner_proof_run_result=proof_path,
        use_planner_proof_for_cleanup_primitives=True,
    )

    assert result["cleanup_status"] == "success"
    assert result["planner_proof_cleanup_executor_enabled"] is True
    primitive_summary = result["cleanup_primitive_evidence"]["primitive_provenance_summary"]
    assert set(primitive_summary) == {"api_semantic"}
    assert result["cleanup_primitive_evidence"]["planner_backed"] is False
    assert result["planner_cleanup_bridge_evidence"]["cleanup_primitives_ready"] is False


def test_realworld_cleanup_can_use_proof_bundle_for_full_gate_readiness(
    tmp_path: Path,
) -> None:
    demo = _load_module(DEMO_PATH, "molmospaces_realworld_cleanup")
    checker = cleanup_checker
    anchor_probe = demo.run_household_world_episode(
        output_dir=tmp_path / "anchor-probe",
        seed=7,
    )
    proof_paths = [
        _write_strict_planner_proof(
            tmp_path / f"proof-{binding['object_id']}",
            embodiment="rby1m",
            upstream_policy_class="CuroboPickAndPlacePlannerPolicy",
            curobo_available=True,
            cleanup_binding=binding,
        )
        for binding in _seed7_cleanup_bindings(anchor_probe)
    ]
    cleanup_dir = tmp_path / "cleanup"

    result = demo.run_household_world_episode(
        output_dir=cleanup_dir,
        seed=7,
        planner_proof_run_results=proof_paths,
        use_planner_proof_for_cleanup_primitives=True,
    )

    assert result["cleanup_status"] == "success"
    assert result["primitive_provenance"] == "planner_backed"
    assert result["cleanup_primitive_evidence"]["status"] == "planner_backed"
    assert result["planner_cleanup_bridge_evidence"]["status"] == "planner_backed"
    assert result["planner_backed_manipulation_proof"]["schema"] == (
        "planner_backed_cleanup_proof_bundle_v1"
    )
    assert result["planner_backed_manipulation_proof"]["proof_count"] == 5
    report = (cleanup_dir / "report.html").read_text(encoding="utf-8")
    assert "Attached Planner-Backed Proofs" in report
    assert "proof_001 Planner Initial" in report
    bound_probe = _first_seed7_binding_requiring_tool(anchor_probe, "place_inside")
    checker.validate_run_result(
        result,
        cleanup_dir,
        expect_task=None,
        expect_backend="api_semantic_synthetic",
        min_generated_mess_count=5,
        require_planner_proof_attachment=True,
        require_planner_backed_cleanup_primitives=True,
        require_bound_planner_cleanup_objects=[
            f"{bound_probe['object_id']}:{bound_probe['target_receptacle_id']}"
        ],
        require_planner_cleanup_bridge_ready=True,
    )


def test_checker_rejects_current_cleanup_when_bridge_ready_required(tmp_path: Path) -> None:
    demo = _load_module(DEMO_PATH, "molmospaces_realworld_cleanup")
    checker = cleanup_checker
    proof_path = _write_strict_planner_proof(
        tmp_path / "proof",
        embodiment="rby1m",
        upstream_policy_class="CuroboPickAndPlacePlannerPolicy",
        curobo_available=True,
    )
    cleanup_dir = tmp_path / "cleanup"

    result = demo.run_household_world_episode(
        output_dir=cleanup_dir,
        seed=7,
        planner_proof_run_result=proof_path,
    )

    with pytest.raises(AssertionError):
        checker.validate_run_result(
            result,
            cleanup_dir,
            expect_task=None,
            expect_backend="api_semantic_synthetic",
            min_generated_mess_count=5,
            require_planner_cleanup_bridge_ready=True,
        )


def test_checker_accepts_blocked_cleanup_primitive_gate(tmp_path: Path) -> None:
    demo = _load_module(DEMO_PATH, "molmospaces_realworld_cleanup")
    checker = cleanup_checker

    result = demo.run_household_world_episode(output_dir=tmp_path, seed=7)

    checker.validate_run_result(
        result,
        tmp_path,
        expect_task=None,
        expect_backend="api_semantic_synthetic",
        min_generated_mess_count=5,
        accept_blocked_planner_cleanup_primitives=True,
    )
    assert result["cleanup_primitive_evidence"]["status"] == "blocked_capability"


def test_checker_rejects_current_cleanup_when_planner_primitives_required(
    tmp_path: Path,
) -> None:
    demo = _load_module(DEMO_PATH, "molmospaces_realworld_cleanup")
    checker = cleanup_checker

    result = demo.run_household_world_episode(output_dir=tmp_path, seed=7)

    with pytest.raises(AssertionError):
        checker.validate_run_result(
            result,
            tmp_path,
            expect_task=None,
            expect_backend="api_semantic_synthetic",
            min_generated_mess_count=5,
            require_planner_backed_cleanup_primitives=True,
        )


def test_checker_rejects_missing_required_planner_proof(tmp_path: Path) -> None:
    demo = _load_module(DEMO_PATH, "molmospaces_realworld_cleanup")
    checker = cleanup_checker

    result = demo.run_household_world_episode(output_dir=tmp_path, seed=7)

    with pytest.raises(AssertionError):
        checker.validate_run_result(
            result,
            tmp_path,
            expect_task=None,
            expect_backend="api_semantic_synthetic",
            min_generated_mess_count=5,
            require_planner_proof_attachment=True,
        )
