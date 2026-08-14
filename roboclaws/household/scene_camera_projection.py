from __future__ import annotations

import math
from typing import Any

from roboclaws.household import scene_camera_geometry_contract

CANONICAL_CAMERA_PROJECTION_THRESHOLD_PX = 0.5
MOLMOSPACES_LANE_ID = "molmospaces-mujoco"
ISAAC_LANE_ID = "isaaclab-prepared-usd"
ROOM_CAMERA_HEIGHT_M = 1.45


def projection_diagnostics(manifest: dict[str, Any]) -> dict[str, Any]:
    pose_contract = (
        manifest.get("camera_pose_contract")
        if isinstance(manifest.get("camera_pose_contract"), dict)
        else {}
    )
    intrinsics = (
        manifest.get("camera_intrinsics_contract")
        if isinstance(manifest.get("camera_intrinsics_contract"), dict)
        else {}
    )
    resolution = (
        intrinsics.get("resolution") if isinstance(intrinsics.get("resolution"), dict) else {}
    )
    width = scene_camera_geometry_contract.optional_float(resolution.get("width"))
    height = scene_camera_geometry_contract.optional_float(resolution.get("height"))
    vertical_fov = _projection_vertical_fov(intrinsics)
    if width is None or height is None or vertical_fov is None:
        return {
            "schema": "canonical_camera_projection_diagnostics_v1",
            "status": "missing_intrinsics",
            "projection_threshold_px": CANONICAL_CAMERA_PROJECTION_THRESHOLD_PX,
            "pair_count": 0,
            "pairs": [],
        }
    pose_pairs = [item for item in pose_contract.get("pairs") or [] if isinstance(item, dict)]
    canonical_views = {
        str(item.get("view_id") or ""): item
        for item in manifest.get("canonical_camera_views") or []
        if isinstance(item, dict)
    }
    isaac_views = scene_camera_geometry_contract._views_by_id(
        (manifest.get("lanes") or {}).get(ISAAC_LANE_ID)
        if isinstance((manifest.get("lanes") or {}).get(ISAAC_LANE_ID), dict)
        else {}
    )
    pairs: list[dict[str, Any]] = []
    for item in pose_pairs:
        view_id = str(item.get("view_id") or "")
        sample_points = _projection_sample_points(
            canonical_views.get(view_id, {}), isaac_views.get(view_id, {})
        )
        point_projections = []
        for point in sample_points:
            world = point.get("world")
            if not scene_camera_geometry_contract.is_vec3(world):
                continue
            molmo_pixel = _project_world_point(
                world,
                eye=item.get("molmospaces_backend_eye"),
                target=item.get("molmospaces_backend_target"),
                width=width,
                height=height,
                vertical_fov_deg=vertical_fov,
            )
            isaac_pixel = _project_world_point(
                world,
                eye=item.get("isaac_backend_eye"),
                target=item.get("isaac_backend_target"),
                width=width,
                height=height,
                vertical_fov_deg=vertical_fov,
            )
            if molmo_pixel is None or isaac_pixel is None:
                continue
            delta_px = math.hypot(
                float(molmo_pixel["pixel"][0]) - float(isaac_pixel["pixel"][0]),
                float(molmo_pixel["pixel"][1]) - float(isaac_pixel["pixel"][1]),
            )
            point_projections.append(
                {
                    "label": point.get("label"),
                    "world": [float(value) for value in world[:3]],
                    "molmospaces_pixel": molmo_pixel["pixel"],
                    "isaac_pixel": isaac_pixel["pixel"],
                    "pixel_delta": delta_px,
                    "depth_m": molmo_pixel["depth_m"],
                    "inside_frame": bool(
                        molmo_pixel["inside_frame"] and isaac_pixel["inside_frame"]
                    ),
                }
            )
        if point_projections:
            max_delta = max(float(point["pixel_delta"]) for point in point_projections)
            pairs.append(
                {
                    "view_id": view_id,
                    "anchor_id": item.get("anchor_id"),
                    "category": item.get("category"),
                    "point_count": len(point_projections),
                    "max_pixel_delta": max_delta,
                    "all_points_inside_frame": all(
                        bool(point["inside_frame"]) for point in point_projections
                    ),
                    "points": point_projections,
                }
            )
    max_pixel_delta = max(float(item["max_pixel_delta"]) for item in pairs) if pairs else None
    status = (
        "same_projected_geometry_within_threshold"
        if max_pixel_delta is not None
        and max_pixel_delta <= CANONICAL_CAMERA_PROJECTION_THRESHOLD_PX
        else "missing_projection_pairs"
        if max_pixel_delta is None
        else "projected_geometry_mismatch"
    )
    return {
        "schema": "canonical_camera_projection_diagnostics_v1",
        "status": status,
        "interpretation": (
            "Projects the same canonical 3D sample points through the backend-reported "
            "eye/target pose and shared vertical FOV. When this passes, apparent framing "
            "differences are not explained by camera position, target, FOV, or room scale."
        ),
        "projection_threshold_px": CANONICAL_CAMERA_PROJECTION_THRESHOLD_PX,
        "resolution": {"width": int(width), "height": int(height)},
        "vertical_fov_deg": vertical_fov,
        "pair_count": len(pairs),
        "max_pixel_delta": max_pixel_delta,
        "pairs": pairs,
    }


