from __future__ import annotations

import math
import re
from dataclasses import dataclass
from typing import Any, Callable

import mujoco
from PIL import Image, ImageDraw

ROBOT_PATH_COLOR = (37, 99, 235)
ROBOT_HEADING_COLOR = (15, 23, 42)
MANUAL_ADJUSTMENT_COLOR = (168, 85, 247)
MAP_WIDTH = 620
MAP_HEIGHT = 420
MAP_MARGIN = 34


@dataclass(frozen=True)
class _MapProjection:
    min_x: float
    max_x: float
    min_y: float
    max_y: float

    def project(self, x: float, y: float) -> tuple[int, int]:
        px = MAP_MARGIN + (x - self.min_x) / max(self.max_x - self.min_x, 0.001) * (
            MAP_WIDTH - 2 * MAP_MARGIN
        )
        py = (
            MAP_HEIGHT
            - MAP_MARGIN
            - (y - self.min_y) / max(self.max_y - self.min_y, 0.001) * (MAP_HEIGHT - 2 * MAP_MARGIN)
        )
        return (int(round(px)), int(round(py)))


def render_robot_map(
    state: dict[str, Any],
    *,
    focus: dict[str, Any] | None = None,
) -> Image.Image:
    image = Image.new("RGB", (MAP_WIDTH, MAP_HEIGHT), (247, 248, 250))
    draw = ImageDraw.Draw(image)

    focus = focus or {}
    projection = _map_projection(state, focus)

    _draw_map_frame(draw)
    _draw_room_outlines(draw, state, projection)
    _draw_focus_receptacle(draw, state, focus, projection)
    _draw_receptacles(draw, state, projection)
    _draw_selected_objects(draw, state, focus, projection)
    _draw_robot_trajectory(draw, state, projection)
    _draw_map_legend(draw)
    return image


def _map_projection(state: dict[str, Any], focus: dict[str, Any]) -> _MapProjection:
    min_x, max_x, min_y, max_y = map_bounds(map_points(state, focus))
    return _MapProjection(min_x=min_x, max_x=max_x, min_y=min_y, max_y=max_y)


def _draw_map_frame(draw: ImageDraw.ImageDraw) -> None:
    draw.rectangle((12, 12, MAP_WIDTH - 12, MAP_HEIGHT - 12), outline=(187, 193, 204), width=2)


def _draw_room_outlines(
    draw: ImageDraw.ImageDraw,
    state: dict[str, Any],
    projection: _MapProjection,
) -> None:
    for outline in state.get("room_outlines", []):
        left, top, right, bottom = _project_room_outline(outline, projection)
        draw.rectangle((left, top, right, bottom), outline=(148, 163, 184), width=2)
        draw.text((left + 5, top + 5), str(outline.get("label", "room")), fill=(71, 85, 105))


def _project_room_outline(
    outline: dict[str, Any],
    projection: _MapProjection,
) -> tuple[int, int, int, int]:
    center = outline["center"]
    half_x, half_y = outline["half_extents"]
    x1, y1 = projection.project(float(center[0]) - float(half_x), float(center[1]) - float(half_y))
    x2, y2 = projection.project(float(center[0]) + float(half_x), float(center[1]) + float(half_y))
    left, right = sorted((x1, x2))
    top, bottom = sorted((y1, y2))
    return left, top, right, bottom


def _draw_focus_receptacle(
    draw: ImageDraw.ImageDraw,
    state: dict[str, Any],
    focus: dict[str, Any],
    projection: _MapProjection,
) -> None:
    focus_receptacle_id = focus.get("receptacle_id")
    if focus_receptacle_id in state["receptacles"]:
        receptacle = state["receptacles"][focus_receptacle_id]
        x, y = projection.project(
            float(receptacle["position"][0]),
            float(receptacle["position"][1]),
        )
        draw.rounded_rectangle(
            (x - 13, y - 13, x + 13, y + 13),
            radius=5,
            outline=(8, 145, 178),
            width=4,
        )
        draw.text(
            (x + 10, y - 20),
            item_label(receptacle, "receptacle_id"),
            fill=(8, 92, 116),
        )


