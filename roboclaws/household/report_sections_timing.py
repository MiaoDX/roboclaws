from __future__ import annotations

import html
from pathlib import Path
from typing import Any

from roboclaws.core.json_sources import read_json_object
from roboclaws.core.runtime_timing import (
    robot_view_capture_overlap_seconds,
    runtime_timing_from_trace,
)
from roboclaws.household.semantic_timeline import PLACE_CLEANUP_PHASES


def runtime_timing_section(
    run_dir: Path,
    run_result: dict[str, Any],
    trace_events: list[dict[str, Any]],
    robot_view_steps: list[dict[str, Any]],
) -> str:
    timing = run_result.get("runtime_timing")
    if not isinstance(timing, dict):
        timing = runtime_timing_from_trace(trace_events, robot_view_steps)
    if not timing:
        return ""
    total_elapsed = timing.get("total_elapsed_s")
    if not isinstance(total_elapsed, (int, float)) or total_elapsed <= 0:
        return ""

    live_timing = _load_live_timing(run_dir)
    runner_timing = live_timing.get("runner_timing") if isinstance(live_timing, dict) else {}
    runner_timeline = (
        _runner_timing_timeline(runner_timing)
        if isinstance(runner_timing, dict) and runner_timing
        else ""
    )
    mcp_timeline = _mcp_timing_timeline(timing)
    metrics = (
        '<div class="metric-grid">'
        f"{_metric('MCP elapsed', _seconds_text(total_elapsed))}"
        f"{_metric('Tool/backend handling', _seconds_text(timing.get('tool_handler_s', 0)))}"
        f"{_metric('Robot-view capture', _seconds_text(timing.get('robot_view_capture_s', 0)))}"
        f"{_metric('Between-tool gap', _seconds_text(timing.get('between_tool_gap_s', 0)))}"
        f"{_metric('Other MCP overhead', _seconds_text(timing.get('other_mcp_overhead_s', 0)))}"
        f"{_metric('Tool calls', timing.get('tool_call_count', 0))}"
        "</div>"
    )
    tool_rows = []
    for item in timing.get("tool_breakdown") or []:
        tool_rows.append(
            "<tr>"
            f"<td>{html.escape(str(item.get('tool', '')))}</td>"
            f"<td>{html.escape(str(item.get('calls', 0)))}</td>"
            f"<td>{html.escape(_seconds_text(item.get('handler_s', 0)))}</td>"
            f"<td>{html.escape(_seconds_text(item.get('avg_handler_s', 0)))}</td>"
            "</tr>"
        )
    gap_rows = []
    for item in timing.get("longest_between_tool_gaps") or []:
        gap_rows.append(
            "<tr>"
            f"<td>{html.escape(str(item.get('after_tool', '')))}</td>"
            f"<td>{html.escape(str(item.get('before_tool', '')))}</td>"
            f"<td>{html.escape(_seconds_text(item.get('gap_s', 0)))}</td>"
            "</tr>"
        )
    tool_table = (
        '<div class="table-wrap"><table><thead><tr><th>Tool</th><th>Calls</th>'
        "<th>Handler time</th><th>Avg handler</th></tr></thead><tbody>"
        + "".join(tool_rows)
        + "</tbody></table></div>"
    )
    gap_table = (
        '<div class="table-wrap"><table><thead><tr><th>After response</th>'
        "<th>Before request</th><th>Gap</th></tr></thead><tbody>"
        + "".join(gap_rows)
        + "</tbody></table></div>"
        if gap_rows
        else ""
    )
    object_cycles = _object_cycle_timing_section(timing, trace_events)
    return (
        '<section class="panel runtime-timing">'
        "<h2>Runtime Timing</h2>"
        '<p class="note">Wall-clock timing is split into scan-friendly lanes. '
        "Runner timing shows the live shell orchestration. MCP timing is the cleanup "
        "server trace inside the agent run; between-tool gaps include model reasoning, "
        "CLI orchestration, transport, and post-response overhead.</p>"
        f"{runner_timeline}{mcp_timeline}{metrics}{object_cycles}"
        '<details class="timing-details"><summary>Tool and gap tables</summary>'
        f"{tool_table}{gap_table}</details></section>"
    )


