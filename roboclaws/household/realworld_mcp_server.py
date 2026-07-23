"""FastMCP bridge for the ADR-0003 MolmoSpaces cleanup contract."""

from __future__ import annotations

import json
import os
import socket
import threading
import time
from pathlib import Path
from typing import Any

from mcp.server.fastmcp import FastMCP
from mcp.server.fastmcp import Image as MCPImage

from roboclaws.core.json_sources import read_jsonl_objects
from roboclaws.household import agent_view as agent_view_module
from roboclaws.household.backend_contract import CleanupBackendSession
from roboclaws.household.realworld_contract import (
    CAMERA_MODEL_POLICY_MODE,
    DEFAULT_REALWORLD_TASK,
    RAW_FPV_ONLY_MODE,
    REALWORLD_CONTRACT,
    VISIBLE_OBJECT_DETECTIONS_MODE,
    RealWorldCleanupContract,
    raw_fpv_inline_candidate_instruction,
)
from roboclaws.household.realworld_mcp_backend import (
    agent_view_public_tool_names,
    dispatch_realworld_mcp_tool,
    register_realworld_mcp_tools,
    validate_realworld_mcp_tool_call,
)
from roboclaws.household.realworld_mcp_run_artifacts import (
    RealWorldMCPDoneArtifactInputs,
    finalize_realworld_mcp_done,
)
from roboclaws.household.realworld_run_artifacts import (
    write_runtime_metric_map_preview_artifact,
)
from roboclaws.household.report import (
    write_state_snapshot,
)
from roboclaws.household.scenario import build_cleanup_scenario
from roboclaws.household.semantic_timeline import (
    camera_offsets_from_raw_fpv_observation,
    has_complete_semantic_sequence,
    robot_view_capture_for_tool,
    semantic_substeps,
    successful_semantic_phases,
)
from roboclaws.household.task_intent import (
    household_runtime_intent,
    household_task_identity_from_contract,
    household_task_name,
)
from roboclaws.household.types import CleanupScenario
from roboclaws.household.visual_grounding import (
    SIM_VISUAL_GROUNDING_PIPELINE_ID,
    visual_grounding_client_from_env,
)
from roboclaws.household.visual_scan_guidance import visual_scan_metric_map_instruction
from roboclaws.launch.goals import (
    GoalContract,
    goal_contract_from_file,
    goal_contract_from_json,
)
from roboclaws.maps.bundle import copy_nav2_map_bundle_snapshot
from roboclaws.operator_console.interactions import (
    check_operator_messages_for_mcp,
    pending_operator_message_hint,
)

__all__ = ["MCP_SERVER_NAME", "RealWorldMolmoCleanupMCPServer", "make_molmo_realworld_cleanup_mcp"]

DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 18788
STARTUP_TIMEOUT_S = 2.0
MCP_SERVER_NAME = "molmo_cleanup_realworld"
ROBOT_VIEW_CAPTURE_POLICY_FULL = "full"
ROBOT_VIEW_CAPTURE_POLICY_ACTION_TIMELINE = "action_timeline"
ROBOT_VIEW_CAPTURE_POLICIES = frozenset(
    {ROBOT_VIEW_CAPTURE_POLICY_FULL, ROBOT_VIEW_CAPTURE_POLICY_ACTION_TIMELINE}
)
AGENT_POLICIES = {
    "realworld_contract_smoke_agent",
    "codex_agent",
    "claude_code_agent",
    "openclaw_agent",
}
REPORT_RERUN_COMMAND_ENV = "ROBOCLAWS_REPORT_RERUN_COMMAND"


def make_molmo_realworld_cleanup_mcp(
    *,
    run_dir: Path,
    scenario: CleanupScenario | None = None,
    base_contract: CleanupBackendSession | None = None,
    contract: RealWorldCleanupContract | None = None,
    host: str = DEFAULT_HOST,
    port: int = DEFAULT_PORT,
    policy: str = "realworld_contract_smoke_agent",
    agent_driven: bool | None = None,
    task_surface: str = "household-world",
    task_intent: str = "cleanup",
    task_prompt: str = DEFAULT_REALWORLD_TASK,
    static_fixture_projection_mode: str = "room_only",
    perception_mode: str = VISIBLE_OBJECT_DETECTIONS_MODE,
    record_robot_views: bool = False,
    evidence_lane: str | None = None,
    planner_proof_run_result: Path | None = None,
    map_bundle_dir: str | Path | None = None,
    runtime_map_prior: dict[str, Any] | None = None,
    runtime_map_prior_source: str = "",
    visual_grounding: str = SIM_VISUAL_GROUNDING_PIPELINE_ID,
    visual_grounding_base_url: str | None = None,
    visual_grounding_timeout_s: float | None = None,
    goal_contract: GoalContract | None = None,
    operator_messages_path: str | Path | None = None,
    agent_sdk_camera_grounded_composite_tools: bool = False,
    robot_view_capture_policy: str = ROBOT_VIEW_CAPTURE_POLICY_FULL,
    rerun_command: str | None = None,
    required_capability_profiles: tuple[str, ...] | None = None,
) -> "RealWorldMolmoCleanupMCPServer":
    return RealWorldMolmoCleanupMCPServer(
        run_dir=run_dir,
        scenario=scenario,
        base_contract=base_contract,
        contract=contract,
        host=host,
        port=port,
        policy=policy,
        agent_driven=agent_driven,
        task_surface=task_surface,
        task_intent=task_intent,
        task_prompt=task_prompt,
        static_fixture_projection_mode=static_fixture_projection_mode,
        perception_mode=perception_mode,
        record_robot_views=record_robot_views,
        evidence_lane=evidence_lane,
        planner_proof_run_result=planner_proof_run_result,
        map_bundle_dir=map_bundle_dir,
        runtime_map_prior=runtime_map_prior,
        runtime_map_prior_source=runtime_map_prior_source,
        visual_grounding=visual_grounding,
        visual_grounding_base_url=visual_grounding_base_url,
        visual_grounding_timeout_s=visual_grounding_timeout_s,
        goal_contract=goal_contract,
        operator_messages_path=operator_messages_path,
        agent_sdk_camera_grounded_composite_tools=agent_sdk_camera_grounded_composite_tools,
        robot_view_capture_policy=robot_view_capture_policy,
        rerun_command=rerun_command,
        required_capability_profiles=required_capability_profiles,
    )


