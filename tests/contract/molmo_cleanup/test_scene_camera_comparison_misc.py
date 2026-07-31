from __future__ import annotations

from roboclaws.household.scene_camera_lighting_diagnostics import (
    native_isaac_render_diagnostics as _native_isaac_render_diagnostics,
)
from tests.contract.molmo_cleanup.scene_camera_comparison_support import (
    _manifest,
)


def test_scene_camera_native_isaac_render_diagnostics_are_summarized() -> None:
    manifest = _manifest()

    diagnostics = _native_isaac_render_diagnostics(manifest)

    assert diagnostics["status"] == "native_settings_recorded"
    assert diagnostics["native_settings_recorded"] is True
    assert diagnostics["default_render_settings_changed"] is False
    assert diagnostics["settings_api_available"] is True
    assert diagnostics["camera_prim_paths"] == ["/World/scene_camera"]
    assert diagnostics["render_product_paths"] == ["/Render/Products/scene_camera"]
    assert diagnostics["post_render_comparison_profile"]["source"] == (
        "not_a_native_renderer_setting"
    )
    assert diagnostics["tone_mapping"]["operator"] == {
        "status": "available",
        "value": "ACES",
        "setting_path": "/rtx/post/tonemap/op",
    }
    assert diagnostics["camera_exposure"]["auto_exposure_enabled"] == {
        "status": "available",
        "value": False,
        "setting_path": "/rtx/post/tonemap/autoExposure/enabled",
    }
