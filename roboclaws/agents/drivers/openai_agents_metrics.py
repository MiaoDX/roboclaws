from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from roboclaws.agents.drivers.openai_agents_metric_sources import (
    read_openai_agents_jsonl_source,
)

MODEL_SERVICE_FALLBACK_SCHEMA = "openai_agents_model_service_fallback_v1"
MODEL_RACING_OBSERVABILITY_SCHEMA = "openai_agents_model_racing_observability_v1"
MODEL_INPUT_FILTER_SCHEMA = "openai_agents_model_input_filter_v1"
MODEL_INPUT_SUM_FIELDS = tuple(
    """
    compacted_item_count unchanged_item_count repeated_item_count
    metric_map_output_count repeated_metric_map_output_count metric_map_delta_compacted_count
    metric_map_bytes_before metric_map_bytes_after metric_map_bytes_reduced
    raw_fpv_image_item_count raw_fpv_image_retained_count raw_fpv_image_evicted_count
    raw_fpv_image_transcoded_count
    raw_fpv_image_bytes_before raw_fpv_image_bytes_after raw_fpv_image_bytes_reduced
    completed_tool_history_bundle_count completed_tool_history_retained_count
    completed_tool_history_evicted_count completed_tool_history_item_count_before
    completed_tool_history_item_count_after completed_tool_history_bytes_reduced
    camera_grounded_history_item_count camera_grounded_history_retained_count
    camera_grounded_history_compacted_count camera_grounded_history_bytes_before
    camera_grounded_history_bytes_after camera_grounded_history_bytes_reduced
    """.split()
)


def _estimated_tokens_from_chars(char_count: int) -> int:
    if char_count <= 0:
        return 0
    return max(1, round(char_count / 4))


def _continuation_attempt_count(timing: dict[str, Any]) -> int:
    attempts = timing.get("openai_agents_attempts")
    if not isinstance(attempts, list):
        return 0
    return sum(
        1
        for attempt in attempts
        if isinstance(attempt, dict) and int(attempt.get("attempt_index") or 0) > 0
    )


def openai_agents_context_metrics(run_dir: Path, timing: dict[str, Any]) -> dict[str, Any]:
    response_spans = _response_span_end_events(run_dir)
    kickoff_prompt_chars = _int_or_none(timing.get("kickoff_prompt_chars")) or 0
    attempts = timing.get("openai_agents_attempts")
    if not isinstance(attempts, list):
        attempts = []
    continuation_prompt_chars = sum(
        _int_or_none(attempt.get("continuation_prompt_chars")) or 0
        for attempt in attempts
        if isinstance(attempt, dict)
    )
    base_payload: dict[str, Any] = {
        "kickoff_prompt_chars": kickoff_prompt_chars,
        "kickoff_prompt_estimated_tokens": _estimated_tokens_from_chars(kickoff_prompt_chars),
        "continuation_prompt_chars": continuation_prompt_chars,
        "continuation_prompt_estimated_tokens": _estimated_tokens_from_chars(
            continuation_prompt_chars
        ),
        "context_window_failure_detected": _context_window_failure_detected(timing, run_dir),
    }
    if not response_spans:
        return {
            "available": False,
            "source": "unavailable",
            "limitations": ["span_usage_missing"],
            **base_payload,
        }

    usage_rows: list[dict[str, int | float | None]] = []
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
        cached_tokens = _cached_input_tokens(usage)
        output_tokens = _int_or_none(usage.get("output_tokens")) or 0
        reasoning_tokens = _reasoning_tokens(usage) or 0
        usage_rows.append(
            {
                "input_tokens": input_tokens,
                "cached_tokens": min(max(cached_tokens, 0), input_tokens),
                "output_tokens": output_tokens,
                "reasoning_tokens": reasoning_tokens,
                "duration_s": _float_or_none(event.get("duration_s")),
            }
        )

    if not usage_rows:
        return {
            "available": False,
            "source": "openai_agents_span_usage",
            "limitations": sorted(set(limitations or ["span_usage_missing"])),
            "response_span_count": len(response_spans),
            **base_payload,
        }

    input_values = [int(row["input_tokens"] or 0) for row in usage_rows]
    total_input = sum(input_values)
    total_cached = sum(int(row["cached_tokens"] or 0) for row in usage_rows)
    total_uncached = max(0, total_input - total_cached)
    total_output = sum(int(row["output_tokens"] or 0) for row in usage_rows)
    total_reasoning = sum(int(row["reasoning_tokens"] or 0) for row in usage_rows)
    durations = [
        float(row["duration_s"])
        for row in usage_rows
        if _float_or_none(row.get("duration_s")) is not None
    ]
    return {
        "available": True,
        "source": "openai_agents_span_usage",
        "limitations": sorted(set(limitations)),
        "response_span_count": len(usage_rows),
        "total_input_tokens": total_input,
        "total_cached_input_tokens": total_cached,
        "total_uncached_input_tokens": total_uncached,
        "cache_hit_ratio": _ratio(total_cached, total_input),
        "max_input_tokens": max(input_values),
        "p50_input_tokens": _nearest_rank_percentile(input_values, 0.50),
        "p95_input_tokens": _nearest_rank_percentile(input_values, 0.95),
        "total_output_tokens": total_output,
        "total_reasoning_tokens": total_reasoning,
        "max_reasoning_tokens": max(int(row["reasoning_tokens"] or 0) for row in usage_rows),
        "first_response_cached_tokens": int(usage_rows[0]["cached_tokens"] or 0),
        "response_span_duration_s": _round_duration(sum(durations)) if durations else None,
        **base_payload,
    }


