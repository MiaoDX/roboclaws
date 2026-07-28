"""Live-agent timing artifacts and latency timeline helpers."""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from roboclaws.core.json_sources import read_json_object, read_json_value, read_jsonl_objects
from roboclaws.household.report_sections_timing import runtime_timing_from_trace


def runner_timing_breakdown(timing: dict[str, Any], finished_at: float) -> dict[str, Any]:
    started = _float_or_none(timing.get("started_at_epoch"))
    sdk_start = _float_or_none(timing.get("openai_agents_start_epoch"))
    sdk_end = _float_or_none(timing.get("openai_agents_end_epoch"))
    checker_start = _float_or_none(timing.get("checker_start_epoch"))
    checker_end = _float_or_none(timing.get("checker_end_epoch"))
    server_start = _float_or_none(timing.get("server_start_epoch"))
    server_ready = _float_or_none(timing.get("server_ready_epoch"))
    server_finished = _float_or_none(timing.get("server_finished_epoch"))
    total = round_duration(finished_at - started) if started is not None else None

    segments: dict[str, float] = {}
    if started is not None and sdk_start is not None:
        segments["pre_agent_setup_s"] = round_duration(sdk_start - started)
    if sdk_start is not None and sdk_end is not None:
        segments["openai_agents_elapsed_s"] = round_duration(sdk_end - sdk_start)
    if sdk_end is not None and server_finished is not None:
        segments["post_agent_server_wait_s"] = round_duration(server_finished - sdk_end)
    if checker_start is not None and checker_end is not None:
        segments["checker_elapsed_s"] = round_duration(checker_end - checker_start)
    if checker_end is not None:
        segments["final_overhead_s"] = round_duration(finished_at - checker_end)
    if server_start is not None and server_ready is not None:
        segments["server_startup_s"] = round_duration(server_ready - server_start)

    partition_keys = (
        "pre_agent_setup_s",
        "openai_agents_elapsed_s",
        "post_agent_server_wait_s",
        "checker_elapsed_s",
        "final_overhead_s",
    )
    accounted = sum(segments.get(key, 0.0) for key in partition_keys)
    breakdown: dict[str, Any] = {"total_elapsed_s": total, **segments}
    if total is not None:
        breakdown["accounted_elapsed_s"] = round_duration(accounted)
        breakdown["unaccounted_elapsed_s"] = round_duration(max(0.0, total - accounted))
        breakdown["accounting_note"] = (
            "The partitioned runner buckets sum to total wall time. MCP trace timing "
            "runs inside openai_agents_elapsed_s and is reported separately to avoid "
            "double counting concurrent server work."
        )
    return breakdown


def codex_runner_timing_breakdown(timing: dict[str, Any], finished_at: float) -> dict[str, Any]:
    started = _float_or_none(timing.get("started_at_epoch"))
    codex_start = _float_or_none(timing.get("codex_exec_start_epoch"))
    codex_end = _float_or_none(timing.get("codex_exec_end_epoch"))
    checker_start = _float_or_none(timing.get("checker_start_epoch"))
    checker_end = _float_or_none(timing.get("checker_end_epoch"))
    server_start = _float_or_none(timing.get("server_start_epoch"))
    server_ready = _float_or_none(timing.get("server_ready_epoch"))
    server_finished = _float_or_none(timing.get("server_finished_epoch"))
    total = round_duration(finished_at - started) if started is not None else None

    segments: dict[str, float] = {}
    if started is not None and codex_start is not None:
        segments["pre_codex_setup_s"] = round_duration(codex_start - started)
    if codex_start is not None and codex_end is not None:
        segments["codex_exec_elapsed_s"] = round_duration(codex_end - codex_start)
    if codex_end is not None and server_finished is not None:
        segments["post_codex_server_wait_s"] = round_duration(server_finished - codex_end)
    if checker_start is not None and checker_end is not None:
        segments["checker_elapsed_s"] = round_duration(checker_end - checker_start)
    if checker_end is not None:
        segments["final_overhead_s"] = round_duration(finished_at - checker_end)
    if server_start is not None and server_ready is not None:
        segments["server_startup_s"] = round_duration(server_ready - server_start)

    partition_keys = (
        "pre_codex_setup_s",
        "codex_exec_elapsed_s",
        "post_codex_server_wait_s",
        "checker_elapsed_s",
        "final_overhead_s",
    )
    accounted = sum(segments.get(key, 0.0) for key in partition_keys)
    breakdown: dict[str, Any] = {"total_elapsed_s": total, **segments}
    if total is not None:
        breakdown["accounted_elapsed_s"] = round_duration(accounted)
        breakdown["unaccounted_elapsed_s"] = round_duration(max(0.0, total - accounted))
        breakdown["accounting_note"] = (
            "The partitioned runner buckets sum to total wall time. MCP trace timing "
            "runs inside codex_exec_elapsed_s and is reported separately to avoid "
            "double counting concurrent server work."
        )
    return breakdown


