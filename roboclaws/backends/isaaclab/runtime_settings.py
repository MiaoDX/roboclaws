"""Stable configuration shared by the Isaac worker runtime owners."""

STATE_SCHEMA = "isaac_lab_backend_state_v1"

DEFAULT_WIDTH = 540
DEFAULT_HEIGHT = 360

ROBOT_VIEW_KEYS = ("fpv", "chase", "topdown", "verify")

REAL_SMOKE_CAPTURE_METHOD = "isaac_lab_camera_rgb"
REAL_ROBOT_VIEW_CAPTURE_METHOD = "isaac_lab_camera_rgb_static_robot_views"
REAL_ROBOT_VIEW_RERENDER_METHOD = "isaac_lab_camera_rgb_semantic_pose_robot_views"
REAL_SMOKE_RENDERER_MODE = "isaac_lab_headless_rtx"