def openai_agents_cache_metrics(
    context_metrics: dict[str, Any], timing: dict[str, Any]
) -> dict[str, Any]:
    model_settings = (
        timing.get("sdk_model_settings")
        if isinstance(timing.get("sdk_model_settings"), dict)
        else {}
    )
    stable_prefix = (
        timing.get("kickoff_prompt_stable_prefix")
        if isinstance(timing.get("kickoff_prompt_stable_prefix"), dict)
        else {}
    )
    if not context_metrics.get("available"):
        return {
            "available": False,
            "source": context_metrics.get("source") or "unavailable",
            "limitations": context_metrics.get("limitations") or ["span_usage_missing"],
            "cache_tools_list": bool(timing.get("cache_tools_list")),
            "prompt_cache_retention": str(model_settings.get("prompt_cache_retention") or ""),
            "stable_prefix_hash": str(stable_prefix.get("hash") or ""),
            "mcp_tool_catalog_cache_enabled": bool(timing.get("cache_tools_list")),
        }
    total_input = _int_or_none(context_metrics.get("total_input_tokens")) or 0
    total_cached = _int_or_none(context_metrics.get("total_cached_input_tokens")) or 0
    return {
        "available": True,
        "source": "openai_agents_span_usage",
        "limitations": list(context_metrics.get("limitations") or []),
        "cache_tools_list": bool(timing.get("cache_tools_list")),
        "prompt_cache_retention": str(model_settings.get("prompt_cache_retention") or ""),
        "provider_prompt_cache_observed": total_cached > 0,
        "cached_input_token_ratio": _ratio(total_cached, total_input),
        "first_response_cached_tokens": context_metrics.get("first_response_cached_tokens"),
        "stable_prefix_hash": str(stable_prefix.get("hash") or ""),
        "prompt_profile_id": str(timing.get("prompt_profile_id") or "baseline"),
        "mcp_tool_catalog_cache_enabled": bool(timing.get("cache_tools_list")),
    }