def live_timing_timeline(timing: dict[str, Any]) -> dict[str, Any]:
    """Build a normalized timeline for cross-run latency comparisons."""

    finished_at = _float_or_none(timing.get("finished_at_epoch"))
    started_at = _float_or_none(timing.get("started_at_epoch"))
    runner_segments = _runner_timeline_segments(timing, finished_at)
    attempt_segments = _attempt_timeline_segments(timing)
    attribution = _latency_attribution(timing)
    return {
        "schema": "live_agent_timeline_v1",
        "surface": timing.get("surface", ""),
        "intent": timing.get("intent", ""),
        "task_name": timing.get("task_name", ""),
        "runtime": timing.get("runtime", ""),
        "provider_profile": timing.get("provider_profile", ""),
        "wire_api": timing.get("wire_api", ""),
        "model": timing.get("model", ""),
        "evidence_lane": timing.get("evidence_lane") or timing.get("profile", ""),
        "started_at_epoch": started_at,
        "finished_at_epoch": finished_at,
        "total_elapsed_s": (timing.get("runner_timing") or {}).get("total_elapsed_s"),
        "runner_segments": runner_segments,
        "openai_agents_attempt_segments": attempt_segments,
        "latency_attribution": attribution,
        "notes": [
            "runner_segments partition end-to-end wall clock.",
            (
                "latency_attribution nests MCP trace attribution inside the SDK agent window; "
                "do not add it to runner_segments as extra wall time."
            ),
            (
                "between_tool_gap_s is the response-to-next-request window and includes model "
                "reasoning, SDK orchestration, transport, and other agent-side delay."
            ),
        ],
    }


def mcp_trace_timing(run_dir: Path) -> dict[str, Any]:
    run_result_path = run_dir / "run_result.json"
    if run_result_path.is_file():
        try:
            run_result = read_json_value(run_result_path, label="OpenAI Agents live run_result")
        except ValueError as exc:
            cause = exc.__cause__
            if not isinstance(cause, json.JSONDecodeError):
                raise
            raise ValueError(
                f"OpenAI Agents live source {run_result_path}: invalid JSON: {cause.msg}"
            ) from exc
        except OSError as exc:
            raise ValueError(
                f"OpenAI Agents live source {run_result_path}: read error: {exc}"
            ) from exc
        if not isinstance(run_result, dict):
            raise ValueError(
                "OpenAI Agents live source "
                f"{run_result_path}: non-object JSON: {type(run_result).__name__}"
            )
        timing = run_result.get("runtime_timing")
        if isinstance(timing, dict):
            return timing
    return runtime_timing_from_trace(_read_jsonl_path(run_dir / "trace.jsonl"))


def codex_mcp_trace_timing(run_dir: Path) -> dict[str, Any]:
    run_result_path = run_dir / "run_result.json"
    if run_result_path.is_file():
        run_result = read_json_object(run_result_path, label="Codex live run_result")
        timing = run_result.get("runtime_timing")
        if isinstance(timing, dict):
            return timing
    return runtime_timing_from_trace(_read_jsonl_path(run_dir / "trace.jsonl", label="Codex live"))


def first_mcp_request_epoch(run_dir: Path, *, label: str = "OpenAI Agents live") -> float | None:
    for event in _read_jsonl_path(run_dir / "trace.jsonl", label=label):
        if event.get("event") == "request" and not str(event.get("tool", "")).startswith("<"):
            return _float_or_none(event.get("ts"))
    return None