def _object_cycle_timing_section(
    timing: dict[str, Any],
    trace_events: list[dict[str, Any]],
) -> str:
    cycles = _object_timing_cycles(trace_events)
    if not cycles:
        return ""
    cycle_total = sum(float(item["total_s"]) for item in cycles)
    total_elapsed = _float_or_none(timing.get("total_elapsed_s")) or 0.0
    search_overhead = max(0.0, total_elapsed - cycle_total)
    metrics = (
        '<div class="metric-grid">'
        f"{_metric('Cleaned-object cycles', len(cycles))}"
        f"{_metric('Cycle time', _seconds_text(cycle_total))}"
        f"{_metric('Sweep/search overhead', _seconds_text(search_overhead))}"
        f"{_metric('Measured only', 'no projections')}"
        "</div>"
    )
    cards = []
    for index, cycle in enumerate(cycles, start=1):
        timing_lane = _timing_lane(
            "",
            cycle["total_s"],
            _object_cycle_segments(cycle),
            render_empty=True,
        )
        cards.append(
            '<article class="object-cycle">'
            f"<h3>{index}. {html.escape(str(cycle['object_id']))}</h3>"
            f"{timing_lane}"
            f"<p>{html.escape(_object_cycle_phase_text(cycle))}</p>"
            "</article>"
        )
    return (
        '<div class="object-cycle-timing">'
        "<h3>Per-object cleanup cycles</h3>"
        '<p class="note">Each cycle starts at the first successful object-directed '
        "action and ends at the post-place observe when present. The orange bucket "
        "is measured response-to-next-request time: agent thinking, CLI orchestration, "
        "transport, and other agent-side delay. It is not projected or estimated "
        "hardware time.</p>"
        f"{metrics}"
        '<div class="object-cycle-grid">' + "".join(cards) + "</div></div>"
    )


def _object_cycle_segments(cycle: dict[str, Any]) -> list[tuple[str, Any, str, str]]:
    return [
        (
            "Agent thinking / orchestration",
            cycle.get("agent_gap_s"),
            "response-to-next-request gap",
            "#b7683f",
        ),
        ("Robot views", cycle.get("robot_view_capture_s"), "measured report capture", "#4f6691"),
        ("Tool handlers", cycle.get("tool_handler_s"), "cleanup server work", "#2f766f"),
        ("Other measured", cycle.get("other_s"), "remaining wall time", "#7a8491"),
    ]


def _object_cycle_phase_text(cycle: dict[str, Any]) -> str:
    tools = " -> ".join(str(item) for item in cycle.get("tools") or [])
    return (
        f"{_seconds_text(cycle.get('total_s'))}; "
        f"window {_seconds_text(cycle.get('start_s'))} to {_seconds_text(cycle.get('end_s'))}; "
        f"{tools}"
    )


def _load_live_timing(run_dir: Path) -> dict[str, Any]:
    path = run_dir / "live_timing.json"
    if not path.exists():
        return {}
    return read_json_object(path, label="report live timing")


def _runner_timing_timeline(runner_timing: dict[str, Any]) -> str:
    total = runner_timing.get("total_elapsed_s")
    agent_label = "Agent run"
    agent_elapsed = runner_timing.get("codex_exec_elapsed_s")
    setup_elapsed = runner_timing.get("pre_codex_setup_s")
    server_wait_elapsed = runner_timing.get("post_codex_server_wait_s")
    if agent_elapsed is None and runner_timing.get("openai_agents_elapsed_s") is not None:
        agent_label = "OpenAI Agents SDK run"
        agent_elapsed = runner_timing.get("openai_agents_elapsed_s")
        setup_elapsed = runner_timing.get("pre_agent_setup_s")
        server_wait_elapsed = runner_timing.get("post_agent_server_wait_s")
    segments = [
        ("Setup", setup_elapsed, "launcher and server prep", "#536d7a"),
        (agent_label, agent_elapsed, "agent execution", "#2f766f"),
        (
            "Server wait",
            server_wait_elapsed,
            "cleanup server finalization",
            "#8a6f39",
        ),
        ("Checker", runner_timing.get("checker_elapsed_s"), "artifact checker", "#4f6691"),
        ("Final", runner_timing.get("final_overhead_s"), "report wrap-up", "#6f7785"),
    ]
    return _timing_lane("Run wall clock", total, segments)


