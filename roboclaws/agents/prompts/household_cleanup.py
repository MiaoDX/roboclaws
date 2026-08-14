"""Household live-agent kickoff prompts."""

from __future__ import annotations

import argparse
import json
from typing import Any

from roboclaws.household.map_build_scan_profile import (
    map_build_scan_profile,
)
from roboclaws.household.task_intent import (
    HOUSEHOLD_INTENT_MAP_BUILD,
    household_intent_from_goal_contract,
    household_intent_is_open_ended,
    normalize_household_intent,
)
from roboclaws.launch.goals import GoalContract, goal_contract_from_json

TOOL_PROTOCOL_PREFIX = (
    "Use the cleanup MCP tool entries exactly as exposed by Codex; in text, "
    "refer to unprefixed tool names, and if the tool protocol requires a namespace "
    "use namespace cleanup, never mcp__cleanup__ or roboclaws__. "
)

OPEN_TASK_TOOL_PROTOCOL_PREFIX = (
    "Use the household MCP tool entries exactly as exposed by Codex; in text, "
    "refer to unprefixed tool names, and if the tool protocol requires a namespace "
    "use namespace cleanup, never mcp__cleanup__ or roboclaws__. "
)

COMMON_PREFIX = "Use the bundled household-world skill instructions. " + TOOL_PROTOCOL_PREFIX

CUSTOM_PREFIX = (
    "Use the bundled household-world skill instructions. "
    "Use the MCP tools as a bounded household robot capability surface. "
    + OPEN_TASK_TOOL_PROTOCOL_PREFIX
)

RUN_ARTIFACT_CONTRACT = (
    "Required closeout artifacts: run_result.json, runtime_metric_map.json, and report.html; "
    "only the MCP done response creates the authoritative run result. "
)
HOUSEHOLD_CLEANUP_TASK_PREFIX = (
    "This run is surface=household-world intent=cleanup. User task: {task}. "
)
OPEN_ENDED_HOUSEHOLD_TASK_PREFIX = (
    "This run is surface=household-world with no task preset. "
    "The following operator task is authoritative: {task}. When this wrapper "
    "and the operator task conflict, follow the "
    "operator task subject to public tool safety and error responses. "
)
DEFAULT_HOUSEHOLD_CLEANUP_TASK = "clean up this room"
OPERATOR_SESSION_CONTEXT_MAX_CHARS = 12_000
OPERATOR_SESSION_CONTEXT_HEADING = "Operator Session follow-up context"
OPERATOR_SESSION_PRIVATE_TERMS = (
    "generated_mess_set",
    "generated_mess_truth",
    "acceptable_destination_sets",
    "acceptable_destination",
    "private_manifest",
    "target_receptacle_id",
    "private_target_truth",
    "global_movable_object_inventory",
    "private_scorer_truth",
    "scorer_truth",
)
OPERATOR_STEER_CHECKPOINT_RULES = (
    "Operator steering checkpoint rule: this run may receive public operator "
    "steering through check_operator_messages. Call check_operator_messages after "
    "metric_map, after each observe or observe_camera_grounded_candidates response, "
    "before starting a new task/object/search chain, and before done. If any tool "
    "response includes operator_message_pending, pending_operator_message_count, or "
    "an operator_message_instruction, call check_operator_messages before continuing "
    "or ending. Treat seen messages as public steering hints; do not read private "
    "run artifacts for steering."
)


def _normalize_task(task: str) -> str:
    return " ".join(str(task or "").split()) or DEFAULT_HOUSEHOLD_CLEANUP_TASK


def _task_prefix(
    task: str,
    *,
    household_intent: str = "",
    goal_contract: GoalContract | None = None,
) -> str:
    normalized = _normalize_task(task)
    if goal_contract is not None:
        return (
            f"This run is surface={goal_contract.surface} intent={goal_contract.intent}. "
            f"Normalized goal: {goal_contract.normalized_goal}. "
            f"Goal scope: {goal_contract.goal_scope}. Raw user goal: "
            f"{goal_contract.raw_prompt or normalized}. "
        )
    if household_intent_is_open_ended(household_intent):
        return OPEN_ENDED_HOUSEHOLD_TASK_PREFIX.format(task=normalized)
    return HOUSEHOLD_CLEANUP_TASK_PREFIX.format(task=normalized)


