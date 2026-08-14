from __future__ import annotations

import json
from pathlib import Path

import pytest

from roboclaws.core.goals import goal_contract_from_file, goal_contract_from_json


def test_goal_contract_from_file_returns_none_for_empty_source() -> None:
    assert goal_contract_from_file(None) is None
    assert goal_contract_from_file("") is None


def test_goal_contract_from_json_returns_none_for_empty_source() -> None:
    assert goal_contract_from_json(None) is None
    assert goal_contract_from_json("") is None


def test_goal_contract_from_json_rejects_malformed_inline_source() -> None:
    with pytest.raises(
        ValueError,
        match=r"goal contract source must contain valid JSON object: inline JSON",
    ):
        goal_contract_from_json("{")


def test_goal_contract_from_json_rejects_non_object_inline_source() -> None:
    with pytest.raises(
        ValueError,
        match=r"goal contract source must contain a JSON object: inline JSON",
    ):
        goal_contract_from_json("[]")


def test_goal_contract_from_file_rejects_missing_source(tmp_path: Path) -> None:
    with pytest.raises(FileNotFoundError, match=r"goal contract source is missing: .*missing"):
        goal_contract_from_file(tmp_path / "missing.json")


def test_goal_contract_from_file_rejects_malformed_source(tmp_path: Path) -> None:
    path = tmp_path / "goal_contract.json"
    path.write_text("{", encoding="utf-8")

    with pytest.raises(
        ValueError,
        match=r"goal contract source must contain valid JSON object: .*goal_contract\.json",
    ):
        goal_contract_from_file(path)


def test_goal_contract_from_file_rejects_non_object_source(tmp_path: Path) -> None:
    path = tmp_path / "goal_contract.json"
    path.write_text("[]", encoding="utf-8")

    with pytest.raises(
        ValueError,
        match=r"goal contract source must contain a JSON object: .*goal_contract\.json",
    ):
        goal_contract_from_file(path)


def test_goal_contract_from_file_loads_object_source(tmp_path: Path) -> None:
    path = tmp_path / "goal_contract.json"
    path.write_text(
        json.dumps(
            {
                "schema": "roboclaws_goal_contract_v1",
                "raw_prompt": "find water",
                "normalized_goal": "find water",
                "surface": "household-world",
                "intent": "open-ended",
                "goal_scope": "agent-declared",
                "assumptions": ["Use public evidence."],
                "tool_plan": ["observe", "done"],
                "success_criteria": ["Structured completion claim is present."],
            }
        ),
        encoding="utf-8",
    )

    contract = goal_contract_from_file(path)

    assert contract is not None
    assert contract.surface == "household-world"
    assert contract.intent == "open-ended"
    assert contract.tool_plan == ("observe", "done")
