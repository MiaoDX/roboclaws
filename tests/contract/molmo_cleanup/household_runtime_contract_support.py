from __future__ import annotations

import math
from pathlib import Path

from PIL import Image

from roboclaws.household import agent_view as agent_view_module
from roboclaws.household.household_backend_contract import HouseholdBackendSession
from roboclaws.household.household_runtime_contract import (
    CLEANUP_WORKLIST_SCHEMA,
    REAL_ROBOT_MAP_BUNDLE_SCHEMA,
    REALWORLD_CONTRACT,
    RUNTIME_METRIC_MAP_SCHEMA,
    HouseholdRuntimeContract,
    _declared_category_matches_object,
    forbidden_agent_view_keys,
)
from roboclaws.household.types import (
    CleanupObject,
    CleanupReceptacle,
    CleanupScenario,
    PrivateScoringManifest,
    TargetRule,
)

REPO_ROOT = Path(__file__).resolve().parents[3]

PREBUILT_BUNDLE = REPO_ROOT / "assets" / "maps" / "molmospaces" / "procthor-10k-val" / "0"


def _contract(
    session: HouseholdBackendSession,
    **kwargs: object,
) -> HouseholdRuntimeContract:
    kwargs.setdefault("map_bundle_dir", PREBUILT_BUNDLE)
    return HouseholdRuntimeContract(session, **kwargs)


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


def _first_detected_metric_map_waypoint(
    contract: HouseholdRuntimeContract,
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
    contract: HouseholdRuntimeContract,
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


def _first_detection_waypoint(
    contract: HouseholdRuntimeContract,
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
    contract: HouseholdRuntimeContract,
    *,
    tmp_path: Path,
    relative_path: str,
) -> None:
    image_path = tmp_path / relative_path
    image_path.parent.mkdir(parents=True, exist_ok=True)
    Image.new("RGB", (20, 10), (240, 240, 240)).save(image_path)
    contract._raw_fpv_observations[-1]["image_artifacts"] = {"fpv": str(image_path)}  # noqa: SLF001


def _first_non_empty_observation(contract: HouseholdRuntimeContract) -> dict:
    for waypoint in contract.metric_map()["inspection_waypoints"]:
        contract.navigate_to_waypoint(str(waypoint["waypoint_id"]))
        observation = contract.observe()
        if observation["visible_object_detections"]:
            return observation
    raise AssertionError("expected at least one visible object detection")


def _observe_raw_fpv_category(
    contract: HouseholdRuntimeContract,
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
    contract: HouseholdRuntimeContract,
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
    contract: HouseholdRuntimeContract,
    heading_degrees: float,
) -> None:
    contract._raw_fpv_observations[-1]["camera_control_contract"] = {  # noqa: SLF001
        "robot_pose": {
            "pose_source": "relative_robot_frame",
            "theta": math.radians(heading_degrees),
        }
    }


def _observe_all_public_waypoints(contract: HouseholdRuntimeContract) -> dict:
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
    contract: HouseholdRuntimeContract,
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
    contract: HouseholdRuntimeContract,
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
    contract: HouseholdRuntimeContract,
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
