from __future__ import annotations

from pathlib import Path
from typing import Any

import numpy as np

from roboclaws.maps.b1_alignment_contract import (
    B1_MAP12_ALIGNMENT_RESIDUALS_SCHEMA,
    GLOBAL_MAX_THRESHOLD_M,
    GLOBAL_MEAN_THRESHOLD_M,
    MIN_GLOBAL_ACCEPTED_ANCHORS,
    SOURCE_MAP_FRAME,
    TARGET_SCENE_FRAME,
    accepted_correspondence_anchors,
    scene_projection_policy,
    threshold_policy,
    validate_correspondence_manifest,
)
from roboclaws.maps.b1_alignment_preview import write_alignment_previews
from roboclaws.maps.b1_alignment_transform import (
    anchor_scene_xy,
    area_alignment_reports,
    fit_affine_transform,
    fit_transform_candidate,
    leave_one_out_residuals,
    residual_metrics,
    residual_rows,
    select_global_transform,
    spatial_gate_errors,
    unavailable_residual_evidence,
)


def build_alignment_residuals(
    manifest: dict[str, Any],
    *,
    map_bundle: Path,
    output_dir: Path,
    correspondences_path: Path | None = None,
) -> dict[str, Any]:
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    manifest_errors = validate_correspondence_manifest(manifest)
    anchors = accepted_correspondence_anchors(manifest) if not manifest_errors else []
    common = {
        "schema": B1_MAP12_ALIGNMENT_RESIDUALS_SCHEMA,
        "source_manifest_schema": manifest.get("schema"),
        "correspondences_artifact": str(correspondences_path) if correspondences_path else "",
        "map_bundle": str(map_bundle),
        "source_map_frame": str(manifest.get("source_map_frame") or SOURCE_MAP_FRAME),
        "target_scene_frame": str(manifest.get("target_scene_frame") or TARGET_SCENE_FRAME),
        "bbox_seed_policy": str(manifest.get("bbox_seed_policy") or ""),
        "scene_projection_policy": scene_projection_policy(manifest),
        "threshold_policy": threshold_policy(),
        "manifest_validation": {
            "status": "passed" if not manifest_errors else "failed",
            "errors": manifest_errors,
        },
        "accepted_anchor_count": len(anchors),
        "accepted_navigation_area_count": len(
            {
                str(anchor.get("navigation_area_id") or "")
                for anchor in anchors
                if anchor.get("navigation_area_id")
            }
        ),
        "accepted_asset_partition_count": len(
            {
                str(anchor.get("asset_partition_id") or "")
                for anchor in anchors
                if anchor.get("asset_partition_id")
            }
        ),
        "object_receptacle_usd_binding_status": "blocked_out_of_scope",
        "manipulation_supported": False,
        "planner_backed_navigation_status": "blocked_out_of_scope",
    }
    if manifest_errors:
        return {
            **common,
            "status": "invalid_manifest",
            "global_alignment_status": "blocked",
            "selected_transform_type": "",
            "selected_transform": {},
            "residual_evidence": unavailable_residual_evidence(
                "Correspondence manifest failed validation."
            ),
            "area_alignment": [],
            "transform_candidates": [],
            "diagnostic_affine_transform": {},
            "previews": {},
        }
    if len(anchors) < MIN_GLOBAL_ACCEPTED_ANCHORS:
        preview_paths = write_alignment_previews(
            anchors,
            selected_transform=None,
            output_dir=output_dir,
            manifest=manifest,
        )
        return {
            **common,
            "status": "insufficient_reviewed_anchors",
            "global_alignment_status": "candidate",
            "selected_transform_type": "",
            "selected_transform_reason": (
                "Need at least six accepted, human/operator-reviewed anchors before "
                "global residual thresholds can be evaluated."
            ),
            "selected_transform": {},
            "residual_evidence": unavailable_residual_evidence(
                "Too few accepted correspondence anchors.",
                matched_anchor_count=len(anchors),
            ),
            "area_alignment": area_alignment_reports(
                anchors,
                selected_transform=None,
                manifest=manifest,
            ),
            "transform_candidates": [],
            "diagnostic_affine_transform": {},
            "previews": preview_paths,
        }

    source_points = np.array([anchor["map_xy"] for anchor in anchors], dtype=float)
    target_points = np.array([anchor_scene_xy(anchor, manifest) for anchor in anchors], dtype=float)
    spatial_errors = spatial_gate_errors(anchors, source_points)
    transform_candidates = [
        fit_transform_candidate("rigid_2d", source_points, target_points),
        fit_transform_candidate("similarity_2d", source_points, target_points),
    ]
    diagnostic_affine = fit_affine_transform(source_points, target_points)
    selected = select_global_transform(transform_candidates, spatial_errors)
    selected_transform = selected.get("transform") if selected.get("passed") else None
    selected_residuals = (
        residual_rows(anchors, selected_transform, manifest)
        if selected_transform is not None
        else []
    )
    selected_metrics = residual_metrics([row["residual_m"] for row in selected_residuals])
    leave_one_out = leave_one_out_residuals(anchors, selected.get("transform_type") or "", manifest)
    area_alignment = area_alignment_reports(
        anchors,
        selected_transform=selected_transform,
        manifest=manifest,
    )
    preview_paths = write_alignment_previews(
        anchors,
        selected_transform=selected_transform,
        output_dir=output_dir,
        manifest=manifest,
    )
    return {
        **common,
        "status": "global_verified" if selected.get("passed") else "global_failed",
        "global_alignment_status": "verified" if selected.get("passed") else "candidate",
        "selected_transform_type": selected.get("transform_type") or "",
        "selected_transform_reason": selected.get("reason") or "",
        "selected_transform": selected.get("transform") or {},
        "residual_evidence": {
            "status": "available" if selected_residuals else "not_available",
            "matched_anchor_count": len(selected_residuals),
            "source": "reviewed_correspondence_residuals",
            "transform_source": "reviewed_correspondence_fit",
            "transform_type": selected.get("transform_type") or "",
            "mean_residual_m": selected_metrics.get("mean_residual_m"),
            "median_residual_m": selected_metrics.get("median_residual_m"),
            "p90_residual_m": selected_metrics.get("p90_residual_m"),
            "max_residual_m": selected_metrics.get("max_residual_m"),
            "thresholds": {
                "mean_residual_m": GLOBAL_MEAN_THRESHOLD_M,
                "max_residual_m": GLOBAL_MAX_THRESHOLD_M,
            },
            "passed": bool(selected.get("passed")),
            "failure_reasons": selected.get("failure_reasons") or [],
        },
        "global_fit_spatial_gate_errors": spatial_errors,
        "residuals": selected_residuals,
        "leave_one_out_residuals": leave_one_out,
        "area_alignment": area_alignment,
        "transform_candidates": transform_candidates,
        "diagnostic_affine_transform": diagnostic_affine,
        "previews": preview_paths,
    }
