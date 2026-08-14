from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pytest

from roboclaws.household.subprocess_backend import (
    MolmoSpacesSubprocessBackend,
)
from tests.unit.molmo_cleanup.molmo_cleanup_subprocess_backend_support import (
    _fake_topdown_render,
    _load_worker_module,
)


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
