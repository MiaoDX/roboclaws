from __future__ import annotations

from pathlib import Path
from typing import Any

import mujoco
from PIL import Image

from roboclaws.backends.molmospaces import capture, focus_camera, navigation, rendering, room_map
from roboclaws.backends.molmospaces.common import (
    DEFAULT_RENDER_HEIGHT,
    DEFAULT_RENDER_WIDTH,
    _render_dimensions,
    _shape_height,
    _shape_width,
    _xyz,
)
from roboclaws.core.json_sources import read_json_value
from roboclaws.household.camera_control import (
    load_camera_control_request,
    normalize_camera_control_request,
)


def _render_fixed_camera(
    model: mujoco.MjModel,
    data: mujoco.MjData,
    camera_name: str,
    *,
    width: int = DEFAULT_RENDER_WIDTH,
    height: int = DEFAULT_RENDER_HEIGHT,
) -> Any:
    return rendering.render_fixed_camera(
        model,
        data,
        camera_name,
        width=width,
        height=height,
        render_dimensions=_render_dimensions,
        ensure_offscreen_framebuffer=_ensure_offscreen_framebuffer,
    )


def _fixed_camera_diagnostics(
    model: mujoco.MjModel,
    data: mujoco.MjData,
    camera_name: str,
) -> dict[str, Any]:
    return rendering.fixed_camera_diagnostics(model, data, camera_name)


def _free_camera_diagnostics(camera: mujoco.MjvCamera) -> dict[str, Any]:
    return rendering.free_camera_diagnostics(camera)


def _focus_camera(state: dict[str, Any], focus: dict[str, Any]) -> mujoco.MjvCamera:
    return focus_camera.focus_camera(
        state,
        focus,
        scene_focus_position=_scene_focus_position,
        focus_camera_azimuth=_focus_camera_azimuth,
    )


def _render_free_camera(
    model: mujoco.MjModel,
    data: mujoco.MjData,
    camera: mujoco.MjvCamera,
    *,
    width: int = DEFAULT_RENDER_WIDTH,
    height: int = DEFAULT_RENDER_HEIGHT,
) -> Any:
    return rendering.render_free_camera(
        model,
        data,
        camera,
        width=width,
        height=height,
        render_dimensions=_render_dimensions,
        ensure_offscreen_framebuffer=_ensure_offscreen_framebuffer,
    )


def _load_rendered_robot_view_image(camera_views: dict[str, Any], *, role: str) -> Any:
    return rendering.load_rendered_robot_view_image(camera_views, role=role)


def _image_to_array(path: Path) -> Any:
    return rendering.image_to_array(path)


def _load_camera_view_specs(path: Path) -> list[dict[str, Any]]:
    payload = read_json_value(path, label="camera view spec")
    raw_views = payload.get("views") if isinstance(payload, dict) else payload
    if not isinstance(raw_views, list):
        raise ValueError("camera view spec must be a list or an object with a views list")
    return [dict(item) for item in raw_views if isinstance(item, dict)]


def _load_camera_request_from_args(
    *,
    view_specs_path: Path | None,
    camera_request_path: Path | None,
    width: int,
    height: int,
) -> dict[str, Any]:
    if camera_request_path is not None:
        return load_camera_control_request(camera_request_path, width=width, height=height)
    if view_specs_path is not None:
        return normalize_camera_control_request(
            _load_camera_view_specs(view_specs_path),
            width=width,
            height=height,
        )
    raise ValueError("camera_views requires --camera-request-path or --view-specs-path")


def _load_camera_request_from_kwargs(
    kwargs: dict[str, Any],
    *,
    width: int,
    height: int,
) -> dict[str, Any]:
    camera_request_path = kwargs.get("camera_request_path")
    if camera_request_path:
        return load_camera_control_request(
            Path(str(camera_request_path)), width=width, height=height
        )
    view_specs_path = kwargs.get("view_specs_path")
    if view_specs_path:
        return normalize_camera_control_request(
            _load_camera_view_specs(Path(str(view_specs_path))),
            width=width,
            height=height,
        )
    raise ValueError("camera_views requires camera_request_path or view_specs_path")


def _camera_view_spec(raw_spec: dict[str, Any], *, index: int) -> dict[str, Any]:
    return focus_camera.camera_view_spec(raw_spec, index=index)


def _lane_camera_orbit(raw_spec: dict[str, Any], lane_id: str) -> dict[str, Any]:
    return focus_camera.lane_camera_orbit(raw_spec, lane_id)


def _camera_request_variant(camera_request: dict[str, Any]) -> str:
    return capture.camera_request_variant(camera_request)


