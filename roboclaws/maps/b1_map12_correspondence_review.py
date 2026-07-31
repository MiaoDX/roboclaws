#!/usr/bin/env python3
from __future__ import annotations

import argparse
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
from roboclaws.maps.b1_alignment_contract import (
    anchor_role,
    anchor_uses_known_poor_seed,
    valid_xy,
    valid_xyz,
    validate_correspondence_manifest,
)
from roboclaws.maps.b1_map12_correspondence_report import render_review_report
from roboclaws.maps.b1_scene_topdown_contract import TOPDOWN_RENDER_SCHEMA
from roboclaws.maps.bundle_validation import parse_map_yaml

REVIEW_PACKET_SCHEMA = "b1_map12_correspondence_review_packet_v1"
SCENE_TOPDOWN_PICK_SOURCE = "rendered_gaussian_scene_topdown_ray_plane_pick"


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Render a B1 / Map 12 correspondence anchor review packet."
    )
    parser.add_argument("--correspondences", type=Path, required=True)
    parser.add_argument("--map-bundle", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument(
        "--scene-topdown-render",
        type=Path,
        required=True,
        help=(
            "Required scene_gaussian_topdown.json from render_b1_scene_gaussian_topdown.py. "
            "Label-inventory diagnostics are rejected."
        ),
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    try:
        manifest = read_json_object(args.correspondences, label="correspondence manifest")
        packet = build_review_packet(
            manifest,
            map_bundle=args.map_bundle,
            correspondences_path=args.correspondences,
            scene_topdown_render_path=args.scene_topdown_render,
            output_dir=args.output_dir,
        )
    except (FileNotFoundError, ValueError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    args.output_dir.mkdir(parents=True, exist_ok=True)
    packet_path = args.output_dir / "correspondence_review_packet.json"
    report_path = args.output_dir / "correspondence_review.html"
    packet_path.write_text(json.dumps(packet, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    report_path.write_text(
        render_review_report(
            packet,
            output_dir=args.output_dir,
            packet_path=packet_path,
            correspondences_path=args.correspondences,
        ),
        encoding="utf-8",
    )
    print(
        json.dumps(
            {
                "schema": REVIEW_PACKET_SCHEMA,
                "status": packet["review_status"],
                "accepted_anchor_count": packet["accepted_anchor_count"],
                "output": str(report_path),
            },
            sort_keys=True,
        )
    )
    return 0


def build_review_packet(
    manifest: dict[str, Any],
    *,
    map_bundle: Path,
    scene_topdown_render_path: Path,
    correspondences_path: Path | None = None,
    output_dir: Path | None = None,
) -> dict[str, Any]:
    anchors = [item for item in manifest.get("anchors") or [] if isinstance(item, dict)]
    rows = [review_anchor_row(anchor, index=index) for index, anchor in enumerate(anchors, start=1)]
    accepted = [row for row in rows if row["review_status"] == "accepted"]
    ready = [row for row in accepted if row["fit_ready"]]
    validation_errors = validate_correspondence_manifest(manifest)
    source_map = source_map_review_context(Path(map_bundle), output_dir=output_dir)
    scene_topdown = scene_topdown_render_context(scene_topdown_render_path, output_dir=output_dir)
    review_status = (
        "ready_for_fit" if len(ready) >= 6 and not validation_errors else "review_pending"
    )
    if validation_errors:
        review_status = "manifest_needs_fix"
    return {
        "schema": REVIEW_PACKET_SCHEMA,
        "source_manifest_schema": manifest.get("schema"),
        "correspondences_artifact": str(correspondences_path) if correspondences_path else "",
        "map_bundle": str(map_bundle),
        "map_preview": source_map.get("image") or "",
        "source_map": source_map,
        "scene_topdown": scene_topdown,
        "source_map_frame": str(manifest.get("source_map_frame") or ""),
        "target_scene_frame": str(manifest.get("target_scene_frame") or ""),
        "bbox_seed_policy": str(manifest.get("bbox_seed_policy") or ""),
        "known_poor_seed_rule": (
            "The bbox-fit overlay may seed coarse visual search only. It must not prefill "
            "accepted scene coordinates or count as residual evidence."
        ),
        "review_status": review_status,
        "anchor_count": len(rows),
        "accepted_anchor_count": len(accepted),
        "fit_ready_anchor_count": len(ready),
        "required_fit_ready_anchor_count": 6,
        "manifest_validation": {
            "status": "passed" if not validation_errors else "failed",
            "errors": validation_errors,
        },
        "anchors": rows,
        "export_manifest_template": export_manifest_template(manifest),
        "next_action": next_action(review_status, rows),
    }


def review_anchor_row(anchor: dict[str, Any], *, index: int) -> dict[str, Any]:
    review_status = str(anchor.get("review_status") or "proposed")
    has_role = bool(anchor.get("anchor_role"))
    has_map_pick = valid_xy(anchor.get("map_xy"))
    has_scene_pick = valid_xyz(anchor.get("scene_xyz"))
    uses_seed = anchor_uses_known_poor_seed(anchor)
    fit_ready = (
        review_status == "accepted"
        and has_role
        and has_map_pick
        and has_scene_pick
        and not uses_seed
    )
    return {
        "index": index,
        "anchor_id": str(anchor.get("anchor_id") or f"anchor_{index:03d}"),
        "anchor_type": str(anchor.get("anchor_type") or ""),
        "anchor_role": anchor_role(anchor),
        "navigation_area_id": str(anchor.get("navigation_area_id") or ""),
        "asset_partition_id": str(anchor.get("asset_partition_id") or ""),
        "review_status": review_status,
        "has_role": has_role,
        "has_map_pick": has_map_pick,
        "has_scene_pick": has_scene_pick,
        "uses_known_poor_bbox_seed": uses_seed,
        "fit_ready": fit_ready,
        "map_xy": anchor.get("map_xy"),
        "scene_xyz": anchor.get("scene_xyz"),
        "confidence": anchor.get("confidence"),
        "evidence": anchor.get("evidence") if isinstance(anchor.get("evidence"), dict) else {},
        "review_action": review_action(
            review_status=review_status,
            has_role=has_role,
            has_map_pick=has_map_pick,
            has_scene_pick=has_scene_pick,
            uses_seed=uses_seed,
        ),
    }


def review_action(
    *,
    review_status: str,
    has_role: bool,
    has_map_pick: bool,
    has_scene_pick: bool,
    uses_seed: bool,
) -> str:
    if uses_seed:
        return "replace seed-derived coordinates with explicit operator map and scene picks"
    if review_status != "accepted":
        return "pick explicit map_xy and scene_xyz, then mark accepted after operator review"
    if not has_role:
        return "accepted anchors require anchor_role=alignment or anchor_role=semantic"
    if not has_map_pick or not has_scene_pick:
        return "accepted anchors require both map_xy and scene_xyz before fitting"
    return "ready_for_fit"


def next_action(review_status: str, rows: list[dict[str, Any]]) -> str:
    if review_status == "manifest_needs_fix":
        return "Fix manifest validation errors before anchor fitting."
    ready_count = sum(1 for row in rows if row["fit_ready"])
    if ready_count < 6:
        return (
            "Review anchor candidates and produce at least six accepted anchors with "
            "explicit map and scene picks."
        )
    return "Run the residual fitter and inspect global/area pass-fail status."


def source_map_review_context(
    map_bundle: Path, *, output_dir: Path | None = None
) -> dict[str, Any]:
    map_yaml_path = map_bundle / "map.yaml"
    if not map_yaml_path.is_file():
        map_yaml_path = map_bundle / "nav2.yaml"
    source_image_path = map_bundle / "map.pgm"
    transform: dict[str, Any] = {}
    if map_yaml_path.is_file():
        map_yaml = parse_map_yaml(map_yaml_path.read_text(encoding="utf-8"))
        source_image_path = map_bundle / str(map_yaml.get("image") or "map.pgm")
        origin = map_yaml.get("origin") if isinstance(map_yaml.get("origin"), list) else []
        transform = {
            "resolution_m": float(map_yaml.get("resolution") or 0.05),
            "origin_x": float(origin[0]) if len(origin) >= 1 else 0.0,
            "origin_y": float(origin[1]) if len(origin) >= 2 else 0.0,
            "origin_yaw_rad": float(origin[2]) if len(origin) >= 3 else 0.0,
        }
    display_image_path = browser_ready_map_image(source_image_path, output_dir=output_dir)
    size = image_size(source_image_path)
    return {
        "image": str(display_image_path) if display_image_path.is_file() else "",
        "image_role": "browser_ready_picker_preview",
        "source_image": str(source_image_path) if source_image_path.is_file() else "",
        "map_yaml": str(map_yaml_path) if map_yaml_path.is_file() else "",
        "width_px": size[0],
        "height_px": size[1],
        "pixel_to_map_xy": transform,
    }


def browser_ready_map_image(source_image_path: Path, *, output_dir: Path | None) -> Path:
    if not source_image_path.is_file() or output_dir is None:
        return source_image_path
    output_path = Path(output_dir) / "map12_source_map.png"
    output_path.parent.mkdir(parents=True, exist_ok=True)
    try:
        with Image.open(source_image_path) as image:
            image.convert("L").save(output_path)
    except Exception:
        return source_image_path
    return output_path


def scene_topdown_render_context(
    scene_topdown_render_path: Path, *, output_dir: Path | None = None
) -> dict[str, Any]:
    packet = read_json_object(Path(scene_topdown_render_path), label="scene top-down render")
    if packet.get("schema") != TOPDOWN_RENDER_SCHEMA:
        raise ValueError(
            f"scene top-down render must use schema {TOPDOWN_RENDER_SCHEMA}; "
            f"got {packet.get('schema')!r}"
        )
    geometry_status = str(packet.get("geometry_status") or "")
    if geometry_status != "rendered_gaussian_scene_topdown":
        raise ValueError(
            "scene top-down render must have geometry_status=rendered_gaussian_scene_topdown; "
            f"got {geometry_status!r}"
        )
    source_image_path = Path(str(packet.get("topdown_image") or ""))
    if not source_image_path.is_file():
        raise FileNotFoundError(f"scene top-down render image missing: {source_image_path}")
    pixel_to_scene = packet.get("pixel_to_scene_xyz")
    if not isinstance(pixel_to_scene, dict):
        raise ValueError("scene top-down render missing pixel_to_scene_xyz")
    if pixel_to_scene.get("source") != SCENE_TOPDOWN_PICK_SOURCE:
        raise ValueError(
            "scene top-down render must map pixels with "
            f"{SCENE_TOPDOWN_PICK_SOURCE}; got {pixel_to_scene.get('source')!r}"
        )
    image_path = local_review_image(source_image_path, output_dir=output_dir)
    size = image_size(source_image_path)
    return {
        "status": "available",
        "path": str(scene_topdown_render_path),
        "image": str(image_path) if image_path.is_file() else "",
        "source_image": str(source_image_path),
        "width_px": size[0],
        "height_px": size[1],
        "geometry_status": geometry_status,
        "display_role": "rendered_gaussian_scene_topdown",
        "up_axis": str(packet.get("up_axis") or "z"),
        "horizontal_axes": list(packet.get("horizontal_axes") or ["x", "y"]),
        "scene_xy_bounds": packet.get("scene_xy_bounds") if isinstance(packet, dict) else {},
        "camera": packet.get("camera") if isinstance(packet.get("camera"), dict) else {},
        "pixel_to_scene_xyz": dict(pixel_to_scene),
    }


def local_review_image(source_image_path: Path, *, output_dir: Path | None) -> Path:
    if not source_image_path.is_file() or output_dir is None:
        return source_image_path
    output_path = Path(output_dir) / source_image_path.name
    if source_image_path.resolve() == output_path.resolve():
        return output_path
    output_path.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source_image_path, output_path)
    return output_path


def export_manifest_template(manifest: dict[str, Any]) -> dict[str, Any]:
    payload = {
        "schema": manifest.get("schema"),
        "source_map_frame": manifest.get("source_map_frame"),
        "target_scene_frame": manifest.get("target_scene_frame"),
        "bbox_seed_policy": manifest.get("bbox_seed_policy"),
        "scene_projection_policy": manifest.get("scene_projection_policy"),
        "anchors": [],
    }
    if isinstance(manifest.get("review_lifecycle"), dict):
        payload["review_lifecycle"] = manifest["review_lifecycle"]
    if isinstance(manifest.get("notes"), list):
        payload["notes"] = manifest["notes"]
    return payload


def image_size(path: Path) -> tuple[int, int]:
    try:
        with Image.open(path) as image:
            return int(image.width), int(image.height)
    except Exception:
        return 0, 0


if __name__ == "__main__":
    raise SystemExit(main())
