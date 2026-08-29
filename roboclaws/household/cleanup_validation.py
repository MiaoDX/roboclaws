#!/usr/bin/env python3
from __future__ import annotations

from pathlib import Path
from typing import Any

from roboclaws.core.json_sources import read_json_object
from roboclaws.household.cleanup_validation_agent_view import (
    assert_public_agent_view as _assert_public_agent_view,
)
from roboclaws.household.cleanup_validation_agent_view import (
    assert_runtime_metric_map as _assert_runtime_metric_map,
)
from roboclaws.household.cleanup_validation_base_map import (
    assert_base_metric_map as _assert_base_metric_map,
)
from roboclaws.household.cleanup_validation_evidence import (
    _assert_camera_model_policy,
    _assert_isaac_runtime,
    _assert_model_declared_observations,
    _assert_raw_fpv_observations,
    _assert_robot_head_camera_fpv,
    _assert_robot_views,
)
from roboclaws.household.cleanup_validation_planner import (
    _assert_b1_robot_consumption_proof,
    _assert_bound_planner_cleanup_objects,
    _assert_cleanup_primitive_gate,
    _assert_mixed_planner_cleanup_primitives,
    _assert_planner_cleanup_bridge,
    _assert_planner_proof_attachment,
    _assert_planner_proof_requests,
    _assert_real_robot_alignment,
    _assert_waypoint_honesty,
    _has_planner_proof_requests,
    _is_open_ended_intent,
)
from roboclaws.household.cleanup_validation_run import (
    _assert_adaptive_inspection_thresholds,
    _assert_clean_agent_run,
    _assert_completion_claim,
    _assert_goal_contract,
    _assert_live_map_build_scan_only,
    _assert_map_build_did_not_clean,
    _assert_map_build_scan_profile,
    _assert_no_duplicate_post_place_navigation,
    _assert_runtime_metric_map_quality,
    _assert_semantic_acceptability,
    _assert_trace_is_public,
    _is_live_map_build,
    _is_map_build,
)
from roboclaws.household.cleanup_validation_support import (
    agent_view_runtime_metric_map as _agent_view_runtime_metric_map,
)
from roboclaws.household.cleanup_validation_support import (
    resolve_path as _resolve_path,
)
from roboclaws.household.household_runtime_contract import (
    REALWORLD_CONTRACT,
)
from roboclaws.household.household_runtime_contract import (
    RUNTIME_METRIC_MAP_SCHEMA as RUNTIME_METRIC_MAP_SCHEMA,
)
from roboclaws.household.profiles import evidence_lane, validate_evidence_lane_metadata
from roboclaws.household.report_visual_core import assert_cleanup_report_visual_core
from roboclaws.household.semantic_timeline import (
    SEMANTIC_LOOP_VARIANT,
    SEMANTIC_RESPONSE_PHASES,
    has_complete_semantic_sequence,
    successful_semantic_phases,
)


class _ResultOptions(dict[str, Any]):
    def __missing__(self, key: str) -> bool:
        return False


def _result_assert_options(overrides: dict[str, Any]) -> _ResultOptions:
    if "require_canonical_robot_view_camera_control" in overrides:
        raise ValueError(
            "require_canonical_robot_view_camera_control is obsolete; "
            "use require_robot_head_camera_fpv instead."
        )
    opts = _ResultOptions(
        {
            "expect_task": None,
            "expect_backend": None,
            "expect_task_name": None,
            "expect_policy": "deterministic_sweep_baseline",
            "expect_profile": None,
            "expect_mcp_server": None,
            "expect_visual_grounding_pipeline": None,
            "min_generated_mess_count": 1,
            "min_model_declared_observations": 1,
            "min_model_declared_actions": 0,
            "min_restored_count": None,
            "min_semantic_accepted_count": None,
            "min_sweep_coverage": None,
            "min_adjust_camera_count": 0,
            "expect_map_build_scan_profile": None,
            "min_map_build_body_turn_count": 0,
            "min_generated_target_inspection_candidates": 0,
            "require_planner_proof_min_steps": None,
            "require_bound_planner_cleanup_objects": None,
        }
    )
    opts.update(overrides)
    return opts


