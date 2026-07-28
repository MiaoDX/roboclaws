from __future__ import annotations

from pathlib import Path
from typing import Any


def dimensions_from_shape(shape: Any) -> dict[str, int]:
    if not isinstance(shape, list) or len(shape) < 2:
        return {}
    try:
        height = int(shape[0])
        width = int(shape[1])
        dimensions = {"width": width, "height": height}
        if len(shape) >= 3:
            dimensions["channels"] = int(shape[2])
        return dimensions
    except (TypeError, ValueError):
        return {}


def output_relpath(path: Path, output_dir: Path) -> str:
    try:
        return str(path.resolve().relative_to(output_dir.resolve()))
    except ValueError:
        return str(path)


def home_relative_path(value: str) -> str:
    """Make paths below the current home portable without changing other values."""
    if not value:
        return value
    path = Path(value)
    if not path.is_absolute():
        return value
    try:
        relative = path.relative_to(Path.home())
    except ValueError:
        return value
    return (Path("~") / relative).as_posix()


def home_relative_paths(value: Any) -> Any:
    if isinstance(value, str):
        return home_relative_path(value)
    if isinstance(value, dict):
        return {key: home_relative_paths(item) for key, item in value.items()}
    if isinstance(value, list):
        return [home_relative_paths(item) for item in value]
    if isinstance(value, tuple):
        return tuple(home_relative_paths(item) for item in value)
    return value


def resolve_home_relative_path(value: str) -> str:
    if value == "~":
        return str(Path.home())
    if value.startswith("~/"):
        return str(Path.home() / value.removeprefix("~/"))
    return value


def resolve_home_relative_paths(value: Any) -> Any:
    if isinstance(value, str):
        return resolve_home_relative_path(value)
    if isinstance(value, dict):
        return {key: resolve_home_relative_paths(item) for key, item in value.items()}
    if isinstance(value, list):
        return [resolve_home_relative_paths(item) for item in value]
    if isinstance(value, tuple):
        return tuple(resolve_home_relative_paths(item) for item in value)
    return value
