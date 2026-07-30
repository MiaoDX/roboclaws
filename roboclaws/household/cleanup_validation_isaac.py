from __future__ import annotations

import json
from collections.abc import Callable
from pathlib import Path
from typing import Any

from PIL import Image, ImageStat

from roboclaws.core.json_sources import read_json_object
from roboclaws.household.cleanup_validation_isaac_pose import (
    assert_isaac_runtime_semantic_pose,
)
from roboclaws.household.isaac_lab_backend import (
    ISAAC_SCENE_INDEX_ARTIFACT_SCHEMA,
    ISAACLAB_ROBOT_VIEW_VARIANT,
    ISAACLAB_SUBPROCESS_BACKEND,
)
from roboclaws.household.manipulation_contract import ISAAC_SEMANTIC_POSE_PROVENANCE

ISAAC_PUBLIC_SCENE_BINDING_SCHEMA = "isaac_public_scene_bindings_v1"


def _resolve_path(base: Path, value: str) -> Path:
    path = Path(value)
    if path.is_absolute() or path.exists():
        return path
    repo_path = Path(__file__).resolve().parents[2] / path
    if repo_path.exists():
        return repo_path
    return base / path


def assert_isaac_runtime(
    data: dict[str, Any],
    base: Path,
    report_text: str,
    *,
    assert_robot_views: Callable[..., None],
    require_real_runtime: bool,
    require_scene_loaded: bool,
    require_local_scene_usd: bool = False,
    require_selected_usd_bindings: bool,
    require_semantic_pose: bool,
    require_robot_view_provenance: bool,
    require_segmentation_evidence: bool,
    require_snapshot_provenance: bool,
) -> None:
    isaac = _assert_isaac_runtime_core(
        data,
        base,
        report_text,
        require_real_runtime=require_real_runtime,
        require_scene_loaded=require_scene_loaded,
        require_local_scene_usd=require_local_scene_usd,
    )
    scene_bindings = isaac.get("scene_binding_diagnostics") or {}
    scene_index_payload = _assert_isaac_scene_binding_gate(
        data,
        base,
        report_text,
        isaac,
        scene_bindings,
        require_selected_usd_bindings=require_selected_usd_bindings,
    )
    if require_semantic_pose:
        assert_isaac_runtime_semantic_pose(
            data,
            base,
            report_text,
            isaac,
            scene_bindings=scene_bindings if require_selected_usd_bindings else None,
            scene_index_payload=scene_index_payload,
        )
    if require_robot_view_provenance:
        _assert_isaac_robot_view_provenance(
            data,
            base,
            isaac,
            assert_robot_views=assert_robot_views,
        )
    if require_segmentation_evidence:
        _assert_isaac_segmentation_evidence(
            isaac.get("segmentation") or {},
            scene_index_payload,
            report_text,
        )
    if require_snapshot_provenance:
        _assert_isaac_snapshot_provenance(isaac, base)


def _assert_isaac_runtime_core(
    data: dict[str, Any],
    base: Path,
    report_text: str,
    *,
    require_real_runtime: bool,
    require_scene_loaded: bool,
    require_local_scene_usd: bool,
) -> dict[str, Any]:
    assert data.get("backend") == ISAACLAB_SUBPROCESS_BACKEND, data
    isaac = data.get("isaac_runtime") or {}
    assert isaac, data
    assert "Isaac Runtime Diagnostics" in report_text, report_text[:500]
    runtime = isaac.get("runtime") or {}
    segmentation = isaac.get("segmentation") or {}
    assert runtime.get("primitive_provenance") == ISAAC_SEMANTIC_POSE_PROVENANCE, runtime
    assert segmentation.get("status") in {"blocked_capability", "available", "unavailable"}, (
        segmentation
    )
    assert segmentation.get("agent_facing") is not True, segmentation
    assert segmentation.get("no_simulator_label_fallback") is not False, segmentation
    if require_real_runtime:
        rendering = runtime.get("rendering") or {}
        assert runtime.get("runtime_mode") == "real", runtime
        _assert_isaac_real_runtime_diagnostics(runtime)
        assert rendering.get("real_rendering_proven") is True, rendering
        assert rendering.get("placeholder_visuals") is not True, rendering
        assert rendering.get("status") == "real_rendering_proven", rendering
    if require_scene_loaded or require_local_scene_usd:
        scene_load = isaac.get("scene_load") or {}
        _assert_isaac_scene_loaded(isaac, scene_load, base)
        if require_local_scene_usd:
            assert scene_load.get("loaded_asset_kind") == "local_scene_usd", scene_load
    return isaac


