"""Build and render the current OpenAI Agents SDK live-run summary."""

from __future__ import annotations

import datetime as dt
import shutil
import subprocess
import time
from pathlib import Path
from typing import Any

from roboclaws.agents.live_debug_summary import debug_snapshot_lines
from roboclaws.core.json_sources import read_json_object, read_jsonl_objects
from roboclaws.core.live_performance import extract_report_performance_metrics
from roboclaws.core.runtime_timing import runtime_timing_from_trace

DEFAULT_SEARCH_ROOT = Path("output/household/household-world")
LIVE_RUN_DISCOVERY_FILES = (
    "run_result.json",
    "trace.jsonl",
    "live_status.json",
    "live_timing.json",
)


def _resolve_run_dir(path: Path | None) -> Path | None:
    if path is None:
        candidates = sorted(
            (
                candidate
                for candidate in DEFAULT_SEARCH_ROOT.rglob("seed-*")
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
        "driver.log",
        "openai-agents-events.jsonl",
        "openai-agents-spans.jsonl",
        "openai-agents-trace.json",
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

    if summary["driver_tail"]:
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
    openai_agents = live_timing.get("openai_agents") or {}
    performance = extract_report_performance_metrics(run_dir)
    return {
        "live": live_timing,
        "runner": live_timing.get("runner_timing") or {},
        "mcp": runtime_timing,
        "profile": profile_metadata,
        "skipped_work": skipped_work,
        "openai_agents": openai_agents,
        "performance": performance,
    }


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


def _print_timing(timing: dict[str, Any]) -> None:
    runner = timing.get("runner") or {}
    mcp = timing.get("mcp") or {}
    if not runner and not mcp:
        print("timing: pending")
        return

    print("timing:")
    _print_runner_timing(runner)
    _print_mcp_timing(mcp)
    _print_model_api_timing(timing.get("openai_agents") or {})
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
            f"pre_sdk={_format_duration(runner.get('pre_openai_agents_setup_s'))} "
            f"sdk_exec={_format_duration(runner.get('openai_agents_elapsed_s'))} "
            f"server_wait={_format_duration(runner.get('post_openai_agents_server_wait_s'))} "
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


def _print_model_api_timing(openai_agents: dict[str, Any]) -> None:
    usage = openai_agents.get("usage") or {}
    model_api_time = openai_agents.get("model_api_time_s")
    print(f"  model API time: {_format_duration(model_api_time)}")
    note = openai_agents.get("model_api_time_note")
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


def _indent(text: str) -> str:
    return "\n".join(f"  {line}" for line in text.splitlines())
