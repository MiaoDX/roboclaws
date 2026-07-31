from __future__ import annotations

from pathlib import Path
from typing import Any

NAVIGATE_TO_OBJECT_PHASE = "navigate_to_object"
NAVIGATE_TO_VISUAL_CANDIDATE_TOOL = "navigate_to_visual_candidate"
PICK_PHASE = "pick"
NAVIGATE_TO_RECEPTACLE_PHASE = "navigate_to_receptacle"
OPEN_RECEPTACLE_PHASE = "open_receptacle"
PLACE_PHASE = "place"
PLACE_INSIDE_PHASE = "place_inside"
CLOSE_RECEPTACLE_PHASE = "close_receptacle"
OBJECT_DONE_PHASE = "object_done"

CANONICAL_BASE_CLEANUP_PHASES = (
    NAVIGATE_TO_OBJECT_PHASE,
    PICK_PHASE,
    NAVIGATE_TO_RECEPTACLE_PHASE,
)
CANONICAL_SURFACE_CLEANUP_PHASES = (*CANONICAL_BASE_CLEANUP_PHASES, PLACE_PHASE)
CANONICAL_INSIDE_CLEANUP_PHASES = (
    *CANONICAL_BASE_CLEANUP_PHASES,
    OPEN_RECEPTACLE_PHASE,
    PLACE_INSIDE_PHASE,
    CLOSE_RECEPTACLE_PHASE,
)
CANONICAL_CLEANUP_TOOL_ORDER = (
    *CANONICAL_BASE_CLEANUP_PHASES,
    OPEN_RECEPTACLE_PHASE,
    PLACE_PHASE,
    PLACE_INSIDE_PHASE,
    CLOSE_RECEPTACLE_PHASE,
)
PLACE_CLEANUP_PHASES = (PLACE_PHASE, PLACE_INSIDE_PHASE)
SEMANTIC_RESPONSE_PHASES = (
    *CANONICAL_BASE_CLEANUP_PHASES,
    NAVIGATE_TO_VISUAL_CANDIDATE_TOOL,
    OPEN_RECEPTACLE_PHASE,
    PLACE_PHASE,
    PLACE_INSIDE_PHASE,
    CLOSE_RECEPTACLE_PHASE,
    OBJECT_DONE_PHASE,
)
SEMANTIC_RESPONSE_PHASE_SET = frozenset(SEMANTIC_RESPONSE_PHASES)
FOCUSED_SEMANTIC_PHASES = (
    *CANONICAL_BASE_CLEANUP_PHASES,
    OPEN_RECEPTACLE_PHASE,
    PLACE_PHASE,
    PLACE_INSIDE_PHASE,
    CLOSE_RECEPTACLE_PHASE,
)
FOCUSED_SEMANTIC_ACTION_PREFIXES = tuple(f"{phase} " for phase in FOCUSED_SEMANTIC_PHASES)

SEMANTIC_LOOP_VARIANT = "navigate-pick-navigate-open-place-close"
SEMANTIC_LOOP_DISPLAY_TEXT = "nav, pick, nav, open when needed, place, close when needed"
SEMANTIC_LOOP_DISPLAY_NOTE = f"Canonical cleanup loop: {SEMANTIC_LOOP_DISPLAY_TEXT}."
ROBOT_VIEW_VARIANT = "molmospaces-rby1m-fpv-topdown-chase-verify"

SEMANTIC_SUBPHASE_LABELS = {
    NAVIGATE_TO_OBJECT_PHASE: ("nav", "object"),
    PICK_PHASE: ("pick", "object"),
    NAVIGATE_TO_RECEPTACLE_PHASE: ("nav", "target"),
    OPEN_RECEPTACLE_PHASE: ("open", "target"),
    PLACE_PHASE: ("place", "surface"),
    PLACE_INSIDE_PHASE: ("place", "inside"),
    CLOSE_RECEPTACLE_PHASE: ("close", "target"),
}
CANONICAL_DISPLAY_SUBPHASES = tuple(
    SEMANTIC_SUBPHASE_LABELS[phase] for phase in CANONICAL_BASE_CLEANUP_PHASES
)
CANONICAL_PLACE_DISPLAY_SUBPHASES = tuple(
    SEMANTIC_SUBPHASE_LABELS[phase] for phase in PLACE_CLEANUP_PHASES
)


