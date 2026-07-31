"""Shared scene-preview metadata, image, and geometry helpers."""

from __future__ import annotations

import datetime as dt
import math
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from PIL import Image, ImageFilter, ImageStat

from roboclaws.household.camera_control import canonical_scene_camera_control_request
from roboclaws.household.household_runtime_contract import HouseholdRuntimeContract
from roboclaws.household.subprocess_backend import MolmoSpacesSubprocessBackend
from roboclaws.launch.worlds import MOLMOSPACES_CONSOLE_WORLD_IDS, world_spec
from roboclaws.maps.preview import (
    BASE_MAP_SOURCE_FAMILY,
    BASE_METRIC_MAP_PREVIEW_ROLE,
    SCENE_RENDER_SOURCE_FAMILY,
    TOPDOWN_SCENE_RENDER_ROLE,
)
from roboclaws.operator_console.scene_preview_contract import (
    B1_MAP12_WORLD_ID,
    DEFAULT_HEIGHT,
    DEFAULT_WIDTH,
    PREVIEW_METADATA_SCHEMA,
)


@dataclass(frozen=True)
class PreviewSceneRef:
    scene_source: str
    scene_index: int


def _preview_metadata(
    *,
    world_id: str,
    scene_source: str,
    scene_index: int,
    seed: int,
    width: int,
    height: int,
    map_bundle_dir: Path | None = None,
    waypoint: dict[str, Any],
    navigation: dict[str, Any],
    robot_views: dict[str, Any],
    topdown_result: dict[str, Any],
    topdown_request: dict[str, Any],
    fpv_path: Path,
    map_path: Path,
    chase_path: Path,
    chase_waypoint: dict[str, Any],
    chase_navigation: dict[str, Any],
    chase_robot_views: dict[str, Any],
    chase_selection: dict[str, Any],
    topdown_path: Path,
    scene_alignment: dict[str, Any],
) -> dict[str, Any]:
    topdown_view = next(
        (
            item
            for item in topdown_result.get("views") or []
            if item.get("view_id") == "topdown_scene"
        ),
        {},
    )
    return {
        "schema": PREVIEW_METADATA_SCHEMA,
        "generated_at": _utc_timestamp(),
        "world_id": world_id,
        "backend": "mujoco",
        "renderer": "molmospaces_subprocess_mujoco",
        "scene_source": scene_source,
        "scene_index": scene_index,
        "map_bundle_dir": str(map_bundle_dir) if map_bundle_dir is not None else "",
        "seed": seed,
        "render_resolution": {"width": width, "height": height},
        "views": {
            "fpv": {
                "path": fpv_path.name,
                "view": "raw_fpv",
                "waypoint_id": str(waypoint.get("waypoint_id") or ""),
                "camera": "robot_0/head_camera",
                "provenance": "mujoco_robot_head_camera_first_public_waypoint",
                "navigation_status": navigation.get("status") or "ok",
                "image_diagnostics": _image_diagnostics(fpv_path),
                "camera_diagnostics": (robot_views.get("camera_diagnostics") or {})
                .get("views", {})
                .get("fpv", {}),
            },
            "map": {
                "path": map_path.name,
                "view": BASE_METRIC_MAP_PREVIEW_ROLE,
                "visual_role": BASE_METRIC_MAP_PREVIEW_ROLE,
                "artifact_source_family": BASE_MAP_SOURCE_FAMILY,
                "provenance": "map_bundle_preview_png",
                "alignment_status": "source_map_frame_preview",
                "image_diagnostics": _image_diagnostics(map_path),
            },
            "chase": {
                "path": chase_path.name,
                "view": "chase_camera",
                "waypoint_id": str(chase_waypoint.get("waypoint_id") or ""),
                "camera": "robot_0/camera_follower",
                "provenance": "mujoco_robot_camera_follower_public_waypoint",
                "navigation_status": chase_navigation.get("status") or "ok",
                "selection_policy": "first_reviewable_public_waypoint_fallback_to_first",
                "selection_status": chase_selection.get("status"),
                "candidate_count_evaluated": chase_selection.get("candidate_count_evaluated"),
                "image_diagnostics": _image_diagnostics(chase_path),
                "camera_diagnostics": (chase_robot_views.get("camera_diagnostics") or {})
                .get("views", {})
                .get("chase", {}),
            },
            "topdown": {
                "path": topdown_path.name,
                "view": TOPDOWN_SCENE_RENDER_ROLE,
                "visual_role": TOPDOWN_SCENE_RENDER_ROLE,
                "artifact_source_family": SCENE_RENDER_SOURCE_FAMILY,
                "waypoint_id": str(waypoint.get("waypoint_id") or ""),
                "camera_model": topdown_request.get("camera_model"),
                "camera_pose": {
                    "eye": topdown_view.get("eye"),
                    "target": topdown_view.get("target"),
                    "azimuth": topdown_view.get("azimuth"),
                    "elevation": topdown_view.get("elevation"),
                    "distance": topdown_view.get("distance"),
                },
                "provenance": "mujoco_camera_control_canonical_eye_target",
                "alignment_status": "mujoco_scene_rendered",
                "scene_alignment": scene_alignment,
                "image_diagnostics": _image_diagnostics(topdown_path),
            },
        },
    }