def load_run_results(path: Path) -> list[tuple[dict[str, Any], Path]]:
    if path.is_file():
        return [(read_json_object(path, label="cleanup run result"), path)]
    results = []
    for child in sorted(path.glob("seed-*/run_result.json")):
        results.append((read_json_object(child, label="cleanup run result"), child))
    if not results and (path / "run_result.json").is_file():
        child = path / "run_result.json"
        results.append((read_json_object(child, label="cleanup run result"), child))
    return results


def validate_run_result(
    data: dict[str, Any],
    base: Path,
    **overrides: Any,
) -> None:
    opts = _result_assert_options(overrides)
    assert data.get("contract") == REALWORLD_CONTRACT, data
    enforce_success, semantic_success_gate = _assert_core_run_result(data, opts)
    map_build = _assert_agent_view_and_runtime_map(data, base, opts)
    _assert_private_evaluation_and_semantic_success(
        data,
        opts,
        enforce_success=enforce_success,
        semantic_success_gate=semantic_success_gate,
    )
    report_text = _assert_artifacts_and_report_core(
        data,
        base,
        opts,
        enforce_success=enforce_success,
    )
    _assert_optional_result_gates(
        data,
        base,
        report_text,
        opts,
        enforce_success=enforce_success,
        map_build=map_build,
    )


def _assert_core_run_result(data: dict[str, Any], opts: _ResultOptions) -> tuple[bool, bool]:
    assert data.get("adr_0003_satisfied") is True, data
    if opts["require_map_build"] and opts["expect_policy"] == "deterministic_sweep_baseline":
        opts["expect_policy"] = "map_build_baseline"
    if opts["expect_policy"] is not None:
        assert data.get("policy") == opts["expect_policy"], data
    assert data.get("semantic_loop_variant") == SEMANTIC_LOOP_VARIANT, data
    assert data.get("policy_uses_private_truth") is False, data
    assert data.get("planner_uses_private_manifest") is False, data
    assert data.get("static_fixture_projection_mode") == "room_only", data
    assert data.get("generated_mess_count", 0) >= opts["min_generated_mess_count"], data
    if opts["require_agent_driven"]:
        _assert_agent_driven_public_tool_use(data)
    raw_contract_only = (
        opts["require_raw_fpv_observations"]
        and not opts["require_model_declared_observations"]
        and not opts["require_clean_agent_run"]
    )
    enforce_success = (
        not raw_contract_only
        and not opts["allow_partial_cleanup"]
        and not opts["require_map_build"]
    )
    semantic_success_gate = opts["min_semantic_accepted_count"] is not None
    if enforce_success:
        _assert_core_cleanup_success(data, opts, semantic_success_gate=semantic_success_gate)
    _assert_core_thresholds(data, opts)
    _assert_expected_core_fields(data, opts)
    return enforce_success, semantic_success_gate


def _assert_agent_driven_public_tool_use(data: dict[str, Any]) -> None:
    assert data.get("agent_driven") is True, data
    counts = data.get("tool_event_counts") or {}
    public_requests = sum(
        int(counts.get(f"{tool}:request") or 0)
        for tool in (
            "metric_map",
            "static_fixture_projection",
            "navigate_to_waypoint",
            "observe",
            *SEMANTIC_RESPONSE_PHASES,
            "done",
        )
    )
    assert public_requests >= 1, (public_requests, counts, data)
    assert int(counts.get("scene_objects:request") or 0) == 0, (counts, data)


def _assert_core_cleanup_success(
    data: dict[str, Any],
    opts: _ResultOptions,
    *,
    semantic_success_gate: bool,
) -> None:
    assert data.get("sweep_coverage_rate", 0) >= 0.90, data
    assert data.get("disturbance_count", 999) <= 2, data
    if semantic_success_gate:
        _assert_semantic_acceptability(data, opts["min_semantic_accepted_count"])
        return
    assert data.get("mess_restoration_rate", 0) >= 0.70, data
    assert data.get("cleanup_status") == "success", data


