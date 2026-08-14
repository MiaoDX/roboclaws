from __future__ import annotations

import json
import sys
from pathlib import Path
from types import ModuleType, SimpleNamespace

import pytest


def test_molmospaces_worker_read_state_rejects_missing_state_source(tmp_path: Path) -> None:
    from roboclaws.backends.molmospaces.protocol import read_state

    missing = tmp_path / "missing_state.json"

    with pytest.raises(
        FileNotFoundError,
        match=r"MolmoSpaces worker state source is missing: .*missing_state\.json",
    ):
        read_state(missing)


def test_molmospaces_worker_read_state_rejects_malformed_state_source(tmp_path: Path) -> None:
    from roboclaws.backends.molmospaces.protocol import read_state

    state_path = tmp_path / "state.json"
    state_path.write_text("{bad json\n", encoding="utf-8")

    with pytest.raises(
        ValueError,
        match=r"MolmoSpaces worker state source must contain valid JSON object: .*state\.json",
    ):
        read_state(state_path)


def test_molmospaces_worker_read_state_rejects_non_object_state_source(tmp_path: Path) -> None:
    from roboclaws.backends.molmospaces.protocol import read_state

    state_path = tmp_path / "state.json"
    state_path.write_text("[]", encoding="utf-8")

    with pytest.raises(
        ValueError,
        match=r"MolmoSpaces worker state source must contain a JSON object: .*state\.json",
    ):
        read_state(state_path)


def test_molmospaces_worker_read_state_loads_valid_state(tmp_path: Path) -> None:
    from roboclaws.backends.molmospaces.protocol import read_state

    state_path = tmp_path / "state.json"
    state = {"schema": "runtime_state_v1", "locations": {}}
    state_path.write_text(json.dumps(state), encoding="utf-8")

    assert read_state(state_path) == state


