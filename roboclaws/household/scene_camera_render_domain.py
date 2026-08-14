from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import Any

from roboclaws.household import scene_camera_render_contracts as contracts
from roboclaws.household.camera_control import CAMERA_CONTROL_API_NAME
from roboclaws.household.scene_camera_render_diagnostics import render_source_snippet

MOLMOSPACES_LANE_ID = "molmospaces-mujoco"
ISAAC_LANE_ID = "isaaclab-prepared-usd"

OFFICIAL_RENDER_SOURCE_REFERENCES = (
    {
        "evidence_id": "mujoco_housegen_materials",
        "lane": MOLMOSPACES_LANE_ID,
        "path": "vendors/molmospaces/molmo_spaces/housegen/builder.py",
        "line_start": 361,
        "line_end": 399,
        "claim": (
            "MuJoCo scene generation parses source-scene material albedo, specular values, "
            "and diffuse texture paths into MJCF material metadata."
        ),
    },
    {
        "evidence_id": "mujoco_housegen_lights",
        "lane": MOLMOSPACES_LANE_ID,
        "path": "vendors/molmospaces/molmo_spaces/housegen/builder.py",
        "line_start": 455,
        "line_end": 470,
        "claim": (
            "MuJoCo housegen optionally exports house lights, otherwise it creates a "
            "default MJCF light at scene-build time."
        ),
    },
    {
        "evidence_id": "mujoco_asset_texture_material_collection",
        "lane": MOLMOSPACES_LANE_ID,
        "path": "vendors/molmospaces/molmo_spaces/housegen/builder.py",
        "line_start": 1372,
        "line_end": 1452,
        "claim": (
            "MuJoCo asset import copies texture slots and material RGBA into the scene "
            "spec before rendering."
        ),
    },
    {
        "evidence_id": "isaac_preview_surface_material_conversion",
        "lane": ISAAC_LANE_ID,
        "path": (
            "vendors/molmospaces/molmo_spaces_isaac/src/molmo_spaces_isaac/assets/utils/material.py"
        ),
        "line_start": 52,
        "line_end": 112,
        "claim": (
            "Isaac USD conversion maps MJCF materials to USD PreviewSurface materials, "
            "forces opacity to 1.0, maps shininess to roughness, and handles diffuse "
            "textures through USD texture nodes."
        ),
    },
    {
        "evidence_id": "isaac_material_binding_texture_warning",
        "lane": ISAAC_LANE_ID,
        "path": (
            "vendors/molmospaces/molmo_spaces_isaac/src/"
            "molmo_spaces_isaac/assets/house_converter.py"
        ),
        "line_start": 288,
        "line_end": 322,
        "claim": (
            "Isaac material binding warns that textured materials bound to non-Mesh prims "
            "can discard textures at render time."
        ),
    },
    {
        "evidence_id": "isaac_default_lights_and_shadow_flags",
        "lane": ISAAC_LANE_ID,
        "path": (
            "vendors/molmospaces/molmo_spaces_isaac/src/"
            "molmo_spaces_isaac/assets/house_converter.py"
        ),
        "line_start": 325,
        "line_end": 380,
        "claim": (
            "Isaac scene conversion authors default DistantLight/DomeLight and disables "
            "shadow casting on selected wall or ceiling visual prims."
        ),
    },
)

CANONICAL_CAMERA_PROJECTION_THRESHOLD_PX = 0.5
REPO_ROOT = Path(__file__).resolve().parents[2]


