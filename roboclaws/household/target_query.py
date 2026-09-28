from __future__ import annotations

import re
from typing import Any

TARGET_QUERY_RESOLUTION_SCHEMA = "target_query_resolution_v1"
_OBJECT_NAVIGATION_OPERATIONS = {"pick", "manipulate"}
_DESTINATION_NAVIGATION_OPERATIONS = {"destination", "place", "place_inside", "use"}


def resolve_target_query(
    runtime_metric_map: dict[str, Any],
    query: str,
    *,
    operation: str = "inspect",
    max_results: int = 8,
) -> dict[str, Any]:
    """Resolve a user or skill target query against public target candidates only."""

    normalized_query = _normalize_query(query)
    operation = str(operation or "inspect").strip().lower() or "inspect"
    public_candidates = [
        candidate
        for candidate in runtime_metric_map.get("target_candidates") or []
        if isinstance(candidate, dict)
    ]
    candidates = [
        _candidate_resolution_row(candidate, normalized_query, operation=operation)
        for candidate in filter_numbered_target_candidates(query, public_candidates)
    ]
    matches = [item for item in candidates if item["match_score"] > 0.0]
    matches.sort(
        key=lambda item: (
            item["actionable_for_operation"] is True,
            item["match_score"],
            _actionability_rank(item["target_actionability_status"]),
            float(item.get("confidence") or 0.0),
        ),
        reverse=True,
    )
    limited = matches[: max(1, int(max_results))]
    budget = dict(runtime_metric_map.get("target_search_summary") or {})
    exhausted = _public_budget_exhausted(budget)
    result = {
        "schema": TARGET_QUERY_RESOLUTION_SCHEMA,
        "query": str(query or ""),
        "normalized_query": normalized_query["compact"],
        "operation": operation,
        "status": "matched" if limited else "not_found",
        "candidate_count": len(public_candidates),
        "match_count": len(matches),
        "matches": limited,
        "best_match": limited[0] if limited else None,
        "public_search_budget": _public_search_budget_evidence(budget),
        "exhausted_public_search_budget": exhausted,
        "missing_target_reason": ""
        if limited
        else (
            "public_search_budget_exhausted" if exhausted else "no_public_candidate_matched_query"
        ),
        "private_truth_included": False,
        "recovery_instruction": (
            "Use matched public candidate ids, waypoint ids, anchor ids, object handles, "
            "or destination options. If no actionable match exists, continue public "
            "waypoint/camera search before claiming not found; never recover by reading "
            "private fixture ids or hidden inventory."
        ),
    }
    return result


def summarize_required_target_queries(
    runtime_metric_map: dict[str, Any],
    queries: list[str],
    *,
    operation: str = "inspect",
) -> dict[str, Any]:
    resolutions = [
        resolve_target_query(runtime_metric_map, query, operation=operation)
        for query in queries
        if str(query or "").strip()
    ]
    return {
        "schema": "target_query_recovery_summary_v1",
        "operation": str(operation or "inspect").strip().lower() or "inspect",
        "query_count": len(resolutions),
        "matched_query_count": sum(1 for item in resolutions if item["status"] == "matched"),
        "unmatched_queries": [item["query"] for item in resolutions if item["status"] != "matched"],
        "resolutions": resolutions,
        "private_truth_included": False,
    }


