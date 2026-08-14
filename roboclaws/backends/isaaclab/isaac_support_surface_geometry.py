"""Isaac Lab backend runtime support."""

from __future__ import annotations

from typing import Any, Callable, Iterable

from roboclaws.backends.isaaclab.isaac_support_surfaces import usd_support_surface_union

ISAAC_DESCENDANT_SUPPORT_SURFACE_SOURCE = "isaac_usd_descendant_support_surface"
ISAAC_DESCENDANT_SUPPORT_SURFACE_UNION_SOURCE = "isaac_usd_descendant_support_surface_union"
ISAAC_WORLD_BOUNDS_SUPPORT_SURFACE_SOURCE = "isaac_usd_world_bounds"


def support_pose_from_usd_bounds(
    bounds: Any,
    *,
    fallback: dict[str, Any] | None = None,
) -> dict[str, Any] | None:
    raw_bounds = bounds if isinstance(bounds, dict) else {}
    center = _vec3(raw_bounds.get("center"))
    max_point = _vec3(raw_bounds.get("max"))
    if center is None:
        return dict(fallback) if fallback else None
    pose = {
        "frame": "usd_world",
        "x": center[0],
        "y": center[1],
        "z": max_point[2] if max_point is not None else center[2],
        "yaw_deg": float(_dict(fallback).get("yaw_deg") or 0.0),
        "source": "usd_world_bounds_top_center",
    }
    size = _vec3(raw_bounds.get("size"))
    if size is not None:
        pose["support_radius_m"] = round(max(size[0], size[1]) / 2.0, 6)
    return pose


def support_pose_from_support_surface(
    surface: dict[str, Any],
    *,
    fallback: dict[str, Any] | None = None,
) -> dict[str, Any] | None:
    center = surface.get("center")
    if not isinstance(center, (list, tuple)) or len(center) < 2:
        return dict(fallback) if fallback else None
    try:
        x = float(center[0])
        y = float(center[1])
        z = float(surface["top_z"])
    except (KeyError, TypeError, ValueError):
        return dict(fallback) if fallback else None
    half_extents = surface.get("half_extents")
    pose = {
        "frame": "usd_world",
        "x": x,
        "y": y,
        "z": z,
        "yaw_deg": _float_or_default(_dict(fallback).get("yaw_deg"), 0.0),
        "source": str(surface.get("source") or ISAAC_DESCENDANT_SUPPORT_SURFACE_SOURCE),
        "support_surface_id": surface.get("surface_id"),
    }
    if isinstance(half_extents, (list, tuple)) and len(half_extents) >= 2:
        try:
            pose["support_radius_m"] = round(
                max(abs(float(half_extents[0])), abs(float(half_extents[1]))),
                6,
            )
        except (TypeError, ValueError):
            pass
    return pose


def usd_receptacle_support_surfaces(
    *,
    prim: Any,
    usd_geom: Any,
    world_bounds: Callable[..., dict[str, Any] | None],
    iter_prim_range: Callable[[Any], Iterable[Any]],
) -> list[dict[str, Any]]:
    whole_bounds = world_bounds(prim, usd_geom=usd_geom)
    whole_surface = support_surface_from_usd_bounds(
        bounds=whole_bounds,
        surface_id=str(prim.GetPath()),
        source=ISAAC_WORLD_BOUNDS_SUPPORT_SURFACE_SOURCE,
    )
    candidates = []
    for descendant in iter_prim_range(prim):
        if descendant == prim:
            continue
        if not is_usd_renderable_support_candidate(descendant, usd_geom=usd_geom):
            continue
        bounds = world_bounds(descendant, usd_geom=usd_geom)
        surface = support_surface_from_usd_bounds(
            bounds=bounds,
            surface_id=str(descendant.GetPath()),
            source=ISAAC_DESCENDANT_SUPPORT_SURFACE_SOURCE,
        )
        if surface is None:
            continue
        score = usd_support_surface_score(surface, whole_surface=whole_surface)
        if score is None:
            continue
        surface["selection_score"] = round(float(score), 6)
        candidates.append(surface)
    candidates.sort(
        key=lambda item: (
            float(item.get("selection_score") or 0.0),
            float(item.get("area_m2") or 0.0),
            -float(item.get("top_z") or 0.0),
            str(item.get("surface_id") or ""),
        ),
        reverse=True,
    )
    if candidates:
        union = usd_support_surface_union_entry(candidates, whole_surface=whole_surface)
        if union is not None:
            return [union, *candidates[:7]]
        return candidates[:8]
    return [whole_surface] if whole_surface is not None else []


