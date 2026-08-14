from __future__ import annotations

import json
import os
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

from roboclaws.core.json_sources import collect_jsonl_object_rows, read_json_object
from roboclaws.evals import long_horizon_contract
from roboclaws.evals import long_horizon_grader as lhg
from roboclaws.evals.agent_identity import (
    agent_engine_spec,
    blocked_result_from_live_agent_request,
    eval_provider_profile,
    validate_sample_agent,
)
from roboclaws.evals.dependencies import (
    dependency_failure,
    resolve_artifact_dependencies,
    sample_artifact_key,
)
from roboclaws.evals.live_runtime import (
    LiveTrialHooks,
    product_run_kwargs,
    run_live_eval_trial,
    run_live_surface_product,
)
from roboclaws.evals.live_timeout import LiveEvalTimeoutError, live_exception_debug_fields
from roboclaws.evals.map_build_quality import grade_runtime_metric_map_quality
from roboclaws.evals.models import (
    MISSING_NOT_APPLICABLE,
    MISSING_UNAVAILABLE,
    EvalResult,
    EvalSample,
    EvalSuite,
    EvalTrial,
    load_eval_sample,
    load_eval_suite,
)
from roboclaws.evals.reports import render_eval_report, results_bundle
from roboclaws.household.household_backend_contract import SYNTHETIC_BACKEND
from roboclaws.household.household_world_episode import run_household_world_episode

REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_OUTPUT_ROOT = REPO_ROOT / "output" / "evals"
ProductRun = Callable[..., dict[str, Any]]


@dataclass(frozen=True)
class EvalSuiteRun:
    """Paths and result bundle for one eval suite execution."""

    suite: EvalSuite
    output_dir: Path
    results_path: Path
    report_path: Path
    bundle: dict[str, Any]


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
    if regrade_source is not None and agent_engine == "direct-runner":
        raise ValueError("regrade_source is only supported for live-agent eval runs")

    suite_path = resolve_suite_path(suite_ref)
    suite = load_eval_suite(suite_path)
    samples = _load_suite_samples(suite)
    _validate_suite_runtime_map_prior(suite, runtime_map_prior)
    engine = agent_engine_spec(agent_engine)
    selected_provider_profile = eval_provider_profile(
        agent_engine=engine.id,
        provider_profile=provider_profile,
    )
    regrade_source_dir = _resolved_regrade_source(regrade_source, suite=suite)
    run_stamp = stamp or _default_run_stamp()
    output_dir = output_root / _path_token(suite.suite_id) / run_stamp
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
            )
            sample_run_dir = output_dir / "runs" / _path_token(sample.sample_id)
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

    bundle = results_bundle(suite=suite, results=results, output_dir=output_dir, budget=budget)
    results_path = output_dir / "eval_results.json"
    report_path = output_dir / "eval_report.html"
    _write_json(results_path, bundle)
    report_path.write_text(render_eval_report(bundle), encoding="utf-8")
    bundle["artifacts"]["eval_results"] = str(results_path)
    bundle["artifacts"]["eval_report"] = str(report_path)
    _write_json(results_path, bundle)
    return EvalSuiteRun(
        suite=suite,
        output_dir=output_dir,
        results_path=results_path,
        report_path=report_path,
        bundle=bundle,
    )


def resolve_suite_path(suite_ref: str) -> Path:
    """Resolve a suite id, short name, or JSON path to a suite file."""

    raw = str(suite_ref or "").strip()
    if not raw:
        raw = "smoke_regression"
    candidate = Path(raw)
    if candidate.suffix == ".json":
        path = candidate if candidate.is_absolute() else REPO_ROOT / candidate
        if path.exists():
            return path
    short = raw.removeprefix("household_world.")
    path = REPO_ROOT / "evals" / "household_world" / "suites" / f"{short}.json"
    if path.exists():
        return path
    raise ValueError(f"unknown eval suite {suite_ref!r}")


def _resolved_regrade_source(regrade_source: Path | None, *, suite: EvalSuite) -> Path | None:
    if regrade_source is None:
        return None
    source = Path(regrade_source)
    if not source.is_absolute():
        source = REPO_ROOT / source
    source = source.resolve()
    if not source.is_dir():
        raise ValueError(f"regrade_source does not exist or is not a directory: {source}")
    if source.name == _path_token(suite.suite_id) and (source / "eval_results.json").is_file():
        return source
    suite_dir = source / _path_token(suite.suite_id)
    if suite_dir.is_dir():
        return suite_dir.resolve()
    if (source / "eval_results.json").is_file():
        return source
    raise ValueError(
        "regrade_source must point to an existing eval run directory for "
        f"{suite.suite_id} or an output root containing it"
    )


def _load_suite_samples(suite: EvalSuite) -> list[EvalSample]:
    if not suite.sample_refs:
        raise ValueError(f"eval suite {suite.suite_id!r} has no sample_refs")
    samples = [load_eval_sample(REPO_ROOT / ref) for ref in suite.sample_refs]
    loaded_ids = tuple(sample.sample_id for sample in samples)
    if loaded_ids != suite.sample_ids:
        raise ValueError(
            f"eval suite {suite.suite_id!r} sample_refs resolve to {loaded_ids}, "
            f"expected {suite.sample_ids}"
        )
    return samples


