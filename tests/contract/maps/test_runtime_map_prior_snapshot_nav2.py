from __future__ import annotations

import importlib.util
import json
import shutil
from pathlib import Path

import pytest

from roboclaws.household.household_backend_contract import HouseholdBackendSession
from roboclaws.household.household_runtime_contract import (
    RAW_FPV_ONLY_MODE,
    HouseholdRuntimeContract,
)
from roboclaws.household.household_world_episode import (
    run_household_world_episode,
)
from roboclaws.household.scenario import build_cleanup_scenario
from roboclaws.maps.runtime_prior_artifact import runtime_metric_map_from_prior_artifact
from roboclaws.maps.runtime_prior_contracts import RUNTIME_MAP_PRIOR_SNAPSHOT_SCHEMA
from roboclaws.maps.runtime_prior_conversion import (
    runtime_prior_snapshot_from_agibot_navigation_memory,
    runtime_prior_snapshot_from_nav2_cleanup_bundle,
)
from roboclaws.maps.runtime_prior_materialization import materialize_runtime_prior_targets
from roboclaws.maps.runtime_prior_snapshot import runtime_prior_snapshot_from_runtime_metric_map
from roboclaws.maps.spatial_contract import source_frame_spatial_contract

REPO_ROOT = Path(__file__).resolve().parents[3]
ROBOT_MAP_12_FIXTURE = REPO_ROOT / "tests" / "fixtures" / "runtime_map_prior" / "robot_map_12"
CANONICAL_SCENE_BUNDLE = REPO_ROOT / "assets" / "maps" / "molmospaces" / "procthor-10k-val" / "0"
CONVERTER_PATH = REPO_ROOT / "scripts" / "maps" / "convert_agibot_navigation_memory.py"
NAV2_BUNDLE_CONVERTER_PATH = REPO_ROOT / "scripts" / "maps" / "convert_nav2_cleanup_bundle.py"
FORBIDDEN_PRIVATE_KEYS = {
    "acceptable_destination_sets",
    "generated_mess_set",
    "global_movable_object_inventory",
    "is_misplaced",
    "private_manifest",
    "target_count",
    "target_receptacle_id",
    "valid_receptacle_ids",
}


def test_nav2_cleanup_bundle_rejects_non_object_semantics(tmp_path: Path) -> None:
    bundle_dir = _write_minimal_nav2_cleanup_bundle(tmp_path / "bundle")
    (bundle_dir / "semantics.json").write_text("[]\n", encoding="utf-8")

    with pytest.raises(
        ValueError,
        match=r"Nav2 cleanup semantics source must contain a JSON object: .*semantics\.json",
    ):
        runtime_prior_snapshot_from_nav2_cleanup_bundle(bundle_dir)


@pytest.mark.parametrize(
    ("inspection_waypoints", "expected_error"),
    [
        (
            None,
            "Nav2 cleanup semantics inspection_waypoints must be a non-empty list",
        ),
        (
            {},
            "Nav2 cleanup semantics inspection_waypoints must be a non-empty list",
        ),
        (
            [],
            "Nav2 cleanup semantics inspection_waypoints must be a non-empty list",
        ),
        (
            [[]],
            "Nav2 cleanup waypoint 1 must be a JSON object",
        ),
    ],
)
def test_nav2_cleanup_bundle_rejects_missing_or_empty_waypoint_sources(
    tmp_path: Path,
    inspection_waypoints: object,
    expected_error: str,
) -> None:
    bundle_dir = _write_minimal_nav2_cleanup_bundle(tmp_path / "bundle")
    semantics_path = bundle_dir / "semantics.json"
    semantics = json.loads(semantics_path.read_text(encoding="utf-8"))
    if inspection_waypoints is None:
        semantics.pop("inspection_waypoints")
    else:
        semantics["inspection_waypoints"] = inspection_waypoints
    semantics_path.write_text(json.dumps(semantics), encoding="utf-8")

    with pytest.raises(ValueError, match=expected_error):
        runtime_prior_snapshot_from_nav2_cleanup_bundle(bundle_dir)


