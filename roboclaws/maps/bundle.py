from __future__ import annotations

import argparse
import copy
import hashlib
import json
import shutil
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from roboclaws.core.json_sources import read_json_object
from roboclaws.maps.bundle_validation import (
    parse_map_yaml as parse_map_yaml,
)
from roboclaws.maps.bundle_validation import (
    validate_base_metric_map_v1_payload,
    validate_nav2_map_bundle_payload,
)
from roboclaws.maps.preview import render_base_metric_map_bundle_preview
from roboclaws.maps.rasterize import (
    occupancy_grid_from_metric_map,
    write_pgm,
)
from roboclaws.maps.spatial_contract import (
    ALIGNMENT_STATUS_NATIVE,
    GEOMETRY_SOURCE_OPERATOR_NAVIGATION_ZONE,
    POLYGON_ROLE_NAVIGATION_AREA,
    normalize_spatial_rooms,
    source_frame_spatial_contract,
)

NAV2_MAP_BUNDLE_SCHEMA = "nav2_map_bundle_v1"
NAV2_MAP_BUNDLE_SNAPSHOT_SCHEMA = "nav2_map_bundle_snapshot_v1"
DEFAULT_ROBOT_PROFILE_ID = "rby1m"
DEFAULT_COSTMAP_PROFILE_ID = "rby1m_static_global"
DEFAULT_COSTMAP_PARAMETERS = {
    "resolution_m": 0.05,
    "inflation_radius_m": 0.45,
    "cost_scaling_factor": 3.0,
    "occupied_threshold": 0.65,
    "free_threshold": 0.25,
}
DEFAULT_ROBOT_PROFILE = {
    "robot_profile_id": DEFAULT_ROBOT_PROFILE_ID,
    "base_frame_id": "base_link",
    "map_frame_id": "map",
    "footprint": {"type": "radius", "radius_m": 0.35},
    "camera": {"frame_id": "head_camera_rgb_optical_frame", "mount": "rby1m_head"},
    "navigation_tolerances": {"xy_goal_tolerance_m": 0.25, "yaw_goal_tolerance_rad": 0.35},
}
RUNTIME_COSTMAP_GAPS = (
    "runtime_obstacle_layer_not_simulated",
    "voxel_layer_not_simulated",
    "rolling_local_costmap_not_simulated",
    "tf_timing_not_simulated",
)
PRIVATE_MAP_KEYS = frozenset(
    {
        "acceptable_destination_sets",
        "generated_mess_set",
        "global_movable_object_inventory",
        "is_misplaced",
        "private_manifest",
        "target_receptacle_id",
        "valid_receptacle_ids",
    }
)


@dataclass(frozen=True)
class MapBundleValidation:
    root: Path
    errors: tuple[str, ...]
    warnings: tuple[str, ...]
    metadata: dict[str, Any]

    @property
    def ok(self) -> bool:
        return not self.errors

    def as_dict(self) -> dict[str, Any]:
        return {
            "schema": "nav2_map_bundle_validation_v1",
            "root": str(self.root),
            "ok": self.ok,
            "errors": list(self.errors),
            "warnings": list(self.warnings),
            "metadata": self.metadata,
        }

    def raise_for_errors(self, *, label: str = "Nav2 map bundle") -> None:
        if self.errors:
            raise AssertionError(f"invalid {label} {self.root}: {self.errors}")