def _select_chase_preview(
    *,
    contract: HouseholdRuntimeContract,
    backend: MolmoSpacesSubprocessBackend,
    run_dir: Path,
    width: int,
    height: int,
    first_waypoint: dict[str, Any],
    first_navigation: dict[str, Any],
    first_robot_views: dict[str, Any],
    first_chase_path: Path,
    candidate_waypoints: list[dict[str, Any]],
) -> dict[str, Any]:
    first_diagnostics = _image_diagnostics(first_chase_path)
    if first_diagnostics["visual_status"] == "reviewable":
        return {
            "status": "first_waypoint_reviewable",
            "path": first_chase_path,
            "waypoint": first_waypoint,
            "navigation": first_navigation,
            "robot_views": first_robot_views,
            "candidate_count_evaluated": 1,
        }

    candidate_count = 1
    for index, waypoint in enumerate(candidate_waypoints, start=2):
        waypoint_id = str(waypoint.get("waypoint_id") or "")
        if not waypoint_id:
            continue
        navigation = contract.navigate_to_waypoint(waypoint_id)
        candidate_count += 1
        if not navigation.get("ok"):
            continue
        robot_views = backend.write_robot_views_with_resolution(
            run_dir / "robot_views",
            label=f"preview_chase_candidate_{index:02d}",
            width=width,
            height=height,
        )
        chase_path = Path(str((robot_views.get("views") or {}).get("chase") or ""))
        if not chase_path.is_file():
            continue
        if _image_diagnostics(chase_path)["visual_status"] != "reviewable":
            continue
        return {
            "status": "alternate_waypoint_reviewable",
            "path": chase_path,
            "waypoint": dict(waypoint),
            "navigation": navigation,
            "robot_views": robot_views,
            "candidate_count_evaluated": candidate_count,
        }

    return {
        "status": "fallback_first_waypoint_low_detail",
        "path": first_chase_path,
        "waypoint": first_waypoint,
        "navigation": first_navigation,
        "robot_views": first_robot_views,
        "candidate_count_evaluated": candidate_count,
    }


def _fit_preview_image(image: Image.Image, *, width: int, height: int) -> Image.Image:
    source = image.convert("RGB")
    source.thumbnail((width, height), Image.Resampling.LANCZOS)
    canvas = Image.new("RGB", (width, height), (228, 231, 235))
    x = (width - source.width) // 2
    y = (height - source.height) // 2
    canvas.paste(source, (x, y))
    return canvas


