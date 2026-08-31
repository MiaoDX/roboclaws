#!/usr/bin/env python3
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from PIL import Image, ImageStat

from roboclaws.core.json_sources import read_json_object
from roboclaws.household import agent_view as agent_view_module
from roboclaws.household.cleanup_validation_base_map import (
    assert_base_metric_map as _assert_base_metric_map,
)
from roboclaws.household.cleanup_validation_isaac import (
    assert_isaac_runtime as _assert_isaac_backend_runtime,
)
from roboclaws.household.cleanup_validation_planner import (
    _assert_focused_robot_step,
    _canonical_robot_view_phase,
    _is_focused_robot_action,
)
from roboclaws.household.cleanup_validation_support import (
    agent_view_raw_fpv_observations as _agent_view_raw_fpv_observations,
)
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
    CAMERA_MODEL_POLICY_MODE,
    CAMERA_MODEL_POLICY_SCHEMA,
    MODEL_DECLARED_OBSERVATIONS_SCHEMA,
    SIMULATED_CAMERA_MODEL_PROVENANCE,
)
from roboclaws.household.household_runtime_contract import (
    RUNTIME_METRIC_MAP_SCHEMA as RUNTIME_METRIC_MAP_SCHEMA,
)
from roboclaws.household.isaac_lab_backend import (
    ISAACLAB_ROBOT_VIEW_VARIANT,
    ISAACLAB_SUBPROCESS_BACKEND,
)
from roboclaws.household.semantic_timeline import (
    CANONICAL_SURFACE_CLEANUP_PHASES,
    CLOSE_RECEPTACLE_PHASE,
    OPEN_RECEPTACLE_PHASE,
    PLACE_INSIDE_PHASE,
)
from roboclaws.household.visual_grounding import EXTERNAL_VISUAL_GROUNDING_PROVENANCE


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
        if expect_pipeline_id not in {None, "sim"}:
            raise AssertionError("grounded evidence cannot use simulator pipeline")
        assert evidence.get("model_provenance") == SIMULATED_CAMERA_MODEL_PROVENANCE, evidence
    else:
        assert evidence.get("model_provenance") == "external_visual_grounding_service", evidence
    assert evidence.get("private_truth_included") is False, evidence
    assert int(evidence.get("event_count") or 0) >= 1, evidence
    failure_count = int(evidence.get("visual_grounding_failure_count") or 0)
    if require_failure:
        assert failure_count >= 1, evidence
    elif (
        map_build
        and pipeline_id not in {"sim", "manual"}
        and (data.get("runtime_metric_map") or {}).get("target_candidates")
    ):
        assert int(evidence.get("event_count") or 0) >= 1, evidence
        assert int(evidence.get("candidate_count") or 0) >= 1, evidence
    else:
        if pipeline_id not in {"sim", "manual"}:
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
