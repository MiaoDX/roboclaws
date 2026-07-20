from __future__ import annotations

import json
import math
from pathlib import Path
from types import SimpleNamespace

from PIL import Image

from roboclaws.household import agent_view as agent_view_module
from roboclaws.household import (
    realworld_done_readiness,
    realworld_runtime_map_targets,
    realworld_visual_candidate_declarations,
    realworld_visual_candidate_lifecycle,
)
from roboclaws.household.backend_contract import CleanupBackendSession
from roboclaws.household.realworld_contract import (
    CAMERA_MODEL_POLICY_MODE,
    CAMERA_MODEL_POLICY_SCHEMA,
    CLEANUP_WORKLIST_SCHEMA,
    DONE_READINESS_POLICY_EXPLICIT,
    DONE_READINESS_POLICY_RAW_FPV,
    RAW_FPV_ONLY_MODE,
    REAL_ROBOT_MAP_BUNDLE_SCHEMA,
    REALWORLD_CONTRACT,
    RUNTIME_METRIC_MAP_SCHEMA,
    SANITIZED_VISIBLE_OBJECT_DETECTIONS_POLICY,
    SANITIZED_VISIBLE_OBJECT_DETECTIONS_PROVENANCE,
    SIMULATED_CAMERA_MODEL_PROVENANCE,
    VISUAL_CANDIDATE_ALREADY_HANDLED_REASON,
    VISUAL_GROUNDING_CATEGORY_HINTS,
    RealWorldCleanupContract,
    _declared_category_matches_object,
    cleanup_policy_trace_from_events,
    forbidden_agent_view_keys,
)
from roboclaws.household.scenario import build_cleanup_scenario
from roboclaws.household.subprocess_backend import MOLMOSPACES_SUBPROCESS_BACKEND
from roboclaws.household.target_query import resolve_target_query
from roboclaws.household.types import (
    CleanupObject,
    CleanupReceptacle,
    CleanupScenario,
    PrivateScoringManifest,
    TargetRule,
)
from roboclaws.household.visual_grounding import VISUAL_GROUNDING_RESPONSE_SCHEMA
from roboclaws.maps.bundle import static_landmarks_from_fixture_projection
from roboclaws.maps.route import validate_metric_map_route

REPO_ROOT = Path(__file__).resolve().parents[3]
PREBUILT_BUNDLE = REPO_ROOT / "assets" / "maps" / "molmospaces" / "procthor-10k-val" / "0"


def _contract(
    session: CleanupBackendSession,
    **kwargs: object,
) -> RealWorldCleanupContract:
    kwargs.setdefault("map_bundle_dir", PREBUILT_BUNDLE)
    return RealWorldCleanupContract(session, **kwargs)


def test_visual_candidate_exact_category_matching_does_not_cross_broad_family() -> None:
    plate = CleanupObject("plate_01", "Plate", "Plate", "table_01")
    mug = CleanupObject("mug_01", "ceramic mug", "dish", "sofa_01")
    ladle = CleanupObject("ladle_01", "Ladle", "Ladle", "counter_01")

    assert _declared_category_matches_object("plate", plate) is True
    assert _declared_category_matches_object("dish", plate) is True
    assert _declared_category_matches_object("cup", plate) is False
    assert _declared_category_matches_object("plate", mug) is False
    assert _declared_category_matches_object("dish", mug) is True
    assert _declared_category_matches_object("spoon", ladle) is True


class _PoseRecordingBackend:
    def __init__(self, scenario: CleanupScenario) -> None:
        self.scenario = scenario
        self._locations = scenario.object_locations()
        self.current_receptacle_id = ""
        self.navigation_targets: list[str] = []
        self.view_poses: list[dict[str, object]] = []
        self.robot_view_camera_offsets: list[dict[str, float]] = []

    def object_locations(self) -> dict[str, str]:
        return dict(self._locations)

    def navigate_to_receptacle(self, receptacle_id: str) -> dict[str, object]:
        self.current_receptacle_id = receptacle_id
        self.navigation_targets.append(receptacle_id)
        return {"ok": True, "tool": "navigate_to_receptacle", "status": "ok"}

    def write_robot_views(
        self,
        output_dir: Path,
        *,
        label: str,
        focus_object_id: str | None = None,
        focus_receptacle_id: str | None = None,
        camera_yaw_offset_deg: float = 0.0,
        camera_pitch_offset_deg: float = 0.0,
    ) -> dict[str, object]:
        del focus_object_id, focus_receptacle_id
        self.robot_view_camera_offsets.append(
            {
                "yaw_delta_deg": camera_yaw_offset_deg,
                "pitch_delta_deg": camera_pitch_offset_deg,
            }
        )
        output_dir.mkdir(parents=True, exist_ok=True)
        current = self.current_receptacle_id or "unknown"
        views = {}
        for key in ("fpv", "chase", "topdown", "verify"):
            path = output_dir / f"{label}.{current}.{key}.png"
            path.write_bytes(b"fake png")
            views[key] = str(path)
        pose = {"receptacle_id": current}
        self.view_poses.append(pose)
        return {
            "ok": True,
            "robot_pose": pose,
            "robot_trajectory": [pose],
            "view_variant": "test-fpv-topdown-chase-verify",
            "views": views,
        }


class _RelativePoseBackend(_PoseRecordingBackend):
    def __init__(self, scenario: CleanupScenario) -> None:
        super().__init__(scenario)
        self.relative_pose_calls: list[dict[str, float]] = []

    def navigate_to_relative_pose(
        self,
        *,
        forward_m: float = 0.0,
        lateral_m: float = 0.0,
        yaw_delta_deg: float = 0.0,
    ) -> dict[str, object]:
        delta = {
            "forward_m": forward_m,
            "lateral_m": lateral_m,
            "yaw_delta_deg": yaw_delta_deg,
        }
        self.relative_pose_calls.append(delta)
        return {
            "ok": True,
            "tool": "navigate_to_relative_pose",
            "status": "ok",
            "primitive_provenance": "api_semantic",
            "robot_pose": {
                "x": 1.25,
                "y": 2.0,
                "pose_source": "relative_robot_frame",
                "target_receptacle_id": "sink_private_001",
            },
            "applied_forward_m": forward_m,
            "applied_lateral_m": lateral_m,
            "applied_yaw_delta_deg": yaw_delta_deg,
            "clamped": False,
        }


def test_realworld_contract_defaults_to_base_metric_map() -> None:
    contract = _contract(CleanupBackendSession(build_cleanup_scenario(seed=7)))

    metric_map = contract.metric_map()
    static_fixture_projection = contract.static_fixture_projection()

    assert metric_map["base_metric_map"]["enabled"] is True
    assert metric_map["rooms"]
    assert all(room["room_label"] for room in metric_map["rooms"])
    assert static_fixture_projection["rooms"] == []


def test_realworld_contract_requires_map_bundle_without_synthetic_opt_in() -> None:
    try:
        RealWorldCleanupContract(CleanupBackendSession(build_cleanup_scenario(seed=7)))
    except ValueError as exc:
        assert "map_bundle_dir is required for product runtime base inspection_waypoints" in str(
            exc
        )
    else:
        raise AssertionError("expected product runtime to reject missing map bundle")


def test_realworld_public_tools_do_not_expose_private_targets_or_global_inventory() -> None:
    contract = _contract(CleanupBackendSession(build_cleanup_scenario(seed=7)))

    metric_map = contract.metric_map()
    static_fixture_projection = contract.static_fixture_projection()
    observation = _first_non_empty_observation(contract)

    assert metric_map["contract"] == REALWORLD_CONTRACT
    assert "objects" not in metric_map
    assert "objects" not in static_fixture_projection
    assert observation["private_target_truth_included"] is False
    assert observation["visible_object_detections"]
    assert observation["visible_fixture_detections"]
    for fixture in observation["visible_fixture_detections"]:
        assert fixture["fixture_id"] == fixture["anchor_id"]
        assert fixture["fixture_id"].startswith("anchor_fixture_")
    serialized_observation = json.dumps(observation)
    assert not any(fixture_id in serialized_observation for fixture_id in contract._fixtures)
    fixture_navigation = contract.navigate_to_receptacle(
        observation["visible_fixture_detections"][0]["fixture_id"]
    )
    assert fixture_navigation["error_reason"] == "semantic_order"
    assert fixture_navigation["required_tool"] == "pick"
    for detection in observation["visible_object_detections"]:
        assert detection["object_id"].startswith("observed_")
        assert "support_estimate" in detection
        assert detection["destination_policy_status"] == "policy_required"
        assert "destination_policy" in detection
        assert "target_receptacle_id" not in detection
        assert "is_misplaced" not in detection
    _assert_no_forbidden_keys(metric_map)
    _assert_no_forbidden_keys(static_fixture_projection)
    _assert_no_forbidden_keys(observation)


def test_world_label_candidate_without_reviewable_fpv_bbox_is_not_actionable() -> None:
    contract = _contract(CleanupBackendSession(build_cleanup_scenario(seed=7)))
    observation = _first_non_empty_observation(contract)
    detection = observation["visible_object_detections"][0]
    handle = detection["object_id"]

    navigation = contract.navigate_to_object(handle)
    picked = contract.pick(handle)
    worklist_item = next(
        item
        for item in contract.cleanup_worklist_payload()["objects"]
        if item["object_id"] == handle
    )

    assert navigation["ok"] is False
    assert navigation["error_reason"] == "visual_evidence_not_reviewable"
    assert navigation["required_next_tool"] == "adjust_camera"
    assert navigation["candidate_state"] == "visual_scan_required"
    assert navigation["visual_grounding_evidence"]["reviewability_status"] == "not_reviewable"
    assert picked["ok"] is False
    assert picked["error_reason"] == "visual_evidence_not_reviewable"
    assert "cleanup_recommended" not in worklist_item
    assert worklist_item["candidate_state"] == "visual_scan_required"
    assert worklist_item["actionability_status"] == "needs_visual_evidence"
    _assert_no_forbidden_keys(navigation)


def test_world_label_candidate_requires_scan_then_observe_before_navigation() -> None:
    contract = _contract(CleanupBackendSession(build_cleanup_scenario(seed=7)))
    first_observation = _first_non_empty_observation(contract)
    handle = first_observation["visible_object_detections"][0]["object_id"]

    blocked = contract.navigate_to_object(handle)
    contract.adjust_camera(yaw_delta_deg=15)
    confirmed_observation = contract.observe()
    confirmed = next(
        item
        for item in confirmed_observation["visible_object_detections"]
        if item["object_id"] == handle
    )
    navigation = contract.navigate_to_object(handle)

    assert blocked["ok"] is False
    assert confirmed["source_observation_id"].startswith("world_label_fpv_")
    assert confirmed["source_observation_id"] != first_observation["source_observation_id"]
    assert confirmed["candidate_state"] == "navigation_authorized"
    assert confirmed["visual_grounding_evidence"]["reviewability_status"] == "reviewable"
    assert navigation["ok"] is True
    assert navigation["candidate_state"] == "navigation_authorized"
    assert (
        navigation["visual_grounding_evidence"]["source_observation_id"]
        == (confirmed["source_observation_id"])
    )
    _assert_no_forbidden_keys(navigation)


def test_zero_camera_adjustment_does_not_confirm_world_label_candidate() -> None:
    contract = _contract(CleanupBackendSession(build_cleanup_scenario(seed=7)))
    first_observation = _first_non_empty_observation(contract)
    handle = first_observation["visible_object_detections"][0]["object_id"]

    adjusted = contract.adjust_camera(yaw_delta_deg=0, pitch_delta_deg=0)
    second_observation = contract.observe()
    still_pending = next(
        item
        for item in second_observation["visible_object_detections"]
        if item["object_id"] == handle
    )
    navigation = contract.navigate_to_object(handle)

    assert adjusted["ok"] is False
    assert adjusted["error_reason"] == "noop_camera_adjustment"
    assert adjusted["required_next_tool"] == "adjust_camera"
    assert adjusted["followup_tool"] == "observe"
    assert adjusted["camera_offset"] == {"yaw_delta_deg": 0.0, "pitch_delta_deg": 0.0}
    assert adjusted["no_camera_motion"] is True
    assert adjusted["fresh_fpv_observation_required"] is True
    assert "does not create a fresh source FPV view" in adjusted["recovery_hint"]
    assert still_pending["candidate_state"] == "visual_scan_required"
    assert still_pending["visual_scan"]["fresh_fpv_observation_required"] is True
    assert navigation["ok"] is False
    assert navigation["required_next_tool"] == "adjust_camera"


def test_world_labels_sanitized_observations_omit_destination_oracle_fields() -> None:
    public_anchor_contract = _contract(CleanupBackendSession(build_cleanup_scenario(seed=7)))
    public_anchor_observation = _first_non_empty_observation(public_anchor_contract)
    public_anchor_detection = public_anchor_observation["visible_object_detections"][0]

    sanitized_contract = _contract(
        CleanupBackendSession(build_cleanup_scenario(seed=7)),
        evidence_lane="world-public-labels",
    )
    sanitized_observation = _first_non_empty_observation(sanitized_contract)
    detection = sanitized_observation["visible_object_detections"][0]

    assert "candidate_fixture_id" not in public_anchor_detection
    assert "recommended_tool" not in public_anchor_detection
    assert sanitized_observation["perception_source"] == (
        SANITIZED_VISIBLE_OBJECT_DETECTIONS_PROVENANCE
    )
    assert sanitized_observation["detection_exposure_policy"] == (
        SANITIZED_VISIBLE_OBJECT_DETECTIONS_POLICY
    )
    assert detection["object_id"].startswith("observed_")
    assert detection["category"]
    assert detection["image_region"]["type"] == "verbal_region"
    assert detection["source_observation_id"]
    assert detection["candidate_state"] == "visual_scan_required"
    assert detection["visual_grounding_evidence"]["reviewability_status"] == "not_reviewable"
    assert detection["producer_type"] == SANITIZED_VISIBLE_OBJECT_DETECTIONS_PROVENANCE
    assert detection["support_estimate"]
    assert "cleanup_recommended" not in detection
    assert detection["destination_policy_status"] == "policy_required"
    assert detection["destination_policy"]["private_truth_included"] is False
    assert detection["destination_policy"]["preferred_fixture_categories"]
    assert "candidate_fixture_id" not in detection["destination_policy"]
    assert "candidate_fixture_id" not in detection
    assert "recommended_tool" not in detection
    _assert_no_forbidden_keys(sanitized_observation)


def test_world_labels_sanitized_destination_policy_is_public_category_guidance() -> None:
    contract = _contract(
        CleanupBackendSession(build_cleanup_scenario(seed=7)),
        evidence_lane="world-public-labels",
    )

    policies_by_category = {}
    for waypoint in contract.metric_map()["inspection_waypoints"]:
        contract.navigate_to_waypoint(str(waypoint["waypoint_id"]))
        observation = contract.observe()
        for detection in observation["visible_object_detections"]:
            policies_by_category.setdefault(
                str(detection["category"]).lower(),
                detection["destination_policy"],
            )

    food_policy = policies_by_category["food"]
    dish_policy = policies_by_category["dish"]
    book_policy = policies_by_category["book"]

    assert food_policy["source"] == "public_category_fixture_affordance"
    assert food_policy["preferred_fixture_categories"] == ["fridge", "refrigerator"]
    assert food_policy["placement_tool"] == "place_inside"
    assert food_policy["placement_tool_by_fixture_category"] == {
        "fridge": "place_inside",
        "refrigerator": "place_inside",
    }
    assert food_policy["private_truth_included"] is False
    assert dish_policy["preferred_fixture_categories"] == ["sink", "countertop"]
    assert dish_policy["placement_tool"] == "place"
    assert book_policy["placement_tool_by_fixture_category"]["shelvingunit"] == "place_inside"
    assert book_policy["placement_tool_by_fixture_category"]["desk"] == "place"


def test_realworld_contract_exposes_nav2_shaped_public_map_and_provenance() -> None:
    contract = _contract(CleanupBackendSession(build_cleanup_scenario(seed=7)))

    metric_map = contract.metric_map()
    static_fixture_projection = contract.static_fixture_projection()
    waypoint, waypoint_nav, detection = _first_detected_metric_map_waypoint(
        contract,
        metric_map,
    )
    fixture = _public_destination_fixture_for_detection(contract, detection)
    blocked_nav = contract.navigate_to_object(detection["object_id"])
    object_nav, receptacle_nav = _confirm_pick_and_navigate_to_fixture(
        contract,
        detection,
        fixture,
    )
    agent_view = contract.agent_view_payload()
    live_metric_map = contract.metric_map()

    _assert_nav2_shaped_metric_map(metric_map, static_fixture_projection, waypoint)
    _assert_nav2_navigation_provenance(
        waypoint_nav,
        blocked_nav,
        object_nav,
        receptacle_nav,
    )
    _assert_nav2_agent_runtime_map(agent_view, live_metric_map)
    _assert_no_forbidden_keys(agent_view)


def _first_detected_metric_map_waypoint(
    contract: RealWorldCleanupContract,
    metric_map: dict,
) -> tuple[dict, dict, dict]:
    waypoint = {}
    waypoint_nav = {}
    detection = None
    for candidate in metric_map["inspection_waypoints"]:
        waypoint = candidate
        waypoint_nav = contract.navigate_to_waypoint(str(waypoint["waypoint_id"]))
        observation = contract.observe()
        detections = observation["visible_object_detections"]
        if detections:
            detection = detections[0]
            break
    assert detection is not None
    return waypoint, waypoint_nav, detection


def _confirm_pick_and_navigate_to_fixture(
    contract: RealWorldCleanupContract,
    detection: dict,
    fixture: dict,
) -> tuple[dict, dict]:
    waypoint_id = str(detection.get("waypoint_id") or detection.get("last_waypoint_id") or "")
    if waypoint_id:
        contract.navigate_to_waypoint(waypoint_id)
    contract.adjust_camera(yaw_delta_deg=15)
    confirmed_observation = contract.observe()
    confirmed = next(
        item
        for item in confirmed_observation["visible_object_detections"]
        if item["object_id"] == detection["object_id"]
    )
    object_nav = contract.navigate_to_object(confirmed["object_id"])
    assert contract.pick(confirmed["object_id"])["ok"] is True
    receptacle_nav = contract.navigate_to_receptacle(str(fixture["fixture_id"]))
    return object_nav, receptacle_nav


def _assert_nav2_shaped_metric_map(
    metric_map: dict,
    static_fixture_projection: dict,
    waypoint: dict,
) -> None:
    assert metric_map["schema"] == REAL_ROBOT_MAP_BUNDLE_SCHEMA
    assert metric_map["frame_id"] == "map"
    assert metric_map["origin"] == {"x": -0.5, "y": 0.0, "yaw": 0.0}
    assert metric_map["occupancy_values"] == {"unknown": -1, "free": 0, "occupied": 100}
    assert metric_map["map_bundle"]["schema"] == "nav2_map_bundle_v1"
    assert metric_map["map_bundle"]["robot_profile_id"] == "rby1m"
    assert metric_map["map_bundle"]["artifact_paths"]["map_yaml"] == "map_bundle/map.yaml"
    assert metric_map["map_bundle"]["parameter_hash"]
    assert waypoint["frame_id"] == "map"
    assert waypoint["purpose"] == "base_navigation_area_inspection"
    assert waypoint["waypoint_source"] == "generated_exploration_candidate"
    assert static_fixture_projection["schema"] == "static_fixture_projection_v1"
    assert static_fixture_projection["contains_runtime_observations"] is False
    assert static_fixture_projection["rooms"] == []
    assert "observations" not in static_fixture_projection


def _assert_nav2_navigation_provenance(
    waypoint_nav: dict,
    blocked_nav: dict,
    object_nav: dict,
    receptacle_nav: dict,
) -> None:
    assert waypoint_nav["navigation_backend"] == "sim_costmap_planner"
    assert waypoint_nav["route_validation"]["ok"] is True
    assert waypoint_nav["pose_source"] == "inspection_waypoint"
    if not blocked_nav["ok"]:
        assert blocked_nav["error_reason"] == "visual_evidence_not_reviewable"
    else:
        assert blocked_nav["candidate_state"] == "navigation_authorized"
    assert object_nav["navigation_backend"] == "api_semantic"
    assert object_nav["candidate_state"] == "navigation_authorized"
    assert object_nav["pose_source"] == "latest_observation"
    assert object_nav["requires_reobserve"] is False
    assert receptacle_nav["navigation_backend"] == "api_semantic"
    assert receptacle_nav["pose_source"] == "static_fixture_projection"