def canonical_cleanup_tool_sequence(tools: Any) -> list[str]:
    """Return cleanup tools in report/command semantic order, preserving unknowns."""
    if isinstance(tools, str):
        raw_tools = tools.split(",")
    else:
        raw_tools = list(tools or [])
    seen = set()
    requested = []
    for item in raw_tools:
        tool = str(item).strip()
        if not tool or tool in seen:
            continue
        seen.add(tool)
        requested.append(tool)
    requested_set = set(requested)
    ordered = [tool for tool in CANONICAL_CLEANUP_TOOL_ORDER if tool in requested_set]
    ordered.extend(tool for tool in requested if tool not in CANONICAL_CLEANUP_TOOL_ORDER)
    return ordered


def semantic_substeps(
    trace_events: list[dict[str, Any]],
    receptacles_by_id: dict[str, dict[str, Any]],
) -> list[dict[str, Any]]:
    steps_by_object: dict[str, dict[str, Any]] = {}
    order: list[str] = []
    active_object_id: str | None = None

    for event in trace_events:
        if event.get("event") != "response":
            continue
        response = event.get("response")
        if not isinstance(response, dict):
            continue
        phase = semantic_phase_for_tool(str(event.get("tool", "")))
        if phase not in SEMANTIC_RESPONSE_PHASE_SET:
            continue
        object_id, active_object_id = _semantic_object_context(
            phase,
            response,
            active_object_id,
        )

        if not object_id:
            continue
        object_id = str(object_id)
        if object_id not in steps_by_object:
            order.append(object_id)
            steps_by_object[object_id] = {
                "object_id": object_id,
                "source_receptacle_id": "",
                "target_receptacle_id": "",
                "target_receptacle_category": "",
                "steps": [],
            }
        item = steps_by_object[object_id]
        if response.get("source_receptacle_id"):
            item["source_receptacle_id"] = str(response["source_receptacle_id"])
        if response.get("receptacle_id"):
            target_id = str(response["receptacle_id"])
            item["target_receptacle_id"] = target_id
            item["target_receptacle_category"] = receptacle_category(
                receptacles_by_id,
                target_id,
            )
        item["steps"].append(semantic_step(phase, response))

    return [steps_by_object[object_id] for object_id in order]


def _semantic_object_context(
    phase: str,
    response: dict[str, Any],
    active_object_id: str | None,
) -> tuple[str | None, str | None]:
    object_id = response.get("object_id") or active_object_id
    if phase == NAVIGATE_TO_OBJECT_PHASE and response.get("object_id"):
        object_id = str(response["object_id"])
        active_object_id = object_id
    elif phase == PICK_PHASE and response.get("ok") and response.get("object_id"):
        object_id = str(response["object_id"])
        active_object_id = object_id
    elif phase in {PLACE_PHASE, CLOSE_RECEPTACLE_PHASE} and response.get("ok"):
        active_object_id = None
    elif phase == OBJECT_DONE_PHASE and response.get("object_id"):
        object_id = str(response["object_id"])
    return str(object_id) if object_id else None, active_object_id


def semantic_phase_for_tool(tool: str) -> str:
    if tool == NAVIGATE_TO_VISUAL_CANDIDATE_TOOL:
        return NAVIGATE_TO_OBJECT_PHASE
    return tool


