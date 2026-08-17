"""Composition owner for repo-native eval suite execution."""

from __future__ import annotations

import os
import time
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from roboclaws.agents.skill_delivery import validate_skill_delivery_cell
from roboclaws.core.json_sources import read_json_object
from roboclaws.evals.agent_identity import (
    agent_engine_spec,
    eval_model_identity,
    eval_provider_profile,
    validate_sample_agent,
)
from roboclaws.evals.canonical_prior import promote_canonical_runtime_prior
from roboclaws.evals.dependencies import sample_artifact_key
from roboclaws.evals.harness import runner as harness_runner
from roboclaws.evals.live_runtime import DEFAULT_LIVE_WALL_CLOCK_BUDGET_S
from roboclaws.evals.map_build_reports import (
    discover_eval_results_paths,
    write_map_build_matrix_report,
)
from roboclaws.evals.models import (
    EVAL_TRIAL_SCHEMA,
    EvalResult,
    EvalSample,
    EvalSuite,
    EvalTrial,
)
from roboclaws.evals.phoenix_projection import project_completed_eval_to_phoenix
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
ResultObserver = Callable[[EvalResult], None]
_REGRADABLE_SAMPLE_IDENTITY_FIELDS = (
    "suite_id",
    "suite_version",
    "sample_id",
    "sample_version",
    "trial_id",
    "repetition_index",
    "surface",
    "intent",
    "preset",
    "world",
    "backend",
    "evidence_lane",
    "camera_labeler",
    "scenario_setup",
    "seed",
    "prompt",
    "goal_contract_hash",
    "prompt_source",
    "mcp_profile",
    "tool_surface",
)


@dataclass(frozen=True)
class EvalSuiteRun:
    """Paths and result bundle for one eval suite execution."""

    suite: EvalSuite
    output_dir: Path
    results_path: Path
    report_path: Path
    bundle: dict[str, Any]
    phoenix_projection: dict[str, object]


def run_cli_tool(mode: str, overrides: dict[str, str]) -> dict[str, object]:
    """Dispatch a non-suite eval CLI mode to its direct behavior owner."""
    if mode in {"evolve", "evolve-promote"}:
        from roboclaws.evals.evolution_control import run_evolution_command

        return run_evolution_command(mode, overrides, suite_runner=run_eval_suite)
    if mode == "phoenix-project":
        from roboclaws.evals.phoenix_projection import project_eval_to_phoenix

        return project_eval_to_phoenix(overrides)
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
    skill_delivery_cell = values.pop("skill_delivery_cell", None)
    skill_source_root = _optional_path(values.pop("skill_source_root", None))
    live_retry_limit = int(values.pop("live_retry_limit", "0"))
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
        skill_source_root=skill_source_root,
        live_retry_limit=live_retry_limit,
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
    live_timeout_s = (
        _optional_float(values.pop("live_timeout_s", None)) or DEFAULT_LIVE_WALL_CLOCK_BUDGET_S
    )
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
    skill_delivery_cell: str | None = None,
    skill_source_root: Path | None = None,
    skill_name: str | None = None,
    live_retry_limit: int = 0,
    live_timeout_s: float | None = None,
    live_stall_timeout_s: float | None = None,
    live_token_budget: float | None = None,
    live_cost_budget_usd: float | None = None,
    regrade_source: Path | None = None,
    runtime_map_prior: Path | None = None,
    product_runner: ProductRun = run_household_world_episode,
    live_product_runner: ProductRun | None = None,
    result_observer: ResultObserver | None = None,
) -> EvalSuiteRun:
    """Run a repo-native deterministic eval suite."""

    if live_execution not in {"blocked", "run"}:
        raise ValueError("live_execution must be blocked or run")
    selected_skill_delivery_cell = validate_skill_delivery_cell(skill_delivery_cell)
    if regrade_source is not None and agent_engine == "direct-runner":
        raise ValueError("regrade_source is only supported for live-agent eval runs")

    suite, samples = load_suite(suite_ref)
    validate_suite_runtime_map_prior(suite, runtime_map_prior)
    engine = agent_engine_spec(agent_engine)
    regrade_source_dir = resolved_regrade_source(regrade_source, suite=suite)
    regrade_trials: dict[tuple[str, int], EvalTrial] = {}
    result_budget = budget
    if regrade_source_dir is not None:
        regrade_trials, result_budget = _load_regrade_trials(
            regrade_source_dir,
            suite=suite,
            samples=samples,
        )
    else:
        selected_provider_profile = eval_provider_profile(
            agent_engine=engine.id,
            provider_profile=provider_profile,
        )
        selected_model_identity = eval_model_identity(
            agent_engine=engine.id,
            provider_profile=selected_provider_profile,
            model=model,
        )
    run_stamp = stamp or _default_run_stamp()
    output_dir = output_root / path_token(suite.suite_id) / run_stamp
    output_dir.mkdir(parents=True, exist_ok=True)

    results: list[EvalResult] = []
    sample_artifacts: dict[str, dict[str, Any]] = {}
    for sample in samples:
        validate_sample_agent(sample, agent_engine=engine.id)
        for repetition_index in range(sample.trial_count):
            if regrade_source_dir is not None:
                trial = regrade_trials[(sample.sample_id, repetition_index)]
                _validate_regrade_trial(
                    trial,
                    suite=suite,
                    sample=sample,
                    repetition_index=repetition_index,
                    budget=budget,
                    agent_engine=engine.id,
                    runner_class=engine.internal_runner_class,
                    provider_profile=provider_profile,
                    model=model,
                    skill_name=skill_name,
                    skill_delivery_cell=skill_delivery_cell,
                )
                trial_provider_profile = trial.provider_profile
                trial_model = None
                trial_skill_delivery_cell = str(trial.runtime["skill_delivery_cell"])
            else:
                trial = _trial_from_sample(
                    suite=suite,
                    sample=sample,
                    repetition_index=repetition_index,
                    budget=budget,
                    agent_engine=engine.id,
                    runner_class=engine.internal_runner_class,
                    provider_profile=selected_provider_profile,
                    model=selected_model_identity,
                    skill_name=skill_name,
                    skill_delivery_cell=selected_skill_delivery_cell,
                )
                trial_provider_profile = selected_provider_profile
                trial_model = model
                trial_skill_delivery_cell = selected_skill_delivery_cell
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
                provider_profile=trial_provider_profile,
                model=trial_model,
                live_execution=live_execution,
                skill_delivery_cell=trial_skill_delivery_cell,
                live_timeout_s=live_timeout_s,
                live_stall_timeout_s=live_stall_timeout_s,
                live_token_budget=live_token_budget,
                live_cost_budget_usd=live_cost_budget_usd,
                regrade_source_dir=regrade_source_dir,
                product_runner=product_runner,
                live_product_runner=live_product_runner,
                skill_source_root=skill_source_root,
                live_retry_limit=live_retry_limit,
            )
            results.append(result)
            if result_observer is not None:
                result_observer(result)
            sample_artifacts[sample_artifact_key(sample.sample_id, repetition_index)] = (
                _sample_artifact_record(result, run_dir=run_dir)
            )
            if repetition_index == 0:
                sample_artifacts[sample.sample_id] = _sample_artifact_record(
                    result,
                    run_dir=run_dir,
                )

    bundle, results_path, report_path = persist_results(
        suite=suite, results=results, output_dir=output_dir, budget=result_budget
    )
    phoenix_projection = project_completed_eval_to_phoenix(
        suite_ref=suite_ref,
        eval_results_path=results_path,
    )
    return EvalSuiteRun(
        suite=suite,
        output_dir=output_dir,
        results_path=results_path,
        report_path=report_path,
        bundle=bundle,
        phoenix_projection=phoenix_projection,
    )