def openai_agents_context_growth_metrics(run_dir: Path, timing: dict[str, Any]) -> dict[str, Any]:
    trace_events = read_openai_agents_jsonl_source(run_dir / "trace.jsonl")
    if not trace_events:
        return {
            "available": False,
            "source": "unavailable",
            "limitations": ["trace_missing"],
            "continuation_attempt_count": _continuation_attempt_count(timing),
        }

    response_events = [event for event in trace_events if event.get("event") == "response"]
    observe_events = [event for event in response_events if event.get("tool") == "observe"]
    raw_fpv_events = [
        event
        for event in response_events
        if "raw_fpv" in json.dumps(event, sort_keys=True, ensure_ascii=True)
    ]
    response_sizes = [len(json.dumps(event, sort_keys=True)) for event in response_events]
    return {
        "available": True,
        "source": "live_timing_and_trace",
        "limitations": [],
        "trace_event_count": len(trace_events),
        "observe_response_count": len(observe_events),
        "raw_fpv_observation_count": len(raw_fpv_events),
        "tool_response_bytes_total": sum(response_sizes),
        "largest_tool_response_bytes": max(response_sizes) if response_sizes else 0,
        "agent_visible_state_bytes_p95": _nearest_rank_percentile(response_sizes, 0.95)
        if response_sizes
        else 0,
        "continuation_attempt_count": _continuation_attempt_count(timing),
    }


def model_service_fallback_metrics(run_dir: Path) -> dict[str, Any]:
    events = _events_by_schema(run_dir, MODEL_SERVICE_FALLBACK_SCHEMA)
    if not events:
        return _unavailable_metrics(
            "openai_agents_model_service_fallback_events",
            "model_service_fallback_events_missing",
        )

    state = _model_service_state()
    for event in events:
        _record_event_count(state, event)
        _record_attempt_identity(state, event)
        _record_model_service_failure(state, event)
        _record_retry_state(state, event)
        _record_counted_text(state["final_outcomes"], event.get("final_outcome"))

    return {
        "available": True,
        "source": "openai_agents_model_service_fallback_events",
        "limitations": [],
        "attempt_event_count": state["event_counts"].get("model_service_attempt", 0),
        "retry_scheduled_count": state["event_counts"].get("model_service_retry_scheduled", 0),
        "failure_event_count": state["event_counts"].get("model_service_failure", 0),
        "success_event_count": state["event_counts"].get("model_service_success", 0),
        "failure_classes": dict(sorted(state["failure_classes"].items())),
        "provider_reasons": dict(sorted(state["provider_reasons"].items())),
        "attempted_models": sorted(state["attempted_models"]),
        "attempted_provider_profiles": sorted(state["attempted_provider_profiles"]),
        "attempted_wire_apis": sorted(state["attempted_wire_apis"]),
        "retry_delay_s_total": _round_duration(state["retry_delay_s_total"]),
        "retry_delay_count": state["retry_delay_count"],
        "retry_exhausted": state["retry_exhausted"],
        "final_outcomes": dict(sorted(state["final_outcomes"].items())),
        "privacy_note": (
            "Fallback metrics retain attempt counts, provider/model ids, failure classes, "
            "retry delays, and outcomes only. Raw prompts, model text, credentials, and "
            "tool payload bodies are not persisted."
        ),
    }


def model_racing_observability_metrics(run_dir: Path) -> dict[str, Any]:
    events = _events_by_schema(run_dir, MODEL_RACING_OBSERVABILITY_SCHEMA)
    if not events:
        return _unavailable_metrics(
            "openai_agents_model_racing_observability_events",
            "model_racing_observability_events_missing",
        )

    state = _model_racing_state()
    for event in events:
        _record_model_racing_event(state, event)

    return {
        "available": True,
        "source": "openai_agents_model_racing_observability_events",
        "limitations": [],
        "event_count": len(events),
        "event_counts": dict(sorted(state["event_counts"].items())),
        "call_count": len(state["call_indexes"]),
        "arm_count": len(state["arm_ids"]),
        "max_arm_count_per_call": state["max_arm_count"],
        "racing_enabled": state["racing_enabled"],
        "racing_multiplier": state["racing_multiplier"],
        "winner_count": state["winner_count"],
        "cancelled_count": state["cancelled_count"],
        "cancellation_observed_count": state["cancellation_observed_count"],
        "loser_billing_unknown_count": state["loser_billing_unknown_count"],
        "elapsed_s_total": _round_duration(state["elapsed_s_total"]),
        "max_elapsed_s": _round_duration(state["max_elapsed_s"]),
        "usage_available_count": state["usage_available_count"],
        "usage_missing_count": state["usage_missing_count"],
        "total_input_tokens": state["total_input_tokens"],
        "total_cached_input_tokens": state["total_cached_input_tokens"],
        "total_uncached_input_tokens": state["total_uncached_input_tokens"],
        "total_output_tokens": state["total_output_tokens"],
        "total_reasoning_tokens": state["total_reasoning_tokens"],
        "methods": sorted(state["methods"]),
        "racing_modes": sorted(state["racing_modes"]),
        "final_outcomes": dict(sorted(state["final_outcomes"].items())),
        "failure_classes": dict(sorted(state["failure_classes"].items())),
        "provider_reasons": dict(sorted(state["provider_reasons"].items())),
        "attempted_models": sorted(state["attempted_models"]),
        "attempted_provider_profiles": sorted(state["attempted_provider_profiles"]),
        "attempted_wire_apis": sorted(state["attempted_wire_apis"]),
        "privacy_note": (
            "Racing observability metrics retain arm lifecycle counts, timing, provider/model "
            "ids, cancellation/winner flags, and usage-availability fields only. Raw prompts, "
            "model text, tool payload bodies, credentials, and private truth are not persisted."
        ),
    }


