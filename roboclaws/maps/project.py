from __future__ import annotations

from pathlib import Path
from typing import Any

from roboclaws.core.json_sources import read_json_object
from roboclaws.maps.bundle import (
    DEFAULT_COSTMAP_PARAMETERS,
    metric_map_bundle_metadata,
    parse_map_yaml,
    validate_nav2_map_bundle,
)
from roboclaws.maps.rasterize import OccupancyGrid, load_pgm
from roboclaws.maps.spatial_contract import (
    ALIGNMENT_STATUS_NATIVE,
    GEOMETRY_SOURCE_OPERATOR_NAVIGATION_ZONE,
    POLYGON_ROLE_NAVIGATION_AREA,
    normalize_spatial_rooms,
)

REAL_ROBOT_MAP_BUNDLE_SCHEMA = "real_robot_map_bundle_v1"
REALWORLD_CONTRACT = "realworld_cleanup_v1"


def metric_map_from_bundle(
    bundle_dir: Path,
    *,
    contract: str = REALWORLD_CONTRACT,
) -> dict[str, Any]:
    _validate_projection_source_bundle(bundle_dir)
    semantics = _read_bundle_semantics(bundle_dir)
    map_yaml = parse_map_yaml((bundle_dir / "map.yaml").read_text(encoding="utf-8"))
    resolution = float(map_yaml.get("resolution") or DEFAULT_COSTMAP_PARAMETERS["resolution_m"])
    origin = map_yaml.get("origin") if isinstance(map_yaml.get("origin"), list) else [0.0, 0.0, 0.0]
    grid = _load_bundle_occupancy_grid(bundle_dir, map_yaml)
    map_id = str(semantics.get("map_id") or bundle_dir.name)
    map_version = str(semantics.get("map_version") or "base-metric-map-v1")
    frame_id = _source_map_frame_id(semantics)
    rooms = normalize_spatial_rooms(
        semantics.get("rooms") or [],
        frame_id=frame_id,
        polygon_role=POLYGON_ROLE_NAVIGATION_AREA,
        geometry_source=GEOMETRY_SOURCE_OPERATOR_NAVIGATION_ZONE,
        alignment_status=ALIGNMENT_STATUS_NATIVE,
    )
    waypoints = []
    for item in semantics.get("inspection_waypoints") or []:
        waypoint = dict(item)
        waypoint.setdefault("frame_id", frame_id)
        waypoint["visited"] = False
        waypoints.append(waypoint)
    robot_pose = (
        {
            "frame_id": frame_id,
            **_waypoint_pose(waypoints[0]),
            "waypoint_id": waypoints[0]["waypoint_id"],
        }
        if waypoints
        else {"frame_id": frame_id, "x": 0.0, "y": 0.0, "yaw": 0.0, "waypoint_id": ""}
    )
    return {
        "ok": True,
        "tool": "metric_map",
        "status": "ok",
        "contract": contract,
        "schema": REAL_ROBOT_MAP_BUNDLE_SCHEMA,
        "frame_id": frame_id,
        "spatial_contract": semantics.get("spatial_contract") or {},
        "display_frame": semantics.get("display_frame") if "display_frame" in semantics else None,
        "map_id": map_id,
        "map_version": map_version,
        "resolution_m": resolution,
        "origin": {
            "x": float(origin[0] if len(origin) > 0 else 0.0),
            "y": float(origin[1] if len(origin) > 1 else 0.0),
            "yaw": float(origin[2] if len(origin) > 2 else 0.0),
        },
        "width": grid.width,
        "height": grid.height,
        "occupancy_values": {"unknown": -1, "free": 0, "occupied": 100},
        "occupancy_grid_artifact": "map_bundle/map.pgm",
        "map_bundle": metric_map_bundle_metadata(
            environment_id=str(semantics.get("environment_id") or bundle_dir.name),
            map_id=map_id,
            map_version=map_version,
        ),
        "rooms": rooms,
        "driveable_ways": semantics.get("driveable_ways") or [],
        "robot_pose": robot_pose,
        "inspection_waypoints": waypoints,
        "public_contract_note": (
            "Metric map projection was derived from a prebuilt Nav2 map bundle. "
            "Runtime movable objects and private scoring truth are not encoded."
        ),
    }


def static_landmarks_from_bundle(bundle_dir: Path) -> list[dict[str, Any]]:
    _validate_projection_source_bundle(bundle_dir)
    semantics = _read_bundle_semantics(bundle_dir)
    return [
        dict(item) for item in semantics.get("static_landmarks") or [] if isinstance(item, dict)
    ]


def occupancy_grid_from_bundle(bundle_dir: Path) -> OccupancyGrid:
    _validate_projection_source_bundle(bundle_dir)
    map_yaml = parse_map_yaml((bundle_dir / "map.yaml").read_text(encoding="utf-8"))
    return _load_bundle_occupancy_grid(bundle_dir, map_yaml)


def _load_bundle_occupancy_grid(
    bundle_dir: Path,
    map_yaml: dict[str, Any],
) -> OccupancyGrid:
    resolution = float(map_yaml.get("resolution") or DEFAULT_COSTMAP_PARAMETERS["resolution_m"])
    origin = map_yaml.get("origin") if isinstance(map_yaml.get("origin"), list) else [0.0, 0.0]
    return load_pgm(
        bundle_dir / str(map_yaml.get("image") or "map.pgm"),
        resolution_m=resolution,
        origin_x=float(origin[0] if len(origin) > 0 else 0.0),
        origin_y=float(origin[1] if len(origin) > 1 else 0.0),
    )


def _waypoint_pose(waypoint: dict[str, Any]) -> dict[str, float]:
    return {
        "x": float(waypoint.get("x", 0.0)),
        "y": float(waypoint.get("y", 0.0)),
        "yaw": float(waypoint.get("yaw", 0.0)),
    }


def _source_map_frame_id(semantics: dict[str, Any]) -> str:
    frame_ids = semantics.get("frame_ids") if isinstance(semantics.get("frame_ids"), dict) else {}
    return str(frame_ids.get("map") or "map")


def _validate_projection_source_bundle(bundle_dir: Path) -> None:
    validate_nav2_map_bundle(bundle_dir).raise_for_errors()


def _read_bundle_semantics(bundle_dir: Path) -> dict[str, Any]:
    return read_json_object(bundle_dir / "semantics.json", label="Nav2 semantics")
