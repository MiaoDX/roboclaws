from __future__ import annotations

import time
from pathlib import Path
from typing import Any

from roboclaws.household import agent_view as agent_view_module
from roboclaws.household.agibot_sdk_runner import (
    AGIBOT_GDK_NORMAL_NAVI_PROVENANCE,
    BLOCKED_MANIPULATION_TOOLS,
    AgibotSDKRunnerAdapter,
)
from roboclaws.household.digital_twin_review_assets import attach_map12_review_assets
from roboclaws.household.manipulation_provenance import BLOCKED_CAPABILITY_PROVENANCE
from roboclaws.household.profiles import (
    AGIBOT_GDK_BACKEND_VARIANT,
    AGIBOT_SDK_RUNNER_BACKEND,
    PHYSICAL_ROBOT_EVIDENCE_LANE,
    agibot_gdk_evidence_metadata,
)
from roboclaws.household.realworld_contract import (
    CAMERA_MODEL_POLICY_MODE,
    CLEANUP_WORKLIST_SCHEMA,
    REAL_ROBOT_MAP_BUNDLE_SCHEMA,
    REALWORLD_CONTRACT,
)
from roboclaws.household.scenario import build_cleanup_scenario
from roboclaws.household.types import CleanupScenario
from roboclaws.household.visual_grounding import (
    EXTERNAL_VISUAL_GROUNDING_PROVENANCE,
    VisualGroundingClient,
    VisualGroundingContractError,
    image_payload_for_raw_observation,
    pipeline_summary_from_response,
    visual_grounding_client_from_env,
    visual_grounding_request,
)
from roboclaws.mcp.profiles import (
    HOUSEHOLD_EPISODE_PROFILE,
    HOUSEHOLD_MANIPULATION_PROFILE,
    HOUSEHOLD_WORLD_PROFILE,
)


class AgibotCleanupBackendSession:
    """CleanupBackendSession-shaped Agibot marker for shared MCP reports."""

    def __init__(self, scenario: CleanupScenario | None = None) -> None:
        self.scenario = scenario or build_cleanup_scenario(seed=7)
        self.backend = self

    def object_locations(self) -> dict[str, str]:
        return self.scenario.object_locations()

    def supports_visual_snapshots(self) -> bool:
        return False

    def write_visual_snapshot(self, output_path: Path, *, title: str) -> Path | None:
        del output_path, title
        return None

    def supports_robot_views(self) -> bool:
        return False

    def close(self) -> None:
        return None


