from __future__ import annotations

import json
from pathlib import Path

import pytest

from roboclaws.backends.isaaclab.isaac_robot_import import load_json_if_file


def test_load_json_if_file_returns_object_payload(tmp_path: Path) -> None:
    source = tmp_path / "rby1m.import_summary.json"
    payload = {"schema": "isaac_rby1m_robot_usd_import_v1", "status": "ready"}
    source.write_text(json.dumps(payload), encoding="utf-8")

    assert load_json_if_file(source) == payload


@pytest.mark.parametrize("source", ["{", "[]"])
def test_load_json_if_file_keeps_optional_empty_on_bad_sources(
    tmp_path: Path,
    source: str,
) -> None:
    path = tmp_path / "rby1m.import_summary.json"
    path.write_text(source, encoding="utf-8")

    assert load_json_if_file(path) == {}
    assert load_json_if_file(tmp_path / "missing.json") == {}
