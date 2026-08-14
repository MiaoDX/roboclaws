#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import math
import sys
from pathlib import Path
from typing import Any

import numpy as np
from PIL import Image, ImageDraw

if __package__ in {None, ""}:
    repo_root = Path(__file__).resolve().parents[2]
    if str(repo_root) not in sys.path:
        sys.path.insert(0, str(repo_root))

from roboclaws.core.json_sources import read_json_object  # noqa: E402

B1_MAP12_CORRESPONDENCES_SCHEMA = "b1_map12_scene_correspondences_v1"
B1_MAP12_ALIGNMENT_RESIDUALS_SCHEMA = "b1_map12_scene_alignment_residuals_v1"
SOURCE_MAP_FRAME = "robot_map_12_map"
TARGET_SCENE_FRAME = "b1_rebuilt_scene_usd_world"
KNOWN_POOR_BBOX_SEED_POLICY = "known_poor_seed_only"
KNOWN_POOR_BBOX_SEED_SOURCE = "known_poor_bbox_seed"
BBOX_FIT_METHOD = "bbox_fit_navigation_memory_nav_goals_to_scene_usd_bounds"
SCENE_PROJECTION_HORIZONTAL_AXES = ["x", "y"]
SCENE_PROJECTION_UP_AXIS = "z"
ALIGNMENT_ANCHOR_ROLE = "alignment"
SEMANTIC_ANCHOR_ROLE = "semantic"
ANCHOR_ROLES = {ALIGNMENT_ANCHOR_ROLE, SEMANTIC_ANCHOR_ROLE}