def metric_map_bundle_metadata(
    *,
    environment_id: str,
    map_id: str,
    map_version: str,
    artifact_root: str = "map_bundle",
) -> dict[str, Any]:
    parameters = {
        "environment_id": environment_id,
        "map_id": map_id,
        "map_version": map_version,
        "robot_profile_id": DEFAULT_ROBOT_PROFILE_ID,
        "costmap_profile_id": DEFAULT_COSTMAP_PROFILE_ID,
        "costmap_defaults": DEFAULT_COSTMAP_PARAMETERS,
    }
    return {
        "schema": NAV2_MAP_BUNDLE_SCHEMA,
        "environment_id": environment_id,
        "map_id": map_id,
        "map_version": map_version,
        "source_provenance": "molmospaces_base_metric_map",
        "robot_profile_id": DEFAULT_ROBOT_PROFILE_ID,
        "costmap_profile_id": DEFAULT_COSTMAP_PROFILE_ID,
        "artifact_paths": _bundle_relative_paths(artifact_root=artifact_root),
        "costmap_defaults": dict(DEFAULT_COSTMAP_PARAMETERS),
        "runtime_costmap_gaps": list(RUNTIME_COSTMAP_GAPS),
        "parameter_hash": _stable_hash(parameters),
        "public_contract_note": (
            "Map bundle paths are public static environment artifacts. Runtime movable "
            "objects and private scoring truth are not encoded in this bundle."
        ),
    }


def write_nav2_map_bundle_snapshot(
    *,
    run_dir: Path,
    metric_map: dict[str, Any],
    static_landmarks: list[dict[str, Any]],
) -> dict[str, Any]:
    bundle_dir = run_dir / "map_bundle"
    snapshot = write_nav2_map_bundle(
        bundle_dir,
        metric_map=metric_map,
        static_landmarks=static_landmarks,
    )
    snapshot["schema"] = NAV2_MAP_BUNDLE_SNAPSHOT_SCHEMA
    snapshot["snapshot_root"] = "map_bundle"
    snapshot["artifact_paths"] = {
        key: (bundle_dir / relative).relative_to(run_dir).as_posix()
        for key, relative in _bundle_local_paths().items()
    }
    return snapshot


def copy_nav2_map_bundle_snapshot(
    *,
    source_bundle_dir: Path,
    run_dir: Path,
) -> dict[str, Any]:
    """Copy a validated Base Metric Map bundle into a run-local snapshot."""
    source_bundle_dir = Path(source_bundle_dir)
    validation = validate_base_metric_map_v1_bundle(source_bundle_dir)
    validation.raise_for_errors(label="Base Metric Map v1 bundle")

    bundle_dir = Path(run_dir) / "map_bundle"
    for key, relative in _bundle_local_paths().items():
        source = source_bundle_dir / relative
        destination = bundle_dir / relative
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, destination)
    write_source_frame_bundle_preview(bundle_dir, output_path=bundle_dir / "preview.png")

    snapshot = _existing_bundle_snapshot(
        bundle_dir=bundle_dir,
        run_dir=Path(run_dir),
        source_bundle_dir=source_bundle_dir,
    )
    snapshot["schema"] = NAV2_MAP_BUNDLE_SNAPSHOT_SCHEMA
    snapshot["snapshot_root"] = "map_bundle"
    return snapshot


