"""Eval grader composition and benchmark-only scoring."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from roboclaws.evals import grading_sources, long_horizon_contract, open_ended_grading
from roboclaws.evals import long_horizon_grader as lhg
from roboclaws.evals.map_build_quality import grade_runtime_metric_map_quality
from roboclaws.evals.models import (
    MISSING_NOT_APPLICABLE,
    MISSING_UNAVAILABLE,
    EvalSample,
)


def _grade_trial(
    *,
    sample: EvalSample,
    run_dir: Path,
    run_result: dict[str, Any],
    dependency_artifacts: dict[str, Any] | None,
) -> dict[str, Any]:
    return {
        "artifacts": _artifact_grader(run_dir, dependency_artifacts=dependency_artifacts),
        "privacy": _privacy_grader(run_result),
        "trajectory": _trajectory_grader(sample=sample, run_dir=run_dir, run_result=run_result),
        "outcome": _outcome_grader(sample=sample, run_dir=run_dir, run_result=run_result),
        "long_horizon": lhg.grade_long_horizon_task(sample, run_dir=run_dir, run_result=run_result),
        "sampler_admission": _sampler_admission_grader(sample=sample),
        "open_ended": open_ended_grading.grade_open_ended(
            sample=sample, run_dir=run_dir, run_result=run_result
        ),
        "efficiency": _efficiency_grader(run_dir=run_dir, run_result=run_result),
    }


def _artifact_grader(
    run_dir: Path,
    *,
    dependency_artifacts: dict[str, Any] | None,
) -> dict[str, Any]:
    required = {
        "run_result": run_dir / "run_result.json",
        "report": run_dir / "report.html",
        "trace": run_dir / "trace.jsonl",
        "agent_view": run_dir / "agent_view.json",
        "runtime_metric_map": run_dir / "runtime_metric_map.json",
        "private_evaluation": run_dir / "private_evaluation.json",
    }
    missing = [name for name, path in required.items() if not path.exists()]
    source_errors = grading_sources.required_json_artifact_source_errors(
        {
            name: required[name]
            for name in (
                "run_result",
                "agent_view",
                "runtime_metric_map",
                "private_evaluation",
            )
        }
    )
    return {
        "status": "failed" if missing or source_errors else "passed",
        "failure_class": (
            "artifact_missing" if missing or source_errors else MISSING_NOT_APPLICABLE
        ),
        "missing": missing,
        "source_errors": source_errors,
        "resolved_dependencies": dict(dependency_artifacts or {}),
        "required": {name: str(path) for name, path in required.items()},
    }


def _privacy_grader(run_result: dict[str, Any]) -> dict[str, Any]:
    leaked = []
    if run_result.get("policy_uses_private_truth") is True:
        leaked.append("policy_uses_private_truth")
    if run_result.get("planner_uses_private_manifest") is True:
        leaked.append("planner_uses_private_manifest")
    agent_view = (
        run_result.get("agent_view") if isinstance(run_result.get("agent_view"), dict) else {}
    )
    for key in ("private_manifest", "acceptable_destinations", "hidden_target_list"):
        if key in agent_view:
            leaked.append(f"agent_view.{key}")
    return {
        "status": "failed" if leaked else "passed",
        "private_truth_leak_count": len(leaked),
        "leaked_fields": leaked,
    }


def _trajectory_grader(
    *,
    sample: EvalSample,
    run_dir: Path,
    run_result: dict[str, Any],
) -> dict[str, Any]:
    trace_events, trace_errors = grading_sources.read_trace_events_with_errors(
        run_dir / "trace.jsonl"
    )
    response_tools = {
        str(event.get("tool"))
        for event in trace_events
        if event.get("event") == "response" and event.get("tool")
    }
    required_groups = (
        {"done"},
        {"metric_map", "resolve_target_query"} if sample.intent == "open-ended" else {"metric_map"},
    )
    missing_tools = sorted(
        ",".join(sorted(group))
        for group in required_groups
        if not response_tools.intersection(group)
    )
    static_fixture_projection_count = sum(
        1 for event in trace_events if event.get("tool") == "static_fixture_projection"
    )
    violations = list(missing_tools)
    failed_or_noop_count = _int_value(
        run_result.get("score", {}).get("failed_or_noop_tool_count")
        if isinstance(run_result.get("score"), dict)
        else None
    )
    if failed_or_noop_count > 0:
        violations.append("failed_or_noop_tool")
    if trace_errors:
        violations.append("trace_json_invalid")
    return {
        "status": "failed" if violations else "passed",
        "failure_class": ("trajectory_policy_violation" if violations else MISSING_NOT_APPLICABLE),
        "missing_required_tools": missing_tools,
        "violation_count": len(violations),
        "violations": violations,
        "trace_parse_errors": trace_errors,
        "static_fixture_projection_trace_count": static_fixture_projection_count,
        "static_fixture_projection_policy": (
            "direct_runner_internal_compatibility"
            if sample.allowed_agent_engines == ("direct-runner",)
            else "trajectory_violation_for_live_mcp"
        ),
    }


def _outcome_grader(
    *,
    sample: EvalSample,
    run_dir: Path,
    run_result: dict[str, Any],
) -> dict[str, Any]:
    if sample.intent == "map-build":
        runtime_map_path = run_dir / "runtime_metric_map.json"
        runtime_map, runtime_map_error = grading_sources.load_required_json_mapping(
            runtime_map_path
        )
        return grade_runtime_metric_map_quality(
            runtime_map=runtime_map,
            runtime_map_exists=runtime_map_path.exists(),
            runtime_map_error=runtime_map_error,
            config=sample.grader_config or {},
            private_goal_reference=_map_build_private_goal_reference(
                sample=sample,
                run_dir=run_dir,
                run_result=run_result,
            ),
        )
    if sample.intent == "open-ended":
        open_ended = open_ended_grading.grade_open_ended(
            sample=sample, run_dir=run_dir, run_result=run_result
        )
        return {
            "status": open_ended["status"],
            "completion_claim_present": open_ended["completion_claim_present"],
            "artifact_readiness": open_ended["artifact_readiness"],
            "semantic_satisfaction_status": open_ended["semantic_satisfaction_status"],
            "open_ended_category": open_ended["open_ended_category"],
            "expected_goal_outcome": open_ended["expected_goal_outcome"],
            "success_predicate": open_ended["success_predicate"],
        }
    score = run_result.get("score") if isinstance(run_result.get("score"), dict) else {}
    completion_status = str(
        score.get("completion_status")
        or run_result.get("completion_status")
        or run_result.get("cleanup_status")
        or ""
    )
    semantic_acceptability = (
        score.get("semantic_acceptability")
        if isinstance(score.get("semantic_acceptability"), dict)
        else {}
    )
    semantic_completion_status = str(semantic_acceptability.get("status") or "")
    if sample.intent == "cleanup":
        restoration_rate = _float_or_none(score.get("mess_restoration_rate"))
        sweep_coverage_rate = _float_or_none(score.get("sweep_coverage_rate"))
        disturbance_count = _int_or_none(score.get("disturbance_count"))
        done_present = _done_response_present(run_dir)
        passed = bool(
            completion_status in {"passed", "success", "complete", "completed"}
            and done_present
            and restoration_rate is not None
            and restoration_rate
            >= float((sample.grader_config or {}).get("min_restoration_rate", 0.7))
            and sweep_coverage_rate is not None
            and sweep_coverage_rate
            >= float((sample.grader_config or {}).get("min_sweep_coverage_rate", 0.9))
            and disturbance_count is not None
            and disturbance_count
            <= int((sample.grader_config or {}).get("max_disturbance_count", 2))
        )
    else:
        restoration_rate = _float_or_none(score.get("mess_restoration_rate"))
        sweep_coverage_rate = _float_or_none(score.get("sweep_coverage_rate"))
        disturbance_count = _int_or_none(score.get("disturbance_count"))
        done_present = _done_response_present(run_dir)
        passed = completion_status in {"passed", "success", "complete", "completed"}
    return {
        "status": "passed" if passed else "failed",
        "completion_status": completion_status,
        "semantic_completion_status": semantic_completion_status or MISSING_UNAVAILABLE,
        "semantic_acceptability": semantic_acceptability or MISSING_UNAVAILABLE,
        "mess_restoration_rate": score.get("mess_restoration_rate", MISSING_UNAVAILABLE),
        "sweep_coverage_rate": score.get("sweep_coverage_rate", MISSING_UNAVAILABLE),
        "disturbance_count": score.get("disturbance_count", MISSING_UNAVAILABLE),
        "authoritative_done_present": done_present,
    }


def _done_response_present(run_dir: Path) -> bool:
    events, _errors = grading_sources.read_trace_events_with_errors(run_dir / "trace.jsonl")
    return any(event.get("event") == "response" and event.get("tool") == "done" for event in events)


def _float_or_none(value: Any) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _int_or_none(value: Any) -> int | None:
    if isinstance(value, bool):
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _map_build_private_goal_reference(
    *,
    sample: EvalSample,
    run_dir: Path,
    run_result: dict[str, Any],
) -> dict[str, Any]:
    reference = dict(sample.private_goal_reference or {})
    if str(run_result.get("backend") or "") != "molmospaces_subprocess":
        return reference
    truth = _molmospaces_fixture_truth_from_backend_state(
        run_dir / "molmospaces_backend_state.json"
    )
    if truth:
        reference["simulator_fixture_truth"] = truth
    return reference


def _molmospaces_fixture_truth_from_backend_state(path: Path) -> dict[str, Any]:
    state, error = grading_sources.load_optional_json_mapping(path)
    if error or not state:
        return {}
    receptacles = state.get("receptacles") if isinstance(state.get("receptacles"), dict) else {}
    rows = []
    categories = set()
    for raw_id, raw_fixture in receptacles.items():
        if not isinstance(raw_fixture, dict):
            continue
        category = str(raw_fixture.get("category") or raw_fixture.get("name") or "").strip()
        room_id = str(
            raw_fixture.get("room_id")
            or raw_fixture.get("room_area")
            or _room_id_for_receptacle_id(str(raw_id))
        ).strip()
        if not category or not room_id:
            continue
        categories.add(category)
        rows.append(
            {
                "category": category,
                "waypoint_ids": [f"{room_id}_inspection"],
            }
        )
    merged: dict[str, set[str]] = {}
    for row in rows:
        key = _normalized_truth_category(row["category"])
        merged.setdefault(key, set()).update(row["waypoint_ids"])
    return {
        "schema": "map_build_simulator_fixture_truth_v1",
        "truth_scope": "grader_only",
        "truth_source": "molmospaces_backend_state.receptacles",
        "pose_semantics": "best_view_waypoint_only",
        "categories": sorted(categories),
        "best_view_waypoint_truth": [
            {"category": category, "waypoint_ids": sorted(waypoint_ids)}
            for category, waypoint_ids in sorted(merged.items())
        ],
    }


def _room_id_for_receptacle_id(value: str) -> str:
    parts = str(value or "").rsplit("_", 3)
    if parts and parts[-1].isdigit():
        return f"room_{parts[-1]}"
    return ""


def _normalized_truth_category(value: Any) -> str:
    return str(value or "").strip().lower()


def _sampler_admission_grader(*, sample: EvalSample) -> dict[str, Any]:
    config = sample.grader_config or {}
    admission = config.get("sampler_admission")
    if not isinstance(admission, dict):
        return {"status": "not_applicable"}
    room_count = _int_value(admission.get("room_count"))
    waypoint_count = _int_value(admission.get("waypoint_count"))
    category_provenance = str(admission.get("category_provenance") or "")
    forbidden_provenance = {
        "heuristic_room_label",
        "heuristic_room_count",
        "room_area_fallback",
    }
    failures: list[str] = []
    if room_count < 3:
        failures.append("fewer_than_three_public_rooms")
    if waypoint_count < room_count:
        failures.append("missing_room_waypoints")
    if category_provenance in forbidden_provenance or category_provenance not in {
        "source_metadata",
        "prepared_visual_label_manifest",
    }:
        failures.append("untrusted_room_category_provenance")
    return {
        "status": "failed" if failures else "passed",
        "failure_class": "map_actionability_failure" if failures else MISSING_NOT_APPLICABLE,
        "failures": failures,
        "scene_family": str(admission.get("scene_family") or ""),
        "scene_split": str(admission.get("scene_split") or ""),
        "scene_source": str(admission.get("scene_source") or ""),
        "scene_index": admission.get("scene_index", MISSING_UNAVAILABLE),
        "room_count": room_count,
        "waypoint_count": waypoint_count,
        "category_provenance": category_provenance,
        "category_manifest": str(admission.get("category_manifest") or ""),
        "generator_version": str(admission.get("generator_version") or ""),
    }


def _efficiency_grader(*, run_dir: Path, run_result: dict[str, Any]) -> dict[str, Any]:
    tool_counts = (
        run_result.get("tool_event_counts")
        if isinstance(run_result.get("tool_event_counts"), dict)
        else {}
    )
    live_status, live_status_error = _merged_live_status(run_dir=run_dir, run_result=run_result)
    live_timing_path = run_dir / "live_timing.json"
    live_timing, live_timing_error = grading_sources.load_optional_json_mapping(live_timing_path)
    timing_payload = dict(run_result)
    if live_timing:
        timing_payload["live_timing"] = live_timing
        timing_payload["runner_wall_time_s"] = _live_wall_time_s(live_timing)
    model_attempt_summary = _model_attempt_summary(timing_payload)
    trace_events, trace_errors = grading_sources.read_trace_events_with_errors(
        run_dir / "trace.jsonl"
    )
    source_errors = [
        error
        for error in (
            grading_sources.json_source_error(run_dir / "live_status.json", live_status_error),
            grading_sources.json_source_error(live_timing_path, live_timing_error),
        )
        if error
    ]
    return {
        "status": "failed" if source_errors or trace_errors else "passed",
        "failure_class": (
            "artifact_missing" if source_errors or trace_errors else MISSING_NOT_APPLICABLE
        ),
        "source_errors": source_errors,
        "trace_parse_errors": trace_errors,
        "tool_event_count": sum(_int_value(value) for value in tool_counts.values()),
        "tool_call_count": sum(
            _int_value(value) for key, value in tool_counts.items() if str(key).endswith(":request")
        ),
        "tool_event_counts": dict(tool_counts),
        "comparison_tool_counts": _comparison_tool_counts(tool_counts),
        "first_relevant_evidence": _first_relevant_evidence(trace_events),
        "first_actionable_object_discovery": _first_actionable_object_discovery(
            trace_events,
            run_result=run_result,
        ),
        "prior_use_verdict": _prior_use_verdict(run_result, trace_events=trace_events),
        "wall_time_s": _first_available_number(
            timing_payload,
            (
                "wall_time_s",
                "elapsed_s",
                "duration_s",
                "runner_wall_time_s",
                "total_elapsed_s",
            ),
        ),
        "live_status": {
            "phase": str(live_status.get("phase") or MISSING_UNAVAILABLE),
            "exit_status": live_status.get("exit_status", MISSING_UNAVAILABLE),
            "reason": str(live_status.get("reason") or MISSING_UNAVAILABLE),
            "provider_reason": str(live_status.get("provider_reason") or MISSING_UNAVAILABLE),
            "retryable": live_status.get("retryable", MISSING_UNAVAILABLE),
        },
        "model_attempt_summary": model_attempt_summary,
    }


def _model_attempt_summary(run_result: dict[str, Any]) -> dict[str, Any]:
    for key in ("model_attempt_summary", "model_service_summary", "live_timing"):
        value = run_result.get(key)
        if isinstance(value, dict):
            return _compact_model_attempt_summary(value)
    return {
        "attempt_count": MISSING_UNAVAILABLE,
        "success_count": MISSING_UNAVAILABLE,
        "failure_count": MISSING_UNAVAILABLE,
        "provider_reasons": {},
    }


def _compact_model_attempt_summary(value: dict[str, Any]) -> dict[str, Any]:
    live_summary = _model_attempt_summary_from_live_timing(value)
    if live_summary:
        return live_summary
    attempts = _int_or_missing(
        value.get("attempt_count")
        or value.get("model_service_attempt_count")
        or value.get("total_attempts")
    )
    successes = _int_or_missing(
        value.get("success_count")
        or value.get("model_service_success_count")
        or value.get("successful_attempts")
    )
    failures = _int_or_missing(
        value.get("failure_count")
        or value.get("model_service_failure_count")
        or value.get("failed_attempts")
    )
    provider_reasons = value.get("provider_reasons")
    if not isinstance(provider_reasons, dict):
        provider_reasons = {}
    return {
        "attempt_count": attempts,
        "success_count": successes,
        "failure_count": failures,
        "provider_reasons": dict(provider_reasons),
    }


def _model_attempt_summary_from_live_timing(value: dict[str, Any]) -> dict[str, Any]:
    fallback = _nested_mapping(
        value,
        "timeline",
        "latency_attribution",
        "model_service_fallback_metrics",
    )
    attempts_list = value.get("openai_agents_attempts")
    if not isinstance(attempts_list, list):
        attempts_list = []
    if fallback:
        attempt_count = _int_or_missing(
            fallback.get("attempt_event_count")
            or fallback.get("attempt_count")
            or len(attempts_list)
        )
        success_count = _int_or_missing(
            fallback.get("success_event_count")
            or fallback.get("success_count")
            or _live_attempt_status_count(attempts_list, "finished")
        )
        failure_count = _int_or_missing(
            fallback.get("failure_event_count")
            or fallback.get("failure_count")
            or _live_attempt_failure_count(attempts_list)
        )
        provider_reasons = fallback.get("provider_reasons")
        if not isinstance(provider_reasons, dict):
            provider_reasons = {}
        return {
            "attempt_count": attempt_count,
            "success_count": success_count,
            "failure_count": failure_count,
            "provider_reasons": dict(provider_reasons),
        }
    if attempts_list:
        return {
            "attempt_count": len(attempts_list),
            "success_count": _live_attempt_status_count(attempts_list, "finished"),
            "failure_count": _live_attempt_failure_count(attempts_list),
            "provider_reasons": _live_provider_reasons(attempts_list),
        }
    return {}


def _merged_live_status(*, run_dir: Path, run_result: dict[str, Any]) -> tuple[dict[str, Any], str]:
    live_status = (
        run_result.get("live_status") if isinstance(run_result.get("live_status"), dict) else {}
    )
    sidecar, sidecar_error = grading_sources.load_optional_json_mapping(
        run_dir / "live_status.json"
    )
    return {**sidecar, **live_status}, sidecar_error


def _live_wall_time_s(live_timing: dict[str, Any]) -> Any:
    runner_timing = _nested_mapping(live_timing, "runner_timing")
    for payload in (
        runner_timing,
        _nested_mapping(live_timing, "timeline"),
        live_timing,
    ):
        value = _first_available_number(
            payload,
            ("total_elapsed_s", "accounted_elapsed_s", "runner_wall_time_s"),
        )
        if value != MISSING_UNAVAILABLE:
            return value
    return MISSING_UNAVAILABLE


def _nested_mapping(payload: dict[str, Any], *keys: str) -> dict[str, Any]:
    current: Any = payload
    for key in keys:
        if not isinstance(current, dict):
            return {}
        current = current.get(key)
    return current if isinstance(current, dict) else {}


def _live_attempt_status_count(attempts: list[Any], phase: str) -> int:
    return sum(
        1
        for attempt in attempts
        if isinstance(attempt, dict)
        and (
            str(attempt.get("phase") or "") == phase
            or (phase == "finished" and attempt.get("exit_status") == 0)
        )
    )


def _live_attempt_failure_count(attempts: list[Any]) -> int:
    return sum(
        1
        for attempt in attempts
        if isinstance(attempt, dict)
        and (
            attempt.get("exit_status") not in {None, 0}
            or str(attempt.get("phase") or "") == "failed"
        )
    )


def _live_provider_reasons(attempts: list[Any]) -> dict[str, int]:
    reasons: dict[str, int] = {}
    for attempt in attempts:
        if not isinstance(attempt, dict):
            continue
        reason = str(attempt.get("provider_reason") or attempt.get("reason") or "").strip()
        if reason:
            reasons[reason] = reasons.get(reason, 0) + 1
    return reasons


def _first_available_number(payload: dict[str, Any], keys: tuple[str, ...]) -> float | str:
    for key in keys:
        value = payload.get(key)
        try:
            return round(float(value), 3)
        except (TypeError, ValueError):
            continue
    return MISSING_UNAVAILABLE


def _int_or_missing(value: Any) -> int | str:
    if value is None:
        return MISSING_UNAVAILABLE
    try:
        return int(value)
    except (TypeError, ValueError):
        return MISSING_UNAVAILABLE


def _status_from_graders(grader_outputs: dict[str, Any]) -> tuple[str, str]:
    ordered_failures = (
        ("artifacts", "artifact_missing"),
        ("privacy", "private_truth_leak"),
        ("trajectory", "trajectory_policy_violation"),
        (long_horizon_contract.LONG_HORIZON_GRADER_NAME, "private_goal_not_satisfied"),
        ("sampler_admission", "map_actionability_failure"),
        ("open_ended", "agent_no_completion_claim"),
        ("outcome", "private_goal_not_satisfied"),
        ("efficiency", "artifact_missing"),
    )
    for grader_name, failure_class in ordered_failures:
        grader = grader_outputs.get(grader_name, {})
        if grader.get("status") == "failed":
            return "failed", str(grader.get("failure_class") or failure_class)
    long_horizon = grader_outputs.get(long_horizon_contract.LONG_HORIZON_GRADER_NAME, {})
    if long_horizon.get("status") == "inconclusive":
        return "inconclusive", str(long_horizon.get("failure_class") or "grader_inconclusive")
    return "passed", MISSING_NOT_APPLICABLE


def _diagnostic_status_from_graders(grader_outputs: dict[str, Any]) -> str:
    artifacts = grader_outputs.get("artifacts")
    if not isinstance(artifacts, dict):
        return "incomplete"
    return "ready" if artifacts.get("status") == "passed" else "incomplete"


def _metrics_from_graders(
    grader_outputs: dict[str, Any],
    *,
    status: str,
    run_result: dict[str, Any],
) -> dict[str, Any]:
    score = run_result.get("score") if isinstance(run_result.get("score"), dict) else {}
    efficiency = grader_outputs["efficiency"]
    return {
        "pass": 1.0 if status == "passed" else 0.0,
        "private_truth_leak_count": grader_outputs["privacy"]["private_truth_leak_count"],
        "trajectory_policy_violation_count": grader_outputs["trajectory"]["violation_count"],
        "mess_restoration_rate": score.get("mess_restoration_rate", MISSING_UNAVAILABLE),
        "open_ended_artifact_readiness": grader_outputs["open_ended"].get(
            "artifact_readiness",
            MISSING_NOT_APPLICABLE,
        ),
        **long_horizon_contract.metric_fields(grader_outputs),
        "tool_event_count": efficiency["tool_event_count"],
        "tool_call_count": efficiency.get("tool_call_count", 0),
        "tool_event_counts": efficiency.get("tool_event_counts", {}),
        "comparison_tool_counts": efficiency.get("comparison_tool_counts", {}),
        "first_relevant_evidence": efficiency.get("first_relevant_evidence", {}),
        "first_actionable_object_discovery": efficiency.get(
            "first_actionable_object_discovery",
            {},
        ),
        "prior_use_verdict": efficiency.get("prior_use_verdict", "prior_ignored"),
        "wall_time_s": efficiency.get("wall_time_s", MISSING_UNAVAILABLE),
        "model_attempt_summary": efficiency.get(
            "model_attempt_summary",
            {},
        ),
    }


def _comparison_tool_counts(tool_counts: dict[str, Any]) -> dict[str, int]:
    return {
        tool: int(tool_counts.get(f"{tool}:request") or 0)
        for tool in (
            "observe",
            "adjust_camera",
            "navigate_to_waypoint",
            "navigate_to_relative_pose",
        )
    }


def _first_relevant_evidence(trace_events: list[dict[str, Any]]) -> dict[str, Any]:
    for index, event in enumerate(trace_events, start=1):
        if event.get("event") != "response":
            continue
        if event.get("tool") not in {
            "observe",
            "resolve_target_query",
            "declare_visual_candidates",
        }:
            continue
        return {
            "step": index,
            "tool": str(event.get("tool") or ""),
            "wallclock_elapsed": event.get("wallclock_elapsed", MISSING_UNAVAILABLE),
        }
    return {"step": MISSING_UNAVAILABLE, "tool": MISSING_UNAVAILABLE}


def _first_actionable_object_discovery(
    trace_events: list[dict[str, Any]],
    *,
    run_result: dict[str, Any],
) -> dict[str, Any]:
    for index, event in enumerate(trace_events, start=1):
        if event.get("event") != "response" or event.get("tool") != "observe":
            continue
        response = event.get("response") if isinstance(event.get("response"), dict) else event
        for detection in grading_sources.list_of_mappings(
            response.get("visible_object_detections")
        ):
            if str(detection.get("candidate_state") or "") == "navigation_authorized":
                return {
                    "step": index,
                    "tool": "observe",
                    "object_id": str(detection.get("object_id") or ""),
                    "wallclock_elapsed": event.get("wallclock_elapsed", MISSING_UNAVAILABLE),
                }
    observed = (
        run_result.get("runtime_metric_map", {}).get("observed_objects")
        if isinstance(run_result.get("runtime_metric_map"), dict)
        else []
    )
    for item in grading_sources.list_of_mappings(observed):
        if str(item.get("actionability") or "") == "actionable":
            return {
                "step": MISSING_UNAVAILABLE,
                "tool": "runtime_metric_map",
                "object_id": str(item.get("object_id") or ""),
            }
    return {"step": MISSING_UNAVAILABLE, "tool": MISSING_UNAVAILABLE}


def _prior_use_verdict(
    run_result: dict[str, Any],
    *,
    trace_events: list[dict[str, Any]],
) -> str:
    prior = (
        run_result.get("runtime_metric_map_prior")
        if isinstance(run_result.get("runtime_metric_map_prior"), dict)
        else {}
    )
    if not prior.get("loaded"):
        return "prior_ignored"
    runtime_map = (
        run_result.get("runtime_metric_map")
        if isinstance(run_result.get("runtime_metric_map"), dict)
        else {}
    )
    observed_objects = grading_sources.list_of_mappings(runtime_map.get("observed_objects"))
    if any(str(item.get("freshness") or "") == "prior" for item in observed_objects):
        unsafe = any(
            str(item.get("actionability") or "") == "actionable"
            for item in observed_objects
            if str(item.get("freshness") or "") == "prior"
        )
        if unsafe:
            return "unsafe_prior_use"
    if any(item.get("prior_match_basis") for item in observed_objects):
        return "movable_hint_rechecked"
    anchors = grading_sources.list_of_mappings(runtime_map.get("public_semantic_anchors"))
    if anchors and int(prior.get("anchor_prior_count") or 0) > 0:
        return "stable_anchor_used"
    target_queries = [
        event
        for event in trace_events
        if event.get("tool") == "resolve_target_query" and event.get("event") == "response"
    ]
    if target_queries:
        return "stable_anchor_used"
    return "prior_ignored"


def _int_value(value: Any) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return 0
