from __future__ import annotations

from pathlib import Path
from typing import Any

import mujoco

from roboclaws.backends.molmospaces import protocol, rendering

DEFAULT_RENDER_WIDTH = 540
DEFAULT_RENDER_HEIGHT = 360


def _apply_qpos(data: mujoco.MjData, qpos: list[float]) -> None:
    data.qpos[:] = qpos


def _optional_str(value: Any) -> str | None:
    return protocol.optional_str(value)


def _positive_int(value: Any, default: int, *, setting_name: str = "value") -> int:
    return protocol.positive_int(
        value,
        default,
        setting_name=setting_name,
    )


def _float_or_zero(value: Any, *, setting_name: str = "value") -> float:
    return protocol.float_or_zero(value, setting_name=setting_name)


def _json_object_from_text(text: str) -> dict[str, Any]:
    return protocol.json_object_from_text(text)


def _render_dimensions(width: int, height: int) -> tuple[int, int]:
    return rendering.render_dimensions(
        width,
        height,
        default_width=DEFAULT_RENDER_WIDTH,
        default_height=DEFAULT_RENDER_HEIGHT,
    )


def _shape_width(shape: Any) -> int:
    return rendering.shape_width(shape, default_width=DEFAULT_RENDER_WIDTH)


def _shape_height(shape: Any) -> int:
    return rendering.shape_height(shape, default_height=DEFAULT_RENDER_HEIGHT)


def _primary_body_name(info: dict[str, Any], *, fallback: str) -> str:
    bodies = info.get("name_map", {}).get("bodies", {})
    return next(iter(bodies), fallback)


def _friendly_name(category: str, upstream_id: Any) -> str:
    return f"{category} ({upstream_id})"


def _xyz(values: Any) -> list[float]:
    return [round(float(values[0]), 6), round(float(values[1]), 6), round(float(values[2]), 6)]


def _read_state(path: Path) -> dict[str, Any]:
    return protocol.read_state(path)


def _count(state: dict[str, Any], tool: str) -> None:
    protocol.count_tool_request(state, tool)


def _ok(tool: str, **payload: Any) -> dict[str, Any]:
    return protocol.ok_response(tool, **payload)


def _error(tool: str, error_reason: str, **payload: Any) -> dict[str, Any]:
    return protocol.error_response(tool, error_reason, **payload)