def _default_run_stamp() -> str:
    return f"{time.strftime('%Y%m%dT%H%M%S')}-{os.getpid()}-{time.time_ns()}"


def _load_regrade_trials(
    source_dir: Path,
    *,
    suite: EvalSuite,
    samples: list[EvalSample],
) -> tuple[dict[tuple[str, int], EvalTrial], str]:
    payload = read_json_object(source_dir / "eval_results.json", label="regrade eval results")
    result_payloads, source_budget = _validated_regrade_bundle(payload, suite=suite)
    trials = _regrade_trials_from_results(result_payloads)

    expected_keys = {
        (sample.sample_id, repetition_index)
        for sample in samples
        for repetition_index in range(sample.trial_count)
    }
    if set(trials) != expected_keys:
        missing = sorted(expected_keys - set(trials))
        unexpected = sorted(set(trials) - expected_keys)
        raise ValueError(
            "regrade_source trial set does not match the exact suite release: "
            f"missing={missing}, unexpected={unexpected}"
        )
    return trials, source_budget


def _validated_regrade_bundle(
    payload: dict[str, Any], *, suite: EvalSuite
) -> tuple[list[Any], str]:
    if payload.get("schema") != "roboclaws_eval_results_bundle_v1":
        raise ValueError("regrade_source must contain a roboclaws eval results bundle")
    source_suite_payload = payload.get("suite")
    if not isinstance(source_suite_payload, dict):
        raise ValueError("regrade_source suite identity must be an object")
    source_suite = EvalSuite.from_mapping(source_suite_payload)
    if (
        source_suite.suite_id != suite.suite_id
        or source_suite.version != suite.version
        or source_suite.sample_ids != suite.sample_ids
    ):
        raise ValueError("regrade_source must match the exact suite release and sample set")
    source_budget = payload.get("budget")
    if not isinstance(source_budget, str) or not source_budget:
        raise ValueError("regrade_source budget must be a non-empty string")
    result_payloads = payload.get("results")
    if not isinstance(result_payloads, list):
        raise ValueError("regrade_source results must be an array")
    return result_payloads, source_budget


