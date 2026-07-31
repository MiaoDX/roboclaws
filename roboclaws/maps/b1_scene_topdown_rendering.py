from __future__ import annotations

import math
from pathlib import Path
from typing import Any

from PIL import Image, ImageDraw

_PARTITION_COLORS = [
    (69, 123, 157),
    (42, 157, 143),
    (233, 196, 106),
    (244, 162, 97),
    (231, 111, 81),
    (128, 90, 213),
    (95, 111, 82),
]


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
