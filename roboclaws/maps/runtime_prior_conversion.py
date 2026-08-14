from __future__ import annotations

import copy
from pathlib import Path
from typing import Any

from roboclaws.core.json_sources import read_json_object
from roboclaws.maps.bundle import parse_map_yaml
from roboclaws.maps.navigation_memory import (
    navigation_memory_item,
    navigation_memory_items,
    read_navigation_memory,
)
from roboclaws.maps.rasterize import load_pgm
from roboclaws.maps.runtime_prior_contracts import (
    MOVABLE_ANCHOR_TYPES,
    RUNTIME_MAP_PRIOR_SNAPSHOT_SCHEMA,
    RUNTIME_METRIC_MAP_SCHEMA,
)
from roboclaws.maps.runtime_prior_conversion_helpers import (
    _anchor_from_bundle_waypoint,
    _anchor_from_navigation_memory_item,
    _bundle_frame_id,
    _bundle_rooms,
    _bundle_waypoint,
    _driveable_ways,
    _nav2_cleanup_waypoint_sources,
    _prior_observed_object_from_anchor,
    _room_category_hints_from_rooms,
    _rooms_from_anchors,
    _snapshot_summary,
    _waypoint_from_anchor,
)
from roboclaws.maps.runtime_prior_source_validation import (
    _artifact_paths,
    _assert_no_private_truth,
    _map_id,
    _require_file,
    _source_hashes,
    _source_map_geometry,
)