def _camera_request_provenance(camera_request: dict[str, Any]) -> str:
    return capture.camera_request_provenance(camera_request)


def _camera_vec3(value: Any, *, field_name: str = "camera vector") -> list[float]:
    return focus_camera.camera_vec3(value, field_name=field_name)


def _eye_from_mujoco_free_camera(
    *,
    lookat: list[float],
    distance: float,
    azimuth: float,
    elevation: float,
) -> list[float]:
    return focus_camera.eye_from_mujoco_free_camera(
        lookat=lookat,
        distance=distance,
        azimuth=azimuth,
        elevation=elevation,
    )


def _free_camera_from_lookat_spec(spec: dict[str, Any]) -> mujoco.MjvCamera:
    return focus_camera.free_camera_from_lookat_spec(spec)


def _camera_from_view_spec(state: dict[str, Any], spec: dict[str, Any]) -> mujoco.MjvCamera:
    return focus_camera.camera_from_view_spec(
        state,
        spec,
        free_camera_from_lookat_spec=_free_camera_from_lookat_spec,
        focus_payload=_focus_payload,
        focus_camera=_focus_camera,
    )


def _annotate_focus_image(image: Image.Image, focus: dict[str, Any]) -> None:
    focus_camera.annotate_focus_image(image, focus)


def _focus_camera_azimuth(
    state: dict[str, Any],
    focus_position: list[float],
    focus: dict[str, Any] | None = None,
) -> float:
    return focus_camera.default_focus_camera_azimuth(state, focus_position, focus)


def _focus_payload(
    state: dict[str, Any],
    focus_object_id: str | None,
    focus_receptacle_id: str | None,
) -> dict[str, Any]:
    return focus_camera.focus_payload(
        state,
        focus_object_id,
        focus_receptacle_id,
        label_item=_item_label,
        average_position=_average_position,
        scene_focus_position=_scene_focus_position,
    )


def _average_position(positions: list[list[float]]) -> list[float]:
    return focus_camera.default_average_position(positions)


def _scene_focus_position(state: dict[str, Any]) -> list[float]:
    return focus_camera.default_scene_focus_position(state)


def _item_label(item: dict[str, Any] | None, id_key: str) -> str:
    return room_map.item_label(item, id_key)


def _focus_visibility(
    model: mujoco.MjModel,
    data: mujoco.MjData,
    camera: mujoco.MjvCamera | str,
    focus: dict[str, Any],
    *,
    frame: Any | None = None,
) -> dict[str, Any]:
    return rendering.focus_visibility(
        model,
        data,
        camera,
        focus,
        frame=frame,
        render_segmentation=_render_segmentation,
        segmentation_box=_segmentation_box,
        highlight_diff_box=_highlight_diff_box,
        shape_width=_shape_width,
        shape_height=_shape_height,
    )


def _annotate_focus_visual_grounding(focus: dict[str, Any]) -> dict[str, Any]:
    return focus_camera.annotate_focus_visual_grounding(
        focus,
        visual_grounding_status=_visual_grounding_status,
    )


def _should_use_fpv_as_verify_focus(focus: dict[str, Any]) -> bool:
    return focus_camera.should_use_fpv_as_verify_focus(
        focus,
        focus_visibility_is_grounded=_focus_visibility_is_grounded,
    )


def _focus_visibility_is_grounded(
    visibility: dict[str, Any],
    focus: dict[str, Any],
) -> bool:
    return focus_camera.default_focus_visibility_is_grounded(visibility, focus)


def _visual_grounding_status(focus: dict[str, Any], visibility: dict[str, Any]) -> str:
    return focus_camera.default_visual_grounding_status(
        focus,
        visibility,
        can_hide_contents=_focus_receptacle_can_hide_contents,
    )


def _focus_receptacle_can_hide_contents(focus: dict[str, Any]) -> bool:
    return focus_camera.focus_receptacle_can_hide_contents(focus)


def _render_segmentation(
    model: mujoco.MjModel,
    data: mujoco.MjData,
    camera: mujoco.MjvCamera | str,
    *,
    width: int = DEFAULT_RENDER_WIDTH,
    height: int = DEFAULT_RENDER_HEIGHT,
) -> Any:
    return rendering.render_segmentation(
        model,
        data,
        camera,
        width=width,
        height=height,
        render_dimensions=_render_dimensions,
        ensure_offscreen_framebuffer=_ensure_offscreen_framebuffer,
    )


