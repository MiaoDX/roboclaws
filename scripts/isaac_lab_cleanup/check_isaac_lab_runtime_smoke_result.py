#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

from PIL import Image, ImageStat

from roboclaws.household.subprocess_backend import _parse_last_json_object

SCHEMA = "roboclaws_isaac_lab_runtime_smoke_check_v1"
SCENE_BINDING_SCHEMA = "isaac_public_scene_bindings_v1"
ISAACLAB_ROBOT_VIEW_VARIANT = "isaaclab-fpv-topdown-chase-verify"
ROBOT_VIEW_KEYS = ("fpv", "chase", "topdown", "verify")
MIN_REVIEWABLE_IMAGE_STDDEV = 5.0
MIN_REVIEWABLE_IMAGE_COLOR_COUNT = 128


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Validate Isaac Lab runtime smoke evidence.")
    parser.add_argument("--init-result", type=Path, required=True)
    parser.add_argument("--state-path", type=Path)
    parser.add_argument("--robot-views-result", type=Path)
    parser.add_argument("--require-real-rendering", action="store_true")
    parser.add_argument("--require-usd-stage-loaded", action="store_true")
    parser.add_argument("--require-local-scene-usd", action="store_true")
    parser.add_argument("--require-usd-scene-index", action="store_true")
    parser.add_argument("--require-selected-usd-bindings", action="store_true")
    parser.add_argument("--require-robot-view-images", action="store_true")
    parser.add_argument("--require-nonblank-image", action="store_true")
    parser.add_argument("--require-segmentation-evidence", action="store_true")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    result = _read_init_result(args.init_result)
    state = _read_sidecar_json(args.state_path, label="Isaac runtime smoke state")
    robot_views_result = _read_sidecar_json(
        args.robot_views_result,
        label="Isaac runtime smoke robot views result",
    )
    errors = validate(
        result=result,
        state=state,
        robot_views_result=robot_views_result,
        require_real_rendering=args.require_real_rendering,
        require_usd_stage_loaded=args.require_usd_stage_loaded,
        require_local_scene_usd=args.require_local_scene_usd,
        require_usd_scene_index=args.require_usd_scene_index,
        require_selected_usd_bindings=args.require_selected_usd_bindings,
        require_robot_view_images=args.require_robot_view_images,
        require_nonblank_image=args.require_nonblank_image,
        require_segmentation_evidence=args.require_segmentation_evidence,
    )
    summary = {
        "schema": SCHEMA,
        "status": "failed" if errors else "passed",
        "errors": errors,
        "backend": result.get("backend"),
        "runtime_mode": (result.get("runtime") or {}).get("runtime_mode"),
        "scene_usd": result.get("scene_usd"),
        "loaded_asset_kind": (_dict(result.get("scene_load"))).get("loaded_asset_kind"),
        "scene_index_status": (_dict(result.get("scene_index_diagnostics"))).get("status"),
        "scene_binding_status": (_dict(result.get("scene_binding_diagnostics"))).get("status"),
        "robot_view_status": _robot_view_status(robot_views_result),
    }
    print(json.dumps(summary, sort_keys=True))
    return 1 if errors else 0


def validate(
    *,
    result: dict[str, Any],
    state: dict[str, Any],
    robot_views_result: dict[str, Any],
    require_real_rendering: bool,
    require_usd_stage_loaded: bool,
    require_local_scene_usd: bool,
    require_usd_scene_index: bool,
    require_selected_usd_bindings: bool,
    require_robot_view_images: bool,
    require_nonblank_image: bool,
    require_segmentation_evidence: bool,
) -> list[str]:
    errors: list[str] = []
    _require(result.get("ok") is True, "init result did not report ok=true", errors)
    _require(
        result.get("backend") == "isaaclab_subprocess",
        "init result backend is not isaaclab_subprocess",
        errors,
    )
    runtime = _dict(result.get("runtime"))
    rendering = _dict(runtime.get("rendering"))
    scene_load = _dict(result.get("scene_load"))
    scene_index = _dict(result.get("scene_index_diagnostics"))
    scene_bindings = _dict(result.get("scene_binding_diagnostics"))
    object_index = _dict(result.get("object_index"))
    receptacle_index = _dict(result.get("receptacle_index"))
    segmentation = _dict(result.get("segmentation"))
    artifacts = _dict(result.get("artifacts"))

    _append_runtime_and_scene_errors(
        errors,
        result=result,
        runtime=runtime,
        rendering=rendering,
        scene_load=scene_load,
        scene_index=scene_index,
        object_index=object_index,
        receptacle_index=receptacle_index,
        require_real_rendering=require_real_rendering,
        require_usd_stage_loaded=require_usd_stage_loaded,
        require_local_scene_usd=require_local_scene_usd,
        require_usd_scene_index=require_usd_scene_index,
    )
    if require_selected_usd_bindings:
        errors.extend(
            _selected_usd_binding_errors(
                scene_bindings,
                object_index=object_index,
                receptacle_index=receptacle_index,
            )
        )
    _append_artifact_evidence_errors(
        errors,
        artifacts=artifacts,
        robot_views_result=robot_views_result,
        segmentation=segmentation,
        require_nonblank_image=require_nonblank_image,
        require_robot_view_images=require_robot_view_images,
        require_segmentation_evidence=require_segmentation_evidence,
        require_real_rendering=require_real_rendering,
    )
    _append_state_consistency_errors(errors, result=result, state=state, runtime=runtime)
    return errors