def write_nav2_map_bundle(
    bundle_dir: Path,
    *,
    metric_map: dict[str, Any],
    static_landmarks: list[dict[str, Any]],
) -> dict[str, Any]:
    metric_map, static_landmarks = _normalized_bundle_inputs(
        metric_map,
        static_landmarks,
    )
    profiles_dir = bundle_dir / "profiles"
    costmaps_dir = bundle_dir / "costmaps"
    profiles_dir.mkdir(parents=True, exist_ok=True)
    costmaps_dir.mkdir(parents=True, exist_ok=True)

    map_id = str(metric_map.get("map_id") or "realworld_cleanup_navigation_map")
    map_version = str(metric_map.get("map_version") or "base-metric-map-v1")
    environment_id = str(
        (metric_map.get("map_bundle") or {}).get("environment_id")
        if isinstance(metric_map.get("map_bundle"), dict)
        else ""
    ) or map_id.removesuffix("_base_metric_map")
    metadata = (
        metric_map.get("map_bundle") if isinstance(metric_map.get("map_bundle"), dict) else {}
    )
    parameter_hash = str(
        metadata.get("parameter_hash")
        or metric_map_bundle_metadata(
            environment_id=environment_id,
            map_id=map_id,
            map_version=map_version,
        )["parameter_hash"]
    )

    paths = _bundle_local_paths()
    map_yaml_path = bundle_dir / paths["map_yaml"]
    map_pgm_path = bundle_dir / paths["occupancy_image"]
    semantics_path = bundle_dir / paths["semantics_json"]
    robot_profile_path = bundle_dir / paths["robot_profile"]
    costmap_params_path = bundle_dir / paths["costmap_params"]
    preview_path = bundle_dir / paths["preview_png"]

    grid = occupancy_grid_from_metric_map(metric_map, static_landmarks)
    write_pgm(map_pgm_path, grid)
    map_yaml_path.write_text(_map_yaml(metric_map), encoding="utf-8")
    semantics_path.write_text(
        json.dumps(_semantics_payload(metric_map, static_landmarks), indent=2, sort_keys=True)
        + "\n",
        encoding="utf-8",
    )
    robot_profile_path.write_text(_simple_yaml(DEFAULT_ROBOT_PROFILE), encoding="utf-8")
    costmap_params_path.write_text(_costmap_yaml(metric_map), encoding="utf-8")
    write_source_frame_bundle_preview(bundle_dir, output_path=preview_path)

    artifact_paths = {
        "map_yaml": map_yaml_path,
        "occupancy_image": map_pgm_path,
        "semantics_json": semantics_path,
        "robot_profile": robot_profile_path,
        "costmap_params": costmap_params_path,
        "preview_png": preview_path,
    }
    hashes = {key: _file_sha256(path) for key, path in artifact_paths.items() if path.is_file()}
    return {
        "schema": NAV2_MAP_BUNDLE_SCHEMA,
        "source_schema": metric_map.get("schema", ""),
        "environment_id": environment_id,
        "map_id": map_id,
        "map_version": map_version,
        "source_provenance": "molmospaces_base_metric_map",
        "robot_profile_id": DEFAULT_ROBOT_PROFILE_ID,
        "costmap_profile_id": DEFAULT_COSTMAP_PROFILE_ID,
        "parameter_hash": parameter_hash,
        "snapshot_root": bundle_dir.name,
        "snapshot_complete": set(artifact_paths) <= set(hashes),
        "artifact_paths": {
            key: path.relative_to(bundle_dir).as_posix() for key, path in artifact_paths.items()
        },
        "artifact_hashes": hashes,
        "runtime_costmap_gaps": list(RUNTIME_COSTMAP_GAPS),
        "public_contract_note": (
            "Snapshot files freeze the public Nav2-shaped map contract used by this run. "
            "They do not encode movable-object target truth or private scoring data."
        ),
    }


def static_landmarks_from_fixture_projection(
    static_fixture_projection: dict[str, Any],
) -> list[dict[str, Any]]:
    landmarks: list[dict[str, Any]] = []
    for room in static_fixture_projection.get("rooms") or []:
        if not isinstance(room, dict):
            continue
        room_id = str(room.get("room_id") or "")
        for fixture in room.get("fixtures") or []:
            if not isinstance(fixture, dict):
                continue
            landmark = dict(fixture)
            landmark_id = str(landmark.get("landmark_id") or landmark.get("fixture_id") or "")
            if landmark_id:
                landmark["landmark_id"] = landmark_id
            landmark.setdefault("room_id", room_id)
            landmarks.append(landmark)
    return landmarks