def _assert_core_thresholds(data: dict[str, Any], opts: _ResultOptions) -> None:
    if opts["min_restored_count"] is not None:
        assert (
            int((data.get("score") or {}).get("restored_count") or 0) >= opts["min_restored_count"]
        ), data
    if opts["min_semantic_accepted_count"] is not None:
        _assert_semantic_acceptability(data, opts["min_semantic_accepted_count"])
    if opts["min_sweep_coverage"] is not None:
        assert float(data.get("sweep_coverage_rate") or 0.0) >= opts["min_sweep_coverage"], data
    _assert_adaptive_inspection_thresholds(
        data,
        min_adjust_camera_count=opts["min_adjust_camera_count"],
        min_generated_target_inspection_candidates=opts[
            "min_generated_target_inspection_candidates"
        ],
    )


def _assert_expected_core_fields(data: dict[str, Any], opts: _ResultOptions) -> None:
    if opts["expect_task"] is not None:
        assert data.get("task_prompt") == opts["expect_task"], data
    if opts["expect_task_name"] is not None:
        assert data.get("task_name") == opts["expect_task_name"], data
    if opts["expect_backend"] is not None:
        assert data.get("backend") == opts["expect_backend"], data
    if opts["expect_mcp_server"] is not None:
        assert data.get("mcp_server") == opts["expect_mcp_server"], data
    if opts["require_agent_driven"]:
        assert data.get("agent_driven") is True, data


def _assert_agent_view_and_runtime_map(
    data: dict[str, Any],
    base: Path,
    opts: _ResultOptions,
) -> bool:
    agent_view = data.get("agent_view") or {}
    map_build = _is_map_build(data)
    _assert_public_agent_view(
        agent_view,
        open_ended_intent=_is_open_ended_intent(data),
        map_build=map_build,
    )
    if opts["require_base_metric_map"]:
        _assert_base_metric_map(data, agent_view)
    if opts["require_runtime_metric_map"]:
        runtime_metric_map = data.get("runtime_metric_map") or _agent_view_runtime_metric_map(
            agent_view
        )
        _assert_runtime_metric_map(runtime_metric_map, agent_view=agent_view, map_build=map_build)
        _assert_runtime_metric_map_quality(runtime_metric_map)
    if opts["require_goal_contract"]:
        _assert_goal_contract(data, base)
    if opts["require_completion_claim"]:
        _assert_completion_claim(data)
    runtime_metric_map = data.get("runtime_metric_map") or _agent_view_runtime_metric_map(
        agent_view
    )
    map_build = map_build or runtime_metric_map.get("mode") == "map_build"
    if opts["require_map_build"]:
        assert map_build, data
        if _is_live_map_build(data):
            _assert_live_map_build_scan_only(data)
        else:
            assert data.get("cleanup_actions_disabled") is True, data
            assert data.get("policy") == "map_build_baseline", data
            assert (data.get("map_build") or {}).get("snapshot_artifact"), data
            assert len((data.get("map_build") or {}).get("camera_schedule") or []) >= 1, data
            _assert_map_build_scan_profile(
                data,
                expected_profile=opts["expect_map_build_scan_profile"],
                min_body_turn_count=opts["min_map_build_body_turn_count"],
            )
    if map_build:
        _assert_map_build_did_not_clean(data)
    trace_path = _resolve_path(base, data["artifacts"]["trace"])
    _assert_trace_is_public(trace_path)
    _assert_no_duplicate_post_place_navigation(trace_path)
    return map_build


def _assert_private_evaluation_and_semantic_success(
    data: dict[str, Any],
    opts: _ResultOptions,
    *,
    enforce_success: bool,
    semantic_success_gate: bool,
) -> None:
    private = data.get("private_evaluation") or {}
    assert private.get("generated_mess_count") == data.get("generated_mess_count"), data
    assert private.get("generated_mess_count", 0) >= opts["min_generated_mess_count"], data
    if int(private.get("generated_mess_count") or 0) > 0:
        assert private.get("acceptable_destination_sets"), data
    else:
        assert private.get("acceptable_destination_sets") == {}, data
    if enforce_success and not semantic_success_gate:
        for item in data.get("semantic_substeps") or []:
            phases = successful_semantic_phases(item.get("steps", []))
            assert has_complete_semantic_sequence(phases), (phases, item)


