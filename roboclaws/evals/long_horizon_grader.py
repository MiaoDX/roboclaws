"""Private grader for long-horizon household eval samples."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from roboclaws.evals.final_state_evidence import FinalStateEvidence, final_state_evidence_for_run
from roboclaws.evals.long_horizon_contract import long_horizon_spec
from roboclaws.evals.models import MISSING_NOT_APPLICABLE, MISSING_UNAVAILABLE, EvalSample


def grade_long_horizon_task(
    sample: EvalSample,
    *,
    run_dir: Path,
    run_result: dict[str, Any],
) -> dict[str, Any]:
    spec = long_horizon_spec(sample)
    if spec is None:
        return {
            "status": "not_applicable",
            "failure_class": MISSING_NOT_APPLICABLE,
            "subgoals": {},
        }
    trace_events, trace_errors = _read_trace_events(run_dir / "trace.jsonl")
    evidence = final_state_evidence_for_run(run_result, trace_events=trace_events)
    if evidence.status != "available":
        return {
            "status": "inconclusive",
            "failure_class": "grader_inconclusive",
            "task_id": spec.task_id,
            "failures": [],
            "subgoals": {},
            "object_results": {},
            "evidence_status": evidence.status,
            "evidence_reason": "authoritative_final_state_unavailable",
            "evidence_source_provenance": list(evidence.source_provenance),
            "evidence_source_errors": list(evidence.source_errors),
            "trace_parse_errors": trace_errors,
            "first_failure_step": MISSING_UNAVAILABLE,
        }
    final_locations = evidence.locations
    final_containment = evidence.containment
    destinations = set(spec.accepted_destination_ids)
    object_results = {
        object_id: {
            "final_location": str(final_locations.get(object_id) or MISSING_UNAVAILABLE),
            "accepted": str(final_locations.get(object_id) or "") in destinations,
            "contained_in": str((final_containment.get(object_id) or {}).get("contained_in") or "")
            if isinstance(final_containment.get(object_id), dict)
            else "",
        }
        for object_id in spec.target_object_ids
    }
    sequence = _tool_sequence(trace_events)
    subgoals = {
        "map_acquired": "metric_map" in sequence,
        "source_visited": _visited_any_room(trace_events, spec.source_room_ids),
        "destination_reached": _destination_reached(trace_events, destinations)
        or all(item["accepted"] for item in object_results.values()),
        "target_observed": _target_observed(run_result, spec.target_object_ids),
        "picked": _tool_count(sequence, "pick") >= len(spec.target_object_ids),
        "placed": all(item["accepted"] for item in object_results.values()),
        "container_closed": _container_closed(evidence, spec.cold_object_ids),
        "done_claim": _has_completion_claim(run_result),
        "hands_empty": evidence.held_object_state == "empty",
    }
    failures = []
    if trace_errors:
        failures.append("trace_json_invalid")
    if not all(subgoals.values()):
        failures.extend(name for name, passed in subgoals.items() if not passed)
    if not _required_sequence_present(sequence, spec.required_tool_sequence):
        failures.append("required_tool_sequence_missing")
    if _private_truth_leaked(run_dir, run_result):
        failures.append("private_truth_leak")
    failure_class = _long_horizon_failure_class(failures)
    return {
        "status": "failed" if failures else "passed",
        "failure_class": failure_class if failures else MISSING_NOT_APPLICABLE,
        "task_id": spec.task_id,
        "failures": failures,
        "subgoals": subgoals,
        "object_results": object_results,
        "trace_parse_errors": trace_errors,
        "first_failure_step": _first_failure_step(trace_events, failures),
        "required_tool_sequence": list(spec.required_tool_sequence),
        "observed_tool_sequence": sequence,
    }


def _read_trace_events(path: Path) -> tuple[list[dict[str, Any]], list[dict[str, str]]]:
    events: list[dict[str, Any]] = []
    errors: list[dict[str, str]] = []
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except FileNotFoundError:
        return [], [{"path": str(path), "error": "missing"}]
    for line_number, line in enumerate(lines, start=1):
        if not line.strip():
            continue
        try:
            item = json.loads(line)
        except json.JSONDecodeError as exc:
            errors.append({"path": str(path), "line": str(line_number), "error": exc.msg})
            continue
        if isinstance(item, dict):
            events.append(item)
        else:
            errors.append({"path": str(path), "line": str(line_number), "error": "not_object"})
    return events, errors


def _tool_sequence(trace_events: list[dict[str, Any]]) -> list[str]:
    return [
        str(event.get("tool") or "")
        for event in trace_events
        if event.get("event") == "response" and event.get("tool")
    ]


def _tool_count(sequence: list[str], tool: str) -> int:
    return sum(1 for item in sequence if item == tool)


def _visited_any_room(trace_events: list[dict[str, Any]], room_ids: tuple[str, ...]) -> bool:
    if not room_ids:
        return True
    expected = set(room_ids)
    for event in trace_events:
        if event.get("event") != "response":
            continue
        response = event.get("response") if isinstance(event.get("response"), dict) else {}
        if str(response.get("current_room_id") or response.get("room_id") or "") in expected:
            return True
    return False


def _destination_reached(trace_events: list[dict[str, Any]], destinations: set[str]) -> bool:
    for event in trace_events:
        if event.get("event") != "response":
            continue
        if event.get("tool") not in {
            "navigate_to_receptacle",
            "place",
            "place_inside",
            "close_receptacle",
        }:
            continue
        response = event.get("response") if isinstance(event.get("response"), dict) else {}
        for key in ("fixture_id", "receptacle_id", "location_id", "contained_in"):
            if str(response.get(key) or "") in destinations:
                return True
    return False


def _target_observed(run_result: dict[str, Any], object_ids: tuple[str, ...]) -> bool:
    runtime_map = (
        run_result.get("runtime_metric_map")
        if isinstance(run_result.get("runtime_metric_map"), dict)
        else {}
    )
    observed = runtime_map.get("observed_objects") if isinstance(runtime_map, dict) else []
    if not isinstance(observed, list):
        return False
    public_count = sum(1 for item in observed if isinstance(item, dict) and item.get("object_id"))
    return public_count >= len(object_ids)


def _container_closed(evidence: FinalStateEvidence, cold_object_ids: tuple[str, ...]) -> bool:
    if not cold_object_ids:
        return True
    receptacle_ids = {
        str(evidence.containment.get(object_id, {}).get("contained_in") or "")
        or str(evidence.locations.get(object_id) or "")
        for object_id in cold_object_ids
    }
    return (
        bool(receptacle_ids)
        and "" not in receptacle_ids
        and all(
            evidence.receptacle_states.get(receptacle_id) == "closed"
            for receptacle_id in receptacle_ids
        )
    )


def _has_completion_claim(run_result: dict[str, Any]) -> bool:
    claim = run_result.get("agent_completion_claim")
    return isinstance(claim, dict) and bool(claim.get("completion_summary"))


def _required_sequence_present(sequence: list[str], required: tuple[str, ...]) -> bool:
    if not required:
        return True
    start = 0
    for tool in required:
        try:
            index = sequence.index(tool, start)
        except ValueError:
            return False
        start = index + 1
    return True


def _private_truth_leaked(run_dir: Path, run_result: dict[str, Any]) -> bool:
    forbidden = {
        "private_manifest",
        "acceptable_destinations",
        "target_object_ids",
        "accepted_destination_ids",
        "long_horizon_task",
    }
    agent_view = run_result.get("agent_view")
    if _contains_forbidden_key(agent_view, forbidden):
        return True
    path = run_dir / "agent_view.json"
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError):
        payload = {}
    if _contains_forbidden_key(payload, forbidden):
        return True
    trace_events, _errors = _read_trace_events(run_dir / "trace.jsonl")
    return any(_contains_forbidden_key(event, forbidden) for event in trace_events)


def _contains_forbidden_key(value: Any, forbidden: set[str]) -> bool:
    if isinstance(value, dict):
        return bool(forbidden.intersection(value)) or any(
            _contains_forbidden_key(item, forbidden) for item in value.values()
        )
    if isinstance(value, list):
        return any(_contains_forbidden_key(item, forbidden) for item in value)
    return False


def _long_horizon_failure_class(failures: list[str]) -> str:
    if "private_truth_leak" in failures:
        return "private_truth_leak"
    if "trace_json_invalid" in failures:
        return "artifact_missing"
    if "required_tool_sequence_missing" in failures:
        return "trajectory_policy_violation"
    if any(item in failures for item in ("placed", "hands_empty", "container_closed")):
        return "private_goal_not_satisfied"
    if "target_observed" in failures:
        return "perception_miss"
    if any(item in failures for item in ("source_visited", "destination_reached")):
        return "trajectory_policy_violation"
    return "partial_progress_only"


def _first_failure_step(trace_events: list[dict[str, Any]], failures: list[str]) -> int | str:
    if not failures:
        return MISSING_NOT_APPLICABLE
    for index, event in enumerate(trace_events, start=1):
        if event.get("event") != "response":
            continue
        response = event.get("response") if isinstance(event.get("response"), dict) else {}
        if response.get("ok") is False:
            return index
    return MISSING_UNAVAILABLE