def model_input_filter_metrics(run_dir: Path) -> dict[str, Any]:
    events = _events_by_schema(run_dir, MODEL_INPUT_FILTER_SCHEMA)
    if not events:
        return _unavailable_metrics(
            "openai_agents_model_input_filter_events",
            "model_input_filter_events_missing",
        )

    state = _model_input_filter_state()
    for event in events:
        _record_model_input_filter_event(state, event)

    return {
        "available": True,
        "source": "openai_agents_model_input_filter_events",
        "limitations": [],
        "event_count": len(events),
        "enabled": state["enabled"],
        "modes": sorted(state["modes"]),
        "attempted_models": sorted(state["attempted_models"]),
        "attempted_provider_profiles": sorted(state["attempted_provider_profiles"]),
        "attempted_wire_apis": sorted(state["attempted_wire_apis"]),
        "compacted_item_count": state["compacted_item_count"],
        "unchanged_item_count": state["unchanged_item_count"],
        "repeated_item_count": state["repeated_item_count"],
        "metric_map_output_count": state["metric_map_output_count"],
        "repeated_metric_map_output_count": state["repeated_metric_map_output_count"],
        "metric_map_delta_compacted_count": state["metric_map_delta_compacted_count"],
        "metric_map_bytes_before": state["metric_map_bytes_before"],
        "metric_map_bytes_after": state["metric_map_bytes_after"],
        "metric_map_bytes_reduced": state["metric_map_bytes_reduced"],
        "metric_map_byte_reduction_ratio": _ratio(
            state["metric_map_bytes_reduced"],
            state["metric_map_bytes_before"],
        ),
        "raw_fpv_image_memory_enabled": state["raw_fpv_image_memory_enabled"],
        "raw_fpv_image_memory_modes": sorted(state["raw_fpv_image_memory_modes"]),
        "raw_fpv_image_item_count": state["raw_fpv_image_item_count"],
        "raw_fpv_image_retained_count": state["raw_fpv_image_retained_count"],
        "raw_fpv_image_evicted_count": state["raw_fpv_image_evicted_count"],
        "raw_fpv_image_transcoded_count": state["raw_fpv_image_transcoded_count"],
        "raw_fpv_image_bytes_before": state["raw_fpv_image_bytes_before"],
        "raw_fpv_image_bytes_after": state["raw_fpv_image_bytes_after"],
        "raw_fpv_image_bytes_reduced": state["raw_fpv_image_bytes_reduced"],
        "raw_fpv_image_byte_reduction_ratio": _ratio(
            state["raw_fpv_image_bytes_reduced"],
            state["raw_fpv_image_bytes_before"],
        ),
        "completed_tool_history_bundle_count": state["completed_tool_history_bundle_count"],
        "completed_tool_history_retained_count": state["completed_tool_history_retained_count"],
        "completed_tool_history_evicted_count": state["completed_tool_history_evicted_count"],
        "completed_tool_history_item_count_before": state[
            "completed_tool_history_item_count_before"
        ],
        "completed_tool_history_item_count_after": state["completed_tool_history_item_count_after"],
        "completed_tool_history_bytes_reduced": state["completed_tool_history_bytes_reduced"],
        "camera_grounded_history_enabled": state["camera_grounded_history_enabled"],
        "camera_grounded_history_modes": sorted(state["camera_grounded_history_modes"]),
        "camera_grounded_history_item_count": state["camera_grounded_history_item_count"],
        "camera_grounded_history_retained_count": state["camera_grounded_history_retained_count"],
        "camera_grounded_history_compacted_count": state["camera_grounded_history_compacted_count"],
        "camera_grounded_history_bytes_before": state["camera_grounded_history_bytes_before"],
        "camera_grounded_history_bytes_after": state["camera_grounded_history_bytes_after"],
        "camera_grounded_history_bytes_reduced": state["camera_grounded_history_bytes_reduced"],
        "camera_grounded_history_byte_reduction_ratio": _ratio(
            state["camera_grounded_history_bytes_reduced"],
            state["camera_grounded_history_bytes_before"],
        ),
        "input_bytes_before": state["input_bytes_before"],
        "input_bytes_after": state["input_bytes_after"],
        "input_bytes_reduced": state["input_bytes_reduced"],
        "input_byte_reduction_ratio": _ratio(
            state["input_bytes_reduced"],
            state["input_bytes_before"],
        ),
        "max_input_bytes_before": state["max_input_bytes_before"],
        "max_input_bytes_after": state["max_input_bytes_after"],
        "max_input_bytes_reduced": state["max_input_bytes_reduced"],
        "privacy_note": (
            "Model-input filter metrics retain aggregate counts, byte sizes, mode, provider, "
            "wire API, and model ids only. Raw prompts, model text, tool payload bodies, "
            "credentials, and private truth are not persisted."
        ),
    }


