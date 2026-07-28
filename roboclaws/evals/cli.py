"""CLI facade for repo-native eval suite tools."""

from __future__ import annotations

import argparse
import importlib.util
import json
from pathlib import Path

from roboclaws.evals.canonical_prior import promote_canonical_runtime_prior
from roboclaws.evals.map_build_reports import (
    discover_eval_results_paths,
    write_map_build_matrix_report,
)
from roboclaws.evals.regression import promote_regression_from_cli_overrides
from roboclaws.evals.runner import DEFAULT_OUTPUT_ROOT, run_eval_suite
from roboclaws.evals.runtime_prior_selection import (
    discover_runtime_prior_eval_results,
    write_runtime_prior_selection,
)

REPO_ROOT = Path(__file__).resolve().parents[2]
EVAL_HARNESS_RUNNER = REPO_ROOT / "skills" / "eval-harness" / "scripts" / "run_eval_harness.py"
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
    parser = argparse.ArgumentParser(description="Run Roboclaws eval tools.")
    parser.add_argument("overrides", nargs="*", help="key=value overrides.")
    args = parser.parse_args(argv)
    tool_result = _run_tool_mode_from_args(args.overrides, parser=parser)
    if tool_result is not None:
        return tool_result
    try:
        run = _run_eval_from_overrides(_parse_key_value_args(args.overrides))
    except ValueError as exc:
        parser.exit(2, f"error: {exc}\n")
    print(json.dumps({"results": str(run.results_path), "report": str(run.report_path)}))
    return 0


def _run_tool_mode_from_args(
    overrides: list[str],
    *,
    parser: argparse.ArgumentParser,
) -> int | None:
    if overrides and overrides[0] in {"recommend", "execute"}:
        try:
            return _run_eval_harness(overrides[0], _parse_key_value_args(overrides[1:]))
        except (RuntimeError, TimeoutError, ValueError) as exc:
            parser.exit(2, f"error: {exc}\n")
    mode = _TOOL_MODE_ALIASES.get(overrides[0]) if overrides else None
    if mode is not None:
        return _run_json_tool_mode(mode, _parse_key_value_args(overrides[1:]), parser=parser)
    return None


def _run_json_tool_mode(
    mode: str,
    overrides: dict[str, str],
    *,
    parser: argparse.ArgumentParser,
) -> int:
    try:
        payload = _tool_mode_payload(mode, overrides)
    except ValueError as exc:
        parser.exit(2, f"error: {exc}\n")
    print(json.dumps(payload, sort_keys=True))
    return 0


def _tool_mode_payload(mode: str, overrides: dict[str, str]) -> dict[str, object]:
    if mode == "promote-regression":
        return promote_regression_from_cli_overrides(overrides)
    if mode == "map-build-report":
        return _run_map_build_report(overrides)
    if mode == "runtime-prior-select":
        return _run_runtime_prior_select(overrides)
    if mode == "runtime-prior-promote":
        return _run_runtime_prior_promote(overrides)
    if mode == "session-live":
        run = _run_session_live_from_overrides(overrides)
        return {"results": str(run.results_path), "report": str(run.report_path)}
    raise ValueError(f"unsupported eval tool mode: {mode}")


def _run_eval_harness(mode: str, overrides: dict[str, str]) -> int:
    values = dict(overrides)
    if values.pop("suite", None):
        raise ValueError(f"{mode} does not accept suite=<suite>; use direct suite mode")
    argv = [mode]
    for key in (
        "budget",
        "profile",
        "plan",
        "since",
        "changed_file",
        "agent_engine",
        "provider_profile",
        "intent",
        "preset",
        "evidence_lane",
        "camera_labeler",
        "scene",
        "runtime_map_prior",
        "output_dir",
        "max_parallel",
        "manifest",
        "row_id",
        "shard_id",
    ):
        value = values.pop(key, None)
        if value in {None, ""}:
            continue
        argv.extend([f"--{key.replace('_', '-')}", value])
    if values:
        keys = ", ".join(sorted(values))
        raise ValueError(f"unsupported eval-harness override(s): {keys}")
    return _load_eval_harness_runner().main(argv)


def _run_map_build_report(overrides: dict[str, str]) -> dict[str, str]:
    values = dict(overrides)
    raw_eval_results = values.pop("eval_results", "")
    output_dir = Path(values.pop("output_dir", "output/evals/map-build-matrix-report"))
    if values:
        keys = ", ".join(sorted(values))
        raise ValueError(f"unsupported map-build-report override(s): {keys}")
    eval_results_paths = discover_eval_results_paths(raw_eval_results)
    return write_map_build_matrix_report(
        eval_results_paths=eval_results_paths,
        output_dir=output_dir,
    )