def backend_swap_geometry_contract(
    manifest: dict[str, Any],
    *,
    optional_float: Callable[[Any], float | None],
) -> dict[str, Any]:
    camera = (
        manifest.get("camera_control") if isinstance(manifest.get("camera_control"), dict) else {}
    )
    pose = (
        manifest.get("camera_pose_contract")
        if isinstance(manifest.get("camera_pose_contract"), dict)
        else {}
    )
    intrinsics = (
        manifest.get("camera_intrinsics_contract")
        if isinstance(manifest.get("camera_intrinsics_contract"), dict)
        else {}
    )
    room_scale = (
        manifest.get("room_scale_contract")
        if isinstance(manifest.get("room_scale_contract"), dict)
        else {}
    )
    projection = (
        manifest.get("projection_diagnostics")
        if isinstance(manifest.get("projection_diagnostics"), dict)
        else {}
    )
    transform = (
        manifest.get("scene_frame_transform")
        if isinstance(manifest.get("scene_frame_transform"), dict)
        else {}
    )
    visual = (
        manifest.get("visual_diagnostics")
        if isinstance(manifest.get("visual_diagnostics"), dict)
        else {}
    )
    render_calibration = (
        visual.get("render_domain_calibration")
        if isinstance(visual.get("render_domain_calibration"), dict)
        else {}
    )
    required_checks = [
        {
            "check": "same_camera_api",
            "status": "pass" if camera.get("api_name") == CAMERA_CONTROL_API_NAME else "fail",
            "value": camera.get("api_name"),
            "expected": CAMERA_CONTROL_API_NAME,
        },
        {
            "check": "same_explicit_eye_target_pose",
            "status": "pass"
            if pose.get("status") == "same_backend_pose_within_threshold"
            else "fail",
            "value": pose.get("status"),
            "max_delta_m": pose.get("max_pose_delta_m"),
            "threshold_m": pose.get("pose_threshold_m"),
        },
        {
            "check": "same_intrinsics",
            "status": "pass" if intrinsics.get("status") == "intrinsics_consistent" else "fail",
            "value": intrinsics.get("status"),
            "vertical_fov_deg": projection.get("vertical_fov_deg"),
            "resolution": projection.get("resolution") or intrinsics.get("resolution"),
        },
        {
            "check": "same_room_scale",
            "status": "pass"
            if room_scale.get("status") == "same_room_outlines_within_threshold"
            else "fail",
            "value": room_scale.get("status"),
            "max_center_delta_m": room_scale.get("max_room_outline_center_delta_m"),
            "max_size_delta_m": room_scale.get("max_room_outline_size_delta_m"),
            "threshold_m": room_scale.get("room_outline_threshold_m"),
        },
        {
            "check": "same_projected_geometry",
            "status": "pass"
            if projection.get("status") == "same_projected_geometry_within_threshold"
            else "fail",
            "value": projection.get("status"),
            "max_pixel_delta": projection.get("max_pixel_delta"),
            "threshold_px": projection.get("projection_threshold_px"),
        },
    ]
    geometry_pass = all(item["status"] == "pass" for item in required_checks)
    mean_pixel_delta = optional_float(visual.get("mean_absolute_pixel_delta"))
    mean_luminance_delta = optional_float(visual.get("mean_abs_mean_luminance_delta"))
    render_domain_status = str(render_calibration.get("status") or "")
    visual_residual_status = (
        "render_domain_residual_high"
        if render_domain_status == "view_dependent_render_domain_delta"
        else "render_domain_luminance_matched"
        if render_domain_status == "already_luminance_matched"
        else render_domain_status or "missing_visual_diagnostics"
    )
    status = (
        "geometry_swap_ready_render_domain_pending"
        if geometry_pass and visual_residual_status == "render_domain_residual_high"
        else "geometry_swap_ready"
        if geometry_pass
        else "geometry_swap_not_ready"
    )
    return {
        "schema": "backend_swap_geometry_contract_v1",
        "status": status,
        "geometry_contract_status": "pass" if geometry_pass else "fail",
        "visual_residual_status": visual_residual_status,
        "required_checks": required_checks,
        "same_api_agent_swap_claim": geometry_pass,
        "view_count": pose.get("pair_count") or projection.get("pair_count"),
        "target_definition_status": transform.get("target_residual_status"),
        "max_target_center_residual_m": transform.get("max_residual_m"),
        "max_target_distance_to_usd_bounds_m": transform.get("max_distance_to_usd_bounds_m"),
        "max_surface_aim_distance_to_usd_bounds_m": transform.get(
            "max_surface_aim_distance_to_usd_bounds_m"
        ),
        "mean_absolute_pixel_delta": mean_pixel_delta,
        "mean_abs_mean_luminance_delta": mean_luminance_delta,
        "render_domain_status": render_domain_status,
        "recommended_next_action": render_calibration.get("recommended_next_action"),
        "interpretation": (
            "This is the backend-swap contract for agent-facing camera control: the same "
            "Roboclaws camera API, explicit eye/target pose, vertical FOV, room scale, and "
            "pinhole projection must pass before an agent can treat MuJoCo and Isaac as "
            "geometry-compatible backends. Visual residuals are tracked separately because "
            "material, texture, light, shadow, and tone-response differences can still make "
            "the images look different."
        ),
    }


