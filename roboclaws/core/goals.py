"""Goal contracts shared by launch and product runtimes."""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from roboclaws.core.json_sources import parse_json_object_text, read_json_object
from roboclaws.core.task_intents import (
    GOAL_SCOPE_AGENT_DECLARED,
    GOAL_SCOPE_PROMPT_SCOPED,
    GOAL_SCOPE_WHOLE_ROOM,
    TaskIntentSpec,
)
from roboclaws.core.task_specs import TaskSurfaceSpec

GOAL_CONTRACT_SCHEMA = "roboclaws_goal_contract_v1"
AGENT_COMPLETION_CLAIM_SCHEMA = "roboclaws_agent_completion_claim_v1"


@dataclass(frozen=True)
class GoalContract:
    """Normalized, run-specific goal contract."""

    schema: str
    raw_prompt: str
    normalized_goal: str
    surface: str
    intent: str
    goal_scope: str
    assumptions: tuple[str, ...]
    tool_plan: tuple[str, ...]
    success_criteria: tuple[str, ...]
    required_capabilities: tuple[str, ...] = ()
    clarification_needed: bool = False
    clarification_question: str = ""
    safety_notes: tuple[str, ...] = ()

    def to_payload(self) -> dict[str, Any]:
        """Return a JSON-serializable payload."""

        return asdict(self)

    def to_json(self) -> str:
        """Serialize the contract as stable JSON."""

        return json.dumps(self.to_payload(), ensure_ascii=False, sort_keys=True)


def normalize_goal_contract(
    *,
    surface: TaskSurfaceSpec,
    intent: TaskIntentSpec,
    raw_prompt: str = "",
    required_capabilities: tuple[str, ...] = (),
) -> GoalContract:
    """Build the deterministic first-slice goal contract for a launch."""

    prompt = _clean_text(raw_prompt)
    goal_scope = _goal_scope_for_intent(intent.intent_id, prompt)
    normalized_goal = _normalized_goal(intent.intent_id, prompt)
    return GoalContract(
        schema=GOAL_CONTRACT_SCHEMA,
        raw_prompt=prompt,
        normalized_goal=normalized_goal,
        surface=surface.surface_id,
        intent=intent.intent_id,
        goal_scope=goal_scope,
        assumptions=_assumptions_for_intent(intent.intent_id, prompt),
        tool_plan=_tool_plan_for_intent(intent.intent_id),
        success_criteria=_success_criteria_for_intent(intent.intent_id, prompt),
        required_capabilities=required_capabilities,
        clarification_needed=False,
        clarification_question="",
        safety_notes=_safety_notes_for_surface(surface.surface_id),
    )


def goal_contract_from_json(value: str | None) -> GoalContract | None:
    """Parse a goal contract from a JSON string."""

    text = str(value or "").strip()
    if not text:
        return None
    payload = parse_json_object_text(text, label="goal contract", source="inline JSON")
    return goal_contract_from_payload(payload)


def goal_contract_from_file(path: str | Path | None) -> GoalContract | None:
    """Read a goal contract JSON file if a path was supplied."""

    if path is None or str(path) == "":
        return None
    return goal_contract_from_payload(read_json_object(Path(path), label="goal contract"))


def goal_contract_from_payload(payload: dict[str, Any]) -> GoalContract:
    """Normalize a JSON payload into a ``GoalContract`` instance."""

    return GoalContract(
        schema=str(payload.get("schema") or GOAL_CONTRACT_SCHEMA),
        raw_prompt=str(payload.get("raw_prompt") or ""),
        normalized_goal=str(payload.get("normalized_goal") or ""),
        surface=str(payload.get("surface") or ""),
        intent=str(payload.get("intent") or ""),
        goal_scope=str(payload.get("goal_scope") or GOAL_SCOPE_AGENT_DECLARED),
        assumptions=tuple(str(item) for item in payload.get("assumptions") or ()),
        tool_plan=tuple(str(item) for item in payload.get("tool_plan") or ()),
        success_criteria=tuple(str(item) for item in payload.get("success_criteria") or ()),
        required_capabilities=tuple(
            str(item) for item in payload.get("required_capabilities") or ()
        ),
        clarification_needed=bool(payload.get("clarification_needed")),
        clarification_question=str(payload.get("clarification_question") or ""),
        safety_notes=tuple(str(item) for item in payload.get("safety_notes") or ()),
    )


