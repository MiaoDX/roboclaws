from __future__ import annotations

import json
import sys
import types
from pathlib import Path

import pytest

from roboclaws.backends.isaaclab import isaac_runtime_diagnostics
from roboclaws.backends.isaaclab import runtime_camera as runtime_camera
from roboclaws.backends.isaaclab import runtime_capture as runtime_capture
from roboclaws.backends.isaaclab import runtime_commands as runtime_commands
from roboclaws.backends.isaaclab import runtime_dependencies as runtime_dependencies
from roboclaws.backends.isaaclab import runtime_evidence as runtime_evidence
from roboclaws.backends.isaaclab import runtime_initialization as runtime_initialization
from roboclaws.backends.isaaclab import runtime_state as runtime_state
from roboclaws.household.b1_nurec_scene import prepare_b1_nurec_scene_usd
from roboclaws.household.isaac_lab_backend import (
    IsaacLabSubprocessBackend,
)
from tests.unit.molmo_cleanup.isaac_lab_backend_support import (
    _write_b1_scene_gs_fixture,
)


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


def test_isaac_runtime_diagnostics_reads_binary_image_versions(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    (tmp_path / "docs" / "py").mkdir(parents=True)
    (tmp_path / "docs" / "py" / "VERSION").write_text("6.0.0\n", encoding="utf-8")
    (tmp_path / "VERSION").write_text(
        "6.0.0-rc.59+release.41464.5f2772bc.gl\n",
        encoding="utf-8",
    )
    monkeypatch.setenv("ISAACSIM_ROOT_PATH", str(tmp_path))
    monkeypatch.setitem(sys.modules, "isaacsim", types.ModuleType("isaacsim"))

    assert isaac_runtime_diagnostics.module_version("isaacsim") == "6.0.0"
    assert (
        isaac_runtime_diagnostics.isaac_sim_build_version()
        == "6.0.0-rc.59+release.41464.5f2772bc.gl"
    )


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


def test_isaac_robot_view_color_profile_merges_comparison_override() -> None:
    profile = runtime_dependencies._robot_view_color_profile(
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
        runtime_evidence,
        "_isaac_settings_interface",
        lambda: _FakeSettings(),
    )

    diagnostics = runtime_evidence._isaac_native_render_diagnostics(
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

    mutation = runtime_evidence._apply_isaac_capture_quality_overrides(
        settings=settings,
        isaac_aa_op=2,
        isaac_tonemap_op=None,
    )
    capture_quality = runtime_dependencies._capture_quality_settings(
        render_settle_frames=0,
        settings=settings,
        settings_mutation=mutation,
    )
    restored = runtime_dependencies._restore_isaac_capture_quality_overrides(
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

    mutation = runtime_evidence._apply_isaac_capture_quality_overrides(
        settings=settings,
        isaac_aa_op=None,
        isaac_tonemap_op=5,
    )
    capture_quality = runtime_dependencies._capture_quality_settings(
        render_settle_frames=0,
        settings=settings,
        settings_mutation=mutation,
    )
    restored = runtime_dependencies._restore_isaac_capture_quality_overrides(
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

    mutation = runtime_evidence._apply_isaac_capture_quality_overrides(
        settings=settings,
        isaac_aa_op=None,
        isaac_tonemap_op=None,
        isaac_exposure_bias=-1.0,
    )
    capture_quality = runtime_dependencies._capture_quality_settings(
        render_settle_frames=0,
        settings=settings,
        settings_mutation=mutation,
    )
    restored = runtime_dependencies._restore_isaac_capture_quality_overrides(
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

    mutation = runtime_evidence._apply_isaac_capture_quality_overrides(
        settings=settings,
        isaac_aa_op=None,
        isaac_tonemap_op=None,
        isaac_exposure_bias=None,
        isaac_colorcorr_gain=(0.9, 0.8, 0.7),
    )
    capture_quality = runtime_dependencies._capture_quality_settings(
        render_settle_frames=0,
        settings=settings,
        settings_mutation=mutation,
    )
    restored = runtime_dependencies._restore_isaac_capture_quality_overrides(
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