def _regrade_trials_from_results(
    result_payloads: list[Any],
) -> dict[tuple[str, int], EvalTrial]:
    trials: dict[tuple[str, int], EvalTrial] = {}
    for index, result_payload in enumerate(result_payloads):
        if not isinstance(result_payload, dict):
            raise ValueError(f"regrade_source result {index} must be an object")
        result = EvalResult.from_mapping(result_payload)
        if result.identity.get("schema") != "roboclaws_eval_identity_v1":
            raise ValueError(f"regrade_source result {index} has invalid identity schema")
        trial = EvalTrial.from_mapping(dict(result.identity) | {"schema": EVAL_TRIAL_SCHEMA})
        key = (trial.sample_id, trial.repetition_index)
        if key in trials:
            raise ValueError(
                "regrade_source contains duplicate trial identity for "
                f"{trial.sample_id} repetition {trial.repetition_index}"
            )
        trials[key] = trial
    return trials


def _validate_regrade_trial(
    source_trial: EvalTrial,
    *,
    suite: EvalSuite,
    sample: EvalSample,
    repetition_index: int,
    budget: str,
    agent_engine: str,
    runner_class: str,
    provider_profile: str | None,
    model: str | None,
    skill_name: str | None,
    skill_delivery_cell: str | None,
) -> None:
    _validate_regrade_sample_identity(
        source_trial,
        suite=suite,
        sample=sample,
        repetition_index=repetition_index,
        budget=budget,
    )
    source_cell = _validate_regrade_source_execution_identity(
        source_trial,
        agent_engine=agent_engine,
        runner_class=runner_class,
    )
    _validate_regrade_execution_overrides(
        source_trial,
        agent_engine=agent_engine,
        source_cell=source_cell,
        provider_profile=provider_profile,
        model=model,
        skill_name=skill_name,
        skill_delivery_cell=skill_delivery_cell,
    )


def _validate_regrade_sample_identity(
    source_trial: EvalTrial,
    *,
    suite: EvalSuite,
    sample: EvalSample,
    repetition_index: int,
    budget: str,
) -> None:
    expected = _trial_from_sample(
        suite=suite,
        sample=sample,
        repetition_index=repetition_index,
        budget=budget,
        agent_engine=source_trial.agent_engine,
        runner_class=source_trial.runner_class,
        provider_profile=source_trial.provider_profile,
        model=source_trial.model,
        skill_name=source_trial.skill_name,
        skill_delivery_cell=str(source_trial.runtime.get("skill_delivery_cell") or ""),
    )
    mismatches = [
        field
        for field in _REGRADABLE_SAMPLE_IDENTITY_FIELDS
        if getattr(source_trial, field) != getattr(expected, field)
    ]
    if mismatches:
        raise ValueError(
            "regrade_source trial does not match the exact suite/sample release: "
            + ", ".join(mismatches)
        )


def _validate_regrade_source_execution_identity(
    source_trial: EvalTrial,
    *,
    agent_engine: str,
    runner_class: str,
) -> str:
    if source_trial.agent_engine != agent_engine or source_trial.runner_class != runner_class:
        raise ValueError("regrade agent_engine does not match source execution identity")
    validated_source_provider = eval_provider_profile(
        agent_engine=agent_engine,
        provider_profile=source_trial.provider_profile,
    )
    if validated_source_provider != source_trial.provider_profile:
        raise ValueError("regrade_source has invalid provider execution identity")
    source_cell = source_trial.runtime.get("skill_delivery_cell")
    if not isinstance(source_cell, str) or validate_skill_delivery_cell(source_cell) != source_cell:
        raise ValueError("regrade_source has invalid skill delivery identity")
    return source_cell


def _validate_regrade_execution_overrides(
    source_trial: EvalTrial,
    *,
    agent_engine: str,
    source_cell: str,
    provider_profile: str | None,
    model: str | None,
    skill_name: str | None,
    skill_delivery_cell: str | None,
) -> None:
    if provider_profile is not None:
        requested_provider = eval_provider_profile(
            agent_engine=agent_engine,
            provider_profile=provider_profile,
        )
        if source_trial.provider_profile != requested_provider:
            raise ValueError("regrade provider_profile does not match source execution identity")
    if model is not None:
        requested_model = eval_model_identity(
            agent_engine=agent_engine,
            provider_profile=source_trial.provider_profile,
            model=model,
        )
        if source_trial.model != requested_model:
            raise ValueError("regrade model does not match source execution identity")
    if skill_name is not None and source_trial.skill_name != skill_name:
        raise ValueError("regrade skill_name does not match source execution identity")
    if skill_delivery_cell is not None:
        requested_cell = validate_skill_delivery_cell(skill_delivery_cell)
        if source_cell != requested_cell:
            raise ValueError("regrade skill_delivery_cell does not match source execution identity")
