from __future__ import annotations

import json
from pathlib import Path

import pytest

from roboclaws.worlds.molmospaces import scanner as scene_sampler_scanner


def test_scene_sampler_scanner_optional_json_loads_object(tmp_path: Path) -> None:
    source = tmp_path / "scanner.json"
    source.write_text(json.dumps({"status": "ready"}), encoding="utf-8")

    assert scene_sampler_scanner._read_json_if_exists(source) == {"status": "ready"}


@pytest.mark.parametrize("source_text", ["{bad json\n", "[]\n"])
def test_scene_sampler_scanner_optional_json_ignores_bad_source(
    tmp_path: Path,
    source_text: str,
) -> None:
    source = tmp_path / "scanner.json"
    source.write_text(source_text, encoding="utf-8")

    assert scene_sampler_scanner._read_json_if_exists(source) == {}


def test_scene_sampler_scanner_optional_json_ignores_missing_source(tmp_path: Path) -> None:
    assert scene_sampler_scanner._read_json_if_exists(tmp_path / "missing.json") == {}


def test_scene_sampler_scanner_optional_json_ignores_unreadable_source(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source = tmp_path / "scanner.json"
    source.write_text(json.dumps({"status": "ready"}), encoding="utf-8")
    monkeypatch.setattr(
        scene_sampler_scanner,
        "read_json_object",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(OSError("read failed")),
    )

    assert scene_sampler_scanner._read_json_if_exists(source) == {}
