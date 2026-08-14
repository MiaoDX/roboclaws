from __future__ import annotations

import math
from pathlib import Path
from typing import Any

from roboclaws.backends.isaaclab.b1_readiness_validation import (
    KNOWN_POOR_BBOX_SEED_POLICY,
    KNOWN_POOR_BBOX_SEED_SOURCE,
    SEMANTIC_SOURCE,
)
from roboclaws.maps.bundle import parse_map_yaml
from roboclaws.maps.navigation_memory import navigation_memory_items, read_navigation_memory
from roboclaws.maps.rasterize import load_pgm

DEFAULT_B1_SCENE_USD = Path("storey_1/scene_gs.usda")
DEFAULT_B1_MESH_SCENE_USD = Path("storey_1/scene.usd")
DEFAULT_B1_SCENE_BASE_USD = Path("storey_1/configuration/scene_base.usd")
DEFAULT_MAP12_NAV2 = Path("agibot/nav2.yaml")
DEFAULT_MAP12_OCCUPANCY = Path("agibot/occupancy.pgm")
DEFAULT_MAP12_MEMORY = Path("navigation_memory.json")


def inspect_scene_engine_asset_layout(scene_root: Path) -> dict[str, Any]:
    scene_root = Path(scene_root)
    partitions = []
    if scene_root.is_dir():
        for partition_root in sorted(path for path in scene_root.iterdir() if path.is_dir()):
            scene_usd = partition_root / "scene.usd"
            gaussian_layer = partition_root / "scene_gs.usda"
            if not scene_usd.exists() and not gaussian_layer.exists():
                continue
            partitions.append(
                {
                    "name": partition_root.name,
                    "scene_usd": _file_inventory(scene_usd),
                    "gaussian_layer": _file_inventory(gaussian_layer),
                    "config_yaml": _file_inventory(partition_root / "config.yaml"),
                    "usdz": _file_inventory(partition_root / "xm_large_scene.usdz"),
                    "material_count": len(
                        list((partition_root / "configuration" / "materials").glob("*"))
                    ),
                }
            )
    return {
        "schema": "scene_engine_rebuilt_asset_inventory_v1",
        "root": str(scene_root),
        "primary_scene_usd": str(scene_root / DEFAULT_B1_SCENE_USD),
        "primary_mesh_scene_usd": str(scene_root / DEFAULT_B1_MESH_SCENE_USD),
        "primary_gaussian_layer": str(scene_root / DEFAULT_B1_SCENE_USD),
        "partition_count": len(partitions),
        "usd_scene_count": sum(1 for item in partitions if item["scene_usd"]["exists"]),
        "gaussian_layer_count": sum(1 for item in partitions if item["gaussian_layer"]["exists"]),
        "partitions": partitions,
    }


def _file_inventory(path: Path) -> dict[str, Any]:
    path = Path(path)
    return {
        "path": str(path),
        "exists": path.is_file(),
        "size_bytes": path.stat().st_size if path.is_file() else 0,
    }


def inspect_usd_stage(path: Path) -> dict[str, Any]:
    path = Path(path)
    if not path.is_file():
        return {
            "path": str(path),
            "opened": False,
            "status": "missing",
            "reason": f"USD file is missing: {path}",
        }
    from pxr import Usd, UsdGeom

    stage = Usd.Stage.Open(str(path))
    if stage is None:
        return {
            "path": str(path),
            "opened": False,
            "status": "open_failed",
            "reason": f"pxr.Usd could not open {path}",
        }
    prims = list(stage.Traverse())
    type_counts: dict[str, int] = {}
    for prim in prims:
        type_name = str(prim.GetTypeName() or "typeless")
        type_counts[type_name] = type_counts.get(type_name, 0) + 1
    default_prim = stage.GetDefaultPrim()
    used_layers = [
        str(Path(layer.realPath).resolve())
        for layer in stage.GetUsedLayers()
        if str(getattr(layer, "realPath", "") or "")
    ]
    root_path = str(path.resolve())
    local_layers = sorted(layer for layer in used_layers if layer != root_path)
    return {
        "path": str(path),
        "opened": True,
        "status": "opened",
        "default_prim": default_prim.GetName() if default_prim else "",
        "meters_per_unit": float(UsdGeom.GetStageMetersPerUnit(stage)),
        "up_axis": str(UsdGeom.GetStageUpAxis(stage)),
        "prim_count": len(prims),
        "mesh_count": type_counts.get("Mesh", 0),
        "type_counts": type_counts,
        "local_referenced_layers": local_layers,
        "local_referenced_layer_count": len(local_layers),
        "world_bounds": usd_world_bounds(stage, Usd=Usd, UsdGeom=UsdGeom),
        "object_candidate_count": sum(1 for prim in prims if "/Objects/" in str(prim.GetPath())),
        "receptacle_candidate_count": sum(
            1 for prim in prims if "/Receptacles/" in str(prim.GetPath())
        ),
    }


