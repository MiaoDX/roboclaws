from __future__ import annotations

import json
from pathlib import Path

import pytest

from roboclaws.agents.drivers.openai_agents_budget import (
    OpenAIAgentsBudgetExceededError,
    openai_agents_budget_failure,
    openai_agents_observe_budget_advisory,
    raw_fpv_budget_metrics,
)
from roboclaws.agents.drivers.openai_agents_provider_runtime import (
    failure_from_exception as _failure_from_exception,
)
from roboclaws.agents.household_live_runner import (
    _budget_failure_from_run_state,
    _cache_metrics,
    _context_growth_metrics,
    _context_metrics,
)
from roboclaws.agents.live_status import LiveAgentFailure
from roboclaws.agents.live_timing import live_timing_timeline as _live_timing_timeline


def test_context_budget_guard_reads_chat_completion_generation_spans(tmp_path: Path) -> None:
    run_dir = tmp_path / "run"
    run_dir.mkdir()
    spans_path = run_dir / "openai-agents-spans.jsonl"
    spans_path.write_text(
        json.dumps(
            {
                "event": "span_end",
                "span_type": "generation",
                "usage": {"input_tokens": 120_000},
            }
        )
        + "\n",
        encoding="utf-8",
    )

    failure = openai_agents_budget_failure(
        run_dir,
        {},
        {"context_hard_limit_tokens": 96_000},
        context_spans_path=spans_path,
    )

    assert failure is not None
    assert failure.reason == "provider_context_budget_exceeded"


def test_openai_agents_runtime_classifies_sdk_max_turn_budget() -> None:
    class MaxTurnsExceeded(Exception):
        pass

    failure = _failure_from_exception(MaxTurnsExceeded("Max turns (40) exceeded"))

    assert failure.reason == "agent_sdk_turn_budget_exceeded"
    assert failure.retryable is False
    assert failure.resume_available is False


def test_openai_agents_budget_exception_preserves_failure_classification() -> None:
    exc = OpenAIAgentsBudgetExceededError(
        LiveAgentFailure(
            "provider_context_budget_exceeded",
            retryable=False,
            resume_available=False,
            detail='{"schema":"agent_sdk_context_budget_terminal_v1"}',
        )
    )

    failure = _failure_from_exception(exc)

    assert failure.reason == "provider_context_budget_exceeded"
    assert failure.retryable is False
    assert failure.detail == '{"schema":"agent_sdk_context_budget_terminal_v1"}'


def test_openai_agents_budget_guard_classifies_context_hard_limit(tmp_path: Path) -> None:
    run_dir = tmp_path / "run"
    run_dir.mkdir()
    (run_dir / "openai-agents-spans.jsonl").write_text(
        json.dumps(
            {
                "event": "span_end",
                "span_type": "response",
                "usage": {"input_tokens": 150, "input_tokens_details": {"cached_tokens": 50}},
            }
        )
        + "\n",
        encoding="utf-8",
    )

    failure = _budget_failure_from_run_state(
        run_dir,
        {"evidence_lane": "world-public-labels", "cache_tools_list": True},
        {
            "profile_id": "custom",
            "context_hard_limit_tokens": 100,
            "raw_fpv_candidate_budget": None,
            "max_observe_per_waypoint": None,
        },
    )

    assert failure is not None
    assert failure.reason == "provider_context_budget_exceeded"
    assert failure.retryable is False
    detail = json.loads(failure.detail)
    assert detail["current_input_tokens"] == 150
    assert detail["total_input_tokens"] == 150
    assert detail["context_hard_limit_tokens"] == 100


