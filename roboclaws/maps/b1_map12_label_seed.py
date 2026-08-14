from __future__ import annotations

import copy
from pathlib import Path
from typing import Any

from roboclaws.core.json_sources import read_json_object
from roboclaws.maps.b1_map12_label_geometry import (
    SourceMapTransform,
    _center_from_room,
    _geometry_center,
    _polygon_points,
    _polygon_signature,
    world_to_pixel,
)
from roboclaws.maps.b1_scene_topdown_diagnostic import (
    DIAGNOSTIC_SCHEMA as SCENE_TOPDOWN_DIAGNOSTIC_SCHEMA,
)
from roboclaws.maps.b1_scene_topdown_rendering import (
    projected_bounds_polygon,
    scene_projector_from_topdown_packet,
)
from roboclaws.maps.spatial_contract import (
    ALIGNMENT_STATUS_CANDIDATE,
    GEOMETRY_SOURCE_GENERATED_CANDIDATE,
    GEOMETRY_SOURCE_OPERATOR_NAVIGATION_ZONE,
    POLYGON_ROLE_NAVIGATION_AREA,
)


def scene_bounds_review_seed_packet(
    *,
    scene_topdown_diagnostic_path: Path,
    alignment_artifact_path: Path,
    room_label_reference_path: Path,
    scene_topdown_render_path: Path,
    transform: SourceMapTransform,
    frame_id: str,
) -> dict[str, Any]:
    diagnostic = read_scene_topdown_diagnostic(scene_topdown_diagnostic_path)
    alignment = read_verified_scene_alignment(alignment_artifact_path)
    selected_transform = alignment["selected_transform"]
    label_reference = read_room_label_reference(room_label_reference_path)
    scene_topdown = read_json_object(scene_topdown_render_path, label="scene topdown render")
    projector = scene_projector_from_topdown_packet(scene_topdown)
    topdown_image = Path(str(scene_topdown.get("topdown_image") or ""))
    if not topdown_image.is_file():
        raise FileNotFoundError(f"scene topdown image missing: {topdown_image}")
    labels_by_partition = room_label_reference_by_partition(label_reference)
    shapes: list[dict[str, Any]] = []
    reference_regions = []
    for index, partition in enumerate(scene_bound_partitions(diagnostic), start=1):
        partition_id = str(partition["partition_id"])
        bounds = partition["bounds"]
        label_row = labels_by_partition.get(partition_id, {})
        scene_polygon = scene_bounds_polygon(bounds)
        map_polygon = [
            transform_scene_xy_to_map_point(point, selected_transform) for point in scene_polygon
        ]
        pixel_polygon = [world_to_pixel(point["x"], point["y"], transform) for point in map_polygon]
        center = _geometry_center({"kind": "polygon", "polygon": map_polygon})
        scene_pixel_polygon = [
            {"x": float(px), "y": float(py)}
            for px, py in projected_bounds_polygon(bounds, projector)
        ]
        display_label = str(label_row.get("room_label") or label_row.get("label") or partition_id)
        category = str(label_row.get("category") or "")
        review_status = str(label_row.get("review_status") or "needs_review")
        shape_id = f"scene_bbox_seed_{partition_id}"
        shapes.append(
            {
                "shape_id": shape_id,
                "label": display_label,
                "category": category,
                "navigation_area_id": "",
                "asset_partition_id": partition_id,
                "source_room_id": partition_id,
                "semantic_source": "digital_twin_object_aggregate_bbox_review_seed",
                "render_review_recommended": True,
                "source_map_frame_id": frame_id,
                "geometry": {
                    "kind": "polygon",
                    "polygon": map_polygon,
                    "pixel_polygon": pixel_polygon,
                },
                "map_center": center,
                "polygon_role": POLYGON_ROLE_NAVIGATION_AREA,
                "geometry_source": GEOMETRY_SOURCE_GENERATED_CANDIDATE,
                "source_alignment_status": "verified_transform_candidate_geometry",
                "alignment_status": ALIGNMENT_STATUS_CANDIDATE,
                "review_status": "draft",
                "review_seed": {
                    "source": "digital_twin_object_aggregate_bbox",
                    "partition_id": partition_id,
                    "source_review_status": review_status,
                    "object_bounds_count": int(partition.get("object_bounds_count") or 0),
                    "bounds_status": str(bounds.get("status") or ""),
                    "warning": (
                        "This is an editable review seed from object aggregate bounds, "
                        "not a verified room boundary."
                    ),
                },
                "polygon_usage": {
                    "navigation": True,
                    "semantic_labeling": ALIGNMENT_STATUS_CANDIDATE,
                    "review": True,
                },
            }
        )
        reference_regions.append(
            {
                "shape_id": shape_id,
                "partition_id": partition_id,
                "label": display_label,
                "category": category,
                "review_status": review_status,
                "object_bounds_count": int(partition.get("object_bounds_count") or 0),
                "scene_pixel_polygon": scene_pixel_polygon,
                "note": "Read-only DT object aggregate bbox reference.",
            }
        )
    return {
        "review_shape_seed_policy": {
            "enabled": True,
            "seed_count": len(shapes),
            "source": str(scene_topdown_diagnostic_path),
            "alignment_artifact": str(alignment_artifact_path),
            "room_label_reference": str(room_label_reference_path),
            "geometry_source": GEOMETRY_SOURCE_GENERATED_CANDIDATE,
            "label_status": "candidate_draft_only",
            "note": (
                "Seeds come from Digital Twin object aggregate bboxes transformed back "
                "into Map12 with verified alignment. They are intentionally draft-only."
            ),
        },
        "scene_reference": {
            "schema": "b1_map12_label_tool_scene_reference_v1",
            "source_topdown_render": str(scene_topdown_render_path),
            "source_topdown_image": str(topdown_image),
            "source_diagnostic": str(scene_topdown_diagnostic_path),
            "coordinate_policy": (
                "scene reference polygons are read-only Digital Twin object aggregate "
                "bbox pixels; edit final labels on the Map12 canvas."
            ),
            "image_width_px": int(scene_topdown.get("width_px") or 0),
            "image_height_px": int(scene_topdown.get("height_px") or 0),
            "regions": reference_regions,
        },
        "shapes": shapes,
    }


