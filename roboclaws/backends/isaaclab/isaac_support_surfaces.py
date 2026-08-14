"""Isaac Lab backend runtime support."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class _SurfaceRect:
    surface: dict[str, Any]
    min_x: float
    max_x: float
    min_y: float
    max_y: float
    top_z: float


def usd_support_surface_union(
    candidates: list[dict[str, Any]],
    *,
    whole_surface: dict[str, Any] | None,
    descendant_source: str,
    union_source: str,
) -> dict[str, Any] | None:
    broad = _broad_support_rects(
        candidates,
        whole_surface=whole_surface,
        descendant_source=descendant_source,
    )
    if len(broad) < 2:
        return None
    bounds = _union_bounds(broad)
    area = (bounds["max_x"] - bounds["min_x"]) * (bounds["max_y"] - bounds["min_y"])
    if area <= 0.0:
        return None
    return _union_payload(broad, bounds=bounds, area=area, union_source=union_source)


def _broad_support_rects(
    candidates: list[dict[str, Any]],
    *,
    whole_surface: dict[str, Any] | None,
    descendant_source: str,
) -> list[_SurfaceRect]:
    best_top_z = _float_or_default(candidates[0].get("top_z"), 0.0) if candidates else 0.0
    whole_area = _float_or_default(_dict(whole_surface).get("area_m2"), 0.0)
    broad: list[_SurfaceRect] = []
    for surface in candidates:
        rect = _support_surface_rect(
            surface,
            descendant_source=descendant_source,
            best_top_z=best_top_z,
            whole_area=whole_area,
        )
        if rect is not None:
            broad.append(rect)
    return broad


def _support_surface_rect(
    surface: dict[str, Any],
    *,
    descendant_source: str,
    best_top_z: float,
    whole_area: float,
) -> _SurfaceRect | None:
    if surface.get("source") != descendant_source:
        return None
    top_z = _float_or_default(surface.get("top_z"), best_top_z)
    area = _float_or_default(surface.get("area_m2"), 0.0)
    if area < 0.03:
        return None
    if whole_area > 0.0 and area / whole_area < 0.35:
        return None
    if abs(top_z - best_top_z) > 0.08:
        return None
    center = _numeric_pair(surface.get("center"))
    half_extents = _numeric_pair(surface.get("half_extents"))
    if center is None or half_extents is None:
        return None
    return _SurfaceRect(
        surface=surface,
        min_x=center[0] - abs(half_extents[0]),
        max_x=center[0] + abs(half_extents[0]),
        min_y=center[1] - abs(half_extents[1]),
        max_y=center[1] + abs(half_extents[1]),
        top_z=top_z,
    )


def _numeric_pair(value: Any) -> tuple[float, float] | None:
    if not isinstance(value, (list, tuple)) or len(value) < 2:
        return None
    try:
        return (float(value[0]), float(value[1]))
    except (TypeError, ValueError):
        return None


def _union_bounds(broad: list[_SurfaceRect]) -> dict[str, float]:
    return {
        "min_x": min(item.min_x for item in broad),
        "max_x": max(item.max_x for item in broad),
        "min_y": min(item.min_y for item in broad),
        "max_y": max(item.max_y for item in broad),
        "top_z": max(item.top_z for item in broad),
    }


def _union_payload(
    broad: list[_SurfaceRect],
    *,
    bounds: dict[str, float],
    area: float,
    union_source: str,
) -> dict[str, Any]:
    min_x = bounds["min_x"]
    max_x = bounds["max_x"]
    min_y = bounds["min_y"]
    max_y = bounds["max_y"]
    return {
        "surface_id": "+".join(str(item.surface.get("surface_id") or "") for item in broad),
        "center": [round((min_x + max_x) / 2.0, 6), round((min_y + max_y) / 2.0, 6)],
        "top_z": round(bounds["top_z"], 6),
        "half_extents": [
            round((max_x - min_x) / 2.0, 6),
            round((max_y - min_y) / 2.0, 6),
        ],
        "area_m2": round(area, 6),
        "source": union_source,
        "selection_score": round(
            max(float(item.surface.get("selection_score") or 0.0) for item in broad),
            6,
        ),
        "member_count": len(broad),
    }


def _dict(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _float_or_default(value: Any, default: float) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default