def _mcp_timing_timeline(timing: dict[str, Any]) -> str:
    segments = [
        (
            "Between tools",
            timing.get("between_tool_gap_s"),
            "agent reasoning and orchestration",
            "#b7683f",
        ),
        ("Robot views", timing.get("robot_view_capture_s"), "FPV/chase/map artifacts", "#4f6691"),
        ("Tool handlers", timing.get("tool_handler_s"), "cleanup server work", "#2f766f"),
        ("Other", timing.get("other_mcp_overhead_s"), "startup/finalization remainder", "#7a8491"),
    ]
    return _timing_lane("MCP trace attribution", timing.get("total_elapsed_s"), segments)


def _timing_lane(
    title: str,
    total: Any,
    segments: list[tuple[str, Any, str, str]],
    *,
    render_empty: bool = False,
) -> str:
    total_s = _float_or_none(total)
    if total_s is None:
        if not render_empty:
            return ""
        total_s = 0.0
    if total_s < 0:
        total_s = 0.0
    if total_s <= 0 and not render_empty:
        return ""
    segment_html = []
    visibly_zero_total = render_empty and total_s < 0.05
    if total_s > 0 and not visibly_zero_total:
        for label, value, detail, color in segments:
            seconds = _float_or_none(value)
            if seconds is None or seconds <= 0:
                continue
            pct = max(0.2, min(100.0, seconds / total_s * 100.0))
            segment_html.append(
                '<div class="timing-segment" '
                f'style="--basis: {pct:.3f}%; --segment-color: {html.escape(color)};" '
                f'title="{html.escape(label)}: {html.escape(_seconds_text(seconds))}">'
                f"<strong>{html.escape(label)}</strong>"
                f"<span>{html.escape(_seconds_text(seconds))}</span>"
                f"<small>{html.escape(detail)}</small>"
                "</div>"
            )
    if not segment_html:
        if not render_empty:
            return ""
        segment_html.append(
            '<div class="timing-segment" '
            'style="--basis: 100.000%; --segment-color: #8d96a3;" '
            'title="No measurable split: timestamps were identical">'
            "<strong>No measurable split</strong>"
            f"<span>{html.escape(_seconds_text(total_s))}</span>"
            "<small>timestamps were identical</small>"
            "</div>"
        )
    heading = f"<h3>{html.escape(title)}</h3>" if title else "<h3>Measured distribution</h3>"
    return (
        '<div class="timing-lane-block">'
        '<div class="timing-lane-head">'
        f"{heading}"
        f"<span>{html.escape(_seconds_text(total_s))}</span>"
        "</div>"
        '<div class="timing-lane">' + "".join(segment_html) + "</div></div>"
    )


def _seconds_text(value: Any) -> str:
    if isinstance(value, (int, float)):
        return f"{float(value):.1f}s"
    try:
        return f"{float(value):.1f}s"
    except (TypeError, ValueError):
        return "n/a"


def _float_or_none(value: Any) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _object_timing_cycles(trace_events: list[dict[str, Any]]) -> list[dict[str, Any]]:
    calls = _paired_tool_calls(trace_events)
    cycles = []
    index = 0
    while index < len(calls):
        call = calls[index]
        if not _is_object_cycle_start(call):
            index += 1
            continue
        object_id = str(call.get("object_id") or "")
        end_index = None
        place_index = None
        for cursor in range(index, len(calls)):
            candidate = calls[cursor]
            candidate_object = str(candidate.get("object_id") or "")
            if (
                cursor > index
                and _is_object_cycle_start(candidate)
                and candidate_object
                and candidate_object != object_id
            ):
                break
            if (
                candidate.get("tool") in PLACE_CLEANUP_PHASES
                and candidate.get("ok") is True
                and candidate_object == object_id
            ):
                place_index = cursor
                end_index = cursor
                if cursor + 1 < len(calls) and calls[cursor + 1].get("tool") == "observe":
                    end_index = cursor + 1
                break
        if place_index is None or end_index is None:
            index += 1
            continue
        cycle_calls = calls[index : end_index + 1]
        cycles.append(_summarize_object_timing_cycle(object_id, cycle_calls, trace_events))
        index = end_index + 1
    return cycles


