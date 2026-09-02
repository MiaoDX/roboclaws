"""Continuation recovery and trace-derived state for household SDK runs."""

from __future__ import annotations

import argparse
import json
import os
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from roboclaws.agents.drivers.openai_agents_budget import (
    context_budget_failure as _shared_context_budget_failure,
)
from roboclaws.agents.drivers.openai_agents_budget import (
    raw_fpv_budget_failure as _raw_fpv_budget_failure,
)
from roboclaws.agents.drivers.openai_agents_metrics import (
    openai_agents_context_metrics as _context_metrics,
)
from roboclaws.agents.drivers.openai_agents_perf_profile import (
    camera_grounded_composite_tools_enabled_for_run,
)
from roboclaws.agents.live_status import LiveAgentFailure
from roboclaws.agents.live_timing import compact_metric_group as _compact_metric_group
from roboclaws.agents.live_timing import round_duration as _round_duration
from roboclaws.agents.prompts.household_cleanup import (
    render_kickoff_prompt,
    render_map_build_prompt,
)
from roboclaws.agents.task_state import Checkpoint, SnapshotError
from roboclaws.core.completion_snapshot import (
    COMPLETION_SNAPSHOT_SCHEMA,
    completion_snapshot_digest,
)
from roboclaws.core.json_sources import read_json_value, read_jsonl_objects
from roboclaws.core.operator_messages import consume_resume_request_for_runner
from roboclaws.core.raw_fpv_guidance import raw_fpv_edge_reframe_instruction
from roboclaws.core.task_intents import household_intent_from_args as _household_intent

DEFAULT_INCOMPLETE_TURN_CONTINUATION_PROMPT = """
Continuation recovery for the same live household cleanup run:

The previous OpenAI Agents SDK invocation ended without calling `done`, so no
`run_result.json` was produced. Continue from the current cleanup MCP server
state. Do not summarize progress as a final answer. First inspect the current
runtime state through cleanup tools, then continue only missing waypoint,
visual-grounding, pick/place, or completion steps. Call `done` only after the
MCP-visible task state satisfies the cleanup instructions. The runner will count
success only when MCP `done` produces `run_result.json`.
""".strip()
OPERATOR_HANDOFF_MARKERS = (
    "manual adjust",
    "manual reposition",
    "manual control",
    "operator handoff",
    "human handoff",
    "wait for operator",
    "wait for human",
    "手动调整",
    "手动调",
    "手动控制",
    "手动移动",
    "人工调整",
    "人工接管",
    "人工介入",
)
OPERATOR_HANDOFF_WAIT_MARKERS = (
    "do not call done",
    "don't call done",
    "not call done",
    "without done",
    "do not exit",
    "don't exit",
    "wait",
    "stop here",
    "不调用 done",
    "不调用done",
    "不要调用 done",
    "不要调用done",
    "不 call done",
    "不退出",
    "不要退出",
    "不要推出",
    "等待",
    "我现在停止",
)


@dataclass(frozen=True)
class IncompleteTurnRecoveryPolicy:
    """Bounded recovery for SDK turns that end cleanly before MCP completion."""

    max_attempts: int
    reason: str = "incomplete_agent_turn"
    continuation_suffix: str = DEFAULT_INCOMPLETE_TURN_CONTINUATION_PROMPT

    def continuation_prompt(
        self,
        *,
        original_prompt: str,
        result: Any,
        run_dir: Path,
        attempt_index: int,
        profile: dict[str, Any] | None = None,
        context_metrics: dict[str, Any] | None = None,
    ) -> str | None:
        decision = classify_checkpoint_resumability(
            run_dir, result=result, attempt_index=attempt_index, max_attempts=self.max_attempts
        )
        if not decision.resumable:
            return None
        context_budget_recovery = _is_context_budget_result(result)
        turn_budget_recovery = _is_turn_budget_result(result)
        budget_recovery = context_budget_recovery or turn_budget_recovery
        if getattr(result, "exit_status", None) not in {0, None} and not budget_recovery:
            return None
        if getattr(result, "phase", "") != "agent-turn-complete" and not budget_recovery:
            return None
        profile = profile or {}
        context_metrics = context_metrics or {}
        return _compact_continuation_prompt(
            run_dir,
            profile=profile,
            context_metrics=context_metrics,
        )


@dataclass(frozen=True)
class ContinuationDecision:
    resumable: bool
    reason_code: str