def test_context_budget_guard_is_scoped_to_current_attempt_spans(tmp_path: Path) -> None:
    run_dir = tmp_path / "run"
    run_dir.mkdir()
    base_spans = run_dir / "openai-agents-spans.jsonl"
    continuation_spans = run_dir / "openai-agents-spans.continuation-1.jsonl"
    base_spans.write_text(
        json.dumps(
            {
                "event": "span_end",
                "span_type": "response",
                "usage": {"input_tokens": 150},
            }
        )
        + "\n",
        encoding="utf-8",
    )
    continuation_spans.write_text(
        json.dumps(
            {
                "event": "span_end",
                "span_type": "response",
                "usage": {"input_tokens": 80},
            }
        )
        + "\n",
        encoding="utf-8",
    )
    profile = {"context_hard_limit_tokens": 100}

    assert (
        openai_agents_budget_failure(
            run_dir,
            {},
            profile,
            context_spans_path=continuation_spans,
        )
        is None
    )
    assert (
        openai_agents_budget_failure(
            run_dir,
            {},
            profile,
            context_spans_path=base_spans,
        ).reason
        == "provider_context_budget_exceeded"
    )


def test_openai_agents_budget_guard_uses_current_context_not_cumulative_tokens(
    tmp_path: Path,
) -> None:
    run_dir = tmp_path / "run"
    run_dir.mkdir()
    (run_dir / "openai-agents-spans.jsonl").write_text(
        "\n".join(
            json.dumps(
                {
                    "event": "span_end",
                    "span_type": "response",
                    "usage": {
                        "input_tokens": 40_000,
                        "input_tokens_details": {"cached_tokens": 38_000},
                    },
                }
            )
            for _ in range(4)
        )
        + "\n",
        encoding="utf-8",
    )

    failure = _budget_failure_from_run_state(
        run_dir,
        {"evidence_lane": "world-public-labels", "cache_tools_list": True},
        {
            "profile_id": "context_managed_v1",
            "context_hard_limit_tokens": 96_000,
            "raw_fpv_candidate_budget": None,
            "max_observe_per_waypoint": None,
        },
    )

    assert failure is None


def test_openai_agents_budget_guard_classifies_raw_fpv_candidate_exhaustion(
    tmp_path: Path,
) -> None:
    run_dir = tmp_path / "run"
    run_dir.mkdir()
    events = [
        {
            "event": "request",
            "tool": "navigate_to_visual_candidate",
            "request": {
                "source_observation_id": "raw_fpv_001",
                "category": "cup",
                "image_region": {"type": "bbox", "value": [1, 2, 3, 4]},
            },
        },
        {
            "event": "response",
            "tool": "navigate_to_visual_candidate",
            "response": {
                "ok": False,
                "source_observation_id": "raw_fpv_001",
                "category": "cup",
                "error_reason": "invalid_visual_candidate",
            },
        },
        {
            "event": "request",
            "tool": "navigate_to_visual_candidate",
            "request": {
                "source_observation_id": "raw_fpv_002",
                "category": "book",
                "image_region": {"type": "bbox", "value": [5, 6, 7, 8]},
            },
        },
    ]
    (run_dir / "trace.jsonl").write_text(
        "\n".join(json.dumps(item) for item in events) + "\n",
        encoding="utf-8",
    )

    failure = _budget_failure_from_run_state(
        run_dir,
        {"evidence_lane": "camera-raw-fpv", "cache_tools_list": True},
        {
            "profile_id": "context_managed_v1",
            "context_hard_limit_tokens": None,
            "raw_fpv_candidate_budget": 2,
            "max_observe_per_waypoint": None,
        },
    )

    assert failure is not None
    assert failure.reason == "raw_fpv_candidate_budget_exhausted"
    detail = json.loads(failure.detail)
    assert detail["candidate_attempt_count"] == 2
    assert detail["raw_fpv_candidate_budget"] == 2
    assert detail["candidate_attempts_sample"][0]["source_observation_id"] == "raw_fpv_001"


