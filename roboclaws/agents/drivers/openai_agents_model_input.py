"""Model-input compaction for the experimental OpenAI Agents SDK runtime."""

from __future__ import annotations

import copy
import hashlib
import json
import os
import re
import time
from pathlib import Path
from typing import Any

from roboclaws.agents.drivers.openai_agents_budget import (
    OpenAIAgentsBudgetExceededError,
    openai_agents_budget_failure,
    openai_agents_observe_budget_advisory,
)
from roboclaws.agents.live_runtime import LiveAgentRequest
from roboclaws.core.json_sources import parse_json_object_text

DEFAULT_MODEL_INPUT_COMPACTION_MIN_CHARS = 1200
MODEL_INPUT_COMPACTION_MIN_CHARS_ENV = "ROBOCLAWS_OPENAI_AGENTS_INPUT_COMPACTION_MIN_CHARS"
RAW_FPV_OBSERVATION_ID_RE = re.compile(r"raw_fpv_\d+")


def _input_compaction_config(request: LiveAgentRequest) -> dict[str, Any]:
    metadata = dict(request.metadata)
    profile = metadata.get("agent_sdk_perf_profile")
    config = profile.get("model_input_compaction") if isinstance(profile, dict) else None
    if not isinstance(config, dict):
        config = metadata.get("model_input_compaction")
    if not isinstance(config, dict):
        config = {}
    enabled = _bool_setting(config.get("enabled"), "model_input_compaction.enabled", default=False)
    mode = str(config.get("mode") or ("public_tool_result_summary_v1" if enabled else "off"))
    min_chars = _positive_int_from_value_or_env(
        config.get("min_chars"),
        env_name=MODEL_INPUT_COMPACTION_MIN_CHARS_ENV,
        default=DEFAULT_MODEL_INPUT_COMPACTION_MIN_CHARS,
        setting_name="model_input_compaction.min_chars",
    )
    payload = {
        "schema": "agent_sdk_model_input_compaction_v1",
        "enabled": enabled,
        "mode": mode,
        "min_chars": min_chars,
        "private_artifact_policy": (
            "filter is model-facing only; MCP traces, reports, and run artifacts remain complete"
        ),
    }
    raw_fpv_image_memory = config.get("raw_fpv_image_memory")
    if isinstance(raw_fpv_image_memory, dict):
        payload["raw_fpv_image_memory"] = _raw_fpv_image_memory_policy(raw_fpv_image_memory)
    camera_grounded_history = config.get("camera_grounded_history")
    if isinstance(camera_grounded_history, dict):
        payload["camera_grounded_history"] = _camera_grounded_history_policy(
            camera_grounded_history
        )
    return payload


def _bool_setting(value: Any, setting_name: str, *, default: bool) -> bool:
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    if value == "":
        return default
    true_values = {"1", "true", "yes", "on"}
    false_values = {"0", "false", "no", "off"}
    if (normalized := str(value).strip().lower()) in true_values | false_values:
        return normalized in true_values
    raise ValueError(
        f"OpenAI Agents SDK setting {setting_name} must be true or false, got {value!r}"
    )


