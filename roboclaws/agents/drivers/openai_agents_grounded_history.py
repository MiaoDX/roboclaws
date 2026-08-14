"""Camera-grounded model-input history retention."""

from __future__ import annotations

import copy
import hashlib
import json
from typing import Any

from roboclaws.agents.drivers.openai_agents_event_projection import (
    _drop_empty,
    _json_size_bytes,
    _to_jsonable,
)
from roboclaws.agents.drivers.openai_agents_setting_values import _bool_setting, _positive_int
from roboclaws.core.json_sources import parse_json_object_text


def _camera_grounded_history_policy(config: dict[str, Any] | None) -> dict[str, Any]:
    config = config if isinstance(config, dict) else {}
    enabled = _bool_setting(config.get("enabled"), "camera_grounded_history.enabled", default=False)
    if enabled:
        retained = _positive_int(
            config.get("retained_recent_outputs"),
            default=4,
            setting_name="camera_grounded_history.retained_recent_outputs",
        )
    else:
        retained = 0
    return {
        "schema": "agent_sdk_camera_grounded_history_policy_v1",
        "enabled": enabled,
        "mode": str(
            config.get("mode") or ("retain_latest_actionable_outputs" if enabled else "off")
        ),
        "retained_recent_outputs": retained,
        "summary_kind": "roboclaws_camera_grounded_history_summary_v1",
        "candidate_ids": ["AC"] if enabled else [],
        "private_artifact_policy": (
            "model-facing camera-grounded history compaction only; MCP traces, reports, "
            "and run artifacts remain complete"
        ),
    }


def _new_camera_grounded_history_metrics(policy: dict[str, Any]) -> dict[str, Any]:
    return {
        "camera_grounded_history_enabled": bool(policy.get("enabled")),
        "camera_grounded_history_mode": str(policy.get("mode") or "off"),
        "camera_grounded_history_retained_limit": int(policy.get("retained_recent_outputs") or 0),
        "camera_grounded_history_item_count": 0,
        "camera_grounded_history_retained_count": 0,
        "camera_grounded_history_compacted_count": 0,
        "camera_grounded_history_bytes_before": 0,
        "camera_grounded_history_bytes_after": 0,
        "camera_grounded_history_bytes_reduced": 0,
    }


def _camera_grounded_history_plan(
    items: list[Any],
    policy: dict[str, Any],
    *,
    tool_names_by_call_id: dict[str, str] | None = None,
) -> dict[int, dict[str, Any]]:
    if not policy.get("enabled"):
        return {}
    tool_names_by_call_id = tool_names_by_call_id or {}
    candidates = [
        (index, info)
        for index, item in enumerate(items)
        if (
            info := _camera_grounded_history_info(
                item,
                tool_names_by_call_id=tool_names_by_call_id,
            )
        )
        is not None
    ]
    retain_limit = int(policy.get("retained_recent_outputs") or 0)
    retained = {index for index, _info in candidates[-retain_limit:]} if retain_limit > 0 else set()
    return {
        index: {
            **info,
            "retain_full_output": index in retained,
        }
        for index, info in candidates
    }


def _tool_names_by_call_id(items: list[Any]) -> dict[str, str]:
    names: dict[str, str] = {}
    for item in items:
        payload = _to_jsonable(item)
        if not isinstance(payload, dict):
            continue
        item_type = str(payload.get("type") or "")
        if item_type not in {"function_call", "mcp_call"}:
            continue
        call_id = str(payload.get("call_id") or "")
        if not call_id:
            continue
        tool = _normalize_mcp_tool_name(
            payload.get("name") or payload.get("tool") or payload.get("tool_name") or ""
        )
        if tool:
            names[call_id] = tool
    return names


