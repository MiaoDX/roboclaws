from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest
from PIL import Image

from roboclaws.household.household_backend_contract import HouseholdBackendSession
from roboclaws.household.household_runtime_contract import HouseholdRuntimeContract
from roboclaws.household.nav2_map_bundle import attach_nav2_map_bundle_snapshot
from roboclaws.household.scenario import build_cleanup_scenario
from roboclaws.maps.bundle import (
    static_landmarks_from_fixture_projection,
    validate_base_metric_map_v1_bundle,
    validate_nav2_map_bundle,
    write_nav2_map_bundle,
)
from roboclaws.maps.project import metric_map_from_bundle, static_landmarks_from_bundle
from roboclaws.maps.route import SIM_COSTMAP_PLANNER, validate_metric_map_route

REPO_ROOT = Path(__file__).resolve().parents[3]
CANONICAL_SCENE_BUNDLE = REPO_ROOT / "assets" / "maps" / "molmospaces" / "procthor-10k-val" / "0"


def _repo_python() -> str:
    python_path = REPO_ROOT / ".venv" / "bin" / "python"
    assert python_path.is_file(), f"repo Python missing: {python_path}; run uv sync --extra dev"
    return str(python_path)


def test_nav2_bundle_writer_exports_valid_projection_and_static_route(tmp_path: Path) -> None:
    agent_view = _agent_view()
    bundle_dir = tmp_path / "base-metric-map-bundle"

    snapshot = write_nav2_map_bundle(
        bundle_dir,
        metric_map=agent_view["metric_map"],
        static_landmarks=_static_landmarks(agent_view),
    )

    validation = validate_nav2_map_bundle(bundle_dir)
    projected_map = metric_map_from_bundle(bundle_dir)
    static_landmarks = static_landmarks_from_bundle(bundle_dir)
    waypoints = projected_map["inspection_waypoints"]
    route = validate_metric_map_route(
        projected_map,
        static_landmarks,
        start_waypoint_id=str(waypoints[0]["waypoint_id"]),
        goal_waypoint_id=str(waypoints[-1]["waypoint_id"]),
    )

    assert snapshot["snapshot_complete"] is True
    assert validation.ok, validation.as_dict()
    assert projected_map["schema"] == "real_robot_map_bundle_v1"
    assert projected_map["map_bundle"]["schema"] == "nav2_map_bundle_v1"
    assert static_landmarks == []
    assert route.ok is True
    assert route.navigation_backend == SIM_COSTMAP_PLANNER
    assert route.path_length_m > 0


def test_nav2_bundle_preview_uses_canonical_map_visual_role(tmp_path: Path) -> None:
    agent_view = _agent_view()
    bundle_dir = tmp_path / "base-metric-map-bundle"

    snapshot = write_nav2_map_bundle(
        bundle_dir,
        metric_map=agent_view["metric_map"],
        static_landmarks=_static_landmarks(agent_view),
    )

    preview_path = bundle_dir / snapshot["artifact_paths"]["preview_png"]
    image = Image.open(preview_path).convert("RGB")
    extrema = image.getextrema()

    assert image.size == (900, 560)
    assert min(channel[1] - channel[0] for channel in extrema) > 80
    assert snapshot["artifact_paths"]["preview_png"] == "preview.png"


def test_nav2_bundle_validation_rejects_private_cleanup_truth(tmp_path: Path) -> None:
    agent_view = _agent_view()
    bundle_dir = tmp_path / "bundle"
    write_nav2_map_bundle(
        bundle_dir,
        metric_map=agent_view["metric_map"],
        static_landmarks=_static_landmarks(agent_view),
    )
    semantics_path = bundle_dir / "semantics.json"
    semantics = json.loads(semantics_path.read_text(encoding="utf-8"))
    semantics["generated_mess_set"] = [{"object_id": "private"}]
    semantics_path.write_text(json.dumps(semantics), encoding="utf-8")

    validation = validate_nav2_map_bundle(bundle_dir)

    assert validation.ok is False
    assert any("private cleanup truth" in error for error in validation.errors)


