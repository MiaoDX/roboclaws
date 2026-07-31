#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import sys
from pathlib import Path
from typing import Any

from PIL import Image

if __package__ in {None, ""}:
    repo_root = Path(__file__).resolve().parents[2]
    if str(repo_root) not in sys.path:
        sys.path.insert(0, str(repo_root))

from roboclaws.core.json_sources import read_json_object
from roboclaws.maps.b1_map12_label_draft import (
    draft_manifest_from_shapes,
    image_data_url,
    render_label_tool_html,
    scene_reference_image_data_url,
)
from roboclaws.maps.b1_map12_label_geometry import (
    SourceMapTransform,
    _origin,
    _repo_artifact_path,
)
from roboclaws.maps.b1_map12_label_seed import (
    attach_room_geometry_conflicts,
    scene_bounds_review_seed_packet,
    seed_shapes_from_semantics,
    source_map_frame_id,
)
from roboclaws.maps.b1_map12_scene_evidence import (
    scene_evidence_from_scene_root,
)
from roboclaws.maps.b1_map12_source_layers import (
    navigation_memory_layer_from_path,
    source_map_layers_from_semantics,
)
from roboclaws.maps.bundle_validation import parse_map_yaml
from roboclaws.maps.spatial_contract import (
    ALIGNMENT_STATUS_CANDIDATE,
    GEOMETRY_SOURCE_OPERATOR_NAVIGATION_ZONE,
    POLYGON_GEOMETRY_SOURCES,
    POLYGON_ROLE_NAVIGATION_AREA,
    POLYGON_ROLES,
)

LABEL_TOOL_PACKET_SCHEMA = "b1_map12_label_tool_packet_v1"
LABEL_DRAFT_MANIFEST_SCHEMA = "b1_map12_label_draft_manifest_v1"
DEFAULT_MAP12_ROOT = Path("vendors/agibot_sdk/artifacts/maps/robot_map_12")
DEFAULT_MAP_BUNDLE = DEFAULT_MAP12_ROOT / "agibot"
DEFAULT_SCENE_ROOT = Path("data/robot-data-lab/scene-engine/data/2rd_floor_seperated")
DEFAULT_OUTPUT_DIR = Path("output/b1-map12/label-tool")
DEFAULT_ROOM_LABEL_REFERENCE = Path("assets/maps/b1-map12-room-semantics.json")
DEFAULT_SCENE_TOPDOWN = Path(
    "output/b1-map12/scene-gaussian-topdown-crop-z1p8/scene_gaussian_topdown.json"
)
DEFAULT_SCENE_TOPDOWN_DIAGNOSTIC = Path(
    "output/b1-map12/scene-topdown-label-overlay/scene_topdown_diagnostic.json"
)
DEFAULT_ALIGNMENT_ARTIFACT = Path("output/b1-map12/alignment/alignment_residuals.json")
TEMPLATE_PATH = Path(__file__).with_name("b1_map12_label_tool_template.html")


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Render a standalone B1 / Map 12 source-map label editor."
    )
    parser.add_argument("--map-bundle", type=Path, default=DEFAULT_MAP_BUNDLE)
    parser.add_argument("--semantics", type=Path)
    parser.add_argument("--scene-root", type=Path, default=DEFAULT_SCENE_ROOT)
    parser.add_argument(
        "--include-gaussian-scene",
        action="store_true",
        help="Include scene/Gaussian evidence in the packet for review-only comparison.",
    )
    parser.add_argument(
        "--seed-review-shapes-from-scene-bounds",
        action="store_true",
        help=(
            "Seed draft editable labels from Digital Twin object aggregate bounds. "
            "Requires verified Map12->scene alignment and keeps exports candidate/draft."
        ),
    )
    parser.add_argument(
        "--room-label-reference",
        type=Path,
        default=DEFAULT_ROOM_LABEL_REFERENCE,
        help="Digital Twin room label reference used only for review seed display names.",
    )
    parser.add_argument(
        "--scene-topdown-render",
        type=Path,
        default=DEFAULT_SCENE_TOPDOWN,
        help="Gaussian top-down render packet used for the review reference canvas.",
    )
    parser.add_argument(
        "--scene-topdown-diagnostic",
        type=Path,
        default=DEFAULT_SCENE_TOPDOWN_DIAGNOSTIC,
        help="Validated scene top-down diagnostic carrying object aggregate bounds.",
    )
    parser.add_argument(
        "--alignment-artifact",
        type=Path,
        default=DEFAULT_ALIGNMENT_ARTIFACT,
        help="Verified Map12->Digital Twin alignment artifact used to seed draft labels.",
    )
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    try:
        artifacts = write_label_tool_artifacts(
            map_bundle=args.map_bundle,
            semantics_path=args.semantics,
            scene_root=args.scene_root,
            include_gaussian_scene=args.include_gaussian_scene,
            seed_review_shapes_from_scene_bounds=args.seed_review_shapes_from_scene_bounds,
            room_label_reference_path=args.room_label_reference,
            scene_topdown_render_path=args.scene_topdown_render,
            scene_topdown_diagnostic_path=args.scene_topdown_diagnostic,
            alignment_artifact_path=args.alignment_artifact,
            output_dir=args.output_dir,
        )
    except ValueError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    payload = {
        "schema": LABEL_TOOL_PACKET_SCHEMA,
        "shape_count": artifacts["shape_count"],
        "output": str(artifacts["html_path"]),
        "packet": str(artifacts["packet_path"]),
    }
    print(json.dumps(payload, sort_keys=True))
    return 0