def _assert_isaac_scene_binding_gate(
    data: dict[str, Any],
    base: Path,
    report_text: str,
    isaac: dict[str, Any],
    scene_bindings: dict[str, Any],
    *,
    require_selected_usd_bindings: bool,
) -> dict[str, Any] | None:
    if not require_selected_usd_bindings:
        return None
    _assert_selected_isaac_usd_bindings(scene_bindings)
    scene_index_payload = _assert_isaac_scene_index_artifact(data, isaac, base)
    _assert_isaac_scene_index_matches_runtime_bindings(
        scene_bindings,
        scene_index_payload.get("scene_binding_diagnostics") or {},
    )
    _assert_isaac_scene_index_report_rows(
        scene_index_payload.get("scene_binding_diagnostics") or scene_bindings,
        report_text,
    )
    return scene_index_payload


def _assert_isaac_robot_view_provenance(
    data: dict[str, Any],
    base: Path,
    isaac: dict[str, Any],
    *,
    assert_robot_views: Callable[..., None],
) -> None:
    assert_robot_views(data, base, require_complete_actions=False)
    assert data.get("view_variant") == ISAACLAB_ROBOT_VIEW_VARIANT, data
    steps = data.get("robot_view_steps") or []
    assert steps, data
    semantic_pose_state = isaac.get("semantic_pose_state") or {}
    require_refreshed_views = semantic_pose_state.get("rendered_to_usd") is True
    for step in steps:
        _assert_isaac_robot_view_step(
            step,
            base,
            semantic_pose_state,
            require_refreshed_views=require_refreshed_views,
        )


def _assert_isaac_robot_view_step(
    step: dict[str, Any],
    base: Path,
    semantic_pose_state: dict[str, Any],
    *,
    require_refreshed_views: bool,
) -> None:
    provenance = step.get("view_provenance") or {}
    provenance_text = json.dumps(provenance, sort_keys=True).lower()
    camera_contract = step.get("camera_control_contract") or {}
    assert camera_contract.get("schema") == "robot_view_camera_control_contract_v1", step
    assert "placeholder" not in provenance_text, step
    assert "isaac_lab_camera_rgb" in provenance_text, step
    if require_refreshed_views:
        assert provenance.get("semantic_pose_state_refreshed") is True, step
        assert "isaac_lab_camera_rgb_semantic_pose_robot_views" in provenance_text, step
        _assert_isaac_refreshed_robot_view_camera_contract(
            camera_contract,
            semantic_pose_state.get("semantic_pose_view_capture") or {},
            step,
        )
    else:
        _assert_isaac_bounds_camera_contract(camera_contract, step)
    views = step.get("views") or {}
    assert isinstance(views, dict), step
    for key in ("fpv", "chase", "topdown", "verify"):
        _assert_nonblank_image(
            _resolve_path(base, str(views.get(key) or "")),
            f"Isaac {key} robot view",
        )


def _assert_isaac_refreshed_robot_view_camera_contract(
    camera_contract: dict[str, Any],
    capture: dict[str, Any],
    step: dict[str, Any],
) -> None:
    if capture.get("robot_mounted_head_camera") is True:
        assert camera_contract.get("same_pose_api") is False, step
        assert camera_contract.get("camera_control_api") is None, step
        assert camera_contract.get("status") == "robot_mounted_head_camera_robot_view", step
        assert camera_contract.get("camera_model") == "robot_mounted_head_camera_v1", step
        assert (camera_contract.get("agent_facing_fpv") or {}).get("robot_mounted") is True, step
        assert camera_contract.get("camera_prim_path") == "/World/robot_0/head_camera", step
    elif capture.get("head_camera_equivalent") is True:
        assert camera_contract.get("same_pose_api") is False, step
        assert camera_contract.get("camera_control_api") is None, step
        assert camera_contract.get("status") == "robot_head_camera_equivalent_robot_view", step
        assert camera_contract.get("camera_model") == "robot_head_camera_equivalent_v1", step
    else:
        _assert_isaac_bounds_camera_contract(camera_contract, step)


def _assert_isaac_bounds_camera_contract(
    camera_contract: dict[str, Any],
    step: dict[str, Any],
) -> None:
    assert camera_contract.get("same_pose_api") is False, step
    assert camera_contract.get("camera_control_api") is None, step
    assert camera_contract.get("status") == "backend_local_scene_bounds_camera", step


