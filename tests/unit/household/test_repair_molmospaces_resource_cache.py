from __future__ import annotations

import json
from pathlib import Path

import pytest

from scripts.dev.repair_molmospaces_resource_cache import repair_cache


def test_repair_removes_only_unrecorded_version(tmp_path: Path, monkeypatch) -> None:
    import scripts.dev.repair_molmospaces_resource_cache as module

    monkeypatch.setattr(
        module, "DATA_TYPE_TO_SOURCE_TO_VERSION", {"grasps": {"droid": "v1", "other": "v2"}}
    )
    incomplete = tmp_path / "grasps/droid/v1"
    incomplete.mkdir(parents=True)
    recorded = tmp_path / "grasps/other/v2"
    recorded.mkdir(parents=True)
    manifest_path = tmp_path / module.LOCAL_MANIFEST_NAME
    manifest_path.write_text(json.dumps({"grasps": {"other": ["v2"]}}))

    result = repair_cache(tmp_path)

    assert str(incomplete) in result["removed"]
    assert not incomplete.exists()
    assert recorded.is_dir()
    assert repair_cache(tmp_path)["removed"] == []
    assert json.loads(manifest_path.read_text()) == {"grasps": {"other": ["v2"]}}


@pytest.mark.parametrize("payload", ["invalid json", "[]", '{"grasps": null}'])
def test_invalid_manifest_does_not_remove_cached_resources(
    tmp_path: Path, monkeypatch, payload: str
) -> None:
    import scripts.dev.repair_molmospaces_resource_cache as module

    monkeypatch.setattr(module, "DATA_TYPE_TO_SOURCE_TO_VERSION", {"grasps": {"droid": "v1"}})
    target = tmp_path / "grasps/droid/v1"
    target.mkdir(parents=True)
    (tmp_path / module.LOCAL_MANIFEST_NAME).write_text(payload)
    with pytest.raises(ValueError):
        repair_cache(tmp_path)
    assert target.is_dir()
