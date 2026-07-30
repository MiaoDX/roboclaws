from __future__ import annotations

import json
from pathlib import Path

from roboclaws.household.scene_camera_usda_contract import load_local_isaac_scene_index


def test_load_local_isaac_scene_index_matches_nearby_scene_usd(tmp_path: Path) -> None:
    scene_usd = _scene_usd(tmp_path)
    index_path = tmp_path / "cleanup-smoke" / "latest" / "isaac_scene_index.json"
    index_path.parent.mkdir(parents=True)
    payload = {
        "scene_usd": str(scene_usd),
        "receptacle_index": {"sink_01": {"usd_prim_path": "/World/sink_01"}},
    }
    index_path.write_text(json.dumps(payload), encoding="utf-8")

    assert load_local_isaac_scene_index(scene_usd) == payload


def test_load_local_isaac_scene_index_ignores_malformed_optional_index(
    tmp_path: Path,
) -> None:
    scene_usd = _scene_usd(tmp_path)
    index_path = tmp_path / "cleanup-smoke" / "latest" / "isaac_scene_index.json"
    index_path.parent.mkdir(parents=True)
    index_path.write_text("{not-json\n", encoding="utf-8")

    assert load_local_isaac_scene_index(scene_usd) == {}


def test_load_local_isaac_scene_index_ignores_non_object_optional_index(
    tmp_path: Path,
) -> None:
    scene_usd = _scene_usd(tmp_path)
    index_path = tmp_path / "cleanup-smoke" / "latest" / "isaac_scene_index.json"
    index_path.parent.mkdir(parents=True)
    index_path.write_text("[]\n", encoding="utf-8")

    assert load_local_isaac_scene_index(scene_usd) == {}


def _scene_usd(tmp_path: Path) -> Path:
    scene_dir = tmp_path / "flattened-semantic-usd" / "scene"
    scene_dir.mkdir(parents=True)
    scene_usd = scene_dir / "scene_semantic.usda"
    scene_usd.write_text("#usda 1.0\n", encoding="utf-8")
    return scene_usd