def test_base_metric_map_v1_validation_accepts_b1_bundle(tmp_path: Path) -> None:
    from roboclaws.maps.b1_base_metric_map import (
        DEFAULT_LABELS,
        DEFAULT_MAP_BUNDLE,
        DEFAULT_ROOM_SEMANTICS,
        build_base_metric_map_bundle,
    )

    output_dir = tmp_path / "base-metric-map"
    build_base_metric_map_bundle(
        map_bundle=DEFAULT_MAP_BUNDLE,
        labels_path=DEFAULT_LABELS,
        room_semantics_path=DEFAULT_ROOM_SEMANTICS,
        output_dir=output_dir,
    )

    validation = validate_base_metric_map_v1_bundle(output_dir)

    assert validation.ok, validation.as_dict()
    assert validation.metadata["base_metric_map_schema"] == "base_metric_map_v1"
    assert validation.metadata["base_metric_map_v1_ready"] is True
    assert validation.metadata["waypoint_count"] == 5


def test_base_metric_map_v1_validation_accepts_canonical_molmospaces_bundle() -> None:
    validation = validate_base_metric_map_v1_bundle(CANONICAL_SCENE_BUNDLE)

    assert validation.ok, validation.as_dict()
    assert validation.metadata["base_metric_map_schema"] == "base_metric_map_v1"
    assert validation.metadata["base_metric_map_v1_ready"] is True
    assert validation.metadata["static_landmark_count"] == 0
    assert validation.metadata["waypoint_count"] > 0


@pytest.mark.parametrize(
    ("mutator", "expected_error"),
    (
        (
            lambda semantics: semantics["rooms"][1].update({"category": ""}),
            "navigation area meeting_room_b missing semantic category",
        ),
        (
            lambda semantics: semantics["rooms"][1].update({"category": "unknown_review_required"}),
            "unknown_review_required",
        ),
        (
            lambda semantics: semantics.update({"inspection_waypoints": []}),
            "Base Metric Map v1 must contain base inspection waypoints",
        ),
        (
            lambda semantics: semantics["inspection_waypoints"][0].update(
                {"navigation_area_id": "missing_area"}
            ),
            "binds unknown navigation_area_id 'missing_area'",
        ),
        (
            lambda semantics: semantics["inspection_waypoints"][0].update(
                {"fixture_id": "counter_1"}
            ),
            "contains forbidden fields: ['fixture_id']",
        ),
    ),
)
def test_base_metric_map_v1_validation_rejects_contract_violations(
    tmp_path: Path,
    mutator,
    expected_error: str,
) -> None:
    bundle_dir = _b1_base_metric_bundle(tmp_path)
    semantics_path = bundle_dir / "semantics.json"
    semantics = json.loads(semantics_path.read_text(encoding="utf-8"))
    mutator(semantics)
    semantics_path.write_text(json.dumps(semantics), encoding="utf-8")

    validation = validate_base_metric_map_v1_bundle(bundle_dir)

    assert validation.ok is False
    assert any(expected_error in error for error in validation.errors), validation.as_dict()


def test_nav2_projection_rejects_map_yaml_without_image(tmp_path: Path) -> None:
    bundle_dir = tmp_path / "bundle"
    agent_view = _agent_view()
    write_nav2_map_bundle(
        bundle_dir,
        metric_map=agent_view["metric_map"],
        static_landmarks=_static_landmarks(agent_view),
    )
    map_yaml_path = bundle_dir / "map.yaml"
    map_yaml = "\n".join(
        line
        for line in map_yaml_path.read_text(encoding="utf-8").splitlines()
        if line != "image: map.pgm"
    )
    map_yaml_path.write_text(map_yaml + "\n", encoding="utf-8")

    with pytest.raises(AssertionError, match="map.yaml image must resolve to map.pgm"):
        metric_map_from_bundle(bundle_dir)


def test_nav2_projection_rejects_semantics_without_waypoints(tmp_path: Path) -> None:
    bundle_dir = tmp_path / "bundle"
    agent_view = _agent_view()
    write_nav2_map_bundle(
        bundle_dir,
        metric_map=agent_view["metric_map"],
        static_landmarks=_static_landmarks(agent_view),
    )
    semantics_path = bundle_dir / "semantics.json"
    semantics = json.loads(semantics_path.read_text(encoding="utf-8"))
    semantics["inspection_waypoints"] = []
    semantics_path.write_text(json.dumps(semantics), encoding="utf-8")

    with pytest.raises(AssertionError, match="semantics.json must contain inspection_waypoints"):
        static_landmarks_from_bundle(bundle_dir)