def test_openai_agents_budget_guard_classifies_repeated_raw_fpv_failures(
    tmp_path: Path,
) -> None:
    run_dir = tmp_path / "run"
    run_dir.mkdir()
    events = []
    for _ in range(3):
        events.extend(
            [
                {
                    "event": "request",
                    "tool": "navigate_to_visual_candidate",
                    "request": {
                        "source_observation_id": "raw_fpv_001",
                        "category": "cup",
                        "image_region": {"type": "bbox", "value": [1, 2, 3, 4]},
                    },
                },
                {
                    "event": "response",
                    "tool": "navigate_to_visual_candidate",
                    "response": {
                        "ok": False,
                        "object_id": f"observed_{len(events):03d}",
                        "error_reason": "source_observation_locality_unresolved",
                    },
                },
            ]
        )
    (run_dir / "trace.jsonl").write_text(
        "\n".join(json.dumps(item) for item in events) + "\n",
        encoding="utf-8",
    )

    failure = _budget_failure_from_run_state(
        run_dir,
        {"evidence_lane": "camera-raw-fpv", "cache_tools_list": True},
        {
            "profile_id": "context_managed_v1",
            "context_hard_limit_tokens": None,
            "raw_fpv_candidate_budget": 24,
            "raw_fpv_repeated_failure_limit": 3,
            "max_observe_per_waypoint": None,
        },
    )

    assert failure is not None
    assert failure.reason == "raw_fpv_repeated_candidate_failure"
    assert failure.retryable is False
    detail = json.loads(failure.detail)
    assert detail["reasons"] == ["raw_fpv_repeated_candidate_failure"]
    assert detail["raw_fpv_repeated_failure_limit"] == 3
    assert detail["candidate_attempt_count"] == 3
    assert detail["repeated_failure_limit_hits"][0]["count"] == 3
    assert detail["repeated_failure_limit_hits"][0]["category"] == "cup"
    assert detail["repeated_failure_limit_hits"][0]["failure_reason"] == (
        "source_observation_locality_unresolved"
    )
    assert "image_region" not in json.dumps(detail)


def test_openai_agents_budget_guard_ignores_success_status_as_failure() -> None:
    metrics = raw_fpv_budget_metrics(
        [
            {
                "event": "request",
                "tool": "navigate_to_visual_candidate",
                "request": {
                    "source_observation_id": "raw_fpv_001",
                    "category": "book",
                    "image_region": {"type": "bbox", "value": [1, 2, 3, 4]},
                },
            },
            {
                "event": "response",
                "tool": "navigate_to_visual_candidate",
                "response": {"ok": True, "status": "ok", "object_id": "observed_001"},
            },
        ]
    )

    assert metrics["candidate_attempt_count"] == 1
    assert metrics["repeated_failure_fingerprints"] == []


def test_raw_fpv_budget_pairs_mixed_embedded_and_fifo_responses() -> None:
    def request(source_id: str, category: str) -> dict[str, object]:
        return {
            "event": "request",
            "tool": "navigate_to_visual_candidate",
            "request": {
                "source_observation_id": source_id,
                "category": category,
                "image_region": {"type": "bbox", "value": [10, 20, 30, 40]},
            },
        }

    first = request("raw_fpv_001", "cup")
    second = request("raw_fpv_002", "book")
    metrics = raw_fpv_budget_metrics(
        [
            first,
            {
                "event": "response",
                "tool": "navigate_to_visual_candidate",
                "request": first["request"],
                "response": {"ok": False, "error_reason": "not_resolved"},
            },
            second,
            {
                "event": "response",
                "tool": "navigate_to_visual_candidate",
                "response": {"ok": False, "error_reason": "not_resolved"},
            },
        ]
    )

    assert [item["category"] for item in metrics["failed_candidate_attempts_sample"]] == [
        "cup",
        "book",
    ]