def _with_task(
    prompt: str,
    task: str,
    *,
    household_intent: str = "",
    goal_contract: GoalContract | None = None,
) -> str:
    prefix = CUSTOM_PREFIX if household_intent_is_open_ended(household_intent) else COMMON_PREFIX
    return (
        prefix
        + _task_prefix(
            task,
            household_intent=household_intent,
            goal_contract=goal_contract,
        )
        + prompt
    )


MAP_BUILD_RUN_CONTEXT = (
    "This run is surface=household-world intent=map-build. User task: {task}. "
    "Manipulation tools are not entitled for this run. Evidence lane={profile}. "
    "Waypoint observation tool={waypoint_observe_tool}. {waypoint_observe_budget_rule}"
    "{camera_grounded_rule}"
)

WORLD_LABELS_RUN_CONTEXT = (
    "Evidence lane=world-public-labels. visible_object_detections are public structured "
    "observations and omit private destination truth. "
)

CAMERA_LABELS_RUN_CONTEXT = (
    "Evidence lane=camera-grounded-labels. For each task-relevant raw FPV observation, call "
    "declare_visual_candidates with observation_id only so the configured server-side labeler "
    "produces public candidates; service URLs, credentials, and image paths are not agent input. "
)

CAMERA_LABELS_COMPOSITE_RUN_CONTEXT = (
    "Evidence lane=camera-grounded-labels with composite observation enabled. Use "
    "observe_camera_grounded_candidates instead of a separate observe plus declaration. "
    "Treat its observation as waypoint evidence and its declaration as server-side labeler "
    "output; do not call "
    "declare_visual_candidates again for the same source_observation_id unless "
    "a public tool explicitly asks for it. Service URLs, credentials, image paths, and model "
    "hosts are not agent input. "
)


def _camera_raw_compact_prompt(
    *,
    target_cleanup_count: int = 7,
    raw_fpv_candidate_budget: int = 24,
    max_observe_per_waypoint: int = 4,
    done_retry_budget: int = 1,
) -> str:
    cleanup_count = max(1, int(target_cleanup_count))
    candidate_budget = max(1, int(raw_fpv_candidate_budget))
    observe_budget = max(1, int(max_observe_per_waypoint))
    done_budget = max(0, int(done_retry_budget))
    return (
        "Evidence lane=camera-raw-fpv. Inspect raw FPV image blocks directly; no structured "
        f"labels are provided. Per-waypoint distinct-heading budget={observe_budget}. Every "
        "waypoint must complete that many "
        "materially distinct robot-body headings, even when the cleanup gate is already met. "
        "The canonical navigate_to_waypoint then observe supplies the first heading. Repeat "
        "navigate_to_relative_pose(forward_m=0, lateral_m=0, yaw_delta_deg=90) then observe at "
        "that same waypoint until the required distinct-heading count is reached. A repeated "
        "heading does not count; rotate again instead of moving to the next waypoint. If a fresh "
        "candidate requires an immediate cleanup chain, return afterward and finish that "
        "waypoint's missing body headings. "
        "When a waypoint has not produced a public cleanup_recommended=true candidate by its "
        "final distinct heading, take one extra overlap probe after those body headings: call "
        "adjust_camera(yaw_delta_deg=45, pitch_delta_deg=20) exactly once, then observe. This "
        "camera-only probe does not count as a distinct robot-body heading and is the only "
        "permitted extra observation during the initial sweep. A compact continuation may "
        "authorize one later bounded recovery view at explicitly listed public revisit "
        "waypoints when done still reports a grounded-chain deficit. "
        "Choose at most one fresh high-confidence cleanup "
        "candidate per raw FPV observation. Raw-FPV candidate-attempt budget="
        f"{candidate_budget} raw-FPV candidate attempts. Never retry the same "
        "source_observation_id/category/region or visual-candidate id after a public failure. "
        f"source_observation_id/category/region. Cleanup target cap={cleanup_count}. Done retry "
        f"budget={done_budget}; a retry is permitted only after resolving a returned public "
        "blocker. Raw image payloads must not be persisted. "
    )