def _model_service_state() -> dict[str, Any]:
    state = _identity_state()
    state.update(
        {
            "event_counts": {},
            "failure_classes": {},
            "provider_reasons": {},
            "retry_delay_s_total": 0.0,
            "retry_delay_count": 0,
            "retry_exhausted": False,
            "final_outcomes": {},
        }
    )
    return state


def _model_racing_state() -> dict[str, Any]:
    state = _identity_state()
    state.update(
        {
            "event_counts": {},
            "methods": set(),
            "racing_modes": set(),
            "arm_ids": set(),
            "call_indexes": set(),
            "final_outcomes": {},
            "failure_classes": {},
            "provider_reasons": {},
            "elapsed_s_total": 0.0,
            "max_elapsed_s": 0.0,
            "winner_count": 0,
            "cancelled_count": 0,
            "cancellation_observed_count": 0,
            "loser_billing_unknown_count": 0,
            "racing_enabled": False,
            "racing_multiplier": 1.0,
            "max_arm_count": 1,
            "usage_available_count": 0,
            "usage_missing_count": 0,
            "total_input_tokens": 0,
            "total_cached_input_tokens": 0,
            "total_uncached_input_tokens": 0,
            "total_output_tokens": 0,
            "total_reasoning_tokens": 0,
        }
    )
    return state


def _model_input_filter_state() -> dict[str, Any]:
    state = _identity_state()
    state.update({key: 0 for key in MODEL_INPUT_SUM_FIELDS})
    state.update(
        {
            "enabled": False,
            "modes": set(),
            "input_bytes_before": 0,
            "input_bytes_after": 0,
            "input_bytes_reduced": 0,
            "max_input_bytes_before": 0,
            "max_input_bytes_after": 0,
            "max_input_bytes_reduced": 0,
            "raw_fpv_image_memory_enabled": False,
            "raw_fpv_image_memory_modes": set(),
            "camera_grounded_history_enabled": False,
            "camera_grounded_history_modes": set(),
        }
    )
    return state


def _identity_state() -> dict[str, Any]:
    return {
        "attempted_models": set(),
        "attempted_provider_profiles": set(),
        "attempted_wire_apis": set(),
    }


