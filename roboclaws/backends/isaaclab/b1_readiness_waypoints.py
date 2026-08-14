from __future__ import annotations

import math
from pathlib import Path
from typing import Any

from roboclaws.backends.isaaclab.b1_readiness_validation import SEMANTIC_SOURCE


def residual_backed_candidate_waypoints(
    readiness: dict[str, Any],
    *,
    selected_transform: dict[str, Any],
    alignment_artifact_path: Path | None,
) -> list[dict[str, Any]]:
    if str(selected_transform.get("source") or "") != "reviewed_correspondence_fit":
        return []
    map12 = _dict(readiness.get("map12"))
    anchors = [
        anchor
        for anchor in map12.get("anchors") or []
        if isinstance(anchor, dict) and _has_xy(_dict(anchor.get("nav_goal")))
    ]
    waypoints = []
    for anchor in anchors[: min(4, len(anchors))]:
        waypoint = residual_backed_waypoint_from_nav_goal(
            nav_goal=_dict(anchor.get("nav_goal")),
            waypoint_id=f"b1_aligned_{anchor['id']}",
            label=str(anchor.get("label") or anchor["id"]),
            source_anchor_id=str(anchor["id"]),
            transform=selected_transform,
            alignment_artifact_path=alignment_artifact_path,
        )
        if waypoint:
            waypoints.append(waypoint)
    return waypoints


def residual_backed_waypoint_from_nav_goal(
    nav_goal: dict[str, Any],
    *,
    waypoint_id: str,
    label: str = "",
    source_anchor_id: str = "",
    transform: dict[str, Any],
    alignment_artifact_path: Path | None,
    coverage_decision: dict[str, Any] | None = None,
) -> dict[str, Any]:
    if not _has_xy(nav_goal):
        return {}
    if str(transform.get("source") or "") != "reviewed_correspondence_fit":
        raise ValueError("Map12 waypoint conversion requires reviewed_correspondence_fit")
    yaw = _optional_float(nav_goal.get("yaw"))
    yaw_deg = (
        math.degrees(yaw) if yaw is not None else _optional_float(nav_goal.get("yaw_deg")) or 0.0
    )
    scene_xy = _apply_reviewed_scene_transform(
        [float(nav_goal["x"]), float(nav_goal["y"])], transform
    )
    return {
        "waypoint_id": waypoint_id,
        "source_anchor_id": source_anchor_id,
        "label": label or waypoint_id,
        "semantic_source": SEMANTIC_SOURCE,
        "alignment_artifact": str(alignment_artifact_path) if alignment_artifact_path else "",
        "alignment_transform_source": "reviewed_correspondence_fit",
        "selected_transform_type": str(transform.get("type") or ""),
        "coverage_decision": dict(
            coverage_decision
            or {
                "status": "verified_global",
                "fit_scope": "global_transform",
            }
        ),
        "map12_nav_goal": nav_goal,
        "b1_pose": {
            "frame": str(transform.get("target_frame") or "b1_rebuilt_scene_usd_world"),
            "x": round(scene_xy[0], 6),
            "y": round(scene_xy[1], 6),
            "z": 0.0,
            "yaw_deg": round(float(yaw_deg) + float(transform.get("yaw_deg") or 0.0), 6),
            "pose_source": "reviewed_correspondence_fit",
        },
        "request_status": "pose_request_only",
        "planner_backed": False,
        "physical_robot": False,
    }


def _apply_reviewed_scene_transform(point: list[float], transform: dict[str, Any]) -> list[float]:
    scale = float(transform.get("scale") or 1.0)
    rotation = transform.get("rotation_matrix")
    if not (
        isinstance(rotation, list)
        and len(rotation) == 2
        and all(isinstance(row, list) and len(row) == 2 for row in rotation)
    ):
        rotation = [[1.0, 0.0], [0.0, 1.0]]
    translation = transform.get("translation")
    if not isinstance(translation, list) or len(translation) != 2:
        translation = [0.0, 0.0]
    x = scale * (float(rotation[0][0]) * point[0] + float(rotation[0][1]) * point[1]) + float(
        translation[0]
    )
    y = scale * (float(rotation[1][0]) * point[0] + float(rotation[1][1]) * point[1]) + float(
        translation[1]
    )
    return [x, y]


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
