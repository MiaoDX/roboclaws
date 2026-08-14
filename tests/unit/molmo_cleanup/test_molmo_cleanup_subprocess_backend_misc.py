from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from roboclaws.household import worker_runner
from roboclaws.household.subprocess_backend import (
    MOLMOSPACES_SUBPROCESS_BACKEND,
    MolmoSpacesSubprocessBackend,
    _parse_last_json_object,
    _parse_persistent_worker_packet,
    _worker_kwargs_from_args,
)
from tests.unit.molmo_cleanup.molmo_cleanup_subprocess_backend_support import (
    _load_worker_module,
)


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
    assert captured["command"][1:3] == ["-m", "roboclaws.backends.molmospaces.worker"]
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
