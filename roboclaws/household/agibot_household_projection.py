"""Agent View and runtime-map projection for the Agibot household backend."""

from __future__ import annotations

from typing import Any

from roboclaws.household import agent_view as agent_view_module
from roboclaws.household.agibot_sdk_contract import BLOCKED_MANIPULATION_TOOLS
from roboclaws.household.household_runtime_contract import (
    CLEANUP_WORKLIST_SCHEMA,
    REALWORLD_CONTRACT,
)
from roboclaws.household.visual_grounding import (
    EXTERNAL_VISUAL_GROUNDING_PROVENANCE,
    VisualGroundingContractError,
    image_payload_for_raw_observation,
    pipeline_summary_from_response,
    visual_grounding_request,
)
from roboclaws.mcp.profiles import (
    HOUSEHOLD_EPISODE_PROFILE,
    HOUSEHOLD_MANIPULATION_PROFILE,
    HOUSEHOLD_WORLD_PROFILE,
)


def _public_map_hints(static_fixture_projection: dict[str, Any]) -> dict[str, Any]:
    fixtures = []
    for room in static_fixture_projection.get("rooms") or []:
        room_id = str(room.get("room_id") or "")
        for fixture in room.get("fixtures") or []:
            fixtures.append(
                {
                    "fixture_id": str(fixture.get("fixture_id") or ""),
                    "room_id": str(fixture.get("room_id") or room_id),
                    "category": str(fixture.get("category") or ""),
                    "name": str(fixture.get("name") or ""),
                    "affordances": list(fixture.get("affordances") or []),
                }
            )
    return {
        "schema": "visual_grounding_public_map_hints_v1",
        "source": "public_agent_view_map_evidence",
        "fixture_hints": fixtures,
        "private_truth_included": False,
    }