def mcp_control_plane_metrics(run_dir: Path) -> dict[str, Any]:
    log_path = run_dir / "openai-agents-server.log"
    if not log_path.is_file():
        return {
            "available": False,
            "reason": "openai-agents-server.log not present",
        }

    request_counts: dict[str, int] = {}
    http_status_counts: dict[str, int] = {}
    session_create_count = 0
    session_termination_count = 0
    trace_export_skip_count = 0
    line_count = 0
    for line in log_path.read_text(encoding="utf-8", errors="replace").splitlines():
        line_count += 1
        request_match = re.search(r"Processing request of type ([A-Za-z0-9_]+)", line)
        if request_match:
            request_type = request_match.group(1)
            request_counts[request_type] = request_counts.get(request_type, 0) + 1
        status_match = re.search(r'HTTP/[^"]+"\s+([0-9]{3})\s+([A-Za-z][A-Za-z ]*)$', line)
        if status_match:
            status_key = f"{status_match.group(1)} {status_match.group(2).strip()}"
            http_status_counts[status_key] = http_status_counts.get(status_key, 0) + 1
        if "Created new transport with session ID:" in line:
            session_create_count += 1
        if "Terminating session:" in line:
            session_termination_count += 1
        if "OPENAI_API_KEY is not set, skipping trace export" in line:
            trace_export_skip_count += 1

    call_tool_count = request_counts.get("CallToolRequest", 0)
    list_tools_count = request_counts.get("ListToolsRequest", 0)
    total_requests = sum(request_counts.values())
    control_request_count = total_requests - call_tool_count
    return {
        "available": True,
        "log": log_path.name,
        "line_count": line_count,
        "request_type_counts": dict(sorted(request_counts.items())),
        "total_mcp_request_count": total_requests,
        "call_tool_request_count": call_tool_count,
        "list_tools_request_count": list_tools_count,
        "control_request_count": control_request_count,
        "list_tools_per_call_tool": (
            round_duration(list_tools_count / call_tool_count) if call_tool_count else None
        ),
        "streamable_http_session_count": session_create_count,
        "session_termination_count": session_termination_count,
        "trace_export_skip_count": trace_export_skip_count,
        "http_status_counts": dict(sorted(http_status_counts.items())),
        "optimization_note": (
            "Control-plane counts are parsed from the MCP server log. Per-request "
            "control-plane latency is not exposed by the server log yet."
        ),
    }


def model_or_sdk_unattributed_seconds(timing: dict[str, Any]) -> float | None:
    runner_timing = (
        timing.get("runner_timing") if isinstance(timing.get("runner_timing"), dict) else {}
    )
    mcp_timing = (
        timing.get("mcp_trace_timing") if isinstance(timing.get("mcp_trace_timing"), dict) else {}
    )
    context_metrics = (
        timing.get("context_metrics") if isinstance(timing.get("context_metrics"), dict) else {}
    )
    sdk_elapsed = _float_or_none(runner_timing.get("openai_agents_elapsed_s"))
    if sdk_elapsed is None:
        return None
    residual = sdk_elapsed
    mcp_elapsed = _float_or_none(mcp_timing.get("total_elapsed_s"))
    if mcp_elapsed is not None:
        residual -= mcp_elapsed
    if context_metrics.get("available"):
        span_duration = _float_or_none(context_metrics.get("response_span_duration_s"))
        if span_duration is not None:
            residual -= span_duration
    return round_duration(residual)


