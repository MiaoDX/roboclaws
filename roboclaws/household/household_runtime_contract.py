from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from roboclaws.core.json_sources import read_json_value
from roboclaws.household import (
    realworld_agent_view_contract,
    realworld_contract_init,
    realworld_contract_payloads,
    realworld_contract_projection,
    realworld_done_readiness,
    realworld_runtime_map_contract,
    realworld_runtime_map_targets,
    realworld_tool_responses,
    realworld_visual_candidate_declarations,
    realworld_visual_candidate_lifecycle,
    realworld_visual_candidates,
)
from roboclaws.household.backend import API_SEMANTIC_PROVENANCE
from roboclaws.household.household_backend_contract import HouseholdBackendSession
from roboclaws.household.planner_observed_binding import (
    observed_handle_planner_binding,
)
from roboclaws.household.raw_fpv_guidance import (
    RAW_FPV_DECLARATION_STRATEGY,
    raw_fpv_inline_candidate_instruction,
)
from roboclaws.household.realworld_contract_fixture_projection import (
    _OBJECT_CATEGORY_TARGETS,
    _first_matching_fixture,
    _fixture_prefers_inside,
    _fixture_requires_open,
    _normalize_fixture_category_label,
    _public_destination_policy_for_category,
    _recommended_place_tool,
    _room_polygon_bounds,
)
from roboclaws.household.realworld_contract_projection import (
    _map_bundle_fields_present,
    _merge_public_rooms,
    _pose_stamped_waypoints_present,
    _room_category_hints_from_public_rooms,
    _room_outline_by_id,
    _scene_index_fixture_pose,
)
from roboclaws.household.realworld_policy_trace import (
    cleanup_policy_trace_from_events as _cleanup_policy_trace_from_events,
)
from roboclaws.household.robot_view_pose import room_for_point
from roboclaws.household.semantic_acceptability import (
    annotate_score_with_semantic_acceptability,
    public_source_requires_cleanup,
    semantic_disturbance_metrics,
)
from roboclaws.household.semantic_timeline import SEMANTIC_LOOP_VARIANT
from roboclaws.household.target_query import resolve_target_query
from roboclaws.household.task_intent import (
    normalize_household_intent,
)
from roboclaws.household.types import CleanupScenario
from roboclaws.household.visual_grounding import (
    EXTERNAL_VISUAL_GROUNDING_PROVENANCE,
    SIM_VISUAL_GROUNDING_PIPELINE_ID,
    VisualGroundingClient,
)
from roboclaws.household.visual_scan_guidance import (
    VISUAL_SCAN_NOOP_ERROR_REASON,
    noop_camera_adjustment_hint,
    visual_scan_payload,
)
from roboclaws.maps.bundle import static_landmarks_from_fixture_projection
from roboclaws.maps.route import SIM_COSTMAP_PLANNER, validate_metric_map_route

REALWORLD_CONTRACT = "realworld_cleanup_v1"
REAL_ROBOT_MAP_BUNDLE_SCHEMA = "real_robot_map_bundle_v1"
RUNTIME_METRIC_MAP_SCHEMA = "runtime_metric_map_v1"
INSPECTION_OBSERVATION_SCHEMA = "target_inspection_observation_v1"
CLEANUP_WORKLIST_SCHEMA = "cleanup_worklist_v1"
CLEANUP_POLICY_TRACE_SCHEMA = "cleanup_policy_trace_v1"
REAL_ROBOT_READINESS_SCHEMA = "real_robot_readiness_v1"
DETERMINISTIC_SWEEP_POLICY = "deterministic_sweep_baseline"
DEFAULT_REALWORLD_TASK = "帮我收拾这个房间"
VISIBLE_OBJECT_DETECTIONS_MODE = "visible_object_detections"
RAW_FPV_ONLY_MODE = "raw_fpv_only"
CAMERA_MODEL_POLICY_MODE = "camera_model_policy"
WORLD_LABELS_DETECTION_POLICY = "world_labels"
SANITIZED_VISIBLE_OBJECT_DETECTIONS_POLICY = "sanitized_visible_object_detections"
VISIBLE_DETECTION_EXPOSURE_POLICIES = frozenset(
    {WORLD_LABELS_DETECTION_POLICY, SANITIZED_VISIBLE_OBJECT_DETECTIONS_POLICY}
)
CAMERA_MODEL_POLICY_SCHEMA = "camera_model_policy_v1"
CAMERA_MODEL_POLICY_NAME = "camera_model_policy_baseline"
MODEL_DECLARED_OBSERVATION_SCHEMA = "model_declared_observation_v1"
MODEL_DECLARED_OBSERVATIONS_SCHEMA = "model_declared_observations_v1"
VISUAL_GROUNDING_EVIDENCE_SCHEMA = realworld_visual_candidates.VISUAL_GROUNDING_EVIDENCE_SCHEMA
DONE_READINESS_SCHEMA = "done_readiness_v1"
DONE_READINESS_POLICY_RAW_FPV = realworld_done_readiness.DONE_READINESS_POLICY_RAW_FPV
DONE_READINESS_POLICY_EXPLICIT = realworld_done_readiness.DONE_READINESS_POLICY_EXPLICIT
MODEL_DECLARED_OBSERVATION_SOURCE = "model_declared_observation"
MAIN_CLEANUP_AGENT_PRODUCER = realworld_visual_candidates.MAIN_CLEANUP_AGENT_PRODUCER
TEST_AGENT_PRODUCER = realworld_visual_candidates.TEST_AGENT_PRODUCER
SIMULATED_CAMERA_MODEL_PROVENANCE = realworld_visual_candidates.SIMULATED_CAMERA_MODEL_PROVENANCE
SANITIZED_VISIBLE_OBJECT_DETECTIONS_PROVENANCE = "sanitized_visible_object_detections"
WORLD_PUBLIC_LABELS_PROFILE = "world-public-labels"
VISUAL_CANDIDATE_ALREADY_HANDLED_REASON = (
    realworld_visual_candidates.VISUAL_CANDIDATE_ALREADY_HANDLED_REASON
)
VISUAL_EVIDENCE_REVIEWABLE_STATUS = realworld_visual_candidates.VISUAL_EVIDENCE_REVIEWABLE_STATUS
VISUAL_EVIDENCE_NOT_REVIEWABLE_STATUS = (
    realworld_visual_candidates.VISUAL_EVIDENCE_NOT_REVIEWABLE_STATUS
)
CANDIDATE_STATE_SEMANTIC = realworld_visual_candidates.CANDIDATE_STATE_SEMANTIC
CANDIDATE_STATE_VISUALLY_CONFIRMED = realworld_visual_candidates.CANDIDATE_STATE_VISUALLY_CONFIRMED
CANDIDATE_STATE_NAVIGATION_AUTHORIZED = (
    realworld_visual_candidates.CANDIDATE_STATE_NAVIGATION_AUTHORIZED
)
VISUAL_GROUNDING_CATEGORY_HINTS = realworld_visual_candidates.VISUAL_GROUNDING_CATEGORY_HINTS
REALWORLD_PERCEPTION_MODES = frozenset(
    {
        VISIBLE_OBJECT_DETECTIONS_MODE,
        RAW_FPV_ONLY_MODE,
        CAMERA_MODEL_POLICY_MODE,
    }
)
_NON_ACTIONABLE_HANDLE_STATES = frozenset({"placed", "placed_closed", "skipped", "stale"})
_FORBIDDEN_AGENT_VIEW_KEYS = frozenset(
    {
        "generated_mess_set",
        "generated_mess_count",
        "environment_setup",
        "relocation_policy",
        "relocation_count",
        "relocated_object_ids",
        "relocated_objects",
        "before_relocation_positions",
        "after_relocation_positions",
        "target_count",
        "acceptable_destination_sets",
        "valid_receptacle_ids",
        "private_manifest",
        "is_misplaced",
        "global_movable_object_inventory",
        "target_receptacle_id",
    }
)


