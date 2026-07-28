from __future__ import annotations

import json
import math
import sys
import types
import zipfile
from pathlib import Path
from types import SimpleNamespace

import pytest
from PIL import Image, ImageDraw

from roboclaws.household.b1_nurec_scene import prepare_b1_nurec_scene_usd
from roboclaws.household.isaac_lab_backend import (
    ISAAC_SCENE_INDEX_ARTIFACT_SCHEMA,
    ISAAC_SEMANTIC_POSE_PROVENANCE,
    ISAAC_SEMANTIC_POSE_STATE_SCHEMA,
    ISAAC_SEMANTIC_POSE_STATE_SOURCE,
    ISAACLAB_ROBOT_VIEW_VARIANT,
    ISAACLAB_SUBPROCESS_BACKEND,
    IsaacLabSubprocessBackend,
)
from scripts.isaac_lab_cleanup import isaac_lab_backend_worker


def test_prepare_b1_nurec_scene_unpacks_usdz_reference(tmp_path: Path) -> None:
    scene_gs = _write_b1_scene_gs_fixture(tmp_path / "storey_1")

    prepared = prepare_b1_nurec_scene_usd(scene_gs, cache_root=tmp_path / "cache")

    assert prepared == tmp_path / "cache" / "storey_1" / "scene_gs.unpacked_nurec.usda"
    text = prepared.read_text(encoding="utf-8")
    assert "xm_large_scene.usdz" not in text
    assert "xm_large_scene_unpacked/default.usda" in text
    assert (prepared.parent / "xm_large_scene_unpacked" / "xm_large_scene.nurec").read_bytes() == (
        b"nurec"
    )