class RealWorldMolmoCleanupMCPServer:
    """FastMCP server wrapping ``RealWorldCleanupContract`` for agent dogfood."""

    def __init__(
        self,
        *,
        run_dir: Path,
        scenario: CleanupScenario | None = None,
        base_contract: CleanupBackendSession | None = None,
        contract: RealWorldCleanupContract | None = None,
        host: str = DEFAULT_HOST,
        port: int = DEFAULT_PORT,
        policy: str = "realworld_contract_smoke_agent",
        agent_driven: bool | None = None,
        task_surface: str = "household-world",
        task_intent: str = "cleanup",
        task_prompt: str = DEFAULT_REALWORLD_TASK,
        static_fixture_projection_mode: str = "room_only",
        perception_mode: str = VISIBLE_OBJECT_DETECTIONS_MODE,
        record_robot_views: bool = False,
        evidence_lane: str | None = None,
        planner_proof_run_result: Path | None = None,
        map_bundle_dir: str | Path | None = None,
        runtime_map_prior: dict[str, Any] | None = None,
        runtime_map_prior_source: str = "",
        visual_grounding: str = SIM_VISUAL_GROUNDING_PIPELINE_ID,
        visual_grounding_base_url: str | None = None,
        visual_grounding_timeout_s: float | None = None,
        goal_contract: GoalContract | None = None,
        operator_messages_path: str | Path | None = None,
        agent_sdk_camera_grounded_composite_tools: bool = False,
        robot_view_capture_policy: str = ROBOT_VIEW_CAPTURE_POLICY_FULL,
        rerun_command: str | None = None,
        required_capability_profiles: tuple[str, ...] | None = None,
    ) -> None:
        self.run_dir = Path(run_dir)
        self.run_dir.mkdir(parents=True, exist_ok=True)
        self.host = host
        self.port = int(port)
        self.policy = policy
        self.task_surface = task_surface
        self.agent_driven = (
            policy in AGENT_POLICIES or policy.endswith("_agent")
            if agent_driven is None
            else agent_driven
        )
        self.policy_uses_private_truth = False
        self.goal_contract = goal_contract or _goal_contract_from_env()
        self.required_capability_profiles = tuple(
            required_capability_profiles
            if required_capability_profiles is not None
            else (
                self.goal_contract.required_capabilities
                if self.goal_contract is not None
                else _required_capability_profiles_from_env()
            )
        )
        if not self.required_capability_profiles:
            raise ValueError(
                "required capability profiles must be resolved before starting household MCP"
            )
        self.task_intent = household_runtime_intent(self.goal_contract, task_intent)
        self.task_name = household_task_name(surface=self.task_surface, intent=self.task_intent)
        self.map_bundle_dir = Path(map_bundle_dir) if map_bundle_dir is not None else None
        self.runtime_map_prior_source = runtime_map_prior_source
        contract = _build_realworld_mcp_contract(
            contract=contract,
            scenario=scenario,
            base_contract=base_contract,
            task_prompt=task_prompt,
            static_fixture_projection_mode=static_fixture_projection_mode,
            perception_mode=perception_mode,
            map_bundle_dir=self.map_bundle_dir,
            runtime_map_prior=runtime_map_prior,
            evidence_lane=evidence_lane,
            task_intent=self.task_intent,
            visual_grounding=visual_grounding,
            visual_grounding_base_url=visual_grounding_base_url,
            visual_grounding_timeout_s=visual_grounding_timeout_s,
            run_dir=self.run_dir,
        )
        self.contract = contract
        self.base_contract = contract.contract
        backend_name = getattr(contract, "backend_name", None)
        self.backend_name = str(backend_name()) if callable(backend_name) else ""
        self.scenario = contract.scenario
        self.task_prompt = task_prompt
        self.task_intent, self.task_name = household_task_identity_from_contract(
            contract,
            surface=self.task_surface,
            fallback_intent=self.task_intent,
        )
        self.static_fixture_projection_mode = static_fixture_projection_mode
        self.perception_mode = contract.perception_mode
        self.record_robot_views = bool(record_robot_views)
        self.evidence_lane = evidence_lane
        self.planner_proof_run_result = planner_proof_run_result
        self.operator_messages_path = (
            Path(operator_messages_path) if operator_messages_path is not None else None
        )
        self.agent_sdk_camera_grounded_composite_tools = bool(
            agent_sdk_camera_grounded_composite_tools
        )
        self.robot_view_capture_policy = _normalize_robot_view_capture_policy(
            robot_view_capture_policy
        )
        self.rerun_command = (
            str(rerun_command or "").strip() or os.environ.get(REPORT_RERUN_COMMAND_ENV, "").strip()
        )
        if self.record_robot_views and not self.base_contract.supports_robot_views():
            raise ValueError("record_robot_views requires a backend with write_robot_views")

        self._init_runtime_state()
        self._init_public_artifacts()
        self._init_fastmcp(host)
        self._write_initialized_event()

    def _init_runtime_state(self) -> None:
        self.trace_path = self.run_dir / "trace.jsonl"
        self.run_result_path = self.run_dir / "run_result.json"
        self.done_event = threading.Event()
        self.robot_view_steps: list[dict[str, Any]] = []
        self._robot_view_index = 0
        self._started_at = time.time()
        self._trace_fp = self.trace_path.open("a", encoding="utf-8", buffering=1)
        self._trace_lock = threading.Lock()
        self._tool_event_counts: dict[str, int] = {}
        self._server_thread: threading.Thread | None = None
        self._closed = False
        self._done_result: dict[str, Any] | None = None

    def _init_public_artifacts(self) -> None:
        self._before_snapshot = self._write_snapshot(
            "before.png", title="Before real-world cleanup"
        )
        self._record_robot_view("before", label_suffix="before")
        if self.map_bundle_dir is None:
            raise ValueError("map_bundle_dir is required to publish live Base Metric Map snapshot")
        copy_nav2_map_bundle_snapshot(source_bundle_dir=self.map_bundle_dir, run_dir=self.run_dir)
        self._write_live_public_artifacts(trigger="server_initialized")

    def _init_fastmcp(self, host: str) -> None:
        self._mcp = FastMCP("roboclaws", host=host, port=self.port)
        register_realworld_mcp_tools(self)

    def _write_initialized_event(self) -> None:
        self.write_runtime_event(
            "molmo_realworld_cleanup_mcp_initialized",
            contract=REALWORLD_CONTRACT,
            policy=self.policy,
            agent_driven=self.agent_driven,
            task_intent=self.task_intent,
            goal_contract=self.goal_contract.to_payload() if self.goal_contract is not None else {},
            perception_mode=self.perception_mode,
            evidence_lane=self.evidence_lane,
            visual_grounding_pipeline_id=self.contract.visual_grounding_pipeline_id,
            agent_sdk_camera_grounded_composite_tools=(
                self.agent_sdk_camera_grounded_composite_tools
            ),
            robot_view_capture_policy=self.robot_view_capture_policy,
        )

    def call_tool(self, name: str, **kwargs: Any) -> dict[str, Any]:
        validate_realworld_mcp_tool_call(self, name)
        request = _json_safe(kwargs)
        self._write_tool_request(name, request)
        try:
            response = dispatch_realworld_mcp_tool(self, name, kwargs)
        except Exception as exc:
            response = {
                "ok": False,
                "tool": name,
                "status": "error",
                "error_reason": "exception",
                "error": str(exc),
            }
        response = self._augment_response(name, request, response)
        if name != "check_operator_messages":
            response = self._attach_operator_message_hint(response)
        response = self._attach_raw_fpv_artifact_if_needed(name, response)
        self._write_tool_response(name, response)
        if name == "done" and response.get("ok"):
            return self._finalize_done(str(kwargs.get("reason", "")), response)
        self._record_tool_robot_view(name, request, response)
        if response.get("ok") and name != "done":
            self._write_live_public_artifacts(trigger=name)
        return response

    def check_operator_messages(self, max_messages: int = 10) -> dict[str, Any]:
        path = self.operator_messages_path
        run_dir = path.parent if path is not None else self.run_dir
        return check_operator_messages_for_mcp(run_dir, max_messages=max(1, max_messages))

    def observe_camera_grounded_candidates(self) -> dict[str, Any]:
        if self.perception_mode != CAMERA_MODEL_POLICY_MODE:
            return {
                "ok": False,
                "tool": "observe_camera_grounded_candidates",
                "status": "error",
                "error_reason": "unsupported_perception_mode",
                "perception_mode": self.perception_mode,
                "supported_perception_mode": CAMERA_MODEL_POLICY_MODE,
            }
        observation = self.call_tool("observe")
        if not observation.get("ok"):
            return {
                "ok": False,
                "tool": "observe_camera_grounded_candidates",
                "status": "error",
                "error_reason": "observe_failed",
                "observation": observation,
                "private_target_truth_included": False,
            }
        raw = observation.get("raw_fpv_observation")
        raw = raw if isinstance(raw, dict) else {}
        observation_id = str(raw.get("observation_id") or "")
        if not observation_id:
            return {
                "ok": False,
                "tool": "observe_camera_grounded_candidates",
                "status": "error",
                "error_reason": "missing_raw_fpv_observation",
                "observation": observation,
                "private_target_truth_included": False,
            }
        declaration = self.call_tool("declare_visual_candidates", observation_id=observation_id)
        return {
            "ok": bool(declaration.get("ok")),
            "tool": "observe_camera_grounded_candidates",
            "status": declaration.get("status", "ok" if declaration.get("ok") else "error"),
            "contract": REALWORLD_CONTRACT,
            "perception_mode": self.perception_mode,
            "observation_id": observation_id,
            "waypoint_id": observation.get("waypoint_id", raw.get("waypoint_id", "")),
            "room_id": observation.get("current_room_id", raw.get("room_id", "")),
            "observation": observation,
            "declaration": declaration,
            "candidate_count": declaration.get("candidate_count", 0),
            "registered_observed_handles": list(
                declaration.get("registered_observed_handles") or []
            ),
            "camera_model_candidates": list(declaration.get("camera_model_candidates") or []),
            "model_declared_observations": list(
                declaration.get("model_declared_observations") or []
            ),
            "visual_grounding_pipeline": declaration.get("visual_grounding_pipeline") or {},
            "private_target_truth_included": False,
            "trace_review_note": (
                "Composite shortcut for private Agent SDK Candidate O. It preserves the "
                "underlying observe and declare_visual_candidates trace events."
            ),
            "instruction": declaration.get("instruction", ""),
        }

    def done_readiness_evidence(self) -> dict[str, Any]:
        trace_events = self._read_trace_events()
        substeps = semantic_substeps(trace_events, self.contract.public_receptacles_by_id())
        complete_handles = [
            handle
            for handle in _complete_semantic_substep_handles(substeps)
            if bool(
                (self.contract._detections_by_handle.get(handle) or {}).get("cleanup_recommended")
            )
        ]
        return {
            "schema": "public_semantic_cleanup_evidence_v1",
            "complete_semantic_substep_objects": len(complete_handles),
            "complete_semantic_substep_object_ids": complete_handles,
            "semantic_substep_count": len(substeps),
            "evidence_source": "public_mcp_trace_semantic_substeps",
        }

    def _agent_view_payload(self) -> dict[str, Any]:
        agent_view = self.contract.agent_view_payload()
        return agent_view_module.with_public_tool_names(
            agent_view,
            agent_view_public_tool_names(
                self,
                agent_view_module.public_tool_names(agent_view),
            ),
        )

    def _write_live_public_artifacts(self, *, trigger: str) -> None:
        """Refresh public map artifacts while a live MCP run is still in progress."""

        try:
            agent_view = self._agent_view_payload()
            runtime_metric_map = agent_view_module.runtime_metric_map(agent_view)
            _write_json(self.run_dir / "agent_view.json", agent_view)
            _write_json(self.run_dir / "runtime_metric_map.json", runtime_metric_map)
            write_runtime_metric_map_preview_artifact(
                output_dir=self.run_dir,
                runtime_metric_map=runtime_metric_map,
            )
        except Exception as exc:
            self.write_runtime_event(
                "live_public_artifact_write_failed",
                trigger=trigger,
                error=str(exc),
            )

    def _augment_response(
        self,
        tool: str,
        request: dict[str, Any],
        response: dict[str, Any],
    ) -> dict[str, Any]:
        augmented = dict(response)
        if tool == "metric_map":
            augmented["instruction"] = (
                "inspection_waypoints are static map/fixture coverage candidates, "
                f"not mess hints. Prefer navigate_to_waypoint -> observe. "
                f"{visual_scan_metric_map_instruction()}"
            )
        if tool == "observe" and self.perception_mode == CAMERA_MODEL_POLICY_MODE:
            raw = augmented.get("raw_fpv_observation") or {}
            augmented["instruction"] = (
                "Call declare_visual_candidates with observation_id="
                f"{raw.get('observation_id', '')} before choosing cleanup candidates. "
                "For camera-grounded-labels, pass only observation_id and omit "
                "candidates so the configured camera labeler produces labels. Service URLs, "
                "credentials, and image paths are server-side details."
            )
        if tool == "observe" and self.perception_mode == RAW_FPV_ONLY_MODE:
            raw = augmented.get("raw_fpv_observation") or {}
            augmented["instruction"] = raw_fpv_inline_candidate_instruction(
                str(raw.get("observation_id") or "")
            )
        if tool == "declare_visual_candidates" and augmented.get("ok"):
            augmented = _compact_declare_visual_candidates_response(augmented)
            augmented["instruction"] = (
                "Use camera_model_candidates with cleanup_recommended=true as the actionable "
                "worklist only when candidate_state is navigation_authorized. For each "
                "authorized candidate, call navigate_to_object, pick, navigate_to_receptacle, "
                "then the recommended placement tool."
            )
        if tool in {"place", "place_inside", "close_receptacle"} and augmented.get("ok"):
            augmented["instruction"] = (
                "After placing and closing if needed, call observe once in the current "
                "room/fixture area before choosing the next object or waypoint."
            )
        return augmented

    def _attach_operator_message_hint(self, response: dict[str, Any]) -> dict[str, Any]:
        path = self.operator_messages_path
        run_dir = path.parent if path is not None else self.run_dir
        hint = pending_operator_message_hint(run_dir)
        if not hint:
            return response
        augmented = dict(response)
        augmented.update(hint)
        return augmented

    def _finalize_done(self, reason: str, done_response: dict[str, Any]) -> dict[str, Any]:
        if self._done_result is not None:
            return self._done_result

        after_snapshot = self._write_snapshot("after.png", title="After real-world cleanup")
        self._record_robot_view("after", label_suffix="after")
        trace_events = self._read_trace_events()
        finalized = finalize_realworld_mcp_done(
            RealWorldMCPDoneArtifactInputs(
                run_dir=self.run_dir,
                trace_path=self.trace_path,
                run_result_path=self.run_result_path,
                base_contract=self.base_contract,
                contract=self.contract,
                scenario=self.scenario,
                task_name=self.task_name,
                task_prompt=self.task_prompt,
                task_intent=self.task_intent,
                goal_contract=self.goal_contract,
                policy=self.policy,
                agent_driven=self.agent_driven,
                policy_uses_private_truth=self.policy_uses_private_truth,
                static_fixture_projection_mode=self.static_fixture_projection_mode,
                perception_mode=self.perception_mode,
                map_bundle_dir=self.map_bundle_dir,
                runtime_map_prior_source=self.runtime_map_prior_source,
                evidence_lane=self.evidence_lane,
                record_robot_views=self.record_robot_views,
                planner_proof_run_result=self.planner_proof_run_result,
                robot_view_steps=self.robot_view_steps,
                robot_view_capture_policy=self.robot_view_capture_policy,
                before_snapshot=self._before_snapshot,
                after_snapshot=after_snapshot,
                trace_events=trace_events,
                agent_view=self._agent_view_payload(),
                done_response=done_response,
                reason=reason,
                tool_event_counts=dict(self._tool_event_counts),
                rerun_command=self.rerun_command,
                mcp_server_name=MCP_SERVER_NAME,
            )
        )
        self._done_result = {
            "ok": True,
            "tool": "done",
            "status": "ok",
            "intent_status": finalized.intent_status,
            "goal_status": finalized.intent_status,
            "cleanup_status": done_response["cleanup_status"],
            "score": done_response["score"],
            "run_result": str(self.run_result_path),
            "report": str(finalized.report_path),
            "contract": REALWORLD_CONTRACT,
            "agent_driven": self.agent_driven,
        }
        self.done_event.set()
        self.write_runtime_event(
            "molmo_realworld_cleanup_mcp_done",
            cleanup_status=done_response["cleanup_status"],
            restored_count=done_response["score"]["restored_count"],
            total_targets=done_response["score"]["total_targets"],
        )
        return self._done_result

    def _attach_raw_fpv_artifact_if_needed(
        self,
        tool: str,
        response: dict[str, Any],
    ) -> dict[str, Any]:
        if (
            tool != "observe"
            or self.perception_mode not in {RAW_FPV_ONLY_MODE, CAMERA_MODEL_POLICY_MODE}
            or not response.get("ok")
            or not self.record_robot_views
        ):
            return response
        raw = response.get("raw_fpv_observation")
        if not isinstance(raw, dict):
            return response
        observation_id = str(raw.get("observation_id", ""))
        if not observation_id:
            return response
        step = self._record_robot_view(
            f"observe {observation_id}",
            label_suffix=observation_id,
            **camera_offsets_from_raw_fpv_observation(raw),
        )
        if step is None:
            return response
        attached = self.contract.attach_raw_fpv_observation_artifact(
            observation_id,
            views=step.get("views") or {},
            robot_view_label=str(step.get("label", "")),
            camera_control_contract=step.get("camera_control_contract")
            if isinstance(step.get("camera_control_contract"), dict)
            else None,
        )
        if attached is None:
            return response
        updated = dict(response)
        updated["raw_fpv_observation"] = attached
        return updated

    def _mcp_observe_response(self) -> dict[str, Any] | list[Any]:
        response = self.call_tool("observe")
        if (
            self.perception_mode != RAW_FPV_ONLY_MODE
            or not response.get("ok")
            or not self.record_robot_views
        ):
            return response
        raw = response.get("raw_fpv_observation") or {}
        image_artifacts = raw.get("image_artifacts") or {}
        fpv_path = image_artifacts.get("fpv") or raw.get("fpv_image")
        if not fpv_path:
            return response
        resolved = Path(str(fpv_path))
        if not resolved.is_absolute():
            resolved = self.run_dir / resolved
        if not resolved.is_file():
            return response
        state_text = json.dumps(
            _compact_raw_fpv_mcp_observe_state(
                response,
                cleanup_worklist=self.contract.cleanup_worklist_payload(),
            ),
            sort_keys=True,
        )
        return [state_text, MCPImage(data=resolved.read_bytes(), format="png")]

    def write_runtime_event(self, event: str, **data: Any) -> None:
        self._write_trace(tool="<runtime>", event=event, **data)

    def run_in_thread(self) -> threading.Thread:
        if self._server_thread is not None and self._server_thread.is_alive():
            return self._server_thread
        thread = threading.Thread(
            target=self._mcp.run,
            kwargs={"transport": "streamable-http"},
            name=f"household-world-mcp-{self.port}",
            daemon=True,
        )
        thread.start()
        self._server_thread = thread
        if self.port == 0:
            return thread

        probe_host = _startup_probe_host(self.host)
        deadline = time.monotonic() + STARTUP_TIMEOUT_S
        while time.monotonic() < deadline:
            if not thread.is_alive():
                address = f"{self.host}:{self.port}"
                raise RuntimeError(
                    f"Molmo real-world cleanup MCP server failed to start on {address}"
                )
            if _port_accepting(probe_host, self.port):
                return thread
            time.sleep(0.05)
        raise RuntimeError(
            f"Molmo real-world cleanup MCP server did not become ready on {self.host}:{self.port}"
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
        self.base_contract.close()
        with self._trace_lock:
            self._closed = True
            try:
                self._trace_fp.close()
            except Exception:
                pass
        if self._server_thread is not None:
            self._server_thread.join(timeout=0.5)

    def _write_snapshot(self, filename: str, *, title: str) -> Path:
        output_path = self.run_dir / filename
        if self.base_contract.supports_visual_snapshots():
            try:
                visual_snapshot = self.base_contract.write_visual_snapshot(output_path, title=title)
                if visual_snapshot is not None:
                    return visual_snapshot
            except Exception as exc:
                self.write_runtime_event(
                    "snapshot_capture_failed",
                    filename=filename,
                    error=str(exc),
                    fallback="state_snapshot",
                )
        return write_state_snapshot(
            self.scenario,
            self.base_contract.object_locations(),
            output_path,
            title=title,
        )

    def _record_tool_robot_view(
        self,
        tool: str,
        request: dict[str, Any],
        response: dict[str, Any],
    ) -> None:
        if not self.record_robot_views or not response.get("ok"):
            return
        if not self._should_record_tool_robot_view(tool):
            self.write_runtime_event(
                "robot_view_capture_skipped",
                skipped_tool=tool,
                policy=self.robot_view_capture_policy,
                reason="report_only_observation",
            )
            return
        capture = robot_view_capture_for_tool(
            tool,
            request,
            response,
            object_id_transform=lambda handle: (
                self.contract._internal_object_id(handle) if handle is not None else None
            ),
        )
        if capture is None:
            return
        self._record_robot_view(**capture)

    def _should_record_tool_robot_view(self, tool: str) -> bool:
        if self.robot_view_capture_policy == ROBOT_VIEW_CAPTURE_POLICY_FULL:
            return True
        if self.robot_view_capture_policy == ROBOT_VIEW_CAPTURE_POLICY_ACTION_TIMELINE:
            return tool not in {"observe", "scene_objects"}
        raise ValueError(
            f"unsupported robot_view_capture_policy '{self.robot_view_capture_policy}'"
        )

    def _record_robot_view(
        self,
        action: str,
        *,
        label_suffix: str,
        focus_object_id: str | None = None,
        focus_receptacle_id: str | None = None,
        semantic_phase: str | None = None,
        action_evidence: dict[str, Any] | None = None,
        camera_yaw_offset_deg: float = 0.0,
        camera_pitch_offset_deg: float = 0.0,
    ) -> dict[str, Any] | None:
        if not self.record_robot_views:
            return None
        if not self.base_contract.supports_robot_views():
            raise RuntimeError("robot view capture requires backend.write_robot_views")
        previous_count = len(self.robot_view_steps)
        capture_started = time.monotonic()
        try:
            self._robot_view_index = self.base_contract.record_robot_view_step(
                steps=self.robot_view_steps,
                output_dir=self.run_dir,
                index=self._robot_view_index,
                action=action,
                label_suffix=label_suffix,
                focus_object_id=focus_object_id,
                focus_receptacle_id=self.contract.internal_fixture_id_for_public_reference(
                    focus_receptacle_id
                ),
                semantic_phase=semantic_phase,
                action_evidence=action_evidence,
                camera_yaw_offset_deg=camera_yaw_offset_deg,
                camera_pitch_offset_deg=camera_pitch_offset_deg,
            )
        except Exception as exc:
            self.write_runtime_event(
                "robot_view_capture_failed",
                action=action,
                label_suffix=label_suffix,
                elapsed_s=round(time.monotonic() - capture_started, 6),
                error=str(exc),
            )
            return None
        if len(self.robot_view_steps) <= previous_count:
            return None
        capture_elapsed_s = round(time.monotonic() - capture_started, 6)
        step = self.robot_view_steps[-1]
        step["capture_elapsed_s"] = capture_elapsed_s
        self.write_runtime_event(
            "robot_view_capture",
            action=action,
            label=step.get("label", ""),
            elapsed_s=capture_elapsed_s,
        )
        return step

    def _write_tool_request(self, tool: str, request: dict[str, Any]) -> None:
        self._tool_event_counts[f"{tool}:request"] = (
            self._tool_event_counts.get(f"{tool}:request", 0) + 1
        )
        self._write_trace(tool=tool, event="request", request=request)

    def _write_tool_response(self, tool: str, response: dict[str, Any]) -> None:
        self._tool_event_counts[f"{tool}:response"] = (
            self._tool_event_counts.get(f"{tool}:response", 0) + 1
        )
        trace_response = response
        if tool == "observe" and self.perception_mode == RAW_FPV_ONLY_MODE:
            trace_response = dict(response)
            trace_response["agent_facing_compact_state"] = _compact_raw_fpv_mcp_observe_state(
                response,
                cleanup_worklist=self.contract.cleanup_worklist_payload(),
            )
        self._write_trace(tool=tool, event="response", response=trace_response)

    def _write_trace(self, *, tool: str, event: str, **payload: Any) -> None:
        trace_event = {
            "ts": time.time(),
            "wallclock_elapsed": round(time.time() - self._started_at, 6),
            "tool": tool,
            "event": event,
            **_json_safe(payload),
        }
        line = json.dumps(trace_event, sort_keys=True)
        with self._trace_lock:
            if self._closed:
                return
            self._trace_fp.write(line + "\n")
            self._trace_fp.flush()

    def _read_trace_events(self) -> list[dict[str, Any]]:
        with self._trace_lock:
            self._trace_fp.flush()
        return read_jsonl_objects(self.trace_path, label="Molmo real-world MCP trace")


def _compact_declare_visual_candidates_response(response: dict[str, Any]) -> dict[str, Any]:
    evidence = response.get("model_declared_observation_evidence") or {}
    declarations = list(response.get("model_declared_observations") or [])
    candidates = list(response.get("camera_model_candidates") or [])
    pipeline = evidence.get("visual_grounding_pipeline") or {}
    if not pipeline:
        for item in declarations:
            candidate_pipeline = item.get("visual_grounding_pipeline")
            if isinstance(candidate_pipeline, dict) and candidate_pipeline:
                pipeline = candidate_pipeline
                break

    return {
        "ok": response.get("ok", True),
        "tool": response.get("tool", "declare_visual_candidates"),
        "status": response.get("status", "ok"),
        "contract": response.get("contract", REALWORLD_CONTRACT),
        "observation_id": evidence.get("observation_id", ""),
        "waypoint_id": evidence.get("waypoint_id", ""),
        "room_id": evidence.get("room_id", ""),
        "producer_type": evidence.get("producer_type", ""),
        "producer_id": evidence.get("producer_id", ""),
        "candidate_count": evidence.get("candidate_count", len(declarations)),
        "registered_observed_handles": list(evidence.get("registered_observed_handles") or []),
        "visual_grounding_pipeline": _compact_visual_grounding_pipeline(pipeline),
        "model_declared_observations": [
            _compact_model_declared_observation(item) for item in declarations
        ],
        "camera_model_candidates": [_compact_camera_model_candidate(item) for item in candidates],
        "visible_object_detections": [],
        "private_target_truth_included": False,
    }


def _complete_semantic_substep_handles(substeps: list[dict[str, Any]]) -> list[str]:
    handles = []
    for item in substeps:
        phases = successful_semantic_phases(item.get("steps", []))
        if has_complete_semantic_sequence(phases):
            handles.append(str(item.get("object_id") or ""))
    return [handle for handle in handles if handle]


def _build_realworld_mcp_contract(
    *,
    contract: RealWorldCleanupContract | None,
    scenario: CleanupScenario | None,
    base_contract: CleanupBackendSession | None,
    task_prompt: str,
    static_fixture_projection_mode: str,
    perception_mode: str,
    map_bundle_dir: Path | None,
    runtime_map_prior: dict[str, Any] | None,
    evidence_lane: str | None,
    task_intent: str,
    visual_grounding: str,
    visual_grounding_base_url: str | None,
    visual_grounding_timeout_s: float | None,
    run_dir: Path,
) -> RealWorldCleanupContract:
    if contract is not None:
        return contract

    scenario = scenario or build_cleanup_scenario()
    base_contract = base_contract or CleanupBackendSession(scenario)
    acceptance_config = _public_acceptance_config_from_backend(base_contract)
    acceptance_config["task_intent"] = task_intent
    return RealWorldCleanupContract(
        base_contract,
        task_prompt=task_prompt,
        static_fixture_projection_mode=static_fixture_projection_mode,
        perception_mode=perception_mode,
        map_bundle_dir=map_bundle_dir,
        runtime_map_prior=runtime_map_prior,
        evidence_lane=evidence_lane,
        public_acceptance_config=acceptance_config,
        visual_grounding_client=visual_grounding_client_from_env(
            visual_grounding,
            base_url=visual_grounding_base_url,
            timeout_s=visual_grounding_timeout_s,
        ),
        visual_grounding_pipeline_id=visual_grounding,
        visual_grounding_artifact_base_dir=run_dir,
        visual_grounding_run_id=f"seed-{scenario.seed}",
    )


def _compact_visual_grounding_pipeline(pipeline: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(pipeline, dict):
        return {}
    compact = _select_keys(
        pipeline,
        (
            "schema",
            "pipeline_id",
            "status",
            "candidate_count",
            "unresolved_count",
            "duplicate_rate",
            "failure_reason",
            "failure_message",
            "auth_mode",
        ),
    )
    compact["stages"] = [
        _select_keys(
            stage,
            ("stage", "status", "producer_id", "model_id", "latency_ms", "version"),
        )
        for stage in pipeline.get("stages") or []
        if isinstance(stage, dict)
    ]
    return compact


def _compact_model_declared_observation(item: dict[str, Any]) -> dict[str, Any]:
    compact = _select_keys(
        item,
        (
            "declaration_id",
            "object_id",
            "source_observation_id",
            "waypoint_id",
            "room_id",
            "category",
            "target_fixture_id",
            "target_fixture_category",
            "source_fixture_id",
            "evidence_note",
            "image_region",
            "confidence",
            "producer_type",
            "producer_id",
            "grounding_status",
            "grounding_confidence",
            "grounding_basis",
            "recovery_hint",
            "actionability_status",
            "visual_grounding_evidence",
            "visual_grounding_destination_hint",
            "image_dimensions",
            "visual_grounding_overlay",
        ),
    )
    target_plausibility = item.get("target_plausibility")
    if isinstance(target_plausibility, dict):
        compact["target_plausibility"] = _select_keys(
            target_plausibility,
            ("status", "basis", "expected_fixture_id"),
        )
    return compact


def _compact_camera_model_candidate(item: dict[str, Any]) -> dict[str, Any]:
    compact = _select_keys(
        item,
        (
            "object_id",
            "category",
            "name",
            "current_room_id",
            "visibility_confidence",
            "image_bbox",
            "perception_source",
            "producer_type",
            "producer_id",
            "source_observation_id",
            "candidate_source",
            "candidate_fixture_id",
            "candidate_fixture_category",
            "cleanup_recommended",
            "recommended_tool",
            "model_declared_observation_id",
            "image_region",
            "evidence_note",
            "grounding_status",
            "grounding_confidence",
            "grounding_basis",
            "actionability_status",
            "visual_grounding_evidence",
        ),
    )
    support_estimate = item.get("support_estimate")
    if isinstance(support_estimate, dict):
        compact["support_estimate"] = _select_keys(
            support_estimate,
            ("fixture_id", "relation", "confidence", "source", "perception_source"),
        )
    return compact


def _compact_raw_fpv_mcp_observe_state(
    response: dict[str, Any],
    *,
    cleanup_worklist: dict[str, Any] | None = None,
) -> dict[str, Any]:
    raw = response.get("raw_fpv_observation") if isinstance(response, dict) else {}
    raw = raw if isinstance(raw, dict) else {}
    return {
        "schema": "raw_fpv_mcp_observe_state_v1",
        "ok": response.get("ok"),
        "tool": response.get("tool"),
        "status": response.get("status"),
        "contract": response.get("contract"),
        "perception_mode": response.get("perception_mode"),
        "waypoint_id": response.get("waypoint_id") or raw.get("waypoint_id"),
        "current_room_id": response.get("current_room_id") or raw.get("room_id"),
        "held_object_id": response.get("held_object_id") or raw.get("held_object_id"),
        "visible_object_detections": response.get("visible_object_detections") or [],
        "raw_fpv_observation": _compact_raw_fpv_observation(raw),
        "cleanup_worklist_summary": _compact_cleanup_worklist_summary(cleanup_worklist),
        "instruction": response.get("instruction"),
    }


def _compact_raw_fpv_observation(raw: dict[str, Any]) -> dict[str, Any]:
    return {
        "observation_id": raw.get("observation_id"),
        "waypoint_id": raw.get("waypoint_id"),
        "room_id": raw.get("room_id"),
        "held_object_id": raw.get("held_object_id"),
        "perception_mode": raw.get("perception_mode"),
        "structured_detections_available": raw.get("structured_detections_available"),
        "camera_offset": raw.get("camera_offset"),
        "image_artifacts": raw.get("image_artifacts") or {},
        "artifact_status": raw.get("artifact_status"),
        "robot_view_label": raw.get("robot_view_label"),
        "public_contract_note": raw.get("public_contract_note"),
        "camera_control_summary": _compact_camera_control_contract(
            raw.get("camera_control_contract")
        ),
    }


def _compact_camera_control_contract(contract: Any) -> dict[str, Any]:
    if not isinstance(contract, dict):
        return {
            "schema": "robot_view_camera_control_contract_summary_v1",
            "status": "missing_camera_control_contract",
            "same_pose_api": False,
        }
    agent_facing_fpv = contract.get("agent_facing_fpv")
    agent_facing_fpv = agent_facing_fpv if isinstance(agent_facing_fpv, dict) else {}
    return {
        "schema": "robot_view_camera_control_contract_summary_v1",
        "contract_schema": contract.get("schema"),
        "status": contract.get("status"),
        "camera_model": contract.get("camera_model"),
        "same_pose_api": contract.get("same_pose_api") is True,
        "agent_facing_fpv_source": agent_facing_fpv.get("source"),
        "canonical_camera_control": agent_facing_fpv.get("canonical_camera_control") is True,
    }


def _normalize_robot_view_capture_policy(value: str) -> str:
    policy = str(value or ROBOT_VIEW_CAPTURE_POLICY_FULL).strip() or ROBOT_VIEW_CAPTURE_POLICY_FULL
    if policy not in ROBOT_VIEW_CAPTURE_POLICIES:
        allowed = ", ".join(sorted(ROBOT_VIEW_CAPTURE_POLICIES))
        raise ValueError(f"unsupported robot_view_capture_policy '{value}' (expected {allowed})")
    return policy


def _compact_cleanup_worklist_summary(worklist: dict[str, Any] | None) -> dict[str, Any]:
    worklist = worklist if isinstance(worklist, dict) else {}
    objects = [item for item in worklist.get("objects") or [] if isinstance(item, dict)]
    next_actions = _compact_worklist_next_actions(objects)
    return {
        "schema": "cleanup_worklist_summary_v1",
        "object_count": len(objects),
        "handled_object_handles": [
            str(item.get("object_id") or "")
            for item in objects
            if str(item.get("state") or "") in {"placed", "placed_closed", "skipped"}
        ],
        "pending_object_handles": [
            str(item.get("object_id") or "")
            for item in objects
            if str(item.get("state") or "") == "pending"
        ],
        "objects": [_compact_worklist_object(item) for item in objects],
        "next_actions": next_actions,
        "next_action_count": len(next_actions),
        "held_object_id": worklist.get("held_object_id"),
    }


def _compact_worklist_next_actions(objects: list[dict[str, Any]]) -> list[dict[str, Any]]:
    actions = []
    for item in objects:
        state = str(item.get("state") or "")
        object_id = str(item.get("object_id") or "")
        candidate_fixture_id = str(item.get("candidate_fixture_id") or "")
        if (
            state not in {"pending", "navigating_to_object", "held"}
            or not object_id
            or not candidate_fixture_id
            or not bool(item.get("cleanup_recommended"))
        ):
            continue
        recommended_tool = str(item.get("recommended_tool") or "place")
        if state == "held":
            tool_sequence = ["navigate_to_receptacle", recommended_tool]
        elif state == "navigating_to_object":
            tool_sequence = ["pick", "navigate_to_receptacle", recommended_tool]
        else:
            tool_sequence = [
                "navigate_to_object",
                "pick",
                "navigate_to_receptacle",
                recommended_tool,
            ]
        actions.append(
            {
                "object_id": object_id,
                "category": str(item.get("category") or ""),
                "candidate_fixture_id": candidate_fixture_id,
                "recommended_tool": recommended_tool,
                "state": state,
                "tool_sequence": tool_sequence,
                "source": "cleanup_worklist_summary",
            }
        )
    return actions


def _compact_worklist_object(item: dict[str, Any]) -> dict[str, Any]:
    return _select_keys(
        item,
        (
            "object_id",
            "state",
            "category",
            "room_id",
            "last_waypoint_id",
            "candidate_fixture_id",
            "candidate_source",
            "actionability_status",
            "cleanup_recommended",
            "recommended_tool",
            "visual_grounding_evidence",
        ),
    )


def _select_keys(source: dict[str, Any], keys: tuple[str, ...]) -> dict[str, Any]:
    return {key: source[key] for key in keys if key in source}


def _json_safe(value: Any) -> Any:
    try:
        json.dumps(value)
        return value
    except TypeError:
        if isinstance(value, dict):
            return {str(key): _json_safe(item) for key, item in value.items()}
        if isinstance(value, (list, tuple)):
            return [_json_safe(item) for item in value]
        return str(value)


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(_json_safe(payload), indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def _public_acceptance_config_from_backend(
    base_contract: CleanupBackendSession | None,
) -> dict[str, int]:
    if base_contract is None:
        return {}
    requested = base_contract.requested_generated_mess_count()
    try:
        requested_run_size = int(requested)
    except (TypeError, ValueError):
        return {}
    if requested_run_size <= 0:
        return {}
    return {"requested_run_size": requested_run_size}


def _goal_contract_from_env() -> GoalContract | None:
    path = os.environ.get("ROBOCLAWS_GOAL_CONTRACT_PATH", "")
    if path:
        return goal_contract_from_file(path)
    payload = os.environ.get("ROBOCLAWS_GOAL_CONTRACT_JSON", "")
    if payload:
        return goal_contract_from_json(payload)
    return None


def _required_capability_profiles_from_env() -> tuple[str, ...]:
    raw = os.environ.get("ROBOCLAWS_REQUIRED_CAPABILITY_PROFILES", "")
    return tuple(item.strip() for item in raw.split(",") if item.strip())


def _startup_probe_host(host: str) -> str:
    return "127.0.0.1" if host in {"0.0.0.0", "::"} else host


def _port_accepting(host: str, port: int, *, timeout_s: float = 0.2) -> bool:
    try:
        with socket.create_connection((host, port), timeout=timeout_s):
            return True
    except OSError:
        return False
