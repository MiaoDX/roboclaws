from __future__ import annotations

import argparse
import copy
import json
import sys
from pathlib import Path
from typing import Any

from roboclaws.core.json_sources import read_json_object

MAP_SPATIAL_CONTRACT_SCHEMA = "map_spatial_contract_v1"

POLYGON_ROLE_NAVIGATION_AREA = "navigation_area"
POLYGON_ROLE_ROOM_BOUNDARY = "room_boundary"
POLYGON_ROLE_SCENE_PARTITION = "scene_partition"
POLYGON_ROLES = frozenset(
    {
        POLYGON_ROLE_NAVIGATION_AREA,
        POLYGON_ROLE_ROOM_BOUNDARY,
        POLYGON_ROLE_SCENE_PARTITION,
    }
)

GEOMETRY_SOURCE_OPERATOR_NAVIGATION_ZONE = "operator_authored_navigation_zone"
GEOMETRY_SOURCE_TRACED_ROOM_BOUNDARY = "traced_occupancy_room_boundary"
GEOMETRY_SOURCE_SCENE_ENGINE_PARTITION = "scene_engine_partition"
GEOMETRY_SOURCE_RUNTIME_OBSERVATION = "runtime_observation"
GEOMETRY_SOURCE_GENERATED_CANDIDATE = "generated_candidate"
POLYGON_GEOMETRY_SOURCES = frozenset(
    {
        GEOMETRY_SOURCE_OPERATOR_NAVIGATION_ZONE,
        GEOMETRY_SOURCE_TRACED_ROOM_BOUNDARY,
        GEOMETRY_SOURCE_SCENE_ENGINE_PARTITION,
        GEOMETRY_SOURCE_RUNTIME_OBSERVATION,
        GEOMETRY_SOURCE_GENERATED_CANDIDATE,
    }
)

ALIGNMENT_STATUS_NATIVE = "native"
ALIGNMENT_STATUS_CANDIDATE = "candidate"
ALIGNMENT_STATUS_VERIFIED = "verified"
ALIGNMENT_STATUS_RUNTIME_PROVEN = "runtime_proven"
ALIGNMENT_STATUS_PLANNER_BACKED = "planner_backed"
ALIGNMENT_STATUS_BLOCKED = "blocked"
ALIGNMENT_STATUSES = frozenset(
    {
        ALIGNMENT_STATUS_NATIVE,
        ALIGNMENT_STATUS_CANDIDATE,
        ALIGNMENT_STATUS_VERIFIED,
        ALIGNMENT_STATUS_RUNTIME_PROVEN,
        ALIGNMENT_STATUS_PLANNER_BACKED,
        ALIGNMENT_STATUS_BLOCKED,
    }
)

DISPLAY_FRAME_STATUS_ABSENT = "absent_first_slice_raw_source_map_frame_only"


def source_frame_spatial_contract(
    *,
    frame_id: str,
    alignment_status: str = ALIGNMENT_STATUS_NATIVE,
) -> dict[str, Any]:
    return {
        "schema": MAP_SPATIAL_CONTRACT_SCHEMA,
        "source_map_frame": {
            "frame_id": frame_id,
            "units": "meters",
            "spatial_truth": True,
        },
        "semantic_geometry_frame": "source_map_frame",
        "display_frame_status": DISPLAY_FRAME_STATUS_ABSENT,
        "alignment_status": alignment_status,
        "public_contract_note": (
            "Semantic geometry is authored in the source map frame. This first "
            "slice intentionally has no rectified display frame."
        ),
    }


def normalize_spatial_room(
    room: dict[str, Any],
    *,
    frame_id: str,
    polygon_role: str = POLYGON_ROLE_NAVIGATION_AREA,
    geometry_source: str = GEOMETRY_SOURCE_OPERATOR_NAVIGATION_ZONE,
    alignment_status: str = ALIGNMENT_STATUS_NATIVE,
    semantic_label_status: str | None = None,
) -> dict[str, Any]:
    item = copy.deepcopy(room)
    item.setdefault("polygon_role", polygon_role)
    item.setdefault("geometry_source", geometry_source)
    item.setdefault("alignment_status", alignment_status)
    item.setdefault("source_map_frame_id", frame_id)
    item.setdefault(
        "polygon_usage",
        {
            "navigation": item["polygon_role"] == POLYGON_ROLE_NAVIGATION_AREA,
            "semantic_labeling": semantic_label_status or item["alignment_status"],
            "review": True,
        },
    )
    return item


def normalize_spatial_rooms(
    rooms: list[Any],
    *,
    frame_id: str,
    polygon_role: str = POLYGON_ROLE_NAVIGATION_AREA,
    geometry_source: str = GEOMETRY_SOURCE_OPERATOR_NAVIGATION_ZONE,
    alignment_status: str = ALIGNMENT_STATUS_NATIVE,
    semantic_label_status: str | None = None,
) -> list[dict[str, Any]]:
    return [
        normalize_spatial_room(
            room,
            frame_id=frame_id,
            polygon_role=polygon_role,
            geometry_source=geometry_source,
            alignment_status=alignment_status,
            semantic_label_status=semantic_label_status,
        )
        for room in rooms
        if isinstance(room, dict)
    ]