def _assert_isaac_segmentation_evidence(
    segmentation: dict[str, Any],
    scene_index_payload: dict[str, Any] | None,
    report_text: str,
) -> None:
    assert segmentation.get("schema") == "isaac_segmentation_diagnostics_v1", segmentation
    assert segmentation.get("status") == "available", segmentation
    assert segmentation.get("available") is True, segmentation
    assert segmentation.get("tensor_output_available") is True, segmentation
    assert segmentation.get("candidate_overlay_status") == "available", segmentation
    assert int(segmentation.get("candidate_bbox_count") or 0) > 0, segmentation
    assert int(segmentation.get("selected_usd_prim_match_count") or 0) > 0, segmentation
    assert segmentation.get("agent_facing") is False, segmentation
    assert segmentation.get("no_simulator_label_fallback") is True, segmentation
    assert "Segmentation" in report_text, report_text[:500]
    if scene_index_payload is not None:
        _assert_isaac_scene_index_matches_runtime_segmentation(
            segmentation,
            scene_index_payload.get("segmentation") or {},
        )


def _assert_isaac_real_runtime_diagnostics(runtime: dict[str, Any]) -> None:
    assert runtime.get("python_version"), runtime
    assert runtime.get("isaac_sim_version"), runtime
    assert runtime.get("isaac_lab_version"), runtime
    assert runtime.get("cuda_available") is True, runtime
    assert runtime.get("gpu_name"), runtime
    assert int(runtime.get("gpu_vram_mb") or 0) > 0, runtime
    assert runtime.get("renderer_mode"), runtime
    camera_resolution = runtime.get("camera_resolution")
    assert isinstance(camera_resolution, list), runtime
    assert len(camera_resolution) == 2, runtime
    assert all(int(value or 0) > 0 for value in camera_resolution), runtime


def _assert_isaac_scene_loaded(
    isaac: dict[str, Any],
    scene_load: dict[str, Any],
    base: Path,
) -> None:
    assert scene_load.get("status") == "loaded", scene_load
    assert scene_load.get("usd_stage_loaded") is True, scene_load
    assert scene_load.get("loaded_asset_kind"), scene_load
    assert scene_load.get("manual_editor_steps_required") is False, scene_load
    scene_usd = str(isaac.get("scene_usd") or scene_load.get("scene_usd") or "")
    assert scene_usd, isaac
    scene_path = Path(scene_usd)
    if scene_path.is_absolute():
        assert scene_path.is_file(), scene_path
    else:
        resolved = _resolve_path(base, scene_usd)
        assert resolved.is_file(), resolved


def _assert_selected_isaac_usd_bindings(scene_bindings: dict[str, Any]) -> None:
    _assert_selected_isaac_usd_bindings_for_indexes(scene_bindings)


def _assert_selected_isaac_usd_bindings_for_indexes(
    scene_bindings: dict[str, Any],
    *,
    object_index: dict[str, Any] | None = None,
    receptacle_index: dict[str, Any] | None = None,
) -> None:
    assert scene_bindings.get("schema") == ISAAC_PUBLIC_SCENE_BINDING_SCHEMA, scene_bindings
    assert scene_bindings.get("status") == "selected_bound", scene_bindings
    assert scene_bindings.get("source") == "usd_stage_traversal", scene_bindings
    assert scene_bindings.get("private_manifest_exposed_to_agent") is False, scene_bindings
    selected_object_count = int(scene_bindings.get("selected_object_count") or 0)
    selected_receptacle_count = int(scene_bindings.get("selected_target_receptacle_count") or 0)
    selected_object_bound_count = int(scene_bindings.get("selected_object_bound_count") or 0)
    selected_receptacle_bound_count = int(
        scene_bindings.get("selected_target_receptacle_bound_count") or 0
    )
    assert selected_object_count > 0, scene_bindings
    assert selected_receptacle_count > 0, scene_bindings
    assert selected_object_bound_count >= selected_object_count, scene_bindings
    assert selected_receptacle_bound_count >= selected_receptacle_count, scene_bindings
    assert not scene_bindings.get("blockers"), scene_bindings
    _assert_bound_isaac_binding_rows(
        scene_bindings.get("selected_object_bindings") or {},
        expected_count=selected_object_count,
        index=object_index,
        index_label="object index",
        label="object",
    )
    _assert_bound_isaac_binding_rows(
        scene_bindings.get("selected_target_receptacle_bindings") or {},
        expected_count=selected_receptacle_count,
        index=receptacle_index,
        index_label="receptacle index",
        label="target receptacle",
    )


