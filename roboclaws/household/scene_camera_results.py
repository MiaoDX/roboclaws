from __future__ import annotations

from pathlib import Path
from typing import Any

MOLMOSPACES_LANE_ID = "molmospaces-mujoco"
ISAAC_LANE_ID = "isaaclab-prepared-usd"


def lane_order(manifest: dict[str, Any]) -> list[str]:
    lanes = manifest.get("lanes") if isinstance(manifest.get("lanes"), dict) else {}
    registry = (
        manifest.get("lane_registry") if isinstance(manifest.get("lane_registry"), dict) else {}
    )
    ordered: list[str] = []
    baseline = registry.get("baseline")
    if isinstance(baseline, str):
        ordered.append(baseline)
    candidates = registry.get("candidates") if isinstance(registry.get("candidates"), list) else []
    for lane_id in candidates:
        if isinstance(lane_id, str) and lane_id not in ordered:
            ordered.append(lane_id)
    for fallback in (MOLMOSPACES_LANE_ID, ISAAC_LANE_ID):
        if fallback in lanes and fallback not in ordered:
            ordered.append(fallback)
    for lane_id in lanes:
        if isinstance(lane_id, str) and lane_id not in ordered:
            ordered.append(lane_id)
    return ordered


def contact_sheet_entries(manifest: dict[str, Any], *, output_dir: Path) -> list[dict[str, Any]]:
    views = [
        item
        for item in manifest.get("canonical_camera_views") or []
        if isinstance(item, dict) and item.get("view_id")
    ]
    entries = []
    for view in views:
        view_id = str(view.get("view_id") or "")
        images: dict[str, Path] = {}
        for lane_id in lane_order(manifest):
            lane = (manifest.get("lanes") or {}).get(lane_id)
            if not isinstance(lane, dict):
                continue
            lane_images = lane.get("images") if isinstance(lane.get("images"), dict) else {}
            image = lane_images.get(view_id) if isinstance(lane_images, dict) else None
            if not isinstance(image, dict):
                continue
            path = output_dir / str(image.get("path") or "")
            if path.is_file():
                images[lane_id] = path
        if images:
            entries.append(
                {
                    "view_id": view_id,
                    "label": view.get("label") or view.get("category") or "",
                    "images": images,
                }
            )
    return entries
