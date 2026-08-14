#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from PIL import Image, ImageStat

from roboclaws.core.json_sources import read_json_object, read_jsonl_objects
from roboclaws.household import agent_view as agent_view_module
from roboclaws.household.cleanup_primitive_evidence import (
    validate_cleanup_primitive_evidence,
)
from roboclaws.household.household_runtime_contract import (
    CAMERA_MODEL_POLICY_MODE,
    CAMERA_MODEL_POLICY_NAME,
    CAMERA_MODEL_POLICY_SCHEMA,
    CLEANUP_POLICY_TRACE_SCHEMA,
    MODEL_DECLARED_OBSERVATIONS_SCHEMA,
    REAL_ROBOT_MAP_BUNDLE_SCHEMA,
    REAL_ROBOT_READINESS_SCHEMA,
    REALWORLD_CONTRACT,
    SIMULATED_CAMERA_MODEL_PROVENANCE,
    forbidden_agent_view_keys,
)
from roboclaws.household.household_runtime_contract import (
    RUNTIME_METRIC_MAP_SCHEMA as RUNTIME_METRIC_MAP_SCHEMA,
)
from roboclaws.household.isaac_lab_backend import (
    ISAACLAB_ROBOT_VIEW_VARIANT,
    ISAACLAB_SUBPROCESS_BACKEND,
)
from roboclaws.household.manipulation_contract import API_SEMANTIC_PROVENANCE
from roboclaws.household.planner_cleanup_bridge import (
    validate_planner_cleanup_bridge_evidence,
)
from roboclaws.household.planner_proof_attachment import (
    validate_planner_proof_attachment,
)
from roboclaws.household.planner_proof_bundle import (
    PLANNER_PROOF_BUNDLE_SCHEMA,
    planner_proof_attachments,
    validate_planner_proof_bundle,
)
from roboclaws.household.planner_proof_quality import (
    planner_proof_quality_evidence,
    validate_planner_proof_quality_evidence,
)
from roboclaws.household.planner_proof_requests import PLANNER_PROOF_REQUESTS_SCHEMA
from roboclaws.household.profiles import evidence_lane, validate_evidence_lane_metadata
from roboclaws.household.realworld_runtime_map_targets import (
    LOCALIZATION_STATUS_VIEWPOINT_ONLY,
    POSE_ROLE_BEST_VIEW_POSE,
    POSE_ROLE_INSPECTION_WAYPOINT,
)
from roboclaws.household.report_visual_core import assert_cleanup_report_visual_core
from roboclaws.household.semantic_timeline import (
    CANONICAL_SURFACE_CLEANUP_PHASES,
    CLOSE_RECEPTACLE_PHASE,
    FOCUSED_SEMANTIC_ACTION_PREFIXES,
    NAVIGATE_TO_VISUAL_CANDIDATE_TOOL,
    OPEN_RECEPTACLE_PHASE,
    PLACE_INSIDE_PHASE,
    SEMANTIC_LOOP_VARIANT,
    SEMANTIC_RESPONSE_PHASES,
    annotate_focus_visual_grounding,
    duplicate_post_place_navigations,
    has_complete_semantic_sequence,
    successful_semantic_phases,
)
from roboclaws.household.visual_grounding import EXTERNAL_VISUAL_GROUNDING_PROVENANCE
from roboclaws.maps.route import SIM_COSTMAP_PLANNER
from scripts.molmo_cleanup.isaac_runtime_checker import (
    assert_isaac_runtime as _assert_isaac_backend_runtime,
)
from scripts.molmo_cleanup.realworld_agent_view_checker import (
    assert_public_agent_view as _assert_public_agent_view,
)
from scripts.molmo_cleanup.realworld_agent_view_checker import (
    assert_runtime_metric_map as _assert_runtime_metric_map,
)
from scripts.molmo_cleanup.realworld_base_metric_map_checker import (
    assert_base_metric_map as _assert_base_metric_map,
)
from scripts.molmo_cleanup.realworld_waypoint_honesty_checker import (
    assert_waypoint_honesty,
    post_place_observe_count_allowing_public_state_queries,
)

ISAAC_PUBLIC_SCENE_BINDING_SCHEMA = "isaac_public_scene_bindings_v1"
LEGACY_ROBOT_VIEW_CAMERA_CONTROL_FLAG = "--require-canonical-robot-view-camera-control"


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


def _add_core_checker_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("path", type=Path, help="run_result.json or a directory of seed-* runs")
    parser.add_argument("--expect-task")
    parser.add_argument("--expect-task-name")
    parser.add_argument("--expect-backend")
    parser.add_argument("--expect-policy")
    parser.add_argument("--expect-profile", help="Expected cleanup evidence lane or smoke preset.")
    parser.add_argument("--expect-mcp-server")
    parser.add_argument("--expect-seeds")
    parser.add_argument("--min-generated-mess-count", type=int, default=1)
    parser.add_argument("--require-agent-driven", action="store_true")
    parser.add_argument("--require-clean-agent-run", action="store_true")
    parser.add_argument(
        "--allow-partial-cleanup",
        action="store_true",
        help="Validate contract/report evidence without requiring cleanup success.",
    )
    parser.add_argument("--require-robot-views", action="store_true")
    parser.add_argument("--require-advisory-scoring", action="store_true")


def _add_evidence_checker_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--require-raw-fpv-observations", action="store_true")
    parser.add_argument("--require-camera-model-policy", action="store_true")
    parser.add_argument("--require-runtime-metric-map", action="store_true")
    parser.add_argument("--require-goal-contract", action="store_true")
    parser.add_argument("--require-completion-claim", action="store_true")
    parser.add_argument("--require-map-build", action="store_true")
    parser.add_argument("--require-agibot-g2-hardware", action="store_true")
    parser.add_argument("--require-base-metric-map", action="store_true")
    parser.add_argument("--expect-visual-grounding-pipeline")
    parser.add_argument("--require-visual-grounding-failure", action="store_true")
    parser.add_argument("--require-model-declared-observations", action="store_true")
    parser.add_argument("--min-model-declared-observations", type=int, default=1)
    parser.add_argument("--min-model-declared-actions", type=int, default=0)
    parser.add_argument("--min-restored-count", type=int, default=None)
    parser.add_argument("--min-semantic-accepted-count", type=int, default=None)
    parser.add_argument("--min-sweep-coverage", type=float, default=None)
    parser.add_argument(
        "--min-adjust-camera-count",
        type=int,
        default=0,
        help="Require at least this many adjust_camera tool requests for adaptive proof runs.",
    )
    parser.add_argument(
        "--expect-map-build-scan-profile",
        help="Require the map-build scan profile id, normally fixture-focused.",
    )
    parser.add_argument(
        "--min-map-build-body-turn-count",
        type=int,
        default=0,
        help="Require at least this many navigate_to_relative_pose requests for map-build scans.",
    )
    parser.add_argument(
        "--min-generated-target-inspection-candidates",
        type=int,
        default=0,
        help=(
            "Require at least this many public generated target-inspection candidates "
            "for adaptive proof runs."
        ),
    )


