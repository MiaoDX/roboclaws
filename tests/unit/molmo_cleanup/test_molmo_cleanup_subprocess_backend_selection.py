from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from roboclaws.core.generated_mess import generated_mess_success_threshold
from roboclaws.household.camera_control import scene_light_rig
from roboclaws.household.generated_mess import (
    build_generated_mess_manifest,
    select_generated_mess_targets,
    targets_from_generated_mess_manifest,
)
from roboclaws.household.robot_view_camera_control import (
    canonical_cleanup_robot_view_camera_request,
)
from tests.unit.molmo_cleanup.molmo_cleanup_subprocess_backend_support import (
    _load_worker_module,
)


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
