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
    _load_runtime_map_prior,
)
from roboclaws.household.scenario import build_cleanup_scenario
from roboclaws.maps.runtime_prior_artifact import runtime_metric_map_from_prior_artifact
from roboclaws.maps.runtime_prior_contracts import RUNTIME_MAP_PRIOR_SNAPSHOT_SCHEMA
from roboclaws.maps.runtime_prior_conversion import (
    runtime_prior_snapshot_from_agibot_navigation_memory,
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


def test_agibot_navigation_memory_converts_to_runtime_prior_snapshot_shape() -> None:
    snapshot = runtime_prior_snapshot_from_agibot_navigation_memory(ROBOT_MAP_12_FIXTURE)
    anchors = {item["source_anchor_id"]: item for item in snapshot["public_semantic_anchors"]}
    targets = materialize_runtime_prior_targets(snapshot)

    assert snapshot["schema"] == RUNTIME_MAP_PRIOR_SNAPSHOT_SCHEMA
    assert snapshot["runtime_metric_map"]["schema"] == "runtime_metric_map_v1"
    assert snapshot["producer"]["type"] == "offline_navigation_memory_conversion"
    assert snapshot["contract"]["online_offline_equivalent_shape"] is True
    assert snapshot["contract"]["private_truth_included"] is False
    assert snapshot["contract"]["source_map_mutated"] is False
    assert len(anchors) == 9
    assert set(anchors) == {
        "plastic_bottle_table_1",
        "long_table",
        "computer_monitor_1",
        "sink_kitchen_1",
        "fridge_main",
        "coffee_table_1",
        "kitchen_center",
        "large_white_sofa_1",
        "stone_book_decor_1",
    }
    assert len(snapshot["inspection_waypoints"]) == len(anchors)
    assert "anchor_sink_kitchen_1" in targets["actionable_fixture_ids"]
    assert "anchor_coffee_table_1" in targets["actionable_fixture_ids"]
    assert "anchor_fridge_main" not in targets["actionable_fixture_ids"]

    assert anchors["sink_kitchen_1"]["anchor_type"] == "receptacle"
    assert anchors["sink_kitchen_1"]["actionability"] == "actionable"
    assert "place_inside" in anchors["sink_kitchen_1"]["affordances"]
    assert anchors["coffee_table_1"]["anchor_type"] == "surface"
    assert anchors["coffee_table_1"]["actionability"] == "actionable"
    assert anchors["large_white_sofa_1"]["anchor_type"] == "surface"
    assert anchors["kitchen_center"]["anchor_type"] == "room_area"
    assert anchors["kitchen_center"]["room_label"] == "厨房/吧台区域"
    assert anchors["kitchen_center"]["materialization"]["waypoint"]["room_label"] == (
        "厨房/吧台区域"
    )
    rooms = {item["room_id"]: item for item in snapshot["runtime_metric_map"]["rooms"]}
    assert rooms["kitchen_center"]["room_label"] == "厨房/吧台区域"
    assert rooms["kitchen_center"]["category"] == "kitchen"
    assert snapshot["runtime_metric_map"]["room_category_hints"][0]["label"] == "厨房/吧台区域"
    assert snapshot["source_navigation_map"]["room_category_hints"][0]["label"] == "厨房/吧台区域"
    assert anchors["stone_book_decor_1"]["anchor_type"] == "landmark"
    assert anchors["stone_book_decor_1"]["actionability"] == "needs_review"

    fridge = anchors["fridge_main"]
    assert fridge["anchor_type"] == "receptacle"
    assert fridge["reachability_status"] == "costmap_disagrees"
    assert fridge["actionability"] == "costmap_disagrees"
    assert fridge["pose_source"] == "agibot_navigation_memory_nav_goal"
    assert fridge["pose_role"] == "nav_goal"
    assert fridge["localization_status"] == "target_pose_verified"
    assert fridge["object_pose_source"] == "agibot_navigation_memory_pose"
    assert fridge["object_pose"]
    assert fridge["materialization"]["waypoint"]["costmap_value"] == 0

    bottle = anchors["plastic_bottle_table_1"]
    assert bottle["anchor_type"] == "movable_object"
    assert bottle["actionability"] == "needs_confirm"
    assert bottle["promotion_status"] == "movable_prior_needs_current_run_confirmation"
    assert "anchor_plastic_bottle_table_1" not in targets["actionable_fixture_ids"]
    observed = {
        item["object_id"]: item for item in snapshot["runtime_metric_map"]["observed_objects"]
    }
    assert observed["plastic_bottle_table_1"]["actionability"] == "needs_confirm"
    assert observed["plastic_bottle_table_1"]["state"] == "prior"
    assert observed["plastic_bottle_table_1"]["candidate_fixture_id"] == ""
    _assert_no_forbidden_keys(snapshot)


def test_online_and_offline_snapshots_share_consumer_contract_shape() -> None:
    online_snapshot = _online_minimal_snapshot()
    offline_snapshot = runtime_prior_snapshot_from_agibot_navigation_memory(ROBOT_MAP_12_FIXTURE)

    for snapshot in (online_snapshot, offline_snapshot):
        assert snapshot["schema"] == RUNTIME_MAP_PRIOR_SNAPSHOT_SCHEMA
        assert set(snapshot) >= {
            "source_navigation_map",
            "runtime_metric_map",
            "public_semantic_anchors",
            "inspection_waypoints",
            "fixture_candidates",
            "producer",
            "contract",
        }
        assert snapshot["runtime_metric_map"]["schema"] == "runtime_metric_map_v1"
        assert snapshot["contract"]["private_truth_included"] is False
        assert snapshot["contract"]["source_map_mutated"] is False
        for anchor in snapshot["public_semantic_anchors"]:
            if anchor.get("pose"):
                assert anchor.get("pose_source"), anchor
                assert anchor.get("pose_role"), anchor
                assert anchor.get("localization_status"), anchor
        materialized = materialize_runtime_prior_targets(snapshot)
        assert materialized["schema"] == "runtime_map_prior_materialized_targets_v1"
        assert materialized["inspection_waypoints"]
        assert materialized["fixture_candidates"]
        assert materialized["actionable_waypoint_ids"]

    assert online_snapshot["producer"]["type"] == "online_map_build"
    assert offline_snapshot["producer"]["type"] == "offline_navigation_memory_conversion"


def test_materialized_online_snapshot_targets_do_not_override_destination_policy() -> None:
    contract = HouseholdRuntimeContract(
        HouseholdBackendSession(build_cleanup_scenario(seed=7)),
        perception_mode=RAW_FPV_ONLY_MODE,
        map_bundle_dir=CANONICAL_SCENE_BUNDLE,
    )
    contract.navigate_to_waypoint("room_4_inspection")
    observation = contract.observe()
    candidate = contract.navigate_to_visual_candidate(
        observation["raw_fpv_observation"]["observation_id"],
        category="tomato",
        evidence_note="round produce item on the desk",
        image_region={"type": "bbox", "value": [0.12, 0.24, 0.18, 0.16]},
        producer_type="test_agent",
        producer_id="test_agent",
    )
    assert candidate["ok"] is True
    online_snapshot = runtime_prior_snapshot_from_runtime_metric_map(
        contract.agent_view_payload()["runtime_metric_map"]
    )
    targets = materialize_runtime_prior_targets(online_snapshot)
    target_fixture = next(
        item
        for item in targets["fixture_candidates"]
        if item["category"] == "desk" and item["actionability"] == "actionable"
    )

    assert contract.pick(candidate["object_id"])["ok"] is True
    rejected = contract.navigate_to_receptacle(str(target_fixture["fixture_id"]))
    assert rejected["ok"] is False
    assert rejected["error_reason"] == "destination_policy_mismatch"
    assert rejected["fixture_category"] == "desk"
    assert contract.navigate_to_receptacle(candidate["candidate_fixture_id"])["ok"] is True


def test_converted_snapshot_targets_are_exposed_through_cleanup_receptacle_path() -> None:
    snapshot = runtime_prior_snapshot_from_agibot_navigation_memory(ROBOT_MAP_12_FIXTURE)
    contract = HouseholdRuntimeContract(
        HouseholdBackendSession(build_cleanup_scenario(seed=7)),
        perception_mode=RAW_FPV_ONLY_MODE,
        runtime_map_prior=snapshot["runtime_metric_map"],
        map_bundle_dir=CANONICAL_SCENE_BUNDLE,
    )
    public_receptacles = contract.public_receptacles_by_id()

    assert "anchor_fixture_006" in public_receptacles
    assert "anchor_fridge_main" not in public_receptacles
    assert public_receptacles["anchor_fixture_006"]["public_fixture_source"] == (
        "runtime_backend_fixture_overlay"
    )
    runtime_rooms = {
        item["room_id"]: item
        for item in contract.agent_view_payload()["runtime_metric_map"]["rooms"]
    }
    assert runtime_rooms["kitchen_center"]["room_label"] == "厨房/吧台区域"

    contract.navigate_to_waypoint("room_4_inspection")
    observation = contract.observe()
    candidate = contract.navigate_to_visual_candidate(
        observation["raw_fpv_observation"]["observation_id"],
        category="tomato",
        target_fixture_id="anchor_fixture_006",
        evidence_note="round produce item on the desk",
        image_region={"type": "bbox", "value": [0.12, 0.24, 0.18, 0.16]},
        producer_type="test_agent",
        producer_id="test_agent",
    )

    assert candidate["ok"] is True
    assert contract.pick(candidate["object_id"])["ok"] is True
    assert contract.navigate_to_receptacle("anchor_fixture_006")["ok"] is True
    assert contract.navigate_to_receptacle("anchor_fridge_main")["error_reason"] == (
        "stale_reference"
    )


def test_runtime_prior_snapshot_rejects_private_truth_keys() -> None:
    runtime_map = _online_minimal_snapshot()["runtime_metric_map"]
    runtime_map["private_manifest"] = {"target_count": 1}

    with pytest.raises(ValueError, match="private truth keys"):
        runtime_prior_snapshot_from_runtime_metric_map(runtime_map)


def test_runtime_map_prior_loader_accepts_raw_runtime_map_and_snapshot(tmp_path: Path) -> None:
    online_snapshot = _online_minimal_snapshot()
    raw_path = tmp_path / "runtime_metric_map.json"
    snapshot_path = tmp_path / "runtime_map_prior_snapshot.json"
    raw_path.write_text(json.dumps(online_snapshot["runtime_metric_map"]), encoding="utf-8")
    snapshot_path.write_text(json.dumps(online_snapshot), encoding="utf-8")

    raw_loaded = _load_runtime_map_prior(raw_path)
    snapshot_loaded = _load_runtime_map_prior(snapshot_path)

    assert raw_loaded == online_snapshot["runtime_metric_map"]
    assert snapshot_loaded == online_snapshot["runtime_metric_map"]
    assert (
        runtime_metric_map_from_prior_artifact(online_snapshot)
        == (online_snapshot["runtime_metric_map"])
    )


def test_runtime_map_prior_loader_rejects_unknown_raw_schema(tmp_path: Path) -> None:
    prior_path = tmp_path / "runtime_metric_map.json"
    prior_path.write_text('{"schema": "wrong"}\n', encoding="utf-8")

    with pytest.raises(
        ValueError,
        match="runtime map prior artifact must be raw runtime_metric_map_v1",
    ):
        _load_runtime_map_prior(prior_path)


def test_runtime_map_prior_loader_rejects_snapshot_with_invalid_runtime_map() -> None:
    with pytest.raises(
        ValueError,
        match="runtime map prior snapshot runtime_metric_map must use schema runtime_metric_map_v1",
    ):
        runtime_metric_map_from_prior_artifact(
            {
                "schema": RUNTIME_MAP_PRIOR_SNAPSHOT_SCHEMA,
                "runtime_metric_map": {"schema": "wrong"},
            }
        )


def test_agibot_navigation_memory_rejects_non_object_navigation_memory(tmp_path: Path) -> None:
    map_dir = _copy_agibot_runtime_prior_fixture(tmp_path)
    (map_dir / "navigation_memory.json").write_text("[]\n", encoding="utf-8")

    with pytest.raises(
        ValueError,
        match=r"Agibot navigation memory must contain a JSON object at .*navigation_memory\.json",
    ):
        runtime_prior_snapshot_from_agibot_navigation_memory(map_dir)


def test_agibot_navigation_memory_accepts_catalog_navigation_memory_items(
    tmp_path: Path,
) -> None:
    map_dir = _copy_agibot_runtime_prior_fixture(tmp_path)
    navigation_memory_path = map_dir / "navigation_memory.json"
    navigation_memory = json.loads(navigation_memory_path.read_text(encoding="utf-8"))
    items = navigation_memory.pop("items")
    navigation_memory["catalog"] = {"navigation_memory": items}
    navigation_memory_path.write_text(json.dumps(navigation_memory), encoding="utf-8")

    snapshot = runtime_prior_snapshot_from_agibot_navigation_memory(map_dir)

    assert snapshot["summary"]["anchor_count"] == 9


@pytest.mark.parametrize(
    ("navigation_memory", "expected_error"),
    [
        (
            {},
            "Agibot navigation memory must contain a non-empty items list "
            "or catalog.navigation_memory list",
        ),
        (
            {"items": {}},
            "Agibot navigation memory items must be a non-empty list",
        ),
        (
            {"items": []},
            "Agibot navigation memory items must be a non-empty list",
        ),
        (
            {"catalog": {"navigation_memory": {}}},
            "Agibot navigation memory catalog.navigation_memory must be a non-empty list",
        ),
        (
            {"catalog": {"navigation_memory": []}},
            "Agibot navigation memory catalog.navigation_memory must be a non-empty list",
        ),
        (
            {"items": [[]]},
            "Agibot navigation memory item 1 must be a JSON object",
        ),
    ],
)
def test_agibot_navigation_memory_rejects_missing_or_empty_item_sources(
    tmp_path: Path,
    navigation_memory: dict,
    expected_error: str,
) -> None:
    map_dir = _copy_agibot_runtime_prior_fixture(tmp_path)
    navigation_memory_path = map_dir / "navigation_memory.json"
    navigation_memory_path.write_text(json.dumps(navigation_memory), encoding="utf-8")

    with pytest.raises(ValueError, match=expected_error):
        runtime_prior_snapshot_from_agibot_navigation_memory(map_dir)


def test_agibot_navigation_memory_rejects_malformed_source_json(tmp_path: Path) -> None:
    map_dir = _copy_agibot_runtime_prior_fixture(tmp_path)
    (map_dir / "agibot" / "source.json").write_text("{not-json\n", encoding="utf-8")

    with pytest.raises(
        ValueError,
        match=r"Agibot map source must contain valid JSON object: .*source\.json",
    ):
        runtime_prior_snapshot_from_agibot_navigation_memory(map_dir)


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
