from __future__ import annotations

import json
from pathlib import Path

import pytest

from roboclaws.core.live_performance import (
    MODEL_CALL_METRIC_SCHEMA,
    REPORT_PERFORMANCE_SCHEMA,
    ReportPerformanceSourceError,
    extract_model_call_metrics,
    extract_report_performance_metrics,
    privacy_findings_for_run_dir,
    write_model_call_metrics_jsonl,
)
from roboclaws.core.live_performance_comparison import (
    compare_report_performance_metrics,
    compare_run_dirs,
)


def test_extract_report_performance_metrics_covers_quality_model_work_and_timing(
    tmp_path: Path,
) -> None:
    run_dir = _write_run(
        tmp_path / "run",
        restored=5,
        elapsed_s=70,
        gap_s=30,
        input_tokens=400,
        cached_tokens=100,
        output_tokens=20,
        reasoning_tokens=4,
        duration_s=12.5,
    )

    packet = extract_report_performance_metrics(run_dir, write_model_call_metrics=True)

    assert packet["schema"] == REPORT_PERFORMANCE_SCHEMA
    assert packet["run_identity"]["wire_api"] == "responses"
    assert packet["quality"]["restored_count"] == 5
    assert packet["quality"]["failed_or_noop_tool_count"] == 0
    assert packet["call_counts"]["model_call_count"] == 1
    assert packet["call_counts"]["mcp_tool_counts"]["done"] == 1
    assert packet["model_work"]["total_input_tokens"] == 400
    assert packet["model_work"]["total_uncached_input_tokens"] == 300
    assert packet["model_work"]["total_output_tokens"] == 20
    assert packet["model_work"]["total_reasoning_tokens"] == 4
    assert packet["timing"]["observed_wall_s"] == 70
    assert packet["timing"]["observed_model_api_s"] == 12.5
    assert packet["timing"]["estimated_model_work_s"]["available"] is False
    rows = [
        json.loads(line)
        for line in (run_dir / "model_call_metrics.jsonl").read_text(encoding="utf-8").splitlines()
    ]
    assert rows[0]["schema"] == MODEL_CALL_METRIC_SCHEMA
    assert rows[0]["source"] == "openai_agents_span"
    assert rows[0]["wire_api"] == "responses"


def test_extract_report_performance_metrics_uses_explicit_calibration(
    tmp_path: Path,
) -> None:
    run_dir = _write_run(
        tmp_path / "run",
        restored=5,
        elapsed_s=70,
        gap_s=30,
        input_tokens=400,
        cached_tokens=100,
        output_tokens=20,
        reasoning_tokens=4,
        duration_s=12.5,
    )

    packet = extract_report_performance_metrics(run_dir, calibration=_calibration_packet())

    estimate = packet["timing"]["estimated_model_work_s"]
    assert estimate["available"] is True
    assert estimate["source"] == "calibration_packet"
    assert estimate["sample_count"] == 20
    assert estimate["coefficient_scope"] == {
        "agent_engine": "openai-agents-sdk",
        "provider_profile": "kimi-openai-chat",
        "model": "gpt-5.5",
        "wire_api": "responses",
    }
    assert estimate["estimated_s"] == 5.9
    assert packet["timing"]["model_latency_residual_s"] == 6.6
    assert "calibration_coefficients_unavailable" not in packet["limitations"]


def test_compare_run_dirs_with_calibration_reports_normalized_deltas(tmp_path: Path) -> None:
    baseline = _write_run(
        tmp_path / "baseline",
        restored=5,
        elapsed_s=100,
        gap_s=50,
        input_tokens=400,
        cached_tokens=100,
        output_tokens=20,
        reasoning_tokens=4,
        duration_s=12.5,
    )
    candidate = _write_run(
        tmp_path / "candidate",
        restored=5,
        elapsed_s=80,
        gap_s=40,
        input_tokens=300,
        cached_tokens=50,
        output_tokens=15,
        reasoning_tokens=2,
        duration_s=8.0,
    )

    comparison = compare_run_dirs(
        baseline_dir=baseline,
        candidate_dir=candidate,
        calibration=_calibration_packet(),
    )

    assert comparison["status"] == "accepted"
    timing = comparison["timing_comparison"]
    assert timing["observed_wall_delta_s"] == -20
    assert timing["estimated_model_work_delta_s"] == -1.2
    assert timing["model_latency_residual_delta_s"] == -3.3
    assert timing["baseline"]["estimated_model_work_s"]["estimated_s"] == 5.9
    assert timing["candidate"]["estimated_model_work_s"]["estimated_s"] == 4.7