def classify_checkpoint_resumability(
    run_dir: Path, *, result: Any, attempt_index: int, max_attempts: int
) -> ContinuationDecision:
    """Classify whether an interrupted SDK result may resume from a checkpoint."""
    if max_attempts <= 0 or attempt_index >= max_attempts:
        return ContinuationDecision(False, "continuation_exhausted")
    if (run_dir / "run_result.json").is_file():
        return ContinuationDecision(False, "terminal_completion_present")
    reason = str(getattr(result, "reason", "") or "")
    context = reason == "provider_context_budget_exceeded"
    turn = reason == "agent_sdk_turn_budget_exceeded"
    if getattr(result, "exit_status", None) not in {0, None} and not (context or turn):
        return ContinuationDecision(False, "non_context_provider_failure")
    if getattr(result, "phase", "") != "agent-turn-complete" and not (context or turn):
        return ContinuationDecision(False, "non_context_provider_failure")
    if context:
        checkpoint = run_dir / "checkpoint.json"
        if not checkpoint.is_file():
            return ContinuationDecision(False, "checkpoint_missing")
        try:
            Checkpoint.from_json(checkpoint.read_text(encoding="utf-8"))
        except (OSError, SnapshotError):
            return ContinuationDecision(False, "checkpoint_invalid")
    try:
        _latest_canonical_completion_snapshot(run_dir)
    except RuntimeError:
        return ContinuationDecision(False, "completion_state_invalid")
    if context:
        return ContinuationDecision(True, "context_budget_overflow_resumable")
    return ContinuationDecision(True, "turn_budget_resumable")


def _is_context_budget_result(result: Any) -> bool:
    return str(getattr(result, "reason", "") or "") == "provider_context_budget_exceeded"


def _is_turn_budget_result(result: Any) -> bool:
    return str(getattr(result, "reason", "") or "") == "agent_sdk_turn_budget_exceeded"


def _continuation_recovery_reason(
    *,
    context_budget_recovery: bool,
    turn_budget_recovery: bool,
    default_reason: str,
) -> str:
    if context_budget_recovery:
        return "context_budget_compact_continuation"
    if turn_budget_recovery:
        return "turn_budget_compact_continuation"
    return default_reason


def _profiled_kickoff_prompt(args: argparse.Namespace, *, profile: dict[str, Any]) -> str:
    original = str(getattr(args, "kickoff_prompt", "") or "")
    lane = str(getattr(args, "profile", "") or "")
    composite_tools = camera_grounded_composite_tools_enabled_for_run(
        profile,
        evidence_lane=lane,
    )
    if _prompt_already_matches_profile(
        original,
        camera_grounded_composite_tools=composite_tools,
    ):
        return original
    intent = _household_intent(args)
    can_render = lane in {"world-public-labels", "camera-grounded-labels", "camera-raw-fpv"}
    if not can_render:
        return original
    if intent == "map-build":
        try:
            return render_map_build_prompt(
                lane,
                str(getattr(args, "task", "") or "build a Runtime Metric Map of this room"),
                camera_grounded_composite_tools=composite_tools,
                max_observe_per_waypoint=_int_or_none(profile.get("max_observe_per_waypoint")),
            )
        except ValueError:
            return original
    if intent != "cleanup":
        return original
    target_cleanup_count = _target_cleanup_count_for_prompt(args, lane=lane)
    try:
        return render_kickoff_prompt(
            lane,
            task=str(getattr(args, "task", "") or ""),
            target_cleanup_count=target_cleanup_count,
            intent=intent,
            goal_contract=None,
            raw_fpv_candidate_budget=int(profile.get("raw_fpv_candidate_budget") or 24),
            max_observe_per_waypoint=int(profile.get("max_observe_per_waypoint") or 1),
            done_retry_budget=int(profile.get("done_retry_budget") or 1),
            camera_grounded_composite_tools=composite_tools,
        )
    except ValueError:
        return original


