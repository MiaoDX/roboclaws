"""CLI router for supported coding-agent MCP servers."""

from __future__ import annotations

import sys

HOUSEHOLD_WORLD_TARGET = "household-world"
SUPPORTED_SERVER_TARGETS = (HOUSEHOLD_WORLD_TARGET,)


def _expected_server_text() -> str:
    return "|".join(SUPPORTED_SERVER_TARGETS)


def main(argv: list[str] | None = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    if not args:
        print(f"error: missing server (expected {_expected_server_text()})", file=sys.stderr)
        return 2

    raw_server = args.pop(0)
    if raw_server not in SUPPORTED_SERVER_TARGETS:
        print(
            f"error: unsupported server {raw_server!r} (expected {_expected_server_text()})",
            file=sys.stderr,
        )
        return 2
    if raw_server == HOUSEHOLD_WORLD_TARGET:
        from roboclaws.cli.household_agent_server import main as household_main

        return household_main(args)

    print(
        f"error: unsupported server {raw_server!r} (expected {_expected_server_text()})",
        file=sys.stderr,
    )
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
