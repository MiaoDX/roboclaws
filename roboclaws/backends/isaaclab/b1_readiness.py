#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import math
import sys
from pathlib import Path
from typing import Any

if __package__ in {None, ""}:
    repo_root = Path(__file__).resolve().parents[2]
    if str(repo_root) not in sys.path:
        sys.path.insert(0, str(repo_root))

from PIL import Image, ImageStat

from roboclaws.core.json_sources import read_json_object
from roboclaws.maps.bundle import parse_map_yaml
from roboclaws.maps.navigation_memory import navigation_memory_items, read_navigation_memory
from roboclaws.maps.rasterize import load_pgm

READINESS_SCHEMA = "b1_map12_digital_twin_readiness_v1"
NAVIGATION_SMOKE_SCHEMA = "b1_map12_navigation_smoke_v1"
ALIGNMENT_RESIDUALS_SCHEMA = "b1_map12_scene_alignment_residuals_v1"
WAYPOINT_POSE_REQUESTS_SCHEMA = "b1_map12_waypoint_pose_requests_v1"
SEMANTIC_SOURCE = "robot_map_12_navigation_memory_overlay"
SEMANTIC_USD_BLOCKED = "blocked_until_segmentation_or_manifest"
NAVIGATION_PROVENANCE = "isaac_b1_map12_navigation_smoke"
KNOWN_POOR_BBOX_SEED_POLICY = "known_poor_seed_only"
KNOWN_POOR_BBOX_SEED_SOURCE = "known_poor_bbox_seed"
DEFAULT_B1_SCENE_USD = Path("storey_1/scene_gs.usda")
DEFAULT_B1_MESH_SCENE_USD = Path("storey_1/scene.usd")
DEFAULT_B1_SCENE_BASE_USD = Path("storey_1/configuration/scene_base.usd")
DEFAULT_B1_VISUAL_ROUTE_SCENE_USD = Path(
    "data/robot-data-lab/scene-engine/data/B1_floor2_slow/usda/F2_all/default.usda"
)
DEFAULT_MAP12_NAV2 = Path("agibot/nav2.yaml")
DEFAULT_MAP12_OCCUPANCY = Path("agibot/occupancy.pgm")
DEFAULT_MAP12_MEMORY = Path("navigation_memory.json")
MIN_REVIEWABLE_IMAGE_STDDEV = 5.0
MIN_REVIEWABLE_IMAGE_COLOR_COUNT = 128


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Build the static B1 / robot_map_12 Digital Twin readiness artifact. "
            "Run this with .venv-isaaclab/bin/python so pxr.Usd is available."
        )
    )
    parser.add_argument("--b1-root", type=Path, required=True)
    parser.add_argument("--map12-root", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument(
        "--navigation-artifact",
        type=Path,
        help=(
            "Optional B1 navigation-smoke artifact. When it passes contract validation, "
            "the output readiness artifact may claim robot_navigation_supported=true."
        ),
    )
    parser.add_argument(
        "--alignment-artifact",
        type=Path,
        help=(
            "Optional B1 / Map 12 reviewed-correspondence residual artifact. "
            "Only passing residual evidence can promote map-scene alignment status."
        ),
    )
    parser.add_argument("--require-navigation-success", action="store_true")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    try:
        payload = build_readiness_artifact(args.b1_root, args.map12_root)
        if args.alignment_artifact is not None:
            alignment_payload = read_json_object(
                args.alignment_artifact,
                label="alignment artifact",
            )
            payload = readiness_artifact_with_alignment(
                payload,
                alignment_payload,
                alignment_artifact_path=args.alignment_artifact,
            )
        navigation_payload: dict[str, Any] | None = None
        if args.navigation_artifact is not None:
            navigation_payload = read_json_object(
                args.navigation_artifact,
                label="navigation artifact",
            )
            payload = readiness_artifact_with_navigation(
                payload,
                navigation_payload,
                navigation_artifact_path=args.navigation_artifact,
            )
    except (FileNotFoundError, ValueError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    errors = validate_readiness_artifact(
        payload,
        require_navigation_success=bool(args.require_navigation_success),
    )
    if args.require_navigation_success and navigation_payload is not None:
        errors.extend(
            f"navigation artifact: {error}"
            for error in validate_navigation_smoke_artifact(
                navigation_payload,
                require_files=True,
            )
        )
    payload["validation"] = {
        "status": "passed" if not errors else "failed",
        "errors": errors,
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(
        json.dumps(
            {
                "schema": READINESS_SCHEMA,
                "status": payload["validation"]["status"],
                "output": str(args.output),
                "robot_navigation_supported": payload.get("robot_navigation_supported"),
                "map12_overlay_status": payload.get("map12_overlay_status"),
                "errors": errors,
            },
            sort_keys=True,
        )
    )
    return 0 if not errors else 2


def build_readiness_artifact(b1_root: Path, map12_root: Path) -> dict[str, Any]:
    b1_root = Path(b1_root)
    map12_root = Path(map12_root)
    scene_layout = inspect_scene_engine_asset_layout(b1_root)
    primary_scene = inspect_usd_stage(b1_root / DEFAULT_B1_SCENE_USD)
    mesh_scene = inspect_usd_stage(b1_root / DEFAULT_B1_MESH_SCENE_USD)
    scene_base = inspect_usd_stage(b1_root / DEFAULT_B1_SCENE_BASE_USD)
    obj_meshes = [inspect_obj_mesh(path) for path in sorted((b1_root / "mesh-files").glob("*.obj"))]
    gaussian_plys = [
        inspect_ply_header(path)
        for path in sorted((b1_root / "point_cloud" / "iteration_100").glob("*.ply"))
    ]
    gaussian_layers = [_file_inventory(path) for path in sorted(b1_root.glob("*/scene_gs.usda"))]
    usd_scene_files = [_file_inventory(path) for path in sorted(b1_root.glob("*/scene.usd"))]
    map12 = inspect_map12(map12_root)
    overlay = build_overlay_report(
        scene_bounds=_dict(primary_scene.get("world_bounds")),
        map12=map12,
    )
    b1_geometry_loaded = bool(primary_scene.get("opened")) and bool(
        _dict(primary_scene.get("world_bounds")).get("valid")
    )
    blockers = []
    if not b1_geometry_loaded:
        blockers.append("B1 rebuilt scene USD did not open with finite world bounds.")
    if overlay["status"] == "blocked":
        blockers.append(str(overlay.get("reason") or "Map 12 overlay could not be derived."))
    return {
        "schema": READINESS_SCHEMA,
        "readiness_status": "static_ready_navigation_pending"
        if not blockers
        else "blocked_static_precheck",
        "static_precheck_only": True,
        "b1_root": str(b1_root),
        "map12_root": str(map12_root),
        "b1_geometry_loaded": b1_geometry_loaded,
        "b1_geometry_source": "rebuilt_scene_engine_usd_meshes",
        "b1_asset_layout": scene_layout,
        "b1_geometry": {
            "local_geometry": primary_scene,
            "gaussian_scene_usd": primary_scene,
            "full_floor_usd": mesh_scene,
            "full_floor_default_usd": scene_base,
            "renderable_robot_view_usd": scene_base,
            "scene_engine_layout": scene_layout,
            "scene_partitions": scene_layout["partitions"],
            "usd_scene_files": usd_scene_files,
            "obj_meshes": obj_meshes,
            "gaussian_point_clouds": gaussian_plys,
            "gaussian_layers": gaussian_layers,
        },
        "usd_object_index_ready": False,
        "usd_receptacle_index_ready": False,
        "reason": "B1 assets are currently coarse meshes without object-level segmentation",
        "map12": map12,
        "map12_overlay_status": overlay["status"],
        "map12_to_b1_usd_transform_status": overlay["transform_status"],
        "map12_overlay": overlay,
        "semantic_source": SEMANTIC_SOURCE,
        "semantic_usd_binding_status": SEMANTIC_USD_BLOCKED,
        "semantic_anchors_are_usd_truth": False,
        "robot_navigation_supported": False,
        "robot_navigation_provenance": "pending_local_isaac_b1_map12_navigation_smoke",
        "robot_navigation_pending_reason": (
            "Static geometry and overlay evidence does not prove robot navigation. "
            "Run the local Isaac B1 / Map 12 navigation smoke before setting "
            "robot_navigation_supported=true."
        ),
        "candidate_navigation_waypoint_count": len(overlay.get("candidate_waypoints") or []),
        "navigation_waypoint_count": 0,
        "robot_view_evidence_status": "pending_local_isaac_navigation_smoke",
        "manipulation_supported": False,
        "blocked_capabilities": [
            "semantic_usd_object_receptacle_binding",
            "pick_place_manipulation",
            "planner_backed_nav2_parity",
        ],
        "blockers": blockers,
    }


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


def readiness_artifact_with_navigation(
    readiness: dict[str, Any],
    navigation: dict[str, Any],
    *,
    navigation_artifact_path: Path | None = None,
) -> dict[str, Any]:
    payload = json.loads(json.dumps(readiness))
    navigation_errors = validate_navigation_smoke_artifact(navigation, require_files=True)
    payload["static_precheck_only"] = False
    payload["navigation_smoke"] = {
        "artifact": str(navigation_artifact_path) if navigation_artifact_path else "",
        "status": navigation.get("status"),
        "validation_status": "passed" if not navigation_errors else "failed",
        "validation_errors": navigation_errors,
    }
    if navigation_errors:
        payload["robot_navigation_supported"] = False
        payload["robot_navigation_provenance"] = "blocked_local_isaac_b1_map12_navigation_smoke"
        payload["robot_navigation_pending_reason"] = "; ".join(navigation_errors)
        payload["robot_view_evidence_status"] = "blocked"
        payload["navigation_waypoint_count"] = 0
        return payload
    payload["readiness_status"] = "navigation_ready"
    payload["robot_navigation_supported"] = True
    payload["robot_navigation_provenance"] = NAVIGATION_PROVENANCE
    payload["robot_navigation_pending_reason"] = ""
    payload["robot_view_evidence_status"] = "available"
    payload["navigation_waypoint_count"] = int(navigation.get("navigation_waypoint_count") or 0)
    payload["navigation_provenance"] = navigation.get("navigation_provenance")
    payload["navigation_artifact"] = (
        str(navigation_artifact_path) if navigation_artifact_path else ""
    )
    return payload


def readiness_artifact_with_alignment(
    readiness: dict[str, Any],
    alignment: dict[str, Any],
    *,
    alignment_artifact_path: Path | None = None,
) -> dict[str, Any]:
    payload = json.loads(json.dumps(readiness))
    alignment_errors = validate_alignment_residual_artifact(alignment)
    residual = _dict(alignment.get("residual_evidence"))
    area_alignment = [
        item for item in alignment.get("area_alignment") or [] if isinstance(item, dict)
    ]
    selected_transform = _dict(alignment.get("selected_transform"))
    payload["alignment_artifact"] = str(alignment_artifact_path) if alignment_artifact_path else ""
    payload["alignment_validation"] = {
        "status": "passed" if not alignment_errors else "failed",
        "errors": alignment_errors,
    }
    payload["residual_evidence"] = {
        "status": residual.get("status") or "not_available",
        "matched_anchor_count": int(residual.get("matched_anchor_count") or 0),
        "mean_residual_m": residual.get("mean_residual_m"),
        "median_residual_m": residual.get("median_residual_m"),
        "p90_residual_m": residual.get("p90_residual_m"),
        "max_residual_m": residual.get("max_residual_m"),
        "source": residual.get("source") or "",
        "transform_source": residual.get("transform_source") or "",
        "artifact": str(alignment_artifact_path) if alignment_artifact_path else "",
    }
    map12_overlay = payload.setdefault("map12_overlay", {})
    map12_overlay["residual_evidence"] = payload["residual_evidence"]
    map12_overlay["bbox_seed_policy"] = KNOWN_POOR_BBOX_SEED_POLICY
    map12_overlay["verified_transform"] = selected_transform
    payload["area_alignment"] = area_alignment
    if alignment_errors:
        payload["map12_overlay_status"] = "candidate"
        payload["map12_to_b1_usd_transform_status"] = "unverified"
        map12_overlay["status"] = "candidate"
        map12_overlay["transform_status"] = "unverified"
        payload["readiness_alignment_status"] = "alignment_artifact_invalid"
        return payload
    if alignment.get("global_alignment_status") == "verified":
        payload["map12_overlay_status"] = "verified"
        payload["map12_to_b1_usd_transform_status"] = "verified"
        map12_overlay["status"] = "verified"
        map12_overlay["transform_status"] = "verified"
        map12_overlay["candidate_waypoints"] = residual_backed_candidate_waypoints(
            payload,
            selected_transform=selected_transform,
            alignment_artifact_path=alignment_artifact_path,
        )
        payload["candidate_navigation_waypoint_count"] = len(
            map12_overlay.get("candidate_waypoints") or []
        )
        payload["readiness_alignment_status"] = "global_verified"
        return payload
    if any(item.get("alignment_status") == "verified" for item in area_alignment):
        payload["map12_overlay_status"] = "candidate"
        payload["map12_to_b1_usd_transform_status"] = "area_verified_only"
        map12_overlay["status"] = "candidate"
        map12_overlay["transform_status"] = "area_verified_only"
        payload["readiness_alignment_status"] = "area_verified_only"
        return payload
    payload["map12_overlay_status"] = "candidate"
    payload["map12_to_b1_usd_transform_status"] = "unverified"
    map12_overlay["status"] = "candidate"
    map12_overlay["transform_status"] = "unverified"
    payload["readiness_alignment_status"] = "alignment_candidate"
    return payload


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


def validate_readiness_artifact(
    payload: dict[str, Any],
    *,
    require_navigation_success: bool = False,
) -> list[str]:
    errors: list[str] = []
    _require(payload.get("schema") == READINESS_SCHEMA, "unexpected readiness schema", errors)
    _require(payload.get("b1_geometry_loaded") is True, "B1 geometry is not loaded", errors)
    _require(
        payload.get("usd_object_index_ready") is False,
        "B1 USD object index must remain false until segmentation or manifest exists",
        errors,
    )
    _require(
        payload.get("usd_receptacle_index_ready") is False,
        "B1 USD receptacle index must remain false until segmentation or manifest exists",
        errors,
    )
    _require(
        payload.get("semantic_source") == SEMANTIC_SOURCE,
        "semantic source must be Map 12 navigation-memory overlay",
        errors,
    )
    _require(
        payload.get("semantic_usd_binding_status") == SEMANTIC_USD_BLOCKED,
        "semantic USD binding must remain blocked",
        errors,
    )
    _require(
        payload.get("semantic_anchors_are_usd_truth") is False,
        "semantic anchors must not be presented as USD prim truth",
        errors,
    )
    _require(
        payload.get("manipulation_supported") is False,
        "manipulation must not be presented as supported",
        errors,
    )
    _require(
        payload.get("map12_overlay_status") in {"candidate", "verified", "blocked"},
        "overlay status must be candidate, verified, or blocked",
        errors,
    )
    _require(
        payload.get("map12_to_b1_usd_transform_status")
        in {"unverified", "verified", "blocked", "area_verified_only"},
        "map-scene transform status must be unverified, verified, blocked, or area_verified_only",
        errors,
    )
    map12_overlay = _dict(payload.get("map12_overlay"))
    if map12_overlay:
        _require(
            map12_overlay.get("bbox_seed_policy") == KNOWN_POOR_BBOX_SEED_POLICY,
            "bbox seed must be labeled known_poor_seed_only",
            errors,
        )
        transform = _dict(map12_overlay.get("transform"))
        if transform:
            _require(
                transform.get("source") == KNOWN_POOR_BBOX_SEED_SOURCE,
                "bbox-fit transform must be labeled known_poor_bbox_seed",
                errors,
            )
    if payload.get("map12_overlay_status") == "verified":
        residual = _dict(payload.get("residual_evidence"))
        _require(
            residual.get("status") == "available",
            "verified overlay requires residual evidence",
            errors,
        )
        _require(
            int(residual.get("matched_anchor_count") or 0) >= 6,
            "verified overlay requires at least six matched anchors",
            errors,
        )
        _require(
            residual.get("transform_source") != KNOWN_POOR_BBOX_SEED_SOURCE,
            "verified overlay must not use known-poor bbox seed",
            errors,
        )
        verified_transform = _dict(map12_overlay.get("verified_transform"))
        _require(
            verified_transform.get("source") != KNOWN_POOR_BBOX_SEED_SOURCE
            and verified_transform.get("method")
            != "bbox_fit_navigation_memory_nav_goals_to_scene_usd_bounds",
            "verified overlay cannot use the bbox-fit transform as its verified transform",
            errors,
        )
    if payload.get("map12_to_b1_usd_transform_status") == "area_verified_only":
        area_rows = [item for item in payload.get("area_alignment") or [] if isinstance(item, dict)]
        _require(
            any(item.get("alignment_status") == "verified" for item in area_rows),
            "area_verified_only requires at least one verified area alignment",
            errors,
        )
    if payload.get("static_precheck_only") is True:
        _require(
            payload.get("robot_navigation_supported") is not True,
            "static-only readiness must not claim robot navigation support",
            errors,
        )
    if payload.get("robot_navigation_supported") is True:
        _require(
            payload.get("robot_navigation_provenance") == NAVIGATION_PROVENANCE,
            "navigation support requires B1 navigation-smoke provenance",
            errors,
        )
        _require(
            int(payload.get("navigation_waypoint_count") or 0) >= 2,
            "navigation support requires at least two waypoints",
            errors,
        )
        _require(
            payload.get("robot_view_evidence_status") == "available",
            "navigation support requires robot-view evidence",
            errors,
        )
    elif require_navigation_success:
        errors.append("robot_navigation_supported is not true")
    return errors


def validate_alignment_residual_artifact(payload: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    _require(
        payload.get("schema") == ALIGNMENT_RESIDUALS_SCHEMA,
        "unexpected alignment residual schema",
        errors,
    )
    _require(
        payload.get("bbox_seed_policy") == KNOWN_POOR_BBOX_SEED_POLICY,
        "alignment artifact must label bbox seed as known_poor_seed_only",
        errors,
    )
    _require(
        payload.get("manipulation_supported") is False,
        "alignment artifact must not claim manipulation support",
        errors,
    )
    _require(
        payload.get("object_receptacle_usd_binding_status") == "blocked_out_of_scope",
        "alignment artifact must keep object/receptacle USD binding blocked",
        errors,
    )
    residual = _dict(payload.get("residual_evidence"))
    selected_transform = _dict(payload.get("selected_transform"))
    if payload.get("global_alignment_status") == "verified":
        _require(
            residual.get("status") == "available",
            "verified alignment requires available residual evidence",
            errors,
        )
        _require(
            int(residual.get("matched_anchor_count") or 0) >= 6,
            "verified alignment requires at least six matched anchors",
            errors,
        )
        _require(
            residual.get("transform_source") != KNOWN_POOR_BBOX_SEED_SOURCE,
            "verified alignment must not use known-poor bbox seed",
            errors,
        )
        _require(
            selected_transform.get("source") != KNOWN_POOR_BBOX_SEED_SOURCE
            and selected_transform.get("method")
            != "bbox_fit_navigation_memory_nav_goals_to_scene_usd_bounds",
            "verified alignment transform must not come from bbox-fit seed",
            errors,
        )
    for area in payload.get("area_alignment") or []:
        if not isinstance(area, dict) or area.get("alignment_status") != "verified":
            continue
        _require(
            int(area.get("matched_anchor_count") or 0) >= 3,
            "verified area alignment requires at least three accepted anchors",
            errors,
        )
    return errors


def validate_navigation_smoke_artifact(
    payload: dict[str, Any],
    *,
    require_files: bool = False,
) -> list[str]:
    errors: list[str] = []
    _require(
        payload.get("schema") == NAVIGATION_SMOKE_SCHEMA,
        "unexpected navigation schema",
        errors,
    )
    _require(payload.get("status") == "passed", "navigation smoke did not pass", errors)
    _require(
        payload.get("robot_navigation_supported") is True,
        "navigation artifact must claim robot_navigation_supported=true only on pass",
        errors,
    )
    _require(
        payload.get("robot_navigation_provenance") == NAVIGATION_PROVENANCE,
        "navigation artifact provenance must be isaac_b1_map12_navigation_smoke",
        errors,
    )
    _require(
        payload.get("navigation_provenance") in {"kinematic_pose_driven", "planner_backed"},
        "navigation artifact must state kinematic or planner-backed provenance",
        errors,
    )
    _require(
        bool(payload.get("alignment_artifact")),
        "navigation artifact requires residual-backed alignment artifact provenance",
        errors,
    )
    _require(
        str(payload.get("b1_scene_usd") or "") == str(DEFAULT_B1_VISUAL_ROUTE_SCENE_USD),
        "navigation artifact must render the verified B1_floor2_slow visual route",
        errors,
    )
    _require(
        str(payload.get("alignment_transform_source") or "") == "reviewed_correspondence_fit",
        "navigation artifact requires reviewed correspondence transform source",
        errors,
    )
    _require(
        payload.get("planner_backed") in {True, False},
        "planner_backed must be explicit",
        errors,
    )
    _require(
        payload.get("semantic_source") == SEMANTIC_SOURCE,
        "navigation semantic source must remain Map 12 overlay",
        errors,
    )
    _require(
        payload.get("semantic_usd_binding_status") == SEMANTIC_USD_BLOCKED,
        "navigation artifact must not claim semantic USD binding",
        errors,
    )
    _require(
        payload.get("manipulation_supported") is False,
        "navigation artifact must not claim manipulation support",
        errors,
    )
    waypoints = [item for item in payload.get("waypoint_evidence") or [] if isinstance(item, dict)]
    _require(
        len(waypoints) >= 2,
        "navigation artifact needs at least two waypoint evidence rows",
        errors,
    )
    _require(
        int(payload.get("navigation_waypoint_count") or 0) >= 2,
        "navigation waypoint count must be at least two",
        errors,
    )
    errors.extend(
        validate_robot_view_waypoint_evidence(
            waypoints,
            require_files=require_files,
            expected_scene_usd=DEFAULT_B1_VISUAL_ROUTE_SCENE_USD,
            expected_scene_usd_label="B1_floor2_slow visual route",
            required_views=("fpv",),
            reviewable_views=("fpv", "chase"),
            require_distinct_robot_poses=True,
            distinct_pose_error="navigation waypoint robot poses must be distinct",
        )
    )
    return errors


def validate_robot_view_waypoint_evidence(
    waypoints: list[dict[str, Any]],
    *,
    require_files: bool = False,
    expected_scene_usd: Path | str | None = None,
    expected_scene_usd_label: str = "",
    required_views: tuple[str, ...] = ("fpv",),
    reviewable_views: tuple[str, ...] = ("fpv", "chase"),
    require_distinct_robot_poses: bool = False,
    distinct_pose_error: str = "waypoint robot poses must be distinct",
) -> list[str]:
    errors: list[str] = []
    if require_distinct_robot_poses:
        pose_keys = {
            (
                round(float(_dict(item.get("robot_pose")).get("x") or 0.0), 3),
                round(float(_dict(item.get("robot_pose")).get("y") or 0.0), 3),
            )
            for item in waypoints
        }
        _require(len(pose_keys) >= 2, distinct_pose_error, errors)
    for index, item in enumerate(waypoints, start=1):
        views = _dict(item.get("views"))
        _require(
            item.get("robot_pose_applied") is True,
            f"waypoint {index} robot pose must be applied in Isaac",
            errors,
        )
        _require(
            bool(item.get("alignment_artifact")),
            f"waypoint {index} missing alignment artifact provenance",
            errors,
        )
        _require(
            str(item.get("alignment_transform_source") or "") == "reviewed_correspondence_fit",
            f"waypoint {index} requires reviewed correspondence transform source",
            errors,
        )
        if expected_scene_usd is not None:
            _require(
                str(item.get("scene_usd") or "") == str(expected_scene_usd),
                f"waypoint {index} must render {expected_scene_usd_label or expected_scene_usd}",
                errors,
            )
        for view_name in required_views:
            _require(
                bool(views.get(view_name)),
                f"waypoint {index} missing {view_name.upper()} image",
                errors,
            )
        if require_files:
            for view_name, raw_path in views.items():
                if not raw_path:
                    continue
                path = Path(str(raw_path))
                exists = path.is_file()
                _require(
                    exists,
                    f"waypoint {index} view {view_name} missing: {path}",
                    errors,
                )
                if exists and view_name in set(reviewable_views):
                    errors.extend(
                        f"waypoint {index} {view_name}: {error}"
                        for error in reviewable_image_errors(path)
                    )
    return errors


def validate_waypoint_pose_requests_artifact(payload: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    _require(
        payload.get("schema") == WAYPOINT_POSE_REQUESTS_SCHEMA,
        "unexpected waypoint pose request schema",
        errors,
    )
    _require(
        payload.get("status") in {"ready", "blocked"},
        "waypoint pose request status must be ready or blocked",
        errors,
    )
    _require(
        payload.get("semantic_source") == SEMANTIC_SOURCE,
        "waypoint pose request semantic source must remain Map 12 overlay",
        errors,
    )
    _require(
        payload.get("alignment_transform_source") in {"reviewed_correspondence_fit", ""},
        "waypoint pose requests require reviewed correspondence transform",
        errors,
    )
    _require(
        payload.get("planner_backed") is False,
        "waypoint pose requests must not claim planner-backed navigation",
        errors,
    )
    _require(
        payload.get("physical_robot") is False,
        "waypoint pose requests must not claim physical robot navigation",
        errors,
    )
    _require(
        payload.get("robot_navigation_supported") is False,
        "waypoint pose requests are pose conversion artifacts, not navigation proof",
        errors,
    )
    waypoints = [item for item in payload.get("waypoints") or [] if isinstance(item, dict)]
    blocked = [item for item in payload.get("blocked_requests") or [] if isinstance(item, dict)]
    _require(
        int(payload.get("waypoint_count") or 0) == len(waypoints),
        "waypoint_count must match ready waypoint rows",
        errors,
    )
    _require(
        int(payload.get("blocked_request_count") or 0) == len(blocked),
        "blocked_request_count must match blocked request rows",
        errors,
    )
    if payload.get("status") == "ready":
        _require(
            bool(payload.get("alignment_artifact")),
            "ready requests need alignment artifact",
            errors,
        )
        _require(len(waypoints) >= 1, "ready requests need at least one waypoint", errors)
        _require(not blocked, "ready requests must not contain blocked rows", errors)
    else:
        _require(
            bool(blocked) or bool(payload.get("artifact_errors")),
            "blocked requests need blocked rows or artifact errors",
            errors,
        )
    for index, item in enumerate(waypoints, start=1):
        coverage = _dict(item.get("coverage_decision"))
        _require(bool(item.get("waypoint_id")), f"waypoint {index} missing waypoint_id", errors)
        _require(
            str(item.get("alignment_transform_source") or "") == "reviewed_correspondence_fit",
            f"waypoint {index} requires reviewed correspondence transform source",
            errors,
        )
        _require(
            bool(item.get("alignment_artifact")),
            f"waypoint {index} missing alignment artifact",
            errors,
        )
        _require(
            isinstance(item.get("map12_nav_goal"), dict)
            and _has_xy(_dict(item.get("map12_nav_goal"))),
            f"waypoint {index} missing Map12 x/y nav goal",
            errors,
        )
        _require(
            isinstance(item.get("b1_pose"), dict),
            f"waypoint {index} missing B1 scene pose",
            errors,
        )
        _require(
            coverage.get("status") in {"verified_global", "verified_local_area"},
            f"waypoint {index} missing verified coverage decision",
            errors,
        )
        _require(
            item.get("planner_backed") is False and item.get("physical_robot") is False,
            f"waypoint {index} must not claim planner-backed or physical navigation",
            errors,
        )
    for index, item in enumerate(blocked, start=1):
        _require(bool(item.get("reason")), f"blocked request {index} missing reason", errors)
        _require(
            item.get("request_status") == "blocked",
            f"blocked request {index} must have request_status=blocked",
            errors,
        )
    return errors


def reviewable_image_errors(path: Path) -> list[str]:
    try:
        with Image.open(path) as image:
            image.verify()
        with Image.open(path) as image:
            rgb = image.convert("RGB")
            stat = ImageStat.Stat(rgb)
            extrema = rgb.getextrema()
            colors = rgb.getcolors(maxcolors=1_000_000)
    except Exception as exc:
        return [f"image is unreadable: {exc}"]
    errors: list[str] = []
    if all(high <= low for low, high in extrema):
        errors.append("image appears blank")
    if max(stat.stddev or [0.0]) < MIN_REVIEWABLE_IMAGE_STDDEV:
        errors.append("image has too little visual detail")
    if colors is not None and len(colors) < MIN_REVIEWABLE_IMAGE_COLOR_COUNT:
        errors.append("image has too few distinct colors")
    return errors


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


def residual_backed_candidate_waypoints(
    readiness: dict[str, Any],
    *,
    selected_transform: dict[str, Any],
    alignment_artifact_path: Path | None,
) -> list[dict[str, Any]]:
    if str(selected_transform.get("source") or "") != "reviewed_correspondence_fit":
        return []
    map12 = _dict(readiness.get("map12"))
    anchors = [
        anchor
        for anchor in map12.get("anchors") or []
        if isinstance(anchor, dict) and _has_xy(_dict(anchor.get("nav_goal")))
    ]
    waypoints = []
    for anchor in anchors[: min(4, len(anchors))]:
        waypoint = residual_backed_waypoint_from_nav_goal(
            nav_goal=_dict(anchor.get("nav_goal")),
            waypoint_id=f"b1_aligned_{anchor['id']}",
            label=str(anchor.get("label") or anchor["id"]),
            source_anchor_id=str(anchor["id"]),
            transform=selected_transform,
            alignment_artifact_path=alignment_artifact_path,
        )
        if waypoint:
            waypoints.append(waypoint)
    return waypoints


def residual_backed_waypoint_from_nav_goal(
    nav_goal: dict[str, Any],
    *,
    waypoint_id: str,
    label: str = "",
    source_anchor_id: str = "",
    transform: dict[str, Any],
    alignment_artifact_path: Path | None,
    coverage_decision: dict[str, Any] | None = None,
) -> dict[str, Any]:
    if not _has_xy(nav_goal):
        return {}
    if str(transform.get("source") or "") != "reviewed_correspondence_fit":
        raise ValueError("Map12 waypoint conversion requires reviewed_correspondence_fit")
    yaw = _optional_float(nav_goal.get("yaw"))
    yaw_deg = (
        math.degrees(yaw) if yaw is not None else _optional_float(nav_goal.get("yaw_deg")) or 0.0
    )
    scene_xy = _apply_reviewed_scene_transform(
        [float(nav_goal["x"]), float(nav_goal["y"])], transform
    )
    return {
        "waypoint_id": waypoint_id,
        "source_anchor_id": source_anchor_id,
        "label": label or waypoint_id,
        "semantic_source": SEMANTIC_SOURCE,
        "alignment_artifact": str(alignment_artifact_path) if alignment_artifact_path else "",
        "alignment_transform_source": "reviewed_correspondence_fit",
        "selected_transform_type": str(transform.get("type") or ""),
        "coverage_decision": dict(
            coverage_decision
            or {
                "status": "verified_global",
                "fit_scope": "global_transform",
            }
        ),
        "map12_nav_goal": nav_goal,
        "b1_pose": {
            "frame": str(transform.get("target_frame") or "b1_rebuilt_scene_usd_world"),
            "x": round(scene_xy[0], 6),
            "y": round(scene_xy[1], 6),
            "z": 0.0,
            "yaw_deg": round(float(yaw_deg) + float(transform.get("yaw_deg") or 0.0), 6),
            "pose_source": "reviewed_correspondence_fit",
        },
        "request_status": "pose_request_only",
        "planner_backed": False,
        "physical_robot": False,
    }


def _apply_reviewed_scene_transform(point: list[float], transform: dict[str, Any]) -> list[float]:
    scale = float(transform.get("scale") or 1.0)
    rotation = transform.get("rotation_matrix")
    if not (
        isinstance(rotation, list)
        and len(rotation) == 2
        and all(isinstance(row, list) and len(row) == 2 for row in rotation)
    ):
        rotation = [[1.0, 0.0], [0.0, 1.0]]
    translation = transform.get("translation")
    if not isinstance(translation, list) or len(translation) != 2:
        translation = [0.0, 0.0]
    x = scale * (float(rotation[0][0]) * point[0] + float(rotation[0][1]) * point[1]) + float(
        translation[0]
    )
    y = scale * (float(rotation[1][0]) * point[0] + float(rotation[1][1]) * point[1]) + float(
        translation[1]
    )
    return [x, y]


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


def _require(condition: bool, message: str, errors: list[str]) -> None:
    if not condition:
        errors.append(message)


if __name__ == "__main__":
    raise SystemExit(main())