def _existing_bundle_snapshot(
    *,
    bundle_dir: Path,
    run_dir: Path,
    source_bundle_dir: Path | None = None,
) -> dict[str, Any]:
    semantics = _read_bundle_semantics(bundle_dir)
    environment_id = str(semantics.get("environment_id") or bundle_dir.name)
    map_id = str(semantics.get("map_id") or f"{environment_id}_base_metric_map")
    map_version = str(semantics.get("map_version") or "base-metric-map-v1")
    metadata = metric_map_bundle_metadata(
        environment_id=environment_id,
        map_id=map_id,
        map_version=map_version,
    )
    artifact_paths = {key: bundle_dir / relative for key, relative in _bundle_local_paths().items()}
    hashes = {key: _file_sha256(path) for key, path in artifact_paths.items() if path.is_file()}
    payload = {
        "schema": NAV2_MAP_BUNDLE_SCHEMA,
        "source_schema": semantics.get("schema", ""),
        "environment_id": environment_id,
        "map_id": map_id,
        "map_version": map_version,
        "source_provenance": (semantics.get("provenance") or {}).get(
            "source",
            "prebuilt_nav2_map_bundle",
        ),
        "robot_profile_id": DEFAULT_ROBOT_PROFILE_ID,
        "costmap_profile_id": DEFAULT_COSTMAP_PROFILE_ID,
        "parameter_hash": metadata["parameter_hash"],
        "snapshot_root": bundle_dir.name,
        "snapshot_complete": set(artifact_paths) <= set(hashes),
        "artifact_paths": {
            key: path.relative_to(run_dir).as_posix() for key, path in artifact_paths.items()
        },
        "artifact_hashes": hashes,
        "runtime_costmap_gaps": list(RUNTIME_COSTMAP_GAPS),
        "public_contract_note": (
            "Snapshot files freeze the selected prebuilt Nav2 map bundle used by this run. "
            "They do not encode movable-object target truth or private scoring data."
        ),
    }
    if source_bundle_dir is not None:
        payload["source_bundle_root"] = str(source_bundle_dir)
    return payload


def validate_nav2_map_bundle(bundle_dir: Path) -> MapBundleValidation:
    bundle_dir = Path(bundle_dir)
    errors, warnings, metadata = validate_nav2_map_bundle_payload(
        bundle_dir,
        paths=_bundle_local_paths(),
        default_resolution_m=DEFAULT_COSTMAP_PARAMETERS["resolution_m"],
        private_map_keys=PRIVATE_MAP_KEYS,
    )
    return MapBundleValidation(bundle_dir, errors, warnings, metadata)


def validate_base_metric_map_v1_bundle(bundle_dir: Path) -> MapBundleValidation:
    bundle_dir = Path(bundle_dir)
    errors, warnings, metadata = validate_base_metric_map_v1_payload(
        bundle_dir,
        paths=_bundle_local_paths(),
        default_resolution_m=DEFAULT_COSTMAP_PARAMETERS["resolution_m"],
        private_map_keys=PRIVATE_MAP_KEYS,
    )
    return MapBundleValidation(bundle_dir, errors, warnings, metadata)


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Validate a prebuilt Base Metric Map v1 bundle before agent runtime."
    )
    parser.add_argument("bundle_dir", type=Path)
    parser.add_argument("--json", action="store_true", help="Print machine-readable validation.")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    result = validate_base_metric_map_v1_bundle(args.bundle_dir)
    label = "base-metric-map-v1-bundle"
    if args.json:
        print(json.dumps(result.as_dict(), indent=2, sort_keys=True))
    elif result.ok:
        meta = result.metadata
        print(
            f"{label} ok: "
            f"{args.bundle_dir} "
            f"rooms={meta.get('room_count', 0)} "
            f"fixtures={meta.get('static_landmark_count', 0)} "
            f"waypoints={meta.get('waypoint_count', 0)}"
        )
    else:
        print(f"{label} invalid: {args.bundle_dir}", file=sys.stderr)
        for error in result.errors:
            print(f"- {error}", file=sys.stderr)
        return 1
    return 0


def _bundle_local_paths() -> dict[str, Path]:
    return {
        "map_yaml": Path("map.yaml"),
        "occupancy_image": Path("map.pgm"),
        "semantics_json": Path("semantics.json"),
        "robot_profile": Path("profiles") / f"{DEFAULT_ROBOT_PROFILE_ID}.yaml",
        "costmap_params": Path("costmaps") / f"{DEFAULT_ROBOT_PROFILE_ID}.costmap_params.yaml",
        "preview_png": Path("preview.png"),
    }