def _projection_vertical_fov(intrinsics: dict[str, Any]) -> float | None:
    requested = (
        intrinsics.get("requested_lens")
        if isinstance(intrinsics.get("requested_lens"), dict)
        else {}
    )
    molmo = (
        intrinsics.get("molmospaces_lens")
        if isinstance(intrinsics.get("molmospaces_lens"), dict)
        else {}
    )
    isaac = intrinsics.get("isaac_lens") if isinstance(intrinsics.get("isaac_lens"), dict) else {}
    return (
        scene_camera_geometry_contract.optional_float(requested.get("vertical_fov_deg"))
        or scene_camera_geometry_contract.optional_float(molmo.get("vertical_fov_deg"))
        or scene_camera_geometry_contract.optional_float(isaac.get("vertical_fov_deg"))
    )


def _projection_sample_points(
    request_view: dict[str, Any],
    isaac_view: dict[str, Any],
) -> list[dict[str, Any]]:
    points: list[dict[str, Any]] = []
    target = request_view.get("target") or request_view.get("lookat") or isaac_view.get("target")
    if scene_camera_geometry_contract.is_vec3(target):
        points.append({"label": "camera_target", "world": [float(value) for value in target[:3]]})
    room_outline = (
        request_view.get("room_outline")
        if isinstance(request_view.get("room_outline"), dict)
        else {}
    )
    center = room_outline.get("center")
    half_extents = room_outline.get("half_extents")
    if (
        isinstance(center, list)
        and len(center) >= 2
        and isinstance(half_extents, list)
        and len(half_extents) >= 2
    ):
        z = (
            float(target[2])
            if scene_camera_geometry_contract.is_vec3(target)
            else ROOM_CAMERA_HEIGHT_M
        )
        cx = float(center[0])
        cy = float(center[1])
        hx = float(half_extents[0])
        hy = float(half_extents[1])
        for label, x_sign, y_sign in (
            ("room_min_min", -1.0, -1.0),
            ("room_min_max", -1.0, 1.0),
            ("room_max_min", 1.0, -1.0),
            ("room_max_max", 1.0, 1.0),
        ):
            points.append({"label": label, "world": [cx + x_sign * hx, cy + y_sign * hy, z]})
    bounds = isaac_view.get("usd_bounds") if isinstance(isaac_view.get("usd_bounds"), dict) else {}
    minimum = scene_camera_geometry_contract._bounds_vec(bounds, "min")
    maximum = scene_camera_geometry_contract._bounds_vec(bounds, "max")
    center3 = scene_camera_geometry_contract._bounds_vec(bounds, "center")
    if center3 is not None:
        points.append({"label": "usd_bounds_center", "world": center3})
    if minimum is not None and maximum is not None:
        for label, x, y, z in (
            ("usd_bounds_min", minimum[0], minimum[1], minimum[2]),
            ("usd_bounds_max", maximum[0], maximum[1], maximum[2]),
        ):
            points.append({"label": label, "world": [x, y, z]})
    deduped: list[dict[str, Any]] = []
    seen: set[tuple[str, tuple[float, float, float]]] = set()
    for point in points:
        world = point.get("world")
        if not scene_camera_geometry_contract.is_vec3(world):
            continue
        key = (
            str(point.get("label") or ""),
            (round(float(world[0]), 6), round(float(world[1]), 6), round(float(world[2]), 6)),
        )
        if key in seen:
            continue
        seen.add(key)
        deduped.append(point)
    return deduped


def _project_world_point(
    point: list[float],
    *,
    eye: Any,
    target: Any,
    width: float,
    height: float,
    vertical_fov_deg: float,
) -> dict[str, Any] | None:
    if not scene_camera_geometry_contract.is_vec3(
        eye
    ) or not scene_camera_geometry_contract.is_vec3(target):
        return None
    eye_vec = [float(value) for value in eye[:3]]
    target_vec = [float(value) for value in target[:3]]
    forward = scene_camera_geometry_contract._normalize_vec3(
        [
            target_vec[0] - eye_vec[0],
            target_vec[1] - eye_vec[1],
            target_vec[2] - eye_vec[2],
        ]
    )
    if forward is None:
        return None
    world_up = [0.0, 0.0, 1.0]
    right = scene_camera_geometry_contract._normalize_vec3(
        scene_camera_geometry_contract._cross(forward, world_up)
    )
    if right is None:
        right = [1.0, 0.0, 0.0]
    up = scene_camera_geometry_contract._cross(right, forward)
    relative = [
        float(point[0]) - eye_vec[0],
        float(point[1]) - eye_vec[1],
        float(point[2]) - eye_vec[2],
    ]
    depth = scene_camera_geometry_contract._dot(relative, forward)
    if depth <= 1e-9:
        return None
    x_camera = scene_camera_geometry_contract._dot(relative, right)
    y_camera = scene_camera_geometry_contract._dot(relative, up)
    focal_y = (height * 0.5) / math.tan(math.radians(vertical_fov_deg) * 0.5)
    focal_x = focal_y
    pixel_x = width * 0.5 + x_camera * focal_x / depth
    pixel_y = height * 0.5 - y_camera * focal_y / depth
    return {
        "pixel": [pixel_x, pixel_y],
        "depth_m": depth,
        "inside_frame": 0.0 <= pixel_x <= width and 0.0 <= pixel_y <= height,
    }
