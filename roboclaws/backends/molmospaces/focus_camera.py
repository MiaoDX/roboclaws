from __future__ import annotations

import math
from typing import Any, Callable

import mujoco
from PIL import Image, ImageDraw

from roboclaws.backends.molmospaces.room_map import item_label
from roboclaws.household.camera_control import ANCHOR_ORBIT_CAMERA_MODEL, camera_pose_vec3


def focus_camera(
    state: dict[str, Any],
    focus: dict[str, Any],
    *,
    scene_focus_position: Callable[[dict[str, Any]], list[float]] | None = None,
    focus_camera_azimuth: Callable[[dict[str, Any], list[float], dict[str, Any] | None], float]
    | None = None,
) -> mujoco.MjvCamera:
    scene_focus_position = scene_focus_position or default_scene_focus_position
    focus_camera_azimuth = focus_camera_azimuth or default_focus_camera_azimuth
    focus_position = focus.get("focus_position") or scene_focus_position(state)
    camera = mujoco.MjvCamera()
    camera.type = mujoco.mjtCamera.mjCAMERA_FREE
    camera.lookat[:] = [
        float(focus_position[0]),
        float(focus_position[1]),
        float(focus_position[2]) + 0.35,
    ]
    if focus.get("focus_mode") == "object_closeup":
        camera.lookat[:] = [
            float(focus_position[0]),
            float(focus_position[1]),
            float(focus_position[2]) + 0.05,
        ]
        camera.distance = 1.8
        camera.elevation = -65
    else:
        camera.distance = 4.0 if focus.get("has_focus") else 7.5
        camera.elevation = -68 if focus.get("has_focus") else -45
    camera.azimuth = focus_camera_azimuth(state, focus_position, focus)
    return camera


def camera_view_spec(raw_spec: dict[str, Any], *, index: int) -> dict[str, Any]:
    view_id = str(raw_spec.get("view_id") or raw_spec.get("id") or f"view_{index:02d}")
    safe_view_id = "".join(ch if ch.isalnum() or ch in {"-", "_"} else "_" for ch in view_id)
    target_field = "lookat" if raw_spec.get("lookat") is not None else "target"
    lookat = camera_vec3(raw_spec.get(target_field), field_name=target_field)
    camera_orbit = lane_camera_orbit(raw_spec, "molmospaces-mujoco")
    lens = raw_spec.get("lens") if isinstance(raw_spec.get("lens"), dict) else {}
    if "eye" in raw_spec and raw_spec.get("eye") is not None:
        eye = camera_vec3(raw_spec.get("eye"), field_name="eye")
        dx = eye[0] - lookat[0]
        dy = eye[1] - lookat[1]
        dz = eye[2] - lookat[2]
        distance = max(math.sqrt(dx * dx + dy * dy + dz * dz), 0.01)
        horizontal = math.hypot(dx, dy)
        if horizontal > 1e-9:
            azimuth = math.degrees(math.atan2(-dy, -dx))
        else:
            azimuth = float(camera_orbit.get("azimuth_deg", raw_spec.get("azimuth", 0.0)))
        elevation = -math.degrees(math.asin(dz / distance))
    else:
        distance = float(camera_orbit.get("distance_m", raw_spec.get("distance", 4.0)))
        azimuth = float(camera_orbit.get("azimuth_deg", raw_spec.get("azimuth", 225.0)))
        elevation = -abs(float(camera_orbit.get("elevation_deg", raw_spec.get("elevation", 35.0))))
        eye = eye_from_mujoco_free_camera(
            lookat=lookat,
            distance=distance,
            azimuth=azimuth,
            elevation=elevation,
        )
    return {
        "view_id": safe_view_id,
        "label": str(raw_spec.get("label") or view_id),
        "anchor_id": str(raw_spec.get("anchor_id") or ""),
        "anchor_kind": str(raw_spec.get("anchor_kind") or ""),
        "robot_view_role": str(raw_spec.get("robot_view_role") or ""),
        "camera_basis": str(raw_spec.get("camera_basis") or ""),
        "camera_mode": str(raw_spec.get("camera_mode") or "free_camera"),
        "focus_receptacle_id": str(raw_spec.get("focus_receptacle_id") or ""),
        "robot_pose": dict(raw_spec["robot_pose"])
        if isinstance(raw_spec.get("robot_pose"), dict)
        else {},
        "lookat": lookat,
        "target": lookat,
        "eye": eye,
        "backend_eye": eye,
        "backend_target": lookat,
        "distance": distance,
        "azimuth": azimuth,
        "elevation": elevation,
        "camera_model": str(raw_spec.get("camera_model") or ANCHOR_ORBIT_CAMERA_MODEL),
        "coordinate_frame": str(raw_spec.get("coordinate_frame") or ""),
        "camera_orbit": dict(camera_orbit),
        "lens": dict(lens),
        "calibration_status": str(raw_spec.get("calibration_status") or ""),
        "coordinate_convention": str(raw_spec.get("coordinate_convention") or ""),
    }


