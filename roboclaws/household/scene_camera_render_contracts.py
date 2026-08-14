from __future__ import annotations

from pathlib import Path
from typing import Any

MOLMOSPACES_LANE_ID = "molmospaces-mujoco"
ISAAC_LANE_ID = "isaaclab-prepared-usd"


def render_domain_artifact_paths(manifest: dict[str, Any]) -> dict[str, str]:
    lanes = manifest.get("lanes") if isinstance(manifest.get("lanes"), dict) else {}
    mujoco_lane = (
        lanes.get(MOLMOSPACES_LANE_ID) if isinstance(lanes.get(MOLMOSPACES_LANE_ID), dict) else {}
    )
    isaac_lane = lanes.get(ISAAC_LANE_ID) if isinstance(lanes.get(ISAAC_LANE_ID), dict) else {}
    scene = manifest.get("scene") if isinstance(manifest.get("scene"), dict) else {}
    return {
        "mujoco_scene_xml": str(mujoco_lane.get("scene_xml") or ""),
        "isaac_scene_usd": str(isaac_lane.get("scene_usd") or scene.get("scene_usd_path") or ""),
    }


def mujoco_view_render_contract(
    mujoco: dict[str, Any],
    *,
    anchor_id: str,
) -> dict[str, Any]:
    if mujoco.get("status") != "parsed":
        return {"status": mujoco.get("status")}
    visuals = []
    body_visuals = (
        mujoco.get("body_visuals") if isinstance(mujoco.get("body_visuals"), dict) else {}
    )
    if anchor_id:
        visuals = list(body_visuals.get(anchor_id) or [])
    if not visuals and anchor_id:
        for body_name, body_entries in body_visuals.items():
            if str(body_name).startswith(anchor_id):
                visuals.extend(body_entries)
    return {
        "status": "bound" if visuals else "missing_anchor_visuals",
        "visual_geom_count": len(visuals),
        "materials": sorted(
            {str(item.get("material") or "") for item in visuals if item.get("material")}
        ),
        "textures": sorted(
            {str(item.get("texture") or "") for item in visuals if item.get("texture")}
        ),
        "texture_files": sorted(
            {str(item.get("texture_file") or "") for item in visuals if item.get("texture_file")}
        ),
        "visuals": visuals[:8],
        "lights": mujoco.get("lights") or [],
    }


def isaac_view_render_contract(
    isaac: dict[str, Any],
    *,
    usd_prim_path: str,
) -> dict[str, Any]:
    if isaac.get("status") != "parsed":
        return {"status": isaac.get("status")}
    bindings_by_prim = (
        isaac.get("material_bindings") if isinstance(isaac.get("material_bindings"), dict) else {}
    )
    bindings = []
    if usd_prim_path:
        prefix = usd_prim_path.rstrip("/") + "/"
        for prim_path, prim_bindings in bindings_by_prim.items():
            if prim_path == usd_prim_path or str(prim_path).startswith(prefix):
                for binding in prim_bindings:
                    bindings.append({"prim_path": prim_path, **binding})
    shadow_disabled_prims = [
        prim
        for prim in isaac.get("shadow_disabled_prims") or []
        if not usd_prim_path
        or str(prim) == usd_prim_path
        or str(prim).startswith(usd_prim_path + "/")
    ]
    physics_joint_paths = usd_paths_under(
        isaac.get("physics_joint_paths") or [], usd_prim_path=usd_prim_path
    )
    physics_api_schema_prim_paths = usd_paths_under(
        isaac.get("physics_api_schema_prim_paths") or [], usd_prim_path=usd_prim_path
    )
    physics_property_prim_paths = usd_paths_under(
        isaac.get("physics_property_prim_paths") or [], usd_prim_path=usd_prim_path
    )
    visual_physics_status = (
        "frozen_static_visual_usd"
        if not physics_joint_paths
        and not physics_api_schema_prim_paths
        and not physics_property_prim_paths
        else "physics_articulation_preserved"
    )
    return {
        "status": "bound" if bindings else "missing_usd_material_bindings",
        "bound_prim_count": len({str(item.get("prim_path") or "") for item in bindings}),
        "material_binding_count": len(bindings),
        "materials": sorted(
            {
                str(item.get("material_name") or Path(str(item.get("material_path") or "")).name)
                for item in bindings
                if item.get("material_path")
            }
        ),
        "texture_files": sorted(
            {
                str(texture)
                for item in bindings
                for texture in item.get("diffuse_texture_files") or []
            }
        ),
        "has_diffuse_texture_count": sum(1 for item in bindings if item.get("has_diffuse_texture")),
        "shadow_disabled_prim_count": len(shadow_disabled_prims),
        "bindings": bindings[:8],
        "lights": isaac.get("lights") or [],
        "shadow_disabled_prims": shadow_disabled_prims[:8],
        "visual_physics_status": visual_physics_status,
        "physics_joint_count": len(physics_joint_paths),
        "physics_api_schema_prim_count": len(physics_api_schema_prim_paths),
        "physics_property_prim_count": len(physics_property_prim_paths),
        "physics_joint_paths": physics_joint_paths[:8],
        "physics_api_schema_prim_paths": physics_api_schema_prim_paths[:8],
        "physics_property_prim_paths": physics_property_prim_paths[:8],
        "prepared_summary_status": isaac.get("prepared_summary_status"),
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
    }


