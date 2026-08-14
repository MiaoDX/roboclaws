"""FastMCP bridge for the household runtime contract."""

from __future__ import annotations

import os
import socket
import threading
import time
from pathlib import Path
from typing import Any

from mcp.server.fastmcp import FastMCP

from roboclaws.core.goals import (
    GoalContract,
    goal_contract_from_file,
    goal_contract_from_json,
)
from roboclaws.core.operator_messages import (
    check_operator_messages_for_mcp,
)
from roboclaws.core.robot_view_capture import (
    ROBOT_VIEW_CAPTURE_POLICY_FULL,
)
from roboclaws.core.task_intents import (
    household_runtime_intent,
    household_task_identity_from_contract,
    household_task_name,
)
from roboclaws.household import realworld_done_readiness
from roboclaws.household.household_backend_contract import HouseholdBackendSession
from roboclaws.household.household_mcp_artifacts import HouseholdMCPArtifactLifecycle
from roboclaws.household.household_mcp_projection import (
    _build_realworld_mcp_contract,
    _complete_semantic_substep_handles,
    _json_safe,
    _normalize_robot_view_capture_policy,
)
from roboclaws.household.household_mcp_tools import (
    dispatch_household_mcp_tool,
    register_household_mcp_tools,
    validate_household_mcp_tool_call,
)
from roboclaws.household.household_mcp_trace import HouseholdMCPTraceLifecycle
from roboclaws.household.household_runtime_contract import (
    CAMERA_MODEL_POLICY_MODE,
    DEFAULT_REALWORLD_TASK,
    REALWORLD_CONTRACT,
    VISIBLE_OBJECT_DETECTIONS_MODE,
    HouseholdRuntimeContract,
)
from roboclaws.household.semantic_timeline import (
    semantic_substeps,
)
from roboclaws.household.types import CleanupScenario
from roboclaws.household.visual_grounding import (
    SIM_VISUAL_GROUNDING_PIPELINE_ID,
)
from roboclaws.maps.bundle import copy_nav2_map_bundle_snapshot

__all__ = ["MCP_SERVER_NAME", "HouseholdWorldMCPServer", "make_household_world_mcp"]

DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 18788
STARTUP_TIMEOUT_S = 2.0
MCP_SERVER_NAME = "household_world"
AGENT_POLICIES = {
    "household_contract_smoke_agent",
    "codex_agent",
    "claude_code_agent",
}
REPORT_RERUN_COMMAND_ENV = "ROBOCLAWS_REPORT_RERUN_COMMAND"


def make_household_world_mcp(
    *,
    run_dir: Path,
    scenario: CleanupScenario | None = None,
    base_contract: HouseholdBackendSession | None = None,
    contract: HouseholdRuntimeContract | None = None,
    host: str = DEFAULT_HOST,
    port: int = DEFAULT_PORT,
    policy: str = "household_contract_smoke_agent",
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
) -> "HouseholdWorldMCPServer":
    return HouseholdWorldMCPServer(
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


class HouseholdWorldMCPServer(HouseholdMCPArtifactLifecycle, HouseholdMCPTraceLifecycle):
    """FastMCP server wrapping ``HouseholdRuntimeContract`` for agent dogfood."""

    def __init__(
        self,
        *,
        run_dir: Path,
        scenario: CleanupScenario | None = None,
        base_contract: HouseholdBackendSession | None = None,
        contract: HouseholdRuntimeContract | None = None,
        host: str = DEFAULT_HOST,
        port: int = DEFAULT_PORT,
        policy: str = "household_contract_smoke_agent",
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
        self.backend_name = contract.backend_name()
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
        self._completion_response_id = 0
        self._completion_snapshot: dict[str, Any] | None = None

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
        register_household_mcp_tools(self)

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
        validate_household_mcp_tool_call(self, name)
        if name == "done" and self._done_result is not None:
            return self._done_result
        request = _json_safe(kwargs)
        self._write_tool_request(name, request)
        try:
            response = dispatch_household_mcp_tool(self, name, kwargs)
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
        if name != "done":
            self._completion_response_id += 1
            self._completion_snapshot = realworld_done_readiness.completion_snapshot(
                self,
                source_tool=name,
                response_id=self._completion_response_id,
            )
            response = realworld_done_readiness.attach_completion_snapshot(
                response, self._completion_snapshot
            )
        response = self._attach_raw_fpv_artifact_if_needed(name, response)
        self._write_tool_response(name, response)
        if name == "done":
            return self._finalize_done(str(kwargs.get("reason", "")), response)
        self._record_tool_robot_view(name, request, response)
        if name != "done":
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