def lane_camera_orbit(raw_spec: dict[str, Any], lane_id: str) -> dict[str, Any]:
    lane_orbits = raw_spec.get("lane_camera_orbits")
    if isinstance(lane_orbits, dict):
        lane_orbit = lane_orbits.get(lane_id)
        if isinstance(lane_orbit, dict):
            return lane_orbit
    camera_orbit = raw_spec.get("camera_orbit")
    return camera_orbit if isinstance(camera_orbit, dict) else {}


def camera_vec3(value: Any, *, field_name: str = "camera vector") -> list[float]:
    return camera_pose_vec3(value, field_name=field_name)


def eye_from_mujoco_free_camera(
    *,
    lookat: list[float],
    distance: float,
    azimuth: float,
    elevation: float,
) -> list[float]:
    azimuth_rad = math.radians(azimuth)
    elevation_rad = math.radians(elevation)
    horizontal = math.cos(elevation_rad) * distance
    return [
        float(lookat[0]) - math.cos(azimuth_rad) * horizontal,
        float(lookat[1]) - math.sin(azimuth_rad) * horizontal,
        float(lookat[2]) - math.sin(elevation_rad) * distance,
    ]


def free_camera_from_lookat_spec(spec: dict[str, Any]) -> mujoco.MjvCamera:
    camera = mujoco.MjvCamera()
    camera.type = mujoco.mjtCamera.mjCAMERA_FREE
    camera.lookat[:] = spec["lookat"]
    camera.distance = float(spec["distance"])
    camera.azimuth = float(spec["azimuth"])
    camera.elevation = float(spec["elevation"])
    return camera


def camera_from_view_spec(
    state: dict[str, Any],
    spec: dict[str, Any],
    *,
    free_camera_from_lookat_spec: Callable[[dict[str, Any]], mujoco.MjvCamera] | None = None,
    focus_payload: Callable[[dict[str, Any], str | None, str | None], dict[str, Any]] | None = None,
    focus_camera: Callable[[dict[str, Any], dict[str, Any]], mujoco.MjvCamera] | None = None,
) -> mujoco.MjvCamera:
    free_camera_from_lookat_spec = (
        free_camera_from_lookat_spec or globals()["free_camera_from_lookat_spec"]
    )
    focus_payload = focus_payload or globals()["focus_payload"]
    focus_camera = focus_camera or globals()["focus_camera"]
    if spec.get("camera_mode") != "focus_receptacle":
        return free_camera_from_lookat_spec(spec)
    focus_receptacle_id = str(spec.get("focus_receptacle_id") or spec.get("anchor_id") or "")
    if spec.get("camera_model") == ANCHOR_ORBIT_CAMERA_MODEL:
        spec["camera_mode"] = "anchor_orbit"
        spec["focus_receptacle_id"] = focus_receptacle_id
        return free_camera_from_lookat_spec(spec)
    state_for_camera = dict(state)
    if isinstance(spec.get("robot_pose"), dict):
        state_for_camera["robot_pose"] = dict(spec["robot_pose"])
    focus = focus_payload(
        state_for_camera,
        None,
        focus_receptacle_id,
    )
    camera = focus_camera(state_for_camera, focus)
    spec["lookat"] = [float(value) for value in camera.lookat]
    spec["distance"] = float(camera.distance)
    spec["azimuth"] = float(camera.azimuth)
    spec["elevation"] = float(camera.elevation)
    spec["camera_model"] = "mujoco_focus_receptacle_camera"
    if isinstance(spec.get("robot_pose"), dict):
        spec["virtual_robot_pose"] = dict(spec["robot_pose"])
    return camera