def _topdown_camera_request(
    state: dict[str, Any],
    *,
    width: int,
    height: int,
    alignment: dict[str, Any] | None = None,
) -> dict[str, Any]:
    alignment = alignment or _scene_alignment(state, width=width, height=height)
    center = alignment["center"]
    vertical_fov_deg = 45.0
    camera_distance = (
        float(alignment["span_y_m"]) / (2.0 * math.tan(math.radians(vertical_fov_deg / 2.0))) * 1.04
    )
    camera_height = float(center[2]) + max(1.0, camera_distance)
    return canonical_scene_camera_control_request(
        [
            {
                "view_id": "topdown_scene",
                "label": "Top-down Scene View",
                "camera_basis": "whole_scene_true_topdown_aligned_to_scene_bounds",
                "eye": [center[0], center[1], camera_height],
                "target": center,
                "azimuth": 90.0,
                "scene_alignment": alignment,
                "calibration_status": "mujoco_scene_rendered",
            }
        ],
        lens={"vertical_fov_deg": vertical_fov_deg, "focal_length_mm": 24.0},
        width=width,
        height=height,
    )


def _scene_alignment(state: dict[str, Any], *, width: int, height: int) -> dict[str, Any]:
    points = _scene_points(state)
    if not points:
        min_x = min_y = -0.5
        max_x = max_y = 0.5
    else:
        xs = [point[0] for point in points]
        ys = [point[1] for point in points]
        min_x, max_x = min(xs), max(xs)
        min_y, max_y = min(ys), max(ys)
    pad = 0.35
    min_x -= pad
    max_x += pad
    min_y -= pad
    max_y += pad
    span_x = max(max_x - min_x, 1.0)
    span_y = max(max_y - min_y, 1.0)
    target_aspect = max(float(width) / max(float(height), 1.0), 0.001)
    current_aspect = span_x / span_y
    if current_aspect < target_aspect:
        expanded_span_x = span_y * target_aspect
        extra = (expanded_span_x - span_x) / 2.0
        min_x -= extra
        max_x += extra
        span_x = expanded_span_x
    elif current_aspect > target_aspect:
        expanded_span_y = span_x / target_aspect
        extra = (expanded_span_y - span_y) / 2.0
        min_y -= extra
        max_y += extra
        span_y = expanded_span_y
    center = [(min_x + max_x) / 2.0, (min_y + max_y) / 2.0, 0.4]
    return {
        "schema": "operator_console_scene_alignment_v1",
        "bounds": {
            "min_x": round(min_x, 6),
            "max_x": round(max_x, 6),
            "min_y": round(min_y, 6),
            "max_y": round(max_y, 6),
        },
        "center": [round(float(value), 6) for value in center],
        "span_x_m": round(float(span_x), 6),
        "span_y_m": round(float(span_y), 6),
        "camera_span_m": round(float(max(span_x, span_y)), 6),
        "screen_coordinate_convention": "screen_x_world_positive_x_screen_y_world_negative_y",
        "topdown_azimuth_deg": 90.0,
    }


def _scene_points(state: dict[str, Any]) -> list[tuple[float, float]]:
    points: list[tuple[float, float]] = []
    for outline in state.get("room_outlines") or []:
        if not isinstance(outline, dict):
            continue
        center = outline.get("center")
        half_extents = outline.get("half_extents")
        if not _is_vec(center, 2) or not _is_vec(half_extents, 2):
            continue
        points.append(
            (
                float(center[0]) - float(half_extents[0]),
                float(center[1]) - float(half_extents[1]),
            )
        )
        points.append(
            (
                float(center[0]) + float(half_extents[0]),
                float(center[1]) + float(half_extents[1]),
            )
        )
    for collection_key in ("objects", "receptacles"):
        collection = state.get(collection_key)
        if not isinstance(collection, dict):
            continue
        for item in collection.values():
            if not isinstance(item, dict) or not _is_vec(item.get("position"), 2):
                continue
            position = item["position"]
            points.append((float(position[0]), float(position[1])))
    for pose in state.get("robot_trajectory") or []:
        if not isinstance(pose, dict) or "x" not in pose or "y" not in pose:
            continue
        points.append((float(pose["x"]), float(pose["y"])))
    return points