def compact_metric_group(metrics: dict[str, Any]) -> dict[str, Any]:
    keys = (
        "available",
        "source",
        "limitations",
        "total_input_tokens",
        "total_cached_input_tokens",
        "total_uncached_input_tokens",
        "total_output_tokens",
        "total_reasoning_tokens",
        "cache_hit_ratio",
        "cached_input_token_ratio",
        "provider_prompt_cache_observed",
        "trace_event_count",
        "observe_response_count",
        "raw_fpv_observation_count",
        "tool_response_bytes_total",
        "largest_tool_response_bytes",
        "continuation_attempt_count",
        "attempt_event_count",
        "retry_scheduled_count",
        "failure_event_count",
        "success_event_count",
        "failure_classes",
        "provider_reasons",
        "attempted_models",
        "attempted_provider_profiles",
        "attempted_wire_apis",
        "retry_delay_s_total",
        "retry_delay_count",
        "retry_exhausted",
        "final_outcomes",
        "event_count",
        "event_counts",
        "call_count",
        "arm_count",
        "max_arm_count_per_call",
        "racing_enabled",
        "racing_multiplier",
        "winner_count",
        "cancelled_count",
        "cancellation_observed_count",
        "loser_billing_unknown_count",
        "elapsed_s_total",
        "max_elapsed_s",
        "usage_available_count",
        "usage_missing_count",
        "methods",
        "racing_modes",
        "enabled",
        "modes",
        "compacted_item_count",
        "unchanged_item_count",
        "repeated_item_count",
        "input_bytes_before",
        "input_bytes_after",
        "input_bytes_reduced",
        "input_byte_reduction_ratio",
        "max_input_bytes_before",
        "max_input_bytes_after",
        "max_input_bytes_reduced",
        "metric_map_output_count",
        "repeated_metric_map_output_count",
        "metric_map_delta_compacted_count",
        "metric_map_bytes_before",
        "metric_map_bytes_after",
        "metric_map_bytes_reduced",
        "metric_map_byte_reduction_ratio",
        "raw_fpv_image_memory_enabled",
        "raw_fpv_image_memory_modes",
        "raw_fpv_image_item_count",
        "raw_fpv_image_retained_count",
        "raw_fpv_image_evicted_count",
        "raw_fpv_image_transcoded_count",
        "raw_fpv_image_bytes_before",
        "raw_fpv_image_bytes_after",
        "raw_fpv_image_bytes_reduced",
        "raw_fpv_image_byte_reduction_ratio",
        "completed_tool_history_bundle_count",
        "completed_tool_history_retained_count",
        "completed_tool_history_evicted_count",
        "completed_tool_history_item_count_before",
        "completed_tool_history_item_count_after",
        "completed_tool_history_bytes_reduced",
        "camera_grounded_history_enabled",
        "camera_grounded_history_modes",
        "camera_grounded_history_item_count",
        "camera_grounded_history_retained_count",
        "camera_grounded_history_compacted_count",
        "camera_grounded_history_bytes_before",
        "camera_grounded_history_bytes_after",
        "camera_grounded_history_bytes_reduced",
        "camera_grounded_history_byte_reduction_ratio",
        "reason",
        "provider_reason",
        "retryable",
        "resume_available",
        "detail_schema",
        "raw_fpv_candidate_budget",
        "raw_fpv_repeated_failure_limit",
        "max_observe_per_waypoint",
        "candidate_attempt_count",
        "repeated_failure_count",
        "repeated_failure_limit_hit_count",
        "observe_waypoint_count",
        "detail_source_error",
        "detail_source_error_kind",
    )
    compact = {key: metrics.get(key) for key in keys if key in metrics}
    detail = metrics.get("detail")
    if isinstance(detail, str) and detail:
        parsed, detail_error = _parse_compact_metric_detail(detail)
        if detail_error:
            compact.setdefault("detail_source_error", detail_error["detail_source_error"])
            compact.setdefault(
                "detail_source_error_kind",
                detail_error["detail_source_error_kind"],
            )
        elif parsed is not None:
            compact.setdefault("detail_schema", parsed.get("schema"))
            for key in (
                "raw_fpv_candidate_budget",
                "raw_fpv_repeated_failure_limit",
                "max_observe_per_waypoint",
                "candidate_attempt_count",
            ):
                if key in parsed:
                    compact.setdefault(key, parsed.get(key))
            repeated = parsed.get("repeated_failure_fingerprints")
            if isinstance(repeated, list):
                compact.setdefault("repeated_failure_count", len(repeated))
            hits = parsed.get("repeated_failure_limit_hits")
            if isinstance(hits, list):
                compact.setdefault("repeated_failure_limit_hit_count", len(hits))
            observe_counts = parsed.get("observe_count_by_waypoint")
            if isinstance(observe_counts, dict):
                compact.setdefault("observe_waypoint_count", len(observe_counts))
    return compact