def _assert_isaac_scene_index_artifact(
    data: dict[str, Any],
    isaac: dict[str, Any],
    base: Path,
) -> dict[str, Any]:
    artifacts = data.get("artifacts") or {}
    artifact_path = str(
        isaac.get("scene_index_artifact") or artifacts.get("isaac_scene_index") or ""
    )
    assert artifact_path, isaac
    resolved = _resolve_path(base, artifact_path)
    try:
        payload = read_json_object(resolved, label="Isaac scene-index artifact")
    except (FileNotFoundError, ValueError) as exc:
        raise AssertionError(str(exc)) from exc
    assert payload.get("schema") == ISAAC_SCENE_INDEX_ARTIFACT_SCHEMA, payload
    assert payload.get("backend") == ISAACLAB_SUBPROCESS_BACKEND, payload
    assert payload.get("agent_facing") is False, payload
    assert payload.get("private_manifest_exposed_to_agent") is False, payload
    assert "private_manifest" not in payload, payload
    assert payload.get("object_index"), payload
    assert payload.get("receptacle_index"), payload
    assert int(payload.get("object_index_count") or 0) == len(payload["object_index"]), payload
    assert int(payload.get("receptacle_index_count") or 0) == len(payload["receptacle_index"]), (
        payload
    )
    _assert_bound_isaac_index_rows(payload.get("object_index") or {})
    _assert_bound_isaac_index_rows(payload.get("receptacle_index") or {})
    _assert_isaac_scene_index_matches_runtime_indexes(isaac, payload)
    _assert_selected_isaac_usd_bindings_for_indexes(
        payload.get("scene_binding_diagnostics") or {},
        object_index=payload.get("object_index") or {},
        receptacle_index=payload.get("receptacle_index") or {},
    )
    return payload


def _assert_isaac_scene_index_matches_runtime_indexes(
    isaac: dict[str, Any],
    payload: dict[str, Any],
) -> None:
    for index_key, count_key in (
        ("object_index", "object_index_count"),
        ("receptacle_index", "receptacle_index_count"),
    ):
        runtime_index = isaac.get(index_key) or {}
        artifact_index = payload.get(index_key) or {}
        assert runtime_index, (index_key, isaac)
        assert runtime_index == artifact_index, (index_key, runtime_index, artifact_index)
        assert int(isaac.get(count_key) or 0) == len(runtime_index), (count_key, isaac)
        assert int(payload.get(count_key) or 0) == len(artifact_index), (count_key, payload)


def _assert_isaac_scene_index_matches_runtime_bindings(
    runtime_bindings: dict[str, Any],
    artifact_bindings: dict[str, Any],
) -> None:
    for key in (
        "schema",
        "status",
        "source",
        "selected_object_count",
        "selected_target_receptacle_count",
        "selected_object_bound_count",
        "selected_target_receptacle_bound_count",
        "private_manifest_exposed_to_agent",
    ):
        assert artifact_bindings.get(key) == runtime_bindings.get(key), (
            key,
            runtime_bindings,
            artifact_bindings,
        )
    for bindings_key in (
        "selected_object_bindings",
        "selected_target_receptacle_bindings",
    ):
        runtime_rows = runtime_bindings.get(bindings_key) or {}
        artifact_rows = artifact_bindings.get(bindings_key) or {}
        assert runtime_rows.keys() == artifact_rows.keys(), (
            bindings_key,
            runtime_rows,
            artifact_rows,
        )
        for public_id, runtime_row in runtime_rows.items():
            artifact_row = artifact_rows.get(public_id)
            assert isinstance(runtime_row, dict), (bindings_key, public_id, runtime_row)
            assert isinstance(artifact_row, dict), (bindings_key, public_id, artifact_row)
            for row_key in (
                "status",
                "usd_handle",
                "usd_prim_path",
                "match_strategy",
                "index_source",
            ):
                assert artifact_row.get(row_key) == runtime_row.get(row_key), (
                    bindings_key,
                    public_id,
                    row_key,
                    runtime_row,
                    artifact_row,
                )


