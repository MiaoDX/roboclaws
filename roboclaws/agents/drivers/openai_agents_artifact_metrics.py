"""Artifact-level event and span summaries for OpenAI Agents runs."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from roboclaws.agents.drivers.openai_agents_metric_sources import (
    read_openai_agents_jsonl_source,
)


def openai_agents_event_metrics(run_dir: Path) -> dict[str, Any]:
    event_paths = sorted(run_dir.glob("openai-agents-events*.jsonl"))
    if not event_paths:
        return {
            "available": False,
            "reason": "openai-agents event files not present",
        }

    event_counts: dict[str, int] = {}
    tool_error_classifications: dict[str, int] = {}
    tool_error_messages: list[str] = []
    result_count = 0
    for path in event_paths:
        for event in read_openai_agents_jsonl_source(path):
            event_type = str(event.get("event") or "")
            if event_type:
                event_counts[event_type] = event_counts.get(event_type, 0) + 1
            if event_type == "result":
                result_count += 1
            if event_type != "tool_error":
                continue
            classification = str(event.get("classification") or "tool_error")
            tool_error_classifications[classification] = (
                tool_error_classifications.get(classification, 0) + 1
            )
            message = str(event.get("message") or "")
            if message and len(tool_error_messages) < 8:
                tool_error_messages.append(message)

    return {
        "available": True,
        "event_files": [path.name for path in event_paths],
        "event_counts": dict(sorted(event_counts.items())),
        "result_count": result_count,
        "tool_error_count": sum(tool_error_classifications.values()),
        "tool_error_classifications": dict(sorted(tool_error_classifications.items())),
        "tool_error_messages_sample": tool_error_messages,
    }


def openai_agents_span_metrics(run_dir: Path) -> dict[str, Any]:
    span_paths = sorted(run_dir.glob("openai-agents-spans*.jsonl"))
    if not span_paths:
        return {
            "available": False,
            "reason": "openai-agents span files not present",
        }

    event_counts: dict[str, int] = {}
    span_type_counts: dict[str, int] = {}
    limitations: list[dict[str, Any]] = []
    span_end_count = 0
    for path in span_paths:
        for event in read_openai_agents_jsonl_source(path):
            event_type = str(event.get("event") or "")
            if event_type:
                event_counts[event_type] = event_counts.get(event_type, 0) + 1
            if event_type == "span_capture_unavailable":
                limitations.append(
                    {
                        "reason": event.get("reason", ""),
                        "error_type": event.get("error_type", ""),
                        "message": event.get("message", ""),
                    }
                )
            if event_type != "span_end":
                continue
            span_end_count += 1
            span_type = str(event.get("span_type") or "unknown")
            span_type_counts[span_type] = span_type_counts.get(span_type, 0) + 1

    return {
        "available": True,
        "span_files": [path.name for path in span_paths],
        "event_counts": dict(sorted(event_counts.items())),
        "span_end_count": span_end_count,
        "span_type_counts": dict(sorted(span_type_counts.items())),
        "limitations": limitations,
        "sanitization_note": (
            "Span artifacts retain IDs, timing, span types, model/usage, MCP tool metadata, "
            "and errors. Raw prompts, model text, function inputs, and function outputs are "
            "not persisted."
        ),
    }
