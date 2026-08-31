"""Household live-agent kickoff prompts."""

from __future__ import annotations

import argparse
import json
from typing import Any

from roboclaws.core.goals import GoalContract, goal_contract_from_json
from roboclaws.core.map_build_scan_profile import map_build_scan_profile
from roboclaws.core.task_intents import (
    HOUSEHOLD_INTENT_MAP_BUILD,
    household_intent_from_goal_contract,
    household_intent_is_open_ended,
    normalize_household_intent,
)

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
    "Waypoint observation tool={waypoint_observe_tool}. {waypoint_observe_budget}"
    "{camera_grounded_mode}"
)

WORLD_LABELS_RUN_CONTEXT = (
    "Evidence lane=world-public-labels. visible_object_detections are public structured "
    "observations and omit private destination truth. "
)

CAMERA_LABELS_RUN_CONTEXT = (
    "Evidence lane=camera-grounded-labels. Camera-grounded observation mode=observe plus "
    "declare_visual_candidates with observation_id only. "
)

COMPOSITE_CAMERA_GROUNDED_RUN_FACT = (
    "Camera-grounded observation mode=composite via observe_camera_grounded_candidates. "
    "Its response already includes the server-side declaration; do not call "
    "declare_visual_candidates again for the same source_observation_id. "
)

CAMERA_LABELS_COMPOSITE_RUN_CONTEXT = (
    "Evidence lane=camera-grounded-labels. "
    + COMPOSITE_CAMERA_GROUNDED_RUN_FACT
    + " At every public inspection waypoint, call the composite tool at the canonical pose, "
    "then perform three bounded 90-degree body turns, calling the composite tool after each "
    "turn before moving to another waypoint. "
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
            prompt += (
                COMPOSITE_CAMERA_GROUNDED_RUN_FACT
                if camera_grounded_composite_tools
                else "Camera-grounded observation mode=observe plus "
                "declare_visual_candidates with observation_id only. "
            )
    elif profile == "camera-raw-fpv":
        prompt = (
            "Evidence lane=camera-raw-fpv; structured labels are absent. "
            f"Per-waypoint observation budget={max(1, int(max_observe_per_waypoint))}. "
            f"Raw-FPV candidate-attempt budget={max(1, int(raw_fpv_candidate_budget))}. "
            f"Cleanup target cap={max(1, int(target_cleanup_count))}. "
            "Raw image payload persistence=disabled. "
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
    return append_operator_session_context(
        prompt,
        operator_session_context=operator_session_context,
        operator_session_context_json=operator_session_context_json,
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

    scan_profile = map_build_scan_profile()
    composite = profile == "camera-grounded-labels" and camera_grounded_composite_tools
    observe_tool = "observe_camera_grounded_candidates" if composite else "observe"
    profile_observe_count = scan_profile.observe_count_per_waypoint
    effective_observe_count = (
        profile_observe_count
        if max_observe_per_waypoint is None
        else max(1, int(max_observe_per_waypoint))
    )
    body_turn_cadence_overridden = scan_profile.uses_robot_body_turns and (
        effective_observe_count == 1
    )
    observe_budget = f"Per-waypoint observation budget={effective_observe_count}. "
    camera_grounded_mode = ""
    if profile == "camera-grounded-labels":
        camera_grounded_mode = (
            COMPOSITE_CAMERA_GROUNDED_RUN_FACT
            if composite
            else "Camera-grounded observation mode=observe plus declare_visual_candidates. "
        )
    prompt = CUSTOM_PREFIX + MAP_BUILD_RUN_CONTEXT.format(
        task=task,
        profile=profile,
        waypoint_observe_tool=observe_tool,
        waypoint_observe_budget=observe_budget,
        camera_grounded_mode=camera_grounded_mode,
    )
    prompt += (
        f" MapBuild scan_profile={scan_profile.profile_id}; "
        f"body-turn count per waypoint={scan_profile.body_turn_count_per_waypoint}; "
        f"body-turn yaw delta deg={scan_profile.body_turn_yaw_delta_deg:g}; "
        f"profile observe cadence={profile_observe_count} per waypoint; "
        f"effective observe cadence={effective_observe_count} per waypoint; "
        "max_observe_per_waypoint override="
        f"{str(max_observe_per_waypoint is not None).lower()}; "
        "profile body-turn cadence overridden="
        f"{str(body_turn_cadence_overridden).lower()}; "
        f"stable-anchor priority={str(scan_profile.stable_anchor_priority).lower()}; "
        f"stable-anchor categories/policy={scan_profile.description}; "
        f"movable-prior policy={scan_profile.movable_prior_policy}."
    )
    prompt += " " + OPERATOR_STEER_CHECKPOINT_RULES
    if profile == "camera-raw-fpv":
        prompt += " Raw-FPV image blocks are public map evidence; structured labels are absent."
    elif profile == "world-public-labels":
        prompt += " visible_object_detections omit destination oracle fields."
    prompt += " " + RUN_ARTIFACT_CONTRACT
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