def annotate_focus_image(image: Image.Image, focus: dict[str, Any]) -> None:
    if not focus.get("has_focus"):
        return
    draw = ImageDraw.Draw(image)
    object_label = str(focus.get("object_label") or "object")
    receptacle_label = str(focus.get("receptacle_label") or "target")
    label = f"Object: {object_label}   Target: {receptacle_label}"
    draw.rectangle((0, 0, image.width, 28), fill=(15, 23, 42))
    draw.text((10, 8), label, fill=(248, 250, 252))
    visibility = focus.get("visibility") or {}
    for box in visibility.get("boxes", []):
        left, top, right, bottom = box["bbox"]
        color = tuple(box["color"])
        draw.rectangle((left, top, right, bottom), outline=color, width=4)
        draw.text((left, max(30, top - 14)), box["label"], fill=color)


def default_focus_camera_azimuth(
    state: dict[str, Any],
    focus_position: list[float],
    focus: dict[str, Any] | None = None,
) -> float:
    if (
        focus is not None
        and focus.get("receptacle_category") == "Fridge"
        and focus.get("focus_mode") != "object_closeup"
        and focus.get("object_contained_in") != focus.get("receptacle_id")
    ):
        return 45.0
    pose = state.get("robot_pose") or {}
    if "x" not in pose or "y" not in pose:
        return 225.0
    dx = float(focus_position[0]) - float(pose["x"])
    dy = float(focus_position[1]) - float(pose["y"])
    if math.hypot(dx, dy) < 0.001:
        return 225.0
    return math.degrees(math.atan2(dx, dy))


def focus_payload(
    state: dict[str, Any],
    focus_object_id: str | None,
    focus_receptacle_id: str | None,
    *,
    label_item: Callable[[dict[str, Any] | None, str], str] = item_label,
    average_position: Callable[[list[list[float]]], list[float]] | None = None,
    scene_focus_position: Callable[[dict[str, Any]], list[float]] | None = None,
) -> dict[str, Any]:
    average_position = average_position or default_average_position
    scene_focus_position = scene_focus_position or default_scene_focus_position
    obj = state["objects"].get(focus_object_id) if focus_object_id else None
    receptacle = state["receptacles"].get(focus_receptacle_id) if focus_receptacle_id else None
    positions = []
    if obj is not None:
        positions.append(obj["position"])
    if receptacle is not None:
        positions.append(receptacle["position"])
    if obj is not None and receptacle is not None:
        focus_position, focus_mode = object_receptacle_focus_target(obj, receptacle)
    else:
        focus_position = average_position(positions) if positions else scene_focus_position(state)
        focus_mode = "receptacle_context" if receptacle is not None else "scene_context"
    return {
        "has_focus": obj is not None or receptacle is not None,
        "object_id": focus_object_id,
        "object_label": label_item(obj, "object_id") if obj is not None else None,
        "object_category": obj.get("category") if obj is not None else None,
        "object_position": obj.get("position") if obj is not None else None,
        "object_body_name": obj.get("body_name") if obj is not None else None,
        "object_contained_in": obj.get("contained_in") if obj is not None else None,
        "object_location_relation": obj.get("location_relation") if obj is not None else None,
        "receptacle_id": focus_receptacle_id,
        "receptacle_label": label_item(receptacle, "receptacle_id")
        if receptacle is not None
        else None,
        "receptacle_category": receptacle.get("category") if receptacle is not None else None,
        "receptacle_position": receptacle.get("position") if receptacle is not None else None,
        "receptacle_body_name": receptacle.get("body_name") if receptacle is not None else None,
        "focus_position": focus_position,
        "focus_mode": focus_mode,
        "provenance": "public_mujoco_state_report_aid",
    }


