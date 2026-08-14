from __future__ import annotations

import math
from typing import Any

import numpy as np

from roboclaws.maps.b1_alignment_contract import (
    AREA_MAX_THRESHOLD_M,
    AREA_MEAN_THRESHOLD_M,
    GLOBAL_MAX_THRESHOLD_M,
    GLOBAL_MEAN_THRESHOLD_M,
    MIN_AREA_ACCEPTED_ANCHORS,
    MIN_AREA_NON_COLLINEAR_ANCHORS,
    MIN_GLOBAL_ACCEPTED_ANCHORS,
    MIN_GLOBAL_NON_COLLINEAR_ANCHORS,
    SEMANTIC_ANCHOR_ROLE,
    SOURCE_MAP_FRAME,
    TARGET_SCENE_FRAME,
    anchor_role,
    scene_projection_policy,
)


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


def round_matrix(matrix: np.ndarray) -> list[list[float]]:
    return [[round(float(value), 9) for value in row] for row in matrix.tolist()]


def round_list(values: Any) -> list[float]:
    return [round(float(value), 6) for value in list(values)]


def _dict(value: Any) -> dict[str, Any]:
    return dict(value) if isinstance(value, dict) else {}
