"""Composition owner for repo-native eval suite execution."""

from __future__ import annotations

import os
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from roboclaws.agents.skill_delivery import validate_skill_delivery_cell
from roboclaws.evals.agent_identity import (
    agent_engine_spec,
    eval_provider_profile,
    validate_sample_agent,
)
from roboclaws.evals.canonical_prior import promote_canonical_runtime_prior
from roboclaws.evals.dependencies import sample_artifact_key
from roboclaws.evals.harness import runner as harness_runner
from roboclaws.evals.map_build_reports import (
    discover_eval_results_paths,
    write_map_build_matrix_report,
)
from roboclaws.evals.models import EvalResult, EvalSuite
from roboclaws.evals.regression import promote_regression_from_cli_overrides
from roboclaws.evals.result_persistence import persist_results
from roboclaws.evals.runtime_prior_selection import (
    discover_runtime_prior_eval_results,
    write_runtime_prior_selection,
)
from roboclaws.evals.suite_loading import (
    REPO_ROOT,
    load_suite,
    path_token,
    resolved_regrade_source,
    validate_suite_runtime_map_prior,
)
from roboclaws.evals.trial_execution import (
    ProductRun,
    _run_trial,
    _sample_artifact_record,
    _trial_from_sample,
)
from roboclaws.household.household_world_episode import run_household_world_episode

DEFAULT_OUTPUT_ROOT = REPO_ROOT / "output" / "evals"


@dataclass(frozen=True)
class EvalSuiteRun:
    """Paths and result bundle for one eval suite execution."""

    suite: EvalSuite
    output_dir: Path
    results_path: Path
    report_path: Path
    bundle: dict[str, Any]


def run_cli_tool(mode: str, overrides: dict[str, str]) -> dict[str, object]:
    """Dispatch a non-suite eval CLI mode to its direct behavior owner."""
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


def run_eval_harness(mode: str, overrides: dict[str, str]) -> int:
    """Run the package-owned eval-harness entrypoint."""
    values = dict(overrides)
    if values.pop("suite", None):
        raise ValueError(f"{mode} does not accept suite=<suite>; use direct suite mode")
    return harness_runner.run_from_overrides(mode, values)


def run_eval_from_overrides(overrides: dict[str, str]) -> EvalSuiteRun:
    """Lower CLI overrides into the canonical suite runner."""
    values = dict(overrides)
    suite_ref = values.pop("suite", "smoke_regression")
    budget = values.pop("budget", "smoke")
    output_root = Path(values.pop("output_dir", str(DEFAULT_OUTPUT_ROOT)))
    stamp = values.pop("stamp", None)
    agent_engine = values.pop("agent_engine", "direct-runner")
    provider_profile = values.pop("provider_profile", None)
    model = values.pop("model", None)
    live_execution = values.pop("live_execution", "blocked")
    skill_delivery_cell = validate_skill_delivery_cell(values.pop("skill_delivery_cell", None))
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
        skill_delivery_cell=skill_delivery_cell,
        live_timeout_s=live_timeout_s,
        live_stall_timeout_s=live_stall_timeout_s,
        regrade_source=regrade_source,
        runtime_map_prior=runtime_map_prior,
    )


def _run_map_build_report(overrides: dict[str, str]) -> dict[str, str]:
    values = dict(overrides)
    raw_eval_results = values.pop("eval_results", "")
    output_dir = Path(values.pop("output_dir", "output/evals/map-build-matrix-report"))
    _reject_overrides(values, "map-build-report")
    return write_map_build_matrix_report(
        eval_results_paths=discover_eval_results_paths(raw_eval_results), output_dir=output_dir
    )


def _run_runtime_prior_select(overrides: dict[str, str]) -> dict[str, str]:
    values = dict(overrides)
    manifest_ref = values.pop("manifest", "")
    raw_eval_results = values.pop("eval_results", "")
    output_dir = Path(values.pop("output_dir", "output/evals/runtime-prior-selection"))
    _reject_overrides(values, "runtime-prior-select")
    if not manifest_ref:
        raise ValueError("runtime-prior-select requires manifest=<path>")
    return write_runtime_prior_selection(
        manifest_path=Path(manifest_ref),
        eval_results_paths=discover_runtime_prior_eval_results(raw_eval_results),
        output_dir=output_dir,
    )


