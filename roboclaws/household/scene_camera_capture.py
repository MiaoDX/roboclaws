from __future__ import annotations

import math
import traceback
from importlib import metadata
from pathlib import Path
from typing import Any

from roboclaws.core.json_sources import parse_json_object_text
from roboclaws.household import scene_camera_geometry_contract, scene_camera_usda_contract
from roboclaws.household.artifact_paths import dimensions_from_shape, output_relpath
from roboclaws.household.camera_control import (
    CANONICAL_CAMERA_MODEL,
    CANONICAL_POSE_CALIBRATION,
    DEFAULT_SCENE_PROBE_CAMERA_ORBIT,
    MOLMOSPACES_SCENE_FRAME,
)
from roboclaws.household.isaac_lab_backend import IsaacLabSubprocessBackend
from roboclaws.household.subprocess_backend import MolmoSpacesSubprocessBackend

MOLMOSPACES_LANE_ID = "molmospaces-mujoco"
ISAAC_LANE_ID = "isaaclab-prepared-usd"
CANONICAL_CAMERA_ELEVATION_DEG = 78.0
ROOM_CAMERA_HEIGHT_M = 1.45
ROOM_CAMERA_INSET_FRACTION = 0.35


def _official_molmospaces_source() -> dict[str, Any]:
    try:
        distribution = metadata.distribution("molmo-spaces")
    except metadata.PackageNotFoundError:
        return {
            "package": "molmo-spaces",
            "status": "not_installed",
            "expected_source": "https://github.com/allenai/molmospaces",
        }
    try:
        direct_url_text = distribution.read_text("direct_url.json")
    except OSError as exc:
        return _molmospaces_source_metadata_error(status="metadata_unreadable", error=exc)
    if not direct_url_text:
        return _molmospaces_source_metadata_error(status="metadata_unavailable")
    try:
        payload = parse_json_object_text(direct_url_text, label="molmo-spaces direct_url.json")
    except ValueError as exc:
        return _molmospaces_source_metadata_error(status="metadata_unreadable", error=exc)
    vcs_info = payload.get("vcs_info") if isinstance(payload, dict) else {}
    return {
        "package": "molmo-spaces",
        "status": "installed",
        "url": str(payload.get("url") or ""),
        "vcs": str(vcs_info.get("vcs") or "") if isinstance(vcs_info, dict) else "",
        "commit_id": str(vcs_info.get("commit_id") or "") if isinstance(vcs_info, dict) else "",
        "requested_revision": str(vcs_info.get("requested_revision") or "")
        if isinstance(vcs_info, dict)
        else "",
    }


def _molmospaces_source_metadata_error(
    *,
    status: str,
    error: BaseException | None = None,
) -> dict[str, Any]:
    payload = {
        "package": "molmo-spaces",
        "status": status,
        "expected_source": "https://github.com/allenai/molmospaces",
    }
    if error is not None:
        payload["error"] = str(error)
    return payload


def _runtime_object_positions(state: dict[str, Any]) -> dict[str, dict[str, Any]]:
    objects = state.get("objects") if isinstance(state.get("objects"), dict) else {}
    result: dict[str, dict[str, Any]] = {}
    for object_key, item in objects.items():
        if not isinstance(item, dict):
            continue
        position = item.get("position")
        if not scene_camera_geometry_contract.is_vec3(position):
            continue
        result[str(object_key)] = {
            "category": item.get("category") or "",
            "position": [float(value) for value in position[:3]],
            "seeded_start_receptacle_id": item.get("seeded_start_receptacle_id") or "",
            "target_receptacle_id": item.get("target_receptacle_id") or "",
            "location_id": item.get("location_id") or "",
            "location_relation": item.get("location_relation") or "",
            "contained_in": item.get("contained_in"),
            "upstream_object_id": item.get("upstream_object_id") or "",
        }
    return result