def usd_world_bounds(stage: Any, *, Usd: Any, UsdGeom: Any) -> dict[str, Any]:
    default_prim = stage.GetDefaultPrim()
    if not default_prim:
        return {"valid": False, "reason": "missing default prim"}
    bbox_cache = UsdGeom.BBoxCache(
        Usd.TimeCode.Default(),
        [UsdGeom.Tokens.default_, UsdGeom.Tokens.render, UsdGeom.Tokens.proxy],
    )
    bbox = bbox_cache.ComputeWorldBound(default_prim).ComputeAlignedBox()
    min_point = [float(value) for value in bbox.GetMin()]
    max_point = [float(value) for value in bbox.GetMax()]
    if not _finite_reasonable_bounds(min_point, max_point):
        return {
            "valid": False,
            "min": _round_vec(min_point),
            "max": _round_vec(max_point),
            "reason": (
                "USD world bounds were empty or non-finite for default/render/proxy purposes."
            ),
        }
    size = [max_v - min_v for min_v, max_v in zip(min_point, max_point, strict=True)]
    center = [(min_v + max_v) / 2.0 for min_v, max_v in zip(min_point, max_point, strict=True)]
    return {
        "valid": True,
        "min": _round_vec(min_point),
        "max": _round_vec(max_point),
        "size": _round_vec(size),
        "center": _round_vec(center),
    }


def inspect_obj_mesh(path: Path) -> dict[str, Any]:
    vertex_count = 0
    face_count = 0
    min_point = [math.inf, math.inf, math.inf]
    max_point = [-math.inf, -math.inf, -math.inf]
    with Path(path).open("r", encoding="utf-8", errors="ignore") as handle:
        for line in handle:
            if line.startswith("v "):
                parts = line.split()
                if len(parts) < 4:
                    continue
                try:
                    point = [float(parts[1]), float(parts[2]), float(parts[3])]
                except ValueError:
                    continue
                vertex_count += 1
                for index, value in enumerate(point):
                    min_point[index] = min(min_point[index], value)
                    max_point[index] = max(max_point[index], value)
            elif line.startswith("f "):
                face_count += 1
    valid = vertex_count > 0 and _finite_reasonable_bounds(min_point, max_point)
    return {
        "path": str(path),
        "vertex_count": vertex_count,
        "face_count": face_count,
        "world_bounds": _bounds_payload(min_point, max_point) if valid else {"valid": False},
    }


def inspect_ply_header(path: Path) -> dict[str, Any]:
    comments: dict[str, str] = {}
    vertex_count = 0
    with Path(path).open("rb") as handle:
        for raw_line in handle:
            line = raw_line.decode("ascii", errors="ignore").strip()
            if line.startswith("element vertex "):
                try:
                    vertex_count = int(line.rsplit(" ", 1)[-1])
                except ValueError:
                    vertex_count = 0
            elif line.startswith("comment "):
                parts = line.split(maxsplit=2)
                if len(parts) == 3:
                    key_value = parts[2].split(maxsplit=1)
                    if len(key_value) == 2:
                        comments[key_value[0]] = key_value[1]
            elif line == "end_header":
                break
    min_point = [_float_or_nan(comments.get(key)) for key in ("minx", "miny", "minz")]
    max_point = [_float_or_nan(comments.get(key)) for key in ("maxx", "maxy", "maxz")]
    valid = _finite_reasonable_bounds(min_point, max_point)
    return {
        "path": str(path),
        "vertex_count": vertex_count,
        "header_comment_bounds": _bounds_payload(min_point, max_point)
        if valid
        else {"valid": False},
        "source": comments.get("source", ""),
    }


