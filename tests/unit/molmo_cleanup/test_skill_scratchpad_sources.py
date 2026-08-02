from __future__ import annotations

import json
from pathlib import Path

import pytest

from roboclaws.household.skill_scratchpad import (
    SCRATCHPAD_SCHEMA,
    read_or_create_skill_scratchpad,
)


def test_read_or_create_skill_scratchpad_creates_missing_source(tmp_path: Path) -> None:
    scratchpad, path = read_or_create_skill_scratchpad(run_dir=tmp_path, note="created")

    assert path == tmp_path / "agent_scratchpad.json"
    assert scratchpad["schema"] == SCRATCHPAD_SCHEMA
    assert scratchpad["notes"] == ["created"]
    assert json.loads(path.read_text(encoding="utf-8")) == scratchpad


@pytest.mark.parametrize(
    ("source", "message"),
    [
        (
            "{not-json\n",
            r"skill scratchpad source must contain valid JSON object: .*agent_scratchpad\.json",
        ),
        (
            "[]\n",
            r"skill scratchpad source must contain a JSON object: .*agent_scratchpad\.json",
        ),
    ],
)
def test_read_or_create_skill_scratchpad_rejects_bad_present_source(
    tmp_path: Path,
    source: str,
    message: str,
) -> None:
    scratchpad = tmp_path / "agent_scratchpad.json"
    scratchpad.write_text(source, encoding="utf-8")

    with pytest.raises(ValueError, match=message):
        read_or_create_skill_scratchpad(run_dir=tmp_path)