def _draw_receptacles(
    draw: ImageDraw.ImageDraw,
    state: dict[str, Any],
    projection: _MapProjection,
) -> None:
    for receptacle in state["receptacles"].values():
        x, y = projection.project(
            float(receptacle["position"][0]),
            float(receptacle["position"][1]),
        )
        draw.rounded_rectangle((x - 5, y - 5, x + 5, y + 5), radius=2, fill=(99, 116, 139))


def _draw_selected_objects(
    draw: ImageDraw.ImageDraw,
    state: dict[str, Any],
    focus: dict[str, Any],
    projection: _MapProjection,
) -> None:
    focus_object_id = focus.get("object_id")
    for object_id in state["selected_object_ids"]:
        obj = state["objects"][object_id]
        x, y = projection.project(float(obj["position"][0]), float(obj["position"][1]))
        draw.ellipse((x - 4, y - 4, x + 4, y + 4), fill=(192, 88, 68))
        if object_id == focus_object_id:
            _draw_focused_object(draw, obj, x, y)


def _draw_focused_object(
    draw: ImageDraw.ImageDraw,
    obj: dict[str, Any],
    x: int,
    y: int,
) -> None:
    draw.ellipse((x - 11, y - 11, x + 11, y + 11), outline=(220, 38, 38), width=4)
    draw.text((x + 10, y + 4), item_label(obj, "object_id"), fill=(153, 27, 27))


def _draw_robot_trajectory(
    draw: ImageDraw.ImageDraw,
    state: dict[str, Any],
    projection: _MapProjection,
) -> None:
    trajectory = state.get("robot_trajectory", [])
    projected_path = [projection.project(float(pose["x"]), float(pose["y"])) for pose in trajectory]
    if len(projected_path) >= 2:
        draw.line(projected_path, fill=ROBOT_PATH_COLOR, width=3)
    for index, (x, y) in enumerate(projected_path):
        pose = trajectory[index]
        manual_adjustment = _is_manual_adjustment_pose(pose)
        color = MANUAL_ADJUSTMENT_COLOR if manual_adjustment else ROBOT_PATH_COLOR
        radius = _robot_path_point_radius(
            manual_adjustment=manual_adjustment,
            index=index,
            path_length=len(projected_path),
        )
        draw.ellipse((x - radius, y - radius, x + radius, y + radius), fill=color)
        if manual_adjustment:
            draw.ellipse((x - radius, y - radius, x + radius, y + radius), outline=(255, 255, 255))

    _draw_robot_heading(draw, trajectory, projected_path)


def _robot_path_point_radius(*, manual_adjustment: bool, index: int, path_length: int) -> int:
    if manual_adjustment:
        return 7 if index == path_length - 1 else 5
    return 5 if index == path_length - 1 else 3


def _draw_robot_heading(
    draw: ImageDraw.ImageDraw,
    trajectory: list[dict[str, Any]],
    projected_path: list[tuple[int, int]],
) -> None:
    if not trajectory:
        return

    pose = trajectory[-1]
    x, y = projected_path[-1]
    heading = float(pose["theta"])
    tip = (int(round(x + math.cos(heading) * 18)), int(round(y - math.sin(heading) * 18)))
    left = (
        int(round(x + math.cos(heading + 2.45) * 10)),
        int(round(y - math.sin(heading + 2.45) * 10)),
    )
    right = (
        int(round(x + math.cos(heading - 2.45) * 10)),
        int(round(y - math.sin(heading - 2.45) * 10)),
    )
    draw.polygon([tip, left, right], fill=ROBOT_HEADING_COLOR)


