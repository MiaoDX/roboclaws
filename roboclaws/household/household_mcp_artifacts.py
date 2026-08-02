"""Public artifact lifecycle for the household MCP server."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from mcp.server.fastmcp import Image as MCPImage

from roboclaws.core.operator_messages import pending_operator_message_hint
from roboclaws.core.raw_fpv_guidance import raw_fpv_inline_candidate_instruction
from roboclaws.household import agent_view as agent_view_module
from roboclaws.household.household_mcp_projection import (
    _compact_declare_visual_candidates_response,
    _compact_raw_fpv_mcp_observe_state,
    _write_json,
)
from roboclaws.household.household_mcp_tools import agent_view_public_tool_names
from roboclaws.household.household_runtime_contract import (
    CAMERA_MODEL_POLICY_MODE,
    RAW_FPV_ONLY_MODE,
    REALWORLD_CONTRACT,
)
from roboclaws.household.realworld_mcp_run_artifacts import (
    RealWorldMCPDoneArtifactInputs,
    finalize_realworld_mcp_done,
)
from roboclaws.household.realworld_run_artifacts import write_runtime_metric_map_preview_artifact
from roboclaws.household.semantic_camera_timeline import camera_offsets_from_raw_fpv_observation
from roboclaws.household.visual_scan_guidance import visual_scan_metric_map_instruction

MCP_SERVER_NAME = "household_world"


class HouseholdMCPArtifactLifecycle:
    def _agent_view_payload(self) -> dict[str, Any]:
        agent_view = self.contract.agent_view_payload()
        return agent_view_module.with_public_tool_names(
            agent_view,
            agent_view_public_tool_names(
                self,
                agent_view_module.public_tool_names(agent_view),
            ),
            capability_profiles=self.required_capability_profiles,
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
                "inspection_waypoints are static map/fixture coverage candidates, not mess hints. "
                "Generated exploration candidate N means 1-based sweep_index=N, never zero-based. "
                f"Prefer navigate_to_waypoint -> observe. {visual_scan_metric_map_instruction()}"
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
                "For the first returned candidate with candidate_state=navigation_authorized, "
                "call navigate_to_object with its public object_id."
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
        agent_view = self._agent_view_payload()
        anchor_prior_count, room_prior_count = self.contract.runtime_map_prior_counts()
        finalized = finalize_realworld_mcp_done(
            RealWorldMCPDoneArtifactInputs(
                run_dir=self.run_dir,
                trace_path=self.trace_path,
                run_result_path=self.run_result_path,
                backend=self.backend_name,
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
                anchor_prior_count=anchor_prior_count,
                room_prior_count=room_prior_count,
                evidence_lane=self.evidence_lane,
                record_robot_views=self.record_robot_views,
                planner_proof_run_result=self.planner_proof_run_result,
                robot_view_steps=self.robot_view_steps,
                robot_view_capture_policy=self.robot_view_capture_policy,
                before_snapshot=self._before_snapshot,
                after_snapshot=after_snapshot,
                trace_events=trace_events,
                agent_view=agent_view,
                done_response=done_response,
                reason=reason,
                tool_event_counts=dict(self._tool_event_counts),
                rerun_command=self.rerun_command,
                mcp_server_name=MCP_SERVER_NAME,
                requested_generated_mess_count=(
                    self.base_contract.requested_generated_mess_count()
                ),
                run_metadata_overrides=self.contract.run_result_overrides(),
                cleanup_policy_trace=self.contract.cleanup_policy_trace_payload(
                    trace_events,
                    agent_view,
                ),
                real_robot_readiness=self.contract.real_robot_readiness_payload(
                    trace_events,
                    self.robot_view_steps,
                    agent_view,
                ),
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