@pytest.mark.parametrize(
    ("map_yaml", "expected_error"),
    [
        (
            ["image: map.pgm", "origin: [0, 0, 0]"],
            "Nav2 cleanup map.yaml resolution must be a positive finite number",
        ),
        (
            ["image: map.pgm", "resolution: 0.05"],
            "Nav2 cleanup map.yaml origin must be a 3-item numeric list",
        ),
        (
            ["image: map.pgm", "resolution: 0.05", "origin: [0, 0]"],
            "Nav2 cleanup map.yaml origin must be a 3-item numeric list",
        ),
    ],
)
def test_nav2_cleanup_bundle_rejects_malformed_map_yaml_geometry(
    tmp_path: Path,
    map_yaml: list[str],
    expected_error: str,
) -> None:
    bundle_dir = _write_minimal_nav2_cleanup_bundle(tmp_path / "bundle")
    (bundle_dir / "map.yaml").write_text("\n".join([*map_yaml, ""]), encoding="utf-8")

    with pytest.raises(ValueError, match=expected_error):
        runtime_prior_snapshot_from_nav2_cleanup_bundle(bundle_dir)


def test_agibot_navigation_memory_rejects_malformed_nav2_yaml_geometry(tmp_path: Path) -> None:
    map_dir = _copy_agibot_runtime_prior_fixture(tmp_path)
    (map_dir / "agibot" / "nav2.yaml").write_text(
        "\n".join(["image: occupancy.pgm", "resolution: 0.05", "origin: [0, 0]", ""]),
        encoding="utf-8",
    )

    with pytest.raises(
        ValueError,
        match="Agibot nav2.yaml origin must be a 3-item numeric list",
    ):
        runtime_prior_snapshot_from_agibot_navigation_memory(map_dir)


@pytest.mark.parametrize(
    ("case", "expected_error"),
    [
        (
            "missing_x",
            "Agibot navigation memory item plastic_bottle_table_1 nav_goal x "
            "must be a finite number",
        ),
        (
            "malformed_x",
            "Agibot navigation memory item plastic_bottle_table_1 nav_goal x "
            "must be a finite number",
        ),
        (
            "none",
            "Agibot navigation memory item plastic_bottle_table_1 nav_goal "
            "must be an object with x, y, and yaw",
        ),
        (
            "list",
            "Agibot navigation memory item plastic_bottle_table_1 nav_goal "
            "must be an object with x, y, and yaw",
        ),
    ],
)
def test_agibot_navigation_memory_rejects_invalid_nav_goal_geometry(
    tmp_path: Path,
    case: str,
    expected_error: str,
) -> None:
    map_dir = _copy_agibot_runtime_prior_fixture(tmp_path)
    navigation_memory_path = map_dir / "navigation_memory.json"
    navigation_memory = json.loads(navigation_memory_path.read_text(encoding="utf-8"))
    navigation_memory["items"][0]["nav_goal"] = _invalid_nav_goal(
        navigation_memory["items"][0]["nav_goal"],
        case,
    )
    navigation_memory_path.write_text(json.dumps(navigation_memory), encoding="utf-8")

    with pytest.raises(ValueError, match=expected_error):
        runtime_prior_snapshot_from_agibot_navigation_memory(map_dir)


@pytest.mark.parametrize(
    ("field", "malformed_value"),
    [
        ("x", None),
        ("y", None),
        ("yaw", None),
        ("x", "not-a-number"),
    ],
)
def test_nav2_cleanup_bundle_rejects_invalid_waypoint_geometry(
    tmp_path: Path,
    field: str,
    malformed_value: object,
) -> None:
    bundle_dir = _write_minimal_nav2_cleanup_bundle(tmp_path / "bundle")
    semantics_path = bundle_dir / "semantics.json"
    semantics = json.loads(semantics_path.read_text(encoding="utf-8"))
    if malformed_value is None:
        semantics["inspection_waypoints"][0].pop(field)
    else:
        semantics["inspection_waypoints"][0][field] = malformed_value
    semantics_path.write_text(json.dumps(semantics), encoding="utf-8")

    with pytest.raises(
        ValueError,
        match=rf"Nav2 cleanup waypoint room_a_center {field} must be a finite number",
    ):
        runtime_prior_snapshot_from_nav2_cleanup_bundle(bundle_dir)