def _add_planner_checker_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--require-planner-proof-attachment", action="store_true")
    parser.add_argument("--require-planner-proof-quality", action="store_true")
    parser.add_argument(
        "--require-planner-proof-min-steps",
        type=int,
        default=None,
        help="Require every attached planner proof to execute at least this many steps.",
    )
    parser.add_argument("--accept-blocked-planner-cleanup-primitives", action="store_true")
    parser.add_argument("--require-planner-backed-cleanup-primitives", action="store_true")
    parser.add_argument(
        "--require-bound-planner-cleanup-object",
        action="append",
        default=[],
        metavar="OBJECT_ID:TARGET_RECEPTACLE_ID",
        help=(
            "Require one cleanup object/target pair to have all cleanup subphases "
            "strictly planner_backed. Repeat for multiple bound objects."
        ),
    )
    parser.add_argument(
        "--require-mixed-planner-cleanup-primitives",
        action="store_true",
        help=(
            "Require a partial rerun state: at least one bound planner-backed "
            "object and at least one unmatched api_semantic object, with the "
            "global primitive gate still blocked."
        ),
    )
    parser.add_argument("--accept-blocked-planner-cleanup-bridge", action="store_true")
    parser.add_argument("--require-planner-cleanup-bridge-ready", action="store_true")
    parser.add_argument("--require-waypoint-honesty", action="store_true")
    parser.add_argument("--require-real-robot-alignment", action="store_true")
    parser.add_argument("--require-b1-robot-consumption-proof", action="store_true")


def _add_isaac_checker_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--require-isaac-runtime", action="store_true")
    parser.add_argument("--require-isaac-real-runtime", action="store_true")
    parser.add_argument("--require-isaac-scene-loaded", action="store_true")
    parser.add_argument("--require-isaac-local-scene-usd", action="store_true")
    parser.add_argument("--require-isaac-selected-usd-bindings", action="store_true")
    parser.add_argument("--require-isaac-semantic-pose", action="store_true")
    parser.add_argument("--require-isaac-robot-view-provenance", action="store_true")
    parser.add_argument("--require-isaac-segmentation-evidence", action="store_true")
    parser.add_argument("--require-isaac-snapshot-provenance", action="store_true")
    parser.add_argument(
        "--require-isaac-scene-index-map-context",
        action="store_true",
        help=(
            "Require Isaac scene-index cleanup runs to expose map/waypoint context "
            "generated from the loaded scene instead of a stale prebuilt map bundle."
        ),
    )


def _add_robot_camera_checker_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        LEGACY_ROBOT_VIEW_CAMERA_CONTROL_FLAG,
        action="store_true",
        dest="unsupported_legacy_robot_view_camera_control",
        help=argparse.SUPPRESS,
    )
    parser.add_argument(
        "--require-robot-head-camera-fpv",
        action="store_true",
        help=(
            "Require every cleanup agent-facing FPV view to come from a robot-mounted "
            "head camera or an explicit backend head-camera-equivalent contract."
        ),
    )


def _reject_legacy_robot_view_camera_control_flag(
    parser: argparse.ArgumentParser,
    args: argparse.Namespace,
) -> None:
    if args.unsupported_legacy_robot_view_camera_control:
        parser.error(
            f"{LEGACY_ROBOT_VIEW_CAMERA_CONTROL_FLAG} is obsolete; "
            "use --require-robot-head-camera-fpv."
        )


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Validate ADR-0003 real-world-style Molmo cleanup artifacts."
    )
    _add_core_checker_args(parser)
    _add_evidence_checker_args(parser)
    _add_planner_checker_args(parser)
    _add_isaac_checker_args(parser)
    _add_robot_camera_checker_args(parser)
    args = parser.parse_args()
    _reject_legacy_robot_view_camera_control_flag(parser, args)
    return args


def main() -> None:
    args = parse_args()
    run_results = _load_run_results(args.path)
    if args.expect_seeds:
        expected = {int(item) for item in args.expect_seeds.split(",") if item}
        actual = {int(data["seed"]) for data, _path in run_results}
        assert expected <= actual, (expected, actual)
    assert len(run_results) >= 1, args.path
    expect_policy = args.expect_policy
    if expect_policy is None:
        expect_policy = (
            "map_build_baseline"
            if args.require_map_build
            else CAMERA_MODEL_POLICY_NAME
            if args.require_camera_model_policy
            else "deterministic_sweep_baseline"
        )
    for data, path in run_results:
        _assert_result(
            data,
            path.parent,
            expect_task=args.expect_task,
            expect_task_name=args.expect_task_name,
            expect_backend=args.expect_backend,
            expect_policy=expect_policy,
            expect_profile=args.expect_profile,
            expect_mcp_server=args.expect_mcp_server,
            min_generated_mess_count=args.min_generated_mess_count,
            require_agent_driven=args.require_agent_driven,
            require_clean_agent_run=args.require_clean_agent_run,
            allow_partial_cleanup=args.allow_partial_cleanup,
            require_robot_views=args.require_robot_views,
            require_advisory_scoring=args.require_advisory_scoring,
            require_raw_fpv_observations=args.require_raw_fpv_observations,
            require_camera_model_policy=args.require_camera_model_policy,
            require_runtime_metric_map=args.require_runtime_metric_map,
            require_goal_contract=args.require_goal_contract,
            require_completion_claim=args.require_completion_claim,
            require_map_build=args.require_map_build,
            require_agibot_g2_hardware=args.require_agibot_g2_hardware,
            require_base_metric_map=args.require_base_metric_map,
            expect_visual_grounding_pipeline=args.expect_visual_grounding_pipeline,
            require_visual_grounding_failure=args.require_visual_grounding_failure,
            require_model_declared_observations=args.require_model_declared_observations,
            min_model_declared_observations=args.min_model_declared_observations,
            min_model_declared_actions=args.min_model_declared_actions,
            min_restored_count=args.min_restored_count,
            min_semantic_accepted_count=args.min_semantic_accepted_count,
            min_sweep_coverage=args.min_sweep_coverage,
            min_adjust_camera_count=args.min_adjust_camera_count,
            expect_map_build_scan_profile=args.expect_map_build_scan_profile,
            min_map_build_body_turn_count=args.min_map_build_body_turn_count,
            min_generated_target_inspection_candidates=(
                args.min_generated_target_inspection_candidates
            ),
            require_planner_proof_attachment=args.require_planner_proof_attachment,
            require_planner_proof_quality=args.require_planner_proof_quality,
            require_planner_proof_min_steps=args.require_planner_proof_min_steps,
            accept_blocked_planner_cleanup_primitives=(
                args.accept_blocked_planner_cleanup_primitives
            ),
            require_planner_backed_cleanup_primitives=(
                args.require_planner_backed_cleanup_primitives
            ),
            require_bound_planner_cleanup_objects=args.require_bound_planner_cleanup_object,
            require_mixed_planner_cleanup_primitives=(
                args.require_mixed_planner_cleanup_primitives
            ),
            accept_blocked_planner_cleanup_bridge=(args.accept_blocked_planner_cleanup_bridge),
            require_planner_cleanup_bridge_ready=(args.require_planner_cleanup_bridge_ready),
            require_waypoint_honesty=args.require_waypoint_honesty,
            require_real_robot_alignment=args.require_real_robot_alignment,
            require_b1_robot_consumption_proof=args.require_b1_robot_consumption_proof,
            require_isaac_runtime=args.require_isaac_runtime,
            require_isaac_real_runtime=args.require_isaac_real_runtime,
            require_isaac_scene_loaded=args.require_isaac_scene_loaded,
            require_isaac_local_scene_usd=args.require_isaac_local_scene_usd,
            require_isaac_selected_usd_bindings=args.require_isaac_selected_usd_bindings,
            require_isaac_semantic_pose=args.require_isaac_semantic_pose,
            require_isaac_robot_view_provenance=args.require_isaac_robot_view_provenance,
            require_isaac_segmentation_evidence=args.require_isaac_segmentation_evidence,
            require_isaac_snapshot_provenance=args.require_isaac_snapshot_provenance,
            require_isaac_scene_index_map_context=(args.require_isaac_scene_index_map_context),
            require_robot_head_camera_fpv=args.require_robot_head_camera_fpv,
        )
    print(f"household-world ok: {args.path} ({len(run_results)} run(s))")


