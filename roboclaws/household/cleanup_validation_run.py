#!/usr/bin/env python3
from __future__ import annotations

from pathlib import Path
from typing import Any

from roboclaws.core.json_sources import read_json_object, read_jsonl_objects
from roboclaws.household.cleanup_validation_support import (
    agent_view_runtime_metric_map as _agent_view_runtime_metric_map,
)
from roboclaws.household.cleanup_validation_support import (
    assert_no_forbidden_keys as _assert_no_forbidden_keys,
)
from roboclaws.household.cleanup_validation_support import (
    resolve_path as _resolve_path,
)
from roboclaws.household.household_runtime_contract import (
    CLEANUP_POLICY_TRACE_SCHEMA,
)
from roboclaws.household.household_runtime_contract import (
    RUNTIME_METRIC_MAP_SCHEMA as RUNTIME_METRIC_MAP_SCHEMA,
)
from roboclaws.household.realworld_runtime_map_targets import (
    LOCALIZATION_STATUS_VIEWPOINT_ONLY,
    POSE_ROLE_BEST_VIEW_POSE,
    POSE_ROLE_INSPECTION_WAYPOINT,
)
from roboclaws.household.semantic_timeline import (
    CANONICAL_SURFACE_CLEANUP_PHASES,
    duplicate_post_place_navigations,
    has_complete_semantic_sequence,
    successful_semantic_phases,
)


def _assert_clean_agent_run(
    data: dict[str, Any],
    *,
    min_complete_count: int | None = None,
) -> None:
    assert data.get("agent_driven") is True, data
    assert data.get("mcp_server") == "household_world", data
    counts = data.get("tool_event_counts") or {}
    for tool in (
        "metric_map",
        "navigate_to_waypoint",
        "observe",
        *CANONICAL_SURFACE_CLEANUP_PHASES,
        "done",
    ):
        request_count = int(counts.get(f"{tool}:request") or 0)
        if tool == "navigate_to_object":
            request_count += int(counts.get("navigate_to_visual_candidate:request") or 0)
        assert request_count >= 1, (tool, counts, data)
    diagnostics = data.get("agent_diagnostics") or {}
    assert diagnostics.get("stale_reference_errors") == 0, data
    assert _unrecovered_semantic_order_error_count(data) == 0, data
    assert int(diagnostics.get("duplicate_post_place_navigation_count") or 0) == 0, data
    assert diagnostics.get("premature_done") is False, data
    assert diagnostics.get("fridge_inside_sequence_ok") is True, data
    required_complete = min_complete_count or int(data.get("generated_mess_count") or 0)
    assert _complete_semantic_substep_count(data) >= required_complete, data


def _unrecovered_semantic_order_error_count(data: dict[str, Any]) -> int:
    diagnostics = data.get("agent_diagnostics") or {}
    if "semantic_order_unrecovered_errors" in diagnostics:
        return int(diagnostics.get("semantic_order_unrecovered_errors") or 0)

    total_errors = int(diagnostics.get("semantic_order_errors") or 0)
    if total_errors == 0:
        return 0

    covered = 0
    unrecovered = 0
    for item in data.get("semantic_substeps") or []:
        steps = item.get("steps", [])
        item_errors = sum(
            1
            for step in steps
            if isinstance(step, dict) and step.get("error_reason") == "semantic_order"
        )
        if item_errors == 0:
            continue
        covered += item_errors
        phases = successful_semantic_phases(steps)
        if not has_complete_semantic_sequence(phases):
            unrecovered += item_errors
    untracked_errors = max(0, total_errors - covered)
    return unrecovered + untracked_errors


def _assert_semantic_acceptability(data: dict[str, Any], min_accepted_count: int) -> None:
    summary = (data.get("score") or {}).get("semantic_acceptability") or {}
    assert summary, data
    assert summary.get("status") == "success", summary
    accepted_count = int(summary.get("accepted_count") or 0)
    assert accepted_count >= min_accepted_count, (accepted_count, min_accepted_count, data)
    accepted_levels = set(summary.get("accepted_levels") or [])
    assert accepted_levels <= {"preferred", "acceptable"}, summary


