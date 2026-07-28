from __future__ import annotations

from pathlib import Path

import pytest

from roboclaws.core.json_sources import read_json_object
from roboclaws.maps.base_waypoints import (
    BASE_WAYPOINT_GENERATION_POLICY,
    BASE_WAYPOINT_PURPOSE,
    BASE_WAYPOINT_SOURCE,
    BaseWaypointBuilder,
    BaseWaypointBuilderConfig,
    BaseWaypointBuildError,
    validate_base_waypoints,
)
from roboclaws.maps.bundle_validation import parse_map_yaml
from roboclaws.maps.rasterize import FREE_PIXEL, OCCUPIED_PIXEL, OccupancyGrid, load_pgm
from scripts.maps.build_b1_map12_base_metric_map import (
    DEFAULT_LABELS,
    DEFAULT_MAP_BUNDLE,
    DEFAULT_ROBOT_PROFILE,
    DEFAULT_ROOM_SEMANTICS,
    _origin_payload,
    _rooms_and_waypoints,
)

REPO_ROOT = Path(__file__).resolve().parents[3]


def test_base_waypoint_builder_preserves_b1_map12_waypoints() -> None:
    labels = read_json_object(REPO_ROOT / DEFAULT_LABELS, label="B1 base metric labels")
    room_semantics = read_json_object(REPO_ROOT / DEFAULT_ROOM_SEMANTICS, label="B1 rooms")
    map_yaml = parse_map_yaml((REPO_ROOT / DEFAULT_MAP_BUNDLE / "nav2.yaml").read_text())
    origin = _origin_payload(map_yaml)
    grid = load_pgm(
        REPO_ROOT / DEFAULT_MAP_BUNDLE / "occupancy.pgm",
        resolution_m=float(map_yaml["resolution"]),
        origin_x=origin["x"],
        origin_y=origin["y"],
    )

    rooms, waypoints = _rooms_and_waypoints(
        labels,
        room_semantics=room_semantics,
        grid=grid,
        frame_id=str(labels["source_map_frame_id"]),
    )
    by_area = {waypoint["navigation_area_id"]: waypoint for waypoint in waypoints}

    assert set(by_area) == {
        "meeting_room_b",
        "meeting_room_c",
        "reception_area_a",
        "open_kitchen_a",
        "long_corridor_a",
    }
    assert by_area["open_kitchen_a"]["x"] == pytest.approx(1.15)
    assert by_area["open_kitchen_a"]["y"] == pytest.approx(-4.7)
    assert all(
        waypoint["generation_policy"] == BASE_WAYPOINT_GENERATION_POLICY
        and waypoint["purpose"] == BASE_WAYPOINT_PURPOSE
        and waypoint["waypoint_source"] == BASE_WAYPOINT_SOURCE
        and "fixture_id" not in waypoint
        and "object_id" not in waypoint
        and "receptacle_id" not in waypoint
        for waypoint in by_area.values()
    )
    assert all(
        waypoint["clearance_radius_m"] == DEFAULT_ROBOT_PROFILE["footprint"]["radius_m"]
        for waypoint in by_area.values()
    )
    assert len(rooms) == len(labels["labels"])


def test_base_waypoint_builder_generates_area_inspection_waypoint_from_area_only() -> None:
    grid = _grid_with_free_box(left=2, right=7, top=2, bottom=7)
    area = _area("kitchen_a")

    waypoints = _builder(grid, clearance_radius_m=1.0).build([area])

    assert waypoints == [
        {
            "waypoint_id": "kitchen_a_inspection",
            "frame_id": "map",
            "x": 4.0,
            "y": 5.0,
            "yaw": 0.0,
            "room_id": "kitchen_a",
            "navigation_area_id": "kitchen_a",
            "label": "Generated exploration candidate 1",
            "room_label": "Kitchen A",
            "purpose": BASE_WAYPOINT_PURPOSE,
            "waypoint_source": BASE_WAYPOINT_SOURCE,
            "generation_policy": BASE_WAYPOINT_GENERATION_POLICY,
            "sweep_index": 1,
            "source_label_id": "label_kitchen_a",
            "clearance_radius_m": 1.0,
            "source_polygon_index": 7,
        }
    ]
    assert (
        validate_base_waypoints(
            waypoints,
            navigation_area_ids={"kitchen_a"},
            grid=grid,
        )
        == []
    )


