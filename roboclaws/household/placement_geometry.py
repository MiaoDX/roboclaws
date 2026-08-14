"""Backend-neutral geometry for placing objects on support surfaces."""

from __future__ import annotations

from typing import Any


def surface_candidate_positions(
    surface: dict[str, Any],
    *,
    footprint: tuple[float, float],
    bottom_offset: float,
    clearance: float,
    index: int,
) -> list[list[float]]:
    center = surface["center"]
    half_extents = surface["half_extents"]
    margin_x = float(footprint[0]) + 0.04
    margin_y = float(footprint[1]) + 0.04
    available_x = max(float(half_extents[0]) - margin_x, 0.0)
    available_y = max(float(half_extents[1]) - margin_y, 0.0)
    slot_x = min(available_x * 0.55, 0.28)
    slot_y = min(available_y * 0.55, 0.28)
    offsets = [
        (0.0, 0.0),
        (-slot_x, 0.0),
        (slot_x, 0.0),
        (0.0, -slot_y),
        (0.0, slot_y),
        (-slot_x, -slot_y),
        (slot_x, -slot_y),
        (-slot_x, slot_y),
        (slot_x, slot_y),
    ]
    if len(offsets) > 1:
        shift = index % len(offsets)
        offsets = offsets[shift:] + offsets[:shift]
    z = float(surface["top_z"]) + float(bottom_offset) + float(clearance)
    return [
        [
            round(float(center[0]) + float(dx), 6),
            round(float(center[1]) + float(dy), 6),
            round(z, 6),
        ]
        for dx, dy in offsets
    ]


def candidate_has_direct_support(
    position: list[float],
    surface: dict[str, Any],
    footprint: tuple[float, float],
) -> bool:
    center = surface["center"]
    half_extents = surface["half_extents"]
    margin_x = float(footprint[0]) + 0.015
    margin_y = float(footprint[1]) + 0.015
    return abs(float(position[0]) - float(center[0])) + margin_x <= float(half_extents[0]) and abs(
        float(position[1]) - float(center[1])
    ) + margin_y <= float(half_extents[1])


def aabb_xy_overlaps(
    first: tuple[float, float, float, float],
    second: dict[str, float],
    *,
    margin: float,
) -> bool:
    min_x, max_x, min_y, max_y = first
    return (
        min_x - margin <= float(second["max_x"])
        and max_x + margin >= float(second["min_x"])
        and min_y - margin <= float(second["max_y"])
        and max_y + margin >= float(second["min_y"])
    )


def elevated_position_over_surface(
    surface: dict[str, Any],
    *,
    bottom_offset: float,
) -> list[float]:
    center = surface["center"]
    return [
        round(float(center[0]), 6),
        round(float(center[1]), 6),
        round(float(surface["top_z"]) + float(bottom_offset) + 0.08, 6),
    ]