def test_agibot_navigation_memory_converter_script_writes_snapshot_and_summary(
    tmp_path: Path,
) -> None:
    converter = _load_module(CONVERTER_PATH, "convert_agibot_navigation_memory")
    output = tmp_path / "runtime_map_prior_snapshot.json"
    summary = tmp_path / "materialized_targets.json"

    converter.main(
        [str(ROBOT_MAP_12_FIXTURE), "--output", str(output), "--summary-json", str(summary)]
    )

    snapshot = json.loads(output.read_text(encoding="utf-8"))
    targets = json.loads(summary.read_text(encoding="utf-8"))

    assert snapshot["schema"] == RUNTIME_MAP_PRIOR_SNAPSHOT_SCHEMA
    assert snapshot["producer"]["type"] == "offline_navigation_memory_conversion"
    assert "anchor_sink_kitchen_1" in targets["actionable_fixture_ids"]
    assert "anchor_plastic_bottle_table_1" not in targets["actionable_fixture_ids"]


def test_nav2_cleanup_bundle_converts_to_runtime_prior_snapshot_shape(tmp_path: Path) -> None:
    bundle_dir = _write_minimal_nav2_cleanup_bundle(tmp_path / "bundle")

    snapshot = runtime_prior_snapshot_from_nav2_cleanup_bundle(bundle_dir)
    targets = materialize_runtime_prior_targets(snapshot)

    assert snapshot["schema"] == RUNTIME_MAP_PRIOR_SNAPSHOT_SCHEMA
    assert snapshot["producer"]["type"] == "offline_nav2_cleanup_bundle_conversion"
    assert snapshot["source_navigation_map"]["source_type"] == "nav2_cleanup_bundle"
    assert snapshot["runtime_metric_map"]["schema"] == "runtime_metric_map_v1"
    robot_proof = snapshot["runtime_metric_map"]["digital_twin_capabilities"][
        "robot_consumption_proof"
    ]
    assert robot_proof["robot_navigation_supported"] is True
    assert snapshot["contract"]["online_offline_equivalent_shape"] is True
    assert snapshot["contract"]["private_truth_included"] is False
    assert targets["actionable_waypoint_ids"] == ["room_a_center"]
    assert targets["fixture_candidates"] == []
    assert (
        targets["digital_twin_capabilities"]["robot_consumption_proof"][
            "robot_navigation_supported"
        ]
        is True
    )
    assert (
        targets["digital_twin_capabilities"]["render_observation_proof"][
            "render_observation_supported"
        ]
        is True
    )
    assert targets["capability_summary"]["robot_navigation_supported"] is True
    assert targets["capability_summary"]["render_observation_supported"] is True
    assert targets["capability_summary"]["same_pose_fpv_supported"] is True
    assert targets["capability_summary"]["same_pose_chase_supported"] is True
    assert targets["capability_summary"]["same_pose_topdown_supported"] is True
    assert targets["capability_summary"]["default_visual_route_status"] == (
        "blocked_missing_verified_b1_floor2_slow_render_proof"
    )
    assert targets["capability_summary"]["default_visual_route_selected"] is False
    assert targets["capability_summary"]["room_semantics_supported"] is False
    assert runtime_metric_map_from_prior_artifact(snapshot) == snapshot["runtime_metric_map"]
    _assert_no_forbidden_keys(snapshot)


