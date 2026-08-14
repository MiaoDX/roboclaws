from __future__ import annotations

from roboclaws.backends.isaaclab.molmospaces_rendering_parity import (
    COMBINED_MATERIAL_LIGHT_ROTATE_X_DEG,
    _default_rendering_path_status,
    _rendering_parity_preset,
)


def test_combined_material_light_preserves_material_scale_by_default() -> None:
    preset = _rendering_parity_preset("combined-material-light")

    assert preset["material_texture_scale_mode"] == "none"
    assert preset["distant_light_rotate_x"] == COMBINED_MATERIAL_LIGHT_ROTATE_X_DEG
    assert (
        _default_rendering_path_status(
            rendering_parity_preset="combined-material-light",
            material_conversion_summary={
                "mode": "none",
                "texture_scale_rewrite_count": 0,
            },
            light_conversion_summary={
                "rotate_x": COMBINED_MATERIAL_LIGHT_ROTATE_X_DEG,
                "rewrite_count": 0,
                "insert_count": 0,
            },
        )
        == "default_rendering_path_uses_combined_material_light"
    )


def test_combined_material_light_blocks_squared_material_scale_default() -> None:
    assert (
        _default_rendering_path_status(
            rendering_parity_preset="combined-material-light",
            material_conversion_summary={
                "mode": "square",
                "texture_scale_rewrite_count": 2,
            },
            light_conversion_summary={
                "rotate_x": COMBINED_MATERIAL_LIGHT_ROTATE_X_DEG,
                "rewrite_count": 1,
                "insert_count": 0,
            },
        )
        == "default_rendering_path_candidate_incomplete"
    )