def render_kickoff_prompt(
    profile: str,
    *,
    task: str = "",
    target_cleanup_count: int = 7,
    intent: str = "",
    goal_contract: GoalContract | None = None,
    raw_fpv_candidate_budget: int = 24,
    max_observe_per_waypoint: int = 4,
    done_retry_budget: int = 1,
    camera_grounded_composite_tools: bool = False,
    operator_session_context: dict[str, Any] | None = None,
    operator_session_context_json: str = "",
) -> str:
    """Render the live-agent kickoff prompt for a cleanup evidence lane."""

    household_intent = household_intent_from_goal_contract(goal_contract, fallback=intent)
    household_intent = normalize_household_intent(household_intent)
    open_ended = household_intent_is_open_ended(household_intent)
    if open_ended:
        prompt = "Evidence lane=" + profile + ". "
        if profile == "camera-grounded-labels":
            prompt = (
                prompt
                + " "
                + _camera_grounded_open_ended_rule(
                    camera_grounded_composite_tools=camera_grounded_composite_tools
                )
            )
    elif profile == "camera-raw-fpv":
        prompt = _camera_raw_compact_prompt(
            target_cleanup_count=target_cleanup_count,
            raw_fpv_candidate_budget=raw_fpv_candidate_budget,
            max_observe_per_waypoint=max_observe_per_waypoint,
            done_retry_budget=done_retry_budget,
        )
    elif profile == "camera-grounded-labels":
        prompt = CAMERA_LABELS_RUN_CONTEXT
        if camera_grounded_composite_tools:
            prompt = CAMERA_LABELS_COMPOSITE_RUN_CONTEXT
    elif profile == "world-public-labels":
        prompt = WORLD_LABELS_RUN_CONTEXT
    else:
        prompt = "Evidence lane=" + profile + ". "
    prompt = f"{prompt} {RUN_ARTIFACT_CONTRACT}{OPERATOR_STEER_CHECKPOINT_RULES}"
    prompt = _with_task(
        prompt,
        task,
        household_intent=household_intent,
        goal_contract=goal_contract,
    )
    return _with_operator_session_context(
        prompt,
        operator_session_context=operator_session_context,
        operator_session_context_json=operator_session_context_json,
    )


def _camera_grounded_open_ended_rule(*, camera_grounded_composite_tools: bool) -> str:
    if camera_grounded_composite_tools:
        return (
            "This open-ended run uses camera-grounded-labels: after navigating to a public "
            "waypoint or target candidate, call observe_camera_grounded_candidates so the "
            "configured camera labeler labels the current FPV frame. Use returned public "
            "camera_model_candidates, model_declared_observations, and runtime_metric_map "
            "evidence for the operator task; do not ask for service URLs, credentials, image "
            "paths, or model hosts."
        )
    return (
        "This open-ended run uses camera-grounded-labels: after each task-relevant observe "
        "response with a raw FPV observation_id, call declare_visual_candidates with "
        "observation_id only and omit candidates so the configured camera labeler labels the "
        "frame. Use returned public camera_model_candidates, model_declared_observations, and "
        "runtime_metric_map evidence for the operator task; do not ask for service URLs, "
        "credentials, image paths, or model hosts."
    )


def render_map_build_prompt(
    profile: str,
    task: str,
    *,
    camera_grounded_composite_tools: bool = False,
    max_observe_per_waypoint: int | None = None,
    operator_session_context: dict[str, Any] | None = None,
    operator_session_context_json: str = "",
) -> str:
    """Render the live-agent kickoff prompt for intent=map-build."""

    selected_scan_profile = map_build_scan_profile()
    cadence = _map_build_observe_cadence(
        profile,
        camera_grounded_composite_tools=camera_grounded_composite_tools,
        max_observe_per_waypoint=max_observe_per_waypoint,
    )
    prompt = CUSTOM_PREFIX + MAP_BUILD_RUN_CONTEXT.format(task=task, profile=profile, **cadence)
    prompt += " " + _map_build_scan_profile_prompt(
        selected_scan_profile.to_payload(),
        max_observe_per_waypoint=max_observe_per_waypoint,
        observe_tool=cadence["waypoint_observe_tool"],
    )
    prompt += " " + OPERATOR_STEER_CHECKPOINT_RULES
    if profile == "camera-raw-fpv":
        prompt += " Raw-FPV image blocks are public map evidence; structured labels are absent."
    elif profile == "world-public-labels":
        prompt += " visible_object_detections omit destination oracle fields."
    prompt += " " + RUN_ARTIFACT_CONTRACT
    return _with_operator_session_context(
        prompt,
        operator_session_context=operator_session_context,
        operator_session_context_json=operator_session_context_json,
    )


