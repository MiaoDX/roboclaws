"""B1 Map 12 static and runtime-camera scene preview production."""

from __future__ import annotations

import json
import tempfile
from pathlib import Path
from typing import Any

from PIL import Image

from roboclaws.core.json_sources import read_json_object
from roboclaws.maps.b1_base_metric_map import (
    DEFAULT_LABELS as B1_BASE_METRIC_LABELS,
)
from roboclaws.maps.b1_base_metric_map import (
    DEFAULT_MAP_BUNDLE as B1_BASE_METRIC_MAP_BUNDLE,
)
from roboclaws.maps.b1_base_metric_map import (
    DEFAULT_ROOM_SEMANTICS as B1_ROOM_SEMANTICS,
)
from roboclaws.maps.b1_base_metric_map import (
    build_base_metric_map_bundle,
)
from roboclaws.maps.preview import (
    BASE_MAP_SOURCE_FAMILY,
    BASE_METRIC_MAP_PREVIEW_ROLE,
    SCENE_RENDER_SOURCE_FAMILY,
    TOPDOWN_SCENE_RENDER_ROLE,
    render_base_metric_map_preview,
)
from roboclaws.operator_console.scene_preview_b1_camera import (
    _b1_metadata_has_real_camera_previews,
    _promote_b1_camera_previews,
)
from roboclaws.operator_console.scene_preview_common import (
    _fit_preview_image,
    _image_diagnostics,
    _utc_timestamp,
    _world_slug,
)
from roboclaws.operator_console.scene_preview_contract import (
    B1_BASE_METRIC_MAP_PROVENANCE,
    B1_GAUSSIAN_SCENE_USD_PATH,
    B1_GAUSSIAN_TOPDOWN_FALLBACK_IMAGE,
    B1_GAUSSIAN_TOPDOWN_PACKET,
    B1_GAUSSIAN_TOPDOWN_PROVENANCE,
    B1_MAP12_WORLD_ID,
    DEFAULT_OUTPUT_DIR,
    PREVIEW_METADATA_SCHEMA,
)

REPO_ROOT = Path(__file__).resolve().parents[2]