def write_goal_contract(path: Path, contract: GoalContract) -> None:
    """Write a goal contract artifact."""

    path.write_text(
        json.dumps(contract.to_payload(), indent=2, ensure_ascii=False, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def completion_claim_from_done_reason(
    reason: str,
    *,
    goal_contract: GoalContract,
) -> dict[str, Any]:
    """Build a structured completion claim from the MCP ``done`` reason.

    This first slice keeps the public done tool signature stable while still
    requiring the report artifact to carry a structured claim for every intent.
    """

    summary = _clean_text(reason) or f"Agent declared {goal_contract.intent} goal complete."
    return {
        "schema": AGENT_COMPLETION_CLAIM_SCHEMA,
        "completion_summary": summary,
        "why_done": summary,
        "evidence_used": [
            "public MCP tool trace",
            "agent-facing run artifacts",
            f"goal_contract:{goal_contract.intent}",
        ],
        "remaining_risks": [],
    }


def _clean_text(value: str | None) -> str:
    return " ".join(str(value or "").split())


def _goal_scope_for_intent(intent_id: str, prompt: str) -> str:
    if intent_id == "cleanup":
        return GOAL_SCOPE_PROMPT_SCOPED if prompt else GOAL_SCOPE_WHOLE_ROOM
    if intent_id == "map-build":
        return GOAL_SCOPE_WHOLE_ROOM
    return GOAL_SCOPE_AGENT_DECLARED


def _normalized_goal(intent_id: str, prompt: str) -> str:
    if prompt:
        if intent_id == "cleanup":
            return f"Clean the household world within this user-scoped request: {prompt}"
        if intent_id == "map-build":
            return f"Build public runtime map evidence for this request: {prompt}"
        if intent_id == "open-ended":
            return prompt
        return prompt
    defaults = {
        "cleanup": "Clean up the household world.",
        "map-build": "Build public runtime map evidence for the household world.",
        "planner-proof": "Produce planner-proof evidence.",
    }
    return defaults.get(intent_id, f"Complete the {intent_id} goal.")


def _assumptions_for_intent(intent_id: str, prompt: str) -> tuple[str, ...]:
    assumptions = ["Use only public agent-facing evidence and public MCP tool responses."]
    if intent_id == "cleanup" and prompt:
        assumptions.append("The prompt narrows cleanup scope but remains a cleanup intent.")
    if intent_id == "open-ended":
        assumptions.append("The agent declares task-specific completion evidence before done.")
    if intent_id == "map-build":
        assumptions.append("Manipulation tools are out of scope for map-build.")
    return tuple(assumptions)


def _tool_plan_for_intent(intent_id: str) -> tuple[str, ...]:
    if intent_id == "cleanup":
        return (
            "metric_map and runtime_metric_map public anchors",
            "navigate_to_waypoint/observe",
            "resolve_target_query and public target candidates",
            "pick/place if needed",
            "done",
        )
    if intent_id == "map-build":
        return (
            "metric_map inspection waypoints",
            "navigate_to_waypoint/observe sweep",
            "runtime_metric_map public evidence",
            "done",
        )
    if intent_id == "open-ended":
        return (
            "metric_map as needed",
            "resolve_target_query and observe as needed",
            "task-relevant public action tools if needed",
            "done with claim",
        )
    return ("run intent-specific tools", "done")


def _success_criteria_for_intent(intent_id: str, prompt: str) -> tuple[str, ...]:
    if intent_id == "cleanup":
        criteria = [
            "Structured completion claim is present.",
            "Cleanup report artifacts are written.",
        ]
        if prompt:
            criteria.append("Cleanup actions stay within the prompt-scoped request.")
        else:
            criteria.append("Whole-room cleanup gates pass for the selected evidence lane.")
        return tuple(criteria)
    if intent_id == "map-build":
        return (
            "Structured completion claim is present.",
            "runtime_metric_map.json is written.",
            "No cleanup/manipulation-only success gate is required.",
        )
    if intent_id == "open-ended":
        return (
            "Structured completion claim is present.",
            "Report and trace artifacts are written.",
            "Cleanup-only sweep/count/pick-place mandates are not required unless the "
            "goal asks for cleanup.",
        )
    return ("Structured completion claim is present.", "Intent-specific artifacts are written.")


def _safety_notes_for_surface(surface_id: str) -> tuple[str, ...]:
    if surface_id == "household-world":
        return (
            "Do not read private generated mess truth or private scoring artifacts.",
            "Follow public tool safety and error responses.",
        )
    return ("Follow public tool safety and error responses.",)
