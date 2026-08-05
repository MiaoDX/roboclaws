"""Trace, lifecycle, and robot-view capture for the household MCP server."""

from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any

from roboclaws.core.json_sources import read_jsonl_objects
from roboclaws.core.robot_view_capture import (
    ROBOT_VIEW_CAPTURE_POLICY_ACTION_TIMELINE,
    ROBOT_VIEW_CAPTURE_POLICY_FULL,
)
from roboclaws.household.candidate_projection_protocol import (
    project_candidate_public_response,
)
from roboclaws.household.household_mcp_projection import (
    _compact_raw_fpv_mcp_observe_state,
    _json_safe,
)
from roboclaws.household.household_runtime_contract import RAW_FPV_ONLY_MODE
from roboclaws.household.report_snapshots import write_state_snapshot
from roboclaws.household.semantic_camera_timeline import robot_view_capture_for_tool


class HouseholdMCPTraceLifecycle:
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
            compact_state = _compact_raw_fpv_mcp_observe_state(
                response,
                cleanup_worklist=self.contract.cleanup_worklist_payload(),
            )
            trace_response["agent_facing_compact_state"] = project_candidate_public_response(
                "raw_fpv_observe_state", compact_state
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