def _draw_map_legend(draw: ImageDraw.ImageDraw) -> None:
    draw.text((24, 22), "RBY1M map", fill=(31, 41, 55))
    draw.text(
        (24, MAP_HEIGHT - 30),
        "blue: robot path  purple: manual adjust waypoint  gray: receptacles  red: objects",
        fill=(75, 85, 99),
    )
    draw.text(
        (24, MAP_HEIGHT - 16),
        "cyan/red rings: focus",
        fill=(75, 85, 99),
    )


def _is_manual_adjustment_pose(pose: Any) -> bool:
    if not isinstance(pose, dict):
        return False
    return str(pose.get("pose_source") or "") == "relative_robot_frame" or isinstance(
        pose.get("relative_pose_delta"), dict
    )


def map_points(state: dict[str, Any], focus: dict[str, Any]) -> list[list[float]]:
    points = [item["position"] for item in state["receptacles"].values()]
    points += [state["objects"][oid]["position"] for oid in state["selected_object_ids"]]
    points += [[pose["x"], pose["y"], 0.0] for pose in state.get("robot_trajectory", [])]
    if focus.get("focus_position"):
        points.append(focus["focus_position"])
    for outline in state.get("room_outlines", []):
        center = outline["center"]
        half_x, half_y = outline["half_extents"]
        points.extend(
            [
                [float(center[0]) - float(half_x), float(center[1]) - float(half_y), 0.0],
                [float(center[0]) + float(half_x), float(center[1]) + float(half_y), 0.0],
            ]
        )
    return points


def collect_room_outlines(
    model: mujoco.MjModel,
    data: mujoco.MjData,
    state: dict[str, Any],
    *,
    xyz: Callable[[Any], list[float]],
) -> list[dict[str, Any]]:
    outlines: list[dict[str, Any]] = []
    seen: set[str] = set()
    for geom_id in range(model.ngeom):
        name = mujoco.mj_id2name(model, mujoco.mjtObj.mjOBJ_GEOM, geom_id)
        if name is None:
            continue
        match = re.match(r"^(room_\d+)_visual", name)
        if match is None:
            continue
        room_id = match.group(1)
        if room_id in seen:
            continue
        bounds = geom_xy_bounds(model, data, geom_id, xyz=xyz)
        if bounds is None:
            continue
        min_xy, max_xy = bounds
        half_extents = [
            (float(max_xy[0]) - float(min_xy[0])) / 2.0,
            (float(max_xy[1]) - float(min_xy[1])) / 2.0,
        ]
        if min(half_extents) < 0.25:
            continue
        center = [
            (float(min_xy[0]) + float(max_xy[0])) / 2.0,
            (float(min_xy[1]) + float(max_xy[1])) / 2.0,
        ]
        outlines.append(
            _with_source_room_label(
                {
                    "room_id": room_id,
                    "label": room_id.replace("_", " ").title(),
                    "center": [round(center[0], 6), round(center[1], 6)],
                    "half_extents": [round(half_extents[0], 6), round(half_extents[1], 6)],
                    "provenance": "mujoco_room_mesh_world_bounds",
                },
                state,
            )
        )
        seen.add(room_id)
    if outlines:
        return sorted(outlines, key=lambda item: item["room_id"])
    return fallback_room_outlines(state)


