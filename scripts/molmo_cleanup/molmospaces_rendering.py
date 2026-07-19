from __future__ import annotations

from pathlib import Path
from typing import Any, Callable

import mujoco
from PIL import Image


def render_fixed_camera(
    model: mujoco.MjModel,
    data: mujoco.MjData,
    camera_name: str,
    *,
    width: int,
    height: int,
    render_dimensions: Callable[[int, int], tuple[int, int]],
    ensure_offscreen_framebuffer: Callable[..., None],
) -> Any:
    width, height = render_dimensions(width, height)
    ensure_offscreen_framebuffer(model, width=width, height=height)
    renderer = mujoco.Renderer(model, height=height, width=width, max_geom=20000)
    renderer.update_scene(data, camera=camera_name)
    frame = renderer.render()
    renderer.close()
    return frame


def fixed_camera_diagnostics(
    model: mujoco.MjModel,
    data: mujoco.MjData,
    camera_name: str,
) -> dict[str, Any]:
    try:
        camera_id = mujoco.mj_name2id(model, mujoco.mjtObj.mjOBJ_CAMERA, camera_name)
        if camera_id < 0:
            return {
                "schema": "mujoco_fixed_camera_diagnostics_v1",
                "status": "missing_camera",
                "camera_name": camera_name,
            }
        world_position = _array_row(getattr(data, "cam_xpos"), camera_id, 3)
        world_xmat = _array_row(getattr(data, "cam_xmat"), camera_id, 9)
        return {
            "schema": "mujoco_fixed_camera_diagnostics_v1",
            "status": "ready",
            "camera_name": camera_name,
            "camera_id": int(camera_id),
            "camera_type": "fixed",
            "world_position": world_position,
            "world_xmat_rowmajor": world_xmat,
            "fovy_deg": _array_scalar(getattr(model, "cam_fovy", None), camera_id),
            "model_pos": _array_row(getattr(model, "cam_pos"), camera_id, 3),
            "model_quat_wxyz": _array_row(getattr(model, "cam_quat"), camera_id, 4),
            "znear": _optional_float(getattr(getattr(model, "vis", None), "map", None), "znear"),
            "zfar": _optional_float(getattr(getattr(model, "vis", None), "map", None), "zfar"),
        }
    except Exception as exc:
        return {
            "schema": "mujoco_fixed_camera_diagnostics_v1",
            "status": "unavailable",
            "camera_name": camera_name,
            "reason": f"{type(exc).__name__}: {exc}",
        }


def free_camera_diagnostics(camera: mujoco.MjvCamera) -> dict[str, Any]:
    try:
        return {
            "schema": "mujoco_free_camera_diagnostics_v1",
            "status": "ready",
            "camera_type": "free",
            "lookat": [round(float(value), 6) for value in camera.lookat],
            "distance": round(float(camera.distance), 6),
            "azimuth": round(float(camera.azimuth), 6),
            "elevation": round(float(camera.elevation), 6),
        }
    except Exception as exc:
        return {
            "schema": "mujoco_free_camera_diagnostics_v1",
            "status": "unavailable",
            "reason": f"{type(exc).__name__}: {exc}",
        }


def render_free_camera(
    model: mujoco.MjModel,
    data: mujoco.MjData,
    camera: mujoco.MjvCamera,
    *,
    width: int,
    height: int,
    render_dimensions: Callable[[int, int], tuple[int, int]],
    ensure_offscreen_framebuffer: Callable[..., None],
) -> Any:
    width, height = render_dimensions(width, height)
    ensure_offscreen_framebuffer(model, width=width, height=height)
    renderer = mujoco.Renderer(model, height=height, width=width, max_geom=20000)
    renderer.update_scene(data, camera=camera)
    frame = renderer.render()
    renderer.close()
    return frame


def load_rendered_robot_view_image(camera_views: dict[str, Any], *, role: str) -> Any:
    for item in camera_views.get("views") or []:
        if not isinstance(item, dict) or item.get("robot_view_role") != role:
            continue
        image_path = Path(str(item.get("image_path") or ""))
        if not image_path.is_file():
            raise RuntimeError(f"missing rendered {role} camera-control image: {image_path}")
        return image_to_array(image_path)
    raise RuntimeError(f"missing rendered {role} camera-control view")


def image_to_array(path: Path) -> Any:
    import numpy as np

    with Image.open(path) as image:
        return np.asarray(image.convert("RGB")).copy()