def _runner_timeline_segments(
    timing: dict[str, Any],
    finished_at: float | None,
) -> list[dict[str, Any]]:
    started_at = _float_or_none(timing.get("started_at_epoch"))
    sdk_start = _float_or_none(timing.get("openai_agents_start_epoch"))
    sdk_end = _float_or_none(timing.get("openai_agents_end_epoch"))
    server_finished = _float_or_none(timing.get("server_finished_epoch"))
    checker_start = _float_or_none(timing.get("checker_start_epoch"))
    checker_end = _float_or_none(timing.get("checker_end_epoch"))
    segments = [
        _timeline_segment(
            "pre_agent_setup",
            "runner",
            started_at,
            sdk_start,
            "Launcher setup, lock acquisition, MCP server startup, and readiness wait.",
        ),
        _timeline_segment(
            "openai_agents_runtime",
            "sdk_agent",
            sdk_start,
            sdk_end,
            "OpenAI Agents SDK execution window including model calls and MCP tool use.",
        ),
        _timeline_segment(
            "post_agent_server_wait",
            "runner",
            sdk_end,
            server_finished,
            "Wait for the cleanup MCP server to flush artifacts and exit after done.",
        ),
        _timeline_segment(
            "checker",
            "verification",
            checker_start,
            checker_end,
            "Cleanup artifact checker.",
        ),
        _timeline_segment(
            "final_overhead",
            "runner",
            checker_end,
            finished_at,
            "Final timing/status write.",
        ),
    ]
    return [segment for segment in segments if segment is not None]


def _attempt_timeline_segments(timing: dict[str, Any]) -> list[dict[str, Any]]:
    segments: list[dict[str, Any]] = []
    attempts = timing.get("openai_agents_attempts")
    if not isinstance(attempts, list):
        return segments
    for attempt in attempts:
        if not isinstance(attempt, dict):
            continue
        attempt_index = _int_or_none(attempt.get("attempt_index"))
        label = "sdk_attempt"
        if attempt_index is not None:
            label = f"sdk_attempt_{attempt_index}"
        segment = _timeline_segment(
            label,
            "sdk_agent_attempt",
            _float_or_none(attempt.get("started_at_epoch")),
            _float_or_none(attempt.get("finished_at_epoch")),
            str(attempt.get("attempt_role") or ""),
            extra={
                "attempt_index": attempt_index,
                "attempt_role": attempt.get("attempt_role"),
                "phase": attempt.get("phase"),
                "run_result_present": bool(attempt.get("run_result_present")),
                "recovery_action": attempt.get("recovery_action", ""),
                "recovery_reason": attempt.get("recovery_reason", ""),
            },
        )
        if segment is not None:
            segments.append(segment)
    return segments