def geom_xy_bounds(
    model: mujoco.MjModel,
    data: mujoco.MjData,
    geom_id: int,
    *,
    xyz: Callable[[Any], list[float]],
) -> tuple[list[float], list[float]] | None:
    geom_type = int(model.geom_type[geom_id])
    if geom_type == int(mujoco.mjtGeom.mjGEOM_MESH):
        mesh_id = int(model.geom_dataid[geom_id])
        if mesh_id < 0:
            return None
        vertex_start = int(model.mesh_vertadr[mesh_id])
        vertex_count = int(model.mesh_vertnum[mesh_id])
        if vertex_count <= 0:
            return None
        vertices = model.mesh_vert[vertex_start : vertex_start + vertex_count]
        matrix = data.geom_xmat[geom_id].reshape(3, 3)
        position = data.geom_xpos[geom_id]
        world_vertices = vertices @ matrix.T + position
        min_xy = [float(world_vertices[:, 0].min()), float(world_vertices[:, 1].min())]
        max_xy = [float(world_vertices[:, 0].max()), float(world_vertices[:, 1].max())]
        return min_xy, max_xy

    center = xyz(data.geom_xpos[geom_id])
    size = [float(value) for value in model.geom_size[geom_id]]
    radius_x = abs(size[0]) if size else 0.0
    radius_y = abs(size[1]) if len(size) > 1 else radius_x
    return [center[0] - radius_x, center[1] - radius_y], [
        center[0] + radius_x,
        center[1] + radius_y,
    ]


def fallback_room_outlines(state: dict[str, Any]) -> list[dict[str, Any]]:
    grouped: dict[str, list[list[float]]] = {}
    for receptacle in state["receptacles"].values():
        grouped.setdefault(str(receptacle.get("room_area", "room_unknown")), []).append(
            receptacle["position"]
        )
    for obj in state["objects"].values():
        location_id = obj.get("seeded_start_receptacle_id") or obj.get("target_receptacle_id")
        receptacle = state["receptacles"].get(location_id)
        if receptacle is None:
            continue
        grouped.setdefault(str(receptacle.get("room_area", "room_unknown")), []).append(
            obj["position"]
        )
    outlines = []
    for room_id, points in grouped.items():
        if not points:
            continue
        xs = [float(point[0]) for point in points]
        ys = [float(point[1]) for point in points]
        center = [round((min(xs) + max(xs)) / 2.0, 6), round((min(ys) + max(ys)) / 2.0, 6)]
        half_extents = [
            round(max((max(xs) - min(xs)) / 2.0, 0.8), 6),
            round(max((max(ys) - min(ys)) / 2.0, 0.8), 6),
        ]
        outlines.append(
            _with_source_room_label(
                {
                    "room_id": room_id,
                    "label": room_id.replace("_", " ").title(),
                    "center": center,
                    "half_extents": half_extents,
                    "provenance": "public_object_room_area_bounds",
                },
                state,
            )
        )
    return sorted(outlines, key=lambda item: item["room_id"])


def _with_source_room_label(outline: dict[str, Any], state: dict[str, Any]) -> dict[str, Any]:
    room_id = str(outline.get("room_id") or "")
    labels = state.get("source_room_labels") or {}
    label = labels.get(room_id) if isinstance(labels, dict) else None
    if not isinstance(label, dict):
        raise RuntimeError(f"missing source room label for {room_id}")
    room_label = str(label.get("room_label") or "").strip()
    if not room_label:
        raise RuntimeError(f"empty source room label for {room_id}")
    room_type = str(label.get("room_type") or "").strip()
    if not room_type:
        raise RuntimeError(f"missing source room type for {room_id}")
    provenance = str(label.get("room_label_provenance") or "").strip()
    if not provenance:
        raise RuntimeError(f"missing source room label provenance for {room_id}")
    return {
        **outline,
        "label": room_label,
        "room_label": room_label,
        "room_type": room_type,
        "room_label_provenance": provenance,
    }


def map_bounds(points: list[list[float]]) -> tuple[float, float, float, float]:
    if not points:
        return (0.0, 1.0, 0.0, 1.0)
    xs = [float(point[0]) for point in points]
    ys = [float(point[1]) for point in points]
    pad = 0.8
    return (min(xs) - pad, max(xs) + pad, min(ys) - pad, max(ys) + pad)


def item_label(item: dict[str, Any] | None, id_key: str) -> str:
    if item is None:
        return ""
    category = str(item.get("category") or item.get("kind") or "item")
    identifier = str(item.get(id_key, ""))
    short_id = identifier.split("_", 1)[0]
    return f"{category} {short_id}"