def test_retired_raw_events_are_not_extracted_as_current_model_calls(
    tmp_path: Path,
) -> None:
    run_dir = tmp_path / "claude"
    run_dir.mkdir()
    (run_dir / "live_timing.json").write_text(
        json.dumps({"runtime": "claude-code", "provider_profile": "retired-anthropic-profile"}),
        encoding="utf-8",
    )
    (run_dir / "claude-events.jsonl").write_text('{"type":"result"}\n', encoding="utf-8")

    rows = extract_model_call_metrics(run_dir)

    assert rows[0]["agent_engine"] == "unknown"
    assert rows[0]["source"] == "unavailable"
    assert rows[0]["limitations"] == ["unknown_model_call_telemetry_unavailable"]


def test_comparison_reads_historical_serialized_retired_engine_identity() -> None:
    historical = {
        "run_dir": "fixtures/retired-codex-run",
        "run_identity": {"agent_engine": "codex-cli", "provider_profile": "retired-profile"},
        "quality": {"checker_state": "result-present", "restored_count": 1},
        "call_counts": {},
        "model_work": {},
        "timing": {"observed_wall_s": 10.0},
    }
    current = {
        **historical,
        "run_dir": "fixtures/current-sdk-run",
        "run_identity": {
            "agent_engine": "openai-agents-sdk",
            "provider_profile": "kimi-openai-chat",
        },
    }

    comparison = compare_report_performance_metrics(historical, current, diagnostic=True)

    assert comparison["baseline"]["run_identity"]["agent_engine"] == "codex-cli"
    assert comparison["identity_comparison"]["apples_to_oranges"] is True


def test_compare_rejects_faster_but_worse_candidate(tmp_path: Path) -> None:
    baseline = _write_run(tmp_path / "baseline", restored=5, elapsed_s=100, gap_s=50)
    candidate = _write_run(tmp_path / "candidate", restored=4, elapsed_s=50, gap_s=25)

    comparison = compare_run_dirs(baseline_dir=baseline, candidate_dir=candidate)

    assert comparison["status"] == "rejected"
    assert "candidate is faster but worse" in comparison["reasons"]
    assert comparison["quality_comparison"]["regressed"] is True
    assert comparison["timing_comparison"]["observed_wall_delta_s"] == -50


def test_compare_caps_sweep_overcoverage_for_quality_gate(tmp_path: Path) -> None:
    baseline = _write_run(tmp_path / "baseline", restored=3, elapsed_s=100, gap_s=50)
    candidate = _write_run(tmp_path / "candidate", restored=4, elapsed_s=50, gap_s=25)
    run_result = json.loads((baseline / "run_result.json").read_text(encoding="utf-8"))
    run_result["sweep_coverage_rate"] = 1.071429
    (baseline / "run_result.json").write_text(json.dumps(run_result), encoding="utf-8")

    comparison = compare_run_dirs(baseline_dir=baseline, candidate_dir=candidate)

    assert comparison["quality_comparison"]["checks"]["sweep_coverage_rate"] is True
    assert comparison["quality_comparison"]["regressed"] is False
    assert comparison["status"] == "accepted"


def test_compare_treats_different_wire_api_as_different_identity(tmp_path: Path) -> None:
    baseline = _write_run(tmp_path / "baseline", restored=5, elapsed_s=100, gap_s=50)
    candidate = _write_run(
        tmp_path / "candidate",
        restored=5,
        elapsed_s=100,
        gap_s=50,
        provider_profile="kimi-openai-chat",
        model="kimi-k2.7-code",
        wire_api="chat-completions",
    )

    comparison = compare_run_dirs(baseline_dir=baseline, candidate_dir=candidate)

    assert comparison["identity_comparison"]["apples_to_oranges"] is True
    assert "wire_api" in comparison["identity_comparison"]["mismatched_fields"]


def test_privacy_gate_scans_model_call_metrics(tmp_path: Path) -> None:
    run_dir = tmp_path / "run"
    run_dir.mkdir()
    write_model_call_metrics_jsonl(
        run_dir / "model_call_metrics.jsonl",
        [
            {
                "schema": MODEL_CALL_METRIC_SCHEMA,
                "agent_engine": "codex-cli",
                "provider_profile": "kimi-openai-chat",
                "model": "gpt-5.5",
                "raw_prompt": "do not persist",
            }
        ],
    )

    findings = privacy_findings_for_run_dir(run_dir)

    assert any(finding["reason"] == "forbidden key raw_prompt" for finding in findings)


def test_report_performance_metrics_fail_aloud_on_malformed_json_source(
    tmp_path: Path,
) -> None:
    run_dir = _write_run(tmp_path / "run", restored=5, elapsed_s=70, gap_s=30)
    (run_dir / "run_result.json").write_text("{not-json", encoding="utf-8")

    with pytest.raises(ReportPerformanceSourceError, match=r"run_result\.json.*line 1"):
        extract_report_performance_metrics(run_dir)