class HouseholdRuntimeContract:
    """ADR-0003 public/private cleanup contract.

    The wrapped ``HouseholdBackendSession`` still owns state mutation and
    deterministic private scoring. This contract is the public agent boundary:
    it exposes metric navigation, room-level static fixture projection, and robot-local
    observed object handles instead of a global object-inventory oracle.
    """

    def __init__(
        self,
        contract: HouseholdBackendSession,
        *,
        task_prompt: str = DEFAULT_REALWORLD_TASK,
        static_fixture_projection_mode: str = "room_only",
        perception_mode: str = VISIBLE_OBJECT_DETECTIONS_MODE,
        map_bundle_dir: str | Path | None = None,
        visual_grounding_client: VisualGroundingClient | None = None,
        visual_grounding_pipeline_id: str = SIM_VISUAL_GROUNDING_PIPELINE_ID,
        visual_grounding_artifact_base_dir: str | Path | None = None,
        visual_grounding_run_id: str = "",
        runtime_map_prior: dict[str, Any] | None = None,
        evidence_lane: str | None = None,
        public_acceptance_config: dict[str, Any] | None = None,
    ) -> None:
        realworld_contract_init.validate_contract_options(
            static_fixture_projection_mode=static_fixture_projection_mode,
            perception_mode=perception_mode,
        )
        self.contract = contract
        self.backend = contract.backend
        self.scenario: CleanupScenario = contract.backend.scenario
        self.task_prompt = task_prompt
        self.static_fixture_projection_mode = static_fixture_projection_mode
        self.perception_mode = perception_mode
        realworld_contract_init.init_profile_and_acceptance(
            self,
            evidence_lane,
            public_acceptance_config,
        )
        realworld_contract_init.init_visual_grounding(
            self,
            visual_grounding_client=visual_grounding_client,
            visual_grounding_pipeline_id=visual_grounding_pipeline_id,
            visual_grounding_artifact_base_dir=visual_grounding_artifact_base_dir,
            visual_grounding_run_id=visual_grounding_run_id,
        )
        realworld_contract_init.init_map_projection(
            self,
            map_bundle_dir,
        )
        realworld_contract_init.init_public_map_projection(self)
        self._current_waypoint_id = realworld_contract_init.initial_waypoint_id(self)
        realworld_contract_init.init_runtime_state(self, runtime_map_prior)

    def _apply_scene_room_outlines_to_fixtures(
        self,
        room_outlines: list[dict[str, Any]],
    ) -> None:
        for fixture_id, fixture in list(self._fixtures.items()):
            pose = _scene_index_fixture_pose(self.backend, fixture_id)
            if pose is None:
                continue
            room_id = room_for_point(room_outlines, pose[:2]) or str(
                room_outlines[0].get("room_id")
                or fixture.get("room_id")
                or fixture.get("room_area")
            )
            outline = _room_outline_by_id(room_outlines, room_id) or room_outlines[0]
            fixture["room_id"] = room_id
            fixture["room_area"] = room_id
            fixture["scene_room_outline"] = dict(outline)
            fixture["pose"] = {
                "frame_id": "map",
                "x": round(float(pose[0]), 6),
                "y": round(float(pose[1]), 6),
                "yaw": 0.0,
            }
            fixture["scene_room_outline_provenance"] = str(
                outline.get("provenance") or "scene_room_outline"
            )

    def public_tool_names(self) -> list[str]:
        return [
            "metric_map",
            "navigate_to_room",
            "navigate_to_waypoint",
            "observe",
            "adjust_camera",
            "declare_visual_candidates",
            "navigate_to_visual_candidate",
            "inspect_visible_object",
            "resolve_target_query",
            "navigate_to_object",
            "pick",
            "navigate_to_receptacle",
            "open_receptacle",
            "place",
            "place_inside",
            "close_receptacle",
            "done",
        ]

    def public_receptacles_by_id(self) -> dict[str, dict[str, Any]]:
        return {
            str(item["fixture_id"]): dict(item)
            for item in realworld_runtime_map_targets.public_runtime_fixture_candidates(
                self,
                include_runtime_backend_fixtures=True,
                assert_no_forbidden_agent_view_keys=_assert_no_forbidden_agent_view_keys,
            )
        }

    def internal_fixture_id_for_public_reference(self, fixture_id: str | None) -> str | None:
        return realworld_runtime_map_targets.internal_fixture_id_for_public_reference(
            self,
            fixture_id,
        )

    def metric_map(self) -> dict[str, Any]:
        return realworld_contract_projection._metric_map(
            self,
            realworld_contract=REALWORLD_CONTRACT,
            real_robot_map_bundle_schema=REAL_ROBOT_MAP_BUNDLE_SCHEMA,
            assert_no_forbidden_agent_view_keys=_assert_no_forbidden_agent_view_keys,
        )

    def static_fixture_projection(self) -> dict[str, Any]:
        return realworld_contract_projection._static_fixture_projection(
            self,
            realworld_contract=REALWORLD_CONTRACT,
            assert_no_forbidden_agent_view_keys=_assert_no_forbidden_agent_view_keys,
        )

    def source_map_static_fixture_projection(self) -> dict[str, Any]:
        return realworld_contract_projection._source_map_static_fixture_projection(self)

    def navigate_to_room(self, room_id: str) -> dict[str, Any]:
        room = next((item for item in self._rooms if item["room_id"] == room_id), None)
        if room is None:
            return self._error("navigate_to_room", "stale_reference", room_id=room_id)
        waypoint = next(item for item in self._waypoints if item["room_id"] == room_id)
        return self.navigate_to_waypoint(str(waypoint["waypoint_id"]))

    def navigate_to_waypoint(self, waypoint_id: str) -> dict[str, Any]:
        waypoint = self._waypoint_by_id(waypoint_id)
        if waypoint is None:
            return self._error("navigate_to_waypoint", "stale_reference", waypoint_id=waypoint_id)
        start_waypoint_id = self._current_waypoint_id
        route = validate_metric_map_route(
            self.metric_map(),
            static_landmarks_from_fixture_projection(self.static_fixture_projection()),
            start_waypoint_id=start_waypoint_id,
            goal_waypoint_id=waypoint_id,
            occupancy_grid=self._bundle_occupancy_grid,
        )
        if not route.ok:
            return self._error(
                "navigate_to_waypoint",
                "blocked_capability",
                navigation_backend=SIM_COSTMAP_PLANNER,
                primitive_provenance=API_SEMANTIC_PROVENANCE,
                route_validation=route.as_dict(),
                waypoint_id=waypoint_id,
                room_id=waypoint["room_id"],
                goal_pose={"frame_id": "map", **self._waypoint_pose(waypoint)},
                pose_source="inspection_waypoint",
            )
        self._current_waypoint_id = waypoint_id
        self._reset_camera_adjustment()
        navigation_waypoint = self._private_waypoint_for_public_waypoint(waypoint)
        navigation_waypoint = self._backend_navigation_waypoint(navigation_waypoint)
        navigation = self.contract.navigate_to_waypoint(navigation_waypoint)
        return self._ok(
            "navigate_to_waypoint",
            navigation_backend=SIM_COSTMAP_PLANNER,
            primitive_provenance=API_SEMANTIC_PROVENANCE,
            route_validation=route.as_dict(),
            goal_pose={"frame_id": "map", **self._waypoint_pose(waypoint)},
            backend_goal_pose={
                "frame_id": "map",
                **self._waypoint_pose(navigation_waypoint),
                "room_id": str(navigation_waypoint.get("room_id") or waypoint["room_id"]),
                "waypoint_id": str(navigation_waypoint.get("waypoint_id") or waypoint_id),
            },
            pose_source="inspection_waypoint",
            staleness_s=0.0,
            pose_confidence=1.0,
            pose_covariance=[0.0, 0.0, 0.0],
            requires_reobserve=False,
            waypoint_id=waypoint_id,
            room_id=waypoint["room_id"],
            coverage_estimate=waypoint["coverage_estimate"],
            backend_pose_mutation=navigation,
            navigation_status=(navigation or {}).get("status", "ok"),
        )

    def navigate_to_relative_pose(
        self,
        forward_m: float = 0.0,
        lateral_m: float = 0.0,
        yaw_delta_deg: float = 0.0,
    ) -> dict[str, Any]:
        requested = _relative_pose_delta(forward_m, lateral_m, yaw_delta_deg)
        limits = {
            "forward_m": [-1.0, 1.0],
            "lateral_m": [-1.0, 1.0],
            "yaw_delta_deg": [-90.0, 90.0],
        }
        if not any(requested.values()):
            return self._error(
                "navigate_to_relative_pose",
                "noop_relative_pose_request",
                frame_id="base_link",
                requested_delta=requested,
                applied_delta=_relative_pose_delta(),
                limits=limits,
                requires_reobserve=True,
            )
        if (
            abs(requested["forward_m"]) > limits["forward_m"][1]
            or abs(requested["lateral_m"]) > limits["lateral_m"][1]
            or abs(requested["yaw_delta_deg"]) > limits["yaw_delta_deg"][1]
        ):
            return self._error(
                "navigate_to_relative_pose",
                "relative_pose_delta_out_of_bounds",
                frame_id="base_link",
                requested_delta=requested,
                applied_delta=_relative_pose_delta(),
                limits=limits,
                requires_reobserve=True,
            )
        self._reset_camera_adjustment()
        backend_response = self.contract.navigate_to_relative_pose(
            forward_m=requested["forward_m"],
            lateral_m=requested["lateral_m"],
            yaw_delta_deg=requested["yaw_delta_deg"],
        )
        public_backend_response = _strip_forbidden_agent_view_keys(backend_response or {})
        backend_ok = bool((backend_response or {}).get("ok"))
        backend_status = str((backend_response or {}).get("status") or "")
        if not backend_ok or backend_status == "blocked_capability":
            return self._error(
                "navigate_to_relative_pose",
                "blocked_capability",
                frame_id="base_link",
                requested_delta=requested,
                applied_delta=_relative_pose_delta(),
                clamped=False,
                clamp_metadata={"console_limits_enforced": True},
                requires_reobserve=True,
                backend_provenance=(
                    (backend_response or {}).get("primitive_provenance")
                    or (backend_response or {}).get("backend_provenance")
                    or "blocked_capability"
                ),
                backend_pose_mutation=public_backend_response,
                backend_status=backend_status or "blocked_capability",
            )
        applied = _relative_pose_delta(
            (backend_response or {}).get("applied_forward_m", requested["forward_m"]),
            (backend_response or {}).get("applied_lateral_m", requested["lateral_m"]),
            (backend_response or {}).get("applied_yaw_delta_deg", requested["yaw_delta_deg"]),
        )
        return self._ok(
            "navigate_to_relative_pose",
            frame_id="base_link",
            requested_delta=requested,
            applied_delta=applied,
            clamped=bool((backend_response or {}).get("clamped", False)),
            clamp_metadata=(backend_response or {}).get("clamp_metadata")
            or {"console_limits_enforced": True},
            requires_reobserve=True,
            pose_source="relative_robot_frame",
            backend_provenance=(
                (backend_response or {}).get("primitive_provenance")
                or (backend_response or {}).get("backend_provenance")
                or API_SEMANTIC_PROVENANCE
            ),
            backend_pose_mutation=public_backend_response,
            backend_status=backend_status or "ok",
        )

    def resolve_target_query(
        self,
        query: str,
        *,
        operation: str = "inspect",
        max_results: int = 8,
    ) -> dict[str, Any]:
        runtime_map = self.runtime_metric_map_payload(
            metric_map=self.metric_map(),
            static_fixture_projection=self.static_fixture_projection(),
        )
        resolution = resolve_target_query(
            runtime_map,
            query,
            operation=operation,
            max_results=max_results,
        )
        return self._ok(
            "resolve_target_query",
            **{key: value for key, value in resolution.items() if key not in {"tool", "ok"}},
        )

    def observe(self) -> dict[str, Any]:
        waypoint = self._waypoint_by_id(self._current_waypoint_id)
        if waypoint is None:
            return self._error("observe", "missing_waypoint")
        self._observed_waypoint_ids.add(str(waypoint["waypoint_id"]))
        realworld_runtime_map_targets.seed_public_fixture_anchor_ids_for_waypoint(
            self,
            waypoint,
        )
        if self.perception_mode in {RAW_FPV_ONLY_MODE, CAMERA_MODEL_POLICY_MODE}:
            raw_observation = self._record_raw_fpv_observation(
                waypoint,
                perception_mode=self.perception_mode,
            )
            if self.perception_mode == CAMERA_MODEL_POLICY_MODE:
                instruction = (
                    "Camera-labels mode: call declare_visual_candidates with this "
                    "observation_id to register model-declared cleanup candidates. "
                    "Built-in visible_object_detections remain empty."
                )
                perception_source = CAMERA_MODEL_POLICY_MODE
                camera_model_available = True
            else:
                instruction = raw_fpv_inline_candidate_instruction(
                    str(raw_observation["observation_id"])
                )
                perception_source = RAW_FPV_ONLY_MODE
                camera_model_available = False
            response = self._ok(
                "observe",
                contract=REALWORLD_CONTRACT,
                current_room_id=waypoint["room_id"],
                waypoint_id=waypoint["waypoint_id"],
                observation_role="coverage_scan"
                if self._held_handle is None
                else "held_object_area_check",
                waypoint_source=waypoint.get("waypoint_source", "static_map_coverage"),
                perception_mode=self.perception_mode,
                perception_source=perception_source,
                structured_detections_available=False,
                visible_object_detections=[],
                raw_fpv_observation=raw_observation,
                camera_model_policy_available=camera_model_available,
                model_declaration_available=True,
                held_object_id=self._held_handle,
                private_target_truth_included=False,
                instruction=instruction,
            )
            self._record_inspection_observation(
                response,
                detections=[],
                source_observation_id=str(raw_observation["observation_id"]),
            )
            return response
        source_observation_id = self._next_visible_observation_id()
        perception_source = (
            SANITIZED_VISIBLE_OBJECT_DETECTIONS_PROVENANCE
            if self.sanitize_world_labels
            else "robot_local_visible_object_detections"
        )
        fixture_observations = (
            realworld_runtime_map_targets.record_fixture_observations_for_waypoint(
                self,
                waypoint,
                source_observation_id=source_observation_id,
                producer_type=perception_source,
                producer_id=perception_source,
            )
        )
        detections = self._visible_detections_for_waypoint(
            waypoint,
            source_observation_id=source_observation_id,
            visual_confirmation=self._camera_scan_confirmed(),
        )
        response = self._ok(
            "observe",
            contract=REALWORLD_CONTRACT,
            current_room_id=waypoint["room_id"],
            waypoint_id=waypoint["waypoint_id"],
            observation_role="coverage_scan"
            if self._held_handle is None
            else "held_object_area_check",
            source_observation_id=source_observation_id,
            waypoint_source=waypoint.get("waypoint_source", "static_map_coverage"),
            perception_mode=self.perception_mode,
            detection_exposure_policy=self.visible_detection_exposure_policy,
            structured_detections_available=True,
            visible_object_detections=[
                self._agent_visible_detection_payload(detection) for detection in detections
            ],
            visible_fixture_detections=self._public_fixture_reference_payload(fixture_observations),
            held_object_id=self._held_handle,
            perception_source=perception_source,
            private_target_truth_included=False,
        )
        self._record_inspection_observation(
            response,
            detections=detections,
            source_observation_id=source_observation_id,
        )
        return response

    def adjust_camera(
        self,
        yaw_delta_deg: float = 0.0,
        pitch_delta_deg: float = 0.0,
    ) -> dict[str, Any]:
        previous = self._camera_offset()
        yaw_delta = _float_or_zero(yaw_delta_deg)
        pitch_delta = _float_or_zero(pitch_delta_deg)
        if not yaw_delta and not pitch_delta:
            return self._error(
                "adjust_camera",
                VISUAL_SCAN_NOOP_ERROR_REASON,
                camera_offset=previous,
                previous_camera_offset=previous,
                required_next_tool="adjust_camera",
                followup_tool="observe",
                yaw_bounds_deg=[-45, 45],
                pitch_bounds_deg=[-20, 20],
                waypoint_id=self._current_waypoint_id,
                recovery_hint=noop_camera_adjustment_hint(),
                no_camera_motion=True,
                fresh_fpv_observation_required=True,
            )
        self._camera_yaw_offset_deg = _clamp(
            self._camera_yaw_offset_deg + yaw_delta,
            -45.0,
            45.0,
        )
        self._camera_pitch_offset_deg = _clamp(
            self._camera_pitch_offset_deg + pitch_delta,
            -20.0,
            20.0,
        )
        current = self._camera_offset()
        event = {
            "event_id": f"camera_adjustment_{len(self._camera_adjustment_events) + 1:03d}",
            "waypoint_id": self._current_waypoint_id,
            "previous_camera_offset": previous,
            "camera_offset": current,
            "yaw_delta_deg": yaw_delta,
            "pitch_delta_deg": pitch_delta,
            "followup_tool": "observe",
            "public_contract_note": (
                "Camera adjustment is bounded public perception control and resets on navigation."
            ),
        }
        _assert_no_forbidden_agent_view_keys(event)
        self._camera_adjustment_events.append(event)
        return self._ok(
            "adjust_camera",
            camera_offset=current,
            previous_camera_offset=previous,
            yaw_bounds_deg=[-45, 45],
            pitch_bounds_deg=[-20, 20],
            waypoint_id=self._current_waypoint_id,
            public_contract_note=(
                "Camera adjustment is bounded public perception control and resets on navigation."
            ),
        )

    def declare_visual_candidates(
        self,
        observation_id: str | None = None,
        *,
        candidates: list[dict[str, Any]] | tuple[dict[str, Any], ...] | None = None,
        producer_type: str = SIMULATED_CAMERA_MODEL_PROVENANCE,
        producer_id: str = CAMERA_MODEL_POLICY_NAME,
    ) -> dict[str, Any]:
        return realworld_visual_candidate_declarations.declare_visual_candidates(
            self,
            observation_id,
            candidates=candidates,
            producer_type=producer_type,
            producer_id=producer_id,
            assert_no_forbidden_agent_view_keys=_assert_no_forbidden_agent_view_keys,
        )

    def navigate_to_visual_candidate(
        self,
        source_observation_id: str | None = None,
        category: str = "",
        target_fixture_id: str = "",
        evidence_note: str = "",
        image_region: dict[str, Any] | str | None = None,
        *,
        source_fixture_id: str = "",
        confidence: float | None = None,
        producer_type: str = MAIN_CLEANUP_AGENT_PRODUCER,
        producer_id: str = "cleanup_agent",
    ) -> dict[str, Any]:
        return realworld_visual_candidate_lifecycle.navigate_to_visual_candidate(
            self,
            source_observation_id,
            category=category,
            target_fixture_id=target_fixture_id,
            evidence_note=evidence_note,
            image_region=image_region,
            source_fixture_id=source_fixture_id,
            confidence=confidence,
            producer_type=producer_type,
            producer_id=producer_id,
            raw_fpv_declaration_strategy=RAW_FPV_DECLARATION_STRATEGY,
        )

    def inspect_visible_object(self, object_id: str) -> dict[str, Any]:
        detection = self._detections_by_handle.get(object_id)
        if detection is None:
            return self._error("inspect_visible_object", "stale_reference", object_id=object_id)
        return self._ok(
            "inspect_visible_object",
            contract=REALWORLD_CONTRACT,
            detection=self._agent_visible_detection_payload(dict(detection)),
            detection_exposure_policy=self.visible_detection_exposure_policy,
            private_target_truth_included=False,
        )

    def planner_observed_handle_binding(
        self,
        object_id: str,
        target_receptacle_id: str,
        *,
        source_receptacle_id: str = "",
        tools: list[str] | tuple[str, ...] | None = None,
    ) -> dict[str, Any]:
        internal_target_receptacle_id = (
            self.internal_fixture_id_for_public_reference(target_receptacle_id)
            or target_receptacle_id
        )
        return observed_handle_planner_binding(
            self,
            object_id=object_id,
            target_receptacle_id=internal_target_receptacle_id,
            source_receptacle_id=source_receptacle_id,
            tools=tools,
        )

    def navigate_to_object(self, object_id: str) -> dict[str, Any]:
        if self._handle_is_non_actionable(object_id):
            return self._error(
                "navigate_to_object",
                "already_handled",
                object_id=object_id,
                required_next_tool="observe",
                recovery_hint=(
                    "This observed handle has already been placed or skipped. "
                    "Continue the waypoint sweep and observe for other cleanup objects."
                ),
            )
        internal_id = self._internal_object_id(object_id)
        if internal_id is None:
            grounding_error = self._unresolved_visual_candidate_error(
                "navigate_to_object", object_id
            )
            if grounding_error is not None:
                return grounding_error
            return self._error("navigate_to_object", "stale_reference", object_id=object_id)
        visual_evidence_error = self._visual_evidence_actionability_error(
            "navigate_to_object",
            object_id,
        )
        if visual_evidence_error is not None:
            return visual_evidence_error
        self._reset_camera_adjustment()
        response = self.contract.navigate_to_object(internal_id)
        if not response.get("ok"):
            return self._public_error_from_private("navigate_to_object", object_id, response)
        self._current_object_handle = object_id
        self._set_handle_state(object_id, "navigating_to_object", tool="navigate_to_object")
        return self._ok(
            "navigate_to_object",
            object_id=object_id,
            navigation_backend=response.get("navigation_backend", API_SEMANTIC_PROVENANCE),
            primitive_provenance=response.get(
                "primitive_provenance",
                API_SEMANTIC_PROVENANCE,
            ),
            goal_pose=self._object_goal_pose(object_id),
            pose_source="latest_observation",
            staleness_s=0.0,
            pose_confidence=self._object_pose_confidence(object_id),
            pose_covariance=[0.1, 0.1, 0.05],
            requires_reobserve=False,
            visual_grounding_evidence=self._visual_evidence_for_handle(object_id),
            actionability_status="actionable",
            candidate_state=CANDIDATE_STATE_NAVIGATION_AUTHORIZED,
            source_receptacle_id=response.get("source_receptacle_id"),
            previous_receptacle_id=response.get("previous_receptacle_id"),
            location_id=response.get("location_id"),
            state_mutation=response.get("state_mutation"),
            navigation_status=response.get("status"),
        )

    def pick(self, object_id: str) -> dict[str, Any]:
        if self._handle_is_non_actionable(object_id):
            return self._error(
                "pick",
                "already_handled",
                object_id=object_id,
                required_next_tool="observe",
                recovery_hint=(
                    "This observed handle has already been handled. Continue the "
                    "waypoint sweep instead of picking it again."
                ),
            )
        internal_id = self._internal_object_id(object_id)
        if internal_id is None:
            grounding_error = self._unresolved_visual_candidate_error("pick", object_id)
            if grounding_error is not None:
                return grounding_error
            return self._error("pick", "stale_reference", object_id=object_id)
        visual_evidence_error = self._visual_evidence_actionability_error("pick", object_id)
        if visual_evidence_error is not None:
            return visual_evidence_error
        if getattr(self, "_current_object_handle", None) != object_id:
            return self._semantic_order_error(
                "pick",
                required_tool="navigate_to_object",
                object_id=object_id,
                recovery_hint=(
                    "Call navigate_to_object with this observed object handle before pick. "
                    "The ADR-0003 clean loop is navigate_to_object -> pick -> "
                    "navigate_to_receptacle -> open_receptacle? -> place/place_inside "
                    "-> close_receptacle?."
                ),
            )
        picked = self.contract.pick(internal_id)
        if picked.get("ok"):
            self._held_handle = object_id
            self._current_object_handle = None
            self._current_receptacle_for_handle = None
            self._opened_receptacle_for_handle = None
            self._set_handle_state(object_id, "held", tool="pick")
        result = self._public_manipulation_response("pick", object_id, picked)
        if picked.get("ok"):
            result.update(self._destination_policy_context(object_id))
            result["required_next_tool"] = "navigate_to_receptacle"
        return result

    def navigate_to_receptacle(self, fixture_id: str) -> dict[str, Any]:
        requested_fixture_id = str(fixture_id)
        internal_fixture_id = self._internal_fixture_id_for_public_anchor(requested_fixture_id)
        if internal_fixture_id not in self._fixtures:
            recovery: dict[str, Any] = {}
            if self._held_handle is not None:
                recovery = {
                    "object_id": self._held_handle,
                    "required_tool": "navigate_to_receptacle",
                    "recovery_hint": (
                        "Choose candidate_fixture_id from destination_options; do not invent "
                        "or reuse non-public fixture ids."
                    ),
                    **self._destination_policy_context(self._held_handle),
                }
            return self._error(
                "navigate_to_receptacle",
                "stale_reference",
                fixture_id=requested_fixture_id,
                **recovery,
            )
        if self._held_handle is None:
            return self._semantic_order_error(
                "navigate_to_receptacle",
                required_tool="pick",
                fixture_id=requested_fixture_id,
                recovery_hint=(
                    "Pick an observed object before navigating to a cleanup fixture. "
                    "Use navigate_to_object -> pick first."
                ),
            )
        destination_policy_error = self._destination_policy_error(
            self._held_handle,
            requested_fixture_id=requested_fixture_id,
            internal_fixture_id=internal_fixture_id,
        )
        if destination_policy_error is not None:
            return destination_policy_error
        response = self.contract.navigate_to_receptacle(internal_fixture_id)
        if not response.get("ok"):
            return self._public_error_from_private(
                "navigate_to_receptacle",
                self._held_handle or "",
                response,
            )
        self._current_waypoint_id = self._public_waypoint_id_for_private_fixture(
            internal_fixture_id
        )
        self._reset_camera_adjustment()
        self._current_receptacle_for_handle = (self._held_handle, internal_fixture_id)
        self._opened_receptacle_for_handle = None
        public_fixture_id = self._public_fixture_response_id(
            internal_fixture_id,
            requested_fixture_id,
        )
        return self._ok(
            "navigate_to_receptacle",
            object_id=self._held_handle,
            receptacle_id=public_fixture_id,
            fixture_id=public_fixture_id,
            navigation_backend=response.get("navigation_backend", API_SEMANTIC_PROVENANCE),
            primitive_provenance=response.get(
                "primitive_provenance",
                API_SEMANTIC_PROVENANCE,
            ),
            goal_pose=self._fixture_pose(internal_fixture_id),
            pose_source="static_fixture_projection",
            staleness_s=0.0,
            pose_confidence=1.0,
            pose_covariance=[0.0, 0.0, 0.0],
            requires_reobserve=False,
            previous_receptacle_id=self._public_fixture_reference_id(
                str(response.get("previous_receptacle_id") or "")
            ),
            state_mutation=response.get("state_mutation"),
            navigation_status=response.get("status"),
        )

    def _destination_policy_error(
        self,
        handle: str,
        *,
        requested_fixture_id: str,
        internal_fixture_id: str,
    ) -> dict[str, Any] | None:
        context = self._destination_policy_context(handle)
        policy = context["destination_policy"]
        allowed_categories = {
            _normalize_fixture_category_label(item)
            for item in policy.get("acceptable_fixture_categories") or []
        }
        fixture = self._fixtures.get(internal_fixture_id) or {}
        requested_category = _normalize_fixture_category_label(
            fixture.get("category") or fixture.get("name")
        )
        if requested_category in allowed_categories:
            return None
        return self._error(
            "navigate_to_receptacle",
            "destination_policy_mismatch",
            object_id=handle,
            fixture_id=requested_fixture_id,
            receptacle_id=requested_fixture_id,
            fixture_category=requested_category,
            destination_policy=policy,
            destination_options=context["destination_options"],
            required_tool="navigate_to_receptacle",
            recovery_hint=(
                "Choose candidate_fixture_id from destination_options. The requested fixture "
                "category is not allowed by this object's public destination policy."
            ),
        )

    def _destination_policy_context(self, handle: str) -> dict[str, Any]:
        detection = self._detections_by_handle.get(handle) or {}
        policy = _public_destination_policy_for_category(detection.get("category"))
        return {
            "destination_policy": policy,
            "destination_options": realworld_done_readiness.destination_options_for_policy(
                self,
                policy,
            ),
        }

    def open_receptacle(self, fixture_id: str) -> dict[str, Any]:
        requested_fixture_id = str(fixture_id)
        internal_fixture_id = self._internal_fixture_id_for_public_anchor(requested_fixture_id)
        if internal_fixture_id not in self._fixtures:
            return self._error(
                "open_receptacle",
                "stale_reference",
                fixture_id=requested_fixture_id,
            )
        if self._held_handle is None:
            return self._semantic_order_error(
                "open_receptacle",
                required_tool="pick",
                fixture_id=requested_fixture_id,
                recovery_hint="Pick an observed object before opening a cleanup fixture.",
            )
        if self._current_receptacle_for_handle != (self._held_handle, internal_fixture_id):
            return self._semantic_order_error(
                "open_receptacle",
                required_tool="navigate_to_receptacle",
                object_id=self._held_handle,
                fixture_id=requested_fixture_id,
                recovery_hint=(
                    "Call navigate_to_receptacle for this fixture before open_receptacle. "
                    "Fridge-like cleanup must be nav -> open -> place_inside -> close."
                ),
            )
        opened = self.contract.open_receptacle(internal_fixture_id)
        if opened.get("ok"):
            self._opened_receptacle_for_handle = (self._held_handle, internal_fixture_id)
        return self._public_fixture_response(
            "open_receptacle",
            self._public_fixture_response_id(internal_fixture_id, requested_fixture_id),
            opened,
        )

    def place(self, fixture_id: str) -> dict[str, Any]:
        return self._place(fixture_id, inside=False)

    def place_inside(self, fixture_id: str) -> dict[str, Any]:
        return self._place(fixture_id, inside=True)

    def close_receptacle(self, fixture_id: str) -> dict[str, Any]:
        requested_fixture_id = str(fixture_id)
        internal_fixture_id = self._internal_fixture_id_for_public_anchor(requested_fixture_id)
        if internal_fixture_id not in self._fixtures:
            return self._error(
                "close_receptacle", "stale_reference", fixture_id=requested_fixture_id
            )
        pending = self._pending_close_receptacle_for_handle
        if pending is None or pending[1] != internal_fixture_id:
            return self._semantic_order_error(
                "close_receptacle",
                required_tool="place_inside",
                object_id=pending[0] if pending is not None else None,
                fixture_id=requested_fixture_id,
                recovery_hint=(
                    "Call close_receptacle only after place_inside for the same fridge-like "
                    "fixture."
                ),
            )
        handle, _ = pending
        closed = self.contract.close_receptacle(internal_fixture_id)
        public_fixture_id = self._public_fixture_response_id(
            internal_fixture_id,
            requested_fixture_id,
        )
        if closed.get("ok"):
            self._pending_close_receptacle_for_handle = None
            self._set_handle_state(
                handle,
                "placed_closed",
                tool="close_receptacle",
                fixture_id=public_fixture_id,
            )
        return self._public_fixture_response(
            "close_receptacle",
            public_fixture_id,
            closed,
            object_id=handle,
        )

    def done(
        self,
        reason: str = "",
        *,
        semantic_cleanup_evidence: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        readiness = self.evaluate_done_readiness(
            semantic_cleanup_evidence=semantic_cleanup_evidence,
        )
        if readiness["status"] == "blocked":
            return self._done_readiness_blocked_response(readiness)
        done = self.contract.done(reason=reason)
        if not done.get("ok"):
            return done
        score = annotate_score_with_semantic_acceptability(done["score"], self.scenario)
        final_locations = dict(done["final_locations"])
        metrics = self._realworld_metrics(score, final_locations)
        score.update(metrics)
        return self._ok(
            "done",
            reason=reason,
            cleanup_status=metrics["completion_status"],
            score=score,
            final_locations=final_locations,
            final_containment=done.get("final_containment", {}),
            tool_event_counts=done.get("tool_event_counts", {}),
            contract=REALWORLD_CONTRACT,
            policy_uses_private_truth=False,
        )

    def evaluate_done_readiness(
        self,
        *,
        semantic_cleanup_evidence: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        return realworld_done_readiness.evaluate_done_readiness(
            self,
            semantic_cleanup_evidence=semantic_cleanup_evidence,
            schema=DONE_READINESS_SCHEMA,
            raw_fpv_only_mode=RAW_FPV_ONLY_MODE,
            assert_no_forbidden_agent_view_keys=_assert_no_forbidden_agent_view_keys,
        )

    def _done_readiness_blocked_response(self, readiness: dict[str, Any]) -> dict[str, Any]:
        return realworld_done_readiness.done_readiness_blocked_response(
            readiness,
            schema=DONE_READINESS_SCHEMA,
            error_builder=self._error,
        )

    def _required_model_declared_observations(self) -> int:
        return realworld_done_readiness.required_model_declared_observations(self)

    def _grounded_cleanup_chain_blocker(
        self,
        semantic_cleanup_evidence: dict[str, Any] | None,
    ) -> dict[str, Any] | None:
        return realworld_done_readiness.grounded_cleanup_chain_blocker(
            self,
            semantic_cleanup_evidence,
            raw_fpv_only_mode=RAW_FPV_ONLY_MODE,
            assert_no_forbidden_agent_view_keys=_assert_no_forbidden_agent_view_keys,
        )

    def _grounded_cleanup_chain_requirement(self) -> tuple[int, str]:
        return realworld_done_readiness.grounded_cleanup_chain_requirement(
            self,
            raw_fpv_only_mode=RAW_FPV_ONLY_MODE,
        )

    def _grounded_cleanup_chain_required_tool(self) -> str:
        return realworld_done_readiness.grounded_cleanup_chain_required_tool(
            self.perception_mode,
            raw_fpv_only_mode=RAW_FPV_ONLY_MODE,
        )

    def _grounded_cleanup_chain_recovery_hint(self, required_tool: str) -> str:
        return realworld_done_readiness.grounded_cleanup_chain_recovery_hint(required_tool)

    def _sweep_coverage(self) -> dict[str, Any]:
        return realworld_done_readiness.sweep_coverage(self)

    def _open_ended_task_intent(self) -> bool:
        return realworld_done_readiness.open_ended_task_intent(self)

    def agent_view_payload(self) -> dict[str, Any]:
        return realworld_contract_payloads.agent_view_payload(
            self,
            realworld_contract=REALWORLD_CONTRACT,
            visible_object_detections_mode=VISIBLE_OBJECT_DETECTIONS_MODE,
            forbidden_keys=_FORBIDDEN_AGENT_VIEW_KEYS,
            assert_no_forbidden_agent_view_keys=_assert_no_forbidden_agent_view_keys,
        )

    def runtime_metric_map_payload(
        self,
        *,
        metric_map: dict[str, Any] | None = None,
        static_fixture_projection: dict[str, Any] | None = None,
        cleanup_worklist: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        return realworld_contract_payloads.runtime_metric_map_payload(
            self,
            metric_map=metric_map,
            static_fixture_projection=static_fixture_projection,
            cleanup_worklist=cleanup_worklist,
            realworld_contract=REALWORLD_CONTRACT,
            runtime_metric_map_schema=RUNTIME_METRIC_MAP_SCHEMA,
            cleanup_worklist_schema=CLEANUP_WORKLIST_SCHEMA,
            visible_object_detections_mode=VISIBLE_OBJECT_DETECTIONS_MODE,
            sanitized_visible_object_detections_provenance=(
                SANITIZED_VISIBLE_OBJECT_DETECTIONS_PROVENANCE
            ),
            runtime_map_producer_summary=_runtime_map_producer_summary,
            merge_public_rooms=_merge_public_rooms,
            room_category_hints_from_public_rooms=_room_category_hints_from_public_rooms,
            candidate_actionability_status=_candidate_actionability_status,
            candidate_state=_candidate_state,
            public_destination_policy_for_category=_public_destination_policy_for_category,
            norm=_norm,
            assert_no_forbidden_agent_view_keys=_assert_no_forbidden_agent_view_keys,
        )

    def _observation_id_for_waypoint(self, waypoint_id: str) -> str:
        for item in self._raw_fpv_observations:
            if str(item.get("waypoint_id") or "") == waypoint_id:
                return str(item.get("observation_id") or "")
        return f"waypoint_observation:{waypoint_id}"

    def _agent_visible_detection_payload(self, detection: dict[str, Any]) -> dict[str, Any]:
        return realworld_contract_payloads.agent_visible_detection_payload(
            self,
            detection,
            sanitized_visible_object_detections_provenance=(
                SANITIZED_VISIBLE_OBJECT_DETECTIONS_PROVENANCE
            ),
            sanitized_visible_object_detections_policy=(SANITIZED_VISIBLE_OBJECT_DETECTIONS_POLICY),
            public_destination_policy_for_category=_public_destination_policy_for_category,
            assert_no_forbidden_agent_view_keys=_assert_no_forbidden_agent_view_keys,
        )

    def _sanitized_visible_detection_payload(self, payload: dict[str, Any]) -> dict[str, Any]:
        return realworld_contract_payloads.sanitized_visible_detection_payload(
            payload,
            sanitized_visible_object_detections_provenance=(
                SANITIZED_VISIBLE_OBJECT_DETECTIONS_PROVENANCE
            ),
            sanitized_visible_object_detections_policy=(SANITIZED_VISIBLE_OBJECT_DETECTIONS_POLICY),
            public_destination_policy_for_category=_public_destination_policy_for_category,
        )

    def _public_fixture_response_id(
        self,
        internal_fixture_id: str,
        requested_fixture_id: str,
    ) -> str:
        return realworld_tool_responses.public_fixture_response_id(
            self,
            internal_fixture_id,
            requested_fixture_id,
        )

    def _public_fixture_reference_payload(self, value: Any) -> Any:
        return realworld_runtime_map_targets.public_fixture_reference_payload(self, value)

    def _public_fixture_reference_id(self, fixture_id: str) -> str:
        return realworld_runtime_map_targets.public_fixture_reference_id(self, fixture_id)

    def _internal_fixture_id_for_public_anchor(self, anchor_id: str) -> str:
        return realworld_runtime_map_targets.internal_fixture_id_for_public_anchor(self, anchor_id)

    def _public_waypoint_id_for_private_fixture(self, fixture_id: str) -> str:
        return realworld_runtime_map_targets.public_waypoint_id_for_private_fixture(
            self,
            fixture_id,
        )

    def policy_view_payload(self) -> dict[str, Any]:
        return realworld_contract_payloads.policy_view_payload(
            assert_no_forbidden_agent_view_keys=_assert_no_forbidden_agent_view_keys,
        )

    def cleanup_worklist_payload(
        self,
        *,
        static_fixture_projection: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        return realworld_contract_payloads.cleanup_worklist_payload(
            self,
            static_fixture_projection=static_fixture_projection,
            cleanup_worklist_schema=CLEANUP_WORKLIST_SCHEMA,
            non_actionable_handle_states=_NON_ACTIONABLE_HANDLE_STATES,
            candidate_actionability_status=_candidate_actionability_status,
            candidate_state=_candidate_state,
            public_destination_policy_for_category=_public_destination_policy_for_category,
            recommended_place_tool=_recommended_place_tool,
            assert_no_forbidden_agent_view_keys=_assert_no_forbidden_agent_view_keys,
        )

    def camera_model_policy_payload(self) -> dict[str, Any]:
        return realworld_contract_payloads.camera_model_policy_payload(
            self,
            camera_model_policy_schema=CAMERA_MODEL_POLICY_SCHEMA,
            camera_model_policy_mode=CAMERA_MODEL_POLICY_MODE,
            simulated_camera_model_provenance=SIMULATED_CAMERA_MODEL_PROVENANCE,
            sim_visual_grounding_pipeline_id=SIM_VISUAL_GROUNDING_PIPELINE_ID,
            external_visual_grounding_provenance=EXTERNAL_VISUAL_GROUNDING_PROVENANCE,
            average_duplicate_rate=_average_duplicate_rate,
        )

    def model_declared_observations_payload(self) -> dict[str, Any]:
        return realworld_contract_payloads.model_declared_observations_payload(
            self,
            model_declared_observations_schema=MODEL_DECLARED_OBSERVATIONS_SCHEMA,
        )

    def private_evaluation_payload(self, score: dict[str, Any]) -> dict[str, Any]:
        targets = self.scenario.private_manifest.targets
        return {
            "generated_mess_count": len(targets),
            "generated_mess_set": [target.object_id for target in targets],
            "acceptable_destination_sets": {
                target.object_id: list(target.valid_receptacle_ids) for target in targets
            },
            "mess_restoration_rate": score["mess_restoration_rate"],
            "sweep_coverage_rate": score["sweep_coverage_rate"],
            "disturbance_count": score["disturbance_count"],
            "completion_status": score["completion_status"],
            "object_results": score["object_results"],
        }

    def target_fixture_for_detection(
        self,
        detection: dict[str, Any],
        static_fixture_projection: dict[str, Any],
        *,
        include_runtime_backend_fixtures: bool = False,
    ) -> dict[str, Any] | None:
        return realworld_runtime_map_targets.target_fixture_for_detection(
            self,
            detection,
            static_fixture_projection,
            include_runtime_backend_fixtures=include_runtime_backend_fixtures,
        )

    def attach_raw_fpv_observation_artifact(
        self,
        observation_id: str,
        *,
        views: dict[str, Any],
        robot_view_label: str | None = None,
        camera_control_contract: dict[str, Any] | None = None,
    ) -> dict[str, Any] | None:
        for item in self._raw_fpv_observations:
            if item.get("observation_id") != observation_id:
                continue
            fpv_path = views.get("fpv")
            if fpv_path:
                item["image_artifacts"] = {"fpv": str(fpv_path)}
                item["fpv_image"] = str(fpv_path)
                item["artifact_status"] = "recorded"
                self._attach_private_raw_fpv_bindings(observation_id, str(fpv_path))
            if robot_view_label:
                item["robot_view_label"] = robot_view_label
            if camera_control_contract:
                item["camera_control_contract"] = _strip_forbidden_agent_view_keys(
                    camera_control_contract
                )
            _assert_no_forbidden_agent_view_keys(item)
            return dict(item)
        return None

    def _attach_private_raw_fpv_bindings(
        self,
        observation_id: str,
        fpv_path: str,
    ) -> None:
        resolved = Path(fpv_path)
        if not resolved.is_absolute() and self.visual_grounding_artifact_base_dir is not None:
            resolved = self.visual_grounding_artifact_base_dir / resolved
        bindings_path = resolved.with_suffix(".bindings.private.json")
        if not bindings_path.is_file():
            return
        payload = read_json_value(bindings_path, label="RAW-FPV private visual bindings")
        if not isinstance(payload, dict) or payload.get("schema") != "raw_fpv_private_bindings_v1":
            raise ValueError(f"invalid RAW-FPV private visual bindings: {bindings_path}")
        bindings = payload.get("bindings")
        if not isinstance(bindings, list):
            raise ValueError(
                f"RAW-FPV private visual bindings must contain a list: {bindings_path}"
            )
        self._private_raw_fpv_bindings_by_observation_id[observation_id] = payload

    def _place(self, fixture_id: str, *, inside: bool) -> dict[str, Any]:
        requested_fixture_id = str(fixture_id)
        internal_fixture_id = self._internal_fixture_id_for_public_anchor(requested_fixture_id)
        public_fixture_id = self._public_fixture_response_id(
            internal_fixture_id,
            requested_fixture_id,
        )
        if internal_fixture_id not in self._fixtures:
            return self._error(
                "place_inside" if inside else "place",
                "stale_reference",
                fixture_id=requested_fixture_id,
            )
        handle = self._held_handle
        if handle is None:
            return self._error("place_inside" if inside else "place", "not_holding")
        tool = "place_inside" if inside else "place"
        if self._current_receptacle_for_handle != (handle, internal_fixture_id):
            return self._semantic_order_error(
                tool,
                required_tool="navigate_to_receptacle",
                object_id=handle,
                fixture_id=requested_fixture_id,
                recovery_hint=(
                    "Call navigate_to_receptacle for this fixture after pick and before "
                    "placing the held object."
                ),
            )
        if not inside and _fixture_prefers_inside(self._fixtures[internal_fixture_id]):
            requires_open = _fixture_requires_open(self._fixtures[internal_fixture_id])
            needs_open = requires_open and self._opened_receptacle_for_handle != (
                handle,
                internal_fixture_id,
            )
            required_tool = "open_receptacle" if needs_open else "place_inside"
            return self._semantic_order_error(
                "place",
                required_tool=required_tool,
                object_id=handle,
                fixture_id=requested_fixture_id,
                recovery_hint=(
                    "Use place_inside for fridge-like or shelf-like fixtures; "
                    "fridge-like fixtures must be opened first."
                ),
            )
        if inside and _fixture_requires_open(self._fixtures[internal_fixture_id]):
            if self._opened_receptacle_for_handle != (handle, internal_fixture_id):
                return self._semantic_order_error(
                    "place_inside",
                    required_tool="open_receptacle",
                    object_id=handle,
                    fixture_id=requested_fixture_id,
                    recovery_hint=(
                        "Call open_receptacle for this fridge-like fixture before place_inside."
                    ),
                )
        placed = (
            self.contract.place_inside(internal_fixture_id)
            if inside
            else self.contract.place(internal_fixture_id)
        )
        if placed.get("ok"):
            self._handled_handles.add(handle)
            self._set_handle_state(
                handle,
                "placed",
                tool=tool,
                fixture_id=public_fixture_id,
            )
            if inside and _fixture_requires_open(self._fixtures[internal_fixture_id]):
                self._pending_close_receptacle_for_handle = (handle, internal_fixture_id)
            else:
                self._pending_close_receptacle_for_handle = None
            self._held_handle = None
            self._current_receptacle_for_handle = None
            self._opened_receptacle_for_handle = None
        return self._public_manipulation_response(
            tool,
            handle,
            placed,
            fixture_id=public_fixture_id,
        )

    def _visible_detections_for_waypoint(
        self,
        waypoint: dict[str, Any],
        *,
        source_observation_id: str,
        visual_confirmation: bool,
    ) -> list[dict[str, Any]]:
        return realworld_visual_candidate_lifecycle.visible_detections_for_waypoint(
            self,
            waypoint,
            source_observation_id=source_observation_id,
            visual_confirmation=visual_confirmation,
            visual_scan_payload=visual_scan_payload,
            assert_no_forbidden_agent_view_keys=_assert_no_forbidden_agent_view_keys,
        )

    def _camera_model_candidates_for_waypoint(
        self,
        waypoint: dict[str, Any],
        *,
        observation_id: str,
        model_provenance: str,
    ) -> list[dict[str, Any]]:
        return realworld_visual_candidate_lifecycle.camera_model_candidates_for_waypoint(
            self,
            waypoint,
            observation_id=observation_id,
            model_provenance=model_provenance,
            camera_model_policy_mode=CAMERA_MODEL_POLICY_MODE,
            assert_no_forbidden_agent_view_keys=_assert_no_forbidden_agent_view_keys,
        )

    def _public_candidate_hint(self, detection: dict[str, Any]) -> dict[str, Any]:
        candidate = self.target_fixture_for_detection(
            detection,
            self.static_fixture_projection(),
            include_runtime_backend_fixtures=True,
        )
        if candidate is None:
            return {
                "candidate_fixture_id": "",
                "candidate_fixture_category": "",
                "cleanup_recommended": False,
                "candidate_source": "public_category_fixture_affordance",
            }
        candidate_fixture_id = str(candidate.get("fixture_id") or "")
        source_fixture_id = str((detection.get("support_estimate") or {}).get("fixture_id") or "")
        internal_candidate_fixture_id = (
            self.internal_fixture_id_for_public_reference(candidate_fixture_id)
            or candidate_fixture_id
        )
        public_candidate_fixture_id = self._public_fixture_reference_id(candidate_fixture_id)
        public_source_fixture_id = self._public_fixture_reference_id(source_fixture_id)
        internal_source_fixture_id = (
            self.internal_fixture_id_for_public_reference(source_fixture_id) or source_fixture_id
        )
        source_fixture = self._fixtures.get(internal_source_fixture_id) or {}
        source_requires_cleanup = public_source_requires_cleanup(
            detection.get("category"),
            source_fixture.get("category") or source_fixture.get("name"),
        )
        return {
            "candidate_fixture_id": public_candidate_fixture_id,
            "candidate_fixture_category": str(candidate.get("category") or ""),
            "cleanup_recommended": bool(
                public_candidate_fixture_id
                and public_candidate_fixture_id != public_source_fixture_id
                and source_requires_cleanup
                and not self._handle_is_non_actionable(str(detection.get("object_id") or ""))
                and _candidate_state(detection) == CANDIDATE_STATE_NAVIGATION_AUTHORIZED
            ),
            "candidate_source": "public_semantic_anchor"
            if candidate_fixture_id
            else "public_category_fixture_affordance",
            "recommended_tool": _recommended_place_tool(
                internal_candidate_fixture_id,
                self._fixtures,
            ),
        }

    def _record_raw_fpv_observation(
        self,
        waypoint: dict[str, Any],
        *,
        perception_mode: str = RAW_FPV_ONLY_MODE,
    ) -> dict[str, Any]:
        return realworld_contract_payloads.record_raw_fpv_observation(
            self,
            waypoint,
            perception_mode=perception_mode,
        )

    def _record_inspection_observation(
        self,
        response: dict[str, Any],
        *,
        detections: list[dict[str, Any]],
        source_observation_id: str,
    ) -> None:
        realworld_contract_payloads.record_inspection_observation(
            self,
            response,
            detections=detections,
            source_observation_id=source_observation_id,
            inspection_observation_schema=INSPECTION_OBSERVATION_SCHEMA,
            target_candidate_evidence_lane=(
                realworld_runtime_map_targets.target_candidate_evidence_lane
            ),
            assert_no_forbidden_agent_view_keys=_assert_no_forbidden_agent_view_keys,
        )

    def _unresolved_visual_candidate_error(
        self,
        tool: str,
        object_id: str,
    ) -> dict[str, Any] | None:
        return realworld_visual_candidate_lifecycle.unresolved_visual_candidate_error(
            self,
            tool,
            object_id,
        )

    def _visual_evidence_for_handle(self, handle: str) -> dict[str, Any]:
        return realworld_visual_candidate_lifecycle.visual_evidence_for_handle(
            self,
            handle,
            assert_no_forbidden_agent_view_keys=_assert_no_forbidden_agent_view_keys,
        )

    def _visual_evidence_actionability_error(
        self,
        tool: str,
        object_id: str,
    ) -> dict[str, Any] | None:
        return realworld_visual_candidate_lifecycle.visual_evidence_actionability_error(
            self,
            tool,
            object_id,
            assert_no_forbidden_agent_view_keys=_assert_no_forbidden_agent_view_keys,
        )

    def _next_visible_observation_id(self) -> str:
        self._visible_observation_count += 1
        return f"world_label_fpv_{self._visible_observation_count:03d}"

    def _camera_scan_confirmed(self) -> bool:
        offset = self._camera_offset()
        waypoint = self._waypoint_by_id(self._current_waypoint_id) or {}
        return bool(
            offset.get("yaw_delta_deg")
            or offset.get("pitch_delta_deg")
            or waypoint.get("waypoint_source") == "generated_target_inspection_candidate"
        )

    def _raw_fpv_observation_by_id(self, observation_id: str | None) -> dict[str, Any] | None:
        if observation_id:
            for item in self._raw_fpv_observations:
                if item.get("observation_id") == observation_id:
                    return item
            return None
        return self._raw_fpv_observations[-1] if self._raw_fpv_observations else None

    def _camera_offset(self) -> dict[str, float]:
        return {
            "yaw_delta_deg": round(self._camera_yaw_offset_deg, 3),
            "pitch_delta_deg": round(self._camera_pitch_offset_deg, 3),
        }

    def _reset_camera_adjustment(self) -> None:
        self._camera_yaw_offset_deg = 0.0
        self._camera_pitch_offset_deg = 0.0

    def _public_navigation_waypoints(self) -> list[dict[str, Any]]:
        return [*self._public_waypoints, *self._generated_inspection_waypoints.values()]

    def _realworld_metrics(
        self,
        score: dict[str, Any],
        final_locations: dict[str, str],
    ) -> dict[str, Any]:
        total_targets = int(score.get("total_targets") or 0)
        restored_count = int(score.get("restored_count") or 0)
        mess_rate = restored_count / total_targets if total_targets else 0.0
        total_waypoints = len(self._waypoints)
        coverage = len(self._observed_waypoint_ids) / total_waypoints if total_waypoints else 1.0
        target_ids = {target.object_id for target in self.scenario.private_manifest.targets}
        disturbance = semantic_disturbance_metrics(
            self.scenario,
            self._initial_locations,
            final_locations,
            excluded_object_ids=target_ids,
        )
        disturbance_count = disturbance["disturbance_count"]
        completion_status = (
            "success"
            if mess_rate >= 0.70 and coverage >= 0.90 and disturbance_count <= 2
            else "partial_success"
            if restored_count
            else "failed"
        )
        return {
            "mess_restoration_rate": round(mess_rate, 6),
            "sweep_coverage_rate": round(coverage, 6),
            "disturbance_count": disturbance_count,
            "non_target_location_change_count": disturbance["non_target_location_change_count"],
            "completion_status": completion_status,
        }

    def _public_manipulation_response(
        self,
        tool: str,
        handle: str,
        response: dict[str, Any],
        *,
        fixture_id: str | None = None,
        navigate: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        return realworld_tool_responses.public_manipulation_response(
            self,
            tool,
            handle,
            response,
            fixture_id=fixture_id,
            navigate=navigate,
        )

    def _public_fixture_response(
        self,
        tool: str,
        fixture_id: str,
        response: dict[str, Any],
        *,
        object_id: str | None = None,
    ) -> dict[str, Any]:
        return realworld_tool_responses.public_fixture_response(
            self,
            tool,
            fixture_id,
            response,
            object_id=object_id,
        )

    def _public_error_from_private(
        self,
        tool: str,
        handle: str,
        response: dict[str, Any],
    ) -> dict[str, Any]:
        return realworld_tool_responses.public_error_from_private(self, tool, handle, response)

    def _current_room_id(self) -> str:
        waypoint = self._waypoint_by_id(self._current_waypoint_id)
        return str(waypoint["room_id"]) if waypoint is not None else ""

    def _current_pose(self) -> dict[str, float]:
        waypoint = self._waypoint_by_id(self._current_waypoint_id)
        if waypoint is None:
            return {"x": 0.0, "y": 0.0, "yaw": 0.0}
        return self._waypoint_pose(waypoint)

    @staticmethod
    def _waypoint_pose(waypoint: dict[str, Any]) -> dict[str, float]:
        return {
            "x": float(waypoint.get("x", 0.0)),
            "y": float(waypoint.get("y", 0.0)),
            "yaw": float(waypoint.get("yaw", 0.0)),
        }

    def _fixture_pose(self, fixture_id: str) -> dict[str, Any]:
        fixture = self._fixtures.get(fixture_id) or {}
        pose = fixture.get("pose") if isinstance(fixture.get("pose"), dict) else {}
        if pose:
            return {
                "frame_id": str(pose.get("frame_id") or "map"),
                "x": float(pose.get("x", 0.0)),
                "y": float(pose.get("y", 0.0)),
                "yaw": float(pose.get("yaw", 0.0)),
            }
        room = next((item for item in self._rooms if fixture_id in item["fixture_ids"]), None)
        if room is None:
            waypoint = self._waypoint_by_id(self._preferred_waypoint_for_fixture(fixture_id))
            pose = self._waypoint_pose(waypoint or {})
            return {"frame_id": "map", **pose}
        polygon = room.get("polygon") or []
        xs = [float(point.get("x", 0.0)) for point in polygon] or [0.0, 2.0]
        ys = [float(point.get("y", 0.0)) for point in polygon] or [0.0, 2.0]
        min_x, max_x = min(xs), max(xs)
        min_y, max_y = min(ys), max(ys)
        fixture_ids = sorted(str(item) for item in room["fixture_ids"])
        index = fixture_ids.index(fixture_id) if fixture_id in fixture_ids else 0
        slots = (
            (min_x + 0.35, min_y + 0.35),
            (max_x - 0.35, min_y + 0.35),
            (min_x + 0.35, max_y - 0.35),
            (max_x - 0.35, max_y - 0.35),
            (min_x + 0.35, (min_y + max_y) / 2.0),
            (max_x - 0.35, (min_y + max_y) / 2.0),
        )
        x, y = slots[index % len(slots)]
        pose = {"x": round(x, 3), "y": round(y, 3), "yaw": 0.0}
        return {"frame_id": "map", **pose}

    def _object_goal_pose(self, handle: str) -> dict[str, Any]:
        detection = self._detections_by_handle.get(handle) or {}
        support = detection.get("support_estimate") or {}
        fixture_id = str(support.get("fixture_id") or "")
        if fixture_id:
            pose = self._fixture_pose(fixture_id)
        else:
            pose = {"frame_id": "map", **self._current_pose()}
        return pose

    def _object_pose_confidence(self, handle: str) -> float:
        detection = self._detections_by_handle.get(handle) or {}
        confidence = detection.get("visibility_confidence")
        try:
            return float(confidence)
        except (TypeError, ValueError):
            return 0.5

    def _handle_is_non_actionable(self, handle: str) -> bool:
        return realworld_visual_candidate_lifecycle.handle_is_non_actionable(self, handle)

    def _preferred_waypoint_for_fixture(self, fixture_id: str) -> str:
        fixture = self._fixtures.get(fixture_id) or {}
        for key in ("preferred_inspection_waypoint_id", "preferred_manipulation_waypoint_id"):
            preferred = str(fixture.get(key) or "")
            if preferred and self._waypoint_by_id(preferred) is not None:
                return preferred
        for waypoint in self._waypoints:
            if fixture_id in set(waypoint.get("fixture_ids") or []):
                return str(waypoint["waypoint_id"])
        return self._current_waypoint_id

    def _record_detection_lifecycle(
        self,
        handle: str,
        detection: dict[str, Any],
        waypoint: dict[str, Any],
    ) -> None:
        state = "placed" if handle in self._handled_handles else "pending"
        if handle == self._held_handle:
            state = "held"
        elif handle == self._current_object_handle:
            state = "navigating_to_object"
        self._set_handle_state(
            handle,
            state,
            tool="observe",
            waypoint_id=str(waypoint["waypoint_id"]),
            room_id=str(waypoint["room_id"]),
            source_fixture_id=str((detection.get("support_estimate") or {}).get("fixture_id", "")),
            category=str(detection.get("category", "")),
            grounding_status=str(detection.get("grounding_status") or ""),
            perception_source=str(
                detection.get("perception_source")
                or detection.get("support_estimate", {}).get("source")
                or "visible_detection"
            ),
        )

    def _set_handle_state(self, handle: str, state: str, **updates: Any) -> None:
        lifecycle = getattr(self, "_object_lifecycle", None)
        if lifecycle is None:
            lifecycle = {}
            self._object_lifecycle = lifecycle
        item = dict(lifecycle.get(handle, {}))
        item.setdefault("object_id", handle)
        item["state"] = state
        item.update({key: value for key, value in updates.items() if value is not None})
        lifecycle[handle] = item

    def _mark_visual_scan_unresolved(self, handle: str, *, reason: str) -> None:
        self._set_handle_state(
            handle,
            "unresolved",
            tool="observe",
            grounding_status="unresolved",
            actionability_status="needs_clarification",
            visual_scan_failure_reason=reason,
        )

    def _waypoint_by_id(self, waypoint_id: str) -> dict[str, Any] | None:
        generated = self._generated_inspection_waypoints.get(str(waypoint_id))
        if generated is not None:
            return generated
        public_waypoint = next(
            (item for item in self._public_waypoints if item["waypoint_id"] == waypoint_id),
            None,
        )
        if public_waypoint is not None:
            return public_waypoint
        return next((item for item in self._waypoints if item["waypoint_id"] == waypoint_id), None)

    def _private_waypoint_for_public_waypoint(self, waypoint: dict[str, Any]) -> dict[str, Any]:
        if str(waypoint.get("waypoint_source") or "") == "generated_target_inspection_candidate":
            mapped = self._private_waypoint_by_public_id.get(str(waypoint.get("waypoint_id") or ""))
            return mapped or waypoint
        return (
            self._private_waypoint_by_public_id.get(str(waypoint.get("waypoint_id") or ""))
            or waypoint
        )

    def _backend_navigation_waypoint(self, waypoint: dict[str, Any]) -> dict[str, Any]:
        navigation_waypoint = dict(waypoint)
        room = next(
            (
                item
                for item in self._rooms
                if str(item.get("room_id") or "") == str(waypoint.get("room_id") or "")
            ),
            None,
        )
        bounds = _room_polygon_bounds(room) if room is not None else None
        if bounds is not None:
            navigation_waypoint["source_room_bounds"] = bounds
        return navigation_waypoint

    def _handle_for_object(self, object_id: str) -> str:
        existing = self._observed_handles_by_object_id.get(object_id)
        if existing is not None:
            return existing
        handle = self._new_observed_handle()
        self._observed_handles_by_object_id[object_id] = handle
        self._object_ids_by_handle[handle] = object_id
        return handle

    def _ensure_generated_inspection_waypoint_for_detection(
        self,
        handle: str,
        detection: dict[str, Any],
    ) -> dict[str, Any]:
        return (
            realworld_visual_candidate_lifecycle.ensure_generated_inspection_waypoint_for_detection(
                self,
                handle,
                detection,
                safe_anchor_id=_safe_anchor_id,
                assert_no_forbidden_agent_view_keys=_assert_no_forbidden_agent_view_keys,
            )
        )

    def _generated_inspection_waypoint_for_object(self, handle: str) -> dict[str, Any]:
        for waypoint in self._generated_inspection_waypoints.values():
            if str(waypoint.get("source_object_id") or "") == handle:
                return dict(waypoint)
        return {}

    def _internal_object_id(self, handle: str) -> str | None:
        return self._object_ids_by_handle.get(handle)

    def _new_unresolved_handle(self) -> str:
        return self._new_observed_handle()

    def _new_observed_handle(self) -> str:
        used = set(self._observed_handles_by_object_id.values()) | set(self._detections_by_handle)
        index = 1
        while True:
            handle = f"observed_{index:03d}"
            if handle not in used:
                return handle
            index += 1

    @staticmethod
    def _ok(tool: str, **payload: Any) -> dict[str, Any]:
        result = {"ok": True, "tool": tool, "status": "ok", **payload}
        _assert_no_forbidden_agent_view_keys(result)
        return result

    @staticmethod
    def _error(tool: str, error_reason: str, **payload: Any) -> dict[str, Any]:
        result = {
            "ok": False,
            "tool": tool,
            "status": "error",
            "error_reason": error_reason,
            **payload,
        }
        _assert_no_forbidden_agent_view_keys(result)
        return result

    def _semantic_order_error(
        self,
        tool: str,
        *,
        required_tool: str,
        recovery_hint: str,
        object_id: str | None = None,
        fixture_id: str | None = None,
    ) -> dict[str, Any]:
        return realworld_tool_responses.semantic_order_error(
            self,
            tool,
            required_tool=required_tool,
            semantic_loop_variant=SEMANTIC_LOOP_VARIANT,
            object_id=object_id,
            fixture_id=fixture_id,
            recovery_hint=recovery_hint,
        )


def _relative_pose_delta(
    forward_m: Any = 0.0,
    lateral_m: Any = 0.0,
    yaw_delta_deg: Any = 0.0,
) -> dict[str, float]:
    return {
        "forward_m": round(_float_or_zero(forward_m), 4),
        "lateral_m": round(_float_or_zero(lateral_m), 4),
        "yaw_delta_deg": round(_float_or_zero(yaw_delta_deg), 4),
    }


def _runtime_map_producer_summary(
    observed_objects: list[dict[str, Any]],
    *,
    public_semantic_anchors: list[dict[str, Any]] | None = None,
    map_update_candidates: list[dict[str, Any]] | None = None,
    target_candidates: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    return realworld_runtime_map_contract.runtime_map_producer_summary(
        observed_objects,
        public_semantic_anchors=public_semantic_anchors,
        map_update_candidates=map_update_candidates,
        target_candidates=target_candidates,
    )


def _visual_grounding_evidence_for_candidate(
    candidate: dict[str, Any],
    *,
    fallback_image_bbox: Any = None,
    grounding_status: str = "",
) -> dict[str, Any]:
    return realworld_visual_candidates._visual_grounding_evidence_for_candidate(
        candidate,
        fallback_image_bbox=fallback_image_bbox,
        grounding_status=grounding_status,
        assert_no_forbidden_agent_view_keys=_assert_no_forbidden_agent_view_keys,
    )


_candidate_state = realworld_visual_candidates._candidate_state
_float_or_zero = realworld_visual_candidates._float_or_zero
_clamp = realworld_visual_candidates._clamp
_average_duplicate_rate = realworld_visual_candidates._average_duplicate_rate
_declared_category_matches_object = realworld_visual_candidates._declared_category_matches_object


def _candidate_actionability_status(candidate: dict[str, Any]) -> str:
    return realworld_visual_candidates._candidate_actionability_status(
        candidate,
        visual_grounding_evidence_builder=_visual_grounding_evidence_for_candidate,
    )


def _visual_candidate_validation_error(
    candidate: Any,
    *,
    require_target_fixture_id: bool = True,
    perception_mode: str = VISIBLE_OBJECT_DETECTIONS_MODE,
    producer_type: str = "",
) -> dict[str, str] | None:
    return realworld_visual_candidates._visual_candidate_validation_error(
        candidate,
        require_target_fixture_id=require_target_fixture_id,
        perception_mode=perception_mode,
        producer_type=producer_type,
    )


def infer_target_fixture_for_detection(
    detection: dict[str, Any],
    static_fixture_projection: dict[str, Any],
) -> dict[str, Any] | None:
    return realworld_runtime_map_contract.infer_target_fixture_for_detection(
        detection,
        static_fixture_projection,
        norm=_norm,
        object_category_targets=_OBJECT_CATEGORY_TARGETS,
        first_matching_fixture=_first_matching_fixture,
        fixture_requires_open=_fixture_requires_open,
    )


def _target_fixture_from_detection_anchor(detection: dict[str, Any]) -> dict[str, Any] | None:
    return realworld_runtime_map_contract.target_fixture_from_detection_anchor(
        detection,
        fixture_requires_open=_fixture_requires_open,
    )


def forbidden_agent_view_keys() -> set[str]:
    return realworld_agent_view_contract.forbidden_agent_view_keys(_FORBIDDEN_AGENT_VIEW_KEYS)


def cleanup_policy_trace_from_events(
    trace_events: list[dict[str, Any]],
    agent_view: dict[str, Any],
) -> dict[str, Any]:
    return realworld_agent_view_contract.cleanup_policy_trace_from_events(
        trace_events,
        agent_view,
        builder=_cleanup_policy_trace_from_events,
        schema=CLEANUP_POLICY_TRACE_SCHEMA,
    )


def real_robot_readiness_from_events(
    *,
    agent_view: dict[str, Any],
    trace_events: list[dict[str, Any]],
    robot_view_steps: list[dict[str, Any]],
) -> dict[str, Any]:
    return realworld_agent_view_contract.real_robot_readiness_from_events(
        agent_view=agent_view,
        trace_events=trace_events,
        robot_view_steps=robot_view_steps,
        schema=REAL_ROBOT_READINESS_SCHEMA,
        api_semantic_provenance=API_SEMANTIC_PROVENANCE,
        sim_costmap_planner=SIM_COSTMAP_PLANNER,
        map_bundle_fields_present=_map_bundle_fields_present,
        pose_stamped_waypoints_present=_pose_stamped_waypoints_present,
        assert_no_forbidden_agent_view_keys=_assert_no_forbidden_agent_view_keys,
    )


def _safe_anchor_id(value: str) -> str:
    safe = re.sub(r"[^a-zA-Z0-9_]+", "_", value).strip("_")
    return safe or "unknown"


def _vec2(value: Any) -> tuple[float, float] | None:
    if not isinstance(value, (list, tuple)) or len(value) < 2:
        return None
    try:
        return (float(value[0]), float(value[1]))
    except (TypeError, ValueError):
        return None


def _norm(value: Any) -> str:
    return re.sub(r"[^a-z0-9]+", "", str(value).lower())


def _assert_no_forbidden_agent_view_keys(payload: Any) -> None:
    realworld_agent_view_contract.assert_no_forbidden_agent_view_keys(
        payload,
        _FORBIDDEN_AGENT_VIEW_KEYS,
    )


def _strip_forbidden_agent_view_keys(payload: Any) -> Any:
    return realworld_agent_view_contract.strip_forbidden_agent_view_keys(
        payload,
        _FORBIDDEN_AGENT_VIEW_KEYS,
    )


def _public_acceptance_config(config: dict[str, Any] | None) -> dict[str, Any]:
    return realworld_agent_view_contract.public_acceptance_config(
        config,
        normalize_household_intent=normalize_household_intent,
        assert_no_forbidden_agent_view_keys=_assert_no_forbidden_agent_view_keys,
    )


def _public_success_threshold(count: int | None) -> int:
    return realworld_agent_view_contract.public_success_threshold(count)


def _positive_int(value: Any) -> int | None:
    return realworld_agent_view_contract.positive_int(value)


def _nonnegative_int(value: Any) -> int:
    return realworld_agent_view_contract.nonnegative_int(value)