def usd_paths_under(paths: Any, *, usd_prim_path: str) -> list[str]:
    if not usd_prim_path:
        return sorted(str(path) for path in paths or [] if str(path))
    prefix = usd_prim_path.rstrip("/") + "/"
    return sorted(
        str(path)
        for path in paths or []
        if str(path) == usd_prim_path or str(path).startswith(prefix)
    )


def view_render_contract_delta(
    *,
    suspicion: str,
    mujoco: dict[str, Any],
    isaac: dict[str, Any],
) -> dict[str, Any]:
    if suspicion == "room_light_wall_shadow_contract":
        mujoco_lights = len(mujoco.get("lights") or [])
        isaac_lights = len(isaac.get("lights") or [])
        shadow_disabled = int(isaac.get("shadow_disabled_prim_count") or 0)
        status = (
            "light_or_shadow_contract_delta"
            if mujoco_lights != isaac_lights or shadow_disabled > 0
            else "light_count_matched"
        )
        return {
            "status": status,
            "mujoco_light_count": mujoco_lights,
            "isaac_light_count": isaac_lights,
            "isaac_shadow_disabled_prim_count": shadow_disabled,
        }
    if mujoco.get("status") != "bound" or isaac.get("status") != "bound":
        return {
            "status": "missing_object_binding_evidence",
            "mujoco_status": mujoco.get("status"),
            "isaac_status": isaac.get("status"),
        }
    mujoco_materials = set(mujoco.get("materials") or [])
    isaac_materials = set(isaac.get("materials") or [])
    mujoco_textures = {Path(str(item)).name for item in mujoco.get("texture_files") or []}
    isaac_textures = {Path(str(item)).name for item in isaac.get("texture_files") or []}
    status = (
        "material_or_texture_name_delta"
        if mujoco_materials != isaac_materials or mujoco_textures != isaac_textures
        else "material_texture_names_match"
    )
    return {
        "status": status,
        "mujoco_material_count": len(mujoco_materials),
        "isaac_material_count": len(isaac_materials),
        "mujoco_texture_count": len(mujoco_textures),
        "isaac_texture_count": len(isaac_textures),
        "material_names_only_in_mujoco": sorted(mujoco_materials - isaac_materials),
        "material_names_only_in_isaac": sorted(isaac_materials - mujoco_materials),
        "texture_files_only_in_mujoco": sorted(mujoco_textures - isaac_textures),
        "texture_files_only_in_isaac": sorted(isaac_textures - mujoco_textures),
    }


def render_domain_contract_probe_next_action(views: list[dict[str, Any]]) -> str:
    for item in views:
        delta = item.get("contract_delta") if isinstance(item.get("contract_delta"), dict) else {}
        if delta.get("status") == "material_or_texture_name_delta":
            return (
                "Compare the top object view's MJCF material names and texture file basenames "
                "against the USD PreviewSurface bindings; fix converter naming or texture "
                "copy/binding before tuning camera or exposure."
            )
        if delta.get("status") == "light_or_shadow_contract_delta":
            return (
                "Align room-level light count/intensity and wall or ceiling shadow flags before "
                "treating room-view residuals as camera differences."
            )
    return (
        "Use this probe to choose the next renderer parity edit; geometry remains a separate pass."
    )


def view_anchor_id(manifest: dict[str, Any], view_id: str) -> str:
    for view in manifest.get("canonical_camera_views") or []:
        if isinstance(view, dict) and str(view.get("view_id") or "") == view_id:
            return str(view.get("anchor_id") or "")
    return ""