def _run_runtime_prior_promote(overrides: dict[str, str]) -> dict[str, str]:
    values = dict(overrides)
    report = values.pop("report", "")
    manifest = values.pop("manifest", "")
    output_dir = Path(values.pop("output_dir", "output/evals/canonical-runtime-map-priors"))
    _reject_overrides(values, "runtime-prior-promote")
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
    _reject_overrides(values, "session-live eval")
    return run_session_live_eval(
        output_root=output_root,
        budget=budget,
        stamp=stamp,
        agent_engine=agent_engine,
        provider_profile=provider_profile,
        live_execution=live_execution,
        live_timeout_s=live_timeout_s,
    )


def _reject_overrides(values: dict[str, str], mode: str) -> None:
    if values:
        keys = ", ".join(sorted(values))
        raise ValueError(f"unsupported {mode} override(s): {keys}")


def _optional_float(value: str | None) -> float | None:
    return None if value in {None, ""} else float(value)


def _optional_path(value: str | None) -> Path | None:
    return None if value in {None, ""} else Path(str(value))


def run_eval_suite(
    suite_ref: str,
    *,
    output_root: Path = DEFAULT_OUTPUT_ROOT,
    budget: str = "smoke",
    stamp: str | None = None,
    agent_engine: str = "direct-runner",
    provider_profile: str | None = None,
    model: str | None = None,
    live_execution: str = "blocked",
    skill_delivery_cell: str = "static-full",
    live_timeout_s: float | None = None,
    live_stall_timeout_s: float | None = None,
    regrade_source: Path | None = None,
    runtime_map_prior: Path | None = None,
    product_runner: ProductRun = run_household_world_episode,
    live_product_runner: ProductRun | None = None,
) -> EvalSuiteRun:
    """Run a repo-native deterministic eval suite."""

    if live_execution not in {"blocked", "run"}:
        raise ValueError("live_execution must be blocked or run")
    skill_delivery_cell = validate_skill_delivery_cell(skill_delivery_cell)
    if regrade_source is not None and agent_engine == "direct-runner":
        raise ValueError("regrade_source is only supported for live-agent eval runs")

    suite, samples = load_suite(suite_ref)
    validate_suite_runtime_map_prior(suite, runtime_map_prior)
    engine = agent_engine_spec(agent_engine)
    selected_provider_profile = eval_provider_profile(
        agent_engine=engine.id,
        provider_profile=provider_profile,
    )
    regrade_source_dir = resolved_regrade_source(regrade_source, suite=suite)
    run_stamp = stamp or _default_run_stamp()
    output_dir = output_root / path_token(suite.suite_id) / run_stamp
    output_dir.mkdir(parents=True, exist_ok=True)

    results: list[EvalResult] = []
    sample_artifacts: dict[str, dict[str, Any]] = {}
    for sample in samples:
        validate_sample_agent(sample, agent_engine=engine.id)
        for repetition_index in range(sample.trial_count):
            trial = _trial_from_sample(
                suite=suite,
                sample=sample,
                repetition_index=repetition_index,
                budget=budget,
                agent_engine=engine.id,
                runner_class=engine.internal_runner_class,
                provider_profile=selected_provider_profile,
                model=model,
                skill_delivery_cell=skill_delivery_cell,
            )
            sample_run_dir = output_dir / "runs" / path_token(sample.sample_id)
            run_dir = sample_run_dir / f"trial-{repetition_index:04d}"
            result = _run_trial(
                suite=suite,
                sample=sample,
                trial=trial,
                run_dir=run_dir,
                budget=budget,
                repetition_index=repetition_index,
                sample_artifacts=sample_artifacts,
                runtime_map_prior=runtime_map_prior,
                agent_engine=engine.id,
                provider_profile=selected_provider_profile,
                model=model,
                live_execution=live_execution,
                skill_delivery_cell=skill_delivery_cell,
                live_timeout_s=live_timeout_s,
                live_stall_timeout_s=live_stall_timeout_s,
                regrade_source_dir=regrade_source_dir,
                product_runner=product_runner,
                live_product_runner=live_product_runner,
            )
            results.append(result)
            sample_artifacts[sample_artifact_key(sample.sample_id, repetition_index)] = (
                _sample_artifact_record(result, run_dir=run_dir)
            )
            if repetition_index == 0:
                sample_artifacts[sample.sample_id] = _sample_artifact_record(
                    result,
                    run_dir=run_dir,
                )

    bundle, results_path, report_path = persist_results(
        suite=suite, results=results, output_dir=output_dir, budget=budget
    )
    return EvalSuiteRun(
        suite=suite,
        output_dir=output_dir,
        results_path=results_path,
        report_path=report_path,
        bundle=bundle,
    )


def _default_run_stamp() -> str:
    return f"{time.strftime('%Y%m%dT%H%M%S')}-{os.getpid()}-{time.time_ns()}"