def _is_object_cycle_start(call: dict[str, Any]) -> bool:
    return (
        call.get("tool") in {"navigate_to_visual_candidate", "navigate_to_object"}
        and call.get("ok") is True
        and bool(call.get("object_id"))
    )


def _paired_tool_calls(trace_events: list[dict[str, Any]]) -> list[dict[str, Any]]:
    timed = [
        event
        for event in trace_events
        if isinstance(event.get("wallclock_elapsed"), (int, float))
        and event.get("event") in {"request", "response"}
        and event.get("tool") != "<runtime>"
    ]
    timed.sort(key=lambda event: float(event["wallclock_elapsed"]))
    pending: dict[str, list[dict[str, Any]]] = {}
    pairs = []
    for event in timed:
        tool = str(event.get("tool") or "")
        if event.get("event") == "request":
            pending.setdefault(tool, []).append(event)
            continue
        requests = pending.get(tool) or []
        request = requests.pop(0) if requests else None
        start_s = float((request or event)["wallclock_elapsed"])
        end_s = float(event["wallclock_elapsed"])
        request_payload = (request or {}).get("request") or {}
        response_payload = event.get("response") or {}
        pairs.append(
            {
                "tool": tool,
                "start_s": start_s,
                "end_s": end_s,
                "handler_s": max(0.0, end_s - start_s),
                "object_id": _call_object_id(tool, request_payload, response_payload),
                "ok": response_payload.get("ok"),
            }
        )
    pairs.sort(key=lambda item: float(item["start_s"]))
    return pairs


def _call_object_id(tool: str, request: dict[str, Any], response: dict[str, Any]) -> str:
    if isinstance(response.get("object_id"), str):
        return str(response["object_id"])
    if isinstance(request.get("object_id"), str):
        return str(request["object_id"])
    if tool in {"place", "place_inside"} and isinstance(response.get("placed_object_id"), str):
        return str(response["placed_object_id"])
    return ""


def _summarize_object_timing_cycle(
    object_id: str,
    calls: list[dict[str, Any]],
    trace_events: list[dict[str, Any]],
) -> dict[str, Any]:
    start_s = float(calls[0]["start_s"])
    end_s = float(calls[-1]["end_s"])
    total_s = max(0.0, end_s - start_s)
    handler_s = sum(float(call.get("handler_s") or 0.0) for call in calls)
    gap_intervals = []
    raw_gap_s = 0.0
    for previous, current in zip(calls, calls[1:]):
        gap_start = float(previous["end_s"])
        gap_end = float(current["start_s"])
        if gap_end <= gap_start:
            continue
        gap = gap_end - gap_start
        raw_gap_s += gap
        gap_intervals.append({"start_s": gap_start, "end_s": gap_end, "gap_s": gap})
    robot_gap_overlap = robot_view_capture_overlap_seconds(trace_events, gap_intervals)
    robot_capture_s = robot_view_capture_overlap_seconds(
        trace_events,
        [{"start_s": start_s, "end_s": end_s}],
    )
    agent_gap_s = max(0.0, raw_gap_s - robot_gap_overlap)
    other_s = max(0.0, total_s - handler_s - agent_gap_s - robot_capture_s)
    return {
        "object_id": object_id,
        "start_s": round(start_s, 3),
        "end_s": round(end_s, 3),
        "total_s": round(total_s, 3),
        "tool_handler_s": round(handler_s, 3),
        "agent_gap_s": round(agent_gap_s, 3),
        "robot_view_capture_s": round(robot_capture_s, 3),
        "other_s": round(other_s, 3),
        "tools": [str(call.get("tool") or "") for call in calls],
    }


def _metric(label: str, value: Any) -> str:
    return (
        '<div class="metric">'
        f"<span>{html.escape(str(label))}</span>"
        f"<strong>{html.escape(str(value))}</strong>"
        "</div>"
    )
