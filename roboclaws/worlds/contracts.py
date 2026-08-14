"""Immutable world selection contracts consumed by launch."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from types import MappingProxyType
from typing import Any


def _freeze(value: Any) -> Any:
    if isinstance(value, Mapping):
        return MappingProxyType({str(key): _freeze(item) for key, item in value.items()})
    if isinstance(value, (list, tuple)):
        return tuple(_freeze(item) for item in value)
    return value


@dataclass(frozen=True)
class WorldSpec:
    """A fully immutable room, map, site, or scene selected before launch."""

    id: str
    label: str
    surface_id: str
    available_backends: tuple[str, ...]
    scene_source: str
    tags: tuple[str, ...]
    default_backend: str
    resource_kind: str
    availability: str = "enabled"
    optional_validation: bool = False
    default_overrides: tuple[str, ...] = ()
    preview_assets: tuple[tuple[str, str], ...] = ()
    sampler_metadata: Mapping[str, object] | None = None

    def __post_init__(self) -> None:
        if self.sampler_metadata is not None:
            object.__setattr__(self, "sampler_metadata", _freeze(self.sampler_metadata))
