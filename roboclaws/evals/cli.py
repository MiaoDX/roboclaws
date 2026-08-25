"""CLI entrypoint for repo-native eval suite tools."""

from __future__ import annotations

import argparse
import json
import os
import sys

_TOOL_MODES = {
    "evolve",
    "evolve-promote",
    "map-build-report",
    "opik-project",
    "opik-dashboard",
    "promote-regression",
    "runtime-prior-promote",
    "runtime-prior-select",
    "session-live",
}
_HARNESS_MODES = {"execute", "recommend"}
_NAMED_MODES = _HARNESS_MODES | _TOOL_MODES


def main(argv: list[str] | None = None) -> int:
    raw_args = list(sys.argv[1:] if argv is None else argv)
    parser = argparse.ArgumentParser(description="Run Roboclaws eval tools.")
    parser.add_argument(
        "overrides",
        nargs="*",
        help="optional kebab-case tool name followed by key=value arguments.",
    )
    args = parser.parse_args(raw_args)
    try:
        _validate_cli_grammar(args.overrides)
    except ValueError as exc:
        parser.exit(2, f"error: {exc}\n")
    if os.environ.get("ROBOCLAWS_JUST_TRACE") == "1":
        print("\t".join(("cmd", sys.executable, "-m", "roboclaws.evals.cli", *raw_args)))
        return 0
    tool_result = _run_tool_mode_from_args(args.overrides, parser=parser)
    if tool_result is not None:
        return tool_result
    try:
        from roboclaws.evals import runner

        run = runner.run_eval_from_overrides(_parse_key_value_args(args.overrides))
    except ValueError as exc:
        parser.exit(2, f"error: {exc}\n")
    print(
        json.dumps(
            {
                "results": str(run.results_path),
                "report": str(run.report_path),
                "opik_projection": run.opik_projection,
            },
            sort_keys=True,
        )
    )
    return 0


def _run_tool_mode_from_args(
    overrides: list[str], *, parser: argparse.ArgumentParser
) -> int | None:
    from roboclaws.evals import runner

    if overrides and overrides[0] in _HARNESS_MODES:
        try:
            return runner.run_eval_harness(overrides[0], _parse_key_value_args(overrides[1:]))
        except (RuntimeError, TimeoutError, ValueError) as exc:
            parser.exit(2, f"error: {exc}\n")
    mode = overrides[0] if overrides and overrides[0] in _TOOL_MODES else None
    if mode is None:
        return None
    try:
        payload = runner.run_cli_tool(mode, _parse_key_value_args(overrides[1:]))
    except ValueError as exc:
        parser.exit(2, f"error: {exc}\n")
    print(json.dumps(payload, sort_keys=True))
    return 0


def _parse_key_value_args(argv: list[str]) -> dict[str, str]:
    parsed: dict[str, str] = {}
    for item in argv:
        if "=" not in item:
            raise ValueError(f"unsupported eval argument {item!r}; expected key=value")
        key, value = item.split("=", 1)
        if not key.isidentifier():
            raise ValueError(f"unsupported eval argument {item!r}; expected key=value")
        parsed[key] = value
    return parsed


def _validate_cli_grammar(argv: list[str]) -> None:
    values = argv[1:] if argv and argv[0] in _NAMED_MODES else argv
    _parse_key_value_args(values)


if __name__ == "__main__":
    raise SystemExit(main())
