from __future__ import annotations

import argparse
import hashlib
import json
import shutil
from pathlib import Path
from typing import Any

from PIL import Image, ImageDraw

from roboclaws.core.json_sources import read_gzip_json_object, read_json_object
from roboclaws.household.agibot_map_defaults import (
    DEFAULT_AGIBOT_ENVIRONMENT_ID,
    DEFAULT_AGIBOT_MAP_VERSION,
)
from roboclaws.maps.bundle import (
    DEFAULT_COSTMAP_PARAMETERS,
    DEFAULT_COSTMAP_PROFILE_ID,
    DEFAULT_ROBOT_PROFILE,
    DEFAULT_ROBOT_PROFILE_ID,
    NAV2_MAP_BUNDLE_SCHEMA,
    RUNTIME_COSTMAP_GAPS,
    metric_map_bundle_metadata,
    parse_map_yaml,
    validate_nav2_map_bundle,
)
from roboclaws.maps.spatial_contract import (
    ALIGNMENT_STATUS_NATIVE,
    GEOMETRY_SOURCE_OPERATOR_NAVIGATION_ZONE,
    POLYGON_ROLE_NAVIGATION_AREA,
    normalize_spatial_room,
    source_frame_spatial_contract,
)

AGIBOT_MAP_BUNDLE_PROVENANCE = "agibot_gdk_map_artifact"
AGIBOT_ROBOT_MAP_9_ENVIRONMENT_ID = "agibot-robot-map-9"
AGIBOT_ROBOT_MAP_9_MAP_VERSION = "agibot-sdk-fetch-2026-05-20"
DEFAULT_AGIBOT_ENVIRONMENT_ID_FALLBACK = DEFAULT_AGIBOT_ENVIRONMENT_ID
DEFAULT_AGIBOT_MAP_VERSION_FALLBACK = DEFAULT_AGIBOT_MAP_VERSION


