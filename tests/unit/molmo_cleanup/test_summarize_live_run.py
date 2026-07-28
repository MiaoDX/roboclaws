from __future__ import annotations

import importlib.util
import json
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
SUMMARY_PATH = REPO_ROOT / "scripts" / "molmo_cleanup" / "summarize_live_run.py"


def _load_summary_module():
    spec = importlib.util.spec_from_file_location("summarize_live_run", SUMMARY_PATH)
    assert spec is not None
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def test_open_ended_summary_uses_claim_headline_instead_of_cleanup_score(
    tmp_path: Path,
    capsys,
) -> None:
    summarize = _load_summary_module()
    run_dir = tmp_path / "seed-7"
    run_dir.mkdir()
    report_path = run_dir / "report.html"
    report_path.write_text("<html></html>\n", encoding="utf-8")

    result = summarize._result_summary(
        {
            "task_surface": "household-world",
            "task_intent": "open-ended",
            "cleanup_status": "failed",
            "completion_status": "failed",
            "sweep_coverage_rate": 0.875,
            "policy": "codex_agent",
            "score": {"restored_count": 0, "total_targets": 5},
            "goal_contract": {
                "schema": "roboclaws_goal_contract_v1",
                "surface": "household-world",
                "intent": "open-ended",
            },
            "agent_completion_claim": {
                "schema": "roboclaws_agent_completion_claim_v1",
                "completion_summary": "Found an apple that satisfies the thirst goal.",
            },
            "artifacts": {"report": str(report_path)},
        },
        run_dir,
    )

    assert result["intent"] == "open-ended"
    assert result["headline"] == "claim=present"

    summarize._print_summary(
        {
            "run_dir": str(run_dir),
            "session": "",
            "tmux_state": "stopped",
            "runner": {
                "phase": "finished",
                "exit_status": 0,
                "elapsed_s": 1.0,
                "started_at": "2026-06-09 18:55:31 CST",
                "finished_at": "2026-06-09 18:58:47 CST",
                "debug_snapshot": {
                    "elapsed_s": 300.0,
                    "run_result_present": False,
                    "report_present": False,
                    "last_trace_event": "observe:response",
                    "last_trace_response": "observe:response",
                    "progress": {
                        "metric_map": 1,
                        "resolve_target_query": 1,
                        "observe": 4,
                        "navigate_to_waypoint": 3,
                        "pick": 0,
                        "place": 0,
                        "done": 0,
                    },
                    "openai_agents_event_counts": {
                        "model_service_attempt": 5,
                        "model_service_success": 4,
                    },
                },
            },
            "trace": {
                "events": 0,
                "requests": 0,
                "responses": 0,
                "last_event": "none",
                "last_response": "none",
                "progress": {
                    "observes": 0,
                    "navigate_to_object": 0,
                    "picks": 0,
                    "navigate_to_receptacle": 0,
                    "opens": 0,
                    "places": 0,
                    "place_inside": 0,
                    "closes": 0,
                    "done": 1,
                },
            },
            "timing": {"runner": {}, "mcp": {}},
            "result": result,
            "artifacts": {},
            "last_codex_message": "",
            "driver_tail": "",
        }
    )

    output = capsys.readouterr().out
    assert "result: open-ended claim=present cleanup_score=failed" in output
    assert "claim: Found an apple that satisfies the thirst goal." in output
    assert "result: failed completion=failed" not in output
    assert "debug snapshot: elapsed=5m00s result=False report=False" in output
    assert "debug progress: metric_map=1 resolve=1 observe=4" in output
    assert "debug model events: model_service_attempt=5 model_service_success=4" in output


def test_agent_sdk_comparison_manifest_rejects_smoke_full_lane(
    tmp_path: Path,
    capsys,
) -> None:
    summarize = _load_summary_module()
    baseline = _write_run(tmp_path / "baseline", elapsed_s=10.0, gap_s=7.0, lane="smoke")
    candidate = _write_run(
        tmp_path / "candidate",
        elapsed_s=8.0,
        gap_s=5.0,
        lane="world-public-labels",
    )
    manifest = tmp_path / "manifest.json"
    manifest.write_text(
        json.dumps(
            {
                "comparisons": [
                    {
                        "key": "bad",
                        "lane": "world-public-labels",
                        "baseline_role": "smoke_reference",
                        "baseline_run_dir": str(baseline),
                        "candidate_run_dir": str(candidate),
                    }
                ]
            }
        ),
        encoding="utf-8",
    )

    status = summarize.main(["--comparison-manifest", str(manifest)])

    assert status == 1
    assert "smoke reference cannot satisfy full-lane baseline" in capsys.readouterr().err


