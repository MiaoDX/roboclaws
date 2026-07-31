from __future__ import annotations

import math
from typing import Any

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


def _dict(value: Any) -> dict[str, Any]:
    return dict(value) if isinstance(value, dict) else {}


def _require(condition: bool, message: str, errors: list[str]) -> None:
    if not condition:
        errors.append(message)