def _assert_nav2_agent_runtime_map(agent_view: dict, live_metric_map: dict) -> None:
    policy_view = agent_view_module.policy_view(agent_view)
    runtime_metric_map = agent_view_module.runtime_metric_map(agent_view)
    cleanup_worklist = agent_view_module.cleanup_worklist(agent_view)
    assert policy_view["chase_camera_policy_input"] is False
    assert "runtime_metric_map" in policy_view["allowed_inputs"]
    assert runtime_metric_map["schema"] == RUNTIME_METRIC_MAP_SCHEMA
    assert live_metric_map["runtime_metric_map"]["schema"] == RUNTIME_METRIC_MAP_SCHEMA
    assert live_metric_map["runtime_metric_map"]["observed_objects"][0]["state"] == "held"
    assert runtime_metric_map["source_map_mutated"] is False
    assert runtime_metric_map["static_map"]["contains_runtime_observations"] is False
    assert runtime_metric_map["observed_objects"][0]["state"] == "held"
    assert cleanup_worklist["schema"] == CLEANUP_WORKLIST_SCHEMA
    assert cleanup_worklist["objects"][0]["state"] == "held"


def test_scene_index_backend_prefers_public_usd_fixture_overlay_over_stale_map_bundle() -> None:
    scenario = CleanupScenario(
        scenario_id="isaac-scene-index-procthor-10k-val-1-7-1",
        task="Clean up this loaded Isaac scene.",
        seed=7,
        objects=(
            CleanupObject(
                object_id="bowl_847a24bfa9d8b1a1f26661ebbb850f56_1_0_2",
                name="Bowl (Bowl_12)",
                category="Bowl",
                location_id="diningtable_f113cf7f8367e89f709b53cbee1a1c05_1_0_2",
            ),
        ),
        receptacles=(
            CleanupReceptacle(
                "diningtable_f113cf7f8367e89f709b53cbee1a1c05_1_0_2",
                "DiningTable DiningTable|2|1|0 Dining_Table_203_1",
                "isaac_scene",
                category="DiningTable",
            ),
            CleanupReceptacle(
                "sink_07e796f32d0d3efce9acf4be00f3bc53_1_0_3",
                "Sink Sink|3|1|0 Sink_1",
                "isaac_scene",
                category="Sink",
            ),
        ),
        private_manifest=PrivateScoringManifest(
            scenario_id="isaac-scene-index-procthor-10k-val-1-7-1",
            targets=(
                TargetRule(
                    object_id="bowl_847a24bfa9d8b1a1f26661ebbb850f56_1_0_2",
                    valid_receptacle_ids=("sink_07e796f32d0d3efce9acf4be00f3bc53_1_0_3",),
                ),
            ),
            success_threshold=1,
        ),
    )
    session = CleanupBackendSession(scenario)
    session.backend.scenario_source = "isaac_scene_index"
    contract = _contract(session)

    detection = None
    inspection_waypoints = contract.metric_map()["inspection_waypoints"]
    for waypoint in inspection_waypoints:
        contract.navigate_to_waypoint(str(waypoint["waypoint_id"]))
        observation = contract.observe()
        if observation["visible_object_detections"]:
            detection = observation["visible_object_detections"][0]
            break

    assert detection is not None
    target_fixture = _public_destination_fixture_for_detection(contract, detection)
    assert str(target_fixture["fixture_id"]).startswith("anchor_fixture_")
    assert str(target_fixture["category"]).lower() in {"countertop", "sink"}
    assert target_fixture["public_fixture_source"] == "runtime_semantic_anchor"

    _assert_no_forbidden_keys(target_fixture)


def test_scene_index_backend_public_map_uses_usd_room_outline_scale() -> None:
    scenario = CleanupScenario(
        scenario_id="isaac-scene-index-procthor-10k-val-1-7-1",
        task="Clean up this loaded Isaac scene.",
        seed=7,
        objects=(
            CleanupObject(
                object_id="bowl_847a24bfa9d8b1a1f26661ebbb850f56_1_0_2",
                name="Bowl (Bowl_12)",
                category="Bowl",
                location_id="diningtable_f113cf7f8367e89f709b53cbee1a1c05_1_0_2",
            ),
        ),
        receptacles=(
            CleanupReceptacle(
                "diningtable_f113cf7f8367e89f709b53cbee1a1c05_1_0_2",
                "DiningTable DiningTable|2|1|0 Dining_Table_203_1",
                "isaac_scene",
                category="DiningTable",
            ),
            CleanupReceptacle(
                "sink_07e796f32d0d3efce9acf4be00f3bc53_1_0_3",
                "Sink Sink|3|1|0 Sink_1",
                "isaac_scene",
                category="Sink",
            ),
        ),
        private_manifest=PrivateScoringManifest(
            scenario_id="isaac-scene-index-procthor-10k-val-1-7-1",
            targets=(
                TargetRule(
                    object_id="bowl_847a24bfa9d8b1a1f26661ebbb850f56_1_0_2",
                    valid_receptacle_ids=("sink_07e796f32d0d3efce9acf4be00f3bc53_1_0_3",),
                ),
            ),
            success_threshold=1,
        ),
    )
    session = CleanupBackendSession(scenario)
    session.backend.scenario_source = "isaac_scene_index"
    session.backend.room_outlines = [
        {
            "room_id": "room_2",
            "label": "Room 2",
            "center": [2.99, 4.983],
            "half_extents": [2.99, 4.983],
            "provenance": "isaac_usd_room_mesh_world_bounds",
            "usd_prim_path": "/val_1/Geometry/room_2_visual_0",
        },
        {
            "room_id": "room_3",
            "label": "Room 3",
            "center": [7.973, 2.99],
            "half_extents": [1.993, 2.99],
            "provenance": "isaac_usd_room_mesh_world_bounds",
            "usd_prim_path": "/val_1/Geometry/room_3_visual_0",
        },
    ]
    session.backend.receptacle_index = {
        "diningtable_f113cf7f8367e89f709b53cbee1a1c05_1_0_2": {
            "usd_world_bounds": {"center": [2.717858, 5.93953, 0.374628]}
        },
        "sink_07e796f32d0d3efce9acf4be00f3bc53_1_0_3": {
            "usd_world_bounds": {"center": [9.578895, 1.843155, 0.52296]}
        },
    }

    contract = _contract(session)
    metric_map = contract.metric_map()
    assert metric_map["rooms"]
    assert all(room["room_label"] for room in metric_map["rooms"])
    assert contract.static_fixture_projection()["rooms"] == []
    assert metric_map["inspection_waypoints"]
    assert all(
        waypoint["waypoint_source"] == "generated_exploration_candidate"
        for waypoint in metric_map["inspection_waypoints"]
    )
    assert all(
        waypoint["generation_policy"] == "base_navigation_area_centroid_clearance_v1"
        for waypoint in metric_map["inspection_waypoints"]
    )
    assert all(waypoint["navigation_area_id"] for waypoint in metric_map["inspection_waypoints"])


def test_scene_index_backend_room_outline_waypoints_avoid_fixture_occupied_goals() -> None:
    scenario = CleanupScenario(
        scenario_id="isaac-scene-index-procthor-10k-val-1-7-1",
        task="Clean up this loaded Isaac scene.",
        seed=7,
        objects=(
            CleanupObject(
                object_id="bowl_847a24bfa9d8b1a1f26661ebbb850f56_1_0_2",
                name="Bowl (Bowl_12)",
                category="Bowl",
                location_id="diningtable_f113cf7f8367e89f709b53cbee1a1c05_1_0_2",
            ),
        ),
        receptacles=(
            CleanupReceptacle("bed_258d27d5fe50e324961c7a8698ace951_1_0_2", "Bed", "isaac_scene"),
            CleanupReceptacle(
                "bed_aed5602affd158c34e7eda83481af599_1_0_2",
                "Bed",
                "isaac_scene",
            ),
            CleanupReceptacle(
                "chair_bfd87bce6390b5a5bb5fcae097e899f7_1_0_2",
                "Chair",
                "isaac_scene",
            ),
            CleanupReceptacle(
                "chair_bfd87bce6390b5a5bb5fcae097e899f7_2_0_2",
                "Chair",
                "isaac_scene",
            ),
            CleanupReceptacle(
                "chair_bfd87bce6390b5a5bb5fcae097e899f7_3_0_2",
                "Chair",
                "isaac_scene",
            ),
            CleanupReceptacle(
                "chestofdrawers_7a2e462b2666d3558113b2d84da9dc74_1_0_2",
                "Dresser",
                "isaac_scene",
            ),
            CleanupReceptacle(
                "diningtable_f113cf7f8367e89f709b53cbee1a1c05_1_0_2",
                "DiningTable",
                "isaac_scene",
            ),
            CleanupReceptacle(
                "sink_07e796f32d0d3efce9acf4be00f3bc53_1_0_3",
                "Sink",
                "isaac_scene",
            ),
        ),
        private_manifest=PrivateScoringManifest(
            scenario_id="isaac-scene-index-procthor-10k-val-1-7-1",
            targets=(
                TargetRule(
                    object_id="bowl_847a24bfa9d8b1a1f26661ebbb850f56_1_0_2",
                    valid_receptacle_ids=("sink_07e796f32d0d3efce9acf4be00f3bc53_1_0_3",),
                ),
            ),
            success_threshold=1,
        ),
    )
    session = CleanupBackendSession(scenario)
    session.backend.scenario_source = "isaac_scene_index"
    session.backend.room_outlines = [
        {
            "room_id": "room_2",
            "label": "Room 2",
            "center": [2.99, 4.983],
            "half_extents": [2.99, 4.983],
            "provenance": "isaac_usd_room_mesh_world_bounds",
            "usd_prim_path": "/val_1/Geometry/room_2_visual_0",
        },
        {
            "room_id": "room_3",
            "label": "Room 3",
            "center": [7.973, 2.99],
            "half_extents": [1.993, 2.99],
            "provenance": "isaac_usd_room_mesh_world_bounds",
            "usd_prim_path": "/val_1/Geometry/room_3_visual_0",
        },
    ]
    session.backend.receptacle_index = {
        "bed_258d27d5fe50e324961c7a8698ace951_1_0_2": {
            "usd_world_bounds": {"center": [2.818349, 8.99204, 0.856923]}
        },
        "bed_aed5602affd158c34e7eda83481af599_1_0_2": {
            "usd_world_bounds": {"center": [2.809145, 1.200613, 0.5965]}
        },
        "chair_bfd87bce6390b5a5bb5fcae097e899f7_1_0_2": {
            "usd_world_bounds": {"center": [3.308217, 5.945434, 0.4]}
        },
        "chair_bfd87bce6390b5a5bb5fcae097e899f7_2_0_2": {
            "usd_world_bounds": {"center": [2.70468, 6.83613, 0.4]}
        },
        "chair_bfd87bce6390b5a5bb5fcae097e899f7_3_0_2": {
            "usd_world_bounds": {"center": [2.11708, 5.932897, 0.4]}
        },
        "chestofdrawers_7a2e462b2666d3558113b2d84da9dc74_1_0_2": {
            "usd_world_bounds": {"center": [5.716285, 0.639941, 0.5]}
        },
        "diningtable_f113cf7f8367e89f709b53cbee1a1c05_1_0_2": {
            "usd_world_bounds": {"center": [2.717858, 5.93953, 0.374628]}
        },
        "sink_07e796f32d0d3efce9acf4be00f3bc53_1_0_3": {
            "usd_world_bounds": {"center": [9.578895, 1.843155, 0.52296]}
        },
    }

    contract = _contract(session)
    metric_map = contract.metric_map()
    static_fixture_projection = contract.static_fixture_projection()
    static_landmarks = static_landmarks_from_fixture_projection(static_fixture_projection)
    waypoints = metric_map["inspection_waypoints"]
    routes = [
        validate_metric_map_route(
            metric_map,
            static_landmarks,
            start_waypoint_id=str(waypoints[0]["waypoint_id"]),
            goal_waypoint_id=str(waypoint["waypoint_id"]),
        )
        for waypoint in waypoints
    ]

    assert len(waypoints) == len(contract.metric_map()["rooms"])
    assert all(route.ok for route in routes), [route.as_dict() for route in routes]
    assert all(waypoint.get("fixture_ids", []) == [] for waypoint in waypoints)
    assert all(waypoint["navigation_area_id"] for waypoint in waypoints)
    for waypoint in waypoints:
        navigation = contract.navigate_to_waypoint(str(waypoint["waypoint_id"]))
        assert navigation["ok"] is True, navigation


def test_cleanup_policy_trace_allows_public_map_query_before_post_place_observe() -> None:
    trace = cleanup_policy_trace_from_events(
        [
            _trace_response("navigate_to_waypoint", {"ok": True, "waypoint_id": "room_1_scan_1"}),
            _trace_response("observe", {"ok": True, "waypoint_id": "room_1_scan_1"}),
            _trace_response("navigate_to_object", {"ok": True, "object_id": "observed_001"}),
            _trace_response("pick", {"ok": True, "object_id": "observed_001"}),
            _trace_response(
                "navigate_to_receptacle",
                {
                    "ok": True,
                    "object_id": "observed_001",
                    "fixture_id": "sink_01",
                },
            ),
            _trace_response(
                "place",
                {
                    "ok": True,
                    "object_id": "observed_001",
                    "fixture_id": "sink_01",
                },
            ),
            _trace_response("metric_map", {"ok": True}),
            _trace_response("observe", {"ok": True, "waypoint_id": "room_1_scan_1"}),
        ],
        _policy_trace_agent_view([{"waypoint_id": "room_1_scan_1"}]),
    )

    assert trace["placed_object_count"] == 1
    assert trace["post_place_observe_count"] == 1
    assert trace["post_place_observe_complete"] is True
    assert trace["events"][-1]["role"] == "post_place_observe"


def test_cleanup_policy_trace_treats_last_base_waypoint_discovery_as_survey_first() -> None:
    trace = cleanup_policy_trace_from_events(
        [
            _trace_response("navigate_to_waypoint", {"ok": True, "waypoint_id": "room_1_scan_1"}),
            _trace_response(
                "observe",
                {
                    "ok": True,
                    "waypoint_id": "room_1_scan_1",
                    "visible_object_detections": [],
                },
            ),
            _trace_response("navigate_to_waypoint", {"ok": True, "waypoint_id": "room_1_scan_2"}),
            _trace_response(
                "observe",
                {
                    "ok": True,
                    "waypoint_id": "room_1_scan_2",
                    "visible_object_detections": [
                        {
                            "object_id": "observed_001",
                            "cleanup_recommended": True,
                        }
                    ],
                },
            ),
            _trace_response("navigate_to_object", {"ok": True, "object_id": "observed_001"}),
            _trace_response("pick", {"ok": True, "object_id": "observed_001"}),
            _trace_response(
                "navigate_to_receptacle",
                {"ok": True, "object_id": "observed_001", "fixture_id": "sink_01"},
            ),
            _trace_response(
                "place",
                {"ok": True, "object_id": "observed_001", "fixture_id": "sink_01"},
            ),
            _trace_response("observe", {"ok": True, "waypoint_id": "room_1_scan_2"}),
        ],
        _policy_trace_agent_view(
            [
                {"waypoint_id": "room_1_scan_1"},
                {"waypoint_id": "room_1_scan_2"},
            ]
        ),
    )

    assert trace["loop_style"] == "survey_first_cleanup_loop"
    assert trace["first_cleanup_before_full_survey"] is False
    assert trace["first_actionable_observation_index"] == 4
    assert trace["first_cleanup_index"] == 5


def test_cleanup_policy_trace_rejects_cached_cleanup_after_later_map_query() -> None:
    trace = cleanup_policy_trace_from_events(
        [
            _trace_response("navigate_to_waypoint", {"ok": True, "waypoint_id": "room_1_scan_1"}),
            _trace_response(
                "observe",
                {
                    "ok": True,
                    "waypoint_id": "room_1_scan_1",
                    "visible_object_detections": [
                        {
                            "object_id": "observed_001",
                            "cleanup_recommended": True,
                        }
                    ],
                },
            ),
            _trace_response("navigate_to_waypoint", {"ok": True, "waypoint_id": "room_1_scan_2"}),
            _trace_response("observe", {"ok": True, "waypoint_id": "room_1_scan_2"}),
            _trace_response("navigate_to_object", {"ok": True, "object_id": "observed_001"}),
        ],
        _policy_trace_agent_view(
            [
                {"waypoint_id": "room_1_scan_1"},
                {"waypoint_id": "room_1_scan_2"},
            ]
        ),
    )

    assert trace["loop_style"] == "survey_first_cleanup_loop"
    assert trace["first_actionable_observation_index"] == 2
    assert trace["first_cleanup_index"] == 5


def _policy_trace_agent_view(inspection_waypoints: list[dict]) -> dict:
    return agent_view_module.build_agent_view(
        contract=REALWORLD_CONTRACT,
        perception_mode="visible_object_detections",
        detection_exposure_policy="world_labels",
        structured_detections_available=True,
        base_metric_map={"inspection_waypoints": inspection_waypoints},
        runtime_metric_map={"schema": RUNTIME_METRIC_MAP_SCHEMA},
        observed_objects=[],
        raw_fpv_observations=[],
        camera_model_policy_evidence={},
        model_declared_observations=[],
        model_declared_observation_evidence={},
        policy_view={"schema": "realworld_cleanup_policy_view_v1"},
        cleanup_worklist={},
        observed_waypoint_ids=[],
        public_tool_names=[],
        forbidden_keys=frozenset(forbidden_agent_view_keys()),
    )


def test_runtime_metric_map_keeps_static_and_dynamic_semantics_separate() -> None:
    contract = _contract(
        CleanupBackendSession(build_cleanup_scenario(seed=7)),
        perception_mode=CAMERA_MODEL_POLICY_MODE,
    )

    observation = {}
    declared = {}
    for waypoint in contract.metric_map()["inspection_waypoints"]:
        contract.navigate_to_waypoint(str(waypoint["waypoint_id"]))
        observation = contract.observe()
        declared = contract.declare_visual_candidates(
            observation["raw_fpv_observation"]["observation_id"]
        )
        if declared["model_declared_observations"]:
            break
    agent_view = contract.agent_view_payload()
    runtime_map = agent_view_module.runtime_metric_map(agent_view)

    assert declared["ok"] is True
    assert runtime_map["schema"] == RUNTIME_METRIC_MAP_SCHEMA
    assert runtime_map["private_truth_included"] is False
    assert runtime_map["source_map_mutated"] is False
    assert runtime_map["static_map"]["fixtures"] == []
    assert runtime_map["public_semantic_anchors"]
    assert runtime_map["map_update_candidates"] == []
    assert runtime_map["observed_objects"]
    observed = runtime_map["observed_objects"][0]
    assert observed["object_id"].startswith("observed_")
    assert observed["source_observation_id"] == observation["raw_fpv_observation"]["observation_id"]
    assert observed["producer_type"] == SIMULATED_CAMERA_MODEL_PROVENANCE
    assert observed["actionability"] in {"actionable", "pending"}
    _assert_no_forbidden_keys(runtime_map)


def test_world_labels_sanitized_runtime_map_keeps_detection_fields_without_destination() -> None:
    contract = _contract(
        CleanupBackendSession(build_cleanup_scenario(seed=7)),
        evidence_lane="world-public-labels",
    )

    _first_non_empty_observation(contract)
    agent_view = contract.agent_view_payload()
    runtime_map = agent_view_module.runtime_metric_map(agent_view)
    observed = runtime_map["observed_objects"][0]
    worklist_item = agent_view_module.cleanup_worklist(agent_view)["objects"][0]

    assert (
        agent_view_module.detection_exposure_policy(agent_view)
        == SANITIZED_VISIBLE_OBJECT_DETECTIONS_POLICY
    )
    assert observed["producer_type"] == SANITIZED_VISIBLE_OBJECT_DETECTIONS_PROVENANCE
    assert observed["source_observation_id"]
    assert observed["image_region"]["type"] == "verbal_region"
    assert observed["grounding_status"] == "resolved"
    assert observed["candidate_state"] == "visual_scan_required"
    assert observed["actionability"] == "pending"
    assert observed["candidate_fixture_id"] == ""
    assert observed["candidate_source"] == "policy_required_destination_selection"
    assert observed["destination_policy_status"] == "policy_required"
    assert observed["destination_policy"]["preferred_fixture_categories"]
    assert observed["destination_policy"]["private_truth_included"] is False
    assert "cleanup_recommended" not in worklist_item
    assert worklist_item["candidate_fixture_id"] == ""
    assert worklist_item["candidate_state"] == "visual_scan_required"
    assert worklist_item["destination_policy_status"] == "policy_required"
    assert worklist_item["destination_policy"] == observed["destination_policy"]
    assert (
        runtime_map["producer_summary"]["producer_types"][
            SANITIZED_VISIBLE_OBJECT_DETECTIONS_PROVENANCE
        ]
        >= 1
    )
    _assert_no_forbidden_keys(runtime_map)


