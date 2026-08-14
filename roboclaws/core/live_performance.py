"""Pure sanitized live-agent performance projections and comparisons."""

from __future__ import annotations

import json
import math
from pathlib import Path
from typing import Any

from roboclaws.core.json_sources import (
    json_source_type_name,
    read_json_object,
    read_jsonl_objects,
)
from roboclaws.core.live_performance_calibration import normalized_model_timing
from roboclaws.core.runtime_timing import runtime_timing_from_trace

REPORT_PERFORMANCE_SCHEMA = "roboclaws_report_performance_metrics_v1"
MODEL_CALL_METRIC_SCHEMA = "roboclaws_model_call_metric_v1"

FORBIDDEN_PRIVACY_KEYS = {
    "api_key",
    "compact_continuation_state",
    "credentials",
    "final_output",
    "function_input",
    "function_output",
    "full_tool_payload",
    "instructions",
    "last_agent",
    "model_output",
    "model_text",
    "output_text",
    "private_evaluator_truth",
    "private_manifest",
    "private_target_truth",
    "raw_prompt",
    "tool_payload_body",
}
FORBIDDEN_PRIVACY_MARKERS = {
    "bearer ",
    "compact_continuation_state:",
    "private_evaluator_truth",
    "private_manifest",
    "private_target_truth",
    "raw_prompt",
    "sk-",
    "tool_payload_body",
}
SAFE_SCAN_GLOBS = (
    "live_status.json",
    "live_timing.json",
    "model_call_metrics.jsonl",
    "openai-agents-events*.jsonl",
    "openai-agents-spans*.jsonl",
)


class ReportPerformanceSourceError(ValueError):
    """Raised when a present report-performance source artifact is malformed."""


