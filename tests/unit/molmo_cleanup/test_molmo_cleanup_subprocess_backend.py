from __future__ import annotations

import importlib.util
import json
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pytest

from roboclaws.household import worker_runner
from roboclaws.household.camera_control import scene_light_rig
from roboclaws.household.generated_mess import (
    build_generated_mess_manifest,
    generated_mess_success_threshold,
    select_generated_mess_targets,
    targets_from_generated_mess_manifest,
)
from roboclaws.household.robot_view_camera_control import (
    canonical_cleanup_robot_view_camera_request,
)
from roboclaws.household.subprocess_backend import (
    MOLMOSPACES_SUBPROCESS_BACKEND,
    MolmoSpacesSubprocessBackend,
    _parse_last_json_object,
    _parse_persistent_worker_packet,
    _worker_kwargs_from_args,
)


def _repo_root() -> Path:
    for parent in Path(__file__).resolve().parents:
        if (parent / "justfile").is_file():
            return parent
    raise AssertionError("could not locate repo root")


REPO_ROOT = _repo_root()
WORKER_PATH = REPO_ROOT / "scripts" / "molmo_cleanup" / "molmospaces_subprocess_worker.py"


def _load_worker_module():
    pytest.importorskip("mujoco")
    spec = importlib.util.spec_from_file_location("molmospaces_subprocess_worker", WORKER_PATH)
    assert spec is not None
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def test_parse_last_json_object_tolerates_upstream_stdout_noise() -> None:
    payload = _parse_last_json_object(
        "Using SCENES_ROOT: /tmp/assets\n"
        + json.dumps({"ok": True, "tool": "init", "backend": MOLMOSPACES_SUBPROCESS_BACKEND})
        + "\n"
    )

    assert payload["backend"] == MOLMOSPACES_SUBPROCESS_BACKEND


def test_persistent_worker_packet_reports_malformed_json_source() -> None:
    with pytest.raises(
        ValueError,
        match=(
            "MolmoSpaces persistent worker returned invalid packet for serve: "
            "MolmoSpaces persistent worker stdout row source must contain valid JSON object: "
            "serve response"
        ),
    ):
        _parse_persistent_worker_packet("{bad json", command="serve")


def test_persistent_worker_packet_rejects_non_object_json() -> None:
    with pytest.raises(
        ValueError,
        match=(
            "MolmoSpaces persistent worker returned invalid packet for locations: "
            "MolmoSpaces persistent worker stdout row source must contain a JSON object: "
            "locations response"
        ),
    ):
        _parse_persistent_worker_packet('["not", "a", "packet"]', command="locations")


def test_subprocess_backend_reports_missing_runtime(tmp_path: Path) -> None:
    with pytest.raises(RuntimeError, match="Python runtime is missing"):
        MolmoSpacesSubprocessBackend(
            run_dir=tmp_path,
            python_executable=tmp_path / "missing-python",
        )


