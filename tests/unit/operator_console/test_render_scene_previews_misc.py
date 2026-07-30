from __future__ import annotations

import pytest

from scripts.operator_console.render_scene_previews import (
    _first_public_waypoint,
    _scene_alignment,
    _scene_center_and_span,
)


def test_preview_helpers_use_first_public_waypoint_and_scene_bounds() -> None:
    waypoint = _first_public_waypoint(
        {"inspection_waypoints": [{"waypoint_id": "first"}, {"waypoint_id": "second"}]}
    )
    center, span = _scene_center_and_span(
        {"room_outlines": [{"center": [2.0, 3.0], "half_extents": [1.0, 2.0]}]}
    )

    assert waypoint["waypoint_id"] == "first"
    assert center == pytest.approx([2.0, 3.0, 0.4])
    assert span >= 4.0


def test_scene_alignment_expands_bounds_to_preview_aspect() -> None:
    alignment = _scene_alignment(
        {"room_outlines": [{"center": [2.0, 3.0], "half_extents": [1.0, 2.0]}]},
        width=900,
        height=560,
    )

    assert alignment["schema"] == "operator_console_scene_alignment_v1"
    assert (
        alignment["screen_coordinate_convention"]
        == "screen_x_world_positive_x_screen_y_world_negative_y"
    )
    assert alignment["topdown_azimuth_deg"] == pytest.approx(90.0)
    assert alignment["span_x_m"] / alignment["span_y_m"] == pytest.approx(900 / 560)
