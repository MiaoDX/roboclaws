from __future__ import annotations

import math
from typing import Any

from roboclaws.household import scene_camera_render_domain
from roboclaws.household.camera_control import (
    CANONICAL_CAMERA_MODEL,
    MOLMOSPACES_SCENE_FRAME,
)
from roboclaws.household.scene_camera_render_diagnostics import room_scale_contract_from_capture

CANONICAL_POSE_PARITY_THRESHOLD_M = 0.08
CANONICAL_CAMERA_POSE_THRESHOLD_M = 0.005
CANONICAL_CAMERA_PROJECTION_THRESHOLD_PX = (
    scene_camera_render_domain.CANONICAL_CAMERA_PROJECTION_THRESHOLD_PX
)
CANONICAL_ROOM_OUTLINE_THRESHOLD_M = 0.005
SURFACE_AIM_HEIGHT_ALLOWANCE_M = 0.3
ROOM_CAMERA_HEIGHT_M = 1.45
ISAAC_LANE_ID = scene_camera_render_domain.ISAAC_LANE_ID


def identity_scene_frame_transform() -> dict[str, Any]:
    return {
        "schema": "molmospaces_to_isaac_scene_transform_v1",
        "source_frame": MOLMOSPACES_SCENE_FRAME,
        "target_frame": "isaac_prepared_usd_world_frame",
        "status": "identity_pending_render_diagnostics",
        "parity_status": "pending_render_diagnostics",
        "pair_count": 0,
        "xy_scale": 1.0,
        "rotation_z_deg": 0.0,
        "translation": [0.0, 0.0, 0.0],
        "residual_threshold_m": CANONICAL_POSE_PARITY_THRESHOLD_M,
        "pairs": [],
    }


