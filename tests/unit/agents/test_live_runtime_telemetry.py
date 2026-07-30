from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

import pytest

from roboclaws.agents.drivers.openai_agents_spans import RoboclawsSpanRecorder
from roboclaws.agents.household_live_runner import (
    LiveOpenAIAgentsHouseholdRunner,
    _openai_agents_event_metrics,
    _openai_agents_span_metrics,
)
from roboclaws.agents.household_live_runner import (
    parse_args as _parse_live_openai_agents_args,
)
from roboclaws.agents.live_timing import live_timing_timeline as _live_timing_timeline
from roboclaws.agents.live_timing import mcp_control_plane_metrics as _mcp_control_plane_metrics
from tests.unit.agents.live_runtime_support import (
    _isolated_repo_root,
)


@pytest.mark.parametrize(
    ("source_name", "source_text", "expected_detail"),
    [
        ("run_result.json", "{not-json}\n", "run_result.json: invalid JSON"),
        ("run_result.json", "[1]\n", "run_result.json: non-object JSON: list"),
        (
            "trace.jsonl",
            json.dumps({"event": "request", "tool": "done"}) + "\n[]\n",
            "OpenAI Agents live source row must contain a JSON object",
        ),
    ],
)
def test_openai_agents_live_timing_fails_aloud_on_malformed_mcp_timing_source(
    tmp_path: Path,
    source_name: str,
    source_text: str,
    expected_detail: str,
) -> None:
    run_dir = tmp_path / "run"
    run_dir.mkdir()
    args = _parse_live_openai_agents_args(
        [
            "--run-dir",
            str(run_dir),
            "--repo-root",
            str(_isolated_repo_root(tmp_path)),
            "--status-path",
            str(run_dir / "live_status.json"),
            "--provider-profile",
            "kimi-openai-chat",
            "--model",
            "kimi-k2.7-code",
            "--client-url",
            "http://127.0.0.1:18788/mcp",
            "--host",
            "127.0.0.1",
            "--port",
            "18788",
            "--lock-path",
            str(tmp_path / "live.lock"),
            "--server-startup-timeout-s",
            "1",
            "--kickoff-prompt",
            "clean the room",
            "--backend",
            "molmospaces_subprocess",
            "--task",
            "clean",
            "--min-generated-mess-count",
            "5",
            "--profile",
            "smoke",
        ]
    )
    runner = LiveOpenAIAgentsHouseholdRunner(args)
    (run_dir / source_name).write_text(source_text, encoding="utf-8")

    source_error = runner._write_live_timing("finished", 0)

    timing = json.loads((run_dir / "live_timing.json").read_text(encoding="utf-8"))
    assert source_error.startswith("live_timing_source_error: OpenAI Agents live source")
    assert expected_detail in source_error
    assert timing["phase"] == "failed"
    assert timing["exit_status"] == 1
    assert timing["reason"] == source_error
    assert timing["live_timing_source_error"] == source_error
    assert timing["mcp_trace_timing"]["available"] is False
    assert expected_detail in timing["mcp_trace_timing"]["source_error"]


def test_openai_agents_control_plane_metrics_parse_server_log(tmp_path: Path) -> None:
    run_dir = tmp_path / "run"
    run_dir.mkdir()
    (run_dir / "openai-agents-server.log").write_text(
        "\n".join(
            [
                "[2026-06-09] INFO Created new transport with session ID: abc",
                'INFO:     127.0.0.1:1 - "POST /mcp HTTP/1.1" 200 OK',
                "[2026-06-09] INFO Processing request of type ListToolsRequest",
                'INFO:     127.0.0.1:2 - "POST /mcp HTTP/1.1" 202 Accepted',
                "[2026-06-09] INFO Processing request of type CallToolRequest",
                "[2026-06-09] INFO Processing request of type CallToolRequest",
                "OPENAI_API_KEY is not set, skipping trace export",
                "[2026-06-09] INFO Terminating session: abc",
            ]
        )
        + "\n",
        encoding="utf-8",
    )

    metrics = _mcp_control_plane_metrics(run_dir)

    assert metrics["available"] is True
    assert metrics["request_type_counts"] == {
        "CallToolRequest": 2,
        "ListToolsRequest": 1,
    }
    assert metrics["total_mcp_request_count"] == 3
    assert metrics["call_tool_request_count"] == 2
    assert metrics["list_tools_request_count"] == 1
    assert metrics["control_request_count"] == 1
    assert metrics["list_tools_per_call_tool"] == 0.5
    assert metrics["streamable_http_session_count"] == 1
    assert metrics["session_termination_count"] == 1
    assert metrics["trace_export_skip_count"] == 1
    assert metrics["http_status_counts"] == {
        "200 OK": 1,
        "202 Accepted": 1,
    }


