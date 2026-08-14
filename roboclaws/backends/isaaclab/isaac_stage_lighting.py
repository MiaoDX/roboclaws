"""Isaac Lab backend runtime support."""

from __future__ import annotations

import math
from typing import Any

from roboclaws.household.camera_control import (
    DEFAULT_SCENE_PROBE_LIGHTING_PROFILE,
    scene_light_rig,
    scene_light_rig_roles,
)

USD_LIGHT_TYPE_NAMES = frozenset(
    {
        "CylinderLight",
        "DiskLight",
        "DistantLight",
        "DomeLight",
        "GeometryLight",
        "PortalLight",
        "RectLight",
        "SphereLight",
    }
)


def current_stage_bounds(stage_utils: Any) -> dict[str, list[float]] | None:
    from pxr import Usd, UsdGeom

    get_current_stage = getattr(stage_utils, "get_current_stage", None)
    if not callable(get_current_stage):
        return None
    stage = get_current_stage()
    if stage is None:
        return None
    root = stage.GetDefaultPrim() or stage.GetPseudoRoot()
    cache = UsdGeom.BBoxCache(
        Usd.TimeCode.Default(),
        [UsdGeom.Tokens.default_, UsdGeom.Tokens.render, UsdGeom.Tokens.proxy],
    )
    bbox = cache.ComputeWorldBound(root).ComputeAlignedBox()
    min_point = [float(value) for value in bbox.GetMin()]
    max_point = [float(value) for value in bbox.GetMax()]
    size = [max_v - min_v for min_v, max_v in zip(min_point, max_point, strict=True)]
    if any(not math.isfinite(value) for value in [*min_point, *max_point, *size]) or max(size) <= 0:
        return None
    center = [(min_v + max_v) / 2.0 for min_v, max_v in zip(min_point, max_point, strict=True)]
    return {"min": min_point, "max": max_point, "size": size, "center": center}


def ensure_capture_lighting(
    stage_utils: Any, profile: dict[str, Any] | None = None
) -> dict[str, Any]:
    from pxr import Gf, UsdGeom, UsdLux

    get_current_stage = getattr(stage_utils, "get_current_stage", None)
    if not callable(get_current_stage):
        return {"status": "missing_stage_api", "existing_light_count": 0, "added_light_count": 0}
    stage = get_current_stage()
    if stage is None:
        return {"status": "missing_stage", "existing_light_count": 0, "added_light_count": 0}
    profile = profile if isinstance(profile, dict) else dict(DEFAULT_SCENE_PROBE_LIGHTING_PROFILE)
    rig = scene_light_rig(profile)
    ambient = _dict(rig.get("ambient"))
    key = _dict(rig.get("key"))
    isaac_overrides = _dict(_dict(rig.get("backend_overrides")).get("isaac"))
    ambient_enabled = bool(ambient.get("enabled", False))
    key_enabled = bool(key.get("enabled", False))
    dome_intensity = float(ambient.get("isaac_dome_intensity", 0.0)) if ambient_enabled else 0.0
    key_intensity = float(isaac_overrides.get("key_intensity", 0.0)) if key_enabled else 0.0
    existing_light_intensity_scale = float(
        isaac_overrides.get("existing_light_intensity_scale", 1.0)
    )
    key_direction = normalized_vec3(key.get("direction"))
    key_rotation_source = "scene_light_rig.key.direction"
    key_rotation = (
        isaac_distant_light_rotation_from_direction(key_direction)
        if key_direction is not None
        else None
    )
    if key_rotation is None:
        key_rotation_source = "scene_light_rig.backend_overrides.isaac.key_rotation_deg"
        key_rotation = isaac_overrides.get("key_rotation_deg")
    if not isinstance(key_rotation, (list, tuple)) or len(key_rotation) < 3:
        key_rotation_source = "fallback"
        key_rotation = [-55.0, 0.0, 35.0]
    existing_lights = stage_light_paths(stage, exclude_prefix="/RoboclawsSmoke")
    existing_light_adjustments = scale_stage_light_intensities(
        stage,
        existing_lights,
        scale=existing_light_intensity_scale,
    )
    added_lights = []
    if dome_intensity > 0.0:
        dome = UsdLux.DomeLight.Define(stage, "/RoboclawsSmokeDomeLight")
        dome.CreateIntensityAttr(dome_intensity)
        added_lights.append("/RoboclawsSmokeDomeLight")
    if key_intensity > 0.0:
        key = UsdLux.DistantLight.Define(stage, "/RoboclawsSmokeKeyLight")
        key.CreateIntensityAttr(key_intensity)
        UsdGeom.XformCommonAPI(key).SetRotate(
            Gf.Vec3f(float(key_rotation[0]), float(key_rotation[1]), float(key_rotation[2]))
        )
        added_lights.append("/RoboclawsSmokeKeyLight")
    return {
        "schema": "isaac_capture_lighting_diagnostics_v1",
        "status": "using_existing_stage_lights" if not added_lights else "added_capture_lights",
        "profile_id": str(profile.get("profile_id") or ""),
        "profile_source": str(profile.get("source") or ""),
        "scene_light_rig": rig,
        "scene_light_rig_schema": rig.get("schema"),
        "scene_light_rig_roles": scene_light_rig_roles(rig),
        "authored_scene_lights_policy": rig.get("authored_scene_lights_policy"),
        "scene_key_light_direction": key_direction,
        "scene_key_light_frame": rig.get("frame"),
        "mujoco_headlight_ambient": ambient.get("mujoco_headlight_ambient"),
        "mujoco_headlight_diffuse": ambient.get("mujoco_headlight_diffuse"),
        "existing_light_count": len(existing_lights),
        "existing_light_paths": existing_lights,
        "existing_light_intensity_scale": existing_light_intensity_scale,
        "existing_light_intensity_adjustments": existing_light_adjustments,
        "added_light_count": len(added_lights),
        "added_light_paths": added_lights,
        "requested_dome_intensity": dome_intensity,
        "requested_key_intensity": key_intensity,
        "requested_key_rotation_deg": [
            float(key_rotation[0]),
            float(key_rotation[1]),
            float(key_rotation[2]),
        ],
        "requested_key_rotation_source": key_rotation_source,
        "applied_key_light_direction": key_direction if key_intensity > 0.0 else None,
        "applied_key_light_frame": rig.get("frame"),
    }