def _scene_center_and_span(state: dict[str, Any]) -> tuple[list[float], float]:
    alignment = _scene_alignment(state, width=DEFAULT_WIDTH, height=DEFAULT_HEIGHT)
    return list(alignment["center"]), float(alignment["camera_span_m"])


def _first_public_waypoint(metric_map: dict[str, Any]) -> dict[str, Any]:
    waypoints = _public_waypoints(metric_map)
    if not waypoints:
        raise ValueError("metric map does not include public inspection waypoints")
    first = waypoints[0]
    if not first.get("waypoint_id"):
        raise ValueError("first public inspection waypoint is invalid")
    return first


def _public_waypoints(metric_map: dict[str, Any]) -> list[dict[str, Any]]:
    waypoints = metric_map.get("inspection_waypoints")
    if not isinstance(waypoints, list):
        return []
    return [
        dict(item)
        for item in waypoints
        if isinstance(item, dict) and str(item.get("waypoint_id") or "")
    ]


def _selected_world_ids(raw_world_ids: list[str]) -> tuple[str, ...]:
    return tuple(raw_world_ids or (*MOLMOSPACES_CONSOLE_WORLD_IDS, B1_MAP12_WORLD_ID))


def _molmospaces_scene_index(world_id: str) -> int:
    return _molmospaces_scene_ref(world_id).scene_index


def _molmospaces_scene_ref(world_id: str) -> PreviewSceneRef:
    spec = world_spec(world_id)
    metadata = dict(spec.sampler_metadata)
    return PreviewSceneRef(
        scene_source=str(spec.scene_source),
        scene_index=int(metadata["scene_index"]),
    )


def _world_slug(world_id: str) -> str:
    return world_id.replace("/", "-")


def _is_vec(value: Any, min_length: int) -> bool:
    return isinstance(value, (list, tuple)) and len(value) >= min_length


def _image_diagnostics(path: Path) -> dict[str, Any]:
    with Image.open(path) as image:
        rgb = image.convert("RGB")
        stat = ImageStat.Stat(rgb)
        extrema = rgb.getextrema()
        thumbnail = rgb.resize((160, 100))
        thumbnail_colors = thumbnail.getcolors(maxcolors=16_000)
        edges = rgb.convert("L").filter(ImageFilter.FIND_EDGES).resize((160, 100))
        edge_values = list(edges.getdata())
    channel_ranges = [float(high) - float(low) for low, high in extrema]
    max_channel_range = max(channel_ranges)
    max_stddev = max(float(value) for value in stat.stddev)
    visual_status = "low_detail" if max_channel_range <= 8.0 and max_stddev <= 2.0 else "reviewable"
    edge_fraction_over_8 = (
        sum(1 for value in edge_values if int(value) > 8) / float(len(edge_values))
        if edge_values
        else 0.0
    )
    edge_fraction_over_16 = (
        sum(1 for value in edge_values if int(value) > 16) / float(len(edge_values))
        if edge_values
        else 0.0
    )
    return {
        "schema": "operator_console_preview_image_diagnostics_v1",
        "width": int(rgb.width),
        "height": int(rgb.height),
        "mean_rgb": [round(float(value), 3) for value in stat.mean],
        "channel_extrema_rgb": [[int(low), int(high)] for low, high in extrema],
        "max_channel_range": round(max_channel_range, 3),
        "max_stddev": round(max_stddev, 3),
        "thumbnail_color_count": len(thumbnail_colors) if thumbnail_colors is not None else 16000,
        "edge_fraction_over_8": round(edge_fraction_over_8, 6),
        "edge_fraction_over_16": round(edge_fraction_over_16, 6),
        "visual_status": visual_status,
    }


def _utc_timestamp() -> str:
    return dt.datetime.now(dt.UTC).isoformat(timespec="seconds").replace("+00:00", "Z")