def is_usd_renderable_support_candidate(prim: Any, *, usd_geom: Any) -> bool:
    gprim_type = getattr(usd_geom, "Gprim", None)
    if gprim_type is not None and prim.IsA(gprim_type):
        return True
    return str(prim.GetTypeName() or "") in {"Mesh", "Cube", "Sphere", "Cylinder", "Capsule"}


def support_surface_from_usd_bounds(
    *,
    bounds: Any,
    surface_id: str,
    source: str,
) -> dict[str, Any] | None:
    raw_bounds = bounds if isinstance(bounds, dict) else {}
    center = _vec3(raw_bounds.get("center"))
    size = _vec3(raw_bounds.get("size"))
    max_point = _vec3(raw_bounds.get("max"))
    if center is None or size is None or max_point is None:
        return None
    half_extents = [abs(float(size[0])) / 2.0, abs(float(size[1])) / 2.0]
    if min(half_extents) < 0.03:
        return None
    area = 4.0 * float(half_extents[0]) * float(half_extents[1])
    if area <= 0.0:
        return None
    return {
        "surface_id": surface_id,
        "center": [round(float(center[0]), 6), round(float(center[1]), 6)],
        "top_z": round(float(max_point[2]), 6),
        "half_extents": [
            round(float(half_extents[0]), 6),
            round(float(half_extents[1]), 6),
        ],
        "area_m2": round(float(area), 6),
        "source": source,
    }


def usd_support_surface_score(
    surface: dict[str, Any],
    *,
    whole_surface: dict[str, Any] | None,
) -> float | None:
    area = float(surface.get("area_m2") or 0.0)
    if area < 0.03:
        return None
    half_extents = surface.get("half_extents")
    if not isinstance(half_extents, (list, tuple)) or len(half_extents) < 2:
        return None
    try:
        min_half_extent = min(abs(float(half_extents[0])), abs(float(half_extents[1])))
        top_z = float(surface["top_z"])
    except (KeyError, TypeError, ValueError):
        return None
    if min_half_extent < 0.06:
        return None
    whole_area = float(_dict(whole_surface).get("area_m2") or 0.0)
    whole_top_z = _dict(whole_surface).get("top_z")
    area_ratio = area / whole_area if whole_area > 0.0 else 1.0
    try:
        below_whole_top = max(float(whole_top_z) - top_z, 0.0)
    except (TypeError, ValueError):
        below_whole_top = 0.0
    # Beds and similar receptacles often include tall backboards in the parent
    # bounds. Favor broad lower descendants over the highest broad descendant.
    return area + min(area_ratio, 1.25) + min(below_whole_top * 2.0, 3.0)


def usd_support_surface_union_entry(
    candidates: list[dict[str, Any]],
    *,
    whole_surface: dict[str, Any] | None,
) -> dict[str, Any] | None:
    return usd_support_surface_union(
        candidates,
        whole_surface=whole_surface,
        descendant_source=ISAAC_DESCENDANT_SUPPORT_SURFACE_SOURCE,
        union_source=ISAAC_DESCENDANT_SUPPORT_SURFACE_UNION_SOURCE,
    )


def _float_or_default(value: Any, default: float) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return float(default)


def _dict(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _vec3(value: Any) -> list[float] | None:
    if not isinstance(value, (list, tuple)) or len(value) < 3:
        return None
    try:
        return [float(value[0]), float(value[1]), float(value[2])]
    except (TypeError, ValueError):
        return None