def _latency_attribution(timing: dict[str, Any]) -> dict[str, Any]:
    mcp_timing = (
        timing.get("mcp_trace_timing") if isinstance(timing.get("mcp_trace_timing"), dict) else {}
    )
    runner_timing = (
        timing.get("runner_timing") if isinstance(timing.get("runner_timing"), dict) else {}
    )
    event_metrics = (
        timing.get("openai_agents_event_metrics")
        if isinstance(timing.get("openai_agents_event_metrics"), dict)
        else {}
    )
    span_metrics = (
        timing.get("openai_agents_span_metrics")
        if isinstance(timing.get("openai_agents_span_metrics"), dict)
        else {}
    )
    fallback_metrics = (
        timing.get("model_service_fallback_metrics")
        if isinstance(timing.get("model_service_fallback_metrics"), dict)
        else {}
    )
    model_input_filter_metrics = (
        timing.get("model_input_filter_metrics")
        if isinstance(timing.get("model_input_filter_metrics"), dict)
        else {}
    )
    context_metrics = (
        timing.get("context_metrics") if isinstance(timing.get("context_metrics"), dict) else {}
    )
    cache_metrics = (
        timing.get("cache_metrics") if isinstance(timing.get("cache_metrics"), dict) else {}
    )
    context_growth_metrics = (
        timing.get("context_growth_metrics")
        if isinstance(timing.get("context_growth_metrics"), dict)
        else {}
    )
    budget_terminal = (
        timing.get("agent_sdk_budget_terminal")
        if isinstance(timing.get("agent_sdk_budget_terminal"), dict)
        else {}
    )
    sdk_elapsed = _float_or_none(runner_timing.get("openai_agents_elapsed_s"))
    mcp_elapsed = _float_or_none(mcp_timing.get("total_elapsed_s"))
    return {
        "openai_agents_elapsed_s": sdk_elapsed,
        "mcp_trace_elapsed_s": mcp_elapsed,
        "model_or_sdk_unattributed_s": model_or_sdk_unattributed_seconds(timing),
        "mcp_between_tool_gap_s": mcp_timing.get("between_tool_gap_s"),
        "mcp_robot_view_capture_s": mcp_timing.get("robot_view_capture_s"),
        "mcp_tool_handler_s": mcp_timing.get("tool_handler_s"),
        "mcp_other_overhead_s": mcp_timing.get("other_mcp_overhead_s"),
        "mcp_tool_call_count": mcp_timing.get("tool_call_count"),
        "mcp_list_tools_request_count": (timing.get("mcp_control_plane_metrics") or {}).get(
            "list_tools_request_count"
        ),
        "openai_agents_tool_error_count": event_metrics.get("tool_error_count"),
        "openai_agents_tool_error_classifications": event_metrics.get("tool_error_classifications"),
        "openai_agents_span_artifact_available": span_metrics.get("available"),
        "openai_agents_span_count": span_metrics.get("span_end_count"),
        "openai_agents_span_type_counts": span_metrics.get("span_type_counts"),
        "openai_agents_span_capture_limitations": span_metrics.get("limitations"),
        "model_service_fallback_metrics": compact_metric_group(fallback_metrics),
        "model_racing_observability_metrics": compact_metric_group(
            timing.get("model_racing_observability_metrics")
            if isinstance(timing.get("model_racing_observability_metrics"), dict)
            else {}
        ),
        "model_input_filter_metrics": compact_metric_group(model_input_filter_metrics),
        "agent_sdk_budget_terminal": compact_metric_group(budget_terminal),
        "mcp_client_session_timeout_s": timing.get("mcp_client_session_timeout_s"),
        "context_metrics": compact_metric_group(context_metrics),
        "cache_metrics": compact_metric_group(cache_metrics),
        "context_growth_metrics": compact_metric_group(context_growth_metrics),
    }


def _timeline_segment(
    name: str,
    category: str,
    started_at: float | None,
    finished_at: float | None,
    detail: str,
    *,
    extra: dict[str, Any] | None = None,
) -> dict[str, Any] | None:
    if started_at is None or finished_at is None:
        return None
    duration = round_duration(finished_at - started_at)
    payload: dict[str, Any] = {
        "name": name,
        "category": category,
        "started_at_epoch": started_at,
        "finished_at_epoch": finished_at,
        "duration_s": duration,
        "detail": detail,
    }
    if extra:
        payload.update({key: value for key, value in extra.items() if value not in {None, ""}})
    return payload


def _parse_compact_metric_detail(
    detail: str,
) -> tuple[dict[str, Any] | None, dict[str, str] | None]:
    stripped = detail.strip()
    if not stripped or stripped[0] not in "[{":
        return None, None
    try:
        parsed = json.loads(stripped)
    except json.JSONDecodeError as exc:
        return None, {
            "detail_source_error": f"detail must contain a valid JSON object: {exc.msg}",
            "detail_source_error_kind": "invalid_json",
        }
    if not isinstance(parsed, dict):
        return None, {
            "detail_source_error": (
                f"detail must contain a JSON object, got {type(parsed).__name__}"
            ),
            "detail_source_error_kind": "non_object",
        }
    return parsed, None


def _read_jsonl_path(path: Path, *, label: str = "OpenAI Agents live") -> list[dict[str, Any]]:
    if not path.is_file():
        return []
    return read_jsonl_objects(path, label=label)


def _float_or_none(value: Any) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _int_or_none(value: Any) -> int | None:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def round_duration(value: float) -> float:
    return round(max(0.0, value), 3)