def _runtime_render_state(state: dict[str, Any]) -> dict[str, Any]:
    runtime_state = (
        state.get("runtime_render_state")
        if isinstance(state.get("runtime_render_state"), dict)
        else {}
    )
    if runtime_state:
        return runtime_state
    positions = _runtime_object_positions(state)
    return {
        "schema": "molmospaces_runtime_render_state_v1",
        "status": "positions_only_legacy_state",
        "source": "legacy_runtime_object_positions_without_articulation",
        "object_count": len(positions),
        "articulated_object_count": 0,
        "objects": {
            object_key: {
                "object_key": object_key,
                "category": value.get("category") or "",
                "position": value.get("position") or [],
                "subtree_joint_count": 0,
                "articulation_status": "unknown_legacy_state",
                "articulation_joints": [],
            }
            for object_key, value in positions.items()
        },
    }


def _capture_molmospaces_lane(config: Any) -> dict[str, Any]:
    lane_dir = config.output_dir / "molmospaces"
    try:
        backend = MolmoSpacesSubprocessBackend(
            run_dir=lane_dir,
            seed=config.seed,
            python_executable=config.molmospaces_python,
            scene_source=config.scene_source,
            scene_index=config.scene_index,
            include_robot=False,
            generated_mess_count=config.generated_mess_count,
        )
        try:
            state = backend._read_state()
            return {
                "status": "success",
                "python_executable": str(config.molmospaces_python),
                "runtime": dict(backend.runtime),
                "scene_xml": backend.scene_xml,
                "requested_generated_mess_count": backend.requested_generated_mess_count,
                "generated_mess_count": backend.generated_mess_count,
                "_state": state,
            }
        finally:
            backend.close()
    except Exception as exc:
        return _lane_failure(config.molmospaces_python, exc)


def _capture_molmospaces_camera_views(
    config: Any,
    *,
    camera_request_path: Path,
    lane_dir: Path,
) -> dict[str, Any]:
    try:
        lane_dir.mkdir(parents=True, exist_ok=True)
        backend = MolmoSpacesSubprocessBackend(
            run_dir=lane_dir,
            seed=config.seed,
            python_executable=config.molmospaces_python,
            scene_source=config.scene_source,
            scene_index=config.scene_index,
            include_robot=False,
            generated_mess_count=config.generated_mess_count,
        )
        try:
            result = backend.render_camera_control_request(
                lane_dir / "camera_views",
                request_path=camera_request_path,
            )
        finally:
            backend.close()
        if result.get("ok") is not True:
            raise RuntimeError(f"MolmoSpaces camera view capture failed: {result}")
        return {
            "status": "success",
            "view_variant": result.get("view_variant"),
            "visual_artifact_provenance": result.get("visual_artifact_provenance"),
            "camera_control_api": result.get("camera_control_api"),
            "camera_request_schema": result.get("camera_request_schema"),
            "calibration_status": result.get("calibration_status"),
            "lighting_profile": result.get("lighting_profile") or {},
            "lighting_diagnostics": result.get("lighting_diagnostics") or {},
            "color_profile": result.get("color_profile") or {},
            "color_management": result.get("color_management") or {},
            "lens": result.get("lens") or {},
            "images": _image_entries(output_dir=config.output_dir, result=result),
            "views": result.get("views") or [],
            "camera_control_request": output_relpath(camera_request_path, config.output_dir),
        }
    except Exception as exc:
        return _lane_failure(config.molmospaces_python, exc)