def object_receptacle_focus_target(
    obj: dict[str, Any],
    receptacle: dict[str, Any],
) -> tuple[list[float], str]:
    object_position = obj["position"]
    receptacle_position = receptacle["position"]
    if obj.get("location_relation") == "held":
        return object_position, "object_closeup"
    if receptacle.get("category") == "Fridge" and obj.get("contained_in") == receptacle.get(
        "receptacle_id"
    ):
        return receptacle_position, "receptacle_context"
    if math.dist(object_position[:2], receptacle_position[:2]) > 1.2:
        return receptacle_position, "receptacle_context"
    return object_position, "object_closeup"


def default_average_position(positions: list[list[float]]) -> list[float]:
    return [
        round(sum(float(position[index]) for position in positions) / len(positions), 6)
        for index in range(3)
    ]


def default_scene_focus_position(state: dict[str, Any]) -> list[float]:
    points = [item["position"] for item in state["receptacles"].values()]
    if not points:
        return [0.0, 0.0, 0.0]
    return default_average_position(points)


def annotate_focus_visual_grounding(
    focus: dict[str, Any],
    *,
    visual_grounding_status: Callable[[dict[str, Any], dict[str, Any]], str] | None = None,
) -> dict[str, Any]:
    visual_grounding_status = visual_grounding_status or default_visual_grounding_status
    if not focus.get("has_focus"):
        return focus
    annotated = dict(focus)
    for key in ("fpv_visibility", "visibility"):
        visibility = annotated.get(key)
        if not isinstance(visibility, dict):
            continue
        updated = dict(visibility)
        if updated.get("status") != "segmentation_unavailable":
            status = visual_grounding_status(annotated, updated)
            updated["status"] = status
            updated["visual_grounding_status"] = status
            if status == "weak_object_visibility":
                updated.setdefault(
                    "evidence_note",
                    "Focused object has zero pixels in this robot-view frame.",
                )
            elif status == "contained_inside":
                updated.setdefault(
                    "evidence_note",
                    "Object is semantically contained inside the focused receptacle.",
                )
        annotated[key] = updated
    return annotated


def should_use_fpv_as_verify_focus(
    focus: dict[str, Any],
    *,
    focus_visibility_is_grounded: Callable[[dict[str, Any], dict[str, Any]], bool] | None = None,
) -> bool:
    focus_visibility_is_grounded = (
        focus_visibility_is_grounded or default_focus_visibility_is_grounded
    )
    fpv_visibility = focus.get("fpv_visibility") or {}
    verify_visibility = focus.get("visibility") or {}
    fpv_grounded = focus_visibility_is_grounded(fpv_visibility, focus)
    verify_grounded = focus_visibility_is_grounded(verify_visibility, focus)
    return fpv_grounded and not verify_grounded


def default_focus_visibility_is_grounded(
    visibility: dict[str, Any],
    focus: dict[str, Any],
) -> bool:
    status = visibility.get("status")
    if status == "contained_inside":
        return True
    if status != "ok":
        return False
    if not (focus.get("object_id") or focus.get("object_body_name") or focus.get("object_label")):
        return True
    return int(visibility.get("object_pixels") or 0) > 0


def default_visual_grounding_status(
    focus: dict[str, Any],
    visibility: dict[str, Any],
    *,
    can_hide_contents: Callable[[dict[str, Any]], bool] | None = None,
) -> str:
    can_hide_contents = can_hide_contents or focus_receptacle_can_hide_contents
    receptacle_id = focus.get("receptacle_id")
    if (
        receptacle_id
        and focus.get("object_contained_in") == receptacle_id
        and focus.get("object_location_relation") == "inside"
        and can_hide_contents(focus)
    ):
        return "contained_inside"
    if not (focus.get("object_id") or focus.get("object_body_name") or focus.get("object_label")):
        return "ok"
    return "ok" if int(visibility.get("object_pixels") or 0) > 0 else "weak_object_visibility"


def focus_receptacle_can_hide_contents(focus: dict[str, Any]) -> bool:
    text = f"{focus.get('receptacle_label', '')} {focus.get('receptacle_category', '')}".lower()
    return "fridge" in text or "refrigerator" in text