def test_nav2_projection_rejects_non_object_semantics(tmp_path: Path) -> None:
    bundle_dir = tmp_path / "bundle"
    agent_view = _agent_view()
    write_nav2_map_bundle(
        bundle_dir,
        metric_map=agent_view["metric_map"],
        static_landmarks=_static_landmarks(agent_view),
    )
    (bundle_dir / "semantics.json").write_text("[]\n", encoding="utf-8")

    validation = validate_nav2_map_bundle(bundle_dir)

    assert validation.ok is False
    assert len(validation.errors) == 1
    assert "Nav2 semantics source must contain a JSON object" in validation.errors[0]
    assert str(bundle_dir / "semantics.json") in validation.errors[0]
    with pytest.raises(
        AssertionError,
        match=r"Nav2 semantics source must contain a JSON object: .*semantics\.json",
    ):
        metric_map_from_bundle(bundle_dir)


def test_nav2_projection_rejects_malformed_semantics(tmp_path: Path) -> None:
    bundle_dir = tmp_path / "bundle"
    agent_view = _agent_view()
    write_nav2_map_bundle(
        bundle_dir,
        metric_map=agent_view["metric_map"],
        static_landmarks=_static_landmarks(agent_view),
    )
    (bundle_dir / "semantics.json").write_text("{", encoding="utf-8")

    validation = validate_nav2_map_bundle(bundle_dir)

    assert validation.ok is False
    assert len(validation.errors) == 1
    assert "Nav2 semantics source must contain valid JSON object" in validation.errors[0]
    assert str(bundle_dir / "semantics.json") in validation.errors[0]
    with pytest.raises(
        AssertionError,
        match=r"Nav2 semantics source must contain valid JSON object: .*semantics\.json",
    ):
        static_landmarks_from_bundle(bundle_dir)


def test_nav2_projection_preserves_declared_map_frame(tmp_path: Path) -> None:
    bundle_dir = tmp_path / "bundle"
    agent_view = _agent_view()
    write_nav2_map_bundle(
        bundle_dir,
        metric_map=agent_view["metric_map"],
        static_landmarks=_static_landmarks(agent_view),
    )
    semantics_path = bundle_dir / "semantics.json"
    semantics = json.loads(semantics_path.read_text(encoding="utf-8"))
    semantics["frame_ids"]["map"] = "operator_map"
    semantics["spatial_contract"]["source_map_frame"]["frame_id"] = "operator_map"
    for room in semantics["rooms"]:
        room["source_map_frame_id"] = "operator_map"
    for waypoint in semantics["inspection_waypoints"]:
        waypoint.pop("frame_id", None)
    semantics_path.write_text(json.dumps(semantics), encoding="utf-8")

    projected_map = metric_map_from_bundle(bundle_dir)

    assert projected_map["frame_id"] == "operator_map"
    assert projected_map["robot_pose"]["frame_id"] == "operator_map"
    assert {room["source_map_frame_id"] for room in projected_map["rooms"]} == {"operator_map"}
    assert {waypoint["frame_id"] for waypoint in projected_map["inspection_waypoints"]} == {
        "operator_map"
    }


def test_nav2_validation_rejects_room_source_frame_drift(tmp_path: Path) -> None:
    bundle_dir = tmp_path / "bundle"
    agent_view = _agent_view()
    write_nav2_map_bundle(
        bundle_dir,
        metric_map=agent_view["metric_map"],
        static_landmarks=_static_landmarks(agent_view),
    )
    semantics_path = bundle_dir / "semantics.json"
    semantics = json.loads(semantics_path.read_text(encoding="utf-8"))
    semantics["frame_ids"]["map"] = "operator_map"
    semantics["spatial_contract"]["source_map_frame"]["frame_id"] = "operator_map"
    room_id = semantics["rooms"][0]["room_id"]
    semantics_path.write_text(json.dumps(semantics), encoding="utf-8")

    validation = validate_nav2_map_bundle(bundle_dir)

    assert validation.ok is False
    assert any(
        f"room source_map_frame_id must match semantics.json frame_ids.map: {room_id}" in error
        for error in validation.errors
    )