def test_base_waypoint_builder_selects_centroid_nearest_safe_pose_for_irregular_area() -> None:
    grid = _grid(
        [
            "##########",
            "#........#",
            "#........#",
            "#...##...#",
            "#...##...#",
            "#........#",
            "#........#",
            "#........#",
            "#........#",
            "##########",
        ],
        resolution_m=1.0,
    )
    area = {
        "room_id": "irregular_living_area",
        "navigation_area_id": "irregular_living_area",
        "room_label": "Irregular living area",
        "polygon": [
            {"x": 1.0, "y": 1.0},
            {"x": 8.0, "y": 1.0},
            {"x": 8.0, "y": 8.0},
            {"x": 5.0, "y": 6.0},
            {"x": 1.0, "y": 8.0},
        ],
    }

    waypoints = _builder(grid, clearance_radius_m=1.0).build([area])

    assert waypoints == [
        {
            "waypoint_id": "irregular_living_area_inspection",
            "frame_id": "map",
            "x": 6.0,
            "y": 4.0,
            "yaw": 0.0,
            "room_id": "irregular_living_area",
            "navigation_area_id": "irregular_living_area",
            "label": "Generated exploration candidate 1",
            "room_label": "Irregular living area",
            "purpose": BASE_WAYPOINT_PURPOSE,
            "waypoint_source": BASE_WAYPOINT_SOURCE,
            "generation_policy": BASE_WAYPOINT_GENERATION_POLICY,
            "sweep_index": 1,
            "source_label_id": "",
            "clearance_radius_m": 1.0,
            "source_polygon_index": 1,
        }
    ]


def test_base_waypoint_builder_fails_loudly_for_fully_occupied_area() -> None:
    grid = _occupied_grid()

    with pytest.raises(BaseWaypointBuildError, match="no clearance-safe free inspection pose"):
        _builder(grid).build([_area("blocked_area")])


@pytest.mark.parametrize(
    "forbidden_key",
    [
        "fixtures",
        "receptacles",
        "object_inventory",
        "static_landmarks",
        "generated_mess_set",
        "relocation_truth",
        "private_cleanup_target_truth",
        "fixture_id",
        "object_id",
        "receptacle_id",
    ],
)
def test_base_waypoint_builder_rejects_fixture_object_and_private_truth_inputs(
    forbidden_key: str,
) -> None:
    grid = _grid_with_free_box(left=2, right=7, top=2, bottom=7)
    area = _area("kitchen_a")
    area[forbidden_key] = [{"id": "private"}]

    with pytest.raises(BaseWaypointBuildError, match="forbidden base waypoint inputs"):
        _builder(grid).build([area])


def test_base_waypoint_validator_reports_bad_area_binding_and_occupied_pose() -> None:
    grid = _grid_with_free_box(left=2, right=7, top=2, bottom=7)
    waypoint = {
        "waypoint_id": "bad_inspection",
        "navigation_area_id": "missing_area",
        "purpose": BASE_WAYPOINT_PURPOSE,
        "generation_policy": BASE_WAYPOINT_GENERATION_POLICY,
        "x": 0.0,
        "y": 0.0,
        "yaw": 0.0,
    }

    errors = validate_base_waypoints([waypoint], navigation_area_ids={"known_area"}, grid=grid)

    assert "binds unknown navigation_area_id 'missing_area'" in "\n".join(errors)
    assert "not on a free occupancy cell" in "\n".join(errors)


def _builder(
    grid: OccupancyGrid,
    *,
    clearance_radius_m: float = 0.5,
) -> BaseWaypointBuilder:
    return BaseWaypointBuilder(
        grid=grid,
        config=BaseWaypointBuilderConfig(frame_id="map", clearance_radius_m=clearance_radius_m),
    )


def _area(area_id: str) -> dict:
    return {
        "room_id": area_id,
        "navigation_area_id": area_id,
        "room_label": "Kitchen A",
        "source_label_id": f"label_{area_id}",
        "source_polygon_index": 7,
        "polygon": [
            {"x": 2.0, "y": 2.0},
            {"x": 7.0, "y": 2.0},
            {"x": 7.0, "y": 7.0},
            {"x": 2.0, "y": 7.0},
        ],
    }


def _grid_with_free_box(*, left: int, right: int, top: int, bottom: int) -> OccupancyGrid:
    rows = []
    for row in range(10):
        values = []
        for col in range(10):
            values.append(254 if left <= col <= right and top <= row <= bottom else 0)
        rows.append(tuple(values))
    return OccupancyGrid(
        width=10,
        height=10,
        resolution_m=1.0,
        origin_x=0.0,
        origin_y=0.0,
        rows=tuple(rows),
    )


def _occupied_grid() -> OccupancyGrid:
    return OccupancyGrid(
        width=10,
        height=10,
        resolution_m=1.0,
        origin_x=0.0,
        origin_y=0.0,
        rows=tuple(tuple(0 for _ in range(10)) for _ in range(10)),
    )


def _grid(rows: list[str], *, resolution_m: float) -> OccupancyGrid:
    height = len(rows)
    width = len(rows[0])
    return OccupancyGrid(
        width=width,
        height=height,
        resolution_m=resolution_m,
        origin_x=0.0,
        origin_y=0.0,
        rows=tuple(
            tuple(FREE_PIXEL if value == "." else OCCUPIED_PIXEL for value in row) for row in rows
        ),
    )
