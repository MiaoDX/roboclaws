from __future__ import annotations

from pathlib import Path
from typing import Any

from roboclaws.core.json_sources import read_json_value
from roboclaws.household import (
    realworld_contract_payloads,
    realworld_done_readiness,
    realworld_runtime_map_targets,
    realworld_tool_responses,
    realworld_visual_candidates,
)
from roboclaws.household.household_runtime_support import (
    _assert_no_forbidden_agent_view_keys,
    _average_duplicate_rate,
    _candidate_actionability_status,
    _candidate_state,
    _norm,
    _runtime_map_producer_summary,
    _strip_forbidden_agent_view_keys,
)
from roboclaws.household.realworld_contract_fixture_projection import (
    _fixture_prefers_inside,
    _fixture_requires_open,
    _public_destination_policy_for_category,
    _recommended_place_tool,
)
from roboclaws.household.realworld_contract_projection import (
    _merge_public_rooms,
    _room_category_hints_from_public_rooms,
)
from roboclaws.household.visual_grounding import (
    EXTERNAL_VISUAL_GROUNDING_PROVENANCE,
    SIM_VISUAL_GROUNDING_PIPELINE_ID,
)

REALWORLD_CONTRACT = "realworld_cleanup_v1"
RUNTIME_METRIC_MAP_SCHEMA = "runtime_metric_map_v1"
CLEANUP_WORKLIST_SCHEMA = "cleanup_worklist_v1"
VISIBLE_OBJECT_DETECTIONS_MODE = "visible_object_detections"
CAMERA_MODEL_POLICY_MODE = "camera_model_policy"
SANITIZED_VISIBLE_OBJECT_DETECTIONS_POLICY = "sanitized_visible_object_detections"
CAMERA_MODEL_POLICY_SCHEMA = "camera_model_policy_v1"
MODEL_DECLARED_OBSERVATIONS_SCHEMA = "model_declared_observations_v1"
SIMULATED_CAMERA_MODEL_PROVENANCE = realworld_visual_candidates.SIMULATED_CAMERA_MODEL_PROVENANCE
SANITIZED_VISIBLE_OBJECT_DETECTIONS_PROVENANCE = "sanitized_visible_object_detections"
_NON_ACTIONABLE_HANDLE_STATES = realworld_done_readiness.NON_ACTIONABLE_HANDLE_STATES
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


class HouseholdRuntimeArtifactsMixin:
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
