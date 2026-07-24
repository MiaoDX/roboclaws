from __future__ import annotations

from collections import deque
from dataclasses import dataclass
from typing import Any

from roboclaws.maps.rasterize import OccupancyGrid, occupancy_grid_from_metric_map, world_to_grid

SIM_COSTMAP_PLANNER = "sim_costmap_planner"


@dataclass(frozen=True)
class StaticRouteResult:
    ok: bool
    start_waypoint_id: str
    goal_waypoint_id: str
    navigation_backend: str = SIM_COSTMAP_PLANNER
    status: str = "ok"
    failure_type: str = ""
    path_length_m: float = 0.0
    path_cell_count: int = 0

    def as_dict(self) -> dict[str, Any]:
        return {
            "ok": self.ok,
            "status": self.status,
            "navigation_backend": self.navigation_backend,
            "start_waypoint_id": self.start_waypoint_id,
            "goal_waypoint_id": self.goal_waypoint_id,
            "failure_type": self.failure_type,
            "path_length_m": self.path_length_m,
            "path_cell_count": self.path_cell_count,
            "costmap_source": "nav2_static_global_costmap_projection",
        }


def validate_metric_map_route(
    metric_map: dict[str, Any],
    static_landmarks: list[dict[str, Any]],
    *,
    start_waypoint_id: str,
    goal_waypoint_id: str,
    occupancy_grid: OccupancyGrid | None = None,
) -> StaticRouteResult:
    waypoints = {
        str(item.get("waypoint_id") or ""): item
        for item in metric_map.get("inspection_waypoints") or []
    }
    start = waypoints.get(start_waypoint_id)
    goal = waypoints.get(goal_waypoint_id)
    if start is None:
        return StaticRouteResult(
            ok=False,
            status="blocked_capability",
            failure_type="unknown_start_waypoint",
            start_waypoint_id=start_waypoint_id,
            goal_waypoint_id=goal_waypoint_id,
        )
    if goal is None:
        return StaticRouteResult(
            ok=False,
            status="blocked_capability",
            failure_type="unknown_goal_waypoint",
            start_waypoint_id=start_waypoint_id,
            goal_waypoint_id=goal_waypoint_id,
        )

    grid = occupancy_grid or occupancy_grid_from_metric_map(metric_map, static_landmarks)
    start_cell = world_to_grid(float(start.get("x", 0.0)), float(start.get("y", 0.0)), grid)
    goal_cell = world_to_grid(float(goal.get("x", 0.0)), float(goal.get("y", 0.0)), grid)
    if not grid.is_free_cell(*start_cell):
        return StaticRouteResult(
            ok=False,
            status="blocked_capability",
            failure_type="start_occupied",
            start_waypoint_id=start_waypoint_id,
            goal_waypoint_id=goal_waypoint_id,
        )
    if not grid.is_free_cell(*goal_cell):
        return StaticRouteResult(
            ok=False,
            status="blocked_capability",
            failure_type="goal_occupied",
            start_waypoint_id=start_waypoint_id,
            goal_waypoint_id=goal_waypoint_id,
        )
    if start_cell == goal_cell:
        return StaticRouteResult(
            ok=True,
            start_waypoint_id=start_waypoint_id,
            goal_waypoint_id=goal_waypoint_id,
            path_cell_count=1,
        )

    distance_cells = _bfs_distance(grid, start_cell, goal_cell)
    if distance_cells is None:
        return StaticRouteResult(
            ok=False,
            status="blocked_capability",
            failure_type="no_static_costmap_path",
            start_waypoint_id=start_waypoint_id,
            goal_waypoint_id=goal_waypoint_id,
        )
    return StaticRouteResult(
        ok=True,
        start_waypoint_id=start_waypoint_id,
        goal_waypoint_id=goal_waypoint_id,
        path_length_m=round(distance_cells * grid.resolution_m, 3),
        path_cell_count=distance_cells + 1,
    )


def _bfs_distance(
    grid,
    start: tuple[int, int],
    goal: tuple[int, int],
) -> int | None:
    queue: deque[tuple[tuple[int, int], int]] = deque([(start, 0)])
    visited = {start}
    while queue:
        (col, row), distance = queue.popleft()
        for next_col, next_row in (
            (col + 1, row),
            (col - 1, row),
            (col, row + 1),
            (col, row - 1),
        ):
            cell = (next_col, next_row)
            if cell in visited or not grid.is_free_cell(next_col, next_row):
                continue
            if cell == goal:
                return distance + 1
            visited.add(cell)
            queue.append((cell, distance + 1))
    return None