def semantic_step(phase: str, response: dict[str, Any]) -> dict[str, Any]:
    return {
        "phase": phase,
        "tool": response.get("tool"),
        "ok": response.get("ok"),
        "status": response.get("status"),
        "error_reason": response.get("error_reason"),
        "object_id": response.get("object_id"),
        "receptacle_id": response.get("receptacle_id"),
        "source_receptacle_id": response.get("source_receptacle_id"),
        "location_id": response.get("location_id"),
        "contained_in": response.get("contained_in"),
        "location_relation": response.get("location_relation"),
        "opened": response.get("opened"),
        "closed": response.get("closed"),
        "matches_expected_location": response.get("matches_expected_location"),
        "primitive_provenance": response.get("primitive_provenance"),
        "planner_backed": response.get("planner_backed"),
        "strict_proof_eligible": response.get("strict_proof_eligible"),
        "planner_primitive_evidence": response.get("planner_primitive_evidence"),
        "placement_diagnostic": response.get("placement_diagnostic"),
        "state_sync_provenance": response.get("state_sync_provenance"),
        "state_mutation": response.get("state_mutation"),
    }


def display_semantic_subphase(phase: Any) -> dict[str, str] | None:
    """Return the report-facing label for one raw semantic tool phase."""
    phase_name = str(phase or "")
    label = SEMANTIC_SUBPHASE_LABELS.get(phase_name)
    if label is None:
        return None
    return {
        "phase": phase_name,
        "label": label[0],
        "detail": label[1],
        "text": label[0],
    }


def semantic_subphase_text(phase: Any) -> str:
    """Return a compact report label, falling back to the raw phase name."""
    displayed = display_semantic_subphase(phase)
    if displayed is not None:
        return displayed["text"]
    return str(phase or "")


def display_semantic_subphases(steps: list[dict[str, Any]]) -> list[dict[str, str]]:
    """Return the report-facing cleanup loop labels for raw semantic tool steps."""
    displayed = []
    for step in steps:
        item = display_semantic_subphase(step.get("phase"))
        if item is not None:
            displayed.append(item)
    return displayed


def cleanup_plan_from_semantic_substeps(
    substeps: list[dict[str, Any]],
) -> list[dict[str, str]]:
    plan = []
    for item in substeps:
        target = str(item.get("target_receptacle_id") or "")
        if not target:
            continue
        plan.append(
            {
                "object_id": str(item["object_id"]),
                "receptacle_id": target,
                "reason": "external agent selected semantic cleanup target",
            }
        )
    return plan


def semantic_diagnostics(
    trace_events: list[dict[str, Any]],
    substeps: list[dict[str, Any]],
    done_response: dict[str, Any],
) -> dict[str, Any]:
    stale_reference_errors = 0
    semantic_order_errors = 0
    attempted_semantic_substeps = 0
    object_done_count = 0
    fridge_inside_sequence_ok = True
    complete_objects = 0
    for item in substeps:
        attempted_phases = [str(step.get("phase")) for step in item.get("steps", [])]
        phases = successful_semantic_phases(item.get("steps", []))
        attempted_semantic_substeps += len(attempted_phases)
        if OBJECT_DONE_PHASE in phases:
            object_done_count += 1
        if has_complete_semantic_sequence(phases):
            complete_objects += 1
        if item.get("target_receptacle_category") == "Fridge":
            fridge_inside_sequence_ok = fridge_inside_sequence_ok and fridge_sequence_ok(phases)

    for event in trace_events:
        response = event.get("response")
        if (
            event.get("event") == "response"
            and isinstance(response, dict)
            and response.get("error_reason") == "stale_reference"
        ):
            stale_reference_errors += 1
        if (
            event.get("event") == "response"
            and isinstance(response, dict)
            and response.get("error_reason") == "semantic_order"
        ):
            semantic_order_errors += 1
    recovered_semantic_order_errors, unrecovered_semantic_order_errors = (
        _semantic_order_recovery_counts(substeps, total_errors=semantic_order_errors)
    )
    duplicate_navigation = duplicate_post_place_navigations(trace_events)
    score = done_response.get("score", {})
    return {
        "stale_reference_errors": stale_reference_errors,
        "semantic_order_errors": semantic_order_errors,
        "semantic_order_recovered_errors": recovered_semantic_order_errors,
        "semantic_order_unrecovered_errors": unrecovered_semantic_order_errors,
        "duplicate_post_place_navigation_count": len(duplicate_navigation),
        "duplicate_post_place_navigation_handles": sorted(
            {str(item["object_id"]) for item in duplicate_navigation}
        ),
        "duplicate_post_place_navigation_events": duplicate_navigation[:10],
        "premature_done": int(score.get("restored_count", 0)) < int(score.get("total_targets", 0)),
        "object_done_count": object_done_count,
        "attempted_semantic_substeps": attempted_semantic_substeps,
        "complete_semantic_substep_objects": complete_objects,
        "fridge_inside_sequence_ok": fridge_inside_sequence_ok,
    }