def _target_cleanup_count_for_prompt(args: argparse.Namespace, *, lane: str) -> int:
    raw_count = str(getattr(args, "min_generated_mess_count", "") or "")
    try:
        count = int(raw_count)
    except ValueError:
        count = 7
    if lane == "camera-raw-fpv":
        return max(1, (count * 7 + 9) // 10)
    return max(1, count)


def _kickoff_prompt_source(args: argparse.Namespace, profile: dict[str, Any]) -> str:
    original = str(getattr(args, "kickoff_prompt", "") or "")
    composite_tools = camera_grounded_composite_tools_enabled_for_run(
        profile,
        evidence_lane=str(getattr(args, "profile", "") or ""),
    )
    if _prompt_already_matches_profile(
        original,
        camera_grounded_composite_tools=composite_tools,
    ):
        return "provided-lane-default"
    rendered = _profiled_kickoff_prompt(args, profile=profile)
    if rendered == original:
        return "provided"
    return "profile-rendered-lane-default"


def _prompt_already_matches_profile(
    prompt: str, *, camera_grounded_composite_tools: bool = False
) -> bool:
    marker = "observe_camera_grounded_candidates instead of a"
    if camera_grounded_composite_tools:
        return marker in prompt
    return marker not in prompt and (
        "Compact action cadence for world-public-labels" in prompt
        or "Compact action cadence for camera-grounded-labels" in prompt
        or "Compact action cadence for camera-raw-fpv" in prompt
    )


def _budget_failure_from_run_state(
    run_dir: Path,
    timing: dict[str, Any],
    profile: dict[str, Any],
) -> LiveAgentFailure | None:
    context_failure = _context_budget_failure(run_dir, timing, profile)
    if context_failure is not None:
        return context_failure
    return _raw_fpv_budget_failure(run_dir, timing, profile)


def _failure_from_sdk_result(
    result: Any,
    *,
    run_dir: Path,
    timing: dict[str, Any],
    profile: dict[str, Any],
) -> LiveAgentFailure:
    if (
        str(getattr(result, "reason", "") or "") == "agent_sdk_turn_budget_exceeded"
        and str(timing.get("evidence_lane") or timing.get("profile") or "") == "camera-raw-fpv"
    ):
        context_metrics = _context_metrics(run_dir, timing)
        detail = json.dumps(
            {
                "schema": "agent_sdk_raw_fpv_budget_terminal_v1",
                "profile_id": profile.get("profile_id") or "baseline",
                "reason": "raw_fpv_sdk_turn_budget_exhausted",
                "max_turns": profile.get("max_turns"),
                "context_hard_limit_tokens": profile.get("context_hard_limit_tokens"),
                "max_input_tokens": context_metrics.get("max_input_tokens"),
                "total_input_tokens": context_metrics.get("total_input_tokens"),
                "total_uncached_input_tokens": context_metrics.get("total_uncached_input_tokens"),
                "response_span_count": context_metrics.get("response_span_count"),
            },
            sort_keys=True,
        )
        return LiveAgentFailure(
            "raw_fpv_sdk_turn_budget_exhausted",
            retryable=False,
            resume_available=False,
            detail=detail,
        )
    return LiveAgentFailure(
        reason=getattr(result, "reason", "") or "agent_cli_failure",
        retryable=bool(getattr(result, "retryable", False)),
        provider_reason=getattr(result, "provider_reason", ""),
        resume_available=bool(getattr(result, "resume_available", False)),
        detail=getattr(result, "detail", ""),
    )


def _explicit_operator_handoff_requested(args: argparse.Namespace) -> str:
    parts = [
        str(getattr(args, "task", "") or ""),
        str(getattr(args, "kickoff_prompt", "") or ""),
    ]
    text = _normalized_handoff_text("\n".join(part for part in parts if part))
    if not text:
        return ""
    has_manual_marker = any(marker in text for marker in OPERATOR_HANDOFF_MARKERS)
    has_wait_marker = any(marker in text for marker in OPERATOR_HANDOFF_WAIT_MARKERS)
    if not (has_manual_marker and has_wait_marker):
        return ""
    return (
        "OpenAI Agents SDK ended without done after an explicit operator handoff request. "
        "The MCP server remains alive for operator-console manual control."
    )


def _claim_operator_resume_request(path: Path | None) -> dict[str, Any]:
    if path is None:
        return {}
    result = consume_resume_request_for_runner(path.parent)
    if not result.get("ok"):
        raise RuntimeError(str(result.get("error_reason") or "operator resume source error"))
    requests = result.get("requests")
    if isinstance(requests, list) and requests:
        request = requests[0]
        return request if isinstance(request, dict) else {}
    return {}


def _resume_prompt(original_prompt: str, request: dict[str, Any]) -> str:
    packet = request.get("resume_request_packet")
    public_packet = packet if isinstance(packet, dict) else {}
    return (
        f"{original_prompt.rstrip()}\n\n"
        "Paused operator handoff resume for the same live MCP run:\n"
        "The operator has manually adjusted or inspected the robot and now requests a "
        "new agent turn. Use current public MCP state, preserve the existing run trace, "
        "and do not consume queued Steer messages as resume input. Call task-relevant "
        "MCP tools, then call done only when the public task is complete.\n\n"
        f"resume_request_packet:\n{json.dumps(public_packet, ensure_ascii=False, sort_keys=True)}\n"
    )


def _next_sdk_resume_attempt_index(run_dir: Path) -> int:
    return 1 + len(list(run_dir.glob("openai-agents-events.resume-*.jsonl")))


def _normalized_handoff_text(text: str) -> str:
    lowered = text.lower()
    for char in "`'\"“”‘’[](){}<>":
        lowered = lowered.replace(char, " ")
    return " ".join(lowered.split())


def _wait_for_terminal_phase_from_status(status_path: Path, *, timeout_s: float = 2.0) -> str:
    deadline = time.monotonic() + timeout_s
    while True:
        phase = _phase_from_status(status_path)
        if phase in {
            "finished",
            "failed",
            "stopped_by_operator",
            "human_takeover_stop",
            "emergency_stopped",
        }:
            return phase
        if time.monotonic() >= deadline:
            return phase
        time.sleep(0.05)


def _phase_from_status(status_path: Path) -> str:
    if not status_path.is_file():
        return ""
    payload = read_json_value(status_path, label="OpenAI Agents live status")
    if not isinstance(payload, dict):
        raise ValueError(
            f"OpenAI Agents live status must contain a JSON object, got {type(payload).__name__}"
        )
    return str(payload.get("phase") or "").strip().lower()


def _context_budget_failure(
    run_dir: Path,
    timing: dict[str, Any],
    profile: dict[str, Any],
) -> LiveAgentFailure | None:
    return _shared_context_budget_failure(run_dir, timing, profile)


def _compact_continuation_prompt(
    run_dir: Path,
    *,
    profile: dict[str, Any],
    context_metrics: dict[str, Any],
) -> str:
    state = _compact_continuation_state(
        run_dir,
        profile=profile,
        context_metrics=context_metrics,
    )
    profile_guidance = _compact_continuation_profile_guidance(profile)
    profile_guidance_section = f"\n\n{profile_guidance}" if profile_guidance else ""
    intent = str(state.get("intent") or "cleanup")
    task_guidance = _compact_continuation_task_guidance(intent)
    return (
        f"Continuation recovery for the same live household {intent} run.\n\n"
        "Use this compact public state packet instead of replaying the original "
        "kickoff prompt. Do not summarize progress as a final answer. "
        f"{task_guidance} "
        "Call done only after MCP-visible public state satisfies the task. "
        "The runner will count success only when MCP done produces run_result.json."
        f"{profile_guidance_section}\n\n"
        f"compact_continuation_state:\n{json.dumps(state, ensure_ascii=False, sort_keys=True)}\n"
    )


def _compact_continuation_task_guidance(intent: str) -> str:
    if intent == "map-build":
        return (
            "Continue only missing public map sweep and Runtime Metric Map evidence work. "
            "Do not pick, place, or perform cleanup manipulation for a map-build task. "
            "Use completed_waypoints and latest_done_blockers before requesting fresh MCP state."
        )
    if intent == "open-ended":
        return (
            "Preserve goal_summary and continue only the missing search, inspection, or "
            "task-relevant action. Do not switch into whole-room cleanup unless the goal asks "
            "for cleanup."
        )
    return (
        "Continue missing cleanup work in this order: first finish held entries in "
        "actionable_pending_candidates using their destination_options; then advance pending "
        "entries with their required_tool; then continue the public sweep at "
        "next_unvisited_waypoint. Do not broad re-sweep while an actionable held or pending "
        "candidate remains."
    )


def _compact_continuation_profile_guidance(profile: dict[str, Any]) -> str:
    if profile.get("raw_fpv_candidate_budget") is not None:
        return (
            "RAW-FPV continuation: if latest_done_blockers is non-empty, do not call done "
            "again until its public current values reach required or trace-reconciled progress "
            "shows a new completion chain. A heading-coverage blocker has first priority: use "
            "remaining_observes_by_waypoint and visit only a waypoint whose remaining count is "
            "positive until that blocker is resolved. Do not consume raw_fpv_revisit_waypoints "
            "while a heading-coverage blocker remains. Do not broad re-sweep exhausted "
            "waypoints; the bounded raw_fpv_revisit_waypoints pass below is the only exception. "
            "If latest_done_blockers contains insufficient_raw_fpv_overlap_probe_coverage, "
            "follow its next_waypoint_id and required_camera_adjustment exactly: navigate there, "
            "call adjust_camera(yaw_delta_deg=45, pitch_delta_deg=20) once, then observe the "
            "fresh diagonal overlap view even when the normal waypoint observe count is exhausted. "
            "If latest_done_blockers contains insufficient_raw_fpv_heading_coverage, follow "
            "its next_waypoint_id and stay at that waypoint for a complete deterministic body "
            "sweep: observe the canonical pose, then call "
            "navigate_to_relative_pose(forward_m=0, lateral_m=0, yaw_delta_deg=90) followed by "
            "observe three consecutive times before leaving. Do not return to canonical or switch "
            "waypoints after only one relative rotation. Treat remaining_observes_by_waypoint as "
            "the public distinct-heading deficit, not a hard cap on recovery observations. "
            "After heading coverage is complete, if insufficient_grounded_cleanup_chains still "
            "remains and no held or pending candidate exists, visit raw_fpv_revisit_waypoints in "
            "order. This is a bounded public recovery pass over otherwise scan-exhausted "
            "waypoints: visit each listed waypoint at most once, call "
            "navigate_to_relative_pose(forward_m=0, lateral_m=0, yaw_delta_deg=45) once, then "
            "observe exactly one fresh diagonal view. Act only on a high-confidence candidate in "
            "that fresh observation, never copy an old source observation, bbox, or public "
            "candidate id, and stop the pass when the public chain gate is met or the list is "
            "exhausted. Do not revisit waypoints absent from that list. "
            "Prefer candidate_free_scan_waypoints in the "
            "listed most-recently-observed-first order before revisiting waypoints that already "
            "produced candidate attempts; this preserves the latest FPV context and current pose. "
            "An empty default FPV view is not evidence that the whole room is clear. Act on each "
            "fresh high-confidence visible candidate "
            "with navigate_to_visual_candidate and complete its pick/place chain. "
            + raw_fpv_edge_reframe_instruction()
            + " Respect raw_fpv_candidate_budget.remaining and do not retry entries "
            "listed in recent_failed_candidate_attempts. Do not call "
            "metric_map again when completed_waypoints already contains the public checklist."
        )
    composite = profile.get("camera_grounded_composite_tools")
    if not isinstance(composite, dict) or not bool(composite.get("enabled")):
        return ""
    tool_names = composite.get("tool_names")
    if not isinstance(tool_names, list) or "observe_camera_grounded_candidates" not in tool_names:
        return ""
    return (
        "Camera-grounded composite continuation: keep using "
        "observe_camera_grounded_candidates for remaining waypoint observations. "
        "Do not resume the older observe plus declare_visual_candidates cadence, and "
        "do not call declare_visual_candidates again for a source_observation_id "
        "already handled by observe_camera_grounded_candidates unless a public tool "
        "explicitly asks for it. If latest_done_blockers contains "
        "insufficient_camera_grounded_heading_coverage and no "
        "pending_cleanup_candidates blocker exists, ignore all previously seen object handles. "
        "Navigate to that blocker's next_waypoint_id, call the composite tool at the canonical "
        "pose, then perform three consecutive navigate_to_relative_pose(yaw_delta_deg=90) plus "
        "composite observations before leaving that waypoint. Do not call navigate_to_object, "
        "pick, navigate_to_receptacle, or place for an old handle during this recovery; act only "
        "when the latest completion snapshot returns that handle in pending_cleanup_candidates. "
        "Never retry a handle after a public tool says it is not cleanup-recommended or says not "
        "to retry it. Keep bounded heading recovery ahead of calling done, but do not perform it "
        "speculatively at every waypoint."
    )


def _compact_continuation_state(
    run_dir: Path,
    *,
    profile: dict[str, Any],
    context_metrics: dict[str, Any],
) -> dict[str, Any]:
    snapshot = _latest_canonical_completion_snapshot(run_dir)
    return {
        "schema": "compact_agent_state_v1",
        "intent": snapshot.get("task_intent") or "cleanup",
        "agent_sdk_perf_profile_id": profile.get("profile_id") or "baseline",
        "completion": snapshot,
        "completion_digest": snapshot["digest"],
        "context_metrics": _compact_metric_group(context_metrics),
    }


def _latest_canonical_completion_snapshot(run_dir: Path) -> dict[str, Any]:
    events = _read_jsonl_path(run_dir / "trace.jsonl")
    responses = [event for event in events if event.get("event") == "response"]
    if not responses:
        raise RuntimeError("terminal-incomplete: missing completion continuation state")
    latest = responses[-1]
    response = latest.get("response")
    snapshot = response.get("completion") if isinstance(response, dict) else None
    if not isinstance(snapshot, dict):
        raise RuntimeError("terminal-incomplete: missing completion continuation state")
    if snapshot.get("schema") != COMPLETION_SNAPSHOT_SCHEMA:
        raise RuntimeError("terminal-incomplete: malformed completion continuation state")
    if snapshot.get("source_tool") != latest.get("tool"):
        raise RuntimeError("terminal-incomplete: stale completion continuation state")
    response_id = snapshot.get("response_id")
    if not isinstance(response_id, int) or isinstance(response_id, bool) or response_id < 1:
        raise RuntimeError("terminal-incomplete: malformed completion continuation state")
    expected = completion_snapshot_digest(snapshot)
    if snapshot.get("digest") != expected:
        raise RuntimeError("terminal-incomplete: malformed completion continuation state digest")
    prior_ids = []
    for event in responses[:-1]:
        prior_response = event.get("response")
        prior = prior_response.get("completion") if isinstance(prior_response, dict) else None
        if isinstance(prior, dict) and isinstance(prior.get("response_id"), int):
            prior_ids.append(prior["response_id"])
    if prior_ids and response_id <= max(prior_ids):
        raise RuntimeError("terminal-incomplete: stale completion continuation state")
    return dict(snapshot)


def _sdk_attempt_summary(result: Any, *, attempt_index: int) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "attempt_index": attempt_index,
        "attempt_role": "continuation" if attempt_index else "initial",
        "phase": getattr(result, "phase", ""),
        "exit_status": getattr(result, "exit_status", None),
        "reason": getattr(result, "reason", ""),
        "provider_reason": getattr(result, "provider_reason", ""),
        "run_result_present": bool(getattr(result, "run_result_present", False)),
        "trace_id": getattr(result, "trace_id", ""),
        "provider_session_id": getattr(result, "provider_session_id", ""),
    }
    started = _float_or_none(getattr(result, "started_at_epoch", None))
    finished = _float_or_none(getattr(result, "finished_at_epoch", None))
    if started is not None:
        payload["started_at_epoch"] = started
    if finished is not None:
        payload["finished_at_epoch"] = finished
    if started is not None and finished is not None:
        payload["elapsed_s"] = _round_duration(finished - started)
    return payload