def test_nav2_validation_rejects_waypoint_frame_drift(tmp_path: Path) -> None:
    bundle_dir = tmp_path / "bundle"
    agent_view = _agent_view()
    write_nav2_map_bundle(
        bundle_dir,
        metric_map=agent_view["metric_map"],
        static_landmarks=_static_landmarks(agent_view),
    )
    semantics_path = bundle_dir / "semantics.json"
    semantics = json.loads(semantics_path.read_text(encoding="utf-8"))
    semantics["frame_ids"]["map"] = "operator_map"
    semantics["spatial_contract"]["source_map_frame"]["frame_id"] = "operator_map"
    for room in semantics["rooms"]:
        room["source_map_frame_id"] = "operator_map"
    semantics["inspection_waypoints"][0]["frame_id"] = "map"
    waypoint_id = semantics["inspection_waypoints"][0]["waypoint_id"]
    semantics_path.write_text(json.dumps(semantics), encoding="utf-8")

    validation = validate_nav2_map_bundle(bundle_dir)

    assert validation.ok is False
    assert any(
        f"inspection waypoint frame_id must match semantics.json frame_ids.map: {waypoint_id}"
        in error
        for error in validation.errors
    )


def test_checker_cli_reports_invalid_bundle_without_traceback(tmp_path: Path) -> None:
    invalid_bundle = tmp_path / "missing-scene-bundle"
    invalid_bundle.mkdir()

    result = subprocess.run(
        [_repo_python(), "-m", "roboclaws.maps.bundle", str(invalid_bundle)],
        cwd=REPO_ROOT,
        check=False,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 1
    assert "base-metric-map-v1-bundle invalid" in result.stderr
    assert "missing required artifact: map.yaml" in result.stderr
    assert "Traceback" not in result.stderr


def test_bundle_writer_normalizes_wide_room_only_static_landmarks(tmp_path: Path) -> None:
    agent_view = _wide_room_only_agent_view()
    bundle_dir = tmp_path / "molmospaces-procthor-val-0-7"

    write_nav2_map_bundle(
        bundle_dir,
        metric_map=agent_view["metric_map"],
        static_landmarks=_static_landmarks(agent_view),
    )

    validation = validate_nav2_map_bundle(bundle_dir)
    projected_map = metric_map_from_bundle(bundle_dir)
    static_landmarks = static_landmarks_from_bundle(bundle_dir)
    waypoints = projected_map["inspection_waypoints"]
    route = validate_metric_map_route(
        projected_map,
        static_landmarks,
        start_waypoint_id=str(waypoints[0]["waypoint_id"]),
        goal_waypoint_id=str(waypoints[-1]["waypoint_id"]),
    )
    semantics = json.loads((bundle_dir / "semantics.json").read_text(encoding="utf-8"))
    waypoint_by_id = {item["waypoint_id"]: item for item in semantics["inspection_waypoints"]}

    assert validation.ok, validation.as_dict()
    assert projected_map["width"] > agent_view["metric_map"]["width"]
    assert route.ok is True
    for fixture in semantics["static_landmarks"]:
        waypoint = waypoint_by_id[fixture["preferred_inspection_waypoint_id"]]
        pose = fixture["pose"]
        assert (pose["x"], pose["y"]) != (waypoint["x"], waypoint["y"])


def test_route_validation_blocks_occupied_goal(tmp_path: Path) -> None:
    agent_view = _wide_room_only_agent_view()
    metric_map = agent_view["metric_map"]
    static_landmarks = _static_landmarks(agent_view)
    first_fixture = static_landmarks[0]
    start_waypoint = dict(metric_map["inspection_waypoints"][0])
    start_waypoint["x"] = 1.5
    metric_map = dict(metric_map)
    metric_map["inspection_waypoints"] = [
        start_waypoint,
        *metric_map["inspection_waypoints"][1:],
    ]
    blocked_waypoint = dict(start_waypoint)
    blocked_waypoint["waypoint_id"] = "blocked_goal"
    blocked_waypoint["x"] = first_fixture["pose"]["x"]
    blocked_waypoint["y"] = first_fixture["pose"]["y"]
    metric_map["inspection_waypoints"] = [*metric_map["inspection_waypoints"], blocked_waypoint]

    result = validate_metric_map_route(
        metric_map,
        static_landmarks,
        start_waypoint_id=str(metric_map["inspection_waypoints"][0]["waypoint_id"]),
        goal_waypoint_id="blocked_goal",
    )

    assert result.ok is False
    assert result.status == "blocked_capability"
    assert result.failure_type == "goal_occupied"


def test_route_validation_rejects_invalid_metric_map_width() -> None:
    agent_view = _wide_room_only_agent_view()
    metric_map = dict(agent_view["metric_map"])
    metric_map["width"] = "wide"
    waypoints = metric_map["inspection_waypoints"]

    with pytest.raises(ValueError, match="metric_map.width must be an integer"):
        validate_metric_map_route(
            metric_map,
            _static_landmarks(agent_view),
            start_waypoint_id=str(waypoints[0]["waypoint_id"]),
            goal_waypoint_id=str(waypoints[-1]["waypoint_id"]),
        )


def test_nav2_bundle_writer_rejects_missing_metric_map_height(tmp_path: Path) -> None:
    agent_view = _agent_view()
    metric_map = dict(agent_view["metric_map"])
    metric_map.pop("height")

    with pytest.raises(ValueError, match="metric_map.height is required"):
        write_nav2_map_bundle(
            tmp_path / "bundle",
            metric_map=metric_map,
            static_landmarks=_static_landmarks(agent_view),
        )


def test_attach_nav2_bundle_snapshot_refuses_agent_view_authoring(tmp_path: Path) -> None:
    run_result = {"agent_view": _agent_view(), "artifacts": {}}

    with pytest.raises(ValueError, match="source_bundle_dir is required"):
        attach_nav2_map_bundle_snapshot(run_result=run_result, run_dir=tmp_path)

    assert "nav2_map_bundle" not in run_result
    assert not (tmp_path / "map_bundle").exists()


def test_realworld_contract_projects_from_selected_prebuilt_bundle() -> None:
    contract = HouseholdRuntimeContract(
        HouseholdBackendSession(build_cleanup_scenario(seed=7)),
        map_bundle_dir=CANONICAL_SCENE_BUNDLE,
    )

    metric_map = contract.metric_map()
    static_fixture_projection = contract.static_fixture_projection()
    waypoints = metric_map["inspection_waypoints"]
    semantics = json.loads((CANONICAL_SCENE_BUNDLE / "semantics.json").read_text(encoding="utf-8"))
    source_waypoints = semantics["inspection_waypoints"]
    navigation = contract.navigate_to_waypoint(str(waypoints[-1]["waypoint_id"]))

    assert metric_map["map_bundle"]["environment_id"] == "molmospaces-procthor-10k-val-0"
    assert metric_map["map_id"] == semantics["map_id"]
    assert metric_map["rooms"]
    assert all(room["room_label"] for room in metric_map["rooms"])
    assert all(item["visited"] is False for item in waypoints)
    assert static_fixture_projection["rooms"] == []
    assert [item["waypoint_id"] for item in waypoints] == [
        item["waypoint_id"] for item in source_waypoints
    ]
    assert waypoints[0]["waypoint_source"] == source_waypoints[0]["waypoint_source"]
    assert waypoints[0]["x"] == source_waypoints[0]["x"]
    assert waypoints[0]["y"] == source_waypoints[0]["y"]
    assert "fixture_ids" not in waypoints[0]
    assert metric_map["base_metric_map"]["source"] == "map_artifact_inspection_waypoints"
    assert navigation["navigation_backend"] == SIM_COSTMAP_PLANNER
    assert navigation["route_validation"]["ok"] is True
    assert navigation["route_validation"]["goal_waypoint_id"] == str(waypoints[-1]["waypoint_id"])


def test_realworld_contract_routes_across_b1_bundle_occupancy_grid(tmp_path: Path) -> None:
    contract = HouseholdRuntimeContract(
        HouseholdBackendSession(build_cleanup_scenario(seed=7)),
        map_bundle_dir=_b1_base_metric_bundle(tmp_path),
    )
    waypoints = contract.metric_map()["inspection_waypoints"]

    navigations = [
        contract.navigate_to_waypoint(str(waypoint["waypoint_id"])) for waypoint in waypoints[1:]
    ]

    assert all(navigation["ok"] is True for navigation in navigations)
    assert all(navigation["route_validation"]["ok"] is True for navigation in navigations)
    assert all(navigation["route_validation"]["path_cell_count"] > 1 for navigation in navigations)


def test_realworld_contract_observes_objects_from_selected_base_metric_bundle() -> None:
    contract = HouseholdRuntimeContract(
        HouseholdBackendSession(build_cleanup_scenario(seed=7)),
        map_bundle_dir=CANONICAL_SCENE_BUNDLE,
    )

    observation = _first_non_empty_observation(contract)
    metric_map = contract.metric_map()
    semantics = json.loads((CANONICAL_SCENE_BUNDLE / "semantics.json").read_text(encoding="utf-8"))

    assert semantics["static_landmarks"] == []
    assert observation["visible_object_detections"]
    assert metric_map["runtime_metric_map"]["observed_objects"]


def _agent_view() -> dict:
    contract = HouseholdRuntimeContract(
        HouseholdBackendSession(build_cleanup_scenario(seed=7)),
        map_bundle_dir=CANONICAL_SCENE_BUNDLE,
    )
    return {
        "metric_map": contract.metric_map(),
        "static_fixture_projection": contract.static_fixture_projection(),
    }


def _static_landmarks(agent_view: dict) -> list[dict]:
    return static_landmarks_from_fixture_projection(agent_view["static_fixture_projection"])


def _first_non_empty_observation(contract: HouseholdRuntimeContract) -> dict:
    for waypoint in contract.metric_map()["inspection_waypoints"]:
        contract.navigate_to_waypoint(str(waypoint["waypoint_id"]))
        observation = contract.observe()
        if observation["visible_object_detections"]:
            return observation
    raise AssertionError("expected at least one visible object detection")


def _b1_base_metric_bundle(tmp_path: Path) -> Path:
    from roboclaws.maps.b1_base_metric_map import (
        DEFAULT_LABELS,
        DEFAULT_MAP_BUNDLE,
        DEFAULT_ROOM_SEMANTICS,
        build_base_metric_map_bundle,
    )

    output_dir = tmp_path / "base-metric-map"
    build_base_metric_map_bundle(
        map_bundle=DEFAULT_MAP_BUNDLE,
        labels_path=DEFAULT_LABELS,
        room_semantics_path=DEFAULT_ROOM_SEMANTICS,
        output_dir=output_dir,
    )
    return output_dir


def _wide_room_only_agent_view() -> dict:
    rooms = []
    waypoints = []
    fixture_rooms = []
    room_count = 7
    for index in range(room_count):
        room_number = index + 2
        room_id = f"room_{room_number}"
        x0 = float(index * 3)
        room = {
            "room_id": room_id,
            "room_label": f"room {room_number}",
            "fixture_count": 1,
            "polygon": [
                {"x": x0, "y": 0.0},
                {"x": x0 + 2.0, "y": 0.0},
                {"x": x0 + 2.0, "y": 2.0},
                {"x": x0, "y": 2.0},
            ],
        }
        waypoint = {
            "waypoint_id": f"{room_id}_scan_1",
            "frame_id": "map",
            "x": x0 + 1.0,
            "y": 1.0,
            "yaw": 0.0,
            "room_id": room_id,
            "label": f"room {room_number} scan 1",
            "visited": False,
            "purpose": "fixture_coverage",
            "waypoint_source": "static_map_coverage",
            "coverage_estimate": 1.0,
        }
        rooms.append(room)
        waypoints.append(waypoint)
        fixture_rooms.append(
            {
                "room_id": room_id,
                "room_label": f"room {room_number}",
                "polygon": room["polygon"],
                "fixtures": [
                    {
                        "fixture_id": f"fixture_{room_number}",
                        "category": "CounterTop",
                        "name": f"Fixture {room_number}",
                        "room_id": room_id,
                        "affordances": ["place"],
                        "footprint": {"shape": "rectangle", "width_m": 0.55, "depth_m": 0.45},
                        "pose": {
                            "frame_id": "map",
                            "x": waypoint["x"],
                            "y": waypoint["y"],
                            "yaw": 0.0,
                        },
                        "preferred_inspection_waypoint_id": waypoint["waypoint_id"],
                        "preferred_manipulation_waypoint_id": waypoint["waypoint_id"],
                        "position_detail": "room_only",
                    }
                ],
            }
        )
    return {
        "metric_map": {
            "schema": "real_robot_map_bundle_v1",
            "frame_id": "map",
            "map_id": "molmospaces-procthor-val-0-7_base_metric_map",
            "map_version": "base-metric-map-v1",
            "resolution_m": 0.05,
            "origin": {"x": 0.0, "y": 0.0, "yaw": 0.0},
            "width": 240,
            "height": 180,
            "rooms": rooms,
            "inspection_waypoints": waypoints,
            "driveable_ways": [
                {
                    "from_room_id": f"room_{index + 2}",
                    "kind": "doorway",
                    "to_room_id": f"room_{index + 3}",
                }
                for index in range(room_count - 1)
            ],
        },
        "static_fixture_projection": {
            "schema": "static_fixture_projection_v1",
            "static_fixture_projection_mode": "room_only",
            "rooms": fixture_rooms,
        },
    }