def normalized_vec3(value: Any) -> list[float] | None:
    if not isinstance(value, (list, tuple)) or len(value) < 3:
        return None
    try:
        vector = [float(value[0]), float(value[1]), float(value[2])]
    except (TypeError, ValueError):
        return None
    magnitude = math.sqrt(sum(component * component for component in vector))
    if magnitude <= 0.0:
        return None
    return [component / magnitude for component in vector]


def isaac_distant_light_rotation_from_direction(direction: list[float]) -> list[float]:
    """Return XYZ Euler degrees rotating the USD DistantLight -Z axis to direction."""

    x, y, z = direction
    pitch = math.degrees(math.asin(max(-1.0, min(1.0, y))))
    yaw = math.degrees(math.atan2(-x, -z))
    return [pitch, yaw, 0.0]


def scale_stage_light_intensities(
    stage: Any,
    light_paths: list[str],
    *,
    scale: float,
) -> list[dict[str, Any]]:
    if scale == 1.0:
        return []
    from pxr import UsdLux

    adjustments: list[dict[str, Any]] = []
    for path in light_paths:
        prim = stage.GetPrimAtPath(path)
        if not prim or not prim.IsValid():
            adjustments.append({"path": path, "status": "missing_prim"})
            continue
        try:
            light_api = UsdLux.LightAPI(prim)
            intensity_attr = light_api.GetIntensityAttr()
        except Exception as exc:  # pragma: no cover - defensive against USD schema drift.
            adjustments.append({"path": path, "status": "missing_intensity_api", "error": str(exc)})
            continue
        if not intensity_attr:
            adjustments.append({"path": path, "status": "missing_intensity_attr"})
            continue
        try:
            previous = float(intensity_attr.Get() or 0.0)
            updated = previous * scale
            intensity_attr.Set(updated)
            adjustments.append(
                {
                    "path": path,
                    "status": "scaled",
                    "previous_intensity": previous,
                    "updated_intensity": updated,
                    "scale": scale,
                }
            )
        except Exception as exc:  # pragma: no cover - defensive against USD value errors.
            adjustments.append({"path": path, "status": "scale_failed", "error": str(exc)})
    return adjustments


def stage_light_paths(
    stage: Any, *, exclude_prefix: str = "", light_api: Any | None = None
) -> list[str]:
    if light_api is None:
        from pxr import UsdLux

        light_api = UsdLux.LightAPI
    paths = []
    for prim in stage.Traverse():
        if not prim or not prim.IsValid():
            continue
        path = str(prim.GetPath())
        if exclude_prefix and path.startswith(exclude_prefix):
            continue
        if prim.IsA(light_api) or prim_type_is_light(prim):
            paths.append(path)
    return paths


def prim_type_is_light(prim: Any) -> bool:
    type_name = ""
    get_type_name = getattr(prim, "GetTypeName", None)
    if callable(get_type_name):
        type_name = str(get_type_name() or "")
    if not type_name:
        get_type_info = getattr(prim, "GetPrimTypeInfo", None)
        if callable(get_type_info):
            type_info = get_type_info()
            info_type_name = getattr(type_info, "GetTypeName", None)
            if callable(info_type_name):
                type_name = str(info_type_name() or "")
    return type_name in USD_LIGHT_TYPE_NAMES


def _dict(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}