def _record_model_racing_event(state: dict[str, Any], event: dict[str, Any]) -> None:
    _record_event_count(state, event)
    _record_attempt_identity(state, event)
    _record_text_set(state["methods"], event.get("method"))
    _record_text_set(state["racing_modes"], event.get("racing_mode"))
    _record_text_set(state["arm_ids"], event.get("arm_id"))
    _record_int_set(state["call_indexes"], event.get("call_index"))
    _record_counted_text(state["final_outcomes"], event.get("final_outcome"))
    _record_counted_text(state["failure_classes"], event.get("failure_class"))
    _record_counted_text(state["provider_reasons"], event.get("provider_reason"))
    _record_model_racing_timing(state, event)
    _record_model_racing_flags(state, event)
    _record_model_racing_usage(state, event)
    state["racing_enabled"] = state["racing_enabled"] or bool(event.get("racing_enabled"))
    state["racing_multiplier"] = max(
        state["racing_multiplier"],
        _float_or_none(event.get("racing_multiplier")) or 1.0,
    )
    state["max_arm_count"] = max(state["max_arm_count"], _int_or_none(event.get("arm_count")) or 1)


def _record_model_input_filter_event(state: dict[str, Any], event: dict[str, Any]) -> None:
    _record_attempt_identity(state, event)
    config = event.get("config") if isinstance(event.get("config"), dict) else {}
    state["enabled"] = state["enabled"] or bool(config.get("enabled"))
    _record_text_set(state["modes"], config.get("mode"))

    metrics = event.get("metrics") if isinstance(event.get("metrics"), dict) else {}
    _record_model_input_byte_totals(state, metrics)
    for key in MODEL_INPUT_SUM_FIELDS:
        state[key] += _int_or_none(metrics.get(key)) or 0
    state["raw_fpv_image_memory_enabled"] = state["raw_fpv_image_memory_enabled"] or bool(
        metrics.get("raw_fpv_image_memory_enabled")
    )
    state["camera_grounded_history_enabled"] = state["camera_grounded_history_enabled"] or bool(
        metrics.get("camera_grounded_history_enabled")
    )
    _record_text_set(
        state["raw_fpv_image_memory_modes"],
        metrics.get("raw_fpv_image_memory_mode"),
    )
    _record_text_set(
        state["camera_grounded_history_modes"],
        metrics.get("camera_grounded_history_mode"),
    )


def _record_event_count(state: dict[str, Any], event: dict[str, Any]) -> None:
    event_type = str(event.get("event") or "")
    if event_type:
        state["event_counts"][event_type] = state["event_counts"].get(event_type, 0) + 1


def _record_attempt_identity(state: dict[str, Any], event: dict[str, Any]) -> None:
    _record_text_set(state["attempted_models"], event.get("model"))
    _record_text_set(state["attempted_provider_profiles"], event.get("provider_profile"))
    _record_text_set(state["attempted_wire_apis"], event.get("wire_api"))


def _record_model_service_failure(state: dict[str, Any], event: dict[str, Any]) -> None:
    if str(event.get("event") or "") != "model_service_failure":
        return
    _record_counted_text(state["failure_classes"], event.get("failure_class"))
    _record_counted_text(state["provider_reasons"], event.get("provider_reason"))


def _record_retry_state(state: dict[str, Any], event: dict[str, Any]) -> None:
    delay = _float_or_none(event.get("retry_delay_s"))
    if delay is not None:
        state["retry_delay_s_total"] += delay
        state["retry_delay_count"] += 1
    state["retry_exhausted"] = state["retry_exhausted"] or event.get("retry_exhausted") is True


def _record_model_racing_timing(state: dict[str, Any], event: dict[str, Any]) -> None:
    elapsed = _float_or_none(event.get("elapsed_s"))
    if elapsed is None:
        return
    state["elapsed_s_total"] += elapsed
    state["max_elapsed_s"] = max(state["max_elapsed_s"], elapsed)


def _record_model_racing_flags(state: dict[str, Any], event: dict[str, Any]) -> None:
    for event_key, state_key in (
        ("winner", "winner_count"),
        ("cancelled", "cancelled_count"),
        ("cancellation_observed", "cancellation_observed_count"),
        ("loser_billing_unknown", "loser_billing_unknown_count"),
    ):
        if event.get(event_key) is True:
            state[state_key] += 1