def _camera_grounded_history_info(
    item: Any,
    *,
    tool_names_by_call_id: dict[str, str] | None = None,
) -> dict[str, Any] | None:
    payload = _to_jsonable(item)
    if not isinstance(payload, dict):
        return None
    item_type = str(payload.get("type") or "")
    if item_type not in {
        "function_call_output",
        "computer_call_output",
        "mcp_call",
        "mcp_approval_response",
    }:
        return None
    call_id = str(payload.get("call_id") or "")
    tool = _camera_grounded_history_tool(
        payload,
        call_id=call_id,
        tool_names_by_call_id=tool_names_by_call_id,
    )
    output = payload.get("output") if "output" in payload else payload.get("content")
    if output is None:
        return None
    decoded = _decode_tool_output_payload(
        output,
        source_label="OpenAI Agents model-input camera-grounded output",
    )
    decoded = decoded if isinstance(decoded, dict) else {}
    if not tool:
        tool = _normalize_mcp_tool_name(decoded.get("tool") or "")
    if not _camera_grounded_history_tool_allowed(tool, decoded):
        return None
    output_text = output if isinstance(output, str) else json.dumps(output, sort_keys=True)
    raw_fpv_observation = decoded.get("raw_fpv_observation")
    raw_fpv_observation = raw_fpv_observation if isinstance(raw_fpv_observation, dict) else {}
    return {
        "item_type": item_type,
        "tool": tool,
        "output_key": "output" if "output" in payload else "content",
        "output_text": output_text,
        "observation_id": str(
            decoded.get("observation_id") or raw_fpv_observation.get("observation_id") or ""
        ),
        "waypoint_id": str(decoded.get("waypoint_id") or ""),
        "room_id": str(decoded.get("room_id") or decoded.get("current_room_id") or ""),
        "status": str(decoded.get("status") or ""),
        "ok": bool(decoded.get("ok", False)),
        "candidate_count": _camera_grounded_candidate_count(decoded),
        "actionable_candidate_count": _camera_grounded_actionable_candidate_count(decoded),
        "candidate_refs": _camera_grounded_candidate_refs(decoded),
    }


def _camera_grounded_history_tool(
    payload: dict[str, Any],
    *,
    call_id: str,
    tool_names_by_call_id: dict[str, str] | None,
) -> str:
    tool = _normalize_mcp_tool_name(
        (tool_names_by_call_id or {}).get(call_id)
        or payload.get("name")
        or payload.get("tool")
        or payload.get("tool_name")
        or ""
    )
    if tool:
        return tool
    if "observe_camera_grounded_candidates" in call_id:
        return "observe_camera_grounded_candidates"
    if "declare_visual_candidates" in call_id:
        return "declare_visual_candidates"
    if "observe" in call_id:
        return "observe"
    return ""


def _camera_grounded_history_tool_allowed(tool: str, decoded: dict[str, Any]) -> bool:
    if tool not in {"observe_camera_grounded_candidates", "declare_visual_candidates", "observe"}:
        return False
    if tool == "observe":
        return str(decoded.get("perception_mode") or "") == "camera_model_policy"
    if tool == "declare_visual_candidates":
        return (
            "camera_model_candidates" in decoded
            or "model_declared_observations" in decoded
            or "visual_grounding_pipeline" in decoded
        )
    return True


def _normalize_mcp_tool_name(value: Any) -> str:
    tool = str(value or "").strip()
    if "__" in tool:
        tool = tool.rsplit("__", 1)[-1]
    return tool


def _camera_grounded_candidate_count(decoded: dict[str, Any]) -> int:
    for key in ("camera_model_candidates", "model_declared_observations"):
        value = decoded.get(key)
        if isinstance(value, list):
            return len(value)
    declaration = decoded.get("declaration")
    if isinstance(declaration, dict):
        return _camera_grounded_candidate_count(declaration)
    return 0


def _camera_grounded_actionable_candidate_count(decoded: dict[str, Any]) -> int:
    candidates = _camera_grounded_candidates(decoded)
    return sum(
        1
        for candidate in candidates
        if isinstance(candidate, dict)
        and (
            candidate.get("cleanup_recommended") is True
            or str(candidate.get("actionability_status") or "") == "actionable"
            or (
                isinstance(candidate.get("visual_grounding_evidence"), dict)
                and str(candidate["visual_grounding_evidence"].get("candidate_state") or "")
                == "navigation_authorized"
            )
        )
    )


