"""Shared public guidance for world-label visual-scan confirmation."""

from __future__ import annotations

from typing import Any

ADJUST_CAMERA_TOOL = "adjust_camera"
OBSERVE_TOOL = "observe"
NAVIGATE_TO_OBJECT_TOOL = "navigate_to_object"

VISUAL_SCAN_NOOP_ERROR_REASON = "noop_camera_adjustment"

FRESH_FPV_EVIDENCE_NOTE = (
    "The cleanup gate is fresh agent-facing FPV evidence with a reviewable bbox. "
    "A default-view observe can satisfy it when it returns that bbox; "
    "adjust_camera(0, 0) is only a no-op camera command and does not create a new view."
)

VISUAL_SCAN_PUBLIC_CONTRACT_NOTE = (
    "Structured world labels are semantic hints only. Before navigate_to_object "
    "or pick, get a fresh source FPV observation whose evidence includes a "
    "reviewable bbox for the same handle. If the current/default view lacks that "
    "bbox, adjust the camera toward the candidate, then observe again."
)


def visual_scan_prompt_rule() -> str:
    return (
        "if a world-label object is visual_scan_required, first obtain a fresh "
        "same-handle source FPV observation with a reviewable bbox before "
        "navigate_to_object; if the current/default view lacks that bbox, call "
        "adjust_camera toward it, then observe. " + FRESH_FPV_EVIDENCE_NOTE
    )


def visual_scan_metric_map_instruction() -> str:
    return (
        "World-label observed_* candidates with candidate_state=visual_scan_required "
        "must have fresh source FPV evidence with a reviewable bbox before "
        "navigate_to_object or pick. If the current/default view lacks that bbox, "
        "use adjust_camera -> observe. " + FRESH_FPV_EVIDENCE_NOTE
    )


def visual_scan_done_recovery_hint() -> str:
    return (
        "Pending observed handles are semantic candidates that still need agent-facing "
        "FPV evidence with a reviewable bbox. Re-observe from the current/default view "
        "if it can produce that bbox; otherwise call adjust_camera toward a candidate, "
        "then observe. Navigate only after candidate_state is navigation_authorized."
    )


def visual_scan_payload(visual_confirmation: bool) -> dict[str, Any]:
    if visual_confirmation:
        return {
            "status": "confirmed_from_source_fpv_observation",
            "required_next_tool": NAVIGATE_TO_OBJECT_TOOL,
        }
    return {
        "status": "required_before_navigation",
        "required_next_tool": ADJUST_CAMERA_TOOL,
        "followup_tool": OBSERVE_TOOL,
        "public_contract_note": VISUAL_SCAN_PUBLIC_CONTRACT_NOTE,
        "fresh_fpv_observation_required": True,
    }


def visual_evidence_recovery_hint() -> str:
    return (
        "Do not navigate or pick this candidate until the agent-facing FPV evidence "
        "has a reviewable bbox. Re-observe if the current/default view can provide "
        "one; otherwise adjust_camera toward the candidate, observe, then retry with "
        "image_region={type:bbox,value:[x,y,width,height]} from the visible object."
    )


def non_recommended_candidate_recovery_hint(perception_mode: str) -> str:
    if perception_mode == "raw_fpv_only":
        return (
            "The current public evidence does not recommend moving this object. Do not "
            "navigate to, pick, or retry it. Keep the current robot pose and call "
            "navigate_to_relative_pose(forward_m=0, lateral_m=0, yaw_delta_deg=90), then "
            "observe until this waypoint has 4 materially distinct robot-body headings; "
            "do not call navigate_to_waypoint again for the same waypoint. Move to the next "
            "public waypoint only after completing that heading sweep."
        )
    return (
        "The current public source/destination evidence does not recommend moving this "
        "object. Do not navigate to or pick it; continue the waypoint sweep."
    )


def noop_camera_adjustment_hint() -> str:
    return (
        "adjust_camera(0, 0) does not change the camera and does not create a fresh "
        "source FPV view. If the current/default view already has a reviewable bbox, "
        "call observe/use that evidence; otherwise retry with a non-zero "
        "yaw_delta_deg or pitch_delta_deg, then call observe."
    )
