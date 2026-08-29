"""Terminal diagnostic artifacts for interrupted household live runs."""

from __future__ import annotations

import html
import json
import os
import tempfile
from pathlib import Path
from typing import Any

from roboclaws.core.json_sources import read_jsonl_objects


def finalize_terminal_incomplete_bundle(run_dir: Path, *, reason: str) -> dict[str, Any]:
    """Persist an honest, privacy-preserving bundle without inferring task success."""

    run_dir = Path(run_dir)
    run_dir.mkdir(parents=True, exist_ok=True)
    trace_path = run_dir / "trace.jsonl"
    trace_path.touch(exist_ok=True)
    events = _trace_events(trace_path)
    agent_view = _read_json(run_dir / "agent_view.json")
    runtime_map = _read_json(run_dir / "runtime_metric_map.json")
    last_event = events[-1] if events else {}
    last_tool = str(last_event.get("tool") or "")
    tool_counts: dict[str, int] = {}
    for event in events:
        tool = str(event.get("tool") or "")
        if tool and event.get("event") == "response":
            tool_counts[tool] = tool_counts.get(tool, 0) + 1
    captured_frames = len(list(run_dir.glob("robot_views/**/*.png")))
    diagnostic = {
        "reason": reason,
        "last_tool": last_tool,
        "progress_counters": {
            "trace_events": len(events),
            "tool_responses": sum(tool_counts.values()),
            "tool_response_counts": tool_counts,
            "captured_frames": captured_frames,
        },
    }
    run_result = {
        "schema": "household_run_result_v1",
        "status": "terminal_incomplete",
        "final_status": "terminal_incomplete",
        "intent_status": "terminal_incomplete",
        "goal_status": "terminal_incomplete",
        "capability_status": "terminal_incomplete",
        "artifact_status": "ready",
        "terminal_reason": reason,
        "diagnostics": diagnostic,
        "artifacts": {
            "run_result": "run_result.json",
            "report": "report.html",
            "trace": "trace.jsonl",
            "agent_view": "agent_view.json",
            "runtime_metric_map": "runtime_metric_map.json",
            "private_evaluation": "private_evaluation.json",
        },
    }
    # These files normally exist after the server's first public artifact refresh.
    # Empty objects explicitly record unavailability without fabricating map evidence.
    _write_json_if_missing(run_dir / "agent_view.json", agent_view)
    _write_json_if_missing(run_dir / "runtime_metric_map.json", runtime_map)
    _write_json_if_missing(
        run_dir / "private_evaluation.json",
        {
            "schema": "household_terminal_diagnostic_private_v1",
            "status": "terminal_incomplete",
            "reason": reason,
            "capability_success": False,
        },
    )
    _atomic_write_text(run_dir / "report.html", _diagnostic_report(diagnostic))
    _atomic_write_json(run_dir / "run_result.json", run_result)
    return run_result


def is_timeout_reason(reason: str, provider_reason: str = "") -> bool:
    text = f"{reason} {provider_reason}".lower()
    return any(marker in text for marker in ("timeout", "timed_out", "timed out", "deadline"))


def _trace_events(path: Path) -> list[dict[str, Any]]:
    try:
        return read_jsonl_objects(path, label="household terminal diagnostic trace")
    except (OSError, ValueError):
        return []


def _read_json(path: Path) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return payload if isinstance(payload, dict) else {}


def _write_json_if_missing(path: Path, payload: dict[str, Any]) -> None:
    if not path.is_file():
        _atomic_write_json(path, payload)


def _atomic_write_json(path: Path, payload: dict[str, Any]) -> None:
    _atomic_write_text(path, json.dumps(payload, indent=2, sort_keys=True) + "\n")


def _atomic_write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary = tempfile.mkstemp(dir=path.parent, prefix=f".{path.name}.")
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            handle.write(text)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    except BaseException:
        try:
            os.unlink(temporary)
        except OSError:
            pass
        raise


def _diagnostic_report(diagnostic: dict[str, Any]) -> str:
    counters = diagnostic["progress_counters"]
    reason = html.escape(str(diagnostic["reason"]))
    last_tool = html.escape(str(diagnostic["last_tool"] or "none"))
    return f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8"><title>Household run incomplete</title></head>
<body><main><h1>Household run incomplete</h1>
<p>This run ended before authoritative task completion. Its evidence was preserved.</p>
<dl><dt>Status</dt><dd>terminal_incomplete</dd><dt>Reason</dt><dd>{reason}</dd>
<dt>Last tool</dt><dd>{last_tool}</dd><dt>Tool responses</dt><dd>{counters["tool_responses"]}</dd>
<dt>Captured frames</dt><dd>{counters["captured_frames"]}</dd></dl>
</main></body></html>
"""