def test_agent_sdk_comparison_manifest_rejects_missing_manifest_source(
    tmp_path: Path,
    capsys,
) -> None:
    summarize = _load_summary_module()

    status = summarize.main(["--comparison-manifest", str(tmp_path / "manifest.json")])

    captured = capsys.readouterr()
    assert status == 1
    assert "live-run summary comparison manifest source is missing" in captured.err
    assert "manifest.json" in captured.err


def test_agent_sdk_comparison_manifest_rejects_malformed_manifest_source(
    tmp_path: Path,
    capsys,
) -> None:
    summarize = _load_summary_module()
    manifest = tmp_path / "manifest.json"
    manifest.write_text("{not-json\n", encoding="utf-8")

    status = summarize.main(["--comparison-manifest", str(manifest)])

    captured = capsys.readouterr()
    assert status == 1
    assert (
        "live-run summary comparison manifest source must contain valid JSON object" in captured.err
    )
    assert "manifest.json" in captured.err


def test_agent_sdk_comparison_manifest_rejects_non_object_manifest_source(
    tmp_path: Path,
    capsys,
) -> None:
    summarize = _load_summary_module()
    manifest = tmp_path / "manifest.json"
    manifest.write_text("[]\n", encoding="utf-8")

    status = summarize.main(["--comparison-manifest", str(manifest)])

    captured = capsys.readouterr()
    assert status == 1
    assert "live-run summary comparison manifest source must contain a JSON object" in captured.err
    assert "manifest.json" in captured.err


def test_agent_sdk_comparison_manifest_prints_explicit_run_pairs(
    tmp_path: Path,
    capsys,
) -> None:
    summarize = _load_summary_module()
    baseline = _write_run(
        tmp_path / "baseline",
        elapsed_s=100.0,
        gap_s=60.0,
        lane="world-public-labels",
        uncached_tokens=1000,
        cache_hit_ratio=0.5,
    )
    candidate = _write_run(
        tmp_path / "candidate",
        elapsed_s=70.0,
        gap_s=30.0,
        lane="world-public-labels",
        uncached_tokens=650,
        cache_hit_ratio=0.7,
    )
    manifest = tmp_path / "manifest.json"
    manifest.write_text(
        json.dumps(
            {
                "comparisons": [
                    {
                        "key": "gpt_world_public",
                        "lane": "world-public-labels",
                        "provider_profile": "codex-router-responses",
                        "baseline_role": "full_lane_baseline",
                        "baseline_run_dir": str(baseline),
                        "candidate_run_dir": str(candidate),
                    }
                ]
            }
        ),
        encoding="utf-8",
    )

    status = summarize.main(["--comparison-manifest", str(manifest)])

    output = capsys.readouterr().out
    assert status == 0
    assert "Report performance comparison manifest" in output
    assert "gpt_world_public | codex-router-responses | world-public-labels" in output
    assert "-30.0s" in output
    assert "-350" in output
    assert "available(max=900)" in output
    assert "finished" in output


def test_single_run_summary_does_not_print_hard_coded_speedup_baseline(
    tmp_path: Path,
    capsys,
) -> None:
    summarize = _load_summary_module()
    run_dir = _write_run(
        tmp_path / "candidate",
        elapsed_s=70.0,
        gap_s=30.0,
        lane="world-public-labels",
        uncached_tokens=650,
        cache_hit_ratio=0.7,
    )

    status = summarize.main([str(run_dir)])

    output = capsys.readouterr().out
    assert status == 0
    assert "18m30s" not in output
    assert "speedup=" not in output
    assert "report performance:" in output
    assert "normalized model time: unavailable" in output