def _camera_grounded_candidates(decoded: dict[str, Any]) -> list[Any]:
    for key in ("camera_model_candidates", "model_declared_observations"):
        value = decoded.get(key)
        if isinstance(value, list):
            return value
    declaration = decoded.get("declaration")
    if isinstance(declaration, dict):
        return _camera_grounded_candidates(declaration)
    return []


def _camera_grounded_candidate_refs(decoded: dict[str, Any]) -> list[dict[str, Any]]:
    refs: list[dict[str, Any]] = []
    for candidate in _camera_grounded_candidates(decoded)[:8]:
        if not isinstance(candidate, dict):
            continue
        evidence = candidate.get("visual_grounding_evidence")
        evidence = evidence if isinstance(evidence, dict) else {}
        refs.append(
            _drop_empty(
                {
                    "object_id": candidate.get("object_id"),
                    "category": candidate.get("category"),
                    "recommended_tool": candidate.get("recommended_tool"),
                    "source_observation_id": candidate.get("source_observation_id")
                    or evidence.get("source_observation_id"),
                    "waypoint_id": candidate.get("waypoint_id"),
                    "room_id": candidate.get("room_id") or candidate.get("current_room_id"),
                    "cleanup_recommended": candidate.get("cleanup_recommended"),
                    "actionability_status": candidate.get("actionability_status"),
                    "candidate_state": evidence.get("candidate_state"),
                }
            )
        )
    return refs


def _camera_grounded_history_candidate(
    item: Any,
    *,
    camera_info: dict[str, Any],
    policy: dict[str, Any],
    metrics: dict[str, Any],
) -> tuple[Any | None, str]:
    original_bytes = _json_size_bytes(item)
    metrics["camera_grounded_history_item_count"] += 1
    metrics["camera_grounded_history_bytes_before"] += original_bytes
    if camera_info.get("retain_full_output"):
        metrics["camera_grounded_history_retained_count"] += 1
        metrics["camera_grounded_history_bytes_after"] += original_bytes
        return None, ""
    output_text = str(camera_info.get("output_text") or "")
    summary = {
        "schema": "roboclaws_camera_grounded_history_summary_v1",
        "item_type": camera_info.get("item_type") or "",
        "tool": camera_info.get("tool") or "",
        "original_chars": len(output_text),
        "original_sha256": hashlib.sha256(output_text.encode("utf-8")).hexdigest(),
        "observation_id": camera_info.get("observation_id") or "",
        "waypoint_id": camera_info.get("waypoint_id") or "",
        "room_id": camera_info.get("room_id") or "",
        "status": camera_info.get("status") or "",
        "ok": bool(camera_info.get("ok")),
        "candidate_count": camera_info.get("candidate_count") or 0,
        "actionable_candidate_count": camera_info.get("actionable_candidate_count") or 0,
        "candidate_refs": camera_info.get("candidate_refs") or [],
        "retention_policy": {
            "mode": policy.get("mode"),
            "retained_recent_outputs": policy.get("retained_recent_outputs"),
        },
        "summary": (
            "Older camera-grounded observation/declaration output compacted before this SDK "
            "model call. Use the latest retained camera-grounded outputs and current MCP "
            "tools for actionable state; Roboclaws trace/report artifacts retain complete "
            "tool responses."
        ),
        "private_artifact_policy": policy.get("private_artifact_policy"),
    }
    if _json_size_bytes(summary) >= original_bytes:
        metrics["camera_grounded_history_retained_count"] += 1
        metrics["camera_grounded_history_bytes_after"] += original_bytes
        return None, ""
    compacted = copy.deepcopy(_to_jsonable(item))
    compacted[str(camera_info.get("output_key") or "output")] = json.dumps(
        _drop_empty(summary),
        sort_keys=True,
    )
    compacted_bytes = _json_size_bytes(compacted)
    metrics["camera_grounded_history_compacted_count"] += 1
    metrics["camera_grounded_history_bytes_after"] += compacted_bytes
    metrics["camera_grounded_history_bytes_reduced"] = max(
        0,
        metrics["camera_grounded_history_bytes_before"]
        - metrics["camera_grounded_history_bytes_after"],
    )
    return compacted, "camera_grounded_history"


