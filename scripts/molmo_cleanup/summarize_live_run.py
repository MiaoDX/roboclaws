#!/usr/bin/env python3
"""Summarize a detached Molmo cleanup live-agent run."""

from __future__ import annotations

import argparse
import datetime as dt
import shutil
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

from roboclaws.core.json_sources import read_json_object, read_jsonl_objects
from roboclaws.core.live_performance import (
    compare_report_performance_metrics,
    extract_report_performance_metrics,
)
from roboclaws.core.runtime_timing import runtime_timing_from_trace
from scripts.molmo_cleanup.live_debug_summary import debug_snapshot_lines

DEFAULT_SEARCH_ROOT = Path("output/molmo/codex-report")
LIVE_RUN_DISCOVERY_FILES = (
    "run_result.json",
    "trace.jsonl",
    "live_status.json",
    "live_timing.json",
)


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Probe a detached Molmo cleanup live-agent run.",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    parser.add_argument(
        "path",
        nargs="?",
        default="",
        help="run directory, run root, or run_result.json. Defaults to latest Codex report run.",
    )
    parser.add_argument(
        "--comparison-manifest",
        type=Path,
        help=(
            "JSON manifest of explicit Agent SDK baseline/candidate run pairs. "
            "Smoke references cannot satisfy full-lane baseline requirements."
        ),
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    if args.comparison_manifest:
        return _print_comparison_manifest(args.comparison_manifest)
    run_dir = _resolve_run_dir(Path(args.path) if args.path else None)
    if run_dir is None:
        print(f"error: no run found under {DEFAULT_SEARCH_ROOT}", file=sys.stderr)
        return 1
    if not run_dir.exists():
        print(f"error: run path does not exist: {run_dir}", file=sys.stderr)
        return 1
    if not _is_live_run_dir(run_dir):
        print(f"error: run path has no live-run evidence: {run_dir}", file=sys.stderr)
        return 1

    try:
        summary = _summarize(run_dir)
    except ValueError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    _print_summary(summary)
    return 0


def _resolve_run_dir(path: Path | None) -> Path | None:
    if path is None:
        candidates = sorted(
            (
                candidate
                for candidate in DEFAULT_SEARCH_ROOT.glob("*/seed-*")
                if _is_live_run_dir(candidate)
            ),
            key=lambda item: item.stat().st_mtime,
            reverse=True,
        )
        return candidates[0] if candidates else None

    path = path.expanduser()
    if path.is_file() and path.name == "run_result.json":
        return path.parent
    if path.is_dir() and _is_live_run_dir(path):
        return path

    seed_dirs = sorted(
        (candidate for candidate in path.glob("seed-*") if _is_live_run_dir(candidate)),
        key=lambda item: item.stat().st_mtime,
        reverse=True,
    )
    if seed_dirs:
        return seed_dirs[0]
    return path


def _is_live_run_dir(path: Path) -> bool:
    return path.is_dir() and any((path / name).is_file() for name in LIVE_RUN_DISCOVERY_FILES)


def _summarize(run_dir: Path) -> dict[str, Any]:
    session = _read_text(run_dir / "tmux_session.txt").strip()
    trace_events = _read_jsonl(run_dir / "trace.jsonl")
    runner_status = _read_json(run_dir / "live_status.json")
    live_timing = _read_json(run_dir / "live_timing.json")
    run_result = _read_json(run_dir / "run_result.json")

    return {
        "run_dir": str(run_dir),
        "session": session,
        "tmux_state": _tmux_state(session),
        "runner": _runner_summary(runner_status),
        "artifacts": _artifact_summary(run_dir),
        "trace": _trace_summary(trace_events),
        "timing": _timing_summary(
            run_dir=run_dir,
            live_timing=live_timing,
            run_result=run_result,
            trace_events=trace_events,
        ),
        "result": _result_summary(run_result, run_dir),
        "last_codex_message": _tail_text(run_dir / "codex-last-message.md", max_chars=800),
        "driver_tail": _tail_text(run_dir / "driver.log", max_chars=1200),
    }


def _runner_summary(status: dict[str, Any]) -> dict[str, Any]:
    started = _float_or_none(status.get("started_at_epoch"))
    finished = _float_or_none(status.get("finished_at_epoch"))
    now = time.time()
    elapsed = None
    if started is not None:
        elapsed = round((finished or now) - started, 1)
    return {
        "phase": str(status.get("phase") or "unknown"),
        "exit_status": status.get("exit_status"),
        "started_at": _format_epoch(started),
        "finished_at": _format_epoch(finished),
        "elapsed_s": elapsed,
        "debug_snapshot": status.get("debug_snapshot")
        if isinstance(status.get("debug_snapshot"), dict)
        else {},
    }


def _artifact_summary(run_dir: Path) -> dict[str, str]:
    names = (
        "run_live_codex.sh",
        "driver.log",
        "codex-events.jsonl",
        "openai-agents-events.jsonl",
        "openai-agents-trace.json",
        "codex-last-message.md",
        "codex.stderr.log",
        "live_timing.json",
        "model_call_metrics.jsonl",
        "trace.jsonl",
        "run_result.json",
        "report.html",
    )
    return {name: _artifact_state(run_dir / name) for name in names}


def _trace_summary(events: list[dict[str, Any]]) -> dict[str, Any]:
    responses = [event for event in events if event.get("event") == "response"]
    requests = [event for event in events if event.get("event") == "request"]
    tool_counts: dict[str, int] = {}
    for event in responses:
        tool = str(event.get("tool") or "")
        if tool and not tool.startswith("<"):
            tool_counts[tool] = tool_counts.get(tool, 0) + 1

    last = events[-1] if events else {}
    last_response = responses[-1] if responses else {}
    return {
        "events": len(events),
        "requests": len(requests),
        "responses": len(responses),
        "last_event": _tool_event_label(last),
        "last_response": _tool_event_label(last_response),
        "progress": {
            "observes": tool_counts.get("observe", 0),
            "navigate_to_object": tool_counts.get("navigate_to_object", 0),
            "picks": tool_counts.get("pick", 0),
            "navigate_to_receptacle": tool_counts.get("navigate_to_receptacle", 0),
            "opens": tool_counts.get("open_receptacle", 0),
            "places": tool_counts.get("place", 0),
            "place_inside": tool_counts.get("place_inside", 0),
            "closes": tool_counts.get("close_receptacle", 0),
            "done": tool_counts.get("done", 0),
        },
    }


def _result_summary(run_result: dict[str, Any], run_dir: Path) -> dict[str, Any]:
    if not run_result:
        return {"state": "pending"}
    score = run_result.get("score") if isinstance(run_result.get("score"), dict) else {}
    goal_contract = (
        run_result.get("goal_contract") if isinstance(run_result.get("goal_contract"), dict) else {}
    )
    completion_claim = (
        run_result.get("agent_completion_claim")
        if isinstance(run_result.get("agent_completion_claim"), dict)
        else {}
    )
    artifacts = run_result.get("artifacts") if isinstance(run_result.get("artifacts"), dict) else {}
    report = artifacts.get("report") or run_dir / "report.html"
    intent = str(run_result.get("task_intent") or goal_contract.get("intent") or "").strip()
    surface = str(run_result.get("task_surface") or goal_contract.get("surface") or "").strip()
    return {
        "state": "present",
        "surface": surface or "unknown",
        "intent": intent or "unknown",
        "headline": _result_headline(intent=intent, completion_claim=completion_claim),
        "claim_summary": str(completion_claim.get("completion_summary") or "").strip(),
        "cleanup_status": run_result.get("cleanup_status"),
        "completion_status": run_result.get("completion_status"),
        "restored": _score_fraction(score, "restored_count", "total_targets"),
        "sweep": run_result.get("sweep_coverage_rate"),
        "primitive_provenance": run_result.get("primitive_provenance"),
        "policy": run_result.get("policy"),
        "report": str(report),
    }


def _print_summary(summary: dict[str, Any]) -> None:
    print("Molmo cleanup live run")
    print(f"run_dir: {summary['run_dir']}")
    session = summary["session"] or "(none)"
    print(f"tmux: {session} [{summary['tmux_state']}]")

    runner = summary["runner"]
    elapsed = runner["elapsed_s"]
    elapsed_text = _format_duration(elapsed) if elapsed is not None else "unknown"
    print(
        "runner: "
        f"{runner['phase']} exit={runner['exit_status']} "
        f"elapsed={elapsed_text} started={runner['started_at']}"
    )
    if runner["finished_at"] != "unknown":
        print(f"finished: {runner['finished_at']}")
    _print_debug_snapshot(runner.get("debug_snapshot") or {})

    trace = summary["trace"]
    print(
        "trace: "
        f"{trace['events']} events, {trace['requests']} requests, "
        f"{trace['responses']} responses"
    )
    print(f"last: {trace['last_event']}")
    print(f"last response: {trace['last_response']}")
    progress = trace["progress"]
    print(
        "progress: "
        f"observe={progress['observes']} nav_obj={progress['navigate_to_object']} "
        f"pick={progress['picks']} nav_rec={progress['navigate_to_receptacle']} "
        f"open={progress['opens']} place={progress['places']} "
        f"inside={progress['place_inside']} close={progress['closes']} "
        f"done={progress['done']}"
    )
    _print_timing(summary["timing"])

    result = summary["result"]
    if result["state"] == "present":
        if result["intent"] == "cleanup":
            print(
                "result: "
                f"{result['cleanup_status']} completion={result['completion_status']} "
                f"restored={result['restored']} sweep={result['sweep']} "
                f"policy={result['policy']}"
            )
        else:
            print(
                "result: "
                f"{result['intent']} {result['headline']} "
                f"cleanup_score={result['cleanup_status']} "
                f"completion={result['completion_status']} sweep={result['sweep']} "
                f"policy={result['policy']}"
            )
            if result["claim_summary"]:
                print(f"claim: {result['claim_summary']}")
        print(f"report: {result['report']}")
    else:
        print("result: pending")

    print("artifacts:")
    for name, state in summary["artifacts"].items():
        print(f"  {name}: {state}")

    if summary["last_codex_message"]:
        print("codex last message:")
        print(_indent(summary["last_codex_message"]))
    elif summary["driver_tail"]:
        print("driver log tail:")
        print(_indent(summary["driver_tail"]))


def _timing_summary(
    *,
    run_dir: Path,
    live_timing: dict[str, Any],
    run_result: dict[str, Any],
    trace_events: list[dict[str, Any]],
) -> dict[str, Any]:
    runtime_timing = run_result.get("runtime_timing")
    if not isinstance(runtime_timing, dict):
        runtime_timing = runtime_timing_from_trace(trace_events)
    profile_metadata = (
        run_result.get("evidence_lane_metadata") or run_result.get("cleanup_profile_metadata") or {}
    )
    if not profile_metadata and live_timing.get("profile"):
        profile_metadata = {"profile": live_timing.get("profile")}
    skipped_work = []
    if profile_metadata.get("record_robot_views") is False:
        skipped_work.append("per-tool robot-view timeline capture")
    codex_events = live_timing.get("codex_events") or {}
    openai_agents = live_timing.get("openai_agents") or {}
    performance = extract_report_performance_metrics(run_dir)
    return {
        "live": live_timing,
        "runner": live_timing.get("runner_timing") or {},
        "mcp": runtime_timing,
        "profile": profile_metadata,
        "skipped_work": skipped_work,
        "codex_events": codex_events,
        "openai_agents": openai_agents,
        "performance": performance,
    }


def _print_comparison_manifest(path: Path) -> int:
    try:
        manifest = read_json_object(path, label="live-run summary comparison manifest")
    except (FileNotFoundError, ValueError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    entries = manifest.get("comparisons")
    if not isinstance(entries, list) or not entries:
        print(
            "error: comparison manifest must contain a non-empty comparisons list",
            file=sys.stderr,
        )
        return 1

    rows: list[dict[str, Any]] = []
    for entry in entries:
        if not isinstance(entry, dict):
            print("error: comparison manifest entries must be objects", file=sys.stderr)
            return 1
        baseline_role = str(entry.get("baseline_role") or "")
        lane = str(entry.get("lane") or "")
        if baseline_role == "smoke_reference" and lane not in {"smoke", "diagnostic"}:
            print(
                "error: smoke reference cannot satisfy full-lane baseline "
                f"for comparison {entry.get('key') or '<unknown>'}",
                file=sys.stderr,
            )
            return 1
        baseline_dir = Path(str(entry.get("baseline_run_dir") or ""))
        candidate_dir = Path(str(entry.get("candidate_run_dir") or ""))
        if not baseline_dir or not candidate_dir:
            print(
                f"error: comparison {entry.get('key') or '<unknown>'} needs explicit run dirs",
                file=sys.stderr,
            )
            return 1
        if not baseline_dir.exists() or not candidate_dir.exists():
            print(
                f"error: comparison {entry.get('key') or '<unknown>'} references missing run dir",
                file=sys.stderr,
            )
            return 1
        rows.append(_comparison_row(entry, baseline_dir=baseline_dir, candidate_dir=candidate_dir))

    print("Report performance comparison manifest")
    header = (
        "key | provider | lane | baseline | candidate | elapsed_delta_s | "
        "gap_delta_s | uncached_delta | model_work | context | terminal | checker | status"
    )
    print(header)
    print("-" * len(header))
    for row in rows:
        print(
            f"{row['key']} | {row['provider_profile']} | {row['lane']} | "
            f"{_format_duration(row['baseline_elapsed_s'])} | "
            f"{_format_duration(row['candidate_elapsed_s'])} | "
            f"{_signed_duration(row['elapsed_delta_s'])} | "
            f"{_signed_duration(row['between_tool_gap_delta_s'])} | "
            f"{row['uncached_delta']} | {row['candidate_cache_hit_ratio']} | "
            f"{row['candidate_context_state']} | {row['candidate_terminal']} | "
            f"{row['candidate_checker']} | {row['status']}"
        )
    return 0


def _comparison_row(
    entry: dict[str, Any],
    *,
    baseline_dir: Path,
    candidate_dir: Path,
) -> dict[str, Any]:
    baseline_metrics = extract_report_performance_metrics(baseline_dir)
    candidate_metrics = extract_report_performance_metrics(candidate_dir)
    comparison = compare_report_performance_metrics(
        baseline_metrics,
        candidate_metrics,
        key=str(entry.get("key") or ""),
        quality_waiver=str(entry.get("quality_waiver") or ""),
        diagnostic=str(entry.get("baseline_role") or "") == "diagnostic",
    )
    baseline = _comparison_run_summary_from_metrics(baseline_metrics)
    candidate = _comparison_run_summary_from_metrics(candidate_metrics)
    return {
        "key": str(entry.get("key") or ""),
        "provider_profile": str(entry.get("provider_profile") or candidate["provider_profile"]),
        "lane": str(entry.get("lane") or candidate["lane"]),
        "baseline_elapsed_s": baseline["elapsed_s"],
        "candidate_elapsed_s": candidate["elapsed_s"],
        "elapsed_delta_s": _delta(candidate["elapsed_s"], baseline["elapsed_s"]),
        "between_tool_gap_delta_s": _delta(
            candidate["between_tool_gap_s"],
            baseline["between_tool_gap_s"],
        ),
        "uncached_delta": _token_delta(
            candidate["total_uncached_input_tokens"],
            baseline["total_uncached_input_tokens"],
        ),
        "candidate_cache_hit_ratio": candidate["cache_hit_ratio"],
        "candidate_context_state": candidate["context_state"],
        "candidate_terminal": candidate["terminal"],
        "candidate_checker": candidate["checker"],
        "status": comparison["status"],
    }


def _comparison_run_summary_from_metrics(metrics: dict[str, Any]) -> dict[str, Any]:
    identity = metrics.get("run_identity") if isinstance(metrics.get("run_identity"), dict) else {}
    quality = metrics.get("quality") if isinstance(metrics.get("quality"), dict) else {}
    timing = metrics.get("timing") if isinstance(metrics.get("timing"), dict) else {}
    model_work = metrics.get("model_work") if isinstance(metrics.get("model_work"), dict) else {}
    return {
        "elapsed_s": _float_or_none(timing.get("observed_wall_s")),
        "between_tool_gap_s": _float_or_none(timing.get("mcp_between_tool_gap_s")),
        "total_uncached_input_tokens": model_work.get("total_uncached_input_tokens"),
        "cache_hit_ratio": _cache_hit_ratio(model_work),
        "provider_profile": identity.get("provider_profile") or "unknown",
        "lane": identity.get("evidence_lane") or "unknown",
        "context_state": _context_state(model_work),
        "terminal": quality.get("terminal") or "unknown",
        "checker": quality.get("checker_state") or "unknown",
    }


def _context_state(context: dict[str, Any]) -> str:
    if context.get("available"):
        max_input = context.get("max_input_tokens")
        return f"available(max={max_input})" if max_input is not None else "available"
    limitations = context.get("limitations")
    if isinstance(limitations, list) and limitations:
        return "unavailable:" + ",".join(str(item) for item in limitations[:3])
    return "unavailable"


def _cache_hit_ratio(model_work: dict[str, Any]) -> float | None:
    total_input = _float_or_none(model_work.get("total_input_tokens"))
    total_cached = _float_or_none(model_work.get("total_cached_input_tokens"))
    if total_input is None or total_cached is None or total_input <= 0:
        return None
    return round(total_cached / total_input, 4)


def _terminal_state(live_timing: dict[str, Any], status: dict[str, Any]) -> str:
    terminal = live_timing.get("agent_sdk_budget_terminal")
    if isinstance(terminal, dict) and terminal.get("reason"):
        return str(terminal["reason"])
    reason = status.get("reason")
    if reason:
        return str(reason)
    phase = status.get("phase")
    return str(phase or "unknown")


def _checker_state(status: dict[str, Any], run_result: dict[str, Any]) -> str:
    if run_result:
        return "result-present"
    reason = status.get("reason") or status.get("phase") or "missing"
    return str(reason)


def _delta(candidate: float | None, baseline: float | None) -> float | None:
    if candidate is None or baseline is None:
        return None
    return round(candidate - baseline, 3)


def _token_delta(candidate: Any, baseline: Any) -> str:
    candidate_int = int(candidate) if isinstance(candidate, int) else None
    baseline_int = int(baseline) if isinstance(baseline, int) else None
    if candidate_int is None or baseline_int is None:
        return "unavailable"
    delta = candidate_int - baseline_int
    return f"{delta:+d}"


def _print_timing(timing: dict[str, Any]) -> None:
    runner = timing.get("runner") or {}
    mcp = timing.get("mcp") or {}
    if not runner and not mcp:
        print("timing: pending")
        return

    print("timing:")
    _print_runner_timing(runner)
    _print_mcp_timing(mcp)
    _print_model_api_timing(timing.get("codex_events") or {})
    _print_profile_timing(timing.get("profile") or {})
    _print_report_performance_timing(timing.get("performance") or {})
    _print_skipped_work(timing.get("skipped_work") or [])


def _print_debug_snapshot(snapshot: dict[str, Any]) -> None:
    for line in debug_snapshot_lines(snapshot):
        print(line)


def _print_runner_timing(runner: dict[str, Any]) -> None:
    if runner:
        print(
            "  runner wall: "
            f"total={_format_duration(runner.get('total_elapsed_s'))} "
            f"pre_codex={_format_duration(runner.get('pre_codex_setup_s'))} "
            f"codex_exec={_format_duration(runner.get('codex_exec_elapsed_s'))} "
            f"server_wait={_format_duration(runner.get('post_codex_server_wait_s'))} "
            f"checker={_format_duration(runner.get('checker_elapsed_s'))} "
            f"unaccounted={_format_duration(runner.get('unaccounted_elapsed_s'))}"
        )
        if runner.get("server_startup_s") is not None:
            print(f"  server startup: {_format_duration(runner.get('server_startup_s'))}")


def _print_mcp_timing(mcp: dict[str, Any]) -> None:
    if mcp:
        print(
            "  MCP trace: "
            f"elapsed={_format_duration(mcp.get('total_elapsed_s'))} "
            f"tool/backend={_format_duration(mcp.get('tool_handler_s'))} "
            f"robot_view={_format_duration(mcp.get('robot_view_capture_s'))} "
            f"between_tool/model_gap={_format_duration(mcp.get('between_tool_gap_s'))} "
            f"other={_format_duration(mcp.get('other_mcp_overhead_s'))} "
            f"calls={mcp.get('tool_call_count', 0)}"
        )
        for item in (mcp.get("tool_breakdown") or [])[:5]:
            print(
                "  slow tool: "
                f"{item.get('tool')} calls={item.get('calls')} "
                f"handler={_format_duration(item.get('handler_s'))} "
                f"avg={_format_duration(item.get('avg_handler_s'))}"
            )
        for item in (mcp.get("longest_between_tool_gaps") or [])[:5]:
            print(
                "  slow gap: "
                f"{item.get('after_tool')} -> {item.get('before_tool')} "
                f"{_format_duration(item.get('gap_s'))}"
            )


def _print_model_api_timing(codex_events: dict[str, Any]) -> None:
    usage = codex_events.get("usage") or {}
    model_api_time = codex_events.get("model_api_time_s")
    print(f"  model API time: {_format_duration(model_api_time)}")
    note = codex_events.get("model_api_time_note")
    if note:
        print(f"  model API note: {note}")
    if usage:
        print(
            "  model usage: "
            f"input={usage.get('input_tokens', 'n/a')} "
            f"cached={usage.get('cached_input_tokens', 'n/a')} "
            f"output={usage.get('output_tokens', 'n/a')} "
            f"reasoning={usage.get('reasoning_output_tokens', 'n/a')}"
        )


def _print_profile_timing(profile: dict[str, Any]) -> None:
    if profile:
        print(
            "  profile: "
            f"{profile.get('profile', 'unknown')} "
            f"record_robot_views={profile.get('record_robot_views', 'unknown')}"
        )


def _print_report_performance_timing(performance: dict[str, Any]) -> None:
    perf_model_work = performance.get("model_work") if isinstance(performance, dict) else {}
    perf_timing = performance.get("timing") if isinstance(performance, dict) else {}
    if perf_model_work:
        print(
            "  report performance: "
            f"schema={performance.get('schema', 'unknown')} "
            f"model_work={'available' if perf_model_work.get('available') else 'unavailable'} "
            f"uncached={perf_model_work.get('total_uncached_input_tokens', 'n/a')} "
            f"output={perf_model_work.get('total_output_tokens', 'n/a')}"
        )
    if perf_timing:
        estimate = perf_timing.get("estimated_model_work_s") or {}
        print(
            "  normalized model time: "
            f"{'available' if estimate.get('available') else 'unavailable'} "
            f"observed_model_api={_format_duration(perf_timing.get('observed_model_api_s'))} "
            f"residual={_format_duration(perf_timing.get('model_latency_residual_s'))} "
            f"model_or_sdk_residual={_format_duration(perf_timing.get('model_or_sdk_residual_s'))}"
        )


def _print_skipped_work(skipped: list[Any]) -> None:
    if skipped:
        print(f"  skipped/sampled: {', '.join(str(item) for item in skipped)}")


def _tmux_state(session: str) -> str:
    if not session:
        return "unknown"
    if shutil.which("tmux") is None:
        return "tmux-not-found"
    result = subprocess.run(
        ["tmux", "has-session", "-t", session],
        check=False,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    return "running" if result.returncode == 0 else "stopped"


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.is_file():
        return []
    return read_jsonl_objects(path, label="live-run summary trace")


def _read_json(path: Path) -> dict[str, Any]:
    if not path.is_file():
        return {}
    return read_json_object(path, label="live-run summary")


def _read_text(path: Path) -> str:
    if not path.is_file():
        return ""
    return path.read_text(encoding="utf-8", errors="replace")


def _tail_text(path: Path, *, max_chars: int) -> str:
    text = _read_text(path)
    if len(text) <= max_chars:
        return text.strip()
    return text[-max_chars:].strip()


def _artifact_state(path: Path) -> str:
    if not path.exists():
        return "missing"
    if path.is_dir():
        return "dir"
    return f"{path.stat().st_size} bytes"


def _tool_event_label(event: dict[str, Any]) -> str:
    if not event:
        return "none"
    tool = event.get("tool", "?")
    kind = event.get("event", "?")
    elapsed = event.get("wallclock_elapsed")
    suffix = ""
    if isinstance(elapsed, int | float):
        suffix = f" at +{_format_duration(float(elapsed))}"
    return f"{tool}:{kind}{suffix}"


def _result_headline(*, intent: str, completion_claim: dict[str, Any]) -> str:
    if intent == "cleanup" or not intent:
        return "cleanup-score"
    if (
        completion_claim.get("schema") == "roboclaws_agent_completion_claim_v1"
        and str(completion_claim.get("completion_summary") or "").strip()
    ):
        return "claim=present"
    return "claim=missing"


def _score_fraction(score: dict[str, Any], numerator: str, denominator: str) -> str:
    top = score.get(numerator)
    bottom = score.get(denominator)
    if top is None or bottom is None:
        return "unknown"
    return f"{top}/{bottom}"


def _float_or_none(value: Any) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _format_epoch(value: float | None) -> str:
    if value is None:
        return "unknown"
    stamp = dt.datetime.fromtimestamp(value).astimezone()
    return stamp.strftime("%Y-%m-%d %H:%M:%S %Z")


def _format_duration(value: Any) -> str:
    parsed = _float_or_none(value)
    if parsed is None:
        return "unknown"
    if parsed < 60:
        return f"{parsed:.1f}s"
    minutes, seconds = divmod(int(parsed), 60)
    hours, minutes = divmod(minutes, 60)
    if hours:
        return f"{hours}h{minutes:02d}m{seconds:02d}s"
    return f"{minutes}m{seconds:02d}s"


def _signed_duration(value: Any) -> str:
    parsed = _float_or_none(value)
    if parsed is None:
        return "unknown"
    sign = "+" if parsed >= 0 else "-"
    return f"{sign}{_format_duration(abs(parsed))}"


def _indent(text: str) -> str:
    return "\n".join(f"  {line}" for line in text.splitlines())


if __name__ == "__main__":
    raise SystemExit(main())
