from __future__ import annotations

from pathlib import Path
from typing import Any

TOPDOWN_RENDER_SCHEMA = "b1_scene_gaussian_topdown_render_v1"
SCENE_TOPDOWN_PICK_SOURCE = "rendered_gaussian_scene_topdown_ray_plane_pick"


def validate_topdown_render_packet(packet: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    if packet.get("schema") != TOPDOWN_RENDER_SCHEMA:
        errors.append("unexpected topdown render schema")
    if packet.get("geometry_status") != "rendered_gaussian_scene_topdown":
        errors.append("topdown render must be captured before review")
    image = Path(str(packet.get("topdown_image") or ""))
    if not image.is_file():
        errors.append("topdown render image missing")
    if int(packet.get("width_px") or 0) <= 0 or int(packet.get("height_px") or 0) <= 0:
        errors.append("topdown render image size missing")
    if packet.get("up_axis") != "z":
        errors.append("topdown render must record up_axis=z")
    if packet.get("horizontal_axes") != ["x", "y"]:
        errors.append("topdown render must record horizontal_axes=[x,y]")
    transform = packet.get("pixel_to_scene_xyz")
    if not isinstance(transform, dict):
        errors.append("topdown render missing pixel_to_scene_xyz")
    elif transform.get("source") != SCENE_TOPDOWN_PICK_SOURCE:
        errors.append("topdown render has unexpected pixel_to_scene_xyz source")
    return errors
