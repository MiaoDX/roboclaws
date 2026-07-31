from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from roboclaws.backends.isaaclab.b1_readiness_inspection import (
    DEFAULT_B1_MESH_SCENE_USD,
    DEFAULT_B1_SCENE_BASE_USD,
    DEFAULT_B1_SCENE_USD,
    _dict,
    _file_inventory,
    build_overlay_report,
    inspect_map12,
    inspect_obj_mesh,
    inspect_ply_header,
    inspect_scene_engine_asset_layout,
    inspect_usd_stage,
)
from roboclaws.backends.isaaclab.b1_readiness_validation import (
    KNOWN_POOR_BBOX_SEED_POLICY,
    NAVIGATION_PROVENANCE,
    READINESS_SCHEMA,
    SEMANTIC_SOURCE,
    SEMANTIC_USD_BLOCKED,
    validate_alignment_residual_artifact,
    validate_navigation_smoke_artifact,
)
from roboclaws.backends.isaaclab.b1_readiness_waypoints import residual_backed_candidate_waypoints


def build_readiness_artifact(b1_root: Path, map12_root: Path) -> dict[str, Any]:
    b1_root = Path(b1_root)
    map12_root = Path(map12_root)
    scene_layout = inspect_scene_engine_asset_layout(b1_root)
    primary_scene = inspect_usd_stage(b1_root / DEFAULT_B1_SCENE_USD)
    mesh_scene = inspect_usd_stage(b1_root / DEFAULT_B1_MESH_SCENE_USD)
    scene_base = inspect_usd_stage(b1_root / DEFAULT_B1_SCENE_BASE_USD)
    obj_meshes = [inspect_obj_mesh(path) for path in sorted((b1_root / "mesh-files").glob("*.obj"))]
    gaussian_plys = [
        inspect_ply_header(path)
        for path in sorted((b1_root / "point_cloud" / "iteration_100").glob("*.ply"))
    ]
    gaussian_layers = [_file_inventory(path) for path in sorted(b1_root.glob("*/scene_gs.usda"))]
    usd_scene_files = [_file_inventory(path) for path in sorted(b1_root.glob("*/scene.usd"))]
    map12 = inspect_map12(map12_root)
    overlay = build_overlay_report(
        scene_bounds=_dict(primary_scene.get("world_bounds")),
        map12=map12,
    )
    b1_geometry_loaded = bool(primary_scene.get("opened")) and bool(
        _dict(primary_scene.get("world_bounds")).get("valid")
    )
    blockers = []
    if not b1_geometry_loaded:
        blockers.append("B1 rebuilt scene USD did not open with finite world bounds.")
    if overlay["status"] == "blocked":
        blockers.append(str(overlay.get("reason") or "Map 12 overlay could not be derived."))
    return {
        "schema": READINESS_SCHEMA,
        "readiness_status": "static_ready_navigation_pending"
        if not blockers
        else "blocked_static_precheck",
        "static_precheck_only": True,
        "b1_root": str(b1_root),
        "map12_root": str(map12_root),
        "b1_geometry_loaded": b1_geometry_loaded,
        "b1_geometry_source": "rebuilt_scene_engine_usd_meshes",
        "b1_asset_layout": scene_layout,
        "b1_geometry": {
            "local_geometry": primary_scene,
            "gaussian_scene_usd": primary_scene,
            "full_floor_usd": mesh_scene,
            "full_floor_default_usd": scene_base,
            "renderable_robot_view_usd": scene_base,
            "scene_engine_layout": scene_layout,
            "scene_partitions": scene_layout["partitions"],
            "usd_scene_files": usd_scene_files,
            "obj_meshes": obj_meshes,
            "gaussian_point_clouds": gaussian_plys,
            "gaussian_layers": gaussian_layers,
        },
        "usd_object_index_ready": False,
        "usd_receptacle_index_ready": False,
        "reason": "B1 assets are currently coarse meshes without object-level segmentation",
        "map12": map12,
        "map12_overlay_status": overlay["status"],
        "map12_to_b1_usd_transform_status": overlay["transform_status"],
        "map12_overlay": overlay,
        "semantic_source": SEMANTIC_SOURCE,
        "semantic_usd_binding_status": SEMANTIC_USD_BLOCKED,
        "semantic_anchors_are_usd_truth": False,
        "robot_navigation_supported": False,
        "robot_navigation_provenance": "pending_local_isaac_b1_map12_navigation_smoke",
        "robot_navigation_pending_reason": (
            "Static geometry and overlay evidence does not prove robot navigation. "
            "Run the local Isaac B1 / Map 12 navigation smoke before setting "
            "robot_navigation_supported=true."
        ),
        "candidate_navigation_waypoint_count": len(overlay.get("candidate_waypoints") or []),
        "navigation_waypoint_count": 0,
        "robot_view_evidence_status": "pending_local_isaac_navigation_smoke",
        "manipulation_supported": False,
        "blocked_capabilities": [
            "semantic_usd_object_receptacle_binding",
            "pick_place_manipulation",
            "planner_backed_nav2_parity",
        ],
        "blockers": blockers,
    }


