"""Household live-agent kickoff prompts."""

from __future__ import annotations

import argparse
import json
from typing import Any

from roboclaws.household.map_build_scan_profile import (
    map_build_scan_profile,
)
from roboclaws.household.raw_fpv_guidance import raw_fpv_inline_candidate_instruction
from roboclaws.household.task_intent import (
    HOUSEHOLD_INTENT_MAP_BUILD,
    household_intent_from_goal_contract,
    household_intent_is_open_ended,
    normalize_household_intent,
)
from roboclaws.household.visual_scan_guidance import visual_scan_prompt_rule
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

COMMON_WAYPOINT_RULES = (
    "Call metric_map first, build an exact waypoint checklist "
    "from metric_map.inspection_waypoints, treat the selected Nav2 map bundle only "
    "through metric_map and runtime_metric_map, not raw occupancy images, sweep every "
    "waypoint with navigate_to_waypoint then observe, mark a waypoint complete only "
    "after that waypoint_id has an observe response, "
    "and resolve named targets, stale fixture ids, destination categories, or "
    "open-ended search terms through resolve_target_query and "
    "runtime_metric_map.target_candidates before acting on them; "
)

COMMON_CLEANUP_RULES = (
    "clean plausible observed objects only after their candidate_state is "
    f"navigation_authorized; {visual_scan_prompt_rule()} Clean with "
    "navigate->pick->navigate->open?->place/place_inside following required_tool "
    "if returned, use place_inside for "
    "shelf/bookshelf/bookcase/shelving/fridge targets, do not call scene_objects "
    "or read private scoring artifacts, compare the checklist before done, visit "
    "any missing waypoint_id, and call done only after every "
    "metric_map.inspection_waypoints waypoint_id has been observed so the report "
    "is generated."
)