def _bundle_relative_paths(*, artifact_root: str) -> dict[str, str]:
    prefix = f"{artifact_root.rstrip('/')}/" if artifact_root else ""
    return {key: f"{prefix}{path.as_posix()}" for key, path in _bundle_local_paths().items()}


def _map_yaml(metric_map: dict[str, Any]) -> str:
    origin = metric_map.get("origin") if isinstance(metric_map.get("origin"), dict) else {}
    return "\n".join(
        [
            "image: map.pgm",
            f"resolution: {float(metric_map.get('resolution_m') or 0.05):.6f}",
            "origin: "
            f"[{float(origin.get('x') or 0.0):.6f}, "
            f"{float(origin.get('y') or 0.0):.6f}, "
            f"{float(origin.get('yaw') or 0.0):.6f}]",
            "negate: 0",
            f"occupied_thresh: {DEFAULT_COSTMAP_PARAMETERS['occupied_threshold']:.6f}",
            f"free_thresh: {DEFAULT_COSTMAP_PARAMETERS['free_threshold']:.6f}",
            "",
        ]
    )


def _costmap_yaml(metric_map: dict[str, Any]) -> str:
    payload = {
        "global_costmap": {
            "global_costmap": {
                "ros__parameters": {
                    "global_frame": str(metric_map.get("frame_id") or "map"),
                    "robot_base_frame": DEFAULT_ROBOT_PROFILE["base_frame_id"],
                    "resolution": DEFAULT_COSTMAP_PARAMETERS["resolution_m"],
                    "footprint_padding": 0.01,
                    "plugins": ["static_layer", "inflation_layer"],
                    "static_layer": {
                        "plugin": "nav2_costmap_2d::StaticLayer",
                        "map_subscribe_transient_local": True,
                    },
                    "inflation_layer": {
                        "plugin": "nav2_costmap_2d::InflationLayer",
                        "inflation_radius": DEFAULT_COSTMAP_PARAMETERS["inflation_radius_m"],
                        "cost_scaling_factor": DEFAULT_COSTMAP_PARAMETERS["cost_scaling_factor"],
                    },
                    "runtime_gaps": list(RUNTIME_COSTMAP_GAPS),
                }
            }
        }
    }
    return _simple_yaml(payload)


