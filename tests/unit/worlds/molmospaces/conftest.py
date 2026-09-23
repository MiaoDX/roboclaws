from __future__ import annotations

import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

from roboclaws.worlds.molmospaces.catalog import known_indices_for_source
from roboclaws.worlds.molmospaces.world_ids import SUPPORTED_SCENE_SOURCES


@pytest.fixture
def visible_sampler_assets(monkeypatch, tmp_path: Path) -> None:
    """Exercise real readiness logic without upstream downloads on cold runners."""
    mappings = {}
    for source in SUPPORTED_SCENE_SOURCES:
        source_dir = tmp_path / source
        source_dir.mkdir()
        indices = set(known_indices_for_source(source))
        # iTHOR is exhausted; the other incomplete sources have new candidates.
        if source != "ithor":
            indices.update(range(100))
        mappings[source] = {}
        for index in sorted(indices):
            path = source_dir / f"{index}.xml"
            path.write_text("<mujoco />", encoding="utf-8")
            mappings[source][index] = path

    def get_scenes(dataset_name, split, *, return_version):
        source = "ithor" if dataset_name == "ithor" else f"{dataset_name}-{split}"
        return {split: mappings[source]}, "test"

    monkeypatch.setitem(
        sys.modules,
        "molmo_spaces.molmo_spaces_constants",
        SimpleNamespace(get_scenes_root=lambda: tmp_path, get_scenes=get_scenes),
    )