def render_domain_source_diagnostics(manifest: dict[str, Any]) -> dict[str, Any]:
    visual = (
        manifest.get("visual_diagnostics")
        if isinstance(manifest.get("visual_diagnostics"), dict)
        else {}
    )
    calibration = (
        visual.get("render_domain_calibration")
        if isinstance(visual.get("render_domain_calibration"), dict)
        else {}
    )
    source_refs = [render_source_reference(item) for item in OFFICIAL_RENDER_SOURCE_REFERENCES]
    missing = [item for item in source_refs if item.get("status") != "available"]
    lane_summary = {
        MOLMOSPACES_LANE_ID: {
            "renderer_contract": "MJCF materials/textures/lights rendered by MuJoCo",
            "evidence_count": sum(
                1 for item in source_refs if item.get("lane") == MOLMOSPACES_LANE_ID
            ),
        },
        ISAAC_LANE_ID: {
            "renderer_contract": "USD PreviewSurface materials/lights rendered by Isaac",
            "evidence_count": sum(1 for item in source_refs if item.get("lane") == ISAAC_LANE_ID),
        },
    }
    status = "official_sources_available" if not missing else "missing_official_source_refs"
    root_cause_status = (
        "render_contract_mismatch_evidence"
        if calibration.get("status") == "view_dependent_render_domain_delta" and not missing
        else "source_evidence_available"
        if not missing
        else "source_evidence_incomplete"
    )
    return {
        "schema": "scene_camera_render_domain_source_diagnostics_v1",
        "status": status,
        "root_cause_status": root_cause_status,
        "official_source": "vendors/molmospaces",
        "source_reference_count": len(source_refs),
        "available_source_reference_count": len(source_refs) - len(missing),
        "missing_source_reference_count": len(missing),
        "lane_summary": lane_summary,
        "source_references": source_refs,
        "recommended_next_action": (
            "Tune renderer parity at the material/light/texture contract boundary before "
            "changing camera geometry: compare MJCF material/texture/light inputs against "
            "the converted USD PreviewSurface, default light, shadow, and texture-binding "
            "outputs for each high-delta view."
        ),
        "interpretation": (
            "These diagnostics cite the official MolmoSpaces code paths that feed each "
            "backend's renderer. They explain why equal camera geometry can still produce "
            "different images: MuJoCo renders MJCF material/light state, while Isaac renders "
            "converted USD PreviewSurface materials, authored USD lights, shadow flags, and "
            "texture bindings."
        ),
    }


def render_domain_view_triage(
    manifest: dict[str, Any],
    *,
    optional_float: Callable[[Any], float | None],
    view_usd_prim_path: Callable[[dict[str, Any], str], str],
) -> dict[str, Any]:
    visual = (
        manifest.get("visual_diagnostics")
        if isinstance(manifest.get("visual_diagnostics"), dict)
        else {}
    )
    projection = (
        manifest.get("projection_diagnostics")
        if isinstance(manifest.get("projection_diagnostics"), dict)
        else {}
    )
    source = (
        manifest.get("render_domain_source_diagnostics")
        if isinstance(manifest.get("render_domain_source_diagnostics"), dict)
        else render_domain_source_diagnostics(manifest)
    )
    source_ids = [
        str(item.get("evidence_id"))
        for item in source.get("source_references") or []
        if isinstance(item, dict) and item.get("status") == "available"
    ]
    projection_by_view = {
        str(item.get("view_id") or ""): item
        for item in projection.get("pairs") or []
        if isinstance(item, dict)
    }
    views = [item for item in visual.get("views") or [] if isinstance(item, dict)]
    rows = []
    for item in views:
        view_id = str(item.get("view_id") or "")
        delta = item.get("delta") if isinstance(item.get("delta"), dict) else {}
        pixel_delta = optional_float(delta.get("mean_absolute_pixel_delta"))
        luminance_delta = optional_float(delta.get("mean_luminance_delta"))
        luminance_abs = abs(luminance_delta) if luminance_delta is not None else None
        projection_pair = projection_by_view.get(view_id, {})
        projection_delta = optional_float(projection_pair.get("max_pixel_delta"))
        anchor_kind = view_anchor_kind(manifest, view_id)
        usd_prim_path = view_usd_prim_path(manifest, view_id)
        residual_class = view_render_residual_class(
            pixel_delta=pixel_delta,
            luminance_abs=luminance_abs,
        )
        suspicion = view_render_suspicion(
            residual_class=residual_class,
            anchor_kind=anchor_kind,
            usd_prim_path=usd_prim_path,
        )
        rows.append(
            {
                "view_id": view_id,
                "label": item.get("label"),
                "anchor_kind": anchor_kind,
                "usd_prim_path": usd_prim_path,
                "mean_absolute_pixel_delta": pixel_delta,
                "abs_mean_luminance_delta": luminance_abs,
                "max_projection_delta_px": projection_delta,
                "geometry_status": "projection_pass"
                if projection_delta is not None
                and projection_delta <= CANONICAL_CAMERA_PROJECTION_THRESHOLD_PX
                else "projection_missing_or_failed",
                "render_residual_class": residual_class,
                "suspected_contract": suspicion,
                "next_probe": view_render_next_probe(suspicion),
            }
        )
    high = [
        item
        for item in rows
        if item.get("render_residual_class") in {"high_pixel_and_luminance", "high_pixel_delta"}
    ]
    rows.sort(
        key=lambda item: (
            float(item.get("mean_absolute_pixel_delta") or 0.0),
            float(item.get("abs_mean_luminance_delta") or 0.0),
        ),
        reverse=True,
    )
    return {
        "schema": "scene_camera_render_domain_view_triage_v1",
        "status": "computed" if rows else "missing_visual_view_metrics",
        "view_count": len(rows),
        "high_residual_view_count": len(high),
        "source_evidence_ids": source_ids,
        "top_residual_view_id": rows[0].get("view_id") if rows else None,
        "views": rows,
        "recommended_next_action": (
            "Start with the highest-residual object/receptacle views. For object views, "
            "compare the MuJoCo MJCF material/texture assigned to the anchor against the "
            "Isaac USD material binding and PreviewSurface inputs for the same prim. For "
            "room views, compare exported/default lights and wall or ceiling shadow flags."
        ),
        "interpretation": (
            "This view-level triage keeps camera geometry separate from renderer-domain "
            "work. A view can have projection_pass while still carrying a material, "
            "texture, lighting, shadow, or tone-response residual."
        ),
    }