def _semantic_order_recovery_counts(
    substeps: list[dict[str, Any]],
    *,
    total_errors: int,
) -> tuple[int, int]:
    recovered = 0
    unrecovered = 0
    covered = 0
    for item in substeps:
        steps = item.get("steps", [])
        item_errors = sum(
            1
            for step in steps
            if isinstance(step, dict) and step.get("error_reason") == "semantic_order"
        )
        if item_errors == 0:
            continue
        covered += item_errors
        phases = successful_semantic_phases(steps)
        if has_complete_semantic_sequence(phases):
            recovered += item_errors
        else:
            unrecovered += item_errors
    untracked_errors = max(0, total_errors - covered)
    return recovered, unrecovered + untracked_errors


def duplicate_post_place_navigations(trace_events: list[dict[str, Any]]) -> list[dict[str, Any]]:
    placed_handles: set[str] = set()
    duplicates: list[dict[str, Any]] = []
    for index, event in enumerate(trace_events, start=1):
        if event.get("event") != "response":
            continue
        response = event.get("response")
        if not isinstance(response, dict) or response.get("ok") is not True:
            continue
        tool = str(event.get("tool") or response.get("tool") or "")
        phase = semantic_phase_for_tool(tool)
        object_id = str(response.get("object_id") or "")
        if phase == NAVIGATE_TO_OBJECT_PHASE and object_id in placed_handles:
            duplicates.append(
                {
                    "index": index,
                    "tool": tool,
                    "object_id": object_id,
                    "phase": phase,
                }
            )
        if phase in PLACE_CLEANUP_PHASES and object_id:
            placed_handles.add(object_id)
    return duplicates


def has_complete_semantic_sequence(phases: list[str]) -> bool:
    phases = _dedupe_adjacent_object_navigation_phases(phases)
    if phases[: len(CANONICAL_BASE_CLEANUP_PHASES)] != list(CANONICAL_BASE_CLEANUP_PHASES):
        return False
    completed_phases = set(phases[len(CANONICAL_BASE_CLEANUP_PHASES) :])
    return bool(completed_phases.intersection(PLACE_CLEANUP_PHASES))


def _dedupe_adjacent_object_navigation_phases(phases: list[str]) -> list[str]:
    normalized: list[str] = []
    for phase in phases:
        if (
            phase == NAVIGATE_TO_OBJECT_PHASE
            and normalized
            and normalized[-1] == NAVIGATE_TO_OBJECT_PHASE
        ):
            continue
        normalized.append(phase)
    return normalized


def successful_semantic_phases(steps: list[dict[str, Any]]) -> list[str]:
    """Return phases from successful semantic tool responses, excluding failed retries."""
    return [str(step.get("phase")) for step in steps if step.get("ok") is True]


def fridge_sequence_ok(phases: list[str]) -> bool:
    try:
        open_index = phases.index(OPEN_RECEPTACLE_PHASE)
        place_index = phases.index(PLACE_INSIDE_PHASE)
        close_index = phases.index(CLOSE_RECEPTACLE_PHASE)
    except ValueError:
        return False
    return open_index < place_index < close_index


