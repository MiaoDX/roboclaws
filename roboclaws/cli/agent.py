"""Maintainer agent command dispatchers."""

from __future__ import annotations

import sys
from collections.abc import Sequence

from roboclaws.cli.agent_common import _die, _exec_or_trace, _strip_prefixes
from roboclaws.cli.agent_run import agent_run

VERIFY_TARGETS = {
    "static",
    "mock",
    "ci-required",
    "contract",
    "molmo-realworld-cleanup",
    "molmo-realworld-agent-mcp",
    "molmo-realworld-agent-dogfood-kit",
    "molmo-realworld-openclaw-dogfood-kit",
    "molmo-realworld-openclaw-visual-dogfood-kit",
    "molmo-realworld-raw-fpv",
    "molmo-planner-proof-bundle-runner",
    "molmo-planner-proof-bundle-execute-rerun",
    "molmo-planner-manipulation-probe",
    "full-local",
}

HARNESS_TARGETS = {
    "molmo-realworld-cleanup",
    "molmo-realworld-agent-mcp",
    "molmo-realworld-agent-dogfood-kit",
    "molmo-realworld-openclaw-dogfood-kit",
    "molmo-realworld-openclaw-visual-dogfood-kit",
    "molmo-realworld-raw-fpv",
    "molmo-planner-proof-bundle-runner",
    "molmo-planner-proof-bundle-execute-rerun",
    "molmo-planner-manipulation-probe",
    "molmo-visual-grounding-benchmark",
    "isaac-runtime-preflight",
    "isaac-runtime-smoke",
    "b1-map12-navigation-smoke",
}


def main(argv: list[str] | None = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    if not args:
        _die("expected agent subcommand: run | verify | harness | mcp | gateway")
    command, rest = args[0], args[1:]
    if command == "run":
        return agent_run(rest)
    if command == "verify":
        return _dispatch_named_target(
            rest,
            default="mock",
            target_set=VERIFY_TARGETS,
            namespace="verify",
            noun="verify target",
        )
    if command == "harness":
        return _dispatch_named_target(
            rest,
            default=None,
            target_set=HARNESS_TARGETS,
            namespace="harness",
            noun="harness target",
        )
    if command == "mcp":
        return _mcp(rest)
    if command == "gateway":
        return _gateway(rest)
    if command == "eval":
        return _exec_or_trace([".venv/bin/python", "-m", "roboclaws.cli.main", "eval", *rest])
    _die(f"unsupported agent subcommand {command!r}")


def _dispatch_named_target(
    args: Sequence[str],
    *,
    default: str | None,
    target_set: set[str],
    namespace: str,
    noun: str,
) -> int:
    if args:
        target = _strip_prefixes(args[0], "target=")
        rest = list(args[1:])
    elif default is not None:
        target = default
        rest = []
    else:
        _die(f"{noun} is required")
    if target not in target_set:
        _die(f"unsupported {noun} '{target}'")
    return _exec_or_trace(["just", f"{namespace}::{target}", *rest])


def _mcp(args: Sequence[str]) -> int:
    action = _strip_prefixes(args[0], "action=") if args else "up"
    if action == "down":
        return _exec_or_trace(["just", "mcp::down"])
    if action != "up":
        _die(f"unsupported mcp action '{action}' (expected up|down)")
    server = args[1] if len(args) > 1 else "household-world.cleanup"
    if server in {"household-world.cleanup", "cleanup"}:
        server = "household-world.cleanup"
    elif server in {"household-world.map-build", "map-build"}:
        server = "household-world.map-build"
    else:
        _die(
            f"unsupported MCP dispatch target '{server}' "
            "(expected household-world.cleanup|household-world.map-build)"
        )
    host = args[2] if len(args) > 2 else "127.0.0.1"
    port = args[3] if len(args) > 3 else "18788"
    output_dir = args[4] if len(args) > 4 else ".tmp/roboclaws-mcp/run"
    return _exec_or_trace(["just", "mcp::up", server, host, port, output_dir])


def _gateway(args: Sequence[str]) -> int:
    action = _strip_prefixes(args[0], "action=") if args else "up"
    if action in {"pull-image", "pull"}:
        return _exec_or_trace(["just", "openclaw::pull-image"])
    if action not in {"up", "down"}:
        _die(f"unsupported gateway action '{action}' (expected up|down|pull-image)")
    token_file = args[1] if len(args) > 1 else ".openclaw-token"
    provider = args[2] if len(args) > 2 else "kimi"
    agents = args[3] if len(args) > 3 else "2"
    return _exec_or_trace(["just", "openclaw::gateway", action, token_file, provider, agents])


if __name__ == "__main__":
    raise SystemExit(main())