def _validate_suite_runtime_map_prior(suite: EvalSuite, runtime_map_prior: Path | None) -> None:
    mode = str((suite.metadata or {}).get("execution_mode") or "")
    if mode == "task_matrix_on_fixed_map" and runtime_map_prior is None:
        raise ValueError(f"eval suite {suite.suite_id!r} requires runtime_map_prior=<path>")
    if mode != "task_matrix_on_fixed_map" and runtime_map_prior is not None:
        raise ValueError(
            "runtime_map_prior suite override is only valid for task_matrix_on_fixed_map suites"
        )


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
        trial_id=f"{_path_token(sample.sample_id)}-{repetition_index:04d}",
        repetition_index=repetition_index,
        agent_engine=agent_engine,
        runner_class=runner_class,
        provider_profile=provider_profile,
        model=model or MISSING_NOT_APPLICABLE,
        skill_name=_skill_name(sample),
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
    live_timeout_s: float | None,
    live_stall_timeout_s: float | None,
    regrade_source_dir: Path | None,
    product_runner: ProductRun,
    live_product_runner: ProductRun | None,
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
                live_product_runner=live_product_runner or run_live_surface_product,
                hooks=LiveTrialHooks(
                    failed_result_from_dependency=_failed_result_from_dependency,
                    blocked_result_from_exception=_blocked_result_from_exception,
                    grade_trial=_grade_trial,
                    status_from_graders=_status_from_graders,
                    artifact_paths=_artifact_paths,
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
        return _blocked_result_from_exception(trial, exc)
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
        return _blocked_result_from_exception(trial, exc)

    grader_outputs = _grade_trial(
        sample=sample,
        run_dir=run_dir,
        run_result=run_result,
        dependency_artifacts=dependency_artifacts,
    )
    status, failure_class = _status_from_graders(grader_outputs)
    artifacts = _artifact_paths(run_dir)
    metrics = _metrics_from_graders(grader_outputs, status=status, run_result=run_result)
    return EvalResult.from_trial(
        trial,
        status=status,
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
        return _blocked_result_from_exception(trial, exc)

    grader_outputs = _grade_trial(
        sample=sample,
        run_dir=source_run_dir,
        run_result=run_result,
        dependency_artifacts=dependency_artifacts,
    )
    status, failure_class = _status_from_graders(grader_outputs)
    artifacts = _artifact_paths(source_run_dir)
    metrics = _metrics_from_graders(grader_outputs, status=status, run_result=run_result)
    return EvalResult.from_trial(
        trial,
        status=status,
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
        regrade_source_dir
        / "runs"
        / _path_token(sample.sample_id)
        / f"trial-{repetition_index:04d}"
    )
    command_record = trial_dir / "live_eval_command.json"
    if command_record.is_file():
        record, error = _load_optional_json_mapping(command_record)
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
    run_result, error = _load_required_json_mapping(run_dir / "run_result.json")
    if error:
        raise ValueError(f"invalid regrade run_result: {error}")
    return run_result


def _grade_trial(
    *,
    sample: EvalSample,
    run_dir: Path,
    run_result: dict[str, Any],
    dependency_artifacts: dict[str, Any] | None,
) -> dict[str, Any]:
    return {
        "artifacts": _artifact_grader(run_dir, dependency_artifacts=dependency_artifacts),
        "privacy": _privacy_grader(run_result),
        "trajectory": _trajectory_grader(sample=sample, run_dir=run_dir, run_result=run_result),
        "outcome": _outcome_grader(sample=sample, run_dir=run_dir, run_result=run_result),
        "long_horizon": lhg.grade_long_horizon_task(sample, run_dir=run_dir, run_result=run_result),
        "sampler_admission": _sampler_admission_grader(sample=sample),
        "open_ended": _open_ended_grader(sample=sample, run_dir=run_dir, run_result=run_result),
        "efficiency": _efficiency_grader(run_dir=run_dir, run_result=run_result),
    }


def _artifact_grader(
    run_dir: Path,
    *,
    dependency_artifacts: dict[str, Any] | None,
) -> dict[str, Any]:
    required = {
        "run_result": run_dir / "run_result.json",
        "report": run_dir / "report.html",
        "trace": run_dir / "trace.jsonl",
        "agent_view": run_dir / "agent_view.json",
        "runtime_metric_map": run_dir / "runtime_metric_map.json",
        "private_evaluation": run_dir / "private_evaluation.json",
    }
    missing = [name for name, path in required.items() if not path.exists()]
    source_errors = _required_json_artifact_source_errors(
        {
            name: required[name]
            for name in (
                "run_result",
                "agent_view",
                "runtime_metric_map",
                "private_evaluation",
            )
        }
    )
    return {
        "status": "failed" if missing or source_errors else "passed",
        "failure_class": (
            "artifact_missing" if missing or source_errors else MISSING_NOT_APPLICABLE
        ),
        "missing": missing,
        "source_errors": source_errors,
        "resolved_dependencies": dict(dependency_artifacts or {}),
        "required": {name: str(path) for name, path in required.items()},
    }


def _privacy_grader(run_result: dict[str, Any]) -> dict[str, Any]:
    leaked = []
    if run_result.get("policy_uses_private_truth") is True:
        leaked.append("policy_uses_private_truth")
    if run_result.get("planner_uses_private_manifest") is True:
        leaked.append("planner_uses_private_manifest")
    agent_view = (
        run_result.get("agent_view") if isinstance(run_result.get("agent_view"), dict) else {}
    )
    for key in ("private_manifest", "acceptable_destinations", "hidden_target_list"):
        if key in agent_view:
            leaked.append(f"agent_view.{key}")
    return {
        "status": "failed" if leaked else "passed",
        "private_truth_leak_count": len(leaked),
        "leaked_fields": leaked,
    }


def _trajectory_grader(
    *,
    sample: EvalSample,
    run_dir: Path,
    run_result: dict[str, Any],
) -> dict[str, Any]:
    trace_events, trace_errors = _read_trace_events_with_errors(run_dir / "trace.jsonl")
    response_tools = {
        str(event.get("tool"))
        for event in trace_events
        if event.get("event") == "response" and event.get("tool")
    }
    required_groups = (
        {"done"},
        {"metric_map", "resolve_target_query"} if sample.intent == "open-ended" else {"metric_map"},
    )
    missing_tools = sorted(
        ",".join(sorted(group))
        for group in required_groups
        if not response_tools.intersection(group)
    )
    static_fixture_projection_count = sum(
        1 for event in trace_events if event.get("tool") == "static_fixture_projection"
    )
    violations = list(missing_tools)
    failed_or_noop_count = _int_value(
        run_result.get("score", {}).get("failed_or_noop_tool_count")
        if isinstance(run_result.get("score"), dict)
        else None
    )
    if failed_or_noop_count > 0:
        violations.append("failed_or_noop_tool")
    if trace_errors:
        violations.append("trace_json_invalid")
    return {
        "status": "failed" if violations else "passed",
        "failure_class": ("trajectory_policy_violation" if violations else MISSING_NOT_APPLICABLE),
        "missing_required_tools": missing_tools,
        "violation_count": len(violations),
        "violations": violations,
        "trace_parse_errors": trace_errors,
        "static_fixture_projection_trace_count": static_fixture_projection_count,
        "static_fixture_projection_policy": (
            "direct_runner_internal_compatibility"
            if sample.allowed_agent_engines == ("direct-runner",)
            else "trajectory_violation_for_live_mcp"
        ),
    }


def _outcome_grader(
    *,
    sample: EvalSample,
    run_dir: Path,
    run_result: dict[str, Any],
) -> dict[str, Any]:
    if sample.intent == "map-build":
        runtime_map_path = run_dir / "runtime_metric_map.json"
        runtime_map, runtime_map_error = _load_required_json_mapping(runtime_map_path)
        return grade_runtime_metric_map_quality(
            runtime_map=runtime_map,
            runtime_map_exists=runtime_map_path.exists(),
            runtime_map_error=runtime_map_error,
            config=sample.grader_config or {},
            private_goal_reference=_map_build_private_goal_reference(
                sample=sample,
                run_dir=run_dir,
                run_result=run_result,
            ),
        )
    if sample.intent == "open-ended":
        open_ended = _open_ended_grader(sample=sample, run_dir=run_dir, run_result=run_result)
        return {
            "status": open_ended["status"],
            "completion_claim_present": open_ended["completion_claim_present"],
            "artifact_readiness": open_ended["artifact_readiness"],
            "semantic_satisfaction_status": open_ended["semantic_satisfaction_status"],
            "open_ended_category": open_ended["open_ended_category"],
            "expected_goal_outcome": open_ended["expected_goal_outcome"],
            "success_predicate": open_ended["success_predicate"],
        }
    score = run_result.get("score") if isinstance(run_result.get("score"), dict) else {}
    completion_status = str(
        score.get("completion_status")
        or run_result.get("completion_status")
        or run_result.get("cleanup_status")
        or ""
    )
    semantic_acceptability = (
        score.get("semantic_acceptability")
        if isinstance(score.get("semantic_acceptability"), dict)
        else {}
    )
    semantic_completion_status = str(semantic_acceptability.get("status") or "")
    passed = completion_status in {"passed", "success", "complete", "completed"} or (
        sample.intent == "cleanup" and semantic_completion_status == "success"
    )
    return {
        "status": "passed" if passed else "failed",
        "completion_status": completion_status,
        "semantic_completion_status": semantic_completion_status or MISSING_UNAVAILABLE,
        "semantic_acceptability": semantic_acceptability or MISSING_UNAVAILABLE,
        "mess_restoration_rate": score.get("mess_restoration_rate", MISSING_UNAVAILABLE),
        "disturbance_count": score.get("disturbance_count", MISSING_UNAVAILABLE),
    }


def _map_build_private_goal_reference(
    *,
    sample: EvalSample,
    run_dir: Path,
    run_result: dict[str, Any],
) -> dict[str, Any]:
    reference = dict(sample.private_goal_reference or {})
    if str(run_result.get("backend") or "") != "molmospaces_subprocess":
        return reference
    truth = _molmospaces_fixture_truth_from_backend_state(
        run_dir / "molmospaces_backend_state.json"
    )
    if truth:
        reference["simulator_fixture_truth"] = truth
    return reference


def _molmospaces_fixture_truth_from_backend_state(path: Path) -> dict[str, Any]:
    state, error = _load_optional_json_mapping(path)
    if error or not state:
        return {}
    receptacles = state.get("receptacles") if isinstance(state.get("receptacles"), dict) else {}
    rows = []
    categories = set()
    for raw_id, raw_fixture in receptacles.items():
        if not isinstance(raw_fixture, dict):
            continue
        category = str(raw_fixture.get("category") or raw_fixture.get("name") or "").strip()
        room_id = str(
            raw_fixture.get("room_id")
            or raw_fixture.get("room_area")
            or _room_id_for_receptacle_id(str(raw_id))
        ).strip()
        if not category or not room_id:
            continue
        categories.add(category)
        rows.append(
            {
                "category": category,
                "waypoint_ids": [f"{room_id}_inspection"],
            }
        )
    merged: dict[str, set[str]] = {}
    for row in rows:
        key = _normalized_truth_category(row["category"])
        merged.setdefault(key, set()).update(row["waypoint_ids"])
    return {
        "schema": "map_build_simulator_fixture_truth_v1",
        "truth_scope": "grader_only",
        "truth_source": "molmospaces_backend_state.receptacles",
        "pose_semantics": "best_view_waypoint_only",
        "categories": sorted(categories),
        "best_view_waypoint_truth": [
            {"category": category, "waypoint_ids": sorted(waypoint_ids)}
            for category, waypoint_ids in sorted(merged.items())
        ],
    }


def _room_id_for_receptacle_id(value: str) -> str:
    parts = str(value or "").rsplit("_", 3)
    if parts and parts[-1].isdigit():
        return f"room_{parts[-1]}"
    return ""


def _normalized_truth_category(value: Any) -> str:
    return str(value or "").strip().lower()


def _sampler_admission_grader(*, sample: EvalSample) -> dict[str, Any]:
    config = sample.grader_config or {}
    admission = config.get("sampler_admission")
    if not isinstance(admission, dict):
        return {"status": "not_applicable"}
    room_count = _int_value(admission.get("room_count"))
    waypoint_count = _int_value(admission.get("waypoint_count"))
    category_provenance = str(admission.get("category_provenance") or "")
    forbidden_provenance = {
        "heuristic_room_label",
        "heuristic_room_count",
        "room_area_fallback",
    }
    failures: list[str] = []
    if room_count < 3:
        failures.append("fewer_than_three_public_rooms")
    if waypoint_count < room_count:
        failures.append("missing_room_waypoints")
    if category_provenance in forbidden_provenance or category_provenance not in {
        "source_metadata",
        "prepared_visual_label_manifest",
    }:
        failures.append("untrusted_room_category_provenance")
    return {
        "status": "failed" if failures else "passed",
        "failure_class": "map_actionability_failure" if failures else MISSING_NOT_APPLICABLE,
        "failures": failures,
        "scene_family": str(admission.get("scene_family") or ""),
        "scene_split": str(admission.get("scene_split") or ""),
        "scene_source": str(admission.get("scene_source") or ""),
        "scene_index": admission.get("scene_index", MISSING_UNAVAILABLE),
        "room_count": room_count,
        "waypoint_count": waypoint_count,
        "category_provenance": category_provenance,
        "category_manifest": str(admission.get("category_manifest") or ""),
        "generator_version": str(admission.get("generator_version") or ""),
    }


def _efficiency_grader(*, run_dir: Path, run_result: dict[str, Any]) -> dict[str, Any]:
    tool_counts = (
        run_result.get("tool_event_counts")
        if isinstance(run_result.get("tool_event_counts"), dict)
        else {}
    )
    live_status, live_status_error = _merged_live_status(run_dir=run_dir, run_result=run_result)
    live_timing_path = run_dir / "live_timing.json"
    live_timing, live_timing_error = _load_optional_json_mapping(live_timing_path)
    timing_payload = dict(run_result)
    if live_timing:
        timing_payload["live_timing"] = live_timing
        timing_payload["runner_wall_time_s"] = _live_wall_time_s(live_timing)
    model_attempt_summary = _model_attempt_summary(timing_payload)
    trace_events, trace_errors = _read_trace_events_with_errors(run_dir / "trace.jsonl")
    source_errors = [
        error
        for error in (
            _json_source_error(run_dir / "live_status.json", live_status_error),
            _json_source_error(live_timing_path, live_timing_error),
        )
        if error
    ]
    return {
        "status": "failed" if source_errors or trace_errors else "passed",
        "failure_class": (
            "artifact_missing" if source_errors or trace_errors else MISSING_NOT_APPLICABLE
        ),
        "source_errors": source_errors,
        "trace_parse_errors": trace_errors,
        "tool_event_count": sum(_int_value(value) for value in tool_counts.values()),
        "tool_call_count": sum(
            _int_value(value) for key, value in tool_counts.items() if str(key).endswith(":request")
        ),
        "tool_event_counts": dict(tool_counts),
        "comparison_tool_counts": _comparison_tool_counts(tool_counts),
        "first_relevant_evidence": _first_relevant_evidence(trace_events),
        "first_actionable_object_discovery": _first_actionable_object_discovery(
            trace_events,
            run_result=run_result,
        ),
        "prior_use_verdict": _prior_use_verdict(run_result, trace_events=trace_events),
        "wall_time_s": _first_available_number(
            timing_payload,
            (
                "wall_time_s",
                "elapsed_s",
                "duration_s",
                "runner_wall_time_s",
                "total_elapsed_s",
            ),
        ),
        "live_status": {
            "phase": str(live_status.get("phase") or MISSING_UNAVAILABLE),
            "exit_status": live_status.get("exit_status", MISSING_UNAVAILABLE),
            "reason": str(live_status.get("reason") or MISSING_UNAVAILABLE),
            "provider_reason": str(live_status.get("provider_reason") or MISSING_UNAVAILABLE),
            "retryable": live_status.get("retryable", MISSING_UNAVAILABLE),
        },
        "model_attempt_summary": model_attempt_summary,
    }


def _open_ended_grader(
    *,
    sample: EvalSample,
    run_dir: Path,
    run_result: dict[str, Any],
) -> dict[str, Any]:
    if sample.intent != "open-ended":
        return {
            "status": "not_applicable",
            "completion_claim_present": MISSING_NOT_APPLICABLE,
            "artifact_readiness": MISSING_NOT_APPLICABLE,
            "semantic_satisfaction_status": "advisory_not_applicable",
        }
    claim = run_result.get("agent_completion_claim")
    claim_present = isinstance(claim, dict) and bool(claim.get("completion_summary"))
    required = ("run_result.json", "report.html", "trace.jsonl", "goal_contract.json")
    missing = [name for name in required if not (run_dir / name).exists()]
    artifact_ready = not missing
    advisory = (
        run_result.get("advisory_evaluation")
        if isinstance(run_result.get("advisory_evaluation"), dict)
        else {}
    )
    advisory_error = ""
    if not advisory:
        advisory_path = run_dir / "advisory_evaluation.json"
        advisory, advisory_error = _load_optional_json_mapping(advisory_path)
    advisory_available = bool(advisory)
    semantic_status = "advisory_available" if advisory_available else "advisory_unavailable"
    config = sample.grader_config or {}
    predicate_config = config.get("success_predicate")
    predicate = _open_ended_success_predicate(
        predicate_config if isinstance(predicate_config, dict) else {},
        run_dir=run_dir,
    )
    source_errors = [
        error
        for error in (
            _json_source_error(run_dir / "advisory_evaluation.json", advisory_error),
            *_open_ended_goal_contract_source_errors(run_dir),
            *(predicate.get("source_errors") or []),
        )
        if error
    ]
    if source_errors:
        semantic_status = "source_error"
    hard_passed = claim_present and artifact_ready
    if predicate["authoritative"]:
        hard_passed = hard_passed and predicate["passed"]
    if source_errors:
        hard_passed = False
    return {
        "status": "passed" if hard_passed else "failed",
        "failure_class": (
            MISSING_NOT_APPLICABLE
            if hard_passed
            else (
                "artifact_missing"
                if source_errors
                else (
                    "private_goal_not_satisfied"
                    if claim_present and artifact_ready and predicate["authoritative"]
                    else "agent_no_completion_claim"
                )
            )
        ),
        "open_ended_category": str(config.get("open_ended_category") or MISSING_UNAVAILABLE),
        "expected_goal_outcome": str(config.get("expected_goal_outcome") or MISSING_UNAVAILABLE),
        "completion_claim_present": claim_present,
        "artifact_readiness": "ready" if artifact_ready else "missing",
        "missing_artifacts": missing,
        "semantic_satisfaction_status": semantic_status,
        "semantic_satisfaction_authoritative": bool(
            config.get("semantic_satisfaction_authoritative") is True
        ),
        "success_predicate": predicate,
        "source_errors": source_errors,
    }


def _open_ended_goal_contract_source_errors(run_dir: Path) -> tuple[dict[str, str], ...]:
    path = run_dir / "goal_contract.json"
    if not path.exists():
        return ()
    contract, reason = _load_optional_json_mapping(path)
    if reason:
        return (_json_source_error(path, reason),)
    errors: list[dict[str, str]] = []
    if contract.get("schema") != "roboclaws_goal_contract_v1":
        errors.append({"path": str(path), "reason": "invalid_goal_contract_schema"})
    for key in ("surface", "intent", "normalized_goal", "goal_scope"):
        if not str(contract.get(key) or "").strip():
            errors.append({"path": str(path), "reason": f"missing_goal_contract_{key}"})
    return tuple(errors)


def _open_ended_success_predicate(
    config: dict[str, Any],
    *,
    run_dir: Path,
) -> dict[str, Any]:
    predicate_id = str(config.get("predicate_id") or "completion_claim")
    authoritative = bool(config.get("authoritative") is True)
    runtime_map_path = run_dir / "runtime_metric_map.json"
    runtime_map, runtime_map_error = _load_optional_json_mapping(runtime_map_path)
    trace_events, _trace_errors = _read_trace_events_with_errors(run_dir / "trace.jsonl")
    if runtime_map_error:
        return {
            "predicate_id": predicate_id,
            "authoritative": authoritative,
            "passed": False,
            "source_error": True,
            "source_errors": [_json_source_error(runtime_map_path, runtime_map_error)],
            "evidence": {},
        }
    source_errors = _runtime_map_predicate_source_errors(
        predicate_id,
        runtime_map=runtime_map,
        runtime_map_path=runtime_map_path,
    )
    if source_errors:
        return {
            "predicate_id": predicate_id,
            "authoritative": authoritative,
            "passed": False,
            "source_error": True,
            "source_errors": source_errors,
            "evidence": {},
        }
    if predicate_id == "completion_claim":
        return {
            "predicate_id": predicate_id,
            "authoritative": authoritative,
            "passed": True,
            "source_errors": [],
            "evidence": {},
        }
    if predicate_id == "public_anchor_observed":
        return _public_anchor_observed_predicate(
            config,
            runtime_map=runtime_map,
            trace_events=trace_events,
            authoritative=authoritative,
        )
    if predicate_id == "waypoint_or_area_visited":
        return _waypoint_or_area_visited_predicate(
            config,
            runtime_map=runtime_map,
            trace_events=trace_events,
            authoritative=authoritative,
        )
    if predicate_id == "observed_category_present":
        return _observed_category_present_predicate(
            config,
            runtime_map=runtime_map,
            authoritative=authoritative,
        )
    return {
        "predicate_id": predicate_id,
        "authoritative": authoritative,
        "passed": False,
        "failure": "unknown_open_ended_success_predicate",
        "evidence": {},
    }


def _public_anchor_observed_predicate(
    config: dict[str, Any],
    *,
    runtime_map: dict[str, Any],
    trace_events: list[dict[str, Any]],
    authoritative: bool,
) -> dict[str, Any]:
    anchor_id = str(config.get("anchor_id") or "")
    room_id = str(config.get("room_id") or "")
    anchors = [
        anchor
        for anchor in _list_of_mappings(runtime_map.get("public_semantic_anchors"))
        if (not anchor_id or str(anchor.get("anchor_id") or "") == anchor_id)
        and (not room_id or str(anchor.get("room_id") or "") == room_id)
    ]
    observed_rooms = _observed_room_ids(runtime_map=runtime_map, trace_events=trace_events)
    passed = bool(anchors) and (not room_id or room_id in observed_rooms)
    return {
        "predicate_id": "public_anchor_observed",
        "authoritative": authoritative,
        "passed": passed,
        "failure": "" if passed else "required_public_anchor_not_observed",
        "evidence": {
            "anchor_id": anchor_id,
            "room_id": room_id,
            "matching_anchor_count": len(anchors),
            "observed_room_ids": sorted(observed_rooms),
        },
    }


def _waypoint_or_area_visited_predicate(
    config: dict[str, Any],
    *,
    runtime_map: dict[str, Any],
    trace_events: list[dict[str, Any]],
    authoritative: bool,
) -> dict[str, Any]:
    waypoint_id = str(config.get("waypoint_id") or "")
    room_id = str(config.get("room_id") or "")
    anchor_id = str(config.get("anchor_id") or "")
    visited_waypoints = _visited_waypoint_ids(runtime_map=runtime_map, trace_events=trace_events)
    observed_rooms = _observed_room_ids(runtime_map=runtime_map, trace_events=trace_events)
    anchors = _list_of_mappings(runtime_map.get("public_semantic_anchors"))
    anchor_present = any(
        (not anchor_id or str(anchor.get("anchor_id") or "") == anchor_id)
        and (not waypoint_id or str(anchor.get("waypoint_id") or "") == waypoint_id)
        and (not room_id or str(anchor.get("room_id") or "") == room_id)
        for anchor in anchors
    )
    waypoint_visited = not waypoint_id or waypoint_id in visited_waypoints
    passed = (
        waypoint_visited
        and (not room_id or room_id in observed_rooms)
        and (not anchor_id or anchor_present or waypoint_visited)
    )
    return {
        "predicate_id": "waypoint_or_area_visited",
        "authoritative": authoritative,
        "passed": passed,
        "failure": "" if passed else "required_waypoint_or_area_not_visited",
        "evidence": {
            "anchor_id": anchor_id,
            "waypoint_id": waypoint_id,
            "room_id": room_id,
            "anchor_present": anchor_present,
            "visited_waypoint_ids": sorted(visited_waypoints),
            "observed_room_ids": sorted(observed_rooms),
        },
    }


def _observed_category_present_predicate(
    config: dict[str, Any],
    *,
    runtime_map: dict[str, Any],
    authoritative: bool,
) -> dict[str, Any]:
    category = str(config.get("category") or "").lower()
    observed = _list_of_mappings(runtime_map.get("observed_objects"))
    matching = [
        item
        for item in observed
        if not category
        or category
        in {
            str(item.get("category") or "").lower(),
            str(item.get("label") or "").lower(),
            str(item.get("query") or "").lower(),
        }
    ]
    passed = bool(matching)
    return {
        "predicate_id": "observed_category_present",
        "authoritative": authoritative,
        "passed": passed,
        "failure": "" if passed else "required_observed_category_missing",
        "evidence": {
            "category": category,
            "matching_observed_count": len(matching),
        },
    }


def _visited_waypoint_ids(
    *,
    runtime_map: dict[str, Any],
    trace_events: list[dict[str, Any]],
) -> set[str]:
    visited: set[str] = set()
    summary = runtime_map.get("target_search_summary")
    if isinstance(summary, dict):
        viewpoint_budget = summary.get("viewpoint_budget")
        if isinstance(viewpoint_budget, dict):
            visited.update(
                str(item) for item in viewpoint_budget.get("observed_waypoint_ids") or []
            )
        for observation in _list_of_mappings(summary.get("inspection_observations")):
            waypoint_id = str(observation.get("waypoint_id") or "")
            if waypoint_id:
                visited.add(waypoint_id)
    for candidate in _list_of_mappings(runtime_map.get("generated_exploration_candidates")):
        if candidate.get("visited") is True and candidate.get("waypoint_id"):
            visited.add(str(candidate["waypoint_id"]))
    for event in trace_events:
        if event.get("tool") == "navigate_to_waypoint" and event.get("event") == "request":
            request = event.get("request") if isinstance(event.get("request"), dict) else {}
            waypoint_id = str(request.get("waypoint_id") or "")
            if waypoint_id:
                visited.add(waypoint_id)
    return visited


def _observed_room_ids(
    *,
    runtime_map: dict[str, Any],
    trace_events: list[dict[str, Any]],
) -> set[str]:
    rooms: set[str] = set()
    summary = runtime_map.get("target_search_summary")
    if isinstance(summary, dict):
        for observation in _list_of_mappings(summary.get("inspection_observations")):
            room_id = str(observation.get("room_id") or "")
            if room_id:
                rooms.add(room_id)
    waypoint_rooms = {
        str(candidate.get("waypoint_id") or ""): str(candidate.get("room_id") or "")
        for candidate in _list_of_mappings(runtime_map.get("generated_exploration_candidates"))
    }
    for waypoint_id in _visited_waypoint_ids(runtime_map=runtime_map, trace_events=trace_events):
        room_id = waypoint_rooms.get(waypoint_id, "")
        if room_id:
            rooms.add(room_id)
    return rooms


def _runtime_map_predicate_source_errors(
    predicate_id: str,
    *,
    runtime_map: dict[str, Any],
    runtime_map_path: Path,
) -> list[dict[str, str]]:
    reasons: list[str] = []
    if predicate_id in {"public_anchor_observed", "waypoint_or_area_visited"}:
        reasons.extend(
            _runtime_map_list_field_errors(
                runtime_map,
                ("public_semantic_anchors", "generated_exploration_candidates"),
            )
        )
        reasons.extend(_target_search_summary_source_errors(runtime_map))
    if predicate_id == "observed_category_present":
        reasons.extend(_runtime_map_list_field_errors(runtime_map, ("observed_objects",)))
    return [_json_source_error(runtime_map_path, reason) for reason in reasons]


def _runtime_map_list_field_errors(payload: dict[str, Any], keys: tuple[str, ...]) -> list[str]:
    errors: list[str] = []
    for key in keys:
        _value, reason = _optional_list_value(payload, key)
        if reason:
            errors.append(reason)
    return errors


def _target_search_summary_source_errors(runtime_map: dict[str, Any]) -> list[str]:
    if (
        "target_search_summary" not in runtime_map
        or runtime_map.get("target_search_summary") is None
    ):
        return []
    summary = runtime_map.get("target_search_summary")
    if not isinstance(summary, dict):
        return ["target_search_summary:invalid_json_object"]
    errors = _runtime_map_list_field_errors(summary, ("inspection_observations",))
    viewpoint_budget = summary.get("viewpoint_budget")
    if viewpoint_budget is not None:
        if not isinstance(viewpoint_budget, dict):
            errors.append("target_search_summary.viewpoint_budget:invalid_json_object")
        else:
            errors.extend(
                _runtime_map_list_field_errors(
                    viewpoint_budget,
                    ("observed_waypoint_ids",),
                )
            )
    return errors


def _list_of_mappings(value: Any) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        return []
    return [item for item in value if isinstance(item, dict)]


def _optional_list_value(payload: dict[str, Any], key: str) -> tuple[list[Any], str]:
    if key not in payload or payload.get(key) is None:
        return [], ""
    value = payload.get(key)
    if not isinstance(value, list):
        return [], f"{key}:invalid_json_array"
    return value, ""


def _model_attempt_summary(run_result: dict[str, Any]) -> dict[str, Any]:
    for key in ("model_attempt_summary", "model_service_summary", "live_timing"):
        value = run_result.get(key)
        if isinstance(value, dict):
            return _compact_model_attempt_summary(value)
    return {
        "attempt_count": MISSING_UNAVAILABLE,
        "success_count": MISSING_UNAVAILABLE,
        "failure_count": MISSING_UNAVAILABLE,
        "provider_reasons": {},
    }


def _compact_model_attempt_summary(value: dict[str, Any]) -> dict[str, Any]:
    live_summary = _model_attempt_summary_from_live_timing(value)
    if live_summary:
        return live_summary
    attempts = _int_or_missing(
        value.get("attempt_count")
        or value.get("model_service_attempt_count")
        or value.get("total_attempts")
    )
    successes = _int_or_missing(
        value.get("success_count")
        or value.get("model_service_success_count")
        or value.get("successful_attempts")
    )
    failures = _int_or_missing(
        value.get("failure_count")
        or value.get("model_service_failure_count")
        or value.get("failed_attempts")
    )
    provider_reasons = value.get("provider_reasons")
    if not isinstance(provider_reasons, dict):
        provider_reasons = {}
    return {
        "attempt_count": attempts,
        "success_count": successes,
        "failure_count": failures,
        "provider_reasons": dict(provider_reasons),
    }


def _model_attempt_summary_from_live_timing(value: dict[str, Any]) -> dict[str, Any]:
    fallback = _nested_mapping(
        value,
        "timeline",
        "latency_attribution",
        "model_service_fallback_metrics",
    )
    attempts_list = value.get("openai_agents_attempts")
    if not isinstance(attempts_list, list):
        attempts_list = []
    if fallback:
        attempt_count = _int_or_missing(
            fallback.get("attempt_event_count")
            or fallback.get("attempt_count")
            or len(attempts_list)
        )
        success_count = _int_or_missing(
            fallback.get("success_event_count")
            or fallback.get("success_count")
            or _live_attempt_status_count(attempts_list, "finished")
        )
        failure_count = _int_or_missing(
            fallback.get("failure_event_count")
            or fallback.get("failure_count")
            or _live_attempt_failure_count(attempts_list)
        )
        provider_reasons = fallback.get("provider_reasons")
        if not isinstance(provider_reasons, dict):
            provider_reasons = {}
        return {
            "attempt_count": attempt_count,
            "success_count": success_count,
            "failure_count": failure_count,
            "provider_reasons": dict(provider_reasons),
        }
    if attempts_list:
        return {
            "attempt_count": len(attempts_list),
            "success_count": _live_attempt_status_count(attempts_list, "finished"),
            "failure_count": _live_attempt_failure_count(attempts_list),
            "provider_reasons": _live_provider_reasons(attempts_list),
        }
    return {}


def _merged_live_status(*, run_dir: Path, run_result: dict[str, Any]) -> tuple[dict[str, Any], str]:
    live_status = (
        run_result.get("live_status") if isinstance(run_result.get("live_status"), dict) else {}
    )
    sidecar, sidecar_error = _load_optional_json_mapping(run_dir / "live_status.json")
    return {**sidecar, **live_status}, sidecar_error


def _live_wall_time_s(live_timing: dict[str, Any]) -> Any:
    runner_timing = _nested_mapping(live_timing, "runner_timing")
    for payload in (
        runner_timing,
        _nested_mapping(live_timing, "timeline"),
        live_timing,
    ):
        value = _first_available_number(
            payload,
            ("total_elapsed_s", "accounted_elapsed_s", "runner_wall_time_s"),
        )
        if value != MISSING_UNAVAILABLE:
            return value
    return MISSING_UNAVAILABLE


def _nested_mapping(payload: dict[str, Any], *keys: str) -> dict[str, Any]:
    current: Any = payload
    for key in keys:
        if not isinstance(current, dict):
            return {}
        current = current.get(key)
    return current if isinstance(current, dict) else {}


def _live_attempt_status_count(attempts: list[Any], phase: str) -> int:
    return sum(
        1
        for attempt in attempts
        if isinstance(attempt, dict)
        and (
            str(attempt.get("phase") or "") == phase
            or (phase == "finished" and attempt.get("exit_status") == 0)
        )
    )


def _live_attempt_failure_count(attempts: list[Any]) -> int:
    return sum(
        1
        for attempt in attempts
        if isinstance(attempt, dict)
        and (
            attempt.get("exit_status") not in {None, 0}
            or str(attempt.get("phase") or "") == "failed"
        )
    )


def _live_provider_reasons(attempts: list[Any]) -> dict[str, int]:
    reasons: dict[str, int] = {}
    for attempt in attempts:
        if not isinstance(attempt, dict):
            continue
        reason = str(attempt.get("provider_reason") or attempt.get("reason") or "").strip()
        if reason:
            reasons[reason] = reasons.get(reason, 0) + 1
    return reasons


def _first_available_number(payload: dict[str, Any], keys: tuple[str, ...]) -> float | str:
    for key in keys:
        value = payload.get(key)
        try:
            return round(float(value), 3)
        except (TypeError, ValueError):
            continue
    return MISSING_UNAVAILABLE


def _int_or_missing(value: Any) -> int | str:
    if value is None:
        return MISSING_UNAVAILABLE
    try:
        return int(value)
    except (TypeError, ValueError):
        return MISSING_UNAVAILABLE


def _status_from_graders(grader_outputs: dict[str, Any]) -> tuple[str, str]:
    ordered_failures = (
        ("artifacts", "artifact_missing"),
        ("privacy", "private_truth_leak"),
        ("trajectory", "trajectory_policy_violation"),
        (long_horizon_contract.LONG_HORIZON_GRADER_NAME, "private_goal_not_satisfied"),
        ("sampler_admission", "map_actionability_failure"),
        ("open_ended", "agent_no_completion_claim"),
        ("outcome", "private_goal_not_satisfied"),
        ("efficiency", "artifact_missing"),
    )
    for grader_name, failure_class in ordered_failures:
        grader = grader_outputs.get(grader_name, {})
        if grader.get("status") == "failed":
            return "failed", str(grader.get("failure_class") or failure_class)
    long_horizon = grader_outputs.get(long_horizon_contract.LONG_HORIZON_GRADER_NAME, {})
    if long_horizon.get("status") == "inconclusive":
        return "inconclusive", str(long_horizon.get("failure_class") or "grader_inconclusive")
    return "passed", MISSING_NOT_APPLICABLE


def _metrics_from_graders(
    grader_outputs: dict[str, Any],
    *,
    status: str,
    run_result: dict[str, Any],
) -> dict[str, Any]:
    score = run_result.get("score") if isinstance(run_result.get("score"), dict) else {}
    efficiency = grader_outputs["efficiency"]
    return {
        "pass": 1.0 if status == "passed" else 0.0,
        "private_truth_leak_count": grader_outputs["privacy"]["private_truth_leak_count"],
        "trajectory_policy_violation_count": grader_outputs["trajectory"]["violation_count"],
        "mess_restoration_rate": score.get("mess_restoration_rate", MISSING_UNAVAILABLE),
        "open_ended_artifact_readiness": grader_outputs["open_ended"].get(
            "artifact_readiness",
            MISSING_NOT_APPLICABLE,
        ),
        **long_horizon_contract.metric_fields(grader_outputs),
        "tool_event_count": efficiency["tool_event_count"],
        "tool_call_count": efficiency.get("tool_call_count", 0),
        "tool_event_counts": efficiency.get("tool_event_counts", {}),
        "comparison_tool_counts": efficiency.get("comparison_tool_counts", {}),
        "first_relevant_evidence": efficiency.get("first_relevant_evidence", {}),
        "first_actionable_object_discovery": efficiency.get(
            "first_actionable_object_discovery",
            {},
        ),
        "prior_use_verdict": efficiency.get("prior_use_verdict", "prior_ignored"),
        "wall_time_s": efficiency.get("wall_time_s", MISSING_UNAVAILABLE),
        "model_attempt_summary": efficiency.get(
            "model_attempt_summary",
            {},
        ),
    }


def _comparison_tool_counts(tool_counts: dict[str, Any]) -> dict[str, int]:
    return {
        tool: int(tool_counts.get(f"{tool}:request") or 0)
        for tool in (
            "observe",
            "adjust_camera",
            "navigate_to_waypoint",
            "navigate_to_relative_pose",
        )
    }


def _first_relevant_evidence(trace_events: list[dict[str, Any]]) -> dict[str, Any]:
    for index, event in enumerate(trace_events, start=1):
        if event.get("event") != "response":
            continue
        if event.get("tool") not in {
            "observe",
            "resolve_target_query",
            "declare_visual_candidates",
        }:
            continue
        return {
            "step": index,
            "tool": str(event.get("tool") or ""),
            "wallclock_elapsed": event.get("wallclock_elapsed", MISSING_UNAVAILABLE),
        }
    return {"step": MISSING_UNAVAILABLE, "tool": MISSING_UNAVAILABLE}


def _first_actionable_object_discovery(
    trace_events: list[dict[str, Any]],
    *,
    run_result: dict[str, Any],
) -> dict[str, Any]:
    for index, event in enumerate(trace_events, start=1):
        if event.get("event") != "response" or event.get("tool") != "observe":
            continue
        response = event.get("response") if isinstance(event.get("response"), dict) else event
        for detection in _list_of_mappings(response.get("visible_object_detections")):
            if str(detection.get("candidate_state") or "") == "navigation_authorized":
                return {
                    "step": index,
                    "tool": "observe",
                    "object_id": str(detection.get("object_id") or ""),
                    "wallclock_elapsed": event.get("wallclock_elapsed", MISSING_UNAVAILABLE),
                }
    observed = (
        run_result.get("runtime_metric_map", {}).get("observed_objects")
        if isinstance(run_result.get("runtime_metric_map"), dict)
        else []
    )
    for item in _list_of_mappings(observed):
        if str(item.get("actionability") or "") == "actionable":
            return {
                "step": MISSING_UNAVAILABLE,
                "tool": "runtime_metric_map",
                "object_id": str(item.get("object_id") or ""),
            }
    return {"step": MISSING_UNAVAILABLE, "tool": MISSING_UNAVAILABLE}


def _prior_use_verdict(
    run_result: dict[str, Any],
    *,
    trace_events: list[dict[str, Any]],
) -> str:
    prior = (
        run_result.get("runtime_metric_map_prior")
        if isinstance(run_result.get("runtime_metric_map_prior"), dict)
        else {}
    )
    if not prior.get("loaded"):
        return "prior_ignored"
    runtime_map = (
        run_result.get("runtime_metric_map")
        if isinstance(run_result.get("runtime_metric_map"), dict)
        else {}
    )
    observed_objects = _list_of_mappings(runtime_map.get("observed_objects"))
    if any(str(item.get("freshness") or "") == "prior" for item in observed_objects):
        unsafe = any(
            str(item.get("actionability") or "") == "actionable"
            for item in observed_objects
            if str(item.get("freshness") or "") == "prior"
        )
        if unsafe:
            return "unsafe_prior_use"
    if any(item.get("prior_match_basis") for item in observed_objects):
        return "movable_hint_rechecked"
    anchors = _list_of_mappings(runtime_map.get("public_semantic_anchors"))
    if anchors and int(prior.get("anchor_prior_count") or 0) > 0:
        return "stable_anchor_used"
    target_queries = [
        event
        for event in trace_events
        if event.get("tool") == "resolve_target_query" and event.get("event") == "response"
    ]
    if target_queries:
        return "stable_anchor_used"
    return "prior_ignored"


def _blocked_result_from_exception(trial: EvalTrial, exc: Exception) -> EvalResult:
    failure_class = _failure_class_from_exception(exc)
    blocked = failure_class in {"environment_blocked", "model_or_provider_unavailable"}
    runner_output: dict[str, Any] = {
        "status": "blocked" if blocked else "failed",
        "error_type": type(exc).__name__,
        "message": str(exc),
    }
    runner_output.update(live_exception_debug_fields(exc))
    return EvalResult.from_trial(
        trial,
        status="blocked" if blocked else "failed",
        failure_class=failure_class,
        grader_outputs={"runner": runner_output},
        artifacts={},
        metrics={"pass": 0.0},
        limitations=(*trial.limitations, "product_run_failed_before_grading"),
    )


def _failure_class_from_exception(exc: Exception) -> str:
    if isinstance(exc, LiveEvalTimeoutError) and exc.timeout_kind == "wall_clock_budget_exhausted":
        return "budget_exhausted"
    if isinstance(exc, (ImportError, ModuleNotFoundError, TimeoutError)):
        return "environment_blocked"
    message = str(exc).lower()
    if any(
        token in message
        for token in (
            "agent_sdk_turn_budget_exceeded",
            "budget_exhausted",
            "observe_budget_exhausted",
            "provider_context_budget_exceeded",
        )
    ):
        return "budget_exhausted"
    environment_tokens = ("no module named", "not installed", "unavailable", "timed out", "mcp")
    if "another interactive codex molmo cleanup session appears to be active" in message:
        return "environment_blocked"
    if any(token in message for token in environment_tokens):
        return "environment_blocked"
    artifact_tokens = (
        "generated_mess_count must be a non-negative integer",
        "launch_overrides.relocation_count must be a non-negative integer",
        "launch_overrides.scene_index must be a non-negative integer",
        "launch_overrides.scene_source must be a non-empty string",
        "runtime_map_prior must be a string path",
        "runtime_map_prior_from_sample must be a non-empty string",
        "eval_effective_run_dir",
        "live eval run_result",
        "invalid live eval json artifact",
        "live eval json artifact",
        "regrade_source",
        "regrade effective run dir",
        "regrade run_result",
    )
    if any(token in message for token in artifact_tokens):
        return "artifact_missing"
    tool_argument_tokens = (
        "invalid function arguments json",
        "invalid function arguments",
        "invalid_prompt",
        "tool_call_id",
    )
    if any(token in message for token in tool_argument_tokens):
        return "tool_argument_invalid"
    if "turn ended without done" in message:
        return "agent_no_completion_claim"
    provider_tokens = (
        "access_terminated_error",
        "provider_",
        "usage limit for this billing cycle",
        "model_service",
        "error code: 5",
        "error code: 429",
        "bad_response_status_code",
        "openai_error",
        "rate_limit",
    )
    if any(token in message for token in provider_tokens):
        return "model_or_provider_unavailable"
    return "harness_bug_unclassified"


def _failed_result_from_dependency(
    trial: EvalTrial,
    run_dir: Path,
    dependency_failure: dict[str, Any],
) -> EvalResult:
    failure_class = str(dependency_failure.get("failure_class") or "artifact_missing")
    blocked = failure_class in {"environment_blocked", "model_or_provider_unavailable"}
    artifacts = _artifact_paths(run_dir)
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
    artifacts = result.artifacts or _artifact_paths(run_dir)
    return {
        **artifacts,
        "source_status": result.status,
        "source_failure_class": result.failure_class,
        "source_sample_id": str(result.identity.get("sample_id") or ""),
    }


def _artifact_paths(run_dir: Path) -> dict[str, Any]:
    paths = {
        "run_dir": run_dir,
        "run_result": run_dir / "run_result.json",
        "report": run_dir / "report.html",
        "trace": run_dir / "trace.jsonl",
        "agent_view": run_dir / "agent_view.json",
        "runtime_metric_map": run_dir / "runtime_metric_map.json",
        "private_evaluation": run_dir / "private_evaluation.json",
    }
    return {key: str(path) for key, path in paths.items()}


def _read_trace_events_with_errors(path: Path) -> tuple[list[dict[str, Any]], list[str]]:
    rows, issues = collect_jsonl_object_rows(path, label="eval trace")
    errors: list[str] = []
    for issue in issues:
        if issue.kind == "invalid_json":
            errors.append(f"line {issue.line_number}: invalid_json:{issue.message}")
        elif issue.kind == "non_object":
            errors.append(f"line {issue.line_number}: invalid_json_object")
        else:
            errors.append(f"read_error:{issue.message}")
    return [row for _, row in rows], errors


def _load_optional_json_mapping(path: Path) -> tuple[dict[str, Any], str]:
    return _load_json_mapping(path, missing_reason="")


def _json_source_error(path: Path, reason: str) -> dict[str, str]:
    if not reason:
        return {}
    return {"path": str(path), "reason": reason}


def _required_json_artifact_source_errors(paths: dict[str, Path]) -> list[dict[str, str]]:
    errors: list[dict[str, str]] = []
    for name, path in paths.items():
        _payload, reason = _load_optional_json_mapping(path)
        if reason:
            errors.append(
                {
                    "artifact": name,
                    "path": str(path),
                    "reason": reason,
                }
            )
    return errors


def _load_required_json_mapping(path: Path) -> tuple[dict[str, Any], str]:
    return _load_json_mapping(path, missing_reason="missing")


def _load_json_mapping(path: Path, *, missing_reason: str) -> tuple[dict[str, Any], str]:
    try:
        return read_json_object(path, label="eval runner JSON artifact"), ""
    except FileNotFoundError:
        return {}, missing_reason
    except ValueError as exc:
        return {}, _json_artifact_error_reason(exc)
    except OSError as exc:
        return {}, f"read_error:{exc.strerror or exc}"


def _json_artifact_error_reason(exc: ValueError) -> str:
    cause = exc.__cause__
    if isinstance(cause, json.JSONDecodeError):
        return f"invalid_json:{cause.msg}"
    if "must contain a JSON object" in str(exc):
        return "invalid_json_object"
    return str(exc)


def _skill_name(sample: EvalSample) -> str:
    if sample.surface == "household-world":
        return "household-world"
    return MISSING_UNAVAILABLE


def _mcp_profile(sample: EvalSample) -> str:
    if long_horizon_contract.manipulation_required(sample, sample.intent == "cleanup"):
        return "household_world+household_manipulation"
    return "household_world+household_episode"


def _tool_surface(sample: EvalSample) -> tuple[str, ...]:
    if long_horizon_contract.manipulation_required(sample, sample.intent == "cleanup"):
        return ("metric_map", "observe", "navigate", "pick", "place", "done")
    return ("metric_map", "observe", "done")


def _budget_steps(budget: str) -> int | str:
    return {"smoke": 50, "focused": 100}.get(budget, MISSING_UNAVAILABLE)


def _path_token(value: str) -> str:
    return str(value).replace("/", "_").replace(".", "_")


def _default_run_stamp() -> str:
    return f"{time.strftime('%Y%m%dT%H%M%S')}-{os.getpid()}-{time.time_ns()}"


def _int_value(value: Any) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return 0


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