def runtime_prior_snapshot_from_agibot_navigation_memory(
    map_dir: str | Path,
    *,
    producer: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Convert an Agibot navigation-memory map folder into the canonical snapshot."""

    map_dir = Path(map_dir)
    navigation_memory_path = map_dir / "navigation_memory.json"
    agibot_dir = map_dir / "agibot"
    nav2_yaml_path = agibot_dir / "nav2.yaml"
    occupancy_path = agibot_dir / "occupancy.pgm"
    source_path = agibot_dir / "source.json"
    _require_file(navigation_memory_path)
    _require_file(nav2_yaml_path)
    _require_file(occupancy_path)

    navigation_memory = read_navigation_memory(
        navigation_memory_path,
        source_name="Agibot navigation memory",
        json_object_label="Agibot navigation memory",
    )
    map_yaml = parse_map_yaml(nav2_yaml_path.read_text(encoding="utf-8"))
    resolution, origin = _source_map_geometry(map_yaml, label="Agibot nav2.yaml")
    grid = load_pgm(
        occupancy_path,
        resolution_m=resolution,
        origin_x=origin[0],
        origin_y=origin[1],
    )
    source = read_json_object(source_path, label="Agibot map")

    anchors: list[dict[str, Any]] = []
    waypoints: list[dict[str, Any]] = []
    fixture_candidates: list[dict[str, Any]] = []
    observed_objects: list[dict[str, Any]] = []
    for index, raw_item in enumerate(
        navigation_memory_items(navigation_memory, source_name="Agibot navigation memory"),
        start=1,
    ):
        item = navigation_memory_item(
            raw_item,
            index=index,
            source_name="Agibot navigation memory",
        )
        anchor = _anchor_from_navigation_memory_item(item, index=index, grid=grid)
        anchors.append(anchor)
        waypoint = _waypoint_from_anchor(anchor)
        waypoints.append(waypoint)
        if anchor["anchor_type"] in MOVABLE_ANCHOR_TYPES:
            observed_objects.append(_prior_observed_object_from_anchor(anchor))
        elif anchor["materialization"]["fixture_candidate"]["enabled"]:
            fixture_candidates.append(anchor["materialization"]["fixture_candidate"])
    rooms = _rooms_from_anchors(anchors)
    room_category_hints = _room_category_hints_from_rooms(rooms)

    runtime_metric_map = {
        "schema": RUNTIME_METRIC_MAP_SCHEMA,
        "contract": "realworld_cleanup_contract_v1",
        "freshness": "offline_converted_prior",
        "source_map_mutated": False,
        "private_truth_included": False,
        "static_map": {
            "schema": "agibot_navigation_memory_source_map_v1",
            "contains_runtime_observations": False,
            "contains_private_scoring_truth": False,
            "map_frame": "map",
            "map_id": _map_id(map_dir, source),
            "artifact_paths": _artifact_paths(map_dir),
            "costmap": {
                "resolution_m": grid.resolution_m,
                "origin": {"x": grid.origin_x, "y": grid.origin_y, "yaw": round(origin[2], 6)},
                "width": grid.width,
                "height": grid.height,
                "occupancy_grid_artifact": "agibot/occupancy.pgm",
            },
        },
        "rooms": rooms,
        "room_category_hints": room_category_hints,
        "driveable_ways": _driveable_ways(rooms),
        "public_semantic_anchors": anchors,
        "observed_objects": observed_objects,
        "map_update_candidates": [],
        "producer_summary": {
            "observed_object_count": len(observed_objects),
            "producer_types": {"agibot_navigation_memory_conversion": len(observed_objects)}
            if observed_objects
            else {},
            "public_semantic_anchor_count": len(anchors),
            "public_semantic_anchor_producer_types": {
                "agibot_navigation_memory_conversion": len(anchors)
            },
            "map_update_candidate_count": 0,
        },
        "public_contract_note": (
            "Offline Agibot navigation memory conversion produces the same downstream "
            "Runtime Metric Map payload used by online intent=map-build output. "
            "Movable objects are preserved only as needs_confirm priors."
        ),
    }
    snapshot = {
        "schema": RUNTIME_MAP_PRIOR_SNAPSHOT_SCHEMA,
        "source_navigation_map": {
            "schema": "agibot_navigation_memory_source_v1",
            "map_id": _map_id(map_dir, source),
            "source_type": "agibot_navigation_memory",
            "source_root": str(map_dir),
            "navigation_memory": "navigation_memory.json",
            "nav2_yaml": "agibot/nav2.yaml",
            "occupancy_grid_artifact": "agibot/occupancy.pgm",
            "raw_map_artifact": "agibot/raw_map.json.gz"
            if (agibot_dir / "raw_map.json.gz").is_file()
            else "",
            "source_json": "agibot/source.json",
            "rooms": rooms,
            "room_category_hints": room_category_hints,
            "source_hashes": _source_hashes(
                navigation_memory_path,
                nav2_yaml_path,
                occupancy_path,
                source_path,
                agibot_dir / "raw_map.json.gz",
            ),
            "source_map_mutated": False,
        },
        "runtime_metric_map": runtime_metric_map,
        "public_semantic_anchors": anchors,
        "inspection_waypoints": waypoints,
        "fixture_candidates": fixture_candidates,
        "producer": {
            "type": "offline_navigation_memory_conversion",
            "provenance": "agibot_navigation_memory",
            "input_schema_version": navigation_memory.get("schema_version"),
            "updated_at": str(navigation_memory.get("updated_at") or ""),
            **dict(producer or {}),
        },
        "contract": {
            "schema": RUNTIME_MAP_PRIOR_SNAPSHOT_SCHEMA,
            "runtime_metric_map_schema": RUNTIME_METRIC_MAP_SCHEMA,
            "online_offline_equivalent_shape": True,
            "private_truth_included": False,
            "source_map_mutated": False,
            "movable_object_priors_require_current_run_confirmation": True,
        },
    }
    snapshot["summary"] = _snapshot_summary(snapshot)
    _assert_no_private_truth(snapshot)
    return snapshot


def runtime_prior_snapshot_from_nav2_cleanup_bundle(
    bundle_dir: str | Path,
    *,
    producer: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Wrap a compiled Nav2 cleanup map bundle in the canonical prior contract."""

    bundle_dir = Path(bundle_dir)
    map_yaml_path = bundle_dir / "map.yaml"
    occupancy_path = bundle_dir / "map.pgm"
    semantics_path = bundle_dir / "semantics.json"
    _require_file(map_yaml_path)
    _require_file(occupancy_path)

    map_yaml = parse_map_yaml(map_yaml_path.read_text(encoding="utf-8"))
    resolution, origin = _source_map_geometry(map_yaml, label="Nav2 cleanup map.yaml")
    grid = load_pgm(
        occupancy_path,
        resolution_m=resolution,
        origin_x=float(origin[0]),
        origin_y=float(origin[1]),
    )
    semantics = read_json_object(semantics_path, label="Nav2 cleanup semantics")
    if semantics.get("schema") != "nav2_cleanup_semantics_v1":
        raise ValueError(
            "compiled cleanup bundle semantics must use schema nav2_cleanup_semantics_v1"
        )
    map_frame_id = _bundle_frame_id(semantics)
    rooms = _bundle_rooms(semantics, map_frame_id=map_frame_id)
    inspection_waypoints = [
        _bundle_waypoint(waypoint, map_frame_id=map_frame_id)
        for waypoint in _nav2_cleanup_waypoint_sources(semantics)
    ]
    anchors = [
        _anchor_from_bundle_waypoint(waypoint, index=index)
        for index, waypoint in enumerate(inspection_waypoints, start=1)
    ]
    runtime_metric_map = {
        "schema": RUNTIME_METRIC_MAP_SCHEMA,
        "contract": "realworld_cleanup_contract_v1",
        "freshness": "offline_compiled_prior",
        "source_map_mutated": False,
        "private_truth_included": False,
        "static_map": {
            "schema": "nav2_cleanup_bundle_source_map_v1",
            "contains_runtime_observations": bool(
                (semantics.get("provenance") or {}).get("contains_runtime_observations")
            ),
            "contains_private_scoring_truth": bool(
                (semantics.get("provenance") or {}).get("contains_private_scoring_truth")
            ),
            "map_frame": map_frame_id,
            "map_id": str(semantics.get("map_id") or bundle_dir.name),
            "artifact_paths": {
                "nav2_yaml": "map.yaml",
                "occupancy_grid": "map.pgm",
                "semantics": "semantics.json",
            },
            "costmap": {
                "resolution_m": grid.resolution_m,
                "origin": {"x": grid.origin_x, "y": grid.origin_y, "yaw": round(origin[2], 6)},
                "width": grid.width,
                "height": grid.height,
                "occupancy_grid_artifact": "map.pgm",
            },
        },
        "rooms": rooms,
        "room_category_hints": copy.deepcopy(semantics.get("room_category_hints") or []),
        "driveable_ways": copy.deepcopy(semantics.get("driveable_ways") or []),
        "public_semantic_anchors": anchors,
        "observed_objects": [],
        "map_update_candidates": [],
        "producer_summary": {
            "observed_object_count": 0,
            "producer_types": {},
            "public_semantic_anchor_count": len(anchors),
            "public_semantic_anchor_producer_types": {
                "nav2_cleanup_bundle_conversion": len(anchors)
            }
            if anchors
            else {},
            "map_update_candidate_count": 0,
        },
        "digital_twin_capabilities": copy.deepcopy(
            semantics.get("digital_twin_capabilities") or {}
        ),
        "public_contract_note": (
            "Compiled Nav2 cleanup bundle conversion produces the same downstream "
            "Runtime Metric Map payload used by online intent=map-build output. "
            "It carries public map/waypoint context only; object priors require a "
            "dedicated semantic projection artifact."
        ),
    }
    snapshot = {
        "schema": RUNTIME_MAP_PRIOR_SNAPSHOT_SCHEMA,
        "source_navigation_map": {
            "schema": "nav2_cleanup_bundle_source_v1",
            "map_id": str(semantics.get("map_id") or bundle_dir.name),
            "source_type": "nav2_cleanup_bundle",
            "source_root": str(bundle_dir),
            "map_frame": map_frame_id,
            "nav2_yaml": "map.yaml",
            "occupancy_grid_artifact": "map.pgm",
            "semantics": "semantics.json",
            "rooms": rooms,
            "room_category_hints": copy.deepcopy(semantics.get("room_category_hints") or []),
            "digital_twin_capabilities": copy.deepcopy(
                semantics.get("digital_twin_capabilities") or {}
            ),
            "source_hashes": _source_hashes(map_yaml_path, occupancy_path, semantics_path),
            "source_map_mutated": False,
        },
        "runtime_metric_map": runtime_metric_map,
        "public_semantic_anchors": anchors,
        "inspection_waypoints": inspection_waypoints,
        "fixture_candidates": [],
        "producer": {
            "type": "offline_nav2_cleanup_bundle_conversion",
            "provenance": "nav2_cleanup_bundle",
            "source_schema": str(semantics.get("schema") or ""),
            "source_provenance": str((semantics.get("provenance") or {}).get("source") or ""),
            **dict(producer or {}),
        },
        "contract": {
            "schema": RUNTIME_MAP_PRIOR_SNAPSHOT_SCHEMA,
            "runtime_metric_map_schema": RUNTIME_METRIC_MAP_SCHEMA,
            "online_offline_equivalent_shape": True,
            "private_truth_included": False,
            "source_map_mutated": False,
            "movable_object_priors_require_current_run_confirmation": True,
        },
    }
    snapshot["summary"] = _snapshot_summary(snapshot)
    _assert_no_private_truth(snapshot)
    return snapshot
