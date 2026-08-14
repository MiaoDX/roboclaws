from __future__ import annotations

import json
from pathlib import Path

import pytest

from roboclaws.backends.isaaclab import molmospaces_semantic_labels as prepare


def test_flattened_semantic_usd_scene_metadata_loader_returns_objects(
    tmp_path: Path,
) -> None:
    scene_dir = tmp_path / "val_1"
    scene_dir.mkdir()
    scene_usd = scene_dir / "scene.usda"
    scene_usd.write_text("#usda 1.0\n", encoding="utf-8")
    (scene_dir / "scene_metadata.json").write_text(
        json.dumps(
            {
                "objects": {
                    "bowl_01": {
                        "asset_id": "Bowl_12",
                        "object_id": "Bowl|surface|1",
                        "category": "Bowl",
                        "is_static": False,
                    },
                    "skip_string": "not an object",
                }
            }
        ),
        encoding="utf-8",
    )

    metadata = prepare._load_molmospaces_scene_metadata(scene_usd)

    assert metadata == {
        "bowl_01": {
            "asset_id": "Bowl_12",
            "object_id": "Bowl|surface|1",
            "category": "Bowl",
            "is_static": False,
        }
    }


@pytest.mark.parametrize(
    ("source_text", "expected_error"),
    [
        (
            "{bad json\n",
            "MolmoSpaces scene metadata source must contain valid JSON object",
        ),
        (
            "[]\n",
            "MolmoSpaces scene metadata source must contain a JSON object",
        ),
    ],
)
def test_flattened_semantic_usd_scene_metadata_loader_rejects_bad_source(
    tmp_path: Path,
    source_text: str,
    expected_error: str,
) -> None:
    scene_dir = tmp_path / "val_1"
    scene_dir.mkdir()
    scene_usd = scene_dir / "scene.usda"
    scene_usd.write_text("#usda 1.0\n", encoding="utf-8")
    (scene_dir / "scene_metadata.json").write_text(source_text, encoding="utf-8")

    with pytest.raises(ValueError, match=expected_error):
        prepare._load_molmospaces_scene_metadata(scene_usd)


def test_flattened_semantic_usd_scene_metadata_loader_allows_missing_source(
    tmp_path: Path,
) -> None:
    scene_usd = tmp_path / "scene.usda"
    scene_usd.write_text("#usda 1.0\n", encoding="utf-8")

    assert prepare._load_molmospaces_scene_metadata(scene_usd) == {}


def test_flattened_semantic_usd_scene_metadata_loader_ignores_missing_objects(
    tmp_path: Path,
) -> None:
    scene_dir = tmp_path / "val_1"
    scene_dir.mkdir()
    scene_usd = scene_dir / "scene.usda"
    scene_usd.write_text("#usda 1.0\n", encoding="utf-8")
    (scene_dir / "scene_metadata.json").write_text('{"scene": "unit"}', encoding="utf-8")

    assert prepare._load_molmospaces_scene_metadata(scene_usd) == {}
