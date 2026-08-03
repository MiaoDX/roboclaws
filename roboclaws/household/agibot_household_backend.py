from __future__ import annotations

import time
from pathlib import Path
from typing import Any

from roboclaws.core.task_intents import HOUSEHOLD_INTENT_MAP_BUILD
from roboclaws.household.agibot_household_evidence import AgibotHouseholdEvidence
from roboclaws.household.agibot_household_projection import AgibotHouseholdProjection
from roboclaws.household.agibot_sdk_contract import (
    AGIBOT_GDK_NORMAL_NAVI_PROVENANCE,
)
from roboclaws.household.agibot_sdk_runner import (
    AgibotSDKRunnerAdapter,
)
from roboclaws.household.household_runtime_contract import (
    CAMERA_MODEL_POLICY_MODE,
    REAL_ROBOT_MAP_BUNDLE_SCHEMA,
    REALWORLD_CONTRACT,
)
from roboclaws.household.manipulation_contract import BLOCKED_CAPABILITY_PROVENANCE
from roboclaws.household.scenario import build_cleanup_scenario
from roboclaws.household.types import CleanupScenario
from roboclaws.household.visual_grounding import (
    VisualGroundingClient,
    visual_grounding_client_from_env,
)


class AgibotHouseholdBackendSession:
    """HouseholdBackendSession-shaped Agibot marker for shared MCP reports."""

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

    def requested_generated_mess_count(self) -> int:
        return 0

    def attach_runtime_metadata(self, run_result: dict[str, Any], *, run_dir: Path) -> None:
        del run_result, run_dir

    def close(self) -> None:
        return None


class AgibotHouseholdBackend(AgibotHouseholdProjection, AgibotHouseholdEvidence):
    """Agibot adapter-backed implementation of the shared cleanup MCP contract."""

    def __init__(
        self,
        *,
        run_dir: Path,
        context_json: Path,
        runner_script: Path,
        runner_python: str | Path,
        agibot_map_artifact_dir: Path,
        real_movement_enabled: bool = False,
        scenario: CleanupScenario | None = None,
        task_prompt: str = "Build a Runtime Metric Map from Agibot G2 public evidence.",
        visual_grounding_pipeline_id: str = "grounding-dino",
        visual_grounding_timeout_s: float | None = None,
        visual_grounding_client: VisualGroundingClient | None = None,
    ) -> None:
        self.run_dir = Path(run_dir)
        self.scenario = scenario or build_cleanup_scenario(seed=7)
        self.contract = AgibotHouseholdBackendSession(self.scenario)
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

    def evaluate_done_readiness(
        self,
        *,
        semantic_cleanup_evidence: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        del semantic_cleanup_evidence
        return {
            "schema": "done_readiness_v1",
            "status": "ready",
            "blockers": [],
            "policy_uses_private_truth": False,
            "task_intent": HOUSEHOLD_INTENT_MAP_BUILD,
            "public_contract_note": (
                "Agibot map-build completion uses public runtime map evidence only."
            ),
        }

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

    def planner_scene(self) -> dict[str, Any]:
        return {
            "schema": "planner_cleanup_proof_scene_v1",
            "available": False,
            "scene_xml": "",
            "backend": "",
        }

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
            "final_locations": {},
            "final_containment": {},
            "tool_event_counts": dict(self._tool_event_counts),
            "contract": REALWORLD_CONTRACT,
            "policy_uses_private_truth": False,
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
