from __future__ import annotations

import pytest

from tests.unit.molmo_cleanup.molmo_cleanup_subprocess_backend_support import (
    _load_worker_module,
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
