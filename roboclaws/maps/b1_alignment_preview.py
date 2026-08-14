from __future__ import annotations

from pathlib import Path
from typing import Any

import numpy as np
from PIL import Image, ImageDraw

from roboclaws.maps.b1_alignment_transform import anchor_scene_xy, apply_transform_point


def write_alignment_previews(
    anchors: list[dict[str, Any]],
    *,
    selected_transform: dict[str, Any] | None,
    output_dir: Path,
    manifest: dict[str, Any] | None = None,
) -> dict[str, str]:
    preview_dir = output_dir / "previews"
    preview_dir.mkdir(parents=True, exist_ok=True)
    before = preview_dir / "alignment_before.png"
    after = preview_dir / "alignment_after.png"
    draw_alignment_preview(anchors, before, transform=None, manifest=manifest or {})
    draw_alignment_preview(anchors, after, transform=selected_transform, manifest=manifest or {})
    return {
        "before_overlay": str(before),
        "after_overlay": str(after),
        "residual_arrows": str(after),
    }


def draw_alignment_preview(
    anchors: list[dict[str, Any]],
    path: Path,
    *,
    transform: dict[str, Any] | None,
    manifest: dict[str, Any],
) -> None:
    image = Image.new("RGB", (960, 720), color=(255, 255, 255))
    draw = ImageDraw.Draw(image)
    draw.rectangle((40, 40, 920, 680), outline=(210, 215, 222), width=2)
    if not anchors:
        draw.text((60, 60), "No accepted correspondence anchors", fill=(120, 30, 30))
        image.save(path)
        return
    map_points = [np.array(anchor["map_xy"], dtype=float) for anchor in anchors]
    scene_points = [np.array(anchor_scene_xy(anchor, manifest), dtype=float) for anchor in anchors]
    predicted_points = [
        apply_transform_point(point, transform) if transform is not None else point
        for point in map_points
    ]
    all_points = [*scene_points, *predicted_points]
    min_x = min(float(point[0]) for point in all_points)
    max_x = max(float(point[0]) for point in all_points)
    min_y = min(float(point[1]) for point in all_points)
    max_y = max(float(point[1]) for point in all_points)
    span_x = max(max_x - min_x, 1e-6)
    span_y = max(max_y - min_y, 1e-6)

    def canvas(point: np.ndarray) -> tuple[int, int]:
        x = 70 + (float(point[0]) - min_x) / span_x * 820
        y = 650 - (float(point[1]) - min_y) / span_y * 580
        return int(round(x)), int(round(y))

    for anchor, scene_point, predicted in zip(anchors, scene_points, predicted_points, strict=True):
        scene_xy = canvas(scene_point)
        predicted_xy = canvas(predicted)
        draw.line((*predicted_xy, *scene_xy), fill=(198, 81, 2), width=2)
        draw.ellipse(
            (scene_xy[0] - 5, scene_xy[1] - 5, scene_xy[0] + 5, scene_xy[1] + 5),
            fill=(9, 105, 218),
        )
        draw.rectangle(
            (
                predicted_xy[0] - 5,
                predicted_xy[1] - 5,
                predicted_xy[0] + 5,
                predicted_xy[1] + 5,
            ),
            fill=(29, 131, 72),
        )
        draw.text(
            (scene_xy[0] + 7, scene_xy[1] - 7),
            str(anchor.get("anchor_id") or ""),
            fill=(40, 45, 52),
        )
    draw.text(
        (60, 60), "Blue: scene pick. Green: fitted map pick. Orange: residual.", fill=(50, 50, 50)
    )
    image.save(path)
