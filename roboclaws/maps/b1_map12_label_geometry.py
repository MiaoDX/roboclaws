from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class SourceMapTransform:
    width_px: int
    height_px: int
    resolution_m: float
    origin_x: float
    origin_y: float
    origin_yaw_rad: float = 0.0


def world_to_pixel(x: float, y: float, transform: SourceMapTransform) -> dict[str, float]:
    return {
        "x": (float(x) - transform.origin_x) / transform.resolution_m,
        "y": transform.height_px - 1.0 - ((float(y) - transform.origin_y) / transform.resolution_m),
    }


def pixel_to_world(px: float, py: float, transform: SourceMapTransform) -> dict[str, float]:
    return {
        "x": transform.origin_x + float(px) * transform.resolution_m,
        "y": transform.origin_y + (transform.height_px - 1.0 - float(py)) * transform.resolution_m,
    }


def _origin(map_yaml: dict[str, Any]) -> list[float]:
    origin = map_yaml.get("origin") if isinstance(map_yaml.get("origin"), list) else []
    values = [float(item) for item in origin[:3]]
    while len(values) < 3:
        values.append(0.0)
    return values


def _polygon_points(value: Any) -> list[dict[str, float]]:
    points = []
    for raw_point in value or []:
        if not isinstance(raw_point, dict):
            continue
        try:
            points.append({"x": float(raw_point["x"]), "y": float(raw_point["y"])})
        except (KeyError, TypeError, ValueError):
            continue
    return points


def _polygon_signature(points: list[dict[str, float]]) -> str:
    if len(points) < 3:
        return ""
    return "|".join(f"{point['x']:.3f},{point['y']:.3f}" for point in points)


def _center_from_room(room: dict[str, Any], polygon: list[dict[str, float]]) -> dict[str, float]:
    raw_center = room.get("map_center") if isinstance(room.get("map_center"), dict) else {}
    if "x" in raw_center and "y" in raw_center:
        return {"x": float(raw_center["x"]), "y": float(raw_center["y"])}
    if polygon:
        return {
            "x": sum(point["x"] for point in polygon) / len(polygon),
            "y": sum(point["y"] for point in polygon) / len(polygon),
        }
    return {"x": 0.0, "y": 0.0}


def _room_centers_by_id(semantics: dict[str, Any]) -> dict[str, dict[str, float]]:
    centers: dict[str, dict[str, float]] = {}
    for raw_room in semantics.get("rooms") or []:
        if not isinstance(raw_room, dict):
            continue
        room_id = str(raw_room.get("room_id") or "")
        if not room_id:
            continue
        centers[room_id] = _center_from_room(raw_room, _polygon_points(raw_room.get("polygon")))
    return centers


def _resolve_map_anchor(
    anchor_id: str,
    *,
    room_centers: dict[str, dict[str, float]],
    waypoint_centers: dict[str, dict[str, float]],
    fixture_centers: dict[str, dict[str, float]],
) -> dict[str, Any] | None:
    if anchor_id in room_centers:
        return {"kind": "room", "center": room_centers[anchor_id]}
    if anchor_id in waypoint_centers:
        return {"kind": "waypoint", "center": waypoint_centers[anchor_id]}
    if anchor_id in fixture_centers:
        return {"kind": "fixture", "center": fixture_centers[anchor_id]}
    return None


def _geometry_center(geometry: dict[str, Any]) -> dict[str, float]:
    if isinstance(geometry.get("center"), dict):
        center = geometry["center"]
        return {"x": float(center.get("x") or 0.0), "y": float(center.get("y") or 0.0)}
    polygon = _polygon_points(geometry.get("polygon"))
    if polygon:
        return {
            "x": sum(point["x"] for point in polygon) / len(polygon),
            "y": sum(point["y"] for point in polygon) / len(polygon),
        }
    return {"x": 0.0, "y": 0.0}


def _draft_geometry(value: Any) -> dict[str, Any]:
    geometry = value if isinstance(value, dict) else {}
    kind = str(geometry.get("kind") or "")
    if kind == "circle":
        center = _geometry_center(geometry)
        return {
            "kind": "circle",
            "center": center,
            "radius_m": max(float(geometry.get("radius_m") or 0.0), 0.0),
        }
    if kind == "point":
        return {"kind": "point", "center": _geometry_center(geometry)}
    polygon = _polygon_points(geometry.get("polygon"))
    return {"kind": "polygon", "polygon": polygon}


def _repo_artifact_path(source: str, *, repo_root: Path) -> Path | None:
    raw_path = Path(source)
    candidate = raw_path if raw_path.is_absolute() else repo_root / raw_path
    try:
        resolved = candidate.resolve(strict=False)
        resolved.relative_to(repo_root.resolve())
    except ValueError:
        return None
    return resolved
