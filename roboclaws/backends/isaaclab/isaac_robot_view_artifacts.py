"""Isaac Lab backend runtime support."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from PIL import Image


def real_robot_view_images(
    state: dict[str, Any],
    *,
    robot_view_keys: tuple[str, ...],
) -> dict[str, str]:
    images = {
        key: str(value)
        for key, value in _dict(state.get("robot_view_images")).items()
        if key in robot_view_keys and value
    }
    if has_required_robot_view_images(images, robot_view_keys=robot_view_keys):
        return images
    return {}


def real_smoke_robot_view_images(
    real_smoke: dict[str, Any] | None,
    *,
    robot_view_keys: tuple[str, ...],
) -> dict[str, str]:
    if real_smoke is None:
        return {}
    images = {
        key: str(value)
        for key, value in _dict(real_smoke.get("robot_view_images")).items()
        if key in robot_view_keys and value
    }
    if not has_required_robot_view_images(images, robot_view_keys=robot_view_keys):
        return {}
    return images if all(Path(value).is_file() for value in images.values()) else {}


def has_required_robot_view_images(
    images: dict[str, str],
    *,
    robot_view_keys: tuple[str, ...],
) -> bool:
    return all(bool(images.get(key)) for key in robot_view_keys)


def copy_real_robot_view_images(
    source_images: dict[str, str],
    target_images: dict[str, Path],
    *,
    width: int,
    height: int,
    robot_view_keys: tuple[str, ...],
) -> dict[str, list[int]]:
    shapes: dict[str, list[int]] = {}
    for key in robot_view_keys:
        source = Path(source_images[key])
        target = target_images[key]
        shapes[key] = copy_nonblank_rgb_image(
            source,
            target,
            width=width,
            height=height,
            description=f"real Isaac {key} view image",
        )
    return shapes


def real_snapshot_source_image(
    state: dict[str, Any],
    *,
    robot_view_keys: tuple[str, ...],
) -> Path:
    real_smoke = _dict(state.get("real_runtime_smoke"))
    image_path = str(real_smoke.get("image_path") or "")
    if image_path:
        return Path(image_path)
    robot_views = real_robot_view_images(state, robot_view_keys=robot_view_keys)
    fpv_path = str(robot_views.get("fpv") or "")
    if fpv_path:
        return Path(fpv_path)
    raise RuntimeError("real Isaac rendering is proven, but no RGB snapshot source is recorded")


def copy_real_snapshot_image(
    source: Path,
    target: Path,
    *,
    width: int,
    height: int,
) -> list[int]:
    return copy_nonblank_rgb_image(
        source,
        target,
        width=width,
        height=height,
        description="real Isaac snapshot source image",
    )


def copy_nonblank_rgb_image(
    source: Path,
    target: Path,
    *,
    width: int,
    height: int,
    description: str,
) -> list[int]:
    if not source.is_file():
        raise RuntimeError(f"missing {description}: {source}")
    target.parent.mkdir(parents=True, exist_ok=True)
    same_path = source.resolve() == target.resolve()
    with Image.open(source) as image:
        rgb = image.convert("RGB")
        if not pil_image_has_variance(rgb):
            raise RuntimeError(f"{description} appears blank: {source}")
        if not same_path and rgb.size != (width, height):
            rgb = rgb.resize((width, height))
        if not same_path:
            rgb.save(target)
        return [rgb.height, rgb.width, 3]


def pil_image_has_variance(image: Image.Image) -> bool:
    return any(high > low for low, high in image.getextrema())


def real_rendering_proven(state: dict[str, Any]) -> bool:
    rendering = _dict(_dict(state.get("runtime")).get("rendering"))
    return rendering.get("real_rendering_proven") is True


def robot_view_provenance(
    runtime_mode: str,
    real_smoke: dict[str, Any] | None,
    *,
    robot_view_keys: tuple[str, ...],
    real_robot_view_capture_method: str,
) -> dict[str, Any]:
    if has_required_robot_view_images(
        real_smoke_robot_view_images(real_smoke, robot_view_keys=robot_view_keys),
        robot_view_keys=robot_view_keys,
    ):
        method = str(real_smoke.get("robot_view_capture_method") or real_robot_view_capture_method)
        provenance = {key: f"{method}:{key}" for key in robot_view_keys}
        mounted_head_camera = bool(real_smoke.get("robot_view_uses_mounted_head_camera"))
        if mounted_head_camera:
            provenance["fpv"] = "isaac_lab_camera_rgb_robot_mounted_head_camera:fpv"
        else:
            provenance["fpv"] = "isaac_lab_camera_rgb_head_camera_equivalent:fpv"
        provenance["semantic_pose_state_refreshed"] = False
        provenance["canonical_camera_control"] = False
        provenance["robot_mounted_head_camera"] = mounted_head_camera
        provenance["head_camera_equivalent"] = not mounted_head_camera
        provenance["evidence_note"] = (
            "Robot-view images are static captures from the loaded USD scene during init. "
            "FPV uses the imported RBY1M mounted head camera when the robot USD import "
            "artifact is present; otherwise it is marked as a head-camera equivalent. "
            "Semantic pose edits are tracked in backend JSON state and are not rendered "
            "back into Isaac yet."
        )
        return provenance
    if runtime_mode == "real":
        provenance = {key: "isaac_robot_view_capture_pending" for key in robot_view_keys}
        provenance.update(
            {
                "semantic_pose_state_refreshed": False,
                "evidence_note": "Real Isaac robot-view captures were not recorded.",
            }
        )
        return provenance
    provenance = {key: "fake_protocol_placeholder_image" for key in robot_view_keys}
    provenance.update(
        {
            "semantic_pose_state_refreshed": False,
            "evidence_note": "CI fake mode writes deterministic placeholder robot-view images.",
        }
    )
    return provenance


def robot_view_command_provenance(
    state: dict[str, Any],
    *,
    semantic_pose_state_refreshed: bool,
    robot_view_keys: tuple[str, ...],
    real_robot_view_rerender_method: str,
) -> dict[str, Any]:
    if semantic_pose_state_refreshed:
        provenance = _dict(state.get("robot_view_provenance"))
        return semantic_pose_robot_view_provenance(
            mounted_head_camera=bool(
                provenance.get("robot_mounted_head_camera")
                or _dict(state.get("semantic_pose_view_capture")).get("robot_mounted_head_camera")
            ),
            head_camera_equivalent=bool(
                provenance.get("head_camera_equivalent")
                or _dict(state.get("semantic_pose_view_capture")).get("head_camera_equivalent")
            ),
            robot_view_keys=robot_view_keys,
            real_robot_view_rerender_method=real_robot_view_rerender_method,
        )
    return _dict(state.get("robot_view_provenance"))


def semantic_pose_robot_view_provenance(
    *,
    mounted_head_camera: bool = False,
    head_camera_equivalent: bool = False,
    robot_view_keys: tuple[str, ...],
    real_robot_view_rerender_method: str,
) -> dict[str, Any]:
    provenance = {key: f"{real_robot_view_rerender_method}:{key}" for key in robot_view_keys}
    if mounted_head_camera:
        provenance["fpv"] = "isaac_lab_camera_rgb_robot_mounted_head_camera:fpv"
    elif head_camera_equivalent:
        provenance["fpv"] = "isaac_lab_camera_rgb_head_camera_equivalent:fpv"
    provenance["semantic_pose_state_refreshed"] = True
    provenance["canonical_camera_control"] = False
    provenance["robot_mounted_head_camera"] = mounted_head_camera
    provenance["head_camera_equivalent"] = head_camera_equivalent
    provenance["evidence_note"] = (
        "Robot-view images were recaptured from the loaded USD scene after applying "
        "backend semantic pose state. FPV is either the imported RBY1M mounted head "
        "camera or an explicit head-camera-equivalent view; chase is a robot-relative "
        "rear/high report view and map remains auxiliary report evidence. "
        "This is still semantic pose rendering, not planner-backed or "
        "physics-backed manipulation."
    )
    return provenance


def _dict(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}