def read_scene_topdown_diagnostic(path: Path) -> dict[str, Any]:
    diagnostic = read_json_object(path, label="scene topdown diagnostic")
    if diagnostic.get("schema") != SCENE_TOPDOWN_DIAGNOSTIC_SCHEMA:
        raise ValueError(
            f"scene topdown diagnostic schema must be {SCENE_TOPDOWN_DIAGNOSTIC_SCHEMA}: {path}"
        )
    validation = (
        diagnostic.get("validation") if isinstance(diagnostic.get("validation"), dict) else {}
    )
    if validation.get("status") != "passed":
        errors = validation.get("errors") if isinstance(validation.get("errors"), list) else []
        raise ValueError(
            f"scene topdown diagnostic must have validation.status=passed: {path}; errors={errors}"
        )
    return diagnostic


def read_verified_scene_alignment(path: Path) -> dict[str, Any]:
    alignment = read_json_object(path, label="alignment artifact")
    if alignment.get("global_alignment_status") != "verified":
        raise ValueError(f"alignment artifact must have global_alignment_status=verified: {path}")
    transform = alignment.get("selected_transform")
    if not isinstance(transform, dict):
        raise ValueError(f"alignment artifact missing selected_transform: {path}")
    if transform.get("type") != "rigid_2d":
        raise ValueError(f"alignment artifact selected_transform.type must be rigid_2d: {path}")
    if str(transform.get("source") or "") != "reviewed_correspondence_fit":
        raise ValueError(
            "alignment artifact selected_transform.source must be "
            f"reviewed_correspondence_fit: {path}"
        )
    return alignment


def read_room_label_reference(path: Path) -> dict[str, Any]:
    reference = read_json_object(path, label="room label reference")
    rooms = reference.get("rooms")
    if not isinstance(rooms, list):
        raise ValueError(f"room label reference must contain rooms list: {path}")
    return reference


def room_label_reference_by_partition(reference: dict[str, Any]) -> dict[str, dict[str, Any]]:
    output = {}
    for room in reference.get("rooms") or []:
        if not isinstance(room, dict):
            continue
        partition_id = str(room.get("asset_partition_id") or room.get("room_id") or "")
        if partition_id:
            output[partition_id] = room
    return output


def scene_bound_partitions(diagnostic: dict[str, Any]) -> list[dict[str, Any]]:
    output = []
    for partition in diagnostic.get("partitions") or []:
        if not isinstance(partition, dict):
            continue
        partition_id = str(partition.get("partition_id") or "")
        bounds = (
            partition.get("scene_frame_bounds")
            if isinstance(partition.get("scene_frame_bounds"), dict)
            else {}
        )
        if not partition_id:
            continue
        if bounds.get("status") != "extracted_from_scene_usd_world_bounds":
            continue
        output.append(
            {
                "partition_id": partition_id,
                "bounds": bounds,
                "object_bounds_count": int(partition.get("object_bounds_count") or 0),
            }
        )
    if not output:
        raise ValueError("scene topdown diagnostic did not contain scene USD world bounds")
    return output


def scene_bounds_polygon(bounds: dict[str, Any]) -> list[dict[str, float]]:
    required = ("min_x", "min_y", "max_x", "max_y")
    try:
        min_x, min_y, max_x, max_y = (float(bounds[key]) for key in required)
    except (KeyError, TypeError, ValueError) as exc:
        raise ValueError("scene bounds missing finite min_x/min_y/max_x/max_y") from exc
    return [
        {"x": min_x, "y": min_y},
        {"x": max_x, "y": min_y},
        {"x": max_x, "y": max_y},
        {"x": min_x, "y": max_y},
    ]