def test_isaac_backend_prepares_b1_scene_gs_before_worker_init(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    scene_gs = _write_b1_scene_gs_fixture(tmp_path / "source")
    captured_init_args: list[str] = []
    original_run_worker = IsaacLabSubprocessBackend._run_worker
    monkeypatch.setenv("ROBOCLAWS_B1_NUREC_CACHE_DIR", str(tmp_path / "cache"))

    def wrapped_run_worker(
        self: IsaacLabSubprocessBackend,
        command: str,
        *args: str,
    ) -> dict[str, object]:
        if command == "init":
            captured_init_args.extend(args)
        return original_run_worker(self, command, *args)

    monkeypatch.setattr(IsaacLabSubprocessBackend, "_run_worker", wrapped_run_worker)

    IsaacLabSubprocessBackend(
        run_dir=tmp_path / "run",
        python_executable=Path(sys.executable),
        runtime_mode="fake",
        scene_usd_path=scene_gs,
    )

    scene_arg = captured_init_args[captured_init_args.index("--scene-usd-path") + 1]
    assert scene_arg.endswith("scene_gs.unpacked_nurec.usda")
    assert Path(scene_arg).is_file()


def _write_b1_scene_gs_fixture(source_dir: Path) -> Path:
    source_dir.mkdir()
    scene_gs = source_dir / "scene_gs.usda"
    scene_gs.write_text(
        "#usda 1.0\n"
        'def Xform "combined" {\n'
        '    def "sim" (prepend references = @./scene.usd@) {}\n'
        '    def Xform "gs" (prepend references = @./xm_large_scene.usdz@) {}\n'
        "}\n",
        encoding="utf-8",
    )
    (source_dir / "scene.usd").write_text("#usda 1.0\n", encoding="utf-8")
    with zipfile.ZipFile(source_dir / "xm_large_scene.usdz", "w") as archive:
        archive.writestr("default.usda", "#usda 1.0\n")
        archive.writestr("gauss.usda", "#usda 1.0\n")
        archive.writestr("xm_large_scene.nurec", b"nurec")
    return scene_gs


def test_isaac_worker_read_state_rejects_missing_state_source(tmp_path: Path) -> None:
    missing = tmp_path / "missing_state.json"

    with pytest.raises(
        FileNotFoundError,
        match=r"Isaac worker state source is missing: .*missing_state\.json",
    ):
        isaac_lab_backend_worker.read_state(missing)


def test_isaac_worker_read_state_rejects_malformed_state_source(tmp_path: Path) -> None:
    state_path = tmp_path / "state.json"
    state_path.write_text("{bad json\n", encoding="utf-8")

    with pytest.raises(
        ValueError,
        match=r"Isaac worker state source must contain valid JSON object: .*state\.json",
    ):
        isaac_lab_backend_worker.read_state(state_path)


def test_isaac_worker_read_state_rejects_non_object_state_source(tmp_path: Path) -> None:
    state_path = tmp_path / "state.json"
    state_path.write_text("[]", encoding="utf-8")

    with pytest.raises(
        ValueError,
        match=r"Isaac worker state source must contain a JSON object: .*state\.json",
    ):
        isaac_lab_backend_worker.read_state(state_path)


def test_isaac_worker_read_state_preserves_state_path(tmp_path: Path) -> None:
    state_path = tmp_path / "state.json"
    state = {"schema": "isaac_lab_backend_state_v1", "scenario": {"objects": []}}
    state_path.write_text(json.dumps(state), encoding="utf-8")

    loaded = isaac_lab_backend_worker.read_state(state_path)

    assert loaded["schema"] == "isaac_lab_backend_state_v1"
    assert loaded["_state_path"] == str(state_path)


def test_isaac_camera_view_specs_reject_missing_source(tmp_path: Path) -> None:
    missing = tmp_path / "missing_views.json"

    with pytest.raises(
        FileNotFoundError,
        match=r"camera view spec source is missing: .*missing_views\.json",
    ):
        isaac_lab_backend_worker._load_camera_view_specs(missing)


def test_isaac_camera_view_specs_reject_malformed_source(tmp_path: Path) -> None:
    specs_path = tmp_path / "camera_views.json"
    specs_path.write_text("{bad json\n", encoding="utf-8")

    with pytest.raises(
        ValueError,
        match=r"camera view spec source must contain valid JSON: .*camera_views\.json",
    ):
        isaac_lab_backend_worker._load_camera_view_specs(specs_path)


def test_isaac_camera_view_specs_reject_wrong_shape_source(tmp_path: Path) -> None:
    specs_path = tmp_path / "camera_views.json"
    specs_path.write_text(json.dumps({"views": {"bad": True}}), encoding="utf-8")

    with pytest.raises(
        ValueError,
        match="camera view spec must be a list or an object with a views list",
    ):
        isaac_lab_backend_worker._load_camera_view_specs(specs_path)


def test_isaac_camera_view_specs_accept_list_or_wrapped_views(tmp_path: Path) -> None:
    list_path = tmp_path / "camera_views_list.json"
    wrapped_path = tmp_path / "camera_views_object.json"
    list_path.write_text(
        json.dumps(
            [
                {"view_id": "fpv", "target": [0.0, 0.0, 0.0]},
                "skip",
                {"view_id": "map", "target": [1.0, 0.0, 0.0]},
            ]
        ),
        encoding="utf-8",
    )
    wrapped_path.write_text(
        json.dumps({"views": [{"view_id": "verify", "target": [2.0, 0.0, 0.0]}]}),
        encoding="utf-8",
    )

    assert isaac_lab_backend_worker._load_camera_view_specs(list_path) == [
        {"view_id": "fpv", "target": [0.0, 0.0, 0.0]},
        {"view_id": "map", "target": [1.0, 0.0, 0.0]},
    ]
    assert isaac_lab_backend_worker._load_camera_view_specs(wrapped_path) == [
        {"view_id": "verify", "target": [2.0, 0.0, 0.0]}
    ]


def test_isaac_lab_backend_reports_missing_runtime(tmp_path: Path) -> None:
    with pytest.raises(RuntimeError, match="Isaac Lab Python runtime is missing"):
        IsaacLabSubprocessBackend(
            run_dir=tmp_path,
            python_executable=tmp_path / "missing-python",
        )


def test_isaac_lab_fake_worker_protocol_produces_views_and_semantic_pose(
    tmp_path: Path,
) -> None:
    backend = _fake_isaac_backend(tmp_path)

    _assert_fake_isaac_runtime_metadata(backend)
    _assert_fake_isaac_scene_bindings(backend)
    _assert_fake_isaac_scene_index_payload(backend)
    _assert_fake_isaac_mess_diagnostics(backend)
    _assert_fake_isaac_snapshot(backend, tmp_path)
    _assert_fake_isaac_robot_views(backend, tmp_path)
    object_id, receptacle_id, place, done = _exercise_fake_isaac_semantic_pose_actions(backend)
    _assert_fake_isaac_action_results(place, done, object_id, receptacle_id)
    _assert_fake_isaac_semantic_pose_state(backend, object_id, receptacle_id)
    _assert_fake_isaac_robot_import(backend)


def _fake_isaac_backend(tmp_path: Path) -> IsaacLabSubprocessBackend:
    return IsaacLabSubprocessBackend(
        run_dir=tmp_path,
        python_executable=Path(sys.executable),
        runtime_mode="fake",
        include_robot=True,
        generated_mess_count=1,
    )


def _assert_fake_isaac_runtime_metadata(backend: IsaacLabSubprocessBackend) -> None:
    assert backend.backend == ISAACLAB_SUBPROCESS_BACKEND
    assert backend.runtime["runtime_mode"] == "fake"
    assert backend.runtime["renderer_mode"] == "fake_isaac_protocol"
    assert backend.runtime["rendering"]["status"] == "fake_protocol"
    assert backend.runtime["rendering"]["real_rendering_proven"] is False
    native_render = backend.runtime["rendering"]["native_render_diagnostics"]
    assert native_render["schema"] == "isaac_native_render_diagnostics_v1"
    assert native_render["status"] == "fake_protocol"
    assert native_render["settings_api_available"] is False
    assert native_render["settings_mutation_attempted"] is False
    assert native_render["default_render_settings_changed"] is False
    assert native_render["post_render_comparison_profile"]["source"] == (
        "not_a_native_renderer_setting"
    )
    assert native_render["tone_mapping"]["operator"]["status"] == "not_available"
    assert native_render["camera_exposure"]["auto_exposure_enabled"]["status"] == ("not_available")
    assert native_render["ocio"]["config"]["status"] == "not_available"
    assert backend.runtime["visual_artifact_provenance"] == "fake_protocol_placeholder_image"
    assert backend.object_index
    assert backend.receptacle_index
    assert backend.scenario_source == "default_cleanup_scenario"


def _assert_fake_isaac_scene_bindings(backend: IsaacLabSubprocessBackend) -> None:
    assert backend.scene_binding_diagnostics["schema"] == "isaac_public_scene_bindings_v1"
    assert backend.scene_binding_diagnostics["status"] == "placeholder_mapping"
    assert backend.scene_binding_diagnostics["source"] == "scenario_fixture"
    assert backend.scene_binding_diagnostics["selected_object_count"] == 1
    assert backend.scene_binding_diagnostics["selected_object_bound_count"] == 1
    assert backend.scene_binding_diagnostics["selected_target_receptacle_count"] == 1
    assert backend.scene_binding_diagnostics["selected_target_receptacle_bound_count"] == 1
    assert backend.scene_binding_diagnostics["private_manifest_exposed_to_agent"] is False
    assert backend.segmentation["status"] == "blocked_capability"
    assert backend.segmentation["agent_facing"] is False
    assert backend.segmentation["no_simulator_label_fallback"] is True
    assert backend.scene_load["status"] == "fake_protocol"
    assert backend.scene_load["usd_stage_loaded"] is False
    assert any(item["area"] == "camera_capture" for item in backend.mapping_gaps)
    assert any(item["status"] == "placeholder_visuals" for item in backend.mapping_gaps)
    assert any(item["area"] == "public_scene_bindings" for item in backend.mapping_gaps)


def _assert_fake_isaac_scene_index_payload(backend: IsaacLabSubprocessBackend) -> None:
    scene_index_payload = backend.scene_index_artifact_payload()
    assert scene_index_payload["schema"] == ISAAC_SCENE_INDEX_ARTIFACT_SCHEMA
    assert scene_index_payload["backend"] == ISAACLAB_SUBPROCESS_BACKEND
    assert scene_index_payload["agent_facing"] is False
    assert scene_index_payload["private_manifest_exposed_to_agent"] is False
    assert "private_manifest" not in scene_index_payload
    assert scene_index_payload["scene_load"]["status"] == "fake_protocol"
    assert scene_index_payload["scenario_source"] == "default_cleanup_scenario"
    assert scene_index_payload["generated_mess_count"] == 1
    assert scene_index_payload["object_index_count"] == len(scene_index_payload["object_index"])
    assert scene_index_payload["receptacle_index_count"] == len(
        scene_index_payload["receptacle_index"]
    )


def _assert_fake_isaac_mess_diagnostics(backend: IsaacLabSubprocessBackend) -> None:
    assert len(backend.mess_placement_diagnostics) == 1
    mess_diagnostic = backend.mess_placement_diagnostics[0]
    assert mess_diagnostic["schema"] == "molmospaces_semantic_placement_diagnostic_v1"
    assert mess_diagnostic["diagnostic_source"] == "mess_seed"
    assert mess_diagnostic["placement_support_status"] in {
        "direct_support",
        "degraded_elevated",
        "semantic_contained_in_receptacle",
    }


def _assert_fake_isaac_snapshot(backend: IsaacLabSubprocessBackend, tmp_path: Path) -> None:
    snapshot_path = tmp_path / "snapshot.png"
    backend.write_snapshot(snapshot_path, title="Fake Isaac snapshot")
    assert snapshot_path.is_file()
    assert snapshot_path.stat().st_size > 0
    assert backend.snapshot_artifacts[-1]["placeholder_visuals"] is True
    assert (
        backend.snapshot_artifacts[-1]["native_render_diagnostics"]["schema"]
        == "isaac_native_render_diagnostics_v1"
    )
    assert (
        backend.snapshot_artifacts[-1]["snapshot_provenance"]["source"]
        == "placeholder_protocol_image"
    )


def _assert_fake_isaac_robot_views(
    backend: IsaacLabSubprocessBackend,
    tmp_path: Path,
) -> None:
    views = backend.write_robot_views(
        tmp_path / "robot_views",
        label="0001_pick",
        focus_object_id=backend.scenario.objects[0].object_id,
        focus_receptacle_id=backend.scenario.receptacles[0].receptacle_id,
    )
    assert views["ok"] is True
    assert views["view_variant"] == ISAACLAB_ROBOT_VIEW_VARIANT
    assert views["native_render_diagnostics"]["schema"] == "isaac_native_render_diagnostics_v1"
    assert views["native_render_diagnostics"]["default_render_settings_changed"] is False
    assert set(views["views"]) == {"fpv", "chase", "topdown", "verify"}
    for path in views["views"].values():
        assert Path(path).is_file()


def _exercise_fake_isaac_semantic_pose_actions(
    backend: IsaacLabSubprocessBackend,
) -> tuple[str, str, dict[str, object], dict[str, object]]:
    object_id = backend.scenario.objects[0].object_id
    receptacle_id = backend.scenario.private_manifest.targets[0].valid_receptacle_ids[0]
    nav = backend.navigate_to_object(object_id)
    pick = backend.pick(object_id)
    target = backend.navigate_to_receptacle(receptacle_id)
    place = backend.place(receptacle_id)
    done = backend.done("fake protocol test complete")

    for response in (nav, pick, target, place):
        assert response["ok"] is True
        assert response["primitive_provenance"] == ISAAC_SEMANTIC_POSE_PROVENANCE
        assert response["planner_backed"] is False
        assert response["physical_robot"] is False
        assert response["semantic_pose_event"]["rendered_to_usd"] is False
        assert response["semantic_pose_event"]["state_source"] == ISAAC_SEMANTIC_POSE_STATE_SOURCE
    return object_id, receptacle_id, place, done


def _assert_fake_isaac_action_results(
    place: dict[str, object],
    done: dict[str, object],
    object_id: str,
    receptacle_id: str,
) -> None:
    assert done["final_locations"][object_id] == receptacle_id
    assert place["placement_diagnostic"]["schema"] == "molmospaces_semantic_placement_diagnostic_v1"
    assert place["placement_diagnostic"]["diagnostic_source"] == "cleanup_place"
    assert (
        place["placement_support_status"]
        == place["placement_diagnostic"]["placement_support_status"]
    )


def _assert_fake_isaac_semantic_pose_state(
    backend: IsaacLabSubprocessBackend,
    object_id: str,
    receptacle_id: str,
) -> None:
    semantic_pose_state = backend.semantic_pose_state
    assert semantic_pose_state["schema"] == ISAAC_SEMANTIC_POSE_STATE_SCHEMA
    assert semantic_pose_state["primitive_provenance"] == ISAAC_SEMANTIC_POSE_PROVENANCE
    assert semantic_pose_state["rendered_to_usd"] is False
    assert semantic_pose_state["planner_backed"] is False
    assert semantic_pose_state["physical_robot"] is False
    assert semantic_pose_state["object_poses"][object_id]["location_id"] == receptacle_id
    assert semantic_pose_state["object_poses"][object_id]["rendered_to_usd"] is False
    assert semantic_pose_state["object_poses"][object_id]["position_source"] == (
        "isaac_support_placement_resolver"
    )
    assert [event["tool"] for event in semantic_pose_state["transform_events"]] == [
        "navigate_to_object",
        "pick",
        "navigate_to_receptacle",
        "place",
    ]


def _assert_fake_isaac_robot_import(backend: IsaacLabSubprocessBackend) -> None:
    if backend.robot_import["status"] == "imported":
        assert backend.robot["embodiment"] == "rby1m"
        assert backend.robot["robot_mounted_head_camera"] is True
    else:
        assert backend.robot["embodiment"] == "rby1m_head_camera_equivalent"
        assert backend.robot["robot_mounted_head_camera"] is False
    assert backend.robot["head_camera_prim_path"] == "/World/robot_0/head_camera"
    assert backend.robot_import["schema"] == "isaac_rby1m_robot_import_plan_v1"
    if backend.robot_import["source_urdf"]:
        assert backend.robot_import["source_urdf"].endswith("model_holobase_isaac.urdf")
    else:
        assert (
            "RBY1M Isaac URDF not found in MolmoSpaces asset cache."
            in backend.robot_import["blockers"]
        )
    assert backend.robot_import["head_link_name"] == "link_head_2"
    assert backend.robot_import["head_camera_prim_path"] == "/World/robot_0/head_camera"
    assert backend.robot_import["head_camera_equivalent"] is (
        backend.robot_import["status"] != "imported"
    )


def test_isaac_lab_worker_detects_imported_rby1m_robot_usd(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    robot_usd = tmp_path / "rby1m_holobase_isaac.usda"
    summary_path = tmp_path / "rby1m_holobase_isaac.import_summary.json"
    robot_usd.write_text("#usda 1.0\n", encoding="utf-8")
    summary_path.write_text(
        json.dumps(
            {
                "schema": "isaac_rby1m_robot_usd_import_v1",
                "status": "ready",
                "output_usd_path": str(robot_usd),
                "stage_head_camera_prim_path": "/World/robot_0/head_camera",
                "head_link_name": "link_head_2",
            }
        )
        + "\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(
        isaac_lab_backend_worker,
        "ISAAC_RBY1M_ROBOT_USD_PATH",
        robot_usd,
    )
    monkeypatch.setattr(
        isaac_lab_backend_worker,
        "ISAAC_RBY1M_ROBOT_IMPORT_SUMMARY_PATH",
        summary_path,
    )
    monkeypatch.setattr(
        isaac_lab_backend_worker,
        "_find_rby1m_isaac_urdf",
        lambda: tmp_path / "model_holobase_isaac.urdf",
    )
    monkeypatch.setattr(isaac_lab_backend_worker, "_repo_path", lambda path: path)

    plan = isaac_lab_backend_worker._rby1m_robot_import_plan("rby1m")
    robot = isaac_lab_backend_worker._robot_payload("rby1m")

    assert plan["status"] == "imported"
    assert plan["usd_path"] == str(robot_usd)
    assert plan["head_camera_mounted"] is True
    assert plan["head_camera_equivalent"] is False
    assert plan["blockers"] == []
    assert robot["embodiment"] == "rby1m"
    assert robot["robot_mounted_head_camera"] is True
    assert robot["robot_usd_path"] == str(robot_usd)


def test_isaac_lab_backend_can_request_segmentation(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured_init_args: list[str] = []
    original_run_worker = IsaacLabSubprocessBackend._run_worker

    def wrapped_run_worker(
        self: IsaacLabSubprocessBackend,
        command: str,
        *args: str,
    ) -> dict[str, object]:
        if command == "init":
            captured_init_args.extend(args)
        return original_run_worker(self, command, *args)

    monkeypatch.setattr(IsaacLabSubprocessBackend, "_run_worker", wrapped_run_worker)

    IsaacLabSubprocessBackend(
        run_dir=tmp_path,
        python_executable=Path(sys.executable),
        runtime_mode="fake",
        enable_segmentation=True,
        segmentation_data_types=("instance_id_segmentation_fast",),
    )

    assert "--enable-segmentation" in captured_init_args
    assert captured_init_args[-2:] == [
        "--segmentation-data-type",
        "instance_id_segmentation_fast",
    ]


def test_isaac_lab_backend_can_request_segmentation_semantic_filter(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured_init_args: list[str] = []
    original_run_worker = IsaacLabSubprocessBackend._run_worker

    def wrapped_run_worker(
        self: IsaacLabSubprocessBackend,
        command: str,
        *args: str,
    ) -> dict[str, object]:
        if command == "init":
            captured_init_args.extend(args)
        return original_run_worker(self, command, *args)

    monkeypatch.setattr(IsaacLabSubprocessBackend, "_run_worker", wrapped_run_worker)

    IsaacLabSubprocessBackend(
        run_dir=tmp_path,
        python_executable=Path(sys.executable),
        runtime_mode="fake",
        segmentation_data_types=("semantic_segmentation",),
        segmentation_semantic_filter=("usd_prim_path",),
    )

    assert "--enable-segmentation" in captured_init_args
    assert [
        "--segmentation-data-type",
        "semantic_segmentation",
        "--segmentation-semantic-filter",
        "usd_prim_path",
    ] == captured_init_args[-4:]


def test_isaac_lab_backend_can_request_robot_view_settle_frames(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    backend = IsaacLabSubprocessBackend(
        run_dir=tmp_path,
        python_executable=Path(sys.executable),
        runtime_mode="fake",
        include_robot=True,
    )
    captured: dict[str, object] = {}

    def fake_run_worker(command: str, *args: str) -> dict[str, object]:
        captured["command"] = command
        captured["args"] = args
        return {"ok": True}

    monkeypatch.setattr(backend, "_run_worker", fake_run_worker)

    backend.write_robot_views_with_resolution(
        tmp_path / "robot_views",
        label="settle",
        width=1080,
        height=720,
        render_settle_frames=16,
    )

    assert captured["command"] == "robot_views"
    assert "--render-settle-frames" in captured["args"]
    assert captured["args"][-2:] == ("--render-settle-frames", "16")


def test_isaac_lab_backend_can_navigate_to_waypoint(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    backend = IsaacLabSubprocessBackend(
        run_dir=tmp_path,
        python_executable=Path(sys.executable),
        runtime_mode="fake",
        include_robot=True,
    )
    captured: dict[str, object] = {}

    def fake_run_worker(command: str, *args: str) -> dict[str, object]:
        captured["command"] = command
        captured["args"] = args
        return {"ok": True, "robot_pose": {"x": -2.0, "y": 0.0, "yaw_deg": 0.0}}

    monkeypatch.setattr(backend, "_run_worker", fake_run_worker)

    result = backend.navigate_to_waypoint(
        waypoint={
            "waypoint_id": "generated_exploration_002",
            "room_id": "meeting_room_b",
            "frame_id": "map",
            "x": -2.0,
            "y": 0.0,
            "yaw": 0.0,
        }
    )

    assert result["ok"] is True
    assert captured["command"] == "navigate_to_waypoint"
    assert captured["args"][0] == "--waypoint-json"
    payload = json.loads(str(captured["args"][1]))
    assert payload["waypoint_id"] == "generated_exploration_002"
    assert payload["x"] == pytest.approx(-2.0)


def test_isaac_lab_backend_can_navigate_to_relative_pose(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    backend = IsaacLabSubprocessBackend(
        run_dir=tmp_path,
        python_executable=Path(sys.executable),
        runtime_mode="fake",
        include_robot=True,
    )
    captured: dict[str, object] = {}

    def fake_run_worker(command: str, *args: str) -> dict[str, object]:
        captured["command"] = command
        captured["args"] = args
        return {
            "ok": True,
            "tool": "navigate_to_relative_pose",
            "applied_delta": {
                "forward_m": 0.25,
                "lateral_m": -0.125,
                "yaw_delta_deg": 15.0,
            },
        }

    monkeypatch.setattr(backend, "_run_worker", fake_run_worker)

    result = backend.navigate_to_relative_pose(
        forward_m=0.25,
        lateral_m=-0.125,
        yaw_delta_deg=15,
    )

    assert result["ok"] is True
    assert captured["command"] == "navigate_to_relative_pose"
    assert captured["args"] == (
        "--forward-m",
        "0.25",
        "--lateral-m",
        "-0.125",
        "--yaw-delta-deg",
        "15.0",
    )


def test_isaac_fake_worker_waypoint_navigation_updates_robot_view_pose(
    tmp_path: Path,
) -> None:
    backend = IsaacLabSubprocessBackend(
        run_dir=tmp_path,
        python_executable=Path(sys.executable),
        runtime_mode="fake",
        include_robot=True,
        generated_mess_count=1,
    )

    waypoint = {
        "waypoint_id": "generated_exploration_003",
        "room_id": "meeting_room_c",
        "frame_id": "map",
        "x": -3.0,
        "y": 7.0,
        "yaw": 1.57079632679,
    }
    nav = backend.navigate_to_waypoint(waypoint=waypoint)
    views = backend.write_robot_views_with_resolution(
        tmp_path / "robot_views_after_waypoint",
        label="0002_waypoint",
        width=64,
        height=48,
    )

    assert nav["ok"] is True
    assert nav["state_mutation"] == "isaac_waypoint_pose"
    assert nav["backend_pose_mutation_available"] is True
    assert nav["robot_pose"]["waypoint_id"] == "generated_exploration_003"
    assert nav["robot_pose"]["pose_source"] == "public_waypoint_map_frame"
    assert nav["robot_pose"]["x"] == pytest.approx(-3.0)
    assert nav["robot_pose"]["y"] == pytest.approx(7.0)
    assert nav["robot_pose"]["yaw_deg"] == pytest.approx(90.0)
    assert views["robot_pose"]["waypoint_id"] == "generated_exploration_003"
    assert views["robot_pose"]["pose_source"] != "hash_fallback_pose_near_receptacle"
    assert backend.semantic_pose_state["robot_pose"]["waypoint_id"] == ("generated_exploration_003")
    assert backend.semantic_pose_state["transform_events"][-1]["tool"] == ("navigate_to_waypoint")


def test_isaac_lab_backend_can_request_robot_view_aa_probe(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    backend = IsaacLabSubprocessBackend(
        run_dir=tmp_path,
        python_executable=Path(sys.executable),
        runtime_mode="fake",
        include_robot=True,
    )
    captured: dict[str, object] = {}

    def fake_run_worker(command: str, *args: str) -> dict[str, object]:
        captured["command"] = command
        captured["args"] = args
        return {"ok": True}

    monkeypatch.setattr(backend, "_run_worker", fake_run_worker)

    backend.write_robot_views_with_resolution(
        tmp_path / "robot_views",
        label="aa_probe",
        width=540,
        height=360,
        isaac_aa_op=2,
    )

    assert captured["command"] == "robot_views"
    assert "--isaac-aa-op" in captured["args"]
    assert captured["args"][-2:] == ("--isaac-aa-op", "2")


def test_isaac_lab_backend_can_request_robot_view_tonemap_probe(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    backend = IsaacLabSubprocessBackend(
        run_dir=tmp_path,
        python_executable=Path(sys.executable),
        runtime_mode="fake",
        include_robot=True,
    )
    captured: dict[str, object] = {}

    def fake_run_worker(command: str, *args: str) -> dict[str, object]:
        captured["command"] = command
        captured["args"] = args
        return {"ok": True}

    monkeypatch.setattr(backend, "_run_worker", fake_run_worker)

    backend.write_robot_views_with_resolution(
        tmp_path / "robot_views",
        label="tone_probe",
        width=540,
        height=360,
        isaac_tonemap_op=5,
    )

    assert captured["command"] == "robot_views"
    assert "--isaac-tonemap-op" in captured["args"]
    assert captured["args"][-2:] == ("--isaac-tonemap-op", "5")


def test_isaac_lab_backend_can_request_robot_view_exposure_probe(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    backend = IsaacLabSubprocessBackend(
        run_dir=tmp_path,
        python_executable=Path(sys.executable),
        runtime_mode="fake",
        include_robot=True,
    )
    captured: dict[str, object] = {}

    def fake_run_worker(command: str, *args: str) -> dict[str, object]:
        captured["command"] = command
        captured["args"] = args
        return {"ok": True}

    monkeypatch.setattr(backend, "_run_worker", fake_run_worker)

    backend.write_robot_views_with_resolution(
        tmp_path / "robot_views",
        label="exposure_probe",
        width=540,
        height=360,
        isaac_exposure_bias=-1.0,
    )

    assert captured["command"] == "robot_views"
    assert "--isaac-exposure-bias" in captured["args"]
    assert captured["args"][-2:] == ("--isaac-exposure-bias", "-1.0")


def test_isaac_lab_backend_can_request_robot_view_colorcorr_gain_probe(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    backend = IsaacLabSubprocessBackend(
        run_dir=tmp_path,
        python_executable=Path(sys.executable),
        runtime_mode="fake",
        include_robot=True,
    )
    captured: dict[str, object] = {}

    def fake_run_worker(command: str, *args: str) -> dict[str, object]:
        captured["command"] = command
        captured["args"] = args
        return {"ok": True}

    monkeypatch.setattr(backend, "_run_worker", fake_run_worker)

    backend.write_robot_views_with_resolution(
        tmp_path / "robot_views",
        label="colorcorr_probe",
        width=540,
        height=360,
        isaac_colorcorr_gain=(0.9, 0.8, 0.7),
    )

    assert captured["command"] == "robot_views"
    assert "--isaac-colorcorr-gain" in captured["args"]
    assert captured["args"][-2:] == ("--isaac-colorcorr-gain", "0.9,0.8,0.7")


def test_isaac_worker_can_request_semantic_filter_override(tmp_path: Path) -> None:
    args = isaac_lab_backend_worker.parse_args(
        [
            "--state-path",
            str(tmp_path / "state.json"),
            "init",
            "--run-dir",
            str(tmp_path),
            "--runtime-mode",
            "fake",
            "--enable-segmentation",
            "--segmentation-semantic-filter",
            "usd_prim_path",
        ]
    )

    assert getattr(args, "segmentation_semantic_filter") == ["usd_prim_path"]


def test_isaac_worker_hard_exits_after_deferred_app_success(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    exit_codes: list[int] = []

    def fake_exit(code: int) -> None:
        exit_codes.append(code)
        raise SystemExit(code)

    class BlockingClose:
        def close(self, **_: object) -> None:  # pragma: no cover - should not be called.
            raise AssertionError("deferred SimulationApp close should not run on success")

    monkeypatch.setattr(isaac_lab_backend_worker.os, "_exit", fake_exit)
    isaac_lab_backend_worker._DEFERRED_SIMULATION_APP = BlockingClose()

    with pytest.raises(SystemExit) as exc:
        isaac_lab_backend_worker._finish_command({"ok": True, "tool": "robot_views"})

    assert exc.value.code == 0
    assert exit_codes == [0]
    assert '"tool": "robot_views"' in capsys.readouterr().out
    assert isaac_lab_backend_worker._DEFERRED_SIMULATION_APP is not None
    isaac_lab_backend_worker._DEFERRED_SIMULATION_APP = None


def test_isaac_lab_backend_exposes_camera_control_request_api(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    backend = IsaacLabSubprocessBackend.__new__(IsaacLabSubprocessBackend)
    backend.state_path = tmp_path / "state.json"
    backend.python_executable = tmp_path / "python"
    captured: dict[str, object] = {}

    def fake_run_worker(command: str, *args: str) -> dict[str, object]:
        captured["command"] = command
        captured["args"] = args
        return {"ok": True}

    monkeypatch.setattr(backend, "_run_worker", fake_run_worker)
    request_path = tmp_path / "camera_control_request.json"
    request_path.write_text(
        json.dumps({"render_resolution": {"width": 960, "height": 640}, "views": []}),
        encoding="utf-8",
    )

    result = backend.render_camera_control_request(
        tmp_path / "camera_views",
        request_path=request_path,
    )

    assert result["ok"] is True
    assert captured["command"] == "camera_views"
    assert captured["args"] == (
        "--output-dir",
        str(tmp_path / "camera_views"),
        "--camera-request-path",
        str(request_path),
        "--render-width",
        "960",
        "--render-height",
        "640",
    )


def test_isaac_scene_camera_spec_uses_camera_control_orbit() -> None:
    spec = isaac_lab_backend_worker._isaac_scene_camera_view_spec(
        {
            "view_id": "view 01/table",
            "target": [2.7, 5.9, 1.0],
            "camera_orbit": {"distance_m": 4.4, "azimuth_deg": 225.0, "elevation_deg": 28.0},
            "lane_camera_orbits": {
                "isaaclab-prepared-usd": {
                    "distance_m": 4.4,
                    "azimuth_deg": 270.0,
                    "elevation_deg": 28.0,
                }
            },
            "camera_model": "anchor_orbit_lookat_camera_v1",
            "calibration_status": "anchor_orbit_relative_calibrated_v1",
            "lens": {"focal_length_mm": 24.0},
        },
        index=1,
    )

    assert spec["view_id"] == "view_01_table"
    assert spec["target"] == pytest.approx([2.7, 5.9, 1.0])
    assert spec["camera_model"] == "anchor_orbit_lookat_camera_v1"
    assert spec["calibration_status"] == "anchor_orbit_relative_calibrated_v1"
    assert spec["eye"][2] > spec["target"][2]
    assert spec["camera_orbit"]["azimuth_deg"] == 270.0
    assert spec["lens"] == {"focal_length_mm": 24.0}


def test_isaac_scene_camera_spec_honors_canonical_explicit_pose() -> None:
    spec = isaac_lab_backend_worker._isaac_scene_camera_view_spec(
        {
            "view_id": "view 01/table",
            "camera_model": "canonical_eye_target_camera_v1",
            "coordinate_frame": "molmospaces_scene_frame_v1",
            "robot_view_role": "fpv",
            "camera_basis": "robot_pose_eye_target",
            "camera_mode": "canonical_robot_fpv",
            "eye": [1.0, 2.0, 3.0],
            "target": [2.7, 5.9, 1.0],
            "usd_prim_path": "/val_1/Geometry/table_01",
            "backend_transforms": {
                "isaaclab-prepared-usd": {
                    "xy_scale": 1.0,
                    "rotation_z_deg": 0.0,
                    "translation": [0.0, 0.0, 0.0],
                }
            },
            "calibration_status": "canonical_scene_frame_similarity_fit_v1",
        },
        index=1,
    )

    assert spec["view_id"] == "view_01_table"
    assert spec["target"] == pytest.approx([2.7, 5.9, 1.0])
    assert spec["eye"] == pytest.approx([1.0, 2.0, 3.0])
    assert spec["backend_eye"] == pytest.approx([1.0, 2.0, 3.0])
    assert spec["target_source"] == "canonical_explicit_target"
    assert spec["robot_view_role"] == "fpv"
    assert spec["camera_basis"] == "robot_pose_eye_target"
    assert spec["camera_mode"] == "canonical_robot_fpv"
    assert spec["camera_model"] == "canonical_eye_target_camera_v1"
    assert spec["coordinate_frame"] == "molmospaces_scene_frame_v1"


@pytest.mark.parametrize(
    ("raw_spec", "message"),
    [
        (
            {
                "camera_model": "canonical_eye_target_camera_v1",
                "eye": [1.0, 2.0, 3.0],
                "target": [2.7, 5.9],
            },
            "target must be a 3-number vector",
        ),
        (
            {
                "camera_model": "canonical_eye_target_camera_v1",
                "eye": [1.0, False, 3.0],
                "target": [2.7, 5.9, 1.0],
            },
            r"eye\[1\] must be a finite number",
        ),
    ],
)
def test_isaac_scene_camera_spec_rejects_invalid_explicit_vectors(
    raw_spec: dict[str, object],
    message: str,
) -> None:
    with pytest.raises(ValueError, match=message):
        isaac_lab_backend_worker._isaac_scene_camera_view_spec(raw_spec, index=1)


def test_isaac_camera_lens_derives_horizontal_aperture_from_vertical_fov() -> None:
    aperture = isaac_lab_backend_worker._horizontal_aperture_from_lens(
        {"vertical_fov_deg": 45.0, "horizontal_aperture_mm": 20.955},
        width=960,
        height=640,
        focal_length=24.0,
    )

    assert aperture == pytest.approx(29.82337649)


def test_isaac_rby1m_head_camera_lens_matches_mujoco_vertical_fov() -> None:
    aperture = isaac_lab_backend_worker._horizontal_aperture_from_lens(
        {"vertical_fov_deg": isaac_lab_backend_worker.RBY1M_HEAD_CAMERA_VERTICAL_FOV_DEG},
        width=540,
        height=360,
        focal_length=isaac_lab_backend_worker.RBY1M_HEAD_CAMERA_FOCAL_LENGTH_MM,
    )
    metadata = isaac_lab_backend_worker._usd_camera_fov_metadata(
        focal_length=isaac_lab_backend_worker.RBY1M_HEAD_CAMERA_FOCAL_LENGTH_MM,
        horizontal_aperture=aperture,
        width=540,
        height=360,
    )

    assert aperture == pytest.approx(29.82337649)
    assert metadata["vertical_fov_deg"] == pytest.approx(45.0)


def test_isaac_rby1m_chase_camera_matches_mujoco_follower_pitch() -> None:
    eye, target = isaac_lab_backend_worker._robot_relative_chase_eye_target(
        {"x": 0.0, "y": 0.0, "z": 0.0, "yaw_deg": 0.0}
    )
    forward = tuple(target[index] - eye[index] for index in range(3))
    horizontal_distance = math.hypot(forward[0], forward[1])
    vertical_drop = -forward[2]

    assert eye == pytest.approx(isaac_lab_backend_worker.RBY1M_CHASE_CAMERA_OFFSET_M)
    assert target == pytest.approx(isaac_lab_backend_worker.RBY1M_CHASE_CAMERA_TARGET_OFFSET_M)
    assert horizontal_distance == pytest.approx(vertical_drop)
    assert math.degrees(math.atan2(vertical_drop, horizontal_distance)) == pytest.approx(45.0)
    assert horizontal_distance == pytest.approx(1.0)


class _FakeSceneCameraSim:
    device = "cpu"

    def __init__(self) -> None:
        self.steps = 0

    def reset(self) -> None:
        self.steps = 0

    def step(self) -> None:
        self.steps += 1

    def get_physics_dt(self) -> float:
        return 1 / 60


class _FakeSceneCameraSimUtils:
    @staticmethod
    def create_prim(*_args: object, **_kwargs: object) -> None:
        return None

    class PinholeCameraCfg:
        def __init__(self, **kwargs: object) -> None:
            self.kwargs = kwargs


class _FakeSceneCameraCfg:
    def __init__(self, **kwargs: object) -> None:
        self.kwargs = kwargs


class _FakeSceneCameraTensor:
    def __init__(self, array: object) -> None:
        self._array = array

    def detach(self) -> "_FakeSceneCameraTensor":
        return self

    def cpu(self) -> "_FakeSceneCameraTensor":
        return self

    def numpy(self) -> object:
        return self._array


def _fake_scene_camera_type(np: object) -> type:
    class _FakeCamera:
        def __init__(self, cfg: _FakeSceneCameraCfg) -> None:
            self.cfg = cfg
            self.data = SimpleNamespace(output={})

        def set_world_poses_from_view(self, *_args: object, **_kwargs: object) -> None:
            return None

        def update(self, *, dt: float) -> None:
            del dt
            frame = np.full((1, 4, 6, 3), 250, dtype=np.uint8)
            frame[:, 0, 0, :] = 230
            self.data.output["rgb"] = _FakeSceneCameraTensor(frame)

    return _FakeCamera


class _FakeSceneCameraTorch:
    float32 = "float32"

    @staticmethod
    def tensor(value: object, **_kwargs: object) -> object:
        return value


def _unit_scene_camera_request() -> dict[str, object]:
    return {
        "camera_model": "canonical_eye_target_camera_v1",
        "views": [
            {
                "view_id": "fpv",
                "eye": [0.0, 0.0, 1.0],
                "target": [1.0, 0.0, 1.0],
            }
        ],
    }


def test_isaac_scene_camera_capture_applies_color_profile(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import numpy as np

    monkeypatch.setattr(
        isaac_lab_backend_worker,
        "_ensure_capture_lighting",
        lambda *_args, **_kwargs: {"status": "unit_lighting_skipped"},
    )

    result = isaac_lab_backend_worker._capture_scene_camera_request_with_existing_sim(
        camera_request=_unit_scene_camera_request(),
        output_dir=tmp_path,
        width=6,
        height=4,
        sim=_FakeSceneCameraSim(),
        sim_utils=_FakeSceneCameraSimUtils,
        stage_utils=SimpleNamespace(),
        camera_type=_fake_scene_camera_type(np),
        camera_cfg_type=_FakeSceneCameraCfg,
        torch=_FakeSceneCameraTorch,
        np=np,
        scene_bounds={},
    )

    assert result["color_profile"]["profile_id"] == "display_srgb_soft_highlight_v1"
    assert result["color_management"]["fpv"]["before"]["overexposed_fraction"] > 0.9
    assert result["color_management"]["fpv"]["after"]["overexposed_fraction"] == pytest.approx(0.0)
    assert result["color_management"]["fpv"]["backend_luminance_gain"]["backend"] == (
        "isaaclab-prepared-usd"
    )
    assert result["color_management"]["fpv"]["backend_luminance_gain"]["gain"] == pytest.approx(
        0.7161647108631373
    )
    assert result["native_render_diagnostics"]["schema"] == "isaac_native_render_diagnostics_v1"
    assert result["native_render_diagnostics"]["view_kind"] == "scene_camera_request"
    assert result["native_render_diagnostics"]["settings_mutation_attempted"] is False
    assert result["native_render_diagnostics"]["default_render_settings_changed"] is False
    assert result["native_render_diagnostics"]["post_render_comparison_profile"]["source"] == (
        "not_a_native_renderer_setting"
    )
    assert Path(result["images"]["fpv"]).is_file()


def test_isaac_robot_view_color_profile_merges_comparison_override() -> None:
    profile = isaac_lab_backend_worker._robot_view_color_profile(
        {
            "backend_rgb_gain": {"isaaclab_subprocess": [0.9, 0.8, 0.7]},
            "backend_rgb_gain_source": "unit-comparison-profile",
        }
    )

    assert profile["profile_id"] == "display_srgb_soft_highlight_v1"
    assert profile["backend_luminance_gain"]["isaaclab_subprocess"] == pytest.approx(1.0)
    assert profile["backend_luminance_gain"]["isaaclab-prepared-usd"] == pytest.approx(1.0)
    assert profile["backend_luminance_gain_source"] == (
        "robot_view_display_default_no_scene_probe_delta"
    )
    assert profile["backend_rgb_gain"]["isaaclab_subprocess"] == pytest.approx([0.9, 0.8, 0.7])
    assert profile["backend_rgb_gain_source"] == "unit-comparison-profile"


def test_isaac_worker_waypoint_navigation_prefers_b1_pose(tmp_path: Path) -> None:
    state_path = tmp_path / "state.json"
    state = {
        "schema": "isaac_lab_backend_state_v1",
        "backend": ISAACLAB_SUBPROCESS_BACKEND,
        "primitive_provenance": ISAAC_SEMANTIC_POSE_PROVENANCE,
        "runtime": {"runtime_mode": "fake"},
        "scenario": {"objects": [], "receptacles": []},
        "locations": {},
        "held_object_id": None,
        "current_receptacle_id": "floor_01",
        "open_receptacle_ids": [],
        "containment": {},
        "object_pose_overrides": {},
        "tool_event_counts": {},
        "object_index": {},
        "receptacle_index": {},
        "semantic_pose_state": {
            "schema": ISAAC_SEMANTIC_POSE_STATE_SCHEMA,
            "robot_pose": {
                "frame": "world",
                "x": 1.36,
                "y": 1.82,
                "z": 0.0,
                "yaw_deg": 23.0,
                "pose_source": "hash_fallback_pose_near_receptacle",
            },
            "object_poses": {},
            "articulations": {},
            "transform_events": [],
        },
    }
    isaac_lab_backend_worker.write_state(state_path, state)

    args = isaac_lab_backend_worker.parse_args(
        [
            "--state-path",
            str(state_path),
            "navigate_to_waypoint",
            "--waypoint-json",
            json.dumps(
                {
                    "waypoint_id": "b1_overlay_anchor_001",
                    "room_id": "meeting_room_b",
                    "frame_id": "map",
                    "x": -2.0,
                    "y": 0.0,
                    "yaw": 0.0,
                    "b1_pose": {
                        "frame": "b1_rebuilt_scene_usd_world_candidate",
                        "x": -42.5,
                        "y": 13.25,
                        "z": 0.0,
                        "yaw_deg": 90.0,
                        "pose_source": "robot_map_12_navigation_memory_overlay",
                    },
                },
                sort_keys=True,
            ),
        ]
    )

    result = isaac_lab_backend_worker.navigate_to_waypoint(
        args,
        isaac_lab_backend_worker.read_state(state_path),
    )
    updated = isaac_lab_backend_worker.read_state(state_path)

    assert result["ok"] is True
    assert result["state_mutation"] == "isaac_waypoint_pose"
    assert result["robot_pose"]["frame"] == "b1_rebuilt_scene_usd_world_candidate"
    assert result["robot_pose"]["x"] == pytest.approx(-42.5)
    assert result["robot_pose"]["y"] == pytest.approx(13.25)
    assert result["robot_pose"]["yaw_deg"] == pytest.approx(90.0)
    assert result["robot_pose"]["waypoint_pose_key"] == "b1_pose"
    assert updated["semantic_pose_state"]["robot_pose"] == result["robot_pose"]
    assert updated["semantic_pose_state"]["transform_events"][-1]["waypoint_id"] == (
        "b1_overlay_anchor_001"
    )
    assert updated["semantic_pose_state"]["rendered_to_usd"] is False


def test_isaac_worker_relative_pose_navigation_updates_semantic_robot_pose(
    tmp_path: Path,
) -> None:
    state_path = tmp_path / "state.json"
    state = {
        "schema": "isaac_lab_backend_state_v1",
        "backend": ISAACLAB_SUBPROCESS_BACKEND,
        "primitive_provenance": ISAAC_SEMANTIC_POSE_PROVENANCE,
        "runtime": {"runtime_mode": "fake"},
        "scenario": {"objects": [], "receptacles": []},
        "locations": {},
        "held_object_id": None,
        "current_receptacle_id": "",
        "current_waypoint_id": "b1_overlay_anchor_001",
        "current_room_id": "meeting_room_b",
        "open_receptacle_ids": [],
        "containment": {},
        "object_pose_overrides": {},
        "tool_event_counts": {},
        "object_index": {},
        "receptacle_index": {},
        "semantic_pose_state": {
            "schema": ISAAC_SEMANTIC_POSE_STATE_SCHEMA,
            "robot_pose": {
                "frame": "world",
                "x": 1.0,
                "y": 2.0,
                "z": 0.0,
                "yaw_deg": 90.0,
                "pose_source": "unit_test_start",
            },
            "object_poses": {},
            "articulations": {},
            "transform_events": [],
        },
    }
    isaac_lab_backend_worker.write_state(state_path, state)

    args = isaac_lab_backend_worker.parse_args(
        [
            "--state-path",
            str(state_path),
            "navigate_to_relative_pose",
            "--forward-m",
            "0.5",
            "--lateral-m",
            "-0.25",
            "--yaw-delta-deg",
            "15",
        ]
    )

    result = isaac_lab_backend_worker.navigate_to_relative_pose(
        args,
        isaac_lab_backend_worker.read_state(state_path),
    )
    updated = isaac_lab_backend_worker.read_state(state_path)

    assert result["ok"] is True
    assert result["tool"] == "navigate_to_relative_pose"
    assert result["pose_source"] == "relative_robot_frame"
    assert result["applied_delta"] == {
        "forward_m": 0.5,
        "lateral_m": -0.25,
        "yaw_delta_deg": 15.0,
    }
    assert result["robot_pose"]["x"] == pytest.approx(1.25)
    assert result["robot_pose"]["y"] == pytest.approx(2.5)
    assert result["robot_pose"]["yaw_deg"] == pytest.approx(105.0)
    assert updated["semantic_pose_state"]["robot_pose"] == result["robot_pose"]
    assert updated["semantic_pose_state"]["transform_events"][-1]["waypoint_id"] == (
        "b1_overlay_anchor_001"
    )
    assert updated["robot_trajectory"][-1] == result["robot_pose"]


def test_isaac_write_camera_views_returns_color_contract(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    state_path = tmp_path / "state.json"
    scene_usd = tmp_path / "scene.usda"
    scene_usd.write_text("#usda 1.0\n", encoding="utf-8")
    state = {
        "runtime": {"runtime_mode": "real"},
        "scene_usd": str(scene_usd),
        "tool_event_counts": {},
    }
    state_path.write_text(json.dumps(state), encoding="utf-8")
    request_path = tmp_path / "camera_control_request.json"
    request_path.write_text(
        json.dumps(
            {
                "camera_model": "canonical_eye_target_camera_v1",
                "render_resolution": {"width": 6, "height": 4},
                "color_profile": {"profile_id": "display_srgb_soft_highlight_v1"},
                "views": [
                    {
                        "view_id": "fpv",
                        "eye": [0.0, 0.0, 1.0],
                        "target": [1.0, 0.0, 1.0],
                    }
                ],
            }
        ),
        encoding="utf-8",
    )

    def fake_capture_scene_camera_views(
        *,
        scene_usd: Path,
        camera_request: dict[str, object],
        output_dir: Path,
        width: int,
        height: int,
        semantic_pose_state: dict[str, object] | None = None,
    ) -> dict[str, object]:
        assert semantic_pose_state == {}
        output_path = output_dir / "fpv.png"
        _write_nonblank_image(output_path)
        return {
            "camera_control_api": "roboclaws.camera_control.render_views",
            "camera_request_schema": camera_request.get("schema"),
            "calibration_status": camera_request.get("calibration_status"),
            "lighting_profile": camera_request.get("lighting_profile"),
            "lighting_diagnostics": {"status": "unit"},
            "color_profile": camera_request.get("color_profile"),
            "color_management": {
                "fpv": {
                    "after": {"overexposed_fraction": 0.0},
                }
            },
            "native_render_diagnostics": {
                "schema": "isaac_native_render_diagnostics_v1",
                "status": "captured",
                "settings_api_available": True,
                "default_render_settings_changed": False,
            },
            "lens": camera_request.get("lens"),
            "derived_lens": {"horizontal_aperture_mm": 29.8},
            "views": [
                {
                    "view_id": "fpv",
                    "camera_model": "canonical_eye_target_camera_v1",
                    "image_path": str(output_path),
                }
            ],
            "images": {"fpv": str(output_path)},
            "shapes": {"fpv": [height, width, 3]},
            "scene_bounds": {},
            "render_steps": 1,
            "scene_usd": str(scene_usd),
        }

    monkeypatch.setattr(
        isaac_lab_backend_worker,
        "capture_scene_camera_views",
        fake_capture_scene_camera_views,
    )

    result = isaac_lab_backend_worker.write_camera_views(
        isaac_lab_backend_worker.parse_args(
            [
                "--state-path",
                str(state_path),
                "camera_views",
                "--output-dir",
                str(tmp_path / "camera_views"),
                "--camera-request-path",
                str(request_path),
            ]
        ),
        isaac_lab_backend_worker.read_state(state_path),
    )

    assert result["ok"] is True
    assert result["color_profile"]["profile_id"] == "display_srgb_soft_highlight_v1"
    assert result["color_management"]["fpv"]["after"]["overexposed_fraction"] == 0.0
    assert result["native_render_diagnostics"]["schema"] == "isaac_native_render_diagnostics_v1"
    assert result["native_render_diagnostics"]["default_render_settings_changed"] is False


def test_isaac_native_render_diagnostics_reads_available_settings(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class _FakeSettings:
        values = {
            "/rtx/post/tonemap/op": "aces",
            "/rtx/post/histogram/autoExposure/enabled": False,
            "/rtx/post/camera/iso": 100,
            "/rtx/post/ocio/view": "sRGB",
            "/rtx/post/colorcorr/enabled": False,
            "/rtx/post/colorGrading/enabled": False,
            "/renderer/active": "RayTracedLighting",
        }

        def get(self, path: str) -> object:
            return self.values.get(path)

    monkeypatch.setattr(
        isaac_lab_backend_worker,
        "_isaac_settings_interface",
        lambda: _FakeSettings(),
    )

    diagnostics = isaac_lab_backend_worker._isaac_native_render_diagnostics(
        renderer_mode="isaac_lab_headless_rtx",
        capture_method="isaac_lab_camera_rgb",
        view_kind="robot_views",
        render_resolution={"width": 540, "height": 360},
        camera_prim_paths=["/World/robot_0/head_camera"],
        render_product_paths=["/Render/Product/Fpv"],
        isaac_lab_isp_active=False,
    )

    assert diagnostics["schema"] == "isaac_native_render_diagnostics_v1"
    assert diagnostics["status"] == "captured"
    assert diagnostics["settings_api_available"] is True
    assert diagnostics["tone_mapping"]["operator"]["value"] == "aces"
    assert diagnostics["camera_exposure"]["auto_exposure_enabled"]["value"] is False
    assert diagnostics["camera_exposure"]["iso"]["value"] == 100
    assert diagnostics["tone_mapping"]["exposure_value"]["status"] == "not_available"
    assert diagnostics["ocio"]["view"]["value"] == "sRGB"
    assert diagnostics["renderer"]["renderer"]["value"] == "RayTracedLighting"
    assert diagnostics["camera_prim_paths"] == ["/World/robot_0/head_camera"]
    assert diagnostics["render_product_paths"] == ["/Render/Product/Fpv"]
    assert diagnostics["isaac_lab_isp_active"] is False
    assert diagnostics["settings_mutation_attempted"] is False
    assert diagnostics["default_render_settings_changed"] is False


def test_isaac_capture_quality_aa_probe_records_set_and_restore() -> None:
    class _FakeSettings:
        def __init__(self) -> None:
            self.values = {"/rtx/post/aa/op": 3}
            self.set_calls: list[tuple[str, object]] = []

        def get(self, path: str) -> object:
            return self.values.get(path)

        def set(self, path: str, value: object) -> None:
            self.set_calls.append((path, value))
            self.values[path] = value

    settings = _FakeSettings()

    mutation = isaac_lab_backend_worker._apply_isaac_capture_quality_overrides(
        settings=settings,
        isaac_aa_op=2,
        isaac_tonemap_op=None,
    )
    capture_quality = isaac_lab_backend_worker._capture_quality_settings(
        render_settle_frames=0,
        settings=settings,
        settings_mutation=mutation,
    )
    restored = isaac_lab_backend_worker._restore_isaac_capture_quality_overrides(
        settings=settings,
        mutation=mutation,
    )

    assert settings.set_calls == [("/rtx/post/aa/op", 2), ("/rtx/post/aa/op", 3)]
    assert capture_quality["settings_mutation_attempted"] is True
    assert capture_quality["default_render_settings_changed"] is True
    assert capture_quality["anti_aliasing"]["status"] == "applied"
    assert capture_quality["anti_aliasing"]["previous_value"] == 3
    assert capture_quality["anti_aliasing"]["requested_value"] == 2
    assert restored["restore_status"] == "restored"
    assert restored["settings"]["anti_aliasing"]["restore_status"] == "restored"


def test_isaac_native_tonemap_probe_records_set_and_restore() -> None:
    class _FakeSettings:
        def __init__(self) -> None:
            self.values = {"/rtx/post/tonemap/op": 6}
            self.set_calls: list[tuple[str, object]] = []

        def get(self, path: str) -> object:
            return self.values.get(path)

        def set(self, path: str, value: object) -> None:
            self.set_calls.append((path, value))
            self.values[path] = value

    settings = _FakeSettings()

    mutation = isaac_lab_backend_worker._apply_isaac_capture_quality_overrides(
        settings=settings,
        isaac_aa_op=None,
        isaac_tonemap_op=5,
    )
    capture_quality = isaac_lab_backend_worker._capture_quality_settings(
        render_settle_frames=0,
        settings=settings,
        settings_mutation=mutation,
    )
    restored = isaac_lab_backend_worker._restore_isaac_capture_quality_overrides(
        settings=settings,
        mutation=mutation,
    )

    assert settings.set_calls == [("/rtx/post/tonemap/op", 5), ("/rtx/post/tonemap/op", 6)]
    assert capture_quality["settings_mutation_attempted"] is True
    assert capture_quality["default_render_settings_changed"] is True
    assert capture_quality["settings_mutation"]["settings"]["tonemap_operator"]["status"] == (
        "applied"
    )
    assert restored["restore_status"] == "restored"
    assert restored["settings"]["tonemap_operator"]["restore_status"] == "restored"


def test_isaac_native_exposure_probe_records_set_and_restore() -> None:
    class _FakeSettings:
        def __init__(self) -> None:
            self.values = {"/rtx/post/tonemap/exposureBias": 0.0}
            self.set_calls: list[tuple[str, object]] = []

        def get(self, path: str) -> object:
            return self.values.get(path)

        def set(self, path: str, value: object) -> None:
            self.set_calls.append((path, value))
            self.values[path] = value

    settings = _FakeSettings()

    mutation = isaac_lab_backend_worker._apply_isaac_capture_quality_overrides(
        settings=settings,
        isaac_aa_op=None,
        isaac_tonemap_op=None,
        isaac_exposure_bias=-1.0,
    )
    capture_quality = isaac_lab_backend_worker._capture_quality_settings(
        render_settle_frames=0,
        settings=settings,
        settings_mutation=mutation,
    )
    restored = isaac_lab_backend_worker._restore_isaac_capture_quality_overrides(
        settings=settings,
        mutation=mutation,
    )

    assert settings.set_calls == [
        ("/rtx/post/tonemap/exposureBias", -1.0),
        ("/rtx/post/tonemap/exposureBias", 0.0),
    ]
    assert capture_quality["settings_mutation_attempted"] is True
    assert capture_quality["default_render_settings_changed"] is True
    assert capture_quality["settings_mutation"]["settings"]["exposure_bias"]["status"] == (
        "applied"
    )
    assert restored["restore_status"] == "restored"
    assert restored["settings"]["exposure_bias"]["restore_status"] == "restored"


def test_isaac_native_colorcorr_gain_probe_records_set_and_restore() -> None:
    class _FakeSettings:
        def __init__(self) -> None:
            self.values = {
                "/rtx/post/colorcorr/enabled": False,
                "/rtx/post/colorcorr/gain": [1.0, 1.0, 1.0],
            }
            self.set_calls: list[tuple[str, object]] = []

        def get(self, path: str) -> object:
            return self.values.get(path)

        def set(self, path: str, value: object) -> None:
            self.set_calls.append((path, value))
            self.values[path] = value

    settings = _FakeSettings()

    mutation = isaac_lab_backend_worker._apply_isaac_capture_quality_overrides(
        settings=settings,
        isaac_aa_op=None,
        isaac_tonemap_op=None,
        isaac_exposure_bias=None,
        isaac_colorcorr_gain=(0.9, 0.8, 0.7),
    )
    capture_quality = isaac_lab_backend_worker._capture_quality_settings(
        render_settle_frames=0,
        settings=settings,
        settings_mutation=mutation,
    )
    restored = isaac_lab_backend_worker._restore_isaac_capture_quality_overrides(
        settings=settings,
        mutation=mutation,
    )

    assert settings.set_calls == [
        ("/rtx/post/colorcorr/enabled", True),
        ("/rtx/post/colorcorr/gain", [0.9, 0.8, 0.7]),
        ("/rtx/post/colorcorr/enabled", False),
        ("/rtx/post/colorcorr/gain", [1.0, 1.0, 1.0]),
    ]
    assert capture_quality["settings_mutation_attempted"] is True
    assert capture_quality["default_render_settings_changed"] is True
    assert capture_quality["settings_mutation"]["settings"]["colorcorr_enabled"]["status"] == (
        "applied"
    )
    assert capture_quality["settings_mutation"]["settings"]["colorcorr_gain"]["status"] == (
        "applied"
    )
    assert restored["restore_status"] == "restored"
    assert restored["settings"]["colorcorr_enabled"]["restore_status"] == "restored"
    assert restored["settings"]["colorcorr_gain"]["restore_status"] == "restored"


def test_isaac_camera_render_product_paths_are_extracted() -> None:
    camera = SimpleNamespace(
        render_product_path="/Render/Product/Fpv",
        data=SimpleNamespace(render_product_paths=["/Render/Product/Chase"]),
    )

    paths = isaac_lab_backend_worker._camera_render_product_paths(camera)

    assert paths == ["/Render/Product/Fpv", "/Render/Product/Chase"]


def test_isaac_scene_camera_spec_records_usd_bounds(monkeypatch: pytest.MonkeyPatch) -> None:
    class _FakePrim:
        def IsValid(self) -> bool:
            return True

    class _FakeStage:
        def GetPrimAtPath(self, _path: str) -> _FakePrim:
            return _FakePrim()

    class _StageUtils:
        @staticmethod
        def get_current_stage() -> _FakeStage:
            return _FakeStage()

    class _FakeAlignedBox:
        def GetMin(self) -> list[float]:
            return [2.0, 5.0, 0.3]

        def GetMax(self) -> list[float]:
            return [3.0, 6.0, 1.2]

    class _FakeWorldBound:
        def ComputeAlignedBox(self) -> _FakeAlignedBox:
            return _FakeAlignedBox()

    class _FakeBBoxCache:
        def __init__(self, *_args: object, **_kwargs: object) -> None:
            pass

        def ComputeWorldBound(self, _prim: _FakePrim) -> _FakeWorldBound:
            return _FakeWorldBound()

    fake_pxr = types.SimpleNamespace(
        Usd=types.SimpleNamespace(TimeCode=types.SimpleNamespace(Default=lambda: object())),
        UsdGeom=types.SimpleNamespace(
            BBoxCache=_FakeBBoxCache,
            Tokens=types.SimpleNamespace(default_="default", render="render", proxy="proxy"),
        ),
    )
    monkeypatch.setitem(sys.modules, "pxr", fake_pxr)

    spec = isaac_lab_backend_worker._isaac_scene_camera_view_spec(
        {
            "view_id": "view 01/table",
            "camera_model": "canonical_eye_target_camera_v1",
            "eye": [1.0, 2.0, 3.0],
            "target": [2.7, 5.9, 1.0],
            "usd_prim_path": "/val_1/Geometry/table_01",
        },
        index=1,
        stage_utils=_StageUtils(),
    )

    assert spec["usd_bounds_target"] == pytest.approx([2.5, 5.5, 0.75])
    assert spec["usd_bounds"]["min"] == pytest.approx([2.0, 5.0, 0.3])
    assert spec["usd_bounds"]["max"] == pytest.approx([3.0, 6.0, 1.2])
    assert spec["usd_bounds"]["center"] == pytest.approx([2.5, 5.5, 0.75])


def test_isaac_support_pose_uses_usd_world_bounds_center() -> None:
    support = isaac_lab_backend_worker._support_pose_from_usd_bounds(
        {
            "center": [2.5, 5.5, 0.75],
            "max": [3.0, 6.0, 1.2],
            "size": [1.0, 2.0, 0.9],
        },
        fallback={"frame": "world", "x": 99.0, "y": 99.0, "z": 0.0, "yaw_deg": 45.0},
    )

    assert support is not None
    assert support["frame"] == "usd_world"
    assert support["x"] == pytest.approx(2.5)
    assert support["y"] == pytest.approx(5.5)
    assert support["z"] == pytest.approx(1.2)
    assert support["yaw_deg"] == pytest.approx(45.0)
    assert support["support_radius_m"] == pytest.approx(1.0)
    assert support["source"] == "usd_world_bounds_top_center"


def test_isaac_robot_pose_prefers_bound_receptacle_support_pose() -> None:
    state = {
        "scene_binding_diagnostics": {
            "selected_target_receptacle_bindings": {
                "sink_01": {
                    "status": "bound",
                    "usd_handle": "real_sink",
                    "usd_prim_path": "/val_1/Geometry/real_sink",
                }
            }
        },
        "receptacle_index": {
            "real_sink": {
                "support_pose": {
                    "frame": "usd_world",
                    "x": 2.5,
                    "y": 5.5,
                    "z": 0.75,
                    "source": "usd_world_bounds_top_center",
                    "support_radius_m": 0.8,
                },
                "usd_world_bounds": {"center": [2.5, 5.5, 0.75]},
            }
        },
        "object_index": {
            "bowl_01": {
                "usd_world_bounds": {"center": [4.5, 7.5, 0.9]},
            }
        },
    }

    pose = isaac_lab_backend_worker._robot_pose_for_receptacle(state, "sink_01")

    assert pose["frame"] == "molmospaces_scene_frame_v1"
    assert pose["schema"] == "cleanup_robot_pose_result_v1"
    assert pose["pose_source"] == "roboclaws_shared_scene_frame_support_pose"
    assert pose["pose_request"]["schema"] == "cleanup_robot_pose_request_v1"
    assert pose["pose_request"]["resolver"] == "roboclaws.cleanup_robot_pose.near_target_v1"
    assert pose["support_pose_source"] == "usd_world_bounds_top_center"
    assert pose["target_position"] == pytest.approx([2.5, 5.5, 0.75])
    distance_to_target = math.hypot(pose["x"] - 2.5, pose["y"] - 5.5)
    assert distance_to_target == pytest.approx(1.15)


def test_isaac_support_placement_resolver_uses_usd_bounds() -> None:
    state = {
        "scenario": {
            "objects": [
                {
                    "object_id": "mug_01",
                    "name": "mug",
                    "category": "dish",
                    "location_id": "sofa_01",
                    "pickupable": True,
                }
            ],
            "receptacles": [
                {
                    "receptacle_id": "sink_01",
                    "name": "sink",
                    "category": "Sink",
                    "room_area": "kitchen",
                }
            ],
        },
        "locations": {"mug_01": "sofa_01"},
        "containment": {},
        "object_pose_overrides": {},
        "object_index": _unit_isaac_object_index(),
        "receptacle_index": _unit_isaac_receptacle_index(),
        "scene_binding_diagnostics": {
            "selected_object_bindings": {
                "mug_01": {
                    "status": "bound",
                    "usd_handle": "mug_01",
                    "usd_prim_path": "/World/Objects/mug_01",
                }
            },
            "selected_target_receptacle_bindings": {
                "sink_01": {
                    "status": "bound",
                    "usd_handle": "sink_01",
                    "usd_prim_path": "/World/Receptacles/sink_01",
                }
            },
        },
    }

    resolution = isaac_lab_backend_worker._resolve_isaac_placement(
        state,
        object_id="mug_01",
        receptacle_id="sink_01",
        index=0,
        relation="on",
        source="unit",
    )

    assert resolution["support_status"] == "direct_support"
    assert resolution["contact_proof"] == "usd_bounds_direct_support"
    assert resolution["position"] == pytest.approx([2.5, 5.5, 1.615])
    assert resolution["object_bottom_offset_m"] == pytest.approx(0.4)
    assert resolution["support_clearance_m"] == pytest.approx(0.015)
    diagnostic = isaac_lab_backend_worker._isaac_placement_diagnostic(
        state=state,
        object_id="mug_01",
        receptacle_id="sink_01",
        relation="on",
        source="unit",
        placement_resolution=resolution,
    )
    assert diagnostic["schema"] == "molmospaces_semantic_placement_diagnostic_v1"
    assert diagnostic["direct_support_proven"] is True
    assert diagnostic["support_surface_top_z"] == pytest.approx(1.2)


def test_isaac_receptacle_support_surfaces_prefer_broad_lower_descendant() -> None:
    class _FakePrim:
        def __init__(
            self,
            path: str,
            *,
            type_name: str = "Mesh",
            children: list["_FakePrim"] | None = None,
        ) -> None:
            self._path = path
            self._type_name = type_name
            self.children = children or []

        def GetPath(self) -> str:
            return self._path

        def GetTypeName(self) -> str:
            return self._type_name

        def IsA(self, _type: object) -> bool:
            return self._type_name == "Mesh"

    mattress = _FakePrim("/World/Receptacles/bed_01/Geometry/mattress")
    bedsheet = _FakePrim("/World/Receptacles/bed_01/Geometry/bedsheet")
    headboard = _FakePrim("/World/Receptacles/bed_01/Geometry/headboard")
    rail = _FakePrim("/World/Receptacles/bed_01/Geometry/rail")
    bed = _FakePrim(
        "/World/Receptacles/bed_01",
        type_name="Xform",
        children=[mattress, bedsheet, headboard, rail],
    )
    bounds_by_path = {
        "/World/Receptacles/bed_01": {
            "center": [2.0, 3.0, 0.85],
            "min": [0.8, 1.8, 0.0],
            "max": [3.2, 4.2, 1.7],
            "size": [2.4, 2.4, 1.7],
        },
        "/World/Receptacles/bed_01/Geometry/mattress": {
            "center": [2.0, 3.0, 0.45],
            "min": [0.9, 1.9, 0.2],
            "max": [3.1, 4.1, 0.7],
            "size": [2.2, 2.2, 0.5],
        },
        "/World/Receptacles/bed_01/Geometry/bedsheet": {
            "center": [2.05, 3.02, 0.43],
            "min": [0.95, 1.92, 0.2],
            "max": [3.15, 4.12, 0.66],
            "size": [2.2, 2.2, 0.46],
        },
        "/World/Receptacles/bed_01/Geometry/headboard": {
            "center": [2.0, 4.15, 0.85],
            "min": [0.8, 4.05, 0.0],
            "max": [3.2, 4.25, 1.7],
            "size": [2.4, 0.2, 1.7],
        },
        "/World/Receptacles/bed_01/Geometry/rail": {
            "center": [0.86, 3.0, 0.7],
            "min": [0.8, 1.8, 0.0],
            "max": [0.92, 4.2, 1.4],
            "size": [0.12, 2.4, 1.4],
        },
    }
    original_usd_world_bounds = isaac_lab_backend_worker._usd_world_bounds
    original_iter_usd_prim_range = isaac_lab_backend_worker._iter_usd_prim_range
    isaac_lab_backend_worker._usd_world_bounds = (  # type: ignore[method-assign]
        lambda prim, *, usd_geom: bounds_by_path[str(prim.GetPath())]
    )
    isaac_lab_backend_worker._iter_usd_prim_range = lambda prim: [  # type: ignore[method-assign]
        prim,
        *getattr(prim, "children", []),
    ]

    try:
        surfaces = isaac_lab_backend_worker._usd_receptacle_support_surfaces(
            prim=bed,
            usd_geom=SimpleNamespace(Gprim=object),
        )
    finally:
        isaac_lab_backend_worker._usd_world_bounds = original_usd_world_bounds  # type: ignore[method-assign]
        isaac_lab_backend_worker._iter_usd_prim_range = original_iter_usd_prim_range  # type: ignore[method-assign]

    assert surfaces[0]["source"] == "isaac_usd_descendant_support_surface_union"
    assert surfaces[0]["top_z"] == pytest.approx(0.7)
    assert surfaces[1]["surface_id"] in {
        "/World/Receptacles/bed_01/Geometry/mattress",
        "/World/Receptacles/bed_01/Geometry/bedsheet",
    }
    assert surfaces[1]["source"] == "isaac_usd_descendant_support_surface"
    assert all("headboard" not in item["surface_id"] for item in surfaces[:2])


def test_isaac_support_placement_resolver_uses_descendant_support_surface() -> None:
    state = {
        "scenario": {
            "objects": [
                {
                    "object_id": "bowl_01",
                    "name": "bowl",
                    "category": "dish",
                    "location_id": "sink_01",
                    "pickupable": True,
                }
            ],
            "receptacles": [
                {
                    "receptacle_id": "bed_01",
                    "name": "bed",
                    "category": "Bed",
                    "room_area": "bedroom",
                }
            ],
        },
        "locations": {"bowl_01": "sink_01"},
        "containment": {},
        "object_pose_overrides": {},
        "object_index": {
            "bowl_01": {
                "usd_prim_path": "/World/Objects/bowl_01",
                "category": "Bowl",
                "public_label": "bowl_01",
                "usd_world_bounds": {
                    "center": [0.0, 0.0, 0.1],
                    "min": [-0.1, -0.1, 0.0],
                    "max": [0.1, 0.1, 0.2],
                    "size": [0.2, 0.2, 0.2],
                },
            }
        },
        "receptacle_index": {
            "bed_01": {
                "usd_prim_path": "/World/Receptacles/bed_01",
                "category": "Bed",
                "public_label": "bed_01",
                "usd_world_bounds": {
                    "center": [2.0, 3.0, 0.85],
                    "min": [0.8, 1.8, 0.0],
                    "max": [3.2, 4.2, 1.7],
                    "size": [2.4, 2.4, 1.7],
                },
                "support_surfaces": [
                    {
                        "surface_id": "/World/Receptacles/bed_01/Geometry/support_union",
                        "center": [2.0, 3.0],
                        "top_z": 0.7,
                        "half_extents": [1.1, 1.1],
                        "area_m2": 4.84,
                        "source": "isaac_usd_descendant_support_surface_union",
                    }
                ],
            }
        },
        "scene_binding_diagnostics": {},
    }

    resolution = isaac_lab_backend_worker._resolve_isaac_placement(
        state,
        object_id="bowl_01",
        receptacle_id="bed_01",
        index=0,
        relation="on",
        source="unit",
    )

    assert resolution["support_status"] == "direct_support"
    assert resolution["position"] == pytest.approx([2.0, 3.0, 0.835])
    assert resolution["support_surface"]["surface_id"].endswith("/support_union")
    assert resolution["support_surface"]["top_z"] == pytest.approx(0.7)
    assert resolution["support_surface"]["source"] == "isaac_usd_descendant_support_surface_union"


def test_isaac_mess_seed_updates_locations_and_pose_overrides() -> None:
    state = {
        "scenario": {
            "objects": [
                {
                    "object_id": "mug_01",
                    "name": "mug",
                    "category": "dish",
                    "location_id": "sink_01",
                    "pickupable": True,
                }
            ],
            "receptacles": [
                {
                    "receptacle_id": "sink_01",
                    "name": "sink",
                    "category": "Sink",
                    "room_area": "kitchen",
                },
                {
                    "receptacle_id": "sofa_01",
                    "name": "sofa",
                    "category": "Sofa",
                    "room_area": "living",
                },
            ],
        },
        "private_manifest": {
            "targets": [{"object_id": "mug_01", "valid_receptacle_ids": ["sink_01"]}],
        },
        "generated_mess_manifest": {
            "schema": "roboclaws_generated_mess_manifest_v1",
            "targets": [
                {
                    "object_id": "mug_01",
                    "valid_receptacle_ids": ["sink_01"],
                    "target_receptacle_id": "sink_01",
                    "start_receptacle_id": "sofa_01",
                    "relation": "on",
                    "placement_index": 3,
                }
            ],
        },
        "locations": {"mug_01": "sink_01"},
        "containment": {},
        "object_pose_overrides": {},
        "mess_placement_diagnostics": [],
        "object_index": _unit_isaac_object_index(),
        "receptacle_index": {
            **_unit_isaac_receptacle_index(),
            "sofa_01": {
                "usd_prim_path": "/World/Receptacles/sofa_01",
                "category": "Sofa",
                "public_label": "sofa_01",
                "usd_world_bounds": {
                    "center": [1.0, 2.0, 0.4],
                    "min": [0.5, 1.5, 0.0],
                    "max": [1.5, 2.5, 0.8],
                    "size": [1.0, 1.0, 0.8],
                },
                "support_pose": {
                    "frame": "usd_world",
                    "x": 1.0,
                    "y": 2.0,
                    "z": 0.8,
                    "source": "usd_world_bounds_top_center",
                    "support_radius_m": 0.5,
                },
            },
        },
        "scene_binding_diagnostics": {},
    }

    isaac_lab_backend_worker._seed_generated_mess_placements(state)

    assert state["locations"]["mug_01"] == "sofa_01"
    assert state["scenario"]["objects"][0]["location_id"] == "sofa_01"
    assert state["object_pose_overrides"]["mug_01"]["position_source"] == (
        "isaac_support_placement_resolver"
    )
    assert state["object_pose_overrides"]["mug_01"]["source"] == "canonical_mess_manifest"
    assert state["mess_placement_diagnostics"][0]["diagnostic_source"] == (
        "canonical_mess_manifest"
    )
    assert state["mess_placement_diagnostics"][0]["placement_support_status"] == ("direct_support")


def test_isaac_usd_scene_index_extracts_room_outlines(monkeypatch: pytest.MonkeyPatch) -> None:
    class _FakePrim:
        def __init__(self, path: str, name: str) -> None:
            self._path = path
            self._name = name

        def GetPath(self) -> str:
            return self._path

        def GetName(self) -> str:
            return self._name

    fake_prim = _FakePrim("/val_1/Geometry/room_2_visual_0", "room_2_visual_0")

    class _FakeStage:
        def Traverse(self) -> list[_FakePrim]:
            return [fake_prim]

    class _FakeUsdStage:
        @staticmethod
        def Open(_path: str) -> _FakeStage:
            return _FakeStage()

    class _FakeUsdGeom:
        pass

    monkeypatch.setitem(
        sys.modules,
        "pxr",
        types.SimpleNamespace(Usd=types.SimpleNamespace(Stage=_FakeUsdStage), UsdGeom=_FakeUsdGeom),
    )
    monkeypatch.setattr(
        isaac_lab_backend_worker,
        "_usd_world_bounds",
        lambda _prim, *, usd_geom: {
            "center": [2.99, 4.983, 1.2],
            "size": [5.98, 9.966, 0.2],
        },
    )
    monkeypatch.setattr(
        isaac_lab_backend_worker,
        "_annotate_usd_index_geometry",
        lambda **_kwargs: None,
    )

    diagnostics = isaac_lab_backend_worker._inspect_usd_scene_index(Path("scene.usda"))

    assert diagnostics["room_outline_count"] == 1
    assert diagnostics["room_outlines"][0]["room_id"] == "room_2"
    assert diagnostics["room_outlines"][0]["center"] == pytest.approx([2.99, 4.983])
    assert diagnostics["room_outlines"][0]["half_extents"] == pytest.approx([2.99, 4.983])
    assert diagnostics["room_outlines"][0]["provenance"] == "isaac_usd_room_mesh_world_bounds"


def test_isaac_robot_view_focus_prefers_object_pose() -> None:
    state = {
        "scene_binding_diagnostics": {
            "selected_object_bindings": {
                "mug_01": {
                    "status": "bound",
                    "usd_handle": "mug_01",
                    "usd_prim_path": "/World/Objects/mug_01",
                }
            }
        },
        "object_index": _unit_isaac_object_index(),
        "receptacle_index": _unit_isaac_receptacle_index(),
    }
    state["semantic_pose_state"] = {
        "object_poses": isaac_lab_backend_worker._semantic_object_poses_from_state(
            {
                **state,
                "scenario": {
                    "objects": [{"object_id": "mug_01", "location_id": "sink_01"}],
                },
                "locations": {"mug_01": "sink_01"},
                "containment": {},
                "current_receptacle_id": "sink_01",
            }
        )
    }

    focus = isaac_lab_backend_worker._robot_view_focus(
        state,
        {"target_position": [2.5, 5.5, 1.2]},
        focus_object_id="mug_01",
        focus_receptacle_id="sink_01",
    )

    assert focus["source"] == "isaac_semantic_pose_object_pose"
    assert focus["focus_position"] == pytest.approx([4.0, 5.0, 0.4])
    assert focus["fpv_visibility"]["status"] == "segmentation_unavailable"
    assert focus["visibility"]["status"] == "segmentation_unavailable"


class _FakeRobotPosePrim:
    def __init__(self, path: str) -> None:
        self.path = path

    def IsValid(self) -> bool:
        return True


class _FakeRobotPoseStage:
    def GetPrimAtPath(self, path: str) -> _FakeRobotPosePrim:
        assert path in {"/World/robot_0", "/World/robot_0/head_camera"}
        return _FakeRobotPosePrim(path)


class _RecordingHeadCameraOp:
    def __init__(self, name: str, camera_transforms: list[tuple[str, object]]) -> None:
        self.name = name
        self.camera_transforms = camera_transforms

    def Set(self, value: object) -> None:
        self.camera_transforms.append((self.name, value))


class _FakeRobotPoseGf:
    @staticmethod
    def Vec3d(*values: float) -> tuple[float, float, float]:
        return (float(values[0]), float(values[1]), float(values[2]))

    @staticmethod
    def Vec3f(*values: float) -> tuple[float, float, float]:
        return (float(values[0]), float(values[1]), float(values[2]))

    @staticmethod
    def Quatf(real: float, imaginary: object) -> tuple[float, object]:
        return (float(real), imaginary)


def _robot_pose_xform_common_api_type(
    translations: list[object],
    rotations: list[object],
) -> type:
    class _FakeXformCommonAPI:
        def __init__(self, prim: _FakeRobotPosePrim) -> None:
            self.prim = prim

        def SetTranslate(self, value: object) -> None:
            translations.append(value)

        def SetRotate(self, value: object) -> None:
            rotations.append(value)

    return _FakeXformCommonAPI


def _head_camera_xformable_type(camera_transforms: list[tuple[str, object]]) -> type:
    class _FakeXformable:
        def __init__(self, prim: _FakeRobotPosePrim) -> None:
            self.prim = prim

        def ClearXformOpOrder(self) -> None:
            camera_transforms.append(("clear", self.prim.path))

        def AddTranslateOp(self) -> _RecordingHeadCameraOp:
            return _RecordingHeadCameraOp("translate", camera_transforms)

        def AddOrientOp(self) -> _RecordingHeadCameraOp:
            return _RecordingHeadCameraOp("orient", camera_transforms)

        def AddScaleOp(self) -> _RecordingHeadCameraOp:
            return _RecordingHeadCameraOp("scale", camera_transforms)

    return _FakeXformable


def _install_robot_pose_pxr(
    monkeypatch: pytest.MonkeyPatch,
    translations: list[object],
    rotations: list[object],
    camera_transforms: list[tuple[str, object]],
) -> None:
    fake_pxr = types.SimpleNamespace(
        Gf=_FakeRobotPoseGf,
        UsdGeom=types.SimpleNamespace(
            XformCommonAPI=_robot_pose_xform_common_api_type(translations, rotations),
            Xformable=_head_camera_xformable_type(camera_transforms),
        ),
    )
    monkeypatch.setitem(sys.modules, "pxr", fake_pxr)
    monkeypatch.setitem(sys.modules, "pxr.Gf", _FakeRobotPoseGf)
    monkeypatch.setitem(sys.modules, "pxr.UsdGeom", fake_pxr.UsdGeom)


def _shared_robot_pose_state() -> dict[str, object]:
    return {
        "robot_pose": {
            "x": 6.37057,
            "y": 8.8752,
            "z": 0.0,
            "theta": math.pi / 2.0,
            "head_pitch": 0.653613,
            "head_pitch_source": "target_framing_head_pitch",
            "pose_source": "roboclaws_shared_scene_frame_support_pose",
        }
    }


def test_isaac_head_camera_robot_pose_application_uses_shared_pose(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    translations: list[object] = []
    rotations: list[object] = []
    camera_transforms: list[tuple[str, object]] = []
    _install_robot_pose_pxr(monkeypatch, translations, rotations, camera_transforms)

    result = isaac_lab_backend_worker._position_robot_for_head_camera_view(
        stage_utils=SimpleNamespace(get_current_stage=lambda: _FakeRobotPoseStage()),
        scene_bounds=None,
        semantic_pose_state=_shared_robot_pose_state(),
    )

    assert translations == [pytest.approx((6.37057, 8.8752, 0.0))]
    assert rotations == [pytest.approx((0.0, 0.0, 90.0))]
    assert result["status"] == "applied"
    assert result["position_source"] == "semantic_pose_state.robot_pose"
    assert result["pose_source"] == "roboclaws_shared_scene_frame_support_pose"
    assert result["yaw_deg"] == pytest.approx(90.0)
    assert result["head_pitch"] == pytest.approx(0.653613)
    assert result["head_pitch_applied"] is True
    assert result["head_pitch_application"]["status"] == "applied"
    assert result["head_pitch_application"]["head_pitch_joint"] == "head_1"
    assert result["head_pitch_application"]["applied_position_m"] == pytest.approx(
        [0.092098, 0.0, 1.515292]
    )
    assert camera_transforms[0] == ("clear", "/World/robot_0/head_camera")
    assert camera_transforms[1][0] == "translate"
    assert camera_transforms[2][0] == "orient"
    assert camera_transforms[3] == ("scale", pytest.approx((1.0, 1.0, 1.0)))


def test_isaac_semantic_pose_stage_application_uses_exact_pose(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    translations: list[object] = []

    class _FakePrim:
        def IsValid(self) -> bool:
            return True

    class _FakeStage:
        def GetPrimAtPath(self, path: str) -> _FakePrim:
            assert path == "/World/Objects/mug_01"
            return _FakePrim()

    class _FakeXformCommonAPI:
        def __init__(self, prim: _FakePrim) -> None:
            self.prim = prim

        def SetTranslate(self, value: object) -> None:
            translations.append(value)

    class _FakeGf:
        @staticmethod
        def Vec3d(*values: float) -> tuple[float, float, float]:
            return (float(values[0]), float(values[1]), float(values[2]))

    fake_pxr = types.SimpleNamespace(
        Gf=_FakeGf,
        UsdGeom=types.SimpleNamespace(XformCommonAPI=_FakeXformCommonAPI),
    )
    monkeypatch.setitem(sys.modules, "pxr", fake_pxr)
    monkeypatch.setitem(sys.modules, "pxr.Gf", _FakeGf)
    monkeypatch.setitem(sys.modules, "pxr.UsdGeom", fake_pxr.UsdGeom)

    result = isaac_lab_backend_worker._apply_semantic_pose_state_to_stage(
        stage_utils=SimpleNamespace(get_current_stage=lambda: _FakeStage()),
        semantic_pose_state={
            "object_poses": {
                "mug_01": {
                    "usd_prim_path": "/World/Objects/mug_01",
                    "support_receptacle_id": "sink_01",
                    "position": [9.0, 8.0, 7.0],
                }
            },
            "receptacle_index": {
                "sink_01": {
                    "support_pose": {
                        "x": 2.5,
                        "y": 5.5,
                        "z": 1.2,
                    }
                }
            },
        },
    )

    assert result["status"] == "applied"
    assert translations == [(9.0, 8.0, 7.0)]
    assert result["applied_objects"][0]["target_position"] == [9.0, 8.0, 7.0]


class _FakeSemanticPoseParent:
    def __bool__(self) -> bool:
        return True


class _FakeSemanticPosePrim:
    def __init__(self) -> None:
        self.parent = _FakeSemanticPoseParent()

    def IsValid(self) -> bool:
        return True

    def GetParent(self) -> _FakeSemanticPoseParent:
        return self.parent


class _FakeSinglePrimStage:
    def __init__(self, expected_path: str) -> None:
        self.expected_path = expected_path
        self.prim = _FakeSemanticPosePrim()

    def GetPrimAtPath(self, path: str) -> _FakeSemanticPosePrim:
        assert path == self.expected_path
        return self.prim


class _OffsetParentWorldTransform:
    def __init__(self, offset: tuple[float, float, float]) -> None:
        self.offset = offset

    def GetInverse(self) -> "_OffsetParentWorldTransform":
        return self

    def Transform(self, value: object) -> tuple[float, float, float]:
        x, y, z = value
        offset_x, offset_y, offset_z = self.offset
        return (float(x) - offset_x, float(y) - offset_y, float(z) - offset_z)


class _FakeSemanticPoseGf:
    @staticmethod
    def Vec3d(*values: float) -> tuple[float, float, float]:
        return (float(values[0]), float(values[1]), float(values[2]))


class _FakeSemanticPoseOrientOp:
    def GetOpName(self) -> str:
        return "xformOp:orient"


class _RecordingTranslateOp:
    def __init__(self, translations: list[object]) -> None:
        self.translations = translations

    def GetOpName(self) -> str:
        return "xformOp:translate"

    def Set(self, value: object) -> bool:
        self.translations.append(value)
        return True


def _offset_parent_xformable_type(offset: tuple[float, float, float]) -> type:
    class _FakeXformable:
        def __init__(self, parent: _FakeSemanticPoseParent) -> None:
            self.parent = parent

        def ComputeLocalToWorldTransform(self, time_code: float) -> _OffsetParentWorldTransform:
            assert time_code == 0.0
            return _OffsetParentWorldTransform(offset)

    return _FakeXformable


def _existing_translate_xformable_type(
    translations: list[object],
    offset: tuple[float, float, float],
) -> type:
    class _FakeXformable:
        def __init__(self, prim: object) -> None:
            self.prim = prim

        def ComputeLocalToWorldTransform(self, time_code: float) -> _OffsetParentWorldTransform:
            assert time_code == 0.0
            return _OffsetParentWorldTransform(offset)

        def GetOrderedXformOps(self) -> list[object]:
            assert isinstance(self.prim, _FakeSemanticPosePrim)
            return [_RecordingTranslateOp(translations), _FakeSemanticPoseOrientOp()]

    return _FakeXformable


def _recording_xform_common_api_type(
    translations: list[object],
    *,
    failure_message: str | None = None,
) -> type:
    class _FakeXformCommonAPI:
        def __init__(self, prim: _FakeSemanticPosePrim) -> None:
            self.prim = prim

        def SetTranslate(self, value: object) -> None:
            if failure_message is not None:
                raise AssertionError(failure_message)
            translations.append(value)

    return _FakeXformCommonAPI


def _install_semantic_pose_stage_pxr(
    monkeypatch: pytest.MonkeyPatch,
    *,
    xform_common_api: type,
    xformable: type,
) -> None:
    fake_pxr = types.SimpleNamespace(
        Gf=_FakeSemanticPoseGf,
        UsdGeom=types.SimpleNamespace(
            XformCommonAPI=xform_common_api,
            Xformable=xformable,
        ),
    )
    monkeypatch.setitem(sys.modules, "pxr", fake_pxr)
    monkeypatch.setitem(sys.modules, "pxr.Gf", _FakeSemanticPoseGf)
    monkeypatch.setitem(sys.modules, "pxr.UsdGeom", fake_pxr.UsdGeom)


def _semantic_pose_stage_state(
    *,
    object_id: str,
    usd_prim_path: str,
    position: list[float],
    support_receptacle_id: str,
) -> dict[str, object]:
    return {
        "object_poses": {
            object_id: {
                "usd_prim_path": usd_prim_path,
                "support_receptacle_id": support_receptacle_id,
                "position": position,
            }
        },
        "receptacle_index": {},
    }


def test_isaac_semantic_pose_stage_application_converts_world_pose_to_parent_local(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    translations: list[object] = []
    _install_semantic_pose_stage_pxr(
        monkeypatch,
        xform_common_api=_recording_xform_common_api_type(translations),
        xformable=_offset_parent_xformable_type((10.0, 20.0, 0.5)),
    )

    result = isaac_lab_backend_worker._apply_semantic_pose_state_to_stage(
        stage_utils=SimpleNamespace(
            get_current_stage=lambda: _FakeSinglePrimStage("/World/Room/Objects/mug_01")
        ),
        semantic_pose_state=_semantic_pose_stage_state(
            object_id="mug_01",
            usd_prim_path="/World/Room/Objects/mug_01",
            position=[12.0, 23.0, 4.5],
            support_receptacle_id="sink_01",
        ),
    )

    assert result["status"] == "applied"
    assert translations == [pytest.approx((2.0, 3.0, 4.0))]
    assert result["applied_objects"][0]["target_position"] == [12.0, 23.0, 4.5]
    assert result["applied_objects"][0]["authored_translate"] == [2.0, 3.0, 4.0]
    assert result["applied_objects"][0]["authored_translate_frame"] == "parent_local"


def test_isaac_semantic_pose_stage_application_updates_existing_translate_op(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    translations: list[object] = []
    _install_semantic_pose_stage_pxr(
        monkeypatch,
        xform_common_api=_recording_xform_common_api_type(
            translations,
            failure_message="existing translate op should be authored directly",
        ),
        xformable=_existing_translate_xformable_type(translations, (3.0, 4.0, 5.0)),
    )

    result = isaac_lab_backend_worker._apply_semantic_pose_state_to_stage(
        stage_utils=SimpleNamespace(
            get_current_stage=lambda: _FakeSinglePrimStage("/World/Geometry/teddy")
        ),
        semantic_pose_state=_semantic_pose_stage_state(
            object_id="teddy",
            usd_prim_path="/World/Geometry/teddy",
            position=[8.0, 10.0, 12.0],
            support_receptacle_id="desk",
        ),
    )

    assert result["status"] == "applied"
    assert translations == [pytest.approx((5.0, 6.0, 7.0))]
    applied = result["applied_objects"][0]
    assert applied["authored_translate"] == [5.0, 6.0, 7.0]
    assert applied["translate_application_method"] == "existing_xformOp_translate"
    assert applied["authored_xform_op"] == "xformOp:translate"


def test_isaac_semantic_pose_stage_application_blocks_parent_transform_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    translations: list[object] = []

    class _FakeParent:
        def __bool__(self) -> bool:
            return True

    class _FakePrim:
        def IsValid(self) -> bool:
            return True

        def GetParent(self) -> _FakeParent:
            return _FakeParent()

    class _FakeStage:
        def GetPrimAtPath(self, path: str) -> _FakePrim:
            assert path == "/World/Room/Objects/mug_01"
            return _FakePrim()

    class _BrokenXformable:
        def __init__(self, parent: _FakeParent) -> None:
            self.parent = parent

        def ComputeLocalToWorldTransform(self, time_code: float) -> object:
            assert time_code == 0.0
            raise RuntimeError("missing parent xform")

    class _FakeXformCommonAPI:
        def __init__(self, prim: _FakePrim) -> None:
            self.prim = prim

        def SetTranslate(self, value: object) -> None:
            translations.append(value)

    class _FakeGf:
        @staticmethod
        def Vec3d(*values: float) -> tuple[float, float, float]:
            return (float(values[0]), float(values[1]), float(values[2]))

    fake_pxr = types.SimpleNamespace(
        Gf=_FakeGf,
        UsdGeom=types.SimpleNamespace(
            XformCommonAPI=_FakeXformCommonAPI,
            Xformable=_BrokenXformable,
        ),
    )
    monkeypatch.setitem(sys.modules, "pxr", fake_pxr)
    monkeypatch.setitem(sys.modules, "pxr.Gf", _FakeGf)
    monkeypatch.setitem(sys.modules, "pxr.UsdGeom", fake_pxr.UsdGeom)

    result = isaac_lab_backend_worker._apply_semantic_pose_state_to_stage(
        stage_utils=SimpleNamespace(get_current_stage=lambda: _FakeStage()),
        semantic_pose_state={
            "object_poses": {
                "mug_01": {
                    "usd_prim_path": "/World/Room/Objects/mug_01",
                    "support_receptacle_id": "sink_01",
                    "position": [12.0, 23.0, 4.5],
                }
            },
            "receptacle_index": {},
        },
    )

    assert result["status"] == "blocked"
    assert result["applied_object_count"] == 0
    assert result["failed_objects"][0]["reason"] == "parent_local_transform_failed"
    assert translations == []


def test_isaac_semantic_pose_stage_application_does_not_mark_partial_as_rendered(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    translations: list[object] = []

    class _FakePrim:
        def __init__(self, valid: bool) -> None:
            self.valid = valid

        def IsValid(self) -> bool:
            return self.valid

    class _FakeStage:
        def GetPrimAtPath(self, path: str) -> _FakePrim:
            return _FakePrim(path.endswith("/mug_01"))

    class _FakeXformCommonAPI:
        def __init__(self, prim: _FakePrim) -> None:
            self.prim = prim

        def SetTranslate(self, value: object) -> None:
            translations.append(value)

    class _FakeGf:
        @staticmethod
        def Vec3d(*values: float) -> tuple[float, float, float]:
            return (float(values[0]), float(values[1]), float(values[2]))

    fake_pxr = types.SimpleNamespace(
        Gf=_FakeGf,
        UsdGeom=types.SimpleNamespace(XformCommonAPI=_FakeXformCommonAPI),
    )
    monkeypatch.setitem(sys.modules, "pxr", fake_pxr)
    monkeypatch.setitem(sys.modules, "pxr.Gf", _FakeGf)
    monkeypatch.setitem(sys.modules, "pxr.UsdGeom", fake_pxr.UsdGeom)

    result = isaac_lab_backend_worker._apply_semantic_pose_state_to_stage(
        stage_utils=SimpleNamespace(get_current_stage=lambda: _FakeStage()),
        semantic_pose_state={
            "object_poses": {
                "mug_01": {
                    "usd_prim_path": "/World/Objects/mug_01",
                    "support_receptacle_id": "sink_01",
                    "position": [1.0, 2.0, 3.0],
                },
                "spoon_01": {
                    "usd_prim_path": "/World/Objects/spoon_01",
                    "support_receptacle_id": "sink_01",
                    "position": [4.0, 5.0, 6.0],
                },
            },
            "receptacle_index": {},
        },
    )

    assert result["status"] == "partial"
    assert result["applied_object_count"] == 1
    assert result["failed_object_count"] == 1
    assert result["rendered_to_usd"] is False
    assert translations == [(1.0, 2.0, 3.0)]


def test_isaac_stage_light_paths_detects_existing_lights_without_pxr() -> None:
    class _FakePrim:
        def __init__(self, path: str, is_light: bool, type_name: str = "") -> None:
            self._path = path
            self._is_light = is_light
            self._type_name = type_name

        def IsValid(self) -> bool:
            return True

        def GetPath(self) -> str:
            return self._path

        def IsA(self, _api: object) -> bool:
            return self._is_light

        def GetTypeName(self) -> str:
            return self._type_name

    class _FakeStage:
        def Traverse(self) -> list[_FakePrim]:
            return [
                _FakePrim("/val_1/scene_skybox_light", True),
                _FakePrim("/val_1/scene_dir_light", False, "DistantLight"),
                _FakePrim("/val_1/Geometry/table", False),
            ]

    paths = isaac_lab_backend_worker._stage_light_paths(
        _FakeStage(),
        light_api=object(),
    )

    assert paths == [
        "/val_1/scene_skybox_light",
        "/val_1/scene_dir_light",
    ]


def test_isaac_lab_fake_worker_can_align_to_nav2_map_bundle(tmp_path: Path) -> None:
    map_bundle = Path("assets/maps/molmospaces/procthor-10k-val/0")
    backend = IsaacLabSubprocessBackend(
        run_dir=tmp_path,
        python_executable=Path(sys.executable),
        runtime_mode="fake",
        include_robot=True,
        generated_mess_count=1,
        map_bundle_dir=map_bundle,
    )

    object_id = backend.scenario.objects[0].object_id
    target_id = backend.scenario.private_manifest.targets[0].valid_receptacle_ids[0]

    assert backend.generated_mess_count == 1
    assert target_id in {item.receptacle_id for item in backend.scenario.receptacles}
    assert backend.navigate_to_object(object_id)["ok"] is True
    assert backend.pick(object_id)["ok"] is True
    assert backend.navigate_to_receptacle(target_id)["ok"] is True
    assert backend.place(target_id)["ok"] is True
    assert backend.done("map aligned fake protocol")["cleanup_status"] == "success"


def test_isaac_usd_index_path_heuristics_skip_container_prims() -> None:
    assert isaac_lab_backend_worker._is_object_prim_path("/World/Objects") is False
    assert isaac_lab_backend_worker._is_object_prim_path("/World/Objects/mug_01") is True
    assert isaac_lab_backend_worker._is_receptacle_prim_path("/World/Receptacles") is False
    assert isaac_lab_backend_worker._is_receptacle_prim_path("/World/Receptacles/sink_01") is True


def test_isaac_molmospaces_scene_metadata_indexes_real_geometry_prims(
    tmp_path: Path,
) -> None:
    scene_dir = tmp_path / "val_0"
    scene_dir.mkdir()
    scene_usd = scene_dir / "scene.usda"
    scene_usd.write_text("#usda 1.0\n", encoding="utf-8")
    (scene_dir / "scene_metadata.json").write_text(
        json.dumps(
            {
                "objects": {
                    "mug_8caf1bb3f88e9a00e02dfe9e6518aeb0_1_0_7": {
                        "hash_name": "mug_8caf1bb3f88e9a00e02dfe9e6518aeb0_1_0_7",
                        "asset_id": "Mug_1",
                        "object_id": "Mug|surface|7|71",
                        "category": "Mug",
                        "is_static": False,
                        "parent": "desk_767b7ce268898119aaeb97804ba52bdd_1_0_7",
                        "children": [],
                    },
                    "sink_07e796f32d0d3efce9acf4be00f3bc53_1_0_5": {
                        "hash_name": "sink_07e796f32d0d3efce9acf4be00f3bc53_1_0_5",
                        "asset_id": "Sink_1",
                        "object_id": "Sink|5|1|0",
                        "category": "Sink",
                        "is_static": True,
                        "children": [],
                    },
                }
            }
        ),
        encoding="utf-8",
    )
    object_index: dict[str, dict[str, object]] = {}
    receptacle_index: dict[str, dict[str, object]] = {}

    isaac_lab_backend_worker._merge_molmospaces_metadata_index(
        usd_path=scene_usd,
        prim_paths_by_name={
            "mug_8caf1bb3f88e9a00e02dfe9e6518aeb0_1_0_7": [
                "/val_0/Geometry/mug_8caf1bb3f88e9a00e02dfe9e6518aeb0_1_0_7"
            ],
            "sink_07e796f32d0d3efce9acf4be00f3bc53_1_0_5": [
                "/val_0/Geometry/sink_07e796f32d0d3efce9acf4be00f3bc53_1_0_5"
            ],
        },
        object_index=object_index,
        receptacle_index=receptacle_index,
    )

    mug = object_index["mug_8caf1bb3f88e9a00e02dfe9e6518aeb0_1_0_7"]
    sink = receptacle_index["sink_07e796f32d0d3efce9acf4be00f3bc53_1_0_5"]
    assert mug["usd_prim_path"] == "/val_0/Geometry/mug_8caf1bb3f88e9a00e02dfe9e6518aeb0_1_0_7"
    assert mug["category"] == "Mug"
    assert mug["index_source"] == "usd_stage_traversal"
    assert mug["metadata_source"] == "molmospaces_scene_metadata"
    assert sink["usd_prim_path"] == "/val_0/Geometry/sink_07e796f32d0d3efce9acf4be00f3bc53_1_0_5"
    assert sink["category"] == "Sink"
    assert sink["kind"] == "receptacle"


@pytest.mark.parametrize("source_text", ["{bad json\n", "[]\n"])
def test_isaac_molmospaces_scene_metadata_ignores_bad_optional_source(
    tmp_path: Path,
    source_text: str,
) -> None:
    scene_dir = tmp_path / "val_0"
    scene_dir.mkdir()
    scene_usd = scene_dir / "scene.usda"
    scene_usd.write_text("#usda 1.0\n", encoding="utf-8")
    (scene_dir / "scene_metadata.json").write_text(source_text, encoding="utf-8")

    assert isaac_lab_backend_worker._load_molmospaces_scene_metadata(scene_usd) == {}


def test_isaac_molmospaces_scene_metadata_allows_missing_optional_source(
    tmp_path: Path,
) -> None:
    scene_usd = tmp_path / "scene.usda"
    scene_usd.write_text("#usda 1.0\n", encoding="utf-8")

    assert isaac_lab_backend_worker._load_molmospaces_scene_metadata(scene_usd) == {}


def test_isaac_molmospaces_metadata_prefers_top_level_geometry_prim() -> None:
    assert (
        isaac_lab_backend_worker._molmospaces_metadata_prim_path(
            "mug_01",
            {
                "mug_01": [
                    "/val_0/A/mug_01",
                    "/val_0/Geometry/mug_01",
                    "/val_0/Geometry/mug_01/mesh",
                ]
            },
        )
        == "/val_0/Geometry/mug_01"
    )


def test_isaac_scene_binding_can_match_synthetic_handle_to_real_usd_metadata() -> None:
    object_index = {
        "mug_3ebc45568ed53a18c8797978b3744a99_1_0_6": {
            "usd_prim_path": "/val_0/Geometry/mug_3ebc45568ed53a18c8797978b3744a99_1_0_6",
            "category": "Mug",
            "public_label": "Mug Mug|surface|6|56 RoboTHOR_mug_ai2_2_v",
            "index_source": "usd_stage_traversal",
            "metadata_handle": "mug_3ebc45568ed53a18c8797978b3744a99_1_0_6",
        },
        "mug_8caf1bb3f88e9a00e02dfe9e6518aeb0_1_0_7": {
            "usd_prim_path": "/val_0/Geometry/mug_8caf1bb3f88e9a00e02dfe9e6518aeb0_1_0_7",
            "category": "Mug",
            "public_label": "Mug Mug|surface|7|71 Mug_1",
            "index_source": "usd_stage_traversal",
            "metadata_handle": "mug_8caf1bb3f88e9a00e02dfe9e6518aeb0_1_0_7",
        },
    }

    binding = isaac_lab_backend_worker._bind_public_scene_item(
        public_id="mug_01",
        public_label="ceramic mug",
        category="dish",
        index=object_index,
        kind="object",
    )

    assert binding["status"] == "bound"
    assert binding["usd_handle"] == "mug_3ebc45568ed53a18c8797978b3744a99_1_0_6"
    assert binding["usd_prim_path"] == (
        "/val_0/Geometry/mug_3ebc45568ed53a18c8797978b3744a99_1_0_6"
    )
    assert binding["match_strategy"] == "public_id_prefix_first"
    assert binding["index_source"] == "usd_stage_traversal"

    state = {
        "scene_binding_diagnostics": {"selected_object_bindings": {"mug_01": binding}},
        "object_index": object_index,
    }
    assert isaac_lab_backend_worker._object_usd_prim_path(state, "mug_01") == (
        "/val_0/Geometry/mug_3ebc45568ed53a18c8797978b3744a99_1_0_6"
    )


def test_isaac_scene_binding_does_not_bind_generic_dish_to_unrelated_category() -> None:
    object_index = {
        "sponge_41cc9aa65073b4cd1fc4d9871335148d_1_0_3": {
            "usd_prim_path": "/val_1/Geometry/sponge_41cc9aa65073b4cd1fc4d9871335148d_1_0_3",
            "category": "DishSponge",
            "public_label": "DishSponge DishSponge|surface|3|17 Dish_Sponge_1",
            "index_source": "usd_stage_traversal",
            "metadata_handle": "sponge_41cc9aa65073b4cd1fc4d9871335148d_1_0_3",
        }
    }

    binding = isaac_lab_backend_worker._bind_public_scene_item(
        public_id="mug_01",
        public_label="ceramic mug",
        category="dish",
        index=object_index,
        kind="object",
    )

    assert binding["status"] == "unresolved"
    assert binding["match_strategy"] == "none"
    assert binding["usd_prim_path"] == ""


def test_isaac_scene_binding_still_allows_specific_unique_category() -> None:
    object_index = {
        "mug_3ebc45568ed53a18c8797978b3744a99_1_0_6": {
            "usd_prim_path": "/val_0/Geometry/mug_3ebc45568ed53a18c8797978b3744a99_1_0_6",
            "category": "Mug",
            "public_label": "Mug Mug|surface|6|56 RoboTHOR_mug_ai2_2_v",
            "index_source": "usd_stage_traversal",
            "metadata_handle": "mug_3ebc45568ed53a18c8797978b3744a99_1_0_6",
        }
    }

    binding = isaac_lab_backend_worker._bind_public_scene_item(
        public_id="cleanup_object_01",
        public_label="unlabeled cleanup object",
        category="Mug",
        index=object_index,
        kind="object",
    )

    assert binding["status"] == "bound"
    assert binding["usd_handle"] == "mug_3ebc45568ed53a18c8797978b3744a99_1_0_6"
    assert binding["match_strategy"] in {"semantic_category_token_unique", "unique_category"}


def test_isaac_scene_index_can_generate_scene_specific_cleanup_scenario() -> None:
    object_index = {
        "baseballbat_37665ef33aee57e330674e8ff865507e_1_0_2": {
            "asset_id": "BaseballBat_2",
            "category": "BaseballBat",
            "index_source": "usd_stage_traversal",
            "is_static": False,
            "kind": "object",
            "metadata_handle": "baseballbat_37665ef33aee57e330674e8ff865507e_1_0_2",
            "metadata_object_id": "BaseballBat|surface|2|10",
            "parent": "bed_258d27d5fe50e324961c7a8698ace951_1_0_2",
            "public_label": "BaseballBat BaseballBat|surface|2|10 BaseballBat_2",
            "usd_prim_path": "/val_1/Geometry/baseballbat_37665ef33aee57e330674e8ff865507e_1_0_2",
        },
        "bowl_847a24bfa9d8b1a1f26661ebbb850f56_1_0_2": {
            "asset_id": "Bowl_12",
            "category": "Bowl",
            "index_source": "usd_stage_traversal",
            "is_static": False,
            "kind": "object",
            "metadata_handle": "bowl_847a24bfa9d8b1a1f26661ebbb850f56_1_0_2",
            "metadata_object_id": "Bowl|surface|2|4",
            "parent": "diningtable_f113cf7f8367e89f709b53cbee1a1c05_1_0_2",
            "public_label": "Bowl Bowl|surface|2|4 Bowl_12",
            "usd_prim_path": "/val_1/Geometry/bowl_847a24bfa9d8b1a1f26661ebbb850f56_1_0_2",
        },
        "sponge_41cc9aa65073b4cd1fc4d9871335148d_1_0_3": {
            "asset_id": "Dish_Sponge_1",
            "category": "DishSponge",
            "index_source": "usd_stage_traversal",
            "is_static": False,
            "kind": "object",
            "metadata_handle": "sponge_41cc9aa65073b4cd1fc4d9871335148d_1_0_3",
            "metadata_object_id": "DishSponge|surface|3|17",
            "parent": "crapper_cd6fa77f725b7ec4a4ced5913731ae93_1_0_3",
            "public_label": "DishSponge DishSponge|surface|3|17 Dish_Sponge_1",
            "usd_prim_path": "/val_1/Geometry/sponge_41cc9aa65073b4cd1fc4d9871335148d_1_0_3",
        },
    }
    receptacle_index = {
        "ashcan_a20a3404d9e4ddd7e8d84c88e9975333_1_0_3": {
            "asset_id": "bin_16",
            "category": "GarbageCan",
            "index_source": "usd_stage_traversal",
            "kind": "receptacle",
            "metadata_handle": "ashcan_a20a3404d9e4ddd7e8d84c88e9975333_1_0_3",
            "public_label": "GarbageCan GarbageCan|3|2 bin_16",
            "usd_prim_path": "/val_1/Geometry/ashcan_a20a3404d9e4ddd7e8d84c88e9975333_1_0_3",
        },
        "diningtable_f113cf7f8367e89f709b53cbee1a1c05_1_0_2": {
            "asset_id": "Dining_Table_203_1",
            "category": "DiningTable",
            "index_source": "usd_stage_traversal",
            "kind": "receptacle",
            "metadata_handle": "diningtable_f113cf7f8367e89f709b53cbee1a1c05_1_0_2",
            "public_label": "DiningTable DiningTable|2|1|0 Dining_Table_203_1",
            "usd_prim_path": "/val_1/Geometry/diningtable_f113cf7f8367e89f709b53cbee1a1c05_1_0_2",
        },
        "sink_07e796f32d0d3efce9acf4be00f3bc53_1_0_3": {
            "asset_id": "Sink_1",
            "category": "Sink",
            "index_source": "usd_stage_traversal",
            "kind": "receptacle",
            "metadata_handle": "sink_07e796f32d0d3efce9acf4be00f3bc53_1_0_3",
            "public_label": "Sink Sink|3|1|0 Sink_1",
            "usd_prim_path": "/val_1/Geometry/sink_07e796f32d0d3efce9acf4be00f3bc53_1_0_3",
        },
    }

    scenario = isaac_lab_backend_worker._scenario_from_scene_index(
        scene_source="procthor-10k-val",
        scene_index=1,
        seed=7,
        generated_mess_count=1,
        object_index=object_index,
        receptacle_index=receptacle_index,
    )

    assert scenario is not None
    assert scenario.scenario_id == "isaac-scene-index-procthor-10k-val-1-7-1"
    assert [item.receptacle_id for item in scenario.receptacles] == [
        "diningtable_f113cf7f8367e89f709b53cbee1a1c05_1_0_2",
        "sink_07e796f32d0d3efce9acf4be00f3bc53_1_0_3",
    ]
    assert scenario.objects[0].object_id == "bowl_847a24bfa9d8b1a1f26661ebbb850f56_1_0_2"
    assert scenario.objects[0].location_id == "diningtable_f113cf7f8367e89f709b53cbee1a1c05_1_0_2"
    target = scenario.private_manifest.targets[0]
    assert target.object_id == "bowl_847a24bfa9d8b1a1f26661ebbb850f56_1_0_2"
    assert target.valid_receptacle_ids == ("sink_07e796f32d0d3efce9acf4be00f3bc53_1_0_3",)
    bindings = isaac_lab_backend_worker._scene_binding_diagnostics(
        runtime_mode="real",
        scenario=scenario,
        object_index=object_index,
        receptacle_index=receptacle_index,
        real_smoke={},
    )
    assert bindings["status"] == "selected_bound"
    assert bindings["selected_object_bound_count"] == 1
    assert bindings["selected_target_receptacle_bound_count"] == 1


def test_isaac_scene_index_uses_shared_generated_mess_selection() -> None:
    object_index = {
        "alarmclock_a": {
            "asset_id": "Alarm_Clock_1",
            "category": "AlarmClock",
            "kind": "object",
            "parent": "bed_01",
            "public_label": "AlarmClock AlarmClock|surface|1|1 Alarm_Clock_1",
        },
        "alarmclock_b": {
            "asset_id": "Alarm_Clock_2",
            "category": "AlarmClock",
            "kind": "object",
            "parent": "bed_02",
            "public_label": "AlarmClock AlarmClock|surface|1|2 Alarm_Clock_2",
        },
        "apple_a": {
            "asset_id": "Apple_1",
            "category": "Apple",
            "kind": "object",
            "parent": "counter_01",
            "public_label": "Apple Apple|surface|1|3 Apple_1",
        },
        "book_a": {
            "asset_id": "Book_1",
            "category": "Book",
            "kind": "object",
            "parent": "desk_01",
            "public_label": "Book Book|surface|1|4 Book_1",
        },
        "plate_a": {
            "asset_id": "Plate_1",
            "category": "Plate",
            "kind": "object",
            "parent": "table_01",
            "public_label": "Plate Plate|surface|1|5 Plate_1",
        },
        "pillow_a": {
            "asset_id": "Pillow_1",
            "category": "Pillow",
            "kind": "object",
            "parent": "sofa_01",
            "public_label": "Pillow Pillow|surface|1|6 Pillow_1",
        },
        "remote_a": {
            "asset_id": "Remote_1",
            "category": "RemoteControl",
            "kind": "object",
            "parent": "desk_02",
            "public_label": "RemoteControl RemoteControl|surface|1|7 Remote_1",
        },
    }
    receptacle_index = {
        "bed_01": {"category": "Bed", "kind": "receptacle", "public_label": "Bed Bed|1|1"},
        "bed_02": {"category": "Bed", "kind": "receptacle", "public_label": "Bed Bed|1|2"},
        "counter_01": {
            "category": "CounterTop",
            "kind": "receptacle",
            "public_label": "CounterTop CounterTop|1|1",
        },
        "desk_01": {"category": "Desk", "kind": "receptacle", "public_label": "Desk Desk|1|1"},
        "desk_02": {"category": "Desk", "kind": "receptacle", "public_label": "Desk Desk|1|2"},
        "fridge_01": {
            "category": "Fridge",
            "kind": "receptacle",
            "public_label": "Fridge Fridge|1|1",
        },
        "shelf_01": {
            "category": "ShelvingUnit",
            "kind": "receptacle",
            "public_label": "ShelvingUnit ShelvingUnit|1|1",
        },
        "sink_01": {"category": "Sink", "kind": "receptacle", "public_label": "Sink Sink|1|1"},
        "sofa_01": {"category": "Sofa", "kind": "receptacle", "public_label": "Sofa Sofa|1|1"},
        "stand_01": {
            "category": "TVStand",
            "kind": "receptacle",
            "public_label": "TVStand TVStand|1|1",
        },
    }

    scenario = isaac_lab_backend_worker._scenario_from_scene_index(
        scene_source="procthor-10k-val",
        scene_index=0,
        seed=7,
        generated_mess_count=5,
        object_index=object_index,
        receptacle_index=receptacle_index,
    )

    assert scenario is not None
    assert [item.category for item in scenario.objects] == [
        "Plate",
        "Book",
        "Potato",
        "RemoteControl",
        "Pillow",
    ]
    assert [target.valid_receptacle_ids[0] for target in scenario.private_manifest.targets] == [
        "sink_01",
        "shelf_01",
        "fridge_01",
        "stand_01",
        "bed_01",
    ]
    assert scenario.private_manifest.success_threshold == 4


def test_isaac_scene_index_can_pin_generated_mess_object_ids() -> None:
    object_index = {
        "apple_01": {
            "asset_id": "Apple_1",
            "category": "Apple",
            "kind": "object",
            "parent": "counter_01",
            "public_label": "Apple Apple|surface|1|3 Apple_1",
        },
        "bread_01": {
            "asset_id": "Bread_1",
            "category": "Bread",
            "kind": "object",
            "parent": "counter_01",
            "public_label": "Bread Bread|surface|1|4 Bread_1",
        },
    }
    receptacle_index = {
        "counter_01": {
            "category": "CounterTop",
            "kind": "receptacle",
            "public_label": "CounterTop CounterTop|1|1",
        },
        "fridge_01": {
            "category": "Fridge",
            "kind": "receptacle",
            "public_label": "Fridge Fridge|1|1",
        },
    }

    scenario = isaac_lab_backend_worker._scenario_from_scene_index(
        scene_source="procthor-10k-val",
        scene_index=0,
        seed=6,
        generated_mess_count=1,
        generated_mess_object_ids=("apple_01",),
        object_index=object_index,
        receptacle_index=receptacle_index,
    )

    assert scenario is not None
    assert [item.object_id for item in scenario.objects] == ["apple_01"]
    assert [target.object_id for target in scenario.private_manifest.targets] == ["apple_01"]
    assert scenario.private_manifest.targets[0].valid_receptacle_ids == ("fridge_01",)


def test_isaac_scene_index_consumes_canonical_generated_mess_manifest() -> None:
    object_index = {
        "apple_01": {
            "asset_id": "Apple_1",
            "category": "Apple",
            "kind": "object",
            "parent": "counter_01",
            "public_label": "Apple Apple|surface|1|3 Apple_1",
        },
        "plate_01": {
            "asset_id": "Plate_1",
            "category": "Plate",
            "kind": "object",
            "parent": "table_01",
            "public_label": "Plate Plate|surface|1|4 Plate_1",
        },
    }
    receptacle_index = {
        "counter_01": {
            "category": "CounterTop",
            "kind": "receptacle",
            "public_label": "CounterTop CounterTop|1|1",
        },
        "fridge_01": {
            "category": "Fridge",
            "kind": "receptacle",
            "public_label": "Fridge Fridge|1|1",
        },
        "sink_01": {"category": "Sink", "kind": "receptacle", "public_label": "Sink Sink|1|1"},
        "sofa_01": {"category": "Sofa", "kind": "receptacle", "public_label": "Sofa Sofa|1|1"},
        "table_01": {
            "category": "DiningTable",
            "kind": "receptacle",
            "public_label": "DiningTable DiningTable|1|1",
        },
    }
    manifest = {
        "schema": "roboclaws_generated_mess_manifest_v1",
        "targets": [
            {
                "object_id": "apple_01",
                "valid_receptacle_ids": ["fridge_01"],
                "target_receptacle_id": "fridge_01",
                "start_receptacle_id": "sofa_01",
                "relation": "on",
                "placement_index": 0,
            },
            {
                "object_id": "plate_01",
                "valid_receptacle_ids": ["sink_01"],
                "target_receptacle_id": "sink_01",
                "start_receptacle_id": "sofa_01",
                "relation": "on",
                "placement_index": 1,
            },
        ],
    }

    scenario = isaac_lab_backend_worker._scenario_from_scene_index(
        scene_source="procthor-10k-val",
        scene_index=0,
        seed=6,
        generated_mess_count=2,
        generated_mess_manifest=manifest,
        object_index=object_index,
        receptacle_index=receptacle_index,
    )

    assert scenario is not None
    assert [item.object_id for item in scenario.objects] == ["apple_01", "plate_01"]
    assert [item.location_id for item in scenario.objects] == ["sofa_01", "sofa_01"]
    assert [target.valid_receptacle_ids[0] for target in scenario.private_manifest.targets] == [
        "fridge_01",
        "sink_01",
    ]


def test_isaac_scene_index_preserves_teddybear_category_for_placement() -> None:
    object_index = {
        "teddy_01": {
            "asset_id": "Teddy_Bear_1",
            "category": "TeddyBear",
            "kind": "object",
            "parent": "desk_01",
            "public_label": "TeddyBear TeddyBear|surface|1|8 Teddy_Bear_1",
        },
        "pillow_01": {
            "asset_id": "Pillow_1",
            "category": "Pillow",
            "kind": "object",
            "parent": "desk_01",
            "public_label": "Pillow Pillow|surface|1|9 Pillow_1",
        },
    }
    receptacle_index = {
        "bed_01": {"category": "Bed", "kind": "receptacle", "public_label": "Bed Bed|1|1"},
        "desk_01": {"category": "Desk", "kind": "receptacle", "public_label": "Desk Desk|1|1"},
    }

    scenario = isaac_lab_backend_worker._scenario_from_scene_index(
        scene_source="procthor-10k-val",
        scene_index=0,
        seed=1,
        generated_mess_count=2,
        generated_mess_object_ids=("teddy_01", "pillow_01"),
        object_index=object_index,
        receptacle_index=receptacle_index,
    )

    assert scenario is not None
    categories = {item.object_id: item.category for item in scenario.objects}
    assert categories == {"teddy_01": "TeddyBear", "pillow_01": "Pillow"}
    assert [target.valid_receptacle_ids[0] for target in scenario.private_manifest.targets] == [
        "bed_01",
        "bed_01",
    ]


def test_isaac_object_bottom_offset_uses_usd_root_position_before_bbox_center() -> None:
    state = {
        "object_index": {
            "teddy_01": {
                "usd_world_bounds": {
                    "min": [1.0, 2.0, 0.84],
                    "center": [1.2, 2.2, 1.10],
                    "max": [1.4, 2.4, 1.36],
                },
                "usd_world_root_position": [1.2, 2.2, 0.90],
            }
        },
        "objects": {
            "teddy_01": {
                "object_id": "teddy_01",
                "category": "TeddyBear",
            }
        },
    }

    assert isaac_lab_backend_worker._isaac_object_bottom_offset(state, "teddy_01") == (
        pytest.approx(0.06)
    )


def test_isaac_scene_index_rejects_missing_explicit_generated_mess_id() -> None:
    with pytest.raises(ValueError, match="explicit generated mess object id is unavailable"):
        isaac_lab_backend_worker._scenario_from_scene_index(
            scene_source="procthor-10k-val",
            scene_index=0,
            seed=6,
            generated_mess_count=1,
            generated_mess_object_ids=("missing_object",),
            object_index={},
            receptacle_index={
                "fridge_01": {
                    "category": "Fridge",
                    "kind": "receptacle",
                    "public_label": "Fridge Fridge|1|1",
                },
            },
        )


def test_isaac_worker_infers_scene_index_from_local_val_path() -> None:
    args = isaac_lab_backend_worker.parse_args(
        [
            "--state-path",
            "state.json",
            "init",
            "--run-dir",
            "run",
            "--scene-index",
            "0",
            "--scene-usd-path",
            "output/isaaclab/molmospaces-usd/scenes/procthor-10k-val/val_12/scene.usda",
        ]
    )

    assert isaac_lab_backend_worker._effective_scene_index(args) == 12


def test_isaac_worker_infers_scene_index_from_prepared_val_path() -> None:
    args = isaac_lab_backend_worker.parse_args(
        [
            "--state-path",
            "state.json",
            "init",
            "--run-dir",
            "run",
            "--scene-index",
            "0",
            "--scene-usd-path",
            (
                "output/isaaclab/flattened-semantic-usd/"
                "0529_val1_flattened_semantic_scene/scene_semantic.usda"
            ),
        ]
    )

    assert isaac_lab_backend_worker._effective_scene_index(args) == 1


def test_isaac_lab_real_init_uses_phase_a_smoke_evidence(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    run_dir = tmp_path / "run"
    state_path = tmp_path / "state.json"
    image_path = run_dir / "isaac_runtime_smoke.png"
    robot_view_images = _write_robot_view_images(run_dir)
    scene_usd = run_dir / "roboclaws_phase_a_smoke_scene.usda"
    _write_nonblank_image(image_path)
    scene_usd.parent.mkdir(parents=True, exist_ok=True)
    scene_usd.write_text("#usda 1.0\n", encoding="utf-8")

    def fake_real_runtime_smoke(
        args: object,
        scenario: object,
    ) -> dict[str, object]:
        del scenario
        assert getattr(args, "runtime_mode") == "real"
        assert getattr(args, "scene_usd_path") == scene_usd
        return {
            "image_path": str(image_path),
            "scene_usd": str(scene_usd),
            "loaded_asset_kind": "local_scene_usd",
            "requested_scene_source": "procthor-10k-val",
            "requested_scene_index": 0,
            "requested_molmospaces_scene_usd": "molmospaces://procthor-10k-val/scene-0.usd",
            "isaac_lab_version": "unit-isaaclab",
            "isaac_sim_version": "unit-isaacsim",
            "renderer_mode": "isaac_lab_headless_rtx",
            "capture_method": "isaac_lab_camera_rgb",
            "robot_view_capture_method": "isaac_lab_camera_rgb_static_robot_views",
            "robot_view_images": robot_view_images,
            "camera_resolution": [540, 360],
            "stage_prim_count": 6,
            "render_steps": 3,
            "scene_index_diagnostics": {
                "schema": "isaac_usd_scene_index_v1",
                "status": "indexed",
                "source": str(scene_usd),
                "stage_prim_count": 6,
                "object_candidate_count": 1,
                "receptacle_candidate_count": 1,
                "blockers": [],
            },
            "object_index": _unit_isaac_object_index(),
            "receptacle_index": _unit_isaac_receptacle_index(),
            "segmentation": {
                "schema": "isaac_segmentation_diagnostics_v1",
                "source": "isaac_lab_camera",
                "capture_method": "isaac_lab_camera_segmentation",
                "requested_data_types": [
                    "semantic_segmentation",
                    "instance_segmentation_fast",
                    "instance_id_segmentation_fast",
                ],
                "output_data_types": ["instance_id_segmentation_fast"],
                "tensor_output_available": True,
                "candidate_bbox_count": 1,
                "candidate_bboxes": [
                    {
                        "view": "fpv",
                        "data_type": "instance_id_segmentation_fast",
                        "label_id": 3,
                        "label": "/World/Objects/mug_01",
                        "usd_prim_path": "/World/Objects/mug_01",
                        "bbox_xyxy": [8, 8, 32, 36],
                        "pixel_count": 144,
                        "image_size": [540, 360],
                    }
                ],
                "no_simulator_label_fallback": True,
            },
        }

    monkeypatch.setattr(
        isaac_lab_backend_worker,
        "real_runtime_smoke",
        fake_real_runtime_smoke,
    )

    args = isaac_lab_backend_worker.parse_args(
        [
            "--state-path",
            str(state_path),
            "init",
            "--run-dir",
            str(run_dir),
            "--runtime-mode",
            "real",
            "--generated-mess-count",
            "1",
            "--scene-usd-path",
            str(scene_usd),
        ]
    )
    result = isaac_lab_backend_worker.init_state(args)

    assert result["ok"] is True
    assert result["runtime"]["runtime_mode"] == "real"
    assert result["runtime"]["rendering"]["status"] == "real_rendering_proven"
    assert result["runtime"]["rendering"]["real_rendering_proven"] is True
    assert result["runtime"]["rendering"]["placeholder_visuals"] is False
    assert result["runtime"]["visual_artifact_provenance"] == "isaac_lab_camera_rgb"
    assert result["scene_usd"] == str(scene_usd)
    assert result["scene_load"]["status"] == "loaded"
    assert result["scene_load"]["usd_stage_loaded"] is True
    assert result["scene_load"]["loaded_asset_kind"] == "local_scene_usd"
    assert result["artifacts"]["runtime_smoke_image"] == str(image_path)
    assert result["artifacts"]["robot_view_images"] == robot_view_images
    assert result["scene_index_diagnostics"]["status"] == "indexed"
    assert result["scene_index_diagnostics"]["object_candidate_count"] == 1
    assert result["object_index"]["mug_01"]["usd_prim_path"] == "/World/Objects/mug_01"
    assert result["receptacle_index"]["sink_01"]["usd_prim_path"] == ("/World/Receptacles/sink_01")
    assert any(
        item["area"] == "camera_capture" and item["status"] == "real_rendering_proven"
        for item in result["mapping_gaps"]
    )
    assert any(
        item["area"] == "local_usd_scene_loading" and item["status"] == "loaded"
        for item in result["mapping_gaps"]
    )
    assert any(
        item["area"] == "robot_view_variants" and item["status"] == "real_rendering_proven"
        for item in result["mapping_gaps"]
    )

    state = json.loads(state_path.read_text(encoding="utf-8"))
    assert state["runtime"]["rendering"]["status"] == "real_rendering_proven"
    assert state["scene_load"]["usd_stage_loaded"] is True
    assert state["real_runtime_smoke"]["scene_usd"] == str(scene_usd)
    assert state["robot_view_images"] == robot_view_images
    assert state["scene_index_diagnostics"]["status"] == "indexed"
    assert state["scene_binding_diagnostics"]["status"] == "selected_bound"
    assert state["scene_binding_diagnostics"]["selected_object_bound_count"] == 1
    assert state["scene_binding_diagnostics"]["selected_target_receptacle_bound_count"] == 1
    assert state["segmentation"]["status"] == "available"
    assert state["segmentation"]["candidate_bbox_count"] == 1
    assert state["segmentation"]["selected_usd_prim_match_count"] == 1
    assert state["segmentation"]["agent_facing"] is False
    assert state["segmentation"]["no_simulator_label_fallback"] is True


def test_isaac_lab_segmentation_capture_extracts_selected_bbox() -> None:
    import numpy as np

    class CameraData:
        output = {
            "instance_id_segmentation_fast": np.array(
                [
                    [[0], [0], [0], [0]],
                    [[0], [3], [3], [0]],
                    [[0], [3], [3], [0]],
                    [[0], [0], [0], [0]],
                ]
            )
        }
        info = {
            "instance_id_segmentation_fast": {
                "idToLabels": {3: "/World/Objects/mug_01"},
            }
        }

    class Camera:
        data = CameraData()

    view = isaac_lab_backend_worker._camera_segmentation_view_diagnostics(
        Camera(),
        data_types=("instance_id_segmentation_fast",),
        view_name="fpv",
        np=np,
    )
    capture = isaac_lab_backend_worker._camera_segmentation_capture_diagnostics(
        [view],
        requested_data_types=("instance_id_segmentation_fast",),
        semantic_filter=["class"],
    )
    diagnostics = isaac_lab_backend_worker.segmentation_diagnostics(
        "real",
        real_smoke={"segmentation": capture},
        scene_binding_diagnostics={
            "selected_object_bindings": {
                "mug_01": {
                    "status": "bound",
                    "usd_prim_path": "/World/Objects/mug_01",
                }
            },
            "selected_target_receptacle_bindings": {},
        },
    )

    assert capture["output_data_types"] == ["instance_id_segmentation_fast"]
    assert capture["requested_data_types"] == ["instance_id_segmentation_fast"]
    assert capture["semantic_filter"] == ["class"]
    assert capture["candidate_bbox_count"] == 1
    assert diagnostics["status"] == "available"
    assert diagnostics["semantic_filter"] == ["class"]
    assert diagnostics["candidate_bbox_count"] == 1
    assert diagnostics["selected_usd_prim_match_count"] == 1
    assert diagnostics["selected_candidate_bboxes"][0]["bbox_xyxy"] == [1, 1, 3, 3]
    assert diagnostics["agent_facing"] is False
    assert diagnostics["no_simulator_label_fallback"] is True


def test_isaac_segmentation_diagnostics_reports_unrenderable_selected_prims() -> None:
    diagnostics = isaac_lab_backend_worker.segmentation_diagnostics(
        "real",
        real_smoke={
            "segmentation": {
                "requested_data_types": ["semantic_segmentation"],
                "output_data_types": ["semantic_segmentation"],
                "candidate_bboxes": [
                    {
                        "data_type": "semantic_segmentation",
                        "label": "BACKGROUND",
                        "label_id": 0,
                        "usd_prim_path": "",
                        "bbox_xyxy": [0, 0, 540, 360],
                        "pixel_count": 194400,
                        "image_size": [540, 360],
                    }
                ],
                "no_simulator_label_fallback": True,
            }
        },
        scene_binding_diagnostics={
            "selected_object_bindings": {
                "bowl_01": {
                    "status": "bound",
                    "usd_prim_path": "/World/Objects/bowl_01",
                    "has_renderable_geometry": False,
                }
            },
            "selected_target_receptacle_bindings": {
                "sink_01": {
                    "status": "bound",
                    "usd_prim_path": "/World/Receptacles/sink_01",
                    "has_renderable_geometry": True,
                }
            },
        },
    )

    assert diagnostics["available"] is False
    assert diagnostics["selected_usd_unrenderable_prim_paths"] == ["/World/Objects/bowl_01"]
    assert any("no renderable geometry" in blocker for blocker in diagnostics["blockers"])


def test_isaac_segmentation_matches_usd_paths_case_insensitively() -> None:
    diagnostics = isaac_lab_backend_worker.segmentation_diagnostics(
        "real",
        real_smoke={
            "segmentation": {
                "requested_data_types": ["semantic_segmentation"],
                "output_data_types": ["semantic_segmentation"],
                "candidate_bboxes": [
                    {
                        "data_type": "semantic_segmentation",
                        "label": "/world/objects/mug_01",
                        "label_id": 4,
                        "usd_prim_path": "/world/objects/mug_01",
                        "bbox_xyxy": [8, 8, 32, 36],
                        "pixel_count": 144,
                        "image_size": [540, 360],
                    }
                ],
                "no_simulator_label_fallback": True,
            }
        },
        scene_binding_diagnostics={
            "selected_object_bindings": {
                "mug_01": {
                    "status": "bound",
                    "usd_prim_path": "/World/Objects/mug_01",
                    "has_renderable_geometry": True,
                }
            },
            "selected_target_receptacle_bindings": {},
        },
    )

    assert diagnostics["available"] is True
    assert diagnostics["selected_usd_prim_match_count"] == 1


def test_isaac_lab_segmentation_capture_accepts_list_info_shape() -> None:
    import numpy as np

    class CameraData:
        output = {
            "semantic_segmentation": np.array(
                [
                    [[0], [0], [0], [0]],
                    [[0], [5], [5], [0]],
                    [[0], [5], [5], [0]],
                    [[0], [0], [0], [0]],
                ]
            )
        }
        info = [
            {
                "semantic_segmentation": {
                    "idToLabels": {"5": {"usd_prim_path": "/World/Objects/bowl_01"}},
                }
            }
        ]

    class Camera:
        data = CameraData()

    view = isaac_lab_backend_worker._camera_segmentation_view_diagnostics(
        Camera(),
        data_types=("semantic_segmentation",),
        view_name="fpv",
        np=np,
    )
    capture = isaac_lab_backend_worker._camera_segmentation_capture_diagnostics(
        [view],
        requested_data_types=("semantic_segmentation",),
    )

    assert capture["output_data_types"] == ["semantic_segmentation"]
    assert capture["candidate_bbox_count"] == 1
    assert capture["candidate_bboxes"][0]["label"] == "/World/Objects/bowl_01"
    assert capture["candidate_bboxes"][0]["bbox_xyxy"] == [1, 1, 3, 3]


def test_isaac_scene_index_semantic_labels_are_applied_to_stage_prims(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    records: list[tuple[str, str, tuple[str, ...]]] = []

    class Prim:
        def __init__(self, path: str, valid: bool = True, type_name: str = "") -> None:
            self.path = path
            self.valid = valid
            self.type_name = type_name

        def IsValid(self) -> bool:
            return self.valid

    bowl = Prim("/World/Objects/bowl_01")
    bowl_mesh = Prim("/World/Objects/bowl_01/mesh", type_name="Mesh")
    sink = Prim("/World/Receptacles/sink_01", type_name="Cube")

    class Stage:
        def __init__(self) -> None:
            self.prims = {
                "/World/Objects/bowl_01": bowl,
                "/World/Receptacles/sink_01": sink,
            }

        def GetPrimAtPath(self, path: str) -> Prim:
            return self.prims.get(path, Prim(path, valid=False))

    class StageUtils:
        @staticmethod
        def get_current_stage() -> Stage:
            return Stage()

    class SimUtils:
        @staticmethod
        def add_labels(
            prim: Prim,
            *,
            labels: list[str],
            instance_name: str,
            overwrite: bool,
        ) -> None:
            assert overwrite is True
            records.append((prim.path, instance_name, tuple(labels)))

    monkeypatch.setattr(
        isaac_lab_backend_worker,
        "_semantic_label_target_prims",
        lambda prim: [bowl, bowl_mesh] if prim is bowl else [prim],
    )

    result = isaac_lab_backend_worker._apply_scene_index_semantic_labels(
        stage_utils=StageUtils(),
        sim_utils=SimUtils(),
        scene_index_diagnostics={
            "object_index": {
                "bowl_01": {
                    "usd_prim_path": "/World/Objects/bowl_01",
                    "category": "Bowl",
                    "kind": "object",
                }
            },
            "receptacle_index": {
                "sink_01": {
                    "usd_prim_path": "/World/Receptacles/sink_01",
                    "category": "Sink",
                    "kind": "receptacle",
                },
                "missing": {
                    "usd_prim_path": "/World/Receptacles/missing",
                    "category": "CounterTop",
                    "kind": "receptacle",
                },
            },
        },
    )

    assert result["status"] == "applied"
    assert result["applied_count"] == 2
    assert result["labeled_prim_count"] == 3
    assert result["descendant_label_count"] == 1
    assert result["gprim_label_count"] == 2
    assert result["mesh_label_count"] == 1
    assert result["missing_prim_count"] == 1
    assert {
        "source_prim_path": "/World/Objects/bowl_01",
        "target_prim_path": "/World/Objects/bowl_01/mesh",
        "target_type": "Mesh",
        "target_kind": "gprim:Mesh",
    } in result["target_samples"]
    assert ("/World/Objects/bowl_01", "class", ("Bowl",)) in records
    assert ("/World/Objects/bowl_01/mesh", "class", ("Bowl",)) in records
    assert (
        "/World/Objects/bowl_01",
        "usd_prim_path",
        ("/World/Objects/bowl_01",),
    ) in records
    assert ("/World/Receptacles/sink_01", "kind", ("receptacle",)) in records


def test_isaac_runtime_smoke_accepts_official_blocks_generated_scene(
    tmp_path: Path,
) -> None:
    args = isaac_lab_backend_worker.parse_args(
        [
            "--state-path",
            str(tmp_path / "state.json"),
            "init",
            "--run-dir",
            str(tmp_path / "run"),
            "--runtime-mode",
            "fake",
            "--generated-scene-kind",
            "isaac_official_blocks",
        ]
    )

    assert args.generated_scene_kind == "isaac_official_blocks"
    assert (
        isaac_lab_backend_worker._generated_scene_filename(args.generated_scene_kind)
        == "roboclaws_isaac_official_blocks_scene.usda"
    )


def test_isaac_lab_generated_count_selects_private_targets_not_first_object(
    tmp_path: Path,
) -> None:
    args = isaac_lab_backend_worker.parse_args(
        [
            "--state-path",
            str(tmp_path / "state.json"),
            "init",
            "--run-dir",
            str(tmp_path / "run"),
            "--runtime-mode",
            "fake",
            "--generated-mess-count",
            "1",
        ]
    )
    result = isaac_lab_backend_worker.init_state(args)

    object_ids = [item["object_id"] for item in result["scenario"]["objects"]]
    target_ids = [item["object_id"] for item in result["private_manifest"]["targets"]]

    assert object_ids == ["mug_01"]
    assert target_ids == ["mug_01"]
    assert object_ids != ["toy_car_01"]
    assert result["scene_binding_diagnostics"]["selected_object_count"] == 1
    assert result["scene_binding_diagnostics"]["selected_target_receptacle_count"] == 1


def test_isaac_lab_real_worker_views_reuse_real_smoke_images(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    run_dir = tmp_path / "run"
    state_path = tmp_path / "state.json"
    image_path = run_dir / "isaac_runtime_smoke.png"
    robot_view_images = _write_robot_view_images(run_dir)
    _write_nonblank_image(image_path)

    def fake_real_runtime_smoke(
        args: object,
        scenario: object,
    ) -> dict[str, object]:
        del args, scenario
        return {
            "image_path": str(image_path),
            "scene_usd": str(run_dir / "scene.usda"),
            "loaded_asset_kind": "generated_runtime_smoke_usd",
            "requested_scene_source": "procthor-10k-val",
            "requested_scene_index": 0,
            "requested_molmospaces_scene_usd": "molmospaces://procthor-10k-val/scene-0.usd",
            "isaac_lab_version": "unit-isaaclab",
            "isaac_sim_version": "unit-isaacsim",
            "renderer_mode": "isaac_lab_headless_rtx",
            "capture_method": "isaac_lab_camera_rgb",
            "robot_view_capture_method": "isaac_lab_camera_rgb_static_robot_views",
            "robot_view_images": robot_view_images,
            "camera_resolution": [540, 360],
            "stage_prim_count": 6,
            "render_steps": 4,
            "scene_index_diagnostics": {
                "schema": "isaac_usd_scene_index_v1",
                "status": "indexed",
                "source": str(run_dir / "scene.usda"),
                "stage_prim_count": 6,
                "object_candidate_count": 1,
                "receptacle_candidate_count": 1,
                "blockers": [],
            },
            "object_index": _unit_isaac_object_index(),
            "receptacle_index": _unit_isaac_receptacle_index(),
        }

    monkeypatch.setattr(
        isaac_lab_backend_worker,
        "real_runtime_smoke",
        fake_real_runtime_smoke,
    )
    init_args = isaac_lab_backend_worker.parse_args(
        [
            "--state-path",
            str(state_path),
            "init",
            "--run-dir",
            str(run_dir),
            "--runtime-mode",
            "real",
            "--include-robot",
        ]
    )
    isaac_lab_backend_worker.init_state(init_args)
    view_args = isaac_lab_backend_worker.parse_args(
        [
            "--state-path",
            str(state_path),
            "robot_views",
            "--output-dir",
            str(run_dir / "robot_views"),
            "--label",
            "runtime smoke",
            "--render-width",
            "64",
            "--render-height",
            "48",
        ]
    )
    result = isaac_lab_backend_worker.write_robot_views(
        view_args,
        isaac_lab_backend_worker.read_state(state_path),
    )

    assert result["ok"] is True
    assert result["view_variant"] == ISAACLAB_ROBOT_VIEW_VARIANT
    assert "placeholder" not in json.dumps(result["view_provenance"])
    assert set(result["views"]) == {"fpv", "chase", "topdown", "verify"}
    assert result["shapes"]["fpv"] == [48, 64, 3]
    for path in result["views"].values():
        assert Path(path).is_file()


def test_isaac_lab_real_worker_views_recapture_semantic_pose_state(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    context = _setup_semantic_pose_recapture_runtime(monkeypatch, tmp_path)
    _patch_semantic_pose_recapture_captures(monkeypatch, context)
    _init_real_worker_with_scene_usd(context)
    _navigate_real_worker_to_receptacle(context)
    result = _write_semantic_pose_robot_views(context)

    _assert_semantic_pose_recapture_result(result)
    state = isaac_lab_backend_worker.read_state(context.state_path)
    _assert_semantic_pose_recapture_state(state)


def _setup_semantic_pose_recapture_runtime(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> SimpleNamespace:
    run_dir = tmp_path / "run"
    state_path = tmp_path / "state.json"
    image_path = run_dir / "isaac_runtime_smoke.png"
    robot_view_images = _write_robot_view_images(run_dir)
    scene_usd = run_dir / "scene.usda"
    scene_usd.parent.mkdir(parents=True, exist_ok=True)
    scene_usd.write_text("#usda 1.0\n", encoding="utf-8")
    _write_nonblank_image(image_path)
    monkeypatch.setattr(
        isaac_lab_backend_worker,
        "ISAAC_RBY1M_ROBOT_USD_PATH",
        tmp_path / "missing_rby1m_holobase_isaac.usda",
    )
    monkeypatch.setattr(
        isaac_lab_backend_worker,
        "ISAAC_RBY1M_ROBOT_IMPORT_SUMMARY_PATH",
        tmp_path / "missing_rby1m_holobase_isaac.import_summary.json",
    )
    context = SimpleNamespace(
        run_dir=run_dir,
        state_path=state_path,
        image_path=image_path,
        robot_view_images=robot_view_images,
        scene_usd=scene_usd,
    )

    def fake_real_runtime_smoke(
        args: object,
        scenario: object,
    ) -> dict[str, object]:
        del args, scenario
        return {
            "image_path": str(image_path),
            "scene_usd": str(scene_usd),
            "loaded_asset_kind": "local_scene_usd",
            "requested_scene_source": "procthor-10k-val",
            "requested_scene_index": 0,
            "requested_molmospaces_scene_usd": "molmospaces://procthor-10k-val/scene-0.usd",
            "isaac_lab_version": "unit-isaaclab",
            "isaac_sim_version": "unit-isaacsim",
            "renderer_mode": "isaac_lab_headless_rtx",
            "capture_method": "isaac_lab_camera_rgb",
            "robot_view_capture_method": "isaac_lab_camera_rgb_static_robot_views",
            "robot_view_images": robot_view_images,
            "camera_resolution": [540, 360],
            "stage_prim_count": 6,
            "render_steps": 4,
            "scene_index_diagnostics": {
                "schema": "isaac_usd_scene_index_v1",
                "status": "indexed",
                "source": str(scene_usd),
                "stage_prim_count": 6,
                "object_candidate_count": 1,
                "receptacle_candidate_count": 1,
                "blockers": [],
            },
            "object_index": _unit_isaac_object_index(),
            "receptacle_index": _unit_isaac_receptacle_index(),
        }

    monkeypatch.setattr(
        isaac_lab_backend_worker,
        "real_runtime_smoke",
        fake_real_runtime_smoke,
    )
    return context


def _patch_semantic_pose_recapture_captures(
    monkeypatch: pytest.MonkeyPatch,
    context: SimpleNamespace,
) -> None:
    def fake_capture_semantic_pose_robot_views(
        *,
        state: dict[str, object],
        scene_usd: Path,
        view_paths: dict[str, Path],
        width: int,
        height: int,
        render_settle_frames: int = 0,
        focus_object_id: str | None = None,
        focus_receptacle_id: str | None = None,
    ) -> dict[str, object]:
        del focus_object_id, focus_receptacle_id
        assert scene_usd == context.scene_usd
        assert width == 64
        assert height == 48
        assert render_settle_frames == 16
        semantic_pose = state["semantic_pose_state"]
        assert isinstance(semantic_pose, dict)
        assert semantic_pose["rendered_to_usd"] is False
        for path in view_paths.values():
            _write_nonblank_image(path)
        return {
            "robot_view_images": {key: str(path) for key, path in view_paths.items()},
            "scene_bounds": {
                "min": [-2.0, -3.0, 0.0],
                "max": [4.0, 5.0, 2.5],
                "size": [6.0, 8.0, 2.5],
                "center": [1.0, 1.0, 1.25],
            },
            "render_steps": 9,
            "render_settle_frames": render_settle_frames,
            "robot_view_uses_mounted_head_camera": False,
            "semantic_pose_stage_application": {
                "schema": "isaac_semantic_pose_stage_application_v1",
                "status": "applied",
                "applied_object_count": 1,
                "failed_object_count": 0,
                "rendered_to_usd": True,
            },
            "camera_diagnostics": {
                "schema": "isaac_robot_view_camera_diagnostics_v1",
                "views": {
                    "fpv": {
                        "schema": "isaac_eye_target_camera_diagnostics_v1",
                        "status": "ready",
                        "camera_type": "eye_target_scene_camera",
                    }
                },
            },
        }

    def fake_capture_scene_camera_views(
        *,
        scene_usd: Path,
        camera_request: dict[str, object],
        output_dir: Path,
        width: int,
        height: int,
        simulation_app: object,
        semantic_pose_state: dict[str, object] | None = None,
    ) -> dict[str, object]:
        assert scene_usd == context.scene_usd
        assert simulation_app == "unit-simulation-app"
        assert semantic_pose_state is not None
        assert camera_request["api_name"] == "roboclaws.camera_control.render_views"
        output_dir.mkdir(parents=True, exist_ok=True)
        views = []
        images: dict[str, str] = {}
        for item in camera_request["views"]:
            assert isinstance(item, dict)
            assert item["robot_view_role"] in {"fpv", "verify"}
            image_path = output_dir / f"{item['view_id']}.png"
            _write_nonblank_image(image_path)
            views.append({**item, "image_path": str(image_path), "shape": [height, width, 3]})
            images[str(item["view_id"])] = str(image_path)
        return {
            "camera_control_api": camera_request["api_name"],
            "color_profile": camera_request.get("color_profile"),
            "color_management": {
                "isaac_robot_view_fpv": {
                    "after": {"overexposed_fraction": 0.0},
                }
            },
            "views": views,
            "images": images,
            "render_steps": 6,
        }

    monkeypatch.setattr(
        isaac_lab_backend_worker,
        "capture_semantic_pose_robot_views",
        fake_capture_semantic_pose_robot_views,
    )
    monkeypatch.setattr(
        isaac_lab_backend_worker,
        "_capture_isaac_lab_scene_camera_views",
        fake_capture_scene_camera_views,
    )


def _init_real_worker_with_scene_usd(context: SimpleNamespace) -> None:
    init_args = isaac_lab_backend_worker.parse_args(
        [
            "--state-path",
            str(context.state_path),
            "init",
            "--run-dir",
            str(context.run_dir),
            "--runtime-mode",
            "real",
            "--include-robot",
            "--scene-usd-path",
            str(context.scene_usd),
        ]
    )
    isaac_lab_backend_worker.init_state(init_args)


def _navigate_real_worker_to_receptacle(context: SimpleNamespace) -> None:
    nav_args = isaac_lab_backend_worker.parse_args(
        [
            "--state-path",
            str(context.state_path),
            "navigate_to_receptacle",
            "--receptacle-id",
            "sink_01",
        ]
    )
    nav_result = isaac_lab_backend_worker.navigate_to_receptacle(
        nav_args,
        isaac_lab_backend_worker.read_state(context.state_path),
    )
    assert nav_result["ok"] is True
    assert nav_result["robot_pose"]["pose_source"] == "roboclaws_shared_scene_frame_support_pose"


def _write_semantic_pose_robot_views(context: SimpleNamespace) -> dict[str, object]:
    result = isaac_lab_backend_worker.write_robot_views(
        isaac_lab_backend_worker.parse_args(
            [
                "--state-path",
                str(context.state_path),
                "robot_views",
                "--output-dir",
                str(context.run_dir / "robot_views"),
                "--label",
                "0001_semantic_pose",
                "--render-width",
                "64",
                "--render-height",
                "48",
                "--render-settle-frames",
                "16",
            ]
        ),
        isaac_lab_backend_worker.read_state(context.state_path),
    )
    assert isinstance(result, dict)
    return result


def _assert_semantic_pose_recapture_result(result: dict[str, object]) -> None:
    assert result["ok"] is True
    assert result["view_provenance"]["semantic_pose_state_refreshed"] is True
    assert result["view_provenance"]["canonical_camera_control"] is False
    assert result["view_provenance"]["head_camera_equivalent"] is True
    assert result["camera_control_contract"]["status"] == (
        "robot_head_camera_equivalent_robot_view"
    )
    assert result["camera_control_contract"]["camera_model"] == "robot_head_camera_equivalent_v1"
    assert result["camera_control_contract"]["same_pose_api"] is False
    assert result["camera_control_contract"]["camera_control_api"] is None
    assert result["camera_control_contract"]["robot_pose"]["pose_source"] == (
        "roboclaws_shared_scene_frame_support_pose"
    )
    assert result["camera_control_contract"]["robot_pose"]["pose_request"]["resolver"] == (
        "roboclaws.cleanup_robot_pose.near_target_v1"
    )
    assert result["camera_diagnostics"]["schema"] == "isaac_robot_view_camera_diagnostics_v1"
    assert result["camera_diagnostics"]["views"]["fpv"]["camera_type"] == (
        "eye_target_scene_camera"
    )
    assert "isaac_lab_camera_rgb_head_camera_equivalent" in json.dumps(result["view_provenance"])


def _assert_semantic_pose_recapture_state(state: dict[str, object]) -> None:
    assert state["semantic_pose_state"]["rendered_to_usd"] is True
    assert state["robot_view_provenance"]["semantic_pose_state_refreshed"] is True
    assert state["robot_view_provenance"]["canonical_camera_control"] is False
    assert state["robot_view_provenance"]["head_camera_equivalent"] is True
    assert state["semantic_pose_view_capture"]["render_steps"] == 9
    assert state["semantic_pose_view_capture"]["render_settle_frames"] == 16
    assert state["scene_bounds"]["center"] == [1.0, 1.0, 1.25]
    assert state["semantic_pose_view_capture"]["scene_bounds"]["size"] == [6.0, 8.0, 2.5]
    assert state["semantic_pose_view_capture"]["canonical_camera_control"] is False
    assert state["semantic_pose_view_capture"]["head_camera_equivalent"] is True
    assert "canonical_robot_view_camera_control_capture" not in state
    assert state["semantic_pose_state"]["semantic_pose_view_capture"]["render_steps"] == 9
    assert state["semantic_pose_state"]["semantic_pose_view_capture"]["scene_bounds"]["center"] == [
        1.0,
        1.0,
        1.25,
    ]
    assert state["semantic_pose_state"]["semantic_pose_view_capture"]["render_settle_frames"] == 16
    robot_view_gap = next(
        item for item in state["mapping_gaps"] if item["area"] == "robot_view_variants"
    )
    assert robot_view_gap["source"] == "isaac_lab_camera_rgb_semantic_pose_robot_views"
    assert "recaptured from the loaded USD scene" in robot_view_gap["detail"]
    assert "static Phase B" not in robot_view_gap["detail"]


def test_isaac_lab_real_worker_views_accept_robot_pose_only_rerender(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    run_dir = tmp_path / "run"
    state_path = tmp_path / "state.json"
    image_path = run_dir / "isaac_runtime_smoke.png"
    robot_view_images = _write_robot_view_images(run_dir)
    scene_usd = run_dir / "scene.usda"
    scene_usd.parent.mkdir(parents=True, exist_ok=True)
    scene_usd.write_text("#usda 1.0\n", encoding="utf-8")
    _write_nonblank_image(image_path)
    monkeypatch.setattr(
        isaac_lab_backend_worker,
        "ISAAC_RBY1M_ROBOT_USD_PATH",
        tmp_path / "missing_rby1m_holobase_isaac.usda",
    )
    monkeypatch.setattr(
        isaac_lab_backend_worker,
        "ISAAC_RBY1M_ROBOT_IMPORT_SUMMARY_PATH",
        tmp_path / "missing_rby1m_holobase_isaac.import_summary.json",
    )

    def fake_real_runtime_smoke(
        args: object,
        scenario: object,
    ) -> dict[str, object]:
        del args, scenario
        return {
            "image_path": str(image_path),
            "scene_usd": str(scene_usd),
            "loaded_asset_kind": "local_scene_usd",
            "requested_scene_source": "procthor-10k-val",
            "requested_scene_index": 0,
            "requested_molmospaces_scene_usd": "molmospaces://procthor-10k-val/scene-0.usd",
            "isaac_lab_version": "unit-isaaclab",
            "isaac_sim_version": "unit-isaacsim",
            "renderer_mode": "isaac_lab_headless_rtx",
            "capture_method": "isaac_lab_camera_rgb",
            "robot_view_capture_method": "isaac_lab_camera_rgb_static_robot_views",
            "robot_view_images": robot_view_images,
            "camera_resolution": [540, 360],
            "stage_prim_count": 6,
            "render_steps": 4,
            "scene_index_diagnostics": {
                "schema": "isaac_usd_scene_index_v1",
                "status": "indexed",
                "source": str(scene_usd),
                "stage_prim_count": 6,
                "object_candidate_count": 0,
                "receptacle_candidate_count": 1,
                "blockers": [],
            },
            "object_index": {},
            "receptacle_index": _unit_isaac_receptacle_index(),
        }

    def fake_capture_semantic_pose_robot_views(
        *,
        state: dict[str, object],
        scene_usd: Path,
        view_paths: dict[str, Path],
        width: int,
        height: int,
        render_settle_frames: int = 0,
        focus_object_id: str | None = None,
        focus_receptacle_id: str | None = None,
    ) -> dict[str, object]:
        del state, scene_usd, width, height, render_settle_frames
        del focus_object_id, focus_receptacle_id
        for path in view_paths.values():
            _write_nonblank_image(path)
        return {
            "robot_view_images": {key: str(path) for key, path in view_paths.items()},
            "render_steps": 7,
            "robot_view_uses_mounted_head_camera": False,
            "semantic_pose_stage_application": {
                "schema": "isaac_semantic_pose_stage_application_v1",
                "status": "blocked",
                "applied_object_count": 0,
                "failed_object_count": 0,
                "rendered_to_usd": False,
            },
            "robot_pose_stage_application": {
                "schema": "isaac_robot_head_camera_pose_application_v1",
                "status": "applied",
                "robot_prim_path": "/World/robot_0",
                "position": [1.0, 2.0, 0.0],
                "position_source": "semantic_pose_state.robot_pose",
            },
            "camera_diagnostics": {
                "schema": "isaac_robot_view_camera_diagnostics_v1",
                "views": {},
            },
        }

    monkeypatch.setattr(
        isaac_lab_backend_worker,
        "real_runtime_smoke",
        fake_real_runtime_smoke,
    )
    monkeypatch.setattr(
        isaac_lab_backend_worker,
        "capture_semantic_pose_robot_views",
        fake_capture_semantic_pose_robot_views,
    )
    init_args = isaac_lab_backend_worker.parse_args(
        [
            "--state-path",
            str(state_path),
            "init",
            "--run-dir",
            str(run_dir),
            "--runtime-mode",
            "real",
            "--include-robot",
            "--scene-usd-path",
            str(scene_usd),
        ]
    )
    isaac_lab_backend_worker.init_state(init_args)
    result = isaac_lab_backend_worker.write_robot_views(
        isaac_lab_backend_worker.parse_args(
            [
                "--state-path",
                str(state_path),
                "robot_views",
                "--output-dir",
                str(run_dir / "robot_views"),
                "--label",
                "0001_robot_pose_only",
                "--render-width",
                "64",
                "--render-height",
                "48",
            ]
        ),
        isaac_lab_backend_worker.read_state(state_path),
    )

    assert result["ok"] is True
    assert result["view_provenance"]["semantic_pose_state_refreshed"] is True
    assert result["camera_control_contract"]["robot_pose"]["pose_source"]
    state = isaac_lab_backend_worker.read_state(state_path)
    assert state["semantic_pose_view_capture"]["rendered_to_usd"] is True
    assert state["semantic_pose_view_capture"]["robot_pose_stage_application"]["status"] == (
        "applied"
    )
    assert state["semantic_pose_state"]["robot_pose_rendered_to_usd"] is True
    assert not any(
        item.get("area") == "semantic_pose_robot_view_rerender" for item in state["mapping_gaps"]
    )


def test_isaac_lab_real_worker_robot_views_use_imported_head_camera(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    run_dir = tmp_path / "run"
    state_path = tmp_path / "state.json"
    image_path = run_dir / "isaac_runtime_smoke.png"
    robot_view_images = _write_robot_view_images(run_dir)
    scene_usd = run_dir / "scene.usda"
    robot_usd = tmp_path / "rby1m_holobase_isaac.usda"
    summary_path = tmp_path / "rby1m_holobase_isaac.import_summary.json"
    scene_usd.parent.mkdir(parents=True, exist_ok=True)
    scene_usd.write_text("#usda 1.0\n", encoding="utf-8")
    robot_usd.write_text("#usda 1.0\n", encoding="utf-8")
    summary_path.write_text(
        json.dumps({"schema": "isaac_rby1m_robot_usd_import_v1", "status": "ready"}) + "\n",
        encoding="utf-8",
    )
    _write_nonblank_image(image_path)

    monkeypatch.setattr(isaac_lab_backend_worker, "ISAAC_RBY1M_ROBOT_USD_PATH", robot_usd)
    monkeypatch.setattr(
        isaac_lab_backend_worker,
        "ISAAC_RBY1M_ROBOT_IMPORT_SUMMARY_PATH",
        summary_path,
    )
    monkeypatch.setattr(isaac_lab_backend_worker, "_repo_path", lambda path: path)

    def fake_real_runtime_smoke(args: object, scenario: object) -> dict[str, object]:
        del args, scenario
        return {
            "image_path": str(image_path),
            "scene_usd": str(scene_usd),
            "loaded_asset_kind": "local_scene_usd",
            "requested_scene_source": "procthor-10k-val",
            "requested_scene_index": 0,
            "requested_molmospaces_scene_usd": "molmospaces://procthor-10k-val/scene-0.usd",
            "isaac_lab_version": "unit-isaaclab",
            "isaac_sim_version": "unit-isaacsim",
            "renderer_mode": "isaac_lab_headless_rtx",
            "capture_method": "isaac_lab_camera_rgb",
            "robot_view_capture_method": "isaac_lab_camera_rgb_static_robot_views",
            "robot_view_images": robot_view_images,
            "robot_view_uses_mounted_head_camera": True,
            "camera_resolution": [540, 360],
            "stage_prim_count": 6,
            "render_steps": 4,
            "scene_index_diagnostics": {
                "schema": "isaac_usd_scene_index_v1",
                "status": "indexed",
                "source": str(scene_usd),
                "stage_prim_count": 6,
                "object_candidate_count": 1,
                "receptacle_candidate_count": 1,
                "blockers": [],
            },
            "object_index": _unit_isaac_object_index(),
            "receptacle_index": _unit_isaac_receptacle_index(),
        }

    def fake_capture_semantic_pose_robot_views(
        *,
        state: dict[str, object],
        scene_usd: Path,
        view_paths: dict[str, Path],
        width: int,
        height: int,
        focus_object_id: str | None = None,
        focus_receptacle_id: str | None = None,
    ) -> dict[str, object]:
        del state, scene_usd, width, height, focus_object_id, focus_receptacle_id
        for path in view_paths.values():
            _write_nonblank_image(path)
        return {
            "robot_view_images": {key: str(path) for key, path in view_paths.items()},
            "render_steps": 11,
            "robot_view_uses_mounted_head_camera": True,
            "semantic_pose_stage_application": {
                "schema": "isaac_semantic_pose_stage_application_v1",
                "status": "applied",
                "applied_object_count": 1,
                "failed_object_count": 0,
                "rendered_to_usd": True,
            },
            "robot_stage": {
                "status": "referenced",
                "head_camera_prim_exists": True,
                "head_camera_prim_path": "/World/robot_0/head_camera",
            },
            "camera_diagnostics": {
                "schema": "isaac_robot_view_camera_diagnostics_v1",
                "views": {
                    "fpv": {
                        "schema": "isaac_usd_camera_diagnostics_v1",
                        "status": "ready",
                        "camera_type": "usd_camera_prim",
                        "prim_path": "/World/robot_0/head_camera",
                    },
                    "chase": {
                        "schema": "isaac_eye_target_camera_diagnostics_v1",
                        "status": "ready",
                        "camera_type": "eye_target_scene_camera",
                        "camera_basis": "robot_relative_camera_follower",
                        "vertical_fov_deg": 45.0,
                    },
                },
            },
        }

    monkeypatch.setattr(isaac_lab_backend_worker, "real_runtime_smoke", fake_real_runtime_smoke)
    monkeypatch.setattr(
        isaac_lab_backend_worker,
        "capture_semantic_pose_robot_views",
        fake_capture_semantic_pose_robot_views,
    )
    init_args = isaac_lab_backend_worker.parse_args(
        [
            "--state-path",
            str(state_path),
            "init",
            "--run-dir",
            str(run_dir),
            "--runtime-mode",
            "real",
            "--include-robot",
            "--scene-usd-path",
            str(scene_usd),
        ]
    )
    init = isaac_lab_backend_worker.init_state(init_args)
    assert init["robot"]["embodiment"] == "rby1m"
    assert init["robot_import"]["status"] == "imported"
    state = isaac_lab_backend_worker.read_state(state_path)
    state["semantic_pose_state"]["robot_pose"] = {
        "frame": "molmospaces_scene_frame_v1",
        "x": 6.37057,
        "y": 8.8752,
        "z": 0.0,
        "theta": math.pi / 2.0,
        "yaw_deg": 90.0,
        "head_pitch": 0.653613,
        "pose_source": "apple2apple_shared_robot_pose",
    }
    isaac_lab_backend_worker.write_state(state_path, state)

    result = isaac_lab_backend_worker.write_robot_views(
        isaac_lab_backend_worker.parse_args(
            [
                "--state-path",
                str(state_path),
                "robot_views",
                "--output-dir",
                str(run_dir / "robot_views"),
                "--label",
                "0001_semantic_pose",
                "--render-width",
                "64",
                "--render-height",
                "48",
            ]
        ),
        isaac_lab_backend_worker.read_state(state_path),
    )

    assert result["ok"] is True
    assert result["view_provenance"]["robot_mounted_head_camera"] is True
    assert result["view_provenance"]["head_camera_equivalent"] is False
    assert result["camera_control_contract"]["status"] == "robot_mounted_head_camera_robot_view"
    assert result["camera_control_contract"]["camera_model"] == "robot_mounted_head_camera_v1"
    assert result["camera_control_contract"]["agent_facing_fpv"]["robot_mounted"] is True
    assert result["camera_control_contract"]["agent_facing_fpv"]["camera_prim_path"] == (
        "/World/robot_0/head_camera"
    )
    assert result["camera_control_contract"]["report_chase_view"]["source"] == (
        "robot_relative_camera_follower"
    )
    assert result["camera_control_contract"]["robot_pose"]["pose_source"] == (
        "apple2apple_shared_robot_pose"
    )
    assert result["camera_control_contract"]["robot_pose"]["x"] == pytest.approx(6.37057)
    assert result["camera_control_contract"]["robot_pose"]["yaw_deg"] == pytest.approx(90.0)
    assert result["camera_diagnostics"]["schema"] == "isaac_robot_view_camera_diagnostics_v1"
    assert result["camera_diagnostics"]["views"]["fpv"]["prim_path"] == (
        "/World/robot_0/head_camera"
    )
    assert result["camera_diagnostics"]["views"]["chase"]["camera_basis"] == (
        "robot_relative_camera_follower"
    )
    assert result["camera_diagnostics"]["views"]["chase"]["vertical_fov_deg"] == pytest.approx(45.0)
    state = isaac_lab_backend_worker.read_state(state_path)
    assert state["semantic_pose_view_capture"]["robot_mounted_head_camera"] is True
    assert state["semantic_pose_view_capture"]["head_camera_equivalent"] is False


def test_isaac_lab_real_worker_robot_views_record_capture_quality_settle(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    run_dir = tmp_path / "run"
    state_path = tmp_path / "state.json"
    image_path = run_dir / "isaac_runtime_smoke.png"
    robot_view_images = _write_robot_view_images(run_dir)
    scene_usd = run_dir / "scene.usda"
    scene_usd.parent.mkdir(parents=True, exist_ok=True)
    scene_usd.write_text("#usda 1.0\n", encoding="utf-8")
    _write_nonblank_image(image_path)

    def fake_real_runtime_smoke(args: object, scenario: object) -> dict[str, object]:
        del args, scenario
        return {
            "image_path": str(image_path),
            "scene_usd": str(scene_usd),
            "loaded_asset_kind": "local_scene_usd",
            "requested_scene_source": "procthor-10k-val",
            "requested_scene_index": 0,
            "requested_molmospaces_scene_usd": "molmospaces://procthor-10k-val/scene-0.usd",
            "isaac_lab_version": "unit-isaaclab",
            "isaac_sim_version": "unit-isaacsim",
            "renderer_mode": "isaac_lab_headless_rtx",
            "capture_method": "isaac_lab_camera_rgb",
            "robot_view_capture_method": "isaac_lab_camera_rgb_static_robot_views",
            "robot_view_images": robot_view_images,
            "camera_resolution": [540, 360],
            "stage_prim_count": 6,
            "render_steps": 4,
            "scene_index_diagnostics": {
                "schema": "isaac_usd_scene_index_v1",
                "status": "indexed",
                "source": str(scene_usd),
                "stage_prim_count": 6,
                "object_candidate_count": 1,
                "receptacle_candidate_count": 1,
                "blockers": [],
            },
            "object_index": _unit_isaac_object_index(),
            "receptacle_index": _unit_isaac_receptacle_index(),
        }

    def fake_capture_semantic_pose_robot_views(**kwargs: object) -> dict[str, object]:
        assert kwargs["render_settle_frames"] == 16
        view_paths = kwargs["view_paths"]
        assert isinstance(view_paths, dict)
        for path in view_paths.values():
            _write_nonblank_image(path)
        return {
            "robot_view_images": {key: str(path) for key, path in view_paths.items()},
            "render_steps": 80,
            "render_settle_frames": 16,
            "robot_view_uses_mounted_head_camera": True,
            "semantic_pose_stage_application": {
                "schema": "isaac_semantic_pose_stage_application_v1",
                "status": "applied",
                "applied_object_count": 1,
                "failed_object_count": 0,
                "rendered_to_usd": True,
            },
            "camera_diagnostics": {
                "schema": "isaac_robot_view_camera_diagnostics_v1",
                "render_settle_frames": 16,
                "native_render_diagnostics": {
                    "schema": "isaac_native_render_diagnostics_v1",
                    "status": "captured",
                    "capture_quality_settings": {
                        "schema": "isaac_capture_quality_settings_v1",
                        "render_settle_frames": 16,
                        "anti_aliasing": {"status": "not_available", "value": None},
                        "denoise": {"status": "not_available", "value": None},
                        "taa": {"status": "not_available", "value": None},
                        "samples_per_pixel": {"status": "not_available", "value": None},
                        "texture_filtering": {"status": "not_available", "value": None},
                    },
                },
            },
            "native_render_diagnostics": {
                "schema": "isaac_native_render_diagnostics_v1",
                "status": "captured",
                "default_render_settings_changed": False,
                "capture_quality_settings": {
                    "schema": "isaac_capture_quality_settings_v1",
                    "render_settle_frames": 16,
                    "anti_aliasing": {"status": "not_available", "value": None},
                    "denoise": {"status": "not_available", "value": None},
                    "taa": {"status": "not_available", "value": None},
                    "samples_per_pixel": {"status": "not_available", "value": None},
                    "texture_filtering": {"status": "not_available", "value": None},
                },
            },
        }

    monkeypatch.setattr(isaac_lab_backend_worker, "real_runtime_smoke", fake_real_runtime_smoke)
    monkeypatch.setattr(
        isaac_lab_backend_worker,
        "capture_semantic_pose_robot_views",
        fake_capture_semantic_pose_robot_views,
    )
    isaac_lab_backend_worker.init_state(
        isaac_lab_backend_worker.parse_args(
            [
                "--state-path",
                str(state_path),
                "init",
                "--run-dir",
                str(run_dir),
                "--runtime-mode",
                "real",
                "--include-robot",
                "--scene-usd-path",
                str(scene_usd),
            ]
        )
    )
    result = isaac_lab_backend_worker.write_robot_views(
        isaac_lab_backend_worker.parse_args(
            [
                "--state-path",
                str(state_path),
                "robot_views",
                "--output-dir",
                str(run_dir / "robot_views"),
                "--label",
                "0001_settle",
                "--render-width",
                "64",
                "--render-height",
                "48",
                "--render-settle-frames",
                "16",
            ]
        ),
        isaac_lab_backend_worker.read_state(state_path),
    )

    assert result["ok"] is True
    assert result["render_settle_frames"] == 16
    assert result["camera_diagnostics"]["render_settle_frames"] == 16
    assert (
        result["native_render_diagnostics"]["capture_quality_settings"]["render_settle_frames"]
        == 16
    )
    state = isaac_lab_backend_worker.read_state(state_path)
    assert state["semantic_pose_view_capture"]["render_settle_frames"] == 16
    assert (
        state["native_render_diagnostics"]["capture_quality_settings"]["render_settle_frames"] == 16
    )


def test_isaac_chase_pose_uses_robot_relative_camera_follower() -> None:
    pose = {
        "x": 3.008962,
        "y": 4.828715,
        "z": 0.0,
        "theta": math.radians(105.0),
    }

    eye, target = isaac_lab_backend_worker._robot_relative_chase_eye_target(pose)

    assert eye == pytest.approx((3.267781, 3.862789, 2.556), abs=1e-6)
    assert target == pytest.approx((3.008962, 4.828715, 1.556), abs=1e-6)


def test_isaac_camera_view_poses_prefers_robot_relative_chase() -> None:
    class _TinyTorch:
        float32 = "float32"

        @staticmethod
        def tensor(values, *, dtype, device):
            return values

    poses = isaac_lab_backend_worker._isaac_camera_view_poses(
        torch=_TinyTorch,
        device="cpu",
        scene_bounds={
            "center": [4.941462, 4.92055, 0.55],
            "size": [10.0, 10.0, 2.0],
            "min": [0.0, 0.0, -0.101716],
            "max": [10.0, 10.0, 1.5],
        },
        semantic_pose_state={
            "robot_pose": {
                "x": 3.008962,
                "y": 4.828715,
                "z": 0.0,
                "yaw_deg": 105.0,
            }
        },
    )

    chase_eye, chase_target = poses["chase"]
    assert chase_eye[0] == pytest.approx([3.267781, 3.862789, 2.556], abs=1e-6)
    assert chase_target[0] == pytest.approx([3.008962, 4.828715, 1.556], abs=1e-6)


def test_isaac_lab_real_worker_views_fallback_when_semantic_pose_rerender_fails(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    run_dir = tmp_path / "run"
    state_path = tmp_path / "state.json"
    image_path = run_dir / "isaac_runtime_smoke.png"
    robot_view_images = _write_robot_view_images(run_dir)
    scene_usd = run_dir / "scene.usda"
    scene_usd.parent.mkdir(parents=True, exist_ok=True)
    scene_usd.write_text("#usda 1.0\n", encoding="utf-8")
    _write_nonblank_image(image_path)

    def fake_real_runtime_smoke(
        args: object,
        scenario: object,
    ) -> dict[str, object]:
        del args, scenario
        return {
            "image_path": str(image_path),
            "scene_usd": str(scene_usd),
            "loaded_asset_kind": "local_scene_usd",
            "requested_scene_source": "procthor-10k-val",
            "requested_scene_index": 0,
            "requested_molmospaces_scene_usd": "molmospaces://procthor-10k-val/scene-0.usd",
            "isaac_lab_version": "unit-isaaclab",
            "isaac_sim_version": "unit-isaacsim",
            "renderer_mode": "isaac_lab_headless_rtx",
            "capture_method": "isaac_lab_camera_rgb",
            "robot_view_capture_method": "isaac_lab_camera_rgb_static_robot_views",
            "robot_view_images": robot_view_images,
            "camera_resolution": [540, 360],
            "stage_prim_count": 6,
            "render_steps": 4,
            "scene_index_diagnostics": {
                "schema": "isaac_usd_scene_index_v1",
                "status": "indexed",
                "source": str(scene_usd),
                "stage_prim_count": 6,
                "object_candidate_count": 1,
                "receptacle_candidate_count": 1,
                "blockers": [],
            },
            "object_index": _unit_isaac_object_index(),
            "receptacle_index": _unit_isaac_receptacle_index(),
        }

    def fail_capture_semantic_pose_robot_views(**_: object) -> dict[str, object]:
        raise RuntimeError("unit rerender failure")

    monkeypatch.setattr(
        isaac_lab_backend_worker,
        "real_runtime_smoke",
        fake_real_runtime_smoke,
    )
    monkeypatch.setattr(
        isaac_lab_backend_worker,
        "capture_semantic_pose_robot_views",
        fail_capture_semantic_pose_robot_views,
    )
    init_args = isaac_lab_backend_worker.parse_args(
        [
            "--state-path",
            str(state_path),
            "init",
            "--run-dir",
            str(run_dir),
            "--runtime-mode",
            "real",
            "--include-robot",
            "--scene-usd-path",
            str(scene_usd),
        ]
    )
    isaac_lab_backend_worker.init_state(init_args)
    result = isaac_lab_backend_worker.write_robot_views(
        isaac_lab_backend_worker.parse_args(
            [
                "--state-path",
                str(state_path),
                "robot_views",
                "--output-dir",
                str(run_dir / "robot_views"),
                "--label",
                "0001_semantic_pose",
                "--render-width",
                "64",
                "--render-height",
                "48",
            ]
        ),
        isaac_lab_backend_worker.read_state(state_path),
    )

    assert result["ok"] is True
    assert result["view_provenance"]["semantic_pose_state_refreshed"] is False
    assert "isaac_lab_camera_rgb_static_robot_views" in json.dumps(result["view_provenance"])
    state = isaac_lab_backend_worker.read_state(state_path)
    assert state["semantic_pose_state"]["rendered_to_usd"] is False
    assert any(
        item["area"] == "semantic_pose_robot_view_rerender"
        and item["status"] == "blocked_capability"
        and "unit rerender failure" in item["detail"]
        for item in state["mapping_gaps"]
    )


def test_isaac_lab_real_worker_views_do_not_claim_refresh_without_usd_pose_application(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    run_dir = tmp_path / "run"
    state_path = tmp_path / "state.json"
    image_path = run_dir / "isaac_runtime_smoke.png"
    robot_view_images = _write_robot_view_images(run_dir)
    scene_usd = run_dir / "scene.usda"
    scene_usd.parent.mkdir(parents=True, exist_ok=True)
    scene_usd.write_text("#usda 1.0\n", encoding="utf-8")
    _write_nonblank_image(image_path)

    def fake_real_runtime_smoke(args: object, scenario: object) -> dict[str, object]:
        del args, scenario
        return {
            "image_path": str(image_path),
            "scene_usd": str(scene_usd),
            "loaded_asset_kind": "local_scene_usd",
            "requested_scene_source": "procthor-10k-val",
            "requested_scene_index": 0,
            "requested_molmospaces_scene_usd": "molmospaces://procthor-10k-val/scene-0.usd",
            "isaac_lab_version": "unit-isaaclab",
            "isaac_sim_version": "unit-isaacsim",
            "renderer_mode": "isaac_lab_headless_rtx",
            "capture_method": "isaac_lab_camera_rgb",
            "robot_view_capture_method": "isaac_lab_camera_rgb_static_robot_views",
            "robot_view_images": robot_view_images,
            "camera_resolution": [540, 360],
            "stage_prim_count": 6,
            "render_steps": 4,
            "scene_index_diagnostics": {
                "schema": "isaac_usd_scene_index_v1",
                "status": "indexed",
                "source": str(scene_usd),
                "stage_prim_count": 6,
                "object_candidate_count": 1,
                "receptacle_candidate_count": 1,
                "blockers": [],
            },
            "object_index": _unit_isaac_object_index(),
            "receptacle_index": _unit_isaac_receptacle_index(),
        }

    def fake_capture_semantic_pose_robot_views(
        *,
        state: dict[str, object],
        scene_usd: Path,
        view_paths: dict[str, Path],
        width: int,
        height: int,
        focus_object_id: str | None = None,
        focus_receptacle_id: str | None = None,
    ) -> dict[str, object]:
        del state, scene_usd, width, height, focus_object_id, focus_receptacle_id
        for path in view_paths.values():
            _write_nonblank_image(path)
        return {
            "robot_view_images": {key: str(path) for key, path in view_paths.items()},
            "render_steps": 7,
            "robot_view_uses_mounted_head_camera": False,
            "semantic_pose_stage_application": {
                "schema": "isaac_semantic_pose_stage_application_v1",
                "status": "blocked",
                "applied_object_count": 0,
                "failed_object_count": 1,
                "rendered_to_usd": False,
                "failed_objects": [{"object_id": "mug_01", "reason": "missing_object_prim"}],
            },
        }

    monkeypatch.setattr(isaac_lab_backend_worker, "real_runtime_smoke", fake_real_runtime_smoke)
    monkeypatch.setattr(
        isaac_lab_backend_worker,
        "capture_semantic_pose_robot_views",
        fake_capture_semantic_pose_robot_views,
    )
    isaac_lab_backend_worker.init_state(
        isaac_lab_backend_worker.parse_args(
            [
                "--state-path",
                str(state_path),
                "init",
                "--run-dir",
                str(run_dir),
                "--runtime-mode",
                "real",
                "--include-robot",
                "--scene-usd-path",
                str(scene_usd),
            ]
        )
    )

    result = isaac_lab_backend_worker.write_robot_views(
        isaac_lab_backend_worker.parse_args(
            [
                "--state-path",
                str(state_path),
                "robot_views",
                "--output-dir",
                str(run_dir / "robot_views"),
                "--label",
                "0001_semantic_pose",
                "--render-width",
                "64",
                "--render-height",
                "48",
            ]
        ),
        isaac_lab_backend_worker.read_state(state_path),
    )

    assert result["ok"] is True
    assert result["view_provenance"]["semantic_pose_state_refreshed"] is False
    assert "isaac_lab_camera_rgb_static_robot_views" in json.dumps(result["view_provenance"])
    state = isaac_lab_backend_worker.read_state(state_path)
    assert state["semantic_pose_state"]["rendered_to_usd"] is False
    assert any(
        item["area"] == "semantic_pose_robot_view_rerender"
        and item["status"] == "blocked_capability"
        and item["semantic_pose_stage_application"]["rendered_to_usd"] is False
        for item in state["mapping_gaps"]
    )


def test_isaac_lab_real_worker_snapshot_reuses_real_smoke_image(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    run_dir = tmp_path / "run"
    state_path = tmp_path / "state.json"
    image_path = run_dir / "isaac_runtime_smoke.png"
    _write_nonblank_image(image_path)

    def fake_real_runtime_smoke(
        args: object,
        scenario: object,
    ) -> dict[str, object]:
        del args, scenario
        return {
            "image_path": str(image_path),
            "scene_usd": str(run_dir / "scene.usda"),
            "loaded_asset_kind": "generated_runtime_smoke_usd",
            "requested_scene_source": "procthor-10k-val",
            "requested_scene_index": 0,
            "requested_molmospaces_scene_usd": "molmospaces://procthor-10k-val/scene-0.usd",
            "isaac_lab_version": "unit-isaaclab",
            "isaac_sim_version": "unit-isaacsim",
            "renderer_mode": "isaac_lab_headless_rtx",
            "capture_method": "isaac_lab_camera_rgb",
            "camera_resolution": [540, 360],
            "stage_prim_count": 6,
            "render_steps": 4,
            "scene_index_diagnostics": {
                "schema": "isaac_usd_scene_index_v1",
                "status": "indexed",
                "source": str(run_dir / "scene.usda"),
                "stage_prim_count": 6,
                "object_candidate_count": 1,
                "receptacle_candidate_count": 1,
                "blockers": [],
            },
            "object_index": _unit_isaac_object_index(),
            "receptacle_index": _unit_isaac_receptacle_index(),
        }

    monkeypatch.setattr(
        isaac_lab_backend_worker,
        "real_runtime_smoke",
        fake_real_runtime_smoke,
    )
    init_args = isaac_lab_backend_worker.parse_args(
        [
            "--state-path",
            str(state_path),
            "init",
            "--run-dir",
            str(run_dir),
            "--runtime-mode",
            "real",
        ]
    )
    isaac_lab_backend_worker.init_state(init_args)
    snapshot_path = run_dir / "before.png"
    snapshot_args = isaac_lab_backend_worker.parse_args(
        [
            "--state-path",
            str(state_path),
            "snapshot",
            "--output-path",
            str(snapshot_path),
            "--title",
            "Before cleanup",
            "--render-width",
            "64",
            "--render-height",
            "48",
        ]
    )
    result = isaac_lab_backend_worker.write_snapshot(
        snapshot_args,
        isaac_lab_backend_worker.read_state(state_path),
    )

    assert result["ok"] is True
    assert result["placeholder_visuals"] is False
    assert result["visual_artifact_provenance"] == "isaac_lab_camera_rgb"
    assert result["snapshot_provenance"]["source_path"] == str(image_path)
    assert result["snapshot_provenance"]["static_isaac_capture"] is True
    assert result["snapshot_provenance"]["semantic_pose_rendered"] is False
    with Image.open(snapshot_path) as image:
        assert image.size == (64, 48)


def test_isaac_lab_real_init_fails_without_renderer_proof(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    state_path = tmp_path / "state.json"

    def fail_real_runtime_smoke(
        args: object,
        scenario: object,
    ) -> dict[str, object]:
        del args, scenario
        raise RuntimeError("camera capture failed")

    monkeypatch.setattr(
        isaac_lab_backend_worker,
        "real_runtime_smoke",
        fail_real_runtime_smoke,
    )
    args = isaac_lab_backend_worker.parse_args(
        [
            "--state-path",
            str(state_path),
            "init",
            "--run-dir",
            str(tmp_path / "run"),
            "--runtime-mode",
            "real",
        ]
    )

    with pytest.raises(RuntimeError, match="Real Isaac runtime smoke failed"):
        isaac_lab_backend_worker.init_state(args)
    assert state_path.exists() is False


def test_isaac_lab_real_init_does_not_persist_missing_smoke_image(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    state_path = tmp_path / "state.json"
    missing_image = tmp_path / "run" / "missing.png"

    def missing_image_real_runtime_smoke(
        args: object,
        scenario: object,
    ) -> dict[str, object]:
        del args, scenario
        return {
            "image_path": str(missing_image),
            "scene_usd": str(tmp_path / "run" / "scene.usda"),
            "loaded_asset_kind": "generated_runtime_smoke_usd",
            "requested_scene_source": "procthor-10k-val",
            "requested_scene_index": 0,
            "renderer_mode": "isaac_lab_headless_rtx",
            "capture_method": "isaac_lab_camera_rgb",
            "camera_resolution": [540, 360],
            "stage_prim_count": 6,
            "render_steps": 3,
        }

    monkeypatch.setattr(
        isaac_lab_backend_worker,
        "real_runtime_smoke",
        missing_image_real_runtime_smoke,
    )
    args = isaac_lab_backend_worker.parse_args(
        [
            "--state-path",
            str(state_path),
            "init",
            "--run-dir",
            str(tmp_path / "run"),
            "--runtime-mode",
            "real",
        ]
    )

    with pytest.raises(RuntimeError, match="real Isaac smoke image is missing"):
        isaac_lab_backend_worker.init_state(args)
    assert state_path.exists() is False


def _write_nonblank_image(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    image = Image.new("RGB", (64, 48), color=(18, 32, 48))
    draw = ImageDraw.Draw(image)
    draw.rectangle((8, 8, 56, 40), outline=(240, 180, 60), width=3)
    image.save(path)


def _write_robot_view_images(run_dir: Path) -> dict[str, str]:
    paths = {
        "fpv": run_dir / "isaac_runtime_smoke.png",
        "chase": run_dir / "isaac_runtime_smoke.chase.png",
        "topdown": run_dir / "isaac_runtime_smoke.topdown.png",
        "verify": run_dir / "isaac_runtime_smoke.verify.png",
    }
    for index, path in enumerate(paths.values(), start=1):
        path.parent.mkdir(parents=True, exist_ok=True)
        image = Image.new("RGB", (64, 48), color=(18 + index, 32, 48))
        draw = ImageDraw.Draw(image)
        draw.rectangle((8, 8, 56, 40), outline=(240, 180 - index, 60), width=3)
        image.save(path)
    return {key: str(path) for key, path in paths.items()}


def _unit_isaac_object_index() -> dict[str, dict[str, object]]:
    return {
        "mug_01": {
            "usd_prim_path": "/World/Objects/mug_01",
            "category": "mug01",
            "public_label": "mug_01",
            "index_source": "usd_stage_traversal",
            "usd_world_bounds": {
                "center": [4.0, 5.0, 0.4],
                "min": [3.8, 4.8, 0.0],
                "max": [4.2, 5.2, 0.8],
                "size": [0.4, 0.4, 0.8],
            },
        }
    }


def _unit_isaac_receptacle_index() -> dict[str, dict[str, object]]:
    return {
        "sink_01": {
            "usd_prim_path": "/World/Receptacles/sink_01",
            "category": "sink01",
            "public_label": "sink_01",
            "index_source": "usd_stage_traversal",
            "usd_world_bounds": {
                "center": [2.5, 5.5, 0.75],
                "max": [3.0, 6.0, 1.2],
                "size": [1.0, 1.0, 0.9],
            },
            "support_pose": {
                "frame": "usd_world",
                "x": 2.5,
                "y": 5.5,
                "z": 1.2,
                "source": "usd_world_bounds_top_center",
                "support_radius_m": 0.5,
            },
        }
    }
