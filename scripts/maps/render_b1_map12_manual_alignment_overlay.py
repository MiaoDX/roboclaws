#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

import numpy as np
from PIL import Image, ImageDraw

if __package__ in {None, ""}:
    repo_root = Path(__file__).resolve().parents[2]
    if str(repo_root) not in sys.path:
        sys.path.insert(0, str(repo_root))

from roboclaws.core.json_sources import read_json_object
from roboclaws.maps.b1_alignment_transform import apply_transform_point
from roboclaws.maps.b1_scene_topdown_rendering import scene_projector_from_topdown_packet
from roboclaws.maps.bundle_validation import parse_map_yaml

DEFAULT_MAP_BUNDLE = Path("vendors/agibot_sdk/artifacts/maps/robot_map_12/agibot")
DEFAULT_SCENE_TOPDOWN = Path(
    "output/b1-map12/scene-gaussian-topdown-crop-z1p8/scene_gaussian_topdown.json"
)
DEFAULT_ALIGNMENT = Path("output/b1-map12/manual-draft-alignment/alignment_residuals.json")
DEFAULT_OUTPUT_DIR = Path("output/b1-map12/manual-draft-alignment")


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Overlay Map12 occupancy on the cropped B1 Gaussian top-down using manual alignment."
        )
    )
    parser.add_argument("--map-bundle", type=Path, default=DEFAULT_MAP_BUNDLE)
    parser.add_argument("--scene-topdown-render", type=Path, default=DEFAULT_SCENE_TOPDOWN)
    parser.add_argument("--alignment-artifact", type=Path, default=DEFAULT_ALIGNMENT)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    try:
        packet = render_overlay(
            map_bundle=args.map_bundle,
            scene_topdown_render=args.scene_topdown_render,
            alignment_artifact=args.alignment_artifact,
            output_dir=args.output_dir,
        )
    except (FileNotFoundError, ValueError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    print(
        json.dumps(
            {
                "comparison": packet["comparison_image"],
                "output": packet["overlay_image"],
                "metadata": packet["metadata"],
                "status": packet["status"],
            },
            sort_keys=True,
        )
    )
    return 0


def render_overlay(
    *,
    map_bundle: Path,
    scene_topdown_render: Path,
    alignment_artifact: Path,
    output_dir: Path,
) -> dict[str, Any]:
    map_context = load_map_context(map_bundle)
    scene_packet = load_json(scene_topdown_render, "scene topdown render")
    alignment = load_json(alignment_artifact, "alignment artifact")
    transform = verified_transform(alignment)
    residuals = verified_residual_rows(alignment)
    scene_image_path = Path(str(scene_packet.get("topdown_image") or ""))
    if not scene_image_path.is_file():
        raise FileNotFoundError(f"scene topdown image missing: {scene_image_path}")
    scene_image = Image.open(scene_image_path).convert("RGBA")
    map_layer = Image.new("RGBA", scene_image.size, (0, 0, 0, 0))
    draw = ImageDraw.Draw(map_layer, "RGBA")
    projector = scene_projector_from_topdown_packet(scene_packet)

    free_points = projected_map_points(map_context, transform, projector, mode="free")
    occupied_points = projected_map_points(map_context, transform, projector, mode="occupied")
    draw_points(draw, free_points, color=(28, 120, 255, 62), radius=1)
    draw_points(draw, occupied_points, color=(255, 64, 42, 185), radius=2)
    draw_alignment_anchors(draw, residuals, transform, projector)

    output_dir.mkdir(parents=True, exist_ok=True)
    overlay_path = output_dir / "map12_on_gaussian_topdown.png"
    map_layer_path = output_dir / "map12_projected_layer.png"
    comparison_path = output_dir / "map12_gaussian_topdown_comparison.png"
    metadata_path = output_dir / "map12_on_gaussian_topdown.json"
    annotated_map_layer = map_layer.copy()
    draw_header(
        ImageDraw.Draw(annotated_map_layer, "RGBA"),
        alignment,
        title="Projected Map12 layer only",
        subtitle="blue=free, red=occupied, green=manual scene picks",
    )
    layer_background = Image.new("RGBA", scene_image.size, (18, 22, 26, 255))
    layer_only = Image.alpha_composite(layer_background, annotated_map_layer).convert("RGB")
    layer_only.save(map_layer_path)

    annotated_overlay = map_layer.copy()
    draw_header(
        ImageDraw.Draw(annotated_overlay, "RGBA"),
        alignment,
        title="Map12 projected onto Gaussian topdown",
        subtitle="photo-like base=Gaussian, colored layer=Map12",
    )
    blended = Image.alpha_composite(scene_image, annotated_overlay).convert("RGB")
    blended.save(overlay_path)
    comparison = comparison_image(scene_image.convert("RGB"), layer_only, blended)
    comparison.save(comparison_path)
    packet = {
        "schema": "b1_map12_manual_alignment_overlay_v1",
        "status": "rendered",
        "overlay_image": str(overlay_path),
        "map12_projected_layer": str(map_layer_path),
        "comparison_image": str(comparison_path),
        "metadata": str(metadata_path),
        "scene_topdown_render": str(scene_topdown_render),
        "gaussian_topdown_image": str(scene_image_path),
        "map_bundle": str(map_bundle),
        "alignment_artifact": str(alignment_artifact),
        "transform": transform,
        "projection_policy": {
            "source": "recorded_perspective_camera_projector",
            "projector": "scene_projector_from_topdown_packet",
            "z_plane": 0.0,
            "forbidden_shortcut": "Do not map scene_xy_bounds linearly to image pixels.",
        },
        "drawn_free_point_count": len(free_points),
        "drawn_occupied_point_count": len(occupied_points),
        "note": (
            "Map12 occupancy is transformed with the reviewed manual-anchor rigid alignment "
            "and projected through the recorded Gaussian top-down perspective camera. The "
            "photo-like source image is the Gaussian top-down. Blue=Map12 free, red=Map12 "
            "occupied."
        ),
    }
    metadata_path.write_text(json.dumps(packet, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return packet


def load_json(path: Path, label: str) -> dict[str, Any]:
    try:
        return read_json_object(path, label=label)
    except FileNotFoundError as exc:
        raise FileNotFoundError(f"{label} missing: {path}") from exc
    except ValueError as exc:
        message = str(exc)
        if "source must contain valid JSON object" in message:
            raise ValueError(f"{label} must contain valid JSON object: {path}") from exc
        if "source must contain a JSON object" in message:
            raise ValueError(f"{label} must be a JSON object: {path}") from exc
        raise


def verified_transform(alignment: dict[str, Any]) -> dict[str, Any]:
    transform = alignment.get("selected_transform")
    if not isinstance(transform, dict) or not transform:
        raise ValueError("alignment artifact must contain selected_transform")
    if alignment.get("global_alignment_status") != "verified":
        raise ValueError("alignment artifact must be globally verified")
    if transform.get("type") != "rigid_2d":
        raise ValueError(
            f"manual overlay expects rigid_2d transform, got {transform.get('type')!r}"
        )
    if str(transform.get("source") or "") != "reviewed_correspondence_fit":
        raise ValueError(
            "manual overlay requires selected_transform.source=reviewed_correspondence_fit"
        )
    return transform


def verified_residual_rows(alignment: dict[str, Any]) -> list[dict[str, Any]]:
    residuals = alignment.get("residuals")
    if not isinstance(residuals, list) or not residuals:
        raise ValueError("alignment artifact must contain residual rows")
    rows = []
    for index, row in enumerate(residuals, start=1):
        if not isinstance(row, dict):
            raise ValueError(f"alignment residual row {index} must be a JSON object")
        scene_xy = row.get("scene_xy")
        map_xy = row.get("map_xy")
        if not valid_xy(scene_xy) or not valid_xy(map_xy):
            raise ValueError(f"alignment residual row {index} must contain scene_xy and map_xy")
        rows.append(row)
    return rows


def valid_xy(value: Any) -> bool:
    if not isinstance(value, list) or len(value) < 2:
        return False
    try:
        float(value[0])
        float(value[1])
    except (TypeError, ValueError):
        return False
    return True


def load_map_context(map_bundle: Path) -> dict[str, Any]:
    map_yaml_path = map_bundle / "nav2.yaml"
    image_path = map_bundle / "occupancy.pgm"
    if not map_yaml_path.is_file():
        raise FileNotFoundError(f"Map12 nav2.yaml missing: {map_yaml_path}")
    if not image_path.is_file():
        raise FileNotFoundError(f"Map12 occupancy.pgm missing: {image_path}")
    map_yaml = parse_map_yaml(map_yaml_path.read_text(encoding="utf-8"))
    origin = map_yaml.get("origin") if isinstance(map_yaml.get("origin"), list) else []
    if len(origin) < 2:
        raise ValueError("Map12 nav2.yaml missing origin x/y")
    image = Image.open(image_path).convert("L")
    resolution_m = float(map_yaml.get("resolution") or 0.0)
    if resolution_m <= 0:
        raise ValueError(f"Map12 nav2.yaml must contain positive resolution: {map_yaml_path}")
    return {
        "image": np.array(image),
        "width": image.width,
        "height": image.height,
        "resolution_m": resolution_m,
        "origin_x": float(origin[0]),
        "origin_y": float(origin[1]),
    }


def projected_map_points(
    map_context: dict[str, Any],
    transform: dict[str, Any],
    projector: Any,
    *,
    mode: str,
    stride: int = 2,
) -> list[tuple[int, int]]:
    image = map_context["image"]
    if mode == "free":
        mask = image > 220
    elif mode == "occupied":
        mask = image < 100
    else:
        raise ValueError(f"unknown map point mode: {mode}")
    rows, cols = np.where(mask)
    points: list[tuple[int, int]] = []
    for row, col in zip(rows[::stride], cols[::stride], strict=False):
        map_xy = pixel_to_map_xy(float(col), float(row), map_context)
        scene_xy = apply_transform_point(np.array(map_xy, dtype=float), transform)
        projected = projector.project(float(scene_xy[0]), float(scene_xy[1]), z=0.0)
        if not projected:
            continue
        px, py = int(round(projected[0])), int(round(projected[1]))
        if 0 <= px < projector.width and 0 <= py < projector.height:
            points.append((px, py))
    return points


def pixel_to_map_xy(px: float, py: float, context: dict[str, Any]) -> list[float]:
    x = float(context["origin_x"]) + px * float(context["resolution_m"])
    y = float(context["origin_y"]) + (float(context["height"]) - 1.0 - py) * float(
        context["resolution_m"]
    )
    return [x, y]


def draw_points(
    draw: ImageDraw.ImageDraw,
    points: list[tuple[int, int]],
    *,
    color: tuple[int, int, int, int],
    radius: int,
) -> None:
    for x, y in points:
        draw.ellipse((x - radius, y - radius, x + radius, y + radius), fill=color)


def draw_alignment_anchors(
    draw: ImageDraw.ImageDraw,
    residuals: list[dict[str, Any]],
    transform: dict[str, Any],
    projector: Any,
) -> None:
    for row in residuals:
        scene_xy = row.get("scene_xy")
        map_xy = row.get("map_xy")
        actual = projector.project(float(scene_xy[0]), float(scene_xy[1]), z=0.0)
        predicted_xy = apply_transform_point(np.array(map_xy, dtype=float), transform)
        predicted = projector.project(float(predicted_xy[0]), float(predicted_xy[1]), z=0.0)
        if not actual or not predicted:
            continue
        ax, ay = actual
        px, py = predicted
        draw.line((px, py, ax, ay), fill=(255, 230, 80, 240), width=2)
        draw.ellipse((ax - 5, ay - 5, ax + 5, ay + 5), fill=(35, 220, 110, 240))
        draw.rectangle((px - 4, py - 4, px + 4, py + 4), outline=(255, 255, 255, 240), width=2)


def draw_header(
    draw: ImageDraw.ImageDraw,
    alignment: dict[str, Any],
    *,
    title: str,
    subtitle: str,
) -> None:
    residual = alignment.get("residual_evidence") if isinstance(alignment, dict) else {}
    lines = [
        title,
        subtitle,
        f"mean={residual.get('mean_residual_m')}m max={residual.get('max_residual_m')}m",
    ]
    y = 14
    for line in lines:
        bbox = draw.textbbox((14, y), line)
        draw.rectangle(
            (bbox[0] - 5, bbox[1] - 3, bbox[2] + 5, bbox[3] + 3),
            fill=(255, 255, 255, 215),
        )
        draw.text((14, y), line, fill=(20, 24, 28, 255))
        y += 20


def comparison_image(
    gaussian: Image.Image,
    map_layer: Image.Image,
    overlay: Image.Image,
) -> Image.Image:
    panels = [
        panel_with_label(
            gaussian,
            "Gaussian topdown source",
            "photo-like floor, walls, furniture, and rendered asset texture",
        ),
        panel_with_label(
            map_layer,
            "Map12 projected layer",
            "manual transform applied to occupancy/free cells",
        ),
        panel_with_label(
            overlay,
            "Overlay",
            "Gaussian source plus projected Map12 layer",
        ),
    ]
    gutter = 16
    width = sum(panel.width for panel in panels) + gutter * (len(panels) - 1)
    height = max(panel.height for panel in panels)
    canvas = Image.new("RGB", (width, height), (245, 247, 250))
    x = 0
    for panel in panels:
        canvas.paste(panel, (x, 0))
        x += panel.width + gutter
    return canvas


def panel_with_label(image: Image.Image, title: str, subtitle: str) -> Image.Image:
    image = image.convert("RGB")
    header_height = 58
    panel = Image.new("RGB", (image.width, image.height + header_height), (255, 255, 255))
    draw = ImageDraw.Draw(panel)
    draw.rectangle((0, 0, image.width, header_height), fill=(18, 24, 32))
    draw.text((14, 10), title, fill=(255, 255, 255))
    draw.text((14, 32), subtitle, fill=(215, 224, 235))
    panel.paste(image, (0, header_height))
    return panel


if __name__ == "__main__":
    raise SystemExit(main())