def test_default_run_discovery_ignores_empty_latest_seed_dir(tmp_path: Path, monkeypatch) -> None:
    summarize = _load_summary_module()
    search_root = tmp_path / "codex-report"
    (search_root / "20260619_120000").mkdir(parents=True)
    evidence_run = _write_run(
        search_root / "20260619_120000" / "seed-7",
        elapsed_s=70.0,
        gap_s=30.0,
        lane="world-public-labels",
    )
    empty_latest = search_root / "20260619_130000" / "seed-7"
    empty_latest.mkdir(parents=True)
    monkeypatch.setattr(summarize, "DEFAULT_SEARCH_ROOT", search_root)

    assert summarize._resolve_run_dir(None) == evidence_run


def test_parent_run_discovery_ignores_empty_latest_seed_dir(tmp_path: Path) -> None:
    summarize = _load_summary_module()
    run_root = tmp_path / "runs"
    run_root.mkdir()
    evidence_run = _write_run(
        run_root / "seed-7",
        elapsed_s=70.0,
        gap_s=30.0,
        lane="world-public-labels",
    )
    empty_latest = run_root / "seed-8"
    empty_latest.mkdir(parents=True)

    assert summarize._resolve_run_dir(run_root) == evidence_run


def test_single_run_summary_fails_aloud_on_empty_explicit_run_dir(
    tmp_path: Path,
    capsys,
) -> None:
    summarize = _load_summary_module()
    run_dir = tmp_path / "seed-7"
    run_dir.mkdir()

    status = summarize.main([str(run_dir)])

    captured = capsys.readouterr()
    assert status == 1
    assert f"run path has no live-run evidence: {run_dir}" in captured.err


def test_single_run_summary_fails_aloud_on_malformed_live_timing(
    tmp_path: Path,
    capsys,
) -> None:
    summarize = _load_summary_module()
    run_dir = _write_run(
        tmp_path / "candidate",
        elapsed_s=70.0,
        gap_s=30.0,
        lane="world-public-labels",
    )
    (run_dir / "live_timing.json").write_text("{bad-json}\n", encoding="utf-8")

    status = summarize.main([str(run_dir)])

    captured = capsys.readouterr()
    assert status == 1
    assert "live_timing.json" in captured.err
    assert "must contain valid JSON object" in captured.err


def test_single_run_summary_fails_aloud_on_non_object_run_result(
    tmp_path: Path,
    capsys,
) -> None:
    summarize = _load_summary_module()
    run_dir = _write_run(
        tmp_path / "candidate",
        elapsed_s=70.0,
        gap_s=30.0,
        lane="world-public-labels",
    )
    (run_dir / "run_result.json").write_text('["not", "a", "result"]\n', encoding="utf-8")

    status = summarize.main([str(run_dir)])

    captured = capsys.readouterr()
    assert status == 1
    assert "run_result.json" in captured.err
    assert "must contain a JSON object" in captured.err


def test_single_run_summary_fails_aloud_on_malformed_trace_source(
    tmp_path: Path,
    capsys,
) -> None:
    summarize = _load_summary_module()
    run_dir = _write_run(
        tmp_path / "candidate",
        elapsed_s=70.0,
        gap_s=30.0,
        lane="world-public-labels",
    )
    (run_dir / "trace.jsonl").write_text(
        '{"event":"response","tool":"done"}\n{bad-json}\n',
        encoding="utf-8",
    )

    status = summarize.main([str(run_dir)])

    captured = capsys.readouterr()
    assert status == 1
    assert "trace.jsonl:2" in captured.err
    assert "must contain valid JSON object" in captured.err


def test_single_run_summary_fails_aloud_on_non_object_trace_row(
    tmp_path: Path,
    capsys,
) -> None:
    summarize = _load_summary_module()
    run_dir = _write_run(
        tmp_path / "candidate",
        elapsed_s=70.0,
        gap_s=30.0,
        lane="world-public-labels",
    )
    (run_dir / "trace.jsonl").write_text(
        '{"event":"response","tool":"done"}\n[]\n',
        encoding="utf-8",
    )

    status = summarize.main([str(run_dir)])

    captured = capsys.readouterr()
    assert status == 1
    assert "trace.jsonl:2" in captured.err
    assert "must contain a JSON object" in captured.err