def view_anchor_kind(manifest: dict[str, Any], view_id: str) -> str:
    for view in manifest.get("canonical_camera_views") or []:
        if isinstance(view, dict) and str(view.get("view_id") or "") == view_id:
            return str(view.get("anchor_kind") or "")
    return ""


def view_render_residual_class(
    *,
    pixel_delta: float | None,
    luminance_abs: float | None,
) -> str:
    if pixel_delta is None:
        return "missing_pixel_delta"
    pixel_high = pixel_delta >= 50.0
    luminance_high = luminance_abs is not None and luminance_abs >= 30.0
    if pixel_high and luminance_high:
        return "high_pixel_and_luminance"
    if pixel_high:
        return "high_pixel_delta"
    if luminance_high:
        return "high_luminance_delta"
    return "moderate_or_low_residual"


def view_render_suspicion(
    *,
    residual_class: str,
    anchor_kind: str,
    usd_prim_path: str,
) -> str:
    if residual_class == "moderate_or_low_residual":
        return "lower_priority_renderer_delta"
    if anchor_kind == "room":
        return "room_light_wall_shadow_contract"
    if usd_prim_path:
        return "object_material_texture_binding_contract"
    return "object_material_texture_contract_missing_usd_prim"


def view_render_next_probe(suspicion: str) -> str:
    if suspicion == "room_light_wall_shadow_contract":
        return "Compare MuJoCo default/exported lights with Isaac USD lights and wall shadow flags."
    if suspicion == "object_material_texture_binding_contract":
        return "Compare MJCF material/texture inputs with the matched Isaac USD material binding."
    if suspicion == "object_material_texture_contract_missing_usd_prim":
        return "Resolve the Isaac USD prim path before comparing material or texture contracts."
    return "Keep as lower priority until high-residual views are explained."