def _segmentation_box(
    model: mujoco.MjModel,
    segmentation: Any,
    body_name: str,
    *,
    label: str,
    color: list[int],
) -> dict[str, Any] | None:
    return rendering.segmentation_box(
        model,
        segmentation,
        body_name,
        label=label,
        color=color,
        subtree_geom_ids=_subtree_geom_ids,
        inflate_bbox=_inflate_bbox,
    )


def _highlight_diff_box(
    model: mujoco.MjModel,
    data: mujoco.MjData,
    camera: mujoco.MjvCamera | str,
    body_name: str,
    *,
    label: str,
    color: list[int],
    frame: Any | None,
) -> dict[str, Any] | None:
    return rendering.highlight_diff_box(
        model,
        data,
        camera,
        body_name,
        label=label,
        color=color,
        frame=frame,
        subtree_geom_ids=_subtree_geom_ids,
        render_color_frame=_render_color_frame,
        shape_width=_shape_width,
        shape_height=_shape_height,
        inflate_bbox=_inflate_bbox,
    )


def _render_color_frame(
    model: mujoco.MjModel,
    data: mujoco.MjData,
    camera: mujoco.MjvCamera | str,
    *,
    width: int = DEFAULT_RENDER_WIDTH,
    height: int = DEFAULT_RENDER_HEIGHT,
) -> Any:
    return rendering.render_color_frame(
        model,
        data,
        camera,
        width=width,
        height=height,
        render_dimensions=_render_dimensions,
        ensure_offscreen_framebuffer=_ensure_offscreen_framebuffer,
    )


def _ensure_offscreen_framebuffer(
    model: mujoco.MjModel,
    *,
    width: int,
    height: int,
) -> None:
    rendering.ensure_offscreen_framebuffer(model, width=width, height=height)


def _subtree_geom_ids(model: mujoco.MjModel, body_name: str) -> list[int]:
    return rendering.subtree_geom_ids(model, body_name, subtree_body_ids=_subtree_body_ids)


def _subtree_body_ids(model: mujoco.MjModel, body_name: str) -> list[int]:
    return rendering.subtree_body_ids(model, body_name)


def _inflate_bbox(
    left: int,
    top: int,
    right: int,
    bottom: int,
    shape: Any,
    *,
    min_size: int = 32,
    pad: int = 8,
) -> tuple[int, int, int, int]:
    return rendering.inflate_bbox(
        left,
        top,
        right,
        bottom,
        shape,
        min_size=min_size,
        pad=pad,
    )


def _render_robot_map(state: dict[str, Any], *, focus: dict[str, Any] | None = None) -> Image.Image:
    return room_map.render_robot_map(state, focus=focus)


def _map_points(state: dict[str, Any], focus: dict[str, Any]) -> list[list[float]]:
    return room_map.map_points(state, focus)


def _room_relation_payload(
    state: dict[str, Any],
    receptacle: dict[str, Any],
    robot_point: list[float],
) -> dict[str, Any]:
    return navigation.room_relation_payload(state, receptacle, robot_point)


def _target_room_id(state: dict[str, Any], receptacle: dict[str, Any]) -> str:
    return navigation.target_room_id_for_receptacle(state, receptacle)


def _room_outline_for_id(
    state: dict[str, Any],
    room_id: Any,
) -> dict[str, Any] | None:
    return navigation.room_outline_for_id(state, room_id)


def _room_for_point(state: dict[str, Any], point: list[float]) -> str | None:
    return navigation.room_for_state_point(state, point)


def _point_inside_outline(
    point: list[float],
    outline: dict[str, Any],
    *,
    margin: float,
) -> bool:
    return navigation.point_inside_outline(point, outline, margin=margin)


def _outline_clearance(point: list[float], outline: dict[str, Any] | None) -> float:
    return navigation.outline_clearance(point, outline)


def _angle_delta(a: float, b: float) -> float:
    return navigation.angle_delta_value(a, b)


def _collect_room_outlines(
    model: mujoco.MjModel,
    data: mujoco.MjData,
    state: dict[str, Any],
) -> list[dict[str, Any]]:
    return room_map.collect_room_outlines(model, data, state, xyz=_xyz)


def _geom_xy_bounds(
    model: mujoco.MjModel,
    data: mujoco.MjData,
    geom_id: int,
) -> tuple[list[float], list[float]] | None:
    return room_map.geom_xy_bounds(model, data, geom_id, xyz=_xyz)


def _fallback_room_outlines(state: dict[str, Any]) -> list[dict[str, Any]]:
    return room_map.fallback_room_outlines(state)


def _map_bounds(points: list[list[float]]) -> tuple[float, float, float, float]:
    return room_map.map_bounds(points)