def focus_visibility(
    model: mujoco.MjModel,
    data: mujoco.MjData,
    camera: mujoco.MjvCamera | str,
    focus: dict[str, Any],
    *,
    frame: Any | None,
    render_segmentation: Callable[..., Any],
    segmentation_box: Callable[..., dict[str, Any] | None],
    highlight_diff_box: Callable[..., dict[str, Any] | None],
    shape_width: Callable[[Any], int],
    shape_height: Callable[[Any], int],
) -> dict[str, Any]:
    boxes = []
    object_pixels = 0
    receptacle_pixels = 0
    try:
        render_shape = frame.shape if frame is not None and hasattr(frame, "shape") else None
        segmentation = render_segmentation(
            model,
            data,
            camera,
            width=shape_width(render_shape),
            height=shape_height(render_shape),
        )
    except Exception as exc:  # pragma: no cover - depends on MuJoCo renderer internals
        return {
            "status": "segmentation_unavailable",
            "error": type(exc).__name__,
            "object_pixels": 0,
            "receptacle_pixels": 0,
            "boxes": [],
        }
    if focus.get("object_body_name"):
        box = segmentation_box(
            model,
            segmentation,
            focus["object_body_name"],
            label=str(focus.get("object_label") or "object"),
            color=[239, 68, 68],
        )
        if focus.get("object_category") == "RemoteControl" and (
            box is None or int(box.get("pixels") or 0) < 20
        ):
            highlight_box = highlight_diff_box(
                model,
                data,
                camera,
                focus["object_body_name"],
                label=str(focus.get("object_label") or "object"),
                color=[239, 68, 68],
                frame=frame,
            )
            if highlight_box is not None and (
                box is None or int(highlight_box.get("pixels") or 0) > int(box.get("pixels") or 0)
            ):
                box = highlight_box
        if box is not None:
            object_pixels = int(box["pixels"])
            boxes.append(box)
    if focus.get("receptacle_body_name"):
        box = segmentation_box(
            model,
            segmentation,
            focus["receptacle_body_name"],
            label=str(focus.get("receptacle_label") or "target"),
            color=[8, 145, 178],
        )
        if box is not None:
            receptacle_pixels = int(box["pixels"])
            boxes.append(box)
    return {
        "status": "ok",
        "object_pixels": object_pixels,
        "receptacle_pixels": receptacle_pixels,
        "boxes": boxes,
    }


def render_segmentation(
    model: mujoco.MjModel,
    data: mujoco.MjData,
    camera: mujoco.MjvCamera | str,
    *,
    width: int,
    height: int,
    render_dimensions: Callable[[int, int], tuple[int, int]],
    ensure_offscreen_framebuffer: Callable[..., None],
) -> Any:
    width, height = render_dimensions(width, height)
    ensure_offscreen_framebuffer(model, width=width, height=height)
    renderer = mujoco.Renderer(model, height=height, width=width, max_geom=20000)
    renderer.update_scene(data, camera=camera)
    renderer.render()
    renderer.enable_segmentation_rendering()
    renderer.update_scene(data, camera=camera)
    segmentation = renderer.render()
    renderer.close()
    return segmentation


def segmentation_box(
    model: mujoco.MjModel,
    segmentation: Any,
    body_name: str,
    *,
    label: str,
    color: list[int],
    subtree_geom_ids: Callable[[mujoco.MjModel, str], list[int]],
    inflate_bbox: Callable[..., tuple[int, int, int, int]],
) -> dict[str, Any] | None:
    geom_ids = subtree_geom_ids(model, body_name)
    if not geom_ids:
        return None
    import numpy as np

    mask = np.isin(segmentation[:, :, 0], geom_ids) & (
        segmentation[:, :, 1] == int(mujoco.mjtObj.mjOBJ_GEOM)
    )
    pixels = int(mask.sum())
    if pixels <= 0:
        return None
    ys, xs = np.where(mask)
    left, right = int(xs.min()), int(xs.max())
    top, bottom = int(ys.min()), int(ys.max())
    left, top, right, bottom = inflate_bbox(left, top, right, bottom, segmentation.shape)
    return {
        "label": label,
        "bbox": [left, top, right, bottom],
        "pixels": pixels,
        "color": color,
        "source": "segmentation",
    }


def highlight_diff_box(
    model: mujoco.MjModel,
    data: mujoco.MjData,
    camera: mujoco.MjvCamera | str,
    body_name: str,
    *,
    label: str,
    color: list[int],
    frame: Any | None,
    subtree_geom_ids: Callable[[mujoco.MjModel, str], list[int]],
    render_color_frame: Callable[..., Any],
    shape_width: Callable[[Any], int],
    shape_height: Callable[[Any], int],
    inflate_bbox: Callable[..., tuple[int, int, int, int]],
) -> dict[str, Any] | None:
    geom_ids = subtree_geom_ids(model, body_name)
    if not geom_ids:
        return None
    import numpy as np

    render_shape = frame.shape if frame is not None and hasattr(frame, "shape") else None
    baseline = frame if frame is not None else render_color_frame(model, data, camera)
    baseline = np.asarray(baseline)
    previous_rgba = model.geom_rgba[geom_ids].copy()
    previous_matid = model.geom_matid[geom_ids].copy()
    try:
        for geom_id in geom_ids:
            model.geom_rgba[geom_id] = np.array([1.0, 0.0, 1.0, 1.0])
            model.geom_matid[geom_id] = -1
        highlighted = render_color_frame(
            model,
            data,
            camera,
            width=shape_width(render_shape or baseline.shape),
            height=shape_height(render_shape or baseline.shape),
        )
    finally:
        model.geom_rgba[geom_ids] = previous_rgba
        model.geom_matid[geom_ids] = previous_matid
    diff = np.abs(np.asarray(highlighted, dtype=np.int16) - baseline.astype(np.int16)).max(axis=2)
    mask = diff > 35
    pixels = int(mask.sum())
    if pixels <= 0:
        return None
    ys, xs = np.where(mask)
    left, right = int(xs.min()), int(xs.max())
    top, bottom = int(ys.min()), int(ys.max())
    left, top, right, bottom = inflate_bbox(left, top, right, bottom, baseline.shape)
    return {
        "label": label,
        "bbox": [left, top, right, bottom],
        "pixels": pixels,
        "color": color,
        "source": "highlight_diff",
    }