def test_agent_sdk_comparison_manifest_prints_terminal_classification(
    tmp_path: Path,
    capsys,
) -> None:
    summarize = _load_summary_module()
    baseline = _write_run(
        tmp_path / "baseline",
        elapsed_s=100.0,
        gap_s=60.0,
        lane="camera-raw-fpv",
        uncached_tokens=1000,
        cache_hit_ratio=0.5,
    )
    candidate = _write_run(
        tmp_path / "candidate",
        elapsed_s=70.0,
        gap_s=30.0,
        lane="camera-raw-fpv",
        uncached_tokens=650,
        cache_hit_ratio=0.7,
        terminal_reason="raw_fpv_sdk_turn_budget_exhausted",
        run_result=False,
    )
    manifest = tmp_path / "manifest.json"
    manifest.write_text(
        json.dumps(
            {
                "comparisons": [
                    {
                        "key": "raw_fpv",
                        "lane": "camera-raw-fpv",
                        "provider_profile": "codex-router-responses",
                        "baseline_role": "diagnostic",
                        "baseline_run_dir": str(baseline),
                        "candidate_run_dir": str(candidate),
                    }
                ]
            }
        ),
        encoding="utf-8",
    )

    status = summarize.main(["--comparison-manifest", str(manifest)])

    output = capsys.readouterr().out
    assert status == 0
    assert "raw_fpv_sdk_turn_budget_exhausted" in output
    assert "available(max=900)" in output
    assert "raw_fpv_sdk_turn_budget_exhausted" in output


def test_agent_sdk_comparison_manifest_treats_null_context_as_unavailable(
    tmp_path: Path,
    capsys,
) -> None:
    summarize = _load_summary_module()
    baseline = _write_run(
        tmp_path / "baseline",
        elapsed_s=100.0,
        gap_s=60.0,
        lane="world-public-labels",
        null_context=True,
    )
    candidate = _write_run(
        tmp_path / "candidate",
        elapsed_s=70.0,
        gap_s=30.0,
        lane="world-public-labels",
        uncached_tokens=650,
        cache_hit_ratio=0.7,
    )
    manifest = tmp_path / "manifest.json"
    manifest.write_text(
        json.dumps(
            {
                "comparisons": [
                    {
                        "key": "null_context",
                        "lane": "world-public-labels",
                        "baseline_run_dir": str(baseline),
                        "candidate_run_dir": str(candidate),
                    }
                ]
            }
        ),
        encoding="utf-8",
    )

    status = summarize.main(["--comparison-manifest", str(manifest)])

    output = capsys.readouterr().out
    assert status == 0
    assert "unavailable" in output
    assert "null_context" in output


def _write_run(
    run_dir: Path,
    *,
    elapsed_s: float,
    gap_s: float,
    lane: str,
    uncached_tokens: int | None = None,
    cache_hit_ratio: float | None = None,
    terminal_reason: str = "",
    run_result: bool = True,
    null_context: bool = False,
) -> Path:
    run_dir.mkdir()
    context_metrics = {"available": False, "source": "unavailable", "limitations": ["fixture"]}
    if uncached_tokens is not None:
        context_metrics = {
            "available": True,
            "source": "openai_agents_span_usage",
            "limitations": [],
            "total_uncached_input_tokens": uncached_tokens,
            "max_input_tokens": 900,
            "cache_hit_ratio": cache_hit_ratio,
        }
    (run_dir / "live_timing.json").write_text(
        json.dumps(
            {
                "provider_profile": "codex-router-responses",
                "evidence_lane": lane,
                "runner_timing": {"total_elapsed_s": elapsed_s},
                "mcp_trace_timing": {"between_tool_gap_s": gap_s},
                "context_metrics": None if null_context else context_metrics,
                "agent_sdk_budget_terminal": (
                    {"reason": terminal_reason} if terminal_reason else {}
                ),
            }
        ),
        encoding="utf-8",
    )
    (run_dir / "live_status.json").write_text(
        json.dumps(
            {
                "phase": "failed" if terminal_reason else "finished",
                "exit_status": 1 if terminal_reason else 0,
                "reason": terminal_reason,
            }
        ),
        encoding="utf-8",
    )
    if run_result:
        (run_dir / "run_result.json").write_text(
            json.dumps({"task_name": "household-cleanup"}),
            encoding="utf-8",
        )
    (run_dir / "trace.jsonl").write_text(
        json.dumps({"event": "response", "tool": "done", "response": {"ok": True}}) + "\n",
        encoding="utf-8",
    )
    return run_dir