def scene_frame_transform_from_capture(
    *,
    canonical_views: list[dict[str, Any]],
    isaac_lane: dict[str, Any],
) -> dict[str, Any]:
    views = {
        str(item.get("view_id") or ""): item
        for item in isaac_lane.get("views") or []
        if isinstance(item, dict)
    }
    pairs = []
    for request_view in canonical_views:
        view_id = str(request_view.get("view_id") or "")
        captured = views.get(view_id, {})
        target = captured.get("usd_bounds_target")
        bounds = captured.get("usd_bounds") if isinstance(captured.get("usd_bounds"), dict) else {}
        source = request_view.get("target")
        if not is_vec3(source) or not is_vec3(target):
            continue
        bounds_distance = _distance_to_axis_aligned_bounds(source, bounds)
        inside_xy = _point_inside_xy_bounds(source, bounds)
        inside_xyz = _point_inside_xyz_bounds(source, bounds)
        surface_aim_distance = _surface_aim_distance_to_bounds(
            source,
            bounds,
            allowance_m=SURFACE_AIM_HEIGHT_ALLOWANCE_M,
        )
        pairs.append(
            {
                "anchor_id": request_view.get("anchor_id"),
                "category": request_view.get("category"),
                "source": [float(value) for value in source[:3]],
                "target": [float(value) for value in target[:3]],
                "usd_bounds_min": _bounds_vec(bounds, "min"),
                "usd_bounds_max": _bounds_vec(bounds, "max"),
                "usd_bounds_center": _bounds_vec(bounds, "center"),
                "distance_to_usd_bounds_m": bounds_distance,
                "surface_aim_distance_to_usd_bounds_m": surface_aim_distance,
                "target_inside_usd_xy_bounds": inside_xy,
                "target_inside_usd_xyz_bounds": inside_xyz,
            }
        )
    if not pairs:
        transform = identity_scene_frame_transform()
        transform["status"] = "missing_render_diagnostics"
        transform["parity_status"] = "not_proven"
        transform["diagnostic_kind"] = "camera_target_vs_isaac_usd_bounds"
        transform["interpretation"] = (
            "No Isaac USD-bounds diagnostics were captured; this does not prove or disprove "
            "camera pose parity."
        )
        return transform
    residuals = []
    for item in pairs:
        xy_residual = math.hypot(
            float(item["source"][0]) - float(item["target"][0]),
            float(item["source"][1]) - float(item["target"][1]),
        )
        z_residual = abs(float(item["source"][2]) - float(item["target"][2]))
        residuals.append(
            {
                **item,
                "fitted": [float(value) for value in item["source"]],
                "residual_m": _distance_3d(item["source"], item["target"]),
                "xy_residual_m": xy_residual,
                "z_residual_m": z_residual,
            }
        )
    residual_values = [float(item["residual_m"]) for item in residuals]
    xy_residual_values = [float(item["xy_residual_m"]) for item in residuals]
    z_residual_values = [float(item["z_residual_m"]) for item in residuals]
    bounds_distance_values = [
        float(item["distance_to_usd_bounds_m"])
        for item in residuals
        if item.get("distance_to_usd_bounds_m") is not None
    ]
    surface_aim_distance_values = [
        float(item["surface_aim_distance_to_usd_bounds_m"])
        for item in residuals
        if item.get("surface_aim_distance_to_usd_bounds_m") is not None
    ]
    xy_inside_count = sum(1 for item in residuals if item.get("target_inside_usd_xy_bounds"))
    xyz_inside_count = sum(1 for item in residuals if item.get("target_inside_usd_xyz_bounds"))
    max_residual = max(residual_values)
    mean_residual = sum(residual_values) / len(residual_values)
    max_xy_residual = max(xy_residual_values)
    mean_xy_residual = sum(xy_residual_values) / len(xy_residual_values)
    max_z_residual = max(z_residual_values)
    mean_z_residual = sum(z_residual_values) / len(z_residual_values)
    max_bounds_distance = max(bounds_distance_values) if bounds_distance_values else None
    mean_bounds_distance = (
        sum(bounds_distance_values) / len(bounds_distance_values)
        if bounds_distance_values
        else None
    )
    max_surface_aim_distance = (
        max(surface_aim_distance_values) if surface_aim_distance_values else None
    )
    mean_surface_aim_distance = (
        sum(surface_aim_distance_values) / len(surface_aim_distance_values)
        if surface_aim_distance_values
        else None
    )
    target_residual_status = (
        "target_inside_or_near_usd_bounds_with_surface_aim_allowance"
        if max_surface_aim_distance is not None
        and max_surface_aim_distance <= CANONICAL_POSE_PARITY_THRESHOLD_M
        else "target_inside_or_near_usd_bounds"
        if max_bounds_distance is not None
        and max_bounds_distance <= CANONICAL_POSE_PARITY_THRESHOLD_M
        else "target_matches_usd_bounds_center_within_threshold"
        if max_residual <= CANONICAL_POSE_PARITY_THRESHOLD_M
        else "target_definition_residual_high"
    )
    return {
        "schema": "molmospaces_to_isaac_scene_transform_v1",
        "source_frame": MOLMOSPACES_SCENE_FRAME,
        "target_frame": "isaac_prepared_usd_world_frame",
        "diagnostic_kind": "camera_target_vs_isaac_usd_bounds",
        "status": "identity_checked_against_usd_bounds",
        "parity_status": target_residual_status,
        "target_residual_status": target_residual_status,
        "interpretation": (
            "This diagnostic compares the requested canonical camera target with the matched "
            "Isaac USD prim bounds. Distance-to-bounds is the primary geometry check because "
            "large receptacles often use a surface aim point, not the object bounding-box "
            "center. Center residuals are retained as context and are not backend camera-pose "
            "residuals."
        ),
        "pair_count": len(pairs),
        "xy_scale": 1.0,
        "rotation_z_deg": 0.0,
        "translation": [0.0, 0.0, 0.0],
        "residual_threshold_m": CANONICAL_POSE_PARITY_THRESHOLD_M,
        "mean_residual_m": mean_residual,
        "max_residual_m": max_residual,
        "mean_xy_residual_m": mean_xy_residual,
        "max_xy_residual_m": max_xy_residual,
        "mean_z_residual_m": mean_z_residual,
        "max_z_residual_m": max_z_residual,
        "mean_distance_to_usd_bounds_m": mean_bounds_distance,
        "max_distance_to_usd_bounds_m": max_bounds_distance,
        "mean_surface_aim_distance_to_usd_bounds_m": mean_surface_aim_distance,
        "max_surface_aim_distance_to_usd_bounds_m": max_surface_aim_distance,
        "surface_aim_height_allowance_m": SURFACE_AIM_HEIGHT_ALLOWANCE_M,
        "target_inside_usd_xy_bounds_count": xy_inside_count,
        "target_inside_usd_xyz_bounds_count": xyz_inside_count,
        "pairs": residuals,
    }