def test_map_build_fixture_anchors_keep_best_view_waypoint_binding() -> None:
    contract = _contract(
        CleanupBackendSession(build_cleanup_scenario(seed=7)),
        evidence_lane="world-public-labels",
    )

    for waypoint in contract.metric_map()["inspection_waypoints"]:
        contract.navigate_to_waypoint(str(waypoint["waypoint_id"]))
        contract.adjust_camera(yaw_delta_deg=15)
        contract.observe()

    runtime_map = agent_view_module.runtime_metric_map(contract.agent_view_payload())
    fixture_waypoints = {
        item["category"]: item["waypoint_id"]
        for item in runtime_map["public_semantic_anchors"]
        if item.get("anchor_type") in {"fixture", "surface", "receptacle"}
    }

    assert fixture_waypoints["kitchen sink"] == "room_2_inspection"
    assert fixture_waypoints["fridge"] == "room_2_inspection"
    assert fixture_waypoints["sofa"] == "room_3_inspection"
    assert fixture_waypoints["desk"] == "room_4_inspection"
    assert fixture_waypoints["laundry hamper"] in {
        "room_6_inspection",
        "room_7_inspection",
        "room_8_inspection",
    }
    assert len(set(fixture_waypoints.values())) >= 4
    _assert_no_forbidden_keys(runtime_map)


def test_runtime_metric_map_promotes_only_observed_fixture_viewpoints() -> None:
    contract = _contract(
        CleanupBackendSession(_empty_cleanup_scenario("map-build-empty-observation-test")),
        evidence_lane="world-public-labels",
    )

    for waypoint in contract.metric_map()["inspection_waypoints"]:
        contract.navigate_to_waypoint(str(waypoint["waypoint_id"]))
        observation = contract.observe()
        assert observation["visible_object_detections"] == []

    runtime_map = agent_view_module.runtime_metric_map(contract.agent_view_payload())
    fixture_anchors = [
        item
        for item in runtime_map["public_semantic_anchors"]
        if item.get("anchor_type") in {"fixture", "surface", "receptacle"}
    ]

    assert runtime_map["observed_objects"] == []
    assert fixture_anchors
    assert all(anchor["source_observation_id"] for anchor in fixture_anchors)
    assert all(
        anchor["waypoint_id"] in contract._observed_waypoint_ids for anchor in fixture_anchors
    )
    assert all(
        anchor["producer_type"] == SANITIZED_VISIBLE_OBJECT_DETECTIONS_PROVENANCE
        for anchor in fixture_anchors
    )
    assert all("object_pose" not in anchor for anchor in fixture_anchors)
    _assert_no_forbidden_keys(runtime_map)


def test_runtime_metric_map_snapshot_priors_require_current_confirmation() -> None:
    sweep_contract = _contract(
        CleanupBackendSession(build_cleanup_scenario(seed=7)),
        perception_mode=CAMERA_MODEL_POLICY_MODE,
    )
    for waypoint in sweep_contract.metric_map()["inspection_waypoints"]:
        sweep_contract.navigate_to_waypoint(str(waypoint["waypoint_id"]))
        observation = sweep_contract.observe()
        declared = sweep_contract.declare_visual_candidates(
            observation["raw_fpv_observation"]["observation_id"]
        )
        if declared["model_declared_observations"]:
            break
    prior_snapshot = sweep_contract.agent_view_payload()["runtime_metric_map"]

    contract = _contract(
        CleanupBackendSession(build_cleanup_scenario(seed=7)),
        perception_mode=CAMERA_MODEL_POLICY_MODE,
        runtime_map_prior=prior_snapshot,
    )
    prior_only_map = contract.agent_view_payload()["runtime_metric_map"]

    prior_rows = [
        item for item in prior_only_map["observed_objects"] if item["freshness"] == "prior"
    ]
    assert prior_rows
    assert all(item["actionability"] == "needs_confirm" for item in prior_rows)
    assert agent_view_module.observed_objects(contract.agent_view_payload()) == []

    for waypoint in contract.metric_map()["inspection_waypoints"]:
        contract.navigate_to_waypoint(str(waypoint["waypoint_id"]))
        observation = contract.observe()
        declared = contract.declare_visual_candidates(
            observation["raw_fpv_observation"]["observation_id"]
        )
        if declared["model_declared_observations"]:
            break

    runtime_map = contract.agent_view_payload()["runtime_metric_map"]
    current_rows = [
        item for item in runtime_map["observed_objects"] if item["freshness"] == "current_run"
    ]
    assert current_rows
    assert current_rows[0]["prior_object_id"] == prior_rows[0]["prior_object_id"]
    assert current_rows[0]["snapshot_object_id"] == prior_rows[0]["snapshot_object_id"]
    _assert_no_forbidden_keys(runtime_map)