def _task_aware_continuation_suffix(args: Any) -> str:
    intent = _household_intent(args) or "cleanup"
    task = " ".join(str(getattr(args, "task", "") or "").split())
    preset = os.environ.get("ROBOCLAWS_TASK_PRESET", "")
    selected = "surface=household-world"
    if preset:
        selected += f" preset={preset}"
    elif intent != "open-ended":
        selected += f" preset={intent}"
    if intent == "open-ended":
        return (
            f"Continuation recovery for the same live household open-task run ({selected}):\n\n"
            "The previous OpenAI Agents SDK invocation ended without calling `done`, so no "
            "`run_result.json` was produced. Continue from the current household MCP server "
            "state. Preserve the operator goal"
            + (f": {task}" if task else ".")
            + " Do not switch into a room-cleanup routine unless the operator goal itself "
            "requires cleanup. First inspect public MCP state as needed, then continue only "
            "the missing search, inspection, manipulation, or completion steps needed for "
            "that goal. Call `done` when the public evidence supports task completion."
        )
    return (
        f"Continuation recovery for the same live household preset run ({selected}):\n\n"
        "The previous OpenAI Agents SDK invocation ended without calling `done`, so no "
        "`run_result.json` was produced. Continue from the current household MCP server "
        "state. Do not summarize progress as a final answer. First inspect the current "
        "runtime state through public tools, then continue only missing preset-specific "
        "steps. Call `done` only after MCP-visible task state satisfies the selected "
        "preset instructions."
    )


def _read_jsonl_path(path: Path) -> list[dict[str, Any]]:
    if not path.is_file():
        return []
    return read_jsonl_objects(path, label="OpenAI Agents live")


def _float_or_none(value: Any) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _int_or_none(value: Any) -> int | None:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None