def _assert_artifacts_and_report_core(
    data: dict[str, Any],
    base: Path,
    opts: _ResultOptions,
    *,
    enforce_success: bool,
) -> str:
    artifacts = data.get("artifacts") or {}
    for key in (
        "agent_view",
        "private_evaluation",
        "trace",
        "before_snapshot",
        "after_snapshot",
        "report",
    ):
        path = _resolve_path(base, artifacts.get(key, ""))
        assert path.is_file(), path
        assert path.stat().st_size > 0, path
    if opts["require_runtime_metric_map"]:
        path = _resolve_path(base, artifacts.get("runtime_metric_map", ""))
        assert path.is_file(), path
        assert path.stat().st_size > 0, path
    report_text = _resolve_path(base, artifacts["report"]).read_text(encoding="utf-8")
    if opts["expect_profile"] is not None:
        _assert_evidence_lane(data, report_text, opts["expect_profile"])
    assert "Agent View" in report_text, report_text[:500]
    assert "Private Evaluation" in report_text, report_text[:500]
    assert "Score" in report_text, report_text[:500]
    if enforce_success or data.get("semantic_substeps"):
        assert "Semantic Substeps" in report_text, report_text[:500]
    assert "ADR-0003 real-world-style cleanup run" not in report_text, report_text[:500]
    if opts["require_runtime_metric_map"]:
        assert "Runtime Metric Map" in report_text, report_text[:500]
    if opts["require_map_build"] and not _is_live_map_build(data):
        assert "Map Build Mode" in report_text, report_text[:500]
    elif opts["require_map_build"]:
        assert "Runtime Metric Map" in report_text, report_text[:500]
        assert "Target Candidates" in report_text, report_text[:500]
    assert_cleanup_report_visual_core(
        report_text,
        require_semantic_subphases=enforce_success or bool(data.get("semantic_substeps")),
        require_robot_timeline=opts["require_robot_views"],
        require_agent_view=True,
        require_private_evaluation=True,
        require_planner_proof_requests=_has_planner_proof_requests(data),
    )
    _assert_planner_proof_requests(data, base, report_text)
    return report_text


def _assert_optional_result_gates(
    data: dict[str, Any],
    base: Path,
    report_text: str,
    opts: _ResultOptions,
    *,
    enforce_success: bool,
    map_build: bool,
) -> None:
    _assert_optional_agent_observation_gates(
        data,
        base,
        report_text,
        opts,
        enforce_success=enforce_success,
        map_build=map_build,
    )
    _assert_optional_planner_gates(data, base, report_text, opts)
    _assert_optional_backend_gates(data, base, report_text, opts)


def _assert_optional_agent_observation_gates(
    data: dict[str, Any],
    base: Path,
    report_text: str,
    opts: _ResultOptions,
    *,
    enforce_success: bool,
    map_build: bool,
) -> None:
    if opts["require_clean_agent_run"] and not opts["allow_partial_cleanup"]:
        _assert_clean_agent_run(data, min_complete_count=opts["min_semantic_accepted_count"])
    if opts["require_robot_views"]:
        _assert_robot_views(data, base, require_complete_actions=enforce_success)
    if opts["require_robot_head_camera_fpv"]:
        _assert_robot_head_camera_fpv(data, base)
    if opts["require_raw_fpv_observations"]:
        _assert_raw_fpv_observations(data, base, report_text)
    if opts["require_camera_model_policy"]:
        _assert_camera_model_policy(
            data,
            base,
            report_text,
            expect_pipeline_id=opts["expect_visual_grounding_pipeline"],
            require_failure=opts["require_visual_grounding_failure"],
            map_build=map_build,
        )
    if opts["require_model_declared_observations"]:
        _assert_model_declared_observations(
            data,
            report_text,
            min_observations=opts["min_model_declared_observations"],
            min_actions=opts["min_model_declared_actions"],
        )