def camera_pose_contract_from_capture(
    *,
    canonical_views: list[dict[str, Any]],
    molmospaces_lane: dict[str, Any],
    isaac_lane: dict[str, Any],
) -> dict[str, Any]:
    request_views = {
        str(item.get("view_id") or ""): item for item in canonical_views if isinstance(item, dict)
    }
    molmo_views = _views_by_id(molmospaces_lane)
    isaac_views = _views_by_id(isaac_lane)
    pairs: list[dict[str, Any]] = []
    for view_id, request_view in request_views.items():
        requested_eye = request_view.get("eye")
        requested_target = request_view.get("target") or request_view.get("lookat")
        molmo_view = molmo_views.get(view_id, {})
        isaac_view = isaac_views.get(view_id, {})
        molmo_eye = _backend_vec(molmo_view, "eye")
        molmo_target = _backend_vec(molmo_view, "target")
        isaac_eye = _backend_vec(isaac_view, "eye")
        isaac_target = _backend_vec(isaac_view, "target")
        if not all(
            is_vec3(value)
            for value in (
                requested_eye,
                requested_target,
                molmo_eye,
                molmo_target,
                isaac_eye,
                isaac_target,
            )
        ):
            continue
        pairs.append(
            {
                "view_id": view_id,
                "anchor_id": request_view.get("anchor_id"),
                "category": request_view.get("category"),
                "requested_eye": [float(value) for value in requested_eye[:3]],
                "requested_target": [float(value) for value in requested_target[:3]],
                "molmospaces_backend_eye": [float(value) for value in molmo_eye[:3]],
                "molmospaces_backend_target": [float(value) for value in molmo_target[:3]],
                "isaac_backend_eye": [float(value) for value in isaac_eye[:3]],
                "isaac_backend_target": [float(value) for value in isaac_target[:3]],
                "molmospaces_request_eye_residual_m": _distance_3d(requested_eye, molmo_eye),
                "molmospaces_request_target_residual_m": _distance_3d(
                    requested_target, molmo_target
                ),
                "isaac_request_eye_residual_m": _distance_3d(requested_eye, isaac_eye),
                "isaac_request_target_residual_m": _distance_3d(requested_target, isaac_target),
                "backend_eye_delta_m": _distance_3d(molmo_eye, isaac_eye),
                "backend_target_delta_m": _distance_3d(molmo_target, isaac_target),
            }
        )
    if not pairs:
        return {
            "schema": "canonical_camera_pose_contract_v1",
            "camera_model": CANONICAL_CAMERA_MODEL,
            "coordinate_frame": MOLMOSPACES_SCENE_FRAME,
            "status": "missing_pose_diagnostics",
            "pair_count": 0,
            "pose_threshold_m": CANONICAL_CAMERA_POSE_THRESHOLD_M,
            "interpretation": "No matched backend eye/target diagnostics were captured.",
            "pairs": [],
        }
    residual_keys = (
        "molmospaces_request_eye_residual_m",
        "molmospaces_request_target_residual_m",
        "isaac_request_eye_residual_m",
        "isaac_request_target_residual_m",
        "backend_eye_delta_m",
        "backend_target_delta_m",
    )
    maxima = {f"max_{key}": max(float(item[key]) for item in pairs) for key in residual_keys}
    max_pose_delta = max(maxima.values())
    status = (
        "same_backend_pose_within_threshold"
        if max_pose_delta <= CANONICAL_CAMERA_POSE_THRESHOLD_M
        else "backend_camera_pose_mismatch"
    )
    return {
        "schema": "canonical_camera_pose_contract_v1",
        "camera_model": CANONICAL_CAMERA_MODEL,
        "coordinate_frame": MOLMOSPACES_SCENE_FRAME,
        "status": status,
        "pair_count": len(pairs),
        "pose_threshold_m": CANONICAL_CAMERA_POSE_THRESHOLD_M,
        "max_pose_delta_m": max_pose_delta,
        **maxima,
        "interpretation": (
            "This checks the requested eye/target against the eye/target each backend "
            "reported after applying the Roboclaws camera-control request."
        ),
        "pairs": pairs,
    }


