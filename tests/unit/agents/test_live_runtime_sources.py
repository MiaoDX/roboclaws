from __future__ import annotations

import json
from pathlib import Path

import pytest

from roboclaws.agents.live_runtime import _read_json


def test_live_runtime_json_source_missing_or_object_policy(tmp_path: Path) -> None:
    assert _read_json(tmp_path / "missing.json") == {}

    path = tmp_path / "live_status.json"
    path.write_text('{"phase": "finished"}\n', encoding="utf-8")

    assert _read_json(path) == {"phase": "finished"}


def test_live_runtime_json_source_rejects_invalid_present_sources(tmp_path: Path) -> None:
    malformed = tmp_path / "live_status.json"
    malformed.write_text("{not json", encoding="utf-8")

    with pytest.raises(
        ValueError,
        match=r"live-agent artifact source .*live_status\.json: invalid JSON at line 1",
    ):
        _read_json(malformed)

    non_object = tmp_path / "run_result.json"
    non_object.write_text(json.dumps(["ok"]), encoding="utf-8")
    with pytest.raises(
        ValueError,
        match=r"live-agent artifact source .*run_result\.json: non-object JSON: list",
    ):
        _read_json(non_object)
