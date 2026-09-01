"""Model-input compaction for the experimental OpenAI Agents SDK runtime."""

from __future__ import annotations

import copy
import hashlib
import json
from pathlib import Path
from typing import Any

from roboclaws.agents.drivers.openai_agents_budget import (
    OpenAIAgentsBudgetExceededError,
    context_budget_policy,
    openai_agents_budget_failure,
    openai_agents_observe_budget_advisory,
)
from roboclaws.agents.drivers.openai_agents_context_assembler import (
    assemble_context,
    load_checkpoint,
)
from roboclaws.agents.drivers.openai_agents_event_log import (
    _append_model_input_budget_advisory_event,
    _append_model_input_budget_event,
    _append_model_input_filter_event,
)
from roboclaws.agents.drivers.openai_agents_event_projection import (
    _json_size_bytes,
    _stable_item_hash,
    _to_jsonable,
)
from roboclaws.agents.drivers.openai_agents_grounded_history import (
    _camera_grounded_history_candidate,
    _camera_grounded_history_plan,
    _camera_grounded_history_policy,
    _decode_tool_output_payload,
    _is_metric_map_tool_output,
    _new_camera_grounded_history_metrics,
    _tool_names_by_call_id,
)
from roboclaws.agents.drivers.openai_agents_history import _prepare_model_input_history
from roboclaws.agents.drivers.openai_agents_image_memory import (
    _new_raw_fpv_image_memory_metrics,
    _raw_fpv_image_memory_candidate,
    _raw_fpv_image_memory_plan,
    _raw_fpv_image_memory_policy,
)
from roboclaws.agents.drivers.openai_agents_input_config import (
    DEFAULT_MODEL_INPUT_COMPACTION_MIN_CHARS,
)
from roboclaws.agents.live_status import LiveAgentFailure

MAX_RETAINED_METRIC_MAP_CHARS = 128_000


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
        assembled_items = original_items
        checkpoint_path = run_dir / "checkpoint.json"
        policy = context_budget_policy(
            budget_profile or {},
            evidence_lane=str((budget_timing or {}).get("evidence_lane") or ""),
        )
        if policy is not None and checkpoint_path.exists():
            assembled = assemble_context(
                load_checkpoint(checkpoint_path),
                fixed_instructions=instructions,
                recent_raw=original_items,
                policy=policy,
            )
            if not assembled.admitted:
                raise OpenAIAgentsBudgetExceededError(
                    LiveAgentFailure(
                        "provider_context_budget_exceeded",
                        retryable=False,
                        resume_available=False,
                        detail=json.dumps(
                            {
                                "schema": "agent_sdk_context_budget_terminal_v1",
                                "estimated_input_tokens": assembled.estimated_input_tokens,
                                "expected_output_tokens": assembled.expected_output_tokens,
                                "safety_reserve_tokens": assembled.safety_reserve_tokens,
                                "context_hard_limit_tokens": assembled.hard_limit_tokens,
                            },
                            sort_keys=True,
                        ),
                    )
                )
            assembled_items = assembled.items
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
                input_items=assembled_items,
                instructions=instructions,
            )
        filtered_items, metrics = _compact_model_input_items(
            assembled_items,
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
            completed_tool_history_limit=int(config.get("completed_tool_history_limit") or 0),
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
    if config.get("enabled") or int(config.get("completed_tool_history_limit") or 0) > 0:
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
    spans_path = events_path.with_name(events_path.name.replace("events", "spans", 1))
    failure = openai_agents_budget_failure(
        run_dir,
        timing,
        profile,
        context_spans_path=spans_path,
    )
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
    completed_tool_history_limit: int = 0,
) -> tuple[list[Any], dict[str, Any]]:
    items, history_metrics, original_item_count, original_input_bytes = (
        _prepare_model_input_history(
            items,
            completed_tool_history_limit=completed_tool_history_limit,
        )
    )
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
    camera_metrics, latest_tool_output_index = (
        _new_camera_grounded_history_metrics(camera_policy),
        _latest_oversized_tool_output_index(items, min_chars=min_chars),
    )
    filtered: list[Any] = []
    items_seen: dict[str, int] = {}
    metric_map_seen = False
    metric_map_output_count = 0
    repeated_metric_map_output_count = 0
    metric_map_delta_compacted_count = 0
    oversized_metric_map_compacted_count = 0
    metric_map_bytes_before = 0
    metric_map_bytes_after = 0
    input_bytes_before = original_input_bytes
    input_bytes_after = 0
    compacted_count = 0
    for index, item in enumerate(items):
        item_bytes = _json_size_bytes(item)
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
                preserve_generic_output=index == latest_tool_output_index,
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
            elif candidate_kind == "oversized_metric_map_snapshot":
                oversized_metric_map_compacted_count += 1
        filtered.append(filtered_item)
        filtered_item_bytes = _json_size_bytes(filtered_item)
        input_bytes_after += filtered_item_bytes
        if _is_metric_map_tool_output(item, tool_names_by_call_id=tool_names_by_call_id):
            metric_map_bytes_after += filtered_item_bytes
    return filtered, {
        "schema": "agent_sdk_model_input_compaction_metrics_v1",
        "input_item_count": original_item_count,
        "compacted_item_count": compacted_count,
        "unchanged_item_count": len(items) - compacted_count,
        "repeated_item_count": sum(count - 1 for count in items_seen.values() if count > 1),
        "input_bytes_before": input_bytes_before,
        "input_bytes_after": input_bytes_after,
        "input_bytes_reduced": max(0, input_bytes_before - input_bytes_after),
        "metric_map_output_count": metric_map_output_count,
        "repeated_metric_map_output_count": repeated_metric_map_output_count,
        "metric_map_delta_compacted_count": metric_map_delta_compacted_count,
        "oversized_metric_map_compacted_count": oversized_metric_map_compacted_count,
        "metric_map_bytes_before": metric_map_bytes_before,
        "metric_map_bytes_after": metric_map_bytes_after,
        "metric_map_bytes_reduced": max(0, metric_map_bytes_before - metric_map_bytes_after),
        **image_metrics,
        **camera_metrics,
        **history_metrics,
    }


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


