#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

if __package__ in {None, ""}:
    repo_root = Path(__file__).resolve().parents[2]
    if str(repo_root) not in sys.path:
        sys.path.insert(0, str(repo_root))

from roboclaws.core.json_sources import read_json_object  # noqa: E402
from roboclaws.maps.b1_alignment import (  # noqa: E402
    B1_MAP12_CORRESPONDENCES_SCHEMA,
    SEMANTIC_ANCHOR_ROLE,
    anchor_role,
    validate_correspondence_manifest,
)

SEMANTIC_PROJECTION_SCHEMA = "b1_map12_semantic_projection_v1"
ROOM_SEMANTICS_REFERENCE_SCHEMA = "scene_room_semantic_overlay_overrides_v1"
DEFAULT_CORRESPONDENCES = Path("assets/maps/b1-map12-scene-correspondences.json")
DEFAULT_ROOM_SEMANTICS = Path("assets/maps/b1-map12-room-semantics.json")
DEFAULT_OUTPUT = Path("output/b1-map12/semantic-projection/semantic_projection.json")


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Project B1 room labels into Map12 semantics only after accepted semantic "
            "anchors exist in the promoted correspondence manifest."
        )
    )
    parser.add_argument("--correspondences", type=Path, default=DEFAULT_CORRESPONDENCES)
    parser.add_argument("--room-semantics", type=Path, default=DEFAULT_ROOM_SEMANTICS)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    try:
        payload = build_semantic_projection(
            correspondences=read_json_object(
                args.correspondences,
                label="correspondence manifest",
            ),
            room_semantics=read_json_object(args.room_semantics, label="room semantics"),
            correspondences_path=args.correspondences,
            room_semantics_path=args.room_semantics,
        )
    except (FileNotFoundError, ValueError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(
        json.dumps(
            {
                "schema": payload["schema"],
                "status": payload["status"],
                "output": str(args.output),
                "room_projection_count": payload["room_projection_count"],
                "object_projection_status": payload["object_projection_status"],
            },
            sort_keys=True,
        )
    )
    return 0


def build_semantic_projection(
    *,
    correspondences: dict[str, Any],
    room_semantics: dict[str, Any],
    correspondences_path: Path | None = None,
    room_semantics_path: Path | None = None,
) -> dict[str, Any]:
    semantic_anchors = accepted_semantic_anchors(correspondences)
    rooms_by_partition = accepted_room_references_by_partition(room_semantics)
    anchors_by_partition: dict[str, list[dict[str, Any]]] = {}
    missing_rooms = []
    for anchor in semantic_anchors:
        partition_id = str(anchor.get("asset_partition_id") or "")
        room = rooms_by_partition.get(partition_id)
        if room is None:
            missing_rooms.append(partition_id)
            continue
        anchors_by_partition.setdefault(partition_id, []).append(anchor)
    if missing_rooms:
        raise ValueError(
            "accepted semantic anchors reference missing accepted DT room semantics: "
            + ", ".join(sorted(set(missing_rooms)))
        )
    rooms = [
        projected_room(anchors, rooms_by_partition[partition_id])
        for partition_id, anchors in sorted(anchors_by_partition.items())
    ]
    if not rooms:
        raise ValueError("no accepted semantic anchors could be projected")
    return {
        "schema": SEMANTIC_PROJECTION_SCHEMA,
        "status": "verified_room_semantics",
        "source_correspondences": str(correspondences_path or ""),
        "source_room_semantics": str(room_semantics_path or ""),
        "source_map_frame": str(correspondences.get("source_map_frame") or ""),
        "target_scene_frame": str(correspondences.get("target_scene_frame") or ""),
        "semantic_anchor_count": len(semantic_anchors),
        "room_projection_count": len(rooms),
        "rooms": rooms,
        "object_projection_status": "blocked_until_object_semantic_anchors",
        "objects": [],
        "policy": {
            "requires_promoted_correspondence_manifest": True,
            "requires_accepted_semantic_anchors": True,
            "proposed_anchors_are_rejected": True,
            "object_labels_are_not_inferred_from_room_anchors": True,
        },
    }


def accepted_semantic_anchors(correspondences: dict[str, Any]) -> list[dict[str, Any]]:
    if correspondences.get("schema") != B1_MAP12_CORRESPONDENCES_SCHEMA:
        raise ValueError(f"unexpected correspondence schema: {correspondences.get('schema')!r}")
    promotion_policy = correspondences.get("promotion_policy")
    if not isinstance(promotion_policy, dict):
        raise ValueError("correspondence manifest must be produced by the strict promoter")
    if promotion_policy.get("requires_review_status") != "accepted":
        raise ValueError("correspondence manifest promotion policy must require accepted anchors")
    errors = validate_correspondence_manifest(correspondences)
    if errors:
        raise ValueError("invalid correspondence manifest: " + "; ".join(errors))
    anchors = [
        anchor
        for anchor in correspondences.get("anchors") or []
        if isinstance(anchor, dict)
        and anchor.get("review_status") == "accepted"
        and anchor_role(anchor) == SEMANTIC_ANCHOR_ROLE
    ]
    if not anchors:
        raise ValueError("accepted semantic anchors are required before projecting room labels")
    return anchors


def accepted_room_references_by_partition(
    room_semantics: dict[str, Any],
) -> dict[str, dict[str, Any]]:
    if room_semantics.get("schema") != ROOM_SEMANTICS_REFERENCE_SCHEMA:
        raise ValueError(f"unexpected room semantics schema: {room_semantics.get('schema')!r}")
    rows = {}
    for room in room_semantics.get("rooms") or []:
        row = room if isinstance(room, dict) else {}
        if row.get("review_status") != "accepted":
            continue
        partition_id = accepted_room_partition_id(row)
        validate_accepted_room_reference(row)
        if partition_id in rows:
            raise ValueError(
                f"duplicate accepted room semantics for scene partition {partition_id!r}"
            )
        rows[partition_id] = row
    if not rows:
        raise ValueError("room semantics reference has no accepted rooms")
    return rows


def accepted_room_partition_id(row: dict[str, Any]) -> str:
    partition_id = str(row.get("asset_partition_id") or row.get("room_id") or "")
    if not partition_id:
        raise ValueError("accepted room semantics need asset_partition_id")
    return partition_id


def validate_accepted_room_reference(row: dict[str, Any]) -> None:
    if not row.get("room_label") or not row.get("category"):
        raise ValueError("accepted room semantics need room_label and category")
    if "geometry" in row or "polygon" in row or "map_polygon" in row:
        raise ValueError("room semantics reference must not carry Map12 geometry")


def projected_room(anchors: list[dict[str, Any]], room: dict[str, Any]) -> dict[str, Any]:
    navigation_area_ids = {str(anchor.get("navigation_area_id") or "") for anchor in anchors}
    if len(navigation_area_ids) != 1:
        raise ValueError(
            "accepted semantic anchors for a scene partition must share one navigation_area_id"
        )
    navigation_area_id = navigation_area_ids.pop()
    map_polygon = anchor_map_polygon(anchors)
    semantic_anchors = [
        {
            "source_anchor_id": str(anchor.get("anchor_id") or ""),
            "map_xy": [float(value) for value in anchor.get("map_xy") or []],
            "scene_xyz": [float(value) for value in anchor.get("scene_xyz") or []],
        }
        for anchor in anchors
    ]
    partition_id = str(anchors[0].get("asset_partition_id") or "")
    return {
        "room_id": str(room.get("room_id") or partition_id),
        "room_label": str(room.get("room_label") or partition_id),
        "category": str(room.get("category") or ""),
        "navigation_area_id": navigation_area_id,
        "asset_partition_id": partition_id,
        "semantic_anchor_count": len(anchors),
        "semantic_anchors": semantic_anchors,
        "map_polygon": map_polygon,
        "alignment_status": "accepted_semantic_anchor",
        "semantic_source": "reviewed_b1_map12_semantic_anchor",
        "review_status": "accepted",
        "source_room_semantics_id": partition_id,
        "source_anchor_ids": [item["source_anchor_id"] for item in semantic_anchors],
    }


def anchor_map_polygon(anchors: list[dict[str, Any]]) -> list[dict[str, float]]:
    polygons = [anchor.get("map_polygon") for anchor in anchors if "map_polygon" in anchor]
    if not polygons:
        raise ValueError("accepted semantic anchors need explicit map_polygon")
    first = normalize_map_polygon(polygons[0])
    for polygon in polygons[1:]:
        if normalize_map_polygon(polygon) != first:
            raise ValueError(
                "accepted semantic anchors for a scene partition must share one map_polygon"
            )
    return first


def normalize_map_polygon(payload: Any) -> list[dict[str, float]]:
    if not isinstance(payload, list) or len(payload) < 3:
        raise ValueError("map_polygon must contain at least three points")
    polygon = []
    for point in payload:
        if not isinstance(point, dict) or "x" not in point or "y" not in point:
            raise ValueError("map_polygon points must contain x/y")
        polygon.append({"x": float(point["x"]), "y": float(point["y"])})
    return polygon


if __name__ == "__main__":
    raise SystemExit(main())