def write_agibot_nav2_map_bundle(
    *,
    source_map_dir: Path,
    context_json: Path,
    bundle_dir: Path,
) -> dict[str, Any]:
    """Write a Nav2-shaped map bundle from an AgiBot fetched map artifact.

    The AgiBot artifact supplies the real occupancy map and map metadata. The
    completed context supplies the public room, fixture, and waypoint semantics.
    """

    source_map_dir = Path(source_map_dir)
    context_json = Path(context_json)
    bundle_dir = Path(bundle_dir)
    artifact_dir = (
        source_map_dir / "agibot" if (source_map_dir / "agibot").is_dir() else source_map_dir
    )
    source_json = _load_json(artifact_dir / "source.json")
    raw_map = _load_raw_map(artifact_dir / "raw_map.json.gz")
    nav2_yaml = parse_map_yaml((artifact_dir / "nav2.yaml").read_text(encoding="utf-8"))
    context = _load_json(context_json)
    semantics = _semantics_from_context(
        context,
        source_json=source_json,
        raw_map=raw_map,
    )

    bundle_dir.mkdir(parents=True, exist_ok=True)
    (bundle_dir / "profiles").mkdir(parents=True, exist_ok=True)
    (bundle_dir / "costmaps").mkdir(parents=True, exist_ok=True)
    shutil.copy2(artifact_dir / "occupancy.pgm", bundle_dir / "map.pgm")
    (bundle_dir / "map.yaml").write_text(_map_yaml_from_agibot(nav2_yaml), encoding="utf-8")
    (bundle_dir / "semantics.json").write_text(
        json.dumps(semantics, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    (bundle_dir / "profiles" / f"{DEFAULT_ROBOT_PROFILE_ID}.yaml").write_text(
        _simple_yaml(DEFAULT_ROBOT_PROFILE),
        encoding="utf-8",
    )
    (bundle_dir / "costmaps" / f"{DEFAULT_ROBOT_PROFILE_ID}.costmap_params.yaml").write_text(
        _costmap_yaml(nav2_yaml),
        encoding="utf-8",
    )
    _write_agibot_preview(
        bundle_dir / "preview.png",
        occupancy_path=bundle_dir / "map.pgm",
        map_yaml=nav2_yaml,
        semantics=semantics,
    )
    validation = validate_nav2_map_bundle(bundle_dir)
    validation.raise_for_errors()
    snapshot = _snapshot_payload(
        bundle_dir=bundle_dir,
        source_map_dir=source_map_dir,
        semantics=semantics,
    )
    return snapshot


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Export an Agibot robot map artifact as a Nav2-shaped map bundle."
    )
    parser.add_argument("--source-map-dir", type=Path, required=True)
    parser.add_argument("--context-json", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    snapshot = write_agibot_nav2_map_bundle(
        source_map_dir=args.source_map_dir,
        context_json=args.context_json,
        bundle_dir=args.output_dir,
    )
    print(json.dumps(snapshot, indent=2, sort_keys=True))
    return 0


def _semantics_from_context(
    context: dict[str, Any],
    *,
    source_json: dict[str, Any],
    raw_map: dict[str, Any],
) -> dict[str, Any]:
    environment_id = str(context.get("environment_id") or DEFAULT_AGIBOT_ENVIRONMENT_ID_FALLBACK)
    map_id = f"{environment_id}_base_metric_map"
    map_source = source_json.get("source_agibot_map") or context.get("map_source") or {}
    frame_id = str(context.get("frame_id") or "map")
    return {
        "schema": "nav2_cleanup_semantics_v1",
        "environment_id": environment_id,
        "map_id": map_id,
        "map_version": str(context.get("map_version") or DEFAULT_AGIBOT_MAP_VERSION_FALLBACK),
        "frame_ids": {
            "map": frame_id,
            "base": "base_link",
            "camera": "head_camera_rgb_optical_frame",
        },
        "spatial_contract": source_frame_spatial_contract(
            frame_id=frame_id,
            alignment_status=ALIGNMENT_STATUS_NATIVE,
        ),
        "display_frame": None,
        "rooms": [_room_payload(room, frame_id=frame_id) for room in _list(context.get("rooms"))],
        "static_landmarks": [
            _fixture_payload(fixture) for fixture in _list(context.get("fixtures"))
        ],
        "inspection_waypoints": [
            _waypoint_payload(waypoint) for waypoint in _list(context.get("inspection_waypoints"))
        ],
        "driveable_ways": _list(context.get("driveable_ways")),
        "provenance": {
            "source": AGIBOT_MAP_BUNDLE_PROVENANCE,
            "contains_runtime_observations": False,
            "contains_private_scoring_truth": False,
            "source_artifact_schema": source_json.get("schema"),
            "raw_map_schema": raw_map.get("schema"),
            "source_agibot_map_id": map_source.get("id") or raw_map.get("source_agibot_map_id"),
            "source_agibot_map_name": map_source.get("name")
            or raw_map.get("source_agibot_map_name"),
            "current_agibot_map_id_at_fetch": raw_map.get("current_agibot_map_id_at_fetch"),
        },
    }


def _room_payload(room: dict[str, Any], *, frame_id: str) -> dict[str, Any]:
    return normalize_spatial_room(
        {
            "room_id": str(room["room_id"]),
            "room_label": str(room.get("room_label") or room["room_id"]),
            "fixture_count": int(room.get("fixture_count") or 0),
            "polygon": _list(room.get("polygon")),
        },
        frame_id=frame_id,
        polygon_role=POLYGON_ROLE_NAVIGATION_AREA,
        geometry_source=GEOMETRY_SOURCE_OPERATOR_NAVIGATION_ZONE,
        alignment_status=ALIGNMENT_STATUS_NATIVE,
    )


def _fixture_payload(fixture: dict[str, Any]) -> dict[str, Any]:
    fixture_id = str(fixture["fixture_id"])
    return {
        "fixture_id": fixture_id,
        "room_id": str(fixture["room_id"]),
        "name": str(fixture.get("name") or fixture.get("label") or fixture_id),
        "label": str(fixture.get("label") or fixture.get("name") or fixture_id),
        "category": str(fixture.get("category") or "fixture"),
        "affordances": _list(fixture.get("affordances")) or ["place"],
        "pose": _dict(fixture.get("pose")),
        "footprint": _dict(fixture.get("footprint"))
        or {"shape": "rectangle", "width_m": 0.5, "depth_m": 0.4},
        "position_detail": str(fixture.get("position_detail") or "agibot_map_authored"),
        "manipulation_frame": str(
            fixture.get("manipulation_frame") or f"{fixture_id}_manipulation"
        ),
        "preferred_inspection_waypoint_id": str(fixture["preferred_inspection_waypoint_id"]),
        "preferred_manipulation_waypoint_id": str(
            fixture.get("preferred_manipulation_waypoint_id")
            or fixture["preferred_inspection_waypoint_id"]
        ),
    }


def _waypoint_payload(waypoint: dict[str, Any]) -> dict[str, Any]:
    return {
        "waypoint_id": str(waypoint["waypoint_id"]),
        "frame_id": str(waypoint.get("frame_id") or "map"),
        "x": float(waypoint["x"]),
        "y": float(waypoint["y"]),
        "yaw": float(waypoint["yaw"]),
        "room_id": str(waypoint["room_id"]),
        "fixture_id": str(waypoint.get("fixture_id") or ""),
        "label": str(waypoint.get("label") or waypoint["waypoint_id"]),
        "purpose": str(waypoint.get("purpose") or "fixture_coverage"),
        "waypoint_source": str(waypoint.get("waypoint_source") or AGIBOT_MAP_BUNDLE_PROVENANCE),
        "visited": bool(waypoint.get("visited", False)),
        "coverage_estimate": waypoint.get("coverage_estimate", 0.5),
        "reachability_status": str(waypoint.get("reachability_status") or "verified"),
    }


def _map_yaml_from_agibot(nav2_yaml: dict[str, Any]) -> str:
    origin = nav2_yaml.get("origin") if isinstance(nav2_yaml.get("origin"), list) else []
    origin = (origin + [0.0, 0.0, 0.0])[:3]
    return "\n".join(
        [
            "image: map.pgm",
            f"resolution: {float(nav2_yaml.get('resolution') or 0.05):.12g}",
            f"origin: [{float(origin[0]):.12g}, {float(origin[1]):.12g}, {float(origin[2]):.12g}]",
            "negate: 0",
            f"occupied_thresh: {float(nav2_yaml.get('occupied_thresh') or 0.65):.6f}",
            f"free_thresh: {float(nav2_yaml.get('free_thresh') or 0.196):.6f}",
            "",
        ]
    )


def _costmap_yaml(nav2_yaml: dict[str, Any]) -> str:
    params = dict(DEFAULT_COSTMAP_PARAMETERS)
    params["resolution_m"] = float(nav2_yaml.get("resolution") or params["resolution_m"])
    return _simple_yaml(
        {
            "costmap_profile_id": DEFAULT_COSTMAP_PROFILE_ID,
            "static_layer": {"enabled": True, "map_topic": "map"},
            "inflation_layer": {
                "enabled": True,
                "inflation_radius_m": params["inflation_radius_m"],
                "cost_scaling_factor": params["cost_scaling_factor"],
            },
            "thresholds": {
                "occupied": params["occupied_threshold"],
                "free": params["free_threshold"],
            },
            "runtime_gaps": list(RUNTIME_COSTMAP_GAPS),
        }
    )


def _write_agibot_preview(
    path: Path,
    *,
    occupancy_path: Path,
    map_yaml: dict[str, Any],
    semantics: dict[str, Any],
) -> None:
    image = Image.open(occupancy_path).convert("L")
    image = Image.eval(image, lambda value: 255 if value >= 250 else 25 if value <= 5 else 205)
    image = image.convert("RGB")
    draw = ImageDraw.Draw(image, "RGBA")
    resolution = float(map_yaml.get("resolution") or 0.05)
    origin = map_yaml.get("origin") if isinstance(map_yaml.get("origin"), list) else [0.0, 0.0]

    def project(x: float, y: float) -> tuple[int, int]:
        col = int(round((x - float(origin[0])) / resolution))
        row = image.height - 1 - int(round((y - float(origin[1])) / resolution))
        return col, row

    for room in semantics.get("rooms") or []:
        points = [project(float(p["x"]), float(p["y"])) for p in room.get("polygon") or []]
        if len(points) >= 3:
            draw.polygon(points, fill=(86, 128, 214, 42), outline=(31, 79, 168, 190))
            cx = sum(point[0] for point in points) / len(points)
            cy = sum(point[1] for point in points) / len(points)
            draw.text((cx - 28, cy - 7), str(room.get("room_label") or ""), fill=(20, 35, 70, 255))
    for fixture in semantics.get("static_landmarks") or []:
        pose = fixture.get("pose") or {}
        x, y = project(float(pose.get("x", 0.0)), float(pose.get("y", 0.0)))
        draw.rectangle((x - 8, y - 6, x + 8, y + 6), fill=(128, 82, 32, 220))
    for waypoint in semantics.get("inspection_waypoints") or []:
        x, y = project(float(waypoint.get("x", 0.0)), float(waypoint.get("y", 0.0)))
        draw.ellipse((x - 5, y - 5, x + 5, y + 5), fill=(22, 163, 74, 240))
        draw.text((x + 7, y - 6), str(waypoint.get("waypoint_id") or ""), fill=(12, 69, 38, 255))
    max_width = 1200
    if image.width > max_width:
        ratio = max_width / image.width
        image = image.resize((max_width, max(1, int(image.height * ratio))))
    image.save(path, format="PNG")


def _snapshot_payload(
    *,
    bundle_dir: Path,
    source_map_dir: Path,
    semantics: dict[str, Any],
) -> dict[str, Any]:
    run_dir = bundle_dir.parent
    artifacts = {
        "map_yaml": bundle_dir / "map.yaml",
        "occupancy_image": bundle_dir / "map.pgm",
        "semantics_json": bundle_dir / "semantics.json",
        "robot_profile": bundle_dir / "profiles" / f"{DEFAULT_ROBOT_PROFILE_ID}.yaml",
        "costmap_params": bundle_dir
        / "costmaps"
        / f"{DEFAULT_ROBOT_PROFILE_ID}.costmap_params.yaml",
        "preview_png": bundle_dir / "preview.png",
    }
    metadata = metric_map_bundle_metadata(
        environment_id=str(
            semantics.get("environment_id") or DEFAULT_AGIBOT_ENVIRONMENT_ID_FALLBACK
        ),
        map_id=str(
            semantics.get("map_id") or f"{DEFAULT_AGIBOT_ENVIRONMENT_ID_FALLBACK}_base_metric_map"
        ),
        map_version=str(semantics.get("map_version") or DEFAULT_AGIBOT_MAP_VERSION_FALLBACK),
    )
    return {
        "schema": NAV2_MAP_BUNDLE_SCHEMA,
        "source_schema": semantics.get("schema", ""),
        "environment_id": metadata["environment_id"],
        "map_id": metadata["map_id"],
        "map_version": metadata["map_version"],
        "source_provenance": AGIBOT_MAP_BUNDLE_PROVENANCE,
        "robot_profile_id": DEFAULT_ROBOT_PROFILE_ID,
        "costmap_profile_id": DEFAULT_COSTMAP_PROFILE_ID,
        "parameter_hash": metadata["parameter_hash"],
        "snapshot_root": bundle_dir.name,
        "snapshot_complete": all(path.is_file() for path in artifacts.values()),
        "source_bundle_root": str(source_map_dir),
        "artifact_paths": {
            key: path.relative_to(run_dir).as_posix() for key, path in artifacts.items()
        },
        "artifact_hashes": {key: _file_sha256(path) for key, path in artifacts.items()},
        "runtime_costmap_gaps": list(RUNTIME_COSTMAP_GAPS),
        "public_contract_note": (
            "Snapshot files adapt a fetched AgiBot map artifact into the shared "
            "Nav2-shaped static map contract. They do not prove live PNC execution."
        ),
    }


def _simple_yaml(value: Any, *, indent: int = 0) -> str:
    lines: list[str] = []
    prefix = " " * indent
    if isinstance(value, dict):
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


def _load_json(path: Path) -> dict[str, Any]:
    return read_json_object(path, label="Agibot map")


def _file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _load_raw_map(path: Path) -> dict[str, Any]:
    return read_gzip_json_object(path, label="Agibot raw map")


def _dict(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _list(value: Any) -> list[Any]:
    return value if isinstance(value, list) else []


if __name__ == "__main__":
    raise SystemExit(main())
