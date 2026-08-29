"""Open-ended goal grading and Runtime Metric Map predicates."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from roboclaws.evals import grading_sources
from roboclaws.evals.models import MISSING_NOT_APPLICABLE, MISSING_UNAVAILABLE, EvalSample


def grade_open_ended(
    *, sample: EvalSample, run_dir: Path, run_result: dict[str, Any]
) -> dict[str, Any]:
    if sample.intent != "open-ended":
        return {
            "status": "not_applicable",
            "completion_claim_present": MISSING_NOT_APPLICABLE,
            "artifact_readiness": MISSING_NOT_APPLICABLE,
            "semantic_satisfaction_status": "advisory_not_applicable",
        }
    claim = run_result.get("agent_completion_claim")
    claim_present = isinstance(claim, dict) and bool(claim.get("completion_summary"))
    required = ("run_result.json", "report.html", "trace.jsonl", "goal_contract.json")
    missing = [name for name in required if not (run_dir / name).exists()]
    artifact_ready = not missing
    advisory = (
        run_result.get("advisory_evaluation")
        if isinstance(run_result.get("advisory_evaluation"), dict)
        else {}
    )
    advisory_error = ""
    if not advisory:
        advisory, advisory_error = grading_sources.load_optional_json_mapping(
            run_dir / "advisory_evaluation.json"
        )
    semantic_status = "advisory_available" if advisory else "advisory_unavailable"
    config = sample.grader_config or {}
    predicate_config = config.get("success_predicate")
    predicate = _success_predicate(
        predicate_config if isinstance(predicate_config, dict) else {}, run_dir=run_dir
    )
    source_errors = [
        error
        for error in (
            grading_sources.json_source_error(run_dir / "advisory_evaluation.json", advisory_error),
            *_goal_contract_source_errors(run_dir),
            *(predicate.get("source_errors") or []),
        )
        if error
    ]
    if source_errors:
        semantic_status = "source_error"
    hard_passed = claim_present and artifact_ready
    if predicate["authoritative"]:
        hard_passed = hard_passed and predicate["passed"]
    if source_errors:
        hard_passed = False
    return {
        "status": "passed" if hard_passed else "failed",
        "failure_class": (
            MISSING_NOT_APPLICABLE
            if hard_passed
            else (
                "artifact_missing"
                if source_errors
                else (
                    "private_goal_not_satisfied"
                    if claim_present and artifact_ready and predicate["authoritative"]
                    else "agent_no_completion_claim"
                )
            )
        ),
        "open_ended_category": str(config.get("open_ended_category") or MISSING_UNAVAILABLE),
        "expected_goal_outcome": str(config.get("expected_goal_outcome") or MISSING_UNAVAILABLE),
        "completion_claim_present": claim_present,
        "artifact_readiness": "ready" if artifact_ready else "missing",
        "missing_artifacts": missing,
        "semantic_satisfaction_status": semantic_status,
        "semantic_satisfaction_authoritative": bool(
            config.get("semantic_satisfaction_authoritative") is True
        ),
        "success_predicate": predicate,
        "source_errors": source_errors,
    }


def _goal_contract_source_errors(run_dir: Path) -> tuple[dict[str, str], ...]:
    path = run_dir / "goal_contract.json"
    if not path.exists():
        return ()
    contract, reason = grading_sources.load_optional_json_mapping(path)
    if reason:
        return (grading_sources.json_source_error(path, reason),)
    errors: list[dict[str, str]] = []
    if contract.get("schema") != "roboclaws_goal_contract_v1":
        errors.append({"path": str(path), "reason": "invalid_goal_contract_schema"})
    for key in ("surface", "intent", "normalized_goal", "goal_scope"):
        if not str(contract.get(key) or "").strip():
            errors.append({"path": str(path), "reason": f"missing_goal_contract_{key}"})
    return tuple(errors)


def _success_predicate(config: dict[str, Any], *, run_dir: Path) -> dict[str, Any]:
    predicate_id = str(config.get("predicate_id") or "completion_claim")
    authoritative = bool(config.get("authoritative") is True)
    runtime_map_path = run_dir / "runtime_metric_map.json"
    runtime_map, runtime_map_error = grading_sources.load_optional_json_mapping(runtime_map_path)
    trace_events, _trace_errors = grading_sources.read_trace_events_with_errors(
        run_dir / "trace.jsonl"
    )
    if runtime_map_error:
        return {
            "predicate_id": predicate_id,
            "authoritative": authoritative,
            "passed": False,
            "source_error": True,
            "source_errors": [
                grading_sources.json_source_error(runtime_map_path, runtime_map_error)
            ],
            "evidence": {},
        }
    source_errors = _runtime_map_source_errors(
        predicate_id, runtime_map=runtime_map, runtime_map_path=runtime_map_path
    )
    if source_errors:
        return {
            "predicate_id": predicate_id,
            "authoritative": authoritative,
            "passed": False,
            "source_error": True,
            "source_errors": source_errors,
            "evidence": {},
        }
    if predicate_id == "completion_claim":
        return {
            "predicate_id": predicate_id,
            "authoritative": authoritative,
            "passed": True,
            "source_errors": [],
            "evidence": {},
        }
    if predicate_id == "public_anchor_observed":
        return _public_anchor_predicate(
            config,
            runtime_map=runtime_map,
            trace_events=trace_events,
            authoritative=authoritative,
        )
    if predicate_id == "waypoint_or_area_visited":
        return _waypoint_predicate(
            config,
            runtime_map=runtime_map,
            trace_events=trace_events,
            authoritative=authoritative,
        )
    if predicate_id == "observed_category_present":
        return _category_predicate(config, runtime_map=runtime_map, authoritative=authoritative)
    if predicate_id == "public_search_exhausted":
        return _public_search_exhausted_predicate(
            runtime_map=runtime_map,
            trace_events=trace_events,
            authoritative=authoritative,
        )
    return {
        "predicate_id": predicate_id,
        "authoritative": authoritative,
        "passed": False,
        "failure": "unknown_open_ended_success_predicate",
        "evidence": {},
    }


def _public_anchor_predicate(
    config: dict[str, Any],
    *,
    runtime_map: dict[str, Any],
    trace_events: list[dict[str, Any]],
    authoritative: bool,
) -> dict[str, Any]:
    anchor_id = str(config.get("anchor_id") or "")
    room_id = str(config.get("room_id") or "")
    anchors = [
        anchor
        for anchor in grading_sources.list_of_mappings(runtime_map.get("public_semantic_anchors"))
        if (not anchor_id or str(anchor.get("anchor_id") or "") == anchor_id)
        and (not room_id or str(anchor.get("room_id") or "") == room_id)
    ]
    observed_rooms = _observed_room_ids(runtime_map=runtime_map, trace_events=trace_events)
    passed = bool(anchors) and (not room_id or room_id in observed_rooms)
    return {
        "predicate_id": "public_anchor_observed",
        "authoritative": authoritative,
        "passed": passed,
        "failure": "" if passed else "required_public_anchor_not_observed",
        "evidence": {
            "anchor_id": anchor_id,
            "room_id": room_id,
            "matching_anchor_count": len(anchors),
            "observed_room_ids": sorted(observed_rooms),
        },
    }


def _waypoint_predicate(
    config: dict[str, Any],
    *,
    runtime_map: dict[str, Any],
    trace_events: list[dict[str, Any]],
    authoritative: bool,
) -> dict[str, Any]:
    waypoint_id = str(config.get("waypoint_id") or "")
    room_id = str(config.get("room_id") or "")
    anchor_id = str(config.get("anchor_id") or "")
    visited_waypoints = _visited_waypoint_ids(runtime_map=runtime_map, trace_events=trace_events)
    observed_rooms = _observed_room_ids(runtime_map=runtime_map, trace_events=trace_events)
    anchors = grading_sources.list_of_mappings(runtime_map.get("public_semantic_anchors"))
    anchor_present = any(
        (not anchor_id or str(anchor.get("anchor_id") or "") == anchor_id)
        and (not waypoint_id or str(anchor.get("waypoint_id") or "") == waypoint_id)
        and (not room_id or str(anchor.get("room_id") or "") == room_id)
        for anchor in anchors
    )
    waypoint_visited = not waypoint_id or waypoint_id in visited_waypoints
    passed = (
        waypoint_visited
        and (not room_id or room_id in observed_rooms)
        and (not anchor_id or anchor_present or waypoint_visited)
    )
    return {
        "predicate_id": "waypoint_or_area_visited",
        "authoritative": authoritative,
        "passed": passed,
        "failure": "" if passed else "required_waypoint_or_area_not_visited",
        "evidence": {
            "anchor_id": anchor_id,
            "waypoint_id": waypoint_id,
            "room_id": room_id,
            "anchor_present": anchor_present,
            "visited_waypoint_ids": sorted(visited_waypoints),
            "observed_room_ids": sorted(observed_rooms),
        },
    }


def _category_predicate(
    config: dict[str, Any], *, runtime_map: dict[str, Any], authoritative: bool
) -> dict[str, Any]:
    category = str(config.get("category") or "").lower()
    matching = [
        item
        for item in grading_sources.list_of_mappings(runtime_map.get("observed_objects"))
        if not category
        or category
        in {
            str(item.get("category") or "").lower(),
            str(item.get("label") or "").lower(),
            str(item.get("query") or "").lower(),
        }
    ]
    passed = bool(matching)
    return {
        "predicate_id": "observed_category_present",
        "authoritative": authoritative,
        "passed": passed,
        "failure": "" if passed else "required_observed_category_missing",
        "evidence": {"category": category, "matching_observed_count": len(matching)},
    }


def _public_search_exhausted_predicate(
    *,
    runtime_map: dict[str, Any],
    trace_events: list[dict[str, Any]],
    authoritative: bool,
) -> dict[str, Any]:
    summary = runtime_map.get("target_search_summary")
    viewpoint_budget = summary.get("viewpoint_budget") if isinstance(summary, dict) else {}
    if not isinstance(viewpoint_budget, dict):
        viewpoint_budget = {}
    observed_waypoint_ids = {
        str(item) for item in viewpoint_budget.get("observed_waypoint_ids") or [] if str(item)
    }
    total_public_waypoints = _nonnegative_int(viewpoint_budget.get("total_public_waypoints"))
    visited_waypoint_count = _nonnegative_int(viewpoint_budget.get("visited_waypoint_count"))
    unvisited_waypoint_count = _nonnegative_int(viewpoint_budget.get("unvisited_waypoint_count"))
    unvisited_waypoint_ids = [
        str(item) for item in viewpoint_budget.get("unvisited_waypoint_ids") or [] if str(item)
    ]
    resolver_events = [
        (index, event)
        for index, event in enumerate(trace_events)
        if event.get("event") == "response" and event.get("tool") == "resolve_target_query"
    ]
    final_index, final_event = resolver_events[-1] if resolver_events else (-1, {})
    resolution = (
        final_event.get("response")
        if isinstance(final_event.get("response"), dict)
        else final_event
    )
    done_after_resolution = any(
        index > final_index and event.get("event") == "response" and event.get("tool") == "done"
        for index, event in enumerate(trace_events)
    )
    every_waypoint_observed = (
        total_public_waypoints is not None
        and visited_waypoint_count == total_public_waypoints
        and len(observed_waypoint_ids) == total_public_waypoints
        and unvisited_waypoint_count == 0
        and not unvisited_waypoint_ids
    )
    no_public_match = resolution.get("match_count") == 0 and not resolution.get("matches")
    final_not_found = (
        resolution.get("status") == "not_found"
        and resolution.get("exhausted_public_search_budget") is True
    )
    passed = bool(
        final_not_found and every_waypoint_observed and no_public_match and done_after_resolution
    )
    return {
        "predicate_id": "public_search_exhausted",
        "authoritative": authoritative,
        "passed": passed,
        "failure": "" if passed else "public_search_not_authoritatively_exhausted",
        "evidence": {
            "final_resolution_status": resolution.get("status", MISSING_UNAVAILABLE),
            "exhausted_public_search_budget": resolution.get(
                "exhausted_public_search_budget", False
            ),
            "public_match_count": resolution.get("match_count", MISSING_UNAVAILABLE),
            "total_public_waypoints": (
                total_public_waypoints
                if total_public_waypoints is not None
                else MISSING_UNAVAILABLE
            ),
            "observed_public_waypoint_count": len(observed_waypoint_ids),
            "every_public_waypoint_observed": every_waypoint_observed,
            "done_after_final_resolution": done_after_resolution,
        },
    }


def _nonnegative_int(value: Any) -> int | None:
    if isinstance(value, bool):
        return None
    try:
        result = int(value)
    except (TypeError, ValueError):
        return None
    return result if result >= 0 else None


def _visited_waypoint_ids(
    *, runtime_map: dict[str, Any], trace_events: list[dict[str, Any]]
) -> set[str]:
    visited: set[str] = set()
    summary = runtime_map.get("target_search_summary")
    if isinstance(summary, dict):
        viewpoint_budget = summary.get("viewpoint_budget")
        if isinstance(viewpoint_budget, dict):
            visited.update(
                str(item) for item in viewpoint_budget.get("observed_waypoint_ids") or []
            )
        for observation in grading_sources.list_of_mappings(summary.get("inspection_observations")):
            waypoint_id = str(observation.get("waypoint_id") or "")
            if waypoint_id:
                visited.add(waypoint_id)
    for candidate in grading_sources.list_of_mappings(
        runtime_map.get("generated_exploration_candidates")
    ):
        if candidate.get("visited") is True and candidate.get("waypoint_id"):
            visited.add(str(candidate["waypoint_id"]))
    for event in trace_events:
        if event.get("tool") == "navigate_to_waypoint" and event.get("event") == "request":
            request = event.get("request") if isinstance(event.get("request"), dict) else {}
            waypoint_id = str(request.get("waypoint_id") or "")
            if waypoint_id:
                visited.add(waypoint_id)
    return visited


def _observed_room_ids(
    *, runtime_map: dict[str, Any], trace_events: list[dict[str, Any]]
) -> set[str]:
    rooms: set[str] = set()
    summary = runtime_map.get("target_search_summary")
    if isinstance(summary, dict):
        for observation in grading_sources.list_of_mappings(summary.get("inspection_observations")):
            room_id = str(observation.get("room_id") or "")
            if room_id:
                rooms.add(room_id)
    waypoint_rooms = {
        str(candidate.get("waypoint_id") or ""): str(candidate.get("room_id") or "")
        for candidate in grading_sources.list_of_mappings(
            runtime_map.get("generated_exploration_candidates")
        )
    }
    for waypoint_id in _visited_waypoint_ids(runtime_map=runtime_map, trace_events=trace_events):
        room_id = waypoint_rooms.get(waypoint_id, "")
        if room_id:
            rooms.add(room_id)
    return rooms


def _runtime_map_source_errors(
    predicate_id: str, *, runtime_map: dict[str, Any], runtime_map_path: Path
) -> list[dict[str, str]]:
    reasons: list[str] = []
    if predicate_id in {
        "public_anchor_observed",
        "waypoint_or_area_visited",
        "public_search_exhausted",
    }:
        reasons.extend(
            _runtime_map_list_field_errors(
                runtime_map,
                ("public_semantic_anchors", "generated_exploration_candidates"),
            )
        )
        reasons.extend(_target_search_summary_source_errors(runtime_map))
    if predicate_id == "observed_category_present":
        reasons.extend(_runtime_map_list_field_errors(runtime_map, ("observed_objects",)))
    return [grading_sources.json_source_error(runtime_map_path, reason) for reason in reasons]


def _runtime_map_list_field_errors(payload: dict[str, Any], keys: tuple[str, ...]) -> list[str]:
    errors: list[str] = []
    for key in keys:
        _value, reason = _optional_list_value(payload, key)
        if reason:
            errors.append(reason)
    return errors


def _target_search_summary_source_errors(runtime_map: dict[str, Any]) -> list[str]:
    if (
        "target_search_summary" not in runtime_map
        or runtime_map.get("target_search_summary") is None
    ):
        return []
    summary = runtime_map.get("target_search_summary")
    if not isinstance(summary, dict):
        return ["target_search_summary:invalid_json_object"]
    errors = _runtime_map_list_field_errors(summary, ("inspection_observations",))
    viewpoint_budget = summary.get("viewpoint_budget")
    if viewpoint_budget is not None:
        if not isinstance(viewpoint_budget, dict):
            errors.append("target_search_summary.viewpoint_budget:invalid_json_object")
        else:
            errors.extend(
                _runtime_map_list_field_errors(
                    viewpoint_budget,
                    ("observed_waypoint_ids", "unvisited_waypoint_ids"),
                )
            )
    return errors


def _optional_list_value(payload: dict[str, Any], key: str) -> tuple[list[Any], str]:
    if key not in payload or payload.get(key) is None:
        return [], ""
    value = payload.get(key)
    if not isinstance(value, list):
        return [], f"{key}:invalid_json_array"
    return value, ""