def test_state_persists_home_paths_portably(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from roboclaws.backends.molmospaces.protocol import read_state, write_state

    home = tmp_path / "operator-home"
    monkeypatch.setenv("HOME", str(home))
    state_path = tmp_path / "state.json"
    state = {
        "scene_xml": str(home / ".cache" / "molmospaces" / "scene.xml"),
        "external_scene": "/opt/molmospaces/scene.xml",
    }

    write_state(state_path, state, refresh_runtime_render_state=lambda _state: None)

    persisted = json.loads(state_path.read_text(encoding="utf-8"))
    assert persisted["scene_xml"] == "~/.cache/molmospaces/scene.xml"
    assert persisted["external_scene"] == "/opt/molmospaces/scene.xml"
    assert str(home) not in state_path.read_text(encoding="utf-8")
    assert read_state(state_path) == state


def test_init_state_builds_init_envelope_with_injected_hooks(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    pytest.importorskip("mujoco")
    from roboclaws.backends.molmospaces.state import init_state

    _install_fake_molmospaces_modules(tmp_path, monkeypatch)
    scene_xml = tmp_path / "scene.xml"
    scene_xml.write_text("<mujoco/>", encoding="utf-8")
    state_path = tmp_path / "state.json"
    model = SimpleNamespace(nbody=1, ngeom=2, njnt=3, nq=4)
    data = SimpleNamespace(qpos=[0.1, 0.2, 0.3, 0.4])

    hooks = _init_hooks(scene_xml=scene_xml, model=model, data=data)

    result = init_state(
        state_path=state_path,
        seed=7,
        scene_source="procthor-10k-val",
        scene_index=3,
        generated_mess_count=0,
        hooks=hooks,
    )

    written_state = json.loads(state_path.read_text(encoding="utf-8"))
    assert result["tool"] == "init"
    assert result["model_stats"] == {"nbody": 1, "ngeom": 2, "njnt": 3, "nq": 4}
    assert result["generated_mess_manifest"] is None
    assert result["scenario"]["scenario_id"] == "molmospaces-unit-1"
    assert written_state["current_receptacle_id"] == "sink_01"
    assert written_state["source_room_labels"] == {
        "room_1": {
            "room_id": "room_1",
            "room_label": "Kitchen",
            "room_type": "Kitchen",
            "room_label_provenance": "source_scene_json",
        }
    }
    assert written_state["room_outlines"] == [{"room_id": "room_1"}]


def test_init_state_private_manifest_preserves_generated_manifest_destinations(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    pytest.importorskip("mujoco")
    from roboclaws.backends.molmospaces.state import init_state

    _install_fake_molmospaces_modules(tmp_path, monkeypatch)
    scene_xml = tmp_path / "scene.xml"
    scene_xml.write_text("<mujoco/>", encoding="utf-8")
    state_path = tmp_path / "state.json"
    model = SimpleNamespace(nbody=1, ngeom=2, njnt=3, nq=4)
    data = SimpleNamespace(qpos=[0.1, 0.2, 0.3, 0.4])
    generated_mess_manifest: dict[str, object] = {
        "schema": "roboclaws_generated_mess_manifest_v1",
        "targets": [
            {
                "object_id": "apple_01",
                "target_receptacle_id": "sink_01",
                "valid_receptacle_ids": ["sink_01", "shelf_01"],
                "start_receptacle_id": "shelf_01",
                "relation": "on",
                "placement_index": 0,
            }
        ],
    }
    hooks = _init_hooks(
        scene_xml=scene_xml,
        model=model,
        data=data,
        generated_mess_manifest=generated_mess_manifest,
    )

    init_state(
        state_path=state_path,
        seed=7,
        scene_source="procthor-10k-val",
        scene_index=3,
        generated_mess_count=1,
        generated_mess_manifest_path=tmp_path / "generated_mess_manifest.json",
        hooks=hooks,
    )

    written_state = json.loads(state_path.read_text(encoding="utf-8"))
    assert written_state["private_manifest"]["targets"] == [
        {
            "object_id": "apple_01",
            "valid_receptacle_ids": ["sink_01", "shelf_01"],
        }
    ]


def test_init_state_seeds_robot_pose_for_targetless_open_task(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    pytest.importorskip("mujoco")
    from roboclaws.backends.molmospaces.state import init_state

    _install_fake_molmospaces_modules(tmp_path, monkeypatch)
    scene_xml = tmp_path / "scene.xml"
    scene_xml.write_text("<mujoco/>", encoding="utf-8")
    robot_dir = tmp_path / "robots" / "rby1m"
    robot_dir.mkdir(parents=True)
    (robot_dir / "rby1m.xml").write_text("<mujoco/>", encoding="utf-8")
    state_path = tmp_path / "state.json"
    model = SimpleNamespace(nbody=1, ngeom=2, njnt=3, nq=4)
    data = SimpleNamespace(qpos=[0.1, 0.2, 0.3, 0.4])
    pose = {
        "x": 1.0,
        "y": 2.0,
        "theta": 0.5,
        "pose_source": "unit_initial_receptacle",
    }
    hooks = _init_hooks(scene_xml=scene_xml, model=model, data=data, robot_pose=pose)

    init_state(
        state_path=state_path,
        seed=7,
        scene_source="procthor-10k-val",
        scene_index=3,
        include_robot=True,
        generated_mess_count=0,
        hooks=hooks,
    )

    written_state = json.loads(state_path.read_text(encoding="utf-8"))
    assert written_state["current_receptacle_id"] == "sink_01"
    assert written_state["robot_pose"] == pose
    assert written_state["robot_trajectory"] == [pose]
    assert written_state["qpos"] == [0.1, 0.2, 0.3, 0.4]


def test_source_room_labels_reads_adjacent_scene_json(tmp_path: Path) -> None:
    from roboclaws.backends.molmospaces.initialization import source_room_labels

    scene_xml = tmp_path / "val_5.xml"
    scene_xml.write_text("<mujoco/>", encoding="utf-8")
    (tmp_path / "val_5.json").write_text(
        json.dumps(
            {
                "rooms": [
                    {"id": "room|4", "roomType": "Bedroom"},
                    {"id": "room|7", "roomType": "LivingRoom"},
                    {"id": "room0", "roomType": "reception lounge"},
                ]
            }
        ),
        encoding="utf-8",
    )

    assert source_room_labels(scene_xml) == {
        "room_4": {
            "room_id": "room_4",
            "room_label": "Bedroom",
            "room_type": "Bedroom",
            "room_label_provenance": "source_scene_json",
        },
        "room_7": {
            "room_id": "room_7",
            "room_label": "Living Room",
            "room_type": "LivingRoom",
            "room_label_provenance": "source_scene_json",
        },
        "room_0": {
            "room_id": "room_0",
            "room_label": "reception lounge",
            "room_type": "reception lounge",
            "room_label_provenance": "source_scene_json",
        },
    }


@pytest.mark.parametrize(
    ("payload", "error"),
    [
        ("{", "malformed source scene JSON"),
        (json.dumps([]), "source scene JSON must be a JSON object"),
        (json.dumps({"rooms": {}}), "source scene JSON rooms must be a JSON array"),
        (json.dumps({"rooms": ["room_1"]}), "source scene JSON rooms must contain JSON objects"),
    ],
)
def test_source_room_labels_fails_on_corrupt_adjacent_scene_json(
    tmp_path: Path,
    payload: str,
    error: str,
) -> None:
    from roboclaws.backends.molmospaces.initialization import source_room_labels

    scene_xml = tmp_path / "val_5.xml"
    scene_xml.write_text("<mujoco/>", encoding="utf-8")
    scene_xml.with_suffix(".json").write_text(payload, encoding="utf-8")

    with pytest.raises(RuntimeError, match=error):
        source_room_labels(scene_xml)


def test_source_room_labels_fails_on_empty_source_scene_json_before_ithor_fallback(
    tmp_path: Path,
) -> None:
    from roboclaws.backends.molmospaces.initialization import source_room_labels

    scene_xml = tmp_path / "FloorPlan301_physics.xml"
    scene_xml.write_text("<mujoco/>", encoding="utf-8")
    (tmp_path / "FloorPlan301.json").write_text(json.dumps({"rooms": []}), encoding="utf-8")

    with pytest.raises(RuntimeError, match="source scene JSON has no room labels"):
        source_room_labels(scene_xml)


def test_source_room_labels_uses_explicit_ithor_floorplan_provenance(tmp_path: Path) -> None:
    from roboclaws.backends.molmospaces.initialization import source_room_labels

    scene_xml = tmp_path / "FloorPlan301_physics.xml"
    scene_xml.write_text("<mujoco/>", encoding="utf-8")

    assert source_room_labels(scene_xml) == {
        "room_0": {
            "room_id": "room_0",
            "room_label": "Bedroom",
            "room_type": "Bedroom",
            "room_label_provenance": "ithor_floorplan_id",
        }
    }


def test_source_room_labels_fails_without_source_label_data(tmp_path: Path) -> None:
    from roboclaws.backends.molmospaces.initialization import source_room_labels

    scene_xml = tmp_path / "scene.xml"
    scene_xml.write_text("<mujoco/>", encoding="utf-8")

    with pytest.raises(RuntimeError, match="missing source room labels"):
        source_room_labels(scene_xml)


def test_all_supported_sim_scene_room_formats_have_source_room_labels(tmp_path: Path) -> None:
    from roboclaws.backends.molmospaces.initialization import source_room_labels

    # Physical-robot and B1 digital-twin room-label parity is future work, not sim coverage.
    scenes = {
        "procthor_scene.xml": [
            {"id": "room|4", "roomType": "Bedroom"},
            {"id": "room|7", "roomType": "LivingRoom"},
        ],
        "holodeck_scene.xml": [
            {"id": "room0", "roomType": "open office"},
            {"id": "room12", "roomType": "Kitchen"},
        ],
        "FloorPlan301_physics.xml": None,
    }

    for xml_name, rooms in scenes.items():
        scene_xml = tmp_path / xml_name
        scene_xml.write_text("<mujoco/>", encoding="utf-8")
        if rooms is not None:
            scene_xml.with_suffix(".json").write_text(
                json.dumps({"rooms": rooms}),
                encoding="utf-8",
            )

        labels = source_room_labels(scene_xml)
        assert labels, xml_name
        for room_id, label in labels.items():
            assert room_id.startswith("room_"), label
            assert label.get("room_id") == room_id
            assert str(label.get("room_label") or "").strip(), label
            assert str(label.get("room_type") or "").strip(), label
            assert str(label.get("room_label_provenance") or "").strip(), label


def _install_fake_molmospaces_modules(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    molmo_spaces = ModuleType("molmo_spaces")
    constants = ModuleType("molmo_spaces.molmo_spaces_constants")
    constants.get_robot_path = lambda robot_name: tmp_path / "robots" / str(robot_name)
    constants.get_scenes = lambda *_args, **_kwargs: {}
    constants.get_scenes_root = lambda: tmp_path
    utils = ModuleType("molmo_spaces.utils")
    lazy_loading = ModuleType("molmo_spaces.utils.lazy_loading_utils")
    lazy_loading.install_scene_with_objects_and_grasps_from_path = lambda _scene_xml: None
    metadata_utils = ModuleType("molmo_spaces.utils.scene_metadata_utils")
    metadata_utils.get_scene_metadata = lambda _scene_xml: {"objects": {"apple_01": {}}}
    for name, module in {
        "molmo_spaces": molmo_spaces,
        "molmo_spaces.molmo_spaces_constants": constants,
        "molmo_spaces.utils": utils,
        "molmo_spaces.utils.lazy_loading_utils": lazy_loading,
        "molmo_spaces.utils.scene_metadata_utils": metadata_utils,
    }.items():
        monkeypatch.setitem(sys.modules, name, module)


def _init_hooks(
    *,
    scene_xml: Path,
    model: SimpleNamespace,
    data: SimpleNamespace,
    robot_pose: dict[str, object] | None = None,
    generated_mess_manifest: dict[str, object] | None = None,
):
    from roboclaws.backends.molmospaces.state import MolmoInitHooks

    return MolmoInitHooks(
        backend="molmospaces_subprocess",
        collect_dynamic_objects=lambda *_args: [
            {
                "object_id": "apple_01",
                "name": "Apple",
                "category": "Apple",
                "body_name": "apple/body",
            }
        ],
        collect_receptacles=lambda *_args: [
            {"receptacle_id": "sink_01", "name": "Sink", "category": "Sink"},
            {"receptacle_id": "shelf_01", "name": "Shelf", "category": "ShelvingUnit"},
        ],
        collect_room_outlines=lambda *_args: [{"room_id": "room_1"}],
        first_receptacle_id=lambda _state: "sink_01",
        load_generated_mess_manifest=lambda _path: generated_mess_manifest or {},
        load_model_data=lambda _scene_xml: (model, data),
        load_robot_model_data=lambda *_args: (model, data),
        ok=lambda tool, **payload: {"ok": True, "tool": tool, "status": "ok", **payload},
        prepare_molmospaces_scene=lambda **_kwargs: (
            scene_xml,
            {"schema": "molmospaces_scene_resolution_v1"},
        ),
        public_scenario=lambda state: {
            "scenario_id": state["private_manifest"]["scenario_id"],
            "scene_xml": state["scene_xml"],
        },
        refresh_object_positions=lambda *_args: None,
        robot_camera_names=lambda _model: [],
        robot_pose_near_receptacle=lambda *_args: dict(robot_pose or {}),
        robot_result_payload=lambda *_args: {},
        robot_xml_name=lambda robot_name: f"{robot_name}.xml",
        scenario_id=lambda **_kwargs: "molmospaces-unit-1",
        seed_misplaced_objects=lambda *_args: None,
        set_robot_pose=lambda *_args: None,
        source_room_labels=lambda _scene_xml: {
            "room_1": {
                "room_id": "room_1",
                "room_label": "Kitchen",
                "room_type": "Kitchen",
                "room_label_provenance": "source_scene_json",
            }
        },
        target_start_receptacle_id=lambda *_args: "sink_01",
        write_state=lambda path, state: path.write_text(
            json.dumps(state, sort_keys=True),
            encoding="utf-8",
        ),
    )