def _run_runtime_prior_select(overrides: dict[str, str]) -> dict[str, str]:
    values = dict(overrides)
    manifest_ref = values.pop("manifest", "")
    raw_eval_results = values.pop("eval_results", "")
    output_dir = Path(values.pop("output_dir", "output/evals/runtime-prior-selection"))
    if values:
        keys = ", ".join(sorted(values))
        raise ValueError(f"unsupported runtime-prior-select override(s): {keys}")
    if not manifest_ref:
        raise ValueError("runtime-prior-select requires manifest=<path>")
    eval_results_paths = discover_runtime_prior_eval_results(raw_eval_results)
    return write_runtime_prior_selection(
        manifest_path=Path(manifest_ref),
        eval_results_paths=eval_results_paths,
        output_dir=output_dir,
    )


def _run_runtime_prior_promote(overrides: dict[str, str]) -> dict[str, str]:
    values = dict(overrides)
    report = values.pop("report", "")
    manifest = values.pop("manifest", "")
    output_dir = Path(values.pop("output_dir", "output/evals/canonical-runtime-map-priors"))
    if values:
        keys = ", ".join(sorted(values))
        raise ValueError(f"unsupported runtime-prior-promote override(s): {keys}")
    if not report or not manifest:
        raise ValueError("runtime-prior-promote requires report=<path> and manifest=<path>")
    return promote_canonical_runtime_prior(
        selection_report_path=Path(report),
        promotion_manifest_path=Path(manifest),
        output_root=output_dir,
    )


def _run_session_live_from_overrides(overrides: dict[str, str]):
    from roboclaws.evals.session_live import run_session_live_eval

    values = dict(overrides)
    budget = values.pop("budget", "smoke")
    output_root = Path(values.pop("output_dir", str(DEFAULT_OUTPUT_ROOT)))
    stamp = values.pop("stamp", None)
    agent_engine = values.pop("agent_engine", "openai-agents-sdk")
    provider_profile = values.pop("provider_profile", "kimi-openai-chat")
    live_execution = values.pop("live_execution", "blocked")
    live_timeout_s = _optional_float(values.pop("live_timeout_s", None)) or 900.0
    if values:
        keys = ", ".join(sorted(values))
        raise ValueError(f"unsupported session-live eval override(s): {keys}")
    return run_session_live_eval(
        output_root=output_root,
        budget=budget,
        stamp=stamp,
        agent_engine=agent_engine,
        provider_profile=provider_profile,
        live_execution=live_execution,
        live_timeout_s=live_timeout_s,
    )


def _load_eval_harness_runner():
    spec = importlib.util.spec_from_file_location(
        "roboclaws_eval_harness_runner",
        EVAL_HARNESS_RUNNER,
    )
    if spec is None or spec.loader is None:
        raise RuntimeError(f"could not load eval harness runner at {EVAL_HARNESS_RUNNER}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _run_eval_from_overrides(overrides: dict[str, str]):
    values = dict(overrides)
    suite_ref = values.pop("suite", "smoke_regression")
    budget = values.pop("budget", "smoke")
    output_root = Path(values.pop("output_dir", str(DEFAULT_OUTPUT_ROOT)))
    stamp = values.pop("stamp", None)
    agent_engine = values.pop("agent_engine", "direct-runner")
    provider_profile = values.pop("provider_profile", None)
    model = values.pop("model", None)
    live_execution = values.pop("live_execution", "blocked")
    live_timeout_s = _optional_float(values.pop("live_timeout_s", None))
    live_stall_timeout_s = _optional_float(values.pop("live_stall_timeout_s", None))
    regrade_source = _optional_path(values.pop("regrade_source", None))
    runtime_map_prior = _optional_path(values.pop("runtime_map_prior", None))
    if values:
        keys = ", ".join(sorted(values))
        raise ValueError(f"unsupported eval override(s): {keys}")
    return run_eval_suite(
        suite_ref,
        output_root=output_root,
        budget=budget,
        stamp=stamp,
        agent_engine=agent_engine,
        provider_profile=provider_profile,
        model=model,
        live_execution=live_execution,
        live_timeout_s=live_timeout_s,
        live_stall_timeout_s=live_stall_timeout_s,
        regrade_source=regrade_source,
        runtime_map_prior=runtime_map_prior,
    )


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


def _optional_float(value: str | None) -> float | None:
    if value in {None, ""}:
        return None
    return float(value)


def _optional_path(value: str | None) -> Path | None:
    if value in {None, ""}:
        return None
    return Path(str(value))
