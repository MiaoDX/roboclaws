"""Operator-console prompt previews for live agent routes."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from roboclaws.agents.prompts.household_cleanup import (
    render_kickoff_prompt,
    render_map_build_prompt,
)
from roboclaws.launch.catalog import LaunchError, resolve_surface_launch
from roboclaws.operator_console.launch_support import build_surface_launch_args
from roboclaws.operator_console.routes import ConsoleLaunchSelection

AGIBOT_MAP_BUILD_WRAPPER_SUMMARY = (
    "Agibot map-build adds a live-route wrapper that restricts the agent to public "
    "metric_map, navigate_to_waypoint, observe, and done behavior."
)
PROMPT_PREVIEW_ENV_KEYS = (
    "ROBOCLAWS_OPENAI_AGENTS_PERF_PROFILE",
    "ROBOCLAWS_OPENAI_AGENTS_RAW_FPV_CANDIDATE_BUDGET",
    "ROBOCLAWS_OPENAI_AGENTS_MAX_OBSERVE_PER_WAYPOINT",
    "ROBOCLAWS_OPENAI_AGENTS_DONE_RETRY_BUDGET",
    "ROBOCLAWS_OPENAI_AGENTS_CAMERA_GROUNDED_COMPOSITE_TOOLS",
)
PROMPT_PREVIEW_INT_ENV_KEYS = {
    "ROBOCLAWS_OPENAI_AGENTS_RAW_FPV_CANDIDATE_BUDGET": "raw_fpv_candidate_budget",
    "ROBOCLAWS_OPENAI_AGENTS_MAX_OBSERVE_PER_WAYPOINT": "max_observe_per_waypoint",
    "ROBOCLAWS_OPENAI_AGENTS_DONE_RETRY_BUDGET": "done_retry_budget",
}


@dataclass(frozen=True)
class PromptPreviewRequest:
    """Resolved prompt-preview inputs from the operator console."""

    intent_id: str = ""
    prompt: str = ""
    overrides: dict[str, str] | None = None
    env_overrides: dict[str, str] | None = None


def build_prompt_preview(
    route: ConsoleLaunchSelection,
    request: PromptPreviewRequest | None = None,
) -> dict[str, Any]:
    """Return the prompt text an operator should expect the route to send."""

    request = request or PromptPreviewRequest()
    selected_intent = str(request.intent_id or route.intent_id)
    raw_prompt = " ".join(str(request.prompt or "").split())
    operator_prompt = _operator_prompt(route, selected_intent, raw_prompt)
    overrides = {str(key): str(value) for key, value in (request.overrides or {}).items()}
    env_overrides = {str(key): str(value) for key, value in (request.env_overrides or {}).items()}
    lane = route.evidence_lane
    target_cleanup_count = _target_cleanup_count(
        selected_intent=selected_intent,
        evidence_lane=lane,
        scenario_setup=overrides.get("scenario_setup") or route.scenario_setup,
        relocation_count=overrides.get("relocation_count"),
    )
    raw_budget = _nonnegative_int_env(
        env_overrides.get("ROBOCLAWS_OPENAI_AGENTS_RAW_FPV_CANDIDATE_BUDGET"),
        "ROBOCLAWS_OPENAI_AGENTS_RAW_FPV_CANDIDATE_BUDGET",
        default=24,
    )
    max_observe = _nonnegative_int_env(
        env_overrides.get("ROBOCLAWS_OPENAI_AGENTS_MAX_OBSERVE_PER_WAYPOINT"),
        "ROBOCLAWS_OPENAI_AGENTS_MAX_OBSERVE_PER_WAYPOINT",
        default=1,
    )
    done_retry_budget = _nonnegative_int_env(
        env_overrides.get("ROBOCLAWS_OPENAI_AGENTS_DONE_RETRY_BUDGET"),
        "ROBOCLAWS_OPENAI_AGENTS_DONE_RETRY_BUDGET",
        default=1,
    )
    composite_tools = _truthy(
        env_overrides.get("ROBOCLAWS_OPENAI_AGENTS_CAMERA_GROUNDED_COMPOSITE_TOOLS")
    )

    kickoff_prompt = operator_prompt
    source = "operator-task"
    if route.surface == "household-world":
        if selected_intent == "map-build":
            kickoff_prompt = render_map_build_prompt(
                lane,
                operator_prompt,
                operator_session_context_json=overrides.get("operator_session_context_json", ""),
            )
            source = "household-map-build"
        elif selected_intent in {"cleanup", "open-ended"}:
            kickoff_prompt = render_kickoff_prompt(
                lane,
                task=operator_prompt,
                target_cleanup_count=target_cleanup_count,
                intent=selected_intent,
                goal_contract=_goal_contract(route, selected_intent, raw_prompt, overrides),
                raw_fpv_candidate_budget=raw_budget,
                max_observe_per_waypoint=max_observe,
                done_retry_budget=done_retry_budget,
                camera_grounded_composite_tools=composite_tools,
                operator_session_context_json=overrides.get("operator_session_context_json", ""),
            )
            source = "household-world"

    wrapper_notes = _wrapper_notes(route)
    return {
        "operator_prompt": operator_prompt,
        "raw_operator_prompt": raw_prompt,
        "agent_kickoff_prompt": kickoff_prompt,
        "prompt": kickoff_prompt,
        "source": source,
        "intent": selected_intent,
        "evidence_lane": lane,
        "target_cleanup_count": target_cleanup_count,
        "wrapper_notes": wrapper_notes,
        "summary": _summary(source=source, wrapper_notes=wrapper_notes),
    }


def _operator_prompt(route: ConsoleLaunchSelection, intent_id: str, prompt: str) -> str:
    if prompt:
        return prompt
    return route.task_prompt_default or _default_prompt_for_intent(intent_id)


def _default_prompt_for_intent(intent_id: str) -> str:
    if intent_id == "map-build":
        return "帮我建立这个房间的 Runtime Metric Map"
    if intent_id == "open-ended":
        return "在这个场景中完成开放性导航任务，并报告你看到的证据。"
    return "帮我收拾这个房间"


def prompt_preview_env(
    env: dict[str, str] | None = None,
    env_overrides: dict[str, str] | None = None,
) -> dict[str, str]:
    """Return non-secret env values that affect prompt rendering."""

    preview_env = {
        key: str(value) for key in PROMPT_PREVIEW_ENV_KEYS if env and (value := env.get(key))
    }
    for key, value in (env_overrides or {}).items():
        if key in PROMPT_PREVIEW_ENV_KEYS and str(value) != "":
            preview_env[key] = str(value)
    validate_prompt_preview_env(preview_env)
    return preview_env


def validate_prompt_preview_env(env: dict[str, str]) -> None:
    """Fail aloud when prompt-affecting env values cannot be rendered faithfully."""

    for key, setting_name in PROMPT_PREVIEW_INT_ENV_KEYS.items():
        _nonnegative_int_env(env.get(key), key, setting_name=setting_name)


def _goal_contract(
    route: ConsoleLaunchSelection,
    intent_id: str,
    raw_prompt: str,
    overrides: dict[str, str],
) -> Any:
    args = build_surface_launch_args(
        route,
        selected_intent=intent_id,
        prompt=raw_prompt,
        overrides=overrides,
        require_route_overrides=False,
    )
    try:
        return resolve_surface_launch(args).goal_contract
    except LaunchError:
        return None


def _target_cleanup_count(
    *,
    selected_intent: str,
    evidence_lane: str,
    scenario_setup: str,
    relocation_count: str | None,
) -> int:
    if selected_intent != "cleanup":
        return 7
    count = _nonnegative_int_env(
        relocation_count
        if relocation_count not in {None, ""}
        else ("0" if scenario_setup == "baseline" else "5"),
        "relocation_count",
        setting_name="relocation_count",
    )
    if evidence_lane == "camera-raw-fpv":
        return max(1, (count * 7 + 9) // 10) if count else 1
    return max(1, count) if count else 1


def _nonnegative_int_env(
    value: str | None,
    key: str,
    *,
    default: int = 0,
    setting_name: str | None = None,
) -> int:
    if value is None or str(value).strip() == "":
        return default
    try:
        parsed = int(str(value).strip())
    except ValueError:
        name = setting_name or PROMPT_PREVIEW_INT_ENV_KEYS.get(key, key)
        raise ValueError(
            f"OpenAI Agents prompt preview setting {name} must be an integer"
        ) from None
    if parsed < 0:
        name = setting_name or PROMPT_PREVIEW_INT_ENV_KEYS.get(key, key)
        raise ValueError(f"OpenAI Agents prompt preview setting {name} must be non-negative")
    return parsed


def _truthy(value: str | None) -> bool:
    return str(value or "").strip() in {"1", "true", "True", "TRUE", "yes", "Yes", "YES", "on"}


def _wrapper_notes(route: ConsoleLaunchSelection) -> list[str]:
    notes: list[str] = []
    if route.world_id == "agibot-g2/map-12" and route.intent_id == "map-build":
        notes.append(AGIBOT_MAP_BUILD_WRAPPER_SUMMARY)
    return notes


def _summary(*, source: str, wrapper_notes: list[str]) -> str:
    parts = [f"{source} kickoff prompt"]
    if wrapper_notes:
        parts.append("plus live-route wrapper")
    return "; ".join(parts)
