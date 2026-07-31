from __future__ import annotations

import math
from pathlib import Path
from typing import Any

from PIL import Image, ImageStat

READINESS_SCHEMA = "b1_map12_digital_twin_readiness_v1"
NAVIGATION_SMOKE_SCHEMA = "b1_map12_navigation_smoke_v1"
ALIGNMENT_RESIDUALS_SCHEMA = "b1_map12_scene_alignment_residuals_v1"
WAYPOINT_POSE_REQUESTS_SCHEMA = "b1_map12_waypoint_pose_requests_v1"
SEMANTIC_SOURCE = "robot_map_12_navigation_memory_overlay"
SEMANTIC_USD_BLOCKED = "blocked_until_segmentation_or_manifest"
NAVIGATION_PROVENANCE = "isaac_b1_map12_navigation_smoke"
KNOWN_POOR_BBOX_SEED_POLICY = "known_poor_seed_only"
KNOWN_POOR_BBOX_SEED_SOURCE = "known_poor_bbox_seed"
DEFAULT_B1_VISUAL_ROUTE_SCENE_USD = Path(
    "data/robot-data-lab/scene-engine/data/B1_floor2_slow/usda/F2_all/default.usda"
)
MIN_REVIEWABLE_IMAGE_STDDEV = 5.0
MIN_REVIEWABLE_IMAGE_COLOR_COUNT = 128


def validate_readiness_artifact(
    payload: dict[str, Any],
    *,
    require_navigation_success: bool = False,
) -> list[str]:
    errors: list[str] = []
    _require(payload.get("schema") == READINESS_SCHEMA, "unexpected readiness schema", errors)
    _require(payload.get("b1_geometry_loaded") is True, "B1 geometry is not loaded", errors)
    _require(
        payload.get("usd_object_index_ready") is False,
        "B1 USD object index must remain false until segmentation or manifest exists",
        errors,
    )
    _require(
        payload.get("usd_receptacle_index_ready") is False,
        "B1 USD receptacle index must remain false until segmentation or manifest exists",
        errors,
    )
    _require(
        payload.get("semantic_source") == SEMANTIC_SOURCE,
        "semantic source must be Map 12 navigation-memory overlay",
        errors,
    )
    _require(
        payload.get("semantic_usd_binding_status") == SEMANTIC_USD_BLOCKED,
        "semantic USD binding must remain blocked",
        errors,
    )
    _require(
        payload.get("semantic_anchors_are_usd_truth") is False,
        "semantic anchors must not be presented as USD prim truth",
        errors,
    )
    _require(
        payload.get("manipulation_supported") is False,
        "manipulation must not be presented as supported",
        errors,
    )
    _require(
        payload.get("map12_overlay_status") in {"candidate", "verified", "blocked"},
        "overlay status must be candidate, verified, or blocked",
        errors,
    )
    _require(
        payload.get("map12_to_b1_usd_transform_status")
        in {"unverified", "verified", "blocked", "area_verified_only"},
        "map-scene transform status must be unverified, verified, blocked, or area_verified_only",
        errors,
    )
    map12_overlay = _dict(payload.get("map12_overlay"))
    if map12_overlay:
        _require(
            map12_overlay.get("bbox_seed_policy") == KNOWN_POOR_BBOX_SEED_POLICY,
            "bbox seed must be labeled known_poor_seed_only",
            errors,
        )
        transform = _dict(map12_overlay.get("transform"))
        if transform:
            _require(
                transform.get("source") == KNOWN_POOR_BBOX_SEED_SOURCE,
                "bbox-fit transform must be labeled known_poor_bbox_seed",
                errors,
            )
    if payload.get("map12_overlay_status") == "verified":
        residual = _dict(payload.get("residual_evidence"))
        _require(
            residual.get("status") == "available",
            "verified overlay requires residual evidence",
            errors,
        )
        _require(
            int(residual.get("matched_anchor_count") or 0) >= 6,
            "verified overlay requires at least six matched anchors",
            errors,
        )
        _require(
            residual.get("transform_source") != KNOWN_POOR_BBOX_SEED_SOURCE,
            "verified overlay must not use known-poor bbox seed",
            errors,
        )
        verified_transform = _dict(map12_overlay.get("verified_transform"))
        _require(
            verified_transform.get("source") != KNOWN_POOR_BBOX_SEED_SOURCE
            and verified_transform.get("method")
            != "bbox_fit_navigation_memory_nav_goals_to_scene_usd_bounds",
            "verified overlay cannot use the bbox-fit transform as its verified transform",
            errors,
        )
    if payload.get("map12_to_b1_usd_transform_status") == "area_verified_only":
        area_rows = [item for item in payload.get("area_alignment") or [] if isinstance(item, dict)]
        _require(
            any(item.get("alignment_status") == "verified" for item in area_rows),
            "area_verified_only requires at least one verified area alignment",
            errors,
        )
    if payload.get("static_precheck_only") is True:
        _require(
            payload.get("robot_navigation_supported") is not True,
            "static-only readiness must not claim robot navigation support",
            errors,
        )
    if payload.get("robot_navigation_supported") is True:
        _require(
            payload.get("robot_navigation_provenance") == NAVIGATION_PROVENANCE,
            "navigation support requires B1 navigation-smoke provenance",
            errors,
        )
        _require(
            int(payload.get("navigation_waypoint_count") or 0) >= 2,
            "navigation support requires at least two waypoints",
            errors,
        )
        _require(
            payload.get("robot_view_evidence_status") == "available",
            "navigation support requires robot-view evidence",
            errors,
        )
    elif require_navigation_success:
        errors.append("robot_navigation_supported is not true")
    return errors


