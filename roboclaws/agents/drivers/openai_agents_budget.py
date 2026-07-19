"""Budget guards and advisories for the experimental OpenAI Agents SDK runtime."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from roboclaws.agents.live_status import LiveAgentFailure
from roboclaws.core.json_sources import read_jsonl_objects


class OpenAIAgentsBudgetExceededError(RuntimeError):
    """Raised inside SDK hooks when Roboclaws-owned budget guards trip."""

    def __init__(self, failure: LiveAgentFailure) -> None:
        self.failure = failure
        super().__init__(f"{failure.reason}: {failure.detail}")


def openai_agents_budget_failure(
    run_dir: Path,
    timing: dict[str, Any],
    profile: dict[str, Any],
    *,
    context_spans_path: Path | None = None,
) -> LiveAgentFailure | None:
    context_failure = context_budget_failure(
        run_dir,
        timing,
        profile,
        context_spans_path=context_spans_path,
    )
    if context_failure is not None:
        return context_failure
    return raw_fpv_budget_failure(run_dir, timing, profile)


def openai_agents_observe_budget_advisory(
    run_dir: Path,
    timing: dict[str, Any],
    profile: dict[str, Any],
) -> dict[str, Any] | None:
    observe_budget = _int_or_none(profile.get("max_observe_per_waypoint"))
    if observe_budget is None:
        return None
    trace_events = _read_jsonl_path(run_dir / "trace.jsonl")
    if not trace_events:
        return None
    metrics = raw_fpv_budget_metrics(trace_events)
    over_budget = _observe_over_budget(
        metrics.get("observe_count_by_waypoint") or {},
        observe_budget=observe_budget,
    )
    if not over_budget:
        return None
    return {
        "schema": "agent_sdk_observe_budget_advisory_v1",
        "reason": "observe_budget_exceeded",
        "profile_id": profile.get("profile_id") or "baseline",
        "evidence_lane": timing.get("evidence_lane") or timing.get("profile") or "",
        "max_observe_per_waypoint": observe_budget,
        "observe_count_by_waypoint": metrics["observe_count_by_waypoint"],
        "observe_over_budget_by_waypoint": over_budget,
    }


def context_budget_failure(
    run_dir: Path,
    timing: dict[str, Any],
    profile: dict[str, Any],
    *,
    context_spans_path: Path | None = None,
) -> LiveAgentFailure | None:
    hard_limit = _int_or_none(profile.get("context_hard_limit_tokens"))
    if hard_limit is None:
        return None
    context_metrics = openai_agents_context_budget_metrics(
        run_dir,
        context_spans_path=context_spans_path,
    )
    current_input = _int_or_none(context_metrics.get("max_input_tokens"))
    if current_input is None or current_input < hard_limit:
        return None
    detail = json.dumps(
        {
            "schema": "agent_sdk_context_budget_terminal_v1",
            "profile_id": profile.get("profile_id") or "baseline",
            "context_hard_limit_tokens": hard_limit,
            "current_input_tokens": current_input,
            "max_input_tokens": current_input,
            "total_input_tokens": context_metrics.get("total_input_tokens"),
            "total_uncached_input_tokens": context_metrics.get("total_uncached_input_tokens"),
            "response_span_count": context_metrics.get("response_span_count"),
            "evidence_source": context_metrics.get("source") or "unavailable",
            "evidence_lane": timing.get("evidence_lane") or timing.get("profile") or "",
        },
        sort_keys=True,
    )
    return LiveAgentFailure(
        "provider_context_budget_exceeded",
        retryable=False,
        resume_available=False,
        detail=detail,
    )


def raw_fpv_budget_failure(
    run_dir: Path,
    timing: dict[str, Any],
    profile: dict[str, Any],
) -> LiveAgentFailure | None:
    lane = str(timing.get("evidence_lane") or timing.get("profile") or "")
    raw_fpv_lane = lane == "camera-raw-fpv"
    limits = _raw_fpv_budget_limits(profile)
    if not limits:
        return None
    if not raw_fpv_lane:
        limits["candidate_budget"] = None
        limits["repeated_failure_limit"] = None
    trace_events = _read_jsonl_path(run_dir / "trace.jsonl")
    if not trace_events:
        return None
    metrics = raw_fpv_budget_metrics(trace_events)
    reasons = _raw_fpv_budget_reasons(metrics, limits)
    if not reasons:
        return None
    detail = json.dumps(
        {
            "schema": "agent_sdk_raw_fpv_budget_terminal_v1",
            "profile_id": profile.get("profile_id") or "baseline",
            "evidence_lane": lane,
            "reasons": reasons,
            "raw_fpv_candidate_budget": limits["candidate_budget"],
            "raw_fpv_repeated_failure_limit": limits["repeated_failure_limit"],
            "max_observe_per_waypoint": limits["observe_budget"],
            **metrics,
        },
        sort_keys=True,
    )
    return LiveAgentFailure(
        _primary_raw_fpv_budget_reason(reasons),
        retryable=False,
        resume_available=False,
        detail=detail,
    )


def openai_agents_context_budget_metrics(
    run_dir: Path,
    *,
    context_spans_path: Path | None = None,
) -> dict[str, Any]:
    response_spans = _response_span_end_events(run_dir, spans_path=context_spans_path)
    if not response_spans:
        return {
            "available": False,
            "source": "unavailable",
            "limitations": ["span_usage_missing"],
        }
    usage_rows: list[dict[str, int]] = []
    limitations: list[str] = []
    for event in response_spans:
        usage = event.get("usage") if isinstance(event.get("usage"), dict) else {}
        if not usage:
            limitations.append("response_span_usage_missing")
            continue
        input_tokens = _int_or_none(usage.get("input_tokens"))
        if input_tokens is None:
            limitations.append("response_span_input_tokens_missing")
            continue
        cached_tokens = min(max(_cached_input_tokens(usage), 0), input_tokens)
        usage_rows.append({"input_tokens": input_tokens, "cached_tokens": cached_tokens})
    if not usage_rows:
        return {
            "available": False,
            "source": "openai_agents_span_usage",
            "limitations": sorted(set(limitations or ["span_usage_missing"])),
            "response_span_count": len(response_spans),
        }
    input_values = [row["input_tokens"] for row in usage_rows]
    total_input = sum(input_values)
    total_cached = sum(row["cached_tokens"] for row in usage_rows)
    return {
        "available": True,
        "source": "openai_agents_span_usage",
        "limitations": sorted(set(limitations)),
        "response_span_count": len(usage_rows),
        "total_input_tokens": total_input,
        "total_cached_input_tokens": total_cached,
        "total_uncached_input_tokens": max(0, total_input - total_cached),
        "max_input_tokens": max(input_values),
    }


def raw_fpv_budget_metrics(trace_events: list[dict[str, Any]]) -> dict[str, Any]:
    candidate_attempts: list[dict[str, str]] = []
    observe_count_by_waypoint: dict[str, int] = {}
    observation_waypoints: dict[str, str] = {}
    observation_view_scopes: dict[str, str] = {}
    failure_fingerprints: dict[str, int] = {}
    failure_fingerprint_details: dict[str, dict[str, str]] = {}
    failed_candidate_attempts: list[dict[str, str]] = []
    pending_requests: dict[str, list[dict[str, Any]]] = {}
    for event in trace_events:
        tool = str(event.get("tool") or "")
        event_type = str(event.get("event") or "")
        if tool == "observe" and event_type == "response":
            _record_observe_response(event, observe_count_by_waypoint)
            _record_observation_context(
                event,
                observation_waypoints,
                observation_view_scopes,
            )
            continue
        if tool not in {"navigate_to_visual_candidate", "declare_visual_candidates"}:
            continue
        if event_type == "request":
            request = event.get("request") if isinstance(event.get("request"), dict) else {}
            pending_requests.setdefault(tool, []).append(request)
            raw_event = _raw_fpv_candidate_event(
                event,
                observation_waypoints=observation_waypoints,
                observation_view_scopes=observation_view_scopes,
            )
        elif event_type == "response":
            pending_request = pending_requests[tool].pop(0) if pending_requests.get(tool) else {}
            request = (
                event.get("request") if isinstance(event.get("request"), dict) else {}
            ) or pending_request
            raw_event = _raw_fpv_candidate_event(
                event,
                request_override=request,
                observation_waypoints=observation_waypoints,
                observation_view_scopes=observation_view_scopes,
            )
        else:
            continue
        if raw_event is None:
            continue
        if event_type == "request":
            candidate_attempts.append(raw_event.attempt)
        if event_type == "response" and raw_event.failure_reason:
            failed_candidate_attempts.append(raw_event.detail)
            failure_fingerprints[raw_event.fingerprint] = (
                failure_fingerprints.get(raw_event.fingerprint, 0) + 1
            )
            failure_fingerprint_details.setdefault(raw_event.fingerprint, raw_event.detail)
    return {
        "candidate_attempt_count": len(candidate_attempts),
        "candidate_attempts_sample": candidate_attempts[-12:],
        "failed_candidate_attempts_sample": failed_candidate_attempts[-12:],
        "observe_count_by_waypoint": dict(sorted(observe_count_by_waypoint.items())),
        "repeated_failure_fingerprints": _repeated_failure_fingerprints(
            failure_fingerprints,
            failure_fingerprint_details,
        ),
    }


class _RawFpvCandidateEvent:
    def __init__(
        self,
        *,
        source_id: str,
        category: str,
        region: str,
        semantic_region: str,
        waypoint_id: str,
        view_scope: str,
        candidate_id: str,
        failure_reason: str,
    ) -> None:
        self.failure_reason = failure_reason
        self.attempt = {
            "source_observation_id": source_id,
            "category": category,
            "region": region,
            "candidate_id": candidate_id,
        }
        stable_scope = view_scope or source_id or waypoint_id
        self.fingerprint = "|".join(
            (stable_scope, category, semantic_region or region, candidate_id, failure_reason)
        )
        self.detail = {
            "source_observation_id": source_id,
            "waypoint_id": waypoint_id,
            "category": category,
            "region": semantic_region or region,
            "candidate_id": candidate_id,
            "failure_reason": failure_reason,
        }


def _response_span_end_events(
    run_dir: Path,
    *,
    spans_path: Path | None = None,
) -> list[dict[str, Any]]:
    events: list[dict[str, Any]] = []
    paths = (
        [spans_path]
        if spans_path is not None
        else sorted(run_dir.glob("openai-agents-spans*.jsonl"))
    )
    for path in paths:
        if not path.is_file():
            continue
        for event in read_jsonl_objects(path, label="OpenAI Agents budget span"):
            if event.get("event") == "span_end" and event.get("span_type") == "response":
                events.append(event)
    return events


def _cached_input_tokens(usage: dict[str, Any]) -> int:
    details = usage.get("input_tokens_details")
    if isinstance(details, dict):
        nested = _int_or_none(details.get("cached_tokens"))
        if nested is not None:
            return nested
    return _int_or_none(usage.get("cached_input_tokens")) or 0


def _raw_fpv_budget_limits(profile: dict[str, Any]) -> dict[str, int | None]:
    limits = {
        "candidate_budget": _int_or_none(profile.get("raw_fpv_candidate_budget")),
        "repeated_failure_limit": _int_or_none(profile.get("raw_fpv_repeated_failure_limit")),
        "observe_budget": _int_or_none(profile.get("max_observe_per_waypoint")),
    }
    return {} if all(value is None for value in limits.values()) else limits


def _raw_fpv_budget_reasons(
    metrics: dict[str, Any],
    limits: dict[str, int | None],
) -> list[str]:
    reasons: list[str] = []
    repeated_failure_limit = limits["repeated_failure_limit"]
    if repeated_failure_limit is not None:
        repeated_failures = [
            item
            for item in metrics["repeated_failure_fingerprints"]
            if int(item.get("count") or 0) >= repeated_failure_limit
        ]
        if repeated_failures:
            metrics["repeated_failure_limit"] = repeated_failure_limit
            metrics["repeated_failure_limit_hits"] = repeated_failures[:12]
            reasons.append("raw_fpv_repeated_candidate_failure")
    candidate_budget = limits["candidate_budget"]
    if candidate_budget is not None and metrics["candidate_attempt_count"] >= candidate_budget:
        reasons.append("raw_fpv_candidate_budget_exhausted")
    return reasons


def _primary_raw_fpv_budget_reason(reasons: list[str]) -> str:
    for reason in (
        "raw_fpv_repeated_candidate_failure",
        "raw_fpv_candidate_budget_exhausted",
    ):
        if reason in reasons:
            return reason
    return "raw_fpv_candidate_budget_exhausted"


def _record_observe_response(
    event: dict[str, Any],
    observe_count_by_waypoint: dict[str, int],
) -> None:
    response = event.get("response") if isinstance(event.get("response"), dict) else {}
    if response.get("ok") is not True:
        return
    waypoint_id = _waypoint_from_response(response)
    if not waypoint_id or waypoint_id == "unknown":
        return
    observe_count_by_waypoint[waypoint_id] = observe_count_by_waypoint.get(waypoint_id, 0) + 1


def _record_observation_context(
    event: dict[str, Any],
    observation_waypoints: dict[str, str],
    observation_view_scopes: dict[str, str],
) -> None:
    response = event.get("response") if isinstance(event.get("response"), dict) else {}
    if response.get("ok") is not True:
        return
    raw = (
        response.get("raw_fpv_observation")
        if isinstance(response.get("raw_fpv_observation"), dict)
        else {}
    )
    observation_id = str(raw.get("observation_id") or response.get("observation_id") or "")
    waypoint_id = _waypoint_from_response(response)
    if observation_id and waypoint_id and waypoint_id != "unknown":
        observation_waypoints[observation_id] = waypoint_id
        observation_view_scopes[observation_id] = _observation_view_scope(
            waypoint_id,
            raw,
        )


def _observation_view_scope(waypoint_id: str, raw: dict[str, Any]) -> str:
    camera_offset = raw.get("camera_offset") if isinstance(raw.get("camera_offset"), dict) else {}
    camera_contract = (
        raw.get("camera_control_contract")
        if isinstance(raw.get("camera_control_contract"), dict)
        else {}
    )
    robot_pose = (
        camera_contract.get("robot_pose")
        if isinstance(camera_contract.get("robot_pose"), dict)
        else {}
    )
    values = [
        camera_offset.get("yaw_delta_deg"),
        camera_offset.get("pitch_delta_deg"),
        robot_pose.get("x"),
        robot_pose.get("y"),
        robot_pose.get("theta"),
        robot_pose.get("head_yaw"),
        robot_pose.get("head_pitch"),
    ]
    normalized: list[str] = []
    for value in values:
        try:
            normalized.append(f"{float(value):.3f}")
        except (TypeError, ValueError):
            normalized.append("")
    return "|".join([waypoint_id, *normalized]) if any(normalized) else waypoint_id


def _observe_over_budget(
    observe_count_by_waypoint: dict[str, Any],
    *,
    observe_budget: int,
) -> dict[str, int]:
    return {
        str(waypoint_id): int(count)
        for waypoint_id, count in sorted(observe_count_by_waypoint.items())
        if waypoint_id and int(count) > observe_budget
    }


def _raw_fpv_candidate_event(
    event: dict[str, Any],
    *,
    request_override: dict[str, Any] | None = None,
    observation_waypoints: dict[str, str] | None = None,
    observation_view_scopes: dict[str, str] | None = None,
) -> _RawFpvCandidateEvent | None:
    request = request_override or (
        event.get("request") if isinstance(event.get("request"), dict) else {}
    )
    response = event.get("response") if isinstance(event.get("response"), dict) else {}
    source_id = str(
        request.get("source_observation_id")
        or request.get("observation_id")
        or response.get("observation_id")
        or response.get("source_observation_id")
        or ""
    )
    if not source_id and "raw_fpv" not in json.dumps(event, sort_keys=True, ensure_ascii=True):
        return None
    category = str(request.get("category") or response.get("category") or "")
    region = _region_fingerprint(request.get("image_region"))
    semantic_region = _semantic_region_fingerprint(request.get("image_region"))
    candidate_id = str(request.get("candidate_id") or request.get("object_id") or "")
    failure_reason = _candidate_failure_reason(response)
    waypoint_id = str((observation_waypoints or {}).get(source_id) or "")
    view_scope = str((observation_view_scopes or {}).get(source_id) or "")
    return _RawFpvCandidateEvent(
        source_id=source_id,
        category=category,
        region=region,
        semantic_region=semantic_region,
        waypoint_id=waypoint_id,
        view_scope=view_scope,
        candidate_id=candidate_id,
        failure_reason=failure_reason,
    )


def _candidate_failure_reason(response: dict[str, Any]) -> str:
    if not response or response.get("ok") is True:
        return ""
    explicit = str(response.get("error_reason") or response.get("failure_reason") or "")
    if explicit:
        return explicit
    status = str(response.get("status") or "")
    return "" if status in {"", "ok", "success", "finished"} else status


def _semantic_region_fingerprint(value: Any) -> str:
    if not isinstance(value, dict) or value.get("type") != "bbox":
        return _region_fingerprint(value)
    raw = value.get("value")
    if not isinstance(raw, list) or len(raw) != 4:
        return _region_fingerprint(value)
    try:
        numbers = [float(item) for item in raw]
    except (TypeError, ValueError):
        return _region_fingerprint(value)
    quantum = 0.02 if all(abs(item) <= 1.0 for item in numbers) else 8.0
    buckets = [round(number / quantum) for number in numbers]
    return "bbox:" + ",".join(str(item) for item in buckets)


def _repeated_failure_fingerprints(
    failure_fingerprints: dict[str, int],
    failure_fingerprint_details: dict[str, dict[str, str]],
) -> list[dict[str, Any]]:
    return [
        {
            "fingerprint": key,
            "count": count,
            **failure_fingerprint_details.get(key, {}),
        }
        for key, count in sorted(failure_fingerprints.items())
        if count > 1
    ][:12]


def _waypoint_from_response(response: dict[str, Any]) -> str:
    waypoint_id = str(response.get("waypoint_id") or "")
    if waypoint_id:
        return waypoint_id
    raw_payload = response.get("raw_fpv_observation")
    raw = raw_payload if isinstance(raw_payload, dict) else {}
    return str(raw.get("waypoint_id") or "unknown")


def _region_fingerprint(value: Any) -> str:
    if isinstance(value, dict):
        region_type = str(value.get("type") or "")
        region_value = value.get("value")
        if isinstance(region_value, list):
            compact = ",".join(str(item) for item in region_value[:4])
        else:
            compact = str(region_value or "")
        return f"{region_type}:{compact}"[:120]
    return str(value or "")[:120]


def _read_jsonl_path(path: Path) -> list[dict[str, Any]]:
    if not path.is_file():
        return []
    return read_jsonl_objects(path, label="OpenAI Agents budget trace")


def _int_or_none(value: Any) -> int | None:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None