def normalize_semantic_map_spatial_contract(bundle_dir: Path) -> None:
    semantics_path = Path(bundle_dir) / "semantics.json"
    semantics = read_json_object(semantics_path, label="semantics")
    frame_id = str((semantics.get("frame_ids") or {}).get("map") or "map")
    alignment_status = ALIGNMENT_STATUS_NATIVE
    semantics["spatial_contract"] = source_frame_spatial_contract(
        frame_id=frame_id,
        alignment_status=alignment_status,
    )
    semantics["display_frame"] = None
    semantics["rooms"] = normalize_spatial_rooms(
        semantics.get("rooms") or [],
        frame_id=frame_id,
        polygon_role=POLYGON_ROLE_NAVIGATION_AREA,
        geometry_source=GEOMETRY_SOURCE_OPERATOR_NAVIGATION_ZONE,
        alignment_status=alignment_status,
        semantic_label_status=alignment_status,
    )
    semantics_path.write_text(
        json.dumps(semantics, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Add first-slice source-frame spatial contract metadata to map bundles."
    )
    parser.add_argument("bundle_dirs", type=Path, nargs="+")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    try:
        for bundle_dir in args.bundle_dirs:
            normalize_semantic_map_spatial_contract(bundle_dir)
            print(f"normalized spatial contract: {bundle_dir}")
        return 0
    except (FileNotFoundError, ValueError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2


def require_source_frame_spatial_contract(
    semantics: dict[str, Any],
    errors: list[str],
) -> None:
    if "display_frame" not in semantics:
        errors.append("semantics.json must explicitly set display_frame to null")
    elif semantics.get("display_frame") is not None:
        errors.append("semantics.json display_frame must be null for raw/source-frame previews")

    contract = semantics.get("spatial_contract")
    if not isinstance(contract, dict):
        errors.append("semantics.json must contain spatial_contract")
        return
    if contract.get("schema") != MAP_SPATIAL_CONTRACT_SCHEMA:
        errors.append(
            f"semantics.json spatial_contract.schema must be {MAP_SPATIAL_CONTRACT_SCHEMA}"
        )
    source_frame = contract.get("source_map_frame")
    if not isinstance(source_frame, dict) or not source_frame.get("frame_id"):
        errors.append("semantics.json spatial_contract must contain source_map_frame.frame_id")
    else:
        frame_ids = (
            semantics.get("frame_ids") if isinstance(semantics.get("frame_ids"), dict) else {}
        )
        map_frame_id = str(frame_ids.get("map") or "")
        if map_frame_id and str(source_frame.get("frame_id") or "") != map_frame_id:
            errors.append(
                "semantics.json spatial_contract.source_map_frame.frame_id must match frame_ids.map"
            )
    if contract.get("semantic_geometry_frame") != "source_map_frame":
        errors.append("semantics.json semantic_geometry_frame must be source_map_frame")
    if contract.get("display_frame_status") != DISPLAY_FRAME_STATUS_ABSENT:
        errors.append(
            "semantics.json spatial_contract.display_frame_status must declare "
            "first-slice display_frame absence"
        )
    _validate_alignment_status(
        contract.get("alignment_status"),
        "spatial_contract.alignment_status",
        errors,
    )


def validate_spatial_room_contract(room: dict[str, Any], *, index: int, errors: list[str]) -> None:
    room_id = str(room.get("room_id") or f"rooms[{index}]")
    polygon_role = str(room.get("polygon_role") or "")
    geometry_source = str(room.get("geometry_source") or "")
    alignment_status = str(room.get("alignment_status") or "")
    if polygon_role not in POLYGON_ROLES:
        errors.append(f"room {room_id} missing valid polygon_role")
    if geometry_source not in POLYGON_GEOMETRY_SOURCES:
        errors.append(f"room {room_id} missing valid geometry_source")
    _validate_alignment_status(alignment_status, f"room {room_id} alignment_status", errors)
    if not str(room.get("source_map_frame_id") or ""):
        errors.append(f"room {room_id} missing source_map_frame_id")
    polygon_usage = room.get("polygon_usage")
    if not isinstance(polygon_usage, dict):
        errors.append(f"room {room_id} missing polygon_usage")
    else:
        for key in ("navigation", "semantic_labeling", "review"):
            if key not in polygon_usage:
                errors.append(f"room {room_id} polygon_usage missing {key}")
    if polygon_role == POLYGON_ROLE_ROOM_BOUNDARY:
        if geometry_source == GEOMETRY_SOURCE_OPERATOR_NAVIGATION_ZONE:
            errors.append(
                f"room {room_id} cannot present an operator navigation zone as a room_boundary"
            )
        if alignment_status in {ALIGNMENT_STATUS_CANDIDATE, ALIGNMENT_STATUS_BLOCKED}:
            errors.append(
                f"room {room_id} cannot present {alignment_status} geometry as a room_boundary"
            )


def _validate_alignment_status(value: Any, label: str, errors: list[str]) -> None:
    if str(value or "") not in ALIGNMENT_STATUSES:
        errors.append(f"{label} must be one of {sorted(ALIGNMENT_STATUSES)}")


if __name__ == "__main__":
    raise SystemExit(main())