def test_b1_runtime_prior_capabilities_are_agent_visible_through_mcp_flow() -> None:
    prior_snapshot = {
        "schema": "runtime_map_prior_snapshot_v1",
        "runtime_metric_map": {
            "schema": RUNTIME_METRIC_MAP_SCHEMA,
            "rooms": [],
            "public_semantic_anchors": [],
            "observed_objects": [],
            "digital_twin_capabilities": {
                "robot_consumption_proof": {
                    "status": "robot_navigation_verified",
                    "robot_navigation_supported": True,
                    "planner_backed": False,
                    "physical_robot": False,
                    "manipulation_supported": False,
                    "object_receptacle_usd_binding_status": "blocked_out_of_scope",
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
                "room_semantic_projection_proof": {
                    "status": "blocked_missing_accepted_semantic_anchors",
                    "room_semantics_supported": False,
                    "object_semantics_supported": False,
                    "object_projection_status": "blocked_until_object_semantic_anchors",
                },
            },
        },
    }
    raw_prior = prior_snapshot["runtime_metric_map"]
    contract = _contract(
        CleanupBackendSession(build_cleanup_scenario(seed=7)),
        runtime_map_prior=raw_prior,
    )

    metric_map = contract.metric_map()
    waypoint = metric_map["inspection_waypoints"][0]
    navigation = contract.navigate_to_waypoint(str(waypoint["waypoint_id"]))
    observation = contract.observe()
    runtime_map = contract.agent_view_payload()["runtime_metric_map"]
    capabilities = runtime_map["digital_twin_capabilities"]
    summary = runtime_map["capability_summary"]

    assert navigation["ok"] is True
    assert observation["ok"] is True
    assert capabilities["robot_consumption_proof"]["robot_navigation_supported"] is True
    assert summary["robot_navigation_supported"] is True
    assert summary["render_observation_supported"] is True
    assert summary["same_pose_fpv_supported"] is True
    assert summary["same_pose_chase_supported"] is True
    assert summary["same_pose_topdown_supported"] is True
    assert summary["default_visual_route_status"] == (
        "blocked_missing_verified_b1_floor2_slow_render_proof"
    )
    assert summary["default_visual_route_selected"] is False
    assert summary["room_semantics_supported"] is False
    assert summary["object_semantics_supported"] is False
    assert summary["object_projection_status"] == "blocked_until_object_semantic_anchors"
    assert summary["manipulation_supported"] is False
    assert summary["planner_backed_navigation_supported"] is False
    assert summary["physical_robot_supported"] is False
    assert "rooms" in runtime_map
    assert not any(
        anchor.get("anchor_role") == "semantic"
        for anchor in runtime_map.get("public_semantic_anchors") or []
    )
    _assert_no_forbidden_keys(runtime_map)


def test_relative_pose_navigation_rejects_noop_and_out_of_bounds_requests() -> None:
    contract = _contract(CleanupBackendSession(build_cleanup_scenario(seed=7)))

    noop = contract.navigate_to_relative_pose()
    too_far = contract.navigate_to_relative_pose(forward_m=1.25)
    too_much_turn = contract.navigate_to_relative_pose(yaw_delta_deg=120)

    assert noop["ok"] is False
    assert noop["tool"] == "navigate_to_relative_pose"
    assert noop["error_reason"] == "noop_relative_pose_request"
    assert noop["frame_id"] == "base_link"
    assert noop["requires_reobserve"] is True
    assert too_far["error_reason"] == "relative_pose_delta_out_of_bounds"
    assert too_far["applied_delta"] == {"forward_m": 0.0, "lateral_m": 0.0, "yaw_delta_deg": 0.0}
    assert too_much_turn["error_reason"] == "relative_pose_delta_out_of_bounds"


def test_relative_pose_navigation_reports_public_delta_and_reobserve_requirement() -> None:
    scenario = build_cleanup_scenario(seed=7)
    backend = _RelativePoseBackend(scenario)
    contract = _contract(CleanupBackendSession(backend=backend))

    response = contract.navigate_to_relative_pose(
        forward_m=0.25,
        lateral_m=-0.125,
        yaw_delta_deg=15,
    )

    assert response["ok"] is True
    assert response["tool"] == "navigate_to_relative_pose"
    assert response["frame_id"] == "base_link"
    assert response["requested_delta"] == {
        "forward_m": 0.25,
        "lateral_m": -0.125,
        "yaw_delta_deg": 15.0,
    }
    assert response["applied_delta"] == response["requested_delta"]
    assert response["pose_source"] == "relative_robot_frame"
    assert response["backend_provenance"] == "api_semantic"
    assert response["requires_reobserve"] is True
    assert response["clamped"] is False
    assert backend.relative_pose_calls == [
        {"forward_m": 0.25, "lateral_m": -0.125, "yaw_delta_deg": 15.0}
    ]


def test_relative_pose_navigation_strips_private_backend_pose_fields() -> None:
    scenario = build_cleanup_scenario(seed=7)
    backend = _RelativePoseBackend(scenario)
    contract = _contract(CleanupBackendSession(backend=backend))

    response = contract.navigate_to_relative_pose(forward_m=0.25)

    assert response["ok"] is True
    assert response["backend_pose_mutation"]["robot_pose"] == {
        "x": 1.25,
        "y": 2.0,
        "pose_source": "relative_robot_frame",
    }
    assert "target_receptacle_id" not in str(response)


def test_base_metric_map_hides_authored_semantics_and_uses_generated_candidates() -> None:
    contract = _contract(
        CleanupBackendSession(build_cleanup_scenario(seed=7)),
    )

    metric_map = contract.metric_map()
    static_fixture_projection = contract.static_fixture_projection()
    waypoint, navigation, observation = _first_detection_waypoint(contract, metric_map)
    agent_view = contract.agent_view_payload()
    runtime_map = agent_view_module.runtime_metric_map(agent_view)

    _assert_base_metric_static_map_privacy(metric_map, static_fixture_projection, waypoint)
    assert navigation["ok"] is True
    assert observation["visible_object_detections"]
    _assert_base_metric_runtime_map_candidates(runtime_map, waypoint)
    _assert_base_metric_runtime_map_public_anchors(runtime_map, waypoint)
    _assert_base_metric_agent_view_observed_object_anchors(agent_view, runtime_map)
    _assert_no_forbidden_keys(agent_view)


def _first_detection_waypoint(
    contract: RealWorldCleanupContract,
    metric_map: dict,
) -> tuple[dict, dict, dict]:
    waypoint = metric_map["inspection_waypoints"][0]
    navigation = contract.navigate_to_waypoint(str(waypoint["waypoint_id"]))
    observation = contract.observe()
    for candidate in metric_map["inspection_waypoints"][1:]:
        if observation["visible_object_detections"]:
            break
        waypoint = candidate
        navigation = contract.navigate_to_waypoint(str(waypoint["waypoint_id"]))
        observation = contract.observe()
    return waypoint, navigation, observation


def _assert_base_metric_static_map_privacy(
    metric_map: dict,
    static_fixture_projection: dict,
    waypoint: dict,
) -> None:
    assert metric_map["base_metric_map"]["enabled"] is True
    assert metric_map["rooms"]
    assert all(room["room_label"] for room in metric_map["rooms"])
    assert metric_map["room_category_hints"]
    assert metric_map["driveable_ways"]
    assert static_fixture_projection["rooms"] == []
    assert str(waypoint["waypoint_id"]).startswith("room_")
    assert str(waypoint["waypoint_id"]).endswith("_inspection")
    assert waypoint["waypoint_source"] == "generated_exploration_candidate"
    assert waypoint["generation_policy"] == "base_navigation_area_centroid_clearance_v1"
    assert waypoint["navigation_area_id"] == waypoint["room_id"]
    assert "fixture_ids" not in waypoint
    assert "candidate_provenance" not in waypoint


def _assert_base_metric_runtime_map_candidates(runtime_map: dict, waypoint: dict) -> None:
    assert runtime_map["static_map"]["rooms"]
    assert all(room["room_label"] for room in runtime_map["static_map"]["rooms"])
    assert runtime_map["static_map"]["fixtures"] == []
    assert runtime_map["static_map"]["driveable_ways"]
    assert runtime_map["generated_exploration_candidates"]
    assert runtime_map["target_candidates"]
    waypoint_candidate = next(
        item
        for item in runtime_map["target_candidates"]
        if item["candidate_type"] == "generated_exploration_candidate"
        and item["waypoint_id"] == waypoint["waypoint_id"]
    )
    assert waypoint_candidate["candidate_id"] == (
        f"target_candidate_waypoint_{waypoint['waypoint_id']}"
    )
    assert waypoint_candidate["target_actionability_status"] == "actionable"
    assert waypoint_candidate["verified_navigation"] is True
    assert waypoint_candidate["inspection_budget"]["observed"] is True
    assert waypoint_candidate["inspection_budget"]["observation_count"] >= 1
    assert any(
        item["target_actionability_status"] == "needs_observe"
        for item in runtime_map["target_candidates"]
        if item["candidate_type"] == "generated_exploration_candidate"
    )
    target_search = runtime_map["target_search_summary"]
    assert target_search["schema"] == "target_search_summary_v1"
    assert target_search["candidate_count"] == len(runtime_map["target_candidates"])
    assert target_search["viewpoint_budget"]["visited_waypoint_count"] >= 1
    assert target_search["viewpoint_budget"]["unvisited_waypoint_count"] >= 1
    assert target_search["inspection_observations"]
    assert target_search["private_truth_included"] is False


def _assert_base_metric_runtime_map_public_anchors(runtime_map: dict, waypoint: dict) -> None:
    assert runtime_map["public_semantic_anchors"]
    waypoint_anchor = next(
        item
        for item in runtime_map["public_semantic_anchors"]
        if item["anchor_type"] == "observation_waypoint"
        and item["waypoint_id"] == waypoint["waypoint_id"]
    )
    assert waypoint_anchor["anchor_id"] == f"anchor_waypoint_{waypoint['waypoint_id']}"
    assert waypoint_anchor["waypoint_id"] == waypoint["waypoint_id"]
    assert waypoint_anchor["producer_type"] == "generated_exploration_candidate"
    assert waypoint_anchor["promotion_status"] == "run_local"
    fixture_anchor = next(
        item
        for item in runtime_map["public_semantic_anchors"]
        if item["anchor_type"] in {"fixture", "receptacle"}
    )
    assert fixture_anchor["anchor_id"].startswith("anchor_fixture_")
    assert fixture_anchor["source_observation_id"]


def _assert_base_metric_agent_view_observed_object_anchors(
    agent_view: dict,
    runtime_map: dict,
) -> None:
    assert runtime_map["observed_objects"]
    assert runtime_map["observed_objects"][0]["source_fixture_id"].startswith("anchor_fixture_")
    assert agent_view_module.observed_objects(agent_view)[0]["support_estimate"][
        "fixture_id"
    ].startswith("anchor_fixture_")


def test_public_fixture_anchor_allocator_skips_prior_anchor_id_collisions() -> None:
    anchor_mapping = {
        **{f"fixture_{index:03d}": f"anchor_fixture_{index:03d}" for index in range(1, 10)},
        "shelf_01": "anchor_fixture_011",
    }
    contract = SimpleNamespace(
        _runtime_map_anchor_priors=[
            {"anchor_id": f"anchor_fixture_{index:03d}"} for index in range(1, 17)
        ],
        _public_anchor_ids_by_private_fixture_id=anchor_mapping,
    )

    anchor_id = realworld_runtime_map_targets.public_anchor_id_for_fixture(
        contract,
        "bed_01",
    )

    public_ids = list(anchor_mapping.values())
    assert anchor_id == "anchor_fixture_017"
    assert len(public_ids) == len(set(public_ids))


def test_target_candidates_force_adaptive_public_reinspection_path() -> None:
    contract = _contract(CleanupBackendSession(build_cleanup_scenario(seed=7)))
    first_observation = _first_non_empty_observation(contract)
    handle = first_observation["visible_object_detections"][0]["object_id"]

    pre_scan_map = agent_view_module.runtime_metric_map(contract.agent_view_payload())
    pre_scan_candidate = next(
        item for item in pre_scan_map["target_candidates"] if item.get("object_id") == handle
    )

    assert pre_scan_candidate["target_actionability_status"] == "visible_only"
    assert pre_scan_candidate["verified_navigation"] is False
    assert pre_scan_candidate["rejection_reason"] == "visual_evidence_not_reviewable"
    generated_waypoint_id = pre_scan_candidate["generated_inspection_waypoint_id"]
    generated_waypoint = next(
        item
        for item in pre_scan_map["generated_target_inspection_candidates"]
        if item["waypoint_id"] == generated_waypoint_id
    )
    generated_target_candidate = next(
        item
        for item in pre_scan_map["target_candidates"]
        if item["candidate_type"] == "generated_target_inspection_candidate"
        and item["waypoint_id"] == generated_waypoint_id
    )
    metric_waypoints = contract.metric_map()["inspection_waypoints"]

    assert generated_waypoint["waypoint_source"] == "generated_target_inspection_candidate"
    assert generated_waypoint["verified_navigation"] is True
    assert generated_waypoint["source_target_candidate_id"] == pre_scan_candidate["candidate_id"]
    assert generated_target_candidate["target_actionability_status"] == "needs_observe"
    assert (
        generated_target_candidate["source_target_candidate_id"]
        == pre_scan_candidate["candidate_id"]
    )
    assert generated_waypoint_id in {str(item["waypoint_id"]) for item in metric_waypoints}
    blocked_navigation = contract.navigate_to_object(handle)
    assert blocked_navigation["ok"] is False
    assert blocked_navigation["error_reason"] == "visual_evidence_not_reviewable"
    assert blocked_navigation["required_next_tool"] == "adjust_camera"
    assert "adjust_camera" in blocked_navigation["recovery_tool_options"]

    waypoint_navigation = contract.navigate_to_waypoint(generated_waypoint_id)
    waypoint_observation = contract.observe()
    waypoint_candidate = next(
        item
        for item in contract.agent_view_payload()["runtime_metric_map"]["target_candidates"]
        if item["candidate_type"] == "generated_target_inspection_candidate"
        and item["waypoint_id"] == generated_waypoint_id
    )

    assert waypoint_navigation["ok"] is True
    assert waypoint_navigation["pose_source"] == "inspection_waypoint"
    assert waypoint_observation["waypoint_id"] == generated_waypoint_id
    assert waypoint_candidate["target_actionability_status"] == "actionable"
    assert waypoint_candidate["inspection_budget"]["observed"] is True

    adjustment = contract.adjust_camera(yaw_delta_deg=15)
    assert adjustment["ok"] is True
    assert adjustment["camera_offset"]["yaw_delta_deg"] == 15.0
    confirmed_observation = contract.observe()
    confirmed = next(
        item
        for item in confirmed_observation["visible_object_detections"]
        if item["object_id"] == handle
    )
    post_scan_map = contract.agent_view_payload()["runtime_metric_map"]
    post_scan_candidate = next(
        item for item in post_scan_map["target_candidates"] if item.get("object_id") == handle
    )
    summary = post_scan_map["target_search_summary"]

    assert confirmed["candidate_state"] == "navigation_authorized"
    assert post_scan_candidate["target_actionability_status"] == "actionable"
    assert post_scan_candidate["verified_navigation"] is True
    assert post_scan_candidate["visual_grounding_evidence"]["reviewability_status"] == "reviewable"
    assert summary["camera_adjustment_budget"]["attempt_count"] == 1
    assert summary["inspection_observations"][-1]["camera_adjusted"] is True
    assert any(
        item["changed_candidate_state_count"] >= 1 for item in summary["inspection_observations"]
    )
    assert contract.navigate_to_object(handle)["ok"] is True
    _assert_no_forbidden_keys(post_scan_map)


def test_target_query_recovery_resolves_stale_fixture_id_through_public_anchor() -> None:
    contract = _contract(
        CleanupBackendSession(build_cleanup_scenario(seed=7)),
    )
    _observe_all_public_waypoints(contract)

    runtime_map = contract.agent_view_payload()["runtime_metric_map"]
    direct = resolve_target_query(runtime_map, "sink_01", operation="destination")
    room_query = resolve_target_query(runtime_map, "kitchen", operation="inspect")
    tool = contract.resolve_target_query("sink_01", operation="destination")

    assert direct["status"] == "matched"
    assert direct["best_match"]["anchor_id"].startswith("anchor_fixture_")
    assert "sink" in direct["best_match"]["category"].lower()
    assert direct["best_match"]["actionable_for_operation"] is True
    assert direct["best_match"]["required_next_tool"] in {
        "navigate_to_waypoint",
        "navigate_to_receptacle",
    }
    assert room_query["status"] == "matched"
    assert room_query["best_match"]["waypoint_id"]
    assert room_query["best_match"]["actionable_for_operation"] is True
    assert any("kitchen" in basis for basis in room_query["best_match"]["match_basis"])
    assert direct["public_search_budget"]["viewpoint_budget"]["unvisited_waypoint_count"] == 0
    assert tool["ok"] is True
    assert tool["schema"] == "target_query_resolution_v1"
    assert tool["best_match"]["anchor_id"] == direct["best_match"]["anchor_id"]
    _assert_no_forbidden_keys(tool)


def test_target_query_recovery_not_found_includes_public_search_budget() -> None:
    contract = _contract(
        CleanupBackendSession(build_cleanup_scenario(seed=7)),
    )
    metric_map = _observe_all_public_waypoints(contract)

    resolution = contract.resolve_target_query("purple piano", operation="inspect")

    assert resolution["ok"] is True
    assert resolution["status"] == "not_found"
    assert resolution["match_count"] == 0
    assert resolution["exhausted_public_search_budget"] is True
    assert resolution["missing_target_reason"] == "public_search_budget_exhausted"
    assert resolution["public_search_budget"]["inspection_observation_count"] >= len(
        metric_map["inspection_waypoints"]
    )
    _assert_no_forbidden_keys(resolution)


def test_base_metric_runtime_map_current_anchor_overrides_same_id_prior_anchor() -> None:
    seed_contract = _contract(
        CleanupBackendSession(build_cleanup_scenario(seed=7)),
    )
    _first_non_empty_observation(seed_contract)
    seed_runtime_map = seed_contract.agent_view_payload()["runtime_metric_map"]
    seed_anchor = next(
        item
        for item in seed_runtime_map["public_semantic_anchors"]
        if item["anchor_type"] in {"fixture", "receptacle"}
    )
    prior_snapshot = {
        "public_semantic_anchors": [
            {
                **seed_anchor,
                "freshness": "current_run",
                "promotion_status": "run_local",
                "waypoint_id": "stale_prior_waypoint",
                "pose": {"x": 999.0, "y": 999.0, "yaw": 0.0},
            }
        ]
    }

    contract = _contract(
        CleanupBackendSession(build_cleanup_scenario(seed=7)),
        runtime_map_prior=prior_snapshot,
    )
    _first_non_empty_observation(contract)
    runtime_map = contract.agent_view_payload()["runtime_metric_map"]
    stale_matches = [
        item
        for item in runtime_map["public_semantic_anchors"]
        if item["anchor_id"] == seed_anchor["anchor_id"]
    ]
    current_matches = [
        item
        for item in runtime_map["public_semantic_anchors"]
        if item["category"] == seed_anchor["category"] and item["freshness"] == "current_run"
    ]

    assert stale_matches == []
    assert current_matches
    assert all(item["waypoint_id"] != "stale_prior_waypoint" for item in current_matches)
    assert all(item["pose"] != {"x": 999.0, "y": 999.0, "yaw": 0.0} for item in current_matches)
    assert all(item["promotion_status"] == "run_local" for item in current_matches)
    _assert_no_forbidden_keys(runtime_map)


def test_runtime_map_prior_anchor_keeps_snapshot_waypoint_without_current_evidence() -> None:
    prior_anchor_id = "anchor_fixture_099"
    prior_snapshot = {
        "public_semantic_anchors": [
            {
                "anchor_id": prior_anchor_id,
                "anchor_type": "receptacle",
                "category": "Fridge",
                "label": "Fridge",
                "room_id": "room_8",
                "waypoint_id": "room_8_inspection",
                "pose": {"x": 10.7, "y": 3.2, "yaw": 0.0},
                "pose_source": "inspection_waypoint",
                "pose_role": "best_view_pose",
                "localization_status": "viewpoint_only",
                "affordances": ["observe", "place", "open", "place_inside", "close"],
                "producer_type": "visible_detection",
                "producer_id": "visible_detection",
                "confidence": 0.68,
                "freshness": "current_run",
                "actionability": "actionable",
                "source_observation_id": "waypoint_observation:room_8_inspection",
                "promotion_status": "run_local",
                "evidence": {
                    "type": "support_estimate",
                    "supporting_observed_object_ids": [],
                },
            }
        ]
    }

    contract = _contract(
        CleanupBackendSession(build_cleanup_scenario(seed=7)),
        runtime_map_prior=prior_snapshot,
    )
    runtime_map = contract.agent_view_payload()["runtime_metric_map"]
    matching = [
        item
        for item in runtime_map["public_semantic_anchors"]
        if item["anchor_id"] == prior_anchor_id
    ]
    resolution = contract.resolve_target_query("Fridge")

    assert len(matching) == 1
    anchor = matching[0]
    assert anchor["freshness"] == "prior"
    assert anchor["promotion_status"] == "prior_runtime_snapshot"
    assert anchor["waypoint_id"] == "room_8_inspection"
    assert anchor["room_id"] == "room_8"
    assert anchor["pose"] == {"x": 10.7, "y": 3.2, "yaw": 0.0}
    assert resolution["best_match"]["anchor_id"] == prior_anchor_id
    assert resolution["best_match"]["waypoint_id"] == "room_8_inspection"

    contract.navigate_to_waypoint("room_2_inspection")
    contract.observe()
    post_observe_map = contract.agent_view_payload()["runtime_metric_map"]
    post_observe_anchor = next(
        item
        for item in post_observe_map["public_semantic_anchors"]
        if item["anchor_id"] == prior_anchor_id
    )
    post_observe_resolution = contract.resolve_target_query("Fridge")

    assert post_observe_anchor["freshness"] == "prior"
    assert post_observe_anchor["waypoint_id"] == "room_8_inspection"
    fresh_fridge_anchors = [
        item
        for item in post_observe_map["public_semantic_anchors"]
        if str(item.get("label") or item.get("category") or "").lower() == "fridge"
        and item["freshness"] == "current_run"
    ]
    assert fresh_fridge_anchors
    assert all(item["anchor_id"] != prior_anchor_id for item in fresh_fridge_anchors)
    assert post_observe_resolution["best_match"]["anchor_id"] in {
        prior_anchor_id,
        *(item["anchor_id"] for item in fresh_fridge_anchors),
    }
    _assert_no_forbidden_keys(runtime_map)
    _assert_no_forbidden_keys(post_observe_map)


def test_base_metric_map_keeps_public_waypoint_after_receptacle_navigation() -> None:
    contract = _contract(
        CleanupBackendSession(build_cleanup_scenario(seed=7)),
    )

    observation = _first_non_empty_observation(contract)
    detection = _confirm_world_label_detection(
        contract,
        observation["visible_object_detections"][0],
    )
    fixture = _public_destination_fixture_for_detection(contract, detection)
    fixture_id = str(fixture["fixture_id"])

    assert contract.navigate_to_object(detection["object_id"])["ok"] is True
    assert contract.pick(detection["object_id"])["ok"] is True
    navigation = contract.navigate_to_receptacle(fixture_id)
    post_nav_map = contract.metric_map()

    assert navigation["ok"] is True
    assert str(post_nav_map["robot_pose"]["waypoint_id"]).startswith("room_")
    assert post_nav_map["robot_pose"]["room_id"]
    assert post_nav_map["robot_pose"]["room_id"] != "generated_area"
    assert post_nav_map["robot_pose"]["waypoint_id"] in {
        str(item["waypoint_id"]) for item in post_nav_map["inspection_waypoints"]
    }


def test_base_metric_map_observe_marks_placed_object_non_actionable() -> None:
    contract = _contract(
        CleanupBackendSession(build_cleanup_scenario(seed=7)),
    )

    observation = _first_non_empty_observation(contract)
    detection = _confirm_world_label_detection(
        contract,
        observation["visible_object_detections"][0],
    )
    fixture = _public_destination_fixture_for_detection(contract, detection)
    fixture_id = str(fixture["fixture_id"])

    assert contract.navigate_to_object(detection["object_id"])["ok"] is True
    assert contract.pick(detection["object_id"])["ok"] is True
    assert contract.navigate_to_receptacle(fixture_id)["ok"] is True
    if detection.get("recommended_tool") == "place_inside":
        opened = contract.open_receptacle(fixture_id)
        if opened["ok"]:
            assert contract.place_inside(fixture_id)["ok"] is True
            closed = contract.close_receptacle(fixture_id)
            if closed["ok"]:
                expected_state = "placed_closed"
            else:
                expected_state = "placed"
        else:
            assert contract.place_inside(fixture_id)["ok"] is True
            expected_state = "placed"
    else:
        assert contract.place(fixture_id)["ok"] is True
        expected_state = "placed"

    later = contract.observe()
    later_detection = next(
        item
        for item in later["visible_object_detections"]
        if item["object_id"] == detection["object_id"]
    )
    worklist_item = next(
        item
        for item in contract.cleanup_worklist_payload()["objects"]
        if item["object_id"] == detection["object_id"]
    )
    duplicate_nav = contract.navigate_to_object(detection["object_id"])
    duplicate_pick = contract.pick(detection["object_id"])

    assert later_detection["actionability_status"] in {"already_handled", "needs_visual_evidence"}
    assert worklist_item["state"] == expected_state
    assert "cleanup_recommended" not in worklist_item
    assert duplicate_nav["ok"] is False
    assert duplicate_nav["error_reason"] == "already_handled"
    assert duplicate_pick["ok"] is False
    assert duplicate_pick["error_reason"] == "already_handled"


def test_base_metric_map_done_uses_generated_candidate_coverage() -> None:
    contract = _contract(
        CleanupBackendSession(
            CleanupScenario(
                scenario_id="base-metric-map-done-gate-test",
                task="build base navigation map",
                seed=7,
                objects=(),
                receptacles=(
                    CleanupReceptacle("sink_01", "Sink", "kitchen", category="Sink"),
                    CleanupReceptacle("desk_01", "Desk", "office", category="Desk"),
                ),
                private_manifest=PrivateScoringManifest(
                    scenario_id="base-metric-map-done-gate-test",
                    targets=(),
                    success_threshold=0,
                ),
            )
        ),
    )

    waypoints = contract.metric_map()["inspection_waypoints"]
    for waypoint in waypoints[:-1]:
        contract.navigate_to_waypoint(str(waypoint["waypoint_id"]))
        contract.observe()

    early_done = contract.done("almost finished minimal sweep")

    assert early_done["ok"] is False
    assert early_done["error_reason"] == "insufficient_sweep_coverage"
    assert early_done["next_waypoint_id"] == waypoints[-1]["waypoint_id"]
    assert early_done["observed_waypoint_count"] == len(waypoints) - 1
    assert early_done["total_waypoints"] == len(waypoints)
    assert all(item.endswith("_inspection") for item in early_done["unvisited_waypoint_ids"])

    contract.navigate_to_waypoint(str(waypoints[-1]["waypoint_id"]))
    contract.observe()
    done = contract.done("finished minimal sweep")

    assert done["ok"] is True


def test_realworld_detected_handle_can_be_cleaned_without_private_manifest() -> None:
    contract = _contract(CleanupBackendSession(build_cleanup_scenario(seed=7)))
    detection = _confirm_world_label_detection(
        contract,
        _first_detection_by_category(contract, "dish"),
    )
    target_fixture = _public_destination_fixture_for_detection(contract, detection)
    navigated_object = contract.navigate_to_object(detection["object_id"])
    picked = contract.pick(detection["object_id"])
    navigated_target = contract.navigate_to_receptacle(str(target_fixture["fixture_id"]))
    placed = contract.place(str(target_fixture["fixture_id"]))

    assert navigated_object["ok"] is True
    assert picked["ok"] is True
    assert picked["object_id"].startswith("observed_")
    assert navigated_target["ok"] is True
    assert placed["ok"] is True
    assert str(placed["fixture_id"]).startswith("anchor_fixture_")
    assert placed["location_id"] == "sink_01"


def test_realworld_contract_rejects_skipped_semantic_phases_without_private_truth() -> None:
    contract = _contract(CleanupBackendSession(build_cleanup_scenario(seed=7)))
    detection = _first_detection_by_category(contract, "dish")
    detection = _confirm_world_label_detection(contract, detection)
    target_fixture = _public_destination_fixture_for_detection(contract, detection)

    skipped_pick = contract.pick(detection["object_id"])
    assert skipped_pick["ok"] is False
    assert skipped_pick["error_reason"] == "semantic_order"
    assert skipped_pick["required_tool"] == "navigate_to_object"
    assert skipped_pick["object_id"] == detection["object_id"]
    _assert_no_forbidden_keys(skipped_pick)

    assert contract.navigate_to_object(detection["object_id"])["ok"] is True
    assert contract.pick(detection["object_id"])["ok"] is True

    skipped_place = contract.place(str(target_fixture["fixture_id"]))
    assert skipped_place["ok"] is False
    assert skipped_place["error_reason"] == "semantic_order"
    assert skipped_place["required_tool"] == "navigate_to_receptacle"
    assert skipped_place["fixture_id"] == target_fixture["fixture_id"]
    _assert_no_forbidden_keys(skipped_place)

    assert contract.navigate_to_receptacle(str(target_fixture["fixture_id"]))["ok"] is True
    assert contract.place(str(target_fixture["fixture_id"]))["ok"] is True


def test_realworld_contract_rejects_done_with_pending_public_candidates() -> None:
    contract = _contract(CleanupBackendSession(build_cleanup_scenario(seed=7)))
    _first_non_empty_observation(contract)

    done = contract.done("finished sweep")

    assert done["ok"] is False
    assert done["status"] == "blocked"
    assert done["error_reason"] == "pending_cleanup_candidates"
    assert done["required_tool"] == "adjust_camera"
    assert done["pending_observed_handles"]
    assert done["pending_cleanup_candidates"][0]["candidate_state"] == "visual_scan_required"
    assert done["completion"]["status"] == "blocked"
    assert done["completion"]["blockers"][0]["type"] == "pending_cleanup_candidates"
    assert done["completion"]["blockers"][0]["required_tool"] == "adjust_camera"
    assert "target_receptacle_id" not in str(done)
    _assert_no_forbidden_keys(done)


def test_visual_scan_failure_removes_stale_candidate_from_done_blockers() -> None:
    contract = _contract(CleanupBackendSession(build_cleanup_scenario(seed=7)))
    observation = _first_non_empty_observation(contract)
    candidate = observation["visible_object_detections"][0]

    contract._mark_visual_scan_unresolved(  # noqa: SLF001
        candidate["object_id"],
        reason="visual_scan_confirmation_missing",
    )
    readiness = contract.evaluate_done_readiness()
    blocked_handles = {
        handle
        for blocker in readiness["blockers"]
        for handle in blocker.get("pending_observed_handles", [])
    }

    assert candidate["object_id"] not in blocked_handles


def test_open_ended_done_ignores_unrelated_pending_public_candidates() -> None:
    contract = _contract(
        CleanupBackendSession(build_cleanup_scenario(seed=7)),
        task_prompt="我渴了，帮我找些解渴的东西",
        public_acceptance_config={"task_intent": "open-ended"},
    )
    observation = _first_non_empty_observation(contract)
    assert observation["visible_object_detections"]

    done = contract.done("open-ended operator task satisfied")

    assert done["ok"] is True
    assert done["tool"] == "done"
    readiness = contract.evaluate_done_readiness()
    assert readiness["task_intent"] == "open-ended"
    _assert_no_forbidden_keys(done)


def test_map_build_done_ignores_cleanup_candidates_after_complete_sweep() -> None:
    contract = _contract(
        CleanupBackendSession(build_cleanup_scenario(seed=7)),
        public_acceptance_config={"task_intent": "map-build"},
    )
    for waypoint in contract.metric_map()["inspection_waypoints"]:
        assert contract.navigate_to_waypoint(waypoint["waypoint_id"])["ok"] is True
        assert contract.observe()["ok"] is True

    done = contract.done("map sweep complete")

    assert done["ok"] is True
    assert contract.evaluate_done_readiness()["status"] == "ready"
    _assert_no_forbidden_keys(done)


def test_map_build_done_still_requires_complete_sweep() -> None:
    contract = _contract(
        CleanupBackendSession(build_cleanup_scenario(seed=7)),
        public_acceptance_config={"task_intent": "map-build"},
    )
    observation = _first_non_empty_observation(contract)
    assert observation["visible_object_detections"]

    done = contract.done("map sweep incomplete")

    assert done["ok"] is False
    assert done["error_reason"] == "insufficient_sweep_coverage"
    assert all(
        blocker["type"] != "pending_cleanup_candidates"
        for blocker in done["completion"]["blockers"]
    )
    _assert_no_forbidden_keys(done)


def test_cleanup_intent_keeps_cleanup_done_policy_for_prompt_text() -> None:
    contract = _contract(
        CleanupBackendSession(build_cleanup_scenario(seed=7)),
        task_prompt="我渴了，帮我找些解渴的东西",
        public_acceptance_config={"task_intent": "cleanup"},
    )
    observation = _first_non_empty_observation(contract)
    assert observation["visible_object_detections"]

    done = contract.done("legacy custom-mode task finished")

    assert done["ok"] is False
    assert done["error_reason"] == "pending_cleanup_candidates"
    readiness = contract.evaluate_done_readiness()
    assert readiness["task_intent"] == "cleanup"
    _assert_no_forbidden_keys(done)


def test_world_labels_done_rejects_held_public_candidate_with_receptacle_hint() -> None:
    contract = _contract(CleanupBackendSession(build_cleanup_scenario(seed=7)))
    detection = _confirm_world_label_detection(
        contract,
        _first_detection_by_category(contract, "food"),
    )

    assert contract.navigate_to_object(detection["object_id"])["ok"] is True
    assert contract.pick(detection["object_id"])["ok"] is True

    done = contract.done("finished while holding a public candidate")

    assert done["ok"] is False
    assert done["error_reason"] == "pending_cleanup_candidates"
    assert done["required_tool"] == "navigate_to_receptacle"
    pending = next(
        item
        for item in done["pending_cleanup_candidates"]
        if item["object_id"] == detection["object_id"]
    )
    assert pending["state"] == "held"
    assert pending["required_tool"] == "navigate_to_receptacle"
    assert pending["candidate_fixture_id"] == ""
    assert pending["destination_options"]
    blocker = done["completion"]["blockers"][0]
    assert blocker["required_tool"] == "navigate_to_receptacle"
    _assert_no_forbidden_keys(done)


def test_open_ended_done_still_rejects_held_public_candidate() -> None:
    contract = _contract(
        CleanupBackendSession(build_cleanup_scenario(seed=7)),
        task_prompt="我渴了，帮我找些解渴的东西",
        public_acceptance_config={"task_intent": "open-ended"},
    )
    detection = _confirm_world_label_detection(
        contract,
        _first_detection_by_category(contract, "food"),
    )

    assert contract.navigate_to_object(detection["object_id"])["ok"] is True
    assert contract.pick(detection["object_id"])["ok"] is True

    done = contract.done("open-ended task finished while holding an object")

    assert done["ok"] is False
    assert done["error_reason"] == "pending_cleanup_candidates"
    assert done["required_tool"] == "navigate_to_receptacle"
    assert done["pending_cleanup_candidates"][0]["state"] == "held"
    _assert_no_forbidden_keys(done)


def test_world_labels_sanitized_done_rejects_held_policy_required_object() -> None:
    contract = _contract(
        CleanupBackendSession(build_cleanup_scenario(seed=7)),
        evidence_lane="world-public-labels",
    )
    detection = _confirm_world_label_detection(
        contract,
        _first_detection_by_category(contract, "food"),
    )

    assert contract.navigate_to_object(detection["object_id"])["ok"] is True
    assert contract.pick(detection["object_id"])["ok"] is True
    for waypoint in contract.metric_map()["inspection_waypoints"]:
        if waypoint["visited"]:
            continue
        contract.navigate_to_waypoint(str(waypoint["waypoint_id"]))
        contract.observe()

    done = contract.done("finished while holding")

    assert done["ok"] is False
    assert done["error_reason"] == "pending_cleanup_candidates"
    assert done["required_tool"] == "navigate_to_receptacle"
    pending = next(
        item
        for item in done["pending_cleanup_candidates"]
        if item["object_id"] == detection["object_id"]
    )
    assert pending["object_id"] == detection["object_id"]
    assert pending["state"] == "held"
    assert pending["candidate_fixture_id"] == ""
    assert pending["destination_policy"]["preferred_fixture_categories"] == [
        "fridge",
        "refrigerator",
    ]
    assert any(
        option["candidate_fixture_category"] == "fridge"
        and option["recommended_tool"] == "place_inside"
        and option["candidate_fixture_id"].startswith("anchor_fixture_")
        for option in pending["destination_options"]
    )
    _assert_no_forbidden_keys(done)


def test_world_labels_sanitized_done_rejects_policy_required_pending_objects() -> None:
    contract = _contract(
        CleanupBackendSession(build_cleanup_scenario(seed=7)),
        evidence_lane="world-public-labels",
    )
    observation = _first_non_empty_observation(contract)
    detection = observation["visible_object_detections"][0]

    done = contract.done("finished without cleaning sanitized detections")

    assert done["ok"] is False
    assert done["error_reason"] == "pending_cleanup_candidates"
    assert done["required_tool"] == "adjust_camera"
    assert detection["object_id"] in done["pending_observed_handles"]
    pending = next(
        item
        for item in done["pending_cleanup_candidates"]
        if item["object_id"] == detection["object_id"]
    )
    assert pending["destination_policy_status"] == "policy_required"
    assert pending["candidate_fixture_id"] == ""
    assert pending["candidate_state"] == "visual_scan_required"
    _assert_no_forbidden_keys(done)


def test_realworld_contract_rejects_place_inside_before_opening_fridge() -> None:
    contract = _contract(CleanupBackendSession(build_cleanup_scenario(seed=7)))
    detection = _confirm_world_label_detection(
        contract,
        _first_detection_by_category(contract, "food"),
    )
    target_fixture = _public_destination_fixture_for_detection(contract, detection)
    fixture_id = str(target_fixture["fixture_id"])

    assert fixture_id.startswith("anchor_fixture_")
    assert target_fixture["category"] == "fridge"
    assert contract.navigate_to_object(detection["object_id"])["ok"] is True
    assert contract.pick(detection["object_id"])["ok"] is True
    assert contract.navigate_to_receptacle(fixture_id)["ok"] is True

    skipped_open = contract.place_inside(fixture_id)
    assert skipped_open["ok"] is False
    assert skipped_open["error_reason"] == "semantic_order"
    assert skipped_open["required_tool"] == "open_receptacle"
    _assert_no_forbidden_keys(skipped_open)

    assert contract.open_receptacle(fixture_id)["ok"] is True
    placed = contract.place_inside(fixture_id)
    closed = contract.close_receptacle(fixture_id)

    assert placed["ok"] is True
    assert placed["object_id"] == detection["object_id"]
    assert placed["location_relation"] == "inside"
    assert placed["placement_diagnostic"]["relation"] == "inside"
    assert closed["ok"] is True
    assert closed["tool"] == "close_receptacle"
    assert closed["object_id"] == detection["object_id"]


def test_realworld_contract_routes_bookshelf_as_inside_without_close() -> None:
    contract = _contract(CleanupBackendSession(build_cleanup_scenario(seed=7)))
    detection = _confirm_world_label_detection(
        contract,
        _first_detection_by_category(contract, "book"),
    )
    target_fixture = _public_destination_fixture_for_detection(contract, detection)
    fixture_id = str(target_fixture["fixture_id"])

    assert fixture_id.startswith("anchor_fixture_")
    assert str(target_fixture["category"]).lower() in {"bookshelf", "shelvingunit"}
    assert "place_inside" in target_fixture["affordances"]
    assert "open" not in target_fixture["affordances"]
    assert "close" not in target_fixture["affordances"]
    assert contract.navigate_to_object(detection["object_id"])["ok"] is True
    assert contract.pick(detection["object_id"])["ok"] is True
    assert contract.navigate_to_receptacle(fixture_id)["ok"] is True

    surface_place = contract.place(fixture_id)
    assert surface_place["ok"] is False
    assert surface_place["error_reason"] == "semantic_order"
    assert surface_place["required_tool"] == "place_inside"

    placed = contract.place_inside(fixture_id)
    assert placed["ok"] is True
    assert placed["location_relation"] == "inside"
    assert placed["placement_diagnostic"]["relation"] == "inside"

    skipped_close = contract.close_receptacle(fixture_id)
    assert skipped_close["ok"] is False
    assert skipped_close["required_tool"] == "place_inside"


def test_realworld_agent_view_payload_keeps_private_evaluation_out() -> None:
    contract = _contract(CleanupBackendSession(build_cleanup_scenario(seed=7)))

    contract.metric_map()
    for waypoint in contract.metric_map()["inspection_waypoints"]:
        contract.navigate_to_waypoint(str(waypoint["waypoint_id"]))
        contract.observe()
    agent_view = contract.agent_view_payload()

    assert agent_view["schema"] == agent_view_module.AGENT_VIEW_SCHEMA
    assert agent_view_module.forbidden_private_fields_absent(agent_view) is True
    assert agent_view_module.observed_objects(agent_view)
    assert "generated_mess_set" not in agent_view
    assert "acceptable_destination_sets" not in agent_view
    assert "static_fixture_projection" not in agent_view
    _assert_no_forbidden_keys(agent_view)


def test_realworld_raw_fpv_mode_suppresses_structured_detections() -> None:
    contract = _contract(
        CleanupBackendSession(build_cleanup_scenario(seed=7)),
        perception_mode=RAW_FPV_ONLY_MODE,
    )

    waypoint = contract.metric_map()["inspection_waypoints"][0]
    contract.navigate_to_waypoint(str(waypoint["waypoint_id"]))
    observation = contract.observe()
    agent_view = contract.agent_view_payload()

    assert observation["perception_mode"] == RAW_FPV_ONLY_MODE
    assert observation["structured_detections_available"] is False
    assert observation["visible_object_detections"] == []
    assert observation["raw_fpv_observation"]["observation_id"].startswith("raw_fpv_")
    assert observation["raw_fpv_observation"]["image_artifacts"] == {}
    assert "inline_on_navigate" in observation["instruction"]
    assert "navigate_to_visual_candidate" in observation["instruction"]
    assert "omit target_fixture_id" in observation["instruction"]
    assert "candidate_fixture_id/recommended_tool" in observation["instruction"]
    assert "image_region={type:bbox,value:[x,y,width,height]}" in observation["instruction"]
    assert "left, right, bottom, or top FPV edge" in observation["instruction"]
    assert "for a bottom-edge candidate use pitch_delta_deg=20" in observation["instruction"]
    assert "for a top-edge candidate use pitch_delta_deg=-20" in observation["instruction"]
    assert "overlap without a clear edge direction" in observation["instruction"]
    assert "never reuse the original sliver bbox" in observation["instruction"]
    assert "declare_visual_candidates" not in observation["instruction"]
    assert agent_view_module.perception_mode(agent_view) == RAW_FPV_ONLY_MODE
    assert agent_view_module.structured_detections_available(agent_view) is False
    active_perception = agent_view_module.active_perception(agent_view)
    assert active_perception["raw_fpv_summary"]["observation_count"] == 1
    assert (
        active_perception["raw_fpv_summary"]["artifact_status_counts"]["pending_robot_view_capture"]
        == 1
    )
    assert active_perception["camera_grounded_labels"]["sidecar_status"] == "disabled"
    assert active_perception["visual_candidate_lifecycle"]["model_declared_observation_count"] == 0
    assert agent_view_module.observed_objects(agent_view) == []
    assert agent_view_module.raw_fpv_observations(agent_view)
    assert "support_estimate" not in str(agent_view_module.raw_fpv_observations(agent_view))
    assert "target_receptacle_id" not in str(agent_view_module.raw_fpv_observations(agent_view))
    _assert_no_forbidden_keys(observation)
    _assert_no_forbidden_keys(agent_view)


def test_realworld_raw_fpv_done_gate_scales_to_small_generated_mess_count() -> None:
    scenario = CleanupScenario(
        scenario_id="small-raw-fpv-done-gate-test",
        task="clean a small room",
        seed=7,
        objects=(
            CleanupObject("mug_01", "mug", "dish", "sofa_01"),
            CleanupObject("book_01", "book", "book", "floor_01"),
            CleanupObject("apple_01", "apple", "food", "desk_01"),
        ),
        receptacles=(
            CleanupReceptacle("sofa_01", "Sofa", "living"),
            CleanupReceptacle("floor_01", "Floor", "living", kind="surface"),
            CleanupReceptacle("desk_01", "Desk", "office", kind="surface"),
            CleanupReceptacle("sink_01", "Sink", "kitchen"),
            CleanupReceptacle("bookshelf_01", "Bookshelf", "living"),
            CleanupReceptacle("fridge_01", "Fridge", "kitchen"),
        ),
        private_manifest=PrivateScoringManifest(
            scenario_id="small-raw-fpv-done-gate-test",
            targets=(
                TargetRule("mug_01", ("sink_01",)),
                TargetRule("book_01", ("bookshelf_01",)),
                TargetRule("apple_01", ("fridge_01",)),
            ),
            success_threshold=2,
        ),
    )
    contract = _contract(
        CleanupBackendSession(scenario),
        perception_mode=RAW_FPV_ONLY_MODE,
        public_acceptance_config={"required_model_declared_observations": 3},
    )

    _observe_raw_fpv_heading_sweep(contract)

    contract._model_declared_observations = [{}, {}]  # noqa: SLF001
    shortfall = contract.done("small raw-fpv rehearsal shortfall")
    contract._model_declared_observations.append({})  # noqa: SLF001
    done = contract.done("small raw-fpv rehearsal complete")

    assert shortfall["ok"] is False
    assert shortfall["status"] == "blocked"
    assert shortfall["error_reason"] == "insufficient_model_declared_observations"
    assert shortfall["required_model_declared_observations"] == 3
    assert shortfall["completion"]["status"] == "blocked"
    assert shortfall["completion"]["blockers"][0]["type"] == (
        "insufficient_model_declared_observations"
    )
    assert done["ok"] is True
    assert done["cleanup_status"] == "failed"


def test_realworld_raw_fpv_camera_adjustment_is_bounded_and_resets() -> None:
    contract = _contract(
        CleanupBackendSession(build_cleanup_scenario(seed=7)),
        perception_mode=RAW_FPV_ONLY_MODE,
    )

    waypoints = contract.metric_map()["inspection_waypoints"]
    contract.navigate_to_waypoint(str(waypoints[0]["waypoint_id"]))
    adjusted = contract.adjust_camera(yaw_delta_deg=90, pitch_delta_deg=-90)
    observation = contract.observe()
    contract.navigate_to_waypoint(str(waypoints[1]["waypoint_id"]))
    reset_observation = contract.observe()

    assert adjusted["camera_offset"] == {"yaw_delta_deg": 45.0, "pitch_delta_deg": -20.0}
    assert observation["raw_fpv_observation"]["camera_offset"] == adjusted["camera_offset"]
    assert reset_observation["raw_fpv_observation"]["camera_offset"] == {
        "yaw_delta_deg": 0.0,
        "pitch_delta_deg": 0.0,
    }


def test_minimal_raw_fpv_waypoint_navigation_moves_backend_before_capture(
    tmp_path: Path,
) -> None:
    scenario = build_cleanup_scenario(seed=7)
    backend = _PoseRecordingBackend(scenario)
    contract = RealWorldCleanupContract(
        CleanupBackendSession(scenario, backend=backend),
        perception_mode=RAW_FPV_ONLY_MODE,
        map_bundle_dir=PREBUILT_BUNDLE,
    )
    waypoints = contract.metric_map()["inspection_waypoints"]
    first_waypoint = waypoints[0]
    second_waypoint = waypoints[1]

    first_nav = contract.navigate_to_waypoint(str(first_waypoint["waypoint_id"]))
    first_observation = contract.observe()
    first_raw = first_observation["raw_fpv_observation"]
    first_views = backend.write_robot_views(
        tmp_path,
        label=str(first_raw["observation_id"]),
    )["views"]
    first_artifact = contract.attach_raw_fpv_observation_artifact(
        first_raw["observation_id"],
        views=first_views,
    )

    second_nav = contract.navigate_to_waypoint(str(second_waypoint["waypoint_id"]))
    second_observation = contract.observe()
    second_raw = second_observation["raw_fpv_observation"]
    second_views = backend.write_robot_views(
        tmp_path,
        label=str(second_raw["observation_id"]),
    )["views"]
    second_artifact = contract.attach_raw_fpv_observation_artifact(
        second_raw["observation_id"],
        views=second_views,
    )

    assert first_nav["waypoint_id"] == first_waypoint["waypoint_id"]
    assert second_nav["waypoint_id"] == second_waypoint["waypoint_id"]
    assert backend.navigation_targets == []
    assert first_nav["backend_goal_pose"]["waypoint_id"] == first_waypoint["waypoint_id"]
    assert second_nav["backend_goal_pose"]["waypoint_id"] == second_waypoint["waypoint_id"]
    assert backend.view_poses[0] == {"receptacle_id": "unknown"}
    assert backend.view_poses[1] == {"receptacle_id": "unknown"}
    assert first_artifact is not None
    assert second_artifact is not None
    assert first_artifact["image_artifacts"]["fpv"] != second_artifact["image_artifacts"]["fpv"]
    assert first_views["verify"] != second_views["verify"]
    assert first_views["topdown"] != second_views["topdown"]
    assert str(first_raw["observation_id"]) in first_artifact["image_artifacts"]["fpv"]
    assert str(second_raw["observation_id"]) in second_artifact["image_artifacts"]["fpv"]


def test_realworld_unresolved_model_declared_candidate_is_unpickable() -> None:
    contract = _contract(
        CleanupBackendSession(build_cleanup_scenario(seed=7)),
        perception_mode=RAW_FPV_ONLY_MODE,
    )

    waypoint = contract.metric_map()["inspection_waypoints"][0]
    contract.navigate_to_waypoint(str(waypoint["waypoint_id"]))
    observation = contract.observe()
    declared = contract.declare_visual_candidates(
        observation["raw_fpv_observation"]["observation_id"],
        candidates=[
            {
                "category": "imaginary widget",
                "evidence_note": "ambiguous tiny object in the far corner",
                "image_region": {"type": "verbal_region", "value": "far corner"},
            }
        ],
        producer_type="main_cleanup_agent",
        producer_id="test_agent",
    )
    candidate = declared["model_declared_observations"][0]
    picked = contract.pick(candidate["object_id"])

    assert candidate["grounding_status"] == "unresolved"
    assert "No public actionable object matched" in candidate["recovery_hint"]
    assert picked["ok"] is False
    assert picked["error_reason"] == "visual_candidate_not_resolved"
    worklist_item = next(
        item
        for item in contract.cleanup_worklist_payload()["objects"]
        if item["object_id"] == candidate["object_id"]
    )
    assert worklist_item["state"] == "grounding_unresolved"
    assert worklist_item["cleanup_recommended"] is False
    assert candidate["private_truth_included"] is False
    _assert_no_forbidden_keys(declared)
    _assert_no_forbidden_keys(picked)


def test_realworld_navigate_to_unresolved_visual_candidate_says_continue_sweep() -> None:
    contract = _contract(
        CleanupBackendSession(build_cleanup_scenario(seed=7)),
        perception_mode=RAW_FPV_ONLY_MODE,
    )

    waypoint = contract.metric_map()["inspection_waypoints"][0]
    contract.navigate_to_waypoint(str(waypoint["waypoint_id"]))
    observation = contract.observe()
    response = contract.navigate_to_visual_candidate(
        observation["raw_fpv_observation"]["observation_id"],
        category="imaginary widget",
        evidence_note="ambiguous tiny object in the far corner",
        image_region={"type": "verbal_region", "value": "far corner"},
        producer_type="main_cleanup_agent",
        producer_id="test_agent",
    )

    assert response["ok"] is False
    assert response["error_reason"] == "visual_candidate_not_resolved"
    assert response["required_next_tool"] == "navigate_to_relative_pose"
    assert "adjust_camera" in response["recovery_tool_options"]
    assert "unchanged pose" in response["recovery_hint"]
    assert "No public actionable object matched" in response["recovery_hint"]
    assert "instead of looping" in response["recovery_hint"]
    _assert_no_forbidden_keys(response)


def test_realworld_raw_fpv_grounding_uses_source_observation_bbox_binding(
    tmp_path: Path,
    monkeypatch,
) -> None:
    scenario = build_cleanup_scenario(seed=7)
    session = CleanupBackendSession(scenario)
    contract = _contract(session, perception_mode=RAW_FPV_ONLY_MODE)
    target = scenario.objects[0]
    target_location = session.object_locations()[target.object_id]
    waypoint = next(
        item
        for item in contract.metric_map()["inspection_waypoints"]
        if target_location
        not in set(contract._private_waypoint_for_public_waypoint(item).get("fixture_ids") or [])
    )
    contract.navigate_to_waypoint(str(waypoint["waypoint_id"]))
    observation = contract.observe()
    observation_id = observation["raw_fpv_observation"]["observation_id"]
    fpv_path = tmp_path / "raw_fpv_001.fpv.png"
    bindings_path = fpv_path.with_suffix(".bindings.private.json")
    bindings_path.write_text(
        json.dumps(
            {
                "schema": "raw_fpv_private_bindings_v1",
                "image_dimensions": {"width": 540, "height": 360},
                "bindings": [
                    {
                        "object_id": target.object_id,
                        "category": target.category,
                        "name": target.name,
                        "location_id": target_location,
                        "bbox": [100, 80, 80, 60],
                        "object_pixels": 3200,
                    },
                    {
                        "object_id": "low_pixel_bbox_distractor",
                        "category": target.category,
                        "name": f"distant {target.name}",
                        "location_id": target_location,
                        "bbox": [105, 85, 70, 50],
                        "object_pixels": 5,
                    },
                ],
            },
            sort_keys=True,
        ),
        encoding="utf-8",
    )
    contract.attach_raw_fpv_observation_artifact(
        observation_id,
        views={"fpv": str(fpv_path)},
    )

    match = realworld_visual_candidate_lifecycle.resolve_visual_candidate(
        contract,
        contract._private_waypoint_for_public_waypoint(waypoint),
        {
            "source_observation_id": observation_id,
            "category": target.category,
            "source_fixture_id": contract._public_fixture_reference_id(target_location),
            "image_region": {"type": "bbox", "value": [105, 85, 70, 50]},
        },
    )

    assert match["status"] == "resolved"
    assert match["objects"][0].object_id == target.object_id
    assert match["locality_status"] == "exact_source_fixture_in_source_observation"
    assert match["binding_source"] == "private_observation_segmentation"
    monkeypatch.setattr(
        realworld_visual_candidate_lifecycle,
        "objects_visible_from_waypoint",
        lambda _contract, _waypoint: [(target, target_location)],
    )
    simulated_inputs = (
        realworld_visual_candidate_declarations.simulated_raw_fpv_inputs_for_observation(
            contract,
            waypoint,
            observation_id=observation_id,
        )
    )
    assert simulated_inputs == [
        {
            "category": target.category,
            "source_fixture_id": contract._public_fixture_reference_id(target_location),
            "evidence_note": (
                "simulated camera model declared a public camera-derived "
                f"{target.category} candidate"
            ),
            "image_region": {"type": "bbox", "value": [100, 80, 80, 60]},
            "confidence": 0.9,
        }
    ]
    assert target.object_id not in json.dumps(simulated_inputs)
    assert target_location not in json.dumps(simulated_inputs)


def test_simulated_raw_fpv_inputs_only_fall_back_for_synthetic_backend(monkeypatch) -> None:
    scenario = build_cleanup_scenario(seed=7)
    session = CleanupBackendSession(scenario)
    contract = _contract(session, perception_mode=RAW_FPV_ONLY_MODE)
    target = scenario.objects[0]
    target_location = session.object_locations()[target.object_id]
    waypoint = contract.metric_map()["inspection_waypoints"][0]
    monkeypatch.setattr(
        realworld_visual_candidate_lifecycle,
        "objects_visible_from_waypoint",
        lambda _contract, _waypoint: [(target, target_location)],
    )

    synthetic_inputs = (
        realworld_visual_candidate_declarations.simulated_raw_fpv_inputs_for_observation(
            contract,
            waypoint,
            observation_id="synthetic-observation-without-bindings",
        )
    )

    assert len(synthetic_inputs) == 1
    assert synthetic_inputs[0]["category"] == target.category
    assert synthetic_inputs[0]["source_fixture_id"] == target_location
    assert synthetic_inputs[0]["image_region"]["type"] == "bbox"
    assert "target_fixture_id" not in synthetic_inputs[0]

    monkeypatch.setattr(
        session.backend,
        "backend",
        MOLMOSPACES_SUBPROCESS_BACKEND,
        raising=False,
    )
    real_backend_inputs = (
        realworld_visual_candidate_declarations.simulated_raw_fpv_inputs_for_observation(
            contract,
            waypoint,
            observation_id="real-observation-without-bindings",
        )
    )

    assert real_backend_inputs == []


def test_realworld_unresolved_visual_candidates_do_not_count_as_model_declared_actions() -> None:
    contract = _contract(
        CleanupBackendSession(build_cleanup_scenario(seed=7)),
        perception_mode=RAW_FPV_ONLY_MODE,
    )

    waypoint = contract.metric_map()["inspection_waypoints"][0]
    contract.navigate_to_waypoint(str(waypoint["waypoint_id"]))
    observation = contract.observe()
    response = contract.navigate_to_visual_candidate(
        observation["raw_fpv_observation"]["observation_id"],
        category="imaginary widget",
        evidence_note="ambiguous tiny object in the far corner",
        image_region={"type": "verbal_region", "value": "far corner"},
        producer_type="main_cleanup_agent",
        producer_id="test_agent",
    )
    evidence = contract.model_declared_observations_payload()

    assert response["ok"] is False
    assert response["error_reason"] == "visual_candidate_not_resolved"
    assert evidence["observation_count"] == 1
    assert evidence["acted_count"] == 0
    assert evidence["observations"][0]["grounding_status"] == "unresolved"
    assert evidence["observations"][0]["acted_on"] is False


def test_realworld_done_does_not_require_unresolved_visual_candidates() -> None:
    contract = _contract(
        CleanupBackendSession(build_cleanup_scenario(seed=7)),
        perception_mode=RAW_FPV_ONLY_MODE,
    )

    waypoint = contract.metric_map()["inspection_waypoints"][0]
    contract.navigate_to_waypoint(str(waypoint["waypoint_id"]))
    observation = contract.observe()
    for index in range(7):
        declared = contract.declare_visual_candidates(
            observation["raw_fpv_observation"]["observation_id"],
            candidates=[
                {
                    "category": f"imaginary widget {index}",
                    "evidence_note": "unresolved visual guess",
                    "image_region": {"type": "verbal_region", "value": f"far corner {index}"},
                }
            ],
            producer_type="main_cleanup_agent",
            producer_id="test_agent",
        )
        assert declared["model_declared_observations"][0]["grounding_status"] == "unresolved"

    early_done = contract.done("finished with unresolved false positives")

    assert early_done["ok"] is False
    assert early_done["error_reason"] == "insufficient_sweep_coverage"
    assert early_done["required_tool"] == "navigate_to_waypoint"
    assert early_done["next_waypoint_id"]
    assert early_done["sweep_coverage_rate"] < 0.90

    _observe_raw_fpv_heading_sweep(contract)

    done = contract.done("finished with unresolved false positives")

    assert done["ok"] is True
    assert done["tool"] == "done"
    _assert_no_forbidden_keys(done)


def test_realworld_done_rejects_one_missing_public_waypoint() -> None:
    contract = _contract(
        CleanupBackendSession(
            CleanupScenario(
                scenario_id="missing-waypoint-gate-test",
                task="check full public sweep",
                seed=7,
                objects=(),
                receptacles=(
                    CleanupReceptacle("sink_01", "Sink", "kitchen", category="Sink"),
                    CleanupReceptacle("desk_01", "Desk", "office", category="Desk"),
                ),
                private_manifest=PrivateScoringManifest(
                    scenario_id="missing-waypoint-gate-test",
                    targets=(),
                    success_threshold=0,
                ),
            )
        ),
    )

    waypoints = contract.metric_map()["inspection_waypoints"]
    for waypoint in waypoints[:-1]:
        contract.navigate_to_waypoint(str(waypoint["waypoint_id"]))
        contract.observe()

    early_done = contract.done("finished after almost all waypoints")

    assert early_done["ok"] is False
    assert early_done["status"] == "blocked"
    assert early_done["error_reason"] == "insufficient_sweep_coverage"
    assert early_done["required_tool"] == "navigate_to_waypoint"
    assert early_done["next_waypoint_id"] == waypoints[-1]["waypoint_id"]
    assert early_done["observed_waypoint_count"] == len(waypoints) - 1
    assert early_done["total_waypoints"] == len(waypoints)
    assert early_done["completion"]["blockers"][0]["type"] == "insufficient_sweep_coverage"


def test_world_labels_requested_run_size_does_not_enable_raw_fpv_grounded_chain_gate() -> None:
    contract = _contract(
        CleanupBackendSession(_empty_cleanup_scenario("world-public-labels-readiness-policy-test")),
        public_acceptance_config={"requested_run_size": 5},
    )

    for waypoint in contract.metric_map()["inspection_waypoints"]:
        contract.navigate_to_waypoint(str(waypoint["waypoint_id"]))
        contract.observe()

    done = contract.done("world-public-labels run completed after public sweep")

    assert done["ok"] is True
    assert done["tool"] == "done"
    _assert_no_forbidden_keys(done)


def test_camera_raw_requested_run_size_enables_grounded_chain_gate_after_sweep() -> None:
    contract = _contract(
        CleanupBackendSession(_empty_cleanup_scenario("camera-raw-fpv-readiness-policy-test")),
        perception_mode=RAW_FPV_ONLY_MODE,
        public_acceptance_config={"requested_run_size": 5},
    )

    observation = _observe_raw_fpv_heading_sweep(contract)
    for index in range(5):
        declared = contract.declare_visual_candidates(
            observation["raw_fpv_observation"]["observation_id"],
            candidates=[
                {
                    "category": f"imaginary widget {index}",
                    "evidence_note": "unresolved visual guess for readiness policy",
                    "image_region": {"type": "verbal_region", "value": f"empty area {index}"},
                }
            ],
            producer_type="main_cleanup_agent",
            producer_id="test_agent",
        )
        assert declared["model_declared_observations"][0]["grounding_status"] == "unresolved"

    for waypoint in contract.metric_map()["inspection_waypoints"]:
        contract.navigate_to_waypoint(str(waypoint["waypoint_id"]))
        contract.adjust_camera(yaw_delta_deg=45, pitch_delta_deg=20)
        contract.observe()

    done = contract.done("camera-raw-fpv run finished without grounded cleanup chains")

    assert done["ok"] is False
    assert done["error_reason"] == "insufficient_grounded_cleanup_chains"
    assert done["required_tool"] == "navigate_to_visual_candidate"
    blocker = done["completion"]["blockers"][0]
    assert blocker["type"] == "insufficient_grounded_cleanup_chains"
    assert blocker["policy_id"] == DONE_READINESS_POLICY_RAW_FPV
    assert blocker["required"] == 4
    assert blocker["required_tool"] == "navigate_to_visual_candidate"
    _assert_no_forbidden_keys(done)


def test_world_labels_explicit_grounded_chain_gate_uses_world_label_tooling() -> None:
    contract = _contract(
        CleanupBackendSession(
            _empty_cleanup_scenario("world-public-labels-explicit-readiness-test")
        ),
        public_acceptance_config={"required_grounded_cleanup_chains": 2},
    )

    for waypoint in contract.metric_map()["inspection_waypoints"]:
        contract.navigate_to_waypoint(str(waypoint["waypoint_id"]))
        contract.observe()

    done = contract.done("world-public-labels run explicitly requires public chains")

    assert done["ok"] is False
    assert done["error_reason"] == "insufficient_grounded_cleanup_chains"
    assert done["required_tool"] == "navigate_to_object"
    blocker = done["completion"]["blockers"][0]
    assert blocker["policy_id"] == DONE_READINESS_POLICY_EXPLICIT
    assert blocker["required_tool"] == "navigate_to_object"
    assert "navigate_to_visual_candidate" not in blocker["recovery_hint"]
    _assert_no_forbidden_keys(done)


def test_realworld_navigate_to_visual_candidate_returns_grounded_handle() -> None:
    contract = _contract(
        CleanupBackendSession(build_cleanup_scenario(seed=7)),
        perception_mode=RAW_FPV_ONLY_MODE,
    )

    observation = _observe_raw_fpv_category(contract, category="food")
    response = contract.navigate_to_visual_candidate(
        observation["raw_fpv_observation"]["observation_id"],
        category="tomato",
        evidence_note="round produce item on the desk",
        image_region={"type": "bbox", "value": [0.12, 0.24, 0.18, 0.16]},
        producer_type="main_cleanup_agent",
        producer_id="test_agent",
    )

    assert response["ok"] is True
    assert response["tool"] == "navigate_to_visual_candidate"
    assert response["object_id"].startswith("observed_")
    assert response["declaration_strategy"] == "inline_on_navigate"
    assert response["required_next_tool"] == "pick"
    assert response["model_declared_observation"]["grounding_status"] == "resolved"
    assert response["actionability_status"] == "actionable"
    assert response["visual_grounding_evidence"]["reviewability_status"] == "reviewable"
    assert response["visual_grounding_evidence"]["bbox_coordinate_space"] == "normalized_xywh"
    assert contract.pick(response["object_id"])["ok"] is True
    _assert_no_forbidden_keys(response)


def test_realworld_raw_fpv_non_recommended_candidate_cannot_navigate_or_pick() -> None:
    scenario = CleanupScenario(
        scenario_id="raw-fpv-not-recommended-test",
        task="leave an already tidy mug in place",
        seed=7,
        objects=(CleanupObject("mug_01", "mug", "dish", "sink_01"),),
        receptacles=(CleanupReceptacle("sink_01", "Sink", "kitchen", category="Sink"),),
        private_manifest=PrivateScoringManifest(
            scenario_id="raw-fpv-not-recommended-test",
            targets=(),
            success_threshold=0,
        ),
    )
    contract = _contract(
        CleanupBackendSession(scenario),
        perception_mode=RAW_FPV_ONLY_MODE,
    )

    observation = _observe_raw_fpv_category(contract, category="dish")
    response = contract.navigate_to_visual_candidate(
        observation["raw_fpv_observation"]["observation_id"],
        category="mug",
        evidence_note="mug already resting at its normal sink destination",
        image_region={"type": "bbox", "value": [0.2, 0.2, 0.2, 0.2]},
        producer_type="main_cleanup_agent",
        producer_id="test_agent",
    )

    assert response["ok"] is False
    assert response["error_reason"] == "visual_candidate_not_cleanup_recommended"
    assert response["cleanup_recommended"] is False
    assert "do not call navigate_to_waypoint again" in response["recovery_hint"]
    assert response["required_next_tool"] == "observe"
    object_id = response["object_id"]
    assert contract.navigate_to_object(object_id)["error_reason"] == (
        "visual_candidate_not_cleanup_recommended"
    )
    assert contract.pick(object_id)["error_reason"] == "visual_candidate_not_cleanup_recommended"
    _assert_no_forbidden_keys(response)


def test_raw_fpv_done_requires_canonical_distinct_heading_coverage() -> None:
    contract = _contract(
        CleanupBackendSession(_empty_cleanup_scenario("raw-fpv-heading-coverage-test")),
        perception_mode=RAW_FPV_ONLY_MODE,
    )

    for waypoint in contract.metric_map()["inspection_waypoints"]:
        contract.navigate_to_waypoint(str(waypoint["waypoint_id"]))
        for _ in range(4):
            contract.observe()
            _set_latest_raw_fpv_heading(contract, 0.0)

    repeated_pose_done = contract.done("repeated the same camera heading")

    assert repeated_pose_done["ok"] is False
    assert repeated_pose_done["error_reason"] == "insufficient_raw_fpv_heading_coverage"
    assert repeated_pose_done["required_distinct_heading_count"] == 4
    assert repeated_pose_done["current_distinct_heading_count"] == 1
    assert repeated_pose_done["required_tool"] == "navigate_to_waypoint"

    _observe_raw_fpv_heading_sweep(contract, headings=(90.0, 180.0, 270.0))

    done = contract.done("covered four distinct headings per public waypoint")
    assert done["ok"] is True
    _assert_no_forbidden_keys(done)


def test_raw_fpv_done_requires_bounded_overlap_probe_for_candidate_free_closeout() -> None:
    contract = _contract(
        CleanupBackendSession(_empty_cleanup_scenario("raw-fpv-overlap-probe-test")),
        perception_mode=RAW_FPV_ONLY_MODE,
        public_acceptance_config={"required_grounded_cleanup_chains": 1},
    )
    _observe_raw_fpv_heading_sweep(contract)

    pitch_only_waypoint = str(contract.metric_map()["inspection_waypoints"][0]["waypoint_id"])
    contract.navigate_to_waypoint(pitch_only_waypoint)
    contract.observe()
    contract._raw_fpv_observations[-1]["camera_offset"] = {  # noqa: SLF001
        "yaw_delta_deg": 90,
        "pitch_delta_deg": 40,
    }
    contract.adjust_camera(pitch_delta_deg=20)
    contract.observe()

    overlap_blocked = contract.done("covered headings but only made a pitch probe")
    assert overlap_blocked["ok"] is False
    assert overlap_blocked["error_reason"] == "insufficient_raw_fpv_overlap_probe_coverage"
    assert overlap_blocked["required_camera_adjustment"] == {
        "yaw_delta_deg": 45,
        "pitch_delta_deg": 20,
    }
    assert overlap_blocked["required_tool"] == "navigate_to_waypoint"
    assert overlap_blocked["followup_tool"] == "adjust_camera"
    assert overlap_blocked["probed_candidate_free_waypoint_ids"] == []
    assert "private target truth" in overlap_blocked["recovery_hint"]

    for waypoint in contract.metric_map()["inspection_waypoints"]:
        contract.navigate_to_waypoint(str(waypoint["waypoint_id"]))
        contract.adjust_camera(yaw_delta_deg=45, pitch_delta_deg=20)
        contract.observe()

    still_blocked = contract.done("covered headings and bounded overlap probes")
    assert still_blocked["ok"] is False
    assert still_blocked["error_reason"] == "insufficient_grounded_cleanup_chains"
    assert all(
        blocker["type"] != "insufficient_raw_fpv_overlap_probe_coverage"
        for blocker in still_blocked["completion"]["blockers"]
    )
    _assert_no_forbidden_keys(still_blocked)


def test_open_ended_raw_fpv_done_does_not_require_whole_room_heading_coverage() -> None:
    contract = _contract(
        CleanupBackendSession(_empty_cleanup_scenario("open-ended-raw-fpv-heading-test")),
        perception_mode=RAW_FPV_ONLY_MODE,
        public_acceptance_config={"task_intent": "open-ended"},
    )

    done = contract.done("task-scoped public search is complete")

    assert done["ok"] is True
    assert all(
        blocker["type"] != "insufficient_raw_fpv_heading_coverage"
        for blocker in contract.evaluate_done_readiness()["blockers"]
    )
    _assert_no_forbidden_keys(done)


def test_grounded_chain_gate_counts_only_cleanup_recommended_handles() -> None:
    contract = _contract(
        CleanupBackendSession(_empty_cleanup_scenario("recommended-chain-count-test")),
        perception_mode=RAW_FPV_ONLY_MODE,
        public_acceptance_config={"required_grounded_cleanup_chains": 2},
    )
    contract._detections_by_handle = {  # noqa: SLF001
        "observed_recommended": {"cleanup_recommended": True},
        "observed_not_recommended": {"cleanup_recommended": False},
    }

    blocker = realworld_done_readiness.grounded_cleanup_chain_blocker(
        contract,
        {
            "complete_semantic_substep_objects": 2,
            "complete_semantic_substep_object_ids": [
                "observed_recommended",
                "observed_not_recommended",
            ],
            "semantic_substep_count": 2,
        },
        raw_fpv_only_mode=RAW_FPV_ONLY_MODE,
        assert_no_forbidden_agent_view_keys=_assert_no_forbidden_keys,
    )

    assert blocker is not None
    assert blocker["current"] == 1
    assert blocker["complete_semantic_substep_object_ids"] == ["observed_recommended"]
    assert blocker["required"] == 2


def test_realworld_raw_fpv_visual_candidate_requires_reviewable_fpv_bbox() -> None:
    contract = _contract(
        CleanupBackendSession(build_cleanup_scenario(seed=7)),
        perception_mode=RAW_FPV_ONLY_MODE,
    )

    observation = _observe_raw_fpv_category(contract, category="food")
    response = contract.navigate_to_visual_candidate(
        observation["raw_fpv_observation"]["observation_id"],
        category="tomato",
        evidence_note="round produce item on the desk",
        image_region={"type": "verbal_region", "value": "front of desk"},
        producer_type="main_cleanup_agent",
        producer_id="test_agent",
    )

    declaration = response["model_declared_observation"]
    evidence = response["visual_grounding_evidence"]
    assert response["ok"] is False
    assert response["error_reason"] == "visual_evidence_not_reviewable"
    assert response["required_next_tool"] == "observe"
    assert response["actionability_status"] == "needs_visual_evidence"
    assert declaration["grounding_status"] == "resolved"
    assert declaration["actionability_status"] == "needs_visual_evidence"
    assert evidence["schema"] == "visual_grounding_evidence_v1"
    assert evidence["camera_frame"] == "agent_facing_fpv"
    assert evidence["reviewability_status"] == "not_reviewable"
    assert evidence["reviewability_reason"] == "missing_bbox"
    assert contract.pick(response["object_id"])["error_reason"] == "visual_evidence_not_reviewable"
    worklist_item = next(
        item
        for item in contract.cleanup_worklist_payload()["objects"]
        if item["object_id"] == response["object_id"]
    )
    assert worklist_item["cleanup_recommended"] is False
    assert worklist_item["actionability_status"] == "needs_visual_evidence"
    _assert_no_forbidden_keys(response)


def test_minimal_raw_fpv_visual_candidate_can_omit_target_fixture_id() -> None:
    contract = _contract(
        CleanupBackendSession(build_cleanup_scenario(seed=7)),
        perception_mode=RAW_FPV_ONLY_MODE,
    )

    observation = _observe_raw_fpv_category(contract, category="food")
    response = contract.navigate_to_visual_candidate(
        observation["raw_fpv_observation"]["observation_id"],
        category="tomato",
        evidence_note="round produce item on the desk",
        image_region={"type": "bbox", "value": [0.12, 0.24, 0.18, 0.16]},
        producer_type="main_cleanup_agent",
        producer_id="test_agent",
    )
    target_anchor_id = response["candidate_fixture_id"]

    declaration = response["model_declared_observation"]
    assert response["ok"] is True
    assert response["candidate_fixture_id"] == target_anchor_id
    assert response["candidate_fixture_category"] == "fridge"
    assert response["recommended_tool"] == "place_inside"
    assert declaration["target_fixture_id"] == ""
    assert declaration["target_fixture_category"] == ""
    assert declaration["target_plausibility"]["status"] == "unknown_fixture"
    worklist = contract.cleanup_worklist_payload()
    worklist_item = next(
        item for item in worklist["objects"] if item["object_id"] == response["object_id"]
    )
    assert worklist_item["cleanup_recommended"] is True
    assert worklist_item["actionability_status"] == "actionable"
    assert worklist_item["candidate_fixture_id"] == target_anchor_id
    assert worklist_item["recommended_tool"] == "place_inside"
    assert contract.pick(response["object_id"])["ok"] is True
    _assert_no_forbidden_keys(response)


def test_minimal_raw_fpv_visual_candidate_requires_public_destination() -> None:
    contract = _contract(
        CleanupBackendSession(build_cleanup_scenario(seed=7)),
        perception_mode=RAW_FPV_ONLY_MODE,
    )

    waypoint = contract.metric_map()["inspection_waypoints"][0]
    contract.navigate_to_waypoint(str(waypoint["waypoint_id"]))
    observation = contract.observe()
    response = contract.navigate_to_visual_candidate(
        observation["raw_fpv_observation"]["observation_id"],
        category="plant",
        evidence_note="plant visible on nearby surface",
        image_region={"type": "bbox", "value": [0.2, 0.2, 0.2, 0.2]},
        producer_type="main_cleanup_agent",
        producer_id="test_agent",
    )

    assert response["ok"] is False
    assert response["error_reason"] == "visual_candidate_not_resolved"
    assert response["object_id"].startswith("observed_")
    assert response["grounding_status"] == "unresolved"
    assert response["required_next_tool"] == "navigate_to_relative_pose"
    assert "No public actionable object matched" in response["recovery_hint"]
    assert contract.pick(response["object_id"])["ok"] is False
    _assert_no_forbidden_keys(response)


def test_realworld_raw_fpv_rejects_already_handled_visual_candidate_without_navigation() -> None:
    contract = _contract(
        CleanupBackendSession(build_cleanup_scenario(seed=7)),
        perception_mode=RAW_FPV_ONLY_MODE,
    )

    observation = _observe_raw_fpv_category(contract, category="food")
    raw_observation_id = observation["raw_fpv_observation"]["observation_id"]
    first = contract.navigate_to_visual_candidate(
        raw_observation_id,
        category="tomato",
        evidence_note="round produce item on the desk",
        image_region={"type": "bbox", "value": [0.12, 0.24, 0.18, 0.16]},
        producer_type="main_cleanup_agent",
        producer_id="test_agent",
    )
    retry_before_place = contract.navigate_to_visual_candidate(
        raw_observation_id,
        category="tomato",
        evidence_note="same produce item before pick",
        image_region={"type": "bbox", "value": [0.12, 0.24, 0.18, 0.16]},
        producer_type="main_cleanup_agent",
        producer_id="test_agent",
    )

    handle = first["object_id"]
    assert first["ok"] is True
    assert retry_before_place["ok"] is True
    assert retry_before_place["object_id"] == handle
    fixture_id = str(first["candidate_fixture_id"])
    declared_before_place = contract.model_declared_observations_payload()["observation_count"]
    assert contract.pick(handle)["ok"] is True
    assert contract.navigate_to_receptacle(fixture_id)["ok"] is True
    assert contract.open_receptacle(fixture_id)["ok"] is True
    assert contract.place_inside(fixture_id)["ok"] is True
    if "close" in contract.public_receptacles_by_id()[fixture_id].get("affordances", []):
        assert contract.close_receptacle(fixture_id)["ok"] is True

    contract.navigate_to_waypoint(
        str(contract.public_receptacles_by_id()[fixture_id]["preferred_inspection_waypoint_id"])
    )
    later_observation = contract.observe()
    lifecycle_before = dict(contract._object_lifecycle[handle])
    current_handle_before = contract._current_object_handle
    held_handle_before = contract._held_handle
    duplicate = contract.navigate_to_visual_candidate(
        later_observation["raw_fpv_observation"]["observation_id"],
        category="food",
        evidence_note="produce-like object already in the fridge area",
        image_region={"type": "bbox", "value": [0.2, 0.2, 0.2, 0.2]},
        producer_type="main_cleanup_agent",
        producer_id="test_agent",
    )

    assert duplicate["ok"] is False
    assert duplicate["error_reason"] == VISUAL_CANDIDATE_ALREADY_HANDLED_REASON
    assert duplicate["object_id"] == handle
    assert duplicate["required_next_tool"] == "observe"
    assert duplicate["model_declared_observation"]["actionability_status"] == "already_handled"
    assert contract.model_declared_observations_payload()["observation_count"] == (
        declared_before_place
    )
    assert contract._current_object_handle == current_handle_before
    assert contract._held_handle == held_handle_before
    assert contract._object_lifecycle[handle] == lifecycle_before
    _assert_no_forbidden_keys(duplicate)


def test_realworld_rejects_malformed_model_declared_candidate() -> None:
    contract = _contract(
        CleanupBackendSession(build_cleanup_scenario(seed=7)),
        perception_mode=RAW_FPV_ONLY_MODE,
    )

    waypoint = contract.metric_map()["inspection_waypoints"][0]
    contract.navigate_to_waypoint(str(waypoint["waypoint_id"]))
    observation = contract.observe()
    declared = contract.declare_visual_candidates(
        observation["raw_fpv_observation"]["observation_id"],
        candidates=[
            {
                "category": "mug",
                "target_fixture_id": "sink_01",
                "evidence_note": "small item near the sink",
                "image_region": {"type": "polygon", "value": [1, 2, 3]},
            }
        ],
        producer_type="main_cleanup_agent",
        producer_id="test_agent",
    )

    assert declared["ok"] is False
    assert declared["error_reason"] == "invalid_visual_candidate"
    assert declared["candidate_error"]["field"] == "image_region.type"
    recovery = declared["raw_fpv_candidate_recovery"]
    assert recovery["schema"] == "raw_fpv_visual_candidate_recovery_v1"
    assert recovery["required_tool"] == "navigate_to_visual_candidate"
    assert recovery["base_metric_map_target_fixture_rule"] == "omit_target_fixture_id"
    assert (
        recovery["valid_example"]["source_observation_id"]
        == (observation["raw_fpv_observation"]["observation_id"])
    )
    assert "target_fixture_id" not in recovery["valid_example"]
    assert {
        "type": "bbox",
        "value": [0.1, 0.2, 0.3, 0.4],
    } in recovery["accepted_image_region_forms"]
    agent_view = contract.agent_view_payload()
    assert (
        agent_view_module.model_declared_observation_evidence(agent_view)["observation_count"] == 0
    )
    _assert_no_forbidden_keys(declared)

    missing_region = contract.declare_visual_candidates(
        observation["raw_fpv_observation"]["observation_id"],
        candidates=[
            {
                "category": "mug",
                "target_fixture_id": "sink_01",
                "evidence_note": "small item near the sink",
            }
        ],
        producer_type="main_cleanup_agent",
        producer_id="test_agent",
    )

    assert missing_region["ok"] is False
    assert missing_region["error_reason"] == "invalid_visual_candidate"
    assert missing_region["candidate_error"]["field"] == "image_region"
    assert "valid navigate_to_visual_candidate example" in missing_region["recovery_hint"]
    assert missing_region["raw_fpv_candidate_recovery"]["valid_example"]["image_region"] == {
        "type": "bbox",
        "value": [0.1, 0.2, 0.3, 0.4],
    }
    _assert_no_forbidden_keys(missing_region)


def test_minimal_raw_fpv_navigate_validation_returns_schema_recovery() -> None:
    contract = _contract(
        CleanupBackendSession(build_cleanup_scenario(seed=7)),
        perception_mode=RAW_FPV_ONLY_MODE,
    )

    waypoint = contract.metric_map()["inspection_waypoints"][0]
    contract.navigate_to_waypoint(str(waypoint["waypoint_id"]))
    observation = contract.observe()
    response = contract.navigate_to_visual_candidate(
        observation["raw_fpv_observation"]["observation_id"],
        category="toy",
        evidence_note="small object on the bed",
    )

    assert response["ok"] is False
    assert response["error_reason"] == "invalid_visual_candidate"
    assert response["candidate_error"]["field"] == "image_region"
    recovery = response["raw_fpv_candidate_recovery"]
    assert recovery["required_next_action"] == "retry_navigate_to_visual_candidate"
    assert recovery["base_metric_map_target_fixture_rule"] == "omit_target_fixture_id"
    assert "target_fixture_id" not in recovery["valid_example"]
    assert "bbox_normalized" in recovery["invalid_fields_to_avoid"]
    assert 'target_fixture_id="None"' in recovery["invalid_fields_to_avoid"]
    _assert_no_forbidden_keys(response)

    invented_target = contract.navigate_to_visual_candidate(
        observation["raw_fpv_observation"]["observation_id"],
        category="toy",
        target_fixture_id="generated_area",
        evidence_note="small object on the bed",
        image_region={"type": "verbal_region", "value": "front of desk"},
    )

    assert invented_target["ok"] is False
    assert invented_target["error_reason"] == "invalid_visual_candidate"
    assert invented_target["candidate_error"]["field"] == "target_fixture_id"
    assert (
        "must be omitted in Base Metric Map RAW_FPV"
        in (invented_target["candidate_error"]["reason"])
    )
    assert (
        invented_target["raw_fpv_candidate_recovery"]["base_metric_map_target_fixture_rule"]
        == "omit_target_fixture_id"
    )
    _assert_no_forbidden_keys(invented_target)


def test_realworld_model_declared_grounding_accepts_public_category_families() -> None:
    contract = _contract(
        CleanupBackendSession(build_cleanup_scenario(seed=7)),
        perception_mode=RAW_FPV_ONLY_MODE,
    )

    observation = _observe_raw_fpv_category(contract, category="food")
    declared = contract.declare_visual_candidates(
        observation["raw_fpv_observation"]["observation_id"],
        candidates=[
            {
                "category": "tomato",
                "evidence_note": "round produce item on the desk",
                "image_region": {"type": "bbox", "value": [0.12, 0.24, 0.18, 0.16]},
            }
        ],
        producer_type="main_cleanup_agent",
        producer_id="test_agent",
    )

    candidate = declared["model_declared_observations"][0]
    assert candidate["grounding_status"] == "resolved"
    assert candidate["target_plausibility"]["status"] == "unknown_fixture"
    _assert_no_forbidden_keys(declared)


def test_realworld_model_declared_grounding_keeps_target_mismatch_as_metadata() -> None:
    contract = _contract(
        CleanupBackendSession(build_cleanup_scenario(seed=7)),
        perception_mode=RAW_FPV_ONLY_MODE,
    )

    observation = _observe_raw_fpv_category(contract, category="toy")
    declared = contract.declare_visual_candidates(
        observation["raw_fpv_observation"]["observation_id"],
        candidates=[
            {
                "category": "toy",
                "evidence_note": "toy-like object on the coffee table",
                "image_region": {"type": "bbox", "value": [0.2, 0.2, 0.2, 0.2]},
            }
        ],
        producer_type="main_cleanup_agent",
        producer_id="test_agent",
    )

    candidate = declared["model_declared_observations"][0]
    assert candidate["grounding_status"] == "resolved"
    assert candidate["target_plausibility"]["status"] == "unknown_fixture"
    _assert_no_forbidden_keys(declared)


def test_realworld_model_declared_grounding_accepts_live_broad_categories() -> None:
    contract = _contract(
        CleanupBackendSession(_live_style_alias_scenario()),
        perception_mode=RAW_FPV_ONLY_MODE,
    )

    observation = _observe_raw_fpv_category(contract, category="electronics")

    bad_source_fixture = contract.navigate_to_visual_candidate(
        observation["raw_fpv_observation"]["observation_id"],
        category="electronics",
        source_fixture_id="tvstand_01",
        evidence_note="black laptop on the sofa cushion",
        image_region={"type": "bbox", "value": [0.18, 0.22, 0.22, 0.18]},
        producer_type="main_cleanup_agent",
        producer_id="test_agent",
    )
    electronics = contract.navigate_to_visual_candidate(
        observation["raw_fpv_observation"]["observation_id"],
        category="electronics",
        evidence_note="black laptop on the sofa cushion",
        image_region={"type": "bbox", "value": [0.18, 0.22, 0.22, 0.18]},
        producer_type="main_cleanup_agent",
        producer_id="test_agent",
    )
    toy = contract.navigate_to_visual_candidate(
        observation["raw_fpv_observation"]["observation_id"],
        category="toy",
        evidence_note="teddy bear plush on the sofa",
        image_region={"type": "bbox", "value": [0.48, 0.34, 0.22, 0.2]},
        producer_type="main_cleanup_agent",
        producer_id="test_agent",
    )

    assert bad_source_fixture["ok"] is False
    assert bad_source_fixture["error_reason"] == "visual_candidate_not_resolved"
    assert bad_source_fixture["grounding_status"] == "unresolved"
    assert electronics["ok"] is False
    assert electronics["error_reason"] == "visual_candidate_not_cleanup_recommended"
    assert electronics["model_declared_observation"]["grounding_status"] == "resolved"
    assert (
        "waypoint-local public context"
        in electronics["model_declared_observation"]["grounding_basis"]
    )
    assert str(electronics["candidate_fixture_id"]).startswith("anchor_fixture_")
    assert electronics["recommended_tool"] == ""
    assert electronics["cleanup_recommended"] is False
    electronics_worklist_item = next(
        item
        for item in contract.cleanup_worklist_payload()["objects"]
        if item["object_id"] == electronics["object_id"]
    )
    assert electronics_worklist_item["cleanup_recommended"] is False
    assert electronics_worklist_item["candidate_fixture_id"] == electronics["candidate_fixture_id"]
    assert electronics_worklist_item["recommended_tool"] == "place"
    pending_handles = {
        item["object_id"] for item in realworld_done_readiness.pending_cleanup_candidates(contract)
    }
    assert electronics["object_id"] not in pending_handles
    assert toy["ok"] is False
    assert toy["error_reason"] == "visual_candidate_not_cleanup_recommended"
    assert toy["model_declared_observation"]["grounding_status"] == "resolved"
    assert str(toy["candidate_fixture_id"]).startswith("anchor_fixture_")
    assert toy["cleanup_recommended"] is False
    assert toy["required_next_tool"] == "observe"
    _assert_no_forbidden_keys(bad_source_fixture)
    _assert_no_forbidden_keys(electronics)
    _assert_no_forbidden_keys(toy)


def test_realworld_raw_fpv_grounding_blocks_same_room_fallback() -> None:
    contract = _contract(
        CleanupBackendSession(_same_room_fallback_scenario()),
        perception_mode=RAW_FPV_ONLY_MODE,
    )

    waypoint = contract.metric_map()["inspection_waypoints"][0]

    contract.navigate_to_waypoint(str(waypoint["waypoint_id"]))
    observation = contract.observe()
    response = contract.navigate_to_visual_candidate(
        observation["raw_fpv_observation"]["observation_id"],
        category="book",
        evidence_note="book visible on a neighboring shelf in the same room",
        image_region={"type": "bbox", "value": [0.62, 0.28, 0.16, 0.18]},
        source_fixture_id="desk_01",
        producer_type="main_cleanup_agent",
        producer_id="test_agent",
    )

    assert response["ok"] is False
    assert response["object_id"].startswith("observed_")
    assert response["error_reason"] == "visual_candidate_not_resolved"
    assert response["grounding_status"] == "unresolved"
    declaration = response["model_declared_observation"]
    assert declaration["grounding_status"] == "unresolved"
    assert "same-room object matched category" not in declaration["grounding_basis"]
    _assert_no_forbidden_keys(response)


def test_realworld_camera_model_policy_registers_model_labelled_candidates() -> None:
    contract = _contract(
        CleanupBackendSession(build_cleanup_scenario(seed=7)),
        perception_mode=CAMERA_MODEL_POLICY_MODE,
    )

    observation = {}
    candidate_response = {}
    for waypoint in contract.metric_map()["inspection_waypoints"]:
        contract.navigate_to_waypoint(str(waypoint["waypoint_id"]))
        observation = contract.observe()
        candidate_response = contract.declare_visual_candidates(
            observation["raw_fpv_observation"]["observation_id"]
        )
        if candidate_response["camera_model_candidates"]:
            break
    agent_view = contract.agent_view_payload()

    assert observation["perception_mode"] == CAMERA_MODEL_POLICY_MODE
    assert observation["structured_detections_available"] is False
    assert observation["visible_object_detections"] == []
    assert observation["raw_fpv_observation"]["perception_mode"] == CAMERA_MODEL_POLICY_MODE
    assert candidate_response["ok"] is True
    assert candidate_response["visible_object_detections"] == []
    assert candidate_response["camera_model_candidates"]
    assert candidate_response["model_declared_observations"]
    candidate = candidate_response["camera_model_candidates"][0]
    assert candidate["object_id"].startswith("observed_")
    assert candidate["perception_source"] == "model_declared_observation"
    assert candidate["model_provenance"] == SIMULATED_CAMERA_MODEL_PROVENANCE
    assert candidate["source_observation_id"].startswith("raw_fpv_")
    assert candidate["support_estimate"]["source"] == "public_semantic_anchor"
    declaration = candidate_response["model_declared_observations"][0]
    assert declaration["source_observation_id"].startswith("raw_fpv_")
    assert declaration["producer_type"] == SIMULATED_CAMERA_MODEL_PROVENANCE
    assert declaration["grounding_status"] == "resolved"
    assert declaration["target_plausibility"]["status"] in {
        "plausible",
        "weak",
        "unknown_fixture",
    }
    evidence = agent_view_module.camera_model_policy_evidence(agent_view)
    active_perception = agent_view_module.active_perception(agent_view)
    assert evidence["schema"] == CAMERA_MODEL_POLICY_SCHEMA
    assert evidence["enabled"] is True
    assert evidence["event_count"] >= 1
    assert evidence["candidate_count"] >= len(candidate_response["camera_model_candidates"])
    assert evidence["events"][0]["schema"] == "model_declared_observations_v1"
    assert active_perception["raw_fpv_summary"]["observation_count"] >= 1
    assert active_perception["camera_grounded_labels"]["sidecar_status"] == "available"
    assert active_perception["camera_grounded_labels"]["candidate_count"] >= len(
        candidate_response["camera_model_candidates"]
    )
    assert active_perception["visual_candidate_lifecycle"]["model_declared_observation_count"] >= 1
    model_evidence = agent_view_module.model_declared_observation_evidence(agent_view)
    assert model_evidence["schema"] == "model_declared_observations_v1"
    assert model_evidence["resolved_count"] >= 1
    assert agent_view_module.observed_objects(agent_view)
    _assert_no_forbidden_keys(observation)
    _assert_no_forbidden_keys(candidate_response)
    _assert_no_forbidden_keys(agent_view)


def test_runtime_metric_map_clusters_same_view_fixture_anchors_and_keeps_view_pose_prior() -> None:
    contract = _contract(
        CleanupBackendSession(build_cleanup_scenario(seed=7)),
        perception_mode=CAMERA_MODEL_POLICY_MODE,
    )

    for waypoint in contract.metric_map()["inspection_waypoints"]:
        contract.navigate_to_waypoint(str(waypoint["waypoint_id"]))
        observation = contract.observe()
        contract.declare_visual_candidates(observation["raw_fpv_observation"]["observation_id"])

    runtime_map = contract.agent_view_payload()["runtime_metric_map"]
    fixture_anchors = [
        item
        for item in runtime_map["public_semantic_anchors"]
        if item["anchor_type"] in {"fixture", "surface", "receptacle"}
    ]
    duplicate_keys: dict[tuple[str, str, str, tuple[float, float, float], str], list[str]] = {}
    for anchor in fixture_anchors:
        pose = anchor["pose"]
        key = (
            anchor["category"],
            anchor["room_id"],
            anchor["waypoint_id"],
            (pose["x"], pose["y"], pose["yaw"]),
            anchor["source_observation_id"],
        )
        duplicate_keys.setdefault(key, []).append(anchor["anchor_id"])
        assert anchor["pose_source"] == "inspection_waypoint"
        assert anchor["pose_role"] == "best_view_pose"
        assert anchor["localization_status"] == "viewpoint_only"
        assert "object_pose" not in anchor
    assert not {key: ids for key, ids in duplicate_keys.items() if len(set(ids)) > 1}

    observed_objects = runtime_map["observed_objects"]
    assert observed_objects
    assert any(
        str(item.get("candidate_fixture_id", "")).startswith("anchor_fixture_")
        for item in observed_objects
    )
    for observed in observed_objects:
        assert "object_pose" not in observed

    anchor_candidates = [
        item
        for item in runtime_map["target_candidates"]
        if item["candidate_type"] == "public_semantic_anchor"
        and item["anchor_type"] in {"fixture", "surface", "receptacle"}
    ]
    assert anchor_candidates
    assert any(item["verified_navigation"] is True for item in anchor_candidates)
    for candidate in anchor_candidates:
        assert candidate["pose_source"] == "inspection_waypoint"
        assert candidate["pose_role"] == "best_view_pose"
        assert candidate["localization_status"] == "viewpoint_only"
        assert candidate["waypoint_id"]
        assert "object_pose" not in candidate
    _assert_no_forbidden_keys(runtime_map)


def test_realworld_camera_raw_empty_declare_does_not_fall_back_to_sim_labels() -> None:
    contract = _contract(
        CleanupBackendSession(build_cleanup_scenario(seed=7)),
        perception_mode=RAW_FPV_ONLY_MODE,
    )

    observation = contract.observe()
    response = contract.declare_visual_candidates(
        observation["raw_fpv_observation"]["observation_id"],
    )

    assert response["ok"] is False
    assert response["error_reason"] == "empty_raw_fpv_candidate_registration"
    assert contract.model_declared_observations_payload()["observation_count"] == 0
    assert contract.camera_model_policy_payload()["event_count"] == 0
    _assert_no_forbidden_keys(response)


def test_realworld_camera_model_policy_records_sim_pipeline_provenance() -> None:
    contract = _contract(
        CleanupBackendSession(build_cleanup_scenario(seed=7)),
        perception_mode=CAMERA_MODEL_POLICY_MODE,
    )

    observation = contract.observe()
    response = contract.declare_visual_candidates(
        observation["raw_fpv_observation"]["observation_id"]
    )
    evidence = response["model_declared_observation_evidence"]
    pipeline = evidence["visual_grounding_pipeline"]

    assert pipeline["pipeline_id"] == "sim"
    assert pipeline["stages"][0]["stage"] == "simulated_camera_model"
    assert pipeline["candidate_count"] == evidence["candidate_count"]
    assert contract.camera_model_policy_payload()["visual_grounding_pipeline_id"] == "sim"
    _assert_no_forbidden_keys(response)


def test_realworld_camera_labels_http_failure_is_visible_without_sim_fallback(
    tmp_path: Path,
) -> None:
    client = _StaticVisualGroundingClient(
        {
            "schema": VISUAL_GROUNDING_RESPONSE_SCHEMA,
            "status": "failed",
            "pipeline": {
                "pipeline_id": "grounding-dino",
                "stages": [
                    {
                        "stage": "proposer",
                        "producer_id": "grounding-dino",
                        "model_id": "fake",
                        "status": "timeout",
                        "latency_ms": 20,
                    }
                ],
            },
            "candidates": [],
            "error": {"reason": "timeout", "message": "sidecar timeout"},
        }
    )
    contract = _contract(
        CleanupBackendSession(build_cleanup_scenario(seed=7)),
        perception_mode=CAMERA_MODEL_POLICY_MODE,
        visual_grounding_client=client,
        visual_grounding_pipeline_id="grounding-dino",
    )
    observation = _observe_raw_fpv_category(contract, category="toy")
    _attach_raw_fpv_test_image(
        contract,
        tmp_path=tmp_path,
        relative_path="robot_views/raw_fpv_001.png",
    )
    response = contract.declare_visual_candidates(
        observation["raw_fpv_observation"]["observation_id"]
    )
    evidence = response["model_declared_observation_evidence"]
    policy = contract.camera_model_policy_payload()

    assert response["ok"] is True
    assert response["model_declared_observations"] == []
    assert response["camera_model_candidates"] == []
    assert evidence["visual_grounding_pipeline"]["status"] == "failed"
    assert evidence["visual_grounding_pipeline"]["failure_reason"] == "timeout"
    assert evidence["candidate_count"] == 0
    assert policy["model_provenance"] == "external_visual_grounding_service"
    assert policy["visual_grounding_failure_count"] == 1
    assert contract.model_declared_observations_payload()["observation_count"] == 0
    assert client.last_request is not None
    _assert_no_forbidden_keys(response)


def test_realworld_camera_labels_missing_raw_image_fails_before_sidecar() -> None:
    client = _StaticVisualGroundingClient(
        {
            "schema": VISUAL_GROUNDING_RESPONSE_SCHEMA,
            "status": "ok",
            "pipeline": {
                "pipeline_id": "grounding-dino",
                "stages": [
                    {
                        "stage": "proposer",
                        "producer_id": "grounding-dino",
                        "model_id": "fake",
                        "status": "ok",
                        "latency_ms": 4,
                    }
                ],
            },
            "candidates": [
                {
                    "category": "mug",
                    "image_region": {"type": "bbox", "value": [0.1, 0.2, 0.3, 0.4]},
                    "confidence": 0.8,
                }
            ],
        }
    )
    contract = _contract(
        CleanupBackendSession(build_cleanup_scenario(seed=7)),
        perception_mode=CAMERA_MODEL_POLICY_MODE,
        visual_grounding_client=client,
        visual_grounding_pipeline_id="grounding-dino",
    )

    observation = contract.observe()
    response = contract.declare_visual_candidates(
        observation["raw_fpv_observation"]["observation_id"]
    )
    evidence = response["model_declared_observation_evidence"]
    policy = contract.camera_model_policy_payload()

    assert response["ok"] is True
    assert response["model_declared_observations"] == []
    assert evidence["visual_grounding_pipeline"]["status"] == "failed"
    assert evidence["visual_grounding_pipeline"]["failure_reason"] == "missing_raw_fpv_image"
    assert policy["visual_grounding_failure_count"] == 1
    assert client.last_request is None
    _assert_no_forbidden_keys(response)


def test_realworld_camera_labels_http_success_uses_destination_resolver(
    tmp_path: Path,
) -> None:
    client = _StaticVisualGroundingClient(
        {
            "schema": VISUAL_GROUNDING_RESPONSE_SCHEMA,
            "status": "ok",
            "pipeline": {
                "pipeline_id": "grounding-dino",
                "stages": [
                    {
                        "stage": "proposer",
                        "producer_id": "grounding-dino",
                        "model_id": "fake",
                        "status": "ok",
                        "latency_ms": 4,
                    }
                ],
            },
            "candidates": [
                {
                    "category": "mug",
                    "image_region": {"type": "bbox", "value": [0.1, 0.2, 0.3, 0.4]},
                    "confidence": 0.8,
                    "evidence_note": "static mug on sofa from public camera frame",
                    "source_fixture_id": "sofa_01",
                    "destination_hint": {
                        "candidate_fixture_id": "bookshelf_01",
                        "confidence": 0.9,
                    },
                }
            ],
        }
    )
    contract = _contract(
        CleanupBackendSession(build_cleanup_scenario(seed=7)),
        perception_mode=CAMERA_MODEL_POLICY_MODE,
        visual_grounding_client=client,
        visual_grounding_pipeline_id="grounding-dino",
        visual_grounding_artifact_base_dir=tmp_path,
    )
    contract.navigate_to_waypoint(contract._preferred_waypoint_for_fixture("sofa_01"))  # noqa: SLF001
    observation = contract.observe()
    _attach_raw_fpv_test_image(
        contract,
        tmp_path=tmp_path,
        relative_path="robot_views/raw_fpv_001.png",
    )
    response = contract.declare_visual_candidates(
        observation["raw_fpv_observation"]["observation_id"]
    )
    declaration = response["model_declared_observations"][0]

    assert client.last_request is not None
    assert client.last_request["category_hints"] == VISUAL_GROUNDING_CATEGORY_HINTS
    assert "static_fixture_projection" not in client.last_request
    assert client.last_request["public_map_hints"]["source"] == "public_agent_view_map_evidence"
    assert isinstance(client.last_request["public_map_hints"]["fixture_hints"], list)
    assert client.last_request["public_map_hints"]["private_truth_included"] is False
    assert client.last_request["image"]["bytes_base64"]
    assert client.last_request["image"]["width"] == 20
    assert client.last_request["image"]["height"] == 10
    assert declaration["producer_type"] == "external_visual_grounding_service"
    assert declaration["visual_grounding_pipeline"]["pipeline_id"] == "grounding-dino"
    assert declaration["visual_grounding_evidence"]["schema"] == "visual_grounding_evidence_v1"
    assert declaration["visual_grounding_evidence"]["producer_id"] == "grounding-dino"
    assert declaration["visual_grounding_evidence"]["reviewability_status"] == "reviewable"
    assert declaration["visual_grounding_evidence"]["bbox_coordinate_space"] == "normalized_xywh"
    assert declaration["actionability_status"] == "actionable"
    assert str(declaration["visual_grounding_destination_hint"]["candidate_fixture_id"]).startswith(
        "anchor_fixture_"
    )
    assert str(declaration["target_fixture_id"]).startswith("anchor_fixture_")
    assert declaration["visual_grounding_overlay"] == (
        "visual_grounding/overlays/raw_fpv_001/candidate_001.jpg"
    )
    assert (tmp_path / declaration["visual_grounding_overlay"]).is_file()
    assert (
        response["model_declared_observation_evidence"]["visual_grounding_pipeline"][
            "candidate_count"
        ]
        == 1
    )
    runtime_observed = contract.agent_view_payload()["runtime_metric_map"]["observed_objects"][0]
    assert runtime_observed["producer_type"] == "external_visual_grounding_service"
    assert runtime_observed["producer_id"] == "grounding-dino"
    assert runtime_observed["source_observation_id"] == declaration["source_observation_id"]
    assert runtime_observed["image_region"]["type"] == "bbox"
    assert runtime_observed["visual_grounding_evidence"]["reviewability_status"] == "reviewable"
    assert runtime_observed["actionability"] == "pending"
    _assert_no_forbidden_keys(response)


def test_b1_isaac_raw_fpv_artifact_can_feed_camera_grounded_labels(
    tmp_path: Path,
) -> None:
    client = _StaticVisualGroundingClient(
        {
            "schema": VISUAL_GROUNDING_RESPONSE_SCHEMA,
            "status": "ok",
            "pipeline": {
                "pipeline_id": "grounding-dino",
                "stages": [
                    {
                        "stage": "proposer",
                        "producer_id": "grounding-dino",
                        "model_id": "fixture:grounding-dino",
                        "status": "ok",
                        "latency_ms": 4,
                    }
                ],
            },
            "candidates": [
                {
                    "category": "mug",
                    "image_region": {"type": "bbox", "value": [0.2, 0.2, 0.4, 0.4]},
                    "confidence": 0.8,
                }
            ],
        }
    )
    contract = _contract(
        CleanupBackendSession(build_cleanup_scenario(seed=7)),
        perception_mode=CAMERA_MODEL_POLICY_MODE,
        evidence_lane="camera-grounded-labels",
        visual_grounding_client=client,
        visual_grounding_pipeline_id="grounding-dino",
        visual_grounding_artifact_base_dir=tmp_path,
        public_acceptance_config={
            "backend": "isaaclab_subprocess",
            "task_intent": "open-ended",
        },
    )
    observation = _observe_raw_fpv_category(contract, category="mug")
    _attach_raw_fpv_test_image(
        contract,
        tmp_path=tmp_path,
        relative_path="robot_views/b1_raw_fpv_001.png",
    )

    response = contract.declare_visual_candidates(
        observation["raw_fpv_observation"]["observation_id"]
    )
    evidence = contract.camera_model_policy_payload()

    assert client.last_request is not None
    assert client.last_request["schema"] == "visual_grounding_request_v2"
    assert client.last_request["image"]["bytes_base64"]
    assert client.last_request["pipeline_request"]["pipeline_id"] == "grounding-dino"
    assert client.last_request["public_map_hints"]["private_truth_included"] is False
    assert response["ok"] is True
    assert response["model_declared_observations"]
    assert evidence["enabled"] is True
    assert evidence["visual_grounding_pipeline_id"] == "grounding-dino"
    assert evidence["visual_grounding_failure_count"] == 0
    assert evidence["candidate_count"] >= 1
    agent_view = contract.agent_view_payload()
    assert (
        agent_view_module.camera_model_policy_evidence(agent_view)["visual_grounding_pipeline_id"]
        == "grounding-dino"
    )
    _assert_no_forbidden_keys(response)


def test_realworld_camera_labels_http_destination_hint_is_evidence_only(
    tmp_path: Path,
) -> None:
    client = _StaticVisualGroundingClient(
        {
            "schema": VISUAL_GROUNDING_RESPONSE_SCHEMA,
            "status": "ok",
            "pipeline": {
                "pipeline_id": "grounding-dino",
                "stages": [
                    {
                        "stage": "proposer",
                        "producer_id": "grounding-dino",
                        "model_id": "fake",
                        "status": "ok",
                        "latency_ms": 4,
                    }
                ],
            },
            "candidates": [
                {
                    "category": "unknown_movable",
                    "image_region": {"type": "bbox", "value": [0.1, 0.2, 0.3, 0.4]},
                    "confidence": 0.7,
                    "evidence_note": "static unknown item with service-suggested destination",
                    "source_fixture_id": "",
                    "destination_hint": {
                        "candidate_fixture_id": "bookshelf_01",
                        "confidence": 0.9,
                    },
                }
            ],
        }
    )
    contract = _contract(
        CleanupBackendSession(build_cleanup_scenario(seed=7)),
        perception_mode=CAMERA_MODEL_POLICY_MODE,
        visual_grounding_client=client,
        visual_grounding_pipeline_id="grounding-dino",
    )

    observation = contract.observe()
    _attach_raw_fpv_test_image(
        contract,
        tmp_path=tmp_path,
        relative_path="robot_views/raw_fpv_001.png",
    )
    response = contract.declare_visual_candidates(
        observation["raw_fpv_observation"]["observation_id"]
    )
    declaration = response["model_declared_observations"][0]

    assert str(declaration["visual_grounding_destination_hint"]["candidate_fixture_id"]).startswith(
        "anchor_fixture_"
    )
    assert declaration["target_fixture_id"] == ""
    assert declaration["target_plausibility"]["status"] == "unknown_fixture"
    assert declaration["grounding_status"] == "unresolved"
    _assert_no_forbidden_keys(response)


def _assert_no_forbidden_keys(payload: object) -> None:
    if isinstance(payload, dict):
        forbidden = forbidden_agent_view_keys().intersection(payload)
        assert not forbidden
        for value in payload.values():
            _assert_no_forbidden_keys(value)
    elif isinstance(payload, list):
        for value in payload:
            _assert_no_forbidden_keys(value)


class _StaticVisualGroundingClient:
    pipeline_id = "grounding-dino"
    config = type(
        "Config",
        (),
        {
            "auth_mode": "none",
            "proposer_id": "grounding-dino",
            "proposer_model_id": "fixture:grounding-dino",
        },
    )()

    def __init__(self, response: dict) -> None:
        self.response = response
        self.last_request: dict | None = None

    def request_candidates(self, request: dict) -> dict:
        self.last_request = request
        return self.response


def _attach_raw_fpv_test_image(
    contract: RealWorldCleanupContract,
    *,
    tmp_path: Path,
    relative_path: str,
) -> None:
    image_path = tmp_path / relative_path
    image_path.parent.mkdir(parents=True, exist_ok=True)
    Image.new("RGB", (20, 10), (240, 240, 240)).save(image_path)
    contract._raw_fpv_observations[-1]["image_artifacts"] = {"fpv": str(image_path)}  # noqa: SLF001


def _first_non_empty_observation(contract: RealWorldCleanupContract) -> dict:
    for waypoint in contract.metric_map()["inspection_waypoints"]:
        contract.navigate_to_waypoint(str(waypoint["waypoint_id"]))
        observation = contract.observe()
        if observation["visible_object_detections"]:
            return observation
    raise AssertionError("expected at least one visible object detection")


def _observe_raw_fpv_category(
    contract: RealWorldCleanupContract,
    *,
    category: str,
) -> dict:
    matching = [
        item
        for item in contract.scenario.objects
        if _declared_category_matches_object(category, item)
    ]
    assert matching, f"expected scenario object category {category}"
    fixture_id = contract.contract.object_locations()[matching[0].object_id]
    waypoint_id = contract._preferred_waypoint_for_fixture(fixture_id)  # noqa: SLF001
    contract.navigate_to_waypoint(waypoint_id)
    return contract.observe()


def _observe_raw_fpv_heading_sweep(
    contract: RealWorldCleanupContract,
    *,
    headings: tuple[float, ...] = (0.0, 90.0, 180.0, 270.0),
) -> dict:
    observation = {}
    for waypoint in contract.metric_map()["inspection_waypoints"]:
        contract.navigate_to_waypoint(str(waypoint["waypoint_id"]))
        for heading in headings:
            observation = contract.observe()
            _set_latest_raw_fpv_heading(contract, heading)
    return observation


def _set_latest_raw_fpv_heading(
    contract: RealWorldCleanupContract,
    heading_degrees: float,
) -> None:
    contract._raw_fpv_observations[-1]["camera_control_contract"] = {  # noqa: SLF001
        "robot_pose": {
            "pose_source": "relative_robot_frame",
            "theta": math.radians(heading_degrees),
        }
    }


def _observe_all_public_waypoints(contract: RealWorldCleanupContract) -> dict:
    seen: set[str] = set()
    metric_map = contract.metric_map()
    for _ in range(20):
        pending = [
            item
            for item in metric_map["inspection_waypoints"]
            if str(item["waypoint_id"]) not in seen
        ]
        if not pending:
            return metric_map
        for waypoint in pending:
            waypoint_id = str(waypoint["waypoint_id"])
            contract.navigate_to_waypoint(waypoint_id)
            contract.observe()
            seen.add(waypoint_id)
        metric_map = contract.metric_map()
    raise AssertionError("public waypoint budget did not converge")


def _first_detection_by_category(
    contract: RealWorldCleanupContract,
    category: str,
) -> dict:
    for waypoint in contract.metric_map()["inspection_waypoints"]:
        contract.navigate_to_waypoint(str(waypoint["waypoint_id"]))
        observation = contract.observe()
        for detection in observation["visible_object_detections"]:
            if detection["category"] == category:
                return detection
    raise AssertionError(f"expected visible detection with category {category}")


def _confirm_world_label_detection(
    contract: RealWorldCleanupContract,
    detection: dict,
) -> dict:
    contract.adjust_camera(yaw_delta_deg=15)
    confirmed_observation = contract.observe()
    return next(
        item
        for item in confirmed_observation["visible_object_detections"]
        if item["object_id"] == detection["object_id"]
    )


def _public_destination_fixture_for_detection(
    contract: RealWorldCleanupContract,
    detection: dict,
) -> dict:
    _observe_all_public_waypoints(contract)
    done = contract.done("probe public destination options")
    pending = list(_pending_cleanup_candidates(done))
    matching = [
        item
        for blocker in done.get("completion", {}).get("blockers", [])
        if blocker.get("type") == "pending_cleanup_candidates"
        for item in blocker.get("pending_cleanup_candidates", [])
        if item.get("object_id") == detection["object_id"]
    ]
    if not matching:
        matching = [item for item in pending if item.get("object_id") == detection["object_id"]]
    assert matching, done
    options = matching[0].get("destination_options") or []
    assert options, matching[0]
    fixture_id = str(options[0]["candidate_fixture_id"])
    target = contract.public_receptacles_by_id().get(fixture_id)
    assert target is not None
    return dict(target)


def _pending_cleanup_candidates(done_response: dict) -> list[dict]:
    return [
        item
        for blocker in done_response.get("completion", {}).get("blockers", [])
        if blocker.get("type") == "pending_cleanup_candidates"
        for item in blocker.get("pending_cleanup_candidates", [])
    ]


def _empty_cleanup_scenario(scenario_id: str) -> CleanupScenario:
    return CleanupScenario(
        scenario_id=scenario_id,
        task="check done readiness policy",
        seed=7,
        objects=(),
        receptacles=(
            CleanupReceptacle("sink_01", "Sink", "kitchen", category="Sink"),
            CleanupReceptacle("desk_01", "Desk", "office", category="Desk"),
        ),
        private_manifest=PrivateScoringManifest(
            scenario_id=scenario_id,
            targets=(),
            success_threshold=0,
        ),
    )


def _live_style_alias_scenario() -> CleanupScenario:
    return CleanupScenario(
        scenario_id="live-style-alias-test",
        task="clean broad raw camera declarations",
        seed=7,
        objects=(
            CleanupObject(
                object_id="laptop_01",
                name="Laptop (Laptop|surface|3|39)",
                category="Laptop",
                location_id="sofa_01",
            ),
            CleanupObject(
                object_id="teddybear_01",
                name="TeddyBear (TeddyBear|surface|3|35)",
                category="TeddyBear",
                location_id="sofa_01",
            ),
        ),
        receptacles=(
            CleanupReceptacle(
                receptacle_id="sofa_01",
                name="Sofa (Sofa|3|0|1)",
                room_area="living_area",
                category="Sofa",
            ),
            CleanupReceptacle(
                receptacle_id="toybin_01",
                name="ToyBin (ToyBin|3|2)",
                room_area="living_area",
                category="ToyBin",
            ),
            CleanupReceptacle(
                receptacle_id="tvstand_01",
                name="TVStand (TVStand|3|0|0)",
                room_area="living_area",
                category="TVStand",
            ),
        ),
        private_manifest=PrivateScoringManifest(
            scenario_id="live-style-alias-test",
            targets=(
                TargetRule("laptop_01", ("tvstand_01",)),
                TargetRule("teddybear_01", ("toybin_01",)),
            ),
            success_threshold=2,
        ),
    )


def _same_room_fallback_scenario() -> CleanupScenario:
    return CleanupScenario(
        scenario_id="same-room-fallback-test",
        task="clean raw camera declaration from neighboring fixture",
        seed=7,
        objects=(
            CleanupObject(
                object_id="book_01",
                name="Paperback Book",
                category="Book",
                location_id="shelf_01",
            ),
        ),
        receptacles=(
            CleanupReceptacle(
                receptacle_id="desk_01",
                name="Desk",
                room_area="living_area",
                category="Desk",
            ),
            CleanupReceptacle(
                receptacle_id="shelf_01",
                name="ShelvingUnit",
                room_area="living_area",
                category="ShelvingUnit",
            ),
        ),
        private_manifest=PrivateScoringManifest(
            scenario_id="same-room-fallback-test",
            targets=(TargetRule("book_01", ("shelf_01",)),),
            success_threshold=1,
        ),
    )


def _trace_response(tool: str, response: dict[str, object]) -> dict[str, object]:
    return {"event": "response", "tool": tool, "response": response}
