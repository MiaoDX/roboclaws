from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pytest

from roboclaws.household.robot_view_camera_control import (
    canonical_cleanup_robot_view_camera_request,
)
from roboclaws.household.subprocess_backend import (
    _worker_kwargs_from_args,
)
from tests.unit.molmo_cleanup.molmo_cleanup_subprocess_backend_support import (
    _load_worker_module,
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
