#!/usr/bin/env python3
from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import shutil
import sys
from pathlib import Path
from typing import Any

if __package__ in {None, ""}:
    REPO_ROOT = Path(__file__).resolve().parents[2]
    if str(REPO_ROOT) not in sys.path:
        sys.path.insert(0, str(REPO_ROOT))
else:
    REPO_ROOT = Path(__file__).resolve().parents[2]

from roboclaws.core.json_sources import read_json_object
from roboclaws.maps.base_waypoints import (
    BASE_WAYPOINT_GENERATION_POLICY,
    BaseWaypointBuilder,
    BaseWaypointBuilderConfig,
)
from roboclaws.maps.bundle import (
    DEFAULT_COSTMAP_PARAMETERS,
    DEFAULT_ROBOT_PROFILE,
    validate_base_metric_map_v1_bundle,
    validate_nav2_map_bundle,
    write_source_frame_bundle_preview,
)
from roboclaws.maps.bundle_validation import parse_map_yaml
from roboclaws.maps.rasterize import OccupancyGrid, load_pgm
from roboclaws.maps.spatial_contract import (
    ALIGNMENT_STATUS_VERIFIED,
    GEOMETRY_SOURCE_OPERATOR_NAVIGATION_ZONE,
    POLYGON_ROLE_NAVIGATION_AREA,
    source_frame_spatial_contract,
)

