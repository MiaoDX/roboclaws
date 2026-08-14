"""Isaac Lab backend runtime support."""

from __future__ import annotations

import json
import math
from typing import Any

from roboclaws.household.robot_view_camera_control import robot_view_display_color_profile

ISAAC_RBY1M_HEAD_CAMERA_PRIM = "/World/robot_0/head_camera"
RBY1M_HEAD_PITCH_PIVOT_M = (0.022, 0.0, 1.506)
RBY1M_HEAD_CAMERA_ZERO_POSITION_M = (0.072, 0.0, 1.556)
RBY1M_HEAD_CAMERA_ZERO_QUAT_WXYZ = (-0.5, -0.5, 0.5, 0.5)
RBY1M_HEAD_CAMERA_VERTICAL_FOV_DEG = 45.0
RBY1M_HEAD_CAMERA_FOCAL_LENGTH_MM = 24.0
RBY1M_CHASE_CAMERA_OFFSET_M = (-1.0, 0.0, 2.556)
RBY1M_CHASE_CAMERA_TARGET_OFFSET_M = (0.0, 0.0, 1.556)


def robot_view_color_profile(override: dict[str, Any] | None = None) -> dict[str, Any]:
    profile = json.loads(json.dumps(robot_view_display_color_profile()))
    luminance_gain = _dict(profile.get("backend_luminance_gain"))
    luminance_gain["isaaclab_subprocess"] = 1.0
    luminance_gain["isaaclab-prepared-usd"] = 1.0
    profile["backend_luminance_gain"] = luminance_gain
    profile["backend_luminance_gain_source"] = "robot_view_display_default_no_scene_probe_delta"
    if isinstance(override, dict) and override:
        profile.update(override)
    return profile


def isaac_camera_view_poses(
    *,
    torch: Any,
    device: Any,
    scene_bounds: dict[str, list[float]] | None = None,
    semantic_pose_state: dict[str, Any] | None = None,
) -> dict[str, tuple[Any, Any]]:
    def tensor(values: list[list[float]]) -> Any:
        return torch.tensor(values, dtype=torch.float32, device=device)

    pose = _dict(_dict(semantic_pose_state).get("robot_pose"))
    if scene_bounds:
        center = scene_bounds["center"]
        size = scene_bounds["size"]
        span_x = max(size[0], 1.5)
        span_y = max(size[1], 1.5)
        span = max(span_x, span_y, size[2], 2.0)
        floor_z = scene_bounds["min"][2]
        target_z = max(floor_z + 0.9, center[2])
        target = [center[0], center[1], target_z]
        chase_eye_target = robot_relative_chase_eye_target(pose)
        chase_pose = (
            (tensor([[*chase_eye_target[0]]]), tensor([[*chase_eye_target[1]]]))
            if chase_eye_target is not None
            else (
                tensor([[center[0] + span_x * 0.55, center[1] - span_y * 0.75, floor_z + 2.4]]),
                tensor([[center[0], center[1], target_z * 0.9]]),
            )
        )
        return {
            "fpv": (
                tensor([[center[0] - span_x * 0.35, center[1] - span_y * 0.55, floor_z + 1.25]]),
                tensor([target]),
            ),
            "chase": chase_pose,
            "topdown": (
                tensor([[center[0], center[1], scene_bounds["max"][2] + span * 1.25]]),
                tensor([[center[0], center[1], floor_z]]),
            ),
            "verify": (
                tensor([[center[0] - span_x * 0.18, center[1] - span_y * 0.35, floor_z + 1.6]]),
                tensor([[center[0] + span_x * 0.08, center[1] + span_y * 0.05, target_z]]),
            ),
        }

    chase_eye_target = robot_relative_chase_eye_target(pose)
    chase_pose = (
        (tensor([[*chase_eye_target[0]]]), tensor([[*chase_eye_target[1]]]))
        if chase_eye_target is not None
        else (tensor([[2.4, -2.6, 1.8]]), tensor([[0.0, 0.0, 0.35]]))
    )
    return {
        "fpv": (tensor([[1.35, -1.35, 1.1]]), tensor([[0.05, 0.0, 0.55]])),
        "chase": chase_pose,
        "topdown": (tensor([[0.05, -0.05, 4.2]]), tensor([[0.0, 0.0, 0.0]])),
        "verify": (tensor([[0.9, -1.0, 0.85]]), tensor([[0.2, -0.15, 0.55]])),
    }


def robot_relative_chase_eye_target(
    pose: dict[str, Any],
) -> tuple[tuple[float, float, float], tuple[float, float, float]] | None:
    if not _has_xy(pose):
        return None
    yaw_deg = robot_pose_yaw_deg(pose)
    if yaw_deg is None:
        return None
    yaw = math.radians(float(yaw_deg))
    cos_yaw = math.cos(yaw)
    sin_yaw = math.sin(yaw)

    def transform(offset: tuple[float, float, float]) -> tuple[float, float, float]:
        return (
            float(pose["x"]) + offset[0] * cos_yaw - offset[1] * sin_yaw,
            float(pose["y"]) + offset[0] * sin_yaw + offset[1] * cos_yaw,
            float(pose.get("z", 0.0)) + offset[2],
        )

    return (
        transform(RBY1M_CHASE_CAMERA_OFFSET_M),
        transform(RBY1M_CHASE_CAMERA_TARGET_OFFSET_M),
    )


