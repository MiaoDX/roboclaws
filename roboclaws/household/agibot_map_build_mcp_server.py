from __future__ import annotations

import json
import socket
import threading
import time
from pathlib import Path
from typing import Any

from mcp.server.fastmcp import FastMCP

from roboclaws.core.json_sources import read_jsonl_objects
from roboclaws.household import agent_view as agent_view_module
from roboclaws.household.agibot_map_build_mcp_tools import (
    AGIBOT_MAP_BUILD_TOOLS,
    dispatch_agibot_map_build_tool,
    register_agibot_map_build_tools,
)
from roboclaws.household.agibot_sdk_runner import BLOCKED_MANIPULATION_TOOLS, AgibotSDKRunnerAdapter
from roboclaws.household.digital_twin_review_assets import attach_map12_review_assets
from roboclaws.household.manipulation_provenance import BLOCKED_CAPABILITY_PROVENANCE
from roboclaws.household.profiles import (
    AGIBOT_GDK_BACKEND_VARIANT,
    AGIBOT_SDK_RUNNER_BACKEND,
    CAMERA_GROUNDED_LABELS_LANE,
    CAMERA_RAW_FPV_LANE,
    agibot_gdk_evidence_metadata,
    camera_labeler_from_visual_grounding_pipeline,
    camera_labeler_to_visual_grounding_pipeline,
    evidence_lane_names,
    validate_evidence_lane_camera_labeler,
)
from roboclaws.household.realworld_contract import (
    CAMERA_MODEL_POLICY_MODE,
    CLEANUP_WORKLIST_SCHEMA,
    RAW_FPV_ONLY_MODE,
    REALWORLD_CONTRACT,
    RUNTIME_METRIC_MAP_SCHEMA,
    VISIBLE_OBJECT_DETECTIONS_MODE,
    VISUAL_GROUNDING_CATEGORY_HINTS,
    forbidden_agent_view_keys,
)
from roboclaws.household.report import render_cleanup_report, write_state_snapshot
from roboclaws.household.scenario import build_cleanup_scenario
from roboclaws.household.types import CleanupScenario
from roboclaws.household.visual_grounding import (
    EXTERNAL_VISUAL_GROUNDING_PROVENANCE,
    SIM_VISUAL_GROUNDING_PIPELINE_ID,
    VISUAL_GROUNDING_PIPELINE_SCHEMA,
    VisualGroundingClient,
    VisualGroundingContractError,
    image_payload_for_raw_observation,
    pipeline_summary_from_response,
    visual_grounding_client_from_env,
    visual_grounding_failure_response,
    visual_grounding_request,
)
from roboclaws.mcp.profiles import (
    HOUSEHOLD_EPISODE_PROFILE,
    HOUSEHOLD_MANIPULATION_PROFILE,
    HOUSEHOLD_WORLD_PROFILE,
)

DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 18788
STARTUP_TIMEOUT_S = 2.0
MCP_SERVER_NAME = "agibot_map_build"
AGIBOT_MAP_BUILD_SCHEMA = "agibot_map_build_mcp_v1"
AGIBOT_MAP_BUILD_POLICY = "codex_agibot_map_build_pilot"
DEFAULT_TASK_PROMPT = (
    "Build a Runtime Metric Map from Agibot G2 public navigation and camera evidence."
)
AGIBOT_MAP_BUILD_LANES = frozenset(evidence_lane_names())


def make_agibot_map_build_mcp(
    *,
    run_dir: Path,
    context_json: Path,
    host: str = DEFAULT_HOST,
    port: int = DEFAULT_PORT,
    policy: str = AGIBOT_MAP_BUILD_POLICY,
    task_prompt: str = DEFAULT_TASK_PROMPT,
    runner_script: Path | None = None,
    runner_python: str | Path | None = None,
    real_movement_enabled: bool = False,
    agibot_map_artifact_dir: Path | None = None,
    evidence_lane: str = CAMERA_GROUNDED_LABELS_LANE,
    visual_grounding_pipeline_id: str = "grounding-dino",
    visual_grounding_timeout_s: float | None = None,
    visual_grounding_client: VisualGroundingClient | None = None,
    scenario: CleanupScenario | None = None,
) -> "AgibotMapBuildMCPServer":
    return AgibotMapBuildMCPServer(
        run_dir=run_dir,
        context_json=context_json,
        host=host,
        port=port,
        policy=policy,
        task_prompt=task_prompt,
        runner_script=runner_script,
        runner_python=runner_python,
        real_movement_enabled=real_movement_enabled,
        agibot_map_artifact_dir=agibot_map_artifact_dir,
        evidence_lane=evidence_lane,
        visual_grounding_pipeline_id=visual_grounding_pipeline_id,
        visual_grounding_timeout_s=visual_grounding_timeout_s,
        visual_grounding_client=visual_grounding_client,
        scenario=scenario,
    )


