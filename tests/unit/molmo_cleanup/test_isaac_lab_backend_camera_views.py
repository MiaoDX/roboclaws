from __future__ import annotations

import json
import math
import sys
import types
from pathlib import Path
from types import SimpleNamespace

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
    IsaacLabSubprocessBackend,
)
from tests.unit.molmo_cleanup.isaac_lab_backend_support import (
    _fake_scene_camera_type,
    _FakeRobotPoseStage,
    _FakeSceneCameraSim,
    _FakeSceneCameraSimUtils,
    _FakeSceneCameraTorch,
    _install_robot_pose_pxr,
    _shared_robot_pose_state,
    _unit_scene_camera_request,
    _write_nonblank_image,
)


def test_isaac_camera_view_specs_reject_missing_source(tmp_path: Path) -> None:
    missing = tmp_path / "missing_views.json"

    with pytest.raises(
        FileNotFoundError,
        match=r"camera view spec source is missing: .*missing_views\.json",
    ):
        runtime_dependencies._load_camera_view_specs(missing)


def test_isaac_camera_view_specs_reject_malformed_source(tmp_path: Path) -> None:
    specs_path = tmp_path / "camera_views.json"
    specs_path.write_text("{bad json\n", encoding="utf-8")

    with pytest.raises(
        ValueError,
        match=r"camera view spec source must contain valid JSON: .*camera_views\.json",
    ):
        runtime_dependencies._load_camera_view_specs(specs_path)


def test_isaac_camera_view_specs_reject_wrong_shape_source(tmp_path: Path) -> None:
    specs_path = tmp_path / "camera_views.json"
    specs_path.write_text(json.dumps({"views": {"bad": True}}), encoding="utf-8")

    with pytest.raises(
        ValueError,
        match="camera view spec must be a list or an object with a views list",
    ):
        runtime_dependencies._load_camera_view_specs(specs_path)


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

    assert runtime_dependencies._load_camera_view_specs(list_path) == [
        {"view_id": "fpv", "target": [0.0, 0.0, 0.0]},
        {"view_id": "map", "target": [1.0, 0.0, 0.0]},
    ]
    assert runtime_dependencies._load_camera_view_specs(wrapped_path) == [
        {"view_id": "verify", "target": [2.0, 0.0, 0.0]}
    ]


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
    spec = runtime_camera._isaac_scene_camera_view_spec(
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
    spec = runtime_camera._isaac_scene_camera_view_spec(
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
        runtime_camera._isaac_scene_camera_view_spec(raw_spec, index=1)


def test_isaac_camera_lens_derives_horizontal_aperture_from_vertical_fov() -> None:
    aperture = runtime_camera._horizontal_aperture_from_lens(
        {"vertical_fov_deg": 45.0, "horizontal_aperture_mm": 20.955},
        width=960,
        height=640,
        focal_length=24.0,
    )

    assert aperture == pytest.approx(29.82337649)


def test_isaac_rby1m_head_camera_lens_matches_mujoco_vertical_fov() -> None:
    aperture = runtime_camera._horizontal_aperture_from_lens(
        {"vertical_fov_deg": runtime_dependencies.RBY1M_HEAD_CAMERA_VERTICAL_FOV_DEG},
        width=540,
        height=360,
        focal_length=runtime_dependencies.RBY1M_HEAD_CAMERA_FOCAL_LENGTH_MM,
    )
    metadata = runtime_dependencies._usd_camera_fov_metadata(
        focal_length=runtime_dependencies.RBY1M_HEAD_CAMERA_FOCAL_LENGTH_MM,
        horizontal_aperture=aperture,
        width=540,
        height=360,
    )

    assert aperture == pytest.approx(29.82337649)
    assert metadata["vertical_fov_deg"] == pytest.approx(45.0)


def test_isaac_rby1m_chase_camera_matches_mujoco_follower_pitch() -> None:
    eye, target = runtime_dependencies._robot_relative_chase_eye_target(
        {"x": 0.0, "y": 0.0, "z": 0.0, "yaw_deg": 0.0}
    )
    forward = tuple(target[index] - eye[index] for index in range(3))
    horizontal_distance = math.hypot(forward[0], forward[1])
    vertical_drop = -forward[2]

    assert eye == pytest.approx(runtime_dependencies.RBY1M_CHASE_CAMERA_OFFSET_M)
    assert target == pytest.approx(runtime_dependencies.RBY1M_CHASE_CAMERA_TARGET_OFFSET_M)
    assert horizontal_distance == pytest.approx(vertical_drop)
    assert math.degrees(math.atan2(vertical_drop, horizontal_distance)) == pytest.approx(45.0)
    assert horizontal_distance == pytest.approx(1.0)


def test_isaac_scene_camera_capture_applies_color_profile(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import numpy as np

    monkeypatch.setattr(
        runtime_camera,
        "_ensure_capture_lighting",
        lambda *_args, **_kwargs: {"status": "unit_lighting_skipped"},
    )

    result = runtime_camera._capture_scene_camera_request_with_existing_sim(
        camera_request=_unit_scene_camera_request(),
        output_dir=tmp_path,
        width=6,
        height=4,
        sim=_FakeSceneCameraSim(),
        sim_utils=_FakeSceneCameraSimUtils,
        stage_utils=SimpleNamespace(),
        camera_type=_fake_scene_camera_type(np),
        camera_cfg_type=SimpleNamespace,
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
        runtime_camera,
        "capture_scene_camera_views",
        fake_capture_scene_camera_views,
    )

    result = runtime_commands.write_camera_views(
        runtime_cli.parse_args(
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
        runtime_commands.read_state(state_path),
    )

    assert result["ok"] is True
    assert result["color_profile"]["profile_id"] == "display_srgb_soft_highlight_v1"
    assert result["color_management"]["fpv"]["after"]["overexposed_fraction"] == 0.0
    assert result["native_render_diagnostics"]["schema"] == "isaac_native_render_diagnostics_v1"
    assert result["native_render_diagnostics"]["default_render_settings_changed"] is False


def test_isaac_camera_render_product_paths_are_extracted() -> None:
    camera = SimpleNamespace(
        render_product_path="/Render/Product/Fpv",
        data=SimpleNamespace(render_product_paths=["/Render/Product/Chase"]),
    )

    paths = runtime_dependencies._camera_render_product_paths(camera)

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

    spec = runtime_camera._isaac_scene_camera_view_spec(
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


def test_isaac_head_camera_robot_pose_application_uses_shared_pose(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    translations: list[object] = []
    rotations: list[object] = []
    camera_transforms: list[tuple[str, object]] = []
    _install_robot_pose_pxr(monkeypatch, translations, rotations, camera_transforms)

    result = runtime_camera._position_robot_for_head_camera_view(
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


def test_isaac_chase_pose_uses_robot_relative_camera_follower() -> None:
    pose = {
        "x": 3.008962,
        "y": 4.828715,
        "z": 0.0,
        "theta": math.radians(105.0),
    }

    eye, target = runtime_dependencies._robot_relative_chase_eye_target(pose)

    assert eye == pytest.approx((3.267781, 3.862789, 2.556), abs=1e-6)
    assert target == pytest.approx((3.008962, 4.828715, 1.556), abs=1e-6)


def test_isaac_camera_view_poses_prefers_robot_relative_chase() -> None:
    class _TinyTorch:
        float32 = "float32"

        @staticmethod
        def tensor(values, *, dtype, device):
            return values

    poses = runtime_dependencies._isaac_camera_view_poses(
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