def camera_intrinsics_contract_from_capture(
    *,
    requested_lens: Any,
    requested_resolution: Any,
    molmospaces_lane: dict[str, Any],
    isaac_lane: dict[str, Any],
) -> dict[str, Any]:
    lens = requested_lens if isinstance(requested_lens, dict) else {}
    resolution = requested_resolution if isinstance(requested_resolution, dict) else {}
    width = optional_float(resolution.get("width"))
    height = optional_float(resolution.get("height"))
    requested_vertical_fov = optional_float(lens.get("vertical_fov_deg"))
    requested_focal = optional_float(lens.get("focal_length_mm"))
    requested_horizontal_aperture = optional_float(lens.get("horizontal_aperture_mm"))
    derived_horizontal_aperture = None
    derived_horizontal_fov = None
    if (
        requested_vertical_fov is not None
        and requested_focal is not None
        and width is not None
        and height is not None
        and height > 0
    ):
        vertical_aperture = (
            2.0 * requested_focal * math.tan(math.radians(requested_vertical_fov) / 2.0)
        )
        derived_horizontal_aperture = vertical_aperture * width / height
        derived_horizontal_fov = math.degrees(
            2.0 * math.atan(derived_horizontal_aperture / (2.0 * requested_focal))
        )
    aperture_delta = None
    if requested_horizontal_aperture is not None and derived_horizontal_aperture is not None:
        aperture_delta = abs(requested_horizontal_aperture - derived_horizontal_aperture)
    precedence = (
        "vertical_fov_deg"
        if requested_vertical_fov is not None
        else "horizontal_aperture_mm"
        if requested_horizontal_aperture is not None
        else "backend_default"
    )
    status = "intrinsics_consistent"
    if aperture_delta is not None and aperture_delta > 0.001:
        status = "vertical_fov_overrides_horizontal_aperture"
    return {
        "schema": "canonical_camera_intrinsics_contract_v1",
        "status": status,
        "camera_model": CANONICAL_CAMERA_MODEL,
        "resolution": {
            "width": int(width) if width is not None else None,
            "height": int(height) if height is not None else None,
        },
        "requested_lens": dict(lens),
        "molmospaces_lens": dict(molmospaces_lane.get("lens") or {}),
        "isaac_lens": dict(isaac_lane.get("lens") or {}),
        "isaac_derived_lens": dict(isaac_lane.get("derived_lens") or {}),
        "intrinsics_precedence": precedence,
        "derived_from_vertical_fov": {
            "horizontal_aperture_mm": derived_horizontal_aperture,
            "horizontal_fov_deg": derived_horizontal_fov,
        },
        "requested_vs_derived_horizontal_aperture_delta_mm": aperture_delta,
        "interpretation": (
            "The scene probe treats vertical_fov_deg as the canonical lens input. "
            "Isaac derives horizontal aperture from vertical FOV and aspect ratio; "
            "MuJoCo applies the same vertical FOV to its free camera."
        ),
    }


def room_scale_contract_from_scene_capture(
    *,
    room_views: list[dict[str, Any]],
    isaac_lane: dict[str, Any],
) -> dict[str, Any]:
    return room_scale_contract_from_capture(
        room_views=room_views,
        isaac_lane=isaac_lane,
        threshold_m=CANONICAL_ROOM_OUTLINE_THRESHOLD_M,
    )


