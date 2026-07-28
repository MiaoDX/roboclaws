from __future__ import annotations

import importlib.util
import json
import shutil
import sys
from pathlib import Path

import pytest
from PIL import Image

from roboclaws.household import agent_view as agent_view_module
from roboclaws.household.agibot_household_backend import AgibotHouseholdBackend
from roboclaws.household.household_mcp_server import make_household_world_mcp
from roboclaws.household.household_runtime_contract import (
    CAMERA_MODEL_POLICY_MODE,
    REALWORLD_CONTRACT,
    forbidden_agent_view_keys,
)
from roboclaws.household.manipulation_provenance import (
    MANIPULATION_PROBE_CONTRACT,
    PLANNER_BACKED_PROVENANCE,
    planner_backed_probe_evidence,
)
from roboclaws.household.nav2_map_bundle import attach_nav2_map_bundle_snapshot
from roboclaws.mcp.profiles import HOUSEHOLD_EPISODE_PROFILE, HOUSEHOLD_WORLD_PROFILE
from scripts.isaac_lab_cleanup.check_b1_map12_readiness import (
    DEFAULT_B1_VISUAL_ROUTE_SCENE_USD,
    NAVIGATION_PROVENANCE,
)
from scripts.maps.augment_b1_map12_base_metric_map import augment_base_metric_map_bundle
from scripts.maps.build_b1_map12_base_metric_map import build_base_metric_map_bundle

REPO_ROOT = Path(__file__).resolve().parents[3]
DEMO_PATH = REPO_ROOT / "examples" / "molmo_cleanup" / "molmospaces_realworld_cleanup.py"
CHECKER_PATH = REPO_ROOT / "scripts" / "molmo_cleanup" / "check_molmo_realworld_cleanup_result.py"
SMOKE_PATH = REPO_ROOT / "scripts" / "molmo_cleanup" / "run_molmo_realworld_agent_mcp_smoke.py"
AGIBOT_CONTEXT_FIXTURE = REPO_ROOT / "tests" / "fixtures" / "agibot_map_context.completed.json"
AGIBOT_SDK_RUNNER_PATH = (
    REPO_ROOT / "vendors" / "agibot_sdk" / "tools" / "run_agibot_cleanup_backend.py"
)
B1_MAP12_BUNDLE = (
    REPO_ROOT / "vendors" / "agibot_sdk" / "artifacts" / "maps" / "robot_map_12" / "agibot"
)
B1_ROOM_SEMANTICS = REPO_ROOT / "assets" / "maps" / "b1-map12-room-semantics.json"
B1_BASE_LABELS = REPO_ROOT / "assets" / "maps" / "b1-map12-base-metric-labels.json"
PREBUILT_BUNDLE = REPO_ROOT / "assets" / "maps" / "molmospaces" / "procthor-10k-val" / "0"
MOLMOSPACES_ROBOT_VIEW_VARIANT = "molmospaces-rby1m-fpv-topdown-chase-verify"
ROBOT_VIEW_KEYS = ("fpv", "chase", "topdown", "verify")


def _require_agibot_sdk_runner() -> None:
    if not AGIBOT_SDK_RUNNER_PATH.is_file():
        pytest.skip("Agibot SDK vendor runner is unavailable in this checkout")