def transform_scene_xy_to_map_point(
    scene_point: dict[str, float],
    transform: dict[str, Any],
) -> dict[str, float]:
    scale = float(transform.get("scale") or 1.0)
    if scale == 0.0:
        raise ValueError("alignment transform scale must be non-zero")
    rotation = transform.get("rotation_matrix")
    if not isinstance(rotation, list) or len(rotation) != 2:
        raise ValueError("alignment transform rotation_matrix must be 2x2")
    try:
        r00 = float(rotation[0][0])
        r01 = float(rotation[0][1])
        r10 = float(rotation[1][0])
        r11 = float(rotation[1][1])
        tx = float((transform.get("translation") or [0.0, 0.0])[0])
        ty = float((transform.get("translation") or [0.0, 0.0])[1])
    except (TypeError, ValueError, IndexError) as exc:
        raise ValueError("alignment transform must contain numeric rotation/translation") from exc
    sx = (float(scene_point["x"]) - tx) / scale
    sy = (float(scene_point["y"]) - ty) / scale
    return {
        "x": round(r00 * sx + r10 * sy, 6),
        "y": round(r01 * sx + r11 * sy, 6),
    }


def source_map_frame_id(semantics: dict[str, Any]) -> str:
    frame_ids = semantics.get("frame_ids") if isinstance(semantics.get("frame_ids"), dict) else {}
    if frame_ids.get("map"):
        return str(frame_ids["map"])
    contract = (
        semantics.get("spatial_contract")
        if isinstance(semantics.get("spatial_contract"), dict)
        else {}
    )
    source_frame = (
        contract.get("source_map_frame")
        if isinstance(contract.get("source_map_frame"), dict)
        else {}
    )
    return str(source_frame.get("frame_id") or "map")


def seed_shapes_from_semantics(
    semantics: dict[str, Any],
    *,
    transform: SourceMapTransform,
    frame_id: str,
) -> list[dict[str, Any]]:
    shapes: list[dict[str, Any]] = []
    for index, raw_room in enumerate(semantics.get("rooms") or [], start=1):
        if not isinstance(raw_room, dict):
            continue
        room = copy.deepcopy(raw_room)
        polygon = _polygon_points(room.get("polygon"))
        center = _center_from_room(room, polygon)
        shape_id = str(room.get("room_id") or f"label_{index:03d}")
        geometry: dict[str, Any]
        if len(polygon) >= 3:
            geometry = {
                "kind": "polygon",
                "polygon": polygon,
                "pixel_polygon": [
                    world_to_pixel(point["x"], point["y"], transform) for point in polygon
                ],
            }
        else:
            geometry = {
                "kind": "point",
                "center": center,
                "pixel_center": world_to_pixel(center["x"], center["y"], transform),
            }
        shapes.append(
            {
                "shape_id": shape_id,
                "label": str(room.get("label") or room.get("room_id") or shape_id),
                "category": str(room.get("category") or ""),
                "navigation_area_id": str(room.get("navigation_area_id") or ""),
                "asset_partition_id": str(room.get("asset_partition_id") or ""),
                "source_room_id": str(room.get("room_id") or ""),
                "semantic_source": str(room.get("semantic_source") or ""),
                "render_review_recommended": bool(room.get("render_review_recommended")),
                "source_map_frame_id": str(room.get("source_map_frame_id") or frame_id),
                "geometry": geometry,
                "map_center": center,
                "polygon_role": str(room.get("polygon_role") or POLYGON_ROLE_NAVIGATION_AREA),
                "geometry_source": str(
                    room.get("geometry_source") or GEOMETRY_SOURCE_OPERATOR_NAVIGATION_ZONE
                ),
                "source_alignment_status": str(room.get("alignment_status") or ""),
                "alignment_status": ALIGNMENT_STATUS_CANDIDATE,
                "review_status": "draft",
                "polygon_usage": {
                    "navigation": True,
                    "semantic_labeling": ALIGNMENT_STATUS_CANDIDATE,
                    "review": True,
                },
            }
        )
    return shapes


def attach_room_geometry_conflicts(shapes: list[dict[str, Any]]) -> None:
    groups: dict[str, list[dict[str, Any]]] = {}
    for shape in shapes:
        geometry = shape.get("geometry") if isinstance(shape.get("geometry"), dict) else {}
        if geometry.get("kind") != "polygon":
            continue
        key = _polygon_signature(_polygon_points(geometry.get("polygon")))
        if key:
            groups.setdefault(key, []).append(shape)
    for group in groups.values():
        if len(group) < 2:
            continue
        room_ids = [
            str(shape.get("source_room_id") or shape.get("shape_id") or "") for shape in group
        ]
        labels = [str(shape.get("label") or shape.get("shape_id") or "") for shape in group]
        sources = sorted({str(shape.get("semantic_source") or "") for shape in group if shape})
        conflict = {
            "status": "shared_polygon",
            "room_ids": room_ids,
            "labels": labels,
            "semantic_sources": sources,
            "message": "multiple semantic room labels currently share the same map polygon",
        }
        for shape in group:
            shape["geometry_conflict"] = copy.deepcopy(conflict)