OPEN_ENDED_TASK_RULES = (
    "The operator task is authoritative. Use metric_map when map context is needed. "
    "Use resolve_target_query for named places, stale labels, or search terms. Navigate "
    "to public waypoints or target_candidates, call observe, and use adjust_camera only "
    "for bounded public recovery when target evidence or observation evidence is "
    "incomplete. Inspect only as much as the operator task needs. For information, "
    "search, or inspection goals, answer from public observations, target_candidates, "
    "and the inspected search budget; not-found answers require enough public evidence "
    "that the useful search space has been checked or exhausted. For manipulation "
    "goals, act only on task-relevant observed objects or visual candidates, use public "
    "navigation/manipulation tools, and follow required_tool, required_next_tool, "
    "blocked_capability, actionability status, or public error responses. Do not call "
    "scene_objects or read private scoring artifacts. Unless the operator explicitly "
    "asks you to wait or not call done, call done when the operator task is satisfied, "
    "blocked by a public capability response, or exhausted by the public search budget, "
    "with a reason summarizing public evidence and remaining risk."
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


MAP_BUILD_RULES = (
    "This run is surface=household-world intent=map-build. "
    "This is not a cleanup run. User task: {task}. "
    "Do not pick, place, place_inside, open_receptacle, close_receptacle, or clean any "
    "object. Call metric_map first, build an exact waypoint "
    "checklist from metric_map.inspection_waypoints, and sweep every inspection "
    "waypoint with navigate_to_waypoint then {waypoint_observe_tool}. Mark a waypoint "
    "complete only after that waypoint_id has a {waypoint_observe_response} response; "
    "{waypoint_observe_budget_rule}"
    "do not treat one empty observation as enough to complete an ambiguous waypoint "
    "or target search. If a target query, visual candidate, anchor, or waypoint "
    "observation has incomplete public evidence, call adjust_camera or "
    "navigate_to_relative_pose and observe again only when a public tool asks for it or "
    "when that successful bounded camera or pose change can produce materially new "
    "evidence; otherwise record the ambiguity and move on. Use "
    "resolve_target_query for any target-search, "
    "stale label, or open-ended map question and leave not-found claims tied to the "
    "returned public search budget. If a public tool returns required_next_tool or "
    "required_tool, call that tool before continuing. If a target candidate is "
    "visible_only, needs_observe, or names a generated target-inspection candidate, "
    "navigate only to the public inspection waypoint returned by metric_map, "
    "resolve_target_query, or tool recovery.{target_candidate_recovery_rule} "
    "{camera_grounded_rule}"
    "Use the returned observations and runtime_metric_map public anchors as "
    "map evidence only. Compare the checklist before done, visit any missing "
    "waypoint_id, and call done only after every metric_map.inspection_waypoints "
    "waypoint_id has been observed so runtime_metric_map.json and report.html are "
    "generated."
)

WORLD_LABELS_COMPACT_PROMPT = (
    "Compact action cadence for world-public-labels. Call metric_map, "
    "build the exact inspection_waypoints checklist, and for each unchecked waypoint call "
    "navigate_to_waypoint then observe. Treat visible_object_detections as public structured "
    "detections without destination oracle fields. Clean only public observed candidates whose "
    "candidate_state or tool response authorizes navigation. Use destination_policy, "
    "destination_options, runtime_metric_map.public_semantic_anchors, required_tool, and public "
    "recovery hints to choose placement; when the destination is named or stale, call "
    "resolve_target_query with operation=destination before choosing the public anchor. "
    "Prefer one short chain at a time: "
    "observe -> candidate decision -> navigate_to_object -> pick -> navigate_to_receptacle -> "
    "open? -> place/place_inside -> observe. Use place_inside for shelf/bookshelf/bookcase/"
    "shelving/fridge targets. If done reports pending_cleanup_candidates, clean only those "
    "public handles before another broad sweep. Call done when every public waypoint has an "
    "observe response and public pending candidates are resolved. Do not call scene_objects, "
    "read private scoring artifacts, invent fixture ids, or treat SDK turn completion as task "
    "success; only MCP done producing run_result.json counts."
)

CAMERA_LABELS_COMPACT_PROMPT = (
    "Compact action cadence for camera-grounded-labels. Call metric_map, "
    "build the exact inspection_waypoints checklist, and for each unchecked waypoint call "
    "navigate_to_waypoint then observe. For each raw FPV observation, call "
    "declare_visual_candidates with observation_id only and omit candidates so the configured "
    "camera labeler produces labels; do not ask for service URLs, credentials, image paths, or "
    "model hosts. Clean only returned public camera candidates whose candidate_state is "
    "navigation_authorized. Prefer one short chain at a time: observe -> declare labels -> "
    "candidate decision -> navigate_to_object -> pick -> navigate_to_receptacle -> open? -> "
    "place/place_inside -> observe. Use place_inside for shelf/bookshelf/bookcase/shelving/"
    "fridge targets. If done reports pending_cleanup_candidates, clean only those public "
    "handles before another broad sweep. Call done when every public waypoint has an observe "
    "response and public pending candidates are resolved. Do not call scene_objects, read "
    "private scoring artifacts, or treat SDK turn completion as task success; only MCP done "
    "producing run_result.json counts."
)

CAMERA_LABELS_COMPOSITE_COMPACT_PROMPT = (
    "Compact action cadence for camera-grounded-labels with the private SDK "
    "composite observation tool enabled. Call metric_map, build the exact "
    "inspection_waypoints checklist, and for each unchecked waypoint call "
    "navigate_to_waypoint then observe_camera_grounded_candidates instead of a "
    "separate observe plus declare_visual_candidates pair. Treat the response "
    "observation as the waypoint observe evidence and the response declaration "
    "as the camera-labeler candidate output; do not call "
    "declare_visual_candidates again for the same source_observation_id unless "
    "a public tool explicitly asks for it. Do not ask for service URLs, "
    "credentials, image paths, or model hosts. Clean only returned public camera "
    "candidates whose candidate_state is navigation_authorized. Prefer one "
    "short chain at a time: observe_camera_grounded_candidates -> candidate "
    "decision -> navigate_to_object -> pick -> navigate_to_receptacle -> "
    "open? -> place/place_inside -> observe_camera_grounded_candidates. Use "
    "place_inside for shelf/bookshelf/bookcase/shelving/fridge targets. If done "
    "reports pending_cleanup_candidates, clean only those public handles before "
    "another broad sweep. Call done when every public waypoint has observation "
    "evidence and public pending candidates are resolved. Do not call "
    "scene_objects, read private scoring artifacts, or treat SDK turn completion "
    "as task success; only MCP done producing run_result.json counts."
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
        "Compact action cadence for camera-raw-fpv. Call metric_map, build "
        "the exact inspection_waypoints checklist, and sweep public waypoints with "
        "navigate_to_waypoint then observe. Inspect raw FPV image blocks directly; do not expect "
        f"structured labels. At each waypoint, use at most {observe_budget} observe response(s). "
        "Until the required cleanup chains succeed, scan each waypoint from "
        f"up to {observe_budget} materially distinct robot-body headings: after the initial "
        "observe, when the current frame has no fresh actionable candidate, call "
        "navigate_to_relative_pose(forward_m=0, lateral_m=0, yaw_delta_deg=90) then observe. "
        "Stop rotating that waypoint when a heading repeats, the observation budget is reached, "
        "or the cleanup gate is met; after the gate is met, use one observe response for each "
        "remaining waypoint. Count post-placement observations within the same waypoint budget. "
        "When a waypoint has not produced a public cleanup_recommended=true candidate by its "
        "final distinct heading, make that final observation the bounded overlap probe: call "
        "adjust_camera(yaw_delta_deg=45, pitch_delta_deg=20) exactly once, then observe. This "
        "probe counts within the waypoint observation budget. "
        "Choose at most one fresh high-confidence cleanup "
        "candidate per raw FPV observation and stay within the run budget of "
        f"{candidate_budget} raw-FPV candidate attempts. Never retry the same "
        "source_observation_id/category/region or visual-candidate id after a public failure. "
        + raw_fpv_inline_candidate_instruction()
        + " Omit source_fixture_id with Base Metric Map context. Use "
        "navigate_to_visual_candidate -> pick -> navigate_to_receptacle -> open? -> "
        "place/place_inside when grounding succeeds, then observe once before choosing another "
        "candidate. Use place_inside for shelf/bookshelf/bookcase/shelving/fridge targets. If "
        "grounding is unresolved, record the public failure, move to another waypoint, or stop "
        "after the budget is exhausted; do not loop until provider context failure. Do not "
        "pre-register raw-FPV candidates with declare_visual_candidates. "
        f"Clean up to {cleanup_count} grounded visual candidates when possible. Call done only "
        "after every public waypoint has an observe response and successful cleanup chains meet "
        "the public gate, or after the bounded raw-FPV profile has no safe public candidate "
        f"remaining. If done reports blockers, retry done at most {done_budget} time(s) after "
        "resolving public blockers. Do not call scene_objects, read private scoring artifacts, "
        "persist raw image payloads, or treat SDK turn completion as task success; only MCP done "
        "producing run_result.json counts."
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
        prompt = OPEN_ENDED_TASK_RULES
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
        prompt = CAMERA_LABELS_COMPACT_PROMPT
        if camera_grounded_composite_tools:
            prompt = CAMERA_LABELS_COMPOSITE_COMPACT_PROMPT
    elif profile == "world-public-labels":
        prompt = WORLD_LABELS_COMPACT_PROMPT
    else:
        prompt = COMMON_WAYPOINT_RULES + COMMON_CLEANUP_RULES
    prompt = f"{prompt} {OPERATOR_STEER_CHECKPOINT_RULES}"
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
    prompt = CUSTOM_PREFIX + MAP_BUILD_RULES.format(task=task, **cadence)
    prompt += " " + _map_build_scan_profile_prompt(
        selected_scan_profile.to_payload(),
        max_observe_per_waypoint=max_observe_per_waypoint,
        observe_tool=cadence["waypoint_observe_tool"],
    )
    prompt += " " + OPERATOR_STEER_CHECKPOINT_RULES
    if profile == "camera-raw-fpv":
        prompt = (
            prompt + " This is the raw-FPV map-build lane: inspect each raw FPV image block "
            "returned by observe, record only public map evidence, and do not declare "
            "cleanup candidates."
        )
    elif profile == "world-public-labels":
        prompt = (
            prompt + " Treat visible_object_detections as structured public detections without "
            "destination oracle fields; use them only as map labels."
        )
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
            "waypoint_observe_response": "observe_camera_grounded_candidates",
            "waypoint_observe_budget_rule": observe_budget,
            "target_candidate_recovery_rule": _map_build_target_candidate_recovery_rule(
                max_observe_per_waypoint=max_observe_per_waypoint,
                observe_tool="observe_camera_grounded_candidates",
            ),
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
            "waypoint_observe_response": "observe",
            "waypoint_observe_budget_rule": observe_budget,
            "target_candidate_recovery_rule": _map_build_target_candidate_recovery_rule(
                max_observe_per_waypoint=max_observe_per_waypoint,
                observe_tool="observe",
            ),
            "camera_grounded_rule": (
                "For camera-grounded-labels, call declare_visual_candidates for each raw FPV "
                "observation with observation_id only and omit candidates so the configured "
                "camera labeler labels the frame. "
            ),
        }
    return {
        "waypoint_observe_tool": "observe",
        "waypoint_observe_response": "observe",
        "waypoint_observe_budget_rule": observe_budget,
        "target_candidate_recovery_rule": _map_build_target_candidate_recovery_rule(
            max_observe_per_waypoint=max_observe_per_waypoint,
            observe_tool="observe",
        ),
        "camera_grounded_rule": "",
    }


def _map_build_target_candidate_recovery_rule(
    *,
    max_observe_per_waypoint: int | None,
    observe_tool: str,
) -> str:
    if max_observe_per_waypoint is not None and max(1, int(max_observe_per_waypoint)) == 1:
        return (
            " If that waypoint_id has already used its preferred observation budget, "
            "record the target-candidate ambiguity as public map evidence and move on "
            "unless a public tool requests a re-observation or a successful bounded "
            f"camera, pose, or world-state change makes one more {observe_tool} call "
            "materially useful."
        )
    return f" Then call {observe_tool} again."


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
