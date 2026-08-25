from __future__ import annotations

import json
import subprocess
import sys
from types import SimpleNamespace

import pytest

import roboclaws.evals.cli as cli


def test_eval_cli_prints_opik_projection_summary(
    tmp_path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    from roboclaws.evals import runner

    monkeypatch.setattr(
        runner,
        "run_eval_from_overrides",
        lambda _overrides: SimpleNamespace(
            results_path=tmp_path / "eval_results.json",
            report_path=tmp_path / "eval_report.html",
            opik_projection={
                "receipt": str(tmp_path / "opik_projection.json"),
                "state": "unavailable",
                "reason": "opik_unavailable",
            },
        ),
    )

    assert cli.main(["suite=smoke_regression"]) == 0

    payload = json.loads(capsys.readouterr().out)
    assert payload["opik_projection"]["state"] == "unavailable"
    assert payload["opik_projection"]["reason"] == "opik_unavailable"


def test_eval_cli_import_does_not_require_session_live_dependencies() -> None:
    script = """
import builtins

original_import = builtins.__import__

def guarded_import(name, *args, **kwargs):
    if name == "mcp" or name.startswith("mcp."):
        raise ModuleNotFoundError("mcp is intentionally unavailable")
    return original_import(name, *args, **kwargs)

builtins.__import__ = guarded_import
import roboclaws.evals.cli
"""

    subprocess.run([sys.executable, "-c", script], check=True)


@pytest.mark.parametrize(
    "alias",
    [
        "map_build_report",
        "promote_regression",
        "runtime_prior_promote",
        "runtime_prior_select",
        "session_live",
    ],
)
def test_eval_cli_rejects_underscore_tool_aliases(alias: str) -> None:
    with pytest.raises(SystemExit) as exc_info:
        cli.main([alias])

    assert exc_info.value.code == 2


@pytest.mark.parametrize(
    "arguments",
    [
        ["suite=smoke_regression", "--budget", "smoke"],
        ["suite=smoke_regression", "--budget=smoke"],
        ["suite=smoke_regression", "agent-engine=direct-runner"],
    ],
)
def test_eval_cli_rejects_flag_and_hyphen_key_aliases(arguments: list[str]) -> None:
    with pytest.raises(SystemExit) as exc_info:
        cli.main(arguments)

    assert exc_info.value.code == 2