def test_openai_agents_budget_guard_reports_label_lane_observe_budget_as_advisory(
    tmp_path: Path,
) -> None:
    run_dir = tmp_path / "run"
    run_dir.mkdir()
    events = [
        {
            "event": "response",
            "tool": "observe",
            "response": {
                "ok": False,
                "waypoint_id": "generated_exploration_001",
                "error_reason": "capture_failed",
            },
        },
        {
            "event": "response",
            "tool": "observe",
            "response": {"ok": True},
        },
        {
            "event": "response",
            "tool": "observe",
            "response": {"ok": True, "waypoint_id": "generated_exploration_001"},
        },
        {
            "event": "response",
            "tool": "observe",
            "response": {"ok": True, "waypoint_id": "generated_exploration_001"},
        },
    ]
    (run_dir / "trace.jsonl").write_text(
        "\n".join(json.dumps(item) for item in events) + "\n",
        encoding="utf-8",
    )

    timing = {"evidence_lane": "camera-grounded-labels", "cache_tools_list": True}
    profile = {
        "profile_id": "context_managed_v1",
        "context_hard_limit_tokens": None,
        "raw_fpv_candidate_budget": None,
        "raw_fpv_repeated_failure_limit": None,
        "max_observe_per_waypoint": 1,
    }

    failure = _budget_failure_from_run_state(
        run_dir,
        timing,
        profile,
    )
    advisory = openai_agents_observe_budget_advisory(run_dir, timing, profile)

    assert failure is None
    assert advisory is not None
    assert advisory["schema"] == "agent_sdk_observe_budget_advisory_v1"
    assert advisory["reason"] == "observe_budget_exceeded"
    assert advisory["evidence_lane"] == "camera-grounded-labels"
    assert advisory["max_observe_per_waypoint"] == 1
    assert advisory["observe_count_by_waypoint"] == {"generated_exploration_001": 2}
    assert advisory["observe_over_budget_by_waypoint"] == {"generated_exploration_001": 2}