def render_domain_contract_probe(
    manifest: dict[str, Any],
    *,
    render_domain_view_triage_builder: Callable[[dict[str, Any]], dict[str, Any]],
    mujoco_render_contract_from_xml: Callable[[Any], dict[str, Any]],
    isaac_render_contract_from_usda: Callable[[Any], dict[str, Any]],
    view_usd_prim_path: Callable[[dict[str, Any], str], str],
) -> dict[str, Any]:
    triage = (
        manifest.get("render_domain_view_triage")
        if isinstance(manifest.get("render_domain_view_triage"), dict)
        else render_domain_view_triage_builder(manifest)
    )
    artifacts = contracts.render_domain_artifact_paths(manifest)
    mujoco = mujoco_render_contract_from_xml(artifacts.get("mujoco_scene_xml"))
    isaac = isaac_render_contract_from_usda(artifacts.get("isaac_scene_usd"))
    views = []
    for item in triage.get("views") or []:
        if not isinstance(item, dict):
            continue
        suspicion = str(item.get("suspected_contract") or "")
        if suspicion not in {
            "object_material_texture_binding_contract",
            "object_material_texture_contract_missing_usd_prim",
            "room_light_wall_shadow_contract",
        }:
            continue
        view_id = str(item.get("view_id") or "")
        anchor_id = contracts.view_anchor_id(manifest, view_id)
        usd_prim_path = str(item.get("usd_prim_path") or view_usd_prim_path(manifest, view_id))
        mujoco_contract = contracts.mujoco_view_render_contract(mujoco, anchor_id=anchor_id)
        isaac_contract = contracts.isaac_view_render_contract(isaac, usd_prim_path=usd_prim_path)
        view_probe = {
            "view_id": view_id,
            "anchor_id": anchor_id,
            "anchor_kind": item.get("anchor_kind"),
            "suspected_contract": suspicion,
            "render_residual_class": item.get("render_residual_class"),
            "mean_absolute_pixel_delta": item.get("mean_absolute_pixel_delta"),
            "abs_mean_luminance_delta": item.get("abs_mean_luminance_delta"),
            "mujoco": mujoco_contract,
            "isaac": isaac_contract,
            "contract_delta": contracts.view_render_contract_delta(
                suspicion=suspicion,
                mujoco=mujoco_contract,
                isaac=isaac_contract,
            ),
        }
        views.append(view_probe)
    status = "computed" if views else "missing_triaged_views"
    if mujoco.get("status") != "parsed" or isaac.get("status") != "parsed":
        status = "partial_artifact_parse"
    high_priority = [
        item
        for item in views
        if (item.get("contract_delta") or {}).get("status")
        in {
            "material_or_texture_name_delta",
            "light_or_shadow_contract_delta",
            "missing_object_binding_evidence",
        }
    ]
    return {
        "schema": "scene_camera_render_domain_contract_probe_v1",
        "status": status,
        "artifact_paths": artifacts,
        "mujoco_parse_status": mujoco.get("status"),
        "isaac_parse_status": isaac.get("status"),
        "view_count": len(views),
        "high_priority_delta_count": len(high_priority),
        "mujoco_light_count": len(mujoco.get("lights") or []),
        "mujoco_lights": mujoco.get("lights") or [],
        "isaac_light_count": len(isaac.get("lights") or []),
        "isaac_lights": isaac.get("lights") or [],
        "isaac_shadow_disabled_prim_count": len(isaac.get("shadow_disabled_prims") or []),
        "visual_physics_status": isaac.get("visual_physics_status"),
        "mujoco_visual_joint_endpoint_pose_status": isaac.get(
            "mujoco_visual_joint_endpoint_pose_status"
        ),
        "mujoco_visual_joint_endpoint_pose_corrected_count": isaac.get(
            "mujoco_visual_joint_endpoint_pose_corrected_count"
        ),
        "mujoco_visual_joint_endpoint_pose_missing_count": isaac.get(
            "mujoco_visual_joint_endpoint_pose_missing_count"
        ),
        "visual_physics_joint_removed_count": isaac.get("visual_physics_joint_removed_count"),
        "visual_physics_api_schema_removed_count": isaac.get(
            "visual_physics_api_schema_removed_count"
        ),
        "visual_physics_property_removed_count": isaac.get("visual_physics_property_removed_count"),
        "views": views,
        "recommended_next_action": contracts.render_domain_contract_probe_next_action(views),
        "interpretation": (
            "This probe reads the actual scene artifacts behind the rendered images. It is "
            "not a screenshot metric: it checks whether high-residual views have matching "
            "MJCF material/texture inputs and Isaac USD material bindings, and whether room "
            "views share compatible light and shadow contracts."
        ),
    }


def render_source_reference(reference: dict[str, Any]) -> dict[str, Any]:
    rel_path = Path(str(reference.get("path") or ""))
    path = REPO_ROOT / rel_path
    line_start = int(reference.get("line_start") or 1)
    line_end = int(reference.get("line_end") or line_start)
    exists = path.is_file()
    snippet_status = "missing"
    snippet = ""
    if exists:
        try:
            lines = path.read_text(encoding="utf-8").splitlines()
            selected = lines[max(line_start - 1, 0) : max(line_end, line_start)]
            snippet_status = "available" if selected else "empty"
            snippet = render_source_snippet(selected)
        except OSError:
            snippet_status = "unreadable"
    return {
        "evidence_id": reference.get("evidence_id"),
        "lane": reference.get("lane"),
        "path": str(rel_path),
        "line_start": line_start,
        "line_end": line_end,
        "status": "available" if exists and snippet_status == "available" else snippet_status,
        "claim": reference.get("claim"),
        "snippet_summary": snippet,
    }
