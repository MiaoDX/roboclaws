"""Isaac Lab backend runtime support."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Callable


def scene_usd_path(scene_source: str, scene_index: int) -> str:
    return f"molmospaces://{scene_source}/scene-{scene_index}.usd"


def scene_load_diagnostics(
    runtime_mode: str,
    scene_source: str,
    scene_index: int,
    *,
    real_smoke: dict[str, Any] | None = None,
) -> dict[str, Any]:
    if real_smoke is not None:
        loaded_asset_kind = str(
            real_smoke.get("loaded_asset_kind") or "generated_runtime_smoke_usd"
        )
        reason = (
            "Phase A loaded a generated local USD stage through Isaac Sim. "
            "MolmoSpaces USD scene loading remains a separate parity gate."
        )
        if loaded_asset_kind == "local_scene_usd":
            reason = (
                "Real mode loaded the caller-supplied local USD stage through Isaac Sim. "
                "If this is a MolmoSpaces scene, object/receptacle parity is recorded "
                "in the USD scene index diagnostics."
            )
        return {
            "status": "loaded",
            "scene_source": scene_source,
            "scene_index": scene_index,
            "scene_usd": str(real_smoke["scene_usd"]),
            "usd_stage_loaded": True,
            "loaded_asset_kind": loaded_asset_kind,
            "requested_molmospaces_scene_usd": scene_usd_path(scene_source, scene_index),
            "manual_editor_steps_required": False,
            "stage_prim_count": int(real_smoke.get("stage_prim_count") or 0),
            "reason": reason,
        }
    if runtime_mode == "real":
        status = "blocked_capability"
        reason = (
            "Real Isaac USD scene loading is not implemented in this "
            "semantic-pose scaffold. A future local-dev pass must launch Isaac "
            "Sim/Lab and prove the selected USD scene loads."
        )
    else:
        status = "fake_protocol"
        reason = (
            "Fake mode derives scenario state from synthetic/map fixtures, not an Isaac USD stage."
        )
    return {
        "status": status,
        "scene_source": scene_source,
        "scene_index": scene_index,
        "scene_usd": scene_usd_path(scene_source, scene_index),
        "usd_stage_loaded": False,
        "manual_editor_steps_required": None if runtime_mode == "real" else False,
        "reason": reason,
    }


def mapping_gap_diagnostics(
    *,
    runtime_mode: str,
    map_bundle_dir: Path | None,
    real_smoke: dict[str, Any] | None = None,
    scene_binding_diagnostics: dict[str, Any] | None = None,
    segmentation: dict[str, Any] | None = None,
    real_smoke_robot_view_images: Callable[[dict[str, Any] | None], dict[str, str]],
    has_required_robot_view_images: Callable[[dict[str, str]], bool],
    real_smoke_capture_method: str,
    real_robot_view_capture_method: str,
) -> list[dict[str, Any]]:
    source = "real_isaac_pending" if runtime_mode == "real" else "fake_protocol"
    scene_bindings = _dict(scene_binding_diagnostics)
    segmentation = _dict(segmentation)
    if real_smoke is not None:
        gaps = _real_mapping_gap_diagnostics(
            real_smoke=real_smoke,
            scene_bindings=scene_bindings,
            segmentation=segmentation,
            real_smoke_robot_view_images=real_smoke_robot_view_images,
            has_required_robot_view_images=has_required_robot_view_images,
            real_smoke_capture_method=real_smoke_capture_method,
            real_robot_view_capture_method=real_robot_view_capture_method,
        )
    else:
        gaps = _fake_mapping_gap_diagnostics(
            runtime_mode=runtime_mode,
            source=source,
            scene_bindings=scene_bindings,
            segmentation=segmentation,
        )
    if map_bundle_dir is not None:
        gaps.append(
            {
                "area": "public_map_source",
                "status": "external_map_bundle",
                "source": str(map_bundle_dir),
                "detail": (
                    "Public map and fixture context still come from the selected Nav2 bundle."
                ),
            }
        )
    return gaps


def _real_mapping_gap_diagnostics(
    *,
    real_smoke: dict[str, Any],
    scene_bindings: dict[str, Any],
    segmentation: dict[str, Any],
    real_smoke_robot_view_images: Callable[[dict[str, Any] | None], dict[str, str]],
    has_required_robot_view_images: Callable[[dict[str, str]], bool],
    real_smoke_capture_method: str,
    real_robot_view_capture_method: str,
) -> list[dict[str, Any]]:
    loaded_asset_kind = str(real_smoke.get("loaded_asset_kind") or "generated_runtime_smoke_usd")
    scene_index = _dict(real_smoke.get("scene_index_diagnostics"))
    scene_loading_gap = {
        "area": "molmospaces_usd_scene_loading",
        "status": "not_attempted",
        "source": scene_usd_path(
            str(real_smoke.get("requested_scene_source") or ""),
            int(real_smoke.get("requested_scene_index") or 0),
        ),
        "detail": (
            "The real smoke proves Isaac renderer/USD plumbing only; loading "
            "the MolmoSpaces USD shard remains a Phase B blocker."
        ),
    }
    if loaded_asset_kind == "local_scene_usd":
        scene_loading_gap = {
            "area": "local_usd_scene_loading",
            "status": "loaded",
            "source": str(real_smoke["scene_usd"]),
            "detail": (
                "The worker loaded the caller-supplied USD stage. Use a "
                "MolmoSpaces USD here for Phase B parity evidence."
            ),
        }
    stage_loading_detail = "Generated local Phase A USD stage loaded through Isaac Sim."
    if loaded_asset_kind == "local_scene_usd":
        stage_loading_detail = "Caller-supplied local USD stage loaded through Isaac Sim."
    robot_view_images = real_smoke_robot_view_images(real_smoke)
    robot_view_status = (
        "real_rendering_proven"
        if has_required_robot_view_images(robot_view_images)
        else "blocked_capability"
    )
    robot_view_detail = (
        "FPV, chase, map, and verification images were captured from the loaded USD scene. "
        "They are static Phase B camera evidence; semantic pose edits are not yet rendered "
        "back into Isaac USD state."
        if robot_view_status == "real_rendering_proven"
        else "FPV/chase/map/verify Isaac camera variants are not fully captured yet."
    )
    return [
        {
            "area": "phase_a_usd_stage_loading",
            "status": "loaded",
            "source": str(real_smoke["scene_usd"]),
            "detail": stage_loading_detail,
        },
        scene_loading_gap,
        {
            "area": "usd_prim_index",
            "status": scene_index.get("status", "partial"),
            "source": scene_index.get("source", "usd_stage_traversal"),
            "detail": (
                f"USD traversal found {scene_index.get('object_candidate_count', 0)} "
                "object candidates and "
                f"{scene_index.get('receptacle_candidate_count', 0)} receptacle candidates."
            ),
        },
        {
            "area": "public_scene_bindings",
            "status": scene_bindings.get("status", "unknown"),
            "source": scene_bindings.get("source", "usd_stage_traversal"),
            "detail": (
                "Selected cleanup USD bindings: "
                f"{scene_bindings.get('selected_object_bound_count', 0)}/"
                f"{scene_bindings.get('selected_object_count', 0)} objects and "
                f"{scene_bindings.get('selected_target_receptacle_bound_count', 0)}/"
                f"{scene_bindings.get('selected_target_receptacle_count', 0)} target "
                "receptacles."
            ),
        },
        {
            "area": "camera_capture",
            "status": "real_rendering_proven",
            "source": real_smoke_capture_method,
            "detail": "An Isaac Lab RGB camera frame was written as the runtime smoke image.",
        },
        {
            "area": "robot_view_variants",
            "status": robot_view_status,
            "source": real_robot_view_capture_method,
            "detail": robot_view_detail,
        },
        {
            "area": "segmentation",
            "status": segmentation.get("status", "blocked_capability"),
            "source": segmentation.get("source", "isaac_lab_camera"),
            "detail": str(
                segmentation.get("reason")
                or "Semantic or instance segmentation masks are not exposed yet."
            ),
        },
        {
            "area": "articulation_and_collision",
            "status": "semantic_pose_only",
            "source": "generated_runtime_smoke_usd",
            "detail": "Open/place effects are semantic state edits, not physics or planner proof.",
        },
    ]


def _fake_mapping_gap_diagnostics(
    *,
    runtime_mode: str,
    source: str,
    scene_bindings: dict[str, Any],
    segmentation: dict[str, Any],
) -> list[dict[str, Any]]:
    return [
        {
            "area": "usd_stage_loading",
            "status": "blocked_capability" if runtime_mode == "real" else "not_attempted",
            "source": source,
            "detail": "MolmoSpaces USD stage loading has not been proven by this worker.",
        },
        {
            "area": "usd_prim_index",
            "status": "placeholder_mapping",
            "source": source,
            "detail": "Object and receptacle USD prim paths are deterministic placeholders.",
        },
        {
            "area": "public_scene_bindings",
            "status": scene_bindings.get("status", "placeholder_mapping"),
            "source": scene_bindings.get("source", source),
            "detail": (
                "Selected cleanup object and target-receptacle bindings are "
                "derived from synthetic scenario fixtures, not real USD prims."
            ),
        },
        {
            "area": "camera_capture",
            "status": "placeholder_visuals",
            "source": source,
            "detail": "FPV, chase, map, and verification images are generated placeholders.",
        },
        {
            "area": "segmentation",
            "status": segmentation.get("status", "blocked_capability"),
            "source": segmentation.get("source", source),
            "detail": str(
                segmentation.get("reason")
                or "Semantic or instance segmentation masks are not exposed yet."
            ),
        },
        {
            "area": "articulation_and_collision",
            "status": "semantic_pose_only",
            "source": source,
            "detail": "Open/place effects are semantic state edits, not physics or planner proof.",
        },
    ]


def _dict(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}
