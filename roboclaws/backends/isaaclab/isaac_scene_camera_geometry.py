"""Isaac Lab backend runtime support."""

from __future__ import annotations

import math
from pathlib import Path
from typing import Any

from roboclaws.core.json_sources import read_json_value
from roboclaws.household.camera_control import (
    ANCHOR_ORBIT_CAMERA_MODEL,
    CANONICAL_CAMERA_MODEL,
    camera_pose_vec3,
    load_camera_control_request,
    normalize_camera_control_request,
)


def load_camera_view_specs(path: Path) -> list[dict[str, Any]]:
    payload = read_json_value(path, label="camera view spec")
    raw_views = payload.get("views") if isinstance(payload, dict) else payload
    if not isinstance(raw_views, list):
        raise ValueError("camera view spec must be a list or an object with a views list")
    return [dict(item) for item in raw_views if isinstance(item, dict)]


def load_camera_request_from_args(
    *,
    view_specs_path: Path | None,
    camera_request_path: Path | None,
    width: int,
    height: int,
) -> dict[str, Any]:
    if camera_request_path is not None:
        return load_camera_control_request(camera_request_path, width=width, height=height)
    if view_specs_path is not None:
        return normalize_camera_control_request(
            load_camera_view_specs(view_specs_path),
            width=width,
            height=height,
        )
    raise ValueError("camera_views requires --camera-request-path or --view-specs-path")


def isaac_scene_camera_view_spec(
    raw_spec: dict[str, Any],
    *,
    index: int,
    stage_utils: Any | None = None,
) -> dict[str, Any]:
    view_id = str(raw_spec.get("view_id") or raw_spec.get("id") or f"view_{index:02d}")
    safe_view_id = "".join(ch if ch.isalnum() or ch in {"-", "_"} else "_" for ch in view_id)
    usd_prim_path = str(raw_spec.get("usd_prim_path") or "")
    usd_bounds = bounds_from_usd_prim_path(
        stage_utils=stage_utils,
        usd_prim_path=usd_prim_path,
        min_target_z=float(raw_spec.get("min_target_z", 0.6)),
    )
    usd_bounds_target = usd_bounds.get("target") if isinstance(usd_bounds, dict) else None
    target_source = "usd_prim_world_bounds" if usd_bounds_target is not None else ""
    target_field = "target" if raw_spec.get("target") is not None else "lookat"
    if raw_spec.get("camera_model") == CANONICAL_CAMERA_MODEL:
        target = camera_vec3(raw_spec.get(target_field), field_name=target_field)
        target_source = "canonical_explicit_target"
    elif usd_bounds_target is not None:
        target = usd_bounds_target
    else:
        target = camera_vec3(raw_spec.get(target_field), field_name=target_field)
        target_source = "explicit_target_or_default"
    backend_transform = backend_transform_for_lane(raw_spec, "isaaclab-prepared-usd")
    if "eye" in raw_spec and raw_spec.get("eye") is not None:
        eye = camera_vec3(raw_spec.get("eye"), field_name="eye")
        if backend_transform:
            eye = apply_scene_transform_to_point(eye, backend_transform)
            target = apply_scene_transform_to_point(target, backend_transform)
    else:
        camera_orbit = lane_camera_orbit(raw_spec, "isaaclab-prepared-usd")
        eye = eye_from_lookat_spec(
            target=target,
            distance=float(camera_orbit.get("distance_m", raw_spec.get("distance", 4.0))),
            azimuth=float(camera_orbit.get("azimuth_deg", raw_spec.get("azimuth", 225.0))),
            elevation=abs(
                float(camera_orbit.get("elevation_deg", raw_spec.get("elevation", 35.0)))
            ),
        )
    return {
        "view_id": safe_view_id,
        "label": str(raw_spec.get("label") or view_id),
        "anchor_id": str(raw_spec.get("anchor_id") or ""),
        "anchor_kind": str(raw_spec.get("anchor_kind") or ""),
        "robot_view_role": str(raw_spec.get("robot_view_role") or ""),
        "camera_basis": str(raw_spec.get("camera_basis") or ""),
        "camera_mode": str(raw_spec.get("camera_mode") or "free_camera"),
        "usd_prim_path": usd_prim_path,
        "eye": eye,
        "target": target,
        "lookat": target,
        "backend_eye": eye,
        "backend_target": target,
        "usd_bounds_target": usd_bounds_target,
        "usd_bounds": usd_bounds,
        "target_source": target_source,
        "camera_model": str(raw_spec.get("camera_model") or ANCHOR_ORBIT_CAMERA_MODEL),
        "coordinate_frame": str(raw_spec.get("coordinate_frame") or ""),
        "camera_orbit": dict(lane_camera_orbit(raw_spec, "isaaclab-prepared-usd")),
        "lens": dict(raw_spec.get("lens")) if isinstance(raw_spec.get("lens"), dict) else {},
        "calibration_status": str(raw_spec.get("calibration_status") or ""),
        "coordinate_convention": str(raw_spec.get("coordinate_convention") or ""),
    }


