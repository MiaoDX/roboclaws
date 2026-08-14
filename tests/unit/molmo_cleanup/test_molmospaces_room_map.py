from __future__ import annotations

import pytest

pytest.importorskip("mujoco")

from roboclaws.backends.molmospaces.room_map import (  # noqa: E402
    MANUAL_ADJUSTMENT_COLOR,
    ROBOT_PATH_COLOR,
    render_robot_map,
)


def test_robot_map_uses_distinct_color_for_manual_adjustment_waypoints() -> None:
    state = {
        "room_outlines": [
            {
                "room_id": "room_1",
                "label": "Kitchen",
                "center": [1.0, 1.0],
                "half_extents": [1.0, 1.0],
            }
        ],
        "receptacles": {"sink_01": {"position": [0.2, 0.4]}},
        "objects": {},
        "selected_object_ids": [],
        "robot_trajectory": [
            {"x": 0.0, "y": 0.0, "theta": 0.0, "pose_source": "public_waypoint"},
            {
                "x": 1.0,
                "y": 1.0,
                "theta": 0.2,
                "pose_source": "relative_robot_frame",
                "relative_pose_delta": {"forward_m": 0.0, "lateral_m": 0.25, "yaw_delta_deg": 0.0},
            },
            {"x": 1.8, "y": 1.2, "theta": 0.3, "pose_source": "public_waypoint"},
        ],
    }

    image = render_robot_map(state)
    colors = set(image.getdata())

    assert ROBOT_PATH_COLOR in colors
    assert MANUAL_ADJUSTMENT_COLOR in colors