def write_label_tool_artifacts(
    *,
    map_bundle: Path,
    semantics_path: Path | None = None,
    scene_root: Path = DEFAULT_SCENE_ROOT,
    include_gaussian_scene: bool = False,
    seed_review_shapes_from_scene_bounds: bool = False,
    room_label_reference_path: Path = DEFAULT_ROOM_LABEL_REFERENCE,
    scene_topdown_render_path: Path = DEFAULT_SCENE_TOPDOWN,
    scene_topdown_diagnostic_path: Path = DEFAULT_SCENE_TOPDOWN_DIAGNOSTIC,
    alignment_artifact_path: Path = DEFAULT_ALIGNMENT_ARTIFACT,
    output_dir: Path,
) -> dict[str, Any]:
    packet = build_label_tool_packet(
        map_bundle=map_bundle,
        semantics_path=semantics_path,
        scene_root=scene_root,
        include_gaussian_scene=include_gaussian_scene,
        seed_review_shapes_from_scene_bounds=seed_review_shapes_from_scene_bounds,
        room_label_reference_path=room_label_reference_path,
        scene_topdown_render_path=scene_topdown_render_path,
        scene_topdown_diagnostic_path=scene_topdown_diagnostic_path,
        alignment_artifact_path=alignment_artifact_path,
    )
    image_url = image_data_url(Path(packet["source_image"]))
    scene_reference_url = scene_reference_image_data_url(packet)
    output_dir.mkdir(parents=True, exist_ok=True)
    materialize_scene_evidence_artifacts(packet, output_dir=output_dir)
    packet_path = output_dir / "label_tool_packet.json"
    html_path = output_dir / "label_tool.html"
    packet_path.write_text(json.dumps(packet, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    html_path.write_text(
        render_label_tool_html(
            packet,
            image_data_url_value=image_url,
            scene_reference_data_url_value=scene_reference_url,
        ),
        encoding="utf-8",
    )
    return {
        "html_path": html_path,
        "packet_path": packet_path,
        "shape_count": len(packet["shapes"]),
    }


def build_label_tool_packet(
    *,
    map_bundle: Path,
    semantics_path: Path | None = None,
    scene_root: Path = DEFAULT_SCENE_ROOT,
    include_gaussian_scene: bool = False,
    seed_review_shapes_from_scene_bounds: bool = False,
    room_label_reference_path: Path = DEFAULT_ROOM_LABEL_REFERENCE,
    scene_topdown_render_path: Path = DEFAULT_SCENE_TOPDOWN,
    scene_topdown_diagnostic_path: Path = DEFAULT_SCENE_TOPDOWN_DIAGNOSTIC,
    alignment_artifact_path: Path = DEFAULT_ALIGNMENT_ARTIFACT,
) -> dict[str, Any]:
    map_bundle = Path(map_bundle)
    map_yaml_path = map_bundle / "map.yaml"
    if not map_yaml_path.is_file():
        map_yaml_path = map_bundle / "nav2.yaml"
    map_yaml = parse_map_yaml(map_yaml_path.read_text(encoding="utf-8"))
    image_path = map_bundle / str(map_yaml.get("image") or "map.pgm")
    with Image.open(image_path) as image:
        width_px, height_px = image.size
    transform = SourceMapTransform(
        width_px=width_px,
        height_px=height_px,
        resolution_m=float(map_yaml.get("resolution") or 0.05),
        origin_x=float(_origin(map_yaml)[0]),
        origin_y=float(_origin(map_yaml)[1]),
        origin_yaw_rad=float(_origin(map_yaml)[2]),
    )
    explicit_semantics_path = semantics_path is not None
    semantics_path = semantics_path or map_bundle / "semantics.json"
    semantics = load_semantics_or_empty(
        semantics_path,
        source_json_path=map_bundle / "source.json",
        allow_missing=not explicit_semantics_path,
    )
    frame_id = source_map_frame_id(semantics)
    shapes = seed_shapes_from_semantics(semantics, transform=transform, frame_id=frame_id)
    review_seed_policy: dict[str, Any] = {
        "enabled": False,
        "seed_count": 0,
        "source": "",
        "note": (
            "No Digital Twin object aggregate bbox review seeds were requested. "
            "The tool starts only from current source-map semantics."
        ),
    }
    scene_reference: dict[str, Any] | None = None
    if seed_review_shapes_from_scene_bounds:
        seed_packet = scene_bounds_review_seed_packet(
            scene_topdown_diagnostic_path=scene_topdown_diagnostic_path,
            alignment_artifact_path=alignment_artifact_path,
            room_label_reference_path=room_label_reference_path,
            scene_topdown_render_path=scene_topdown_render_path,
            transform=transform,
            frame_id=frame_id,
        )
        shapes.extend(seed_packet["shapes"])
        review_seed_policy = seed_packet["review_shape_seed_policy"]
        scene_reference = seed_packet["scene_reference"]
    attach_room_geometry_conflicts(shapes)
    source_map_layers = source_map_layers_from_semantics(
        semantics,
        transform=transform,
        frame_id=frame_id,
    )
    navigation_memory_layer = navigation_memory_layer_from_path(
        map_bundle.parent / "navigation_memory.json",
        transform=transform,
        frame_id=frame_id,
    )
    packet = {
        "schema": LABEL_TOOL_PACKET_SCHEMA,
        "draft_manifest_schema": LABEL_DRAFT_MANIFEST_SCHEMA,
        "map_bundle": str(map_bundle),
        "scene_root": str(scene_root),
        "source_semantics": str(semantics_path),
        "source_image": str(image_path),
        "source_map_frame_id": frame_id,
        "source_map_frame_policy": "raw_source_map_frame_no_rectified_display_frame",
        "draft_policy": {
            "review_status": "draft",
            "export_alignment_status": ALIGNMENT_STATUS_CANDIDATE,
            "verified_status_allowed": False,
            "source_map_mutated": False,
        },
        "map": {
            "image_width_px": transform.width_px,
            "image_height_px": transform.height_px,
            "resolution_m": transform.resolution_m,
            "origin": {
                "x": transform.origin_x,
                "y": transform.origin_y,
                "yaw": transform.origin_yaw_rad,
            },
            "pixel_frame": "image_top_left_col_row",
            "world_frame": frame_id,
            "world_to_pixel": "px=(x-origin_x)/resolution; py=height-1-(y-origin_y)/resolution",
            "pixel_to_world": "x=origin_x+px*resolution; y=origin_y+(height-1-py)*resolution",
        },
        "shape_defaults": {
            "polygon_role": POLYGON_ROLE_NAVIGATION_AREA,
            "geometry_source": GEOMETRY_SOURCE_OPERATOR_NAVIGATION_ZONE,
            "alignment_status": ALIGNMENT_STATUS_CANDIDATE,
            "review_status": "draft",
        },
        "review_shape_seed_policy": review_seed_policy,
        "valid_polygon_roles": sorted(POLYGON_ROLES),
        "valid_geometry_sources": sorted(POLYGON_GEOMETRY_SOURCES),
        "shapes": shapes,
        "source_map_layers": source_map_layers,
        "navigation_memory_layer": navigation_memory_layer,
        "initial_draft_manifest": draft_manifest_from_shapes(
            shapes,
            source_packet={
                "source_map_frame_id": frame_id,
                "map_bundle": str(map_bundle),
                "scene_root": str(scene_root),
                "source_semantics": str(semantics_path),
                "source_image": str(image_path),
            },
        ),
    }
    if scene_reference:
        packet["scene_reference"] = scene_reference
    if include_gaussian_scene:
        packet["scene_evidence"] = scene_evidence_from_scene_root(
            scene_root,
            map_bundle=map_bundle,
            fallback_semantics=semantics,
        )
    return packet


def load_semantics_or_empty(
    semantics_path: Path,
    *,
    source_json_path: Path,
    allow_missing: bool = True,
) -> dict[str, Any]:
    path = Path(semantics_path)
    if path.is_file():
        return _read_label_tool_json_object(path, "semantics")
    if not allow_missing:
        raise ValueError(f"semantics missing: {path}")
    if not source_json_path.is_file():
        raise ValueError(f"map source metadata missing: {source_json_path}")
    source = _read_label_tool_json_object(source_json_path, "map source metadata")
    return {
        "schema": "robot_map12_empty_label_tool_semantics_v1",
        "environment_id": str(source.get("alias") or "robot_map_12"),
        "frame_ids": {"map": "map"},
        "display_frame": None,
        "rooms": [],
        "fixtures": [],
        "inspection_waypoints": [],
        "driveable_ways": [],
        "provenance": {
            "source": "agibot_vendor_map_without_authored_semantics",
            "contains_private_scoring_truth": False,
            "contains_runtime_observations": False,
        },
    }


def _read_label_tool_json_object(path: Path, label: str) -> dict[str, Any]:
    try:
        return read_json_object(path, label=label)
    except ValueError as exc:
        message = str(exc)
        if "source must contain valid JSON object" in message:
            raise ValueError(f"{label} must contain valid JSON object: {path}") from exc
        if "source must contain a JSON object" in message:
            raise ValueError(f"{label} must contain a JSON object: {path}") from exc
        raise


def materialize_scene_evidence_artifacts(packet: dict[str, Any], *, output_dir: Path) -> None:
    repo_root = Path(__file__).resolve().parents[2]
    copied: dict[str, dict[str, Any]] = {}
    rooms = (packet.get("scene_evidence") or {}).get("rooms") or {}
    if not isinstance(rooms, dict):
        return
    for room in rooms.values():
        if not isinstance(room, dict):
            continue
        links = []
        for source in room.get("evidence_artifacts") or []:
            source_text = str(source)
            if source_text in copied:
                links.append(dict(copied[source_text]))
                continue
            link = {
                "source_path": source_text,
                "available": False,
                "href": "",
            }
            source_path = _repo_artifact_path(source_text, repo_root=repo_root)
            if source_path and source_path.is_file():
                evidence_dir = output_dir / "evidence"
                evidence_dir.mkdir(parents=True, exist_ok=True)
                digest = hashlib.sha256(source_text.encode("utf-8")).hexdigest()[:12]
                destination = evidence_dir / f"{digest}_{source_path.name}"
                shutil.copy2(source_path, destination)
                link = {
                    **link,
                    "available": True,
                    "href": str(Path("evidence") / destination.name),
                }
            copied[source_text] = dict(link)
            links.append(link)
        room["evidence_artifact_links"] = links


if __name__ == "__main__":
    raise SystemExit(main())