B1_BASE_METRIC_LABELS_SCHEMA = "b1_map12_base_metric_labels_v1"
B1_BASE_METRIC_MAP_MANIFEST_SCHEMA = "b1_map12_base_metric_map_manifest_v1"
ROOM_SEMANTICS_REFERENCE_SCHEMA = "scene_room_semantic_overlay_overrides_v1"
DEFAULT_MAP_BUNDLE = Path("vendors/agibot_sdk/artifacts/maps/robot_map_12/agibot")
DEFAULT_LABELS = Path("assets/maps/b1-map12-base-metric-labels.json")
DEFAULT_ROOM_SEMANTICS = Path("assets/maps/b1-map12-room-semantics.json")
DEFAULT_OUTPUT_DIR = Path("output/b1-map12/base-metric-map")
WAYPOINT_GENERATION_POLICY = BASE_WAYPOINT_GENERATION_POLICY


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Generate the strict B1 / Map 12 Base Metric Map bundle shared by "
            "real-robot and Digital Twin consumers."
        )
    )
    parser.add_argument("--map-bundle", type=Path, default=DEFAULT_MAP_BUNDLE)
    parser.add_argument("--labels", type=Path, default=DEFAULT_LABELS)
    parser.add_argument("--room-semantics", type=Path, default=DEFAULT_ROOM_SEMANTICS)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    try:
        result = build_base_metric_map_bundle(
            map_bundle=args.map_bundle,
            labels_path=args.labels,
            room_semantics_path=args.room_semantics,
            output_dir=args.output_dir,
        )
    except (FileNotFoundError, ValueError, AssertionError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


def build_base_metric_map_bundle(
    *,
    map_bundle: Path,
    labels_path: Path = DEFAULT_LABELS,
    room_semantics_path: Path = DEFAULT_ROOM_SEMANTICS,
    output_dir: Path = DEFAULT_OUTPUT_DIR,
) -> dict[str, Any]:
    map_bundle = Path(map_bundle)
    labels_path = Path(labels_path)
    room_semantics_path = Path(room_semantics_path)
    output_dir = Path(output_dir)

    labels = read_json_object(labels_path, label="base metric labels")
    room_semantics = read_json_object(room_semantics_path, label="room semantics")
    map_yaml = parse_map_yaml((map_bundle / "nav2.yaml").read_text(encoding="utf-8"))
    origin = _origin_payload(map_yaml)
    grid = load_pgm(
        map_bundle / "occupancy.pgm",
        resolution_m=float(map_yaml.get("resolution") or 0.05),
        origin_x=origin["x"],
        origin_y=origin["y"],
    )
    errors = validate_base_metric_labels(
        labels,
        room_semantics=room_semantics,
        grid=grid,
        labels_path=labels_path,
        map_bundle=map_bundle,
    )
    if errors:
        raise ValueError("invalid B1 / Map 12 base metric labels: " + "; ".join(errors))
    frame_id = _labels_source_map_frame_id(labels)

    if output_dir.exists():
        shutil.rmtree(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    _copy_map_bundle_source(map_bundle, output_dir=output_dir, map_yaml=map_yaml)
    rooms, waypoints = _rooms_and_waypoints(
        labels,
        room_semantics=room_semantics,
        grid=grid,
        frame_id=frame_id,
    )
    semantics = _semantics_payload(
        map_bundle=map_bundle,
        labels_path=labels_path,
        room_semantics_path=room_semantics_path,
        labels=labels,
        map_yaml=map_yaml,
        rooms=rooms,
        waypoints=waypoints,
    )
    (output_dir / "semantics.json").write_text(
        json.dumps(semantics, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    write_source_frame_bundle_preview(output_dir)
    validation = validate_nav2_map_bundle(output_dir)
    validation.raise_for_errors()
    base_metric_validation = validate_base_metric_map_v1_bundle(output_dir)
    base_metric_validation.raise_for_errors()
    manifest = _manifest_payload(
        output_dir=output_dir,
        map_bundle=map_bundle,
        labels_path=labels_path,
        room_semantics_path=room_semantics_path,
        labels=labels,
        semantics=semantics,
        validation=base_metric_validation.as_dict(),
    )
    (output_dir / "base_metric_map_manifest.json").write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return {
        "schema": B1_BASE_METRIC_MAP_MANIFEST_SCHEMA,
        "status": "generated",
        "output_dir": str(output_dir),
        "manifest": str(output_dir / "base_metric_map_manifest.json"),
        "navigation_area_count": manifest["base_metric_map"]["navigation_area_count"],
        "inspection_waypoint_count": manifest["base_metric_map"]["inspection_waypoint_count"],
        "validation": base_metric_validation.as_dict(),
    }


def validate_base_metric_labels(
    payload: dict[str, Any],
    *,
    room_semantics: dict[str, Any],
    grid: OccupancyGrid,
    labels_path: Path,
    map_bundle: Path,
) -> list[str]:
    errors = _base_metric_source_errors(
        payload,
        labels_path=labels_path,
        map_bundle=map_bundle,
    )
    room_reference_by_partition = _accepted_room_reference_by_partition(room_semantics, errors)
    labels = payload.get("labels") if isinstance(payload.get("labels"), list) else []
    if not labels:
        errors.append("labels must not be empty")
        return errors
    errors.extend(
        _navigation_label_rows_errors(
            labels,
            room_reference_by_partition=room_reference_by_partition,
            grid=grid,
            expected_frame_id=str(payload.get("source_map_frame_id") or ""),
        )
    )
    return errors


def _base_metric_source_errors(
    payload: dict[str, Any],
    *,
    labels_path: Path,
    map_bundle: Path,
) -> list[str]:
    errors: list[str] = []
    if payload.get("schema") != B1_BASE_METRIC_LABELS_SCHEMA:
        errors.append(f"schema must be {B1_BASE_METRIC_LABELS_SCHEMA}")
    if payload.get("review_status") != "accepted":
        errors.append("review_status must be accepted")
    if payload.get("source_map_mutated") is not False:
        errors.append("source_map_mutated must be false")
    if _resolve_repo_path(str(payload.get("map_bundle") or "")) != Path(map_bundle).resolve():
        errors.append("map_bundle must match --map-bundle")
    if not str(payload.get("source_map_frame_id") or ""):
        errors.append("source_map_frame_id must be set")
    if not Path(labels_path).is_file():
        errors.append(f"labels missing: {labels_path}")
    return errors


def _navigation_label_rows_errors(
    labels: list[Any],
    *,
    room_reference_by_partition: dict[str, dict[str, Any]],
    grid: OccupancyGrid,
    expected_frame_id: str,
) -> list[str]:
    errors: list[str] = []
    seen_area_ids: set[str] = set()
    navigation_area_count = 0
    for index, raw_label in enumerate(labels, start=1):
        label = raw_label if isinstance(raw_label, dict) else {}
        label_id = str(label.get("label_id") or f"labels[{index}]")
        errors.extend(
            _navigation_area_id_errors(label, label_id=label_id, seen_area_ids=seen_area_ids)
        )
        errors.extend(_label_contract_errors(label, label_id=label_id))
        errors.extend(
            _label_source_frame_errors(
                label,
                label_id=label_id,
                expected_frame_id=expected_frame_id,
            )
        )
        errors.extend(
            _dt_reference_binding_errors(
                label,
                label_id=label_id,
                room_reference_by_partition=room_reference_by_partition,
            )
        )
        navigation_enabled = bool((label.get("polygon_usage") or {}).get("navigation"))
        if navigation_enabled:
            navigation_area_count += 1
            if _inspection_waypoint_for_label(label, grid=grid) is None:
                errors.append(
                    f"label {label_id} navigation=true but no clearance-safe free waypoint exists"
                )
    if navigation_area_count == 0:
        errors.append("at least one label must have polygon_usage.navigation=true")
    return errors


def _label_source_frame_errors(
    label: dict[str, Any],
    *,
    label_id: str,
    expected_frame_id: str,
) -> list[str]:
    frame_id = str(label.get("source_map_frame_id") or "")
    if not frame_id:
        return [f"label {label_id} missing source_map_frame_id"]
    if not expected_frame_id:
        return []
    if frame_id != expected_frame_id:
        return [
            f"label {label_id} source_map_frame_id must match top-level "
            f"source_map_frame_id: {expected_frame_id}"
        ]
    return []


def _navigation_area_id_errors(
    label: dict[str, Any],
    *,
    label_id: str,
    seen_area_ids: set[str],
) -> list[str]:
    area_id = str(label.get("navigation_area_id") or "")
    if not area_id:
        seen_area_ids.add(area_id)
        return [f"label {label_id} missing navigation_area_id"]
    if area_id in seen_area_ids:
        seen_area_ids.add(area_id)
        return [f"duplicate navigation_area_id: {area_id}"]
    seen_area_ids.add(area_id)
    return []


def _label_contract_errors(label: dict[str, Any], *, label_id: str) -> list[str]:
    return [
        *_label_identity_errors(label, label_id=label_id),
        *_label_usage_errors(label, label_id=label_id),
        *_label_geometry_errors(label, label_id=label_id),
    ]


def _label_identity_errors(label: dict[str, Any], *, label_id: str) -> list[str]:
    errors: list[str] = []
    if label.get("review_status") != "accepted":
        errors.append(f"label {label_id} review_status must be accepted")
    if not str(label.get("label") or ""):
        errors.append(f"label {label_id} missing label")
    if not str(label.get("category") or ""):
        errors.append(f"label {label_id} missing category")
    if label.get("polygon_role") != POLYGON_ROLE_NAVIGATION_AREA:
        errors.append(f"label {label_id} polygon_role must be {POLYGON_ROLE_NAVIGATION_AREA}")
    if label.get("geometry_source") != GEOMETRY_SOURCE_OPERATOR_NAVIGATION_ZONE:
        errors.append(
            f"label {label_id} geometry_source must be {GEOMETRY_SOURCE_OPERATOR_NAVIGATION_ZONE}"
        )
    return errors


def _label_usage_errors(label: dict[str, Any], *, label_id: str) -> list[str]:
    errors: list[str] = []
    usage = label.get("polygon_usage") if isinstance(label.get("polygon_usage"), dict) else {}
    if not isinstance(usage.get("navigation"), bool):
        errors.append(f"label {label_id} polygon_usage.navigation must be boolean")
    if usage.get("semantic_labeling") != "accepted":
        errors.append(f"label {label_id} polygon_usage.semantic_labeling must be accepted")
    if usage.get("review") is not True:
        errors.append(f"label {label_id} polygon_usage.review must be true")
    return errors


def _label_geometry_errors(label: dict[str, Any], *, label_id: str) -> list[str]:
    errors: list[str] = []
    geometry = label.get("geometry") if isinstance(label.get("geometry"), dict) else {}
    polygon = geometry.get("polygon") if isinstance(geometry.get("polygon"), list) else []
    if geometry.get("kind") != "polygon" or len(polygon) < 3:
        errors.append(f"label {label_id} geometry must be a polygon with at least three points")
    for point in polygon:
        if not isinstance(point, dict) or "x" not in point or "y" not in point:
            errors.append(f"label {label_id} polygon points must contain x/y")
            break
    return errors


def _accepted_room_reference_by_partition(
    room_semantics: dict[str, Any],
    errors: list[str],
) -> dict[str, dict[str, Any]]:
    if room_semantics.get("schema") != ROOM_SEMANTICS_REFERENCE_SCHEMA:
        errors.append(f"room semantics schema must be {ROOM_SEMANTICS_REFERENCE_SCHEMA}")
        return {}
    output: dict[str, dict[str, Any]] = {}
    for room in room_semantics.get("rooms") or []:
        if not isinstance(room, dict) or room.get("review_status") != "accepted":
            continue
        partition_id = str(room.get("asset_partition_id") or room.get("room_id") or "")
        if partition_id:
            output[partition_id] = room
    return output


def _dt_reference_binding_errors(
    label: dict[str, Any],
    *,
    label_id: str,
    room_reference_by_partition: dict[str, dict[str, Any]],
) -> list[str]:
    partition_id = str(label.get("asset_partition_id") or "")
    if not partition_id:
        return []
    reference = room_reference_by_partition.get(partition_id)
    if reference is None:
        return [f"label {label_id} asset_partition_id {partition_id!r} is not accepted in DT"]
    errors: list[str] = []
    if str(label.get("label") or "") != str(reference.get("room_label") or ""):
        errors.append(f"label {label_id} label must match DT room_label for {partition_id}")
    if str(label.get("category") or "") != str(reference.get("category") or ""):
        errors.append(f"label {label_id} category must match DT category for {partition_id}")
    return errors


def _rooms_and_waypoints(
    labels: dict[str, Any],
    *,
    room_semantics: dict[str, Any],
    grid: OccupancyGrid,
    frame_id: str,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    room_reference_by_partition = _accepted_room_reference_by_partition(room_semantics, [])
    rooms: list[dict[str, Any]] = []
    navigation_rooms: list[dict[str, Any]] = []
    for index, label in enumerate(labels.get("labels") or [], start=1):
        room = _room_from_label(
            label,
            room_reference_by_partition=room_reference_by_partition,
            frame_id=frame_id,
        )
        rooms.append(room)
        if not room["polygon_usage"]["navigation"]:
            continue
        room["source_polygon_index"] = index
        navigation_rooms.append(room)
    waypoints = BaseWaypointBuilder(
        grid=grid,
        config=BaseWaypointBuilderConfig(
            frame_id=frame_id,
            clearance_radius_m=float(DEFAULT_ROBOT_PROFILE["footprint"]["radius_m"]),
        ),
    ).build(navigation_rooms)
    if not waypoints:
        raise ValueError("base navigation map must contain at least one inspection waypoint")
    return rooms, waypoints


def _room_from_label(
    label: dict[str, Any],
    *,
    room_reference_by_partition: dict[str, dict[str, Any]],
    frame_id: str,
) -> dict[str, Any]:
    area_id = str(label.get("navigation_area_id") or "")
    partition_id = str(label.get("asset_partition_id") or "")
    reference = room_reference_by_partition.get(partition_id, {})
    polygon = [
        {"x": float(point["x"]), "y": float(point["y"])}
        for point in ((label.get("geometry") or {}).get("polygon") or [])
    ]
    label_source = (
        "digital_twin_room_semantic_reference"
        if partition_id
        else "operator_reviewed_map12_base_label"
    )
    return {
        "room_id": area_id,
        "navigation_area_id": area_id,
        "map_area_id": area_id,
        "room_label": str(label.get("label") or area_id),
        "category": str(label.get("category") or ""),
        "polygon": polygon,
        "source_map_frame_id": frame_id,
        "polygon_role": POLYGON_ROLE_NAVIGATION_AREA,
        "geometry_source": GEOMETRY_SOURCE_OPERATOR_NAVIGATION_ZONE,
        "alignment_status": ALIGNMENT_STATUS_VERIFIED,
        "polygon_usage": dict(label.get("polygon_usage") or {}),
        "semantic_source": "operator_reviewed_map12_base_metric_label",
        "label_source": label_source,
        "asset_partition_id": partition_id,
        "source_room_semantics_id": partition_id,
        "source_label_id": str(label.get("label_id") or ""),
        "aliases": list(reference.get("aliases") or []),
        "review_status": "accepted",
    }


def _inspection_waypoint_for_label(
    label: dict[str, Any],
    *,
    grid: OccupancyGrid,
) -> dict[str, float] | None:
    area = {
        "navigation_area_id": str(label.get("navigation_area_id") or ""),
        "geometry": dict(label.get("geometry") or {}),
    }
    return BaseWaypointBuilder(
        grid=grid,
        config=BaseWaypointBuilderConfig(
            frame_id=str(label.get("source_map_frame_id") or "map"),
            clearance_radius_m=float(DEFAULT_ROBOT_PROFILE["footprint"]["radius_m"]),
        ),
    ).inspection_pose(area)


def _semantics_payload(
    *,
    map_bundle: Path,
    labels_path: Path,
    room_semantics_path: Path,
    labels: dict[str, Any],
    map_yaml: dict[str, Any],
    rooms: list[dict[str, Any]],
    waypoints: list[dict[str, Any]],
) -> dict[str, Any]:
    frame_id = _labels_source_map_frame_id(labels)
    navigation_rooms = [room for room in rooms if room["polygon_usage"]["navigation"]]
    return {
        "schema": "nav2_cleanup_semantics_v1",
        "environment_id": "agibot-robot-map-12",
        "frame_ids": {
            "map": frame_id,
            "base": DEFAULT_ROBOT_PROFILE["base_frame_id"],
            "camera": DEFAULT_ROBOT_PROFILE["camera"]["frame_id"],
        },
        "spatial_contract": source_frame_spatial_contract(
            frame_id=frame_id,
            alignment_status=ALIGNMENT_STATUS_VERIFIED,
        ),
        "display_frame": None,
        "map_id": "agibot-robot-map-12_base_metric_map",
        "map_version": "robot_map_12_base_metric_map_v1",
        "resolution_m": float(map_yaml.get("resolution") or 0.05),
        "origin": _origin_payload(map_yaml),
        "rooms": rooms,
        "fixtures": [],
        "static_landmarks": [],
        "inspection_waypoints": waypoints,
        "driveable_ways": [
            {"from_room_id": room["room_id"], "to_room_id": room["room_id"]}
            for room in navigation_rooms
        ],
        "navigation_memory_anchors": [],
        "room_category_hints": [
            {
                "room_id": room["room_id"],
                "navigation_area_id": room["navigation_area_id"],
                "room_label": room["room_label"],
                "category": room["category"],
            }
            for room in navigation_rooms
        ],
        "base_metric_map_contract": {
            "schema": "base_metric_map_v1",
            "navigation_area_count": len(navigation_rooms),
            "semantic_label_count": len(rooms),
            "inspection_waypoint_count": len(waypoints),
            "waypoint_generation_policy": WAYPOINT_GENERATION_POLICY,
            "consumer_scope": "real_robot_and_digital_twin",
        },
        "provenance": {
            "source": "b1_map12_base_metric_labels",
            "raw_map_bundle": str(map_bundle),
            "base_metric_labels": str(labels_path),
            "room_semantics_reference": str(room_semantics_path),
            "b1_base_metric_map_builder": _repo_relative_path(Path(__file__)),
            "contains_static_fixtures": False,
            "contains_receptacles": False,
            "contains_movable_objects": False,
            "contains_runtime_observations": False,
            "contains_private_scoring_truth": False,
            "uses_navigation_memory_as_waypoint_source": False,
        },
    }


def _labels_source_map_frame_id(labels: dict[str, Any]) -> str:
    frame_id = str(labels.get("source_map_frame_id") or "")
    if not frame_id:
        raise ValueError("source_map_frame_id must be set")
    return frame_id


def _manifest_payload(
    *,
    output_dir: Path,
    map_bundle: Path,
    labels_path: Path,
    room_semantics_path: Path,
    labels: dict[str, Any],
    semantics: dict[str, Any],
    validation: dict[str, Any],
) -> dict[str, Any]:
    contract = semantics["base_metric_map_contract"]
    source_files = [
        map_bundle / "nav2.yaml",
        map_bundle / "occupancy.pgm",
        map_bundle / "source.json",
        labels_path,
        room_semantics_path,
    ]
    return {
        "schema": B1_BASE_METRIC_MAP_MANIFEST_SCHEMA,
        "status": "generated",
        "generated_at": dt.datetime.now(dt.UTC).isoformat().replace("+00:00", "Z"),
        "output_dir": str(output_dir),
        "source_assets": {
            "map_bundle": str(map_bundle),
            "base_metric_labels": str(labels_path),
            "room_semantics_reference": str(room_semantics_path),
            "label_review_status": str(labels.get("review_status") or ""),
        },
        "source_file_hashes": {
            str(path): _file_sha256(path) for path in source_files if path.is_file()
        },
        "base_metric_map": {
            "schema": contract["schema"],
            "environment_id": semantics["environment_id"],
            "map_id": semantics["map_id"],
            "map_version": semantics["map_version"],
            "navigation_area_count": contract["navigation_area_count"],
            "semantic_label_count": contract["semantic_label_count"],
            "inspection_waypoint_count": contract["inspection_waypoint_count"],
            "waypoint_generation_policy": contract["waypoint_generation_policy"],
        },
        "validation": validation,
        "policy": {
            "shared_by_real_robot_and_digital_twin": True,
            "requires_checked_in_accepted_labels": True,
            "fails_on_dt_label_mismatch": True,
            "fails_on_navigation_area_without_clearance_safe_waypoint": True,
            "does_not_use_navigation_memory_as_waypoint_source": True,
            "does_not_include_static_fixture_or_object_truth": True,
        },
    }


def _copy_map_bundle_source(source: Path, *, output_dir: Path, map_yaml: dict[str, Any]) -> None:
    required = {
        "nav2.yaml": source / "nav2.yaml",
        "occupancy.pgm": source / "occupancy.pgm",
        "source.json": source / "source.json",
    }
    missing = [str(path) for path in required.values() if not path.is_file()]
    if missing:
        raise ValueError("raw Map12 source is incomplete: " + ", ".join(missing))
    (output_dir / "map.yaml").write_text(_runtime_map_yaml(map_yaml), encoding="utf-8")
    shutil.copy2(required["occupancy.pgm"], output_dir / "map.pgm")
    shutil.copy2(required["source.json"], output_dir / "source.json")
    if (source / "raw_map.json.gz").is_file():
        shutil.copy2(source / "raw_map.json.gz", output_dir / "raw_map.json.gz")
    profiles_dir = output_dir / "profiles"
    costmaps_dir = output_dir / "costmaps"
    profiles_dir.mkdir(parents=True, exist_ok=True)
    costmaps_dir.mkdir(parents=True, exist_ok=True)
    (profiles_dir / "rby1m.yaml").write_text(_simple_yaml(DEFAULT_ROBOT_PROFILE), encoding="utf-8")
    (costmaps_dir / "rby1m.costmap_params.yaml").write_text(
        _costmap_yaml(),
        encoding="utf-8",
    )


def _runtime_map_yaml(map_yaml: dict[str, Any]) -> str:
    origin = _origin_payload(map_yaml)
    return "\n".join(
        [
            "image: map.pgm",
            f"resolution: {float(map_yaml.get('resolution') or 0.05):.12g}",
            f"origin: [{origin['x']:.12g}, {origin['y']:.12g}, {origin['yaw']:.12g}]",
            f"negate: {int(map_yaml.get('negate') or 0)}",
            f"occupied_thresh: {float(map_yaml.get('occupied_thresh') or 0.65):.12g}",
            f"free_thresh: {float(map_yaml.get('free_thresh') or 0.196):.12g}",
            "",
        ]
    )


def _costmap_yaml() -> str:
    return _simple_yaml(
        {
            "global_costmap": {
                "global_costmap": {
                    "ros__parameters": {
                        "global_frame": "map",
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
                            "cost_scaling_factor": DEFAULT_COSTMAP_PARAMETERS[
                                "cost_scaling_factor"
                            ],
                        },
                    }
                }
            }
        }
    )


def _origin_payload(map_yaml: dict[str, Any]) -> dict[str, float]:
    origin = map_yaml.get("origin") if isinstance(map_yaml.get("origin"), list) else []
    origin = (origin + [0.0, 0.0, 0.0])[:3]
    return {"x": float(origin[0]), "y": float(origin[1]), "yaw": float(origin[2])}


def _simple_yaml(value: Any, *, indent: int = 0) -> str:
    prefix = " " * indent
    if isinstance(value, dict):
        lines: list[str] = []
        for key, item in value.items():
            if isinstance(item, dict):
                lines.append(f"{prefix}{key}:")
                lines.append(_simple_yaml(item, indent=indent + 2).rstrip())
            elif isinstance(item, list):
                lines.append(f"{prefix}{key}:")
                for entry in item:
                    lines.append(f"{prefix}  - {entry}")
            else:
                lines.append(f"{prefix}{key}: {item}")
        return "\n".join(lines) + "\n"
    return f"{prefix}{value}\n"


def _repo_relative_path(path: Path) -> str:
    try:
        return path.resolve().relative_to(REPO_ROOT).as_posix()
    except ValueError:
        return path.as_posix()


def _resolve_repo_path(path: str) -> Path:
    raw = Path(path)
    if raw.is_absolute():
        return raw.resolve()
    return (REPO_ROOT / raw).resolve()


def _file_sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


if __name__ == "__main__":
    raise SystemExit(main())
