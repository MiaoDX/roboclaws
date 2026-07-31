from __future__ import annotations

import json
import math
import sys
from pathlib import Path

import pytest

from roboclaws.backends.isaaclab import runtime as runtime_cli
from roboclaws.backends.isaaclab import runtime_camera as runtime_camera
from roboclaws.backends.isaaclab import runtime_capture as runtime_capture
from roboclaws.backends.isaaclab import runtime_commands as runtime_commands
from roboclaws.backends.isaaclab import runtime_dependencies as runtime_dependencies
from roboclaws.backends.isaaclab import runtime_evidence as runtime_evidence
from roboclaws.backends.isaaclab import runtime_initialization as runtime_initialization
from roboclaws.backends.isaaclab import runtime_state as runtime_state
from roboclaws.household.isaac_lab_backend import (
    ISAAC_SEMANTIC_POSE_STATE_SCHEMA,
    ISAACLAB_SUBPROCESS_BACKEND,
    IsaacLabSubprocessBackend,
)
from roboclaws.household.manipulation_contract import ISAAC_SEMANTIC_POSE_PROVENANCE
from tests.unit.molmo_cleanup.isaac_lab_backend_semantic_pose_support import (
    _assert_semantic_pose_recapture_result,
    _assert_semantic_pose_recapture_state,
    _init_real_worker_with_scene_usd,
    _navigate_real_worker_to_receptacle,
    _patch_semantic_pose_recapture_captures,
    _setup_semantic_pose_recapture_runtime,
    _write_semantic_pose_robot_views,
)
from tests.unit.molmo_cleanup.isaac_lab_backend_support import (
    _assert_fake_isaac_action_results,
    _assert_fake_isaac_mess_diagnostics,
    _assert_fake_isaac_robot_import,
    _assert_fake_isaac_robot_views,
    _assert_fake_isaac_runtime_metadata,
    _assert_fake_isaac_scene_bindings,
    _assert_fake_isaac_scene_index_payload,
    _assert_fake_isaac_semantic_pose_state,
    _assert_fake_isaac_snapshot,
    _exercise_fake_isaac_semantic_pose_actions,
    _fake_isaac_backend,
    _write_b1_scene_gs_fixture,
    _write_nonblank_image,
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


def test_isaac_worker_read_state_preserves_state_path(tmp_path: Path) -> None:
    state_path = tmp_path / "state.json"
    state = {"schema": "isaac_lab_backend_state_v1", "scenario": {"objects": []}}
    state_path.write_text(json.dumps(state), encoding="utf-8")

    loaded = runtime_commands.read_state(state_path)

    assert loaded["schema"] == "isaac_lab_backend_state_v1"
    assert loaded["_state_path"] == str(state_path)


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
        runtime_state,
        "ISAAC_RBY1M_ROBOT_USD_PATH",
        robot_usd,
    )
    monkeypatch.setattr(
        runtime_dependencies,
        "ISAAC_RBY1M_ROBOT_IMPORT_SUMMARY_PATH",
        summary_path,
    )
    monkeypatch.setattr(
        runtime_state,
        "_find_rby1m_isaac_urdf",
        lambda: tmp_path / "model_holobase_isaac.urdf",
    )
    monkeypatch.setattr(runtime_state, "_repo_path", lambda path: path)

    plan = runtime_state._rby1m_robot_import_plan("rby1m")
    robot = runtime_commands._robot_payload("rby1m")

    assert plan["status"] == "imported"
    assert plan["usd_path"] == str(robot_usd)
    assert plan["head_camera_mounted"] is True
    assert plan["head_camera_equivalent"] is False
    assert plan["blockers"] == []
    assert robot["embodiment"] == "rby1m"
    assert robot["robot_mounted_head_camera"] is True
    assert robot["robot_usd_path"] == str(robot_usd)


def test_isaac_robot_import_resolves_repo_relative_artifacts() -> None:
    relative_path = Path("output/isaaclab/robots/rby1m/robot.usda")

    assert runtime_state._repo_path(relative_path) == Path.cwd() / relative_path


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


def test_isaac_worker_can_request_semantic_filter_override(tmp_path: Path) -> None:
    args = runtime_cli.parse_args(
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


def test_isaac_worker_robot_views_apply_pitch_offset_to_head_camera_pose(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    context = _setup_semantic_pose_recapture_runtime(monkeypatch, tmp_path)
    captured_state: dict[str, object] = {}

    def fake_capture_semantic_pose_robot_views(
        *,
        state: dict[str, object],
        scene_usd: Path,
        view_paths: dict[str, Path],
        width: int,
        height: int,
        **_: object,
    ) -> dict[str, object]:
        del scene_usd, width, height
        captured_state.update(state)
        for path in view_paths.values():
            _write_nonblank_image(path)
        return {
            "robot_view_images": {key: str(path) for key, path in view_paths.items()},
            "render_steps": 7,
            "robot_view_uses_mounted_head_camera": True,
            "semantic_pose_stage_application": {
                "schema": "isaac_semantic_pose_stage_application_v1",
                "status": "applied",
                "applied_object_count": 0,
                "failed_object_count": 0,
                "rendered_to_usd": True,
            },
            "robot_pose_stage_application": {
                "schema": "isaac_robot_head_camera_pose_application_v1",
                "status": "applied",
                "head_pitch": math.radians(-10.0),
                "head_pitch_applied": True,
            },
            "camera_diagnostics": {
                "schema": "isaac_robot_view_camera_diagnostics_v1",
                "views": {},
            },
        }

    monkeypatch.setattr(
        runtime_capture,
        "capture_semantic_pose_robot_views",
        fake_capture_semantic_pose_robot_views,
    )
    _init_real_worker_with_scene_usd(context)

    result = runtime_commands.write_robot_views(
        runtime_cli.parse_args(
            [
                "--state-path",
                str(context.state_path),
                "robot_views",
                "--output-dir",
                str(context.run_dir / "robot_views"),
                "--label",
                "0001_adjusted",
                "--camera-pitch-offset-deg",
                "-10.0",
            ]
        ),
        runtime_commands.read_state(context.state_path),
    )

    assert result["ok"] is True
    robot_pose = captured_state["semantic_pose_state"]["robot_pose"]  # type: ignore[index]
    assert robot_pose["head_pitch"] == pytest.approx(math.radians(-10.0))
    assert robot_pose["head_pitch_source"] == "camera_pitch_offset_deg"
    assert robot_pose["camera_adjustment"]["pitch_applied_to_static_head_camera"] is True


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
    runtime_commands.write_state(state_path, state)

    args = runtime_cli.parse_args(
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

    result = runtime_commands.navigate_to_waypoint(
        args,
        runtime_commands.read_state(state_path),
    )
    updated = runtime_commands.read_state(state_path)

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
    runtime_commands.write_state(state_path, state)

    args = runtime_cli.parse_args(
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

    result = runtime_commands.navigate_to_relative_pose(
        args,
        runtime_commands.read_state(state_path),
    )
    updated = runtime_commands.read_state(state_path)

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


def test_isaac_worker_infers_scene_index_from_local_val_path() -> None:
    args = runtime_cli.parse_args(
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

    assert runtime_commands._effective_scene_index(args) == 12


def test_isaac_worker_infers_scene_index_from_prepared_val_path() -> None:
    args = runtime_cli.parse_args(
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

    assert runtime_commands._effective_scene_index(args) == 1


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
    state = runtime_commands.read_state(context.state_path)
    _assert_semantic_pose_recapture_state(state)