class AgibotCleanupMCPContract:
    """Agibot adapter-backed implementation of the shared cleanup MCP contract."""

    def __init__(
        self,
        *,
        run_dir: Path,
        context_json: Path,
        runner_script: Path | None = None,
        runner_python: str | Path | None = None,
        real_movement_enabled: bool = False,
        agibot_map_artifact_dir: Path | None = None,
        scenario: CleanupScenario | None = None,
        task_prompt: str = "Build a Runtime Metric Map from Agibot G2 public evidence.",
        visual_grounding_pipeline_id: str = "grounding-dino",
        visual_grounding_timeout_s: float | None = None,
        visual_grounding_client: VisualGroundingClient | None = None,
    ) -> None:
        self.run_dir = Path(run_dir)
        self.scenario = scenario or build_cleanup_scenario(seed=7)
        self.contract = AgibotCleanupBackendSession(self.scenario)
        self.task_prompt = task_prompt
        self.perception_mode = CAMERA_MODEL_POLICY_MODE
        self.visual_grounding_pipeline_id = visual_grounding_pipeline_id
        self.visual_grounding_client = visual_grounding_client or visual_grounding_client_from_env(
            visual_grounding_pipeline_id,
            timeout_s=visual_grounding_timeout_s,
        )
        self.adapter = AgibotSDKRunnerAdapter(
            context_json=context_json,
            run_dir=run_dir,
            runner_script=runner_script,
            runner_python=runner_python,
            real_movement_enabled=real_movement_enabled,
            agibot_map_artifact_dir=agibot_map_artifact_dir,
        )
        self.real_movement_enabled = bool(real_movement_enabled)
        self._current_waypoint_id = ""
        self._visited_waypoint_ids: set[str] = set()
        self._observed_waypoint_ids: set[str] = set()
        self._raw_fpv_observations: list[dict[str, Any]] = []
        self._tool_event_counts: dict[str, int] = {}

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
        fixtures = {}
        for room in self.static_fixture_projection().get("rooms") or []:
            for fixture in room.get("fixtures") or []:
                fixture_id = str(fixture.get("fixture_id") or "")
                if fixture_id:
                    fixtures[fixture_id] = dict(fixture)
        return fixtures

    def internal_fixture_id_for_public_reference(self, fixture_id: str | None) -> str | None:
        return fixture_id

    def metric_map(self) -> dict[str, Any]:
        metric_map = dict(self.adapter.metric_map())
        metric_map.setdefault("schema", REAL_ROBOT_MAP_BUNDLE_SCHEMA)
        metric_map.setdefault("contract", REALWORLD_CONTRACT)
        metric_map.setdefault("tool", "metric_map")
        metric_map.setdefault("status", "ok")
        metric_map.setdefault("ok", True)
        metric_map["inspection_waypoints"] = [
            {
                **dict(item),
                "visited": str(item.get("waypoint_id") or "") in self._visited_waypoint_ids,
            }
            for item in metric_map.get("inspection_waypoints") or []
        ]
        metric_map["runtime_metric_map"] = self.runtime_metric_map_payload(
            metric_map=metric_map,
            static_fixture_projection=self.static_fixture_projection(),
        )
        return metric_map

    def static_fixture_projection(self) -> dict[str, Any]:
        payload = dict(self.adapter.static_fixture_projection())
        payload.setdefault("contract", REALWORLD_CONTRACT)
        payload.setdefault("tool", "static_fixture_projection")
        payload.setdefault("status", "ok")
        payload.setdefault("ok", True)
        payload.setdefault("schema", "static_fixture_projection_v1")
        return payload

    def navigate_to_room(self, room_id: str) -> dict[str, Any]:
        return self._remember_navigation(self.adapter.navigate_to_room(room_id=room_id))

    def navigate_to_waypoint(self, waypoint_id: str) -> dict[str, Any]:
        return self._remember_navigation(self.adapter.navigate_to_waypoint(waypoint_id=waypoint_id))

    def navigate_to_receptacle(self, fixture_id: str) -> dict[str, Any]:
        return self._remember_navigation(
            self.adapter.navigate_to_fixture_preferred_waypoint(fixture_id=fixture_id)
        )

    def navigate_to_object(self, object_id: str) -> dict[str, Any]:
        return self.adapter.navigate_to_object(object_id=object_id)

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
        producer_type: str = "",
        producer_id: str = "",
    ) -> dict[str, Any]:
        del category, evidence_note, image_region, source_fixture_id, confidence, producer_type
        del producer_id
        return self._remember_navigation(
            self.adapter.navigate_to_visual_candidate(
                source_observation_id=str(source_observation_id or ""),
                target_fixture_id=target_fixture_id,
            )
        )

    def observe(self) -> dict[str, Any]:
        response = dict(self.adapter.observe(label="shared_cleanup_mcp_observe"))
        waypoint_id = self._current_waypoint_id
        if waypoint_id:
            self._observed_waypoint_ids.add(waypoint_id)
        response.setdefault("current_room_id", "")
        response.setdefault("waypoint_id", waypoint_id)
        response.setdefault("perception_mode", self.perception_mode)
        response.setdefault("structured_detections_available", False)
        response.setdefault("visible_object_detections", [])
        response.setdefault("private_target_truth_included", False)
        raw = self._raw_observation_from_response(response, waypoint_id=waypoint_id)
        response["raw_fpv_observation"] = raw
        self._raw_fpv_observations.append(raw)
        return response

    def adjust_camera(self, yaw_delta_deg: float = 0.0, pitch_delta_deg: float = 0.0) -> dict:
        del yaw_delta_deg, pitch_delta_deg
        return self._blocked(
            "adjust_camera",
            "agibot_camera_motion_unproven",
            "Agibot G2 camera adjustment is blocked until bounded control is proven.",
        )

    def declare_visual_candidates(
        self,
        observation_id: str | None = None,
        *,
        candidates: list[dict[str, Any]] | tuple[dict[str, Any], ...] | None = None,
        producer_type: str = "",
        producer_id: str = "",
    ) -> dict[str, Any]:
        del candidates, producer_type, producer_id
        return self._blocked(
            "declare_visual_candidates",
            "agibot_cleanup_mcp_camera_labels_blocked",
            (
                "Use intent=map-build camera-grounded-labels for Agibot G2 visual grounding; "
                "the shared cleanup MCP path keeps manipulation and cleanup labels blocked."
            ),
            extra={"observation_id": observation_id or ""},
        )

    def inspect_visible_object(self, object_id: str) -> dict[str, Any]:
        return self._blocked(
            "inspect_visible_object",
            "agibot_cleanup_object_observation_unavailable",
            "No cleanup object handles are exposed by the Agibot shared MCP pilot.",
            extra={"object_id": object_id},
        )

    def pick(self, object_id: str) -> dict[str, Any]:
        return self._blocked_manipulation("pick", object_id=object_id)

    def open_receptacle(self, fixture_id: str) -> dict[str, Any]:
        return self._blocked_manipulation("open_receptacle", fixture_id=fixture_id)

    def place(self, fixture_id: str) -> dict[str, Any]:
        return self._blocked_manipulation("place", fixture_id=fixture_id)

    def place_inside(self, fixture_id: str) -> dict[str, Any]:
        return self._blocked_manipulation("place_inside", fixture_id=fixture_id)

    def close_receptacle(self, fixture_id: str) -> dict[str, Any]:
        return self._blocked_manipulation("close_receptacle", fixture_id=fixture_id)

    def done(
        self,
        reason: str = "",
        *,
        semantic_cleanup_evidence: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        del semantic_cleanup_evidence
        self._count("done")
        total_waypoints = len(self.metric_map().get("inspection_waypoints") or [])
        coverage = len(self._observed_waypoint_ids) / total_waypoints if total_waypoints else 1.0
        completion = (
            "physical_agibot_cleanup_pilot_rehearsal"
            if not self.real_movement_enabled
            else "physical_agibot_cleanup_pilot_complete"
        )
        score = {
            "completion_status": completion,
            "cleanup_status": completion,
            "restored_count": 0,
            "total_targets": 0,
            "object_results": [],
            "mess_restoration_rate": 0.0,
            "sweep_coverage_rate": round(coverage, 6),
            "disturbance_count": 0,
            "semantic_acceptability": {
                "accepted_count": 0,
                "total_targets": 0,
                "acceptance_rate": 0.0,
            },
        }
        return {
            "ok": True,
            "tool": "done",
            "status": "ok",
            "reason": reason,
            "cleanup_status": completion,
            "score": score,
            "final_locations": self.scenario.object_locations(),
            "final_containment": {},
            "tool_event_counts": dict(self._tool_event_counts),
            "contract": REALWORLD_CONTRACT,
            "policy_uses_private_truth": False,
        }

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

    def backend_name(self) -> str:
        return AGIBOT_SDK_RUNNER_BACKEND

    def run_result_overrides(self) -> dict[str, Any]:
        result = {
            "evidence_lane": PHYSICAL_ROBOT_EVIDENCE_LANE,
            "evidence_lane_metadata": agibot_gdk_evidence_metadata(),
            "backend": AGIBOT_SDK_RUNNER_BACKEND,
            "backend_variant": AGIBOT_GDK_BACKEND_VARIANT,
            "primitive_provenance": AGIBOT_GDK_NORMAL_NAVI_PROVENANCE
            if self._has_successful_gdk_navigation()
            else BLOCKED_CAPABILITY_PROVENANCE,
            "generated_mess_count": 0,
            "requested_generated_mess_count": 0,
            "manipulation_evidence": {
                "schema": "physical_manipulation_block_v1",
                "status": BLOCKED_CAPABILITY_PROVENANCE,
                "primitive_provenance": BLOCKED_CAPABILITY_PROVENANCE,
                "planner_backed": False,
                "strict_proof_eligible": False,
                "api_semantic_state_edits": False,
                "physical_robot": True,
                "backend": AGIBOT_GDK_BACKEND_VARIANT,
                "evidence_note": "Agibot shared cleanup MCP intentionally blocks manipulation.",
                "blockers": list(BLOCKED_MANIPULATION_TOOLS),
            },
            "agibot_sdk_runner": {
                "schema": "agibot_sdk_runner_boundary_v1",
                "backend_variant": AGIBOT_GDK_BACKEND_VARIANT,
                "runner_script": str(self.adapter.runner_script),
                "real_movement_enabled": self.real_movement_enabled,
                "gdk_imported_by_roboclaws": False,
                "public_tool_boundary": self.public_tool_names(),
                "subphase_reports": [
                    {
                        "stage": str(item.get("stage") or ""),
                        "status": str(item.get("status") or ""),
                        "primitive_provenance": str(item.get("primitive_provenance") or ""),
                    }
                    for item in self.adapter.subphase_results
                ],
            },
        }
        attach_map12_review_assets(self.run_dir, self.adapter.context_payload, result)
        return result

    def real_robot_readiness_payload(self, trace_events: list[dict[str, Any]]) -> dict[str, Any]:
        del trace_events
        total_waypoints = len(self.metric_map().get("inspection_waypoints") or [])
        observed_rate = (
            len(self._observed_waypoint_ids) / total_waypoints if total_waypoints else 1.0
        )
        movement_complete = self.real_movement_enabled and self._has_successful_gdk_navigation()
        return {
            "schema": "real_robot_readiness_v1",
            "status": "physical_agibot_cleanup_pilot_complete"
            if movement_complete
            else "physical_agibot_cleanup_pilot_rehearsal",
            "backend_variant": AGIBOT_GDK_BACKEND_VARIANT,
            "movement_enabled": self.real_movement_enabled,
            "physical_navigation_pilot": True,
            "map_build": True,
            "physical_cleanup_ready": False,
            "manipulation_ready": False,
            "manipulation_blocked": True,
            "visited_waypoint_ids": sorted(self._visited_waypoint_ids),
            "observed_waypoint_ids": sorted(self._observed_waypoint_ids),
            "observed_waypoint_rate": round(observed_rate, 6),
            "human_takeover_stop": False,
        }

    def cleanup_policy_trace_payload(self, trace_events: list[dict[str, Any]]) -> dict[str, Any]:
        events = []
        decisions = {
            "metric_map": "inspect_public_metric_map",
            "navigate_to_room": "visit_public_waypoint",
            "navigate_to_waypoint": "visit_public_waypoint",
            "navigate_to_receptacle": "visit_public_waypoint",
            "navigate_to_object": "visit_public_waypoint",
            "navigate_to_visual_candidate": "visit_public_waypoint",
            "observe": "observe_head_color",
        }
        for trace_event in trace_events:
            if trace_event.get("event") != "response":
                continue
            tool = str(trace_event.get("tool") or "")
            if tool == "done":
                continue
            response = trace_event.get("response") or {}
            events.append(
                {
                    "index": len(events) + 1,
                    "tool": tool,
                    "decision": decisions.get(tool, tool),
                    "status": response.get("status", ""),
                    "waypoint_id": response.get("waypoint_id", ""),
                }
            )
        return {
            "schema": "cleanup_policy_trace_v1",
            "agent_review_kind": "agibot_codex_map_build_review",
            "agent_reasoning_visible": True,
            "waypoint_source": "agibot_sdk_agent_view_export",
            "loop_style": "household_world_map_build",
            "cleanup_action_count": 0,
            "events": events,
        }

    def _remember_navigation(self, response: dict[str, Any]) -> dict[str, Any]:
        response = dict(response)
        waypoint_id = str(response.get("waypoint_id") or "")
        if waypoint_id:
            self._current_waypoint_id = waypoint_id
            self._visited_waypoint_ids.add(waypoint_id)
        return response

    def _raw_observation_from_response(
        self,
        response: dict[str, Any],
        *,
        waypoint_id: str,
    ) -> dict[str, Any]:
        artifact = response.get("camera_artifact") or response.get("fpv_image") or ""
        provenance = str(response.get("primitive_provenance") or "")
        return {
            "schema": "raw_fpv_observation_v1",
            "observation_id": str(
                response.get("observation_id") or f"agibot_observe_{time.time_ns()}"
            ),
            "source": "agibot_g2_policy_camera",
            "camera": str(
                response.get("policy_observation_camera")
                or response.get("would_capture_camera")
                or "head_color"
            ),
            "waypoint_id": waypoint_id,
            "perception_mode": self.perception_mode,
            "status": "ok" if response.get("ok") else "blocked_capability",
            "ok": bool(response.get("ok")),
            "primitive_provenance": provenance or BLOCKED_CAPABILITY_PROVENANCE,
            "image_artifacts": {"fpv": artifact} if artifact else {},
            "private_target_truth_included": False,
        }

    def _blocked_manipulation(
        self,
        tool: str,
        *,
        object_id: str = "",
        fixture_id: str = "",
    ) -> dict[str, Any]:
        extra = {}
        if object_id:
            extra["object_id"] = object_id
        if fixture_id:
            extra["fixture_id"] = fixture_id
            extra["receptacle_id"] = fixture_id
        return self._blocked(
            tool,
            "physical_manipulation_unproven",
            "Agibot physical manipulation remains blocked in the cleanup pilot.",
            extra=extra,
        )

    def _blocked(
        self,
        tool: str,
        failure_type: str,
        message: str,
        *,
        extra: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        payload = {
            "ok": False,
            "tool": tool,
            "status": "blocked_capability",
            "contract": REALWORLD_CONTRACT,
            "primitive_provenance": BLOCKED_CAPABILITY_PROVENANCE,
            "error_reason": "blocked_capability",
            "failure_type": failure_type,
            "backend_error_summary": message,
            "physical_navigation_pilot": True,
            "physical_cleanup_ready": False,
            "manipulation_ready": False,
        }
        if extra:
            payload.update(extra)
        return payload

    def _has_successful_gdk_navigation(self) -> bool:
        return any(
            item.get("primitive_provenance") == AGIBOT_GDK_NORMAL_NAVI_PROVENANCE and item.get("ok")
            for item in self.adapter.subphase_results
        )

    def _count(self, tool: str) -> None:
        self._tool_event_counts[f"{tool}:request"] = (
            self._tool_event_counts.get(f"{tool}:request", 0) + 1
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