def test_nav2_cleanup_bundle_converter_script_writes_snapshot_and_summary(
    tmp_path: Path,
) -> None:
    converter = _load_module(NAV2_BUNDLE_CONVERTER_PATH, "convert_nav2_cleanup_bundle")
    bundle_dir = _write_minimal_nav2_cleanup_bundle(tmp_path / "bundle")
    output = tmp_path / "runtime_map_prior_snapshot.json"
    summary = tmp_path / "materialized_targets.json"

    converter.main([str(bundle_dir), "--output", str(output), "--summary-json", str(summary)])

    snapshot = json.loads(output.read_text(encoding="utf-8"))
    targets = json.loads(summary.read_text(encoding="utf-8"))
    assert snapshot["schema"] == RUNTIME_MAP_PRIOR_SNAPSHOT_SCHEMA
    assert snapshot["producer"]["type"] == "offline_nav2_cleanup_bundle_conversion"
    assert targets["actionable_waypoint_ids"] == ["room_a_center"]


def test_synthetic_cleanup_consumes_converted_snapshot_through_runtime_prior(
    tmp_path: Path,
) -> None:
    snapshot = runtime_prior_snapshot_from_agibot_navigation_memory(ROBOT_MAP_12_FIXTURE)
    prior_path = tmp_path / "runtime_map_prior_snapshot.json"
    prior_path.write_text(json.dumps(snapshot), encoding="utf-8")

    result = run_household_world_episode(
        output_dir=tmp_path / "cleanup",
        seed=7,
        runtime_map_prior_path=prior_path,
        map_bundle_dir=CANONICAL_SCENE_BUNDLE,
    )

    prior_rows = [
        item
        for item in result["runtime_metric_map"]["observed_objects"]
        if item["freshness"] == "prior"
    ]
    assert result["runtime_metric_map_prior"]["loaded"] is True
    assert result["runtime_metric_map_prior"]["source_provided"] is True
    assert result["runtime_metric_map_prior"]["source"] == str(prior_path)
    assert result["runtime_metric_map_prior"]["observed_object_count"] == 1
    assert result["runtime_metric_map_prior"]["object_prior_count"] == 1
    assert result["runtime_metric_map_prior"]["anchor_prior_count"] >= 1
    assert {item["object_id"] for item in prior_rows} == {"plastic_bottle_table_1"}
    assert all(item["actionability"] == "needs_confirm" for item in prior_rows)
    assert all(item["state"] == "prior" for item in prior_rows)
    assert result["policy_uses_private_truth"] is False
    assert result["planner_uses_private_manifest"] is False
    _assert_no_forbidden_keys(result["agent_view"])


def _online_minimal_snapshot() -> dict:
    contract = HouseholdRuntimeContract(
        HouseholdBackendSession(build_cleanup_scenario(seed=7)),
        map_bundle_dir=CANONICAL_SCENE_BUNDLE,
    )
    _observe_until_anchor(contract, anchor_category="fridge", anchor_type="receptacle")
    return runtime_prior_snapshot_from_runtime_metric_map(
        contract.agent_view_payload()["runtime_metric_map"],
        source_navigation_map=contract.metric_map(),
    )


def _copy_agibot_runtime_prior_fixture(tmp_path: Path) -> Path:
    map_dir = tmp_path / "robot_map_12"
    shutil.copytree(ROBOT_MAP_12_FIXTURE, map_dir)
    return map_dir