MIN_GLOBAL_ACCEPTED_ANCHORS = 6
MIN_GLOBAL_NON_COLLINEAR_ANCHORS = 4
GLOBAL_MEAN_THRESHOLD_M = 0.75
GLOBAL_MAX_THRESHOLD_M = 1.5
MIN_AREA_ACCEPTED_ANCHORS = 3
MIN_AREA_NON_COLLINEAR_ANCHORS = 3
AREA_MEAN_THRESHOLD_M = 0.5
AREA_MAX_THRESHOLD_M = 1.0


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Fit B1 / Map 12 map-scene alignment from reviewed correspondences."
    )
    parser.add_argument("--correspondences", type=Path, required=True)
    parser.add_argument("--map-bundle", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    try:
        manifest = read_json_object(args.correspondences, label="correspondence manifest")
        payload = build_alignment_residuals(
            manifest,
            map_bundle=args.map_bundle,
            output_dir=args.output_dir,
            correspondences_path=args.correspondences,
        )
    except (FileNotFoundError, ValueError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    errors = validate_alignment_residual_artifact(payload)
    payload["validation"] = {
        "status": "passed" if not errors else "failed",
        "errors": errors,
    }
    args.output_dir.mkdir(parents=True, exist_ok=True)
    output_path = args.output_dir / "alignment_residuals.json"
    output_path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(
        json.dumps(
            {
                "schema": B1_MAP12_ALIGNMENT_RESIDUALS_SCHEMA,
                "status": payload.get("status"),
                "global_alignment_status": payload.get("global_alignment_status"),
                "selected_transform_type": payload.get("selected_transform_type"),
                "accepted_anchor_count": payload.get("accepted_anchor_count"),
                "output": str(output_path),
                "errors": errors,
            },
            sort_keys=True,
        )
    )
    return 0 if not errors else 2


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


def validate_correspondence_manifest(payload: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    _require(
        payload.get("schema") == B1_MAP12_CORRESPONDENCES_SCHEMA,
        "unexpected correspondence manifest schema",
        errors,
    )
    _require(
        payload.get("source_map_frame") == SOURCE_MAP_FRAME,
        "source_map_frame must be robot_map_12_map",
        errors,
    )
    _require(
        payload.get("target_scene_frame") == TARGET_SCENE_FRAME,
        "target_scene_frame must be b1_rebuilt_scene_usd_world",
        errors,
    )
    _require(
        payload.get("bbox_seed_policy") == KNOWN_POOR_BBOX_SEED_POLICY,
        "bbox_seed_policy must be known_poor_seed_only",
        errors,
    )
    projection = scene_projection_policy(payload)
    _require(
        projection["horizontal_axes"] == SCENE_PROJECTION_HORIZONTAL_AXES,
        "scene_projection_policy.horizontal_axes must be ['x', 'y']",
        errors,
    )
    _require(
        projection["up_axis"] == SCENE_PROJECTION_UP_AXIS,
        "scene_projection_policy.up_axis must be z",
        errors,
    )
    seen: set[str] = set()
    for index, raw_anchor in enumerate(payload.get("anchors") or [], start=1):
        anchor = raw_anchor if isinstance(raw_anchor, dict) else {}
        anchor_id = str(anchor.get("anchor_id") or "")
        _require(bool(anchor_id), f"anchor {index} missing anchor_id", errors)
        if anchor_id in seen:
            errors.append(f"anchor {anchor_id} is duplicated")
        seen.add(anchor_id)
        status = str(anchor.get("review_status") or "")
        if status != "accepted":
            continue
        role = anchor_role(anchor)
        _require(
            bool(anchor.get("anchor_role")),
            f"accepted anchor {anchor_id} needs anchor_role",
            errors,
        )
        _require(
            role in ANCHOR_ROLES,
            f"accepted anchor {anchor_id} has invalid anchor_role: {role}",
            errors,
        )
        _require(
            valid_xy(anchor.get("map_xy")),
            f"accepted anchor {anchor_id} needs explicit map_xy",
            errors,
        )
        _require(
            valid_xyz(anchor.get("scene_xyz")),
            f"accepted anchor {anchor_id} needs explicit scene_xyz",
            errors,
        )
        if role == SEMANTIC_ANCHOR_ROLE:
            _require(
                bool(anchor.get("navigation_area_id")),
                f"accepted semantic anchor {anchor_id} needs navigation_area_id",
                errors,
            )
            _require(
                bool(anchor.get("asset_partition_id")),
                f"accepted semantic anchor {anchor_id} needs asset_partition_id",
                errors,
            )
        _require(
            not anchor_uses_known_poor_seed(anchor),
            f"accepted anchor {anchor_id} must not use known-poor bbox seed coordinates",
            errors,
        )
    return errors


def validate_alignment_residual_artifact(payload: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    _require(
        payload.get("schema") == B1_MAP12_ALIGNMENT_RESIDUALS_SCHEMA,
        "unexpected alignment residual schema",
        errors,
    )
    _require(
        payload.get("bbox_seed_policy") == KNOWN_POOR_BBOX_SEED_POLICY,
        "bbox seed must remain labeled known_poor_seed_only",
        errors,
    )
    _require(
        payload.get("manipulation_supported") is False,
        "alignment artifact must not claim manipulation support",
        errors,
    )
    _require(
        payload.get("object_receptacle_usd_binding_status") == "blocked_out_of_scope",
        "alignment artifact must keep object/receptacle USD binding blocked",
        errors,
    )
    residual = _dict(payload.get("residual_evidence"))
    transform_source = str(residual.get("transform_source") or "")
    transform = _dict(payload.get("selected_transform"))
    if payload.get("global_alignment_status") == "verified":
        _require(
            residual.get("status") == "available",
            "verified alignment requires available residual evidence",
            errors,
        )
        _require(
            int(residual.get("matched_anchor_count") or 0) >= MIN_GLOBAL_ACCEPTED_ANCHORS,
            "verified alignment requires at least six matched anchors",
            errors,
        )
        _require(
            optional_float(residual.get("mean_residual_m"), default=math.inf)
            <= GLOBAL_MEAN_THRESHOLD_M,
            "verified alignment mean residual exceeds threshold",
            errors,
        )
        _require(
            optional_float(residual.get("max_residual_m"), default=math.inf)
            <= GLOBAL_MAX_THRESHOLD_M,
            "verified alignment max residual exceeds threshold",
            errors,
        )
        _require(
            transform_source != KNOWN_POOR_BBOX_SEED_SOURCE,
            "verified alignment must not use known-poor bbox seed",
            errors,
        )
        _require(
            str(transform.get("source") or "") != KNOWN_POOR_BBOX_SEED_SOURCE
            and str(transform.get("method") or "") != BBOX_FIT_METHOD,
            "verified transform must not come from bbox-fit seed",
            errors,
        )
    for area in payload.get("area_alignment") or []:
        if not isinstance(area, dict) or area.get("alignment_status") != "verified":
            continue
        _require(
            int(area.get("matched_anchor_count") or 0) >= MIN_AREA_ACCEPTED_ANCHORS,
            "area verified alignment requires at least three matched anchors",
            errors,
        )
        _require(
            optional_float(area.get("max_residual_m"), default=math.inf) <= AREA_MAX_THRESHOLD_M,
            "area verified alignment max residual exceeds threshold",
            errors,
        )
    return errors


def accepted_correspondence_anchors(payload: dict[str, Any]) -> list[dict[str, Any]]:
    anchors = []
    for raw_anchor in payload.get("anchors") or []:
        if not isinstance(raw_anchor, dict) or raw_anchor.get("review_status") != "accepted":
            continue
        if not valid_xy(raw_anchor.get("map_xy")) or not valid_xyz(raw_anchor.get("scene_xyz")):
            continue
        anchor = dict(raw_anchor)
        anchor["map_xy"] = [float(anchor["map_xy"][0]), float(anchor["map_xy"][1])]
        anchor["scene_xyz"] = [
            float(anchor["scene_xyz"][0]),
            float(anchor["scene_xyz"][1]),
            float(anchor["scene_xyz"][2]),
        ]
        anchor["anchor_role"] = anchor_role(anchor)
        anchors.append(anchor)
    return anchors


def scene_projection_policy(payload: dict[str, Any]) -> dict[str, Any]:
    raw = _dict(payload.get("scene_projection_policy"))
    axes = raw.get("horizontal_axes")
    if not isinstance(axes, list) or len(axes) != 2:
        axes = SCENE_PROJECTION_HORIZONTAL_AXES
    return {
        "horizontal_axes": [str(axes[0]), str(axes[1])],
        "up_axis": str(raw.get("up_axis") or SCENE_PROJECTION_UP_AXIS),
        "source": str(raw.get("source") or "2rd_floor_seperated_scene_topdown_policy"),
    }


def threshold_policy() -> dict[str, Any]:
    return {
        "minimum_global_anchors": MIN_GLOBAL_ACCEPTED_ANCHORS,
        "minimum_global_non_collinear_anchors": MIN_GLOBAL_NON_COLLINEAR_ANCHORS,
        "global_verified_target": {
            "mean_residual_m": GLOBAL_MEAN_THRESHOLD_M,
            "max_residual_m": GLOBAL_MAX_THRESHOLD_M,
        },
        "minimum_area_anchors": MIN_AREA_ACCEPTED_ANCHORS,
        "minimum_area_non_collinear_anchors": MIN_AREA_NON_COLLINEAR_ANCHORS,
        "area_verified_target": {
            "mean_residual_m": AREA_MEAN_THRESHOLD_M,
            "max_residual_m": AREA_MAX_THRESHOLD_M,
        },
    }


def fit_transform_candidate(
    transform_type: str,
    source_points: np.ndarray,
    target_points: np.ndarray,
) -> dict[str, Any]:
    if transform_type == "rigid_2d":
        transform = fit_rigid_transform(source_points, target_points)
    elif transform_type == "similarity_2d":
        transform = fit_similarity_transform(source_points, target_points)
    else:
        raise ValueError(f"unknown transform type: {transform_type}")
    predicted = apply_transform_array(source_points, transform)
    residual_values = np.linalg.norm(predicted - target_points, axis=1)
    metrics = residual_metrics([float(value) for value in residual_values])
    passed = (
        bool(metrics)
        and float(metrics["mean_residual_m"]) <= GLOBAL_MEAN_THRESHOLD_M
        and float(metrics["max_residual_m"]) <= GLOBAL_MAX_THRESHOLD_M
    )
    return {
        "transform_type": transform_type,
        "transform": transform,
        **metrics,
        "thresholds": {
            "mean_residual_m": GLOBAL_MEAN_THRESHOLD_M,
            "max_residual_m": GLOBAL_MAX_THRESHOLD_M,
        },
        "passes_residual_thresholds": passed,
    }


def fit_rigid_transform(source_points: np.ndarray, target_points: np.ndarray) -> dict[str, Any]:
    source_centroid = source_points.mean(axis=0)
    target_centroid = target_points.mean(axis=0)
    source_centered = source_points - source_centroid
    target_centered = target_points - target_centroid
    covariance = source_centered.T @ target_centered
    u, _, vt = np.linalg.svd(covariance)
    rotation = vt.T @ u.T
    if np.linalg.det(rotation) < 0:
        vt[-1, :] *= -1
        rotation = vt.T @ u.T
    translation = target_centroid - rotation @ source_centroid
    return transform_payload("rigid_2d", rotation, translation, scale=1.0)


def fit_similarity_transform(
    source_points: np.ndarray, target_points: np.ndarray
) -> dict[str, Any]:
    source_centroid = source_points.mean(axis=0)
    target_centroid = target_points.mean(axis=0)
    source_centered = source_points - source_centroid
    target_centered = target_points - target_centroid
    covariance = source_centered.T @ target_centered
    u, singular_values, vt = np.linalg.svd(covariance)
    rotation = vt.T @ u.T
    if np.linalg.det(rotation) < 0:
        vt[-1, :] *= -1
        rotation = vt.T @ u.T
        singular_values[-1] *= -1
    source_var = float((source_centered**2).sum())
    scale = float(singular_values.sum() / source_var) if source_var > 0 else 1.0
    translation = target_centroid - scale * (rotation @ source_centroid)
    return transform_payload("similarity_2d", rotation, translation, scale=scale)


def fit_affine_transform(source_points: np.ndarray, target_points: np.ndarray) -> dict[str, Any]:
    design = np.column_stack([source_points, np.ones(len(source_points))])
    x_params, *_ = np.linalg.lstsq(design, target_points[:, 0], rcond=None)
    y_params, *_ = np.linalg.lstsq(design, target_points[:, 1], rcond=None)
    matrix = np.array([[x_params[0], x_params[1]], [y_params[0], y_params[1]]], dtype=float)
    translation = np.array([x_params[2], y_params[2]], dtype=float)
    predicted = source_points @ matrix.T + translation
    residual_values = np.linalg.norm(predicted - target_points, axis=1)
    return {
        "transform_type": "affine_2d",
        "diagnostic_only": True,
        "reason": "Affine fit is emitted for diagnosis only and must not verify alignment.",
        "matrix": round_matrix(matrix),
        "translation": round_list(translation),
        **residual_metrics([float(value) for value in residual_values]),
    }


def transform_payload(
    transform_type: str,
    rotation: np.ndarray,
    translation: np.ndarray,
    *,
    scale: float,
) -> dict[str, Any]:
    yaw = math.atan2(float(rotation[1, 0]), float(rotation[0, 0]))
    return {
        "type": transform_type,
        "source": "reviewed_correspondence_fit",
        "source_frame": SOURCE_MAP_FRAME,
        "target_frame": TARGET_SCENE_FRAME,
        "scale": round(float(scale), 9),
        "rotation_matrix": round_matrix(rotation),
        "yaw_rad": round(float(yaw), 9),
        "yaw_deg": round(math.degrees(yaw), 6),
        "translation": round_list(translation),
    }


def select_global_transform(
    candidates: list[dict[str, Any]],
    spatial_errors: list[str],
) -> dict[str, Any]:
    failure_reasons = list(spatial_errors)
    if spatial_errors:
        for candidate in candidates:
            candidate["passes_global_gate"] = False
            candidate["failure_reasons"] = spatial_errors
        return {
            "passed": False,
            "transform_type": "",
            "transform": {},
            "reason": "Global fit failed the spatial coverage gate.",
            "failure_reasons": failure_reasons,
        }
    for candidate in candidates:
        candidate_errors = []
        if not candidate.get("passes_residual_thresholds"):
            candidate_errors.append(
                "residual thresholds failed: "
                f"mean={candidate.get('mean_residual_m')} max={candidate.get('max_residual_m')}"
            )
        candidate["passes_global_gate"] = not candidate_errors
        candidate["failure_reasons"] = candidate_errors
        if not candidate_errors:
            return {
                "passed": True,
                "transform_type": candidate["transform_type"],
                "transform": candidate["transform"],
                "reason": "Selected simplest transform that passed residual thresholds.",
                "failure_reasons": [],
            }
        failure_reasons.extend(candidate_errors)
    return {
        "passed": False,
        "transform_type": "",
        "transform": {},
        "reason": "No rigid or similarity transform passed residual thresholds.",
        "failure_reasons": sorted(set(failure_reasons)),
    }


def spatial_gate_errors(anchors: list[dict[str, Any]], source_points: np.ndarray) -> list[str]:
    errors: list[str] = []
    if len(anchors) < MIN_GLOBAL_ACCEPTED_ANCHORS:
        errors.append("global fit requires at least six accepted anchors")
    if non_collinear_count(source_points) < MIN_GLOBAL_NON_COLLINEAR_ANCHORS:
        errors.append("global fit requires at least four non-collinear anchors")
    return errors


def residual_rows(
    anchors: list[dict[str, Any]],
    transform: dict[str, Any],
    manifest: dict[str, Any],
) -> list[dict[str, Any]]:
    rows = []
    for anchor in anchors:
        map_xy = np.array(anchor["map_xy"], dtype=float)
        scene_xy = np.array(anchor_scene_xy(anchor, manifest), dtype=float)
        predicted = apply_transform_point(map_xy, transform)
        residual = float(np.linalg.norm(predicted - scene_xy))
        rows.append(
            {
                "anchor_id": str(anchor.get("anchor_id") or ""),
                "anchor_type": str(anchor.get("anchor_type") or ""),
                "anchor_role": anchor_role(anchor),
                "navigation_area_id": str(anchor.get("navigation_area_id") or ""),
                "asset_partition_id": str(anchor.get("asset_partition_id") or ""),
                "map_xy": round_list(map_xy),
                "scene_xy": round_list(scene_xy),
                "predicted_scene_xy": round_list(predicted),
                "residual_m": round(float(residual), 6),
                "classification": "inlier" if residual <= GLOBAL_MAX_THRESHOLD_M else "outlier",
                "outlier_reason": ""
                if residual <= GLOBAL_MAX_THRESHOLD_M
                else "residual exceeds global max threshold",
            }
        )
    return rows


def leave_one_out_residuals(
    anchors: list[dict[str, Any]],
    transform_type: str,
    manifest: dict[str, Any],
) -> list[dict[str, Any]]:
    if transform_type not in {"rigid_2d", "similarity_2d"} or len(anchors) <= 3:
        return []
    rows = []
    for index, anchor in enumerate(anchors):
        training = [item for item_index, item in enumerate(anchors) if item_index != index]
        source = np.array([item["map_xy"] for item in training], dtype=float)
        target = np.array([anchor_scene_xy(item, manifest) for item in training], dtype=float)
        transform = (
            fit_rigid_transform(source, target)
            if transform_type == "rigid_2d"
            else fit_similarity_transform(source, target)
        )
        predicted = apply_transform_point(np.array(anchor["map_xy"], dtype=float), transform)
        actual = np.array(anchor_scene_xy(anchor, manifest), dtype=float)
        rows.append(
            {
                "held_out_anchor_id": str(anchor.get("anchor_id") or ""),
                "residual_m": round(float(np.linalg.norm(predicted - actual)), 6),
            }
        )
    return rows


def area_alignment_reports(
    anchors: list[dict[str, Any]],
    *,
    selected_transform: dict[str, Any] | None,
    manifest: dict[str, Any],
) -> list[dict[str, Any]]:
    by_area: dict[str, list[dict[str, Any]]] = {}
    for anchor in anchors:
        if anchor_role(anchor) != SEMANTIC_ANCHOR_ROLE:
            continue
        area_id = str(anchor.get("navigation_area_id") or "")
        if not area_id:
            continue
        by_area.setdefault(area_id, []).append(anchor)
    reports = []
    for area_id, area_anchors in sorted(by_area.items()):
        source = np.array([item["map_xy"] for item in area_anchors], dtype=float)
        if (
            len(area_anchors) >= MIN_AREA_ACCEPTED_ANCHORS
            and non_collinear_count(source) >= MIN_AREA_NON_COLLINEAR_ANCHORS
        ):
            target = np.array(
                [anchor_scene_xy(item, manifest) for item in area_anchors], dtype=float
            )
            local_transform = fit_similarity_transform(source, target)
            residual_values = np.linalg.norm(
                apply_transform_array(source, local_transform) - target, axis=1
            )
            metrics = residual_metrics([float(value) for value in residual_values])
            passed = (
                float(metrics["mean_residual_m"]) <= AREA_MEAN_THRESHOLD_M
                and float(metrics["max_residual_m"]) <= AREA_MAX_THRESHOLD_M
            )
            reports.append(
                {
                    "navigation_area_id": area_id,
                    "alignment_status": "verified" if passed else "candidate",
                    "fit_scope": "independent_area_transform",
                    "matched_anchor_count": len(area_anchors),
                    "non_collinear_anchor_count": non_collinear_count(source),
                    "transform_type": "similarity_2d",
                    "transform": local_transform,
                    **metrics,
                    "thresholds": {
                        "mean_residual_m": AREA_MEAN_THRESHOLD_M,
                        "max_residual_m": AREA_MAX_THRESHOLD_M,
                    },
                }
            )
            continue
        inherited_status = "candidate"
        if selected_transform is not None:
            rows = residual_rows(area_anchors, selected_transform, manifest)
            residual_values = [row["residual_m"] for row in rows]
            metrics = residual_metrics(residual_values)
            inherited_status = (
                "global_verified_inherited"
                if metrics
                and float(metrics["mean_residual_m"]) <= AREA_MEAN_THRESHOLD_M
                and float(metrics["max_residual_m"]) <= AREA_MAX_THRESHOLD_M
                else "candidate"
            )
        else:
            metrics = {}
        reports.append(
            {
                "navigation_area_id": area_id,
                "alignment_status": inherited_status,
                "fit_scope": "inherits_global_transform"
                if selected_transform is not None
                else "insufficient_for_independent_area_transform",
                "matched_anchor_count": len(area_anchors),
                "non_collinear_anchor_count": non_collinear_count(source),
                **metrics,
                "reason": (
                    "Independent area transform requires at least three accepted, "
                    "non-collinear anchors in the area."
                ),
            }
        )
    return reports


def write_alignment_previews(
    anchors: list[dict[str, Any]],
    *,
    selected_transform: dict[str, Any] | None,
    output_dir: Path,
    manifest: dict[str, Any] | None = None,
) -> dict[str, str]:
    preview_dir = output_dir / "previews"
    preview_dir.mkdir(parents=True, exist_ok=True)
    before = preview_dir / "alignment_before.png"
    after = preview_dir / "alignment_after.png"
    draw_alignment_preview(anchors, before, transform=None, manifest=manifest or {})
    draw_alignment_preview(anchors, after, transform=selected_transform, manifest=manifest or {})
    return {
        "before_overlay": str(before),
        "after_overlay": str(after),
        "residual_arrows": str(after),
    }


def draw_alignment_preview(
    anchors: list[dict[str, Any]],
    path: Path,
    *,
    transform: dict[str, Any] | None,
    manifest: dict[str, Any],
) -> None:
    image = Image.new("RGB", (960, 720), color=(255, 255, 255))
    draw = ImageDraw.Draw(image)
    draw.rectangle((40, 40, 920, 680), outline=(210, 215, 222), width=2)
    if not anchors:
        draw.text((60, 60), "No accepted correspondence anchors", fill=(120, 30, 30))
        image.save(path)
        return
    map_points = [np.array(anchor["map_xy"], dtype=float) for anchor in anchors]
    scene_points = [np.array(anchor_scene_xy(anchor, manifest), dtype=float) for anchor in anchors]
    predicted_points = [
        apply_transform_point(point, transform) if transform is not None else point
        for point in map_points
    ]
    all_points = [*scene_points, *predicted_points]
    min_x = min(float(point[0]) for point in all_points)
    max_x = max(float(point[0]) for point in all_points)
    min_y = min(float(point[1]) for point in all_points)
    max_y = max(float(point[1]) for point in all_points)
    span_x = max(max_x - min_x, 1e-6)
    span_y = max(max_y - min_y, 1e-6)

    def canvas(point: np.ndarray) -> tuple[int, int]:
        x = 70 + (float(point[0]) - min_x) / span_x * 820
        y = 650 - (float(point[1]) - min_y) / span_y * 580
        return int(round(x)), int(round(y))

    for anchor, scene_point, predicted in zip(anchors, scene_points, predicted_points, strict=True):
        scene_xy = canvas(scene_point)
        predicted_xy = canvas(predicted)
        draw.line((*predicted_xy, *scene_xy), fill=(198, 81, 2), width=2)
        draw.ellipse(
            (scene_xy[0] - 5, scene_xy[1] - 5, scene_xy[0] + 5, scene_xy[1] + 5),
            fill=(9, 105, 218),
        )
        draw.rectangle(
            (
                predicted_xy[0] - 5,
                predicted_xy[1] - 5,
                predicted_xy[0] + 5,
                predicted_xy[1] + 5,
            ),
            fill=(29, 131, 72),
        )
        draw.text(
            (scene_xy[0] + 7, scene_xy[1] - 7),
            str(anchor.get("anchor_id") or ""),
            fill=(40, 45, 52),
        )
    draw.text(
        (60, 60), "Blue: scene pick. Green: fitted map pick. Orange: residual.", fill=(50, 50, 50)
    )
    image.save(path)


def unavailable_residual_evidence(
    reason: str,
    *,
    matched_anchor_count: int = 0,
) -> dict[str, Any]:
    return {
        "status": "not_available",
        "matched_anchor_count": matched_anchor_count,
        "source": "",
        "transform_source": "",
        "reason": reason,
    }


def anchor_scene_xy(anchor: dict[str, Any], manifest: dict[str, Any]) -> list[float]:
    axes = scene_projection_policy(manifest)["horizontal_axes"]
    values = dict(zip(["x", "y", "z"], anchor["scene_xyz"], strict=True))
    return [float(values[axes[0]]), float(values[axes[1]])]


def apply_transform_point(point: np.ndarray, transform: dict[str, Any]) -> np.ndarray:
    scale = float(transform.get("scale") or 1.0)
    rotation = np.array(transform.get("rotation_matrix") or [[1.0, 0.0], [0.0, 1.0]], dtype=float)
    translation = np.array(transform.get("translation") or [0.0, 0.0], dtype=float)
    return scale * (rotation @ point) + translation


def apply_transform_array(points: np.ndarray, transform: dict[str, Any]) -> np.ndarray:
    return np.array([apply_transform_point(point, transform) for point in points], dtype=float)


def residual_metrics(values: list[float]) -> dict[str, Any]:
    if not values:
        return {}
    ordered = sorted(float(value) for value in values)
    return {
        "mean_residual_m": round(float(sum(ordered) / len(ordered)), 6),
        "median_residual_m": round(percentile(ordered, 50), 6),
        "p90_residual_m": round(percentile(ordered, 90), 6),
        "max_residual_m": round(float(max(ordered)), 6),
    }


def percentile(sorted_values: list[float], percentile_value: float) -> float:
    if not sorted_values:
        return math.nan
    if len(sorted_values) == 1:
        return float(sorted_values[0])
    index = (len(sorted_values) - 1) * (percentile_value / 100.0)
    lower = math.floor(index)
    upper = math.ceil(index)
    if lower == upper:
        return float(sorted_values[int(index)])
    fraction = index - lower
    return float(sorted_values[lower] * (1.0 - fraction) + sorted_values[upper] * fraction)


def non_collinear_count(points: np.ndarray) -> int:
    if len(points) < 3:
        return len(points)
    unique = np.unique(np.round(points, 6), axis=0)
    if len(unique) < 3:
        return len(unique)
    base = unique[0]
    for first in range(1, len(unique) - 1):
        for second in range(first + 1, len(unique)):
            first_vec = unique[first] - base
            second_vec = unique[second] - base
            area = abs(first_vec[0] * second_vec[1] - first_vec[1] * second_vec[0])
            if float(area) > 1e-6:
                return len(unique)
    return 2


def anchor_uses_known_poor_seed(anchor: dict[str, Any]) -> bool:
    sources = [
        anchor.get("coordinate_source"),
        anchor.get("scene_coordinate_source"),
        anchor.get("map_coordinate_source"),
    ]
    evidence = _dict(anchor.get("evidence"))
    sources.extend(
        [
            evidence.get("source"),
            evidence.get("scene_source"),
            evidence.get("map_source"),
        ]
    )
    return any(
        str(source) in {KNOWN_POOR_BBOX_SEED_SOURCE, BBOX_FIT_METHOD}
        for source in sources
        if source is not None
    )


def anchor_role(anchor: dict[str, Any]) -> str:
    return str(anchor.get("anchor_role") or ALIGNMENT_ANCHOR_ROLE)


def valid_xy(value: Any) -> bool:
    return (
        isinstance(value, list)
        and len(value) == 2
        and all(isinstance(item, int | float) and math.isfinite(float(item)) for item in value)
    )


def valid_xyz(value: Any) -> bool:
    return (
        isinstance(value, list)
        and len(value) == 3
        and all(isinstance(item, int | float) and math.isfinite(float(item)) for item in value)
    )


def optional_float(value: Any, *, default: float) -> float:
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return default
    return parsed if math.isfinite(parsed) else default


def round_matrix(matrix: np.ndarray) -> list[list[float]]:
    return [[round(float(value), 9) for value in row] for row in matrix.tolist()]


def round_list(values: Any) -> list[float]:
    return [round(float(value), 6) for value in list(values)]


def _dict(value: Any) -> dict[str, Any]:
    return dict(value) if isinstance(value, dict) else {}


def _require(condition: bool, message: str, errors: list[str]) -> None:
    if not condition:
        errors.append(message)


if __name__ == "__main__":
    raise SystemExit(main())