def test_report_performance_metrics_fail_aloud_on_non_object_json_source(
    tmp_path: Path,
) -> None:
    run_dir = _write_run(tmp_path / "run", restored=5, elapsed_s=70, gap_s=30)
    (run_dir / "live_timing.json").write_text("[]", encoding="utf-8")

    with pytest.raises(ReportPerformanceSourceError, match=r"live_timing\.json.*expected object"):
        extract_report_performance_metrics(run_dir)


def test_report_performance_metrics_fail_aloud_on_malformed_jsonl_source(
    tmp_path: Path,
) -> None:
    run_dir = _write_run(tmp_path / "run", restored=5, elapsed_s=70, gap_s=30)
    (run_dir / "trace.jsonl").write_text(
        '{"event":"response","tool":"observe"}\n{bad-json}\n',
        encoding="utf-8",
    )

    with pytest.raises(ReportPerformanceSourceError, match=r"trace\.jsonl:2"):
        extract_report_performance_metrics(run_dir)


def test_report_performance_metrics_fail_aloud_on_non_object_jsonl_source(
    tmp_path: Path,
) -> None:
    run_dir = _write_run(tmp_path / "run", restored=5, elapsed_s=70, gap_s=30)
    (run_dir / "openai-agents-spans.jsonl").write_text(
        json.dumps(["not", "an", "object"]) + "\n",
        encoding="utf-8",
    )

    with pytest.raises(
        ReportPerformanceSourceError,
        match=r"openai-agents-spans\.jsonl:1",
    ):
        extract_model_call_metrics(run_dir)


def _write_run(
    run_dir: Path,
    *,
    restored: int,
    elapsed_s: float,
    gap_s: float,
    input_tokens: int = 100,
    cached_tokens: int = 0,
    output_tokens: int = 10,
    reasoning_tokens: int = 0,
    duration_s: float = 5.0,
    provider_profile: str = "kimi-openai-chat",
    model: str = "gpt-5.5",
    wire_api: str = "responses",
) -> Path:
    run_dir.mkdir()
    (run_dir / "live_timing.json").write_text(
        json.dumps(
            {
                "runtime": "openai-agents-live",
                "surface": "household-world",
                "intent": "cleanup",
                "task_name": "household-cleanup",
                "provider_profile": provider_profile,
                "wire_api": wire_api,
                "model": model,
                "evidence_lane": "world-public-labels",
                "runner_timing": {"total_elapsed_s": elapsed_s},
                "mcp_trace_timing": {"between_tool_gap_s": gap_s, "tool_handler_s": 5.0},
            }
        ),
        encoding="utf-8",
    )
    (run_dir / "live_status.json").write_text(
        json.dumps({"phase": "finished", "exit_status": 0}),
        encoding="utf-8",
    )
    (run_dir / "run_result.json").write_text(
        json.dumps(
            {
                "task_surface": "household-world",
                "task_intent": "cleanup",
                "task_name": "household-cleanup",
                "cleanup_status": "success",
                "completion_status": "success",
                "mess_restoration_rate": restored / 5,
                "sweep_coverage_rate": 1.0,
                "disturbance_count": 0,
                "score": {
                    "restored_count": restored,
                    "total_targets": 5,
                    "object_results": [{"restored": True} for _ in range(restored)],
                },
            }
        ),
        encoding="utf-8",
    )
    (run_dir / "trace.jsonl").write_text(
        "\n".join(
            json.dumps({"event": "response", "tool": tool, "response": {"ok": True}})
            for tool in ["observe", "pick", "place", "done"]
        )
        + "\n",
        encoding="utf-8",
    )
    (run_dir / "openai-agents-spans.jsonl").write_text(
        json.dumps(
            {
                "event": "span_end",
                "span_type": "response",
                "ts_epoch": 1.0,
                "duration_s": duration_s,
                "provider_profile": provider_profile,
                "wire_api": wire_api,
                "model": model,
                "usage": {
                    "input_tokens": input_tokens,
                    "input_tokens_details": {"cached_tokens": cached_tokens},
                    "output_tokens": output_tokens,
                    "output_tokens_details": {"reasoning_tokens": reasoning_tokens},
                },
            }
        )
        + "\n",
        encoding="utf-8",
    )
    return run_dir


def _calibration_packet() -> dict[str, object]:
    return {
        "schema": "roboclaws_model_latency_calibration_v1",
        "available": True,
        "sample_count": 20,
        "total_row_count": 20,
        "limitations": ["unit_test_calibration"],
        "coefficient_sets": [
            {
                "agent_engine": "openai-agents-sdk",
                "provider_profile": "kimi-openai-chat",
                "model": "gpt-5.5",
                "wire_api": "responses",
                "coefficients": {
                    "intercept_s": 1.0,
                    "uncached_input_s_per_token": 0.01,
                    "cached_input_s_per_token": 0.001,
                    "output_s_per_token": 0.05,
                    "reasoning_s_per_token": 0.2,
                    "image_s_per_unit": 0.0,
                },
            }
        ],
    }
