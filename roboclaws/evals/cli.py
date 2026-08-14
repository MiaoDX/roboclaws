"""CLI entrypoint for repo-native eval suite tools."""

from __future__ import annotations

import argparse
import json
import os
import sys

from roboclaws.evals import runner

_TOOL_MODE_ALIASES = {
    "promote-regression": "promote-regression",
    "promote_regression": "promote-regression",
    "map-build-report": "map-build-report",
    "map_build_report": "map-build-report",
    "runtime-prior-select": "runtime-prior-select",
    "runtime_prior_select": "runtime-prior-select",
    "runtime-prior-promote": "runtime-prior-promote",
    "runtime_prior_promote": "runtime-prior-promote",
    "session-live": "session-live",
    "session_live": "session-live",
}


def main(argv: list[str] | None = None) -> int:
    raw_args = list(sys.argv[1:] if argv is None else argv)
    if os.environ.get("ROBOCLAWS_JUST_TRACE") == "1":
        print("\t".join(("cmd", sys.executable, "-m", "roboclaws.evals.cli", *raw_args)))
        return 0
    parser = argparse.ArgumentParser(description="Run Roboclaws eval tools.")
    parser.add_argument("overrides", nargs="*", help="key=value overrides.")
    args = parser.parse_args(raw_args)
    tool_result = _run_tool_mode_from_args(args.overrides, parser=parser)
    if tool_result is not None:
        return tool_result
    try:
        run = runner.run_eval_from_overrides(_parse_key_value_args(args.overrides))
    except ValueError as exc:
        parser.exit(2, f"error: {exc}\n")
    print(json.dumps({"results": str(run.results_path), "report": str(run.report_path)}))
    return 0


def _run_tool_mode_from_args(
    overrides: list[str], *, parser: argparse.ArgumentParser
) -> int | None:
    if overrides and overrides[0] in {"recommend", "execute"}:
        try:
            return runner.run_eval_harness(overrides[0], _parse_key_value_args(overrides[1:]))
        except (RuntimeError, TimeoutError, ValueError) as exc:
            parser.exit(2, f"error: {exc}\n")
    mode = _TOOL_MODE_ALIASES.get(overrides[0]) if overrides else None
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
    index = 0
    while index < len(argv):
        item = argv[index]
        if item.startswith("--"):
            key = item.removeprefix("--").replace("-", "_")
            if "=" in key:
                key, value = key.split("=", 1)
            else:
                index += 1
                if index >= len(argv):
                    raise ValueError(f"missing value for {item}")
                value = argv[index]
            parsed[key] = value
        elif "=" in item:
            key, value = item.split("=", 1)
            parsed[key.replace("-", "_")] = value
        else:
            raise ValueError(f"unsupported eval argument {item!r}; expected key=value")
        index += 1
    return parsed


if __name__ == "__main__":
    raise SystemExit(main())