def inspect_map12(map12_root: Path) -> dict[str, Any]:
    map12_root = Path(map12_root)
    nav2_path = map12_root / DEFAULT_MAP12_NAV2
    occupancy_path = map12_root / DEFAULT_MAP12_OCCUPANCY
    memory_path = map12_root / DEFAULT_MAP12_MEMORY
    nav2 = parse_map_yaml(nav2_path.read_text(encoding="utf-8"))
    origin = nav2.get("origin") if isinstance(nav2.get("origin"), list) else [0.0, 0.0, 0.0]
    resolution = float(nav2.get("resolution") or 0.05)
    grid = load_pgm(
        occupancy_path,
        resolution_m=resolution,
        origin_x=float(origin[0]),
        origin_y=float(origin[1]),
    )
    memory = read_navigation_memory(memory_path)
    anchors = [
        _anchor_summary(item, index)
        for index, item in enumerate(navigation_memory_items(memory), start=1)
    ]
    nav_goal_bounds = _xy_pose_bounds([anchor["nav_goal"] for anchor in anchors])
    pose_bounds = _xy_pose_bounds([anchor["pose"] for anchor in anchors])
    return {
        "schema": "robot_map_12_navigation_memory_inventory_v1",
        "nav2_yaml": str(nav2_path),
        "navigation_memory": str(memory_path),
        "occupancy_pgm": str(occupancy_path),
        "resolution_m": resolution,
        "origin": {"x": float(origin[0]), "y": float(origin[1]), "yaw": float(origin[2])},
        "occupancy_grid": {
            "width": grid.width,
            "height": grid.height,
            "bounds": _bounds_payload(
                [grid.origin_x, grid.origin_y, 0.0],
                [
                    grid.origin_x + grid.width * grid.resolution_m,
                    grid.origin_y + grid.height * grid.resolution_m,
                    0.0,
                ],
            ),
        },
        "anchor_count": len(anchors),
        "anchors_with_nav_goal_count": sum(1 for anchor in anchors if _has_xy(anchor["nav_goal"])),
        "anchors": anchors,
        "nav_goal_bounds": nav_goal_bounds,
        "pose_bounds": pose_bounds,
        "semantic_source": SEMANTIC_SOURCE,
    }


def build_overlay_report(
    *,
    scene_bounds: dict[str, Any],
    map12: dict[str, Any],
) -> dict[str, Any]:
    if scene_bounds.get("valid") is not True:
        return {
            "status": "blocked",
            "transform_status": "blocked",
            "reason": "B1 rebuilt scene USD bounds are unavailable.",
            "candidate_waypoints": [],
        }
    source_bounds = _dict(map12.get("nav_goal_bounds"))
    if source_bounds.get("valid") is not True:
        return {
            "status": "blocked",
            "transform_status": "blocked",
            "reason": "Map 12 navigation-memory nav_goal bounds are unavailable.",
            "candidate_waypoints": [],
        }
    b1_min = scene_bounds["min"]
    b1_max = scene_bounds["max"]
    source_min = source_bounds["min"]
    source_max = source_bounds["max"]
    source_width = max(float(source_max[0]) - float(source_min[0]), 1e-6)
    source_depth = max(float(source_max[1]) - float(source_min[1]), 1e-6)
    b1_width = max(float(b1_max[0]) - float(b1_min[0]), 1e-6)
    b1_depth = max(float(b1_max[1]) - float(b1_min[1]), 1e-6)
    transform = {
        "method": "bbox_fit_navigation_memory_nav_goals_to_scene_usd_bounds",
        "source": KNOWN_POOR_BBOX_SEED_SOURCE,
        "bbox_seed_policy": KNOWN_POOR_BBOX_SEED_POLICY,
        "scale_x": b1_width / source_width,
        "scale_y": b1_depth / source_depth,
        "translate_x": float(b1_min[0]) - float(source_min[0]) * (b1_width / source_width),
        "translate_y": float(b1_min[1]) - float(source_min[1]) * (b1_depth / source_depth),
        "source_frame": "robot_map_12_map",
        "target_frame": "b1_rebuilt_scene_usd_world_candidate",
    }
    anchors = [
        anchor
        for anchor in map12.get("anchors") or []
        if isinstance(anchor, dict) and _has_xy(_dict(anchor.get("nav_goal")))
    ]
    floor_z = 0.0
    candidate_waypoints = [
        _candidate_waypoint_from_anchor(anchor, transform=transform, floor_z=floor_z)
        for anchor in anchors[: min(4, len(anchors))]
    ]
    return {
        "status": "candidate" if len(candidate_waypoints) >= 2 else "blocked",
        "transform_status": "unverified",
        "bbox_seed_policy": KNOWN_POOR_BBOX_SEED_POLICY,
        "semantic_source": SEMANTIC_SOURCE,
        "source_bounds": source_bounds,
        "target_bounds": scene_bounds,
        "transform": {key: _round_float(value) for key, value in transform.items()},
        "candidate_waypoints": candidate_waypoints,
        "candidate_waypoint_count": len(candidate_waypoints),
        "residual_evidence": {
            "status": "not_available",
            "matched_anchor_count": 0,
            "reason": (
                "No human-authored B1/USD anchor correspondences are available. "
                "The overlay is a bounding-box candidate, not verified frame parity."
            ),
        },
        "reason": (
            "Map 12 navigation-memory anchors were projected into the B1 rebuilt scene USD "
            "bounds by a candidate bbox fit. At least three matched anchors with residuals "
            "are required before this can become verified."
        ),
    }