def _positive_int(
    value: Any,
    *,
    default: int,
    setting_name: str,
    env_name: str | None = None,
) -> int:
    source_name = env_name or f"OpenAI Agents SDK setting {setting_name}"
    if value is None or value == "":
        return default
    if isinstance(value, bool):
        raise ValueError(f"{source_name} must be a positive integer, got {value!r}")
    try:
        parsed = int(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{source_name} must be a positive integer, got {value!r}") from exc
    if parsed < 1:
        raise ValueError(f"{source_name} must be a positive integer, got {value!r}")
    return parsed


def _model_input_compaction_filter(
    events_path: Path,
    *,
    run_dir: Path,
    runtime_config: dict[str, Any],
    config: dict[str, Any],
    budget_profile: dict[str, Any] | None = None,
    budget_timing: dict[str, Any] | None = None,
) -> Any:
    async def _filter(data: Any) -> Any:
        model_data = getattr(data, "model_data", None)
        original_items = getattr(model_data, "input", None)
        instructions = getattr(model_data, "instructions", None)
        if not isinstance(original_items, list):
            return model_data
        _raise_budget_failure_before_model_call(
            run_dir,
            events_path=events_path,
            runtime_config=runtime_config,
            profile=budget_profile or {},
            timing=budget_timing or {},
        )
        budget_advisory = _observe_budget_advisory_before_model_call(
            run_dir,
            events_path=events_path,
            runtime_config=runtime_config,
            profile=budget_profile or {},
            timing=budget_timing or {},
        )
        instructions = _instructions_with_observe_budget_advisory(instructions, budget_advisory)
        if not _model_input_compaction_enabled(config):
            if budget_advisory is None:
                return model_data
            return _model_input_data_like(
                model_data,
                input_items=original_items,
                instructions=instructions,
            )
        filtered_items, metrics = _compact_model_input_items(
            original_items,
            min_chars=int(config.get("min_chars") or DEFAULT_MODEL_INPUT_COMPACTION_MIN_CHARS),
            public_tool_output_summary="public_tool_result_summary_v1"
            in str(config.get("mode") or ""),
            repeated_metric_map_delta="repeated_metric_map_delta_v1"
            in str(config.get("mode") or ""),
            raw_fpv_image_memory=config.get("raw_fpv_image_memory")
            if isinstance(config.get("raw_fpv_image_memory"), dict)
            else None,
            camera_grounded_history=config.get("camera_grounded_history")
            if isinstance(config.get("camera_grounded_history"), dict)
            else None,
        )
        _append_model_input_filter_event(
            events_path,
            runtime_config=runtime_config,
            config=config,
            metrics=metrics,
            input_items=original_items,
        )
        return _model_input_data_like(
            model_data,
            input_items=filtered_items,
            instructions=instructions,
        )

    return _filter


def _model_input_compaction_enabled(config: dict[str, Any]) -> bool:
    if config.get("enabled"):
        return True
    for key in ("raw_fpv_image_memory", "camera_grounded_history"):
        nested = config.get(key)
        if isinstance(nested, dict) and nested.get("enabled"):
            return True
    return False


def _raise_budget_failure_before_model_call(
    run_dir: Path,
    *,
    events_path: Path,
    runtime_config: dict[str, Any],
    profile: dict[str, Any],
    timing: dict[str, Any],
) -> None:
    failure = openai_agents_budget_failure(run_dir, timing, profile)
    if failure is None:
        return
    _append_model_input_budget_event(
        events_path,
        runtime_config=runtime_config,
        profile=profile,
        timing=timing,
        failure=failure,
    )
    raise OpenAIAgentsBudgetExceededError(failure)


def _observe_budget_advisory_before_model_call(
    run_dir: Path,
    *,
    events_path: Path,
    runtime_config: dict[str, Any],
    profile: dict[str, Any],
    timing: dict[str, Any],
) -> dict[str, Any] | None:
    advisory = openai_agents_observe_budget_advisory(run_dir, timing, profile)
    if advisory is None:
        return None
    _append_model_input_budget_advisory_event(
        events_path,
        runtime_config=runtime_config,
        advisory=advisory,
    )
    return advisory


def _instructions_with_observe_budget_advisory(
    instructions: Any,
    advisory: dict[str, Any] | None,
) -> Any:
    if advisory is None or not isinstance(instructions, (str, type(None))):
        return instructions
    observe_budget = int(advisory.get("max_observe_per_waypoint") or 0)
    over_budget = advisory.get("observe_over_budget_by_waypoint")
    counts = over_budget if isinstance(over_budget, dict) else {}
    waypoint_summary = ", ".join(
        f"{waypoint_id} (count={count})" for waypoint_id, count in sorted(counts.items())[:12]
    )
    note = (
        "Observation cadence advisory: the following public waypoint_id values have "
        f"exceeded the preferred limit of {observe_budget} successful observe response(s): "
        f"{waypoint_summary}. Continue the task instead of terminating. Reuse existing "
        "evidence, navigate to another waypoint, or record public ambiguity. Re-observe one "
        "of these waypoint_ids only after a public tool requests it or a successful camera, "
        "pose, or world-state change can produce materially new evidence; otherwise call done "
        "when the task contract is satisfied."
    )
    if not instructions:
        return note
    return f"{instructions.rstrip()}\n\n{note}"


def _model_input_data_like(model_data: Any, *, input_items: list[Any], instructions: Any) -> Any:
    cls = model_data.__class__
    try:
        return cls(input=input_items, instructions=instructions)
    except Exception:
        try:
            from agents.run_config import ModelInputData  # type: ignore[import-not-found]

            return ModelInputData(input=input_items, instructions=instructions)
        except Exception:
            return type(
                "_RoboclawsModelInputData",
                (),
                {"input": input_items, "instructions": instructions},
            )()


def _compact_model_input_items(
    items: list[Any],
    *,
    min_chars: int,
    public_tool_output_summary: bool = True,
    repeated_metric_map_delta: bool = True,
    raw_fpv_image_memory: dict[str, Any] | None = None,
    camera_grounded_history: dict[str, Any] | None = None,
) -> tuple[list[Any], dict[str, Any]]:
    image_policy = _raw_fpv_image_memory_policy(raw_fpv_image_memory)
    image_plan = _raw_fpv_image_memory_plan(items, image_policy)
    image_metrics = _new_raw_fpv_image_memory_metrics(image_policy)
    camera_policy = _camera_grounded_history_policy(camera_grounded_history)
    tool_names_by_call_id = _tool_names_by_call_id(items)
    camera_plan = _camera_grounded_history_plan(
        items,
        camera_policy,
        tool_names_by_call_id=tool_names_by_call_id,
    )
    camera_metrics = _new_camera_grounded_history_metrics(camera_policy)
    filtered: list[Any] = []
    items_seen: dict[str, int] = {}
    metric_map_seen = False
    metric_map_output_count = 0
    repeated_metric_map_output_count = 0
    metric_map_delta_compacted_count = 0
    metric_map_bytes_before = 0
    metric_map_bytes_after = 0
    input_bytes_before = 0
    input_bytes_after = 0
    compacted_count = 0
    for index, item in enumerate(items):
        item_bytes = _json_size_bytes(item)
        input_bytes_before += item_bytes
        image_info = image_plan.get(index)
        if image_info is not None:
            candidate, candidate_kind = _raw_fpv_image_memory_candidate(
                item,
                image_info=image_info,
                policy=image_policy,
                metrics=image_metrics,
            )
        elif (camera_info := camera_plan.get(index)) is not None:
            candidate, candidate_kind = _camera_grounded_history_candidate(
                item,
                camera_info=camera_info,
                policy=camera_policy,
                metrics=camera_metrics,
            )
        else:
            candidate, candidate_kind = _compaction_candidate(
                item,
                min_chars=min_chars,
                metric_map_seen=metric_map_seen,
                public_tool_output_summary=public_tool_output_summary,
                repeated_metric_map_delta=repeated_metric_map_delta,
                tool_names_by_call_id=tool_names_by_call_id,
            )
        if _is_metric_map_tool_output(item, tool_names_by_call_id=tool_names_by_call_id):
            metric_map_output_count += 1
            metric_map_bytes_before += item_bytes
            if metric_map_seen:
                repeated_metric_map_output_count += 1
            metric_map_seen = True
        item_hash = _stable_item_hash(item)
        items_seen[item_hash] = items_seen.get(item_hash, 0) + 1
        if candidate is None:
            filtered_item = item
        else:
            filtered_item = candidate
            compacted_count += 1
            if candidate_kind == "repeated_metric_map_delta":
                metric_map_delta_compacted_count += 1
        filtered.append(filtered_item)
        filtered_item_bytes = _json_size_bytes(filtered_item)
        input_bytes_after += filtered_item_bytes
        if _is_metric_map_tool_output(item, tool_names_by_call_id=tool_names_by_call_id):
            metric_map_bytes_after += filtered_item_bytes
    return filtered, {
        "schema": "agent_sdk_model_input_compaction_metrics_v1",
        "input_item_count": len(items),
        "compacted_item_count": compacted_count,
        "unchanged_item_count": len(items) - compacted_count,
        "repeated_item_count": sum(count - 1 for count in items_seen.values() if count > 1),
        "input_bytes_before": input_bytes_before,
        "input_bytes_after": input_bytes_after,
        "input_bytes_reduced": max(0, input_bytes_before - input_bytes_after),
        "metric_map_output_count": metric_map_output_count,
        "repeated_metric_map_output_count": repeated_metric_map_output_count,
        "metric_map_delta_compacted_count": metric_map_delta_compacted_count,
        "metric_map_bytes_before": metric_map_bytes_before,
        "metric_map_bytes_after": metric_map_bytes_after,
        "metric_map_bytes_reduced": max(0, metric_map_bytes_before - metric_map_bytes_after),
        **image_metrics,
        **camera_metrics,
    }


def _compaction_candidate(
    item: Any,
    *,
    min_chars: int,
    metric_map_seen: bool,
    public_tool_output_summary: bool,
    repeated_metric_map_delta: bool,
    tool_names_by_call_id: dict[str, str] | None = None,
) -> tuple[Any | None, str]:
    payload = _to_jsonable(item)
    if not isinstance(payload, dict):
        return None, ""
    item_type = str(payload.get("type") or "")
    if item_type not in {
        "function_call_output",
        "computer_call_output",
        "mcp_call",
        "mcp_approval_response",
    }:
        return None, ""
    output_key = "output" if "output" in payload else "content" if "content" in payload else ""
    if not output_key:
        return None, ""
    output = payload.get(output_key)
    output_text = output if isinstance(output, str) else json.dumps(output, sort_keys=True)
    is_metric_map_output = _is_metric_map_tool_output(
        payload,
        tool_names_by_call_id=tool_names_by_call_id,
    )
    if repeated_metric_map_delta and is_metric_map_output and not metric_map_seen:
        return None, ""
    if repeated_metric_map_delta and metric_map_seen and is_metric_map_output:
        compacted = copy.deepcopy(payload)
        summary = json.dumps(
            _repeated_metric_map_delta_summary(output_text, item_type=item_type),
            sort_keys=True,
        )
        if len(summary) < len(output_text):
            compacted[output_key] = summary
            return compacted, "repeated_metric_map_delta"
    if not public_tool_output_summary or len(output_text) < min_chars:
        return None, ""
    compacted = copy.deepcopy(payload)
    compacted[output_key] = json.dumps(
        _public_tool_output_summary(output_text, item_type=item_type),
        sort_keys=True,
    )
    return compacted, "generic_public_tool_output_summary"


def _raw_fpv_image_memory_policy(config: dict[str, Any] | None) -> dict[str, Any]:
    config = config if isinstance(config, dict) else {}
    enabled = _bool_setting(config.get("enabled"), "raw_fpv_image_memory.enabled", default=False)
    if enabled:
        retained = _positive_int(
            config.get("retained_full_frame_limit"),
            default=1,
            setting_name="raw_fpv_image_memory.retained_full_frame_limit",
        )
    else:
        retained = 0
    return {
        "schema": "agent_sdk_raw_fpv_image_memory_policy_v1",
        "enabled": enabled,
        "mode": str(config.get("mode") or ("retain_latest_full_frame" if enabled else "off")),
        "retained_full_frame_limit": retained,
        "summary_kind": "raw_fpv_evicted_image_frame_summary_v1",
        "candidate_ids": ["AA"] if enabled else [],
        "private_artifact_policy": (
            "model-facing raw-FPV image memory only; MCP traces, reports, and image artifacts "
            "remain complete"
        ),
    }


def _new_raw_fpv_image_memory_metrics(policy: dict[str, Any]) -> dict[str, Any]:
    return {
        "raw_fpv_image_memory_enabled": bool(policy.get("enabled")),
        "raw_fpv_image_memory_mode": str(policy.get("mode") or "off"),
        "raw_fpv_image_retained_limit": int(policy.get("retained_full_frame_limit") or 0),
        "raw_fpv_image_item_count": 0,
        "raw_fpv_image_retained_count": 0,
        "raw_fpv_image_evicted_count": 0,
        "raw_fpv_image_bytes_before": 0,
        "raw_fpv_image_bytes_after": 0,
        "raw_fpv_image_bytes_reduced": 0,
    }


def _raw_fpv_image_memory_plan(
    items: list[Any],
    policy: dict[str, Any],
) -> dict[int, dict[str, Any]]:
    if not policy.get("enabled"):
        return {}
    candidates = []
    last_observation_id = ""
    for index, item in enumerate(items):
        item_text = json.dumps(_to_jsonable(item), sort_keys=True)
        matches = RAW_FPV_OBSERVATION_ID_RE.findall(item_text)
        if matches:
            last_observation_id = matches[-1]
        info = _raw_fpv_image_info(item)
        if info is not None:
            if not info.get("observation_id"):
                info["observation_id"] = last_observation_id
            candidates.append((index, info))
    retain_limit = int(policy.get("retained_full_frame_limit") or 0)
    retained = {index for index, _info in candidates[-retain_limit:]} if retain_limit > 0 else set()
    return {
        index: {
            **info,
            "retain_full_frame": index in retained,
        }
        for index, info in candidates
    }


def _raw_fpv_image_info(item: Any) -> dict[str, Any] | None:
    payload = _to_jsonable(item)
    if not isinstance(payload, dict):
        return None
    data = payload.get("data")
    if isinstance(data, (bytes, bytearray)):
        data_len = len(data)
    else:
        data_text = str(data or "")
        data_len = len(data_text.encode("utf-8")) if data_text else 0
    if data_len <= 0:
        return None
    mime = str(payload.get("_mime_type") or payload.get("mime_type") or payload.get("mime") or "")
    fmt = str(payload.get("_format") or payload.get("format") or "")
    if "image" not in mime and fmt.lower() not in {"png", "jpg", "jpeg", "webp"}:
        return None
    material = json.dumps(payload, sort_keys=True).encode("utf-8")
    text = material.decode("utf-8", errors="ignore")
    matches = RAW_FPV_OBSERVATION_ID_RE.findall(text)
    observation_id = matches[-1] if matches else ""
    return {
        "observation_id": observation_id,
        "mime_type": mime or (f"image/{fmt.lower()}" if fmt else "image/unknown"),
        "format": fmt,
        "data_bytes": data_len,
        "item_bytes": len(material),
        "sha256": hashlib.sha256(material).hexdigest(),
    }


def _raw_fpv_image_memory_candidate(
    item: Any,
    *,
    image_info: dict[str, Any],
    policy: dict[str, Any],
    metrics: dict[str, Any],
) -> tuple[Any | None, str]:
    metrics["raw_fpv_image_item_count"] += 1
    metrics["raw_fpv_image_bytes_before"] += _json_size_bytes(item)
    if image_info.get("retain_full_frame"):
        metrics["raw_fpv_image_retained_count"] += 1
        metrics["raw_fpv_image_bytes_after"] += _json_size_bytes(item)
        return None, ""
    summary = {
        "schema": "raw_fpv_evicted_image_frame_summary_v1",
        "observation_id": image_info.get("observation_id") or "",
        "mime_type": image_info.get("mime_type") or "",
        "format": image_info.get("format") or "",
        "original_data_bytes": image_info.get("data_bytes") or 0,
        "original_item_bytes": image_info.get("item_bytes") or 0,
        "original_sha256": image_info.get("sha256") or "",
        "retention_policy": {
            "mode": policy.get("mode"),
            "retained_full_frame_limit": policy.get("retained_full_frame_limit"),
        },
        "summary": (
            "Older raw-FPV image frame compacted before this SDK model call. "
            "Use the latest retained frame and current raw-FPV MCP tools for visual work; "
            "Roboclaws trace/report artifacts retain complete image evidence."
        ),
        "private_artifact_policy": policy.get("private_artifact_policy"),
    }
    if _json_size_bytes(summary) >= _json_size_bytes(item):
        metrics["raw_fpv_image_retained_count"] += 1
        metrics["raw_fpv_image_bytes_after"] += _json_size_bytes(item)
        return None, ""
    metrics["raw_fpv_image_evicted_count"] += 1
    metrics["raw_fpv_image_bytes_after"] += _json_size_bytes(summary)
    metrics["raw_fpv_image_bytes_reduced"] = max(
        0,
        metrics["raw_fpv_image_bytes_before"] - metrics["raw_fpv_image_bytes_after"],
    )
    return summary, "raw_fpv_image_memory"


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


def _repeated_metric_map_delta_summary(output_text: str, *, item_type: str) -> dict[str, Any]:
    decoded = _decode_tool_output_payload(output_text)
    metric_map = decoded.get("metric_map") if isinstance(decoded, dict) else None
    if not isinstance(metric_map, dict) and isinstance(decoded, dict):
        metric_map = decoded
    metric_map = metric_map if isinstance(metric_map, dict) else {}
    runtime_map = (
        metric_map.get("runtime_metric_map")
        if isinstance(metric_map.get("runtime_metric_map"), dict)
        else {}
    )
    return {
        "schema": "roboclaws_repeated_metric_map_delta_summary_v1",
        "item_type": item_type,
        "original_chars": len(output_text),
        "original_sha256": hashlib.sha256(output_text.encode("utf-8")).hexdigest(),
        "map_id": str(metric_map.get("map_id") or ""),
        "map_version": str(metric_map.get("map_version") or ""),
        "mode": str(metric_map.get("mode") or ""),
        "inspection_waypoint_count": len(metric_map.get("inspection_waypoints") or []),
        "generated_target_candidate_count": len(
            metric_map.get("generated_target_inspection_candidates") or []
        ),
        "runtime_observed_object_count": len(runtime_map.get("observed_objects") or []),
        "runtime_target_candidate_count": len(runtime_map.get("target_candidates") or []),
        "summary": (
            "Repeated metric_map output compacted before this SDK model call. "
            "Use the current metric_map tool again when full map fields are needed; "
            "Roboclaws trace/report artifacts retain complete tool responses."
        ),
        "private_artifact_policy": (
            "model-facing repeated-map delta only; raw map body is not persisted in "
            "OpenAI Agents SDK events"
        ),
    }


def _public_tool_output_summary(output_text: str, *, item_type: str) -> dict[str, Any]:
    return {
        "schema": "roboclaws_public_tool_output_summary_v1",
        "item_type": item_type,
        "original_chars": len(output_text),
        "original_sha256": hashlib.sha256(output_text.encode("utf-8")).hexdigest(),
        "summary": (
            "Oversized public tool output compacted before this SDK model call. "
            "Use current MCP tools for fresh state; full tool responses remain in "
            "Roboclaws trace/report artifacts."
        ),
    }


def _append_model_input_filter_event(
    events_path: Path,
    *,
    runtime_config: dict[str, Any],
    config: dict[str, Any],
    metrics: dict[str, Any],
    input_items: list[Any] | None = None,
) -> None:
    _append_event(
        events_path,
        _drop_empty(
            {
                "schema": "openai_agents_model_input_filter_v1",
                "event": "model_input_filter",
                "ts_epoch": time.time(),
                "runtime": runtime_config.get("runtime"),
                "provider_profile": runtime_config.get("provider_profile"),
                "wire_api": runtime_config.get("wire_api"),
                "model": runtime_config.get("model"),
                "config": _drop_empty(_to_jsonable(config)),
                "metrics": _drop_empty(_to_jsonable(metrics)),
                "input_shape_summary": _model_input_shape_summary(input_items or []),
                "privacy_note": (
                    "Only aggregate counts, byte sizes, hashes, and policy metadata are persisted. "
                    "Raw prompts, model text, tool payload bodies, credentials, and private truth "
                    "are not stored by this event."
                ),
            }
        ),
    )


def _append_model_input_budget_event(
    events_path: Path,
    *,
    runtime_config: dict[str, Any],
    profile: dict[str, Any],
    timing: dict[str, Any],
    failure: Any,
) -> None:
    detail: dict[str, Any] = {}
    if getattr(failure, "detail", ""):
        try:
            parsed = json.loads(failure.detail)
        except json.JSONDecodeError:
            detail = {"detail_text_sha256": hashlib.sha256(failure.detail.encode()).hexdigest()}
        else:
            detail = parsed if isinstance(parsed, dict) else {}
    _append_event(
        events_path,
        _drop_empty(
            {
                "schema": "openai_agents_model_input_budget_guard_v1",
                "event": "model_input_budget_guard",
                "ts_epoch": time.time(),
                "runtime": runtime_config.get("runtime"),
                "provider_profile": runtime_config.get("provider_profile"),
                "wire_api": runtime_config.get("wire_api"),
                "model": runtime_config.get("model"),
                "profile_id": profile.get("profile_id") or "baseline",
                "evidence_lane": timing.get("evidence_lane") or timing.get("profile") or "",
                "reason": getattr(failure, "reason", ""),
                "retryable": getattr(failure, "retryable", False),
                "resume_available": getattr(failure, "resume_available", False),
                "detail_schema": detail.get("schema"),
                "detail_summary": _budget_detail_summary(detail),
                "privacy_note": (
                    "Aggregate budget guard metadata only. Raw prompts, model text, tool "
                    "payload bodies, image payloads, credentials, and private truth are "
                    "not stored by this event."
                ),
            }
        ),
    )


def _append_model_input_budget_advisory_event(
    events_path: Path,
    *,
    runtime_config: dict[str, Any],
    advisory: dict[str, Any],
) -> None:
    _append_event(
        events_path,
        _drop_empty(
            {
                "schema": "openai_agents_model_input_budget_advisory_v1",
                "event": "model_input_budget_advisory",
                "ts_epoch": time.time(),
                "runtime": runtime_config.get("runtime"),
                "provider_profile": runtime_config.get("provider_profile"),
                "wire_api": runtime_config.get("wire_api"),
                "model": runtime_config.get("model"),
                "profile_id": advisory.get("profile_id"),
                "evidence_lane": advisory.get("evidence_lane"),
                "reason": advisory.get("reason"),
                "detail_schema": advisory.get("schema"),
                "detail_summary": _budget_detail_summary(advisory),
                "privacy_note": (
                    "Public waypoint ids and aggregate observation counts only. Raw prompts, "
                    "model text, tool payload bodies, image payloads, credentials, and private "
                    "truth are not stored by this event."
                ),
            }
        ),
    )


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


def _append_event(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(payload, sort_keys=True) + "\n")


def _positive_int_from_value_or_env(
    value: Any,
    *,
    env_name: str,
    default: int,
    setting_name: str,
) -> int:
    if value is None:
        raw_env = os.environ.get(env_name)
        if raw_env not in {None, ""}:
            return _positive_int(
                raw_env,
                default=default,
                setting_name=setting_name,
                env_name=env_name,
            )
        value = default
    if value == "":
        value = default
    return _positive_int(value, default=default, setting_name=setting_name)


def _drop_empty(payload: dict[str, Any]) -> dict[str, Any]:
    return {key: value for key, value in payload.items() if not _is_empty_json_value(value)}


def _is_empty_json_value(value: Any) -> bool:
    if value is None:
        return True
    if isinstance(value, str) and value == "":
        return True
    if isinstance(value, (list, tuple, dict)) and not value:
        return True
    return False


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
