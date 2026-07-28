from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any

from PIL import Image, ImageDraw

from roboclaws.maps.rasterize import OccupancyGrid, world_to_grid

BASE_WAYPOINT_GENERATION_POLICY = "base_navigation_area_centroid_clearance_v1"
BASE_WAYPOINT_PURPOSE = "base_navigation_area_inspection"
BASE_WAYPOINT_SOURCE = "generated_exploration_candidate"
BASE_WAYPOINT_FORBIDDEN_INPUT_KEYS = frozenset(
    {
        "acceptable_destination_sets",
        "fixture_groups",
        "fixture_id",
        "fixture_ids",
        "fixtures",
        "generated_mess_set",
        "global_movable_object_inventory",
        "landmark_id",
        "movable_objects",
        "navigation_memory_anchors",
        "object_id",
        "object_inventory",
        "preferred_inspection_waypoint_id",
        "preferred_manipulation_waypoint_id",
        "private_cleanup_target_truth",
        "receptacle_id",
        "receptacle_ids",
        "receptacles",
        "relocation_truth",
        "static_landmarks",
        "target_fixture_id",
        "target_receptacle_id",
        "valid_receptacle_ids",
    }
)


class BaseWaypointBuildError(ValueError):
    """Raised when a navigation area cannot produce a valid base waypoint."""


def generated_exploration_candidate_label(sweep_index: int) -> str:
    if sweep_index <= 0:
        raise ValueError("generated exploration candidate sweep_index must be positive")
    return f"Generated exploration candidate {sweep_index}"


@dataclass(frozen=True)
class BaseWaypointBuilderConfig:
    frame_id: str
    clearance_radius_m: float
    generation_policy: str = BASE_WAYPOINT_GENERATION_POLICY
    waypoint_source: str = BASE_WAYPOINT_SOURCE
    yaw: float = 0.0


class BaseWaypointBuilder:
    """Build sparse area-inspection waypoints from Base Metric Map fields only."""

    def __init__(self, *, grid: OccupancyGrid, config: BaseWaypointBuilderConfig) -> None:
        if not config.frame_id:
            raise BaseWaypointBuildError("base waypoint builder requires frame_id")
        if config.clearance_radius_m <= 0:
            raise BaseWaypointBuildError(
                "base waypoint builder clearance_radius_m must be positive"
            )
        self._grid = grid
        self._config = config

    def build(self, navigation_areas: list[dict[str, Any]]) -> list[dict[str, Any]]:
        if not navigation_areas:
            raise BaseWaypointBuildError("base waypoint builder requires navigation areas")
        waypoints: list[dict[str, Any]] = []
        for index, area in enumerate(navigation_areas, start=1):
            self._validate_builder_input(area)
            area_id = _area_id(area)
            if not area_id:
                raise BaseWaypointBuildError(f"navigation area {index} missing navigation_area_id")
            pose = self.inspection_pose(area)
            if pose is None:
                raise BaseWaypointBuildError(
                    f"navigation area {area_id} has no clearance-safe free inspection pose"
                )
            sweep_index = len(waypoints) + 1
            room_label = str(area.get("room_label") or area.get("label") or area_id)
            waypoints.append(
                {
                    "waypoint_id": f"{area_id}_inspection",
                    "frame_id": self._config.frame_id,
                    "x": pose["x"],
                    "y": pose["y"],
                    "yaw": self._config.yaw,
                    "room_id": str(area.get("room_id") or area_id),
                    "navigation_area_id": area_id,
                    "label": generated_exploration_candidate_label(sweep_index),
                    "room_label": room_label,
                    "purpose": BASE_WAYPOINT_PURPOSE,
                    "waypoint_source": self._config.waypoint_source,
                    "generation_policy": self._config.generation_policy,
                    "sweep_index": sweep_index,
                    "source_label_id": str(area.get("source_label_id") or ""),
                    "clearance_radius_m": self._config.clearance_radius_m,
                    "source_polygon_index": int(area.get("source_polygon_index") or index),
                }
            )
        return waypoints

    def inspection_pose(self, area: dict[str, Any]) -> dict[str, float] | None:
        polygon = _polygon(area)
        if len(polygon) < 3:
            return None
        mask = Image.new("1", (self._grid.width, self._grid.height), 0)
        ImageDraw.Draw(mask).polygon(
            [world_to_grid(point["x"], point["y"], self._grid) for point in polygon],
            fill=1,
        )
        bbox = mask.getbbox()
        if bbox is None:
            return None
        centroid = _polygon_centroid(polygon)
        clearance_radius_cells = max(
            1,
            int(math.ceil(self._config.clearance_radius_m / self._grid.resolution_m)),
        )
        candidates: list[tuple[int, float, int, int, float, float]] = []
        for row in range(bbox[1], bbox[3]):
            for col in range(bbox[0], bbox[2]):
                if not mask.getpixel((col, row)):
                    continue
                clearance_score = _clearance_score(
                    self._grid,
                    col=col,
                    row=row,
                    radius_cells=clearance_radius_cells,
                )
                if clearance_score < clearance_radius_cells:
                    continue
                x = self._grid.origin_x + col * self._grid.resolution_m
                y = self._grid.origin_y + (self._grid.height - 1 - row) * self._grid.resolution_m
                distance_to_centroid = (x - centroid["x"]) ** 2 + (y - centroid["y"]) ** 2
                candidates.append((-clearance_score, distance_to_centroid, row, col, x, y))
        if not candidates:
            return None
        _, _, _, _, x, y = min(candidates)
        return {"x": round(x, 3), "y": round(y, 3)}

    def _validate_builder_input(self, area: dict[str, Any]) -> None:
        forbidden_keys = sorted(BASE_WAYPOINT_FORBIDDEN_INPUT_KEYS.intersection(area))
        if forbidden_keys:
            area_id = _area_id(area) or "<unknown>"
            raise BaseWaypointBuildError(
                f"navigation area {area_id} contains forbidden base waypoint inputs: "
                f"{forbidden_keys}"
            )