def _candidate_resolution_row(
    candidate: dict[str, Any],
    normalized_query: dict[str, Any],
    *,
    operation: str,
) -> dict[str, Any]:
    searchable = _candidate_search_terms(candidate)
    match_score, basis = _match_score(normalized_query, searchable)
    actionability = str(candidate.get("target_actionability_status") or "")
    actionable = _candidate_actionable_for_operation(candidate, operation)
    row = {
        "candidate_id": str(candidate.get("candidate_id") or ""),
        "candidate_type": str(candidate.get("candidate_type") or ""),
        "query": str(candidate.get("query") or ""),
        "label": str(candidate.get("label") or ""),
        "category": str(candidate.get("category") or ""),
        "target_actionability_status": actionability,
        "actionability": actionability,
        "actionable_for_operation": actionable,
        "required_next_tool": _required_next_tool(candidate, operation),
        "match_score": match_score,
        "match_basis": basis,
        "confidence": _float_or_zero(candidate.get("confidence")),
        "waypoint_id": str(candidate.get("waypoint_id") or ""),
        "anchor_id": str(candidate.get("anchor_id") or ""),
        "object_id": str(candidate.get("object_id") or ""),
        "candidate_fixture_id": str(candidate.get("candidate_fixture_id") or ""),
        "source_observation_id": str(candidate.get("source_observation_id") or ""),
        "generated_inspection_waypoint_id": str(
            candidate.get("generated_inspection_waypoint_id") or ""
        ),
        "inspection_budget": dict(candidate.get("inspection_budget") or {}),
        "rejection_reason": str(candidate.get("rejection_reason") or ""),
        "private_truth_included": False,
    }
    if candidate.get("generated_inspection_candidate"):
        row["generated_inspection_candidate"] = dict(
            candidate.get("generated_inspection_candidate") or {}
        )
    return row


def _candidate_search_values(candidate: dict[str, Any]) -> list[Any]:
    values: list[Any] = [
        candidate.get("query"),
        candidate.get("label"),
        candidate.get("category"),
        candidate.get("candidate_type"),
        candidate.get("waypoint_id"),
        candidate.get("anchor_id"),
        candidate.get("object_id"),
        candidate.get("candidate_fixture_id"),
        candidate.get("source_fixture_id"),
        candidate.get("room_id"),
        candidate.get("room_label"),
        candidate.get("producer_type"),
        candidate.get("producer_id"),
    ]
    values.extend(candidate.get("affordances") or [])
    values.extend(candidate.get("aliases") or [])
    generated = candidate.get("generated_inspection_candidate")
    if isinstance(generated, dict):
        values.extend(
            [
                generated.get("waypoint_id"),
                generated.get("label"),
                generated.get("waypoint_source"),
            ]
        )
    return values


def filter_numbered_target_candidates(
    query: str, candidates: list[dict[str, Any]]
) -> list[dict[str, Any]]:
    """Bind numbered references only to identities present in public candidates.

    Semantic recovery for stale fixture names (e.g. sink_01) remains possible
    when that numbered identity family is absent from the public map.
    """
    requested = _numbered_references(query)
    if not requested:
        return candidates
    references = [
        set().union(
            *(_numbered_references(str(value or "")) for value in _candidate_search_values(c))
        )
        for c in candidates
    ]
    public_families = {family for refs in references for family, _ in refs}
    required = {ref for ref in requested if ref[0] in public_families}
    return [candidate for candidate, refs in zip(candidates, references) if required <= refs]


def _numbered_references(value: str) -> set[tuple[str, int]]:
    return {
        (family, int(number))
        for family, number in re.findall(r"([a-z]+)[ _-]*(\d+)(?!\d)", value.lower())
    }


def _candidate_search_terms(candidate: dict[str, Any]) -> list[str]:
    terms: list[str] = []
    for value in _candidate_search_values(candidate):
        text = str(value or "").strip()
        if not text:
            continue
        terms.extend(_query_aliases(text))
    return list(dict.fromkeys(item for item in terms if item))


def _match_score(query: dict[str, Any], terms: list[str]) -> tuple[float, list[str]]:
    if not query["compact"]:
        return 0.0, []
    query_terms = list(dict.fromkeys([query["compact"], *query["tokens"]]))
    basis: list[str] = []
    score = 0.0
    for query_term in query_terms:
        if not query_term:
            continue
        for term in terms:
            if query_term == term:
                basis.append(f"exact:{term}")
                score = max(score, 1.0)
            elif len(query_term) >= 3 and query_term in term:
                basis.append(f"contains:{query_term}->{term}")
                score = max(score, 0.72)
            elif len(term) >= 3 and term in query_term:
                basis.append(f"contains:{term}->{query_term}")
                score = max(score, 0.64)
    return score, list(dict.fromkeys(basis))