def _record_model_racing_usage(state: dict[str, Any], event: dict[str, Any]) -> None:
    usage = event.get("usage_summary") if isinstance(event.get("usage_summary"), dict) else {}
    if not usage:
        return
    if usage.get("usage_available") is not True:
        state["usage_missing_count"] += 1
        return
    state["usage_available_count"] += 1
    state["total_input_tokens"] += _int_or_none(usage.get("input_tokens")) or 0
    state["total_cached_input_tokens"] += _int_or_none(usage.get("cached_input_tokens")) or 0
    state["total_uncached_input_tokens"] += _int_or_none(usage.get("uncached_input_tokens")) or 0
    state["total_output_tokens"] += _int_or_none(usage.get("output_tokens")) or 0
    state["total_reasoning_tokens"] += _int_or_none(usage.get("reasoning_tokens")) or 0


def _record_model_input_byte_totals(state: dict[str, Any], metrics: dict[str, Any]) -> None:
    before = _int_or_none(metrics.get("input_bytes_before")) or 0
    after = _int_or_none(metrics.get("input_bytes_after")) or 0
    reduced = _int_or_none(metrics.get("input_bytes_reduced")) or 0
    state["input_bytes_before"] += before
    state["input_bytes_after"] += after
    state["input_bytes_reduced"] += reduced
    state["max_input_bytes_before"] = max(state["max_input_bytes_before"], before)
    state["max_input_bytes_after"] = max(state["max_input_bytes_after"], after)
    state["max_input_bytes_reduced"] = max(state["max_input_bytes_reduced"], reduced)


def _events_by_schema(run_dir: Path, schema: str) -> list[dict[str, Any]]:
    return [
        event
        for path in sorted(run_dir.glob("openai-agents-events*.jsonl"))
        for event in read_openai_agents_jsonl_source(path)
        if event.get("schema") == schema
    ]


def _response_span_end_events(run_dir: Path) -> list[dict[str, Any]]:
    events: list[dict[str, Any]] = []
    for path in sorted(run_dir.glob("openai-agents-spans*.jsonl")):
        for event in read_openai_agents_jsonl_source(path):
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


def _reasoning_tokens(usage: dict[str, Any]) -> int | None:
    details = usage.get("output_tokens_details")
    if isinstance(details, dict):
        return _int_or_none(details.get("reasoning_tokens"))
    return _int_or_none(usage.get("reasoning_tokens"))


def _context_window_failure_detected(timing: dict[str, Any], run_dir: Path) -> bool:
    haystack_parts = [
        str(timing.get("reason") or ""),
        str(timing.get("provider_reason") or ""),
        str(timing.get("detail") or ""),
    ]
    for path in sorted(run_dir.glob("openai-agents-*.jsonl")):
        text = path.read_text(encoding="utf-8", errors="replace")[:200_000].lower()
        haystack_parts.append(text)
    haystack = " ".join(haystack_parts).lower()
    return any(
        marker in haystack
        for marker in (
            "context window",
            "context length",
            "context_length",
            "maximum context",
            "input exceeds the context",
            "context-budget",
            "provider_context_failure",
        )
    )


def _nearest_rank_percentile(values: list[int], percentile: float) -> int | None:
    if not values:
        return None
    ordered = sorted(values)
    index = max(0, min(len(ordered) - 1, int(len(ordered) * percentile + 0.999999) - 1))
    return ordered[index]


def _unavailable_metrics(source: str, limitation: str) -> dict[str, Any]:
    return {
        "available": False,
        "source": source,
        "limitations": [limitation],
    }


def _record_text_set(target: set[str], value: Any) -> None:
    text = str(value or "")
    if text:
        target.add(text)


def _record_int_set(target: set[int], value: Any) -> None:
    int_value = _int_or_none(value)
    if int_value is not None:
        target.add(int_value)


def _record_counted_text(target: dict[str, int], value: Any) -> None:
    text = str(value or "")
    if text:
        target[text] = target.get(text, 0) + 1


def _ratio(numerator: int, denominator: int) -> float | None:
    if denominator <= 0:
        return None
    return round(numerator / denominator, 6)


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


def _round_duration(value: float) -> float:
    return round(max(0.0, value), 3)