def readiness_artifact_with_navigation(
    readiness: dict[str, Any],
    navigation: dict[str, Any],
    *,
    navigation_artifact_path: Path | None = None,
) -> dict[str, Any]:
    payload = json.loads(json.dumps(readiness))
    navigation_errors = validate_navigation_smoke_artifact(navigation, require_files=True)
    payload["static_precheck_only"] = False
    payload["navigation_smoke"] = {
        "artifact": str(navigation_artifact_path) if navigation_artifact_path else "",
        "status": navigation.get("status"),
        "validation_status": "passed" if not navigation_errors else "failed",
        "validation_errors": navigation_errors,
    }
    if navigation_errors:
        payload["robot_navigation_supported"] = False
        payload["robot_navigation_provenance"] = "blocked_local_isaac_b1_map12_navigation_smoke"
        payload["robot_navigation_pending_reason"] = "; ".join(navigation_errors)
        payload["robot_view_evidence_status"] = "blocked"
        payload["navigation_waypoint_count"] = 0
        return payload
    payload["readiness_status"] = "navigation_ready"
    payload["robot_navigation_supported"] = True
    payload["robot_navigation_provenance"] = NAVIGATION_PROVENANCE
    payload["robot_navigation_pending_reason"] = ""
    payload["robot_view_evidence_status"] = "available"
    payload["navigation_waypoint_count"] = int(navigation.get("navigation_waypoint_count") or 0)
    payload["navigation_provenance"] = navigation.get("navigation_provenance")
    payload["navigation_artifact"] = (
        str(navigation_artifact_path) if navigation_artifact_path else ""
    )
    return payload


def readiness_artifact_with_alignment(
    readiness: dict[str, Any],
    alignment: dict[str, Any],
    *,
    alignment_artifact_path: Path | None = None,
) -> dict[str, Any]:
    payload = json.loads(json.dumps(readiness))
    alignment_errors = validate_alignment_residual_artifact(alignment)
    residual = _dict(alignment.get("residual_evidence"))
    area_alignment = [
        item for item in alignment.get("area_alignment") or [] if isinstance(item, dict)
    ]
    selected_transform = _dict(alignment.get("selected_transform"))
    payload["alignment_artifact"] = str(alignment_artifact_path) if alignment_artifact_path else ""
    payload["alignment_validation"] = {
        "status": "passed" if not alignment_errors else "failed",
        "errors": alignment_errors,
    }
    payload["residual_evidence"] = {
        "status": residual.get("status") or "not_available",
        "matched_anchor_count": int(residual.get("matched_anchor_count") or 0),
        "mean_residual_m": residual.get("mean_residual_m"),
        "median_residual_m": residual.get("median_residual_m"),
        "p90_residual_m": residual.get("p90_residual_m"),
        "max_residual_m": residual.get("max_residual_m"),
        "source": residual.get("source") or "",
        "transform_source": residual.get("transform_source") or "",
        "artifact": str(alignment_artifact_path) if alignment_artifact_path else "",
    }
    map12_overlay = payload.setdefault("map12_overlay", {})
    map12_overlay["residual_evidence"] = payload["residual_evidence"]
    map12_overlay["bbox_seed_policy"] = KNOWN_POOR_BBOX_SEED_POLICY
    map12_overlay["verified_transform"] = selected_transform
    payload["area_alignment"] = area_alignment
    if alignment_errors:
        payload["map12_overlay_status"] = "candidate"
        payload["map12_to_b1_usd_transform_status"] = "unverified"
        map12_overlay["status"] = "candidate"
        map12_overlay["transform_status"] = "unverified"
        payload["readiness_alignment_status"] = "alignment_artifact_invalid"
        return payload
    if alignment.get("global_alignment_status") == "verified":
        payload["map12_overlay_status"] = "verified"
        payload["map12_to_b1_usd_transform_status"] = "verified"
        map12_overlay["status"] = "verified"
        map12_overlay["transform_status"] = "verified"
        map12_overlay["candidate_waypoints"] = residual_backed_candidate_waypoints(
            payload,
            selected_transform=selected_transform,
            alignment_artifact_path=alignment_artifact_path,
        )
        payload["candidate_navigation_waypoint_count"] = len(
            map12_overlay.get("candidate_waypoints") or []
        )
        payload["readiness_alignment_status"] = "global_verified"
        return payload
    if any(item.get("alignment_status") == "verified" for item in area_alignment):
        payload["map12_overlay_status"] = "candidate"
        payload["map12_to_b1_usd_transform_status"] = "area_verified_only"
        map12_overlay["status"] = "candidate"
        map12_overlay["transform_status"] = "area_verified_only"
        payload["readiness_alignment_status"] = "area_verified_only"
        return payload
    payload["map12_overlay_status"] = "candidate"
    payload["map12_to_b1_usd_transform_status"] = "unverified"
    map12_overlay["status"] = "candidate"
    map12_overlay["transform_status"] = "unverified"
    payload["readiness_alignment_status"] = "alignment_candidate"
    return payload