def test_openai_agents_event_metrics_parse_tool_errors(tmp_path: Path) -> None:
    run_dir = tmp_path / "run"
    run_dir.mkdir()
    (run_dir / "openai-agents-events.jsonl").write_text(
        "\n".join(
            [
                json.dumps({"event": "start", "mcp_client_session_timeout_s": 5}),
                json.dumps(
                    {
                        "event": "tool_error",
                        "classification": "mcp_client_request_timeout",
                        "message": (
                            "Timed out while waiting for response to ClientRequest. "
                            "Waited 5.0 seconds."
                        ),
                    }
                ),
                json.dumps({"event": "result"}),
            ]
        )
        + "\n",
        encoding="utf-8",
    )

    metrics = _openai_agents_event_metrics(run_dir)

    assert metrics["available"] is True
    assert metrics["event_counts"]["tool_error"] == 1
    assert metrics["tool_error_count"] == 1
    assert metrics["tool_error_classifications"] == {"mcp_client_request_timeout": 1}
    assert "Waited 5.0 seconds" in metrics["tool_error_messages_sample"][0]


def test_openai_agents_event_metrics_fail_aloud_on_malformed_event_source(
    tmp_path: Path,
) -> None:
    run_dir = tmp_path / "run"
    run_dir.mkdir()
    (run_dir / "openai-agents-events.jsonl").write_text(
        '{"event":"result"}\n{bad-json}\n',
        encoding="utf-8",
    )

    with pytest.raises(
        ValueError,
        match=r"OpenAI Agents metrics source row must contain valid JSON object: "
        r".*openai-agents-events\.jsonl:2",
    ):
        _openai_agents_event_metrics(run_dir)


def test_openai_agents_span_recorder_writes_sanitized_span_events(tmp_path: Path) -> None:
    spans_path = tmp_path / "openai-agents-spans.jsonl"
    recorder = RoboclawsSpanRecorder(
        spans_path,
        runtime_config={
            "runtime": "openai-agents-live",
            "provider_profile": "kimi-openai-chat",
            "model": "kimi-k2.7-code",
        },
    )

    class FakeSpanData:
        type = "function"

        def export(self) -> dict[str, object]:
            return {
                "type": "function",
                "name": "pickup_object",
                "input": '{"secret":"prompt text"}',
                "output": '{"private_target_truth": true}',
                "mcp_data": {"server": "cleanup", "tool_name": "pickup_object"},
            }

    class FakeSpan:
        trace_id = "trace_1"
        span_id = "span_1"
        parent_id = "span_parent"
        started_at = datetime.fromtimestamp(100, UTC).isoformat()
        ended_at = datetime.fromtimestamp(102.5, UTC).isoformat()
        span_data = FakeSpanData()
        error = {"message": "tool failed", "data": {"raw": "not persisted"}}

    recorder.on_span_end(FakeSpan())
    recorder.shutdown()
    recorder.on_span_end(FakeSpan())

    events = [json.loads(line) for line in spans_path.read_text(encoding="utf-8").splitlines()]

    assert len(events) == 1
    event = events[0]
    assert event["schema"] == "openai_agents_sanitized_span_v1"
    assert event["event"] == "span_end"
    assert event["runtime"] == "openai-agents-live"
    assert event["span_type"] == "function"
    assert event["span_name"] == "pickup_object"
    assert event["duration_s"] == 2.5
    assert event["mcp"] == {"server": "cleanup", "tool_name": "pickup_object"}
    assert event["error"] == {"message": "tool failed", "data_keys": ["raw"]}
    assert "input" not in event
    assert "output" not in event