def _capture_isaac_lane(
    config: Any,
    *,
    camera_request_path: Path,
    lane_dir: Path,
) -> dict[str, Any]:
    try:
        lane_dir.mkdir(parents=True, exist_ok=True)
        backend = IsaacLabSubprocessBackend(
            run_dir=lane_dir,
            seed=config.seed,
            python_executable=config.isaac_python,
            scene_source=config.scene_source,
            scene_index=config.scene_index,
            include_robot=False,
            generated_mess_count=config.generated_mess_count,
            scene_usd_path=config.scene_usd_path,
            runtime_mode="real",
        )
        result = backend.render_camera_control_request(
            lane_dir / "camera_views",
            request_path=camera_request_path,
        )
        if result.get("ok") is not True:
            raise RuntimeError(f"Isaac camera view capture failed: {result}")
        return {
            "status": "success",
            "python_executable": str(config.isaac_python),
            "runtime": dict(backend.runtime),
            "scene_usd": backend.scene_usd,
            "scene_load": backend.scene_load,
            "scene_index_diagnostics": backend.scene_index_diagnostics,
            "requested_generated_mess_count": backend.requested_generated_mess_count,
            "generated_mess_count": backend.generated_mess_count,
            "view_variant": result.get("view_variant"),
            "visual_artifact_provenance": result.get("visual_artifact_provenance"),
            "camera_control_api": result.get("camera_control_api"),
            "camera_request_schema": result.get("camera_request_schema"),
            "calibration_status": result.get("calibration_status"),
            "lighting_profile": result.get("lighting_profile") or {},
            "lighting_diagnostics": result.get("lighting_diagnostics") or {},
            "color_profile": result.get("color_profile") or {},
            "color_management": result.get("color_management") or {},
            "native_render_diagnostics": result.get("native_render_diagnostics") or {},
            "lens": result.get("lens") or {},
            "derived_lens": result.get("derived_lens") or {},
            "render_steps": result.get("render_steps"),
            "scene_bounds": result.get("scene_bounds"),
            "images": _image_entries(output_dir=config.output_dir, result=result),
            "views": result.get("views") or [],
            "camera_control_request": output_relpath(camera_request_path, config.output_dir),
        }
    except Exception as exc:
        return _lane_failure(config.isaac_python, exc)


def _scene_anchors(state: dict[str, Any], *, limit: int) -> list[dict[str, Any]]:
    anchors = []
    for item in (state.get("receptacles") or {}).values():
        if not isinstance(item, dict):
            continue
        position = item.get("position")
        if not isinstance(position, list) or len(position) < 3:
            continue
        room_id = str(item.get("room_area") or "")
        room = _room_outline(state, room_id)
        room_center = room.get("center") if isinstance(room.get("center"), list) else None
        anchors.append(
            {
                "anchor_id": str(item.get("receptacle_id") or ""),
                "anchor_kind": "receptacle",
                "category": str(item.get("category") or ""),
                "room_id": room_id,
                "label": str(item.get("name") or item.get("receptacle_id") or ""),
                "molmospaces_position": [
                    float(position[0]),
                    float(position[1]),
                    float(position[2]),
                ],
                "molmospaces_support_top_z": scene_camera_geometry_contract.optional_float(
                    item.get("support_top_z")
                ),
                "room_center_xy": [float(room_center[0]), float(room_center[1])]
                if isinstance(room_center, list) and len(room_center) >= 2
                else None,
            }
        )
    anchors.sort(key=lambda item: (item["room_id"], item["category"], item["anchor_id"]))
    return anchors[:limit]