def test_subprocess_backend_worker_defaults_to_egl_for_mujoco(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    fake_python = tmp_path / "python"
    fake_python.write_text("", encoding="utf-8")
    backend = MolmoSpacesSubprocessBackend.__new__(MolmoSpacesSubprocessBackend)
    backend.state_path = tmp_path / "state.json"
    backend.python_executable = fake_python
    captured: dict[str, object] = {}

    def fake_run(command, **kwargs):
        captured["command"] = command
        captured["env"] = kwargs["env"]
        captured["timeout"] = kwargs["timeout"]
        return SimpleNamespace(
            returncode=0, stdout='{"ok": true, "tool": "locations"}\n', stderr=""
        )

    monkeypatch.delenv("MUJOCO_GL", raising=False)
    monkeypatch.setattr(worker_runner.subprocess, "run", fake_run)

    result = backend._run_worker("locations")

    assert result["ok"] is True
    assert captured["env"]["MUJOCO_GL"] == "egl"
    assert captured["timeout"] == 120.0


def test_subprocess_backend_worker_times_out_hung_snapshot(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    fake_python = tmp_path / "python"
    fake_python.write_text("", encoding="utf-8")
    backend = MolmoSpacesSubprocessBackend.__new__(MolmoSpacesSubprocessBackend)
    backend.state_path = tmp_path / "state.json"
    backend.python_executable = fake_python
    captured: dict[str, object] = {}

    def fake_run(command, **kwargs):
        captured["timeout"] = kwargs["timeout"]
        raise worker_runner.subprocess.TimeoutExpired(command, kwargs["timeout"])

    monkeypatch.setattr(worker_runner.subprocess, "run", fake_run)

    with pytest.raises(RuntimeError, match="worker timed out"):
        backend._run_worker("snapshot", "--output-path", str(tmp_path / "before.png"))

    assert captured["timeout"] == 60.0


def test_subprocess_backend_worker_payload_parses_cli_style_args() -> None:
    payload = _worker_kwargs_from_args(
        "robot_views",
        (
            "--output-dir",
            "/tmp/views",
            "--label",
            "0001_pick",
            "--focus-object-id",
            "Apple_1",
            "--focus-receptacle-id",
            "Fridge_1",
            "--camera-yaw-offset-deg",
            "12.5",
            "--camera-pitch-offset-deg",
            "-7.0",
        ),
    )

    assert payload == {
        "output_dir": "/tmp/views",
        "label": "0001_pick",
        "focus_object_id": "Apple_1",
        "focus_receptacle_id": "Fridge_1",
        "camera_yaw_offset_deg": "12.5",
        "camera_pitch_offset_deg": "-7.0",
    }


def test_subprocess_backend_navigate_to_waypoint_passes_full_waypoint_json(
    tmp_path: Path,
) -> None:
    fake_python = tmp_path / "python"
    fake_python.write_text("", encoding="utf-8")
    backend = MolmoSpacesSubprocessBackend.__new__(MolmoSpacesSubprocessBackend)
    backend.state_path = tmp_path / "state.json"
    backend.python_executable = fake_python
    captured: dict[str, object] = {}

    def fake_run_worker(command: str, *args: str) -> dict[str, object]:
        captured["command"] = command
        captured["args"] = args
        return {"ok": True, "tool": command}

    backend._run_worker = fake_run_worker
    waypoint = {
        "waypoint_id": "wp_1",
        "room_id": "room_2",
        "x": 4.0,
        "y": 7.0,
        "source_room_bounds": {"min_x": 1.0, "max_x": 7.0, "min_y": 2.0, "max_y": 8.0},
    }

    result = backend.navigate_to_waypoint(waypoint=waypoint)

    assert result["ok"] is True
    assert captured["command"] == "navigate_to_waypoint"
    args = captured["args"]
    assert args[0] == "--waypoint-json"
    assert json.loads(args[1]) == waypoint


def test_worker_frame_comparison_object_uses_object_target_pose(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    worker = _load_worker_module()
    state_path = tmp_path / "state.json"
    state_path.write_text(
        json.dumps(
            {
                "robot_included": True,
                "qpos": [0.0, 0.0, 0.0],
                "objects": {
                    "box_1": {
                        "object_id": "box_1",
                        "body_name": "box_1",
                        "category": "Box",
                        "position": [1.0, 2.0, 0.8],
                    }
                },
                "receptacles": {},
                "robot_trajectory": [],
            }
        ),
        encoding="utf-8",
    )
    sentinel_model = object()
    sentinel_data = SimpleNamespace(qpos=[0.0, 0.0, 0.0])

    monkeypatch.setattr(
        worker, "_load_model_data_for_state", lambda state: (sentinel_model, sentinel_data)
    )
    monkeypatch.setattr(worker, "_apply_qpos", lambda data, qpos: None)
    monkeypatch.setattr(worker.mujoco, "mj_forward", lambda model, data: None)
    monkeypatch.setattr(worker, "_refresh_object_positions", lambda model, data, state: None)

    def fake_robot_pose_near_object(state, obj, *, source_receptacle_id=None):
        assert source_receptacle_id is None
        assert obj["object_id"] == "box_1"
        return {
            "x": 0.5,
            "y": 1.5,
            "theta": 0.25,
            "target_object_id": "box_1",
            "target_position": obj["position"],
            "pose_request": {
                "target_object_id": "box_1",
                "target_position": obj["position"],
            },
        }

    monkeypatch.setattr(worker, "_robot_pose_near_object", fake_robot_pose_near_object)
    monkeypatch.setattr(worker, "_set_robot_pose", lambda model, data, pose: None)

    result = worker.run_state_command(
        state_path,
        "frame_comparison_object",
        {"object_id": "box_1"},
    )

    state = json.loads(state_path.read_text(encoding="utf-8"))
    assert result["ok"] is True
    assert result["tool"] == "frame_comparison_object"
    assert result["robot_pose"]["target_object_id"] == "box_1"
    assert result["robot_pose"]["pose_source"] == "roboclaws_comparison_object_pose"
    assert state["robot_pose"]["target_object_id"] == "box_1"
    assert state["robot_trajectory"][-1]["target_object_id"] == "box_1"


def test_worker_navigate_to_waypoint_projects_bundle_room_to_scene_outline(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    worker = _load_worker_module()
    state_path = tmp_path / "state.json"
    state_path.write_text(
        json.dumps(
            {
                "robot_included": True,
                "robot_name": "rby1m",
                "qpos": [0.0, 0.0, 0.0],
                "objects": {},
                "receptacles": {},
                "room_outlines": [
                    {
                        "room_id": "room_2",
                        "center": [10.0, 20.0],
                        "half_extents": [4.0, 6.0],
                    }
                ],
                "robot_trajectory": [],
                "tool_event_counts": {},
            }
        ),
        encoding="utf-8",
    )
    sentinel_model = object()
    sentinel_data = SimpleNamespace(qpos=[0.0, 0.0, 0.0, 0.0, 0.0])
    applied_poses: list[dict[str, float]] = []

    monkeypatch.setattr(
        worker, "_load_model_data_for_state", lambda state: (sentinel_model, sentinel_data)
    )
    monkeypatch.setattr(worker, "_apply_qpos", lambda data, qpos: None)
    monkeypatch.setattr(worker.mujoco, "mj_forward", lambda model, data: None)
    monkeypatch.setattr(worker, "_refresh_object_positions", lambda model, data, state: None)
    monkeypatch.setattr(worker, "_sync_held_object_to_robot_pose", lambda *_args: None)

    def fake_set_robot_pose(model, data, pose):
        applied_poses.append(pose)
        data.qpos[:] = [pose["x"], pose["y"], pose["theta"], pose["head_pitch"], 1.0]

    monkeypatch.setattr(worker, "_set_robot_pose", fake_set_robot_pose)

    result = worker.run_state_command(
        state_path,
        "navigate_to_waypoint",
        {
            "waypoint_json": json.dumps(
                {
                    "waypoint_id": "wp_2",
                    "room_id": "room_2",
                    "x": 4.0,
                    "y": 5.0,
                    "source_room_bounds": {
                        "min_x": 0.0,
                        "max_x": 8.0,
                        "min_y": 0.0,
                        "max_y": 10.0,
                    },
                }
            )
        },
    )

    state = json.loads(state_path.read_text(encoding="utf-8"))
    assert result["ok"] is True
    assert result["tool"] == "navigate_to_waypoint"
    assert result["state_mutation"] == "robot_base_qpos"
    assert result["qpos_changed"] is True
    assert result["robot_pose"]["pose_source"] == "waypoint_room_outline_projection"
    assert result["robot_pose"]["target_waypoint_id"] == "wp_2"
    assert applied_poses[0]["x"] == pytest.approx(10.0)
    assert applied_poses[0]["y"] == pytest.approx(20.0)
    assert state["current_waypoint_id"] == "wp_2"
    assert state["robot_pose"]["target_waypoint_id"] == "wp_2"
    assert state["robot_trajectory"][-1]["target_waypoint_id"] == "wp_2"
    assert state["qpos"] == pytest.approx(
        [10.0, 20.0, applied_poses[0]["theta"], applied_poses[0]["head_pitch"], 1.0]
    )


def test_worker_model_data_cache_reuses_loaded_scene(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    pytest.importorskip("mujoco")
    worker = _load_worker_module()
    worker._MODEL_DATA_CACHE.clear()
    scene_xml = tmp_path / "scene.xml"
    calls = []
    sentinel = (object(), SimpleNamespace(qpos=[0.0]))

    def fake_load_model_data(path: Path):
        calls.append(path)
        return sentinel

    monkeypatch.setattr(worker, "_load_model_data", fake_load_model_data)
    state = {"scene_xml": str(scene_xml), "robot_included": False}

    assert worker._load_model_data_for_state(state) is sentinel
    assert worker._load_model_data_for_state(state) is sentinel
    assert calls == [scene_xml]


def test_worker_resolves_procthor_scene_from_get_scenes_base_ref(tmp_path: Path) -> None:
    worker = _load_worker_module()
    scenes_root = tmp_path / "scenes"
    scene_xml = scenes_root / "procthor-10k-val" / "val_4.xml"

    def fake_get_scenes(dataset_name: str, split: str):
        assert dataset_name == "procthor-10k"
        assert split == "val"
        return {
            "val": {
                4: {
                    "base": scene_xml,
                    "ceiling": scenes_root / "procthor-10k-val" / "val_4_ceiling.xml",
                    "map": scenes_root / "procthor-10k-val" / "val_4_map.png",
                }
            }
        }

    resolved, resolution = worker._resolve_molmospaces_scene_xml(
        scene_source="procthor-10k-val",
        scene_index=4,
        get_scenes=fake_get_scenes,
        scenes_root=scenes_root,
    )

    assert resolved == scene_xml
    assert resolution["dataset_name"] == "procthor-10k"
    assert resolution["split"] == "val"
    assert resolution["selected_ref_role"] == "base"


def test_worker_resolves_ithor_scene_from_get_scenes_path_ref(tmp_path: Path) -> None:
    worker = _load_worker_module()
    scenes_root = tmp_path / "scenes"

    def fake_get_scenes(dataset_name: str, split: str):
        assert dataset_name == "ithor"
        assert split == "train"
        return {"train": {1: "ithor/FloorPlan1_physics.xml"}}

    resolved, resolution = worker._resolve_molmospaces_scene_xml(
        scene_source="ithor",
        scene_index=1,
        get_scenes=fake_get_scenes,
        scenes_root=scenes_root,
    )

    assert resolved == scenes_root / "ithor" / "FloorPlan1_physics.xml"
    assert "val_1.xml" not in str(resolved)
    assert resolution["selected_ref_role"] == "path"
    assert resolution["path_was_relative"] is True


def test_worker_resolve_scene_reports_missing_get_scenes_index(tmp_path: Path) -> None:
    worker = _load_worker_module()

    with pytest.raises(FileNotFoundError, match="scene index missing"):
        worker._resolve_molmospaces_scene_xml(
            scene_source="holodeck-objaverse-val",
            scene_index=9,
            get_scenes=lambda _dataset, _split: {"val": {0: {"base": "val_0.xml"}}},
            scenes_root=tmp_path,
        )


def test_worker_kwargs_parse_render_resolution_args() -> None:
    kwargs = _worker_kwargs_from_args(
        "robot_views",
        (
            "--output-dir",
            "/tmp/views",
            "--label",
            "focus-01",
            "--render-width",
            "1280",
            "--render-height",
            "720",
        ),
    )

    assert kwargs["render_width"] == "1280"
    assert kwargs["render_height"] == "720"


def test_subprocess_backend_exposes_camera_control_request_api(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake_python = tmp_path / "python"
    fake_python.write_text("", encoding="utf-8")
    backend = MolmoSpacesSubprocessBackend.__new__(MolmoSpacesSubprocessBackend)
    backend.state_path = tmp_path / "state.json"
    backend.python_executable = fake_python
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


def test_molmospaces_worker_normalizes_camera_control_request() -> None:
    pytest.importorskip("mujoco")
    worker = _load_worker_module()
    request = worker.normalize_camera_control_request(
        {
            "camera_orbit": {"distance_m": 4.4, "azimuth_deg": 225.0, "elevation_deg": 28.0},
            "lens": {"vertical_fov_deg": 45.0},
            "views": [
                {
                    "view_id": "view 01/table",
                    "lookat": [2.7, 5.9, 1.0],
                    "camera_model": "anchor_orbit_lookat_camera_v1",
                    "lane_camera_orbits": {
                        "molmospaces-mujoco": {
                            "distance_m": 4.4,
                            "azimuth_deg": 90.0,
                            "elevation_deg": 28.0,
                        }
                    },
                    "calibration_status": "anchor_orbit_relative_calibrated_v1",
                }
            ],
        },
        width=960,
        height=640,
    )

    spec = worker._camera_view_spec(request["views"][0], index=1)

    assert spec["view_id"] == "view_01_table"
    assert spec["camera_model"] == "anchor_orbit_lookat_camera_v1"
    assert spec["calibration_status"] == "anchor_orbit_relative_calibrated_v1"
    assert spec["distance"] == pytest.approx(4.4)
    assert spec["azimuth"] == pytest.approx(90.0)
    assert spec["elevation"] == pytest.approx(-28.0)
    assert spec["lookat"] == pytest.approx([2.7, 5.9, 1.0])
    assert spec["eye"][2] > spec["lookat"][2]
    assert spec["backend_eye"] == pytest.approx(spec["eye"])
    assert spec["backend_target"] == pytest.approx(spec["lookat"])


def test_molmospaces_camera_view_specs_reject_missing_source(tmp_path: Path) -> None:
    worker = _load_worker_module()
    missing = tmp_path / "missing_views.json"

    with pytest.raises(
        FileNotFoundError,
        match=r"camera view spec source is missing: .*missing_views\.json",
    ):
        worker._load_camera_view_specs(missing)


def test_molmospaces_camera_view_specs_reject_malformed_source(tmp_path: Path) -> None:
    worker = _load_worker_module()
    specs_path = tmp_path / "camera_views.json"
    specs_path.write_text("{bad json\n", encoding="utf-8")

    with pytest.raises(
        ValueError,
        match=r"camera view spec source must contain valid JSON: .*camera_views\.json",
    ):
        worker._load_camera_view_specs(specs_path)


def test_molmospaces_camera_view_specs_reject_wrong_shape_source(tmp_path: Path) -> None:
    worker = _load_worker_module()
    specs_path = tmp_path / "camera_views.json"
    specs_path.write_text(json.dumps({"views": {"bad": True}}), encoding="utf-8")

    with pytest.raises(
        ValueError,
        match="camera view spec must be a list or an object with a views list",
    ):
        worker._load_camera_view_specs(specs_path)


def test_molmospaces_camera_view_specs_accept_list_or_wrapped_views(tmp_path: Path) -> None:
    worker = _load_worker_module()
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

    assert worker._load_camera_view_specs(list_path) == [
        {"view_id": "fpv", "target": [0.0, 0.0, 0.0]},
        {"view_id": "map", "target": [1.0, 0.0, 0.0]},
    ]
    assert worker._load_camera_view_specs(wrapped_path) == [
        {"view_id": "verify", "target": [2.0, 0.0, 0.0]}
    ]


def test_molmospaces_worker_converts_canonical_eye_to_mujoco_free_camera_angles() -> None:
    pytest.importorskip("mujoco")
    worker = _load_worker_module()
    requested_eye = [1.9435, 3.23895, 1.45]
    requested_target = [2.99, 4.983, 1.45]

    spec = worker._camera_view_spec(
        {
            "view_id": "room 01/room 2",
            "camera_model": "canonical_eye_target_camera_v1",
            "eye": requested_eye,
            "target": requested_target,
        },
        index=1,
    )

    assert spec["view_id"] == "room_01_room_2"
    assert spec["lookat"] == pytest.approx(requested_target)
    assert spec["eye"] == pytest.approx(requested_eye)
    assert spec["backend_eye"] == pytest.approx(requested_eye)
    assert spec["backend_target"] == pytest.approx(requested_target)
    assert spec["azimuth"] == pytest.approx(59.03455257875734)
    assert spec["elevation"] == pytest.approx(0.0)
    reconstructed_eye = worker._eye_from_mujoco_free_camera(
        lookat=spec["lookat"],
        distance=spec["distance"],
        azimuth=spec["azimuth"],
        elevation=spec["elevation"],
    )
    assert reconstructed_eye == pytest.approx(requested_eye)


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
                "eye": [1.0, True, 3.0],
                "target": [2.7, 5.9, 1.0],
            },
            r"eye\[1\] must be a finite number",
        ),
    ],
)
def test_molmospaces_camera_view_spec_rejects_invalid_explicit_vectors(
    raw_spec: dict[str, object],
    message: str,
) -> None:
    pytest.importorskip("mujoco")
    worker = _load_worker_module()

    with pytest.raises(ValueError, match=message):
        worker._camera_view_spec(raw_spec, index=1)


def test_molmospaces_camera_views_apply_color_profile(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    pytest.importorskip("mujoco")
    worker = _load_worker_module()
    model = SimpleNamespace(vis=SimpleNamespace(global_=SimpleNamespace(fovy=55.0)))
    data = object()
    frame = np.full((4, 6, 3), 250, dtype=np.uint8)

    monkeypatch.setattr(worker, "_camera_from_view_spec", lambda _state, spec: spec)
    monkeypatch.setattr(worker, "_render_free_camera", lambda *_args, **_kwargs: frame.copy())

    result = worker._render_camera_views_with_model_data(
        model,
        data,
        state={},
        output_dir=tmp_path,
        camera_request={
            "camera_model": "canonical_eye_target_camera_v1",
            "views": [
                {
                    "view_id": "fpv",
                    "eye": [0.0, 0.0, 1.0],
                    "target": [1.0, 0.0, 1.0],
                }
            ],
        },
        width=6,
        height=4,
    )

    assert result["ok"] is True
    assert model.vis.global_.fovy == pytest.approx(55.0)
    assert result["color_profile"]["profile_id"] == "display_srgb_soft_highlight_v1"
    assert result["color_management"]["fpv"]["before"]["overexposed_fraction"] == pytest.approx(1.0)
    assert result["color_management"]["fpv"]["after"]["overexposed_fraction"] == pytest.approx(0.0)
    assert result["color_management"]["fpv"]["backend_luminance_gain"]["backend"] == (
        "molmospaces-mujoco"
    )
    assert result["color_management"]["fpv"]["backend_luminance_gain"]["gain"] == pytest.approx(1.0)
    assert Path(result["images"]["fpv"]).is_file()


def test_molmospaces_worker_preserves_robot_view_role_on_camera_spec() -> None:
    pytest.importorskip("mujoco")
    worker = _load_worker_module()
    request = canonical_cleanup_robot_view_camera_request(
        label="0001 observe",
        robot_pose={"x": 1.0, "y": 2.0, "z": 0.0, "theta": 0.0, "head_pitch": 0.25},
        focus={"focus_position": [3.0, 2.0, 0.6]},
        width=320,
        height=240,
    )

    spec = worker._camera_view_spec(request["views"][0], index=1)

    assert spec["robot_view_role"] == "fpv"
    assert spec["camera_basis"] == "robot_pose_eye_target"


def test_worker_select_targets_honors_requested_generated_count() -> None:
    receptacles = [
        {"receptacle_id": "sink_01", "category": "Sink"},
        {"receptacle_id": "shelf_01", "category": "ShelvingUnit"},
        {"receptacle_id": "fridge_01", "category": "Fridge"},
        {"receptacle_id": "tvstand_01", "category": "TVStand"},
        {"receptacle_id": "bed_01", "category": "Bed"},
    ]
    objects = (
        [{"object_id": f"mug_{index:02d}", "category": "Mug"} for index in range(3)]
        + [{"object_id": f"book_{index:02d}", "category": "Book"} for index in range(3)]
        + [{"object_id": f"apple_{index:02d}", "category": "Apple"} for index in range(3)]
        + [{"object_id": f"remote_{index:02d}", "category": "RemoteControl"} for index in range(3)]
        + [{"object_id": f"pillow_{index:02d}", "category": "Pillow"} for index in range(3)]
    )

    selected = select_generated_mess_targets(objects, receptacles, target_count=10)

    assert len(selected) == 10
    assert len({item["object_id"] for item in selected}) == 10
    assert all(item["target_receptacle_id"] for item in selected)
    assert generated_mess_success_threshold(10) == 7


def test_worker_select_targets_can_pin_object_ids() -> None:
    receptacles = [
        {"receptacle_id": "counter_01", "category": "CounterTop"},
        {"receptacle_id": "fridge_01", "category": "Fridge"},
    ]
    objects = [
        {"object_id": "bread_01", "category": "Bread"},
        {"object_id": "apple_01", "category": "Apple"},
    ]

    selected = select_generated_mess_targets(
        objects,
        receptacles,
        target_count=1,
        object_ids=("apple_01",),
    )

    assert [item["object_id"] for item in selected] == ["apple_01"]
    assert selected[0]["target_receptacle_id"] == "fridge_01"


def test_worker_select_targets_uses_seed_for_source_pool_diversity() -> None:
    receptacles = [
        {"receptacle_id": "sink_01", "category": "Sink"},
        {"receptacle_id": "shelf_01", "category": "ShelvingUnit"},
        {"receptacle_id": "fridge_01", "category": "Fridge"},
        {"receptacle_id": "tvstand_01", "category": "TVStand"},
        {"receptacle_id": "bed_01", "category": "Bed"},
    ]
    objects = (
        [{"object_id": f"mug_{index:02d}", "category": "Mug"} for index in range(5)]
        + [{"object_id": f"book_{index:02d}", "category": "Book"} for index in range(5)]
        + [{"object_id": f"apple_{index:02d}", "category": "Apple"} for index in range(5)]
        + [{"object_id": f"remote_{index:02d}", "category": "RemoteControl"} for index in range(5)]
        + [{"object_id": f"pillow_{index:02d}", "category": "Pillow"} for index in range(5)]
    )

    first = select_generated_mess_targets(objects, receptacles, target_count=10, seed=11)
    second = select_generated_mess_targets(objects, receptacles, target_count=10, seed=11)
    third = select_generated_mess_targets(objects, receptacles, target_count=10, seed=12)

    assert [item["object_id"] for item in first] == [item["object_id"] for item in second]
    assert [item["object_id"] for item in first] != [item["object_id"] for item in third]
    assert [item["target_receptacle_id"] for item in first] == [
        item["target_receptacle_id"] for item in third
    ]


def test_generated_mess_manifest_records_stable_start_receptacles() -> None:
    receptacles = [
        {"receptacle_id": "sink_01", "category": "Sink"},
        {"receptacle_id": "fridge_01", "category": "Fridge"},
        {"receptacle_id": "sofa_01", "category": "Sofa"},
    ]
    objects = [
        {"object_id": "apple_01", "category": "Apple"},
        {"object_id": "plate_01", "category": "Plate"},
    ]

    first = build_generated_mess_manifest(
        objects,
        receptacles,
        target_count=2,
        seed=6,
        scene_source="procthor-10k-val",
        scene_index=0,
    )
    second = build_generated_mess_manifest(
        objects,
        receptacles,
        target_count=2,
        seed=6,
        scene_source="procthor-10k-val",
        scene_index=0,
    )
    selected = targets_from_generated_mess_manifest(
        objects,
        receptacles,
        first,
        target_count=2,
    )

    assert first == second
    assert first["schema"] == "roboclaws_generated_mess_manifest_v1"
    assert [target["object_id"] for target in first["targets"]] == ["plate_01", "apple_01"]
    assert [target["target_receptacle_id"] for target in first["targets"]] == [
        "sink_01",
        "fridge_01",
    ]
    assert [target["start_receptacle_id"] for target in first["targets"]] == [
        "sofa_01",
        "sofa_01",
    ]
    assert [item["start_receptacle_id"] for item in selected] == ["sofa_01", "sofa_01"]


def test_generated_mess_manifest_requires_explicit_relation_and_placement_index() -> None:
    receptacles = [
        {"receptacle_id": "sink_01", "category": "Sink"},
        {"receptacle_id": "sofa_01", "category": "Sofa"},
    ]
    objects = [{"object_id": "plate_01", "category": "Plate"}]

    with pytest.raises(ValueError, match="relation must be 'on' or 'inside'"):
        targets_from_generated_mess_manifest(
            objects,
            receptacles,
            {
                "schema": "roboclaws_generated_mess_manifest_v1",
                "targets": [
                    {
                        "object_id": "plate_01",
                        "valid_receptacle_ids": ["sink_01"],
                        "target_receptacle_id": "sink_01",
                        "start_receptacle_id": "sofa_01",
                        "placement_index": 0,
                    }
                ],
            },
            target_count=1,
        )

    with pytest.raises(ValueError, match="placement_index must be an integer"):
        targets_from_generated_mess_manifest(
            objects,
            receptacles,
            {
                "schema": "roboclaws_generated_mess_manifest_v1",
                "targets": [
                    {
                        "object_id": "plate_01",
                        "valid_receptacle_ids": ["sink_01"],
                        "target_receptacle_id": "sink_01",
                        "start_receptacle_id": "sofa_01",
                        "relation": "on",
                    }
                ],
            },
            target_count=1,
        )

    for placement_index in (1.2, True):
        with pytest.raises(ValueError, match="placement_index must be an integer"):
            targets_from_generated_mess_manifest(
                objects,
                receptacles,
                {
                    "schema": "roboclaws_generated_mess_manifest_v1",
                    "targets": [
                        {
                            "object_id": "plate_01",
                            "valid_receptacle_ids": ["sink_01"],
                            "target_receptacle_id": "sink_01",
                            "start_receptacle_id": "sofa_01",
                            "relation": "on",
                            "placement_index": placement_index,
                        }
                    ],
                },
                target_count=1,
            )


def test_worker_placement_diagnostic_records_support_relation() -> None:
    pytest.importorskip("mujoco")
    worker = _load_worker_module()
    state = {
        "objects": {
            "book_01": {
                "object_id": "book_01",
                "category": "Book",
                "body_name": "book/body",
                "position": [5.12, 6.08, 0.73],
            }
        },
        "receptacles": {
            "table_01": {
                "receptacle_id": "table_01",
                "category": "DiningTable",
                "body_name": "table/body",
                "position": [5.0, 6.0, 0.38],
            }
        },
    }

    diagnostic = worker._placement_diagnostic(
        state=state,
        object_id="book_01",
        receptacle_id="table_01",
        relation="on",
        requested_position=[5.12, 6.08, 0.73],
        source="unit_test",
    )

    assert diagnostic["schema"] == "molmospaces_semantic_placement_diagnostic_v1"
    assert diagnostic["support_status"] == "semantic_on_receptacle"
    assert diagnostic["relation"] == "on"
    assert diagnostic["xy_distance_m"] == pytest.approx(0.144222)
    assert diagnostic["z_delta_m"] == pytest.approx(0.35)
    assert diagnostic["contact_proof"] == "not_measured_mujoco_freejoint_qpos"


def test_worker_table_placement_uses_support_top_for_flat_objects() -> None:
    pytest.importorskip("mujoco")
    worker = _load_worker_module()

    position = worker._placement_position(
        {
            "receptacle_id": "table_01",
            "category": "DiningTable",
            "position": [5.0, 6.0, 0.38],
            "support_top_z": 1.21,
        },
        index=0,
        relation="on",
        object_category="Book",
    )

    assert position == pytest.approx([4.88, 6.0, 1.25])


def test_worker_remote_control_tv_stand_placement_stays_visible_from_front() -> None:
    pytest.importorskip("mujoco")
    worker = _load_worker_module()
    tv_stand = {
        "receptacle_id": "stand_01",
        "category": "TVStand",
        "position": [1.06, 10.21, 0.35],
    }

    first_position = worker._placement_position(
        tv_stand,
        index=3,
        relation="on",
        object_category="RemoteControl",
    )
    second_position = worker._placement_position(
        tv_stand,
        index=8,
        relation="on",
        object_category="RemoteControl",
    )

    assert first_position == pytest.approx([0.88, 9.93, 0.84])
    assert second_position == pytest.approx([1.06, 9.93, 0.84])


@pytest.mark.parametrize("category", ["CounterTop", "DiningTable", "Desk", "TVStand"])
def test_worker_direct_support_resolver_is_geometry_first_for_surface_categories(
    category: str,
) -> None:
    pytest.importorskip("mujoco")
    worker = _load_worker_module()
    model = worker.mujoco.MjModel.from_xml_string(
        """
        <mujoco>
          <worldbody>
            <body name="fixture">
              <geom name="fixture_collision" type="box" pos="0 0 0.7" size="0.6 0.4 0.05"/>
            </body>
            <body name="object" pos="0 0 1.0">
              <freejoint/>
              <geom name="object_collision" type="box" size="0.08 0.04 0.02"/>
            </body>
          </worldbody>
        </mujoco>
        """
    )
    data = worker.mujoco.MjData(model)
    worker.mujoco.mj_forward(model, data)
    surfaces = worker._receptacle_support_surfaces(model, data, "fixture")
    state = {
        "objects": {
            "object_01": {
                "object_id": "object_01",
                "category": "RemoteControl",
                "body_name": "object",
                "position": [0.0, 0.0, 1.0],
            }
        },
        "receptacles": {
            "fixture_01": {
                "receptacle_id": "fixture_01",
                "category": category,
                "body_name": "fixture",
                "position": [0.0, 0.0, 0.7],
                "support_surfaces": surfaces,
                "support_top_z": worker._support_top_z(surfaces),
            }
        },
    }

    resolution = worker._resolve_placement(
        model,
        data,
        state=state,
        object_id="object_01",
        receptacle_id="fixture_01",
        index=0,
        relation="on",
    )

    assert resolution["support_status"] == "direct_support"
    assert resolution["contact_proof"] == "geometry_direct_support"
    assert resolution["degraded"] is False
    surface = resolution["support_surface"]
    assert abs(resolution["position"][0] - surface["center"][0]) <= surface["half_extents"][0]
    assert abs(resolution["position"][1] - surface["center"][1]) <= surface["half_extents"][1]
    assert resolution["position"][2] > surface["top_z"]


def test_worker_direct_support_resolver_avoids_occupied_surface_slot() -> None:
    pytest.importorskip("mujoco")
    worker = _load_worker_module()
    model = worker.mujoco.MjModel.from_xml_string(
        """
        <mujoco>
          <worldbody>
            <body name="fixture">
              <geom name="fixture_collision" type="box" pos="0 0 0.7" size="0.6 0.4 0.05"/>
            </body>
            <body name="object" pos="0 0 1.0">
              <freejoint/>
              <geom name="object_collision" type="box" size="0.08 0.04 0.02"/>
            </body>
            <body name="blocker" pos="0 0 0.82">
              <freejoint/>
              <geom name="blocker_collision" type="box" size="0.16 0.16 0.06"/>
            </body>
          </worldbody>
        </mujoco>
        """
    )
    data = worker.mujoco.MjData(model)
    worker.mujoco.mj_forward(model, data)
    surfaces = worker._receptacle_support_surfaces(model, data, "fixture")
    state = {
        "objects": {
            "object_01": {
                "object_id": "object_01",
                "category": "RemoteControl",
                "body_name": "object",
                "position": [0.0, 0.0, 1.0],
            },
            "blocker_01": {
                "object_id": "blocker_01",
                "category": "Pillow",
                "body_name": "blocker",
                "position": [0.0, 0.0, 0.82],
            },
        },
        "receptacles": {
            "fixture_01": {
                "receptacle_id": "fixture_01",
                "category": "Bed",
                "body_name": "fixture",
                "position": [0.0, 0.0, 0.7],
                "support_surfaces": surfaces,
                "support_top_z": worker._support_top_z(surfaces),
            }
        },
    }

    resolution = worker._resolve_placement(
        model,
        data,
        state=state,
        object_id="object_01",
        receptacle_id="fixture_01",
        index=0,
        relation="on",
    )

    assert resolution["support_status"] == "direct_support"
    assert resolution["degraded"] is False
    assert abs(resolution["position"][0]) > 0.05 or abs(resolution["position"][1]) > 0.05


def test_worker_place_degrades_without_blocking_when_support_surface_missing() -> None:
    pytest.importorskip("mujoco")
    worker = _load_worker_module()
    model = worker.mujoco.MjModel.from_xml_string(
        """
        <mujoco>
          <worldbody>
            <body name="object" pos="0 0 1.0">
              <freejoint/>
              <geom name="object_collision" type="box" size="0.08 0.04 0.02"/>
            </body>
          </worldbody>
        </mujoco>
        """
    )
    data = worker.mujoco.MjData(model)
    worker.mujoco.mj_forward(model, data)
    state = {
        "objects": {
            "object_01": {
                "object_id": "object_01",
                "category": "RemoteControl",
                "body_name": "object",
                "position": [0.0, 0.0, 1.0],
            }
        },
        "receptacles": {
            "fixture_01": {
                "receptacle_id": "fixture_01",
                "category": "Desk",
                "body_name": "missing_fixture",
                "position": [1.0, 2.0, 0.4],
            }
        },
    }

    resolution = worker._resolve_placement(
        model,
        data,
        state=state,
        object_id="object_01",
        receptacle_id="fixture_01",
        index=0,
        relation="on",
    )

    assert resolution["support_status"] == "degraded_elevated"
    assert resolution["degraded"] is True
    assert resolution["position"] == pytest.approx([1.0, 2.34, 0.85])


def test_worker_support_surface_accepts_rotated_collision_slab() -> None:
    pytest.importorskip("mujoco")
    worker = _load_worker_module()
    model = worker.mujoco.MjModel.from_xml_string(
        """
        <mujoco>
          <compiler angle="radian"/>
          <worldbody>
            <body name="fixture">
              <geom name="fixture_collision" type="box" euler="1.57079632679 0 0"
                    pos="0 0 0.7" size="0.6 0.05 0.4"/>
            </body>
          </worldbody>
        </mujoco>
        """
    )
    data = worker.mujoco.MjData(model)
    worker.mujoco.mj_forward(model, data)

    surfaces = worker._receptacle_support_surfaces(model, data, "fixture")

    assert surfaces
    assert surfaces[0]["top_z"] == pytest.approx(0.75)
    assert surfaces[0]["half_extents"] == pytest.approx([0.6, 0.4])


def test_worker_room_outlines_use_mesh_world_bounds_not_geom_size() -> None:
    pytest.importorskip("mujoco")
    worker = _load_worker_module()
    model = worker.mujoco.MjModel.from_xml_string(
        """
        <mujoco>
          <asset>
            <mesh name="room_1"
                  vertex="0 0 0  0 2 0  4 0 0  4 2 0
                          0 0 .1  0 2 .1  4 0 .1  4 2 .1"/>
          </asset>
          <worldbody>
            <body name="room_1" pos="1 2 0">
              <geom name="room_1_visual_0" type="mesh" mesh="room_1"/>
            </body>
          </worldbody>
        </mujoco>
        """
    )
    data = worker.mujoco.MjData(model)
    worker.mujoco.mj_forward(model, data)

    outlines = worker._collect_room_outlines(
        model,
        data,
        {
            "receptacles": {},
            "objects": {},
            "source_room_labels": {
                "room_1": {
                    "room_label": "Kitchen",
                    "room_type": "Kitchen",
                    "room_label_provenance": "source_scene_json",
                }
            },
        },
    )

    assert outlines == [
        {
            "room_id": "room_1",
            "label": "Kitchen",
            "room_label": "Kitchen",
            "room_type": "Kitchen",
            "room_label_provenance": "source_scene_json",
            "center": pytest.approx([3.0, 3.0]),
            "half_extents": pytest.approx([2.0, 1.0]),
            "provenance": "mujoco_room_mesh_world_bounds",
        }
    ]


def test_worker_places_non_scoring_object_on_open_shelf_without_open(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    pytest.importorskip("mujoco")
    worker = _load_worker_module()

    class _FakeData:
        qpos = [0.0]

    state = {
        "held_object_id": "book_01",
        "selected_object_ids": [],
        "qpos": [0.0],
        "open_receptacle_ids": [],
        "current_receptacle_id": None,
        "objects": {
            "book_01": {
                "object_id": "book_01",
                "category": "Book",
                "body_name": "book/body",
                "position": [0.0, 0.0, 0.0],
            }
        },
        "receptacles": {
            "shelf_01": {
                "receptacle_id": "shelf_01",
                "category": "ShelvingUnit",
                "body_name": "shelf/body",
                "position": [1.0, 2.0, 0.4],
            },
            "fridge_01": {
                "receptacle_id": "fridge_01",
                "category": "Fridge",
                "body_name": "fridge/body",
                "position": [3.0, 4.0, 0.6],
            },
        },
    }

    monkeypatch.setattr(
        worker,
        "_load_model_data_for_state",
        lambda _state: (object(), _FakeData()),
    )
    monkeypatch.setattr(worker, "_apply_qpos", lambda _data, _qpos: None)
    monkeypatch.setattr(worker, "_set_free_body_position", lambda *_args: None)
    monkeypatch.setattr(worker, "_refresh_object_positions", lambda *_args: None)
    monkeypatch.setattr(worker.mujoco, "mj_forward", lambda *_args: None)

    placed = worker._place_object_at_receptacle(
        state,
        "shelf_01",
        tool="place_inside",
        relation="inside",
    )

    assert placed["ok"] is True
    assert placed["location_relation"] == "inside"
    assert placed["contained_in"] == "shelf_01"
    state["held_object_id"] = "book_01"
    rejected = worker._place_object_at_receptacle(
        state,
        "fridge_01",
        tool="place_inside",
        relation="inside",
    )
    assert rejected["ok"] is False
    assert rejected["error_reason"] == "receptacle_closed"


def test_worker_visual_grounding_marks_zero_pixels_weak_or_contained() -> None:
    pytest.importorskip("mujoco")
    worker = _load_worker_module()

    weak = worker._annotate_focus_visual_grounding(
        {
            "has_focus": True,
            "object_id": "book_01",
            "receptacle_id": "desk_01",
            "fpv_visibility": {"status": "ok", "object_pixels": 0},
            "visibility": {"status": "ok", "object_pixels": 0},
        }
    )
    contained = worker._annotate_focus_visual_grounding(
        {
            "has_focus": True,
            "object_id": "apple_01",
            "receptacle_id": "fridge_01",
            "receptacle_category": "Fridge",
            "object_contained_in": "fridge_01",
            "object_location_relation": "inside",
            "fpv_visibility": {"status": "ok", "object_pixels": 0},
            "visibility": {"status": "ok", "object_pixels": 0},
        }
    )
    open_shelf = worker._annotate_focus_visual_grounding(
        {
            "has_focus": True,
            "object_id": "book_01",
            "receptacle_id": "shelf_01",
            "receptacle_category": "ShelvingUnit",
            "object_contained_in": "shelf_01",
            "object_location_relation": "inside",
            "fpv_visibility": {"status": "ok", "object_pixels": 0},
            "visibility": {"status": "ok", "object_pixels": 0},
        }
    )

    assert weak["fpv_visibility"]["status"] == "weak_object_visibility"
    assert weak["visibility"]["status"] == "weak_object_visibility"
    assert contained["fpv_visibility"]["status"] == "contained_inside"
    assert contained["visibility"]["status"] == "contained_inside"
    assert open_shelf["fpv_visibility"]["status"] == "weak_object_visibility"
    assert open_shelf["visibility"]["status"] == "weak_object_visibility"


def test_worker_reuses_grounded_fpv_when_verify_closeup_misses_focus() -> None:
    pytest.importorskip("mujoco")
    worker = _load_worker_module()
    focus = {
        "has_focus": True,
        "object_id": "potato_01",
        "object_body_name": "potato/body",
        "object_label": "Potato potato",
        "fpv_visibility": {"status": "ok", "object_pixels": 120, "boxes": [{"bbox": [1, 2, 3, 4]}]},
        "visibility": {
            "status": "weak_object_visibility",
            "object_pixels": 0,
            "boxes": [],
        },
    }

    assert worker._should_use_fpv_as_verify_focus(focus) is True


def test_canonical_cleanup_robot_view_camera_request_uses_explicit_eye_target() -> None:
    request = canonical_cleanup_robot_view_camera_request(
        label="0001 observe",
        robot_pose={"x": 1.0, "y": 2.0, "z": 0.0, "theta": 0.0, "head_pitch": 0.25},
        focus={"focus_position": [3.0, 2.0, 0.6]},
        width=320,
        height=240,
    )

    assert request is not None
    assert request["api_name"] == "roboclaws.camera_control.render_views"
    assert request["camera_model"] == "canonical_eye_target_camera_v1"
    assert request["render_resolution"] == {"width": 320, "height": 240}
    assert request["lighting_profile"]["profile_id"] == "scene_probe_balanced_review_light_v1"
    rig = scene_light_rig(request["lighting_profile"])
    assert rig["schema"] == "scene_light_rig_v1"
    assert rig["key"]["enabled"] is True
    assert rig["fill"]["enabled"] is False
    assert rig["backend_overrides"]["isaac"]["key_intensity"] == pytest.approx(900.0)
    assert rig["ambient"]["isaac_dome_intensity"] == pytest.approx(120.0)
    assert rig["ambient"]["mujoco_headlight_ambient"] == pytest.approx([0.35, 0.35, 0.35])
    assert rig["ambient"]["mujoco_headlight_diffuse"] == pytest.approx([0.4, 0.4, 0.4])
    assert request["color_profile"]["profile_id"] == "display_srgb_soft_highlight_v1"
    assert request["color_profile"]["highlight_knee"] == pytest.approx(225.0)
    assert request["color_profile"]["backend_luminance_gain"]["molmospaces-mujoco"] == (
        pytest.approx(1.0)
    )
    assert request["color_profile"]["backend_luminance_gain"]["isaaclab-prepared-usd"] == (
        pytest.approx(0.7161647108631373)
    )
    assert [item["robot_view_role"] for item in request["views"]] == ["fpv", "verify"]
    assert request["views"][0]["eye"] == [1.0, 2.0, 1.55]
    assert request["views"][0]["target"] == [3.0, 2.0, 0.8]


def test_camera_color_profile_compresses_highlights() -> None:
    from roboclaws.household.color_management import apply_camera_color_profile

    frame = np.array(
        [
            [[250, 250, 250], [220, 220, 220]],
            [[245, 240, 235], [10, 20, 30]],
        ],
        dtype=np.uint8,
    )

    adjusted, diagnostics = apply_camera_color_profile(
        frame,
        np=np,
        profile={
            "profile_id": "display_srgb_soft_highlight_v1",
            "highlight_knee": 225.0,
            "highlight_compression": 0.5,
            "gamma": 1.0,
        },
    )

    assert adjusted.dtype == np.uint8
    assert int(adjusted[0, 0, 0]) == 237
    assert int(adjusted[0, 1, 0]) == 220
    assert diagnostics["profile"]["profile_id"] == "display_srgb_soft_highlight_v1"
    assert (
        diagnostics["before"]["overexposed_fraction"] > diagnostics["after"]["overexposed_fraction"]
    )


def test_camera_color_profile_applies_backend_luminance_gain() -> None:
    from roboclaws.household.color_management import apply_camera_color_profile

    frame = np.full((2, 2, 3), 100, dtype=np.uint8)

    adjusted, diagnostics = apply_camera_color_profile(
        frame,
        np=np,
        profile={
            "profile_id": "display_srgb_soft_highlight_v1",
            "highlight_knee": 225.0,
            "highlight_compression": 0.5,
            "gamma": 1.0,
            "backend_luminance_gain": {
                "molmospaces-mujoco": 1.0,
                "isaaclab-prepared-usd": 0.5,
            },
            "backend_luminance_gain_source": "unit",
        },
        backend="isaaclab-prepared-usd",
    )

    assert int(adjusted[0, 0, 0]) == 50
    assert diagnostics["backend_luminance_gain"]["status"] == "applied"
    assert diagnostics["backend_luminance_gain"]["gain"] == pytest.approx(0.5)
    assert diagnostics["backend_luminance_gain"]["source"] == "unit"


def test_camera_color_profile_prefers_backend_view_luminance_gain() -> None:
    from roboclaws.household.color_management import apply_camera_color_profile

    frame = np.full((2, 2, 3), 100, dtype=np.uint8)

    adjusted, diagnostics = apply_camera_color_profile(
        frame,
        np=np,
        profile={
            "profile_id": "display_srgb_soft_highlight_v1",
            "highlight_knee": 225.0,
            "highlight_compression": 0.5,
            "gamma": 1.0,
            "backend_luminance_gain": {"isaaclab-prepared-usd": 0.5},
            "backend_view_luminance_gain": {"isaaclab-prepared-usd": {"room_02_room_3": 0.25}},
            "backend_view_luminance_gain_source": "unit-view",
        },
        backend="isaaclab-prepared-usd",
        view_id="room_02_room_3",
    )

    assert int(adjusted[0, 0, 0]) == 25
    assert diagnostics["backend_luminance_gain"]["status"] == "applied_view_gain"
    assert diagnostics["backend_luminance_gain"]["gain"] == pytest.approx(0.25)
    assert diagnostics["backend_luminance_gain"]["source"] == "unit-view"


def test_camera_color_profile_prefers_backend_view_rgb_gain() -> None:
    from roboclaws.household.color_management import apply_camera_color_profile

    frame = np.full((2, 2, 3), 100, dtype=np.uint8)

    adjusted, diagnostics = apply_camera_color_profile(
        frame,
        np=np,
        profile={
            "profile_id": "display_srgb_soft_highlight_v1",
            "highlight_knee": 225.0,
            "highlight_compression": 0.5,
            "gamma": 1.0,
            "backend_rgb_gain": {"isaaclab-prepared-usd": [1.0, 1.0, 1.0]},
            "backend_view_rgb_gain": {
                "isaaclab-prepared-usd": {"room_02_room_3": [0.5, 0.25, 0.1]}
            },
            "backend_view_rgb_gain_source": "unit-view-rgb",
        },
        backend="isaaclab-prepared-usd",
        view_id="room_02_room_3",
    )

    assert adjusted[0, 0].tolist() == [50, 25, 10]
    assert diagnostics["backend_rgb_gain"]["status"] == "applied_view_gain"
    assert diagnostics["backend_rgb_gain"]["gain"] == pytest.approx([0.5, 0.25, 0.1])
    assert diagnostics["backend_rgb_gain"]["source"] == "unit-view-rgb"


def test_camera_color_profile_applies_backend_tone_adjustment() -> None:
    from roboclaws.household.color_management import apply_camera_color_profile

    frame = np.full((2, 2, 3), 64, dtype=np.uint8)

    adjusted, diagnostics = apply_camera_color_profile(
        frame,
        np=np,
        profile={
            "profile_id": "display_srgb_soft_highlight_v1",
            "highlight_knee": 225.0,
            "highlight_compression": 0.5,
            "gamma": 1.0,
            "backend_tone_adjustment": {
                "unit-test-renderer": {
                    "shadow_lift": 16.0,
                    "shadow_floor": 128.0,
                    "gamma": 1.0,
                    "saturation": 1.0,
                    "gain": 1.25,
                }
            },
            "backend_tone_adjustment_source": "unit-tone",
        },
        backend="unit-test-renderer",
    )

    assert int(adjusted[0, 0, 0]) == 90
    assert diagnostics["backend_tone_adjustment"]["status"] == "applied"
    assert diagnostics["backend_tone_adjustment"]["adjustment"]["shadow_lift"] == (
        pytest.approx(16.0)
    )
    assert diagnostics["backend_tone_adjustment"]["source"] == "unit-tone"


def test_worker_robot_pose_near_receptacle_uses_shared_pose_resolver() -> None:
    pytest.importorskip("mujoco")
    worker = _load_worker_module()
    state = {
        "receptacles": {
            "sink_01": {
                "receptacle_id": "sink_01",
                "position": [2.5, 5.5, 0.75],
                "room_area": "room_2",
            }
        },
        "objects": {},
        "room_outlines": [
            {
                "room_id": "room_2",
                "center": [2.99, 4.983],
                "half_extents": [2.99, 4.983],
            }
        ],
    }

    pose = worker._robot_pose_near_receptacle(state, state["receptacles"]["sink_01"])

    assert pose["schema"] == "cleanup_robot_pose_result_v1"
    assert pose["pose_source"] == "roboclaws_shared_scene_frame_support_pose"
    assert pose["pose_request"]["schema"] == "cleanup_robot_pose_request_v1"
    assert pose["pose_request"]["resolver"] == "roboclaws.cleanup_robot_pose.near_target_v1"
    assert pose["target_receptacle_id"] == "sink_01"
    assert pose["target_room_id"] == "room_2"
    assert pose["same_room_as_target"] is True


def test_worker_robot_views_uses_robot_head_camera_for_fpv(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    pytest.importorskip("mujoco")
    worker = _load_worker_module()
    frame = np.zeros((12, 16, 3), dtype=np.uint8)
    state = {
        "robot_included": True,
        "robot_name": "rby1m",
        "robot_pose": {"x": 1.0, "y": 2.0, "z": 0.0, "theta": 0.0, "head_pitch": 0.25},
        "robot_trajectory": [],
        "robot_view_provenance": {},
        "objects": {},
        "receptacles": {},
        "room_outlines": [],
        "qpos": [],
        "tool_event_counts": {},
    }
    fake_model = SimpleNamespace(jnt_qposadr=[0, 1])
    fake_data = SimpleNamespace(qpos=[0.0, 0.0])
    joint_ids = {"robot_0/head_0": 0, "robot_0/head_1": 1}
    monkeypatch.setattr(
        worker,
        "_load_model_data_for_state",
        lambda _state: (fake_model, fake_data),
    )
    monkeypatch.setattr(worker, "_apply_qpos", lambda *_args: None)
    monkeypatch.setattr(worker, "_refresh_object_positions", lambda *_args: None)
    monkeypatch.setattr(worker.mujoco, "mj_forward", lambda *_args: None)
    monkeypatch.setattr(
        worker.mujoco,
        "mj_name2id",
        lambda _model, _obj_type, name: joint_ids.get(name, -1),
    )
    fixed_camera_calls: list[str] = []

    def fake_render_fixed_camera(_model, _data, camera_name: str, **_kwargs):
        fixed_camera_calls.append(camera_name)
        return frame.copy()

    monkeypatch.setattr(worker, "_render_fixed_camera", fake_render_fixed_camera)
    monkeypatch.setattr(worker, "_render_free_camera", lambda *_args, **_kwargs: frame.copy())
    monkeypatch.setattr(
        worker, "_render_robot_map", lambda *_args, **_kwargs: worker.Image.new("RGB", (4, 4))
    )
    monkeypatch.setattr(
        worker,
        "_focus_visibility",
        lambda *_args, **_kwargs: {"status": "ok", "object_pixels": 1, "boxes": []},
    )

    def fake_topdown_render(*_args, **kwargs):
        output_dir = Path(kwargs["output_dir"])
        output_dir.mkdir(parents=True, exist_ok=True)
        image_path = output_dir / "topdown_scene.png"
        worker.Image.new("RGB", (16, 12)).save(image_path)
        return {
            "ok": True,
            "images": {"topdown_scene": "~/0001_observe.topdown_scene/topdown_scene.png"},
        }

    monkeypatch.setattr(Path, "home", classmethod(lambda _cls: tmp_path))
    monkeypatch.setattr(worker, "_render_camera_views_with_model_data", fake_topdown_render)
    result = worker.write_robot_views(
        state,
        tmp_path,
        "0001_observe",
        camera_yaw_offset_deg=12.5,
        camera_pitch_offset_deg=-7.0,
        width=16,
        height=12,
    )

    assert result["ok"] is True
    assert state["tool_event_counts"] == {"robot_views:request": 1}
    assert fixed_camera_calls[:2] == ["robot_0/head_camera", "robot_0/camera_follower"]
    assert result["camera_control_contract"]["same_pose_api"] is False
    assert result["camera_control_contract"]["status"] == "robot_mounted_head_camera_robot_view"
    assert result["camera_control_contract"]["camera_model"] == "robot_mounted_head_camera_v1"
    assert result["camera_control_contract"]["agent_facing_fpv"]["source"] == (
        "robot_0/head_camera"
    )
    assert result["camera_control_contract"]["agent_facing_fpv"]["robot_mounted"] is True
    assert result["camera_control_contract"]["camera_adjustment"]["requested"] is True
    assert result["camera_control_contract"]["camera_adjustment"]["applied"] is True
    assert result["camera_control_contract"]["camera_adjustment"]["yaw_delta_deg"] == 12.5
    assert result["camera_control_contract"]["camera_adjustment"]["pitch_delta_deg"] == -7.0
    assert result["camera_diagnostics"]["schema"] == "mujoco_robot_view_camera_diagnostics_v1"
    assert result["camera_diagnostics"]["render_resolution"] == {"width": 16, "height": 12}
    assert result["camera_diagnostics"]["camera_adjustment"]["apply_status"] == (
        "robot_head_joints_render_only"
    )
    assert result["camera_diagnostics"]["views"]["fpv"]["camera_name"] == "robot_0/head_camera"
    assert result["camera_diagnostics"]["views"]["chase"]["camera_name"] == (
        "robot_0/camera_follower"
    )
    assert result["camera_adjustment"]["applied"] is True
    assert fake_data.qpos[0] == pytest.approx(np.deg2rad(12.5))
    assert fake_data.qpos[1] == pytest.approx(np.deg2rad(-7.0))
    assert (tmp_path / "0001_observe.fpv.png").is_file()


def test_worker_robot_view_camera_offset_updates_head_joints_for_render(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    worker = _load_worker_module()
    model = SimpleNamespace(jnt_qposadr=[3, 4])
    data = SimpleNamespace(qpos=[0.0, 0.0, 0.0, 0.25, -0.1])
    joint_ids = {"robot_0/head_0": 0, "robot_0/head_1": 1}

    def fake_name2id(_model, _obj_type, name: str) -> int:
        return joint_ids.get(name, -1)

    monkeypatch.setattr(worker.mujoco, "mj_name2id", fake_name2id)

    adjustment = worker._apply_robot_view_camera_offset(
        model,
        data,
        yaw_offset_deg=30.0,
        pitch_offset_deg=-15.0,
    )

    assert adjustment["applied"] is True
    assert adjustment["applied_joints"] == ["robot_0/head_0", "robot_0/head_1"]
    assert data.qpos[3] == pytest.approx(0.25 + np.deg2rad(30.0))
    assert data.qpos[4] == pytest.approx(-0.1 + np.deg2rad(-15.0))


def test_worker_grows_mujoco_offscreen_buffer_for_high_res_render() -> None:
    pytest.importorskip("mujoco")
    worker = _load_worker_module()

    class GlobalSettings:
        offwidth = 1280
        offheight = 720

    class Vis:
        global_ = GlobalSettings()

    class Model:
        vis = Vis()

    model = Model()

    worker._ensure_offscreen_framebuffer(model, width=1620, height=1080)

    assert model.vis.global_.offwidth == 1620
    assert model.vis.global_.offheight == 1080

    worker._ensure_offscreen_framebuffer(model, width=540, height=360)

    assert model.vis.global_.offwidth == 1620
    assert model.vis.global_.offheight == 1080


def test_worker_robot_views_keeps_backend_local_fallback_without_pose(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    pytest.importorskip("mujoco")
    worker = _load_worker_module()
    frame = np.zeros((12, 16, 3), dtype=np.uint8)
    state = {
        "robot_included": True,
        "robot_name": "rby1m",
        "robot_trajectory": [],
        "robot_view_provenance": {},
        "objects": {},
        "receptacles": {},
        "room_outlines": [],
        "qpos": [],
    }

    monkeypatch.setattr(worker, "_load_model_data_for_state", lambda _state: (object(), object()))
    monkeypatch.setattr(worker, "_apply_qpos", lambda *_args: None)
    monkeypatch.setattr(worker, "_refresh_object_positions", lambda *_args: None)
    monkeypatch.setattr(worker.mujoco, "mj_forward", lambda *_args: None)
    monkeypatch.setattr(worker, "_render_fixed_camera", lambda *_args, **_kwargs: frame.copy())
    monkeypatch.setattr(worker, "_render_free_camera", lambda *_args, **_kwargs: frame.copy())
    monkeypatch.setattr(
        worker, "_render_robot_map", lambda *_args, **_kwargs: worker.Image.new("RGB", (4, 4))
    )
    monkeypatch.setattr(worker, "_focus_camera", lambda *_args, **_kwargs: object())
    monkeypatch.setattr(
        worker,
        "_focus_visibility",
        lambda *_args, **_kwargs: {"status": "ok", "object_pixels": 1, "boxes": []},
    )
    monkeypatch.setattr(
        worker,
        "_render_camera_views_with_model_data",
        lambda *_args, **kwargs: _fake_topdown_render(worker, kwargs["output_dir"]),
    )

    result = worker.write_robot_views(state, tmp_path, "0001_observe", width=16, height=12)

    assert result["ok"] is True
    assert result["camera_control_contract"]["same_pose_api"] is False
    assert result["camera_control_contract"]["status"] == "robot_mounted_head_camera_robot_view"
    assert result["camera_control_contract"]["agent_facing_fpv"]["source"] == (
        "robot_0/head_camera"
    )


def _fake_topdown_render(worker, output_dir: Path) -> dict[str, object]:
    output_dir.mkdir(parents=True, exist_ok=True)
    image_path = output_dir / "topdown_scene.png"
    worker.Image.new("RGB", (16, 12)).save(image_path)
    return {
        "ok": True,
        "images": {"topdown_scene": str(image_path)},
    }


def test_worker_focus_payload_uses_held_object_closeup_before_receptacle_place() -> None:
    pytest.importorskip("mujoco")
    worker = _load_worker_module()
    state = {
        "objects": {
            "potato_01": {
                "object_id": "potato_01",
                "category": "Potato",
                "body_name": "potato/body",
                "position": [8.2, 5.0, 1.22],
                "contained_in": None,
                "location_relation": "held",
            }
        },
        "receptacles": {
            "fridge_01": {
                "receptacle_id": "fridge_01",
                "category": "Fridge",
                "body_name": "fridge/body",
                "position": [8.2, 4.7, 0.7],
            }
        },
    }

    focus = worker._focus_payload(state, "potato_01", "fridge_01")

    assert focus["focus_mode"] == "object_closeup"
    assert focus["focus_position"] == [8.2, 5.0, 1.22]


def test_worker_focus_camera_azimuth_does_not_apply_fridge_angle_to_held_object() -> None:
    pytest.importorskip("mujoco")
    worker = _load_worker_module()
    focus = {
        "focus_mode": "object_closeup",
        "receptacle_category": "Fridge",
        "object_contained_in": None,
        "receptacle_id": "fridge_01",
    }

    azimuth = worker._focus_camera_azimuth(
        {"robot_pose": {"x": 8.2, "y": 5.8}},
        [8.2, 5.0, 1.22],
        focus,
    )

    assert azimuth == pytest.approx(180.0)


def test_sync_held_object_to_robot_pose_moves_freejoint_body() -> None:
    pytest.importorskip("mujoco")
    worker = _load_worker_module()
    model = worker.mujoco.MjModel.from_xml_string(
        """
        <mujoco>
          <worldbody>
            <body name="apple" pos="0 0 0">
              <freejoint name="apple_free"/>
              <geom type="sphere" size="0.03"/>
            </body>
          </worldbody>
        </mujoco>
        """
    )
    data = worker.mujoco.MjData(model)
    state = {
        "held_object_id": "apple_01",
        "robot_pose": {"x": 1.0, "y": 2.0, "theta": 0.0},
        "objects": {"apple_01": {"body_name": "apple", "position": [0.0, 0.0, 0.0]}},
    }

    result = worker._sync_held_object_to_robot_pose(model, data, state)
    worker.mujoco.mj_forward(model, data)

    body_id = worker.mujoco.mj_name2id(model, worker.mujoco.mjtObj.mjOBJ_BODY, "apple")
    assert result == {
        "object_id": "apple_01",
        "position": [1.8, 2.0, 1.22],
        "position_source": "robot_relative_held_pose",
    }
    assert data.xpos[body_id].tolist() == pytest.approx([1.8, 2.0, 1.22])


def test_worker_runtime_render_state_records_object_articulation_joints() -> None:
    pytest.importorskip("mujoco")
    worker = _load_worker_module()
    model = worker.mujoco.MjModel.from_xml_string(
        """
        <mujoco>
          <compiler angle="radian"/>
          <worldbody>
            <body name="box" pos="0 0 0">
              <freejoint name="box_free"/>
              <geom type="box" size="0.1 0.1 0.05"/>
              <body name="box_flap" pos="0 0.1 0.05">
                <joint name="box/flap_outer_1" type="hinge" axis="1 0 0" range="-3.14 3.14"/>
                <geom type="box" size="0.1 0.01 0.05"/>
              </body>
            </body>
          </worldbody>
        </mujoco>
        """
    )
    data = worker.mujoco.MjData(model)
    joint_id = worker.mujoco.mj_name2id(
        model,
        worker.mujoco.mjtObj.mjOBJ_JOINT,
        "box/flap_outer_1",
    )
    data.qpos[int(model.jnt_qposadr[joint_id])] = 2.75
    worker.mujoco.mj_forward(model, data)
    state = {
        "qpos": [float(value) for value in data.qpos],
        "objects": {
            "box_01": {
                "object_id": "box_01",
                "category": "Box",
                "body_name": "box",
                "upstream_object_id": "Box|surface|1|1",
            }
        },
    }

    runtime_state = worker._runtime_render_state(model, data, state)

    box_state = runtime_state["objects"]["box_01"]
    assert runtime_state["articulated_object_count"] == 1
    assert box_state["articulation_status"] == "articulated"
    assert box_state["subtree_joint_count"] == 1
    assert box_state["articulation_joints"] == [
        {
            "joint_name": "box/flap_outer_1",
            "body_name": "box_flap",
            "joint_type": "hinge",
            "qposadr": int(model.jnt_qposadr[joint_id]),
            "qpos": [2.75],
            "range": [-3.14, 3.14],
        }
    ]
