"""Roboclaws public CLI entrypoint."""

from __future__ import annotations

import sys

from roboclaws.cli.agent_server import main as agent_server_main
from roboclaws.cli.task_run import die, surface_run_main


def main(argv: list[str] | None = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    if len(args) >= 2 and args[0] == "run" and args[1] == "surface":
        return surface_run_main(args[2:])
    if args and args[0] == "agent-server":
        return agent_server_main(args[1:])
    die("expected subcommand: run surface | agent-server")


if __name__ == "__main__":
    raise SystemExit(main())