def render_b1_map12_preview(
    *,
    output_dir: Path,
    width: int,
    height: int,
    skip_existing: bool = False,
    camera_artifact: Path | None = None,
) -> dict[str, Any]:
    slug = _world_slug(B1_MAP12_WORLD_ID)
    fpv_path = output_dir / f"{slug}-fpv.png"
    map_path = output_dir / f"{slug}-map.png"
    chase_path = output_dir / f"{slug}-chase.png"
    topdown_path = output_dir / f"{slug}-topdown.png"
    metadata_path = output_dir / f"{slug}-preview.json"
    removed_stale: list[str] = []
    skip_result = (
        _b1_preview_skip_result(
            camera_artifact=camera_artifact,
            fpv_path=fpv_path,
            map_path=map_path,
            chase_path=chase_path,
            topdown_path=topdown_path,
            metadata_path=metadata_path,
            removed_stale=removed_stale,
        )
        if skip_existing
        else None
    )
    if skip_result is not None:
        if skip_result.get("status") == "metadata_unreadable":
            return skip_result
        skip_result["removed_stale"] = removed_stale
        return skip_result

    if camera_artifact is None:
        removed_stale.extend(_unlink_existing_paths(fpv_path, chase_path))

    static_result = _write_b1_static_preview_assets(
        output_dir=output_dir,
        map_path=map_path,
        topdown_path=topdown_path,
        width=width,
        height=height,
    )
    metadata = _b1_map12_preview_metadata(
        width=width,
        height=height,
        map_path=map_path,
        topdown_path=topdown_path,
        static_result=static_result,
    )
    camera_result: dict[str, Any] | None = None
    if camera_artifact is not None:
        camera_result = _promote_b1_camera_previews(
            camera_artifact=Path(camera_artifact),
            fpv_path=fpv_path,
            chase_path=chase_path,
            width=width,
            height=height,
        )
        if camera_result.get("status") != "promoted":
            removed_stale.extend(_unlink_existing_paths(fpv_path, chase_path))
            metadata_path.write_text(
                json.dumps(metadata, indent=2, sort_keys=True) + "\n",
                encoding="utf-8",
            )
            return {
                "world_id": B1_MAP12_WORLD_ID,
                "scene_source": "b1-gaussian-digital-twin",
                "status": "camera_preview_unavailable",
                "metadata": str(metadata_path),
                "camera_artifact": str(camera_artifact),
                "camera_result": camera_result,
                "removed_stale": removed_stale,
                "map": str(map_path),
                "topdown": str(topdown_path),
            }
        metadata["renderer"] = "b1_map12_static_gaussian_topdown_with_isaac_runtime_camera"
        metadata["views"]["fpv"] = camera_result["views"]["fpv"]
        metadata["views"]["chase"] = camera_result["views"]["chase"]
        metadata["camera_preview_artifact"] = camera_result["artifact"]
    metadata_path.write_text(
        json.dumps(metadata, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    result = {
        "world_id": B1_MAP12_WORLD_ID,
        "scene_source": "b1-gaussian-digital-twin",
        "status": "rendered",
        "metadata": str(metadata_path),
        "map": str(map_path),
        "topdown": str(topdown_path),
        "removed_stale": removed_stale,
    }
    if camera_result is not None:
        result.update(
            {
                "fpv": str(fpv_path),
                "chase": str(chase_path),
                "camera_artifact": str(camera_artifact),
                "camera_selection_status": camera_result.get("selection_status"),
            }
        )
    return result


def _unlink_existing_paths(*paths: Path) -> list[str]:
    removed: list[str] = []
    for path in paths:
        if path.exists():
            path.unlink()
            removed.append(str(path))
    return removed


def _b1_preview_skip_result(
    *,
    camera_artifact: Path | None,
    fpv_path: Path,
    map_path: Path,
    chase_path: Path,
    topdown_path: Path,
    metadata_path: Path,
    removed_stale: list[str],
) -> dict[str, Any] | None:
    if not metadata_path.exists():
        return None
    try:
        static_ready = _b1_metadata_has_static_previews(
            metadata_path,
            map_path=map_path,
            topdown_path=topdown_path,
        )
        if camera_artifact is None:
            can_skip = static_ready and _b1_metadata_has_no_camera_previews(metadata_path)
        else:
            metadata_has_real_camera_previews = _b1_metadata_has_real_camera_previews(
                metadata_path,
                camera_artifact=camera_artifact,
            )
            can_skip = (
                static_ready
                and fpv_path.exists()
                and chase_path.exists()
                and metadata_has_real_camera_previews
            )
    except (OSError, ValueError) as exc:
        return {
            "world_id": B1_MAP12_WORLD_ID,
            "scene_source": "b1-gaussian-digital-twin",
            "status": "metadata_unreadable",
            "metadata": str(metadata_path),
            "reason": str(exc),
            "removed_stale": removed_stale,
        }
    if not can_skip:
        return None
    return {
        "world_id": B1_MAP12_WORLD_ID,
        "scene_source": "b1-gaussian-digital-twin",
        "status": "skipped",
        "map": str(map_path),
        "topdown": str(topdown_path),
        **(
            {"fpv": str(fpv_path), "chase": str(chase_path)}
            if fpv_path.exists() and chase_path.exists()
            else {}
        ),
        "metadata": str(metadata_path),
        "removed_stale": removed_stale,
    }


def _b1_metadata_has_static_previews(
    path: Path,
    *,
    map_path: Path,
    topdown_path: Path,
) -> bool:
    if not map_path.exists() or not topdown_path.exists():
        return False
    payload = read_json_object(path, label="B1 preview metadata")
    views = payload.get("views")
    if not isinstance(views, dict):
        return False
    return _b1_static_view_ready(
        views.get("map"),
        expected_path=map_path.name,
        expected_provenance=B1_BASE_METRIC_MAP_PROVENANCE,
    ) and _b1_static_view_ready(
        views.get("topdown"),
        expected_path=topdown_path.name,
        expected_provenance=B1_GAUSSIAN_TOPDOWN_PROVENANCE,
    )


def _b1_static_view_ready(
    view: Any,
    *,
    expected_path: str,
    expected_provenance: str,
) -> bool:
    if not isinstance(view, dict):
        return False
    return (
        str(view.get("path") or "") == expected_path
        and str(view.get("provenance") or "") == expected_provenance
    )


def _b1_metadata_has_no_camera_previews(path: Path) -> bool:
    payload = read_json_object(path, label="B1 preview metadata")
    views = payload.get("views")
    if not isinstance(views, dict):
        return False
    return "fpv" not in views and "chase" not in views


def _write_b1_static_preview_assets(
    *,
    output_dir: Path,
    map_path: Path,
    topdown_path: Path,
    width: int,
    height: int,
) -> dict[str, Any]:
    output_dir.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="b1-map12-preview-") as temp_dir:
        bundle_dir = Path(temp_dir) / "base-metric-map"
        bundle_result = build_base_metric_map_bundle(
            map_bundle=B1_BASE_METRIC_MAP_BUNDLE,
            labels_path=B1_BASE_METRIC_LABELS,
            room_semantics_path=B1_ROOM_SEMANTICS,
            output_dir=bundle_dir,
        )
        semantics = read_json_object(
            bundle_dir / "semantics.json",
            label="B1 Base Metric Map semantics",
        )
        render_base_metric_map_preview(
            semantics=semantics,
            output_path=map_path,
            width=width,
            height=height,
            provenance=B1_BASE_METRIC_MAP_PROVENANCE,
        )
        gaussian_topdown = _write_b1_gaussian_topdown_preview(
            output_path=topdown_path,
            width=width,
            height=height,
        )
        return {
            "map_bundle": str(B1_BASE_METRIC_MAP_BUNDLE),
            "base_metric_labels": str(B1_BASE_METRIC_LABELS),
            "room_semantics": str(B1_ROOM_SEMANTICS),
            "navigation_area_count": int(bundle_result["navigation_area_count"]),
            "inspection_waypoint_count": int(bundle_result["inspection_waypoint_count"]),
            "semantic_label_count": len(semantics.get("rooms") or []),
            "gaussian_topdown": gaussian_topdown,
            "first_waypoint_id": str(
                ((semantics.get("inspection_waypoints") or [{}])[0]).get("waypoint_id") or ""
            ),
        }


def _write_b1_gaussian_topdown_preview(
    *,
    output_path: Path,
    width: int,
    height: int,
) -> dict[str, Any]:
    packet = _b1_gaussian_topdown_packet_or_none()
    source_image = _b1_gaussian_topdown_source_image(packet)
    if source_image is None:
        source_image = _fallback_b1_gaussian_topdown_image(output_path)
    if source_image is None:
        raise FileNotFoundError(
            "B1 Gaussian topdown source missing: expected "
            f"{B1_GAUSSIAN_TOPDOWN_PACKET} or {B1_GAUSSIAN_TOPDOWN_FALLBACK_IMAGE}"
        )
    _fit_preview_image(Image.open(source_image), width=width, height=height).save(output_path)
    return _b1_gaussian_topdown_metadata(packet=packet, source_image=source_image)


def _b1_gaussian_topdown_packet_or_none() -> dict[str, Any] | None:
    if not B1_GAUSSIAN_TOPDOWN_PACKET.is_file():
        return None
    packet = read_json_object(B1_GAUSSIAN_TOPDOWN_PACKET, label="B1 Gaussian topdown packet")
    if packet.get("geometry_status") != "rendered_gaussian_scene_topdown":
        raise ValueError("B1 Gaussian topdown packet must be rendered_gaussian_scene_topdown")
    return packet


def _b1_gaussian_topdown_source_image(packet: dict[str, Any] | None) -> Path | None:
    if packet is None:
        return None
    raw_path = str(packet.get("topdown_image") or "").strip()
    if not raw_path:
        raise ValueError("B1 Gaussian topdown packet missing topdown_image")
    image_path = Path(raw_path)
    if image_path.is_file():
        return image_path
    repo_path = REPO_ROOT / image_path
    if repo_path.is_file():
        return repo_path
    raise FileNotFoundError(f"B1 Gaussian topdown image missing: {raw_path}")


def _fallback_b1_gaussian_topdown_image(output_path: Path) -> Path | None:
    fallback = B1_GAUSSIAN_TOPDOWN_FALLBACK_IMAGE
    if not _checked_in_b1_gaussian_topdown_is_current():
        return None
    if output_path.resolve() == fallback.resolve():
        return output_path if output_path.is_file() else None
    return fallback if fallback.is_file() else None


def _b1_gaussian_topdown_metadata(
    *,
    packet: dict[str, Any] | None,
    source_image: Path,
) -> dict[str, Any]:
    metadata: dict[str, Any] = {
        "source_image": _portable_repo_path(source_image),
        "source_packet": str(B1_GAUSSIAN_TOPDOWN_PACKET),
        "source_status": "captured_gaussian_topdown_packet"
        if packet is not None
        else "checked_in_operator_preview_png",
    }
    if packet is None:
        return metadata
    visibility_policy = packet.get("scene_visibility_policy")
    if isinstance(visibility_policy, dict):
        metadata["scene_visibility_policy"] = _portable_b1_metadata_value(visibility_policy)
    for key in (
        "geometry_status",
        "capture_status",
        "prepared_scene_usd",
        "scene_usd",
        "up_axis",
        "horizontal_axes",
        "scene_xy_bounds",
        "pixel_to_scene_xyz",
        "camera",
        "width_px",
        "height_px",
    ):
        if key in packet:
            metadata[key] = _portable_b1_metadata_value(packet[key])
    return metadata


def _checked_in_b1_gaussian_topdown_is_current() -> bool:
    metadata_path = DEFAULT_OUTPUT_DIR / "b1-map12-preview.json"
    if not metadata_path.is_file():
        return False
    try:
        payload = read_json_object(metadata_path, label="checked-in B1 preview metadata")
    except (OSError, ValueError):
        return False
    views = payload.get("views") if isinstance(payload.get("views"), dict) else {}
    topdown = views.get("topdown") if isinstance(views.get("topdown"), dict) else {}
    return (
        str(topdown.get("provenance") or "") == B1_GAUSSIAN_TOPDOWN_PROVENANCE
        and str(topdown.get("artifact_source_family") or "") == SCENE_RENDER_SOURCE_FAMILY
        and B1_GAUSSIAN_TOPDOWN_FALLBACK_IMAGE.is_file()
    )


def _portable_b1_metadata_value(value: Any) -> Any:
    if isinstance(value, dict):
        return {str(key): _portable_b1_metadata_value(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_portable_b1_metadata_value(item) for item in value]
    if isinstance(value, str):
        return _portable_repo_path(Path(value)) if value.startswith("/") else value
    return value


def _portable_repo_path(path: Path) -> str:
    resolved = Path(path).resolve()
    try:
        return resolved.relative_to(REPO_ROOT).as_posix()
    except ValueError:
        return str(path)


def _b1_map12_preview_metadata(
    *,
    width: int,
    height: int,
    map_path: Path,
    topdown_path: Path,
    static_result: dict[str, Any],
) -> dict[str, Any]:
    return {
        "schema": PREVIEW_METADATA_SCHEMA,
        "generated_at": _utc_timestamp(),
        "world_id": B1_MAP12_WORLD_ID,
        "backend": "isaaclab",
        "renderer": "b1_map12_static_gaussian_topdown_previews",
        "scene_source": "b1-gaussian-digital-twin",
        "scene_usd_path": str(B1_GAUSSIAN_SCENE_USD_PATH),
        "map_bundle": static_result["map_bundle"],
        "base_metric_labels": static_result["base_metric_labels"],
        "room_semantics": static_result["room_semantics"],
        "render_resolution": {"width": width, "height": height},
        "views": {
            "map": {
                "path": map_path.name,
                "view": BASE_METRIC_MAP_PREVIEW_ROLE,
                "visual_role": BASE_METRIC_MAP_PREVIEW_ROLE,
                "artifact_source_family": BASE_MAP_SOURCE_FAMILY,
                "provenance": B1_BASE_METRIC_MAP_PROVENANCE,
                "alignment_status": "verified_source_map_frame",
                "image_diagnostics": _image_diagnostics(map_path),
            },
            "topdown": {
                "path": topdown_path.name,
                "view": TOPDOWN_SCENE_RENDER_ROLE,
                "visual_role": TOPDOWN_SCENE_RENDER_ROLE,
                "artifact_source_family": SCENE_RENDER_SOURCE_FAMILY,
                "provenance": B1_GAUSSIAN_TOPDOWN_PROVENANCE,
                "alignment_status": "height_cropped_gaussian_scene_topdown",
                **static_result["gaussian_topdown"],
                "image_diagnostics": _image_diagnostics(topdown_path),
            },
        },
    }