def _complete_semantic_substep_count(data: dict[str, Any]) -> int:
    complete = 0
    for item in data.get("semantic_substeps") or []:
        phases = successful_semantic_phases(item.get("steps", []))
        if has_complete_semantic_sequence(phases):
            complete += 1
    return complete


def _successful_semantic_phase_set(data: dict[str, Any]) -> set[str]:
    phases: set[str] = set()
    for item in data.get("semantic_substeps") or []:
        phases.update(successful_semantic_phases(item.get("steps", [])))
    return phases


def _assert_goal_contract(data: dict[str, Any], base: Path) -> None:
    contract = data.get("goal_contract") or {}
    assert contract.get("schema") == "roboclaws_goal_contract_v1", data
    assert contract.get("surface"), contract
    assert contract.get("intent"), contract
    assert contract.get("normalized_goal"), contract
    assert contract.get("goal_scope") in {"whole-room", "prompt-scoped", "agent-declared"}, contract
    artifacts = data.get("artifacts") or {}
    path = _resolve_path(base, artifacts.get("goal_contract", ""))
    payload = read_json_object(path, label="goal contract")
    assert payload == contract, (payload, contract)


def _assert_completion_claim(data: dict[str, Any]) -> None:
    claim = data.get("agent_completion_claim") or {}
    assert claim.get("schema") == "roboclaws_agent_completion_claim_v1", data
    for key in ("completion_summary", "why_done", "evidence_used", "remaining_risks"):
        assert key in claim, claim
    assert str(claim["completion_summary"]).strip(), claim
    assert str(claim["why_done"]).strip(), claim
    assert isinstance(claim["evidence_used"], list), claim
    assert isinstance(claim["remaining_risks"], list), claim


def _assert_map_build_did_not_clean(data: dict[str, Any]) -> None:
    counts = data.get("tool_event_counts") or {}
    cleanup_tools = {
        "navigate_to_object",
        "pick",
        "navigate_to_receptacle",
        "open_receptacle",
        "place",
        "place_inside",
        "close_receptacle",
    }
    called = {
        tool: int(counts.get(f"{tool}:request") or 0)
        for tool in cleanup_tools
        if int(counts.get(f"{tool}:request") or 0)
    }
    assert not called, (called, data)


def _assert_runtime_metric_map_quality(runtime_metric_map: dict[str, Any]) -> None:
    anchors = [
        item
        for item in runtime_metric_map.get("public_semantic_anchors") or []
        if isinstance(item, dict)
    ]
    _assert_no_duplicate_current_run_fixture_anchor_viewpoints(anchors)
    for anchor in anchors:
        _assert_runtime_map_pose_contract(anchor, item_kind="public_semantic_anchor")
    for candidate in runtime_metric_map.get("target_candidates") or []:
        if isinstance(candidate, dict):
            _assert_runtime_map_pose_contract(candidate, item_kind="target_candidate")
    for observed in runtime_metric_map.get("observed_objects") or []:
        if isinstance(observed, dict):
            _assert_rgb_only_item_does_not_claim_object_pose(
                observed,
                item_kind="observed_object",
            )


def _assert_no_duplicate_current_run_fixture_anchor_viewpoints(
    anchors: list[dict[str, Any]],
) -> None:
    groups: dict[tuple[str, str, str, str, str], list[str]] = {}
    for anchor in anchors:
        if str(anchor.get("freshness") or "") != "current_run":
            continue
        if str(anchor.get("anchor_type") or "") not in {"fixture", "surface", "receptacle"}:
            continue
        key = _runtime_anchor_viewpoint_key(anchor)
        groups.setdefault(key, []).append(str(anchor.get("anchor_id") or ""))
    duplicates = {key: ids for key, ids in groups.items() if len(set(ids)) > 1}
    assert not duplicates, {
        "duplicate_fixture_anchor_viewpoints": duplicates,
        "hint": (
            "Current-run RGB/map-build fixture anchors must cluster same category, "
            "waypoint, observation, and viewpoint instead of exposing duplicate "
            "independent anchors."
        ),
    }