def _oversized_metric_map_snapshot_summary(
    output_text: str,
    *,
    item_type: str,
) -> dict[str, Any]:
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
        "schema": "roboclaws_oversized_metric_map_snapshot_v1",
        "item_type": item_type,
        "original_chars": len(output_text),
        "original_sha256": hashlib.sha256(output_text.encode("utf-8")).hexdigest(),
        "map_id": str(metric_map.get("map_id") or ""),
        "map_version": str(metric_map.get("map_version") or ""),
        "mode": str(metric_map.get("mode") or ""),
        "inspection_waypoints": _compact_public_rows(
            metric_map.get("inspection_waypoints"),
            keys=(
                "waypoint_id",
                "room_id",
                "room_label",
                "label",
                "category",
                "actionability",
                "target_actionability_status",
                "verified_navigation",
            ),
            limit=64,
        ),
        "public_semantic_anchors": _compact_public_rows(
            runtime_map.get("public_semantic_anchors") or metric_map.get("public_semantic_anchors"),
            keys=(
                "anchor_id",
                "anchor_type",
                "category",
                "label",
                "waypoint_id",
                "room_id",
                "actionability",
                "recommended_tool",
            ),
            limit=64,
        ),
        "observed_objects": _compact_public_rows(
            runtime_map.get("observed_objects"),
            keys=(
                "candidate_id",
                "object_id",
                "category",
                "waypoint_id",
                "room_id",
                "candidate_state",
                "actionability",
                "actionability_status",
                "target_actionability_status",
                "localization_status",
                "required_tool",
                "source_observation_id",
            ),
            limit=64,
        ),
        "target_candidates": _compact_public_rows(
            runtime_map.get("target_candidates"),
            keys=(
                "candidate_id",
                "object_id",
                "category",
                "waypoint_id",
                "room_id",
                "candidate_state",
                "actionability",
                "actionability_status",
                "target_actionability_status",
                "localization_status",
                "source_observation_id",
                "required_tool",
                "candidate_fixture_id",
                "candidate_fixture_category",
                "recommended_tool",
                "destination_options",
            ),
            limit=64,
        ),
        "cleanup_worklist_summary": runtime_map.get("cleanup_worklist_summary")
        or metric_map.get("cleanup_worklist_summary")
        or {},
        "summary": (
            "Oversized current metric_map projected to actionable public fields before this "
            "SDK model call. Use metric_map again only when a missing public field is required; "
            "Roboclaws trace/report artifacts retain the complete response."
        ),
        "private_artifact_policy": (
            "model-facing public metric-map projection only; no private scorer truth is added"
        ),
    }


def _compact_public_rows(
    value: Any,
    *,
    keys: tuple[str, ...],
    limit: int,
) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        return []
    rows = []
    for item in value[:limit]:
        if not isinstance(item, dict):
            continue
        row = {key: item[key] for key in keys if key in item}
        if row:
            rows.append(row)
    return rows


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


def _append_event(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(payload, sort_keys=True) + "\n")


def _compaction_candidate(
    item: Any,
    *,
    min_chars: int,
    metric_map_seen: bool,
    preserve_generic_output: bool,
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
        if len(output_text) <= MAX_RETAINED_METRIC_MAP_CHARS:
            return None, ""
        compacted = copy.deepcopy(payload)
        summary = json.dumps(
            _oversized_metric_map_snapshot_summary(output_text, item_type=item_type),
            sort_keys=True,
        )
        if len(summary) < len(output_text):
            compacted[output_key] = summary
            return compacted, "oversized_metric_map_snapshot"
    if repeated_metric_map_delta and metric_map_seen and is_metric_map_output:
        compacted = copy.deepcopy(payload)
        summary = json.dumps(
            _repeated_metric_map_delta_summary(output_text, item_type=item_type),
            sort_keys=True,
        )
        if len(summary) < len(output_text):
            compacted[output_key] = summary
            return compacted, "repeated_metric_map_delta"
    if preserve_generic_output or not public_tool_output_summary or len(output_text) < min_chars:
        return None, ""
    compacted = copy.deepcopy(payload)
    compacted[output_key] = json.dumps(
        _public_tool_output_summary(output_text, item_type=item_type),
        sort_keys=True,
    )
    return compacted, "generic_public_tool_output_summary"


def _latest_oversized_tool_output_index(items: list[Any], *, min_chars: int) -> int | None:
    for index in range(len(items) - 1, -1, -1):
        payload = _to_jsonable(items[index])
        if not isinstance(payload, dict):
            continue
        if str(payload.get("type") or "") not in {
            "function_call_output",
            "computer_call_output",
            "mcp_call",
            "mcp_approval_response",
        }:
            continue
        output_key = "output" if "output" in payload else "content" if "content" in payload else ""
        if not output_key:
            continue
        output = payload.get(output_key)
        output_text = output if isinstance(output, str) else json.dumps(output, sort_keys=True)
        if len(output_text) >= min_chars:
            return index
    return None
