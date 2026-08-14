"""Canonical MolmoSpaces world identifiers."""

from __future__ import annotations

from roboclaws.worlds.molmospaces.contracts import MolmoSpacesSceneRef

SUPPORTED_SCENE_SOURCES: tuple[str, ...] = (
    "procthor-10k-val",
    "ithor",
    "procthor-objaverse-val",
    "holodeck-objaverse-val",
)


def parse_molmospaces_world_id(world_id: str) -> MolmoSpacesSceneRef:
    """Parse a source-aware ``molmospaces/<scene_source>/<index>`` world id."""

    legacy_prefix = "molmospaces/val_"
    if world_id.startswith(legacy_prefix):
        index = _parse_scene_index(world_id.removeprefix(legacy_prefix), world_id=world_id)
        raise ValueError(
            f"legacy MolmoSpaces world id {world_id!r} is unsupported; "
            f"use 'molmospaces/procthor-10k-val/{index}'"
        )

    parts = world_id.split("/")
    if len(parts) == 3 and parts[0] == "molmospaces":
        scene_source = parts[1]
        if scene_source not in SUPPORTED_SCENE_SOURCES:
            raise ValueError(f"unsupported MolmoSpaces scene_source {scene_source!r}: {world_id}")
        return MolmoSpacesSceneRef(
            scene_source=scene_source,
            scene_index=_parse_scene_index(parts[2], world_id=world_id),
        )

    raise ValueError(f"unsupported world {world_id!r}")


def _parse_scene_index(raw_value: str, *, world_id: str) -> int:
    try:
        scene_index = int(raw_value)
    except ValueError as exc:
        raise ValueError(f"unsupported MolmoSpaces scene index {raw_value!r}: {world_id}") from exc
    if scene_index < 0:
        raise ValueError(f"unsupported negative MolmoSpaces scene index {scene_index}: {world_id}")
    return scene_index