def test_openai_agents_context_metrics_parse_response_span_usage(tmp_path: Path) -> None:
    run_dir = tmp_path / "run"
    run_dir.mkdir()
    (run_dir / "openai-agents-spans.jsonl").write_text(
        "\n".join(
            [
                json.dumps(
                    {
                        "event": "span_end",
                        "span_type": "response",
                        "duration_s": 1.5,
                        "usage": {
                            "input_tokens": 100,
                            "input_tokens_details": {"cached_tokens": 25},
                            "output_tokens": 10,
                            "output_tokens_details": {"reasoning_tokens": 4},
                        },
                    }
                ),
                json.dumps(
                    {
                        "event": "span_end",
                        "span_type": "custom",
                        "duration_s": 1.6,
                        "usage": {
                            "input_tokens": 100,
                            "cached_input_tokens": 25,
                            "output_tokens": 10,
                        },
                    }
                ),
                json.dumps(
                    {
                        "event": "span_end",
                        "span_type": "response",
                        "duration_s": 2.5,
                        "usage": {
                            "input_tokens": 400,
                            "cached_input_tokens": 100,
                            "output_tokens": 20,
                        },
                    }
                ),
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    (run_dir / "trace.jsonl").write_text(
        "\n".join(
            [
                json.dumps({"event": "request", "tool": "observe"}),
                json.dumps(
                    {
                        "event": "response",
                        "tool": "observe",
                        "payload": {"observation_id": "raw_fpv_1"},
                    }
                ),
                json.dumps({"event": "response", "tool": "done", "payload": {"ok": True}}),
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    timing = {
        "kickoff_prompt_chars": 80,
        "cache_tools_list": True,
        "sdk_model_settings": {"prompt_cache_retention": "in_memory"},
        "kickoff_prompt_stable_prefix": {"hash": "stable-hash"},
        "openai_agents_attempts": [
            {"attempt_index": 0, "continuation_prompt_chars": 0},
            {"attempt_index": 1, "continuation_prompt_chars": 40},
        ],
    }

    context = _context_metrics(run_dir, timing)
    cache = _cache_metrics(context, timing)
    growth = _context_growth_metrics(run_dir, timing)

    assert context["available"] is True
    assert context["source"] == "openai_agents_span_usage"
    assert context["response_span_count"] == 2
    assert context["total_input_tokens"] == 500
    assert context["total_cached_input_tokens"] == 125
    assert context["total_uncached_input_tokens"] == 375
    assert context["cache_hit_ratio"] == 0.25
    assert context["p50_input_tokens"] == 100
    assert context["p95_input_tokens"] == 400
    assert context["total_reasoning_tokens"] == 4
    assert context["response_span_duration_s"] == 4.0
    assert context["kickoff_prompt_estimated_tokens"] == 20
    assert context["continuation_prompt_estimated_tokens"] == 10
    assert cache["available"] is True
    assert cache["provider_prompt_cache_observed"] is True
    assert cache["first_response_cached_tokens"] == 25
    assert cache["prompt_cache_retention"] == "in_memory"
    assert cache["stable_prefix_hash"] == "stable-hash"
    assert cache["mcp_tool_catalog_cache_enabled"] is True
    assert growth["available"] is True
    assert growth["trace_event_count"] == 3
    assert growth["observe_response_count"] == 1
    assert growth["raw_fpv_observation_count"] == 1
    assert growth["continuation_attempt_count"] == 1
    assert growth["tool_response_bytes_total"] > 0


def test_openai_agents_context_growth_metrics_fail_aloud_on_malformed_trace_source(
    tmp_path: Path,
) -> None:
    run_dir = tmp_path / "run"
    run_dir.mkdir()
    (run_dir / "trace.jsonl").write_text(
        '{"event":"request","tool":"observe"}\n{bad-json}\n',
        encoding="utf-8",
    )

    with pytest.raises(
        ValueError,
        match=r"OpenAI Agents metrics source row must contain valid JSON object: .*trace\.jsonl:2",
    ):
        _context_growth_metrics(run_dir, {})


def test_openai_agents_context_metrics_missing_usage_is_unavailable(tmp_path: Path) -> None:
    run_dir = tmp_path / "run"
    run_dir.mkdir()
    (run_dir / "openai-agents-spans.jsonl").write_text(
        json.dumps({"event": "span_end", "span_type": "response"}) + "\n",
        encoding="utf-8",
    )

    context = _context_metrics(run_dir, {"cache_tools_list": True})
    cache = _cache_metrics(
        context,
        {
            "cache_tools_list": True,
            "sdk_model_settings": {"prompt_cache_retention": "in_memory"},
            "kickoff_prompt_stable_prefix": {"hash": "stable-hash"},
        },
    )

    assert context["available"] is False
    assert context["source"] == "openai_agents_span_usage"
    assert "response_span_usage_missing" in context["limitations"]
    assert "total_input_tokens" not in context
    assert cache["available"] is False
    assert cache["source"] == "openai_agents_span_usage"
    assert "response_span_usage_missing" in cache["limitations"]
    assert cache["prompt_cache_retention"] == "in_memory"
    assert cache["stable_prefix_hash"] == "stable-hash"


def test_openai_agents_live_timing_compact_metrics_extracts_valid_budget_detail() -> None:
    timeline = _live_timing_timeline(
        {
            "runtime": "openai-agents-live",
            "provider_profile": "kimi-openai-chat",
            "wire_api": "responses",
            "model": "kimi-k2.7-code",
            "runner_timing": {},
            "agent_sdk_budget_terminal": {
                "available": True,
                "reason": "raw_fpv_candidate_budget_exhausted",
                "detail": json.dumps(
                    {
                        "schema": "openai_agents_raw_fpv_budget_failure_v1",
                        "raw_fpv_candidate_budget": 2,
                        "raw_fpv_repeated_failure_limit": 3,
                        "max_observe_per_waypoint": 1,
                        "candidate_attempt_count": 2,
                        "repeated_failure_fingerprints": ["a", "b"],
                        "repeated_failure_limit_hits": ["a"],
                        "observe_count_by_waypoint": {"wp-a": 1, "wp-b": 2},
                    }
                ),
            },
        }
    )

    metrics = timeline["latency_attribution"]["agent_sdk_budget_terminal"]
    assert metrics == {
        "available": True,
        "reason": "raw_fpv_candidate_budget_exhausted",
        "detail_schema": "openai_agents_raw_fpv_budget_failure_v1",
        "raw_fpv_candidate_budget": 2,
        "raw_fpv_repeated_failure_limit": 3,
        "max_observe_per_waypoint": 1,
        "candidate_attempt_count": 2,
        "repeated_failure_count": 2,
        "repeated_failure_limit_hit_count": 1,
        "observe_waypoint_count": 2,
    }
