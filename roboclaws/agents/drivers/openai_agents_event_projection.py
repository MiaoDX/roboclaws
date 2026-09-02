"""JSON-safe event and SDK-result projection for the OpenAI Agents runtime."""

from __future__ import annotations

import hashlib
import json
from typing import Any

from roboclaws.agents.task_state import (
    Checkpoint,
    EvidenceRef,
    Observation,
    TaskSnapshot,
    atomic_write_checkpoint,
    digest_payload,
)


def _drop_empty(payload: dict[str, Any]) -> dict[str, Any]:
    return {key: value for key, value in payload.items() if not _is_empty_json_value(value)}


def _is_empty_json_value(value: Any) -> bool:
    if value is None:
        return True
    if isinstance(value, str) and value == "":
        return True
    return isinstance(value, (list, tuple, dict)) and not value


def _json_size_bytes(value: Any) -> int:
    return len(json.dumps(_to_jsonable(value), sort_keys=True).encode("utf-8"))


def _stable_item_hash(value: Any) -> str:
    material = json.dumps(_to_jsonable(value), sort_keys=True).encode("utf-8")
    return hashlib.sha256(material).hexdigest()


def _to_jsonable(value: Any) -> Any:
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    if isinstance(value, dict):
        return {str(key): _to_jsonable(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_to_jsonable(item) for item in value]
    if hasattr(value, "model_dump"):
        return _to_jsonable(value.model_dump())
    if hasattr(value, "__dict__"):
        return _to_jsonable(vars(value))
    return str(value)


_PUBLIC_KEYS = {
    "pose": ("pose", "robot_pose", "position"),
    "waypoint": ("waypoint", "current_waypoint"),
    "safety": ("safety", "safety_status"),
    "completion": ("completion", "done", "completed"),
}


def project_tool_event(snapshot: TaskSnapshot, event: Any) -> TaskSnapshot:
    """Apply one successful normalized public tool event to a new snapshot."""
    if not isinstance(event, dict) or event.get("success") is False or event.get("error"):
        return snapshot
    name = str(event.get("tool") or event.get("tool_name") or event.get("event") or "").lower()
    payload = event.get("result", event.get("output", event.get("data", event)))
    if not isinstance(payload, dict):
        payload = {"value": payload}
    updated = TaskSnapshot.from_dict(snapshot.to_dict())
    changed = _project_fields(updated, payload)
    if any(term in name for term in ("observe", "look", "inspect")):
        for key, value in (
            payload.get("objects", {}).items() if isinstance(payload.get("objects"), dict) else ()
        ):
            updated.objects[str(key)] = Observation(
                value if isinstance(value, (str, int, float, bool)) else None,
                str(event.get("ts") or ""),
                "mcp",
                False,
            )
        changed = True
    if any(term in name for term in ("pick", "place", "move", "navigate", "grasp")):
        updated.action_outcomes = [*updated.action_outcomes[-31:], {"action": name, "ok": True}]
        changed = True
    if any(key in payload for key in ("evidence_ref", "artifact_ref", "evidence")):
        ref = payload.get("evidence_ref") or payload.get("artifact_ref") or payload.get("evidence")
        updated.evidence.append(EvidenceRef(str(ref), digest_payload(payload)))
        updated.evidence = updated.evidence[-32:]
        changed = True
    if not changed:
        return snapshot
    updated.revision = snapshot.revision + 1
    return updated


def _project_fields(snapshot: TaskSnapshot, payload: dict[str, Any]) -> bool:
    changed = False
    for field, keys in _PUBLIC_KEYS.items():
        value = next((payload[key] for key in keys if key in payload), None)
        if value is not None and _json_size_bytes(value) <= 4096:
            setattr(snapshot, field, _to_jsonable(value))
            changed = True
    return changed


def persist_projected_tool_event(path: str, snapshot: TaskSnapshot, event: Any) -> TaskSnapshot:
    updated = project_tool_event(snapshot, event)
    if updated.revision != snapshot.revision:
        atomic_write_checkpoint(path, Checkpoint(updated))
    return updated


def _summarize_sdk_result(result: Any) -> dict[str, Any]:
    payload: dict[str, Any] = {}
    final_output = getattr(result, "final_output", None)
    if final_output is not None:
        final_output_text = str(final_output)
        payload["final_output_present"] = True
        payload["final_output_chars"] = len(final_output_text)
        payload["message"] = (
            "OpenAI Agents SDK result captured; assistant output redacted by "
            "artifact privacy policy."
        )
    last_agent = getattr(result, "last_agent", None)
    if last_agent is not None:
        name = getattr(last_agent, "name", None)
        if name:
            payload["last_agent_name"] = str(name)
        payload["last_agent_class"] = last_agent.__class__.__name__
    trace_id = getattr(result, "trace_id", None)
    if trace_id is not None:
        payload["trace_id"] = str(trace_id)
    usage = getattr(result, "usage", None)
    if usage is not None:
        payload["usage"] = _to_jsonable(usage)
    session_id = getattr(result, "session_id", None)
    if session_id:
        payload["session_id"] = str(session_id)
    return payload


def _usage_summary(result: Any) -> dict[str, Any]:
    raw_usage = getattr(result, "usage", None)
    if raw_usage is None:
        context_wrapper = getattr(result, "context_wrapper", None)
        raw_usage = getattr(context_wrapper, "usage", None)
    usage = _to_jsonable(raw_usage) if raw_usage is not None else {}
    if not isinstance(usage, dict) or not usage:
        return {"usage_available": False}
    input_tokens = _int_from_any(usage.get("input_tokens"))
    cached_tokens = _cached_input_tokens_from_usage(usage)
    output_tokens = _int_from_any(usage.get("output_tokens"))
    reasoning_tokens = _reasoning_tokens_from_usage(usage)
    payload: dict[str, Any] = {
        "usage_available": True,
        "input_tokens": input_tokens,
        "cached_input_tokens": cached_tokens,
        "output_tokens": output_tokens,
        "reasoning_tokens": reasoning_tokens,
    }
    if input_tokens is not None and cached_tokens is not None:
        payload["uncached_input_tokens"] = max(0, input_tokens - cached_tokens)
    return _drop_empty(payload)


def _cached_input_tokens_from_usage(usage: dict[str, Any]) -> int | None:
    details = usage.get("input_tokens_details")
    if isinstance(details, dict):
        cached = _int_from_any(details.get("cached_tokens"))
        if cached is not None:
            return cached
    return _int_from_any(usage.get("cached_input_tokens"))


def _reasoning_tokens_from_usage(usage: dict[str, Any]) -> int | None:
    details = usage.get("output_tokens_details")
    if isinstance(details, dict):
        reasoning = _int_from_any(details.get("reasoning_tokens"))
        if reasoning is not None:
            return reasoning
    return _int_from_any(usage.get("reasoning_tokens"))


def _int_from_any(value: Any) -> int | None:
    if isinstance(value, bool):
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _budget_detail_summary(detail: dict[str, Any]) -> dict[str, Any]:
    keys = (
        "context_hard_limit_tokens",
        "current_input_tokens",
        "max_input_tokens",
        "total_input_tokens",
        "total_uncached_input_tokens",
        "response_span_count",
        "raw_fpv_candidate_budget",
        "raw_fpv_repeated_failure_limit",
        "max_observe_per_waypoint",
        "candidate_attempt_count",
        "observe_over_budget_by_waypoint",
        "reasons",
    )
    return {key: detail[key] for key in keys if key in detail}


def _model_input_shape_summary(items: list[Any]) -> dict[str, Any]:
    type_counts: dict[str, int] = {}
    key_set_counts: dict[str, int] = {}
    tool_field_counts: dict[str, int] = {}
    output_field_counts: dict[str, int] = {}
    role_counts: dict[str, int] = {}
    for item in items:
        payload = _to_jsonable(item)
        if not isinstance(payload, dict):
            item_type = type(payload).__name__
            type_counts[item_type] = type_counts.get(item_type, 0) + 1
            continue
        item_type = str(payload.get("type") or "<missing>")
        type_counts[item_type] = type_counts.get(item_type, 0) + 1
        key_set = ",".join(sorted(str(key) for key in payload.keys()))
        key_set_counts[key_set] = key_set_counts.get(key_set, 0) + 1
        role = str(payload.get("role") or "")
        if role:
            role_counts[role] = role_counts.get(role, 0) + 1
        for key in ("name", "tool", "tool_name", "call_id", "id"):
            if key in payload:
                tool_field_counts[key] = tool_field_counts.get(key, 0) + 1
        for key in ("output", "content", "result", "error"):
            if key in payload:
                output_field_counts[key] = output_field_counts.get(key, 0) + 1
    return {
        "schema": "openai_agents_model_input_shape_summary_v1",
        "input_item_count": len(items),
        "type_counts": dict(sorted(type_counts.items())),
        "key_set_counts": dict(sorted(key_set_counts.items())),
        "tool_field_counts": dict(sorted(tool_field_counts.items())),
        "output_field_counts": dict(sorted(output_field_counts.items())),
        "role_counts": dict(sorted(role_counts.items())),
        "privacy_note": (
            "Aggregate model-input item shape only. Values, prompts, model text, tool output "
            "bodies, credentials, and private truth are not persisted."
        ),
    }
