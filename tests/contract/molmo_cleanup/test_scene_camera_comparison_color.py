from __future__ import annotations

from pathlib import Path

import pytest

from roboclaws.household.camera_control import (
    DEFAULT_SCENE_PROBE_COLOR_PROFILE,
    scene_probe_camera_control_request,
)
from roboclaws.household.scene_camera_color_diagnostics import (
    ISAAC_LANE_ID,
    MOLMOSPACES_LANE_ID,
    _candidate_color_calibrations,
    _normalize_color_profile_for_replay,
    _offline_color_profile_replay,
    _render_domain_calibration,
)
from roboclaws.household.scene_camera_image_metrics import (
    image_pair_visual_delta as _image_pair_visual_delta,
)
from roboclaws.household.scene_camera_image_metrics import (
    image_visual_metrics as _image_visual_metrics,
)
from tests.contract.molmo_cleanup.scene_camera_comparison_support import (
    _visual_metric_pair,
    _write_image,
)


def test_scene_camera_visual_metrics_quantify_brightness_delta(tmp_path: Path) -> None:
    dark = tmp_path / "dark.png"
    bright = tmp_path / "bright.png"
    _write_image(dark, color=(10, 20, 30))
    _write_image(bright, color=(110, 120, 130))

    dark_metrics = _image_visual_metrics(dark)
    bright_metrics = _image_visual_metrics(bright)
    delta = _image_pair_visual_delta(dark, bright)

    assert dark_metrics["mean_rgb"] == pytest.approx([10.0, 20.0, 30.0])
    assert bright_metrics["mean_luminance"] > dark_metrics["mean_luminance"]
    assert dark_metrics["overexposed_fraction"] == 0.0
    assert delta["mean_absolute_pixel_delta"] == pytest.approx(100.0)


def test_scene_camera_color_profile_replay_applies_backend_gain(tmp_path: Path) -> None:
    molmo = tmp_path / "molmo.png"
    isaac = tmp_path / "isaac.png"
    _write_image(molmo, color=(100, 100, 100))
    _write_image(isaac, color=(200, 200, 200))

    replay = _offline_color_profile_replay(
        view_id="view_1",
        label="View 1",
        molmo_path=molmo,
        isaac_path=isaac,
        color_profile={
            "profile_id": "display_srgb_soft_highlight_v1",
            "highlight_knee": 225.0,
            "highlight_compression": 0.55,
            "gamma": 1.0,
            "backend_luminance_gain": {
                MOLMOSPACES_LANE_ID: 1.0,
                ISAAC_LANE_ID: 0.5,
            },
        },
    )

    assert replay["lanes"][MOLMOSPACES_LANE_ID]["mean_luminance"] == pytest.approx(100.0)
    assert replay["lanes"][ISAAC_LANE_ID]["mean_luminance"] == pytest.approx(100.0)
    assert replay["delta"]["mean_luminance_delta"] == pytest.approx(0.0)
    assert (tmp_path / "isaac.color_profile_replay.png").is_file()


def test_scene_camera_color_profile_replay_prefers_view_gain(tmp_path: Path) -> None:
    molmo = tmp_path / "molmo.png"
    isaac = tmp_path / "isaac.png"
    _write_image(molmo, color=(100, 100, 100))
    _write_image(isaac, color=(200, 200, 200))

    replay = _offline_color_profile_replay(
        view_id="room_02_room_3",
        label="Room 3",
        molmo_path=molmo,
        isaac_path=isaac,
        color_profile={
            "profile_id": "display_srgb_soft_highlight_v1",
            "backend_luminance_gain": {
                MOLMOSPACES_LANE_ID: 1.0,
                ISAAC_LANE_ID: 0.5,
            },
            "backend_view_luminance_gain": {ISAAC_LANE_ID: {"room_02_room_3": 0.25}},
        },
    )

    assert replay["lanes"][ISAAC_LANE_ID]["mean_luminance"] == pytest.approx(50.0)
    assert replay["delta"]["mean_luminance_delta"] == pytest.approx(-50.0)