def test_openai_agents_span_metrics_parse_span_artifacts(tmp_path: Path) -> None:
    run_dir = tmp_path / "run"
    run_dir.mkdir()
    (run_dir / "openai-agents-spans.jsonl").write_text(
        "\n".join(
            [
                json.dumps({"event": "trace_start", "trace_id": "trace_1"}),
                json.dumps({"event": "span_end", "span_type": "response"}),
                json.dumps({"event": "span_end", "span_type": "function"}),
                json.dumps(
                    {
                        "event": "span_capture_unavailable",
                        "reason": "sdk_trace_processor_registration_failed",
                        "error_type": "RuntimeError",
                        "message": "cannot register",
                    }
                ),
            ]
        )
        + "\n",
        encoding="utf-8",
    )

    metrics = _openai_agents_span_metrics(run_dir)

    assert metrics["available"] is True
    assert metrics["span_files"] == ["openai-agents-spans.jsonl"]
    assert metrics["event_counts"]["span_end"] == 2
    assert metrics["span_end_count"] == 2
    assert metrics["span_type_counts"] == {"function": 1, "response": 1}
    assert metrics["limitations"] == [
        {
            "reason": "sdk_trace_processor_registration_failed",
            "error_type": "RuntimeError",
            "message": "cannot register",
        }
    ]
    assert "Raw prompts" in metrics["sanitization_note"]


def test_openai_agents_span_metrics_fail_aloud_on_non_object_span_source(
    tmp_path: Path,
) -> None:
    run_dir = tmp_path / "run"
    run_dir.mkdir()
    (run_dir / "openai-agents-spans.jsonl").write_text(
        json.dumps(["not", "an", "event"]) + "\n",
        encoding="utf-8",
    )

    with pytest.raises(
        ValueError,
        match=r"OpenAI Agents metrics source row must contain a JSON object: "
        r".*openai-agents-spans\.jsonl:1",
    ):
        _openai_agents_span_metrics(run_dir)


