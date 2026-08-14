"""Completed tool-call history windowing for OpenAI Agents model input."""

from __future__ import annotations

from typing import Any

from roboclaws.agents.drivers.openai_agents_event_projection import _json_size_bytes, _to_jsonable
from roboclaws.agents.drivers.openai_agents_grounded_history import _tool_names_by_call_id


def _prepare_model_input_history(
    items: list[Any],
    *,
    completed_tool_history_limit: int,
) -> tuple[list[Any], dict[str, Any], int, int]:
    original_item_count = len(items)
    original_input_bytes = sum(_json_size_bytes(item) for item in items)
    windowed, metrics = _window_completed_tool_history(
        items,
        completed_tool_history_limit=completed_tool_history_limit,
    )
    return windowed, metrics, original_item_count, original_input_bytes


def _window_completed_tool_history(
    items: list[Any],
    *,
    completed_tool_history_limit: int,
) -> tuple[list[Any], dict[str, Any]]:
    metrics = {
        "completed_tool_history_limit": max(0, completed_tool_history_limit),
        "completed_tool_history_bundle_count": 0,
        "completed_tool_history_retained_count": 0,
        "completed_tool_history_evicted_count": 0,
        "completed_tool_history_item_count_before": len(items),
        "completed_tool_history_item_count_after": len(items),
        "completed_tool_history_bytes_reduced": 0,
    }
    if completed_tool_history_limit <= 0:
        return items, metrics

    payloads, call_indices, completed_ids, metric_map_call_ids = _completed_tool_history_state(
        items
    )
    ordered_completed_ids = sorted(
        completed_ids,
        key=lambda call_id: max(call_indices.get(call_id) or [-1]),
    )
    recent_ids = set(ordered_completed_ids[-completed_tool_history_limit:])
    incomplete_ids = set(call_indices) - completed_ids
    retained_ids = recent_ids | incomplete_ids | metric_map_call_ids
    recent_indices = [
        index for call_id in recent_ids | incomplete_ids for index in call_indices.get(call_id, [])
    ]
    cutoff = _completed_tool_history_cutoff(
        payloads,
        min(recent_indices) if recent_indices else len(items),
    )

    retained = [
        item
        for index, (item, payload) in enumerate(zip(items, payloads, strict=True))
        if _retain_completed_tool_history_item(
            index,
            payload,
            retained_ids=retained_ids,
            cutoff=cutoff,
        )
    ]

    metrics.update(
        {
            "completed_tool_history_bundle_count": len(completed_ids),
            "completed_tool_history_retained_count": len(completed_ids & retained_ids),
            "completed_tool_history_evicted_count": len(completed_ids - retained_ids),
            "completed_tool_history_item_count_after": len(retained),
            "completed_tool_history_bytes_reduced": max(
                0,
                sum(_json_size_bytes(item) for item in items)
                - sum(_json_size_bytes(item) for item in retained),
            ),
        }
    )
    return retained, metrics


def _completed_tool_history_cutoff(payloads: list[Any], cutoff: int) -> int:
    while cutoff > 0:
        previous = payloads[cutoff - 1]
        if not isinstance(previous, dict) or str(previous.get("type") or "") != "reasoning":
            break
        cutoff -= 1
    return cutoff


def _completed_tool_history_state(
    items: list[Any],
) -> tuple[list[Any], dict[str, list[int]], set[str], set[str]]:
    payloads = [_to_jsonable(item) for item in items]
    call_indices: dict[str, list[int]] = {}
    call_item_ids: set[str] = set()
    output_item_ids: set[str] = set()
    metric_map_call_ids: set[str] = set()
    tool_names = _tool_names_by_call_id(items)
    for index, payload in enumerate(payloads):
        if not isinstance(payload, dict):
            continue
        call_id = str(payload.get("call_id") or "")
        if not call_id:
            continue
        call_indices.setdefault(call_id, []).append(index)
        item_type = str(payload.get("type") or "")
        if item_type in {"function_call", "computer_call", "mcp_call"}:
            call_item_ids.add(call_id)
        if item_type in {"function_call_output", "computer_call_output", "mcp_approval_response"}:
            output_item_ids.add(call_id)
        if str(tool_names.get(call_id) or "") == "metric_map":
            metric_map_call_ids.add(call_id)
    return payloads, call_indices, call_item_ids & output_item_ids, metric_map_call_ids


def _retain_completed_tool_history_item(
    index: int,
    payload: Any,
    *,
    retained_ids: set[str],
    cutoff: int,
) -> bool:
    payload = payload if isinstance(payload, dict) else {}
    if str(payload.get("role") or "") in {"user", "system", "developer"}:
        return True
    call_id = str(payload.get("call_id") or "")
    if call_id:
        return call_id in retained_ids
    return index >= cutoff