class AgibotHouseholdProjection:
    def agent_view_payload(self) -> dict[str, Any]:
        metric_map = self.metric_map()
        static_fixture_projection = self.static_fixture_projection()
        runtime_metric_map = self.runtime_metric_map_payload(
            metric_map=metric_map,
            static_fixture_projection=static_fixture_projection,
        )
        model_declared_evidence = {
            "schema": "model_declared_observations_v1",
            "perception_mode": self.perception_mode,
            "observation_count": 0,
            "resolved_count": 0,
            "acted_count": 0,
            "observations": [],
            "private_truth_included": False,
        }
        return agent_view_module.build_agent_view(
            contract=REALWORLD_CONTRACT,
            perception_mode=self.perception_mode,
            detection_exposure_policy="agibot_g2_policy_camera",
            structured_detections_available=False,
            base_metric_map=metric_map,
            runtime_metric_map=runtime_metric_map,
            observed_objects=[],
            raw_fpv_observations=[dict(item) for item in self._raw_fpv_observations],
            camera_model_policy_evidence=self.camera_model_policy_payload(),
            model_declared_observations=[],
            model_declared_observation_evidence=model_declared_evidence,
            policy_view=self.policy_view_payload(),
            cleanup_worklist=self.cleanup_worklist_payload(),
            observed_waypoint_ids=self._observed_waypoint_ids,
            public_tool_names=self.public_tool_names(),
            blocked_capabilities=BLOCKED_MANIPULATION_TOOLS,
            capability_profiles=(
                HOUSEHOLD_WORLD_PROFILE,
                HOUSEHOLD_MANIPULATION_PROFILE,
                HOUSEHOLD_EPISODE_PROFILE,
            ),
            forbidden_keys=frozenset(
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
            ),
        )

    def runtime_metric_map_payload(
        self,
        *,
        metric_map: dict[str, Any] | None = None,
        static_fixture_projection: dict[str, Any] | None = None,
        cleanup_worklist: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        del cleanup_worklist
        public_metric_map = dict(metric_map if metric_map is not None else self.metric_map())
        public_metric_map.pop("runtime_metric_map", None)
        public_static_fixture_projection = (
            static_fixture_projection
            if static_fixture_projection is not None
            else self.static_fixture_projection()
        )
        return {
            "schema": "runtime_metric_map_v1",
            "contract": REALWORLD_CONTRACT,
            "source": "household_world_mcp",
            "freshness": "current_run",
            "source_map_mutated": False,
            "private_truth_included": False,
            "static_map": {
                "rooms": [dict(item) for item in public_metric_map.get("rooms") or []],
                "fixtures": [
                    dict(fixture)
                    for room in public_static_fixture_projection.get("rooms") or []
                    for fixture in room.get("fixtures") or []
                ],
                "inspection_waypoints": [
                    dict(item) for item in public_metric_map.get("inspection_waypoints") or []
                ],
                "driveable_ways": [
                    dict(item) for item in public_metric_map.get("driveable_ways") or []
                ],
                "contains_runtime_observations": False,
            },
            "metric_map": public_metric_map,
            "static_fixture_projection": public_static_fixture_projection,
            "public_semantic_anchors": [],
            "observed_objects": [],
            "map_update_candidates": [],
            "visited_waypoint_ids": sorted(self._visited_waypoint_ids),
            "observed_waypoint_ids": sorted(self._observed_waypoint_ids),
            "cleanup_worklist_summary": {
                "schema": CLEANUP_WORKLIST_SCHEMA,
                "object_count": 0,
                "pending_count": 0,
                "held_object_id": None,
                "prior_count": 0,
            },
            "producer_summary": {
                "observed_object_count": 0,
                "public_semantic_anchor_count": 0,
                "map_update_candidate_count": 0,
            },
        }

    def cleanup_worklist_payload(
        self, *, static_fixture_projection: dict[str, Any] | None = None
    ) -> dict:
        del static_fixture_projection
        return {
            "schema": CLEANUP_WORKLIST_SCHEMA,
            "waypoint_source": "agibot_sdk_agent_view_export",
            "held_object_id": None,
            "objects": [],
            "waypoints": [
                {
                    "waypoint_id": str(item.get("waypoint_id") or ""),
                    "room_id": str(item.get("room_id") or ""),
                    "state": "visited"
                    if str(item.get("waypoint_id") or "") in self._observed_waypoint_ids
                    else "unvisited",
                    "purpose": str(item.get("purpose") or "inspect_fixture"),
                    "waypoint_source": str(item.get("waypoint_source") or ""),
                }
                for item in self.metric_map().get("inspection_waypoints") or []
            ],
            "rooms": [],
            "public_policy_note": (
                "Agibot shared cleanup MCP path exposes navigation and perception only; "
                "physical manipulation remains blocked."
            ),
        }

    def camera_model_policy_payload(self) -> dict[str, Any]:
        events = [self._camera_model_policy_event(item) for item in self._raw_fpv_observations]
        return {
            "schema": "camera_model_policy_v1",
            "perception_mode": self.perception_mode,
            "enabled": True,
            "model_provenance": EXTERNAL_VISUAL_GROUNDING_PROVENANCE,
            "visual_grounding_pipeline_id": self.visual_grounding_pipeline_id,
            "visual_grounding_pipeline_ids": [self.visual_grounding_pipeline_id],
            "visual_grounding_failure_count": sum(
                1
                for event in events
                if (event.get("visual_grounding_pipeline") or {}).get("status") != "ok"
            ),
            "event_count": len(self._raw_fpv_observations),
            "candidate_count": sum(int(item.get("candidate_count") or 0) for item in events),
            "unresolved_count": 0,
            "duplicate_rate": 0.0,
            "events": events,
            "private_truth_included": False,
            "policy_note": "Agibot G2 head_color evidence is robot-local public perception.",
        }

    def _camera_model_policy_event(self, raw: dict[str, Any]) -> dict[str, Any]:
        pipeline: dict[str, Any]
        candidates: list[dict[str, Any]] = []
        if not raw.get("ok") or not (raw.get("image_artifacts") or {}).get("fpv"):
            pipeline = {
                "schema": "visual_grounding_pipeline_v1",
                "pipeline_id": self.visual_grounding_pipeline_id,
                "status": "failed",
                "failure_reason": "no_live_camera_pixels",
                "stages": [
                    {
                        "stage": "agibot_head_color_capture",
                        "producer_id": "agibot_g2_policy_camera",
                        "status": str(raw.get("status") or "blocked"),
                    }
                ],
            }
        else:
            request = visual_grounding_request(
                run_id="household_world",
                raw_observation={**raw, "room_id": "", "artifact_status": raw.get("status", "ok")},
                category_hints=[],
                public_map_hints=_public_map_hints(self.static_fixture_projection()),
                pipeline_id=self.visual_grounding_pipeline_id,
                image=image_payload_for_raw_observation(raw, base_dir=self.run_dir),
            )
            try:
                response = self.visual_grounding_client.request_candidates(request)
                pipeline = pipeline_summary_from_response(response)
                candidates = list(response.get("candidates") or [])
            except VisualGroundingContractError as exc:
                pipeline = {
                    "schema": "visual_grounding_pipeline_v1",
                    "pipeline_id": self.visual_grounding_pipeline_id,
                    "status": "contract_error",
                    "failure_reason": "contract_error",
                    "failure_message": str(exc),
                    "stages": [],
                }
        return {
            "observation_id": raw.get("observation_id", ""),
            "room_id": "",
            "candidate_count": len(candidates),
            "registered_observed_handles": [],
            "visual_grounding_pipeline": pipeline,
        }

    def policy_view_payload(self) -> dict[str, Any]:
        return {
            "schema": "realworld_cleanup_policy_view_v1",
            "policy_observation_camera": "head_color",
            "allowed_inputs": [
                "base_metric_map",
                "runtime_metric_map",
                "raw_fpv_observations",
                "navigation_status",
            ],
            "excluded_report_only_views": ["private_operator_evidence", "private_evaluation"],
            "public_contract_note": (
                "Agibot G2 policy input uses head_color and public map context."
            ),
        }

    def private_evaluation_payload(self, score: dict[str, Any]) -> dict[str, Any]:
        return {
            "generated_mess_count": 0,
            "generated_mess_set": [],
            "acceptable_destination_sets": {},
            "mess_restoration_rate": score.get("mess_restoration_rate", 0.0),
            "sweep_coverage_rate": score.get("sweep_coverage_rate", 0.0),
            "disturbance_count": score.get("disturbance_count", 0),
            "completion_status": score.get("completion_status", ""),
            "object_results": [],
            "public_contract_note": "Agibot shared MCP pilot does not run private cleanup scoring.",
        }

    def attach_raw_fpv_observation_artifact(
        self,
        observation_id: str,
        *,
        views: dict[str, Any],
        robot_view_label: str | None = None,
        camera_control_contract: dict[str, Any] | None = None,
    ) -> dict[str, Any] | None:
        del views, robot_view_label, camera_control_contract
        for item in self._raw_fpv_observations:
            if item.get("observation_id") == observation_id:
                return dict(item)
        return None