def static_head_camera_pose_for_pitch(
    head_pitch: float,
) -> tuple[tuple[float, float, float], tuple[float, float, float, float]]:
    position = rotate_point_y_about_pivot(
        RBY1M_HEAD_CAMERA_ZERO_POSITION_M,
        pivot=RBY1M_HEAD_PITCH_PIVOT_M,
        angle_rad=head_pitch,
    )
    pitch_quat = quat_from_axis_angle((0.0, 1.0, 0.0), head_pitch)
    quat = quat_multiply(pitch_quat, RBY1M_HEAD_CAMERA_ZERO_QUAT_WXYZ)
    return position, quat


def rotate_point_y_about_pivot(
    point: tuple[float, float, float],
    *,
    pivot: tuple[float, float, float],
    angle_rad: float,
) -> tuple[float, float, float]:
    dx = point[0] - pivot[0]
    dy = point[1] - pivot[1]
    dz = point[2] - pivot[2]
    cos_pitch = math.cos(angle_rad)
    sin_pitch = math.sin(angle_rad)
    return (
        pivot[0] + cos_pitch * dx + sin_pitch * dz,
        pivot[1] + dy,
        pivot[2] - sin_pitch * dx + cos_pitch * dz,
    )


def quat_from_axis_angle(
    axis: tuple[float, float, float],
    angle_rad: float,
) -> tuple[float, float, float, float]:
    norm = math.sqrt(sum(float(value) * float(value) for value in axis))
    if norm <= 0.0:
        return (1.0, 0.0, 0.0, 0.0)
    half = angle_rad * 0.5
    scale = math.sin(half) / norm
    return normalize_quat(
        (
            math.cos(half),
            float(axis[0]) * scale,
            float(axis[1]) * scale,
            float(axis[2]) * scale,
        )
    )


def quat_multiply(
    left: tuple[float, float, float, float],
    right: tuple[float, float, float, float],
) -> tuple[float, float, float, float]:
    lw, lx, ly, lz = left
    rw, rx, ry, rz = right
    return normalize_quat(
        (
            lw * rw - lx * rx - ly * ry - lz * rz,
            lw * rx + lx * rw + ly * rz - lz * ry,
            lw * ry - lx * rz + ly * rw + lz * rx,
            lw * rz + lx * ry - ly * rx + lz * rw,
        )
    )


def normalize_quat(
    quat: tuple[float, float, float, float],
) -> tuple[float, float, float, float]:
    norm = math.sqrt(sum(value * value for value in quat))
    if norm <= 0.0:
        return (1.0, 0.0, 0.0, 0.0)
    return tuple(float(value / norm) for value in quat)  # type: ignore[return-value]


def usd_camera_fov_metadata(
    *,
    focal_length: float | None,
    horizontal_aperture: float | None,
    width: int,
    height: int,
) -> dict[str, float]:
    if focal_length is None or horizontal_aperture is None or width <= 0 or height <= 0:
        return {}
    horizontal_fov = math.degrees(
        2.0 * math.atan(float(horizontal_aperture) / (2.0 * focal_length))
    )
    vertical_aperture = float(horizontal_aperture) * float(height) / float(width)
    vertical_fov = math.degrees(2.0 * math.atan(vertical_aperture / (2.0 * focal_length)))
    return {
        "vertical_aperture_mm": round(vertical_aperture, 6),
        "vertical_fov_deg": round(vertical_fov, 6),
        "horizontal_fov_deg": round(horizontal_fov, 6),
    }


def matrix4d_rowmajor(matrix: Any) -> list[float]:
    return [round(float(matrix[row][column]), 6) for row in range(4) for column in range(4)]


def usd_attr_float(attr: Any) -> float | None:
    if not attr:
        return None
    value = attr.Get()
    if value is None:
        return None
    return round(float(value), 6)


def usd_vec(attr: Any) -> list[float] | None:
    if not attr:
        return None
    value = attr.Get()
    if value is None:
        return None
    try:
        return [round(float(item), 6) for item in value]
    except TypeError:
        return None


def tensor_first_vec3(value: Any) -> list[float]:
    if hasattr(value, "detach"):
        value = value.detach()
    if hasattr(value, "cpu"):
        value = value.cpu()
    if hasattr(value, "tolist"):
        value = value.tolist()
    if isinstance(value, list) and value and isinstance(value[0], list):
        value = value[0]
    if not isinstance(value, list | tuple) or len(value) < 3:
        return []
    return [round(float(value[index]), 6) for index in range(3)]


def robot_pose_yaw_deg(pose: dict[str, Any]) -> float | None:
    if not isinstance(pose, dict):
        return None
    try:
        if "theta" in pose:
            return round(math.degrees(float(pose["theta"])), 6)
        if "yaw_deg" in pose:
            return round(float(pose["yaw_deg"]), 6)
    except (TypeError, ValueError):
        return None
    return None


def optional_float(value: Any) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def horizontal_aperture_from_lens(
    lens: dict[str, Any],
    *,
    width: int,
    height: int,
    focal_length: float,
) -> float:
    if "vertical_fov_deg" in lens:
        vertical_fov_rad = math.radians(float(lens["vertical_fov_deg"]))
        vertical_aperture = 2.0 * focal_length * math.tan(vertical_fov_rad / 2.0)
        return vertical_aperture * float(width) / float(height)
    return float(lens.get("horizontal_aperture_mm", 20.955))


def _has_xy(value: dict[str, Any]) -> bool:
    try:
        float(value["x"])
        float(value["y"])
        return True
    except (KeyError, TypeError, ValueError):
        return False


def _dict(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}