def _candidate_waypoint_from_anchor(
    anchor: dict[str, Any],
    *,
    transform: dict[str, Any],
    floor_z: float,
) -> dict[str, Any]:
    nav_goal = _dict(anchor.get("nav_goal"))
    yaw = _optional_float(nav_goal.get("yaw"))
    yaw_deg = (
        math.degrees(yaw) if yaw is not None else _optional_float(nav_goal.get("yaw_deg")) or 0.0
    )
    b1_x = float(nav_goal["x"]) * float(transform["scale_x"]) + float(transform["translate_x"])
    b1_y = float(nav_goal["y"]) * float(transform["scale_y"]) + float(transform["translate_y"])
    return {
        "waypoint_id": f"b1_overlay_{anchor['id']}",
        "source_anchor_id": anchor["id"],
        "label": anchor.get("label") or anchor["id"],
        "semantic_source": SEMANTIC_SOURCE,
        "map12_nav_goal": nav_goal,
        "b1_pose": {
            "frame": str(transform.get("target_frame") or "b1_rebuilt_scene_usd_world_candidate"),
            "x": round(b1_x, 6),
            "y": round(b1_y, 6),
            "z": round(float(floor_z), 6),
            "yaw_deg": round(float(yaw_deg), 6),
            "pose_source": SEMANTIC_SOURCE,
        },
    }


def _anchor_summary(item: Any, index: int) -> dict[str, Any]:
    entry = item if isinstance(item, dict) else {}
    return {
        "id": str(entry.get("id") or f"anchor_{index:03d}"),
        "label": str(entry.get("label") or entry.get("id") or f"anchor_{index:03d}"),
        "kind": str(entry.get("kind") or ""),
        "pose": _pose_dict(entry.get("pose")),
        "nav_goal": _pose_dict(entry.get("nav_goal") or entry.get("pose")),
        "confidence": _optional_float(entry.get("confidence")),
        "source": str(entry.get("source") or ""),
    }


def _pose_dict(value: Any) -> dict[str, Any]:
    pose = _dict(value)
    result: dict[str, Any] = {}
    for key in ("x", "y", "z", "yaw", "yaw_deg"):
        parsed = _optional_float(pose.get(key))
        if parsed is not None:
            result[key] = parsed
    return result


def _xy_pose_bounds(poses: list[dict[str, Any]]) -> dict[str, Any]:
    points = [pose for pose in poses if _has_xy(pose)]
    if not points:
        return {"valid": False, "reason": "no xy poses"}
    xs = [float(point["x"]) for point in points]
    ys = [float(point["y"]) for point in points]
    return _bounds_payload([min(xs), min(ys), 0.0], [max(xs), max(ys), 0.0])


def _bounds_payload(min_point: list[float], max_point: list[float]) -> dict[str, Any]:
    if not _finite_reasonable_bounds(min_point, max_point):
        return {"valid": False, "min": _round_vec(min_point), "max": _round_vec(max_point)}
    size = [max_v - min_v for min_v, max_v in zip(min_point, max_point, strict=True)]
    center = [(min_v + max_v) / 2.0 for min_v, max_v in zip(min_point, max_point, strict=True)]
    return {
        "valid": True,
        "min": _round_vec(min_point),
        "max": _round_vec(max_point),
        "size": _round_vec(size),
        "center": _round_vec(center),
    }


def _finite_reasonable_bounds(min_point: list[float], max_point: list[float]) -> bool:
    values = [*min_point, *max_point]
    if any(not math.isfinite(value) or abs(value) > 1e20 for value in values):
        return False
    return all(max_v >= min_v for min_v, max_v in zip(min_point, max_point, strict=True))


def _round_vec(values: list[float]) -> list[float]:
    return [
        round(float(value), 6) if math.isfinite(float(value)) else float(value) for value in values
    ]


def _round_float(value: Any) -> Any:
    if isinstance(value, (int, float)):
        return round(float(value), 9)
    return value


def _float_or_nan(value: Any) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return math.nan


def _optional_float(value: Any) -> float | None:
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return None
    return parsed if math.isfinite(parsed) else None


def _has_xy(value: dict[str, Any]) -> bool:
    return (
        _optional_float(value.get("x")) is not None and _optional_float(value.get("y")) is not None
    )


def _dict(value: Any) -> dict[str, Any]:
    return dict(value) if isinstance(value, dict) else {}