def _assert_isaac_scene_index_matches_runtime_segmentation(
    runtime_segmentation: dict[str, Any],
    artifact_segmentation: dict[str, Any],
) -> None:
    for key in (
        "schema",
        "status",
        "available",
        "source",
        "capture_method",
        "tensor_output_available",
        "candidate_overlay_status",
        "candidate_bbox_count",
        "selected_usd_prim_match_count",
        "agent_facing",
        "no_simulator_label_fallback",
    ):
        assert artifact_segmentation.get(key) == runtime_segmentation.get(key), (
            key,
            runtime_segmentation,
            artifact_segmentation,
        )
    for key in (
        "requested_data_types",
        "output_data_types",
        "selected_usd_prim_paths",
        "selected_candidate_bboxes",
        "candidate_bboxes",
    ):
        assert artifact_segmentation.get(key) == runtime_segmentation.get(key), (
            key,
            runtime_segmentation,
            artifact_segmentation,
        )


def _assert_isaac_scene_index_report_rows(
    scene_bindings: dict[str, Any],
    report_text: str,
) -> None:
    for expected in (
        "Scene Index Artifact Rows",
        "Selected USD Binding Rows",
        "Selected USD Index Rows",
    ):
        assert expected in report_text, report_text[:1000]
    for bindings_key in (
        "selected_object_bindings",
        "selected_target_receptacle_bindings",
    ):
        bindings = scene_bindings.get(bindings_key) or {}
        assert bindings, scene_bindings
        for binding in bindings.values():
            assert isinstance(binding, dict), binding
            if binding.get("status") != "bound":
                continue
            usd_handle = str(binding.get("usd_handle") or "")
            usd_prim_path = str(binding.get("usd_prim_path") or "")
            assert usd_handle in report_text, (usd_handle, report_text[:1000])
            assert usd_prim_path in report_text, (usd_prim_path, report_text[:1000])


def _assert_bound_isaac_index_rows(index: dict[str, Any]) -> None:
    for handle, row in index.items():
        assert isinstance(row, dict), (handle, row)
        assert row.get("usd_prim_path"), row


def _assert_isaac_snapshot_provenance(isaac: dict[str, Any], base: Path) -> None:
    snapshots = isaac.get("snapshot_artifacts") or []
    assert len(snapshots) >= 2, isaac
    for snapshot in snapshots:
        assert isinstance(snapshot, dict), snapshot
        assert snapshot.get("placeholder_visuals") is False, snapshot
        assert snapshot.get("visual_artifact_provenance") == "isaac_lab_camera_rgb", snapshot
        output_path = _resolve_path(base, snapshot.get("output_path", ""))
        _assert_nonblank_image(output_path, "Isaac snapshot")
        provenance = snapshot.get("snapshot_provenance") or {}
        assert provenance.get("placeholder_visuals") is False, provenance
        assert provenance.get("visual_artifact_provenance") == "isaac_lab_camera_rgb", provenance
        assert provenance.get("static_isaac_capture") is True, provenance
        assert provenance.get("semantic_pose_rendered") is False, provenance
        source_path = _resolve_path(base, provenance.get("source_path", ""))
        _assert_nonblank_image(source_path, "Isaac snapshot source")
        assert "placeholder_protocol_image" not in json.dumps(provenance, sort_keys=True).lower(), (
            provenance
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


def _assert_bound_isaac_binding_rows(
    bindings: dict[str, Any],
    *,
    expected_count: int,
    index: dict[str, Any] | None,
    index_label: str,
    label: str,
) -> None:
    assert bindings and len(bindings) >= expected_count, (label, expected_count, bindings)
    for public_id, binding in bindings.items():
        assert isinstance(binding, dict), (label, public_id, binding)
        assert binding.get("status") == "bound", (label, public_id, binding)
        usd_handle = str(binding.get("usd_handle") or "")
        usd_prim_path = str(binding.get("usd_prim_path") or "")
        assert usd_handle, (label, public_id, binding)
        assert usd_prim_path, (label, public_id, binding)
        assert binding.get("index_source") == "usd_stage_traversal", (label, public_id, binding)
        assert binding.get("match_strategy") not in {"", "none"}, (label, public_id, binding)
        assert "private_manifest" not in binding, (label, public_id, binding)
        if index is None:
            continue
        index_row = index.get(usd_handle)
        assert isinstance(index_row, dict), (label, public_id, usd_handle, index_label, index)
        index_prim_path = str(index_row.get("usd_prim_path") or "")
        assert index_prim_path, (label, public_id, usd_handle, index_row)
        assert usd_prim_path == index_prim_path, (
            label,
            public_id,
            usd_prim_path,
            index_label,
            index_prim_path,
        )