def optional_float(value: Any) -> float | None:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def is_vec3(value: Any) -> bool:
    return isinstance(value, list) and len(value) >= 3


def _views_by_id(lane: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {
        str(item.get("view_id") or ""): item
        for item in lane.get("views") or []
        if isinstance(item, dict)
    }


def _backend_vec(view: dict[str, Any], key: str) -> list[float] | None:
    backend_value = view.get(f"backend_{key}")
    value = backend_value if is_vec3(backend_value) else view.get(key)
    return [float(item) for item in value[:3]] if is_vec3(value) else None


def _bounds_vec(bounds: dict[str, Any], key: str) -> list[float] | None:
    value = bounds.get(key)
    return [float(item) for item in value[:3]] if is_vec3(value) else None


def _point_inside_xy_bounds(point: list[float], bounds: dict[str, Any]) -> bool | None:
    minimum = _bounds_vec(bounds, "min")
    maximum = _bounds_vec(bounds, "max")
    if minimum is None or maximum is None:
        return None
    return (
        minimum[0] <= float(point[0]) <= maximum[0] and minimum[1] <= float(point[1]) <= maximum[1]
    )


def _point_inside_xyz_bounds(point: list[float], bounds: dict[str, Any]) -> bool | None:
    minimum = _bounds_vec(bounds, "min")
    maximum = _bounds_vec(bounds, "max")
    if minimum is None or maximum is None:
        return None
    return (
        minimum[0] <= float(point[0]) <= maximum[0]
        and minimum[1] <= float(point[1]) <= maximum[1]
        and minimum[2] <= float(point[2]) <= maximum[2]
    )


def _distance_to_axis_aligned_bounds(point: list[float], bounds: dict[str, Any]) -> float | None:
    minimum = _bounds_vec(bounds, "min")
    maximum = _bounds_vec(bounds, "max")
    if minimum is None or maximum is None:
        return None
    squared = 0.0
    for index in range(3):
        value = float(point[index])
        if value < minimum[index]:
            squared += (minimum[index] - value) ** 2
        elif value > maximum[index]:
            squared += (value - maximum[index]) ** 2
    return math.sqrt(squared)


def _surface_aim_distance_to_bounds(
    point: list[float],
    bounds: dict[str, Any],
    *,
    allowance_m: float,
) -> float | None:
    minimum = _bounds_vec(bounds, "min")
    maximum = _bounds_vec(bounds, "max")
    if minimum is None or maximum is None:
        return None
    adjusted_maximum = list(maximum)
    adjusted_maximum[2] += max(0.0, float(allowance_m))
    return _distance_to_explicit_axis_aligned_bounds(point, minimum, adjusted_maximum)


def _distance_to_explicit_axis_aligned_bounds(
    point: list[float],
    minimum: list[float],
    maximum: list[float],
) -> float:
    squared = 0.0
    for index in range(3):
        value = float(point[index])
        if value < minimum[index]:
            squared += (minimum[index] - value) ** 2
        elif value > maximum[index]:
            squared += (value - maximum[index]) ** 2
    return math.sqrt(squared)


def _distance_3d(left: list[float], right: list[float]) -> float:
    return math.sqrt(
        (float(left[0]) - float(right[0])) ** 2
        + (float(left[1]) - float(right[1])) ** 2
        + (float(left[2]) - float(right[2])) ** 2
    )


def _normalize_vec3(value: list[float]) -> list[float] | None:
    norm = math.sqrt(value[0] * value[0] + value[1] * value[1] + value[2] * value[2])
    if norm <= 1e-12:
        return None
    return [value[0] / norm, value[1] / norm, value[2] / norm]


def _cross(left: list[float], right: list[float]) -> list[float]:
    return [
        left[1] * right[2] - left[2] * right[1],
        left[2] * right[0] - left[0] * right[2],
        left[0] * right[1] - left[1] * right[0],
    ]


def _dot(left: list[float], right: list[float]) -> float:
    return left[0] * right[0] + left[1] * right[1] + left[2] * right[2]