def _load_module(path: Path, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    if path == DEMO_PATH:
        run_household_world_episode = module.run_household_world_episode

        def run_synthetic_realworld_cleanup(**kwargs):
            kwargs.setdefault("map_bundle_dir", PREBUILT_BUNDLE)
            return run_household_world_episode(**kwargs)

        module.run_household_world_episode = run_synthetic_realworld_cleanup
    elif path == SMOKE_PATH:
        run_smoke = module.run_smoke

        def run_synthetic_smoke(**kwargs):
            kwargs.setdefault("map_bundle_dir", PREBUILT_BUNDLE)
            return run_smoke(**kwargs)

        module.run_smoke = run_synthetic_smoke
    return module


def test_checker_parses_robot_head_camera_fpv_flag(monkeypatch: pytest.MonkeyPatch) -> None:
    checker = _load_module(CHECKER_PATH, "check_molmo_realworld_cleanup_result")

    monkeypatch.setattr(
        sys,
        "argv",
        [
            "check_molmo_realworld_cleanup_result.py",
            "run_result.json",
            "--require-robot-head-camera-fpv",
        ],
    )

    args = checker.parse_args()

    assert args.require_robot_head_camera_fpv is True


def test_checker_rejects_legacy_canonical_robot_view_camera_control_flag(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    checker = _load_module(CHECKER_PATH, "check_molmo_realworld_cleanup_result")

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
        checker.parse_args()

    assert exc_info.value.code == 2
    stderr = capsys.readouterr().err
    assert "--require-canonical-robot-view-camera-control is obsolete" in stderr
    assert "use --require-robot-head-camera-fpv" in stderr


def test_checker_rejects_legacy_canonical_robot_view_camera_control_override() -> None:
    checker = _load_module(CHECKER_PATH, "check_molmo_realworld_cleanup_result")

    with pytest.raises(ValueError, match="use require_robot_head_camera_fpv"):
        checker._result_assert_options({"require_canonical_robot_view_camera_control": True})


def test_checker_accepts_single_realworld_run(tmp_path: Path) -> None:
    demo = _load_module(DEMO_PATH, "molmospaces_realworld_cleanup")
    checker = _load_module(CHECKER_PATH, "check_molmo_realworld_cleanup_result")

    demo.run_household_world_episode(output_dir=tmp_path, seed=7)

    data, path = checker._load_run_results(tmp_path / "run_result.json")[0]
    checker._assert_result(
        data,
        path.parent,
        expect_task=None,
        expect_backend="api_semantic_synthetic",
        min_generated_mess_count=5,
    )


def test_checker_can_require_runtime_metric_map(tmp_path: Path) -> None:
    demo = _load_module(DEMO_PATH, "molmospaces_realworld_cleanup")
    checker = _load_module(CHECKER_PATH, "check_molmo_realworld_cleanup_result")

    result = demo.run_household_world_episode(output_dir=tmp_path, seed=7)

    checker._assert_result(
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
    checker = _load_module(CHECKER_PATH, "check_molmo_realworld_cleanup_result")

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
        checker._assert_result(
            result,
            tmp_path,
            expect_task=None,
            expect_backend="api_semantic_synthetic",
            min_generated_mess_count=5,
            require_runtime_metric_map=True,
        )


def test_checker_rejects_rgb_only_runtime_map_object_pose(tmp_path: Path) -> None:
    demo = _load_module(DEMO_PATH, "molmospaces_realworld_cleanup")
    checker = _load_module(CHECKER_PATH, "check_molmo_realworld_cleanup_result")

    result = demo.run_household_world_episode(
        output_dir=tmp_path,
        seed=7,
        perception_mode=CAMERA_MODEL_POLICY_MODE,
    )
    observed = result["runtime_metric_map"]["observed_objects"][0]
    observed["object_pose"] = {"x": 1.0, "y": 2.0, "yaw": 0.0}
    result["agent_view"]["runtime_metric_map"] = result["runtime_metric_map"]

    with pytest.raises(AssertionError, match="RGB-only current-run map evidence"):
        checker._assert_result(
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
    checker = _load_module(CHECKER_PATH, "check_molmo_realworld_cleanup_result")

    result = demo.run_household_world_episode(
        output_dir=tmp_path,
        seed=7,
        intent="map-build",
        perception_mode=CAMERA_MODEL_POLICY_MODE,
    )

    checker._assert_result(
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
    checker = _load_module(CHECKER_PATH, "check_molmo_realworld_cleanup_result")

    result = demo.run_household_world_episode(
        output_dir=tmp_path,
        seed=7,
        intent="map-build",
        perception_mode=CAMERA_MODEL_POLICY_MODE,
    )
    result["tool_event_counts"]["adjust_camera:request"] = 0

    checker._assert_result(
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
        checker._assert_result(
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
    checker = _load_module(CHECKER_PATH, "check_molmo_realworld_cleanup_result")

    result = demo.run_household_world_episode(
        output_dir=tmp_path,
        seed=7,
        intent="map-build",
        perception_mode=CAMERA_MODEL_POLICY_MODE,
    )
    result["runtime_metric_map"]["generated_target_inspection_candidates"] = []
    result["agent_view"]["runtime_metric_map"] = result["runtime_metric_map"]

    checker._assert_result(
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
        checker._assert_result(
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
    checker = _load_module(CHECKER_PATH, "check_molmo_realworld_cleanup_result")

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

    checker._assert_result(
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
    checker = _load_module(CHECKER_PATH, "check_molmo_realworld_cleanup_result")
    run_dir = _write_agibot_map_build_fixture(tmp_path)

    data, path = checker._load_run_results(run_dir / "run_result.json")[0]
    checker._assert_result(
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
    checker = _load_module(CHECKER_PATH, "check_molmo_realworld_cleanup_result")
    run_dir = _write_agibot_map_build_fixture(tmp_path)

    data, path = checker._load_run_results(run_dir / "run_result.json")[0]
    with pytest.raises(AssertionError):
        checker._assert_result(
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
    checker = _load_module(CHECKER_PATH, "check_molmo_realworld_cleanup_result")
    run_dir = _write_agibot_map_build_fixture(tmp_path)
    data, path = checker._load_run_results(run_dir / "run_result.json")[0]
    _promote_agibot_fixture_to_hardware_shape(data, run_dir)

    checker._assert_result(
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
    checker = _load_module(CHECKER_PATH, "check_molmo_realworld_cleanup_result")
    run_dir = _write_agibot_map_build_fixture(tmp_path)
    data, path = checker._load_run_results(run_dir / "run_result.json")[0]
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
        checker._assert_result(
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
    checker = _load_module(CHECKER_PATH, "check_molmo_realworld_cleanup_result")
    run_dir = _write_agibot_map_build_fixture(tmp_path)
    data, path = checker._load_run_results(run_dir / "run_result.json")[0]
    _promote_agibot_fixture_to_hardware_shape(data, run_dir)
    data[field] = value

    with pytest.raises(AssertionError):
        checker._assert_result(
            data,
            path.parent,
            expect_task=None,
            expect_backend="agibot_sdk_runner",
            min_generated_mess_count=0,
            require_map_build=True,
            require_agibot_g2_hardware=True,
            min_sweep_coverage=1.0,
        )


def test_checker_rejects_agibot_hardware_without_runtime_metric_map(
    tmp_path: Path,
) -> None:
    checker = _load_module(CHECKER_PATH, "check_molmo_realworld_cleanup_result")
    run_dir = _write_agibot_map_build_fixture(tmp_path)
    data, path = checker._load_run_results(run_dir / "run_result.json")[0]
    _promote_agibot_fixture_to_hardware_shape(data, run_dir)
    data.pop("runtime_metric_map", None)
    agent_view = data["agent_view"]
    assert isinstance(agent_view, dict)
    agent_view.pop("runtime_metric_map", None)

    with pytest.raises(AssertionError):
        checker._assert_result(
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
    checker = _load_module(CHECKER_PATH, "check_molmo_realworld_cleanup_result")

    result = demo.run_household_world_episode(
        output_dir=tmp_path,
        seed=7,
        intent="map-build",
    )

    checker._assert_result(
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
    checker = _load_module(CHECKER_PATH, "check_molmo_realworld_cleanup_result")

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

    checker._assert_result(
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
    checker = _load_module(CHECKER_PATH, "check_molmo_realworld_cleanup_result")

    result = demo.run_household_world_episode(output_dir=tmp_path, seed=7)
    result["runtime_metric_map"]["observed_objects"][0]["target_receptacle_id"] = "sink_01"
    result["agent_view"]["runtime_metric_map"] = result["runtime_metric_map"]

    with pytest.raises(AssertionError):
        checker._assert_result(
            result,
            tmp_path,
            expect_task=None,
            expect_backend="api_semantic_synthetic",
            min_generated_mess_count=5,
            require_runtime_metric_map=True,
        )


def test_checker_rejects_target_candidate_private_leak(tmp_path: Path) -> None:
    demo = _load_module(DEMO_PATH, "molmospaces_realworld_cleanup")
    checker = _load_module(CHECKER_PATH, "check_molmo_realworld_cleanup_result")

    result = demo.run_household_world_episode(output_dir=tmp_path, seed=7)
    result["runtime_metric_map"]["target_candidates"][0]["target_receptacle_id"] = "sink_01"
    result["agent_view"]["runtime_metric_map"] = result["runtime_metric_map"]

    with pytest.raises(AssertionError):
        checker._assert_result(
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
    checker = _load_module(CHECKER_PATH, "check_molmo_realworld_cleanup_result")

    result = demo.run_household_world_episode(output_dir=tmp_path, seed=7)
    candidate = next(
        item
        for item in result["runtime_metric_map"]["target_candidates"]
        if item["target_actionability_status"] != "actionable"
    )
    candidate["rejection_reason"] = ""
    result["agent_view"]["runtime_metric_map"] = result["runtime_metric_map"]

    with pytest.raises(AssertionError):
        checker._assert_result(
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
    checker = _load_module(CHECKER_PATH, "check_molmo_realworld_cleanup_result")

    result = demo.run_household_world_episode(
        output_dir=tmp_path,
        seed=7,
        intent="map-build",
    )
    result["runtime_metric_map"]["public_semantic_anchors"][0]["promotion_status"] = "promoted"
    result["agent_view"]["runtime_metric_map"] = result["runtime_metric_map"]

    with pytest.raises(AssertionError):
        checker._assert_result(
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
    checker = _load_module(CHECKER_PATH, "check_molmo_realworld_cleanup_result")

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
        checker._assert_result(
            result,
            tmp_path / "cleanup",
            expect_task=None,
            expect_backend="api_semantic_synthetic",
            min_generated_mess_count=5,
            require_runtime_metric_map=True,
        )


def test_checker_allows_actionable_current_run_confirmation_of_prior(tmp_path: Path) -> None:
    demo = _load_module(DEMO_PATH, "molmospaces_realworld_cleanup")
    checker = _load_module(CHECKER_PATH, "check_molmo_realworld_cleanup_result")

    result = demo.run_household_world_episode(output_dir=tmp_path, seed=7)
    current = result["runtime_metric_map"]["observed_objects"][0]
    current["freshness"] = "current_run"
    current["prior_object_id"] = "observed_prior_001"
    current["snapshot_object_id"] = "observed_prior_001"
    current["actionability"] = "actionable"
    result["agent_view"]["runtime_metric_map"] = result["runtime_metric_map"]

    checker._assert_result(
        result,
        tmp_path,
        expect_task=None,
        expect_backend="api_semantic_synthetic",
        min_generated_mess_count=5,
        require_runtime_metric_map=True,
    )


def test_checker_accepts_smoke_profile_metadata_and_report_note(tmp_path: Path) -> None:
    demo = _load_module(DEMO_PATH, "molmospaces_realworld_cleanup")
    checker = _load_module(CHECKER_PATH, "check_molmo_realworld_cleanup_result")

    result = demo.run_household_world_episode(
        output_dir=tmp_path,
        seed=7,
        evidence_lane="smoke",
    )

    checker._assert_result(
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
    checker = _load_module(CHECKER_PATH, "check_molmo_realworld_cleanup_result")

    result = demo.run_household_world_episode(output_dir=tmp_path, seed=7)

    checker._assert_result(
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
    checker = _load_module(CHECKER_PATH, "check_molmo_realworld_cleanup_result")

    result = demo.run_household_world_episode(
        output_dir=tmp_path,
        seed=7,
        intent="map-build",
    )

    checker._assert_result(
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
    checker = _load_module(CHECKER_PATH, "check_molmo_realworld_cleanup_result")

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

    checker._assert_result(
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
    checker = _load_module(CHECKER_PATH, "check_molmo_realworld_cleanup_result")

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

    checker._assert_result(
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
    checker = _load_module(CHECKER_PATH, "check_molmo_realworld_cleanup_result")

    result = demo.run_household_world_episode(
        output_dir=tmp_path,
        seed=7,
    )
    trace = result["cleanup_policy_trace"]
    trace["loop_style"] = "scan_only"
    trace["cleanup_action_count"] = 0

    with pytest.raises(AssertionError):
        checker._assert_result(
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
    checker = _load_module(CHECKER_PATH, "check_molmo_realworld_cleanup_result")

    result = demo.run_household_world_episode(
        output_dir=tmp_path,
        seed=7,
    )

    checker._assert_result(
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
    assert trace["post_place_observe_count"] >= trace["placed_object_count"]


def test_checker_allows_base_metric_map_waypoint_honesty_for_online_interleaved_cleanup(
    tmp_path: Path,
) -> None:
    demo = _load_module(DEMO_PATH, "molmospaces_realworld_cleanup")
    checker = _load_module(CHECKER_PATH, "check_molmo_realworld_cleanup_result")

    result = demo.run_household_world_episode(
        output_dir=tmp_path,
        seed=7,
    )
    trace = result["cleanup_policy_trace"]
    trace["loop_style"] = "interleaved_cleanup_loop"
    trace["first_cleanup_before_full_survey"] = True

    checker._assert_result(
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
    checker = _load_module(CHECKER_PATH, "check_molmo_realworld_cleanup_result")

    result = demo.run_household_world_episode(
        output_dir=tmp_path,
        seed=7,
    )
    result["map_build"] = None
    result["map_build_mode"] = None

    checker._assert_result(
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
    checker = _load_module(CHECKER_PATH, "check_molmo_realworld_cleanup_result")

    result = demo.run_household_world_episode(
        output_dir=tmp_path,
        seed=7,
    )
    trace = result["cleanup_policy_trace"]
    trace["loop_style"] = "interleaved_cleanup_loop"
    trace["first_cleanup_before_full_survey"] = True
    trace["observed_waypoint_count"] = max(0, int(trace["total_waypoints"]) - 1)

    with pytest.raises(AssertionError):
        checker._assert_result(
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
    checker = _load_module(CHECKER_PATH, "check_molmo_realworld_cleanup_result")
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
    checker = _load_module(CHECKER_PATH, "check_molmo_realworld_cleanup_result")
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
    checker = _load_module(CHECKER_PATH, "check_molmo_realworld_cleanup_result")
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


def test_checker_rejects_stale_prebuilt_map_bundle_for_isaac_scene_index(
    tmp_path: Path,
) -> None:
    checker = _load_module(CHECKER_PATH, "check_molmo_realworld_cleanup_result")
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
    checker = _load_module(CHECKER_PATH, "check_molmo_realworld_cleanup_result")
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
    checker = _load_module(CHECKER_PATH, "check_molmo_realworld_cleanup_result")
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
    checker = _load_module(CHECKER_PATH, "check_molmo_realworld_cleanup_result")
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
    checker = _load_module(CHECKER_PATH, "check_molmo_realworld_cleanup_result")
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
    checker = _load_module(CHECKER_PATH, "check_molmo_realworld_cleanup_result")
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
    checker = _load_module(CHECKER_PATH, "check_molmo_realworld_cleanup_result")
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
    checker = _load_module(CHECKER_PATH, "check_molmo_realworld_cleanup_result")
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
    checker = _load_module(CHECKER_PATH, "check_molmo_realworld_cleanup_result")
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
    checker = _load_module(CHECKER_PATH, "check_molmo_realworld_cleanup_result")
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
    checker = _load_module(CHECKER_PATH, "check_molmo_realworld_cleanup_result")
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
    checker = _load_module(CHECKER_PATH, "check_molmo_realworld_cleanup_result")
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
    checker = _load_module(CHECKER_PATH, "check_molmo_realworld_cleanup_result")
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
    checker = _load_module(CHECKER_PATH, "check_molmo_realworld_cleanup_result")
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
    checker = _load_module(CHECKER_PATH, "check_molmo_realworld_cleanup_result")
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
    checker = _load_module(CHECKER_PATH, "check_molmo_realworld_cleanup_result")
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
    checker = _load_module(CHECKER_PATH, "check_molmo_realworld_cleanup_result")
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
    checker = _load_module(CHECKER_PATH, "check_molmo_realworld_cleanup_result")
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
    checker = _load_module(CHECKER_PATH, "check_molmo_realworld_cleanup_result")
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
    checker = _load_module(CHECKER_PATH, "check_molmo_realworld_cleanup_result")

    data = demo.run_household_world_episode(output_dir=tmp_path, seed=7)
    _add_isaac_robot_view_step(
        data,  # type: ignore[arg-type]
        tmp_path,
        capture_method="isaac_lab_camera_rgb_semantic_pose_robot_views",
        semantic_pose_state_refreshed=True,
        head_camera_equivalent=True,
    )
    data["view_variant"] = MOLMOSPACES_ROBOT_VIEW_VARIANT

    checker._assert_result(
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
    checker = _load_module(CHECKER_PATH, "check_molmo_realworld_cleanup_result")

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
        checker._assert_result(
            data,
            tmp_path,
            expect_task=None,
            expect_backend="api_semantic_synthetic",
            min_generated_mess_count=0,
            allow_partial_cleanup=True,
            require_robot_head_camera_fpv=True,
        )


def test_checker_rejects_canonical_free_camera_when_head_camera_required(
    tmp_path: Path,
) -> None:
    demo = _load_module(DEMO_PATH, "molmospaces_realworld_cleanup")
    checker = _load_module(CHECKER_PATH, "check_molmo_realworld_cleanup_result")

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
        checker._assert_result(
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
    checker = _load_module(CHECKER_PATH, "check_molmo_realworld_cleanup_result")

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
        checker._assert_result(
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
    checker = _load_module(CHECKER_PATH, "check_molmo_realworld_cleanup_result")
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
    checker = _load_module(CHECKER_PATH, "check_molmo_realworld_cleanup_result")
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
    checker = _load_module(CHECKER_PATH, "check_molmo_realworld_cleanup_result")
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
    checker = _load_module(CHECKER_PATH, "check_molmo_realworld_cleanup_result")
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
    checker = _load_module(CHECKER_PATH, "check_molmo_realworld_cleanup_result")
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
    checker = _load_module(CHECKER_PATH, "check_molmo_realworld_cleanup_result")

    count = checker._post_place_observe_count_allowing_public_state_queries(
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
    checker = _load_module(CHECKER_PATH, "check_molmo_realworld_cleanup_result")

    result = demo.run_household_world_episode(output_dir=tmp_path, seed=7)
    result["cleanup_policy_trace"]["loop_style"] = "survey_first_cleanup_loop"
    result["cleanup_policy_trace"]["first_cleanup_before_full_survey"] = False

    checker._assert_result(
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
    checker = _load_module(CHECKER_PATH, "check_molmo_realworld_cleanup_result")

    result = demo.run_household_world_episode(output_dir=tmp_path, seed=7)
    result["agent_view"]["policy_view"]["chase_camera_policy_input"] = True
    result["real_robot_readiness"]["policy_view_chase_excluded"] = False

    with pytest.raises(AssertionError):
        checker._assert_result(
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
    checker = _load_module(CHECKER_PATH, "check_molmo_realworld_cleanup_result")
    run_result = _b1_robot_consumption_run_result(tmp_path, verified=True)

    checker._assert_b1_robot_consumption_proof(run_result, tmp_path)
    with pytest.raises(AssertionError):
        checker._assert_real_robot_alignment(run_result, tmp_path, "Nav2 Map Bundle")


def test_checker_rejects_b1_robot_consumption_without_verified_navigation(
    tmp_path: Path,
) -> None:
    checker = _load_module(CHECKER_PATH, "check_molmo_realworld_cleanup_result")
    run_result = _b1_robot_consumption_run_result(tmp_path, verified=False)

    with pytest.raises(AssertionError):
        checker._assert_b1_robot_consumption_proof(run_result, tmp_path)


def test_checker_rejects_b1_robot_consumption_without_manifest(
    tmp_path: Path,
) -> None:
    checker = _load_module(CHECKER_PATH, "check_molmo_realworld_cleanup_result")
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
    checker = _load_module(CHECKER_PATH, "check_molmo_realworld_cleanup_result")
    run_result = _b1_robot_consumption_run_result(tmp_path, verified=True)
    manifest_path = tmp_path / "b1_robot_consumption_manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["navigation"]["navigation_artifact"] = "wrong.json"
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")

    with pytest.raises(AssertionError):
        checker._assert_b1_robot_consumption_proof(run_result, tmp_path)


def test_checker_rejects_too_small_generated_mess_set(tmp_path: Path) -> None:
    demo = _load_module(DEMO_PATH, "molmospaces_realworld_cleanup")
    checker = _load_module(CHECKER_PATH, "check_molmo_realworld_cleanup_result")

    result = demo.run_household_world_episode(output_dir=tmp_path, seed=7)

    with pytest.raises(AssertionError):
        checker._assert_result(
            result,
            tmp_path,
            expect_task=None,
            expect_backend="api_semantic_synthetic",
            min_generated_mess_count=6,
        )


def test_checker_accepts_realworld_mcp_smoke_policy(tmp_path: Path) -> None:
    smoke = _load_module(SMOKE_PATH, "run_molmo_realworld_agent_mcp_smoke")
    checker = _load_module(CHECKER_PATH, "check_molmo_realworld_cleanup_result")

    result = smoke.run_smoke(output_dir=tmp_path, seed=7)

    checker._assert_result(
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


def test_checker_accepts_openclaw_minimum_gate(tmp_path: Path) -> None:
    smoke = _load_module(SMOKE_PATH, "run_molmo_realworld_agent_mcp_smoke")
    checker = _load_module(CHECKER_PATH, "check_molmo_realworld_cleanup_result")

    result = smoke.run_smoke(output_dir=tmp_path, seed=7, policy="openclaw_agent")

    checker._assert_result(
        result,
        tmp_path,
        expect_task=None,
        expect_backend="api_semantic_synthetic",
        expect_policy="openclaw_agent",
        expect_mcp_server="household_world",
        min_generated_mess_count=5,
        require_agent_driven=True,
        require_openclaw_minimum=True,
    )


def test_checker_openclaw_minimum_allows_partial_report_without_semantic_section(
    tmp_path: Path,
) -> None:
    smoke = _load_module(SMOKE_PATH, "run_molmo_realworld_agent_mcp_smoke")
    checker = _load_module(CHECKER_PATH, "check_molmo_realworld_cleanup_result")

    result = smoke.run_smoke(output_dir=tmp_path, seed=7, policy="openclaw_agent")
    result["semantic_substeps"] = []
    result["mess_restoration_rate"] = 0.0
    result["sweep_coverage_rate"] = 0.0
    result["disturbance_count"] = 99
    result["cleanup_status"] = "incomplete"
    report_path = tmp_path / "report.html"
    report_path.write_text(
        report_path.read_text(encoding="utf-8").replace("Semantic Substeps", "Partial Trace"),
        encoding="utf-8",
    )

    checker._assert_result(
        result,
        tmp_path,
        expect_task=None,
        expect_backend="api_semantic_synthetic",
        expect_policy="openclaw_agent",
        expect_mcp_server="household_world",
        min_generated_mess_count=5,
        require_agent_driven=True,
        require_openclaw_minimum=True,
    )


def test_checker_rejects_openclaw_minimum_without_public_tool_use(tmp_path: Path) -> None:
    smoke = _load_module(SMOKE_PATH, "run_molmo_realworld_agent_mcp_smoke")
    checker = _load_module(CHECKER_PATH, "check_molmo_realworld_cleanup_result")

    result = smoke.run_smoke(output_dir=tmp_path, seed=7, policy="openclaw_agent")
    result["tool_event_counts"] = {}

    with pytest.raises(AssertionError):
        checker._assert_result(
            result,
            tmp_path,
            expect_task=None,
            expect_backend="api_semantic_synthetic",
            expect_policy="openclaw_agent",
            expect_mcp_server="household_world",
            min_generated_mess_count=5,
            require_agent_driven=True,
            require_openclaw_minimum=True,
        )


def test_checker_rejects_openclaw_minimum_for_non_openclaw_policy(tmp_path: Path) -> None:
    smoke = _load_module(SMOKE_PATH, "run_molmo_realworld_agent_mcp_smoke")
    checker = _load_module(CHECKER_PATH, "check_molmo_realworld_cleanup_result")

    result = smoke.run_smoke(output_dir=tmp_path, seed=7)

    with pytest.raises(AssertionError):
        checker._assert_result(
            result,
            tmp_path,
            expect_task=None,
            expect_backend="api_semantic_synthetic",
            expect_policy=None,
            expect_mcp_server="household_world",
            min_generated_mess_count=5,
            require_agent_driven=True,
            require_openclaw_minimum=True,
        )


def test_checker_rejects_scene_objects_in_realworld_trace(tmp_path: Path) -> None:
    smoke = _load_module(SMOKE_PATH, "run_molmo_realworld_agent_mcp_smoke")
    checker = _load_module(CHECKER_PATH, "check_molmo_realworld_cleanup_result")

    result = smoke.run_smoke(output_dir=tmp_path, seed=7)
    trace_path = tmp_path / "trace.jsonl"
    with trace_path.open("a", encoding="utf-8") as fp:
        fp.write('{"tool": "scene_objects", "event": "request"}\n')

    with pytest.raises(AssertionError):
        checker._assert_result(
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
    checker = _load_module(CHECKER_PATH, "check_molmo_realworld_cleanup_result")

    result = smoke.run_smoke(output_dir=tmp_path, seed=7)
    result["agent_diagnostics"]["semantic_order_errors"] = 1
    result["agent_diagnostics"]["semantic_order_unrecovered_errors"] = 1

    with pytest.raises(AssertionError):
        checker._assert_result(
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
    checker = _load_module(CHECKER_PATH, "check_molmo_realworld_cleanup_result")

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

    checker._assert_result(
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
    checker = _load_module(CHECKER_PATH, "check_molmo_realworld_cleanup_result")

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

    checker._assert_result(
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
    checker = _load_module(CHECKER_PATH, "check_molmo_realworld_cleanup_result")

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
        checker._assert_result(
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
    checker = _load_module(CHECKER_PATH, "check_molmo_realworld_cleanup_result")

    result = smoke.run_smoke(output_dir=tmp_path, seed=7)

    checker._assert_result(
        result,
        tmp_path,
        expect_task=None,
        expect_backend="api_semantic_synthetic",
        expect_policy="household_contract_smoke_agent",
        expect_mcp_server="household_world",
        min_generated_mess_count=5,
        require_agent_driven=True,
        require_clean_agent_run=True,
        require_advisory_scoring=True,
        min_semantic_accepted_count=4,
    )


def test_checker_can_require_raw_fpv_observation_artifacts(tmp_path: Path) -> None:
    demo = _load_module(DEMO_PATH, "molmospaces_realworld_cleanup")
    checker = _load_module(CHECKER_PATH, "check_molmo_realworld_cleanup_result")

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

    checker._assert_result(
        result,
        tmp_path,
        expect_task=None,
        expect_backend="api_semantic_synthetic",
        min_generated_mess_count=5,
        require_robot_views=True,
        require_raw_fpv_observations=True,
    )


def test_checker_accepts_live_raw_fpv_map_build_shape(tmp_path: Path) -> None:
    demo = _load_module(DEMO_PATH, "molmospaces_realworld_cleanup")
    checker = _load_module(CHECKER_PATH, "check_molmo_realworld_cleanup_result")

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

    checker._assert_result(
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
    checker = _load_module(CHECKER_PATH, "check_molmo_realworld_cleanup_result")

    result = smoke.run_smoke(
        output_dir=tmp_path,
        seed=7,
        perception_mode=CAMERA_MODEL_POLICY_MODE,
    )

    checker._assert_result(
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
    checker = _load_module(CHECKER_PATH, "check_molmo_realworld_cleanup_result")

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
        checker._assert_result(
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
    checker = _load_module(CHECKER_PATH, "check_molmo_realworld_cleanup_result")

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
        checker._assert_result(
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
    checker = _load_module(CHECKER_PATH, "check_molmo_realworld_cleanup_result")
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
    checker = _load_module(CHECKER_PATH, "check_molmo_realworld_cleanup_result")
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
    checker = _load_module(CHECKER_PATH, "check_molmo_realworld_cleanup_result")
    proof_path = _write_strict_planner_proof(tmp_path / "proof")
    cleanup_dir = tmp_path / "cleanup"

    result = demo.run_household_world_episode(
        output_dir=cleanup_dir,
        seed=7,
        planner_proof_run_result=proof_path,
    )

    assert result["primitive_provenance"] == "api_semantic"
    checker._assert_result(
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
    checker = _load_module(CHECKER_PATH, "check_molmo_realworld_cleanup_result")
    proof_path = _write_strict_planner_proof(tmp_path / "proof", steps_executed=1)
    cleanup_dir = tmp_path / "cleanup"

    result = demo.run_household_world_episode(
        output_dir=cleanup_dir,
        seed=7,
        planner_proof_run_result=proof_path,
    )

    with pytest.raises(AssertionError):
        checker._assert_result(
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
    checker = _load_module(CHECKER_PATH, "check_molmo_realworld_cleanup_result")
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
    checker._assert_result(
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
    checker = _load_module(CHECKER_PATH, "check_molmo_realworld_cleanup_result")
    checker._assert_result(
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
    checker = _load_module(CHECKER_PATH, "check_molmo_realworld_cleanup_result")
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
    checker._assert_result(
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
    checker = _load_module(CHECKER_PATH, "check_molmo_realworld_cleanup_result")
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
        checker._assert_result(
            result,
            cleanup_dir,
            expect_task=None,
            expect_backend="api_semantic_synthetic",
            min_generated_mess_count=5,
            require_planner_cleanup_bridge_ready=True,
        )


def test_checker_accepts_blocked_cleanup_primitive_gate(tmp_path: Path) -> None:
    demo = _load_module(DEMO_PATH, "molmospaces_realworld_cleanup")
    checker = _load_module(CHECKER_PATH, "check_molmo_realworld_cleanup_result")

    result = demo.run_household_world_episode(output_dir=tmp_path, seed=7)

    checker._assert_result(
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
    checker = _load_module(CHECKER_PATH, "check_molmo_realworld_cleanup_result")

    result = demo.run_household_world_episode(output_dir=tmp_path, seed=7)

    with pytest.raises(AssertionError):
        checker._assert_result(
            result,
            tmp_path,
            expect_task=None,
            expect_backend="api_semantic_synthetic",
            min_generated_mess_count=5,
            require_planner_backed_cleanup_primitives=True,
        )


def test_checker_rejects_missing_required_planner_proof(tmp_path: Path) -> None:
    demo = _load_module(DEMO_PATH, "molmospaces_realworld_cleanup")
    checker = _load_module(CHECKER_PATH, "check_molmo_realworld_cleanup_result")

    result = demo.run_household_world_episode(output_dir=tmp_path, seed=7)

    with pytest.raises(AssertionError):
        checker._assert_result(
            result,
            tmp_path,
            expect_task=None,
            expect_backend="api_semantic_synthetic",
            min_generated_mess_count=5,
            require_planner_proof_attachment=True,
        )


def test_checker_rejects_raw_fpv_when_structured_detections_leak(tmp_path: Path) -> None:
    demo = _load_module(DEMO_PATH, "molmospaces_realworld_cleanup")
    checker = _load_module(CHECKER_PATH, "check_molmo_realworld_cleanup_result")

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
        checker._assert_result(
            result,
            tmp_path,
            expect_task=None,
            expect_backend="api_semantic_synthetic",
            min_generated_mess_count=5,
            require_raw_fpv_observations=True,
        )


def test_checker_can_require_camera_model_policy(tmp_path: Path) -> None:
    demo = _load_module(DEMO_PATH, "molmospaces_realworld_cleanup")
    checker = _load_module(CHECKER_PATH, "check_molmo_realworld_cleanup_result")

    result = demo.run_household_world_episode(
        output_dir=tmp_path,
        seed=7,
        perception_mode=CAMERA_MODEL_POLICY_MODE,
    )

    checker._assert_result(
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
    checker = _load_module(CHECKER_PATH, "check_molmo_realworld_cleanup_result")
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
    checker = _load_module(CHECKER_PATH, "check_molmo_realworld_cleanup_result")
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
    checker = _load_module(CHECKER_PATH, "check_molmo_realworld_cleanup_result")
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
    checker = _load_module(CHECKER_PATH, "check_molmo_realworld_cleanup_result")
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
    checker = _load_module(CHECKER_PATH, "check_molmo_realworld_cleanup_result")

    result = demo.run_household_world_episode(
        output_dir=tmp_path,
        seed=7,
        perception_mode=CAMERA_MODEL_POLICY_MODE,
    )
    observed_objects = agent_view_module.active_perception(result["agent_view"])["observed_objects"]
    observed_objects[0].pop("model_provenance")
    observed_objects[0].pop("producer_type")

    with pytest.raises(AssertionError):
        checker._assert_result(
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
    checker = _load_module(CHECKER_PATH, "check_molmo_realworld_cleanup_result")

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

    checker._assert_result(
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
    checker = _load_module(CHECKER_PATH, "check_molmo_realworld_cleanup_result")

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

    checker._assert_result(
        result,
        tmp_path,
        expect_task=None,
        expect_backend="api_semantic_synthetic",
        require_robot_views=True,
    )


def test_checker_openclaw_minimum_robot_views_allows_partial_visual_actions(
    tmp_path: Path,
) -> None:
    smoke = _load_module(SMOKE_PATH, "run_molmo_realworld_agent_mcp_smoke")
    checker = _load_module(CHECKER_PATH, "check_molmo_realworld_cleanup_result")

    result = smoke.run_smoke(output_dir=tmp_path, seed=7, policy="openclaw_agent")
    _add_molmospaces_robot_view_artifacts(result, tmp_path)
    result["robot_view_steps"] = [
        _robot_step("pick observed_001"),
        _robot_step("place observed_001"),
    ]

    checker._assert_result(
        result,
        tmp_path,
        expect_task=None,
        expect_backend="api_semantic_synthetic",
        expect_policy="openclaw_agent",
        expect_mcp_server="household_world",
        min_generated_mess_count=5,
        require_agent_driven=True,
        require_openclaw_minimum=True,
        require_robot_views=True,
    )


def test_checker_rejects_zero_pixel_focused_surface_action(tmp_path: Path) -> None:
    smoke = _load_module(SMOKE_PATH, "run_molmo_realworld_agent_mcp_smoke")
    checker = _load_module(CHECKER_PATH, "check_molmo_realworld_cleanup_result")

    result = smoke.run_smoke(output_dir=tmp_path, seed=7, policy="openclaw_agent")
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
        checker._assert_result(
            result,
            tmp_path,
            expect_task=None,
            expect_backend="api_semantic_synthetic",
            expect_policy="openclaw_agent",
            expect_mcp_server="household_world",
            min_generated_mess_count=5,
            require_agent_driven=True,
            require_openclaw_minimum=True,
            require_robot_views=True,
        )


def test_checker_accepts_authorized_source_fpv_evidence_for_weak_nav_view(
    tmp_path: Path,
) -> None:
    smoke = _load_module(SMOKE_PATH, "run_molmo_realworld_agent_mcp_smoke")
    checker = _load_module(CHECKER_PATH, "check_molmo_realworld_cleanup_result")

    result = smoke.run_smoke(output_dir=tmp_path, seed=7, policy="openclaw_agent")
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

    checker._assert_result(
        result,
        tmp_path,
        expect_task=None,
        expect_backend="api_semantic_synthetic",
        expect_policy="openclaw_agent",
        expect_mcp_server="household_world",
        min_generated_mess_count=5,
        require_agent_driven=True,
        require_openclaw_minimum=True,
        require_robot_views=True,
    )


def test_checker_rejects_weak_nav_view_without_authorized_source_fpv_evidence(
    tmp_path: Path,
) -> None:
    smoke = _load_module(SMOKE_PATH, "run_molmo_realworld_agent_mcp_smoke")
    checker = _load_module(CHECKER_PATH, "check_molmo_realworld_cleanup_result")

    result = smoke.run_smoke(output_dir=tmp_path, seed=7, policy="openclaw_agent")
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
        checker._assert_result(
            result,
            tmp_path,
            expect_task=None,
            expect_backend="api_semantic_synthetic",
            expect_policy="openclaw_agent",
            expect_mcp_server="household_world",
            min_generated_mess_count=5,
            require_agent_driven=True,
            require_openclaw_minimum=True,
            require_robot_views=True,
        )


def test_checker_allows_weak_fpv_when_verify_view_is_grounded(tmp_path: Path) -> None:
    smoke = _load_module(SMOKE_PATH, "run_molmo_realworld_agent_mcp_smoke")
    checker = _load_module(CHECKER_PATH, "check_molmo_realworld_cleanup_result")

    result = smoke.run_smoke(output_dir=tmp_path, seed=7, policy="openclaw_agent")
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

    checker._assert_result(
        result,
        tmp_path,
        expect_task=None,
        expect_backend="api_semantic_synthetic",
        expect_policy="openclaw_agent",
        expect_mcp_server="household_world",
        min_generated_mess_count=5,
        require_agent_driven=True,
        require_openclaw_minimum=True,
        require_robot_views=True,
    )


def test_checker_allows_weak_place_view_when_surface_evidence_is_grounded() -> None:
    checker = _load_module(CHECKER_PATH, "check_molmo_realworld_cleanup_result")

    checker._assert_focused_robot_step(
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
    checker = _load_module(CHECKER_PATH, "check_molmo_realworld_cleanup_result")

    result = smoke.run_smoke(output_dir=tmp_path, seed=7, policy="openclaw_agent")
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

    checker._assert_result(
        result,
        tmp_path,
        expect_task=None,
        expect_backend="api_semantic_synthetic",
        expect_policy="openclaw_agent",
        expect_mcp_server="household_world",
        min_generated_mess_count=5,
        require_agent_driven=True,
        require_openclaw_minimum=True,
        require_robot_views=True,
    )


def test_checker_rejects_agent_view_private_leak(tmp_path: Path) -> None:
    demo = _load_module(DEMO_PATH, "molmospaces_realworld_cleanup")
    checker = _load_module(CHECKER_PATH, "check_molmo_realworld_cleanup_result")

    result = demo.run_household_world_episode(output_dir=tmp_path, seed=7)
    result["agent_view"]["generated_mess_set"] = ["leak"]

    with pytest.raises(AssertionError):
        checker._assert_result(
            result,
            tmp_path,
            expect_task=None,
            expect_backend="api_semantic_synthetic",
        )


def _external_visual_grounding_checker_result(*, overlay: str) -> dict[str, object]:
    pipeline = {
        "schema": "visual_grounding_pipeline_v1",
        "pipeline_id": "grounding-dino",
        "status": "ok",
        "stages": [
            {
                "stage": "proposer",
                "producer_id": "grounding-dino",
                "model_id": "fake",
                "status": "ok",
                "latency_ms": 1,
            }
        ],
        "candidate_count": 1,
        "unresolved_count": 0,
        "duplicate_rate": 0.0,
    }
    observation = {
        "schema": "model_declared_observation_v1",
        "declaration_id": "declared_001",
        "object_id": "observed_001",
        "source_observation_id": "raw_fpv_001",
        "waypoint_id": "wp_kitchen_01",
        "room_id": "kitchen",
        "category": "dish",
        "target_fixture_id": "sink_01",
        "target_fixture_category": "sink",
        "source_fixture_id": "counter_01",
        "evidence_note": "fake dish",
        "image_region": {"type": "bbox", "value": [0.1, 0.2, 0.3, 0.4]},
        "confidence": 0.8,
        "producer_type": "external_visual_grounding_service",
        "producer_id": "grounding-dino",
        "grounding_status": "resolved",
        "grounding_confidence": 0.8,
        "grounding_basis": "single public camera-context object matched",
        "recovery_hint": "",
        "target_plausibility": {"status": "plausible"},
        "actionability_status": "actionable",
        "private_truth_included": False,
        "visual_grounding_pipeline": pipeline,
        "visual_grounding_overlay": overlay,
    }
    event = {
        "schema": "model_declared_observations_v1",
        "perception_mode": CAMERA_MODEL_POLICY_MODE,
        "observation_id": "raw_fpv_001",
        "waypoint_id": "wp_kitchen_01",
        "room_id": "kitchen",
        "producer_type": "external_visual_grounding_service",
        "producer_id": "grounding-dino",
        "candidate_count": 1,
        "registered_observed_handles": ["observed_001"],
        "visual_grounding_pipeline": pipeline,
        "private_truth_included": False,
    }
    return {
        "perception_mode": CAMERA_MODEL_POLICY_MODE,
        "raw_fpv_observations": [
            {
                "observation_id": "raw_fpv_001",
                "waypoint_id": "wp_kitchen_01",
                "room_id": "kitchen",
                "image_artifacts": {"fpv": "robot_views/raw_fpv_001.jpg"},
            }
        ],
        "camera_model_policy_evidence": {
            "schema": "camera_model_policy_v1",
            "perception_mode": CAMERA_MODEL_POLICY_MODE,
            "enabled": True,
            "model_provenance": "external_visual_grounding_service",
            "visual_grounding_pipeline_id": "grounding-dino",
            "visual_grounding_pipeline_ids": ["grounding-dino"],
            "visual_grounding_failure_count": 0,
            "event_count": 1,
            "candidate_count": 1,
            "unresolved_count": 0,
            "duplicate_rate": 0.0,
            "events": [event],
            "private_truth_included": False,
        },
        "model_declared_observation_evidence": {
            "schema": "model_declared_observations_v1",
            "observation_count": 1,
            "resolved_count": 1,
            "acted_count": 0,
            "observations": [observation],
            "private_truth_included": False,
        },
        "model_declared_observations": [observation],
        "tool_event_counts": {"declare_visual_candidates:request": 1},
    }


def _write_agibot_map_build_fixture(tmp_path: Path) -> Path:
    _require_agibot_sdk_runner()
    run_dir = tmp_path / "agibot-map-build"
    server = _make_common_agibot_map_build_server(
        run_dir=run_dir,
        context_json=AGIBOT_CONTEXT_FIXTURE,
    )
    try:
        server.call_tool("metric_map")
        server.call_tool("navigate_to_waypoint", waypoint_id="wp_sofa_front")
        server.call_tool("observe")
        server.call_tool("done", reason="checker fixture complete")
    finally:
        server.close()
    return run_dir


def _make_common_agibot_map_build_server(*, run_dir: Path, context_json: Path):
    contract = AgibotHouseholdBackend(
        run_dir=run_dir,
        context_json=context_json,
        visual_grounding_pipeline_id="grounding-dino",
    )
    return make_household_world_mcp(
        run_dir=run_dir,
        contract=contract,
        map_bundle_dir=PREBUILT_BUNDLE,
        task_intent="map-build",
        evidence_lane=None,
        required_capability_profiles=(HOUSEHOLD_WORLD_PROFILE, HOUSEHOLD_EPISODE_PROFILE),
    )


def _promote_agibot_fixture_to_hardware_shape(
    data: dict[str, object],
    run_dir: Path,
) -> None:
    pipeline = {
        "schema": "visual_grounding_pipeline_v1",
        "pipeline_id": "grounding-dino",
        "status": "ok",
        "stages": [
            {
                "stage": "grounding_dino",
                "producer_id": "grounding-dino",
                "model_id": "grounding-dino",
                "status": "ok",
                "latency_ms": 1,
            }
        ],
        "candidate_count": 1,
        "unresolved_count": 0,
        "duplicate_rate": 0.0,
        "auth_mode": "none",
    }
    image_rel = "subphases/02-observe/head_color.jpg"
    image_path = run_dir / image_rel
    image_path.parent.mkdir(parents=True, exist_ok=True)
    Image.new("RGB", (20, 10), (240, 240, 240)).save(image_path)

    data["cleanup_status"] = "physical_agibot_map_build_complete"
    data["completion_status"] = "physical_agibot_map_build_complete"
    data["primitive_provenance"] = "agibot_gdk_normal_navi"
    data["sweep_coverage_rate"] = 1.0
    readiness = data["real_robot_readiness"]
    assert isinstance(readiness, dict)
    readiness.update(
        {
            "status": "physical_agibot_map_build_complete",
            "movement_enabled": True,
            "navigation_perception_ready": True,
            "human_takeover_stop": False,
            "inspection_waypoint_attempt_count": 1,
            "inspection_waypoint_total": 1,
            "reached_waypoint_count": 1,
            "observed_reached_waypoint_count": 1,
            "observed_reached_waypoint_rate": 1.0,
            "observed_waypoint_rate": 1.0,
        }
    )

    raw = data["raw_fpv_observations"]
    assert isinstance(raw, list)
    raw[0].update(
        {
            "ok": True,
            "status": "ok",
            "camera": "head_color",
            "primitive_provenance": "agibot_gdk_head_color_camera",
            "image_artifacts": {"fpv": image_rel},
        }
    )
    agent_view = data["agent_view"]
    assert isinstance(agent_view, dict)
    agent_view_module.active_perception(agent_view)["raw_fpv_observations"] = raw

    camera_policy = data["camera_model_policy_evidence"]
    assert isinstance(camera_policy, dict)
    camera_policy.update(
        {
            "event_count": 1,
            "candidate_count": 1,
            "visual_grounding_failure_count": 0,
            "events": [
                {
                    "observation_id": raw[0]["observation_id"],
                    "room_id": "",
                    "candidate_count": 1,
                    "registered_observed_handles": [],
                    "visual_grounding_pipeline": pipeline,
                }
            ],
        }
    )
    agent_view_module.active_perception(agent_view)["camera_model_policy_evidence"] = camera_policy

    trace = data["cleanup_policy_trace"]
    assert isinstance(trace, dict)
    events = trace["events"]
    assert isinstance(events, list)
    for event in events:
        if isinstance(event, dict) and event.get("decision") == "visit_public_waypoint":
            event["primitive_provenance"] = "agibot_gdk_normal_navi"
            event["status"] = "ok"
        if isinstance(event, dict) and event.get("decision") == "observe_head_color":
            event["primitive_provenance"] = "agibot_gdk_head_color_camera"
            event["status"] = "ok"


def _robot_step(action: str) -> dict[str, object]:
    return {
        "action": action,
        "room_outline_count": 1,
        "views": {
            "fpv": "robot_views/step.fpv.png",
            "chase": "robot_views/step.chase.png",
            "topdown": "robot_views/step.topdown.png",
            "verify": "robot_views/step.verify.png",
        },
        "focus": {
            "has_focus": True,
            "fpv_visibility": {"status": "ok"},
            "visibility": {"status": "ok"},
        },
    }


def _scene_context_robot_step(action: str) -> dict[str, object]:
    return {
        "action": action,
        "room_outline_count": 1,
        "views": {
            "fpv": "robot_views/scene.fpv.png",
            "chase": "robot_views/scene.chase.png",
            "topdown": "robot_views/scene.topdown.png",
            "verify": "robot_views/scene.verify.png",
        },
        "focus": {
            "has_focus": False,
            "fpv_visibility": {"status": "ok"},
            "visibility": {"status": "ok"},
        },
    }


def _add_molmospaces_robot_view_artifacts(
    result: dict[str, object],
    base: Path,
    *,
    prefix: str = "step",
) -> None:
    robot_views = base / "robot_views"
    robot_views.mkdir()
    for key in ROBOT_VIEW_KEYS:
        (robot_views / f"{prefix}.{key}.png").write_bytes(b"placeholder")
    _insert_robot_timeline_before_score(base / "report.html")
    result["view_variant"] = MOLMOSPACES_ROBOT_VIEW_VARIANT
    artifacts = result.setdefault("artifacts", {})
    assert isinstance(artifacts, dict)
    artifacts["robot_views"] = str(robot_views)


def _trace_response(tool: str, response: dict[str, object]) -> dict[str, object]:
    return {"event": "response", "tool": tool, "response": response}


def _write_trace(path: Path, events: list[dict[str, object]]) -> None:
    path.write_text(
        "".join(json.dumps(event, sort_keys=True) + "\n" for event in events),
        encoding="utf-8",
    )


def _isaac_selected_scene_bindings() -> dict[str, object]:
    return {
        "schema": "isaac_public_scene_bindings_v1",
        "status": "selected_bound",
        "source": "usd_stage_traversal",
        "selected_object_count": 1,
        "selected_target_receptacle_count": 1,
        "selected_object_bound_count": 1,
        "selected_target_receptacle_bound_count": 1,
        "selected_object_bindings": {
            "mug_01": {
                "status": "bound",
                "usd_handle": "mug_01",
                "usd_prim_path": "/World/Objects/mug_01",
                "match_strategy": "exact_public_id",
                "index_source": "usd_stage_traversal",
            }
        },
        "selected_target_receptacle_bindings": {
            "sink_01": {
                "status": "bound",
                "usd_handle": "sink_01",
                "usd_prim_path": "/World/Receptacles/sink_01",
                "match_strategy": "exact_public_id",
                "index_source": "usd_stage_traversal",
            }
        },
        "blockers": [],
        "private_manifest_exposed_to_agent": False,
    }


def _isaac_runtime_result(
    base: Path,
    scene_bindings: dict[str, object],
    *,
    segmentation: dict[str, object] | None = None,
    semantic_pose_state: dict[str, object] | None = None,
) -> dict[str, object]:
    if segmentation is None:
        segmentation = {
            "status": "blocked_capability",
            "agent_facing": False,
            "no_simulator_label_fallback": True,
        }
    result: dict[str, object] = {
        "backend": "isaaclab_subprocess",
        "artifacts": {"isaac_scene_index": str(base / "isaac_scene_index.json")},
        "isaac_runtime": {
            "runtime": {"primitive_provenance": "isaac_semantic_pose"},
            "object_index": {"mug_01": {"usd_prim_path": "/World/Objects/mug_01"}},
            "object_index_count": 1,
            "receptacle_index": {
                "sink_01": {"usd_prim_path": "/World/Receptacles/sink_01"},
            },
            "receptacle_index_count": 1,
            "scene_binding_diagnostics": scene_bindings,
            "scene_index_artifact": str(base / "isaac_scene_index.json"),
            "segmentation": segmentation,
        },
    }
    if semantic_pose_state is not None:
        trace_path = base / "trace.jsonl"
        _write_trace(trace_path, _isaac_semantic_pose_trace_events(semantic_pose_state))
        result["artifacts"]["trace"] = str(trace_path)
        result["primitive_provenance"] = "isaac_semantic_pose"
        result["manipulation_evidence"] = {
            "primitive_provenance": "isaac_semantic_pose",
            "isaac_semantic_pose_edits": True,
            "planner_backed": False,
            "physical_robot": False,
        }
        result["semantic_substeps"] = [
            {
                "steps": [
                    {
                        "phase": "pick",
                        "status": "ok",
                        "primitive_provenance": "isaac_semantic_pose",
                        "planner_backed": False,
                        "physical_robot": False,
                    },
                    {
                        "phase": "place",
                        "status": "ok",
                        "primitive_provenance": "isaac_semantic_pose",
                        "planner_backed": False,
                        "physical_robot": False,
                    },
                ]
            }
        ]
        result["isaac_runtime"]["semantic_pose_state"] = semantic_pose_state
    return result


def _isaac_real_runtime_diagnostics() -> dict[str, object]:
    return {
        "runtime_mode": "real",
        "python_version": "3.12.3",
        "isaac_sim_version": "unit-isaacsim",
        "isaac_lab_version": "unit-isaaclab",
        "cuda_available": True,
        "gpu_name": "unit-gpu",
        "gpu_vram_mb": 16384,
        "renderer_mode": "isaac_lab_headless_rtx",
        "camera_resolution": [540, 360],
        "primitive_provenance": "isaac_semantic_pose",
        "rendering": {
            "status": "real_rendering_proven",
            "real_rendering_proven": True,
            "placeholder_visuals": False,
        },
    }


def _add_isaac_loaded_scene(
    data: dict[str, object],
    base: Path,
    *,
    manual_editor_steps_required: bool = False,
    loaded_asset_kind: str = "local_scene_usd",
) -> Path:
    scene_usd = base / "loaded_scene.usda"
    scene_usd.write_text("#usda 1.0\n", encoding="utf-8")
    isaac_runtime = data["isaac_runtime"]
    assert isinstance(isaac_runtime, dict)
    isaac_runtime["scene_usd"] = str(scene_usd)
    isaac_runtime["scene_load"] = {
        "status": "loaded",
        "usd_stage_loaded": True,
        "scene_usd": str(scene_usd),
        "loaded_asset_kind": loaded_asset_kind,
        "manual_editor_steps_required": manual_editor_steps_required,
    }
    return scene_usd


def _minimal_agent_view(
    *,
    base_metric_map: dict[str, object] | None = None,
    runtime_metric_map: dict[str, object] | None = None,
    perception_mode: str = "visible_object_detections",
    structured_detections_available: bool = True,
    observed_objects: list[dict[str, object]] | None = None,
    raw_fpv_observations: list[dict[str, object]] | None = None,
    camera_model_policy_evidence: dict[str, object] | None = None,
    model_declared_observations: list[dict[str, object]] | None = None,
    model_declared_observation_evidence: dict[str, object] | None = None,
) -> dict[str, object]:
    base_metric_map = base_metric_map or _minimal_base_metric_map()
    runtime_metric_map = runtime_metric_map or {}
    return agent_view_module.build_agent_view(
        contract=REALWORLD_CONTRACT,
        perception_mode=perception_mode,
        detection_exposure_policy="sanitized_visible_object_detections",
        structured_detections_available=structured_detections_available,
        base_metric_map=base_metric_map,
        runtime_metric_map=runtime_metric_map,
        observed_objects=observed_objects or [],
        raw_fpv_observations=raw_fpv_observations or [],
        camera_model_policy_evidence=camera_model_policy_evidence or {},
        model_declared_observations=model_declared_observations or [],
        model_declared_observation_evidence=model_declared_observation_evidence or {},
        policy_view={
            "schema": "realworld_cleanup_policy_view_v1",
            "allowed_inputs": ["base_metric_map", "runtime_metric_map"],
            "chase_camera_policy_input": False,
            "excluded_report_only_views": ["chase_camera"],
        },
        cleanup_worklist={
            "schema": "cleanup_worklist_v1",
            "waypoint_source": "generated_exploration_candidate",
            "objects": [],
        },
        observed_waypoint_ids=[],
        public_tool_names=[],
        forbidden_keys=frozenset(forbidden_agent_view_keys()),
    )


def _minimal_base_metric_map() -> dict[str, object]:
    return {
        "schema": "real_robot_map_bundle_v1",
        "rooms": [{"room_id": "room_1", "label": "Room 1"}],
        "room_category_hints": [],
        "inspection_waypoints": [],
    }


def _add_isaac_scene_index_map_context(data: dict[str, object], base: Path) -> None:
    scenario_id = "isaac-scene-index-procthor-10k-val-1-7-1"
    map_id = f"{scenario_id}_base_metric_map"
    map_bundle = {
        "schema": "nav2_map_bundle_v1",
        "environment_id": scenario_id,
        "map_id": map_id,
        "map_version": "base-metric-map-v1",
        "source_provenance": "molmospaces_base_metric_map",
        "robot_profile_id": "rby1m",
        "parameter_hash": "unit-scene-index-map-context",
    }
    metric_map = {
        "schema": "real_robot_map_bundle_v1",
        "map_bundle": dict(map_bundle),
        "rooms": [_isaac_scene_index_room()],
    }
    runtime_map = {
        "schema": "runtime_metric_map_v1",
        "static_map": {
            "map_bundle": dict(map_bundle),
            "rooms": [_isaac_scene_index_room()],
            "scene_index_fixture_overlay": {
                "enabled": True,
                "source": "isaac_scene_index",
                "fixture_count": 1,
            },
        },
    }
    data["scenario_id"] = scenario_id
    isaac_runtime = data["isaac_runtime"]
    assert isinstance(isaac_runtime, dict)
    isaac_runtime["scenario_source"] = "isaac_scene_index"
    data["agent_view"] = _minimal_agent_view(
        base_metric_map=metric_map,
        runtime_metric_map=runtime_map,
    )
    data["runtime_metric_map"] = runtime_map
    semantics_path = base / "map_bundle" / "semantics.json"
    semantics_path.parent.mkdir(parents=True, exist_ok=True)
    semantics_path.write_text(
        json.dumps(
            {
                "schema": "nav2_cleanup_semantics_v1",
                "environment_id": scenario_id,
                "map_id": map_id,
                "map_version": "base-metric-map-v1",
                "rooms": [_isaac_scene_index_room()],
                "fixtures": [],
                "inspection_waypoints": [],
                "driveable_ways": [],
            }
        ),
        encoding="utf-8",
    )
    data["nav2_map_bundle"] = {
        "schema": "nav2_map_bundle_snapshot_v1",
        "environment_id": scenario_id,
        "map_id": map_id,
        "map_version": "base-metric-map-v1",
        "source_provenance": "molmospaces_base_metric_map",
        "snapshot_complete": True,
        "artifact_paths": {"semantics_json": "map_bundle/semantics.json"},
        "artifact_hashes": {"semantics_json": "0" * 64},
    }


def _add_isaac_scene_index_base_metric_map_context(data: dict[str, object], base: Path) -> None:
    scenario_id = "isaac-scene-index-procthor-10k-val-1-7-1"
    map_id = f"{scenario_id}_base_metric_map"
    public_room = _isaac_scene_index_room()
    room_category_hints = [_room_category_hint(public_room)]
    map_bundle = {
        "schema": "nav2_map_bundle_v1",
        "environment_id": scenario_id,
        "map_id": map_id,
        "map_version": "base-metric-map-v1",
        "source_provenance": "molmospaces_base_metric_map",
        "robot_profile_id": "rby1m",
        "parameter_hash": "unit-scene-index-base-metric-map-context",
    }
    candidates = [
        {
            "waypoint_id": "generated_exploration_001",
            "waypoint_source": "generated_exploration_candidate",
            "purpose": "base_metric_map_exploration",
            "x": 2.99,
            "y": 4.983,
            "room_id": "room_2",
            "room_label": "Room 2",
            "candidate_provenance": {
                "source": "public_occupancy_free_space",
                "source_room_hidden": False,
                "source_room_label_available": True,
                "source_fixtures_hidden": True,
                "source_waypoint_hidden": True,
            },
        },
        {
            "waypoint_id": "generated_exploration_002",
            "waypoint_source": "generated_exploration_candidate",
            "purpose": "base_metric_map_exploration",
            "x": 7.973,
            "y": 2.512,
            "room_id": "room_2",
            "room_label": "Room 2",
            "candidate_provenance": {
                "source": "public_occupancy_free_space",
                "source_room_hidden": False,
                "source_room_label_available": True,
                "source_fixtures_hidden": True,
                "source_waypoint_hidden": True,
            },
        },
    ]
    metric_map = {
        "schema": "real_robot_map_bundle_v1",
        "map_bundle": dict(map_bundle),
        "rooms": [public_room],
        "room_category_hints": room_category_hints,
        "driveable_ways": [],
        "base_metric_map": {"enabled": True},
        "inspection_waypoints": list(candidates),
        "generated_exploration_candidates": list(candidates),
    }
    runtime_map = {
        "schema": "runtime_metric_map_v1",
        "source_map_mutated": False,
        "static_map": {
            "map_bundle": dict(map_bundle),
            "rooms": [public_room],
            "fixtures": [],
            "driveable_ways": [],
            "generated_exploration_candidates": list(candidates),
            "inspection_waypoints": list(candidates),
        },
        "generated_exploration_candidates": list(candidates),
        "public_semantic_anchors": [
            {
                "anchor_id": "anchor_waypoint_generated_exploration_001",
                "anchor_type": "observation_waypoint",
                "waypoint_id": "generated_exploration_001",
            }
        ],
    }
    data["scenario_id"] = scenario_id
    isaac_runtime = data["isaac_runtime"]
    assert isinstance(isaac_runtime, dict)
    isaac_runtime["scenario_source"] = "isaac_scene_index"
    data["agent_view"] = _minimal_agent_view(
        base_metric_map=metric_map,
        runtime_metric_map=runtime_map,
    )
    data["runtime_metric_map"] = runtime_map
    semantics_path = base / "map_bundle" / "semantics.json"
    semantics_path.parent.mkdir(parents=True, exist_ok=True)
    semantics_path.write_text(
        json.dumps(
            {
                "schema": "nav2_cleanup_semantics_v1",
                "environment_id": scenario_id,
                "map_id": map_id,
                "map_version": "base-metric-map-v1",
                "rooms": [public_room],
                "fixtures": [],
                "inspection_waypoints": [],
                "driveable_ways": [],
            }
        ),
        encoding="utf-8",
    )
    data["nav2_map_bundle"] = {
        "schema": "nav2_map_bundle_snapshot_v1",
        "environment_id": scenario_id,
        "map_id": map_id,
        "map_version": "base-metric-map-v1",
        "source_provenance": "molmospaces_base_metric_map",
        "snapshot_complete": True,
        "artifact_paths": {"semantics_json": "map_bundle/semantics.json"},
        "artifact_hashes": {"semantics_json": "0" * 64},
    }


def _room_category_hint(room: dict[str, object]) -> dict[str, object]:
    return {
        "anchor_type": "room_area",
        "category": "room_area",
        "label": str(room["room_label"]),
        "room_id": str(room["room_id"]),
        "room_label": str(room["room_label"]),
        "waypoint_id": "generated_exploration_001",
        "affordances": ["navigate", "observe"],
        "classification_status": "map_prior",
        "confidence": 0.8,
        "aliases": [str(room["room_id"]), str(room["room_label"])],
        "producer_type": "base_metric_map",
    }


def _isaac_scene_index_room() -> dict[str, object]:
    return {
        "room_id": "room_2",
        "room_label": "Room 2",
        "fixture_count": 1,
        "polygon": [
            {"x": 0.0, "y": 0.0},
            {"x": 5.98, "y": 0.0},
            {"x": 5.98, "y": 9.966},
            {"x": 0.0, "y": 9.966},
        ],
        "scene_room_outline": {
            "room_id": "room_2",
            "center": [2.99, 4.983],
            "half_extents": [2.99, 4.983],
            "provenance": "isaac_usd_room_mesh_world_bounds",
            "usd_prim_path": "/val_1/Geometry/room_2_visual_0",
        },
    }


def _write_isaac_robot_view_images(
    base: Path,
    *,
    blank_key: str,
) -> tuple[Path, dict[str, str]]:
    view_dir = base / "isaac_robot_views"
    view_dir.mkdir(parents=True, exist_ok=True)
    views: dict[str, str] = {}
    for key in ("fpv", "chase", "topdown", "verify"):
        path = view_dir / f"step.{key}.png"
        if key == blank_key:
            _write_blank_png(path)
        else:
            _write_nonblank_png(path)
        views[key] = str(path.relative_to(base))
    return view_dir, views


def _ensure_isaac_robot_view_report(base: Path) -> Path:
    report = base / "report.html"
    if report.is_file():
        _insert_robot_timeline_before_score(report)
    else:
        report.write_text("<h2>Robot View Timeline</h2>", encoding="utf-8")
    return report


def _isaac_robot_view_pose() -> dict[str, object]:
    return {
        "schema": "cleanup_robot_pose_result_v1",
        "pose_source": "roboclaws_shared_scene_frame_support_pose",
        "x": 1.0,
        "y": 2.0,
        "z": 0.0,
        "theta": 0.0,
        "pose_request": {
            "schema": "cleanup_robot_pose_request_v1",
            "resolver": "roboclaws.cleanup_robot_pose.near_target_v1",
        },
    }


def _base_isaac_robot_view_steps(views: dict[str, str]) -> list[dict[str, object]]:
    return [
        {
            "action": "observe mug_01",
            "room_outline_count": 1,
            "views": views,
        },
        {
            "action": "observe sink_01",
            "room_outline_count": 1,
            "views": views,
        },
    ]


def _isaac_robot_view_provenance(
    views: dict[str, str],
    *,
    capture_method: str,
    semantic_pose_state_refreshed: bool,
    canonical_camera_control: bool,
    mounted_head_camera: bool,
    head_camera_equivalent: bool,
) -> dict[str, object]:
    provenance: dict[str, object] = {key: f"{capture_method}:{key}" for key in views}
    if canonical_camera_control:
        provenance["fpv"] = "isaac_lab_camera_rgb_canonical_robot_view:fpv"
        provenance["verify"] = "isaac_lab_camera_rgb_canonical_robot_view:verify"
    if mounted_head_camera:
        provenance["fpv"] = "isaac_lab_camera_rgb_robot_mounted_head_camera:fpv"
    if head_camera_equivalent:
        provenance["fpv"] = "isaac_lab_camera_rgb_head_camera_equivalent:fpv"
    provenance["semantic_pose_state_refreshed"] = semantic_pose_state_refreshed
    provenance["canonical_camera_control"] = canonical_camera_control
    provenance["robot_mounted_head_camera"] = mounted_head_camera
    provenance["head_camera_equivalent"] = head_camera_equivalent
    return provenance


def _mounted_head_camera_contract(
    robot_pose: dict[str, object],
    provenance: dict[str, object],
) -> dict[str, object]:
    return {
        "schema": "robot_view_camera_control_contract_v1",
        "backend": "isaaclab_subprocess",
        "status": "robot_mounted_head_camera_robot_view",
        "camera_control_api": None,
        "camera_model": "robot_mounted_head_camera_v1",
        "same_pose_api": False,
        "camera_prim_path": "/World/robot_0/head_camera",
        "robot_pose": robot_pose,
        "agent_facing_fpv": {
            "source": "isaac_lab_camera_rgb_robot_mounted_head_camera:fpv",
            "canonical_camera_control": False,
            "robot_mounted": True,
            "head_camera_equivalent": False,
            "camera_prim_path": "/World/robot_0/head_camera",
        },
        "report_verify_view": {
            "source": provenance["verify"],
            "canonical_camera_control": False,
        },
    }


def _head_camera_equivalent_contract(
    robot_pose: dict[str, object],
    provenance: dict[str, object],
) -> dict[str, object]:
    return {
        "schema": "robot_view_camera_control_contract_v1",
        "backend": "isaaclab_subprocess",
        "status": "robot_head_camera_equivalent_robot_view",
        "camera_control_api": None,
        "camera_model": "robot_head_camera_equivalent_v1",
        "same_pose_api": False,
        "robot_pose": robot_pose,
        "agent_facing_fpv": {
            "source": "isaac_lab_camera_rgb_head_camera_equivalent:fpv",
            "canonical_camera_control": False,
            "head_camera_equivalent": True,
        },
        "report_verify_view": {
            "source": provenance["verify"],
            "canonical_camera_control": False,
        },
    }


def _canonical_camera_control_contract(robot_pose: dict[str, object]) -> dict[str, object]:
    return {
        "schema": "robot_view_camera_control_contract_v1",
        "backend": "isaaclab_subprocess",
        "status": "canonical_camera_control_robot_view",
        "camera_control_api": "roboclaws.camera_control.render_views",
        "camera_model": "canonical_eye_target_camera_v1",
        "same_pose_api": True,
        "lighting_profile": {"profile_id": "scene_probe_existing_usd_lights_v1"},
        "color_profile": {"profile_id": "display_srgb_soft_highlight_v1"},
        "robot_pose": robot_pose,
        "agent_facing_fpv": {
            "source": "canonical_eye_target_robot_pose",
            "canonical_camera_control": True,
            "eye": [1.0, 2.0, 1.55],
            "target": [2.5, 5.5, 0.6],
        },
        "report_verify_view": {
            "source": "canonical_eye_target_robot_verify",
            "canonical_camera_control": True,
            "eye": [1.2, 2.4, 2.3],
            "target": [2.5, 5.5, 0.6],
        },
    }


def _backend_local_camera_control_contract(provenance: dict[str, object]) -> dict[str, object]:
    return {
        "schema": "robot_view_camera_control_contract_v1",
        "backend": "isaaclab_subprocess",
        "status": "backend_local_scene_bounds_camera",
        "camera_control_api": None,
        "camera_model": "backend_local_robot_view",
        "same_pose_api": False,
        "agent_facing_fpv": {
            "source": provenance["fpv"],
            "canonical_camera_control": False,
        },
        "report_verify_view": {
            "source": provenance["verify"],
            "canonical_camera_control": False,
        },
    }


def _isaac_robot_view_camera_control_contract(
    robot_pose: dict[str, object],
    provenance: dict[str, object],
    *,
    canonical_camera_control: bool,
    mounted_head_camera: bool,
    head_camera_equivalent: bool,
) -> dict[str, object]:
    if mounted_head_camera:
        return _mounted_head_camera_contract(robot_pose, provenance)
    if head_camera_equivalent:
        return _head_camera_equivalent_contract(robot_pose, provenance)
    if canonical_camera_control:
        return _canonical_camera_control_contract(robot_pose)
    return _backend_local_camera_control_contract(provenance)


def _apply_isaac_robot_view_step_metadata(
    step: dict[str, object],
    views: dict[str, str],
    *,
    capture_method: str,
    semantic_pose_state_refreshed: bool,
    canonical_camera_control: bool,
    mounted_head_camera: bool,
    head_camera_equivalent: bool,
) -> None:
    provenance = _isaac_robot_view_provenance(
        views,
        capture_method=capture_method,
        semantic_pose_state_refreshed=semantic_pose_state_refreshed,
        canonical_camera_control=canonical_camera_control,
        mounted_head_camera=mounted_head_camera,
        head_camera_equivalent=head_camera_equivalent,
    )
    robot_pose = _isaac_robot_view_pose()
    step["robot_pose"] = robot_pose
    step["view_provenance"] = provenance
    step["camera_control_contract"] = _isaac_robot_view_camera_control_contract(
        robot_pose,
        provenance,
        canonical_camera_control=canonical_camera_control,
        mounted_head_camera=mounted_head_camera,
        head_camera_equivalent=head_camera_equivalent,
    )


def _isaac_robot_view_camera_control_summary(
    step_count: int,
    *,
    canonical_camera_control: bool,
    head_camera_equivalent: bool,
) -> dict[str, object]:
    if head_camera_equivalent:
        return {
            "schema": "robot_view_camera_control_summary_v1",
            "status": "all_robot_views_use_head_camera_fpv",
            "same_pose_api": False,
            "head_camera_fpv": True,
            "step_count": step_count,
            "contract_count": step_count,
            "canonical_contract_count": 0,
            "head_camera_contract_count": step_count,
            "backend_local_contract_count": step_count,
        }
    if canonical_camera_control:
        return {
            "schema": "robot_view_camera_control_summary_v1",
            "status": "all_robot_views_use_canonical_camera_control",
            "same_pose_api": True,
            "head_camera_fpv": False,
            "step_count": step_count,
            "contract_count": step_count,
            "canonical_contract_count": step_count,
            "head_camera_contract_count": 0,
            "backend_local_contract_count": 0,
        }
    return {
        "schema": "robot_view_camera_control_summary_v1",
        "status": "mixed_or_backend_local_robot_views",
        "same_pose_api": False,
        "head_camera_fpv": False,
        "step_count": step_count,
        "contract_count": step_count,
        "canonical_contract_count": 0,
        "head_camera_contract_count": 0,
        "backend_local_contract_count": step_count,
    }


def _add_isaac_robot_view_step(
    data: dict[str, object],
    base: Path,
    *,
    blank_key: str = "",
    capture_method: str = "isaac_lab_camera_rgb_static_robot_views",
    semantic_pose_state_refreshed: bool = False,
    canonical_camera_control: bool = False,
    mounted_head_camera: bool = False,
    head_camera_equivalent: bool = False,
) -> None:
    view_dir, views = _write_isaac_robot_view_images(base, blank_key=blank_key)
    report = _ensure_isaac_robot_view_report(base)
    artifacts = data.setdefault("artifacts", {})
    assert isinstance(artifacts, dict)
    artifacts["robot_views"] = str(view_dir.relative_to(base))
    artifacts["report"] = str(report.relative_to(base))
    data["view_variant"] = "isaaclab-fpv-topdown-chase-verify"
    steps = _base_isaac_robot_view_steps(views)
    for step in steps:
        _apply_isaac_robot_view_step_metadata(
            step,
            views,
            capture_method=capture_method,
            semantic_pose_state_refreshed=semantic_pose_state_refreshed,
            canonical_camera_control=canonical_camera_control,
            mounted_head_camera=mounted_head_camera,
            head_camera_equivalent=head_camera_equivalent,
        )
    data["robot_view_steps"] = steps
    data["robot_view_camera_control"] = _isaac_robot_view_camera_control_summary(
        len(steps),
        canonical_camera_control=canonical_camera_control,
        head_camera_equivalent=head_camera_equivalent,
    )


def _add_isaac_snapshot_artifacts(
    data: dict[str, object],
    base: Path,
    *,
    blank_output: bool = False,
) -> None:
    snapshot_dir = base / "isaac_snapshots"
    snapshot_dir.mkdir(parents=True, exist_ok=True)
    source_path = snapshot_dir / "source.png"
    _write_nonblank_png(source_path)
    snapshots: list[dict[str, object]] = []
    for index in range(2):
        output_path = snapshot_dir / f"snapshot_{index}.png"
        if blank_output and index == 0:
            _write_blank_png(output_path)
        else:
            _write_nonblank_png(output_path)
        snapshots.append(
            {
                "title": f"snapshot {index}",
                "output_path": str(output_path.relative_to(base)),
                "visual_artifact_provenance": "isaac_lab_camera_rgb",
                "placeholder_visuals": False,
                "snapshot_provenance": {
                    "source_path": str(source_path.relative_to(base)),
                    "visual_artifact_provenance": "isaac_lab_camera_rgb",
                    "placeholder_visuals": False,
                    "static_isaac_capture": True,
                    "semantic_pose_rendered": False,
                },
            }
        )
    isaac_runtime = data["isaac_runtime"]
    assert isinstance(isaac_runtime, dict)
    isaac_runtime["snapshot_artifacts"] = snapshots


def _write_nonblank_png(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    image = Image.new("RGB", (8, 8), (24, 40, 72))
    image.putpixel((0, 0), (220, 180, 40))
    image.save(path)


def _write_blank_png(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    Image.new("RGB", (8, 8), (0, 0, 0)).save(path)


def _write_isaac_scene_index(
    base: Path,
    scene_bindings: dict[str, object],
    *,
    artifact_scene_bindings: dict[str, object] | None = None,
    segmentation: dict[str, object] | None = None,
    object_prim_path: str = "/World/Objects/mug_01",
    extra_object_index: dict[str, object] | None = None,
) -> None:
    if artifact_scene_bindings is None:
        artifact_scene_bindings = scene_bindings
    if segmentation is None:
        segmentation = {
            "status": "blocked_capability",
            "agent_facing": False,
            "no_simulator_label_fallback": True,
        }
    object_index = {"mug_01": {"usd_prim_path": object_prim_path}}
    object_index.update(extra_object_index or {})
    payload = {
        "schema": "isaac_scene_index_artifact_v1",
        "backend": "isaaclab_subprocess",
        "agent_facing": False,
        "private_manifest_exposed_to_agent": False,
        "object_index": object_index,
        "object_index_count": len(object_index),
        "receptacle_index": {
            "sink_01": {"usd_prim_path": "/World/Receptacles/sink_01"},
        },
        "receptacle_index_count": 1,
        "scene_binding_diagnostics": artifact_scene_bindings,
        "segmentation": segmentation,
    }
    (base / "isaac_scene_index.json").write_text(json.dumps(payload), encoding="utf-8")


def _isaac_available_segmentation() -> dict[str, object]:
    bbox = _isaac_segmentation_bbox()
    return {
        "schema": "isaac_segmentation_diagnostics_v1",
        "status": "available",
        "available": True,
        "source": "isaac_lab_camera",
        "capture_method": "isaac_lab_camera_segmentation",
        "requested_data_types": [
            "semantic_segmentation",
            "instance_segmentation_fast",
            "instance_id_segmentation_fast",
        ],
        "output_data_types": ["instance_id_segmentation_fast"],
        "tensor_output_available": True,
        "candidate_overlay_status": "available",
        "candidate_bbox_count": 1,
        "selected_usd_prim_match_count": 1,
        "selected_usd_prim_paths": [
            "/World/Objects/mug_01",
            "/World/Receptacles/sink_01",
        ],
        "selected_candidate_bboxes": [bbox],
        "candidate_bboxes": [bbox],
        "agent_facing": False,
        "no_simulator_label_fallback": True,
    }


def _isaac_semantic_pose_state() -> dict[str, object]:
    event_base = {
        "schema": "isaac_semantic_pose_event_v1",
        "state_source": "backend_json_state",
        "primitive_provenance": "isaac_semantic_pose",
        "rendered_to_usd": False,
        "planner_backed": False,
        "physical_robot": False,
        "object_id": "mug_01",
        "object_usd_prim_path": "/World/Objects/mug_01",
        "receptacle_id": "sink_01",
        "receptacle_usd_prim_path": "/World/Receptacles/sink_01",
    }
    return {
        "schema": "isaac_semantic_pose_state_v1",
        "state_source": "backend_json_state",
        "primitive_provenance": "isaac_semantic_pose",
        "rendered_to_usd": False,
        "planner_backed": False,
        "physical_robot": False,
        "semantic_pose_only": True,
        "object_poses": {
            "mug_01": {
                "state_source": "backend_json_state",
                "rendered_to_usd": False,
                "usd_prim_path": "/World/Objects/mug_01",
                "support_receptacle_id": "sink_01",
                "support_usd_prim_path": "/World/Receptacles/sink_01",
            }
        },
        "articulations": {
            "sink_01": {
                "state_source": "backend_json_state",
                "rendered_to_usd": False,
                "usd_prim_path": "/World/Receptacles/sink_01",
            }
        },
        "transform_events": [
            {
                **event_base,
                "sequence": 1,
                "tool": "pick",
                "state_mutation": "isaac_prim_attach",
            },
            {
                **event_base,
                "sequence": 2,
                "tool": "place",
                "state_mutation": "isaac_prim_transform",
            },
        ],
    }


def _isaac_semantic_pose_state_with_refreshed_robot_views(
    *,
    canonical_camera_control: bool = False,
    mounted_head_camera: bool = False,
    head_camera_equivalent: bool = False,
) -> dict[str, object]:
    state = _isaac_semantic_pose_state()
    state["rendered_to_usd"] = True
    state["semantic_pose_view_capture"] = {
        "schema": "isaac_semantic_pose_robot_view_capture_v1",
        "capture_method": "isaac_lab_camera_rgb_semantic_pose_robot_views",
        "rendered_to_usd": True,
        "scene_usd": "loaded_scene.usda",
        "render_steps": 4,
        "canonical_camera_control": canonical_camera_control,
        "robot_mounted_head_camera": mounted_head_camera,
        "head_camera_prim_path": "/World/robot_0/head_camera" if mounted_head_camera else "",
        "head_camera_equivalent": head_camera_equivalent,
    }
    return state


def _isaac_semantic_pose_trace_events(
    state: dict[str, object],
    *,
    include_provenance: bool = True,
) -> list[dict[str, object]]:
    events = state.get("transform_events") or []
    trace_events: list[dict[str, object]] = []
    if not isinstance(events, list):
        return trace_events
    for event in events:
        if not isinstance(event, dict):
            continue
        response = {
            "ok": True,
            "status": "ok",
            "tool": str(event.get("tool") or ""),
            "object_id": str(event.get("object_id") or ""),
            "receptacle_id": str(event.get("receptacle_id") or ""),
            "state_mutation": str(event.get("state_mutation") or ""),
        }
        if include_provenance:
            response["primitive_provenance"] = "isaac_semantic_pose"
        trace_events.append(_trace_response(str(event.get("tool") or ""), response))
    return trace_events


def _isaac_segmentation_bbox() -> dict[str, object]:
    return {
        "view": "fpv",
        "data_type": "instance_id_segmentation_fast",
        "label_id": 3,
        "label": "/World/Objects/mug_01",
        "usd_prim_path": "/World/Objects/mug_01",
        "bbox_xyxy": [8, 8, 32, 36],
        "pixel_count": 144,
        "image_size": [64, 48],
    }


def _isaac_report_text(
    scene_bindings: dict[str, object],
    *,
    semantic_pose_state: dict[str, object] | None = None,
    include_semantic_pose_rows: bool = True,
) -> str:
    selected_objects = scene_bindings.get("selected_object_bindings") or {}
    selected_receptacles = scene_bindings.get("selected_target_receptacle_bindings") or {}
    rows = [*selected_objects.values(), *selected_receptacles.values()]
    row_text = " ".join(
        f"{row.get('usd_handle', '')} {row.get('usd_prim_path', '')}"
        for row in rows
        if isinstance(row, dict)
    )
    semantic_pose_text = ""
    if semantic_pose_state is not None and include_semantic_pose_rows:
        semantic_pose_text = _isaac_semantic_pose_report_text(semantic_pose_state)
    return (
        "Isaac Runtime Diagnostics Segmentation Scene Index Artifact Rows "
        "Selected USD Binding Rows Selected USD Index Rows "
        "isaac_semantic_pose Semantic Pose State Semantic Pose Events "
        "Rendered to USD Planner backed "
        f"{row_text} {semantic_pose_text}"
    )


def _isaac_semantic_pose_report_text(state: dict[str, object]) -> str:
    values: list[str] = [
        "Object USD",
        "Support USD",
        "USD prim",
        "Mutation",
        "Receptacle USD",
    ]
    object_poses = state.get("object_poses") or {}
    if isinstance(object_poses, dict):
        for object_id, pose in object_poses.items():
            if not isinstance(pose, dict):
                continue
            values.extend(
                [
                    str(object_id),
                    str(pose.get("support_receptacle_id") or ""),
                    str(pose.get("usd_prim_path") or ""),
                    str(pose.get("support_usd_prim_path") or ""),
                ]
            )
    articulations = state.get("articulations") or {}
    if isinstance(articulations, dict):
        for receptacle_id, articulation in articulations.items():
            if not isinstance(articulation, dict):
                continue
            values.extend(
                [
                    str(receptacle_id),
                    str(articulation.get("usd_prim_path") or ""),
                ]
            )
    events = state.get("transform_events") or []
    if isinstance(events, list):
        for event in events:
            if not isinstance(event, dict):
                continue
            values.extend(
                [
                    str(event.get("tool") or ""),
                    str(event.get("state_mutation") or ""),
                    str(event.get("object_id") or ""),
                    str(event.get("receptacle_id") or ""),
                    str(event.get("object_usd_prim_path") or ""),
                    str(event.get("receptacle_usd_prim_path") or ""),
                ]
            )
    return " ".join(value for value in values if value)


def _seed7_cleanup_bindings(anchor_probe: dict[str, object]) -> list[dict[str, object]]:
    bindings = []
    anchor_by_id = _runtime_anchor_by_id(anchor_probe)
    for row in anchor_probe.get("semantic_substeps", []):
        if not isinstance(row, dict):
            continue
        object_id = str(row.get("object_id") or "")
        source_fixture_id = str(row.get("source_receptacle_id") or "")
        candidate_fixture_id = str(row.get("target_receptacle_id") or "")
        if not object_id or not candidate_fixture_id:
            continue
        tools = _planner_tools_for_target_anchor(anchor_by_id.get(candidate_fixture_id, {}))
        bindings.append(
            _cleanup_binding(
                object_id,
                source_fixture_id,
                candidate_fixture_id,
                tools,
            )
        )
    if len(bindings) < 5:
        raise AssertionError(f"expected at least five seed=7 cleanup bindings, got {bindings}")
    return bindings[:5]


def _runtime_anchor_by_id(result: dict[str, object]) -> dict[str, dict[str, object]]:
    agent_view = result.get("agent_view")
    agent_view = agent_view if isinstance(agent_view, dict) else {}
    runtime_map = agent_view_module.runtime_metric_map(agent_view) if agent_view else {}
    runtime_map = runtime_map if isinstance(runtime_map, dict) else {}
    return {
        str(item.get("anchor_id") or ""): item
        for item in runtime_map.get("public_semantic_anchors", [])
        if isinstance(item, dict) and item.get("anchor_id")
    }


def _planner_tools_for_target_anchor(anchor: dict[str, object]) -> list[str]:
    affordances = {str(item) for item in anchor.get("affordances", [])}
    if "open" in affordances:
        return ["open_receptacle", "place_inside", "close_receptacle"]
    if "place_inside" in affordances:
        return ["place_inside"]
    return ["place"]


def _first_seed7_binding_requiring_tool(
    anchor_probe: dict[str, object],
    required_tool: str,
) -> dict[str, object]:
    for binding in _seed7_cleanup_bindings(anchor_probe):
        if required_tool in binding["tools"]:
            return binding
    raise AssertionError(f"expected seed=7 binding requiring {required_tool}")


def _candidate_fixture_id_for_object(result: dict[str, object], object_id: str) -> str:
    for candidate_fixture_id in (
        _semantic_substep_target_fixture_id(result, object_id),
        _primitive_evidence_target_fixture_id(result, object_id),
        _agent_view_worklist_candidate_fixture_id(result, object_id),
    ):
        if candidate_fixture_id:
            return candidate_fixture_id
    raise AssertionError(f"expected candidate fixture for {object_id}")


def _semantic_substep_target_fixture_id(result: dict[str, object], object_id: str) -> str:
    return _target_fixture_id_from_rows(
        result.get("semantic_substeps", []),
        object_id=object_id,
        field="target_receptacle_id",
    )


def _primitive_evidence_target_fixture_id(result: dict[str, object], object_id: str) -> str:
    primitive_evidence = result.get("cleanup_primitive_evidence")
    primitive_evidence = primitive_evidence if isinstance(primitive_evidence, dict) else {}
    return _target_fixture_id_from_rows(
        primitive_evidence.get("objects", []),
        object_id=object_id,
        field="target_receptacle_id",
    )


def _agent_view_worklist_candidate_fixture_id(result: dict[str, object], object_id: str) -> str:
    agent_view = result.get("agent_view") if isinstance(result.get("agent_view"), dict) else {}
    worklist = agent_view_module.cleanup_worklist(agent_view) if agent_view else {}
    rows = worklist.get("objects", []) if isinstance(worklist, dict) else []
    for item in rows:
        if not isinstance(item, dict) or str(item.get("object_id") or "") != object_id:
            continue
        candidate_fixture_id = str(item.get("candidate_fixture_id") or "")
        if candidate_fixture_id:
            return candidate_fixture_id
        return _first_destination_option_fixture_id(item.get("destination_options") or [])
    return ""


def _target_fixture_id_from_rows(rows: object, *, object_id: str, field: str) -> str:
    for item in rows if isinstance(rows, list) else []:
        if not isinstance(item, dict) or str(item.get("object_id") or "") != object_id:
            continue
        candidate_fixture_id = str(item.get(field) or "")
        if candidate_fixture_id:
            return candidate_fixture_id
    return ""


def _first_destination_option_fixture_id(destination_options: object) -> str:
    for option in destination_options if isinstance(destination_options, list) else []:
        if not isinstance(option, dict):
            continue
        candidate_fixture_id = str(option.get("candidate_fixture_id") or "")
        if candidate_fixture_id:
            return candidate_fixture_id
    return ""


def _cleanup_binding(
    object_id: str,
    source_receptacle_id: str,
    target_receptacle_id: str,
    target_tools: list[str],
) -> dict[str, object]:
    return {
        "schema": "planner_probe_cleanup_primitive_binding_v1",
        "object_id": object_id,
        "target_receptacle_id": target_receptacle_id,
        "source_receptacle_id": source_receptacle_id,
        "planner_object_id": f"{object_id}/body",
        "planner_target_receptacle_id": f"{target_receptacle_id}/body",
        "tools": [
            "navigate_to_object",
            "pick",
            "navigate_to_receptacle",
            *target_tools,
        ],
    }


def _insert_robot_timeline_before_score(report: Path) -> None:
    report_text = report.read_text(encoding="utf-8")
    robot_timeline = (
        '\n<section class="panel robot-timeline"><h2>Robot View Timeline</h2></section>'
    )
    score_marker = '<section class="panel">\n      <h2>Score</h2>'
    if score_marker in report_text:
        report_text = report_text.replace(score_marker, robot_timeline + "\n" + score_marker)
    else:
        report_text += robot_timeline
    report.write_text(report_text, encoding="utf-8")


def _b1_robot_consumption_run_result(tmp_path: Path, *, verified: bool) -> dict[str, object]:
    source_bundle = _compile_b1_runtime_bundle_for_checker(tmp_path, verified=verified)
    run_result: dict[str, object] = {
        "contract": "realworld_cleanup_contract_v1",
        "artifacts": {},
    }
    attach_nav2_map_bundle_snapshot(
        run_result=run_result,
        run_dir=tmp_path,
        source_bundle_dir=source_bundle,
    )
    manifest_path = source_bundle / "b1_robot_consumption_manifest.json"
    if manifest_path.is_file():
        shutil.copy2(manifest_path, tmp_path / "b1_robot_consumption_manifest.json")
    return run_result


def _compile_b1_runtime_bundle_for_checker(tmp_path: Path, *, verified: bool) -> Path:
    kwargs: dict[str, Path] = {}
    if verified:
        alignment_path = tmp_path / "b1_alignment_residuals.json"
        navigation_path = tmp_path / "b1_navigation_smoke.json"
        alignment_path.write_text(
            json.dumps(_b1_verified_alignment_artifact()),
            encoding="utf-8",
        )
        navigation_path.write_text(
            json.dumps(_b1_navigation_artifact(tmp_path, alignment_path=alignment_path)),
            encoding="utf-8",
        )
        kwargs = {
            "alignment_artifact_path": alignment_path,
            "navigation_artifact_path": navigation_path,
        }
    base_result = build_base_metric_map_bundle(
        map_bundle=B1_MAP12_BUNDLE,
        labels_path=B1_BASE_LABELS,
        room_semantics_path=B1_ROOM_SEMANTICS,
        output_dir=tmp_path / ("b1-base-verified" if verified else "b1-base-blocked"),
    )
    result = augment_base_metric_map_bundle(
        base_map_bundle=Path(base_result["output_dir"]),
        output_dir=tmp_path / ("b1-runtime-verified" if verified else "b1-runtime-blocked"),
        allow_blocked_proof=not verified,
        **kwargs,
    )
    return Path(result["output_dir"])


def _b1_verified_alignment_artifact() -> dict[str, object]:
    return {
        "schema": "b1_map12_scene_alignment_residuals_v1",
        "bbox_seed_policy": "known_poor_seed_only",
        "manipulation_supported": False,
        "object_receptacle_usd_binding_status": "blocked_out_of_scope",
        "global_alignment_status": "verified",
        "selected_transform_type": "rigid_2d",
        "selected_transform": {
            "source": "reviewed_correspondence_fit",
            "type": "rigid_2d",
        },
        "residual_evidence": {
            "status": "available",
            "matched_anchor_count": 6,
            "transform_source": "reviewed_correspondence_fit",
            "mean_residual_m": 0.1,
            "median_residual_m": 0.1,
            "p90_residual_m": 0.2,
            "max_residual_m": 0.3,
        },
        "area_alignment": [],
    }


def _b1_navigation_artifact(tmp_path: Path, *, alignment_path: Path) -> dict[str, object]:
    first = tmp_path / "b1-waypoint-1.fpv.png"
    second = tmp_path / "b1-waypoint-2.fpv.png"
    _write_checker_reviewable_png(first, color=(32, 64, 96))
    _write_checker_reviewable_png(second, color=(96, 64, 32))
    return {
        "schema": "b1_map12_navigation_smoke_v1",
        "status": "passed",
        "b1_scene_usd": str(DEFAULT_B1_VISUAL_ROUTE_SCENE_USD),
        "visual_route": {
            "scene_id": "B1_floor2_slow",
            "scene_usd": str(DEFAULT_B1_VISUAL_ROUTE_SCENE_USD),
            "selected": True,
            "status": "same_pose_render_verified",
        },
        "robot_navigation_supported": True,
        "robot_navigation_provenance": NAVIGATION_PROVENANCE,
        "navigation_provenance": "kinematic_pose_driven",
        "alignment_artifact": str(alignment_path),
        "alignment_transform_source": "reviewed_correspondence_fit",
        "planner_backed": False,
        "physical_robot": False,
        "semantic_source": "robot_map_12_navigation_memory_overlay",
        "semantic_usd_binding_status": "blocked_until_segmentation_or_manifest",
        "semantic_anchors_are_usd_truth": False,
        "usd_object_index_ready": False,
        "usd_receptacle_index_ready": False,
        "manipulation_supported": False,
        "navigation_waypoint_count": 2,
        "robot_view_evidence_status": "available",
        "waypoint_evidence": [
            _b1_waypoint_evidence(
                "wp_1",
                x=-4.0,
                y=-8.0,
                alignment_path=alignment_path,
                fpv=first,
            ),
            _b1_waypoint_evidence(
                "wp_2",
                x=-2.0,
                y=-7.0,
                alignment_path=alignment_path,
                fpv=second,
            ),
        ],
    }


def _b1_waypoint_evidence(
    waypoint_id: str,
    *,
    x: float,
    y: float,
    alignment_path: Path,
    fpv: Path,
) -> dict[str, object]:
    return {
        "waypoint_id": waypoint_id,
        "scene_usd": str(DEFAULT_B1_VISUAL_ROUTE_SCENE_USD),
        "robot_pose": {
            "frame": "b1_rebuilt_scene_usd_world_candidate",
            "x": x,
            "y": y,
            "z": 0.0,
            "yaw_deg": 0.0,
        },
        "robot_pose_applied": True,
        "alignment_artifact": str(alignment_path),
        "alignment_transform_source": "reviewed_correspondence_fit",
        "views": {"fpv": str(fpv)},
    }


def _write_checker_reviewable_png(path: Path, *, color: tuple[int, int, int]) -> None:
    image = Image.new("RGB", (32, 24))
    pixels = image.load()
    red, green, blue = color
    for y in range(image.height):
        for x in range(image.width):
            pixels[x, y] = (
                (red + x * 7) % 256,
                (green + y * 11) % 256,
                (blue + (x + y) * 5) % 256,
            )
    image.save(path)


def _write_strict_planner_proof(
    base: Path,
    *,
    embodiment: str = "franka",
    upstream_policy_class: str = "PickAndPlacePlannerPolicy",
    curobo_available: bool = False,
    cleanup_binding: dict[str, object] | None = None,
    steps_executed: int = 2,
    max_abs_qpos_delta: float = 0.01,
) -> Path:
    base.mkdir(parents=True)
    views = base / "planner_views"
    views.mkdir()
    (views / "initial_wrist_camera.png").write_bytes(b"initial")
    (views / "final_wrist_camera.png").write_bytes(b"final")
    evidence = planner_backed_probe_evidence(
        backend="molmospaces_subprocess",
        embodiment=embodiment,
        task="pick_and_place",
        probe_mode="execute",
        upstream_policy_class=upstream_policy_class,
        steps_requested=2,
        steps_executed=steps_executed,
        max_abs_qpos_delta=max_abs_qpos_delta,
        image_artifacts={
            "initial": "planner_views/initial_wrist_camera.png",
            "final": "planner_views/final_wrist_camera.png",
        },
    )
    evidence["runtime_diagnostics"] = {
        "renderer_adapter_enabled": True,
        "modules": {"curobo": {"available": curobo_available}},
    }
    if cleanup_binding is not None:
        evidence["cleanup_primitive_binding"] = cleanup_binding
    path = base / "run_result.json"
    path.write_text(
        json.dumps(
            {
                "contract": MANIPULATION_PROBE_CONTRACT,
                "status": PLANNER_BACKED_PROVENANCE,
                "primitive_provenance": PLANNER_BACKED_PROVENANCE,
                "manipulation_evidence": evidence,
            }
        ),
        encoding="utf-8",
    )
    return path