def test_openai_agents_live_timing_timeline_partitions_runner_and_attribution() -> None:
    timing = {
        "surface": "household-world",
        "intent": "open-ended",
        "task_name": "household-world",
        "runtime": "openai-agents-live",
        "provider_profile": "kimi-openai-chat",
        "wire_api": "responses",
        "model": "kimi-k2.7-code",
        "evidence_lane": "world-public-labels",
        "started_at_epoch": 100.0,
        "openai_agents_start_epoch": 105.0,
        "openai_agents_end_epoch": 145.0,
        "server_finished_epoch": 146.0,
        "checker_start_epoch": 146.5,
        "checker_end_epoch": 148.0,
        "finished_at_epoch": 149.0,
        "mcp_client_session_timeout_s": 30.0,
        "runner_timing": {
            "total_elapsed_s": 49.0,
            "openai_agents_elapsed_s": 40.0,
        },
        "mcp_trace_timing": {
            "total_elapsed_s": 33.0,
            "between_tool_gap_s": 20.0,
            "robot_view_capture_s": 6.0,
            "tool_handler_s": 5.0,
            "other_mcp_overhead_s": 2.0,
            "tool_call_count": 10,
        },
        "mcp_control_plane_metrics": {"list_tools_request_count": 2},
        "openai_agents_event_metrics": {
            "tool_error_count": 1,
            "tool_error_classifications": {"mcp_client_request_timeout": 1},
        },
        "openai_agents_span_metrics": {
            "available": True,
            "span_end_count": 3,
            "span_type_counts": {"function": 2, "response": 1},
            "limitations": [],
        },
        "model_service_fallback_metrics": {
            "available": True,
            "source": "openai_agents_model_service_fallback_events",
            "limitations": [],
            "attempt_event_count": 2,
            "retry_scheduled_count": 1,
            "failure_event_count": 1,
            "success_event_count": 1,
            "failure_classes": {"provider_transient_failure": 1},
            "provider_reasons": {"upstream_unavailable": 1},
            "attempted_models": ["kimi-k2.7-code"],
            "attempted_provider_profiles": ["kimi-openai-chat"],
            "attempted_wire_apis": ["responses"],
            "retry_delay_s_total": 1.0,
            "retry_delay_count": 1,
            "retry_exhausted": False,
            "final_outcomes": {"success": 1},
        },
        "model_input_filter_metrics": {
            "available": True,
            "source": "openai_agents_model_input_filter_events",
            "limitations": [],
            "event_count": 2,
            "enabled": True,
            "modes": ["public_tool_result_summary_v1"],
            "attempted_models": ["kimi-k2.7-code"],
            "attempted_provider_profiles": ["kimi-openai-chat"],
            "attempted_wire_apis": ["responses"],
            "compacted_item_count": 2,
            "unchanged_item_count": 3,
            "repeated_item_count": 1,
            "input_bytes_before": 2500,
            "input_bytes_after": 1300,
            "input_bytes_reduced": 1200,
            "input_byte_reduction_ratio": 0.48,
            "metric_map_output_count": 3,
            "repeated_metric_map_output_count": 1,
            "metric_map_delta_compacted_count": 1,
            "metric_map_bytes_before": 1700,
            "metric_map_bytes_after": 800,
            "metric_map_bytes_reduced": 900,
            "metric_map_byte_reduction_ratio": 0.529412,
            "raw_fpv_image_memory_enabled": True,
            "raw_fpv_image_memory_modes": ["retain_latest_full_frame"],
            "raw_fpv_image_item_count": 2,
            "raw_fpv_image_retained_count": 1,
            "raw_fpv_image_evicted_count": 1,
            "raw_fpv_image_bytes_before": 1000,
            "raw_fpv_image_bytes_after": 350,
            "raw_fpv_image_bytes_reduced": 650,
            "raw_fpv_image_byte_reduction_ratio": 0.65,
        },
        "model_racing_observability_metrics": {
            "available": True,
            "source": "openai_agents_model_racing_observability_events",
            "limitations": [],
            "event_count": 2,
            "call_count": 1,
            "arm_count": 1,
            "max_arm_count_per_call": 1,
            "racing_enabled": False,
            "racing_multiplier": 1.0,
            "winner_count": 1,
            "cancelled_count": 0,
            "cancellation_observed_count": 0,
            "loser_billing_unknown_count": 0,
            "elapsed_s_total": 2.5,
            "max_elapsed_s": 2.5,
            "usage_available_count": 1,
            "usage_missing_count": 0,
            "total_input_tokens": 120,
            "total_cached_input_tokens": 20,
            "total_uncached_input_tokens": 100,
            "total_output_tokens": 30,
            "total_reasoning_tokens": 5,
            "methods": ["get_response"],
            "racing_modes": ["per_arm_observability_v1"],
            "final_outcomes": {"success": 1},
        },
        "context_metrics": {
            "available": True,
            "source": "openai_agents_span_usage",
            "limitations": [],
            "total_input_tokens": 500,
            "total_cached_input_tokens": 125,
            "total_uncached_input_tokens": 375,
            "cache_hit_ratio": 0.25,
            "response_span_duration_s": 4.0,
        },
        "cache_metrics": {
            "available": True,
            "source": "openai_agents_span_usage",
            "limitations": [],
            "provider_prompt_cache_observed": True,
            "cached_input_token_ratio": 0.25,
        },
        "context_growth_metrics": {
            "available": True,
            "source": "live_timing_and_trace",
            "limitations": [],
            "trace_event_count": 10,
            "observe_response_count": 2,
            "raw_fpv_observation_count": 0,
            "tool_response_bytes_total": 1000,
            "continuation_attempt_count": 1,
        },
        "openai_agents_attempts": [
            {
                "attempt_index": 0,
                "attempt_role": "initial",
                "phase": "agent-turn-complete",
                "started_at_epoch": 105.0,
                "finished_at_epoch": 115.0,
                "run_result_present": False,
                "recovery_action": "continue",
                "recovery_reason": "incomplete_agent_turn",
            },
            {
                "attempt_index": 1,
                "attempt_role": "continuation",
                "phase": "finished",
                "started_at_epoch": 115.0,
                "finished_at_epoch": 145.0,
                "run_result_present": True,
            },
        ],
    }

    timeline = _live_timing_timeline(timing)

    assert timeline["schema"] == "live_agent_timeline_v1"
    assert timeline["surface"] == "household-world"
    assert timeline["intent"] == "open-ended"
    assert timeline["task_name"] == "household-world"
    assert timeline["runtime"] == "openai-agents-live"
    assert timeline["provider_profile"] == "kimi-openai-chat"
    assert timeline["wire_api"] == "responses"
    assert timeline["model"] == "kimi-k2.7-code"
    assert timeline["evidence_lane"] == "world-public-labels"
    assert [segment["duration_s"] for segment in timeline["runner_segments"]] == [
        5.0,
        40.0,
        1.0,
        1.5,
        1.0,
    ]
    assert [segment["name"] for segment in timeline["openai_agents_attempt_segments"]] == [
        "sdk_attempt_0",
        "sdk_attempt_1",
    ]
    assert timeline["latency_attribution"]["model_or_sdk_unattributed_s"] == 3.0
    assert timeline["latency_attribution"]["openai_agents_tool_error_classifications"] == {
        "mcp_client_request_timeout": 1
    }
    assert timeline["latency_attribution"]["openai_agents_span_artifact_available"] is True
    assert timeline["latency_attribution"]["openai_agents_span_count"] == 3
    assert timeline["latency_attribution"]["openai_agents_span_type_counts"] == {
        "function": 2,
        "response": 1,
    }
    assert timeline["latency_attribution"]["model_service_fallback_metrics"] == {
        "available": True,
        "source": "openai_agents_model_service_fallback_events",
        "limitations": [],
        "attempt_event_count": 2,
        "retry_scheduled_count": 1,
        "failure_event_count": 1,
        "success_event_count": 1,
        "failure_classes": {"provider_transient_failure": 1},
        "provider_reasons": {"upstream_unavailable": 1},
        "attempted_models": ["kimi-k2.7-code"],
        "attempted_provider_profiles": ["kimi-openai-chat"],
        "attempted_wire_apis": ["responses"],
        "retry_delay_s_total": 1.0,
        "retry_delay_count": 1,
        "retry_exhausted": False,
        "final_outcomes": {"success": 1},
    }
    assert timeline["latency_attribution"]["model_input_filter_metrics"] == {
        "available": True,
        "source": "openai_agents_model_input_filter_events",
        "limitations": [],
        "event_count": 2,
        "enabled": True,
        "modes": ["public_tool_result_summary_v1"],
        "attempted_models": ["kimi-k2.7-code"],
        "attempted_provider_profiles": ["kimi-openai-chat"],
        "attempted_wire_apis": ["responses"],
        "compacted_item_count": 2,
        "unchanged_item_count": 3,
        "repeated_item_count": 1,
        "input_bytes_before": 2500,
        "input_bytes_after": 1300,
        "input_bytes_reduced": 1200,
        "input_byte_reduction_ratio": 0.48,
        "metric_map_output_count": 3,
        "repeated_metric_map_output_count": 1,
        "metric_map_delta_compacted_count": 1,
        "metric_map_bytes_before": 1700,
        "metric_map_bytes_after": 800,
        "metric_map_bytes_reduced": 900,
        "metric_map_byte_reduction_ratio": 0.529412,
        "raw_fpv_image_memory_enabled": True,
        "raw_fpv_image_memory_modes": ["retain_latest_full_frame"],
        "raw_fpv_image_item_count": 2,
        "raw_fpv_image_retained_count": 1,
        "raw_fpv_image_evicted_count": 1,
        "raw_fpv_image_bytes_before": 1000,
        "raw_fpv_image_bytes_after": 350,
        "raw_fpv_image_bytes_reduced": 650,
        "raw_fpv_image_byte_reduction_ratio": 0.65,
    }
    assert timeline["latency_attribution"]["model_racing_observability_metrics"] == {
        "available": True,
        "source": "openai_agents_model_racing_observability_events",
        "limitations": [],
        "event_count": 2,
        "call_count": 1,
        "arm_count": 1,
        "max_arm_count_per_call": 1,
        "racing_enabled": False,
        "racing_multiplier": 1.0,
        "winner_count": 1,
        "cancelled_count": 0,
        "cancellation_observed_count": 0,
        "loser_billing_unknown_count": 0,
        "elapsed_s_total": 2.5,
        "max_elapsed_s": 2.5,
        "usage_available_count": 1,
        "usage_missing_count": 0,
        "total_input_tokens": 120,
        "total_cached_input_tokens": 20,
        "total_uncached_input_tokens": 100,
        "total_output_tokens": 30,
        "total_reasoning_tokens": 5,
        "methods": ["get_response"],
        "racing_modes": ["per_arm_observability_v1"],
        "final_outcomes": {"success": 1},
    }
    assert timeline["latency_attribution"]["context_metrics"] == {
        "available": True,
        "source": "openai_agents_span_usage",
        "limitations": [],
        "total_input_tokens": 500,
        "total_cached_input_tokens": 125,
        "total_uncached_input_tokens": 375,
        "cache_hit_ratio": 0.25,
    }
    assert timeline["latency_attribution"]["cache_metrics"] == {
        "available": True,
        "source": "openai_agents_span_usage",
        "limitations": [],
        "cached_input_token_ratio": 0.25,
        "provider_prompt_cache_observed": True,
    }
    assert timeline["latency_attribution"]["context_growth_metrics"] == {
        "available": True,
        "source": "live_timing_and_trace",
        "limitations": [],
        "trace_event_count": 10,
        "observe_response_count": 2,
        "raw_fpv_observation_count": 0,
        "tool_response_bytes_total": 1000,
        "continuation_attempt_count": 1,
    }


