from __future__ import annotations

from pathlib import Path
from typing import Any

from roboclaws.maps.room_semantics import build_scene_room_semantic_overlay
from roboclaws.maps.spatial_contract import ALIGNMENT_STATUS_CANDIDATE


def scene_evidence_from_semantics(semantics: dict[str, Any]) -> dict[str, Any]:
    rooms: dict[str, dict[str, Any]] = {}
    for raw_room in semantics.get("rooms") or []:
        if not isinstance(raw_room, dict):
            continue
        room_id = str(raw_room.get("room_id") or "")
        if not room_id:
            continue
        evidence = raw_room.get("evidence") if isinstance(raw_room.get("evidence"), dict) else {}
        correspondence = (
            raw_room.get("scene_map_correspondence")
            if isinstance(raw_room.get("scene_map_correspondence"), dict)
            else {}
        )
        object_name_counts = evidence.get("object_name_counts")
        object_name_counts = object_name_counts if isinstance(object_name_counts, dict) else {}
        rooms[room_id] = {
            "room_id": room_id,
            "room_label": str(raw_room.get("room_label") or raw_room.get("label") or room_id),
            "navigation_area_id": str(raw_room.get("navigation_area_id") or ""),
            "candidate_scene_partition_id": str(
                correspondence.get("asset_partition_id")
                or raw_room.get("asset_partition_id")
                or evidence.get("partition_name")
                or ""
            ),
            "partition_name": str(evidence.get("partition_name") or ""),
            "alignment_status": str(
                correspondence.get("alignment_status")
                or raw_room.get("alignment_status")
                or ALIGNMENT_STATUS_CANDIDATE
            ),
            "transform_source": str(correspondence.get("transform_source") or ""),
            "map_polygon_provided": bool(correspondence.get("map_polygon_provided")),
            "weak_evidence": bool(evidence.get("weak_evidence")),
            "matched_terms": [str(item) for item in evidence.get("matched_terms") or []],
            "conflicting_evidence": [
                str(item) for item in evidence.get("conflicting_evidence") or []
            ],
            "object_name_counts": {
                str(name): int(count)
                for name, count in sorted(
                    object_name_counts.items(),
                    key=lambda item: (-int(item[1]), str(item[0])),
                )
            },
            "evidence_artifacts": [
                str(item)
                for item in (
                    correspondence.get("evidence_artifacts") or evidence.get("artifacts") or []
                )
            ],
            "semantic_source": str(raw_room.get("semantic_source") or ""),
            "coordinate_status": "scene_evidence_has_no_map_coordinates",
            "identity_status": "candidate_name_match_not_verified_identity",
        }
    return {
        "schema": "b1_map12_scene_evidence_packet_v1",
        "coordinate_policy": "do_not_project_scene_or_gaussian_objects_without_verified_transform",
        "rooms": rooms,
    }


def scene_evidence_from_scene_root(
    scene_root: Path,
    *,
    map_bundle: Path,
    fallback_semantics: dict[str, Any],
) -> dict[str, Any]:
    scene_root = Path(scene_root)
    if not scene_root.is_dir():
        return scene_evidence_from_semantics(fallback_semantics)
    overlay = build_scene_room_semantic_overlay(scene_root, source_bundle_dir=map_bundle)
    rooms: dict[str, dict[str, Any]] = {}
    correspondences = {
        str(item.get("asset_partition_id") or ""): item
        for item in overlay.get("scene_map_correspondence_v1") or []
        if isinstance(item, dict)
    }
    for raw_room in overlay.get("rooms") or []:
        if not isinstance(raw_room, dict):
            continue
        room_id = str(raw_room.get("asset_partition_id") or raw_room.get("room_id") or "")
        if not room_id:
            continue
        evidence = raw_room.get("evidence") if isinstance(raw_room.get("evidence"), dict) else {}
        correspondence = correspondences.get(room_id, {})
        object_name_counts = evidence.get("object_name_counts")
        object_name_counts = object_name_counts if isinstance(object_name_counts, dict) else {}
        rooms[room_id] = {
            "room_id": room_id,
            "room_label": str(raw_room.get("room_label") or room_id),
            "navigation_area_id": str(correspondence.get("navigation_area_id") or ""),
            "candidate_scene_partition_id": room_id,
            "partition_name": str(evidence.get("partition_name") or room_id),
            "alignment_status": str(
                correspondence.get("alignment_status")
                or raw_room.get("alignment_status")
                or ALIGNMENT_STATUS_CANDIDATE
            ),
            "transform_source": str(correspondence.get("transform_source") or ""),
            "map_polygon_provided": bool(correspondence.get("map_polygon_provided")),
            "weak_evidence": bool(evidence.get("weak_evidence")),
            "matched_terms": [str(item) for item in evidence.get("matched_terms") or []],
            "conflicting_evidence": [
                str(item) for item in evidence.get("conflicting_evidence") or []
            ],
            "object_name_counts": {
                str(name): int(count)
                for name, count in sorted(
                    object_name_counts.items(),
                    key=lambda item: (-int(item[1]), str(item[0])),
                )
            },
            "evidence_artifacts": [
                str(item)
                for item in (
                    correspondence.get("evidence_artifacts") or evidence.get("artifacts") or []
                )
            ],
            "semantic_source": str(raw_room.get("semantic_source") or ""),
            "coordinate_status": "scene_evidence_has_no_map_coordinates",
            "identity_status": "candidate_name_match_not_verified_identity",
        }
    return {
        "schema": "b1_map12_scene_evidence_packet_v1",
        "scene_root": str(scene_root),
        "coordinate_policy": "do_not_project_scene_or_gaussian_objects_without_verified_transform",
        "rooms": rooms,
    }
