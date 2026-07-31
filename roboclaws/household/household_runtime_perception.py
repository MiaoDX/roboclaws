from __future__ import annotations

from typing import Any

import roboclaws.household.realworld_visual_perception_navigation as visual_perception
from roboclaws.household import (
    realworld_contract_payloads,
    realworld_done_readiness,
    realworld_runtime_target_selection,
    realworld_tool_responses,
    realworld_visual_candidates,
)
from roboclaws.household.household_runtime_support import (
    _assert_no_forbidden_agent_view_keys,
    _candidate_state,
    _safe_anchor_id,
)
from roboclaws.household.realworld_contract_fixture_projection import (
    _recommended_place_tool,
    _room_polygon_bounds,
)
from roboclaws.household.semantic_acceptability import (
    public_source_requires_cleanup,
    semantic_disturbance_metrics,
)
from roboclaws.household.semantic_timeline import SEMANTIC_LOOP_VARIANT
from roboclaws.household.visual_scan_guidance import (
    visual_scan_payload,
)

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
    (WORLD_LABELS_DETECTION_POLICY, SANITIZED_VISIBLE_OBJECT_DETECTIONS_POLICY)
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
_visual_candidates = realworld_visual_candidates
VISUAL_CANDIDATE_ALREADY_HANDLED_REASON = _visual_candidates.VISUAL_CANDIDATE_ALREADY_HANDLED_REASON
VISUAL_EVIDENCE_REVIEWABLE_STATUS = realworld_visual_candidates.VISUAL_EVIDENCE_REVIEWABLE_STATUS
VISUAL_EVIDENCE_NOT_REVIEWABLE_STATUS = _visual_candidates.VISUAL_EVIDENCE_NOT_REVIEWABLE_STATUS
CANDIDATE_STATE_SEMANTIC = realworld_visual_candidates.CANDIDATE_STATE_SEMANTIC
CANDIDATE_STATE_VISUALLY_CONFIRMED = realworld_visual_candidates.CANDIDATE_STATE_VISUALLY_CONFIRMED
CANDIDATE_STATE_NAVIGATION_AUTHORIZED = _visual_candidates.CANDIDATE_STATE_NAVIGATION_AUTHORIZED
VISUAL_GROUNDING_CATEGORY_HINTS = realworld_visual_candidates.VISUAL_GROUNDING_CATEGORY_HINTS
REALWORLD_PERCEPTION_MODES = frozenset(
    (VISIBLE_OBJECT_DETECTIONS_MODE, RAW_FPV_ONLY_MODE, CAMERA_MODEL_POLICY_MODE)
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


class HouseholdRuntimePerceptionMixin:
    def _visible_detections_for_waypoint(
        self,
        waypoint: dict[str, Any],
        *,
        source_observation_id: str,
        visual_confirmation: bool,
    ) -> list[dict[str, Any]]:
        return visual_perception.visible_detections_for_waypoint(
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
        return visual_perception.camera_model_candidates_for_waypoint(
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
                realworld_runtime_target_selection.target_candidate_evidence_lane
            ),
            assert_no_forbidden_agent_view_keys=_assert_no_forbidden_agent_view_keys,
        )

    def _unresolved_visual_candidate_error(
        self,
        tool: str,
        object_id: str,
    ) -> dict[str, Any] | None:
        return visual_perception.unresolved_visual_candidate_error(
            self,
            tool,
            object_id,
        )

    def _visual_evidence_for_handle(self, handle: str) -> dict[str, Any]:
        return visual_perception.visual_evidence_for_handle(
            self,
            handle,
            assert_no_forbidden_agent_view_keys=_assert_no_forbidden_agent_view_keys,
        )

    def _visual_evidence_actionability_error(
        self,
        tool: str,
        object_id: str,
    ) -> dict[str, Any] | None:
        return visual_perception.visual_evidence_actionability_error(
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
        return visual_perception.handle_is_non_actionable(self, handle)

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
        return visual_perception.ensure_generated_inspection_waypoint_for_detection(
            self,
            handle,
            detection,
            safe_anchor_id=_safe_anchor_id,
            assert_no_forbidden_agent_view_keys=_assert_no_forbidden_agent_view_keys,
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
