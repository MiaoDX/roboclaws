from __future__ import annotations

from typing import Any

import roboclaws.household.realworld_visual_perception_navigation as visual_perception
from roboclaws.core.raw_fpv_guidance import (
    RAW_FPV_DECLARATION_STRATEGY,
    raw_fpv_inline_candidate_instruction,
)
from roboclaws.household import (
    realworld_contract_projection,
    realworld_runtime_map_targets,
    realworld_visual_candidate_declarations,
    realworld_visual_candidates,
)
from roboclaws.household.household_runtime_support import (
    _assert_no_forbidden_agent_view_keys,
    _clamp,
    _float_or_zero,
    _relative_pose_delta,
    _strip_forbidden_agent_view_keys,
)
from roboclaws.household.manipulation_contract import API_SEMANTIC_PROVENANCE
from roboclaws.household.planner_observed_binding import (
    observed_handle_planner_binding,
)
from roboclaws.household.realworld_contract_projection import (
    _room_outline_by_id,
    _scene_index_fixture_pose,
)
from roboclaws.household.robot_view_pose import room_for_point
from roboclaws.household.target_query import resolve_target_query
from roboclaws.household.visual_scan_guidance import (
    VISUAL_SCAN_NOOP_ERROR_REASON,
    noop_camera_adjustment_hint,
)
from roboclaws.maps.bundle import static_landmarks_from_fixture_projection
from roboclaws.maps.route import SIM_COSTMAP_PLANNER, validate_metric_map_route

REALWORLD_CONTRACT = "realworld_cleanup_v1"
REAL_ROBOT_MAP_BUNDLE_SCHEMA = "real_robot_map_bundle_v1"
RAW_FPV_ONLY_MODE = "raw_fpv_only"
CAMERA_MODEL_POLICY_MODE = "camera_model_policy"
CAMERA_MODEL_POLICY_NAME = "camera_model_policy_baseline"
MAIN_CLEANUP_AGENT_PRODUCER = realworld_visual_candidates.MAIN_CLEANUP_AGENT_PRODUCER
SIMULATED_CAMERA_MODEL_PROVENANCE = realworld_visual_candidates.SIMULATED_CAMERA_MODEL_PROVENANCE
SANITIZED_VISIBLE_OBJECT_DETECTIONS_PROVENANCE = "sanitized_visible_object_detections"
CANDIDATE_STATE_NAVIGATION_AUTHORIZED = (
    realworld_visual_candidates.CANDIDATE_STATE_NAVIGATION_AUTHORIZED
)


class HouseholdRuntimeNavigationMixin:
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
        return visual_perception.navigate_to_visual_candidate(
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