def test_scene_camera_color_profile_replay_prefers_view_rgb_gain(tmp_path: Path) -> None:
    molmo = tmp_path / "molmo.png"
    isaac = tmp_path / "isaac.png"
    _write_image(molmo, color=(100, 100, 100))
    _write_image(isaac, color=(200, 200, 200))

    replay = _offline_color_profile_replay(
        view_id="room_02_room_3",
        label="Room 3",
        molmo_path=molmo,
        isaac_path=isaac,
        color_profile={
            "profile_id": "display_srgb_soft_highlight_v1",
            "backend_rgb_gain": {ISAAC_LANE_ID: [1.0, 1.0, 1.0]},
            "backend_view_rgb_gain": {ISAAC_LANE_ID: {"room_02_room_3": [0.5, 0.25, 0.1]}},
        },
    )

    assert replay["lanes"][ISAAC_LANE_ID]["mean_rgb"] == pytest.approx([100.0, 50.0, 20.0])
    assert replay["delta"]["mean_absolute_pixel_delta"] == pytest.approx(43.333333333333336)


def test_scene_camera_color_profile_replay_normalizes_legacy_profile() -> None:
    profile = _normalize_color_profile_for_replay({"profile_id": "display_srgb_soft_highlight_v1"})

    assert profile["backend_luminance_gain"][MOLMOSPACES_LANE_ID] == pytest.approx(1.0)
    assert profile["backend_luminance_gain"][ISAAC_LANE_ID] == pytest.approx(0.7161647108631373)


def test_scene_camera_color_profile_replay_normalizes_view_gain() -> None:
    profile = _normalize_color_profile_for_replay(
        {
            "profile_id": "display_srgb_soft_highlight_v1",
            "backend_view_luminance_gain": {
                ISAAC_LANE_ID: {"room_02_room_3": "0.25", "bad": "not-a-float"}
            },
            "backend_view_luminance_gain_source": "unit",
        }
    )

    assert profile["backend_view_luminance_gain"][ISAAC_LANE_ID]["room_02_room_3"] == (
        pytest.approx(0.25)
    )
    assert "bad" not in profile["backend_view_luminance_gain"][ISAAC_LANE_ID]
    assert profile["backend_view_luminance_gain_source"] == "unit"


def test_scene_camera_color_profile_replay_normalizes_rgb_gain() -> None:
    profile = _normalize_color_profile_for_replay(
        {
            "profile_id": "display_srgb_soft_highlight_v1",
            "backend_rgb_gain": {ISAAC_LANE_ID: ["0.5", "0.25", "0.1"]},
            "backend_view_rgb_gain": {
                ISAAC_LANE_ID: {
                    "room_02_room_3": ["0.4", "0.3", "0.2"],
                    "bad": ["not-a-float", "0.3", "0.2"],
                }
            },
            "backend_view_rgb_gain_source": "unit-rgb",
        }
    )

    assert profile["backend_rgb_gain"][ISAAC_LANE_ID] == pytest.approx([0.5, 0.25, 0.1])
    assert profile["backend_view_rgb_gain"][ISAAC_LANE_ID]["room_02_room_3"] == pytest.approx(
        [0.4, 0.3, 0.2]
    )
    assert "bad" not in profile["backend_view_rgb_gain"][ISAAC_LANE_ID]
    assert profile["backend_view_rgb_gain_source"] == "unit-rgb"