def _map_build_observe_cadence(
    profile: str,
    *,
    camera_grounded_composite_tools: bool,
    max_observe_per_waypoint: int | None = None,
) -> dict[str, str]:
    observe_budget = _map_build_observe_budget_rule(
        max_observe_per_waypoint=max_observe_per_waypoint,
        observe_tool=(
            "observe_camera_grounded_candidates"
            if profile == "camera-grounded-labels" and camera_grounded_composite_tools
            else "observe"
        ),
    )
    if profile == "camera-grounded-labels" and camera_grounded_composite_tools:
        return {
            "waypoint_observe_tool": "observe_camera_grounded_candidates",
            "waypoint_observe_budget_rule": observe_budget,
            "camera_grounded_rule": (
                "For camera-grounded-labels with the private SDK composite observation tool "
                "enabled, after navigating to each public inspection waypoint call "
                "observe_camera_grounded_candidates so the configured camera labeler labels "
                "the current FPV frame. Treat the response observation as the waypoint "
                "observation evidence and the response declaration as camera-labeler map "
                "evidence. Do not resume the older observe plus declare_visual_candidates "
                "cadence, and do not call declare_visual_candidates again for the same "
                "source_observation_id unless a public tool explicitly asks for it. "
            ),
        }
    if profile == "camera-grounded-labels":
        return {
            "waypoint_observe_tool": "observe",
            "waypoint_observe_budget_rule": observe_budget,
            "camera_grounded_rule": (
                "For camera-grounded-labels, call declare_visual_candidates for each raw FPV "
                "observation with observation_id only and omit candidates so the configured "
                "camera labeler labels the frame. "
            ),
        }
    return {
        "waypoint_observe_tool": "observe",
        "waypoint_observe_budget_rule": observe_budget,
        "camera_grounded_rule": "",
    }


def _map_build_observe_budget_rule(
    *,
    max_observe_per_waypoint: int | None,
    observe_tool: str,
) -> str:
    if max_observe_per_waypoint is None:
        return ""
    observe_budget = max(1, int(max_observe_per_waypoint))
    if observe_budget == 1:
        return (
            f"Prefer one {observe_tool} response per waypoint_id. If evidence remains "
            "ambiguous, record the ambiguity and move on. One bounded re-observation is "
            "allowed only when a public tool requests it or after a successful camera, "
            "pose, or world-state change can produce materially new Runtime Metric Map "
            "evidence. "
        )
    return (
        f"Use at most {observe_budget} {observe_tool} responses per waypoint_id, including "
        "any pose-adjustment recovery; after the budget is reached, record the public "
        "ambiguity and move to the next public waypoint. "
    )


def _with_operator_session_context(
    prompt: str,
    *,
    operator_session_context: dict[str, Any] | None = None,
    operator_session_context_json: str = "",
) -> str:
    return append_operator_session_context(
        prompt,
        operator_session_context=operator_session_context,
        operator_session_context_json=operator_session_context_json,
    )


def append_operator_session_context(
    prompt: str,
    *,
    operator_session_context: dict[str, Any] | None = None,
    operator_session_context_json: str = "",
) -> str:
    if OPERATOR_SESSION_CONTEXT_HEADING in prompt:
        return prompt
    block = _operator_session_context_block(
        operator_session_context=operator_session_context,
        operator_session_context_json=operator_session_context_json,
    )
    if not block:
        return prompt
    return f"{prompt.rstrip()}\n\n{block}"


def _operator_session_context_block(
    *,
    operator_session_context: dict[str, Any] | None = None,
    operator_session_context_json: str = "",
) -> str:
    payload = operator_session_context or _parse_operator_session_context(
        operator_session_context_json
    )
    if not payload:
        return ""
    sanitized = _strip_operator_session_private_payload(payload)
    if not isinstance(sanitized, dict) or not sanitized:
        return ""
    serialized = json.dumps(sanitized, ensure_ascii=False, indent=2, sort_keys=True)
    serialized = _strip_operator_session_private_text(serialized)
    if len(serialized) > OPERATOR_SESSION_CONTEXT_MAX_CHARS:
        serialized = serialized[:OPERATOR_SESSION_CONTEXT_MAX_CHARS].rstrip() + "\n..."
    return (
        f"{OPERATOR_SESSION_CONTEXT_HEADING} (sanitized public next_goal_packet):\n"
        f"{serialized}\n"
        "Use operator_session_id, parent_run_id, the parent public summary, and public "
        "artifact links as continuity context. Use only public parent context; do not "
        "consume hidden scoring, generation, destination-answer, manifest, or inventory "
        "truth from the parent run."
    )


def _parse_operator_session_context(raw: str) -> dict[str, Any]:
    raw = str(raw or "").strip()
    if not raw:
        return {}
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError:
        return {}
    return payload if isinstance(payload, dict) else {}