def _assert_optional_planner_gates(
    data: dict[str, Any],
    base: Path,
    report_text: str,
    opts: _ResultOptions,
) -> None:
    if (
        opts["require_planner_proof_attachment"]
        or opts["require_planner_proof_quality"]
        or opts["require_planner_proof_min_steps"] is not None
    ):
        _assert_planner_proof_attachment(
            data,
            base,
            report_text,
            require_quality=opts["require_planner_proof_quality"],
            min_steps_executed=opts["require_planner_proof_min_steps"],
        )
    if (
        opts["accept_blocked_planner_cleanup_primitives"]
        or opts["require_planner_backed_cleanup_primitives"]
    ):
        _assert_cleanup_primitive_gate(
            data,
            report_text,
            accept_blocked=opts["accept_blocked_planner_cleanup_primitives"],
            require_planner_backed=opts["require_planner_backed_cleanup_primitives"],
        )
    if opts["require_bound_planner_cleanup_objects"]:
        _assert_bound_planner_cleanup_objects(
            data,
            report_text,
            opts["require_bound_planner_cleanup_objects"],
        )
    if opts["require_mixed_planner_cleanup_primitives"]:
        _assert_mixed_planner_cleanup_primitives(data, report_text)
    if (
        opts["accept_blocked_planner_cleanup_bridge"]
        or opts["require_planner_cleanup_bridge_ready"]
    ):
        _assert_planner_cleanup_bridge(
            data,
            report_text,
            accept_blocked=opts["accept_blocked_planner_cleanup_bridge"],
            require_ready=opts["require_planner_cleanup_bridge_ready"],
        )
    if opts["require_waypoint_honesty"]:
        _assert_waypoint_honesty(data, report_text)


def _assert_optional_backend_gates(
    data: dict[str, Any],
    base: Path,
    report_text: str,
    opts: _ResultOptions,
) -> None:
    if opts["require_real_robot_alignment"]:
        _assert_real_robot_alignment(data, base, report_text)
    if opts["require_b1_robot_consumption_proof"]:
        _assert_b1_robot_consumption_proof(data, base)
    if _needs_isaac_runtime(opts):
        _assert_isaac_runtime(
            data,
            base,
            report_text,
            require_real_runtime=opts["require_isaac_real_runtime"],
            require_scene_loaded=opts["require_isaac_scene_loaded"],
            require_local_scene_usd=opts["require_isaac_local_scene_usd"],
            require_selected_usd_bindings=opts["require_isaac_selected_usd_bindings"],
            require_semantic_pose=opts["require_isaac_semantic_pose"],
            require_robot_view_provenance=opts["require_isaac_robot_view_provenance"],
            require_segmentation_evidence=opts["require_isaac_segmentation_evidence"],
            require_snapshot_provenance=opts["require_isaac_snapshot_provenance"],
            require_scene_index_map_context=opts["require_isaac_scene_index_map_context"],
        )


def _needs_isaac_runtime(opts: _ResultOptions) -> bool:
    return any(
        opts[key]
        for key in (
            "require_isaac_runtime",
            "require_isaac_real_runtime",
            "require_isaac_scene_loaded",
            "require_isaac_local_scene_usd",
            "require_isaac_selected_usd_bindings",
            "require_isaac_semantic_pose",
            "require_isaac_robot_view_provenance",
            "require_isaac_segmentation_evidence",
            "require_isaac_snapshot_provenance",
            "require_isaac_scene_index_map_context",
        )
    )


def _assert_evidence_lane(
    data: dict[str, Any],
    report_text: str,
    expected_profile: str,
) -> None:
    profile = evidence_lane(expected_profile)
    assert data.get("evidence_lane") == profile.evidence_lane, data
    metadata = data.get("evidence_lane_metadata") or data.get("cleanup_profile_metadata") or {}
    validate_evidence_lane_metadata(
        metadata,
        expected_evidence_lane=profile.profile,
        expected_backend=data.get("backend"),
        expected_perception_mode=data.get("perception_mode"),
    )
    assert profile.evidence_lane in report_text, report_text[:500]
    assert profile.agent_input in report_text, report_text[:500]
    if profile.evidence_lane == "world-public-labels":
        assert "image reasoning" not in report_text.lower(), report_text[:500]
        model_input_note = str(metadata.get("model_input_note") or "")
        assert "withheld" in model_input_note.lower(), metadata
    if profile.evidence_lane == "camera-grounded-labels":
        expected_labeler = str(metadata.get("camera_labeler") or "")
        assert expected_labeler, metadata
        pipeline = str(
            (data.get("camera_model_policy_evidence") or {}).get("visual_grounding_pipeline_id")
            or ""
        )
        assert pipeline == expected_labeler, (expected_labeler, pipeline, data)