def _candidate_actionable_for_operation(candidate: dict[str, Any], operation: str) -> bool:
    actionability = str(candidate.get("target_actionability_status") or "")
    if actionability != "actionable":
        return False
    operation = str(operation or "inspect").lower()
    if operation in {"inspect", "observe", "find", "where", "is-there", "map-build"}:
        return bool(candidate.get("waypoint_id") or candidate.get("object_id"))
    if operation in {"go", "navigate", "destination", "place", "place_inside", "use"}:
        return bool(
            candidate.get("waypoint_id")
            or candidate.get("anchor_id")
            or candidate.get("candidate_fixture_id")
        )
    if operation in {"pick", "manipulate"}:
        return bool(candidate.get("object_id"))
    return True


def _required_next_tool(candidate: dict[str, Any], operation: str) -> str:
    actionability = str(candidate.get("target_actionability_status") or "")
    if actionability == "actionable":
        return _required_tool_for_actionable_candidate(candidate, operation)
    return _required_tool_for_non_actionable_candidate(candidate, actionability)


def _required_tool_for_actionable_candidate(candidate: dict[str, Any], operation: str) -> str:
    if operation in _OBJECT_NAVIGATION_OPERATIONS and candidate.get("object_id"):
        return "navigate_to_object"
    if operation in _DESTINATION_NAVIGATION_OPERATIONS:
        return _required_destination_navigation_tool(candidate)
    return _required_general_actionable_tool(candidate)


def _required_destination_navigation_tool(candidate: dict[str, Any]) -> str:
    if candidate.get("candidate_fixture_id"):
        return "navigate_to_receptacle"
    if candidate.get("waypoint_id"):
        return "navigate_to_waypoint"
    return _required_general_actionable_tool(candidate)


def _required_general_actionable_tool(candidate: dict[str, Any]) -> str:
    if candidate.get("waypoint_id"):
        return "navigate_to_waypoint"
    if candidate.get("object_id"):
        return "inspect_visible_object"
    return ""


def _required_tool_for_non_actionable_candidate(
    candidate: dict[str, Any], actionability: str
) -> str:
    if actionability == "needs_observe":
        return "navigate_to_waypoint" if candidate.get("waypoint_id") else "observe"
    if actionability == "visible_only":
        return "adjust_camera"
    if actionability == "anchor_unbound":
        return "metric_map"
    return "observe"


def _public_search_budget_evidence(summary: dict[str, Any]) -> dict[str, Any]:
    viewpoint = dict(summary.get("viewpoint_budget") or {})
    camera = dict(summary.get("camera_adjustment_budget") or {})
    return {
        "schema": str(summary.get("schema") or ""),
        "candidate_count": int(summary.get("candidate_count") or 0),
        "viewpoint_budget": viewpoint,
        "camera_adjustment_budget": camera,
        "inspection_observation_count": len(summary.get("inspection_observations") or []),
        "missing_target_policy": str(summary.get("missing_target_policy") or ""),
        "private_truth_included": False,
    }


def _public_budget_exhausted(summary: dict[str, Any]) -> bool:
    viewpoint = summary.get("viewpoint_budget") or {}
    unvisited = int(viewpoint.get("unvisited_waypoint_count") or 0)
    observed = int(viewpoint.get("visited_waypoint_count") or 0)
    total = int(viewpoint.get("total_public_waypoints") or 0)
    return total > 0 and observed >= total and unvisited == 0


def _actionability_rank(actionability: str) -> int:
    order = {
        "actionable": 6,
        "needs_observe": 5,
        "visible_only": 4,
        "anchor_unbound": 3,
        "unreachable": 2,
        "query_unmatched": 1,
    }
    return order.get(str(actionability or ""), 0)


def _normalize_query(query: str) -> dict[str, Any]:
    aliases = _query_aliases(query)
    compact = aliases[0] if aliases else ""
    return {"compact": compact, "tokens": aliases[1:]}


def _query_aliases(value: Any) -> list[str]:
    text = str(value or "").strip().lower()
    if not text:
        return []
    words = re.findall(r"[a-z0-9]+", text)
    stripped_words = [_strip_numeric_suffix(word) for word in words]
    compact = "".join(words)
    stripped_compact = "".join(stripped_words)
    aliases = [compact, stripped_compact, *words, *stripped_words]
    return list(dict.fromkeys(alias for alias in aliases if alias))


def _strip_numeric_suffix(value: str) -> str:
    return re.sub(r"\d+$", "", value).strip("_")


def _float_or_zero(value: Any) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0
