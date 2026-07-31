from __future__ import annotations

import subprocess
import sys

import pytest

from roboclaws.evals import cli


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