def test_scene_camera_candidate_color_calibrations_compare_gain_strategies(
    tmp_path: Path,
) -> None:
    molmo = tmp_path / "molmo.png"
    isaac = tmp_path / "isaac.png"
    _write_image(molmo, color=(100, 100, 100))
    _write_image(isaac, color=(200, 160, 120))
    view_results = [
        {
            "view_id": "view_1",
            "label": "View 1",
            "lanes": {
                MOLMOSPACES_LANE_ID: _image_visual_metrics(molmo),
                ISAAC_LANE_ID: _image_visual_metrics(isaac),
            },
            "delta": _image_pair_visual_delta(molmo, isaac),
        }
    ]
    summary = _candidate_color_calibrations(
        view_results,
        entries=[
            {
                "view_id": "view_1",
                "label": "View 1",
                "images": {MOLMOSPACES_LANE_ID: molmo, ISAAC_LANE_ID: isaac},
            }
        ],
        base_color_profile={
            "profile_id": "display_srgb_soft_highlight_v1",
            "backend_luminance_gain": {MOLMOSPACES_LANE_ID: 1.0, ISAAC_LANE_ID: 1.0},
        },
    )

    candidates = {item["candidate_id"]: item for item in summary["candidates"]}
    assert summary["best_candidate"] in candidates
    assert candidates["current_profile"]["mean_absolute_pixel_delta"] > 0.0
    assert candidates["ideal_per_view_luminance_gain"]["mean_absolute_pixel_delta"] > 0.0
    assert candidates["ideal_per_view_rgb_gain"]["gain_delta"]["backend_view_rgb_gain"][
        ISAAC_LANE_ID
    ]["view_1"] == pytest.approx([0.5, 0.625, 0.8333333333333334])
    assert candidates["ideal_per_view_rgb_gain"]["gain_delta"]["backend_view_luminance_gain"][
        ISAAC_LANE_ID
    ]["view_1"] == pytest.approx(1.0)


def test_scene_camera_render_domain_calibration_detects_global_gain() -> None:
    calibration = _render_domain_calibration(
        [
            _visual_metric_pair("view_1", molmo_luminance=50.0, isaac_luminance=100.0),
            _visual_metric_pair("view_2", molmo_luminance=100.0, isaac_luminance=200.0),
        ]
    )

    assert calibration["status"] == "global_luminance_gain_sufficient"
    assert calibration["global_isaac_luminance_gain"] == pytest.approx(0.5)
    assert calibration["mean_abs_calibrated_luminance_residual"] == pytest.approx(0.0)


def test_scene_camera_render_domain_calibration_flags_view_dependent_delta() -> None:
    calibration = _render_domain_calibration(
        [
            _visual_metric_pair("view_1", molmo_luminance=50.0, isaac_luminance=100.0),
            _visual_metric_pair("view_2", molmo_luminance=180.0, isaac_luminance=200.0),
        ]
    )

    assert calibration["status"] == "view_dependent_render_domain_delta"
    assert calibration["mean_abs_calibrated_luminance_residual"] > 12.0
    assert "material" in calibration["recommended_next_action"]


def test_scene_camera_comparison_default_color_profile_contract() -> None:
    assert DEFAULT_SCENE_PROBE_COLOR_PROFILE["profile_id"] == "display_srgb_soft_highlight_v1"
    assert DEFAULT_SCENE_PROBE_COLOR_PROFILE["highlight_knee"] == 225.0
    assert DEFAULT_SCENE_PROBE_COLOR_PROFILE["highlight_compression"] == 0.55
    assert DEFAULT_SCENE_PROBE_COLOR_PROFILE["backend_luminance_gain"][
        "molmospaces-mujoco"
    ] == pytest.approx(1.0)
    assert DEFAULT_SCENE_PROBE_COLOR_PROFILE["backend_luminance_gain"][
        "isaaclab-prepared-usd"
    ] == pytest.approx(0.7161647108631373)
    assert "0530_0009" in DEFAULT_SCENE_PROBE_COLOR_PROFILE["backend_luminance_gain_source"]


def test_scene_camera_color_profile_normalizes_backend_tone_adjustment() -> None:
    request = scene_probe_camera_control_request(
        [{"view_id": "room_01", "target": [0.0, 0.0, 0.0]}],
        width=64,
        height=48,
        color_profile={
            "backend_tone_adjustment": {
                "unit-test-renderer": {
                    "shadow_lift": 8,
                    "shadow_floor": 135,
                    "gamma": 1.1,
                    "saturation": 1.0,
                    "gain": 1.2,
                }
            },
            "backend_tone_adjustment_source": "unit-tone",
        },
    )

    assert request["color_profile"]["backend_tone_adjustment"]["unit-test-renderer"] == {
        "shadow_lift": pytest.approx(8.0),
        "shadow_floor": pytest.approx(135.0),
        "gamma": pytest.approx(1.1),
        "saturation": pytest.approx(1.0),
        "gain": pytest.approx(1.2),
    }
    assert request["color_profile"]["backend_tone_adjustment_source"] == "unit-tone"
