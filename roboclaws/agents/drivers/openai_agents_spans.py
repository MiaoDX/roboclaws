"""Sanitized OpenAI Agents SDK span capture."""

from __future__ import annotations

import json
import time
from datetime import datetime
from pathlib import Path
from typing import Any

from roboclaws.agents.drivers.openai_agents_event_projection import _drop_empty, _to_jsonable


class RoboclawsSpanRecorder:
    """Tracing processor that writes sanitized SDK span metadata.

    The OpenAI Agents SDK span export can include raw model input/output and
    function input/output. Roboclaws keeps only identifiers, timing, span type,
    model/usage, MCP tool names, and error metadata so live artifacts stay useful
    without persisting prompts, credentials, or private evaluator truth.
    """

    def __init__(self, path: Path, *, runtime_config: dict[str, Any]) -> None:
        self.path = path
        self.runtime_config = runtime_config
        self.active = True

    def on_trace_start(self, trace: Any) -> None:
        self._append(
            {
                "event": "trace_start",
                "ts_epoch": time.time(),
                "trace_id": str(getattr(trace, "trace_id", "") or ""),
                "workflow_name": str(getattr(trace, "name", "") or ""),
            }
        )

    def on_trace_end(self, trace: Any) -> None:
        self._append(
            {
                "event": "trace_end",
                "ts_epoch": time.time(),
                "trace_id": str(getattr(trace, "trace_id", "") or ""),
                "workflow_name": str(getattr(trace, "name", "") or ""),
            }
        )

    def on_span_start(self, span: Any) -> None:
        self._append(_sanitized_span_event(span, event="span_start", runtime_config=None))

    def on_span_end(self, span: Any) -> None:
        self._append(_sanitized_span_event(span, event="span_end", runtime_config=None))

    def shutdown(self) -> None:
        self.active = False

    def force_flush(self) -> None:
        return None

    def _append(self, payload: dict[str, Any]) -> None:
        if not self.active:
            return
        payload.setdefault("schema", "openai_agents_sanitized_span_v1")
        payload.setdefault("runtime", self.runtime_config.get("runtime"))
        payload.setdefault("provider_profile", self.runtime_config.get("provider_profile"))
        payload.setdefault("model", self.runtime_config.get("model"))
        _append_event(self.path, _drop_empty(payload))


def append_span_limitation(
    path: Path,
    *,
    runtime_config: dict[str, Any],
    reason: str,
    exc: Exception | None = None,
) -> None:
    payload = {
        "schema": "openai_agents_sanitized_span_v1",
        "event": "span_capture_unavailable",
        "ts_epoch": time.time(),
        "runtime": runtime_config.get("runtime"),
        "provider_profile": runtime_config.get("provider_profile"),
        "model": runtime_config.get("model"),
        "reason": reason,
    }
    if exc is not None:
        payload["error_type"] = exc.__class__.__name__
        payload["message"] = str(exc)
    _append_event(path, _drop_empty(payload))


def _sanitized_span_event(
    span: Any,
    *,
    event: str,
    runtime_config: dict[str, Any] | None,
) -> dict[str, Any]:
    span_data = getattr(span, "span_data", None)
    exported = _span_data_export(span_data)
    payload: dict[str, Any] = {
        "schema": "openai_agents_sanitized_span_v1",
        "event": event,
        "ts_epoch": time.time(),
        "trace_id": str(getattr(span, "trace_id", "") or ""),
        "span_id": str(getattr(span, "span_id", "") or ""),
        "parent_id": str(getattr(span, "parent_id", "") or ""),
        "started_at": getattr(span, "started_at", None),
        "ended_at": getattr(span, "ended_at", None),
        "duration_s": _iso_duration_seconds(
            getattr(span, "started_at", None),
            getattr(span, "ended_at", None),
        ),
        "span_type": str(_span_export_value(exported, "type") or getattr(span_data, "type", "")),
        "span_name": _safe_span_name(exported, span_data),
        "error": _sanitized_span_error(getattr(span, "error", None)),
        "usage": _span_usage(exported),
        "mcp": _span_mcp(exported),
        "model": _span_model(exported),
    }
    if runtime_config:
        payload.update(
            {
                "runtime": runtime_config.get("runtime"),
                "provider_profile": runtime_config.get("provider_profile"),
                "model": runtime_config.get("model"),
            }
        )
    return _drop_empty(payload)


def _span_data_export(span_data: Any) -> dict[str, Any]:
    if span_data is None or not hasattr(span_data, "export"):
        return {}
    try:
        exported = span_data.export()
    except Exception:
        return {}
    return exported if isinstance(exported, dict) else {}


def _span_export_value(exported: dict[str, Any], key: str) -> Any:
    if key in exported:
        return exported[key]
    data = exported.get("data")
    if isinstance(data, dict):
        return data.get(key) or data.get(f"sdk_span_{key}")
    return None


def _safe_span_name(exported: dict[str, Any], span_data: Any) -> str:
    span_type = str(_span_export_value(exported, "type") or getattr(span_data, "type", "") or "")
    name = _span_export_value(exported, "name")
    if span_type == "function":
        return str(name or "")
    if span_type in {"agent", "task", "turn", "custom", "mcp_list_tools"}:
        return str(name or "")
    return ""


def _span_usage(exported: dict[str, Any]) -> dict[str, Any]:
    usage = _span_export_value(exported, "usage")
    return _to_jsonable(usage) if isinstance(usage, dict) else {}


def _span_mcp(exported: dict[str, Any]) -> dict[str, Any]:
    mcp: dict[str, Any] = {}
    mcp_data = exported.get("mcp_data")
    if isinstance(mcp_data, dict):
        for key in ("server", "tool_name", "name"):
            if key in mcp_data:
                mcp[key] = mcp_data[key]
    server = exported.get("server")
    if server:
        mcp["server"] = server
    result = exported.get("result")
    if isinstance(result, list):
        mcp["tool_names"] = [str(item) for item in result]
        mcp["tool_count"] = len(result)
    return _to_jsonable(mcp) if mcp else {}


def _span_model(exported: dict[str, Any]) -> str:
    model = _span_export_value(exported, "model")
    return str(model or "")


def _sanitized_span_error(error: Any) -> dict[str, Any]:
    if not isinstance(error, dict):
        return {}
    payload: dict[str, Any] = {}
    message = str(error.get("message") or "")
    if message:
        payload["message"] = message
    data = error.get("data")
    if isinstance(data, dict):
        payload["data_keys"] = sorted(str(key) for key in data.keys())
    return payload


def _iso_duration_seconds(started_at: Any, ended_at: Any) -> float | None:
    if not started_at or not ended_at:
        return None
    try:
        start = datetime.fromisoformat(str(started_at).replace("Z", "+00:00"))
        end = datetime.fromisoformat(str(ended_at).replace("Z", "+00:00"))
    except ValueError:
        return None
    return round(max(0.0, (end - start).total_seconds()), 3)


def _append_event(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(payload, sort_keys=True) + "\n")
