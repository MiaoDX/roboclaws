from __future__ import annotations

import json
from pathlib import Path

import pytest

import roboclaws.evals.cli as cli


def test_evolve_defaults_to_blocked_without_live_execution(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    campaign = tmp_path / "campaign.json"
    campaign.write_text("{}", encoding="utf-8")
    monkeypatch.setattr(
        "roboclaws.evals.runner.run_cli_tool",
        lambda mode, overrides: {"mode": mode, "status": "blocked", "live_execution": "blocked"},
    )
    assert cli.main(["evolve", f"campaign={campaign}"]) == 0
    assert json.loads(capsys.readouterr().out) == {
        "live_execution": "blocked",
        "mode": "evolve",
        "status": "blocked",
    }


def test_evolve_promote_is_named_grammar() -> None:
    with pytest.raises(SystemExit) as exc_info:
        cli.main(["evolve_promote"])
    assert exc_info.value.code == 2