def extract_report_performance_metrics(
    run_dir: Path,
    *,
    write_model_call_metrics: bool = False,
    calibration: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Build one sanitized performance packet for a live-agent run directory."""

    run_dir = Path(run_dir)
    live_timing = read_json(run_dir / "live_timing.json")
    live_status = read_json(run_dir / "live_status.json")
    run_result = read_json(run_dir / "run_result.json")
    trace_events = read_jsonl(run_dir / "trace.jsonl")
    runner_timing = _dict(live_timing.get("runner_timing"))
    mcp_timing = _mcp_timing(run_dir, live_timing, run_result, trace_events)
    model_calls = extract_model_call_metrics(run_dir, live_timing=live_timing)
    if write_model_call_metrics:
        write_model_call_metrics_jsonl(run_dir / "model_call_metrics.jsonl", model_calls)
    packet = {
        "schema": REPORT_PERFORMANCE_SCHEMA,
        "run_dir": str(run_dir),
        "run_identity": _run_identity(run_dir, live_timing, run_result),
        "quality": _quality_packet(live_timing, live_status, run_result, trace_events),
        "call_counts": _call_counts(live_timing, trace_events, model_calls),
        "model_work": _model_work(model_calls, live_timing),
        "timing": _timing_packet(
            runner_timing,
            mcp_timing,
            model_calls,
            live_timing,
        ),
        "limitations": [],
    }
    packet["timing"].update(
        normalized_model_timing(
            packet["timing"],
            packet["model_work"],
            calibration=calibration,
            run_identity=packet["run_identity"],
        )
    )
    packet["limitations"] = _packet_limitations(packet)
    return packet


def extract_model_call_metrics(
    run_dir: Path,
    *,
    live_timing: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    """Extract sanitized per-call model metrics from known live-agent artifacts."""

    run_dir = Path(run_dir)
    live_timing = (
        live_timing if live_timing is not None else read_json(run_dir / "live_timing.json")
    )
    engine = _agent_engine(live_timing, run_dir)
    rows = (
        _openai_agents_model_call_rows(run_dir, live_timing)
        if engine == "openai-agents-sdk"
        else []
    )

    if rows:
        return rows
    return [
        _model_call_row(
            agent_engine=engine,
            provider_profile=str(live_timing.get("provider_profile") or ""),
            wire_api=str(live_timing.get("wire_api") or ""),
            model=str(live_timing.get("model") or ""),
            source="unavailable",
            status="unavailable",
            limitations=[f"{engine}_model_call_telemetry_unavailable"],
        )
    ]


def write_model_call_metrics_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "".join(json.dumps(row, sort_keys=True) + "\n" for row in rows),
        encoding="utf-8",
    )


def privacy_findings_for_packet(packet: Any) -> list[dict[str, Any]]:
    return _privacy_scan_payload(packet, source="packet", row_id="")


def privacy_findings_for_run_dir(run_dir: Path, *, row_id: str = "") -> list[dict[str, Any]]:
    findings: list[dict[str, Any]] = []
    for pattern in SAFE_SCAN_GLOBS:
        for path in sorted(Path(run_dir).glob(pattern)):
            findings.extend(_privacy_scan_text(path.read_text(encoding="utf-8"), path, row_id))
    return findings


def read_json(path: Path) -> dict[str, Any]:
    if not path.is_file():
        return {}
    try:
        return read_json_object(path, label="report performance JSON")
    except OSError as exc:
        raise ReportPerformanceSourceError(f"failed to read JSON source {path}: {exc}") from exc
    except ValueError as exc:
        cause = exc.__cause__
        if isinstance(cause, json.JSONDecodeError):
            raise ReportPerformanceSourceError(
                f"malformed JSON source {path}: "
                f"line {cause.lineno} column {cause.colno}: {cause.msg}"
            ) from exc
        raise ReportPerformanceSourceError(
            f"malformed JSON source {path}: expected object, got {json_source_type_name(path)}"
        ) from exc


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.is_file():
        return []
    try:
        return read_jsonl_objects(path, label="report performance JSONL")
    except OSError as exc:
        raise ReportPerformanceSourceError(f"failed to read JSONL source {path}: {exc}") from exc
    except ValueError as exc:
        raise ReportPerformanceSourceError(str(exc)) from exc


def read_model_latency_calibration(path: Path) -> dict[str, Any]:
    """Read a named model-latency calibration packet."""

    packet = read_json(path)
    if not packet:
        return {}
    result = dict(packet)
    result["source_path"] = str(path)
    return result


def _run_identity(
    run_dir: Path,
    live_timing: dict[str, Any],
    run_result: dict[str, Any],
) -> dict[str, Any]:
    goal_contract = _dict(run_result.get("goal_contract"))
    return {
        "surface": _first_text(live_timing, run_result, goal_contract, "surface", "task_surface"),
        "intent": _first_text(live_timing, run_result, goal_contract, "intent", "task_intent"),
        "task_name": _first_text(live_timing, run_result, "task_name"),
        "agent_engine": _agent_engine(live_timing, run_dir),
        "provider_profile": str(live_timing.get("provider_profile") or ""),
        "wire_api": str(live_timing.get("wire_api") or ""),
        "model": str(live_timing.get("model") or ""),
        "evidence_lane": str(live_timing.get("evidence_lane") or live_timing.get("profile") or ""),
        "seed": run_result.get("seed") or live_timing.get("seed"),
        "profile_id": _profile_id(live_timing),
    }


def _quality_packet(
    live_timing: dict[str, Any],
    live_status: dict[str, Any],
    run_result: dict[str, Any],
    trace_events: list[dict[str, Any]],
) -> dict[str, Any]:
    score = _dict(run_result.get("score"))
    return {
        "checker_state": (
            "result-present" if run_result else str(live_status.get("reason") or "missing")
        ),
        "terminal": _terminal_state(live_timing, live_status),
        "cleanup_status": run_result.get("cleanup_status"),
        "completion_status": run_result.get("completion_status"),
        "restored_count": _int_or_none(score.get("restored_count")),
        "total_targets": _int_or_none(score.get("total_targets")),
        "mess_restoration_rate": _float_or_none(
            run_result.get("mess_restoration_rate") or score.get("mess_restoration_rate")
        ),
        "sweep_coverage_rate": _float_or_none(run_result.get("sweep_coverage_rate")),
        "disturbance_count": _int_or_none(
            run_result.get("disturbance_count") or score.get("disturbance_count")
        )
        or 0,
        "failed_or_noop_tool_count": _failed_or_noop_tool_count(trace_events),
        "semantic_accepted_count": _semantic_accepted_count(score),
    }


def _call_counts(
    live_timing: dict[str, Any],
    trace_events: list[dict[str, Any]],
    model_calls: list[dict[str, Any]],
) -> dict[str, Any]:
    mcp_tool_counts = _tool_counts(trace_events)
    attempts = live_timing.get("openai_agents_attempts")
    if isinstance(attempts, list):
        agent_attempt_count = len([item for item in attempts if isinstance(item, dict)])
    else:
        agent_attempt_count = _int_or_none(live_timing.get("openai_agents_attempt_count")) or 1
    continuation_count = max(0, agent_attempt_count - 1)
    return {
        "model_call_count": len([row for row in model_calls if row.get("status") != "unavailable"]),
        "agent_attempt_count": agent_attempt_count,
        "continuation_count": continuation_count,
        "mcp_tool_call_count": sum(mcp_tool_counts.values()),
        "mcp_tool_counts": mcp_tool_counts,
        "non_tool_turn_count": _non_tool_turn_count(live_timing),
    }


def _model_work(model_calls: list[dict[str, Any]], live_timing: dict[str, Any]) -> dict[str, Any]:
    available_rows = [row for row in model_calls if row.get("status") != "unavailable"]
    limitations = sorted(
        {
            str(item)
            for row in model_calls
            for item in list(row.get("limitations") or [])
            if str(item)
        }
    )
    input_values = [
        int(row["input_tokens"])
        for row in available_rows
        if _int_or_none(row.get("input_tokens")) is not None
    ]
    total_input = _sum_int(available_rows, "input_tokens")
    total_cached = _sum_int(available_rows, "cached_input_tokens")
    total_output = _sum_int(available_rows, "output_tokens")
    total_reasoning = _sum_int(available_rows, "reasoning_tokens")
    image_input_count = _sum_int(available_rows, "image_input_count")
    image_input_pixels = _sum_int(available_rows, "image_input_pixels")
    if not available_rows and not input_values:
        context = _dict(live_timing.get("context_metrics"))
        if context.get("available"):
            total_input = _int_or_none(context.get("total_input_tokens"))
            total_cached = _int_or_none(context.get("total_cached_input_tokens"))
            total_uncached = _int_or_none(context.get("total_uncached_input_tokens"))
            total_output = _int_or_none(context.get("total_output_tokens"))
            total_reasoning = _int_or_none(context.get("total_reasoning_tokens"))
            max_input = _int_or_none(context.get("max_input_tokens"))
            p50_input = _int_or_none(context.get("p50_input_tokens"))
            p95_input = _int_or_none(context.get("p95_input_tokens"))
            return {
                "available": True,
                "source": str(context.get("source") or "live_timing_context_metrics"),
                "total_input_tokens": total_input,
                "total_cached_input_tokens": total_cached,
                "total_uncached_input_tokens": (
                    total_uncached
                    if total_uncached is not None
                    else _uncached(total_input, total_cached)
                ),
                "total_output_tokens": total_output,
                "total_reasoning_tokens": total_reasoning,
                "max_input_tokens": max_input,
                "p50_input_tokens": p50_input,
                "p95_input_tokens": p95_input,
                "image_input_count": image_input_count,
                "image_input_pixels": image_input_pixels,
                "unavailable_metrics": list(context.get("limitations") or []),
            }
    return {
        "available": bool(available_rows),
        "source": "model_call_metrics",
        "total_input_tokens": total_input,
        "total_cached_input_tokens": total_cached,
        "total_uncached_input_tokens": _uncached(total_input, total_cached),
        "total_output_tokens": total_output,
        "total_reasoning_tokens": total_reasoning,
        "max_input_tokens": max(input_values) if input_values else None,
        "p50_input_tokens": _nearest_rank_percentile(input_values, 0.50) if input_values else None,
        "p95_input_tokens": _nearest_rank_percentile(input_values, 0.95) if input_values else None,
        "image_input_count": image_input_count,
        "image_input_pixels": image_input_pixels,
        "unavailable_metrics": limitations,
    }


def _timing_packet(
    runner: dict[str, Any],
    mcp: dict[str, Any],
    model_calls: list[dict[str, Any]],
    live_timing: dict[str, Any],
) -> dict[str, Any]:
    observed_model_api = _model_api_time(model_calls, live_timing)
    observed_wall = _float_or_none(runner.get("total_elapsed_s")) or _float_or_none(
        mcp.get("total_elapsed_s")
    )
    runner_agent_s = _float_or_none(runner.get("openai_agents_elapsed_s"))
    mcp_elapsed = _float_or_none(mcp.get("total_elapsed_s"))
    tool_handler = _float_or_none(mcp.get("tool_handler_s"))
    robot_view = _float_or_none(mcp.get("robot_view_capture_s"))
    non_model = None
    if observed_wall is not None and observed_model_api is not None:
        non_model = round(max(0.0, observed_wall - observed_model_api), 3)
    elif observed_wall is not None and _float_or_none(mcp.get("between_tool_gap_s")) is not None:
        non_model = round(
            max(0.0, observed_wall - float(mcp.get("between_tool_gap_s") or 0.0)),
            3,
        )
    return {
        "observed_wall_s": observed_wall,
        "runner_agent_s": runner_agent_s,
        "mcp_elapsed_s": mcp_elapsed,
        "mcp_between_tool_gap_s": _float_or_none(mcp.get("between_tool_gap_s")),
        "mcp_tool_handler_s": tool_handler,
        "robot_view_capture_s": robot_view,
        "observed_model_api_s": observed_model_api,
        "non_model_s": non_model,
    }


def _openai_agents_model_call_rows(
    run_dir: Path,
    live_timing: dict[str, Any],
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    attempt_by_file = _attempt_index_by_span_file(live_timing)
    call_index = 0
    for path in sorted(run_dir.glob("openai-agents-spans*.jsonl")):
        attempt_index = attempt_by_file.get(path.name, _attempt_index_from_name(path.name))
        for event in read_jsonl(path):
            if event.get("event") != "span_end" or event.get("span_type") != "response":
                continue
            usage = _dict(event.get("usage"))
            limitations: list[str] = []
            if not usage:
                limitations.append("response_span_usage_missing")
            input_tokens = _int_or_none(usage.get("input_tokens"))
            if input_tokens is None:
                limitations.append("input_tokens_unavailable")
            cached_input_tokens = _cached_input_tokens(usage)
            output_tokens = _int_or_none(usage.get("output_tokens"))
            if output_tokens is None:
                limitations.append("output_tokens_unavailable")
            reasoning_tokens = _reasoning_tokens(usage)
            duration = _float_or_none(event.get("duration_s"))
            if duration is None:
                limitations.append("duration_unavailable")
            rows.append(
                _model_call_row(
                    agent_engine="openai-agents-sdk",
                    provider_profile=str(
                        event.get("provider_profile") or live_timing.get("provider_profile") or ""
                    ),
                    wire_api=str(event.get("wire_api") or live_timing.get("wire_api") or ""),
                    model=str(event.get("model") or live_timing.get("model") or ""),
                    attempt_index=attempt_index,
                    call_index=call_index,
                    started_at_epoch=_float_or_none(event.get("ts_epoch")),
                    duration_s=duration,
                    input_tokens=input_tokens,
                    cached_input_tokens=cached_input_tokens,
                    output_tokens=output_tokens,
                    reasoning_tokens=reasoning_tokens,
                    status="success" if not _dict(event.get("error")) else "failure",
                    failure_class=str(_dict(event.get("error")).get("type") or ""),
                    source="openai_agents_span",
                    limitations=limitations,
                )
            )
            call_index += 1
    return rows


def _model_call_row(
    *,
    agent_engine: str,
    provider_profile: str,
    model: str,
    wire_api: str = "",
    attempt_index: int = 0,
    call_index: int = 0,
    started_at_epoch: float | None = None,
    duration_s: float | None = None,
    input_tokens: int | None = None,
    cached_input_tokens: int | None = None,
    output_tokens: int | None = None,
    reasoning_tokens: int | None = None,
    image_input_count: int | None = None,
    image_input_pixels: int | None = None,
    status: str = "success",
    failure_class: str = "",
    source: str = "",
    limitations: list[str] | None = None,
) -> dict[str, Any]:
    input_tokens = _int_or_none(input_tokens)
    cached_input_tokens = _int_or_none(cached_input_tokens)
    output_tokens = _int_or_none(output_tokens)
    reasoning_tokens = _int_or_none(reasoning_tokens)
    image_input_count = _int_or_none(image_input_count) or 0
    image_input_pixels = _int_or_none(image_input_pixels) or 0
    if input_tokens is None:
        cached_input_tokens = None
        uncached = None
    else:
        cached_input_tokens = min(max(cached_input_tokens or 0, 0), input_tokens)
        uncached = max(0, input_tokens - cached_input_tokens)
    return {
        "schema": MODEL_CALL_METRIC_SCHEMA,
        "agent_engine": agent_engine,
        "provider_profile": provider_profile,
        "wire_api": wire_api,
        "model": model,
        "attempt_index": attempt_index,
        "call_index": call_index,
        "started_at_epoch": started_at_epoch,
        "duration_s": duration_s,
        "input_tokens": input_tokens,
        "cached_input_tokens": cached_input_tokens,
        "uncached_input_tokens": uncached,
        "output_tokens": output_tokens,
        "reasoning_tokens": reasoning_tokens,
        "image_input_count": image_input_count,
        "image_input_pixels": image_input_pixels,
        "status": status,
        "failure_class": failure_class,
        "source": source,
        "limitations": sorted(set(limitations or [])),
    }


def _agent_engine(live_timing: dict[str, Any], run_dir: Path) -> str:
    runtime = str(live_timing.get("runtime") or "").lower()
    if (
        runtime == "openai-agents-live"
        or "openai_agents" in live_timing
        or (run_dir / "openai-agents-spans.jsonl").exists()
        or (run_dir / "openai-agents-events.jsonl").exists()
    ):
        return "openai-agents-sdk"
    return str(live_timing.get("agent_engine") or "unknown")


def _agent_engine_from_identity(identity: dict[str, Any] | None) -> str:
    return str(_dict(identity).get("agent_engine") or "")


def _mcp_timing(
    run_dir: Path,
    live_timing: dict[str, Any],
    run_result: dict[str, Any],
    trace_events: list[dict[str, Any]],
) -> dict[str, Any]:
    timing = _dict(live_timing.get("mcp_trace_timing"))
    if timing:
        return timing
    runtime_timing = _dict(run_result.get("runtime_timing"))
    if runtime_timing:
        return runtime_timing
    if trace_events:
        return runtime_timing_from_trace(trace_events)
    trace_events = read_jsonl(run_dir / "trace.jsonl")
    return runtime_timing_from_trace(trace_events) if trace_events else {}


def _terminal_state(live_timing: dict[str, Any], status: dict[str, Any]) -> str:
    terminal = live_timing.get("agent_sdk_budget_terminal")
    if isinstance(terminal, dict) and terminal.get("reason"):
        return str(terminal["reason"])
    reason = live_timing.get("reason") or status.get("reason")
    if reason:
        return str(reason)
    phase = live_timing.get("phase") or status.get("phase")
    return str(phase or "unknown")


def _profile_id(live_timing: dict[str, Any]) -> str:
    profile = live_timing.get("agent_sdk_perf_profile")
    if isinstance(profile, dict):
        return str(profile.get("profile_id") or "")
    return str(live_timing.get("profile_id") or live_timing.get("profile") or "")


def _first_text(*sources: Any) -> str:
    keys = sources[-2:] if all(isinstance(item, str) for item in sources[-2:]) else sources[-1:]
    containers = sources[: -len(keys)]
    for container in containers:
        if not isinstance(container, dict):
            continue
        for key in keys:
            value = container.get(key)
            if value not in {None, ""}:
                return str(value)
    return ""


def _packet_limitations(packet: dict[str, Any]) -> list[str]:
    limitations: set[str] = set()
    model_work = _dict(packet.get("model_work"))
    for item in model_work.get("unavailable_metrics") or []:
        limitations.add(str(item))
    estimate = _dict(_dict(packet.get("timing")).get("estimated_model_work_s"))
    for item in estimate.get("limitations") or []:
        limitations.add(str(item))
    if not model_work.get("available"):
        limitations.add("model_work_unavailable")
    return sorted(limitations)


def _tool_counts(events: list[dict[str, Any]]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for event in events:
        if event.get("event") != "response":
            continue
        tool = str(event.get("tool") or "")
        if not tool:
            continue
        counts[tool] = counts.get(tool, 0) + 1
    return dict(sorted(counts.items()))


def _failed_or_noop_tool_count(events: list[dict[str, Any]]) -> int:
    count = 0
    for event in events:
        if event.get("event") != "response":
            continue
        response = _dict(event.get("response"))
        ok = response.get("ok")
        error_reason = str(response.get("error_reason") or response.get("failure_reason") or "")
        status = str(response.get("status") or "")
        if ok is False or error_reason or status in {"noop", "failed", "error"}:
            count += 1
    return count


def _semantic_accepted_count(score: dict[str, Any]) -> int | None:
    rows = score.get("object_results")
    if not isinstance(rows, list):
        return None
    accepted = 0
    for row in rows:
        if not isinstance(row, dict):
            continue
        if row.get("restored") or str(row.get("semantic_acceptability") or "") in {
            "preferred",
            "acceptable",
        }:
            accepted += 1
    return accepted


def _non_tool_turn_count(live_timing: dict[str, Any]) -> int | None:
    sdk = _dict(live_timing.get("openai_agents"))
    item_counts = _dict(sdk.get("item_counts"))
    if item_counts:
        return sum(
            int(value or 0) for key, value in item_counts.items() if str(key) != "function_call"
        )
    return None


def _model_api_time(model_calls: list[dict[str, Any]], live_timing: dict[str, Any]) -> float | None:
    durations = [
        float(row["duration_s"])
        for row in model_calls
        if _float_or_none(row.get("duration_s")) is not None
    ]
    if durations:
        return round(sum(durations), 3)
    direct = _float_or_none(live_timing.get("model_api_time_s"))
    if direct is not None:
        return direct
    sdk = _dict(live_timing.get("openai_agents"))
    return _float_or_none(sdk.get("model_api_time_s"))


def _sum_int(rows: list[dict[str, Any]], key: str) -> int | None:
    values = [_int_or_none(row.get(key)) for row in rows]
    known = [value for value in values if value is not None]
    if not known:
        return None
    return sum(known)


def _uncached(input_tokens: int | None, cached_input_tokens: int | None) -> int | None:
    if input_tokens is None:
        return None
    return max(0, input_tokens - (cached_input_tokens or 0))


def _attempt_index_by_span_file(live_timing: dict[str, Any]) -> dict[str, int]:
    attempts = live_timing.get("openai_agents_attempts")
    if not isinstance(attempts, list):
        return {}
    result: dict[str, int] = {}
    for attempt in attempts:
        if not isinstance(attempt, dict):
            continue
        index = _int_or_none(attempt.get("attempt_index")) or 0
        path = attempt.get("openai_agents_spans")
        if path:
            result[Path(str(path)).name] = index
    return result


def _attempt_index_from_name(name: str) -> int:
    marker = ".continuation-"
    if marker not in name:
        return 0
    suffix = name.split(marker, 1)[1].split(".", 1)[0]
    return _int_or_none(suffix) or 0


def _cached_input_tokens(usage: dict[str, Any]) -> int | None:
    details = usage.get("input_tokens_details")
    if isinstance(details, dict):
        nested = _int_or_none(details.get("cached_tokens"))
        if nested is not None:
            return nested
    return _int_or_none(usage.get("cached_input_tokens"))


def _reasoning_tokens(usage: dict[str, Any]) -> int | None:
    details = usage.get("output_tokens_details")
    if isinstance(details, dict):
        return _int_or_none(details.get("reasoning_tokens"))
    return _int_or_none(usage.get("reasoning_tokens"))


def _privacy_scan_text(text: str, path: Path, row_id: str) -> list[dict[str, Any]]:
    findings: list[dict[str, Any]] = []
    for line_number, line in enumerate(text.splitlines(), start=1):
        try:
            payload = json.loads(line)
        except json.JSONDecodeError:
            payload = {"text": line}
        findings.extend(
            _privacy_scan_payload(payload, source=f"{path}:{line_number}", row_id=row_id)
        )
    return findings


def _privacy_scan_payload(payload: Any, *, source: str, row_id: str) -> list[dict[str, Any]]:
    findings: list[dict[str, Any]] = []

    def visit(value: Any, path: str) -> None:
        if isinstance(value, dict):
            for key, item in value.items():
                key_text = str(key)
                normalized_key = key_text.lower()
                if normalized_key in FORBIDDEN_PRIVACY_KEYS:
                    findings.append(
                        {
                            "row_id": row_id,
                            "source": source,
                            "path": f"{path}.{key_text}" if path else key_text,
                            "reason": f"forbidden key {key_text}",
                        }
                    )
                visit(item, f"{path}.{key_text}" if path else key_text)
            return
        if isinstance(value, list):
            for index, item in enumerate(value):
                visit(item, f"{path}[{index}]")
            return
        if isinstance(value, str):
            lowered = value.lower()
            for marker in FORBIDDEN_PRIVACY_MARKERS:
                if marker in lowered:
                    findings.append(
                        {
                            "row_id": row_id,
                            "source": source,
                            "path": path,
                            "reason": f"forbidden marker {marker}",
                        }
                    )
                    break

    visit(payload, "")
    return findings


def _dict(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _float_or_none(value: Any) -> float | None:
    try:
        result = float(value)
    except (TypeError, ValueError):
        return None
    if math.isnan(result) or math.isinf(result):
        return None
    return result


def _int_or_none(value: Any) -> int | None:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _nearest_rank_percentile(values: list[int], percentile: float) -> int | None:
    if not values:
        return None
    ordered = sorted(values)
    index = max(0, min(len(ordered) - 1, math.ceil(percentile * len(ordered)) - 1))
    return ordered[index]