@pytest.mark.parametrize(
    ("detail", "expected_error", "expected_kind"),
    [
        (
            '{"schema":',
            "detail must contain a valid JSON object: Expecting value",
            "invalid_json",
        ),
        (
            '["wrong-shape"]',
            "detail must contain a JSON object, got list",
            "non_object",
        ),
    ],
)
def test_openai_agents_live_timing_compact_metrics_surface_structured_detail_errors(
    detail: str,
    expected_error: str,
    expected_kind: str,
) -> None:
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
                "detail": detail,
            },
        }
    )

    metrics = timeline["latency_attribution"]["agent_sdk_budget_terminal"]
    assert metrics == {
        "available": True,
        "reason": "raw_fpv_candidate_budget_exhausted",
        "detail_source_error": expected_error,
        "detail_source_error_kind": expected_kind,
    }


def test_openai_agents_live_timing_compact_metrics_tolerates_plaintext_detail() -> None:
    timeline = _live_timing_timeline(
        {
            "runtime": "openai-agents-live",
            "provider_profile": "kimi-openai-chat",
            "wire_api": "responses",
            "model": "kimi-k2.7-code",
            "runner_timing": {},
            "agent_sdk_budget_terminal": {
                "available": True,
                "reason": "provider_transient_failure",
                "provider_reason": "rate_limit",
                "detail": "429 Too Many Requests",
            },
        }
    )

    metrics = timeline["latency_attribution"]["agent_sdk_budget_terminal"]
    assert metrics == {
        "available": True,
        "reason": "provider_transient_failure",
        "provider_reason": "rate_limit",
    }