def _is_metric_map_tool_output(
    item: Any,
    *,
    tool_names_by_call_id: dict[str, str] | None = None,
) -> bool:
    payload = _to_jsonable(item)
    if not isinstance(payload, dict):
        return False
    if str(payload.get("type") or "") not in {
        "function_call_output",
        "computer_call_output",
        "mcp_call",
        "mcp_approval_response",
    }:
        return False
    for key in ("name", "tool", "tool_name"):
        if str(payload.get(key) or "") == "metric_map":
            return True
    call_id = str(payload.get("call_id") or "")
    if _normalize_mcp_tool_name((tool_names_by_call_id or {}).get(call_id) or "") == "metric_map":
        return True
    if "metric_map" in call_id:
        return True
    output = payload.get("output") if "output" in payload else payload.get("content")
    decoded = _decode_tool_output_payload(output)
    if isinstance(decoded, dict):
        if decoded.get("tool") == "metric_map":
            return True
        nested = decoded.get("metric_map")
        return isinstance(nested, dict) and nested.get("tool") == "metric_map"
    return False


def _decode_tool_output_payload(output: Any, *, source_label: str = "") -> Any:
    if isinstance(output, str):
        try:
            decoded = json.loads(output)
        except json.JSONDecodeError:
            if source_label and _looks_like_json_text(output):
                parse_json_object_text(output, label=source_label)
            return None
        if isinstance(decoded, str):
            try:
                unwrapped = _unwrap_mcp_text_content_payload(
                    json.loads(decoded),
                    source_label=source_label,
                )
            except json.JSONDecodeError as exc:
                if source_label and _looks_like_json_text(decoded):
                    raise ValueError(
                        f"{source_label} source must contain valid JSON object"
                    ) from exc
                return decoded
            if source_label and _looks_like_json_text(decoded) and not isinstance(unwrapped, dict):
                raise ValueError(f"{source_label} source must contain a JSON object")
            return unwrapped
        unwrapped = _unwrap_mcp_text_content_payload(decoded, source_label=source_label)
        if source_label and _looks_like_json_text(output) and not isinstance(unwrapped, dict):
            raise ValueError(f"{source_label} source must contain a JSON object")
        return unwrapped
    return _unwrap_mcp_text_content_payload(output, source_label=source_label)


def _looks_like_json_text(text: str) -> bool:
    stripped = text.strip()
    return bool(stripped) and stripped[0] in "[{"


def _unwrap_mcp_text_content_payload(decoded: Any, *, source_label: str = "") -> Any:
    if isinstance(decoded, dict):
        return _unwrap_mcp_text_content_dict(decoded, source_label=source_label)
    if isinstance(decoded, list):
        return _unwrap_mcp_text_content_list(decoded, source_label=source_label)
    return decoded


def _unwrap_mcp_text_content_dict(decoded: dict[str, Any], *, source_label: str = "") -> Any:
    content = decoded.get("content")
    if isinstance(content, list):
        unwrapped = _unwrap_mcp_text_content_payload(content, source_label=source_label)
        if unwrapped is not content:
            return unwrapped
    text = decoded.get("text")
    if isinstance(text, str) and str(decoded.get("type") or "") in {"", "text"}:
        if source_label and _looks_like_json_text(text):
            return _unwrap_mcp_text_content_payload(
                parse_json_object_text(text, label=f"{source_label} text content"),
                source_label=source_label,
            )
        try:
            return _unwrap_mcp_text_content_payload(json.loads(text), source_label=source_label)
        except json.JSONDecodeError:
            return decoded
    return decoded


def _unwrap_mcp_text_content_list(decoded: list[Any], *, source_label: str = "") -> Any:
    for item in decoded:
        if not isinstance(item, dict):
            continue
        if str(item.get("type") or "") not in {"", "text"}:
            continue
        text = item.get("text")
        if not isinstance(text, str):
            continue
        if source_label and _looks_like_json_text(text):
            return _unwrap_mcp_text_content_payload(
                parse_json_object_text(text, label=f"{source_label} text content"),
                source_label=source_label,
            )
        try:
            return _unwrap_mcp_text_content_payload(json.loads(text), source_label=source_label)
        except json.JSONDecodeError:
            continue
    return decoded
