from __future__ import annotations

import json
import os
import subprocess
import tarfile
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[3]
STAGE_SCRIPT = REPO_ROOT / "scripts" / "dev" / "stage_cloudml_cleanup_assets.sh"


def _fixture_assets(root: Path, *, scene_source: str, scene_indices: tuple[int, ...]):
    assets = root / "assets"
    cache = root / "cache"
    scene_dir = assets / "scenes" / scene_source
    shared_files = (
        "mjthor_resources_combined_meta.json.gz",
        "mjthor_resource_file_to_size_mb.json",
    )
    for name in shared_files:
        path = scene_dir / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(f"fixture:{name}\n", encoding="utf-8")
    for index in scene_indices:
        name = f"val_{index}"
        for suffix in (".xml", ".json", "_metadata.json", "_ceiling.xml"):
            (scene_dir / f"{name}{suffix}").write_text("fixture\n", encoding="utf-8")
        mesh = scene_dir / f"{name}_assets" / "mesh.obj"
        mesh.parent.mkdir()
        mesh.write_text(f"mesh:{index}\n", encoding="utf-8")
        (scene_dir / f".{scene_source}_{name}.tar.zst_complete_links").write_text(
            "fixture\n", encoding="utf-8"
        )
    for relative in (
        "objects/thor/object.txt",
        "robots/rby1m/robot.txt",
        "mjthor_data_type_to_source_to_versions.json",
    ):
        path = assets / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("fixture\n", encoding="utf-8")
    for relative in (
        f"scenes/{scene_source}/version/resource.json",
        "objects/objaverse/version/object.txt",
        "grasps/droid_objaverse/version/resource.json",
        "mjthor_data_type_to_source_to_versions.json",
    ):
        path = cache / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("fixture\n", encoding="utf-8")
    return assets, cache


def _stage(
    tmp_path: Path,
    assets: Path,
    cache: Path,
    *,
    scenes: str,
    label: str,
) -> dict:
    stage_dir = tmp_path / f"stage-{label}"
    env = os.environ.copy()
    env.update(
        {
            "MLSPACES_ASSETS_DIR": str(assets),
            "MLSPACES_CACHE_DIR": str(cache),
            "ROBOCLAWS_CLOUDML_CODE_COMMIT": "HEAD",
            "ROBOCLAWS_EXECUTOR_ROOT": str(tmp_path / "missing-executor"),
            "ROBOCLAWS_STAGE_DIR": str(stage_dir),
            "ROBOCLAWS_STAGE_CONTENT_CACHE_DIR": str(tmp_path / "content-cache"),
            "ROBOCLAWS_STAGE_RUN_UPLOAD_DRY_RUN": "false",
            "ROBOCLAWS_STAGE_RUN_UPLOAD": "false",
            "ROBOCLAWS_STAGE_SCENES": scenes,
        }
    )
    subprocess.run([str(STAGE_SCRIPT)], cwd=REPO_ROOT, env=env, check=True, capture_output=True)
    return json.loads((stage_dir / "roboclaws_cloudml_cleanup_assets.json").read_text())


@pytest.mark.parametrize("scene_index", [0, 10])
def test_staging_freezes_only_the_selected_scene(tmp_path: Path, scene_index: int) -> None:
    assets, cache = _fixture_assets(
        tmp_path, scene_source="procthor-10k-val", scene_indices=(0, 10)
    )

    manifest = _stage(
        tmp_path,
        assets,
        cache,
        scenes=f"procthor-10k-val/{scene_index}",
        label=str(scene_index),
    )

    scene_name = f"val_{scene_index}"
    other_name = "val_10" if scene_index == 0 else "val_0"
    assert manifest["source_assets"]["scenes"] == [
        {
            "scene_id": f"procthor-10k-val/{scene_index}",
            "source": "procthor-10k-val",
            "index": scene_index,
            "name": scene_name,
            "world": (
                f"molmospaces/val_{scene_index}"
                if scene_index == 0
                else f"molmospaces/procthor-10k-val/{scene_index}"
            ),
            "map_bundle": f"assets/maps/molmospaces/procthor-10k-val/{scene_index}",
        }
    ]
    required = manifest["required_cloudml_checks"]
    assert any(f"/{scene_name}.xml" in path for path in required)
    assert any(path.endswith(f"/{scene_index}/map.yaml") for path in required)
    with tarfile.open(manifest["staged_assets"]["archive"]["local_path"], "r:gz") as archive:
        names = archive.getnames()
    assert f"molmospaces/assets/scenes/procthor-10k-val/{scene_name}.xml" in names
    assert f"molmospaces/assets/scenes/procthor-10k-val/{other_name}.xml" not in names


def test_staging_freezes_multiple_source_aware_scenes_in_one_archive(tmp_path: Path) -> None:
    assets, cache = _fixture_assets(tmp_path, scene_source="procthor-10k-val", scene_indices=(0,))
    assets, cache = _fixture_assets(
        tmp_path, scene_source="procthor-objaverse-val", scene_indices=(0,)
    )

    manifest = _stage(
        tmp_path,
        assets,
        cache,
        scenes="procthor-10k-val/0,procthor-objaverse-val/0",
        label="multi",
    )

    assert [scene["scene_id"] for scene in manifest["source_assets"]["scenes"]] == [
        "procthor-10k-val/0",
        "procthor-objaverse-val/0",
    ]
    assert manifest["staged_assets"]["archive"]["name"] == (
        "cleanup-focused-molmospaces-scenes.tar.gz"
    )
    with tarfile.open(manifest["staged_assets"]["archive"]["local_path"], "r:gz") as archive:
        names = set(archive.getnames())
    assert "molmospaces/assets/scenes/procthor-10k-val/val_0.xml" in names
    assert "molmospaces/assets/scenes/procthor-objaverse-val/val_0.xml" in names
    assert "molmospaces/cache/objects/objaverse/version/object.txt" in names
    assert "roboclaws/assets/maps/molmospaces/procthor-10k-val/0/map.yaml" in names
    assert "roboclaws/assets/maps/molmospaces/procthor-objaverse-val/0/map.yaml" in names


def test_scene_defaults_remain_val_zero() -> None:
    stage = STAGE_SCRIPT.read_text(encoding="utf-8")
    dry_run = (REPO_ROOT / "scripts" / "dev" / "cloudml_eval_dry_run.sh").read_text()
    worker = (REPO_ROOT / "scripts" / "dev" / "run_cloudml_eval_worker.sh").read_text()

    assert "ROBOCLAWS_STAGE_SCENE_SOURCE:-procthor-10k-val" in stage
    assert "ROBOCLAWS_STAGE_SCENE_INDEX:-0" in stage
    assert "ROBOCLAWS_CLOUDML_SCENE_SOURCE:-procthor-10k-val" in dry_run
    assert "ROBOCLAWS_CLOUDML_SCENE_INDEX:-0" in dry_run
    assert 'get("source_assets", {}).get("scenes", [])' in worker
    assert 'row.get("case")' in worker
    assert 'scene_dir="$MLSPACES_ASSETS_DIR/scenes/$scene_source"' in worker
    assert 'object_cache_root="$MLSPACES_CACHE_DIR/objects"' in worker
    assert 'ln -s "${object_versions[0]}" "$object_link"' in worker