def _runtime_anchor_viewpoint_key(anchor: dict[str, Any]) -> tuple[str, str, str, str, str]:
    pose = anchor.get("pose") if isinstance(anchor.get("pose"), dict) else {}
    pose_key = ",".join(str(round(_float_or_zero(pose.get(key)), 4)) for key in ("x", "y", "yaw"))
    return (
        str(anchor.get("category") or ""),
        str(anchor.get("room_id") or ""),
        str(anchor.get("waypoint_id") or ""),
        pose_key,
        str(anchor.get("source_observation_id") or ""),
    )


def _assert_runtime_map_pose_contract(item: dict[str, Any], *, item_kind: str) -> None:
    if item.get("pose") is not None:
        assert item.get("pose_source"), {item_kind: item, "missing": "pose_source"}
        assert item.get("pose_role"), {item_kind: item, "missing": "pose_role"}
        assert item.get("localization_status"), {
            item_kind: item,
            "missing": "localization_status",
        }
    producer_type = str(item.get("producer_type") or "")
    if (
        producer_type
        in {
            "external_visual_grounding_service",
            "visible_detection",
            "visible_object_detections",
            "simulated_camera_model",
            "simulated_camera_model_policy",
        }
        and item.get("pose") is not None
    ):
        assert item.get("localization_status") == LOCALIZATION_STATUS_VIEWPOINT_ONLY, item
        if item.get("pose_role"):
            assert item.get("pose_role") in {
                POSE_ROLE_BEST_VIEW_POSE,
                POSE_ROLE_INSPECTION_WAYPOINT,
            }, item
    _assert_rgb_only_item_does_not_claim_object_pose(item, item_kind=item_kind)


def _assert_rgb_only_item_does_not_claim_object_pose(
    item: dict[str, Any],
    *,
    item_kind: str,
) -> None:
    producer_type = str(item.get("producer_type") or "")
    producer_id = str(item.get("producer_id") or "")
    if producer_type in {
        "external_visual_grounding_service",
        "visible_detection",
        "visible_object_detections",
        "simulated_camera_model",
        "simulated_camera_model_policy",
    } or producer_id in {"grounding-dino", "yoloe", "yolo-world", "omdet-turbo"}:
        assert "object_pose" not in item, {
            item_kind: item,
            "reason": (
                "RGB-only current-run map evidence may expose waypoint/viewpoint "
                "pose but not target object map-frame pose."
            ),
        }


def _float_or_zero(value: Any) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


def _assert_adaptive_inspection_thresholds(
    data: dict[str, Any],
    *,
    min_adjust_camera_count: int = 0,
    min_generated_target_inspection_candidates: int = 0,
) -> None:
    counts = data.get("tool_event_counts") or {}
    adjust_count = int(counts.get("adjust_camera:request") or 0)
    assert adjust_count >= min_adjust_camera_count, {
        "actual_adjust_camera_count": adjust_count,
        "min_adjust_camera_count": min_adjust_camera_count,
        "tool_event_counts": counts,
    }
    agent_view = data.get("agent_view") or {}
    runtime_metric_map = data.get("runtime_metric_map") or _agent_view_runtime_metric_map(
        agent_view
    )
    generated = runtime_metric_map.get("generated_target_inspection_candidates") or []
    generated_count = len(generated)
    assert generated_count >= min_generated_target_inspection_candidates, {
        "actual_generated_target_inspection_candidates": generated_count,
        "min_generated_target_inspection_candidates": (min_generated_target_inspection_candidates),
        "runtime_metric_map": runtime_metric_map,
    }