def render_color_frame(
    model: mujoco.MjModel,
    data: mujoco.MjData,
    camera: mujoco.MjvCamera | str,
    *,
    width: int,
    height: int,
    render_dimensions: Callable[[int, int], tuple[int, int]],
    ensure_offscreen_framebuffer: Callable[..., None],
) -> Any:
    width, height = render_dimensions(width, height)
    ensure_offscreen_framebuffer(model, width=width, height=height)
    renderer = mujoco.Renderer(model, height=height, width=width, max_geom=20000)
    renderer.update_scene(data, camera=camera)
    frame = renderer.render()
    renderer.close()
    return frame


def ensure_offscreen_framebuffer(
    model: mujoco.MjModel,
    *,
    width: int,
    height: int,
) -> None:
    """Grow MuJoCo's offscreen buffer so requested high-res renders are valid."""
    global_settings = getattr(getattr(model, "vis", None), "global_", None)
    if global_settings is None:
        return
    if int(getattr(global_settings, "offwidth", 0) or 0) < int(width):
        global_settings.offwidth = int(width)
    if int(getattr(global_settings, "offheight", 0) or 0) < int(height):
        global_settings.offheight = int(height)


def subtree_geom_ids(
    model: mujoco.MjModel,
    body_name: str,
    *,
    subtree_body_ids: Callable[[mujoco.MjModel, str], list[int]],
) -> list[int]:
    body_ids = subtree_body_ids(model, body_name)
    return [
        geom_id
        for geom_id in range(model.ngeom)
        if int(model.geom_bodyid[geom_id]) in set(body_ids)
    ]


def subtree_body_ids(model: mujoco.MjModel, body_name: str) -> list[int]:
    body_id = mujoco.mj_name2id(model, mujoco.mjtObj.mjOBJ_BODY, body_name)
    if body_id < 0:
        return []
    body_ids = []
    for candidate_id in range(model.nbody):
        current_id = candidate_id
        while current_id > 0:
            if current_id == body_id:
                body_ids.append(candidate_id)
                break
            current_id = int(model.body_parentid[current_id])
    return body_ids


def inflate_bbox(
    left: int,
    top: int,
    right: int,
    bottom: int,
    shape: Any,
    *,
    min_size: int = 32,
    pad: int = 8,
) -> tuple[int, int, int, int]:
    height, width = int(shape[0]), int(shape[1])
    center_x = (left + right) // 2
    center_y = (top + bottom) // 2
    half_width = max((right - left) // 2 + pad, min_size // 2)
    half_height = max((bottom - top) // 2 + pad, min_size // 2)
    clipped_left = max(0, center_x - half_width)
    clipped_top = max(29, center_y - half_height)
    clipped_right = min(width - 1, center_x + half_width)
    clipped_bottom = min(height - 1, center_y + half_height)
    return (
        min(clipped_left, clipped_right),
        clipped_top,
        clipped_right,
        max(clipped_top, clipped_bottom),
    )


def render_dimensions(
    width: int,
    height: int,
    *,
    default_width: int,
    default_height: int,
) -> tuple[int, int]:
    return (
        _positive_int(width, default_width),
        _positive_int(height, default_height),
    )


def shape_width(shape: Any, *, default_width: int) -> int:
    if isinstance(shape, (tuple, list)) and len(shape) >= 2:
        return _positive_int(shape[1], default_width)
    return default_width


def shape_height(shape: Any, *, default_height: int) -> int:
    if isinstance(shape, (tuple, list)) and len(shape) >= 1:
        return _positive_int(shape[0], default_height)
    return default_height


def _array_row(array: Any, index: int, length: int) -> list[float]:
    return [round(float(value), 6) for value in array[index][:length]]


def _array_scalar(array: Any, index: int) -> float | None:
    if array is None:
        return None
    return round(float(array[index]), 6)


def _optional_float(parent: Any, attribute: str) -> float | None:
    if parent is None or not hasattr(parent, attribute):
        return None
    try:
        return round(float(getattr(parent, attribute)), 6)
    except (TypeError, ValueError):
        return None


def _positive_int(value: Any, default: int) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return default
    return parsed if parsed > 0 else default