class AgibotMapBuildMCPServer:
    """FastMCP bridge for Agibot-backed intent=map-build pilot runs."""

    def __init__(
        self,
        *,
        run_dir: Path,
        context_json: Path,
        host: str = DEFAULT_HOST,
        port: int = DEFAULT_PORT,
        policy: str = AGIBOT_MAP_BUILD_POLICY,
        task_prompt: str = DEFAULT_TASK_PROMPT,
        runner_script: Path | None = None,
        runner_python: str | Path | None = None,
        real_movement_enabled: bool = False,
        agibot_map_artifact_dir: Path | None = None,
        evidence_lane: str = CAMERA_GROUNDED_LABELS_LANE,
        visual_grounding_pipeline_id: str = "grounding-dino",
        visual_grounding_timeout_s: float | None = None,
        visual_grounding_client: VisualGroundingClient | None = None,
        scenario: CleanupScenario | None = None,
    ) -> None:
        self.run_dir = Path(run_dir).resolve()
        self.run_dir.mkdir(parents=True, exist_ok=True)
        self.context_json = Path(context_json).resolve()
        self.host = host
        self.port = port
        self.policy = policy
        self.task_prompt = task_prompt
        self.evidence_lane = _normalized_evidence_lane(evidence_lane)
        self.perception_mode = _perception_mode_for_lane(self.evidence_lane)
        self.visual_grounding_pipeline_id = _normalized_visual_grounding_pipeline(
            visual_grounding_pipeline_id,
            evidence_lane=self.evidence_lane,
        )
        self.camera_labeler = camera_labeler_from_visual_grounding_pipeline(
            self.visual_grounding_pipeline_id
        )
        self.visual_grounding_client = (
            visual_grounding_client
            if visual_grounding_client is not None
            else visual_grounding_client_from_env(
                self.visual_grounding_pipeline_id,
                timeout_s=visual_grounding_timeout_s,
            )
        )
        self.visual_grounding_timeout_s = visual_grounding_timeout_s
        self.real_movement_enabled = bool(real_movement_enabled)
        self.scenario = scenario or build_cleanup_scenario(seed=7)
        self.adapter = AgibotSDKRunnerAdapter(
            context_json=self.context_json,
            run_dir=self.run_dir,
            runner_script=runner_script,
            runner_python=runner_python,
            real_movement_enabled=self.real_movement_enabled,
            agibot_map_artifact_dir=agibot_map_artifact_dir,
        )
        self.trace_path = self.run_dir / "trace.jsonl"
        self.run_result_path = self.run_dir / "run_result.json"
        self._started_at = time.time()
        self._trace_fp = self.trace_path.open("a", encoding="utf-8", buffering=1)
        self._trace_lock = threading.Lock()
        self._server_thread: threading.Thread | None = None
        self._closed = False
        self._done_result: dict[str, Any] | None = None
        self.done_event = threading.Event()
        self._mcp = FastMCP("roboclaws", host=host, port=port)
        self._before_snapshot = write_state_snapshot(
            self.scenario,
            _initial_locations(self.scenario),
            self.run_dir / "before.png",
            title="Before Agibot map build",
        )
        register_agibot_map_build_tools(self)
        self.write_runtime_event(
            "agibot_map_build_mcp_initialized",
            contract=REALWORLD_CONTRACT,
            policy=self.policy,
            backend_variant=AGIBOT_GDK_BACKEND_VARIANT,
            real_movement_enabled=self.real_movement_enabled,
            evidence_lane=self.evidence_lane,
            camera_labeler=self.camera_labeler,
            perception_mode=self.perception_mode,
            visual_grounding_pipeline_id=self.visual_grounding_pipeline_id,
        )

    @property
    def registered_tool_names(self) -> tuple[str, ...]:
        return AGIBOT_MAP_BUILD_TOOLS

    def call_tool(self, name: str, **kwargs: Any) -> dict[str, Any]:
        if name not in AGIBOT_MAP_BUILD_TOOLS:
            raise ValueError(f"unknown Agibot intent=map-build MCP tool {name!r}")
        if self.done_event.is_set() and name != "done":
            return {"ok": False, "tool": name, "status": "error", "error_reason": "run_done"}
        request = _json_safe(kwargs)
        self._write_trace(tool=name, event="request", arguments=request)
        try:
            response = dispatch_agibot_map_build_tool(self, name, request)
        except Exception as exc:  # noqa: BLE001
            response = {
                "ok": False,
                "tool": name,
                "status": "error",
                "error_reason": "exception",
                "error": str(exc),
            }
        response = _json_safe(response)
        self._write_trace(tool=name, event="response", response=response)
        if name == "done" and response.get("ok"):
            self.done_event.set()
        return response

    def _finalize_done(self, *, reason: str) -> dict[str, Any]:
        if self._done_result is not None:
            return self._done_result
        after_snapshot = write_state_snapshot(
            self.scenario,
            _initial_locations(self.scenario),
            self.run_dir / "after.png",
            title="After Agibot map build",
        )
        trace_events = self._read_trace_events()
        metric_map = self.adapter.metric_map()
        static_fixture_projection = self.adapter.static_fixture_projection()
        policy_events = _policy_events_from_trace(trace_events, metric_map)
        readiness = _readiness_from_trace(
            trace_events=trace_events,
            metric_map=metric_map,
            static_fixture_projection=static_fixture_projection,
            real_movement_enabled=self.real_movement_enabled,
        )
        raw_observations = _raw_fpv_observations_from_trace(
            trace_events,
            perception_mode=self.perception_mode,
        )
        camera_model_policy_evidence = _camera_model_policy_evidence(
            trace_events,
            perception_mode=self.perception_mode,
            visual_grounding_pipeline_id=self.visual_grounding_pipeline_id,
            raw_observations=raw_observations,
            static_fixture_projection=static_fixture_projection,
            run_dir=self.run_dir,
            visual_grounding_client=self.visual_grounding_client,
        )
        runtime_metric_map = _runtime_metric_map_payload(
            metric_map=metric_map,
            static_fixture_projection=static_fixture_projection,
            readiness=readiness,
        )
        agent_view = agent_view_module.build_agent_view(
            contract=REALWORLD_CONTRACT,
            perception_mode=self.perception_mode,
            detection_exposure_policy=self.evidence_lane,
            structured_detections_available=False,
            base_metric_map=metric_map,
            runtime_metric_map=runtime_metric_map,
            observed_objects=[],
            raw_fpv_observations=raw_observations,
            camera_model_policy_evidence=camera_model_policy_evidence,
            model_declared_observations=[],
            model_declared_observation_evidence={
                "schema": "model_declared_observations_v1",
                "perception_mode": self.perception_mode,
                "observation_count": 0,
                "resolved_count": 0,
                "acted_count": 0,
                "observations": [],
                "private_truth_included": False,
            },
            policy_view={
                "schema": "realworld_cleanup_policy_view_v1",
                "policy_observation_camera": "head_color",
                "allowed_inputs": [
                    "base_metric_map",
                    "runtime_metric_map",
                    "raw_fpv_observations",
                    "navigation_status",
                ],
                "excluded_report_only_views": [
                    "private_operator_evidence",
                    "private_evaluation",
                ],
                "chase_camera_policy_input": False,
            },
            cleanup_worklist={
                "schema": CLEANUP_WORKLIST_SCHEMA,
                "waypoint_source": "agibot_sdk_agent_view_export",
                "held_object_id": None,
                "objects": [],
                "waypoints": [
                    {
                        "waypoint_id": str(item.get("waypoint_id") or ""),
                        "room_id": str(item.get("room_id") or ""),
                        "state": "visited"
                        if str(item.get("waypoint_id") or "")
                        in set(readiness["observed_waypoint_ids"])
                        else "unvisited",
                        "purpose": str(item.get("purpose") or ""),
                        "waypoint_source": str(item.get("waypoint_source") or ""),
                    }
                    for item in metric_map.get("inspection_waypoints") or []
                ],
                "rooms": [],
            },
            observed_waypoint_ids=readiness["observed_waypoint_ids"],
            public_tool_names=list(AGIBOT_MAP_BUILD_TOOLS),
            blocked_capabilities=BLOCKED_MANIPULATION_TOOLS,
            capability_profiles=(
                HOUSEHOLD_WORLD_PROFILE,
                HOUSEHOLD_MANIPULATION_PROFILE,
                HOUSEHOLD_EPISODE_PROFILE,
            ),
            forbidden_keys=forbidden_agent_view_keys(),
        )
        run_result = {
            "schema": AGIBOT_MAP_BUILD_SCHEMA,
            "contract": REALWORLD_CONTRACT,
            "backend": AGIBOT_SDK_RUNNER_BACKEND,
            "backend_variant": AGIBOT_GDK_BACKEND_VARIANT,
            "backend_evidence": agibot_gdk_evidence_metadata(),
            "policy": self.policy,
            "planner": self.policy,
            "agent_driven": True,
            "mcp_server": MCP_SERVER_NAME,
            "scenario_id": self.scenario.scenario_id,
            "task_prompt": self.task_prompt,
            "seed": self.scenario.seed,
            "evidence_lane": self.evidence_lane,
            "camera_labeler": self.camera_labeler,
            "perception_mode": self.perception_mode,
            "visual_grounding_pipeline_id": self.visual_grounding_pipeline_id,
            "cleanup_status": readiness["status"],
            "completion_status": readiness["status"],
            "terminate_reason": reason,
            "primitive_provenance": _dominant_provenance(trace_events),
            "generated_mess_count": 0,
            "requested_generated_mess_count": 0,
            "sweep_coverage_rate": readiness["observed_waypoint_rate"],
            "disturbance_count": 0,
            "score": _empty_score(readiness["observed_waypoint_rate"]),
            "private_evaluation": {
                "generated_mess_count": 0,
                "generated_mess_set": [],
                "acceptable_destination_sets": {},
                "mess_restoration_rate": 0.0,
                "sweep_coverage_rate": readiness["observed_waypoint_rate"],
                "disturbance_count": 0,
                "public_contract_note": (
                    "Agibot intent=map-build does not run private cleanup scoring."
                ),
            },
            "agent_view": agent_view,
            "raw_fpv_observations": raw_observations,
            "camera_model_policy_evidence": camera_model_policy_evidence,
            "runtime_metric_map": runtime_metric_map,
            "cleanup_policy_trace": {
                "schema": "cleanup_policy_trace_v1",
                "agent_review_kind": "agibot_codex_map_build_review",
                "agent_reasoning_visible": True,
                "waypoint_source": "agibot_sdk_agent_view_export",
                "loop_style": "codex_agibot_map_build",
                "total_waypoints": len(metric_map.get("inspection_waypoints") or []),
                "visited_waypoint_count": len(readiness["visited_waypoint_ids"]),
                "observed_waypoint_count": len(readiness["observed_waypoint_ids"]),
                "scan_observe_count": readiness["observe_count"],
                "cleanup_action_count": 0,
                "placed_object_count": 0,
                "post_place_observe_count": 0,
                "post_place_observe_complete": True,
                "first_cleanup_before_full_survey": False,
                "events": policy_events,
                "operator_review_note": (
                    "Agibot intent=map-build records Codex-visible map, navigation, "
                    "observation, skipped waypoint, and blocked manipulation decisions."
                ),
            },
            "semantic_substeps": [],
            "real_robot_readiness": readiness,
            "agibot_sdk_runner": {
                "schema": "agibot_sdk_runner_boundary_v1",
                "backend_variant": AGIBOT_GDK_BACKEND_VARIANT,
                "runner_script": str(self.adapter.runner_script),
                "real_movement_enabled": self.real_movement_enabled,
                "subphase_reports": _subphase_reports(self.adapter.subphase_results, self.run_dir),
                "gdk_imported_by_roboclaws": False,
                "public_tool_boundary": list(AGIBOT_MAP_BUILD_TOOLS),
            },
            "manipulation_evidence": {
                "schema": "physical_manipulation_block_v1",
                "status": "blocked_capability",
                "primitive_provenance": BLOCKED_CAPABILITY_PROVENANCE,
                "planner_backed": False,
                "strict_proof_eligible": False,
                "api_semantic_state_edits": 0,
                "evidence_note": (
                    "Agibot intent=map-build intentionally disables physical manipulation."
                ),
                "blockers": list(BLOCKED_MANIPULATION_TOOLS),
            },
            "artifacts": {
                "run_result": "run_result.json",
                "trace": "trace.jsonl",
                "before_snapshot": "before.png",
                "after_snapshot": "after.png",
                "report": "report.html",
                "agibot_subphases": "subphases",
                "runtime_metric_map": "runtime_metric_map.json",
            },
            "runtime_timing": _runtime_timing(trace_events),
        }
        (self.run_dir / "runtime_metric_map.json").write_text(
            json.dumps(run_result["runtime_metric_map"], indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        attach_map12_review_assets(self.run_dir, self.adapter.context_payload, run_result)
        report_path = render_cleanup_report(
            run_dir=self.run_dir,
            scenario=self.scenario,
            run_result=run_result,
            trace_events=trace_events,
            before_snapshot=self._before_snapshot,
            after_snapshot=after_snapshot,
            robot_view_steps=[],
        )
        run_result["artifacts"]["report"] = str(report_path)
        self.run_result_path.write_text(
            json.dumps(run_result, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        self._done_result = {
            "ok": True,
            "tool": "done",
            "status": "ok",
            "cleanup_status": run_result["cleanup_status"],
            "run_result": str(self.run_result_path),
            "report": str(report_path),
            "contract": REALWORLD_CONTRACT,
            "agent_driven": True,
        }
        return self._done_result

    def write_runtime_event(self, event: str, **data: Any) -> None:
        self._write_trace(tool="<runtime>", event=event, **data)

    def run_in_thread(self) -> threading.Thread:
        if self._server_thread is not None and self._server_thread.is_alive():
            return self._server_thread
        thread = threading.Thread(
            target=self._mcp.run,
            kwargs={"transport": "streamable-http"},
            name=f"agibot-map-build-mcp-{self.port}",
            daemon=True,
        )
        thread.start()
        self._server_thread = thread
        if self.port == 0:
            return thread
        deadline = time.monotonic() + STARTUP_TIMEOUT_S
        probe_host = "127.0.0.1" if self.host in {"0.0.0.0", "::"} else self.host
        while time.monotonic() < deadline:
            if not thread.is_alive():
                raise RuntimeError(
                    f"Agibot intent=map-build MCP server failed on {self.host}:{self.port}"
                )
            if _port_accepting(probe_host, self.port):
                return thread
            time.sleep(0.05)
        raise RuntimeError(
            f"Agibot intent=map-build MCP server did not start on {self.host}:{self.port}"
        )

    def close(self) -> None:
        if self._closed:
            return
        try:
            shutdown = getattr(self._mcp, "shutdown", None)
            if callable(shutdown):
                shutdown()
        except Exception:
            pass
        with self._trace_lock:
            self._closed = True
            try:
                self._trace_fp.close()
            except Exception:
                pass
        if self._server_thread is not None:
            self._server_thread.join(timeout=0.5)

    def _observe_count(self) -> int:
        return sum(
            1
            for event in self._read_trace_events()
            if event.get("tool") == "observe" and event.get("event") == "response"
        )

    def _write_trace(self, *, tool: str, event: str, **data: Any) -> None:
        payload = {
            "ts": time.time(),
            "wallclock_elapsed": time.time() - self._started_at,
            "tool": tool,
            "event": event,
            **_json_safe(data),
        }
        with self._trace_lock:
            self._trace_fp.write(json.dumps(payload, sort_keys=True) + "\n")
            self._trace_fp.flush()

    def _read_trace_events(self) -> list[dict[str, Any]]:
        try:
            self._trace_fp.flush()
        except Exception:
            pass
        if not self.trace_path.is_file():
            return []
        return read_jsonl_objects(self.trace_path, label="Agibot map-build MCP trace")


def _policy_events_from_trace(
    trace_events: list[dict[str, Any]],
    metric_map: dict[str, Any],
) -> list[dict[str, Any]]:
    responses = [
        event
        for event in trace_events
        if event.get("event") == "response" and isinstance(event.get("response"), dict)
    ]
    selected_waypoints = {
        str((event.get("response") or {}).get("waypoint_id") or "")
        for event in responses
        if event.get("tool")
        in {"navigate_to_waypoint", "navigate_to_room", "navigate_to_receptacle"}
    }
    selected_waypoints.discard("")
    events: list[dict[str, Any]] = []
    for event in responses:
        tool = str(event.get("tool") or "")
        response = dict(event.get("response") or {})
        if tool == "done":
            continue
        events.append(_policy_event(len(events), tool, response))
    for waypoint in metric_map.get("inspection_waypoints") or []:
        if not isinstance(waypoint, dict):
            continue
        waypoint_id = str(waypoint.get("waypoint_id") or "")
        if not waypoint_id or waypoint_id in selected_waypoints:
            continue
        events.append(
            {
                "index": len(events) + 1,
                "tool": "navigate_to_waypoint",
                "role": "inspection_waypoint",
                "waypoint_id": waypoint_id,
                "fixture_id": waypoint.get("fixture_id", ""),
                "status": "skipped",
                "decision": "skip_public_waypoint",
                "progress": f"Skipped public waypoint {waypoint_id}; Codex did not visit it.",
                "reason": (
                    "The report keeps skipped generated/public waypoints visible "
                    "for operator review."
                ),
            }
        )
    return events


def _policy_event(index: int, tool: str, response: dict[str, Any]) -> dict[str, Any]:
    decision = {
        "metric_map": "inspect_public_metric_map",
        "navigate_to_room": "visit_public_waypoint",
        "navigate_to_waypoint": "visit_public_waypoint",
        "navigate_to_receptacle": "visit_public_waypoint",
        "navigate_to_object": "visit_public_waypoint",
        "navigate_to_visual_candidate": "visit_public_waypoint",
        "observe": "observe_head_color",
        "adjust_camera": "block_camera_adjustment",
        "pick": "block_manipulation",
        "place": "block_manipulation",
        "place_inside": "block_manipulation",
        "open_receptacle": "block_manipulation",
        "close_receptacle": "block_manipulation",
    }.get(tool, tool)
    return {
        "index": index + 1,
        "tool": response.get("tool", tool),
        "role": _policy_role(tool),
        "waypoint_id": response.get("waypoint_id", ""),
        "object_id": response.get("object_id", ""),
        "fixture_id": response.get("fixture_id", ""),
        "navigation_backend": response.get("navigation_backend", ""),
        "status": response.get("status") or response.get("navigation_status", ""),
        "decision": decision,
        "progress": _policy_progress(tool, response),
        "reason": _policy_reason(tool, response),
    }


def _policy_role(tool: str) -> str:
    if tool.startswith("navigate"):
        return "navigation"
    if tool == "observe":
        return "policy_observation"
    if tool in BLOCKED_MANIPULATION_TOOLS:
        return "blocked_manipulation"
    return "map_build_context"


def _policy_progress(tool: str, response: dict[str, Any]) -> str:
    if tool == "observe":
        camera = response.get("policy_observation_camera") or response.get("would_capture_camera")
        return f"Observed Agibot policy camera {camera or 'head_color'}."
    if tool.startswith("navigate"):
        waypoint = response.get("waypoint_id", "")
        status = response.get("navigation_status") or response.get("status")
        return f"Navigation tool {tool} targeted {waypoint or 'unresolved waypoint'}: {status}."
    if tool in BLOCKED_MANIPULATION_TOOLS:
        return f"Physical manipulation is intentionally blocked: {tool}."
    if tool == "adjust_camera":
        return "Agibot camera adjustment is intentionally blocked."
    return f"Codex called {tool}."


def _policy_reason(tool: str, response: dict[str, Any]) -> str:
    if tool == "metric_map":
        return "Metric map is the backend-agnostic public navigation context."
    if tool == "observe":
        return "Agibot G2 map building uses robot-local head_color evidence."
    if tool.startswith("navigate"):
        return "Navigation must resolve through verified public Agibot waypoints."
    if tool in BLOCKED_MANIPULATION_TOOLS:
        return "The first Agibot G2 milestone is navigation and perception, not cleanup."
    if tool == "adjust_camera":
        return "Bounded G2 camera motion remains unproven."
    return str(response.get("backend_error_summary") or "")


def _readiness_from_trace(
    *,
    trace_events: list[dict[str, Any]],
    metric_map: dict[str, Any],
    static_fixture_projection: dict[str, Any],
    real_movement_enabled: bool,
) -> dict[str, Any]:
    responses = [
        dict(event.get("response") or {})
        for event in trace_events
        if event.get("event") == "response" and isinstance(event.get("response"), dict)
    ]
    waypoint_responses = [
        item
        for item in responses
        if item.get("tool")
        in {"navigate_to_waypoint", "navigate_to_room", "navigate_to_receptacle"}
        and item.get("waypoint_id")
    ]
    observed_count = sum(1 for item in responses if item.get("tool") == "observe")
    observed_waypoint_ids = [
        str(item.get("waypoint_id") or "")
        for item in waypoint_responses
        if item.get("ok") or item.get("navigation_status") == "dry_run_not_executed"
    ]
    observed_waypoint_ids = [item for item in dict.fromkeys(observed_waypoint_ids) if item]
    total = len(metric_map.get("inspection_waypoints") or [])
    rate = (len(observed_waypoint_ids) / total) if total else 0.0
    return {
        "schema": "real_robot_readiness_v1",
        "status": "physical_agibot_map_build_complete"
        if real_movement_enabled and rate >= 1.0
        else "physical_agibot_map_build_rehearsal",
        "real_robot_ready": False,
        "navigation_perception_ready": bool(real_movement_enabled and rate >= 1.0),
        "backend_variant": AGIBOT_GDK_BACKEND_VARIANT,
        "movement_enabled": real_movement_enabled,
        "map_bundle_schema": metric_map.get("schema", ""),
        "map_bundle_fields_present": bool(metric_map.get("inspection_waypoints") is not None),
        "pose_stamped_waypoints": True,
        "static_fixture_projection": (
            static_fixture_projection.get("schema") == "static_fixture_projection_v1"
        ),
        "physical_navigation_pilot": True,
        "physical_cleanup_ready": False,
        "map_build": True,
        "inspection_waypoint_attempt_count": len(waypoint_responses),
        "inspection_waypoint_total": total,
        "reached_waypoint_count": sum(1 for item in waypoint_responses if item.get("ok")),
        "observed_reached_waypoint_count": len(observed_waypoint_ids),
        "observed_reached_waypoint_rate": rate,
        "observed_waypoint_rate": rate,
        "visited_waypoint_ids": observed_waypoint_ids,
        "observed_waypoint_ids": observed_waypoint_ids if observed_count else [],
        "observe_count": observed_count,
        "manipulation_blocked": True,
        "blocked_capabilities": list(BLOCKED_MANIPULATION_TOOLS),
        "human_takeover_stop": any(
            item.get("failure_type", "").startswith("operator_") for item in responses
        ),
        "public_contract_note": (
            "Agibot intent=map-build uses task-neutral household public tools while "
            "the SDK runner owns GDK map, camera, and PNC evidence."
        ),
    }


def _runtime_metric_map_payload(
    *,
    metric_map: dict[str, Any],
    static_fixture_projection: dict[str, Any],
    readiness: dict[str, Any],
) -> dict[str, Any]:
    return {
        "schema": RUNTIME_METRIC_MAP_SCHEMA,
        "contract": REALWORLD_CONTRACT,
        "freshness": "current_run",
        "source": "agibot_map_build_mcp",
        "source_map_mutated": False,
        "private_truth_included": False,
        "metric_map": metric_map,
        "static_fixture_projection": static_fixture_projection,
        "static_map": {
            "rooms": [dict(item) for item in metric_map.get("rooms") or []],
            "fixtures": [
                dict(fixture)
                for room in static_fixture_projection.get("rooms") or []
                for fixture in room.get("fixtures") or []
                if isinstance(fixture, dict)
            ],
            "inspection_waypoints": [
                dict(item) for item in metric_map.get("inspection_waypoints") or []
            ],
            "driveable_ways": [dict(item) for item in metric_map.get("driveable_ways") or []],
            "contains_runtime_observations": False,
        },
        "public_semantic_anchors": [],
        "observed_objects": [],
        "target_candidates": [],
        "map_update_candidates": [],
        "visited_waypoint_ids": readiness["visited_waypoint_ids"],
        "observed_waypoint_ids": readiness["observed_waypoint_ids"],
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


def _normalized_evidence_lane(value: str) -> str:
    lane = str(value or CAMERA_GROUNDED_LABELS_LANE).strip() or CAMERA_GROUNDED_LABELS_LANE
    if lane not in AGIBOT_MAP_BUILD_LANES:
        raise ValueError(
            f"unsupported Agibot intent=map-build evidence lane {lane!r}; "
            "expected smoke|world-public-labels|camera-grounded-labels|camera-raw-fpv"
        )
    return lane


def _perception_mode_for_lane(evidence_lane: str) -> str:
    if evidence_lane == CAMERA_RAW_FPV_LANE:
        return RAW_FPV_ONLY_MODE
    if evidence_lane == CAMERA_GROUNDED_LABELS_LANE:
        return CAMERA_MODEL_POLICY_MODE
    return VISIBLE_OBJECT_DETECTIONS_MODE


def _normalized_visual_grounding_pipeline(
    value: str,
    *,
    evidence_lane: str,
) -> str:
    selected = str(value or "").strip()
    if selected:
        labeler = camera_labeler_from_visual_grounding_pipeline(selected)
    elif evidence_lane == CAMERA_GROUNDED_LABELS_LANE:
        labeler = "grounding-dino"
    else:
        labeler = ""
    validate_evidence_lane_camera_labeler(evidence_lane=evidence_lane, camera_labeler=labeler)
    if labeler:
        return camera_labeler_to_visual_grounding_pipeline(labeler)
    return SIM_VISUAL_GROUNDING_PIPELINE_ID


def _raw_fpv_observations_from_trace(
    trace_events: list[dict[str, Any]],
    *,
    perception_mode: str,
) -> list[dict[str, Any]]:
    if perception_mode not in {RAW_FPV_ONLY_MODE, CAMERA_MODEL_POLICY_MODE}:
        return []
    observations = []
    observe_index = 0
    for event in trace_events:
        if event.get("tool") != "observe" or event.get("event") != "response":
            continue
        response = event.get("response")
        if not isinstance(response, dict):
            continue
        observe_index += 1
        observation_id = str(
            response.get("observation_id")
            or response.get("observation_label")
            or f"agibot_head_color_{observe_index:03d}"
        )
        observations.append(
            {
                "schema": "raw_fpv_observation_v1",
                "observation_id": observation_id,
                "source": "agibot_g2_policy_camera",
                "camera": response.get("policy_observation_camera")
                or response.get("would_capture_camera")
                or "head_color",
                "perception_mode": perception_mode,
                "status": response.get("status", ""),
                "ok": bool(response.get("ok")),
                "primitive_provenance": response.get(
                    "primitive_provenance",
                    BLOCKED_CAPABILITY_PROVENANCE,
                ),
                "image_artifacts": _raw_fpv_image_artifacts(response),
                "public_contract_note": (
                    "Agibot map-build records robot-local head_color observation "
                    "intent. Dry-run runs do not include live camera pixels."
                ),
            }
        )
    return observations


def _raw_fpv_image_artifacts(response: dict[str, Any]) -> dict[str, str]:
    artifact = str(response.get("camera_artifact") or "")
    if not artifact:
        return {}
    report_dir = str(response.get("agibot_sdk_report") or "")
    if not report_dir:
        return {"fpv": artifact}
    parent = Path(report_dir).parent
    return {"fpv": str(parent / artifact)}


def _camera_model_policy_evidence(
    trace_events: list[dict[str, Any]],
    *,
    perception_mode: str,
    visual_grounding_pipeline_id: str,
    raw_observations: list[dict[str, Any]],
    static_fixture_projection: dict[str, Any],
    run_dir: Path,
    visual_grounding_client: VisualGroundingClient | None,
) -> dict[str, Any]:
    if perception_mode != CAMERA_MODEL_POLICY_MODE:
        return {
            "schema": "camera_model_policy_v1",
            "enabled": False,
            "visual_grounding_pipeline_id": visual_grounding_pipeline_id,
            "camera_labeler": camera_labeler_from_visual_grounding_pipeline(
                visual_grounding_pipeline_id
            ),
            "event_count": 0,
            "candidate_count": 0,
            "visual_grounding_failure_count": 0,
            "private_truth_included": False,
        }
    events = [
        _camera_model_policy_event(
            raw,
            trace_events=trace_events,
            visual_grounding_pipeline_id=visual_grounding_pipeline_id,
            static_fixture_projection=static_fixture_projection,
            run_dir=run_dir,
            visual_grounding_client=visual_grounding_client,
        )
        for raw in raw_observations
    ]
    event_count = len(events)
    failure_count = sum(
        1
        for event in events
        if (event.get("visual_grounding_pipeline") or {}).get("status") != "ok"
    )
    return {
        "schema": "camera_model_policy_v1",
        "enabled": True,
        "event_count": event_count,
        "candidate_count": sum(int(event.get("candidate_count") or 0) for event in events),
        "visual_grounding_pipeline_id": visual_grounding_pipeline_id,
        "camera_labeler": camera_labeler_from_visual_grounding_pipeline(
            visual_grounding_pipeline_id
        ),
        "visual_grounding_pipeline_ids": [visual_grounding_pipeline_id],
        "visual_grounding_failure_count": failure_count,
        "model_provenance": EXTERNAL_VISUAL_GROUNDING_PROVENANCE,
        "private_truth_included": False,
        "duplicate_rate": _duplicate_rate_from_events(events),
        "events": events,
        "policy_note": (
            "Agibot camera-grounded-labels requests a camera labeler over robot-local "
            "head_color evidence when live camera pixels are available. Dry-run artifacts "
            "record explicit no-live-camera failure instead of fabricating labels."
        ),
    }


def _camera_model_policy_event(
    raw_observation: dict[str, Any],
    *,
    trace_events: list[dict[str, Any]],
    visual_grounding_pipeline_id: str,
    static_fixture_projection: dict[str, Any],
    run_dir: Path,
    visual_grounding_client: VisualGroundingClient | None,
) -> dict[str, Any]:
    if not raw_observation.get("ok"):
        return _failed_camera_model_policy_event(
            raw_observation,
            visual_grounding_pipeline_id=visual_grounding_pipeline_id,
            failure_reason=_observe_failure_reason(raw_observation, trace_events),
            capture_status=str(raw_observation.get("status") or "blocked"),
        )
    if visual_grounding_client is None:
        pipeline = pipeline_summary_from_response(
            visual_grounding_failure_response(
                pipeline_id=visual_grounding_pipeline_id,
                reason="missing_client",
                message=(
                    "Agibot camera-grounded-labels hardware validation requires an External "
                    "Visual Grounding Service client."
                ),
                latency_ms=0,
            )
        )
        return _camera_model_policy_event_from_pipeline(
            raw_observation,
            pipeline=pipeline,
            candidates=[],
        )

    request = visual_grounding_request(
        run_id="agibot_map_build",
        raw_observation=_visual_grounding_raw_observation(raw_observation),
        category_hints=list(VISUAL_GROUNDING_CATEGORY_HINTS),
        public_map_hints=_public_map_hints_for_visual_grounding_request(static_fixture_projection),
        pipeline_id=visual_grounding_pipeline_id,
        image=image_payload_for_raw_observation(raw_observation, base_dir=run_dir),
    )
    try:
        response = visual_grounding_client.request_candidates(request)
        client_config = getattr(visual_grounding_client, "config", None)
        auth_mode = str(getattr(client_config, "auth_mode", "none"))
        pipeline = pipeline_summary_from_response(response, auth_mode=auth_mode)
        candidates = list(response.get("candidates") or [])
    except VisualGroundingContractError as exc:
        pipeline = {
            "schema": VISUAL_GROUNDING_PIPELINE_SCHEMA,
            "pipeline_id": visual_grounding_pipeline_id,
            "status": "contract_error",
            "stages": [],
            "candidate_count": 0,
            "unresolved_count": 0,
            "duplicate_rate": 0.0,
            "failure_reason": "contract_error",
            "failure_message": str(exc),
            "auth_mode": "none",
        }
        candidates = []

    return _camera_model_policy_event_from_pipeline(
        raw_observation,
        pipeline=pipeline,
        candidates=candidates,
    )


def _failed_camera_model_policy_event(
    raw_observation: dict[str, Any],
    *,
    visual_grounding_pipeline_id: str,
    failure_reason: str,
    capture_status: str,
) -> dict[str, Any]:
    return {
        "observation_id": raw_observation.get("observation_id", ""),
        "room_id": "",
        "candidate_count": 0,
        "registered_observed_handles": [],
        "visual_grounding_pipeline": {
            "schema": VISUAL_GROUNDING_PIPELINE_SCHEMA,
            "pipeline_id": visual_grounding_pipeline_id,
            "status": "failed",
            "failure_reason": failure_reason,
            "stages": [
                {
                    "stage": "agibot_head_color_capture",
                    "producer_id": "agibot_g2_policy_camera",
                    "status": capture_status,
                },
                {
                    "stage": "external_visual_grounding_not_invoked",
                    "producer_id": visual_grounding_pipeline_id,
                    "status": "blocked",
                },
            ],
        },
    }


def _camera_model_policy_event_from_pipeline(
    raw_observation: dict[str, Any],
    *,
    pipeline: dict[str, Any],
    candidates: list[dict[str, Any]],
) -> dict[str, Any]:
    return {
        "observation_id": raw_observation.get("observation_id", ""),
        "room_id": "",
        "candidate_count": len(candidates),
        "registered_observed_handles": [],
        "visual_grounding_pipeline": pipeline,
    }


def _visual_grounding_raw_observation(raw_observation: dict[str, Any]) -> dict[str, Any]:
    result = dict(raw_observation)
    result.setdefault("waypoint_id", "")
    result.setdefault("room_id", "")
    result.setdefault("artifact_status", str(raw_observation.get("status") or "ok"))
    return result


def _public_map_hints_for_visual_grounding_request(
    static_fixture_projection: dict[str, Any],
) -> dict[str, Any]:
    rows = []
    for room in static_fixture_projection.get("rooms") or []:
        if not isinstance(room, dict):
            continue
        room_id = str(room.get("room_id") or "")
        for fixture in room.get("fixtures") or []:
            if not isinstance(fixture, dict):
                continue
            rows.append(
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
        "fixture_hints": rows,
        "private_truth_included": False,
    }


def _observe_failure_reason(
    raw_observation: dict[str, Any],
    trace_events: list[dict[str, Any]],
) -> str:
    observation_id = str(raw_observation.get("observation_id") or "")
    observe_failures = [
        event.get("response") or {}
        for event in trace_events
        if event.get("tool") == "observe"
        and event.get("event") == "response"
        and isinstance(event.get("response"), dict)
        and not (event.get("response") or {}).get("ok")
    ]
    for failure in observe_failures:
        failure_id = str(failure.get("observation_id") or failure.get("observation_label") or "")
        if observation_id and failure_id and failure_id != observation_id:
            continue
        return str(failure.get("failure_type") or "no_live_camera_pixels")
    return str(raw_observation.get("status") or "no_live_camera_pixels")


def _duplicate_rate_from_events(events: list[dict[str, Any]]) -> float:
    rates = [
        float((event.get("visual_grounding_pipeline") or {}).get("duplicate_rate") or 0.0)
        for event in events
    ]
    if not rates:
        return 0.0
    return max(rates)


def _dominant_provenance(trace_events: list[dict[str, Any]]) -> str:
    for event in trace_events:
        response = event.get("response")
        if not isinstance(response, dict):
            continue
        if response.get("primitive_provenance") == "agibot_gdk_normal_navi":
            return "agibot_gdk_normal_navi"
    for event in trace_events:
        response = event.get("response")
        if isinstance(response, dict) and response.get("primitive_provenance"):
            return str(response["primitive_provenance"])
    return BLOCKED_CAPABILITY_PROVENANCE


def _empty_score(sweep_rate: float) -> dict[str, Any]:
    return {
        "completion_status": "map_build_rehearsal",
        "cleanup_status": "map_build_rehearsal",
        "restored_count": 0,
        "total_targets": 0,
        "object_results": [],
        "mess_restoration_rate": 0.0,
        "sweep_coverage_rate": sweep_rate,
        "disturbance_count": 0,
        "semantic_acceptability": {
            "accepted_count": 0,
            "total_targets": 0,
            "acceptance_rate": 0.0,
        },
    }


def _subphase_reports(results: list[dict[str, Any]], run_dir: Path) -> list[dict[str, Any]]:
    reports = []
    for result in results:
        report_path = Path(str(result.get("report_path") or ""))
        reports.append(
            {
                "stage": result.get("stage", ""),
                "status": result.get("status", ""),
                "ok": result.get("ok", False),
                "report": _relpath(report_path, run_dir),
                "run_result": _relpath(report_path.with_name("run_result.json"), run_dir),
            }
        )
    return reports


def _runtime_timing(trace_events: list[dict[str, Any]]) -> dict[str, Any]:
    elapsed = float(trace_events[-1].get("wallclock_elapsed") or 0.0) if trace_events else 0.0
    return {
        "total_elapsed_s": elapsed,
        "tool_handler_s": 0.0,
        "robot_view_capture_s": 0.0,
        "between_tool_gap_s": 0.0,
        "tool_call_count": sum(1 for item in trace_events if item.get("event") == "request"),
    }


def _initial_locations(scenario: CleanupScenario) -> dict[str, str]:
    return {obj.object_id: obj.location_id for obj in scenario.objects}


def _relpath(path: Path, root: Path) -> str:
    try:
        return str(path.resolve().relative_to(root.resolve()))
    except ValueError:
        return str(path)


def _json_safe(value: Any) -> Any:
    return json.loads(json.dumps(value, default=str))


def _port_accepting(host: str, port: int, *, timeout_s: float = 0.2) -> bool:
    try:
        with socket.create_connection((host, port), timeout=timeout_s):
            return True
    except OSError:
        return False
