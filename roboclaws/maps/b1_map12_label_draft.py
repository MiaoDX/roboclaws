from __future__ import annotations

import base64
import io
import json
from pathlib import Path
from typing import Any

from PIL import Image

from roboclaws.maps.b1_map12_label_geometry import _draft_geometry, _geometry_center
from roboclaws.maps.spatial_contract import (
    ALIGNMENT_STATUS_CANDIDATE,
    GEOMETRY_SOURCE_OPERATOR_NAVIGATION_ZONE,
    POLYGON_ROLES,
)

TEMPLATE_PATH = Path(__file__).with_name("b1_map12_label_tool_template.html")
LABEL_DRAFT_MANIFEST_SCHEMA = "b1_map12_label_draft_manifest_v1"


def draft_manifest_from_shapes(
    shapes: list[dict[str, Any]],
    *,
    source_packet: dict[str, Any],
) -> dict[str, Any]:
    labels = [draft_label_from_shape(shape) for shape in shapes]
    manifest = {
        "schema": LABEL_DRAFT_MANIFEST_SCHEMA,
        "source_map_frame_id": str(source_packet.get("source_map_frame_id") or "map"),
        "map_bundle": str(source_packet.get("map_bundle") or ""),
        "source_semantics": str(source_packet.get("source_semantics") or ""),
        "source_image": str(source_packet.get("source_image") or ""),
        "review_status": "draft",
        "alignment_status": ALIGNMENT_STATUS_CANDIDATE,
        "source_map_mutated": False,
        "verified_status_allowed": False,
        "labels": labels,
    }
    errors = validate_label_draft_manifest(manifest)
    if errors:
        raise ValueError("; ".join(errors))
    return manifest


def draft_label_from_shape(shape: dict[str, Any]) -> dict[str, Any]:
    geometry = _draft_geometry(shape.get("geometry"))
    center = geometry.get("center") or _geometry_center(geometry)
    return {
        "label_id": str(shape.get("shape_id") or ""),
        "label": str(shape.get("label") or ""),
        "category": str(shape.get("category") or ""),
        "navigation_area_id": str(shape.get("navigation_area_id") or ""),
        "asset_partition_id": str(shape.get("asset_partition_id") or ""),
        "source_room_id": str(shape.get("source_room_id") or ""),
        "source_map_frame_id": str(shape.get("source_map_frame_id") or "map"),
        "geometry": geometry,
        "map_center": center,
        "polygon_role": str(shape.get("polygon_role") or ""),
        "geometry_source": GEOMETRY_SOURCE_OPERATOR_NAVIGATION_ZONE,
        "alignment_status": ALIGNMENT_STATUS_CANDIDATE,
        "review_status": "draft",
        "polygon_usage": {
            "navigation": True,
            "semantic_labeling": ALIGNMENT_STATUS_CANDIDATE,
            "review": True,
        },
    }


def validate_label_draft_manifest(payload: dict[str, Any]) -> list[str]:
    errors = _draft_manifest_header_errors(payload)
    for index, raw_label in enumerate(payload.get("labels") or [], start=1):
        errors.extend(_draft_manifest_label_errors(raw_label, index=index))
    return errors


def _draft_manifest_header_errors(payload: dict[str, Any]) -> list[str]:
    errors = []
    if payload.get("schema") != LABEL_DRAFT_MANIFEST_SCHEMA:
        errors.append(f"schema must be {LABEL_DRAFT_MANIFEST_SCHEMA}")
    if payload.get("source_map_mutated") is not False:
        errors.append("label drafts must not mutate the source map")
    if payload.get("verified_status_allowed") is not False:
        errors.append("label drafts must not allow verified status")
    return errors


def _draft_manifest_label_errors(raw_label: Any, *, index: int) -> list[str]:
    errors = []
    label = raw_label if isinstance(raw_label, dict) else {}
    label_id = str(label.get("label_id") or f"labels[{index}]")
    if label.get("alignment_status") != ALIGNMENT_STATUS_CANDIDATE:
        errors.append(f"label {label_id} alignment_status must remain candidate")
    if label.get("review_status") != "draft":
        errors.append(f"label {label_id} review_status must remain draft")
    polygon_role = str(label.get("polygon_role") or "")
    if polygon_role not in POLYGON_ROLES:
        errors.append(f"label {label_id} polygon_role must be one of {sorted(POLYGON_ROLES)}")
    geometry = label.get("geometry") if isinstance(label.get("geometry"), dict) else {}
    errors.extend(_draft_manifest_geometry_errors(label_id, geometry))
    return errors


def _draft_manifest_geometry_errors(label_id: str, geometry: dict[str, Any]) -> list[str]:
    kind = str(geometry.get("kind") or "")
    if kind == "polygon" and len(geometry.get("polygon") or []) < 3:
        return [f"label {label_id} polygon needs at least three points"]
    if kind == "circle":
        return _draft_manifest_circle_errors(label_id, geometry)
    if kind == "point" and not isinstance(geometry.get("center"), dict):
        return [f"label {label_id} point needs a center"]
    if kind not in {"polygon", "circle", "point"}:
        return [f"label {label_id} has unsupported geometry kind"]
    return []


def _draft_manifest_circle_errors(label_id: str, geometry: dict[str, Any]) -> list[str]:
    errors = []
    if not isinstance(geometry.get("center"), dict):
        errors.append(f"label {label_id} circle needs a center")
    if float(geometry.get("radius_m") or 0.0) <= 0.0:
        errors.append(f"label {label_id} circle radius_m must be positive")
    return errors


def image_data_url(path: Path) -> str:
    with Image.open(path) as image:
        png = image.convert("RGB")
        buffer = io.BytesIO()
        png.save(buffer, format="PNG")
    encoded = base64.b64encode(buffer.getvalue()).decode("ascii")
    return f"data:image/png;base64,{encoded}"


def scene_reference_image_data_url(packet: dict[str, Any]) -> str:
    reference = (
        packet.get("scene_reference") if isinstance(packet.get("scene_reference"), dict) else {}
    )
    source = str(reference.get("source_topdown_image") or "")
    if not source:
        return ""
    return image_data_url(Path(source))


def render_label_tool_html(
    packet: dict[str, Any],
    *,
    image_data_url_value: str,
    scene_reference_data_url_value: str = "",
) -> str:
    packet_json = json.dumps(packet, sort_keys=True)
    image_json = json.dumps(image_data_url_value)
    scene_reference_json = json.dumps(scene_reference_data_url_value)
    return (
        label_tool_template()
        .replace("__PACKET_JSON__", packet_json)
        .replace(
            "__IMAGE_DATA_URL__",
            image_json,
        )
        .replace("__SCENE_REFERENCE_DATA_URL__", scene_reference_json)
    )


def label_tool_template_path() -> Path:
    return TEMPLATE_PATH


def label_tool_template() -> str:
    return TEMPLATE_PATH.read_text(encoding="utf-8")
