"""Safety and trace evidence for the Agibot household backend."""

from __future__ import annotations

from typing import Any

from roboclaws.household.agibot_sdk_contract import (
    AGIBOT_GDK_NORMAL_NAVI_PROVENANCE,
    BLOCKED_MANIPULATION_TOOLS,
)
from roboclaws.household.digital_twin_review_assets import attach_map12_review_assets
from roboclaws.household.manipulation_contract import BLOCKED_CAPABILITY_PROVENANCE
from roboclaws.household.profiles import (
    AGIBOT_GDK_BACKEND_VARIANT,
    AGIBOT_SDK_RUNNER_BACKEND,
    PHYSICAL_ROBOT_EVIDENCE_LANE,
    agibot_gdk_evidence_metadata,
)


class AgibotHouseholdEvidence:
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

    def real_robot_readiness_payload(
        self,
        trace_events: list[dict[str, Any]],
        robot_view_steps: list[dict[str, Any]],
        agent_view: dict[str, Any],
    ) -> dict[str, Any]:
        del trace_events, robot_view_steps, agent_view
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

    def cleanup_policy_trace_payload(
        self,
        trace_events: list[dict[str, Any]],
        agent_view: dict[str, Any],
    ) -> dict[str, Any]:
        del agent_view
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