def lane_camera_orbit(raw_spec: dict[str, Any], lane_id: str) -> dict[str, Any]:
    lane_orbits = raw_spec.get("lane_camera_orbits")
    if isinstance(lane_orbits, dict):
        lane_orbit = lane_orbits.get(lane_id)
        if isinstance(lane_orbit, dict):
            return lane_orbit
    camera_orbit = raw_spec.get("camera_orbit")
    return camera_orbit if isinstance(camera_orbit, dict) else {}


def backend_transform_for_lane(raw_spec: dict[str, Any], lane_id: str) -> dict[str, Any]:
    transforms = raw_spec.get("backend_transforms")
    if isinstance(transforms, dict):
        transform = transforms.get(lane_id)
        if isinstance(transform, dict):
            return transform
    return {}


def apply_scene_transform_to_point(point: list[float], transform: dict[str, Any]) -> list[float]:
    scale = float(transform.get("xy_scale", 1.0))
    rotation_rad = math.radians(float(transform.get("rotation_z_deg", 0.0)))
    raw_translation = transform.get("translation")
    translation = raw_translation if isinstance(raw_translation, list) else []
    tx = float(translation[0]) if len(translation) > 0 else 0.0
    ty = float(translation[1]) if len(translation) > 1 else 0.0
    tz = float(translation[2]) if len(translation) > 2 else 0.0
    x = float(point[0])
    y = float(point[1])
    return [
        scale * (math.cos(rotation_rad) * x - math.sin(rotation_rad) * y) + tx,
        scale * (math.sin(rotation_rad) * x + math.cos(rotation_rad) * y) + ty,
        float(point[2]) + tz,
    ]


def bounds_from_usd_prim_path(
    *,
    stage_utils: Any | None,
    usd_prim_path: str,
    min_target_z: float,
) -> dict[str, Any] | None:
    if stage_utils is None or not usd_prim_path:
        return None
    from pxr import Usd, UsdGeom

    get_current_stage = getattr(stage_utils, "get_current_stage", None)
    if not callable(get_current_stage):
        return None
    stage = get_current_stage()
    if stage is None:
        return None
    prim = stage.GetPrimAtPath(usd_prim_path)
    if not prim or not prim.IsValid():
        return None
    cache = UsdGeom.BBoxCache(
        Usd.TimeCode.Default(),
        [UsdGeom.Tokens.default_, UsdGeom.Tokens.render, UsdGeom.Tokens.proxy],
    )
    bbox = cache.ComputeWorldBound(prim).ComputeAlignedBox()
    min_point = [float(value) for value in bbox.GetMin()]
    max_point = [float(value) for value in bbox.GetMax()]
    size = [max_v - min_v for min_v, max_v in zip(min_point, max_point, strict=True)]
    if any(not math.isfinite(value) for value in [*min_point, *max_point, *size]):
        return None
    if max(size) <= 0:
        return None
    center = [(min_v + max_v) / 2.0 for min_v, max_v in zip(min_point, max_point, strict=True)]
    target = list(center)
    target[2] = max(target[2], min_target_z)
    return {
        "min": min_point,
        "max": max_point,
        "size": size,
        "center": center,
        "target": target,
        "target_z_floor": min_target_z,
    }


def eye_from_lookat_spec(
    *,
    target: list[float],
    distance: float,
    azimuth: float,
    elevation: float,
) -> list[float]:
    azimuth_rad = math.radians(azimuth)
    elevation_rad = math.radians(elevation)
    horizontal = math.cos(elevation_rad) * distance
    return [
        float(target[0]) + math.sin(azimuth_rad) * horizontal,
        float(target[1]) + math.cos(azimuth_rad) * horizontal,
        float(target[2]) + math.sin(elevation_rad) * distance,
    ]


def camera_vec3(value: Any, *, field_name: str = "camera vector") -> list[float]:
    return camera_pose_vec3(value, field_name=field_name)


def image_has_variance(array: Any, *, np: Any) -> bool:
    return bool(np.max(array) > np.min(array))
