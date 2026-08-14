from __future__ import annotations

import subprocess
import sys
import types

import pytest

from tests.contract.dev_tools.task_agent_just_recipes_support import (
    REPO_ROOT,
    just_bin,
    just_summary,
    trace_household_cleanup_run,
)


def test_public_just_summary_is_the_canonical_command_surface() -> None:
    assert just_summary() == {
        "agent::eval",
        "agent::verify",
        "console::run",
        "run::surface",
    }


@pytest.mark.parametrize(
    ("namespace", "recipes"),
    (
        ("agent", {"eval", "verify"}),
        ("console", {"run"}),
        ("run", {"surface"}),
    ),
)
def test_namespace_only_invocation_lists_recipes_instead_of_running_one(
    namespace: str,
    recipes: set[str],
) -> None:
    result = subprocess.run(
        [just_bin(), namespace],
        cwd=REPO_ROOT,
        check=True,
        capture_output=True,
        text=True,
    )

    for recipe in recipes:
        assert f"    {recipe}" in result.stdout


def test_run_surface_routes_direct_household_cleanup_to_package_owner() -> None:
    route = trace_household_cleanup_run("direct", "world-public-labels")

    assert route[:4] == [
        "cmd",
        ".venv/bin/python",
        "-m",
        "roboclaws.household.household_world_episode",
    ]


def test_agent_server_cli_routes_canonical_household_target(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from roboclaws.cli import agent_server

    calls: list[list[str]] = []

    def fake_main(args: list[str]) -> int:
        calls.append(list(args))
        return 0

    monkeypatch.setitem(
        sys.modules,
        "roboclaws.cli.household_agent_server",
        types.SimpleNamespace(main=fake_main),
    )

    assert agent_server.main(["household-world", "--host", "127.0.0.1"]) == 0
    assert calls == [["--host", "127.0.0.1"]]