def _molmospaces_view_specs(
    anchors: list[dict[str, Any]],
    *,
    molmo_state: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    specs = []
    for index, anchor in enumerate(anchors, start=1):
        position = anchor["molmospaces_position"]
        support_top_z = anchor.get("molmospaces_support_top_z")
        target_z = float(support_top_z) + 0.25 if support_top_z is not None else position[2]
        lookat = [position[0], position[1], max(float(target_z), 0.6)]
        camera_orbit = _anchor_camera_orbit(anchor, state=molmo_state or {})
        specs.append(
            {
                "view_id": f"view_{index:02d}_{_safe_id(anchor['category'])}",
                "label": f"{anchor['room_id']} {anchor['category']} {anchor['anchor_id']}",
                "anchor_id": anchor["anchor_id"],
                "anchor_kind": anchor["anchor_kind"],
                "camera_mode": "anchor_orbit",
                "focus_receptacle_id": anchor["anchor_id"],
                "lookat": lookat,
                "target_source": "molmospaces_metadata_anchor_position",
                "camera_orbit": camera_orbit,
            }
        )
    return specs


def _anchor_camera_orbit(anchor: dict[str, Any], *, state: dict[str, Any]) -> dict[str, float]:
    """Choose a room-interior orbit that keeps the anchor visible in MuJoCo."""

    category = _category_key(anchor.get("category"))
    if category == "sink":
        azimuth = 315.0
    elif category in {"diningtable", "table"}:
        azimuth = 90.0
    elif category == "bed":
        azimuth = _bed_anchor_azimuth(anchor, state=state)
    else:
        azimuth = float(DEFAULT_SCENE_PROBE_CAMERA_ORBIT["azimuth_deg"])
    return {
        "distance_m": float(DEFAULT_SCENE_PROBE_CAMERA_ORBIT["distance_m"]),
        "azimuth_deg": azimuth,
        "elevation_deg": float(DEFAULT_SCENE_PROBE_CAMERA_ORBIT["elevation_deg"]),
    }


def _bed_anchor_azimuth(anchor: dict[str, Any], *, state: dict[str, Any]) -> float:
    room = _room_outline(state, str(anchor.get("room_id") or ""))
    position = anchor.get("molmospaces_position") if isinstance(anchor, dict) else None
    if room and isinstance(position, list) and len(position) >= 2:
        center = room.get("center")
        if isinstance(center, list) and len(center) >= 2:
            dy = float(position[1]) - float(center[1])
            return 90.0 if dy >= 0 else 225.0
    return 90.0


def _room_outline(state: dict[str, Any], room_id: str) -> dict[str, Any]:
    for room in state.get("room_outlines") or []:
        if isinstance(room, dict) and str(room.get("room_id") or "") == room_id:
            return room
    return {}


def _category_key(value: Any) -> str:
    return "".join(ch for ch in str(value or "").lower() if ch.isalnum())


def _isaac_lane_camera_orbit(anchor: dict[str, Any]) -> dict[str, float]:
    category = _category_key(anchor.get("category"))
    if category == "bed":
        azimuth = 225.0
    elif category in {"diningtable", "table"}:
        azimuth = 180.0
    elif category == "sink":
        azimuth = 315.0
    else:
        azimuth = float(DEFAULT_SCENE_PROBE_CAMERA_ORBIT["azimuth_deg"])
    return {
        "distance_m": float(DEFAULT_SCENE_PROBE_CAMERA_ORBIT["distance_m"]),
        "azimuth_deg": azimuth,
        "elevation_deg": float(DEFAULT_SCENE_PROBE_CAMERA_ORBIT["elevation_deg"]),
    }


def _isaac_view_specs(
    anchors: list[dict[str, Any]],
    *,
    scene_usd_path: Path,
    scene_index: int,
) -> list[dict[str, Any]]:
    metadata = scene_camera_usda_contract.load_scene_metadata(scene_usd_path)
    local_scene_index = scene_camera_usda_contract.load_local_isaac_scene_index(scene_usd_path)
    specs = []
    for index, anchor in enumerate(anchors, start=1):
        raw = metadata.get(anchor["anchor_id"]) or {}
        index_entry = scene_camera_usda_contract.isaac_scene_index_entry(
            anchor["anchor_id"], local_scene_index
        )
        usd_prim_path = (
            str(index_entry.get("usd_prim_path") or "") if isinstance(index_entry, dict) else ""
        )
        support_pose = index_entry.get("support_pose") if isinstance(index_entry, dict) else None
        isaac_support_position = scene_camera_usda_contract.support_pose_position(support_pose)
        if not usd_prim_path and raw:
            usd_prim_path = f"/val_{scene_index}/Geometry/{anchor['anchor_id']}"
        specs.append(
            {
                "view_id": f"view_{index:02d}_{_safe_id(anchor['category'])}",
                "label": f"{anchor['room_id']} {anchor['category']} {anchor['anchor_id']}",
                "anchor_id": anchor["anchor_id"],
                "anchor_kind": anchor["anchor_kind"],
                "usd_prim_path": usd_prim_path,
                "target_source": (
                    "isaac_worker_usd_prim_world_bounds_diagnostic"
                    if usd_prim_path
                    else "missing_isaac_usd_prim_path"
                ),
                "isaac_support_position": isaac_support_position,
                "min_target_z": 0.6,
            }
        )
        anchor["isaac_usd_prim_path"] = usd_prim_path
        if isaac_support_position:
            anchor["isaac_support_position"] = isaac_support_position
            anchor["isaac_target_source"] = (
                "Canonical explicit target; Isaac support pose recorded as navigation metadata"
            )
        else:
            anchor["isaac_target_source"] = (
                "Canonical explicit target; USD prim bounds resolved in Isaac worker"
            )
    return specs


def _room_camera_control_views(state: dict[str, Any]) -> list[dict[str, Any]]:
    views = []
    rooms = [room for room in (state.get("room_outlines") or []) if isinstance(room, dict)]
    rooms.sort(key=lambda item: str(item.get("room_id") or ""))
    for index, room in enumerate(rooms, start=1):
        center = room.get("center")
        half_extents = room.get("half_extents")
        if not (
            isinstance(center, list)
            and len(center) >= 2
            and isinstance(half_extents, list)
            and len(half_extents) >= 2
        ):
            continue
        room_id = str(room.get("room_id") or f"room_{index}")
        hx = max(float(half_extents[0]), 0.5)
        hy = max(float(half_extents[1]), 0.5)
        target = [float(center[0]), float(center[1]), ROOM_CAMERA_HEIGHT_M]
        eye = [
            float(center[0]) - hx * ROOM_CAMERA_INSET_FRACTION,
            float(center[1]) - hy * ROOM_CAMERA_INSET_FRACTION,
            ROOM_CAMERA_HEIGHT_M,
        ]
        views.append(
            {
                "view_id": f"room_{index:02d}_{_safe_id(room_id)}",
                "label": f"{room.get('label') or room_id} canonical room view",
                "anchor_id": room_id,
                "anchor_kind": "room",
                "category": "Room",
                "room_id": room_id,
                "camera_mode": "canonical_eye_target",
                "camera_model": CANONICAL_CAMERA_MODEL,
                "coordinate_frame": MOLMOSPACES_SCENE_FRAME,
                "coordinate_convention": MOLMOSPACES_SCENE_FRAME,
                "calibration_status": CANONICAL_POSE_CALIBRATION,
                "eye": eye,
                "target": target,
                "lookat": target,
                "up": [0.0, 0.0, 1.0],
                "camera_basis": "room_center_inset_eye_target",
                "target_source": {
                    MOLMOSPACES_LANE_ID: "molmospaces_room_outline_center",
                    ISAAC_LANE_ID: "canonical_explicit_room_target_from_molmospaces_scene_frame",
                },
                "lane_targets": {
                    MOLMOSPACES_LANE_ID: {"lookat": target, "room_id": room_id},
                    ISAAC_LANE_ID: {"room_id": room_id},
                },
                "room_outline": {
                    "center": [float(center[0]), float(center[1])],
                    "half_extents": [hx, hy],
                    "provenance": str(room.get("provenance") or ""),
                },
            }
        )
    return views


def _canonical_camera_control_views(
    anchors: list[dict[str, Any]],
    *,
    molmo_specs: list[dict[str, Any]],
    isaac_specs: list[dict[str, Any]],
    scene_transform: dict[str, Any],
) -> list[dict[str, Any]]:
    views = []
    for anchor, molmo_spec, isaac_spec in zip(anchors, molmo_specs, isaac_specs, strict=True):
        target = [float(value) for value in molmo_spec.get("lookat") or []]
        camera_orbit = molmo_spec.get("camera_orbit") or DEFAULT_SCENE_PROBE_CAMERA_ORBIT
        distance = float(
            camera_orbit.get("distance_m", DEFAULT_SCENE_PROBE_CAMERA_ORBIT["distance_m"])
        )
        azimuth = float(
            camera_orbit.get("azimuth_deg", DEFAULT_SCENE_PROBE_CAMERA_ORBIT["azimuth_deg"])
        )
        eye = _eye_from_mujoco_orbit(
            target=target,
            distance=distance,
            azimuth=azimuth,
            elevation=-CANONICAL_CAMERA_ELEVATION_DEG,
        )
        view = {
            "view_id": molmo_spec["view_id"],
            "label": molmo_spec["label"],
            "anchor_id": anchor["anchor_id"],
            "anchor_kind": anchor["anchor_kind"],
            "category": anchor["category"],
            "room_id": anchor["room_id"],
            "camera_mode": "canonical_eye_target",
            "camera_model": CANONICAL_CAMERA_MODEL,
            "coordinate_frame": MOLMOSPACES_SCENE_FRAME,
            "coordinate_convention": MOLMOSPACES_SCENE_FRAME,
            "calibration_status": CANONICAL_POSE_CALIBRATION,
            "eye": eye,
            "target": target,
            "lookat": target,
            "up": [0.0, 0.0, 1.0],
            "camera_basis": "near_topdown_anchor_orbit",
            "backend_transforms": {
                ISAAC_LANE_ID: scene_transform,
            },
            "target_source": {
                MOLMOSPACES_LANE_ID: molmo_spec.get("target_source"),
                ISAAC_LANE_ID: "canonical_explicit_target_from_molmospaces_scene_frame",
            },
            "lane_targets": {
                MOLMOSPACES_LANE_ID: {
                    "lookat": target,
                    "focus_receptacle_id": molmo_spec.get("focus_receptacle_id"),
                },
                ISAAC_LANE_ID: {
                    "usd_prim_path": isaac_spec.get("usd_prim_path"),
                    "support_position": isaac_spec.get("isaac_support_position"),
                    "min_target_z": isaac_spec.get("min_target_z", 0.6),
                },
            },
            "usd_prim_path": isaac_spec.get("usd_prim_path"),
            "min_target_z": isaac_spec.get("min_target_z", 0.6),
        }
        views.append(view)
    return views


def _eye_from_mujoco_orbit(
    *,
    target: list[float],
    distance: float,
    azimuth: float,
    elevation: float,
) -> list[float]:
    azimuth_rad = math.radians(azimuth)
    elevation_rad = math.radians(elevation)
    horizontal = math.cos(elevation_rad) * distance
    return [
        float(target[0]) - math.cos(azimuth_rad) * horizontal,
        float(target[1]) - math.sin(azimuth_rad) * horizontal,
        float(target[2]) - math.sin(elevation_rad) * distance,
    ]


def _image_entries(*, output_dir: Path, result: dict[str, Any]) -> dict[str, dict[str, Any]]:
    images = result.get("images") if isinstance(result.get("images"), dict) else {}
    shapes = result.get("shapes") if isinstance(result.get("shapes"), dict) else {}
    entries = {}
    for view_id, raw_path in images.items():
        path = Path(str(raw_path))
        entries[str(view_id)] = {
            "path": output_relpath(path, output_dir),
            "dimensions": dimensions_from_shape(shapes.get(view_id)),
        }
    return entries


def _lane_failure(python_executable: Path, exc: Exception) -> dict[str, Any]:
    return {
        "status": "failed",
        "python_executable": str(python_executable),
        "failure": {
            "type": type(exc).__name__,
            "message": str(exc),
            "traceback": traceback.format_exc(limit=8),
        },
    }


def _safe_id(value: Any) -> str:
    text = str(value or "scene").lower()
    safe = "".join(ch if ch.isalnum() else "_" for ch in text).strip("_")
    return safe or "scene"