def validate_base_waypoints(
    waypoints: list[dict[str, Any]],
    *,
    navigation_area_ids: set[str],
    grid: OccupancyGrid,
) -> list[str]:
    errors: list[str] = []
    if not waypoints:
        return ["base waypoint set must not be empty"]
    seen: set[str] = set()
    for index, waypoint in enumerate(waypoints, start=1):
        waypoint_id = str(waypoint.get("waypoint_id") or "")
        if not waypoint_id:
            errors.append(f"base waypoint {index} missing waypoint_id")
            continue
        if waypoint_id in seen:
            errors.append(f"duplicate base waypoint_id: {waypoint_id}")
        seen.add(waypoint_id)
        area_id = str(waypoint.get("navigation_area_id") or "")
        if area_id not in navigation_area_ids:
            errors.append(
                f"base waypoint {waypoint_id} binds unknown navigation_area_id {area_id!r}"
            )
        if waypoint.get("purpose") != BASE_WAYPOINT_PURPOSE:
            errors.append(f"base waypoint {waypoint_id} has invalid purpose")
        if waypoint.get("generation_policy") != BASE_WAYPOINT_GENERATION_POLICY:
            errors.append(f"base waypoint {waypoint_id} has invalid generation_policy")
        try:
            x = float(waypoint.get("x"))
            y = float(waypoint.get("y"))
            float(waypoint.get("yaw"))
        except (TypeError, ValueError):
            errors.append(f"base waypoint {waypoint_id} must contain numeric x/y/yaw")
            continue
        if not grid.is_free_world(x, y):
            errors.append(f"base waypoint {waypoint_id} is not on a free occupancy cell")
    return errors


def _area_id(area: dict[str, Any]) -> str:
    return str(
        area.get("navigation_area_id") or area.get("map_area_id") or area.get("room_id") or ""
    )


def _polygon(area: dict[str, Any]) -> list[dict[str, float]]:
    return [
        {"x": float(point["x"]), "y": float(point["y"])}
        for point in (area.get("polygon") or ((area.get("geometry") or {}).get("polygon") or []))
        if isinstance(point, dict) and "x" in point and "y" in point
    ]


def _polygon_centroid(polygon: list[dict[str, float]]) -> dict[str, float]:
    return {
        "x": sum(point["x"] for point in polygon) / len(polygon),
        "y": sum(point["y"] for point in polygon) / len(polygon),
    }


def _clearance_score(
    grid: OccupancyGrid,
    *,
    col: int,
    row: int,
    radius_cells: int,
) -> int:
    if not grid.is_free_cell(col, row):
        return -1
    safe_radius = 0
    for candidate_radius in range(1, radius_cells + 1):
        if not _is_clearance_safe_cell(grid, col=col, row=row, radius_cells=candidate_radius):
            return safe_radius
        safe_radius = candidate_radius
    return safe_radius


def _is_clearance_safe_cell(
    grid: OccupancyGrid,
    *,
    col: int,
    row: int,
    radius_cells: int,
) -> bool:
    for next_row in range(row - radius_cells, row + radius_cells + 1):
        for next_col in range(col - radius_cells, col + radius_cells + 1):
            if (next_col - col) ** 2 + (next_row - row) ** 2 > radius_cells**2:
                continue
            if not grid.is_free_cell(next_col, next_row):
                return False
    return True