def _load_run_results(path: Path) -> list[tuple[dict[str, Any], Path]]:
    if path.is_file():
        return [(read_json_object(path, label="cleanup run result"), path)]
    results = []
    for child in sorted(path.glob("seed-*/run_result.json")):
        results.append((read_json_object(child, label="cleanup run result"), child))
    if not results and (path / "run_result.json").is_file():
        child = path / "run_result.json"
        results.append((read_json_object(child, label="cleanup run result"), child))
    return results


def _assert_result(
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
    if opts["require_advisory_scoring"]:
        _assert_advisory_scoring(data, base, report_text)
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


def _assert_robot_views(
    data: dict[str, Any],
    base: Path,
    *,
    require_complete_actions: bool = True,
) -> None:
    expected_variants = {"molmospaces-rby1m-fpv-topdown-chase-verify"}
    if data.get("backend") == ISAACLAB_SUBPROCESS_BACKEND:
        expected_variants.add(ISAACLAB_ROBOT_VIEW_VARIANT)
    assert data.get("view_variant") in expected_variants, data
    artifacts = data.get("artifacts") or {}
    robot_views_dir = _resolve_path(base, artifacts.get("robot_views", ""))
    assert robot_views_dir.is_dir(), robot_views_dir
    report_path = _resolve_path(base, artifacts.get("report", ""))
    report_text = report_path.read_text(encoding="utf-8")
    assert "Robot View Timeline" in report_text, report_text[:500]
    steps = data.get("robot_view_steps") or []
    assert len(steps) >= 2, data
    camera_summary = data.get("robot_view_camera_control")
    if camera_summary is not None:
        assert isinstance(camera_summary, dict), data
        assert camera_summary.get("schema") == "robot_view_camera_control_summary_v1", data
        assert isinstance(camera_summary.get("same_pose_api"), bool), data
    focused_actions: set[str] = set()
    for step in steps:
        views = step.get("views") or {}
        assert int(step.get("room_outline_count") or 0) > 0, step
        for key in ("fpv", "chase", "topdown", "verify"):
            path = _resolve_path(report_path.parent, views.get(key, ""))
            assert path.is_file(), path
            assert path.stat().st_size > 0, path
        action = str(step.get("action", ""))
        if _is_focused_robot_action(action):
            focused_actions.add(_canonical_robot_view_phase(step, action))
            if not action.startswith("observe "):
                _assert_focused_robot_step(step)
    if require_complete_actions:
        assert focused_actions, (focused_actions, data)
        for expected in CANONICAL_SURFACE_CLEANUP_PHASES:
            assert expected in focused_actions, (expected, focused_actions, data)
        if any(
            item.get("target_receptacle_category") == "Fridge"
            for item in data.get("semantic_substeps") or []
        ):
            assert OPEN_RECEPTACLE_PHASE in focused_actions, data
            assert PLACE_INSIDE_PHASE in focused_actions, data
            assert CLOSE_RECEPTACLE_PHASE in focused_actions, data


def _assert_robot_head_camera_fpv(data: dict[str, Any], base: Path) -> None:
    _assert_robot_views(data, base, require_complete_actions=False)
    summary = data.get("robot_view_camera_control") or {}
    assert summary.get("schema") == "robot_view_camera_control_summary_v1", data
    assert summary.get("status") == "all_robot_views_use_head_camera_fpv", summary
    assert summary.get("head_camera_fpv") is True, summary
    steps = data.get("robot_view_steps") or []
    assert steps, data
    assert int(summary.get("contract_count") or 0) == len(steps), summary
    assert int(summary.get("head_camera_contract_count") or 0) == len(steps), summary
    report_path = _resolve_path(base, (data.get("artifacts") or {}).get("report", ""))
    for step in steps:
        contract = step.get("camera_control_contract") or {}
        assert contract.get("schema") == "robot_view_camera_control_contract_v1", step
        assert contract.get("status") in {
            "robot_mounted_head_camera_robot_view",
            "robot_head_camera_equivalent_robot_view",
        }, step
        assert contract.get("camera_control_api") is None, step
        assert contract.get("camera_model") in {
            "robot_mounted_head_camera_v1",
            "robot_head_camera_equivalent_v1",
        }, step
        fpv = contract.get("agent_facing_fpv") or {}
        verify = contract.get("report_verify_view") or {}
        assert fpv.get("canonical_camera_control") is False, step
        assert verify.get("canonical_camera_control") is False, step
        assert fpv.get("source"), step
        assert "head_camera" in str(fpv.get("source")) or fpv.get("head_camera_equivalent"), step
        robot_pose = contract.get("robot_pose") or step.get("robot_pose") or {}
        if robot_pose:
            assert robot_pose.get("schema") == "cleanup_robot_pose_result_v1", step
            pose_request = robot_pose.get("pose_request") or {}
            assert pose_request.get("schema") == "cleanup_robot_pose_request_v1", step
            assert pose_request.get("resolver") == "roboclaws.cleanup_robot_pose.near_target_v1", (
                step
            )
        views = step.get("views") or {}
        _assert_nonblank_image(
            _resolve_path(report_path.parent, str(views.get("fpv") or "")),
            "robot head-camera FPV",
        )
        _assert_nonblank_image(
            _resolve_path(report_path.parent, str(views.get("verify") or "")),
            "robot verify",
        )


def _assert_nonblank_image(path: Path, label: str) -> None:
    assert path.is_file(), path
    try:
        with Image.open(path) as image:
            image.verify()
        with Image.open(path) as image:
            rgb = image.convert("RGB")
            extrema = rgb.getextrema()
            stat = ImageStat.Stat(rgb)
    except Exception as exc:
        raise AssertionError(f"{label} is not a readable image: {path}") from exc
    assert any(high > low for low, high in extrema), (label, path)
    assert max(stat.stddev or [0.0]) > 0.0, (label, path)


def _assert_isaac_runtime(
    data: dict[str, Any],
    base: Path,
    report_text: str,
    *,
    require_real_runtime: bool,
    require_scene_loaded: bool,
    require_local_scene_usd: bool = False,
    require_selected_usd_bindings: bool,
    require_semantic_pose: bool,
    require_robot_view_provenance: bool,
    require_segmentation_evidence: bool,
    require_snapshot_provenance: bool,
    require_scene_index_map_context: bool = False,
) -> None:
    _assert_isaac_backend_runtime(
        data,
        base,
        report_text,
        assert_robot_views=_assert_robot_views,
        require_real_runtime=require_real_runtime,
        require_scene_loaded=require_scene_loaded,
        require_local_scene_usd=require_local_scene_usd,
        require_selected_usd_bindings=require_selected_usd_bindings,
        require_semantic_pose=require_semantic_pose,
        require_robot_view_provenance=require_robot_view_provenance,
        require_segmentation_evidence=require_segmentation_evidence,
        require_snapshot_provenance=require_snapshot_provenance,
    )
    if require_scene_index_map_context:
        _assert_isaac_scene_index_map_context(data, base)


def _assert_isaac_scene_index_map_context(data: dict[str, Any], base: Path) -> None:
    isaac = data.get("isaac_runtime") or {}
    scenario_id = str(data.get("scenario_id") or "")
    assert scenario_id.startswith("isaac-scene-index-"), data
    assert isaac.get("scenario_source") == "isaac_scene_index", isaac

    agent_view = data.get("agent_view") or {}
    metric_map = agent_view_module.base_metric_map(agent_view)
    runtime_map = data.get("runtime_metric_map") or _agent_view_runtime_metric_map(agent_view)
    static_map = runtime_map.get("static_map") or {}
    nav2_bundle = data.get("nav2_map_bundle") or {}
    scene_index_overlay = static_map.get("scene_index_fixture_overlay") or {}

    if scene_index_overlay:
        assert scene_index_overlay.get("enabled") is True, scene_index_overlay
        assert scene_index_overlay.get("source") == "isaac_scene_index", scene_index_overlay
    else:
        assert isaac.get("scenario_source") == "isaac_scene_index", {
            "isaac_runtime": isaac,
            "runtime_static_map": static_map,
        }
    _assert_map_bundle_environment(metric_map.get("map_bundle") or {}, scenario_id)
    _assert_map_bundle_environment(static_map.get("map_bundle") or {}, scenario_id)
    _assert_map_bundle_environment(nav2_bundle, scenario_id)
    if _is_base_metric_map(metric_map, runtime_map):
        _assert_base_metric_map(data, agent_view)
        _assert_isaac_scene_index_generated_candidate_scale(metric_map)
        _assert_isaac_scene_index_generated_candidate_scale(static_map or runtime_map)
    else:
        _assert_isaac_scene_index_room_scale(metric_map)
        _assert_isaac_scene_index_room_scale(static_map)
    assert "source_bundle_root" not in nav2_bundle, nav2_bundle
    assert nav2_bundle.get("source_provenance") == "molmospaces_base_metric_map", nav2_bundle

    artifact_paths = nav2_bundle.get("artifact_paths") or {}
    semantics_path = _resolve_path(base, str(artifact_paths.get("semantics_json") or ""))
    semantics = read_json_object(semantics_path, label="Isaac scene-index Nav2 semantics")
    assert semantics.get("environment_id") == scenario_id, semantics
    assert str(semantics.get("map_id") or "").startswith(scenario_id), semantics
    assert "molmospaces-procthor-val-0-7" not in json.dumps(
        {
            "metric_map": metric_map.get("map_bundle"),
            "static_map": static_map.get("map_bundle"),
            "nav2_bundle": nav2_bundle,
            "semantics_environment_id": semantics.get("environment_id"),
            "semantics_map_id": semantics.get("map_id"),
        },
        sort_keys=True,
    )


def _assert_map_bundle_environment(bundle: dict[str, Any], scenario_id: str) -> None:
    assert bundle.get("schema") in {
        "nav2_map_bundle_v1",
        "nav2_map_bundle_snapshot_v1",
    }, bundle
    assert bundle.get("environment_id") == scenario_id, bundle
    assert str(bundle.get("map_id") or "").startswith(scenario_id), bundle


def _assert_isaac_scene_index_room_scale(metric_map: dict[str, Any]) -> None:
    rooms = [room for room in metric_map.get("rooms") or [] if isinstance(room, dict)]
    assert rooms, metric_map
    outlines = [
        room.get("scene_room_outline")
        for room in rooms
        if isinstance(room.get("scene_room_outline"), dict)
    ]
    assert outlines, rooms
    assert any(
        outline.get("provenance") == "isaac_usd_room_mesh_world_bounds" for outline in outlines
    ), outlines
    max_width = max(_polygon_extent(room.get("polygon") or [], "x") for room in rooms)
    max_depth = max(_polygon_extent(room.get("polygon") or [], "y") for room in rooms)
    assert max_width > 2.5 or max_depth > 2.5, rooms


def _is_base_metric_map(metric_map: dict[str, Any], runtime_map: dict[str, Any]) -> bool:
    base_map = metric_map.get("base_metric_map") or {}
    return bool(
        base_map.get("enabled") is True or runtime_map.get("generated_exploration_candidates")
    )


def _assert_isaac_scene_index_generated_candidate_scale(metric_map: dict[str, Any]) -> None:
    candidates = [
        item
        for item in metric_map.get("generated_exploration_candidates")
        or metric_map.get("inspection_waypoints")
        or []
        if isinstance(item, dict)
    ]
    assert candidates, metric_map
    assert all(
        (item.get("candidate_provenance") or {}).get("source") == "public_occupancy_free_space"
        for item in candidates
    ), candidates
    x_extent = max(float(item.get("x", 0.0)) for item in candidates) - min(
        float(item.get("x", 0.0)) for item in candidates
    )
    y_extent = max(float(item.get("y", 0.0)) for item in candidates) - min(
        float(item.get("y", 0.0)) for item in candidates
    )
    assert x_extent > 2.5 or y_extent > 2.5, candidates


def _polygon_extent(points: list[Any], axis: str) -> float:
    values = [
        float(point.get(axis, 0.0))
        for point in points
        if isinstance(point, dict) and point.get(axis) is not None
    ]
    if not values:
        return 0.0
    return max(values) - min(values)


def _assert_advisory_scoring(data: dict[str, Any], base: Path, report_text: str) -> None:
    advisory = data.get("advisory_evaluation") or {}
    assert advisory, data
    assert advisory.get("schema_version") == "advisory_cleanup_scoring_v1", advisory
    assert advisory.get("authoritative") is False, advisory
    assert advisory.get("status") == "ok", advisory
    reviews = advisory.get("object_reviews") or []
    if int(data.get("generated_mess_count") or 0) == 0:
        assert advisory.get("overall_verdict") == "no_targets", advisory
    else:
        assert reviews, advisory
    counts = advisory.get("counts") or {}
    assert int(counts.get("total_reviewed") or 0) == len(reviews), advisory
    artifacts = data.get("artifacts") or {}
    advisory_path = _resolve_path(base, artifacts.get("advisory_evaluation", ""))
    loaded = read_json_object(advisory_path, label="advisory evaluation")
    assert loaded.get("authoritative") is False, loaded
    assert "Advisory Review" in report_text, report_text[:500]


def _assert_raw_fpv_observations(
    data: dict[str, Any],
    base: Path,
    report_text: str,
) -> None:
    assert data.get("perception_mode") == "raw_fpv_only", data
    agent_view = data.get("agent_view") or {}
    assert agent_view_module.perception_mode(agent_view) == "raw_fpv_only", agent_view
    assert agent_view_module.structured_detections_available(agent_view) is False, agent_view
    observations = data.get("raw_fpv_observations") or _agent_view_raw_fpv_observations(agent_view)
    assert observations, data
    assert "Raw FPV Observations" in report_text, report_text[:500]
    artifacts = data.get("artifacts") or {}
    robot_views_dir = _resolve_path(base, artifacts.get("robot_views", ""))
    assert robot_views_dir.is_dir(), robot_views_dir
    for item in observations:
        assert item.get("perception_mode") == "raw_fpv_only", item
        assert item.get("structured_detections_available") is False, item
        assert not {"category", "name", "support_estimate", "target_receptacle_id"}.intersection(
            item
        ), item
        camera_contract = item.get("camera_control_contract")
        if camera_contract is not None:
            assert isinstance(camera_contract, dict), item
            assert camera_contract.get("schema") == "robot_view_camera_control_contract_v1", item
            assert isinstance(camera_contract.get("same_pose_api"), bool), item
        image_artifacts = item.get("image_artifacts") or {}
        fpv = image_artifacts.get("fpv") or item.get("fpv_image")
        assert fpv, item
        fpv_path = _resolve_path(base, str(fpv))
        if not fpv_path.exists():
            fpv_path = _resolve_path(robot_views_dir.parent, str(fpv))
        assert fpv_path.is_file(), (fpv_path, item)
        assert fpv_path.stat().st_size > 0, (fpv_path, item)


def _assert_camera_model_policy(
    data: dict[str, Any],
    base: Path,
    report_text: str,
    *,
    expect_pipeline_id: str | None = None,
    require_failure: bool = False,
    map_build: bool = False,
) -> None:
    backend_grounding_pipeline = _uses_backend_grounding_pipeline(data, map_build=map_build)
    assert data.get("perception_mode") == CAMERA_MODEL_POLICY_MODE, data
    agent_view = data.get("agent_view") or {}
    evidence = data.get("camera_model_policy_evidence") or (
        agent_view_module.camera_model_policy_evidence(agent_view) if agent_view else {}
    )
    assert evidence.get("schema") == CAMERA_MODEL_POLICY_SCHEMA, evidence
    assert evidence.get("enabled") is True, evidence
    pipeline_id = str(evidence.get("visual_grounding_pipeline_id") or "sim")
    pipeline_ids = [
        str(item)
        for item in (evidence.get("visual_grounding_pipeline_ids") or [pipeline_id])
        if item
    ]
    if not pipeline_ids:
        pipeline_ids = [pipeline_id]
    if expect_pipeline_id is not None:
        assert expect_pipeline_id in pipeline_ids, evidence
        overlay_pipeline_id = expect_pipeline_id
    else:
        overlay_pipeline_id = next(
            (item for item in pipeline_ids if item not in {"sim", "manual"}),
            pipeline_id,
        )
    if set(pipeline_ids) == {"sim"}:
        assert evidence.get("model_provenance") == SIMULATED_CAMERA_MODEL_PROVENANCE, evidence
    else:
        assert evidence.get("model_provenance") == "external_visual_grounding_service", evidence
    assert evidence.get("private_truth_included") is False, evidence
    assert int(evidence.get("event_count") or 0) >= 1, evidence
    failure_count = int(evidence.get("visual_grounding_failure_count") or 0)
    if require_failure:
        assert failure_count >= 1, evidence
    elif map_build and (data.get("runtime_metric_map") or {}).get("target_candidates"):
        assert int(evidence.get("event_count") or 0) >= 1, evidence
    else:
        assert int(evidence.get("candidate_count") or 0) >= 1, evidence
    assert evidence.get("events"), evidence
    _assert_visual_grounding_event_pipelines(evidence["events"], pipeline_ids=pipeline_ids)
    assert data.get("raw_fpv_observations"), data
    counts = data.get("tool_event_counts") or {}
    if not backend_grounding_pipeline:
        assert int(counts.get("declare_visual_candidates:request") or 0) >= 1, counts
    assert "Camera Labeler Evidence" in report_text, report_text[:500]
    assert "Raw FPV Observations" in report_text, report_text[:500]
    assert overlay_pipeline_id in report_text, report_text[:500]
    assert "Bearer " not in json.dumps(data), data
    assert "Bearer " not in report_text, report_text[:500]
    if (
        overlay_pipeline_id not in {"sim", "manual"}
        and not require_failure
        and not backend_grounding_pipeline
    ):
        _assert_external_visual_grounding_overlays(
            data,
            base,
            report_text,
            pipeline_id=overlay_pipeline_id,
        )


def _assert_visual_grounding_event_pipelines(
    events: list[dict[str, Any]], *, pipeline_ids: list[str]
) -> None:
    for event in events:
        pipeline = event.get("visual_grounding_pipeline") or {}
        assert pipeline.get("pipeline_id") in pipeline_ids, event
        assert pipeline.get("schema") == "visual_grounding_pipeline_v1", event
        assert pipeline.get("status") in {"ok", "failed"}, event
        stages = pipeline.get("stages") or []
        assert stages, event
        for stage in stages:
            assert stage.get("stage"), stage
            if pipeline.get("status") == "ok":
                assert "latency_ms" in stage, stage


def _uses_backend_grounding_pipeline(data: dict[str, Any], *, map_build: bool) -> bool:
    return map_build and data.get("backend_variant") == "agibot_gdk"


def _assert_model_declared_observations(
    data: dict[str, Any],
    report_text: str,
    *,
    min_observations: int,
    min_actions: int,
) -> None:
    agent_view = data.get("agent_view") or {}
    evidence = data.get("model_declared_observation_evidence") or (
        agent_view_module.model_declared_observation_evidence(agent_view) if agent_view else {}
    )
    observations = data.get("model_declared_observations") or evidence.get("observations") or []
    assert evidence.get("schema") == MODEL_DECLARED_OBSERVATIONS_SCHEMA, evidence
    assert evidence.get("private_truth_included") is False, evidence
    assert len(observations) >= min_observations, (len(observations), min_observations, data)
    assert int(evidence.get("observation_count") or 0) >= min_observations, evidence
    assert int(evidence.get("resolved_count") or 0) >= min_observations, evidence
    assert int(evidence.get("acted_count") or 0) >= min_actions, evidence
    for item in observations:
        assert str(item.get("object_id", "")).startswith("observed_"), item
        assert item.get("source_observation_id"), item
        assert item.get("producer_type"), item
        assert item.get("category"), item
        assert item.get("target_fixture_id") is not None, item
        assert item.get("image_region"), item
        assert item.get("evidence_note") is not None, item
        assert item.get("grounding_status") in {"resolved", "ambiguous", "unresolved"}, item
        assert "grounding_confidence" in item, item
        assert "grounding_basis" in item, item
        assert "target_plausibility" in item, item
        assert item.get("private_truth_included") is False, item
        _assert_no_forbidden_keys(item)
    counts = data.get("tool_event_counts") or {}
    declaration_requests = int(counts.get("declare_visual_candidates:request") or 0) + int(
        counts.get("navigate_to_visual_candidate:request") or 0
    )
    assert declaration_requests >= 1, counts
    assert "Model-Declared Observations" in report_text, report_text[:500]


def _assert_external_visual_grounding_overlays(
    data: dict[str, Any],
    base: Path,
    report_text: str,
    *,
    pipeline_id: str,
) -> None:
    agent_view = data.get("agent_view") or {}
    evidence = data.get("model_declared_observation_evidence") or (
        agent_view_module.model_declared_observation_evidence(agent_view) if agent_view else {}
    )
    observations = data.get("model_declared_observations") or evidence.get("observations") or []
    assert observations, data
    bbox_candidates_with_source = 0
    for item in observations:
        pipeline = item.get("visual_grounding_pipeline") or {}
        if str(pipeline.get("pipeline_id") or "") != pipeline_id:
            continue
        if item.get("producer_type") != EXTERNAL_VISUAL_GROUNDING_PROVENANCE:
            continue
        image_region = item.get("image_region") or {}
        if image_region.get("type") != "bbox":
            continue
        source_image_path = _raw_fpv_image_path_for_observation(
            data,
            base,
            observation_id=str(item.get("source_observation_id") or ""),
        )
        if source_image_path is None or not source_image_path.is_file():
            continue
        bbox_candidates_with_source += 1
        overlay = str(item.get("visual_grounding_overlay") or "")
        assert overlay, item
        overlay_path = _resolve_path(base, overlay)
        assert overlay_path.is_file(), (overlay_path, item)
        assert overlay_path.stat().st_size > 0, (overlay_path, item)
    if bbox_candidates_with_source:
        assert "Overlay" in report_text, report_text[:500]


def _raw_fpv_image_path_for_observation(
    data: dict[str, Any],
    base: Path,
    *,
    observation_id: str,
) -> Path | None:
    agent_view = data.get("agent_view") or {}
    observations = data.get("raw_fpv_observations") or _agent_view_raw_fpv_observations(agent_view)
    for item in observations:
        if str(item.get("observation_id") or "") != observation_id:
            continue
        image_artifacts = item.get("image_artifacts") or {}
        fpv = image_artifacts.get("fpv") or item.get("fpv_image")
        if not fpv:
            return None
        return _resolve_path(base, str(fpv))
    return None


def _assert_planner_proof_attachment(
    data: dict[str, Any],
    base: Path,
    report_text: str,
    *,
    require_quality: bool = False,
    min_steps_executed: int | None = None,
) -> None:
    assert data.get("primitive_provenance") in {
        API_SEMANTIC_PROVENANCE,
        "planner_backed",
    }, data
    evidence = data.get("manipulation_evidence") or {}
    assert evidence.get("primitive_provenance") in {
        API_SEMANTIC_PROVENANCE,
        "planner_backed",
    }, evidence
    attachment = data.get("planner_backed_manipulation_proof") or {}
    if attachment.get("schema") == PLANNER_PROOF_BUNDLE_SCHEMA:
        validate_planner_proof_bundle(attachment)
        proof_attachments = planner_proof_attachments(attachment)
        assert "Attached Planner-Backed Proofs" in report_text, report_text[:500]
    else:
        validate_planner_proof_attachment(attachment)
        proof_attachments = [attachment]
        assert "Attached Planner-Backed Proof" in report_text, report_text[:500]
    for proof in proof_attachments:
        quality = planner_proof_quality_evidence(proof)
        validate_planner_proof_quality_evidence(
            quality,
            min_steps_executed=min_steps_executed or 1,
        )
        if require_quality:
            assert "Proof Quality" in report_text, report_text[:500]
            assert str(quality.get("quality_tier") or "") in report_text, report_text[:500]
        for value in (proof.get("image_artifacts") or {}).values():
            path = _resolve_path(base, str(value))
            assert path.is_file(), path
            assert path.stat().st_size > 0, path
    assert "Planner Initial" in report_text, report_text[:500]
    assert "Planner Final" in report_text, report_text[:500]
    if attachment.get("schema") != PLANNER_PROOF_BUNDLE_SCHEMA:
        assert "Cleanup object moves" in report_text, report_text[:500]


def _assert_cleanup_primitive_gate(
    data: dict[str, Any],
    report_text: str,
    *,
    accept_blocked: bool = False,
    require_planner_backed: bool = False,
) -> None:
    evidence = data.get("cleanup_primitive_evidence") or {}
    validate_cleanup_primitive_evidence(
        evidence,
        accept_blocked_capability=accept_blocked,
        require_planner_backed=require_planner_backed,
    )
    assert "Cleanup Primitive Gate" in report_text, report_text[:500]
    assert "Display subphase" in report_text, report_text[:500]
    assert "Subphase role" in report_text, report_text[:500]
    if require_planner_backed:
        assert data.get("primitive_provenance") != API_SEMANTIC_PROVENANCE, data


def _assert_bound_planner_cleanup_objects(
    data: dict[str, Any],
    report_text: str,
    specs: list[str],
) -> None:
    assert data.get("planner_proof_cleanup_executor_enabled") is True, data
    evidence = data.get("cleanup_primitive_evidence") or {}
    assert evidence.get("schema") == "planner_backed_cleanup_primitives_v1", evidence
    objects = evidence.get("objects") or []
    assert objects, evidence
    for spec in specs:
        object_id, target_receptacle_id = _parse_bound_object_spec(spec)
        row = next(
            (
                item
                for item in objects
                if item.get("object_id") == object_id
                and item.get("target_receptacle_id") == target_receptacle_id
            ),
            None,
        )
        assert row is not None, (spec, objects)
        assert row.get("planner_backed") is True, row
        assert row.get("strict_proof_eligible") is True, row
        subphases = row.get("subphases") or []
        assert subphases, row
        required_phases = _required_bound_cleanup_phases(subphases)
        assert required_phases <= {str(step.get("phase") or "") for step in subphases}, row
        for step in subphases:
            assert step.get("primitive_provenance") == "planner_backed", step
            assert step.get("planner_backed") is True, step
            assert step.get("strict_proof_eligible") is True, step
            assert step.get("status") == "ok", step
            assert step.get("object_id_matches") is True, step
            assert step.get("target_receptacle_id_matches") is True, step
        assert object_id in report_text, report_text[:500]
        assert target_receptacle_id in report_text, report_text[:500]
        assert "planner_backed" in report_text, report_text[:500]


def _required_bound_cleanup_phases(subphases: list[dict[str, Any]]) -> set[str]:
    phases = {str(step.get("phase") or "") for step in subphases}
    required = set(CANONICAL_SURFACE_CLEANUP_PHASES)
    if PLACE_INSIDE_PHASE in phases:
        required = required - {"place"} | {PLACE_INSIDE_PHASE}
    return required | (phases & {OPEN_RECEPTACLE_PHASE, CLOSE_RECEPTACLE_PHASE})


def _assert_mixed_planner_cleanup_primitives(
    data: dict[str, Any],
    report_text: str,
) -> None:
    evidence = data.get("cleanup_primitive_evidence") or {}
    assert evidence.get("status") == "blocked_capability", evidence
    assert evidence.get("planner_backed") is False, evidence
    assert data.get("primitive_provenance") == API_SEMANTIC_PROVENANCE, data
    objects = evidence.get("objects") or []
    assert any(item.get("planner_backed") is True for item in objects), objects
    assert any(item.get("planner_backed") is False for item in objects), objects
    summary = evidence.get("primitive_provenance_summary") or {}
    assert int(summary.get("planner_backed") or 0) >= 1, summary
    assert int(summary.get(API_SEMANTIC_PROVENANCE) or 0) >= 1, summary
    blockers = evidence.get("blockers") or []
    assert any(
        blocker.get("code") == "cleanup_subphase_not_planner_backed" for blocker in blockers
    ), blockers
    assert "Cleanup Primitive Gate" in report_text, report_text[:500]
    assert "blocked_capability" in report_text, report_text[:500]


def _parse_bound_object_spec(spec: str) -> tuple[str, str]:
    object_id, sep, target_receptacle_id = spec.partition(":")
    assert sep and object_id and target_receptacle_id, spec
    return object_id, target_receptacle_id


def _assert_planner_cleanup_bridge(
    data: dict[str, Any],
    report_text: str,
    *,
    accept_blocked: bool = False,
    require_ready: bool = False,
) -> None:
    evidence = data.get("planner_cleanup_bridge_evidence") or {}
    validate_planner_cleanup_bridge_evidence(
        evidence,
        accept_blocked_capability=accept_blocked,
        require_ready=require_ready,
    )
    assert "Planner Cleanup Bridge" in report_text, report_text[:500]
    if require_ready:
        assert data.get("primitive_provenance") != API_SEMANTIC_PROVENANCE, data


def _assert_waypoint_honesty(data: dict[str, Any], report_text: str) -> None:
    assert_waypoint_honesty(
        data,
        report_text,
        open_ended_intent=_is_open_ended_intent(data),
        map_build=_is_map_build(data),
    )


def _is_open_ended_intent(data: dict[str, Any]) -> bool:
    goal_contract = data.get("goal_contract") if isinstance(data.get("goal_contract"), dict) else {}
    intent = str(data.get("task_intent") or goal_contract.get("intent") or "").strip()
    return intent == "open-ended"


def _agent_view_runtime_metric_map(agent_view: dict[str, Any]) -> dict[str, Any]:
    if not agent_view:
        return {}
    return agent_view_module.runtime_metric_map(agent_view)


def _agent_view_raw_fpv_observations(agent_view: dict[str, Any]) -> list[dict[str, Any]]:
    if not agent_view:
        return []
    return agent_view_module.raw_fpv_observations(agent_view)


def _post_place_observe_count_allowing_public_state_queries(trace: dict[str, Any]) -> int:
    return post_place_observe_count_allowing_public_state_queries(trace)


def _assert_real_robot_alignment(data: dict[str, Any], base: Path, report_text: str) -> None:
    agent_view = data.get("agent_view") or {}
    metric_map = agent_view_module.base_metric_map(agent_view)
    runtime_metric_map = data.get("runtime_metric_map") or _agent_view_runtime_metric_map(
        agent_view
    )
    static_map = runtime_metric_map.get("static_map") or {}
    assert metric_map.get("schema") == REAL_ROBOT_MAP_BUNDLE_SCHEMA, metric_map
    for key in (
        "frame_id",
        "map_id",
        "map_version",
        "resolution_m",
        "origin",
        "width",
        "height",
        "occupancy_values",
        "map_bundle",
        "robot_pose",
    ):
        assert key in metric_map, metric_map
    map_bundle_metadata = metric_map.get("map_bundle") or {}
    assert map_bundle_metadata.get("schema") == "nav2_map_bundle_v1", map_bundle_metadata
    assert map_bundle_metadata.get("robot_profile_id") == "rby1m", map_bundle_metadata
    assert map_bundle_metadata.get("parameter_hash"), map_bundle_metadata
    waypoints = metric_map.get("inspection_waypoints") or []
    assert waypoints, metric_map
    for waypoint in waypoints:
        for key in ("frame_id", "x", "y", "yaw", "room_id", "label", "visited", "purpose"):
            assert key in waypoint, waypoint
    assert static_map.get("contains_runtime_observations") is False, static_map
    assert "observations" not in static_map, static_map
    for fixture in static_map.get("fixtures") or []:
        assert fixture.get("fixture_id"), fixture
        assert fixture.get("affordances"), fixture
        assert fixture.get("pose", {}).get("frame_id") == "map", fixture
        assert "observed_objects" not in fixture, fixture
    policy_view = agent_view_module.policy_view(agent_view)
    assert policy_view.get("chase_camera_policy_input") is False, policy_view
    assert not any("chase" in str(item).lower() for item in policy_view.get("allowed_inputs", []))
    readiness = data.get("real_robot_readiness") or {}
    assert readiness.get("schema") == REAL_ROBOT_READINESS_SCHEMA, readiness
    assert readiness.get("map_bundle_fields_present") is True, readiness
    assert readiness.get("pose_stamped_waypoints") is True, readiness
    assert readiness.get("public_static_map") is True, readiness
    assert readiness.get("static_fixture_projection") is False, readiness
    assert readiness.get("policy_view_chase_excluded") is True, readiness
    assert readiness.get("semantic_navigation_only") is True, readiness
    assert readiness.get("sim_costmap_route_validation") is True, readiness
    assert readiness.get("real_robot_ready") is False, readiness
    assert readiness.get("physical_navigation_pilot") is False, readiness
    assert readiness.get("physical_cleanup_ready") is False, readiness
    assert readiness.get("map_bundle_snapshot_present") is True, readiness
    assert readiness.get("map_bundle_parameter_hash"), readiness
    assert readiness.get("navigation_backend_summary", {}).get(SIM_COSTMAP_PLANNER), readiness
    nav2_bundle = data.get("nav2_map_bundle") or {}
    assert nav2_bundle.get("schema") == "nav2_map_bundle_snapshot_v1", nav2_bundle
    assert nav2_bundle.get("snapshot_complete") is True, nav2_bundle
    artifact_paths = nav2_bundle.get("artifact_paths") or {}
    artifact_hashes = nav2_bundle.get("artifact_hashes") or {}
    for key in (
        "map_yaml",
        "occupancy_image",
        "semantics_json",
        "robot_profile",
        "costmap_params",
        "preview_png",
    ):
        assert key in artifact_paths, nav2_bundle
        assert key in artifact_hashes, nav2_bundle
        assert len(str(artifact_hashes[key])) == 64, artifact_hashes
        assert _resolve_path(base, str(artifact_paths[key])).is_file(), artifact_paths[key]
    assert "Real-Robot Readiness" in report_text, report_text[:500]
    assert "Nav2 Map Bundle" in report_text, report_text[:500]
    assert "map_bundle/map.yaml" in report_text, report_text[:500]
    assert "report_only_simulation_view" in report_text, report_text[:500]


def _assert_b1_robot_consumption_proof(data: dict[str, Any], base: Path) -> None:
    nav2_bundle = data.get("nav2_map_bundle") or {}
    assert nav2_bundle.get("schema") == "nav2_map_bundle_snapshot_v1", nav2_bundle
    assert nav2_bundle.get("snapshot_complete") is True, nav2_bundle
    artifact_paths = nav2_bundle.get("artifact_paths") or {}
    artifact_hashes = nav2_bundle.get("artifact_hashes") or {}
    semantics_path = _resolve_path(base, str(artifact_paths.get("semantics_json") or ""))
    assert len(str(artifact_hashes.get("semantics_json") or "")) == 64, artifact_hashes
    semantics = read_json_object(semantics_path, label="B1 Nav2 semantics")
    assert semantics.get("schema") == "nav2_cleanup_semantics_v1", semantics
    assert semantics.get("environment_id") == "agibot-robot-map-12", semantics
    assert (semantics.get("spatial_contract") or {}).get("alignment_status") == "verified", (
        semantics.get("spatial_contract") or {}
    )
    proof = (
        (semantics.get("digital_twin_capabilities") or {}).get("robot_consumption_proof")
    ) or {}
    assert proof.get("schema") == "b1_map12_robot_consumption_proof_v1", proof
    assert proof.get("status") == "robot_navigation_verified", proof
    assert proof.get("alignment_status") == "verified", proof
    assert proof.get("navigation_status") == "verified", proof
    assert proof.get("robot_navigation_supported") is True, proof
    assert proof.get("robot_navigation_provenance") == "isaac_b1_map12_navigation_smoke", proof
    assert int(proof.get("navigation_waypoint_count") or 0) >= 1, proof
    assert proof.get("alignment_artifact"), proof
    assert proof.get("navigation_artifact"), proof
    assert proof.get("physical_robot") is False, proof
    assert proof.get("manipulation_supported") is False, proof
    _assert_b1_robot_consumption_manifest(base, proof)


def _assert_b1_robot_consumption_manifest(base: Path, proof: dict[str, Any]) -> None:
    manifest_path = base / "b1_robot_consumption_manifest.json"
    manifest = read_json_object(manifest_path, label="B1 robot consumption manifest")
    assert manifest.get("schema") == "b1_map12_robot_consumption_manifest_v1", manifest
    assert manifest.get("status") == "robot_navigation_ready", manifest
    navigation = manifest.get("navigation") if isinstance(manifest.get("navigation"), dict) else {}
    assert navigation.get("ready") is True, navigation
    assert navigation.get("status") == proof.get("status"), navigation
    assert navigation.get("alignment_status") == proof.get("alignment_status"), navigation
    assert navigation.get("navigation_status") == proof.get("navigation_status"), navigation
    assert navigation.get("alignment_artifact") == proof.get("alignment_artifact"), navigation
    assert navigation.get("navigation_artifact") == proof.get("navigation_artifact"), navigation
    assert navigation.get("robot_navigation_provenance") == proof.get(
        "robot_navigation_provenance"
    ), navigation
    assert int(navigation.get("navigation_waypoint_count") or 0) == int(
        proof.get("navigation_waypoint_count") or 0
    ), navigation
    capabilities = (
        manifest.get("capabilities") if isinstance(manifest.get("capabilities"), dict) else {}
    )
    assert capabilities.get("robot_navigation") is True, capabilities
    assert capabilities.get("manipulation") is False, capabilities
    semantics = manifest.get("semantics") if isinstance(manifest.get("semantics"), dict) else {}
    assert semantics.get("object_projection_status") == "blocked_until_object_semantic_anchors", (
        semantics
    )
    policy = manifest.get("policy") if isinstance(manifest.get("policy"), dict) else {}
    assert policy.get("no_output_directory_autodiscovery") is True, policy
    assert policy.get("object_labels_are_not_inferred_from_room_anchors") is True, policy


def _has_planner_proof_requests(data: dict[str, Any]) -> bool:
    artifacts = data.get("artifacts") or {}
    return bool(data.get("planner_proof_requests") or artifacts.get("planner_proof_requests"))


def _assert_planner_proof_requests(data: dict[str, Any], base: Path, report_text: str) -> None:
    artifacts = data.get("artifacts") or {}
    manifest = data.get("planner_proof_requests")
    if manifest is None and artifacts.get("planner_proof_requests"):
        path = _resolve_path(base, str(artifacts["planner_proof_requests"]))
        manifest = read_json_object(path, label="planner proof requests")
    if manifest is None:
        return
    assert "Planner Proof Requests" in report_text, report_text[:500]
    assert manifest.get("schema") == PLANNER_PROOF_REQUESTS_SCHEMA, manifest
    assert manifest.get("agent_view_exposed") is False, manifest
    requests = manifest.get("requests") or []
    assert manifest.get("request_count") == len(requests), manifest
    semantic_substeps = data.get("semantic_substeps") or []
    if semantic_substeps:
        assert len(requests) == len(semantic_substeps), manifest
    for request in requests:
        assert request.get("object_id"), request
        if request.get("ready") is False:
            assert request.get("blockers"), request
        else:
            assert request.get("target_receptacle_id"), request
        assert "planner_probe_args" in request, request
    assert "planner_proof_requests" not in data.get("agent_view", {}), data.get("agent_view")


def _is_focused_robot_action(action: str) -> bool:
    return action.startswith(
        (
            "navigate_to_waypoint ",
            "observe ",
            f"{NAVIGATE_TO_VISUAL_CANDIDATE_TOOL} ",
            *FOCUSED_SEMANTIC_ACTION_PREFIXES,
        )
    )


def _canonical_robot_view_phase(step: dict[str, Any], action: str) -> str:
    semantic_phase = step.get("semantic_phase")
    if isinstance(semantic_phase, str) and semantic_phase:
        return semantic_phase
    action_evidence = step.get("action_evidence")
    if isinstance(action_evidence, dict):
        backend_primitive = action_evidence.get("backend_primitive")
        if isinstance(backend_primitive, str) and backend_primitive:
            return backend_primitive
    return action.split(" ", 1)[0]


def _assert_focused_robot_step(step: dict[str, Any]) -> None:
    focus = annotate_focus_visual_grounding(step.get("focus") or {}) or {}
    assert focus.get("has_focus") is True, step
    if _has_reviewable_source_fpv_action_evidence(step):
        return
    fpv_visibility = focus.get("fpv_visibility") or {}
    verify_visibility = focus.get("visibility") or {}
    visibility_states = [
        _focus_visibility_grounding_state(fpv_visibility, focus, step),
        _focus_visibility_grounding_state(verify_visibility, focus, step),
    ]
    if _has_reviewable_place_surface_evidence(step, focus):
        return
    assert any(state == "grounded" for state in visibility_states) or all(
        state == "unavailable" for state in visibility_states
    ), step


def _has_reviewable_source_fpv_action_evidence(step: dict[str, Any]) -> bool:
    action_evidence = step.get("action_evidence")
    if not isinstance(action_evidence, dict):
        return False
    if action_evidence.get("backend_primitive") != "navigate_to_object":
        return False
    if action_evidence.get("candidate_state") != "navigation_authorized":
        return False
    if action_evidence.get("reviewability_status") != "reviewable":
        return False
    if action_evidence.get("locality_status") != "same_waypoint_source_observation":
        return False
    if not action_evidence.get("source_observation_id"):
        return False
    bbox = action_evidence.get("source_image_bbox")
    return isinstance(bbox, list) and len(bbox) == 4


def _has_reviewable_place_surface_evidence(
    step: dict[str, Any],
    focus: dict[str, Any],
) -> bool:
    if step.get("semantic_phase") not in {"place", "place_inside"}:
        return False
    if not (focus.get("object_id") or focus.get("object_body_name") or focus.get("object_label")):
        return False
    if not (
        focus.get("receptacle_id")
        or focus.get("receptacle_body_name")
        or focus.get("receptacle_label")
    ):
        return False
    if not (focus.get("object_location_relation") or focus.get("object_contained_in")):
        return False
    visibilities = [focus.get("fpv_visibility") or {}, focus.get("visibility") or {}]
    return any(
        visibility.get("status") == "weak_object_visibility"
        and int(visibility.get("receptacle_pixels") or 0) > 0
        for visibility in visibilities
    )


def _focus_visibility_grounding_state(
    visibility: dict[str, Any],
    focus: dict[str, Any],
    step: dict[str, Any],
) -> str:
    status = visibility.get("status")
    assert status in {
        "ok",
        "contained_inside",
        "segmentation_unavailable",
        "weak_object_visibility",
    }, step
    if status == "segmentation_unavailable":
        return "unavailable"
    if status == "contained_inside":
        return "grounded"
    if status == "weak_object_visibility":
        return "weak"
    has_object_focus = bool(
        focus.get("object_id") or focus.get("object_body_name") or focus.get("object_label")
    )
    if status == "ok" and "object_pixels" in visibility and has_object_focus:
        assert int(visibility.get("object_pixels") or 0) > 0, step
    return "grounded"


def _assert_no_forbidden_keys(payload: Any) -> None:
    if isinstance(payload, dict):
        forbidden = forbidden_agent_view_keys().intersection(payload)
        assert not forbidden, (sorted(forbidden), payload)
        for value in payload.values():
            _assert_no_forbidden_keys(value)
    elif isinstance(payload, list):
        for value in payload:
            _assert_no_forbidden_keys(value)


def _resolve_path(base: Path, value: str) -> Path:
    path = Path(value)
    if path.is_absolute() or path.exists():
        return path
    repo_path = Path(__file__).resolve().parents[2] / path
    if repo_path.exists():
        return repo_path
    return base / path


if __name__ == "__main__":
    main()