def _normalized_bundle_inputs(
    metric_map: dict[str, Any],
    static_landmarks: list[dict[str, Any]],
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    normalized_map = copy.deepcopy(metric_map)
    normalized_landmarks = copy.deepcopy(static_landmarks)
    _normalize_room_only_landmark_poses(normalized_map, normalized_landmarks)
    return normalized_map, normalized_landmarks


def _normalize_room_only_landmark_poses(
    metric_map: dict[str, Any],
    static_landmarks: list[dict[str, Any]],
) -> None:
    rooms_by_id = {str(room.get("room_id") or ""): room for room in metric_map.get("rooms") or []}
    waypoints_by_room: dict[str, list[dict[str, Any]]] = {}
    for waypoint in metric_map.get("inspection_waypoints") or []:
        waypoints_by_room.setdefault(str(waypoint.get("room_id") or ""), []).append(waypoint)

    next_slot_by_room: dict[str, int] = {}
    for landmark in static_landmarks:
        if not isinstance(landmark, dict):
            continue
        room_id = str(landmark.get("room_id") or "")
        room = rooms_by_id.get(room_id) or {}
        waypoints = waypoints_by_room.get(room_id, [])
        if not waypoints:
            continue
        if str(landmark.get("position_detail") or "") != "room_only":
            continue
        if not _fixture_blocks_waypoint(landmark, waypoints):
            continue
        candidates = _fixture_slot_candidates(room, landmark)
        offset = next_slot_by_room.get(room_id, 0)
        candidate, index = _next_nonblocking_fixture_pose(
            landmark,
            waypoints=waypoints,
            candidates=candidates,
            offset=offset,
        )
        if candidate is None:
            continue
        pose = landmark.get("pose") if isinstance(landmark.get("pose"), dict) else {}
        landmark["pose"] = {
            "frame_id": str(pose.get("frame_id") or "map"),
            "x": round(candidate[0], 3),
            "y": round(candidate[1], 3),
            "yaw": float(pose.get("yaw") or 0.0),
        }
        next_slot_by_room[room_id] = (offset + index + 1) % max(len(candidates), 1)


def _fixture_blocks_waypoint(
    fixture: dict[str, Any],
    waypoints: list[dict[str, Any]],
) -> bool:
    pose = fixture.get("pose") if isinstance(fixture.get("pose"), dict) else {}
    center = (float(pose.get("x") or 0.0), float(pose.get("y") or 0.0))
    return _fixture_pose_blocks_waypoint(fixture, center, waypoints)


def _next_nonblocking_fixture_pose(
    fixture: dict[str, Any],
    *,
    waypoints: list[dict[str, Any]],
    candidates: list[tuple[float, float]],
    offset: int,
) -> tuple[tuple[float, float] | None, int]:
    ordered_candidates = candidates[offset:] + candidates[:offset]
    for index, candidate in enumerate(ordered_candidates):
        if not _fixture_pose_blocks_waypoint(fixture, candidate, waypoints):
            return candidate, index
    return None, 0


def _fixture_pose_blocks_waypoint(
    fixture: dict[str, Any],
    center: tuple[float, float],
    waypoints: list[dict[str, Any]],
) -> bool:
    width_m, depth_m = _fixture_footprint_size(fixture)
    half_width = width_m / 2.0 + 0.05
    half_depth = depth_m / 2.0 + 0.05
    center_x, center_y = center
    for waypoint in waypoints:
        waypoint_x = float(waypoint.get("x", 0.0))
        waypoint_y = float(waypoint.get("y", 0.0))
        if abs(waypoint_x - center_x) <= half_width and abs(waypoint_y - center_y) <= half_depth:
            return True
    return False


def _fixture_slot_candidates(
    room: dict[str, Any],
    fixture: dict[str, Any],
) -> list[tuple[float, float]]:
    min_x, min_y, max_x, max_y = _room_bounds(room)
    width_m, depth_m = _fixture_footprint_size(fixture)
    x_pad = max(width_m / 2.0 + 0.1, 0.2)
    y_pad = max(depth_m / 2.0 + 0.1, 0.2)
    left = min(max_x, min_x + x_pad)
    right = max(min_x, max_x - x_pad)
    bottom = min(max_y, min_y + y_pad)
    top = max(min_y, max_y - y_pad)
    mid_x = (min_x + max_x) / 2.0
    mid_y = (min_y + max_y) / 2.0
    return [
        (left, bottom),
        (right, bottom),
        (left, top),
        (right, top),
        (left, mid_y),
        (right, mid_y),
        (mid_x, bottom),
        (mid_x, top),
    ]


def _fixture_footprint_size(fixture: dict[str, Any]) -> tuple[float, float]:
    footprint = fixture.get("footprint") if isinstance(fixture.get("footprint"), dict) else {}
    return (
        float(footprint.get("width_m") or 0.45),
        float(footprint.get("depth_m") or 0.35),
    )


def _room_bounds(room: dict[str, Any]) -> tuple[float, float, float, float]:
    polygon = room.get("polygon") or []
    xs = [float(point.get("x", 0.0)) for point in polygon if isinstance(point, dict)]
    ys = [float(point.get("y", 0.0)) for point in polygon if isinstance(point, dict)]
    if not xs or not ys:
        return (0.0, 0.0, 2.0, 2.0)
    return (min(xs), min(ys), max(xs), max(ys))


def _semantics_payload(
    metric_map: dict[str, Any], static_landmarks: list[dict[str, Any]]
) -> dict[str, Any]:
    metadata = (
        metric_map.get("map_bundle") if isinstance(metric_map.get("map_bundle"), dict) else {}
    )
    frame_id = str(metric_map.get("frame_id") or "map")
    payload = {
        "schema": "nav2_cleanup_semantics_v1",
        "environment_id": metadata.get("environment_id") or metric_map.get("map_id"),
        "frame_ids": {
            "map": frame_id,
            "base": DEFAULT_ROBOT_PROFILE["base_frame_id"],
            "camera": DEFAULT_ROBOT_PROFILE["camera"]["frame_id"],
        },
        "spatial_contract": source_frame_spatial_contract(
            frame_id=frame_id,
            alignment_status=ALIGNMENT_STATUS_NATIVE,
        ),
        "display_frame": None,
        "map_id": metric_map.get("map_id"),
        "map_version": metric_map.get("map_version"),
        "rooms": normalize_spatial_rooms(
            metric_map.get("rooms") or [],
            frame_id=frame_id,
            polygon_role=POLYGON_ROLE_NAVIGATION_AREA,
            geometry_source=GEOMETRY_SOURCE_OPERATOR_NAVIGATION_ZONE,
            alignment_status=ALIGNMENT_STATUS_NATIVE,
        ),
        "static_landmarks": [dict(landmark) for landmark in static_landmarks],
        "inspection_waypoints": metric_map.get("inspection_waypoints") or [],
        "driveable_ways": metric_map.get("driveable_ways") or [],
        "provenance": {
            "source": "molmospaces_base_metric_map",
            "contains_runtime_observations": False,
            "contains_private_scoring_truth": False,
        },
    }
    if isinstance(metric_map.get("base_metric_map_contract"), dict):
        payload["base_metric_map_contract"] = dict(metric_map["base_metric_map_contract"])
    if isinstance(metric_map.get("provenance"), dict):
        payload["provenance"] = {
            **payload["provenance"],
            **dict(metric_map["provenance"]),
        }
    return payload


def write_source_frame_bundle_preview(bundle_dir: Path, *, output_path: Path | None = None) -> Path:
    """Render preview.png in the canonical Base Metric Map review style."""

    result = render_base_metric_map_bundle_preview(
        Path(bundle_dir),
        output_path=output_path,
    )
    return result.path


def _simple_yaml(value: Any, *, indent: int = 0) -> str:
    lines = _yaml_lines(value, indent=indent)
    return "\n".join(lines) + "\n"


def _yaml_lines(value: Any, *, indent: int) -> list[str]:
    pad = " " * indent
    if isinstance(value, dict):
        lines: list[str] = []
        for key, item in value.items():
            if isinstance(item, (dict, list, tuple)):
                lines.append(f"{pad}{key}:")
                lines.extend(_yaml_lines(item, indent=indent + 2))
            else:
                lines.append(f"{pad}{key}: {_yaml_scalar(item)}")
        return lines
    if isinstance(value, (list, tuple)):
        lines = []
        for item in value:
            if isinstance(item, (dict, list, tuple)):
                lines.append(f"{pad}-")
                lines.extend(_yaml_lines(item, indent=indent + 2))
            else:
                lines.append(f"{pad}- {_yaml_scalar(item)}")
        return lines
    return [f"{pad}{_yaml_scalar(value)}"]


def _yaml_scalar(value: Any) -> str:
    if isinstance(value, bool):
        return "true" if value else "false"
    if value is None:
        return "null"
    if isinstance(value, (int, float)):
        return str(value)
    text = str(value)
    if not text or any(ch in text for ch in ":#[]{}&,"):
        return json.dumps(text)
    return text


def _read_bundle_semantics(bundle_dir: Path) -> dict[str, Any]:
    return read_json_object(bundle_dir / "semantics.json", label="Nav2 semantics")


def _stable_hash(value: Any) -> str:
    payload = json.dumps(value, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def _file_sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


if __name__ == "__main__":
    raise SystemExit(main())
