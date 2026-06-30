"""Normalize existing run artifacts into one operator-state payload."""

from __future__ import annotations

import json
import os
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from roboclaws.core.json_sources import read_json_object
from roboclaws.maps.preview import (
    BASE_MAP_SOURCE_FAMILY,
    BASE_METRIC_MAP_PREVIEW_ROLE,
    RUNTIME_MAP_SOURCE_FAMILY,
    RUNTIME_METRIC_MAP_PREVIEW_ROLE,
    SCENE_RENDER_SOURCE_FAMILY,
    TOPDOWN_SCENE_RENDER_ROLE,
)
from roboclaws.operator_console.jsonl_sources import collect_jsonl_objects
from roboclaws.operator_console.locks import ResourceLock


def pid_is_active(pid: Any) -> bool:
    try:
        parsed_pid = int(pid)
    except (TypeError, ValueError):
        return False
    if parsed_pid <= 0:
        return False
    try:
        os.kill(parsed_pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True
from roboclaws.operator_console.redaction import redact_text
from roboclaws.operator_console.routes import ConsoleLaunchSelection
from roboclaws.operator_console.state_checker import checker_status
from roboclaws.operator_console.state_summary import (
    camera_angle_summary,
)

LIVE_RUN_MARKERS = (
    "live_status.json",
    "run_result.json",
    "trace.jsonl",
    "report.html",
    "runtime_metric_map.json",
    "tmux_session.txt",
    "driver.log",
    "openai-agents-events.jsonl",
    "openai-agents-trace.json",
)

AGENT_EVENT_GLOBS = ("openai-agents-events*.jsonl",)


@dataclass(frozen=True)
class ArtifactLink:
    label: str
    path: Path
    kind: str

    def to_payload(self, root: Path) -> dict[str, str]:
        return {
            "label": self.label,
            "kind": self.kind,
            "path": str(self.path),
            "href": _artifact_href(root, self.path),
        }


@dataclass(frozen=True)
class JsonSourceError:
    """Operator-visible source error for a present JSON artifact."""

    path: Path
    label: str
    reason: str

    def to_payload(self, root: Path) -> dict[str, str]:
        return {
            "label": self.label,
            "path": str(self.path),
            "href": _artifact_href(root, self.path) if self.path.exists() else "",
            "reason": self.reason,
        }


def derive_operator_state(
    root: Path, run_dir: Path, route: ConsoleLaunchSelection | None = None
) -> dict[str, Any]:
    """Read a run directory and return the console's normalized live state."""

    run_dir = run_dir.resolve()
    display_run_dir = resolve_display_run_dir(run_dir)
    json_sources = (
        _read_json_source(run_dir / "operator_state.json", label="Operator State"),
        _read_json_source(
            _latest_existing(display_run_dir, ("live_status.json",)),
            label="Live Status",
        ),
        _read_json_source(
            _latest_existing(display_run_dir, ("run_result.json",)),
            label="Run Result",
        ),
    )
    status = _json_source_payload(json_sources[0])
    live_status = _json_source_payload(json_sources[1])
    run_result = _json_source_payload(json_sources[2])
    launch_failure = _wrapper_launch_failure(
        status, live_status, run_result, run_dir, display_run_dir
    )
    trace_path = _latest_existing(display_run_dir, ("trace.jsonl",))
    trace_rows, trace_source_errors = _read_jsonl_source(trace_path, label="Trace")
    source_errors = (
        *(source for source in json_sources if isinstance(source, JsonSourceError)),
        *trace_source_errors,
    )
    latest_trace = _last_robot_tool_jsonl(trace_rows) or _last_jsonl(trace_rows)
    camera_state = _camera_angle_summary(trace_rows)
    phase = str(
        live_status.get("phase")
        or launch_failure.get("phase")
        or status.get("phase")
        or live_status.get("status")
        or run_result.get("status")
        or "idle"
    )
    stale_live_failure = _stale_live_status_failure(live_status, run_result)
    if stale_live_failure:
        phase = "failed"
    agent_message, agent_source_errors = _latest_agent_message(display_run_dir)
    source_errors = (*source_errors, *agent_source_errors)
    source_failure = _json_source_failure(source_errors)
    if source_failure:
        phase = "failed"
    checker = checker_status(
        checker_log=_latest_existing(display_run_dir, ("checker.log",)),
        report=_latest_existing(display_run_dir, ("report.html",)),
        run_result=run_result,
        phase=phase,
        launch_failure_reason=str(
            source_failure.get("terminal_reason")
            or stale_live_failure.get("terminal_reason")
            or launch_failure.get("terminal_reason")
            or ""
        ),
    )
    terminal_status = dict(status)
    terminal_status.update(launch_failure)
    terminal_status.update(stale_live_failure)
    terminal_status.update(source_failure)
    terminal_reason = _terminal_reason(terminal_status, live_status, run_result)
    artifacts = [link.to_payload(root) for link in _artifact_links(display_run_dir)]
    artifacts.extend(link.to_payload(root) for link in _wrapper_artifact_links(run_dir))
    latest_view_assets = _latest_view_assets(
        root,
        display_run_dir,
    )
    public_result = _public_run_result_summary(run_result)
    prompt_preview = _prompt_preview(status, live_status, run_result, display_run_dir)
    run_id = str(status.get("run_id") or run_dir.name)
    from roboclaws.operator_console.interactions import operator_message_state

    interaction_state = operator_message_state(root, run_dir)
    normalized_status = _status_from_phase(phase, checker, terminal_reason)
    controls_terminal = _control_terminal_state(phase, normalized_status, terminal_reason)
    supports_relative_control = bool(route.supports_relative_navigation_control) if route else False
    operator_handoff_paused = _operator_handoff_paused(phase, terminal_reason)
    supports_resume = bool(route.supports_paused_handoff_resume) if route else False
    raw_resume_available = bool(
        live_status.get("resume_available") or status.get("resume_available")
    )
    resume_available = bool(operator_handoff_paused and supports_resume and raw_resume_available)
    steer_available = bool(
        route
        and route.supports_operator_steer
        and not controls_terminal
        and not operator_handoff_paused
    )
    relative_control_pending = bool(
        supports_relative_control
        and not controls_terminal
        and _relative_control_startup_pending(phase)
    )
    relative_control_available = bool(
        supports_relative_control and not controls_terminal and not relative_control_pending
    )
    stop_available = _stop_available(
        root=root,
        run_id=run_id,
        route=route,
        status=status,
        phase=phase,
    )

    return {
        "run_id": run_id,
        "display_run_id": display_run_id(run_dir, display_run_dir),
        "route": status.get("route") or (route.to_payload() if route else None),
        "selected_intent": status.get("selected_intent") or (route.intent_id if route else ""),
        "run_dir": str(run_dir),
        "display_run_dir": str(display_run_dir),
        "phase": phase,
        "status": normalized_status,
        "status_label": _status_label(phase, terminal_reason),
        "backend_lock": status.get("backend_lock") or (route.lock_name if route else ""),
        "pid": status.get("pid"),
        "started_at": status.get("started_at"),
        "elapsed_seconds": _elapsed_seconds(status),
        "latest_action": _latest_action(latest_trace, run_result),
        "latest_public_decision_evidence": _decision_evidence(
            latest_trace, run_result, agent_message
        ),
        "latest_tool_call": _tool_call_summary(latest_trace),
        "camera_state": camera_state,
        "artifact_paths": artifacts,
        "latest_view_assets": latest_view_assets,
        "checker_status": checker,
        "terminal_reason": terminal_reason,
        "operator_handoff_paused": operator_handoff_paused,
        "live_resume_available": raw_resume_available,
        "live_retryable": bool(live_status.get("retryable")),
        "source_errors": [error.to_payload(root) for error in source_errors],
        "public_run_result": public_result,
        "prompt_preview": prompt_preview,
        "operator_prompt": prompt_preview.get("operator_prompt") or "",
        "agent_kickoff_prompt": prompt_preview.get("agent_kickoff_prompt") or "",
        "operator_session_id": status.get("operator_session_id") or "",
        "operator_messages": interaction_state,
        "latest_operator_control": status.get("latest_operator_control") or {},
        "operator_interventions": status.get("operator_interventions") or {},
        "controls": {
            "next_goal_available": controls_terminal,
            "steer_available": steer_available,
            "resume_available": resume_available,
            "resume_blocked": bool(operator_handoff_paused and not resume_available),
            "operator_handoff_paused": operator_handoff_paused,
            "supports_operator_steer": bool(route.supports_operator_steer) if route else False,
            "supports_paused_handoff_resume": supports_resume,
            "relative_navigation_control_available": relative_control_available,
            "relative_navigation_control_pending": relative_control_pending,
            "supports_relative_navigation_control": supports_relative_control,
            "stop_available": stop_available,
            "emergency_stop_required": bool(route.emergency_stop_required) if route else False,
        },
    }


def resolve_display_run_dir(run_dir: Path) -> Path:
    """Return the nested live-attempt directory that currently owns evidence."""

    run_dir = run_dir.resolve()
    candidates = (
        [run_dir] if any((run_dir / marker).exists() for marker in LIVE_RUN_MARKERS) else []
    )
    for marker in LIVE_RUN_MARKERS:
        try:
            matches = run_dir.rglob(marker)
        except OSError:
            continue
        for path in matches:
            if not path.is_file():
                continue
            parent = path.parent.resolve()
            if parent not in candidates:
                candidates.append(parent)
    if not candidates:
        return run_dir
    return max(candidates, key=_run_dir_activity_mtime)


def display_run_id(wrapper_run_dir: Path, display_run_dir: Path) -> str:
    """Return the operator-facing id for a wrapper run or nested live attempt."""

    if wrapper_run_dir == display_run_dir:
        return wrapper_run_dir.name
    try:
        return str(display_run_dir.relative_to(wrapper_run_dir))
    except ValueError:
        return display_run_dir.name


def redacted_artifact_text(path: Path, *, max_bytes: int = 200_000) -> str:
    """Read a raw text artifact and redact secrets before serving it."""

    data = path.read_bytes()
    if max_bytes > 0 and len(data) > max_bytes:
        head_bytes = max_bytes // 2
        tail_bytes = max_bytes - head_bytes
        omitted = len(data) - max_bytes
        marker = (
            f"\n\n[operator console truncated {omitted} raw bytes; "
            "showing beginning and end of artifact]\n\n"
        ).encode()
        data = data[:head_bytes] + marker + data[-tail_bytes:]
    text = data.decode("utf-8", errors="replace")
    return redact_text(text)


def _wrapper_launch_failure(
    status: dict[str, Any],
    live_status: dict[str, Any],
    run_result: dict[str, Any],
    run_dir: Path,
    display_run_dir: Path,
) -> dict[str, str]:
    if live_status or run_result or display_run_dir != run_dir:
        return {}
    phase = str(status.get("phase") or "").strip().lower()
    if not _phase_is_active(phase):
        return {}
    if not status.get("pid"):
        return {}
    if pid_is_active(status.get("pid")):
        return {}
    reason = _launch_log_failure_reason(run_dir / "console-launch.log")
    return {
        "phase": "failed",
        "terminal_reason": reason or "launch wrapper exited before writing live run artifacts",
    }


def _launch_log_failure_reason(log_path: Path) -> str:
    if not log_path.exists():
        return ""
    try:
        text = log_path.read_text(encoding="utf-8", errors="replace")[-80_000:]
    except OSError:
        return ""
    lines = [line.strip() for line in redact_text(text).splitlines() if line.strip()]
    error_lines = [line for line in lines if line.lower().startswith("error:")]
    for line in error_lines:
        if "recipe `" not in line:
            return line.split(":", 1)[1].strip()
    if error_lines:
        return error_lines[0].split(":", 1)[1].strip()
    if "Traceback (most recent call last)" in text:
        return "launch command raised an exception before live artifacts were written"
    return ""


def _stale_live_status_failure(
    live_status: dict[str, Any], run_result: dict[str, Any]
) -> dict[str, str]:
    phase = str(live_status.get("phase") or "").strip().lower()
    if not _phase_is_active(phase) or run_result:
        return {}
    pid = _live_status_owner_pid(live_status)
    if pid is None or pid_is_active(pid):
        return {}
    return {
        "phase": "failed",
        "terminal_reason": "live runner process exited before terminal status",
    }


def _live_status_owner_pid(live_status: dict[str, Any]) -> int | None:
    for value in (
        live_status.get("pid"),
        (live_status.get("visual_backend_slot") or {}).get("pid")
        if isinstance(live_status.get("visual_backend_slot"), dict)
        else None,
    ):
        try:
            pid = int(value)
        except (TypeError, ValueError):
            continue
        if pid > 0:
            return pid
    return None


def _read_json_source(path: Path, *, label: str) -> dict[str, Any] | JsonSourceError:
    if not path or not path.exists():
        return {}
    try:
        return read_json_object(path, label=label)
    except ValueError as exc:
        cause = exc.__cause__
        if isinstance(cause, json.JSONDecodeError):
            return JsonSourceError(
                path=path.resolve(),
                label=label,
                reason=f"invalid JSON at line {cause.lineno} column {cause.colno}",
            )
        return JsonSourceError(path=path.resolve(), label=label, reason="expected JSON object")
    except OSError as exc:
        return JsonSourceError(path=path.resolve(), label=label, reason=str(exc))


def _json_source_payload(source: dict[str, Any] | JsonSourceError) -> dict[str, Any]:
    return source if isinstance(source, dict) else {}


def _json_source_failure(errors: tuple[JsonSourceError, ...]) -> dict[str, str]:
    if not errors:
        return {}
    labels = ", ".join(dict.fromkeys(error.label for error in errors))
    return {
        "phase": "failed",
        "terminal_reason": f"operator state source error: {labels}",
    }


def _prompt_preview(
    status: dict[str, Any],
    live_status: dict[str, Any],
    run_result: dict[str, Any],
    display_run_dir: Path,
) -> dict[str, Any]:
    for payload in (status, live_status, run_result):
        value = payload.get("prompt_preview")
        if isinstance(value, dict):
            return value
    kickoff_path = display_run_dir / "agent_kickoff_prompt.txt"
    if kickoff_path.exists():
        try:
            kickoff = kickoff_path.read_text(encoding="utf-8", errors="replace").strip()
        except OSError:
            kickoff = ""
        if kickoff:
            return {
                "operator_prompt": str(
                    run_result.get("task_prompt") or run_result.get("task") or ""
                ),
                "agent_kickoff_prompt": kickoff,
                "prompt": kickoff,
                "source": "artifact",
                "summary": "kickoff prompt artifact",
                "wrapper_notes": [],
            }
    prompt = str(
        status.get("agent_kickoff_prompt")
        or live_status.get("agent_kickoff_prompt")
        or run_result.get("agent_kickoff_prompt")
        or ""
    )
    operator_prompt = str(
        status.get("operator_prompt")
        or live_status.get("operator_prompt")
        or run_result.get("task_prompt")
        or run_result.get("task")
        or ""
    )
    if not prompt and operator_prompt:
        prompt = operator_prompt
    if not prompt:
        return {}
    return {
        "operator_prompt": operator_prompt,
        "agent_kickoff_prompt": prompt,
        "prompt": prompt,
        "source": "status",
        "summary": "launch prompt from status",
        "wrapper_notes": [],
    }


def _last_jsonl(rows: list[dict[str, Any]]) -> dict[str, Any]:
    for payload in reversed(rows):
        if isinstance(payload, dict):
            return payload
    return {}


def _read_jsonl_source(
    path: Path,
    *,
    label: str,
) -> tuple[list[dict[str, Any]], tuple[JsonSourceError, ...]]:
    rows, issues = collect_jsonl_objects(path, label=label)
    return rows, tuple(
        JsonSourceError(path=issue.path, label=issue.label, reason=issue.state_reason())
        for issue in issues
    )


def _last_robot_tool_jsonl(rows: list[dict[str, Any]]) -> dict[str, Any]:
    for index in range(len(rows) - 1, -1, -1):
        payload = rows[index]
        if isinstance(payload, dict):
            tool = str(payload.get("tool") or payload.get("tool_name") or "")
            if tool and tool != "<runtime>":
                return _paired_tool_trace(payload, rows[:index])
    return {}


def _camera_angle_summary(rows: list[dict[str, Any]]) -> dict[str, Any]:
    return camera_angle_summary(rows)


def _paired_tool_trace(trace: dict[str, Any], previous: list[dict[str, Any]]) -> dict[str, Any]:
    if trace.get("event") != "response":
        return trace
    request = trace.get("request") if isinstance(trace.get("request"), dict) else None
    if request:
        return _with_latency_from_request(trace, None)
    tool = str(trace.get("tool") or trace.get("tool_name") or "")
    for candidate in reversed(previous):
        if candidate.get("event") != "request":
            continue
        candidate_tool = str(candidate.get("tool") or candidate.get("tool_name") or "")
        if candidate_tool != tool:
            continue
        merged = dict(trace)
        candidate_request = candidate.get("request")
        if isinstance(candidate_request, dict):
            merged["request"] = candidate_request
        return _with_latency_from_request(merged, candidate)
    return trace


def _with_latency_from_request(
    trace: dict[str, Any], request_trace: dict[str, Any] | None
) -> dict[str, Any]:
    if trace.get("latency_ms") is not None or trace.get("duration_ms") is not None:
        return trace
    start = _numeric_trace_time(request_trace) if request_trace is not None else None
    end = _numeric_trace_time(trace)
    if start is None or end is None or end < start:
        return trace
    merged = dict(trace)
    merged["latency_ms"] = round((end - start) * 1000, 3)
    return merged


def _numeric_trace_time(trace: dict[str, Any] | None) -> float | None:
    if not trace:
        return None
    for key in ("ts", "timestamp", "wallclock_elapsed"):
        try:
            return float(trace.get(key))
        except (TypeError, ValueError):
            continue
    return None


def _float_or_zero(value: Any) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return 0.0
    if number == 0:
        return 0.0
    return round(number, 3)


def _latest_agent_message(run_dir: Path) -> tuple[str, tuple[JsonSourceError, ...]]:
    event_paths: list[Path] = []
    for pattern in AGENT_EVENT_GLOBS:
        event_paths.extend(path for path in run_dir.glob(pattern) if path.is_file())
    event_paths = sorted(set(event_paths), key=_safe_mtime)
    source_errors: list[JsonSourceError] = []
    for path in reversed(event_paths):
        rows, row_errors = _read_jsonl_source(path, label=_agent_event_label(path))
        source_errors.extend(row_errors)
        message = _last_agent_message(rows)
        if message:
            return message, tuple(source_errors)
    return "", tuple(source_errors)


def _agent_event_label(path: Path) -> str:
    del path
    return "Agent Events"


def _last_agent_message(rows: list[dict[str, Any]]) -> str:
    for payload in reversed(rows):
        text = _agent_message_text(payload)
        if text:
            return text
    return ""


def _agent_message_text(payload: dict[str, Any]) -> str:
    item = payload.get("item")
    if isinstance(item, dict) and item.get("type") == "agent_message":
        text = item.get("text")
        if text:
            return str(text)

    message = payload.get("message")
    if isinstance(message, dict) and _is_assistant_message_payload(payload, message):
        text = _message_content_text(message.get("content"))
        if text:
            return text

    if _is_assistant_payload(payload):
        text = _message_content_text(payload.get("content"))
        if text:
            return text

    summary = payload.get("summary")
    if isinstance(summary, dict):
        for key in ("final_output", "output_text", "message"):
            value = summary.get(key)
            if value:
                return str(value)
    return ""


def _is_assistant_message_payload(payload: dict[str, Any], message: dict[str, Any]) -> bool:
    return (
        str(payload.get("type") or "").lower() == "assistant"
        or str(message.get("role") or "").lower() == "assistant"
    )


def _is_assistant_payload(payload: dict[str, Any]) -> bool:
    return str(payload.get("role") or "").lower() == "assistant"


def _message_content_text(content: Any) -> str:
    if isinstance(content, str):
        return content
    if not isinstance(content, list):
        return ""
    texts: list[str] = []
    for item in content:
        if isinstance(item, str):
            texts.append(item)
            continue
        if not isinstance(item, dict):
            continue
        if item.get("type") in {None, "text", "output_text"} and item.get("text"):
            texts.append(str(item["text"]))
    return "\n".join(text.strip() for text in texts if text and text.strip())


def _latest_existing(run_dir: Path, names: tuple[str, ...]) -> Path:
    candidates: list[Path] = []
    for name in names:
        candidates.extend(path for path in run_dir.rglob(name) if path.is_file())
    if not candidates:
        return run_dir / names[0]
    return max(candidates, key=lambda path: path.stat().st_mtime)


def _artifact_links(run_dir: Path) -> list[ArtifactLink]:
    specs = (
        ("Report", "report.html", "html"),
        ("Run Result", "run_result.json", "json"),
        ("Trace", "trace.jsonl", "jsonl"),
        ("Agent Events", "openai-agents-events.jsonl", "jsonl"),
        ("OpenAI Agents Trace", "openai-agents-trace.json", "json"),
        ("Driver Log", "driver.log", "log"),
        ("Checker Output", "checker.log", "log"),
        ("Runtime Map", "runtime_metric_map.json", "json"),
        ("Runtime Metric Map Preview", "runtime_metric_map_preview.png", "image"),
        ("B1 Robot Consumption", "b1_robot_consumption_manifest.json", "json"),
        ("Runtime Map Prior", "runtime_map_prior_snapshot.json", "json"),
        ("Runtime Map Prior Targets", "runtime_map_prior_targets.json", "json"),
    )
    links: list[ArtifactLink] = []
    for label, name, kind in specs:
        path = _latest_existing(run_dir, (name,))
        if path.exists():
            links.append(ArtifactLink(label=label, path=path.resolve(), kind=kind))
    return links


def _wrapper_artifact_links(run_dir: Path) -> list[ArtifactLink]:
    specs = (
        ("Console Launch Log", "console-launch.log", "log"),
        ("Operator State", "operator_state.json", "json"),
        ("Operator Messages", "operator_messages.jsonl", "jsonl"),
        ("Operator Control", "operator_control.jsonl", "jsonl"),
        ("Operator Interventions", "operator_interventions.json", "json"),
        ("B1 Robot Consumption", "b1_robot_consumption_manifest.json", "json"),
        ("Runtime Map Prior", "runtime_map_prior_snapshot.json", "json"),
        ("Runtime Map Prior Targets", "runtime_map_prior_targets.json", "json"),
    )
    links: list[ArtifactLink] = []
    for label, name, kind in specs:
        path = run_dir / name
        if path.exists():
            links.append(ArtifactLink(label=label, path=path.resolve(), kind=kind))
    return links


def _latest_view_assets(root: Path, run_dir: Path) -> dict[str, dict[str, Any]]:
    patterns = {
        "fpv": ("*.fpv*.png", "*.fpv*.jpg", "*fpv*.png", "*fpv*.jpg"),
        "chase": ("*.chase*.png", "*.chase*.jpg", "*chase*.png", "*chase*.jpg"),
        "map": ("map_bundle/preview.png",),
        "runtime_map": ("runtime_metric_map_preview.png",),
        "topdown": (
            "*topdown*.png",
            "*topdown*.jpg",
            "*top-down*.png",
            "*top-down*.jpg",
            "*top_down*.png",
            "*top_down*.jpg",
        ),
        "grounding": (
            "visual_grounding/overlays/**/*.jpg",
            "visual_grounding/overlays/**/*.png",
        ),
    }
    preferred_dirs = {
        "fpv": ("robot_views",),
        "chase": ("robot_views",),
        "topdown": ("robot_views",),
    }
    output: dict[str, dict[str, Any]] = {}
    for key, globs in patterns.items():
        matches: list[Path] = []
        for directory in preferred_dirs.get(key, ()):
            base = run_dir / directory
            if not base.is_dir():
                continue
            for pattern in globs:
                matches.extend(path for path in base.rglob(pattern) if path.is_file())
        if not matches:
            for pattern in globs:
                matches.extend(path for path in run_dir.rglob(pattern) if path.is_file())
        if not matches:
            continue
        path = max(matches, key=lambda item: item.stat().st_mtime).resolve()
        output[key] = {
            "path": str(path),
            "href": _artifact_href(root, path),
            "mtime": str(path.stat().st_mtime),
            **_view_asset_role_metadata(key),
        }
    if "grounding" in output:
        output["fpv"] = {
            **output["grounding"],
            "display_source": "visual_grounding_overlay",
        }
    return output


def _view_asset_role_metadata(key: str) -> dict[str, str]:
    if key == "map":
        return {
            "visual_role": BASE_METRIC_MAP_PREVIEW_ROLE,
            "artifact_source_family": BASE_MAP_SOURCE_FAMILY,
        }
    if key == "runtime_map":
        return {
            "visual_role": RUNTIME_METRIC_MAP_PREVIEW_ROLE,
            "artifact_source_family": RUNTIME_MAP_SOURCE_FAMILY,
        }
    if key == "topdown":
        return {
            "visual_role": TOPDOWN_SCENE_RENDER_ROLE,
            "artifact_source_family": SCENE_RENDER_SOURCE_FAMILY,
        }
    return {"visual_role": key, "artifact_source_family": "run_view_artifact"}


def _artifact_href(root: Path, path: Path) -> str:
    if not path.is_relative_to(root):
        return ""
    return f"/artifacts/{path.relative_to(root)}?v={path.stat().st_mtime_ns}"


def _terminal_reason(
    status: dict[str, Any], live_status: dict[str, Any], run_result: dict[str, Any]
) -> str:
    for payload in (live_status, status, run_result):
        for key in ("terminal_reason", "terminate_reason", "error_reason", "reason", "status"):
            value = payload.get(key)
            if value:
                return str(value)
    return ""


def _status_from_phase(phase: str, checker: dict[str, Any], terminal_reason: str) -> str:
    lower = phase.lower()
    if _is_provider_transient_reason(terminal_reason):
        return "provider_transient_failed"
    if lower in {"stopped_by_operator", "human_takeover_stop", "failed", "passed"}:
        return lower
    if checker.get("status") == "passed":
        return "passed"
    if terminal_reason and lower in {"failed", "error", "terminated"}:
        return "failed"
    if _phase_is_active(lower):
        return lower
    return "idle"


def _status_label(phase: str, terminal_reason: str) -> str:
    if _is_provider_transient_reason(terminal_reason):
        return "Provider transient failure"
    return phase


def _control_terminal_state(phase: str, status: str, terminal_reason: str) -> bool:
    terminal_values = {
        "done",
        "finished",
        "passed",
        "failed",
        "stopped_by_operator",
        "human_takeover_stop",
        "emergency_stopped",
    }
    return (
        phase.lower() in terminal_values
        or status.lower() in terminal_values
        or terminal_reason.lower() in terminal_values
    )


def _relative_control_startup_pending(phase: str) -> bool:
    return phase.lower() in {
        "queued",
        "starting",
        "starting-server",
    }


def _operator_handoff_paused(phase: str, terminal_reason: str) -> bool:
    return phase.lower() == "paused" and terminal_reason.lower() == "operator_handoff_requested"


def _is_provider_transient_reason(reason: str) -> bool:
    normalized = reason.lower()
    return "provider_transient_failure" in normalized or "provider transient" in normalized


def _elapsed_seconds(status: dict[str, Any]) -> float | None:
    value = status.get("started_at_epoch") or status.get("started_at")
    try:
        start = float(value)
    except (TypeError, ValueError):
        return None
    return max(0.0, time.time() - start)


def _latest_action(trace: dict[str, Any], run_result: dict[str, Any]) -> str:
    for payload in (trace, run_result):
        for key in ("action", "tool", "tool_name", "selected_action", "latest_action"):
            value = payload.get(key)
            if value:
                return str(value)
    return ""


def _phase_is_active(phase: str) -> bool:
    return phase in {
        "queued",
        "starting",
        "starting-server",
        "running",
        "running-sdk",
        "waiting-for-server-finish",
        "checking-result",
        "paused",
        "stopping",
    }


def _stop_available(
    *,
    root: Path,
    run_id: str,
    route: ConsoleLaunchSelection | None,
    status: dict[str, Any],
    phase: str,
) -> bool:
    normalized = phase.lower()
    if _phase_is_active(normalized):
        return True
    if normalized not in {
        "failed",
        "finished",
        "passed",
        "stopped_by_operator",
        "human_takeover_stop",
    }:
        return False
    lock_name = str(status.get("backend_lock") or (route.lock_name if route else ""))
    if not lock_name:
        return False
    lock_state = ResourceLock(root, lock_name).read()
    return lock_state.held and lock_state.owner_run_id == run_id


def _decision_evidence(
    trace: dict[str, Any], run_result: dict[str, Any], agent_message: str = ""
) -> dict[str, str]:
    evidence: dict[str, str] = {}
    for key in ("goal", "observation_summary", "reasoning", "decision", "blocked_reason"):
        value = trace.get(key) or run_result.get(key)
        if value:
            evidence[key] = str(value)
    if "observation_summary" not in evidence:
        summary = _trace_summary(trace)
        if summary:
            evidence["observation_summary"] = summary
    if agent_message:
        evidence.setdefault("decision", agent_message)
    return evidence


def _trace_summary(trace: dict[str, Any]) -> str:
    event = str(trace.get("event") or "")
    tool = str(trace.get("tool") or trace.get("tool_name") or trace.get("action") or "")
    if not tool:
        return ""
    response = trace.get("response") if isinstance(trace.get("response"), dict) else {}
    request = trace.get("request") if isinstance(trace.get("request"), dict) else {}
    if event == "request":
        args = _compact_tool_arguments(request)
        return f"Calling {tool}{args}."
    if event == "response" or response:
        status = response.get("status") or response.get("navigation_status") or ""
        ok = response.get("ok")
        suffix = _compact_response_detail(tool, response)
        if ok is True:
            return f"{tool} completed{suffix}."
        if ok is False:
            error = response.get("error") or response.get("error_reason") or "not ok"
            return f"{tool} failed: {error}."
        if status:
            return f"{tool} returned {status}{suffix}."
        return f"{tool} returned a response{suffix}."
    return f"Latest trace event: {tool}."


def _compact_tool_arguments(request: dict[str, Any]) -> str:
    for key in ("object_id", "fixture_id", "waypoint_id"):
        value = request.get(key)
        if value:
            return f" {key}={value}"
    return ""


def _compact_response_detail(tool: str, response: dict[str, Any]) -> str:
    for key in ("object_id", "fixture_id", "waypoint_id", "receptacle_id"):
        value = response.get(key)
        if value:
            return f" for {key}={value}"
    if tool == "observe":
        detections = response.get("visible_object_detections")
        if isinstance(detections, list):
            return f" with {len(detections)} visible detection(s)"
    return ""


def _tool_call_summary(trace: dict[str, Any]) -> dict[str, Any]:
    if not trace:
        return {}
    response = trace.get("response") if isinstance(trace.get("response"), dict) else {}
    request = trace.get("request") if isinstance(trace.get("request"), dict) else {}
    return {
        "name": trace.get("tool") or trace.get("tool_name") or trace.get("action") or "",
        "ok": trace.get("ok") if "ok" in trace else response.get("ok"),
        "arguments": request,
        "latency_ms": trace.get("latency_ms") or trace.get("duration_ms"),
        "error": trace.get("error") or trace.get("error_reason") or response.get("error") or "",
    }


def _public_run_result_summary(run_result: dict[str, Any]) -> dict[str, Any]:
    allowed = (
        "task",
        "backend",
        "policy",
        "profile",
        "task_surface",
        "task_intent",
        "status",
        "ok",
        "success",
        "cleanup_success",
        "runtime_map_success",
        "intent_status",
        "goal_status",
        "cleanup_status",
        "cleanup_status_role",
        "completion_status",
        "final_status",
        "terminate_reason",
        "primitive_provenance",
    )
    return {key: run_result[key] for key in allowed if key in run_result}


def _run_dir_activity_mtime(path: Path) -> float:
    mtimes: list[float] = []
    for marker in LIVE_RUN_MARKERS:
        marker_path = path / marker
        if marker_path.exists():
            try:
                mtimes.append(marker_path.stat().st_mtime)
            except OSError:
                pass
    if mtimes:
        return max(mtimes)
    try:
        return path.stat().st_mtime
    except OSError:
        return 0.0


def _safe_mtime(path: Path) -> float:
    try:
        return path.stat().st_mtime
    except OSError:
        return 0.0