def _assert_map_build_scan_profile(
    data: dict[str, Any],
    *,
    expected_profile: str | None,
    min_body_turn_count: int,
) -> None:
    map_build = data.get("map_build") if isinstance(data.get("map_build"), dict) else {}
    scan_profile = (
        map_build.get("scan_profile") if isinstance(map_build.get("scan_profile"), dict) else {}
    )
    profile_id = str(
        map_build.get("scan_profile_id") or scan_profile.get("profile") or "fixture-focused"
    )
    if expected_profile:
        assert profile_id == expected_profile, {
            "actual_map_build_scan_profile": profile_id,
            "expected_map_build_scan_profile": expected_profile,
            "map_build": map_build,
        }
    counts = data.get("tool_event_counts") or {}
    body_turn_count = int(counts.get("navigate_to_relative_pose:request") or 0)
    assert body_turn_count >= min_body_turn_count, {
        "actual_map_build_body_turn_count": body_turn_count,
        "min_map_build_body_turn_count": min_body_turn_count,
        "tool_event_counts": counts,
        "map_build": map_build,
    }


def _is_map_build(data: dict[str, Any]) -> bool:
    agent_view = data.get("agent_view") or {}
    runtime_metric_map = data.get("runtime_metric_map") or _agent_view_runtime_metric_map(
        agent_view
    )
    return (
        data.get("task_intent") == "map-build"
        or data.get("map_build_mode") is True
        or runtime_metric_map.get("mode") == "map_build"
        or _is_live_map_build(data)
    )


def _is_live_map_build(data: dict[str, Any]) -> bool:
    trace = data.get("cleanup_policy_trace") or {}
    task_identity = {
        str(data.get("task_intent") or ""),
    }
    return (
        "map-build" in task_identity
        and int(trace.get("cleanup_action_count") or 0) == 0
        and str(trace.get("loop_style") or "") in {"scan_only", "household_world_map_build"}
    )


def _assert_live_map_build_scan_only(data: dict[str, Any]) -> None:
    assert data.get("task_intent") == "map-build", data
    trace = data.get("cleanup_policy_trace") or {}
    assert trace.get("schema") == CLEANUP_POLICY_TRACE_SCHEMA, trace
    loop_style = trace.get("loop_style")
    assert loop_style in {"scan_only", "household_world_map_build"}, trace
    assert int(trace.get("cleanup_action_count") or 0) == 0, trace
    if loop_style == "scan_only":
        assert (
            int(trace.get("observed_waypoint_count") or 0)
            >= int(trace.get("total_waypoints") or 0)
            > 0
        ), trace
    else:
        readiness = data.get("real_robot_readiness") or {}
        assert float(readiness.get("observed_waypoint_rate") or 0.0) >= 1.0, readiness
    assert float(data.get("sweep_coverage_rate") or 0.0) >= 1.0, data


def _assert_trace_is_public(trace_path: Path) -> None:
    for payload in _trace_events_from_path(trace_path):
        assert payload.get("tool") != "scene_objects", payload
        if payload.get("tool") == "done":
            continue
        public_payload = _without_internal_proof_evidence(payload)
        _assert_no_forbidden_keys(public_payload)
        response = public_payload.get("response")
        if isinstance(response, dict):
            assert "objects" not in response, response
            assert "scene_objects" not in response, response


def _assert_no_duplicate_post_place_navigation(trace_path: Path) -> None:
    duplicates = duplicate_post_place_navigations(_trace_events_from_path(trace_path))
    assert not duplicates, (trace_path, duplicates)


def _trace_events_from_path(trace_path: Path) -> list[dict[str, Any]]:
    return read_jsonl_objects(trace_path, label="cleanup trace")


def _without_internal_proof_evidence(payload: Any) -> Any:
    if isinstance(payload, dict):
        return {
            key: _without_internal_proof_evidence(value)
            for key, value in payload.items()
            if key != "planner_primitive_evidence"
        }
    if isinstance(payload, list):
        return [_without_internal_proof_evidence(value) for value in payload]
    return payload