def annotate_focus_visual_grounding(focus: dict[str, Any] | None) -> dict[str, Any] | None:
    """Normalize robot-view focus visibility into report/checker grounding statuses."""
    if not isinstance(focus, dict):
        return focus
    if not focus.get("has_focus"):
        return focus
    annotated = dict(focus)
    for key in ("fpv_visibility", "visibility"):
        visibility = annotated.get(key)
        if not isinstance(visibility, dict):
            continue
        updated = dict(visibility)
        status = str(updated.get("status") or "")
        if status != "segmentation_unavailable":
            grounding = visual_grounding_status(annotated, updated)
            updated["status"] = grounding
            updated["visual_grounding_status"] = grounding
            if grounding == "weak_object_visibility":
                updated.setdefault(
                    "evidence_note",
                    "Focused object has zero pixels in this robot-view frame.",
                )
            elif grounding == "contained_inside":
                updated.setdefault(
                    "evidence_note",
                    "Object is semantically contained inside the focused receptacle.",
                )
        annotated[key] = updated
    return annotated


def visual_grounding_status(focus: dict[str, Any], visibility: dict[str, Any]) -> str:
    """Return ok, weak_object_visibility, or contained_inside for a focused object."""
    receptacle_id = optional_str(focus.get("receptacle_id"))
    contained_in = optional_str(focus.get("object_contained_in"))
    relation = str(focus.get("object_location_relation") or "")
    if receptacle_id and contained_in == receptacle_id and relation == "inside":
        text = f"{focus.get('receptacle_label', '')} {focus.get('receptacle_category', '')}".lower()
        if "fridge" in text or "refrigerator" in text:
            return "contained_inside"
    if not (focus.get("object_id") or focus.get("object_body_name") or focus.get("object_label")):
        return "ok"
    return "ok" if _pixel_count(visibility.get("object_pixels")) > 0 else "weak_object_visibility"


def primitive_provenance_counts(trace_events: list[dict[str, Any]]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for event in trace_events:
        response = event.get("response")
        if not isinstance(response, dict):
            continue
        if isinstance(response.get("semantic_steps"), list):
            for step in response.get("semantic_steps") or []:
                if not isinstance(step, dict):
                    continue
                provenance = step.get("primitive_provenance")
                if provenance:
                    counts[str(provenance)] = counts.get(str(provenance), 0) + 1
            continue
        provenance = response.get("primitive_provenance")
        if provenance:
            counts[str(provenance)] = counts.get(str(provenance), 0) + 1
    return counts


def receptacle_category(receptacles_by_id: dict[str, dict[str, Any]], receptacle_id: str) -> str:
    receptacle = receptacles_by_id.get(receptacle_id, {})
    category = str(receptacle.get("category", ""))
    if category:
        return category
    name = str(receptacle.get("name", "")).lower()
    if "fridge" in name or "refrigerator" in name or "fridge" in receptacle_id.lower():
        return "Fridge"
    return ""


def label_suffix(prefix: str, value: str | None) -> str:
    if not value:
        return prefix
    safe_value = "".join(char if char.isalnum() or char in {"_", "-"} else "_" for char in value)
    return f"{prefix}_{safe_value}"


def optional_str(value: Any) -> str | None:
    return None if value is None else str(value)


def response_or_request_id(
    response: dict[str, Any],
    request: dict[str, Any],
    *keys: str,
) -> str | None:
    for key in keys:
        value = response.get(key)
        if value:
            return str(value)
    for key in keys:
        value = request.get(key)
        if value:
            return str(value)
    return None


def _identity_optional_str(value: str | None) -> str | None:
    return value


def _pixel_count(value: Any) -> int:
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return 0


def relative_view_paths(output_dir: Path, views: dict[str, str]) -> dict[str, str]:
    relative = {}
    for key, value in views.items():
        path = Path(value)
        try:
            relative[key] = str(path.relative_to(output_dir))
        except ValueError:
            relative[key] = str(path)
    return relative