def validate_alignment_residual_artifact(payload: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    _require(
        payload.get("schema") == ALIGNMENT_RESIDUALS_SCHEMA,
        "unexpected alignment residual schema",
        errors,
    )
    _require(
        payload.get("bbox_seed_policy") == KNOWN_POOR_BBOX_SEED_POLICY,
        "alignment artifact must label bbox seed as known_poor_seed_only",
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
    selected_transform = _dict(payload.get("selected_transform"))
    if payload.get("global_alignment_status") == "verified":
        _require(
            residual.get("status") == "available",
            "verified alignment requires available residual evidence",
            errors,
        )
        _require(
            int(residual.get("matched_anchor_count") or 0) >= 6,
            "verified alignment requires at least six matched anchors",
            errors,
        )
        _require(
            residual.get("transform_source") != KNOWN_POOR_BBOX_SEED_SOURCE,
            "verified alignment must not use known-poor bbox seed",
            errors,
        )
        _require(
            selected_transform.get("source") != KNOWN_POOR_BBOX_SEED_SOURCE
            and selected_transform.get("method")
            != "bbox_fit_navigation_memory_nav_goals_to_scene_usd_bounds",
            "verified alignment transform must not come from bbox-fit seed",
            errors,
        )
    for area in payload.get("area_alignment") or []:
        if not isinstance(area, dict) or area.get("alignment_status") != "verified":
            continue
        _require(
            int(area.get("matched_anchor_count") or 0) >= 3,
            "verified area alignment requires at least three accepted anchors",
            errors,
        )
    return errors


def validate_navigation_smoke_artifact(
    payload: dict[str, Any],
    *,
    require_files: bool = False,
) -> list[str]:
    errors: list[str] = []
    _require(
        payload.get("schema") == NAVIGATION_SMOKE_SCHEMA,
        "unexpected navigation schema",
        errors,
    )
    _require(payload.get("status") == "passed", "navigation smoke did not pass", errors)
    _require(
        payload.get("robot_navigation_supported") is True,
        "navigation artifact must claim robot_navigation_supported=true only on pass",
        errors,
    )
    _require(
        payload.get("robot_navigation_provenance") == NAVIGATION_PROVENANCE,
        "navigation artifact provenance must be isaac_b1_map12_navigation_smoke",
        errors,
    )
    _require(
        payload.get("navigation_provenance") in {"kinematic_pose_driven", "planner_backed"},
        "navigation artifact must state kinematic or planner-backed provenance",
        errors,
    )
    _require(
        bool(payload.get("alignment_artifact")),
        "navigation artifact requires residual-backed alignment artifact provenance",
        errors,
    )
    _require(
        str(payload.get("b1_scene_usd") or "") == str(DEFAULT_B1_VISUAL_ROUTE_SCENE_USD),
        "navigation artifact must render the verified B1_floor2_slow visual route",
        errors,
    )
    _require(
        str(payload.get("alignment_transform_source") or "") == "reviewed_correspondence_fit",
        "navigation artifact requires reviewed correspondence transform source",
        errors,
    )
    _require(
        payload.get("planner_backed") in {True, False},
        "planner_backed must be explicit",
        errors,
    )
    _require(
        payload.get("semantic_source") == SEMANTIC_SOURCE,
        "navigation semantic source must remain Map 12 overlay",
        errors,
    )
    _require(
        payload.get("semantic_usd_binding_status") == SEMANTIC_USD_BLOCKED,
        "navigation artifact must not claim semantic USD binding",
        errors,
    )
    _require(
        payload.get("manipulation_supported") is False,
        "navigation artifact must not claim manipulation support",
        errors,
    )
    waypoints = [item for item in payload.get("waypoint_evidence") or [] if isinstance(item, dict)]
    _require(
        len(waypoints) >= 2,
        "navigation artifact needs at least two waypoint evidence rows",
        errors,
    )
    _require(
        int(payload.get("navigation_waypoint_count") or 0) >= 2,
        "navigation waypoint count must be at least two",
        errors,
    )
    errors.extend(
        validate_robot_view_waypoint_evidence(
            waypoints,
            require_files=require_files,
            expected_scene_usd=DEFAULT_B1_VISUAL_ROUTE_SCENE_USD,
            expected_scene_usd_label="B1_floor2_slow visual route",
            required_views=("fpv",),
            reviewable_views=("fpv", "chase"),
            require_distinct_robot_poses=True,
            distinct_pose_error="navigation waypoint robot poses must be distinct",
        )
    )
    return errors


def validate_robot_view_waypoint_evidence(
    waypoints: list[dict[str, Any]],
    *,
    require_files: bool = False,
    expected_scene_usd: Path | str | None = None,
    expected_scene_usd_label: str = "",
    required_views: tuple[str, ...] = ("fpv",),
    reviewable_views: tuple[str, ...] = ("fpv", "chase"),
    require_distinct_robot_poses: bool = False,
    distinct_pose_error: str = "waypoint robot poses must be distinct",
) -> list[str]:
    errors: list[str] = []
    if require_distinct_robot_poses:
        pose_keys = {
            (
                round(float(_dict(item.get("robot_pose")).get("x") or 0.0), 3),
                round(float(_dict(item.get("robot_pose")).get("y") or 0.0), 3),
            )
            for item in waypoints
        }
        _require(len(pose_keys) >= 2, distinct_pose_error, errors)
    for index, item in enumerate(waypoints, start=1):
        views = _dict(item.get("views"))
        _require(
            item.get("robot_pose_applied") is True,
            f"waypoint {index} robot pose must be applied in Isaac",
            errors,
        )
        _require(
            bool(item.get("alignment_artifact")),
            f"waypoint {index} missing alignment artifact provenance",
            errors,
        )
        _require(
            str(item.get("alignment_transform_source") or "") == "reviewed_correspondence_fit",
            f"waypoint {index} requires reviewed correspondence transform source",
            errors,
        )
        if expected_scene_usd is not None:
            _require(
                str(item.get("scene_usd") or "") == str(expected_scene_usd),
                f"waypoint {index} must render {expected_scene_usd_label or expected_scene_usd}",
                errors,
            )
        for view_name in required_views:
            _require(
                bool(views.get(view_name)),
                f"waypoint {index} missing {view_name.upper()} image",
                errors,
            )
        if require_files:
            for view_name, raw_path in views.items():
                if not raw_path:
                    continue
                path = Path(str(raw_path))
                exists = path.is_file()
                _require(
                    exists,
                    f"waypoint {index} view {view_name} missing: {path}",
                    errors,
                )
                if exists and view_name in set(reviewable_views):
                    errors.extend(
                        f"waypoint {index} {view_name}: {error}"
                        for error in reviewable_image_errors(path)
                    )
    return errors


def validate_waypoint_pose_requests_artifact(payload: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    _require(
        payload.get("schema") == WAYPOINT_POSE_REQUESTS_SCHEMA,
        "unexpected waypoint pose request schema",
        errors,
    )
    _require(
        payload.get("status") in {"ready", "blocked"},
        "waypoint pose request status must be ready or blocked",
        errors,
    )
    _require(
        payload.get("semantic_source") == SEMANTIC_SOURCE,
        "waypoint pose request semantic source must remain Map 12 overlay",
        errors,
    )
    _require(
        payload.get("alignment_transform_source") in {"reviewed_correspondence_fit", ""},
        "waypoint pose requests require reviewed correspondence transform",
        errors,
    )
    _require(
        payload.get("planner_backed") is False,
        "waypoint pose requests must not claim planner-backed navigation",
        errors,
    )
    _require(
        payload.get("physical_robot") is False,
        "waypoint pose requests must not claim physical robot navigation",
        errors,
    )
    _require(
        payload.get("robot_navigation_supported") is False,
        "waypoint pose requests are pose conversion artifacts, not navigation proof",
        errors,
    )
    waypoints = [item for item in payload.get("waypoints") or [] if isinstance(item, dict)]
    blocked = [item for item in payload.get("blocked_requests") or [] if isinstance(item, dict)]
    _require(
        int(payload.get("waypoint_count") or 0) == len(waypoints),
        "waypoint_count must match ready waypoint rows",
        errors,
    )
    _require(
        int(payload.get("blocked_request_count") or 0) == len(blocked),
        "blocked_request_count must match blocked request rows",
        errors,
    )
    if payload.get("status") == "ready":
        _require(
            bool(payload.get("alignment_artifact")),
            "ready requests need alignment artifact",
            errors,
        )
        _require(len(waypoints) >= 1, "ready requests need at least one waypoint", errors)
        _require(not blocked, "ready requests must not contain blocked rows", errors)
    else:
        _require(
            bool(blocked) or bool(payload.get("artifact_errors")),
            "blocked requests need blocked rows or artifact errors",
            errors,
        )
    for index, item in enumerate(waypoints, start=1):
        coverage = _dict(item.get("coverage_decision"))
        _require(bool(item.get("waypoint_id")), f"waypoint {index} missing waypoint_id", errors)
        _require(
            str(item.get("alignment_transform_source") or "") == "reviewed_correspondence_fit",
            f"waypoint {index} requires reviewed correspondence transform source",
            errors,
        )
        _require(
            bool(item.get("alignment_artifact")),
            f"waypoint {index} missing alignment artifact",
            errors,
        )
        _require(
            isinstance(item.get("map12_nav_goal"), dict)
            and _has_xy(_dict(item.get("map12_nav_goal"))),
            f"waypoint {index} missing Map12 x/y nav goal",
            errors,
        )
        _require(
            isinstance(item.get("b1_pose"), dict),
            f"waypoint {index} missing B1 scene pose",
            errors,
        )
        _require(
            coverage.get("status") in {"verified_global", "verified_local_area"},
            f"waypoint {index} missing verified coverage decision",
            errors,
        )
        _require(
            item.get("planner_backed") is False and item.get("physical_robot") is False,
            f"waypoint {index} must not claim planner-backed or physical navigation",
            errors,
        )
    for index, item in enumerate(blocked, start=1):
        _require(bool(item.get("reason")), f"blocked request {index} missing reason", errors)
        _require(
            item.get("request_status") == "blocked",
            f"blocked request {index} must have request_status=blocked",
            errors,
        )
    return errors


def reviewable_image_errors(path: Path) -> list[str]:
    try:
        with Image.open(path) as image:
            image.verify()
        with Image.open(path) as image:
            rgb = image.convert("RGB")
            stat = ImageStat.Stat(rgb)
            extrema = rgb.getextrema()
            colors = rgb.getcolors(maxcolors=1_000_000)
    except Exception as exc:
        return [f"image is unreadable: {exc}"]
    errors: list[str] = []
    if all(high <= low for low, high in extrema):
        errors.append("image appears blank")
    if max(stat.stddev or [0.0]) < MIN_REVIEWABLE_IMAGE_STDDEV:
        errors.append("image has too little visual detail")
    if colors is not None and len(colors) < MIN_REVIEWABLE_IMAGE_COLOR_COUNT:
        errors.append("image has too few distinct colors")
    return errors


def _finite_reasonable_bounds(min_point: list[float], max_point: list[float]) -> bool:
    values = [*min_point, *max_point]
    if any(not math.isfinite(value) or abs(value) > 1e20 for value in values):
        return False
    return all(max_v >= min_v for min_v, max_v in zip(min_point, max_point, strict=True))


def _float_or_nan(value: Any) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return math.nan


def _optional_float(value: Any) -> float | None:
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return None
    return parsed if math.isfinite(parsed) else None


def _has_xy(value: dict[str, Any]) -> bool:
    return (
        _optional_float(value.get("x")) is not None and _optional_float(value.get("y")) is not None
    )


def _dict(value: Any) -> dict[str, Any]:
    return dict(value) if isinstance(value, dict) else {}


def _require(condition: bool, message: str, errors: list[str]) -> None:
    if not condition:
        errors.append(message)