def _write_minimal_nav2_cleanup_bundle(bundle_dir: Path) -> Path:
    bundle_dir.mkdir(parents=True)
    (bundle_dir / "map.yaml").write_text(
        "\n".join(
            [
                "image: map.pgm",
                "resolution: 0.05",
                "origin: [0, 0, 0]",
                "negate: 0",
                "occupied_thresh: 0.65",
                "free_thresh: 0.196",
                "",
            ]
        ),
        encoding="utf-8",
    )
    (bundle_dir / "map.pgm").write_text(
        "\n".join(["P2", "2 2", "255", "0 0", "0 0", ""]),
        encoding="ascii",
    )
    semantics = {
        "schema": "nav2_cleanup_semantics_v1",
        "environment_id": "test-b1-map12",
        "map_id": "test-b1-map12_base_metric_map",
        "frame_ids": {"map": "map", "base": "base_link", "camera": "camera"},
        "spatial_contract": source_frame_spatial_contract(frame_id="map"),
        "display_frame": None,
        "rooms": [
            {
                "room_id": "room_a",
                "room_label": "Room A",
                "category": "meeting_room",
                "polygon": [
                    {"x": 0.0, "y": 0.0},
                    {"x": 1.0, "y": 0.0},
                    {"x": 1.0, "y": 1.0},
                ],
            }
        ],
        "room_category_hints": [
            {
                "room_id": "room_a",
                "room_label": "Room A",
                "category": "meeting_room",
            }
        ],
        "inspection_waypoints": [
            {
                "waypoint_id": "room_a_center",
                "frame_id": "map",
                "x": 0.5,
                "y": 0.5,
                "yaw": 0.0,
                "room_id": "room_a",
                "label": "Room A",
                "waypoint_source": "generated_exploration_candidate",
            }
        ],
        "driveable_ways": [{"from_room_id": "room_a", "to_room_id": "room_a"}],
        "digital_twin_capabilities": {
            "robot_consumption_proof": {
                "status": "robot_navigation_verified",
                "robot_navigation_supported": True,
                "manipulation_supported": False,
            },
            "room_semantic_projection_proof": {
                "status": "blocked_missing_accepted_semantic_anchors",
                "room_semantics_supported": False,
                "object_semantics_supported": False,
                "object_projection_status": "blocked_until_object_semantic_anchors",
            },
            "render_observation_proof": {
                "status": "same_pose_render_observation_verified",
                "render_observation_supported": True,
                "same_pose_fpv_supported": True,
                "same_pose_chase_supported": True,
                "same_pose_topdown_supported": True,
                "default_visual_route": {
                    "scene_id": "B1_floor2_slow",
                    "scene_root": "data/robot-data-lab/scene-engine/data/B1_floor2_slow",
                    "selected": False,
                    "status": "blocked_missing_verified_b1_floor2_slow_render_proof",
                },
            },
        },
        "provenance": {
            "source": "test_nav2_cleanup_bundle",
            "contains_private_scoring_truth": False,
            "contains_runtime_observations": False,
        },
    }
    (bundle_dir / "semantics.json").write_text(json.dumps(semantics), encoding="utf-8")
    return bundle_dir


def _observe_until_anchor(
    contract: HouseholdRuntimeContract,
    *,
    anchor_category: str,
    anchor_type: str,
) -> None:
    for waypoint in contract.metric_map()["inspection_waypoints"]:
        contract.navigate_to_waypoint(str(waypoint["waypoint_id"]))
        observation = contract.observe()
        if contract.perception_mode == RAW_FPV_ONLY_MODE and anchor_category == "fridge":
            contract.navigate_to_visual_candidate(
                observation["raw_fpv_observation"]["observation_id"],
                category="tomato",
                evidence_note="round produce item on the desk",
                image_region={"type": "bbox", "value": [0.12, 0.24, 0.18, 0.16]},
                producer_type="test_agent",
                producer_id="test_agent",
            )
        anchors = contract.agent_view_payload()["runtime_metric_map"]["public_semantic_anchors"]
        if any(
            item.get("category") == anchor_category and item.get("anchor_type") == anchor_type
            for item in anchors
        ):
            return
    raise AssertionError(f"missing {anchor_category} {anchor_type} anchor")


def _assert_no_forbidden_keys(value: object) -> None:
    hits: set[str] = set()
    _collect_forbidden_keys(value, hits)
    assert hits == set()


def _collect_forbidden_keys(value: object, hits: set[str]) -> None:
    if isinstance(value, dict):
        for key, item in value.items():
            if str(key) in FORBIDDEN_PRIVATE_KEYS:
                hits.add(str(key))
            _collect_forbidden_keys(item, hits)
    elif isinstance(value, list):
        for item in value:
            _collect_forbidden_keys(item, hits)


def _invalid_nav_goal(nav_goal: dict, case: str) -> object:
    if case == "none":
        return None
    if case == "list":
        return []
    result = dict(nav_goal)
    _, field = case.split("_", 1)
    if case.startswith("missing_"):
        result.pop(field)
    else:
        result[field] = "not-a-number"
    return result


def _load_module(path: Path, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module
