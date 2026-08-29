"""Deterministic, live, and regrade trial execution."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Callable

from roboclaws.agents.skill_delivery import sandbox_readiness
from roboclaws.evals import long_horizon_contract
from roboclaws.evals.agent_identity import blocked_result_from_live_agent_request
from roboclaws.evals.dependencies import dependency_failure, resolve_artifact_dependencies
from roboclaws.evals.grading import (
    _diagnostic_status_from_graders,
    _grade_trial,
    _metrics_from_graders,
    _status_from_graders,
)
from roboclaws.evals.grading_failures import blocked_result_from_exception
from roboclaws.evals.grading_sources import (
    artifact_paths,
    load_optional_json_mapping,
    load_required_json_mapping,
)
from roboclaws.evals.live_execution import (
    LiveTrialHooks,
    run_live_eval_trial,
    run_live_surface_product,
)
from roboclaws.evals.live_runtime import product_run_kwargs
from roboclaws.evals.models import (
    MISSING_NOT_APPLICABLE,
    MISSING_UNAVAILABLE,
    EvalResult,
    EvalSample,
    EvalSuite,
    EvalTrial,
)
from roboclaws.evals.suite_loading import REPO_ROOT
from roboclaws.household.household_backend_contract import SYNTHETIC_BACKEND
from roboclaws.household.realworld_contract_payloads import (
    HOUSEHOLD_EPISODE_PROFILE,
    HOUSEHOLD_MANIPULATION_PROFILE,
    HOUSEHOLD_WORLD_PROFILE,
    contract_profile,
)

ProductRun = Callable[..., dict[str, Any]]


def _trial_from_sample(
    *,
    suite: EvalSuite,
    sample: EvalSample,
    repetition_index: int,
    budget: str,
    agent_engine: str,
    runner_class: str,
    provider_profile: str,
    model: str | None,
    skill_name: str | None = None,
    skill_delivery_cell: str = "static-full",
) -> EvalTrial:
    limitations: list[str] = []
    if (
        budget == "smoke"
        and sample.backend != SYNTHETIC_BACKEND
        and agent_engine == "direct-runner"
    ):
        limitations.append("smoke_budget_uses_synthetic_backend_for_local_determinism")
    return EvalTrial.from_sample(
        sample,
        suite=suite,
        trial_id=f"{path_token(sample.sample_id)}-{repetition_index:04d}",
        repetition_index=repetition_index,
        agent_engine=agent_engine,
        runner_class=runner_class,
        provider_profile=provider_profile,
        model=model or MISSING_NOT_APPLICABLE,
        skill_name=_skill_name(sample, override=skill_name),
        prompt_source=MISSING_NOT_APPLICABLE
        if sample.prompt == MISSING_NOT_APPLICABLE
        else "sample",
        mcp_profile=_mcp_profile(sample),
        tool_surface=_tool_surface(sample),
        budgets={
            "steps": _budget_steps(budget),
            "time_s": MISSING_UNAVAILABLE,
            "token": MISSING_NOT_APPLICABLE,
            "cost": MISSING_NOT_APPLICABLE,
        },
        runtime={
            "host": MISSING_UNAVAILABLE,
            "hardware": "local_cpu",
            "network": MISSING_NOT_APPLICABLE,
            "local_live_limitations": [],
            "skill_delivery_cell": skill_delivery_cell,
        },
        limitations=limitations,
    )


def _run_trial(
    *,
    suite: EvalSuite,
    sample: EvalSample,
    trial: EvalTrial,
    run_dir: Path,
    budget: str,
    repetition_index: int,
    sample_artifacts: dict[str, dict[str, Any]],
    runtime_map_prior: Path | None,
    agent_engine: str,
    provider_profile: str,
    model: str | None,
    live_execution: str,
    skill_delivery_cell: str = "static-full",
    live_timeout_s: float | None,
    live_stall_timeout_s: float | None,
    live_token_budget: float | None,
    live_cost_budget_usd: float | None,
    regrade_source_dir: Path | None,
    product_runner: ProductRun,
    live_product_runner: ProductRun | None,
    skill_source_root: Path | None = None,
    live_retry_limit: int = 0,
) -> EvalResult:
    run_dir.mkdir(parents=True, exist_ok=True)
    if agent_engine != "direct-runner":
        if regrade_source_dir is not None:
            return _regrade_live_eval_trial(
                sample=sample,
                trial=trial,
                run_dir=run_dir,
                repetition_index=repetition_index,
                sample_artifacts=sample_artifacts,
                runtime_map_prior=runtime_map_prior,
                regrade_source_dir=regrade_source_dir,
            )
        if skill_delivery_cell == "sandbox-skills":
            posture = sandbox_readiness()
            if posture["status"] != "ready":
                return blocked_result_from_exception(
                    trial,
                    RuntimeError(f"sandbox-skills unavailable: {posture['reason']}"),
                )
        if live_execution == "run":
            return run_live_eval_trial(
                sample=sample,
                trial=trial,
                run_dir=run_dir,
                budget=budget,
                repetition_index=repetition_index,
                sample_artifacts=sample_artifacts,
                runtime_map_prior=runtime_map_prior,
                agent_engine=agent_engine,
                provider_profile=provider_profile,
                model=model,
                live_timeout_s=live_timeout_s,
                live_stall_timeout_s=live_stall_timeout_s,
                live_token_budget=live_token_budget,
                live_cost_budget_usd=live_cost_budget_usd,
                skill_delivery_cell=skill_delivery_cell,
                skill_source_root=skill_source_root,
                live_retry_limit=live_retry_limit,
                live_product_runner=live_product_runner or run_live_surface_product,
                hooks=LiveTrialHooks(
                    failed_result_from_dependency=_failed_result_from_dependency,
                    blocked_result_from_exception=blocked_result_from_exception,
                    grade_trial=_grade_trial,
                    status_from_graders=_status_from_graders,
                    artifact_paths=artifact_paths,
                    metrics_from_graders=_metrics_from_graders,
                ),
            )
        return blocked_result_from_live_agent_request(
            trial,
            agent_engine=agent_engine,
            run_dir=run_dir,
        )
    try:
        dependency_artifacts = resolve_artifact_dependencies(
            sample,
            repetition_index=repetition_index,
            sample_artifacts=sample_artifacts,
            runtime_map_prior=runtime_map_prior,
        )
        failure = dependency_failure(dependency_artifacts)
    except Exception as exc:  # noqa: BLE001 - eval packets must classify metadata failures.
        return blocked_result_from_exception(trial, exc)
    if failure is not None:
        return _failed_result_from_dependency(trial, run_dir, failure)
    try:
        kwargs = product_run_kwargs(
            sample,
            run_dir=run_dir,
            budget=budget,
            dependency_artifacts=dependency_artifacts,
        )
        run_result = product_runner(**kwargs)
    except Exception as exc:  # noqa: BLE001 - eval packets must classify runner failures.
        return blocked_result_from_exception(trial, exc)

    grader_outputs = _grade_trial(
        sample=sample,
        run_dir=run_dir,
        run_result=run_result,
        dependency_artifacts=dependency_artifacts,
    )
    status, failure_class = _status_from_graders(grader_outputs)
    artifacts = artifact_paths(run_dir)
    metrics = _metrics_from_graders(grader_outputs, status=status, run_result=run_result)
    return EvalResult.from_trial(
        trial,
        status=status,
        capability_status=status,
        diagnostic_status=_diagnostic_status_from_graders(grader_outputs),
        failure_class=failure_class,
        grader_outputs=grader_outputs,
        artifacts=artifacts,
        artifact_schema_versions={key: MISSING_UNAVAILABLE for key in artifacts},
        metrics=metrics,
        limitations=trial.limitations,
    )


def _regrade_live_eval_trial(
    *,
    sample: EvalSample,
    trial: EvalTrial,
    run_dir: Path,
    repetition_index: int,
    sample_artifacts: dict[str, dict[str, Any]],
    runtime_map_prior: Path | None,
    regrade_source_dir: Path,
) -> EvalResult:
    try:
        dependency_artifacts = resolve_artifact_dependencies(
            sample,
            repetition_index=repetition_index,
            sample_artifacts=sample_artifacts,
            runtime_map_prior=runtime_map_prior,
        )
        failure = dependency_failure(dependency_artifacts)
        if failure is not None:
            return _failed_result_from_dependency(trial, run_dir, failure)
        source_run_dir = _regrade_effective_run_dir(
            regrade_source_dir,
            sample=sample,
            repetition_index=repetition_index,
        )
        run_result = _load_required_regrade_run_result(source_run_dir)
    except Exception as exc:  # noqa: BLE001 - eval packets must classify regrade failures.
        return blocked_result_from_exception(trial, exc)

    grader_outputs = _grade_trial(
        sample=sample,
        run_dir=source_run_dir,
        run_result=run_result,
        dependency_artifacts=dependency_artifacts,
    )
    status, failure_class = _status_from_graders(grader_outputs)
    artifacts = artifact_paths(source_run_dir)
    metrics = _metrics_from_graders(grader_outputs, status=status, run_result=run_result)
    return EvalResult.from_trial(
        trial,
        status=status,
        capability_status=status,
        diagnostic_status=_diagnostic_status_from_graders(grader_outputs),
        failure_class=failure_class,
        grader_outputs=grader_outputs,
        artifacts=artifacts,
        artifact_schema_versions={key: MISSING_UNAVAILABLE for key in artifacts},
        metrics=metrics,
        limitations=(*trial.limitations, "live_eval_regraded_from_existing_artifacts"),
    )


def _regrade_effective_run_dir(
    regrade_source_dir: Path,
    *,
    sample: EvalSample,
    repetition_index: int,
) -> Path:
    trial_dir = (
        regrade_source_dir / "runs" / path_token(sample.sample_id) / f"trial-{repetition_index:04d}"
    )
    command_record = trial_dir / "live_eval_command.json"
    if command_record.is_file():
        record, error = load_optional_json_mapping(command_record)
        effective = str(record.get("effective_run_dir") or "").strip() if not error else ""
        if effective:
            path = Path(effective)
            if not path.is_absolute():
                path = (REPO_ROOT / path).resolve()
            else:
                path = path.resolve()
            if not path.is_relative_to(trial_dir.resolve()):
                raise ValueError(
                    f"regrade effective run dir must stay under source trial dir {trial_dir}, "
                    f"got {path}"
                )
            if not path.is_dir():
                raise ValueError(f"regrade effective run dir does not exist: {path}")
            return path
    surface_root = trial_dir / "surface-run"
    candidates = sorted(surface_root.glob(f"**/seed-{sample.seed}"))
    if not candidates and surface_root.is_dir():
        candidates = [surface_root]
    for candidate in candidates:
        if (candidate / "run_result.json").is_file():
            return candidate
    raise ValueError(f"regrade_source has no live artifacts for sample {sample.sample_id}")


def _load_required_regrade_run_result(run_dir: Path) -> dict[str, Any]:
    run_result, error = load_required_json_mapping(run_dir / "run_result.json")
    if error:
        raise ValueError(f"invalid regrade run_result: {error}")
    return run_result


def _failed_result_from_dependency(
    trial: EvalTrial,
    run_dir: Path,
    dependency_failure: dict[str, Any],
) -> EvalResult:
    failure_class = str(dependency_failure.get("failure_class") or "artifact_missing")
    blocked = failure_class in {"environment_blocked", "model_or_provider_unavailable"}
    artifacts = artifact_paths(run_dir)
    return EvalResult.from_trial(
        trial,
        status="blocked" if blocked else "failed",
        failure_class=failure_class,
        grader_outputs={
            "artifacts": {
                "status": "blocked" if blocked else "failed",
                "missing": [],
                "missing_dependencies": dependency_failure.get("missing_dependencies", []),
                "resolved_dependencies": dependency_failure.get("resolved_dependencies", {}),
                "required": {},
            },
            "runner": {
                "status": "blocked" if blocked else "failed",
                "error_type": "EvalDependencyError",
                "message": str(dependency_failure.get("message") or ""),
            },
        },
        artifacts=artifacts,
        artifact_schema_versions={key: MISSING_UNAVAILABLE for key in artifacts},
        metrics={"pass": 0.0},
        limitations=(*trial.limitations, "eval_dependency_missing_before_product_run"),
    )


def _sample_artifact_record(result: EvalResult, *, run_dir: Path) -> dict[str, Any]:
    artifacts = result.artifacts or artifact_paths(run_dir)
    return {
        **artifacts,
        "source_status": result.status,
        "source_failure_class": result.failure_class,
        "source_sample_id": str(result.identity.get("sample_id") or ""),
    }


def _skill_name(sample: EvalSample, *, override: str | None = None) -> str:
    if override:
        if override in {".", ".."} or "/" in override or "\\" in override:
            raise ValueError("eval skill_name must be one normalized path segment")
        return override
    if sample.surface == "household-world":
        return "household-world"
    return MISSING_UNAVAILABLE


def _mcp_profile(sample: EvalSample) -> str:
    if long_horizon_contract.manipulation_required(sample, sample.intent == "cleanup"):
        return "household_world+household_manipulation"
    return "household_world+household_episode"


def _tool_surface(sample: EvalSample) -> tuple[str, ...]:
    profiles = [HOUSEHOLD_WORLD_PROFILE, HOUSEHOLD_EPISODE_PROFILE]
    if long_horizon_contract.manipulation_required(sample, sample.intent == "cleanup"):
        profiles.insert(1, HOUSEHOLD_MANIPULATION_PROFILE)
    return tuple(
        name for profile_id in profiles for name in contract_profile(profile_id).public_tool_names()
    )


def _budget_steps(budget: str) -> int | str:
    return {"smoke": 50, "focused": 100}.get(budget, MISSING_UNAVAILABLE)


def path_token(value: str) -> str:
    return str(value).replace("/", "_").replace(".", "_")