def _strip_operator_session_private_payload(value: Any) -> Any:
    if isinstance(value, dict):
        output: dict[str, Any] = {}
        for key, item in value.items():
            key_text = str(key)
            if _operator_session_private_key(key_text):
                continue
            output[key_text] = _strip_operator_session_private_payload(item)
        return output
    if isinstance(value, list):
        return [_strip_operator_session_private_payload(item) for item in value]
    if isinstance(value, str):
        return _strip_operator_session_private_text(value)
    return value


def _operator_session_private_key(key: str) -> bool:
    normalized = key.lower()
    return any(term.lower() in normalized for term in OPERATOR_SESSION_PRIVATE_TERMS)


def _strip_operator_session_private_text(text: str) -> str:
    output = text
    for term in OPERATOR_SESSION_PRIVATE_TERMS:
        output = output.replace(term, "[redacted_private_field]")
    return output


def _map_build_scan_profile_prompt(
    scan_profile: dict[str, object],
    *,
    max_observe_per_waypoint: int | None = None,
    observe_tool: str = "observe",
) -> str:
    profile_id = str(scan_profile.get("profile") or "fixture-focused")
    body_turn_count = int(scan_profile.get("body_turn_count_per_waypoint") or 4)
    yaw_delta = float(scan_profile.get("body_turn_yaw_delta_deg") or 90.0)
    emphasis = (
        " Prioritize stable semantic anchors: fixtures, surfaces, receptacles, "
        "room or area anchors, and navigation-visible landmarks. Record movable "
        "objects only as observations that future runs must recheck before action."
        if bool(scan_profile.get("stable_anchor_priority"))
        else ""
    )
    if max_observe_per_waypoint is not None and max(1, int(max_observe_per_waypoint)) == 1:
        return (
            f"MapBuild scan_profile={profile_id}: this managed profile prefers one "
            f"{observe_tool} response per waypoint_id, so skip routine multi-heading "
            "scanning. Use one bounded re-observation only after a successful camera or "
            "pose change when public evidence is ambiguous or a tool requests it; otherwise "
            f"record missing heading coverage as public ambiguity.{emphasis}"
        )
    return (
        f"MapBuild scan_profile={profile_id}: at each inspection waypoint, after the "
        f"initial observe, call navigate_to_relative_pose(forward_m=0, lateral_m=0, "
        f"yaw_delta_deg={yaw_delta:g}) then observe again for each of {body_turn_count} "
        "bounded robot-body headings. If navigate_to_relative_pose is blocked, report "
        "the blocked capability instead of silently treating camera-only scanning as "
        f"complete MapBuild scan proof.{emphasis}"
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Render a household live-agent kickoff prompt.")
    parser.add_argument(
        "--profile",
        "--evidence-lane",
        dest="profile",
        default="world-public-labels",
    )
    parser.add_argument("--task", default="")
    parser.add_argument("--intent", default="")
    parser.add_argument("--goal-contract-json", default="")
    parser.add_argument("--target-cleanup-count", type=int, default=7)
    parser.add_argument("--raw-fpv-candidate-budget", type=int, default=24)
    parser.add_argument("--max-observe-per-waypoint", type=int, default=1)
    parser.add_argument("--done-retry-budget", type=int, default=1)
    parser.add_argument("--camera-grounded-composite-tools", action="store_true")
    parser.add_argument("--operator-session-context-json", default="")
    args = parser.parse_args(argv)
    goal_contract = goal_contract_from_json(args.goal_contract_json)
    intent = normalize_household_intent(str(getattr(goal_contract, "intent", "") or args.intent))
    if intent == HOUSEHOLD_INTENT_MAP_BUILD:
        task = args.task or "build a Runtime Metric Map of this room"
        print(
            render_map_build_prompt(
                args.profile,
                task,
                camera_grounded_composite_tools=args.camera_grounded_composite_tools,
                operator_session_context_json=args.operator_session_context_json,
            )
        )
    else:
        print(
            render_kickoff_prompt(
                args.profile,
                task=args.task,
                target_cleanup_count=args.target_cleanup_count,
                intent=intent,
                goal_contract=goal_contract,
                raw_fpv_candidate_budget=args.raw_fpv_candidate_budget,
                max_observe_per_waypoint=args.max_observe_per_waypoint,
                done_retry_budget=args.done_retry_budget,
                camera_grounded_composite_tools=args.camera_grounded_composite_tools,
                operator_session_context_json=args.operator_session_context_json,
            )
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