def _append_runtime_and_scene_errors(
    errors: list[str],
    *,
    result: dict[str, Any],
    runtime: dict[str, Any],
    rendering: dict[str, Any],
    scene_load: dict[str, Any],
    scene_index: dict[str, Any],
    object_index: dict[str, Any],
    receptacle_index: dict[str, Any],
    require_real_rendering: bool,
    require_usd_stage_loaded: bool,
    require_local_scene_usd: bool,
    require_usd_scene_index: bool,
) -> None:
    if require_real_rendering:
        errors.extend(_real_rendering_errors(runtime, rendering))
    if require_usd_stage_loaded:
        errors.extend(_usd_stage_loaded_errors(result, scene_load))
    if require_local_scene_usd:
        errors.extend(_local_scene_usd_errors(result, scene_load))
    if require_usd_scene_index:
        errors.extend(_usd_scene_index_errors(scene_index, object_index, receptacle_index))


def _real_rendering_errors(runtime: dict[str, Any], rendering: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    _require(
        runtime.get("runtime_mode") == "real",
        "runtime_mode is not real",
        errors,
    )
    errors.extend(_real_runtime_diagnostic_errors(runtime))
    _require(
        rendering.get("real_rendering_proven") is True,
        "real Isaac rendering is not proven",
        errors,
    )
    _require(
        rendering.get("placeholder_visuals") is not True,
        "runtime smoke still reports placeholder visuals",
        errors,
    )
    return errors


def _usd_stage_loaded_errors(
    result: dict[str, Any],
    scene_load: dict[str, Any],
) -> list[str]:
    errors: list[str] = []
    _require(
        scene_load.get("usd_stage_loaded") is True,
        "USD stage loading is not proven",
        errors,
    )
    _require(
        scene_load.get("status") == "loaded",
        "scene_load status is not loaded",
        errors,
    )
    errors.extend(_scene_load_errors(result, scene_load))
    return errors


def _local_scene_usd_errors(
    result: dict[str, Any],
    scene_load: dict[str, Any],
) -> list[str]:
    errors: list[str] = []
    _require(
        scene_load.get("usd_stage_loaded") is True,
        "local scene USD loading is not proven",
        errors,
    )
    _require(
        scene_load.get("status") == "loaded",
        "local scene_load status is not loaded",
        errors,
    )
    errors.extend(_scene_load_errors(result, scene_load))
    _require(
        scene_load.get("loaded_asset_kind") == "local_scene_usd",
        "loaded scene USD was not caller supplied local_scene_usd",
        errors,
    )
    return errors


def _usd_scene_index_errors(
    scene_index: dict[str, Any],
    object_index: dict[str, Any],
    receptacle_index: dict[str, Any],
) -> list[str]:
    errors: list[str] = []
    _require(bool(scene_index), "missing USD scene index diagnostics", errors)
    _require(
        int(scene_index.get("stage_prim_count") or 0) > 0,
        "USD scene index has no stage prims",
        errors,
    )
    _require(
        int(scene_index.get("object_candidate_count") or 0) > 0 or bool(object_index),
        "USD scene index has no object candidates",
        errors,
    )
    _require(
        int(scene_index.get("receptacle_candidate_count") or 0) > 0 or bool(receptacle_index),
        "USD scene index has no receptacle candidates",
        errors,
    )
    return errors


def _append_artifact_evidence_errors(
    errors: list[str],
    *,
    artifacts: dict[str, Any],
    robot_views_result: dict[str, Any],
    segmentation: dict[str, Any],
    require_nonblank_image: bool,
    require_robot_view_images: bool,
    require_segmentation_evidence: bool,
    require_real_rendering: bool,
) -> None:
    if require_nonblank_image:
        image_path = artifacts.get("runtime_smoke_image")
        _require(
            isinstance(image_path, str) and bool(image_path), "missing smoke image path", errors
        )
        if isinstance(image_path, str) and image_path:
            errors.extend(_image_errors(Path(image_path)))
    if require_robot_view_images:
        errors.extend(
            _robot_view_errors(
                robot_views_result,
                require_real_rendering=require_real_rendering,
            )
        )
    if require_segmentation_evidence:
        errors.extend(_segmentation_errors(segmentation))


def _append_state_consistency_errors(
    errors: list[str],
    *,
    result: dict[str, Any],
    state: dict[str, Any],
    runtime: dict[str, Any],
) -> None:
    if not state:
        return
    _require(
        state.get("backend") == result.get("backend"),
        "state backend does not match init result",
        errors,
    )
    _require(
        _dict(state.get("runtime")).get("runtime_mode") == runtime.get("runtime_mode"),
        "state runtime_mode does not match init result",
        errors,
    )


def _scene_load_errors(result: dict[str, Any], scene_load: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    scene_usd = str(scene_load.get("scene_usd") or result.get("scene_usd") or "")
    _require(bool(scene_usd), "missing loaded scene USD path", errors)
    if scene_usd:
        _require(Path(scene_usd).is_file(), f"loaded scene USD is missing: {scene_usd}", errors)
    _require(bool(scene_load.get("loaded_asset_kind")), "missing loaded asset kind", errors)
    _require(
        scene_load.get("manual_editor_steps_required") is False,
        "USD stage loading still requires manual editor steps",
        errors,
    )
    return errors


def _real_runtime_diagnostic_errors(runtime: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    _require(bool(runtime.get("python_version")), "missing runtime Python version", errors)
    _require(bool(runtime.get("isaac_sim_version")), "missing Isaac Sim version", errors)
    _require(bool(runtime.get("isaac_lab_version")), "missing Isaac Lab version", errors)
    _require(runtime.get("cuda_available") is True, "runtime CUDA is not available", errors)
    _require(bool(runtime.get("gpu_name")), "missing runtime GPU name", errors)
    _require(_int(runtime.get("gpu_vram_mb")) > 0, "missing runtime GPU VRAM", errors)
    _require(bool(runtime.get("renderer_mode")), "missing runtime renderer mode", errors)
    resolution = runtime.get("camera_resolution")
    _require(
        isinstance(resolution, list)
        and len(resolution) == 2
        and all(_int(item) > 0 for item in resolution),
        "missing runtime camera resolution",
        errors,
    )
    return errors


def _selected_usd_binding_errors(
    scene_bindings: dict[str, Any],
    *,
    object_index: dict[str, Any],
    receptacle_index: dict[str, Any],
) -> list[str]:
    errors: list[str] = []
    _require(bool(scene_bindings), "missing selected USD binding diagnostics", errors)
    if not scene_bindings:
        return errors
    _require(
        scene_bindings.get("schema") == SCENE_BINDING_SCHEMA,
        "selected USD binding diagnostics schema is not isaac_public_scene_bindings_v1",
        errors,
    )
    _require(
        scene_bindings.get("source") == "usd_stage_traversal",
        "selected USD bindings are not sourced from USD stage traversal",
        errors,
    )
    _require(
        scene_bindings.get("status") == "selected_bound",
        "selected cleanup handles are not fully bound to USD prims",
        errors,
    )
    selected_object_count = _int(scene_bindings.get("selected_object_count"))
    selected_receptacle_count = _int(scene_bindings.get("selected_target_receptacle_count"))
    selected_object_bound_count = _int(scene_bindings.get("selected_object_bound_count"))
    selected_receptacle_bound_count = _int(
        scene_bindings.get("selected_target_receptacle_bound_count")
    )
    _require(selected_object_count > 0, "no selected cleanup objects were checked", errors)
    _require(
        selected_receptacle_count > 0,
        "no selected target receptacles were checked",
        errors,
    )
    _require(
        selected_object_bound_count >= selected_object_count,
        "not all selected cleanup objects have USD prim bindings",
        errors,
    )
    _require(
        selected_receptacle_bound_count >= selected_receptacle_count,
        "not all selected target receptacles have USD prim bindings",
        errors,
    )
    _require(
        not scene_bindings.get("blockers"),
        "selected USD binding diagnostics still report blockers",
        errors,
    )
    _require(
        scene_bindings.get("private_manifest_exposed_to_agent") is False,
        "selected USD binding diagnostics report private manifest exposure",
        errors,
    )
    errors.extend(
        _selected_binding_row_errors(
            scene_bindings,
            bindings_key="selected_object_bindings",
            expected_count=selected_object_count,
            index=object_index,
            index_label="object index",
            label="object",
        )
    )
    errors.extend(
        _selected_binding_row_errors(
            scene_bindings,
            bindings_key="selected_target_receptacle_bindings",
            expected_count=selected_receptacle_count,
            index=receptacle_index,
            index_label="receptacle index",
            label="target receptacle",
        )
    )
    return errors


def _selected_binding_row_errors(
    scene_bindings: dict[str, Any],
    *,
    bindings_key: str,
    expected_count: int,
    index: dict[str, Any],
    index_label: str,
    label: str,
) -> list[str]:
    errors: list[str] = []
    rows = scene_bindings.get(bindings_key)
    _require(
        isinstance(rows, dict) and len(rows) >= expected_count,
        f"selected {label} binding rows are missing",
        errors,
    )
    if not isinstance(rows, dict):
        return errors
    for public_id, row in rows.items():
        if not isinstance(row, dict):
            errors.append(f"selected {label} binding row is not an object: {public_id}")
            continue
        row_is_bound = row.get("status") == "bound"
        has_usd_handle = bool(row.get("usd_handle"))
        has_usd_prim_path = bool(row.get("usd_prim_path"))
        has_usd_index_source = row.get("index_source") == "usd_stage_traversal"
        has_match_strategy = str(row.get("match_strategy") or "") not in {"", "none"}
        hides_private_manifest = "private_manifest" not in row
        _require(
            row_is_bound,
            f"selected {label} binding row is not bound: {public_id}",
            errors,
        )
        _require(
            has_usd_handle,
            f"selected {label} binding row has no USD handle: {public_id}",
            errors,
        )
        _require(
            has_usd_prim_path,
            f"selected {label} binding row has no USD prim path: {public_id}",
            errors,
        )
        _require(
            has_usd_index_source,
            f"selected {label} binding row is not from USD stage traversal: {public_id}",
            errors,
        )
        _require(
            has_match_strategy,
            f"selected {label} binding row has no match strategy: {public_id}",
            errors,
        )
        _require(
            hides_private_manifest,
            f"selected {label} binding row exposes private manifest: {public_id}",
            errors,
        )
        if not all(
            (
                row_is_bound,
                has_usd_handle,
                has_usd_prim_path,
                has_usd_index_source,
                has_match_strategy,
                hides_private_manifest,
            )
        ):
            continue
        errors.extend(
            _selected_binding_index_errors(
                public_id=str(public_id),
                row=row,
                index=index,
                index_label=index_label,
                label=label,
            )
        )
    return errors


def _selected_binding_index_errors(
    *,
    public_id: str,
    row: dict[str, Any],
    index: dict[str, Any],
    index_label: str,
    label: str,
) -> list[str]:
    errors: list[str] = []
    usd_handle = str(row.get("usd_handle") or "")
    usd_prim_path = str(row.get("usd_prim_path") or "")
    index_row = index.get(usd_handle)
    if not isinstance(index_row, dict):
        errors.append(
            f"selected {label} binding row USD handle is missing from {index_label}: {public_id}"
        )
        return errors
    index_prim_path = str(index_row.get("usd_prim_path") or "")
    _require(
        bool(index_prim_path),
        f"selected {label} binding row {index_label} row has no USD prim path: {public_id}",
        errors,
    )
    _require(
        usd_prim_path == index_prim_path,
        f"selected {label} binding row USD prim path does not match {index_label}: {public_id}",
        errors,
    )
    return errors


def _segmentation_errors(segmentation: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    _require(bool(segmentation), "missing Isaac segmentation diagnostics", errors)
    if not segmentation:
        return errors
    _require(
        segmentation.get("schema") == "isaac_segmentation_diagnostics_v1",
        "Isaac segmentation diagnostics schema is not isaac_segmentation_diagnostics_v1",
        errors,
    )
    _require(
        segmentation.get("status") == "available",
        "Isaac segmentation evidence is not available",
        errors,
    )
    _require(
        segmentation.get("available") is True,
        "Isaac segmentation diagnostics do not report available=true",
        errors,
    )
    _require(
        segmentation.get("tensor_output_available") is True,
        "Isaac segmentation tensors were not captured",
        errors,
    )
    _require(
        _int(segmentation.get("candidate_bbox_count")) > 0,
        "Isaac segmentation produced no bbox candidates",
        errors,
    )
    _require(
        _int(segmentation.get("selected_usd_prim_match_count")) > 0,
        "Isaac segmentation produced no selected-USD candidate matches",
        errors,
    )
    _require(
        segmentation.get("candidate_overlay_status") == "available",
        "Isaac segmentation candidate overlays are not available",
        errors,
    )
    _require(
        segmentation.get("agent_facing") is False,
        "Isaac segmentation diagnostics leaked into agent-facing fields",
        errors,
    )
    _require(
        segmentation.get("no_simulator_label_fallback") is True,
        "Isaac segmentation diagnostics used simulator-label fallback",
        errors,
    )
    return errors


def _robot_view_errors(
    result: dict[str, Any],
    *,
    require_real_rendering: bool,
) -> list[str]:
    errors: list[str] = []
    _require(bool(result), "missing robot views result", errors)
    if not result:
        return errors
    _require(result.get("ok") is True, "robot views result did not report ok=true", errors)
    _require(
        result.get("view_variant") == ISAACLAB_ROBOT_VIEW_VARIANT,
        "robot views result is not the Isaac Lab view variant",
        errors,
    )
    views = _dict(result.get("views"))
    for key in ROBOT_VIEW_KEYS:
        image_path = views.get(key)
        _require(
            isinstance(image_path, str) and bool(image_path),
            f"missing {key} robot view image path",
            errors,
        )
        if isinstance(image_path, str) and image_path:
            errors.extend(
                error.replace("smoke image", f"{key} robot view")
                for error in _image_errors(Path(image_path))
            )
    if require_real_rendering:
        provenance_text = json.dumps(result.get("view_provenance"), sort_keys=True).lower()
        _require(
            "placeholder" not in provenance_text,
            "robot view provenance still reports placeholder visuals",
            errors,
        )
        _require(
            "isaac_lab_camera_rgb" in provenance_text,
            "robot view provenance does not show Isaac camera capture",
            errors,
        )
    return errors


def _robot_view_status(result: dict[str, Any]) -> str:
    if not result:
        return "not_checked"
    if result.get("ok") is not True:
        return "failed"
    views = _dict(result.get("views"))
    if all(views.get(key) for key in ROBOT_VIEW_KEYS):
        return "present"
    return "partial"


def _image_errors(path: Path) -> list[str]:
    errors: list[str] = []
    if not path.is_file():
        return [f"smoke image is missing: {path}"]
    try:
        with Image.open(path) as image:
            image.verify()
        with Image.open(path) as image:
            rgb = image.convert("RGB")
            stat = ImageStat.Stat(rgb)
            extrema = rgb.getextrema()
            colors = rgb.getcolors(maxcolors=1_000_000)
    except Exception as exc:
        return [f"smoke image is unreadable: {exc}"]
    if all(high <= low for low, high in extrema):
        errors.append("smoke image appears blank")
    if max(stat.stddev or [0.0]) <= 0.0:
        errors.append("smoke image has no pixel variance")
    if max(stat.stddev or [0.0]) < MIN_REVIEWABLE_IMAGE_STDDEV:
        errors.append("smoke image has too little visual detail")
    if colors is not None and len(colors) < MIN_REVIEWABLE_IMAGE_COLOR_COUNT:
        errors.append("smoke image has too few distinct colors")
    return errors


def _read_init_result(path: Path) -> dict[str, Any]:
    text = path.read_text(encoding="utf-8")
    try:
        payload = json.loads(text)
    except json.JSONDecodeError:
        payload = _parse_last_json_object(text)
    if not isinstance(payload, dict):
        raise ValueError(
            f"Isaac runtime smoke init result source must contain a JSON object: {path}"
        )
    return payload


def _read_sidecar_json(path: Path | None, *, label: str) -> dict[str, Any]:
    if path is None:
        return {}
    text = path.read_text(encoding="utf-8")
    try:
        payload = json.loads(text)
    except json.JSONDecodeError:
        # Isaac Sim writes diagnostics to stderr; the harness captures both
        # streams in the sidecar. Recover the worker's final JSON object while
        # retaining strict object validation.
        payload = _parse_last_json_object(text)
    if not isinstance(payload, dict):
        raise ValueError(f"{label} source must contain valid JSON object: {path}")
    return payload


def _dict(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _int(value: Any) -> int:
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return 0


def _require(condition: bool, message: str, errors: list[str]) -> None:
    if not condition:
        errors.append(message)


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
