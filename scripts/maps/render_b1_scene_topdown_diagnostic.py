#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import math
import re
import sys
from collections import Counter
from pathlib import Path
from typing import Any

from PIL import Image, ImageDraw

if __package__ in {None, ""}:
    repo_root = Path(__file__).resolve().parents[2]
    if str(repo_root) not in sys.path:
        sys.path.insert(0, str(repo_root))

from roboclaws.core.json_sources import read_json_object
from roboclaws.maps.b1_alignment import (
    SCENE_PROJECTION_HORIZONTAL_AXES,
    SCENE_PROJECTION_UP_AXIS,
)
from scripts.maps.render_b1_scene_gaussian_topdown import (
    TOPDOWN_RENDER_SCHEMA,
    validate_topdown_render_packet,
)

DIAGNOSTIC_SCHEMA = "b1_scene_topdown_diagnostic_v1"
DEFAULT_SCENE_ROOT = Path("data/robot-data-lab/scene-engine/data/2rd_floor_seperated")
_PARTITION_RE = re.compile(r'over\s+"([^"]+)"')
_INSTANCE_SUFFIX_RE = re.compile(r"(?:_\d+)+$")
_PARTITION_COLORS = [
    (69, 123, 157),
    (42, 157, 143),
    (233, 196, 106),
    (244, 162, 97),
    (231, 111, 81),
    (128, 90, 213),
    (95, 111, 82),
]


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Render an honest 2rd_floor_seperated scene topdown diagnostic."
    )
    parser.add_argument("--scene-root", type=Path, default=DEFAULT_SCENE_ROOT)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--width", type=_positive_int_arg, default=960)
    parser.add_argument("--height", type=_positive_int_arg, default=640)
    parser.add_argument(
        "--scene-topdown-render",
        type=Path,
        help=(
            "Optional rendered Gaussian topdown packet. When provided, scene USD room/object "
            "bounds are drawn onto that image. Missing or malformed inputs fail loudly."
        ),
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    packet = build_scene_topdown_diagnostic(
        scene_root=args.scene_root,
        output_dir=args.output_dir,
        width=int(args.width),
        height=int(args.height),
        scene_topdown_render=args.scene_topdown_render,
    )
    errors = validate_scene_topdown_diagnostic(packet)
    packet["validation"] = {"status": "passed" if not errors else "failed", "errors": errors}
    args.output_dir.mkdir(parents=True, exist_ok=True)
    packet_path = args.output_dir / "scene_topdown_diagnostic.json"
    html_path = args.output_dir / "scene_topdown_diagnostic.html"
    packet_path.write_text(json.dumps(packet, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    html_path.write_text(render_diagnostic_html(packet, packet_path=packet_path), encoding="utf-8")
    print(
        json.dumps(
            {
                "schema": DIAGNOSTIC_SCHEMA,
                "status": packet["validation"]["status"],
                "geometry_status": packet.get("geometry_status"),
                "partition_count": packet.get("partition_count"),
                "topdown": packet.get("topdown_image"),
                "packet": str(packet_path),
                "report": str(html_path),
                "errors": errors,
            },
            sort_keys=True,
        )
    )
    return 0 if not errors else 2


def build_scene_topdown_diagnostic(
    *,
    scene_root: Path,
    output_dir: Path,
    width: int = 960,
    height: int = 640,
    scene_topdown_render: Path | None = None,
) -> dict[str, Any]:
    scene_root = Path(scene_root)
    output_dir = Path(output_dir)
    if not scene_root.is_dir():
        raise FileNotFoundError(f"scene root does not exist: {scene_root}")
    output_dir.mkdir(parents=True, exist_ok=True)
    partitions = scene_partitions(scene_root)
    topdown_packet = None
    object_bounds: list[dict[str, Any]] = []
    render_stats: dict[str, Any] = {}
    source_topdown_image = ""
    if scene_topdown_render is not None:
        topdown_packet = load_scene_topdown_render(scene_topdown_render)
        object_bounds = scene_object_bounds_from_usd(scene_root / "storey_1" / "scene.usd")
        partitions = attach_scene_bounds(partitions, object_bounds)
        topdown_path = output_dir / "scene_topdown_label_overlay.png"
        render_stats = render_scene_label_overlay_topdown(
            topdown_packet,
            partitions,
            object_bounds,
            topdown_path,
        )
        geometry_status = "rendered_gaussian_topdown_with_scene_usd_bounds_overlay"
        geometry_backend = "scene_usd_world_bounds_on_gaussian_topdown"
        geometry_honesty = (
            "This PNG draws scene USD top-level object bounds, partition bounds, and labels "
            "onto the rendered Gaussian topdown. It is a scene self-check in the B1 scene "
            "frame only. It does not project labels into Map12 and cannot verify map-scene "
            "alignment by itself."
        )
        source_topdown_image = str(topdown_packet["topdown_image"])
    else:
        topdown_path = output_dir / "scene_topdown_diagnostic.png"
        render_label_inventory_topdown(partitions, topdown_path, width=width, height=height)
        geometry_status = (
            "label_inventory_only" if partitions else "unavailable_no_scene_partitions"
        )
        geometry_backend = "scene_partition_label_inventory"
        geometry_honesty = (
            "No metric USD/mesh bounds were extracted. The PNG is a review inventory "
            "layout showing partition identities and object label counts. It is not a "
            "Gaussian asset topdown, not a metric scene projection, and cannot verify "
            "map-scene alignment by itself."
        )
    packet = {
        "schema": DIAGNOSTIC_SCHEMA,
        "scene_root": str(scene_root),
        "up_axis": SCENE_PROJECTION_UP_AXIS,
        "horizontal_axes": SCENE_PROJECTION_HORIZONTAL_AXES,
        "scene_projection_policy": {
            "up_axis": SCENE_PROJECTION_UP_AXIS,
            "horizontal_axes": SCENE_PROJECTION_HORIZONTAL_AXES,
            "source": "2rd_floor_seperated_scene_topdown_policy",
        },
        "geometry_status": geometry_status,
        "geometry_backend": geometry_backend,
        "geometry_honesty": geometry_honesty,
        "source_topdown_render": str(scene_topdown_render or ""),
        "source_topdown_image": source_topdown_image,
        "topdown_image": str(topdown_path),
        "alignment_scope": "scene_self_check_only",
        "map_projection_status": "not_projected_to_map12",
        "partition_count": len(partitions),
        "partitions": partitions,
        "object_bound_count": len(object_bounds),
        "overlay_render_stats": render_stats,
        "high_signal_object_labels": high_signal_object_labels(partitions),
        "self_consistency": scene_self_consistency(partitions),
    }
    return packet


def scene_partitions(scene_root: Path) -> list[dict[str, Any]]:
    partitions = []
    for index, partition_root in enumerate(
        sorted(path for path in scene_root.iterdir() if path.is_dir()),
        start=1,
    ):
        if partition_root.name == "storey_1":
            continue
        scene_usd = partition_root / "scene.usd"
        gaussian_layer = partition_root / "scene_gs.usda"
        if not scene_usd.is_file() and not gaussian_layer.is_file():
            continue
        object_counts = object_counts_from_gaussian_layer(gaussian_layer)
        if not object_counts:
            object_counts = object_counts_from_materials(
                partition_root / "configuration" / "materials"
            )
        partitions.append(
            {
                "partition_id": partition_root.name,
                "display_order": index,
                "scene_usd": file_inventory(scene_usd),
                "gaussian_layer": file_inventory(gaussian_layer),
                "config_yaml": file_inventory(partition_root / "config.yaml"),
                "usdz": file_inventory(partition_root / "xm_large_scene.usdz"),
                "object_label_count": int(sum(object_counts.values())),
                "unique_object_label_count": int(len(object_counts)),
                "object_name_counts": dict(object_counts.most_common()),
                "high_signal_object_labels": [
                    {"label": name, "count": count} for name, count in object_counts.most_common(12)
                ],
                "scene_frame_bounds": {"status": "not_extracted"},
                "geometry_status": "label_inventory_only",
            }
        )
    return partitions


def load_scene_topdown_render(path: Path) -> dict[str, Any]:
    packet = read_json_object(path, label="scene top-down render")
    if packet.get("schema") != TOPDOWN_RENDER_SCHEMA:
        raise ValueError(
            f"scene top-down render must use schema {TOPDOWN_RENDER_SCHEMA}; "
            f"got {packet.get('schema')!r}"
        )
    errors = validate_topdown_render_packet(packet)
    if errors:
        raise ValueError("invalid scene top-down render packet: " + "; ".join(errors))
    camera = packet.get("camera") if isinstance(packet.get("camera"), dict) else {}
    if not camera:
        raise ValueError("scene top-down render missing camera")
    return packet


def scene_object_bounds_from_usd(scene_usd: Path) -> list[dict[str, Any]]:
    if not scene_usd.is_file():
        raise FileNotFoundError(f"scene USD missing for bounds overlay: {scene_usd}")
    try:
        from pxr import Usd, UsdGeom
    except ModuleNotFoundError as exc:
        raise RuntimeError(
            "scene USD bounds overlay requires pxr/OpenUSD; run with "
            ".venv-isaaclab/bin/python or install a declared USD runtime"
        ) from exc

    stage = Usd.Stage.Open(str(scene_usd))
    if stage is None:
        raise ValueError(f"failed to open scene USD: {scene_usd}")
    root = stage.GetDefaultPrim()
    if not root:
        raise ValueError(f"scene USD has no default prim: {scene_usd}")
    cache = UsdGeom.BBoxCache(
        Usd.TimeCode.Default(),
        [UsdGeom.Tokens.default_, UsdGeom.Tokens.render, UsdGeom.Tokens.proxy],
        useExtentsHint=True,
    )
    bounds = []
    for prim in root.GetChildren():
        prim_name = prim.GetName()
        if "__" not in prim_name:
            continue
        partition_id, raw_object = prim_name.split("__", 1)
        object_label = normalize_object_label(raw_object)
        box = cache.ComputeWorldBound(prim).ComputeAlignedBox()
        if box.IsEmpty():
            continue
        min_point = box.GetMin()
        max_point = box.GetMax()
        values = [
            float(min_point[0]),
            float(min_point[1]),
            float(min_point[2]),
            float(max_point[0]),
            float(max_point[1]),
            float(max_point[2]),
        ]
        if not all(math.isfinite(value) for value in values):
            continue
        min_x, min_y, min_z, max_x, max_y, max_z = values
        bounds.append(
            {
                "partition_id": partition_id,
                "object_id": prim_name,
                "object_label": object_label,
                "prim_path": str(prim.GetPath()),
                "bounds": {
                    "min_x": round(min_x, 6),
                    "min_y": round(min_y, 6),
                    "min_z": round(min_z, 6),
                    "max_x": round(max_x, 6),
                    "max_y": round(max_y, 6),
                    "max_z": round(max_z, 6),
                },
                "center": {
                    "x": round((min_x + max_x) / 2.0, 6),
                    "y": round((min_y + max_y) / 2.0, 6),
                    "z": round((min_z + max_z) / 2.0, 6),
                },
            }
        )
    if not bounds:
        raise ValueError(f"no top-level scene object bounds extracted from {scene_usd}")
    return bounds


def attach_scene_bounds(
    partitions: list[dict[str, Any]],
    object_bounds: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    bounds_by_partition: dict[str, list[dict[str, Any]]] = {}
    for item in object_bounds:
        bounds_by_partition.setdefault(str(item.get("partition_id") or ""), []).append(item)
    output = []
    for partition in partitions:
        row = dict(partition)
        items = bounds_by_partition.get(str(row.get("partition_id") or ""), [])
        if items:
            row["scene_frame_bounds"] = aggregate_bounds(items)
            row["geometry_status"] = "scene_usd_world_bounds"
            row["object_bounds_count"] = len(items)
        else:
            row["scene_frame_bounds"] = {"status": "missing_scene_usd_bounds"}
            row["geometry_status"] = "missing_scene_usd_bounds"
            row["object_bounds_count"] = 0
        output.append(row)
    return output


def aggregate_bounds(items: list[dict[str, Any]]) -> dict[str, Any]:
    min_x = min(float(item["bounds"]["min_x"]) for item in items)
    min_y = min(float(item["bounds"]["min_y"]) for item in items)
    min_z = min(float(item["bounds"]["min_z"]) for item in items)
    max_x = max(float(item["bounds"]["max_x"]) for item in items)
    max_y = max(float(item["bounds"]["max_y"]) for item in items)
    max_z = max(float(item["bounds"]["max_z"]) for item in items)
    return {
        "status": "extracted_from_scene_usd_world_bounds",
        "min_x": round(min_x, 6),
        "min_y": round(min_y, 6),
        "min_z": round(min_z, 6),
        "max_x": round(max_x, 6),
        "max_y": round(max_y, 6),
        "max_z": round(max_z, 6),
        "center": {
            "x": round((min_x + max_x) / 2.0, 6),
            "y": round((min_y + max_y) / 2.0, 6),
            "z": round((min_z + max_z) / 2.0, 6),
        },
    }


def object_counts_from_gaussian_layer(path: Path) -> Counter[str]:
    counts: Counter[str] = Counter()
    if not path.is_file():
        return counts
    text = path.read_text(encoding="utf-8", errors="ignore")
    for name in _PARTITION_RE.findall(text):
        if "__" not in name:
            continue
        _partition_id, raw_object = name.split("__", 1)
        object_name = normalize_object_label(raw_object)
        if object_name:
            counts[object_name] += 1
    return counts


def object_counts_from_materials(materials_dir: Path) -> Counter[str]:
    counts: Counter[str] = Counter()
    if not materials_dir.is_dir():
        return counts
    for path in sorted(materials_dir.glob("*_aligned_albedo.png")):
        stem = path.name.removesuffix("_aligned_albedo.png")
        object_name = _INSTANCE_SUFFIX_RE.sub("", stem)
        if object_name:
            counts[object_name] += 1
    return counts


def normalize_object_label(raw_object: str) -> str:
    object_name = _INSTANCE_SUFFIX_RE.sub("", raw_object)
    object_name = re.sub(r"__.*$", "", object_name)
    return object_name


def high_signal_object_labels(partitions: list[dict[str, Any]]) -> list[dict[str, Any]]:
    total: Counter[str] = Counter()
    for partition in partitions:
        total.update(
            {
                str(name): int(count)
                for name, count in (partition.get("object_name_counts") or {}).items()
            }
        )
    return [{"label": name, "count": count} for name, count in total.most_common(20)]


def scene_self_consistency(partitions: list[dict[str, Any]]) -> dict[str, Any]:
    conflicts = []
    for partition in partitions:
        if int(partition.get("object_label_count") or 0) <= 0:
            conflicts.append(f"{partition['partition_id']} has no object labels")
    return {
        "status": "needs_operator_review" if conflicts else "inventory_consistent",
        "conflicts": conflicts,
        "review_note": (
            "This check proves only inventory consistency. Room-label identity still needs "
            "operator review against a rendered or metric topdown when available."
        ),
    }


def render_label_inventory_topdown(
    partitions: list[dict[str, Any]],
    path: Path,
    *,
    width: int,
    height: int,
) -> None:
    image = Image.new("RGB", (width, height), color=(248, 250, 252))
    draw = ImageDraw.Draw(image)
    draw.rectangle((18, 18, width - 18, height - 18), outline=(191, 201, 214), width=2)
    draw.text((34, 30), "2rd_floor_seperated label inventory diagnostic", fill=(23, 32, 42))
    draw.text(
        (34, 54),
        "Not Gaussian topdown. Not metric geometry. Labels only.",
        fill=(85, 99, 114),
    )
    if not partitions:
        draw.text((34, 92), "No scene partitions found.", fill=(130, 40, 40))
        image.save(path)
        return
    columns = min(3, max(1, len(partitions)))
    rows = (len(partitions) + columns - 1) // columns
    pad = 22
    top = 92
    cell_w = max(1, (width - 2 * pad) / columns)
    cell_h = max(1, (height - top - pad) / rows)
    for index, partition in enumerate(partitions):
        row = index // columns
        col = index % columns
        x0 = int(pad + col * cell_w + 8)
        y0 = int(top + row * cell_h + 8)
        x1 = int(pad + (col + 1) * cell_w - 8)
        y1 = int(top + (row + 1) * cell_h - 8)
        color = _PARTITION_COLORS[index % len(_PARTITION_COLORS)]
        draw.rounded_rectangle(
            (x0, y0, x1, y1), radius=6, fill=(255, 255, 255), outline=color, width=3
        )
        draw.text((x0 + 12, y0 + 12), str(partition["partition_id"]), fill=(23, 32, 42))
        label_count = partition["object_label_count"]
        unique_label_count = partition["unique_object_label_count"]
        draw.text(
            (x0 + 12, y0 + 34),
            f"labels: {label_count} / unique: {unique_label_count}",
            fill=(85, 99, 114),
        )
        labels = [
            f"{item['label']} x{item['count']}"
            for item in partition.get("high_signal_object_labels", [])[:5]
        ]
        for label_index, label in enumerate(labels):
            draw.text((x0 + 12, y0 + 60 + label_index * 18), label, fill=(35, 45, 58))
    image.save(path)


def render_scene_label_overlay_topdown(
    topdown_packet: dict[str, Any],
    partitions: list[dict[str, Any]],
    object_bounds: list[dict[str, Any]],
    path: Path,
) -> dict[str, Any]:
    source_image = Path(str(topdown_packet.get("topdown_image") or ""))
    image = Image.open(source_image).convert("RGBA")
    draw = ImageDraw.Draw(image, "RGBA")
    projector = scene_projector_from_topdown_packet(topdown_packet)
    drawn_partitions = 0
    drawn_objects = 0

    partition_colors = {
        str(partition.get("partition_id") or ""): _PARTITION_COLORS[index % len(_PARTITION_COLORS)]
        for index, partition in enumerate(partitions)
    }
    for partition in partitions:
        bounds = partition.get("scene_frame_bounds")
        if (
            not isinstance(bounds, dict)
            or bounds.get("status") != "extracted_from_scene_usd_world_bounds"
        ):
            continue
        polygon = projected_bounds_polygon(bounds, projector)
        if len(polygon) < 3:
            continue
        color = partition_colors.get(str(partition.get("partition_id") or ""), (69, 123, 157))
        fill = color + (34,)
        outline = color + (210,)
        draw.polygon(polygon, fill=fill)
        draw.line(polygon + [polygon[0]], fill=outline, width=3)
        center = projector.project(
            float(bounds["center"]["x"]),
            float(bounds["center"]["y"]),
            z=0.0,
        )
        if center:
            draw_label(
                draw,
                center,
                f"{partition.get('partition_id')} ({partition.get('object_bounds_count')})",
                fill=(20, 24, 28, 255),
                background=color + (220,),
            )
        drawn_partitions += 1

    for item in object_bounds:
        center = item.get("center") if isinstance(item.get("center"), dict) else {}
        point = projector.project(float(center["x"]), float(center["y"]), z=0.0)
        if not point:
            continue
        partition_id = str(item.get("partition_id") or "")
        color = partition_colors.get(partition_id, (69, 123, 157))
        x, y = point
        draw.ellipse(
            (x - 3, y - 3, x + 3, y + 3), fill=color + (235,), outline=(255, 255, 255, 230)
        )
        if should_label_object(str(item.get("object_label") or "")):
            draw.text(
                (x + 5, y - 6), str(item.get("object_label") or "")[:24], fill=(13, 21, 31, 230)
            )
        drawn_objects += 1

    draw_overlay_header(draw, topdown_packet)
    path.parent.mkdir(parents=True, exist_ok=True)
    image.convert("RGB").save(path)
    return {
        "source_image": str(source_image),
        "drawn_partition_count": drawn_partitions,
        "drawn_object_count": drawn_objects,
        "projection": projector.metadata,
        "overlay_note": (
            "Scene USD bounds are projected through the recorded topdown camera with z=0 "
            "for labels. Tall objects may appear shifted relative to their visible top."
        ),
    }


class SceneProjector:
    def __init__(
        self,
        *,
        eye: tuple[float, float, float],
        target: tuple[float, float, float],
        up: tuple[float, float, float],
        vertical_fov_deg: float,
        width: int,
        height: int,
    ) -> None:
        self.eye = eye
        self.forward = normalize((target[0] - eye[0], target[1] - eye[1], target[2] - eye[2]))
        self.right = normalize(cross(self.forward, up))
        if vector_length(self.right) <= 0:
            raise ValueError("topdown camera right vector is degenerate")
        self.camera_up = normalize(cross(self.right, self.forward))
        self.width = int(width)
        self.height = int(height)
        self.focal_y = (self.height / 2.0) / math.tan(math.radians(vertical_fov_deg) / 2.0)
        self.focal_x = self.focal_y
        self.metadata = {
            "model": "recorded_perspective_camera_world_to_pixel",
            "label_z_policy": "project_scene_xy_at_z0",
            "width_px": self.width,
            "height_px": self.height,
            "vertical_fov_deg": vertical_fov_deg,
            "eye": list(eye),
            "target": list(target),
            "up": list(up),
        }

    def project(self, x: float, y: float, *, z: float) -> tuple[float, float] | None:
        rel = (x - self.eye[0], y - self.eye[1], z - self.eye[2])
        cam_x = dot(rel, self.right)
        cam_y = dot(rel, self.camera_up)
        depth = dot(rel, self.forward)
        if depth <= 1e-6:
            return None
        px = self.width / 2.0 + self.focal_x * cam_x / depth
        py = self.height / 2.0 - self.focal_y * cam_y / depth
        if not math.isfinite(px) or not math.isfinite(py):
            return None
        return px, py


def scene_projector_from_topdown_packet(packet: dict[str, Any]) -> SceneProjector:
    camera = packet.get("camera") if isinstance(packet.get("camera"), dict) else {}
    lens = camera.get("lens") if isinstance(camera.get("lens"), dict) else {}
    width = int(packet.get("width_px") or 0)
    height = int(packet.get("height_px") or 0)
    eye = xyz_tuple(camera.get("eye"), "camera.eye")
    target = xyz_tuple(camera.get("target"), "camera.target")
    up = xyz_tuple(camera.get("up") or [0.0, 0.0, 1.0], "camera.up")
    vertical_fov = float(lens.get("vertical_fov_deg") or 0.0)
    if width <= 0 or height <= 0:
        raise ValueError("scene topdown render image size missing")
    if vertical_fov <= 0:
        raise ValueError("scene topdown render missing positive vertical_fov_deg")
    return SceneProjector(
        eye=eye,
        target=target,
        up=up,
        vertical_fov_deg=vertical_fov,
        width=width,
        height=height,
    )


def projected_bounds_polygon(
    bounds: dict[str, Any],
    projector: SceneProjector,
) -> list[tuple[float, float]]:
    points = [
        projector.project(float(bounds["min_x"]), float(bounds["min_y"]), z=0.0),
        projector.project(float(bounds["max_x"]), float(bounds["min_y"]), z=0.0),
        projector.project(float(bounds["max_x"]), float(bounds["max_y"]), z=0.0),
        projector.project(float(bounds["min_x"]), float(bounds["max_y"]), z=0.0),
    ]
    return [point for point in points if point is not None]


def draw_label(
    draw: ImageDraw.ImageDraw,
    point: tuple[float, float],
    text: str,
    *,
    fill: tuple[int, int, int, int],
    background: tuple[int, int, int, int],
) -> None:
    x, y = point
    text = text[:42]
    bbox = draw.textbbox((x, y), text)
    pad = 4
    draw.rectangle(
        (bbox[0] - pad, bbox[1] - pad, bbox[2] + pad, bbox[3] + pad),
        fill=background,
        outline=(255, 255, 255, 220),
    )
    draw.text((x, y), text, fill=fill)


def draw_overlay_header(draw: ImageDraw.ImageDraw, packet: dict[str, Any]) -> None:
    policy = packet.get("scene_visibility_policy")
    crop_source = ""
    if isinstance(policy, dict):
        crop_source = str(policy.get("source") or policy.get("status") or "")
    lines = [
        "B1 Gaussian topdown + scene USD label/bounds overlay",
        "Scene self-check only. Not projected to Map12.",
    ]
    if crop_source:
        lines.append(f"visibility: {crop_source}")
    y = 14
    for line in lines:
        bbox = draw.textbbox((14, y), line)
        draw.rectangle(
            (bbox[0] - 5, bbox[1] - 3, bbox[2] + 5, bbox[3] + 3), fill=(255, 255, 255, 205)
        )
        draw.text((14, y), line, fill=(20, 24, 28, 255))
        y += 20


def should_label_object(label: str) -> bool:
    return label not in {"chair", "plant"} and bool(label)


def xyz_tuple(value: Any, label: str) -> tuple[float, float, float]:
    if not isinstance(value, list | tuple) or len(value) != 3:
        raise ValueError(f"scene topdown render missing {label}")
    result = tuple(float(item) for item in value)
    if not all(math.isfinite(item) for item in result):
        raise ValueError(f"scene topdown render has non-finite {label}")
    return result


def normalize(vector: tuple[float, float, float]) -> tuple[float, float, float]:
    length = vector_length(vector)
    if length <= 0:
        raise ValueError("zero-length vector")
    return (vector[0] / length, vector[1] / length, vector[2] / length)


def vector_length(vector: tuple[float, float, float]) -> float:
    return math.sqrt(dot(vector, vector))


def dot(a: tuple[float, float, float], b: tuple[float, float, float]) -> float:
    return a[0] * b[0] + a[1] * b[1] + a[2] * b[2]


def cross(
    a: tuple[float, float, float],
    b: tuple[float, float, float],
) -> tuple[float, float, float]:
    return (
        a[1] * b[2] - a[2] * b[1],
        a[2] * b[0] - a[0] * b[2],
        a[0] * b[1] - a[1] * b[0],
    )


def validate_scene_topdown_diagnostic(packet: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    require(packet.get("schema") == DIAGNOSTIC_SCHEMA, "unexpected diagnostic schema", errors)
    require(packet.get("up_axis") == "z", "diagnostic must record up_axis=z", errors)
    require(
        packet.get("horizontal_axes") == ["x", "y"],
        "diagnostic must record horizontal_axes=[x,y]",
        errors,
    )
    require(bool(packet.get("geometry_status")), "diagnostic must record geometry_status", errors)
    require(
        packet.get("alignment_scope") == "scene_self_check_only",
        "diagnostic must be scoped to scene self-check only",
        errors,
    )
    require(
        packet.get("map_projection_status") == "not_projected_to_map12",
        "diagnostic must not project scene labels to Map12",
        errors,
    )
    require(
        int(packet.get("partition_count") or 0) > 0, "diagnostic must list scene partitions", errors
    )
    require(
        Path(str(packet.get("topdown_image") or "")).is_file(),
        "topdown diagnostic image missing",
        errors,
    )
    for partition in packet.get("partitions") or []:
        if not isinstance(partition, dict):
            errors.append("partition rows must be objects")
            continue
        require(bool(partition.get("partition_id")), "partition missing partition_id", errors)
        require(
            "object_name_counts" in partition,
            f"partition {partition.get('partition_id')} missing object_name_counts",
            errors,
        )
        if (
            packet.get("geometry_status")
            == "rendered_gaussian_topdown_with_scene_usd_bounds_overlay"
        ):
            require(
                partition.get("geometry_status") == "scene_usd_world_bounds",
                f"partition {partition.get('partition_id')} missing scene USD bounds",
                errors,
            )
    if packet.get("geometry_status") == "rendered_gaussian_topdown_with_scene_usd_bounds_overlay":
        require(
            int(packet.get("object_bound_count") or 0) > 0,
            "scene bounds overlay must include object bounds",
            errors,
        )
        stats = packet.get("overlay_render_stats")
        require(isinstance(stats, dict), "scene bounds overlay missing render stats", errors)
    return errors


def render_diagnostic_html(packet: dict[str, Any], *, packet_path: Path) -> str:
    axes = escape_html(json.dumps(packet.get("horizontal_axes") or []))
    rows = "".join(
        "<tr>"
        f"<td>{escape_html(str(partition.get('partition_id') or ''))}</td>"
        f"<td>{partition.get('object_label_count') or 0}</td>"
        f"<td>{partition.get('unique_object_label_count') or 0}</td>"
        f"<td>{high_signal_label_summary(partition)}</td>"
        "</tr>"
        for partition in packet.get("partitions") or []
        if isinstance(partition, dict)
    )
    image_name = Path(str(packet.get("topdown_image") or "")).name
    packet_name = packet_path.name
    source_image = Path(str(packet.get("source_topdown_image") or "")).name
    source_html = (
        f"<p>Source Gaussian topdown: <strong>{escape_html(source_image)}</strong></p>"
        if source_image
        else ""
    )
    overlay_stats = packet.get("overlay_render_stats")
    stats_html = ""
    if isinstance(overlay_stats, dict) and overlay_stats:
        drawn_partitions = overlay_stats.get("drawn_partition_count") or 0
        drawn_objects = overlay_stats.get("drawn_object_count") or 0
        stats_html = (
            "<p>"
            f"Drawn partitions: <strong>{drawn_partitions}</strong>. "
            f"Drawn objects: <strong>{drawn_objects}</strong>."
            "</p>"
        )
    alignment_scope = escape_html(str(packet.get("alignment_scope") or ""))
    map_projection_status = escape_html(str(packet.get("map_projection_status") or ""))
    return f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>B1 Scene Label Inventory Diagnostic</title>
  <style>
    :root {{ font-family: Inter, ui-sans-serif, system-ui, sans-serif; color: #17202a; }}
    body {{ margin: 0; background: #fff; }}
    main {{ max-width: 1120px; margin: 0 auto; padding: 28px 24px 44px; }}
    h1 {{ margin: 0 0 8px; font-size: 28px; letter-spacing: 0; }}
    p {{ color: #5d6b7a; line-height: 1.5; }}
    img {{ max-width: 100%; border: 1px solid #d8dee6; border-radius: 6px; }}
    table {{ width: 100%; border-collapse: collapse; margin-top: 18px; }}
    th, td {{ padding: 10px; border: 1px solid #d8dee6; text-align: left; vertical-align: top; }}
    th {{ background: #f7f8fa; font-size: 12px; color: #39424e; }}
  </style>
</head>
<body>
<main>
  <h1>B1 Scene Label Inventory Diagnostic</h1>
  <p>Geometry status: <strong>{escape_html(str(packet.get("geometry_status") or ""))}</strong>.
  Up axis: <strong>{escape_html(str(packet.get("up_axis") or ""))}</strong>.
  Horizontal axes: <strong>{axes}</strong>.</p>
  <p>Alignment scope: <strong>{alignment_scope}</strong>.
  Map projection: <strong>{map_projection_status}</strong>.</p>
  <p>{escape_html(str(packet.get("geometry_honesty") or ""))}</p>
  {source_html}
  {stats_html}
  <img src="{escape_html(image_name)}" alt="B1 scene label inventory diagnostic" />
  <table>
    <thead>
      <tr><th>Partition</th><th>Object Labels</th><th>Unique</th><th>High-Signal Labels</th></tr>
    </thead>
    <tbody>{rows}</tbody>
  </table>
  <p><a href="{escape_html(packet_name)}">scene_topdown_diagnostic.json</a></p>
</main>
</body>
</html>
"""


def high_signal_label_summary(partition: dict[str, Any]) -> str:
    labels = [
        str(item.get("label") or "")
        for item in partition.get("high_signal_object_labels", [])[:8]
        if isinstance(item, dict)
    ]
    return escape_html(", ".join(label for label in labels if label))


def file_inventory(path: Path) -> dict[str, Any]:
    return {
        "path": str(path),
        "exists": path.is_file(),
        "size_bytes": path.stat().st_size if path.is_file() else 0,
    }


def require(condition: bool, message: str, errors: list[str]) -> None:
    if not condition:
        errors.append(message)


def escape_html(value: str) -> str:
    return (
        value.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;").replace('"', "&quot;")
    )


def _positive_int_arg(value: str) -> int:
    try:
        parsed = int(value)
    except ValueError:
        raise argparse.ArgumentTypeError(f"expected a positive integer; got {value!r}") from None
    if parsed <= 0:
        raise argparse.ArgumentTypeError(f"expected a positive integer; got {value!r}")
    return parsed


if __name__ == "__main__":
    raise SystemExit(main())
